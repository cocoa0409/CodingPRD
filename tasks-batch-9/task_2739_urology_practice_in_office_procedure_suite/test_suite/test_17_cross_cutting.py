"""
Cross-cutting guarantees of the urology suite: the four stale-parent-version
guards, the version counter as a write counter, and the two derived counters
that must reconcile rather than only climb.

Three concerns are exercised here, and all three cut across every entity of the
contract rather than belonging to one workflow.

The first is optimistic concurrency. Four writes reach across into a record that
other writers also mutate — committing a case to the room calendar, assigning a
scope, reserving consigned device units and opening a surveillance recall — and
each carries the version the client last observed. Every probe below holds a
version that was current when it was captured and has since been advanced by an
unrelated successful write, so each refusal must name that guard's own error and
answer HTTP 412; and every probe is then repeated with the re-read version to
prove the guard is a concurrency check and not a blanket refusal.

The second is the meaning of the version counter itself. It counts writes, not
state changes: it advances on a write that leaves the schedule dimension exactly
where it was, stays put across a read, and stays put when a write is refused.

The third is derived-counter reconciliation. A patient's outstanding recall
count and a room's occupied block count are both recomputed from their source
sets on every write, so both must fall as well as rise, and both must hold flat
when one row enters the counted set as another leaves it.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_NOT_CLEARED,
    ERR_SCOPE_NOT_AVAILABLE,
    ERR_STALE_LOT_VERSION,
    ERR_STALE_PATIENT_VERSION,
    ERR_STALE_ROOM_VERSION,
    ERR_STALE_SCOPE_VERSION,
)
from test_helpers.assertions import (
    assert_fields,
    assert_lot_counters,
    assert_version_advanced,
    assert_version_unchanged,
)
from test_helpers.constants import (
    BASIS_PROTOCOL_ANCHORED,
    CASE_DRAFT,
    CASE_COMPLETED,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CHANNEL_PHONE,
    CLEANUP_HIGH,
    CLEARANCE_CLEARED,
    CLEARANCE_DECISION_CLEAR,
    CLEARANCE_PENDING_PREP,
    CLEARANCE_PREP_ACKNOWLEDGED,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_STATE_NONE,
    DEVICE_STATE_RESERVED,
    PROTOCOL_BLADDER_CANCER,
    PROTOCOL_STONE,
    RECALL_CLOSED,
    RECALL_SCHEDULED_DUE,
    RECALL_SUPERSEDED,
    ROOM_TYPE_CYSTO_SUITE,
    SCOPE_IN_USE,
    TIER_HIGH,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
)

# ─── The one dataset every concurrency probe runs against ───────────────────

CONCURRENCY_CLOCK = "2026-09-14T07:00:00Z"
CASE_1_START_AT = "2026-09-14T09:00:00Z"
CASE_2_START_AT = "2026-09-14T11:00:00Z"
DEVICE_SKU = "BX-KIT-1"
RECALL_ANCHOR_DATE = "2026-09-01"
PREP_CODE_NPO_MIDNIGHT = "NPO_MIDNIGHT"


def _build_concurrency_stage(api):
    """
    One practice, one patient, one room, one scope and one consignment lot, plus
    two cystoscopy cases that both still sit in draft.

    Each of the four guarded parents is then advanced by exactly one unrelated
    successful write against the *first* case — the room by committing it to the
    calendar, the scope by assigning it, the lot by reserving a unit, and the
    patient by an ordinary renal-function edit — so the versions captured at
    creation time are all one behind by the time the probes run.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5080",
        full_name="Uma Frey",
        date_of_birth="1954-04-24",
        egfr=66,
    )
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
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=True,
        single_use_device_sku=DEVICE_SKU,
        required_prep_codes=[],
    )
    scope = fx.create_scope(
        api,
        roster.tech,
        serial_number="SN-E",
        scope_model="FlexCysto 200",
        channel_count=2,
    )
    lot = fx.create_lot(
        api,
        supplier_name="Medline",
        sku=DEVICE_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=10,
        unit_price_cents=4500,
        lot_expires_on="2027-06-30",
    )
    fx.set_clock(api, CONCURRENCY_CLOCK, roster.admin_headers)

    stage = SimpleNamespace(
        roster=roster,
        patient=patient,
        room=room,
        procedure_type=procedure_type,
        scope=scope,
        lot=lot,
        room_v0=room["version"],
        scope_v0=scope["version"],
        lot_v0=lot["version"],
        patient_v0=patient["version"],
    )

    stage.case_1 = fx.draft_case(
        api, roster, patient, procedure_type, room, CASE_1_START_AT
    )
    stage.case_2 = fx.draft_case(
        api, roster, patient, procedure_type, room, CASE_2_START_AT
    )

    # Four unrelated successful writes, one per guarded parent.
    validate_success(
        api.schedule_case(
            stage.case_1["id"],
            f.schedule_payload(stage.room_v0),
            roster.scheduler_headers,
        )
    )
    validate_success(
        api.assign_scope(
            stage.case_1["id"],
            f.scope_assignment_payload(scope["id"], stage.scope_v0),
            roster.nurse_headers,
        )
    )
    validate_success(
        api.reserve_device(
            stage.case_1["id"],
            f.device_reservation_payload(lot["id"], 1, stage.lot_v0),
            roster.nurse_headers,
        )
    )
    validate_success(
        api.update_patient(
            patient["id"],
            f.patient_update_payload(egfr=55),
            roster.urologist_headers,
        )
    )
    return stage


