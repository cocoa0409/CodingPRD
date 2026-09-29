"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds the
state it needs from scratch through the PRD's own endpoints.  Setup steps use
the lenient ``get_success_data`` so that a broken preamble reports as a setup
failure rather than as a business-rule failure.

The canonical chain is: set the logical clock, register a state policy, register
the facility, add a unit, then enrol a physicist, a technologist and an
interpreting physician.  ``setup_core`` returns that whole world plus the
headers needed to act as each of its people.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC
from .factories import (
    audit_cycle_payload,
    ce_credit_payload,
    close_cycle_payload,
    ct_policy_payload,
    equipment_failure_payload,
    exam_payload,
    facility_payload,
    failing_survey_decision_payload,
    funding_deposit_payload,
    inspection_payload,
    interpret_payload,
    letter_payload,
    ma_policy_payload,
    nv_policy_payload,
    outcome_payload,
    packet_payload,
    passing_survey_decision_payload,
    qualified_physician_payload,
    qualified_physicist_payload,
    qualified_technologist_payload,
    repeat_record_payload,
    review_decision_payload,
    ri_policy_payload,
    schedule_payload,
    supplemental_order_payload,
    survey_payload,
    volume_credit_payload,
)
from .test_users import (
    TEST_USERS,
    make_physician_headers,
    make_physicist_headers,
    make_technologist_headers,
)

COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
QA = TEST_USERS["qa_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(current_utc: str = CLOCK_START_UTC, headers: Optional[dict] = None) -> dict:
    """Move the logical clock and return the reading."""
    return get_success_data(
        api_client.set_clock(current_utc, headers or COORD)
    )


def read_clock(headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_clock(headers or COORD))


# ---------------------------------------------------------------------------
# Policies, facilities, units, personnel
# ---------------------------------------------------------------------------


def create_policy(payload: dict, headers: Optional[dict] = None) -> dict:
    """Register a state policy.  Only the two regulator-side roles may do this."""
    return get_success_data(api_client.create_state_policy(payload, headers or REVIEWER))


def create_ct_policy(**overrides) -> dict:
    return create_policy(ct_policy_payload(**overrides))


def create_ma_policy(**overrides) -> dict:
    return create_policy(ma_policy_payload(**overrides))


def create_ri_policy(**overrides) -> dict:
    return create_policy(ri_policy_payload(**overrides))


def create_nv_policy(**overrides) -> dict:
    return create_policy(nv_policy_payload(**overrides))


def create_facility(policy_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(facility_payload(policy_id, **overrides), COORD)
    )


def add_unit(facility_id: str, **overrides) -> dict:
    from .factories import unit_payload

    return get_success_data(
        api_client.create_unit(facility_id, unit_payload(**overrides), COORD)
    )


def add_second_unit(facility_id: str, **overrides) -> dict:
    """A `DM_2D` sibling unit, used wherever a cross-unit mismatch is the point."""
    defaults = {"manufacturer": "GE", "model_serial": "SEL-9002", "modality": "DM_2D"}
    defaults.update(overrides)
    return add_unit(facility_id, **defaults)


def add_personnel(facility_id: str, payload: dict) -> dict:
    return get_success_data(api_client.create_personnel(facility_id, payload, COORD))


def add_physicist(facility_id: str, **overrides) -> dict:
    return add_personnel(facility_id, qualified_physicist_payload(**overrides))


def add_technologist(facility_id: str, **overrides) -> dict:
    return add_personnel(facility_id, qualified_technologist_payload(**overrides))


def add_radiologist(facility_id: str, **overrides) -> dict:
    return add_personnel(facility_id, qualified_physician_payload(**overrides))


def fund_facility(facility_id: str, amount_cents: int = 1000000) -> dict:
    """Record a funding deposit; the response is the refreshed facility."""
    return get_success_data(
        api_client.create_funding_deposit(
            facility_id, funding_deposit_payload(amount_cents), COORD
        )
    )


def read_facility(facility_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_facility(facility_id, headers or COORD))


def read_unit(unit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_unit(unit_id, headers or COORD))


def read_personnel(personnel_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_personnel(personnel_id, headers or COORD))


def read_exam(exam_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_exam(exam_id, headers or COORD))


def read_survey(survey_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_physicist_survey(survey_id, headers or COORD))


def read_submission(submission_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_clinical_image_review(submission_id, headers or COORD)
    )


def read_letter(letter_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_notification_letter(letter_id, headers or COORD))


def read_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_supplemental_order(order_id, headers or COORD))


