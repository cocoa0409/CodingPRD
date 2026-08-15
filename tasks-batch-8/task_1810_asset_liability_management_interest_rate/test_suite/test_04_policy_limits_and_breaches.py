"""Policy limits, breach evaluation boundaries, the breach lifecycle, and the
clock-driven escalation sweep (PRD §2.4, §3.5)."""
import pytest

from test_helpers import (
    CH1,
    MV1,
    ApiErrorId,
    acknowledge_breach,
    assert_limit_breach,
    close_breach,
    create_book,
    create_policy_limit,
    create_run,
    get_breach,
    get_success_data,
    list_breaches,
    plan_breach_remediation,
    set_clock,
    setup_book1_runnable,
    validate_error,
    validate_success,
)


class TestLimitScope:
    def test_limit_scope_conflict_rejected(self, api):
        """PRD §3.5: "At most one `ACTIVE` limit may exist for a given book,
        metric, and identical `applies_to_kinds` scope; a conflicting creation
        is rejected with `ERR_LIMIT_SCOPE_CONFLICT` (HTTP 409)."

        Design: Corner/validations/limit_scope_conflict_rejected
        """
        book = create_book()
        create_policy_limit(book["id"], "NII_DELTA_PCT", 5.0)
        resp = api.create_policy_limit(
            book["id"],
            {"metric": "NII_DELTA_PCT", "applies_to_kinds": ["ALL"],
             "threshold_pct": 6.0},
            CH1)
        validate_error(resp, ApiErrorId.ERR_LIMIT_SCOPE_CONFLICT)
        # A different metric over the same scope is a different scope.
        other = validate_success(api.create_policy_limit(
            book["id"],
            {"metric": "EVE_DELTA_PCT", "applies_to_kinds": ["ALL"],
             "threshold_pct": 12.0},
            CH1), 201)
        assert other["status"] == "ACTIVE"


