"""
Read-your-own-write behaviour of the Urology Practice & In-Office Procedure
Suite API.

Every derived value this contract defines is produced by the write that caused
it, not by some later reconciliation pass. These tests walk one prostate biopsy
from the room calendar through the laboratory and check, at each step, that the
mutation's own response body already carries the derived figures, and that
reading the mutated rows again afterwards returns exactly the same values. The
surfaces exercised are the occupancy window on a calendar commit, the readiness
picture taken immediately after a clearance decision, the patient's derived
counters across a completion, and the escalation deadline and the recall the
pathology result files.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_occupancy_window,
    assert_readiness,
    assert_version_unchanged,
)
from test_helpers.constants import (
    BASIS_PROTOCOL_ANCHORED,
    CASE_COMPLETED,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CHAIN_ACCESSIONED,
    CHAIN_RESULTED,
    CLEANUP_HIGH,
    CLEARANCE_CLEARED,
    CONDITION_INTACT,
    NOTIFY_PENDING,
    PROTOCOL_PROSTATE,
    RECALL_SCHEDULED_DUE,
    RESULT_MALIGNANT,
    ROOM_TYPE_CYSTO_SUITE,
    SPECIMEN_PROSTATE_CORE,
    TIER_HIGH,
    TYPE_PROSTATE_BIOPSY,
)

# The whole scenario runs at one logical instant: Friday 18 September 2026 at
# 09:00 UTC, which is also the case's scheduled start.
CLOCK = "2026-09-18T09:00:00Z"
CASE_START_AT = "2026-09-18T09:00:00.000Z"

PATIENT_MRN = "MRN-5083"
PATIENT_NAME = "Xan Ivy"
PATIENT_DOB = "1953-03-13"
PATIENT_EGFR = 63

ROOM_NAME = "Cysto A"
ROOM_TURNOVER_MINUTES = 10

BASE_MINUTES = 30

# base_minutes 30, no anticoagulant addition and no renal addition (egfr 63 is
# not below 45), so the in-room duration is the bare baseline.
EXPECTED_PROCEDURE_MINUTES = 30
# The room's baseline 10 minutes doubled for HIGH cleanup is 20, which already
# clears the quarter-hour floor, and this type needs no scope.
EXPECTED_TURNOVER_MINUTES = 20
EXPECTED_END_AT = "2026-09-18T09:30:00.000Z"
EXPECTED_BLOCK_END_AT = "2026-09-18T09:50:00.000Z"

RECEIVED_AT = "2026-09-18T10:00:00Z"
ACCESSION_NUMBER = "ACC-7200"
CONTAINER_LABEL = "CUP-1"
SITE_CODE = "LEFT-BASE"

# A MALIGNANT grade must be reached within 24 hours of result_at, which lands
# provisionally on Saturday 19 September, so the 48-hour weekend extension
# applies; the first attempt has not been made, so there is no backoff.
EXPECTED_ESCALATION_DUE_AT = "2026-09-21T09:00:00.000Z"

# A PROSTATE recall at HIGH risk is due three months after its anchor date.
EXPECTED_RECALL_DUE_ON = "2026-12-18"
EXPECTED_RECALL_ANCHOR_DATE = "2026-09-18"


def _build_drafted_biopsy(api):
    """One prostate biopsy drafted onto Friday morning, not yet committed."""
    roster = fx.build_roster(api)
    room = fx.create_room(
        api,
        ROOM_TYPE_CYSTO_SUITE,
        name=ROOM_NAME,
        turnover_minutes=ROOM_TURNOVER_MINUTES,
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=BASE_MINUTES,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_specimen=True,
        required_prep_codes=[],
    )
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn=PATIENT_MRN,
        full_name=PATIENT_NAME,
        date_of_birth=PATIENT_DOB,
        egfr=PATIENT_EGFR,
    )
    fx.set_clock(api, CLOCK)
    case = fx.draft_case(api, roster, patient, procedure_type, room, CLOCK)
    return {
        "roster": roster,
        "room": room,
        "procedure_type": procedure_type,
        "patient": patient,
        "case": case,
    }


def _commit(api, scenario):
    """Put the drafted case on the room calendar and return the response body."""
    return validate_success(
        api.schedule_case(
            scenario["case"]["id"],
            f.schedule_payload(scenario["room"]["version"]),
            scenario["roster"].scheduler_headers,
        )
    )


def _bring_into_room(api, scenario):
    """Clear the case and check the patient in, returning the IN_ROOM case."""
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]
    _commit(api, scenario)
    fx.clear_case(api, roster, case_id)
    return fx.check_in_case(api, roster, case_id)


def _collect_by_nurse(api, scenario):
    """
    Collect the biopsy container as the nurse in the room, who is also the
    acting user, and return the new specimen.
    """
    roster = scenario["roster"]
    return validate_success(
        api.create_specimen(
            f.specimen_payload(
                case_id=scenario["case"]["id"],
                collected_by_provider_id=roster.nurse["id"],
                container_label=CONTAINER_LABEL,
                specimen_type=SPECIMEN_PROSTATE_CORE,
                site_code=SITE_CODE,
            ),
            roster.nurse_headers,
        ),
        expected_status=201,
    )


def _receive_intact(api, roster, specimen_id):
    """Receive the container in the laboratory, sound and intact."""
    return fx.accession_specimen(
        api,
        roster,
        specimen_id,
        RECEIVED_AT,
        CONDITION_INTACT,
        accession_number=ACCESSION_NUMBER,
    )


# ─── The calendar commit answers with the whole window ───────────────────────
def test_commit_response_already_carries_the_derived_occupancy_window(api):
    """The commit's own response body holds the recomputed duration, turnover
    and both derived instants; nothing is left for a follow-up read to supply.

    PRD §3.3: "A successful commit recomputes `procedure_minutes`,
    `turnover_minutes`, `scheduled_end_at` and `block_end_at` from scratch,
    increments the room's `version` by 1 because the room's occupancy ledger has
    changed, recomputes that room's `occupied_block_count`, and recomputes the
    case's readiness gates."
    PRD §3.2: "Two derived instants close the window out. `scheduled_end_at` is
    `scheduled_start_at` advanced by `procedure_minutes` minutes, and
    `block_end_at` is `scheduled_end_at` advanced by `turnover_minutes` minutes."
    PRD §3.2: "First the room's own `turnover_minutes` is multiplied by a cleanup
    multiplier of 2 when the procedure type's `cleanup_class` is `HIGH` and by 1
    when it is `LOW`."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)

    committed = _commit(api, scenario)

    assert_fields(committed, schedule_status=CASE_SCHEDULED)
    assert_occupancy_window(
        committed,
        procedure_minutes=EXPECTED_PROCEDURE_MINUTES,
        turnover_minutes=EXPECTED_TURNOVER_MINUTES,
        scheduled_start_at=CASE_START_AT,
        scheduled_end_at=EXPECTED_END_AT,
        block_end_at=EXPECTED_BLOCK_END_AT,
    )


