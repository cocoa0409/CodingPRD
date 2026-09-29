"""Lifecycle transitions, their cascades, and the state guards that reject them."""

from test_helpers import (
    ApiErrorId,
    acknowledge_registration,
    api_client,
    assert_instant_equals,
    create_and_approve_document,
    create_approved_revision,
    create_campaign,
    create_document,
    create_draft_revision,
    create_product,
    create_product_document_payload,
    create_test_bench,
    get_campaign_data,
    get_corrective_action_data,
    get_incident_data,
    get_listing_record_data,
    get_lot_data,
    get_product_data,
    get_recall_data,
    get_registration_data,
    get_reservation_data,
    get_revision_data,
    make_certification_body_headers,
    open_lot,
    quarantine_payload,
    reserve_bench,
    run_audit_campaign,
    setup_frozen_product,
    setup_incident_under_investigation,
    setup_recall_in_progress,
    setup_retail_released_product,
    setup_shipping_product_with_registered_units,
    setup_verified_capa,
    start_campaign_payload,
    start_lot_production,
    suspend_listing_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]
APPROVER = TEST_USERS["design_approver_headers"]

AUDIT_WINDOW = ("2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z")


def test_new_product_document_starts_in_draft():
    """PRD §3.3: "Documents begin at `status` `DRAFT` with `approved_at` null."
    PRD §2.5: "A product's document collection accepts `doc_kind` and `status`."

    Design: Corner/state_machines/product_document_initial_state_is_draft
    """
    product = create_product()
    payload = create_product_document_payload(
        product["id"],
        "WARNING_LABEL",
        document_version="1.0",
        placement_zone="SIDE_RAIL_LOWER",
        pictogram_count=3,
    )

    document = validate_success(
        api_client.create_product_document(payload, OFFICER), 201
    )

    assert document["status"] == "DRAFT"
    assert document["approved_at"] is None

    _, meta = validate_paginated(
        api_client.list_product_documents(
            product["id"], OFFICER, {"status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 0


def test_campaign_start_moves_to_in_progress_and_consumes_the_reservation():
    """PRD §3.4: "Starting a campaign moves it `PLANNED` → `IN_PROGRESS`, stamps
    `started_at` with the logical clock, and consumes a bench slot."
    PRD §3.4: "On success the named reservation moves `HELD` → `CONSUMED`, and
    the bench's `reserved_minutes_total` does not change."

    Design: Corner/state_machines/campaign_start_moves_planned_to_in_progress_and_consumes_reservation
    """
    product = create_product()
    revision = create_draft_revision(product["id"])
    bench = create_test_bench(max_load_capacity_lb=5000.00)
    campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    reservation = reserve_bench(bench["id"], campaign["id"], duration_minutes=240)
    assert reservation["duration_minutes"] == 240

    started = validate_success(
        api_client.start_test_campaign(
            campaign["id"], start_campaign_payload(reservation["id"]), TECHNICIAN
        )
    )

    assert started["status"] == "IN_PROGRESS"
    assert_instant_equals(started["started_at"], "2026-08-01T00:00:00Z", "started_at")
    assert started["concluded_at"] is None
    assert get_reservation_data(reservation["id"])["status"] == "CONSUMED"
    assert validate_success(api_client.get_test_bench(bench["id"], TECHNICIAN))[
        "reserved_minutes_total"
    ] == 240


def test_campaign_start_on_an_undersized_bench_is_rejected():
    """PRD §3.4: "The reserved bench must also be able to reach the model's
    requirement: when the bench's `max_load_capacity_lb` is below the model's
    `required_test_load_lb`, the start is rejected with
    `ERR_BENCH_CAPACITY_INSUFFICIENT`."

    Design: Corner/state_machines/campaign_start_with_insufficient_bench_capacity_rejected
    """
    product = create_product(
        material="FIBERGLASS_PULTRUSION", duty_rating="TYPE_IA", working_length_ft=24.0
    )
    assert float(product["required_test_load_lb"]) == 1350.00
    revision = create_draft_revision(product["id"])
    small = create_test_bench(max_load_capacity_lb=1000.00)
    campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    reservation = reserve_bench(small["id"], campaign["id"])

    response = api_client.start_test_campaign(
        campaign["id"], start_campaign_payload(reservation["id"]), TECHNICIAN
    )
    validate_error(response, ApiErrorId.ERR_BENCH_CAPACITY_INSUFFICIENT.value, 422)

    reread = get_campaign_data(campaign["id"])
    assert reread["status"] == "PLANNED"
    assert reread["started_at"] is None
    assert get_reservation_data(reservation["id"])["status"] == "HELD"


def test_listing_suspension_cascade_stops_shipment_and_terminates_there():
    """PRD §3.5: "Suspension moves the record `LISTED` → `SUSPENDED`, stamps
    `suspended_at` with the logical clock, records the reason, and clears
    `audit_due_at` to null — a suspended listing has no audit deadline."
    PRD §3.5: "It also cascades one hop: when the model's `market_status` is
    `RETAIL_RELEASED`, that model moves `RETAIL_RELEASED` → `STOP_SHIP` with
    `stop_ship_reason_code` set to `LISTING_SUSPENDED`, dragging the stop-ship
    consequences of §3.7 with it"

    Design: Corner/state_machines/listing_suspension_cascade_terminates_without_overwriting_reason
    """
    ctx = setup_retail_released_product()
    body_headers = make_certification_body_headers(ctx["listing_body"]["id"])

    suspended = validate_success(
        api_client.suspend_listing(
            ctx["listing_record"]["id"],
            suspend_listing_payload("BODY_REQUEST"),
            body_headers,
        )
    )

    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "BODY_REQUEST"
    assert_instant_equals(
        suspended["suspended_at"], "2026-08-01T00:00:00Z", "suspended_at"
    )
    assert suspended["audit_due_at"] is None

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "STOP_SHIP"
    assert product["stop_ship_reason_code"] == "LISTING_SUSPENDED"
    assert product["design_status"] == "DESIGN_FROZEN"

    assert get_campaign_data(ctx["qualification_campaign"]["id"])["status"] == "PASSED"
    assert get_campaign_data(ctx["listing_campaign"]["id"])["status"] == "PASSED", (
        "a concluded campaign is untouched by the stop-ship cascade"
    )


def test_failed_audit_suspends_the_listing_and_quarantines_the_sampled_lot():
    """PRD §3.5: "**Hop one:** the linked listing record moves `LISTED` →
    `SUSPENDED` with `suspension_reason` set to `AUDIT_FAILURE` and `audit_due_at`
    cleared to null."
    PRD §3.5: "**Hop three,** caused by hop two and applicable only to the audit
    purpose: the lot named by `sampled_lot_id`, if its `status` is `IN_PROCESS` or
    `RELEASED`, moves to `QUARANTINED` with `quarantine_reason_code` set to
    `AUDIT_FAILURE`, and that quarantine's own first hop sets `hold_flag` on the
    lot's consumer registrations in `REGISTERED` or `NOTIFIED`"

    Design: Corner/state_machines/audit_failure_cascade_suspends_listing_and_quarantines_sampled_lot
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )

    audit = run_audit_campaign(
        ctx, ctx["lot"]["id"], *AUDIT_WINDOW, failing_tests=1
    )

    assert audit["status"] == "FAILED"
    assert audit["load_test_count"] == 5
    assert audit["failed_test_count"] == 1

    record = get_listing_record_data(ctx["listing_record"]["id"])
    assert record["status"] == "SUSPENDED"
    assert record["suspension_reason"] == "AUDIT_FAILURE"
    assert record["audit_due_at"] is None

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "STOP_SHIP"
    assert product["stop_ship_reason_code"] == "LISTING_SUSPENDED", (
        "an audit failure always reads LISTING_SUSPENDED, never LOT_QUARANTINE"
    )
    assert product["held_registration_count"] == 1

    lot = get_lot_data(ctx["lot"]["id"])
    assert lot["status"] == "QUARANTINED"
    assert lot["quarantine_reason_code"] == "AUDIT_FAILURE"
    assert lot["units_quarantined"] == 400
    assert lot["units_released"] == 0

    registration = get_registration_data(ctx["registrations"][0]["id"])
    assert registration["hold_flag"] is True


def test_quarantine_cascade_skips_a_model_that_never_reached_retail():
    """PRD §3.6: "**Hop two,** caused by hop one: because registrations were
    flagged, the model's `held_registration_count` is recomputed as the number of
    its registrations with `hold_flag` true, and when that count becomes greater
    than 0 while the model's `market_status` is `RETAIL_RELEASED`, the model moves
    `RETAIL_RELEASED` → `STOP_SHIP` with `stop_ship_reason_code` set to
    `LOT_QUARANTINE`."

    Design: Corner/state_machines/lot_quarantine_conditional_cascade_skips_not_released_product
    """
    ctx = setup_frozen_product()
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    assert ctx["product"]["market_status"] == "NOT_RELEASED"

    quarantined = validate_success(
        api_client.quarantine_production_lot(
            lot["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
        )
    )

    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason_code"] == "JOINT_INTEGRITY"
    assert quarantined["units_quarantined"] == 400
    assert quarantined["units_wip"] == 0

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "NOT_RELEASED"
    assert product["stop_ship_reason_code"] is None
    assert product["held_registration_count"] == 0


def test_document_approval_supersedes_the_prior_approved_document_of_that_kind():
    """PRD §3.3: "Approval also supersedes: any other document for the same model
    with the same `doc_kind` that was in `APPROVED` moves `APPROVED` →
    `SUPERSEDED`, which is terminal."
    PRD §3.3: "A superseded document no longer satisfies the mandated-document
    gate on retail release, so replacing artwork never leaves two live versions of
    the same kind."

    Design: Corner/state_machines/document_approve_supersedes_prior_approved_document_of_same_kind
    """
    product = create_product()
    first = create_and_approve_document(
        product["id"], "DUTY_RATING_LABEL", document_version="1.0"
    )
    other_kind = create_and_approve_document(
        product["id"], "WARNING_LABEL", document_version="1.0"
    )
    replacement = create_document(
        product["id"], "DUTY_RATING_LABEL", document_version="2.0"
    )

    approved = validate_success(
        api_client.approve_product_document(replacement["id"], OFFICER)
    )

    assert approved["status"] == "APPROVED"
    assert_instant_equals(
        approved["approved_at"], "2026-08-01T00:00:00Z", "approved_at"
    )

    rows, meta = validate_paginated(
        api_client.list_product_documents(
            product["id"], OFFICER, {"status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {other_kind["id"], approved["id"]}

    superseded_rows, superseded_meta = validate_paginated(
        api_client.list_product_documents(
            product["id"], OFFICER, {"status": "SUPERSEDED"}
        )
    )
    assert superseded_meta["total_count"] == 1
    assert superseded_rows[0]["id"] == first["id"]
    assert_instant_equals(
        superseded_rows[0]["approved_at"],
        "2026-08-01T00:00:00Z",
        "approved_at",
    )


def test_submit_on_an_already_approved_revision_is_rejected():
    """PRD §3.2: "A revision that is not in `DRAFT` when submission is requested is
    rejected with `ERR_REVISION_STATE_INVALID`, and the same code answers a review
    decision on a revision that is not `UNDER_REVIEW` and a revise request on a
    revision that is not `CHANGES_REQUESTED`."

    Design: Corner/state_machines/submit_on_approved_revision_rejected
    """
    product = create_product()
    revision = create_approved_revision(product["id"])
    assert revision["status"] == "APPROVED"

    response = api_client.submit_design_revision(revision["id"], ENGINEER)
    validate_error(response, ApiErrorId.ERR_REVISION_STATE_INVALID.value, 409)

    reread = get_revision_data(revision["id"])
    assert reread["status"] == "APPROVED"
    assert reread["review_round"] == 1


def test_second_investigation_on_the_same_incident_is_rejected():
    """PRD §3.8: "An investigation requested on an incident that is not
    `REPORTED`, a resolution requested on one that is not `UNDER_INVESTIGATION`,
    and a corrective action created against one that is not
    `ROOT_CAUSE_IDENTIFIED` are each rejected with `ERR_INCIDENT_STATE_INVALID`."
    PRD §3.8: "Opening an investigation moves the incident `REPORTED` →
    `UNDER_INVESTIGATION`, increments the incident's `version`, derives that
    incident's `incident_points`, and recomputes both of the model's risk
    scores"

    Design: Corner/state_machines/repeat_investigate_on_same_incident_rejected
    """
    product = create_product()
    incident = setup_incident_under_investigation(
        product["id"], incident_type="RAIL_FRACTURE", injury_severity="MINOR"
    )
    # MINOR weight 4 times RAIL_FRACTURE weight 3.0.
    assert float(incident["incident_points"]) == 12.00

    response = api_client.investigate_field_incident(incident["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_INCIDENT_STATE_INVALID.value, 409)

    reread = get_incident_data(incident["id"])
    assert reread["status"] == "UNDER_INVESTIGATION"
    assert reread["version"] == 2
    assert reread["finding"] is None
    assert reread["requires_capa"] is False
    assert float(get_product_data(product["id"])["risk_score_gross"]) == 12.00


def test_verification_of_an_already_verified_corrective_action_is_rejected():
    """PRD §3.8: "A superseded action can no longer be verified, and a
    verification requested on an action that is already `VERIFIED` or
    `SUPERSEDED` is rejected with `ERR_CORRECTIVE_ACTION_NOT_OPEN`."

    Design: Corner/state_machines/verify_on_already_verified_corrective_action_rejected
    """
    product = create_product()
    incident, action = setup_verified_capa(product["id"])
    assert incident["status"] == "CLOSED"

    response = api_client.verify_corrective_action(action["id"], APPROVER)
    validate_error(response, ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_OPEN.value, 409)

    reread = get_corrective_action_data(action["id"])
    assert reread["status"] == "VERIFIED"
    assert_instant_equals(
        reread["verified_at"], "2026-08-01T00:00:00Z", "verified_at"
    )
    assert get_incident_data(incident["id"])["status"] == "CLOSED"

    reread_product = get_product_data(product["id"])
    assert float(reread_product["risk_score_gross"]) == 36.00
    assert float(reread_product["risk_score_mitigated"]) == 9.00


def test_a_closed_recall_can_be_neither_closed_nor_notified_again():
    """PRD §3.9: "Closing the recall moves it `IN_PROGRESS` → the terminal
    `CLOSED` and stamps `closed_at` with the logical clock; a recall that is not
    `IN_PROGRESS` is rejected with `ERR_RECALL_STATE_INVALID`."
    PRD §3.9: "A recall may close on either of two grounds: every remedy is
    accounted for, meaning `units_outstanding` is exactly 0, or the outreach
    window has run out, meaning the logical clock has reached or passed
    `announced_at` advanced by 365 days — one 365-day year."

    Design: Corner/state_machines/closed_recall_cannot_be_closed_again
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    recall = setup_recall_in_progress(ctx)
    acknowledge_registration(ctx["registrations"][0]["id"], "REPAIR_KIT")

    closed = validate_success(api_client.close_recall(recall["id"], DIRECTOR))
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

    validate_error(
        api_client.close_recall(recall["id"], DIRECTOR),
        ApiErrorId.ERR_RECALL_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.notify_recall(recall["id"], DIRECTOR),
        ApiErrorId.ERR_RECALL_STATE_INVALID.value,
        409,
    )

    reread = get_recall_data(recall["id"])
    assert reread["status"] == "CLOSED"
    assert reread["units_outstanding"] == 0
    assert reread["units_remedied"] == 1


def test_a_superseded_revision_can_no_longer_be_revised():
    """PRD §3.2: "Approval also carries one cascade: if this revision names a
    `supersedes_revision_id` and the revision so named is itself in `APPROVED`,
    that older revision moves `APPROVED` → `SUPERSEDED` and its `superseded_at` is
    stamped with the logical clock."
    PRD §3.2: "A revision that is not in `DRAFT` when submission is requested is
    rejected with `ERR_REVISION_STATE_INVALID`, and the same code answers a review
    decision on a revision that is not `UNDER_REVIEW` and a revise request on a
    revision that is not `CHANGES_REQUESTED`."

    Design: Corner/state_machines/superseded_revision_cannot_be_revised
    """
    product = create_product()
    first = create_approved_revision(product["id"], structural_margin_pct=6.50)
    create_approved_revision(product["id"], supersedes_revision_id=first["id"])

    response = api_client.revise_design_revision(
        first["id"], ENGINEER, {"structural_margin_pct": 8.0}
    )
    validate_error(response, ApiErrorId.ERR_REVISION_STATE_INVALID.value, 409)

    reread = get_revision_data(first["id"])
    assert reread["status"] == "SUPERSEDED"
    assert_instant_equals(
        reread["superseded_at"], "2026-08-01T00:00:00Z", "superseded_at"
    )
    assert float(reread["structural_margin_pct"]) == 6.50, (
        "the rejected revise wrote nothing"
    )


def test_resume_ship_with_a_quarantined_lot_still_present_is_rejected():
    """PRD §3.7: "No lot of the model may still be in `QUARANTINED`, and the
    model's `held_registration_count` must be exactly 0; either condition failing
    is rejected with `ERR_QUARANTINE_HOLD_PRESENT`."

    Design: Corner/state_machines/resume_ship_with_quarantined_lot_rejected
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    validate_success(
        api_client.quarantine_production_lot(
            ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
        )
    )

    response = api_client.resume_ship(ctx["product"]["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_QUARANTINE_HOLD_PRESENT.value, 409)

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "STOP_SHIP"
    assert product["stop_ship_reason_code"] == "LOT_QUARANTINE"
    assert float(product["risk_score_mitigated"]) == 0.00
    assert get_lot_data(ctx["lot"]["id"])["status"] == "QUARANTINED"
    assert (
        get_registration_data(ctx["registrations"][0]["id"])["hold_flag"] is True
    )
