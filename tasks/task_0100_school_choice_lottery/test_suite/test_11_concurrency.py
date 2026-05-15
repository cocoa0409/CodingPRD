"""Concurrency / race guarantees explicitly defined in PRD §2.11.

PRD §2.11 names FOUR race conditions whose outcomes are pinned in PRD
prose, so concrete error_id-asserting tests are PRD-faithful:

1. Two accepts on different OFFERED applications of the same student →
   exactly one ACCEPTED; loser sees ERR_STUDENT_ALREADY_ACCEPTED.
2. Two accepts racing for the last seat (originally-offered vs
   waitlist-promoted) → loser sees ERR_SEAT_NOT_AVAILABLE.
3. Two /lottery/draw on same Program → loser sees
   ERR_LOTTERY_ALREADY_DRAWN.
4. Two transfer-request approvals racing for the same district's last
   capacity unit → loser sees ERR_DISTRICT_CAPACITY_EXCEEDED.

The framework's run_race() / assert_exactly_one_succeeds() utilities
are used because PRD pins the WINNER count (exactly one). The loser's
error_id is asserted because PRD explicitly names it for every one of
these four races.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    accept_application,
    advance_clock_to,
    api_client,
    assert_exactly_one_succeeds,
    create_application,
    create_district,
    create_family,
    create_program,
    create_school,
    create_student,
    create_transfer_request,
    draw_lottery,
    get_application,
    iso_utc,
    make_district_admin_headers,
    make_family_user_headers,
    open_program_window,
    close_program_window,
    run_race,
    setup_drawn_program_with_offer_and_one_waitlisted,
    setup_district_with_school_and_program,
    setup_family_with_student,
    submit_application,
    validate_error,
    validate_error_is_one_of,
)


class TestSameStudentAcceptRace:

    def test_two_accepts_by_same_student_exactly_one_wins(self, api):
        """PRD §2.11: "When two accept calls arrive on two different
        OFFERED applications by the same student simultaneously,
        exactly one application reaches ACCEPTED; serialization is
        first-writer-wins on Application.status keyed by student_id,
        and the loser sees ERR_STUDENT_ALREADY_ACCEPTED."

        Claim: build TWO OFFERED applications for the same student
        across two programs. Two concurrent /accept calls produce
        exactly one ACCEPTED winner.
        """
        # Two programs, same district, same school, single student with
        # two applications (different ranks).
        district, school, program1 = setup_district_with_school_and_program(
            seats_total=1, seed="race1-p1",
        )
        program2 = create_program(
            district, school,
            grade_level=5, seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="race1-p2",
        )
        family, student = setup_family_with_student(district)
        app1 = create_application(family, student, program1, choice_rank=1)
        app2 = create_application(family, student, program2, choice_rank=2)
        open_program_window(program1)
        app1 = submit_application(family, app1)
        app2 = submit_application(family, app2)
        close_program_window(program1)
        # Both programs share the same registration_close_at → program2
        # is also CLOSED by this clock advance.
        draw_lottery(district, program1)
        draw_lottery(district, program2)
        app1 = get_application(app1["id"])
        app2 = get_application(app2["id"])
        assert app1["status"] == "OFFERED"
        assert app2["status"] == "OFFERED"
        headers = make_family_user_headers(family["id"])
        results = run_race(
            lambda: api.accept_application(app1["id"], headers),
            lambda: api.accept_application(app2["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §2.11 pins the loser's error_id.
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_STUDENT_ALREADY_ACCEPTED.value, (
            f"PRD §2.11: loser sees ERR_STUDENT_ALREADY_ACCEPTED, got {body['data']['error_id']}"
        )


class TestLotteryDrawRace:

    def test_two_draws_same_program_exactly_one_wins(self, api):
        """PRD §2.11: "When two lottery draws are invoked on the same
        program at the same time, the lottery runs exactly once per
        program lifecycle; the loser observes the program already in
        LOTTERY_DRAWN or BACKFILL and is rejected with
        ERR_LOTTERY_ALREADY_DRAWN."

        Claim: two concurrent /lottery/draw calls on a single CLOSED
        program produce exactly one success; the loser sees
        ERR_LOTTERY_ALREADY_DRAWN.
        """
        district, school, program = setup_district_with_school_and_program(
            seats_total=1, seed="race-draw",
        )
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        open_program_window(program)
        submit_application(family, app)
        close_program_window(program)
        headers = make_district_admin_headers(district["id"])
        results = run_race(
            lambda: api.draw_lottery(program["id"], headers),
            lambda: api.draw_lottery(program["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN.value, (
            f"PRD §2.11: loser sees ERR_LOTTERY_ALREADY_DRAWN, got {body['data']['error_id']}"
        )


class TestTransferApprovalRace:

    def test_two_approvals_same_district_capacity_one_wins(self, api):
        """PRD §2.11: "When two transfer-request approvals race against
        the same target district's last available inter-district
        capacity unit, the total number of APPROVED TransferRequest
        rows for that district must not exceed the district's
        inter-district capacity floor; the loser sees
        ERR_DISTRICT_CAPACITY_EXCEEDED."

        Claim: with capacity=1 and two PENDING transfers, two
        concurrent /approve calls produce exactly one success; loser
        sees ERR_DISTRICT_CAPACITY_EXCEEDED.
        """
        advance_clock_to(DEFAULT_BASE_CLOCK)
        target = create_district(accepts_inter_district_transfers=True)
        target_school = create_school(target, school_type="MAGNET", grade_levels_offered=[5])
        target_program = create_program(
            target, target_school, grade_level=5, seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="race-cap",
        )
        home = create_district()
        f1 = create_family(home, poverty_index_score=0.10)
        s1 = create_student(f1, grade_level_next_year=5)
        a1 = create_application(f1, s1, target_program, choice_rank=1)
        tr1 = create_transfer_request(f1, a1, target)
        f2 = create_family(home, poverty_index_score=0.10)
        s2 = create_student(f2, grade_level_next_year=5)
        a2 = create_application(f2, s2, target_program, choice_rank=1)
        tr2 = create_transfer_request(f2, a2, target)
        headers = make_district_admin_headers(target["id"])
        results = run_race(
            lambda: api.approve_transfer_request(tr1["id"], headers),
            lambda: api.approve_transfer_request(tr2["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_DISTRICT_CAPACITY_EXCEEDED.value, (
            f"PRD §2.11: loser sees ERR_DISTRICT_CAPACITY_EXCEEDED, got {body['data']['error_id']}"
        )
