"""
Role-based access control across the urology suite: who may invoke what.

Four independent controls are exercised here, and the contract keeps them
strictly apart. A caller may fail at the header rung, because no acting user or
no capacity was declared at all. A caller may fail identity resolution, because
the identifier in the header does not resolve to a roster row of the claimed
capacity — or resolves to one whose credential standing has been withdrawn. A
caller may fail the per-endpoint allowlist, because the operation belongs to
another role entirely. And a caller who passes all three may still be refused
because the actor named in the body is somebody else, or because the second
signature on a sterile-processing stage is their own.

Each control has its own identifier, its own HTTP status and its own position in
the validation ladder, so every test here also checks that the refusal it
provokes is the refusal the ladder pins — a role failure answers 403 even when
the path names a resource that does not exist, and a missing header answers 401
even when the body is malformed too.
"""

from typing import Any, Dict, List, Tuple

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTOR_IDENTITY_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_readiness,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CIPROFLOXACIN,
    ANTIBIOTIC_ADMINISTERED,
    ANTIBIOTIC_ORDERED,
    CASE_COMPLETED,
    CASE_DRAFT,
    CASE_IN_ROOM,
    CASE_SCHEDULED,
    CHAIN_ACCESSIONED,
    CHAIN_COLLECTED,
    CHAIN_RESULTED,
    CLEANUP_HIGH,
    CLEARANCE_CLEARED,
    CLEARANCE_DECISION_CLEAR,
    CLEARANCE_DECISION_WAIVE,
    CLEARANCE_PENDING_PREP,
    CLEARANCE_PREP_ACKNOWLEDGED,
    CONDITION_INTACT,
    CREDENTIAL_SUSPENDED,
    GATE_CHECKIN_TOO_EARLY,
    GATE_CLEARANCE_NOT_GRANTED,
    LOG_CLOSED,
    LOG_OPEN,
    NOTIFY_ACKNOWLEDGED,
    NOTIFY_OUTCOME_REACHED,
    NOTIFY_PENDING,
    OUTCOME_PASS,
    PROTOCOL_STONE,
    RESULT_BENIGN,
    ROLE_SCHEDULER,
    ROLE_TYPE_PATHOLOGY_LIAISON,
    ROLE_TYPE_PELVIC_COORDINATOR,
    ROLE_TYPE_RN,
    ROLE_TYPE_SCHEDULER,
    ROLE_TYPE_TECH,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    ROUTE_ORAL,
    SPECIMEN_BLADDER_WASHING,
    SPECIMEN_PROSTATE_CORE,
    STAGE_PRECLEAN,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
    CHANNEL_PHONE,
    CHANNEL_PORTAL,
)
from test_helpers.test_users import (
    make_headers,
    make_headers_blank_user_id,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_pathology_liaison_headers,
    make_pelvic_health_coordinator_headers,
    make_practice_admin_headers,
    make_procedure_nurse_headers,
    make_scheduler_headers,
    make_sterile_processing_tech_headers,
    make_urologist_headers,
)

# ─── Fixed instants and identifiers ────────────────────────────────────────
PROBE_CLOCK = "2026-09-14T07:00:00Z"
PROBE_CASE_START = "2026-09-14T09:00:00Z"
PROBE_CLOCK_ATTEMPTED_MOVE = "2026-09-15T07:00:00Z"

LIST_MORNING_CLOCK = "2026-09-14T09:00:00Z"
FIRST_CASE_START = "2026-09-14T09:00:00Z"
SECOND_CASE_START = "2026-09-14T11:00:00Z"
LAB_RECEIVED_AT = "2026-09-14T10:00:00Z"

PREP_CODE_NPO_MIDNIGHT = "NPO_MIDNIGHT"

# Syntactically valid identifiers that name no row at all: a role refusal must
# be reported before the service ever looks for them.
ABSENT_SCOPE_ID = "00000000-0000-4000-8000-0000000000c1"
ABSENT_SCOPE_ID_ALT = "00000000-0000-4000-8000-0000000000c2"
ABSENT_SPECIMEN_ID = "00000000-0000-4000-8000-0000000000c3"
ABSENT_REFERRAL_ID = "00000000-0000-4000-8000-0000000000c4"
ABSENT_LOT_ID = "00000000-0000-4000-8000-0000000000c5"
ABSENT_PROVIDER_ID = "00000000-0000-4000-8000-0000000000d1"


def _room_version(api, room_id: str) -> int:
    """The room's current version, which the calendar commit must carry."""
    room = validate_success(api.get_procedure_room(room_id, make_practice_admin_headers()))
    return room["version"]


# ══════════════════════════════════════════════════════════════════════════
# Exclusive operations: every role's own acts are closed to the other roles
# ══════════════════════════════════════════════════════════════════════════

def _build_cross_role_stage(api) -> Dict[str, Any]:
    """
    One Provider per entity-backed role, a patient, a cystoscopy suite, a
    cystoscopy type with no preparation obligations and one drafted case — the
    smallest stage on which every role's exclusive operations can be probed by
    the wrong role.
    """
    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )
    nurse = fx.create_provider(api, ROLE_TYPE_RN, full_name="Nia Park", npi="1000000003")
    tech = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Omar Diaz", npi="1000000004", hld_certified=True
    )
    pathologist = fx.create_provider(
        api, ROLE_TYPE_PATHOLOGY_LIAISON, full_name="Pat Loew", npi="1000000005"
    )
    coordinator = fx.create_provider(
        api, ROLE_TYPE_PELVIC_COORDINATOR, full_name="Kim Vasa", npi="1000000006"
    )

    scheduler_headers = make_scheduler_headers(scheduler["id"])
    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5070",
                full_name="Rex Halo",
                date_of_birth="1960-02-02",
                egfr=70,
            ),
            scheduler_headers,
        ),
        201,
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
        required_prep_codes=[],
    )
    fx.set_clock(api, PROBE_CLOCK)
    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at=PROBE_CASE_START,
            ),
            scheduler_headers,
        ),
        201,
    )
    # The recall probe carries the patient's real version so that only the role
    # can explain the refusal.
    patient_row = validate_success(
        api.get_patient(patient["id"], make_practice_admin_headers())
    )
    return {
        "urologist": urologist,
        "scheduler": scheduler,
        "nurse": nurse,
        "tech": tech,
        "pathologist": pathologist,
        "coordinator": coordinator,
        "patient": patient_row,
        "room": room,
        "procedure_type": procedure_type,
        "case": case,
        "urologist_headers": make_urologist_headers(urologist["id"]),
        "scheduler_headers": scheduler_headers,
        "nurse_headers": make_procedure_nurse_headers(nurse["id"]),
        "tech_headers": make_sterile_processing_tech_headers(tech["id"]),
        "pathologist_headers": make_pathology_liaison_headers(pathologist["id"]),
        "coordinator_headers": make_pelvic_health_coordinator_headers(coordinator["id"]),
    }


