"""Setup builders that construct preconditions through declared endpoints only.

Every helper here drives the public API: no state is written behind the
service's back. The logical clock reads exactly `2026-08-01T00:00:00Z` on a
freshly started server, so all default windows are anchored on that instant.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import INITIAL_CLOCK
from .test_users import (
    make_biomed_tech_headers,
    make_chief_perfusionist_headers,
    make_contract_admin_headers,
    make_perfusionist_headers,
    make_surgeon_headers,
)

ADMIN_HEADERS = make_contract_admin_headers()
TECH_HEADERS = make_biomed_tech_headers()


# ─── Logical clock ────────────────────────────────────
def set_clock(current_utc: str) -> Dict[str, Any]:
    """Advance the server's only time source and return the reconciliation report."""
    return get_success_data(
        api_client.set_clock(factories.build_clock(current_utc), ADMIN_HEADERS)
    )


# ─── Master data ──────────────────────────────────────
def create_contract(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_hospital_contract(
            factories.build_hospital_contract(**overrides), ADMIN_HEADERS
        ),
        201,
    )


def read_contract(contract_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_hospital_contract(contract_id, headers or ADMIN_HEADERS)
    )


def create_surgeon(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_surgeon(factories.build_surgeon(**overrides), ADMIN_HEADERS), 201
    )


def create_preference_card(
    surgeon_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_preference_card(
            factories.build_preference_card(surgeon_id, **overrides),
            headers or make_surgeon_headers(surgeon_id),
        ),
        201,
    )


def create_perfusionist(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_perfusionist(factories.build_perfusionist(**overrides), ADMIN_HEADERS),
        201,
    )


def read_perfusionist(perfusionist_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_perfusionist(perfusionist_id, headers or ADMIN_HEADERS)
    )


def create_certification(perfusionist_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_certification(
            perfusionist_id, factories.build_certification(**overrides), ADMIN_HEADERS
        ),
        201,
    )


def create_ce_activity(perfusionist_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ce_activity(
            perfusionist_id, factories.build_ce_activity(**overrides), ADMIN_HEADERS
        ),
        201,
    )


def adjudicate_ce_activity(ce_activity_id: str, decision: str = "VERIFIED", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_ce_activity(
            ce_activity_id, factories.build_ce_decision(decision, **overrides), ADMIN_HEADERS
        )
    )


def create_device(contract_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_perfusion_device(
            factories.build_perfusion_device(contract_id, **overrides), TECH_HEADERS
        ),
        201,
    )


def read_device(device_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_perfusion_device(device_id, headers or TECH_HEADERS)
    )


def capture_device_event(
    device_id: str, event_code: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_device_event_log(
            device_id,
            factories.build_device_event_log(event_code, **overrides),
            headers or TECH_HEADERS,
        ),
        201,
    )


def complete_device_service(device_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_service_completion(
            device_id, factories.build_service_completion(**overrides), TECH_HEADERS
        ),
        200,
    )


