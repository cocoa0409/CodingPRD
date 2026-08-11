"""Composite setup helpers.

Every helper builds preconditions from scratch against a fresh server using only
PRD-declared endpoints. Setup calls use the lenient get_success_data() so a
failure surfaces as a clear "Setup failed" error rather than an assertion fault.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    payer_plan_payload,
    formulary_item_payload,
    patient_payload,
    prescription_payload,
    fit_profile_payload,
    resupply_program_payload,
    order_payload,
    order_line_payload,
    prior_authorization_payload,
    stock_level_payload,
    fitting_sample_payload,
    hsa_debit_payload,
    hsa_credit_payload,
)
from .test_users import TEST_USERS, make_patient_headers

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
PA_SPEC = TEST_USERS["prior_auth_specialist_headers"]
FULFIL = TEST_USERS["fulfillment_agent_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


def _setup_failed(step: str, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code}: {resp.text}"
    )


def _ok(step: str, resp):
    if resp.status_code // 100 != 2:
        _setup_failed(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin test-driving capability)."""
    _ok("set_clock", api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: configuration + patient intake primitives
# ---------------------------------------------------------------------------

def create_payer_plan(**overrides) -> dict:
    return _ok("create_payer_plan", api_client.create_payer_plan(payer_plan_payload(**overrides), ADMIN))


def create_formulary_item(covered_plan_ids, **overrides) -> dict:
    return _ok(
        "create_formulary_item",
        api_client.create_formulary_item(formulary_item_payload(covered_plan_ids, **overrides), ADMIN),
    )


def create_stock_level(formulary_item_id, on_hand_qty=500) -> dict:
    return _ok(
        "create_stock_level",
        api_client.create_stock_level(
            stock_level_payload(formulary_item_id, on_hand_qty=on_hand_qty), ADMIN
        ),
    )


def create_patient(payer_plan_id, hsa_initial_credit_cents=0, **overrides) -> dict:
    """Enroll a patient (born PENDING_VERIFICATION; cascade-creates the HSA account)."""
    return _ok(
        "create_patient",
        api_client.create_patient(
            patient_payload(
                payer_plan_id, hsa_initial_credit_cents=hsa_initial_credit_cents, **overrides
            ),
            INTAKE,
        ),
    )


def verify_patient(patient_id, eligible=True) -> dict:
    """Verify eligibility; returns the post-transition patient (with fresh version)."""
    return _ok(
        "verify_eligibility",
        api_client.verify_eligibility(patient_id, {"eligible": eligible}, INTAKE),
    )


def create_active_patient(payer_plan_id, hsa_initial_credit_cents=0, **overrides) -> dict:
    """Enroll + verify eligible=true. Returns the ACTIVE patient."""
    patient = create_patient(payer_plan_id, hsa_initial_credit_cents, **overrides)
    return verify_patient(patient["id"], eligible=True)


def create_prescription(patient_id, **overrides) -> dict:
    return _ok(
        "create_prescription",
        api_client.create_prescription(prescription_payload(patient_id, **overrides), INTAKE),
    )


def create_fit_profile(patient_id, expected_patient_version, **overrides) -> dict:
    return _ok(
        "create_fit_profile",
        api_client.create_fit_profile(
            fit_profile_payload(patient_id, expected_patient_version, **overrides), INTAKE
        ),
    )


def create_prior_authorization(patient_id, **overrides) -> dict:
    return _ok(
        "create_prior_authorization",
        api_client.create_prior_authorization(
            prior_authorization_payload(patient_id, **overrides), PA_SPEC
        ),
    )


def decide_prior_authorization(pa_id, outcome) -> dict:
    return _ok(
        "decide_prior_authorization",
        api_client.decide_prior_authorization(pa_id, {"outcome": outcome}, PA_SPEC),
    )


def appeal_prior_authorization(pa_id) -> dict:
    return _ok("appeal_prior_authorization", api_client.appeal_prior_authorization(pa_id, PA_SPEC))


def create_program(patient_id, **overrides) -> dict:
    return _ok(
        "create_resupply_program",
        api_client.create_resupply_program(resupply_program_payload(patient_id, **overrides), INTAKE),
    )


def suspend_program(program_id, reason="manual hold") -> dict:
    return _ok("suspend_program", api_client.suspend_program(program_id, {"reason": reason}, INTAKE))


def resume_program(program_id) -> dict:
    return _ok("resume_program", api_client.resume_program(program_id, INTAKE))


# ---------------------------------------------------------------------------
# Orders, lines, shipments
# ---------------------------------------------------------------------------

def create_manual_order(patient_id) -> dict:
    """Create a DRAFT manual reorder as the owning Patient."""
    return _ok(
        "create_order",
        api_client.create_order(order_payload(patient_id), make_patient_headers(patient_id)),
    )


def get_order(order_id) -> dict:
    return _ok("get_order", api_client.get_order(order_id, INTAKE))


def add_order_line(order_id, expected_order_version, formulary_item_id,
                   size_code="45MM", quantity=1, patient_id=None) -> dict:
    """Add a line to a DRAFT order (OCC on the order version)."""
    headers = make_patient_headers(patient_id) if patient_id else INTAKE
    return _ok(
        "add_order_line",
        api_client.add_order_line(
            order_id,
            order_line_payload(
                formulary_item_id,
                expected_order_version,
                size_code=size_code,
                quantity=quantity,
            ),
            headers,
        ),
    )


def submit_order(order_id, patient_id) -> dict:
    return _ok(
        "submit_order",
        api_client.submit_order(order_id, make_patient_headers(patient_id)),
    )


def cancel_order(order_id, patient_id) -> dict:
    return _ok(
        "cancel_order",
        api_client.cancel_order(order_id, make_patient_headers(patient_id)),
    )


def create_shipment_for_order(order_id) -> dict:
    return _ok("create_shipment", api_client.create_shipment({"order_id": order_id}, FULFIL))


def get_shipment(shipment_id) -> dict:
    return _ok("get_shipment", api_client.get_shipment(shipment_id, FULFIL))


def release_shipment(shipment_id) -> dict:
    return _ok("release_shipment", api_client.release_shipment(shipment_id, FULFIL))


def ship_shipment(shipment_id) -> dict:
    return _ok("ship_shipment", api_client.ship_shipment(shipment_id, FULFIL))


def deliver_shipment(shipment_id) -> dict:
    return _ok("deliver_shipment", api_client.deliver_shipment(shipment_id, FULFIL))


def return_shipment(shipment_id) -> dict:
    return _ok("return_shipment", api_client.return_shipment(shipment_id, FULFIL))


def restock(stock_id, qty_added) -> dict:
    return _ok("restock", api_client.restock_stock_level(stock_id, {"qty_added": qty_added}, ADMIN))


def get_stock_level(stock_id) -> dict:
    return _ok("get_stock_level", api_client.get_stock_level(stock_id, ADMIN))


# ---------------------------------------------------------------------------
# Claims & HSA
# ---------------------------------------------------------------------------

def create_claim(order_id) -> dict:
    return _ok("create_claim", api_client.create_claim({"order_id": order_id}, BILLING))


def submit_claim(claim_id) -> dict:
    return _ok("submit_claim", api_client.submit_claim(claim_id, BILLING))


def adjudicate_claim(claim_id, outcome) -> dict:
    return _ok("adjudicate_claim", api_client.adjudicate_claim(claim_id, {"outcome": outcome}, BILLING))


def appeal_claim(claim_id) -> dict:
    return _ok("appeal_claim", api_client.appeal_claim(claim_id, BILLING))


def get_hsa_account(patient_id) -> dict:
    """The patient's single HSA account (array of 0-1 from the patient)."""
    data = _ok(
        "list_patient_hsa_accounts",
        api_client.list_patient_hsa_accounts(patient_id, BILLING),
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one HSA account for patient {patient_id}, got {data}"
    )
    return data[0]


def get_hsa_balance(account_id) -> float:
    return _ok("get_hsa_account", api_client.get_hsa_account(account_id, BILLING))["balance_cents"]


def post_hsa_debit(account_id, amount_cents, reason="debit", **overrides) -> dict:
    return _ok(
        "post_hsa_debit",
        api_client.post_hsa_debit(
            account_id, hsa_debit_payload(amount_cents, reason=reason, **overrides), BILLING
        ),
    )


def post_hsa_credit(account_id, amount_cents, reason="credit", **overrides) -> dict:
    return _ok(
        "post_hsa_credit",
        api_client.post_hsa_credit(
            account_id, hsa_credit_payload(amount_cents, reason=reason, **overrides), BILLING
        ),
    )


# ---------------------------------------------------------------------------
# Fitting samples
# ---------------------------------------------------------------------------

def create_sample(patient_id, **overrides) -> dict:
    return _ok(
        "create_fitting_sample",
        api_client.create_fitting_sample(fitting_sample_payload(patient_id, **overrides), INTAKE),
    )


# ---------------------------------------------------------------------------
# Tier 2 composite: plan + item (+stock) + ACTIVE patient + Rx + fit profile
# ---------------------------------------------------------------------------

def setup_active_patient_with_item(
    plan_type="MEDICARE_DMEPOS",
    coinsurance_pct=0.20,
    cycle_months=3,
    hsa_initial_credit_cents=0,
    hcpcs_code="A4419",
    category="OSTOMY",
    size_code="45MM",
    size_codes=("45MM",),
    pack_fee_cents=1850,
    pack_size=10,
    retail_price_cents=300,
    max_units_per_cycle=60,
    requires_pa=False,
    monthly_quantity=20,
    on_hand_qty=None,
    diagnosis_codes=("N39.3",),
    rx_effective_date="2026-05-01",
    rx_expiration_date="2026-11-01",
    with_rx=True,
    with_fit=True,
    with_pa=None,
    pa_approved_units=45,
    pa_valid_from="2026-05-01",
    pa_valid_to="2026-08-31",
    pa_decision="APPROVED",
) -> dict:
    """Plan + formulary item (+ optional stock row) + ACTIVE patient + optional
    ACTIVE prescription + optional CURRENT fit profile + optional PA.

    Returns a context dict with every created entity.
    """
    plan = create_payer_plan(plan_type=plan_type, coinsurance_pct=coinsurance_pct,
                             cycle_months=cycle_months)
    item = create_formulary_item(
        [plan["id"]],
        hcpcs_code=hcpcs_code,
        category=category,
        pack_fee_cents=pack_fee_cents,
        pack_size=pack_size,
        retail_price_cents=retail_price_cents,
        max_units_per_cycle=max_units_per_cycle,
        requires_pa=requires_pa,
        size_codes=list(size_codes),
    )
    stock = None
    if on_hand_qty is not None:
        stock = create_stock_level(item["id"], on_hand_qty=on_hand_qty)
    patient = create_active_patient(plan["id"], hsa_initial_credit_cents)
    rx = None
    if with_rx:
        payload = prescription_payload(
            patient["id"],
            hcpcs_code=hcpcs_code,
            monthly_quantity=monthly_quantity,
            effective_date=rx_effective_date,
            expiration_date=rx_expiration_date,
        )
        if diagnosis_codes is None:
            payload.pop("diagnosis_codes", None)
        else:
            payload["diagnosis_codes"] = list(diagnosis_codes)
        rx = _ok("create_prescription", api_client.create_prescription(payload, INTAKE))
    fit = None
    if with_fit:
        fit = create_fit_profile(
            patient["id"],
            patient["version"],
            category=category,
            size_code=size_code,
        )
        # Fit-profile creation bumps the patient's version (OCC parent).
        patient = _ok("get_patient", api_client.get_patient(patient["id"], INTAKE))
    pa = None
    if with_pa:
        pa = create_prior_authorization(
            patient["id"],
            hcpcs_code=hcpcs_code,
            approved_units=pa_approved_units,
            valid_from=pa_valid_from,
            valid_to=pa_valid_to,
        )
        if pa_decision:
            pa = decide_prior_authorization(pa["id"], pa_decision)
    return {
        "plan": plan,
        "item": item,
        "stock": stock,
        "patient": patient,
        "rx": rx,
        "fit": fit,
        "pa": pa,
    }


# ---------------------------------------------------------------------------
# Tier 3 composite: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def build_submitted_order(ctx, quantity=10, size_code="45MM") -> dict:
    """DRAFT order + one line + submit. Returns ctx enriched with order/line."""
    patient_id = ctx["patient"]["id"]
    order = create_manual_order(patient_id)
    line = add_order_line(
        order["id"], order["version"], ctx["item"]["id"],
        size_code=size_code, quantity=quantity, patient_id=patient_id,
    )
    order = submit_order(order["id"], patient_id)
    return {**ctx, "order": order, "line": line}


def build_delivered_order(ctx, quantity=10, size_code="45MM") -> dict:
    """Full chain to a FULFILLED order: line, submit, shipment, release, ship, deliver."""
    ctx = build_submitted_order(ctx, quantity=quantity, size_code=size_code)
    shipment = create_shipment_for_order(ctx["order"]["id"])
    release_shipment(shipment["id"])
    ship_shipment(shipment["id"])
    shipment = deliver_shipment(shipment["id"])
    order = get_order(ctx["order"]["id"])
    return {**ctx, "order": order, "shipment": shipment}


# ---------------------------------------------------------------------------
# Tier 4 composite: resupply program cycle helpers
# ---------------------------------------------------------------------------

def confirm_cycle(program_id, patient_id) -> dict:
    """Confirm the due cycle as the owning Patient. Returns the program order."""
    return _ok(
        "confirm_cycle",
        api_client.confirm_cycle(program_id, make_patient_headers(patient_id)),
    )


def fulfill_program_order(order_id) -> dict:
    """Shipment create + release + ship for a SUBMITTED program order."""
    shipment = create_shipment_for_order(order_id)
    release_shipment(shipment["id"])
    ship_shipment(shipment["id"])
    return get_shipment(shipment["id"])


def setup_program_with_delivered_cycle(
    frequency_days=30,
    start_date="2026-05-01",
    deliver_clock="2026-05-03T00:00:00Z",
    category="OSTOMY",
    **kwargs,
) -> dict:
    """Program whose first cycle is confirmed at start_date and DELIVERED at
    deliver_clock. Clock is left at deliver_clock. Returns ctx with program,
    first order (ord1), and its shipment (shp1)."""
    ctx = setup_active_patient_with_item(category=category, on_hand_qty=500, **kwargs)
    program = create_program(
        ctx["patient"]["id"], category=category,
        frequency_days=frequency_days, start_date=start_date,
    )
    ord1 = confirm_cycle(program["id"], ctx["patient"]["id"])
    shp1 = fulfill_program_order(ord1["id"])
    set_logical_clock(deliver_clock)
    shp1 = deliver_shipment(shp1["id"])
    return {**ctx, "program": program, "ord1": ord1, "shp1": shp1}


def setup_two_cycle_adherence_scenario() -> dict:
    """Program with cycle 1 DELIVERED (2026-05-03) and cycle 2 SHIPPED
    (2026-06-04, in transit); clock ends at 2026-07-15 (3 cycles due)."""
    ctx = setup_program_with_delivered_cycle()
    program = ctx["program"]
    patient_id = ctx["patient"]["id"]
    set_logical_clock("2026-06-02T00:00:00Z")
    ord2 = confirm_cycle(program["id"], patient_id)
    shp2 = create_shipment_for_order(ord2["id"])
    release_shipment(shp2["id"])
    set_logical_clock("2026-06-04T00:00:00Z")
    shp2 = ship_shipment(shp2["id"])
    set_logical_clock("2026-07-15T00:00:00Z")
    return {**ctx, "ord2": ord2, "shp2": shp2}