def read_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_audit_cycle(cycle_id, headers or COORD))


def read_failure(failure_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_equipment_failure(failure_id, headers or COORD))


# ---------------------------------------------------------------------------
# Tier 2: the base world
# ---------------------------------------------------------------------------


def setup_core(policy_payload_fn=ct_policy_payload, clock: str = CLOCK_START_UTC, **facility_overrides) -> dict:
    """Clock, one state policy, one facility, one unit, three enrolled people.

    Returns a dict carrying every id, the entity bodies as first read, and the
    headers required to act as each entity-backed person.
    """
    set_clock(clock)
    policy = create_policy(policy_payload_fn())
    facility = create_facility(policy["id"], **facility_overrides)
    unit = add_unit(facility["id"])
    physicist = add_physicist(facility["id"])
    technologist = add_technologist(facility["id"])
    radiologist = add_radiologist(facility["id"])
    return {
        "clock": clock,
        "policy": policy,
        "policy_id": policy["id"],
        "facility": facility,
        "facility_id": facility["id"],
        "unit": unit,
        "unit_id": unit["id"],
        "physicist": physicist,
        "phys_id": physicist["id"],
        "technologist": technologist,
        "tech_id": technologist["id"],
        "radiologist": radiologist,
        "rad_id": radiologist["id"],
        "phys_headers": make_physicist_headers(physicist["id"]),
        "tech_headers": make_technologist_headers(technologist["id"]),
        "rad_headers": make_physician_headers(radiologist["id"]),
        "coord_headers": COORD,
        "reviewer_headers": REVIEWER,
        "inspector_headers": INSPECTOR,
        "qa_headers": QA,
    }


def setup_core_funded(amount_cents: int = 1000000, **kwargs) -> dict:
    """The base world with the fee account pre-funded."""
    core = setup_core(**kwargs)
    core["facility"] = fund_facility(core["facility_id"], amount_cents)
    return core


def add_second_radiologist(core: dict, **overrides) -> dict:
    """A colleague physician, for ownership and segregation-of-duties crossings."""
    defaults = {
        "full_name": "Rex Reader",
        "initial_qualification_on": "2024-04-01T00:00:00Z",
        "initial_training_hours": 70,
        "initial_read_volume": 300,
    }
    defaults.update(overrides)
    person = add_radiologist(core["facility_id"], **defaults)
    core["rad2"] = person
    core["rad2_id"] = person["id"]
    core["rad2_headers"] = make_physician_headers(person["id"])
    return person


def add_second_physicist(core: dict, **overrides) -> dict:
    defaults = {"full_name": "Peter Physicist", "initial_qualification_on": "2024-01-20T00:00:00Z"}
    defaults.update(overrides)
    person = add_physicist(core["facility_id"], **defaults)
    core["phys2"] = person
    core["phys2_id"] = person["id"]
    core["phys2_headers"] = make_physicist_headers(person["id"])
    return person


# ---------------------------------------------------------------------------
# Tier 3: exams
# ---------------------------------------------------------------------------


def acquire_exam(core: dict, **overrides) -> dict:
    """Acquire an exam as the core technologist.

    ``unit_id`` and ``technologist_id`` default to the core world's unit and
    technologist but may be overridden by keyword, which is how the cross-unit
    tests place an exam on a sibling unit.
    """
    unit_id = overrides.pop("unit_id", core["unit_id"])
    technologist_id = overrides.pop("technologist_id", core["tech_id"])
    payload = exam_payload(unit_id, technologist_id, **overrides)
    return get_success_data(api_client.create_exam(payload, core["tech_headers"]))


def interpret(core: dict, exam_id: str, birads: int = 1, density: Optional[str] = "B", headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.interpret_exam(
            exam_id, interpret_payload(birads, density), headers or core["rad_headers"]
        )
    )


