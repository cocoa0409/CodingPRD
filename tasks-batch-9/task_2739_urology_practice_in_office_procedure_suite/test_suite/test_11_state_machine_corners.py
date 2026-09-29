"""
State machines of the Urology Procedure Suite contract.

Each test here pins one edge or one resting position of one of the contract's
state machines: the two independent dimensions a procedure case is born into,
the intact branch of the specimen chain of custody, the cross-entity
precondition that blocks completion while a container is still in the room, the
counter and version side effects of closing a surveillance recall, the dead end
a cancelled case represents, the non-idempotence of check-in, and the two-hop
waitlist path into an accepted pelvic health referral.

Every test builds its own world through the API — the service is restarted with
an empty database before each one — and every identity is threaded from the
Provider row it belongs to, because six of the seven roles are entity-backed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_CASE_TRANSITION,
    ERR_INVALID_RECALL_TRANSITION,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_fields,
    assert_null_fields,
    assert_specimen_dimensions,
    assert_version_advanced,
    assert_version_unchanged,
    assert_visit_counters,
)
from test_helpers.constants import (
    BASIS_PROTOCOL_ANCHORED,
    CASE_CANCELLED,
    CASE_COMPLETED,
    CASE_DRAFT,
    CASE_IN_ROOM,
    CHAIN_ACCESSIONED,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CLEARANCE_PENDING_PREP,
    CONDITION_INTACT,
    DECISION_ACCEPT,
    DECISION_WAITLIST,
    DEVICE_STATE_NONE,
    NOTIFY_NOT_REQUIRED,
    PROGRAM_PELVIC_FLOOR_PT,
    PROTOCOL_STONE,
    RECALL_CLOSED,
    RECALL_SCHEDULED_DUE,
    REFERRAL_ACCEPTED,
    REFERRAL_REQUESTED,
    REFERRAL_WAITLISTED,
    ROOM_TYPE_CYSTO_SUITE,
    SPECIMEN_PROSTATE_CORE,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)
from test_helpers.fixtures import (
    build_roster,
    build_simple_practice,
    check_in_case,
    clear_case,
    collect_specimen,
    create_patient,
    draft_case,
    read_case,
    read_patient,
    read_recall,
    read_referral,
    read_room,
    schedule_new_case,
    set_clock,
)


# ─── Local scenario builders ────────────────────────────────────────────────
def _cystoscopy_practice(api, patient_egfr=66):
    """
    The smallest working suite for a cystoscopy: one room, one procedure type
    with no obligations and no preparation codes, and one patient.
    """
    return build_simple_practice(
        api,
        procedure_code=TYPE_CYSTOSCOPY,
        room_type=ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 20,
            "cleanup_class": CLEANUP_HIGH,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={"egfr": patient_egfr},
    )


def _biopsy_case_with_collected_container(api):
    """
    A prostate biopsy case taken to IN_ROOM at 2026-09-15T09:00:00Z with one
    container collected in the room, after which the clock stands at 10:00.
    """
    practice = build_simple_practice(
        api,
        procedure_code=TYPE_PROSTATE_BIOPSY,
        room_type=ROOM_TYPE_CYSTO_SUITE,
        type_kwargs={
            "base_minutes": 30,
            "cleanup_class": CLEANUP_LOW,
            "requires_specimen": True,
            "required_prep_codes": [],
        },
        room_kwargs={"name": "Cysto A", "turnover_minutes": 10},
        patient_kwargs={"egfr": 60},
    )
    roster = practice["roster"]
    set_clock(api, "2026-09-15T09:00:00Z")
    case = schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        "2026-09-15T09:00:00Z",
    )
    clear_case(api, roster, case["id"])
    check_in_case(api, roster, case["id"])
    specimen = collect_specimen(
        api,
        roster,
        case["id"],
        specimen_type=SPECIMEN_PROSTATE_CORE,
        container_label="IV-CORE-01",
        site_code="LEFT_BASE",
    )
    set_clock(api, "2026-09-15T10:00:00Z")
    return practice, case, specimen


def _patient_for_recalls(api, mrn):
    """One urologist and one patient, with the logical clock at 2026-09-01."""
    roster = build_roster(api)
    patient = create_patient(
        api,
        roster.urologist,
        mrn=mrn,
        full_name="Elin Kaas",
        date_of_birth="1970-11-02",
        egfr=70,
    )
    set_clock(api, "2026-09-01T08:00:00Z")
    return roster, patient


def _open_stone_recall(api, roster, patient, expected_patient_version):
    """Open a STONE/LOW surveillance recall anchored on the clock date."""
    return api.create_surveillance_recall(
        f.surveillance_recall_payload(
            patient_id=patient["id"],
            expected_patient_version=expected_patient_version,
            protocol=PROTOCOL_STONE,
            risk_tier=TIER_LOW,
            anchor_date="2026-09-01",
        ),
        roster.urologist_headers,
    )


# ─── A case is born into two independent state dimensions ───────────────────
def test_new_case_is_born_draft_and_pending_prep(api):
    """PRD §3.2: "The new case is created with `schedule_status` `DRAFT`,
    `clearance_status` `PENDING_PREP`, `device_state` `NONE` and
    `acknowledged_prep_codes` as the empty array."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/sm_initial_state_case_two_dimensions_at_once
    """
    practice = _cystoscopy_practice(api)
    roster = practice["roster"]
    set_clock(api, "2026-09-14T07:00:00Z")

    response = api.create_procedure_case(
        f.procedure_case_payload(
            patient_id=practice["patient"]["id"],
            procedure_type_id=practice["procedure_type"]["id"],
            room_id=practice["room"]["id"],
            primary_provider_id=roster.urologist["id"],
            scheduled_start_at="2026-09-14T09:00:00Z",
            indication_note="recurrent haematuria",
        ),
        roster.scheduler_headers,
    )
    case = validate_success(response, expected_status=201)

    assert_case_dimensions(case, CASE_DRAFT, CLEARANCE_PENDING_PREP)
    assert_fields(
        case,
        device_state=DEVICE_STATE_NONE,
        acknowledged_prep_codes=[],
        version=1,
    )


def test_drafting_a_case_leaves_the_room_unoccupied(api):
    """PRD §3.2: "Crucially, **a draft occupies nothing**: it holds neither the
    room nor the urologist, so no overlap check runs at drafting time and two
    drafts may sit on top of each other indefinitely."
    PRD §3.1: "Each room also exposes `occupied_block_count`, a derived count of
    the cases naming that room whose `schedule_status` is `SCHEDULED`, `IN_ROOM`
    or `COMPLETED`; it initialises to 0."

    Design: Corner/state_machines/sm_initial_state_case_two_dimensions_at_once
    """
    practice = _cystoscopy_practice(api)
    roster = practice["roster"]
    room = practice["room"]
    set_clock(api, "2026-09-14T07:00:00Z")

    room_before = read_room(api, roster, room["id"])
    assert_fields(room_before, occupied_block_count=0, version=1)

    case = draft_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        room,
        "2026-09-14T09:00:00Z",
    )
    assert case["schedule_status"] == CASE_DRAFT, (
        f"expected the new case to be DRAFT, got {case['schedule_status']!r}"
    )

    room_after = read_room(api, roster, room["id"])
    assert_fields(room_after, occupied_block_count=0, version=1)
    assert_version_unchanged(room_before, room_after)


# ─── The intact branch of the specimen chain of custody ─────────────────────
def test_intact_container_advances_chain_to_accessioned(api):
    """PRD §3.8: "An `INTACT` container simply advances `chain_status` from
    `COLLECTED` to `ACCESSIONED` and does nothing else."
    PRD §3.8: "Both branches record `accession_number`, `received_at` and
    `condition_on_receipt`."

    Design: Corner/state_machines/sm_valid_transition_specimen_accession_intact
    """
    practice, _case, specimen = _biopsy_case_with_collected_container(api)
    roster = practice["roster"]

    response = api.accession_specimen(
        specimen["id"],
        f.accession_payload(
            received_at="2026-09-15T10:00:00Z",
            accession_number="ACC-2026-0001",
            condition_on_receipt=CONDITION_INTACT,
        ),
        roster.pathologist_headers,
    )
    accessioned = validate_success(response, expected_status=200)

    assert_specimen_dimensions(accessioned, CHAIN_ACCESSIONED, NOTIFY_NOT_REQUIRED)
    assert_fields(
        accessioned,
        condition_on_receipt=CONDITION_INTACT,
        accession_number="ACC-2026-0001",
        received_at="2026-09-15T10:00:00.000Z",
        notification_attempt_count=0,
    )
    assert_null_fields(accessioned, "escalation_due_at", "pathology_result")


def test_intact_accession_fires_no_notification_or_recall_cascade(api):
    """PRD §3.8: "The notification dimension stays at `NOT_REQUIRED`, and no
    recall is created."
    PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."

    Design: Corner/state_machines/sm_valid_transition_specimen_accession_intact
    """
    practice, _case, specimen = _biopsy_case_with_collected_container(api)
    roster = practice["roster"]
    patient = practice["patient"]

    validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at="2026-09-15T10:00:00Z",
                accession_number="ACC-2026-0001",
                condition_on_receipt=CONDITION_INTACT,
            ),
            roster.pathologist_headers,
        ),
        expected_status=200,
    )

    patient_after = read_patient(api, roster, patient["id"])
    assert_fields(patient_after, open_notification_count=0, outstanding_recall_count=0)

    recalls, meta = validate_paginated(
        api.list_surveillance_recalls(roster.urologist_headers, patient_id=patient["id"])
    )
    assert meta["total_count"] == 0, (
        "the intact branch must create no surveillance recall, but the patient "
        f"has {meta['total_count']}: {recalls}"
    )


# ─── Completion is blocked while a container is still in the room ───────────
def test_completion_blocked_while_a_container_is_still_collected(api):
    """PRD §3.7: "There is one further precondition and it is easy to miss:
    **every specimen belonging to the case must already have left the room**,
    meaning no specimen with this `case_id` may still have `chain_status`
    `COLLECTED`."
    PRD §3.7: "A case with an unhandled container is refused with
    `ERR_INVALID_CASE_TRANSITION`."
    PRD §3.7: "On success `completed_at` records the logical clock instant, and
    the room's `occupied_block_count` is recomputed — a completed case still
    occupies its historical block, so the count does not fall."

    Design: Corner/state_machines/sm_precondition_enforcement_complete_blocked_by_collected_specimen
    """
    practice, case, specimen = _biopsy_case_with_collected_container(api)
    roster = practice["roster"]

    blocked = api.complete_case(
        case["id"],
        f.complete_case_payload(outcome_note="six cores taken"),
        roster.urologist_headers,
    )
    validate_error(blocked, ERR_INVALID_CASE_TRANSITION)

    still_in_room = read_case(api, roster, case["id"])
    assert still_in_room["schedule_status"] == CASE_IN_ROOM, (
        "a rejected completion must leave the case IN_ROOM, got "
        f"{still_in_room['schedule_status']!r}"
    )
    assert_null_fields(still_in_room, "completed_at")

    # The container leaves the room: the same call must now stand.
    validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at="2026-09-15T10:00:00Z",
                accession_number="ACC-2026-0002",
                condition_on_receipt=CONDITION_INTACT,
            ),
            roster.pathologist_headers,
        ),
        expected_status=200,
    )

    completed = validate_success(
        api.complete_case(
            case["id"],
            f.complete_case_payload(outcome_note="six cores taken"),
            roster.urologist_headers,
        ),
        expected_status=200,
    )
    assert_fields(
        completed,
        schedule_status=CASE_COMPLETED,
        completed_at="2026-09-15T10:00:00.000Z",
    )


# ─── Closing a recall recomputes the patient chart ──────────────────────────
def test_opening_a_stone_recall_recounts_the_patient_chart(api):
    """PRD §3.9: "A `STONE` recall is due in 24 months at `LOW` risk, 12 months
    at `INTERMEDIATE` and 6 months at `HIGH`."
    PRD §3.9: "The new row is stored with `status` `SCHEDULED_DUE`, `lapse_days`
    0, `due_basis` `PROTOCOL_ANCHORED`, and `predecessor_recall_id` null unless
    there is something to supersede — and if there is, the same supersession
    rule that governs cascade-created recalls applies here: every other recall
    of the same `patient_id` and `protocol` whose `status` is `SCHEDULED_DUE` or
    `OVERDUE` becomes `SUPERSEDED`, the newest of them is recorded as this row's
    `predecessor_recall_id`, and the patient's `outstanding_recall_count` is
    recomputed with the patient's `version` incremented by 1."
    PRD §2.4: "When a cascade recomputes a patient's derived counters, the
    patient's `version` increments."

    Design: Corner/state_machines/sm_side_effect_execution_recall_close_recounts_patient
    """
    roster, patient = _patient_for_recalls(api, mrn="MRN-5013")
    patient_before = read_patient(api, roster, patient["id"])

    recall = validate_success(
        _open_stone_recall(api, roster, patient, patient_before["version"]),
        expected_status=201,
    )
    assert_fields(
        recall,
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        due_on="2028-09-01",
        lapse_days=0,
    )
    assert_null_fields(recall, "predecessor_recall_id", "satisfying_case_id")

    patient_after = read_patient(api, roster, patient["id"])
    assert_fields(patient_after, outstanding_recall_count=1)
    assert_version_advanced(patient_before, patient_after)


def test_closing_a_recall_recomputes_counter_and_bumps_patient_version(api):
    """PRD §3.9: "Or a `Urologist` can **close** it administratively — a
    deceased patient, a transfer of care, a retired protocol — supplying a
    `closed_reason` that is stored on the row, which again recomputes the
    patient's `outstanding_recall_count` and increments the patient's `version`
    by 1."

    Design: Corner/state_machines/sm_side_effect_execution_recall_close_recounts_patient
    """
    roster, patient = _patient_for_recalls(api, mrn="MRN-5013")
    recall = validate_success(
        _open_stone_recall(api, roster, patient, patient["version"]),
        expected_status=201,
    )
    patient_before_close = read_patient(api, roster, patient["id"])
    assert_fields(patient_before_close, outstanding_recall_count=1)

    closed = validate_success(
        api.close_surveillance_recall(
            recall["id"],
            f.recall_close_payload(closed_reason="PATIENT_DECLINED"),
            roster.urologist_headers,
        ),
        expected_status=200,
    )
    assert_fields(closed, status=RECALL_CLOSED, closed_reason="PATIENT_DECLINED")

    patient_after_close = read_patient(api, roster, patient["id"])
    assert_fields(patient_after_close, outstanding_recall_count=0)
    assert_version_advanced(patient_before_close, patient_after_close)


def test_second_close_of_a_closed_recall_is_rejected(api):
    """PRD §3.9: "Closing is permitted only from `SCHEDULED_DUE` or `OVERDUE`;
    closing an already-satisfied, already-superseded or already-closed recall is
    refused with `ERR_INVALID_RECALL_TRANSITION`."
    PRD §3.9: "`SATISFIED`, `SUPERSEDED` and `CLOSED` are all terminal."

    Design: Corner/state_machines/sm_terminal_state_lockdown_closed_recall_cannot_close_again
    """
    roster, patient = _patient_for_recalls(api, mrn="MRN-5014")
    recall = validate_success(
        _open_stone_recall(api, roster, patient, patient["version"]),
        expected_status=201,
    )
    validate_success(
        api.close_surveillance_recall(
            recall["id"],
            f.recall_close_payload(closed_reason="PATIENT_DECLINED"),
            roster.urologist_headers,
        ),
        expected_status=200,
    )
    patient_after_close = read_patient(api, roster, patient["id"])

    rejected = api.close_surveillance_recall(
        recall["id"],
        f.recall_close_payload(closed_reason="DUPLICATE"),
        roster.urologist_headers,
    )
    validate_error(rejected, ERR_INVALID_RECALL_TRANSITION)

    # The refused call must have written nothing at all.
    unchanged = read_recall(api, roster, recall["id"])
    assert_fields(
        unchanged, status=RECALL_CLOSED, closed_reason="PATIENT_DECLINED"
    )

    patient_now = read_patient(api, roster, patient["id"])
    assert_fields(patient_now, outstanding_recall_count=0)
    assert_version_unchanged(patient_after_close, patient_now)


# ─── A cancelled case is a dead end ─────────────────────────────────────────
def test_cancelled_case_can_neither_be_rescheduled_nor_scheduled(api):
    """PRD §3.3: "Cancellation is available to a `Scheduler` or a `Urologist`
    from either `DRAFT` or `SCHEDULED`, and it is the system's compensating
    action."
    PRD §3.3: "The payload carries a `cancel_reason_code`, which is recorded on
    the case."
    PRD §3.3: "Rescheduling is also the `Scheduler`'s exclusive act and it
    leaves `schedule_status` at `SCHEDULED` — a self-loop rather than a
    transition."
    PRD §3.3: "Committing a case to the calendar is the `Scheduler`'s exclusive
    act, and it advances `schedule_status` from `DRAFT` to `SCHEDULED`."
    PRD §2.8: "The target row is in a state from which the requested action is
    declared in §3."

    Design: Corner/state_machines/sm_invalid_transition_reschedule_after_cancel
    """
    practice = _cystoscopy_practice(api)
    roster = practice["roster"]
    set_clock(api, "2026-09-14T07:00:00Z")

    case = draft_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        "2026-09-14T09:00:00Z",
    )
    cancelled = validate_success(
        api.cancel_case(
            case["id"],
            f.cancel_payload(cancel_reason_code="PATIENT_REQUEST"),
            roster.scheduler_headers,
        ),
        expected_status=200,
    )
    assert_fields(
        cancelled,
        schedule_status=CASE_CANCELLED,
        cancel_reason_code="PATIENT_REQUEST",
    )

    # Moving a cancelled case: the self-loop is declared from SCHEDULED only.
    moved = api.reschedule_case(
        case["id"],
        f.reschedule_payload(scheduled_start_at="2026-09-14T11:00:00Z"),
        roster.scheduler_headers,
    )
    validate_error(moved, ERR_INVALID_CASE_TRANSITION)

    # Nor can it be committed again: that edge leaves DRAFT, not CANCELLED.
    # The room's version is read fresh so the stale-version guard cannot fire
    # ahead of the transition check.
    current_room = read_room(api, roster, practice["room"]["id"])
    recommitted = api.schedule_case(
        case["id"],
        f.schedule_payload(current_room["version"]),
        roster.scheduler_headers,
    )
    validate_error(recommitted, ERR_INVALID_CASE_TRANSITION)

    still_cancelled = read_case(api, roster, case["id"])
    assert_fields(
        still_cancelled,
        schedule_status=CASE_CANCELLED,
        cancel_reason_code="PATIENT_REQUEST",
        scheduled_start_at="2026-09-14T09:00:00.000Z",
    )


# ─── Check-in is not idempotent ─────────────────────────────────────────────
def test_second_check_in_rejected_and_checked_in_at_preserved(api):
    """PRD §3.7: "Bringing the patient into the room is a `ProcedureNurse`'s
    exclusive act and takes no payload; it advances `schedule_status` from
    `SCHEDULED` to `IN_ROOM`."
    PRD §3.7: "On success the case's `checked_in_at` records the logical clock
    instant and `blocking_reason_codes` collapses to the empty array."
    PRD §3.7: "Checking in a case that is not `SCHEDULED` — including a second
    check-in of a case already `IN_ROOM` — is refused with
    `ERR_INVALID_CASE_TRANSITION`."

    Design: Corner/state_machines/sm_idempotency_second_check_in_rejected
    """
    practice = _cystoscopy_practice(api)
    roster = practice["roster"]
    set_clock(api, "2026-09-14T09:00:00Z")

    case = schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        "2026-09-14T09:00:00Z",
    )
    clear_case(api, roster, case["id"])

    first = check_in_case(api, roster, case["id"])
    assert_fields(
        first,
        schedule_status=CASE_IN_ROOM,
        checked_in_at="2026-09-14T09:00:00.000Z",
        blocking_reason_codes=[],
    )
    after_first = read_case(api, roster, case["id"])

    # Twenty minutes later the nurse tries again. A repeat is not a no-op.
    set_clock(api, "2026-09-14T09:20:00Z")
    second = api.check_in_case(case["id"], {}, roster.nurse_headers)
    validate_error(second, ERR_INVALID_CASE_TRANSITION)

    after_second = read_case(api, roster, case["id"])
    assert_fields(
        after_second,
        schedule_status=CASE_IN_ROOM,
        checked_in_at="2026-09-14T09:00:00.000Z",
    )
    assert_version_unchanged(after_first, after_second)


# ─── The waitlist detour into an accepted referral ──────────────────────────
def _requested_referral_off_a_completed_case(api, requested_visits=3):
    """
    Run one cystoscopy through to completion and open a pelvic floor referral
    against it, so the referral has a source case that has reached `COMPLETED`.
    """
    practice = _cystoscopy_practice(api, patient_egfr=80)
    roster = practice["roster"]
    set_clock(api, "2026-09-15T09:00:00Z")
    case = schedule_new_case(
        api,
        roster,
        practice["patient"],
        practice["procedure_type"],
        practice["room"],
        "2026-09-15T09:00:00Z",
    )
    clear_case(api, roster, case["id"])
    check_in_case(api, roster, case["id"])
    completed = validate_success(
        api.complete_case(
            case["id"],
            f.complete_case_payload(outcome_note="no lesion seen"),
            roster.urologist_headers,
        ),
        expected_status=200,
    )
    assert_fields(completed, schedule_status=CASE_COMPLETED)

    referral = validate_success(
        api.create_pelvic_health_referral(
            f.referral_payload(
                patient_id=practice["patient"]["id"],
                source_case_id=case["id"],
                program=PROGRAM_PELVIC_FLOOR_PT,
                requested_visits=requested_visits,
            ),
            roster.urologist_headers,
        ),
        expected_status=201,
    )
    return roster, referral


def test_referral_starts_requested_and_waitlists_at_position_one(api):
    """PRD §3.10: "The new referral starts at `status` `REQUESTED` with
    `visits_authorized`, `visits_used`, `visits_remaining` and
    `visits_forfeited` all 0, and with `waitlist_position`, `therapy_start_by`,
    `first_visit_date` and `decline_reason` all null."
    PRD §3.10: "`WAITLIST` is accepted only from `REQUESTED` and grants a queue
    position instead of a ledger: `waitlist_position` becomes 1 plus the number
    of referrals in the same `program` already sitting at `status` `WAITLISTED`,
    counted immediately before this mutation is applied."

    Design: Corner/state_machines/sm_valid_transition_referral_waitlist_then_accept
    """
    roster, referral = _requested_referral_off_a_completed_case(api)

    assert_fields(referral, status=REFERRAL_REQUESTED)
    assert_visit_counters(referral, authorized=0, used=0, remaining=0, forfeited=0)
    assert_null_fields(
        referral,
        "waitlist_position",
        "therapy_start_by",
        "first_visit_date",
        "decline_reason",
    )

    # The programme has no capacity today, so the referral takes a queue place.
    # It is the first waitlisted referral of its programme.
    waitlisted = validate_success(
        api.decide_pelvic_health_referral(
            referral["id"],
            f.referral_decision_payload(DECISION_WAITLIST),
            roster.coordinator_headers,
        ),
        expected_status=200,
    )
    assert_fields(
        waitlisted, status=REFERRAL_WAITLISTED, waitlist_position=1
    )
    assert_visit_counters(waitlisted, authorized=0, used=0, remaining=0, forfeited=0)


def test_waitlisted_referral_accepted_opens_triple_minimised_ledger(api):
    """PRD §3.10: "The waitlist is a detour, not a dead end — a waitlisted
    referral can later be accepted, rejoining the accepted branch with exactly
    the acceptance side effects above."
    PRD §3.10: "On acceptance `visits_authorized` becomes the smallest of three
    numbers — the `requested_visits` recorded on the referral, the
    `authorized_visits` the payer approved, and the programme's own ceiling,
    which is 8 visits for `PELVIC_FLOOR_PT`, 4 for `BEHAVIORAL_TRAINING` and 6
    for `BIOFEEDBACK`."
    PRD §3.10: "`visits_remaining` is set equal to `visits_authorized`,
    `visits_used` and `visits_forfeited` are set to 0, `waitlist_position` is
    cleared back to null, and `therapy_start_by` is set to the source case's
    `completed_at` date plus 30 days — or, for a direct referral with no source
    case, to the logical clock date plus 30 days."

    Design: Corner/state_machines/sm_valid_transition_referral_waitlist_then_accept
    """
    roster, referral = _requested_referral_off_a_completed_case(api, requested_visits=3)
    validate_success(
        api.decide_pelvic_health_referral(
            referral["id"],
            f.referral_decision_payload(DECISION_WAITLIST),
            roster.coordinator_headers,
        ),
        expected_status=200,
    )

    # The payer approves five, the programme allows eight, the clinician asked
    # for three: the smallest of the three wins.
    accepted = validate_success(
        api.decide_pelvic_health_referral(
            referral["id"],
            f.referral_decision_payload(DECISION_ACCEPT, authorized_visits=5),
            roster.coordinator_headers,
        ),
        expected_status=200,
    )
    assert_fields(
        accepted, status=REFERRAL_ACCEPTED, therapy_start_by="2026-10-15"
    )
    assert_null_fields(accepted, "waitlist_position")
    assert_visit_counters(accepted, authorized=3, used=0, remaining=3, forfeited=0)

    persisted = read_referral(api, roster, referral["id"])
    assert_fields(
        persisted, status=REFERRAL_ACCEPTED, therapy_start_by="2026-10-15"
    )
    assert_visit_counters(persisted, authorized=3, used=0, remaining=3, forfeited=0)
