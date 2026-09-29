"""State transitions and their declared side effects.

Every test here walks one of the programme's state machines — the donor, the
search, the match candidate, the confirmatory-typing request, the workup case
with its three independent dimensions, the collection booking, the product
shipment, the conditioning timeline and the reimbursement claim — and pins both
the transition itself and every row the same call is required to move with it.
"""
from test_helpers import (
    ApiErrorId,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_entity_is_born_in_its_declared_initial_state(api):
    """PRD §3.2: "A donor profile also accepts `availability_status` at registration, defaulting to `AVAILABLE`; the four legal values are `AVAILABLE`, `TEMPORARILY_DEFERRED`, `PERMANENTLY_DEFERRED` and `WITHDRAWN`, and after registration this field is mutated only by system transitions — a non-availability answer to a typing request, a screening deferral, an adverse event, or the lapse of a deferral."
    PRD §3.3: "At creation the server stamps `coordinating_user_id` from `X-User-ID`, sets `conditioning_status` to `NOT_SCHEDULED` with `conditioning_start_date` null, `conditioning_aborted_reason` null and `committed_cost_cents` at zero."
    PRD §3.3: "The seven legal search states are `SEARCHING`, `NO_MATCH_FOUND`, `PRIMARY_ENGAGED`, `WORKUP_ACTIVE`, `BACKUP_REQUIRED`, `STALLED` and `FULFILLED`; a new search starts in `SEARCHING` with `last_sweep_at` null, and `NO_MATCH_FOUND` and `FULFILLED` are terminal."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with `ct_attempt_count` at zero, and carries `confirmed_score`, `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and `promoted_from_rank` all null."
    PRD §3.4: "It opens in `status` `REQUESTED` with `responded_at`, `reported_hla_typing`, `reported_match_grade`, `donor_available_flag` and `expired_by_sweep_at` all null, and its four legal states are `REQUESTED`, `RESPONDED`, `EXPIRED` and `CANCELLED`, the last three all terminal."
    PRD §3.6: "The workup case records its `match_candidate_id`, stamps `opened_by_user_id` from `X-User-ID`, and opens with `case_status` `OPEN`, `clearance_status` `PENDING`, `logistics_status` `UNSCHEDULED`, `collection_method` null, `method_decided_by_user_id` null, `physical_cleared_by_user_id` null, `idm_resulted_at` null and `abort_reason` null."
    PRD §3.6: "Three clearance items are created together, distinguished by their `item_type` and written in a pinned order that never varies — first `PHYSICAL_EXAM`, then `IDM_PANEL`, then `CONSENT` — each recording its `workup_case_id`, each with `result` `PENDING`, `resulted_at` null, `resulted_by_user_id` null, `expires_at` null and no `note`."
    PRD §3.9: "It opens in `status` `PROVISIONAL` with `variant_applied` `PROVISIONAL`, `finalized_at` null, `void_reason` null and `cancellation_fee_applied` false; its three legal states are `PROVISIONAL`, `FINALIZED` and `VOID`, the latter two terminal."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    ctx = fixtures.setup_primary_candidate()

    donor = ctx["donors"][0]
    assert donor["availability_status"] == "AVAILABLE", (
        f"a freshly registered donor defaults to AVAILABLE, got "
        f"{donor['availability_status']!r}"
    )
    assert ctx["patient"]["conditioning_status"] == "NOT_SCHEDULED", (
        f"a new patient starts NOT_SCHEDULED, got "
        f"{ctx['patient']['conditioning_status']!r}"
    )
    assert ctx["patient"]["conditioning_start_date"] is None
    assert ctx["patient"]["conditioning_aborted_reason"] is None
    assert ctx["patient"]["committed_cost_cents"] == 0
    assert ctx["search"]["status"] == "SEARCHING", (
        f"a new search starts in SEARCHING, got {ctx['search']['status']!r}"
    )
    assert ctx["search"]["last_sweep_at"] is None

    candidate = ctx["candidates"][0]
    assert candidate["status"] == "IDENTIFIED", (
        f"a materialised candidate opens in IDENTIFIED, got {candidate['status']!r}"
    )
    assert candidate["ct_attempt_count"] == 0
    for field in ("confirmed_score", "confirmed_match_grade", "screening_outcome",
                  "screening_deferral_type", "promoted_from_rank"):
        assert candidate[field] is None, f"a new candidate carries {field} null"

    typing_request = fixtures.advance_to_typing_requested(ctx)
    assert typing_request["status"] == "REQUESTED", (
        f"a new typing request opens in REQUESTED, got {typing_request['status']!r}"
    )
    for field in ("responded_at", "reported_hla_typing", "reported_match_grade",
                  "donor_available_flag", "expired_by_sweep_at"):
        assert typing_request[field] is None, f"a new typing request carries {field} null"

    fixtures.advance_to_typing_responded(ctx)
    fixtures.advance_to_screening_passed(ctx)

    case = validate_success(
        api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"]), 201
    )
    assert case["case_status"] == "OPEN"
    assert case["clearance_status"] == "PENDING"
    assert case["logistics_status"] == "UNSCHEDULED", (
        "all three workup-case dimensions start at their own initial state: "
        f"got {case['case_status']}/{case['clearance_status']}/{case['logistics_status']}"
    )
    assert case["collection_method"] is None
    assert case["method_decided_by_user_id"] is None
    assert case["physical_cleared_by_user_id"] is None
    assert case["idm_resulted_at"] is None
    assert case["abort_reason"] is None

    items = fixtures.find_clearance_items(case["id"], ctx["physician_headers"])["ordered"]
    assert [item["item_type"] for item in items] == [
        "PHYSICAL_EXAM", "IDM_PANEL", "CONSENT",
    ], f"the three items are written in a pinned order, got {[i['item_type'] for i in items]}"
    for item in items:
        assert item["result"] == "PENDING", (
            f"{item['item_type']} is created with result PENDING, got {item['result']!r}"
        )
        assert item["resulted_at"] is None
        assert item["resulted_by_user_id"] is None
        assert item["expires_at"] is None

    claim = fixtures.find_claim_for_case(case["id"])
    assert claim["status"] == "PROVISIONAL", (
        f"the cascade-created claim opens PROVISIONAL, got {claim['status']!r}"
    )
    assert claim["variant_applied"] == "PROVISIONAL"
    assert claim["finalized_at"] is None
    assert claim["void_reason"] is None
    assert claim["cancellation_fee_applied"] is False


def test_screening_pass_moves_the_candidate_to_screening_passed(api):
    """PRD §3.5: "A clean pass moves the candidate `TYPING_RESPONDED → SCREENING_PASSED`, recording `screening_outcome` `PASS` and `screening_deferral_type` `NONE`."
    PRD §3.4: "That string is stored as the request's `reported_match_grade` and copied onto the candidate's `confirmed_match_grade`, and the candidate moves `TYPING_REQUESTED → TYPING_RESPONDED`."

    Design: Corner/state_machines/screening_pass_moves_the_candidate_from_typing_responded_to_screening_passed
    """
    ctx = fixtures.setup_pipeline("typing_responded")
    candidate_before = fixtures.read_candidate(
        ctx["candidate_id"], ctx["coordinator_headers"]
    )
    assert candidate_before["status"] == "TYPING_RESPONDED", (
        f"setup must leave the candidate in TYPING_RESPONDED, got "
        f"{candidate_before['status']!r}"
    )

    candidate = validate_success(
        api.record_screening(
            ctx["candidate_id"],
            f.screening_payload(outcome="PASS", deferral_type="NONE"),
            ctx["liaison_headers"],
        )
    )
    A.assert_match_candidate(candidate)
    assert candidate["status"] == "SCREENING_PASSED", (
        f"a clean PASS moves TYPING_RESPONDED -> SCREENING_PASSED, got "
        f"{candidate['status']!r}"
    )
    assert candidate["screening_outcome"] == "PASS"
    assert candidate["screening_deferral_type"] == "NONE"

    assert float(candidate["confirmed_score"]) == 98.25, (
        f"the screening call does not recompute the confirmed score, got "
        f"{candidate['confirmed_score']!r}"
    )
    assert candidate["confirmed_match_grade"] == "9/10", (
        f"the confirmed grade survives the screening untouched, got "
        f"{candidate['confirmed_match_grade']!r}"
    )

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["availability_status"] == "AVAILABLE", (
        f"a passing screening leaves the donor AVAILABLE, got "
        f"{donor['availability_status']!r}"
    )
    assert donor["deferral_until"] is None
    assert donor["blocked_day_count"] == 0, (
        f"a PASS creates no calendar window, so blocked_day_count stays 0, got "
        f"{donor['blocked_day_count']}"
    )

    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "PRIMARY_ENGAGED", (
        f"the screening advances only the candidate, so the search is still "
        f"PRIMARY_ENGAGED, got {search['status']!r}"
    )

    cases, _ = validate_paginated(
        api.list_workup_cases(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert cases == [], "a screening PASS opens no workup case of its own"


def test_opening_a_workup_case_on_a_backup_candidate_is_refused(api):
    """PRD §3.6: "The candidate must be in `SCREENING_PASSED` status and its `candidate_role` must be `PRIMARY`; a backup or archived candidate is refused with `ERR_CANDIDATE_NOT_PRIMARY`."
    PRD §3.3: "Roles follow directly from position: the candidate at position 1 becomes `PRIMARY`, positions 2 and 3 become `BACKUP` — two backup slots — and positions 4 and 5 become `ARCHIVED_POOL`."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that search's candidates whose `candidate_role` is `BACKUP` and whose `status` is one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or `SCREENING_PASSED`."
    PRD §3.4: "When the candidate carrying the request is the search's `PRIMARY`, the search itself advances `SEARCHING → PRIMARY_ENGAGED`; when the candidate is a newly promoted primary, the same act moves the search `BACKUP_REQUIRED → PRIMARY_ENGAGED`, and that cycle may repeat once for each available backup."

    Design: Corner/state_machines/opening_a_workup_case_on_a_backup_candidate_is_rejected
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2)
    backup = fixtures.candidate_by_rank(ctx, 2)
    assert backup["candidate_role"] == "BACKUP", (
        f"the rank-2 candidate must be a BACKUP, got {backup['candidate_role']!r}"
    )

    fixtures.engage_candidate(ctx, backup["id"])
    engaged = fixtures.read_candidate(backup["id"], ctx["coordinator_headers"])
    assert engaged["status"] == "SCREENING_PASSED", (
        f"the backup must be screened all the way to SCREENING_PASSED before the "
        f"probe, got {engaged['status']!r}"
    )

    validate_error(
        api.open_workup_case(backup["id"], ctx["coordinator_headers"]),
        ApiErrorId.ERR_CANDIDATE_NOT_PRIMARY.value,
    )

    after = fixtures.read_candidate(backup["id"], ctx["coordinator_headers"])
    assert after["status"] == "SCREENING_PASSED", (
        f"the refused open leaves the backup's status untouched, got {after['status']!r}"
    )
    assert after["candidate_role"] == "BACKUP", (
        "a refused open never promotes the candidate it was aimed at"
    )
    assert after["rank_position"] == 2, (
        f"the frozen rank survives the refusal, got {after['rank_position']}"
    )
    assert after["promoted_from_rank"] is None, (
        "no promotion happened, so promoted_from_rank stays null"
    )

    cases, _ = validate_paginated(
        api.list_workup_cases(backup["id"], ctx["coordinator_headers"])
    )
    assert cases == [], (
        f"the refused open must write no workup case at all, found {len(cases)}"
    )

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == 0, (
        f"no claim was created, so the patient commits nothing, got "
        f"{patient['committed_cost_cents']}"
    )

    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["backup_candidate_count"] == 1, (
        f"the bench is unchanged by the refusal: one BACKUP remains, got "
        f"{search['backup_candidate_count']}"
    )
    assert search["status"] == "SEARCHING", (
        f"only a request against the PRIMARY advances the search, and no request "
        f"was ever raised against the rank-1 candidate, got {search['status']!r}"
    )


