"""Composite setup helpers — multi-step preambles tests can reuse.

The ad-delivery pipeline is long: advertiser create -> qualification
upload -> qualification review -> recharge wallet -> activate -> create
campaign -> create ad-group -> create creative -> prescreen -> human
review approve -> activate campaign+ad-group -> run auction -> ingest
billing event -> ... Many test claims need the system in a late-pipeline
state; these helpers reach it.

IDENTITY THREADING — PRD §2.1:

- AccountOwner, CampaignManager, FinanceOfficer are ENTITY-BACKED.
  X-User-ID == external_user_id of an AccountUser row belonging to the
  advertiser scope. Every call whose success requires an ownership match
  (POST /advertisers/{aid}/campaigns, POST .../ad-groups, POST
  .../creatives, POST .../wallet/transactions, etc.) MUST mint headers
  via make_account_owner_headers / make_campaign_manager_headers /
  make_finance_officer_headers with that AccountUser's external_user_id.
  Fixtures below mint a per-advertiser AccountUser for each role and
  return its external_user_id alongside the advertiser.

- PlatformAdmin, CreativeReviewer, ExchangeService, MeasurementPartner,
  AntiFraudService are OPAQUE — shared constants are canonical.
  CreativeReviewer additionally has segregation-of-duties: the reviewer
  X-User-ID must not collide with any AccountUser external_user_id of
  the creative's owning advertiser. The default reviewer ids never
  collide with our advertiser-side ids, so the shared constants are
  safe.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_LOW_BALANCE_THRESHOLD_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    advance_clock_payload,
    appeal_decide_payload,
    appeal_payload,
    create_account_user_payload,
    create_ad_group_payload,
    create_advertiser_payload,
    create_billing_event_payload,
    create_campaign_payload,
    create_conversion_payload,
    create_creative_payload,
    create_wallet_tx_payload,
    human_review_payload,
    iso_offset,
    prescreen_payload,
    random_suffix,
    review_qualification_payload,
    run_auction_payload,
    upload_qualification_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_owner_headers,
    make_anti_fraud_service_headers,
    make_campaign_manager_headers,
    make_creative_reviewer_headers,
    make_exchange_service_headers,
    make_finance_officer_headers,
    make_measurement_partner_headers,
)


# ===========================================================================
# Clock (PRD §3.9 — PlatformAdmin only)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.advance_clock(seconds, headers)
    return get_success_data(res)


# ===========================================================================
# Advertiser primitives
# ===========================================================================
def create_advertiser(**overrides: Any) -> Dict[str, Any]:
    """Create an advertiser. Returns the Advertiser resource.

    Defaults: PREPAY / GENERAL / INDEPENDENT / tax_rate_bps=0.
    """
    res = api_client.create_advertiser(
        create_advertiser_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def get_advertiser(advertiser_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.get_advertiser(advertiser_id, headers)
    return get_success_data(res)


def upload_qualification(advertiser_id: str,
                         doc_type: str = "BUSINESS_LICENSE",
                         expiry_days_from_now: int = 365,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.upload_qualification(
        advertiser_id,
        upload_qualification_payload(
            doc_type=doc_type,
            expiry_date=iso_offset(days=expiry_days_from_now),
        ),
        headers,
    )
    return get_success_data(res)


def review_qualification(advertiser_id: str, doc_id: str,
                         outcome: str = "APPROVE",
                         rejection_reason: Optional[str] = None,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.review_qualification(
        advertiser_id, doc_id,
        review_qualification_payload(
            outcome=outcome,
            rejection_reason=rejection_reason,
        ),
        headers,
    )
    return get_success_data(res)


def create_account_user(advertiser_id: str,
                        external_user_id: Optional[str] = None,
                        account_role: str = "OWNER",
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """Create an AccountUser under the advertiser. The external_user_id
    is the string the user will later present in their X-User-ID.

    By default uses PlatformAdmin to create — the AccountOwner path is
    only available once an owner exists.
    """
    headers = headers or TEST_USERS["platform_admin_headers"]
    ext = external_user_id or f"ext-{random_suffix(8)}"
    res = api_client.create_account_user(
        advertiser_id,
        create_account_user_payload(
            external_user_id=ext, account_role=account_role,
        ),
        headers,
    )
    return get_success_data(res)


def recharge_wallet(advertiser_id: str,
                    amount_cents: int = 100000,
                    idempotency_key: Optional[str] = None,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """Create a RECHARGE WalletTransaction — auto-settles per PRD §3.8.

    Headers default to PlatformAdmin (PRD §3.8 allows PlatformAdmin to
    create wallet transactions). The advertiser must have either a
    FinanceOfficer AccountUser or use PlatformAdmin.
    """
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.create_wallet_tx(
        advertiser_id,
        create_wallet_tx_payload(
            tx_type="RECHARGE",
            amount_cents=amount_cents,
            idempotency_key=idempotency_key or f"recharge-{random_suffix(8)}",
        ),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 / Tier 3 — advertiser hierarchies with identity threading.
# ===========================================================================
def setup_active_advertiser(
    *,
    industry: str = "GENERAL",
    billing_mode: str = "PREPAY",
    initial_recharge_cents: int = 100000,
    tax_rate_bps: int = 0,
    low_balance_threshold_cents: int = DEFAULT_LOW_BALANCE_THRESHOLD_CENTS,
    credit_line_cents: int = 0,
    account_type: str = "INDEPENDENT",
    parent_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end advertiser setup that reaches Advertiser.status =
    ACTIVE per PRD §3.1.

    Steps (PRD §3.1):
      1. POST /advertisers (status=PENDING, qualification_status=UNVERIFIED)
      2. POST /advertisers/{id}/qualifications — upload BUSINESS_LICENSE
         (and the industry-specific doc when industry != GENERAL)
      3. POST .../qualifications/{docId}/review — approve each
         (qualification_status -> VERIFIED)
      4. POST .../wallet/transactions — initial RECHARGE
         (balance_cents + credit_line_cents > 0 — Advertiser goes ACTIVE)

    Also creates one AccountUser per entity-backed role
    (OWNER / CAMPAIGN_MANAGER / FINANCE) so ownership-gated tests can
    mint correct headers via make_*_headers(external_user_id).

    Returns a dict with keys:
      advertiser            -> Advertiser dict (refreshed after activation)
      owner_ext_id          -> external_user_id of OWNER AccountUser
      manager_ext_id        -> external_user_id of CAMPAIGN_MANAGER user
      finance_ext_id        -> external_user_id of FINANCE user
      owner_headers         -> AccountOwner headers with owner_ext_id
      manager_headers       -> CampaignManager headers with manager_ext_id
      finance_headers       -> FinanceOfficer headers with finance_ext_id
      qualification_docs    -> list of approved QualificationDocs
    """
    overrides: Dict[str, Any] = {
        "industry_category": industry,
        "billing_mode": billing_mode,
        "tax_rate_bps": tax_rate_bps,
        "low_balance_threshold_cents": low_balance_threshold_cents,
        "credit_line_cents": credit_line_cents,
        "account_type": account_type,
    }
    if parent_account_id is not None:
        overrides["parent_account_id"] = parent_account_id
    advertiser = create_advertiser(**overrides)

    # Per-role AccountUsers (PRD §3.2 — these may be created by
    # PlatformAdmin before the advertiser is ACTIVE).
    owner_ext = f"owner-{random_suffix(8)}"
    manager_ext = f"mgr-{random_suffix(8)}"
    finance_ext = f"fin-{random_suffix(8)}"
    create_account_user(advertiser["id"], external_user_id=owner_ext,
                        account_role="OWNER")
    create_account_user(advertiser["id"], external_user_id=manager_ext,
                        account_role="CAMPAIGN_MANAGER")
    create_account_user(advertiser["id"], external_user_id=finance_ext,
                        account_role="FINANCE")

    # Qualification docs. BUSINESS_LICENSE is always uploaded; for
    # regulated industries also add the matching industry doc.
    docs: List[Dict[str, Any]] = []
    bl = upload_qualification(advertiser["id"], doc_type="BUSINESS_LICENSE")
    bl = review_qualification(
        advertiser["id"], bl["id"], outcome="APPROVE",
    )
    docs.append(bl)

    industry_doc_type = {
        "MEDICAL": "MEDICAL_PERMIT",
        "FINANCIAL": "FINANCIAL_LICENSE",
        "EDUCATION": "EDUCATION_PERMIT",
    }.get(industry)
    if industry_doc_type is not None:
        ind = upload_qualification(advertiser["id"],
                                   doc_type=industry_doc_type)
        ind = review_qualification(
            advertiser["id"], ind["id"], outcome="APPROVE",
        )
        docs.append(ind)

    # PRD §3.1: first time qualification_status reaches VERIFIED AND
    # balance_cents + credit_line_cents > 0, Advertiser -> ACTIVE.
    # Recharge to satisfy the second condition (unless caller set
    # initial_recharge_cents == 0 deliberately).
    if initial_recharge_cents > 0:
        recharge_wallet(advertiser["id"],
                        amount_cents=initial_recharge_cents)

    advertiser = get_advertiser(advertiser["id"])

    return {
        "advertiser": advertiser,
        "owner_ext_id": owner_ext,
        "manager_ext_id": manager_ext,
        "finance_ext_id": finance_ext,
        "owner_headers": make_account_owner_headers(owner_ext),
        "manager_headers": make_campaign_manager_headers(manager_ext),
        "finance_headers": make_finance_officer_headers(finance_ext),
        "qualification_docs": docs,
    }