def acquire_and_interpret(core: dict, birads: int = 1, density: Optional[str] = "B", **overrides) -> dict:
    """Acquire an exam and read it, returning the interpreted exam body."""
    exam = acquire_exam(core, **overrides)
    return interpret(core, exam["id"], birads, density)


def setup_two_interpreted_exams(core: dict) -> List[dict]:
    """Two interpreted exams on the core unit — the minimum a packet accepts."""
    first = acquire_and_interpret(
        core, patient_ref="PT-1201", performed_at="2026-07-20T00:00:00Z"
    )
    second = acquire_and_interpret(
        core, patient_ref="PT-1202", performed_at="2026-07-21T00:00:00Z"
    )
    core["pk_a"] = first
    core["pk_a_id"] = first["id"]
    core["pk_b"] = second
    core["pk_b_id"] = second["id"]
    return [first, second]


def setup_three_interpreted_exams(core: dict) -> List[dict]:
    exams = setup_two_interpreted_exams(core)
    third = acquire_and_interpret(
        core, patient_ref="PT-1203", performed_at="2026-07-22T00:00:00Z"
    )
    core["pk_c"] = third
    core["pk_c_id"] = third["id"]
    return exams + [third]


def setup_dense_screening_exam(core: dict, density: str = "C", birads: int = 1, **overrides) -> dict:
    """A screening exam read as dense, which is what a supplemental order needs."""
    defaults = {"patient_ref": "PT-SC-1", "performed_at": "2026-07-20T00:00:00Z"}
    defaults.update(overrides)
    exam = acquire_and_interpret(core, birads=birads, density=density, **defaults)
    core["dense_exam"] = exam
    core["dense_exam_id"] = exam["id"]
    return exam


def record_outcome(core: dict, exam_id: str, biopsy_performed: bool = True, pathology_result: str = "BENIGN") -> dict:
    return get_success_data(
        api_client.record_exam_outcome(
            exam_id, outcome_payload(biopsy_performed, pathology_result), QA
        )
    )


def document_repeat(core: dict, exam_id: str, reason_code: str = "POSITIONING", repeat_image_count: int = 2, headers: Optional[dict] = None, **overrides) -> dict:
    payload = repeat_record_payload(reason_code, repeat_image_count, **overrides)
    return get_success_data(
        api_client.create_repeat_record(exam_id, payload, headers or core["tech_headers"])
    )


# ---------------------------------------------------------------------------
# Tier 3: surveys and equipment failures
# ---------------------------------------------------------------------------


def create_draft_survey(core: dict, unit_id: Optional[str] = None, **overrides) -> dict:
    """Open a survey as the authoring physicist; only that physicist may decide it."""
    return get_success_data(
        api_client.create_physicist_survey(
            unit_id or core["unit_id"], survey_payload(**overrides), core["phys_headers"]
        )
    )


def decide_survey(core: dict, survey_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.submit_physicist_survey(
            survey_id, payload or passing_survey_decision_payload(), headers or core["phys_headers"]
        )
    )


def create_passed_survey(core: dict, unit_id: Optional[str] = None, **survey_overrides) -> dict:
    """A survey whose window covers the clock and which passes all three conjuncts."""
    survey = create_draft_survey(core, unit_id, **survey_overrides)
    return decide_survey(core, survey["id"])


def create_failed_survey(core: dict, unit_id: Optional[str] = None, decision: Optional[dict] = None, **survey_overrides) -> dict:
    """A survey decided against the unit, which opens the five-level cascade."""
    survey = create_draft_survey(core, unit_id, **survey_overrides)
    return decide_survey(core, survey["id"], decision or failing_survey_decision_payload())


def remediate_survey(core: dict, survey_id: str, payload: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.remediate_physicist_survey(
            survey_id, payload or passing_survey_decision_payload(), COORD
        )
    )


def report_failure(core: dict, unit_id: Optional[str] = None, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_equipment_failure(
            unit_id or core["unit_id"],
            equipment_failure_payload(**overrides),
            headers or core["tech_headers"],
        )
    )


