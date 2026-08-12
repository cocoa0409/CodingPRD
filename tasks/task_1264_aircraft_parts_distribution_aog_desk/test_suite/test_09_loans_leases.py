"""Desk-direct loans and leases: settlement variants and window overlap."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_customer, create_part, create_unit, create_loan,
    set_clock, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]


def _rotable_unit(customer_name="Polar Air", part_number="PN-ROT",
                  serial="SN-L1", **unit_kw):
    customer = create_customer(name=customer_name)
    part = create_part(part_number=part_number, rotable=True,
                       list_price_cents=300_000, core_value_cents=100_000)
    unit = create_unit(part["id"], serial_number=serial, condition="OVERHAULED",
                       trace_doc_level="FAA_8130", **unit_kw)
    return customer, part, unit


class TestLoanVsLeaseSettlementDivergence:
    """Identical span for both contracts: start 2026-05-10, due 2026-06-09,
    returned 2026-06-14 (35 actual days), rate 25000/day."""

    def _setup_pair(self, api):
        customer = create_customer(name="Polar Air")
        part = create_part(part_number="PN-ROT", rotable=True,
                           list_price_cents=300_000, core_value_cents=100_000,
                           warranty_months=12)
        u1 = create_unit(part["id"], serial_number="SN-L1",
                         condition="OVERHAULED", trace_doc_level="FAA_8130")
        u2 = create_unit(part["id"], serial_number="SN-L2",
                         condition="OVERHAULED", trace_doc_level="FAA_8130")
        loan = create_loan(customer["id"], u1["id"], loan_type="LOAN",
                           daily_rate_cents=25_000,
                           start_at="2026-05-10T00:00:00Z",
                           due_at="2026-06-09T00:00:00Z")
        lease = create_loan(customer["id"], u2["id"], loan_type="LEASE",
                            daily_rate_cents=25_000, lease_periods=1,
                            start_at="2026-05-10T00:00:00Z",
                            due_at="2026-06-09T00:00:00Z")
        set_clock("2026-06-14T00:00:00Z")
        return loan, lease

    def test_loan_bills_chronologically_with_late_tier(self, api):
        """PRD §3.7: "A `LOAN` bills chronologically at return: on-time days
        are the smaller of the actual days and the whole days between start
        and due, late days are the remainder, and `billed_cents` is the
        on-time days at the daily rate plus the late days at one and a half
        times the daily rate, the late portion rounded half-up to whole
        cents." Also: "The actual days run from `start_at` to `returned_at`
        in whole days rounded up, minimum one."

        35 actual days, 30 on-time, 5 late: 30*25000 + round(5*25000*1.5) =
        750000 + 187500 = 937500.

        Design: Difficulty/dual_variant_calc/loan_vs_lease_settlement_divergence
        """
        loan, _ = self._setup_pair(api)
        returned = validate_success(api.return_loan(
            loan["id"], {"damage_flag": False}, WAREHOUSE,
        ))
        assert returned["billed_cents"] == 937_500
        assert returned["status"] == "SETTLED"

    def test_lease_bills_forward_whole_periods(self, api):
        """PRD §3.7: "A `LEASE` bills forward-looking whole periods: periods
        used are the actual days divided into 30-day periods rounded up, and
        `billed_cents` is the greater of contracted periods or periods used,
        times 30 days, times the daily rate — no late multiplier, and no
        credit for returning early, so identical dates can bill differently
        under the two shapes."

        ceil(35/30) = 2 periods used vs 1 contracted: 2 * 30 * 25000 =
        1500000, which differs from the 937500 the same dates bill as a LOAN.

        Design: Difficulty/dual_variant_calc/loan_vs_lease_settlement_divergence
        """
        _, lease = self._setup_pair(api)
        returned = validate_success(api.return_loan(
            lease["id"], {"damage_flag": False}, WAREHOUSE,
        ))
        assert returned["billed_cents"] == 1_500_000
        assert returned["status"] == "SETTLED"


class TestLoanWindowsHalfOpenAdjacency:
    def _setup_loan(self, api):
        customer, part, unit = _rotable_unit(
            customer_name="HalfOpen Air", part_number="PN-HO", serial="SN-HO1"
        )
        loan = create_loan(customer["id"], unit["id"], loan_type="LOAN",
                           daily_rate_cents=10_000,
                           start_at="2026-05-10T00:00:00Z",
                           due_at="2026-06-09T00:00:00Z")
        return customer, unit, loan

    def test_adjacent_window_allowed(self, api):
        """PRD §3.7: "the new window must not intersect another `ACTIVE` or
        `OVERDUE` loan of the same unit — the window is half-open, so an
        existing loan ending exactly when the new one starts is allowed".

        Existing [2026-05-10, 2026-06-09); new [2026-06-09, 2026-07-09).

        Design: Difficulty/resource_temporal_overlap/loan_windows_half_open_adjacency
        """
        customer, unit, _ = self._setup_loan(api)
        adjacent = validate_success(api.create_loan(
            {"customer_id": customer["id"], "unit_id": unit["id"],
             "loan_type": "LOAN", "daily_rate_cents": 10_000,
             "start_at": "2026-06-09T00:00:00Z",
             "due_at": "2026-07-09T00:00:00Z"},
            AGENT,
        ), 201)
        assert adjacent["status"] == "ACTIVE"

        data, meta = validate_paginated(
            api.list_loans(AGENT, params={"unit_id": unit["id"]})
        )
        assert meta["total_count"] == 2

    def test_interior_overlap_rejected(self, api):
        """PRD §3.7: "any genuine overlap is `ERR_LOAN_WINDOW_OVERLAP`".

        New window [2026-06-01, 2026-06-20) intersects the existing
        [2026-05-10, 2026-06-09) loan's interior.

        Design: Difficulty/resource_temporal_overlap/loan_windows_half_open_adjacency
        """
        customer, unit, _ = self._setup_loan(api)
        res = api.create_loan(
            {"customer_id": customer["id"], "unit_id": unit["id"],
             "loan_type": "LOAN", "daily_rate_cents": 10_000,
             "start_at": "2026-06-01T00:00:00Z",
             "due_at": "2026-06-20T00:00:00Z"},
            AGENT,
        )
        validate_error(res, "ERR_LOAN_WINDOW_OVERLAP", expected_status=409)

        data, meta = validate_paginated(
            api.list_loans(AGENT, params={"unit_id": unit["id"]})
        )
        assert meta["total_count"] == 1


class TestLoanWindowPastBeatsOverlap:
    def _setup(self, api):
        customer, part, unit = _rotable_unit(
            customer_name="OverCo", part_number="PN-OV", serial="SN-OV1",
        )
        create_loan(customer["id"], unit["id"], loan_type="LOAN",
                    daily_rate_cents=10_000,
                    start_at="2026-05-10T00:00:00Z",
                    due_at="2026-06-09T00:00:00Z")
        return customer, unit

    def test_past_start_surfaces_temporal_error_not_overlap(self, api):
        """PRD §2.11 gate 8 (business temporal) covers "Future-dated
        deadlines, valid loan windows, warranty and return windows, and
        tier-capped validity" surfacing `ERR_LOAN_WINDOW_IN_PAST`, and gate 9
        (business constraint) covers "Uniqueness, overlap, and availability
        rules" surfacing `ERR_LOAN_WINDOW_OVERLAP`; "Lower-numbered gates run
        first." A window that is both in the past and overlapping must surface
        the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/loan_window_past_beats_overlap
        """
        customer, unit = self._setup(api)
        res = api.create_loan(
            {"customer_id": customer["id"], "unit_id": unit["id"],
             "loan_type": "LOAN", "daily_rate_cents": 10_000,
             "start_at": "2026-04-01T00:00:00Z",
             "due_at": "2026-06-15T00:00:00Z"},
            AGENT,
        )
        validate_error(res, "ERR_LOAN_WINDOW_IN_PAST", expected_status=422)

    def test_rejected_loan_is_not_persisted(self, api):
        """PRD §3.7: "Violations of these window rules — a past start, a due
        instant not after start, a mismatched lease horizon, or
        `lease_periods` on a loan — surface as `ERR_LOAN_WINDOW_IN_PAST` or
        `ERR_INVALID_REQUEST` as applicable." A rejected create persists no
        agreement: the loan book ("The loans collection filters by
        `customer_id`, `unit_id`, `order_line_id`, and `status`") still shows
        only the pre-existing loan for the unit.

        Design: Difficulty/priority_pair_validation_conflict/loan_window_past_beats_overlap
        """
        customer, unit = self._setup(api)
        res = api.create_loan(
            {"customer_id": customer["id"], "unit_id": unit["id"],
             "loan_type": "LOAN", "daily_rate_cents": 10_000,
             "start_at": "2026-04-01T00:00:00Z",
             "due_at": "2026-06-15T00:00:00Z"},
            AGENT,
        )
        validate_error(res, "ERR_LOAN_WINDOW_IN_PAST", expected_status=422)

        data, meta = validate_paginated(
            api.list_loans(AGENT, params={"unit_id": unit["id"]})
        )
        assert meta["total_count"] == 1
