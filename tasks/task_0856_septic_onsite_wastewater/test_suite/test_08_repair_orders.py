"""Failure investigations: severity, the enforcement cascade and the closing branch."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_repair_order,
    condemn_parcel_well,
    create_parcel,
    create_repair_order_payload,
    create_well,
    open_and_issue_repair_order,
    open_repair_order,
    refresh_operating_permit,
    refresh_parcel,
    refresh_repair_order,
    refresh_transfer_inspection,
    request_transfer_inspection,
    set_clock,
    setup_operating_parcel,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_repair_order_against_an_unknown_operating_permit_is_not_found(api, ehs_field_headers):
    """PRD §2.6: "Every foreign key supplied in a request body must resolve to an
    existing row, reported with the same 404 family — `ERR_PARCEL_NOT_FOUND`,
    `ERR_SITE_EVALUATION_NOT_FOUND`, `ERR_SYSTEM_DESIGN_NOT_FOUND`,
    `ERR_CONTRACTOR_NOT_FOUND`, `ERR_CONSTRUCTION_PERMIT_NOT_FOUND` or
    `ERR_OPERATING_PERMIT_NOT_FOUND`."
    PRD §2.6: "It guards the nine creation operations that carry references in their
    payloads: recording a well, opening a site evaluation, drawing a system design,
    issuing a construction permit, scheduling an inspection, issuing an operating
    permit, filing a pumping record, opening a repair order and requesting a transfer
    inspection."

    Design: Corner/errors/corner_repair_order_create_with_unknown_operating_permit_returns_not_found
    """
    refused = api.create_repair_order(
        create_repair_order_payload(
            NON_EXISTENT_UUID, failure_type="BACKUP", reported_on="2026-05-01T00:00:00Z"
        ),
        ehs_field_headers,
    )
    validate_error(refused, ApiErrorId.ERR_OPERATING_PERMIT_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_repair_orders(ehs_field_headers))
    assert meta["total_count"] == 0


def test_issuing_an_order_computes_severity_and_suspends_the_operating_permit(api, applicant_headers, health_officer_headers):
    """PRD §3.8: "Otherwise a `SURFACING_EFFLUENT` or `BACKUP` failure is `URGENT`, and a
    `STRUCTURAL` failure is `ROUTINE`. The `compliance_deadline` is then the logical
    clock advanced by whole days according to that severity: 10 days for
    `IMMINENT_HAZARD`, 30 days for `URGENT` and 90 days for `ROUTINE`, preserving the
    time of day."
    PRD §3.8: "Second the operating permit: it moves `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/repair_order_issue_cascades_operating_permit_suspension_to_transfer_block
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TC2"),
        site_address="9 Failure Field",
    )
    order = open_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    assert order["status"] == "DRAFT"
    assert order["severity"] is None
    assert order["compliance_deadline"] is None
    assert order["extension_count"] == 0

    issued = validate_success(api.issue_repair_order(order["id"], health_officer_headers), 200)
    assert_repair_order(issued)
    assert issued["status"] == "ISSUED"
    assert issued["severity"] == "ROUTINE"
    assert issued["compliance_deadline"] == "2026-07-30T00:00:00.000Z"

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["status"] == "SUSPENDED"
    assert permit["compliance_status"] == "COMPLIANT", "the pumping dimension is untouched"


