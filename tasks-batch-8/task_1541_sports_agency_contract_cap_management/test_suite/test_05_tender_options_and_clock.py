"""Tender/option exercise windows and scheduled auto-expiry under the clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_certified_agent,
    create_contract,
    create_draft_proposal,
    create_tender_option,
    make_agent_headers,
    setup_negotiation_env,
    setup_signed_contract,
    sign_contract_via_proposal,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


class TestExerciseWindowBoundaries:
    def test_exercise_at_exactly_window_open_succeeds(self, api):
        """PRD §3.7: "Exercising is the primary agent's act: the acting agent
        must be `CERTIFIED` and must equal the client's `primary_agent_id`, the
        contract must stand `SIGNED`, and the logical clock must read on or
        after `window_open_at` and strictly before `window_close_at` — outside
        that window the attempt is rejected with `ERR_WINDOW_CLOSED`. A
        successful exercise moves the record from `PENDING` to `EXERCISED`,
        stamps `exercised_at` with the current UTC instant, and locks the
        contract's `base_salary_cents` for the option year at the tender
        amount."

        Half-open interval [open, close): the inclusive lower bound admits
        exercise at exactly window_open_at.

        Design: Difficulty/resource_temporal_overlap/tender_option_window_half_open_interval
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        tender = create_tender_option(
            env, env["contract"]["id"], kind="TEAM_OPTION",
            window_open_at="2026-08-10T00:00:00Z",
            window_close_at="2026-08-20T00:00:00Z")
        validate_success(api.set_clock("2026-08-10T00:00:00Z", LEAGUE))
        exercised = validate_success(api.exercise_tender_option(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            tender["id"], make_agent_headers(env["agent"]["id"])))
        assert exercised["status"] == "EXERCISED", \
            "the half-open lower bound is inclusive"
        assert exercised["exercised_at"].startswith("2026-08-10T00:00:00"), \
            "exercised_at is stamped with the current UTC instant"

    def test_exercise_at_exactly_window_close_rejected(self, api):
        """PRD §3.7: "the logical clock must read on or after `window_open_at`
        and strictly before `window_close_at` — outside that window the attempt
        is rejected with `ERR_WINDOW_CLOSED`."
        PRD §3.7: "Should the clock reach `window_close_at` with the option
        unexercised, the system itself moves the record from `PENDING` to
        `EXPIRED`."

        Half-open interval [open, close): at exactly window_close_at the
        exercise is out of window and must be rejected. Because the automatic
        expiry also fires at that instant, the rejection surfaces either as the
        temporal failure (ERR_WINDOW_CLOSED) or as the state failure
        (ERR_INVALID_STATE on the already-EXPIRED record).

        Design: Difficulty/resource_temporal_overlap/tender_option_window_half_open_interval
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        tender = create_tender_option(
            env, env["contract"]["id"], kind="TEAM_OPTION",
            window_open_at="2026-08-10T00:00:00Z",
            window_close_at="2026-08-20T00:00:00Z")
        validate_success(api.set_clock("2026-08-20T00:00:00Z", LEAGUE))
        resp = api.exercise_tender_option(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            tender["id"], make_agent_headers(env["agent"]["id"]))
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_WINDOW_CLOSED, ApiErrorId.ERR_INVALID_STATE])
        assert actual in ("ERR_WINDOW_CLOSED", "ERR_INVALID_STATE")
        after = validate_success(api.get_tender_option(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            tender["id"], LEAGUE))
        assert after["status"] in ("PENDING", "EXPIRED"), "never EXERCISED out of window"


class TestExerciseValidationPriority:
    def test_intruder_agent_and_closed_window_yields_ownership_violation(self, api):
        """PRD §2.7: "Beyond path resolution, every request passes a fixed
        validation pipeline, evaluated in order so that an earlier failure masks
        all later checks. ... Sixth, ownership: the acting agent must own the
        resource being acted upon, else `ERR_OWNERSHIP_VIOLATION` (422).
        Seventh, temporal windows: an option exercise must fall inside its
        declared window and an endorsement's date range must be coherent, else
        `ERR_WINDOW_CLOSED` (422)."
        PRD §3.7: "Exercising is the primary agent's act: the acting agent must
        be `CERTIFIED` and must equal the client's `primary_agent_id`, the
        contract must stand `SIGNED`, and the logical clock must read on or
        after `window_open_at` and strictly before `window_close_at` — outside
        that window the attempt is rejected with `ERR_WINDOW_CLOSED`."

        An intruder agent (certified, but not the client's primary) exercising a
        window that closed before the boot clock trips the ownership check
        first: ERR_OWNERSHIP_VIOLATION masks ERR_WINDOW_CLOSED. Because the
        automatic expiry may also have moved the record to EXPIRED before the
        exercise is evaluated, the rejection may instead surface as the state
        failure on the already-expired record (ERR_INVALID_STATE, step 4,
        outranks ownership at step 6).

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_tender_exercise
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        intruder = add_certified_agent(env)
        tender = create_tender_option(
            env, env["contract"]["id"], kind="PLAYER_OPTION",
            window_open_at="2026-07-01T00:00:00Z",
            window_close_at="2026-07-15T00:00:00Z")
        # Boot clock is 2026-08-01: the window is already closed.
        resp = api.exercise_tender_option(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            tender["id"], make_agent_headers(intruder["id"]))
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_OWNERSHIP_VIOLATION, ApiErrorId.ERR_INVALID_STATE])
        assert actual in ("ERR_OWNERSHIP_VIOLATION", "ERR_INVALID_STATE")

    def test_primary_agent_and_closed_window_yields_window_error(self, api):
        """PRD §2.7: "Seventh, temporal windows: an option exercise must fall
        inside its declared window and an endorsement's date range must be
        coherent, else `ERR_WINDOW_CLOSED` (422)."
        PRD §3.7: "the logical clock must read on or after `window_open_at` and
        strictly before `window_close_at` — outside that window the attempt is
        rejected with `ERR_WINDOW_CLOSED`."

        The primary (owning) agent passes certification and ownership, so only
        the temporal check can fire on the already-closed window. Because the
        automatic expiry may also have moved the record to EXPIRED, the
        rejection surfaces either as ERR_WINDOW_CLOSED or as the state failure.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_tender_exercise
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        tender = create_tender_option(
            env, env["contract"]["id"], kind="PLAYER_OPTION",
            window_open_at="2026-07-01T00:00:00Z",
            window_close_at="2026-07-15T00:00:00Z")
        resp = api.exercise_tender_option(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            tender["id"], make_agent_headers(env["agent"]["id"]))
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_WINDOW_CLOSED, ApiErrorId.ERR_INVALID_STATE])
        assert actual in ("ERR_WINDOW_CLOSED", "ERR_INVALID_STATE")


class TestScheduledAutoExpiry:
    def test_tender_option_auto_expires_after_window_close(self, api):
        """PRD §3.7: "Should the clock reach `window_close_at` with the option
        unexercised, the system itself moves the record from `PENDING` to
        `EXPIRED`."
        PRD §2.5: "Automatic state changes — an endorsement deal completing when
        its `end_date` is reached, a tender option expiring once its
        `window_close_at` has passed — are evaluated against this logical clock,
        and so are all exercise-window checks."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_tender_option_auto_expire
        """
        env = setup_negotiation_env(agency_name="SchA")
        contract = create_contract(env, base_salary_cents=5_000_000,
                                   guaranteed_cents=5_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        tender = create_tender_option(
            env, contract["id"], kind="QUALIFYING_OFFER",
            window_open_at="2026-08-05T00:00:00Z",
            window_close_at="2026-08-10T00:00:00Z")
        assert tender["status"] == "PENDING"

        validate_success(api.set_clock("2026-08-15T00:00:00Z", LEAGUE))
        after = validate_success(api.get_tender_option(
            env["agency"]["id"], env["client"]["id"], contract["id"], tender["id"],
            LEAGUE))
        assert after["status"] == "EXPIRED", \
            "the system moves the unexercised option to EXPIRED once the clock passes window_close_at"
