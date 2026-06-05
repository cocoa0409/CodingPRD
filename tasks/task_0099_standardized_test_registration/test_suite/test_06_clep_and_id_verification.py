"""CLEP credit recognition and on-test-day identity verification (PRD §3.9, §3.2)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures, factories,
)

SCORE_OPS = TEST_USERS["score_ops_headers"]
ADMIN = TEST_USERS["test_center_admin_headers"]


def _pending_clep(api, scaled_score, subject="COLLEGE_ALGEBRA"):
    cand = fixtures.create_candidate(legal_first_name="Cle", legal_last_name="Pper",
                                    date_of_birth="2007-07-07")
    claim = get_success_data(api.create_clep_claim(
        factories.create_clep_claim_payload(cand["id"], subject, scaled_score),
        make_candidate_headers(cand["id"])))
    return cand, claim


class TestCLEPCredit:
    def test_clep_score_60_recognized_six_hours(self, api):
        """PRD §3.9: "If the score is 50 or above, the claim is recognized — its
        status becomes RECOGNIZED — and the recommended credit hours follow a step
        schedule keyed on the score: a score of at least 50 but below 60 grants 3
        credit hours; a score of at least 60 but below 70 grants 6 credit hours;
        and a score of 70 or above grants 9 credit hours."

        Design: Corner/calculations/clep_credit_tier_boundaries_exact
        """
        cand, claim = _pending_clep(api, 60)
        adjudicated = validate_success(api.adjudicate_clep_claim(claim["id"], SCORE_OPS))
        assert adjudicated["status"] == "RECOGNIZED"
        assert adjudicated["recommended_credit_hours"] == 6, "[60,70) tier grants 6"

    def test_clep_below_threshold_rejected_zero_hours(self, api):
        """PRD §3.9: "If the clep_scaled_score is below 50, the claim is rejected —
        its status becomes REJECTED and recommended_credit_hours stays at zero."

        Design: Corner/calculations/clep_below_threshold_rejected_zero_hours
        """
        cand, claim = _pending_clep(api, 49, subject="BIOLOGY")
        adjudicated = validate_success(api.adjudicate_clep_claim(claim["id"], SCORE_OPS))
        assert adjudicated["status"] == "REJECTED"
        assert adjudicated["recommended_credit_hours"] == 0

    def test_clep_re_adjudicate_invalid_state(self, api):
        """PRD §3.9: "Adjudication is permitted only from PENDING; a second
        adjudication of an already-decided claim is rejected with
        ERR_INVALID_STATE."

        Design: Corner/state_machines/clep_adjudicate_twice_idempotency_invalid_state
        """
        cand, claim = _pending_clep(api, 70)
        validate_success(api.adjudicate_clep_claim(claim["id"], SCORE_OPS))  # -> RECOGNIZED
        resp = api.adjudicate_clep_claim(claim["id"], SCORE_OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestIDVerification:
    def test_same_state_case_insensitive_match(self, api):
        """PRD §3.2: "When the ID is same-state, the comparison is
        case-insensitive: the outcome is MATCH when the presented first and last
        names equal the candidate's legal names ignoring letter case, and MISMATCH
        otherwise." PRD §3.2: "The system first determines cross_state, which is
        true exactly when the presented ID's issuing state differs from the host
        center's state_code, and false otherwise."

        Design: Corner/entities/id_verification_outcome_is_computed_not_input
        """
        center, candidate, session, reg = fixtures.create_reserved_registration()
        resp = api.create_id_verification(
            reg["id"],
            factories.create_id_verification_payload("ada", "lovelace", "CA"),
            ADMIN,
        )
        idv = validate_success(resp, 201)
        assert idv["cross_state"] is False
        assert idv["outcome"] == "MATCH", "same-state case-insensitive match"

    def test_cross_state_case_sensitive_mismatch(self, api):
        """PRD §3.2: "when the ID is cross-state, the verification yields an
        outcome of MATCH only if both the presented first name and the presented
        last name are exactly equal — character for character, case sensitive — to
        the candidate's legal first and last names, and MISMATCH otherwise."

        Design: Corner/calculations/cross_state_id_requires_exact_case_sensitive_match
        """
        center, candidate, session, reg = fixtures.create_reserved_registration(
            candidate_overrides={"home_state_code": "NY", "id_document_state_code": "NY"},
        )
        # Center is CA, presented ID is NY -> cross_state true. Case-mismatched name.
        resp = api.create_id_verification(
            reg["id"],
            factories.create_id_verification_payload("ada", "lovelace", "NY"),
            ADMIN,
        )
        idv = validate_success(resp, 201)
        assert idv["cross_state"] is True, "NY id at CA center"
        assert idv["outcome"] == "MISMATCH", "case-insensitive match not allowed cross-state"
