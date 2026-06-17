"""State-machine transitions: initial states, valid transitions, invalid
transitions, terminal lockdown, idempotency.

Corner queue (B): section state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_site_floor_host, setup_site_host,
    create_site, create_floor, create_host,
    create_visit, screen_visit, create_cleared_visit, create_flagged_visit,
    create_contractor_pass, sign_in_visit, get_floor_version, set_clock,
    make_security_officer_headers,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_sign_out_from_preregistered_is_invalid_state(api):
    """PRD 3.6: "Signing a `SIGNED_IN` visitor out is also a `LobbyAttendant`
    operation and is permitted only while the visit is `SIGNED_IN`."
    PRD 2.7: "The state-machine guard comes sixth: a target resource that is not in a
    legal state for the requested transition yields `ERR_INVALID_STATE` (HTTP 409)."

    Sign-out on a PREREGISTERED visit -> ERR_INVALID_STATE; status unchanged.

    Design: Corner/state_machines/sign_out_from_preregistered_returns_invalid_state
    """
    site, floor, host = setup_site_floor_host()
    visit = create_visit(site["id"], host["id"], floor["id"],
                         visitor_full_name="Pre Reg", visitor_company="PreCo")
    res = api.sign_out_visit(visit["id"], LA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "PREREGISTERED", (
        f"expected PREREGISTERED, got {fetched['status']}"
    )


def test_suspend_revoked_contractor_pass_is_invalid_state(api):
    """PRD 3.7: "A pass may be revoked from either live state — `ACTIVE → REVOKED` or
    `SUSPENDED → REVOKED` — and `REVOKED` is terminal. Each of these transitions is
    permitted only from its stated source status; attempting one from any other
    status is rejected as an invalid state."

    After REVOKED (terminal), POST /suspend -> ERR_INVALID_STATE; status unchanged.

    Design: Corner/state_machines/revoke_then_suspend_terminal_lockdown_returns_invalid_state
    """
    site, host = setup_site_host()
    pass_ = create_contractor_pass(host["id"])
    get_success_data(api.revoke_contractor_pass(pass_["id"], SO))
    res = api.suspend_contractor_pass(pass_["id"], SO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_contractor_pass(pass_["id"], SO))
    assert fetched["status"] == "REVOKED", f"expected REVOKED, got {fetched['status']}"


def test_new_visit_starts_preregistered_with_zero_risk(api):
    """PRD 3.3: "A newly pre-registered visit begins in `PREREGISTERED` status with a
    `risk_score` of 0, and its system-managed `sign_in_at`, `sign_out_at`,
    `visit_duration_minutes`, and `badge_number` remain null until the relevant
    lifecycle moments."

    A freshly created visit has status PREREGISTERED and risk_score 0.

    Design: Corner/state_machines/new_visit_starts_in_preregistered
    """
    site, floor, host = setup_site_floor_host()
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "visitor_full_name": "Fresh V", "visitor_company": "FreshCo",
            "scheduled_start": "2026-06-16T09:00:00Z",
            "scheduled_end": "2026-06-16T11:00:00Z", "id_scanned": True,
        },
        LA,
    )
    visit = validate_success(res, 201)
    assert visit["status"] == "PREREGISTERED", (
        f"expected PREREGISTERED, got {visit['status']}"
    )
    assert visit["risk_score"] == 0, f"expected risk_score 0, got {visit['risk_score']}"


def test_second_signin_attempt_is_invalid_state(api):
    """PRD 3.6: "Signing a `CLEARED` visitor in is a `LobbyAttendant` operation ...
    Sign-in is permitted only while the visit is in `CLEARED` status."
    PRD 2.9: "For each `Floor`, `current_occupancy` is the count of visits with that
    `floor_id` currently in `SIGNED_IN` status".

    A second sign-in on an already SIGNED_IN visit -> ERR_INVALID_STATE; occupancy not
    double-counted (still 1).

    Design: Corner/state_machines/sign_in_idempotency_second_attempt_returns_invalid_state
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Once In", visitor_company="OnceCo")
    sign_in_visit(visit["id"], floor["id"])
    floor_v1 = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": floor_v1}, LA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    fetched_floor = validate_success(api.get_floor(floor["id"], LA))
    assert fetched_floor["current_occupancy"] == 1, (
        f"expected current_occupancy 1, got {fetched_floor['current_occupancy']}"
    )


def test_clean_visit_screens_to_cleared(api):
    """PRD 3.4: "On a CLEAR decision the screening auto-advances the visit from
    `SCREENING` to `CLEARED`."
    PRD 3.4: "otherwise the decision is CLEAR."

    Screening a visit with no matching watchlist entries auto-advances to CLEARED with
    risk_score 0.

    Design: Corner/state_machines/clear_clean_visit_from_screening_auto_advances
    """
    site, floor, host = setup_site_floor_host()
    visit = create_visit(site["id"], host["id"], floor["id"],
                         visitor_full_name="Clean V", visitor_company="CleanCo")
    screened = validate_success(api.screen_visit(visit["id"], LA))
    assert screened["status"] == "CLEARED", f"expected CLEARED, got {screened['status']}"
    assert screened["risk_score"] == 0, f"expected 0, got {screened['risk_score']}"


def test_officer_clears_flagged_visit_to_cleared(api):
    """PRD 3.4: "A `CLEAR` decision moves the visit `FLAGGED → CLEARED`".
    PRD 3.4: "Every successful clearance increments the visit's `version`."

    A SecurityOfficer (X-User-ID differs from host_id) clears a FLAGGED visit -> status
    CLEARED.

    Design: Corner/state_machines/clearance_clear_flagged_visit_by_officer_succeeds
    """
    site, floor, host = setup_site_floor_host()
    flagged = create_flagged_visit(site["id"], host["id"], floor["id"])
    assert flagged["status"] == "FLAGGED"
    res = api.clearance_visit(
        flagged["id"],
        {"decision": "CLEAR", "expected_visit_version": flagged["version"]},
        make_security_officer_headers("officer-1"),
    )
    cleared = validate_success(res)
    assert cleared["status"] == "CLEARED", f"expected CLEARED, got {cleared['status']}"
