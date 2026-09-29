"""
Cross-entity state dependencies of the Urology Procedure Suite API.

Two mutations in this contract are legal or illegal purely because of state
held on a *different* row than the one being written. Checking a patient into
the room is gated on the assigned scope's sterile-processing record, and
committing a case to the room calendar is gated on date state carried by the
procedure room and by the operating urologist.

Both families are exercised here through the API alone: the scope's
high-level-disinfection stamp is the only unmet condition in the first family,
and the room's and the provider's accreditation expiries are the only unmet
conditions in the second, so nothing about the case itself explains the
refusal.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PROVIDER_ACCREDITATION_LAPSED,
    ERR_ROOM_ACCREDITATION_LAPSED,
    ERR_SCOPE_NOT_READY,
)
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_readiness,
)
from test_helpers.constants import (
    CASE_DRAFT,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CLEARANCE_CLEARED,
    GATE_SCOPE_NOT_READY,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    ROOM_TYPE_URODYNAMICS_LAB,
    SCOPE_IN_USE,
    TYPE_CYSTOSCOPY,
    TYPE_URODYNAMICS,
)

# The instant the front desk attempts the check-in: exactly the case's
# scheduled start, so the thirty-minute early-arrival allowance is satisfied.
CHECK_IN_CLOCK = "2026-09-14T14:00:00Z"
CHECK_IN_INSTANT = "2026-09-14T14:00:00.000Z"


def _cystoscopy_stage(api, roster):
    """
    A cystoscopy case in an open cystoscopy suite, cleared for its patient and
    sitting on the calendar at the logical clock instant. The procedure type
    requires a scope and nothing else, so the scope is the only cross-entity
    dependency left in play.
    """
    patient = fx.create_patient(api, roster.urologist, full_name="Noor Fadel", egfr=60)
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
        consignment_required=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, CHECK_IN_CLOCK, roster.admin_headers)
    return {"patient": patient, "room": room, "procedure_type": procedure_type}


def _case_awaiting_scope(api, roster, stage, scope):
    """
    Draft the case, hold the given scope for it, commit it to the calendar and
    grant clearance — so every check-in gate other than the scope gate passes.
    """
    case = fx.draft_case(
        api,
        roster,
        stage["patient"],
        stage["procedure_type"],
        stage["room"],
        CHECK_IN_CLOCK,
    )
    fx.assign_scope(api, roster, case["id"], scope)
    fx.commit_case(api, roster, case, stage["room"])
    cleared = fx.clear_case(api, roster, case["id"])
    assert_fields(
        cleared, schedule_status=CASE_SCHEDULED, clearance_status=CLEARANCE_CLEARED
    )
    return case


def test_check_in_refused_when_assigned_scope_has_no_disinfection_stamp(api, roster):
    """PRD §2.8: "When the case's procedure type has `requires_scope` true, the
    case has a `scope_asset_id` whose scope has `status` `IN_USE`, a non-null
    `hld_pass_at`, and a null `reprocess_due_at`."
    PRD §2.8: "Otherwise `ERR_SCOPE_NOT_READY`, HTTP 422. Applies to check-in
    only."
    PRD §3.1: "Everything else about a new scope is fixed by the service:
    `status` starts at `AVAILABLE`, `cycles_since_leak_test` at 0,
    `leak_test_required` at `false`, and both `hld_pass_at` and
    `reprocess_due_at` at null."

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_blocked_by_scope_state
    """
    stage = _cystoscopy_stage(api, roster)
    scope = fx.create_scope(
        api,
        roster.tech,
        serial_number="SCP-9002",
        scope_model="Olympus CYF-VH",
        channel_count=1,
    )
    case = _case_awaiting_scope(api, roster, stage, scope)

    response = api.check_in_case(case["id"], {}, roster.nurse_headers)
    validate_error(response, ERR_SCOPE_NOT_READY)

    still_scheduled = fx.read_case(api, roster, case["id"])
    assert_fields(still_scheduled, schedule_status=CASE_SCHEDULED)
    assert still_scheduled["checked_in_at"] is None, (
        "a refused check-in must not stamp checked_in_at, got "
        f"{still_scheduled['checked_in_at']!r}"
    )


def test_readiness_names_the_scope_gate_as_the_only_blocker(api, roster):
    """PRD §3.7: "`SCOPE_NOT_READY` — the procedure type's `requires_scope` is
    true and the assigned scope is not ready, meaning any one of:
    `scope_asset_id` is null, the scope's `status` is not `IN_USE`, the scope's
    `hld_pass_at` is null, or the scope's `reprocess_due_at` is non-null."
    PRD §3.7: "It reports the `case_id`, both dimensions as `schedule_status`
    and `clearance_status`, the ordered `blocking_reason_codes`, the convenience
    field `first_blocking_reason_code` — the first element of that array, or
    null when the array is empty — and `check_in_allowed`, a boolean that is
    true exactly when the case's `schedule_status` is `SCHEDULED` and the gate
    array is empty."

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_blocked_by_scope_state
    """
    stage = _cystoscopy_stage(api, roster)
    scope = fx.create_scope(
        api,
        roster.tech,
        serial_number="SCP-9002",
        scope_model="Olympus CYF-VH",
        channel_count=1,
    )
    case = _case_awaiting_scope(api, roster, stage, scope)

    readiness = validate_success(
        api.get_case_readiness(case["id"], roster.nurse_headers)
    )
    assert_readiness(readiness, [GATE_SCOPE_NOT_READY], check_in_allowed=False)
    assert_fields(
        readiness,
        case_id=case["id"],
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_CLEARED,
        first_blocking_reason_code=GATE_SCOPE_NOT_READY,
    )


def test_held_scope_satisfies_every_status_level_condition_yet_still_blocks(api, roster):
    """PRD §3.5: "On success the case's `scope_asset_id` is set, the scope moves
    from `AVAILABLE` to `IN_USE`, the scope's `version` increments by 1, and the
    case's readiness gates are recomputed."
    PRD §3.1: "Everything else about a new scope is fixed by the service:
    `status` starts at `AVAILABLE`, `cycles_since_leak_test` at 0,
    `leak_test_required` at `false`, and both `hld_pass_at` and
    `reprocess_due_at` at null."
    PRD §2.8: "When the case's procedure type has `requires_scope` true, the
    case has a `scope_asset_id` whose scope has `status` `IN_USE`, a non-null
    `hld_pass_at`, and a null `reprocess_due_at`."

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_blocked_by_scope_state
    """
    stage = _cystoscopy_stage(api, roster)
    scope = fx.create_scope(
        api,
        roster.tech,
        serial_number="SCP-9002",
        scope_model="Olympus CYF-VH",
        channel_count=1,
    )
    case = _case_awaiting_scope(api, roster, stage, scope)

    held = validate_success(api.get_scope_asset(scope["id"], roster.tech_headers))
    assert_fields(
        held,
        status=SCOPE_IN_USE,
        leak_test_required=False,
        cycles_since_leak_test=0,
    )
    assert_null_fields(held, "hld_pass_at", "reprocess_due_at")

    # Only the disinfection stamp is missing, and that alone stops the check-in.
    validate_error(
        api.check_in_case(case["id"], {}, roster.nurse_headers), ERR_SCOPE_NOT_READY
    )


def test_check_in_succeeds_once_the_scope_carries_a_disinfection_stamp(api, roster):
    """PRD §3.5: "Commissioning sets `hld_pass_at` to the logical clock instant,
    leaves `status` at `AVAILABLE` and `reprocess_due_at` at null, and increments
    the scope's `version` by 1."
    PRD §3.7: "Bringing the patient into the room is a `ProcedureNurse`'s
    exclusive act and takes no payload; it advances `schedule_status` from
    `SCHEDULED` to `IN_ROOM`."
    PRD §3.7: "On success the case's `checked_in_at` records the logical clock
    instant and `blocking_reason_codes` collapses to the empty array."

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_blocked_by_scope_state
    """
    stage = _cystoscopy_stage(api, roster)
    # The factory attestation is recorded while the scope is still on the shelf,
    # so its disinfection stamp is the logical clock instant of the commissioning.
    scope = fx.build_ready_scope(
        api,
        roster,
        serial_number="SCP-9002",
        scope_model="Olympus CYF-VH",
        channel_count=1,
    )
    assert_fields(scope, hld_pass_at=CHECK_IN_INSTANT)
    assert_null_fields(scope, "reprocess_due_at")

    case = _case_awaiting_scope(api, roster, stage, scope)

    checked_in = validate_success(
        api.check_in_case(case["id"], {}, roster.nurse_headers)
    )
    assert_fields(
        checked_in,
        schedule_status=CASE_IN_ROOM,
        checked_in_at=CHECK_IN_INSTANT,
        blocking_reason_codes=[],
    )

    # Nothing about the case changed between the two attempts — only the scope's
    # disinfection record did.
    held = validate_success(api.get_scope_asset(scope["id"], roster.tech_headers))
    assert_fields(held, status=SCOPE_IN_USE, hld_pass_at=CHECK_IN_INSTANT)


# ─── Accreditation state held by the room and by the operating urologist ─────

# The clock sits fourteen days past both accreditation expiries below.
ACCREDITATION_CLOCK = "2026-09-14T07:00:00Z"
LAPSED_ON = "2026-08-31"
RENEWED_ROOM_ON = "2027-01-31"
RENEWED_PROVIDER_ON = "2027-03-31"


def _accreditation_stage(api, roster):
    """
    A urodynamics lab whose accreditation lapsed a fortnight ago and an
    operating urologist whose ultrasound accreditation lapsed on the same day,
    plus a cystoscopy suite that carries no accreditation fields at all as the
    control. One drafted case sits in each room.
    """
    urologist = fx.create_provider(
        api,
        ROLE_TYPE_UROLOGIST,
        full_name="Dr Ada Nour",
        ultrasound_accreditation_expires_on=LAPSED_ON,
    )
    patient = fx.create_patient(api, urologist, full_name="Priya Anand", egfr=60)
    uds_room = fx.create_room(
        api,
        ROOM_TYPE_URODYNAMICS_LAB,
        name="Uro Lab",
        turnover_minutes=8,
        accreditation_body="AIUM",
        accreditation_expires_on=LAPSED_ON,
    )
    cysto_room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    uds_type = fx.create_procedure_type(
        api,
        TYPE_URODYNAMICS,
        base_minutes=45,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_URODYNAMICS_LAB,
        requires_scope=False,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, ACCREDITATION_CLOCK, roster.admin_headers)
    uds_case = fx.draft_case(
        api,
        roster,
        patient,
        uds_type,
        uds_room,
        "2026-09-16T10:00:00Z",
        provider=urologist,
    )
    cysto_case = fx.draft_case(
        api,
        roster,
        patient,
        cysto_type,
        cysto_room,
        "2026-09-17T14:00:00Z",
        provider=urologist,
    )
    return {
        "urologist": urologist,
        "uds_room": uds_room,
        "cysto_room": cysto_room,
        "uds_case": uds_case,
        "cysto_case": cysto_case,
    }


def _renew_room(api, roster, room_id):
    """Renew a room's imaging accreditation and report its new version."""
    return validate_success(
        api.update_procedure_room(
            room_id,
            f.procedure_room_update_payload(accreditation_expires_on=RENEWED_ROOM_ON),
            roster.admin_headers,
        )
    )