def _cross_role_probes(api, stage: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """
    Thirteen operations, each invoked by a role the endpoint does not list.
    Returns (label, response) pairs in the order the calls were made.
    """
    case_id = stage["case"]["id"]
    nurse_id = stage["nurse"]["id"]
    return [
        # Committing to the calendar belongs to the Scheduler.
        (
            "schedule_by_urologist",
            api.schedule_case(
                case_id,
                f.schedule_payload(stage["room"]["version"]),
                stage["urologist_headers"],
            ),
        ),
        # Bringing the patient into the room belongs to the ProcedureNurse.
        ("check_in_by_urologist", api.check_in_case(case_id, {}, stage["urologist_headers"])),
        # Ordering prophylaxis belongs to the Urologist.
        (
            "antibiotic_order_by_nurse",
            api.create_antibiotic_order(
                f.antibiotic_order_payload(
                    case_id=case_id,
                    ordered_by_provider_id=nurse_id,
                    requested_agent=AGENT_AUTO,
                ),
                stage["nurse_headers"],
            ),
        ),
        # Reprocessing belongs to the SterileProcessingTech.
        (
            "reprocessing_log_by_nurse",
            api.create_reprocessing_log(
                f.reprocessing_log_payload(
                    scope_asset_id=ABSENT_SCOPE_ID,
                    performed_by_provider_id=nurse_id,
                    stage=STAGE_PRECLEAN,
                ),
                stage["nurse_headers"],
            ),
        ),
        (
            "commissioning_by_nurse",
            api.commission_scope_asset(
                ABSENT_SCOPE_ID_ALT,
                f.commissioning_payload(nurse_id),
                stage["nurse_headers"],
            ),
        ),
        # Pathology filing and accession belong to the PathologyLiaison.
        (
            "specimen_result_by_nurse",
            api.result_specimen(
                ABSENT_SPECIMEN_ID, f.result_payload(RESULT_BENIGN), stage["nurse_headers"]
            ),
        ),
        (
            "specimen_accession_by_urologist",
            api.accession_specimen(
                ABSENT_SPECIMEN_ID,
                f.accession_payload(
                    received_at="2026-09-14T08:00:00Z",
                    accession_number="ACC-1",
                    condition_on_receipt=CONDITION_INTACT,
                ),
                stage["urologist_headers"],
            ),
        ),
        # Referral decisions and the visit ledger belong to the coordinator.
        (
            "referral_decision_by_urologist",
            api.decide_pelvic_health_referral(
                ABSENT_REFERRAL_ID,
                f.referral_decision_payload(authorized_visits=1),
                stage["urologist_headers"],
            ),
        ),
        (
            "referral_visit_by_urologist",
            api.log_referral_visit(
                ABSENT_REFERRAL_ID,
                f.referral_visit_payload(visit_date="2026-09-20"),
                stage["urologist_headers"],
            ),
        ),
        # Opening a surveillance recall belongs to the Urologist.
        (
            "surveillance_recall_by_coordinator",
            api.create_surveillance_recall(
                f.surveillance_recall_payload(
                    patient_id=stage["patient"]["id"],
                    expected_patient_version=stage["patient"]["version"],
                    protocol=PROTOCOL_STONE,
                    risk_tier=TIER_LOW,
                    anchor_date="2026-09-01",
                ),
                stage["coordinator_headers"],
            ),
        ),
        # Roster registration, supplier returns and the clock belong to the
        # PracticeAdmin.
        (
            "provider_registration_by_scheduler",
            api.create_provider(
                f.provider_payload(
                    role_type=ROLE_TYPE_RN, full_name="Mole Ratt", npi="1000000099"
                ),
                stage["scheduler_headers"],
            ),
        ),
        (
            "lot_return_by_nurse",
            api.return_consignment_lot(
                ABSENT_LOT_ID, f.lot_return_payload(1), stage["nurse_headers"]
            ),
        ),
        (
            "clock_set_by_tech",
            api.set_clock(PROBE_CLOCK_ATTEMPTED_MOVE, stage["tech_headers"]),
        ),
    ]


PROBES_ON_EXISTING_ROWS = (
    "schedule_by_urologist",
    "check_in_by_urologist",
    "antibiotic_order_by_nurse",
    "surveillance_recall_by_coordinator",
    "provider_registration_by_scheduler",
    "clock_set_by_tech",
)

PROBES_ON_ABSENT_ROWS = (
    "reprocessing_log_by_nurse",
    "commissioning_by_nurse",
    "specimen_result_by_nurse",
    "specimen_accession_by_urologist",
    "referral_decision_by_urologist",
    "referral_visit_by_urologist",
    "lot_return_by_nurse",
)


def test_exclusive_operations_refused_when_invoked_by_another_role(api):
    """PRD §2.1: "Every endpoint declares which of those roles may invoke it
    (see §4); a syntactically valid caller whose role is not on an endpoint's
    list is refused with `ERR_UNAUTHORIZED`."
    PRD §4: "Every endpoint requires the `X-User-ID` and `X-User-Role` headers
    described in §2.1, and a caller whose role is outside the authorised set for
    the endpoint is refused with `ERR_UNAUTHORIZED` at HTTP 403 before any
    payload is examined."

    Design: Corner/rbac/rbac_exclusive_operations_cross_role_unauthorized
    """
    stage = _build_cross_role_stage(api)
    responses = dict(_cross_role_probes(api, stage))

    for label in PROBES_ON_EXISTING_ROWS:
        response = responses[label]
        validate_error(response, ERR_UNAUTHORIZED)
        assert response.status_code == 403, (
            f"{label}: an endpoint invoked by a role outside its authorised set "
            f"must answer HTTP 403, got {response.status_code}"
        )


def test_role_allowlist_refusal_precedes_resource_lookup(api):
    """PRD §4: "Every endpoint requires the `X-User-ID` and `X-User-Role`
    headers described in §2.1, and a caller whose role is outside the authorised
    set for the endpoint is refused with `ERR_UNAUTHORIZED` at HTTP 403 before
    any payload is examined."
    PRD §2.8: "`X-User-Role` appears in the endpoint's declared role list in §4.
    Otherwise `ERR_UNAUTHORIZED`, HTTP 403. Applies to every endpoint."
    PRD §2.8: "Path parameters resolve to their declared entity, evaluated
    strictly left to right."

    Design: Corner/rbac/rbac_exclusive_operations_cross_role_unauthorized
    """
    stage = _build_cross_role_stage(api)
    responses = dict(_cross_role_probes(api, stage))

    for label in PROBES_ON_ABSENT_ROWS:
        response = responses[label]
        validate_error(response, ERR_UNAUTHORIZED)
        assert response.status_code == 403, (
            f"{label}: the role check outranks resource existence, so a call by "
            f"an unauthorised role naming a row that does not exist must answer "
            f"403 and never 404, got {response.status_code}"
        )


def test_waive_decision_refused_for_procedure_nurse(api):
    """PRD §3.4: "It is reserved to the `Urologist` role — a `ProcedureNurse`
    submitting it is refused with `ERR_UNAUTHORIZED` — and it is the clinical
    override that lets an urgent case proceed without the paperwork."
    PRD §2.8: "On a case's clearance review, a `decision` of `WAIVE` requires the
    `Urologist` role; a `ProcedureNurse` may submit `CLEAR` and `BLOCK` but never
    `WAIVE`. Otherwise `ERR_UNAUTHORIZED`, HTTP 403. Applies to clearance review
    only."

    Design: Corner/rbac/rbac_exclusive_operations_cross_role_unauthorized
    """
    stage = _build_cross_role_stage(api)
    case_id = stage["case"]["id"]

    refused = api.review_clearance(
        case_id,
        f.clearance_review_payload(CLEARANCE_DECISION_WAIVE),
        stage["nurse_headers"],
    )
    validate_error(refused, ERR_UNAUTHORIZED)
    assert refused.status_code == 403, (
        "a nurse submitting WAIVE must be refused at HTTP 403, got "
        f"{refused.status_code}"
    )

    # The very same nurse on the very same case may submit CLEAR, which is what
    # makes this an argument-level authority check rather than an endpoint one.
    cleared = validate_success(
        api.review_clearance(
            case_id,
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            stage["nurse_headers"],
        )
    )
    assert_fields(cleared, clearance_status=CLEARANCE_CLEARED)


def test_refused_exclusive_operations_leave_the_practice_untouched(api):
    """PRD §4: "Every endpoint requires the `X-User-ID` and `X-User-Role` headers
    described in §2.1, and a caller whose role is outside the authorised set for
    the endpoint is refused with `ERR_UNAUTHORIZED` at HTTP 403 before any
    payload is examined."
    PRD §3.3: "A successful commit recomputes `procedure_minutes`,
    `turnover_minutes`, `scheduled_end_at` and `block_end_at` from scratch,
    increments the room's `version` by 1 because the room's occupancy ledger has
    changed, recomputes that room's `occupied_block_count`, and recomputes the
    case's readiness gates."
    PRD §3.7: "`CHECKIN_TOO_EARLY` — the logical clock instant is strictly
    earlier than `scheduled_start_at` less the thirty-minute early-arrival
    allowance."

    Design: Corner/rbac/rbac_exclusive_operations_cross_role_unauthorized
    """
    stage = _build_cross_role_stage(api)
    admin_headers = make_practice_admin_headers()

    for label, response in _cross_role_probes(api, stage):
        validate_error(response, ERR_UNAUTHORIZED)
    refused_waive = api.review_clearance(
        stage["case"]["id"],
        f.clearance_review_payload(CLEARANCE_DECISION_WAIVE),
        stage["nurse_headers"],
    )
    validate_error(refused_waive, ERR_UNAUTHORIZED)

    case = validate_success(api.get_procedure_case(stage["case"]["id"], admin_headers))
    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        clearance_status=CLEARANCE_PENDING_PREP,
    )

    room = validate_success(api.get_procedure_room(stage["room"]["id"], admin_headers))
    assert_fields(
        room,
        version=stage["room"]["version"],
        occupied_block_count=0,
    )

    rows, meta = validate_paginated(api.list_providers(admin_headers))
    assert meta["total_count"] == 6, (
        "the roster must still hold exactly the six providers registered in "
        f"setup, got {meta['total_count']}"
    )

    # The clock never moved, so the case is still inside its early-arrival
    # exclusion window: had the technician's clock call landed, the day would
    # have advanced past it and this gate would have dropped out.
    readiness = validate_success(
        api.get_case_readiness(stage["case"]["id"], admin_headers)
    )
    assert_readiness(
        readiness,
        [GATE_CLEARANCE_NOT_GRANTED, GATE_CHECKIN_TOO_EARLY],
        check_in_allowed=False,
    )


