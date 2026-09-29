"""Assurance scoring: the two score variants, per-attempt flooring and tamper ordering."""
from test_helpers import (
    complete_session,
    finalize_attempt,
    list_session_cases,
    open_attempt,
    read_attempt,
    read_method_profile,
    read_session,
    restrict_profile_by_bias,
    setup_session,
    submit_database_evidence,
    submit_document_capture,
    submit_knowledge_based_evidence,
)


def _two_accepted_attempts_with_restricted_document_profile():
    """Two accepted attempts worth 39 + 19 points, with the document vendor restricted."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK"),
        client_overrides={"granted_review_credits": 2},
        policy_overrides={
            "min_assurance_score": 60,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
        },
        session_overrides={"external_subject_ref": "subj-r1a"},
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]

    document_attempt = open_attempt(
        session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    submit_document_capture(
        document_attempt["id"],
        client_id,
        document_type="PASSPORT",
        required_feature_count=16,
        passed_feature_count=14,
        tamper_signal_count=0,
        mrz_checksum_valid=True,
    )
    env["document_attempt"] = finalize_attempt(document_attempt["id"], client_id)

    database_attempt = open_attempt(
        session_id, client_id, env["profiles"]["DATABASE_CHECK"]["id"]
    )
    submit_database_evidence(database_attempt["id"], client_id, 7, 9)
    env["database_attempt"] = finalize_attempt(database_attempt["id"], client_id)

    # The document vendor is driven to a restricted bias posture only after both
    # attempts have already reached a terminal state.
    restrict_profile_by_bias(env["profiles"]["DOCUMENT_SCAN"]["id"])
    return env


class TestProvisionalAndFinalAssuranceVariants:
    def test_provisional_score_ignores_the_bias_haircut_that_the_final_score_applies(self):
        """PRD §3.8: "`assurance_score_provisional` is the running view a relying party can
        watch during collection: it sums the `contribution_points` of every attempt of the
        session currently in `SCORED` or `ACCEPTED`, and caps the sum at 100. It applies no
        bias haircut and it ignores `assurance_ceiling` entirely." For the final figure,
        "if that attempt's method profile has `bias_state` equal to `RESTRICTED` at the
        moment the final score is written, its contribution is halved: `contribution_points`
        multiplied by 5000, divided by ten thousand, truncated toward zero."

        Design: Difficulty/dual_variant_calc/assurance_final_variant_applies_bias_haircut_absent_from_provisional
        """
        env = _two_accepted_attempts_with_restricted_document_profile()
        client_id = env["client"]["id"]

        assert read_method_profile(env["profiles"]["DOCUMENT_SCAN"]["id"])["bias_state"] == (
            "RESTRICTED"
        )
        before = read_session(env["session"]["id"], client_id)
        assert before["assurance_score_provisional"] == 58
        assert before["assurance_score_final"] is None

        session = complete_session(env["session"]["id"], client_id)
        assert session["assurance_score_provisional"] == 58
        assert session["assurance_score_final"] == 38

    def test_accepted_contributions_are_untouched_while_the_final_score_halves_the_restricted_one(self):
        """PRD §3.8: "A profile that becomes restricted only after its attempt was accepted
        halves that attempt's weight in the final figure while leaving the provisional figure
        exactly where it was."

        Design: Difficulty/dual_variant_calc/assurance_final_variant_applies_bias_haircut_absent_from_provisional
        """
        env = _two_accepted_attempts_with_restricted_document_profile()
        client_id = env["client"]["id"]
        complete_session(env["session"]["id"], client_id)

        document_attempt = read_attempt(env["document_attempt"]["id"], client_id)
        database_attempt = read_attempt(env["database_attempt"]["id"], client_id)
        assert document_attempt["state"] == "ACCEPTED"
        assert document_attempt["contribution_points"] == 39
        assert database_attempt["state"] == "ACCEPTED"
        assert database_attempt["contribution_points"] == 19

    def test_final_score_short_of_the_policy_floor_escalates_to_a_shortfall_review_case(self):
        """PRD §3.8: "When the age axis is not failed and the final score falls short of
        `min_assurance_score`, the session moves `IN_PROGRESS → MANUAL_REVIEW`:
        `assurance_score_final` is still written, a manual review case is created in `QUEUED`
        with `trigger_reason` of `SCORE_SHORTFALL`, and an audit event of type
        `ESCALATED_TO_REVIEW` is appended. This third branch does not set `completed_at` and does
        not touch biometric templates — the session is not finished, only handed off."

        Design: Difficulty/dual_variant_calc/assurance_final_variant_applies_bias_haircut_absent_from_provisional
        """
        env = _two_accepted_attempts_with_restricted_document_profile()
        client_id = env["client"]["id"]

        session = complete_session(env["session"]["id"], client_id)
        assert session["identity_state"] == "MANUAL_REVIEW"
        assert session["disposition_reason"] is None

        cases, meta = list_session_cases(env["session"]["id"])
        assert meta["total_count"] == 1
        assert cases[0]["trigger_reason"] == "SCORE_SHORTFALL"
        assert cases[0]["state"] == "QUEUED"


def _three_scored_attempts_with_awkward_quality_figures():
    """Three accepted attempts whose weighted products all fall between whole points."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK", "KNOWLEDGE_BASED"),
        policy_overrides={
            "min_assurance_score": 60,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
        },
        session_overrides={"external_subject_ref": "subj-r2b"},
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]

    document_attempt = open_attempt(
        session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    submit_document_capture(
        document_attempt["id"],
        client_id,
        document_type="PASSPORT",
        required_feature_count=16,
        passed_feature_count=14,
        tamper_signal_count=0,
        mrz_checksum_valid=True,
    )
    env["document_attempt"] = finalize_attempt(document_attempt["id"], client_id)

    database_attempt = open_attempt(
        session_id, client_id, env["profiles"]["DATABASE_CHECK"]["id"]
    )
    submit_database_evidence(database_attempt["id"], client_id, 7, 9)
    env["database_attempt"] = finalize_attempt(database_attempt["id"], client_id)

    knowledge_attempt = open_attempt(
        session_id, client_id, env["profiles"]["KNOWLEDGE_BASED"]["id"]
    )
    submit_knowledge_based_evidence(knowledge_attempt["id"], client_id, 5, 7)
    env["knowledge_attempt"] = finalize_attempt(knowledge_attempt["id"], client_id)
    return env


class TestPerAttemptTruncationBeforeSummation:
    def test_each_attempt_contribution_is_truncated_before_the_session_sums_them(self):
        """PRD §2.5: "Truncation is applied per attempt before any summation, never after;
        the sum is never re-derived from raw basis points." PRD §3.4: "the attempt's
        `contribution_points` is the resolved profile's `assurance_weight` multiplied by that
        quality, divided by ten thousand, truncated toward zero."

        Design: Difficulty/combinatorial_formula/assurance_contributions_floored_per_attempt_before_summation
        """
        env = _three_scored_attempts_with_awkward_quality_figures()
        client_id = env["client"]["id"]

        document_attempt = read_attempt(env["document_attempt"]["id"], client_id)
        database_attempt = read_attempt(env["database_attempt"]["id"], client_id)
        knowledge_attempt = read_attempt(env["knowledge_attempt"]["id"], client_id)

        assert document_attempt["evidence_quality_bps"] == 8750
        assert document_attempt["contribution_points"] == 39
        assert database_attempt["evidence_quality_bps"] == 7777
        assert database_attempt["contribution_points"] == 19
        assert knowledge_attempt["evidence_quality_bps"] == 7142
        assert knowledge_attempt["contribution_points"] == 10

    def test_summed_floored_contributions_do_not_recover_the_lost_fractions(self):
        """PRD §3.8: "`assurance_score_final` is written exactly once, by the transition that
        gives the session a terminal identity state or escalates it to manual review at
        completion, and it is null before that. It sums only attempts in `ACCEPTED` — attempts
        sitting in `REQUIRES_RESCORE`, `REJECTED` or `EXPIRED` contribute nothing to either
        figure."

        Design: Difficulty/combinatorial_formula/assurance_contributions_floored_per_attempt_before_summation
        """
        env = _three_scored_attempts_with_awkward_quality_figures()
        client_id = env["client"]["id"]

        assert read_session(env["session"]["id"], client_id)["assurance_score_provisional"] == 68
        session = complete_session(env["session"]["id"], client_id)
        assert session["assurance_score_final"] == 68
        assert session["assurance_score_final"] != 69

    def test_floored_sum_at_or_above_the_policy_floor_verifies_the_session(self):
        """PRD §3.8: "When the age axis is not failed and the freshly written
        `assurance_score_final` is at or above the pinned policy's `min_assurance_score`, the
        session moves `IN_PROGRESS → VERIFIED` with `disposition_reason` set to
        `SCORE_SATISFIED`, `completed_at` set to the clock, the same retention schedule applied and
        the same `SESSION_TERMINAL` event appended."

        Design: Difficulty/combinatorial_formula/assurance_contributions_floored_per_attempt_before_summation
        """
        env = _three_scored_attempts_with_awkward_quality_figures()
        session = complete_session(env["session"]["id"], env["client"]["id"])

        assert session["identity_state"] == "VERIFIED"
        assert session["disposition_reason"] == "SCORE_SATISFIED"
        assert session["completed_at"] is not None


def _capture_tiered_on_its_pre_penalty_base_score():
    """A capture whose base score sits in the middle tamper tier before any penalty."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN",),
        policy_overrides={
            "min_assurance_score": 60,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
        },
        session_overrides={"external_subject_ref": "subj-r2c"},
    )
    client_id = env["client"]["id"]
    attempt = open_attempt(
        env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    env["capture"] = submit_document_capture(
        attempt["id"],
        client_id,
        document_type="NATIONAL_ID",
        required_feature_count=9,
        passed_feature_count=8,
        tamper_signal_count=4,
        mrz_checksum_valid=True,
    )
    env["attempt"] = read_attempt(attempt["id"], client_id)
    return env


class TestTamperTierKeyedOnPrePenaltyBaseScore:
    def test_tamper_tier_is_read_off_the_pre_penalty_base_score(self):
        """PRD §3.4: "`tamper_tier_multiplier_bps` is read off the *pre-penalty* base score,
        never off any later figure. A `base_score_bps` of 9000 or more yields a multiplier of
        10000; a `base_score_bps` of at least 7000 and below 9000 yields 15000; a
        `base_score_bps` below 7000 yields 20000."

        Design: Difficulty/combinatorial_formula/document_tamper_tier_keyed_on_pre_penalty_base_score
        """
        env = _capture_tiered_on_its_pre_penalty_base_score()
        capture = env["capture"]

        assert capture["base_score_bps"] == 8889
        assert capture["tamper_tier_multiplier_bps"] == 15000
        assert capture["tamper_penalty_bps"] == 2700

    def test_authenticity_score_reflects_the_pre_penalty_tier_not_the_post_penalty_one(self):
        """PRD §3.4: "`tamper_penalty_bps` is 450 basis points per tamper signal, scaled by
        that tier multiplier: 450 multiplied by `tamper_signal_count`, multiplied by
        `tamper_tier_multiplier_bps`, divided by ten thousand, truncated toward zero." The
        raw score is then "the base score less the tamper penalty, floored at zero".

        Design: Difficulty/combinatorial_formula/document_tamper_tier_keyed_on_pre_penalty_base_score
        """
        env = _capture_tiered_on_its_pre_penalty_base_score()
        capture = env["capture"]

        assert capture["authenticity_score_bps"] == 6189
        assert capture["authenticity_score_bps"] != 5289

    def test_capture_below_the_policy_floor_but_above_five_thousand_is_suspect_and_scores_the_attempt(self):
        """PRD §3.4: "the `assessment` verdict is `AUTHENTIC` when `authenticity_score_bps` is
        at or above the pinned policy's `doc_authenticity_floor_bps`, `SUSPECT` when it is at
        least 5000 basis points but below that floor, and `FORGED` otherwise." The capture's
        "`authenticity_score_bps` becomes the attempt's `evidence_quality_bps` verbatim".

        Design: Difficulty/combinatorial_formula/document_tamper_tier_keyed_on_pre_penalty_base_score
        """
        env = _capture_tiered_on_its_pre_penalty_base_score()

        assert env["capture"]["assessment"] == "SUSPECT"
        assert env["attempt"]["state"] == "SCORED"
        assert env["attempt"]["evidence_quality_bps"] == 6189
        assert env["attempt"]["contribution_points"] == 27
        assert env["attempt"]["tamper_flag"] is False
