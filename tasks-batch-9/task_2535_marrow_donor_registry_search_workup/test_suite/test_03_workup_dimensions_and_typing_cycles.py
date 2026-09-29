"""Non-linear state walks: the workup case's two dimensions and the typing cycle.

A `WorkupCase` carries a clinical dimension (`clearance_status`) and an
operational one (`logistics_status`) on the same row, and they advance
independently — including a backwards edge from `BOOKED` to `METHOD_SET`.  A
`MatchCandidate` walks a genuine cycle
`TYPING_REQUESTED -> TYPING_EXPIRED -> TYPING_REQUESTED`, where the same
deadline sweep lands on two different destinations depending on how many
confirmatory-typing attempts the candidate has already consumed.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    constants as C,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# Clearance is resulted here so the infectious-disease panel's thirty-day
# validity covers every collection date the conditioning window admits.
CLEARANCE_AT = "2026-09-13T08:00:00Z"
FIRST_BOOKING_START_AT = "2026-10-11T08:00:00Z"
REPLACEMENT_BOOKING_START_AT = "2026-10-12T08:00:00Z"

# The confirmatory-typing cycle's instants: the registry's contractual
# `ct_response_deadline_hours` is 168, so a request raised at the clock's
# mandated default falls due a week later.
FIRST_DEADLINE_AT = "2026-08-08T00:00:00Z"
FIRST_EXPIRY_SWEEP_AT = "2026-08-08T00:00:01Z"
SECOND_DEADLINE_AT = "2026-08-15T00:00:01Z"
SECOND_EXPIRY_SWEEP_AT = "2026-08-16T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC instant so instants compare exactly, to the second."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _typing_requests(api, ctx, candidate_id):
    """The candidate's confirmatory-typing requests, keyed by `attempt_number`."""
    rows, _meta = validate_paginated(
        api.list_typing_requests(
            candidate_id, ctx["coordinator_headers"], params={"limit": 100}
        )
    )
    return {row["attempt_number"]: row for row in rows}