def test_opening_a_workup_case_fires_its_three_declared_side_effects(api):
    """PRD §3.6: "Three clearance items are created together, distinguished by their `item_type` and written in a pinned order that never varies — first `PHYSICAL_EXAM`, then `IDM_PANEL`, then `CONSENT` — each recording its `workup_case_id`, each with `result` `PENDING`, `resulted_at` null, `resulted_by_user_id` null, `expires_at` null and no `note`."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."
    PRD §3.6: "The candidate moves `SCREENING_PASSED → WORKUP_OPEN` and the search moves `PRIMARY_ENGAGED → WORKUP_ACTIVE`."
    PRD §3.6: "Its `planned_window_days` starts at 6, which is the planning default used while no method has been chosen."
    PRD §3.9: "Its `currency_code` is copied from that registry's `currency_code`, and its `fx_rate_snapshot` captures that registry's `fx_rate_to_usd` at the moment the current numbers were computed."
    PRD §3.9: "Every claim carries a `line_items` array of seven objects, each with a `line_type` and an `amount_usd_cents`, in one pinned order that never varies: `CT_TYPING`, `WORKUP_PHYSICAL`, `IDM_PANEL`, `COLLECTION`, `COURIER`, `DONOR_LOST_WAGE`, `CANCELLATION`."
    PRD §3.9: "The **provisional** variant runs at claim creation, before any collection method has been decided, so it cannot know the real method: it assumes `PBSC` for the collection line and the cancellation line's basis, assumes a window-day count of 6 for the lost-wage line, always charges a zero cancellation line, and captures `fx_rate_snapshot` from the registry as read at creation."

    Design: Corner/state_machines/opening_a_workup_case_fires_its_three_declared_side_effects
    """
    ctx = fixtures.setup_pipeline("screening_passed")

    case = validate_success(
        api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"]), 201
    )
    A.assert_workup_case(case)
    assert case["opened_by_user_id"] == "tc-1", (
        f"opened_by_user_id is stamped from X-User-ID, got "
        f"{case['opened_by_user_id']!r}"
    )
    assert case["planned_window_days"] == 6, (
        f"planned_window_days starts at 6 while no method has been chosen, got "
        f"{case['planned_window_days']}"
    )

    items = fixtures.find_clearance_items(case["id"], ctx["physician_headers"])["ordered"]
    assert len(items) == 3, f"exactly three clearance items are created, got {len(items)}"
    assert [item["item_type"] for item in items] == [
        "PHYSICAL_EXAM", "IDM_PANEL", "CONSENT",
    ], f"the pinned order never varies, got {[i['item_type'] for i in items]}"
    for item in items:
        A.assert_clearance_item(item)
        assert item["workup_case_id"] == case["id"]
        assert item["result"] == "PENDING"
        assert item["expires_at"] is None

    claim = fixtures.find_claim_for_case(case["id"])
    A.assert_reimbursement_claim(claim)
    assert claim["variant_applied"] == "PROVISIONAL", (
        f"the claim born with the case uses the PROVISIONAL variant, got "
        f"{claim['variant_applied']!r}"
    )
    assert claim["currency_code"] == "USD", (
        f"the claim's currency is copied from the billing registry, got "
        f"{claim['currency_code']!r}"
    )
    assert float(claim["fx_rate_snapshot"]) == 1.0, (
        f"the snapshot captures the registry's fx_rate_to_usd as read at creation, "
        f"got {claim['fx_rate_snapshot']!r}"
    )
    A.assert_claim_line_items(claim)
    assert A.claim_line(claim, "CANCELLATION") == 0, (
        f"the provisional variant always charges a zero cancellation line, got "
        f"{A.claim_line(claim, 'CANCELLATION')}"
    )
    assert claim["cancellation_fee_applied"] is False
    A.assert_claim_arithmetic(claim)

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == claim["total_usd_cents"], (
        f"the patient's committed cost re-derives to the live claim's total, got "
        f"{patient['committed_cost_cents']}"
    )

    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "WORKUP_OPEN", (
        f"the candidate moves SCREENING_PASSED -> WORKUP_OPEN, got "
        f"{candidate['status']!r}"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "WORKUP_ACTIVE", (
        f"the search moves PRIMARY_ENGAGED -> WORKUP_ACTIVE, got {search['status']!r}"
    )


def test_booking_actions_from_the_wrong_status_are_each_rejected(api):
    """PRD §3.7: "The booking must be in `CONFIRMED` status with no shipment already recorded, or the request is refused with `ERR_BOOKING_NOT_CONFIRMED`, and the recipient's conditioning must already be under way — `conditioning_status` `STARTED` — or the request is refused with `ERR_CONDITIONING_NOT_STARTED`."
    PRD §2.9: "Rungs eleven through thirty-two are the state-machine gates, in exactly this order: search not terminal and not stalled (`ERR_SEARCH_ALREADY_TERMINAL`); candidate status admits the operation (`ERR_INVALID_CANDIDATE_STATE`); candidate is the primary (`ERR_CANDIDATE_NOT_PRIMARY`); typing request still open (`ERR_TYPING_REQUEST_NOT_OPEN`); donor available for a passing screening (`ERR_DONOR_NOT_AVAILABLE`); workup case still open (`ERR_WORKUP_CASE_NOT_OPEN`); clearance item not yet resulted (`ERR_CLEARANCE_ITEM_ALREADY_RESULTED`); clearance items resulted in their pinned order (`ERR_CLEARANCE_ORDER_VIOLATION`); method not yet decided (`ERR_METHOD_ALREADY_DECIDED`); method already decided (`ERR_METHOD_NOT_DECIDED`); clearance complete (`ERR_CLEARANCE_NOT_COMPLETE`); booking held (`ERR_BOOKING_NOT_HELD`); booking cancellable (`ERR_BOOKING_NOT_CANCELLABLE`); booking confirmed and unharvested (`ERR_BOOKING_NOT_CONFIRMED`); conditioning already started (`ERR_CONDITIONING_NOT_STARTED`); conditioning action legal from the current conditioning state (`ERR_INVALID_CONDITIONING_ACTION`); conditioning cross-entity precondition met (`ERR_CONDITIONING_PRECONDITION_UNMET`); product delivered (`ERR_PRODUCT_NOT_DELIVERED`); shipment event legal from the shipment's status (`ERR_SHIPMENT_EVENT_NOT_ALLOWED`); claim still provisional (`ERR_CLAIM_NOT_PROVISIONAL`); claim finalizable (`ERR_CLAIM_NOT_FINALIZABLE`); and calendar window manually releasable (`ERR_WINDOW_NOT_RELEASABLE`)."
    PRD §3.7: "The booking must be in `HELD` status; a confirm aimed at anything else is refused with `ERR_BOOKING_NOT_HELD`."
    PRD §3.7: "The booking must be in `HELD` or `CONFIRMED` status and must have no product shipment recorded against it; anything else — a `COMPLETED`, `CANCELLED` or `SUPERSEDED` booking, or one that already produced a shipment — is refused with `ERR_BOOKING_NOT_CANCELLABLE`."
    PRD §3.7: "Cancellation records the supplied reason in `cancel_reason`, releases the booking's `duration_minutes` from the centre's `committed_slot_minutes`, and moves any `COLLECTION_WINDOW` window that this booking sourced to `RELEASED`, restoring the donor's `blocked_day_count` to exactly its pre-confirmation value."
    PRD §3.7: "Whether the booking had been confirmed matters for the money: cancelling from `HELD → CANCELLED` leaves `cancelled_after_confirmation` false and costs the programme nothing, whereas cancelling from `CONFIRMED → CANCELLED` sets `cancelled_after_confirmation` true, which adds a cancellation line to the case's final claim."
    PRD §3.7: "Finally, if the case is left with no booking in `HELD` or `CONFIRMED` status, the case's logistics dimension reverts `BOOKED → METHOD_SET` while its clearance dimension is untouched — the case is bookable again without redoing any clinical work."

    Design: Corner/state_machines/booking_actions_from_the_wrong_status_are_each_rejected
    """
    ctx = fixtures.setup_pipeline("booking_held")
    center_ops = ctx["center_ops_headers"]
    assert ctx["booking"]["status"] == "HELD", (
        f"setup must leave the slot merely HELD, got {ctx['booking']['status']!r}"
    )
    center_before = fixtures.read_center(ctx["center_id"])
    assert center_before["committed_slot_minutes"] == 300, (
        f"the held PBSC slot commits its 300 minutes, got "
        f"{center_before['committed_slot_minutes']}"
    )

    # The clock sits past the collection instant, so only the booking's own
    # status stands between the centre and recording a product.
    fixtures.set_clock("2026-10-11T14:00:00Z")

    validate_error(
        api.create_shipment(ctx["booking_id"], f.create_shipment_payload(), center_ops),
        ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value,
    )
    shipments, _ = validate_paginated(
        api.list_booking_shipments(ctx["booking_id"], center_ops)
    )
    assert shipments == [], (
        f"the refused harvest must write no shipment at all, found {len(shipments)}"
    )

    cancelled = validate_success(
        api.cancel_collection_booking(
            ctx["booking_id"],
            f.cancel_booking_payload(reason="CENTER_UNAVAILABLE"),
            center_ops,
        )
    )
    A.assert_collection_booking(cancelled)
    assert cancelled["status"] == "CANCELLED", (
        f"a HELD booking is cancellable, got {cancelled['status']!r}"
    )
    assert cancelled["cancel_reason"] == "CENTER_UNAVAILABLE", (
        f"the supplied reason is recorded verbatim, got {cancelled['cancel_reason']!r}"
    )
    assert cancelled["cancelled_after_confirmation"] is False, (
        "cancelling from HELD leaves cancelled_after_confirmation false"
    )

    validate_error(
        api.confirm_collection_booking(ctx["booking_id"], center_ops),
        ApiErrorId.ERR_BOOKING_NOT_HELD.value,
    )
    after_confirm = fixtures.read_booking(ctx["booking_id"])
    assert after_confirm["confirmed_at"] is None, (
        f"the refused confirm stamps nothing, got {after_confirm['confirmed_at']!r}"
    )

    validate_error(
        api.cancel_collection_booking(
            ctx["booking_id"],
            f.cancel_booking_payload(reason="CENTER_UNAVAILABLE"),
            center_ops,
        ),
        ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE.value,
    )

    booking = fixtures.read_booking(ctx["booking_id"])
    assert booking["status"] == "CANCELLED", (
        f"CANCELLED is terminal and the three refusals leave it there, got "
        f"{booking['status']!r}"
    )
    assert booking["cancel_reason"] == "CENTER_UNAVAILABLE", (
        "the second cancel is refused, so it cannot overwrite the recorded reason"
    )

    center = fixtures.read_center(ctx["center_id"])
    assert center["committed_slot_minutes"] == 0, (
        f"cancellation releases the booking's minutes from the centre, got "
        f"{center['committed_slot_minutes']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["logistics_status"] == "METHOD_SET", (
        f"with no live booking left the logistics dimension reverts to METHOD_SET, "
        f"got {case['logistics_status']!r}"
    )
    assert case["clearance_status"] == "CLEARED", (
        f"the clearance dimension is untouched by the booking walk, got "
        f"{case['clearance_status']!r}"
    )

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 0, (
        f"the booking never reached CONFIRMED, so no COLLECTION_WINDOW was ever "
        f"created and the donor's calendar stays clear, got "
        f"{donor['blocked_day_count']}"
    )


def test_a_finalized_claim_refuses_a_second_finalize(api):
    """PRD §3.9: "The claim must be in `PROVISIONAL` status, or the request is refused with `ERR_CLAIM_NOT_PROVISIONAL`."
    PRD §3.9: "And the case must have reached an accountable end: either its `case_status` is `COMPLETED`, or the case holds a booking with `cancelled_after_confirmation` true."
    PRD §3.9: "Anything else — a case still open, or an aborted case that never confirmed a booking — is refused with `ERR_CLAIM_NOT_FINALIZABLE`."
    PRD §3.9: "A successful finalisation moves the claim `PROVISIONAL → FINALIZED`, sets `variant_applied` to `FINAL`, recomputes every line, the discount tier, the coordination fee, the total and the local billed amount against the freshly read rate, and stamps `finalized_at` from the logical clock."
    PRD §3.9: "The patient's `committed_cost_cents` then moves by the difference between the final total and the provisional total it previously carried — upward when the final numbers are larger, downward when they are smaller — because both `PROVISIONAL` and `FINALIZED` claims count towards that commitment."
    PRD §3.9: "The **final** variant runs at finalisation: it uses the case's actual `collection_method` for the collection line, the case's actual `planned_window_days` for the lost-wage line, charges the cancellation line when a confirmed booking of the case was cancelled, and re-reads `fx_rate_snapshot` from the registry at that moment."
    PRD §3.9: "The `COLLECTION` line depends on the method the variant is working from: 1,450,000 cents for `PBSC` and 1,980,000 cents for `MARROW`."
    PRD §3.9: "The `CANCELLATION` line is the collection fee for the variant's method multiplied by 0.40, that is forty per cent, rounded half up to whole cents, and it is charged only in the final variant and only when some booking of the case carries `cancelled_after_confirmation` true; in every other situation it is zero."
    PRD §3.9: "When that line is charged, the claim's `cancellation_fee_applied` is recorded as true."
    PRD §3.9: "The `subtotal_usd_cents` is the exact integer sum of those seven already-rounded lines."
    PRD §3.9: "From the subtotal alone — never from the total, never from any individual line — a `volume_discount_pct` is selected: a subtotal of at least 4,000,000 cents earns 0.09, otherwise a subtotal of at least 2,500,000 cents earns 0.05, and anything below that earns nothing."
    PRD §3.9: "The `discount_usd_cents` is the subtotal multiplied by that rate, rounded half up to whole cents."
    PRD §3.9: "The `total_usd_cents` is then the subtotal less the discount plus the coordination fee."
    PRD §3.7: "Whether the booking had been confirmed matters for the money: cancelling from `HELD → CANCELLED` leaves `cancelled_after_confirmation` false and costs the programme nothing, whereas cancelling from `CONFIRMED → CANCELLED` sets `cancelled_after_confirmation` true, which adds a cancellation line to the case's final claim."

    Design: Corner/state_machines/a_finalized_claim_refuses_a_second_finalize
    """
    ctx = fixtures.setup_pipeline("booking_confirmed")
    claim_before = fixtures.read_claim(ctx["claim_id"])
    assert claim_before["status"] == "PROVISIONAL"
    lines_before = {
        line["line_type"]: line["amount_usd_cents"] for line in claim_before["line_items"]
    }

    # The claim is PROVISIONAL, so the refusal can only be about the case: it is
    # still OPEN and no confirmed booking has been cancelled yet.
    validate_error(
        api.finalize_reimbursement_claim(ctx["claim_id"], ctx["operations_headers"]),
        ApiErrorId.ERR_CLAIM_NOT_FINALIZABLE.value,
    )

    cancelled = fixtures.cancel_booking(ctx, reason="DONOR_WITHDREW")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_after_confirmation"] is True, (
        "the booking had reached CONFIRMED, so its cancellation is the billable kind"
    )

    claim = validate_success(
        api.finalize_reimbursement_claim(ctx["claim_id"], ctx["operations_headers"])
    )
    A.assert_reimbursement_claim(claim)
    assert claim["status"] == "FINALIZED", (
        f"an accountable end admits the finalisation, got {claim['status']!r}"
    )
    assert claim["variant_applied"] == "FINAL"
    assert is_iso8601_timestamp(claim["finalized_at"]), (
        f"finalized_at is stamped from the logical clock, got {claim['finalized_at']!r}"
    )
    assert claim["finalized_at"].startswith("2026-09-11T08:00:00"), (
        f"finalized_at is the logical clock, not wall time, got {claim['finalized_at']!r}"
    )

    lines_after = {
        line["line_type"]: line["amount_usd_cents"] for line in claim["line_items"]
    }
    assert lines_after["CANCELLATION"] == 580000, (
        f"the cancellation line is the PBSC collection fee of 1,450,000 cents times "
        f"0.40, got {lines_after['CANCELLATION']}"
    )
    assert claim["cancellation_fee_applied"] is True
    for line_type, amount in lines_before.items():
        if line_type == "CANCELLATION":
            continue
        assert lines_after[line_type] == amount, (
            f"the final variant reads the same PBSC method and the same six planned "
            f"window days, so the {line_type} line is unchanged: expected {amount}, "
            f"got {lines_after[line_type]}"
        )

    assert claim["subtotal_usd_cents"] == claim_before["subtotal_usd_cents"] + 580000, (
        f"the subtotal grows by exactly the new cancellation line, got "
        f"{claim['subtotal_usd_cents']} against a provisional "
        f"{claim_before['subtotal_usd_cents']}"
    )
    assert float(claim["volume_discount_pct"]) == 0.05, (
        f"a subtotal of {claim['subtotal_usd_cents']} cents sits in the 2,500,000 "
        f"tier, so the rate is 0.05, got {claim['volume_discount_pct']!r}"
    )
    expected_discount = (claim["subtotal_usd_cents"] * 5 + 50) // 100
    assert claim["discount_usd_cents"] == expected_discount, (
        f"the discount is the subtotal times 0.05 rounded half up, expected "
        f"{expected_discount}, got {claim['discount_usd_cents']}"
    )
    assert claim["intl_coordination_fee_usd_cents"] == 0
    A.assert_claim_arithmetic(claim)
    finalized_total = claim["total_usd_cents"]

    validate_error(
        api.finalize_reimbursement_claim(ctx["claim_id"], ctx["operations_headers"]),
        ApiErrorId.ERR_CLAIM_NOT_PROVISIONAL.value,
    )
    replayed = fixtures.read_claim(ctx["claim_id"])
    assert replayed["status"] == "FINALIZED", "FINALIZED is terminal"
    assert replayed["total_usd_cents"] == finalized_total, (
        f"the refused replay recomputes nothing, got {replayed['total_usd_cents']}"
    )
    assert replayed["finalized_at"] == claim["finalized_at"], (
        "the refused replay does not re-stamp finalized_at"
    )

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == finalized_total, (
        f"the final-minus-provisional delta is applied exactly once, so the patient "
        f"commits the finalised total {finalized_total}, got "
        f"{patient['committed_cost_cents']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "OPEN", (
        f"finalising the money does not close the clinical case, got "
        f"{case['case_status']!r}"
    )
    assert case["logistics_status"] == "METHOD_SET", (
        f"the cancelled booking left the case bookable again, got "
        f"{case['logistics_status']!r}"
    )


