"""Mediation reschedule cycle, sealing lifecycle, terminal lockdown, SoD, and sealed
listing (PRD §3.4, §3.7, §3.9, §2.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_mediator_headers, make_judge_headers, make_tenant_headers, TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


def test_mediation_reschedule_after_impasse_is_cyclic(api):
    """PRD §3.4: "An impassed session is not the end of the road: it may be rescheduled,
    moving from IMPASSE back to SCHEDULED with a fresh scheduled_at, and this loop may
    repeat as many times as needed."

    Design: Corner/state_machines/mediation_reschedule_after_impasse_is_cyclic
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    session = get_success_data(api.create_mediation_session(
        f.create_mediation_session_payload(ctx["case"]["id"], "med-1", "2026-05-05T10:00:00Z"),
        make_mediator_headers("med-1")))
    fx.set_clock(api, "2026-05-05T10:00:00Z")
    get_success_data(api.transition_mediation_session(
        session["id"], {"to_status": "HELD"}, make_mediator_headers("med-1")))
    get_success_data(api.transition_mediation_session(
        session["id"], {"to_status": "IMPASSE"}, make_mediator_headers("med-1")))
    data = get_success_data(api.transition_mediation_session(
        session["id"], {"to_status": "SCHEDULED", "scheduled_at": "2026-05-10T10:00:00Z"},
        make_mediator_headers("med-1")))
    assert data["status"] == "SCHEDULED"
    assert data["scheduled_at"] == "2026-05-10T10:00:00.000Z"


def test_sealing_grant_sets_case_sealed(api):
    """PRD §3.9: "Granting moves the request from REQUESTED to GRANTED, sets the parent
    case's sealed flag to true".

    Design: Corner/state_machines/sealing_grant_sets_case_sealed
    """
    ctx = fx.setup_dismissed_case(api, claimed_arrears_cents=600000)
    fx.set_clock(api, "2026-08-01T00:00:00Z")  # past closed_at(2026-05-01) + 90d
    sealing = fx.request_sealing(api, ctx, basis="DISMISSAL")
    granted = get_success_data(api.transition_sealing_request(
        sealing["id"], {"to_status": "GRANTED"}, make_judge_headers("judge-1")))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert granted["status"] == "GRANTED"
    assert case["sealed"] is True


def test_case_transition_from_terminal_returns_invalid_state(api):
    """PRD §2.8: "(6) state legality — the target resource is in a state from which the
    requested transition is legal, else ERR_INVALID_STATE". A DISMISSED case is terminal.

    Design: Corner/state_machines/case_transition_from_terminal_returns_invalid_state
    """
    ctx = fx.setup_dismissed_case(api, claimed_arrears_cents=600000)
    resp = api.transition_case(ctx["case"]["id"], {"to_status": "SERVED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_judge_who_mediated_returns_sod_violation(api):
    """PRD §3.7: "the judge entering a judgment must not be the same person recorded as
    the mediator_user_id on any mediation session of the case that reached HELD or
    AGREEMENT. A judge who mediated the case may not then rule on it, and the attempt is
    refused with ERR_SOD_VIOLATION."

    Design: Corner/validations/judge_who_mediated_returns_sod_violation
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    # Session conducted by mediator "u1" (both header identity and recorded field).
    session = get_success_data(api.create_mediation_session(
        f.create_mediation_session_payload(ctx["case"]["id"], "u1", "2026-05-05T10:00:00Z"),
        make_mediator_headers("u1")))
    fx.set_clock(api, "2026-05-05T10:00:00Z")
    get_success_data(api.transition_mediation_session(
        session["id"], {"to_status": "HELD"}, make_mediator_headers("u1")))
    fx.case_to_in_litigation(api, ctx["case"]["id"])
    resp = api.create_judgment(
        f.create_judgment_payload(ctx["case"]["id"], "POSSESSION"),
        make_judge_headers("u1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value, expected_status=409)


def test_sealing_before_waiting_period_returns_ineligible(api):
    """PRD §3.9: "the current logical-clock instant must be at or after closed_at plus a
    ninety-day waiting period (SEALING_WAIT_DAYS of 90) ... a request that fails any part
    of this test is refused with ERR_SEALING_INELIGIBLE."

    Design: Corner/validations/sealing_before_waiting_period_returns_ineligible
    """
    ctx = fx.setup_dismissed_case(api, claimed_arrears_cents=600000)
    # closed_at == clock default 2026-05-01; clock NOT advanced (< closed_at + 90d).
    resp = api.create_sealing_request(
        f.create_sealing_request_payload(ctx["case"]["id"], "DISMISSAL"),
        make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SEALING_INELIGIBLE.value, expected_status=409)


def test_sealed_case_excluded_from_default_list_included_with_flag(api):
    """PRD §3.9: "sets the parent case's sealed flag to true, and thereby removes the
    case from the default case listing; a sealed case is still directly retrievable by
    its identifier, and callers may opt back into seeing sealed cases in a listing by
    passing the include_sealed filter."

    Design: Corner/consistency_model/sealed_case_excluded_from_default_list_included_with_flag
    """
    ctx = fx.setup_sealed_case(api, claimed_arrears_cents=600000)
    case_id = ctx["case"]["id"]
    tenant_id = ctx["tenant"]["id"]

    default_list, _ = validate_paginated(api.list_cases(CLERK, params={"tenant_id": tenant_id}))
    assert case_id not in [c["id"] for c in default_list]

    with_sealed, _ = validate_paginated(api.list_cases(
        CLERK, params={"tenant_id": tenant_id, "include_sealed": "true"}))
    assert case_id in [c["id"] for c in with_sealed]