def test_reading_the_committed_case_twice_returns_the_very_same_body(api):
    """A second read never reveals a figure the first read missed: two reads
    taken back to back agree on every field, version included.

    PRD §2.5: "Nothing in this system reads the host machine's wall clock."
    PRD §2.4: "any row whose stored fields change as a result of a request has
    its `version` incremented once for that request and its `updated_at`
    refreshed."
    PRD §3.2: "Even though a draft occupies nothing, its window is computed
    immediately, because the front desk needs to see how long the case will run
    before committing it."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]

    committed = _commit(api, scenario)

    first = validate_success(api.get_procedure_case(case_id, roster.admin_headers))
    second = validate_success(api.get_procedure_case(case_id, roster.admin_headers))

    assert first == second, (
        "two consecutive reads of the same case must be identical, but they "
        f"differ: {[k for k in set(first) | set(second) if first.get(k) != second.get(k)]}"
    )
    assert_version_unchanged(committed, first)
    assert_occupancy_window(
        first,
        procedure_minutes=EXPECTED_PROCEDURE_MINUTES,
        turnover_minutes=EXPECTED_TURNOVER_MINUTES,
        scheduled_start_at=CASE_START_AT,
        scheduled_end_at=EXPECTED_END_AT,
        block_end_at=EXPECTED_BLOCK_END_AT,
    )


def test_readiness_read_straight_after_the_clearance_review_is_already_clear(api):
    """Granting clearance opens the last gate in the same write, so the
    readiness read taken immediately afterwards already permits the check-in.

    PRD §3.4: "A successful clear sets `clearance_block_reason` back to null and
    recomputes the readiness gates."
    PRD §3.7: "It reports the `case_id`, both dimensions as `schedule_status` and
    `clearance_status`, the ordered `blocking_reason_codes`, the convenience
    field `first_blocking_reason_code` — the first element of that array, or null
    when the array is empty — and `check_in_allowed`, a boolean that is true
    exactly when the case's `schedule_status` is `SCHEDULED` and the gate array
    is empty."
    PRD §3.4: "When `required_prep_codes` is the empty array the requirement is
    satisfied vacuously, which is the only way a case reaches `CLEARED` straight
    out of `PENDING_PREP` with no acknowledgements recorded."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]
    _commit(api, scenario)

    cleared = fx.clear_case(api, roster, case_id)
    assert_fields(cleared, clearance_status=CLEARANCE_CLEARED)
    assert cleared["blocking_reason_codes"] == [], (
        "the clearance response itself must already show no unmet gates, got "
        f"{cleared['blocking_reason_codes']}"
    )

    readiness = validate_success(api.get_case_readiness(case_id, roster.nurse_headers))
    assert_fields(
        readiness,
        case_id=case_id,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_CLEARED,
    )
    assert_readiness(readiness, [], check_in_allowed=True)


