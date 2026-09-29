"""
Composite setup builders for the Urology Practice & In-Office Procedure Suite.

Every test starts against an empty database, so all state is built by calling
the contract's own endpoints. The builders here climb the dependency chain:
roster first, then reference data, then cases, then the specimen, recall,
referral and consignment flows that hang off a case.

Each builder returns the parsed entity payload (or a small bundle of them) so a
test can assert on it directly and can read the ``version`` values the
stale-version guards require.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    AGENT_AUTO,
    CLEARANCE_DECISION_CLEAR,
    CONDITION_INTACT,
    DECISION_ACCEPT,
    OUTCOME_PASS,
    PROGRAM_PELVIC_FLOOR_PT,
    PROTOCOL_STONE,
    RESULT_BENIGN,
    ROLE_TYPE_PATHOLOGY_LIAISON,
    ROLE_TYPE_PELVIC_COORDINATOR,
    ROLE_TYPE_RN,
    ROLE_TYPE_SCHEDULER,
    ROLE_TYPE_TECH,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    SPECIMEN_PROSTATE_CORE,
    STAGE_SEQUENCE,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
)
from .test_users import (
    make_pathology_liaison_headers,
    make_pelvic_health_coordinator_headers,
    make_practice_admin_headers,
    make_procedure_nurse_headers,
    make_scheduler_headers,
    make_sterile_processing_tech_headers,
    make_urologist_headers,
)


# ─── Tier 1: single rows ───────────────────────────────────────────────────
def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the service's logical UTC clock and return the reported instant."""
    response = api.set_clock(to_iso8601, headers or make_practice_admin_headers())
    return get_success_data(response)


