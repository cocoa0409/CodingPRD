"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. All setup
calls use get_success_data() so a setup failure surfaces as a clear
"setup failed" error rather than a confusing assertion failure.
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_adherence_report_payload,
    create_device_enrollment_payload,
    create_mask_exchange_payload,
    create_patient_payload,
    create_payer_policy_payload,
    create_resupply_order_payload,
    initiate_discontinuation_payload,
    occ_payload,
)
from .test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
RT = TEST_USERS["respiratory_therapist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# Clock / sweep drivers (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock. Returns the sweep response data."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def run_daily_sweep() -> dict:
    """Run the daily operations sweep. Returns {reminders_sent, ...}."""
    return get_success_data(api_client.run_daily_sweep(OPS))


# ---------------------------------------------------------------------------
# Tier 1/2: payer policy, patient, device enrollment, therapy activation
# ---------------------------------------------------------------------------

def create_payer_policy(**overrides) -> dict:
    """Create a payer policy with CMS-standard defaults. Returns the policy."""
    return get_success_data(
        api_client.create_payer_policy(create_payer_policy_payload(**overrides), OPS))


def register_patient(payer_policy_id: str, **overrides) -> dict:
    """Register a patient in INTAKE. Returns the patient."""
    return get_success_data(
        api_client.create_patient(create_patient_payload(payer_policy_id, **overrides),
                                  INTAKE))


def enroll_device(patient_id: str, acquisition_type: str = "PURCHASE",
                  **overrides) -> dict:
    """Enroll a device for a patient (lands in PENDING_SETUP)."""
    return get_success_data(api_client.create_device_enrollment(
        create_device_enrollment_payload(patient_id, acquisition_type=acquisition_type,
                                         **overrides), INTAKE))


def get_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, OPS))


def current_patient_version(patient_id: str) -> int:
    return get_patient(patient_id)["version"]


def get_plan_for(patient_id: str, component_type: str) -> dict:
    """Fetch the patient's supply plan for one component type."""
    data = get_success_data(api_client.list_component_supply_plans(
        OPS, params={"patient_id": patient_id, "component_type": component_type}))
    assert data, f"setup failed: no {component_type} plan for patient {patient_id}"
    return data[0]


def get_plans_for(patient_id: str) -> dict:
    """Fetch all of a patient's supply plans keyed by component_type."""
    data = get_success_data(api_client.list_component_supply_plans(
        OPS, params={"patient_id": patient_id, "limit": 100}))
    return {plan["component_type"]: plan for plan in data}


def get_rental_contract_for(patient_id: str):
    """Fetch the patient's rental contract, or None if they own the device."""
    data = get_success_data(api_client.list_rental_contracts(
        OPS, params={"patient_id": patient_id}))
    return data[0] if data else None


def setup_therapy_patient(acquisition_type: str = "PURCHASE",
                          clock: str = TEST_DEFAULTS["CLOCK_START"],
                          payer_overrides: dict | None = None,
                          patient_overrides: dict | None = None) -> dict:
    """Master setup: clock -> payer policy -> patient -> enrollment ->
    begin-setup -> complete-setup. Patient lands in ACTIVE_THERAPY with four
    ACTIVE supply plans; a RENTAL enrollment also creates a RentalContract.

    Returns {"policy", "patient", "enrollment", "plans", "rental_contract"}.
    """
    set_clock(clock)
    policy = create_payer_policy(**(payer_overrides or {}))
    patient = register_patient(policy["id"], **(patient_overrides or {}))
    enrollment = enroll_device(patient["id"], acquisition_type=acquisition_type)
    get_success_data(api_client.begin_setup(enrollment["id"], RT))
    enrollment = get_success_data(api_client.complete_setup(enrollment["id"], RT))
    patient = get_patient(patient["id"])
    plans = get_plans_for(patient["id"])
    rental_contract = get_rental_contract_for(patient["id"])
    return {
        "policy": policy,
        "patient": patient,
        "enrollment": enrollment,
        "plans": plans,
        "rental_contract": rental_contract,
    }


# ---------------------------------------------------------------------------
# Tier 3: resupply order lifecycle shortcuts (PRD §3.5)
# ---------------------------------------------------------------------------

