"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" error rather than a confusing assertion failure.

The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD §2.5); helpers
never move it unless the test asks for it explicitly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bus_payload,
    create_campaign_payload,
    create_certification_payload,
    create_claim_payload,
    create_defect_payload,
    create_inspection_payload,
    create_mechanic_payload,
    create_mileage_log_payload,
    create_part_line_payload,
    create_part_payload,
    create_pm_policy_payload,
    create_shift_assignment_payload,
    create_shift_payload,
    create_work_order_payload,
    labor_entry_payload,
)
from .test_users import TEST_USERS, make_mechanic_headers

FM = TEST_USERS["fleet_manager_headers"]
SUP = TEST_USERS["supervisor_headers"]
OP = TEST_USERS["operator_headers"]
PC = TEST_USERS["parts_clerk_headers"]
WC = TEST_USERS["warranty_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators
# ---------------------------------------------------------------------------

def new_bus(**overrides):
    """Register a bus. Returns the created Bus dict."""
    return get_success_data(api_client.create_bus(create_bus_payload(**overrides), FM))


def new_buses(n, model_year=2023, **overrides):
    """Register n buses with distinct fleet numbers/VINs. Returns list."""
    fleet_prefix = overrides.pop("fleet_prefix", "FL")
    vin_prefix = overrides.pop("vin_prefix", f"VIN-{fleet_prefix}")
    buses = []
    for i in range(n):
        buses.append(
            new_bus(
                fleet_number=f"{fleet_prefix}{i + 1:03d}",
                vin=f"{vin_prefix}{i + 1:03d}",
                model_year=model_year,
                **overrides,
            )
        )
    return buses


def new_pm_policy(**overrides):
    return get_success_data(
        api_client.create_pm_policy(create_pm_policy_payload(**overrides), FM)
    )


def new_mechanic(**overrides):
    return get_success_data(
        api_client.create_mechanic(create_mechanic_payload(**overrides), SUP)
    )


def grant_cert(mechanic_id, cert_type, issued_date="2026-01-01", expiry_date="2027-01-01"):
    return get_success_data(
        api_client.create_certification(
            mechanic_id,
            create_certification_payload(
                cert_type=cert_type, issued_date=issued_date, expiry_date=expiry_date
            ),
            SUP,
        )
    )


def new_mechanic_with_certs(*cert_types, name=None):
    """Create a mechanic holding the given certs (all VALID at grant)."""
    mech = new_mechanic(**({"name": name} if name else {}))
    for ct in cert_types:
        grant_cert(mech["id"], ct)
    return mech


def new_qa_mechanic(name="QA Reviewer"):
    """Mechanic holding QA_AUTHORITY (the QA gate cert)."""
    return new_mechanic_with_certs("QA_AUTHORITY", name=name)


def new_part(**overrides):
    return get_success_data(api_client.create_part(create_part_payload(**overrides), PC))


def bus_version(bus_id):
    return get_success_data(api_client.get_bus(bus_id, SUP))["version"]


def wo_version(wo_id):
    return get_success_data(api_client.get_work_order(wo_id, SUP))["version"]


# ---------------------------------------------------------------------------
# Tier 1: work-order state progression
# ---------------------------------------------------------------------------

def new_work_order(bus_id, **overrides):
    """Create a DRAFT work order; re-reads the bus for a fresh OCC version."""
    payload = create_work_order_payload(bus_id, bus_version(bus_id), **overrides)
    return get_success_data(api_client.create_work_order(payload, SUP))


def wo_event(wo_id, event_type, headers=None, **payload):
    body = {"event_type": event_type}
    body.update(payload)
    return api_client.work_order_event(wo_id, body, headers or SUP)


def schedule_wo(wo_id):
    return get_success_data(wo_event(wo_id, "SCHEDULE"))


def start_wo(wo_id):
    return get_success_data(wo_event(wo_id, "START"))


def assign_lead(wo_id, mechanic_id):
    return get_success_data(wo_event(wo_id, "ASSIGN", lead_mechanic_id=mechanic_id))


def add_labor(wo_id, mechanic, work_date="2026-08-02", shift_type="AM", hours=1):
    """Append a labor entry as the lead mechanic (entity-backed ownership)."""
    return get_success_data(
        api_client.add_labor_entry(
            wo_id,
            labor_entry_payload(work_date=work_date, shift_type=shift_type, hours=hours),
            make_mechanic_headers(mechanic["id"]),
        )
    )


def reserve_line(wo_id, part_id, qty=1):
    return get_success_data(
        api_client.create_part_line(wo_id, create_part_line_payload(part_id, qty=qty), PC)
    )


def line_event(line_id, event_type, headers=None, **payload):
    body = {"event_type": event_type}
    body.update(payload)
    return api_client.part_line_event(line_id, body, headers or PC)


def issue_line(line_id, mechanic=None):
    """ISSUE a line; defaults to PartsClerk (allowed issuer per PRD §3.6)."""
    headers = make_mechanic_headers(mechanic["id"]) if mechanic else PC
    return get_success_data(line_event(line_id, "ISSUE", headers=headers))


def create_scheduled_wo(bus_id, **overrides):
    """DRAFT -> SCHEDULED. Returns the SCHEDULED work order."""
    wo = new_work_order(bus_id, **overrides)
    return get_success_data(api_client.get_work_order(schedule_wo(wo["id"])["id"], SUP))


def create_in_progress_wo(bus_id, lead, **overrides):
    """Create -> SCHEDULE -> START. Lead is assigned at create. Returns WO."""
    overrides.setdefault("lead_mechanic_id", lead["id"])
    wo = create_scheduled_wo(bus_id, **overrides)
    return start_wo(wo["id"])


def create_pending_qa_wo(bus_id, lead, labor_entries=None, **overrides):
    """Create -> SCHEDULE -> START -> labor -> SUBMIT_QA. Returns WO in PENDING_QA."""
    wo = create_in_progress_wo(bus_id, lead, **overrides)
    for entry in labor_entries or [{"hours": 1, "shift_type": "AM"}]:
        add_labor(wo["id"], lead, **entry)
    return get_success_data(
        wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    )


def create_closed_wo(bus_id, lead, qa, labor_entries=None, **overrides):
    """Full lifecycle through QA_CERTIFY. Returns the CLOSED work order."""
    wo = create_pending_qa_wo(bus_id, lead, labor_entries=labor_entries, **overrides)
    return get_success_data(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 2: mileage logs, defects, holds
# ---------------------------------------------------------------------------

def post_log(bus_id, log_date, odometer_end, fuel_gallons):
    return get_success_data(
        api_client.create_mileage_fuel_log(
            create_mileage_log_payload(
                bus_id, log_date=log_date, odometer_end=odometer_end,
                fuel_gallons=fuel_gallons,
            ),
            OP,
        )
    )


def file_defect(bus_id, severity="MINOR", defect_code="OTHER", description="defect",
                odometer_at_report=10_000):
    return get_success_data(
        api_client.create_defect_report(
            create_defect_payload(
                bus_id,
                severity=severity,
                defect_code=defect_code,
                description=description,
                odometer_at_report=odometer_at_report,
            ),
            OP,
        )
    )


def file_safety_defect(bus_id, defect_code="BRAKES", description="safety"):
    """SAFETY_CRITICAL defect -> bus HELD with SAFETY hold (PRD §3.8)."""
    return file_defect(
        bus_id, severity="SAFETY_CRITICAL", defect_code=defect_code,
        description=description,
    )


def defect_event(defect_id, event_type, headers=None, **payload):
    body = {"event_type": event_type}
    body.update(payload)
    return api_client.defect_event(defect_id, body, headers or SUP)


# ---------------------------------------------------------------------------
# Tier 3: fleet posture scenarios
# ---------------------------------------------------------------------------

def setup_fleet_with_holds(n_buses, n_holds, model_year=2021, **bus_overrides):
    """n_buses ACTIVE buses; SAFETY_CRITICAL defects hold the first n_holds.
    Returns (buses, defects)."""
    defaults = dict(
        in_service_date="2026-01-01",
        initial_odometer_miles=10_000,
        base_warranty_expiry_miles=200_000,
        base_warranty_expiry_date="2028-01-01",
    )
    defaults.update(bus_overrides)
    buses = new_buses(n_buses, model_year=model_year, **defaults)
    defects = [file_safety_defect(b["id"]) for b in buses[:n_holds]]
    return buses, defects


def get_posture_data():
    return get_success_data(api_client.get_posture(FM))


# ---------------------------------------------------------------------------
# Tier 4: clock / epoch, shifts, campaigns, inspections
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, FM))


