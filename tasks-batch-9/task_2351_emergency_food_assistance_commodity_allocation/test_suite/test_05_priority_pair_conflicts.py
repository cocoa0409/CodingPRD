"""Requests that break two rules at once, where the precedence list picks the answer."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    EligibilityPosture,
    FormulaVariant,
    OrderStatus,
    TrainingStatus,
    assert_agency_axes,
    factories as f,
    fixtures as fx,
    make_agency_coordinator_headers,
    validate_error,
)

PEACH_CODE = "CANNED_PEACHES"


def _two_orders_over_one_tight_entitlement(api):
    """A 20-case entitlement fully committed by order A while order B still sits SUBMITTED."""
    env = fx.build_program(
        api,
        commodity_payloads=[f.canned_peaches_payload(entitlement_value_cents_per_case=1800)],
        lot_cases=100,
        allocatable_cases=20,
        admin_funds_pool_cents=5000000,
    )
    agency = env["agency"]
    peaches = env["commodities"][PEACH_CODE]

    order_a = fx.create_order(
        api, env["cycle"]["id"], agency["id"], env["warehouse"]["id"]
    )
    fx.add_line(api, order_a["id"], agency["id"], peaches["id"], 20)
    fx.submit_order(api, order_a["id"], agency["id"])

    order_b = fx.create_order(
        api, env["cycle"]["id"], agency["id"], env["warehouse"]["id"]
    )
    fx.add_line(api, order_b["id"], agency["id"], peaches["id"], 15)
    fx.submit_order(api, order_b["id"], agency["id"])

    fx.approve_order(api, order_a["id"])
    env["order_a"] = order_a
    env["order_b"] = order_b
    return env


def test_01_both_violations_are_live_before_the_conflicting_resubmit(api):
    """PRD §3.4: "The sum of `allocated_cases` across the cycle's entitlement rows
    equals the cycle's `allocatable_cases` exactly, and the cycle's
    `total_allocated_cases` is written from that sum." PRD §3.6: "the entitlement's
    `cases_committed` grows by `total_cases_approved` with `cases_remaining`
    recomputed and its `status` moved to `PARTIALLY_DRAWN`".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_over_entitlement_order_returns_state_error_not_fiscal_error
    """
    env = _two_orders_over_one_tight_entitlement(api)

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])

    assert allocation["allocated_cases"] == 20, (
        f"allocated_cases expected 20 but got {allocation['allocated_cases']}"
    )
    assert allocation["cases_committed"] == 20, (
        f"cases_committed expected 20 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 0, (
        f"cases_remaining expected 0 but got {allocation['cases_remaining']}"
    )
    order_b = fx.read_order(api, env["order_b"]["id"])
    assert order_b["status"] == OrderStatus.SUBMITTED, (
        f"order B expected SUBMITTED but got {order_b['status']}"
    )
    assert order_b["total_cases_requested"] == 15, (
        f"order B total_cases_requested expected 15 but got {order_b['total_cases_requested']}"
    )


def test_02_the_state_check_wins_over_the_headroom_check(api):
    """PRD §2.10: "Submitting an order that is already `SUBMITTED` *and* asks for
    more cases than remain answers `ERR_INVALID_ORDER_STATE`, because the state check
    at position 8 precedes the headroom check at position 32."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_over_entitlement_order_returns_state_error_not_fiscal_error
    """
    env = _two_orders_over_one_tight_entitlement(api)

    response = api.submit_order(
        env["order_b"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
        payload={},
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE, 409)


def test_03_the_refused_resubmit_changes_nothing(api):
    """PRD §2.11: "The rule is that every cascade named in §3 is part of the same
    transaction as its trigger: either the whole chain lands or nothing does." PRD
    §3.6: "The return increases `revision_count` by one, writes the acting reviewer's
    `X-User-ID` into `last_returned_by_user_id`, and increments the order's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_over_entitlement_order_returns_state_error_not_fiscal_error
    """
    env = _two_orders_over_one_tight_entitlement(api)

    api.submit_order(
        env["order_b"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
        payload={},
    )

    order_b = fx.read_order(api, env["order_b"]["id"])
    assert order_b["status"] == OrderStatus.SUBMITTED, (
        f"order B must stay SUBMITTED but got {order_b['status']}"
    )
    assert order_b["revision_count"] == 0, (
        f"order B revision_count must stay 0 but got {order_b['revision_count']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 20, (
        f"cases_committed must stay 20 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 0, (
        f"cases_remaining must stay 0 but got {allocation['cases_remaining']}"
    )


def _expired_agency_holding_cases(api):
    """An agency whose agreement lapsed after it had already taken 10 cases on hand."""
    fx.set_clock(api, "2026-07-01T00:00:00Z")
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
    fx.make_agency_eligible(
        api,
        agency["id"],
        completed_at="2026-07-01T00:00:00Z",
        agreement_start_date="2026-07-01",
        agreement_end_date="2026-07-31",
    )
    rice = fx.create_bulk_rice(api)
    peaches = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
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
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 10)
    fx.accept_transfer(api, transfer["id"], agency["id"])

    cycle = fx.create_cycle(
        api,
        cycle_code="FY27PAIR",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["BULK_RICE"],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    fx.run_compliance_sweep(api)
    return {
        "agency": fx.read_agency(api, agency["id"]),
        "cycle": fx.read_cycle(api, cycle["id"]),
        "peaches": peaches,
    }


def _record_unoffered_peach_distribution(api, env):
    return api.create_household_distribution(
        f.household_distribution_payload(
            env["agency"]["id"],
            env["cycle"]["id"],
            env["peaches"]["id"],
            household_size=1,
            declared_monthly_income_cents=100000,
            participates_in_snap=False,
            self_declaration_signed=True,
            cases_distributed=2,
            distribution_date="2026-08-05",
        ),
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )


def test_04_both_violations_are_live_before_the_conflicting_distribution(api):
    """PRD §3.2: "An agreement moves `ACTIVE → EXPIRED` once its
    `agreement_end_date` is strictly before the current date." PRD §3.2: "In every
    other combination — including an `ACTIVE` agreement whose training is still
    `REQUIRED`, and any agency whose agreement is `PENDING`, `EXPIRED`, or
    `TERMINATED` — the posture is `INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/distribution_by_ineligible_agency_of_unoffered_commodity_returns_safety_error
    """
    env = _expired_agency_holding_cases(api)

    assert_agency_axes(
        env["agency"],
        AgreementStatus.EXPIRED,
        TrainingStatus.CURRENT,
        EligibilityPosture.INELIGIBLE,
    )
    assert PEACH_CODE not in env["cycle"]["offered_commodity_codes"], (
        "the cycle must not offer canned peaches but offers "
        f"{env['cycle']['offered_commodity_codes']}"
    )


def test_05_the_posture_gate_wins_over_the_offering_check(api):
    """PRD §2.10: "Submitting an order for an agency whose training has lapsed —
    posture `PROBATION` — where a line also names a commodity absent from the cycle's
    offering answers `ERR_AGENCY_INELIGIBLE`, because the posture gate at position 14
    precedes the offering check at position 17." PRD §2.10: "Agency eligibility
    posture — `ERR_AGENCY_INELIGIBLE`. This guards five operations: order submit,
    order approve, transfer accept, household distribution recording, and delivery
    confirmation."

    Design: Difficulty/priority_pair_validation_conflict/distribution_by_ineligible_agency_of_unoffered_commodity_returns_safety_error
    """
    env = _expired_agency_holding_cases(api)

    response = _record_unoffered_peach_distribution(api, env)

    validate_error(response, ApiErrorId.ERR_AGENCY_INELIGIBLE, 422)


def test_06_the_refused_distribution_leaves_no_row_and_no_counter_moved(api):
    """PRD §2.11: "The rule is that every cascade named in §3 is part of the same
    transaction as its trigger: either the whole chain lands or nothing does."

    Design: Difficulty/priority_pair_validation_conflict/distribution_by_ineligible_agency_of_unoffered_commodity_returns_safety_error
    """
    env = _expired_agency_holding_cases(api)

    _record_unoffered_peach_distribution(api, env)

    _rows, meta = fx.list_rows_and_meta(
        api.list_household_distributions(
            headers=fx.ADMIN, params={"agency_id": env["agency"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no distribution row may exist but total_count is {meta['total_count']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 10, (
        f"agency_cases_on_hand must stay 10 but got {agency['agency_cases_on_hand']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["distribution_record_count"] == 0, (
        "distribution_record_count must stay 0 but got "
        f"{allocation['distribution_record_count']}"
    )
