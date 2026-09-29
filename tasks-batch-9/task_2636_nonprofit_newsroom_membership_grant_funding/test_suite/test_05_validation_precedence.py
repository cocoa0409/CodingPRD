"""Two requests that offend two rules at once, and answer only the higher one.

In both cases the lower-ranked rule is shown to be present rather than absent:
the same request reports it once the higher-ranked obstacle is removed.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    fiscal_period_action,
    open_fiscal_period,
    read_fiscal_period,
    read_proposal,
    read_sustainability,
    record_board_override,
    rule_on_funder,
    set_clock,
    setup_cleared_funder,
    setup_cleared_proposal,
    validate_error,
)
from test_helpers.fixtures import DO_HEADERS, FC_HEADERS

_OVERRIDE_JUSTIFICATION = (
    "Board accepts closing FY2027 below the one-month reserve floor; "
    "recovery plan adopted."
)


def _setup_reserve_thin_period():
    """An OPEN period holding 150000 against a 200000 monthly expense base, so
    the reserve floor is breached from the moment it opens."""
    return open_fiscal_period(
        monthly_expense_base_cents=200000, reserve_balance_cents=150000
    )


class TestCloseOnOpenPeriodReportsInvalidStateFirst:
    """The declared-transition guard outranks the reserve floor."""

    def test_the_thin_reserve_puts_the_period_at_critical_from_the_start(self):
        """150000 against a 200000 base is a ratio of 7500 and a CRITICAL
        posture, which is exactly the reserve-floor condition.

        PRD: "a period may not close while `reserve_months_ratio_bps` is below
        10000 - that is, while the reserve holds less than one full month of the
        expense base, which is precisely the condition that puts
        `sustainability_posture` at `CRITICAL` - unless `board_override_active`
        is true."

        Design: Difficulty/priority_pair_validation_conflict/pp_close_on_open_period_reports_invalid_state_before_reserve_floor_breach
        """
        period = _setup_reserve_thin_period()

        picture = read_sustainability(period["id"])
        assert picture["reserve_months_ratio_bps"] == 7500
        assert picture["sustainability_posture"] == "CRITICAL"
        assert picture["restricted_release_cap_pct_bps"] == 0
        assert picture["operating_reserve_target_cents"] == 600000

    def test_closing_an_open_period_reports_the_state_error_not_the_floor(self):
        """CLOSE is not a declared exit from OPEN, and that ranks above the
        fiscal complaint the same request also earns.

        PRD: "Both of these sit *below* the declared-transition guard, so asking
        to close a period that is still `OPEN` reports `ERR_INVALID_STATE`
        rather than either fiscal complaint."

        Design: Difficulty/priority_pair_validation_conflict/pp_close_on_open_period_reports_invalid_state_before_reserve_floor_breach
        """
        period = _setup_reserve_thin_period()

        response = api_client.fiscal_period_status_action(
            period["id"], {"action": "CLOSE"}, FC_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        unchanged = read_fiscal_period(period["id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["board_override_active"] is False

    def test_the_identical_close_reports_the_floor_once_the_period_is_locked(self):
        """With the transition legal the masked rule surfaces on an untouched
        reserve, proving it was evaluated all along.

        PRD: "That failure is `ERR_RESERVE_FLOOR_BREACH`."

        Design: Difficulty/priority_pair_validation_conflict/pp_close_on_open_period_reports_invalid_state_before_reserve_floor_breach
        """
        period = _setup_reserve_thin_period()

        locked = fiscal_period_action(period["id"], "LOCK")
        assert locked["status"] == "REVIEW_LOCKED"
        assert locked["locked_at"].startswith("2026-08-01T00:00:00")

        response = api_client.fiscal_period_status_action(
            period["id"], {"action": "CLOSE"}, FC_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_RESERVE_FLOOR_BREACH)

        assert read_fiscal_period(period["id"])["status"] == "REVIEW_LOCKED"

    def test_a_board_override_is_what_finally_lets_the_thin_period_close(self):
        """The documented override is warranted by the CRITICAL posture and is
        the only thing that changes between the refused and the accepted CLOSE.

        PRD: "Once on file, the override is what lets a severely concentrated
        period lock and a reserve-thin period close."

        Design: Difficulty/priority_pair_validation_conflict/pp_close_on_open_period_reports_invalid_state_before_reserve_floor_breach
        """
        period = _setup_reserve_thin_period()
        fiscal_period_action(period["id"], "LOCK")

        overridden = record_board_override(period["id"], _OVERRIDE_JUSTIFICATION)
        assert overridden["board_override_active"] is True
        assert overridden["board_override_justification"] == _OVERRIDE_JUSTIFICATION
        assert overridden["status"] == "REVIEW_LOCKED"

        closed = fiscal_period_action(period["id"], "CLOSE")
        assert closed["status"] == "CLOSED"
        assert closed["reserve_months_ratio_bps"] == 7500


def _setup_cleared_proposal_on_a_restricted_funder():
    """A CLEARED unrestricted proposal whose funder has just been restricted, so
    `restricted_at` reads the epoch instant."""
    period = open_fiscal_period()
    funder = setup_cleared_funder(legal_name="Ashgrove Foundation")
    proposal = setup_cleared_proposal(
        funder["id"],
        period["id"],
        title="General operating support",
        requested_amount_cents=250000,
        restriction_type="UNRESTRICTED",
        reporting_cadence="NONE",
        award_probability_bps=6000,
    )
    restricted = rule_on_funder(
        funder["id"],
        "RESTRICT",
        "SELF_ATTESTED",
        reason="Program officer publicly demanded a retraction.",
    )
    return {"period": period, "funder": restricted, "proposal": proposal}


def _submit(proposal_id):
    return api_client.grant_proposal_pipeline_action(
        proposal_id, {"action": "SUBMIT"}, DO_HEADERS
    )


class TestRestrictedFunderOutranksTheCoolingOffWindow:
    """Both rules are offended by one SUBMIT; only the restriction is reported."""

    def test_the_restriction_stamps_the_cooling_off_anchor(self):
        """RESTRICT lands the funder in RESTRICTED and stamps `restricted_at`
        with the clock, leaving the proposal in CLEARED.

        PRD: "`RESTRICT` is legal from `PROSPECT` and from `CLEARED`, landing the
        funder in `RESTRICTED`."

        Design: Difficulty/priority_pair_validation_conflict/pp_restricted_funder_outranks_cooling_off_on_proposal_submit
        """
        ctx = _setup_cleared_proposal_on_a_restricted_funder()

        assert ctx["funder"]["status"] == "RESTRICTED"
        assert ctx["funder"]["restricted_at"].startswith("2026-08-01T00:00:00")
        assert ctx["funder"]["independence_risk_score"] == 10
        assert read_proposal(ctx["proposal"]["id"])["status"] == "CLEARED"

    def test_submitting_for_a_restricted_funder_reports_the_restriction(self):
        """The clock is 30 days short of the cooling-off expiry as well, but the
        restriction ranks strictly above it.

        PRD: "Either way the refusal is `ERR_FUNDER_COOLING_OFF_VIOLATION` (HTTP
        409), and it is ranked strictly *below* the restricted-funder check, so a
        funder that is still restricted and also inside its cooling-off window
        reports `ERR_FUNDER_RESTRICTED`."

        Design: Difficulty/priority_pair_validation_conflict/pp_restricted_funder_outranks_cooling_off_on_proposal_submit
        """
        ctx = _setup_cleared_proposal_on_a_restricted_funder()

        validate_error(_submit(ctx["proposal"]["id"]), ApiErrorId.ERR_FUNDER_RESTRICTED)

        assert read_proposal(ctx["proposal"]["id"])["status"] == "CLEARED"

    def test_rehabilitation_leaves_the_cooling_off_clock_running(self):
        """Clearing the funder again does not reset `restricted_at`, so nine days
        later the same SUBMIT now reports the cooling-off violation.

        PRD: "at least 30 days must have elapsed since the funder's
        `restricted_at` instant before any proposal for that funder may be
        submitted, and because `restricted_at` survives rehabilitation, a funder
        cleared back to `CLEARED` two days after being restricted is still barred
        for another 28."

        Design: Difficulty/priority_pair_validation_conflict/pp_restricted_funder_outranks_cooling_off_on_proposal_submit
        """
        ctx = _setup_cleared_proposal_on_a_restricted_funder()

        rehabilitated = rule_on_funder(
            ctx["funder"]["id"],
            "CLEAR",
            "SELF_ATTESTED",
            reason="Funder adopted a written non-interference policy.",
        )
        assert rehabilitated["status"] == "CLEARED"
        assert rehabilitated["restricted_at"].startswith("2026-08-01T00:00:00")

        set_clock("2026-08-10T00:00:00Z")
        validate_error(
            _submit(ctx["proposal"]["id"]),
            ApiErrorId.ERR_FUNDER_COOLING_OFF_VIOLATION,
        )
        assert read_proposal(ctx["proposal"]["id"])["status"] == "CLEARED"

    def test_the_submit_succeeds_exactly_thirty_days_after_the_restriction(self):
        """At 2026-08-31 the 30 days have elapsed, the proposal reaches SUBMITTED
        and starts counting in the probability-weighted projection.

        PRD: "`SUBMIT` takes a `CLEARED` proposal to `SUBMITTED` and is the point
        at which the proposal starts counting toward the pipeline revenue
        projection weighted by its `award_probability_bps`."

        Design: Difficulty/priority_pair_validation_conflict/pp_restricted_funder_outranks_cooling_off_on_proposal_submit
        """
        ctx = _setup_cleared_proposal_on_a_restricted_funder()
        rule_on_funder(ctx["funder"]["id"], "CLEAR", "SELF_ATTESTED")

        set_clock("2026-08-31T00:00:00Z")
        submitted = _submit(ctx["proposal"]["id"])
        assert submitted.status_code == 200
        assert read_proposal(ctx["proposal"]["id"])["status"] == "SUBMITTED"

        projection = read_sustainability(ctx["period"]["id"], basis="PIPELINE")
        assert projection["recognized_revenue_cents"] == 150000
        assert projection["grants_share_bps"] == 10000
