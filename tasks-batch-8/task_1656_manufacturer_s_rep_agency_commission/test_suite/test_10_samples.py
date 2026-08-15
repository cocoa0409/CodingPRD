"""Sample and demo inventory: checkout windows, depreciation, conservation (PRD §3.8).

Covers the unit state gate, the step-depreciation charge with its residual floor,
the blocked-interval inspection buffer, and unit-count conservation across the
checkout loop.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    checkout_sample,
    convert_checkout,
    create_principal,
    create_rep,
    create_sample_unit,
    get_checkout,
    get_sample_unit,
    list_entries,
    list_units,
    make_rep_headers,
    parse_instant,
    return_checkout,
    set_clock,
    validate_error,
)


class TestCheckoutStateGate:
    def test_checkout_on_converted_unit_rejected(self, api):
        """PRD §3.8: "The unit must currently be `IN_STOCK` (else
        `ERR_INVALID_STATE_TRANSITION`)". PRD §3.8: "A rep who wants to keep the unit
        converts the checkout instead: the charge is the full depreciated value at
        conversion time, posted as a `SAMPLE_CHARGE` entry, the unit moves from
        `CHECKED_OUT` to `CONVERTED`". One day held is zero started months, so the
        depreciated value is the full 80,000c list.

        Design: Corner/state_machines/checkout_on_converted_unit_rejected
        """
        principal = create_principal()
        rep = create_rep("R1", ["CA"])
        unit = create_sample_unit(principal["id"], serial_number="S-1", value_cents=80_000)
        checkout = checkout_sample(unit["id"], rep["id"])
        set_clock("2026-08-02T00:00:00Z")
        converted = convert_checkout(checkout["id"], rep["id"])
        assert converted["charge_cents"] == 80000
        assert converted["status"] == "CONVERTED"

        resp = api.create_sample_checkout(
            {"sample_unit_id": unit["id"]}, make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_sample_unit(unit["id"])["status"] == "CONVERTED"


class TestDepreciationCharge:
    def test_sample_depreciation_step_and_residual_floor(self, api):
        """PRD §3.8: "The charge calculation counts the whole days between the
        checkout's `checked_out_at` and the event, then counts each started thirty-day
        month. The unit loses fifteen percent of list per started month, and the
        remaining factor is never allowed below twenty percent of list." and
        "Conversion and the overdue sweep charge the full depreciated value". Day 30
        is one started month (85% of 80,000c = 68,000c); 369 days is twelve started
        months, clamped to the 20% floor (16,000c).

        Design: Corner/calculations/sample_depreciation_step_and_residual_floor
        """
        principal = create_principal()
        rep = create_rep("R1", ["CA"])
        u_a = create_sample_unit(principal["id"], serial_number="S-A", value_cents=80_000)
        u_b = create_sample_unit(principal["id"], serial_number="S-B", value_cents=80_000)
        co_a = checkout_sample(u_a["id"], rep["id"])
        co_b = checkout_sample(u_b["id"], rep["id"])

        # Exactly due_at (day 30): not "past" it, so still OPEN and convertible.
        set_clock("2026-08-31T00:00:00Z")
        converted = convert_checkout(co_a["id"], rep["id"])
        assert converted["charge_cents"] == 68000
        assert converted["status"] == "CONVERTED"
        assert get_sample_unit(u_a["id"])["status"] == "CONVERTED"

        # 2026-08-01 -> 2027-08-05 is 369 days -> 12 started months -> floor.
        set_clock("2027-08-05T00:00:00Z")
        charged = get_checkout(co_b["id"])
        assert charged["status"] == "CHARGED"
        assert charged["charge_cents"] == 16000
        assert get_sample_unit(u_b["id"])["status"] == "WRITTEN_OFF"

        charges = sorted(
            e["amount_cents"]
            for e in list_entries(rep_id=rep["id"], entry_type="SAMPLE_CHARGE")
        )
        assert charges == [-68000, -16000]


class TestCheckoutBlockedInterval:
    def _setup_returned_unit(self, api):
        """Unit checked out at the default clock, returned SELLABLE on 2026-08-10."""
        principal = create_principal()
        rep = create_rep("R1", ["CA", "OR"])
        unit = create_sample_unit(principal["id"], serial_number="S-9", value_cents=80_000)
        checkout = checkout_sample(unit["id"], rep["id"])
        set_clock("2026-08-10T00:00:00Z")
        returned = return_checkout(checkout["id"], rep["id"], "SELLABLE")
        assert returned["status"] == "RETURNED"
        return principal, rep, unit, returned

    def test_checkout_inside_inspection_buffer_rejected(self, api):
        """PRD §3.8: "the unit is blocked while any checkout of it is still `OPEN`,
        and after the most recent checkout it stays blocked until one full day of
        inspection buffer has passed beyond that checkout's `returned_at` — or beyond
        its `due_at` if it never came back. A checkout attempted inside a blocked
        interval fails with `ERR_CHECKOUT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/sample_checkout_buffer_closed_interval
        """
        _principal, rep, unit, returned = self._setup_returned_unit(api)
        # Noon on return day: the one-day inspection buffer has not fully passed.
        set_clock("2026-08-10T12:00:00Z")
        resp = api.create_sample_checkout(
            {"sample_unit_id": unit["id"]}, make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECKOUT_WINDOW_CONFLICT)

    def test_checkout_at_buffer_end_allowed(self, api):
        """PRD §3.8: "A successful checkout is born `OPEN` with `checked_out_at`
        stamped from the clock and `due_at` set thirty days out, while the unit flips
        from `IN_STOCK` to `CHECKED_OUT`." One full day beyond the 2026-08-10 return
        is 2026-08-11 — the first unblocked instant.

        Design: Difficulty/resource_temporal_overlap/sample_checkout_buffer_closed_interval
        """
        _principal, rep, unit, returned = self._setup_returned_unit(api)
        set_clock("2026-08-11T00:00:00Z")
        checkout = checkout_sample(unit["id"], rep["id"])
        assert checkout["status"] == "OPEN"
        assert parse_instant(checkout["due_at"]) == datetime(
            2026, 9, 10, tzinfo=timezone.utc,
        ), "checked out 2026-08-11, due thirty days out"
        assert get_sample_unit(unit["id"])["status"] == "CHECKED_OUT"


class TestUnitCountConservation:
    def test_checkout_return_loop_conserves_unit(self, api):
        """PRD §3.8: "A successful checkout is born `OPEN` with `checked_out_at`
        stamped from the clock and `due_at` set thirty days out, while the unit flips
        from `IN_STOCK` to `CHECKED_OUT`." and "a `SELLABLE` unit goes back to
        `IN_STOCK` with a `charge_cents` of zero". The forward and compensating
        transitions move the same single unit between statuses — none is created or
        destroyed.

        Design: Difficulty/compensating_invariant/sample_unit_count_conservation
        """
        principal = create_principal()
        rep = create_rep("R1", ["CA"])
        unit = create_sample_unit(principal["id"], serial_number="S-1", value_cents=50_000)
        assert unit["status"] == "IN_STOCK"
        assert len(list_units(principal_id=principal["id"], status="IN_STOCK")) == 1

        checkout = checkout_sample(unit["id"], rep["id"])
        assert len(list_units(principal_id=principal["id"], status="IN_STOCK")) == 0
        assert len(list_units(principal_id=principal["id"], status="CHECKED_OUT")) == 1
        assert len(list_units(principal_id=principal["id"])) == 1

        returned = return_checkout(checkout["id"], rep["id"], "SELLABLE")
        assert returned["status"] == "RETURNED"
        assert returned["charge_cents"] == 0
        assert len(list_units(principal_id=principal["id"], status="IN_STOCK")) == 1

    def test_unit_identity_preserved_across_loop(self, api):
        """PRD §3.8: "A successful checkout is born `OPEN` with `checked_out_at`
        stamped from the clock and `due_at` set thirty days out, while the unit flips
        from `IN_STOCK` to `CHECKED_OUT`." and "Either way `returned_at` takes the
        clock and the checkout moves from `OPEN` to `RETURNED`." The unit record
        observed after the loop is the same id registered at the start — quantity is
        conserved with no duplicate materialized.

        Design: Difficulty/compensating_invariant/sample_unit_count_conservation
        """
        principal = create_principal()
        rep = create_rep("R1", ["CA"])
        unit = create_sample_unit(principal["id"], serial_number="S-1", value_cents=50_000)
        checkout = checkout_sample(unit["id"], rep["id"])
        assert checkout["sample_unit_id"] == unit["id"]

        return_checkout(checkout["id"], rep["id"], "SELLABLE")
        units = list_units(principal_id=principal["id"])
        assert len(units) == 1
        assert units[0]["id"] == unit["id"]
        assert units[0]["status"] == "IN_STOCK"
        assert get_checkout(checkout["id"])["status"] == "RETURNED"
