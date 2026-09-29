"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success reader so a broken precondition
surfaces as a setup failure rather than as a confusing assertion error.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import REQUIRED_DRILL_TYPES
from .factories import (
    auto_size_payload,
    create_adverse_event_payload,
    create_block_payload,
    create_case_payload,
    create_determination_payload,
    create_drill_payload,
    create_evaluation_payload,
    create_imaging_study_payload,
    create_inspection_payload,
    create_lot_payload,
    create_patient_payload,
    create_permit_payload,
    create_practice_payload,
    create_reservation_payload,
    create_staff_payload,
    day_of_verification_payload,
    inspection_result_payload,
)
from .test_users import (
    ADMIN,
    BENEFITS,
    INVENTORY,
    SCHEDULER,
    make_anesthesia_coordinator_headers,
    make_quality_reviewer_headers,
    make_surgeon_headers,
)

# --- Logical-clock arithmetic ------------------------------------------------

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_iso(instant: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and fractions."""
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def assert_instant_equals(actual: str, expected: str, message: str = ""):
    """Assert two ISO 8601 UTC instants denote the same moment.

    The PRD mandates a three-fractional-digit rendering only for
    `api_request_timestamp` (2.2) and for `created_at` / `updated_at` (2.4). It is
    silent on how derived instants such as `issued_at`, `expires_at`,
    `remediation_deadline_at` and `reporting_deadline_at` are rendered, so those are
    compared by the moment they denote rather than by their exact spelling.
    """
    assert actual is not None, message or f"expected the instant {expected}, got None"
    assert parse_iso(actual) == parse_iso(expected), (
        message or f"expected the instant {expected}, got {actual}"
    )


def shift(instant: str, days=0, hours=0, minutes=0, seconds=0) -> str:
    """Return `instant` moved by the given offset, as an ISO 8601 UTC string."""
    return iso(
        parse_iso(instant)
        + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    )


def minutes_between(start: str, end: str) -> int:
    return int((parse_iso(end) - parse_iso(start)).total_seconds() // 60)


def add_calendar_years(instant: str, years: int) -> str:
    moment = parse_iso(instant)
    try:
        return iso(moment.replace(year=moment.year + years))
    except ValueError:  # 29 February clamped to the last day of the month
        return iso(moment.replace(year=moment.year + years, day=28))


def add_calendar_months(instant: str, months: int) -> str:
    moment = parse_iso(instant)
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = moment.day
    while True:
        try:
            return iso(moment.replace(year=year, month=month, day=day))
        except ValueError:
            day -= 1


# --- Primitive setup calls ---------------------------------------------------

def set_clock(instant: str, headers=None) -> dict:
    return get_success_data(api.set_clock({"current_utc": instant}, headers or ADMIN))


def create_practice(**overrides) -> dict:
    return get_success_data(api.create_practice(create_practice_payload(**overrides), ADMIN))


def create_staff(practice_id, role_type="SURGEON", full_name=None, **overrides) -> dict:
    payload = create_staff_payload(
        practice_id, full_name=full_name or f"Staff {role_type.title()}",
        role_type=role_type, **overrides
    )
    return get_success_data(api.create_staff_member(payload, ADMIN))


def create_patient(practice_id, **overrides) -> dict:
    return get_success_data(
        api.create_patient(create_patient_payload(practice_id, **overrides), SCHEDULER)
    )


def create_block(practice_id, surgeon_id, block_start, block_end, **overrides) -> dict:
    payload = create_block_payload(practice_id, surgeon_id, block_start, block_end, **overrides)
    return get_success_data(api.create_block_time(payload, SCHEDULER))


def create_case(practice_id, patient_id, primary_surgeon_id, planned_start, planned_end,
                **overrides) -> dict:
    payload = create_case_payload(
        practice_id, patient_id, primary_surgeon_id, planned_start, planned_end, **overrides
    )
    return get_success_data(api.create_surgical_case(payload, SCHEDULER))


def create_lot(practice_id, **overrides) -> dict:
    return get_success_data(
        api.create_implant_lot(create_lot_payload(practice_id, **overrides), INVENTORY)
    )


def log_drill(practice_id, drill_type, conducted_at, participant_staff_ids,
              **overrides) -> dict:
    payload = create_drill_payload(
        practice_id, drill_type, conducted_at, participant_staff_ids, **overrides
    )
    return get_success_data(api.create_drill(payload, ADMIN))


def log_drills_for_level(practice_id, participant_staff_ids, permit_level,
                         conducted_at, skip_types=()) -> list:
    """Log one clean drill for each type the given permit level requires."""
    logged = []
    for drill_type in REQUIRED_DRILL_TYPES[permit_level]:
        if drill_type in skip_types:
            continue
        logged.append(
            log_drill(practice_id, drill_type, conducted_at, participant_staff_ids)
        )
    return logged


def apply_permit(practice_id, permit_level="MODERATE_SEDATION",
                 applied_on="2026-08-01T00:00:00Z", **overrides) -> dict:
    payload = create_permit_payload(practice_id, permit_level, applied_on, **overrides)
    return get_success_data(api.create_permit(payload, ADMIN))


def schedule_inspection(permit_id, scheduled_for, **overrides) -> dict:
    payload = create_inspection_payload(permit_id, scheduled_for, **overrides)
    return get_success_data(api.create_inspection(payload, ADMIN))


def record_inspection_result(inspection_id, minor=0, major=0, critical=0) -> dict:
    payload = inspection_result_payload(minor, major, critical)
    return get_success_data(api.record_inspection_result(inspection_id, payload, ADMIN))


# --- Fresh reads -------------------------------------------------------------

def fetch_practice(practice_id) -> dict:
    return get_success_data(api.get_practice(practice_id, ADMIN))


def fetch_permit(permit_id) -> dict:
    return get_success_data(api.get_permit(permit_id, ADMIN))


def fetch_case(case_id) -> dict:
    return get_success_data(api.get_surgical_case(case_id, SCHEDULER))


def fetch_block(block_id) -> dict:
    return get_success_data(api.get_block_time(block_id, SCHEDULER))


def fetch_lot(lot_id) -> dict:
    return get_success_data(api.get_implant_lot(lot_id, INVENTORY))


def fetch_reservation(reservation_id) -> dict:
    return get_success_data(api.get_reservation(reservation_id, INVENTORY))


def fetch_evaluation(evaluation_id) -> dict:
    return get_success_data(api.get_evaluation(evaluation_id, ADMIN))


def fetch_determination(determination_id) -> dict:
    return get_success_data(api.get_determination(determination_id, BENEFITS))


def fetch_adverse_event(event_id) -> dict:
    return get_success_data(api.get_adverse_event(event_id, ADMIN))


# --- Tier 1/2: practice, roster, and a permitted office ----------------------

def setup_practice_with_roster(clock="2026-08-01T00:00:00Z", recovery_bay_count=2,
                               include_recovery_nurse=True, monitoring_certified=True,
                               surgeon_acls_expires_on="2027-06-30T00:00:00Z",
                               patient_overrides=None, **practice_overrides) -> dict:
    """Set the clock, register a practice and build the clinical roster.

    Returns an environment dict carrying the practice, a surgeon, a certified
    monitor, a second monitor available as an independent verifier, an optional
    recovery nurse, a quality reviewer and one patient.
    """
    set_clock(clock)
    practice = create_practice(recovery_bay_count=recovery_bay_count, **practice_overrides)
    surgeon = create_staff(
        practice["id"], "SURGEON", "Dr Alma Reyes",
        acls_expires_on=surgeon_acls_expires_on,
    )
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Nia Monitor",
        monitoring_certified=monitoring_certified,
        acls_expires_on=surgeon_acls_expires_on,
    )
    verifier = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Val Verifier",
        monitoring_certified=True, acls_expires_on=surgeon_acls_expires_on,
    )
    reviewer = create_staff(practice["id"], "INVENTORY_TECH", "Quinn Reviewer")
    recovery_nurse = None
    if include_recovery_nurse:
        recovery_nurse = create_staff(practice["id"], "RECOVERY_NURSE", "Rae Nurse")
    patient = create_patient(practice["id"], **(patient_overrides or {}))
    return {
        "clock": clock,
        "practice": practice,
        "practice_id": practice["id"],
        "surgeon": surgeon,
        "monitor": monitor,
        "verifier": verifier,
        "reviewer": reviewer,
        "recovery_nurse": recovery_nurse,
        "patient": patient,
    }


def advance_clock(env: dict, days=0, hours=0, minutes=0, seconds=0) -> str:
    """Move the logical clock forward and record the new instant on the env."""
    env["clock"] = shift(env["clock"], days=days, hours=hours, minutes=minutes,
                         seconds=seconds)
    set_clock(env["clock"])
    return env["clock"]


def set_env_clock(env: dict, instant: str) -> str:
    set_clock(instant)
    env["clock"] = instant
    return instant


def setup_permitted_practice(permit_level="DEEP_SEDATION_GENERAL",
                             clock="2026-08-01T00:00:00Z", **roster_kwargs) -> dict:
    """Full chain to an ACTIVE permit: roster, a clean drill for every required
    type, an application, a scheduled inspection and a passing result.

    On return the practice's sedation_privilege_state is PERMITTED and the
    logical clock sits one day after `clock`.
    """
    env = setup_practice_with_roster(clock=clock, **roster_kwargs)
    participants = [env["surgeon"]["id"], env["monitor"]["id"]]
    log_drills_for_level(env["practice_id"], participants, permit_level, clock)
    permit = apply_permit(env["practice_id"], permit_level, clock)
    inspection_at = shift(clock, days=1)
    inspection = schedule_inspection(permit["id"], inspection_at)
    set_env_clock(env, inspection_at)
    record_inspection_result(inspection["id"], 0, 0, 0)
    env["permit"] = fetch_permit(permit["id"])
    env["permit_level"] = permit_level
    env["inspection"] = inspection
    env["practice"] = fetch_practice(env["practice_id"])
    return env


def drive_permit_to_probation(env: dict, minor=0, major=5, critical=0) -> dict:
    """Post a FAILED_CORRECTABLE re-inspection against the ACTIVE permit, which
    drops it to PROBATION and restricts the practice."""
    inspection_at = shift(env["clock"], hours=1)
    inspection = schedule_inspection(env["permit"]["id"], inspection_at)
    set_env_clock(env, inspection_at)
    record_inspection_result(inspection["id"], minor, major, critical)
    env["permit"] = fetch_permit(env["permit"]["id"])
    env["practice"] = fetch_practice(env["practice_id"])
    return env["permit"]


def drive_permit_to_suspension(env: dict) -> dict:
    """Post a FAILED_CRITICAL re-inspection against a live permit, which suspends
    it and runs the full suspension cascade."""
    inspection_at = shift(env["clock"], hours=1)
    inspection = schedule_inspection(env["permit"]["id"], inspection_at)
    set_env_clock(env, inspection_at)
    record_inspection_result(inspection["id"], 0, 0, 1)
    env["permit"] = fetch_permit(env["permit"]["id"])
    env["practice"] = fetch_practice(env["practice_id"])
    return env["permit"]


# --- Tier 3: cases through the scheduling lifecycle --------------------------

def draft_case(env: dict, planned_anesthesia_level="MODERATE_SEDATION",
               planned_start=None, planned_end=None, with_monitor=True,
               patient_id=None, primary_surgeon_id=None, **overrides) -> dict:
    """Draft a case for the env's practice. Defaults place the operative window a
    week after the current logical clock.

    `primary_surgeon_id` defaults to the env's surgeon but is overridable, because
    the PRD's `ERR_BLOCK_SURGEON_MISMATCH` rule ("The case's `primary_surgeon_id`
    must equal the block's `surgeon_id`") can only be exercised with a second
    surgeon on the roster.
    """
    planned_start = planned_start or shift(env["clock"], days=7)
    planned_end = planned_end or shift(planned_start, minutes=60)
    if with_monitor and "monitor_staff_id" not in overrides:
        overrides["monitor_staff_id"] = env["monitor"]["id"]
    return create_case(
        env["practice_id"],
        patient_id or env["patient"]["id"],
        primary_surgeon_id or env["surgeon"]["id"],
        planned_start,
        planned_end,
        planned_anesthesia_level=planned_anesthesia_level,
        **overrides,
    )


def block_covering(env: dict, planned_start, planned_end, room_code="OR-1",
                   pad_minutes=120, **overrides) -> dict:
    """Reserve a block for the env's surgeon that wholly contains the window."""
    return create_block(
        env["practice_id"],
        env["surgeon"]["id"],
        shift(planned_start, minutes=-pad_minutes),
        shift(planned_end, minutes=pad_minutes),
        room_code=room_code,
        **overrides,
    )


def hold_case_on_block(case_id, block_id) -> dict:
    return get_success_data(api.hold_block(case_id, {"block_id": block_id}, SCHEDULER))


def setup_case_block_held(env: dict, planned_anesthesia_level="MODERATE_SEDATION",
                          planned_start=None, planned_end=None, block=None,
                          room_code="OR-1", **case_overrides):
    """Draft a case, reserve a covering block and hold the case's minutes.

    Returns (case, block) with the case in BLOCK_HELD.
    """
    planned_start = planned_start or shift(env["clock"], days=7)
    planned_end = planned_end or shift(planned_start, minutes=60)
    if block is None:
        block = block_covering(env, planned_start, planned_end, room_code=room_code)
    case = draft_case(
        env,
        planned_anesthesia_level=planned_anesthesia_level,
        planned_start=planned_start,
        planned_end=planned_end,
        **case_overrides,
    )
    case = hold_case_on_block(case["id"], block["id"])
    return case, fetch_block(block["id"])


def create_evaluation_for(env: dict, case_id, evaluator_staff_id=None,
                          asa_class_recorded=2, airway_class_recorded=2,
                          **overrides) -> dict:
    """Open a fresh evaluation against the case's current version."""
    evaluator_staff_id = evaluator_staff_id or env["monitor"]["id"]
    case = fetch_case(case_id)
    payload = create_evaluation_payload(
        evaluator_staff_id, case["version"],
        asa_class_recorded=asa_class_recorded,
        airway_class_recorded=airway_class_recorded,
        **overrides,
    )
    return get_success_data(
        api.create_evaluation(
            case_id, payload, make_anesthesia_coordinator_headers(evaluator_staff_id)
        )
    )


def sign_evaluation_as(evaluation_id, evaluator_staff_id) -> dict:
    return get_success_data(
        api.sign_evaluation(
            evaluation_id, {}, make_anesthesia_coordinator_headers(evaluator_staff_id)
        )
    )


def verify_evaluation_as(env: dict, evaluation_id, verifier_staff_id=None,
                         intent="CLEAR", solids_minutes_ago=600,
                         clears_minutes_ago=180, escort_confirmed=True,
                         escort_name="Ada Escort", **overrides) -> dict:
    """Day-of verification by an independent staff member. Fasting instants are
    derived from the current logical clock so the intervals clear the floors."""
    verifier_staff_id = verifier_staff_id or env["verifier"]["id"]
    payload = day_of_verification_payload(
        intent,
        shift(env["clock"], minutes=-solids_minutes_ago),
        shift(env["clock"], minutes=-clears_minutes_ago),
        escort_confirmed=escort_confirmed,
        escort_name=escort_name,
        **overrides,
    )
    return get_success_data(
        api.verify_evaluation(
            evaluation_id, payload, make_anesthesia_coordinator_headers(verifier_staff_id)
        )
    )


def clear_case(env: dict, case_id, evaluator_staff_id=None, verifier_staff_id=None,
               asa_class_recorded=2, airway_class_recorded=2, **eval_overrides) -> dict:
    """Create, sign and CLEAR-verify an evaluation so the case reads CLEARED."""
    evaluator_staff_id = evaluator_staff_id or env["monitor"]["id"]
    evaluation = create_evaluation_for(
        env, case_id, evaluator_staff_id,
        asa_class_recorded=asa_class_recorded,
        airway_class_recorded=airway_class_recorded,
        **eval_overrides,
    )
    sign_evaluation_as(evaluation["id"], evaluator_staff_id)
    return verify_evaluation_as(
        env, evaluation["id"], verifier_staff_id=verifier_staff_id, intent="CLEAR"
    )


def confirm_case(case_id, block_id) -> dict:
    """Confirm the case against the block's current version."""
    block = fetch_block(block_id)
    return get_success_data(
        api.confirm_case(
            case_id, {"expected_block_version": block["version"]}, SCHEDULER
        )
    )


def setup_confirmed_case(env: dict, planned_anesthesia_level="MODERATE_SEDATION",
                         planned_start=None, planned_end=None, block=None,
                         room_code="OR-1", **case_overrides):
    """Draft -> hold -> clear -> confirm. Returns (case, block)."""
    case, block = setup_case_block_held(
        env, planned_anesthesia_level=planned_anesthesia_level,
        planned_start=planned_start, planned_end=planned_end, block=block,
        room_code=room_code, **case_overrides,
    )
    clear_case(env, case["id"])
    case = confirm_case(case["id"], block["id"])
    return case, fetch_block(block["id"])


def cancel_case(case_id, cancellation_reason="PATIENT_REQUEST") -> dict:
    return get_success_data(
        api.cancel_case(case_id, {"cancellation_reason": cancellation_reason}, SCHEDULER)
    )


def start_recovery(env: dict, case_id) -> dict:
    return get_success_data(
        api.start_recovery(case_id, {}, make_surgeon_headers(env["surgeon"]["id"]))
    )


def complete_case(env: dict, case_id) -> dict:
    return get_success_data(
        api.complete_case(case_id, {}, make_surgeon_headers(env["surgeon"]["id"]))
    )


def setup_completed_case(env: dict, planned_anesthesia_level="LOCAL_ONLY",
                         planned_start=None, planned_end=None, **case_overrides):
    """Walk a case all the way to COMPLETED, advancing the clock past its window
    and past its recovery obligation. Returns (case, block)."""
    planned_start = planned_start or shift(env["clock"], days=7)
    planned_end = planned_end or shift(planned_start, minutes=60)
    case, block = setup_confirmed_case(
        env, planned_anesthesia_level=planned_anesthesia_level,
        planned_start=planned_start, planned_end=planned_end, **case_overrides,
    )
    set_env_clock(env, planned_start)
    case = start_recovery(env, case["id"])
    if case["recovery_minutes_required"]:
        set_env_clock(env, shift(env["clock"], minutes=case["recovery_minutes_required"]))
    case = complete_case(env, case["id"])
    return case, fetch_block(block["id"])


# --- Tier 4: inventory, consignment exposure and benefit determinations -------

def reserve_from_lot(case_id, lot_id, quantity=1, **overrides) -> dict:
    """Explicit reservation against the lot's current version."""
    lot = fetch_lot(lot_id)
    payload = create_reservation_payload(case_id, lot_id, quantity, lot["version"],
                                         **overrides)
    return get_success_data(api.create_reservation(payload, INVENTORY))


def auto_size_for_case(case_id, requested_diameter_mm, requested_length_mm,
                       quantity=1, **overrides) -> dict:
    payload = auto_size_payload(requested_diameter_mm, requested_length_mm, quantity,
                                **overrides)
    return get_success_data(api.auto_size_reservation(case_id, payload, INVENTORY))


def consume_reservation(reservation_id) -> dict:
    return get_success_data(api.consume_reservation(reservation_id, {}, INVENTORY))


def dispose_reservation(reservation_id, disposition="RELEASED") -> dict:
    return get_success_data(
        api.release_reservation(reservation_id, {"disposition": disposition}, INVENTORY)
    )


def quarantine_lot(lot_id, quarantine_reason="Manufacturer recall") -> dict:
    return get_success_data(
        api.quarantine_lot(lot_id, {"quarantine_reason": quarantine_reason}, INVENTORY)
    )


def setup_confirmed_case_with_held_reservation(env: dict, quantity=1,
                                              lot_overrides=None,
                                              planned_anesthesia_level="MODERATE_SEDATION",
                                              **case_overrides):
    """Confirmed sedated case plus one HELD reservation on a fresh lot.

    Returns (case, block, lot, reservation) — the shape the privilege cascade and
    the cancellation chain both need.
    """
    lot = create_lot(env["practice_id"], **(lot_overrides or {}))
    case, block = setup_confirmed_case(
        env, planned_anesthesia_level=planned_anesthesia_level, **case_overrides
    )
    reservation = reserve_from_lot(case["id"], lot["id"], quantity)
    return case, fetch_block(block["id"]), fetch_lot(lot["id"]), reservation


def open_determination(case_id, service_lines) -> dict:
    payload = create_determination_payload(case_id, service_lines)
    return get_success_data(api.create_determination(payload, BENEFITS))


def submit_determination(determination_id) -> dict:
    return get_success_data(api.submit_determination(determination_id, {}, BENEFITS))


def record_payer_response(determination_id, outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api.record_payer_response(determination_id, payload, BENEFITS)
    )


def setup_case_with_verified_evaluation(env: dict,
                                        planned_anesthesia_level="MODERATE_SEDATION",
                                        total_charge_cents=100_000, **case_overrides):
    """A BLOCK_HELD case whose evaluation is VERIFIED — the precondition a benefit
    determination must satisfy before it may be submitted. Returns (case, block)."""
    case, block = setup_case_block_held(
        env, planned_anesthesia_level=planned_anesthesia_level,
        total_charge_cents=total_charge_cents, **case_overrides
    )
    clear_case(env, case["id"])
    return fetch_case(case["id"]), block


# --- Tier 5: adverse events, imaging and the compliance sweep ----------------

def file_adverse_event(env: dict, case_id, severity="MINOR", event_type="HYPOXEMIA",
                       occurred_at=None, reporter_staff_id=None, **overrides) -> dict:
    payload = create_adverse_event_payload(
        case_id, event_type=event_type, severity=severity,
        occurred_at=occurred_at or env["clock"], **overrides
    )
    reporter_staff_id = reporter_staff_id or env["reviewer"]["id"]
    return get_success_data(
        api.create_adverse_event(payload, make_quality_reviewer_headers(reporter_staff_id))
    )


def open_morbidity_review(env: dict, event_id, reviewer_staff_id=None,
                          actor_staff_id=None) -> dict:
    reviewer_staff_id = reviewer_staff_id or env["reviewer"]["id"]
    actor_staff_id = actor_staff_id or reviewer_staff_id
    return get_success_data(
        api.morbidity_review(
            event_id,
            {"action": "OPEN", "reviewer_staff_id": reviewer_staff_id},
            make_quality_reviewer_headers(actor_staff_id),
        )
    )


def sign_off_morbidity_review(event_id, reviewer_staff_id,
                              corrective_action_required=False) -> dict:
    return get_success_data(
        api.morbidity_review(
            event_id,
            {
                "action": "SIGN_OFF",
                "corrective_action_required": corrective_action_required,
            },
            make_quality_reviewer_headers(reviewer_staff_id),
        )
    )


def record_regulator_notification(env: dict, event_id, notified_at=None,
                                  notification_reference="BOARD-REF-1") -> dict:
    return get_success_data(
        api.record_regulator_notification(
            event_id,
            {
                "notified_at": notified_at or env["clock"],
                "notification_reference": notification_reference,
            },
            ADMIN,
        )
    )


def close_adverse_event(env: dict, event_id, reviewer_staff_id=None) -> dict:
    reviewer_staff_id = reviewer_staff_id or env["reviewer"]["id"]
    return get_success_data(
        api.close_adverse_event(
            event_id, {}, make_quality_reviewer_headers(reviewer_staff_id)
        )
    )


def register_imaging_study(env: dict, patient_id=None, **overrides) -> dict:
    payload = create_imaging_study_payload(
        patient_id or env["patient"]["id"], **overrides
    )
    return get_success_data(
        api.create_imaging_study(payload, make_surgeon_headers(env["surgeon"]["id"]))
    )


def run_compliance_sweep(practice_id=None) -> dict:
    payload = {"practice_id": practice_id} if practice_id else {}
    return get_success_data(api.run_compliance_sweep(payload, ADMIN))