# ─── The completion recomputes the patient's counters in its own write ───────
def test_completion_with_no_open_recall_leaves_the_patient_counter_at_zero(api):
    """This patient has no surveillance obligation for the completion to
    satisfy, so the recall counter is recomputed to the same 0 the chart already
    carried — and it is already 0 by the time the completion answers.

    PRD §3.7: "Sibling recalls are left alone, and when the candidate set is
    empty no recall is touched at all."
    PRD §2.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the number
    of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`. Both initialise to 0."
    PRD §3.7: "On success `completed_at` records the logical clock instant, and
    the room's `occupied_block_count` is recomputed — a completed case still
    occupies its historical block, so the count does not fall."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]
    patient_id = scenario["patient"]["id"]

    in_room = _bring_into_room(api, scenario)
    assert_fields(in_room, schedule_status=CASE_IN_ROOM)

    specimen = _collect_by_nurse(api, scenario)
    _receive_intact(api, roster, specimen["id"])

    completed = fx.complete_case(api, roster, case_id)
    assert_fields(completed, schedule_status=CASE_COMPLETED)

    patient = fx.read_patient(api, roster, patient_id)
    assert_fields(patient, outstanding_recall_count=0)


# ─── Filing the result answers with the escalation deadline already set ──────
def test_result_response_already_carries_the_escalation_deadline(api):
    """The response to the result filing itself reports the opened notification
    loop and the computed deadline; no later read is needed to see them.

    PRD §3.8: "The first hop records the result on the specimen:
    `pathology_result` is stored, `result_at` is set to the logical clock instant,
    `chain_status` advances from `ACCESSIONED` to `RESULTED`,
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` with
    `notification_attempt_count` still at 0, and `escalation_due_at` is computed."
    PRD §3.8: "The grade drives the base window: a `MALIGNANT` result must be
    communicated within 24 hours, an `ATYPICAL` result within 72 hours, a `BENIGN`
    result within 168 hours — a full week — and where no grade exists at all,
    which is the compromised-container case, the `INSUFFICIENT` window of 72
    hours applies."
    PRD §3.8: "Step two tests **that provisional instant, and only that
    instant**: if it falls on a Saturday or a Sunday in UTC, a weekend extension
    of 48 hours applies, otherwise the extension is zero."
    PRD §3.8: "Step four adds the weekend extension and the backoff to the
    provisional instant, and the sum is `escalation_due_at`."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    _bring_into_room(api, scenario)

    specimen = _collect_by_nurse(api, scenario)
    accessioned = _receive_intact(api, roster, specimen["id"])
    assert_fields(accessioned, chain_status=CHAIN_ACCESSIONED)
    fx.complete_case(api, roster, scenario["case"]["id"])

    resulted = validate_success(
        api.result_specimen(
            specimen["id"],
            f.result_payload(RESULT_MALIGNANT),
            roster.pathologist_headers,
        )
    )
    assert_fields(
        resulted,
        pathology_result=RESULT_MALIGNANT,
        chain_status=CHAIN_RESULTED,
        notification_status=NOTIFY_PENDING,
        notification_attempt_count=0,
        result_at=CASE_START_AT,
        escalation_due_at=EXPECTED_ESCALATION_DUE_AT,
    )


def test_reading_the_specimen_after_the_result_repeats_the_result_body(api):
    """Reading the specimen back returns exactly what the result filing already
    reported, field for field.

    PRD §2.5: "Nothing in this system reads the host machine's wall clock."
    PRD §2.4: "any row whose stored fields change as a result of a request has
    its `version` incremented once for that request and its `updated_at`
    refreshed."
    PRD §3.8: "The first hop records the result on the specimen:
    `pathology_result` is stored, `result_at` is set to the logical clock instant,
    `chain_status` advances from `ACCESSIONED` to `RESULTED`,
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` with
    `notification_attempt_count` still at 0, and `escalation_due_at` is computed."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    _bring_into_room(api, scenario)

    specimen = _collect_by_nurse(api, scenario)
    _receive_intact(api, roster, specimen["id"])
    fx.complete_case(api, roster, scenario["case"]["id"])
    resulted = fx.result_specimen(api, roster, specimen["id"], RESULT_MALIGNANT)

    read_back = validate_success(
        api.get_specimen(specimen["id"], roster.pathologist_headers)
    )
    assert read_back == resulted, (
        "the read of the specimen must repeat the result response exactly, but "
        f"these fields differ: "
        f"{[k for k in set(read_back) | set(resulted) if read_back.get(k) != resulted.get(k)]}"
    )
    assert_version_unchanged(resulted, read_back)


