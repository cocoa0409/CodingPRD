"""Composite setup helpers that build API state from scratch through public endpoints.

The server is relaunched with an empty store before every test, so nothing here may
assume pre-existing data: each helper walks the real workflow — register the asset graph,
price the stream, approve the price, open the deal, negotiate, clear diligence, fund
escrow, close — using only endpoints the PRD declares.

Layering, from the bottom up:

* **Tier 1 — atomic steps.** One call each, returning the created resource.
* **Tier 2 — entity hierarchy.** The asset graph and a priced stream.
* **Tier 3 — lifecycle shortcuts.** ``build_chain`` walks the deal pipeline to a named
  milestone and returns every resource it created along the way.
* **Tier 4 — accumulation and threshold targeting.** Financing facilities with pledges,
  parallel closed deals, and a portfolio driven to a chosen posture.
* **Tier 5 — finalization and terminal state.** Disputes, cures and amendment events on
  an already-acquired stream.

Every helper accepts ``**overrides``-style keyword payload dictionaries so a test can
vary one input without restating the chain.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .test_users import (
    PM_APPROVER_USER_ID,
    PM_CLOSER_USER_ID,
    make_acquisition_analyst_headers,
    make_landowner_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    make_title_officer_headers,
    make_tower_company_agent_headers,
    make_treasury_officer_headers,
)
from .types import (
    AmendmentEventType,
    DisputeType,
    ValuationMethod,
)


class Scenario(dict):
    """A dictionary of created resources that also supports attribute access."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error path
            raise AttributeError(item) from exc

    # Convenience id accessors for the resources most often threaded into requests.
    @property
    def portfolio_id(self) -> str:
        return self["portfolio"]["id"]

    @property
    def tower_company_id(self) -> str:
        return self["tower_company"]["id"]

    @property
    def tower_site_id(self) -> str:
        return self["tower_site"]["id"]

    @property
    def landowner_id(self) -> str:
        return self["landowner"]["id"]

    @property
    def lease_stream_id(self) -> str:
        return self["lease_stream"]["id"]

    @property
    def valuation_id(self) -> str:
        return self["valuation"]["id"]

    @property
    def deal_id(self) -> str:
        return self["deal"]["id"]

    @property
    def offer_id(self) -> str:
        return self["offer"]["id"]

    @property
    def title_report_id(self) -> str:
        return self["title_report"]["id"]

    @property
    def facility_id(self) -> str:
        return self["facility"]["id"]

    @property
    def landowner_headers(self) -> Dict[str, str]:
        return make_landowner_headers(self.landowner_id)

    @property
    def tower_agent_headers(self) -> Dict[str, str]:
        return make_tower_company_agent_headers(self.tower_company_id)


# ===========================================================================
# Tier 1 — atomic steps
# ===========================================================================


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Reposition the logical clock as the PlatformAdmin (PRD section 2.6)."""
    return get_success_data(api.set_current_utc(current_utc, headers=make_platform_admin_headers()))


def create_portfolio(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.portfolio_payload(**overrides)
    return get_success_data(api.create_portfolio(payload, headers=make_platform_admin_headers()))


def adjust_capital(api: ApiClient, portfolio_id: str, delta_cents: int, memo: str = "Investor capital call") -> Dict[str, Any]:
    payload = factories.capital_adjustment_payload(delta_cents, memo)
    return get_success_data(api.adjust_portfolio_capital(portfolio_id, payload, headers=make_platform_admin_headers()))


def create_tower_company(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.tower_company_payload(**overrides)
    return get_success_data(api.create_tower_company(payload, headers=make_platform_admin_headers()))


def create_tower_site(api: ApiClient, tower_company_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.tower_site_payload(tower_company_id, **overrides)
    return get_success_data(api.create_tower_site(payload, headers=make_acquisition_analyst_headers()))


def create_landowner(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.landowner_payload(**overrides)
    return get_success_data(api.create_landowner(payload, headers=make_acquisition_analyst_headers()))


def create_lease_stream(api: ApiClient, tower_site_id: str, landowner_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.lease_stream_payload(tower_site_id, landowner_id, **overrides)
    return get_success_data(api.create_lease_stream(payload, headers=make_acquisition_analyst_headers()))


def add_tenancy(
    api: ApiClient, lease_stream_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.tenancy_payload(**overrides)
    return get_success_data(
        api.create_tenancy(lease_stream_id, payload, headers=headers or make_acquisition_analyst_headers())
    )


def set_tenancy_status(api: ApiClient, tenancy_id: str, status: str) -> Dict[str, Any]:
    """Only a ServicingAgent may reclassify a tenancy (PRD section 3.3)."""
    return get_success_data(
        api.set_tenancy_status(tenancy_id, {"status": status}, headers=make_servicing_agent_headers())
    )


def read_lease_stream(api: ApiClient, lease_stream_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lease_stream(lease_stream_id, headers=make_acquisition_analyst_headers()))


def create_valuation(api: ApiClient, lease_stream_id: str, **overrides: Any) -> Dict[str, Any]:
    """Read the stream's current version and pin it, as PRD section 2.7 requires."""
    version = read_lease_stream(api, lease_stream_id)["version"]
    payload = factories.valuation_payload(version, **overrides)
    return get_success_data(api.create_valuation(lease_stream_id, payload, headers=make_acquisition_analyst_headers()))


