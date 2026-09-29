"""Composite setup helpers.

The API server is restarted before every individual test, so each test begins
against an empty database and must build every precondition it needs through the
documented endpoints. These helpers do exactly that and nothing more: they pin
the logical clock, declare the level standards, register the two units, staff and
equip them, and then walk the referral, transport, admission, milk, surge,
surveillance and follow-up chains.

`setup_network()` returns an environment mapping with these keys:

``unit_a`` / ``unit_b``       the registered unit resources (``unit_b`` may be None)
``unit_a_id`` / ``unit_b_id`` their ids
``standards``                 {level: standard resource}
``credentials``               {credential_code: credential resource}
``assets``                    {equipment_code: asset resource}
``admin`` / ``admin_2``       NetworkAdmin headers (net-1 / net-2)
``dir_a`` / ``dir_b``         UnitDirector headers scoped to unit A / unit B
``intake_a`` / ``intake_b``   IntakeNeonatologist headers scoped to unit A / unit B
``ref_a`` / ``ref_b``         ReferringClinician headers scoped to unit A / unit B
``coord``                     TransportCoordinator headers (coord-1)
``nurse`` / ``nurse_2``       BedsideNurse headers (nurse-1 / nurse-2)
``fu``                        FollowUpCoordinator headers (fu-1)

Unit-scoped headers are always rebuilt from the id the test just created, never
taken from a constant, because the unit portion of ``X-User-ID`` is what the
ownership checks compare.
"""

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START
from .test_users import (
    make_bedside_nurse_headers,
    make_followup_coordinator_headers,
    make_intake_neonatologist_headers,
    make_network_admin_headers,
    make_referring_clinician_headers,
    make_transport_coordinator_headers,
    make_unit_director_headers,
)

Env = Dict[str, Any]

DEFAULT_STANDARD_LEVELS: Tuple[str, ...] = ("LEVEL_I", "LEVEL_II", "LEVEL_III")

DEFAULT_CREDENTIALS: Tuple[Tuple[str, str, float], ...] = (
    ("NEO_BOARD", "neo-1", 1.0),
    ("RN_NICU_CORE", "rn-pool", 3.0),
)

DEFAULT_EQUIPMENT: Tuple[Tuple[str, str], ...] = (
    ("CONVENTIONAL_VENT", "VENT-1"),
    ("HFOV", "HFOV-1"),
)

ISOLETTE_EQUIPMENT: Tuple[str, str] = ("TRANSPORT_ISOLETTE", "ISO-1")


# ---------------------------------------------------------------------------
# Clock and sweep
# ---------------------------------------------------------------------------


