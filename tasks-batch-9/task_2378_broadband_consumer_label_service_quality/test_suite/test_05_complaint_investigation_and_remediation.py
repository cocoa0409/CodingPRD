"""Complaint investigation, remediation credits and their compensation (PRD §3.8).

The four families exercised here are the cyclic shape of the complaint machine
(the `INFO_REQUESTED` loop against the bounded reopen loop), the four hops that
upholding a complaint propagates through the account ledger, the whole-day
truncation boundary of the reopen window, and the conserved account ledger that
voiding a credit must restore without drift (PRD §2.12).
"""

from datetime import datetime

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId
from test_helpers.assertions import assert_account_ledger, assert_posture
from test_helpers.constants import (
    MAX_REOPENS,
    REFERENCE_NOW,
    REMEDIATION_AUDIT_THRESHOLD,
)
from test_helpers.factories import (
    build_reopen_payload,
    build_request_info_payload,
    build_uphold_payload,
    build_void_credit_payload,
    build_withdraw_complaint_payload,
)
from test_helpers.fixtures import (
    create_dismissed_complaint,
    create_investigated_complaint,
    create_upheld_complaint,
    dismiss_complaint,
    first_credit_of,
    read_complaint,
    read_service_plan,
    read_subscriber_account,
    uphold_complaint,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLAINT_ANALYST_USER_ID,
    make_operator_headers,
    make_subscriber_headers,
)
from test_helpers.types import (
    ComplaintResolution,
    ComplaintSeverity,
    ComplaintState,
    CreditBasis,
    LabelPosture,
    PricingPhase,
    RemediationCreditStatus,
    UserRole,
)

# ---------------------------------------------------------------------------
# Pre-computed figures of the reference world (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------

#: The account enrols on the day its plan's label takes effect, so its
#: `pricing_phase` is `INTRO` and every credit base is the label's pinned
#: introductory net monthly charge.
INTRO_NET_MONTHLY_CENTS = 3766

#: A `SPEED_SHORTFALL` of 120 Mbps against the label's pinned 240.00 Mbps.
SEVERE_SHORTFALL_MEASURED_DOWNLOAD = 120
SEVERE_SHORTFALL_RATIO = 0.5000
#: 3766 * 0.5 * 15/30 == 941.5, rounded half up to a whole cent.
SEVERE_PRORATA_CREDIT_CENTS = 942

#: A `SPEED_SHORTFALL` of 180 Mbps against the same pinned 240.00 Mbps.
MODERATE_SHORTFALL_MEASURED_DOWNLOAD = 180
MODERATE_SHORTFALL_RATIO = 0.2500
#: 3766 * 0.25 * 15/30 == 470.75, which rounds to 471 and is then lifted to the
#: 500-cent floor.
MODERATE_PRORATA_CREDIT_CENTS = 500

BALANCE_AFTER_BOTH_CREDITS_CENTS = SEVERE_PRORATA_CREDIT_CENTS + MODERATE_PRORATA_CREDIT_CENTS
UPHELD_COMPLAINT_COUNT_AFTER_BOTH = 2

AFFECTED_DAYS = 15

SEVERE_OBSERVED_DATE = "2026-09-01T12:00:00Z"
MODERATE_OBSERVED_DATE = "2026-09-02T12:00:00Z"
THIRD_OBSERVED_DATE = "2026-09-03T12:00:00Z"

# ---------------------------------------------------------------------------
# Reopen-window boundary instants (PRD §3.8), measured from a dismissal at the
# reference instant 2026-09-01T00:00:00Z.
# ---------------------------------------------------------------------------

#: 2,592,000 elapsed seconds -> floor division by 86,400 yields exactly 30.
THIRTY_WHOLE_DAYS_LATER = "2026-10-01T00:00:00Z"
#: 2,678,399 elapsed seconds -> floor division by 86,400 still yields 30.
THIRTY_DAYS_AND_ALMOST_ONE_MORE = "2026-10-01T23:59:59Z"
#: 2,678,400 elapsed seconds -> floor division by 86,400 yields 31.
THIRTY_ONE_WHOLE_DAYS_LATER = "2026-10-02T00:00:00Z"

