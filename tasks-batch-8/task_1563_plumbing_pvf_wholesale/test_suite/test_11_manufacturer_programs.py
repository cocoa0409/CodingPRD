"""Manufacturer stocking programs: overlap rule, accrual, rebate attainment (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_program,
    create_program_payload,
    make_branch,
    make_product,
    make_program,
    receive_stock,
    set_clock,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]

TIERS_12 = [{"threshold_cents": 250000, "rebate_pct": 1}, {"threshold_cents": 500000, "rebate_pct": 2}]


class TestProgramOverlap:
    def test_touching_periods_same_manufacturer_conflict(self, api, manager_headers):
        """PRD §3.2: "Programs for the same `manufacturer_name` may not touch or
        intersect: because the intervals are closed, two periods that share even
        a boundary date conflict, and the conflicting creation is rejected with
        `ERR_PROGRAM_OVERLAP`."

        A second Acme program starting exactly on the first program's
        period_end touches it and is rejected.

        Design: Difficulty/resource_temporal_overlap/program_closed_interval_touch
        """
        make_program(manufacturer_name="Acme", period_start="2026-01-01T00:00:00Z",
                     period_end="2026-03-31T00:00:00Z")
        res = api.create_program(
            create_program_payload(manufacturer_name="Acme",
                                   period_start="2026-03-31T00:00:00Z",
                                   period_end="2026-06-30T00:00:00Z"),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_OVERLAP)

    def test_other_manufacturer_and_strictly_after_both_allowed(self, api, manager_headers):
        """PRD §3.2: "Programs for the same `manufacturer_name` may not touch or intersect: because the intervals are closed, two periods that share even a boundary date conflict, and the conflicting creation is rejected with `ERR_PROGRAM_OVERLAP`. Different manufacturers are unrestricted."

        BrassCo may hold the exact same dates, and an Acme program starting
        strictly after the first one's period_end (2026-04-01 > 2026-03-31) is
        also clear of the closed interval.

        Design: Difficulty/resource_temporal_overlap/program_closed_interval_touch
        """
        make_program(manufacturer_name="Acme", period_start="2026-01-01T00:00:00Z",
                     period_end="2026-03-31T00:00:00Z")

        other_mfr = api.create_program(
            create_program_payload(manufacturer_name="BrassCo",
                                   period_start="2026-03-31T00:00:00Z",
                                   period_end="2026-06-30T00:00:00Z"),
            manager_headers,
        )
        validate_success(other_mfr, 201)

        after = api.create_program(
            create_program_payload(manufacturer_name="Acme",
                                   period_start="2026-04-01T00:00:00Z",
                                   period_end="2026-06-30T00:00:00Z"),
            manager_headers,
        )
        validate_success(after, 201)


class TestRebateAttainment:
    def _setup_program_with_purchases(self, unit_cost_cents: int, qty: int = 10):
        """Acme program 2026-07-01..2026-08-31 with tiers 1%/2%; a receipt of
        `qty` x unit_cost_cents accrues in-window; clock advanced past the end."""
        branch = make_branch()
        product = make_product(sku="PM", description="Acme manifold", category="FITTING",
                               list_price_cents=90000, cost_cents=unit_cost_cents, cubes_per_unit=4)
        program = make_program(
            manufacturer_name="Acme",
            period_start="2026-07-01T00:00:00Z", period_end="2026-08-31T23:59:59Z",
            tiers=TIERS_12,
        )
        receive_stock(branch["id"], product["id"], qty, unit_cost_cents)
        set_clock("2026-09-01T00:00:00Z")
        return branch, product, program

    def test_purchases_accrue_in_window(self, api, sales_headers):
        """PRD §3.1: "Any manufacturer program whose `manufacturer_name` matches
        the line's product and whose accrual window contains the receipt's
        `received_at` accrues the line's quantity times its `unit_cost_cents`
        into the program's `purchases_cents`."
        PRD §3.2: "The window is a closed interval — both boundary instants are
        inside the period".

        Ten units at 50000 received at the default clock (2026-08-01, inside
        the window) accrue purchases_cents of exactly 500000.

        Design: Difficulty/boundary_precision_check/rebate_threshold_equality_attains_tier
        """
        branch = make_branch()
        product = make_product(sku="PM", description="Acme manifold", category="FITTING",
                               list_price_cents=90000, cost_cents=50000, cubes_per_unit=4)
        program = make_program(
            manufacturer_name="Acme",
            period_start="2026-07-01T00:00:00Z", period_end="2026-08-31T23:59:59Z",
            tiers=TIERS_12,
        )
        receive_stock(branch["id"], product["id"], 10, 50000)

        after = validate_success(api.get_program(program["id"], sales_headers))
        assert_program(after)
        assert after["purchases_cents"] == 500000, (
            f"10 x 50000 in-window must accrue 500000, got {after['purchases_cents']}"
        )

    def test_threshold_equality_attains_tier(self, api, manager_headers):
        """PRD §3.2: "Closing computes attainment: the highest rung whose
        `threshold_cents` is less than or equal to the accumulated
        `purchases_cents` is attained (purchases exactly equal to a threshold
        attain that rung), and `attained_rebate_pct` becomes that rung's
        percent, or 0 when no rung qualifies. The earned rebate is then
        `purchases_cents` multiplied by `attained_rebate_pct` and divided by
        100, rounded half up to a whole cent, and stored as
        `earned_rebate_cents`; the program lands in `CLOSED`."

        Purchases of exactly 500000 attain the 2% rung: earned 10000.

        Design: Difficulty/boundary_precision_check/rebate_threshold_equality_attains_tier
        """
        _, _, program = self._setup_program_with_purchases(unit_cost_cents=50000)
        closed = validate_success(api.close_program(program["id"], manager_headers))
        assert closed["status"] == "CLOSED"
        assert closed["attained_rebate_pct"] == 2, (
            f"purchases exactly at the 500000 threshold attain that rung, got {closed['attained_rebate_pct']}"
        )
        assert closed["earned_rebate_cents"] == 10000

    def test_below_top_threshold_attains_lower_tier(self, api, manager_headers):
        """PRD §3.2: "the highest rung whose `threshold_cents` is less than or
        equal to the accumulated `purchases_cents` is attained" and "A later
        settle action by a `BranchManager` records payout and moves the program
        from `CLOSED` to its terminal state `SETTLED`."

        Purchases 499990 fall one rung short of the 500000 top tier: 1% is
        attained, earned round_half_up(4999.90) = 5000, and settle lands the
        program in SETTLED.

        Design: Corner/calculations/rebate_below_top_threshold_attains_lower_tier
        """
        _, _, program = self._setup_program_with_purchases(unit_cost_cents=49999)
        closed = validate_success(api.close_program(program["id"], manager_headers))
        assert closed["purchases_cents"] == 499990
        assert closed["attained_rebate_pct"] == 1, (
            f"499990 < 500000 attains only the 1% rung, got {closed['attained_rebate_pct']}"
        )
        assert closed["earned_rebate_cents"] == 5000

        settled = validate_success(api.settle_program(program["id"], manager_headers))
        assert settled["status"] == "SETTLED"


class TestProgramStateGates:
    def test_settle_before_close_rejected(self, api, manager_headers, sales_headers):
        """PRD §3.2: "A later settle action by a `BranchManager` records payout
        and moves the program from `CLOSED` to its terminal state `SETTLED`."
        Settle is defined only from `CLOSED`; an ACTIVE program rejects it.

        Design: Corner/state_machines/program_settle_before_close_rejected
        """
        program = make_program()
        res = api.settle_program(program["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_program(program["id"], sales_headers))
        assert after["status"] == "ACTIVE"

    def test_close_before_period_end_rejected(self, api, manager_headers, sales_headers):
        """PRD §3.2: "Once the logical clock has moved past `period_end` — a
        close attempted earlier is rejected with `ERR_PROGRAM_PERIOD_NOT_ENDED`
        — a `BranchManager` closes the program."

        The clock still reads the default 2026-08-01, inside a period ending
        2026-12-31.

        Design: Corner/validations/program_close_before_period_end_rejected
        """
        program = make_program(period_start="2026-01-01T00:00:00Z",
                               period_end="2026-12-31T00:00:00Z")
        res = api.close_program(program["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_PROGRAM_PERIOD_NOT_ENDED)
        after = validate_success(api.get_program(program["id"], sales_headers))
        assert after["status"] == "ACTIVE"