def test_issuing_an_order_blocks_the_pending_transfer_request_and_holds_the_parcel(api, applicant_headers, health_officer_headers):
    """PRD §3.8: "Third the transfer certificates hanging off that permit: because the
    permit entered `SUSPENDED`, every transfer inspection citing it whose status is
    `REQUESTED` moves `REQUESTED → BLOCKED`."
    PRD §3.8: "First the parcel: `open_repair_order_count` is re-derived and rises by
    one, `transfer_hold` becomes true, and `risk_tier` is re-derived."
    PRD §3.1: "It scores 25 points for each open repair order, counting at most 2 of
    them, so the repair-order contribution never exceeds 50 points."

    Design: Difficulty/transitive_cascade/repair_order_issue_cascades_operating_permit_suspension_to_transfer_block
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TC2B"),
        site_address="9 Failure Field",
    )
    transfer = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-02T00:00:00Z",
        buyer_name="Buyer Three",
        seller_name="Seller Three",
        inspection_mode="DESK_REVIEW",
    )
    assert transfer["status"] == "REQUESTED"

    order = open_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    validate_success(api.issue_repair_order(order["id"], health_officer_headers), 200)

    assert refresh_transfer_inspection(api, transfer["id"])["status"] == "BLOCKED"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["open_repair_order_count"] == 1
    assert parcel["transfer_hold"] is True
    assert parcel["risk_tier"] == "ELEVATED"


def test_water_quality_flag_escalates_a_structural_failure_to_imminent_hazard(api, applicant_headers, health_officer_headers):
    """PRD §3.8: "**Severity** turns on two things: if the `failure_type` is
    `GROUNDWATER_CONTAMINATION`, or if the parcel's `water_quality_flag` stands true at
    that moment whatever the failure type, the severity is `IMMINENT_HAZARD`."
    PRD §3.8: "and an extension is refused outright with `ERR_EXTENSION_NOT_ALLOWED`
    when the order's severity is `IMMINENT_HAZARD`, because a ten-day hazard deadline is
    not negotiable."

    Design: Corner/calculations/corner_repair_order_severity_escalates_to_imminent_hazard_and_cannot_be_extended
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-C9"),
        site_address="54 Hazard Hollow",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    ctx = setup_operating_parcel(
        api, existing_parcel=parcel, applicant_headers=applicant_headers
    )
    condemn_parcel_well(api, well["id"], collected_at="2026-05-02T06:00:00Z", nitrate_mg_l=3.0)
    assert refresh_parcel(api, parcel["id"])["water_quality_flag"] is True

    issued = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    assert issued["severity"] == "IMMINENT_HAZARD"
    assert issued["compliance_deadline"] == "2026-05-11T00:00:00.000Z"

    refused = api.extend_repair_order(issued["id"], health_officer_headers)
    validate_error(refused, ApiErrorId.ERR_EXTENSION_NOT_ALLOWED.value, 422)

    order_now = refresh_repair_order(api, issued["id"])
    assert order_now["extension_count"] == 0
    assert order_now["status"] == "ISSUED"

    assert refresh_parcel(api, parcel["id"])["risk_tier"] == "HIGH"
    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["status"] == "SUSPENDED"
    assert permit["monitoring_required"] is True


