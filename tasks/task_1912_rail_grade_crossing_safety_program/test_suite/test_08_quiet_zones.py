"""Quiet zone applications: membership defaults, SSM-credited risk pinning,
supplement cycle, submit gauntlet, reinstate gate (PRD §2.4, §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_quiet_zone_application,
    assert_quiet_zone_crossing,
    create_accepted_review,
    create_draft_zone,
    create_effective_zone,
    create_executed_agreement,
    create_locality,
    create_quiet_zone_application_payload,
    create_team,
    get_success_data,
    make_local_authority_headers,
    setup_locality_and_crossing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _zone_crossing(locality_id, dot, **overrides):
    from test_helpers import create_crossing

    defaults = {
        "dot_crossing_number": dot,
        "annual_train_count": 365,
        "train_speed_max_mph": 25,
        "aadt": 5000,
        "school_bus_count": 0,
        "sight_distance_rating": 3,
        "warning_device_class": "GATES",
    }
    defaults.update(overrides)
    return create_crossing(locality_id, **defaults)


class TestZoneMembership:
    def test_member_added_without_ssm_codes_defaults(self, api, admin_headers):
        """PRD §3.6: "the owning locality adds a member crossing with a payload
        containing the `crossing_id` and an optional `ssm_codes` list of
        supplemental safety measures drawn from `FOUR_QUADRANT_GATES`, `MEDIANS`,
        `CHANNELIZATION`, `ONE_WAY_STREET`, and `WAYSIDE_HORN` (defaulting to an
        empty list). ... Each row records its `quiet_zone_application_id` from the
        path and starts with `membership_status` `MEMBER`."

        Design: Corner/entities/zone_member_defaults
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-010021"}
        )
        zone = create_draft_zone(locality["id"])
        resp = api.add_quiet_zone_member(
            zone["id"],
            {"crossing_id": crossing["id"]},
            make_local_authority_headers(locality["id"]),
        )
        member = validate_success(resp, expected_status=201)
        assert_quiet_zone_crossing(member)
        assert member["ssm_codes"] == []
        assert member["membership_status"] == "MEMBER"
        assert member["quiet_zone_application_id"] == zone["id"]

    def test_crossing_cannot_join_two_non_terminal_zones(self, api, admin_headers):
        """PRD §3.6: "The crossing must be `ACTIVE` (else
        `ERR_CROSSING_NOT_ACTIVE`) and must not already be a `MEMBER` of another
        zone whose status is neither `REJECTED` nor `WITHDRAWN` (else
        `ERR_ZONE_MEMBERSHIP_CONFLICT`)."

        Design: Corner/validations/zone_membership_conflict_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040091"}
        )
        loc_headers = make_local_authority_headers(locality["id"])
        zone_a = create_draft_zone(locality["id"], notes="zone A")
        get_success_data(
            api.add_quiet_zone_member(
                zone_a["id"], {"crossing_id": crossing["id"]}, loc_headers
            )
        )
        zone_b = create_draft_zone(locality["id"], notes="zone B")
        resp = api.add_quiet_zone_member(
            zone_b["id"], {"crossing_id": crossing["id"]}, loc_headers
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_MEMBERSHIP_CONFLICT, expected_status=409)


class TestSubmitGauntlet:
    def test_empty_zone_submit_rejected(self, api, admin_headers):
        """PRD §3.6: "at least one membership row must be `MEMBER` (else
        `ERR_EMPTY_ZONE`)".

        Design: Corner/validations/empty_zone_submit_rejected
        """
        locality = create_locality(locality_name="Empty Zone City")
        zone = create_draft_zone(locality["id"])
        resp = api.transition_quiet_zone_application(
            zone["id"],
            {"to_status": "SUBMITTED"},
            make_local_authority_headers(locality["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_ZONE, expected_status=422)
        after = get_success_data(api.get_quiet_zone_application(zone["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_submit_requires_accepted_review_on_every_member(self, api, admin_headers):
        """PRD §3.6: "every member crossing must have at least one diagnostic
        review in `ACCEPTED` status (else `ERR_DIAGNOSTIC_REVIEW_REQUIRED`)".

        Design: Difficulty/cross_entity_state_dependency/quiet_zone_submit_requires_accepted_reviews
        """
        locality = create_locality(locality_name="Review Gap City")
        team = create_team(team_name="Team Gamma")
        cx_a = _zone_crossing(locality["id"], "DOT-700101")
        cx_b = _zone_crossing(locality["id"], "DOT-700102")
        create_accepted_review(cx_a["id"], team["id"], recommendations=("NO_ACTION",))
        # cx_b deliberately has no review.

        zone = create_draft_zone(locality["id"])
        loc_headers = make_local_authority_headers(locality["id"])
        get_success_data(
            api.add_quiet_zone_member(zone["id"], {"crossing_id": cx_a["id"]}, loc_headers)
        )
        get_success_data(
            api.add_quiet_zone_member(zone["id"], {"crossing_id": cx_b["id"]}, loc_headers)
        )
        resp = api.transition_quiet_zone_application(
            zone["id"], {"to_status": "SUBMITTED"}, loc_headers
        )
        validate_error(resp, ApiErrorId.ERR_DIAGNOSTIC_REVIEW_REQUIRED, expected_status=409)
        after = get_success_data(api.get_quiet_zone_application(zone["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_submit_succeeds_when_every_member_has_accepted_review(
        self, api, admin_headers
    ):
        """PRD §3.6: "the server runs the full submission gauntlet: the caller
        must own the zone (else `ERR_LOCALITY_MISMATCH`); at least one membership
        row must be `MEMBER` (else `ERR_EMPTY_ZONE`); every member crossing must
        be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`); and every member crossing
        must have at least one diagnostic review in `ACCEPTED` status (else
        `ERR_DIAGNOSTIC_REVIEW_REQUIRED`). On success the server computes and pins
        both risk indices."

        Design: Difficulty/cross_entity_state_dependency/quiet_zone_submit_requires_accepted_reviews
        """
        locality = create_locality(locality_name="Review OK City")
        team = create_team(team_name="Team Gamma2")
        cx = _zone_crossing(locality["id"], "DOT-700103")
        create_accepted_review(cx["id"], team["id"], recommendations=("NO_ACTION",))
        zone = create_draft_zone(locality["id"])
        loc_headers = make_local_authority_headers(locality["id"])
        get_success_data(
            api.add_quiet_zone_member(zone["id"], {"crossing_id": cx["id"]}, loc_headers)
        )
        submitted = get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "SUBMITTED"}, loc_headers
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["riwh_pre_ssm"] is not None
        assert submitted["riwh_post_ssm"] is not None


class TestQuietZoneRiskDecision:
    def _build_two_crossing_zone(self, api, ssm_a):
        """Crossings with hazard 50.00 and 34.00, each ACCEPTED-reviewed; a DRAFT
        zone with the first carrying ssm_a and the second none. Submits and moves
        to UNDER_REVIEW. Returns (locality, zone, members)."""
        locality = create_locality(locality_name="Quiet City")
        team = create_team(team_name="Team Alpha")
        # Hazard 50.00: exposure 30.00 SEVERE -> (30*1.40 + 8) * 1.00 = 50.00
        cx_a = _zone_crossing(
            locality["id"],
            "DOT-300201",
            highway_functional_class="ARTERIAL",
            annual_train_count=2190,
            train_speed_max_mph=40,
            aadt=5000,
            school_bus_count=16,
            sight_distance_rating=4,
        )
        # Hazard 34.00: exposure 20.00 HIGH -> (20*1.20 + 10) * 1.00 = 34.00
        cx_b = _zone_crossing(
            locality["id"],
            "DOT-300202",
            annual_train_count=3650,
            train_speed_max_mph=40,
            aadt=2000,
            school_bus_count=20,
            sight_distance_rating=4,
        )
        assert cx_a["hazard_score"] == pytest.approx(50.00, abs=1e-9)
        assert cx_b["hazard_score"] == pytest.approx(34.00, abs=1e-9)
        create_accepted_review(cx_a["id"], team["id"], scheduled_date="2026-09-10")
        create_accepted_review(
            cx_b["id"], team["id"], scheduled_date="2026-09-12",
            recommendations=("NO_ACTION",),
        )
        zone = create_draft_zone(locality["id"], notes="downtown zone")
        loc_headers = make_local_authority_headers(locality["id"])
        m_a = get_success_data(
            api.add_quiet_zone_member(
                zone["id"], {"crossing_id": cx_a["id"], "ssm_codes": ssm_a},
                loc_headers,
            )
        )
        m_b = get_success_data(
            api.add_quiet_zone_member(
                zone["id"], {"crossing_id": cx_b["id"]}, loc_headers
            )
        )
        get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "SUBMITTED"}, loc_headers
            )
        )
        get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "UNDER_REVIEW"}, OFFICER
            )
        )
        return locality, zone, (m_a, m_b)

    def test_pinned_evaluation_order_pre_fails_post_passes_approves(
        self, api, officer_headers
    ):
        """PRD §3.6: "If that pre-SSM index is already at or below the Nationwide
        Significant Risk Threshold of 40.00, the SSM credits are irrelevant to the
        outcome — the pre-check is evaluated first. Otherwise each member crossing
        earns a credit equal to the sum of the effectiveness values of its
        `ssm_codes` — 0.82 for `FOUR_QUADRANT_GATES`, 0.40 for `MEDIANS`, 0.33 for
        `CHANNELIZATION`, 0.25 for `ONE_WAY_STREET`, and 0.15 for `WAYSIDE_HORN` —
        capped at 0.75 per crossing, and `riwh_post_ssm` is the mean over member
        crossings of each hazard score multiplied by one minus its capped credit,
        rounded half-up to 2 decimal places."
        PRD §3.6: "The outcome is `APPROVED` when `riwh_pre_ssm` is at or below
        40.00, or when `riwh_post_ssm` is at or below 40.00."

        Design: Difficulty/combinatorial_formula/quiet_zone_ssm_pinned_evaluation_order
        """
        locality, zone, _ = self._build_two_crossing_zone(api, ["MEDIANS"])
        decided = get_success_data(api.decide_quiet_zone_application(zone["id"], officer_headers))
        assert_quiet_zone_application(decided)
        # riwh_pre_ssm = mean(50.00, 34.00) = 42.00 > NSRT: pre-check fails.
        assert decided["riwh_pre_ssm"] == pytest.approx(42.00, abs=1e-9)
        # riwh_post_ssm = mean(50*0.60, 34) = mean(30, 34) = 32.00 <= NSRT.
        assert decided["riwh_post_ssm"] == pytest.approx(32.00, abs=1e-9)
        assert decided["status"] == "APPROVED", (
            "pre > NSRT must NOT reject when post <= NSRT (pinned order)"
        )

    def test_approved_zone_activates_to_effective(self, api, admin_headers):
        """PRD §3.6: "An approved zone is activated by its owning locality, moving
        `APPROVED` → `EFFECTIVE` (ownership mismatch: `ERR_LOCALITY_MISMATCH`)."

        Design: Difficulty/combinatorial_formula/quiet_zone_ssm_pinned_evaluation_order
        """
        locality, zone, _ = self._build_two_crossing_zone(api, ["MEDIANS"])
        decided = get_success_data(api.decide_quiet_zone_application(zone["id"], OFFICER))
        assert decided["status"] == "APPROVED"
        effective = get_success_data(
            api.transition_quiet_zone_application(
                zone["id"],
                {"to_status": "EFFECTIVE"},
                make_local_authority_headers(locality["id"]),
            )
        )
        assert effective["status"] == "EFFECTIVE"


class TestSupplementCycle:
    def test_supplement_required_then_strengthened_ssms_approved(
        self, api, admin_headers
    ):
        """PRD §3.6: "Failing that, the outcome is `SUPPLEMENT_REQUIRED` when
        `riwh_post_ssm` remains above 40.00 but is strictly below `riwh_pre_ssm`
        — the proposed measures help, just not enough." PRD §3.6: "From `DRAFT` —
        or from `SUPPLEMENT_REQUIRED` when the locality has strengthened its
        measures — the owning locality submits ... re-submission from
        `SUPPLEMENT_REQUIRED` recomputes and re-pins both."
        PRD §3.6: "While the zone is `DRAFT` or `SUPPLEMENT_REQUIRED` — the two
        editable states; adding to a zone in any other state is
        `ERR_INVALID_STATE_TRANSITION`".

        Design: Corner/state_machines/quiet_zone_supplement_cycle_to_approval
        """
        locality = create_locality(locality_name="Cycle Zone City")
        team = create_team(team_name="Team Zeta")
        # Hazard 80.00: exposure 50.00 SEVERE -> (50*1.40 + 10) * 1.00 = 80.00
        cx_c = _zone_crossing(
            locality["id"],
            "DOT-020071",
            highway_functional_class="ARTERIAL",
            annual_train_count=3650,
            train_speed_max_mph=40,
            aadt=5000,
            school_bus_count=20,
            sight_distance_rating=4,
        )
        # Hazard 70.00: exposure 45.00 SEVERE -> (45*1.40 + 7) * 1.00 = 70.00
        cx_d = _zone_crossing(
            locality["id"],
            "DOT-020072",
            highway_functional_class="ARTERIAL",
            annual_train_count=3285,
            train_speed_max_mph=40,
            aadt=5000,
            school_bus_count=14,
            sight_distance_rating=4,
        )
        assert cx_c["hazard_score"] == pytest.approx(80.00, abs=1e-9)
        assert cx_d["hazard_score"] == pytest.approx(70.00, abs=1e-9)
        create_accepted_review(cx_c["id"], team["id"], scheduled_date="2026-09-10")
        create_accepted_review(cx_d["id"], team["id"], scheduled_date="2026-09-12")

        zone = create_draft_zone(locality["id"])
        loc_headers = make_local_authority_headers(locality["id"])
        mem_c = get_success_data(
            api.add_quiet_zone_member(
                zone["id"],
                {"crossing_id": cx_c["id"], "ssm_codes": ["WAYSIDE_HORN"]},
                loc_headers,
            )
        )
        mem_d = get_success_data(
            api.add_quiet_zone_member(
                zone["id"], {"crossing_id": cx_d["id"]}, loc_headers
            )
        )
        get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "SUBMITTED"}, loc_headers
            )
        )
        get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "UNDER_REVIEW"}, OFFICER
            )
        )
        first = get_success_data(api.decide_quiet_zone_application(zone["id"], OFFICER))
        # pre = mean(80, 70) = 75.00; post = mean(80*0.85, 70) = mean(68, 70) = 69.00
        assert first["riwh_pre_ssm"] == pytest.approx(75.00, abs=1e-9)
        assert first["riwh_post_ssm"] == pytest.approx(69.00, abs=1e-9)
        assert first["status"] == "SUPPLEMENT_REQUIRED"

        # The zone is editable again in SUPPLEMENT_REQUIRED: rebuild memberships.
        del_c = api.delete_quiet_zone_crossing(mem_c["id"], loc_headers)
        assert del_c.status_code == 204
        del_d = api.delete_quiet_zone_crossing(mem_d["id"], loc_headers)
        assert del_d.status_code == 204
        get_success_data(
            api.add_quiet_zone_member(
                zone["id"],
                {
                    "crossing_id": cx_c["id"],
                    "ssm_codes": ["WAYSIDE_HORN", "FOUR_QUADRANT_GATES"],
                },
                loc_headers,
            )
        )
        get_success_data(
            api.add_quiet_zone_member(
                zone["id"],
                {"crossing_id": cx_d["id"], "ssm_codes": ["MEDIANS"]},
                loc_headers,
            )
        )
        resubmitted = get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "SUBMITTED"}, loc_headers
            )
        )
        # C credit min(0.82+0.15, 0.75) = 0.75 -> 80*0.25 = 20; D credit 0.40 -> 42.
        assert resubmitted["riwh_pre_ssm"] == pytest.approx(75.00, abs=1e-9)
        assert resubmitted["riwh_post_ssm"] == pytest.approx(31.00, abs=1e-9)

        get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "UNDER_REVIEW"}, OFFICER
            )
        )
        second = get_success_data(api.decide_quiet_zone_application(zone["id"], OFFICER))
        assert second["status"] == "APPROVED"
        assert second["riwh_post_ssm"] == pytest.approx(31.00, abs=1e-9)


class TestReinstateGate:
    def _build_suspended_zone_with_zero_members(self, api):
        """EFFECTIVE zone whose only member crossing is then closed via an
        executed + confirmed closure agreement (PRD §3.5 cascade), leaving the
        zone SUSPENDED with zero MEMBER rows."""
        locality = create_locality(locality_name="Reinstate City")
        team = create_team(team_name="Team Theta")
        cd = _zone_crossing(
            locality["id"],
            "DOT-045001",
            annual_train_count=730,
            aadt=5000,
            school_bus_count=20,
            sight_distance_rating=4,
        )  # hazard 22.00
        create_accepted_review(cd["id"], team["id"], recommendations=("CLOSE_CROSSING",))
        zone, members = create_effective_zone(
            locality["id"], [{"crossing_id": cd["id"]}]
        )
        create_executed_agreement(cd["id"], locality["id"])
        get_success_data(api.confirm_crossing_closure(cd["id"], ADMIN))
        zone_after = get_success_data(api.get_quiet_zone_application(zone["id"], ADMIN))
        assert zone_after["status"] == "SUSPENDED"
        return locality, zone

    def test_reinstate_with_zero_members_rejected(self, api, officer_headers):
        """PRD §3.6: "Reinstatement returns a `SUSPENDED` zone to `EFFECTIVE` at a
        `RailSafetyOfficer`'s hand, but only after the server recomputes the
        post-SSM index live over the current `MEMBER` rows: reinstatement requires
        at least one remaining member and a recomputed `riwh_post_ssm` at or below
        40.00, and failure is rejected with `ERR_SSM_INSUFFICIENT`".

        Design: Corner/validations/ssm_insufficient_on_reinstate
        """
        locality, zone = self._build_suspended_zone_with_zero_members(api)
        resp = api.transition_quiet_zone_application(
            zone["id"], {"to_status": "EFFECTIVE"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_SSM_INSUFFICIENT, expected_status=409)
        after = get_success_data(api.get_quiet_zone_application(zone["id"], ADMIN))
        assert after["status"] == "SUSPENDED"

    def test_suspension_by_officer_allowed_from_effective(self, api, officer_headers):
        """PRD §3.6: "An `EFFECTIVE` zone may be suspended by a
        `RailSafetyOfficer`, and it is also suspended automatically by the closure
        cascade of §3.5 when a member crossing closes and the recomputed post-SSM
        index exceeds the threshold or no members remain."

        Design: Corner/validations/ssm_insufficient_on_reinstate
        """
        locality = create_locality(locality_name="Suspend City")
        team = create_team(team_name="Team Iota")
        cd = _zone_crossing(
            locality["id"],
            "DOT-045002",
            annual_train_count=730,
            aadt=5000,
            school_bus_count=20,
            sight_distance_rating=4,
        )  # hazard 22.00 -> pre 22 <= 40 -> APPROVED
        create_accepted_review(cd["id"], team["id"])
        zone, _members = create_effective_zone(
            locality["id"], [{"crossing_id": cd["id"]}]
        )
        assert zone["status"] == "EFFECTIVE"

        suspended = get_success_data(
            api.transition_quiet_zone_application(
                zone["id"], {"to_status": "SUSPENDED"}, officer_headers
            )
        )
        assert suspended["status"] == "SUSPENDED"
