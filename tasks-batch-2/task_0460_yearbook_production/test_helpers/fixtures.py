"""Composite setup helpers for multi-step test prerequisites (Yearbook Production).

Every test runs against a fresh, empty database (the harness restarts the server
before each test), so these helpers build all preconditions from scratch using only
PRD-declared endpoints. They use get_success_data() (lenient) internally so setup
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_yearbook_payload,
    create_page_payload,
    create_submission_payload,
    create_staff_assignment_payload,
    create_ad_contract_payload,
    create_proof_payload,
    create_presale_order_payload,
    create_print_run_payload,
)
from .test_users import TEST_USERS

ADVISER = TEST_USERS["adviser_headers"]
STAFF = TEST_USERS["staff_headers"]
CONTRIBUTOR = TEST_USERS["contributor_headers"]
SALESREP = TEST_USERS["salesrep_headers"]

EARLY_CLOCK_ISO = "2026-02-01T00:00:00Z"


# ─── Tier 0: Clock ────────────────────────────────────────────────────────────

def set_clock(to_iso: str):
    """Advance the server logical clock to `to_iso`."""
    return get_success_data(api_client.set_clock(to_iso, ADVISER))


# ─── Tier 1: Yearbook creation ────────────────────────────────────────────────

def create_yearbook(**overrides):
    """Create a Yearbook. Returns the created yearbook dict (includes version)."""
    res = api_client.create_yearbook(create_yearbook_payload(**overrides), ADVISER)
    return get_success_data(res)


def create_yearbook_early_window(**overrides):
    """Create a Yearbook and advance the clock into the EARLY pre-sale window
    (2026-02-01, between presale_open 2026-01-01 and presale_close 2026-03-01)."""
    yb = create_yearbook(**overrides)
    set_clock(EARLY_CLOCK_ISO)
    return yb


# ─── Tier 2: Ladder pages ─────────────────────────────────────────────────────

def create_page(yearbook_id, page_number, section, **overrides):
    """Add a single ladder page. Returns the created page dict."""
    res = api_client.create_page(
        create_page_payload(yearbook_id, page_number, section, **overrides), ADVISER
    )
    return get_success_data(res)


def create_active_staff_assignment(yearbook_id, **overrides):
    """Create an ACTIVE staff assignment scoped to the yearbook. Returns the assignment."""
    res = api_client.create_staff_assignment(
        create_staff_assignment_payload(yearbook_id, **overrides), ADVISER
    )
    return get_success_data(res)


def create_ads_page_with_ad(yearbook_id, page_number=2, size="HALF",
                            discount_pct=None, sponsor_name="Joe Pizza"):
    """Create an ADS-section page and a DRAFT AdContract referencing it.
    Returns (page, ad_contract)."""
    page = create_page(yearbook_id, page_number, "ADS", template_code="T-AD")
    payload = create_ad_contract_payload(
        yearbook_id, page["id"], sponsor_name=sponsor_name, size=size
    )
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    ad = get_success_data(api_client.create_ad_contract(payload, SALESREP))
    return page, ad


def create_signed_ad(yearbook_id, page_number=2, size="HALF", discount_pct=0.10):
    """ADS page + AdContract SIGNED (ad_revenue_cents reflects net_price_cents).
    Returns (page, signed_ad)."""
    page, ad = create_ads_page_with_ad(
        yearbook_id, page_number=page_number, size=size, discount_pct=discount_pct
    )
    signed = get_success_data(api_client.sign_ad_contract(ad["id"], SALESREP))
    return page, signed


# ─── Tier 3: Approved pages and full-ladder yearbooks ─────────────────────────

def create_approved_page(yearbook_id, assignment_id, page_number, section,
                         template_code="T"):
    """Create an assigned page with required_submission_count=0, drive it
    DRAFT → IN_REVIEW → APPROVED. Returns the approved page dict."""
    page = create_page(
        yearbook_id, page_number, section, template_code=template_code,
        required_submission_count=0, assigned_staff_id=assignment_id,
    )
    get_success_data(api_client.submit_review_page(page["id"], STAFF))
    return get_success_data(api_client.approve_page(page["id"], ADVISER))


def create_full_approved_yearbook(target_page_count=4):
    """Create a target_page_count=N yearbook, an ACTIVE assignment, and N approved
    pages (ladder complete, every page APPROVED). Returns (yearbook, assignment, pages)."""
    yb = create_yearbook(school_name="Tiny High", target_page_count=target_page_count)
    sa = create_active_staff_assignment(yb["id"])
    sections = ["STUDENT_LIFE", "ACADEMICS", "SPORTS", "CLUBS", "SIGNATURE", "ADS"]
    pages = []
    for i in range(1, target_page_count + 1):
        page = create_approved_page(
            yb["id"], sa["id"], i, sections[(i - 1) % len(sections)]
        )
        pages.append(page)
    return yb, sa, pages


def create_yearbook_with_open_proof_all_approved(target_page_count=4):
    """Full-approved yearbook plus one OPEN proof. Returns (yearbook, assignment, pages, proof)."""
    yb, sa, pages = create_full_approved_yearbook(target_page_count)
    proof = get_success_data(
        api_client.create_proof(create_proof_payload(yb["id"], reviewer_note="round 1"), ADVISER)
    )
    return yb, sa, pages, proof


def create_yearbook_with_plant_submitted_proof(target_page_count=4):
    """Full-approved yearbook + proof submitted to plant (pages now LOCKED, phase PLANT).
    Returns (yearbook, assignment, pages, proof)."""
    yb, sa, pages, proof = create_yearbook_with_open_proof_all_approved(target_page_count)
    proof = get_success_data(api_client.submit_plant_proof(proof["id"], ADVISER))
    return yb, sa, pages, proof


# ─── Tier 4: Pre-sale orders and print runs ───────────────────────────────────

def create_paid_order(yearbook_id, buyer_name="Pat", quantity=1, **overrides):
    """Create a pre-sale order (EARLY window assumed already set) and pay it.
    Returns the PAID order dict."""
    order = get_success_data(
        api_client.create_presale_order(
            create_presale_order_payload(yearbook_id, buyer_name=buyer_name,
                                         quantity=quantity, **overrides),
            SALESREP,
        )
    )
    return get_success_data(api_client.pay_presale_order(order["id"], SALESREP))


def current_yearbook_version(yearbook_id):
    """Read the yearbook's current version (for OCC-guarded print-run commits)."""
    yb = get_success_data(api_client.get_yearbook(yearbook_id, ADVISER))
    return yb["version"]


def create_committed_print_run(yearbook_id, quantity, expected_version=None):
    """Commit a print run against the yearbook's current version. Returns the run dict."""
    if expected_version is None:
        expected_version = current_yearbook_version(yearbook_id)
    return get_success_data(
        api_client.create_print_run(
            create_print_run_payload(yearbook_id, quantity, expected_version), ADVISER
        )
    )


def create_shipped_print_run(yearbook_id, quantity, expected_version=None):
    """Commit + ship a print run. Returns the SHIPPED run dict."""
    run = create_committed_print_run(yearbook_id, quantity, expected_version)
    return get_success_data(api_client.ship_print_run(run["id"], ADVISER))
