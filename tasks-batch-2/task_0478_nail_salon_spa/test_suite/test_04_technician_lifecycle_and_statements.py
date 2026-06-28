"""Technician lifecycle (suspend/reinstate/terminate guards), commission-statement
settlement side effects, booth-rent payout flooring, period-window exclusion, and
the menu-item retire action."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    setup_base, make_station, make_menu_item, make_technician, make_client,
    drive_to_completed, make_draft_statement, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_technician_reinstate_revert_cycle(api):
    """PRD §3.1: "Suspending an `ACTIVE` technician transitions `status` to
    `SUSPENDED`".
    PRD §3.1: "Reinstating a `SUSPENDED` technician returns `status` to `ACTIVE`,
    but only if the technician's `license_expiry` is strictly after the current
    logical clock".

    Design: Corner/state_machines/technician_reinstate_revert_cycle
    """
    set_clock("2026-07-07T12:00:00Z")
    station = make_station(requires_autoclave=False)
    tech = make_technician(station["id"], license_expiry="2027-01-01T00:00:00Z")
    validate_success(api.suspend_technician(tech["id"], MANAGER))

    reinstated = validate_success(api.reinstate_technician(tech["id"], MANAGER))
    assert reinstated["status"] == "ACTIVE"


def test_terminate_active_technician_rejected_invalid_state(api):
    """PRD §3.1: "Terminating a `SUSPENDED` technician moves `status` to
    `TERMINATED`, the terminal state, but only when the technician's
    `accrued_earnings_cents` equals 0".

    Design: Corner/state_machines/terminate_active_technician_rejected_invalid_state
    """
    station = make_station(requires_autoclave=False)
    tech = make_technician(station["id"])  # never suspended -> still ACTIVE
    res = api.terminate_technician(tech["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_commission_statement_settle_resets_accrual_bubble(api):
    """PRD §3.16: "Settling resets the technician's `accrued_earnings_cents` to 0
    and increments the statement's `version` by one."
    PRD §3.16: "the rounding order is pinned to **sum-then-round**: aggregate the
    gross over all swept appointments first, then apply the complement of
    `commission_pct` (one minus `commission_pct`) once to that aggregate, rounding
    half up to whole cents."

    Design: Corner/state_machines/commission_statement_settle_resets_accrual_bubble
    """
    set_clock("2026-07-09T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="WALK_IN")
    stmt = make_draft_statement(tech["id"], "2026-07-09T00:00:00Z",
                                "2026-07-10T00:00:00Z")

    settled = validate_success(api.settle_commission_statement(stmt["id"], MANAGER))
    # gross 4500, commission_pct 0.40 -> payout round_half_up(4500*0.60) = 2700.
    assert settled["technician_payout_cents"] == 2700

    after = validate_success(api.get_technician(tech["id"], MANAGER))
    assert after["accrued_earnings_cents"] == 0


def test_booth_rent_statement_floors_at_zero(api):
    """PRD §3.16: "For a `BOOTH_RENT` technician, the payout is the gross minus the
    flat `booth_rent_cents`, floored at 0; the salon retains exactly
    `booth_rent_cents`, or the whole gross when the gross is smaller than the
    rent."

    Design: Corner/calculations/booth_rent_statement_floors_at_zero
    """
    set_clock("2026-07-12T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="BOOTH_RENT", booth_rent_cents=5000)
    client = make_client()
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="WALK_IN")
    stmt = make_draft_statement(tech["id"], "2026-07-12T00:00:00Z",
                                "2026-07-13T00:00:00Z")

    settled = validate_success(api.settle_commission_statement(stmt["id"], MANAGER))
    assert settled["gross_service_cents"] == 3000
    assert settled["technician_payout_cents"] == 0       # max(0, 3000-5000)
    assert settled["salon_retained_cents"] == 3000


def test_statement_excludes_appointment_outside_window(api):
    """PRD §3.16: "The sweep selects every appointment on the statement's
    `technician_id` whose `booking_status` is `COMPLETED` and whose completion
    instant ... falls within the half-open window from `period_start` (inclusive)
    up to `period_end` (exclusive)."

    Design: Corner/calculations/statement_excludes_appointment_outside_window
    """
    set_clock("2026-07-14T10:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    # Appointment COMPLETED at 2026-07-14T10:00; window is the prior day only.
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="WALK_IN")
    stmt = make_draft_statement(tech["id"], "2026-07-13T00:00:00Z",
                                "2026-07-14T00:00:00Z")

    settled = validate_success(api.settle_commission_statement(stmt["id"], MANAGER))
    assert settled["swept_appointment_count"] == 0
    assert settled["gross_service_cents"] == 0
    assert settled["technician_payout_cents"] == 0


def test_retire_menu_item_action_endpoint(api):
    """PRD §3.3: "Each item also has a system-managed `is_active` flag defaulting
    to true; the manager may retire an item, flipping `is_active` to false."

    Design: Corner/endpoints/retire_menu_item_action_endpoint
    """
    menu = make_menu_item(base_price_cents=3000, requires_sterile_station=False)
    retired = validate_success(api.retire_menu_item(menu["id"], MANAGER))
    assert retired["is_active"] is False
