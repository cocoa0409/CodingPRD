"""Composite setup helpers.

Every fixture builds its preconditions from scratch (the server DB is empty at
the start of each test) using only PRD-declared endpoints, and uses the lenient
get_success_data() validator so setup failures produce clear "Setup failed"
errors. Entity-backed role headers are threaded with the actual anchor field
(tech_user_id / customer_user_id) wherever a call is ownership/identity-gated.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_field_tech_headers,
    make_customer_owner_headers,
)
from . import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def create_technician(tech_user_id="tech-1", full_name="Tia Tech",
                      certified_for_reef=None, active=None):
    """Create a Technician on the roster. Returns the Technician dict."""
    payload = f.create_technician_payload(tech_user_id=tech_user_id, full_name=full_name)
    if certified_for_reef is not None:
        payload["certified_for_reef"] = certified_for_reef
    if active is not None:
        payload["active"] = active
    return get_success_data(api_client.create_technician(payload, DISP))


def create_contract(service_tier="BASIC", customer_user_id="owner-1",
                    route_day="MON", customer_name="Acme"):
    """Create a DRAFT contract. Returns the ServiceContract dict."""
    payload = f.create_contract_payload(
        service_tier=service_tier, customer_user_id=customer_user_id,
        route_day=route_day, customer_name=customer_name,
    )
    return get_success_data(api_client.create_contract(payload, AM))


def create_system(contract_id, system_kind="FRESHWATER", nominal_volume_l=200,
                  label="Tank", substrate_displacement_pct=None):
    """Create a PROVISIONING system under a contract. Returns the SystemProfile dict."""
    payload = f.create_system_payload(
        contract_id, system_kind=system_kind, nominal_volume_l=nominal_volume_l, label=label,
    )
    if substrate_displacement_pct is not None:
        payload["substrate_displacement_pct"] = substrate_displacement_pct
    return get_success_data(api_client.create_system(payload, AM))


# ---------------------------------------------------------------------------
# Tier 1: state progression — active contract + active system
# ---------------------------------------------------------------------------
def create_active_contract_with_system(service_tier="BASIC", customer_user_id="owner-1",
                                       system_kind="FRESHWATER", nominal_volume_l=200,
                                       substrate_displacement_pct=None, label="Tank",
                                       route_day="MON"):
    """Create contract + system, activate contract, commission system to ACTIVE.

    Returns dict with keys: contract, system (both freshly fetched after
    commission so version is current).
    """
    contract = create_contract(service_tier=service_tier, customer_user_id=customer_user_id,
                               route_day=route_day)
    system = create_system(contract["id"], system_kind=system_kind,
                           nominal_volume_l=nominal_volume_l, label=label,
                           substrate_displacement_pct=substrate_displacement_pct)
    get_success_data(api_client.activate_contract(contract["id"], AM))
    system = get_success_data(api_client.commission_system(system["id"], AM))
    return {"contract": contract, "system": system}


def setup_active_system_with_tech(service_tier="BASIC", customer_user_id="owner-1",
                                  system_kind="FRESHWATER", nominal_volume_l=200,
                                  substrate_displacement_pct=None,
                                  tech_user_id="tech-1", certified_for_reef=None):
    """Active contract + active system + one technician.

    Returns dict: contract, system, technician.
    """
    tech = create_technician(tech_user_id=tech_user_id, certified_for_reef=certified_for_reef)
    base = create_active_contract_with_system(
        service_tier=service_tier, customer_user_id=customer_user_id,
        system_kind=system_kind, nominal_volume_l=nominal_volume_l,
        substrate_displacement_pct=substrate_displacement_pct,
    )
    base["technician"] = tech
    return base


# ---------------------------------------------------------------------------
# Tier 2/3: visit lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_visit(system_id, technician_id, expected_system_version,
               scheduled_start="2026-02-02T09:00:00Z",
               scheduled_end="2026-02-02T10:00:00Z", **extra):
    """Book a ROUTINE visit. Returns the ServiceVisit dict."""
    payload = f.create_visit_payload(
        system_id, technician_id, expected_system_version,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **extra,
    )
    return get_success_data(api_client.create_visit(payload, DISP))


def create_started_visit(service_tier="BASIC", customer_user_id="owner-1",
                         tech_user_id="tech-1", certified_for_reef=None,
                         system_kind="FRESHWATER", nominal_volume_l=200,
                         substrate_displacement_pct=None,
                         scheduled_start="2026-02-02T09:00:00Z",
                         scheduled_end="2026-02-02T10:00:00Z"):
    """Full chain: active system + tech + booked visit + started (IN_PROGRESS).

    Returns dict: contract, system, technician, visit (IN_PROGRESS).
    """
    base = setup_active_system_with_tech(
        service_tier=service_tier, customer_user_id=customer_user_id,
        tech_user_id=tech_user_id, certified_for_reef=certified_for_reef,
        system_kind=system_kind, nominal_volume_l=nominal_volume_l,
        substrate_displacement_pct=substrate_displacement_pct,
    )
    visit = book_visit(base["system"]["id"], base["technician"]["id"],
                       base["system"]["version"],
                       scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    tech_headers = make_field_tech_headers(tech_user_id)
    visit = get_success_data(api_client.start_visit(visit["id"], tech_headers))
    base["visit"] = visit
    return base


def create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                           tech_user_id="tech-1", labor_minutes=30,
                           consumable_lines=None, serviced_equipment_ids=None,
                           **start_kwargs):
    """Full chain through COMPLETED. Returns dict: contract, system,
    technician, visit (COMPLETED, with invoice_id set)."""
    base = create_started_visit(service_tier=service_tier,
                                customer_user_id=customer_user_id,
                                tech_user_id=tech_user_id, **start_kwargs)
    payload = f.complete_visit_payload(labor_minutes=labor_minutes)
    if consumable_lines is not None:
        payload["consumable_lines"] = consumable_lines
    if serviced_equipment_ids is not None:
        payload["serviced_equipment_ids"] = serviced_equipment_ids
    tech_headers = make_field_tech_headers(tech_user_id)
    visit = get_success_data(api_client.complete_visit(base["visit"]["id"], payload, tech_headers))
    base["visit"] = visit
    return base


# ---------------------------------------------------------------------------
# Tier 3: emergency lifecycle
# ---------------------------------------------------------------------------
def create_dispatched_emergency(service_tier="BASIC", customer_user_id="owner-1",
                                tech_user_id="tech-1", certified_for_reef=None,
                                system_kind="FRESHWATER", nominal_volume_l=200,
                                severity="HIGH", trip_fee_cents=5000,
                                reported_at="2026-02-25T08:00:00Z",
                                scheduled_start="2026-02-25T09:00:00Z",
                                scheduled_end="2026-02-25T10:00:00Z"):
    """Active system + tech + OPEN emergency dispatched -> DISPATCHED with an
    EMERGENCY ServiceVisit SCHEDULED.

    Returns dict: contract, system, technician, emergency (DISPATCHED),
    dispatched_visit_id.
    """
    base = setup_active_system_with_tech(
        service_tier=service_tier, customer_user_id=customer_user_id,
        tech_user_id=tech_user_id, certified_for_reef=certified_for_reef,
        system_kind=system_kind, nominal_volume_l=nominal_volume_l,
    )
    emergency = get_success_data(api_client.create_emergency(
        f.create_emergency_payload(base["system"]["id"], severity=severity,
                                   trip_fee_cents=trip_fee_cents, reported_at=reported_at),
        DISP))
    emergency = get_success_data(api_client.dispatch_emergency(
        emergency["id"],
        f.dispatch_emergency_payload(base["technician"]["id"],
                                     scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end),
        DISP))
    base["emergency"] = emergency
    base["dispatched_visit_id"] = emergency["dispatched_visit_id"]
    return base


# ---------------------------------------------------------------------------
# Tier 3: install lifecycle
# ---------------------------------------------------------------------------
def create_quoted_install(service_tier="PLUS", customer_user_id="owner-1",
                          labor_estimate_cents=40000, equipment_estimate_cents=120000,
                          nominal_volume_l=400, activate_contract=True):
    """Active (or DRAFT) contract + PROVISIONING system + QUOTED install.

    Returns dict: contract, system, install. If activate_contract is False the
    contract is left DRAFT (system stays PROVISIONING, no commission).
    """
    contract = create_contract(service_tier=service_tier, customer_user_id=customer_user_id)
    system = create_system(contract["id"], nominal_volume_l=nominal_volume_l, label="Build")
    if activate_contract:
        contract = get_success_data(api_client.activate_contract(contract["id"], AM))
    install = get_success_data(api_client.create_install(
        f.create_install_payload(contract["id"], system["id"],
                                 labor_estimate_cents=labor_estimate_cents,
                                 equipment_estimate_cents=equipment_estimate_cents),
        AM))
    return {"contract": contract, "system": system, "install": install}


def create_approved_install(customer_user_id="owner-1", service_tier="PLUS",
                            labor_estimate_cents=40000, equipment_estimate_cents=120000):
    """Active contract + PROVISIONING system + APPROVED install (deposit invoice issued).

    Returns dict: contract, system, install (APPROVED).
    """
    base = create_quoted_install(service_tier=service_tier, customer_user_id=customer_user_id,
                                 labor_estimate_cents=labor_estimate_cents,
                                 equipment_estimate_cents=equipment_estimate_cents)
    owner_headers = make_customer_owner_headers(customer_user_id)
    install = get_success_data(api_client.approve_install(base["install"]["id"], owner_headers))
    base["install"] = install
    return base


# ---------------------------------------------------------------------------
# Tier: quarantine setup
# ---------------------------------------------------------------------------
def setup_home_and_qt_with_livestock(customer_user_id="owner-1",
                                     tech_user_id="tech-1",
                                     home_volume_l=300, qt_volume_l=80,
                                     num_fish=2, species_class="COMMUNITY",
                                     adult_length_cm=4):
    """Active contract + active home FRESHWATER system + active FRESHWATER QT
    tank + N ALIVE livestock in the home system.

    Returns dict: contract, home (system), qt (tank system, freshly fetched so
    version is current), livestock (list).
    """
    contract = create_contract(customer_user_id=customer_user_id)
    home = create_system(contract["id"], system_kind="FRESHWATER",
                        nominal_volume_l=home_volume_l, label="Home")
    qt = create_system(contract["id"], system_kind="FRESHWATER",
                       nominal_volume_l=qt_volume_l, label="QT")
    get_success_data(api_client.activate_contract(contract["id"], AM))
    get_success_data(api_client.commission_system(home["id"], AM))
    qt = get_success_data(api_client.commission_system(qt["id"], AM))
    tech_headers = make_field_tech_headers(tech_user_id)
    create_technician(tech_user_id=tech_user_id)
    livestock = []
    for i in range(num_fish):
        ls = get_success_data(api_client.create_livestock(
            f.create_livestock_payload(home["id"], common_name=f"Fish{i}",
                                       species_class=species_class,
                                       adult_length_cm=adult_length_cm),
            tech_headers))
        livestock.append(ls)
    return {"contract": contract, "home": home, "qt": qt, "livestock": livestock}


def create_active_quarantine(customer_user_id="owner-1", tech_user_id="tech-1",
                             window_start="2026-03-01T00:00:00Z",
                             window_end="2026-03-03T00:00:00Z"):
    """Home system with two ALIVE livestock + QT tank + one ACTIVE quarantine on
    fish[0].

    Returns dict: contract, home, qt, livestock (list), quarantine (ACTIVE).
    """
    base = setup_home_and_qt_with_livestock(customer_user_id=customer_user_id,
                                            tech_user_id=tech_user_id)
    tech_headers = make_field_tech_headers(tech_user_id)
    quarantine = get_success_data(api_client.create_quarantine(
        f.create_quarantine_payload(base["livestock"][0]["id"], base["qt"]["id"],
                                    base["qt"]["version"],
                                    window_start=window_start, window_end=window_end),
        tech_headers))
    base["quarantine"] = quarantine
    return base


# ---------------------------------------------------------------------------
# Tier: equipment + repair setup
# ---------------------------------------------------------------------------
def create_equipment_on_system(customer_user_id="owner-1", device_kind="FILTER",
                               media_interval_days=30, nominal_volume_l=200):
    """DRAFT contract + PROVISIONING system + one device (no activation needed
    for equipment registration). Returns dict: contract, system, equipment."""
    contract = create_contract(customer_user_id=customer_user_id)
    system = create_system(contract["id"], nominal_volume_l=nominal_volume_l)
    equipment = get_success_data(api_client.create_equipment(
        f.create_equipment_payload(system["id"], device_kind=device_kind,
                                   media_interval_days=media_interval_days),
        AM))
    return {"contract": contract, "system": system, "equipment": equipment}


def create_diagnosed_repair(tech_user_id="tech-1", device_kind="FILTER",
                            parts_needed=False, reported_symptom="leak"):
    """System + device + repair order diagnosed (DIAGNOSED; equipment DEGRADED).

    Returns dict: contract, system, equipment, repair (DIAGNOSED).
    """
    base = create_equipment_on_system(device_kind=device_kind)
    create_technician(tech_user_id=tech_user_id)
    tech_headers = make_field_tech_headers(tech_user_id)
    payload = f.create_repair_payload(base["equipment"]["id"], reported_symptom=reported_symptom)
    if parts_needed:
        payload["parts_needed"] = True
    repair = get_success_data(api_client.create_repair(payload, tech_headers))
    repair = get_success_data(api_client.diagnose_repair(repair["id"], tech_headers))
    base["repair"] = repair
    return base


# ---------------------------------------------------------------------------
# Tier: invoice from completed visit
# ---------------------------------------------------------------------------
def create_issued_invoice_from_visit(service_tier="BASIC", customer_user_id="owner-1",
                                     tech_user_id="tech-1", labor_minutes=30):
    """Completed visit -> ISSUED invoice. Returns dict: contract, system,
    technician, visit (COMPLETED), invoice_id."""
    base = create_completed_visit(service_tier=service_tier,
                                  customer_user_id=customer_user_id,
                                  tech_user_id=tech_user_id, labor_minutes=labor_minutes)
    base["invoice_id"] = base["visit"]["invoice_id"]
    return base
