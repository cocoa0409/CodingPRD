"""Compensating-invariant tests (core deposit conservation, warranty banked-hours
debit) and the technician-efficiency zero-actual-hours boundary.

Covers difficulty queue rules: compensating_invariant,
boundary_precision_check (efficiency null boundary).
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
)
from test_helpers.test_users import TEST_USERS, make_technician_headers
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# compensating_invariant — core return restores core_deposit_total_cents
# ===========================================================================
class TestCoreReturnRestoresDepositTotal:
    def test_return_sets_refunded_equal_to_deposit(self, api):
        """PRD §3.12: "it moves the core charge to `CORE_RETURNED`, sets
        `refunded_cents` equal to `deposit_cents`, subtracts that deposit from the
        order's `core_deposit_total_cents` to restore the core invariant, and
        recomputes the order's totals."

        Design: Difficulty/compensating_invariant/core_charge_return_restores_core_deposit_total
        """
        s = fx.setup_ro_with_charged_core(api, deposit_cents=3000, quantity=2, unit_cost_cents=8000)
        cc = s["core_charge"]
        assert cc["deposit_cents"] == 6000, "deposit = quantity(2) * 3000 = 6000"
        returned = validate_success(api.return_core_charge(cc["id"], PM), 200)
        assert returned["status"] == "CORE_RETURNED"
        assert returned["refunded_cents"] == 6000

    def test_return_zeroes_ro_core_deposit_total(self, api):
        """PRD §3.12: "subtracts that deposit from the order's
        `core_deposit_total_cents` to restore the core invariant, and recomputes the
        order's totals."

        Design: Difficulty/compensating_invariant/core_charge_return_restores_core_deposit_total
        """
        s = fx.setup_ro_with_charged_core(api, deposit_cents=3000, quantity=2, unit_cost_cents=8000)
        ro_before = validate_success(api.get_repair_order(s["ro"]["id"], SM), 200)
        assert ro_before["core_deposit_total_cents"] == 6000
        validate_success(api.return_core_charge(s["core_charge"]["id"], PM), 200)
        ro_after = validate_success(api.get_repair_order(s["ro"]["id"], SM), 200)
        # +6000 charged then -6000 returned nets to 0.
        assert ro_after["core_deposit_total_cents"] == 0


# ===========================================================================
# compensating_invariant — warranty comeback debit preserves banked_flat_hours
# ===========================================================================
class TestWarrantyComebackDebitPreservesBankedHours:
    def test_warranty_comeback_debits_original_tech_banked_flat_hours(self, api):
        """PRD §3.7: "If the completing order is itself a comeback, then
        additionally, for each warranty labor line on it, the original order's
        assigned technician has their `banked_flat_hours` reduced by that line's
        `book_hours` as a warranty penalty, and that original technician's
        `efficiency_pct` is then recomputed."

        Design: Difficulty/compensating_invariant/warranty_comeback_debit_preserves_shop_banked_flat_hours
        """
        result = _warranty_comeback_completed(api)
        orig_tech = validate_success(api.get_technician(result["tech_o"], SM), 200)
        # Original credited +2.0; warranty comeback debits -2.0 -> net 0.0.
        assert orig_tech["banked_flat_hours"] == 0.0, (
            f"original tech banked_flat_hours must net to 0.0, got {orig_tech['banked_flat_hours']}"
        )

    def test_warranty_labor_line_billed_zero(self, api):
        """PRD §3.5: "If the line is a warranty line (`is_warranty` true), its
        `charge_cents` is zero regardless of anything else."

        Design: Difficulty/compensating_invariant/warranty_comeback_debit_preserves_shop_banked_flat_hours
        """
        result = _warranty_comeback_completed(api)
        ll_c = validate_success(api.get_labor_line(result["ll_c"], SM), 200)
        assert ll_c["charge_cents"] == 0, "is_warranty line must bill at zero"


def _warranty_comeback_completed(api):
    """Original RO closed at 2026-01-01 (tech credited +2.0/+1.5). A within-warranty
    comeback at 2026-02-01 with one is_warranty labor line by a different tech is
    completed. Returns dict: tech_o, tech_c, ll_c, ro_c."""
    base = fx.setup_closed_original_ro(
        api,
        closed_clock="2026-01-01T08:00:00Z",
        odometer_miles=40000,
        book_hours=2.0,
        rate_cents=12000,
        clock_in_ts="2026-01-01T09:00:00Z",
        clock_out_ts="2026-01-01T10:30:00Z",
        bay_start="2026-01-01T09:00:00Z",
        bay_end="2026-01-01T13:00:00Z",
    )
    tech_o = base["technician"]["id"]
    operation_id = base["operation"]["id"]
    customer_id = base["customer"]["id"]
    vehicle_id = base["vehicle"]["id"]
    bay_id = base["bay"]["id"]

    # Advance into the warranty window and open a comeback.
    fx.set_clock(api, "2026-02-01T08:00:00Z")
    tech_c = fx.create_technician(api)["id"]
    ro_c = fx.create_repair_order(api, customer_id, vehicle_id, comeback_of_ro_id=base["ro"]["id"])
    ll_c = validate_success(
        api.create_labor_line(
            ro_c["id"],
            f.create_labor_line_payload(
                operation_id, technician_id=tech_c, billing_method="FLAT_RATE", is_warranty=True
            ),
            SM,
        ),
        201,
    )
    fx.authorize_ro(api, ro_c["id"], customer_id)
    fx.schedule_ro(api, ro_c["id"], bay_id, "2026-02-01T09:00:00Z", "2026-02-01T13:00:00Z")
    fx.transition_ro(api, ro_c["id"], "START")
    fx.clock_session_and_complete(api, ll_c["id"], tech_c,
                                  "2026-02-01T09:00:00Z", "2026-02-01T10:00:00Z")
    validate_success(api.complete_repair_order(ro_c["id"], make_technician_headers(tech_c)), 200)
    return {"tech_o": tech_o, "tech_c": tech_c, "ll_c": ll_c["id"], "ro_c": ro_c["id"]}


# ===========================================================================
# boundary_precision_check — efficiency_pct null on zero banked actual hours
# ===========================================================================
class TestEfficiencyZeroActualHoursIsNull:
    def test_fresh_technician_has_zero_banked_actual_hours(self, api):
        """PRD §3.1: "A new technician starts with `banked_flat_hours` of 0,
        `banked_actual_hours` of 0, and an `efficiency_pct` of null".

        Design: Difficulty/boundary_precision_check/efficiency_zero_actual_hours_is_null
        """
        tech = fx.create_technician(api)
        fetched = validate_success(api.get_technician(tech["id"], SM), 200)
        assert fetched["banked_actual_hours"] == 0

    def test_fresh_technician_efficiency_is_null(self, api):
        """PRD §3.7: "As a boundary rule, when `banked_actual_hours` is zero the
        `efficiency_pct` is null rather than zero — there is no division by zero."

        Design: Difficulty/boundary_precision_check/efficiency_zero_actual_hours_is_null
        """
        tech = fx.create_technician(api)
        fetched = validate_success(api.get_technician(tech["id"], SM), 200)
        assert fetched["efficiency_pct"] is None, (
            f"efficiency_pct must be null when banked_actual_hours==0, got {fetched['efficiency_pct']}"
        )
