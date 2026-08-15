"""Dues-objector (agency fee) cases: filing rules and rebate projections."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_set_rate_payload,
    get_success_data,
    make_local,
    make_member,
    make_member_headers,
    make_objector_case,
    make_payment,
    run_period,
    set_clock,
    set_objector_rate,
    setup_flat_local_with_journeyman,
    validate_error,
    validate_success,
)


class TestFilingConstraints:
    def test_second_active_objector_case_rejected(self, api):
        """PRD section on objector cases: "it is refused when the member
        already has a non-terminal case (`ERR_OBJECTOR_CASE_EXISTS`)".

        Design: Corner/errors/second_active_objector_case_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Double Dan", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        make_objector_case(member["id"])
        resp = api.create_objector_case(member["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_OBJECTOR_CASE_EXISTS)

    def test_appeal_filed_case_rejected(self, api):
        """PRD section on objector cases: "The member may appeal an issued
        rebate — only from `REBATE_ISSUED` (`ERR_OBJECTOR_CASE_STATE_FORBIDDEN`)".
        A case still in FILED has no issued rebate to appeal.

        Design: Corner/errors/appeal_filed_case_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Early Eve", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        case = make_objector_case(member["id"])
        resp = api.appeal_objector_case(case["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_OBJECTOR_CASE_STATE_FORBIDDEN)

    def test_secretary_cannot_set_objector_rate(self, api, secretary_treasurer_headers):
        """PRD section on roles: "A request whose role is declared but not
        permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." The endpoint table
        authorizes only LocalAdmin to set the chargeable-share percent.

        Design: Corner/rbac/secretary_cannot_set_objector_rate
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Rate Rita", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        case = make_objector_case(member["id"])
        resp = api.set_objector_rate(case["id"], create_set_rate_payload(50), secretary_treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestRebateProjectionVariants:
    """The projection read answers two different questions: the lifetime
    actual rebate to date, and the forward-looking year-end projection."""

    def _setup_objector_case(self, api):
        """FLAT local, flat dues 1001; FINAL paid assessments for 2026-08 and
        2026-09; a 2026-10 PROVISIONAL; objector case RATE_SET at 33%."""
        local, cls = setup_flat_local_with_journeyman(
            flat=1001, local_name="Local 300", notice_cure_days=30
        )
        member = make_member(local["id"], cls["id"], full_name="Obie Objector", member_number="M-001")
        run_period(local["id"], "2026-08")
        run_period(local["id"], "2026-09")
        run_period(local["id"], "2026-10")
        make_payment(member["id"], 2002)  # covers both FINAL 1001 buckets
        case = make_objector_case(member["id"])
        set_objector_rate(case["id"], 33)
        return member, case

    def test_actual_rebate_to_date_rounds_per_line(self, api, secretary_treasurer_headers):
        """PRD section on rebates: "The actual-to-date figure is the lifetime
        line-rebate sum, computed by the same per-line rounding rule, over the
        member's `FINAL` paid assessments with periods at or before the
        current clock period, deliberately ignoring `last_rebated_period`."
        Per 1001 line at 33%: agency fee round_half_up(330.33) = 330, line
        rebate 671; two lines total 1342.

        Design: Difficulty/dual_variant_calc/objector_rebate_projected_vs_actual_diverge
        """
        _, case = self._setup_objector_case(api)
        projection = get_success_data(api.get_rebate_projection(case["id"], secretary_treasurer_headers))
        assert projection["actual_rebate_to_date_cents"] == 1342, (
            "two FINAL paid periods x (1001 - 330)"
        )

    def test_projected_year_rebate_adds_remaining_periods_at_floor(self, api, secretary_treasurer_headers):
        """PRD section on rebates: "it is the actual rebate to date plus, for
        each remaining calendar period of the calendar year containing the
        current clock that falls after the latest `FINAL` assessment period,
        the floor dues minus the floor dues multiplied by the chargeable-share
        percent divided by one hundred and rounded half up." With the clock in
        2026-10 and the latest FINAL at 2026-09, the three remaining periods
        2026-10..12 each add 671: 1342 + 2013 = 3355.

        Design: Difficulty/dual_variant_calc/objector_rebate_projected_vs_actual_diverge
        """
        _, case = self._setup_objector_case(api)
        projection = get_success_data(api.get_rebate_projection(case["id"], secretary_treasurer_headers))
        assert projection["projected_year_rebate_cents"] == 3355
        assert projection["projected_year_rebate_cents"] != projection["actual_rebate_to_date_cents"], (
            "the two variants answer different questions for the same case"
        )
