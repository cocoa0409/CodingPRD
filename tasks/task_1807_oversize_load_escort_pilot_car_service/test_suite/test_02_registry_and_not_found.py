"""Carrier/escort registration defaults and the not-found error matrix."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    setup_booked_job,
    create_job_payload,
    create_assignment_payload,
    create_permit_payload,
    submit_survey_payload,
    assess_incident_payload,
    assert_carrier,
    assert_escort,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_carrier_creation_defaults(api):
    """PRD §3.1: "A freshly registered carrier starts with `ytd_billed_cents`
    at 0 and `credit_available_cents` equal to its full credit limit"
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every modification of the resource, including system-driven
    cascade mutations."

    Design: Corner/entities/carrier_creation_defaults
    """
    resp = api.create_carrier(
        {"carrier_name": "Defaults Co", "credit_limit_cents": 500000}, DISPATCHER
    )
    created = validate_success(resp, 201)
    assert_carrier(created)
    assert created["ytd_billed_cents"] == 0
    assert created["credit_available_cents"] == 500000
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert created["created_at"] == created["updated_at"]
    assert created["created_at"].endswith("Z") and "." in created["created_at"]

    fetched = validate_success(api.get_carrier(created["id"], DISPATCHER))
    assert fetched["ytd_billed_cents"] == 0
    assert fetched["credit_available_cents"] == 500000
    assert fetched["version"] == 1


def test_escort_creation_defaults(api):
    """PRD §3.1: "`has_height_pole`, which defaults to false when omitted, and
    `height_pole_max_inches`, which defaults to 0 but must be greater than zero
    whenever `has_height_pole` is true. A new escort begins with a
    `reliability_score` of 100, an `escort_status` of `ACTIVE`, and an
    `active_assignment_count` of 0."

    Design: Corner/entities/escort_creation_defaults
    """
    resp = api.create_escort(
        {"operator_name": "Plain Rider", "certified_state_codes": ["TX", "OK"]},
        DISPATCHER,
    )
    created = validate_success(resp, 201)
    assert_escort(created)
    assert created["has_height_pole"] is False, "omitted has_height_pole must default false"
    assert created["height_pole_max_inches"] == 0, "omitted height_pole_max_inches must default 0"
    assert created["reliability_score"] == 100
    assert created["escort_status"] == "ACTIVE"
    assert created["active_assignment_count"] == 0
    assert created["version"] == 1

    rows, _ = validate_paginated(api.list_escorts(DISPATCHER))
    listed = next(r for r in rows if r["id"] == created["id"])
    assert listed["reliability_score"] == 100
    assert listed["escort_status"] == "ACTIVE"
    assert listed["active_assignment_count"] == 0


def test_not_found_matrix(api):
    """PRD §2.8: "Endpoints that address nested resources validate path
    identifiers strictly left to right, and the request is rejected with the
    not-found error belonging to the first path identifier that does not
    resolve to an existing resource"
    PRD §2.8: "an assignment offer that names an unknown `escort_id` is
    rejected with `ERR_ESCORT_NOT_FOUND`"

    Design: Corner/errors/not_found_matrix
    """
    carrier = register_carrier(10_000_000, "NF Co")
    bundle = setup_booked_job(carrier)
    leg_id = bundle["leg"]["id"]

    NF = {
        "carrier": "00000000-0000-0000-0000-0000000000c1",
        "job": "00000000-0000-0000-0000-0000000000a1",
        "leg": "00000000-0000-0000-0000-0000000000b1",
        "permit": "00000000-0000-0000-0000-0000000000d1",
        "survey": "00000000-0000-0000-0000-0000000000e1",
        "assignment": "00000000-0000-0000-0000-0000000000f1",
        "delay": "00000000-0000-0000-0000-000000000001",
        "incident": "00000000-0000-0000-0000-000000000002",
        "invoice": "00000000-0000-0000-0000-000000000003",
        "escort": "00000000-0000-0000-0000-000000000004",
    }

    # Path-form carrier lookup.
    validate_error(api.get_carrier(NF["carrier"], DISPATCHER), ApiErrorId.ERR_CARRIER_NOT_FOUND)

    # Body-referenced carrier on job create (existence precedes ownership).
    ghost_headers = {
        "X-User-ID": NF["carrier"],
        "X-User-Role": "CarrierRep",
        "Content-Type": "application/json",
    }
    resp = api.create_job(create_job_payload(NF["carrier"]), ghost_headers)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)

    validate_error(api.get_job(NF["job"], DISPATCHER), ApiErrorId.ERR_JOB_NOT_FOUND)
    validate_error(
        api.create_permit(
            NF["leg"],
            create_permit_payload("X", "2026-08-09T00:00:00Z", "2026-08-12T00:00:00Z"),
            DISPATCHER,
        ),
        ApiErrorId.ERR_LEG_NOT_FOUND,
    )
    validate_error(api.issue_permit(NF["permit"], DISPATCHER), ApiErrorId.ERR_PERMIT_NOT_FOUND)
    validate_error(
        api.submit_survey(NF["survey"], submit_survey_payload(180), TEST_USERS["route_surveyor_headers"]),
        ApiErrorId.ERR_SURVEY_NOT_FOUND,
    )
    validate_error(
        api.accept_assignment(
            NF["assignment"],
            {"X-User-ID": "00000000-0000-0000-0000-0000000000e9", "X-User-Role": "EscortOperator"},
        ),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    )
    validate_error(api.close_delay_event(NF["delay"], DISPATCHER), ApiErrorId.ERR_DELAY_EVENT_NOT_FOUND)
    validate_error(
        api.assess_incident(NF["incident"], assess_incident_payload(50), TEST_USERS["safety_manager_headers"]),
        ApiErrorId.ERR_INCIDENT_NOT_FOUND,
    )
    validate_error(
        api.finalize_invoice(NF["invoice"], TEST_USERS["billing_clerk_headers"]),
        ApiErrorId.ERR_INVOICE_NOT_FOUND,
    )

    # Body-referenced escort on an existing leg.
    resp = api.create_assignment(leg_id, create_assignment_payload("REAR", NF["escort"]), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ESCORT_NOT_FOUND)