def test_case_schedule_with_stale_room_version_rejected_then_accepted_on_reread(api):
    """PRD §2.6: "Committing a drafted case to the room calendar must carry
    `expected_room_version`, matching the current `version` of the
    `ProcedureRoom` the case names."
    PRD §2.6: "If the value does not match, the commit is refused with
    `ERR_STALE_ROOM_VERSION` and HTTP 412: a client holding an older room
    version cannot have evaluated the overlap rules against the ledger the
    server now holds."
    PRD §3.3: "A successful commit recomputes `procedure_minutes`,
    `turnover_minutes`, `scheduled_end_at` and `block_end_at` from scratch,
    increments the room's `version` by 1 because the room's occupancy ledger has
    changed, recomputes that room's `occupied_block_count`, and recomputes the
    case's readiness gates."

    Design: Corner/cross_cutting_complexity_layers/ccl_optimistic_concurrency_stale_parent_version_rejected
    """
    stage = _build_concurrency_stage(api)
    roster = stage.roster

    # The first commit already advanced the room's occupancy ledger, so the
    # version captured when the room was commissioned is one behind.
    room_before = fx.read_room(api, roster, stage.room["id"])
    assert room_before["version"] == stage.room_v0 + 1, (
        "committing the first case must advance the room's version by exactly "
        f"1: expected {stage.room_v0 + 1}, got {room_before['version']}"
    )

    response = api.schedule_case(
        stage.case_2["id"], f.schedule_payload(stage.room_v0), roster.scheduler_headers
    )
    validate_error(response, ERR_STALE_ROOM_VERSION)

    room_after_refusal = fx.read_room(api, roster, stage.room["id"])
    assert_version_unchanged(room_before, room_after_refusal)
    refused_case = fx.read_case(api, roster, stage.case_2["id"])
    assert_fields(refused_case, schedule_status=CASE_DRAFT)

    # Re-reading the room hands the client the version the server now holds, and
    # the very same commit then stands.
    committed = validate_success(
        api.schedule_case(
            stage.case_2["id"],
            f.schedule_payload(room_after_refusal["version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(committed, schedule_status=CASE_SCHEDULED)
    room_end = fx.read_room(api, roster, stage.room["id"])
    assert_fields(room_end, occupied_block_count=2)
    assert_version_advanced(room_after_refusal, room_end)


def test_scope_assignment_stale_version_is_reported_before_scope_availability(api):
    """PRD §2.6: "Assigning a scope to a case must carry
    `expected_scope_asset_version`, matching the current `version` of the
    `ScopeAsset` being assigned."
    PRD §2.6: "A mismatch is refused with `ERR_STALE_SCOPE_VERSION` and HTTP
    412."
    PRD §2.8: "When it does, the response reports exactly one error, and which
    one is fully determined: the service evaluates its checks in a **total
    priority order** and returns the error belonging to the lowest-numbered rule
    that fails."
    PRD §2.8: "**Priority 51 — scope availability.** The scope being assigned
    has `status` `AVAILABLE`; `SOILED`, `REPROCESSING`, `IN_USE` and
    `QUARANTINED` are all refused."

    Design: Corner/cross_cutting_complexity_layers/ccl_optimistic_concurrency_stale_parent_version_rejected
    """
    stage = _build_concurrency_stage(api)
    roster = stage.roster

    # Assigning the scope to the first case both advanced its version and took
    # it out of the available pool, so this one probe can fail two rungs at once.
    scope_before = fx.read_scope(api, roster, stage.scope["id"])
    assert_fields(scope_before, status=SCOPE_IN_USE)
    assert scope_before["version"] == stage.scope_v0 + 1, (
        "assigning the scope must advance its version by exactly 1: expected "
        f"{stage.scope_v0 + 1}, got {scope_before['version']}"
    )

    response = api.assign_scope(
        stage.case_2["id"],
        f.scope_assignment_payload(stage.scope["id"], stage.scope_v0),
        roster.nurse_headers,
    )
    validate_error(response, ERR_STALE_SCOPE_VERSION)

    scope_after_refusal = fx.read_scope(api, roster, stage.scope["id"])
    assert_version_unchanged(scope_before, scope_after_refusal)

    # With the fresh version the concurrency rung passes and the lower-priority
    # availability rung is finally the one that answers.
    second = api.assign_scope(
        stage.case_2["id"],
        f.scope_assignment_payload(
            stage.scope["id"], scope_after_refusal["version"]
        ),
        roster.nurse_headers,
    )
    validate_error(second, ERR_SCOPE_NOT_AVAILABLE)


def test_device_reservation_with_stale_lot_version_rejected_then_accepted_on_reread(api):
    """PRD §2.6: "Reserving single-use device units for a case must carry
    `expected_lot_version`, matching the current `version` of the
    `ConsignmentLot` the units come from."
    PRD §2.6: "A mismatch is refused with `ERR_STALE_LOT_VERSION` and HTTP 412."
    PRD §3.6: "A successful hold writes `device_lot_id` and `device_quantity`
    onto the case and sets its `device_state` to `RESERVED`; the lot's
    `quantity_available` falls by the reserved quantity and its
    `quantity_reserved` rises by the same amount; the lot is re-billed
    provisionally, its `billing_status` re-derived and its `version` incremented
    by 1; and the case's readiness gates are recomputed."

    Design: Corner/cross_cutting_complexity_layers/ccl_optimistic_concurrency_stale_parent_version_rejected
    """
    stage = _build_concurrency_stage(api)
    roster = stage.roster

    # One unit is already held for the first case, which re-derived the lot's
    # available count and advanced its version.
    lot_before = fx.read_lot(api, roster, stage.lot["id"])
    assert_lot_counters(lot_before, available=9, reserved=1, consumed=0, returned=0, wasted=0)
    assert lot_before["version"] == stage.lot_v0 + 1, (
        "the first reservation must advance the lot's version by exactly 1: "
        f"expected {stage.lot_v0 + 1}, got {lot_before['version']}"
    )

    response = api.reserve_device(
        stage.case_2["id"],
        f.device_reservation_payload(stage.lot["id"], 2, stage.lot_v0),
        roster.nurse_headers,
    )
    validate_error(response, ERR_STALE_LOT_VERSION)

    lot_after_refusal = fx.read_lot(api, roster, stage.lot["id"])
    assert_lot_counters(
        lot_after_refusal, available=9, reserved=1, consumed=0, returned=0, wasted=0
    )
    assert_version_unchanged(lot_before, lot_after_refusal)
    refused_case = fx.read_case(api, roster, stage.case_2["id"])
    assert_fields(refused_case, device_state=DEVICE_STATE_NONE)

    held = validate_success(
        api.reserve_device(
            stage.case_2["id"],
            f.device_reservation_payload(
                stage.lot["id"], 2, lot_after_refusal["version"]
            ),
            roster.nurse_headers,
        )
    )
    assert_fields(held, device_state=DEVICE_STATE_RESERVED, device_quantity=2)
    lot_end = fx.read_lot(api, roster, stage.lot["id"])
    assert_lot_counters(lot_end, available=7, reserved=3, consumed=0, returned=0, wasted=0)
    assert_version_advanced(lot_after_refusal, lot_end)


def test_recall_creation_with_stale_patient_version_rejected_then_accepted_on_reread(api):
    """PRD §2.6: "Opening a surveillance recall must carry
    `expected_patient_version`, matching the current `version` of the `Patient`
    the recall is for."
    PRD §2.6: "A mismatch is refused with `ERR_STALE_PATIENT_VERSION` and HTTP
    412 — which is exactly the situation where a recall the client never saw has
    already superseded the row the client intended to supersede."
    PRD §3.1: "It increments the patient's `version`, which is precisely what
    makes a previously captured `expected_patient_version` stale for the recall
    guard of §2.6."
    PRD §3.9: "A `STONE` recall is due in 24 months at `LOW` risk, 12 months at
    `INTERMEDIATE` and 6 months at `HIGH`."

    Design: Corner/cross_cutting_complexity_layers/ccl_optimistic_concurrency_stale_parent_version_rejected
    """
    stage = _build_concurrency_stage(api)
    roster = stage.roster

    # The renal-function edit advanced the patient past the version captured at
    # registration.
    patient_before = fx.read_patient(api, roster, stage.patient["id"])
    assert patient_before["version"] == stage.patient_v0 + 1, (
        "editing the patient's renal function must advance the patient's "
        f"version by exactly 1: expected {stage.patient_v0 + 1}, got "
        f"{patient_before['version']}"
    )

    response = api.create_surveillance_recall(
        f.surveillance_recall_payload(
            patient_id=stage.patient["id"],
            expected_patient_version=stage.patient_v0,
            protocol=PROTOCOL_STONE,
            risk_tier=TIER_LOW,
            anchor_date=RECALL_ANCHOR_DATE,
        ),
        roster.urologist_headers,
    )
    validate_error(response, ERR_STALE_PATIENT_VERSION)

    rows, meta = validate_paginated(
        api.list_surveillance_recalls(roster.admin_headers, patient_id=stage.patient["id"])
    )
    assert meta["total_count"] == 0, (
        f"a refused recall creation must persist nothing, found {meta['total_count']} rows"
    )
    assert rows == [], f"a refused recall creation must persist nothing, got {rows}"
    patient_after_refusal = fx.read_patient(api, roster, stage.patient["id"])
    assert_version_unchanged(patient_before, patient_after_refusal)

    recall = validate_success(
        api.create_surveillance_recall(
            f.surveillance_recall_payload(
                patient_id=stage.patient["id"],
                expected_patient_version=patient_after_refusal["version"],
                protocol=PROTOCOL_STONE,
                risk_tier=TIER_LOW,
                anchor_date=RECALL_ANCHOR_DATE,
            ),
            roster.urologist_headers,
        ),
        201,
    )
    assert_fields(
        recall,
        protocol=PROTOCOL_STONE,
        risk_tier=TIER_LOW,
        interval_months=24,
        due_on="2028-09-01",
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        lapse_days=0,
    )
    patient_end = fx.read_patient(api, roster, stage.patient["id"])
    assert_fields(patient_end, outstanding_recall_count=1)


def test_every_refused_guarded_write_leaves_its_parent_version_untouched(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is
    created and increases by exactly 1 on every mutation of that row."
    PRD §2.4: "Cascaded side effects are described in full in §3; the rule here
    is that any row whose stored fields change as a result of a request has its
    `version` incremented once for that request and its `updated_at` refreshed."

    Design: Corner/cross_cutting_complexity_layers/ccl_optimistic_concurrency_stale_parent_version_rejected
    """
    stage = _build_concurrency_stage(api)
    roster = stage.roster
    case_2_id = stage.case_2["id"]

    probes = [
        (
            "room",
            lambda: fx.read_room(api, roster, stage.room["id"]),
            lambda: api.schedule_case(
                case_2_id, f.schedule_payload(stage.room_v0), roster.scheduler_headers
            ),
            ERR_STALE_ROOM_VERSION,
        ),
        (
            "scope asset",
            lambda: fx.read_scope(api, roster, stage.scope["id"]),
            lambda: api.assign_scope(
                case_2_id,
                f.scope_assignment_payload(stage.scope["id"], stage.scope_v0),
                roster.nurse_headers,
            ),
            ERR_STALE_SCOPE_VERSION,
        ),
        (
            "consignment lot",
            lambda: fx.read_lot(api, roster, stage.lot["id"]),
            lambda: api.reserve_device(
                case_2_id,
                f.device_reservation_payload(stage.lot["id"], 2, stage.lot_v0),
                roster.nurse_headers,
            ),
            ERR_STALE_LOT_VERSION,
        ),
        (
            "patient",
            lambda: fx.read_patient(api, roster, stage.patient["id"]),
            lambda: api.create_surveillance_recall(
                f.surveillance_recall_payload(
                    patient_id=stage.patient["id"],
                    expected_patient_version=stage.patient_v0,
                    protocol=PROTOCOL_STONE,
                    risk_tier=TIER_LOW,
                    anchor_date=RECALL_ANCHOR_DATE,
                ),
                roster.urologist_headers,
            ),
            ERR_STALE_PATIENT_VERSION,
        ),
    ]

    for label, read_parent, refuse, expected_error in probes:
        before = read_parent()
        validate_error(refuse(), expected_error)
        after = read_parent()
        assert after["version"] == before["version"], (
            f"the refused write advanced the {label}'s version from "
            f"{before['version']} to {after['version']}"
        )
        assert_version_unchanged(before, after)


# ─── The version counter counts writes, not state changes ───────────────────

SINGLE_CASE_CLOCK = "2026-09-14T09:00:00Z"
SINGLE_CASE_START_AT = "2026-09-14T09:00:00Z"


def _build_single_case_stage(api):
    """
    One cystoscopy in a cystoscopy suite, drafted and no more, whose procedure
    type demands one preparation instruction and nothing else — no scope, no
    prophylaxis, no consigned device, no specimen — so the whole lifecycle can
    be walked with one write per step and nothing else touching the case.

    The logical clock sits exactly on the case's ``scheduled_start_at``, which is
    inside the early check-in allowance and before the no-show grace expires.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5081",
        full_name="Vic Gale",
        date_of_birth="1962-02-12",
        egfr=64,
    )
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
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[PREP_CODE_NPO_MIDNIGHT],
    )
    fx.set_clock(api, SINGLE_CASE_CLOCK, roster.admin_headers)
    case = fx.draft_case(
        api, roster, patient, procedure_type, room, SINGLE_CASE_START_AT
    )
    return SimpleNamespace(
        roster=roster,
        patient=patient,
        room=room,
        procedure_type=procedure_type,
        case=case,
    )


def test_a_freshly_created_case_is_at_version_one_and_reads_never_advance_it(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is
    created and increases by exactly 1 on every mutation of that row."
    PRD §2.4: "Cascaded side effects are described in full in §3; the rule here
    is that any row whose stored fields change as a result of a request has its
    `version` incremented once for that request and its `updated_at` refreshed."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_every_write
    """
    stage = _build_single_case_stage(api)
    roster = stage.roster

    assert stage.case["version"] == 1, (
        "a freshly created case must be at version 1, got "
        f"{stage.case['version']}"
    )
    assert_fields(
        stage.case,
        schedule_status=CASE_DRAFT,
        clearance_status=CLEARANCE_PENDING_PREP,
    )

    # Three reads of the same row, two of them through a different projection.
    first_read = fx.read_case(api, roster, stage.case["id"])
    validate_success(api.get_case_readiness(stage.case["id"], roster.nurse_headers))
    validate_success(api.get_procedure_case(stage.case["id"], roster.scheduler_headers))
    last_read = fx.read_case(api, roster, stage.case["id"])

    assert first_read["version"] == 1, (
        f"reading a case must not advance its version, got {first_read['version']}"
    )
    assert_version_unchanged(stage.case, first_read)
    assert_version_unchanged(first_read, last_read)


def test_case_version_advances_by_exactly_one_on_each_successive_write(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is
    created and increases by exactly 1 on every mutation of that row."
    PRD §3.4: "Preparation acknowledgements are recorded one instruction at a
    time by a `Scheduler` or a `ProcedureNurse`, each call naming a single
    `instruction_code` and the `channel` through which the patient confirmed
    it."
    PRD §3.7: "Bringing the patient into the room is a `ProcedureNurse`'s
    exclusive act and takes no payload; it advances `schedule_status` from
    `SCHEDULED` to `IN_ROOM`."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_every_write
    """
    stage = _build_single_case_stage(api)
    roster = stage.roster
    case_id = stage.case["id"]

    room = fx.read_room(api, roster, stage.room["id"])
    scheduled = validate_success(
        api.schedule_case(
            case_id, f.schedule_payload(room["version"]), roster.scheduler_headers
        )
    )
    assert_fields(scheduled, schedule_status=CASE_SCHEDULED)
    assert scheduled["version"] == 2, (
        f"committing the case is its second write, got version {scheduled['version']}"
    )
    assert_version_advanced(stage.case, scheduled)

    acknowledged = validate_success(
        api.acknowledge_prep(
            case_id,
            f.prep_acknowledgement_payload(
                instruction_code=PREP_CODE_NPO_MIDNIGHT, channel=CHANNEL_PHONE
            ),
            roster.nurse_headers,
        )
    )
    assert_fields(
        acknowledged,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PREP_ACKNOWLEDGED,
        acknowledged_prep_codes=[PREP_CODE_NPO_MIDNIGHT],
    )
    assert acknowledged["version"] == 3, (
        f"the acknowledgement is the third write, got version {acknowledged['version']}"
    )
    assert_version_advanced(scheduled, acknowledged)

    cleared = validate_success(
        api.review_clearance(
            case_id,
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            roster.nurse_headers,
        )
    )
    assert_fields(
        cleared, schedule_status=CASE_SCHEDULED, clearance_status=CLEARANCE_CLEARED
    )
    assert cleared["version"] == 4, (
        f"the clearance decision is the fourth write, got version {cleared['version']}"
    )
    assert_version_advanced(acknowledged, cleared)

    in_room = validate_success(api.check_in_case(case_id, {}, roster.nurse_headers))
    assert_fields(in_room, schedule_status=CASE_IN_ROOM)
    assert in_room["version"] == 5, (
        f"the check-in is the fifth write, got version {in_room['version']}"
    )
    assert_version_advanced(cleared, in_room)

    completed = validate_success(
        api.complete_case(case_id, f.complete_case_payload(), roster.nurse_headers)
    )
    assert_fields(completed, schedule_status=CASE_COMPLETED)
    assert completed["version"] == 6, (
        f"the completion is the sixth write, got version {completed['version']}"
    )
    assert_version_advanced(in_room, completed)


def test_two_writes_that_leave_the_schedule_dimension_alone_still_advance_version(api):
    """PRD §3.4: "Every case carries two independent state dimensions, and
    understanding that independence is essential to implementing it."
    PRD §3.4: "The case's `schedule_status` must be `DRAFT` or `SCHEDULED` for an
    acknowledgement to be accepted, and the acknowledgement is declared only from
    `clearance_status` `PENDING_PREP` (which advances to `PREP_ACKNOWLEDGED`) and
    from `PREP_ACKNOWLEDGED` itself (which stays put — a self-loop)."
    PRD §2.4: "Cascaded side effects are described in full in §3; the rule here
    is that any row whose stored fields change as a result of a request has its
    `version` incremented once for that request and its `updated_at` refreshed."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_every_write
    """
    stage = _build_single_case_stage(api)
    roster = stage.roster
    case_id = stage.case["id"]

    scheduled = fx.commit_case(api, roster, stage.case, stage.room)

    # Neither of the next two writes is a calendar operation, so the schedule
    # dimension is untouched by both — and both must still count as writes.
    acknowledged = validate_success(
        api.acknowledge_prep(
            case_id,
            f.prep_acknowledgement_payload(
                instruction_code=PREP_CODE_NPO_MIDNIGHT, channel=CHANNEL_PHONE
            ),
            roster.nurse_headers,
        )
    )
    cleared = validate_success(
        api.review_clearance(
            case_id,
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            roster.nurse_headers,
        )
    )

    assert scheduled["schedule_status"] == CASE_SCHEDULED
    assert acknowledged["schedule_status"] == CASE_SCHEDULED, (
        "acknowledging preparation must not move the schedule dimension, got "
        f"{acknowledged['schedule_status']!r}"
    )
    assert cleared["schedule_status"] == CASE_SCHEDULED, (
        "granting clearance must not move the schedule dimension, got "
        f"{cleared['schedule_status']!r}"
    )
    assert_version_advanced(scheduled, acknowledged)
    assert_version_advanced(acknowledged, cleared)
    assert cleared["version"] == scheduled["version"] + 2, (
        "two writes that leave schedule_status alone must still advance the "
        f"case's version twice: expected {scheduled['version'] + 2}, got "
        f"{cleared['version']}"
    )


def test_a_refused_write_leaves_the_case_version_where_the_commit_left_it(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is
    created and increases by exactly 1 on every mutation of that row."
    PRD §2.8: "**Priority 40 — clearance granted.** At check-in the case's
    `clearance_status` is `CLEARED` or `PREP_WAIVED`; `PENDING_PREP`,
    `PREP_ACKNOWLEDGED` and `BLOCKED` all fail. Otherwise
    `ERR_CASE_NOT_CLEARED`, HTTP 409."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_every_write
    """
    stage = _build_single_case_stage(api)
    roster = stage.roster
    case_id = stage.case["id"]

    scheduled = fx.commit_case(api, roster, stage.case, stage.room)
    assert scheduled["version"] == 2, (
        f"committing the case is its second write, got version {scheduled['version']}"
    )

    # Clearance was never granted, so the check-in cannot stand.
    validate_error(
        api.check_in_case(case_id, {}, roster.nurse_headers), ERR_CASE_NOT_CLEARED
    )

    after = fx.read_case(api, roster, case_id)
    assert after["version"] == 2, (
        "a refused check-in must not count as a write: expected the case to "
        f"remain at version 2, got {after['version']}"
    )
    assert_version_unchanged(scheduled, after)
    assert_fields(
        after,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
    )


def test_room_version_advances_only_for_the_write_that_changed_its_ledger(api):
    """PRD §3.3: "A successful commit recomputes `procedure_minutes`,
    `turnover_minutes`, `scheduled_end_at` and `block_end_at` from scratch,
    increments the room's `version` by 1 because the room's occupancy ledger has
    changed, recomputes that room's `occupied_block_count`, and recomputes the
    case's readiness gates."
    PRD §2.4: "Cascaded side effects are described in full in §3; the rule here
    is that any row whose stored fields change as a result of a request has its
    `version` incremented once for that request and its `updated_at` refreshed."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_increments_on_every_write
    """
    stage = _build_single_case_stage(api)
    roster = stage.roster
    case_id = stage.case["id"]

    room_before = fx.read_room(api, roster, stage.room["id"])
    fx.commit_case(api, roster, stage.case, stage.room)
    room_after_commit = fx.read_room(api, roster, stage.room["id"])
    assert_version_advanced(room_before, room_after_commit)
    assert_fields(room_after_commit, occupied_block_count=1)

    # None of the four remaining lifecycle writes changes a stored field of the
    # room, so none of them may bump the room's version.
    fx.acknowledge_all_prep(api, roster, case_id, [PREP_CODE_NPO_MIDNIGHT])
    fx.clear_case(api, roster, case_id)
    fx.check_in_case(api, roster, case_id)
    completed = fx.complete_case(api, roster, case_id)
    assert_fields(completed, schedule_status=CASE_COMPLETED)

    room_end = fx.read_room(api, roster, stage.room["id"])
    assert room_end["version"] == room_before["version"] + 1, (
        "only the calendar commit rewrote the room's occupancy ledger, so the "
        f"room must be at version {room_before['version'] + 1}, got "
        f"{room_end['version']}"
    )
    assert_version_unchanged(room_after_commit, room_end)
    # A completed case still occupies its block, so the count does not fall.
    assert_fields(room_end, occupied_block_count=1)


# ─── Derived counters are recomputed, so they fall as well as rise ──────────

COUNTER_CLOCK = "2026-09-14T09:00:00Z"
COUNTER_NO_SHOW_CLOCK = "2026-09-14T11:16:00Z"
COUNTER_CASE_1_START_AT = "2026-09-14T09:00:00Z"
COUNTER_CASE_2_START_AT = "2026-09-14T11:00:00Z"
STONE_ANCHOR_DATE = "2026-09-01"
BLADDER_ANCHOR_DATE = "2026-09-01"
BLADDER_RESTAGE_ANCHOR_DATE = "2026-09-14"


def _build_counter_stage(api):
    """
    One patient with no recalls at all and one room holding two drafted
    cystoscopies, at 09:00 and at 11:00 — far enough apart that both fit the
    room and the urologist, so both counters start from a clean zero and every
    later movement is attributable to exactly one write.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5082",
        full_name="Wes Hone",
        date_of_birth="1951-11-01",
        egfr=61,
    )
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
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, COUNTER_CLOCK, roster.admin_headers)
    case_1 = fx.draft_case(
        api, roster, patient, procedure_type, room, COUNTER_CASE_1_START_AT
    )
    case_2 = fx.draft_case(
        api, roster, patient, procedure_type, room, COUNTER_CASE_2_START_AT
    )
    assert_fields(room, occupied_block_count=0)
    assert_fields(patient, outstanding_recall_count=0)
    return SimpleNamespace(
        roster=roster,
        patient=patient,
        room=room,
        procedure_type=procedure_type,
        case_1=case_1,
        case_2=case_2,
    )


def _open_recall(api, stage, protocol, risk_tier, anchor_date):
    """Open one recall against the patient's freshly re-read version."""
    current = fx.read_patient(api, stage.roster, stage.patient["id"])
    return validate_success(
        api.create_surveillance_recall(
            f.surveillance_recall_payload(
                patient_id=stage.patient["id"],
                expected_patient_version=current["version"],
                protocol=protocol,
                risk_tier=risk_tier,
                anchor_date=anchor_date,
            ),
            stage.roster.urologist_headers,
        ),
        201,
    )


def test_patient_recall_counter_climbs_on_each_open_recall_and_falls_on_a_close(api):
    """PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the number
    of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."
    PRD §3.9: "Or a `Urologist` can **close** it administratively — a deceased
    patient, a transfer of care, a retired protocol — supplying a `closed_reason`
    that is stored on the row, which again recomputes the patient's
    `outstanding_recall_count` and increments the patient's `version` by 1."
    PRD §3.9: "`BLADDER_CANCER` runs on a tighter cadence: 12 months at `LOW`, 6
    at `INTERMEDIATE`, 3 at `HIGH`."

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_counters
    """
    stage = _build_counter_stage(api)
    roster = stage.roster

    stone = _open_recall(api, stage, PROTOCOL_STONE, TIER_LOW, STONE_ANCHOR_DATE)
    assert_fields(
        stone,
        protocol=PROTOCOL_STONE,
        risk_tier=TIER_LOW,
        interval_months=24,
        due_on="2028-09-01",
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        lapse_days=0,
    )
    after_first = fx.read_patient(api, roster, stage.patient["id"])
    assert_fields(after_first, outstanding_recall_count=1)

    bladder = _open_recall(
        api, stage, PROTOCOL_BLADDER_CANCER, TIER_LOW, BLADDER_ANCHOR_DATE
    )
    assert_fields(
        bladder,
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_LOW,
        interval_months=12,
        due_on="2027-09-01",
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        lapse_days=0,
    )
    after_second = fx.read_patient(api, roster, stage.patient["id"])
    assert_fields(after_second, outstanding_recall_count=2)
    assert_version_advanced(after_first, after_second)

    # A close takes one row out of the counted set, so a counter that is
    # recomputed rather than incremented must fall.
    closed = validate_success(
        api.close_surveillance_recall(
            stone["id"],
            f.recall_close_payload(closed_reason="PATIENT_DECLINED"),
            roster.urologist_headers,
        )
    )
    assert_fields(closed, status=RECALL_CLOSED, closed_reason="PATIENT_DECLINED")

    after_close = fx.read_patient(api, roster, stage.patient["id"])
    assert after_close["outstanding_recall_count"] == 1, (
        "closing one of two open recalls must recompute the counter downward to "
        f"1, got {after_close['outstanding_recall_count']}"
    )
    assert_version_advanced(after_second, after_close)
    # The untouched recall is still open, which is why the counter is 1 and not 0.
    assert_fields(
        fx.read_recall(api, roster, bladder["id"]), status=RECALL_SCHEDULED_DUE
    )


def test_patient_recall_counter_holds_flat_when_a_supersede_swaps_one_open_row(api):
    """PRD §3.9: "The new row is stored with `status` `SCHEDULED_DUE`,
    `lapse_days` 0, `due_basis` `PROTOCOL_ANCHORED`, and `predecessor_recall_id`
    null unless there is something to supersede — and if there is, the same
    supersession rule that governs cascade-created recalls applies here: every
    other recall of the same `patient_id` and `protocol` whose `status` is
    `SCHEDULED_DUE` or `OVERDUE` becomes `SUPERSEDED`, the newest of them is
    recorded as this row's `predecessor_recall_id`, and the patient's
    `outstanding_recall_count` is recomputed with the patient's `version`
    incremented by 1."
    PRD §3.9: "`BLADDER_CANCER` runs on a tighter cadence: 12 months at `LOW`, 6
    at `INTERMEDIATE`, 3 at `HIGH`."
    PRD §3.1: "`outstanding_recall_count`, the number of that patient's
    surveillance recalls whose `status` is either `SCHEDULED_DUE` or `OVERDUE`"

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_counters
    """
    stage = _build_counter_stage(api)
    roster = stage.roster

    stone = _open_recall(api, stage, PROTOCOL_STONE, TIER_LOW, STONE_ANCHOR_DATE)
    bladder = _open_recall(
        api, stage, PROTOCOL_BLADDER_CANCER, TIER_LOW, BLADDER_ANCHOR_DATE
    )
    validate_success(
        api.close_surveillance_recall(
            stone["id"],
            f.recall_close_payload(closed_reason="PATIENT_DECLINED"),
            roster.urologist_headers,
        )
    )
    before_supersede = fx.read_patient(api, roster, stage.patient["id"])
    assert_fields(before_supersede, outstanding_recall_count=1)

    # Restaging the bladder protocol at HIGH risk supersedes the open LOW row:
    # one row enters the counted set exactly as another leaves it.
    restaged = _open_recall(
        api,
        stage,
        PROTOCOL_BLADDER_CANCER,
        TIER_HIGH,
        BLADDER_RESTAGE_ANCHOR_DATE,
    )
    assert_fields(
        restaged,
        protocol=PROTOCOL_BLADDER_CANCER,
        risk_tier=TIER_HIGH,
        interval_months=3,
        due_on="2026-12-14",
        status=RECALL_SCHEDULED_DUE,
        due_basis=BASIS_PROTOCOL_ANCHORED,
        lapse_days=0,
        predecessor_recall_id=bladder["id"],
    )
    assert_fields(fx.read_recall(api, roster, bladder["id"]), status=RECALL_SUPERSEDED)

    after_supersede = fx.read_patient(api, roster, stage.patient["id"])
    assert after_supersede["outstanding_recall_count"] == 1, (
        "a supersede admits one row to the open set as it removes another, so "
        "the recomputed counter must stay at 1, got "
        f"{after_supersede['outstanding_recall_count']}"
    )
    # Flat counter, advanced version: the row was recomputed, not left alone.
    assert_version_advanced(before_supersede, after_supersede)

    rows, meta = validate_paginated(
        api.list_surveillance_recalls(roster.admin_headers, patient_id=stage.patient["id"])
    )
    assert meta["total_count"] == 3, (
        f"the patient must hold three recall rows, got {meta['total_count']}"
    )
    statuses = sorted(row["status"] for row in rows)
    assert statuses == sorted(
        [RECALL_CLOSED, RECALL_SCHEDULED_DUE, RECALL_SUPERSEDED]
    ), (
        "the three rows must be exactly one closed, one open and one "
        f"superseded, got {statuses}"
    )


def test_room_occupied_block_count_reconciles_downward_as_blocks_are_released(api):
    """PRD §3.1: "Each room also exposes `occupied_block_count`, a derived count
    of the cases naming that room whose `schedule_status` is `SCHEDULED`,
    `IN_ROOM` or `COMPLETED`; it initialises to 0."
    PRD §3.3: "Finally, when the cancelled case had been `SCHEDULED` rather than
    merely `DRAFT`, the room's `version` is incremented by 1 and its
    `occupied_block_count` recomputed, because an occupancy block has just been
    released; a cancelled draft touches no room."
    PRD §3.3: "Antibiotic orders in `ORDERED` are likewise cancelled, the room's
    `version` is incremented by 1 and its `occupied_block_count` recomputed, and
    the case's `blocking_reason_codes` collapses to the empty array."

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_counters
    """
    stage = _build_counter_stage(api)
    roster = stage.roster

    room_v0 = fx.read_room(api, roster, stage.room["id"])
    assert_fields(room_v0, occupied_block_count=0)

    fx.commit_case(api, roster, stage.case_1, stage.room)
    room_after_first = fx.read_room(api, roster, stage.room["id"])
    assert_fields(room_after_first, occupied_block_count=1)
    assert_version_advanced(room_v0, room_after_first)

    fx.commit_case(api, roster, stage.case_2, stage.room)
    room_after_second = fx.read_room(api, roster, stage.room["id"])
    assert_fields(room_after_second, occupied_block_count=2)
    assert_version_advanced(room_after_first, room_after_second)

    # Cancelling a case that had reached SCHEDULED releases its block.
    validate_success(
        api.cancel_case(
            stage.case_1["id"], f.cancel_payload(), roster.scheduler_headers
        )
    )
    room_after_cancel = fx.read_room(api, roster, stage.room["id"])
    assert room_after_cancel["occupied_block_count"] == 1, (
        "cancelling one of two committed cases must recompute the room's block "
        f"count down to 1, got {room_after_cancel['occupied_block_count']}"
    )
    assert_version_advanced(room_after_second, room_after_cancel)

    # The no-show grace is fifteen minutes, so the clock has to pass 11:15.
    fx.set_clock(api, COUNTER_NO_SHOW_CLOCK, roster.admin_headers)
    validate_success(api.no_show_case(stage.case_2["id"], {}, roster.scheduler_headers))
    room_end = fx.read_room(api, roster, stage.room["id"])
    assert room_end["occupied_block_count"] == 0, (
        "with both cases off the calendar the room's block count must reconcile "
        f"back to 0, got {room_end['occupied_block_count']}"
    )
    assert_version_advanced(room_after_cancel, room_end)
    assert room_end["version"] == room_v0["version"] + 4, (
        "two commits, a cancellation and a no-show each rewrite the room's "
        f"occupancy ledger once: expected version {room_v0['version'] + 4}, got "
        f"{room_end['version']}"
    )