def create_order_for_plan(patient_id: str, plan: dict,
                          expected_patient_version: int | None = None,
                          requested_quantity: int | None = None,
                          headers=None) -> dict:
    """Create a resupply order against a plan. Quantity defaults to the plan's
    quantity_per_cycle (orders are always full-cycle); the OCC version is
    fetched fresh when not supplied. Returns the PENDING_CLINICAL_CLEARANCE
    order."""
    if expected_patient_version is None:
        expected_patient_version = current_patient_version(patient_id)
    if requested_quantity is None:
        requested_quantity = plan["quantity_per_cycle"]
    return get_success_data(api_client.create_resupply_order(
        create_resupply_order_payload(patient_id, plan["id"], requested_quantity,
                                      expected_patient_version),
        headers or INTAKE))


def clinical_clear(order_id: str, user_id: str = "rt-1") -> dict:
    """RespiratoryTherapist clears the order (records their X-User-ID)."""
    from .test_users import make_respiratory_therapist_headers
    return get_success_data(api_client.clinical_clear_order(
        order_id, make_respiratory_therapist_headers(user_id)))


def authorize_order(order_id: str, patient_id: str, user_id: str = "bs-1",
                    expected_patient_version: int | None = None) -> dict:
    """BillingSpecialist authorizes with a fresh OCC version by default."""
    from .test_users import make_billing_specialist_headers
    if expected_patient_version is None:
        expected_patient_version = current_patient_version(patient_id)
    return get_success_data(api_client.authorize_order(
        order_id, occ_payload(expected_patient_version),
        make_billing_specialist_headers(user_id)))


def ship_order(order_id: str, patient_id: str,
               expected_patient_version: int | None = None) -> dict:
    """Ship an AUTHORIZED order with a fresh OCC version by default."""
    if expected_patient_version is None:
        expected_patient_version = current_patient_version(patient_id)
    return get_success_data(api_client.ship_order(
        order_id, occ_payload(expected_patient_version), INTAKE))


def deliver_order(order_id: str) -> dict:
    return get_success_data(api_client.mark_order_delivered(order_id, INTAKE))


def invoice_order(order_id: str) -> dict:
    return get_success_data(api_client.invoice_order(order_id, BILLING))


def create_cleared_order(patient_id: str, plan: dict, clearer_id: str = "rt-1") -> dict:
    """Create an order and clinically clear it -> PENDING_PAYER_AUTH."""
    order = create_order_for_plan(patient_id, plan)
    return clinical_clear(order["id"], user_id=clearer_id)


def create_authorized_order(patient_id: str, plan: dict,
                            clearer_id: str = "rt-1",
                            authorizer_id: str = "bs-1") -> dict:
    """Create -> clinical-clear -> authorize. Returns the AUTHORIZED order
    (fulfillment READY_TO_SHIP); the response carries unit_allowable_cents."""
    order = create_cleared_order(patient_id, plan, clearer_id=clearer_id)
    return authorize_order(order["id"], patient_id, user_id=authorizer_id)


def create_shipped_order(patient_id: str, plan: dict) -> dict:
    """Create -> clear -> authorize -> ship. Returns the SHIPPED order."""
    order = create_authorized_order(patient_id, plan)
    return ship_order(order["id"], patient_id)


def dispense_component(patient_id: str, component_type: str) -> dict:
    """Drive one full-cycle order for the given component through SHIPPED so
    the plan's last_dispensed_on/next_eligible_on are set to the current date.
    Returns the refreshed plan."""
    plans = get_plans_for(patient_id)
    order = create_shipped_order(patient_id, plans[component_type])
    assert order["fulfillment_status"] == "SHIPPED", "setup failed: order not SHIPPED"
    return get_success_data(api_client.get_component_supply_plan(
        plans[component_type]["id"], OPS))


# ---------------------------------------------------------------------------
# Adherence report helpers (PRD §3.4)
# ---------------------------------------------------------------------------

def ingest_adherence_report(patient_id: str, device_enrollment_id: str,
                            window_end_on: str, nights_reported: int,
                            compliant_nights: int) -> dict:
    """Ingest a report (lands in RECEIVED with provisional percentage)."""
    return get_success_data(api_client.create_adherence_report(
        create_adherence_report_payload(patient_id, device_enrollment_id,
                                        window_end_on, nights_reported,
                                        compliant_nights), RT))


def finalize_adherence_report(report_id: str) -> dict:
    """begin-review -> finalize. Returns the FINALIZED report."""
    get_success_data(api_client.begin_review_report(report_id, RT))
    return get_success_data(api_client.finalize_report(report_id, RT))


