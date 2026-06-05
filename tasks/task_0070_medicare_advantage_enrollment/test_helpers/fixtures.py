"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Both roles are opaque identifiers, so every call uses the shared role headers.
The default beneficiary date_of_birth is 2024-08-15 (day-of-month != 1); its IEP
window runs May 1 2024 .. Nov 30 2024, so the 2024 test clocks fall inside it.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_beneficiary_payload, create_plan_payload, create_enrollment_period_payload,
    create_part_b_enrollment_payload, create_part_c_enrollment_payload, confirm_part_c_payload,
    create_part_d_enrollment_payload, create_drug_claim_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["enrollment_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(iso):
    """Set the system clock; both roles may invoke it."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_beneficiary(full_name="Test Beneficiary", dob="2024-08-15T00:00:00.000Z",
                       part_d_creditable_since=None):
    """Create a beneficiary (status ACTIVE). Returns the beneficiary dict."""
    payload = create_beneficiary_payload(full_name=full_name, date_of_birth=dob)
    if part_d_creditable_since is not None:
        payload["part_d_creditable_since"] = part_d_creditable_since
    return get_success_data(api_client.create_beneficiary(payload, ADMIN))


def create_plan(name="Test Plan", part_type="PART_C", monthly_premium_cents=2000,
                star_rating=3.0, includes_drug_coverage=False):
    payload = create_plan_payload(name=name, part_type=part_type,
                                  monthly_premium_cents=monthly_premium_cents,
                                  star_rating=star_rating,
                                  includes_drug_coverage=includes_drug_coverage)
    return get_success_data(api_client.create_plan(payload, ADMIN))


def create_period(beneficiary_id, period_type, **kwargs):
    payload = create_enrollment_period_payload(period_type, **kwargs)
    return get_success_data(api_client.create_enrollment_period(beneficiary_id, payload, ADMIN))


def read_beneficiary_version(beneficiary_id):
    ben = get_success_data(api_client.get_beneficiary(beneficiary_id, ADMIN))
    return ben["version"]


# ─── Tier 2: Part B active foundation ────────────────────────────────────────

def setup_beneficiary_with_active_part_b(dob="2024-08-15T00:00:00.000Z",
                                         part_d_creditable_since=None):
    """Create a beneficiary, establish Part A, file + activate Part B under an IEP.

    Leaves the beneficiary with part_b_status=ENROLLED. Returns
    (beneficiary, iep_period, part_b_enrollment). Assumes the clock is already
    inside the IEP window (caller sets the clock first).
    """
    ben = create_beneficiary(dob=dob, part_d_creditable_since=part_d_creditable_since)
    get_success_data(api_client.establish_part_a(ben["id"], ADMIN))
    iep = create_period(ben["id"], "IEP")
    pbe = get_success_data(api_client.create_part_b_enrollment(
        create_part_b_enrollment_payload(ben["id"], iep["id"]), ADMIN))
    get_success_data(api_client.activate_part_b_enrollment(pbe["id"], ADMIN))
    return ben, iep, pbe


# ─── Tier 3: Part C lifecycle shortcuts ──────────────────────────────────────

def file_part_c(beneficiary_id, plan_id, period_id):
    """File a PENDING Part C enrollment. Returns the enrollment dict."""
    return get_success_data(api_client.create_part_c_enrollment(
        create_part_c_enrollment_payload(beneficiary_id, plan_id, period_id), ADMIN))


def confirm_part_c(enrollment_id, beneficiary_id):
    """Confirm a PENDING Part C using the beneficiary's current version. Returns the enrollment."""
    ver = read_beneficiary_version(beneficiary_id)
    return get_success_data(api_client.confirm_part_c_enrollment(
        enrollment_id, confirm_part_c_payload(ver), ADMIN))


def setup_confirmed_part_c(plan_overrides=None, dob="2024-08-15T00:00:00.000Z"):
    """Beneficiary with active Part B + one confirmed (ACTIVE) Part C enrollment.

    plan_overrides controls the Part C plan (e.g. includes_drug_coverage).
    Returns (beneficiary, iep_period, plan, part_c_enrollment).
    """
    ben, iep, _pbe = setup_beneficiary_with_active_part_b(dob=dob)
    plan = create_plan(part_type="PART_C", **(plan_overrides or {}))
    pce = file_part_c(ben["id"], plan["id"], iep["id"])
    pce = confirm_part_c(pce["id"], ben["id"])
    return ben, iep, plan, pce


def setup_confirmed_mapd_with_bundled_part_d(
        dob="2024-08-15T00:00:00.000Z", mapd_plan_overrides=None, pdp_plan_overrides=None):
    """Beneficiary with active Part B, one ACTIVE MAPD Part C, and one ACTIVE bundled
    Part D enrollment.

    The bundled Part D is filed while the MAPD Part C is still PENDING (PRD §3.7 only
    forbids a standalone Part D when an MAPD Part C is already ACTIVE), then the Part D
    is confirmed, then the Part C is confirmed -- the only PRD-faithful ordering that
    leaves both ACTIVE simultaneously. Returns (beneficiary, iep_period, mapd_plan,
    pdp_plan, part_c_enrollment, part_d_enrollment).
    """
    ben, iep, _pbe = setup_beneficiary_with_active_part_b(dob=dob)
    mapd_kwargs = {"name": "MAPD", "includes_drug_coverage": True}
    mapd_kwargs.update(mapd_plan_overrides or {})
    mapd = create_plan(part_type="PART_C", **mapd_kwargs)
    pdp_kwargs = {"name": "PDP", "star_rating": 4.0, "includes_drug_coverage": True}
    pdp_kwargs.update(pdp_plan_overrides or {})
    pdp = create_plan(part_type="PART_D", **pdp_kwargs)
    pce = file_part_c(ben["id"], mapd["id"], iep["id"])
    pde = get_success_data(api_client.create_part_d_enrollment(
        create_part_d_enrollment_payload(ben["id"], pdp["id"], iep["id"]), ADMIN))
    pde = get_success_data(api_client.confirm_part_d_enrollment(pde["id"], ADMIN))
    pce = confirm_part_c(pce["id"], ben["id"])
    return ben, iep, mapd, pdp, pce, pde


# ─── Tier 4: Part D lifecycle + drug-claim accumulation ──────────────────────

def setup_pending_part_d(dob="2024-08-15T00:00:00.000Z", part_d_creditable_since=None,
                         star_rating=3.0):
    """Beneficiary + IEP + PDP plan + PENDING Part D enrollment (no Part B/A needed).

    Returns (beneficiary, iep_period, pdp_plan, part_d_enrollment).
    Assumes the clock is already inside the IEP window for the create.
    """
    ben = create_beneficiary(dob=dob, part_d_creditable_since=part_d_creditable_since)
    iep = create_period(ben["id"], "IEP")
    pdp = create_plan(name="PDP", part_type="PART_D", star_rating=star_rating,
                      includes_drug_coverage=True)
    pde = get_success_data(api_client.create_part_d_enrollment(
        create_part_d_enrollment_payload(ben["id"], pdp["id"], iep["id"]), ADMIN))
    return ben, iep, pdp, pde


def setup_active_part_d(dob="2024-08-15T00:00:00.000Z", part_d_creditable_since=None,
                        confirm_clock=None):
    """As setup_pending_part_d, then confirm to ACTIVE.

    If confirm_clock is given, the clock is advanced to it before confirm (affects
    uncovered_months). Returns (beneficiary, iep_period, pdp_plan, part_d_enrollment).
    """
    ben, iep, pdp, pde = setup_pending_part_d(dob=dob, part_d_creditable_since=part_d_creditable_since)
    if confirm_clock is not None:
        set_clock(confirm_clock)
    pde = get_success_data(api_client.confirm_part_d_enrollment(pde["id"], ADMIN))
    return ben, iep, pdp, pde


def post_claim(part_d_enrollment_id, list_price_cents, incurred_at):
    """Post a single drug claim. Returns the claim dict."""
    return get_success_data(api_client.post_drug_claim(
        part_d_enrollment_id, create_drug_claim_payload(list_price_cents, incurred_at), ADMIN))


def setup_active_part_d_with_total(target_total_cents, dob="2024-08-15T00:00:00.000Z"):
    """ACTIVE Part D enrollment driven so total_drug_cost_cents == target_total_cents
    via a single seeding claim (T advances by the claim's full list_price).

    Returns (beneficiary, part_d_enrollment) where the enrollment was refetched after
    the seeding claim. Used for boundary tests that need T at an exact value before
    the trigger claim.
    """
    ben, _iep, _pdp, pde = setup_active_part_d(dob=dob)
    if target_total_cents > 0:
        post_claim(pde["id"], target_total_cents, "2024-11-05T00:00:00.000Z")
    pde = get_success_data(api_client.get_part_d_enrollment(pde["id"], ADMIN))
    return ben, pde