class TestBreachThresholdBoundary:
    def test_nii_delta_exactly_at_threshold_not_breach(self, api):
        """PRD §3.5: "For each `ACTIVE` limit of the book whose
        `applies_to_kinds` is `ALL` or contains the run's scenario kind, an
        `NII_DELTA_PCT` limit is breached when the run's `nii_delta_pct` is
        strictly less than the negative of `threshold_pct`, and an
        `EVE_DELTA_PCT` limit is breached when the run's `eve_delta_pct` is
        strictly less than the negative of `threshold_pct`." PRD §3.5: "A
        delta exactly equal to the negative threshold is not a breach, and the
        comparison uses the rounded two-decimal delta values stored on the
        run."

        Design: Difficulty/boundary_precision_check/nii_delta_exactly_at_threshold_not_breach
        """
        ctx = setup_book1_runnable()
        create_policy_limit(ctx["book"]["id"], "NII_DELTA_PCT", 4.57)
        create_policy_limit(ctx["book"]["id"], "EVE_DELTA_PCT", 12.0)
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        assert run["nii_delta_pct"] == pytest.approx(-4.57)
        assert run["breach_summary"] == "EVE", (
            "-4.57 is exactly the negative of the 4.57 NII threshold: only "
            "the EVE limit (-25.33 < -12.0) breaches")

    def test_nii_delta_one_tick_past_threshold_breaches(self, api):
        """PRD §3.5: "an `NII_DELTA_PCT` limit is breached when the run's
        `nii_delta_pct` is strictly less than the negative of `threshold_pct`"
        — lowering the threshold to 4.56 makes the same -4.57 run strictly
        past it. PRD §3.5: "The `ALCOChair` may patch a limit's
        `threshold_pct` and/or `status`".

        Design: Difficulty/boundary_precision_check/nii_delta_exactly_at_threshold_not_breach
        """
        ctx = setup_book1_runnable()
        lim = create_policy_limit(ctx["book"]["id"], "NII_DELTA_PCT", 4.57)
        create_policy_limit(ctx["book"]["id"], "EVE_DELTA_PCT", 12.0)
        create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                   ctx["ds"]["id"], ctx["bs"]["id"])
        get_success_data(api.patch_policy_limit(
            lim["id"], {"threshold_pct": 4.56}, CH1))
        run2 = create_run(ctx["book"]["id"], ctx["sc"]["id"],
                          ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"])
        assert run2["breach_summary"] == "BOTH", (
            "with the threshold at 4.56 the same -4.57 NII delta breaches")


class TestSuspendedLimit:
    def test_suspended_limit_excluded_from_breach_evaluation(self, api):
        """PRD §3.5: "a `SUSPENDED` limit is excluded from subsequent run
        breach evaluation". PRD §3.5: "For each `ACTIVE` limit of the book
        whose `applies_to_kinds` is `ALL` or contains the run's scenario kind,
        an `NII_DELTA_PCT` limit is breached when the run's `nii_delta_pct` is
        strictly less than the negative of `threshold_pct`".

        Design: Corner/calculations/suspended_limit_excluded_from_breach_evaluation
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        lim = create_policy_limit(ctx["book"]["id"], "NII_DELTA_PCT", 1.0)
        get_success_data(api.patch_policy_limit(
            lim["id"], {"status": "SUSPENDED"}, CH1))
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        assert run["breach_summary"] == "NONE", (
            "the only limit is SUSPENDED, so the -0.80 delta breaches nothing")
        assert list_breaches({"book_id": ctx["book"]["id"]}) == []


class TestBreachLifecycleFork:
    def _setup_two_breaches(self, api):
        """Book1 + NII limit 1.0 + EVE limit 12.0 + one +200 STATIC run: the
        run's -4.57 NII delta and -25.33 EVE delta open one breach each."""
        ctx = setup_book1_runnable()
        create_policy_limit(ctx["book"]["id"], "NII_DELTA_PCT", 1.0)
        create_policy_limit(ctx["book"]["id"], "EVE_DELTA_PCT", 12.0)
        create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                   ctx["ds"]["id"], ctx["bs"]["id"])
        nii = list_breaches({"book_id": ctx["book"]["id"],
                             "metric": "NII_DELTA_PCT"})
        eve = list_breaches({"book_id": ctx["book"]["id"],
                             "metric": "EVE_DELTA_PCT"})
        assert len(nii) == 1 and len(eve) == 1
        return ctx, nii[0], eve[0]

    def test_breach_remediation_branch_walks_to_closed(self, api):
        """PRD §3.5: "Acknowledgement moves a breach `OPEN → ACKNOWLEDGED`; a
        remediation plan moves it `ACKNOWLEDGED → REMEDIATION_PLANNED` and
        requires a non-empty `remediation_note` together with a `due_date`
        timestamp, otherwise the request is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.5: "Closure moves a breach
        to its terminal `CLOSED` status from either `ACKNOWLEDGED` or
        `REMEDIATION_PLANNED` and requires a non-empty `resolution_note`,
        again otherwise `ERR_INVALID_REQUEST`."

        Design: Difficulty/non_linear_state_machine/limit_breach_fork_escalation_and_remediation
        """
        _, nii, _ = self._setup_two_breaches(api)
        acked = acknowledge_breach(nii["id"])
        assert acked["status"] == "ACKNOWLEDGED"
        planned = plan_breach_remediation(
            nii["id"], "Add receive-fixed swap", "2026-09-15T00:00:00Z")
        assert planned["status"] == "REMEDIATION_PLANNED"
        assert planned["remediation_note"] == "Add receive-fixed swap"
        closed = close_breach(nii["id"], "Hedge executed")
        assert_limit_breach(closed)
        assert closed["status"] == "CLOSED"
        # The sibling EVE breach is still OPEN; advancing the clock six days
        # past creation sweeps it without touching the CLOSED one.
        set_clock("2026-08-07T00:00:00Z", CH1)
        assert get_breach(nii["id"])["status"] == "CLOSED"

    def test_breach_left_open_escalates_after_five_days(self, api):
        """PRD §3.5: "Whenever the clock is set, the escalation sweep runs: a
        breach still `OPEN` once the clock reaches or passes the instant five
        days after its `created_at` moves `OPEN → ESCALATED`". PRD §2.4: "At
        server startup the logical clock reads exactly 2026-08-01T00:00:00Z".

        Design: Difficulty/non_linear_state_machine/limit_breach_fork_escalation_and_remediation
        """
        _, nii, eve = self._setup_two_breaches(api)
        # Work the NII branch to CLOSED; leave the EVE breach OPEN.
        acknowledge_breach(nii["id"])
        plan_breach_remediation(nii["id"], "Add receive-fixed swap",
                                "2026-09-15T00:00:00Z")
        close_breach(nii["id"], "Hedge executed")
        set_clock("2026-08-07T00:00:00Z", CH1)
        escalated = get_breach(eve["id"])
        assert escalated["status"] == "ESCALATED", (
            "created 2026-08-01, still OPEN: at 2026-08-07 the 5-day "
            "acknowledgement deadline has passed")


class TestBreachRoleEnforcement:
    def test_validator_cannot_close_breach_forbidden(self, api):
        """PRD §3.5: "The breach lifecycle is worked by the `ALCOChair`."
        PRD §2.1: "a caller whose role is not permitted for the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/validator_cannot_close_breach_forbidden
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        # Threshold 0.5: the +200 run's -0.80 NII delta on the two-position
        # book opens exactly one breach.
        create_policy_limit(ctx["book"]["id"], "NII_DELTA_PCT", 0.5)
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        assert run["breach_summary"] == "NII"
        breaches = list_breaches({"book_id": ctx["book"]["id"]}, headers=MV1)
        assert len(breaches) == 1
        resp = api.close_breach(
            breaches[0]["id"],
            {"resolution_note": "validator cannot do this"}, MV1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_breach(breaches[0]["id"])["status"] == "OPEN"
