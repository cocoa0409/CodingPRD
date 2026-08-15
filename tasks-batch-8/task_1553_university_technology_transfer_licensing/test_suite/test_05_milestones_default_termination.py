"""Milestones, default declaration, cure/terminate window boundaries, and
the license-termination cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_milestone,
    assert_same_instant,
    set_clock,
    setup_active_license,
    setup_approved_distribution,
    setup_defaulted_license,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import api_client

ADMIN = TEST_USERS["system_admin_headers"]
LM = TEST_USERS["licensing_manager_headers"]


class TestDeclareDefault:
    def test_declare_default_requires_overdue_milestone(self, api):
        """PRD: "Declaration requires the license to be `ACTIVE` — else
        `ERR_LICENSE_NOT_ACTIVE` — and at least one `PENDING` milestone whose
        `due_date` precedes the current clock; without such grounds the
        declaration is refused with `ERR_NO_DEFAULT_GROUNDS`. A declared
        default moves the license to `DEFAULT_NOTICE`, stamps
        `default_notice_date` with the current clock, and computes a
        `cure_deadline` sixty days later."

        Design: Difficulty/cross_entity_state_dependency/declare_default_requires_overdue_milestone
        """
        ctx = setup_active_license()
        lic_id = ctx["license"]["id"]
        add_milestone(lic_id, due_date="2026-12-31T00:00:00Z",
                      description="First sale", amount_cents=50000)
        set_clock("2026-08-01T00:00:00Z")
        resp = api.declare_default(lic_id, {"reason": "No grounds yet"}, LM)
        validate_error(resp, ApiErrorId.ERR_NO_DEFAULT_GROUNDS, 409)

        set_clock("2027-01-01T00:00:00Z")
        defaulted = validate_success(api.declare_default(
            lic_id, {"reason": "Milestone now overdue"}, LM))
        assert defaulted["status"] == "DEFAULT_NOTICE"
        assert_same_instant(defaulted["cure_deadline"], "2027-03-02T00:00:00Z")

    def test_declare_default_due_date_equal_clock_not_overdue(self, api):
        """PRD: "at least one `PENDING` milestone whose `due_date` precedes
        the current clock; without such grounds the declaration is refused
        with `ERR_NO_DEFAULT_GROUNDS`."

        Design: Difficulty/cross_entity_state_dependency/declare_default_requires_overdue_milestone
        """
        ctx = setup_active_license()
        lic_id = ctx["license"]["id"]
        add_milestone(lic_id, due_date="2026-09-01T00:00:00Z")
        # Clock exactly at the due date: the milestone is not yet overdue
        # ("precedes" is strict).
        set_clock("2026-09-01T00:00:00Z")
        resp = api.declare_default(lic_id, {"reason": "At due date"}, LM)
        validate_error(resp, ApiErrorId.ERR_NO_DEFAULT_GROUNDS, 409)
        set_clock("2026-09-01T00:00:01Z")
        defaulted = validate_success(api.declare_default(
            lic_id, {"reason": "Now overdue"}, LM))
        assert defaulted["status"] == "DEFAULT_NOTICE"


class TestCureAndTerminateBoundaries:
    def test_cure_when_not_in_default_rejected(self, api):
        """PRD: "Curing returns the license to `ACTIVE` and clears both
        `default_notice_date` and `cure_deadline`; it requires the license to
        be in `DEFAULT_NOTICE` — else `ERR_LICENSE_NOT_IN_DEFAULT`".

        Design: Corner/state_machines/cure_when_not_in_default_rejected
        """
        ctx = setup_active_license()
        resp = api.cure_license(ctx["license"]["id"], LM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_IN_DEFAULT, 409)

    def test_cure_deadline_and_terminate_boundaries(self, api):
        """PRD: "it requires the license to be in `DEFAULT_NOTICE` — else
        `ERR_LICENSE_NOT_IN_DEFAULT` — and the current clock to be at or
        before the `cure_deadline`, else `ERR_CURE_PERIOD_EXPIRED`.
        Termination moves the license to the terminal `TERMINATED` state and
        requires the clock to be strictly past the `cure_deadline`;
        terminating at or before it is refused with
        `ERR_CURE_PERIOD_ACTIVE`".

        Design: Corner/state_machines/cure_after_deadline_and_terminate_before_deadline
        """
        ctx_a, _ = setup_defaulted_license()
        ctx_b, _ = setup_defaulted_license()
        lic_a = ctx_a["license"]["id"]
        lic_b = ctx_b["license"]["id"]

        # cure_deadline is default_notice (2026-08-01) + 60 days.
        set_clock("2026-09-30T00:00:00Z")
        cured = validate_success(api.cure_license(lic_a, LM))
        assert cured["status"] == "ACTIVE", "cure at exactly cure_deadline succeeds"
        resp = api.terminate_license(lic_b, {}, LM)
        validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE, 409)

        set_clock("2026-09-30T00:00:01Z")
        terminated = validate_success(api.terminate_license(lic_b, {}, LM))
        assert terminated["status"] == "TERMINATED", \
            "one second past cure_deadline, termination succeeds"


class TestMilestoneBoundaries:
    def test_milestone_achieve_boundaries_and_twice(self, api):
        """PRD: "Marking a milestone achieved requires the milestone to be
        `PENDING` — else `ERR_MILESTONE_NOT_PENDING` — the license to be
        `EXECUTED` or `ACTIVE` — else `ERR_LICENSE_NOT_ACTIVE` — and the
        current clock to be at or before the milestone's `due_date`;
        achieving after the due date is refused with
        `ERR_MILESTONE_OVERDUE`. Success moves the milestone to `ACHIEVED`."

        Design: Corner/state_machines/milestone_achieve_after_due_and_twice_rejected
        """
        ctx = setup_active_license()
        lic_id = ctx["license"]["id"]
        m1 = add_milestone(lic_id, due_date="2026-09-01T00:00:00Z",
                           description="M1")
        m2 = add_milestone(lic_id, due_date="2026-09-01T00:00:00Z",
                           description="M2")

        set_clock("2026-09-01T00:00:00Z")
        achieved = validate_success(api.achieve_milestone(lic_id, m1["id"], LM))
        assert achieved["status"] == "ACHIEVED", \
            "achieve at exactly the due date succeeds (at or before)"
        resp_twice = api.achieve_milestone(lic_id, m1["id"], LM)
        validate_error(resp_twice, ApiErrorId.ERR_MILESTONE_NOT_PENDING, 409)

        set_clock("2026-09-01T00:00:01Z")
        resp_late = api.achieve_milestone(lic_id, m2["id"], LM)
        validate_error(resp_late, ApiErrorId.ERR_MILESTONE_OVERDUE, 409)

    def test_milestone_waive_during_default_notice(self, api):
        """PRD: "Waiving a milestone stores a `waiver_reason` and moves it to
        `WAIVED`; waiver likewise requires a `PENDING` milestone, but is
        permitted while the license is `ACTIVE` or in `DEFAULT_NOTICE`."

        Design: Corner/state_machines/milestone_waive_during_default_notice_succeeds
        """
        ctx, milestone = setup_defaulted_license()
        waived = validate_success(api.waive_milestone(
            ctx["license"]["id"], milestone["id"], {"waiver_reason": "Goodwill"},
            LM))
        assert waived["status"] == "WAIVED"
        assert waived["waiver_reason"] == "Goodwill"


class TestTerminationCascade:
    def test_license_termination_full_cascade(self, api):
        """PRD: "In the first hop, every `PENDING` milestone of the license
        moves to `CANCELLED`, and every royalty report in `SUBMITTED` or
        `ACCEPTED` status moves to `VOIDED`. In the second hop, each report
        voided in the first hop that has a distribution in `CALCULATED` or
        `APPROVED` status has that distribution moved to `CANCELLED`... In
        the third hop, each distribution that had been `APPROVED` when
        cancelled reverses its recorded cost applications exactly — every
        affected cost row's `reimbursed_amount_cents` is reduced by the cents
        originally applied to it, and a row returning to 0 flips from
        `REIMBURSED` back to `UNREIMBURSED` — after which the disclosure's
        cost rollups are recomputed."

        Design: Difficulty/transitive_cascade/license_termination_cascade
        """
        ctx = setup_approved_distribution(sales_cents=20_000_000,
                                          patent_costs=[400_000])
        lic_id = ctx["license"]["id"]
        cost_id = ctx["costs"][0]["id"]
        milestone = add_milestone(lic_id, due_date="2026-06-01T00:00:00Z",
                                  description="First sale", amount_cents=50000)
        # The milestone is overdue at the current clock; declare default,
        # then advance past the cure window (notice + 60 days).
        validate_success(api.declare_default(
            lic_id, {"reason": "Milestone overdue"}, LM))
        set_clock("2026-10-02T00:00:00Z")

        terminated = validate_success(api.terminate_license(lic_id, {}, LM))
        assert terminated["status"] == "TERMINATED"

        ms = validate_success(api.get_milestone(milestone["id"], ADMIN))
        assert ms["status"] == "CANCELLED", "hop 1 cancels pending milestones"
        report = validate_success(api.get_royalty_report(ctx["report"]["id"], ADMIN))
        assert report["status"] == "VOIDED", "hop 1 voids the accepted report"
        dist = validate_success(
            api.get_distribution(ctx["distribution"]["id"], ADMIN))
        assert dist["status"] == "CANCELLED", \
            "hop 2 cancels the voided report's approved distribution"
        costs = validate_paginated(
            api.list_costs(ctx["application"]["id"], ADMIN))[0]
        cost = [c for c in costs if c["id"] == cost_id][0]
        assert cost["reimbursed_amount_cents"] == 0, "hop 3 reverses the offset"
        assert cost["reimbursement_status"] == "UNREIMBURSED"
        disc = validate_success(api.get_disclosure(ctx["disclosure"]["id"], ADMIN))
        assert disc["unreimbursed_cost_cents"] == 400_000, \
            "the rollup is restored exactly to its pre-approve value"

    def test_termination_cancels_milestones_and_voids_submitted_reports(self, api):
        """PRD: "In the first hop, every `PENDING` milestone of the license
        moves to `CANCELLED`, and every royalty report in `SUBMITTED` or
        `ACCEPTED` status moves to `VOIDED`."

        Design: Difficulty/transitive_cascade/license_termination_cascade
        """
        ctx = setup_active_license()
        lic_id = ctx["license"]["id"]
        report = submit_report(lic_id, 1000)  # stays SUBMITTED
        overdue = add_milestone(lic_id, due_date="2026-06-01T00:00:00Z")
        validate_success(api.declare_default(lic_id, {"reason": "overdue"}, LM))
        set_clock("2026-10-02T00:00:00Z")
        terminated = validate_success(api.terminate_license(lic_id, {}, LM))
        assert terminated["status"] == "TERMINATED"
        ms = validate_success(api.get_milestone(overdue["id"], ADMIN))
        assert ms["status"] == "CANCELLED"
        rep = validate_success(api.get_royalty_report(report["id"], ADMIN))
        assert rep["status"] == "VOIDED"
