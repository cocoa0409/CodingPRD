"""Award rubric scoring, star quota, withdraw forks, and scholarship points."""
import pytest

from test_helpers import (
    TEST_DEFAULTS,
    assert_award_application,
    build_approved_record_book,
    create_active_member,
    create_award_application,
    make_member_headers,
    make_volunteer_headers,
    nominate_award,
    setup_active_member_with_project,
    setup_club_with_volunteers,
    setup_endorsed_award,
    setup_evaluated_award,
    setup_member_with_completed_projects,
    setup_nominated_award,
    setup_open_scholarship_app,
    validate_error,
    validate_success,
)


def _late_officer_book(ctx, officer=True):
    """Member + APPROVED book with final_score exactly 80.00:
    sections 80/90/70/85 -> provisional 81.00; officer +5 capped at 100 -> 86;
    submitted 2026-07-17 -> late penalty 2*3=6 -> 80.00."""
    member, project = setup_active_member_with_project(ctx, officer=officer)
    record_book = build_approved_record_book(
        ctx, member, project, submit_at=TEST_DEFAULTS["CLOCK_TWO_DAYS_LATE"]
    )
    assert record_book["final_score"] == pytest.approx(80.00, abs=0.01)
    return member, record_book


class TestAwardRubricScore:
    def test_leadership_norm_below_cap_yields_silver(self, api):
        """PRD §3.9: "The rubric score blends three components: one-half of the
        linked record book's `final_score`, three-tenths of `participation_pct`,
        and one-fifth of the leadership percentage, where the leadership
        percentage is `leadership_pts` capped at twenty points and expressed as
        a percentage of that cap." PRD §3.9: "The tier is GOLD when the rubric
        score is at least 85, SILVER when at least 70, BRONZE when at least 55,
        and NONE below 55; boundaries are inclusive, so a score of exactly 85.00
        earns GOLD."

        final 80.00, participation 92, leadership 14 -> 14/20 = 70% ->
        0.5*80 + 0.3*92 + 0.2*70 = 81.60 -> SILVER.

        Design: Difficulty/combinatorial_formula/award_rubric_tiered_multi_input
        """
        ctx = setup_club_with_volunteers()
        member, record_book = _late_officer_book(ctx)
        app = setup_evaluated_award(
            ctx, member, record_book, track="DEGREE", participation_pct=92, leadership_pts=14
        )
        assert_award_application(app)
        assert app["status"] == "EVALUATED"
        assert app["rubric_score"] == pytest.approx(81.60, abs=0.01), (
            f"0.5*80 + 0.3*92 + 0.2*(14/20*100) = 81.60, got {app['rubric_score']}"
        )
        assert app["award_tier"] == "SILVER"

    def test_leadership_pts_above_cap_are_capped(self, api):
        """PRD §3.9: "the leadership percentage is `leadership_pts` capped at
        twenty points and expressed as a percentage of that cap."

        final 80.00, participation 100, leadership 50 -> capped to 20 -> 100% ->
        0.5*80 + 0.3*100 + 0.2*100 = 90.00 -> GOLD.

        Design: Difficulty/combinatorial_formula/award_rubric_tiered_multi_input
        """
        ctx = setup_club_with_volunteers()
        member, record_book = _late_officer_book(ctx)
        app = setup_evaluated_award(
            ctx, member, record_book, track="DEGREE", participation_pct=100, leadership_pts=50
        )
        assert app["rubric_score"] == pytest.approx(90.00, abs=0.01), (
            f"leadership 50 must cap at 20 (100%): rubric 90.00, got {app['rubric_score']}"
        )
        assert app["award_tier"] == "GOLD"


class TestAwardTierBoundary:
    def test_rubric_exactly_85_is_gold(self, api):
        """PRD §3.9: "The tier is GOLD when the rubric score is at least 85,
        SILVER when at least 70, BRONZE when at least 55, and NONE below 55;
        boundaries are inclusive, so a score of exactly 85.00 earns GOLD."

        final 80.00, participation 100, leadership 15 -> 75% ->
        0.5*80 + 0.3*100 + 0.2*75 = 85.00 exactly.

        Design: Corner/calculations/award_tier_gold_at_exact_boundary
        """
        ctx = setup_club_with_volunteers()
        member, record_book = _late_officer_book(ctx)
        app = setup_evaluated_award(
            ctx, member, record_book, track="DEGREE", participation_pct=100, leadership_pts=15
        )
        assert app["rubric_score"] == pytest.approx(85.00, abs=0.01), (
            f"expected exactly 85.00, got {app['rubric_score']}"
        )
        assert app["award_tier"] == "GOLD", "the 85.00 boundary is inclusive"