# ══════════════════════════════════════════════════════════════════════════
# Shared operations: both declared partners are admitted, with equal effect
# ══════════════════════════════════════════════════════════════════════════
def _build_shared_stage(api) -> Dict[str, Any]:
    """
    One provider per role the shared operations need, one cystoscopy suite, one
    procedure type that expects a specimen and asks for a single preparation
    instruction, and the logical clock parked on the morning of the list.
    """
    admin_headers = make_practice_admin_headers()

    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )
    nurse = fx.create_provider(
        api, ROLE_TYPE_RN, full_name="Nia Park", npi="1000000003"
    )
    pathologist = fx.create_provider(
        api, ROLE_TYPE_PATHOLOGY_LIAISON, full_name="Pat Loew", npi="1000000005"
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
        requires_specimen=True,
        required_prep_codes=[PREP_CODE_NPO_MIDNIGHT],
    )
    fx.set_clock(api, LIST_MORNING_CLOCK, admin_headers)

    return {
        "admin_headers": admin_headers,
        "urologist": urologist,
        "scheduler": scheduler,
        "nurse": nurse,
        "pathologist": pathologist,
        "urologist_headers": make_urologist_headers(urologist["id"]),
        "scheduler_headers": make_scheduler_headers(scheduler["id"]),
        "nurse_headers": make_procedure_nurse_headers(nurse["id"]),
        "pathologist_headers": make_pathology_liaison_headers(pathologist["id"]),
        "room": room,
        "procedure_type": procedure_type,
    }


def _register_patient(api, stage: Dict[str, Any], headers: Dict[str, str], **kwargs: Any):
    """Register a patient bound to the stage's urologist, as the given caller."""
    return api.create_patient(
        f.patient_payload(primary_urologist_id=stage["urologist"]["id"], **kwargs),
        headers,
    )


def _draft_shared_case(
    api,
    stage: Dict[str, Any],
    patient_id: str,
    scheduled_start_at: str,
    headers: Dict[str, str],
):
    return api.create_procedure_case(
        f.procedure_case_payload(
            patient_id=patient_id,
            procedure_type_id=stage["procedure_type"]["id"],
            room_id=stage["room"]["id"],
            primary_provider_id=stage["urologist"]["id"],
            scheduled_start_at=scheduled_start_at,
        ),
        headers,
    )


def _commit_shared_case(api, stage: Dict[str, Any], case_id: str):
    """Commit a drafted case, carrying the room version the client just read."""
    return api.schedule_case(
        case_id,
        f.schedule_payload(_room_version(api, stage["room"]["id"])),
        stage["scheduler_headers"],
    )


def _shared_stage_with_two_cases(api) -> Dict[str, Any]:
    """
    The stage plus two patients and two committed cases — the first entered by
    the urologist, the second by the scheduler — on non-overlapping windows.
    """
    stage = _build_shared_stage(api)

    patient_one = validate_success(
        _register_patient(
            api,
            stage,
            stage["admin_headers"],
            mrn="MRN-5071",
            full_name="Ana Fell",
            date_of_birth="1963-04-04",
            egfr=68,
        ),
        201,
    )
    patient_two = validate_success(
        _register_patient(
            api,
            stage,
            stage["scheduler_headers"],
            mrn="MRN-5072",
            full_name="Bo Kant",
            date_of_birth="1964-05-05",
            egfr=69,
        ),
        201,
    )

    case_one = validate_success(
        _draft_shared_case(
            api,
            stage,
            patient_one["id"],
            FIRST_CASE_START,
            stage["urologist_headers"],
        ),
        201,
    )
    case_two = validate_success(
        _draft_shared_case(
            api,
            stage,
            patient_two["id"],
            SECOND_CASE_START,
            stage["scheduler_headers"],
        ),
        201,
    )

    case_one = validate_success(_commit_shared_case(api, stage, case_one["id"]))
    case_two = validate_success(_commit_shared_case(api, stage, case_two["id"]))

    stage["patient_one"] = patient_one
    stage["patient_two"] = patient_two
    stage["case_one"] = case_one
    stage["case_two"] = case_two
    return stage


