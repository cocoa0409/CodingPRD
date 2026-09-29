"""The two expected-version guards read against a write on a neighbouring dimension, the
posture band's inclusive floor carried all the way into a priced certificate, and the
audit-history selector when closes and on-site windows disagree.
"""

from test_helpers import (
    ApiErrorId,
    AssayMethod,
    AuditType,
    CaRejectionReason,
    Decision,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    MarkTier,
    NcCategory,
    NcSeverity,
    NcSourceType,
    RiskClass,
    close_audit,
    decide_corrective_action,
    make_admin_headers,
    make_applicant_contact_headers,
    make_auditor_headers,
    make_decision_maker_headers,
    make_reviewer_headers,
    raise_nonconformance,
    read_applicant,
    read_audit,
    read_facility,
    read_nonconformance,
    read_product,
    record_lot_test,
    setup_certification_ready_product,
    submit_corrective_action,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    start_audit,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
CA_DUE_ON = "2026-08-31T00:00:00Z"
PLAN_TEXT = "Reinstate the daily swab log"
AUDIT_OPENS = "2026-08-05T09:00:00Z"
AUDIT_CLOSES = "2026-08-05T17:00:00Z"
SECOND_AUDIT_OPENS = "2026-08-10T09:00:00Z"
SECOND_AUDIT_CLOSES = "2026-08-10T17:00:00Z"
LATE_CLOSE_DAY = "2026-08-11T00:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"
SURVEILLANCE_DUE_ON = "2027-08-06T00:00:00Z"

CLEAN_SITE = {
    "site_name": "Plant 9",
    "shared_equipment_present": False,
    "gluten_containing_operations": GlutenContainingOperations.NONE,
}
ONE_CLEAN_LINE = (
    IngredientSpec(
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=55,
        doc_expires_on=DOC_EXPIRES,
    ),
)


def test_a_label_approval_invalidates_the_version_the_plan_was_computed_against(api):
    """The label review touches the other product dimension entirely, and the version it
    consumed is still the one the plan activation offers, so the plan is refused 412.

    PRD: "If that value does not equal the product's current `version`, the request is
    rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412) and nothing whatsoever is persisted
    — no threshold, no sampling figure, no revision increment."
    PRD: "The two dimensions advance through separate operations and separate cascades;
    neither one reads or writes the other."

    Design: Corner/complexity_layers/testing_plan_with_the_pre_label_product_version_is_rejected_as_stale
    """
    context = setup_certification_ready_product(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        activate_plan=False,
        review_label_decision=Decision.APPROVE,
        mark_tier_granted=MarkTier.STANDARD,
        run_audit=False,
    )
    cleared_version = context.formula_review["version"]
    labelled = context.label_review
    assert context.formula_review["formula_status"] == "CLEARED"
    assert labelled["label_status"] == "APPROVED"
    assert labelled["version"] != cleared_version

    response = api.activate_testing_plan(
        context.product_id,
        make_reviewer_headers("rev-1"),
        expected_product_version=cleared_version,
    )
    validate_error(response, ApiErrorId.STALE_PRODUCT_VERSION, 412)

    row = read_product(api, context.product_id)
    assert row["version"] == labelled["version"]
    assert row["testing_plan_status"] == "NONE"
    assert row["testing_plan_revision"] == 0
    assert row["threshold_ppm"] is None
    assert row["sampling_lots_per_year"] is None
    assert row["sampling_exclusion_days"] is None


def test_a_revised_plan_answering_the_pre_rejection_version_is_refused(api):
    """The record is `CA_REJECTED`, which is a legal state for a plan, and the due date is
    weeks away, so the only fault is that the version predates the rejection.

    PRD: "A mismatch with the nonconformance's current `version` is rejected with
    `ERR_STALE_NONCONFORMANCE_VERSION` (HTTP 412) and leaves the record untouched; a
    successful submission increases `version` by 1."
    PRD: "Rejection is where the loop is bounded, and the order of operations decides the
    outcome: `ca_revision_count` is increased by 1 **first**, and only then is the branch
    chosen."

    Design: Corner/complexity_layers/corrective_action_plan_with_the_pre_rejection_version_is_rejected_as_stale
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    audit = schedule_audit(
        api,
        context.facility_id,
        onsite_start_at=CLOCK_START,
        onsite_end_at="2026-08-01T17:00:00Z",
    )
    start_audit(api, audit["id"])
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        raiser_user_id="rev-1",
        role="reviewer",
        source_type=NcSourceType.AUDIT,
        category=NcCategory.SANITATION,
        severity=NcSeverity.MAJOR,
        description="Swab log gap for the 2026-07 sanitation cycle",
        audit_id=audit["id"],
    )
    assert finding["ca_due_on"] == CA_DUE_ON

    submitted = submit_corrective_action(
        api,
        context.applicant_id,
        finding["id"],
        finding["version"],
        plan_text=PLAN_TEXT,
    )
    assert submitted["status"] == "CA_SUBMITTED"

    rejected = decide_corrective_action(
        api,
        finding["id"],
        decision=Decision.REJECT,
        reviewer_user_id="rev-2",
        ca_rejection_reason=CaRejectionReason.NO_VERIFICATION_EVIDENCE,
    )
    assert rejected["status"] == "CA_REJECTED"
    assert rejected["ca_revision_count"] == 1
    assert rejected["version"] != submitted["version"]

    response = api.submit_corrective_action_plan(
        finding["id"],
        make_applicant_contact_headers(context.applicant_id),
        expected_nonconformance_version=submitted["version"],
        ca_plan_text="Second attempt at the swab log remedy",
    )
    validate_error(response, ApiErrorId.STALE_NONCONFORMANCE_VERSION, 412)

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == "CA_REJECTED"
    assert row["ca_revision_count"] == 1
    assert row["ca_plan_text"] == PLAN_TEXT
    assert row["version"] == rejected["version"]
    assert read_applicant(api, context.applicant_id)["open_nc_penalty_points"] == 8


def test_forty_points_leaves_the_applicant_on_the_watch_floor_and_certifiable(api):
    """Five MAJOR findings deduct exactly 40 points, which lands the cycle score on the
    inclusive WATCH floor of 60 — a band that does not block — and the mark is issued and
    priced in full.

    PRD: "`compliance_posture` is banded from `posture_score_cycle`: a score of at least 85
    is `GOOD_STANDING`, a score from 60 up to but not including 85 is `WATCH`, and a score
    below 60 is `PROBATION`."
    PRD: "Step one computes `base_fee_cents` as 98000 cents of product base fee, plus 6000
    cents for each ingredient counted in the product's `linked_ingredient_count`, plus a
    further 45000 cents when the manufacturing facility has `shared_equipment_present` true
    and nothing extra when it is false."
    PRD: "The certificate's term and first surveillance date follow from `issued_on`:
    `expires_on` is 1095 days later — a three-year term — and `surveillance_due_on` is 365
    days later."

    Design: Corner/complexity_layers/five_major_findings_land_exactly_on_the_watch_floor_and_issuance_proceeds
    """
    context = setup_certification_ready_product(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
        audit_start_clock=AUDIT_OPENS,
        audit_close_clock=AUDIT_CLOSES,
    )
    planned = read_product(api, context.product_id)
    assert planned["threshold_ppm"] == 20
    assert planned["sampling_lots_per_year"] == 2

    set_clock(api, ISSUE_DAY)
    first_lot = None
    for index in range(1, 6):
        lot = record_lot_test(
            api,
            context.product_id,
            lot_code=f"RSL-L{index}",
            test_type=LotTestType.FOR_CAUSE,
            sample_collected_on=ISSUE_DAY,
            ppm_result=30.0,
            lab_method=AssayMethod.G12_ELISA,
        )
        first_lot = first_lot or lot
    assert first_lot["verdict"] == "FAIL"

    before = read_applicant(api, context.applicant_id)
    assert before["open_nc_penalty_points"] == 40
    assert before["posture_score_cycle"] == 60
    assert before["compliance_posture"] == "WATCH"
    assert before["current_cycle_started_on"] is None

    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=read_product(api, context.product_id)["version"],
    )
    assert response.status_code == 201, response.text
    certificate = response.json()["data"]

    assert certificate["product_id"] == context.product_id
    assert certificate["applicant_id"] == context.applicant_id
    assert certificate["status"] == "ISSUED"
    assert certificate["surveillance_status"] == "CURRENT"
    assert certificate["mark_tier_granted"] == MarkTier.STANDARD
    assert certificate["certified_threshold_ppm"] == 20
    assert certificate["issued_on"] == ISSUE_DAY
    assert certificate["issued_by_user_id"] == "dm-1"
    assert certificate["surveillance_due_on"] == SURVEILLANCE_DUE_ON
    assert certificate["base_fee_cents"] == 104000
    assert certificate["surveillance_surcharge_cents"] == 20800
    assert certificate["total_fee_cents"] == 124800
    assert certificate["fee_charged"] is True
    assert certificate["fee_refunded"] is False
    assert certificate["mark_usage_locked"] is False
    assert certificate["suspension_count"] == 0

    after = read_applicant(api, context.applicant_id)
    assert after["current_cycle_started_on"] == ISSUE_DAY
    assert after["open_nc_penalty_points"] == 40
    assert after["posture_score_cycle"] == 60
    assert after["posture_score_rolling_12m"] == 60
    assert after["compliance_posture"] == "WATCH"
    assert after["active_certified_product_count"] == 1
    assert after["fee_balance_cents"] == 124800


def test_the_facility_snapshot_follows_the_closing_order_not_the_window_order(api):
    """Two audits close in the reverse order of their on-site windows, and the facility
    carries the later close even though that audit's window was the earlier one.

    PRD: "`last_closed_audit_outcome` is the `status` of the audit of this facility with the
    greatest `closed_on` among those whose `status` is `CLOSED_PASS`, `CLOSED_CONDITIONAL` or
    `CLOSED_FAIL`, with ties broken by taking the audit with the earlier `created_at`; it
    reads `NONE` while no audit has ever closed there."
    PRD: "- **`CLOSED_PASS`** is selected when the provisional score is at least 90 **and**
    `critical_finding_count` is 0."

    Design: Corner/complexity_layers/facility_outcome_selector_takes_the_latest_closed_audit_not_the_earliest_window
    """
    context = setup_applicant_with_facility(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
    )
    assert context.facility["last_closed_audit_outcome"] == "NONE"

    early = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.INITIAL,
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
    )
    late = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.SURVEILLANCE,
        onsite_start_at=SECOND_AUDIT_OPENS,
        onsite_end_at=SECOND_AUDIT_CLOSES,
    )

    set_clock(api, AUDIT_OPENS)
    start_audit(api, early["id"])
    set_clock(api, SECOND_AUDIT_OPENS)
    start_audit(api, late["id"])

    set_clock(api, SECOND_AUDIT_CLOSES)
    closed_late = close_audit(api, late["id"])
    assert closed_late["status"] == "CLOSED_PASS"
    assert closed_late["closed_on"] == SECOND_AUDIT_CLOSES
    assert closed_late["provisional_score"] == 100

    set_clock(api, LATE_CLOSE_DAY)
    response = api.close_audit(
        early["id"],
        make_auditor_headers("aud-1"),
        shared_equipment_verified=True,
        air_handling_verified=True,
        sanitation_validation_reviewed=True,
    )
    assert response.status_code == 200, response.text
    closed_early = response.json()["data"]

    assert closed_early["id"] == early["id"]
    assert closed_early["status"] == "CLOSED_PASS"
    assert closed_early["closed_on"] == LATE_CLOSE_DAY
    assert closed_early["closed_by_user_id"] == "aud-1"
    assert closed_early["provisional_score"] == 100
    assert closed_early["final_score"] == 100
    assert closed_early["finding_count"] == 0
    assert closed_early["critical_finding_count"] == 0

    facility = read_facility(api, context.facility_id)
    assert facility["last_closed_audit_outcome"] == "CLOSED_PASS"
    assert facility["last_closed_audit_closed_on"] == LATE_CLOSE_DAY
    assert read_audit(api, late["id"])["closed_on"] == SECOND_AUDIT_CLOSES

    _rows, meta = validate_paginated(
        api.list_audits(
            make_admin_headers(), facility_id=context.facility_id, status="IN_PROGRESS"
        )
    )
    assert meta["total_count"] == 0
