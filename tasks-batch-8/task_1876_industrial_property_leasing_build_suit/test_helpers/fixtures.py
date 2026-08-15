"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses get_success_data() so setup
failures surface as clear "Setup failed" errors.

Fixture tiers:
  1. Single-entity creation (requirement / site / land parcel)
  2. Tour progression (request -> confirm -> complete via the logical clock)
  3. LOI progression (draft -> submit -> accept) on a toured pair
  4. Execution bundle (compliance cleared -> executed LOI -> plan + invoices)
  5. Delivery / option / commission terminal-state setups
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_loi_payload,
    create_milestone_payload,
    create_option_payload,
    create_requirement_payload,
    create_review_payload,
    create_land_site_payload,
    create_site_payload,
    create_tour_payload,
    price_plan_payload,
    submit_loi_payload,
)
from .test_users import TEST_USERS, make_tenant_rep_headers

REP_1 = TEST_USERS["tenant_rep_1_headers"]
REP_2 = TEST_USERS["tenant_rep_2_headers"]
LM = TEST_USERS["leasing_manager_headers"]
PM = TEST_USERS["project_manager_headers"]
AM = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_requirement(rep_headers=None, **overrides) -> dict:
    """Register a tenant requirement; starts ACTIVE (PRD §3.1)."""
    headers = rep_headers or REP_1
    resp = api_client.create_tenant_requirement(
        create_requirement_payload(**overrides), headers
    )
    return get_success_data(resp, 201)


def create_second_requirement(**overrides) -> dict:
    """A second requirement owned by rep-002 (BlueRidge Cold Chain)."""
    defaults = {"tenant_name": "BlueRidge Cold Chain", "use_type": "COLD_STORAGE"}
    defaults.update(overrides)
    return create_requirement(rep_headers=REP_2, **defaults)


def create_bolt_requirement(**overrides) -> dict:
    """A manufacturing requirement owned by rep-001 targeting Antelope Valley."""
    defaults = {
        "tenant_name": "Bolt Manufacturing",
        "use_type": "MANUFACTURING",
        "target_submarket": "Antelope Valley",
        "required_delivery_date": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return create_requirement(rep_headers=REP_1, **defaults)


def create_site(**overrides) -> dict:
    """Register a building; starts LISTED with reserved_sf 0 (PRD §3.1)."""
    resp = api_client.create_site(create_site_payload(**overrides), LM)
    return get_success_data(resp, 201)


def create_bts_site(**overrides) -> dict:
    """The Pacific BTS Site: Antelope Valley, asking 13.20."""
    defaults = {
        "site_name": "Pacific BTS Site",
        "submarket": "Antelope Valley",
        "zoning_designation": "M-2",
        "asking_rate_psf": 13.20,
    }
    defaults.update(overrides)
    return create_site(**defaults)


def create_land_bank_site(**overrides) -> dict:
    """Register a LAND_BANK parcel (zeroed physical specs)."""
    resp = api_client.create_site(create_land_site_payload(**overrides), LM)
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 2: tour progression
# ---------------------------------------------------------------------------

def request_tour(site_id, requirement_id, rep_headers=None, **overrides) -> dict:
    """Request a tour; starts REQUESTED (PRD §3.2)."""
    headers = rep_headers or REP_1
    resp = api_client.create_tour(
        create_tour_payload(site_id, requirement_id, **overrides), headers
    )
    return get_success_data(resp, 201)


def set_logical_clock(to_iso8601: str) -> dict:
    """Move the logical clock (PRD §2.5; AssetManager-only)."""
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, AM)
    return get_success_data(resp, 200)


def confirm_and_complete_tour(tour: dict, rep_headers=None) -> dict:
    """REQUESTED -> CONFIRMED -> COMPLETED.

    The logical clock is moved to the tour's end_at before completion so the
    completion gate of PRD §3.2 passes (clock must have reached end_at).
    """
    headers = rep_headers or REP_1
    resp = api_client.confirm_tour(tour["id"], LM)
    get_success_data(resp, 200)
    set_logical_clock(tour["end_at"])
    resp = api_client.complete_tour(tour["id"], headers)
    return get_success_data(resp, 200)


def create_completed_tour(site_id, requirement_id, rep_headers=None, **overrides) -> dict:
    """Request + confirm + complete a tour in one call."""
    headers = rep_headers or REP_1
    tour = request_tour(site_id, requirement_id, headers, **overrides)
    return confirm_and_complete_tour(tour, headers)


def setup_toured_pair(req_overrides=None, site_overrides=None,
                      rep_headers=None, tour_overrides=None):
    """Requirement + site + one COMPLETED tour for the pair.

    Returns (requirement, site, tour).
    """
    headers = rep_headers or REP_1
    req = create_requirement(headers, **(req_overrides or {}))
    site = create_site(**(site_overrides or {}))
    tour = create_completed_tour(
        site["id"], req["id"], headers, **(tour_overrides or {})
    )
    return req, site, tour