class TestStarQuotaBoundary:
    def _star_member(self, api, ctx, birth_date):
        member = create_active_member(
            ctx["club"]["id"], ctx["vol1"]["id"], is_club_officer=True, birth_date=birth_date
        )
        project = validate_success(
            api.create_project(
                {"member_id": member["id"], "project_type": "FOODS", "program_year": 2026},
                make_member_headers(member["id"]),
            ),
            201,
        )
        validate_success(api.start_project(project["id"], make_member_headers(member["id"])), 200)
        record_book = build_approved_record_book(ctx, member, project)
        app = create_award_application(member["id"], record_book["id"], "STAR")
        return member, app

    def test_second_star_nomination_succeeds(self, api):
        """PRD §3.9: "For the STAR track the club quota applies: the member's
        club must have a `star_nomination_count` below two — two active star
        nominations per club is the hard ceiling — or the nomination is rejected
        with `ERR_STAR_QUOTA_EXCEEDED` (HTTP 422)."

        The second nomination moves the count 1 -> 2; 1 is below 2, so it is
        admitted.

        Design: Difficulty/boundary_precision_check/star_quota_empty_slot_boundary
        """
        ctx = setup_club_with_volunteers()
        _, app1 = self._star_member(api, ctx, "2008-01-01")
        _, app2 = self._star_member(api, ctx, "2008-02-01")
        nominated1 = nominate_award(app1["id"], ctx["club"]["id"], ctx["vol1"]["id"])
        assert nominated1["status"] == "NOMINATED"
        nominated2 = nominate_award(app2["id"], ctx["club"]["id"], ctx["vol1"]["id"])
        assert nominated2["status"] == "NOMINATED", (
            "count 1 is below the quota of 2, so the second nomination succeeds"
        )
        club = validate_success(
            api.get_club(ctx["club"]["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert club["star_nomination_count"] == 2

    def test_third_star_nomination_rejected(self, api):
        """PRD §3.9: "the member's club must have a `star_nomination_count`
        below two — two active star nominations per club is the hard ceiling —
        or the nomination is rejected with `ERR_STAR_QUOTA_EXCEEDED`
        (HTTP 422)."

        With the count already at 2, the third nomination has no headroom.

        Design: Difficulty/boundary_precision_check/star_quota_empty_slot_boundary
        """
        ctx = setup_club_with_volunteers()
        _, app1 = self._star_member(api, ctx, "2008-01-01")
        _, app2 = self._star_member(api, ctx, "2008-02-01")
        _, app3 = self._star_member(api, ctx, "2008-03-01")
        nominate_award(app1["id"], ctx["club"]["id"], ctx["vol1"]["id"])
        nominate_award(app2["id"], ctx["club"]["id"], ctx["vol1"]["id"])

        club = validate_success(
            api.get_club(ctx["club"]["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        res = api.nominate_award_application(
            app3["id"],
            {"expected_club_version": club["version"]},
            make_volunteer_headers(ctx["vol1"]["id"]),
        )
        validate_error(res, "ERR_STAR_QUOTA_EXCEEDED")


class TestStarNominateWithdrawInvariant:
    def test_nominate_then_withdraw_restores_zero(self, api):
        """PRD §3.9: "A successful nomination records the acting volunteer's id
        in `nominated_by`, and for the STAR track it also increments the club's
        `star_nomination_count` by one and advances the club's `version`". PRD
        §3.9: "withdrawing a NOMINATED STAR application releases the club's star
        slot (the count decrements by one)".

        Design: Difficulty/compensating_invariant/star_quota_nominate_withdraw_invariant
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=True)
        record_book = build_approved_record_book(ctx, member, project)
        app = setup_nominated_award(ctx, member, record_book, track="STAR")
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        club_mid = validate_success(api.get_club(ctx["club"]["id"], vol_headers), 200)
        assert club_mid["star_nomination_count"] == 1, "nomination must consume one slot"

        withdrawn = validate_success(
            api.withdraw_award_application(app["id"], make_member_headers(member["id"])), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        club_end = validate_success(api.get_club(ctx["club"]["id"], vol_headers), 200)
        assert club_end["star_nomination_count"] == 0, (
            "nominate (+1) then withdraw (-1) must conserve the quota at zero drift"
        )

    def test_two_nominations_one_withdraw_leaves_one(self, api):
        """PRD §3.9: "for the STAR track it also increments the club's
        `star_nomination_count` by one and advances the club's `version`". PRD
        §3.9: "withdrawing a NOMINATED STAR application releases the club's star
        slot (the count decrements by one)".

        Design: Difficulty/compensating_invariant/star_quota_nominate_withdraw_invariant
        """
        ctx = setup_club_with_volunteers()
        member1, project1 = setup_active_member_with_project(ctx, officer=True, birth_date="2008-01-01")
        rb1 = build_approved_record_book(ctx, member1, project1)
        app1 = setup_nominated_award(ctx, member1, rb1, track="STAR")
        member2, project2 = setup_active_member_with_project(ctx, officer=True, birth_date="2008-02-01")
        rb2 = build_approved_record_book(ctx, member2, project2)
        setup_nominated_award(ctx, member2, rb2, track="STAR")

        validate_success(
            api.withdraw_award_application(app1["id"], make_member_headers(member1["id"])), 200
        )
        club = validate_success(
            api.get_club(ctx["club"]["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert club["star_nomination_count"] == 1, (
            f"two nominations and one withdrawal must net to 1, got {club['star_nomination_count']}"
        )


class TestNominatedFork:
    def test_withdraw_from_nominated_releases_star_slot(self, api):
        """PRD §3.9: "A member may also withdraw their own application, from
        NOMINATED or from ENDORSED, moving it to WITHDRAWN; withdrawing a
        NOMINATED STAR application releases the club's star slot (the count
        decrements by one), while withdrawing an ENDORSED application simply
        retires the application."

        The NOMINATED fork carries the quota side effect.

        Design: Difficulty/non_linear_state_machine/award_application_fork_withdraw_vs_evaluate
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=True)
        record_book = build_approved_record_book(ctx, member, project)
        app = setup_nominated_award(ctx, member, record_book, track="STAR")

        withdrawn = validate_success(
            api.withdraw_award_application(app["id"], make_member_headers(member["id"])), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        club = validate_success(
            api.get_club(ctx["club"]["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert club["star_nomination_count"] == 0, (
            "the withdraw fork must release the star slot the nomination consumed"
        )

    def test_withdraw_from_endorsed_retires_application(self, api):
        """PRD §3.9: "A member may also withdraw their own application, from
        NOMINATED or from ENDORSED, moving it to WITHDRAWN; withdrawing a
        NOMINATED STAR application releases the club's star slot (the count
        decrements by one), while withdrawing an ENDORSED application simply
        retires the application."

        The ENDORSED fork is a plain retirement of the application.

        Design: Difficulty/non_linear_state_machine/award_application_fork_withdraw_vs_evaluate
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=True)
        record_book = build_approved_record_book(ctx, member, project)
        app = setup_endorsed_award(ctx, member, record_book, track="STAR")
        assert app["status"] == "ENDORSED"

        withdrawn = validate_success(
            api.withdraw_award_application(app["id"], make_member_headers(member["id"])), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"


class TestEndorseSegregationOfDuties:
    def test_endorse_by_nominating_volunteer_rejected(self, api):
        """PRD §3.9: "Endorsement (NOMINATED → ENDORSED) must be performed by a
        different volunteer than the one recorded in `nominated_by`; a
        self-endorsement is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."

        Design: Corner/state_machines/award_endorse_by_same_volunteer_rejected
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=True)
        record_book = build_approved_record_book(ctx, member, project)
        app = setup_nominated_award(ctx, member, record_book, track="DEGREE")
        assert app["status"] == "NOMINATED"

        res = api.endorse_award_application(app["id"], make_volunteer_headers(ctx["vol1"]["id"]))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


class TestScholarshipPoints:
    def test_round_per_line_then_sum_yields_37(self, api):
        """PRD §2.6: "Scholarship points obey a pinned rounding order: each
        per-project value is rounded half-up to a whole number first, and only
        then are the per-line values summed — summing raw values and rounding
        once at the end is a rejected alternative that produces a different
        total." PRD §3.9: "for each project in COMPLETED status graded A, B, or
        C, a base of seven points is multiplied by the grade factor — one and a
        half for A, one and two-tenths for B, one for C — and each per-project
        value is rounded half-up to a whole number first, per §2.6, before the
        values are summed into the total."

        Grades A,A,B,C -> round(10.5)+round(10.5)+round(8.4)+round(7.0)
        = 11+11+8+7 = 37; the rejected sum-then-round order would give 36.

        Design: Difficulty/dual_variant_calc/scholarship_round_per_line_vs_sum_then_round
        """
        ctx = setup_club_with_volunteers()
        member = create_active_member(
            ctx["club"]["id"], ctx["vol1"]["id"], is_club_officer=True, birth_date="2008-03-01"
        )
        completed = setup_member_with_completed_projects(ctx, member, ["A", "A", "B", "C"])
        assert len(completed) == 4
        app = setup_open_scholarship_app(ctx, member, completed[0]["record_book"])

        submitted = validate_success(
            api.submit_scholarship_app(app["id"], make_member_headers(member["id"])), 200
        )
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["scholarship_points"] == 37, (
            f"per-line rounding must total 37 (not the sum-then-round 36), "
            f"got {submitted['scholarship_points']}"
        )

    def test_two_a_projects_total_22(self, api):
        """PRD §3.9: "Two completed A-grade projects, for instance, contribute
        eleven points each and total twenty-two."

        Design: Difficulty/dual_variant_calc/scholarship_round_per_line_vs_sum_then_round
        """
        ctx = setup_club_with_volunteers()
        member = create_active_member(
            ctx["club"]["id"], ctx["vol1"]["id"], is_club_officer=True, birth_date="2008-04-01"
        )
        completed = setup_member_with_completed_projects(ctx, member, ["A", "A"])
        app = setup_open_scholarship_app(ctx, member, completed[0]["record_book"])

        submitted = validate_success(
            api.submit_scholarship_app(app["id"], make_member_headers(member["id"])), 200
        )
        assert submitted["scholarship_points"] == 22, (
            f"two A projects contribute 11 each for 22, got {submitted['scholarship_points']}"
        )