def setup_pending_advertiser_with_doc(
    *, industry: str = "GENERAL",
) -> Dict[str, Any]:
    """Advertiser created and one BUSINESS_LICENSE uploaded but NOT yet
    reviewed — qualification_status=UNDER_REVIEW; status=PENDING.
    """
    advertiser = create_advertiser(industry_category=industry)
    doc = upload_qualification(advertiser["id"],
                               doc_type="BUSINESS_LICENSE")
    return {"advertiser": advertiser, "qualification_doc": doc}


# ===========================================================================
# Campaign + AdGroup + Creative scaffolding
# ===========================================================================
def create_campaign(advertiser_id: str,
                    manager_headers: Dict[str, str],
                    **overrides: Any) -> Dict[str, Any]:
    """Create a campaign in DRAFT (PRD §3.3). Use manager_headers minted
    from make_campaign_manager_headers(...) — ownership-gated.
    """
    res = api_client.create_campaign(
        advertiser_id,
        create_campaign_payload(**overrides),
        manager_headers,
    )
    return get_success_data(res)


def create_ad_group(advertiser_id: str, campaign_id: str,
                    manager_headers: Dict[str, str],
                    **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_ad_group(
        advertiser_id, campaign_id,
        create_ad_group_payload(**overrides),
        manager_headers,
    )
    return get_success_data(res)


def create_creative(advertiser_id: str, campaign_id: str,
                    ad_group_id: str,
                    manager_headers: Dict[str, str],
                    **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_creative(
        advertiser_id, campaign_id, ad_group_id,
        create_creative_payload(**overrides),
        manager_headers,
    )
    return get_success_data(res)


def update_ad_group(advertiser_id: str, campaign_id: str, ad_group_id: str,
                    manager_headers: Dict[str, str],
                    **overrides: Any) -> Dict[str, Any]:
    from .factories import update_ad_group_payload
    res = api_client.update_ad_group(
        advertiser_id, campaign_id, ad_group_id,
        update_ad_group_payload(**overrides),
        manager_headers,
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Creative review walkers
# ---------------------------------------------------------------------------
def prescreen_creative(creative_id: str,
                       pre_screen_score: float = 0.0,
                       outcome: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """Run pre-screen pipeline. PRD §3.4 says PlatformAdmin runs this."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.prescreen_creative(
        creative_id,
        prescreen_payload(pre_screen_score=pre_screen_score, outcome=outcome),
        headers,
    )
    return get_success_data(res)


def human_review_creative(creative_id: str,
                          outcome: str = "APPROVE",
                          rejection_codes: Optional[List[str]] = None,
                          notes: Optional[str] = None,
                          reviewer_headers: Optional[Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    reviewer_headers = (
        reviewer_headers or TEST_USERS["creative_reviewer_headers"]
    )
    res = api_client.human_review_creative(
        creative_id,
        human_review_payload(
            outcome=outcome,
            rejection_codes=rejection_codes,
            notes=notes,
        ),
        reviewer_headers,
    )
    return get_success_data(res)


def approve_creative_end_to_end(advertiser_id: str, campaign_id: str,
                                ad_group_id: str,
                                manager_headers: Dict[str, str],
                                *,
                                creative_overrides: Optional[Dict[str, Any]] = None,
                                pre_screen_score: float = 0.0,
                                reviewer_headers: Optional[Dict[str, str]] = None,
                                ) -> Dict[str, Any]:
    """Create a Creative, prescreen (pre_screen_score < 0.5 by default
    -> PENDING_HUMAN_REVIEW), human-review APPROVE -> APPROVED.

    Returns the APPROVED Creative.
    """
    creative = create_creative(
        advertiser_id, campaign_id, ad_group_id, manager_headers,
        **(creative_overrides or {}),
    )
    creative = prescreen_creative(
        creative["id"], pre_screen_score=pre_screen_score,
    )
    creative = human_review_creative(
        creative["id"], outcome="APPROVE",
        reviewer_headers=reviewer_headers,
    )
    return creative


def reject_creative_end_to_end(advertiser_id: str, campaign_id: str,
                               ad_group_id: str,
                               manager_headers: Dict[str, str],
                               *,
                               creative_overrides: Optional[Dict[str, Any]] = None,
                               pre_screen_score: float = 0.0,
                               rejection_codes: Optional[List[str]] = None,
                               reviewer_headers: Optional[Dict[str, str]] = None,
                               ) -> Dict[str, Any]:
    """Create a Creative, prescreen (escalate to human review), then
    REJECT via human-review.

    Returns the REJECTED Creative.
    """
    creative = create_creative(
        advertiser_id, campaign_id, ad_group_id, manager_headers,
        **(creative_overrides or {}),
    )
    creative = prescreen_creative(
        creative["id"], pre_screen_score=pre_screen_score,
    )
    creative = human_review_creative(
        creative["id"], outcome="REJECT",
        rejection_codes=rejection_codes or ["MISLEADING_CLAIM"],
        reviewer_headers=reviewer_headers,
    )
    return creative


# ---------------------------------------------------------------------------
# Activate campaign + ad-group
# ---------------------------------------------------------------------------
def activate_campaign(advertiser_id: str, campaign_id: str,
                      manager_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.activate_campaign(
        advertiser_id, campaign_id, manager_headers,
    )
    return get_success_data(res)


def activate_ad_group(advertiser_id: str, campaign_id: str, ad_group_id: str,
                      manager_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.activate_ad_group(
        advertiser_id, campaign_id, ad_group_id, manager_headers,
    )
    return get_success_data(res)


def pause_campaign(advertiser_id: str, campaign_id: str,
                   manager_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.pause_campaign(
        advertiser_id, campaign_id, manager_headers,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 — full pipeline preambles
# ===========================================================================
def setup_active_campaign_with_approved_creative(
    *,
    industry: str = "GENERAL",
    bid_cents: int = 500,
    bidding_strategy: str = "CPC",
    daily_budget_cents: int = 100000,
    lifetime_budget_cents: Optional[int] = None,
    initial_recharge_cents: int = 100000,
    tax_rate_bps: int = 0,
    quality_score_override: Optional[float] = None,
    predicted_ctr_override: Optional[float] = None,
    frequency_cap_per_user_per_day: Optional[int] = None,
    low_balance_threshold_cents: int = DEFAULT_LOW_BALANCE_THRESHOLD_CENTS,
    activate: bool = True,
    creative_disclaimer: Optional[str] = None,
) -> Dict[str, Any]:
    """Complete pipeline to an ACTIVE Campaign with one RUNNING AdGroup
    carrying one APPROVED Creative.

    Returns dict with: bundle (from setup_active_advertiser), campaign,
    ad_group, creative, and the auxiliary headers.
    """
    bundle = setup_active_advertiser(
        industry=industry,
        initial_recharge_cents=initial_recharge_cents,
        tax_rate_bps=tax_rate_bps,
        low_balance_threshold_cents=low_balance_threshold_cents,
    )
    advertiser = bundle["advertiser"]
    manager_headers = bundle["manager_headers"]

    campaign_kwargs: Dict[str, Any] = {
        "daily_budget_cents": daily_budget_cents,
    }
    if lifetime_budget_cents is not None:
        campaign_kwargs["lifetime_budget_cents"] = lifetime_budget_cents
    campaign = create_campaign(advertiser["id"], manager_headers,
                               **campaign_kwargs)

    ad_group_kwargs: Dict[str, Any] = {
        "bidding_strategy": bidding_strategy,
        "bid_cents": bid_cents,
    }
    if frequency_cap_per_user_per_day is not None:
        ad_group_kwargs["frequency_cap_per_user_per_day"] = (
            frequency_cap_per_user_per_day
        )
    ad_group = create_ad_group(
        advertiser["id"], campaign["id"], manager_headers,
        **ad_group_kwargs,
    )

    # Optionally tune quality_score / predicted_ctr via PUT to control
    # auction math (PRD §3.3 allows updates to these).
    if quality_score_override is not None or predicted_ctr_override is not None:
        upd: Dict[str, Any] = {}
        if quality_score_override is not None:
            upd["quality_score"] = quality_score_override
        if predicted_ctr_override is not None:
            upd["predicted_ctr"] = predicted_ctr_override
        ad_group = update_ad_group(
            advertiser["id"], campaign["id"], ad_group["id"],
            manager_headers, **upd,
        )

    creative_overrides: Dict[str, Any] = {}
    if creative_disclaimer is not None:
        creative_overrides["required_disclaimer"] = creative_disclaimer
    # For regulated industries, supply a disclaimer by default.
    elif industry in {"MEDICAL", "FINANCIAL", "EDUCATION"}:
        creative_overrides["required_disclaimer"] = (
            "Regulatory disclaimer text for compliance."
        )
    creative = approve_creative_end_to_end(
        advertiser["id"], campaign["id"], ad_group["id"], manager_headers,
        creative_overrides=creative_overrides or None,
    )

    if activate:
        campaign = activate_campaign(
            advertiser["id"], campaign["id"], manager_headers,
        )
        ad_group = activate_ad_group(
            advertiser["id"], campaign["id"], ad_group["id"], manager_headers,
        )

    return {
        "bundle": bundle,
        "advertiser": get_advertiser(advertiser["id"]),
        "campaign": campaign,
        "ad_group": ad_group,
        "creative": creative,
        "owner_headers": bundle["owner_headers"],
        "manager_headers": manager_headers,
        "finance_headers": bundle["finance_headers"],
        "owner_ext_id": bundle["owner_ext_id"],
        "manager_ext_id": bundle["manager_ext_id"],
        "finance_ext_id": bundle["finance_ext_id"],
    }


def setup_two_ad_groups_for_auction(
    *,
    g1_kwargs: Optional[Dict[str, Any]] = None,
    g2_kwargs: Optional[Dict[str, Any]] = None,
    initial_recharge_cents: int = 200000,
    tax_rate_bps: int = 0,
    activate: bool = True,
) -> Dict[str, Any]:
    """Two RUNNING AdGroups under one ACTIVE Campaign, each with one
    APPROVED Creative — used for GSP vs VCG and ranking_score tests.

    g1_kwargs and g2_kwargs override the AdGroup create_payload and may
    also include `quality_score` / `predicted_ctr` (those are written via
    a subsequent PUT, since PRD §3.3 initialises them to 5.0 / 0.02).
    """
    g1_kwargs = dict(g1_kwargs or {})
    g2_kwargs = dict(g2_kwargs or {})

    bundle = setup_active_advertiser(
        initial_recharge_cents=initial_recharge_cents,
        tax_rate_bps=tax_rate_bps,
    )
    advertiser = bundle["advertiser"]
    manager_headers = bundle["manager_headers"]

    campaign = create_campaign(
        advertiser["id"], manager_headers,
        daily_budget_cents=200000,
    )

    def _make_ad_group(kw: Dict[str, Any]) -> Dict[str, Any]:
        q = kw.pop("quality_score", None)
        p = kw.pop("predicted_ctr", None)
        ag = create_ad_group(
            advertiser["id"], campaign["id"], manager_headers, **kw,
        )
        if q is not None or p is not None:
            upd: Dict[str, Any] = {}
            if q is not None:
                upd["quality_score"] = q
            if p is not None:
                upd["predicted_ctr"] = p
            ag = update_ad_group(
                advertiser["id"], campaign["id"], ag["id"],
                manager_headers, **upd,
            )
        return ag

    g1 = _make_ad_group(g1_kwargs or {"bid_cents": 500, "bidding_strategy": "CPC"})
    g2 = _make_ad_group(g2_kwargs or {"bid_cents": 300, "bidding_strategy": "CPC"})

    # Approved creative under each.
    cr1 = approve_creative_end_to_end(
        advertiser["id"], campaign["id"], g1["id"], manager_headers,
    )
    cr2 = approve_creative_end_to_end(
        advertiser["id"], campaign["id"], g2["id"], manager_headers,
    )

    if activate:
        campaign = activate_campaign(
            advertiser["id"], campaign["id"], manager_headers,
        )
        g1 = activate_ad_group(
            advertiser["id"], campaign["id"], g1["id"], manager_headers,
        )
        g2 = activate_ad_group(
            advertiser["id"], campaign["id"], g2["id"], manager_headers,
        )

    return {
        "bundle": bundle,
        "advertiser": get_advertiser(advertiser["id"]),
        "campaign": campaign,
        "ad_group_1": g1,
        "ad_group_2": g2,
        "creative_1": cr1,
        "creative_2": cr2,
        "manager_headers": manager_headers,
    }


# ===========================================================================
# Auction + billing
# ===========================================================================
def run_auction(candidate_ad_group_ids: List[str],
                pricing_rule: str = "GSP",
                floor_price_cents: int = 1,
                user_id: Optional[str] = None,
                exchange: str = "INTERNAL",
                headers: Optional[Dict[str, str]] = None,
                **overrides: Any) -> Dict[str, Any]:
    headers = headers or TEST_USERS["exchange_service_headers"]
    payload = run_auction_payload(
        candidate_ad_group_ids=candidate_ad_group_ids,
        pricing_rule=pricing_rule,
        floor_price_cents=floor_price_cents,
        exchange=exchange,
        **overrides,
    )
    if user_id is not None:
        payload["user_id"] = user_id
    res = api_client.run_auction(payload, headers)
    return get_success_data(res)


def ingest_billing_event(auction_event_id: str,
                         ad_group_id: str,
                         event_type: str = "CLICK",
                         dedup_key: Optional[str] = None,
                         ivt_score: float = 0.0,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["exchange_service_headers"]
    res = api_client.create_billing_event(
        create_billing_event_payload(
            auction_event_id=auction_event_id,
            ad_group_id=ad_group_id,
            event_type=event_type,
            dedup_key=dedup_key,
            ivt_score=ivt_score,
        ),
        headers,
    )
    return get_success_data(res)


def run_auction_and_ingest_click(
    advertiser_id: str,
    ad_group_id: str,
    *,
    pricing_rule: str = "GSP",
    floor_price_cents: int = 1,
    user_id: Optional[str] = None,
    ivt_score: float = 0.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Helper for cost / budget / wallet pipeline tests: run an auction
    with the single ad-group and ingest a CLICK that finalises.
    Returns (auction_event, billing_event).
    """
    auc = run_auction(
        candidate_ad_group_ids=[ad_group_id],
        pricing_rule=pricing_rule,
        floor_price_cents=floor_price_cents,
        user_id=user_id,
    )
    be = ingest_billing_event(
        auction_event_id=auc["id"],
        ad_group_id=ad_group_id,
        event_type="CLICK",
        ivt_score=ivt_score,
    )
    return auc, be


def setup_finalized_billing_event(
    *,
    bid_cents: int = 100,
    floor_price_cents: int = 1,
    pricing_rule: str = "GSP",
    tax_rate_bps: int = 0,
    initial_recharge_cents: int = 100000,
    ivt_score: float = 0.0,
) -> Dict[str, Any]:
    """End-to-end pipeline reaching a FINALIZED BillingEvent that
    deducted balance_cents. Returns dict including advertiser, campaign,
    ad_group, creative, auction, billing_event, and headers.
    """
    setup = setup_active_campaign_with_approved_creative(
        bid_cents=bid_cents,
        tax_rate_bps=tax_rate_bps,
        initial_recharge_cents=initial_recharge_cents,
    )
    auc, be = run_auction_and_ingest_click(
        setup["advertiser"]["id"], setup["ad_group"]["id"],
        pricing_rule=pricing_rule,
        floor_price_cents=floor_price_cents,
        ivt_score=ivt_score,
    )
    setup["auction"] = auc
    setup["billing_event"] = be
    return setup


# ===========================================================================
# Wallet helpers (entity-backed FinanceOfficer or PlatformAdmin)
# ===========================================================================
def wallet_tx(advertiser_id: str,
              tx_type: str,
              amount_cents: int,
              *,
              idempotency_key: Optional[str] = None,
              reference_event_id: Optional[str] = None,
              note: Optional[str] = None,
              headers: Optional[Dict[str, str]] = None,
              ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    res = api_client.create_wallet_tx(
        advertiser_id,
        create_wallet_tx_payload(
            tx_type=tx_type,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            reference_event_id=reference_event_id,
            note=note,
        ),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Conversion helpers
# ===========================================================================
def create_conversion(advertiser_id: str, user_id: str,
                      *, value_cents: int = 1000,
                      attribution_window_days: int = 7,
                      attribution_model: str = "LAST_CLICK",
                      source: str = "WEB_PIXEL",
                      conversion_type: str = "PURCHASE",
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["measurement_partner_headers"]
    payload = create_conversion_payload(
        advertiser_id=advertiser_id,
        user_id=user_id,
        source=source,
        conversion_type=conversion_type,
        value_cents=value_cents,
        attribution_window_days=attribution_window_days,
        attribution_model=attribution_model,
    )
    res = api_client.create_conversion(payload, headers)
    return get_success_data(res)


def attribute_conversion(conversion_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["measurement_partner_headers"]
    res = api_client.attribute_conversion(conversion_id, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 4 — accumulation/threshold targeting fixtures
# ===========================================================================
def setup_advertiser_at_low_balance_boundary(
    *,
    low_balance_threshold_cents: int = 10000,
    target_balance_cents: int = 10000,
) -> Dict[str, Any]:
    """Reach a specific balance_cents value via RECHARGE so balance_state
    is exactly at the LOW_BALANCE / HEALTHY boundary.

    PRD §3.9: 0 < balance_cents <= low_balance_threshold_cents -> LOW_BALANCE.
    """
    bundle = setup_active_advertiser(
        initial_recharge_cents=target_balance_cents,
        low_balance_threshold_cents=low_balance_threshold_cents,
    )
    return bundle


def setup_advertiser_at_zero_balance(
    *,
    bid_cents: int = 50000,
    tax_rate_bps: int = 0,
) -> Dict[str, Any]:
    """Drive Advertiser.balance_cents down to exactly 0 by running a
    CLICK finalisation that consumes the full balance.

    Returns the same bundle as setup_active_campaign_with_approved_creative
    plus 'auction' and 'billing_event'. The advertiser will be
    SUSPENDED-equivalent in spend terms — balance_state=ZERO_BALANCE,
    Campaign + AdGroup paused via pause-on-zero (PRD §3.9).
    """
    setup = setup_active_campaign_with_approved_creative(
        bid_cents=bid_cents,
        bidding_strategy="CPC",
        daily_budget_cents=max(bid_cents * 2, 200),
        lifetime_budget_cents=max(bid_cents * 2, 200),
        initial_recharge_cents=bid_cents,
        tax_rate_bps=tax_rate_bps,
    )
    auc, be = run_auction_and_ingest_click(
        setup["advertiser"]["id"], setup["ad_group"]["id"],
        pricing_rule="GSP", floor_price_cents=bid_cents,
    )
    setup["auction"] = auc
    setup["billing_event"] = be
    setup["advertiser"] = get_advertiser(setup["advertiser"]["id"])
    return setup


def accumulate_impressions_for_user(
    ad_group_id: str, user_id: str, count: int,
    *, advertiser_id: str,
) -> List[Dict[str, Any]]:
    """Build `count` FINALIZED IMPRESSION BillingEvents for a single user
    on a single ad-group — used to put the system at the inclusive
    frequency-cap boundary (PRD §3.5 / §3.6 / freq-cap calc).

    Each impression goes through a fresh auction so the ad-group remains
    eligible (no cap has fired yet). Requires the ad-group to be CPM so
    IMPRESSION events actually finalise with non-zero gross — but per
    PRD §3.6, even a CPC ad-group will finalise IMPRESSION events with
    gross_cost_cents=0 (the strategy/event-type mismatch). The freq-cap
    counter only looks at status IN {VALID, FINALIZED}, both of which
    these reach.
    """
    out: List[Dict[str, Any]] = []
    for _ in range(count):
        auc = run_auction(
            candidate_ad_group_ids=[ad_group_id],
            user_id=user_id,
            pricing_rule="GSP",
            floor_price_cents=1,
        )
        # The auction must FILL; if not, surface immediately.
        if auc.get("outcome") != "FILLED":
            raise AssertionError(
                f"Setup failed: auction did not FILL while accumulating "
                f"impressions ({auc.get('outcome')!r})"
            )
        be = ingest_billing_event(
            auction_event_id=auc["id"],
            ad_group_id=ad_group_id,
            event_type="IMPRESSION",
            ivt_score=0.0,
        )
        out.append(be)
    return out


def setup_frequency_cap_at_boundary(
    *, cap: int = 2,
) -> Dict[str, Any]:
    """Create a CPM AdGroup with frequency_cap_per_user_per_day=cap, then
    finalise exactly `cap` IMPRESSION billing events for one user.
    The next auction with that user_id MUST filter the ad-group out
    per PRD §3.5 (>= cap is inclusive boundary).
    """
    setup = setup_active_campaign_with_approved_creative(
        bidding_strategy="CPM",
        bid_cents=1000,  # per-thousand
        frequency_cap_per_user_per_day=cap,
        initial_recharge_cents=1_000_000,
    )
    target_user = f"freqcap-user-{random_suffix(6)}"
    setup["user_id"] = target_user
    setup["impressions"] = accumulate_impressions_for_user(
        ad_group_id=setup["ad_group"]["id"],
        user_id=target_user,
        count=cap,
        advertiser_id=setup["advertiser"]["id"],
    )
    return setup


# ===========================================================================
# Tier 5 — terminal-state setups
# ===========================================================================
def setup_closed_advertiser() -> Dict[str, Any]:
    """Advertiser closed to terminal CLOSED state with cascade depth-3
    archive of Campaign -> AdGroup -> Creative.

    Pre-pauses the campaign so 'close' precondition (no ACTIVE/RUNNING
    campaigns) holds per PRD §3.1.
    """
    setup = setup_active_campaign_with_approved_creative()
    advertiser = setup["advertiser"]
    campaign = setup["campaign"]
    manager_headers = setup["manager_headers"]

    pause_campaign(advertiser["id"], campaign["id"], manager_headers)

    res = api_client.close_advertiser(
        advertiser["id"], TEST_USERS["platform_admin_headers"],
    )
    closed = get_success_data(res)
    setup["advertiser"] = closed
    return setup


def setup_rejected_creative() -> Dict[str, Any]:
    """End-to-end: REJECTED creative ready for appeal."""
    bundle = setup_active_advertiser()
    advertiser = bundle["advertiser"]
    manager_headers = bundle["manager_headers"]
    campaign = create_campaign(advertiser["id"], manager_headers)
    ad_group = create_ad_group(
        advertiser["id"], campaign["id"], manager_headers,
    )
    creative = reject_creative_end_to_end(
        advertiser["id"], campaign["id"], ad_group["id"], manager_headers,
    )
    return {
        "bundle": bundle,
        "advertiser": advertiser,
        "campaign": campaign,
        "ad_group": ad_group,
        "creative": creative,
        "manager_headers": manager_headers,
    }


__all__ = [
    # Clock
    "advance_clock",
    # Advertiser primitives
    "create_advertiser",
    "get_advertiser",
    "upload_qualification",
    "review_qualification",
    "create_account_user",
    "recharge_wallet",
    # Hierarchies
    "setup_active_advertiser",
    "setup_pending_advertiser_with_doc",
    # Campaign + AdGroup + Creative
    "create_campaign",
    "create_ad_group",
    "create_creative",
    "update_ad_group",
    "prescreen_creative",
    "human_review_creative",
    "approve_creative_end_to_end",
    "reject_creative_end_to_end",
    "activate_campaign",
    "activate_ad_group",
    "pause_campaign",
    "setup_active_campaign_with_approved_creative",
    "setup_two_ad_groups_for_auction",
    # Auction / billing
    "run_auction",
    "ingest_billing_event",
    "run_auction_and_ingest_click",
    "setup_finalized_billing_event",
    # Wallet
    "wallet_tx",
    # Conversion
    "create_conversion",
    "attribute_conversion",
    # Threshold targeting
    "setup_advertiser_at_low_balance_boundary",
    "setup_advertiser_at_zero_balance",
    "accumulate_impressions_for_user",
    "setup_frequency_cap_at_boundary",
    # Terminal state
    "setup_closed_advertiser",
    "setup_rejected_creative",
]
