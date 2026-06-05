"""Composite setup helpers.

Each test runs against a freshly restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls go through get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" message.

Operator-identity note: AssetManager and ComplianceOfficer are opaque ids; the
disposal segregation-of-duties check is the only place where the two are
compared, so the disposal fixtures keep the submitter (mgr-1) and approver
(co-1) deliberately distinct.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_asset_manager_headers,
)

MGR = TEST_USERS["asset_manager_headers"]            # X-User-ID = mgr-1
CO = TEST_USERS["compliance_officer_headers"]        # X-User-ID = co-1


# ─── Clock ────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the server clock; returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, MGR))


# ─── Tier 1/2: reference data ────────────────────────
def create_vendor(vendor_type="HARDWARE", name="Acme Supplier", **overrides):
    payload = {
        "name": name,
        "vendor_type": vendor_type,
        "support_email": "support@example.com",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_vendor(payload, MGR))


def create_employee(email="employee@example.com", **overrides):
    payload = {"full_name": "Test Employee", "email": email, "department": "ENG"}
    payload.update(overrides)
    return get_success_data(api_client.create_employee(payload, MGR))


def create_software_product(vendor_id, license_model="PER_SEAT", name="EditorPro", **overrides):
    payload = {"vendor_id": vendor_id, "name": name, "license_model": license_model}
    payload.update(overrides)
    return get_success_data(api_client.create_software_product(payload, MGR))


def create_hardware(vendor_id, asset_tag="TAG-001", category="LAPTOP",
                    purchase_cost_cents=100000, in_service_date="2025-01-01T00:00:00.000Z",
                    **overrides):
    payload = {
        "vendor_id": vendor_id,
        "asset_tag": asset_tag,
        "category": category,
        "purchase_cost_cents": purchase_cost_cents,
        "in_service_date": in_service_date,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_hardware(payload, MGR))


def create_entitlement(software_product_id, vendor_id, entitled_units=5,
                       unit_price_cents=1000, term_start="2025-01-01T00:00:00.000Z",
                       term_end="2025-12-31T00:00:00.000Z", **overrides):
    payload = {
        "software_product_id": software_product_id,
        "vendor_id": vendor_id,
        "entitled_units": entitled_units,
        "unit_price_cents": unit_price_cents,
        "term_start": term_start,
        "term_end": term_end,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_entitlement(payload, MGR))


def activate_entitlement(entitlement_id):
    return get_success_data(api_client.activate_entitlement(entitlement_id, MGR))


def create_coverage(hardware_asset_id, vendor_id, coverage_type="WARRANTY",
                    coverage_start="2025-01-01T00:00:00.000Z",
                    coverage_end="2025-12-31T00:00:00.000Z", **overrides):
    payload = {
        "hardware_asset_id": hardware_asset_id,
        "vendor_id": vendor_id,
        "coverage_type": coverage_type,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_coverage(payload, MGR))


# ─── Tier 2: product + active entitlement bundle ─────
def setup_product_with_active_entitlement(vendor_type="SOFTWARE", license_model="PER_SEAT",
                                          entitled_units=5, unit_price_cents=1000,
                                          term_start="2025-01-01T00:00:00.000Z",
                                          term_end="2025-12-31T00:00:00.000Z",
                                          grace_days=None, core_factor=None,
                                          min_core_units=None):
    """Vendor + product + ACTIVE entitlement. Returns
    (vendor, product, entitlement) where entitlement is the post-activate read."""
    vendor = create_vendor(vendor_type=vendor_type, name="SW Co")
    prod_overrides = {}
    if core_factor is not None:
        prod_overrides["core_factor"] = core_factor
    if min_core_units is not None:
        prod_overrides["min_core_units"] = min_core_units
    product = create_software_product(
        vendor["id"], license_model=license_model, **prod_overrides
    )
    ent_overrides = {}
    if grace_days is not None:
        ent_overrides["grace_days"] = grace_days
    entitlement = create_entitlement(
        product["id"], vendor["id"], entitled_units=entitled_units,
        unit_price_cents=unit_price_cents, term_start=term_start, term_end=term_end,
        **ent_overrides,
    )
    activated = activate_entitlement(entitlement["id"])
    return vendor, product, activated


# ─── Tier 3/4: installs against an entitlement ───────
def create_pending_install(product_id, hardware_id, entitlement_id):
    """Create a PENDING install, re-reading the entitlement's current version
    immediately before the create so the OCC check passes."""
    ent = get_success_data(api_client.get_entitlement(entitlement_id, MGR))
    payload = {
        "software_product_id": product_id,
        "hardware_asset_id": hardware_id,
        "license_entitlement_id": entitlement_id,
        "expected_entitlement_version": ent["version"],
    }
    return get_success_data(api_client.create_installation(payload, MGR))


def create_active_install(product_id, hardware_id, entitlement_id):
    """Create then activate an install (consumes capacity). Returns the
    activated install read."""
    install = create_pending_install(product_id, hardware_id, entitlement_id)
    return get_success_data(api_client.activate_installation(install["id"], MGR))


def setup_entitlement_with_active_installs(num_active, entitled_units=5,
                                           license_model="PER_SEAT",
                                           extra_pending=0):
    """Active entitlement with `num_active` ACTIVE installs and `extra_pending`
    PENDING installs, all charged to the same entitlement and hosted on one asset.

    Returns (vendor, product, entitlement, asset, active_ids, pending_ids).
    Re-reads version before every install create to satisfy OCC.
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model=license_model,
        entitled_units=entitled_units,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-INST", category="DESKTOP")
    active_ids = []
    for _ in range(num_active):
        inst = create_active_install(product["id"], asset["id"], entitlement["id"])
        active_ids.append(inst["id"])
    pending_ids = []
    for _ in range(extra_pending):
        inst = create_pending_install(product["id"], asset["id"], entitlement["id"])
        pending_ids.append(inst["id"])
    return vendor, product, entitlement, asset, active_ids, pending_ids


