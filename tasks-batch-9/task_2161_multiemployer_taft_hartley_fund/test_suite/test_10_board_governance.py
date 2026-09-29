"""Equal representation: bloc tallies, deadlock arbitration and the voting guards."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_board_motion,
    cast_vote,
    create_board_motion_payload,
    create_fund,
    create_motion_vote_payload,
    create_sister_fund,
    create_trustee,
    list_report_assessments,
    make_trustee_headers,
    move_motion,
    read_employer,
    read_fund,
    read_motion,
    set_clock,
    setup_ld_waiver_motion_voted_against,
    setup_open_board_with_sister_fund,
    tally_motion,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_disagreeing_blocs_deadlock_and_the_arbitrator_carries_the_motion(api):
    """PRD §3.2: "In every other case — the two blocs disagreeing, or either bloc
    landing on `TIED` — the motion becomes `DEADLOCKED`, because equal
    representation means disagreement is a deadlock rather than a loss. A tally
    that lands on `FAILED` or `DEADLOCKED` stamps `tallied_on` and the bloc
    positions but mutates no subject."
    PRD §3.2: "An award of `CARRIED` records `arbitration_award` as `CARRIED`,
    moves the motion from `DEADLOCKED` to `ARBITRATION_CARRIED`, and fires
    exactly the same subject cascades a motion carried at the vote would have
    fired."
    PRD §3.2: "A carried `RECIPROCITY_AGREEMENT` motion has a single effect: the
    referenced sister fund's `reciprocity_agreement_status` flips from `NONE` to
    `EXECUTED`, which is what unlocks the acceptance of transfers from that
    fund."

    Design: Corner/state_machines/motion_deadlock_resolved_by_arbitration_award_carried
    """
    base = setup_open_board_with_sister_fund(union=3, employer=3)
    board = base["board"]
    motion = move_motion(
        base["fund"]["id"],
        "RECIPROCITY_AGREEMENT",
        base["sister"]["id"],
        board["union"][0],
    )
    cast_vote(motion["id"], board["union"][1], "FOR")
    cast_vote(motion["id"], board["union"][2], "FOR")
    cast_vote(motion["id"], board["employer"][0], "AGAINST")
    cast_vote(motion["id"], board["employer"][1], "AGAINST")

    deadlocked = validate_success(api.tally_board_motion(motion["id"], {}, ADMIN))

    assert_board_motion(deadlocked)
    assert deadlocked["status"] == "DEADLOCKED"
    assert deadlocked["union_bloc_position"] == "FOR"
    assert deadlocked["employer_bloc_position"] == "AGAINST"
    assert read_fund(base["sister"]["id"])["reciprocity_agreement_status"] == "NONE"

    awarded = validate_success(
        api.tally_board_motion(motion["id"], {"arbitration_award": "CARRIED"}, ADMIN)
    )

    assert awarded["status"] == "ARBITRATION_CARRIED"
    assert awarded["arbitration_award"] == "CARRIED"
    assert awarded["tallied_on"] == "2026-05-01"
    assert read_fund(base["sister"]["id"])["reciprocity_agreement_status"] == "EXECUTED"


def test_a_failed_waiver_motion_leaves_the_assessment_and_the_ledger_alone(api):
    """PRD §3.2: "If both blocs read `FOR`, the motion becomes `CARRIED`. If both
    read `AGAINST`, it becomes `FAILED`."
    PRD §3.2: "A tally that lands on `FAILED` or `DEADLOCKED` stamps `tallied_on`
    and the bloc positions but mutates no subject."
    PRD §3.6: "The second is open assessments: across every delinquency
    assessment raised on a report of this employer whose `status` is `ASSESSED`,
    add up that assessment's `total_cents`."

    Design: Corner/state_machines/motion_failed_leaves_ld_waiver_subject_and_ledger_untouched
    """
    base = setup_ld_waiver_motion_voted_against()

    failed = tally_motion(base["motion"]["id"])

    assert failed["status"] == "FAILED"
    assert failed["union_bloc_position"] == "AGAINST"
    assert failed["employer_bloc_position"] == "AGAINST"

    assessment = [
        row
        for row in list_report_assessments(base["report"]["id"])
        if row["id"] == base["assessment"]["id"]
    ][0]
    assert assessment["status"] == "ASSESSED"
    assert assessment["waived_cents"] is None
    assert assessment["total_cents"] == 100281

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 182831
    assert employer["status"] == "ACTIVE"
    assert employer["delinquency_strikes"] == 0


def test_a_motion_cannot_be_moved_while_the_board_is_only_restricted(api):
    """PRD §3.2: "no motion at all may be moved unless the fund's posture is
    `OPEN`, which means a `RESTRICTED` or `FROZEN` board is refused with
    `ERR_FUND_GOVERNANCE_NOT_OPEN`."
    PRD §3.2: "Otherwise, if the two counts differ from one another, or if the
    smaller of the two counts is below two trustees per party, the posture is
    `RESTRICTED`."
    PRD §3.2: "The new motion opens in `OPEN` status with `union_bloc_position`,
    `employer_bloc_position`, `tallied_on` and `arbitration_award` all null, and
    the act of moving it bars the mover from voting on it."

    Design: Corner/rbac/motion_moved_while_posture_restricted_is_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    fund = create_fund(name="Restricted Posture Fund", ein="36-7000009")
    sister = create_sister_fund(name="Restricted Posture Sister", ein="36-7000010")
    union_one = create_trustee(fund["id"], "UNION", full_name="Union Trustee One")
    create_trustee(fund["id"], "UNION", full_name="Union Trustee Two")
    create_trustee(fund["id"], "EMPLOYER", full_name="Employer Trustee One")

    lopsided = read_fund(fund["id"])
    assert lopsided["governance_posture"] == "RESTRICTED"
    assert lopsided["active_union_trustees"] == 2
    assert lopsided["active_employer_trustees"] == 1

    validate_error(
        api.create_board_motion(
            create_board_motion_payload(
                fund["id"], "RECIPROCITY_AGREEMENT", sister["id"]
            ),
            make_trustee_headers(union_one["id"]),
        ),
        ApiErrorId.ERR_FUND_GOVERNANCE_NOT_OPEN.value,
    )

    _rows, meta = validate_paginated(
        api.list_board_motions(ADMIN, params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 0

    create_trustee(fund["id"], "EMPLOYER", full_name="Employer Trustee Two")
    assert read_fund(fund["id"])["governance_posture"] == "OPEN"

    motion = validate_success(
        api.create_board_motion(
            create_board_motion_payload(
                fund["id"], "RECIPROCITY_AGREEMENT", sister["id"]
            ),
            make_trustee_headers(union_one["id"]),
        ),
        201,
    )
    assert motion["status"] == "OPEN"
    assert motion["moved_by_trustee_id"] == union_one["id"]
    assert motion["union_bloc_position"] is None
    assert motion["employer_bloc_position"] is None
    assert motion["tallied_on"] is None
    assert motion["arbitration_award"] is None


def test_the_governance_guards_turn_away_every_illegitimate_vote(api):
    """PRD §3.2: "A reference that does not resolve to a row of the type its
    subject demands is rejected with `ERR_MOTION_SUBJECT_INVALID`."
    PRD §3.2: "The motion must still be `OPEN` (`ERR_MOTION_INVALID_STATE`), the
    voting trustee must sit on the same fund's board as the motion
    (`ERR_TRUSTEE_FUND_MISMATCH`), the trustee's seat must be `ACTIVE`
    (`ERR_TRUSTEE_SEAT_INACTIVE`), the trustee must not be the motion's own mover
    (`ERR_MOVER_CANNOT_VOTE`), and the trustee must not already have voted on
    this motion (`ERR_DUPLICATE_VOTE`)."
    PRD §3.2: "If either party has contributed fewer than two counting votes, the
    tally is refused outright with `ERR_QUORUM_NOT_MET` and the motion stays
    `OPEN`."
    PRD §3.2: "For each party in turn, gather the votes cast on this motion by
    trustees whose `appointing_party` is that party, count how many are `FOR` and
    how many are `AGAINST`, and add those two counts together to get the party's
    counting votes — an `ABSTAIN` never counts toward anything."
    PRD §2.8: "Checks are evaluated in the order below and the **first** failure
    wins; later checks are never reached."

    Design: Corner/rbac/motion_vote_guard_sweep_rejects_mover_resigned_foreign_duplicate_and_late_votes
    """
    base = setup_open_board_with_sister_fund(union=3, employer=3)
    fund_id = base["fund"]["id"]
    board = base["board"]
    resigned = create_trustee(
        fund_id, "UNION", full_name="Resigned Union Trustee", seat_status="RESIGNED"
    )
    other_fund = create_fund(name="Governance Guard Fund C", ein="36-7000007")
    foreign_trustee = create_trustee(
        other_fund["id"], "UNION", full_name="Foreign Union Trustee"
    )

    fund_now = read_fund(fund_id)
    assert fund_now["active_union_trustees"] == 3
    assert fund_now["active_employer_trustees"] == 3
    assert fund_now["governance_posture"] == "OPEN"

    motion = move_motion(
        fund_id, "RECIPROCITY_AGREEMENT", base["sister"]["id"], board["union"][0]
    )

    validate_error(
        api.create_board_motion(
            create_board_motion_payload(fund_id, "LD_WAIVER", fund_id),
            make_trustee_headers(board["union"][1]),
        ),
        ApiErrorId.ERR_MOTION_SUBJECT_INVALID.value,
    )

    validate_error(
        api.create_motion_vote(
            create_motion_vote_payload(motion["id"], "FOR"),
            make_trustee_headers(board["union"][0]),
        ),
        ApiErrorId.ERR_MOVER_CANNOT_VOTE.value,
    )

    validate_error(
        api.create_motion_vote(
            create_motion_vote_payload(motion["id"], "FOR"),
            make_trustee_headers(resigned["id"]),
        ),
        ApiErrorId.ERR_TRUSTEE_SEAT_INACTIVE.value,
    )

    validate_error(
        api.create_motion_vote(
            create_motion_vote_payload(motion["id"], "FOR"),
            make_trustee_headers(foreign_trustee["id"]),
        ),
        ApiErrorId.ERR_TRUSTEE_FUND_MISMATCH.value,
    )

    cast_vote(motion["id"], board["union"][1], "FOR")
    validate_error(
        api.create_motion_vote(
            create_motion_vote_payload(motion["id"], "AGAINST"),
            make_trustee_headers(board["union"][1]),
        ),
        ApiErrorId.ERR_DUPLICATE_VOTE.value,
    )
    _votes, vote_meta = validate_paginated(
        api.list_motion_votes(ADMIN, params={"motion_id": motion["id"]})
    )
    assert vote_meta["total_count"] == 1

    validate_error(
        api.tally_board_motion(motion["id"], {}, ADMIN),
        ApiErrorId.ERR_QUORUM_NOT_MET.value,
    )

    cast_vote(motion["id"], board["union"][2], "FOR")
    cast_vote(motion["id"], board["employer"][0], "FOR")
    cast_vote(motion["id"], board["employer"][1], "ABSTAIN")

    validate_error(
        api.tally_board_motion(motion["id"], {}, ADMIN),
        ApiErrorId.ERR_QUORUM_NOT_MET.value,
    )

    cast_vote(motion["id"], board["employer"][2], "FOR")
    carried = tally_motion(motion["id"])
    assert carried["status"] == "CARRIED"
    assert carried["union_bloc_position"] == "FOR"
    assert carried["employer_bloc_position"] == "FOR"

    validate_error(
        api.create_motion_vote(
            create_motion_vote_payload(motion["id"], "AGAINST"),
            make_trustee_headers(resigned["id"]),
        ),
        ApiErrorId.ERR_MOTION_INVALID_STATE.value,
    )

    assert read_fund(base["sister"]["id"])["reciprocity_agreement_status"] == "EXECUTED"
    assert read_motion(motion["id"])["status"] == "CARRIED"