def test_patient_registration_and_case_drafting_admit_either_partner(api):
    """
    A shared operation admits both of its declared callers with equal effect.

    "Patients are registered by a `PracticeAdmin` or a `Scheduler` and are bound
    to a treating clinician at the moment of registration."

    "Renal function drifts, anticoagulation is started and stopped, and
    allergies are discovered late; a `PracticeAdmin` or the treating
    `Urologist` may therefore revise `egfr`, `anticoagulant_flag` and
    `antibiotic_allergy_class` on an existing patient."

    "A `Scheduler` or a `Urologist` supplies the four references that define it
    — `patient_id`, `procedure_type_id`, `room_id` and `primary_provider_id` —
    together with `scheduled_start_at`, the intended start of the in-room window
    as an ISO 8601 UTC instant with three fractional digits, and optionally an
    `indication_note` carrying free-text clinical justification, which defaults
    to null."

    Design: Corner/rbac/rbac_shared_operations_accepted_for_both_partners
    """
    stage = _build_shared_stage(api)

    patient_one = validate_success(
        _register_patient(
            api,
            stage,
            stage["admin_headers"],
            mrn="MRN-5071",
            full_name="Ana Fell",
            date_of_birth="1963-04-04",
            egfr=68,
        ),
        201,
    )
    patient_two = validate_success(
        _register_patient(
            api,
            stage,
            stage["scheduler_headers"],
            mrn="MRN-5072",
            full_name="Bo Kant",
            date_of_birth="1964-05-05",
            egfr=69,
        ),
        201,
    )
    assert_fields(patient_one, mrn="MRN-5071", egfr=68, version=1)
    assert_fields(patient_two, mrn="MRN-5072", egfr=69, version=1)

    # The treating urologist revises the chart the administrator opened.
    edited = validate_success(
        api.update_patient(
            patient_one["id"],
            f.patient_update_payload(anticoagulant_flag=True),
            stage["urologist_headers"],
        )
    )
    assert_fields(edited, anticoagulant_flag=True, version=2)

    # The urologist drafts one case and the scheduler the other; both are
    # accepted, and both land in the same starting state.
    case_one = validate_success(
        _draft_shared_case(
            api,
            stage,
            patient_one["id"],
            FIRST_CASE_START,
            stage["urologist_headers"],
        ),
        201,
    )
    case_two = validate_success(
        _draft_shared_case(
            api,
            stage,
            patient_two["id"],
            SECOND_CASE_START,
            stage["scheduler_headers"],
        ),
        201,
    )
    for case in (case_one, case_two):
        assert_fields(
            case,
            schedule_status=CASE_DRAFT,
            clearance_status=CLEARANCE_PENDING_PREP,
            procedure_minutes=20,
            turnover_minutes=20,
        )

    committed_one = validate_success(_commit_shared_case(api, stage, case_one["id"]))
    committed_two = validate_success(_commit_shared_case(api, stage, case_two["id"]))
    assert_fields(committed_one, schedule_status=CASE_SCHEDULED)
    assert_fields(committed_two, schedule_status=CASE_SCHEDULED)

    # Two commits, two occupancy blocks on the one room.
    room = validate_success(
        api.get_procedure_room(stage["room"]["id"], stage["admin_headers"])
    )
    assert_fields(room, occupied_block_count=2)


def test_prep_acknowledgement_and_clearance_admit_either_partner(api):
    """
    The preparation rung and the clearance rung each name two callers, and each
    accepts both of them on equal terms.

    "Preparation acknowledgements are recorded one instruction at a time by a
    `Scheduler` or a `ProcedureNurse`, each call naming a single
    `instruction_code` and the `channel` through which the patient confirmed
    it."

    "Clearance decisions are submitted by a `ProcedureNurse` or a `Urologist`
    and are shaped by a single `decision` field taking one of three values, with
    `block_reason_code` an optional companion."

    "A successful clear sets `clearance_block_reason` back to null and
    recomputes the readiness gates."

    Design: Corner/rbac/rbac_shared_operations_accepted_for_both_partners
    """
    stage = _shared_stage_with_two_cases(api)

    # The scheduler takes one acknowledgement, the nurse the other.
    acked_one = validate_success(
        api.acknowledge_prep(
            stage["case_one"]["id"],
            f.prep_acknowledgement_payload(
                instruction_code=PREP_CODE_NPO_MIDNIGHT, channel=CHANNEL_PHONE
            ),
            stage["scheduler_headers"],
        )
    )
    acked_two = validate_success(
        api.acknowledge_prep(
            stage["case_two"]["id"],
            f.prep_acknowledgement_payload(
                instruction_code=PREP_CODE_NPO_MIDNIGHT, channel=CHANNEL_PORTAL
            ),
            stage["nurse_headers"],
        )
    )
    for case in (acked_one, acked_two):
        assert_fields(
            case,
            clearance_status=CLEARANCE_PREP_ACKNOWLEDGED,
            acknowledged_prep_codes=[PREP_CODE_NPO_MIDNIGHT],
        )

    # The nurse clears one case, the urologist the other.
    cleared_one = validate_success(
        api.review_clearance(
            stage["case_one"]["id"],
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            stage["nurse_headers"],
        )
    )
    cleared_two = validate_success(
        api.review_clearance(
            stage["case_two"]["id"],
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            stage["urologist_headers"],
        )
    )
    for case in (cleared_one, cleared_two):
        assert_fields(
            case,
            schedule_status=CASE_SCHEDULED,
            clearance_status=CLEARANCE_CLEARED,
            clearance_block_reason=None,
        )


def _clear_and_admit_case_one(api, stage: Dict[str, Any]) -> Dict[str, Any]:
    """Acknowledge the one required instruction, clear the case, bring it in."""
    validate_success(
        api.acknowledge_prep(
            stage["case_one"]["id"],
            f.prep_acknowledgement_payload(
                instruction_code=PREP_CODE_NPO_MIDNIGHT, channel=CHANNEL_PHONE
            ),
            stage["scheduler_headers"],
        )
    )
    validate_success(
        api.review_clearance(
            stage["case_one"]["id"],
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            stage["nurse_headers"],
        )
    )
    return validate_success(
        api.check_in_case(stage["case_one"]["id"], {}, stage["nurse_headers"])
    )


def test_collection_accession_and_completion_admit_their_partners(api):
    """
    The container leaves the room in the urologist's hands, is received by the
    laboratory liaison, and the urologist rather than the nurse closes the case.

    "Bringing the patient into the room is a `ProcedureNurse`'s exclusive act and
    takes no payload; it advances `schedule_status` from `SCHEDULED` to
    `IN_ROOM`."

    "Containers are labelled and collected in the room by the attending
    `Urologist` or `ProcedureNurse`."

    "An `INTACT` container simply advances `chain_status` from `COLLECTED` to
    `ACCESSIONED` and does nothing else."

    "Closing out the procedure is available to the attending `ProcedureNurse` or
    the `Urologist`, optionally carrying an `outcome_note`, and it advances
    `schedule_status` from `IN_ROOM` to `COMPLETED`."

    Design: Corner/rbac/rbac_shared_operations_accepted_for_both_partners
    """
    stage = _shared_stage_with_two_cases(api)

    # _clear_and_admit_case_one already returns the validated `data` payload.
    admitted = _clear_and_admit_case_one(api, stage)
    assert_fields(
        admitted,
        schedule_status=CASE_IN_ROOM,
        checked_in_at="2026-09-14T09:00:00.000Z",
        blocking_reason_codes=[],
    )

    # The urologist collects, naming himself as the collecting provider.
    specimen = validate_success(
        api.create_specimen(
            f.specimen_payload(
                case_id=stage["case_one"]["id"],
                collected_by_provider_id=stage["urologist"]["id"],
                container_label="CUP-1",
                specimen_type=SPECIMEN_PROSTATE_CORE,
                site_code="LEFT-BASE",
            ),
            stage["urologist_headers"],
        ),
        201,
    )
    assert_fields(
        specimen,
        collected_by_provider_id=stage["urologist"]["id"],
        chain_status=CHAIN_COLLECTED,
        collected_at="2026-09-14T09:00:00.000Z",
    )

    received = validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at=LAB_RECEIVED_AT,
                accession_number="ACC-7100",
                condition_on_receipt=CONDITION_INTACT,
            ),
            stage["pathologist_headers"],
        )
    )
    assert_fields(received, chain_status=CHAIN_ACCESSIONED)

    # No container is left in the room, so the urologist may close the case.
    completed = validate_success(
        api.complete_case(
            stage["case_one"]["id"],
            f.complete_case_payload(),
            stage["urologist_headers"],
        )
    )
    assert_fields(
        completed,
        schedule_status=CASE_COMPLETED,
        completed_at="2026-09-14T09:00:00.000Z",
        blocking_reason_codes=[],
    )


