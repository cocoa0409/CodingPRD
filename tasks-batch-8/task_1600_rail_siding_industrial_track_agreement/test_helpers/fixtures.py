"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through PRD-declared
endpoints — the runner restarts the server before every test, so nothing is
carried over. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors rather than confusing assertion output.

Role headers used internally:
  RCM       RailroadContractsManager (agreements, amendments, claims, settle)
  SHIPPER   ShipperFacilityManager bound to the canonical shipper_user_id
  ENGINEER  RailroadEngineer (segments, spec approval, devices, removal)
  INSPECTOR SafetyInspector (inspections)
  SERVICE   RailroadServiceManager (car dwells, order completion)
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_amendment_payload,
    create_car_dwell_payload,
    create_device_payload,
    create_inspection_payload,
    create_liability_claim_payload,
    create_project_payload,
    create_segment_payload,
    create_service_order_payload,
    create_storage_placement_payload,
    submit_spec_payload,
)
from .test_users import TEST_USERS, make_shipper_headers

RCM = TEST_USERS["railroad_contracts_manager_headers"]
SHIPPER = TEST_USERS["shipper_facility_manager_headers"]
ENGINEER = TEST_USERS["railroad_engineer_headers"]
INSPECTOR = TEST_USERS["safety_inspector_headers"]
SERVICE = TEST_USERS["railroad_service_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: agreement state progression (PRD §3.1)
# ---------------------------------------------------------------------------

def make_agreement(**overrides) -> dict:
    """Create a TrackAgreement in DRAFT. Returns the created agreement."""
    res = api_client.create_agreement(create_agreement_payload(**overrides), RCM)
    return get_success_data(res)


def make_active_agreement(**overrides) -> dict:
    """Create + submit + countersign. Returns the ACTIVE agreement (version 3)."""
    agreement = make_agreement(**overrides)
    agr_id = agreement["id"]
    get_success_data(api_client.submit_agreement(agr_id, RCM))
    shipper_id = agreement.get("shipper_user_id", C.SHIPPER_USER_ID)
    res = api_client.countersign_agreement(agr_id, make_shipper_headers(shipper_id))
    return get_success_data(res)


def make_terminated_agreement(**overrides) -> dict:
    """ACTIVE agreement moved to TERMINATED (PRD §3.1)."""
    agreement = make_active_agreement(**overrides)
    res = api_client.terminate_agreement(
        agreement["id"], RCM, payload={"reason": "Shipper discontinued rail service"}
    )
    return get_success_data(res)


def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PRD §2.4). Returns {current_utc}."""
    res = api_client.set_current_utc({"to_iso8601": to_iso8601}, RCM)
    return get_success_data(res)


def get_agreement(agreement_id: str) -> dict:
    """Read one agreement back (expiry sweep applied per PRD §2.4)."""
    return get_success_data(api_client.get_agreement(agreement_id, RCM))


# ---------------------------------------------------------------------------
# Tier 2: child entities under an agreement (PRD §3.3-§3.7)
# ---------------------------------------------------------------------------

def make_segment(agreement_id, **overrides) -> dict:
    """Define a TrackSegment (born IN_SERVICE) under an ACTIVE agreement."""
    res = api_client.create_segment(
        create_segment_payload(agreement_id, **overrides), ENGINEER
    )
    return get_success_data(res)


def get_segment(segment_id: str) -> dict:
    return get_success_data(api_client.get_segment(segment_id, ENGINEER))


def make_project(agreement_id, **overrides) -> dict:
    """Create a ConstructionProject in DRAFT under an ACTIVE agreement."""
    res = api_client.create_project(
        create_project_payload(agreement_id, **overrides), SHIPPER
    )
    return get_success_data(res)


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, RCM))


def submit_project_spec(project_id, **spec_overrides) -> dict:
    """Submit a track spec (DRAFT/SPEC_REJECTED -> SPEC_SUBMITTED)."""
    res = api_client.submit_spec(
        project_id, submit_spec_payload(**spec_overrides), SHIPPER
    )
    return get_success_data(res)


def make_approved_project(agreement_id, **overrides) -> dict:
    """Project driven to SPEC_APPROVED; estimated share computed at approval."""
    project = make_project(agreement_id, **overrides)
    submit_project_spec(project["id"])
    res = api_client.approve_spec(project["id"], ENGINEER)
    return get_success_data(res)


def make_completed_project(agreement_id, actual_cost_cents=450000, **overrides) -> dict:
    """Project driven to COMPLETED; final share and outstanding computed."""
    project = make_approved_project(agreement_id, **overrides)
    res = api_client.complete_project(
        project["id"], {"actual_cost_cents": actual_cost_cents}, SHIPPER
    )
    return get_success_data(res)


def make_car_dwell(agreement_id, car_mark="RBOX1001", car_ownership="RAILROAD",
                   placed_at="2026-08-01T00:00:00Z") -> dict:
    """Record a car placement (born SPOTTED)."""
    res = api_client.create_car_dwell(
        create_car_dwell_payload(
            agreement_id,
            car_mark=car_mark,
            car_ownership=car_ownership,
            placed_at=placed_at,
        ),
        SERVICE,
    )
    return get_success_data(res)


def release_car_dwell(dwell_id, released_at) -> dict:
    """Release a SPOTTED dwell (computes the final demurrage variant)."""
    res = api_client.release_car_dwell(dwell_id, {"released_at": released_at}, SERVICE)
    return get_success_data(res)


def get_car_dwell(dwell_id: str) -> dict:
    return get_success_data(api_client.get_car_dwell(dwell_id, SERVICE))


def make_storage_placement(segment_id, car_mark="STGX101",
                           placed_date="2026-08-01") -> dict:
    """Place a car into private-track storage (born STORED)."""
    res = api_client.create_storage_placement(
        create_storage_placement_payload(
            segment_id, car_mark=car_mark, placed_date=placed_date
        ),
        SHIPPER,
    )
    return get_success_data(res)


def release_storage_placement(placement_id, released_date) -> dict:
    """Release a STORED placement (computes the final per-car charge)."""
    res = api_client.release_storage_placement(
        placement_id, {"released_date": released_date}, SHIPPER
    )
    return get_success_data(res)


def get_storage_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_storage_placement(placement_id, SHIPPER))


def make_device(segment_id, device_type="DERAIL",
                location_description="East end, fouling point") -> dict:
    """Propose a DerailDevice (born PROPOSED)."""
    res = api_client.create_device(
        create_device_payload(
            segment_id,
            device_type=device_type,
            location_description=location_description,
        ),
        SHIPPER,
    )
    return get_success_data(res)


def make_installed_device(segment_id, **overrides) -> dict:
    """Device driven PROPOSED -> APPROVED -> INSTALLED."""
    device = make_device(segment_id, **overrides)
    get_success_data(api_client.approve_device(device["id"], ENGINEER))
    res = api_client.mark_installed(device["id"], SHIPPER)
    return get_success_data(res)


def get_device(device_id: str) -> dict:
    return get_success_data(api_client.get_device(device_id, ENGINEER))


def make_inspection(agreement_id, segment_id, scheduled_date="2026-08-01") -> dict:
    """Schedule a SafetyInspection (born SCHEDULED; due_date = scheduled_date)."""
    res = api_client.create_inspection(
        create_inspection_payload(
            agreement_id, segment_id, scheduled_date=scheduled_date
        ),
        INSPECTOR,
    )
    return get_success_data(res)


def record_inspection_result(inspection_id, result, completed_date,
                             cited_device_ids=None) -> dict:
    """Record PASS/FAIL; cascades to cited devices and segment suspension."""
    payload = {"result": result, "completed_date": completed_date}
    if cited_device_ids is not None:
        payload["cited_device_ids"] = cited_device_ids
    res = api_client.record_result(inspection_id, payload, INSPECTOR)
    return get_success_data(res)


def get_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, INSPECTOR))


def make_service_order(agreement_id, segment_id, order_type="SWITCHING",
                       service_date=C.MONDAY_DATE, start_hour=8, end_hour=10) -> dict:
    """Request a ServiceOrder (born REQUESTED)."""
    res = api_client.create_service_order(
        create_service_order_payload(
            agreement_id,
            segment_id,
            order_type=order_type,
            service_date=service_date,
            start_hour=start_hour,
            end_hour=end_hour,
        ),
        SHIPPER,
    )
    return get_success_data(res)


def get_service_order(order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(order_id, SHIPPER))


def make_liability_claim(agreement_id, claim_amount_cents=60000,
                         claimant_name="J. Doe", incident_date="2026-08-02") -> dict:
    """File a LiabilityClaim (born FILED)."""
    res = api_client.create_liability_claim(
        create_liability_claim_payload(
            agreement_id,
            claim_amount_cents=claim_amount_cents,
            claimant_name=claimant_name,
            incident_date=incident_date,
        ),
        RCM,
    )
    return get_success_data(res)


def get_liability_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_liability_claim(claim_id, RCM))


# ---------------------------------------------------------------------------
# Tier 3: amendment protocol (PRD §3.2; OCC-guarded per PRD §2.7)
# ---------------------------------------------------------------------------

_AMENDMENT_DEFAULT_FIELDS = {
    "COST_SHARE": {"new_shipper_cost_share_pct": 55},
    "LIABILITY_CAP": {"new_liability_cap_cents": 250000},
    "STORAGE_RATE": {"new_storage_rate_per_car_month_cents": 12000},
    "DEMURRAGE_RATES": {
        "new_demurrage_base_rate_cents": 9000,
        "new_demurrage_escalated_rate_cents": 18000,
    },
    "TERM": {"new_term_end_date": "2028-07-31"},
}


def make_amendment(agreement_id, expected_agreement_version,
                   amendment_type="LIABILITY_CAP", proposer="railroad",
                   **new_field_overrides) -> dict:
    """Propose a PENDING amendment against an ACTIVE agreement.

    proposer="railroad" uses the contracts manager; "shipper" uses the
    party-bound facility manager. The new_* field defaults match the type pin
    of PRD §3.2.
    """
    new_fields = dict(_AMENDMENT_DEFAULT_FIELDS[amendment_type])
    new_fields.update(new_field_overrides)
    payload = create_amendment_payload(
        amendment_type, expected_agreement_version, **new_fields
    )
    headers = RCM if proposer == "railroad" else SHIPPER
    res = api_client.create_amendment(agreement_id, payload, headers)
    return get_success_data(res)


def get_amendment(amendment_id: str) -> dict:
    return get_success_data(api_client.get_amendment(amendment_id, RCM))


# ---------------------------------------------------------------------------
# Tier 4: composite domain states
# ---------------------------------------------------------------------------

def setup_agreement_with_segment(capacity=3, **agreement_overrides) -> dict:
    """ACTIVE agreement + one IN_SERVICE segment. Returns dict(agreement, segment)."""
    agreement = make_active_agreement(**agreement_overrides)
    segment = make_segment(agreement["id"], storage_capacity_cars=capacity)
    return {"agreement": agreement, "segment": segment}


def setup_suspended_segment(capacity=3, completed_date="2026-08-01") -> dict:
    """ACTIVE agreement + segment + INSTALLED device + FAIL inspection citing it.

    After this fixture the segment's safety_suspended is True (PRD §3.4 FAIL
    cascade). Returns dict(agreement, segment, device, inspection).
    """
    ctx = setup_agreement_with_segment(capacity=capacity)
    device = make_installed_device(ctx["segment"]["id"])
    inspection = make_inspection(ctx["agreement"]["id"], ctx["segment"]["id"])
    completed = record_inspection_result(
        inspection["id"], "FAIL", completed_date, cited_device_ids=[device["id"]]
    )
    return {
        "agreement": ctx["agreement"],
        "segment": ctx["segment"],
        "device": device,
        "inspection": completed,
    }


def setup_terminated_with_stored_car(capacity=3, car_mark="STGX901",
                                     placed_date="2026-08-01") -> dict:
    """Agreement ACTIVE -> TERMINATED with one STORED placement on one segment.

    Ready for file-abandonment-notice (PRD §3.8).
    Returns dict(agreement, segment, placement).
    """
    ctx = setup_agreement_with_segment(capacity=capacity)
    placement = make_storage_placement(
        ctx["segment"]["id"], car_mark=car_mark, placed_date=placed_date
    )
    terminated = get_success_data(
        api_client.terminate_agreement(
            ctx["agreement"]["id"],
            RCM,
            payload={"reason": "Shipper discontinued rail service"},
        )
    )
    return {
        "agreement": terminated,
        "segment": ctx["segment"],
        "placement": placement,
    }


def setup_abandonment_in_progress(notice_date=C.ABANDONMENT_NOTICE_DATE,
                                  with_segment=True) -> dict:
    """Agreement driven TERMINATED -> ABANDONMENT_IN_PROGRESS (PRD §3.8).

    Returns dict(agreement, segment) where segment is the post-cascade segment
    (or None when with_segment=False).
    """
    if with_segment:
        ctx = setup_agreement_with_segment()
        terminated = get_success_data(
            api_client.terminate_agreement(
                ctx["agreement"]["id"],
                RCM,
                payload={"reason": "Shipper discontinued rail service"},
            )
        )
        segment = ctx["segment"]
    else:
        terminated = make_terminated_agreement()
        segment = None
    res = api_client.file_abandonment_notice(
        terminated["id"], {"notice_date": notice_date}, SHIPPER
    )
    return {"agreement": get_success_data(res), "segment": segment}
