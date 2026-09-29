"""
Derived-value arithmetic of the Urology Procedure Suite contract.

Five computations in this contract turn stored inputs into a single answer that
a reader can get subtly wrong: the escalation deadline a pathology result opens
(its weekend extension and its per-attempt backoff), the surveillance due date a
sweep recomputes from the patient's completed procedures, the authorised visit
count a pelvic health programme allows, and the prophylaxis agent an automatic
order resolves to. Every expectation below is a single instant, date, integer or
enum value, so an implementation that composes the terms in the wrong order, or
that reads the wrong input set, answers something different.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_visit_counters,
)
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CEFAZOLIN,
    AGENT_CIPROFLOXACIN,
    ALLERGY_CEPHALOSPORIN,
    ANTIBIOTIC_ORDERED,
    BASIS_PROTOCOL_ANCHORED,
    CHAIN_RESULTED,
    CHANNEL_PHONE,
    CHANNEL_PORTAL,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    DECISION_ACCEPT,
    NOTIFY_ATTEMPTED,
    NOTIFY_FAILED,
    NOTIFY_OUTCOME_UNREACHABLE,
    NOTIFY_PENDING,
    PROGRAM_BEHAVIORAL_TRAINING,
    PROTOCOL_BLADDER_CANCER,
    PROTOCOL_PROSTATE,
    RECALL_SCHEDULED_DUE,
    REFERRAL_ACCEPTED,
    RESULT_MALIGNANT,
    ROOM_TYPE_CYSTO_SUITE,
    ROUTE_IV,
    ROUTE_ORAL,
    SPECIMEN_PROSTATE_CORE,
    TIER_HIGH,
    TIER_INTERMEDIATE,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)

# ─── The pathology scenario, one day at a time ─────────────────────────────
FRIDAY = "2026-09-18"
WEDNESDAY = "2026-09-16"


def _setup_biopsy_specimen_awaiting_result(api, day: str):
    """
    A prostate biopsy taken at 08:00 on ``day`` whose container reached the
    laboratory intact at 08:30, with the logical clock left at 09:00 so the next
    call files the result at a known instant.

    The procedure type asks for a specimen and for nothing else, so no
    prophylaxis, scope or device gate stands between the case and its check-in.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Hana Ohm",
        date_of_birth="1959-02-02",
        egfr=62,
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    biopsy_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=True,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, f"{day}T08:00:00.000Z")
    case = fx.schedule_new_case(
        api, roster, patient, biopsy_type, room, f"{day}T08:00:00.000Z"
    )
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    specimen = fx.collect_specimen(
        api,
        roster,
        case["id"],
        specimen_type=SPECIMEN_PROSTATE_CORE,
        container_label="HO-CORE-01",
    )

    fx.set_clock(api, f"{day}T08:30:00.000Z")
    fx.accession_specimen(
        api,
        roster,
        specimen["id"],
        f"{day}T08:30:00.000Z",
        accession_number="ACC-2026-0010",
    )
    fx.set_clock(api, f"{day}T09:00:00.000Z")
    return {
        "roster": roster,
        "patient": patient,
        "case": case,
        "specimen": specimen,
    }