def _resulted_specimen_of_case_one(api, stage: Dict[str, Any]) -> Dict[str, Any]:
    """Carry one case through to a filed benign result on its one container."""
    _clear_and_admit_case_one(api, stage)
    specimen = validate_success(
        api.create_specimen(
            f.specimen_payload(
                case_id=stage["case_one"]["id"],
                collected_by_provider_id=stage["urologist"]["id"],
                container_label="CUP-1",
                specimen_type=SPECIMEN_PROSTATE_CORE,
                site_code="LEFT-BASE",
            ),
            stage["urologist_headers"],
        ),
        201,
    )
    validate_success(
        api.accession_specimen(
            specimen["id"],
            f.accession_payload(
                received_at=LAB_RECEIVED_AT,
                accession_number="ACC-7100",
                condition_on_receipt=CONDITION_INTACT,
            ),
            stage["pathologist_headers"],
        )
    )
    validate_success(
        api.complete_case(
            stage["case_one"]["id"],
            f.complete_case_payload(),
            stage["urologist_headers"],
        )
    )
    return validate_success(
        api.result_specimen(
            specimen["id"], f.result_payload(RESULT_BENIGN), stage["pathologist_headers"]
        )
    )


def test_notification_attempt_and_recall_sweep_admit_either_partner(api):
    """
    The last two shared operations of the pathology thread: the nurse may close
    the notification loop the liaison opened, and the sweep answers to both of
    its callers.

    "Reaching the patient is recorded as one attempt at a time by a
    `PathologyLiaison` or a `ProcedureNurse`, naming the `outcome` — `REACHED` or
    `UNREACHABLE` — and the `channel` used."

    "A `PracticeAdmin` or a `Urologist` may trigger it; it takes no payload."

    "Its response carries `swept_at` holding the logical clock instant of the
    sweep, `recomputed_recall_count` for the number of recalls step 1
    recomputed, `overdue_recall_count` for the number step 2 moved into
    `OVERDUE`, `restored_recall_count` for the number step 2 pulled back to
    `SCHEDULED_DUE`, and `escalated_specimen_count` for the number of
    notifications step 3 escalated."

    Design: Corner/rbac/rbac_shared_operations_accepted_for_both_partners
    """
    stage = _shared_stage_with_two_cases(api)
    resulted = _resulted_specimen_of_case_one(api, stage)
    assert_fields(
        resulted, chain_status=CHAIN_RESULTED, notification_status=NOTIFY_PENDING
    )

    # The nurse, not the liaison, reaches the patient.
    acknowledged = validate_success(
        api.record_notification_attempt(
            resulted["id"],
            f.notification_attempt_payload(
                outcome=NOTIFY_OUTCOME_REACHED, channel=CHANNEL_PHONE
            ),
            stage["nurse_headers"],
        )
    )
    assert_fields(
        acknowledged,
        notification_status=NOTIFY_ACKNOWLEDGED,
        notification_attempt_count=1,
    )

    # Both callers of the checkpoint see the same book: the benign prostate core
    # opened one recall due a year out, and the acknowledgement closed the
    # notification loop, so nothing lapses and nothing escalates.
    for label, headers in (
        ("PracticeAdmin", stage["admin_headers"]),
        ("Urologist", stage["urologist_headers"]),
    ):
        report = validate_success(api.run_recall_sweep({}, headers))
        assert_fields(
            report,
            swept_at="2026-09-14T09:00:00.000Z",
            recomputed_recall_count=1,
            overdue_recall_count=0,
            restored_recall_count=0,
            escalated_specimen_count=0,
        )
        assert report["recomputed_recall_count"] == 1, (
            f"the sweep triggered by the {label} must report the one recall it "
            f"recomputed, got {report['recomputed_recall_count']}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Segregation of duties: two technicians, and the attester must be the caller
# ══════════════════════════════════════════════════════════════════════════
def _build_reprocessing_stage(api) -> Dict[str, Any]:
    """
    Three certified technicians — one who performs, one who will attest, and one
    who is named in a payload but never holds the header — plus a registered
    scope carrying a single open pre-clean log.
    """
    admin_headers = make_practice_admin_headers()

    omar = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Omar Diaz", npi="1000000004", hld_certified=True
    )
    rue = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Rue Bell", npi="1000000007", hld_certified=True
    )
    tal = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Tal Wynn", npi="1000000008", hld_certified=True
    )

    omar_headers = make_sterile_processing_tech_headers(omar["id"])
    rue_headers = make_sterile_processing_tech_headers(rue["id"])

    scope = fx.create_scope(
        api, omar, serial_number="SN-C", scope_model="FlexCysto 200", channel_count=2
    )
    log = validate_success(
        api.create_reprocessing_log(
            f.reprocessing_log_payload(
                scope_asset_id=scope["id"],
                performed_by_provider_id=omar["id"],
                stage=STAGE_PRECLEAN,
            ),
            omar_headers,
        ),
        201,
    )

    return {
        "admin_headers": admin_headers,
        "omar": omar,
        "rue": rue,
        "tal": tal,
        "omar_headers": omar_headers,
        "rue_headers": rue_headers,
        "scope": scope,
        "log": log,
    }


