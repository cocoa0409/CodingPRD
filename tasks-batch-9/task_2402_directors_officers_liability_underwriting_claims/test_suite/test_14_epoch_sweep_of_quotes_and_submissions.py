"""The epoch advance: what it reports, and what it moves on the pre-bind side.

Nothing in this system expires on its own, so the sweep is the only place these
transitions happen. It has to be safe on an empty portfolio, it has to bubble a
submission back when its last live offer lapses, and its comparisons against the
clock are inclusive to the instant.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    UNDERWRITER,
    advance_epoch,
    assert_instant_equals,
    assert_money,
    assert_ops_run_counters,
    assert_premium_stack,
    assert_quote,
    file_disclosure_package,
    issue_quote,
    open_submission,
    read_quote,
    read_submission,
    register_insured,
    score_submission_payload,
    set_clock,
    setup_scored_submission,
)


def test_a_sweep_over_an_empty_portfolio_still_advances_the_epoch(api):
    """PRD 2.10: "The logical clock is the system's only source of time. Before any
    operator sets it, it reads exactly `2026-08-01T00:00:00Z` — a fixed startup default
    that never falls back to real wall-clock time." PRD 2.11: the sweep's "response body
    carries `epoch`, the new epoch counter; `current_utc`, the clock reading the sweep
    used; and eight counters — `activated_policy_count`, `expired_policy_count`,
    `delinquent_policy_count`, `lapsed_quote_count`, `expired_submission_count`,
    `reverted_submission_count`, `lapsed_circumstance_report_count` and
    `expired_runoff_count`. The sweep takes no request body." PRD 2.11: "Setting the
    logical clock forward records a new time but changes no record."

    Design: Corner/endpoints/ops_run_on_an_empty_portfolio_reports_zero_of_everything
    """
    first = validate_success(api.advance_epoch(COMPLIANCE), 200)

    assert_instant_equals(first["current_utc"], "2026-08-01T00:00:00Z", "current_utc")
    assert_ops_run_counters(
        first,
        activated_policy_count=0, expired_policy_count=0, delinquent_policy_count=0,
        lapsed_quote_count=0, expired_submission_count=0, reverted_submission_count=0,
        lapsed_circumstance_report_count=0, expired_runoff_count=0,
    )

    moved = validate_success(api.set_clock("2027-01-15T00:00:00Z", COMPLIANCE), 200)
    assert_instant_equals(moved["current_utc"], "2027-01-15T00:00:00Z", "current_utc")

    second = validate_success(api.advance_epoch(COMPLIANCE), 200)
    assert_instant_equals(second["current_utc"], "2027-01-15T00:00:00Z", "current_utc")
    assert_ops_run_counters(
        second,
        activated_policy_count=0, expired_policy_count=0, delinquent_policy_count=0,
        lapsed_quote_count=0, expired_submission_count=0, reverted_submission_count=0,
        lapsed_circumstance_report_count=0, expired_runoff_count=0,
    )
    assert second["epoch"] == first["epoch"] + 1, (
        "the epoch counter advances on a run that changed nothing"
    )


def test_a_submission_falls_back_to_scored_when_its_last_offer_lapses(api):
    """PRD 2.11: the sweep moves "quotes in `OFFERED` whose `quote_valid_until` the
    clock has reached ... to `LAPSED`" and "submissions in `QUOTED` whose every quote
    has become terminal revert to `SCORED`", while "submissions in `DRAFT`, `SCORED` or
    `QUOTED` whose `expires_at` the clock has reached move to `EXPIRED`". PRD 3.3:
    "Issuing a quote moves the submission `SCORED → QUOTED`", and it "snapshots the
    submission's current `risk_band` into `risk_band_at_quote`". PRD 2.4: `version`
    "increases by exactly 1 on every successful write to it".

    Design: Corner/state_machines/submission_reverts_to_scored_when_all_quotes_lapse
    """
    scenario = setup_scored_submission()
    submission_id = scenario["submission"]["id"]
    quote = issue_quote(submission_id, quote_valid_until="2026-08-31T00:00:00Z")

    quoted = read_submission(submission_id)
    assert quoted["status"] == "QUOTED"
    assert quoted["version"] == 3, "one insert, one scoring write, one quote issuance"

    # Past the offer's validity, but well short of the submission's own expires_at.
    set_clock("2026-09-01T00:00:00Z")
    sweep = advance_epoch()

    assert_ops_run_counters(
        sweep,
        lapsed_quote_count=1, reverted_submission_count=1, expired_submission_count=0,
        activated_policy_count=0, delinquent_policy_count=0,
    )

    lapsed = read_quote(quote["id"])
    assert_quote(lapsed)
    assert lapsed["status"] == "LAPSED"
    assert_money(lapsed["net_premium_usd"], 206_910.00, "net_premium_usd")
    assert_money(lapsed["gross_premium_usd"], 236_468.57, "gross_premium_usd")

    reverted = read_submission(submission_id)
    assert reverted["status"] == "SCORED", "the fall-back is to SCORED, not to DRAFT"
    assert reverted["risk_score"] == pytest.approx(85.80, abs=0.01)
    assert reverted["risk_band"] == "ELEVATED"
    assert_instant_equals(reverted["scored_at"], "2026-08-01T00:00:00Z", "scored_at")
    assert reverted["version"] == 4, "the revert is itself a write"

    # SCORED is the state quote issuance requires, so no re-score is needed.
    replacement = issue_quote(submission_id, expected_submission_version=4,
                              quote_valid_until="2026-09-30T00:00:00Z")
    assert replacement["status"] == "OFFERED"
    assert replacement["risk_band_at_quote"] == "ELEVATED"
    assert_money(replacement["net_premium_usd"], 206_910.00, "net_premium_usd")
    assert_money(replacement["gross_premium_usd"], 236_468.57, "gross_premium_usd")
    assert_premium_stack(replacement)
    requoted = read_submission(submission_id)
    assert requoted["status"] == "QUOTED"
    assert requoted["version"] == 5

    again = advance_epoch()
    assert_ops_run_counters(again, lapsed_quote_count=0, reverted_submission_count=0)
    assert read_quote(quote["id"])["status"] == "LAPSED", (
        "the already-terminal child is not swept a second time"
    )
    assert read_submission(submission_id)["version"] == 5, "the second sweep wrote nothing"


def test_a_draft_submission_expires_on_the_run_at_its_expiry_instant(api):
    """PRD 2.11: "submissions in `DRAFT`, `SCORED` or `QUOTED` whose `expires_at` the
    clock has reached move to `EXPIRED`", and "Each comparison against the clock is
    inclusive: a deadline is reached when the clock reading is greater than or equal to
    it." PRD 2.11: "No deadline in this system fires by itself." PRD 3.2: "A submission
    in any other state — notably `QUOTED`, `BOUND` or `EXPIRED` — is refused with
    `ERR_INVALID_SUBMISSION_STATE`."

    Design: Corner/cross_cutting_complexity_layers/draft_submission_expires_on_the_ops_run_at_its_expiry_instant
    """
    insured = register_insured()
    file_disclosure_package(insured["id"])
    submission = open_submission(
        insured["id"], requested_period_start="2026-11-01T00:00:00Z",
        requested_period_end="2027-11-01T00:00:00Z",
    )
    submission_id = submission["id"]
    assert_instant_equals(submission["expires_at"], "2026-10-30T00:00:00Z", "expires_at")

    set_clock("2026-10-29T00:00:00Z")
    early = advance_epoch()
    assert_ops_run_counters(early, expired_submission_count=0, lapsed_quote_count=0)
    still_draft = read_submission(submission_id)
    assert still_draft["status"] == "DRAFT", "one day short of expires_at"
    assert still_draft["version"] == 1

    set_clock("2026-10-30T00:00:00Z")
    on_the_instant = advance_epoch()
    assert_ops_run_counters(on_the_instant, expired_submission_count=1)

    validate_error(
        api.score_submission(submission_id, score_submission_payload("INDICATIVE"),
                             UNDERWRITER),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )

    expired = read_submission(submission_id)
    assert expired["status"] == "EXPIRED"
    assert expired["risk_score"] is None
    assert expired["risk_band"] is None
    assert expired["version"] == 2, (
        "the insert plus the single sweep write; the refused score bumped nothing"
    )
