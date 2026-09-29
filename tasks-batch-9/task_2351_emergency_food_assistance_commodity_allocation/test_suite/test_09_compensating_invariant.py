"""Forward-then-reverse pairs that must land back on the exact pre-operation figures."""

from test_helpers import (
    AllocationStatus,
    DistributionStatus,
    DrawPosture,
    FormulaVariant,
    LotStatus,
    OrderStatus,
    assert_lot_ledger,
    assert_pounds,
    assert_ratio,
    fixtures as fx,
    program_case_total,
)

PEACH_CODE = "CANNED_PEACHES"


def _approved_ten_case_order(api):
    """A 10-case peach order approved against a 1001-case entitlement."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    peaches = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        peaches["id"],
        warehouse["id"],
        federal_lot_code="FL-P-001",
        cases_received=300,
        pack_date="2026-05-01",
        best_by_date="2028-05-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27COMP",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[PEACH_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], peaches["id"], 10)
    fx.submit_order(api, order["id"], agency["id"])
    fx.approve_order(api, order["id"])
    return {"agency": agency, "cycle": cycle, "lot": lot, "order": order}


def test_01_approval_commits_the_cases_it_reserved(api):
    """PRD §2.9: "Approval adds each line's reserved cases to that lot's
    `cases_committed` and adds the order's `total_cases_approved` to the allocation's
    `cases_committed`." PRD §2.11: "it reads `NOT_STARTED` while every entitlement of
    the cycle is still `ENTITLED`, `FULLY_DRAWN` only when every entitlement of the
    cycle is `FULLY_DRAWN`, and `PARTIAL` in every other case."

    Design: Difficulty/compensating_invariant/order_cancel_returns_case_commitments_to_pre_approval_values
    """
    env = _approved_ten_case_order(api)

    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {lot['cases_committed']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 991, (
        f"cases_remaining expected 991 but got {allocation['cases_remaining']}"
    )
    assert allocation["status"] == AllocationStatus.PARTIALLY_DRAWN, (
        f"entitlement status expected PARTIALLY_DRAWN but got {allocation['status']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["draw_posture"] == DrawPosture.PARTIAL, (
        f"draw_posture expected PARTIAL but got {cycle['draw_posture']}"
    )


def test_02_cancelling_restores_every_touched_commitment_exactly(api):
    """PRD §2.9: "Cancelling the order subtracts exactly those same amounts, restoring
    every touched `cases_committed` and the allocation's `cases_remaining` to their
    exact pre-approval values." PRD §3.5: "From `APPROVED` the full compensation of
    §2.9 runs: each lot named in the order's `lot_assignments` has its
    `cases_committed` reduced by exactly the cases it had reserved with `cases_on_hand`
    untouched, the entitlement's `cases_committed` falls by `total_cases_approved` and
    its `cases_remaining` is recomputed, the entitlement returns to `status` `ENTITLED`
    when both its `cases_committed` and its `cases_delivered` are zero, and the cycle's
    `draw_posture` is recomputed."

    Design: Difficulty/compensating_invariant/order_cancel_returns_case_commitments_to_pre_approval_values
    """
    env = _approved_ten_case_order(api)

    order = fx.cancel_order(
        api,
        env["order"]["id"],
        env["agency"]["id"],
        cancel_reason="Agency withdrew the order after approval.",
    )

    assert order["status"] == OrderStatus.CANCELLED, (
        f"order status expected CANCELLED but got {order['status']}"
    )
    assert order["cancel_reason"] == "Agency withdrew the order after approval.", (
        f"cancel_reason expected the supplied text but got {order['cancel_reason']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=300, cases_committed=0, cases_shipped_to_date=0)
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"lot status expected AVAILABLE but got {lot['status']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_delivered"] == 0, (
        f"cases_delivered expected 0 but got {allocation['cases_delivered']}"
    )
    assert allocation["cases_remaining"] == 1001, (
        f"cases_remaining expected 1001 but got {allocation['cases_remaining']}"
    )
    assert allocation["status"] == AllocationStatus.ENTITLED, (
        f"entitlement status expected ENTITLED but got {allocation['status']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["draw_posture"] == DrawPosture.NOT_STARTED, (
        f"draw_posture expected NOT_STARTED but got {cycle['draw_posture']}"
    )


def test_03_the_program_case_total_never_moves_across_the_pair(api):
    """PRD §2.9: "The **program case total** is the sum of `cases_on_hand` across every
    `InventoryLot` whose `status` is `AVAILABLE`, `WATCH`, or `HOLD`, plus the sum of
    `agency_cases_on_hand` across every `Agency`." PRD §2.9: "The program case total is
    untouched by either, because `cases_on_hand` never moves."

    Design: Difficulty/compensating_invariant/order_cancel_returns_case_commitments_to_pre_approval_values
    """
    env = _approved_ten_case_order(api)
    before = program_case_total(
        [fx.read_lot(api, env["lot"]["id"])], [fx.read_agency(api, env["agency"]["id"])]
    )
    assert before == 300, f"the program case total expected 300 but got {before}"

    fx.cancel_order(
        api,
        env["order"]["id"],
        env["agency"]["id"],
        cancel_reason="Agency withdrew the order after approval.",
    )

    after = program_case_total(
        [fx.read_lot(api, env["lot"]["id"])], [fx.read_agency(api, env["agency"]["id"])]
    )
    assert after == before, (
        f"the program case total moved from {before} to {after} across approve/cancel"
    )


def _two_distributions_one_unsigned(api):
    """A signed 5-case record and an unsigned 3-case record against 40 cases on hand."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 40)
    fx.accept_transfer(api, transfer["id"], agency["id"])
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27VOID",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["BULK_RICE"],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.set_clock(api, "2026-08-10T00:00:00Z")

    signed = fx.record_distribution(
        api,
        agency["id"],
        cycle["id"],
        rice["id"],
        household_size=2,
        declared_monthly_income_cents=150000,
        participates_in_snap=False,
        self_declaration_signed=True,
        cases_distributed=5,
        distribution_date="2026-08-10",
    )
    unsigned = fx.record_distribution(
        api,
        agency["id"],
        cycle["id"],
        rice["id"],
        household_size=4,
        declared_monthly_income_cents=300000,
        participates_in_snap=False,
        self_declaration_signed=False,
        cases_distributed=3,
        distribution_date="2026-08-10",
    )
    return {
        "agency": agency,
        "cycle": cycle,
        "signed": signed,
        "unsigned": unsigned,
    }