def test_third_extension_is_refused_at_the_cap(api, applicant_headers, health_officer_headers):
    """PRD §3.8: "Extension moves it `ISSUED → EXTENDED`, or `EXTENDED → EXTENDED` on
    the self-loop, advancing `compliance_deadline` by a further 30 whole days and
    incrementing `extension_count` by 1 each time."
    PRD §3.8: "Two limits bound the loop: an extension is refused with
    `ERR_MAX_EXTENSIONS_REACHED` once `extension_count` has reached 2, so an order may
    be extended at most twice for a total of 60 additional days"

    Design: Corner/validations/corner_third_repair_order_extension_is_rejected_at_the_cap
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V10"),
        site_address="63 Extension Estate",
    )
    issued = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="BACKUP",
        reported_on="2026-05-01T00:00:00Z",
    )
    assert issued["severity"] == "URGENT"
    assert issued["compliance_deadline"] == "2026-05-31T00:00:00.000Z"

    first = validate_success(api.extend_repair_order(issued["id"], health_officer_headers), 200)
    assert first["status"] == "EXTENDED"
    assert first["extension_count"] == 1
    assert first["compliance_deadline"] == "2026-06-30T00:00:00.000Z"

    second = validate_success(api.extend_repair_order(issued["id"], health_officer_headers), 200)
    assert second["extension_count"] == 2
    assert second["compliance_deadline"] == "2026-07-30T00:00:00.000Z"

    refused = api.extend_repair_order(issued["id"], health_officer_headers)
    validate_error(refused, ApiErrorId.ERR_MAX_EXTENSIONS_REACHED.value, 422)

    order_now = refresh_repair_order(api, issued["id"])
    assert order_now["extension_count"] == 2
    assert order_now["compliance_deadline"] == "2026-07-30T00:00:00.000Z"


def test_repaired_closure_after_the_deadline_is_refused_while_escalation_is_not(api, applicant_headers, ehs_field_headers):
    """PRD §3.8: "A `REPAIRED` outcome moves the order to `RESOLVED`, which is terminal,
    and is permitted only while the logical clock stands at or before
    `compliance_deadline`; once the deadline has passed the department will not accept a
    repair closure and the request is refused with `ERR_REPAIR_DEADLINE_PASSED`."
    PRD §3.8: "An `ESCALATE` outcome moves the order to `ESCALATED`, likewise terminal,
    and carries no deadline precondition — the department may always escalate, including
    after the deadline has lapsed."

    Design: Corner/validations/corner_repaired_resolution_after_deadline_is_rejected
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V11"),
        site_address="64 Overdue Oval",
    )
    issued = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="BACKUP",
        reported_on="2026-05-01T00:00:00Z",
    )
    assert issued["compliance_deadline"] == "2026-05-31T00:00:00.000Z"
    set_clock(api, "2026-06-01T00:00:00Z")

    refused = api.resolve_repair_order(
        issued["id"], {"outcome": "REPAIRED"}, ehs_field_headers
    )
    validate_error(refused, ApiErrorId.ERR_REPAIR_DEADLINE_PASSED.value, 409)
    assert refresh_repair_order(api, issued["id"])["status"] == "ISSUED"
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "SUSPENDED"

    escalated = validate_success(
        api.resolve_repair_order(issued["id"], {"outcome": "ESCALATE"}, ehs_field_headers), 200
    )
    assert escalated["status"] == "ESCALATED"
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "REVOKED"
    assert refresh_parcel(api, ctx["parcel_id"])["transfer_hold"] is True