def test_self_attestation_and_proxy_attestation_are_both_refused(api):
    """
    The second signature must belong to a second person, and it must belong to
    the person making the call.

    "On completing a reprocessing log, `attested_by_provider_id` differs from
    that log's `performed_by_provider_id` and equals `X-User-ID`. Otherwise
    `ERR_SEGREGATION_OF_DUTIES`, HTTP 403. Applies to reprocessing log
    completion only."

    "One person may not both perform and attest a reprocessing stage; an attempt
    is refused with `ERR_SEGREGATION_OF_DUTIES`."

    "The scope moves only when the log closes."

    Design: Corner/rbac/rbac_segregation_of_duties_rejected
    """
    stage = _build_reprocessing_stage(api)
    log_id = stage["log"]["id"]
    assert_fields(stage["log"], log_status=LOG_OPEN, outcome=None)

    scope_before = validate_success(
        api.get_scope_asset(stage["scope"]["id"], stage["admin_headers"])
    )

    # The performer signs his own work.
    self_signed = api.complete_reprocessing_log(
        log_id,
        f.reprocessing_complete_payload(stage["omar"]["id"], outcome=OUTCOME_PASS),
        stage["omar_headers"],
    )
    validate_error(self_signed, ERR_SEGREGATION_OF_DUTIES)

    # A second technician calls, but signs a third technician's name — the
    # attester differs from the performer and is still refused, because the
    # attester named in the body is not the acting user.
    proxy_signed = api.complete_reprocessing_log(
        log_id,
        f.reprocessing_complete_payload(stage["tal"]["id"], outcome=OUTCOME_PASS),
        stage["rue_headers"],
    )
    validate_error(proxy_signed, ERR_SEGREGATION_OF_DUTIES)

    # Neither refusal touched the audit trail or the scope.
    log_after = validate_success(api.get_reprocessing_log(log_id, stage["admin_headers"]))
    assert_fields(
        log_after,
        log_status=LOG_OPEN,
        outcome=None,
        completed_at=None,
        attested_by_provider_id=None,
        performed_by_provider_id=stage["omar"]["id"],
    )

    scope_after = validate_success(
        api.get_scope_asset(stage["scope"]["id"], stage["admin_headers"])
    )
    assert_version_unchanged(scope_before, scope_after)


def test_stage_closes_when_the_second_technician_signs_and_calls(api):
    """
    The same call succeeds the moment the attester in the body is the caller and
    is not the performer.

    "A successful close sets `log_status` to `CLOSED`, records `completed_at` at
    the logical clock instant, and stores the `outcome`."

    Design: Corner/rbac/rbac_segregation_of_duties_rejected
    """
    stage = _build_reprocessing_stage(api)

    closed = validate_success(
        api.complete_reprocessing_log(
            stage["log"]["id"],
            f.reprocessing_complete_payload(stage["rue"]["id"], outcome=OUTCOME_PASS),
            stage["rue_headers"],
        )
    )
    assert_fields(
        closed,
        log_status=LOG_CLOSED,
        outcome=OUTCOME_PASS,
        attested_by_provider_id=stage["rue"]["id"],
        performed_by_provider_id=stage["omar"]["id"],
    )
    assert closed["completed_at"] is not None, (
        "a closed stage log must record the instant it was completed, got null"
    )


# ══════════════════════════════════════════════════════════════════════════
# Identity binding: the header pair must agree with the roster, and stay valid
# ══════════════════════════════════════════════════════════════════════════
def _build_identity_stage(api) -> Dict[str, Any]:
    """
    A urologist, a scheduler and a nurse, with one committed case waiting on its
    clearance decision — the operation both refused callers will aim at.
    """
    admin_headers = make_practice_admin_headers()

    urologist = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )
    nurse = fx.create_provider(api, ROLE_TYPE_RN, full_name="Nia Park", npi="1000000003")

    scheduler_headers = make_scheduler_headers(scheduler["id"])

    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5073",
                full_name="Cid Vane",
                date_of_birth="1959-09-09",
                egfr=72,
            ),
            scheduler_headers,
        ),
        201,
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
        required_prep_codes=[],
    )
    fx.set_clock(api, LIST_MORNING_CLOCK, admin_headers)

    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at=FIRST_CASE_START,
            ),
            scheduler_headers,
        ),
        201,
    )
    case = validate_success(
        api.schedule_case(
            case["id"],
            f.schedule_payload(_room_version(api, room["id"])),
            scheduler_headers,
        )
    )

    return {
        "admin_headers": admin_headers,
        "urologist": urologist,
        "scheduler": scheduler,
        "nurse": nurse,
        "scheduler_headers": scheduler_headers,
        "case": case,
    }


def test_claimed_role_must_match_the_roster_row_behind_the_identifier(api):
    """
    An entity-backed role is only as good as the row it names: a scheduler
    cannot borrow the nurse's capacity, and an identifier that names nobody at
    all cannot act either.

    "For each of the six entity-backed roles, `X-User-ID` resolves to an existing
    `Provider` whose `role_type` matches the binding declared in §2.1 for the
    claimed `X-User-Role`, and whose `credential_status` is `ACTIVE`; a
    `SUSPENDED` provider is refused even for reads."

    "The identity resolution described above runs **before** the per-endpoint
    role allowlist, so a caller who presents an `X-User-ID` that does not resolve
    to a Provider of the claimed role is refused with `ERR_UNAUTHORIZED` even on
    an endpoint their claimed role is permitted to use."

    Design: Corner/rbac/rbac_identity_binding_role_mismatch_unauthorized
    """
    stage = _build_identity_stage(api)
    case_id = stage["case"]["id"]

    # The identifier resolves, but to a Provider whose role_type is SCHEDULER.
    wrong_role_type = api.review_clearance(
        case_id,
        f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
        make_procedure_nurse_headers(stage["scheduler"]["id"]),
    )
    validate_error(wrong_role_type, ERR_UNAUTHORIZED)

    # The identifier resolves to nobody, and the answer is a role refusal, not a
    # not-found: identity resolution is decided long before any lookup.
    unknown_user = api.review_clearance(
        case_id,
        f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
        make_procedure_nurse_headers(ABSENT_PROVIDER_ID),
    )
    validate_error(unknown_user, ERR_UNAUTHORIZED)

    case_after = validate_success(
        api.get_procedure_case(case_id, stage["admin_headers"])
    )
    assert_fields(
        case_after,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
    )


def test_suspended_provider_is_refused_on_a_write_and_on_a_read(api):
    """
    Withdrawing a credential closes the door in both directions, which is what
    separates identity resolution from a write-only permission check.

    "In all six cases the resolved Provider must additionally have
    `credential_status` equal to `ACTIVE`; a Provider whose credential standing
    has been moved to `SUSPENDED` is refused on every request, including
    read-only ones, with `ERR_UNAUTHORIZED`."

    "Moving someone to `SUSPENDED` is the practice's off-switch: from that moment
    the identity-resolution rung of §2.8 refuses their very next request, read or
    write, with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_identity_binding_role_mismatch_unauthorized
    """
    stage = _build_identity_stage(api)
    case_id = stage["case"]["id"]
    nurse_headers = make_procedure_nurse_headers(stage["nurse"]["id"])

    suspended = validate_success(
        api.update_provider(
            stage["nurse"]["id"],
            f.provider_update_payload(credential_status=CREDENTIAL_SUSPENDED),
            stage["admin_headers"],
        )
    )
    assert_fields(suspended, credential_status=CREDENTIAL_SUSPENDED)

    # The write the nurse was entitled to a moment ago.
    refused_write = api.review_clearance(
        case_id, f.clearance_review_payload(CLEARANCE_DECISION_CLEAR), nurse_headers
    )
    validate_error(refused_write, ERR_UNAUTHORIZED)

    # And a plain read of the same case, which no role list would ever refuse.
    refused_read = api.get_procedure_case(case_id, nurse_headers)
    validate_error(refused_read, ERR_UNAUTHORIZED)

    case_after = validate_success(
        api.get_procedure_case(case_id, stage["admin_headers"])
    )
    assert_fields(
        case_after,
        schedule_status=CASE_SCHEDULED,
        clearance_status=CLEARANCE_PENDING_PREP,
    )


