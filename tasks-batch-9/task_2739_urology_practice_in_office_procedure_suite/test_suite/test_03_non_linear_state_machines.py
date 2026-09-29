"""
Non-linear state machines of the Urology Procedure Suite contract.

Two shapes are exercised here. The first is a procedure case, which carries two
genuinely independent dimensions: ``schedule_status`` on the room calendar and
``clearance_status`` on the patient's preparation. The clearance dimension walks
CLEARED -> BLOCKED -> CLEARED while the schedule dimension never leaves
SCHEDULED, and the schedule dimension separately takes its SCHEDULED ->
SCHEDULED self-loop through a reschedule while clearance stays CLEARED.

The second is a flexible cystoscope, whose ``status`` leaves AVAILABLE, passes
through IN_USE and SOILED, sits in REPROCESSING across three consecutive stage
closures that mutate other fields without moving the status, and finally returns
to the state it started in.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_fields,
    assert_null_fields,
    assert_not_null_fields,
    assert_occupancy_window,
)
from test_helpers.constants import (
    CASE_COMPLETED,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    CLEARANCE_BLOCKED,
    CLEARANCE_CLEARED,
    CLEARANCE_DECISION_BLOCK,
    CLEARANCE_DECISION_CLEAR,
    CLEARANCE_PENDING_PREP,
    DEFAULT_BLOCK_REASON_CODE,
    LOG_CLOSED,
    OUTCOME_PASS,
    ROOM_TYPE_CYSTO_SUITE,
    SCOPE_AVAILABLE,
    SCOPE_REPROCESSING,
    SCOPE_SOILED,
    STAGE_HIGH_LEVEL_DISINFECT,
    STAGE_LEAK_TEST,
    STAGE_MANUAL_CLEAN,
    STAGE_PRECLEAN,
    STAGE_SEQUENCE,
    TYPE_CYSTOSCOPY,
)

# ─── Fixed instants of these scenarios ──────────────────────────────────────
# The two-dimension case scenario runs the logical clock well before the case,
# so both the original and the moved window sit in the future.
PARALLEL_CLOCK = "2026-09-14T07:00:00Z"
PARALLEL_START = "2026-09-14T14:00:00.000Z"
PARALLEL_END = "2026-09-14T14:20:00.000Z"
PARALLEL_BLOCK_END = "2026-09-14T14:40:00.000Z"
PARALLEL_MOVED_START = "2026-09-14T16:00:00.000Z"
PARALLEL_MOVED_END = "2026-09-14T16:20:00.000Z"
PARALLEL_MOVED_BLOCK_END = "2026-09-14T16:40:00.000Z"

# The reprocessing scenario parks the clock on the case's start instant, so the
# check-in, the completion and every stage closure share one logical instant.
CYCLE_CLOCK = "2026-09-14T14:00:00Z"
CYCLE_INSTANT = "2026-09-14T14:00:00.000Z"
CYCLE_START = "2026-09-14T14:00:00.000Z"
# Twelve hours after the completion instant.
CYCLE_REPROCESS_DUE = "2026-09-15T02:00:00.000Z"


# ─── Local scenario builders ────────────────────────────────────────────────
def _build_two_dimension_case(api, roster):
    """
    A cystoscopy case sitting on the calendar of a cystoscopy suite whose
    baseline turnover allowance is 10 minutes, for a patient who is neither
    anticoagulated nor renally impaired. The procedure type asks for no scope,
    no prophylaxis and no preparation instructions, so nothing outside the two
    state dimensions interferes with the scenario.
    """
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
        required_prep_codes=[],
    )
    patient = get_success_data(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=roster.urologist["id"],
                mrn="MRN-4204",
                full_name="Dana Wray",
                date_of_birth="1971-11-05",
                egfr=60,
                anticoagulant_flag=False,
            ),
            roster.scheduler_headers,
        ),
        201,
    )
    fx.set_clock(api, PARALLEL_CLOCK)
    case = fx.draft_case(api, roster, patient, procedure_type, room, PARALLEL_START)
    return {
        "room": room,
        "procedure_type": procedure_type,
        "patient": patient,
        "case": case,
    }


def _review_clearance(api, case_id, decision, headers, block_reason_code=None):
    """Submit one clearance decision and return the affected case row."""
    return validate_success(
        api.review_clearance(
            case_id,
            f.clearance_review_payload(decision, block_reason_code=block_reason_code),
            headers,
        )
    )


def _build_checked_in_scope_case(api, roster):
    """
    A scope-bearing cystoscopy case brought into the room. The scope is
    registered and then commissioned on the manufacturer's factory attestation,
    so it carries a high-level-disinfection stamp and may be used on a patient;
    the clock is parked on the case's own start instant before the case is
    drafted, so the check-in, the completion and every reprocessing stage
    closure all happen at one logical instant.
    """
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=True,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    patient = get_success_data(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=roster.urologist["id"],
                mrn="MRN-4205",
                full_name="Kai Merrit",
                date_of_birth="1966-03-19",
                egfr=60,
            ),
            roster.scheduler_headers,
        ),
        201,
    )
    scope = fx.build_ready_scope(
        api,
        roster,
        serial_number="SCP-7781",
        scope_model="Olympus CYF-VH",
        channel_count=1,
    )
    fx.set_clock(api, CYCLE_CLOCK)
    case = fx.draft_case(api, roster, patient, procedure_type, room, CYCLE_START)
    fx.assign_scope(api, roster, case["id"], scope)
    fx.commit_case(api, roster, case, room)
    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    return {
        "room": room,
        "procedure_type": procedure_type,
        "patient": patient,
        "scope": scope,
        "case": case,
    }


def _close_stage(api, roster, scope_id, stage, case_id, outcome=OUTCOME_PASS):
    """
    Open one sterile-processing stage log and close it with a second-person
    attestation. The performing technician and the attesting technician are
    different people, and the attester is the caller who closes the log.
    """
    opened = get_success_data(
        api.create_reprocessing_log(
            f.reprocessing_log_payload(
                scope_asset_id=scope_id,
                performed_by_provider_id=roster.tech["id"],
                stage=stage,
                case_id=case_id,
            ),
            roster.tech_headers,
        ),
        201,
    )
    return validate_success(
        api.complete_reprocessing_log(
            opened["id"],
            f.reprocessing_complete_payload(roster.tech_alt["id"], outcome=outcome),
            roster.tech_alt_headers,
        )
    )


def _read_scope(api, roster, scope_id):
    return validate_success(api.get_scope_asset(scope_id, roster.tech_headers))


# ═══ A case's two independent dimensions, and the cycle inside clearance ═════
def test_clearance_cycle_never_disturbs_the_schedule_dimension(api, roster):
    """PRD §3.4: "A case can be `SCHEDULED` and `PENDING_PREP`, or `DRAFT` and
    `CLEARED`, or `SCHEDULED` and `BLOCKED`, and all three are ordinary working
    states."
    PRD §3.4: "The clearance dimension is genuinely cyclic: a case blocked
    because the patient ate breakfast can be re-cleared once the case is moved
    to the afternoon, and blocked again if something else surfaces, all without
    the case ever leaving `SCHEDULED`."
    PRD §3.4: "A successful clear sets `clearance_block_reason` back to null and
    recomputes the readiness gates."
    PRD §3.4: "The supplied value is stored in the case's
    `clearance_block_reason`, and the readiness gates are recomputed."

    Design: Difficulty/non_linear_state_machine/nl_case_parallel_dimensions_clearance_cycle
    """
    stage = _build_two_dimension_case(api, roster)
    case, room = stage["case"], stage["room"]

    scheduled = fx.commit_case(api, roster, case, room)
    assert_case_dimensions(scheduled, CASE_SCHEDULED, CLEARANCE_PENDING_PREP)
    assert_occupancy_window(
        scheduled,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at=PARALLEL_START,
        scheduled_end_at=PARALLEL_END,
        block_end_at=PARALLEL_BLOCK_END,
    )

    cleared = _review_clearance(
        api, case["id"], CLEARANCE_DECISION_CLEAR, roster.nurse_headers
    )
    assert_case_dimensions(cleared, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_null_fields(cleared, "clearance_block_reason")

    blocked = _review_clearance(
        api,
        case["id"],
        CLEARANCE_DECISION_BLOCK,
        roster.urologist_headers,
        block_reason_code=DEFAULT_BLOCK_REASON_CODE,
    )
    assert_case_dimensions(blocked, CASE_SCHEDULED, CLEARANCE_BLOCKED)
    assert_fields(blocked, clearance_block_reason=DEFAULT_BLOCK_REASON_CODE)

    recleared = _review_clearance(
        api, case["id"], CLEARANCE_DECISION_CLEAR, roster.nurse_headers
    )
    assert_case_dimensions(recleared, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_null_fields(recleared, "clearance_block_reason")

    # The clearance round trip touched neither the calendar position nor the
    # occupancy window the commit computed.
    assert_occupancy_window(
        recleared,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at=PARALLEL_START,
        scheduled_end_at=PARALLEL_END,
        block_end_at=PARALLEL_BLOCK_END,
    )

    persisted = validate_success(
        api.get_procedure_case(case["id"], roster.scheduler_headers)
    )
    assert_case_dimensions(persisted, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_null_fields(persisted, "clearance_block_reason")


def test_scheduled_case_carries_a_blocked_clearance_and_still_moves(api, roster):
    """PRD §3.4: "Every case carries two independent state dimensions, and
    understanding that independence is essential to implementing it."
    PRD §3.4: "They advance on different operations and neither gates the
    other's transitions — with one exception, check-in, where the two finally
    meet."
    PRD §3.4: "`BLOCK` is declared from `PENDING_PREP`, from
    `PREP_ACKNOWLEDGED` and from `CLEARED`, and lands on `BLOCKED`."
    PRD §3.3: "Rescheduling is also the `Scheduler`'s exclusive act and it
    leaves `schedule_status` at `SCHEDULED` — a self-loop rather than a
    transition."

    Design: Difficulty/non_linear_state_machine/nl_case_parallel_dimensions_clearance_cycle
    """
    stage = _build_two_dimension_case(api, roster)
    case, room = stage["case"], stage["room"]

    fx.commit_case(api, roster, case, room)
    blocked = _review_clearance(
        api,
        case["id"],
        CLEARANCE_DECISION_BLOCK,
        roster.nurse_headers,
        block_reason_code=DEFAULT_BLOCK_REASON_CODE,
    )
    assert_case_dimensions(blocked, CASE_SCHEDULED, CLEARANCE_BLOCKED)
    assert_fields(blocked, clearance_block_reason=DEFAULT_BLOCK_REASON_CODE)

    # A blocked clearance does not gate the schedule dimension: the case still
    # moves on the calendar, and it stays SCHEDULED while it does.
    moved = validate_success(
        api.reschedule_case(
            case["id"],
            f.reschedule_payload(PARALLEL_MOVED_START),
            roster.scheduler_headers,
        )
    )
    assert_case_dimensions(moved, CASE_SCHEDULED, CLEARANCE_BLOCKED)
    assert_occupancy_window(
        moved,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at=PARALLEL_MOVED_START,
        scheduled_end_at=PARALLEL_MOVED_END,
        block_end_at=PARALLEL_MOVED_BLOCK_END,
    )

    # And the clearance dimension is still free to move afterwards.
    recleared = _review_clearance(
        api, case["id"], CLEARANCE_DECISION_CLEAR, roster.nurse_headers
    )
    assert_case_dimensions(recleared, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_null_fields(recleared, "clearance_block_reason")


def test_reschedule_self_loop_recomputes_the_window_and_keeps_clearance(api, roster):
    """PRD §3.3: "Rescheduling is also the `Scheduler`'s exclusive act and it
    leaves `schedule_status` at `SCHEDULED` — a self-loop rather than a
    transition."
    PRD §3.3: "The whole window is recomputed against the target room's
    *current* `turnover_minutes`, which is how a room whose baseline allowance
    was retuned after the original booking finally gets its new figure applied."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."
    PRD §3.2: "That product is then floored at a quarter of an hour: whichever
    of the product and 15 minutes is larger becomes the working figure."

    Design: Difficulty/non_linear_state_machine/nl_case_parallel_dimensions_clearance_cycle
    """
    stage = _build_two_dimension_case(api, roster)
    case, room = stage["case"], stage["room"]

    fx.commit_case(api, roster, case, room)
    fx.clear_case(api, roster, case["id"])

    moved = validate_success(
        api.reschedule_case(
            case["id"],
            f.reschedule_payload(PARALLEL_MOVED_START),
            roster.scheduler_headers,
        )
    )
    assert_case_dimensions(moved, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_occupancy_window(
        moved,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at=PARALLEL_MOVED_START,
        scheduled_end_at=PARALLEL_MOVED_END,
        block_end_at=PARALLEL_MOVED_BLOCK_END,
    )

    # The move left both durations exactly as the original commit computed them:
    # 20 procedure minutes, and a turnover of max(10 * 2, 15) with no scope
    # handling to add.
    fetched = validate_success(
        api.get_procedure_case(case["id"], roster.scheduler_headers)
    )
    assert_fields(fetched, turnover_minutes=20, procedure_minutes=20)
    assert_case_dimensions(fetched, CASE_SCHEDULED, CLEARANCE_CLEARED)
    assert_fields(
        fetched,
        scheduled_start_at=PARALLEL_MOVED_START,
        scheduled_end_at=PARALLEL_MOVED_END,
        block_end_at=PARALLEL_MOVED_BLOCK_END,
    )


# ═══ The scope's five-stage cycle back to its initial state ══════════════════
def test_case_completion_soils_the_scope_and_stamps_the_reprocessing_deadline(
    api, roster
):
    """PRD §3.5: "A scope's `status` describes where it sits in a genuine cycle,
    not a one-way lifecycle: `AVAILABLE` when it is clean and on the shelf,
    `IN_USE` when a case is holding it, `SOILED` immediately after a patient
    cycle, `REPROCESSING` while its stage logs are being worked through, and
    `QUARANTINED` when something has gone wrong."
    PRD §3.5: "When the case that holds it is completed, the scope moves from
    `IN_USE` to `SOILED`, `cycles_since_leak_test` is increased by 1,
    `reprocess_due_at` is set to twelve hours after the logical clock instant of
    the completion — the deadline by which reprocessing must finish — and the
    scope's `version` increments."

    Design: Difficulty/non_linear_state_machine/nl_scope_reprocessing_full_cycle
    """
    stage = _build_checked_in_scope_case(api, roster)
    case, scope = stage["case"], stage["scope"]

    completed = fx.complete_case(
        api,
        roster,
        case["id"],
        headers=roster.urologist_headers,
        outcome_note="diagnostic cystoscopy, no lesion",
    )
    assert_fields(completed, schedule_status=CASE_COMPLETED)

    soiled = _read_scope(api, roster, scope["id"])
    assert_fields(
        soiled,
        status=SCOPE_SOILED,
        cycles_since_leak_test=1,
        leak_test_required=False,
        reprocess_due_at=CYCLE_REPROCESS_DUE,
    )


def test_reprocessing_stages_hold_the_scope_in_reprocessing(api, roster):
    """PRD §3.5: "A passing `PRECLEAN` on a `SOILED` scope moves it to
    `REPROCESSING` and increments its `version`."
    PRD §3.5: "A passing `LEAK_TEST` zeroes `cycles_since_leak_test` and sets
    `leak_test_required` back to `false`, incrementing the scope's `version`."
    PRD §3.5: "A passing `MANUAL_CLEAN` closes its own log but drives no
    scope-side change at all: the scope's `status`, counters, timestamps and
    `version` are all left exactly as they were."
    PRD §3.5: "A passing `HIGH_LEVEL_DISINFECT` sets the scope's `hld_pass_at`
    to the log's `completed_at` and increments the scope's `version`, while the
    `status` stays at `REPROCESSING`."
    PRD §3.5: "A successful close sets `log_status` to `CLOSED`, records
    `completed_at` at the logical clock instant, and stores the `outcome`."

    Design: Difficulty/non_linear_state_machine/nl_scope_reprocessing_full_cycle
    """
    stage = _build_checked_in_scope_case(api, roster)
    case, scope = stage["case"], stage["scope"]
    scope_id = scope["id"]

    fx.complete_case(
        api,
        roster,
        case["id"],
        headers=roster.urologist_headers,
        outcome_note="diagnostic cystoscopy, no lesion",
    )

    _close_stage(api, roster, scope_id, STAGE_PRECLEAN, case["id"])
    after_preclean = _read_scope(api, roster, scope_id)
    assert_fields(after_preclean, status=SCOPE_REPROCESSING)

    _close_stage(api, roster, scope_id, STAGE_LEAK_TEST, case["id"])
    after_leak_test = _read_scope(api, roster, scope_id)
    assert_fields(
        after_leak_test,
        status=SCOPE_REPROCESSING,
        cycles_since_leak_test=0,
        leak_test_required=False,
    )

    before_manual_clean = _read_scope(api, roster, scope_id)
    _close_stage(api, roster, scope_id, STAGE_MANUAL_CLEAN, case["id"])
    after_manual_clean = _read_scope(api, roster, scope_id)
    assert_fields(
        after_manual_clean,
        status=SCOPE_REPROCESSING,
        cycles_since_leak_test=before_manual_clean["cycles_since_leak_test"],
        leak_test_required=before_manual_clean["leak_test_required"],
        hld_pass_at=before_manual_clean["hld_pass_at"],
        reprocess_due_at=before_manual_clean["reprocess_due_at"],
    )

    hld_log = _close_stage(
        api, roster, scope_id, STAGE_HIGH_LEVEL_DISINFECT, case["id"]
    )
    assert_fields(
        hld_log,
        log_status=LOG_CLOSED,
        outcome=OUTCOME_PASS,
        completed_at=CYCLE_INSTANT,
    )
    after_hld = _read_scope(api, roster, scope_id)
    assert_fields(after_hld, status=SCOPE_REPROCESSING, hld_pass_at=CYCLE_INSTANT)
    assert after_hld["hld_pass_at"] == hld_log["completed_at"], (
        "hld_pass_at must be the closing log's completed_at, got "
        f"{after_hld['hld_pass_at']!r} against {hld_log['completed_at']!r}"
    )


def test_dry_store_returns_the_scope_to_the_state_it_started_in(api, roster):
    """PRD §3.5: "A passing `DRY_STORE` returns the scope from `REPROCESSING` to
    `AVAILABLE`, clears `reprocess_due_at` to null and increments the scope's
    `version` — but only if a closed, passing `HIGH_LEVEL_DISINFECT` log exists
    for that scope whose `completed_at` is at or after the moment the scope most
    recently became `SOILED`."
    PRD §3.5: "The five stages run in the fixed sequence `PRECLEAN`,
    `LEAK_TEST`, `MANUAL_CLEAN`, `HIGH_LEVEL_DISINFECT`, `DRY_STORE`, and a
    newly opened log's `stage` must be the immediate successor of the scope's
    last closed passing stage."

    Design: Difficulty/non_linear_state_machine/nl_scope_reprocessing_full_cycle
    """
    stage = _build_checked_in_scope_case(api, roster)
    case, scope = stage["case"], stage["scope"]
    scope_id = scope["id"]

    # The scope starts the scenario on the shelf; the cycle must bring it back.
    assert_fields(scope, status=SCOPE_AVAILABLE)

    fx.complete_case(
        api,
        roster,
        case["id"],
        headers=roster.urologist_headers,
        outcome_note="diagnostic cystoscopy, no lesion",
    )
    for reprocessing_stage in STAGE_SEQUENCE:
        _close_stage(api, roster, scope_id, reprocessing_stage, case["id"])

    final = _read_scope(api, roster, scope_id)
    assert_fields(
        final,
        status=SCOPE_AVAILABLE,
        cycles_since_leak_test=0,
        leak_test_required=False,
    )
    assert_null_fields(final, "reprocess_due_at")
    assert_not_null_fields(final, "hld_pass_at")


def test_reprocessing_audit_trail_holds_five_closed_passing_stages(api, roster):
    """PRD §2.11: "Reprocessing logs may be filtered by `scope_asset_id`,
    `case_id`, `performed_by_provider_id`, `attested_by_provider_id`, `stage`,
    `log_status` and `outcome` — this is the practice's reprocessing audit
    trail."
    PRD §3.5: "A successful close sets `log_status` to `CLOSED`, records
    `completed_at` at the logical clock instant, and stores the `outcome`."
    PRD §3.5: "The five stages run in the fixed sequence `PRECLEAN`,
    `LEAK_TEST`, `MANUAL_CLEAN`, `HIGH_LEVEL_DISINFECT`, `DRY_STORE`, and a
    newly opened log's `stage` must be the immediate successor of the scope's
    last closed passing stage."

    Design: Difficulty/non_linear_state_machine/nl_scope_reprocessing_full_cycle
    """
    stage = _build_checked_in_scope_case(api, roster)
    case, scope = stage["case"], stage["scope"]
    scope_id = scope["id"]

    fx.complete_case(
        api,
        roster,
        case["id"],
        headers=roster.urologist_headers,
        outcome_note="diagnostic cystoscopy, no lesion",
    )
    for reprocessing_stage in STAGE_SEQUENCE:
        _close_stage(api, roster, scope_id, reprocessing_stage, case["id"])

    rows, meta = validate_paginated(
        api.list_reprocessing_logs(roster.tech_headers, scope_asset_id=scope_id)
    )
    assert meta["total_count"] == 5, (
        f"the scope's audit trail must hold five stage logs, got {meta['total_count']}"
    )
    assert len(rows) == 5, f"expected five rows on the page, got {len(rows)}"
    assert sorted(row["stage"] for row in rows) == sorted(STAGE_SEQUENCE), (
        "the audit trail must carry each of the five stages exactly once, got "
        f"{[row['stage'] for row in rows]}"
    )
    for row in rows:
        assert_fields(row, log_status=LOG_CLOSED, outcome=OUTCOME_PASS)

    # Every stage of this cycle was closed by the second technician, who is not
    # the one who performed it.
    for row in rows:
        assert row["performed_by_provider_id"] == roster.tech["id"], (
            "performed_by_provider_id: expected "
            f"{roster.tech['id']!r}, got {row['performed_by_provider_id']!r}"
        )
        assert row["attested_by_provider_id"] == roster.tech_alt["id"], (
            "attested_by_provider_id: expected "
            f"{roster.tech_alt['id']!r}, got {row['attested_by_provider_id']!r}"
        )

    # And the scope has come back round to the state it started in.
    final = _read_scope(api, roster, scope_id)
    assert_fields(final, status=SCOPE_AVAILABLE, leak_test_required=False)
    assert_null_fields(final, "reprocess_due_at")
