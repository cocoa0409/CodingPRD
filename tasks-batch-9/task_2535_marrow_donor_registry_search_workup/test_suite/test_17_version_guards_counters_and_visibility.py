"""Version guards, re-derived counters and same-request cascade visibility.

The two case-level version guards of §2.7 protect the two write paths that
legitimately overwrite another operator's decision, so both are exercised
sequentially: read, write, then replay the pre-write version.  The rest of the
module covers the counters that are pure re-derivations over child rows and the
rule that a cascade's effects are visible in the very response that caused them.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_booking_create_rejects_a_stale_workup_case_version(api):
    """PRD §2.7: "A `POST /registry/collection-bookings` request must carry `expected_workup_case_version` as a required, non-optional body field holding the `version` of the target `WorkupCase` that the client last observed."
    PRD §2.7: "If that value does not equal the workup case's current `version`, the create is rejected with `ERR_STALE_WORKUP_VERSION` (HTTP 412)."
    PRD §2.7: "The guard exists because creating a booking is a supersede operation: it silently retires the case's prior held slot, so a client whose view of the case has fallen behind would otherwise discard a slot decision it never saw."
    PRD §3.7: "Creating it adds its `duration_minutes` to the centre's `committed_slot_minutes`, moves the case `METHOD_SET → BOOKED` on the logistics dimension, and increments the case's `version` by one."
    PRD §3.7: "If the case already holds a booking in `HELD` status, that earlier booking moves `HELD → SUPERSEDED`, records the reason `SUPERSEDED_BY_NEW_BOOKING` in its `cancel_reason`, and releases its `duration_minutes` back out of the centre's `committed_slot_minutes`."
    PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."

    Design: Corner/cross-cutting complexity layers/booking_create_rejects_a_stale_workup_case_version
    """
    ctx = fixtures.setup_pipeline("conditioning_scheduled", method="PBSC")
    center_ops = ctx["center_ops_headers"]

    # The client reads the case once and keeps that version.
    observed = validate_success(api.get_workup_case(ctx["workup_case_id"], center_ops))
    stale_version = observed["version"]
    assert observed["logistics_status"] == "METHOD_SET", (
        f"Setup failed: the case must sit at METHOD_SET, got {observed['logistics_status']!r}"
    )

    first = validate_success(
        api.create_collection_booking(
            f.create_booking_payload(
                ctx["workup_case_id"], ctx["center_id"],
                C.TIMELINE["BOOKING_START_AT"], stale_version,
            ),
            center_ops,
        ),
        expected_status=201,
    )
    assert first["status"] == "HELD", (
        f"a fresh booking opens HELD, got {first['status']!r}"
    )
    assert first["duration_minutes"] == 300, (
        f"a PBSC slot runs 300 minutes, got {first['duration_minutes']}"
    )

    # The create bumped the case's version, so the held view is now behind.
    #
    # The replacement slot stays on WINDOW_OPEN_DATE, the last day the IDM panel
    # is still valid, because PRD §3.7 checks infectious-disease validity after
    # the version guard: "the booking's `collection_date` must fall on or before
    # the UTC calendar date of the `IDM_PANEL` clearance item's `expires_at`".
    # 14:30 is the first instant outside the first slot's buffered interval, so
    # the capacity-1 centre admits it: "Because the intervals are half-open, a
    # slot beginning exactly at a buffered interval's end instant does not
    # overlap it and is admitted."
    second_start_at = f"{C.TIMELINE['WINDOW_OPEN_DATE']}T14:30:00Z"
    validate_error(
        api.create_collection_booking(
            f.create_booking_payload(
                ctx["workup_case_id"], ctx["center_id"], second_start_at, stale_version
            ),
            center_ops,
        ),
        ApiErrorId.ERR_STALE_WORKUP_VERSION.value,
    )

    # The refusal is inert: no second row, the first slot survives untouched.
    bookings, meta = validate_paginated(
        api.list_collection_bookings(
            center_ops, params={"workup_case_id": ctx["workup_case_id"], "limit": 50}
        )
    )
    assert meta["total_count"] == 1, (
        f"the stale create must not have written a booking, found {meta['total_count']}"
    )
    assert bookings[0]["id"] == first["id"] and bookings[0]["status"] == "HELD"
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "the refused create must not have committed any further centre minutes"
    )

    # Re-reading the case and replaying the identical payload now succeeds.
    fresh = validate_success(api.get_workup_case(ctx["workup_case_id"], center_ops))
    assert_version_incremented(fresh["version"], stale_version)
    assert fresh["logistics_status"] == "BOOKED", (
        f"the first create moved the case METHOD_SET -> BOOKED, got {fresh['logistics_status']!r}"
    )

    second = validate_success(
        api.create_collection_booking(
            f.create_booking_payload(
                ctx["workup_case_id"], ctx["center_id"], second_start_at, fresh["version"]
            ),
            center_ops,
        ),
        expected_status=201,
    )
    assert second["status"] == "HELD"
    assert second["id"] != first["id"]

    superseded = fixtures.read_booking(first["id"], center_ops)
    assert superseded["status"] == "SUPERSEDED", (
        f"the earlier held slot moves HELD -> SUPERSEDED, got {superseded['status']!r}"
    )
    assert superseded["cancel_reason"] == "SUPERSEDED_BY_NEW_BOOKING", (
        f"the supersede records its own reason, got {superseded['cancel_reason']!r}"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "the supersede released the retired slot's minutes, so one PBSC slot is committed, "
        "not two"
    )


def test_conditioning_action_rejects_a_stale_patient_version(api):
    """PRD §2.7: "A `POST /registry/patients/{id}/conditioning` request must carry `expected_patient_version` as a required, non-optional body field holding the `version` of the target `Patient` that the client last observed."
    PRD §2.7: "If that value does not equal the patient's current `version`, the action is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412)."
    PRD §2.7: "The guard exists because a re-schedule overwrites the previously recorded `conditioning_start_date` and cancels every booking that falls outside the newly derived window; a client acting on a stale view of the patient would be rewriting a timeline it has not read."
    PRD §3.8: "Every successful action increments the patient's `version` by one."
    PRD §3.8: "Re-scheduling is a self-loop: `SCHEDULED → SCHEDULED`."
    PRD §3.8: "Starting the regimen moves `SCHEDULED → STARTED` and is the point of no return."
    PRD §2.9: "The two version guards of §2.7 sit immediately below the state gates and above every safety, temporal and constraint rule: `ERR_STALE_WORKUP_VERSION` on booking creation, then `ERR_STALE_PATIENT_VERSION` on a conditioning action."

    Design: Corner/cross-cutting complexity layers/conditioning_action_rejects_a_stale_patient_version
    """
    ctx = fixtures.setup_pipeline("booking_confirmed", method="PBSC")
    coordinator = ctx["coordinator_headers"]
    start_date = C.TIMELINE["CONDITIONING_START_DATE"]

    # Standing on the conditioning start date, every state gate for START passes:
    # the patient is SCHEDULED and a CONFIRMED booking exists for its open case.
    fixtures.set_clock(C.TIMELINE["CONDITIONING_START_AT"])
    observed = validate_success(api.get_patient(ctx["patient_id"], coordinator))
    stale_version = observed["version"]
    assert observed["conditioning_status"] == "SCHEDULED", (
        f"Setup failed: the patient must be SCHEDULED, got {observed['conditioning_status']!r}"
    )

    # A re-schedule self-loop is a real write, so it moves the version on.
    rescheduled = validate_success(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload(
                "SCHEDULE", stale_version, conditioning_start_date=start_date
            ),
            coordinator,
        )
    )
    assert rescheduled["conditioning_status"] == "SCHEDULED", (
        "re-scheduling is a self-loop and leaves the state label alone"
    )
    assert_version_incremented(rescheduled["version"], stale_version)
    settled_version = rescheduled["version"]

    # Replaying the same action with the pre-write version is refused.
    validate_error(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload(
                "SCHEDULE", stale_version, conditioning_start_date=start_date
            ),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
    )

    # And so is a different action whose own state gates would all have passed:
    # the guard sits below the state gates, so nothing above it masks it.
    validate_error(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload("START", stale_version),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
    )

    # Both refusals are inert.
    unchanged = validate_success(api.get_patient(ctx["patient_id"], coordinator))
    assert unchanged["version"] == settled_version, (
        f"a stale conditioning action must not bump the version: expected "
        f"{settled_version}, got {unchanged['version']}"
    )
    assert unchanged["conditioning_status"] == "SCHEDULED", (
        f"the refused START must not have started the regimen, got "
        f"{unchanged['conditioning_status']!r}"
    )
    assert unchanged["conditioning_start_date"] == start_date
    assert fixtures.read_booking(ctx["booking_id"])["status"] == "CONFIRMED", (
        "the refused actions must not have touched the confirmed slot"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300

    # Quoting the version the client can now actually read lets the action through.
    started = validate_success(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload("START", settled_version),
            coordinator,
        )
    )
    assert started["conditioning_status"] == "STARTED", (
        f"the retry moves SCHEDULED -> STARTED, got {started['conditioning_status']!r}"
    )
    assert_version_incremented(started["version"], settled_version)


def test_blocked_day_count_is_re_derived_after_create_and_after_source_release(api):
    """PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."
    PRD §3.2: "A liaison may block its own donor's calendar by hand, supplying `date_from`, `date_to` and a `reason` of either `PERSONAL` or `MEDICAL_HOLD`."
    PRD §3.2: "A manually created window leaves `source_booking_id` null; only windows auto-created by booking confirmation carry a `source_booking_id` pointing back at the booking that generated them."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."
    PRD §3.2: "A new window starts with `status` `ACTIVE` and `released_at` null."
    PRD §3.2: "A window whose `reason` is `PERSONAL` or `MEDICAL_HOLD` may be released at any time while it is `ACTIVE`."
    PRD §3.2: "A successful release sets the window's `status` to `RELEASED`, stamps `released_at` from the logical clock, and lowers the donor's `blocked_day_count` by that window's `day_count`; the call returns no body."
    PRD §3.2: "Any attempt outside those rules, including a release aimed at a window that is already `RELEASED`, is refused with `ERR_WINDOW_NOT_RELEASABLE`."
    PRD §3.2: "A donor profile also accepts `availability_status` at registration, defaulting to `AVAILABLE`; the four legal values are `AVAILABLE`, `TEMPORARILY_DEFERRED`, `PERMANENTLY_DEFERRED` and `WITHDRAWN`, and after registration this field is mutated only by system transitions — a non-availability answer to a typing request, a screening deferral, an adverse event, or the lapse of a deferral."

    Design: Corner/cross-cutting complexity layers/blocked_day_count_is_re_derived_after_create_and_after_source_release
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)
    liaison = ctx["liaison_headers"]
    assert donor["blocked_day_count"] == 0, (
        f"a freshly registered donor has no blocked days, got {donor['blocked_day_count']}"
    )

    # Three days, inclusive of both ends.
    first = validate_success(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload("2026-09-01", "2026-09-03", "PERSONAL"),
            liaison,
        ),
        expected_status=201,
    )
    assert first["day_count"] == 3, (
        f"2026-09-01..2026-09-03 spans three calendar days, got {first['day_count']}"
    )
    assert first["status"] == "ACTIVE" and first["released_at"] is None
    assert first["source_booking_id"] is None, (
        "a hand-blocked window has no source booking behind it"
    )
    assert fixtures.read_donor(donor["id"])["blocked_day_count"] == 3

    # A single-day window and a five-day window, so the sum is unambiguous.
    single = validate_success(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload("2026-09-10", "2026-09-10", "MEDICAL_HOLD"),
            liaison,
        ),
        expected_status=201,
    )
    assert single["day_count"] == 1, (
        f"a window whose two dates are equal counts one day, got {single['day_count']}"
    )
    third = validate_success(
        api.create_unavailability_window(
            donor["id"],
            f.create_unavailability_window_payload("2026-09-20", "2026-09-24", "PERSONAL"),
            liaison,
        ),
        expected_status=201,
    )
    assert third["day_count"] == 5, (
        f"2026-09-20..2026-09-24 spans five calendar days, got {third['day_count']}"
    )
    assert fixtures.read_donor(donor["id"])["blocked_day_count"] == 9, (
        "blocked_day_count is the sum 3 + 1 + 5 over the three ACTIVE windows"
    )

    # Releasing drops the sum by exactly that row's day_count.
    A.assert_no_content(api.release_unavailability_window(donor["id"], first["id"], liaison))
    after_release = fixtures.read_donor(donor["id"])
    assert after_release["blocked_day_count"] == 6, (
        f"releasing the three-day window leaves 1 + 5, got {after_release['blocked_day_count']}"
    )
    assert after_release["availability_status"] == "AVAILABLE", (
        "a hand-blocked calendar never changes the donor's availability_status"
    )

    # The released row is excluded from the sum, not deleted.
    released, released_meta = validate_paginated(
        api.list_unavailability_windows(
            donor["id"], liaison, params={"status": "RELEASED", "limit": 10, "offset": 0}
        )
    )
    assert released_meta["total_count"] == 1, (
        f"the released row must still be readable, found {released_meta['total_count']}"
    )
    assert released[0]["id"] == first["id"]
    assert released[0]["status"] == "RELEASED"
    assert released[0]["day_count"] == 3, (
        "the row keeps its own day_count; only its exclusion from the sum changed"
    )
    assert is_iso8601_timestamp(released[0]["released_at"]), (
        f"released_at must be stamped from the logical clock, got {released[0]['released_at']!r}"
    )
    assert released[0]["released_at"].startswith(C.CLOCK_EPOCH[:19]), (
        f"released_at must carry the logical clock instant {C.CLOCK_EPOCH}, got "
        f"{released[0]['released_at']!r}"
    )

    A.assert_no_content(api.release_unavailability_window(donor["id"], third["id"], liaison))
    assert fixtures.read_donor(donor["id"])["blocked_day_count"] == 1, (
        "with only the single-day MEDICAL_HOLD window left ACTIVE the sum is 1"
    )

    # A second release of the same row cannot subtract twice.
    validate_error(
        api.release_unavailability_window(donor["id"], first["id"], liaison),
        ApiErrorId.ERR_WINDOW_NOT_RELEASABLE.value,
    )
    final = fixtures.read_donor(donor["id"])
    assert final["blocked_day_count"] == 1, (
        f"the refused re-release must leave the aggregate where it was, got "
        f"{final['blocked_day_count']}"
    )
    assert final["availability_status"] == "AVAILABLE"

    active, active_meta = validate_paginated(
        api.list_unavailability_windows(
            donor["id"], liaison, params={"status": "ACTIVE", "limit": 10, "offset": 0}
        )
    )
    assert active_meta["total_count"] == 1, (
        f"exactly one window is still ACTIVE, found {active_meta['total_count']}"
    )
    assert active[0]["id"] == single["id"]
    assert active[0]["reason"] == "MEDICAL_HOLD"
    assert active[0]["day_count"] == final["blocked_day_count"], (
        "the surviving ACTIVE window's day_count reconciles with the donor's aggregate"
    )