def test_resulting_the_same_clearance_item_twice_is_refused(api):
    """PRD §3.6: "The item must still carry `result` `PENDING`, or the write is refused with `ERR_CLEARANCE_ITEM_ALREADY_RESULTED`."
    PRD §3.6: "And the three items must be resulted in their created order: `IDM_PANEL` may be resulted only once `PHYSICAL_EXAM` carries `PASS`, and `CONSENT` only once both `PHYSICAL_EXAM` and `IDM_PANEL` carry `PASS`."
    PRD §3.6: "Any attempt out of order is refused with `ERR_CLEARANCE_ORDER_VIOLATION`."
    PRD §3.6: "A recorded result stamps `resulted_at` from the logical clock and `resulted_by_user_id` from `X-User-ID`."
    PRD §3.6: "A passing `PHYSICAL_EXAM` stamps the case's `physical_cleared_by_user_id` with the acting `X-User-ID`, which is the comparand the two-physician rule uses later."
    PRD §3.6: "The first passing result moves the case `PENDING → IN_PROGRESS`."

    Design: Corner/state_machines/resulting_the_same_clearance_item_twice_is_refused
    """
    ctx = fixtures.setup_pipeline("workup_open")
    items = ctx["clearance"]

    fixtures.set_clock("2026-08-02T09:00:00Z")
    first = validate_success(
        api.record_clearance_result(
            items["PHYSICAL_EXAM"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        )
    )
    A.assert_clearance_item(first)
    assert first["result"] == "PASS"
    assert first["resulted_at"].startswith("2026-08-02T09:00:00"), (
        f"resulted_at comes from the logical clock, got {first['resulted_at']!r}"
    )
    assert first["resulted_by_user_id"] == "md-1", (
        f"resulted_by_user_id is stamped from X-User-ID, got "
        f"{first['resulted_by_user_id']!r}"
    )

    # A later clock instant makes any silent re-stamp visible.
    fixtures.set_clock("2026-08-03T09:00:00Z")

    validate_error(
        api.record_clearance_result(
            items["PHYSICAL_EXAM"]["id"],
            f.clearance_result_payload(result="FAIL"),
            ctx["physician_headers"],
        ),
        ApiErrorId.ERR_CLEARANCE_ITEM_ALREADY_RESULTED.value,
    )
    validate_error(
        api.record_clearance_result(
            items["CONSENT"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        ),
        ApiErrorId.ERR_CLEARANCE_ORDER_VIOLATION.value,
    )

    physical = validate_success(
        api.get_clearance_item(items["PHYSICAL_EXAM"]["id"], ctx["physician_headers"])
    )
    assert physical["result"] == "PASS", (
        f"the refused replay cannot overwrite a recorded result, got "
        f"{physical['result']!r}"
    )
    assert physical["resulted_at"].startswith("2026-08-02T09:00:00"), (
        f"the refused replay cannot re-stamp resulted_at, got "
        f"{physical['resulted_at']!r}"
    )

    consent = validate_success(
        api.get_clearance_item(items["CONSENT"]["id"], ctx["physician_headers"])
    )
    assert consent["result"] == "PENDING", (
        f"the out-of-order write leaves the consent item PENDING, got "
        f"{consent['result']!r}"
    )
    assert consent["resulted_at"] is None
    assert consent["resulted_by_user_id"] is None

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["clearance_status"] == "IN_PROGRESS", (
        f"exactly one passing result is on file, so the dimension sits at "
        f"IN_PROGRESS, got {case['clearance_status']!r}"
    )
    assert case["physical_cleared_by_user_id"] == "md-1", (
        f"the passing physical examination stamped its physician on the case, got "
        f"{case['physical_cleared_by_user_id']!r}"
    )
    assert case["case_status"] == "OPEN", (
        "two refused writes cannot abort the case"
    )


def test_clearance_status_is_re_derived_after_every_child_result(api):
    """PRD §3.6: "The parent's clearance dimension is then re-derived from its three children."
    PRD §3.6: "The first passing result moves the case `PENDING → IN_PROGRESS`."
    PRD §3.6: "A passing result on the last item still pending, with the other two already carrying `PASS`, moves the case `IN_PROGRESS → CLEARED`."
    PRD §3.6: "A passing `PHYSICAL_EXAM` stamps the case's `physical_cleared_by_user_id` with the acting `X-User-ID`, which is the comparand the two-physician rule uses later."
    PRD §3.6: "A passing `IDM_PANEL` sets that item's `expires_at` to its `resulted_at` plus thirty days — infectious-disease results are considered valid for one month and no longer — and surfaces the same instant as the case's `idm_resulted_at`, which stays null unless the panel actually passed."
    PRD §3.6: "The `CONSENT` item carries no derived field, and its `expires_at` remains null, as does that of `PHYSICAL_EXAM`."
    PRD §3.6: "The two dimensions evolve independently of one another until booking creation couples them by demanding that clearance be complete; a `MedicalDirector` can perfectly well decide the method while clearance is still `IN_PROGRESS`."

    Design: Corner/state_machines/clearance_status_is_re_derived_after_every_child_result
    """
    ctx = fixtures.setup_pipeline("workup_open")
    fixtures.set_clock(C.TIMELINE["CLEARANCE_AT"])

    physical = fixtures.result_clearance_item(ctx, "PHYSICAL_EXAM", "PASS")
    assert physical["expires_at"] is None, (
        f"the physical examination carries no expiry, got {physical['expires_at']!r}"
    )
    case = ctx["workup_case"]
    assert case["clearance_status"] == "IN_PROGRESS", (
        f"the first passing result moves PENDING -> IN_PROGRESS, got "
        f"{case['clearance_status']!r}"
    )
    assert case["physical_cleared_by_user_id"] == "md-1"
    assert case["idm_resulted_at"] is None, (
        "idm_resulted_at stays null until the panel itself passes"
    )
    assert case["logistics_status"] == "UNSCHEDULED", (
        f"the clinical dimension moves alone, got {case['logistics_status']!r}"
    )

    idm = fixtures.result_clearance_item(ctx, "IDM_PANEL", "PASS")
    assert idm["expires_at"].startswith("2026-10-11T08:00:00"), (
        f"the panel expires thirty days after its resulted_at of "
        f"{C.TIMELINE['CLEARANCE_AT']}, got {idm['expires_at']!r}"
    )
    case = ctx["workup_case"]
    assert case["clearance_status"] == "IN_PROGRESS", (
        f"one item is still pending, so the dimension holds at IN_PROGRESS, got "
        f"{case['clearance_status']!r}"
    )
    assert case["idm_resulted_at"].startswith("2026-09-11T08:00:00"), (
        f"the case surfaces the panel's own resulted_at, got "
        f"{case['idm_resulted_at']!r}"
    )

    consent = fixtures.result_clearance_item(ctx, "CONSENT", "PASS")
    assert consent["expires_at"] is None, (
        f"the consent item carries no derived expiry, got {consent['expires_at']!r}"
    )
    case = ctx["workup_case"]
    assert case["clearance_status"] == "CLEARED", (
        f"a pass on the last pending item moves IN_PROGRESS -> CLEARED, got "
        f"{case['clearance_status']!r}"
    )
    assert case["case_status"] == "OPEN", (
        f"a cleared donor is not a completed case, got {case['case_status']!r}"
    )
    assert case["logistics_status"] == "UNSCHEDULED", (
        f"three clinical passes move nothing on the operational dimension, got "
        f"{case['logistics_status']!r}"
    )

    final_items = fixtures.find_clearance_items(
        ctx["workup_case_id"], ctx["physician_headers"]
    )["ordered"]
    assert [item["result"] for item in final_items] == ["PASS", "PASS", "PASS"], (
        f"exactly three rows, all passing, got {[i['result'] for i in final_items]}"
    )


def test_recording_the_collected_product_moves_booking_candidate_and_case_together(api):
    """PRD §3.7: "The shipment records its `collection_booking_id`, stamps `collected_at` from the logical clock as the moment collection ended, and derives `must_infuse_by` as that instant advanced by the method's viability allowance — 72 hours, three full days, for a `PBSC` product, and 48 hours, two full days, for a `MARROW` product."
    PRD §3.7: "It also derives `dose_adequacy`, which is `ADEQUATE` when `collected_cd34_e6_per_kg` is greater than or equal to two million cells per kilogram — the threshold expressed in the same units of one million as the field itself, namely 2.00 — and `INADEQUATE` otherwise."
    PRD §3.7: "The shipment opens with `status` `SCHEDULED`, `departed_at` null, `delivered_at` null and `transit_event_count` at zero; its five legal states are `SCHEDULED`, `IN_TRANSIT`, `DELIVERED`, `DISCARDED` and `CANCELLED`, the last three terminal."
    PRD §3.7: "Recording the product moves the booking `CONFIRMED → COMPLETED` — and a `COMPLETED` booking keeps counting towards its centre's `committed_slot_minutes` — moves the candidate `WORKUP_OPEN → COLLECTED`, and moves the case `BOOKED → COLLECTED` on the logistics dimension."
    PRD §3.7: "Every accepted event increments the shipment's `transit_event_count` by one."
    PRD §3.7: "A `DEPARTED` event stamps `departed_at` from the logical clock and moves the shipment `SCHEDULED → IN_TRANSIT`, carrying the case `COLLECTED → IN_TRANSIT`."

    Design: Corner/state_machines/recording_the_collected_product_moves_booking_candidate_and_case_together
    """
    ctx = fixtures.setup_pipeline("conditioning_started")
    center_before = fixtures.read_center(ctx["center_id"])
    assert center_before["committed_slot_minutes"] == 300, (
        f"the confirmed PBSC slot commits 300 minutes, got "
        f"{center_before['committed_slot_minutes']}"
    )

    fixtures.set_clock(C.TIMELINE["COLLECTED_AT"])
    shipment = validate_success(
        api.create_shipment(
            ctx["booking_id"], f.create_shipment_payload(), ctx["center_ops_headers"]
        ),
        201,
    )
    A.assert_product_shipment(shipment)
    assert shipment["collection_booking_id"] == ctx["booking_id"]
    assert shipment["status"] == "SCHEDULED", (
        f"a fresh shipment opens SCHEDULED, got {shipment['status']!r}"
    )
    assert shipment["departed_at"] is None
    assert shipment["delivered_at"] is None
    assert shipment["transit_event_count"] == 0
    assert shipment["collected_at"].startswith("2026-10-11T13:00:00"), (
        f"collected_at comes from the logical clock, got {shipment['collected_at']!r}"
    )
    assert shipment["must_infuse_by"].startswith("2026-10-14T13:00:00"), (
        f"a PBSC product stays viable for 72 hours from 2026-10-11T13:00:00Z, got "
        f"{shipment['must_infuse_by']!r}"
    )
    assert shipment["dose_adequacy"] == "ADEQUATE", (
        f"5.20 cells per kilogram clears the 2.00 threshold, got "
        f"{shipment['dose_adequacy']!r}"
    )

    booking = fixtures.read_booking(ctx["booking_id"])
    assert booking["status"] == "COMPLETED", (
        f"recording the product moves the booking CONFIRMED -> COMPLETED, got "
        f"{booking['status']!r}"
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "COLLECTED", (
        f"the candidate moves WORKUP_OPEN -> COLLECTED, got {candidate['status']!r}"
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["logistics_status"] == "COLLECTED", (
        f"the case moves BOOKED -> COLLECTED on its logistics dimension, got "
        f"{case['logistics_status']!r}"
    )

    ctx["shipment"] = shipment
    ctx["shipment_id"] = shipment["id"]
    departed = fixtures.file_shipment_event(ctx, "DEPARTED")
    assert departed["status"] == "IN_TRANSIT", (
        f"a DEPARTED event moves SCHEDULED -> IN_TRANSIT, got {departed['status']!r}"
    )
    assert departed["departed_at"].startswith("2026-10-11T13:00:00"), (
        f"departed_at is stamped from the logical clock, got "
        f"{departed['departed_at']!r}"
    )
    assert departed["delivered_at"] is None
    assert departed["transit_event_count"] == 1, (
        f"every accepted event increments the counter by one, got "
        f"{departed['transit_event_count']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["logistics_status"] == "IN_TRANSIT", (
        f"the departure carries the case COLLECTED -> IN_TRANSIT, got "
        f"{case['logistics_status']!r}"
    )
    assert case["case_status"] == "OPEN", (
        f"the product is in the air, not infused, got {case['case_status']!r}"
    )
    assert case["clearance_status"] == "CLEARED", (
        f"the clinical dimension is untouched by transport, got "
        f"{case['clearance_status']!r}"
    )

    booking = fixtures.read_booking(ctx["booking_id"])
    assert booking["status"] == "COMPLETED", (
        "the transit event does not move the booking again"
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "COLLECTED", (
        "the transit event does not move the candidate again"
    )
    center = fixtures.read_center(ctx["center_id"])
    assert center["committed_slot_minutes"] == 300, (
        f"a COMPLETED booking keeps counting towards the centre's ledger, got "
        f"{center['committed_slot_minutes']}"
    )
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["conditioning_status"] == "STARTED", (
        f"harvest and transport never touch the recipient's regimen, got "
        f"{patient['conditioning_status']!r}"
    )


def test_infusion_closes_the_case_only_when_both_dimensions_are_terminal(api):
    """PRD §3.8: "Infusion moves `STARTED → INFUSED` and closes the case."
    PRD §3.8: "It requires that a product shipment of the patient's workup case is in `DELIVERED` status, or the request is refused with `ERR_PRODUCT_NOT_DELIVERED`."
    PRD §3.8: "A successful infusion moves the workup case `OPEN → COMPLETED` — which is legitimate precisely because its `clearance_status` is `CLEARED` and its `logistics_status` is `DELIVERED` — moves the candidate `COLLECTED → CLOSED`, and moves the search `WORKUP_ACTIVE → FULFILLED`."
    PRD §3.8: "Every successful action increments the patient's `version` by one."
    PRD §3.7: "A `DELIVERED` event filed at or before `must_infuse_by` stamps `delivered_at` and moves the shipment `IN_TRANSIT → DELIVERED`, carrying the case `IN_TRANSIT → DELIVERED`, at which point the recipient may be infused."
    PRD §3.7: "Every accepted event increments the shipment's `transit_event_count` by one."

    Design: Corner/state_machines/infusion_closes_the_case_only_when_both_dimensions_are_terminal
    """
    ctx = fixtures.setup_pipeline("in_transit")
    patient_before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient_before["conditioning_status"] == "STARTED"
    case_before = fixtures.read_workup_case(
        ctx["workup_case_id"], ctx["coordinator_headers"]
    )
    assert case_before["logistics_status"] == "IN_TRANSIT", (
        f"the product is still in the courier's hands, got "
        f"{case_before['logistics_status']!r}"
    )

    validate_error(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload("INFUSE", patient_before["version"]),
            ctx["coordinator_headers"],
        ),
        ApiErrorId.ERR_PRODUCT_NOT_DELIVERED.value,
    )
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["conditioning_status"] == "STARTED", (
        f"the refused infusion leaves the regimen where it was, got "
        f"{patient['conditioning_status']!r}"
    )
    assert patient["version"] == patient_before["version"], (
        f"only a successful action increments the patient's version, got "
        f"{patient['version']} against {patient_before['version']}"
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "OPEN", (
        f"the refused infusion cannot close the case, got {case['case_status']!r}"
    )

    fixtures.set_clock(C.TIMELINE["DELIVERY_AT"])
    delivered = fixtures.file_shipment_event(ctx, "DELIVERED")
    assert delivered["status"] == "DELIVERED", (
        f"a DELIVERED event filed inside the viability allowance moves IN_TRANSIT -> "
        f"DELIVERED, got {delivered['status']!r}"
    )
    assert delivered["delivered_at"].startswith("2026-10-12T09:00:00"), (
        f"delivered_at is stamped from the logical clock, got "
        f"{delivered['delivered_at']!r}"
    )
    assert delivered["transit_event_count"] == 2, (
        f"the departure and the delivery are two accepted events, got "
        f"{delivered['transit_event_count']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["logistics_status"] == "DELIVERED", (
        f"the delivery carries the case IN_TRANSIT -> DELIVERED, got "
        f"{case['logistics_status']!r}"
    )
    assert case["case_status"] == "OPEN", (
        f"a delivered product does not by itself close the case — only the infusion "
        f"does, got {case['case_status']!r}"
    )

    infused = fixtures.drive_conditioning(ctx, "INFUSE")
    assert infused["conditioning_status"] == "INFUSED", (
        f"infusion moves STARTED -> INFUSED, got {infused['conditioning_status']!r}"
    )
    assert infused["version"] == patient_before["version"] + 1, (
        f"the one successful action increments the version exactly once, got "
        f"{infused['version']} against {patient_before['version']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "COMPLETED", (
        f"with clearance CLEARED and logistics DELIVERED the case may close, got "
        f"{case['case_status']!r}"
    )
    assert case["clearance_status"] == "CLEARED"
    assert case["logistics_status"] == "DELIVERED"
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "CLOSED", (
        f"the candidate moves COLLECTED -> CLOSED, got {candidate['status']!r}"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "FULFILLED", (
        f"the search moves WORKUP_ACTIVE -> FULFILLED, got {search['status']!r}"
    )

    claim = fixtures.read_claim(ctx["claim_id"])
    assert claim["status"] == "PROVISIONAL", (
        f"the infusion moves the case, the candidate and the search — not the money, "
        f"got {claim['status']!r}"
    )
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == claim["total_usd_cents"], (
        f"the still-provisional claim keeps its commitment, got "
        f"{patient['committed_cost_cents']}"
    )


def test_aborting_conditioning_spares_the_already_cancelled_booking(api):
    """PRD §3.8: "Aborting is the widest cascade in the system, and it runs identically whether the abort comes from `SCHEDULED → ABORTED` or from `STARTED → ABORTED`."
    PRD §3.8: "The supplied reason is recorded as the patient's `conditioning_aborted_reason`."
    PRD §3.8: "Every booking of the patient's `OPEN` workup case in `HELD` or `CONFIRMED` status becomes `CANCELLED` with `cancel_reason` `CONDITIONING_ABORTED`, each releasing its minutes from its centre's `committed_slot_minutes`; bookings already in a terminal status keep whatever `cancel_reason` they already carried and are not rewritten."
    PRD §3.8: "Every `COLLECTION_WINDOW` calendar window sourced by those bookings becomes `RELEASED`, restoring the donor's `blocked_day_count`."
    PRD §3.8: "The workup case moves `case_status` `OPEN → ABORTED` with `abort_reason` `CONDITIONING_ABORTED`, and its match candidate is moved to `CLOSED` from either `WORKUP_OPEN` or `COLLECTED`, whichever it held."
    PRD §3.8: "Every reimbursement claim of that case still in `PROVISIONAL` status becomes `VOID` with its `void_reason` recorded, restoring the patient's `committed_cost_cents` by the voided total."
    PRD §3.8: "And the search moves `WORKUP_ACTIVE → STALLED`."
    PRD §3.8: "Every successful action increments the patient's `version` by one."
    PRD §3.7: "Those offsets are method-specific and asymmetric, reflecting how the two procedures actually burden a volunteer: a `PBSC` collection blocks the four days before the collection date and the one day after it, because mobilisation injections precede apheresis, while a `MARROW` harvest blocks the one day before and the six days after, because recovery from general anaesthesia and aspiration takes far longer."
    PRD §3.7: "Either way the window's `day_count` is the inclusive number of days it spans, which comes to six for `PBSC` and eight for `MARROW` — precisely the case's `planned_window_days` — and it raises the donor's `blocked_day_count` accordingly."
    PRD §3.7: "Cancellation records the supplied reason in `cancel_reason`, releases the booking's `duration_minutes` from the centre's `committed_slot_minutes`, and moves any `COLLECTION_WINDOW` window that this booking sourced to `RELEASED`, restoring the donor's `blocked_day_count` to exactly its pre-confirmation value."

    Design: Corner/state_machines/aborting_conditioning_spares_the_already_cancelled_booking
    """
    ctx = fixtures.setup_pipeline("conditioning_scheduled")

    # One booking cancelled while merely HELD, then a second booking of the same
    # slot taken all the way to CONFIRMED.
    first = fixtures.advance_to_booking_held(ctx)
    first_id = first["id"]
    fixtures.cancel_booking(ctx, reason="CENTER_UNAVAILABLE")
    second = fixtures.advance_to_booking_held(ctx)
    second_id = second["id"]
    assert second_id != first_id, "the second hold must be a distinct booking row"
    fixtures.advance_to_booking_confirmed(ctx)

    before_first = fixtures.read_booking(first_id)
    assert before_first["status"] == "CANCELLED"
    assert before_first["cancel_reason"] == "CENTER_UNAVAILABLE"
    before_second = fixtures.read_booking(second_id)
    assert before_second["status"] == "CONFIRMED", (
        f"the live booking must be CONFIRMED before the abort, got "
        f"{before_second['status']!r}"
    )
    center_before = fixtures.read_center(ctx["center_id"])
    assert center_before["committed_slot_minutes"] == 300, (
        f"only the live booking's 300 minutes are committed — the cancelled one "
        f"released its own at its own cancellation, got "
        f"{center_before['committed_slot_minutes']}"
    )
    donor_before = fixtures.read_donor(ctx["donor_id"])
    assert donor_before["blocked_day_count"] == 6, (
        f"the confirmed PBSC booking blocks six inclusive days, got "
        f"{donor_before['blocked_day_count']}"
    )
    patient_before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    claim_before = fixtures.read_claim(ctx["claim_id"])
    assert patient_before["committed_cost_cents"] == claim_before["total_usd_cents"]

    aborted = fixtures.drive_conditioning(
        ctx, "ABORT", reason="Patient developed sepsis"
    )
    A.assert_patient(aborted)
    assert aborted["conditioning_status"] == "ABORTED", (
        f"the abort runs from SCHEDULED just as it does from STARTED, got "
        f"{aborted['conditioning_status']!r}"
    )
    assert aborted["conditioning_aborted_reason"] == "Patient developed sepsis", (
        f"the supplied reason is recorded verbatim, got "
        f"{aborted['conditioning_aborted_reason']!r}"
    )
    assert aborted["version"] == patient_before["version"] + 1, (
        f"one successful action, one version increment, got {aborted['version']} "
        f"against {patient_before['version']}"
    )

    after_second = fixtures.read_booking(second_id)
    assert after_second["status"] == "CANCELLED", (
        f"the CONFIRMED booking is swept up by the cascade, got "
        f"{after_second['status']!r}"
    )
    assert after_second["cancel_reason"] == "CONDITIONING_ABORTED", (
        f"the cascade stamps its own reason on the live booking, got "
        f"{after_second['cancel_reason']!r}"
    )
    after_first = fixtures.read_booking(first_id)
    assert after_first["cancel_reason"] == "CENTER_UNAVAILABLE", (
        f"a booking already in a terminal status keeps the reason it carried and is "
        f"not rewritten, got {after_first['cancel_reason']!r}"
    )

    windows = [
        window for window in fixtures.find_windows(ctx["donor_id"])
        if window["reason"] == "COLLECTION_WINDOW"
    ]
    assert len(windows) == 1, (
        f"only the confirmed booking ever sourced a collection window, got "
        f"{len(windows)}"
    )
    window = windows[0]
    A.assert_unavailability_window(window)
    assert window["status"] == "RELEASED", (
        f"the sourced window is released by the cascade, got {window['status']!r}"
    )
    assert window["date_from"] == "2026-10-07", (
        f"a PBSC window opens four days before the 2026-10-11 collection date, got "
        f"{window['date_from']!r}"
    )
    assert window["date_to"] == "2026-10-12", (
        f"a PBSC window closes one day after the collection date, got "
        f"{window['date_to']!r}"
    )
    assert window["day_count"] == 6

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 0, (
        f"releasing the one window restores the donor's calendar exactly, got "
        f"{donor['blocked_day_count']}"
    )
    center = fixtures.read_center(ctx["center_id"])
    assert center["committed_slot_minutes"] == 0, (
        f"the live booking's minutes are released once and the cancelled booking's "
        f"are not released a second time, got {center['committed_slot_minutes']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "ABORTED", (
        f"the case moves OPEN -> ABORTED, got {case['case_status']!r}"
    )
    assert case["abort_reason"] == "CONDITIONING_ABORTED", (
        f"the case's own abort_reason is the cascade's label, got "
        f"{case['abort_reason']!r}"
    )
    assert case["clearance_status"] == "CLEARED", (
        f"the clinical dimension keeps its own terminal value, got "
        f"{case['clearance_status']!r}"
    )

    claim = fixtures.read_claim(ctx["claim_id"])
    assert claim["status"] == "VOID", (
        f"the provisional claim is voided, got {claim['status']!r}"
    )
    assert claim["void_reason"] is not None, "the void records its reason"
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == 0, (
        f"voiding the only claim restores the whole commitment, got "
        f"{patient['committed_cost_cents']}"
    )

    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "CLOSED", (
        f"the candidate is closed from WORKUP_OPEN, got {candidate['status']!r}"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "STALLED", (
        f"the search moves WORKUP_ACTIVE -> STALLED, got {search['status']!r}"
    )