# ══════════════════════════════════════════════════════════════════════════
# Acting-provider identity: the provider named in the body is the caller
# ══════════════════════════════════════════════════════════════════════════
def _build_actor_stage(api) -> Dict[str, Any]:
    """
    Two urologists, two nurses, two technicians and a scheduler, so that every
    body field can name a second, equally credentialed provider of exactly the
    right kind. One committed case that needs prophylaxis and yields a specimen,
    plus one registered scope.
    """
    admin_headers = make_practice_admin_headers()

    urologist_a = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ada Nour", npi="1000000001"
    )
    urologist_b = fx.create_provider(
        api, ROLE_TYPE_UROLOGIST, full_name="Dr Ben Oro", npi="1000000011"
    )
    nurse_a = fx.create_provider(api, ROLE_TYPE_RN, full_name="Nia Park", npi="1000000003")
    nurse_b = fx.create_provider(api, ROLE_TYPE_RN, full_name="Ola Sund", npi="1000000012")
    tech_a = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Omar Diaz", npi="1000000004", hld_certified=True
    )
    tech_b = fx.create_provider(
        api, ROLE_TYPE_TECH, full_name="Rue Bell", npi="1000000007", hld_certified=True
    )
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )

    scheduler_headers = make_scheduler_headers(scheduler["id"])
    tech_a_headers = make_sterile_processing_tech_headers(tech_a["id"])

    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist_a["id"],
                mrn="MRN-5074",
                full_name="Dov Lark",
                date_of_birth="1957-07-17",
                egfr=75,
            ),
            scheduler_headers,
        ),
        201,
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
        requires_antibiotic=True,
        requires_specimen=True,
        required_prep_codes=[],
    )
    scope = fx.create_scope(
        api, tech_a, serial_number="SN-D", scope_model="FlexCysto 200", channel_count=2
    )
    fx.set_clock(api, LIST_MORNING_CLOCK, admin_headers)

    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist_a["id"],
                scheduled_start_at=FIRST_CASE_START,
            ),
            scheduler_headers,
        ),
        201,
    )
    case = validate_success(
        api.schedule_case(
            case["id"],
            f.schedule_payload(_room_version(api, room["id"])),
            scheduler_headers,
        )
    )

    return {
        "admin_headers": admin_headers,
        "urologist_a": urologist_a,
        "urologist_b": urologist_b,
        "nurse_a": nurse_a,
        "nurse_b": nurse_b,
        "tech_a": tech_a,
        "tech_b": tech_b,
        "urologist_a_headers": make_urologist_headers(urologist_a["id"]),
        "nurse_a_headers": make_procedure_nurse_headers(nurse_a["id"]),
        "tech_a_headers": tech_a_headers,
        "scheduler_headers": scheduler_headers,
        "patient": patient,
        "room": room,
        "procedure_type": procedure_type,
        "scope": scope,
        "case": case,
    }


def test_ordering_and_log_opening_refuse_a_body_naming_another_provider(api):
    """
    Two of the three body-named actors, each refused although the acting role is
    on the endpoint's list and the provider named is of exactly the right kind.

    "The provider named in the body is the caller: `ordered_by_provider_id` on
    antibiotic ordering, `performed_by_provider_id` on opening a reprocessing
    log, and `collected_by_provider_id` on specimen collection must each equal
    `X-User-ID`. Otherwise `ERR_ACTOR_IDENTITY_MISMATCH`, HTTP 403. Applies to
    exactly those three operations."

    "The payload names the `case_id` the order belongs to, the
    `ordered_by_provider_id` — which must be the acting user's own identifier, a
    mismatch being `ERR_ACTOR_IDENTITY_MISMATCH` — and a `requested_agent` of
    `AUTO`, `CIPROFLOXACIN`, `CEFAZOLIN`, `TMP_SMX` or `GENTAMICIN`."

    "Opening a stage log names the `scope_asset_id`, the `stage`, and the
    `performed_by_provider_id` — who must be the acting user, must have
    `role_type` `TECH`, and must have `credential_status` `ACTIVE` — plus
    optionally the `case_id` of the case that soiled the scope, which is null for
    a maintenance cycle."

    Design: Corner/rbac/rbac_actor_identity_body_mismatch_rejected
    """
    stage = _build_actor_stage(api)

    # One urologist orders in another urologist's name.
    order_attempt = api.create_antibiotic_order(
        f.antibiotic_order_payload(
            case_id=stage["case"]["id"],
            ordered_by_provider_id=stage["urologist_b"]["id"],
            requested_agent=AGENT_AUTO,
        ),
        stage["urologist_a_headers"],
    )
    validate_error(order_attempt, ERR_ACTOR_IDENTITY_MISMATCH)

    rows, meta = validate_paginated(
        api.list_antibiotic_orders(stage["admin_headers"], case_id=stage["case"]["id"])
    )
    assert meta["total_count"] == 0, (
        "a refused order must leave no antibiotic order behind, got "
        f"{meta['total_count']}"
    )
    assert rows == [], f"expected no antibiotic order rows, got {rows}"

    # One technician opens a stage log in another technician's name.
    log_attempt = api.create_reprocessing_log(
        f.reprocessing_log_payload(
            scope_asset_id=stage["scope"]["id"],
            performed_by_provider_id=stage["tech_b"]["id"],
            stage=STAGE_PRECLEAN,
        ),
        stage["tech_a_headers"],
    )
    validate_error(log_attempt, ERR_ACTOR_IDENTITY_MISMATCH)

    log_rows, log_meta = validate_paginated(
        api.list_reprocessing_logs(
            stage["admin_headers"], scope_asset_id=stage["scope"]["id"]
        )
    )
    assert log_meta["total_count"] == 0, (
        "a refused stage log must leave the reprocessing audit trail empty, got "
        f"{log_meta['total_count']}"
    )
    assert log_rows == [], f"expected no reprocessing log rows, got {log_rows}"


def test_order_naming_the_acting_urologist_is_accepted_and_administered(api):
    """
    The same call stands the moment the body names the caller, and the rest of
    the prophylaxis arithmetic follows from the formulary.

    "Otherwise `AUTO` selects the eligible agent with the lowest protocol rank,
    and ties on rank are broken by agent name in ascending alphabetical order."

    "The selected agent's base dose is taken at full strength when the patient's
    `egfr` is at least 45, and at exactly half strength when it is below 45."

    "The order also records `prophylaxis_window_start_at`, fixed at one hour
    before the case's `scheduled_start_at`, and is created with `status`
    `ORDERED` and `administered_at` null."

    "On success the order's `status` moves from `ORDERED` to `ADMINISTERED`,
    `administered_at` is stored, and the antibiotic gate drops out of the case's
    `blocking_reason_codes`."

    Design: Corner/rbac/rbac_actor_identity_body_mismatch_rejected
    """
    stage = _build_actor_stage(api)

    order = validate_success(
        api.create_antibiotic_order(
            f.antibiotic_order_payload(
                case_id=stage["case"]["id"],
                ordered_by_provider_id=stage["urologist_a"]["id"],
                requested_agent=AGENT_AUTO,
            ),
            stage["urologist_a_headers"],
        ),
        201,
    )
    assert_fields(
        order,
        ordered_by_provider_id=stage["urologist_a"]["id"],
        agent=AGENT_CIPROFLOXACIN,
        dose_mg=500,
        route=ROUTE_ORAL,
        prophylaxis_window_start_at="2026-09-14T08:00:00.000Z",
        status=ANTIBIOTIC_ORDERED,
        administered_at=None,
    )

    # Fifteen minutes before the list starts, well inside the closed window.
    administered = validate_success(
        api.administer_antibiotic_order(
            order["id"],
            f.administer_payload("2026-09-14T08:45:00Z"),
            stage["nurse_a_headers"],
        )
    )
    assert_fields(
        administered,
        status=ANTIBIOTIC_ADMINISTERED,
        administered_at="2026-09-14T08:45:00.000Z",
    )


