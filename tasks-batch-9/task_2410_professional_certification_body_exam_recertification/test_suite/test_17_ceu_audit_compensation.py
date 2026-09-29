"""Audit selection unwinds a counted credit; verification puts it back exactly."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_3_ID,
    ELIGIBILITY_REVIEWER_4_ID,
    make_eligibility_reviewer_headers,
)

REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)
AUDITOR = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_4_ID)

STRICT_PROGRAM = {"ceu_credit_accrual_basis": "STRICT_CYCLE"}
CREDIT_CLAIM = {"activity_date": "2026-09-15T00:00:00Z", "category": "LIVE_INSTRUCTION",
                "provider": "State Chapter Seminar", "contact_hours": 12.0}


def _satisfied_cycle_with_one_approved_activity(api):
    """A cycle carried over the line by a single approved twelve-credit activity."""
    state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
    activity = fx.approved_ceu(api, state, reviewer_user_id=ELIGIBILITY_REVIEWER_3_ID,
                               **CREDIT_CLAIM)
    return state, activity


def _select_for_audit(api, activity_id):
    return validate_success(api.review_ceu_activity(
        activity_id, f.review_ceu_payload("SELECT_FOR_AUDIT"), REVIEWER), 200)


class TestAuditSelectionUnwindsTheLedger:
    """Selection from APPROVED is an explicit compensation, not a fresh review."""

    def test_selection_forces_the_credit_back_out_of_the_count(self, api):
        """The activity keeps the credit it earned but stops counting, and the acting
        reviewer is recorded while no verifier is yet.

        PRD §3.11: "A `SELECT_FOR_AUDIT` is permitted from either `SUBMITTED` or
        `APPROVED`: arriving from `SUBMITTED` it moves the activity `SUBMITTED →
        AUDIT_SELECTED` with `counted` still false, since documentation must be verified
        before credit counts; arriving from `APPROVED` it moves the activity `APPROVED →
        AUDIT_SELECTED` and **compensates** by forcing `counted` back to false and
        `credits_counted` back to 0."

        Design: Difficulty/compensating_invariant/ceu_credit_ledger_unwinds_on_audit_selection_and_reinstates_on_verification
        """
        _state, activity = _satisfied_cycle_with_one_approved_activity(api)
        assert activity["counted"] is True
        assert float(activity["credits_counted"]) == pytest.approx(12.00, abs=0.01)

        selected = _select_for_audit(api, activity["id"])

        assert selected["status"] == "AUDIT_SELECTED"
        assert selected["counted"] is False
        assert float(selected["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert float(selected["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert selected["reviewer_user_id"] == ELIGIBILITY_REVIEWER_3_ID
        assert selected["audit_verifier_user_id"] is None
        ax.assert_ceu_activity(selected)

    def test_the_cycle_and_the_credential_both_fall_back_below_the_line(self, api):
        """The cycle re-derives from its children and reverts to OPEN, and the
        credential's mirror of the applied credit follows it to zero.

        PRD §3.11: "an audit selection or an audit revocation that drops
        `credits_applied` back below `required_credits` compensates by reverting the
        cycle `SATISFIED → OPEN` — at which point closure is refused with
        `ERR_CREDITS_NOT_SATISFIED`."

        PRD §3.10: "`ceu_credits_applied` mirrors the `credits_applied` of the
        certificant's cycle whose `status` is `OPEN` or `SATISFIED`, and is 0 when no
        such cycle exists."

        Design: Difficulty/compensating_invariant/ceu_credit_ledger_unwinds_on_audit_selection_and_reinstates_on_verification
        """
        state, activity = _satisfied_cycle_with_one_approved_activity(api)
        assert fx.read_cycle(api, state.cycle_id)["status"] == "SATISFIED"

        _select_for_audit(api, activity["id"])

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["status"] == "OPEN"
        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(0.00, abs=0.01)
        ax.assert_credits_applied_matches_counted_children(
            cycle, fx.read_activities_of(api, state.cycle_id))


class TestOnlyAnotherOfficerCanReinstateTheCredit:
    """The reinstating call is guarded by segregation of duties."""

    def test_the_selecting_reviewer_cannot_verify_their_own_selection(self, api):
        """The user recorded as reviewer is refused, and the ledger stays unwound.

        PRD §3.11: "Audit verification closes the audit branch and is guarded by
        segregation of duties: the verifying user must differ from the activity's
        `reviewer_user_id`, or the call is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/compensating_invariant/ceu_credit_ledger_unwinds_on_audit_selection_and_reinstates_on_verification
        """
        state, activity = _satisfied_cycle_with_one_approved_activity(api)
        _select_for_audit(api, activity["id"])

        refused = api.audit_verify_ceu_activity(
            activity["id"], f.audit_verify_ceu_payload("VERIFY"), REVIEWER)

        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        unchanged = fx.read_activity(api, activity["id"])
        assert unchanged["status"] == "AUDIT_SELECTED"
        assert unchanged["audit_verifier_user_id"] is None
        assert float(fx.read_cycle(api, state.cycle_id)["credits_applied"]) == pytest.approx(
            0.00, abs=0.01)

    def test_verification_by_another_officer_restores_the_credit_exactly(self, api):
        """The credit returns once and only once, so the cycle reads its pre-audit total
        rather than twice it.

        PRD §3.11: "An `outcome` of `VERIFY` moves the activity `AUDIT_SELECTED →
        VERIFIED` and sets `counted` to true; an `outcome` of `REVOKE` moves it
        `AUDIT_SELECTED → REVOKED`, which is terminal, and leaves `counted` false."

        PRD §3.11: "the invariant behind it holds at every observable moment:
        `credits_applied` always equals the rounded sum of the counted children's
        `credits_counted` plus the cycle's carry-in contribution."

        Design: Difficulty/compensating_invariant/ceu_credit_ledger_unwinds_on_audit_selection_and_reinstates_on_verification
        """
        state, activity = _satisfied_cycle_with_one_approved_activity(api)
        _select_for_audit(api, activity["id"])

        verified = validate_success(api.audit_verify_ceu_activity(
            activity["id"], f.audit_verify_ceu_payload("VERIFY"), AUDITOR), 200)

        assert verified["status"] == "VERIFIED"
        assert verified["counted"] is True
        assert float(verified["credits_counted"]) == pytest.approx(12.00, abs=0.01)
        assert verified["audit_verifier_user_id"] == ELIGIBILITY_REVIEWER_4_ID

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert float(cycle["credits_applied"]) != pytest.approx(24.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"

    def test_the_credential_ends_where_it_began(self, api):
        """After the full swing the credential's mirrored credit is byte-identical to its
        pre-audit value and the holder is still active.

        PRD §3.11: "The cycle's status is **re-derived from its children**, never
        patched."

        Design: Difficulty/compensating_invariant/ceu_credit_ledger_unwinds_on_audit_selection_and_reinstates_on_verification
        """
        state, activity = _satisfied_cycle_with_one_approved_activity(api)
        before = fx.read_certificant(api, state.certificant_id)
        _select_for_audit(api, activity["id"])
        validate_success(api.audit_verify_ceu_activity(
            activity["id"], f.audit_verify_ceu_payload("VERIFY"), AUDITOR), 200)

        after = fx.read_certificant(api, state.certificant_id)
        assert float(after["ceu_credits_applied"]) == pytest.approx(
            float(before["ceu_credits_applied"]), abs=0.01)
        assert float(after["ceu_credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert after["status"] == "ACTIVE"
        ax.assert_credit_precision(after["ceu_credits_applied"])