def test_cascade_results_are_visible_in_the_same_request_that_caused_them(api):
    """PRD §2.10: "Six fields in this system are not stored decisions but pure re-derivations from child rows, recomputed on every write that touches one of those children."
    PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §2.10: "`SearchRequest.match_pool_size` is the count of match candidates belonging to that search."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that search's candidates whose `candidate_role` is `BACKUP` and whose `status` is one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or `SCREENING_PASSED`."
    PRD §3.3: "Opening a search is the single most computationally involved call in the system, because the entire candidate pool is scored, ranked, sliced and frozen inside that one call."
    PRD §3.3: "Each materialised candidate records its `search_request_id`, its `donor_id`, the computed `preliminary_score` and `rank_score`, its frozen `rank_position` and its `candidate_role`, opens in `status` `IDENTIFIED` with `ct_attempt_count` at zero, and carries `confirmed_score`, `confirmed_match_grade`, `screening_outcome`, `screening_deferral_type` and `promoted_from_rank` all null."
    PRD §3.3: "The search's `match_pool_size` records how many candidates were written and `backup_candidate_count` records how many of them are backups."
    PRD §3.4: "When `donor_available_flag` is true, the confirmed variant of the match score is computed and stored: every one of the five loci is compared at allele level, the ambiguity penalty is zero because the reported typing carries no ambiguity, and the resulting score lands in the candidate's `confirmed_score`."
    PRD §3.4: "Alongside the score, the response computes the allele-level matched count — the sum across the five loci of the allele-level matched counts, a whole number from 0 through 10 — and renders it as a grade string of that number followed by a slash and ten."
    PRD §3.4: "That string is stored as the request's `reported_match_grade` and copied onto the candidate's `confirmed_match_grade`, and the candidate moves `TYPING_REQUESTED → TYPING_RESPONDED`."
    PRD §3.6: "A successful open creates a great deal at once."
    PRD §3.6: "Its `planned_window_days` starts at 6, which is the planning default used while no method has been chosen."
    PRD §3.6: "Three clearance items are created together, distinguished by their `item_type` and written in a pinned order that never varies — first `PHYSICAL_EXAM`, then `IDM_PANEL`, then `CONSENT` — each recording its `workup_case_id`, each with `result` `PENDING`, `resulted_at` null, `resulted_by_user_id` null, `expires_at` null and no `note`."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."
    PRD §3.6: "The candidate moves `SCREENING_PASSED → WORKUP_OPEN` and the search moves `PRIMARY_ENGAGED → WORKUP_ACTIVE`."
    PRD §3.9: "It opens in `status` `PROVISIONAL` with `variant_applied` `PROVISIONAL`, `finalized_at` null, `void_reason` null and `cancellation_fee_applied` false; its three legal states are `PROVISIONAL`, `FINALIZED` and `VOID`, the latter two terminal."
    PRD §3.9: "The **provisional** variant runs at claim creation, before any collection method has been decided, so it cannot know the real method: it assumes `PBSC` for the collection line and the cancellation line's basis, assumes a window-day count of 6 for the lost-wage line, always charges a zero cancellation line, and captures `fx_rate_snapshot` from the registry as read at creation."

    Design: Corner/consistency model/cascade_results_are_visible_in_the_same_request_that_caused_them
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)
    coordinator = ctx["coordinator_headers"]
    liaison = ctx["liaison_headers"]

    patient = validate_success(
        api.create_patient(f.create_patient_payload(), coordinator), expected_status=201
    )
    assert patient["committed_cost_cents"] == 0, (
        f"a fresh patient commits nothing, got {patient['committed_cost_cents']}"
    )

    # --- fan-out one: the search create materialises the whole pool inline ----
    search = validate_success(
        api.create_search_request(
            f.create_search_request_payload(patient["id"]), coordinator
        ),
        expected_status=201,
    )
    assert search["status"] == "SEARCHING"
    assert search["match_pool_size"] == 1, (
        f"the create response itself already counts the materialised pool, got "
        f"{search['match_pool_size']}"
    )
    assert search["backup_candidate_count"] == 0, (
        f"a one-donor pool has no backup slots filled, got {search['backup_candidate_count']}"
    )

    # The very next call, with no write in between, already carries both scores.
    candidates, meta = validate_paginated(
        api.list_match_candidates(
            coordinator,
            params={"search_request_id": search["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        f"the pool was written inside the create, not lazily on this read, got "
        f"{meta['total_count']}"
    )
    candidate = candidates[0]
    assert candidate["donor_id"] == donor["id"]
    assert float(candidate["preliminary_score"]) == pytest.approx(94.75, abs=1e-9), (
        f"the preliminary score is computed at materialisation, got "
        f"{candidate['preliminary_score']!r}"
    )
    assert float(candidate["rank_score"]) == pytest.approx(97.113, abs=1e-9), (
        f"the ranking score is computed at materialisation, got {candidate['rank_score']!r}"
    )
    assert candidate["rank_position"] == 1
    assert candidate["candidate_role"] == "PRIMARY"
    assert candidate["status"] == "IDENTIFIED"
    assert candidate["ct_attempt_count"] == 0
    assert candidate["confirmed_score"] is None and candidate["confirmed_match_grade"] is None

    # --- the confirmed variant is not deferred to a later recomputation ------
    typing_request = validate_success(
        api.create_typing_request(candidate["id"], f.create_typing_request_payload(), coordinator),
        expected_status=201,
    )
    assert typing_request["attempt_number"] == 1
    assert typing_request["status"] == "REQUESTED"
    assert typing_request["reported_match_grade"] is None

    responded = validate_success(
        api.respond_typing_request(typing_request["id"], f.typing_response_payload(), liaison)
    )
    assert responded["status"] == "RESPONDED"
    assert responded["reported_match_grade"] == "9/10", (
        f"nine matched alleles render as the grade string 9/10, got "
        f"{responded['reported_match_grade']!r}"
    )

    typed = validate_success(api.get_match_candidate(candidate["id"], coordinator))
    assert float(typed["confirmed_score"]) == pytest.approx(98.25, abs=1e-9), (
        f"the immediately following read already carries the confirmed score, got "
        f"{typed['confirmed_score']!r}"
    )
    assert typed["confirmed_match_grade"] == "9/10", (
        "the grade string is copied onto the candidate in the same response"
    )
    assert typed["status"] == "TYPING_RESPONDED"

    screened = validate_success(api.record_screening(candidate["id"], f.screening_payload(), liaison))
    assert screened["status"] == "SCREENING_PASSED"
    assert screened["screening_outcome"] == "PASS"

    # --- fan-out two: opening the workup writes four neighbours at once ------
    case = validate_success(
        api.open_workup_case(candidate["id"], coordinator), expected_status=201
    )
    assert case["case_status"] == "OPEN"
    assert case["clearance_status"] == "PENDING", (
        f"the clearance dimension opens PENDING, got {case['clearance_status']!r}"
    )
    assert case["logistics_status"] == "UNSCHEDULED", (
        f"the logistics dimension opens UNSCHEDULED, got {case['logistics_status']!r}"
    )
    assert case["collection_method"] is None
    assert case["planned_window_days"] == 6, (
        f"planned_window_days is already the planning default of 6, not left null for a "
        f"later pass, got {case['planned_window_days']!r}"
    )
    assert case["opened_by_user_id"] == coordinator["X-User-ID"]

    # The patient read immediately after: no sweep, no clock move, no other write.
    committed = validate_success(api.get_patient(patient["id"], coordinator))
    assert committed["committed_cost_cents"] == 2_072_000, (
        f"the provisional domestic PBSC claim total is already committed, got "
        f"{committed['committed_cost_cents']}"
    )

    items, items_meta = validate_paginated(
        api.list_clearance_items(case["id"], coordinator, params={"limit": 10, "offset": 0})
    )
    assert items_meta["total_count"] == 3, (
        f"all three clearance rows exist already, got {items_meta['total_count']}"
    )
    assert [item["item_type"] for item in items] == ["PHYSICAL_EXAM", "IDM_PANEL", "CONSENT"], (
        f"the three rows sit in their pinned order, got {[i['item_type'] for i in items]}"
    )
    for item in items:
        assert item["workup_case_id"] == case["id"]
        assert item["result"] == "PENDING", (
            f"a cascade-created clearance row opens unresulted, got {item['result']!r}"
        )
        assert item["resulted_at"] is None and item["resulted_by_user_id"] is None

    claims, claims_meta = validate_paginated(
        api.list_reimbursement_claims(
            coordinator, params={"patient_id": patient["id"], "limit": 10, "offset": 0}
        )
    )
    assert claims_meta["total_count"] == 1, (
        f"exactly one provisional claim was opened in the same breath, got "
        f"{claims_meta['total_count']}"
    )
    claim = claims[0]
    assert claim["workup_case_id"] == case["id"]
    assert claim["status"] == "PROVISIONAL"
    assert claim["variant_applied"] == "PROVISIONAL"
    assert claim["cancellation_fee_applied"] is False
    assert claim["finalized_at"] is None and claim["void_reason"] is None
    assert claim["billing_registry_id"] == ctx["registry_id"]
    assert claim["currency_code"] == "USD"
    A.assert_claim_arithmetic(claim)
    assert A.claim_line(claim, "COLLECTION") == 1_450_000, (
        "the provisional variant assumes PBSC for the collection line"
    )
    assert A.claim_line(claim, "DONOR_LOST_WAGE") == 192_000, (
        "the provisional variant assumes a six-day window: 32,000 cents per day"
    )
    assert A.claim_line(claim, "CANCELLATION") == 0, (
        "the provisional variant always charges a zero cancellation line"
    )
    assert claim["total_usd_cents"] == 2_072_000
    assert claim["total_usd_cents"] == committed["committed_cost_cents"], (
        "the claim total reconciles exactly with the patient's committed_cost_cents"
    )

    active_search = validate_success(api.get_search_request(search["id"], coordinator))
    assert active_search["status"] == "WORKUP_ACTIVE", (
        f"the open carried the search to WORKUP_ACTIVE in the same request, got "
        f"{active_search['status']!r}"
    )
    assert validate_success(api.get_match_candidate(candidate["id"], coordinator))["status"] == (
        "WORKUP_OPEN"
    )
