"""Revocation: three hops down a chain the request never names."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ETHICS_OFFICER_1_ID,
    ETHICS_OFFICER_2_ID,
    NO_HEADERS,
    make_ethics_officer_headers,
)

OPENER = make_ethics_officer_headers(ETHICS_OFFICER_1_ID)
DECIDER = make_ethics_officer_headers(ETHICS_OFFICER_2_ID)

STRICT_PROGRAM = {"ceu_credit_accrual_basis": "STRICT_CYCLE"}
CREDIT_CLAIM = {"activity_date": "2026-09-15T00:00:00Z", "category": "LIVE_INSTRUCTION",
                "provider": "State Chapter Seminar", "contact_hours": 12.0}


def _holder_with_credit_and_a_case_under_review(api):
    """A satisfied cycle, one approved activity, and a case that has completed one
    due-process round.
    """
    state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
    activity = fx.approved_ceu(api, state, **CREDIT_CLAIM)
    case = fx.case_awaiting_decision(api, state, opener_user_id=ETHICS_OFFICER_1_ID,
                                    allegation_type="CREDENTIAL_MISUSE",
                                    description="Used the mark on an unrelated licence")
    return state, activity, case


class TestRevocationCascade:
    """One REVOKED decision by an officer other than the one who opened."""

    def test_decision_closes_the_case_and_removes_the_credential_from_publication(self, api):
        """The case closes with its outcome and clock stamp, and hop one strips the
        certificant of its publication and its current cycle pointer.

        PRD §3.12: "Every decision writes the `outcome` and stamps `decided_on` from
        the logical clock, and moves the case to `CLOSED`, which is terminal."

        PRD §3.12: "**Hop one:** the certificant's `status` becomes `REVOKED`, its
        `publication_status` recomputes to `REMOVED` so the credential disappears
        from public verification, and its `current_cycle_id` is cleared."

        Design: Difficulty/transitive_cascade/disciplinary_revocation_cascades_to_cycle_void_ceu_uncounting_and_registry_suppression
        """
        state, _activity, case = _holder_with_credit_and_a_case_under_review(api)
        assert case["status"] == "UNDER_REVIEW"
        assert case["response_round"] == 1
        assert case["opened_by_user_id"] == ETHICS_OFFICER_1_ID

        decided = validate_success(api.decide_case(
            case["id"], f.decide_case_payload("REVOKED"), DECIDER), 200)

        assert decided["status"] == "CLOSED"
        assert decided["outcome"] == "REVOKED"
        assert str(decided["decided_on"]).startswith("2026-08-10")
        ax.assert_disciplinary_case(decided)

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "REVOKED"
        assert certificant["publication_status"] == "REMOVED"
        assert certificant["current_cycle_id"] is None
        ax.assert_publication_status_agrees_with_status(certificant)

    def test_revocation_voids_every_live_cycle_and_zeroes_its_applied_credit(self, api):
        """Hop two voids the cycle that was satisfied, and its applied credit is
        recomputed to zero.

        PRD §3.12: "**Hop two:** because the certificant was revoked, every
        recertification cycle of that certificant whose `status` is `OPEN`,
        `SATISFIED`, or `LAPSED` moves to `VOID`, which is terminal."

        Design: Difficulty/transitive_cascade/disciplinary_revocation_cascades_to_cycle_void_ceu_uncounting_and_registry_suppression
        """
        state, _activity, case = _holder_with_credit_and_a_case_under_review(api)
        assert fx.read_cycle(api, state.cycle_id)["status"] == "SATISFIED"

        validate_success(api.decide_case(
            case["id"], f.decide_case_payload("REVOKED"), DECIDER), 200)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "VOID"
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)

    def test_revocation_uncounts_approved_credit_without_rewriting_its_own_status(self, api):
        """Hop three makes the activity inert while its own status and the credit it
        earned stay on the record.

        PRD §3.12: "**Hop three:** because those cycles were voided, every
        continuing-education activity beneath them whose `status` is `APPROVED`,
        `AUDIT_SELECTED`, or `VERIFIED` has `counted` set to false and
        `credits_counted` set to 0, and each affected cycle's `credits_applied` is
        recomputed to 0.00."

        Design: Difficulty/transitive_cascade/disciplinary_revocation_cascades_to_cycle_void_ceu_uncounting_and_registry_suppression
        """
        state, activity, case = _holder_with_credit_and_a_case_under_review(api)
        assert activity["counted"] is True
        assert float(activity["credits_counted"]) == pytest.approx(12.00, abs=0.01)

        validate_success(api.decide_case(
            case["id"], f.decide_case_payload("REVOKED"), DECIDER), 200)

        after = fx.read_activity(api, activity["id"])
        assert after["status"] == "APPROVED"
        assert float(after["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        ax.assert_uncounted_activity_is_inert(after)

        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(0.00, abs=0.01)

    def test_public_verification_stops_admitting_the_credential_exists(self, api):
        """A lookup that answered a moment earlier now answers as though the record
        had never existed.

        PRD §3.10: "Suppression is deliberately indistinguishable from
        non-existence: when the matched certificant's `publication_status` is
        `WITHHELD` or `REMOVED`, the verification answers
        `ERR_CERTIFICANT_NOT_FOUND` rather than revealing that a suppressed record
        exists."

        Design: Difficulty/transitive_cascade/disciplinary_revocation_cascades_to_cycle_void_ceu_uncounting_and_registry_suppression
        """
        state, _activity, case = _holder_with_credit_and_a_case_under_review(api)
        lookup = {"certificate_number": state.certificate_number}

        disclosed = validate_success(api.verify_registry(lookup, NO_HEADERS), 200)
        assert disclosed["certificate_number"] == state.certificate_number
        assert disclosed["credential_status"] == "ACTIVE"
        ax.assert_registry_verification(disclosed)

        validate_success(api.decide_case(
            case["id"], f.decide_case_payload("REVOKED"), DECIDER), 200)

        suppressed = api.verify_registry(lookup, NO_HEADERS)
        validate_error(suppressed, ApiErrorId.ERR_CERTIFICANT_NOT_FOUND.value, 404)
