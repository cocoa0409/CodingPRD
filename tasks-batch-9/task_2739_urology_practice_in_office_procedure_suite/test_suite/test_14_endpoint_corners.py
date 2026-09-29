"""
Endpoint surface behaviour of the Urology Procedure Suite contract.

Five surfaces are exercised here, each one a different shape of endpoint.

The narrow patient PATCH shows that a partial body writes exactly the clinical
field it names, leaves the identity fields and the derived counters alone, and
still advances the row's version.

The consignment return shows the only path a lot has into ``RETURNED``: handing
the whole untouched lot back zeroes the chargeable value on the final basis,
after which a further single-unit return has nothing left to draw on.

The readiness read shows its all-clear shape — an empty gate list with a null
first blocker and check-in permitted — and then shows that the permission flag,
unlike the gate list, also depends on the case still sitting at ``SCHEDULED``.

The recall sweep shows that a practice with nothing to sweep still gets a
report: the clock echoed back and four counters at zero, with no version bumped
anywhere.

The scope assignment shows one call writing both sides of an association, the
case gaining the scope reference while the scope moves onto a case, and the
association being reachable back from the scope through a filtered case list.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CONSIGNMENT_RETURN_EXCEEDS_AVAILABLE
from test_helpers.assertions import (
    assert_fields,
    assert_lot_counters,
    assert_null_fields,
    assert_readiness,
    assert_version_advanced,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ALLERGY_NONE,
    ALLERGY_SULFA,
    BILLING_FINAL,
    BILLING_STATUS_RETURNED,
    CASE_DRAFT,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    CLEARANCE_CLEARED,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    GATE_SCOPE_NOT_READY,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    SCOPE_AVAILABLE,
    SCOPE_IN_USE,
    TYPE_CYSTOSCOPY,
)
from test_helpers.test_users import make_practice_admin_headers, make_urologist_headers

# ─── The patient chart scenario ─────────────────────────────────────────────
PATIENT_MRN = "MRN-5040"
PATIENT_NAME = "Nadia Ruhl"
PATIENT_DOB = "1977-03-03"
PATIENT_EGFR_ON_FILE = 90
PATIENT_EGFR_REVISED = 44

# ─── The consignment lot scenario ───────────────────────────────────────────
LOT_SKU = "BX-NEEDLE-18G"
LOT_QUANTITY = 10
LOT_UNIT_PRICE_CENTS = 1999
LOT_EXPIRES_ON = "2027-06-30"

# ─── The readiness scenario ─────────────────────────────────────────────────
READINESS_CLOCK = "2026-09-14T09:00:00Z"
READINESS_START_AT = "2026-09-14T09:00:00.000Z"

# ─── The recall sweep scenario ──────────────────────────────────────────────
SWEEP_CLOCK = "2026-09-14T07:00:00Z"
SWEPT_AT = "2026-09-14T07:00:00.000Z"

# ─── The scope assignment scenario ──────────────────────────────────────────
SCOPE_CLOCK = "2026-09-14T07:00:00Z"
SCOPE_CASE_START_AT = "2026-09-14T14:00:00.000Z"
SCOPE_SERIAL = "SN-9001"


def _build_patient_on_file(api) -> Dict[str, Any]:
    """
    One urologist and the patient they carry, registered with a renal function
    well above the adjustment threshold, no anticoagulation and no allergy
    recorded, so every clinical field starts at its registration default.
    """
    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    patient = fx.create_patient(
        api,
        urologist,
        mrn=PATIENT_MRN,
        full_name=PATIENT_NAME,
        date_of_birth=PATIENT_DOB,
        egfr=PATIENT_EGFR_ON_FILE,
    )
    return {
        "urologist": urologist,
        "urologist_headers": make_urologist_headers(urologist["id"]),
        "patient": patient,
    }


def _build_untouched_lot(api) -> Dict[str, Any]:
    """A freshly received lot of ten biopsy needles: nothing reserved, spent or
    handed back, so the whole quantity is still available."""
    return fx.create_lot(
        api,
        supplier_name="Meridian Devices",
        sku=LOT_SKU,
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        quantity_received=LOT_QUANTITY,
        unit_price_cents=LOT_UNIT_PRICE_CENTS,
        lot_expires_on=LOT_EXPIRES_ON,
    )


def _build_cleared_cystoscopy(api) -> Dict[str, Any]:
    """
    A cystoscopy on the calendar for the current clock instant, already cleared,
    in a cystoscopy suite that carries no accreditation obligation, of a type
    that asks for no scope, no prophylaxis, no specimen, no device and no
    preparation instructions — so not one readiness gate can be open.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5041",
        full_name="Ilse Braun",
        date_of_birth="1961-01-21",
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
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )
    fx.set_clock(api, READINESS_CLOCK)

    case = fx.draft_case(api, roster, patient, procedure_type, room, READINESS_START_AT)
    case = fx.commit_case(api, roster, case, room)
    case = fx.clear_case(api, roster, case["id"])
    return {"roster": roster, "patient": patient, "room": room, "case": case}


