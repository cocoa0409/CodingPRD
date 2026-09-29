"""The attendance gate, the CEU certificate, and the conserved learner CEU ledger."""

from test_helpers import (
    ADMIN,
    REGISTRAR,
    ApiErrorId,
    assert_certificate_number,
    assert_completion_record,
    make_instructor_headers,
    memberships_by_segment,
    list_memberships,
    read_learner,
    read_record,
    read_registration,
    record_attendance,
    reset_clock,
    setup_census_locked_offering,
    setup_issued_completion,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCompletionAwardCascade:
    """Awarding a completion drives record, learner totals and marketing segments."""

    def test_award_issues_the_certificate_and_moves_the_registration_to_completed(self, api):
        """PRD 3.7: "**Hop one**: the registration moves `ENROLLED → COMPLETED`."
        PRD 3.7: "**Hop two**, caused by hop one: a `CompletionRecord` is created with
        `status` `ISSUED`, its `registration_id` pointing at the registration and its
        `learner_id` denormalised from that registration so learner-scoped queries need
        no join, its `ceu_awarded` and `attendance_ratio` as computed above, its
        `issued_at` stamped from the logical clock, and its `certificate_number`
        minted."
        PRD 3.7: "The sequence is the one-based position of this record among that
        section's completion records ordered by `created_at` ascending, written with
        leading zeros to exactly four digits — so the first certificate issued on the
        autumn 2026 delivery reads `CEU-2026FA-0001` and the twelfth on a rolling
        section reads `CEU-ROLL-0012`."

        Design: Difficulty/transitive_cascade/completion_award_four_hop_learner_loyalty_marketing_chain
        """
        reset_clock()
        scene = setup_census_locked_offering(num_learners=1)
        seat = scene["seats"][0]
        record_attendance(seat["registration_id"], 10, scene["instructor_id"])

        data = validate_success(
            api.award_completion(
                seat["registration_id"], make_instructor_headers(scene["instructor_id"])
            ),
            201,
        )
        assert_completion_record(data)
        assert data["status"] == "ISSUED"
        assert data["ceu_awarded"] == 1.2
        assert data["attendance_ratio"] == 1.0
        assert data["certificate_number"] == "CEU-2026FA-0001"
        assert data["learner_id"] == seat["learner_id"]

        registration = read_registration(seat["registration_id"])
        assert registration["enrollment_status"] == "COMPLETED"

    def test_award_recomputes_learner_totals_and_flips_the_marketing_segment(self, api):
        """PRD 3.7: "**Hop three**, caused by hop two: the learner's
        `lifetime_completed_count`, `lifetime_ceu_total` and `loyalty_tier` are
        recomputed."
        PRD 3.7: "**Hop four**, caused by hop three: the marketing segmentation
        recompute runs for the learner, so the previously `ACTIVE` membership among
        `PROSPECT`, `FIRST_TIME` and `REPEAT` moves to `state` `REMOVED` and the newly
        matching segment gains an `ACTIVE` membership."
        PRD 3.3: "The **exclusive axis** admits exactly one active segment at a time and
        is keyed purely on `lifetime_completed_count`: a count of zero puts the learner
        in `PROSPECT`, a count of exactly one puts them in `FIRST_TIME`, and a count of
        two or more puts them in `REPEAT`."

        Design: Difficulty/transitive_cascade/completion_award_four_hop_learner_loyalty_marketing_chain
        """
        reset_clock()
        scene = setup_issued_completion()
        learner = read_learner(scene["learner_id"])
        assert learner["lifetime_completed_count"] == 1
        assert learner["lifetime_ceu_total"] == 1.2
        assert learner["loyalty_tier"] == "RETURNING"

        states = memberships_by_segment(list_memberships(scene["learner_id"]))
        assert states.get("PROSPECT") == "REMOVED"
        assert states.get("FIRST_TIME") == "ACTIVE"


class TestAttendanceGate:
    """The 0.80 attendance ratio is compared inclusively."""

    def test_ratio_exactly_at_the_threshold_awards_the_full_ceu(self, api):
        """PRD 3.7: "The gate computes `attendance_ratio` as `sessions_attended`
        divided by `total_sessions`, rounded half up to four decimal places, and
        requires it to be at least the minimum attendance ratio of 0.80. The comparison
        is inclusive: a ratio of exactly `0.8000` passes, and only a ratio strictly
        below it is rejected with `ERR_ATTENDANCE_BELOW_THRESHOLD` (HTTP 422)."
        PRD 3.7: "The CEU credited is then `ceu_awarded`, taken as the section's
        course's `ceu_units` rounded half up to one decimal place."

        Design: Difficulty/boundary_precision_check/attendance_ratio_exactly_at_threshold_awards_ceu
        """
        reset_clock()
        scene = setup_census_locked_offering(num_learners=2)
        pass_seat = scene["seats"][0]
        record_attendance(pass_seat["registration_id"], 8, scene["instructor_id"])

        data = validate_success(
            api.award_completion(
                pass_seat["registration_id"], make_instructor_headers(scene["instructor_id"])
            ),
            201,
        )
        assert data["attendance_ratio"] == 0.8, (
            f"8 of 10 sessions is exactly 0.8000, got {data['attendance_ratio']}"
        )
        assert data["ceu_awarded"] == 1.2
        assert data["status"] == "ISSUED"
        assert read_registration(pass_seat["registration_id"])["enrollment_status"] == "COMPLETED"

    def test_ratio_below_the_threshold_is_rejected_and_issues_no_record(self, api):
        """PRD 3.7: "The gate computes `attendance_ratio` as `sessions_attended`
        divided by `total_sessions`, rounded half up to four decimal places, and
        requires it to be at least the minimum attendance ratio of 0.80. The comparison
        is inclusive: a ratio of exactly `0.8000` passes, and only a ratio strictly
        below it is rejected with `ERR_ATTENDANCE_BELOW_THRESHOLD` (HTTP 422)."
        PRD 2.3: "Completion records may be filtered by `registration_id`,
        `learner_id` and `status`."

        Design: Difficulty/boundary_precision_check/attendance_ratio_exactly_at_threshold_awards_ceu
        """
        reset_clock()
        scene = setup_census_locked_offering(num_learners=2)
        fail_seat = scene["seats"][1]
        record_attendance(fail_seat["registration_id"], 7, scene["instructor_id"])

        validate_error(
            api.award_completion(
                fail_seat["registration_id"], make_instructor_headers(scene["instructor_id"])
            ),
            ApiErrorId.ERR_ATTENDANCE_BELOW_THRESHOLD,
            422,
        )
        assert read_registration(fail_seat["registration_id"])["enrollment_status"] == "ENROLLED"
        _, meta = validate_paginated(
            api.list_completion_records(
                REGISTRAR, params={"registration_id": fail_seat["registration_id"]}
            )
        )
        assert meta["total_count"] == 0


class TestCeuLedgerConservation:
    """Award then revoke returns the learner's CEU total to exactly its prior value."""

    def test_award_raises_the_ceu_total_and_promotes_the_tier(self, api):
        """PRD 2.10: "A learner's `lifetime_ceu_total` always equals the sum of
        `ceu_awarded` across that learner's completion records whose `status` is
        `ISSUED`, rounded half up to one decimal place."
        PRD 3.7: "`loyalty_tier` follows from the count alone, evaluated from the top
        down: `CHAMPION` at 8 or more completions, otherwise `LOYAL` at 4 or more,
        otherwise `RETURNING` at 1 or more, otherwise `NEW`."

        Design: Difficulty/compensating_invariant/completion_award_then_revoke_conserves_learner_ceu_total
        """
        reset_clock()
        scene = setup_census_locked_offering(num_learners=1)
        seat = scene["seats"][0]
        before = read_learner(seat["learner_id"])
        assert before["lifetime_ceu_total"] == 0.0
        assert before["loyalty_tier"] == "NEW"

        record_attendance(seat["registration_id"], 10, scene["instructor_id"])
        api.award_completion(
            seat["registration_id"], make_instructor_headers(scene["instructor_id"])
        )

        after = read_learner(seat["learner_id"])
        assert after["lifetime_completed_count"] == 1
        assert after["lifetime_ceu_total"] == 1.2
        assert after["loyalty_tier"] == "RETURNING"

    def test_revocation_returns_the_ceu_total_to_zero_with_no_drift(self, api):
        """PRD 2.10: "Awarding a completion and then revoking it must therefore return
        `lifetime_ceu_total` to exactly its pre-award value, with zero drift."
        PRD 3.7: "On success the record moves `ISSUED → REVOKED`, the originating
        registration moves `COMPLETED → NO_SHOW` on its seat axis, and the learner's
        `lifetime_completed_count`, `lifetime_ceu_total` and `loyalty_tier` are
        recomputed by the same rule as above; because the record has left the issued
        input set, `lifetime_ceu_total` returns to exactly its pre-award value with no
        residual drift."

        Design: Difficulty/compensating_invariant/completion_award_then_revoke_conserves_learner_ceu_total
        """
        reset_clock()
        scene = setup_issued_completion()

        revoked = validate_success(
            api.revoke_completion_record(scene["record_id"], REGISTRAR)
        )
        assert revoked["status"] == "REVOKED"

        learner = read_learner(scene["learner_id"])
        assert learner["lifetime_ceu_total"] == 0.0, (
            f"Expected the CEU total back at 0.0, got {learner['lifetime_ceu_total']}"
        )
        assert learner["lifetime_completed_count"] == 0
        assert learner["loyalty_tier"] == "NEW"
        assert read_registration(scene["registration_id"])["enrollment_status"] == "NO_SHOW"

        states = memberships_by_segment(list_memberships(scene["learner_id"]))
        assert states.get("PROSPECT") == "ACTIVE"
        assert states.get("FIRST_TIME") == "REMOVED"


def test_certificate_numbers_follow_created_at_order(api):
    """PRD 3.7: "The certificate identifier is built to a fixed shape: the literal
    prefix `CEU`, then the section's `term_code`, then a sequence number, the three
    parts joined by hyphens."
    PRD 3.7: "The sequence is the one-based position of this record among that
    section's completion records ordered by `created_at` ascending, written with
    leading zeros to exactly four digits — so the first certificate issued on the
    autumn 2026 delivery reads `CEU-2026FA-0001` and the twelfth on a rolling section
    reads `CEU-ROLL-0012`."
    PRD 2.5: "It is also the source of `enrolled_at`, `issued_at`, `settled_at` and
    `recomputed_at`, and of `created_at` and `updated_at` on every resource."

    Design: Corner/calculations/certificate_number_sequence_follows_created_at_order
    """
    reset_clock()
    scene = setup_census_locked_offering(num_learners=2)
    for seat in scene["seats"]:
        record_attendance(seat["registration_id"], 10, scene["instructor_id"])

    first = validate_success(
        api.award_completion(
            scene["seats"][0]["registration_id"],
            make_instructor_headers(scene["instructor_id"]),
        ),
        201,
    )
    second = validate_success(
        api.award_completion(
            scene["seats"][1]["registration_id"],
            make_instructor_headers(scene["instructor_id"]),
        ),
        201,
    )
    assert_certificate_number(first, "2026FA", 1)
    assert_certificate_number(second, "2026FA", 2)
    assert first["issued_at"] == "2026-09-01T00:00:00.000Z", (
        f"issued_at is stamped from the logical clock, got {first['issued_at']}"
    )
    _, meta = validate_paginated(
        api.list_completion_records(
            REGISTRAR, params={"registration_id": scene["seats"][0]["registration_id"]}
        )
    )
    assert meta["total_count"] == 1


def test_second_revocation_of_the_same_record_returns_invalid_state(api):
    """PRD 3.7: "Revocation is the compensating action, and it belongs to the
    `Registrar`. It requires the record's `status` to be `ISSUED`, and it is blocked
    when any citation pointing at this record belongs to a credit-for-prior-learning
    petition whose `status` is `APPROVED` — the extension school will not pull the
    ground out from under credit it has already granted — in which case the answer is
    `ERR_CITATION_NOT_ELIGIBLE` (HTTP 422)."
    PRD 2.8: "From-state legality — the addressed resource sits in a state from which
    the requested transition is declared; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revoke_completion_record_twice_returns_invalid_state
    """
    reset_clock()
    scene = setup_issued_completion()
    validate_success(api.revoke_completion_record(scene["record_id"], REGISTRAR))

    validate_error(
        api.revoke_completion_record(scene["record_id"], REGISTRAR),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert read_record(scene["record_id"])["status"] == "REVOKED"
    learner = read_learner(scene["learner_id"])
    assert learner["lifetime_ceu_total"] == 0.0
    assert learner["lifetime_completed_count"] == 0
