"""Composite setup helpers used by the test suite.

Every fixture builds its preconditions from scratch using PRD-declared
endpoints only; the harness restarts the server before each test, so no state
carries over.

Identity threading (PRD §2.1): BrandRep is entity-backed — ownership-gated
calls pass make_brand_rep_headers(brand["id"]). Segregation-of-duties flows
(PRD §3.4 production decision, §3.7 verify) deliberately use two distinct
opaque operator ids.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_airing_report_payload,
    create_brand_payload,
    create_brief_payload,
    create_clearance_payload,
    create_continuity_record_payload,
    create_disclosure_payload,
    create_episode_payload,
    create_opportunity_payload,
    create_proposal_payload,
    create_series_payload,
    create_shipment_payload,
    decide_clearance_payload,
    proposal_decision_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_brand_rep_headers,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
NETWORK = TEST_USERS["network_headers"]
PROD_CREATOR = TEST_USERS["production_headers"]        # "prod-1" — creates episodes
PROD_DECIDER = TEST_USERS["production_alt_headers"]    # "prod-2" — decides proposals
CLEARANCE = TEST_USERS["clearance_headers"]            # "co-1"
FILER = TEST_USERS["verifier_headers"]                 # "ver-1" — files reports
VERIFIER = TEST_USERS["verifier_alt_headers"]          # "ver-2" — verifies reports

DEFAULT_AIR_DATE = "2026-06-01T20:00:00Z"
DEFAULT_CLOCK_AFTER_AIR = "2026-06-02T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 / 2: entity hierarchy building blocks
# ---------------------------------------------------------------------------


def create_brand(name: str = "FizzCo", category: str = "BEVERAGE", **overrides) -> dict:
    resp = api_client.create_brand(
        create_brand_payload(name=name, category=category, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_open_brief(brand_id: str, budget_cents: int = 1_000_000, **overrides) -> dict:
    """Create a brief under `brand_id` and submit it so it is OPEN."""
    rep = make_brand_rep_headers(brand_id)
    brief = get_success_data(
        api_client.create_brief(
            brand_id, create_brief_payload(budget_cents=budget_cents, **overrides), rep
        )
    )
    brief = get_success_data(api_client.submit_brief(brief["id"], rep))
    return brief


def create_series(name: str = "Night Shift", clearance_policy: Optional[str] = "STANDARD") -> dict:
    payload = create_series_payload(name=name)
    if clearance_policy is not None:
        payload["clearance_policy"] = clearance_policy
    return get_success_data(api_client.create_series(payload, ADMIN))


def create_episode(
    series_id: str,
    episode_number: int = 1,
    air_date: str = DEFAULT_AIR_DATE,
    runtime_seconds: int = 1200,
    creator_headers=None,
) -> dict:
    """Create an episode; created_by_user_id stamped from X-User-ID (PRD §3.2)."""
    headers = creator_headers or PROD_CREATOR
    return get_success_data(
        api_client.create_episode(
            series_id,
            create_episode_payload(
                episode_number=episode_number,
                runtime_seconds=runtime_seconds,
                air_date=air_date,
            ),
            headers,
        )
    )


def create_opportunity(
    episode_id: str,
    start: int = 0,
    end: int = 40,
    estimated_exposure_seconds: int = 25,
    scene_description: str = "Kitchen",
    creator_headers=None,
) -> dict:
    headers = creator_headers or PROD_CREATOR
    return get_success_data(
        api_client.create_opportunity(
            episode_id,
            create_opportunity_payload(
                scene_description=scene_description,
                start_timecode_seconds=start,
                end_timecode_seconds=end,
                estimated_exposure_seconds=estimated_exposure_seconds,
            ),
            headers,
        )
    )


def request_and_grant_clearance(episode_id: str, brand_id: str) -> dict:
    """Request a clearance (OCC on the episode's current version) and GRANT it."""
    ep = get_success_data(api_client.get_episode(episode_id, MANAGER))
    clearance = get_success_data(
        api_client.create_clearance(
            episode_id,
            create_clearance_payload(brand_id, ep["version"]),
            MANAGER,
        )
    )
    clearance = get_success_data(
        api_client.decide_clearance(
            clearance["id"], decide_clearance_payload("GRANT"), CLEARANCE
        )
    )
    return clearance


def create_proposal(
    brief_id: str,
    opportunity_id: str,
    proposed_fee_cents: int = 1_000_000,
    guaranteed_seconds: int = 30,
    guaranteed_verbal_mentions: int = 0,
    cross_promo_owed_count: int = 0,
    rate_cents_per_second: float = 2000,
) -> dict:
    return get_success_data(
        api_client.create_proposal(
            create_proposal_payload(
                brief_id,
                opportunity_id,
                proposed_fee_cents=proposed_fee_cents,
                guaranteed_seconds=guaranteed_seconds,
                guaranteed_verbal_mentions=guaranteed_verbal_mentions,
                cross_promo_owed_count=cross_promo_owed_count,
                rate_cents_per_second=rate_cents_per_second,
            ),
            MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_approved_proposal(
    budget_cents: int = 1_000_000,
    proposed_fee_cents: int = 1_000_000,
    guaranteed_seconds: int = 30,
    guaranteed_verbal_mentions: int = 0,
    cross_promo_owed_count: int = 0,
    rate_cents_per_second: float = 2000,
    estimated_exposure_seconds: int = 25,
    brand_category: str = "BEVERAGE",
    clearance_policy: str = "STANDARD",
    air_date: str = DEFAULT_AIR_DATE,
    runtime_seconds: int = 1200,
    with_clearance: bool = True,
) -> dict:
    """Brand + OPEN brief + series + episode + opportunity + proposal approved
    by both gates. Returns a dict of all built entities."""
    brand = create_brand(category=brand_category)
    brief = create_open_brief(brand["id"], budget_cents=budget_cents)
    series = create_series(clearance_policy=clearance_policy)
    episode = create_episode(series["id"], air_date=air_date, runtime_seconds=runtime_seconds)
    opportunity = create_opportunity(
        episode["id"], estimated_exposure_seconds=estimated_exposure_seconds
    )
    clearance = None
    if with_clearance:
        clearance = request_and_grant_clearance(episode["id"], brand["id"])
    proposal = create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=proposed_fee_cents,
        guaranteed_seconds=guaranteed_seconds,
        guaranteed_verbal_mentions=guaranteed_verbal_mentions,
        cross_promo_owed_count=cross_promo_owed_count,
        rate_cents_per_second=rate_cents_per_second,
    )
    proposal = get_success_data(api_client.submit_proposal(proposal["id"], MANAGER))
    proposal = get_success_data(
        api_client.production_decision(
            proposal["id"], proposal_decision_payload("APPROVE"), PROD_DECIDER
        )
    )
    proposal = get_success_data(
        api_client.network_decision(
            proposal["id"], proposal_decision_payload("APPROVE"), NETWORK
        )
    )
    return {
        "brand": brand,
        "brief": brief,
        "series": series,
        "episode": episode,
        "opportunity": opportunity,
        "clearance": clearance,
        "proposal": proposal,
    }


def setup_pending_contract(**overrides) -> dict:
    """Approved proposal converted to a PENDING_SIGNATURE contract.
    The episode is LOCKED unless lock_episode=False is passed."""
    lock_episode = overrides.pop("lock_episode", True)
    ctx = setup_approved_proposal(**overrides)
    if lock_episode:
        ctx["episode"] = get_success_data(
            api_client.lock_episode(ctx["episode"]["id"], PROD_CREATOR)
        )
    ctx["contract"] = get_success_data(
        api_client.create_contract_from_proposal(ctx["proposal"]["id"], MANAGER)
    )
    return ctx


def setup_active_contract(**overrides) -> dict:
    """PENDING_SIGNATURE contract activated (requires LOCKED episode and a
    GRANTED clearance)."""
    ctx = setup_pending_contract(**overrides)
    ctx["contract"] = get_success_data(
        api_client.activate_contract(ctx["contract"]["id"], MANAGER)
    )
    return ctx


def setup_aired_contract(
    clock_after_air: str = DEFAULT_CLOCK_AFTER_AIR,
    disclosure_text: str = "Paid placement by FizzCo",
    acknowledge_disclosure: bool = True,
    **overrides,
) -> dict:
    """ACTIVE contract + disclosure filed pre-air + clock advanced past air
    date + episode marked AIRED. When acknowledge_disclosure is True the
    filing is also ACKNOWLEDGED (the verification gate of PRD §3.7)."""
    ctx = setup_active_contract(**overrides)
    disclosure = get_success_data(
        api_client.create_disclosure(
            ctx["contract"]["id"],
            create_disclosure_payload(disclosure_text=disclosure_text),
            MANAGER,
        )
    )
    get_success_data(api_client.file_disclosure(disclosure["id"], MANAGER))
    get_success_data(api_client.set_clock(set_clock_payload(clock_after_air), ADMIN))
    ctx["episode"] = get_success_data(
        api_client.mark_episode_aired(ctx["episode"]["id"], PROD_CREATOR)
    )
    if acknowledge_disclosure:
        disclosure = get_success_data(
            api_client.acknowledge_disclosure(disclosure["id"], NETWORK)
        )
    ctx["disclosure"] = disclosure
    return ctx


def setup_filed_report(
    measured_segments_seconds=None,
    measured_verbal_mentions: int = 2,
    **overrides,
) -> dict:
    """Aired contract + a FILED airing report (filed by ver-1)."""
    ctx = setup_aired_contract(**overrides)
    report = get_success_data(
        api_client.create_airing_report(
            ctx["episode"]["id"],
            create_airing_report_payload(
                ctx["contract"]["id"],
                measured_segments_seconds=measured_segments_seconds or [30],
                measured_verbal_mentions=measured_verbal_mentions,
            ),
            FILER,
        )
    )
    ctx["report"] = report
    return ctx


def setup_verified_report(**overrides) -> dict:
    """Filed report verified by a different analyst (ver-2)."""
    ctx = setup_filed_report(**overrides)
    ctx["report"] = get_success_data(
        api_client.verify_airing_report(ctx["report"]["id"], VERIFIER)
    )
    ctx["contract"] = get_success_data(
        api_client.get_contract(ctx["contract"]["id"], MANAGER)
    )
    return ctx


def setup_makegood_required(**overrides) -> dict:
    """Verified report that produced a PENDING MakeGoodCredit (contract in
    MAKEGOOD_REQUIRED). Defaults force a shortfall: measured 20s + 1 mention
    against guaranteed 30s + 2 mentions."""
    overrides.setdefault("guaranteed_verbal_mentions", 2)
    overrides.setdefault("measured_segments_seconds", [20])
    overrides.setdefault("measured_verbal_mentions", 1)
    ctx = setup_verified_report(**overrides)
    credits = get_success_data(
        api_client.list_contract_makegood_credits(ctx["contract"]["id"], MANAGER)
    )
    ctx["makegood_credit"] = credits[0]
    return ctx


def setup_settled_contract(**overrides) -> dict:
    """Contract SETTLED. With the defaults (no shortfall) verification settles
    directly; otherwise any PENDING make-good credits are waived."""
    ctx = setup_verified_report(**overrides)
    if ctx["contract"]["status"] == "MAKEGOOD_REQUIRED":
        credits = get_success_data(
            api_client.list_contract_makegood_credits(ctx["contract"]["id"], MANAGER)
        )
        for credit in credits:
            if credit["status"] == "PENDING":
                get_success_data(api_client.waive_makegood_credit(credit["id"], MANAGER))
        ctx["contract"] = get_success_data(
            api_client.get_contract(ctx["contract"]["id"], MANAGER)
        )
    return ctx


# ---------------------------------------------------------------------------
# Shipment helpers
# ---------------------------------------------------------------------------


def create_shipment(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_shipment(
            contract_id, create_shipment_payload(**overrides), MANAGER
        )
    )


def advance_shipment(shipment_id: str, to: str) -> dict:
    from .factories import advance_shipment_payload

    return get_success_data(
        api_client.advance_shipment(shipment_id, advance_shipment_payload(to), MANAGER)
    )


def create_continuity_record(contract_id: str, shipment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_continuity_record(
            contract_id,
            create_continuity_record_payload(shipment_id, **overrides),
            PROD_CREATOR,
        )
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_brief(brief_id: str) -> dict:
    return get_success_data(api_client.get_brief(brief_id, MANAGER))


def get_episode(episode_id: str) -> dict:
    return get_success_data(api_client.get_episode(episode_id, MANAGER))


def get_opportunity(opportunity_id: str) -> dict:
    return get_success_data(api_client.get_opportunity(opportunity_id, MANAGER))


def get_proposal(proposal_id: str) -> dict:
    return get_success_data(api_client.get_proposal(proposal_id, MANAGER))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, MANAGER))


def get_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, MANAGER))


def get_clearance(clearance_id: str) -> dict:
    """Clearances are listed per episode (no bare GET /clearances/{id} in PRD §4)."""
    raise NotImplementedError(
        "No GET /clearances/{id} endpoint; use list_episode_clearances instead"
    )


def list_episode_clearances(episode_id: str) -> list:
    return get_success_data(api_client.list_episode_clearances(episode_id, MANAGER))


def find_clearance(episode_id: str, clearance_id: str) -> dict:
    for row in list_episode_clearances(episode_id):
        if row["id"] == clearance_id:
            return row
    raise AssertionError(f"clearance {clearance_id} not found on episode {episode_id}")


def list_makegood_credits(contract_id: str) -> list:
    return get_success_data(
        api_client.list_contract_makegood_credits(contract_id, MANAGER)
    )


def list_cross_promos(contract_id: str) -> list:
    return get_success_data(api_client.list_contract_cross_promos(contract_id, MANAGER))


def list_continuity_records(contract_id: str) -> list:
    return get_success_data(
        api_client.list_contract_continuity_records(contract_id, MANAGER)
    )


def list_episode_opportunities(episode_id: str) -> list:
    return get_success_data(api_client.list_episode_opportunities(episode_id, MANAGER))