def ingest_and_finalize_report(patient_id: str, device_enrollment_id: str,
                               window_end_on: str, nights_reported: int,
                               compliant_nights: int) -> dict:
    """Ingest then finalize a report in one call chain."""
    report = ingest_adherence_report(patient_id, device_enrollment_id,
                                     window_end_on, nights_reported, compliant_nights)
    return finalize_adherence_report(report["id"])


def finalize_non_compliant_report(patient_id: str, device_enrollment_id: str,
                                  window_end_on: str, nights_reported: int = 30,
                                  compliant_nights: int = 5) -> dict:
    """Finalize a report below the 70% threshold -> NON_COMPLIANT_HOLD."""
    return ingest_and_finalize_report(patient_id, device_enrollment_id,
                                      window_end_on, nights_reported, compliant_nights)


def finalize_compliant_report(patient_id: str, device_enrollment_id: str,
                              window_end_on: str, nights_reported: int = 30,
                              compliant_nights: int = 28) -> dict:
    """Finalize a report at/above the 70% threshold -> compliance restored."""
    return ingest_and_finalize_report(patient_id, device_enrollment_id,
                                      window_end_on, nights_reported, compliant_nights)


# ---------------------------------------------------------------------------
# Mask exchange helpers (PRD §3.6)
# ---------------------------------------------------------------------------

def request_mask_exchange(patient_id: str, device_enrollment_id: str,
                          mask_plan_id: str, reason_code: str = "FIT_LEAK") -> dict:
    """Request a mask exchange (lands in REQUESTED with window_anchor_on)."""
    return get_success_data(api_client.create_mask_exchange(
        create_mask_exchange_payload(patient_id, device_enrollment_id,
                                     mask_plan_id, reason_code=reason_code), INTAKE))


def get_mask_exchange(exchange_id: str) -> dict:
    return get_success_data(api_client.get_mask_exchange(exchange_id, OPS))


def complete_mask_exchange_flow(exchange_id: str) -> dict:
    """approve -> ship -> complete. Returns the COMPLETED exchange."""
    get_success_data(api_client.approve_mask_exchange(exchange_id, RT))
    get_success_data(api_client.ship_mask_exchange(exchange_id, INTAKE))
    return get_success_data(api_client.complete_mask_exchange(exchange_id, INTAKE))


# ---------------------------------------------------------------------------
# Tier 5: discontinuation / retrieval terminal flows (PRD §3.8)
# ---------------------------------------------------------------------------

def initiate_discontinuation_for(patient_id: str,
                                 reason_code: str = "THERAPY_DISCONTINUED") -> dict:
    """Initiate discontinuation. Returns the DISCONTINUING patient."""
    return get_success_data(api_client.initiate_discontinuation(
        patient_id, initiate_discontinuation_payload(reason_code=reason_code), RT))


def get_retrieval_case_for(patient_id: str) -> dict:
    """Fetch the patient's retrieval case (created by discontinuation)."""
    data = get_success_data(api_client.list_retrieval_cases(
        OPS, params={"patient_id": patient_id}))
    assert data, f"setup failed: no retrieval case for patient {patient_id}"
    return data[0]


def setup_discontinuing_patient(clock: str = TEST_DEFAULTS["CLOCK_START"]) -> dict:
    """RENTAL patient driven to DISCONTINUING with an OPEN retrieval case.
    Returns the setup_therapy_patient dict plus "retrieval_case"."""
    ctx = setup_therapy_patient(acquisition_type="RENTAL", clock=clock)
    patient = initiate_discontinuation_for(ctx["patient"]["id"])
    ctx["patient"] = patient
    ctx["retrieval_case"] = get_retrieval_case_for(patient["id"])
    return ctx


def drive_retrieval_to_received(case_id: str) -> dict:
    """schedule-pickup -> mark-picked-up -> mark-received. Returns RECEIVED case."""
    get_success_data(api_client.schedule_pickup(case_id, INTAKE))
    get_success_data(api_client.mark_picked_up(case_id, INTAKE))
    return get_success_data(api_client.mark_received(case_id, INTAKE))


# ---------------------------------------------------------------------------
# Calculation helpers (PRD §2.8 / §3.5)
# ---------------------------------------------------------------------------

def expected_coinsurance_share(unit_allowable_cents: int, requested_quantity: int) -> int:
    """Patient share = 20% of the line total, rounded half-up to a whole cent,
    applied to the line total after multiplication — never per unit (PRD §3.5).
    """
    line_total = Decimal(unit_allowable_cents) * Decimal(requested_quantity)
    share = (line_total * Decimal(TEST_DEFAULTS["COINSURANCE_RATE"])).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(share)
