"""Composite setup helpers.

The travel-nurse platform reaches most interesting states only after a long
chain of calls: clock -> per-diem -> facility -> clinician -> verified license
-> assignment (which also mints a DRAFT contract + DRAFT packet) -> five verified
credential items -> packet review/clearance -> contract signature/execution ->
activation. These helpers encapsulate that chain so tests focus on assertions.

Every helper uses get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" instead of a confusing assertion error. Ownership-gated
calls thread the real entity id through make_<role>_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_per_diem_locality_payload, create_facility_payload, create_clinician_payload,
    create_license_payload, create_assignment_payload, create_credential_item_payload,
)
from .test_users import (
    TEST_USERS, make_clinician_headers, make_facility_manager_headers,
    make_credentialing_specialist_headers, make_recruiter_headers,
)
from .types import REQUIRED_CREDENTIAL_TYPES

PLATFORM = TEST_USERS["platform_admin_headers"]
RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]
CS2 = TEST_USERS["credentialing_specialist_2_headers"]
PAYROLL1 = TEST_USERS["payroll_admin_headers"]


# --------------------------------------------------------------------------
# Low-level primitives
# --------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, PLATFORM))


def create_per_diem(api, **overrides):
    return get_success_data(api.create_per_diem_locality(create_per_diem_locality_payload(**overrides), PLATFORM))


def create_facility(api, **overrides):
    return get_success_data(api.create_facility(create_facility_payload(**overrides), PLATFORM))


def create_clinician(api, **overrides):
    return get_success_data(api.create_clinician(create_clinician_payload(**overrides), RECRUITER))


def create_verified_license(api, clinician_id, verify=True, **overrides):
    lic = get_success_data(api.create_license(create_license_payload(clinician_id, **overrides), RECRUITER))
    if verify:
        lic = get_success_data(api.transition_license(lic["id"], "VERIFIED", CS1))
    return lic


def create_assignment_bundle(api, clinician_id, facility_id, **overrides):
    """Create an assignment; return (assignment, contract, packet) fresh objects."""
    asg = get_success_data(api.create_assignment(
        create_assignment_payload(clinician_id, facility_id, **overrides), RECRUITER))
    contracts, _ = _list(api.list_assignment_contracts(asg["id"], RECRUITER))
    packets, _ = _list(api.list_assignment_credential_packets(asg["id"], RECRUITER))
    return asg, contracts[0], packets[0]


def add_required_items(api, packet_id, item_expiries=None, verify=True):
    """Attach the five required credential items to a packet; verify them by default.
    item_expiries maps item_type -> expires_on (default 2027-12-31 for all)."""
    item_expiries = item_expiries or {}
    items = {}
    for t in REQUIRED_CREDENTIAL_TYPES:
        exp = item_expiries.get(t, "2027-12-31")
        it = get_success_data(api.create_credential_item(
            packet_id, create_credential_item_payload(t, document_ref=f"doc-{t.lower()}", expires_on=exp), CS1))
        items[t] = it
    if verify:
        for t in REQUIRED_CREDENTIAL_TYPES:
            get_success_data(api.transition_credential_item(items[t]["id"], "VERIFIED", CS1))
    return items


def submit_packet(api, packet_id, submitter_headers=CS1):
    return get_success_data(api.transition_credential_packet(packet_id, "SUBMITTED", submitter_headers))


def review_packet(api, packet_id):
    return get_success_data(api.transition_credential_packet(packet_id, "UNDER_REVIEW", CS1))


def clear_packet(api, packet_id, clearer_headers=CS2):
    return get_success_data(api.transition_credential_packet(packet_id, "CLEARED", clearer_headers))


def send_contract(api, contract_id):
    return get_success_data(api.transition_contract(contract_id, {"to": "SENT_FOR_SIGNATURE"}, RECRUITER))


def execute_contract(api, contract_id, clinician_id):
    return get_success_data(api.transition_contract(
        contract_id, {"to": "FULLY_EXECUTED"}, make_clinician_headers(clinician_id)))


def activate(api, assignment_id):
    return get_success_data(api.activate_assignment(assignment_id, RECRUITER))


def approve_timesheet(api, timesheet_id, facility_id):
    return get_success_data(api.transition_timesheet(
        timesheet_id, {"to": "APPROVED"}, make_facility_manager_headers(facility_id)))


def submit_timesheet(api, assignment_id, week_start_date, daily_hours, clinician_id, callback_hours=0):
    from .factories import create_timesheet_payload
    return get_success_data(api.create_timesheet(
        create_timesheet_payload(assignment_id, week_start_date, daily_hours, callback_hours),
        make_clinician_headers(clinician_id)))


# --- read helpers ---
def _list(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


def get_assignment_data(api, assignment_id, headers=RECRUITER):
    return get_success_data(api.get_assignment(assignment_id, headers))


def get_packet_data(api, packet_id, headers=CS1):
    return get_success_data(api.get_credential_packet(packet_id, headers))


def get_clinician_data(api, clinician_id, headers=RECRUITER):
    return get_success_data(api.get_clinician(clinician_id, headers))


def statements_for_assignment(api, assignment_id, headers=PAYROLL1):
    data, meta = _list(api.list_earnings_statements(headers, params={"assignment_id": assignment_id}))
    return data, meta


def statement_for_timesheet(api, timesheet_id, headers=PAYROLL1):
    data, _ = _list(api.list_earnings_statements(headers, params={"timesheet_id": timesheet_id}))
    return data[0] if data else None


# --------------------------------------------------------------------------
# Composite provisioner
# --------------------------------------------------------------------------
class Ctx(dict):
    """Attribute-accessible context dict returned by provision().

    Stored keys are mirrored into the instance __dict__ so attribute access
    resolves to the stored value even when the key name collides with a built-in
    dict method (e.g. ``items``). Instance attributes shadow class methods, which
    a plain ``__getattr__`` (only invoked on lookup failure) cannot.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__dict__.update(self)

    __getattr__ = dict.get