def run_epoch():
    return get_success_data(api_client.run_epoch(FM))


def new_shift(shift_date="2026-08-10", shift_type="AM", required_headcount=None):
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(
                shift_date=shift_date,
                shift_type=shift_type,
                required_headcount=required_headcount or {},
            ),
            SUP,
        )
    )


def publish_shift(shift_id):
    return get_success_data(api_client.publish_shift(shift_id, SUP))


def new_published_shift(shift_date="2026-08-10", shift_type="AM", required_headcount=None):
    shift = new_shift(shift_date, shift_type, required_headcount)
    return publish_shift(shift["id"])


def assign_mechanic(shift_id, mechanic_id, role_in_shift="TECH"):
    return get_success_data(
        api_client.create_shift_assignment(
            shift_id,
            create_shift_assignment_payload(mechanic_id, role_in_shift=role_in_shift),
            SUP,
        )
    )


def confirm_assignment(assignment_id, mechanic_id):
    """CONFIRM as the mechanic themselves (self-confirm, PRD §3.12)."""
    return get_success_data(
        api_client.shift_assignment_event(
            assignment_id, {"event_type": "CONFIRM"}, make_mechanic_headers(mechanic_id)
        )
    )


def new_campaign(**overrides):
    return get_success_data(
        api_client.create_campaign(create_campaign_payload(**overrides), FM)
    )


