"""Rent schedule lines and escalation steps: overlap, rounding, required
fields, referential integrity."""
from test_helpers import (
    ApiErrorId,
    add_schedule_line,
    assert_rent_schedule_line,
    create_lease,
    create_property,
    create_rent_schedule_line_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["portfolio_manager_headers"]


def _draft_lease(api, **overrides):
    set_clock()
    prop = create_property()
    return create_lease(prop["id"], **overrides)


class TestEscalationStepRequiredFields:
    def test_fixed_pct_requires_pct_bps(self, api):
        """PRD §3.3: "EscalationSteps are created on the lease with a 1-based
        `step_index` that is unique within the lease, a `kind` of `FIXED_PCT`,
        `CPI_LOOKUP`, or `STEPPED_AMOUNT`, an `effective_on` date, and exactly
        one accompanying magnitude: `pct_bps` (from 0 to 100000) is required if
        and only if the kind is `FIXED_PCT` or `CPI_LOOKUP`, while
        `amount_cents` (zero or greater) is required if and only if the kind is
        `STEPPED_AMOUNT`."
        PRD §2.11: "Fourth, request shape: required request-body fields must be
        present and well-typed — dates in ISO `YYYY-MM-DD` form, enum values
        within their declared sets, integers within their declared ranges —
        else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/escalation_step_conditional_required_pct_bps
        """
        lease = _draft_lease(api, escalation_type="FIXED_PCT",
                             recovery_structure="GROSS", pro_rata_share_bps=0)
        resp = api.create_escalation_step(
            lease["id"],
            {"step_index": 1, "kind": "FIXED_PCT", "effective_on": "2027-06-01"},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_stepped_amount_requires_amount_cents(self, api):
        """PRD §3.3: "EscalationSteps are created on the lease with a 1-based
        `step_index` that is unique within the lease, a `kind` of `FIXED_PCT`,
        `CPI_LOOKUP`, or `STEPPED_AMOUNT`, an `effective_on` date, and exactly
        one accompanying magnitude: `pct_bps` (from 0 to 100000) is required if
        and only if the kind is `FIXED_PCT` or `CPI_LOOKUP`, while
        `amount_cents` (zero or greater) is required if and only if the kind is
        `STEPPED_AMOUNT`."
        PRD §2.11: "Fourth, request shape: required request-body fields must be
        present and well-typed — dates in ISO `YYYY-MM-DD` form, enum values
        within their declared sets, integers within their declared ranges —
        else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/escalation_step_conditional_required_amount
        """
        lease = _draft_lease(api, escalation_type="NONE",
                             recovery_structure="GROSS", pro_rata_share_bps=0)
        resp = api.create_escalation_step(
            lease["id"],
            {"step_index": 1, "kind": "STEPPED_AMOUNT", "effective_on": "2027-06-01"},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestScheduleLineHalfOpenOverlapBoundary:
    def test_adjacent_lines_on_both_sides_allowed(self, api):
        """PRD §3.3: "Second, exclusivity: a new line must not overlap any
        existing line on the same lease under the half-open overlap test — the
        new line's start falling before an existing line's end while the new
        line's end falls after that existing line's start constitutes overlap
        and is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409)."
        (A new line whose start equals the existing line's end, or whose end
        equals the existing line's start, touches only at the endpoint and is
        not an overlap.)

        Design: Difficulty/boundary_precision_check/schedule_line_half_open_overlap_boundary
        """
        lease = _draft_lease(api, recovery_structure="GROSS", pro_rata_share_bps=0)
        add_schedule_line(
            lease["id"], period_start="2027-01-01", period_end="2027-07-01",
            base_rent_cents=600000,
        )
        right = api.create_rent_schedule_line(
            lease["id"],
            create_rent_schedule_line_payload(
                period_start="2027-07-01", period_end="2028-01-01",
                base_rent_cents=600000,
            ),
            PM,
        )
        right_data = validate_success(right, 201)
        assert_rent_schedule_line(right_data)
        left = api.create_rent_schedule_line(
            lease["id"],
            create_rent_schedule_line_payload(
                period_start="2026-12-31", period_end="2027-01-01",
                base_rent_cents=100,
            ),
            PM,
        )
        left_data = validate_success(left, 201)
        assert_rent_schedule_line(left_data)

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.3: "Second, exclusivity: a new line must not overlap any
        existing line on the same lease under the half-open overlap test — the
        new line's start falling before an existing line's end while the new
        line's end falls after that existing line's start constitutes overlap
        and is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/schedule_line_half_open_overlap_boundary
        """
        lease = _draft_lease(api, recovery_structure="GROSS", pro_rata_share_bps=0)
        add_schedule_line(
            lease["id"], period_start="2027-01-01", period_end="2027-07-01",
            base_rent_cents=600000,
        )
        add_schedule_line(
            lease["id"], period_start="2027-07-01", period_end="2028-01-01",
            base_rent_cents=600000,
        )
        resp = api.create_rent_schedule_line(
            lease["id"],
            create_rent_schedule_line_payload(
                period_start="2027-06-30", period_end="2027-08-01",
                base_rent_cents=100,
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)


class TestRentScheduleLineTemporalOverlap:
    def test_endpoint_adjacency_is_allowed(self, api):
        """PRD §3.3: "Second, exclusivity: a new line must not overlap any
        existing line on the same lease under the half-open overlap test — the
        new line's start falling before an existing line's end while the new
        line's end falls after that existing line's start constitutes overlap
        and is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rent_schedule_line_half_open_overlap
        """
        lease = _draft_lease(api, recovery_structure="GROSS", pro_rata_share_bps=0)
        add_schedule_line(
            lease["id"], period_start="2027-03-01", period_end="2027-09-01",
            base_rent_cents=600000,
        )
        resp = api.create_rent_schedule_line(
            lease["id"],
            create_rent_schedule_line_payload(
                period_start="2027-09-01", period_end="2028-01-01",
                base_rent_cents=400000,
            ),
            PM,
        )
        data = validate_success(resp, 201)
        assert data["period_start"] == "2027-09-01"

    def test_one_day_interior_overlap_rejected(self, api):
        """PRD §3.3: "Second, exclusivity: a new line must not overlap any
        existing line on the same lease under the half-open overlap test — the
        new line's start falling before an existing line's end while the new
        line's end falls after that existing line's start constitutes overlap
        and is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rent_schedule_line_half_open_overlap
        """
        lease = _draft_lease(api, recovery_structure="GROSS", pro_rata_share_bps=0)
        add_schedule_line(
            lease["id"], period_start="2027-03-01", period_end="2027-09-01",
            base_rent_cents=600000,
        )
        add_schedule_line(
            lease["id"], period_start="2027-09-01", period_end="2028-01-01",
            base_rent_cents=400000,
        )
        resp = api.create_rent_schedule_line(
            lease["id"],
            create_rent_schedule_line_payload(
                period_start="2027-08-31", period_end="2027-10-01",
                base_rent_cents=100,
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)


class TestEscalationReferentialIntegrity:
    def test_escalation_step_from_other_lease_rejected(self, api):
        """PRD §3.3: "Referential integrity binds the two entities: the
        `escalation_step_id` on a schedule line must reference an existing
        EscalationStep belonging to the same lease, else creation is rejected
        with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/errors/err_referential_integrity_escalation_step_wrong_lease
        """
        set_clock()
        prop = create_property()
        l1 = create_lease(
            prop["id"], tenant_legal_name="A", suite="100", leased_sf=1000,
            base_rent_annual_cents=100, escalation_type="FIXED_PCT",
            recovery_structure="GROSS", pro_rata_share_bps=0,
        )
        step = validate_success(
            api.create_escalation_step(
                l1["id"],
                {"step_index": 1, "kind": "FIXED_PCT", "pct_bps": 100,
                 "effective_on": "2027-06-01"},
                PM,
            ),
            201,
        )
        l2 = create_lease(
            prop["id"], tenant_legal_name="B", suite="200", leased_sf=1000,
            base_rent_annual_cents=100, escalation_type="NONE",
            recovery_structure="GROSS", pro_rata_share_bps=0,
        )
        resp = api.create_rent_schedule_line(
            l2["id"],
            create_rent_schedule_line_payload(
                period_start="2027-01-01", period_end="2028-01-01",
                base_rent_cents=100, escalation_step_id=step["id"],
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestEscalatedRentPerLineRounding:
    def _build(self, api):
        lease = _draft_lease(
            api, tenant_legal_name="T1", suite="100", leased_sf=4000,
            commencement_date="2027-01-01", expiration_date="2027-12-31",
            base_rent_annual_cents=1200000, escalation_type="FIXED_PCT",
            recovery_structure="GROSS", pro_rata_share_bps=0,
        )
        step = validate_success(
            api.create_escalation_step(
                lease["id"],
                {"step_index": 1, "kind": "FIXED_PCT", "pct_bps": 1,
                 "effective_on": "2027-01-01"},
                PM,
            ),
            201,
        )
        lines = []
        for start, end in (
            ("2027-01-01", "2027-02-01"),
            ("2027-02-01", "2027-03-01"),
            ("2027-03-01", "2027-04-01"),
        ):
            lines.append(
                validate_success(
                    api.create_rent_schedule_line(
                        lease["id"],
                        create_rent_schedule_line_payload(
                            period_start=start, period_end=end,
                            base_rent_cents=333333,
                            escalation_step_id=step["id"],
                        ),
                        PM,
                    ),
                    201,
                )
            )
        validate_success(
            api.create_rent_schedule_line(
                lease["id"],
                create_rent_schedule_line_payload(
                    period_start="2027-04-01", period_end="2028-01-01",
                    base_rent_cents=200001,
                ),
                PM,
            ),
            201,
        )
        return lease, lines

    def test_per_line_round_half_up(self, api):
        """PRD §3.3: "For a `FIXED_PCT` step, the effective rent is the base
        multiplied by the sum of 10000 and the step's `pct_bps`, divided by
        10000, rounded half-up to whole cents."
        PRD §2.6: "Wherever a calculation produces a fractional cent, the
        result is rounded to whole cents — zero decimal places — using the
        round-half-up method."

        Design: Difficulty/combinatorial_formula/escalated_rent_per_line_rounding
        """
        _, lines = self._build(api)
        for line in lines:
            assert line["effective_rent_cents"] == 333366, (
                "round_half_up(333333 * 10001 / 10000) must be 333366, "
                f"got {line['effective_rent_cents']}"
            )

    def test_annual_total_is_sum_of_rounded_lines(self, api, lease_accountant_headers):
        """PRD §2.6: "Rounding order is significant and is pinned by the system:
        per-line amounts are rounded individually first, and any aggregate total
        is a sum of already-rounded line amounts, never a rounding of the summed
        raw values."
        PRD §3.9: "The default `cash` basis reports the lease's
        `cached_annual_rent_cents` — the sum of scheduled, per-line-rounded
        `effective_rent_cents` overlapping the fiscal year as defined in §3.3."

        Design: Difficulty/combinatorial_formula/escalated_rent_per_line_rounding
        """
        lease, _ = self._build(api)
        data = validate_success(
            api.get_rent_roll(
                lease["id"], lease_accountant_headers,
                params={"fiscal_year": 2027, "basis": "cash"},
            )
        )
        # 3 * 333366 + 200001 = 1200099 (sum of per-line rounded values;
        # sum-then-round of the raw values would give 1200100).
        assert data["total_rent_cents"] == 1200099, (
            f"expected per-line-rounded total 1200099, got {data['total_rent_cents']}"
        )
