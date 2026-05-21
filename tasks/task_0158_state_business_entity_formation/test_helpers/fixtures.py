"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late
lifecycle state that takes 5–15 API calls to reach. Each fixture
composes the lower-level steps so the test body can focus on the rule
under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Filer, X-User-ID is the id of the acting
    BusinessEntity; ownership checks on any resource that references a
    BusinessEntity compare the resource's business_entity_id to
    X-User-ID."

After a BusinessEntity is created, fixtures act as that Filer by
minting headers via make_filer_headers(entity["id"]) — never by
reusing the shared TEST_USERS["filer_headers"] constant for
ownership-gated operations. The shared constant is reserved for tests
that probe auth/RBAC failure modes without exercising ownership.
The same rule applies to RegisteredAgentService and the resign-agent
path: make_registered_agent_headers(agent["id"]).

CLOCK ANCHORING — PRD §3.12:

    "Advancing the clock by a duration sweeps every entity in one
    pass, applying every overdue-tax transition, every delinquency
    transition, every stale-BOI transition, and every cascade those
    transitions imply, and finally recomputes compliance_status for
    every entity using the rule in §3.6."

The logical clock is shared across the test process. Fixtures advance
the clock via the TestHarness role; they never make absolute clock
assumptions — only relative durations from "wherever the clock is now".

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    ADMIN_DISSOLUTION_WAIT_DAYS,
    BOI_STALE_TIMER_DAYS,
    TAX_DELINQUENCY_DAYS,
)
from .factories import (
    add_boi_ownership_payload,
    clock_advance_payload,
    create_annual_report_payload,
    create_beneficial_owner_payload,
    create_boi_report_payload,
    create_ein_application_payload,
    create_entity_payload,
    create_foreign_qualification_payload,
    create_operating_agreement_payload,
    create_registered_agent_payload,
    create_tax_assessment_payload,
    credit_deposit_payload,
    iso_now,
    parse_iso,
    reject_annual_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_filer_headers,
    make_registered_agent_headers,
)


# ===========================================================================
# Low-level read helpers
# ===========================================================================
def get_entity(entity_id: str, headers: Optional[Dict[str, str]] = None,
               ) -> Dict[str, Any]:
    """Read a BusinessEntity. Falls back to the shared filer headers
    only when no caller-supplied headers exist — most call sites pass
    make_filer_headers(entity_id) directly so ownership checks resolve.
    """
    h = headers or TEST_USERS["filer_headers"]
    return get_success_data(api_client.get_entity(entity_id, h))


