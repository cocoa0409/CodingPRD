"""Technician earnings under the two pay models: per-appointment commission vs
booth-rent line earning, and the statement-level sum-then-round divergence from
per-line rounding."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_station, make_menu_item, make_technician, make_client,
    drive_to_in_service, checkout, drive_to_completed, make_draft_statement,
    set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual-variant per-appointment earning (COMMISSION vs BOOTH_RENT)
# ---------------------------------------------------------------------------
def test_commission_technician_earning_keeps_complement_share(api):
    """PRD §3.11: "For a `COMMISSION` technician, the earning is `subtotal_cents`
    multiplied by the complement of `commission_pct` (that is, one minus
    `commission_pct`), rounded half up to whole cents; the salon retains the
    `commission_pct` share."

    Design: Difficulty/dual_variant_calc/technician_earning_commission_vs_booth_per_appointment
    """
    set_clock("2026-03-01T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=6000, duration_minutes=45,
                          requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-01T13:00:00Z")
    completed = checkout(started["id"], started["version"])
    # round_half_up(6000 * (1 - 0.40)) = 3600.
    assert completed["technician_earning_cents"] == 3600


def test_booth_rent_technician_earning_is_full_subtotal(api):
    """PRD §3.11: "For a `BOOTH_RENT` technician, the earning is the full
    `subtotal_cents` at the line — booth-rent technicians keep 100% of
    per-appointment service revenue, because their flat booth rent is withheld once
    per statement rather than per appointment, so per-appointment salon retention
    is 0."

    Design: Difficulty/dual_variant_calc/technician_earning_commission_vs_booth_per_appointment
    """
    set_clock("2026-03-01T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=6000, duration_minutes=45,
                          requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="BOOTH_RENT", booth_rent_cents=5000)
    client = make_client()
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-01T15:00:00Z")
    completed = checkout(started["id"], started["version"])
    assert completed["technician_earning_cents"] == 6000


# ---------------------------------------------------------------------------
# Difficulty: statement sum-then-round vs per-line rounding order
# ---------------------------------------------------------------------------
def test_statement_payout_uses_sum_then_round(api):
    """PRD §3.16: "the rounding order is pinned to **sum-then-round**: aggregate the
    gross over all swept appointments first, then apply the complement of
    `commission_pct` (one minus `commission_pct`) once to that aggregate, rounding
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/statement_sum_then_round_vs_per_line_rounding_order
    """
    set_clock("2026-06-01T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=333, duration_minutes=15,
                          requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.35)
    client = make_client()
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="APPOINTMENT", start_at="2026-06-01T10:00:00Z")
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="APPOINTMENT", start_at="2026-06-01T12:00:00Z")
    stmt = make_draft_statement(tech["id"], "2026-06-01T00:00:00Z",
                                "2026-06-02T00:00:00Z")

    settled = validate_success(api.settle_commission_statement(stmt["id"], MANAGER))
    assert settled["gross_service_cents"] == 666
    # sum-then-round: round_half_up(666 * 0.65) = round_half_up(432.9) = 433.
    assert settled["technician_payout_cents"] == 433


def test_statement_sweeps_all_completed_in_window(api):
    """PRD §3.16: "The `swept_appointment_count` is the number of appointments
    swept, and `gross_service_cents` is the sum of their `subtotal_cents` (add-ons
    included)."

    Design: Difficulty/combinatorial_formula/statement_sum_then_round_vs_per_line_rounding_order
    """
    set_clock("2026-06-01T00:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=333, duration_minutes=15,
                          requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.35)
    client = make_client()
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="APPOINTMENT", start_at="2026-06-01T10:00:00Z")
    drive_to_completed(client["id"], tech["id"], station["id"], menu["id"],
                       origin="APPOINTMENT", start_at="2026-06-01T12:00:00Z")
    stmt = make_draft_statement(tech["id"], "2026-06-01T00:00:00Z",
                                "2026-06-02T00:00:00Z")

    settled = validate_success(api.settle_commission_statement(stmt["id"], MANAGER))
    assert settled["swept_appointment_count"] == 2
