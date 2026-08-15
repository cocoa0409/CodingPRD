"""Composite setup helpers for the advancement pipeline tests.

Every fixture builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" pytest error.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_fundraiser_payload,
    create_prospect_payload,
    create_assessment_payload,
    create_assignment_payload,
    create_proposal_payload,
    create_agreement_payload,
    create_pledge_payload,
    create_write_off_payload,
    create_gift_payment_payload,
    create_campaign_payload,
    create_naming_opportunity_payload,
    create_valuation_payload,
    create_disbursement_payload,
    create_report_payload,
    create_recognition_society_payload,
)
from .test_users import (
    TEST_USERS,
    make_gift_officer_headers,
)

VP = TEST_USERS["vp_headers"]
VP2 = TEST_USERS["vp2_headers"]
RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
DIR2 = TEST_USERS["director2_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


def _setup_fail(ctx, resp):
    pytest.fail(f"Setup failed at {ctx}: status={resp.status_code} body={resp.text[:300]}")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def create_fundraiser(max_prospect_count=10, max_open_ask_cents=100000000, **overrides):
    """Create a fundraiser (ACTIVE, counters 0/0). Returns fundraiser dict.

    Extra keyword arguments (e.g. display_name, email) pass through to the
    payload factory so tests can distinguish multiple fundraisers."""
    options = {
        "max_prospect_count": max_prospect_count,
        "max_open_ask_cents": max_open_ask_cents,
    }
    options.update(overrides)
    resp = api_client.create_fundraiser(
        create_fundraiser_payload(**options),
        VP,
    )
    if resp.status_code != 201:
        _setup_fail("create_fundraiser", resp)
    return get_success_data(resp)


def create_prospect(full_name="Donor A", prospect_type="INDIVIDUAL", contact_email="a@x.com", **extra):
    """Create a prospect (IDENTIFIED / QUALIFICATION). Returns prospect dict."""
    resp = api_client.create_prospect(
        create_prospect_payload(
            full_name=full_name,
            prospect_type=prospect_type,
            contact_email=contact_email,
            **extra,
        ),
        RES,
    )
    if resp.status_code != 201:
        _setup_fail("create_prospect", resp)
    return get_success_data(resp)


def create_campaign(active=True, **overrides):
    """Create a campaign; activate by default. Returns campaign dict."""
    resp = api_client.create_campaign(create_campaign_payload(**overrides), VP)
    if resp.status_code != 201:
        _setup_fail("create_campaign", resp)
    campaign = get_success_data(resp)
    if active:
        resp = api_client.activate_campaign(campaign["id"], VP)
        if resp.status_code != 200:
            _setup_fail("activate_campaign", resp)
        campaign = get_success_data(resp)
    return campaign


def create_naming_opportunity(**overrides):
    resp = api_client.create_naming_opportunity(create_naming_opportunity_payload(**overrides), VP)
    if resp.status_code != 201:
        _setup_fail("create_naming_opportunity", resp)
    return get_success_data(resp)


def create_recognition_society(**overrides):
    resp = api_client.create_recognition_society(create_recognition_society_payload(**overrides), DRO)
    if resp.status_code != 201:
        _setup_fail("create_recognition_society", resp)
    return get_success_data(resp)


def get_fundraiser(f_id):
    return get_success_data(api_client.get_fundraiser(f_id, DIR))


def get_prospect(p_id, headers=None):
    return get_success_data(api_client.get_prospect(p_id, headers or RES))


def get_proposal(prop_id):
    return get_success_data(api_client.get_proposal(prop_id, VP))


def get_agreement(agr_id):
    return get_success_data(api_client.get_agreement(agr_id, VP))


def get_fund(fund_id):
    return get_success_data(api_client.get_fund(fund_id, FIN))


def get_pledge(pl_id):
    return get_success_data(api_client.get_pledge(pl_id, FIN))


def list_installments(pl_id):
    data, _meta = _paginated(api_client.list_installments(pl_id, FIN))
    return data


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def find_fund_for_agreement(agr_id):
    """Reverse-FK lookup of the restricted fund established by an agreement."""
    data, _meta = _paginated(api_client.list_funds(FIN, params={"agreement_id": agr_id}))
    if not data:
        pytest.fail(f"Setup failed: no fund found for agreement {agr_id}")
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2: research/rating chains
# ---------------------------------------------------------------------------

def rate_prospect(p_id, assessed_capacity_cents=30000000, evidence_tier="VERIFIED_DOCUMENT",
                  engagement_score=80, philanthropy_score=70, recency_score=60):
    """File an assessment and approve it. Returns the APPROVED assessment dict."""
    resp = api_client.create_assessment(
        p_id,
        create_assessment_payload(
            assessed_capacity_cents=assessed_capacity_cents,
            engagement_score=engagement_score,
            philanthropy_score=philanthropy_score,
            recency_score=recency_score,
            evidence_tier=evidence_tier,
        ),
        RES,
    )
    if resp.status_code != 201:
        _setup_fail("create_assessment", resp)
    assessment = get_success_data(resp)
    resp = api_client.review_assessment(assessment["id"], {"decision": "APPROVE"}, DIR)
    if resp.status_code != 200:
        _setup_fail("review_assessment APPROVE", resp)
    return get_success_data(resp)


def assign_prospect(f_id, p_id):
    """Assign prospect to fundraiser (AdvancementDirector). Returns assignment."""
    fundraiser = get_fundraiser(f_id)
    resp = api_client.create_assignment(
        f_id,
        create_assignment_payload(p_id, fundraiser["version"]),
        DIR,
    )
    if resp.status_code != 201:
        _setup_fail("create_assignment", resp)
    return get_success_data(resp)


def move_prospect(p_id, f_id, target_stage):
    """Move a prospect via its owning officer. Returns updated prospect."""
    officer = make_gift_officer_headers(f_id)
    resp = api_client.move_prospect(p_id, {"target_stage": target_stage}, officer)
    if resp.status_code != 200:
        _setup_fail(f"move_prospect {target_stage}", resp)
    return get_success_data(resp)


def setup_rated_assigned_prospect(assessed_capacity_cents=30000000, prospect_type="INDIVIDUAL",
                                  move_to="CULTIVATION", max_prospect_count=10,
                                  max_open_ask_cents=100000000, name="Donor A",
                                  fundraiser=None, **assessment_kw):
    """Fundraiser + prospect rated and assigned, optionally moved.

    Returns (fundraiser, prospect, assignment).
    """
    f = fundraiser or create_fundraiser(max_prospect_count, max_open_ask_cents)
    p = create_prospect(full_name=name, prospect_type=prospect_type, contact_email=f"{name.replace(' ', '').lower()}@x.com")
    rate_prospect(p["id"], assessed_capacity_cents=assessed_capacity_cents, **assessment_kw)
    asg = assign_prospect(f["id"], p["id"])
    if move_to:
        move_prospect(p["id"], f["id"], move_to)
        p = get_prospect(p["id"])
    return f, p, asg


# ---------------------------------------------------------------------------
# Tier 3: proposal lifecycle
# ---------------------------------------------------------------------------

def create_proposal_for(p_id, f_id, ask_amount_cents, proposal_type="OUTRIGHT",
                        designation_purpose="Programs"):
    """Create a DRAFT proposal with a fresh OCC pin. Returns proposal dict."""
    officer = make_gift_officer_headers(f_id)
    p = get_prospect(p_id, officer)
    resp = api_client.create_proposal(
        create_proposal_payload(
            p_id, p["version"],
            proposal_type=proposal_type,
            ask_amount_cents=ask_amount_cents,
            designation_purpose=designation_purpose,
        ),
        officer,
    )
    if resp.status_code != 201:
        _setup_fail("create_proposal", resp)
    return get_success_data(resp)


def submit_proposal(prop_id, f_id):
    officer = make_gift_officer_headers(f_id)
    resp = api_client.submit_proposal(prop_id, officer)
    if resp.status_code != 200:
        _setup_fail("submit_proposal", resp)
    return get_success_data(resp)


def review_proposal(prop_id, decision, headers, rationale=None):
    payload = {"decision": decision}
    if rationale is not None:
        payload["decision_rationale"] = rationale
    resp = api_client.review_proposal(prop_id, payload, headers)
    if resp.status_code != 200:
        _setup_fail(f"review_proposal {decision}", resp)
    return get_success_data(resp)


def create_submitted_proposal(p_id, f_id, ask_amount_cents, proposal_type="OUTRIGHT",
                              designation_purpose="Programs"):
    """DRAFT -> UNDER_REVIEW. Returns submitted proposal."""
    prop = create_proposal_for(p_id, f_id, ask_amount_cents, proposal_type, designation_purpose)
    return submit_proposal(prop["id"], f_id)


def create_approved_proposal(p_id, f_id, ask_amount_cents, proposal_type="OUTRIGHT",
                             designation_purpose="Programs"):
    """DRAFT -> UNDER_REVIEW -> APPROVED (STANDARD tier path via director)."""
    prop = create_submitted_proposal(p_id, f_id, ask_amount_cents, proposal_type, designation_purpose)
    tier = prop["approval_tier"]
    if tier == "STANDARD":
        return review_proposal(prop["id"], "APPROVE", DIR)
    elif tier == "MAJOR":
        return review_proposal(prop["id"], "APPROVE", VP)
    else:  # PRINCIPAL
        review_proposal(prop["id"], "APPROVE", VP)
        return review_proposal(prop["id"], "APPROVE", VP2)


# ---------------------------------------------------------------------------
# Tier 4: agreements, pledges, funds
# ---------------------------------------------------------------------------

def create_executed_agreement(prop, f_id, restriction_type="UNRESTRICTED",
                              amount_cents=None, purpose_code=None,
                              naming_opportunity_id=None):
    """Draft -> present -> execute. Returns the EXECUTED agreement."""
    officer = make_gift_officer_headers(f_id)
    payload = create_agreement_payload(
        restriction_type=restriction_type,
        agreement_amount_cents=amount_cents if amount_cents is not None else prop["ask_amount_cents"],
    )
    if purpose_code is not None:
        payload["purpose_code"] = purpose_code
    if naming_opportunity_id is not None:
        payload["naming_opportunity_id"] = naming_opportunity_id
    resp = api_client.create_agreement(prop["id"], payload, officer)
    if resp.status_code != 201:
        _setup_fail("create_agreement", resp)
    agr = get_success_data(resp)
    resp = api_client.present_agreement(agr["id"], officer)
    if resp.status_code != 200:
        _setup_fail("present_agreement", resp)
    resp = api_client.execute_agreement(agr["id"], VP)
    if resp.status_code != 200:
        _setup_fail("execute_agreement", resp)
    return get_success_data(resp)


def setup_executed_agreement(ask_amount_cents, proposal_type="OUTRIGHT",
                             restriction_type="UNRESTRICTED", purpose_code=None,
                             assessed_capacity_cents=30000000,
                             naming_opportunity_id=None, move_to="CULTIVATION"):
    """Full chain: fundraiser + rated/assigned/moved prospect + approved proposal
    + executed agreement. Returns dict with f, p, asg, prop, agr (and fund when restricted)."""
    f, p, asg = setup_rated_assigned_prospect(
        assessed_capacity_cents=assessed_capacity_cents, move_to=move_to,
    )
    prop = create_approved_proposal(p["id"], f["id"], ask_amount_cents, proposal_type=proposal_type)
    agr = create_executed_agreement(
        prop, f["id"], restriction_type=restriction_type,
        purpose_code=purpose_code, naming_opportunity_id=naming_opportunity_id,
    )
    out = {"f": f, "p": get_prospect(p["id"]), "asg": asg, "prop": prop, "agr": agr}
    if restriction_type in ("RESTRICTED_CURRENT_USE", "ENDOWED"):
        out["fund"] = find_fund_for_agreement(agr["id"])
    return out


def create_pledge_for(agr_id, f_id, total_amount_cents, installment_count=1,
                      frequency="ANNUAL", first_due_date="2026-12-01T00:00:00Z",
                      campaign_id=None):
    officer = make_gift_officer_headers(f_id)
    payload = create_pledge_payload(
        agr_id,
        total_amount_cents=total_amount_cents,
        installment_count=installment_count,
        frequency=frequency,
        first_due_date=first_due_date,
    )
    if campaign_id is not None:
        payload["campaign_id"] = campaign_id
    resp = api_client.create_pledge(payload, officer)
    if resp.status_code != 201:
        _setup_fail("create_pledge", resp)
    return get_success_data(resp)


def create_payment(donor_prospect_id, amount_cents, received_at="2026-08-10T00:00:00Z",
                   payment_method="WIRE", **extra):
    payload = create_gift_payment_payload(
        donor_prospect_id, amount_cents=amount_cents, received_at=received_at,
        payment_method=payment_method, **extra,
    )
    resp = api_client.create_gift_payment(payload, FIN)
    if resp.status_code != 201:
        _setup_fail("create_gift_payment", resp)
    return get_success_data(resp)


def set_clock(to_iso8601, headers=None):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers or VP)
    if resp.status_code != 200:
        _setup_fail(f"set_clock {to_iso8601}", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: fully-assembled composite scenarios
# ---------------------------------------------------------------------------

def setup_endowed_fund_active(balance_cents=3000000, ask_amount_cents=3000000,
                              payment_received_at="2026-08-05T00:00:00Z"):
    """ENDOWED agreement executed + a direct fund payment activating the fund.

    Returns dict with f, p, prop, agr, fund (post-payment, ACTIVE when
    balance_cents >= 2500000).
    """
    ctx = setup_executed_agreement(
        ask_amount_cents, proposal_type="OUTRIGHT",
        restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
    )
    create_payment(
        ctx["p"]["id"], balance_cents, received_at=payment_received_at,
        fund_id=ctx["fund"]["id"],
    )
    ctx["fund"] = get_fund(ctx["fund"]["id"])
    return ctx


def setup_active_pledge(total_amount_cents, installment_count=1, frequency="ANNUAL",
                        first_due_date="2026-12-01T00:00:00Z", restriction_type="UNRESTRICTED",
                        purpose_code=None, campaign_id=None, proposal_type="PLEDGE",
                        assessed_capacity_cents=30000000):
    """Executed PLEDGE-type agreement + an ACTIVE pledge on it.

    Returns dict with f, p, prop, agr, pledge (+ fund when restricted).
    """
    ctx = setup_executed_agreement(
        total_amount_cents, proposal_type=proposal_type,
        restriction_type=restriction_type, purpose_code=purpose_code,
        assessed_capacity_cents=assessed_capacity_cents,
    )
    pledge = create_pledge_for(
        ctx["agr"]["id"], ctx["f"]["id"], total_amount_cents,
        installment_count=installment_count, frequency=frequency,
        first_due_date=first_due_date, campaign_id=campaign_id,
    )
    ctx["pledge"] = pledge
    return ctx
