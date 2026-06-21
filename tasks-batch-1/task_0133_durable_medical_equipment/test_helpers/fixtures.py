"""Composite setup helpers for the DME API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before each
test). Fixtures use get_success_data() internally so setup failures surface as
clear "Setup step failed" errors.

Identity threading: SupplierUser is entity_backed:Supplier, so every
ownership-gated supplier call uses make_supplier_headers(supplier_id) with the
actual Supplier.id, never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_supplier_headers,
    make_physician_headers,
    make_payer_headers,
)
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
PAYER = TEST_USERS["payer_headers"]

# Monotonic counter so each fixture call mints globally-unique reference keys
# (medicare_id / ptan / hcpcs_code are unique constraints, §2.10).
_SEQ = {"n": 0}


def _uniq() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]


# ─── Clock ────────────────────────────────────────────
def set_clock(iso_instant: str):
    """Advance the deterministic clock (§2.5)."""
    return get_success_data(api_client.set_clock(iso_instant, ADMIN))


# ─── Reference data (Tier 1) ──────────────────────────
def create_patient(**overrides) -> dict:
    n = _uniq()
    payload = f.create_patient_payload(
        full_name=overrides.pop("full_name", f"Patient {n}"),
        medicare_id=overrides.pop("medicare_id", f"MBI-{n:06d}"),
        **overrides,
    )
    return get_success_data(api_client.create_patient(payload, ADMIN))


def create_supplier(**overrides) -> dict:
    n = _uniq()
    payload = f.create_supplier_payload(
        name=overrides.pop("name", f"Supplier {n}"),
        ptan=overrides.pop("ptan", f"PTAN-{n:06d}"),
        **overrides,
    )
    return get_success_data(api_client.create_supplier(payload, ADMIN))


def create_item(**overrides) -> dict:
    n = _uniq()
    payload = f.create_hcpcs_item_payload(
        hcpcs_code=overrides.pop("hcpcs_code", f"K{n:05d}"),
        **overrides,
    )
    return get_success_data(api_client.create_hcpcs_item(payload, ADMIN))


def create_reference_set(item_overrides=None, supplier_overrides=None):
    """Patient + Supplier + HCPCSItem. Returns (patient, supplier, item)."""
    patient = create_patient()
    supplier = create_supplier(**(supplier_overrides or {}))
    item = create_item(**(item_overrides or {}))
    return patient, supplier, item


# ─── Order creation (Tier 1) ──────────────────────────
def create_order(item_overrides=None, supplier_overrides=None, **order_overrides):
    """Create a DRAFT order with fresh reference data.
    Returns (order, supplier, item, patient)."""
    patient, supplier, item = create_reference_set(item_overrides, supplier_overrides)
    sup_headers = make_supplier_headers(supplier["id"])
    payload = f.create_order_payload(
        patient["id"], supplier["id"], item["id"], **order_overrides
    )
    order = get_success_data(api_client.create_order(payload, sup_headers))
    return order, supplier, item, patient


# ─── State progression (Tier 1 / Tier 2) ──────────────
def activate_cmn_for_order(order, supplier, signed_date="2025-12-15",
                           length_of_need_months=12):
    """Create + activate a CMN for an order at its current version.
    Returns (cmn, new_order_version)."""
    cmn = get_success_data(
        api_client.create_cmn(
            f.create_cmn_payload(
                order["id"],
                signed_date=signed_date,
                length_of_need_months=length_of_need_months,
            ),
            PHYSICIAN,
        )
    )
    # Read the order's current version to satisfy OCC (§2.9).
    sup_headers = make_supplier_headers(supplier["id"])
    cur = get_success_data(api_client.get_order(order["id"], sup_headers))
    activated = get_success_data(
        api_client.activate_cmn(cmn["id"], cur["version"], PHYSICIAN)
    )
    new_order = get_success_data(api_client.get_order(order["id"], sup_headers))
    return activated, new_order["version"]


def drive_order_to_ready(order, supplier, *, with_cmn=False):
    """Drive a DRAFT order to READY_FOR_DELIVERY (§3.6).
    If with_cmn, activate a CMN first (for CMN-required items)."""
    sup_headers = make_supplier_headers(supplier["id"])
    if with_cmn:
        activate_cmn_for_order(order, supplier)
    get_success_data(api_client.mark_ready(order["id"], sup_headers))
    return get_success_data(api_client.get_order(order["id"], sup_headers))


def drive_order_to_delivered(order, supplier, *, with_cmn=False,
                             pod_signature_name="Signer", scheduled_for_utc="2026-01-02T00:00:00Z"):
    """Drive order to DELIVERED: mark-ready -> schedule delivery -> confirm (§3.5/§3.6).
    Returns (order_after, delivery)."""
    drive_order_to_ready(order, supplier, with_cmn=with_cmn)
    sup_headers = make_supplier_headers(supplier["id"])
    delivery = get_success_data(
        api_client.create_delivery(
            f.create_delivery_payload(order["id"], scheduled_for_utc=scheduled_for_utc),
            sup_headers,
        )
    )
    get_success_data(
        api_client.confirm_delivery(delivery["id"], pod_signature_name, sup_headers)
    )
    order_after = get_success_data(api_client.get_order(order["id"], sup_headers))
    return order_after, delivery


def drive_order_to_active(order, supplier, *, with_cmn=False, **delivered_kwargs):
    """Drive order through to ACTIVE: ...-> DELIVERED -> activate-billing (§3.6).
    Returns (order_after, delivery)."""
    order_after, delivery = drive_order_to_delivered(
        order, supplier, with_cmn=with_cmn, **delivered_kwargs
    )
    sup_headers = make_supplier_headers(supplier["id"])
    get_success_data(api_client.activate_billing(order["id"], sup_headers))
    order_after = get_success_data(api_client.get_order(order["id"], sup_headers))
    return order_after, delivery


# ─── Tier 2 / Tier 4: order + posted cycles ───────────
def setup_active_rental_order(*, item_overrides=None, supplier_overrides=None,
                              with_cmn=False, **order_overrides):
    """Create -> ACTIVE rental order. Returns (order, supplier, item, patient)."""
    item_ov = dict(item_overrides or {})
    item_ov.setdefault("billing_category", "CAPPED_RENTAL")
    order, supplier, item, patient = create_order(
        item_overrides=item_ov, supplier_overrides=supplier_overrides, **order_overrides
    )
    if with_cmn:
        # CMN activation must precede mark-ready and bumps order version.
        activate_cmn_for_order(order, supplier)
    drive_order_to_active(order, supplier, with_cmn=False)
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api_client.get_order(order["id"], sup_headers))
    return order, supplier, item, patient


def post_cycles(order, supplier, count, *, with_period_starts=None):
    """Post `count` rental cycles on an ACTIVE order (§3.7).
    If with_period_starts is given (list of ISO instants), each cycle is
    back-billed at the explicit start; otherwise defaults are used.
    Returns the list of created cycle dicts."""
    sup_headers = make_supplier_headers(supplier["id"])
    cycles = []
    for i in range(count):
        payload = None
        if with_period_starts is not None:
            payload = {"period_start_utc": with_period_starts[i]}
        cyc = get_success_data(
            api_client.post_rental_cycle(order["id"], sup_headers, payload)
        )
        cycles.append(cyc)
    return cycles


def setup_rental_with_cycles(count, *, monthly_rental_cents=10000, modifier="KX",
                             item_overrides=None, with_period_starts=None,
                             **order_overrides):
    """Active CAPPED_RENTAL order with `count` posted cycles.
    Returns (order, supplier, item, cycles)."""
    item_ov = dict(item_overrides or {})
    item_ov.setdefault("billing_category", "CAPPED_RENTAL")
    item_ov.setdefault("monthly_rental_cents", monthly_rental_cents)
    order, supplier, item, _ = setup_active_rental_order(
        item_overrides=item_ov, modifier=modifier, **order_overrides
    )
    cycles = post_cycles(order, supplier, count, with_period_starts=with_period_starts)
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api_client.get_order(order["id"], sup_headers))
    return order, supplier, item, cycles


def distinct_month_starts(n, year=2026, start_month=1):
    """Generate n distinct, non-overlapping monthly period starts (1-month spacing)."""
    out = []
    month = start_month
    yr = year
    for _ in range(n):
        out.append(f"{yr:04d}-{month:02d}-01T00:00:00Z")
        month += 1
        if month > 12:
            month = 1
            yr += 1
    return out


# ─── Tier 3 / Tier 5: audits ──────────────────────────
def open_audit(order, reason_code):
    """Open an OPEN audit (§3.11). Returns the audit dict."""
    return get_success_data(
        api_client.create_audit(f.create_audit_payload(order["id"], reason_code), PAYER)
    )


def setup_audit_ready(count, reason_code="OVERBILLED_PAST_CAP", *,
                      monthly_rental_cents=10000, modifier="KX",
                      item_overrides=None, with_period_starts=None,
                      paid_cycle_indices=None, **order_overrides):
    """Active CAPPED_RENTAL order with `count` posted cycles and an OPEN audit.
    paid_cycle_indices: 0-based positions of cycles to mark PAID before the audit.
    Returns (order, supplier, item, cycles, audit)."""
    order, supplier, item, cycles = setup_rental_with_cycles(
        count, monthly_rental_cents=monthly_rental_cents, modifier=modifier,
        item_overrides=item_overrides, with_period_starts=with_period_starts,
        **order_overrides,
    )
    for idx in (paid_cycle_indices or []):
        get_success_data(api_client.mark_paid(cycles[idx]["id"], PAYER))
    audit = open_audit(order, reason_code)
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api_client.get_order(order["id"], sup_headers))
    return order, supplier, item, cycles, audit


# ─── CPAP resupply setups ─────────────────────────────
def setup_cpap_order(*, ordered_at_utc="2026-01-01T00:00:00Z", **order_overrides):
    """A RENTAL order against a CPAP item (is_cpap=true). Returns (order, supplier, item)."""
    item_ov = {
        "billing_category": "CAPPED_RENTAL",
        "is_cpap": True,
    }
    order, supplier, item, _ = create_order(
        item_overrides=item_ov, ordered_at_utc=ordered_at_utc, **order_overrides
    )
    return order, supplier, item


def request_resupply(order, supplier, supply_kind="MASK", quantity=1):
    """Open a REQUESTED CPAP resupply. Returns the resupply dict."""
    sup_headers = make_supplier_headers(supplier["id"])
    return get_success_data(
        api_client.create_resupply(
            f.create_resupply_payload(order["id"], supply_kind=supply_kind, quantity=quantity),
            sup_headers,
        )
    )