def report_qualifying_failure(core: dict, unit_id: Optional[str] = None, **overrides) -> dict:
    """A `DETECTOR`/`MAJOR` fault requires a post-repair survey and pulls the unit out of service."""
    defaults = {"failure_code": "DETECTOR", "severity": "MAJOR"}
    defaults.update(overrides)
    return report_failure(core, unit_id, **defaults)


def restore_unit(core: dict, failure_id: str, note: str = "Detector module replaced and verified") -> dict:
    from .factories import restore_payload

    return get_success_data(
        api_client.restore_equipment_failure(failure_id, restore_payload(repair_note=note), COORD)
    )


def create_post_repair_passed_survey(core: dict, detected_at: str = "2026-08-01T00:00:00Z", unit_id: Optional[str] = None) -> dict:
    """A `POST_REPAIR` survey whose window opens at or after the failure instant."""
    survey = create_draft_survey(
        core,
        unit_id,
        survey_type="POST_REPAIR",
        effective_start=detected_at,
        effective_end="2027-07-01T00:00:00Z",
    )
    return decide_survey(core, survey["id"])


# ---------------------------------------------------------------------------
# Tier 3: clinical image packets
# ---------------------------------------------------------------------------


def unit_version(core: dict, unit_id: Optional[str] = None) -> int:
    """Read the unit's current `version`, the mandatory packet concurrency token."""
    return read_unit(unit_id or core["unit_id"])["version"]


def file_packet(core: dict, exam_ids: List[str], unit_id: Optional[str] = None, expected_unit_version: Optional[int] = None, **overrides) -> dict:
    target = unit_id or core["unit_id"]
    version = expected_unit_version if expected_unit_version is not None else unit_version(core, target)
    return get_success_data(
        api_client.create_clinical_image_review(
            target, packet_payload(exam_ids, version, **overrides), COORD
        )
    )


def setup_submitted_packet(core: dict) -> dict:
    """Fund the account, build two interpreted exams and file one packet."""
    if core["facility"]["total_funded_cents"] == 0:
        core["facility"] = fund_facility(core["facility_id"])
    exams = setup_two_interpreted_exams(core)
    submission = file_packet(core, [exams[0]["id"], exams[1]["id"]])
    core["submission"] = submission
    core["submission_id"] = submission["id"]
    return submission


def review_packet(core: dict, submission_id: str, decision: str = "PASS", **overrides) -> dict:
    return get_success_data(
        api_client.review_clinical_image_review(
            submission_id, review_decision_payload(decision, **overrides), REVIEWER
        )
    )


def setup_passed_packet(core: dict) -> dict:
    """A packet filed and passed, so the unit reaches `ACCREDITED`."""
    submission = setup_submitted_packet(core)
    return review_packet(core, submission["id"], "PASS")


def setup_revision_required_packet(core: dict) -> dict:
    """A packet filed and sent back, so the submission sits in `REVISION_REQUIRED`."""
    submission = setup_submitted_packet(core)
    return review_packet(core, submission["id"], "REVISION_REQUIRED")


def resubmit_packet(core: dict, submission_id: str, exam_ids: List[str], expected_unit_version: Optional[int] = None, **overrides) -> dict:
    version = expected_unit_version if expected_unit_version is not None else unit_version(core)
    return get_success_data(
        api_client.resubmit_clinical_image_review(
            submission_id, packet_payload(exam_ids, version, **overrides), COORD
        )
    )


def withdraw_packet(core: dict, submission_id: str, expected_unit_version: Optional[int] = None) -> dict:
    from .factories import withdraw_payload

    version = expected_unit_version if expected_unit_version is not None else unit_version(core)
    payload = withdraw_payload()
    payload["expected_unit_version"] = version
    return get_success_data(
        api_client.withdraw_clinical_image_review(submission_id, payload, COORD)
    )


def setup_denied_final_packet(core: dict) -> dict:
    """Walk the revision loop until the attempt budget is spent and the unit is suspended.

    Three filings consume the three attempts; the fourth `REVISION_REQUIRED`
    verdict is the terminal one.
    """
    submission = setup_submitted_packet(core)
    exam_ids = [core["pk_a_id"], core["pk_b_id"]]
    submission = review_packet(core, submission["id"], "REVISION_REQUIRED")
    submission = resubmit_packet(core, submission["id"], exam_ids)
    submission = review_packet(core, submission["id"], "REVISION_REQUIRED")
    submission = resubmit_packet(core, submission["id"], exam_ids)
    submission = review_packet(core, submission["id"], "REVISION_REQUIRED")
    core["submission"] = submission
    core["submission_id"] = submission["id"]
    return submission


