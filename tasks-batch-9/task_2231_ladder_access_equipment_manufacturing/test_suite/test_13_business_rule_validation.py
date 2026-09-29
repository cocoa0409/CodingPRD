"""Business-constraint gates: production quantities, accreditation, evidence
coverage, remedy pairing, engineering thresholds and recall closure grounds."""

from test_helpers import (
    ApiErrorId,
    acknowledge_payload,
    api_client,
    create_approved_revision,
    create_campaign,
    create_consumer_registration_payload,
    create_draft_revision,
    create_joint_sample_payload,
    create_listing_body,
    create_product,
    create_recall_event_payload,
    create_test_bench,
    draft_recall,
    file_listing_record,
    freeze_design_payload,
    get_campaign_data,
    get_incident_data,
    get_lot_data,
    get_listing_record_data,
    get_product_data,
    get_recall_data,
    get_registration_data,
    get_revision_data,
    make_certification_body_headers,
    open_lot,
    plan_audit_campaign,
    record_passing_load_test,
    resolve_investigation_payload,
    review_design_revision_payload,
    run_campaign_to_passed,
    setup_frozen_product,
    setup_incident_under_investigation,
    setup_recall_in_progress,
    setup_released_lot,
    setup_retail_released_product,
    setup_shipping_product_with_registered_units,
    start_campaign_on_new_reservation,
    start_lot_production,
    start_production_payload,
    stop_ship_payload,
    submit_revision,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
CONSUMER = TEST_USERS["consumer_headers"]

FIBERGLASS = {"material": "FIBERGLASS_PULTRUSION"}


def test_produced_units_must_be_positive_and_within_the_plan():
    """PRD §3.6: "And the supplied `produced_units` must be greater than zero and
    no greater than the lot's `planned_units`, or the request is rejected with
    `ERR_PRODUCED_UNITS_INVALID`."

    Design: Corner/validations/produced_units_above_planned_units_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"], planned_units=500)

    above_plan = api_client.start_production(
        lot["id"], start_production_payload(501), SUPERVISOR
    )
    validate_error(above_plan, ApiErrorId.ERR_PRODUCED_UNITS_INVALID.value, 422)

    nothing_built = api_client.start_production(
        lot["id"], start_production_payload(0), SUPERVISOR
    )
    validate_error(nothing_built, ApiErrorId.ERR_PRODUCED_UNITS_INVALID.value, 422)

    reread = get_lot_data(lot["id"])
    assert reread["status"] == "OPEN"
    assert reread["produced_units"] == 0
    assert reread["planned_units"] == 500


def test_granting_a_listing_for_a_standard_the_body_does_not_hold_is_rejected():
    """PRD §3.5: "the record's `standard_code` must be a member of the owning
    body's `accredited_standards`, or the request is rejected with
    `ERR_STANDARD_NOT_ACCREDITED`"
    PRD §3.5: "A filed record begins at `status` `APPLIED` with `listed_at`,
    `audit_due_at`, `listing_expires_at`, `suspended_at`, and `suspension_reason` all
    null."

    Design: Corner/validations/listing_with_standard_outside_body_accreditation_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    body = create_listing_body(accredited_standards=["EN_131_2"])
    record = file_listing_record(
        ctx["product"]["id"], body["id"], standard_code="ANSI_ASC_A14_2"
    )
    listing_campaign = run_campaign_to_passed(
        ctx["product"], ctx["revision"]["id"], "CERTIFICATION_LISTING", ctx["bench"]["id"]
    )
    assert listing_campaign["status"] == "PASSED"

    response = api_client.grant_listing(
        record["id"], make_certification_body_headers(body["id"])
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_NOT_ACCREDITED.value, 422)

    reread = get_listing_record_data(record["id"])
    assert reread["status"] == "APPLIED"
    assert reread["listed_at"] is None
    assert reread["audit_due_at"] is None
    assert reread["listing_expires_at"] is None


def test_conclude_is_rejected_while_a_required_test_code_has_no_row():
    """PRD §3.4: "For a campaign whose `purpose` is `DESIGN_QUALIFICATION`,
    `CERTIFICATION_LISTING`, or `INCIDENT_INVESTIGATION`, every `test_code` in the
    campaign's required test-code set must have at least one load test row on the
    campaign; a missing code is rejected with `ERR_REQUIRED_TESTS_MISSING`. The
    required set is determined by the model's `product_type`, extended with
    `RIVET_SHEAR` whenever the campaign's pinned design revision has `joint_type`
    `RIVETED` — the pinned revision, not the model's current one, is what decides
    this."

    Design: Corner/validations/conclude_with_required_test_code_missing_rejected
    """
    product = create_product(**FIBERGLASS)
    revision = create_draft_revision(product["id"], joint_type="RIVETED")
    bench = create_test_bench()
    campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    start_campaign_on_new_reservation(campaign["id"], bench["id"])
    for code in ("STATIC_VERTICAL", "RAIL_BENDING", "SLIP_RESISTANCE"):
        recorded = record_passing_load_test(campaign["id"], product, code)
        assert recorded["outcome"] == "PASS"

    response = api_client.conclude_test_campaign(campaign["id"], TECHNICIAN)
    validate_error(response, ApiErrorId.ERR_REQUIRED_TESTS_MISSING.value, 422)

    reread = get_campaign_data(campaign["id"])
    assert reread["status"] == "IN_PROGRESS"
    assert reread["load_test_count"] == 3
    assert reread["failed_test_count"] == 0
    assert reread["concluded_at"] is None


def test_concluding_an_audit_short_of_its_sample_size_is_rejected():
    """PRD §3.5: "Concluding an audit campaign substitutes the sample-size rule
    for the test-coverage rule: the campaign's `load_test_count` must be at least
    its `audit_sample_size`, and a short audit is rejected with
    `ERR_AUDIT_SAMPLE_SHORT`."
    PRD §3.5: "It is `TIER_0` when there is no prior audit or when
    `prior_failure_rate_pct` is exactly 0.00."

    Design: Corner/validations/conclude_audit_with_sample_short_of_size_rejected
    """
    ctx, lot = setup_released_lot(produced_units=400)
    campaign = plan_audit_campaign(
        ctx, lot["id"], "2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z"
    )
    assert campaign["audit_sample_size"] == 5
    assert campaign["escalation_tier"] == "TIER_0"
    assert campaign["prior_failure_rate_pct"] is None
    start_campaign_on_new_reservation(campaign["id"], ctx["bench"]["id"])
    product = get_product_data(ctx["product"]["id"])
    for _ in range(4):
        record_passing_load_test(campaign["id"], product)

    response = api_client.conclude_test_campaign(campaign["id"], TECHNICIAN)
    validate_error(response, ApiErrorId.ERR_AUDIT_SAMPLE_SHORT.value, 422)

    reread = get_campaign_data(campaign["id"])
    assert reread["status"] == "IN_PROGRESS"
    assert reread["audit_sample_size"] == 5
    assert reread["load_test_count"] == 4
    assert reread["failed_test_count"] == 0
    assert get_listing_record_data(ctx["listing_record"]["id"])["status"] == "LISTED"


def test_the_finding_and_root_cause_must_pair_in_both_directions():
    """PRD §3.8: "The pairing rule is strict in both directions:
    `ROOT_CAUSE_IDENTIFIED` requires a non-null `root_cause_code`, and
    `NOT_SUBSTANTIATED` requires `root_cause_code` to be null; either mismatch is
    rejected with `ERR_FINDING_ROOT_CAUSE_MISMATCH`."

    Design: Corner/validations/resolve_investigation_with_finding_root_cause_mismatch_rejected
    """
    product = create_product()
    incident = setup_incident_under_investigation(
        product["id"], incident_type="RUNG_SEPARATION", injury_severity="MINOR"
    )
    # MINOR weight 4 times RUNG_SEPARATION weight 2.5.
    assert float(incident["incident_points"]) == 10.00

    missing_code = api_client.resolve_investigation(
        incident["id"],
        resolve_investigation_payload("ROOT_CAUSE_IDENTIFIED", None),
        DIRECTOR,
    )
    validate_error(missing_code, ApiErrorId.ERR_FINDING_ROOT_CAUSE_MISMATCH.value, 422)

    unwanted_code = api_client.resolve_investigation(
        incident["id"],
        resolve_investigation_payload("NOT_SUBSTANTIATED", "RIVET_SHEAR_MARGIN"),
        DIRECTOR,
    )
    validate_error(unwanted_code, ApiErrorId.ERR_FINDING_ROOT_CAUSE_MISMATCH.value, 422)

    reread = get_incident_data(incident["id"])
    assert reread["status"] == "UNDER_INVESTIGATION"
    assert reread["finding"] is None
    assert reread["root_cause_code"] is None
    assert reread["requires_capa"] is False
    assert float(get_product_data(product["id"])["risk_score_gross"]) == 10.00


def test_a_consumer_may_not_choose_a_remedy_the_recall_does_not_offer():
    """PRD §3.9: "The supplied `remedy_choice` must equal the recall's
    `remedy_type`, or the acknowledgement is rejected with
    `ERR_REMEDY_CHOICE_MISMATCH` — consumers take the remedy the recall offers, not
    one of their choosing."

    Design: Corner/validations/acknowledge_with_remedy_choice_mismatch_rejected
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    recall = setup_recall_in_progress(ctx, remedy_type="REPAIR_KIT")
    assert recall["remedy_type"] == "REPAIR_KIT"
    assert recall["units_outstanding"] == 1
    registration = ctx["registrations"][0]
    assert get_registration_data(registration["id"])["registration_status"] == "NOTIFIED"

    response = api_client.acknowledge_recall(
        registration["id"], acknowledge_payload("REFUND"), CONSUMER
    )
    validate_error(response, ApiErrorId.ERR_REMEDY_CHOICE_MISMATCH.value, 422)

    reread = get_registration_data(registration["id"])
    assert reread["registration_status"] == "NOTIFIED"
    assert reread["remedy_choice"] is None
    assert reread["acknowledged_at"] is None

    reread_recall = get_recall_data(recall["id"])
    assert reread_recall["units_outstanding"] == 1
    assert reread_recall["units_remedied"] == 0


def test_both_engineering_thresholds_answer_with_the_same_margin_error():
    """PRD §3.2: "Submission is gated on the predicted margin: a
    `structural_margin_pct` below 2.00 percent is rejected with
    `ERR_DESIGN_MARGIN_INSUFFICIENT`."
    PRD §3.2: "`APPROVE` moves the revision `UNDER_REVIEW` → `APPROVED`, but only
    if `rail_section_modulus_in3` is at least 0.180 cubic inches; below that the
    approval is rejected with `ERR_DESIGN_MARGIN_INSUFFICIENT`."

    Design: Corner/validations/submit_with_structural_margin_below_minimum_rejected
    """
    product = create_product()
    thin_margin = create_draft_revision(
        product["id"], structural_margin_pct=1.50, rail_section_modulus_in3=0.250
    )
    thin_rail = create_draft_revision(
        product["id"], structural_margin_pct=6.50, rail_section_modulus_in3=0.150
    )
    thin_rail = submit_revision(thin_rail["id"])
    assert thin_rail["status"] == "UNDER_REVIEW"

    submit_response = api_client.submit_design_revision(thin_margin["id"], ENGINEER)
    validate_error(
        submit_response, ApiErrorId.ERR_DESIGN_MARGIN_INSUFFICIENT.value, 422
    )

    approve_response = api_client.review_design_revision(
        thin_rail["id"], review_design_revision_payload("APPROVE"), APPROVER
    )
    validate_error(
        approve_response, ApiErrorId.ERR_DESIGN_MARGIN_INSUFFICIENT.value, 422
    )

    assert get_revision_data(thin_margin["id"])["status"] == "DRAFT"
    still_under_review = get_revision_data(thin_rail["id"])
    assert still_under_review["status"] == "UNDER_REVIEW"
    assert still_under_review["reviewed_by_user_id"] is None
    assert get_product_data(product["id"])["design_status"] == "DRAFT"


def test_a_second_live_recall_for_the_same_model_is_rejected():
    """PRD §3.9: "Only one live recall per model is permitted: if any other recall
    event for that model is in `DRAFT`, `ANNOUNCED`, or `IN_PROGRESS`, the draft is
    rejected with `ERR_RECALL_ALREADY_OPEN`."
    PRD §3.9: "A drafted recall begins at `status` `DRAFT` with every exposure
    figure null and `announced_at` and `closed_at` null."

    Design: Corner/validations/second_open_recall_for_same_product_rejected
    """
    ctx, _ = setup_released_lot(produced_units=400)
    first = draft_recall(
        ctx["product"]["id"], [ctx["revision"]["id"]], remedy_type="REPAIR_KIT"
    )
    assert first["status"] == "DRAFT"

    response = api_client.create_recall_event(
        create_recall_event_payload(
            ctx["product"]["id"], [ctx["revision"]["id"]], remedy_type="REFUND"
        ),
        DIRECTOR,
    )
    validate_error(response, ApiErrorId.ERR_RECALL_ALREADY_OPEN.value, 409)

    rows, meta = validate_paginated(
        api_client.list_recall_events(DIRECTOR, {"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert get_recall_data(first["id"])["status"] == "DRAFT"
    assert get_product_data(ctx["product"]["id"])["market_status"] == "RETAIL_RELEASED"


def test_announcing_a_recall_with_no_lots_in_scope_is_rejected():
    """PRD §3.9: "The recall's in-scope lot set must be non-empty, or the
    announcement is rejected with `ERR_RECALL_SCOPE_EMPTY`."
    PRD §3.9: "Announcement is the irreversible step, and it freezes the
    numbers."

    Design: Corner/validations/announce_with_empty_recall_scope_rejected
    """
    ctx = setup_retail_released_product()
    recall = draft_recall(
        ctx["product"]["id"], [ctx["revision"]["id"]], remedy_type="REPLACEMENT"
    )

    response = api_client.announce_recall(recall["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_RECALL_SCOPE_EMPTY.value, 422)

    reread = get_recall_data(recall["id"])
    assert reread["status"] == "DRAFT"
    assert reread["announced_at"] is None
    assert reread["exposure_units_shipped_basis"] is None
    assert reread["exposure_units_registered_basis"] is None
    assert get_product_data(ctx["product"]["id"])["market_status"] == "RETAIL_RELEASED"


def test_a_recall_with_units_still_outstanding_cannot_close_yet():
    """PRD §3.9: "A recall may close on either of two grounds: every remedy is
    accounted for, meaning `units_outstanding` is exactly 0, or the outreach window
    has run out, meaning the logical clock has reached or passed `announced_at`
    advanced by 365 days — one 365-day year. When neither ground holds, the close is
    rejected with `ERR_RECALL_UNITS_OUTSTANDING`."

    Design: Corner/validations/close_recall_with_units_outstanding_rejected
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    recall = setup_recall_in_progress(ctx)

    response = api_client.close_recall(recall["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_RECALL_UNITS_OUTSTANDING.value, 409)

    reread = get_recall_data(recall["id"])
    assert reread["status"] == "IN_PROGRESS"
    assert reread["closed_at"] is None
    assert reread["units_outstanding"] == 1
    assert reread["exposure_units_registered_basis"] == 1
    assert reread["exposure_units_shipped_basis"] == 400
    # One registration against four hundred shipped units.
    assert float(reread["notification_coverage_pct"]) == 0.25


def test_a_unit_from_an_in_process_lot_cannot_be_registered():
    """PRD §3.8: "The named lot must have `status` `RELEASED` or `QUARANTINED`,
    since a consumer cannot own a unit that never shipped; a lot still `OPEN` or
    `IN_PROCESS`, or already `SCRAPPED`, is rejected with `ERR_LOT_NOT_SHIPPABLE`."

    Design: Corner/validations/registration_against_in_process_lot_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    assert lot["status"] == "IN_PROCESS"

    response = api_client.create_consumer_registration(
        create_consumer_registration_payload(
            lot["id"],
            purchase_channel="ONLINE",
            purchase_date="2026-07-28T00:00:00Z",
            serial_suffix="0003",
        ),
        CONSUMER,
    )
    validate_error(response, ApiErrorId.ERR_LOT_NOT_SHIPPABLE.value, 409)

    assert get_lot_data(lot["id"])["status"] == "IN_PROCESS"
    _, meta = validate_paginated(
        api_client.list_consumer_registrations(
            OFFICER, {"production_lot_id": lot["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert get_product_data(ctx["product"]["id"])["held_registration_count"] == 0


def test_freezing_a_design_without_a_passed_qualification_is_rejected():
    """PRD §3.7: "And at least one test campaign must exist for this model, pinned
    to exactly the revision being frozen, with `purpose` `DESIGN_QUALIFICATION` and
    `status` `PASSED`; without it the freeze is rejected with
    `ERR_QUALIFYING_CAMPAIGN_MISSING`."

    Design: Corner/validations/freeze_design_without_qualifying_campaign_rejected
    """
    product = create_product()
    revision = create_approved_revision(product["id"])

    response = api_client.freeze_design(
        product["id"], freeze_design_payload(revision["id"]), APPROVER
    )
    validate_error(response, ApiErrorId.ERR_QUALIFYING_CAMPAIGN_MISSING.value, 422)

    reread = get_product_data(product["id"])
    assert reread["design_status"] == "DRAFT"
    assert reread["design_frozen_at"] is None
    assert reread["frozen_revision_id"] is None
    assert reread["dhf_retention_until"] is None
    assert reread["retention_anchor_source"] is None
    assert get_revision_data(revision["id"])["status"] == "APPROVED"


def test_production_cannot_start_before_the_design_is_frozen():
    """PRD §3.6: "The model's `design_status` must be `DESIGN_FROZEN`, or the
    request is rejected with `ERR_DESIGN_NOT_FROZEN` — which is also what a model
    already advanced to `DESIGN_OBSOLETE` receives, so no lot may start production
    for a recalled model."

    Design: Corner/validations/start_production_before_design_frozen_rejected
    """
    product = create_product(**FIBERGLASS)
    revision = create_approved_revision(product["id"])
    assert revision["status"] == "APPROVED"
    lot = open_lot(product, revision["id"], pultrusion_batch_id="PB-77")

    response = api_client.start_production(
        lot["id"], start_production_payload(400), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_DESIGN_NOT_FROZEN.value, 409)

    reread = get_lot_data(lot["id"])
    assert reread["status"] == "OPEN"
    assert reread["produced_units"] == 0
    assert get_product_data(product["id"])["design_status"] == "DRAFT"


def test_resume_ship_is_refused_while_the_mitigated_risk_stays_high():
    """PRD §3.7: "The model's `risk_score_mitigated` must be strictly below 25.00,
    or the resume is rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD` — note that the
    threshold is compared against the mitigated variant only, never the gross one."

    Design: Corner/validations/resume_ship_with_risk_score_above_threshold_rejected
    """
    ctx = setup_retail_released_product()
    incident = setup_incident_under_investigation(
        ctx["product"]["id"],
        incident_type="RAIL_FRACTURE",
        injury_severity="HOSPITALIZATION",
    )
    # HOSPITALIZATION weight 12 times RAIL_FRACTURE weight 3.0.
    assert float(incident["incident_points"]) == 36.00
    stopped = validate_success(
        api_client.stop_ship(
            ctx["product"]["id"], stop_ship_payload("FIELD_INCIDENT_REVIEW"), DIRECTOR
        )
    )
    assert stopped["market_status"] == "STOP_SHIP"

    response = api_client.resume_ship(ctx["product"]["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_RISK_SCORE_ABOVE_THRESHOLD.value, 422)

    reread = get_product_data(ctx["product"]["id"])
    assert reread["market_status"] == "STOP_SHIP"
    assert reread["stop_ship_reason_code"] == "FIELD_INCIDENT_REVIEW"
    assert float(reread["risk_score_gross"]) == 36.00
    assert float(reread["risk_score_mitigated"]) == 36.00


def test_a_sample_sequence_is_unique_only_within_its_own_lot():
    """PRD §2.5: "A joint sample's `sample_seq` is unique within its
    `production_lot_id`. Any repeat is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_sample_seq_on_same_lot_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    first_lot = open_lot(ctx["product"], ctx["revision"]["id"])
    first_lot = start_lot_production(first_lot["id"], 400)
    second_lot = open_lot(ctx["product"], ctx["revision"]["id"])
    second_lot = start_lot_production(second_lot["id"], 300)
    validate_success(
        api_client.create_joint_sample(
            first_lot["id"], create_joint_sample_payload(1, 470.00), TECHNICIAN
        ),
        201,
    )

    duplicate = api_client.create_joint_sample(
        first_lot["id"], create_joint_sample_payload(1, 462.00), TECHNICIAN
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

    accepted = validate_success(
        api_client.create_joint_sample(
            second_lot["id"], create_joint_sample_payload(1, 462.00), TECHNICIAN
        ),
        201,
    )
    # 12.00 lbf over the 450.00 snapshot is 2.67 percent, which rounds to 3.
    assert int(accepted["margin_pct"]) == 3

    first_reread = get_lot_data(first_lot["id"])
    assert first_reread["joint_sample_count"] == 1
    assert float(first_reread["conformance_index"]) == 4.00
    assert get_lot_data(second_lot["id"])["joint_sample_count"] == 1
