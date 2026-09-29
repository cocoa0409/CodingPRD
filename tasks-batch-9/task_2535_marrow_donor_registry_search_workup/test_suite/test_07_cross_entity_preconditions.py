"""Cross-entity preconditions: a write gated by the state of a *different* record.

Three gates are exercised.  Starting the recipient's conditioning regimen reads
the collection booking's status, so a merely held slot is not enough.  Raising a
confirmatory-typing request reads the donor's home registry cooperation status,
so suspending the partner registry closes the door on new requests while leaving
the ones already raised alone.  Releasing a `DEFERRAL` calendar window reads the
donor's own `deferral_until` date, so the release is impossible until the logical
UTC date has moved strictly past it.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assertions,
    constants as C,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CONDITIONING_START_INSTANT = "2026-10-05T09:00:00Z"

DEFERRAL_UNTIL_DATE = "2026-09-30"
DEFERRAL_WINDOW_DAY_COUNT = 61
ON_DEFERRAL_UNTIL_INSTANT = "2026-09-30T23:59:59Z"
DAY_AFTER_DEFERRAL_UNTIL_INSTANT = "2026-10-01T00:00:00Z"

INTERNATIONAL_TYPING_DEADLINE_AT = "2026-08-10T00:00:00Z"


def _instant(value: str) -> datetime:
    """One UTC instant, parsed so that any legal ISO 8601 rendering compares equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_case_with_a_held_booking():
    """A patient whose conditioning is `SCHEDULED` and whose only slot is `HELD`.

    The clock is then moved onto the recorded `conditioning_start_date` itself, so
    the date half of the start precondition is satisfied and the booking's status
    is the only thing left that can refuse the call.
    """
    ctx = fixtures.setup_pipeline("booking_held")
    fixtures.set_clock(CONDITIONING_START_INSTANT)
    return ctx


def _setup_deferred_donor_with_a_deferral_window():
    """A temporarily deferred donor carrying one system-created `DEFERRAL` window."""
    ctx = fixtures.setup_pipeline("typing_responded")
    fixtures.advance_to_screening_passed(
        ctx,
        outcome="DEFER",
        deferral_type="TEMPORARY",
        deferral_until=DEFERRAL_UNTIL_DATE,
    )
    windows = fixtures.find_windows(ctx["donor_id"], reason="DEFERRAL")
    assert len(windows) == 1, (
        f"Setup failed: the deferral must create exactly one window, got {len(windows)}"
    )
    ctx["window"] = windows[0]
    ctx["window_id"] = windows[0]["id"]
    return ctx