def test_method_decision_moves_logistics_while_clearance_ladder_runs_separately(api):
    """PRD §3.6: "The workup case records its `match_candidate_id`, stamps `opened_by_user_id` from `X-User-ID`, and opens with `case_status` `OPEN`, `clearance_status` `PENDING`, `logistics_status` `UNSCHEDULED`, `collection_method` null, `method_decided_by_user_id` null, `physical_cleared_by_user_id` null, `idm_resulted_at` null and `abort_reason` null."
    PRD §3.6: "Its `planned_window_days` starts at 6, which is the planning default used while no method has been chosen."
    PRD §3.6: "The two dimensions evolve independently of one another until booking creation couples them by demanding that clearance be complete; a `MedicalDirector` can perfectly well decide the method while clearance is still `IN_PROGRESS`."
    PRD §3.6: "The decision stores `collection_method` and stamps `method_decided_by_user_id` from `X-User-ID`, moves the case `UNSCHEDULED → METHOD_SET` on its logistics dimension, sets `planned_window_days` to 6 for `PBSC` or 8 for `MARROW`, and increments the case's `version` by one — which matters immediately, because that version is what the next booking attempt must quote."
    PRD §3.6: "The first passing result moves the case `PENDING → IN_PROGRESS`."
    PRD §3.6: "A passing result on the last item still pending, with the other two already carrying `PASS`, moves the case `IN_PROGRESS → CLEARED`."

    Design: Difficulty/non_linear_state_machine/workup_case_clearance_and_logistics_dimensions_advance_independently
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1)
    opened = ctx["workup_case"]
    assert opened["case_status"] == "OPEN", opened
    assert opened["clearance_status"] == "PENDING", (
        f"a freshly opened case starts PENDING on its clinical dimension, got "
        f"{opened['clearance_status']}"
    )
    assert opened["logistics_status"] == "UNSCHEDULED", (
        f"a freshly opened case starts UNSCHEDULED on its operational dimension, got "
        f"{opened['logistics_status']}"
    )
    assert opened["collection_method"] is None, opened["collection_method"]
    assert opened["planned_window_days"] == 6, opened["planned_window_days"]

    # The method decision is taken while no clearance item has been resulted at all.
    decided = validate_success(
        api.decide_collection_method(
            ctx["workup_case_id"],
            f.collection_method_payload(method="PBSC"),
            ctx["second_physician_headers"],
        )
    )
    assert decided["collection_method"] == "PBSC", decided["collection_method"]
    assert decided["logistics_status"] == "METHOD_SET", (
        f"the method decision moves only the logistics dimension, got "
        f"{decided['logistics_status']}"
    )
    assert decided["clearance_status"] == "PENDING", (
        f"the clinical dimension is untouched by the method decision, got "
        f"{decided['clearance_status']}"
    )
    assert decided["planned_window_days"] == 6, decided["planned_window_days"]
    assert decided["version"] == opened["version"] + 1, (
        f"the method decision increments the case version by one: expected "
        f"{opened['version'] + 1}, got {decided['version']}"
    )

    fixtures.set_clock(CLEARANCE_AT)
    items = fixtures.find_clearance_items(ctx["workup_case_id"], ctx["physician_headers"])

    validate_success(
        api.record_clearance_result(
            items["PHYSICAL_EXAM"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        )
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["clearance_status"] == "IN_PROGRESS", case["clearance_status"]
    assert case["logistics_status"] == "METHOD_SET", (
        f"the first passing clearance result leaves the logistics dimension alone, got "
        f"{case['logistics_status']}"
    )

    validate_success(
        api.record_clearance_result(
            items["IDM_PANEL"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        )
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["clearance_status"] == "IN_PROGRESS", case["clearance_status"]
    assert case["logistics_status"] == "METHOD_SET", case["logistics_status"]

    validate_success(
        api.record_clearance_result(
            items["CONSENT"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        )
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["clearance_status"] == "CLEARED", (
        f"the last pending item's PASS clears the clinical dimension, got "
        f"{case['clearance_status']}"
    )
    assert case["logistics_status"] == "METHOD_SET", (
        f"the clinical dimension reaching CLEARED does not advance logistics, got "
        f"{case['logistics_status']}"
    )
    assert case["case_status"] == "OPEN", case["case_status"]


def test_cancelling_the_confirmed_booking_reverts_logistics_and_the_case_rebooks(api):
    """PRD §3.7: "Creating it adds its `duration_minutes` to the centre's `committed_slot_minutes`, moves the case `METHOD_SET → BOOKED` on the logistics dimension, and increments the case's `version` by one."
    PRD §3.7: "Whether the booking had been confirmed matters for the money: cancelling from `HELD → CANCELLED` leaves `cancelled_after_confirmation` false and costs the programme nothing, whereas cancelling from `CONFIRMED → CANCELLED` sets `cancelled_after_confirmation` true, which adds a cancellation line to the case's final claim."
    PRD §3.7: "Finally, if the case is left with no booking in `HELD` or `CONFIRMED` status, the case's logistics dimension reverts `BOOKED → METHOD_SET` while its clearance dimension is untouched — the case is bookable again without redoing any clinical work."
    PRD §3.7: "From the method it derives `duration_minutes` — 300 minutes for `PBSC`, 240 minutes for `MARROW` — then `end_at` as `start_at` advanced by that many minutes, and `collection_date` as the UTC calendar date of `start_at`."

    Design: Difficulty/non_linear_state_machine/workup_case_clearance_and_logistics_dimensions_advance_independently
    """
    ctx = fixtures.setup_primary_candidate(num_donors=1)
    fixtures.engage_candidate(ctx)
    fixtures.advance_to_workup_open(ctx)
    fixtures.advance_to_cleared(ctx, clearance_at=CLEARANCE_AT)
    fixtures.advance_to_method_set(ctx, method="PBSC")
    fixtures.advance_to_conditioning_scheduled(ctx)
    first_booking = fixtures.advance_to_booking_held(
        ctx, start_at=FIRST_BOOKING_START_AT
    )
    assert first_booking["status"] == "HELD", first_booking["status"]
    booked = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert booked["logistics_status"] == "BOOKED", booked["logistics_status"]

    fixtures.advance_to_booking_confirmed(ctx)
    confirmed_case = fixtures.read_workup_case(
        ctx["workup_case_id"], ctx["coordinator_headers"]
    )
    assert confirmed_case["logistics_status"] == "BOOKED", (
        f"confirming a held slot is a booking-only transition and leaves the case's "
        f"logistics dimension at BOOKED, got {confirmed_case['logistics_status']}"
    )

    cancelled = validate_success(
        api.cancel_collection_booking(
            ctx["booking_id"],
            f.cancel_booking_payload(reason="Apheresis machine offline for maintenance"),
            ctx["center_ops_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert cancelled["cancel_reason"] == "Apheresis machine offline for maintenance", (
        f"cancellation records the supplied reason, got {cancelled['cancel_reason']!r}"
    )
    assert cancelled["cancelled_after_confirmation"] is True, (
        "cancelling from CONFIRMED sets cancelled_after_confirmation true, got "
        f"{cancelled['cancelled_after_confirmation']!r}"
    )

    reverted = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert reverted["logistics_status"] == "METHOD_SET", (
        f"losing its last live booking drives the case backwards BOOKED → METHOD_SET, got "
        f"{reverted['logistics_status']}"
    )
    assert reverted["clearance_status"] == "CLEARED", (
        f"the clinical dimension is untouched by the cancellation, got "
        f"{reverted['clearance_status']}"
    )
    assert reverted["case_status"] == "OPEN", reverted["case_status"]

    # The case is bookable again without redoing any clinical work.
    replacement = validate_success(
        api.create_collection_booking(
            f.create_booking_payload(
                ctx["workup_case_id"],
                ctx["center_id"],
                REPLACEMENT_BOOKING_START_AT,
                reverted["version"],
            ),
            ctx["center_ops_headers"],
        ),
        201,
    )
    assert replacement["status"] == "HELD", replacement["status"]
    assert replacement["collection_date"] == "2026-10-12", (
        f"collection_date is the UTC calendar date of start_at, got "
        f"{replacement['collection_date']!r}"
    )
    rebooked = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert rebooked["logistics_status"] == "BOOKED", (
        f"the replacement booking re-enters BOOKED, got {rebooked['logistics_status']}"
    )


def test_typing_request_expires_only_past_its_frozen_deadline_and_candidate_recycles(api):
    """PRD §3.4: "It begins at `requested_at` plus the donor registry's contractual `ct_response_deadline_hours`."
    PRD §3.4: "When the donor's registry has `is_domestic` false, a further 48 hours of grace — two full days — are added, in recognition of the time zones and translation involved in international coordination."
    PRD §3.4: "When `priority_flag` is true, 24 hours are subtracted."
    PRD §3.4: "A sweep that lands at exactly the deadline instant expires nothing; a sweep one second later expires it."
    PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep instant, whether or not anything expired."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."
    PRD §3.4: "The created request records `match_candidate_id`, an `attempt_number` equal to the candidate's `ct_attempt_count` after the increment — so 1 or 2 — a `requested_at` stamped from the logical clock, and a computed `deadline_at`."

    Design: Difficulty/non_linear_state_machine/match_candidate_cycles_typing_expired_twice_before_terminal_exclusion
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2, with_center=False)
    candidate_id = ctx["candidate_id"]

    first = validate_success(
        api.create_typing_request(
            candidate_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
        ),
        201,
    )
    assert first["attempt_number"] == 1, first["attempt_number"]
    assert first["status"] == "REQUESTED", first["status"]
    assert _instant(first["requested_at"]) == _instant(C.CLOCK_EPOCH), (
        f"requested_at is stamped from the logical clock, got {first['requested_at']!r}"
    )
    assert _instant(first["deadline_at"]) == _instant(FIRST_DEADLINE_AT), (
        f"a domestic, non-priority request due 168 contractual hours after "
        f"{C.CLOCK_EPOCH} falls due at {FIRST_DEADLINE_AT}, got {first['deadline_at']!r}"
    )
    candidate = fixtures.read_candidate(candidate_id, ctx["coordinator_headers"])
    assert candidate["status"] == "TYPING_REQUESTED", candidate["status"]
    assert candidate["ct_attempt_count"] == 1, candidate["ct_attempt_count"]

    # A sweep landing exactly on the frozen deadline expires nothing at all.
    fixtures.set_clock(FIRST_DEADLINE_AT)
    validate_success(
        api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"])
    )
    on_deadline = _typing_requests(api, ctx, candidate_id)[1]
    assert on_deadline["status"] == "REQUESTED", (
        f"only a deadline strictly before the sweep instant expires, got "
        f"{on_deadline['status']}"
    )
    assert on_deadline["expired_by_sweep_at"] is None, on_deadline["expired_by_sweep_at"]
    assert (
        fixtures.read_candidate(candidate_id, ctx["coordinator_headers"])["status"]
        == "TYPING_REQUESTED"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert _instant(search["last_sweep_at"]) == _instant(FIRST_DEADLINE_AT), (
        f"every sweep stamps last_sweep_at whether or not anything expired, got "
        f"{search['last_sweep_at']!r}"
    )

    # One second later the very same sweep expires it.
    fixtures.set_clock(FIRST_EXPIRY_SWEEP_AT)
    validate_success(
        api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"])
    )
    expired = _typing_requests(api, ctx, candidate_id)[1]
    assert expired["status"] == "EXPIRED", expired["status"]
    assert _instant(expired["expired_by_sweep_at"]) == _instant(FIRST_EXPIRY_SWEEP_AT), (
        f"expired_by_sweep_at carries the sweep instant, got "
        f"{expired['expired_by_sweep_at']!r}"
    )
    candidate = fixtures.read_candidate(candidate_id, ctx["coordinator_headers"])
    assert candidate["status"] == "TYPING_EXPIRED", candidate["status"]
    assert candidate["ct_attempt_count"] == 1, candidate["ct_attempt_count"]
    assert candidate["candidate_role"] == "PRIMARY", (
        f"a first expiry at one consumed attempt leaves the primary in place, got "
        f"{candidate['candidate_role']}"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert _instant(search["last_sweep_at"]) == _instant(FIRST_EXPIRY_SWEEP_AT)

    # The candidate re-enters the cycle on its second and last attempt.
    second = validate_success(
        api.create_typing_request(
            candidate_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
        ),
        201,
    )
    assert second["attempt_number"] == 2, second["attempt_number"]
    assert _instant(second["deadline_at"]) == _instant(SECOND_DEADLINE_AT), (
        f"the second request's deadline is frozen 168 hours after its own "
        f"requested_at, got {second['deadline_at']!r}"
    )
    candidate = fixtures.read_candidate(candidate_id, ctx["coordinator_headers"])
    assert candidate["status"] == "TYPING_REQUESTED", (
        f"TYPING_EXPIRED → TYPING_REQUESTED closes the cycle, got {candidate['status']}"
    )
    assert candidate["ct_attempt_count"] == 2, candidate["ct_attempt_count"]


def _consume_both_typing_attempts(api, ctx, candidate_id):
    """Raise, expire and re-raise the candidate's confirmatory typing request.

    On return the candidate sits in TYPING_REQUESTED with `ct_attempt_count` 2 and
    its second request is open with a deadline of SECOND_DEADLINE_AT.
    """
    validate_success(
        api.create_typing_request(
            candidate_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
        ),
        201,
    )
    fixtures.set_clock(FIRST_EXPIRY_SWEEP_AT)
    validate_success(api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"]))
    return validate_success(
        api.create_typing_request(
            candidate_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
        ),
        201,
    )


def test_second_expiry_of_the_primary_excludes_it_and_promotes_the_rank_two_backup(api):
    """PRD §3.4: "If that candidate is the `PRIMARY` and its `ct_attempt_count` has already reached two, the candidate is additionally moved `TYPING_EXPIRED → EXCLUDED` and the promotion cascade runs."
    PRD §3.5: "Of the promotable ones, the candidate holding the smallest `rank_position` is lifted to `candidate_role` `PRIMARY`, and its `promoted_from_rank` records the `rank_position` it held when it was promoted."
    PRD §3.5: "The outgoing primary's `candidate_role` becomes `ARCHIVED_POOL`."
    PRD §3.3: "Because ranking is a one-time act, `rank_position` is frozen at materialisation and is never recomputed afterwards — not when a donor is deferred, not when a backup is promoted, not when the pool shrinks."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that search's candidates whose `candidate_role` is `BACKUP` and whose `status` is one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or `SCREENING_PASSED`."
    PRD §3.4: "After processing, if the search has no candidate in the `PRIMARY` role sitting in a non-terminal status and no promotable backup remains — its `backup_candidate_count` having fallen to zero — the search moves to `STALLED`."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with `ct_attempt_count` at zero, and carries `confirmed_score`, `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and `promoted_from_rank` all null."

    Design: Difficulty/non_linear_state_machine/match_candidate_cycles_typing_expired_twice_before_terminal_exclusion
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2, with_center=False)
    primary_id = fixtures.candidate_by_rank(ctx, 1)["id"]
    backup_id = fixtures.candidate_by_rank(ctx, 2)["id"]
    second_request = _consume_both_typing_attempts(api, ctx, primary_id)

    fixtures.set_clock(SECOND_EXPIRY_SWEEP_AT)
    validate_success(api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"]))

    expired = _typing_requests(api, ctx, primary_id)[2]
    assert expired["id"] == second_request["id"]
    assert expired["status"] == "EXPIRED", expired["status"]

    outgoing = fixtures.read_candidate(primary_id, ctx["coordinator_headers"])
    assert outgoing["status"] == "EXCLUDED", (
        f"a primary whose second attempt expires is excluded outright rather than "
        f"resting in TYPING_EXPIRED, got {outgoing['status']}"
    )
    assert outgoing["ct_attempt_count"] == 2, outgoing["ct_attempt_count"]
    assert outgoing["candidate_role"] == "ARCHIVED_POOL", (
        f"the outgoing primary is archived by the promotion cascade, got "
        f"{outgoing['candidate_role']}"
    )
    assert outgoing["confirmed_score"] is None, (
        f"no typing response was ever filed, so confirmed_score stays null, got "
        f"{outgoing['confirmed_score']!r}"
    )

    promoted = fixtures.read_candidate(backup_id, ctx["coordinator_headers"])
    assert promoted["candidate_role"] == "PRIMARY", (
        f"the promotable backup holding the smallest rank_position is lifted to "
        f"PRIMARY, got {promoted['candidate_role']}"
    )
    assert promoted["promoted_from_rank"] == 2, (
        f"promoted_from_rank records the rank_position held at promotion, got "
        f"{promoted['promoted_from_rank']!r}"
    )
    assert promoted["rank_position"] == 2, (
        f"rank_position is frozen at materialisation and is never recomputed, got "
        f"{promoted['rank_position']}"
    )
    assert promoted["status"] == "IDENTIFIED", promoted["status"]

    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["backup_candidate_count"] == 0, (
        f"the promoted candidate no longer counts as a backup, got "
        f"{search['backup_candidate_count']}"
    )
    assert search["status"] != "STALLED", (
        "a search still holding a PRIMARY in a non-terminal status is not stalled, got "
        f"{search['status']}"
    )


def test_backup_at_two_attempts_rests_in_typing_expired_and_a_third_request_is_refused(api):
    """PRD §3.4: "An expiring request moves `REQUESTED → EXPIRED`, has `expired_by_sweep_at` stamped with the sweep instant, and drags its candidate `TYPING_REQUESTED → TYPING_EXPIRED`."
    PRD §3.4: "A `BACKUP` candidate at two attempts is deliberately *not* auto-excluded: it rests in `TYPING_EXPIRED`, which is precisely how a later third request against it becomes reachable and is refused with `ERR_CT_ATTEMPTS_EXHAUSTED`."
    PRD §3.4: "A third request against the same candidate is refused with `ERR_CT_ATTEMPTS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/match_candidate_cycles_typing_expired_twice_before_terminal_exclusion
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2, with_center=False)
    backup_id = fixtures.candidate_by_rank(ctx, 2)["id"]
    _consume_both_typing_attempts(api, ctx, backup_id)

    fixtures.set_clock(SECOND_EXPIRY_SWEEP_AT)
    validate_success(api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"]))

    expired = _typing_requests(api, ctx, backup_id)[2]
    assert expired["status"] == "EXPIRED", expired["status"]
    candidate = fixtures.read_candidate(backup_id, ctx["coordinator_headers"])
    assert candidate["status"] == "TYPING_EXPIRED", (
        f"a BACKUP at two consumed attempts rests in TYPING_EXPIRED rather than being "
        f"auto-excluded, got {candidate['status']}"
    )
    assert candidate["ct_attempt_count"] == 2, candidate["ct_attempt_count"]
    assert candidate["candidate_role"] == "BACKUP", candidate["candidate_role"]

    validate_error(
        api.create_typing_request(
            backup_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
        ),
        ApiErrorId.ERR_CT_ATTEMPTS_EXHAUSTED.value,
    )
