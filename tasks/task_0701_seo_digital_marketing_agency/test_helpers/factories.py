"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD endpoint definitions (§4) and §3 narratives:
- Reseller: brand_name, markup_pct required; ppc_management_pct optional (default 0.15)
- Client: company_name, primary_domain required; reseller_id optional
- SiteAudit: technical_score, content_score, backlink_score required
- KeywordTarget: client_id, phrase, search_volume, difficulty required
- RankSnapshot: position, organic_traffic required; observed_at optional (default clock now)
- Retainer: client_id, tier, monthly_credits, wholesale_price_cents required; rollover_cap_pct optional (default 0.25)
- Contract: client_id, retainer_id, term_cycles required; auto_renew optional (default true)
- Sprint: client_id, retainer_id, name, starts_at, ends_at, capacity_credits required
- Deliverable: client_id, retainer_id, sprint_id, kind required; complexity optional (default STANDARD)
- AdCampaign: client_id, retainer_id, channel, budget_cents required
- AdSpendDispute: ad_campaign_id, client_id, disputed_cents required
- GbpListing: client_id, location_name, service_area required
"""


def create_reseller_payload(**overrides) -> dict:
    payload = {"brand_name": "WhiteLabel Co", "markup_pct": 0.30}
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {"company_name": "Test Client Co", "primary_domain": "test.example"}
    payload.update(overrides)
    return payload


def create_audit_payload(**overrides) -> dict:
    payload = {"technical_score": 70, "content_score": 70, "backlink_score": 70}
    payload.update(overrides)
    return payload


def create_keyword_target_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "phrase": "seo services",
        "search_volume": 1000,
        "difficulty": 40,
    }
    payload.update(overrides)
    return payload


def create_snapshot_payload(**overrides) -> dict:
    payload = {"position": 10, "organic_traffic": 100}
    payload.update(overrides)
    return payload


def create_retainer_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "tier": "GROWTH",
        "monthly_credits": 20,
        "wholesale_price_cents": 200000,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(**overrides) -> dict:
    payload = {"client_id": None, "retainer_id": None, "term_cycles": 6}
    payload.update(overrides)
    return payload


def create_sprint_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "retainer_id": None,
        "name": "Test Sprint",
        "starts_at": "2026-04-01T00:00:00Z",
        "ends_at": "2026-05-01T00:00:00Z",
        "capacity_credits": 20,
    }
    payload.update(overrides)
    return payload


def create_deliverable_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "retainer_id": None,
        "sprint_id": None,
        "kind": "CONTENT",
        "complexity": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_ad_campaign_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "retainer_id": None,
        "channel": "GOOGLE_ADS",
        "budget_cents": 1000000,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(**overrides) -> dict:
    payload = {"ad_campaign_id": None, "client_id": None, "disputed_cents": 100000}
    payload.update(overrides)
    return payload


def create_gbp_listing_payload(**overrides) -> dict:
    payload = {
        "client_id": None,
        "location_name": "Main St",
        "service_area": "Downtown",
    }
    payload.update(overrides)
    return payload


def create_report_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-04-01T00:00:00Z",
        "period_end": "2026-05-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