def get_tax_assessment(assessment_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    h = headers or TEST_USERS["tax_officer_headers"]
    return get_success_data(api_client.get_tax_assessment(assessment_id, h))


def list_compliance_events(entity_id: str,
                           headers: Optional[Dict[str, str]] = None,
                           **params: Any) -> List[Dict[str, Any]]:
    """List ComplianceEvent rows for an entity. Returns the data array
    only (test_suite handles meta if needed). Uses validate_paginated
    because PRD §2.3 declares list endpoints paginated.
    """
    h = headers or make_filer_headers(entity_id)
    if not params:
        params = {"limit": 100}
    elif "limit" not in params:
        params["limit"] = 100
    resp = api_client.list_compliance_events(entity_id, h, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ===========================================================================
# RegisteredAgent fixtures — PRD §3.2
# ===========================================================================
def create_registered_agent(service_state: str = "DE",
                            **overrides: Any,
                            ) -> Dict[str, Any]:
    """Create a RegisteredAgent via a RegisteredAgentService caller.

    The headers used to create the agent are the shared
    RegisteredAgentService constant — PRD §3.2 permits creation by
    either RegisteredAgentService or StateRegistrar without ownership-
    gating creation itself.
    """
    payload = create_registered_agent_payload(
        service_state=service_state, **overrides,
    )
    resp = api_client.create_registered_agent(
        payload, TEST_USERS["registered_agent_service_headers"],
    )
    return get_success_data(resp)


def resign_registered_agent(agent_id: str) -> Dict[str, Any]:
    """PRD §3.2 / §4: resign is exclusive to RegisteredAgentService;
    PRD §2.1 makes RegisteredAgentService entity_backed:RegisteredAgent.
    """
    resp = api_client.resign_registered_agent(
        agent_id, make_registered_agent_headers(agent_id),
    )
    return get_success_data(resp)


# ===========================================================================
# BusinessEntity fixtures — PRD §3.1
# ===========================================================================
def create_entity_in_pending(entity_type: str = "LLC",
                             home_state: str = "DE",
                             agent: Optional[Dict[str, Any]] = None,
                             **overrides: Any,
                             ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an agent in `home_state` and a BusinessEntity referencing
    it. Returns (entity, agent). Entity remains PENDING_FORMATION.
    """
    if agent is None:
        agent = create_registered_agent(service_state=home_state)
    payload = create_entity_payload(
        entity_type=entity_type,
        home_state=home_state,
        registered_agent_id=agent["id"],
        **overrides,
    )
    resp = api_client.create_entity(payload, TEST_USERS["filer_headers"])
    entity = get_success_data(resp)
    return entity, agent


def form_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Drive PENDING_FORMATION → ACTIVE via a StateRegistrar caller.
    PRD §3.1: "Formation proper is a separate step performed by a
    StateRegistrar."
    """
    resp = api_client.form_entity(
        entity["id"], TEST_USERS["state_registrar_headers"],
    )
    return get_success_data(resp)


def create_and_activate_entity(entity_type: str = "LLC",
                               home_state: str = "DE",
                               **overrides: Any,
                               ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Combine create-in-pending + form. Returns (entity, agent) where
    entity.formation_status is ACTIVE and compliance_status is
    GOOD_STANDING per PRD §3.1 ("Upon successful formation the system
    ... sets compliance_status to GOOD_STANDING").
    """
    entity, agent = create_entity_in_pending(
        entity_type=entity_type, home_state=home_state, **overrides,
    )
    entity = form_entity(entity)
    return entity, agent


def credit_deposit(entity_id: str, amount_cents: int) -> Dict[str, Any]:
    """PRD §3.6: "The credit-deposit endpoint, accepting amount_cents,
    lets a TaxOfficer top up an entity's credit_balance_cents."""
    resp = api_client.credit_deposit(
        entity_id,
        credit_deposit_payload(amount_cents),
        TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# OperatingAgreement fixtures — PRD §3.3
# ===========================================================================
def attach_operating_agreement(entity_id: str,
                               template_code: str = "LLC_MM",
                               template_version: str = "1.0.0",
                               ) -> Dict[str, Any]:
    resp = api_client.create_operating_agreement(
        create_operating_agreement_payload(
            entity_id,
            template_code=template_code,
            template_version=template_version,
        ),
        make_filer_headers(entity_id),
    )
    return get_success_data(resp)


# ===========================================================================
# EINApplication fixtures — PRD §3.4
# ===========================================================================
def create_ein_application(entity_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    resp = api_client.create_ein_application(
        create_ein_application_payload(entity_id, **overrides),
        make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def submit_ein_application(app_id: str,
                           entity_id: str) -> Dict[str, Any]:
    resp = api_client.submit_ein_application(
        app_id, make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def approve_ein_application(app_id: str) -> Dict[str, Any]:
    """Use the shared TaxOfficer headers — opaque role. PRD §3.4
    segregation rule: "the TaxOfficer's X-User-ID must not equal the
    BusinessEntity.id that owns the application." The shared id is
    never an entity id, so no SoD collision.
    """
    resp = api_client.approve_ein_application(
        app_id, TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


def create_submitted_ein(entity_id: str) -> Dict[str, Any]:
    """Create DRAFT EIN application and advance to SUBMITTED."""
    app = create_ein_application(entity_id)
    return submit_ein_application(app["id"], entity_id)


def create_approved_ein(entity_id: str) -> Dict[str, Any]:
    """Full lifecycle: DRAFT → SUBMITTED → APPROVED. Returns the
    approved application (assigned_ein populated)."""
    app = create_submitted_ein(entity_id)
    return approve_ein_application(app["id"])


# ===========================================================================
# AnnualReport fixtures — PRD §3.5
# ===========================================================================
def create_draft_annual_report(entity_id: str, report_year: int,
                               **overrides: Any) -> Dict[str, Any]:
    resp = api_client.create_annual_report(
        create_annual_report_payload(entity_id, report_year, **overrides),
        make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def submit_annual_report(report_id: str,
                         entity_id: str) -> Dict[str, Any]:
    resp = api_client.submit_annual_report(
        report_id, make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def accept_annual_report(report_id: str) -> Dict[str, Any]:
    """Use shared TaxOfficer headers. PRD §3.5: accepter's X-User-ID
    must not equal BusinessEntity.id — the shared op-id is never an
    entity id, so SoD is satisfied."""
    resp = api_client.accept_annual_report(
        report_id, TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


def reject_annual_report(report_id: str, reason: str) -> Dict[str, Any]:
    resp = api_client.reject_annual_report(
        report_id,
        reject_annual_report_payload(reason),
        TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


def create_submitted_annual_report(entity_id: str,
                                   report_year: int,
                                   **overrides: Any) -> Dict[str, Any]:
    """Create DRAFT and submit to SUBMITTED."""
    rep = create_draft_annual_report(entity_id, report_year, **overrides)
    return submit_annual_report(rep["id"], entity_id)


def create_accepted_annual_report(entity_id: str,
                                  report_year: int,
                                  **overrides: Any) -> Dict[str, Any]:
    """Full DRAFT → SUBMITTED → ACCEPTED lifecycle."""
    sub = create_submitted_annual_report(
        entity_id, report_year, **overrides,
    )
    return accept_annual_report(sub["id"])


# ===========================================================================
# FranchiseTaxAssessment fixtures — PRD §3.6
# ===========================================================================
def create_tax_assessment(entity_id: str, tax_year: int,
                          calculation_method: str) -> Dict[str, Any]:
    """PRD §3.6: assessment creation is exclusive to TaxOfficer."""
    resp = api_client.create_tax_assessment(
        create_tax_assessment_payload(
            entity_id, tax_year, calculation_method,
        ),
        TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


def pay_tax_assessment(assessment_id: str,
                       entity_id: str) -> Dict[str, Any]:
    """PRD §3.6: pay is exclusive to Filer. The Filer's X-User-ID must
    equal the owning BusinessEntity.id (ownership) — and must not equal
    any TaxOfficer who accepted an AnnualReport in the same tax_year
    (SoD). Using make_filer_headers(entity_id) threads ownership;
    fixtures default to a TaxOfficer id never reused as a Filer."""
    resp = api_client.pay_tax_assessment(
        assessment_id, make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def refund_tax_assessment(assessment_id: str) -> Dict[str, Any]:
    """PRD §3.6: refund is a TaxOfficer compensating action."""
    resp = api_client.refund_tax_assessment(
        assessment_id, TEST_USERS["tax_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# ForeignQualification fixtures — PRD §3.7
# ===========================================================================
def create_pending_foreign_qualification(entity_id: str,
                                         foreign_state: str,
                                         foreign_agent_id: Optional[str] = None,
                                         cogs_date: Optional[str] = None,
                                         ) -> Tuple[Dict[str, Any], str]:
    """Create a pending foreign qualification. Returns (qual, agent_id).

    PRD §3.7: foreign_registered_agent_id must resolve to an agent
    whose service_state equals foreign_state. If no agent id is
    supplied, the fixture creates one in foreign_state.
    """
    if foreign_agent_id is None:
        agent = create_registered_agent(service_state=foreign_state)
        foreign_agent_id = agent["id"]
    if cogs_date is None:
        # PRD §3.7: COGS must be within 60 days of the CURRENT clock.
        # Use the server clock — wall-clock drift relative to the
        # advanced server clock would push the date past 60 days.
        cogs_date = server_now_iso()
    payload = create_foreign_qualification_payload(
        entity_id, foreign_state, foreign_agent_id, cogs_date,
    )
    resp = api_client.create_foreign_qualification(
        payload, make_filer_headers(entity_id),
    )
    return get_success_data(resp), foreign_agent_id


def approve_foreign_qualification(qual_id: str) -> Dict[str, Any]:
    """Approve is exclusive to StateRegistrar."""
    resp = api_client.approve_foreign_qualification(
        qual_id, TEST_USERS["state_registrar_headers"],
    )
    return get_success_data(resp)


def create_qualified_foreign(entity_id: str,
                             foreign_state: str = "NY",
                             ) -> Tuple[Dict[str, Any], str]:
    """Drive PENDING → QUALIFIED. Returns (qualification, agent_id)."""
    qual, agent_id = create_pending_foreign_qualification(
        entity_id, foreign_state,
    )
    qual = approve_foreign_qualification(qual["id"])
    return qual, agent_id


# ===========================================================================
# BeneficialOwner / BOIOwnership / BOIReport fixtures — PRD §3.8
# ===========================================================================
def create_beneficial_owner(**overrides: Any) -> Dict[str, Any]:
    """Filer-exclusive. The shared filer constant is fine here because
    PRD §3.8 doesn't make BeneficialOwner ownership-gated by Filer id —
    however we use make_filer_headers when the caller threads an entity
    id, to keep identity consistent across compound setups.
    """
    headers = overrides.pop("headers", TEST_USERS["filer_headers"])
    resp = api_client.create_beneficial_owner(
        create_beneficial_owner_payload(**overrides), headers,
    )
    return get_success_data(resp)


def add_boi_ownership(entity_id: str, owner_id: str,
                      bps: int) -> Dict[str, Any]:
    resp = api_client.add_boi_ownership(
        entity_id,
        add_boi_ownership_payload(owner_id, bps),
        make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def delete_boi_ownership(entity_id: str, ownership_id: str) -> None:
    """DELETE returns 204 with no body — accept the 2xx and ignore the
    body."""
    resp = api_client.delete_boi_ownership(
        entity_id, ownership_id, make_filer_headers(entity_id),
    )
    # PRD §4: "DELETE on BOIOwnership returns 204 with no body"
    assert 200 <= resp.status_code < 300, (
        f"Setup failed: delete BOI ownership returned {resp.status_code} "
        f"{resp.text}"
    )


def create_boi_report(entity_id: str,
                      filing_type: str = "INITIAL") -> Dict[str, Any]:
    resp = api_client.create_boi_report(
        create_boi_report_payload(entity_id, filing_type),
        make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def file_boi_report(report_id: str, entity_id: str) -> Dict[str, Any]:
    resp = api_client.file_boi_report(
        report_id, make_filer_headers(entity_id),
    )
    return get_success_data(resp)


def setup_owners_full_100(entity_id: str,
                          ) -> Tuple[List[Dict[str, Any]],
                                     List[Dict[str, Any]]]:
    """Add two beneficial owners summing to exactly 10000 bps for the
    entity. Returns (owners, ownerships). Default document type
    spreads two RISK_DEFAULT owners (weight 1 each).
    """
    o1 = create_beneficial_owner()
    o2 = create_beneficial_owner(
        identifying_document_type="STATE_DRIVERS_LICENSE",
    )
    own1 = add_boi_ownership(entity_id, o1["id"], 4000)
    own2 = add_boi_ownership(entity_id, o2["id"], 6000)
    return [o1, o2], [own1, own2]


def setup_initial_boi_filed(entity_id: str,
                            owners: Optional[List[Dict[str, Any]]] = None,
                            ownerships: Optional[List[Dict[str, Any]]] = None,
                            ) -> Tuple[Dict[str, Any],
                                       List[Dict[str, Any]],
                                       List[Dict[str, Any]]]:
    """Set up an INITIAL BOIReport filed → CURRENT for entity_id.
    Returns (report, owners, ownerships).
    """
    if owners is None or ownerships is None:
        owners, ownerships = setup_owners_full_100(entity_id)
    rep = create_boi_report(entity_id, "INITIAL")
    rep = file_boi_report(rep["id"], entity_id)
    return rep, owners, ownerships


# ===========================================================================
# Time-driving helpers — PRD §3.12
# ===========================================================================
def advance_clock_iso(duration_iso8601: str) -> Dict[str, Any]:
    """Advance the server clock by an ISO 8601 duration.
    PRD §3.12: only TestHarness may call /_clock/advance."""
    resp = api_client.advance_clock(
        clock_advance_payload(duration_iso8601),
        TEST_USERS["test_harness_headers"],
    )
    return get_success_data(resp)


def advance_clock_by_days(days: int) -> Dict[str, Any]:
    return advance_clock_iso(f"P{days}D")


def run_sweep() -> Dict[str, Any]:
    resp = api_client.run_sweep(TEST_USERS["test_harness_headers"])
    return get_success_data(resp)


def server_now_iso() -> str:
    """Return the current server clock instant (ISO 8601 UTC).

    PRD §3.12: the sweep endpoint returns ``{"now": <iso>, ...}``. Tests
    that mint date inputs (cogs_date, report_year, tax_year) must derive
    them from the server clock — not Python's wall-clock — because the
    server clock drifts forward as earlier tests advance it.
    """
    data = run_sweep()
    now = data.get("now")
    assert now is not None, (
        "sweep response must carry the current server clock instant"
    )
    return now


def server_now_year() -> int:
    """Return the calendar year of the current server clock instant."""
    return parse_iso(server_now_iso()).year


def setup_active_entity_eligible_for_annual_report(
    entity_type: str = "LLC", home_state: str = "DE",
    **overrides: Any,
) -> Tuple[Dict[str, Any], int]:
    """Create + form an entity, then advance the clock by ~1 year so the
    entity's formation_year is strictly less than the current server
    year. Returns ``(entity, report_year)`` where ``report_year`` is the
    current server calendar year — the largest value that satisfies
    PRD §3.5's report_year window (``> formation_year`` and
    ``<= current_year``).

    PRD §3.5: "The report_year must be strictly greater than the
    formation year (the year extracted from formation_date) and less
    than or equal to the current calendar year derived from the clock"
    """
    entity, _agent = create_and_activate_entity(
        entity_type=entity_type, home_state=home_state, **overrides,
    )
    # Advance the clock by ~13 months so the calendar year increments
    # at least once past the entity's formation_year.
    advance_clock_by_days(395)
    report_year = server_now_year()
    return entity, report_year


# ===========================================================================
# Threshold / boundary fixtures — driven by SCAFFOLD_DIFFICULTY_DESIGN
# ===========================================================================
def setup_active_corp_with_shares(authorized_shares: int,
                                  home_state: str = "DE",
                                  total_gross_assets_cents: int = 0,
                                  total_issued_shares: int = 0,
                                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ACTIVE CORP with the given share count. Used for tax-tier
    boundary tests in PRD §3.6 (AUTHORIZED_SHARES method).
    """
    overrides: Dict[str, Any] = {
        "authorized_shares": authorized_shares,
    }
    if total_gross_assets_cents:
        overrides["total_gross_assets_cents"] = total_gross_assets_cents
    if total_issued_shares:
        overrides["total_issued_shares"] = total_issued_shares
    return create_and_activate_entity(
        entity_type="CORP", home_state=home_state, **overrides,
    )


def setup_assessment_in_overdue(authorized_shares: int = 12000,
                                tax_year: Optional[int] = None,
                                days_past_due: int = 5,
                                ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ACTIVE CORP, AUTHORIZED_SHARES tax assessment, then advance the
    clock past due_date so the sweep transitions ASSESSED → OVERDUE.

    PRD §3.6: "sets due_date to March 1 of the year following tax_year
    (so a 2024 tax-year assessment is due March 1, 2025)."
    PRD §3.6: "Once the clock moves past due_date, the assessment
    transitions to OVERDUE (the sweep applies this on any
    clock-advance that crosses the date)."

    Returns (entity, assessment). The assessment is read back after
    the sweep to reflect the OVERDUE status / recomputed late_fee.

    ``tax_year`` defaults to the current server year, which keeps the
    assessment due ~March 1 of the following year and lets the
    days_past_due bump drive the OVERDUE transition deterministically.
    """
    entity, _ = setup_active_corp_with_shares(authorized_shares)
    if tax_year is None:
        # Use the current server year so due_date (March 1 of year+1) is
        # close enough that days_past_due puts us past due but not so
        # far ahead that OVERDUE skips straight to DELINQUENT.
        tax_year = server_now_year()
    assessment = create_tax_assessment(
        entity["id"], tax_year, "AUTHORIZED_SHARES",
    )
    # Drive the clock until the sweep flips the assessment to OVERDUE.
    # Start by advancing to ~just past March 1 of (tax_year + 1).
    refreshed = get_tax_assessment(assessment["id"])
    # First jump to a few days past due_date.
    due_iso = refreshed.get("due_date")
    if due_iso is not None:
        from datetime import datetime, timezone, timedelta
        due_dt = parse_iso(due_iso)
        now_dt = parse_iso(server_now_iso())
        gap_days = (due_dt - now_dt).days + days_past_due
        if gap_days > 0:
            advance_clock_by_days(gap_days)
    else:
        advance_clock_by_days(days_past_due)
    refreshed = get_tax_assessment(assessment["id"])
    months = 0
    while refreshed["status"] == "ASSESSED" and months < 24:
        advance_clock_by_days(30)
        months += 1
        refreshed = get_tax_assessment(assessment["id"])
    return entity, refreshed


def setup_assessment_in_delinquent(authorized_shares: int = 12000,
                                   tax_year: Optional[int] = None,
                                   ) -> Tuple[Dict[str, Any],
                                              Dict[str, Any]]:
    """Take an assessment past due_date + 90 days so the sweep
    transitions OVERDUE → DELINQUENT.
    PRD §3.6: "Once the clock moves past due_date plus 90 days, the
    assessment transitions to DELINQUENT."
    """
    entity, assessment = setup_assessment_in_overdue(
        authorized_shares=authorized_shares, tax_year=tax_year,
    )
    # Advance to >90 days past due_date.
    advance_clock_by_days(TAX_DELINQUENCY_DAYS + 5)
    refreshed = get_tax_assessment(assessment["id"])
    months = 0
    while refreshed["status"] == "OVERDUE" and months < 12:
        advance_clock_by_days(30)
        months += 1
        refreshed = get_tax_assessment(assessment["id"])
    return entity, refreshed


def setup_entity_delinquent_for_60d(authorized_shares: int = 12000,
                                    tax_year: Optional[int] = None,
                                    ) -> Tuple[Dict[str, Any],
                                               Dict[str, Any]]:
    """Take an entity into compliance_status=DELINQUENT and let
    60 days elapse so administrative dissolution is permitted.
    PRD §3.11: "the entity has been in compliance_status DELINQUENT
    for at least sixty days."
    """
    entity, assessment = setup_assessment_in_delinquent(
        authorized_shares=authorized_shares, tax_year=tax_year,
    )
    # Re-read entity to confirm compliance_status posture, then sit
    # past the 60-day wait.
    entity = get_entity(entity["id"], make_filer_headers(entity["id"]))
    advance_clock_by_days(ADMIN_DISSOLUTION_WAIT_DAYS + 5)
    entity = get_entity(entity["id"], make_filer_headers(entity["id"]))
    return entity, assessment


# ---------------------------------------------------------------------------
# BOI staleness fixtures — PRD §3.8
# ---------------------------------------------------------------------------
def setup_entity_with_stale_boi(
    entity: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (entity, owners, ownerships). The entity's
    compliance_status will be NOT_IN_GOOD_STANDING after this fixture
    completes because PRD §3.8 says STALE drives the entity into
    NOT_IN_GOOD_STANDING.
    """
    if entity is None:
        entity, _ = create_and_activate_entity()
    _rep, owners, ownerships = setup_initial_boi_filed(entity["id"])
    # An ownership change is required to start the stale-timer per
    # PRD §3.8: "If a CURRENT BOI report is in place and a BOIOwnership
    # row is added or terminated for the entity, the report becomes
    # vulnerable to going STALE."
    delete_boi_ownership(entity["id"], ownerships[-1]["id"])
    advance_clock_by_days(BOI_STALE_TIMER_DAYS + 1)
    entity = get_entity(entity["id"], make_filer_headers(entity["id"]))
    return entity, owners, ownerships


__all__ = [
    "get_entity",
    "get_tax_assessment",
    "list_compliance_events",
    "create_registered_agent",
    "resign_registered_agent",
    "create_entity_in_pending",
    "form_entity",
    "create_and_activate_entity",
    "credit_deposit",
    "attach_operating_agreement",
    "create_ein_application",
    "submit_ein_application",
    "approve_ein_application",
    "create_submitted_ein",
    "create_approved_ein",
    "create_draft_annual_report",
    "submit_annual_report",
    "accept_annual_report",
    "reject_annual_report",
    "create_submitted_annual_report",
    "create_accepted_annual_report",
    "create_tax_assessment",
    "pay_tax_assessment",
    "refund_tax_assessment",
    "create_pending_foreign_qualification",
    "approve_foreign_qualification",
    "create_qualified_foreign",
    "create_beneficial_owner",
    "add_boi_ownership",
    "delete_boi_ownership",
    "create_boi_report",
    "file_boi_report",
    "setup_owners_full_100",
    "setup_initial_boi_filed",
    "advance_clock_iso",
    "advance_clock_by_days",
    "run_sweep",
    "server_now_iso",
    "server_now_year",
    "setup_active_corp_with_shares",
    "setup_assessment_in_overdue",
    "setup_assessment_in_delinquent",
    "setup_entity_delinquent_for_60d",
    "setup_entity_with_stale_boi",
    "setup_active_entity_eligible_for_annual_report",
]
