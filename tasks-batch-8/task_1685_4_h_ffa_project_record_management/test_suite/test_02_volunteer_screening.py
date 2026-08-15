"""Volunteer registration, the pinned-order screening score, and clearance gating."""
from test_helpers import (
    TEST_USERS,
    assert_volunteer,
    create_club,
    create_volunteer,
    make_member_headers,
    make_volunteer_headers,
    setup_club_with_volunteers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestScreeningScorePinnedOrder:
    def test_years_capped_by_base_clearance_floor_division(self, api):
        """PRD §3.2: "First, the service cap is the `base_clearance` divided by
        ten, rounded down to a whole number. Second, the effective service is the
        lesser of `years_service` and that cap. Third, the `screening_score` is
        the `base_clearance`, minus ten points for each open risk flag, plus two
        points for each effective service year."

        base=50, risk=1, years=12: cap=5, effective=5, score = 50-10+5*2 = 50
        (an evaluation that failed to cap years would wrongly produce 64).

        Design: Difficulty/combinatorial_formula/volunteer_screening_circular_pinned_order
        """
        club = create_club()
        res = api.create_volunteer(
            {
                "full_name": "Vol C",
                "email": "vc-pinned@example.com",
                "base_clearance": 50,
                "risk_flags": 1,
                "years_service": 12,
                "club_id": club["id"],
            },
            ADMIN,
        )
        vol = validate_success(res, 201)
        assert_volunteer(vol)
        assert vol["screening_score"] == 50, (
            f"pinned-order score must be 50 (years capped at floor(50/10)=5), "
            f"got {vol['screening_score']}"
        )
        assert vol["screening_status"] == "PENDING"

    def test_years_below_cap_count_in_full(self, api):
        """PRD §3.2: "First, the service cap is the `base_clearance` divided by
        ten, rounded down to a whole number. Second, the effective service is the
        lesser of `years_service` and that cap. Third, the `screening_score` is
        the `base_clearance`, minus ten points for each open risk flag, plus two
        points for each effective service year."

        base=50, risk=0, years=3: cap=5, effective=min(3,5)=3, score = 50+3*2 = 56.

        Design: Difficulty/combinatorial_formula/volunteer_screening_circular_pinned_order
        """
        club = create_club()
        vol = create_volunteer(club["id"], base_clearance=50, risk_flags=0, years_service=3)
        assert vol["screening_score"] == 56, (
            f"score must be 56 (50 + 3*2, all 3 years credited under cap 5), "
            f"got {vol['screening_score']}"
        )

    def test_clearance_at_exactly_threshold_score_succeeds(self, api):
        """PRD §3.2: "Clearing a volunteer (PENDING → CLEARED) requires a
        `screening_score` of at least 40 and no screening event on record with
        outcome FAIL; a clearance request that finds the score below 40 or a
        FAIL event in the history is rejected with `ERR_SCREENING_NOT_CLEARED`
        (HTTP 422)."

        base=40, risk=0, years=0 -> score exactly 40, and "at least 40" is met.

        Design: Difficulty/combinatorial_formula/volunteer_screening_circular_pinned_order
        """
        club = create_club()
        vol = create_volunteer(club["id"], base_clearance=40, risk_flags=0, years_service=0)
        assert vol["screening_score"] == 40
        res = api.clear_volunteer(vol["id"], ADMIN)
        cleared = validate_success(res, 200)
        assert cleared["screening_status"] == "CLEARED"

    def test_clearance_below_threshold_score_rejected(self, api):
        """PRD §3.2: "a clearance request that finds the score below 40 or a
        FAIL event in the history is rejected with `ERR_SCREENING_NOT_CLEARED`
        (HTTP 422)."

        base=30, risk=0, years=20: cap=floor(30/10)=3, score = 30+3*2 = 36 < 40.

        Design: Difficulty/combinatorial_formula/volunteer_screening_circular_pinned_order
        """
        club = create_club()
        vol = create_volunteer(club["id"], base_clearance=30, risk_flags=0, years_service=20)
        assert vol["screening_score"] == 36
        res = api.clear_volunteer(vol["id"], ADMIN)
        validate_error(res, "ERR_SCREENING_NOT_CLEARED")


class TestScreeningRbac:
    def test_member_cannot_clear_volunteer(self, api):
        """PRD §4: "`/api/volunteers/{id}/clear` | Clear a volunteer after
        screening | ProgramAdmin". PRD §2.1: "A request whose role is recognized
        but is not permitted to invoke the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/member_cannot_clear_volunteer
        """
        ctx = setup_club_with_volunteers()
        pending = create_volunteer(ctx["club"]["id"], base_clearance=50, risk_flags=2, years_service=0)
        member = validate_success(
            api.create_member(
                {
                    "full_name": "Mem Rbac",
                    "birth_date": "2009-01-01",
                    "club_id": ctx["club"]["id"],
                },
                make_volunteer_headers(ctx["vol1"]["id"]),
            ),
            201,
        )
        res = api.clear_volunteer(pending["id"], make_member_headers(member["id"]))
        validate_error(res, "ERR_UNAUTHORIZED")
        # The denied call must not have changed the volunteer's state.
        after = validate_success(api.get_volunteer(pending["id"], ADMIN), 200)
        assert after["screening_status"] == "PENDING"