def approve_valuation(api: ApiClient, valuation_id: str, user_id: str = PM_APPROVER_USER_ID) -> Dict[str, Any]:
    return get_success_data(api.approve_valuation(valuation_id, headers=make_portfolio_manager_headers(user_id)))


def create_facility(api: ApiClient, portfolio_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.financing_facility_payload(portfolio_id, **overrides)
    return get_success_data(api.create_financing_facility(payload, headers=make_treasury_officer_headers()))


def read_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_financing_facility(facility_id, headers=make_treasury_officer_headers()))


def create_pledge(api: ApiClient, facility_id: str, lease_stream_id: str, **overrides: Any) -> Dict[str, Any]:
    """Read the facility's current version and pin it, as PRD section 2.7 requires."""
    version = read_facility(api, facility_id)["version"]
    payload = factories.pledge_payload(lease_stream_id, version, **overrides)
    return get_success_data(api.create_pledge(facility_id, payload, headers=make_treasury_officer_headers()))


def draw_advance(api: ApiClient, facility_id: str, amount_cents: int) -> Dict[str, Any]:
    payload = factories.advance_payload(amount_cents)
    return get_success_data(api.create_advance(facility_id, payload, headers=make_treasury_officer_headers()))


# ===========================================================================
# Tier 2 — entity hierarchy
# ===========================================================================

DEFAULT_TENANCIES: Sequence[Dict[str, Any]] = ({},)  # one canonical investment-grade anchor


def build_asset_graph(
    api: ApiClient,
    *,
    tower_company: Optional[Dict[str, Any]] = None,
    tower_site: Optional[Dict[str, Any]] = None,
    landowner: Optional[Dict[str, Any]] = None,
    lease_stream: Optional[Dict[str, Any]] = None,
    tenancies: Optional[Sequence[Dict[str, Any]]] = DEFAULT_TENANCIES,
) -> Scenario:
    """Tower company, site, landowner, stream and its opening tenancy roster."""
    company = create_tower_company(api, **(tower_company or {}))
    site = create_tower_site(api, company["id"], **(tower_site or {}))
    owner = create_landowner(api, **(landowner or {}))
    stream = create_lease_stream(api, site["id"], owner["id"], **(lease_stream or {}))
    rows: List[Dict[str, Any]] = []
    for tenancy_overrides in tenancies or ():
        overrides = dict(tenancy_overrides)
        headers = overrides.pop("headers", None)
        rows.append(add_tenancy(api, stream["id"], headers=headers, **overrides))
    return Scenario(
        tower_company=company,
        tower_site=site,
        landowner=owner,
        lease_stream=read_lease_stream(api, stream["id"]),
        tenancies=rows,
    )


