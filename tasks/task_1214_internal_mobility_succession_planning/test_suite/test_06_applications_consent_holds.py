"""Internal posting applications: eligibility, consent windows, holds, offers."""
from datetime import timedelta

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_manager,
    setup_active_role, add_active_successor,
    setup_vacancy_scenario, setup_open_posting, setup_application,
    consent_application, advance_application, terminate_and_get_vacancy,
    set_clock, parse_timestamp,
    make_employee_headers, make_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _env(api, **posting_overrides):
    """OPEN vacancy + OPEN posting. Returns the scenario context plus posting."""
    ctx = setup_vacancy_scenario()
    ctx["posting"] = setup_open_posting(
        ctx["vacancy"]["id"], ctx["hrbp_headers"], **posting_overrides,
    )
    return ctx


def _applicant(api, manager=None, **overrides):
    overrides.setdefault("job_level", 5)
    overrides.setdefault("hire_date", "2024-05-01")
    overrides.setdefault("performance_rating", "SOLID")
    if manager is not None:
        overrides["current_manager_id"] = manager["id"]
    return setup_employee(**overrides)


class TestApplicationEligibility:
    def test_terminated_applicant_returns_employee_not_active(self, api):
        """PRD §3.5: "Applying enforces five checks in order: the posting must
        be `OPEN` (otherwise `ERR_POSTING_INVALID_STATE`); the applicant's
        `employment_status` must be `ACTIVE` (otherwise
        `ERR_EMPLOYEE_NOT_ACTIVE`); the applicant's whole-month tenure per §2.4
        must be at least the posting's `min_tenure_months`, with equality
        passing (otherwise `ERR_TENURE_REQUIREMENT`); the applicant's
        `job_level` must be at least `min_job_level` (otherwise
        `ERR_JOB_LEVEL_REQUIREMENT`); and the applicant must not already hold
        another non-terminal application on the same posting (otherwise
        `ERR_DUPLICATE_APPLICATION`)."

        Design: Corner/validations/terminated_applicant_returns_employee_not_active
        """
        ctx = _env(api)
        applicant = _applicant(api)
        validate_success(api.terminate_employee(applicant["id"], ADMIN), 200)

        resp = api.create_application(
            ctx["posting"]["id"], make_employee_headers(applicant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE, 409)

        applications, meta = validate_paginated(api.list_applications(
            ctx["hrbp_headers"], params={"posting_id": ctx["posting"]["id"]},
        ))
        assert meta["total_count"] == 0, "no application may be created"

    def test_job_level_requirement_returns_error(self, api):
        """PRD §3.5: "the applicant's `job_level` must be at least
        `min_job_level` (otherwise `ERR_JOB_LEVEL_REQUIREMENT`)"

        Design: Corner/validations/job_level_requirement_returns_error
        """
        ctx = _env(api, min_tenure_months=12, min_job_level=7)
        applicant = _applicant(api, job_level=5, hire_date="2024-05-01")

        resp = api.create_application(
            ctx["posting"]["id"], make_employee_headers(applicant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_JOB_LEVEL_REQUIREMENT, 409)
        applications, meta = validate_paginated(api.list_applications(
            ctx["hrbp_headers"], params={"posting_id": ctx["posting"]["id"]},
        ))
        assert meta["total_count"] == 0

    def test_tenure_months_boundary_for_posting_eligibility(self, api):
        """PRD §2.4: "Tenure is measured in whole calendar months between an
        employee's `hire_date` and the current logical-clock instant: twelve
        times the difference in calendar years plus the difference in calendar
        months, reduced by one when the day-of-month of the current instant is
        earlier than the day-of-month of the hire date."
        PRD §2.4: "A posting's tenure requirement passes on equality — an
        applicant whose whole-month tenure exactly equals the required minimum
        is eligible — while the retention-risk tenure modifier applies when
        tenure is less than 24 months."

        Design: Corner/calculations/tenure_months_boundary_for_posting_eligibility
        """
        ctx = _env(api, min_tenure_months=24)
        # At the startup clock 2026-05-01: hire 2024-05-01 -> exactly 24 months;
        # hire 2024-05-02 -> 23 months (day-of-month 1 < 2 reduces the count).
        eligible = _applicant(api, job_level=8, hire_date="2024-05-01")
        short = _applicant(api, job_level=8, hire_date="2024-05-02")

        ok = validate_success(api.create_application(
            ctx["posting"]["id"], make_employee_headers(eligible["id"]),
        ), 201)
        assert ok["status"] == "CONSENT_GRANTED", (
            "tenure exactly equal to the minimum passes (equality passes)"
        )

        resp = api.create_application(
            ctx["posting"]["id"], make_employee_headers(short["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TENURE_REQUIREMENT, 409)

    def test_duplicate_application_returns_error(self, api):
        """PRD §3.5: "and the applicant must not already hold another
        non-terminal application on the same posting (otherwise
        `ERR_DUPLICATE_APPLICATION`)."

        Design: Corner/validations/duplicate_application_returns_error
        """
        ctx = _env(api)
        applicant = _applicant(api)
        first = setup_application(ctx["posting"]["id"], applicant)
        assert first["status"] in ("PENDING_MANAGER_CONSENT", "CONSENT_GRANTED")

        resp = api.create_application(
            ctx["posting"]["id"], make_employee_headers(applicant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)

        applications, meta = validate_paginated(api.list_applications(
            ctx["hrbp_headers"],
            params={"posting_id": ctx["posting"]["id"], "employee_id": applicant["id"]},
        ))
        assert meta["total_count"] == 1


class TestClosedPostingPriority:
    def _setup_closed_posting(self, api):
        """Posting published then closed; low-tenure applicant standing by."""
        ctx = _env(api, min_tenure_months=12)
        validate_success(api.close_posting(ctx["posting"]["id"], ctx["hrbp_headers"]), 200)
        low_tenure = _applicant(api, hire_date="2025-06-01")
        return ctx, low_tenure

    def test_closed_posting_and_tenure_state_beats_constraint(self, api):
        """PRD §3.5: "Applying enforces five checks in order: the posting must
        be `OPEN` (otherwise `ERR_POSTING_INVALID_STATE`); the applicant's
        `employment_status` must be `ACTIVE` (otherwise
        `ERR_EMPLOYEE_NOT_ACTIVE`); the applicant's whole-month tenure per §2.4
        must be at least the posting's `min_tenure_months`, with equality
        passing (otherwise `ERR_TENURE_REQUIREMENT`)"
        PRD §2.8: "Every request passes through a fixed validation pipeline,
        and a request that violates several checks is rejected by the earliest
        applicable one."

        Design: Difficulty/priority_pair_validation_conflict/closed_posting_and_tenure_state_beats_constraint
        """
        ctx, low_tenure = self._setup_closed_posting(api)

        resp = api.create_application(
            ctx["posting"]["id"], make_employee_headers(low_tenure["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POSTING_INVALID_STATE, 409)
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_TENURE_REQUIREMENT", (
            "the state error (posting CLOSED) must mask the tenure failure"
        )

    def test_closed_posting_creates_no_application(self, api):
        """PRD §3.5: "Applying enforces five checks in order: the posting must
        be `OPEN` (otherwise `ERR_POSTING_INVALID_STATE`)"
        PRD §3.5: "Applications can be listed filtered by `posting_id`,
        `employee_id`, or `status`."

        Design: Difficulty/priority_pair_validation_conflict/closed_posting_and_tenure_state_beats_constraint
        """
        ctx, low_tenure = self._setup_closed_posting(api)

        api.create_application(
            ctx["posting"]["id"], make_employee_headers(low_tenure["id"]),
        )
        applications, meta = validate_paginated(api.list_applications(
            ctx["hrbp_headers"], params={"posting_id": ctx["posting"]["id"]},
        ))
        assert applications == [] and meta["total_count"] == 0


class TestConsentWindow:
    def _setup_two_pending_applications(self, api):
        """One posting; two applicants managed by the same manager; both
        applications PENDING_MANAGER_CONSENT at the default clock
        (consent_deadline 2026-05-15T00:00:00Z)."""
        ctx = _env(api)
        manager, _ = setup_manager()
        app_a = _applicant(api, manager=manager)
        app_b = _applicant(api, manager=manager)
        application_a = setup_application(ctx["posting"]["id"], app_a)
        application_b = setup_application(ctx["posting"]["id"], app_b)
        assert application_a["status"] == "PENDING_MANAGER_CONSENT"
        assert application_b["status"] == "PENDING_MANAGER_CONSENT"
        return ctx, manager, application_a, application_b

    def test_consent_one_second_before_deadline_succeeds(self, api):
        """PRD §2.4: "An application's `consent_deadline` is its
        `submitted_at` instant plus 14 days, and a manager's consent or hold is
        accepted only while the current instant is strictly before that
        deadline — at exactly the deadline the window is already closed and the
        action is rejected with `ERR_CONSENT_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/consent_deadline_exact_instant_rejected
        """
        ctx, manager, application_a, _ = self._setup_two_pending_applications(api)
        assert_instant = parse_timestamp(application_a["consent_deadline"])
        assert_instant = assert_instant - timedelta(seconds=1)
        set_clock(assert_instant.strftime("%Y-%m-%dT%H:%M:%SZ"))

        consented = validate_success(
            api.consent_application(application_a["id"], make_manager_headers(manager["id"])),
            200,
        )
        assert consented["status"] == "CONSENT_GRANTED", (
            "one second before the deadline the window is still open"
        )

    def test_consent_at_exact_deadline_rejected(self, api):
        """PRD §2.4: "An application's `consent_deadline` is its
        `submitted_at` instant plus 14 days, and a manager's consent or hold is
        accepted only while the current instant is strictly before that
        deadline — at exactly the deadline the window is already closed and the
        action is rejected with `ERR_CONSENT_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/consent_deadline_exact_instant_rejected
        """
        ctx, manager, _, application_b = self._setup_two_pending_applications(api)
        set_clock("2026-05-15T00:00:00Z")  # exactly the consent deadline

        resp = api.consent_application(
            application_b["id"], make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_WINDOW_CLOSED, 409)
        after = get_success_data(api.get_application(application_b["id"], ADMIN))
        assert after["status"] == "PENDING_MANAGER_CONSENT"


class TestHoldLimitCompensation:
    def _setup_two_applications_one_applicant(self, api):
        """Employee E_H (manager MH) holds PENDING_MANAGER_CONSENT applications
        on two different postings (two vacancies from two incumbents)."""
        hrbp, hrbp_headers = setup_hrbp()
        manager, _ = setup_manager()
        holder = _applicant(api, manager=manager)
        applications = []
        for title in ("Role A", "Role B"):
            incumbent = setup_employee(job_level=8, performance_rating="STRONG",
                                       hire_date="2019-03-01")
            role = setup_active_role(hrbp_headers, incumbent["id"], role_title=title)
            vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
            posting = setup_open_posting(vacancy["id"], hrbp_headers, title=title,
                                         min_tenure_months=12)
            applications.append(setup_application(posting["id"], holder))
        return hrbp_headers, manager, holder, applications

    def test_hold_raises_count_and_second_hold_rejected(self, api):
        """PRD §3.5: "Placing a hold runs the same three checks in the same
        order, then requires the applicant's `active_hold_count` to be below
        the single active hold any employee may carry (otherwise
        `ERR_HOLD_LIMIT_REACHED`) and a `hold_reason` of `CRITICAL_PROJECT`,
        `PERFORMANCE_PLAN`, or `RECENT_MOVE` to be supplied (otherwise
        `ERR_INVALID_REQUEST`); a placed hold moves the application to
        `MANAGER_HOLD`, stamps `hold_at` from the logical clock, sets
        `hold_expires_at` 30 days later, and raises the applicant's
        `active_hold_count` by one."

        Design: Difficulty/compensating_invariant/hold_release_restores_active_hold_count
        """
        _, manager, holder, (app1, app2) = self._setup_two_applications_one_applicant(api)

        held = validate_success(api.hold_application(
            app1["id"], {"hold_reason": "CRITICAL_PROJECT"},
            make_manager_headers(manager["id"]),
        ), 200)
        assert held["status"] == "MANAGER_HOLD"

        employee = get_success_data(api.get_employee(holder["id"], ADMIN))
        assert employee["active_hold_count"] == 1

        resp = api.hold_application(
            app2["id"], {"hold_reason": "PERFORMANCE_PLAN"},
            make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOLD_LIMIT_REACHED, 409)

    def test_release_restores_count_and_rehold_succeeds(self, api):
        """PRD §3.5: "Releasing a hold — again by the reporting manager only —
        moves `MANAGER_HOLD` back to `CONSENT_GRANTED` and lowers the count by
        one, so a hold followed by a release leaves `active_hold_count`
        unchanged; the release is not subject to the consent window."

        Design: Difficulty/compensating_invariant/hold_release_restores_active_hold_count
        """
        _, manager, holder, (app1, app2) = self._setup_two_applications_one_applicant(api)

        validate_success(api.hold_application(
            app1["id"], {"hold_reason": "CRITICAL_PROJECT"},
            make_manager_headers(manager["id"]),
        ), 200)
        released = validate_success(
            api.release_hold_application(app1["id"], make_manager_headers(manager["id"])),
            200,
        )
        assert released["status"] == "CONSENT_GRANTED"

        employee = get_success_data(api.get_employee(holder["id"], ADMIN))
        assert employee["active_hold_count"] == 0, (
            "the hold + release pair must leave the conserved count unchanged"
        )

        held = validate_success(api.hold_application(
            app2["id"], {"hold_reason": "PERFORMANCE_PLAN"},
            make_manager_headers(manager["id"]),
        ), 200)
        assert held["status"] == "MANAGER_HOLD"


class TestConsentOwnership:
    def test_consent_by_wrong_manager_within_window_returns_not_reporting_manager(self, api):
        """PRD §2.10: "Reporting-manager ownership requires `X-User-ID` to
        equal the subject employee's `current_manager_id` when a manager
        consents to an application, places or releases a hold, nominates a
        direct report to a program cycle, or proposes a calibration rating;
        violations are rejected with `ERR_NOT_REPORTING_MANAGER` (HTTP 403)."
        PRD §3.5: "Granting consent requires the application to be
        `PENDING_MANAGER_CONSENT` (otherwise `ERR_APPLICATION_INVALID_STATE`),
        the caller to equal the applicant's `current_manager_id` (otherwise
        `ERR_NOT_REPORTING_MANAGER`), and the current instant to be strictly
        before the `consent_deadline` (otherwise `ERR_CONSENT_WINDOW_CLOSED`);
        success moves the application to `CONSENT_GRANTED`."

        Design: Corner/validations/consent_by_wrong_manager_within_window_returns_not_reporting_manager
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        other, _ = setup_manager()
        applicant = _applicant(api, manager=manager)
        application = setup_application(ctx["posting"]["id"], applicant)
        assert application["status"] == "PENDING_MANAGER_CONSENT"

        resp = api.consent_application(
            application["id"], make_manager_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_REPORTING_MANAGER, 403)
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "PENDING_MANAGER_CONSENT"

        consented = consent_application(application["id"], manager["id"])
        assert consented["status"] == "CONSENT_GRANTED", (
            "the real manager can still consent afterwards"
        )

    def test_foreign_manager_after_deadline_referential_beats_temporal(self, api):
        """PRD §3.5: "Placing a hold runs the same three checks in the same
        order, then requires the applicant's `active_hold_count` to be below
        the single active hold any employee may carry"
        PRD §2.8: "Every request passes through a fixed validation pipeline,
        and a request that violates several checks is rejected by the earliest
        applicable one."

        Design: Difficulty/priority_pair_validation_conflict/foreign_manager_after_deadline_referential_beats_temporal
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        other, _ = setup_manager()
        applicant = _applicant(api, manager=manager)
        application = setup_application(ctx["posting"]["id"], applicant)
        # Submitted at the default clock 2026-05-01T00:00:00Z; deadline
        # 2026-05-15T00:00:00Z. Advance past it.
        set_clock("2026-05-20T00:00:00Z")

        resp = api.hold_application(
            application["id"], {"hold_reason": "CRITICAL_PROJECT"},
            make_manager_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_REPORTING_MANAGER, 403)
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_CONSENT_WINDOW_CLOSED", (
            "referential ownership (earlier check) must mask the expired window"
        )
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "PENDING_MANAGER_CONSENT"

    def test_foreign_manager_after_deadline_real_manager_also_blocked(self, api):
        """PRD §2.4: "An application's `consent_deadline` is its
        `submitted_at` instant plus 14 days, and a manager's consent or hold is
        accepted only while the current instant is strictly before that
        deadline — at exactly the deadline the window is already closed and the
        action is rejected with `ERR_CONSENT_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/foreign_manager_after_deadline_referential_beats_temporal
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        applicant = _applicant(api, manager=manager)
        application = setup_application(ctx["posting"]["id"], applicant)
        set_clock("2026-05-20T00:00:00Z")

        resp = api.hold_application(
            application["id"], {"hold_reason": "CRITICAL_PROJECT"},
            make_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_WINDOW_CLOSED, 409)
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "PENDING_MANAGER_CONSENT"


class TestWithdrawAndAdvance:
    def test_application_withdraw_twice_returns_invalid_state(self, api):
        """PRD §3.5: "Withdrawal is likewise the applicant's alone: from any
        non-terminal status (a terminal application rejects the attempt with
        `ERR_APPLICATION_INVALID_STATE`), with the caller matching
        `employee_id` (otherwise `ERR_APPLICANT_NOT_SELF`), the application
        becomes `WITHDRAWN`"

        Design: Corner/state_machines/application_withdraw_twice_returns_invalid_state
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        applicant = _applicant(api, manager=manager)
        application = setup_application(ctx["posting"]["id"], applicant)

        withdrawn = validate_success(
            api.withdraw_application(application["id"], make_employee_headers(applicant["id"])),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.withdraw_application(
            application["id"], make_employee_headers(applicant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE, 409)
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "WITHDRAWN"

    def test_withdraw_by_other_employee_returns_applicant_not_self(self, api):
        """PRD §2.10: "Applicant self-service ownership requires `X-User-ID` to
        equal the application's `employee_id` when an employee withdraws an
        application or responds to an offer; violations are rejected with
        `ERR_APPLICANT_NOT_SELF` (HTTP 403)."

        Design: Corner/validations/withdraw_by_other_employee_returns_applicant_not_self
        """
        ctx = _env(api)
        applicant = _applicant(api)  # no manager -> lands in CONSENT_GRANTED
        other = _applicant(api)
        application = setup_application(ctx["posting"]["id"], applicant)
        assert application["status"] == "CONSENT_GRANTED"

        resp = api.withdraw_application(
            application["id"], make_employee_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_SELF, 403)
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "CONSENT_GRANTED"

    def test_application_advance_skip_stage_returns_invalid_state(self, api):
        """PRD §3.5: "`OFFER_EXTENDED` from `INTERVIEWING`, which additionally
        requires the posting to still be `OPEN` (otherwise
        `ERR_POSTING_INVALID_STATE`) and its vacancy to still be `OPEN`
        (otherwise `ERR_VACANCY_NOT_OPEN`) — this is where applications
        stranded by a slate fill die; or `REJECTED` from either
        `CONSENT_GRANTED` or `INTERVIEWING`. Any other pairing of current
        status and target is rejected with `ERR_APPLICATION_INVALID_STATE`."

        Design: Corner/state_machines/application_advance_skip_stage_returns_invalid_state
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        applicant = _applicant(api, manager=manager)
        application = setup_application(ctx["posting"]["id"], applicant)
        consent_application(application["id"], manager["id"])

        resp = api.advance_application(
            application["id"], {"target_state": "OFFER_EXTENDED"}, ctx["hrbp_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE, 409)
        after = get_success_data(api.get_application(application["id"], ADMIN))
        assert after["status"] == "CONSENT_GRANTED"


class TestManagerlessApplicant:
    def test_managerless_applicant_skips_manager_consent(self, api):
        """PRD §3.5: "A created application is stamped with `submitted_at` from
        the logical clock and a `consent_deadline` 14 days later, and starts in
        `PENDING_MANAGER_CONSENT` — or directly in `CONSENT_GRANTED`, skipping
        the consent step entirely, when the applicant has no current manager."

        Design: Corner/state_machines/managerless_applicant_skips_manager_consent
        """
        ctx = _env(api)
        applicant = _applicant(api)  # current_manager_id omitted -> null
        application = setup_application(ctx["posting"]["id"], applicant)
        assert application["status"] == "CONSENT_GRANTED", (
            "no current manager -> the consent step is skipped entirely"
        )
        delta = parse_timestamp(application["consent_deadline"]) - parse_timestamp(
            application["submitted_at"]
        )
        assert delta == timedelta(days=14), (
            "consent_deadline must still be stamped as submitted_at + 14 days"
        )


class TestOfferFlow:
    def test_offer_acceptance_fills_vacancy_via_posting_channel(self, api):
        """PRD §3.5: "A `decision` of `ACCEPT` moves it to `OFFER_ACCEPTED` and
        fires the posting-channel fill cascade: the vacancy transitions `OPEN`
        to `FILLED` with `fill_source` `INTERNAL_POSTING` and
        `filled_by_employee_id` set to the applicant; the role transitions
        `VACANT` to `ACTIVE` with the applicant as incumbent, its `version`
        incrementing; the posting transitions `OPEN` to `CLOSED`; every other
        non-terminal application of the posting becomes `REJECTED`; and if the
        applicant holds a successor entry on this role in `ACTIVE` or
        `SUSPENDED` status, that entry becomes `PROMOTED`, with the role's
        bench recomputing."

        Design: Corner/state_machines/offer_acceptance_fills_vacancy_via_posting_channel
        """
        ctx = _env(api)
        manager, _ = setup_manager()
        applicant_a = _applicant(api, manager=manager)
        applicant_b = _applicant(api, manager=manager)
        app_a = setup_application(ctx["posting"]["id"], applicant_a)
        app_b = setup_application(ctx["posting"]["id"], applicant_b)
        consent_application(app_a["id"], manager["id"])
        advance_application(app_a["id"], "INTERVIEWING", ctx["hrbp_headers"])
        advance_application(app_a["id"], "OFFER_EXTENDED", ctx["hrbp_headers"])
        consent_application(app_b["id"], manager["id"])

        accepted = validate_success(api.respond_offer(
            app_a["id"], {"decision": "ACCEPT"},
            make_employee_headers(applicant_a["id"]),
        ), 200)
        assert accepted["status"] == "OFFER_ACCEPTED"

        vacancy = get_success_data(api.get_vacancy(ctx["vacancy"]["id"], ctx["hrbp_headers"]))
        assert vacancy["status"] == "FILLED"
        assert vacancy["fill_source"] == "INTERNAL_POSTING"
        assert vacancy["filled_by_employee_id"] == applicant_a["id"]

        role = get_success_data(api.get_critical_role(ctx["role"]["id"], ctx["hrbp_headers"]))
        assert role["status"] == "ACTIVE"
        assert role["incumbent_employee_id"] == applicant_a["id"]

        posting = get_success_data(api.get_posting(ctx["posting"]["id"], ctx["hrbp_headers"]))
        assert posting["status"] == "CLOSED"

        app_b = get_success_data(api.get_application(app_b["id"], ctx["hrbp_headers"]))
        assert app_b["status"] == "REJECTED", (
            "every other non-terminal application of the posting becomes REJECTED"
        )


class TestOfferBlockedAfterSlateFill:
    def _setup_interviewing_then_fill(self, api):
        """INTERVIEWING application on an OPEN posting whose vacancy is then
        filled from the succession slate."""
        hrbp, hrbp_headers = setup_hrbp()
        manager, _ = setup_manager()
        incumbent = setup_employee(job_level=8, performance_rating="STRONG",
                                   hire_date="2019-03-01")
        successor = setup_employee(job_level=6, performance_rating="STRONG",
                                   hire_date="2022-07-01")
        applicant = _applicant(api, manager=manager)
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Data Lead", criticality_tier="TIER_1")
        add_active_successor(role["id"], successor["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
        posting = setup_open_posting(vacancy["id"], hrbp_headers, title="Data Lead",
                                     min_tenure_months=12)
        application = setup_application(posting["id"], applicant)
        consent_application(application["id"], manager["id"])
        advance_application(application["id"], "INTERVIEWING", hrbp_headers)

        filled = validate_success(
            api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers), 200,
        )
        assert filled["status"] == "FILLED"
        return hrbp_headers, posting, application, vacancy

    def test_slate_fill_leaves_posting_open(self, api):
        """PRD §3.4: "The vacancy's postings are deliberately not touched — the
        posting channel winds down independently, and the `HRBusinessPartner`
        closes it manually; applications that had reached `INTERVIEWING` will
        subsequently fail offer extension with `ERR_VACANCY_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/offer_extension_blocked_after_vacancy_filled
        """
        hrbp_headers, posting, application, vacancy = self._setup_interviewing_then_fill(api)
        posting = get_success_data(api.get_posting(posting["id"], hrbp_headers))
        assert posting["status"] == "OPEN", "a slate fill must not touch the posting channel"
        application = get_success_data(api.get_application(application["id"], hrbp_headers))
        assert application["status"] == "INTERVIEWING"

    def test_offer_extension_blocked_after_vacancy_filled(self, api):
        """PRD §3.5: "`OFFER_EXTENDED` from `INTERVIEWING`, which additionally
        requires the posting to still be `OPEN` (otherwise
        `ERR_POSTING_INVALID_STATE`) and its vacancy to still be `OPEN`
        (otherwise `ERR_VACANCY_NOT_OPEN`) — this is where applications
        stranded by a slate fill die"
        PRD §3.4: "applications that had reached `INTERVIEWING` will
        subsequently fail offer extension with `ERR_VACANCY_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/offer_extension_blocked_after_vacancy_filled
        """
        hrbp_headers, posting, application, vacancy = self._setup_interviewing_then_fill(api)

        resp = api.advance_application(
            application["id"], {"target_state": "OFFER_EXTENDED"}, hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VACANCY_NOT_OPEN, 409)
        after = get_success_data(api.get_application(application["id"], hrbp_headers))
        assert after["status"] == "INTERVIEWING"
