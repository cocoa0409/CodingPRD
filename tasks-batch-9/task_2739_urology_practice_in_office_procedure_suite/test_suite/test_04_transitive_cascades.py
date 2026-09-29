"""
Multi-hop cascades of the Urology Procedure Suite contract.

Two chains are exercised here, each of which reaches well past the row the
caller named.

The first runs off a case completion: reaching ``COMPLETED`` satisfies one
surveillance recall of the case's patient, and that recall reaching
``SATISFIED`` in turn re-derives the patient's outstanding-recall counter and
advances the patient's version. The middle hop is selective — the patient is
carried on two open protocols and only the one whose qualifying procedure the
completed case actually was may be touched, even when the other is due sooner.

The second runs off filing a pathology result: the graded result opens the
notification conversation with a computed escalation deadline, inserts a fresh
surveillance recall whose protocol and risk tier come from the specimen class
and the grade, supersedes the recall that new row displaces while back-linking
it as the predecessor, and finally re-derives the patient's counter and
version.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_null_fields
from test_helpers.constants import (
    BASIS_PROTOCOL_ANCHORED,
    CASE_COMPLETED,
    CHAIN_RESULTED,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CONDITION_INTACT,
    NOTIFY_PENDING,
    PROTOCOL_BLADDER_CANCER,
    PROTOCOL_PROSTATE,
    PROTOCOL_STONE,
    RECALL_SATISFIED,
    RECALL_SCHEDULED_DUE,
    RECALL_SUPERSEDED,
    RESULT_MALIGNANT,
    ROOM_TYPE_CYSTO_SUITE,
    SPECIMEN_PROSTATE_CORE,
    TIER_HIGH,
    TIER_INTERMEDIATE,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)

# ─── The cystoscopy scenario ────────────────────────────────────────────────
CYSTO_CLOCK = "2026-10-05T14:00:00Z"
CYSTO_START_AT = "2026-10-05T14:00:00.000Z"
CYSTO_COMPLETED_AT = "2026-10-05T14:00:00.000Z"
STONE_ANCHOR_DATE = "2026-08-31"
STONE_DUE_ON = "2027-02-28"
BLADDER_ANCHOR_DATE = "2026-09-30"
BLADDER_DUE_ON = "2027-03-30"

# ─── The prostate biopsy scenario ───────────────────────────────────────────
BIOPSY_CLOCK = "2026-09-15T09:00:00Z"
BIOPSY_START_AT = "2026-09-15T09:00:00.000Z"
BIOPSY_RESULT_AT = "2026-09-15T09:00:00.000Z"
BIOPSY_ANCHOR_DATE = "2026-09-15"
OLD_PROSTATE_ANCHOR_DATE = "2026-06-30"
OLD_PROSTATE_DUE_ON = "2026-12-30"
NEW_PROSTATE_INTERVAL_MONTHS = 3
NEW_PROSTATE_DUE_ON = "2026-12-15"
MALIGNANT_ESCALATION_DUE_AT = "2026-09-16T09:00:00.000Z"


def _build_two_protocol_recall_book(api) -> Dict[str, Any]:
    """
    A patient carried on two open surveillance protocols with a cystoscopy
    checked in and ready to close.

    The stone recall is deliberately due earlier than the bladder-cancer one, so
    a chain that ranks the candidates before filtering them by protocol picks
    the wrong row. The procedure type asks for nothing at all — no scope, no
    prophylaxis, no specimen and no preparation instructions — so the only
    interesting thing about the completion is its fan-out.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(api, roster.urologist, egfr=60)
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        requires_specimen=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, CYSTO_CLOCK)

    stone_recall = fx.open_recall(
        api,
        roster,
        patient,
        protocol=PROTOCOL_STONE,
        risk_tier=TIER_HIGH,
        anchor_date=STONE_ANCHOR_DATE,
    )
    bladder_recall = fx.open_recall(
        api,
        roster,
        patient,
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_INTERMEDIATE,
        anchor_date=BLADDER_ANCHOR_DATE,
    )

    case = fx.draft_case(api, roster, patient, procedure_type, room, CYSTO_START_AT)
    case = fx.commit_case(api, roster, case, room)
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])

    patient_before = fx.read_patient(api, roster, patient["id"])
    return {
        "roster": roster,
        "patient": patient,
        "patient_before": patient_before,
        "room": room,
        "procedure_type": procedure_type,
        "stone_recall": stone_recall,
        "bladder_recall": bladder_recall,
        "case": case,
    }