def create_provider(api, role_type: str = ROLE_TYPE_UROLOGIST, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_provider(
        f.provider_payload(role_type=role_type, **kwargs), make_practice_admin_headers()
    )
    return get_success_data(response, 201)


def create_patient(api, urologist: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    response = api.create_patient(
        f.patient_payload(primary_urologist_id=urologist["id"], **kwargs),
        make_practice_admin_headers(),
    )
    return get_success_data(response, 201)


def create_room(api, room_type: str = ROOM_TYPE_CYSTO_SUITE, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_procedure_room(
        f.procedure_room_payload(room_type=room_type, **kwargs),
        make_practice_admin_headers(),
    )
    return get_success_data(response, 201)


def create_procedure_type(api, code: str = TYPE_CYSTOSCOPY, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_procedure_type(
        f.procedure_type_payload(code=code, **kwargs), make_practice_admin_headers()
    )
    return get_success_data(response, 201)


def create_scope(api, tech: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    response = api.create_scope_asset(
        f.scope_asset_payload(**kwargs), make_sterile_processing_tech_headers(tech["id"])
    )
    return get_success_data(response, 201)


def create_lot(api, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_consignment_lot(
        f.consignment_lot_payload(**kwargs), make_practice_admin_headers()
    )
    return get_success_data(response, 201)


# ─── Tier 2: the roster ────────────────────────────────────────────────────
class Roster:
    """
    The practice's people, one Provider per role plus a spare for each role
    that needs two distinct actors — the attester of a reprocessing stage must
    not be its performer, and overlap rules need a second urologist.
    """

    def __init__(self, api):
        self.admin_headers = make_practice_admin_headers()

        self.urologist = create_provider(api, ROLE_TYPE_UROLOGIST)
        self.urologist_alt = create_provider(api, ROLE_TYPE_UROLOGIST)
        self.nurse = create_provider(api, ROLE_TYPE_RN)
        self.nurse_alt = create_provider(api, ROLE_TYPE_RN)
        self.tech = create_provider(api, ROLE_TYPE_TECH, hld_certified=True)
        self.tech_alt = create_provider(api, ROLE_TYPE_TECH, hld_certified=True)
        self.scheduler = create_provider(api, ROLE_TYPE_SCHEDULER)
        self.pathologist = create_provider(api, ROLE_TYPE_PATHOLOGY_LIAISON)
        self.coordinator = create_provider(api, ROLE_TYPE_PELVIC_COORDINATOR)

        self.urologist_headers = make_urologist_headers(self.urologist["id"])
        self.urologist_alt_headers = make_urologist_headers(self.urologist_alt["id"])
        self.nurse_headers = make_procedure_nurse_headers(self.nurse["id"])
        self.nurse_alt_headers = make_procedure_nurse_headers(self.nurse_alt["id"])
        self.tech_headers = make_sterile_processing_tech_headers(self.tech["id"])
        self.tech_alt_headers = make_sterile_processing_tech_headers(self.tech_alt["id"])
        self.scheduler_headers = make_scheduler_headers(self.scheduler["id"])
        self.pathologist_headers = make_pathology_liaison_headers(self.pathologist["id"])
        self.coordinator_headers = make_pelvic_health_coordinator_headers(
            self.coordinator["id"]
        )


def build_roster(api) -> Roster:
    return Roster(api)


# ─── Tier 3: cases ─────────────────────────────────────────────────────────
def draft_case(
    api,
    roster: Roster,
    patient: Dict[str, Any],
    procedure_type: Dict[str, Any],
    room: Dict[str, Any],
    scheduled_start_at: str,
    provider: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Draft a case. A draft occupies neither the room nor the urologist."""
    provider = provider or roster.urologist
    response = api.create_procedure_case(
        f.procedure_case_payload(
            patient_id=patient["id"],
            procedure_type_id=procedure_type["id"],
            room_id=room["id"],
            primary_provider_id=provider["id"],
            scheduled_start_at=scheduled_start_at,
            **kwargs,
        ),
        headers or roster.scheduler_headers,
    )
    return get_success_data(response, 201)


def read_room(api, roster: Roster, room_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_procedure_room(room_id, roster.admin_headers))


def read_case(api, roster: Roster, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_procedure_case(case_id, roster.admin_headers))


def read_patient(api, roster: Roster, patient_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_patient(patient_id, roster.admin_headers))


def read_scope(api, roster: Roster, scope_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_scope_asset(scope_id, roster.admin_headers))


def read_lot(api, roster: Roster, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_consignment_lot(lot_id, roster.admin_headers))


def read_specimen(api, roster: Roster, specimen_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_specimen(specimen_id, roster.admin_headers))


def read_recall(api, roster: Roster, recall_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_surveillance_recall(recall_id, roster.admin_headers)
    )


def read_referral(api, roster: Roster, referral_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_pelvic_health_referral(referral_id, roster.admin_headers)
    )


def commit_case(
    api, roster: Roster, case: Dict[str, Any], room: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Commit a drafted case to the room calendar, reading the room's current
    version first so the stale-version guard is satisfied.
    """
    current_room = read_room(api, roster, room["id"])
    response = api.schedule_case(
        case["id"],
        f.schedule_payload(current_room["version"]),
        roster.scheduler_headers,
    )
    return get_success_data(response)


def schedule_new_case(
    api,
    roster: Roster,
    patient: Dict[str, Any],
    procedure_type: Dict[str, Any],
    room: Dict[str, Any],
    scheduled_start_at: str,
    provider: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Draft a case and put it straight onto the room calendar."""
    case = draft_case(
        api,
        roster,
        patient,
        procedure_type,
        room,
        scheduled_start_at,
        provider=provider,
        **kwargs,
    )
    return commit_case(api, roster, case, room)


def acknowledge_all_prep(
    api, roster: Roster, case_id: str, prep_codes: List[str], channel: Optional[str] = None
) -> Dict[str, Any]:
    """Acknowledge each of a procedure type's required preparation codes once."""
    data: Dict[str, Any] = {}
    for code in prep_codes:
        kwargs = {"instruction_code": code}
        if channel is not None:
            kwargs["channel"] = channel
        response = api.acknowledge_prep(
            case_id, f.prep_acknowledgement_payload(**kwargs), roster.nurse_headers
        )
        data = get_success_data(response)
    return data


def clear_case(
    api, roster: Roster, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Grant pre-procedure clearance on a case."""
    response = api.review_clearance(
        case_id,
        f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
        headers or roster.nurse_headers,
    )
    return get_success_data(response)


def assign_scope(
    api, roster: Roster, case_id: str, scope: Dict[str, Any]
) -> Dict[str, Any]:
    """Reserve a reprocessed scope for a case, carrying the scope's version."""
    current = read_scope(api, roster, scope["id"])
    response = api.assign_scope(
        case_id,
        f.scope_assignment_payload(scope["id"], current["version"]),
        roster.nurse_headers,
    )
    return get_success_data(response)


def reserve_device(
    api, roster: Roster, case_id: str, lot: Dict[str, Any], quantity: int = 1
) -> Dict[str, Any]:
    """Hold device units from a lot for a case, carrying the lot's version."""
    current = read_lot(api, roster, lot["id"])
    response = api.reserve_device(
        case_id,
        f.device_reservation_payload(lot["id"], quantity, current["version"]),
        roster.nurse_headers,
    )
    return get_success_data(response)


def check_in_case(api, roster: Roster, case_id: str) -> Dict[str, Any]:
    response = api.check_in_case(case_id, {}, roster.nurse_headers)
    return get_success_data(response)


def complete_case(
    api, roster: Roster, case_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api.complete_case(
        case_id, f.complete_case_payload(**kwargs), headers or roster.nurse_headers
    )
    return get_success_data(response)


# ─── Tier 4: whole flows ───────────────────────────────────────────────────
def build_simple_practice(
    api,
    procedure_code: str = TYPE_CYSTOSCOPY,
    room_type: str = ROOM_TYPE_CYSTO_SUITE,
    type_kwargs: Optional[Dict[str, Any]] = None,
    room_kwargs: Optional[Dict[str, Any]] = None,
    patient_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Roster, one room, one procedure type with no obligations, and one patient —
    the smallest complete stage on which a case can be booked.
    """
    roster = build_roster(api)
    room = create_room(api, room_type, **(room_kwargs or {}))
    procedure_type = create_procedure_type(
        api, procedure_code, allowed_room_type=room_type, **(type_kwargs or {})
    )
    patient = create_patient(api, roster.urologist, **(patient_kwargs or {}))
    return {
        "roster": roster,
        "room": room,
        "procedure_type": procedure_type,
        "patient": patient,
    }


def build_ready_scope(api, roster: Roster, **kwargs: Any) -> Dict[str, Any]:
    """
    A scope that may be used on a patient. A freshly registered scope has a
    null high-level-disinfection stamp, so it is commissioned on the
    manufacturer's factory attestation first.
    """
    scope = create_scope(api, roster.tech, **kwargs)
    response = api.commission_scope_asset(
        scope["id"],
        f.commissioning_payload(roster.tech_alt["id"]),
        roster.tech_headers,
    )
    return get_success_data(response)


def run_full_reprocessing_cycle(
    api, roster: Roster, scope_id: str, case_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Take a soiled scope through all five sterile-processing stages in order,
    closing each stage log with a second-person attestation from a different
    technician than the performer.
    """
    logs: List[Dict[str, Any]] = []
    for stage in STAGE_SEQUENCE:
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
        closed = get_success_data(
            api.complete_reprocessing_log(
                opened["id"],
                f.reprocessing_complete_payload(
                    roster.tech_alt["id"], outcome=OUTCOME_PASS
                ),
                roster.tech_alt_headers,
            )
        )
        logs.append(closed)
    return logs


def order_and_administer_antibiotic(
    api,
    roster: Roster,
    case_id: str,
    administered_at: str,
    requested_agent: str = AGENT_AUTO,
) -> Dict[str, Any]:
    """Order prophylaxis as the operating urologist, then record it given."""
    order = get_success_data(
        api.create_antibiotic_order(
            f.antibiotic_order_payload(
                case_id=case_id,
                ordered_by_provider_id=roster.urologist["id"],
                requested_agent=requested_agent,
            ),
            roster.urologist_headers,
        ),
        201,
    )
    return get_success_data(
        api.administer_antibiotic_order(
            order["id"], f.administer_payload(administered_at), roster.nurse_headers
        )
    )


def collect_specimen(
    api,
    roster: Roster,
    case_id: str,
    specimen_type: str = SPECIMEN_PROSTATE_CORE,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Label and collect a specimen container as the collecting urologist."""
    response = api.create_specimen(
        f.specimen_payload(
            case_id=case_id,
            collected_by_provider_id=roster.urologist["id"],
            specimen_type=specimen_type,
            **kwargs,
        ),
        roster.urologist_headers,
    )
    return get_success_data(response, 201)


def accession_specimen(
    api,
    roster: Roster,
    specimen_id: str,
    received_at: str,
    condition_on_receipt: str = CONDITION_INTACT,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = api.accession_specimen(
        specimen_id,
        f.accession_payload(
            received_at=received_at, condition_on_receipt=condition_on_receipt, **kwargs
        ),
        roster.pathologist_headers,
    )
    return get_success_data(response)


def result_specimen(
    api, roster: Roster, specimen_id: str, pathology_result: str = RESULT_BENIGN
) -> Dict[str, Any]:
    response = api.result_specimen(
        specimen_id, f.result_payload(pathology_result), roster.pathologist_headers
    )
    return get_success_data(response)


def open_recall(
    api,
    roster: Roster,
    patient: Dict[str, Any],
    protocol: str = PROTOCOL_STONE,
    risk_tier: str = TIER_LOW,
    anchor_date: str = "2026-08-01",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Open a surveillance recall, reading the patient's current version first so
    the patient guard is satisfied.
    """
    current = read_patient(api, roster, patient["id"])
    response = api.create_surveillance_recall(
        f.surveillance_recall_payload(
            patient_id=patient["id"],
            expected_patient_version=current["version"],
            protocol=protocol,
            risk_tier=risk_tier,
            anchor_date=anchor_date,
            **kwargs,
        ),
        roster.urologist_headers,
    )
    return get_success_data(response, 201)


def open_referral(
    api,
    roster: Roster,
    patient: Dict[str, Any],
    source_case_id: str,
    program: str = PROGRAM_PELVIC_FLOOR_PT,
    requested_visits: int = 4,
) -> Dict[str, Any]:
    response = api.create_pelvic_health_referral(
        f.referral_payload(
            patient_id=patient["id"],
            source_case_id=source_case_id,
            program=program,
            requested_visits=requested_visits,
        ),
        roster.urologist_headers,
    )
    return get_success_data(response, 201)


def accept_referral(
    api, roster: Roster, referral_id: str, authorized_visits: Optional[int] = None
) -> Dict[str, Any]:
    response = api.decide_pelvic_health_referral(
        referral_id,
        f.referral_decision_payload(DECISION_ACCEPT, authorized_visits=authorized_visits),
        roster.coordinator_headers,
    )
    return get_success_data(response)


def run_sweep(api, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the recall-book and notification-queue checkpoint."""
    response = api.run_recall_sweep({}, headers or make_practice_admin_headers())
    return get_success_data(response)
