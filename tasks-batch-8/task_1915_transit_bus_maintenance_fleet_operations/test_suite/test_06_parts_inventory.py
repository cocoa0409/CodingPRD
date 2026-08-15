"""Parts inventory: computed stock fields, reservation guards, supersession,
issue/return conservation, and the core-exchange credit tiers."""
from test_helpers import (
    ApiErrorId,
    assert_part,
    assert_part_line,
    assert_part_stock_invariants,
    create_in_progress_wo,
    create_part_payload,
    get_success_data,
    issue_line,
    line_event,
    new_bus,
    new_mechanic,
    new_part,
    reserve_line,
    run_epoch,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_part_computed_fields_derive_from_stock_inputs(api):
    """PRD §3.6: "A part's **available quantity** is its `quantity_on_hand`
    minus its `quantity_reserved`; it may go negative after a write-down. The
    derived `stock_status` classifies the part: `NORMAL` when the available
    quantity is strictly greater than `reorder_point`; `LOW_STOCK` when it is
    between zero and `reorder_point` inclusive; and `BACKORDERED` when it is
    negative."
    PRD §3.6: "At creation, `quantity_on_hand` is seeded from
    `initial_on_hand`, `quantity_reserved` starts at zero, and
    `superseded_by_id` is null while the part is current."

    Design: Corner/entities/part_computed_fields_derive_from_stock_inputs
    """
    part = validate_success(
        api.create_part(
            create_part_payload(sku="P-CMP", description="Computed check",
                                unit_cost_cents=1_000, reorder_point=2,
                                initial_on_hand=7),
            fx.PC,
        ),
        201,
    )
    assert_part(part)
    assert part["quantity_on_hand"] == 7
    assert part["quantity_reserved"] == 0
    assert part["quantity_available"] == 7
    assert part["stock_status"] == "NORMAL", "7 > reorder_point 2"
    assert part["superseded_by_id"] is None


def test_part_stock_insufficient_rejected(api):
    """PRD §3.6: "Two referential checks run at reserve: the part's
    `quantity_available` must be at least `qty` (otherwise
    `ERR_PART_STOCK_INSUFFICIENT`)"

    Design: Corner/validations/part_stock_insufficient_rejected
    """
    bus = new_bus(initial_odometer_miles=100,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-Y37", description="Scarce relay",
                    unit_cost_cents=1_500, initial_on_hand=2)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=4_500)

    res = api.create_part_line(wo["id"], {"part_id": part["id"], "qty": 3}, fx.PC)
    validate_error(res, ApiErrorId.ERR_PART_STOCK_INSUFFICIENT)

    after = get_success_data(api.get_part(part["id"], fx.PC))
    assert after["quantity_on_hand"] == 2
    assert after["quantity_reserved"] == 0, "a rejected reserve must not mutate stock"


def test_superseded_part_cannot_be_reserved(api):
    """PRD §3.6: "A `PartsClerk` marks the current part with a `new_part_id`
    reference; the system sets `superseded_by_id` on the current part, and
    subsequent reservation attempts against it are rejected with
    `ERR_PART_SUPERSEDED`."

    Design: Corner/validations/superseded_part_cannot_be_reserved
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    old = new_part(sku="P-OLD", description="Old valve", unit_cost_cents=1_000,
                   initial_on_hand=5)
    new = new_part(sku="P-NEW", description="New valve", unit_cost_cents=1_100,
                   initial_on_hand=5)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=2_000)
    validate_success(
        api.supersede_part(old["id"], {"new_part_id": new["id"]}, fx.PC)
    )

    res = api.create_part_line(wo["id"], {"part_id": old["id"], "qty": 1}, fx.PC)
    validate_error(res, ApiErrorId.ERR_PART_SUPERSEDED)

    line = validate_success(
        api.create_part_line(wo["id"], {"part_id": new["id"], "qty": 1}, fx.PC), 201
    )
    assert_part_line(line)
    assert line["issue_status"] == "RESERVED", (
        "the replacement SKU remains reservable"
    )


def test_core_return_on_non_core_line_rejected(api):
    """PRD §3.6: "A `CORE_RETURN` against a line whose `core_status` is not
    `CORE_PENDING` or `CORE_LATE` is rejected with `ERR_CORE_NOT_PENDING`."

    Design: Corner/validations/core_return_on_non_core_line_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-Y19", description="Wiper", unit_cost_cents=800,
                    initial_on_hand=5)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=800)
    line = reserve_line(wo["id"], part["id"], qty=1)
    issue_line(line["id"], mechanic=lead)

    res = line_event(line["id"], "CORE_RETURN", core_condition="GOOD")
    validate_error(res, ApiErrorId.ERR_CORE_NOT_PENDING)
    after = get_success_data(api.get_part_line(line["id"], fx.PC))
    assert after["core_status"] == "NONE", (
        "a CONSUMABLE line's core dimension never leaves NONE"
    )


def test_core_late_tier_half_credit_and_grace_expiry(api):
    """PRD §3.6: "The epoch sweep ages a `CORE_PENDING` line past its due date
    to `CORE_LATE`, and a `CORE_LATE` line more than 15 days past due to
    `CORE_REJECTED`."
    PRD §3.6: "A return with `core_condition` `GOOD` is tiered by timing: on or
    before `core_due_date`, the credit is the full `core_charge_cents`
    multiplied by `qty` and the line moves to `CORE_CREDITED`; after
    `core_due_date` but on or before 15 days past it, the credit is half —
    computed as `core_charge_cents` multiplied by `qty` multiplied by 0.50 and
    rounded half-up — and the line likewise moves to `CORE_CREDITED`; more than
    15 days past due, the return is rejected with no credit (`CORE_REJECTED`)."

    Both cores issued at clock 2026-08-01 have due date 2026-08-31.

    Design: Corner/calculations/core_late_tier_half_credit_and_grace_expiry
    """
    bus = new_bus(fleet_number="K2", vin="VINK2", initial_odometer_miles=100,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-K2", description="Starter core",
                    part_class="REBUILDABLE_CORE", unit_cost_cents=25_000,
                    initial_on_hand=5, core_charge_cents=10_000)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_labor_hours=2,
                               estimated_cost_cents=50_000)
    line_a = reserve_line(wo["id"], part["id"], qty=1)
    line_b = reserve_line(wo["id"], part["id"], qty=1)
    issue_line(line_a["id"], mechanic=lead)
    issue_line(line_b["id"], mechanic=lead)

    # 5 days past due: within the 15-day late grace -> half credit.
    set_clock("2026-09-05T00:00:00Z")
    run_epoch()
    line_a_after = get_success_data(api.get_part_line(line_a["id"], fx.PC))
    assert line_a_after["core_status"] == "CORE_LATE"
    credited = validate_success(
        line_event(line_a["id"], "CORE_RETURN", core_condition="GOOD")
    )
    assert credited["core_status"] == "CORE_CREDITED"
    wo_after = get_success_data(api.get_work_order(wo["id"], fx.PC))
    assert wo_after["core_credits_cents"] == 5_000, (
        f"late GOOD return earns the 50% tier: 5000, got "
        f"{wo_after['core_credits_cents']}"
    )

    # 20 days past due (due+15 == 2026-09-15): sweep rejects the second core.
    set_clock("2026-09-20T00:00:00Z")
    run_epoch()
    line_b_after = get_success_data(api.get_part_line(line_b["id"], fx.PC))
    assert line_b_after["core_status"] == "CORE_REJECTED", (
        "past due+15 the sweep rejects the core with no credit"
    )
    res = line_event(line_b["id"], "CORE_RETURN", core_condition="GOOD")
    validate_error(res, ApiErrorId.ERR_CORE_NOT_PENDING)


class TestIssueReturnConservation:
    """Physical stock units are conserved across ISSUE + RETURN_UNUSED."""

    def _setup(self):
        bus = new_bus(fleet_number="V1", vin="VINV1", model_year=2022,
                      base_warranty_expiry_miles=5_000,
                      base_warranty_expiry_date="2024-01-01")
        part = new_part(sku="P-FIL", description="Filter",
                        unit_cost_cents=3_000, initial_on_hand=10)
        lead = new_mechanic(name="Lead", employee_ref="E110")
        wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=12_000)
        return bus, part, lead, wo

    def test_reserve_then_issue_move_quantities(self, api):
        """PRD §3.6: "On a successful reserve, the line starts in
        `issue_status` `RESERVED` with `core_status` `NONE`, with `qty_issued`
        initialized to zero; the part's `quantity_reserved` is increased by
        `qty`; the line's `unit_cost_cents` snapshots the part's current
        `unit_cost_cents`; and `stock_status` is recomputed."
        PRD §3.6: "On issue the part's `quantity_on_hand` and
        `quantity_reserved` are each decremented by `qty`, and `stock_status`
        is recomputed."

        Design: Difficulty/compensating_invariant/parts_issue_return_unused_conserve_on_hand_units
        """
        _, part, lead, wo = self._setup()
        line = reserve_line(wo["id"], part["id"], qty=4)
        assert line["unit_cost_cents"] == 3_000, "reservation snapshots unit cost"

        after_reserve = get_success_data(api.get_part(part["id"], fx.PC))
        assert after_reserve["quantity_on_hand"] == 10
        assert after_reserve["quantity_reserved"] == 4
        assert after_reserve["quantity_available"] == 6

        issue_line(line["id"], mechanic=lead)
        after_issue = get_success_data(api.get_part(part["id"], fx.PC))
        assert after_issue["quantity_on_hand"] == 6
        assert after_issue["quantity_reserved"] == 0
        assert_part_stock_invariants(after_issue)

    def test_return_unused_restores_exactly(self, api):
        """PRD §3.6: "On return the part's `quantity_on_hand` is incremented by
        `qty`, `stock_status` is recomputed, the work order's
        `core_charges_accrued_cents` is decreased by `core_charge_cents`
        multiplied by `qty` (reversing the accrual), and the line's
        `core_status` becomes `CORE_REJECTED` with no credit posted."
        PRD §3.5: "A `RETURNED` line contributes zero."

        Design: Difficulty/compensating_invariant/parts_issue_return_unused_conserve_on_hand_units
        """
        _, part, lead, wo = self._setup()
        line = reserve_line(wo["id"], part["id"], qty=4)
        issue_line(line["id"], mechanic=lead)
        returned = validate_success(line_event(line["id"], "RETURN_UNUSED"))
        assert returned["issue_status"] == "RETURNED"

        after = get_success_data(api.get_part(part["id"], fx.PC))
        assert after["quantity_on_hand"] == 10, "compensation restores on-hand"
        assert after["quantity_reserved"] == 0
        assert after["quantity_available"] == 10, "no drift after issue+return"

        wo_after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert wo_after["parts_total_cents"] == 0, (
            "RETURNED lines contribute nothing to parts_total_cents"
        )


