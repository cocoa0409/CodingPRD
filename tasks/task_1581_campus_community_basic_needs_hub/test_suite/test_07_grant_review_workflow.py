"""Grant review workflow: info-request resubmission cycle, expiry reopen
cascade, submit gate ordering, terminal lockdown, disbursement window, and
segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_client,
    create_approved_grant,
    create_coordinator,
    create_draft_grant,
    create_fund,
    create_reviewer,
    create_under_review_grant,
    run_sweeps,
    set_clock,
    setup_disbursed_grant_scenario,
    setup_exhausted_fund_with_queued_grant,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    make_client_headers,
    make_hub_admin_headers,
)

ADMIN = TEST_USERS["hub_admin_headers"]


def _under_review_scenario(alias="wren", fund_name="FY26", requested=80000):
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, client_headers = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=120000,
            housing_status="UNSTABLE", dependents_under_18=1,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=4, consent_confidential=True,
        ),
        client_overrides={"alias_name": alias},
    )
    fund = create_fund(fund_name, allocated_cents=500000)
    grant = create_under_review_grant(
        client, fund, reviewer,
        category="UTILITY", requested_cents=requested,
        hardship_statement="shutoff notice",
    )
    return coord, reviewer, client, client_headers, fund, grant


class TestInfoRequestResubmissionCycle:
    def test_request_info_then_resubmit_clears_reviewer(self, api):
        """PRD §3.5: "Requesting more information moves `UNDER_REVIEW` to
        `MORE_INFO_REQUESTED` and records the reviewer's `info_request_notes`.
        The applicant's resubmission — again by the creating client or an
        `IntakeCoordinator`, with the same client-active and
        verified-assessment gates — moves `MORE_INFO_REQUESTED` back to
        `SUBMITTED`, clearing `reviewed_by` so the application re-enters the
        open review pool."

        Design: Difficulty/non_linear_state_machine/grant_info_request_resubmission_cycle
        """
        _, reviewer, _, client_headers, _, grant = _under_review_scenario()
        more_info = validate_success(
            api.request_info(grant["id"], {"info_request_notes": "need current lease"},
                             reviewer),
            200,
        )
        assert more_info["status"] == "MORE_INFO_REQUESTED"
        assert more_info["info_request_notes"] == "need current lease"

        resubmitted = validate_success(
            api.submit_grant_application(grant["id"], client_headers), 200
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["reviewed_by"] is None, (
            "resubmission clears the review claim"
        )

    def test_cycle_leaves_fund_untouched_and_application_reclaimable(self, api):
        """PRD §3.5: "Review begins when a `GrantReviewer` claims a
        `SUBMITTED` application, moving it to `UNDER_REVIEW` and stamping
        `reviewed_by` with the acting reviewer's staff id."
        PRD §3.5: "`committed_cents` sums the `approved_cents` of the fund's
        applications currently in `APPROVED`."

        Design: Difficulty/non_linear_state_machine/grant_info_request_resubmission_cycle
        """
        _, reviewer, _, client_headers, fund, grant = _under_review_scenario()
        validate_success(
            api.request_info(grant["id"], {"info_request_notes": "need current lease"},
                             reviewer),
            200,
        )
        validate_success(api.submit_grant_application(grant["id"], client_headers), 200)

        reclaimed = validate_success(api.begin_review(grant["id"], reviewer), 200)
        assert reclaimed["status"] == "UNDER_REVIEW"
        assert reclaimed["reviewed_by"] is not None

        fund_after = validate_success(api.get_grant_fund(fund["id"], reviewer), 200)
        assert fund_after["committed_cents"] == 0, (
            "the revision loop never touches fund accounting"
        )


class TestGrantExpiryReopenCascade:
    def test_expiry_sweep_reopens_exhausted_fund(self, api):
        """PRD §3.5: "An approval never disbursed in time expires instead: the
        sweep moves `APPROVED` to `EXPIRED` once the logical clock is strictly
        past the 72-hour mark, releasing `committed_cents`, recomputing the
        bases, advancing the fund's `version`, and running the same
        reopen-and-promote cascade."
        PRD §2.10: "A fund flips from `OPEN` to `EXHAUSTED` when an approval
        consumes the last of its committed-basis remainder, and back to `OPEN`
        when disbursement or approval expiry restores headroom — each reopen
        promoting one queued application."

        Design: Difficulty/transitive_cascade/grant_expiry_reopens_fund_and_promotes_queued_application
        """
        env = setup_exhausted_fund_with_queued_grant()
        assert env["queued_grant"]["status"] == "QUEUED", (
            "submission against the EXHAUSTED fund parks as QUEUED"
        )
        set_clock("2026-08-04T00:00:01Z")
        sweep = run_sweeps()
        assert sweep["grants_expired"] == 2
        assert sweep["queued_grants_promoted"] == 1

        fund = validate_success(
            api.get_grant_fund(env["fund"]["id"], env["reviewer_headers"]), 200
        )
        assert fund["committed_cents"] == 0
        assert fund["remaining_committed_basis"] == 300000
        assert fund["status"] == "OPEN", "reopened when the remainder returned"

    def test_reopen_promotes_oldest_queued_application(self, api):
        """PRD §3.5: "Queued promotion is automatic: when a fund flips from
        `EXHAUSTED` back to `OPEN` within a single atomic event, the queued
        application on that fund with the earliest `created_at` moves to
        `SUBMITTED`, at most one promotion per reopen event."

        Design: Difficulty/transitive_cascade/grant_expiry_reopens_fund_and_promotes_queued_application
        """
        env = setup_exhausted_fund_with_queued_grant()
        set_clock("2026-08-04T00:00:01Z")
        run_sweeps()

        promoted = validate_success(
            api.get_grant_application(env["queued_grant"]["id"], env["reviewer_headers"]),
            200,
        )
        assert promoted["status"] == "SUBMITTED"
        for app in (env["app_a"], env["app_b"]):
            after = validate_success(
                api.get_grant_application(app["id"], env["reviewer_headers"]), 200
            )
            assert after["status"] == "EXPIRED", (
                "approved at 2026-08-01T00:00:00Z, strictly past +72h at the sweep"
            )


class TestSubmitGateOrdering:
    def _suspended_client_with_closed_fund(self):
        """DRAFT application created while the client is ACTIVE and the fund
        OPEN; then the client is SUSPENDED and the fund CLOSED (a DRAFT does
        not block closing)."""
        _, coord = create_coordinator()
        client, _, client_headers = create_active_client(
            coord, client_overrides={"alias_name": "ivy"}
        )
        fund = create_fund("FY26-mini", allocated_cents=100000)
        grant = create_draft_grant(
            client["id"], fund["id"], client_headers,
            category="TRANSPORT", requested_cents=20000,
            hardship_statement="bus pass",
        )
        validate_success(api_client.suspend_client(client["id"], ADMIN), 200)
        closed = validate_success(api_client.close_grant_fund(fund["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"
        return coord, client, grant

    def test_suspended_client_submit_reports_client_gate(self, api):
        """PRD §2.6: "Every request is evaluated against a fixed cascade of
        checks, and a rejection at any step halts the cascade — earlier
        failures mask later ones rather than accumulating." The client-status
        gate (step 8) precedes the domain business rules (step 10).
        PRD §3.5: "Submission ... requires the client `ACTIVE` (else
        `ERR_CLIENT_NOT_ACTIVE`) with a verified assessment (else
        `ERR_ASSESSMENT_REQUIRED`) and a fund that is not `CLOSED` (else
        `ERR_FUND_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_suspended_client_and_closed_fund_state_beats_fiscal
        """
        coord, _, grant = self._suspended_client_with_closed_fund()
        res = api.submit_grant_application(grant["id"], coord)
        validate_error(res, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, expected_status=409)

    def test_masked_fund_gate_surfaces_after_reinstate(self, api):
        """PRD §2.6: "a rejection at any step halts the cascade — earlier
        failures mask later ones rather than accumulating."
        PRD §3.5: "... and a fund that is not `CLOSED` (else
        `ERR_FUND_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_suspended_client_and_closed_fund_state_beats_fiscal
        """
        coord, client, grant = self._suspended_client_with_closed_fund()
        validate_success(api.reinstate_client(client["id"], ADMIN), 200)
        res = api.submit_grant_application(grant["id"], coord)
        validate_error(res, ApiErrorId.ERR_FUND_CLOSED, expected_status=409)


def test_terminal_disbursed_grant_rejects_all_actions(api):
    """PRD §3.5: "Either party on the applicant side — the creating client or
    an `IntakeCoordinator` — may withdraw an application from `DRAFT`,
    `SUBMITTED`, or `QUEUED`, moving it to `WITHDRAWN`; withdrawal from any
    later state is `ERR_GRANT_NOT_REVIEWABLE`."
    PRD §3.5: "Denial, likewise reserved to the recorded reviewer, moves
    `UNDER_REVIEW` to the terminal `DENIED` state ..."
    PRD §2.6: "the target resource's current state must admit the requested
    transition. Where the governing state machine names a machine-specific
    error, that error applies ..."

    Design: Corner/state_machines/terminal_disbursed_grant_rejects_all_actions
    """
    env = setup_disbursed_grant_scenario()
    assert env["grant"]["status"] == "DISBURSED"

    res = api.withdraw_grant(env["grant"]["id"], make_client_headers(env["client"]["id"]))
    validate_error(res, ApiErrorId.ERR_GRANT_NOT_REVIEWABLE, expected_status=409)

    res = api.deny_grant(
        env["grant"]["id"], {"decision_rationale": "too late"}, env["reviewer_headers"]
    )
    validate_error(res, ApiErrorId.ERR_GRANT_NOT_REVIEWABLE, expected_status=409)

    fund = validate_success(api.get_grant_fund(env["fund"]["id"], env["reviewer_headers"]), 200)
    assert fund["disbursed_cents"] == 100000, "terminal lockdown — no drift"


def test_disburse_window_inclusive_boundary_then_lapsed(api):
    """PRD §3.5: "the logical clock must be no later than 72 hours after
    `approved_at`, inclusive — a disbursement at exactly the 72-hour mark is
    admitted, anything later is `ERR_DISBURSE_WINDOW_LAPSED`."
    PRD §3.5: "the sweep moves `APPROVED` to `EXPIRED` once the logical clock
    is strictly past the 72-hour mark, releasing `committed_cents` ..."

    Design: Corner/errors/disburse_window_inclusive_boundary_then_lapsed
    """
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "dw"})
    fund = create_fund("FY26-d", allocated_cents=500000)
    app1, _ = create_approved_grant(
        client, fund, reviewer, category="UTILITY", requested_cents=50000,
        hardship_statement="one",
    )
    app2, _ = create_approved_grant(
        client, fund, reviewer, category="UTILITY", requested_cents=50000,
        hardship_statement="two",
    )
    admin9 = make_hub_admin_headers("admin-9")

    # Exactly approved_at + 72h: the inclusive boundary admits disbursement.
    set_clock("2026-08-04T00:00:00Z")
    disbursed = validate_success(api.disburse_grant(app1["id"], admin9), 200)
    assert disbursed["status"] == "DISBURSED"

    # One second later the window has lapsed for app2.
    set_clock("2026-08-04T00:00:01Z")
    res = api.disburse_grant(app2["id"], admin9)
    validate_error(res, ApiErrorId.ERR_DISBURSE_WINDOW_LAPSED, expected_status=409)

    sweep = run_sweeps()
    assert sweep["grants_expired"] == 1
    app2_after = validate_success(api.get_grant_application(app2["id"], reviewer), 200)
    assert app2_after["status"] == "EXPIRED"


def test_sod_reviewer_who_assisted_intake_cannot_review(api):
    """PRD §2.9: "the reviewer who begins review of an application must not be
    the user recorded as its `created_by_user_id`; because grant creation is
    open to `GrantReviewer` for staff-assisted intake, this conflict is
    reachable and is rejected with `ERR_SOD_CONFLICT`."

    Design: Corner/rbac/sod_reviewer_who_assisted_intake_cannot_review
    """
    _, coord = create_coordinator()
    r1, r1_headers = create_reviewer(email="r1@hub.test", full_name="R One")
    r2, r2_headers = create_reviewer(email="r2@hub.test", full_name="R Two")
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "sod"})
    fund = create_fund("FY26-s", allocated_cents=500000)

    grant = create_draft_grant(
        client["id"], fund["id"], r1_headers,
        category="RENT", requested_cents=40000,
        hardship_statement="assisted intake",
    )
    assert grant["created_by_user_id"] == r1["id"]
    validate_success(api.submit_grant_application(grant["id"], coord), 200)

    res = api.begin_review(grant["id"], r1_headers)
    validate_error(res, ApiErrorId.ERR_SOD_CONFLICT, expected_status=409)

    claimed = validate_success(api.begin_review(grant["id"], r2_headers), 200)
    assert claimed["status"] == "UNDER_REVIEW"
    assert claimed["reviewed_by"] == r2["id"]


def test_disburse_two_person_rule_blocks_reviewing_admin(api):
    """PRD §2.9: "the two-person rule on disbursement requires the disbursing
    `HubAdmin`'s `X-User-ID` to differ from the application's recorded
    `reviewed_by`; a violation is likewise `ERR_SOD_CONFLICT`."

    Design: Corner/rbac/disburse_two_person_rule_blocks_reviewing_admin
    """
    _, coord = create_coordinator()
    rev, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "tp"})
    fund = create_fund("FY26-tp", allocated_cents=500000)
    approved, _ = create_approved_grant(
        client, fund, reviewer, category="FOOD", requested_cents=40000,
        hardship_statement="x",
    )

    res = api.disburse_grant(approved["id"], make_hub_admin_headers(rev["id"]))
    validate_error(res, ApiErrorId.ERR_SOD_CONFLICT, expected_status=409)

    disbursed = validate_success(
        api.disburse_grant(approved["id"], make_hub_admin_headers("admin-9")), 200
    )
    assert disbursed["status"] == "DISBURSED"