def provision(api, *, clock=None, per_diems=None, facility_overrides=None,
              clinician_overrides=None, license_overrides=None,
              assignment_overrides=None,
              add_items=False, item_expiries=None, verify_items=True,
              packet_stage=None, contract_stage=None, activate_assignment=False,
              submitter_headers=CS1, clearer_headers=CS2):
    """Provision a placement to a requested state.

    packet_stage: None | 'submitted' | 'under_review' | 'cleared'
    contract_stage: None | 'sent' | 'executed'
    activate_assignment: drive PENDING_START -> ACTIVE (needs executed + cleared).

    Returns Ctx with keys: fac_id, clin_id, lic_id, asg_id, con_id, pkt_id, items.
    """
    if clock is not None:
        set_clock(api, clock)

    if per_diems is None:
        per_diems = [{}]  # one default PHX-AZ row
    for pd in per_diems:
        create_per_diem(api, **pd)

    fac = create_facility(api, **(facility_overrides or {}))
    clin = create_clinician(api, **(clinician_overrides or {}))
    lic = create_verified_license(api, clin["id"], **(license_overrides or {}))
    asg, con, pkt = create_assignment_bundle(api, clin["id"], fac["id"], **(assignment_overrides or {}))

    items = {}
    if add_items:
        items = add_required_items(api, pkt["id"], item_expiries=item_expiries, verify=verify_items)

    # Packet review pipeline.
    if packet_stage in ("submitted", "under_review", "cleared"):
        submit_packet(api, pkt["id"], submitter_headers)
    if packet_stage in ("under_review", "cleared"):
        review_packet(api, pkt["id"])
    if packet_stage == "cleared":
        clear_packet(api, pkt["id"], clearer_headers)

    # Contract signature pipeline.
    if contract_stage in ("sent", "executed"):
        send_contract(api, con["id"])
    if contract_stage == "executed":
        execute_contract(api, con["id"], clin["id"])

    if activate_assignment:
        activate(api, asg["id"])

    return Ctx(
        fac_id=fac["id"], clin_id=clin["id"], lic_id=lic["id"],
        asg_id=asg["id"], con_id=con["id"], pkt_id=pkt["id"], items=items,
        facility=fac, clinician=clin, license=lic,
    )


def setup_active_assignment(api, *, clock="2026-06-14", item_expiries=None, **kw):
    """Common shortcut: a fully ACTIVE assignment (staffing ACTIVE, compliance
    CLEARED) with the default 5200/14000/13-week terms. Extra kwargs pass through
    to provision (e.g. clinician_overrides, assignment_overrides, per_diems)."""
    return provision(
        api, clock=clock, add_items=True, verify_items=True, item_expiries=item_expiries,
        packet_stage="cleared", contract_stage="executed", activate_assignment=True, **kw)