class TestCoreAccrualOnTimeCreditInvariant:
    """Core liability in cents nets to zero after an on-time GOOD return."""

    def _setup(self):
        bus = new_bus(fleet_number="K1", vin="VINK1", model_year=2022,
                      base_warranty_expiry_miles=5_000,
                      base_warranty_expiry_date="2024-01-01")
        part = new_part(sku="P-ALT", description="Alternator core",
                        part_class="REBUILDABLE_CORE", unit_cost_cents=25_000,
                        initial_on_hand=3, core_charge_cents=10_000)
        lead = new_mechanic(name="Lead", employee_ref="E120")
        wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=25_000)
        line = reserve_line(wo["id"], part["id"], qty=1)
        return bus, part, lead, wo, line

    def test_issue_accrues_core_charge_with_due_date(self, api):
        """PRD §3.6: "If the line's part is a `REBUILDABLE_CORE`, the work
        order's `core_charges_accrued_cents` is increased by
        `core_charge_cents` multiplied by `qty`, the line's `core_status` moves
        from `NONE` to `CORE_PENDING`, and `core_due_date` is set to the issue
        clock date plus 30 days."

        Issue at clock 2026-08-01 -> due 2026-08-31.

        Design: Difficulty/compensating_invariant/core_accrue_and_on_time_credit_net_zero_liability
        """
        _, _, lead, wo, line = self._setup()
        issued = issue_line(line["id"], mechanic=lead)
        assert issued["core_status"] == "CORE_PENDING"
        assert issued["core_due_date"] == "2026-08-31", (
            f"issue clock date + 30 days; got {issued['core_due_date']}"
        )
        wo_after = get_success_data(api.get_work_order(wo["id"], fx.PC))
        assert wo_after["core_charges_accrued_cents"] == 10_000

    def test_on_time_good_return_nets_zero(self, api):
        """PRD §3.6: "A return with `core_condition` `GOOD` is tiered by
        timing: on or before `core_due_date`, the credit is the full
        `core_charge_cents` multiplied by `qty` and the line moves to
        `CORE_CREDITED`"
        PRD §3.6: "The core machinery has a conserved-quantity invariant:
        after an on-time `GOOD` return of the full `qty`, the line's
        accrued-minus-credited amount is zero."
        PRD §3.5: "`parts_net_cents` is `parts_total_cents` minus
        `core_credits_cents`, and `total_cost_cents` is `labor_total_cents`
        plus `parts_net_cents`."

        Design: Difficulty/compensating_invariant/core_accrue_and_on_time_credit_net_zero_liability
        """
        _, _, lead, wo, line = self._setup()
        issue_line(line["id"], mechanic=lead)
        credited = validate_success(
            line_event(line["id"], "CORE_RETURN", core_condition="GOOD")
        )
        assert credited["core_status"] == "CORE_CREDITED"

        wo_after = get_success_data(api.get_work_order(wo["id"], fx.PC))
        accrued = wo_after["core_charges_accrued_cents"]
        credits = wo_after["core_credits_cents"]
        assert accrued == 10_000 and credits == 10_000
        assert accrued - credits == 0, "core liability nets to zero"
        assert wo_after["parts_total_cents"] == 25_000
        assert wo_after["parts_net_cents"] == 15_000, (
            "the 10000 credit offsets parts cost exactly"
        )