def create_slot(
    contract_id: str,
    perfusionist_id: str,
    chief_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    headers = make_chief_perfusionist_headers(chief_id) if chief_id else ADMIN_HEADERS
    return get_success_data(
        api_client.create_call_rotation_slot(
            factories.build_call_rotation_slot(contract_id, perfusionist_id, **overrides), headers
        ),
        201,
    )


def read_slot(slot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_call_rotation_slot(slot_id, headers or ADMIN_HEADERS)
    )


# ─── Case lifecycle steps ─────────────────────────────
def create_case(
    contract_id: str,
    surgeon_id: str,
    chief_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    headers = make_chief_perfusionist_headers(chief_id) if chief_id else ADMIN_HEADERS
    return get_success_data(
        api_client.create_bypass_case(
            factories.build_bypass_case(contract_id, surgeon_id, **overrides), headers
        ),
        201,
    )


def read_case(case_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_bypass_case(case_id, headers or ADMIN_HEADERS))


def assign_perfusionist(
    case_id: str,
    perfusionist_id: str,
    expected_case_version: int,
    chief_id: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.assign_perfusionist(
            case_id,
            factories.build_assignment(perfusionist_id, expected_case_version, **overrides),
            make_chief_perfusionist_headers(chief_id),
        )
    )


def configure_pack(
    case_id: str,
    primary_device_id: str,
    perfusionist_id: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.configure_disposable_pack(
            case_id,
            factories.build_pack_configuration(primary_device_id, **overrides),
            make_perfusionist_headers(perfusionist_id),
        ),
        201,
    )


def read_pack(pack_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_disposable_pack(pack_id, headers or ADMIN_HEADERS))


def approve_pack(pack_id: str, surgeon_id: str, decision: str = "APPROVED", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_disposable_pack(
            pack_id,
            factories.build_pack_decision(decision, **overrides),
            make_surgeon_headers(surgeon_id),
        )
    )


def open_checklist(case_id: str, perfusionist_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pump_checklist(
            case_id,
            factories.build_pump_checklist(**overrides),
            make_perfusionist_headers(perfusionist_id),
        ),
        201,
    )


def read_checklist(checklist_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_pump_checklist(checklist_id, headers or ADMIN_HEADERS))


def verify_checklist(checklist_id: str, perfusionist_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_pump_checklist(
            checklist_id, make_perfusionist_headers(perfusionist_id)
        )
    )


def start_bypass(case_id: str, perfusionist_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_bypass(case_id, make_perfusionist_headers(perfusionist_id))
    )


def end_bypass(case_id: str, perfusionist_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.end_bypass(
            case_id,
            factories.build_end_bypass(**overrides),
            make_perfusionist_headers(perfusionist_id),
        )
    )


def close_case(case_id: str, chief_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_bypass_case(case_id, make_chief_perfusionist_headers(chief_id))
    )


def cancel_case(case_id: str, chief_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_bypass_case(case_id, make_chief_perfusionist_headers(chief_id))
    )


def settle_month(contract_id: str, period: str = "2026-08", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_settlement_run(
            contract_id, factories.build_settlement_run(period, **overrides), ADMIN_HEADERS
        ),
        200,
    )


# ─── ECMO runs ────────────────────────────────────────
def create_ecmo_run(case_id: str, perfusionist_id: str, mode: str = "VA", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ecmo_run(
            case_id,
            factories.build_ecmo_run(mode, **overrides),
            make_perfusionist_headers(perfusionist_id),
        ),
        201,
    )


def read_ecmo_run(run_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_ecmo_run(run_id, headers or ADMIN_HEADERS))


def handoff_ecmo_run(run_id: str, relief_slot_id: str, chief_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.handoff_ecmo_run(
            run_id,
            factories.build_ecmo_handoff(relief_slot_id, **overrides),
            make_chief_perfusionist_headers(chief_id),
        )
    )


def decannulate_ecmo_run(run_id: str, perfusionist_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.decannulate_ecmo_run(run_id, make_perfusionist_headers(perfusionist_id))
    )


# ─── Incident reports ─────────────────────────────────
def create_incident_report(
    case_id: str, involved_perfusionist_id: str, filer_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_incident_report(
            factories.build_incident_report(case_id, involved_perfusionist_id, **overrides),
            make_perfusionist_headers(filer_id),
        ),
        201,
    )


def read_incident_report(report_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_incident_report(report_id, headers or ADMIN_HEADERS))


def submit_incident_report(report_id: str, filer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_incident_report(report_id, make_perfusionist_headers(filer_id))
    )


def review_incident_report(report_id: str, chief_id: str, decision: str = "ACCEPT_FOR_REVIEW", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_incident_report(
            report_id,
            factories.build_incident_review(decision, **overrides),
            make_chief_perfusionist_headers(chief_id),
        )
    )


def close_incident_report(report_id: str, chief_id: str, finding: str = "ISOLATED", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_incident_report(
            report_id,
            factories.build_incident_close(finding, **overrides),
            make_chief_perfusionist_headers(chief_id),
        )
    )


# ─── Composite environments ───────────────────────────
def _headers_for(env: Dict[str, Any]) -> None:
    """Attach header conveniences for the actors an environment created."""
    env["admin_headers"] = ADMIN_HEADERS
    env["tech_headers"] = TECH_HEADERS
    env["chief_headers"] = make_chief_perfusionist_headers(env["chief"]["id"])
    env["p1_headers"] = make_perfusionist_headers(env["p1"]["id"])
    env["surgeon_headers"] = make_surgeon_headers(env["surgeon"]["id"])


def base_setup(
    contract_overrides: Optional[Dict[str, Any]] = None,
    card_overrides: Optional[Dict[str, Any]] = None,
    cert_overrides: Optional[Dict[str, Any]] = None,
    ce_overrides: Optional[Dict[str, Any]] = None,
    slot_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    with_devices: bool = True,
    with_slot: bool = True,
    with_case: bool = True,
) -> Dict[str, Any]:
    """Build the shared starting point: one hospital, one surgeon and card, a
    staff perfusionist with a current certification and a CE claim, a machine
    pair, a primary call window and one scheduled case.

    A machine designating another as its standing fallback is created second,
    so that the fallback row already exists when the designation is made.
    """
    env: Dict[str, Any] = {}
    env["contract"] = create_contract(**(contract_overrides or {}))
    env["surgeon"] = create_surgeon()
    env["card"] = create_preference_card(env["surgeon"]["id"], **(card_overrides or {}))
    env["p1"] = create_perfusionist()
    env["chief"] = create_perfusionist(
        full_name="Nadia Oyelaran",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    env["cert"] = create_certification(env["p1"]["id"], **(cert_overrides or {}))
    env["ce"] = create_ce_activity(env["p1"]["id"], **(ce_overrides or {}))
    if with_devices:
        env["d2"] = create_device(env["contract"]["id"], asset_tag="HLM-002")
        env["d1"] = create_device(
            env["contract"]["id"], asset_tag="HLM-001", backup_device_id=env["d2"]["id"]
        )
    _headers_for(env)
    if with_slot:
        env["slot_p1"] = create_slot(
            env["contract"]["id"],
            env["p1"]["id"],
            chief_id=env["chief"]["id"],
            **(slot_overrides or {}),
        )
    if with_case:
        env["case"] = create_case(
            env["contract"]["id"],
            env["surgeon"]["id"],
            chief_id=env["chief"]["id"],
            **(case_overrides or {}),
        )
    return env


def add_perfusionist(env: Dict[str, Any], key: str = "p2", **overrides) -> Dict[str, Any]:
    """Onboard a further perfusionist and register them under `key`."""
    payload = {
        "full_name": "Tom Vasquez",
        "employee_code": "EMP-1003",
        "ecmo_privileged": True,
        "career_case_count": 90,
    }
    payload.update(overrides)
    env[key] = create_perfusionist(**payload)
    return env[key]


def add_slot(env: Dict[str, Any], perfusionist_id: str, key: str = "slot_extra", **overrides) -> Dict[str, Any]:
    """Put a perfusionist on call at the environment's hospital."""
    env[key] = create_slot(
        env["contract"]["id"], perfusionist_id, chief_id=env["chief"]["id"], **overrides
    )
    return env[key]


def add_case(env: Dict[str, Any], key: str = "case_extra", **overrides) -> Dict[str, Any]:
    """Schedule a further case at the environment's hospital."""
    env[key] = create_case(
        env["contract"]["id"], env["surgeon"]["id"], chief_id=env["chief"]["id"], **overrides
    )
    return env[key]


def add_device(env: Dict[str, Any], key: str = "d3", **overrides) -> Dict[str, Any]:
    """Commission a further machine at the environment's hospital."""
    payload = {"asset_tag": "HLM-003"}
    payload.update(overrides)
    env[key] = create_device(env["contract"]["id"], **payload)
    return env[key]


def staffed_setup(**opts) -> Dict[str, Any]:
    """Base setup with the staff perfusionist assigned, so the case is STAFFED."""
    env = base_setup(**opts)
    env["case"] = assign_perfusionist(
        env["case"]["id"], env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    return env


def pack_configured_setup(pack_overrides: Optional[Dict[str, Any]] = None, **opts) -> Dict[str, Any]:
    """Staffed setup with the disposable pack materialised and both machines reserved."""
    env = staffed_setup(**opts)
    env["pack"] = configure_pack(
        env["case"]["id"], env["d1"]["id"], env["p1"]["id"], **(pack_overrides or {})
    )
    env["case"] = read_case(env["case"]["id"])
    return env


def setup_verified_setup(
    checklist_overrides: Optional[Dict[str, Any]] = None, **opts
) -> Dict[str, Any]:
    """Pack-configured setup with the pre-bypass checklist opened and signed off."""
    env = pack_configured_setup(**opts)
    env["checklist"] = open_checklist(
        env["case"]["id"], env["p1"]["id"], **(checklist_overrides or {})
    )
    env["checklist"] = verify_checklist(env["checklist"]["id"], env["p1"]["id"])
    env["case"] = read_case(env["case"]["id"])
    return env


def on_bypass_setup(**opts) -> Dict[str, Any]:
    """Setup-verified environment taken on pump."""
    env = setup_verified_setup(**opts)
    env["case"] = start_bypass(env["case"]["id"], env["p1"]["id"])
    return env


def off_bypass_setup(end_bypass_overrides: Optional[Dict[str, Any]] = None, **opts) -> Dict[str, Any]:
    """On-pump environment brought off pump with its clinical record written."""
    env = on_bypass_setup(**opts)
    env["case"] = end_bypass(
        env["case"]["id"], env["p1"]["id"], **(end_bypass_overrides or {})
    )
    return env


def closed_case_setup(**opts) -> Dict[str, Any]:
    """Off-pump environment closed, so the final fee variant has been settled."""
    env = off_bypass_setup(**opts)
    env["case"] = close_case(env["case"]["id"], env["chief"]["id"])
    return env
