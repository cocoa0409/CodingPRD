"""Death-master file matching: the weighted match score with its SSN
short-circuit, the score bands driving auto-confirmation and auto-dismissal,
manual review of pending matches, and proactive claim generation."""
from test_helpers import (
    ApiErrorId,
    assert_death_master_match,
    create_dmf_match,
    create_policy_with_statute,
    get_claim,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_JANE = {
    "insured_name": "Jane Doe",
    "insured_dob": "1960-01-01",
    "insured_ssn_last4": "1234",
    "insured_zip": "60601",
}


class TestMatchScoreInputs:
    def test_ssn_exact_match_short_circuits(
        self, api, compliance_officer_headers
    ):
        """PRD §3.3: "If both the record's `deceased_ssn_last4` and the
        policy's `insured_ssn_last4` are present and exactly equal, the score
        is 100 outright — the SSN match short-circuits the weighted
        computation."
        PRD §3.3: "A score of 85 or higher is automatically `CONFIRMED` at
        creation".
        PRD §3.3: "If the policy has no non-terminal claim, the system creates
        one in `NOTIFIED` status with `date_of_death` taken from the record's
        `deceased_death_date`, a null `assigned_examiner_id`, and a freshly
        computed contestability flag, and records it on the match as
        `generated_claim_id`."

        Every weighted input mismatches, yet the equal SSN last-four pins the
        score at 100 and generates a claim.

        Design: Difficulty/combinatorial_formula/dmf_match_score_weighted_inputs_and_ssn_shortcircuit
        """
        policy = create_policy_with_statute("IL", policy_number="P-DMF-1", **_JANE)
        set_clock("2026-06-01T00:00:00Z")
        match = create_dmf_match(
            policy["id"],
            deceased_name="John Smith", deceased_dob="1941-02-03",
            deceased_death_date="2026-05-20", deceased_ssn_last4="1234")
        assert_death_master_match(match)
        assert match["match_score"] == 100, "SSN exact match short-circuits"
        assert match["status"] == "CONFIRMED"
        assert match["generated_claim_id"] is not None

        generated = get_claim(match["generated_claim_id"])
        assert generated["status"] == "NOTIFIED"
        assert generated["date_of_death"] == "2026-05-20"

    def test_weighted_score_bands_and_manual_review(
        self, api, compliance_officer_headers
    ):
        """PRD §3.3: "Otherwise the score is a weighted sum: 45 points when
        `deceased_name` equals the policy's `insured_name` exactly, 25 points
        when `deceased_dob` equals `insured_dob`, 15 points when both ZIP
        values are present and equal, and 15 points when both SSN last-four
        values are present and equal — a term that is unreachable in the
        weighted path precisely because an exact SSN match has already
        short-circuited to 100, and which is retained for specification
        symmetry."
        PRD §3.3: "A score of 85 or higher is automatically `CONFIRMED` at
        creation; a score from 60 through 84 lands in `PENDING_REVIEW`; a score
        below 60 is automatically dismissed as `FALSE_POSITIVE`."
        PRD §3.3: "A `ComplianceOfficer` may manually settle a pending match
        through review with a `review_outcome` of `CONFIRMED` or
        `FALSE_POSITIVE`".

        Boundary leg: name+dob+zip lands exactly on 85 (auto-CONFIRMED);
        name+dob lands on 70 (PENDING_REVIEW) and a manual CONFIRMED review
        generates the claim.

        Design: Difficulty/combinatorial_formula/dmf_match_score_weighted_inputs_and_ssn_shortcircuit
        """
        policy2 = create_policy_with_statute("IL", policy_number="P-DMF-2", **_JANE)
        policy3 = create_policy_with_statute("IL", policy_number="P-DMF-3", **_JANE)
        set_clock("2026-06-01T00:00:00Z")

        # 45 + 25 + 15 = 85 -> boundary auto-confirm (>= 85).
        match2 = create_dmf_match(policy2["id"], deceased_zip="60601")
        assert match2["match_score"] == 85
        assert match2["status"] == "CONFIRMED"
        assert match2["generated_claim_id"] is not None

        # 45 + 25 = 70 -> manual review band.
        match3 = create_dmf_match(policy3["id"])
        assert match3["match_score"] == 70
        assert match3["status"] == "PENDING_REVIEW"
        assert match3["generated_claim_id"] is None

        reviewed = validate_success(
            api.review_death_master_match(match3["id"],
                                          {"review_outcome": "CONFIRMED"},
                                          compliance_officer_headers))
        assert reviewed["status"] == "CONFIRMED"
        assert reviewed["generated_claim_id"] is not None
        generated = get_claim(reviewed["generated_claim_id"])
        assert generated["status"] == "NOTIFIED"
        assert generated["date_of_death"] == "2026-05-20"


class TestLowScoreAutoDismissal:
    def test_low_score_auto_false_positive(self, api,
                                           compliance_officer_headers):
        """PRD §3.3: "a score below 60 is automatically dismissed as
        `FALSE_POSITIVE`."
        PRD §3.3: "the manual path requires the match to still be in
        `PENDING_REVIEW`, else it is rejected with
        `ERR_MATCH_NOT_PENDING_REVIEW`."
        PRD §3.3: "Confirmation — whether automatic at creation or by manual
        review — generates a claim proactively."

        A dob-only record scores 25 and is dismissed at creation; no claim is
        generated and no manual review is possible afterwards.

        Design: Corner/calculations/c_dmf_low_score_auto_false_positive
        """
        policy = create_policy_with_statute("IL", policy_number="P-CALC-4", **_JANE)
        set_clock("2026-06-01T00:00:00Z")
        match = create_dmf_match(policy["id"], deceased_name="Nobody Else")
        assert match["match_score"] == 25, "Only the dob term scores"
        assert match["status"] == "FALSE_POSITIVE"
        assert match["generated_claim_id"] is None

        resp = api.review_death_master_match(match["id"],
                                             {"review_outcome": "CONFIRMED"},
                                             compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_MATCH_NOT_PENDING_REVIEW)

        data, meta = validate_paginated(
            api.list_claims(compliance_officer_headers,
                            params={"policy_id": policy["id"]}))
        assert meta["total_count"] == 0 and data == []