def setup_bolt_toured_pair(req_overrides=None, site_overrides=None,
                           tour_overrides=None):
    """Bolt Manufacturing requirement + Pacific BTS Site + COMPLETED tour.

    Tour window 2026-08-11 10:00-11:00 (per the delivery-track scenarios).
    Returns (requirement, site, tour).
    """
    req = create_bolt_requirement(**(req_overrides or {}))
    site = create_bts_site(**(site_overrides or {}))
    tour = create_completed_tour(
        site["id"],
        req["id"],
        REP_1,
        start_at="2026-08-11T10:00:00Z",
        end_at="2026-08-11T11:00:00Z",
        **(tour_overrides or {}),
    )
    return req, site, tour


# ---------------------------------------------------------------------------
# Tier 3: LOI progression
# ---------------------------------------------------------------------------

def create_draft_loi(requirement_id, site_id, rep_headers=None, **econ) -> dict:
    """Open an LOI; starts DRAFT with negotiation_round 0 (PRD §3.3)."""
    headers = rep_headers or REP_1
    resp = api_client.create_loi(
        create_loi_payload(requirement_id, site_id, **econ), headers
    )
    return get_success_data(resp, 201)


def submit_loi(loi, rep_headers=None, **revisions) -> dict:
    """Submit (or resubmit) an LOI with the correct current version."""
    headers = rep_headers or REP_1
    payload = submit_loi_payload(loi["version"], **revisions)
    resp = api_client.submit_loi(loi["id"], payload, headers)
    return get_success_data(resp, 200)


def create_submitted_loi(requirement_id, site_id, rep_headers=None, **econ) -> dict:
    """DRAFT -> SUBMITTED. Returns the submitted LOI."""
    headers = rep_headers or REP_1
    loi = create_draft_loi(requirement_id, site_id, headers, **econ)
    return submit_loi(loi, headers)


def create_accepted_loi(requirement_id, site_id, rep_headers=None, **econ) -> dict:
    """DRAFT -> SUBMITTED -> ACCEPTED (site LISTED -> RESERVED, PRD §3.3)."""
    headers = rep_headers or REP_1
    loi = create_submitted_loi(requirement_id, site_id, headers, **econ)
    resp = api_client.accept_loi(loi["id"], LM)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 4: compliance clearance and execution bundle
# ---------------------------------------------------------------------------

def create_review(site_id, requirement_id, review_type, **overrides) -> dict:
    """Open a compliance review; starts PENDING (PRD §3.4)."""
    resp = api_client.create_compliance_review(
        create_review_payload(site_id, requirement_id, review_type, **overrides), CO
    )
    return get_success_data(resp, 201)


def clear_review(site_id, requirement_id, review_type) -> dict:
    """Create -> begin -> resolve CLEARED for one review axis (PRD §3.4)."""
    review = create_review(site_id, requirement_id, review_type)
    get_success_data(api_client.begin_compliance_review(review["id"], CO), 200)
    resp = api_client.resolve_compliance_review(
        review["id"], {"outcome": "CLEARED"}, CO
    )
    return get_success_data(resp, 200)


def clear_both_reviews(site_id, requirement_id):
    """CLEARED ENVIRONMENTAL + ZONING_USE reviews for a (site, requirement)
    pair — the twin execution gates of PRD §3.4."""
    env = clear_review(site_id, requirement_id, "ENVIRONMENTAL")
    zoning = clear_review(site_id, requirement_id, "ZONING_USE")
    return env, zoning


def get_plan_for_loi(loi_id) -> dict:
    """Fetch the single auto-created build-to-suit plan of an executed LOI."""
    resp = api_client.list_bts_plans(PM, params={"loi_id": loi_id})
    plans = get_success_data(resp, 200)
    assert isinstance(plans, list) and len(plans) == 1, (
        f"Setup failed: expected exactly one plan for LOI {loi_id}, "
        f"got {plans}"
    )
    return plans[0]


def get_invoices_for_loi(loi_id):
    """Fetch the two auto-created commission invoices of an executed LOI.

    PRD §3.5 pins the creation order — TENANT_REP first, LANDLORD_REP second —
    and list results sort by created_at ascending (PRD §2.3), so element 0 is
    the tenant-side invoice and element 1 the landlord-side invoice.
    Returns (tenant_invoice, landlord_invoice).
    """
    resp = api_client.list_commission_invoices(LM, params={"loi_id": loi_id})
    invoices = get_success_data(resp, 200)
    assert isinstance(invoices, list) and len(invoices) == 2, (
        f"Setup failed: expected two invoices for LOI {loi_id}, got {invoices}"
    )
    assert invoices[0]["broker_side"] == "TENANT_REP", (
        f"Setup failed: first invoice should be TENANT_REP, got "
        f"{invoices[0].get('broker_side')}"
    )
    assert invoices[1]["broker_side"] == "LANDLORD_REP", (
        f"Setup failed: second invoice should be LANDLORD_REP, got "
        f"{invoices[1].get('broker_side')}"
    )
    return invoices[0], invoices[1]