def test_malignant_escalation_deadline_gains_one_weekend_extension(api):
    """PRD 3.8: "The grade drives the base window: a `MALIGNANT` result must be
    communicated within 24 hours, an `ATYPICAL` result within 72 hours, a
    `BENIGN` result within 168 hours — a full week — and where no grade exists
    at all, which is the compromised-container case, the `INSUFFICIENT` window
    of 72 hours applies."
    PRD 3.8: "The anchor instant is the specimen's `result_at` when a result has
    been filed; for a compromised container, where `pathology_result` and
    `result_at` both stay null, the anchor is the logical clock instant of the
    accession itself."
    PRD 3.8: "Step two tests **that provisional instant, and only that
    instant**: if it falls on a Saturday or a Sunday in UTC, a weekend extension
    of 48 hours applies, otherwise the extension is zero."
    PRD 3.8: "Step four adds the weekend extension and the backoff to the
    provisional instant, and the sum is `escalation_due_at`."

    Design: Corner/calculations/calc_correct_result_notification_weekend_extension
    """
    scene = _setup_biopsy_specimen_awaiting_result(api, FRIDAY)

    response = api.result_specimen(
        scene["specimen"]["id"],
        factories.result_payload(RESULT_MALIGNANT),
        scene["roster"].pathologist_headers,
    )
    resulted = validate_success(response, 200)

    assert_fields(
        resulted,
        chain_status=CHAIN_RESULTED,
        pathology_result=RESULT_MALIGNANT,
        result_at="2026-09-18T09:00:00.000Z",
        notification_status=NOTIFY_PENDING,
        notification_attempt_count=0,
    )
    # Anchor 2026-09-18T09:00Z plus the 24-hour malignant window lands the
    # provisional deadline on Saturday 2026-09-19T09:00Z, which earns the
    # 48-hour weekend extension exactly once; no attempt has been counted yet,
    # so there is no backoff term at all.
    assert resulted["escalation_due_at"] == "2026-09-21T09:00:00.000Z", (
        "a malignant result filed at 2026-09-18T09:00:00.000Z whose provisional "
        "deadline falls on a Saturday must escalate at 2026-09-21T09:00:00.000Z, "
        f"got {resulted['escalation_due_at']!r}"
    )


def test_malignant_result_opens_a_high_risk_prostate_recall_and_moves_both_patient_counters(api):
    """PRD 3.8: "A result of `BENIGN`, `ATYPICAL` or `MALIGNANT` creates a recall
    for the case's patient whose `protocol` is determined by the specimen class
    (a `PROSTATE_CORE` maps to `PROSTATE`, a `BLADDER_WASHING` to
    `BLADDER_CANCER`, and a `BIOPSY_FRAGMENT` to `PROSTATE`) and whose
    `risk_tier` is determined by the grade (`MALIGNANT` maps to `HIGH`,
    `ATYPICAL` to `INTERMEDIATE`, and `BENIGN` to `LOW`), with `anchor_date` set
    to the logical clock date, `due_basis` `PROTOCOL_ANCHORED`, and
    `source_specimen_id` naming this specimen."
    PRD 3.9: "`PROSTATE` uses the same figures as `BLADDER_CANCER` — 12, 6 and 3
    months respectively."
    PRD 3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."

    Design: Corner/calculations/calc_correct_result_notification_weekend_extension
    """
    scene = _setup_biopsy_specimen_awaiting_result(api, FRIDAY)
    roster = scene["roster"]

    fx.result_specimen(api, roster, scene["specimen"]["id"], RESULT_MALIGNANT)

    recalls, meta = validate_paginated(
        api.list_surveillance_recalls(
            roster.urologist_headers, patient_id=scene["patient"]["id"]
        )
    )
    assert meta["total_count"] == 1, (
        "filing one graded result must open exactly one surveillance recall, "
        f"got total_count {meta['total_count']}"
    )
    assert_fields(
        recalls[0],
        protocol=PROTOCOL_PROSTATE,
        risk_tier=TIER_HIGH,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        anchor_date="2026-09-18",
        due_on="2026-12-18",
        status=RECALL_SCHEDULED_DUE,
        source_specimen_id=scene["specimen"]["id"],
    )

    patient = validate_success(
        api.get_patient(scene["patient"]["id"], roster.urologist_headers), 200
    )
    assert_fields(patient, open_notification_count=1, outstanding_recall_count=1)


def test_unreachable_attempts_add_backoff_only_from_the_second_attempt_onwards(api):
    """PRD 3.8: "Step three computes a backoff of 12 hours multiplied by the
    attempt count less one, floored at zero, where the attempt count is the value
    *after* the current attempt has been counted — so a first attempt contributes
    no backoff at all, a second contributes 12 hours and a third 24."
    PRD 3.8: "While the incremented `notification_attempt_count` is still
    strictly below 3, the specimen lands on `ATTEMPTED` — from `PENDING`, from
    `ATTEMPTED` itself as a self-loop, or from `ESCALATED` — and
    `escalation_due_at` is recomputed with the new attempt count, which pushes
    the deadline out by a further 12 hours each time."
    PRD 3.8: "When the incremented count reaches exactly 3, the loop is
    abandoned: `notification_status` becomes `FAILED`, `escalation_due_at` is
    still recomputed with the final count, and the patient's
    `open_notification_count` is recomputed because a failed notification also
    leaves the open set."

    Design: Corner/calculations/calc_correct_result_notification_attempt_backoff_chronology
    """
    scene = _setup_biopsy_specimen_awaiting_result(api, WEDNESDAY)
    roster = scene["roster"]
    specimen_id = scene["specimen"]["id"]

    resulted = fx.result_specimen(api, roster, specimen_id, RESULT_MALIGNANT)
    # Anchor 2026-09-16T09:00Z plus the 24-hour malignant window is a Thursday,
    # so no weekend extension ever enters this arithmetic.
    assert resulted["escalation_due_at"] == "2026-09-17T09:00:00.000Z", (
        "before any attempt the malignant deadline is the bare 24-hour window, "
        f"expected 2026-09-17T09:00:00.000Z, got {resulted['escalation_due_at']!r}"
    )

    first = validate_success(
        api.record_notification_attempt(
            specimen_id,
            factories.notification_attempt_payload(
                outcome=NOTIFY_OUTCOME_UNREACHABLE, channel=CHANNEL_PHONE
            ),
            roster.pathologist_headers,
        ),
        200,
    )
    assert_fields(
        first,
        notification_status=NOTIFY_ATTEMPTED,
        notification_attempt_count=1,
        escalation_due_at="2026-09-17T09:00:00.000Z",
    )
    assert first["escalation_due_at"] == "2026-09-17T09:00:00.000Z", (
        "a first attempt contributes 12 * (1 - 1) = 0 hours of backoff, so the "
        "deadline must not move at all, got "
        f"{first['escalation_due_at']!r}"
    )

    second = validate_success(
        api.record_notification_attempt(
            specimen_id,
            factories.notification_attempt_payload(
                outcome=NOTIFY_OUTCOME_UNREACHABLE, channel=CHANNEL_PORTAL
            ),
            roster.pathologist_headers,
        ),
        200,
    )
    assert_fields(
        second,
        notification_status=NOTIFY_ATTEMPTED,
        notification_attempt_count=2,
        escalation_due_at="2026-09-17T21:00:00.000Z",
    )

    third = validate_success(
        api.record_notification_attempt(
            specimen_id,
            factories.notification_attempt_payload(
                outcome=NOTIFY_OUTCOME_UNREACHABLE, channel=CHANNEL_PHONE
            ),
            roster.nurse_headers,
        ),
        200,
    )
    assert_fields(
        third,
        notification_status=NOTIFY_FAILED,
        notification_attempt_count=3,
        escalation_due_at="2026-09-18T09:00:00.000Z",
    )
    assert third["escalation_due_at"] == "2026-09-18T09:00:00.000Z", (
        "the third attempt still recomputes the deadline with the final count, "
        "12 * (3 - 1) = 24 hours past 2026-09-17T09:00:00.000Z, got "
        f"{third['escalation_due_at']!r}"
    )

    patient = validate_success(
        api.get_patient(scene["patient"]["id"], roster.urologist_headers), 200
    )
    assert patient["open_notification_count"] == 0, (
        "a FAILED notification leaves the open set, so the patient's "
        f"open_notification_count must fall back to 0, got "
        f"{patient['open_notification_count']}"
    )


