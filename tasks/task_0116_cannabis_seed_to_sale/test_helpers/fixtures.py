"""Composite setup helpers for the Cannabis Seed-to-Sale Compliance API.

Most interesting claims require the system to be walked through a long
provenance chain (license -> batch -> advance x2 -> harvest -> cure -> package
-> lab-result -> release) before the behaviour under test is reachable. These
helpers encapsulate those chains so each test focuses on assertions.

All setup calls use get_success_data() (the lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion error. Because the harness rebuilds an empty database before every
test, every helper builds its preconditions from scratch.

Counters keep tags (lot_tag / package_tag / license_number) unique WITHIN a
single test; the DB is empty at the start of each test so cross-test collisions
are impossible.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_headers

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


# Default opaque operator ids used throughout setups.
QA_USER = "qa-setup-1"
CM_USER = "cm-setup-1"
AUDIT_USER = "audit-setup-1"


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def reg_h():
    return TEST_USERS["state_regulator_headers"]


def cult_h():
    return TEST_USERS["cultivator_headers"]


def dist_h():
    return TEST_USERS["distribution_agent_headers"]


def bud_h():
    return TEST_USERS["budtender_headers"]


def qa_h(user_id=QA_USER):
    return make_headers("QALabUser", user_id)


def cm_h(user_id=CM_USER):
    return make_headers("ComplianceManager", user_id)


def audit_h(user_id=AUDIT_USER):
    return make_headers("InventoryAuditor", user_id)


# ---------------------------------------------------------------------------
# Tier 0: License creation
# ---------------------------------------------------------------------------
def create_license(license_type, daily_purchase_limit_grams=None,
                   state_code="CA", expires_on="2027-01-01T00:00:00Z",
                   license_number=None):
    """Create one license of the given type; returns the License resource."""
    payload = {
        "license_number": license_number or f"LIC-{license_type[:3]}-{_n()}",
        "license_type": license_type,
        "state_code": state_code,
        "expires_on": expires_on,
    }
    if daily_purchase_limit_grams is not None:
        payload["daily_purchase_limit_grams"] = daily_purchase_limit_grams
    return get_success_data(api_client.create_license(payload, reg_h()))


def create_retail_license(daily_purchase_limit_grams=28.5, **kw):
    return create_license("RETAIL", daily_purchase_limit_grams=daily_purchase_limit_grams, **kw)


def create_cultivation_license(**kw):
    return create_license("CULTIVATION", **kw)


def create_testing_license(**kw):
    return create_license("TESTING", **kw)


def create_distribution_license(**kw):
    return create_license("DISTRIBUTION", **kw)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, reg_h()))


# ---------------------------------------------------------------------------
# Tier 1: Cultivation chain — batch through flowering
# ---------------------------------------------------------------------------
def create_batch(license_id, plant_count=10, strain="Kush",
                 planted_at="2026-01-01T00:00:00Z", lot_tag=None):
    """Create an IMMATURE plant batch under a cultivation license."""
    payload = {
        "license_id": license_id,
        "lot_tag": lot_tag or f"LOT-{_n()}",
        "strain": strain,
        "plant_count": plant_count,
        "planted_at": planted_at,
    }
    return get_success_data(api_client.create_plant_batch(payload, cult_h()))


def advance_batch(batch_id):
    return get_success_data(api_client.advance_plant_batch(batch_id, cult_h()))


def create_flowering_batch(license_id, plant_count=10, **kw):
    """Create a batch and advance IMMATURE -> VEGETATIVE -> FLOWERING."""
    batch = create_batch(license_id, plant_count=plant_count, **kw)
    advance_batch(batch["id"])
    advance_batch(batch["id"])
    return batch


# ---------------------------------------------------------------------------
# Tier 2: Harvest chain — drying / cured harvest
# ---------------------------------------------------------------------------
def create_cured_harvest(license_id, wet_weight_grams=1000, dry_weight_grams=500,
                         harvest_name=None):
    """Walk batch -> flowering -> harvest -> cure; returns the CURED harvest.

    The harvest's license_id is copied from the source batch's license, so the
    supplied license_id should be the CULTIVATION license owning the batch.
    """
    batch = create_flowering_batch(license_id)
    harvest = get_success_data(api_client.create_harvest({
        "plant_batch_id": batch["id"],
        "harvest_name": harvest_name or f"H-{_n()}",
        "wet_weight_grams": wet_weight_grams,
    }, cult_h()))
    harvest = get_success_data(api_client.cure_harvest(
        harvest["id"], {"dry_weight_grams": dry_weight_grams}, cult_h()))
    return harvest


def create_drying_harvest(license_id, wet_weight_grams=1000, harvest_name=None):
    """Walk batch -> flowering -> harvest; returns the DRYING harvest (not cured)."""
    batch = create_flowering_batch(license_id)
    return get_success_data(api_client.create_harvest({
        "plant_batch_id": batch["id"],
        "harvest_name": harvest_name or f"H-{_n()}",
        "wet_weight_grams": wet_weight_grams,
    }, cult_h()))


# ---------------------------------------------------------------------------
# Tier 3: Package lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_package(harvest_id, quantity_grams=100, product_category="FLOWER",
                   package_tag=None):
    """Pull a TESTING package from a CURED harvest."""
    return get_success_data(api_client.create_package({
        "harvest_id": harvest_id,
        "package_tag": package_tag or f"PKG-{_n()}",
        "product_category": product_category,
        "quantity_grams": quantity_grams,
    }, cult_h()))


def record_lab_result(package_id, testing_license_id, thc_pct=18.0,
                      pesticide_pass=True, qa_user_id=QA_USER,
                      tested_at="2026-05-01T00:00:00Z"):
    """Record a lab result; PASS clears hold + sets thc_pct, FAIL keeps hold."""
    return get_success_data(api_client.create_lab_result({
        "package_id": package_id,
        "testing_license_id": testing_license_id,
        "thc_pct": thc_pct,
        "pesticide_pass": pesticide_pass,
        "tested_at": tested_at,
    }, qa_h(qa_user_id)))


def release_package(package_id, cm_user_id=CM_USER):
    """Release a PASSED package to ACTIVE (must differ from the QA user)."""
    return get_success_data(api_client.release_package(package_id, cm_h(cm_user_id)))


def create_active_package(cultivation_license_id, testing_license_id,
                          quantity_grams=100, product_category="FLOWER",
                          thc_pct=18.0, dry_weight_grams=None,
                          wet_weight_grams=1000, qa_user_id=QA_USER,
                          cm_user_id=CM_USER, package_tag=None):
    """Full chain to an ACTIVE, released package.

    cultivation -> flowering batch -> harvest -> cure -> package -> PASS lab ->
    release. Returns the ACTIVE Package resource. dry_weight defaults to a value
    comfortably above quantity_grams so packaging always succeeds.
    """
    if dry_weight_grams is None:
        dry_weight_grams = max(quantity_grams * 2, 500)
    harvest = create_cured_harvest(
        cultivation_license_id, wet_weight_grams=wet_weight_grams,
        dry_weight_grams=dry_weight_grams)
    pkg = create_package(harvest["id"], quantity_grams=quantity_grams,
                         product_category=product_category, package_tag=package_tag)
    record_lab_result(pkg["id"], testing_license_id, thc_pct=thc_pct,
                      pesticide_pass=True, qa_user_id=qa_user_id)
    return release_package(pkg["id"], cm_user_id=cm_user_id)


def create_failed_package(cultivation_license_id, testing_license_id,
                          quantity_grams=600, dry_weight_grams=None,
                          wet_weight_grams=1500, qa_user_id=QA_USER):
    """Chain to a FAILED package (pesticide_pass false) still holding remaining grams.

    Returns (package, harvest). dry_weight defaults to exactly quantity_grams so
    the harvest is fully packaged (remaining_weight_grams == 0) — needed for the
    failed-test destroy cascade auto-finish.
    """
    if dry_weight_grams is None:
        dry_weight_grams = quantity_grams
    harvest = create_cured_harvest(
        cultivation_license_id, wet_weight_grams=wet_weight_grams,
        dry_weight_grams=dry_weight_grams)
    pkg = create_package(harvest["id"], quantity_grams=quantity_grams,
                         product_category="FLOWER")
    record_lab_result(pkg["id"], testing_license_id, pesticide_pass=False,
                      qa_user_id=qa_user_id)
    pkg = get_success_data(api_client.get_package(pkg["id"], cult_h()))
    harvest = get_success_data(api_client.get_harvest(harvest["id"], cult_h()))
    return pkg, harvest


# ---------------------------------------------------------------------------
# Tier 4: Customer + Sale chains
# ---------------------------------------------------------------------------
def create_customer(is_medical=False, birthdate="1990-01-01T00:00:00Z",
                    medical_card_number=None):
    payload = {"birthdate": birthdate, "is_medical": is_medical}
    if medical_card_number is not None:
        payload["medical_card_number"] = medical_card_number
    return get_success_data(api_client.create_customer(payload, bud_h()))


def open_sale(retail_license_id, customer_id, sale_date="2026-06-01T00:00:00Z"):
    return get_success_data(api_client.create_sale({
        "retail_license_id": retail_license_id,
        "customer_id": customer_id,
        "sale_date": sale_date,
    }, bud_h()))


def add_sale_line(sale_id, package_id, grams):
    return get_success_data(api_client.add_sale_line(
        sale_id, {"package_id": package_id, "grams": grams}, bud_h()))


def open_sale_with_line(retail_license_id, customer_id, package_id, grams,
                        sale_date="2026-06-01T00:00:00Z"):
    """Open a sale and add one dispensing line. Returns the Sale (re-read)."""
    sale = open_sale(retail_license_id, customer_id, sale_date=sale_date)
    add_sale_line(sale["id"], package_id, grams)
    return get_success_data(api_client.get_sale(sale["id"], bud_h()))


def finalize_sale(sale_id, expected_version=None):
    """Finalize a sale, reading the current version if none supplied."""
    if expected_version is None:
        sale = get_success_data(api_client.get_sale(sale_id, bud_h()))
        expected_version = sale["version"]
    return api_client.finalize_sale(
        sale_id, {"expected_sale_version": expected_version}, bud_h())


def setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                          birthdate="1990-01-01T00:00:00Z",
                          product_category="FLOWER", package_quantity=200,
                          thc_pct=18.0):
    """Build a retail-ready scenario: RETAIL + CULTIVATION + TESTING licenses,
    one ACTIVE released package of the requested category, and a registered
    customer. Returns dict with ret, cul, lab, package, customer.
    """
    ret = create_retail_license(daily_purchase_limit_grams=daily_purchase_limit_grams)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(
        cul["id"], lab["id"], quantity_grams=package_quantity,
        product_category=product_category, thc_pct=thc_pct)
    customer = create_customer(
        is_medical=is_medical, birthdate=birthdate,
        medical_card_number="MED-1" if is_medical else None)
    return {"ret": ret, "cul": cul, "lab": lab, "package": pkg, "customer": customer}


# ---------------------------------------------------------------------------
# Tier 5: Manifest chains
# ---------------------------------------------------------------------------
def create_manifest(origin_license_id, destination_license_id):
    return get_success_data(api_client.create_manifest({
        "origin_license_id": origin_license_id,
        "destination_license_id": destination_license_id,
    }, dist_h()))


def add_manifest_line(manifest_id, package_id, grams):
    return get_success_data(api_client.add_manifest_line(
        manifest_id, {"package_id": package_id, "grams": grams}, dist_h()))


def create_draft_manifest_with_line(origin_license_id, destination_license_id,
                                    package_id, grams):
    """Create a DRAFT manifest and attach one line. Returns the Manifest (re-read)."""
    man = create_manifest(origin_license_id, destination_license_id)
    add_manifest_line(man["id"], package_id, grams)
    return get_success_data(api_client.get_manifest(man["id"], dist_h()))


def depart_manifest(manifest_id, expected_version=None):
    if expected_version is None:
        man = get_success_data(api_client.get_manifest(manifest_id, dist_h()))
        expected_version = man["version"]
    return api_client.depart_manifest(
        manifest_id, {"expected_manifest_version": expected_version}, dist_h())


def setup_departed_manifest(package_quantity=50):
    """DISTRIBUTION origin + CULTIVATION destination, one ACTIVE package
    custodied at origin, a DRAFT manifest with one line, then departed to
    IN_TRANSIT. Returns dict with dist, dest, lab, package, manifest.
    """
    dist = create_distribution_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=package_quantity)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], package_quantity)
    get_success_data(depart_manifest(man["id"], expected_version=man["version"]))
    man = get_success_data(api_client.get_manifest(man["id"], dist_h()))
    return {"dist": dist, "dest": dest, "lab": lab, "package": pkg, "manifest": man}


# ---------------------------------------------------------------------------
# Tier 6: Reconciliation
# ---------------------------------------------------------------------------
def record_reconciliation_count(package_id, counted_grams, counted_by_user_id=AUDIT_USER,
                                counted_at="2026-06-02T00:00:00Z"):
    return get_success_data(api_client.create_reconciliation_count({
        "package_id": package_id,
        "counted_by_user_id": counted_by_user_id,
        "counted_grams": counted_grams,
        "counted_at": counted_at,
    }, audit_h(counted_by_user_id)))