def _build_scope_and_draft_case(api) -> Dict[str, Any]:
    """
    A draft cystoscopy of a type that requires a scope, plus one freshly
    registered scope that has never been reprocessed or commissioned — so it is
    ``AVAILABLE`` and assignable, yet its disinfection stamp is still null.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api,
        roster.urologist,
        mrn="MRN-5043",
        full_name="Ilse Braun",
        date_of_birth="1961-01-21",
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
        consignment_required=False,
        required_prep_codes=[],
    )
    scope = fx.create_scope(
        api,
        roster.tech,
        serial_number=SCOPE_SERIAL,
        scope_model="FlexCysto 200",
        channel_count=2,
    )
    fx.set_clock(api, SCOPE_CLOCK)
    case = fx.draft_case(
        api, roster, patient, procedure_type, room, SCOPE_CASE_START_AT
    )
    return {
        "roster": roster,
        "patient": patient,
        "room": room,
        "procedure_type": procedure_type,
        "scope": scope,
        "case": case,
    }


# ─── The narrow patient PATCH ───────────────────────────────────────────────
def test_patch_patient_egfr_alone_leaves_the_other_clinical_fields_at_default(api):
    """A body naming only the renal function writes it and nothing else.

    PRD §3.1: "Renal function drifts, anticoagulation is started and stopped,
    and allergies are discovered late; a `PracticeAdmin` or the treating
    `Urologist` may therefore revise `egfr`, `anticoagulant_flag` and
    `antibiotic_allergy_class` on an existing patient."
    PRD §3.1: "Two optional clinical flags complete the record:
    `anticoagulant_flag`, defaulting to `false`, and `antibiotic_allergy_class`,
    defaulting to `NONE` and otherwise one of `FLUOROQUINOLONE`,
    `CEPHALOSPORIN`, `SULFA` or `AMINOGLYCOSIDE`."
    PRD §3.1: "It increments the patient's `version`, which is precisely what
    makes a previously captured `expected_patient_version` stale for the recall
    guard of §2.6."

    Design: Corner/endpoints/ep_standard_crud_patch_patient_clinical_fields
    """
    scenario = _build_patient_on_file(api)
    patient = scenario["patient"]

    updated = validate_success(
        api.update_patient(
            patient["id"],
            f.patient_update_payload(egfr=PATIENT_EGFR_REVISED),
            scenario["urologist_headers"],
        )
    )

    assert_fields(
        updated,
        egfr=PATIENT_EGFR_REVISED,
        anticoagulant_flag=False,
        antibiotic_allergy_class=ALLERGY_NONE,
    )
    assert_version_advanced(patient, updated)


def test_patch_patient_flags_keep_the_revised_egfr_and_the_chart_identity(api):
    """A second partial body writes both flags, keeps the earlier renal figure,
    advances the version again and never disturbs the identity fields or the
    derived counters.

    PRD §3.1: "Renal function drifts, anticoagulation is started and stopped,
    and allergies are discovered late; a `PracticeAdmin` or the treating
    `Urologist` may therefore revise `egfr`, `anticoagulant_flag` and
    `antibiotic_allergy_class` on an existing patient."
    PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."
    PRD §3.1: "It increments the patient's `version`, which is precisely what
    makes a previously captured `expected_patient_version` stale for the recall
    guard of §2.6."

    Design: Corner/endpoints/ep_standard_crud_patch_patient_clinical_fields
    """
    scenario = _build_patient_on_file(api)
    patient = scenario["patient"]

    after_egfr = validate_success(
        api.update_patient(
            patient["id"],
            f.patient_update_payload(egfr=PATIENT_EGFR_REVISED),
            scenario["urologist_headers"],
        )
    )
    after_flags = validate_success(
        api.update_patient(
            patient["id"],
            f.patient_update_payload(
                anticoagulant_flag=True, antibiotic_allergy_class=ALLERGY_SULFA
            ),
            make_practice_admin_headers(),
        )
    )

    assert_fields(
        after_flags,
        anticoagulant_flag=True,
        antibiotic_allergy_class=ALLERGY_SULFA,
        egfr=PATIENT_EGFR_REVISED,
    )
    assert_version_advanced(after_egfr, after_flags)

    read_back = validate_success(
        api.get_patient(patient["id"], scenario["urologist_headers"])
    )
    assert_fields(
        read_back,
        mrn=PATIENT_MRN,
        full_name=PATIENT_NAME,
        date_of_birth=PATIENT_DOB,
        primary_urologist_id=scenario["urologist"]["id"],
        outstanding_recall_count=0,
        open_notification_count=0,
    )
    assert read_back["version"] == after_flags["version"], (
        "a read must report the version the last write returned, got "
        f"{read_back['version']} against {after_flags['version']}"
    )


# ─── Returning a whole untouched consignment lot ─────────────────────────────
def test_full_lot_return_zeroes_the_billing_on_the_final_basis(api):
    """Handing all ten untouched units back moves the whole quantity into the
    returned bucket, bills nothing, and pins the basis at final.

    PRD §3.6: "The return reduces `quantity_available` and increases
    `quantity_returned` by that amount, re-bills the lot on the **final** basis
    with `billing_basis` set to `FINAL`, re-derives `billing_status`, and
    increments the lot's `version` by 1."
    PRD §3.6: "A lot whose entire `quantity_received` has been returned with
    nothing consumed and nothing wasted ends up with `billed_amount_cents` of 0
    and `billing_basis` `FINAL`."
    PRD §3.6: "If `quantity_returned` equals `quantity_received` while both
    `quantity_consumed` and `quantity_wasted` are 0, the lot is `RETURNED`."
    PRD §2.10: "For a consignment lot, `quantity_received` is the conserved
    total: at every observable moment it equals the sum of
    `quantity_available`, `quantity_reserved`, `quantity_consumed`,
    `quantity_returned` and `quantity_wasted`."

    Design: Corner/endpoints/ep_action_endpoint_consignment_full_return
    """
    lot = _build_untouched_lot(api)
    admin_headers = make_practice_admin_headers()

    returned = validate_success(
        api.return_consignment_lot(
            lot["id"], f.lot_return_payload(LOT_QUANTITY), admin_headers
        )
    )

    assert_lot_counters(
        returned, available=0, reserved=0, consumed=0, returned=LOT_QUANTITY, wasted=0
    )
    assert_fields(
        returned,
        billing_status=BILLING_STATUS_RETURNED,
        billed_amount_cents=0,
        billing_basis=BILLING_FINAL,
    )
    assert_version_advanced(lot, returned)


def test_return_beyond_available_stock_is_refused_and_changes_nothing(api):
    """With every unit already back at the supplier there is nothing left to
    draw on, so a further single-unit return is refused and the lot stands
    exactly as the first return left it.

    PRD §3.6: "A `PracticeAdmin` returns units by naming a `quantity`, which may
    be no greater than the lot's `quantity_available` — reserved and consumed
    units cannot be returned, and an over-large request is refused with
    `ERR_CONSIGNMENT_RETURN_EXCEEDS_AVAILABLE`."
    PRD §2.10: "For a consignment lot, `quantity_received` is the conserved
    total: at every observable moment it equals the sum of
    `quantity_available`, `quantity_reserved`, `quantity_consumed`,
    `quantity_returned` and `quantity_wasted`."

    Design: Corner/endpoints/ep_action_endpoint_consignment_full_return
    """
    lot = _build_untouched_lot(api)
    admin_headers = make_practice_admin_headers()

    after_return = validate_success(
        api.return_consignment_lot(
            lot["id"], f.lot_return_payload(LOT_QUANTITY), admin_headers
        )
    )

    validate_error(
        api.return_consignment_lot(lot["id"], f.lot_return_payload(1), admin_headers),
        ERR_CONSIGNMENT_RETURN_EXCEEDS_AVAILABLE,
    )

    read_back = validate_success(api.get_consignment_lot(lot["id"], admin_headers))
    assert_lot_counters(
        read_back, available=0, reserved=0, consumed=0, returned=LOT_QUANTITY, wasted=0
    )
    assert_version_unchanged(after_return, read_back)


# ─── The readiness computed read ─────────────────────────────────────────────
def test_readiness_all_clear_reports_no_gates_and_permits_check_in(api):
    """With every gate satisfied the read carries an empty gate list, a null
    first blocker and permission to bring the patient in.

    PRD §3.7: "A dedicated computed read exposes the whole picture for one case
    and is open to all seven roles."
    PRD §3.7: "It reports the `case_id`, both dimensions as `schedule_status`
    and `clearance_status`, the ordered `blocking_reason_codes`, the convenience
    field `first_blocking_reason_code` — the first element of that array, or
    null when the array is empty — and `check_in_allowed`, a boolean that is
    true exactly when the case's `schedule_status` is `SCHEDULED` and the gate
    array is empty."
    PRD §3.4: "When `required_prep_codes` is the empty array the requirement is
    satisfied vacuously, which is the only way a case reaches `CLEARED` straight
    out of `PENDING_PREP` with no acknowledgements recorded."

    Design: Corner/endpoints/ep_computed_read_readiness_clear_then_in_room
    """
    scenario = _build_cleared_cystoscopy(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]

    readiness = validate_success(
        api.get_case_readiness(case_id, roster.urologist_headers)
    )

    assert_fields(
        readiness,
        case_id=case_id,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_CLEARED,
    )
    assert_readiness(readiness, [], check_in_allowed=True)


def test_readiness_after_check_in_keeps_no_gates_but_refuses_permission(api):
    """Once the patient is in the room the gate list stays empty, yet the
    permission flag flips to false because the case is no longer scheduled — and
    the read itself mutates nothing.

    PRD §3.7: "It reports the `case_id`, both dimensions as `schedule_status`
    and `clearance_status`, the ordered `blocking_reason_codes`, the convenience
    field `first_blocking_reason_code` — the first element of that array, or
    null when the array is empty — and `check_in_allowed`, a boolean that is
    true exactly when the case's `schedule_status` is `SCHEDULED` and the gate
    array is empty."
    PRD §3.7: "They describe a *pending* check-in only, so a case whose
    `schedule_status` is `IN_ROOM`, `COMPLETED`, `CANCELLED` or `NO_SHOW`
    carries the empty array regardless of anything else about it."
    PRD §3.7: "Bringing the patient into the room is a `ProcedureNurse`'s
    exclusive act and takes no payload; it advances `schedule_status` from
    `SCHEDULED` to `IN_ROOM`."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/ep_computed_read_readiness_clear_then_in_room
    """
    scenario = _build_cleared_cystoscopy(api)
    roster = scenario["roster"]
    case_id = scenario["case"]["id"]

    checked_in = validate_success(
        api.check_in_case(case_id, {}, roster.nurse_headers)
    )
    assert_fields(checked_in, schedule_status=CASE_IN_ROOM)

    readiness = validate_success(api.get_case_readiness(case_id, roster.admin_headers))
    assert_fields(readiness, schedule_status=CASE_IN_ROOM)
    assert_readiness(readiness, [], check_in_allowed=False)

    after_read = validate_success(
        api.get_procedure_case(case_id, roster.admin_headers)
    )
    assert_version_unchanged(checked_in, after_read)


# ─── The recall sweep with nothing to do ─────────────────────────────────────
def test_no_op_recall_sweep_reports_the_clock_and_four_zero_counters(api):
    """A practice with no recall, no specimen and no case still gets a report
    rather than a refusal.

    PRD §3.9: "A `PracticeAdmin` or a `Urologist` may trigger it; it takes no
    payload."
    PRD §3.9: "Its response carries `swept_at` holding the logical clock instant
    of the sweep, `recomputed_recall_count` for the number of recalls step 1
    recomputed, `overdue_recall_count` for the number step 2 moved into
    `OVERDUE`, `restored_recall_count` for the number step 2 pulled back to
    `SCHEDULED_DUE`, and `escalated_specimen_count` for the number of
    notifications step 3 escalated."
    PRD §3.9: "A sweep that finds nothing to do is not an error; it returns all
    four counters at zero."

    Design: Corner/endpoints/ep_conditional_action_recall_sweep_no_op
    """
    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    fx.create_patient(
        api,
        urologist,
        mrn="MRN-5042",
        full_name="Elin Kaas",
        date_of_birth="1970-11-02",
        egfr=70,
    )
    fx.set_clock(api, SWEEP_CLOCK)

    report = validate_success(
        api.run_recall_sweep({}, make_urologist_headers(urologist["id"]))
    )

    assert_fields(
        report,
        swept_at=SWEPT_AT,
        recomputed_recall_count=0,
        overdue_recall_count=0,
        restored_recall_count=0,
        escalated_specimen_count=0,
    )


def test_no_op_recall_sweep_bumps_no_patient_version(api):
    """The sweep touched no patient, so the chart keeps the version and the
    counters it was registered with.

    PRD §3.9: "Across all three steps the sweep recomputes
    `outstanding_recall_count` and `open_notification_count` for every patient
    it touched."
    PRD §3.1: "Each patient also exposes two derived counters that the service
    maintains and the client never writes: `outstanding_recall_count`, the
    number of that patient's surveillance recalls whose `status` is either
    `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of
    specimens belonging to that patient's cases whose `notification_status` is
    `PENDING`, `ATTEMPTED` or `ESCALATED`."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/ep_conditional_action_recall_sweep_no_op
    """
    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    urologist_headers = make_urologist_headers(urologist["id"])
    patient = fx.create_patient(
        api,
        urologist,
        mrn="MRN-5042",
        full_name="Elin Kaas",
        date_of_birth="1970-11-02",
        egfr=70,
    )
    fx.set_clock(api, SWEEP_CLOCK)

    validate_success(api.run_recall_sweep({}, urologist_headers))

    read_back = validate_success(api.get_patient(patient["id"], urologist_headers))
    assert_fields(
        read_back,
        outstanding_recall_count=0,
        open_notification_count=0,
        version=patient["version"],
    )


# ─── Assigning a scope writes both sides of the association ──────────────────
def test_scope_assignment_writes_the_case_reference_and_moves_the_scope(api):
    """One call sets the case's scope reference and takes the scope out of the
    shelf onto that case, advancing the scope's version.

    PRD §3.5: "Assigning a scope to a case is a `ProcedureNurse`'s exclusive
    act, and the payload names the `scope_asset_id` together with
    `expected_scope_asset_version`."
    PRD §3.5: "On success the case's `scope_asset_id` is set, the scope moves
    from `AVAILABLE` to `IN_USE`, the scope's `version` increments by 1, and the
    case's readiness gates are recomputed."
    PRD §3.1: "Everything else about a new scope is fixed by the service:
    `status` starts at `AVAILABLE`, `cycles_since_leak_test` at 0,
    `leak_test_required` at `false`, and both `hld_pass_at` and
    `reprocess_due_at` at null."

    Design: Corner/endpoints/ep_cross_reference_link_scope_assignment
    """
    scenario = _build_scope_and_draft_case(api)
    roster = scenario["roster"]
    scope = scenario["scope"]
    case_id = scenario["case"]["id"]

    assert_fields(scope, status=SCOPE_AVAILABLE, cycles_since_leak_test=0)

    assigned = validate_success(
        api.assign_scope(
            case_id,
            f.scope_assignment_payload(scope["id"], scope["version"]),
            roster.nurse_headers,
        )
    )
    assert_fields(
        assigned, scope_asset_id=scope["id"], schedule_status=CASE_DRAFT
    )

    scope_after = validate_success(
        api.get_scope_asset(scope["id"], roster.tech_headers)
    )
    assert_fields(scope_after, status=SCOPE_IN_USE, cycles_since_leak_test=0)
    assert_null_fields(scope_after, "reprocess_due_at", "hld_pass_at")
    assert_version_advanced(scope, scope_after)


def test_scope_assignment_does_not_clear_the_scope_readiness_gate(api):
    """Holding a scope is not the same as having a reprocessed one: the
    disinfection stamp is still null, so the scope gate stays open.

    PRD §3.7: "`SCOPE_NOT_READY` — the procedure type's `requires_scope` is true
    and the assigned scope is not ready, meaning any one of: `scope_asset_id` is
    null, the scope's `status` is not `IN_USE`, the scope's `hld_pass_at` is
    null, or the scope's `reprocess_due_at` is non-null."
    PRD §3.1: "Its `hld_pass_at` is null, so the scope-readiness gate at
    priority 52 fails at check-in."
    PRD §3.5: "On success the case's `scope_asset_id` is set, the scope moves
    from `AVAILABLE` to `IN_USE`, the scope's `version` increments by 1, and the
    case's readiness gates are recomputed."

    Design: Corner/endpoints/ep_cross_reference_link_scope_assignment
    """
    scenario = _build_scope_and_draft_case(api)
    roster = scenario["roster"]
    scope = scenario["scope"]
    case_id = scenario["case"]["id"]

    assigned = validate_success(
        api.assign_scope(
            case_id,
            f.scope_assignment_payload(scope["id"], scope["version"]),
            roster.nurse_headers,
        )
    )

    assert GATE_SCOPE_NOT_READY in assigned["blocking_reason_codes"], (
        "a scope whose high-level-disinfection stamp is null must keep the "
        f"scope gate open, got {assigned['blocking_reason_codes']}"
    )


def test_assigned_case_is_reachable_from_the_scope_through_the_case_filter(api):
    """The association reads back from the scope's side: filtering the case
    collection on the scope returns exactly the case that holds it.

    PRD §2.9: "Parent-child relationships are carried by reference fields on the
    child row, and every such reference is reverse-reachable through a filter on
    the parent's collection read."
    PRD §2.11: "Procedure cases may be filtered by `patient_id`,
    `procedure_type_id`, `room_id`, `primary_provider_id`, `scope_asset_id`,
    `device_lot_id`, `schedule_status` and `clearance_status`."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching
    the filter before pagination is applied and `has_more` indicates whether any
    matching row remains beyond the current page."

    Design: Corner/endpoints/ep_cross_reference_link_scope_assignment
    """
    scenario = _build_scope_and_draft_case(api)
    roster = scenario["roster"]
    scope = scenario["scope"]
    case_id = scenario["case"]["id"]

    validate_success(
        api.assign_scope(
            case_id,
            f.scope_assignment_payload(scope["id"], scope["version"]),
            roster.nurse_headers,
        )
    )

    rows, meta = validate_paginated(
        api.list_procedure_cases(roster.tech_headers, scope_asset_id=scope["id"])
    )
    assert meta["total_count"] == 1, (
        "exactly the one case holding the scope must match the filter, got "
        f"total_count {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [case_id], (
        f"the filtered page must hold only the assigned case, got {rows}"
    )