def test_sweep_keeps_the_protocol_anchor_when_the_only_matching_case_is_still_scheduled(api):
    """PRD 3.9: "It gathers every procedure case of the same patient whose
    `schedule_status` is `COMPLETED` and whose procedure type code is one of the
    protocol's qualifying codes — cases still in `DRAFT`, `SCHEDULED` or
    `IN_ROOM`, and cases that ended in `CANCELLED` or `NO_SHOW`, are all
    excluded."
    PRD 3.9: "If that set is empty the variant falls back to the anchor: `due_on`
    is the interval added to `anchor_date` and `due_basis` is written as
    `PROTOCOL_ANCHORED`."
    PRD 3.9: "A recall anchored on 31 March with a six-month interval is due on
    30 September, not 1 October."
    PRD 3.9: "Its response carries `swept_at` holding the logical clock instant
    of the sweep, `recomputed_recall_count` for the number of recalls step 1
    recomputed, `overdue_recall_count` for the number step 2 moved into
    `OVERDUE`, `restored_recall_count` for the number step 2 pulled back to
    `SCHEDULED_DUE`, and `escalated_specimen_count` for the number of
    notifications step 3 escalated."

    Design: Corner/calculations/calc_input_set_filtering_event_anchor_ignores_open_cases
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Nils Aro", date_of_birth="1955-07-07", egfr=74
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-14T07:00:00.000Z")
    recall = fx.open_recall(
        api,
        roster,
        patient,
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_INTERMEDIATE,
        anchor_date="2026-03-31",
    )
    # The one qualifying CYSTOSCOPY is booked but never checked in or completed,
    # so the event-anchored input set stays empty.
    fx.schedule_new_case(
        api, roster, patient, cysto_type, room, "2026-09-14T09:00:00.000Z"
    )

    sweep = validate_success(api.run_recall_sweep({}, roster.admin_headers), 200)

    assert_fields(
        sweep,
        swept_at="2026-09-14T07:00:00.000Z",
        recomputed_recall_count=1,
        overdue_recall_count=0,
        restored_recall_count=0,
        escalated_specimen_count=0,
    )

    swept = validate_success(
        api.get_surveillance_recall(recall["id"], roster.urologist_headers), 200
    )
    assert_fields(
        swept,
        interval_months=6,
        anchor_date="2026-03-31",
        due_on="2026-09-30",
        due_basis=BASIS_PROTOCOL_ANCHORED,
        status=RECALL_SCHEDULED_DUE,
        lapse_days=0,
    )
    assert swept["due_basis"] == BASIS_PROTOCOL_ANCHORED, (
        "a SCHEDULED cystoscopy is not a completed procedure, so the sweep must "
        "leave the recall on its own anchor date rather than re-anchoring it, "
        f"got {swept['due_basis']!r}"
    )


def test_programme_ceiling_binds_the_authorised_visit_count_below_both_requests(api):
    """PRD 3.9: "On acceptance `visits_authorized` becomes the smallest of three
    numbers — the `requested_visits` recorded on the referral, the
    `authorized_visits` the payer approved, and the programme's own ceiling,
    which is 8 visits for `PELVIC_FLOOR_PT`, 4 for `BEHAVIORAL_TRAINING` and 6
    for `BIOFEEDBACK`."
    PRD 3.9: "`visits_remaining` is set equal to `visits_authorized`,
    `visits_used` and `visits_forfeited` are set to 0, `waitlist_position` is
    cleared back to null, and `therapy_start_by` is set to the source case's
    `completed_at` date plus 30 days — or, for a direct referral with no source
    case, to the logical clock date plus 30 days."

    Design: Corner/calculations/calc_constants_applied_program_visit_cap_binds
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Pia Renn", date_of_birth="1971-05-05", egfr=88
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-15T09:00:00.000Z")
    case = fx.schedule_new_case(
        api, roster, patient, cysto_type, room, "2026-09-15T09:00:00.000Z"
    )
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    fx.complete_case(api, roster, case["id"], headers=roster.urologist_headers)

    referral = fx.open_referral(
        api,
        roster,
        patient,
        case["id"],
        program=PROGRAM_BEHAVIORAL_TRAINING,
        requested_visits=6,
    )

    response = api.decide_pelvic_health_referral(
        referral["id"],
        factories.referral_decision_payload(DECISION_ACCEPT, authorized_visits=6),
        roster.coordinator_headers,
    )
    accepted = validate_success(response, 200)

    assert_fields(
        accepted,
        status=REFERRAL_ACCEPTED,
        program=PROGRAM_BEHAVIORAL_TRAINING,
        requested_visits=6,
        therapy_start_by="2026-10-15",
    )
    assert_null_fields(accepted, "waitlist_position")
    assert_visit_counters(accepted, authorized=4, used=0, remaining=4, forfeited=0)
    assert accepted["visits_authorized"] == 4, (
        "the BEHAVIORAL_TRAINING ceiling of 4 is smaller than both the 6 visits "
        "requested and the 6 the payer approved, so it must bind, got "
        f"{accepted['visits_authorized']}"
    )


