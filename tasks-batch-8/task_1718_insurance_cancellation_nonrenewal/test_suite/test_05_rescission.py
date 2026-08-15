"""Rescission of a cancellation: calendar gate and the premium-ledger
invariant for a case rescinded before effectiveness.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_cancellation,
    assert_ledger_sum,
    assert_no_return_entries,
    cancel_policy_effective,
    dispatch_cancellation_notices,
    open_cancellation_case,
    rescind_payload,
    setup_active_policy,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]


class TestRescindAfterEffectiveness:
    def test_rescind_after_effectiveness_rejected(self, api):
        """PRD §3.5: "Once the case has reached `NOTICE_SENT`, the calendar
        binds as well: the current clock date must be strictly earlier than
        the `scheduled_effective_date`, because a rescission attempted on or
        after the cancellation's effective date is rejected with
        `ERR_ALREADY_EFFECTIVE`." A case the sweep has already moved to
        `EFFECTIVE` likewise does not admit the transition: "a case in any
        other status does not admit the transition and is rejected with
        `ERR_INVALID_STATE`." The PRD does not state which of the two
        rejections pre-empts the other once both hold, so either is accepted;
        both are HTTP 409.

        Design: Corner/state_machines/rescind_after_effectiveness_rejected
        """
        bundle = cancel_policy_effective(
            "NC",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-NC-1",
        )
        case = bundle["case"]
        assert case["status"] == "EFFECTIVE"

        fx.set_clock("2026-08-21T00:00:00Z")
        resp = api.rescind_cancellation_case(case["id"], rescind_payload("too late"), OFFICER)
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_ALREADY_EFFECTIVE, ApiErrorId.ERR_INVALID_STATE]
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({actual})"

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "EFFECTIVE"


class TestRescissionLedgerInvariant:
    def test_rescinded_case_returns_policy_to_active(self, api):
        """PRD §3.5: "Rescinding moves the case to `RESCINDED`, returns the
        policy from `CANCEL_PENDING` to `ACTIVE`, bumps the policy's
        `version`, and increments the `rescinded_count` on the regulatory
        report for the pinned profile and the current clock month —
        auto-creating an `OPEN` report row when none exists."

        Design: Difficulty/compensating_invariant/rescinded_cancellation_preserves_premium_ledger_sum
        """
        _profile, _holder, policy = setup_active_policy("SC", clock="2026-08-01T00:00:00Z",
                                                        policy_over={"total_premium_cents": 36500})
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        approve_cancellation(case["id"], "2026-08-20")
        dispatch_cancellation_notices(case["id"], "2026-08-01", tracking_prefix="T-SC")
        fx.set_clock("2026-08-10T00:00:00Z")  # before the scheduled date

        rescinded = validate_success(
            api.rescind_cancellation_case(case["id"], rescind_payload("Insured paid in full"), OFFICER)
        )
        assert rescinded["status"] == "RESCINDED"
        assert fx.get_policy(policy["id"])["status"] == "ACTIVE"

    def test_rescission_before_effectiveness_posts_no_return_entries(self, api):
        """PRD §2.9: "Four posting events write ledger lines. Issuing a
        policy posts a `WRITTEN` entry for the full `total_premium_cents`. A
        cancellation that reaches effectiveness posts a `RETURN_PRO_RATA` or
        `RETURN_SHORT_RATE` entry — chosen by the case's pinned
        `return_method` — with a negative amount equal to the finalized
        `return_premium_cents`. An approved reinstatement posts a positive
        `REINSTATEMENT_FEE` entry for the request's computed
        `reinstatement_fee_cents`. An appeal that overturns an
        already-effective cancellation posts a compensating `RETURN_PRO_RATA`
        entry with a positive amount exactly equal to the original negative
        return entry." Rescission before effectiveness is none of the four,
        so the ledger still holds only the written premium.

        Design: Difficulty/compensating_invariant/rescinded_cancellation_preserves_premium_ledger_sum
        """
        _profile, _holder, policy = setup_active_policy("SC", clock="2026-08-01T00:00:00Z",
                                                        policy_over={"total_premium_cents": 36500})
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        approve_cancellation(case["id"], "2026-08-20")
        dispatch_cancellation_notices(case["id"], "2026-08-01", tracking_prefix="T-SC")
        fx.set_clock("2026-08-10T00:00:00Z")

        validate_success(
            api.rescind_cancellation_case(case["id"], rescind_payload("Insured paid in full"), OFFICER)
        )

        ledger = fx.policy_ledger(policy["id"])
        assert_no_return_entries(ledger)
        assert_ledger_sum(ledger, 36500)
