"""Post feed-score and neighborhood safety-posture tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_resident_headers, make_agency_officer_headers,
    setup_neighborhood_with_verified_resident,
    setup_neighborhood_with_verified_residents,
    setup_neighborhood_in_emergency,
    create_post, drive_neighborhood_to_emergency,
    report_critical_incident, set_clock,
    api_client, ADMIN,
)


class TestFeedScoreSafetyBoostVariant:
    """The post_feed_score safety_boost variant amplifies SAFETY posts under
    ELEVATED and EMERGENCY posture (Difficulty rule 1)."""

    def test_safety_post_score_amplified_under_emergency_posture(self, api):
        """PRD §3.2: "when the neighborhood's `safety_posture` equals `EMERGENCY`
        and the post's `category` equals `SAFETY`, the posture multiplier
        contribution is 2.0; when the neighborhood's `safety_posture` equals
        `ELEVATED` and the post's `category` equals `SAFETY`, the contribution
        is 1.5; in every other case (the posture is `OPEN`, or the post's
        category is anything other than `SAFETY`) the contribution is 1.0."

        Design: Difficulty/dual_variant_calc/post_feed_score_safety_boost_variant_amplifies_score_under_emergency_posture
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import create_verified_resident
        n, mod, r1 = setup_neighborhood_with_verified_resident()
        # Build a second verified reporter so we can drive N1 to EMERGENCY.
        reporter = create_verified_resident(
            n["id"], mod["id"],
            email="rep@x.com", display_name="Reporter",
            home_address_line="7 A St",
        )
        # Author a SAFETY post first, under OPEN posture.
        p1 = create_post(r1["id"], n["id"], category="SAFETY",
                        title="Fire hazard", body="See 4th and Main")
        # Recency at t=0: 1.0 * 0.5 + SAFETY(1.5) * 0.4 + posture(1.0) + 0 = 2.10
        assert p1["local_relevance_score"] == 2.10, \
            f"Expected 2.10 under OPEN, got {p1['local_relevance_score']}"
        # Drive to EMERGENCY: 3 CRITICAL incidents by the reporter.
        drive_neighborhood_to_emergency(n["id"], reporter["id"])
        # PRD §3.2: score recomputed on every safety_posture transition.
        p1_now = get_success_data(api_client.get_post(p1["id"], ADMIN))
        # Under EMERGENCY: recency 0.5 + category 0.6 + posture 2.0 + 0 = 3.10.
        assert p1_now["local_relevance_score"] == 3.10, \
            f"Expected 3.10 under EMERGENCY, got {p1_now['local_relevance_score']}"
        n_now = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_now["safety_posture"] == "EMERGENCY"

    def test_safety_post_score_delta_between_open_and_emergency(self, api):
        """PRD §3.2: "when the neighborhood's `safety_posture` equals `EMERGENCY`
        and the post's `category` equals `SAFETY`, the posture multiplier
        contribution is 2.0; when the neighborhood's `safety_posture` equals
        `ELEVATED` and the post's `category` equals `SAFETY`, the contribution
        is 1.5; in every other case (the posture is `OPEN`, or the post's
        category is anything other than `SAFETY`) the contribution is 1.0."

        Design: Difficulty/dual_variant_calc/post_feed_score_safety_boost_variant_amplifies_score_under_emergency_posture
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import create_verified_resident
        n, mod, r1 = setup_neighborhood_with_verified_resident()
        reporter = create_verified_resident(
            n["id"], mod["id"],
            email="rep@x.com", display_name="Rep", home_address_line="7 A St",
        )
        p1 = create_post(r1["id"], n["id"], category="SAFETY",
                        title="Fire hazard", body="body")
        open_score = p1["local_relevance_score"]
        drive_neighborhood_to_emergency(n["id"], reporter["id"])
        p1_final = get_success_data(api_client.get_post(p1["id"], ADMIN))
        # Delta between OPEN posture_multiplier=1.0 and EMERGENCY 2.0 is 1.00.
        assert p1_final["local_relevance_score"] - open_score == pytest.approx(1.00, abs=0.001), \
            f"safety_boost delta expected 1.00, got {p1_final['local_relevance_score'] - open_score}"


class TestPostFeedScorePrecision:
    """Corner: post_feed_score precision — two decimals, round_half_up."""

    def test_new_safety_post_under_open_posture_has_score_2_10(self, api):
        """PRD §3.2: "The `local_relevance_score` is the sum of these four
        contributions rounded half up to two decimal places."
        PRD §3.2: "The recency term is multiplied by the recency weight 0.5 to
        yield its contribution to the score."
        PRD §3.2: "The category term is multiplied by the category weight 0.4
        to yield its contribution."

        Design: Corner/calculations/post_feed_score_precision_two_decimals_round_half_up
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r = setup_neighborhood_with_verified_resident()
        p = create_post(r["id"], n["id"], category="SAFETY", title="T", body="b")
        # SAFETY at age=0 under OPEN: 0.5*1.0 + 0.4*1.5 + 1.0 + 0 = 2.10 exact.
        assert p["local_relevance_score"] == 2.10, \
            f"Expected 2.10 (SAFETY, OPEN, age 0), got {p['local_relevance_score']}"


