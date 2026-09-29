"""Composite setup helpers.

Every helper here builds its preconditions from scratch through PRD-declared
routes, because each test starts against an empty database. Setup calls use the
lenient validator so a broken precondition reports as a setup failure rather
than as a confusing assertion failure.

Identity threading: a caller acting as `Agent` presents the producer agency
record's own `id` as `X-User-ID`, and a `LossControlSpecialist` presents the
inspector record's `id`. Every ownership-gated call below therefore uses
`make_agent_headers(agent["id"])` / `make_loss_control_headers(inspector["id"])`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agent_payload,
    create_cat_capacity_pool_payload,
    create_farm_account_payload,
    create_farm_policy_payload,
    create_inspection_payload,
    create_inspector_payload,
    create_labor_profile_payload,
    create_liability_exposure_payload,
    create_livestock_group_payload,
    create_scheduled_item_payload,
    create_seasonal_item_payload,
)
from .test_users import TEST_USERS, make_agent_headers, make_loss_control_headers

DEFAULT_TEST_CLOCK = "2026-08-15T00:00:00Z"

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
UW_ALT = TEST_USERS["underwriter_headers_alt"]
SENIOR = TEST_USERS["senior_underwriter_headers"]
SENIOR_ALT = TEST_USERS["senior_underwriter_headers_alt"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Context object
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Everything a test needs to keep talking to the rows a fixture built."""

    agent: Dict[str, Any]
    agent_headers: Dict[str, str]
    pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    account: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    livestock: List[Dict[str, Any]] = field(default_factory=list)
    liabilities: List[Dict[str, Any]] = field(default_factory=list)
    labor_profile: Optional[Dict[str, Any]] = None
    inspector: Optional[Dict[str, Any]] = None
    inspections: List[Dict[str, Any]] = field(default_factory=list)
    endorsements: List[Dict[str, Any]] = field(default_factory=list)
    zone_code: str = "ZN-1"

    # -- convenience accessors -------------------------------------------
    @property
    def agent_id(self) -> str:
        return self.agent["id"]

    @property
    def account_id(self) -> str:
        return self.account["id"]

    @property
    def policy_id(self) -> str:
        return self.policy["id"]

    @property
    def inspector_id(self) -> str:
        return self.inspector["id"]

    @property
    def inspector_headers(self) -> Dict[str, str]:
        return make_loss_control_headers(self.inspector["id"])

    @property
    def hail_pool(self) -> Dict[str, Any]:
        return self.pools["HAIL"]

    @property
    def wind_pool(self) -> Dict[str, Any]:
        return self.pools["WIND"]

    @property
    def wildfire_pool(self) -> Dict[str, Any]:
        return self.pools["WILDFIRE"]

    @property
    def item(self) -> Dict[str, Any]:
        return self.items[0]

    @property
    def inspection(self) -> Dict[str, Any]:
        return self.inspections[0]

    @property
    def endorsement(self) -> Dict[str, Any]:
        return self.endorsements[0]


# ---------------------------------------------------------------------------
# Tier 1 primitives
# ---------------------------------------------------------------------------


