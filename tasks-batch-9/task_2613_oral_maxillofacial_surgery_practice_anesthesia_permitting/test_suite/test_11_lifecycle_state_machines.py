"""Lifecycle behaviour of the permit, inspection, block, case, evaluation,
adverse-event and inventory state machines: initial states, the legal hops that
stamp derived fields, the illegal hops that must be refused, and the cross-entity
cascades a single transition is required to run."""
from test_helpers import (
    ADMIN,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    assert_adverse_event,
    assert_block_ledger_conserved,
    assert_inspection,
    assert_lot_quantities_consistent,
    assert_permit,
    assert_reservation,
    create_adverse_event_payload,
    create_block,
    create_case,
    create_evaluation_payload,
    create_lot,
    create_patient,
    create_practice,
    create_staff,
    fetch_block,
    fetch_case,
    fetch_evaluation,
    fetch_lot,
    fetch_permit,
    fetch_practice,
    fetch_reservation,
    get_success_data,
    hold_case_on_block,
    inspection_result_payload,
    log_drill,
    make_anesthesia_coordinator_headers,
    make_quality_reviewer_headers,
    make_surgeon_headers,
    parse_iso,
    reserve_from_lot,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_success,
)


def test_lifecycle_permit_starts_in_applied_with_zeroed_compliance(api):
    """PRD 3.2: "The new permit is stamped `status` `APPLIED`, and two derived fields
    are populated immediately: `required_drill_types`, fixed by the level applied for,
    and `drill_compliance_ratio`, computed from whatever drills the practice has
    already logged."
    PRD 3.2: "`issued_at`, `expires_at`, `remediation_deadline_at`, and
    `last_enforcement_reason` are all null on a fresh application, and
    `probation_count` is 0."
    PRD 3.2: "A `MODERATE_SEDATION` permit requires those two plus `LARYNGOSPASM` and
    `CARDIAC_ARREST` — four scenarios."
    PRD 2.10: "It is recomputed from the practice's open anesthesia permit on every
    change to that permit's `status`, by a fixed mapping: when there is no open permit
    at all, or the permit's `status` is `APPLIED` or `INSPECTION_PENDING`, or the
    permit's `status` is `EXPIRED` or `REVOKED`, the privilege is `UNPERMITTED`; an
    `ACTIVE` permit yields `PERMITTED`; a permit on `PROBATION` yields `RESTRICTED`;
    and a `SUSPENDED` permit yields `SUSPENDED`."

    Design: Corner/state_machines/permit_starts_in_applied_with_zeroed_compliance
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(name="Initial OMS", state_code="OH", recovery_bay_count=2)

    data = validate_success(
        api.create_permit(
            {
                "practice_id": practice["id"],
                "permit_level": "MODERATE_SEDATION",
                "applied_on": "2026-09-01T09:00:00Z",
            },
            ADMIN,
        ),
        201,
    )

    assert_permit(data)
    assert data["status"] == "APPLIED"
    assert float(data["drill_compliance_ratio"]) == 0.00, (
        "a practice with no logged drills covers none of its required types"
    )
    assert data["probation_count"] == 0
    assert data["issued_at"] is None
    assert data["expires_at"] is None
    assert data["remediation_deadline_at"] is None
    assert data["last_enforcement_reason"] is None
    assert sorted(data["required_drill_types"]) == sorted(
        ["AIRWAY_OBSTRUCTION", "LARYNGOSPASM", "LOCAL_ANESTHETIC_TOXICITY", "CARDIAC_ARREST"]
    ), "MODERATE_SEDATION requires exactly the four cumulative scenarios"

    practice_row = validate_success(api.get_practice(practice["id"], ADMIN), 200)
    assert practice_row["sedation_privilege_state"] == "UNPERMITTED", (
        "an APPLIED permit confers no sedation privilege"
    )


def test_lifecycle_permit_activation_stamps_issue_and_expiry_dates(api):
    """PRD 3.2: "Scheduling from `APPLIED` is the one origin that moves the permit: it
    advances the permit from `APPLIED` to `INSPECTION_PENDING`, increments the permit's
    `version`, and recomputes the practice's `sedation_privilege_state`, which remains
    `UNPERMITTED` because neither `APPLIED` nor `INSPECTION_PENDING` confers privilege."
    PRD 3.2: "The score starts at 100; each minor deficiency costs 2 points, each major
    deficiency costs 7 points, and each critical deficiency costs 25 points."
    PRD 3.2: "Otherwise, if `inspection_score` is at or above 70 the inspection is
    `PASSED`; because that comparison is inclusive, a score of exactly 70 passes."
    PRD 3.2: "In every branch the computed `inspection_score` is persisted and
    `outcome_recorded_at` is stamped with the logical clock, and the practice's
    `sedation_privilege_state` is recomputed with the practice's `version` incremented."
    PRD 3.2: "A `PASSED` result on a permit in `INSPECTION_PENDING` whose
    `drill_compliance_ratio`, recomputed at that instant, is at or above 0.75 advances
    the permit to `ACTIVE`: `issued_at` is set to the logical clock if it was null,
    `expires_at` is set to `issued_at` plus 24 calendar months if it was null,
    `last_enforcement_reason` and `remediation_deadline_at` are both cleared to null,
    `sedation_privilege_state` becomes `PERMITTED`, and both the permit's and the
    practice's `version` increment."

    Design: Corner/state_machines/permit_activation_stamps_issue_and_expiry_dates
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Activation OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    permit = get_success_data(
        api.create_permit(
            {
                "practice_id": practice["id"],
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-09-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    log_drill(
        practice["id"], "AIRWAY_OBSTRUCTION", "2026-06-01T09:00:00Z",
        [surgeon["id"], monitor["id"]],
    )
    log_drill(
        practice["id"], "LOCAL_ANESTHETIC_TOXICITY", "2026-06-02T09:00:00Z",
        [surgeon["id"], monitor["id"]],
    )

    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-12T09:00:00Z"}, ADMIN
        ),
        201,
    )
    assert inspection["status"] == "SCHEDULED"
    assert fetch_permit(permit["id"])["status"] == "INSPECTION_PENDING", (
        "scheduling from APPLIED is the one origin that moves the permit"
    )

    set_clock("2026-09-12T10:00:00Z")
    result = validate_success(
        api.record_inspection_result(
            inspection["id"],
            inspection_result_payload(
                minor_deficiency_count=1, major_deficiency_count=1,
                critical_deficiency_count=0,
            ),
            ADMIN,
        ),
        200,
    )

    assert_inspection(result)
    assert result["inspection_score"] == 91, "100 less one minor (2) and one major (7)"
    assert result["status"] == "PASSED"
    assert parse_iso(result["outcome_recorded_at"]) == parse_iso("2026-09-12T10:00:00Z")

    permit_row = fetch_permit(permit["id"])
    assert permit_row["status"] == "ACTIVE"
    assert float(permit_row["drill_compliance_ratio"]) == 1.00
    assert parse_iso(permit_row["issued_at"]) == parse_iso("2026-09-12T10:00:00Z")
    assert parse_iso(permit_row["expires_at"]) == parse_iso("2028-09-12T10:00:00Z"), (
        "expires_at is issued_at plus 24 calendar months"
    )
    assert fetch_practice(practice["id"])["sedation_privilege_state"] == "PERMITTED"


def test_lifecycle_inspection_result_before_the_scheduled_instant_rejected(api):
    """PRD 3.2: "The administrator submits the inspector's three counts, which overwrite
    whatever the inspection row held before the score is computed, and the call is
    admitted only while the inspection is still `SCHEDULED` and the logical clock has
    reached or passed its `scheduled_for` instant."
    PRD 2.6: "After that prefix, the optimistic-concurrency checks of §2.7 are
    evaluated, then the clock-monotonicity check of §2.5, then the state-transition
    legality check that asks whether the anchor row's current state declares the
    requested transition at all (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — which is
    also what a repeat call of a one-shot action receives)."

    Design: Corner/state_machines/inspection_result_before_the_scheduled_instant_rejected
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Early OMS", state_code="OH", recovery_bay_count=2)
    permit = get_success_data(
        api.create_permit(
            {
                "practice_id": practice["id"],
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-09-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    inspection = schedule_inspection(permit["id"], "2026-09-12T09:00:00Z")

    response = api.record_inspection_result(
        inspection["id"],
        inspection_result_payload(
            minor_deficiency_count=0, major_deficiency_count=0, critical_deficiency_count=0
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    inspection_row = validate_success(api.get_inspection(inspection["id"], ADMIN), 200)
    assert inspection_row["status"] == "SCHEDULED"
    assert inspection_row["inspection_score"] is None
    assert inspection_row["outcome_recorded_at"] is None
    assert fetch_permit(permit["id"])["status"] == "INSPECTION_PENDING"


def test_lifecycle_block_release_moves_open_minutes_into_released_minutes(api):
    """PRD 3.3: "The action is admitted only while the block's `status` is `RESERVED`,
    and it branches on whether anything is committed."
    PRD 3.3: "When `committed_minutes` is greater than zero the block becomes
    `PARTIALLY_RELEASED`: the current `open_minutes` are added to `released_minutes`,
    `open_minutes` is set to 0, and `utilization_pct` is recomputed against the
    unchanged `block_duration_minutes` — the committed minutes are untouched, so the
    percentage does not move, and the conservation identity still holds."
    PRD 3.3: "The invariant that holds after every write is that `committed_minutes`,
    `released_minutes`, and `open_minutes` sum to exactly `block_duration_minutes`; a
    two-hundred-minute block carrying ninety committed minutes therefore reports a
    utilization of 45.00 with 110 minutes still open."

    Design: Corner/state_machines/block_release_moves_open_minutes_into_released_minutes
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Release OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Release", date_of_birth="1980-03-15T00:00:00Z"
    )
    block = create_block(
        practice["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T17:00:00Z",
        release_deadline_hours=48,
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    hold_case_on_block(case["id"], block["id"])

    before = fetch_block(block["id"])
    assert before["status"] == "RESERVED"
    assert before["committed_minutes"] == 60
    assert before["released_minutes"] == 0
    assert before["open_minutes"] == 180
    assert float(before["utilization_pct"]) == 25.00

    data = validate_success(
        api.release_block_time(
            block["id"], {"release_note": "surgeon vacation"}, SCHEDULER
        ),
        200,
    )

    assert data["status"] == "PARTIALLY_RELEASED"
    assert data["committed_minutes"] == 60
    assert data["released_minutes"] == 180, "the still-open minutes move into released"
    assert data["open_minutes"] == 0
    assert float(data["utilization_pct"]) == 25.00
    assert_block_ledger_conserved(data)

    case_row = fetch_case(case["id"])
    assert case_row["scheduling_status"] == "BLOCK_HELD", "the held case is untouched"
    assert case_row["block_id"] == block["id"]


def test_lifecycle_start_recovery_from_draft_is_an_invalid_transition(api):
    """PRD 3.4: "The case must be `CONFIRMED`, and the logical clock must be at or
    after `planned_start`."
    PRD 3.4: "The transition stamps `recovery_started_at` with the logical clock, moves
    `scheduling_status` from `CONFIRMED` to `IN_RECOVERY`, increments the case's
    `version`, and starts the interval during which the case genuinely occupies a
    recovery bay for `recovery_minutes_required` minutes."
    PRD 2.6: "After that prefix, the optimistic-concurrency checks of §2.7 are
    evaluated, then the clock-monotonicity check of §2.5, then the state-transition
    legality check that asks whether the anchor row's current state declares the
    requested transition at all (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — which is
    also what a repeat call of a one-shot action receives)."

    Design: Corner/state_machines/start_recovery_from_draft_is_an_invalid_transition
    """
    set_clock("2026-09-14T13:30:00Z")
    practice = create_practice(name="Invalid OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Draft", date_of_birth="1980-03-15T00:00:00Z"
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )

    response = api.start_recovery(case["id"], {}, make_surgeon_headers(surgeon["id"]))

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    case_row = fetch_case(case["id"])
    assert case_row["scheduling_status"] == "DRAFT"
    assert case_row["recovery_started_at"] is None
    assert case_row["version"] == case["version"], "a refused transition writes nothing"


def test_lifecycle_cancelled_case_cannot_be_cancelled_again(api):
    """PRD 3.4: "Cancellation is available from `DRAFT`, `BLOCK_HELD`, and `CONFIRMED`,
    and the `SchedulingCoordinator` supplies a `cancellation_reason` of
    `PATIENT_REQUEST`, `CLINICAL`, or `PRIVILEGE_SUSPENDED`, which is persisted on the
    case."
    PRD 3.4: "In all three origins the case's `clearance_status` is deliberately left
    untouched, and cancelling an already-`CANCELLED` or `COMPLETED` case is an
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/cancelled_case_cannot_be_cancelled_again
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Terminal OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Terminal", date_of_birth="1980-03-15T00:00:00Z"
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    first = validate_success(
        api.cancel_case(case["id"], {"cancellation_reason": "PATIENT_REQUEST"}, SCHEDULER),
        200,
    )
    assert first["scheduling_status"] == "CANCELLED"

    response = api.cancel_case(
        case["id"], {"cancellation_reason": "CLINICAL"}, SCHEDULER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    case_row = fetch_case(case["id"])
    assert case_row["cancellation_reason"] == "PATIENT_REQUEST", (
        "the refused second reason is not written"
    )


def test_lifecycle_signing_an_evaluation_twice_is_rejected(api):
    """PRD 3.5: "The evaluation must be in `DRAFT`, the acting `X-User-ID` must equal
    its `evaluator_staff_id` — anyone else is refused with `ERR_ACTOR_NOT_ASSIGNED` —
    and the parent case's `scheduling_status` must be neither `COMPLETED` nor
    `CANCELLED`."
    PRD 3.5: "Signature stamps `signed_at` with the logical clock, recomputes
    `provisional_risk_score` and re-derives `risk_band` from it against the case's
    *current* `planned_anesthesia_level` (so a case whose planned depth changed between
    drafting and signature is rescored, not left stale), advances the evaluation from
    `DRAFT` to `SIGNED`, moves the case's `clearance_status` from `NOT_EVALUATED` to
    `EVALUATED`, and increments the case's `version`."
    PRD 3.5: "Those five contributions are added into a factor subtotal, which is then
    multiplied by the level multiplier of the case's `planned_anesthesia_level`: one
    half for `LOCAL_ONLY`, eight tenths for `MINIMAL_SEDATION`, exactly one for
    `MODERATE_SEDATION`, and one and three tenths for `DEEP_SEDATION_GENERAL`."
    PRD 2.6: "After that prefix, the optimistic-concurrency checks of §2.7 are
    evaluated, then the clock-monotonicity check of §2.5, then the state-transition
    legality check that asks whether the anchor row's current state declares the
    requested transition at all (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — which is
    also what a repeat call of a one-shot action receives)."

    Design: Corner/state_machines/signing_an_evaluation_twice_is_rejected
    """
    set_clock("2026-09-14T12:00:00Z")
    practice = create_practice(name="Idem OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    author = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Nia Author", monitoring_certified=True
    )
    patient = create_patient(
        practice["id"], full_name="Pat Idem", date_of_birth="1980-03-15T00:00:00Z"
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    coordinator = make_anesthesia_coordinator_headers(author["id"])
    evaluation = get_success_data(
        api.create_evaluation(
            case["id"],
            create_evaluation_payload(
                author["id"], case["version"], asa_class_recorded=2,
                airway_class_recorded=2, comorbidity_count=0,
            ),
            coordinator,
        )
    )
    signed = get_success_data(api.sign_evaluation(evaluation["id"], {}, coordinator))
    assert signed["status"] == "SIGNED"
    assert float(signed["provisional_risk_score"]) == 10.0
    assert signed["risk_band"] == "LOW"
    assert parse_iso(signed["signed_at"]) == parse_iso("2026-09-14T12:00:00Z")

    response = api.sign_evaluation(evaluation["id"], {}, coordinator)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    evaluation_row = fetch_evaluation(evaluation["id"])
    assert evaluation_row["status"] == "SIGNED"
    assert parse_iso(evaluation_row["signed_at"]) == parse_iso("2026-09-14T12:00:00Z"), (
        "the refused second signature does not move signed_at"
    )
    assert fetch_case(case["id"])["clearance_status"] == "EVALUATED"


def test_lifecycle_closing_an_event_syncs_the_practice_open_event_counter(api):
    """PRD 3.1: "`open_adverse_event_count` is the number of adverse events filed
    against cases of this practice whose own `status` is anything other than `CLOSED`."
    PRD 3.8: "`reporting_deadline_at` is `occurred_at` plus 24 hours for a `SENTINEL`
    event, plus 72 hours for a `SEVERE` one, plus 7 days for a `MODERATE` one, and plus
    30 days for a `MINOR` one."
    PRD 3.8: "Opening moves `status` from `REPORTED` to `UNDER_MORBIDITY_REVIEW` and
    persists the `reviewer_staff_id` on the event."
    PRD 3.8: "`status` moves from `UNDER_MORBIDITY_REVIEW` to `REVIEW_SIGNED_OFF`."
    PRD 3.8: "The event must be in `REVIEW_SIGNED_OFF`, and the join condition is that
    an event whose `severity` is `SEVERE` or `SENTINEL` must already have
    `regulator_notified` true; a signed-off severe event with no recorded notification
    is refused with `ERR_REGULATOR_NOTIFICATION_REQUIRED` (HTTP 409), while `MINOR` and
    `MODERATE` events may close with the flag still false."
    PRD 3.8: "Closure moves `status` to the terminal `CLOSED`, recomputes the practice's
    `open_adverse_event_count` so this event drops out of it, and increments the
    practice's `version`."

    Design: Corner/state_machines/closing_an_event_syncs_the_practice_open_event_counter
    """
    set_clock("2026-09-14T15:00:00Z")
    practice = create_practice(name="Ledger OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    reviewer = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Quinn Reviewer", monitoring_certified=True
    )
    patient = create_patient(
        practice["id"], full_name="Pat Ledger", date_of_birth="1980-03-15T00:00:00Z"
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    event = get_success_data(
        api.create_adverse_event(
            create_adverse_event_payload(
                case["id"],
                event_type="PROLONGED_RECOVERY",
                severity="MODERATE",
                occurred_at="2026-09-14T14:30:00Z",
                narrative="Extended emergence, no intervention required.",
            ),
            make_surgeon_headers(surgeon["id"]),
        )
    )

    assert_adverse_event(event)
    assert event["status"] == "REPORTED"
    assert parse_iso(event["reporting_deadline_at"]) == parse_iso("2026-09-21T14:30:00Z"), (
        "a MODERATE event is due 7 days after it occurred"
    )
    assert event["late_report"] is False
    assert event["regulator_notified"] is False
    practice_before = fetch_practice(practice["id"])
    assert practice_before["open_adverse_event_count"] == 1

    reviewer_headers = make_quality_reviewer_headers(reviewer["id"])
    opened = validate_success(
        api.morbidity_review(
            event["id"], {"action": "OPEN", "reviewer_staff_id": reviewer["id"]},
            reviewer_headers,
        ),
        200,
    )
    assert opened["status"] == "UNDER_MORBIDITY_REVIEW"
    assert opened["reviewer_staff_id"] == reviewer["id"]
    assert fetch_practice(practice["id"])["open_adverse_event_count"] == 1

    signed_off = validate_success(
        api.morbidity_review(
            event["id"], {"action": "SIGN_OFF", "corrective_action_required": False},
            reviewer_headers,
        ),
        200,
    )
    assert signed_off["status"] == "REVIEW_SIGNED_OFF"
    assert signed_off["corrective_action_required"] is False
    assert fetch_practice(practice["id"])["open_adverse_event_count"] == 1

    closed = validate_success(
        api.close_adverse_event(event["id"], {}, reviewer_headers), 200
    )
    assert closed["status"] == "CLOSED"
    assert closed["regulator_notified"] is False, (
        "a MODERATE event closes with no regulator notification required"
    )
    practice_after = fetch_practice(practice["id"])
    assert practice_after["open_adverse_event_count"] == 0
    assert practice_after["version"] > practice_before["version"], (
        "closure increments the practice's version"
    )


def test_lifecycle_quarantining_a_lot_releases_its_held_reservations_without_a_fee(api):
    """PRD 3.7: "Quarantine moves the lot's `status` from `AVAILABLE` to `QUARANTINED`
    and forces its `available_quantity` to 0 so nothing further can be drawn from it."
    PRD 3.7: "Every reservation on the lot still in `HELD` moves to `RELEASED`, but —
    because a manufacturer recall is not the practice's fault — with
    `restocking_fee_cents` set to 0 rather than to the tiered fee,
    `consignment_credit_cents` reset to 0, and `consignment_liability_cents` therefore
    0; each released quantity is returned to the lot's `quantity_reserved`."
    PRD 3.7: "The practice's `consignment_committed_cents` is recomputed afterwards and
    the practice's `version` increments."
    PRD 3.7: "Thereafter `quantity_reserved` is always the sum of `quantity` over the
    lot's reservations whose `status` is `HELD`, and `available_quantity` is
    `quantity_on_hand` less `quantity_reserved`, never negative."
    PRD 3.7: "`consignment_credit_cents` is twenty percent of `line_subtotal_cents`,
    rounded half-up to whole cents, when the lot's `is_consignment` is true, and 0 when
    it is false."

    Design: Corner/state_machines/quarantining_a_lot_releases_its_held_reservations_without_a_fee
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Recall OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Recall", date_of_birth="1980-03-15T00:00:00Z"
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-20T13:00:00Z",
        "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="IMPLANT",
        total_charge_cents=90000,
    )
    lot = create_lot(
        practice["id"],
        manufacturer_code="NOBEL",
        catalog_reference="NB-4310",
        diameter_mm=4.3,
        length_mm=10.0,
        unit_cost_cents=30000,
        quantity_on_hand=5,
        expiry_date="2027-01-31T00:00:00Z",
    )
    reservation = reserve_from_lot(case["id"], lot["id"], 2)

    lot_before = fetch_lot(lot["id"])
    assert lot_before["status"] == "AVAILABLE"
    assert lot_before["quantity_reserved"] == 2
    assert lot_before["available_quantity"] == 3
    reservation_before = fetch_reservation(reservation["id"])
    assert_reservation(reservation_before)
    assert reservation_before["status"] == "HELD"
    assert reservation_before["line_subtotal_cents"] == 60000
    assert reservation_before["consignment_credit_cents"] == 0, "the lot is owned outright"
    assert reservation_before["consignment_liability_cents"] == 60000

    data = validate_success(
        api.quarantine_lot(
            lot["id"], {"quarantine_reason": "MANUFACTURER_RECALL"}, INVENTORY
        ),
        200,
    )

    assert data["status"] == "QUARANTINED"
    assert data["available_quantity"] == 0
    assert data["quantity_reserved"] == 0
    assert data["quantity_on_hand"] == 5, "a recall destroys no physical units"
    assert_lot_quantities_consistent(data)

    reservation_after = fetch_reservation(reservation["id"])
    assert reservation_after["status"] == "RELEASED"
    assert reservation_after["restocking_fee_cents"] == 0, (
        "a recall waives the tiered restocking fee"
    )
    assert reservation_after["consignment_liability_cents"] == 0

    assert fetch_practice(practice["id"])["consignment_committed_cents"] == 0