def _build_prostate_biopsy_with_open_recall(api) -> Dict[str, Any]:
    """
    A prostate biopsy whose container has already been received in the
    laboratory, on a patient who is separately carried on one open prostate
    recall.

    The case is completed *before* that recall is opened, so the completion's
    own recall-satisfaction cascade finds an empty candidate set and leaves the
    recall book alone; every recall movement observed afterwards therefore
    belongs to the result-filing chain.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, egfr=60, anticoagulant_flag=False
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        requires_specimen=True,
        consignment_required=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, BIOPSY_CLOCK)

    case = fx.draft_case(api, roster, patient, procedure_type, room, BIOPSY_START_AT)
    case = fx.commit_case(api, roster, case, room)
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])

    specimen = fx.collect_specimen(
        api,
        roster,
        case["id"],
        specimen_type=SPECIMEN_PROSTATE_CORE,
        container_label="TR-CORE-01",
        site_code="RIGHT_APEX",
    )
    fx.accession_specimen(
        api,
        roster,
        specimen["id"],
        received_at=BIOPSY_START_AT,
        condition_on_receipt=CONDITION_INTACT,
        accession_number="ACC-2026-0915-01",
    )
    case = fx.complete_case(
        api, roster, case["id"], headers=roster.urologist_headers,
        outcome_note="12-core biopsy",
    )

    old_recall = fx.open_recall(
        api,
        roster,
        patient,
        protocol=PROTOCOL_PROSTATE,
        risk_tier=TIER_INTERMEDIATE,
        anchor_date=OLD_PROSTATE_ANCHOR_DATE,
    )
    patient_before = fx.read_patient(api, roster, patient["id"])
    return {
        "roster": roster,
        "patient": patient,
        "patient_before": patient_before,
        "case": case,
        "specimen": specimen,
        "old_recall": old_recall,
    }


# ─── Completion → recall satisfaction → patient counter (three hops) ────────
def test_completion_satisfies_only_the_protocol_matching_recall(api):
    """A completed cystoscopy satisfies the bladder-cancer recall, not the stone one.

    PRD §3.7: "Because the case reached `COMPLETED`, the service looks for
    surveillance recalls belonging to that case's patient whose `status` is
    `SCHEDULED_DUE` or `OVERDUE` and whose protocol counts this procedure as a
    surveillance event — `STONE` recalls are satisfied by an `OFFICE_ULTRASOUND`,
    `BLADDER_CANCER` recalls by a `CYSTOSCOPY`, and `PROSTATE` recalls by a
    `PROSTATE_BIOPSY`."
    PRD §3.7: "That single recall transitions to `SATISFIED`, its
    `satisfying_case_id` is set to the completing case, and its `lapse_days` is
    reset to 0."
    PRD §3.7: "On success `completed_at` records the logical clock instant, and
    the room's `occupied_block_count` is recomputed — a completed case still
    occupies its historical block, so the count does not fall."

    Design: Difficulty/transitive_cascade/tc_complete_case_recall_patient_depth3
    """
    scenario = _build_two_protocol_recall_book(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]

    completed = validate_success(
        api.complete_case(
            case_id,
            f.complete_case_payload(outcome_note="surveillance cystoscopy"),
            roster.urologist_headers,
        )
    )
    assert_fields(
        completed,
        schedule_status=CASE_COMPLETED,
        completed_at=CYSTO_COMPLETED_AT,
    )

    bladder = validate_success(
        api.get_surveillance_recall(
            scenario["bladder_recall"]["id"], roster.urologist_headers
        )
    )
    assert_fields(
        bladder,
        status=RECALL_SATISFIED,
        satisfying_case_id=case_id,
        lapse_days=0,
        due_on=BLADDER_DUE_ON,
    )


def test_completion_leaves_the_earlier_due_non_matching_recall_untouched(api):
    """The stone recall is due sooner yet is never a candidate for a cystoscopy.

    PRD §3.7: "Among those candidates exactly **one** is chosen: the earliest
    `due_on`, with ties broken by the earlier `created_at`."
    PRD §3.7: "Sibling recalls are left alone, and when the candidate set is
    empty no recall is touched at all."
    PRD §3.9: "A `STONE` recall is due in 24 months at `LOW` risk, 12 months at
    `INTERMEDIATE` and 6 months at `HIGH`."
    PRD §3.9: "`due_on` is that interval added to a date, and the arithmetic is
    calendar-month arithmetic with a clamp rather than a rollover: advancing a
    date by *n* months lands in the target year and month, and the day of month
    is the smaller of the original day and the last day of the target month."

    Design: Difficulty/transitive_cascade/tc_complete_case_recall_patient_depth3
    """
    scenario = _build_two_protocol_recall_book(api)
    roster = scenario["roster"]
    stone_id = scenario["stone_recall"]["id"]

    before = validate_success(
        api.get_surveillance_recall(stone_id, roster.urologist_headers)
    )
    assert_fields(before, status=RECALL_SCHEDULED_DUE, due_on=STONE_DUE_ON)
    assert before["due_on"] < BLADDER_DUE_ON, (
        "the stone recall must be due strictly earlier than the bladder-cancer "
        f"recall for this scenario to bite, got {before['due_on']!r} against "
        f"{BLADDER_DUE_ON!r}"
    )

    validate_success(
        api.complete_case(
            scenario["case"]["id"],
            f.complete_case_payload(outcome_note="surveillance cystoscopy"),
            roster.urologist_headers,
        )
    )

    after = validate_success(
        api.get_surveillance_recall(stone_id, roster.urologist_headers)
    )
    assert_fields(
        after,
        status=RECALL_SCHEDULED_DUE,
        lapse_days=0,
        due_on=STONE_DUE_ON,
    )
    assert_null_fields(after, "satisfying_case_id")


def test_completion_recall_cascade_recomputes_patient_counter_and_version(api):
    """The satisfied recall drives the third hop onto the patient chart.

    PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."
    PRD §3.7: "Then, because that recall reached `SATISFIED`, the patient's
    `outstanding_recall_count` is recomputed and the patient's `version`
    increments by 1 — the third hop of the cascade, and the reason a completion
    can invalidate a client's held `expected_patient_version`."

    Design: Difficulty/transitive_cascade/tc_complete_case_recall_patient_depth3
    """
    scenario = _build_two_protocol_recall_book(api)
    roster = scenario["roster"]
    patient_id = scenario["patient"]["id"]

    before = validate_success(api.get_patient(patient_id, roster.urologist_headers))
    assert_fields(before, outstanding_recall_count=2)

    validate_success(
        api.complete_case(
            scenario["case"]["id"],
            f.complete_case_payload(outcome_note="surveillance cystoscopy"),
            roster.urologist_headers,
        )
    )

    after = validate_success(api.get_patient(patient_id, roster.urologist_headers))
    assert_fields(after, outstanding_recall_count=1)
    assert after["version"] > before["version"], (
        "the patient's version must advance when the completion cascade "
        f"recomputes the recall counter, got {after['version']} against "
        f"{before['version']} before the completion"
    )


# ─── Result filing → notification, new recall, supersession, patient ────────
def test_malignant_result_opens_the_notification_loop_with_a_computed_escalation_clock(
    api,
):
    """Filing a malignant grade records it and arms the notification deadline.

    PRD §3.8: "The first hop records the result on the specimen:
    `pathology_result` is stored, `result_at` is set to the logical clock
    instant, `chain_status` advances from `ACCESSIONED` to `RESULTED`,
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` with
    `notification_attempt_count` still at 0, and `escalation_due_at` is
    computed."
    PRD §3.8: "The grade drives the base window: a `MALIGNANT` result must be
    communicated within 24 hours, an `ATYPICAL` result within 72 hours, a
    `BENIGN` result within 168 hours — a full week — and where no grade exists at
    all, which is the compromised-container case, the `INSUFFICIENT` window of 72
    hours applies."
    PRD §3.8: "Step two tests **that provisional instant, and only that
    instant**: if it falls on a Saturday or a Sunday in UTC, a weekend extension
    of 48 hours applies, otherwise the extension is zero."
    PRD §3.8: "Step three computes a backoff of 12 hours multiplied by the
    attempt count less one, floored at zero, where the attempt count is the value
    *after* the current attempt has been counted — so a first attempt contributes
    no backoff at all, a second contributes 12 hours and a third 24."

    Design: Difficulty/transitive_cascade/tc_specimen_result_recall_supersede_depth4
    """
    scenario = _build_prostate_biopsy_with_open_recall(api)
    roster = scenario["roster"]

    resulted = validate_success(
        api.result_specimen(
            scenario["specimen"]["id"],
            f.result_payload(RESULT_MALIGNANT),
            roster.pathologist_headers,
        )
    )
    assert_fields(
        resulted,
        chain_status=CHAIN_RESULTED,
        pathology_result=RESULT_MALIGNANT,
        result_at=BIOPSY_RESULT_AT,
        notification_status=NOTIFY_PENDING,
        notification_attempt_count=0,
        escalation_due_at=MALIGNANT_ESCALATION_DUE_AT,
    )


def test_malignant_result_inserts_a_recall_mapped_from_specimen_type_and_grade(api):
    """The new recall's protocol comes from the container, its tier from the grade.

    PRD §3.8: "A result of `BENIGN`, `ATYPICAL` or `MALIGNANT` creates a recall
    for the case's patient whose `protocol` is determined by the specimen class
    (a `PROSTATE_CORE` maps to `PROSTATE`, a `BLADDER_WASHING` to
    `BLADDER_CANCER`, and a `BIOPSY_FRAGMENT` to `PROSTATE`) and whose
    `risk_tier` is determined by the grade (`MALIGNANT` maps to `HIGH`,
    `ATYPICAL` to `INTERMEDIATE`, and `BENIGN` to `LOW`), with `anchor_date` set
    to the logical clock date, `due_basis` `PROTOCOL_ANCHORED`, and
    `source_specimen_id` naming this specimen."
    PRD §3.9: "The recall interval is a lookup on the pair of `protocol` and
    `risk_tier`, and it lands in `interval_months`."
    PRD §3.9: "`PROSTATE` uses the same figures as `BLADDER_CANCER` — 12, 6 and 3
    months respectively."

    Design: Difficulty/transitive_cascade/tc_specimen_result_recall_supersede_depth4
    """
    scenario = _build_prostate_biopsy_with_open_recall(api)
    roster = scenario["roster"]
    old_recall_id = scenario["old_recall"]["id"]
    specimen_id = scenario["specimen"]["id"]

    validate_success(
        api.result_specimen(
            specimen_id, f.result_payload(RESULT_MALIGNANT), roster.pathologist_headers
        )
    )

    rows, meta = validate_paginated(
        api.list_surveillance_recalls(
            roster.urologist_headers, predecessor_recall_id=old_recall_id
        )
    )
    assert meta["total_count"] == 1, (
        "filing the result must insert exactly one recall back-linked to the "
        f"superseded row, got total_count {meta['total_count']}"
    )
    assert len(rows) == 1, f"expected one recall row on the page, got {len(rows)}"

    new_recall = rows[0]
    assert_fields(
        new_recall,
        protocol=PROTOCOL_PROSTATE,
        risk_tier=TIER_HIGH,
        anchor_date=BIOPSY_ANCHOR_DATE,
        interval_months=NEW_PROSTATE_INTERVAL_MONTHS,
        due_on=NEW_PROSTATE_DUE_ON,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        status=RECALL_SCHEDULED_DUE,
        source_specimen_id=specimen_id,
        predecessor_recall_id=old_recall_id,
    )


def test_malignant_result_supersedes_the_open_prostate_recall_and_backlinks_it(api):
    """The recall the new row displaces is superseded, not left open beside it.

    PRD §3.9: "The new row is stored with `status` `SCHEDULED_DUE`, `lapse_days`
    0, `due_basis` `PROTOCOL_ANCHORED`, and `predecessor_recall_id` null unless
    there is something to supersede — and if there is, the same supersession rule
    that governs cascade-created recalls applies here: every other recall of the
    same `patient_id` and `protocol` whose `status` is `SCHEDULED_DUE` or
    `OVERDUE` becomes `SUPERSEDED`, the newest of them is recorded as this row's
    `predecessor_recall_id`, and the patient's `outstanding_recall_count` is
    recomputed with the patient's `version` incremented by 1."
    PRD §3.8: "Because the second hop inserted a new recall, the third hop
    supersedes the old ones: every *other* surveillance recall of that patient
    sharing the new recall's `protocol` whose `status` is `SCHEDULED_DUE` or
    `OVERDUE` is processed in ascending `created_at` order and transitions to
    `SUPERSEDED`, and the newest of those rows is recorded as the new recall's
    `predecessor_recall_id`."

    Design: Difficulty/transitive_cascade/tc_specimen_result_recall_supersede_depth4
    """
    scenario = _build_prostate_biopsy_with_open_recall(api)
    roster = scenario["roster"]
    old_recall_id = scenario["old_recall"]["id"]

    before = validate_success(
        api.get_surveillance_recall(old_recall_id, roster.urologist_headers)
    )
    assert_fields(
        before, status=RECALL_SCHEDULED_DUE, due_on=OLD_PROSTATE_DUE_ON
    )
    assert_null_fields(before, "predecessor_recall_id")

    validate_success(
        api.result_specimen(
            scenario["specimen"]["id"],
            f.result_payload(RESULT_MALIGNANT),
            roster.pathologist_headers,
        )
    )

    after = validate_success(
        api.get_surveillance_recall(old_recall_id, roster.urologist_headers)
    )
    assert_fields(after, status=RECALL_SUPERSEDED)


def test_result_cascade_recomputes_patient_counter_and_version(api):
    """The fourth hop lands on the patient chart, one open recall later.

    PRD §3.8: "Because the third hop changed recall statuses, the fourth hop
    recomputes the patient's `outstanding_recall_count` and increments the
    patient's `version` by 1."
    PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."

    Design: Difficulty/transitive_cascade/tc_specimen_result_recall_supersede_depth4
    """
    scenario = _build_prostate_biopsy_with_open_recall(api)
    roster = scenario["roster"]
    patient_id = scenario["patient"]["id"]

    before = validate_success(api.get_patient(patient_id, roster.urologist_headers))
    assert_fields(before, outstanding_recall_count=1)

    validate_success(
        api.result_specimen(
            scenario["specimen"]["id"],
            f.result_payload(RESULT_MALIGNANT),
            roster.pathologist_headers,
        )
    )

    after = validate_success(api.get_patient(patient_id, roster.urologist_headers))
    assert_fields(after, outstanding_recall_count=1)
    assert after["version"] > before["version"], (
        "the patient's version must advance when the result cascade rewrites the "
        f"recall book, got {after['version']} against {before['version']} before "
        "the result was filed"
    )