def set_clock(current_utc: str = DEFAULT_TEST_CLOCK) -> dict:
    """Park the logical clock. Changes no business row whatsoever."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, ADMIN))


def register_agent(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_agent(create_agent_payload(**overrides), ADMIN))


def register_inspector(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_inspector(create_inspector_payload(**overrides), ADMIN)
    )


def open_pool(zone_code: str, peril: str, **overrides) -> Dict[str, Any]:
    payload = create_cat_capacity_pool_payload(peril=peril, zone_code=zone_code, **overrides)
    return get_success_data(api_client.create_cat_capacity_pool(payload, ADMIN))


def open_zone_pools(
    zone_code: str = "ZN-1",
    hail_capacity_cents: int = 200_000_000,
    wind_capacity_cents: int = 200_000_000,
    wildfire_capacity_cents: int = 200_000_000,
    perils=("HAIL", "WIND", "WILDFIRE"),
) -> Dict[str, Dict[str, Any]]:
    """Open the three per-peril pools a zone needs before any policy in it can
    be rated. Participation is 0.50 / 0.30 / 0.20."""
    capacity = {
        "HAIL": hail_capacity_cents,
        "WIND": wind_capacity_cents,
        "WILDFIRE": wildfire_capacity_cents,
    }
    return {
        peril: open_pool(zone_code, peril, total_capacity_cents=capacity[peril])
        for peril in perils
    }


def open_account(agent_headers: Dict[str, str], **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_farm_account(create_farm_account_payload(**overrides), agent_headers)
    )


def open_policy(agent_headers: Dict[str, str], account_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_farm_policy(
            create_farm_policy_payload(account_id, **overrides), agent_headers
        )
    )


def add_scheduled_item(
    agent_headers: Dict[str, str], policy_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_scheduled_item(
            policy_id, create_scheduled_item_payload(**overrides), agent_headers
        )
    )


def add_seasonal_item(agent_headers: Dict[str, str], policy_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_scheduled_item(
            policy_id, create_seasonal_item_payload(**overrides), agent_headers
        )
    )


def add_livestock_group(
    agent_headers: Dict[str, str], policy_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_livestock_group(
            policy_id, create_livestock_group_payload(**overrides), agent_headers
        )
    )


def add_liability_exposure(
    agent_headers: Dict[str, str], policy_id: str, exposure_type: str = "GENERAL_FARM", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_liability_exposure(
            policy_id,
            create_liability_exposure_payload(exposure_type=exposure_type, **overrides),
            agent_headers,
        )
    )


def upsert_labor_profile(
    agent_headers: Dict[str, str],
    policy_id: str,
    full_time_count: int = 0,
    seasonal_count: int = 0,
    migrant_h2a_count: int = 0,
    **overrides,
) -> Dict[str, Any]:
    payload = create_labor_profile_payload(
        full_time_count=full_time_count,
        seasonal_count=seasonal_count,
        migrant_h2a_count=migrant_h2a_count,
        **overrides,
    )
    return get_success_data(api_client.upsert_labor_profile(policy_id, payload, agent_headers))


# ---------------------------------------------------------------------------
# Reads used as setup steps
# ---------------------------------------------------------------------------


def read_policy(policy_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_farm_policy(policy_id, headers or UW))


def policy_version(policy_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return read_policy(policy_id, headers)["version"]


def read_pool(pool_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_cat_capacity_pool(pool_id, headers or UW))


def pool_version(pool_id: str) -> int:
    return read_pool(pool_id)["version"]


def read_item(item_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_scheduled_item(item_id, headers or UW))


def read_endorsement(endorsement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_endorsement(endorsement_id, headers or UW))


def read_inspection(inspection_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_inspection(inspection_id, headers or UW))


def read_labor_profile(labor_profile_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_labor_profile(labor_profile_id, headers or UW))


def read_ledger(policy_id: str, headers: Optional[Dict[str, str]] = None, **params) -> List[dict]:
    """The append-only premium ledger of a policy in `sequence_no` order."""
    query = {"limit": 100}
    query.update(params)
    body = api_client.list_premium_transactions(policy_id, headers or UW, params=query)
    return get_success_data(body)


def read_reservations(policy_id: str, headers: Optional[Dict[str, str]] = None, **params) -> List[dict]:
    query = {"policy_id": policy_id, "limit": 100}
    query.update(params)
    return get_success_data(api_client.list_cat_reservations(headers or UW, params=query))


def reservation_by_peril(policy_id: str) -> Dict[str, dict]:
    return {row["peril"]: row for row in read_reservations(policy_id)}


def read_recommendations(inspection_id: str, headers: Optional[Dict[str, str]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_recommendations(inspection_id, headers or UW, params={"limit": 100})
    )


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3 lifecycle drivers
# ---------------------------------------------------------------------------


def rate_policy(policy_id: str, headers: Optional[Dict[str, str]] = None):
    """Read the current policy version, then rate. Returns the raw response so
    a caller can assert on either branch."""
    version = policy_version(policy_id, headers or UW)
    return api_client.rate_farm_policy(
        policy_id, {"expected_policy_version": version}, headers or UW
    )


def rate_policy_ok(policy_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(rate_policy(policy_id, headers))


def bind_policy(policy_id: str, headers: Optional[Dict[str, str]] = None):
    version = policy_version(policy_id, headers or UW)
    return api_client.bind_farm_policy(
        policy_id, {"expected_policy_version": version}, headers or UW
    )


def bind_policy_ok(policy_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(bind_policy(policy_id, headers))


def cancel_policy(
    policy_id: str, closure_reason: str = "Insured sold the operation", headers=None
):
    version = policy_version(policy_id, headers or UW)
    return api_client.cancel_farm_policy(
        policy_id,
        {"expected_policy_version": version, "closure_reason": closure_reason},
        headers or UW,
    )


def cancel_policy_ok(policy_id: str, closure_reason: str = "Insured sold the operation", headers=None):
    return get_success_data(cancel_policy(policy_id, closure_reason, headers))


def decline_policy(policy_id: str, closure_reason: str = "Risk outside appetite", headers=None):
    return api_client.decline_farm_policy(
        policy_id, {"closure_reason": closure_reason}, headers or UW
    )


def decline_policy_ok(policy_id: str, closure_reason: str = "Risk outside appetite", headers=None):
    return get_success_data(decline_policy(policy_id, closure_reason, headers))


def decide_referral(policy_id: str, decision: str, decision_note: str = "", headers=None):
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note:
        payload["decision_note"] = decision_note
    return api_client.decide_referral(policy_id, payload, headers or SENIOR_ALT)


def request_endorsement(
    agent_headers: Dict[str, str],
    policy_id: str,
    form_code: str = "PEAK_SEASON_INCREASE",
    sublimit_cents: int = 12_000_000,
    requested_effective_date: str = "2026-10-01",
):
    """Requesting an endorsement carries the policy version as the client last
    observed it and does not itself lift the policy's version."""
    version = policy_version(policy_id, UW)
    payload = {
        "expected_policy_version": version,
        "form_code": form_code,
        "sublimit_cents": sublimit_cents,
        "requested_effective_date": requested_effective_date,
    }
    return api_client.create_endorsement(policy_id, payload, agent_headers)