# ---------------------------------------------------------------------------
# The voiding officer: a third compliance identity, so that the recorded
# `voided_by_user_id` is unmistakably the acting principal.
# ---------------------------------------------------------------------------

VOIDING_OFFICER_USER_ID = "co-3"
VOIDING_OFFICER_HEADERS = make_operator_headers(
    VOIDING_OFFICER_USER_ID, UserRole.COMPLIANCE_OFFICER.value
)
FIRST_VOID_REASON = "Credit applied twice by the billing feed"
SECOND_VOID_REASON = "Second credit reversed for the same reason"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse a server ISO-8601 UTC instant, whose fractional digits the PRD
    fixes at three, into a comparable value."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected_iso: str, field: str) -> None:
    assert actual is not None, f"{field} should have been set"
    assert _instant(actual) == _instant(expected_iso), (
        f"{field}: expected {expected_iso}, got {actual}"
    )


def _two_upheld_complaints_with_credits(env):
    """Two upheld complaints on the reference account: a severe one crediting
    942 cents and a moderate one crediting the 500-cent floor."""
    severe = create_upheld_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=SEVERE_OBSERVED_DATE,
        credit_basis=CreditBasis.PRORATA_DAYS.value,
        affected_days=AFFECTED_DAYS,
        measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        narrative="Evening speeds roughly half the label figure",
    )
    moderate = create_upheld_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=MODERATE_OBSERVED_DATE,
        credit_basis=CreditBasis.PRORATA_DAYS.value,
        affected_days=AFFECTED_DAYS,
        measured_download_mbps=MODERATE_SHORTFALL_MEASURED_DOWNLOAD,
        narrative="Speeds a quarter below the label figure",
    )
    return severe, moderate, first_credit_of(severe["id"]), first_credit_of(moderate["id"])


# ---------------------------------------------------------------------------
# The cyclic complaint machine: an unbounded information loop and a bounded
# reopen loop.
# ---------------------------------------------------------------------------


