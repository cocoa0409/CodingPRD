"""Authentication, role authorization, sign-up implementation materialization,
and version semantics."""
import pytest

from test_helpers import (
    ApiErrorId,
    award_run_to_operator,
    create_grievance,
    create_operator,
    create_period,
    create_picking_period,
    create_run,
    create_run_piece,
    implement_period,
    list_board_slots,
    lock_period,
    make_operator_headers,
    setup_implemented_with_award,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_sign_up_period_payload
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]
PC = TEST_USERS["payroll_clerk_headers"]
UR = TEST_USERS["union_rep_headers"]


class TestAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring their
        operational capacity."
        PRD §2.1: "A request with a missing or unknown role header, or a
        missing user header, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.list_sign_up_periods({"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_user_header_rejected(self, api):
        """PRD §2.1: "A request with a missing or unknown role header, or a
        missing user header, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.list_sign_up_periods({"X-User-Role": "SchedulingOfficer"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_operator_cannot_create_sign_up_period(self, api):
        """PRD §2.1: "An authenticated role attempting an operation outside its
        grant is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/operator_cannot_create_signup_period
        """
        operator = create_operator()
        resp = api.create_sign_up_period(
            create_sign_up_period_payload(name="X"),
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_payroll_clerk_cannot_uphold_grievance(self, api):
        """PRD §2.1: "An authenticated role attempting an operation outside its
        grant is rejected with `ERR_FORBIDDEN`."
        PRD §3.9: "A `UnionRep` may uphold a case — optionally supplying
        `remedy_minutes` — moving it from `FILED` to `UPHELD` and crediting
        those remedy minutes to the filing operator's `weekly_ot_minutes_accum`
        as the compensating make-whole."

        Design: Corner/rbac/payroll_clerk_cannot_uphold_grievance
        """
        period = create_period(name="G")
        operator = create_operator()
        case = create_grievance(operator["id"], period["id"],
                                category="SENIORITY_BYPASS", detail="bypassed")
        resp = api.uphold_grievance_case(case["id"], {}, PC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_operator_cannot_dispute_pay_on_anothers_assignment(self, api):
        """PRD §3.8: "The assigned operator — and only that operator, by the
        identity rule of §2.1 — may dispute the pay, moving `pay_status` from
        `PROVISIONAL` or `FINALIZED` to `DISPUTED`."
        PRD §2.1: "ownership checks on any resource that references an Operator
        — submitting or withdrawing that operator's own bid entries, disputing
        pay on their own assignments, withdrawing their own grievances,
        reporting their own absence — compare the resource's operator
        foreign-key field to `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/operator_dispute_pay_on_own_assignment_only
        """
        ctx = setup_implemented_with_award()
        asg = ctx["assignment"]
        other = create_operator(employee_number="E2", full_name="Op Two", hire_date="2005-01-01")
        resp = api.dispute_pay(asg["id"], make_operator_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestImplementMaterialization:
    def test_implement_creates_assignment_per_awarded_run(self, api):
        """PRD §3.5: "For every `AWARDED` run, a `DailyAssignment` is created
        for each of the run's service dates falling inside the period's
        effective window — the run's `service_date` having already been
        validated against that window at creation — stamped with the period's
        `sign_up_period_id`, the awarded `operator_id`, the `run_id`, the
        `service_date`, a `source` of `BID_AWARD`, `status` `SCHEDULED`,
        `pay_status` `PROVISIONAL`, and a `scheduled_minutes` snapshot equal to
        the run's `paid_minutes` at the moment of assignment."

        Design: Corner/endpoints/implement_materializes_assignments
        """
        period, runs = create_picking_period()
        operator = create_operator()
        award_run_to_operator(period["id"], operator["id"], runs[0]["id"])
        lock_period(period["id"])
        validate_success(api.implement_sign_up_period(period["id"], SO))
        data, _meta = validate_paginated(
            api.list_daily_assignments(
                SO, params={"operator_id": operator["id"], "sign_up_period_id": period["id"]}
            )
        )
        assert len(data) == 1
        asg = data[0]
        assert asg["status"] == "SCHEDULED"
        assert asg["source"] == "BID_AWARD"
        assert asg["pay_status"] == "PROVISIONAL"
        assert asg["run_id"] == runs[0]["id"]
        assert asg["service_date"] == runs[0]["service_date"]
        assert asg["scheduled_minutes"] == runs[0]["paid_minutes"]


class TestVersionSemantics:
    def test_version_starts_at_one_and_increments_per_mutation(self, api):
        """PRD §2.4: "**`version` (integer):** a system-managed integer that
        increments by exactly one on every mutation, and which anchors the
        optimistic-concurrency rules of §2.9."
        PRD §2.10: "Two operations additionally advance the parent sign-up
        period's `version`: creating a run beneath the period, and submitting a
        bid entry against it."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        period = create_period(name="VI")
        assert period["version"] == 1
        create_run(period["id"], run_number="R1", service_date="2026-09-07",
                   pieces=[create_run_piece(300, 700, 400)])
        from test_helpers import get_period
        after = get_period(period["id"])
        assert after["version"] == 2