def request_endorsement_ok(agent_headers, policy_id, **kwargs) -> Dict[str, Any]:
    return get_success_data(request_endorsement(agent_headers, policy_id, **kwargs))


def decide_endorsement(endorsement_id: str, decision: str, decision_note: str = "", headers=None):
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note:
        payload["decision_note"] = decision_note
    return api_client.decide_endorsement(endorsement_id, payload, headers or UW)


def approve_endorsement_ok(endorsement_id: str, decision_note: str = "Accepted") -> Dict[str, Any]:
    return get_success_data(decide_endorsement(endorsement_id, "APPROVE", decision_note))


def rescind_endorsement(endorsement_id: str, decision_note: str = "", headers=None):
    payload: Dict[str, Any] = {}
    if decision_note:
        payload["decision_note"] = decision_note
    return api_client.rescind_endorsement(endorsement_id, payload, headers or UW)


def schedule_inspection(
    policy_id: str,
    inspector_id: str,
    inspection_type: str = "INITIAL",
    scheduled_for: str = "2026-08-16T09:00:00Z",
    duration_minutes: int = 120,
    headers=None,
):
    payload = create_inspection_payload(
        policy_id, inspector_id, inspection_type, scheduled_for, duration_minutes
    )
    return api_client.create_inspection(payload, headers or UW)