def campaign_event(campaign_id, event_type):
    return api_client.campaign_event(campaign_id, {"event_type": event_type}, FM)


def activate_campaign(campaign_id):
    return get_success_data(campaign_event(campaign_id, "ACTIVATE"))


def record_inspection(bus_id, test_type="OBD", test_date="2026-08-01", result="PASS",
                      **overrides):
    payload = create_inspection_payload(
        bus_id, test_type=test_type, test_date=test_date, result=result, **overrides
    )
    if result == "FAIL":
        payload.pop("certificate_expiry_date", None)
    return get_success_data(api_client.create_emissions_inspection(payload, SUP))


def get_inspection_auto_wo(inspection_id):
    """The single auto-created EMISSIONS work order for a FAIL inspection."""
    wos = get_success_data(api_client.list_inspection_work_orders(inspection_id, SUP))
    assert len(wos) == 1, f"expected exactly one auto WO, got {len(wos)}"
    return wos[0]


# ---------------------------------------------------------------------------
# Tier 5: warranty claims
# ---------------------------------------------------------------------------

def create_claim(wo_id, claim_type="BASE_OEM", headers=None, **overrides):
    """Create a DRAFT claim; re-reads the work order for a fresh OCC version."""
    payload = create_claim_payload(wo_id, wo_version(wo_id), claim_type=claim_type,
                                   **overrides)
    return get_success_data(api_client.create_warranty_claim(payload, headers or WC))


def claim_event(claim_id, event_type, headers=None, **payload):
    body = {"event_type": event_type}
    body.update(payload)
    return api_client.warranty_claim_event(claim_id, body, headers or WC)


def get_wo_claims(wo_id):
    return get_success_data(api_client.list_wo_warranty_claims(wo_id, WC))


def setup_approved_claim(labor_hours=1, part=None, submitter_id="clerk-9"):
    """Bus inside base warranty -> closed labor WO -> auto claim -> SUBMIT ->
    APPROVED. Returns (bus, wo, claim) with claim APPROVED for its claimed
    amount. Claim is submitted by `submitter_id` (opaque clerk id)."""
    bus = new_bus(initial_odometer_miles=50_000, base_warranty_expiry_miles=100_000,
                  base_warranty_expiry_date="2027-01-01")
    lead = new_mechanic()
    qa = new_qa_mechanic()
    wo = new_work_order(bus["id"], lead_mechanic_id=lead["id"])
    schedule_wo(wo["id"])
    start_wo(wo["id"])
    if part is not None:
        line = reserve_line(wo["id"], part["id"], qty=1)
        issue_line(line["id"])
        line_event(line["id"], "CONSUME")
    add_labor(wo["id"], lead, hours=labor_hours)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    claims = get_wo_claims(wo["id"])
    assert len(claims) == 1, f"expected one auto-created claim, got {len(claims)}"
    claim = claims[0]
    claim = get_success_data(
        claim_event(claim["id"], "SUBMIT", headers=_wc(submitter_id))
    )
    claim = get_success_data(
        claim_event(
            claim["id"],
            "RECORD_OEM_DECISION",
            headers=_wc(submitter_id),
            decision_outcome="APPROVED",
            oem_reference="OEM-77",
        )
    )
    return bus, wo, claim


def _wc(user_id):
    from .test_users import make_warranty_clerk_headers

    return make_warranty_clerk_headers(user_id)


# ---------------------------------------------------------------------------
# Composite lifecycle scenarios
# ---------------------------------------------------------------------------

def setup_closed_wo_scenario(bus_overrides=None, part=None, part_qty=1,
                             labor_entries=None, wo_overrides=None):
    """Bus + lead mechanic + QA mechanic + a CLOSED CORRECTIVE work order.

    If `part` is given, one line of `part_qty` units is reserved, issued, and
    consumed before close. Returns (bus, closed_wo).
    """
    bus = new_bus(**(bus_overrides or {}))
    lead = new_mechanic()
    qa = new_qa_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, **(wo_overrides or {}))
    if part is not None:
        line = reserve_line(wo["id"], part["id"], qty=part_qty)
        issue_line(line["id"])
        get_success_data(line_event(line["id"], "CONSUME"))
    for entry in (labor_entries or [{"hours": 1, "shift_type": "AM"}]):
        add_labor(wo["id"], lead, **entry)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    wo = get_success_data(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )
    return bus, wo


def close_campaign_wo(bus_id, campaign_id, lead, qa, labor_hours=2, **wo_overrides):
    """Create -> schedule -> start -> labor -> QA close a CAMPAIGN work order."""
    wo = create_in_progress_wo(
        bus_id, lead, wo_type="CAMPAIGN", campaign_id=campaign_id, **wo_overrides
    )
    add_labor(wo["id"], lead, hours=labor_hours)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    return get_success_data(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )
