"""Admission freeze cycle, gate check-in, wristband band, and the cross-entity
gate that assignment/check-in place on EntryWindow.status (PRD §3.4, §3.5)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    setup_confirmed_admission, setup_season_pass_confirmed, get_window,
)

PM = TEST_USERS["park_manager_headers"]
GA = TEST_USERS["gate_agent_headers"]


# ───────────────── Queue A: non_linear_state_machine (freeze cycle) ─────────────────

def test_admission_freeze_then_unfreeze_returns_to_confirmed(api):
    """PRD §3.5: "A guest may freeze an admission that is currently CONFIRMED,
    moving it to FROZEN"
    PRD §3.5: "Unfreezing returns a FROZEN admission to CONFIRMED."

    Design: Difficulty/non_linear_state_machine/admission_freeze_unfreeze_cycle
    """
    ctx = setup_season_pass_confirmed(clock="2026-06-01T00:00:00Z")
    adm_id = ctx["admission"]["id"]
    gh = make_guest_headers(ctx["guest"]["id"])
    frozen = get_success_data(api_client.freeze_admission(adm_id, gh))
    assert frozen["status"] == "FROZEN", f"expected FROZEN, got {frozen['status']}"
    back = get_success_data(api_client.unfreeze_admission(adm_id, gh))
    assert back["status"] == "CONFIRMED", f"cycle should close to CONFIRMED, got {back['status']}"


def test_admission_freeze_cycle_repeatable(api):
    """PRD §3.5: "A guest may freeze an admission that is currently CONFIRMED,
    moving it to FROZEN"
    PRD §3.5: "Unfreezing returns a FROZEN admission to CONFIRMED."

    Design: Difficulty/non_linear_state_machine/admission_freeze_unfreeze_cycle
    """
    ctx = setup_season_pass_confirmed(clock="2026-06-01T00:00:00Z")
    adm_id = ctx["admission"]["id"]
    gh = make_guest_headers(ctx["guest"]["id"])
    # First loop.
    get_success_data(api_client.freeze_admission(adm_id, gh))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-06-02T00:00:00Z"}, PM))
    after1 = get_success_data(api_client.unfreeze_admission(adm_id, gh))
    assert after1["status"] == "CONFIRMED"
    # Re-enter FROZEN.
    second = get_success_data(api_client.freeze_admission(adm_id, gh))
    assert second["status"] == "FROZEN", "same admission must be re-freezable (true cycle)"


# ───────────────── Queue B: validations / calculations (check-in, band, freeze) ─────────────────

def test_freeze_day_ticket_rejected(api):
    """PRD §3.5: "a freeze (or unfreeze) attempted on a DAY_TICKET admission is
    rejected with ERR_FREEZE_NOT_ALLOWED."

    Design: Corner/validations/freeze_day_ticket_returns_freeze_not_allowed
    """
    ctx = setup_confirmed_admission(product_type="DAY_TICKET")
    res = api_client.freeze_admission(ctx["admission"]["id"],
                                     make_guest_headers(ctx["guest"]["id"]))
    validate_error(res, "ERR_FREEZE_NOT_ALLOWED")


def test_checkin_without_bound_guest_rejected(api):
    """PRD §3.4: "It requires that the admission be CONFIRMED, that its window's
    status be OPEN (otherwise ERR_WINDOW_NOT_OPEN), that a guest_id be bound
    (otherwise ERR_GUEST_NOT_BOUND)"

    Design: Corner/validations/checkin_without_bound_guest_returns_guest_not_bound
    """
    # Build a CONFIRMED admission with NO guest bound: assign-window requires only
    # ISSUED + FULFILLED + OPEN window, so we skip bind-guest.
    from test_helpers import setup_issued_admission
    ctx = setup_issued_admission(clock="2026-07-01T10:00:00Z")
    gh = make_guest_headers(ctx["guest"]["id"])
    adm = ctx["admissions"][0]
    fresh = get_window(ctx["window"]["id"])
    get_success_data(api_client.assign_window(
        adm["id"], {"entry_window_id": ctx["window"]["id"],
                    "expected_entry_window_version": fresh["version"]}, gh))
    res = api_client.check_in_admission(adm["id"], GA)
    validate_error(res, "ERR_GUEST_NOT_BOUND")


def test_band_yellow_floor_boundary_at_107cm(api):
    """PRD §3.4: "a height of at least 107 but below 122 centimeters earns YELLOW
    (most attractions)"
    PRD §3.4: "the comparison is exact integer-against-floor, so a height equal to a
    floor takes the higher band."

    Design: Difficulty/boundary_precision_check/band_color_yellow_floor_boundary_on_checkin
    """
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z",
                                    guest_overrides={"height_cm": 107})
    checked = get_success_data(api_client.check_in_admission(ctx["admission"]["id"], GA))
    assert checked["band_color"] == "YELLOW", \
        f"height 107 == YELLOW_MIN_CM should be YELLOW, got {checked['band_color']}"


def test_band_red_below_yellow_floor_at_106cm(api):
    """PRD §3.4: "any lesser height earns RED (kiddie area only)"
    PRD §3.4: "a height of at least 107 but below 122 centimeters earns YELLOW
    (most attractions)"

    Design: Difficulty/boundary_precision_check/band_color_yellow_floor_boundary_on_checkin
    """
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z",
                                    guest_overrides={"height_cm": 106})
    checked = get_success_data(api_client.check_in_admission(ctx["admission"]["id"], GA))
    assert checked["band_color"] == "RED", \
        f"height 106 (below YELLOW floor 107) should be RED, got {checked['band_color']}"


# ───────────────── Queue A: cross_entity_state_dependency (assign requires OPEN) ─────────────────

def test_assign_window_requires_window_open(api):
    """PRD §3.4: "Assignment is allowed only when the admission is ISSUED, its parent
    order's fulfillment_status is FULFILLED (otherwise ERR_ORDER_NOT_PAID), the target
    window's status is OPEN (otherwise ERR_WINDOW_NOT_OPEN)"

    Design: Difficulty/cross_entity_state_dependency/assign_window_requires_window_open
    """
    from test_helpers import setup_issued_admission
    ctx = setup_issued_admission()
    gh = make_guest_headers(ctx["guest"]["id"])
    adm = ctx["admissions"][0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    # Restrict the window so it is no longer OPEN.
    get_success_data(api_client.restrict_entry_window(ctx["window"]["id"], PM))
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        adm["id"], {"entry_window_id": ctx["window"]["id"],
                    "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_WINDOW_NOT_OPEN")


def test_assign_window_to_restricted_window_blocked_even_when_room(api):
    """PRD §3.4: "the target window's status is OPEN (otherwise ERR_WINDOW_NOT_OPEN)"
    PRD §3.1: "Restricting a window moves it from OPEN to RESTRICTED, which keeps
    existing reservations valid but blocks new assignment"

    Design: Difficulty/cross_entity_state_dependency/assign_window_requires_window_open
    """
    from test_helpers import setup_issued_admission
    ctx = setup_issued_admission(window_overrides={"window_capacity": 50})
    gh = make_guest_headers(ctx["guest"]["id"])
    adm = ctx["admissions"][0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    get_success_data(api_client.restrict_entry_window(ctx["window"]["id"], PM))
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        adm["id"], {"entry_window_id": ctx["window"]["id"],
                    "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_WINDOW_NOT_OPEN")