def schedule_inspection_ok(policy_id: str, inspector_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(schedule_inspection(policy_id, inspector_id, **kwargs))


def complete_inspection(
    inspection_id: str,
    inspector_id: str,
    findings_summary: str = "Visit complete",
    findings: Optional[List[dict]] = None,
):
    """Only the assigned inspector may complete the visit."""
    payload = {"findings_summary": findings_summary, "findings": list(findings or [])}
    return api_client.complete_inspection(
        inspection_id, payload, make_loss_control_headers(inspector_id)
    )


def complete_inspection_ok(inspection_id: str, inspector_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(complete_inspection(inspection_id, inspector_id, **kwargs))


def reinspect(
    inspection_id: str,
    scheduled_for: str = "2026-08-18T09:00:00Z",
    duration_minutes: int = 120,
    headers=None,
):
    return api_client.reinspect_inspection(
        inspection_id,
        {"scheduled_for": scheduled_for, "duration_minutes": duration_minutes},
        headers or UW,
    )


def submit_evidence(
    agent_headers: Dict[str, str],
    recommendation_id: str,
    evidence_note: str = "Work completed and photographed",
    completed_date: str = "2026-08-15",
):
    return api_client.submit_recommendation_evidence(
        recommendation_id,
        {"evidence_note": evidence_note, "completed_date": completed_date},
        agent_headers,
    )


def review_recommendation(recommendation_id: str, decision: str, review_note: str = "", headers=None):
    payload: Dict[str, Any] = {"decision": decision}
    if review_note:
        payload["review_note"] = review_note
    return api_client.review_recommendation(recommendation_id, payload, headers or COMPLIANCE)


def run_sweep(policy_id: Optional[str] = None, headers=None):
    payload: Dict[str, Any] = {}
    if policy_id:
        payload["policy_id"] = policy_id
    return api_client.run_compliance_sweep(payload, headers or COMPLIANCE)


def run_sweep_ok(policy_id: Optional[str] = None, headers=None) -> Dict[str, Any]:
    return get_success_data(run_sweep(policy_id, headers))


def verify_wc(labor_profile_id: str, note: str = "", headers=None):
    payload: Dict[str, Any] = {}
    if note:
        payload["note"] = note
    return api_client.verify_wc_coordination(labor_profile_id, payload, headers or COMPLIANCE)


def patch_item(item_id: str, agent_headers: Dict[str, str], **changes):
    """Re-value a scheduled item, flip its election, or remove it."""
    return api_client.update_scheduled_item(item_id, dict(changes), agent_headers)


def patch_item_ok(item_id: str, agent_headers: Dict[str, str], **changes) -> Dict[str, Any]:
    return get_success_data(patch_item(item_id, agent_headers, **changes))


def patch_agent(agent_id: str, headers=None, **changes):
    """Suspend, reinstate or re-authorise a producer agency."""
    return api_client.update_agent(agent_id, dict(changes), headers or ADMIN)


def patch_agent_ok(agent_id: str, **changes) -> Dict[str, Any]:
    return get_success_data(patch_agent(agent_id, **changes))


def patch_inspector(inspector_id: str, headers=None, **changes):
    """Change an inspector's standing or daily capacity."""
    return api_client.update_inspector(inspector_id, dict(changes), headers or ADMIN)


def patch_inspector_ok(inspector_id: str, **changes) -> Dict[str, Any]:
    return get_success_data(patch_inspector(inspector_id, **changes))


def patch_pool(pool_id: str, headers=None, **changes):
    payload: Dict[str, Any] = {"expected_pool_version": pool_version(pool_id)}
    payload.update(changes)
    return api_client.update_cat_capacity_pool(pool_id, payload, headers or ADMIN)


# ---------------------------------------------------------------------------
# Tier 2: bootstrap composites
# ---------------------------------------------------------------------------


def bootstrap_zone(
    clock: str = DEFAULT_TEST_CLOCK,
    zone_code: str = "ZN-1",
    authority_limit_cents: int = 5_000_000,
    hail_capacity_cents: int = 200_000_000,
    wind_capacity_cents: int = 200_000_000,
    wildfire_capacity_cents: int = 200_000_000,
    perils=("HAIL", "WIND", "WILDFIRE"),
    account_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    with_policy: bool = True,
) -> Scenario:
    """Clock + one producer + the zone's three capacity pools + one account in
    that zone + one DRAFT policy on it with no exposures yet."""
    set_clock(clock)
    agent = register_agent(authority_limit_cents=authority_limit_cents)
    agent_headers = make_agent_headers(agent["id"])
    pools = open_zone_pools(
        zone_code,
        hail_capacity_cents=hail_capacity_cents,
        wind_capacity_cents=wind_capacity_cents,
        wildfire_capacity_cents=wildfire_capacity_cents,
        perils=perils,
    )
    account = open_account(agent_headers, cat_zone_code=zone_code, **(account_overrides or {}))
    scenario = Scenario(
        agent=agent,
        agent_headers=agent_headers,
        pools=pools,
        account=account,
        zone_code=zone_code,
    )
    if with_policy:
        scenario.policy = open_policy(agent_headers, account["id"], **(policy_overrides or {}))
    return scenario


def setup_draft_policy_with_dwelling(
    clock: str = DEFAULT_TEST_CLOCK,
    zone_code: str = "ZN-1",
    stated_value_cents: int = 40_000_000,
    deductible_cents: int = 500_000,
    **bootstrap_kwargs,
) -> Scenario:
    """The ZN-1 bootstrap plus a single replacement-cost dwelling stated at
    40000000 cents — the canonical rateable DRAFT package."""
    scenario = bootstrap_zone(
        clock=clock,
        zone_code=zone_code,
        policy_overrides={"deductible_cents": deductible_cents},
        **bootstrap_kwargs,
    )
    scenario.items.append(
        add_scheduled_item(
            scenario.agent_headers,
            scenario.policy_id,
            stated_value_cents=stated_value_cents,
        )
    )
    return scenario


def setup_rated_dwelling_policy(
    clock: str = DEFAULT_TEST_CLOCK,
    zone_code: str = "ZN-1",
    stated_value_cents: int = 40_000_000,
    deductible_cents: int = 500_000,
    with_labor_profile: bool = True,
    **bootstrap_kwargs,
) -> Scenario:
    """A RATED single-dwelling package: property 144000, catastrophe load
    125200, total 269200. With `with_labor_profile` the policy also carries an
    all-zero labor profile, so its coordination is NOT_REQUIRED and the package
    is bindable."""
    scenario = setup_draft_policy_with_dwelling(
        clock=clock,
        zone_code=zone_code,
        stated_value_cents=stated_value_cents,
        deductible_cents=deductible_cents,
        **bootstrap_kwargs,
    )
    if with_labor_profile:
        scenario.labor_profile = upsert_labor_profile(
            scenario.agent_headers, scenario.policy_id
        )
    scenario.policy = rate_policy_ok(scenario.policy_id)
    return scenario


def setup_bound_dwelling_policy(**kwargs) -> Scenario:
    """A BOUND single-dwelling package, with the three reservations COMMITTED."""
    scenario = setup_rated_dwelling_policy(**kwargs)
    scenario.policy = bind_policy_ok(scenario.policy_id)
    return scenario


def setup_rated_policy_with_inspector(
    inspection_scheduled_for: str = "2026-08-16T09:00:00Z",
    duration_minutes: int = 120,
    with_labor_profile: bool = True,
    with_inspection: bool = True,
    **kwargs,
) -> Scenario:
    """A RATED single-dwelling package plus an ACTIVE inspector and, by default,
    one SCHEDULED INITIAL inspection on that inspector's calendar."""
    scenario = setup_rated_dwelling_policy(with_labor_profile=with_labor_profile, **kwargs)
    scenario.inspector = register_inspector()
    if with_inspection:
        scenario.inspections.append(
            schedule_inspection_ok(
                scenario.policy_id,
                scenario.inspector_id,
                scheduled_for=inspection_scheduled_for,
                duration_minutes=duration_minutes,
            )
        )
    return scenario


def setup_policy_with_approved_endorsement(
    form_code: str = "PEAK_SEASON_INCREASE",
    sublimit_cents: int = 12_000_000,
    requested_effective_date: str = "2026-10-01",
    **kwargs,
) -> Scenario:
    """A RATED single-dwelling package carrying one APPROVED endorsement."""
    scenario = setup_rated_dwelling_policy(**kwargs)
    endorsement = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code=form_code,
        sublimit_cents=sublimit_cents,
        requested_effective_date=requested_effective_date,
    )
    scenario.endorsements.append(approve_endorsement_ok(endorsement["id"]))
    scenario.policy = read_policy(scenario.policy_id)
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: targeted pricing scenarios
# ---------------------------------------------------------------------------


def setup_full_schedule_policy(clock: str = DEFAULT_TEST_CLOCK) -> Scenario:
    """A DRAFT package carrying all five property lines that exercise per-line
    rounding, one per-head cattle group and three liability exposures."""
    scenario = setup_draft_policy_with_dwelling(clock=clock)
    headers, policy_id = scenario.agent_headers, scenario.policy_id
    scenario.items.append(
        add_scheduled_item(
            headers,
            policy_id,
            item_class="FARM_STRUCTURE",
            description="Machine shed",
            valuation_basis="ACV",
            stated_value_cents=12_000_000,
            age_years=18,
            condition_grade="C",
        )
    )
    scenario.items.append(
        add_scheduled_item(
            headers,
            policy_id,
            item_class="EQUIPMENT",
            description="Combine harvester",
            valuation_basis="ACV",
            stated_value_cents=30_001_000,
            age_years=12,
            condition_grade="B",
        )
    )
    scenario.items.append(
        add_seasonal_item(
            headers,
            policy_id,
            item_class="STORED_CROP",
            stated_value_cents=6_005_000,
            peak_season_value_cents=18_000_000,
            peak_season_start_month=10,
            peak_season_end_month=2,
        )
    )
    scenario.items.append(
        add_seasonal_item(
            headers,
            policy_id,
            item_class="HAY",
            description="Alfalfa stack",
            stated_value_cents=2_760_000,
            peak_season_value_cents=8_280_000,
            peak_season_start_month=6,
            peak_season_end_month=9,
        )
    )
    scenario.livestock.append(
        add_livestock_group(
            headers,
            policy_id,
            species="CATTLE",
            head_count=170,
            per_head_value_cents=150_000,
            limit_basis="PER_HEAD",
            peril_scope="FULL_PERIL",
        )
    )
    scenario.liabilities.append(
        add_liability_exposure(headers, policy_id, "GENERAL_FARM", annual_receipts_cents=0)
    )
    scenario.liabilities.append(
        add_liability_exposure(
            headers,
            policy_id,
            "AGRITOURISM",
            annual_receipts_cents=4_000_000,
            annual_visitor_count=800,
        )
    )
    scenario.liabilities.append(
        add_liability_exposure(
            headers, policy_id, "CUSTOM_FARMING", annual_receipts_cents=15_000_000
        )
    )
    return scenario


def setup_thin_hail_zone_policy(
    zone_code: str,
    hail_capacity_cents: int,
    clock: str = DEFAULT_TEST_CLOCK,
    stated_value_cents: int = 40_000_000,
) -> Scenario:
    """A DRAFT single-dwelling package in a zone whose HAIL pool is deliberately
    small, so the prospective utilization lands in a chosen scarcity band."""
    return setup_draft_policy_with_dwelling(
        clock=clock,
        zone_code=zone_code,
        stated_value_cents=stated_value_cents,
        hail_capacity_cents=hail_capacity_cents,
    )


def setup_agritourism_referral_policy(clock: str = DEFAULT_TEST_CLOCK) -> Scenario:
    """A DRAFT single-dwelling package plus an AGRITOURISM exposure of 2500
    visitors, which trips the visitor referral trigger at rating."""
    scenario = setup_draft_policy_with_dwelling(clock=clock)
    scenario.liabilities.append(
        add_liability_exposure(
            scenario.agent_headers,
            scenario.policy_id,
            "AGRITOURISM",
            annual_receipts_cents=4_000_000,
            annual_visitor_count=2500,
        )
    )
    return scenario


def setup_suspended_compliance_policy(
    clock: str = DEFAULT_TEST_CLOCK,
    critical_due_date: str = "2026-08-10",
    **kwargs,
) -> Scenario:
    """A RATED package escalated to compliance SUSPENDED: an INITIAL inspection
    completed with one CRITICAL finding already past its due date, then one
    compliance checkpoint run at the current clock."""
    scenario = setup_rated_policy_with_inspector(clock=clock, **kwargs)
    complete_inspection_ok(
        scenario.inspection["id"],
        scenario.inspector_id,
        findings_summary="Anhydrous nurse tank unsecured",
        findings=[
            {
                "severity": "CRITICAL",
                "description": "Secure and placard the nurse tank",
                "due_date": critical_due_date,
            }
        ],
    )
    run_sweep_ok(scenario.policy_id)
    scenario.policy = read_policy(scenario.policy_id)
    return scenario


__all__ = [
    "DEFAULT_TEST_CLOCK",
    "ADMIN",
    "UW",
    "UW_ALT",
    "SENIOR",
    "SENIOR_ALT",
    "COMPLIANCE",
    "Scenario",
    "set_clock",
    "register_agent",
    "register_inspector",
    "open_pool",
    "open_zone_pools",
    "open_account",
    "open_policy",
    "add_scheduled_item",
    "add_seasonal_item",
    "add_livestock_group",
    "add_liability_exposure",
    "upsert_labor_profile",
    "read_policy",
    "policy_version",
    "read_pool",
    "pool_version",
    "read_item",
    "read_endorsement",
    "read_inspection",
    "read_labor_profile",
    "read_ledger",
    "read_reservations",
    "reservation_by_peril",
    "read_recommendations",
    "rate_policy",
    "rate_policy_ok",
    "bind_policy",
    "bind_policy_ok",
    "cancel_policy",
    "cancel_policy_ok",
    "decline_policy",
    "decline_policy_ok",
    "decide_referral",
    "request_endorsement",
    "request_endorsement_ok",
    "decide_endorsement",
    "approve_endorsement_ok",
    "rescind_endorsement",
    "schedule_inspection",
    "schedule_inspection_ok",
    "complete_inspection",
    "complete_inspection_ok",
    "reinspect",
    "submit_evidence",
    "review_recommendation",
    "run_sweep",
    "run_sweep_ok",
    "verify_wc",
    "patch_item",
    "patch_item_ok",
    "patch_agent",
    "patch_agent_ok",
    "patch_inspector",
    "patch_inspector_ok",
    "patch_pool",
    "bootstrap_zone",
    "setup_draft_policy_with_dwelling",
    "setup_rated_dwelling_policy",
    "setup_bound_dwelling_policy",
    "setup_rated_policy_with_inspector",
    "setup_policy_with_approved_endorsement",
    "setup_full_schedule_policy",
    "setup_thin_hail_zone_policy",
    "setup_agritourism_referral_policy",
    "setup_suspended_compliance_policy",
]
