"""Composite setup helpers — multi-step state builders used across tests.

All fixtures use get_success_data() internally so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_alloy_rule_payload,
    create_bath_payload,
    create_customer_payload,
    create_discharge_permit_payload,
    create_fixture_payload,
    create_inspection_payload,
    create_load_run_payload,
    create_salt_spray_lot_payload,
    create_titration_payload,
    create_waste_manifest_payload,
    create_waste_sample_payload,
    create_work_order_payload,
    create_manifest_line_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)

MGR = TEST_USERS["shop_manager_headers"]
OP = TEST_USERS["line_operator_headers"]
CHEM = TEST_USERS["lab_chemist_headers"]
QC = TEST_USERS["qc_inspector_headers"]
EHS = TEST_USERS["ehs_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: master data
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    """Create a customer; returns the customer record."""
    resp = api_client.create_customer(create_customer_payload(**overrides), MGR)
    return get_success_data(resp)


def create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE",
                       **overrides):
    """Create an alloy compatibility rule; returns the rule record."""
    payload = create_alloy_rule_payload(
        alloy_code=alloy_code, process_type=process_type,
        chemistry_family=chemistry_family, compatibility=compatibility,
        **overrides,
    )
    resp = api_client.create_alloy_rule(payload, CHEM)
    return get_success_data(resp)


def create_fixture(**overrides):
    resp = api_client.create_fixture(create_fixture_payload(**overrides), MGR)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: baths and chemistry
# ---------------------------------------------------------------------------

def create_bath(**overrides):
    """Create a bath (ACTIVE, untitrated); returns the bath record."""
    resp = api_client.create_bath(create_bath_payload(**overrides), MGR)
    return get_success_data(resp)


def titrate_bath(bath_id, **overrides):
    """Record a titration on a bath; returns the BathTitration record.

    Default readings (50.0 ml x 0.1 N x 49.0 / 49.0 ml) measure 5.000 g/L on a
    SULFURIC bath. For other chemistry families pass explicit readings.
    """
    resp = api_client.create_titration(bath_id, create_titration_payload(**overrides), CHEM)
    return get_success_data(resp)


def create_titrated_bath(target_conc=5.0, titration_overrides=None, **overrides):
    """Create a bath and record a baseline titration (default measures exactly 5.000).
    Returns the refreshed bath record (version after the titration).

    Callers may pass the canonical field name `target_concentration_g_l` instead of
    the `target_conc` shorthand; the two spellings are reconciled here."""
    if "target_concentration_g_l" in overrides:
        target_conc = overrides.pop("target_concentration_g_l")
    bath = create_bath(target_concentration_g_l=target_conc, **overrides)
    titrate_bath(bath["id"], **(titration_overrides or {}))
    return get_success_data(api_client.get_bath(bath["id"], CHEM))


def get_bath(bath_id):
    return get_success_data(api_client.get_bath(bath_id, CHEM))


def get_bath_version(bath_id) -> int:
    return get_success_data(api_client.get_bath(bath_id, CHEM))["version"]


def dose_bath(bath_id, expected_bath_version, **overrides):
    from .factories import create_dose_payload
    payload = create_dose_payload(**overrides)
    payload["expected_bath_version"] = expected_bath_version
    resp = api_client.create_dose(bath_id, payload, CHEM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: work order state progression
# ---------------------------------------------------------------------------

def create_work_order(customer_id, as_owner=True, **overrides):
    """Create a work order. By default the owner Customer creates it for itself."""
    payload = create_work_order_payload(customer_id=customer_id, **overrides)
    headers = make_customer_headers(customer_id) if as_owner else MGR
    resp = api_client.create_work_order(payload, headers)
    return get_success_data(resp)


def prepare_work_order(work_order_id, masking_minutes=None):
    """prepare: RECEIVED -> READY_FOR_ROUTING. Pass masking_minutes only when required."""
    payload = {} if masking_minutes is None else {"masking_minutes": masking_minutes}
    resp = api_client.prepare_work_order(work_order_id, payload, OP)
    return get_success_data(resp)


def route_work_order(work_order_id, bath_id, fixture_id=None,
                     planned_duration_minutes=40, planned_current_density_a_dm2=1.5):
    """route: READY_FOR_ROUTING/ROUTE_HELD -> ROUTED. Returns updated order."""
    payload = {
        "bath_id": bath_id,
        "planned_duration_minutes": planned_duration_minutes,
        "planned_current_density_a_dm2": planned_current_density_a_dm2,
    }
    if fixture_id is not None:
        payload["fixture_id"] = fixture_id
    resp = api_client.route_work_order(work_order_id, payload, OP)
    return get_success_data(resp)


def start_load_run(work_order_id, bath_version=None, duration_minutes=40,
                   current_density_a_dm2=1.5, bath_id=None):
    """Start a load run on the work order's routed bath.

    If bath_version is None and bath_id is given, reads the bath for its current
    version. Returns the LoadRun record (status RUNNING).
    """
    if bath_version is None:
        assert bath_id is not None, "bath_id required when bath_version not given"
        bath_version = get_bath_version(bath_id)
    payload = create_load_run_payload(
        duration_minutes=duration_minutes,
        current_density_a_dm2=current_density_a_dm2,
    )
    payload["expected_bath_version"] = bath_version
    resp = api_client.start_load_run(work_order_id, payload, OP)
    return get_success_data(resp)


def complete_load_run(load_run_id):
    resp = api_client.complete_load_run(load_run_id, OP)
    return get_success_data(resp)


def abort_load_run(load_run_id):
    resp = api_client.abort_load_run(load_run_id, OP)
    return get_success_data(resp)


def inspect_work_order(work_order_id, **overrides):
    """Record an inspection; returns the InspectionReport."""
    resp = api_client.create_inspection(work_order_id, create_inspection_payload(**overrides), QC)
    return get_success_data(resp)


def get_work_order(work_order_id, headers=None):
    return get_success_data(api_client.get_work_order(work_order_id, headers or OP))


def strip_and_replate(work_order_id):
    """REJECTED -> STRIPPING -> READY_FOR_ROUTING. Returns the refreshed order."""
    get_success_data(api_client.start_strip(work_order_id, {"strip_method": "CHEMICAL"}, OP))
    return get_success_data(api_client.complete_strip(work_order_id, OP))


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_customer_rule_bath(company_name="Test Co", alloy_code="AL6061",
                             process_type="ANODIZE", chemistry_family="SULFURIC",
                             compatibility="COMPATIBLE", bath_overrides=None,
                             titration_overrides=None, fixture_overrides=None):
    """Create customer + compat rule + titrated bath (+ optional fixture).

    Returns (customer, bath, fixture_or_None).
    """
    customer = create_customer(company_name=company_name)
    create_compat_rule(alloy_code=alloy_code, process_type=process_type,
                       chemistry_family=chemistry_family, compatibility=compatibility)
    bath = create_titrated_bath(
        process_type=process_type, chemistry_family=chemistry_family,
        titration_overrides=titration_overrides, **(bath_overrides or {}),
    )
    fixture = create_fixture(**fixture_overrides) if fixture_overrides is not None else None
    return customer, bath, fixture


def setup_routed_order(customer_id, bath_id, fixture_id=None,
                       planned_duration_minutes=40, planned_current_density_a_dm2=1.5,
                       masking_minutes=None, **wo_overrides):
    """Create -> prepare -> route a work order. Returns the ROUTED order."""
    wo = create_work_order(customer_id, **wo_overrides)
    prepare_work_order(wo["id"], masking_minutes=masking_minutes)
    return route_work_order(
        wo["id"], bath_id, fixture_id=fixture_id,
        planned_duration_minutes=planned_duration_minutes,
        planned_current_density_a_dm2=planned_current_density_a_dm2,
    )


def setup_awaiting_inspection(customer_id, bath_id, fixture_id=None,
                              duration_minutes=40, current_density_a_dm2=1.5,
                              masking_minutes=None, **wo_overrides):
    """Drive a work order to AWAITING_INSPECTION via one completed load.

    Returns (work_order_record, load_run_record).
    """
    wo = setup_routed_order(
        customer_id, bath_id, fixture_id=fixture_id,
        planned_duration_minutes=duration_minutes,
        planned_current_density_a_dm2=current_density_a_dm2,
        masking_minutes=masking_minutes, **wo_overrides,
    )
    lr = start_load_run(wo["id"], bath_id=bath_id,
                        duration_minutes=duration_minutes,
                        current_density_a_dm2=current_density_a_dm2)
    complete_load_run(lr["id"])
    return get_work_order(wo["id"]), lr


def run_passing_cycle(work_order_id, bath_id, fixture_id=None,
                      duration_minutes=40, current_density_a_dm2=1.5,
                      readings=None, defect_type="NONE"):
    """From ROUTED: start+complete a load, then inspect (PASS disposition by default).
    Returns (load_run, inspection_report)."""
    lr = start_load_run(work_order_id, bath_id=bath_id,
                        duration_minutes=duration_minutes,
                        current_density_a_dm2=current_density_a_dm2)
    complete_load_run(lr["id"])
    report = inspect_work_order(
        work_order_id,
        thickness_readings_um=readings or [13.0, 14.0, 15.0],
        defect_type=defect_type,
    )
    return lr, report


def setup_awaiting_lot_test(customer_id, bath_id, **wo_overrides):
    """Drive a requires_salt_spray order to AWAITING_LOT_TEST.
    Returns the refreshed work order."""
    wo_overrides.setdefault("requires_salt_spray", True)
    wo, _lr = setup_awaiting_inspection(customer_id, bath_id, **wo_overrides)
    inspect_work_order(wo["id"])
    return get_work_order(wo["id"])


# ---------------------------------------------------------------------------
# Tier 4: manifests and permits
# ---------------------------------------------------------------------------

def create_manifest(creator_headers=None, creator_user_id=None, **overrides):
    """Create a DRAFT manifest. If creator_user_id is given, builds EHS headers
    for that user so created_by_user_id is pinned."""
    if creator_user_id is not None:
        from .test_users import make_ehs_officer_headers
        creator_headers = make_ehs_officer_headers(creator_user_id)
    resp = api_client.create_waste_manifest(
        create_waste_manifest_payload(**overrides), creator_headers or EHS
    )
    return get_success_data(resp)


def add_line_item(manifest_id, expected_manifest_version, headers=None, **overrides):
    payload = create_manifest_line_item_payload(**overrides)
    payload["expected_manifest_version"] = expected_manifest_version
    resp = api_client.add_manifest_line_item(manifest_id, payload, headers or EHS)
    return get_success_data(resp)


def get_manifest(manifest_id):
    return get_success_data(api_client.get_waste_manifest(manifest_id, EHS))


def create_salt_spray_lot(work_order_id, **overrides):
    """Create a SaltSprayLot for an AWAITING_LOT_TEST order; returns the lot."""
    payload = create_salt_spray_lot_payload(work_order_id=work_order_id, **overrides)
    resp = api_client.create_salt_spray_lot(payload, CHEM)
    return get_success_data(resp)


def create_permit(**overrides):
    resp = api_client.create_discharge_permit(create_discharge_permit_payload(**overrides), EHS)
    return get_success_data(resp)


def record_sample(permit_id, **overrides):
    resp = api_client.create_waste_sample(permit_id, create_waste_sample_payload(**overrides), EHS)
    return get_success_data(resp)


def get_permit(permit_id):
    return get_success_data(api_client.get_discharge_permit(permit_id, EHS))


# ---------------------------------------------------------------------------
# Tier 5: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, MGR)
    return get_success_data(resp)
