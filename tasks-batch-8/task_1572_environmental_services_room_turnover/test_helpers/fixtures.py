"""Composite setup helpers for the EVS API tests.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints; the runner restarts the server (empty DB) before every test.
Fixtures use get_success_data() internally so setup failures surface as
clear errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    STANDARD_FIXTURES,
    SUPPLY_FIXTURES,
    CLOCK_T0800,
)
from .factories import (
    create_unit_payload,
    create_bed_payload,
    create_clean_request_payload,
    create_staff_payload,
    create_supply_item_payload,
    create_clean_standard_payload,
    create_placement_demand_payload,
    create_outbreak_event_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_auditor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + base facility
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_T0800):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_unit(unit_code: str = "U1", display_name: str = "Unit One") -> dict:
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(unit_code=unit_code, display_name=display_name), ADMIN
        )
    )


def create_standard(clean_type: str, **overrides) -> dict:
    spec = dict(STANDARD_FIXTURES[clean_type])
    spec.update(overrides)
    return get_success_data(
        api_client.create_clean_standard(
            create_clean_standard_payload(clean_type=clean_type, **spec), ADMIN
        )
    )


def create_all_standards() -> dict:
    """Create ROUTINE/ISOLATION/TERMINAL standard rows. Returns {type: row}."""
    return {ct: create_standard(ct) for ct in ("ROUTINE", "ISOLATION", "TERMINAL")}


def create_supply(item_code: str, **overrides) -> dict:
    spec = dict(SUPPLY_FIXTURES[item_code])
    spec.update(overrides)
    return get_success_data(
        api_client.create_supply_item(
            create_supply_item_payload(item_code=item_code, **spec), ADMIN
        )
    )


def seed_supplies(*item_codes) -> dict:
    """Create the given supply items (default: all four). Returns {code: row}."""
    codes = item_codes or ("DISINFECTANT", "PPE_PACK", "CLOTH", "SEALANT")
    return {c: create_supply(c) for c in codes}


def create_bed(unit_id: str, bed_code: str = "B1", bed_kind: str = "STANDARD") -> dict:
    return get_success_data(
        api_client.create_bed(
            create_bed_payload(unit_id=unit_id, bed_code=bed_code, bed_kind=bed_kind),
            ADMIN,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: staff + shift state
# ---------------------------------------------------------------------------

def create_staff(
    employee_code: str = "T1",
    capabilities=("CLEAN",),
    certifications=(),
    display_name: str = "Tech One",
) -> dict:
    return get_success_data(
        api_client.create_staff(
            create_staff_payload(
                employee_code=employee_code,
                display_name=display_name,
                capabilities=list(capabilities),
                certifications=list(certifications),
            ),
            ADMIN,
        )
    )


def create_technician(employee_code: str = "T1", certifications=(), **kw) -> dict:
    return create_staff(
        employee_code=employee_code,
        capabilities=("CLEAN",),
        certifications=certifications,
        **kw,
    )


def create_auditor(employee_code: str = "A1", **kw) -> dict:
    return create_staff(
        employee_code=employee_code,
        capabilities=("AUDIT",),
        certifications=(),
        display_name=kw.pop("display_name", "Auditor One"),
        **kw,
    )


def clock_in(staff_id: str):
    return get_success_data(
        api_client.clock_in_staff(staff_id, make_technician_headers(staff_id))
    )


def clock_out(staff_id: str):
    return get_success_data(
        api_client.clock_out_staff(staff_id, make_technician_headers(staff_id))
    )


def break_start(staff_id: str):
    return get_success_data(
        api_client.break_start_staff(staff_id, make_technician_headers(staff_id))
    )


def break_end(staff_id: str):
    return get_success_data(
        api_client.break_end_staff(staff_id, make_technician_headers(staff_id))
    )


def create_on_shift_technician(employee_code: str = "T1", certifications=()) -> dict:
    tech = create_technician(employee_code=employee_code, certifications=certifications)
    clock_in(tech["id"])
    return tech


# ---------------------------------------------------------------------------
# Tier 2: clean requests through lifecycle stages
# ---------------------------------------------------------------------------

def create_request(bed_id: str, clean_type: str = "ROUTINE") -> dict:
    return get_success_data(
        api_client.create_clean_request(
            create_clean_request_payload(bed_id=bed_id, clean_type=clean_type),
            DISPATCHER,
        )
    )


def assign_request(request_id: str, staff_id: str, planned_start_at=None) -> dict:
    payload = {"staff_id": staff_id}
    if planned_start_at is not None:
        payload["planned_start_at"] = planned_start_at
    return get_success_data(
        api_client.assign_clean_request(request_id, payload, DISPATCHER)
    )


def start_request(request_id: str, staff_id: str) -> dict:
    return get_success_data(
        api_client.start_clean_request(request_id, make_technician_headers(staff_id))
    )


def complete_request(request_id: str, staff_id: str) -> dict:
    return get_success_data(
        api_client.complete_clean_request(request_id, make_technician_headers(staff_id))
    )


def submit_audit(
    clean_request_id: str,
    auditor_id: str,
    audit_method: str = "ATP_SWAB",
    rlu_reading=None,
    marker_fraction_removed=None,
) -> dict:
    payload = {"clean_request_id": clean_request_id, "audit_method": audit_method}
    if rlu_reading is not None:
        payload["rlu_reading"] = rlu_reading
    if marker_fraction_removed is not None:
        payload["marker_fraction_removed"] = marker_fraction_removed
    return get_success_data(
        api_client.create_quality_audit(payload, make_auditor_headers(auditor_id))
    )


def setup_basic_scenario():
    """Clock 08:00 + unit + all standards + all supplies + on-shift tech +
    auditor + one STANDARD bed. Returns a dict of the pieces."""
    set_clock(CLOCK_T0800)
    unit = create_unit()
    standards = create_all_standards()
    supplies = seed_supplies()
    tech = create_on_shift_technician("T1")
    auditor = create_auditor("A1")
    bed = create_bed(unit["id"], "B1", "STANDARD")
    return {
        "unit": unit,
        "standards": standards,
        "supplies": supplies,
        "tech": tech,
        "auditor": auditor,
        "bed": bed,
    }


def create_request_in_state(
    bed_id: str,
    tech_id: str,
    clean_type: str = "ROUTINE",
    target_state: str = "ASSIGNED",
    auditor_id: str = None,
    pass_rlu: int = 100,
    fail_rlu: int = None,
    planned_start_at=None,
) -> dict:
    """Walk a request from QUEUED up to the requested state.

    target_state one of: QUEUED, ASSIGNED, IN_PROGRESS, PENDING_QA,
    NEEDS_RECLEAN, VERIFIED. For NEEDS_RECLEAN a FAIL audit (fail_rlu) is
    submitted; for VERIFIED a PASS audit (pass_rlu) is submitted.
    """
    req = create_request(bed_id, clean_type)
    if target_state == "QUEUED":
        return req
    req = assign_request(req["id"], tech_id, planned_start_at=planned_start_at)
    if target_state == "ASSIGNED":
        return req
    req = start_request(req["id"], tech_id)
    if target_state == "IN_PROGRESS":
        return req
    req = complete_request(req["id"], tech_id)
    if target_state == "PENDING_QA":
        return req
    if target_state == "NEEDS_RECLEAN":
        submit_audit(
            req["id"], auditor_id, rlu_reading=(fail_rlu if fail_rlu is not None else 99999)
        )
        return get_success_data(api_client.get_clean_request(req["id"], ANY))
    if target_state == "VERIFIED":
        submit_audit(req["id"], auditor_id, rlu_reading=pass_rlu)
        return get_success_data(api_client.get_clean_request(req["id"], ANY))
    raise ValueError(f"unsupported target_state {target_state}")


def setup_verified_clean(
    clean_type: str = "ROUTINE",
    bed_kind: str = "STANDARD",
    pass_rlu: int = 100,
    start_clock: str = None,
    complete_clock: str = None,
):
    """Full happy path: request -> assign -> start -> complete -> PASS audit.

    Returns dict with unit/bed/request/tech/auditor and the verified request.
    Bed is READY afterwards (unmatched unless a demand existed).
    """
    ctx = setup_basic_scenario()
    req = create_request(ctx["bed"]["id"], clean_type)
    assign_request(req["id"], ctx["tech"]["id"])
    if start_clock:
        set_clock(start_clock)
    start_request(req["id"], ctx["tech"]["id"])
    if complete_clock:
        set_clock(complete_clock)
    complete_request(req["id"], ctx["tech"]["id"])
    submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=pass_rlu)
    verified = get_success_data(api_client.get_clean_request(req["id"], ANY))
    ctx["request"] = verified
    return ctx


def setup_ready_bed_with_match(
    urgency_tier: str = "URGENT",
    needed_by: str = "2026-08-01T20:00:00Z",
    required_bed_kind: str = "STANDARD",
    pass_rlu: int = 100,
):
    """Unit + standards + supplies + tech + auditor + bed + OPEN demand, then a
    verified clean so the bed goes READY and the demand is MATCHED with a SENT
    notification. Returns ctx including demand and notification."""
    ctx = setup_basic_scenario()
    demand = get_success_data(
        api_client.create_placement_demand(
            create_placement_demand_payload(
                unit_id=ctx["unit"]["id"],
                required_bed_kind=required_bed_kind,
                urgency_tier=urgency_tier,
                needed_by=needed_by,
            ),
            COORDINATOR,
        )
    )
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])
    start_request(req["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], ctx["tech"]["id"])
    submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=pass_rlu)
    notifications, _meta = _list_notifications(ctx["bed"]["id"])
    ctx["request"] = get_success_data(api_client.get_clean_request(req["id"], ANY))
    ctx["demand"] = get_success_data(
        api_client.get_placement_demand(demand["id"], ANY)
    )
    ctx["notification"] = notifications[0] if notifications else None
    return ctx


def _list_notifications(bed_id=None, status=None):
    params = {}
    if bed_id:
        params["bed_id"] = bed_id
    if status:
        params["status"] = status
    resp = api_client.list_bed_ready_notifications(ANY, params=params)
    body = resp.json()
    return body["data"], body["meta"]


def setup_needs_reclean(pass_setup=True):
    """Drive a ROUTINE request to NEEDS_RECLEAN via a FAIL audit (rlu 300 > 250).

    Returns ctx with unit/bed/request/tech/auditor and audit_id.
    """
    ctx = setup_basic_scenario()
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])
    start_request(req["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], ctx["tech"]["id"])
    audit = submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=300)
    ctx["request"] = get_success_data(api_client.get_clean_request(req["id"], ANY))
    ctx["audit"] = audit
    return ctx


def setup_outbreak_active(unit_id: str, pathogen_class: str = "C_DIFF") -> dict:
    """Declare + activate an outbreak on the unit. Returns the ACTIVE event."""
    event = get_success_data(
        api_client.create_outbreak_event(
            create_outbreak_event_payload(
                unit_id=unit_id, pathogen_class=pathogen_class
            ),
            IP,
        )
    )
    return get_success_data(api_client.activate_outbreak_event(event["id"], IP))


def list_requests(params: dict):
    resp = api_client.list_clean_requests(ANY, params=params)
    body = resp.json()
    return body["data"], body["meta"]


def list_ledger_entries(params: dict):
    resp = api_client.list_supply_ledger_entries(ANY, params=params)
    body = resp.json()
    return body["data"], body["meta"]


def get_request(request_id: str) -> dict:
    return get_success_data(api_client.get_clean_request(request_id, ANY))


def get_bed(bed_id: str) -> dict:
    return get_success_data(api_client.get_bed(bed_id, ANY))


def get_staff(staff_id: str) -> dict:
    return get_success_data(api_client.get_staff(staff_id, ANY))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, ANY))


def get_supply_item(item_id: str) -> dict:
    return get_success_data(api_client.get_supply_item(item_id, ANY))