# ---------------------------------------------------------------------------
# Tier 3: inspections
# ---------------------------------------------------------------------------


def record_inspection(core: dict, level: str = "NONE", **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(
            core["facility_id"], inspection_payload(level, **overrides), INSPECTOR
        )
    )


def record_level_1_inspection(core: dict, **overrides) -> dict:
    """An open `LEVEL_1` corrective action drops the facility straight to `SUSPENDED`."""
    defaults = {"finding_codes": ["MQSA-1"]}
    defaults.update(overrides)
    return record_inspection(core, "LEVEL_1", **defaults)


def close_inspection(core: dict, inspection_id: str, **overrides) -> dict:
    from .factories import close_inspection_payload

    return get_success_data(
        api_client.close_inspection(
            inspection_id, INSPECTOR, close_inspection_payload(**overrides)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: notification letters
# ---------------------------------------------------------------------------


def exam_version(exam_id: str) -> int:
    """Read the exam's current `version`, the letter-generation concurrency token."""
    return read_exam(exam_id)["version"]


def generate_letter(core: dict, exam_id: str, expected_exam_version: Optional[int] = None, **overrides) -> dict:
    version = expected_exam_version if expected_exam_version is not None else exam_version(exam_id)
    return get_success_data(
        api_client.create_notification_letter(
            exam_id, letter_payload(version, **overrides), COORD
        )
    )


def send_letter(core: dict, letter_id: str) -> dict:
    return get_success_data(api_client.send_notification_letter(letter_id, COORD))


def mark_letter_undeliverable(core: dict, letter_id: str, reason: str = "Returned by the postal service") -> dict:
    from .factories import undeliverable_payload

    return get_success_data(
        api_client.mark_letter_undeliverable(
            letter_id, undeliverable_payload(undeliverable_reason=reason), COORD
        )
    )


def setup_queued_letter(core: dict, exam_id: Optional[str] = None) -> dict:
    """An interpreted dense exam with its first letter still `QUEUED`."""
    target = exam_id or core.get("dense_exam_id")
    if target is None:
        target = setup_dense_screening_exam(core)["id"]
    letter = generate_letter(core, target)
    core["letter"] = letter
    core["letter_id"] = letter["id"]
    return letter


def setup_sent_letter(core: dict, exam_id: Optional[str] = None) -> dict:
    letter = setup_queued_letter(core, exam_id)
    sent = send_letter(core, letter["id"])
    core["letter"] = sent
    core["letter_id"] = sent["id"]
    return sent


# ---------------------------------------------------------------------------
# Tier 3: supplemental orders
# ---------------------------------------------------------------------------


def recommend_order(core: dict, exam_id: str, modality: str = "ULTRASOUND", headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_supplemental_order(
            exam_id, supplemental_order_payload(modality, **overrides), headers or COORD
        )
    )


def determine_coverage(core: dict, order_id: str) -> dict:
    return get_success_data(api_client.determine_coverage(order_id, COORD))


def schedule_order(core: dict, order_id: str, appointment_start: str = "2026-08-01T09:00:00Z") -> dict:
    return get_success_data(
        api_client.schedule_supplemental_order(
            order_id, schedule_payload(appointment_start), COORD
        )
    )


def complete_order(core: dict, order_id: str) -> dict:
    from .factories import complete_order_payload

    return get_success_data(
        api_client.complete_supplemental_order(order_id, COORD, complete_order_payload())
    )


def setup_recommended_order(core: dict, modality: str = "ULTRASOUND", density: str = "C") -> dict:
    """A dense screening exam carrying one `RECOMMENDED` supplemental order."""
    exam = core.get("dense_exam") or setup_dense_screening_exam(core, density=density)
    order = recommend_order(core, exam["id"], modality)
    core["order"] = order
    core["order_id"] = order["id"]
    return order


def setup_determined_order(core: dict, modality: str = "ULTRASOUND", density: str = "C") -> dict:
    order = setup_recommended_order(core, modality, density)
    determined = determine_coverage(core, order["id"])
    core["order"] = determined
    core["order_id"] = determined["id"]
    return determined


def setup_scheduled_order(core: dict, appointment_start: str = "2026-08-01T09:00:00Z", modality: str = "ULTRASOUND") -> dict:
    order = setup_determined_order(core, modality)
    scheduled = schedule_order(core, order["id"], appointment_start)
    core["order"] = scheduled
    core["order_id"] = scheduled["id"]
    return scheduled


# ---------------------------------------------------------------------------
# Tier 3: credits and qualification reviews
# ---------------------------------------------------------------------------


def post_ce_credit(core: dict, personnel_id: str, ce_hours: float, awarded_on: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_credit(
            personnel_id, ce_credit_payload(ce_hours, awarded_on, **overrides), COORD
        )
    )


def post_volume_credit(core: dict, personnel_id: str, exam_count: int, awarded_on: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_credit(
            personnel_id, volume_credit_payload(exam_count, awarded_on, **overrides), COORD
        )
    )


def run_qualification_review(core: dict, personnel_id: str, **overrides) -> dict:
    from .factories import qualification_review_payload

    return get_success_data(
        api_client.run_qualification_review(
            personnel_id, COORD, qualification_review_payload(**overrides)
        )
    )


def setup_fully_credited_technologist(core: dict, personnel_id: Optional[str] = None) -> dict:
    """Post enough hours and volume that the review finds no shortfall at all."""
    target = personnel_id or core["tech_id"]
    post_ce_credit(core, target, 7.50)
    post_ce_credit(core, target, 7.75)
    post_volume_credit(core, target, 200)
    return run_qualification_review(core, target)


def setup_person_in_grace(core: dict, personnel_id: Optional[str] = None) -> dict:
    """One review with no credits posted at all: first detection moves ce_status to GRACE."""
    target = personnel_id or core["rad_id"]
    return run_qualification_review(core, target)


# ---------------------------------------------------------------------------
# Tier 3: audit cycles
# ---------------------------------------------------------------------------


def open_cycle(core: dict, radiologist_id: Optional[str] = None, **overrides) -> dict:
    target = radiologist_id or core["rad_id"]
    return get_success_data(
        api_client.create_audit_cycle(target, audit_cycle_payload(**overrides), QA)
    )


def close_cycle(core: dict, cycle_id: str, variant: str = "PPV1_SCREENING", headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.close_audit_cycle(cycle_id, close_cycle_payload(variant), headers or QA)
    )


def cycle_metrics(core: dict, cycle_id: str, variant: Optional[str] = None, headers: Optional[dict] = None) -> dict:
    params = {"variant": variant} if variant else None
    return get_success_data(
        api_client.get_audit_cycle_metrics(cycle_id, headers or QA, params)
    )


def setup_locked_cycle(core: dict, variant: str = "PPV1_SCREENING", **cycle_overrides) -> dict:
    """An elapsed period closed under the requested variant."""
    cycle = open_cycle(core, **cycle_overrides)
    locked = close_cycle(core, cycle["id"], variant)
    core["cycle"] = locked
    core["cycle_id"] = locked["id"]
    return locked


def setup_scored_screening_exam(core: dict, birads: int = 0, pathology_result: str = "MALIGNANT", **overrides) -> dict:
    """A screening exam recalled, biopsied and settled, so both PPV variants can score it."""
    defaults = {"performed_at": "2026-03-01T00:00:00Z", "patient_ref": "PT-AUD-1"}
    defaults.update(overrides)
    exam = acquire_and_interpret(core, birads=birads, density="B", **defaults)
    record_outcome(core, exam["id"], True, pathology_result)
    return read_exam(exam["id"])


# ---------------------------------------------------------------------------
# Tier 5: compliance runs
# ---------------------------------------------------------------------------


def run_compliance(core: dict, facility_id: Optional[str] = None, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.run_compliance_run(facility_id or core["facility_id"], headers or COORD)
    )


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def list_total_count(response) -> int:
    """Read `meta.total_count` off a listing response."""
    return response.json()["meta"]["total_count"]