class TestSafetyPostureThresholds:
    """Corner: safety_posture threshold — 1 unresolved CRITICAL -> ELEVATED."""

    def test_one_unresolved_critical_incident_yields_elevated_posture(self, api):
        """PRD §3.4: "If the unresolved critical count is at least 3 (the
        emergency threshold), the `safety_posture` is `EMERGENCY`. Otherwise,
        if the unresolved critical count is at least 1, the `safety_posture`
        is `ELEVATED`."

        Design: Corner/calculations/neighborhood_safety_posture_elevated_below_emergency_threshold
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r = setup_neighborhood_with_verified_resident()
        report_critical_incident(r["id"], n["id"])
        n_now = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_now["unresolved_critical_count"] == 1
        assert n_now["safety_posture"] == "ELEVATED", \
            f"Expected ELEVATED with 1 unresolved CRITICAL, got {n_now['safety_posture']}"


class TestDerivedFieldRecomputationOnPostureFlip:
    """Corner: Post.local_relevance_score recomputed on posture transition."""

    def test_post_score_recomputed_when_posture_flips_open_to_elevated(self, api):
        """PRD §3.2: "The score is recomputed on every write to the post, on
        every neighborhood-level `safety_posture` transition affecting the
        post's neighborhood, and on every logical-clock advance that crosses
        the recency-decay boundary; each recomputation is a mutation on the
        post row and bumps `updated_at` and `version`."

        Design: Corner/cross_cutting_layers/derived_field_recomputation_on_post_after_incident_ack
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r = setup_neighborhood_with_verified_resident()
        p = create_post(r["id"], n["id"], category="SAFETY", title="T", body="b")
        assert p["local_relevance_score"] == 2.10
        # File one CRITICAL incident -> unresolved_critical_count=1 -> ELEVATED.
        report_critical_incident(r["id"], n["id"])
        n_now = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_now["safety_posture"] == "ELEVATED"
        p_now = get_success_data(api_client.get_post(p["id"], ADMIN))
        # SAFETY at age=0 under ELEVATED: 0.5 + 0.6 + 1.5 + 0 = 2.60.
        assert p_now["local_relevance_score"] == 2.60, \
            f"Expected 2.60 after posture flip, got {p_now['local_relevance_score']}"


class TestPostCreationReturnsComputedScore:
    """Corner: POST /posts response includes computed local_relevance_score."""

    def test_post_response_includes_local_relevance_score(self, api):
        """PRD §2.4: "Fields whose value the server derives (marked as
        computed in the underlying data model) — for example, a neighborhood's
        `safety_posture`, its `unresolved_critical_count`, its
        `verified_resident_count`, a resident's `trust_score` and
        `verification_status`, a post's `flag_count` and
        `local_relevance_score`, an event's `rsvp_count`, a business's
        `recommendation_count`, and a moderation decision's
        `trust_delta_applied` — are visible on the returned resource."

        Design: Corner/entities/post_creation_computed_local_relevance_score_returned
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r = setup_neighborhood_with_verified_resident()
        p = create_post(r["id"], n["id"], category="SAFETY", title="T", body="b")
        assert "local_relevance_score" in p, "Post response must expose local_relevance_score"
        assert p["local_relevance_score"] == 2.10