def test_specimen_collection_refuses_a_collector_who_is_not_the_caller(api):
    """
    The third body-named actor, refused on a case that is otherwise perfectly
    ready: the nurse named on the container is an active nurse too, so only the
    identity binding can explain the refusal.

    "The payload names the `case_id`, the `collected_by_provider_id` — which must
    be the acting user's own identifier, a mismatch being
    `ERR_ACTOR_IDENTITY_MISMATCH` — the `container_label` written on the pot, the
    `specimen_type` of `PROSTATE_CORE`, `BLADDER_WASHING` or `BIOPSY_FRAGMENT`,
    and the `site_code` identifying the anatomic site sampled."

    "On success the case's `checked_in_at` records the logical clock instant and
    `blocking_reason_codes` collapses to the empty array."

    Design: Corner/rbac/rbac_actor_identity_body_mismatch_rejected
    """
    stage = _build_actor_stage(api)
    case_id = stage["case"]["id"]

    order = validate_success(
        api.create_antibiotic_order(
            f.antibiotic_order_payload(
                case_id=case_id,
                ordered_by_provider_id=stage["urologist_a"]["id"],
                requested_agent=AGENT_AUTO,
            ),
            stage["urologist_a_headers"],
        ),
        201,
    )
    validate_success(
        api.administer_antibiotic_order(
            order["id"],
            f.administer_payload("2026-09-14T08:45:00Z"),
            stage["nurse_a_headers"],
        )
    )
    validate_success(
        api.review_clearance(
            case_id,
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            stage["nurse_a_headers"],
        )
    )
    admitted = validate_success(
        api.check_in_case(case_id, {}, stage["nurse_a_headers"])
    )
    assert_fields(
        admitted,
        schedule_status=CASE_IN_ROOM,
        checked_in_at="2026-09-14T09:00:00.000Z",
        blocking_reason_codes=[],
    )

    # The attending nurse labels the pot with a colleague's name on it.
    specimen_attempt = api.create_specimen(
        f.specimen_payload(
            case_id=case_id,
            collected_by_provider_id=stage["nurse_b"]["id"],
            container_label="CUP-1",
            specimen_type=SPECIMEN_BLADDER_WASHING,
            site_code="BLADDER-DOME",
        ),
        stage["nurse_a_headers"],
    )
    validate_error(specimen_attempt, ERR_ACTOR_IDENTITY_MISMATCH)

    rows, meta = validate_paginated(
        api.list_specimens(stage["admin_headers"], case_id=case_id)
    )
    assert meta["total_count"] == 0, (
        f"a refused collection must leave no container behind, got {meta['total_count']}"
    )
    assert rows == [], f"expected no specimen rows, got {rows}"


# ══════════════════════════════════════════════════════════════════════════
# Missing headers: the first rung, ahead of every other check on every path
# ══════════════════════════════════════════════════════════════════════════
def _patient_probe_payload(scheduler_id: str, mrn: str, full_name: str, dob: str) -> Dict[str, Any]:
    """
    A registration payload whose `primary_urologist_id` names the scheduler — it
    could never be accepted on its merits, which is the point: the header rung
    answers long before any reference is resolved.
    """
    return f.patient_payload(
        primary_urologist_id=scheduler_id,
        mrn=mrn,
        full_name=full_name,
        date_of_birth=dob,
        egfr=70,
    )


def _probe_no_headers(api, scheduler_id: str):
    return api.create_patient(
        _patient_probe_payload(scheduler_id, "MRN-5075", "Eve Nom", "1968-08-08"), {}
    )


def _probe_role_only(api, scheduler_id: str):
    return api.create_patient(
        _patient_probe_payload(scheduler_id, "MRN-5076", "Fay Oon", "1969-09-09"),
        make_headers_missing_user_id(ROLE_SCHEDULER),
    )


def _probe_user_id_only(api, scheduler_id: str):
    return api.create_patient(
        _patient_probe_payload(scheduler_id, "MRN-5077", "Gus Pim", "1970-10-10"),
        make_headers_missing_role(scheduler_id),
    )


def _probe_blank_role(api, scheduler_id: str):
    return api.create_patient(
        _patient_probe_payload(scheduler_id, "MRN-5078", "Hal Quin", "1971-11-11"),
        make_headers(scheduler_id, ""),
    )


def _probe_blank_user_id(api, scheduler_id: str):
    return api.create_patient(
        _patient_probe_payload(scheduler_id, "MRN-5080", "Ivo Roth", "1972-12-12"),
        make_headers_blank_user_id(ROLE_SCHEDULER),
    )


def _probe_collection_read(api, scheduler_id: str):
    return api.list_patients({})


def _probe_no_headers_and_malformed_body(api, scheduler_id: str):
    return api.create_patient({"mrn": "MRN-5079"}, {})


UNAUTHENTICATED_PROBES = [
    ("neither header", _probe_no_headers),
    ("role without an acting user", _probe_role_only),
    ("acting user without a role", _probe_user_id_only),
    ("a blank role", _probe_blank_role),
    ("a blank acting user", _probe_blank_user_id),
    ("neither header on a collection read", _probe_collection_read),
    ("neither header and a malformed body", _probe_no_headers_and_malformed_body),
]


@pytest.mark.parametrize(
    "description,probe", UNAUTHENTICATED_PROBES, ids=[p[0] for p in UNAUTHENTICATED_PROBES]
)
def test_request_without_both_headers_is_unauthenticated(api, description, probe):
    """
    Every one of these requests is refused at the header rung: on a write, on a
    read, and even when the body could not have been accepted either.

    "Every request must carry two headers: `X-User-ID`, identifying the acting
    user, and `X-User-Role`, declaring the capacity in which they are acting. If
    either header is absent or blank, the request is refused with
    `ERR_UNAUTHENTICATED`."

    "`X-User-Role` and `X-User-ID` are both present and non-blank. Otherwise
    `ERR_UNAUTHENTICATED`, HTTP 401. Applies to every endpoint."

    "When it does, the response reports exactly one error, and which one is fully
    determined: the service evaluates its checks in a **total priority order**
    and returns the error belonging to the lowest-numbered rule that fails."

    Design: Corner/rbac/rbac_unauthenticated_missing_x_user_header_rejected
    """
    admin_headers = make_practice_admin_headers()
    scheduler = fx.create_provider(
        api, ROLE_TYPE_SCHEDULER, full_name="Sam Reyes", npi="1000000002"
    )

    response = probe(api, scheduler["id"])
    validate_error(response, ERR_UNAUTHENTICATED)

    # Nothing an unauthenticated caller sent may have landed.
    rows, meta = validate_paginated(api.list_patients(admin_headers))
    assert meta["total_count"] == 0, (
        f"a request carrying {description} must register no patient, got "
        f"{meta['total_count']}"
    )
    assert rows == [], f"expected no patient rows after a refusal, got {rows}"