class TestComplaintCyclesAndReopenBound:
    def test_information_loop_counts_every_return_without_bound(
        self, api, reference_environment
    ):
        """Pausing for consumer information and resuming counts a cycle each time.

        PRD: "Resuming afterwards moves it `INFO_REQUESTED → UNDER_INVESTIGATION`,
        increments `investigation_cycles` by one, and recomputes the assessment
        against the same pinned label figures — the loop between these two states
        may be walked any number of times, and each return through it is counted."

        Design: Difficulty/non_linear_state_machine/complaint_info_request_cycle_and_reopen_bound
        """
        env = reference_environment
        complaint = create_investigated_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="Evening speeds far below the label figure",
        )
        complaint_id = complaint["id"]
        assert complaint["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert complaint["investigation_cycles"] == 0

        paused = validate_success(
            api.request_complaint_info(
                complaint_id,
                build_request_info_payload(
                    info_request_note="Send router logs for the affected evenings"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert paused["state"] == ComplaintState.INFO_REQUESTED.value
        assert paused["investigation_cycles"] == 0, (
            "pausing the investigation is not itself a counted return"
        )

        resumed = validate_success(
            api.investigate_complaint(complaint_id, COMPLAINT_ANALYST_HEADERS)
        )
        assert resumed["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert resumed["investigation_cycles"] == 1
        assert resumed["shortfall_ratio"] == pytest.approx(
            SEVERE_SHORTFALL_RATIO, abs=1e-4
        ), "the assessment is recomputed against the same pinned label figures"
        assert resumed["severity"] == ComplaintSeverity.SEVERE.value

        paused_again = validate_success(
            api.request_complaint_info(
                complaint_id,
                build_request_info_payload(
                    info_request_note="Second clarification round"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert paused_again["state"] == ComplaintState.INFO_REQUESTED.value

        resumed_again = validate_success(
            api.investigate_complaint(complaint_id, COMPLAINT_ANALYST_HEADERS)
        )
        assert resumed_again["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert resumed_again["investigation_cycles"] == 2, (
            "the information loop is unbounded and every return is counted"
        )
        assert resumed_again["shortfall_ratio"] == pytest.approx(
            SEVERE_SHORTFALL_RATIO, abs=1e-4
        )
        assert resumed_again["severity"] == ComplaintSeverity.SEVERE.value

    def test_third_reopen_is_refused_once_the_count_reaches_the_bound(
        self, api, reference_environment
    ):
        """Two reopens are admissible; the third is refused and mutates nothing.

        PRD: "Two admissibility rules apply: the whole number of days between
        `resolved_at` and the logical clock — the elapsed seconds divided by
        86,400, rounded down — must be no more than thirty, an inclusive
        boundary; and `reopened_count` must still be below two. A violation of
        either answers `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Difficulty/non_linear_state_machine/complaint_info_request_cycle_and_reopen_bound
        """
        env = reference_environment
        complaint = create_dismissed_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        )
        complaint_id = complaint["id"]
        assert complaint["state"] == ComplaintState.DISMISSED.value
        assert complaint["reopened_count"] == 0

        first = validate_success(
            api.reopen_complaint(
                complaint_id,
                build_reopen_payload(reopen_reason="Subscriber supplied router logs"),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert first["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert first["reopened_count"] == 1
        assert first["resolved_at"] is None, "reopening clears resolved_at"
        assert first["resolution"] == ComplaintResolution.NONE.value

        dismiss_complaint(complaint_id, resolution_note="Logs inconclusive")
        second = validate_success(
            api.reopen_complaint(
                complaint_id,
                build_reopen_payload(
                    reopen_reason="Third-party measurement submitted"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert second["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert second["reopened_count"] == MAX_REOPENS

        dismiss_complaint(complaint_id, resolution_note="Still inconclusive")
        refused = api.reopen_complaint(
            complaint_id,
            build_reopen_payload(reopen_reason="Fourth attempt"),
            COMPLAINT_ANALYST_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED.value)

        after = read_complaint(complaint_id)
        assert after["state"] == ComplaintState.DISMISSED.value, (
            "the refused reopen leaves the complaint dismissed"
        )
        assert after["reopened_count"] == MAX_REOPENS, "no partial mutation"

    def test_dismissed_reopens_while_upheld_and_withdrawn_refuse_reopening(
        self, api, reference_environment
    ):
        """`DISMISSED` is the only state a reopen may be taken from.

        PRD: "Reopening from any state other than `DISMISSED` answers
        `ERR_COMPLAINT_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/complaint_info_request_cycle_and_reopen_bound
        """
        env = reference_environment
        dismissed = create_dismissed_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        )
        reopened = validate_success(
            api.reopen_complaint(
                dismissed["id"],
                build_reopen_payload(),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert reopened["state"] == ComplaintState.UNDER_INVESTIGATION.value, (
            "a dismissed complaint is reopenable, so DISMISSED is not terminal"
        )

        upheld = uphold_complaint(dismissed["id"])
        assert upheld["state"] == ComplaintState.UPHELD.value
        refused_after_uphold = api.reopen_complaint(
            dismissed["id"], build_reopen_payload(), COMPLAINT_ANALYST_HEADERS
        )
        validate_error(
            refused_after_uphold, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value
        )

        other = create_investigated_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        )
        withdrawn = validate_success(
            api.withdraw_complaint(
                other["id"],
                build_withdraw_complaint_payload(),
                make_subscriber_headers(env.account_id),
            )
        )
        assert withdrawn["state"] == ComplaintState.WITHDRAWN.value
        refused_after_withdrawal = api.reopen_complaint(
            other["id"], build_reopen_payload(), COMPLAINT_ANALYST_HEADERS
        )
        validate_error(
            refused_after_withdrawal, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value
        )


# ---------------------------------------------------------------------------
# Upholding a complaint: complaint -> credit -> account ledger -> audit flag.
# ---------------------------------------------------------------------------


class TestUpholdCreditAuditCascade:
    def test_severe_uphold_issues_the_prorata_credit_and_moves_the_ledger(
        self, api, reference_environment
    ):
        """The pro-rata raw figure rounds to 942 cents and reaches the account.

        PRD: "Under `PRORATA_DAYS` the raw figure is the base multiplied by the
        complaint's `shortfall_ratio`, multiplied by the lesser of the
        complaint's `affected_days` and thirty days, divided by thirty."

        Design: Difficulty/transitive_cascade/uphold_complaint_four_hop_credit_audit_cascade
        """
        env = reference_environment
        assert env.label["net_monthly_intro_cents"] == INTRO_NET_MONTHLY_CENTS
        assert env.account["pricing_phase"] == PricingPhase.INTRO.value, (
            "the credit base is the label's introductory net monthly charge"
        )

        complaint = create_investigated_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="Evening speeds roughly half the label figure",
        )
        resolved = validate_success(
            api.resolve_complaint(
                complaint["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.PRORATA_DAYS.value,
                    resolution_note="Severe shortfall confirmed",
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )

        # Hop 1: the complaint itself.
        assert resolved["state"] == ComplaintState.UPHELD.value
        assert resolved["resolution"] == ComplaintResolution.UPHELD.value
        _assert_instant(resolved["resolved_at"], REFERENCE_NOW, "resolved_at")
        assert resolved["shortfall_ratio"] == pytest.approx(
            SEVERE_SHORTFALL_RATIO, abs=1e-4
        )
        assert resolved["severity"] == ComplaintSeverity.SEVERE.value
        assert resolved["credit_basis"] == CreditBasis.PRORATA_DAYS.value
        assert resolved["remediation_credit_cents"] == SEVERE_PRORATA_CREDIT_CENTS

        # Hop 2: the remediation credit caused by hop 1.
        rows, _meta = validate_paginated(
            api.list_complaint_remediation_credits(
                complaint["id"], COMPLAINT_ANALYST_HEADERS
            )
        )
        assert len(rows) == 1, "one uphold issues exactly one remediation credit"
        credit = rows[0]
        assert credit["complaint_id"] == complaint["id"]
        assert credit["account_id"] == env.account_id
        assert credit["basis"] == CreditBasis.PRORATA_DAYS.value
        assert credit["amount_cents"] == SEVERE_PRORATA_CREDIT_CENTS
        assert credit["status"] == RemediationCreditStatus.ISSUED.value
        assert credit["issued_by_user_id"] == COMPLAINT_ANALYST_USER_ID
        assert credit["voided_by_user_id"] is None
        assert credit["voided_at"] is None
        assert credit["void_reason"] is None

        # Hops 3 and 4: the recomputed ledger and the flag derived from it.
        account = read_subscriber_account(env.account_id)
        assert_account_ledger(account, SEVERE_PRORATA_CREDIT_CENTS, 1)
        assert account["audit_flag"] is False, (
            f"one credit is below the audit threshold of "
            f"{REMEDIATION_AUDIT_THRESHOLD}"
        )

    def test_moderate_uphold_is_lifted_to_the_floor_and_raises_the_audit_flag(
        self, api, reference_environment
    ):
        """471 cents is raised to the 500-cent floor, and the second credit flags
        the account.

        PRD: "The clamping order is pinned: round the raw figure half up to a
        whole number of cents *first*, then raise it to a floor of 500 cents if
        it is below that, and only then cap it at the base."

        Design: Difficulty/transitive_cascade/uphold_complaint_four_hop_credit_audit_cascade
        """
        env = reference_environment
        assert env.label["net_monthly_intro_cents"] == INTRO_NET_MONTHLY_CENTS
        create_upheld_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            credit_basis=CreditBasis.PRORATA_DAYS.value,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        )

        moderate = create_investigated_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=MODERATE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=MODERATE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="Speeds a quarter below the label figure",
        )
        resolved = validate_success(
            api.resolve_complaint(
                moderate["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.PRORATA_DAYS.value,
                    resolution_note="Moderate shortfall confirmed",
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert resolved["shortfall_ratio"] == pytest.approx(
            MODERATE_SHORTFALL_RATIO, abs=1e-4
        )
        assert resolved["severity"] == ComplaintSeverity.MODERATE.value
        assert resolved["remediation_credit_cents"] == MODERATE_PRORATA_CREDIT_CENTS

        credit = first_credit_of(moderate["id"])
        assert credit["amount_cents"] == MODERATE_PRORATA_CREDIT_CENTS
        assert credit["status"] == RemediationCreditStatus.ISSUED.value

        account = read_subscriber_account(env.account_id)
        assert_account_ledger(
            account, BALANCE_AFTER_BOTH_CREDITS_CENTS, REMEDIATION_AUDIT_THRESHOLD
        )
        assert account["audit_flag"] is True, (
            "the flag turns true at exactly the audit threshold"
        )

    def test_plan_upheld_count_moves_while_the_posture_stays_open(
        self, api, reference_environment
    ):
        """The plan-level counter is bumped by each uphold without freezing yet.

        PRD: "One further consequence follows from hop 1 without being part of
        the declared four-hop chain: the plan the account is subscribed to has
        its `upheld_complaint_count` incremented by one, its disclosure posture
        recomputed — which drops it to `FROZEN` once the count reaches three —
        and its `version` incremented."

        Design: Difficulty/transitive_cascade/uphold_complaint_four_hop_credit_audit_cascade
        """
        env = reference_environment
        assert env.plan["upheld_complaint_count"] == 0
        _two_upheld_complaints_with_credits(env)

        plan = read_service_plan(env.plan_id)
        assert plan["upheld_complaint_count"] == UPHELD_COMPLAINT_COUNT_AFTER_BOTH
        assert_posture(plan, LabelPosture.OPEN.value)

    def test_further_resolution_of_an_upheld_complaint_is_refused(
        self, api, reference_environment
    ):
        """`UPHELD` is terminal, so no second resolution is admissible.

        PRD: "Either resolution requires the complaint to be
        `UNDER_INVESTIGATION`, and otherwise answers
        `ERR_COMPLAINT_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/uphold_complaint_four_hop_credit_audit_cascade
        """
        env = reference_environment
        upheld = create_upheld_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            credit_basis=CreditBasis.PRORATA_DAYS.value,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
        )
        assert upheld["state"] == ComplaintState.UPHELD.value

        refused = api.resolve_complaint(
            upheld["id"],
            build_uphold_payload(
                credit_basis=CreditBasis.PRORATA_DAYS.value,
                resolution_note="Attempt to resolve an already upheld complaint",
            ),
            COMPLAINT_ANALYST_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)

        account = read_subscriber_account(env.account_id)
        assert_account_ledger(account, SEVERE_PRORATA_CREDIT_CENTS, 1)


# ---------------------------------------------------------------------------
# The reopen window is a truncated whole-day count.
# ---------------------------------------------------------------------------


class TestReopenWindowWholeDayBoundary:
    def test_reopen_succeeds_at_exactly_thirty_whole_days(
        self, api, reference_environment
    ):
        """2,592,000 elapsed seconds is 30 whole days, an inclusive boundary.

        PRD: "Two admissibility rules apply: the whole number of days between
        `resolved_at` and the logical clock — the elapsed seconds divided by
        86,400, rounded down — must be no more than thirty, an inclusive
        boundary; and `reopened_count` must still be below two. A violation of
        either answers `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/reopen_window_at_exactly_thirty_whole_days
        """
        env = reference_environment
        dismissed = create_dismissed_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SEVERE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="First dismissed allegation",
        )
        _assert_instant(dismissed["resolved_at"], REFERENCE_NOW, "resolved_at")

        validate_success(
            api.set_clock(THIRTY_WHOLE_DAYS_LATER, COMPLAINT_ANALYST_HEADERS)
        )
        reopened = validate_success(
            api.reopen_complaint(
                dismissed["id"],
                build_reopen_payload(
                    reopen_reason="New evidence at the window edge"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert reopened["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert reopened["reopened_count"] == 1
        assert reopened["resolved_at"] is None
        assert reopened["resolution"] == ComplaintResolution.NONE.value

    def test_reopen_succeeds_one_second_before_the_day_rolls_over(
        self, api, reference_environment
    ):
        """2,678,399 elapsed seconds still truncates to 30 whole days.

        PRD: "Two admissibility rules apply: the whole number of days between
        `resolved_at` and the logical clock — the elapsed seconds divided by
        86,400, rounded down — must be no more than thirty, an inclusive
        boundary; and `reopened_count` must still be below two. A violation of
        either answers `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/reopen_window_at_exactly_thirty_whole_days
        """
        env = reference_environment
        dismissed = create_dismissed_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=THIRD_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="Third dismissed allegation",
        )
        _assert_instant(dismissed["resolved_at"], REFERENCE_NOW, "resolved_at")

        validate_success(
            api.set_clock(THIRTY_DAYS_AND_ALMOST_ONE_MORE, COMPLAINT_ANALYST_HEADERS)
        )
        reopened = validate_success(
            api.reopen_complaint(
                dismissed["id"],
                build_reopen_payload(
                    reopen_reason="Evidence one second before the day rolls over"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert reopened["state"] == ComplaintState.UNDER_INVESTIGATION.value
        assert reopened["reopened_count"] == 1
        assert reopened["resolved_at"] is None
        assert reopened["resolution"] == ComplaintResolution.NONE.value

    def test_reopen_is_refused_once_the_thirty_first_whole_day_completes(
        self, api, reference_environment
    ):
        """2,678,400 elapsed seconds truncates to 31, one day past the window.

        PRD: "Two admissibility rules apply: the whole number of days between
        `resolved_at` and the logical clock — the elapsed seconds divided by
        86,400, rounded down — must be no more than thirty, an inclusive
        boundary; and `reopened_count` must still be below two. A violation of
        either answers `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/reopen_window_at_exactly_thirty_whole_days
        """
        env = reference_environment
        dismissed = create_dismissed_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=MODERATE_OBSERVED_DATE,
            affected_days=AFFECTED_DAYS,
            measured_download_mbps=SEVERE_SHORTFALL_MEASURED_DOWNLOAD,
            narrative="Second dismissed allegation",
        )
        _assert_instant(dismissed["resolved_at"], REFERENCE_NOW, "resolved_at")

        validate_success(
            api.set_clock(THIRTY_ONE_WHOLE_DAYS_LATER, COMPLAINT_ANALYST_HEADERS)
        )
        refused = api.reopen_complaint(
            dismissed["id"],
            build_reopen_payload(reopen_reason="Evidence one day too late"),
            COMPLAINT_ANALYST_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED.value)

        after = read_complaint(dismissed["id"])
        assert after["state"] == ComplaintState.DISMISSED.value
        assert after["reopened_count"] == 0
        assert after["resolution"] == ComplaintResolution.DISMISSED.value
        _assert_instant(after["resolved_at"], REFERENCE_NOW, "resolved_at")


# ---------------------------------------------------------------------------
# Voiding a credit compensates the conserved account ledger.
# ---------------------------------------------------------------------------


class TestVoidCreditRestoresLedger:
    def test_voiding_one_credit_recomputes_the_ledger_from_the_remaining_row(
        self, api, reference_environment
    ):
        """The balance, the count and the flag are recomputed, not adjusted.

        PRD: "Voiding sets the credit's `status` to `VOIDED`, `voided_at` to the
        logical clock, `voided_by_user_id` to the officer's `X-User-ID`, and
        `void_reason` to the supplied reason, then compensates: the account's
        `credit_balance_cents` is recomputed as the sum of `amount_cents` over
        that account's remaining `ISSUED` credits, `remediation_count` as the
        count of those rows, and `audit_flag` re-derived as true exactly when
        that recomputed count is two or more."

        Design: Difficulty/compensating_invariant/void_credit_restores_account_ledger_invariant
        """
        env = reference_environment
        _severe, _moderate, credit_one, _credit_two = (
            _two_upheld_complaints_with_credits(env)
        )

        before = read_subscriber_account(env.account_id)
        assert_account_ledger(
            before, BALANCE_AFTER_BOTH_CREDITS_CENTS, REMEDIATION_AUDIT_THRESHOLD
        )
        assert before["audit_flag"] is True

        voided = validate_success(
            api.void_remediation_credit(
                credit_one["id"],
                build_void_credit_payload(void_reason=FIRST_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )
        assert voided["status"] == RemediationCreditStatus.VOIDED.value
        _assert_instant(voided["voided_at"], REFERENCE_NOW, "voided_at")
        assert voided["voided_by_user_id"] == VOIDING_OFFICER_USER_ID
        assert voided["void_reason"] == FIRST_VOID_REASON
        assert voided["amount_cents"] == SEVERE_PRORATA_CREDIT_CENTS, (
            "the credit amount is immutable after issuance"
        )

        account = read_subscriber_account(env.account_id)
        assert_account_ledger(account, MODERATE_PRORATA_CREDIT_CENTS, 1)
        assert account["audit_flag"] is False, (
            "the flag is re-derived from the recomputed count, not latched"
        )

    def test_voiding_both_credits_leaves_no_drift_on_the_ledger(
        self, api, reference_environment
    ):
        """After both compensations the account is back at its opening figures.

        PRD: "The compensating invariant is that after voiding, the account's
        `credit_balance_cents` again equals the sum of `amount_cents` over its
        `ISSUED` credits: identical to the value it held before the credit was
        ever issued."

        Design: Difficulty/compensating_invariant/void_credit_restores_account_ledger_invariant
        """
        env = reference_environment
        opening_balance = env.account["credit_balance_cents"]
        opening_count = env.account["remediation_count"]
        assert (opening_balance, opening_count) == (0, 0)

        _severe, _moderate, credit_one, credit_two = (
            _two_upheld_complaints_with_credits(env)
        )

        validate_success(
            api.void_remediation_credit(
                credit_one["id"],
                build_void_credit_payload(void_reason=FIRST_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )
        validate_success(
            api.void_remediation_credit(
                credit_two["id"],
                build_void_credit_payload(void_reason=SECOND_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )

        account = read_subscriber_account(env.account_id)
        assert_account_ledger(account, opening_balance, opening_count)
        assert account["credit_balance_cents"] == 0
        assert account["remediation_count"] == 0
        assert account["audit_flag"] is False

    def test_voiding_reverses_the_money_but_not_the_finding(
        self, api, reference_environment
    ):
        """The complaints stay upheld and the plan's counter does not move back.

        PRD: "The complaint's `remediation_credit_cents` is set back to 0, while
        the complaint's `state` stays `UPHELD` and the plan's
        `upheld_complaint_count` is left unchanged — the finding stands even
        though the money is reversed."

        Design: Difficulty/compensating_invariant/void_credit_restores_account_ledger_invariant
        """
        env = reference_environment
        severe, moderate, credit_one, credit_two = (
            _two_upheld_complaints_with_credits(env)
        )

        validate_success(
            api.void_remediation_credit(
                credit_one["id"],
                build_void_credit_payload(void_reason=FIRST_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )
        after_first = read_complaint(severe["id"])
        assert after_first["remediation_credit_cents"] == 0
        assert after_first["state"] == ComplaintState.UPHELD.value
        assert after_first["resolution"] == ComplaintResolution.UPHELD.value

        validate_success(
            api.void_remediation_credit(
                credit_two["id"],
                build_void_credit_payload(void_reason=SECOND_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )
        after_second = read_complaint(moderate["id"])
        assert after_second["remediation_credit_cents"] == 0
        assert after_second["state"] == ComplaintState.UPHELD.value

        plan = read_service_plan(env.plan_id)
        assert plan["upheld_complaint_count"] == UPHELD_COMPLAINT_COUNT_AFTER_BOTH, (
            "the plan's upheld counter is deliberately not reversed"
        )
        assert_posture(plan, LabelPosture.OPEN.value)

    def test_repeated_void_is_refused_so_the_compensation_is_not_applied_twice(
        self, api, reference_environment
    ):
        """A second void of the same credit cannot reverse the money again.

        PRD: "A `ComplianceOfficer` may void an issued credit with a
        `void_reason`; a credit already voided answers
        `ERR_CREDIT_ALREADY_VOIDED`."

        Design: Difficulty/compensating_invariant/void_credit_restores_account_ledger_invariant
        """
        env = reference_environment
        _severe, _moderate, credit_one, credit_two = (
            _two_upheld_complaints_with_credits(env)
        )

        validate_success(
            api.void_remediation_credit(
                credit_one["id"],
                build_void_credit_payload(void_reason=FIRST_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )
        validate_success(
            api.void_remediation_credit(
                credit_two["id"],
                build_void_credit_payload(void_reason=SECOND_VOID_REASON),
                VOIDING_OFFICER_HEADERS,
            )
        )

        refused = api.void_remediation_credit(
            credit_one["id"],
            build_void_credit_payload(void_reason="Duplicate reversal attempt"),
            VOIDING_OFFICER_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_CREDIT_ALREADY_VOIDED.value)

        account = read_subscriber_account(env.account_id)
        assert_account_ledger(account, 0, 0)
        assert account["credit_balance_cents"] == 0, (
            "the compensation is not applied a second time"
        )