def test_conditioning_start_is_refused_while_the_booking_is_only_held(api):
    """PRD §3.8: "It requires that the current logical UTC date is not earlier than the recorded `conditioning_start_date`, and that a booking in `CONFIRMED` status exists for the patient's `OPEN` workup case; a start without such a booking is refused with `ERR_CONDITIONING_PRECONDITION_UNMET`."
    PRD §3.7: "The booking opens with `status` `HELD`, `confirmed_at` null, `cancel_reason` null and `cancelled_after_confirmation` false; its five legal states are `HELD`, `CONFIRMED`, `COMPLETED`, `CANCELLED` and `SUPERSEDED`, the last three terminal."
    PRD §3.7: "Creating it adds its `duration_minutes` to the centre's `committed_slot_minutes`, moves the case `METHOD_SET → BOOKED` on the logistics dimension, and increments the case's `version` by one."
    PRD §3.8: "Every successful action increments the patient's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/conditioning_start_depends_on_booking_confirmation_state
    """
    ctx = _setup_case_with_a_held_booking()
    booking = fixtures.read_booking(ctx["booking_id"])
    assert booking["status"] == "HELD", (
        f"Setup failed: the slot must merely be held, got {booking['status']}"
    )
    before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert before["conditioning_status"] == "SCHEDULED", (
        f"Setup failed: conditioning must be SCHEDULED, got {before['conditioning_status']}"
    )
    assert before["conditioning_start_date"] == C.TIMELINE["CONDITIONING_START_DATE"], (
        "Setup failed: the scheduled date must be the canonical one, got "
        f"{before['conditioning_start_date']}"
    )

    # The date half of the precondition is satisfied; only the booking's status
    # stands in the way, and it belongs to a different record entirely.
    response = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("START", before["version"]),
        ctx["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONDITIONING_PRECONDITION_UNMET.value)

    after = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert after["conditioning_status"] == "SCHEDULED", (
        f"the refused start leaves conditioning SCHEDULED, got {after['conditioning_status']}"
    )
    assert after["version"] == before["version"], (
        "only a successful action moves the patient's version: expected "
        f"{before['version']}, got {after['version']}"
    )

    booking_after = fixtures.read_booking(ctx["booking_id"])
    assert booking_after["status"] == "HELD", (
        f"the refused start does not touch the booking, got {booking_after['status']}"
    )
    assert booking_after["confirmed_at"] is None, (
        f"an unconfirmed booking carries no confirmed_at, got {booking_after['confirmed_at']}"
    )
    case = fixtures.read_workup_case(ctx["workup_case_id"])
    assert case["logistics_status"] == "BOOKED", (
        f"the held slot leaves the case BOOKED, got {case['logistics_status']}"
    )


def test_conditioning_start_succeeds_once_the_booking_is_confirmed(api):
    """PRD §3.8: "It requires that the current logical UTC date is not earlier than the recorded `conditioning_start_date`, and that a booking in `CONFIRMED` status exists for the patient's `OPEN` workup case; a start without such a booking is refused with `ERR_CONDITIONING_PRECONDITION_UNMET`."
    PRD §3.8: "Starting the regimen moves `SCHEDULED → STARTED` and is the point of no return."
    PRD §3.8: "Every successful action increments the patient's `version` by one."
    PRD §3.7: "Confirmation stamps `confirmed_at` from the logical clock and creates the donor's collection window: an `ACTIVE` calendar window with `reason` `COLLECTION_WINDOW` and `source_booking_id` pointing back at this booking, spanning from a number of days before `collection_date` through a number of days after it."

    Design: Difficulty/cross_entity_state_dependency/conditioning_start_depends_on_booking_confirmation_state
    """
    ctx = _setup_case_with_a_held_booking()
    # The one and only change from the refused case: the slot is confirmed.
    fixtures.advance_to_booking_confirmed(ctx)
    booking = fixtures.read_booking(ctx["booking_id"])
    assert booking["status"] == "CONFIRMED", (
        f"Setup failed: the slot must be confirmed, got {booking['status']}"
    )

    before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    response = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("START", before["version"]),
        ctx["coordinator_headers"],
    )
    patient = validate_success(response)

    assert patient["conditioning_status"] == "STARTED", (
        "with a CONFIRMED booking in place the start must be admitted, got "
        f"{patient['conditioning_status']}"
    )
    assert patient["version"] == before["version"] + 1, (
        f"the successful action increments the version once: expected "
        f"{before['version'] + 1}, got {patient['version']}"
    )
    assert patient["conditioning_start_date"] == C.TIMELINE["CONDITIONING_START_DATE"], (
        f"starting does not move the scheduled date, got {patient['conditioning_start_date']}"
    )
    assert fixtures.read_booking(ctx["booking_id"])["status"] == "CONFIRMED", (
        "the start does not disturb the booking it depended on"
    )


def _setup_international_primary_candidate():
    """One international donor, materialised as the primary of a global search.

    The search is opened while the partner registry is still `ACTIVE`, because
    eligibility itself reads that same field; only afterwards is the registry's
    cooperation status changed, which is what isolates the typing-request gate.
    """
    ctx = fixtures.setup_programme(with_center=False)
    international = fixtures.create_international_registry()
    ctx["international_registry"] = international
    ctx["international_registry_id"] = international["id"]
    fixtures.add_donor(ctx, registry_id=international["id"])

    patient = fixtures.create_patient()
    ctx["patient"] = patient
    ctx["patient_id"] = patient["id"]
    search = fixtures.open_search(patient["id"], search_scope="DOMESTIC_AND_INTERNATIONAL")
    ctx["search"] = search
    ctx["search_id"] = search["id"]

    candidates = fixtures.list_candidates(search["id"])
    assert len(candidates) == 1, (
        f"Setup failed: the partner donor alone must materialise, got {len(candidates)}"
    )
    ctx["candidate"] = candidates[0]
    ctx["candidate_id"] = candidates[0]["id"]
    return ctx