def _renew_provider(api, roster, provider_id):
    """Renew a urologist's ultrasound accreditation."""
    return validate_success(
        api.update_provider(
            provider_id,
            f.provider_update_payload(
                ultrasound_accreditation_expires_on=RENEWED_PROVIDER_ON
            ),
            roster.admin_headers,
        )
    )


def test_commit_reports_the_room_accreditation_before_the_provider_one(api, roster):
    """PRD §2.8: "When the case's room is of type `IMAGING_BAY` or
    `URODYNAMICS_LAB`, that room's `accreditation_expires_on` is non-null and
    falls on or after the logical clock date. Otherwise
    `ERR_ROOM_ACCREDITATION_LAPSED`, HTTP 422. Applies to two operations:
    check-in and case scheduling."
    PRD §2.8: "When it does, the response reports exactly one error, and which
    one is fully determined: the service evaluates its checks in a **total
    priority order** and returns the error belonging to the lowest-numbered rule
    that fails."
    PRD §2.8: "This ladder is normative and the numbers below are the ordering
    keys — they are not exposed in any response, but the relative order they
    impose is observable on every multiply-invalid request."

    Design: Difficulty/cross_entity_state_dependency/ce_schedule_blocked_by_room_accreditation
    """
    stage = _accreditation_stage(api, roster)
    uds_room = stage["uds_room"]

    response = api.schedule_case(
        stage["uds_case"]["id"],
        f.schedule_payload(uds_room["version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_ROOM_ACCREDITATION_LAPSED)


def test_refused_commit_leaves_the_case_drafted_and_the_room_version_alone(api, roster):
    """PRD §3.3: "A successful commit recomputes `procedure_minutes`,
    `turnover_minutes`, `scheduled_end_at` and `block_end_at` from scratch,
    increments the room's `version` by 1 because the room's occupancy ledger has
    changed, recomputes that room's `occupied_block_count`, and recomputes the
    case's readiness gates."
    PRD §2.4: "Cascaded side effects are described in full in §3; the rule here
    is that any row whose stored fields change as a result of a request has its
    `version` incremented once for that request and its `updated_at` refreshed."
    PRD §2.8: "When the case's room is of type `IMAGING_BAY` or
    `URODYNAMICS_LAB`, that room's `accreditation_expires_on` is non-null and
    falls on or after the logical clock date. Otherwise
    `ERR_ROOM_ACCREDITATION_LAPSED`, HTTP 422. Applies to two operations:
    check-in and case scheduling."

    Design: Difficulty/cross_entity_state_dependency/ce_schedule_blocked_by_room_accreditation
    """
    stage = _accreditation_stage(api, roster)
    uds_room = stage["uds_room"]

    validate_error(
        api.schedule_case(
            stage["uds_case"]["id"],
            f.schedule_payload(uds_room["version"]),
            roster.scheduler_headers,
        ),
        ERR_ROOM_ACCREDITATION_LAPSED,
    )

    still_drafted = fx.read_case(api, roster, stage["uds_case"]["id"])
    assert_fields(still_drafted, schedule_status=CASE_DRAFT)

    untouched_room = fx.read_room(api, roster, uds_room["id"])
    assert_fields(untouched_room, version=uds_room["version"])
    assert untouched_room["occupied_block_count"] == 0, (
        "a refused commit must take no occupancy block, got "
        f"{untouched_room['occupied_block_count']}"
    )


def test_provider_accreditation_surfaces_only_after_the_room_is_renewed(api, roster):
    """PRD §2.8: "When the case's room is of type `IMAGING_BAY` or
    `URODYNAMICS_LAB`, the primary provider's
    `ultrasound_accreditation_expires_on` is non-null and falls on or after the
    logical clock date. Otherwise `ERR_PROVIDER_ACCREDITATION_LAPSED`, HTTP 422.
    Applies to two operations: check-in and case scheduling."
    PRD §3.1: "Administrative edits may change `room_status`,
    `turnover_minutes`, `accreditation_body` and `accreditation_expires_on`, each
    optional; any such edit increments the room's `version` — which is what
    invalidates a client's held `expected_room_version` — and, like the patient
    edit, does not retune the turnover already baked into cases sitting on that
    room's calendar."

    Design: Difficulty/cross_entity_state_dependency/ce_schedule_blocked_by_room_accreditation
    """
    stage = _accreditation_stage(api, roster)
    uds_room = stage["uds_room"]

    renewed_room = _renew_room(api, roster, uds_room["id"])
    assert_fields(
        renewed_room,
        accreditation_expires_on=RENEWED_ROOM_ON,
        version=uds_room["version"] + 1,
    )

    response = api.schedule_case(
        stage["uds_case"]["id"],
        f.schedule_payload(renewed_room["version"]),
        roster.scheduler_headers,
    )
    validate_error(response, ERR_PROVIDER_ACCREDITATION_LAPSED)

    still_drafted = fx.read_case(api, roster, stage["uds_case"]["id"])
    assert_fields(still_drafted, schedule_status=CASE_DRAFT)


def test_commit_stands_once_both_accreditations_are_renewed(api, roster):
    """PRD §3.3: "Two accreditation conditions also bite at commit time and not
    only at check-in: for a case whose room is an `IMAGING_BAY` or a
    `URODYNAMICS_LAB`, the room's `accreditation_expires_on` must be non-null and
    on or after the logical clock date (`ERR_ROOM_ACCREDITATION_LAPSED`), and the
    primary provider's `ultrasound_accreditation_expires_on` must likewise be
    non-null and on or after the logical clock date
    (`ERR_PROVIDER_ACCREDITATION_LAPSED`)."
    PRD §3.3: "Committing a case to the calendar is the `Scheduler`'s exclusive
    act, and it advances `schedule_status` from `DRAFT` to `SCHEDULED`."
    PRD §3.2: "That product is then floored at a quarter of an hour: whichever of
    the product and 15 minutes is larger becomes the working figure."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."

    Design: Difficulty/cross_entity_state_dependency/ce_schedule_blocked_by_room_accreditation
    """
    stage = _accreditation_stage(api, roster)

    renewed_room = _renew_room(api, roster, stage["uds_room"]["id"])
    renewed_provider = _renew_provider(api, roster, stage["urologist"]["id"])
    assert_fields(
        renewed_provider, ultrasound_accreditation_expires_on=RENEWED_PROVIDER_ON
    )

    committed = validate_success(
        api.schedule_case(
            stage["uds_case"]["id"],
            f.schedule_payload(renewed_room["version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(
        committed,
        schedule_status=CASE_SCHEDULED,
        procedure_minutes=45,
        turnover_minutes=15,
        scheduled_start_at="2026-09-16T10:00:00.000Z",
        scheduled_end_at="2026-09-16T10:45:00.000Z",
        block_end_at="2026-09-16T11:00:00.000Z",
    )


def test_cysto_suite_commit_ignores_both_accreditation_gates(api, roster):
    """PRD §2.8: "When the case's room is of type `IMAGING_BAY` or
    `URODYNAMICS_LAB`, that room's `accreditation_expires_on` is non-null and
    falls on or after the logical clock date. Otherwise
    `ERR_ROOM_ACCREDITATION_LAPSED`, HTTP 422. Applies to two operations:
    check-in and case scheduling."
    PRD §2.8: "When the case's room is of type `IMAGING_BAY` or
    `URODYNAMICS_LAB`, the primary provider's
    `ultrasound_accreditation_expires_on` is non-null and falls on or after the
    logical clock date. Otherwise `ERR_PROVIDER_ACCREDITATION_LAPSED`, HTTP 422.
    Applies to two operations: check-in and case scheduling."
    PRD §3.1: "Three optional attributes may be supplied: `turnover_minutes`,
    the room's baseline cleaning allowance, which may not be negative and
    defaults to 10 minutes; `accreditation_body`, the accrediting organisation
    for in-office imaging and ultrasound work in that room, defaulting to null;
    and `accreditation_expires_on`, an `YYYY-MM-DD` date defaulting to null,
    where null means the room has never been accredited."

    Design: Difficulty/cross_entity_state_dependency/ce_schedule_blocked_by_room_accreditation
    """
    stage = _accreditation_stage(api, roster)
    cysto_room = stage["cysto_room"]

    # The cystoscopy suite was commissioned with no accreditation fields at all,
    # and the operating urologist's ultrasound accreditation is still lapsed —
    # neither gate applies to a CYSTO_SUITE case.
    assert_null_fields(cysto_room, "accreditation_body", "accreditation_expires_on")
    assert_fields(
        stage["urologist"], ultrasound_accreditation_expires_on=LAPSED_ON
    )

    committed = validate_success(
        api.schedule_case(
            stage["cysto_case"]["id"],
            f.schedule_payload(cysto_room["version"]),
            roster.scheduler_headers,
        )
    )
    assert_fields(
        committed,
        schedule_status=CASE_SCHEDULED,
        procedure_minutes=20,
        turnover_minutes=20,
        scheduled_start_at="2026-09-17T14:00:00.000Z",
        scheduled_end_at="2026-09-17T14:20:00.000Z",
        block_end_at="2026-09-17T14:40:00.000Z",
    )
