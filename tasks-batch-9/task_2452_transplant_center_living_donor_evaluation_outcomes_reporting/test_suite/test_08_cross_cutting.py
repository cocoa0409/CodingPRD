"""Where concurrency, cascades, dual variants and counting thresholds meet in one request."""
from test_helpers import (
    accept_offer,
    add_operating_room,
    advance_clock,
    book_theatre,
    complete_transplant,
    create_chain,
    create_offer_payload,
    add_segment,
    get_chain,
    get_donor,
    get_segment,
    list_donor_follow_ups,
    refresh_program,
    send_offer,
    setup_accepted_segment,
    setup_committed_paired_loop,
    setup_paired_loop_participants,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def test_a_fresh_chain_version_is_accepted_and_bumps_by_exactly_one():
    """PRD §2.7: "Inserting a segment into a chain — `POST /exchange-chains/{id}/segments`
    — requires a non-optional `expected_chain_version` field carrying the client's last
    observed `version` of the target `ExchangeChain`."
    PRD §2.7: "A successful insertion increments the chain's `version`, which makes any
    other holder of the previous value stale."
    PRD §3.5: "Insertion recomputes the chain's `segment_count` and `is_closed_loop` and
    increments the chain's `version`, so any other client holding the previous value is
    immediately stale."
    PRD §3.5: "Insertion deliberately does **not** check the chain's shape."
    PRD §3.5: "The new segment starts in `PLANNED` with every offer and planning field
    null."

    Design: Corner/cross_cutting_complexity_layers/fresh_chain_version_write_succeeds_and_bumps_by_exactly_one
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    version_zero = chain["version"]
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    version_one = get_chain(env, chain["id"])["version"]
    assert version_one == version_zero + 1, "one accepted child write, one bump"

    inserted = validate_success(
        api_client.create_chain_segment(
            chain["id"],
            {
                "expected_chain_version": version_one,
                "position": 2,
                "donor_candidate_id": env["donor_two"]["id"],
                "recipient_candidate_id": env["recipient_one"]["id"],
                "predecessor_segment_id": first["id"],
            },
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert inserted["position"] == 2
    assert inserted["predecessor_segment_id"] == first["id"]
    assert inserted["status"] == "PLANNED"
    assert inserted["planned_cit_minutes"] is None

    after = get_chain(env, chain["id"])
    assert after["version"] == version_one + 1, "not two, and not one per segment"
    assert after["segment_count"] == 2
    assert after["status"] == "DRAFT", "adding segments never validates"

    _rows, meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_one_completion_fires_three_dependent_cascade_hops():
    """PRD §3.7: "The segment's donor moves from `CHAIN_COMMITTED` to `DONATED` with
    `donated_at` set to the current logical clock; because the donor has now donated, three
    follow-up rows are created for that donor, each in `DUE` status, with `interval_code`
    values of `SIX_MONTH`, `ONE_YEAR` and `TWO_YEAR` and `due_on` values of `donated_at`
    plus 180, 365 and 730 days respectively; and because those rows now exist, the
    program's `follow_up_compliance_pct` is recomputed and `compliance_posture`
    re-derived."
    PRD §3.7: "Each interval has a fixed required field count: a `SIX_MONTH` interval
    requires 12 fields, a `ONE_YEAR` interval requires 14, and a `TWO_YEAR` interval
    requires 10, and that number is stored as `required_fields_count`."
    PRD §3.7: "Every procedure booking of this segment whose status is `ACTIVE` moves to
    `COMPLETED`, and the room's `reserved_minutes_total` is left unchanged, because
    completed bookings stay in the ledger."
    PRD §3.7: "The segment's recipient moves from `ACTIVE` to `TRANSPLANTED` with a
    waitlist event appended as described in §3.2."
    PRD §3.7: "And the parent chain moves from `COMMITTED` to `EXECUTING` on the first
    completion, or from `EXECUTING` to `COMPLETED` when the count of non-withdrawn segments
    at `TRANSPLANTED` has reached the chain's `segment_count`; a chain reaching `COMPLETED`
    zeroes its `committed_donor_count`."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program
    with three future-dated rows reports the vacuous 100.00 rather than 0.00."

    Design: Corner/cross_cutting_complexity_layers/one_completion_fires_three_dependent_cascade_hops
    """
    env = setup_accepted_segment()
    assert env["clock"] == "2026-08-09T06:00:00Z"
    bookings = env["segment_one_bookings"]
    recovery_id = bookings["donor_recovery"]["id"]
    implant_id = bookings["recipient_implant"]["id"]

    completed = complete_transplant(
        env, env["segment_one"]["id"], "2026-08-09T07:05:00Z", "2026-08-09T13:00:00Z"
    )

    assert completed["status"] == "TRANSPLANTED"
    assert completed["actual_cit_minutes"] == 355
    assert completed["cit_breach"] is False

    donor = get_donor(env, env["donor_one"]["id"])
    assert donor["overall_status"] == "DONATED", "hop 1"
    assert donor["donated_at"].startswith("2026-08-09T06:00:00")

    rows, meta = validate_paginated(
        api_client.list_donor_follow_ups(donor["id"], env["coordinator_headers"])
    )
    assert meta["total_count"] == 3, "hop 2 could not run before hop 1"
    assert {row["status"] for row in rows} == {"DUE"}
    by_interval = {row["interval_code"]: row for row in rows}
    assert by_interval["SIX_MONTH"]["due_on"].startswith("2027-02-05T06:00:00")
    assert by_interval["ONE_YEAR"]["due_on"].startswith("2027-08-09T06:00:00")
    assert by_interval["TWO_YEAR"]["due_on"].startswith("2028-08-08T06:00:00")
    assert by_interval["SIX_MONTH"]["required_fields_count"] == 12
    assert by_interval["ONE_YEAR"]["required_fields_count"] == 14
    assert by_interval["TWO_YEAR"]["required_fields_count"] == 10

    program = refresh_program(env)
    assert program["follow_up_compliance_pct"] == 100.0, "hop 3, on future-dated rows"
    assert program["compliance_posture"] == "OPEN"

    assert validate_success(
        api_client.get_procedure_booking(recovery_id, env["coordinator_headers"])
    )["status"] == "COMPLETED"
    assert validate_success(
        api_client.get_procedure_booking(implant_id, env["coordinator_headers"])
    )["status"] == "COMPLETED"
    rooms = validate_success(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    reserved = {room["room_code"]: room["reserved_minutes_total"] for room in rooms}
    assert reserved["OR-1"] == 240, "completion does not release the ledger"

    recipient = validate_success(
        api_client.get_recipient_candidate(
            env["recipient_two"]["id"], env["coordinator_headers"]
        )
    )
    assert recipient["listing_status"] == "TRANSPLANTED"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "EXECUTING"
    assert chain["committed_donor_count"] == 2


def test_the_same_span_is_refused_as_a_plan_and_accepted_as_the_realized_interval():
    """PRD §3.6: "`planned_cit_minutes` is computed when the offer is sent: it is the
    whole minutes between `planned_cross_clamp_at` and `planned_reperfusion_at`, truncated
    toward zero, plus a fixed forty-five-minute allowance for the final cross-match hold."
    PRD §3.6: "`actual_cit_minutes`, by contrast, is computed at completion as simply the
    whole minutes between `actual_cross_clamp_at` and `actual_reperfusion_at`, truncated
    toward zero, with no allowance added, because the realized interval already contains
    whatever hold actually occurred."
    PRD §3.6: "Both figures are compared against the same per-segment ceiling of 1,080
    minutes — eighteen hours — which means an identical clamp-to-reperfusion span can pass
    as an actual figure and fail as a planned one."
    PRD §3.6: "A planned figure of exactly 1,080 is accepted; 1,081 is refused with
    `ERR_CIT_LIMIT_EXCEEDED`."
    PRD §3.6: "`total_planned_cit_minutes` on a chain is the sum of `planned_cit_minutes`
    over that chain's segments whose status is `OFFER_SENT`, `ACCEPTED` or `TRANSPLANTED`,
    accumulated in `position` ascending and, for ties, `created_at` ascending order."

    Design: Corner/cross_cutting_complexity_layers/same_span_is_rejected_as_planned_and_accepted_as_actual
    """
    env = setup_committed_paired_loop()
    room_one = add_operating_room(env, "OR-1")
    room_two = add_operating_room(env, "OR-2")
    segment_id = env["segment_one"]["id"]
    book_theatre(
        env,
        room_one["id"],
        segment_id,
        "DONOR_RECOVERY",
        "2026-08-09T05:00:00Z",
        "2026-08-09T07:00:00Z",
    )
    book_theatre(
        env,
        room_two["id"],
        segment_id,
        "RECIPIENT_IMPLANT",
        "2026-08-09T22:00:00Z",
        "2026-08-10T02:00:00Z",
    )
    advance_clock(env, "2026-08-09T04:00:00Z")

    refused = api_client.send_segment_offer(
        segment_id,
        create_offer_payload("2026-08-09T06:00:00Z", "2026-08-09T23:16:00Z"),
        env["coordinator_headers"],
    )
    validate_error(
        refused, ApiErrorId.ERR_CIT_LIMIT_EXCEEDED.value, expected_status=422
    )
    unplanned = get_segment(env, segment_id)
    assert unplanned["status"] == "PLANNED"
    assert unplanned["planned_cit_minutes"] is None, "1036 plus the hold is 1081"

    offered = send_offer(env, segment_id, "2026-08-09T06:00:00Z", "2026-08-09T23:15:00Z")
    assert offered["planned_cit_minutes"] == 1080, "1035 plus the hold is exactly the cap"
    accept_offer(env, segment_id)
    advance_clock(env, "2026-08-10T02:00:00Z")

    completed = complete_transplant(
        env, segment_id, "2026-08-09T06:00:00Z", "2026-08-09T23:16:00Z"
    )

    assert completed["status"] == "TRANSPLANTED"
    assert completed["actual_cit_minutes"] == 1036, "the very span refused as a plan"
    assert completed["cit_breach"] is False
    assert completed["planned_cit_minutes"] == 1080, "the accepted plan is not restated"

    program = refresh_program(env)
    assert program["cit_breach_count"] == 0
    assert program["compliance_posture"] == "OPEN"
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 1080


def test_the_second_breach_and_not_the_first_crosses_into_restricted():
    """PRD §3.7: "When `cit_breach` came out true, the program's `cit_breach_count`
    increases by 1 and `compliance_posture` is re-derived again — two breaches are enough
    to restrict the program."
    PRD §2.8: "A `cit_breach_count` of 1 keeps the program `OPEN`; 2 degrades it to
    `RESTRICTED`."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`.
    Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count` is
    at least 2, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."
    PRD §3.7: "And the parent chain moves from `COMMITTED` to `EXECUTING` on the first
    completion, or from `EXECUTING` to `COMPLETED` when the count of non-withdrawn segments
    at `TRANSPLANTED` has reached the chain's `segment_count`; a chain reaching `COMPLETED`
    zeroes its `committed_donor_count`."
    PRD §3.6: "A total of exactly 2,400 minutes is accepted; 2,401 is refused with
    `ERR_CHAIN_CIT_BUDGET_EXCEEDED`."

    Design: Corner/cross_cutting_complexity_layers/second_cit_breach_crosses_the_rate_threshold_into_restricted
    """
    env = setup_committed_paired_loop()
    room_one = add_operating_room(env, "OR-1")
    room_two = add_operating_room(env, "OR-2")
    segment_one_id = env["segment_one"]["id"]
    segment_two_id = env["segment_two"]["id"]
    for segment_id, day in ((segment_one_id, "2026-08-09"), (segment_two_id, "2026-08-11")):
        book_theatre(
            env, room_one["id"], segment_id, "DONOR_RECOVERY",
            f"{day}T05:00:00Z", f"{day}T07:00:00Z",
        )
    book_theatre(
        env, room_two["id"], segment_one_id, "RECIPIENT_IMPLANT",
        "2026-08-09T22:00:00Z", "2026-08-10T02:00:00Z",
    )
    book_theatre(
        env, room_two["id"], segment_two_id, "RECIPIENT_IMPLANT",
        "2026-08-11T22:00:00Z", "2026-08-12T02:00:00Z",
    )
    advance_clock(env, "2026-08-09T04:00:00Z")
    first_offer = send_offer(
        env, segment_one_id, "2026-08-09T06:00:00Z", "2026-08-09T23:15:00Z"
    )
    assert first_offer["planned_cit_minutes"] == 1080
    accept_offer(env, segment_one_id)
    advance_clock(env, "2026-08-10T02:00:00Z")
    first_completion = complete_transplant(
        env, segment_one_id, "2026-08-09T06:00:00Z", "2026-08-10T00:05:30Z"
    )
    assert first_completion["cit_breach"] is True
    after_first = refresh_program(env)
    assert after_first["cit_breach_count"] == 1
    assert after_first["compliance_posture"] == "OPEN", "one breach is tolerated"
    advance_clock(env, "2026-08-11T04:00:00Z")
    second_offer = send_offer(
        env, segment_two_id, "2026-08-11T06:00:00Z", "2026-08-11T23:15:00Z"
    )
    assert second_offer["planned_cit_minutes"] == 1080
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 2160
    accept_offer(env, segment_two_id)
    advance_clock(env, "2026-08-12T02:00:00Z")

    completed = complete_transplant(
        env, segment_two_id, "2026-08-11T06:00:00Z", "2026-08-12T00:05:30Z"
    )

    assert completed["status"] == "TRANSPLANTED"
    assert completed["actual_cit_minutes"] == 1085
    assert completed["cit_breach"] is True

    program = refresh_program(env)
    assert program["cit_breach_count"] == 2
    assert program["compliance_posture"] == "RESTRICTED"
    assert program["follow_up_compliance_pct"] == 100.0, "the counter is the sole cause"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "COMPLETED"
    assert chain["committed_donor_count"] == 0
    assert chain["total_planned_cit_minutes"] == 2160

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "DONATED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "DONATED"
    assert len(list_donor_follow_ups(env, env["donor_two"]["id"])) == 3