def test_auto_prophylaxis_breaks_the_rank_tie_alphabetically_then_drops_the_allergen(api):
    """PRD 3.4: "Otherwise `AUTO` selects the eligible agent with the lowest
    protocol rank, and ties on rank are broken by agent name in ascending
    alphabetical order."
    PRD 3.4: "The joint first place in the prostate-biopsy ranking exists
    precisely to exercise that tie-break: for a patient with no relevant allergy
    the resolved `agent` is `CEFAZOLIN`, because `CEFAZOLIN` sorts before
    `CIPROFLOXACIN`; for a patient whose `antibiotic_allergy_class` is
    `CEPHALOSPORIN`, cefazolin drops out of the pool and `CIPROFLOXACIN` is
    chosen instead."
    PRD 3.4: "The selected agent's base dose is taken at full strength when the
    patient's `egfr` is at least 45, and at exactly half strength when it is
    below 45."
    PRD 3.4: "The order also records `prophylaxis_window_start_at`, fixed at one
    hour before the case's `scheduled_start_at`, and is created with `status`
    `ORDERED` and `administered_at` null."

    Design: Corner/calculations/calc_correct_result_antibiotic_protocol_rank_tie_break
    """
    roster = fx.build_roster(api)
    tolerant = fx.create_patient(
        api, roster.urologist, full_name="Ada Volk", date_of_birth="1960-01-01", egfr=62
    )
    allergic = fx.create_patient(
        api,
        roster.urologist,
        full_name="Boris Kant",
        date_of_birth="1957-03-03",
        egfr=62,
        antibiotic_allergy_class=ALLERGY_CEPHALOSPORIN,
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    biopsy_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=True,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-14T07:00:00.000Z")
    tolerant_case = fx.draft_case(
        api, roster, tolerant, biopsy_type, room, "2026-09-14T14:00:00.000Z"
    )
    allergic_case = fx.draft_case(
        api, roster, allergic, biopsy_type, room, "2026-09-14T16:00:00.000Z"
    )

    tolerant_order = validate_success(
        api.create_antibiotic_order(
            factories.antibiotic_order_payload(
                case_id=tolerant_case["id"],
                ordered_by_provider_id=roster.urologist["id"],
                requested_agent=AGENT_AUTO,
            ),
            roster.urologist_headers,
        ),
        201,
    )
    assert_fields(
        tolerant_order,
        requested_agent=AGENT_AUTO,
        agent=AGENT_CEFAZOLIN,
        dose_mg=1000,
        route=ROUTE_IV,
        status=ANTIBIOTIC_ORDERED,
        prophylaxis_window_start_at="2026-09-14T13:00:00.000Z",
    )
    assert_null_fields(tolerant_order, "administered_at")
    assert tolerant_order["agent"] == AGENT_CEFAZOLIN, (
        "with two agents tied at the lowest prostate-biopsy rank the alphabetical "
        f"tie-break must resolve to CEFAZOLIN, got {tolerant_order['agent']!r}"
    )

    allergic_order = validate_success(
        api.create_antibiotic_order(
            factories.antibiotic_order_payload(
                case_id=allergic_case["id"],
                ordered_by_provider_id=roster.urologist["id"],
                requested_agent=AGENT_AUTO,
            ),
            roster.urologist_headers,
        ),
        201,
    )
    assert_fields(
        allergic_order,
        requested_agent=AGENT_AUTO,
        agent=AGENT_CIPROFLOXACIN,
        dose_mg=500,
        route=ROUTE_ORAL,
        status=ANTIBIOTIC_ORDERED,
        prophylaxis_window_start_at="2026-09-14T15:00:00.000Z",
    )
    assert_null_fields(allergic_order, "administered_at")
    assert allergic_order["agent"] == AGENT_CIPROFLOXACIN, (
        "a CEPHALOSPORIN allergy removes cefazolin from the eligible pool, so the "
        f"tie-break loser must be selected instead, got {allergic_order['agent']!r}"
    )
