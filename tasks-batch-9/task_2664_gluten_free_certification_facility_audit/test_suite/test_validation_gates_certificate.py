"""The issuance gates, read one at a time: the audit outcome that outranks the gates
below it, the label dimension on an otherwise complete file, the one-live-certificate
rule, and the posture band that closes the door on a probationary applicant.
"""

from test_helpers import (
    ApiErrorId,
    AssayMethod,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    MarkTier,
    RiskClass,
    create_product,
    make_admin_headers,
    make_decision_maker_headers,
    read_applicant,
    read_facility,
    read_product,
    record_lot_test,
    set_clock,
    setup_applicant_with_facility,
    setup_certification_ready_product,
    setup_issued_certificate,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
AUDIT_OPENS = "2026-08-05T09:00:00Z"
AUDIT_CLOSES = "2026-08-05T17:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"

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


def test_the_never_audited_site_blocks_issuance_ahead_of_every_later_gate(api):
    """Sanitation is validated but the site has never been audited, and although the
    product also has no formula, no plan and no label, the answer is the audit gate.

    PRD: "**Facility has passed an audit.** At issuance, the product's facility has
    `last_closed_audit_outcome` of `CLOSED_PASS` or `CLOSED_CONDITIONAL`; both `NONE` (no
    audit has ever closed there) and `CLOSED_FAIL` fail with
    `ERR_FACILITY_AUDIT_NOT_PASSED` (422)."
    PRD: "A freshly registered applicant starts in the cleanest possible position:
    `compliance_posture` is `GOOD_STANDING`, `open_nc_penalty_points` is 0,
    `active_certified_product_count`, `suspended_certificate_count` and
    `revoked_certificate_count` are all 0, `fee_balance_cents` is 0, both
    `posture_score_rolling_12m` and `posture_score_cycle` are 100, and
    `current_cycle_started_on` is null because no certificate has ever been issued to
    them."

    Design: Corner/validations/certificate_issuance_with_no_passed_facility_audit_is_rejected
    """
    context = setup_applicant_with_facility(
        api, clock=CLOCK_START, sanitation_validated_on=CLOCK_START, swab_ppm=2.0
    )
    assert context.facility["sanitation_validation_status"] == "VALIDATED"
    assert read_facility(api, context.facility_id)["last_closed_audit_outcome"] == "NONE"

    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
        requested_mark_tier=MarkTier.STANDARD,
    )
    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=product["id"],
        expected_product_version=product["version"],
    )
    validate_error(response, ApiErrorId.FACILITY_AUDIT_NOT_PASSED, 422)

    _rows, meta = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=product["id"])
    )
    assert meta["total_count"] == 0

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["current_cycle_started_on"] is None


def test_an_unreviewed_label_is_the_last_thing_standing_between_file_and_mark(api):
    """Every other issuance gate is satisfied — validated site, passing audit, approved
    ingredient, active plan — and the skipped label review alone refuses the mark.

    PRD: "**Label approved.** At issuance the product's `label_status` is `APPROVED` —
    otherwise `ERR_LABEL_NOT_APPROVED` (422)."
    PRD: "Label review is the other dimension, also a `CertificationReviewer` act, and it
    accepts `NOT_SUBMITTED`, `REJECTED` **and** `APPROVED` as starting states — an
    already-approved label can be re-reviewed and withdrawn."

    Design: Corner/validations/certificate_issuance_with_an_unapproved_label_is_rejected
    """
    context = setup_certification_ready_product(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        review_label_decision=None,
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
        audit_start_clock=AUDIT_OPENS,
        audit_close_clock=AUDIT_CLOSES,
    )
    assert context.ingredient["status"] == "APPROVED"
    assert context.audit["status"] == "CLOSED_PASS"

    set_clock(api, ISSUE_DAY)
    product = read_product(api, context.product_id)
    assert product["testing_plan_status"] == "ACTIVE"
    assert product["label_status"] == "NOT_SUBMITTED"

    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=product["version"],
    )
    validate_error(response, ApiErrorId.LABEL_NOT_APPROVED, 422)

    _rows, meta = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=context.product_id)
    )
    assert meta["total_count"] == 0

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["compliance_posture"] == "GOOD_STANDING"