def test_04_both_records_are_in_the_rollup_before_the_void(api):
    """PRD §3.9: "The distribution's `pounds_distributed` is its `cases_distributed`
    multiplied by the commodity's `net_weight_lbs_per_case`, rounded half up to two
    decimals." PRD §3.9: "The `cases_distributed` figure must not exceed the agency's
    `agency_cases_on_hand`, otherwise `ERR_AGENCY_INVENTORY_INSUFFICIENT`; on success
    that counter falls by `cases_distributed`."

    Design: Difficulty/compensating_invariant/distribution_void_restores_pounds_records_and_agency_on_hand
    """
    env = _two_distributions_one_unsigned(api)

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_pounds(allocation["distributed_pounds"], 160.0, "distributed_pounds")
    assert allocation["distribution_record_count"] == 2, (
        f"distribution_record_count expected 2 but got {allocation['distribution_record_count']}"
    )
    assert_ratio(allocation["record_compliance_pct"], 0.5, "record_compliance_pct")
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 32, (
        f"agency_cases_on_hand expected 32 but got {agency['agency_cases_on_hand']}"
    )


def test_05_voiding_the_unsigned_record_restores_every_rollup_figure(api):
    """PRD §3.9: "The void compensates exactly: the entitlement's `distributed_pounds`
    falls by the record's `pounds_distributed`, its `distribution_record_count` falls
    by one, and its `record_compliance_pct` is recomputed over the remaining
    `RECORDED` rows, while the agency's `agency_cases_on_hand` rises by
    `cases_distributed`." PRD §3.9: "Recording a row and then voiding it therefore
    restores `distributed_pounds`, `distribution_record_count`,
    `record_compliance_pct`, and `agency_cases_on_hand` to their exact pre-record
    values."

    Design: Difficulty/compensating_invariant/distribution_void_restores_pounds_records_and_agency_on_hand
    """
    env = _two_distributions_one_unsigned(api)

    voided = fx.void_distribution(
        api,
        env["unsigned"]["id"],
        env["agency"]["id"],
        void_reason="Duplicate data entry for the same household visit.",
    )

    assert voided["status"] == DistributionStatus.VOIDED, (
        f"status expected VOIDED but got {voided['status']}"
    )
    assert voided["void_reason"] == "Duplicate data entry for the same household visit.", (
        f"void_reason expected the supplied text but got {voided['void_reason']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_pounds(allocation["distributed_pounds"], 100.0, "distributed_pounds")
    assert allocation["distribution_record_count"] == 1, (
        f"distribution_record_count expected 1 but got {allocation['distribution_record_count']}"
    )
    assert_ratio(allocation["record_compliance_pct"], 1.0, "record_compliance_pct")
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 35, (
        f"agency_cases_on_hand expected 35 but got {agency['agency_cases_on_hand']}"
    )


def test_06_the_surviving_record_is_untouched_by_the_void(api):
    """PRD §3.9: "**The recordkeeping rollup** is then recomputed on the entitlement
    row for that agency and cycle, over its `RECORDED` rows only — `VOIDED` rows are
    excluded from every aggregate."

    Design: Difficulty/compensating_invariant/distribution_void_restores_pounds_records_and_agency_on_hand
    """
    env = _two_distributions_one_unsigned(api)

    fx.void_distribution(
        api,
        env["unsigned"]["id"],
        env["agency"]["id"],
        void_reason="Duplicate data entry for the same household visit.",
    )

    survivor = fx.read_distribution(api, env["signed"]["id"])
    assert survivor["status"] == DistributionStatus.RECORDED, (
        f"the surviving record expected RECORDED but got {survivor['status']}"
    )
    assert_pounds(survivor["pounds_distributed"], 100.0, "pounds_distributed")
    _rows, meta = fx.list_rows_and_meta(
        api.list_household_distributions(
            headers=fx.ADMIN,
            params={
                "agency_id": env["agency"]["id"],
                "status": DistributionStatus.RECORDED,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one RECORDED row must remain but total_count is {meta['total_count']}"
    )
