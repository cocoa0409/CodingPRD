"""Issuing the order, serving the owner, and the negotiation loop."""

from test_helpers import (
    ApiErrorId,
    assert_abatement_order,
    assert_owner_notice,
    bootstrap_registry,
    complete_visit,
    file_complaint,
    generate_notice,
    make_supervisor_headers,
    read_property_version,
    record_assessment,
    record_service,
    schedule_visit,
    set_clock,
    setup_completed_violation_visit,
    setup_escalated_order,
    setup_issued_order,
    setup_served_order,
    start_visit,
    TEST_USERS,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


def test_order_issuance_guard_rails(api):
    """PRD §3.6: "The originating visit must have reached `COMPLETED`, else
    `ERR_INSPECTION_NOT_COMPLETED`, and its `result` must be `VIOLATION_FOUND`,
    else `ERR_NO_VIOLATION_FOUND` (HTTP 422). The issuing supervisor may not be
    the officer who ran that visit, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.8: "A supervisor issuing an abatement order may not be the officer who
    performed the originating inspection: if the issuer's `X-User-ID` equals the
    `officer_id` of that inspection, the issuance fails with
    `ERR_SEGREGATION_OF_DUTIES` (422)."

    Design: Corner/validations/corner_order_creation_guard_rails
    """
    env = bootstrap_registry(inspectors=2, parcels=2)
    first = file_complaint(env["prop1_id"], complaint_type="HARBORAGE",
                           reported_severity="HIGH")
    triage(first["id"], env["sup_id"], "HIGH")
    second = file_complaint(
        env["prop2_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Sighting near the porch",
    )
    triage(second["id"], env["sup_id"], "ROUTINE")
    visit_a = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=first["id"],
    )
    visit_b = schedule_visit(
        env["sup_id"], "INITIAL", env["insp2_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=second["id"],
    )
    set_clock("2026-05-05T09:00:00Z")
    start_visit(visit_a["id"], env["insp1_id"])
    record_assessment(
        visit_a["id"], env["insp1_id"], harborage_score=8, attractant_score=7,
        sanitation_score=6, burrow_count=4,
    )
    start_visit(visit_b["id"], env["insp2_id"])
    complete_visit(visit_b["id"], env["insp2_id"], "NO_VIOLATION")

    sup = make_supervisor_headers(env["sup_id"])
    prop1_v = read_property_version(env["prop1_id"], env["sup_id"])
    prop2_v = read_property_version(env["prop2_id"], env["sup_id"])

    not_completed = api.create_abatement_order(
        {"inspection_id": visit_a["id"], "required_actions": ["REMOVE_HARBORAGE"],
         "expected_property_version": prop1_v},
        sup,
    )
    assert not_completed.status_code == 409
    validate_error(not_completed, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED.value)

    no_violation = api.create_abatement_order(
        {"inspection_id": visit_b["id"], "required_actions": ["REMOVE_HARBORAGE"],
         "expected_property_version": prop2_v},
        sup,
    )
    assert no_violation.status_code == 422
    validate_error(no_violation, ApiErrorId.ERR_NO_VIOLATION_FOUND.value)

    set_clock("2026-05-05T09:45:00Z")
    complete_visit(visit_a["id"], env["insp1_id"], "VIOLATION_FOUND")
    prop1_v2 = read_property_version(env["prop1_id"], env["sup_id"])

    self_issued = api.create_abatement_order(
        {"inspection_id": visit_a["id"], "required_actions": ["REMOVE_HARBORAGE"],
         "expected_property_version": prop1_v2},
        make_supervisor_headers(env["insp1_id"]),
    )
    assert self_issued.status_code == 422
    validate_error(self_issued, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    complaint_after = validate_success(api.get_complaint(first["id"], CLERK))
    assert complaint_after["status"] == "INSPECTED"
    prop_after = validate_success(api.get_property(env["prop1_id"], sup))
    assert prop_after["open_order_count"] == 0
    assert prop_after["version"] == prop1_v2


def test_stale_parcel_version_blocks_the_order_then_a_fresh_read_succeeds(api):
    """PRD §2.6: "If `expected_property_version` does not equal the parcel's
    current `version`, the issuance is rejected with
    `ERR_STALE_PROPERTY_VERSION` and HTTP 412, and nothing is written."
    PRD §3.6: "Its `property_id` is copied from the originating visit, its
    `issued_by_officer_id` is taken from the issuer's `X-User-ID`, and its
    `infestation_tier_at_issue` is copied from the assessment recorded during
    that visit — a snapshot that is never re-derived even if the parcel's
    condition later changes."
    PRD §3.6: "Issuance also moves the linked complaint `INSPECTED →
    ABATEMENT_ORDERED`, raises the parcel's `open_order_count` by one and
    increments the parcel's `version` by one."

    Design: Corner/cross_cutting_layers/corner_occ_stale_property_version_blocks_order
    """
    env, _complaint, visit = setup_completed_violation_visit(
        bootstrap_kwargs={"inspectors": 1}
    )
    sup = make_supervisor_headers(env["sup_id"])
    current = read_property_version(env["prop_id"], env["sup_id"])

    stale = api.create_abatement_order(
        {"inspection_id": visit["id"], "required_actions": ["REMOVE_HARBORAGE"],
         "expected_property_version": current - 1},
        sup,
    )
    assert stale.status_code == 412
    validate_error(stale, ApiErrorId.ERR_STALE_PROPERTY_VERSION.value)
    untouched = validate_success(api.get_property(env["prop_id"], sup))
    assert untouched["open_order_count"] == 0
    assert untouched["version"] == current

    accepted = api.create_abatement_order(
        {"inspection_id": visit["id"], "required_actions": ["REMOVE_HARBORAGE"],
         "expected_property_version": current},
        sup,
    )
    order = validate_success(accepted, 201)
    assert_abatement_order(order)
    assert order["status"] == "ISSUED"
    assert order["escalation_level"] == 0
    assert order["infestation_tier_at_issue"] == "SEVERE"
    assert order["issued_by_officer_id"] == env["sup_id"]

    after = validate_success(api.get_property(env["prop_id"], sup))
    assert after["version"] == current + 1
    assert after["open_order_count"] == 1


def test_notice_sequencing_is_regulated(api):
    """PRD §3.6: "Notice sequencing is regulated. The very first notice generated
    on an order must be an `ABATEMENT_ORDER` notice; and a `FINAL_WARNING` may
    only be generated while the order is in `ESCALATED`. Either violation is
    refused with `ERR_NOTICE_SEQUENCE_INVALID` (HTTP 422)."
    PRD §3.6: "The notice is created in status `PENDING_SERVICE`, its `sent_at`
    stamped from the logical clock, its `served_at` and `service_outcome` null,
    and its `recipient_address` copied from the owner's `mailing_address` as it
    stands at that moment — later edits to the owner's address of record do not
    rewrite an already-generated notice."

    Design: Corner/validations/corner_notice_sequence_guard_rails
    """
    env = setup_issued_order()

    advisory_first = api.create_notice(
        env["order_id"],
        {"notice_type": "EDUCATIONAL_ADVISORY", "delivery_method": "FIRST_CLASS_MAIL"},
        CLERK,
    )
    assert advisory_first.status_code == 422
    validate_error(advisory_first, ApiErrorId.ERR_NOTICE_SEQUENCE_INVALID.value)

    warning_first = api.create_notice(
        env["order_id"],
        {"notice_type": "FINAL_WARNING", "delivery_method": "PERSONAL_SERVICE"},
        CLERK,
    )
    assert warning_first.status_code == 422
    validate_error(warning_first, ApiErrorId.ERR_NOTICE_SEQUENCE_INVALID.value)

    statutory = api.create_notice(
        env["order_id"],
        {"notice_type": "ABATEMENT_ORDER", "delivery_method": "CERTIFIED_MAIL"},
        CLERK,
    )
    notice = validate_success(statutory, 201)
    assert_owner_notice(notice)
    assert notice["status"] == "PENDING_SERVICE"
    assert notice["recipient_address"] == "12 Elm St"

    rows, meta = validate_paginated(api.list_notices(env["order_id"], CLERK))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_undeliverable_notice_leaves_the_order_unserved(api):
    """PRD §3.6: "An `UNDELIVERABLE` outcome moves the notice `PENDING_SERVICE →
    UNDELIVERABLE`, leaves `served_at` null and leaves the order untouched — a
    further notice must be generated to advance the order."
    PRD §3.6: "The new order is created in status `ISSUED` with
    `escalation_level` 0, `extension_count` 0, `extension_days_total` 0,
    `education_advisory_served` false, and `compliance_deadline`, `served_at`,
    `actual_labor_hours`, `actual_materials_cents`, `abated_at` and `closed_at`
    all null."

    Design: Corner/state_machines/corner_undeliverable_notice_leaves_order_unserved
    """
    env = setup_issued_order()
    notice = generate_notice(env["order_id"], "ABATEMENT_ORDER", "FIRST_CLASS_MAIL")
    set_clock("2026-05-06T09:00:00Z")

    served = validate_success(
        api.record_service_result(
            notice["id"], {"service_outcome": "UNDELIVERABLE"}, CLERK
        )
    )
    assert served["status"] == "UNDELIVERABLE"
    assert served["served_at"] is None
    assert served["service_outcome"] == "UNDELIVERABLE"

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "ISSUED"
    assert order["compliance_deadline"] is None
    assert order["served_at"] is None
    assert order["education_advisory_served"] is False

    rows, meta = validate_paginated(api.list_notices(env["order_id"], CLERK))
    assert meta["total_count"] == 1


def test_second_service_result_on_a_served_notice_is_refused(api):
    """PRD §3.6: "The notice must still be in `PENDING_SERVICE`; recording a
    second outcome on a notice that already reached `SERVED` or `UNDELIVERABLE`
    is refused with `ERR_NOTICE_ALREADY_SERVED`."
    PRD §3.6: "Under the program ordinance a refusal is deemed good service, so
    `DELIVERED` and `REFUSED` both move the notice `PENDING_SERVICE → SERVED` and
    stamp its `served_at` with the current logical clock."
    PRD §3.6: "The `compliance_deadline` is then the notice's `served_at` plus
    that number of days, preserving the exact time of day of `served_at`."

    Design: Corner/state_machines/corner_second_service_result_on_served_notice_rejected
    """
    env = setup_served_order()
    set_clock("2026-05-06T10:00:00Z")

    resp = api.record_service_result(
        env["notice_id"], {"service_outcome": "REFUSED"}, CLERK
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_SERVED.value)

    notices, _meta = validate_paginated(api.list_notices(env["order_id"], CLERK))
    notice = next(n for n in notices if n["id"] == env["notice_id"])
    assert notice["service_outcome"] == "DELIVERED"
    assert notice["served_at"] == "2026-05-05T10:00:00.000Z"

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "SERVED"
    assert order["compliance_deadline"] == "2026-05-12T10:00:00.000Z"


def test_served_order_guard_rails_for_reinspection_and_city_abatement(api):
    """PRD §3.3: "The assigned `officer_id` must differ from the officer who ran
    the order's originating inspection — otherwise
    `ERR_REINSPECTION_SAME_OFFICER` — and the visit may not be booked to begin
    before the owner's window has run out: if `scheduled_start` is strictly
    earlier than the order's `compliance_deadline`, the booking is refused with
    `ERR_REINSPECTION_TOO_EARLY`."
    PRD §3.6: "From `SERVED` it is allowed only once the owner's window has run
    out: if the current logical clock is strictly before the order's
    `compliance_deadline`, the recording is refused with
    `ERR_DEADLINE_NOT_PASSED`, while a clock exactly at the deadline is
    permitted."

    Design: Corner/validations/corner_served_order_guard_rails
    """
    env = setup_served_order()
    sup = make_supervisor_headers(env["sup_id"])
    assert env["order"]["compliance_deadline"] == "2026-05-12T10:00:00.000Z"

    too_early = api.create_inspection(
        {"kind": "REINSPECTION", "abatement_order_id": env["order_id"],
         "officer_id": env["insp2_id"],
         "scheduled_start": "2026-05-11T09:00:00Z",
         "scheduled_end": "2026-05-11T10:00:00Z"},
        sup,
    )
    assert too_early.status_code == 409
    validate_error(too_early, ApiErrorId.ERR_REINSPECTION_TOO_EARLY.value)

    same_officer = api.create_inspection(
        {"kind": "REINSPECTION", "abatement_order_id": env["order_id"],
         "officer_id": env["insp1_id"],
         "scheduled_start": "2026-05-12T10:00:00Z",
         "scheduled_end": "2026-05-12T11:00:00Z"},
        sup,
    )
    assert same_officer.status_code == 422
    validate_error(same_officer, ApiErrorId.ERR_REINSPECTION_SAME_OFFICER.value)

    premature_abatement = api.city_abate_order(
        env["order_id"], {"actual_labor_hours": 3, "actual_materials_cents": 9000}, sup
    )
    assert premature_abatement.status_code == 409
    validate_error(premature_abatement, ApiErrorId.ERR_DEADLINE_NOT_PASSED.value)

    order = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order["status"] == "SERVED"
    assert order["actual_labor_hours"] is None

    rows, meta = validate_paginated(
        api.list_inspections(sup, params={"abatement_order_id": env["order_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_extension_length_and_the_one_extension_ceiling(api):
    """PRD §3.6: "At most one extension exists per order: once `extension_count`
    has reached 1, a further request is refused with
    `ERR_EXTENSION_LIMIT_REACHED` (422), and that check is made before the
    requested length is examined."
    PRD §3.6: "The length must be a whole number of days between 1 and 14
    inclusive; anything below 1 or above 14 is refused with
    `ERR_EXTENSION_WINDOW_EXCEEDED`."
    PRD §3.6: "A granted extension pushes `compliance_deadline` later by the
    granted number of days, raises `extension_count` by one, adds the granted
    days to `extension_days_total`, and increments the order's `version` by one."

    Design: Corner/validations/corner_extension_window_and_limit_rules
    """
    env = setup_served_order()
    sup = make_supervisor_headers(env["sup_id"])

    too_long = api.extend_order(
        env["order_id"], {"extension_days": 20, "reason": "Contractor lead time"}, sup
    )
    assert too_long.status_code == 409
    validate_error(too_long, ApiErrorId.ERR_EXTENSION_WINDOW_EXCEEDED.value)
    unchanged = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert unchanged["compliance_deadline"] == "2026-05-12T10:00:00.000Z"

    granted = validate_success(
        api.extend_order(
            env["order_id"],
            {"extension_days": 10, "reason": "Contractor lead time"}, sup,
        )
    )
    assert granted["compliance_deadline"] == "2026-05-22T10:00:00.000Z"
    assert granted["extension_count"] == 1
    assert granted["extension_days_total"] == 10

    second_request = api.extend_order(
        env["order_id"], {"extension_days": 5, "reason": "Further delay"}, sup
    )
    assert second_request.status_code == 422
    validate_error(second_request, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED.value)

    final = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert final["compliance_deadline"] == "2026-05-22T10:00:00.000Z"
    assert final["status"] == "SERVED"


def test_final_warning_service_returns_an_escalated_order_to_served(api):
    """PRD §3.6: "A `FINAL_WARNING` notice served while the order is `ESCALATED`
    moves the order `ESCALATED → SERVED`, again stamping `served_at`, recomputing
    a deadline that is necessarily shorter because the escalation level is now at
    least 1, and incrementing the order's `version` by one; crucially, neither
    `extension_count` nor `extension_days_total` is reset by this leg, so an
    owner who already consumed their extension does not get another."
    PRD §3.6: "Under the program ordinance a refusal is deemed good service, so
    `DELIVERED` and `REFUSED` both move the notice `PENDING_SERVICE → SERVED` and
    stamp its `served_at` with the current logical clock."

    Design: Difficulty/non_linear_state_machine/abatement_order_escalation_cycle_returns_to_served
    """
    env = setup_escalated_order()
    assert env["order"]["status"] == "ESCALATED"

    warning = generate_notice(env["order_id"], "FINAL_WARNING", "PERSONAL_SERVICE")
    set_clock("2026-05-12T12:00:00Z")
    record_service(warning["id"], "DELIVERED")

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "SERVED"
    assert order["served_at"] == "2026-05-12T12:00:00.000Z"


def test_escalation_level_and_window_survive_the_negotiation_cycle(api):
    """PRD §3.6: "**The negotiation loop.** Together these rules form a cycle
    that an obstinate parcel can traverse repeatedly: an order is `SERVED`, a
    re-inspection is booked and the order becomes `REINSPECTION_SCHEDULED`, the
    re-inspection finds the work undone and the order becomes `ESCALATED`, a
    `FINAL_WARNING` is served and the order returns to `SERVED` with a shorter
    window. Each pass through `ESCALATED` raises `escalation_level`, which
    saturates at 2."
    PRD §3.6: "If the order's `escalation_level` is 1 or more, the window is
    reduced to 7 days if that is shorter than what has been derived so far."
    PRD §3.6: "The `compliance_deadline` is then the notice's `served_at` plus
    that number of days, preserving the exact time of day of `served_at`."

    Design: Difficulty/non_linear_state_machine/abatement_order_escalation_cycle_returns_to_served
    """
    env = setup_escalated_order()
    warning = generate_notice(env["order_id"], "FINAL_WARNING", "PERSONAL_SERVICE")
    set_clock("2026-05-12T12:00:00Z")
    record_service(warning["id"], "DELIVERED")

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["escalation_level"] == 1
    assert order["compliance_deadline"] == "2026-05-19T12:00:00.000Z"

    complaint = validate_success(api.get_complaint(env["comp_id"], CLERK))
    assert complaint["status"] == "ABATEMENT_ORDERED"


def test_reinspection_of_an_escalated_order_reports_order_not_served(api):
    """PRD §3.3: "A `REINSPECTION` may only be booked against an order currently
    in `SERVED`; any other order status yields `ERR_ORDER_NOT_SERVED`, and
    booking one moves the order `SERVED → REINSPECTION_SCHEDULED`."
    PRD §2.5: "Requests are screened by a fixed fourteen-step ladder, and the
    **first** step that fails determines the response."

    Design: Difficulty/priority_pair_validation_conflict/order_not_served_outranks_reinspection_too_early
    """
    env = setup_escalated_order()
    resp = api.create_inspection(
        {"kind": "REINSPECTION", "abatement_order_id": env["order_id"],
         "officer_id": env["insp2_id"],
         "scheduled_start": "2026-05-12T09:00:00Z",
         "scheduled_end": "2026-05-12T10:00:00Z"},
        make_supervisor_headers(env["sup_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SERVED.value)


def test_rejected_reinspection_leaves_the_escalated_order_untouched(api):
    """PRD §3.3: "A `REINSPECTION` may only be booked against an order currently
    in `SERVED`; any other order status yields `ERR_ORDER_NOT_SERVED`, and
    booking one moves the order `SERVED → REINSPECTION_SCHEDULED`."
    PRD §3.5: "**`REINSPECTION` ending `NON_COMPLIANT`** moves the linked order
    `REINSPECTION_SCHEDULED → ESCALATED`, raises the order's `escalation_level`
    by one but never above the ceiling of 2 — a third failed re-inspection leaves
    it saturated at 2 — and increments the order's `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/order_not_served_outranks_reinspection_too_early
    """
    env = setup_escalated_order()
    sup = make_supervisor_headers(env["sup_id"])
    resp = api.create_inspection(
        {"kind": "REINSPECTION", "abatement_order_id": env["order_id"],
         "officer_id": env["insp2_id"],
         "scheduled_start": "2026-05-12T09:00:00Z",
         "scheduled_end": "2026-05-12T10:00:00Z"},
        sup,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SERVED.value)

    order = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order["status"] == "ESCALATED"
    assert order["escalation_level"] == 1

    rows, meta = validate_paginated(
        api.list_inspections(sup, params={"abatement_order_id": env["order_id"]})
    )
    assert meta["total_count"] == 1, "no further re-inspection may have been booked"
    assert rows[0]["id"] == env["reinspection_id"]
