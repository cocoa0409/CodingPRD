"""Semester policy lifecycle and the session-limit derivation matrix."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    complete_intake_short_term,
    create_counselor,
    create_intake,
    create_policy_draft,
    create_published_policy,
    create_student,
    get_episode_for_student,
    make_counselor_headers,
    make_triage_screener_headers,
    publish_policy,
    setup_open_episode,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
RC = TEST_USERS["referral_coordinator_headers"]
CD = TEST_USERS["clinical_director_headers"]


class TestPolicyLifecycle:

    def test_policy_second_publish_same_term_rejected(self):
        """PRD section 3.2: "Publishing a draft policy transitions it from
        `DRAFT` to `PUBLISHED` and is allowed only while no other policy for
        the same term is already `PUBLISHED`; a second publish for the term
        is rejected with `ERR_POLICY_CONFLICT`."

        Design: Corner/state_machines/policy_second_publish_same_term_rejected
        """
        create_published_policy("2026-FALL", base_session_limit=8)
        second = create_policy_draft("2026-FALL", base_session_limit=10,
                                     no_show_strike_limit=4,
                                     late_cancel_window_hours=12)
        resp = api_client.publish_policy(second["id"], CD)
        validate_error(resp, ApiErrorId.ERR_POLICY_CONFLICT)

    def test_policy_retire_requires_draft_replacement(self):
        """PRD section 3.2: "Retiring moves a policy from `PUBLISHED` to
        `RETIRED` and is permitted only when a replacement policy for the same
        term already exists in `DRAFT`; retiring without a waiting replacement
        is likewise rejected with `ERR_POLICY_CONFLICT`."

        Design: Corner/state_machines/policy_retire_requires_draft_replacement
        """
        policy = create_published_policy("2026-FALL", base_session_limit=8)
        resp = api_client.retire_policy(policy["id"], CD)
        validate_error(resp, ApiErrorId.ERR_POLICY_CONFLICT)


class TestSessionLimitDerivation:

    def test_session_limit_standard_term_uses_policy_base(self):
        """PRD section 3.4: "Starting from the published policy's
        `base_session_limit`, a `LOW` band subtracts two sessions, `MODERATE`
        leaves the base unchanged, `HIGH` adds four, and `CRITICAL` adds
        eight."

        MODERATE + STUDENT_FEE under a published base of 8 yields exactly 8.

        Design: Difficulty/dual_variant_calc/session_limit_standard_vs_intersession_variant_divergence
        """
        counselor, student, episode = setup_open_episode(
            student_number="S200", phq9=10, gad7=5,  # 15 -> MODERATE
            academic_term="2026-FALL", base_session_limit=8)
        assert episode["session_limit"] == 8, \
            f"standard-term MODERATE/STUDENT_FEE limit must be 8, got {episode['session_limit']}"
        assert episode["status"] == "OPEN"

    def test_session_limit_intersession_uses_default_base_six(self):
        """PRD section 3.4: "In intersession the default base of six replaces
        the policy base, and the band used for a crisis-created episode is the
        visit's presenting band rather than an intake band."

        With no published policy for 2026-SUMMER, a MODERATE STUDENT_FEE
        student receives 6 + 0 + 0 = 6, not the standard-term 8.

        Design: Difficulty/dual_variant_calc/session_limit_standard_vs_intersession_variant_divergence
        """
        counselor, student, episode = setup_open_episode(
            student_number="S201", full_name="Intersession Term",
            phq9=10, gad7=5,  # 15 -> MODERATE
            academic_term="2026-SUMMER", publish=False)
        assert episode["academic_term"] == "2026-SUMMER"
        assert episode["session_limit"] == 6, \
            f"intersession MODERATE/STUDENT_FEE limit must be 6, got {episode['session_limit']}"

    def test_session_limit_low_band_insurance_funding(self):
        """PRD section 3.4: "Starting from the published policy's
        `base_session_limit`, a `LOW` band subtracts two sessions, `MODERATE`
        leaves the base unchanged, `HIGH` adds four, and `CRITICAL` adds
        eight. The funding adjustment then applies: `STUDENT_FEE` adds
        nothing, `INSURANCE` subtracts one session (insurer-capped plans
        receive one fewer center session), and `SPLIT` adds one. The final
        limit is the greater of two and the adjusted figure — two sessions is
        the absolute floor."

        LOW + INSURANCE under base 8: max(2, (8-2) + (-1)) = 5.

        Design: Difficulty/combinatorial_formula/session_limit_tier_funding_floor_combinatorics
        """
        counselor, student, episode = setup_open_episode(
            student_number="S300", funding_model="INSURANCE",
            phq9=3, gad7=2,  # 5 -> LOW
            academic_term="2026-FALL", base_session_limit=8)
        assert episode["session_limit"] == 5, \
            f"max(2, (8-2)-1) must be 5, got {episode['session_limit']}"

    def test_session_limit_moderate_band_insurance_funding(self):
        """PRD section 3.4: "The funding adjustment then applies:
        `STUDENT_FEE` adds nothing, `INSURANCE` subtracts one session
        (insurer-capped plans receive one fewer center session), and `SPLIT`
        adds one. The final limit is the greater of two and the adjusted
        figure — two sessions is the absolute floor."

        MODERATE + INSURANCE under base 8: max(2, 8 + (-1)) = 7.

        Design: Difficulty/combinatorial_formula/session_limit_tier_funding_floor_combinatorics
        """
        counselor, student, episode = setup_open_episode(
            student_number="S303", funding_model="INSURANCE",
            phq9=10, gad7=8,  # 18 -> MODERATE
            academic_term="2026-FALL", base_session_limit=8)
        assert episode["session_limit"] == 7, \
            f"max(2, 8-1) must be 7, got {episode['session_limit']}"

    def test_high_band_routes_to_referral_without_episode(self):
        """PRD section 3.3: "A `HIGH` band routes to `COMMUNITY_REFERRAL`:
        the system creates a CommunityReferral in `PENDING` status for the
        student with `episode_id` left null, `provider_name` left null, and
        `required_specialty` defaulting to `GEN`. No care episode is created
        for the student."

        Design: Difficulty/combinatorial_formula/session_limit_tier_funding_floor_combinatorics
        """
        counselor = create_counselor(license_id="LIC-3", weekly_capacity=40,
                                     max_risk_points=1000)
        create_published_policy("2026-FALL", base_session_limit=8)
        student = create_student("S301", "High Split", funding_model="SPLIT")
        intake = create_intake(student["id"], counselor["id"],
                               phq9=20, gad7=20)  # 40 -> HIGH
        assert intake["risk_band"] == "HIGH"
        completed = validate_success(api_client.complete_intake_assessment(
            intake["id"], {}, make_triage_screener_headers(counselor["id"])))
        assert completed["disposition"] == "COMMUNITY_REFERRAL"
        referrals, _m = validate_paginated(api_client.list_referrals(
            RC, params={"student_id": student["id"]}))
        assert len(referrals) == 1
        assert referrals[0]["status"] == "PENDING"
        assert referrals[0]["episode_id"] is None
        assert referrals[0]["provider_name"] is None
        assert referrals[0]["required_specialty"] == "GEN"
        episodes, _m2 = validate_paginated(api_client.list_episodes(
            make_counselor_headers(counselor["id"]),
            params={"student_id": student["id"]}))
        assert episodes == [], "HIGH routing must not create a care episode"


class TestCounselorCaseloadGate:

    def test_caseload_risk_points_gate_at_episode_creation(self):
        """PRD section 3.3: "A `LOW` or `MODERATE` band routes to
        `SHORT_TERM_CARE`, provided the student's `enrollment_status` is
        `ENROLLED`, the payload names a `primary_counselor_id` who is
        currently active, and accepting the new episode would not push that
        counselor past either capacity dial of §3.1 — the counselor's
        resulting caseload, current load plus the new episode's risk points,
        must remain within `max_caseload_risk_points`, or the completion is
        rejected with `ERR_COUNSELOR_OVER_CAPACITY`."

        Counselor cap 40 already carries an 18-point OPEN episode; a second
        30-point intake would reach 48.

        Design: Corner/calculations/caseload_risk_points_gate_at_episode_creation
        """
        counselor = create_counselor(license_id="LIC-C3", weekly_capacity=20,
                                     max_risk_points=40)
        create_published_policy("2026-FALL", base_session_limit=8)
        first = create_student("C300", "First Stud")
        ia_first = create_intake(first["id"], counselor["id"],
                                 phq9=10, gad7=8)  # 18 -> MODERATE
        complete_intake_short_term(ia_first["id"], counselor["id"],
                                   "2026-FALL")
        second = create_student("C301", "Second Stud")
        ia_second = create_intake(second["id"], counselor["id"],
                                  phq9=15, gad7=15)  # 30 -> MODERATE
        assert ia_second["risk_points"] == 30
        resp = api_client.complete_intake_assessment(
            ia_second["id"],
            {"primary_counselor_id": counselor["id"],
             "academic_term": "2026-FALL"},
            make_triage_screener_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_COUNSELOR_OVER_CAPACITY)