def test_a_fresh_version_does_not_buy_a_second_mark_for_one_product(api):
    """The product version presented is re-read after the first issuance, so the 409 is
    the duplicate guard and not the concurrency gate, and the live certificate is not
    re-priced or re-dated.

    PRD: "**One live certificate per product.** No certificate of this `product_id`
    already has `status` of `ISSUED` or `SUSPENDED` — otherwise
    `ERR_DUPLICATE_ACTIVE_CERTIFICATE` (409)."
    PRD: "Issuance then increases the applicant's `active_certified_product_count`, sets
    the applicant's `current_cycle_started_on` if it was still null, recomputes the
    applicant's posture fields, and increases the product's `version` by 1."

    Design: Corner/validations/second_certificate_for_an_already_certified_product_is_rejected
    """
    context = setup_issued_certificate(
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
        issue_clock=ISSUE_DAY,
    )
    first = context.certificate
    assert first["status"] == "ISSUED"

    fresh_version = read_product(api, context.product_id)["version"]
    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=fresh_version,
    )
    validate_error(response, ApiErrorId.DUPLICATE_ACTIVE_CERTIFICATE, 409)

    rows, meta = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=context.product_id)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["issued_on"] == first["issued_on"]
    assert rows[0]["total_fee_cents"] == first["total_fee_cents"]

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 1
    assert applicant["suspended_certificate_count"] == 0


def test_forty_eight_open_points_put_the_applicant_below_the_watch_floor(api):
    """Six failing lots raise six MAJOR findings worth 8 points each, so the cycle score
    lands on 52 and the posture band alone refuses the issuance.

    PRD: "**Applicant posture permits the write.** The owning applicant's
    `compliance_posture` is neither `PROBATION` nor `SUSPENDED` — otherwise
    `ERR_APPLICANT_POSTURE_BLOCKED` (422). This guards certificate issuance, certificate
    reinstatement and change-notification filing."
    PRD: "A failing lot raises a finding automatically: a nonconformance is created with
    `source_type` of `LOT_TEST`, `category` of `THRESHOLD_EXCEEDANCE`, and a `severity` of
    `CRITICAL` when `ppm_result` is strictly more than twice `threshold_applied_ppm` and
    `MAJOR` otherwise — exactly twice the threshold is `MAJOR`, not `CRITICAL`."

    Design: Corner/validations/certificate_issuance_while_the_applicant_sits_on_probation_is_rejected
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
    assert context.audit["status"] == "CLOSED_PASS"
    assert read_product(api, context.product_id)["threshold_ppm"] == 20

    set_clock(api, ISSUE_DAY)
    first_lot = None
    for index in range(1, 7):
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
    assert first_lot["nonconformance_created"] is True

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 48
    assert applicant["posture_score_cycle"] == 52
    assert applicant["posture_score_rolling_12m"] == 52
    assert applicant["compliance_posture"] == "PROBATION"

    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=read_product(api, context.product_id)["version"],
    )
    validate_error(response, ApiErrorId.APPLICANT_POSTURE_BLOCKED, 422)

    assert read_facility(api, context.facility_id)["last_closed_audit_outcome"] == "CLOSED_PASS"
    _rows, critical = validate_paginated(
        api.list_nonconformances(
            make_admin_headers(), applicant_id=context.applicant_id, severity="CRITICAL"
        )
    )
    assert critical["total_count"] == 0
    _rows, still_open = validate_paginated(
        api.list_nonconformances(
            make_admin_headers(), applicant_id=context.applicant_id, status="OPEN"
        )
    )
    assert still_open["total_count"] == 6
    _rows, certificates = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=context.product_id)
    )
    assert certificates["total_count"] == 0
    assert read_applicant(api, context.applicant_id)["active_certified_product_count"] == 0
