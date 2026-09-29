"""The validation ladder read from both ends: rungs that refuse, and a request that clears them all."""
from test_helpers import (
    NON_EXISTENT_UUID,
    add_operating_room,
    add_segment,
    create_active_recipient,
    create_approved_donor,
    create_chain,
    create_finalized_watch_review,
    create_program,
    create_operating_room_payload,
    create_recipient,
    get_chain,
    get_donor,
    get_recipient,
    get_segment,
    refresh_program,
    setup_paired_loop_participants,
    setup_program_with_staff,
    setup_committed_paired_loop,
    setup_validated_paired_loop,
    update_recipient_status,
    validate_chain,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def _segments_of(env, chain_id):
    rows, meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain_id}
        )
    )
    return rows, meta


def test_a_missing_required_field_answers_before_an_unresolvable_body_key():
    """PRD §2.10: "Validation rules are evaluated strictly in ascending priority order,
    and the **first** rule violated determines the response."
    PRD §2.10: "Request shape, as specified in §2.6 — `ERR_VALIDATION`, 400."
    PRD §2.10: "Every foreign key supplied in the request body exists — the matching
    not-found code, 404."
    PRD §3.2: "A coordinator opens a recipient workup by supplying the owning
    `program_id`, the patient's `mrn`, an `abo_blood_type` of `O`, `A`, `B` or `AB`, an
    `age_years` value of at least 0, and a `cpra` calculated panel reactive antibody
    fraction between 0 and 1 inclusive."

    Design: Corner/validations/validation_body_shape_outranks_body_fk_returns_400
    """
    env = setup_program_with_staff()

    response = api_client.create_recipient_candidate(
        {
            "program_id": NON_EXISTENT_UUID,
            "mrn": "R-401",
            "abo_blood_type": "A",
            "age_years": 44,
        },
        env["coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    _rows, meta = validate_paginated(
        api_client.list_recipient_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused request created no candidacy"


def test_a_stale_chain_version_answers_before_the_repeated_participant():
    """PRD §2.10: "A request that breaks several rules always reports the lowest-numbered
    one."
    PRD §2.10: "`expected_chain_version` matches the chain's `version` on segment
    insertion, and `expected_review_version` matches the review's `version` on
    improvement-plan creation — `ERR_STALE_CHAIN_VERSION` or `ERR_STALE_REVIEW_VERSION`,
    412."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "Insertion recomputes the chain's `segment_count` and `is_closed_loop` and
    increments the chain's `version`, so any other client holding the previous value is
    immediately stale."

    Design: Corner/validations/validation_stale_chain_version_outranks_duplicate_participant_returns_412
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    stale_version = chain["version"]
    first_segment = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    after_insert = get_chain(env, chain["id"])
    assert after_insert["version"] > stale_version, "the insertion moved the version on"

    response = api_client.create_chain_segment(
        chain["id"],
        {
            "expected_chain_version": stale_version,
            "position": 2,
            "donor_candidate_id": env["donor_one"]["id"],
            "recipient_candidate_id": env["recipient_one"]["id"],
            "predecessor_segment_id": first_segment["id"],
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_CHAIN_VERSION.value, expected_status=412
    )

    _rows, meta = _segments_of(env, chain["id"])
    assert meta["total_count"] == 1, "the duplicate donor never reached the topology rung"

    final = get_chain(env, chain["id"])
    assert final["status"] == "DRAFT"
    assert final["segment_count"] == 1
    assert final["version"] == after_insert["version"], (
        "a refused write leaves the version untouched"
    )


def test_a_commitment_that_satisfies_every_rung_locks_both_donors():
    """PRD §3.6: "The program's posture must not be `FROZEN`, or the request is refused
    with `ERR_PROGRAM_FROZEN`; and if the posture is `RESTRICTED`, the chain's
    `segment_count` must be at most 2, or the request is refused with
    `ERR_PROGRAM_RESTRICTED`."
    PRD §3.6: "Every non-withdrawn segment's donor must still have `overall_status`
    `APPROVED` and every such segment's recipient must still be `ACTIVE`."
    PRD §3.6: "On success the chain moves to `COMMITTED`, `committed_at` is set to the
    current logical clock, `committed_donor_count` becomes the number of distinct donors
    on non-withdrawn segments, every one of those donors moves from `APPROVED` to
    `CHAIN_COMMITTED`, and the chain's `version` increments."
    PRD §3.6: "If any segment of the chain has already been offered, the chain's
    `total_planned_cit_minutes` must not exceed the chain-wide budget of 2,400 minutes —
    forty hours of accumulated cold time across the whole chain."

    Design: Corner/validations/commitment_satisfies_every_validation_rung
    """
    env = setup_validated_paired_loop()
    assert env["clock"] == "2026-08-08T00:00:00Z"
    assert refresh_program(env)["compliance_posture"] == "OPEN"
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"
    assert get_recipient(env, env["recipient_one"]["id"])["listing_status"] == "ACTIVE"
    assert get_recipient(env, env["recipient_two"]["id"])["listing_status"] == "ACTIVE"

    committed = validate_success(
        api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"])
    )

    assert committed["status"] == "COMMITTED"
    assert committed["committed_at"].startswith("2026-08-08T00:00:00")
    assert committed["committed_donor_count"] == 2
    assert committed["segment_count"] == 2
    assert committed["total_planned_cit_minutes"] == 0, "commitment plans nothing"

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "CHAIN_COMMITTED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "CHAIN_COMMITTED"
    assert get_segment(env, env["segment_one"]["id"])["status"] == "PLANNED"
    assert get_segment(env, env["segment_two"]["id"])["status"] == "PLANNED"
    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_equal_instants_are_accepted_where_an_earlier_one_is_refused():
    """PRD §3.2: "It must be at or after the `effective_at` of the candidate's most
    recent waitlist event — at the `WORKUP` starting point no event exists, so only the
    upper bound applies — and it must be at or before the current logical clock."
    PRD §3.2: "A value that precedes the latest event or lies in the clock's future is
    rejected with `ERR_EFFECTIVE_AT_OUT_OF_ORDER`."
    PRD §3.2: "Those half-open windows are then merged — overlapping or exactly touching
    windows become one, and a window that opens and closes at the same instant
    contributes nothing."
    PRD §3.2: "The operation both drives the candidate's `listing_status` and appends an
    immutable waitlist event recording the `recipient_candidate_id`, the `from_status` the
    candidate held, the `to_status` it moved to, the supplied `reason_code` and
    `effective_at`, and an `actor_user_id` taken from `X-User-ID`."

    Design: Corner/validations/status_update_effective_at_before_the_last_event_is_rejected
    """
    env = setup_program_with_staff()
    recipient = create_recipient(env, mrn="R-001")
    epoch = "2026-08-01T00:00:00Z"
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", epoch
    )
    update_recipient_status(env, recipient["id"], "ACTIVE", "LISTED", epoch)
    update_recipient_status(env, recipient["id"], "INACTIVE_HOLD", "MEDICALLY_UNFIT", epoch)
    relisted = update_recipient_status(env, recipient["id"], "ACTIVE", "RELISTED", epoch)
    assert relisted["listing_status"] == "ACTIVE", "equal instants are accepted"

    response = api_client.create_recipient_status_update(
        recipient["id"],
        {
            "to_status": "INACTIVE_HOLD",
            "reason_code": "MEDICALLY_UNFIT",
            "effective_at": "2026-07-31T23:59:59Z",
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_EFFECTIVE_AT_OUT_OF_ORDER.value, expected_status=422
    )

    after = get_recipient(env, recipient["id"])
    assert after["listing_status"] == "ACTIVE"
    assert after["active_days_total"] == 0, (
        "every window opened and closed at the same instant"
    )

    _events, meta = validate_paginated(
        api_client.list_waitlist_events(recipient["id"], env["coordinator_headers"])
    )
    assert meta["total_count"] == 4, "the refused update appended nothing"


def test_a_room_owned_by_another_program_cannot_be_booked():
    """PRD §2.5: "Once every reference resolves, they must all belong to the same
    program."
    PRD §2.5: "A single request may not mix a staff member, recipient, donor, chain,
    segment, room, review or claim drawn from two different transplant programs; such a
    request is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 422)."
    PRD §2.5: "This is checked on every write endpoint that accepts more than one foreign
    key."
    PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole
    minutes between `start_at` and `end_at`, its `cancel_reason_code` is null, and the
    room's `reserved_minutes_total` is incremented by that duration."

    Design: Corner/validations/booking_a_room_from_another_program_is_rejected
    """
    env = setup_committed_paired_loop()
    room_one = add_operating_room(env, "OR-1")
    add_operating_room(env, "OR-2")
    other_program = create_program(
        name="Southlake Transplant Center", center_code="STL-02"
    )
    foreign_room = validate_success(
        api_client.create_operating_room(
            create_operating_room_payload(other_program["id"], room_code="OR-9"),
            env["admin_headers"],
        ),
        expected_status=201,
    )
    body = {
        "chain_segment_id": env["segment_one"]["id"],
        "surgeon_staff_id": env["surgeon"]["id"],
        "booking_role": "DONOR_RECOVERY",
        "start_at": "2026-08-09T06:00:00Z",
        "end_at": "2026-08-09T10:00:00Z",
    }

    response = api_client.create_procedure_booking(
        {"operating_room_id": foreign_room["id"], **body}, env["coordinator_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE.value, expected_status=422
    )

    _rows, meta = validate_paginated(
        api_client.list_procedure_bookings(
            env["coordinator_headers"], params={"operating_room_id": foreign_room["id"]}
        )
    )
    assert meta["total_count"] == 0

    foreign_rooms = validate_success(
        api_client.list_program_operating_rooms(
            other_program["id"], env["admin_headers"]
        )
    )
    assert foreign_rooms[0]["reserved_minutes_total"] == 0

    accepted = validate_success(
        api_client.create_procedure_booking(
            {"operating_room_id": room_one["id"], **body}, env["coordinator_headers"]
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACTIVE", (
        "the identical body is accepted once the room belongs to the same program"
    )
    assert accepted["duration_minutes"] == 240


def test_a_restricted_posture_refuses_a_three_segment_commitment_without_suspending_it():
    """PRD §3.6: "The program's posture must not be `FROZEN`, or the request is refused
    with `ERR_PROGRAM_FROZEN`; and if the posture is `RESTRICTED`, the chain's
    `segment_count` must be at most 2, or the request is refused with
    `ERR_PROGRAM_RESTRICTED`."
    PRD §2.8: "Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count`
    is at least 2, the posture is `RESTRICTED`."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and
    `flag_level` is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it is
    strictly below 0.95 but not below 0.85, and `NONE` otherwise."
    PRD §3.8: "`requires_improvement_plan` is true exactly when `flag_level` is
    `FLAGGED`."
    PRD §2.8: "Moving between `OPEN` and `RESTRICTED` in either direction changes no
    chain."

    Design: Corner/validations/commitment_of_three_segment_chain_rejected_while_restricted
    """
    env = setup_program_with_staff()
    recipient_one = create_active_recipient(
        env, mrn="R-001", abo_blood_type="A", age_years=44
    )
    recipient_two = create_active_recipient(
        env, mrn="R-002", abo_blood_type="B", age_years=51
    )
    recipient_three = create_active_recipient(
        env, mrn="R-003", abo_blood_type="AB", age_years=47
    )
    donor_one = create_approved_donor(
        env, intended_recipient_id=recipient_one["id"], mrn="D-001", age_years=41
    )
    donor_two = create_approved_donor(
        env, intended_recipient_id=recipient_two["id"], mrn="D-002", age_years=38
    )
    donor_three = create_approved_donor(
        env, intended_recipient_id=recipient_three["id"], mrn="D-003", age_years=45
    )
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(env, chain["id"], 1, donor_one["id"], recipient_two["id"])
    second = add_segment(
        env,
        chain["id"],
        2,
        donor_two["id"],
        recipient_three["id"],
        predecessor_segment_id=first["id"],
    )
    add_segment(
        env,
        chain["id"],
        3,
        donor_three["id"],
        recipient_one["id"],
        predecessor_segment_id=second["id"],
    )
    validated = validate_chain(env, chain["id"])
    assert validated["status"] == "VALIDATED"
    assert validated["segment_count"] == 3
    assert validated["is_closed_loop"] is True
    review = create_finalized_watch_review(
        env, cohort_size=25, observed_survivor_count=17
    )

    response = api_client.commit_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_PROGRAM_RESTRICTED.value, expected_status=409
    )

    program = refresh_program(env)
    assert program["compliance_posture"] == "RESTRICTED"
    assert program["follow_up_compliance_pct"] == 100.0, "the vacuous figure"
    assert program["cit_breach_count"] == 0, "the watch review is the only cause"

    assert review["flag_level"] == "WATCH"
    assert review["oe_ratio"] == 0.85, "17 observed against 20.0 expected"
    assert review["requires_improvement_plan"] is False

    after = get_chain(env, chain["id"])
    assert after["status"] == "VALIDATED", "RESTRICTED does not suspend chains"
    assert after["committed_donor_count"] == 0
    assert after["committed_at"] is None
    for donor in (donor_one, donor_two, donor_three):
        assert get_donor(env, donor["id"])["overall_status"] == "APPROVED"
