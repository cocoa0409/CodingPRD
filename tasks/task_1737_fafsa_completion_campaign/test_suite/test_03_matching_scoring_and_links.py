"""Match review: weighted scoring, score bands, OCC on the senior, and link
uniqueness (PRD §2.8, §3.5)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    REVIEWER,
    add_aid_record,
    add_senior,
    create_matched_senior,
    create_match_link_payload,
    fresh_senior,
    propose_link,
    setup_campaign_with_school,
    validate_error,
    validate_paginated,
)

def _band_scenario(api):
    """Three seniors and three aid records engineered to score 1.00 / 0.85 /
    0.55 under default thresholds. Returns (links...)."""
    campaign, school = setup_campaign_with_school()
    # A: everything matches; the aid record's name differs only by case.
    _srA, _arA, link_a, _c = create_matched_senior(
        campaign,
        school,
        student_ref="A1",
        full_name="Ana Lee",
        dob="2009-03-04",
        aid_full_name="ana lee",
        aid_status="SUBMITTED",
    )
    # B: dob + name + district match; school code differs -> 0.85.
    _srB, _arB, link_b, _c = create_matched_senior(
        campaign,
        school,
        student_ref="B1",
        full_name="Bob Kim",
        dob="2009-05-06",
        aid_school_code="SC99",
        aid_status="SUBMITTED",
    )
    # C: dob + school match; name and district differ -> 0.55.
    _srC, _arC, link_c, _c = create_matched_senior(
        campaign,
        school,
        student_ref="C1",
        full_name="Cat Diaz",
        dob="2009-07-08",
        home_language="es",
        aid_full_name="Catalina Diaz",
        aid_district_code="D99",
        aid_status="SUBMITTED",
    )
    return link_a, link_b, link_c


class TestMatchScoreBands:
    def test_full_match_scores_one_and_auto_confirms(self, api):
        """PRD §3.5: "`name_exact` compares `full_name` values case-insensitively
        after trimming" and "The `match_score` is the sum of the weights of the
        true components — 0.40 for an exact date of birth, 0.35 for an exact
        name, 0.15 for a school-code match, 0.10 for a district match".
        PRD §3.5: "a score at or above `auto_confirm_threshold` starts
        `AUTO_CONFIRMED`".

        Design: Difficulty/combinatorial_formula/match_score_weighted_band_assignment
        """
        link_a, _link_b, _link_c = _band_scenario(api)
        assert link_a["match_score"] == pytest.approx(1.0, abs=1e-9), (
            f"all four components true must total 1.00, got "
            f"{link_a['match_score']}"
        )
        assert link_a["status"] == "AUTO_CONFIRMED"
        assert link_a["score_components"] == {
            "dob_exact": True,
            "name_exact": True,  # 'Ana Lee' vs 'ana lee': case-insensitive
            "school_code_match": True,
            "district_match": True,
        }

    def test_partial_scores_land_in_suggested_and_auto_rejected_bands(self, api):
        """PRD §3.5: "a score at or above `review_floor` but below the
        auto-confirm threshold starts `SUGGESTED`; anything below `review_floor`
        starts `AUTO_REJECTED` and is terminal on arrival."

        Design: Difficulty/combinatorial_formula/match_score_weighted_band_assignment
        """
        _link_a, link_b, link_c = _band_scenario(api)
        # dob(0.40) + name(0.35) + district(0.10) = 0.85
        assert link_b["match_score"] == pytest.approx(0.85, abs=1e-9)
        assert link_b["status"] == "SUGGESTED"
        assert link_b["score_components"]["school_code_match"] is False
        # dob(0.40) + school(0.15) = 0.55, below the 0.60 review floor
        assert link_c["match_score"] == pytest.approx(0.55, abs=1e-9)
        assert link_c["status"] == "AUTO_REJECTED"
        assert link_c["score_components"]["name_exact"] is False
        assert link_c["score_components"]["district_match"] is False


class TestMatchScoreThresholdBoundary:
    def _pair(self, api, **campaign_overrides):
        campaign, school = setup_campaign_with_school(
            campaign_overrides=campaign_overrides
        )
        return campaign, school

    def test_score_exactly_at_auto_confirm_threshold_auto_confirms(self, api):
        """PRD §3.5: "a score at or above `auto_confirm_threshold` starts
        `AUTO_CONFIRMED`" — the boundary is inclusive at the default 0.90
        (dob 0.40 + name 0.35 + school 0.15 = 0.90, district differs).

        Design: Difficulty/boundary_precision_check/match_score_exact_threshold_auto_confirm
        """
        campaign, school = self._pair(api)
        _sr, _ar, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_district_code="D99",
            aid_status="SUBMITTED",
        )
        assert link["match_score"] == pytest.approx(0.90, abs=1e-9)
        assert link["status"] == "AUTO_CONFIRMED", (
            f"0.90 >= 0.90 must AUTO_CONFIRM, got {link['status']}"
        )

    def test_score_one_component_below_threshold_is_suggested(self, api):
        """PRD §3.5: "a score at or above `review_floor` but below the
        auto-confirm threshold starts `SUGGESTED`" — 0.85 (dob + name +
        district, school differs) sits one component below the 0.90 default.

        Design: Difficulty/boundary_precision_check/match_score_exact_threshold_auto_confirm
        """
        campaign, school = self._pair(api)
        _sr, _ar, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S2",
            full_name="Bob Kim",
            dob="2009-05-06",
            aid_school_code="SC99",
            aid_status="SUBMITTED",
        )
        assert link["match_score"] == pytest.approx(0.85, abs=1e-9)
        assert link["status"] == "SUGGESTED"

    def test_custom_auto_confirm_threshold_rebands_same_score(self, api):
        """PRD §3.1: the tuning knobs "may be overridden at creation:
        `auto_confirm_threshold` (default 0.90) and `review_floor` (default
        0.60) govern the matching bands of §3.3" — with the threshold lowered
        to 0.80, the same 0.85 pair that defaults to SUGGESTED starts
        AUTO_CONFIRMED.

        Design: Corner/complexity_layers/custom_match_thresholds_change_band
        """
        campaign, school = self._pair(api, auto_confirm_threshold=0.8)
        _sr, _ar, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_school_code="SC99",
            aid_status="SUBMITTED",
        )
        assert link["match_score"] == pytest.approx(0.85, abs=1e-9)
        assert link["status"] == "AUTO_CONFIRMED", (
            f"0.85 >= 0.80 custom threshold must AUTO_CONFIRM, got "
            f"{link['status']}"
        )


class TestMatchLinkConstraints:
    def test_second_non_terminal_link_for_same_senior_rejected(self, api):
        """PRD §3.5: "a senior may have at most one non-terminal link at a time,
        so proposing while a `SUGGESTED`, `AUTO_CONFIRMED`, or `CONFIRMED` link
        still stands is refused with `ERR_LINK_ALREADY_EXISTS`."

        Design: Corner/validations/second_link_for_same_senior_rejected
        """
        campaign, school = setup_campaign_with_school()
        _sr, _ar1, link1, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_school_code="SC99",
            external_ref="E1",
            aid_status="SUBMITTED",
        )
        assert link1["status"] == "SUGGESTED"
        senior_id = link1["senior_record_id"]
        aid2 = add_aid_record(
            campaign,
            external_ref="E2",
            full_name="Ana Lee",
            dob="2009-03-04",
            school_code="SC98",
            district_code="D01",
            initial_status="STARTED",
            effective_date="2027-01-11",
        )
        # Carry a FRESH OCC version so only the dedupe constraint can fail.
        fresh_version = fresh_senior(senior_id)["version"]
        resp = api.create_match_link(
            create_match_link_payload(senior_id, aid2["id"], fresh_version), REVIEWER
        )
        validate_error(resp, ApiErrorId.ERR_LINK_ALREADY_EXISTS)

    def test_match_link_with_nonexistent_aid_record_rejected(self, api):
        """PRD §2.9 step 4: "Existence: path identifiers and body foreign-key
        references resolve to existing resources, validated left to right" —
        the per-resource not-found family includes `ERR_AID_RECORD_NOT_FOUND`
        (PRD §5, 404 Not Found).

        Design: Corner/endpoints/match_link_cross_reference_requires_existing_aid_record
        """
        _campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        resp = api.create_match_link(
            create_match_link_payload(
                senior["id"], NON_EXISTENT_UUID, senior["version"]
            ),
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_AID_RECORD_NOT_FOUND)

    def test_stale_senior_version_rejected_and_fresh_retry_succeeds(self, api):
        """PRD §2.8: "when the supplied value does not equal the senior's
        current `version`, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.5: "Every link creation, whatever its band, increments the
        senior record's `version` by one" and "anything below `review_floor`
        starts `AUTO_REJECTED` and is terminal on arrival" — a terminal
        auto-rejected link does not block a retry carrying the fresh version.

        Design: Corner/complexity_layers/occ_match_link_stale_version_rejected
        """
        campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        aid1 = add_aid_record(
            campaign,
            external_ref="E1",
            full_name="Someone Else",
            dob="2000-01-01",
            school_code="SC99",
            district_code="D99",
            initial_status="STARTED",
            effective_date="2027-01-10",
        )
        aid2 = add_aid_record(
            campaign,
            external_ref="E2",
            full_name="Another Person",
            dob="2000-02-02",
            school_code="SC98",
            district_code="D98",
            initial_status="STARTED",
            effective_date="2027-01-11",
        )

        v1 = senior["version"]
        link1 = propose_link(senior["id"], aid1["id"], expected_version=v1)
        assert link1["status"] == "AUTO_REJECTED", (
            f"a 0.00-scoring pair must auto-reject, got {link1['status']}"
        )
        v2 = fresh_senior(senior["id"])["version"]
        assert v2 == v1 + 1, (
            f"link creation must bump the senior version by one: {v1} -> {v2}"
        )

        # Stale retry carrying the pre-first-create version.
        resp = api.create_match_link(
            create_match_link_payload(senior["id"], aid2["id"], v2 - 1), REVIEWER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Retry with the fresh version succeeds; both links are terminal.
        link2 = propose_link(senior["id"], aid2["id"], expected_version=v2)
        assert link2["status"] == "AUTO_REJECTED"
        resp = api.list_match_links(REVIEWER, params={"senior_record_id": senior["id"]})
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