def test_permit_returns_to_active_only_when_the_last_open_order_closes(api, applicant_headers, ehs_field_headers, health_officer_headers):
    """PRD §3.8: "The cited operating permit returns `SUSPENDED → ACTIVE`, but only when
    no other repair order on the parcel remains in `ISSUED` or `EXTENDED`; and every
    transfer inspection on that permit whose status is `BLOCKED` returns `BLOCKED →
    REQUESTED`."
    PRD §3.7: "it is barred while the parcel still carries any repair order in `ISSUED`
    or `EXTENDED`, refused with `ERR_OPEN_REPAIR_ORDER`."
    PRD §3.8: "Both stamp `closed_by_user_id` from the acting `X-User-ID` and both
    re-derive the parcel's `open_repair_order_count`, which falls by one."

    Design: Corner/state_machines/corner_repair_orders_repaired_branch_reinstates_permit_only_when_last_order_closes
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S12"),
        site_address="43 Order Alley",
    )
    routine = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    urgent = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="BACKUP",
        reported_on="2026-05-03T00:00:00Z",
    )
    assert routine["severity"] == "ROUTINE"
    assert routine["compliance_deadline"] == "2026-07-30T00:00:00.000Z"
    assert urgent["severity"] == "URGENT"
    assert urgent["compliance_deadline"] == "2026-05-31T00:00:00.000Z"

    blocked_reinstate = api.set_operating_permit_status(
        ctx["operating_permit_id"], {"action": "REINSTATE"}, health_officer_headers
    )
    validate_error(blocked_reinstate, ApiErrorId.ERR_OPEN_REPAIR_ORDER.value, 409)

    first_closed = validate_success(
        api.resolve_repair_order(routine["id"], {"outcome": "REPAIRED"}, ehs_field_headers), 200
    )
    assert first_closed["status"] == "RESOLVED"
    assert first_closed["closed_by_user_id"] == "u-ehs-field"
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "SUSPENDED"
    assert refresh_parcel(api, ctx["parcel_id"])["open_repair_order_count"] == 1

    validate_success(
        api.resolve_repair_order(urgent["id"], {"outcome": "REPAIRED"}, ehs_field_headers), 200
    )
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "ACTIVE"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["open_repair_order_count"] == 0
    assert parcel["transfer_hold"] is False
    assert parcel["risk_tier"] == "LOW"


def test_a_resolved_order_can_no_longer_be_extended(api, applicant_headers, ehs_field_headers, health_officer_headers):
    """PRD §3.8: "A `REPAIRED` outcome moves the order to `RESOLVED`, which is terminal"
    PRD §2.6: "First, the target resource must currently sit in a state from which the
    requested transition is declared, else `ERR_INVALID_STATE` (HTTP 409); this applies
    to every action operation."

    Design: Corner/state_machines/corner_repair_orders_repaired_branch_reinstates_permit_only_when_last_order_closes
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S12B"),
        site_address="43 Order Alley",
    )
    order = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="STRUCTURAL",
        reported_on="2026-05-03T00:00:00Z",
    )
    validate_success(
        api.resolve_repair_order(order["id"], {"outcome": "REPAIRED"}, ehs_field_headers), 200
    )

    refused = api.extend_repair_order(order["id"], health_officer_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert refresh_repair_order(api, order["id"])["extension_count"] == 0


def test_escalation_revokes_the_permit_and_denies_the_pending_transfer(api, applicant_headers, ehs_field_headers):
    """PRD §3.8: "Where the repaired branch reinstates, this branch revokes: the cited
    operating permit moves to `REVOKED`, and every transfer inspection on that permit
    whose status is `REQUESTED` or `BLOCKED` moves to `DENIED` with `certificate_grade`
    set to `UNSATISFACTORY`."
    PRD §3.8: "The parcel's `transfer_hold` stays true — a revoked operating permit
    holds the parcel on its own account, independently of the now-closed order — and
    `risk_tier` is re-derived, picking up the 35 points that a revoked permit
    contributes."
    PRD §3.9: "A denial moves the request `REQUESTED → DENIED` or `BLOCKED → DENIED`,
    sets `certificate_grade` to `UNSATISFACTORY`, and leaves both `certified_at` and
    `certificate_valid_until` null; it carries no preconditions."

    Design: Corner/state_machines/corner_repair_order_escalate_branch_revokes_permit_and_denies_pending_transfer
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S13"),
        site_address="44 Escalate Edge",
    )
    transfer = request_transfer_inspection(
        api,
        ctx["parcel_id"],
        ctx["operating_permit_id"],
        requester_headers=applicant_headers,
        requested_on="2026-05-03T00:00:00Z",
        buyer_name="Buyer Five",
        seller_name="Seller Five",
        inspection_mode="DESK_REVIEW",
    )
    order = open_and_issue_repair_order(
        api,
        ctx["operating_permit_id"],
        failure_type="SURFACING_EFFLUENT",
        reported_on="2026-05-03T00:00:00Z",
    )
    assert refresh_transfer_inspection(api, transfer["id"])["status"] == "BLOCKED"

    escalated = validate_success(
        api.resolve_repair_order(order["id"], {"outcome": "ESCALATE"}, ehs_field_headers), 200
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["severity"] == "URGENT"

    assert refresh_operating_permit(api, ctx["operating_permit_id"])["status"] == "REVOKED"

    certificate = refresh_transfer_inspection(api, transfer["id"])
    assert certificate["status"] == "DENIED"
    assert certificate["certificate_grade"] == "UNSATISFACTORY"
    assert certificate["certified_at"] is None
    assert certificate["certificate_valid_until"] is None

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["open_repair_order_count"] == 0
    assert parcel["transfer_hold"] is True
    assert parcel["risk_tier"] == "ELEVATED"