def test_typing_request_is_refused_while_the_donor_registry_is_suspended(api):
    """PRD §3.4: "The candidate must be in `IDENTIFIED` or `TYPING_EXPIRED` status, its search must not be terminal or stalled, the donor's registry must have `cooperation_status` of `ACTIVE` — a suspended or terminated partner is refused with `ERR_REGISTRY_NOT_COOPERATING` — and the candidate's `ct_attempt_count` must be strictly below the ceiling of two attempts."
    PRD §3.1: "Moving a registry to `SUSPENDED` or `TERMINATED` blocks any new confirmatory-typing request against that registry's donors but leaves already-`REQUESTED` typing requests entirely untouched — they may still be answered, and they still expire on their original schedule."
    PRD §3.1: "An operations update may adjust `cooperation_status`, `cooperation_tier`, `fx_rate_to_usd` or `ct_response_deadline_hours`, each optionally, and each such update increments the registry's `version` by one."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."

    Design: Difficulty/cross_entity_state_dependency/typing_request_depends_on_donor_registry_cooperation_state
    """
    ctx = _setup_international_primary_candidate()

    registry = validate_success(
        api.update_registry(
            ctx["international_registry_id"],
            {"cooperation_status": "SUSPENDED"},
            ctx["operations_headers"],
        )
    )
    assert registry["cooperation_status"] == "SUSPENDED", (
        f"Setup failed: the partner must be suspended, got {registry['cooperation_status']}"
    )
    assert registry["version"] == ctx["international_registry"]["version"] + 1, (
        "the cooperation update increments the registry's version once: expected "
        f"{ctx['international_registry']['version'] + 1}, got {registry['version']}"
    )

    # The candidate itself is spotless; the refusal comes from its donor's registry.
    response = api.create_typing_request(
        ctx["candidate_id"],
        f.create_typing_request_payload(),
        ctx["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REGISTRY_NOT_COOPERATING.value)

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "IDENTIFIED", (
        f"the refused request leaves the candidate IDENTIFIED, got {candidate['status']}"
    )
    assert candidate["ct_attempt_count"] == 0, (
        "a refused request consumes no attempt, got "
        f"{candidate['ct_attempt_count']}"
    )
    assert candidate["candidate_role"] == "PRIMARY", (
        f"the refused request does not re-role the candidate, got {candidate['candidate_role']}"
    )

    rows, meta = validate_paginated(
        api.list_typing_requests(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert rows == [] and meta["total_count"] == 0, (
        f"the refused request writes no row, got {meta['total_count']}"
    )
    assert fixtures.read_search(ctx["search_id"])["status"] == "SEARCHING", (
        "a refused request cannot engage the search"
    )


def test_typing_request_succeeds_once_the_registry_cooperates_again(api):
    """PRD §3.4: "The candidate must be in `IDENTIFIED` or `TYPING_EXPIRED` status, its search must not be terminal or stalled, the donor's registry must have `cooperation_status` of `ACTIVE` — a suspended or terminated partner is refused with `ERR_REGISTRY_NOT_COOPERATING` — and the candidate's `ct_attempt_count` must be strictly below the ceiling of two attempts."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."
    PRD §3.4: "When the candidate carrying the request is the search's `PRIMARY`, the search itself advances `SEARCHING → PRIMARY_ENGAGED`; when the candidate is a newly promoted primary, the same act moves the search `BACKUP_REQUIRED → PRIMARY_ENGAGED`, and that cycle may repeat once for each available backup."
    PRD §3.4: "When the donor's registry has `is_domestic` false, a further 48 hours of grace — two full days — are added, in recognition of the time zones and translation involved in international coordination."

    Design: Difficulty/cross_entity_state_dependency/typing_request_depends_on_donor_registry_cooperation_state
    """
    ctx = _setup_international_primary_candidate()
    validate_success(
        api.update_registry(
            ctx["international_registry_id"],
            {"cooperation_status": "SUSPENDED"},
            ctx["operations_headers"],
        )
    )
    # Cooperation is restored, which is the single difference from the refusal.
    restored = validate_success(
        api.update_registry(
            ctx["international_registry_id"],
            {"cooperation_status": "ACTIVE"},
            ctx["operations_headers"],
        )
    )
    assert restored["cooperation_status"] == "ACTIVE", (
        f"Setup failed: the partner must cooperate again, got {restored['cooperation_status']}"
    )

    response = api.create_typing_request(
        ctx["candidate_id"],
        f.create_typing_request_payload(),
        ctx["coordinator_headers"],
    )
    request = validate_success(response, expected_status=201)

    assert request["status"] == "REQUESTED", (
        f"a new typing request opens in REQUESTED, got {request['status']}"
    )
    assert request["attempt_number"] == 1, (
        f"this is the candidate's first attempt, got {request['attempt_number']}"
    )
    assert _instant(request["deadline_at"]) == _instant(INTERNATIONAL_TYPING_DEADLINE_AT), (
        "168 contractual hours from 2026-08-01T00:00:00Z plus 48 hours of "
        f"international grace fall due at {INTERNATIONAL_TYPING_DEADLINE_AT}, got "
        f"{request['deadline_at']}"
    )

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "TYPING_REQUESTED", (
        f"the successful request moves the candidate, got {candidate['status']}"
    )
    assert candidate["ct_attempt_count"] == 1, (
        f"the successful request spends one attempt, got {candidate['ct_attempt_count']}"
    )
    assert fixtures.read_search(ctx["search_id"])["status"] == "PRIMARY_ENGAGED", (
        "requesting typing for the primary engages the search"
    )


def test_deferral_window_release_is_refused_while_the_deferral_still_runs(api):
    """PRD §3.2: "A window whose `reason` is `DEFERRAL` may be released only once the current logical UTC date is strictly later than the donor's `deferral_until`."
    PRD §3.2: "Any attempt outside those rules, including a release aimed at a window that is already `RELEASED`, is refused with `ERR_WINDOW_NOT_RELEASABLE`."
    PRD §3.5: "The supplied `deferral_until` is written onto the donor, and the system creates an `ACTIVE` calendar window for that donor with `reason` `DEFERRAL`, spanning the current logical UTC date through `deferral_until` inclusive, which raises the donor's `blocked_day_count` by that window's `day_count`."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."

    Design: Difficulty/cross_entity_state_dependency/deferral_window_release_depends_on_donor_deferral_until_date
    """
    ctx = _setup_deferred_donor_with_a_deferral_window()
    window = ctx["window"]
    assert window["date_from"] == C.CLOCK_EPOCH[:10], (
        "Setup failed: the window opens on the current logical date, got "
        f"{window['date_from']}"
    )
    assert window["date_to"] == DEFERRAL_UNTIL_DATE, (
        f"Setup failed: the window closes on deferral_until, got {window['date_to']}"
    )
    assert window["day_count"] == DEFERRAL_WINDOW_DAY_COUNT, (
        "Setup failed: 2026-08-01 through 2026-09-30 inclusive is 61 days, got "
        f"{window['day_count']}"
    )
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["availability_status"] == "TEMPORARILY_DEFERRED", (
        f"Setup failed: the donor must be deferred, got {donor['availability_status']}"
    )
    assert donor["deferral_until"] == DEFERRAL_UNTIL_DATE, (
        f"Setup failed: deferral_until must be recorded, got {donor['deferral_until']}"
    )
    assert donor["blocked_day_count"] == DEFERRAL_WINDOW_DAY_COUNT, (
        f"Setup failed: the window blocks 61 days, got {donor['blocked_day_count']}"
    )

    # The logical date is still 2026-08-01, two months short of the donor's own
    # deferral_until, which is the field the release consults.
    response = api.release_unavailability_window(
        ctx["donor_id"], ctx["window_id"], ctx["liaison_headers"]
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_NOT_RELEASABLE.value)

    after_window = fixtures.find_windows(ctx["donor_id"], reason="DEFERRAL")[0]
    assert after_window["status"] == "ACTIVE", (
        f"the refused release leaves the window ACTIVE, got {after_window['status']}"
    )
    assert after_window["released_at"] is None, (
        f"the refused release stamps nothing, got {after_window['released_at']}"
    )
    after_donor = fixtures.read_donor(ctx["donor_id"])
    assert after_donor["availability_status"] == "TEMPORARILY_DEFERRED", (
        "the refused release cannot restore availability, got "
        f"{after_donor['availability_status']}"
    )
    assert after_donor["blocked_day_count"] == DEFERRAL_WINDOW_DAY_COUNT, (
        f"the refused release frees no days, got {after_donor['blocked_day_count']}"
    )
    assert after_donor["deferral_until"] == DEFERRAL_UNTIL_DATE, (
        f"the refused release keeps deferral_until, got {after_donor['deferral_until']}"
    )


def test_deferral_window_release_is_refused_on_the_deferral_until_date_itself(api):
    """PRD §3.2: "A window whose `reason` is `DEFERRAL` may be released only once the current logical UTC date is strictly later than the donor's `deferral_until`."
    PRD §3.2: "Any attempt outside those rules, including a release aimed at a window that is already `RELEASED`, is refused with `ERR_WINDOW_NOT_RELEASABLE`."
    PRD §2.4: "Date-valued fields (`conditioning_start_date`, `deferral_until`, `collection_date`, `date_from` and `date_to`) are whole UTC calendar days written as `YYYY-MM-DD`, and every comparison involving them is a calendar-day comparison in UTC."

    Design: Difficulty/cross_entity_state_dependency/deferral_window_release_depends_on_donor_deferral_until_date
    """
    ctx = _setup_deferred_donor_with_a_deferral_window()

    # The last instant of the deferral_until day itself: later in the day, but not
    # a later calendar day, and the comparison is a calendar-day one.
    fixtures.set_clock(ON_DEFERRAL_UNTIL_INSTANT)
    response = api.release_unavailability_window(
        ctx["donor_id"], ctx["window_id"], ctx["liaison_headers"]
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_NOT_RELEASABLE.value)

    after_window = fixtures.find_windows(ctx["donor_id"], reason="DEFERRAL")[0]
    assert after_window["status"] == "ACTIVE", (
        "the deferral date is not yet strictly past, so the window stays ACTIVE, got "
        f"{after_window['status']}"
    )
    after_donor = fixtures.read_donor(ctx["donor_id"])
    assert after_donor["availability_status"] == "TEMPORARILY_DEFERRED", (
        f"the donor stays deferred, got {after_donor['availability_status']}"
    )
    assert after_donor["blocked_day_count"] == DEFERRAL_WINDOW_DAY_COUNT, (
        f"no days are freed, got {after_donor['blocked_day_count']}"
    )


def test_deferral_window_release_succeeds_the_day_after_deferral_until(api):
    """PRD §3.2: "A window whose `reason` is `DEFERRAL` may be released only once the current logical UTC date is strictly later than the donor's `deferral_until`."
    PRD §3.2: "A successful release sets the window's `status` to `RELEASED`, stamps `released_at` from the logical clock, and lowers the donor's `blocked_day_count` by that window's `day_count`; the call returns no body."
    PRD §3.2: "Releasing the last `ACTIVE` `DEFERRAL` window of a `TEMPORARILY_DEFERRED` donor also restores the donor's `availability_status` to `AVAILABLE` and clears `deferral_until` back to null."
    PRD §4: "Releasing a donor calendar window returns `204 No Content` with no body."

    Design: Difficulty/cross_entity_state_dependency/deferral_window_release_depends_on_donor_deferral_until_date
    """
    ctx = _setup_deferred_donor_with_a_deferral_window()

    # One calendar day past deferral_until: now strictly later.
    fixtures.set_clock(DAY_AFTER_DEFERRAL_UNTIL_INSTANT)
    response = api.release_unavailability_window(
        ctx["donor_id"], ctx["window_id"], ctx["liaison_headers"]
    )
    assertions.assert_no_content(response)

    released = fixtures.find_windows(ctx["donor_id"], reason="DEFERRAL")[0]
    assert released["status"] == "RELEASED", (
        f"the successful release moves the window to RELEASED, got {released['status']}"
    )
    assert released["released_at"] is not None, (
        "the successful release stamps released_at from the logical clock"
    )
    assert _instant(released["released_at"]) == _instant(DAY_AFTER_DEFERRAL_UNTIL_INSTANT), (
        f"released_at is the releasing instant, got {released['released_at']}"
    )
    assert released["day_count"] == DEFERRAL_WINDOW_DAY_COUNT, (
        f"the released window keeps its own day_count, got {released['day_count']}"
    )

    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["blocked_day_count"] == 0, (
        "a `RELEASED` window contributes no days, so the count returns to zero, got "
        f"{donor['blocked_day_count']}"
    )
    assert donor["availability_status"] == "AVAILABLE", (
        "releasing the last ACTIVE DEFERRAL window restores availability, got "
        f"{donor['availability_status']}"
    )
    assert donor["deferral_until"] is None, (
        f"the lapse clears deferral_until back to null, got {donor['deferral_until']}"
    )

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "DEFERRED", (
        "the calendar release is a donor-level act and does not itself re-admit the "
        f"candidate, got {candidate['status']}"
    )