def build_priced_stream(
    api: ApiClient,
    *,
    approved: bool = True,
    valuation: Optional[Dict[str, Any]] = None,
    approver_user_id: str = PM_APPROVER_USER_ID,
    **asset_kwargs: Any,
) -> Scenario:
    """An asset graph plus one valuation, optionally already approved."""
    scenario = build_asset_graph(api, **asset_kwargs)
    priced = create_valuation(api, scenario.lease_stream_id, **(valuation or {}))
    if approved:
        priced = approve_valuation(api, priced["id"], user_id=approver_user_id)
    scenario["valuation"] = priced
    return scenario


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================

MILESTONES = (
    "asset",
    "valuation_draft",
    "valuation_approved",
    "deal",
    "outreach",
    "offer_draft",
    "offer_sent",
    "offer_countered",
    "offer_accepted",
    "title_ordered",
    "title_cleared",
    "escrowed",
    "closed",
)


def build_chain(
    api: ApiClient,
    milestone: str = "closed",
    *,
    portfolio: Optional[Dict[str, Any]] = None,
    tower_company: Optional[Dict[str, Any]] = None,
    tower_site: Optional[Dict[str, Any]] = None,
    landowner: Optional[Dict[str, Any]] = None,
    lease_stream: Optional[Dict[str, Any]] = None,
    tenancies: Optional[Sequence[Dict[str, Any]]] = DEFAULT_TENANCIES,
    valuation: Optional[Dict[str, Any]] = None,
    approver_user_id: str = PM_APPROVER_USER_ID,
    deal: Optional[Dict[str, Any]] = None,
    offer: Optional[Dict[str, Any]] = None,
    counter_amount_cents: int = 34_000_000,
    title_report: Optional[Dict[str, Any]] = None,
    findings: Optional[Dict[str, Any]] = None,
    serve_rofr: bool = False,
    recording_ref: Optional[str] = None,
    closer_user_id: str = PM_CLOSER_USER_ID,
    existing: Optional[Scenario] = None,
) -> Scenario:
    """Walk the deal pipeline as far as ``milestone`` and return everything created.

    ``existing`` lets a caller extend a scenario that already holds an asset graph or a
    portfolio, so parallel deals can share one capital pool.
    """
    assert milestone in MILESTONES, f"unknown milestone {milestone!r}; expected one of {MILESTONES}"
    stop_at = MILESTONES.index(milestone)

    scenario = Scenario(existing or {})

    # --- asset graph -----------------------------------------------------
    if "lease_stream" not in scenario:
        scenario.update(
            build_asset_graph(
                api,
                tower_company=tower_company,
                tower_site=tower_site,
                landowner=landowner,
                lease_stream=lease_stream,
                tenancies=tenancies,
            )
        )
    if stop_at == MILESTONES.index("asset"):
        return scenario

    # --- valuation -------------------------------------------------------
    if "valuation" not in scenario:
        scenario["valuation"] = create_valuation(api, scenario.lease_stream_id, **(valuation or {}))
    if stop_at == MILESTONES.index("valuation_draft"):
        return scenario

    if scenario["valuation"]["status"] == "DRAFT":
        scenario["valuation"] = approve_valuation(api, scenario.valuation_id, user_id=approver_user_id)
    scenario["approver_user_id"] = approver_user_id
    if stop_at == MILESTONES.index("valuation_approved"):
        return scenario

    # --- deal ------------------------------------------------------------
    if "portfolio" not in scenario:
        scenario["portfolio"] = create_portfolio(api, **(portfolio or {}))
    deal_payload = factories.deal_payload(
        scenario.portfolio_id, scenario.lease_stream_id, scenario.valuation_id, **(deal or {})
    )
    scenario["deal"] = get_success_data(api.create_deal(deal_payload, headers=make_acquisition_analyst_headers()))
    if stop_at == MILESTONES.index("deal"):
        return scenario

    # --- outreach --------------------------------------------------------
    scenario["deal"] = get_success_data(
        api.start_outreach(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    if stop_at == MILESTONES.index("outreach"):
        return scenario

    # --- offer -----------------------------------------------------------
    offer_body = factories.offer_payload(**(offer or {}))
    scenario["offer"] = get_success_data(
        api.create_offer(scenario.deal_id, offer_body, headers=make_acquisition_analyst_headers())
    )
    if stop_at == MILESTONES.index("offer_draft"):
        return scenario

    scenario["offer"] = get_success_data(
        api.transition_offer(scenario.offer_id, {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    if stop_at == MILESTONES.index("offer_sent"):
        return scenario

    if stop_at == MILESTONES.index("offer_countered"):
        scenario["offer"] = get_success_data(
            api.transition_offer(
                scenario.offer_id,
                {"action": "COUNTER", "counter_amount_cents": counter_amount_cents},
                headers=scenario.landowner_headers,
            )
        )
        return scenario

    scenario["offer"] = get_success_data(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )
    if stop_at == MILESTONES.index("offer_accepted"):
        return scenario

    # --- diligence: title track and, when required, the refusal track ----
    scenario["title_report"] = get_success_data(
        api.create_title_report(
            scenario.deal_id, factories.title_report_payload(**(title_report or {})), headers=make_acquisition_analyst_headers()
        )
    )
    if serve_rofr:
        scenario["rofr_notice"] = get_success_data(
            api.serve_rofr_notice(scenario.deal_id, {}, headers=make_acquisition_analyst_headers())
        )
    if stop_at == MILESTONES.index("title_ordered"):
        return scenario

    scenario["title_report"] = get_success_data(
        api.transition_title_report(
            scenario.title_report_id, factories.record_findings_payload(**(findings or {})), headers=make_title_officer_headers()
        )
    )
    if stop_at == MILESTONES.index("title_cleared"):
        return scenario

    # --- escrow ----------------------------------------------------------
    if serve_rofr and "rofr_notice" in scenario:
        scenario["rofr_notice"] = get_success_data(
            api.respond_to_rofr_notice(
                scenario["rofr_notice"]["id"], {"decision": "WAIVE"}, headers=scenario.tower_agent_headers
            )
        )
    scenario["deal"] = get_success_data(api.fund_escrow(scenario.deal_id, headers=make_treasury_officer_headers()))
    if stop_at == MILESTONES.index("escrowed"):
        return scenario

    # --- close -----------------------------------------------------------
    scenario["close_response"] = get_success_data(
        api.close_deal(
            scenario.deal_id,
            factories.close_payload(recording_ref),
            headers=make_portfolio_manager_headers(closer_user_id),
        )
    )
    scenario["deal"] = scenario["close_response"]
    scenario["closer_user_id"] = closer_user_id
    return scenario


# Readable aliases for the milestones tests reach for most often.


def asset_graph(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "asset", **kwargs)


def stream_with_draft_valuation(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "valuation_draft", **kwargs)


def stream_with_approved_valuation(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "valuation_approved", **kwargs)


def deal_in_origination(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "deal", **kwargs)


def deal_in_outreach(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "outreach", **kwargs)


def deal_with_draft_offer(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "offer_draft", **kwargs)


def deal_in_negotiation(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "offer_sent", **kwargs)


def deal_with_countered_offer(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "offer_countered", **kwargs)


def deal_in_diligence(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "offer_accepted", **kwargs)


def deal_with_ordered_title(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "title_ordered", **kwargs)


def deal_cleared_to_close(api: ApiClient, **kwargs: Any) -> Scenario:
    """Title findings of zero exceptions on an unmortgaged property clear the join."""
    return build_chain(api, "title_cleared", **kwargs)


def deal_escrowed(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "escrowed", **kwargs)


def closed_deal(api: ApiClient, **kwargs: Any) -> Scenario:
    return build_chain(api, "closed", **kwargs)


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def build_mortgaged_deal_awaiting_consent(
    api: ApiClient, *, lender_name: str = "Hudson Valley Savings", **kwargs: Any
) -> Scenario:
    """A cleared report on a mortgaged property with consent already REQUESTED."""
    scenario = build_chain(
        api,
        "title_cleared",
        findings={"exception_count": 0, "mortgage_present": True, "lender_name": lender_name},
        **kwargs,
    )
    scenario["title_report"] = get_success_data(
        api.transition_title_report(
            scenario.title_report_id, {"action": "REQUEST_CONSENT"}, headers=make_title_officer_headers()
        )
    )
    return scenario


def grant_consent(api: ApiClient, title_report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_consent(title_report_id, {"decision": "GRANT"}, headers=make_lender_headers())
    )


def build_facility_with_pledge(
    api: ApiClient,
    *,
    facility: Optional[Dict[str, Any]] = None,
    pledge: Optional[Dict[str, Any]] = None,
    **chain_kwargs: Any,
) -> Scenario:
    """A closed deal whose acquired stream is pledged into a warehouse facility."""
    scenario = closed_deal(api, **chain_kwargs)
    scenario["facility"] = create_facility(api, scenario.portfolio_id, **(facility or {}))
    scenario["pledge"] = create_pledge(api, scenario.facility_id, scenario.lease_stream_id, **(pledge or {}))
    scenario["facility"] = read_facility(api, scenario.facility_id)
    return scenario


def build_two_closed_deals(
    api: ApiClient,
    *,
    total_capital_cents: int = 100_000_000,
    site_codes: Sequence[str] = ("NE-6201", "NE-6202"),
    landowner_names: Sequence[str] = ("Owner_a LLC", "Owner_b LLC"),
    landowner_emails: Sequence[str] = ("owner_a@x.example", "owner_b@x.example"),
    recording_refs: Sequence[str] = ("BK1420-PG201", "BK1420-PG202"),
    tower_company: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """One capital pool, one tower company, two independently closed deals."""
    portfolio = create_portfolio(api, total_capital_cents=total_capital_cents)
    company = create_tower_company(api, **(tower_company or {}))
    legs: List[Scenario] = []
    for index in range(2):
        leg = build_chain(
            api,
            "closed",
            existing=Scenario(portfolio=portfolio, tower_company=company),
            tower_site={"site_code": site_codes[index]},
            landowner={"legal_name": landowner_names[index], "contact_email": landowner_emails[index]},
            recording_ref=recording_refs[index],
        )
        legs.append(leg)
    return Scenario(portfolio=portfolio, tower_company=company, legs=legs, deal_a=legs[0], deal_b=legs[1])


def build_two_deals_on_one_portfolio(
    api: ApiClient,
    *,
    milestone: str = "offer_sent",
    total_capital_cents: int = 50_000_000,
    site_codes: Sequence[str] = ("NE-6301", "NE-6302"),
    landowner_names: Sequence[str] = ("Owner_a LLC", "Owner_b LLC"),
    landowner_emails: Sequence[str] = ("owner_a@x.example", "owner_b@x.example"),
    offers: Optional[Sequence[Dict[str, Any]]] = None,
    milestones: Optional[Sequence[str]] = None,
) -> Scenario:
    """Two sibling deals funded from one pool, each stopped at its own milestone."""
    portfolio = create_portfolio(api, total_capital_cents=total_capital_cents)
    company = create_tower_company(api)
    legs: List[Scenario] = []
    for index in range(2):
        legs.append(
            build_chain(
                api,
                (milestones[index] if milestones else milestone),
                existing=Scenario(portfolio=portfolio, tower_company=company),
                tower_site={"site_code": site_codes[index]},
                landowner={"legal_name": landowner_names[index], "contact_email": landowner_emails[index]},
                offer=(offers[index] if offers else None),
            )
        )
    return Scenario(portfolio=portfolio, tower_company=company, legs=legs, deal_a=legs[0], deal_b=legs[1])


# ===========================================================================
# Tier 5 — finalization and terminal state
# ===========================================================================


def open_dispute(
    api: ApiClient,
    lease_stream_id: str,
    *,
    landowner_id: Optional[str] = None,
    dispute_type: str = DisputeType.ACCESS.value,
    description: str = "Access road gated without notice",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a dispute; by default the stream's own landowner raises it."""
    caller = headers or (make_landowner_headers(landowner_id) if landowner_id else make_servicing_agent_headers())
    payload = factories.dispute_payload(dispute_type, description)
    return get_success_data(api.open_dispute(lease_stream_id, payload, headers=caller))


def transition_dispute(api: ApiClient, dispute_id: str, action: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.transition_dispute(dispute_id, {"action": action}, headers=headers))


def build_dispute_on_closed_stream(
    api: ApiClient,
    *,
    dispute_type: str = DisputeType.ACCESS.value,
    description: str = "Access road gated without notice",
    start_cure: bool = False,
    **chain_kwargs: Any,
) -> Scenario:
    """A closed deal plus one dispute on its acquired stream, optionally already in cure."""
    scenario = closed_deal(api, **chain_kwargs)
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=dispute_type,
        description=description,
    )
    if start_cure:
        scenario["dispute"] = transition_dispute(
            api, scenario["dispute"]["id"], "START_CURE", make_servicing_agent_headers()
        )
    return scenario


def record_amendment_event(
    api: ApiClient,
    lease_stream_id: str,
    gross_amount_cents: int,
    *,
    event_type: str = AmendmentEventType.COLOCATION_ADDED.value,
    effective_date: str = "2026-09-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.amendment_event_payload(
        gross_amount_cents, event_type=event_type, effective_date=effective_date, **overrides
    )
    return get_success_data(api.create_amendment_event(lease_stream_id, payload, headers=make_servicing_agent_headers()))


def reverse_amendment_event(api: ApiClient, amendment_event_id: str, reversal_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_amendment_event(
            amendment_event_id, {"reversal_reason": reversal_reason}, headers=make_servicing_agent_headers()
        )
    )


def build_amendment_on_closed_stream(
    api: ApiClient,
    *,
    gross_amount_cents: int = 1_000_002,
    event_type: str = AmendmentEventType.COLOCATION_ADDED.value,
    effective_date: str = "2026-09-01",
    amendment_overrides: Optional[Dict[str, Any]] = None,
    **chain_kwargs: Any,
) -> Scenario:
    """A closed deal plus one recorded amendment event on its acquired stream."""
    scenario = closed_deal(api, **chain_kwargs)
    scenario["amendment_event"] = record_amendment_event(
        api,
        scenario.lease_stream_id,
        gross_amount_cents,
        event_type=event_type,
        effective_date=effective_date,
        **(amendment_overrides or {}),
    )
    return scenario


# ===========================================================================
# Shared literals a few scenarios need to agree on
# ===========================================================================

PREPAID_VALUATION = {"method": ValuationMethod.PREPAID_RENT_TERM.value}
ROFR_REQUIRED_COMPANY = {"rofr_required": True, "rofr_window_days": TEST_DEFAULTS["ROFR_WINDOW_DAYS"]}


__all__ = [
    "Scenario",
    "set_clock",
    "create_portfolio",
    "adjust_capital",
    "create_tower_company",
    "create_tower_site",
    "create_landowner",
    "create_lease_stream",
    "add_tenancy",
    "set_tenancy_status",
    "read_lease_stream",
    "create_valuation",
    "approve_valuation",
    "create_facility",
    "read_facility",
    "create_pledge",
    "draw_advance",
    "build_asset_graph",
    "build_priced_stream",
    "MILESTONES",
    "build_chain",
    "asset_graph",
    "stream_with_draft_valuation",
    "stream_with_approved_valuation",
    "deal_in_origination",
    "deal_in_outreach",
    "deal_with_draft_offer",
    "deal_in_negotiation",
    "deal_with_countered_offer",
    "deal_in_diligence",
    "deal_with_ordered_title",
    "deal_cleared_to_close",
    "deal_escrowed",
    "closed_deal",
    "build_mortgaged_deal_awaiting_consent",
    "grant_consent",
    "build_facility_with_pledge",
    "build_two_closed_deals",
    "build_two_deals_on_one_portfolio",
    "open_dispute",
    "transition_dispute",
    "build_dispute_on_closed_stream",
    "record_amendment_event",
    "reverse_amendment_event",
    "build_amendment_on_closed_stream",
    "PREPAID_VALUATION",
    "ROFR_REQUIRED_COMPANY",
]