def setup_executed_loi(req_overrides=None, site_overrides=None,
                       tour_overrides=None, rep_headers=None, **econ) -> dict:
    """Full pipeline: toured pair -> LOI -> submit -> accept -> compliance
    CLEARED x2 -> execute.

    Returns a dict with requirement, site, tour, loi (EXECUTED), plan
    (SCHEMATIC), tenant_invoice, landlord_invoice (both ACCRUED).
    """
    headers = rep_headers or REP_1
    req, site, tour = setup_toured_pair(
        req_overrides, site_overrides, headers, tour_overrides
    )
    loi = create_accepted_loi(req["id"], site["id"], headers, **econ)
    clear_both_reviews(site["id"], req["id"])
    resp = api_client.execute_loi(loi["id"], AM)
    executed = get_success_data(resp, 200)
    plan = get_plan_for_loi(executed["id"])
    tenant_inv, landlord_inv = get_invoices_for_loi(executed["id"])
    return {
        "requirement": req,
        "site": site,
        "tour": tour,
        "loi": executed,
        "plan": plan,
        "tenant_invoice": tenant_inv,
        "landlord_invoice": landlord_inv,
    }


def setup_executed_bolt_loi(**econ) -> dict:
    """Executed LOI for Bolt Manufacturing on the Pacific BTS Site
    (12.00 base rate / 13.20 asking). Same return shape as setup_executed_loi."""
    req, site, tour = setup_bolt_toured_pair()
    defaults = {"base_rate_psf": 12.00}
    defaults.update(econ)
    loi = create_accepted_loi(req["id"], site["id"], REP_1, **defaults)
    clear_both_reviews(site["id"], req["id"])
    executed = get_success_data(api_client.execute_loi(loi["id"], AM), 200)
    plan = get_plan_for_loi(executed["id"])
    tenant_inv, landlord_inv = get_invoices_for_loi(executed["id"])
    return {
        "requirement": req,
        "site": site,
        "tour": tour,
        "loi": executed,
        "plan": plan,
        "tenant_invoice": tenant_inv,
        "landlord_invoice": landlord_inv,
    }


# ---------------------------------------------------------------------------
# Tier 5: pricing / delivery / option / commission terminal-state setups
# ---------------------------------------------------------------------------

def price_plan(plan_id, **overrides) -> dict:
    """SCHEMATIC -> PRICED with the given cost inputs (PRD §3.5)."""
    resp = api_client.price_bts_plan(plan_id, price_plan_payload(**overrides), PM)
    return get_success_data(resp, 200)


def setup_priced_plan(**econ) -> dict:
    """Executed LOI + plan priced YIELD_ON_COST with canonical cost inputs."""
    bundle = setup_executed_bolt_loi(**econ)
    bundle["plan"] = price_plan(bundle["plan"]["id"])
    return bundle


def setup_approved_plan_with_sc_milestone(actual_ready=False, **econ) -> dict:
    """Executed Bolt LOI -> plan priced YIELD_ON_COST -> approved ->
    one SUBSTANTIAL_COMPLETION milestone (planned 2027-03-01) attached.

    The converted rate 10.25 stays under the 110% cap of 13.20, so approval
    succeeds (PRD §3.5). Returns the bundle with keys plan, milestone.
    """
    bundle = setup_priced_plan(**econ)
    plan_id = bundle["plan"]["id"]
    approved = get_success_data(api_client.approve_bts_plan(plan_id, AM), 200)
    milestone = get_success_data(
        api_client.create_delivery_milestone(
            create_milestone_payload(plan_id), PM
        ),
        201,
    )
    bundle["plan"] = approved
    bundle["milestone"] = milestone
    return bundle


def setup_granted_option(execute_loi=False, zoning_outcome=None,
                         option_overrides=None, land_overrides=None) -> dict:
    """ACCEPTED LOI_A + LAND_BANK parcel + GRANTED expansion option.

    zoning_outcome: None -> no zoning review is created; "CLEARED" or
    "FLAGGED" -> the ZONING_USE review for (land parcel, requirement) is
    resolved to that outcome.
    Returns dict with requirement, site, loi, land_site, option, review.
    """
    req, site, tour = setup_toured_pair()
    loi = create_accepted_loi(req["id"], site["id"], REP_1)
    land = create_land_bank_site(**(land_overrides or {}))
    option = get_success_data(
        api_client.create_expansion_option(
            create_option_payload(loi["id"], land["id"], **(option_overrides or {})),
            LM,
        ),
        201,
    )
    review = None
    if zoning_outcome is not None:
        review = create_review(land["id"], req["id"], "ZONING_USE")
        get_success_data(api_client.begin_compliance_review(review["id"], CO), 200)
        review = get_success_data(
            api_client.resolve_compliance_review(
                review["id"], {"outcome": zoning_outcome}, CO
            ),
            200,
        )
    return {
        "requirement": req,
        "site": site,
        "tour": tour,
        "loi": loi,
        "land_site": land,
        "option": option,
        "review": review,
    }