# ─── Tier 1/3: hardware + employee ───────────────────
def setup_employee_and_asset(emp_overrides=None, asset_overrides=None,
                             vendor_type="HARDWARE"):
    """ACTIVE employee + IN_STOCK asset under one vendor.
    Returns (vendor, employee, asset)."""
    vendor = create_vendor(vendor_type=vendor_type, name="HW Corp")
    employee = create_employee(**(emp_overrides or {}))
    asset = create_hardware(vendor["id"], **(asset_overrides or {}))
    return vendor, employee, asset


def open_checkout(asset_id, employee_id, checkout_at="2025-02-01T00:00:00.000Z",
                  expected_return_at="2025-02-10T00:00:00.000Z"):
    payload = {
        "employee_id": employee_id,
        "checkout_at": checkout_at,
        "expected_return_at": expected_return_at,
    }
    return get_success_data(api_client.checkout_hardware(asset_id, payload, MGR))


# ─── Tier 5: disposal lifecycle ──────────────────────
def submit_disposal(asset_id, reason="END_OF_LIFE", proposed_proceeds_cents=None,
                    submitter_id="mgr-1"):
    """Submit a disposal request as the given AssetManager operator id.
    Returns the SUBMITTED request."""
    payload = {"hardware_asset_id": asset_id, "reason": reason}
    if proposed_proceeds_cents is not None:
        payload["proposed_proceeds_cents"] = proposed_proceeds_cents
    headers = make_asset_manager_headers(submitter_id)
    return get_success_data(api_client.create_disposal_request(payload, headers))


def submit_and_approve_disposal(asset_id, reason="END_OF_LIFE",
                                proposed_proceeds_cents=None,
                                submitter_id="mgr-1", approver_id="co-1"):
    """Submit (as submitter_id) then approve (as a distinct approver_id) a
    disposal request — asset moves to RETIRED. Returns the APPROVED request."""
    request = submit_disposal(
        asset_id, reason=reason, proposed_proceeds_cents=proposed_proceeds_cents,
        submitter_id=submitter_id,
    )
    approver = make_compliance_officer_headers(approver_id)
    return get_success_data(api_client.approve_disposal(request["id"], approver))


def dispose_asset(asset_id, reason="END_OF_LIFE", proposed_proceeds_cents=None,
                  submitter_id="mgr-1", approver_id="co-1"):
    """Full disposal: submit → approve → complete. Asset ends DISPOSED.
    Returns the COMPLETED request."""
    request = submit_and_approve_disposal(
        asset_id, reason=reason, proposed_proceeds_cents=proposed_proceeds_cents,
        submitter_id=submitter_id, approver_id=approver_id,
    )
    approver = make_compliance_officer_headers(approver_id)
    return get_success_data(api_client.complete_disposal(request["id"], approver))


# ─── Tier 3: renewal order ───────────────────────────
def create_entitlement_renewal_order(entitlement_id, extend_months=6, added_units=None):
    payload = {
        "target_type": "ENTITLEMENT",
        "license_entitlement_id": entitlement_id,
        "extend_months": extend_months,
    }
    if added_units is not None:
        payload["added_units"] = added_units
    return get_success_data(api_client.create_renewal_order(payload, CO))


def create_coverage_renewal_order(coverage_id, extend_months=12):
    payload = {
        "target_type": "COVERAGE",
        "warranty_lease_id": coverage_id,
        "extend_months": extend_months,
    }
    return get_success_data(api_client.create_renewal_order(payload, CO))


# ─── Tier 4/5: true-up reconciliation ────────────────
def create_true_up(product_id, variant="LIVE", as_of=None):
    payload = {"software_product_id": product_id, "variant": variant}
    if as_of is not None:
        payload["as_of"] = as_of
    return get_success_data(api_client.create_true_up(payload, CO))


def setup_over_deployed_finding(as_of="2025-03-01T00:00:00.000Z"):
    """Build an AUDIT over-deployed true-up that mints exactly one
    ComplianceFinding: entitled=1, 1 ACTIVE install + 1 PENDING install
    (audit counts both = 2 consumed) → position -1, OVER_DEPLOYED.

    Returns (product, entitlement, true_up_finalized).
    """
    set_clock(as_of)
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=1,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-FND", category="DESKTOP")
    # One ACTIVE install (consumes the single seat).
    create_active_install(product["id"], asset["id"], entitlement["id"])
    # One PENDING install (counts under AUDIT only).
    create_pending_install(product["id"], asset["id"], entitlement["id"])
    true_up = create_true_up(product["id"], variant="AUDIT", as_of=as_of)
    finalized = get_success_data(api_client.finalize_true_up(true_up["id"], CO))
    return product, entitlement, finalized
