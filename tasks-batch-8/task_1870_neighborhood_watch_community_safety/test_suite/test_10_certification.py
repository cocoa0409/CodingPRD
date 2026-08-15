"""Certification reviews: composite points, decision tiers, duplicate-open
guard, and the certification gate on National Night Out approval."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    complete_bias_training,
    create_certification_review_payload,
    create_officer,
    decide_review,
    make_officer_headers,
    open_certification_review,
    propose_event,
    setup_cert_scoring_group,
    setup_group_with_registered_block,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCertificationPointsComposite:
    def test_composite_lands_at_45_from_tiered_inputs(self, api):
        """PRD §3.8: "The membership term is one point per `ACTIVE` member whose
        `bias_training_completed_at` is set, capped at 25. The meetings term is
        five points per `HELD` liaison meeting with `quorum_met` true, capped at
        25. The events term is 20 points when a `COMPLETED` `NATIONAL_NIGHT_OUT`
        exists for the group, otherwise 10 points when any `COMPLETED` event
        exists, otherwise zero. The captaincy term is 15 points when every
        `REGISTERED` block holds exactly one `ACTIVE` captain assignment,
        otherwise zero. The alerts term is 15 points when the group has at least
        three alerts in `SENT`, otherwise 5 points when it has at least one,
        otherwise zero."
        PRD §3.8: "its `certification_points` composite is computed at creation
        and recomputed fresh on every decision call."

        Design: Difficulty/combinatorial_formula/certification_points_tiered_branch_mode_a
        """
        ws = setup_cert_scoring_group(
            "Cert Watch", "PCT3",
            member_count=5, trained_count=5,
            quorum_meeting_count=2, sent_alert_count=3,
        )
        review = open_certification_review(ws["group"]["id"], ws["reviewer"])
        assert review["review_status"] == "PENDING"
        assert review["certification_points"] == 45, (
            "5 member (below the 25 cap) + 10 meeting + 0 event (no COMPLETED "
            "events) + 15 captain + 15 three-alert branch = 45"
        )
        assert review["certification_grant_months"] == 0

    def test_conditional_decision_in_40_to_59_band_grants_provisional(self, api):
        """PRD §3.8: "A `CONDITIONAL` decision from `PENDING` requires the points
        to be at least 40 and below 60 and sets certification to `PROVISIONAL`;
        `certification_grant_months` is zero whenever the review is not approved."

        Design: Difficulty/combinatorial_formula/certification_points_tiered_branch_mode_a
        """
        ws = setup_cert_scoring_group(
            "Cert Watch", "PCT3",
            member_count=5, trained_count=5,
            quorum_meeting_count=2, sent_alert_count=3,
        )
        review = open_certification_review(ws["group"]["id"], ws["reviewer"])
        assert review["certification_points"] == 45

        decided = decide_review(review["id"], ws["reviewer"], "CONDITIONAL")
        assert decided["review_status"] == "CONDITIONAL"
        assert decided["certification_grant_months"] == 0

        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["certification_status"] == "PROVISIONAL", (
            "40 <= 45 < 60 places the group on the CONDITIONAL branch"
        )
        assert group["certification_valid_until"] is None


class TestOpenReviewCardinality:
    def test_second_open_review_rejected(self, api):
        """PRD §3.8: "Only one open review per group is allowed: opening a second
        while a `PENDING` or `CONDITIONAL` review exists is rejected with
        `ERR_DUPLICATE`."

        Design: Corner/validations/duplicate_pending_certification_review_rejected
        """
        group = validate_success(
            api.create_watch_group(
                {"name": "DupRev Watch", "precinct_code": "V09"}, COORD,
            ),
            201,
        )
        officer = create_officer("BV09", "Officer DR", "V09")
        open_certification_review(group["id"], officer)

        resp = api.create_certification_review(
            create_certification_review_payload(group["id"], officer["id"]), COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestTrainerCertificationSegregation:
    def test_trainer_cannot_review_own_trained_group(self, api):
        """PRD §2.12: "Second, certification authority is separated from training
        delivery: the officer recorded as `reviewing_officer_id` on a
        certification review must differ from the officer who delivered the
        group's most recent completed `BIAS_AVOIDANCE` training session. A
        violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."
        PRD §3.8: "per §2.12 the reviewing officer must not be the officer who
        delivered the group's most recent completed `BIAS_AVOIDANCE` session,
        enforced at both opening and decision time with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_trainer_cannot_certify_own_group
        """
        group, block = setup_group_with_registered_block(
            "SoD2 Watch", "V03", "3-3 Val St", 4,
        )
        member = add_member(group["id"], block["id"], "SoD2 M", "SMS")
        officer = create_officer("BV03", "Officer SoD", "V03")
        complete_bias_training(group["id"], officer, [member["id"]])

        resp = api.create_certification_review(
            create_certification_review_payload(group["id"], officer["id"]), COORD,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestNationalNightOutCertificationGate:
    def _full_threshold_workspace(self, api):
        """Group built to exactly 80 composite points WITHOUT any completed
        event: 25 capped member points + 25 capped meeting points + 15 captain +
        15 three-alert branch. Returns (workspace, NNO event proposed)."""
        ws = setup_cert_scoring_group(
            "NNO Watch", "PCT14",
            member_count=25, trained_count=25,
            quorum_meeting_count=5, sent_alert_count=3,
        )
        nno = propose_event(
            ws["group"]["id"], "NATIONAL_NIGHT_OUT",
            "2026-08-20T18:00:00Z", "2026-08-20T21:00:00Z", 80,
        )
        return ws, nno

    def test_nno_approve_rejected_while_uncertified(self, api):
        """PRD §3.7: "The certification gate requires the group's
        `certification_status` to be `CERTIFIED` for a `NATIONAL_NIGHT_OUT`, and
        either `PROVISIONAL` or `CERTIFIED` for the other kinds; a shortfall is
        rejected with `ERR_CERTIFICATION_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/event_approval_requires_watch_group_certification_state
        """
        ws, nno = self._full_threshold_workspace(api)
        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["certification_status"] == "UNCERTIFIED"

        resp = api.approve_community_event(
            nno["id"], make_officer_headers(ws["trainer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
        after = validate_success(api.get_community_event(nno["id"], COORD))
        assert after["event_status"] == "PROPOSED"

    def test_nno_approve_succeeds_once_group_certified(self, api):
        """PRD §3.8: "From `PENDING`, an `APPROVED` decision requires the
        recomputed points to be at least 60; it sets the group's
        `certification_status` to `CERTIFIED` when the points reach 80 or more
        and to `PROVISIONAL` below that, grants 24 months of validity at the full
        threshold or 12 months below it in `certification_grant_months`, sets
        `certification_valid_until` to the current moment plus the granted
        months, and recomputes posture."
        PRD §3.7: "The certification gate requires the group's
        `certification_status` to be `CERTIFIED` for a `NATIONAL_NIGHT_OUT`"

        Design: Difficulty/cross_entity_state_dependency/event_approval_requires_watch_group_certification_state
        """
        ws, nno = self._full_threshold_workspace(api)

        review = open_certification_review(ws["group"]["id"], ws["reviewer"])
        assert review["certification_points"] == 80, (
            "25 member cap + 25 meeting cap + 0 event + 15 captain + 15 alert — "
            "exactly the full threshold"
        )
        decided = decide_review(review["id"], ws["reviewer"], "APPROVED")
        assert decided["review_status"] == "APPROVED"
        assert decided["certification_grant_months"] == 24

        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["certification_status"] == "CERTIFIED"
        assert group["certification_valid_until"] is not None
        assert group["certification_valid_until"].startswith("2028-08-11"), (
            "current moment plus 24 months (the fixture's clock rests at "
            "2026-08-11 after the third alert send)"
        )

        approved = validate_success(
            api.approve_community_event(
                nno["id"], make_officer_headers(ws["trainer"]["id"]),
            )
        )
        assert approved["event_status"] == "APPROVED", (
            "Same event, same endpoint — only the parent group's "
            "certification_status changed"
        )