def set_clock(instant: str = CLOCK_START, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or make_network_admin_headers()
    return get_success_data(api_client.set_current_utc(factories.clock_payload(instant), headers))


def run_sweep(
    env: Optional[Env] = None,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or (env["admin"] if env else make_network_admin_headers())
    return get_success_data(
        api_client.run_capacity_sweep(factories.capacity_sweep_payload(unit_id), headers)
    )


# ---------------------------------------------------------------------------
# Standards, units, credentials, assets
# ---------------------------------------------------------------------------


def declare_standard(
    level: str = "LEVEL_III", headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    headers = headers or make_network_admin_headers()
    return get_success_data(
        api_client.create_designation_standard(
            factories.designation_standard_payload(level, **overrides), headers
        )
    )


def declare_standards(
    levels: Iterable[str] = DEFAULT_STANDARD_LEVELS, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Dict[str, Any]]:
    return {level: declare_standard(level, headers) for level in levels}


def register_unit(
    payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or make_network_admin_headers()
    return get_success_data(
        api_client.create_nicu_unit(payload or factories.nicu_unit_payload(), headers)
    )


def add_credential(
    unit_id: str,
    credential_code: str = "RN_NICU_CORE",
    holder_reference: str = "rn-pool",
    fte: float = 3.0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_unit_director_headers(unit_id)
    return get_success_data(
        api_client.create_staff_credential(
            factories.staff_credential_payload(
                unit_id,
                credential_code=credential_code,
                holder_reference=holder_reference,
                fte=fte,
                **overrides,
            ),
            headers,
        )
    )


def add_equipment(
    unit_id: str,
    equipment_code: str = "CONVENTIONAL_VENT",
    asset_tag: str = "VENT-1",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_unit_director_headers(unit_id)
    return get_success_data(
        api_client.create_equipment_asset(
            factories.equipment_asset_payload(
                unit_id, equipment_code=equipment_code, asset_tag=asset_tag, **overrides
            ),
            headers,
        )
    )


def setup_network(
    standard_levels: Iterable[str] = DEFAULT_STANDARD_LEVELS,
    clock: Optional[str] = CLOCK_START,
    unit_a_overrides: Optional[Dict[str, Any]] = None,
    unit_b_overrides: Optional[Dict[str, Any]] = None,
    with_unit_b: bool = True,
    credentials: Sequence[Tuple[str, str, float]] = DEFAULT_CREDENTIALS,
    equipment: Sequence[Tuple[str, str]] = DEFAULT_EQUIPMENT,
    with_isolette: bool = False,
) -> Env:
    """Pin the clock, declare the standards and stand up a staffed LEVEL_III unit
    plus a LEVEL_I community unit that can refer into it."""
    if clock is not None:
        set_clock(clock)

    admin = make_network_admin_headers()
    standards = declare_standards(standard_levels, admin)

    unit_a = register_unit(factories.nicu_unit_payload(**(unit_a_overrides or {})), admin)
    unit_a_id = unit_a["id"]

    unit_b = None
    unit_b_id = None
    if with_unit_b:
        unit_b = register_unit(factories.community_unit_payload(**(unit_b_overrides or {})), admin)
        unit_b_id = unit_b["id"]

    dir_a = make_unit_director_headers(unit_a_id)

    credential_resources: Dict[str, Dict[str, Any]] = {}
    for code, holder, fte in credentials:
        credential_resources[code] = add_credential(
            unit_a_id, credential_code=code, holder_reference=holder, fte=fte, headers=dir_a
        )

    asset_specs = list(equipment)
    if with_isolette:
        asset_specs.append(ISOLETTE_EQUIPMENT)

    asset_resources: Dict[str, Dict[str, Any]] = {}
    for code, tag in asset_specs:
        asset_resources[code] = add_equipment(
            unit_a_id, equipment_code=code, asset_tag=tag, headers=dir_a
        )

    env: Env = {
        "unit_a": unit_a,
        "unit_b": unit_b,
        "unit_a_id": unit_a_id,
        "unit_b_id": unit_b_id,
        "standards": standards,
        "credentials": credential_resources,
        "assets": asset_resources,
        "admin": admin,
        "admin_2": make_network_admin_headers("net-2"),
        "dir_a": dir_a,
        "intake_a": make_intake_neonatologist_headers(unit_a_id),
        "ref_a": make_referring_clinician_headers(unit_a_id),
        "coord": make_transport_coordinator_headers(),
        "nurse": make_bedside_nurse_headers("nurse-1"),
        "nurse_2": make_bedside_nurse_headers("nurse-2"),
        "fu": make_followup_coordinator_headers(),
    }
    if unit_b_id is not None:
        env["dir_b"] = make_unit_director_headers(unit_b_id)
        env["intake_b"] = make_intake_neonatologist_headers(unit_b_id)
        env["ref_b"] = make_referring_clinician_headers(unit_b_id)
    return env


# ---------------------------------------------------------------------------
# Unit reads and capacity edits
# ---------------------------------------------------------------------------


def read_unit(
    env: Env, unit_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or env["admin"]
    return get_success_data(api_client.get_nicu_unit(unit_id, headers))


def read_unit_version(
    env: Env, unit_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> int:
    return read_unit(env, unit_id, headers)["version"]


def patch_unit(
    env: Env,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_unit_version: Optional[int] = None,
    **fields: Any,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or env["admin"]
    if expected_unit_version is None:
        expected_unit_version = read_unit_version(env, unit_id, headers)
    return get_success_data(
        api_client.patch_nicu_unit(
            unit_id, factories.unit_patch_payload(expected_unit_version, **fields), headers
        )
    )


def read_capacity_projection(
    env: Env, unit_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or env["admin"]
    return get_success_data(api_client.get_capacity_projection(unit_id, headers))


# ---------------------------------------------------------------------------
# Designation reviews
# ---------------------------------------------------------------------------


def open_review(
    env: Env,
    unit_id: Optional[str] = None,
    requested_level: str = "LEVEL_III",
    assigned_nurse_count: int = 2,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or make_unit_director_headers(unit_id)
    return get_success_data(
        api_client.create_designation_review(
            factories.designation_review_payload(
                unit_id,
                requested_level=requested_level,
                assigned_nurse_count=assigned_nurse_count,
                **overrides,
            ),
            headers,
        )
    )


def submit_review(
    env: Env,
    review_id: str,
    headers: Optional[Dict[str, str]] = None,
    **payload: Any,
) -> Dict[str, Any]:
    headers = headers or env["dir_a"]
    return get_success_data(
        api_client.submit_designation_review(review_id, dict(payload), headers)
    )


def return_review(
    env: Env,
    review_id: str,
    return_reason: str = "Credential evidence incomplete",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or env["admin"]
    return get_success_data(
        api_client.return_designation_review(
            review_id, factories.review_return_payload(return_reason), headers
        )
    )


def verify_review(
    env: Env, review_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or env["admin"]
    return get_success_data(api_client.verify_designation_review(review_id, {}, headers))


def certify_review(
    env: Env, review_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or env["admin_2"]
    return get_success_data(api_client.certify_designation_review(review_id, {}, headers))


def designate_unit(
    env: Env,
    unit_id: Optional[str] = None,
    requested_level: str = "LEVEL_III",
    assigned_nurse_count: int = 2,
) -> Dict[str, Any]:
    """Walk a review all the way from DRAFT to CERTIFIED with two distinct
    network reviewers, so the unit ends up designated."""
    unit_id = unit_id or env["unit_a_id"]
    review = open_review(
        env, unit_id=unit_id, requested_level=requested_level, assigned_nurse_count=assigned_nurse_count
    )
    submit_review(env, review["id"], headers=make_unit_director_headers(unit_id))
    verify_review(env, review["id"], headers=env["admin"])
    return certify_review(env, review["id"], headers=env["admin_2"])


# ---------------------------------------------------------------------------
# Referrals, holds and admissions
# ---------------------------------------------------------------------------


def create_referral(
    env: Env,
    case_reference: str = "CASE-N1",
    referring_unit_id: Optional[str] = None,
    receiving_unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    referring_unit_id = referring_unit_id or env["unit_b_id"]
    receiving_unit_id = receiving_unit_id or env["unit_a_id"]
    headers = headers or make_referring_clinician_headers(referring_unit_id)
    return get_success_data(
        api_client.create_referral(
            factories.referral_payload(
                referring_unit_id,
                receiving_unit_id,
                case_reference=case_reference,
                **overrides,
            ),
            headers,
        )
    )


def accept_referral(
    env: Env,
    referral_id: str,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_unit_version: Optional[int] = None,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or make_intake_neonatologist_headers(unit_id)
    if expected_unit_version is None:
        expected_unit_version = read_unit_version(env, unit_id, headers)
    return get_success_data(
        api_client.accept_referral(
            referral_id, factories.accept_referral_payload(expected_unit_version), headers
        )
    )


def hold_bed(
    env: Env, case_reference: str = "CASE-N1", **overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a referral and accept it, returning (referral, accepted_referral)."""
    referral = create_referral(env, case_reference=case_reference, **overrides)
    accepted = accept_referral(env, referral["id"])
    return referral, accepted


def admit(
    env: Env,
    referral_id: str,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or make_intake_neonatologist_headers(unit_id)
    return get_success_data(
        api_client.create_admission(factories.admission_payload(referral_id), headers)
    )


def admit_case(
    env: Env, case_reference: str = "CASE-N1", **overrides: Any
) -> Dict[str, Any]:
    """Refer, accept and admit in one step; returns the admission."""
    referral = create_referral(env, case_reference=case_reference, **overrides)
    accept_referral(env, referral["id"])
    return admit(env, referral["id"])


def read_referral(
    env: Env, referral_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or env["admin"]
    return get_success_data(api_client.get_referral(referral_id, headers))


def read_reservation(
    env: Env, reservation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or env["admin"]
    return get_success_data(api_client.get_bed_reservation(reservation_id, headers))


# ---------------------------------------------------------------------------
# Transport runs
# ---------------------------------------------------------------------------


def create_run(
    env: Env,
    reservation_id: str,
    isolette_asset_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if isolette_asset_id is None:
        isolette_asset_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]
    headers = headers or env["coord"]
    return get_success_data(
        api_client.create_transport_run(
            factories.transport_run_payload(reservation_id, isolette_asset_id, **overrides), headers
        )
    )


def dispatch_run(
    env: Env, run_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispatch_transport_run(run_id, {}, headers or env["coord"])
    )


def run_on_scene(
    env: Env, run_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.transport_run_on_scene(run_id, {}, headers or env["coord"])
    )


def stabilize_run(
    env: Env, run_id: str, headers: Optional[Dict[str, str]] = None, **vitals: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.stabilize_transport_run(
            run_id, factories.stabilize_payload(**vitals), headers or env["coord"]
        )
    )


def depart_run(env: Env, run_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.depart_transport_run(run_id, {}, headers or env["coord"]))


def arrive_run(
    env: Env,
    run_id: str,
    arrived_at: str = "2026-08-01T04:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.arrive_transport_run(
            run_id, factories.arrive_payload(arrived_at), headers or env["coord"]
        )
    )


def complete_run(
    env: Env,
    reservation_id: str,
    arrived_at: str = "2026-08-01T04:00:00Z",
    stabilize: Optional[Dict[str, Any]] = None,
    **run_overrides: Any,
) -> Dict[str, Any]:
    """Activate, dispatch, arrive on scene, stabilise, depart and arrive."""
    run = create_run(env, reservation_id, **run_overrides)
    dispatch_run(env, run["id"])
    run_on_scene(env, run["id"])
    stabilize_run(env, run["id"], **(stabilize or {}))
    depart_run(env, run["id"])
    return arrive_run(env, run["id"], arrived_at)


# ---------------------------------------------------------------------------
# Bedside care
# ---------------------------------------------------------------------------


def care_update(
    env: Env, admission_id: str, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_care_update(
            admission_id, factories.care_update_payload(**fields), headers or env["nurse"]
        )
    )


def developmental_round(
    env: Env, admission_id: str, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_developmental_round(
            admission_id, factories.developmental_round_payload(**fields), headers or env["nurse"]
        )
    )


def developmental_rounds(
    env: Env, admission_id: str, count: int = 2, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    admission: Dict[str, Any] = {}
    for _ in range(count):
        admission = developmental_round(env, admission_id, headers=headers, **fields)
    return admission


def infection_event(
    env: Env, admission_id: str, event: str = "SUSPECT", headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_infection_event(
            admission_id, factories.infection_event_payload(event), headers or env["nurse"]
        )
    )


def attest_back_transfer_ready(
    env: Env,
    admission_id: str,
    headers: Optional[Dict[str, str]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.attest_back_transfer_ready(
            admission_id,
            factories.back_transfer_ready_payload(**fields),
            headers or env["intake_a"],
        )
    )


def make_back_transfer_ready(
    env: Env, admission_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Bring an admission to BACK_TRANSFER_READY: room air, two compliant
    developmental rounds, then the attestation."""
    care_update(env, admission_id, support_modality="ROOM_AIR")
    developmental_rounds(env, admission_id, count=2, light_cycling_compliant=True)
    return attest_back_transfer_ready(env, admission_id)


def back_transfer_referral(
    env: Env,
    admission_id: str,
    receiving_unit_id: Optional[str] = None,
    case_reference: str = "CASE-BT1",
    expected_admission_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    receiving_unit_id = receiving_unit_id or env["unit_b_id"]
    headers = headers or env["intake_a"]
    if expected_admission_version is None:
        expected_admission_version = read_admission(env, admission_id)["version"]
    return get_success_data(
        api_client.create_back_transfer_referral(
            admission_id,
            factories.back_transfer_referral_payload(
                expected_admission_version, receiving_unit_id, case_reference
            ),
            headers,
        )
    )


def discharge(
    env: Env,
    admission_id: str,
    disposition: str = "HOME",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.discharge_admission(
            admission_id, factories.discharge_payload(disposition), headers or env["intake_a"]
        )
    )


def read_admission(
    env: Env, admission_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    headers = headers or env["admin"]
    return get_success_data(api_client.get_admission(admission_id, headers))


# ---------------------------------------------------------------------------
# Milk
# ---------------------------------------------------------------------------


def receive_milk_batch(
    env: Env, admission_id: str, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_milk_batch(
            factories.milk_batch_payload(admission_id, **fields), headers or env["nurse"]
        )
    )


def verify_milk_batch(
    env: Env,
    batch_id: str,
    label_code: str = "LBL-1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_milk_batch(
            batch_id, factories.verify_milk_payload(label_code), headers or env["nurse_2"]
        )
    )


def administer_milk(
    env: Env, batch_id: str, volume_ml: float = 30.0, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.administer_milk(
            batch_id, factories.milk_volume_payload(volume_ml), headers or env["nurse"]
        )
    )


def verified_milk_batch(
    env: Env,
    admission_id: str,
    label_code: str = "LBL-1",
    **fields: Any,
) -> Dict[str, Any]:
    """Receive a batch as nurse-1 and verify it as nurse-2, as two-person
    verification requires."""
    batch = receive_milk_batch(env, admission_id, label_code=label_code, **fields)
    return verify_milk_batch(env, batch["id"], label_code=label_code)


# ---------------------------------------------------------------------------
# Surge escalations
# ---------------------------------------------------------------------------


def request_surge(
    env: Env,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or make_unit_director_headers(unit_id)
    return get_success_data(
        api_client.create_surge_escalation(
            factories.surge_escalation_payload(unit_id, **fields), headers
        )
    )


def authorize_surge(
    env: Env, escalation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.authorize_surge_escalation(escalation_id, {}, headers or env["admin"])
    )


def deny_surge(
    env: Env,
    escalation_id: str,
    denial_reason: str = "Network capacity retained elsewhere",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.deny_surge_escalation(
            escalation_id, factories.deny_surge_payload(denial_reason), headers or env["admin"]
        )
    )


# ---------------------------------------------------------------------------
# Surveillance
# ---------------------------------------------------------------------------


def create_report(
    env: Env,
    unit_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    unit_id = unit_id or env["unit_a_id"]
    headers = headers or make_unit_director_headers(unit_id)
    return get_success_data(
        api_client.create_surveillance_report(
            factories.surveillance_report_payload(unit_id, **fields), headers
        )
    )


def submit_report(
    env: Env, report_id: str, headers: Optional[Dict[str, str]] = None, **fields: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_surveillance_report(
            report_id, factories.submit_report_payload(**fields), headers or env["dir_a"]
        )
    )


def accept_report(
    env: Env, report_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_surveillance_report(report_id, {}, headers or env["admin"])
    )


# ---------------------------------------------------------------------------
# Follow-up
# ---------------------------------------------------------------------------


def enroll_graduate(
    env: Env,
    admission_id: str,
    clinic_unit_id: Optional[str] = None,
    target_appointment_date: str = "2026-08-20T09:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    clinic_unit_id = clinic_unit_id or env["unit_a_id"]
    return get_success_data(
        api_client.create_follow_up_enrollment(
            factories.follow_up_enrollment_payload(
                admission_id, clinic_unit_id, target_appointment_date
            ),
            headers or env["fu"],
        )
    )


def schedule_enrollment(
    env: Env,
    enrollment_id: str,
    confirmed_appointment_date: str = "2026-08-20T09:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.schedule_follow_up_enrollment(
            enrollment_id,
            factories.schedule_payload(confirmed_appointment_date),
            headers or env["fu"],
        )
    )


def record_attendance(
    env: Env, enrollment_id: str, attended: bool = True, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_follow_up_attendance(
            enrollment_id, factories.attendance_payload(attended), headers or env["fu"]
        )
    )


def discharged_graduate(
    env: Env, case_reference: str = "CASE-N1", **referral_overrides: Any
) -> Dict[str, Any]:
    """Admit a case, close it home and return the discharged admission."""
    admission = admit_case(env, case_reference=case_reference, **referral_overrides)
    return discharge(env, admission["id"], "HOME")
