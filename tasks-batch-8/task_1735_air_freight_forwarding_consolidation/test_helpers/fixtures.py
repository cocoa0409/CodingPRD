"""Composite setup helpers for the air-freight test suite.

Each helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so every test starts
against an empty database). Setup calls use the lenient get_success_data()
validator so setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLAIM_FILING_CLOCK_UTC,
    DEMERIT_LIMIT,
    MILESTONE_ARRIVED_UTC,
    MILESTONE_DELIVERED_UTC,
    MILESTONE_DEPARTED_UTC,
    STANDARD_TENDER_WINDOW_END,
    STANDARD_TENDER_WINDOW_START,
)
from .factories import (
    consolidate_payload,
    create_claim_payload,
    create_customs_entry_payload,
    create_flight_booking_payload,
    create_house_waybill_payload,
    create_master_waybill_payload,
    create_rate_agreement_payload,
    create_shipper_payload,
    customs_transition_payload,
    measure_payload,
    milestone_payload,
    resolve_review_payload,
    resolve_screening_payload,
    tender_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_forwarder_ops_headers,
)

OPS = TEST_USERS["forwarder_ops_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BROKER = TEST_USERS["customs_broker_headers"]
PRICING = TEST_USERS["pricing_manager_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, OPS))


def create_shipper(name: str = "Acme Exports", account_code: str = "ACME") -> dict:
    return get_success_data(
        api_client.create_shipper(create_shipper_payload(name=name, account_code=account_code), OPS)
    )


def create_known_shipper(name: str = "Acme Exports", account_code: str = "ACME") -> dict:
    """Shipper verified KNOWN by a ComplianceOfficer (PRD §3.1)."""
    shipper = create_shipper(name, account_code)
    return get_success_data(api_client.verify_known_shipper(shipper["id"], COMPLIANCE))


def file_rate_agreement(shipper_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_agreement(
            create_rate_agreement_payload(shipper_id, **overrides), PRICING
        )
    )


def create_booking(**overrides) -> dict:
    return get_success_data(
        api_client.create_flight_booking(create_flight_booking_payload(**overrides), PLANNER)
    )


def get_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_flight_booking(booking_id, OPS))


def create_mawb(booking_id: str, mawb_number: str = "180-12345675") -> dict:
    return get_success_data(
        api_client.create_master_waybill(
            create_master_waybill_payload(booking_id, mawb_number=mawb_number), PLANNER
        )
    )


def get_mawb(mawb_id: str) -> dict:
    return get_success_data(api_client.get_master_waybill(mawb_id, OPS))


def open_mawb(mawb_id: str) -> dict:
    return get_success_data(api_client.open_master_waybill(mawb_id, PLANNER))


def create_open_mawb(booking_id: str, mawb_number: str = "180-12345675") -> dict:
    mawb = create_mawb(booking_id, mawb_number)
    return open_mawb(mawb["id"])


def create_hwb(shipper_id: str, hwb_number: str = "HWB-A", **overrides) -> dict:
    return get_success_data(
        api_client.create_house_waybill(
            create_house_waybill_payload(shipper_id, hwb_number=hwb_number, **overrides), OPS
        )
    )


def get_hwb(hwb_id: str) -> dict:
    return get_success_data(api_client.get_house_waybill(hwb_id, OPS))


def submit_hwb(hwb_id: str, user_id: str = "ops-1") -> dict:
    """Submit to screening; stamps submitted_by_user_id with user_id (PRD §3.3)."""
    return get_success_data(
        api_client.submit_house_waybill(hwb_id, make_forwarder_ops_headers(user_id))
    )


def list_screening_records(hwb_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_screening_records(hwb_id, OPS))
    return data


def resolve_screening(
    record_id: str,
    outcome: str = "CLEARED",
    rejection_reason: str = None,
    user_id: str = "comp-1",
) -> dict:
    """ComplianceOfficer resolves a PENDING record (PRD §3.3)."""
    return get_success_data(
        api_client.resolve_screening_record(
            record_id,
            resolve_screening_payload(outcome, rejection_reason),
            make_compliance_officer_headers(user_id),
        )
    )


def clear_hwb(hwb_id: str, user_id: str = "ops-1") -> dict:
    """Submit and resolve every PENDING record CLEARED; returns the CLEARED waybill."""
    submit_hwb(hwb_id, user_id)
    for record in list_screening_records(hwb_id):
        if record["result"] == "PENDING":
            resolve_screening(record["id"], "CLEARED")
    hwb = get_hwb(hwb_id)
    assert hwb["status"] == "CLEARED", (
        f"Setup failed: waybill {hwb_id} is {hwb['status']}, expected CLEARED"
    )
    return hwb


def consolidate_hwb(mawb_id: str, hwb_id: str) -> dict:
    """OCC-guarded consolidation: reads the current version, then attaches (PRD §2.5, §3.4)."""
    mawb = get_mawb(mawb_id)
    return get_success_data(
        api_client.consolidate_house_waybill(
            mawb_id, consolidate_payload(hwb_id, mawb["version"]), OPS
        )
    )


def deconsolidate_hwb(mawb_id: str, hwb_id: str) -> dict:
    return get_success_data(api_client.deconsolidate_house_waybill(mawb_id, hwb_id, OPS))


def measure_hwb(hwb_id: str, measured_volume_m3: float) -> dict:
    return get_success_data(
        api_client.measure_house_waybill(hwb_id, measure_payload(measured_volume_m3), OPS)
    )


def tender_mawb(
    mawb_id: str,
    start: str = STANDARD_TENDER_WINDOW_START,
    end: str = STANDARD_TENDER_WINDOW_END,
) -> dict:
    return get_success_data(api_client.tender_master_waybill(mawb_id, tender_payload(start, end), PLANNER))


def record_milestone(mawb_id: str, event_code: str, event_time_utc: str, **extra) -> dict:
    return get_success_data(
        api_client.record_milestone_event(
            mawb_id, milestone_payload(event_code, event_time_utc, **extra), OPS
        )
    )


def create_customs_entry(hwb_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_customs_entry(hwb_id, create_customs_entry_payload(**overrides), OPS)
    )


def transition_customs_entry(entry_id: str, target_status: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.transition_customs_entry(
            entry_id, customs_transition_payload(target_status, **overrides), headers
        )
    )


def file_claim(hwb_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_claim(create_claim_payload(hwb_id, **overrides), OPS))


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------

def setup_lane(
    shipper_name: str = "Acme Exports",
    account_code: str = "ACME",
    agreement_overrides: dict = None,
    booking_overrides: dict = None,
    mawb_number: str = "180-12345675",
) -> dict:
    """KNOWN shipper + rate agreement + OPEN booking + OPEN_FOR_CONSOLIDATION MAWB."""
    shipper = create_known_shipper(shipper_name, account_code)
    agreement = file_rate_agreement(shipper["id"], **(agreement_overrides or {}))
    booking = create_booking(**(booking_overrides or {}))
    mawb = create_open_mawb(booking["id"], mawb_number)
    return {"shipper": shipper, "agreement": agreement, "booking": booking, "mawb": mawb}


def setup_cleared_hwb(
    hwb_number: str = "HWB-A",
    hwb_overrides: dict = None,
    **lane_kwargs,
) -> dict:
    """Lane fixture plus one screening-CLEARED waybill (not yet consolidated)."""
    ctx = setup_lane(**lane_kwargs)
    hwb = create_hwb(ctx["shipper"]["id"], hwb_number, **(hwb_overrides or {}))
    ctx["hwb"] = clear_hwb(hwb["id"])
    return ctx


def setup_consolidated(
    hwb_number: str = "HWB-A",
    hwb_overrides: dict = None,
    **lane_kwargs,
) -> dict:
    """Lane fixture plus one waybill consolidated into the open MAWB (QUOTED rated)."""
    ctx = setup_lane(**lane_kwargs)
    hwb = create_hwb(ctx["shipper"]["id"], hwb_number, **(hwb_overrides or {}))
    clear_hwb(hwb["id"])
    ctx["hwb"] = consolidate_hwb(ctx["mawb"]["id"], hwb["id"])
    return ctx


def setup_tendered(
    hwb_number: str = "HWB-A",
    hwb_overrides: dict = None,
    measured_volume_m3: float = None,
    tender_window: tuple = None,
    **lane_kwargs,
) -> dict:
    """Consolidated waybill, measured, then the MAWB tendered (FINAL re-rate)."""
    ctx = setup_consolidated(hwb_number, hwb_overrides, **lane_kwargs)
    measured = (
        measured_volume_m3
        if measured_volume_m3 is not None
        else ctx["hwb"]["declared_volume_m3"]
    )
    measure_hwb(ctx["hwb"]["id"], measured)
    window = tender_window or (STANDARD_TENDER_WINDOW_START, STANDARD_TENDER_WINDOW_END)
    ctx["mawb"] = tender_mawb(ctx["mawb"]["id"], *window)
    return ctx


def setup_delivered(
    hwb_specs: list = None,
    measured_volumes: dict = None,
    **lane_kwargs,
) -> dict:
    """Full chain through DELIVERED.

    hwb_specs: list of (hwb_number, overrides) tuples. Each waybill is created,
    cleared, consolidated, measured (default: at its declared volume), flown via
    the standard DEPARTED/ARRIVED/DELIVERED milestone timeline.
    Returns the lane context plus "hwbs" (post-delivery reads) and "hwb" (first).
    """
    specs = hwb_specs or [("HWB-A", {})]
    measured_volumes = measured_volumes or {}
    ctx = setup_lane(**lane_kwargs)
    rated_hwbs = []
    for number, overrides in specs:
        hwb = create_hwb(ctx["shipper"]["id"], number, **overrides)
        clear_hwb(hwb["id"])
        rated_hwbs.append(consolidate_hwb(ctx["mawb"]["id"], hwb["id"]))
    for rated in rated_hwbs:
        measure_hwb(
            rated["id"],
            measured_volumes.get(rated["hwb_number"], rated["declared_volume_m3"]),
        )
    ctx["mawb"] = tender_mawb(ctx["mawb"]["id"])
    record_milestone(ctx["mawb"]["id"], "DEPARTED", MILESTONE_DEPARTED_UTC)
    record_milestone(ctx["mawb"]["id"], "ARRIVED", MILESTONE_ARRIVED_UTC)
    record_milestone(ctx["mawb"]["id"], "DELIVERED", MILESTONE_DELIVERED_UTC)
    ctx["hwbs"] = [get_hwb(h["id"]) for h in rated_hwbs]
    ctx["hwb"] = ctx["hwbs"][0]
    return ctx


def setup_delivered_claim(claim_overrides: dict = None, **delivered_kwargs) -> dict:
    """Delivered waybill plus one FILED claim, clock inside the filing window."""
    ctx = setup_delivered(**delivered_kwargs)
    set_clock(CLAIM_FILING_CLOCK_UTC)
    ctx["claim"] = file_claim(ctx["hwb"]["id"], **(claim_overrides or {}))
    return ctx


def drive_shipper_to_suspended(
    shipper_id: str, count: int = DEMERIT_LIMIT, number_prefix: str = "HWB-R"
) -> list:
    """Reject `count` waybills' security screenings, driving the demerit counter.

    Returns the list of rejected waybill ids. At the inclusive limit a KNOWN
    shipper flips to SUSPENDED (PRD §3.3).
    """
    rejected_ids = []
    for i in range(1, count + 1):
        hwb = create_hwb(
            shipper_id,
            f"{number_prefix}{i}",
            pieces=1,
            gross_weight_kg=10.0,
            declared_volume_m3=0.05,
            dg_flag=False,
        )
        submit_hwb(hwb["id"])
        record = list_screening_records(hwb["id"])[0]
        resolve_screening(record["id"], "REJECTED", rejection_reason="x-ray alarm")
        rejected_ids.append(hwb["id"])
    return rejected_ids