def test_the_result_write_files_the_recall_and_opens_the_loop_at_once(api):
    """Both of the patient's derived counters move inside the write that filed
    the result: the new surveillance recall and the open notification are on the
    chart the moment the result is accepted.

    PRD §3.8: "A result of `BENIGN`, `ATYPICAL` or `MALIGNANT` creates a recall
    for the case's patient whose `protocol` is determined by the specimen class (a
    `PROSTATE_CORE` maps to `PROSTATE`, a `BLADDER_WASHING` to `BLADDER_CANCER`,
    and a `BIOPSY_FRAGMENT` to `PROSTATE`) and whose `risk_tier` is determined by
    the grade (`MALIGNANT` maps to `HIGH`, `ATYPICAL` to `INTERMEDIATE`, and
    `BENIGN` to `LOW`), with `anchor_date` set to the logical clock date,
    `due_basis` `PROTOCOL_ANCHORED`, and `source_specimen_id` naming this
    specimen."
    PRD §3.8: "Because the third hop changed recall statuses, the fourth hop
    recomputes the patient's `outstanding_recall_count` and increments the
    patient's `version` by 1."
    PRD §3.9: "`PROSTATE` uses the same figures as `BLADDER_CANCER` — 12, 6 and 3
    months respectively."
    PRD §2.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the number
    of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`. Both initialise to 0."

    Design: Corner/consistency_model/consistency_immediate_all_effects_visible_in_same_response
    """
    scenario = _build_drafted_biopsy(api)
    roster = scenario["roster"]
    patient_id = scenario["patient"]["id"]
    _bring_into_room(api, scenario)

    specimen = _collect_by_nurse(api, scenario)
    _receive_intact(api, roster, specimen["id"])
    fx.complete_case(api, roster, scenario["case"]["id"])
    fx.result_specimen(api, roster, specimen["id"], RESULT_MALIGNANT)

    patient = fx.read_patient(api, roster, patient_id)
    assert_fields(patient, outstanding_recall_count=1, open_notification_count=1)

    recalls, meta = validate_paginated(
        api.list_surveillance_recalls(roster.urologist_headers, patient_id=patient_id)
    )
    assert meta["total_count"] == 1, (
        "the graded result must have filed exactly one recall, got "
        f"total_count {meta['total_count']}"
    )
    assert_fields(
        recalls[0],
        protocol=PROTOCOL_PROSTATE,
        risk_tier=TIER_HIGH,
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        anchor_date=EXPECTED_RECALL_ANCHOR_DATE,
        due_on=EXPECTED_RECALL_DUE_ON,
        source_specimen_id=specimen["id"],
    )
