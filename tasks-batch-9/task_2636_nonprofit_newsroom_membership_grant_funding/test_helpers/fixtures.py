"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database with the logical
clock reading 2026-08-01T00:00:00Z.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    benefit_payload,
    create_coverage_area_payload,
    create_collaboration_partner_payload,
    create_collaboration_payload,
    create_contribution_payload,
    create_firewall_disclosure_payload,
    create_fiscal_period_payload,
    create_funder_payload,
    create_gift_offer_payload,
    create_grant_proposal_payload,
    create_influence_contact_payload,
    create_member_payload,
    create_membership_tier_payload,
    unique_email,
)
from .test_users import TEST_USERS, USER_IDS, make_member_headers

DO_HEADERS = TEST_USERS["development_officer_headers"]
DO2_HEADERS = TEST_USERS["development_officer_2_headers"]
ED_HEADERS = TEST_USERS["editorial_director_headers"]
ED2_HEADERS = TEST_USERS["editorial_director_2_headers"]
FC_HEADERS = TEST_USERS["finance_controller_headers"]
BO_HEADERS = TEST_USERS["board_oversight_headers"]


# --------------------------------------------------------------------------
# Single-call primitives
# --------------------------------------------------------------------------

def set_clock(current_utc: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    """Move the logical clock forward to current_utc."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, headers or FC_HEADERS)
    )


def run_daily_sweep(headers: Optional[dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.daily_sweep(headers or FC_HEADERS))


def open_fiscal_period(**overrides) -> Dict[str, Any]:
    payload = create_fiscal_period_payload(**overrides)
    return get_success_data(api_client.create_fiscal_period(payload, FC_HEADERS))


def read_fiscal_period(period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_fiscal_period(period_id, FC_HEADERS))


def fiscal_period_action(period_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.fiscal_period_status_action(period_id, {"action": action}, FC_HEADERS)
    )


def record_board_override(period_id: str, justification: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.fiscal_period_board_override(
            period_id, {"justification": justification}, BO_HEADERS
        )
    )


def read_sustainability(period_id: str, basis: Optional[str] = None) -> Dict[str, Any]:
    params = {"basis": basis} if basis else None
    return get_success_data(
        api_client.get_sustainability(period_id, FC_HEADERS, params=params)
    )


def register_coverage_area(**overrides) -> Dict[str, Any]:
    payload = create_coverage_area_payload(**overrides)
    return get_success_data(api_client.create_coverage_area(payload, ED_HEADERS))


def read_coverage_area(area_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_coverage_area(area_id, ED_HEADERS))


def read_transparency_report(area_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_transparency_report(area_id, ED_HEADERS))


def register_funder(headers: Optional[dict] = None, **overrides) -> Dict[str, Any]:
    payload = create_funder_payload(**overrides)
    return get_success_data(api_client.create_funder(payload, headers or DO_HEADERS))


def read_funder(funder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_funder(funder_id, DO_HEADERS))


def rule_on_funder(
    funder_id: str,
    decision: str = "CLEAR",
    basis: str = "SELF_ATTESTED",
    headers: Optional[dict] = None,
    **extra,
) -> Dict[str, Any]:
    payload = {"decision": decision, "basis": basis}
    payload.update(extra)
    return get_success_data(
        api_client.funder_independence_clearance(
            funder_id, payload, headers or ED_HEADERS
        )
    )


def file_disclosure(
    funder_id: str,
    coverage_area_id: str,
    expected_funder_version: Optional[int] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """File a firewall disclosure, reading the funder's current version when the
    caller does not pin one."""
    if expected_funder_version is None:
        expected_funder_version = read_funder(funder_id)["version"]
    payload = create_firewall_disclosure_payload(
        funder_id, coverage_area_id, expected_funder_version, **overrides
    )
    return get_success_data(
        api_client.create_firewall_disclosure(payload, headers or ED_HEADERS)
    )


def attest_disclosure(
    disclosure_id: str, void: Optional[bool] = None, headers: Optional[dict] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {} if void is None else {"void": void}
    return get_success_data(
        api_client.attest_firewall_disclosure(
            disclosure_id, payload, headers or ED_HEADERS
        )
    )


def log_influence_contact(
    funder_id: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = create_influence_contact_payload(funder_id, **overrides)
    return get_success_data(
        api_client.create_influence_contact(payload, headers or DO_HEADERS)
    )


def define_tier(benefits: Optional[List[Dict[str, Any]]] = None, **overrides):
    payload = create_membership_tier_payload(benefits=benefits, **overrides)
    return get_success_data(api_client.create_membership_tier(payload, DO_HEADERS))


def publish_tier(tier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_membership_tier(tier_id, DO_HEADERS))


def create_published_tier(
    benefits: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    """Define a tier and publish it, which is the precondition on enrolment."""
    tier = define_tier(benefits=benefits, **overrides)
    return publish_tier(tier["id"])


def enrol_member(tier_id: str, **overrides) -> Dict[str, Any]:
    payload = create_member_payload(tier_id, **overrides)
    return get_success_data(api_client.create_member(payload, DO_HEADERS))


def read_member(member_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(member_id, DO_HEADERS))


def member_lifecycle(
    member_id: str, action: str, headers: Optional[dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.member_lifecycle_action(
            member_id, {"action": action}, headers or DO_HEADERS
        )
    )


def change_member_tier(
    member_id: str,
    new_tier_id: str,
    expected_member_version: int,
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    payload = {
        "new_tier_id": new_tier_id,
        "expected_member_version": expected_member_version,
    }
    return get_success_data(
        api_client.member_tier_change(member_id, payload, headers or DO_HEADERS)
    )


def record_contribution(
    fiscal_period_id: str,
    revenue_stream: str,
    amount_cents: int,
    headers: Optional[dict] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = create_contribution_payload(
        fiscal_period_id, revenue_stream, amount_cents, **overrides
    )
    return get_success_data(
        api_client.create_contribution(payload, headers or DO_HEADERS)
    )


def read_contribution(contribution_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contribution(contribution_id, DO_HEADERS))


def settle_contribution(contribution_id: str, outcome: str = "SETTLED"):
    return get_success_data(
        api_client.settle_contribution(contribution_id, {"outcome": outcome}, FC_HEADERS)
    )


def refund_contribution(contribution_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.refund_contribution(contribution_id, dict(overrides), FC_HEADERS)
    )


def acknowledge_contribution(
    contribution_id: str, disclose_publicly: bool = False
) -> Dict[str, Any]:
    return get_success_data(
        api_client.acknowledge_contribution(
            contribution_id, {"disclose_publicly": disclose_publicly}, DO_HEADERS
        )
    )


def record_gift_offer(
    funder_id: str, fiscal_period_id: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = create_gift_offer_payload(funder_id, fiscal_period_id, **overrides)
    return get_success_data(
        api_client.create_gift_offer(payload, headers or DO_HEADERS)
    )


def read_gift_offer(offer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_gift_offer(offer_id, DO_HEADERS))


def submit_offer_for_review(
    offer_id: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_gift_offer_for_review(
            offer_id, dict(overrides), headers or DO_HEADERS
        )
    )


def review_gift_offer(
    offer_id: str, decision: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api_client.gift_offer_independence_review(
            offer_id, payload, headers or ED_HEADERS
        )
    )


def ratify_gift_offer(
    offer_id: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.gift_offer_board_ratification(
            offer_id, dict(overrides), headers or BO_HEADERS
        )
    )


def accept_gift_offer(
    offer_id: str, received_date: str, headers: Optional[dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_gift_offer(
            offer_id, {"received_date": received_date}, headers or DO2_HEADERS
        )
    )


def draft_proposal(
    funder_id: str, fiscal_period_id: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = create_grant_proposal_payload(funder_id, fiscal_period_id, **overrides)
    return get_success_data(
        api_client.create_grant_proposal(payload, headers or DO_HEADERS)
    )


def read_proposal(proposal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grant_proposal(proposal_id, DO_HEADERS))


def proposal_pipeline_action(
    proposal_id: str, action: str, headers: Optional[dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.grant_proposal_pipeline_action(
            proposal_id, {"action": action}, headers or DO_HEADERS
        )
    )


def review_proposal(
    proposal_id: str, decision: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api_client.grant_proposal_internal_review(
            proposal_id, payload, headers or ED_HEADERS
        )
    )


def record_proposal_outcome(
    proposal_id: str, outcome: str, headers: Optional[dict] = None, **overrides
) -> Dict[str, Any]:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api_client.grant_proposal_record_outcome(
            proposal_id, payload, headers or DO_HEADERS
        )
    )


def release_funds(proposal_id: str, request_amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.release_restricted_funds(
            proposal_id, {"request_amount_cents": request_amount_cents}, FC_HEADERS
        )
    )


def reinstate_proposal(proposal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reinstate_grant_proposal(proposal_id, FC_HEADERS))


def close_proposal(proposal_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_grant_proposal(proposal_id, dict(overrides), FC_HEADERS)
    )


def list_proposal_reports(proposal_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_grant_proposal_reports(
            proposal_id, FC_HEADERS, params=params or None
        )
    )


def read_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grant_report(report_id, FC_HEADERS))


def submit_report(report_id: str, spend_reported_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_grant_report(
            report_id, {"spend_reported_cents": spend_reported_cents}, DO_HEADERS
        )
    )


def review_report(report_id: str, decision: str, **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api_client.review_grant_report(report_id, payload, FC_HEADERS)
    )


def open_collaboration(
    coverage_area_id: str, fiscal_period_id: str, **overrides
) -> Dict[str, Any]:
    payload = create_collaboration_payload(
        coverage_area_id, fiscal_period_id, **overrides
    )
    return get_success_data(api_client.create_collaboration(payload, ED_HEADERS))


def read_collaboration(collaboration_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_collaboration(collaboration_id, ED_HEADERS))


def add_partner(
    collaboration_id: str,
    partner_org_name: str = "Delta River Report",
    credit_share_bps: int = 4000,
    cost_share_bps: int = 4000,
    **overrides,
) -> Dict[str, Any]:
    payload = create_collaboration_partner_payload(
        partner_org_name, credit_share_bps, cost_share_bps, **overrides
    )
    return get_success_data(
        api_client.create_collaboration_partner(collaboration_id, payload, ED_HEADERS)
    )


def list_partners(collaboration_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_collaboration_partners(
            collaboration_id, ED_HEADERS, params=params or None
        )
    )


def read_partner(partner_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_collaboration_partner(partner_id, ED_HEADERS)
    )


def collaboration_action(collaboration_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.collaboration_status_action(
            collaboration_id, {"action": action}, ED_HEADERS
        )
    )


def withdraw_partner(partner_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_collaboration_partner(
            partner_id, dict(overrides), ED_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Composite setups
# --------------------------------------------------------------------------

def setup_period_and_area(
    area_code: str = "HOUSING", area_name: str = "Housing", **period_overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An OPEN fiscal period plus one registered beat."""
    period = open_fiscal_period(**period_overrides)
    area = register_coverage_area(area_code=area_code, name=area_name)
    return period, area


def setup_cleared_funder(
    legal_name: str = TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
    funder_type: str = "FOUNDATION",
    basis: str = "SELF_ATTESTED",
    audited_advocacy_index: Optional[int] = None,
    affiliated_coverage_area_id: Optional[str] = None,
    self_attested_advocacy: Optional[bool] = None,
) -> Dict[str, Any]:
    """Register a funder and clear it. Only for funders whose recomputed score
    stays below the disclosure floor, so no disclosure is required."""
    overrides: Dict[str, Any] = {"legal_name": legal_name, "funder_type": funder_type}
    if affiliated_coverage_area_id is not None:
        overrides["affiliated_coverage_area_id"] = affiliated_coverage_area_id
    if self_attested_advocacy is not None:
        overrides["self_attested_advocacy"] = self_attested_advocacy
    funder = register_funder(**overrides)
    extra: Dict[str, Any] = {}
    if audited_advocacy_index is not None:
        extra["audited_advocacy_index"] = audited_advocacy_index
    return rule_on_funder(funder["id"], "CLEAR", basis, **extra)


def setup_disclosed_and_cleared_funder(
    coverage_area_id: str,
    legal_name: str = TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
    funder_type: str = "FOUNDATION",
    basis: str = "SELF_ATTESTED",
    audited_advocacy_index: Optional[int] = None,
    affiliated: bool = False,
    self_attested_advocacy: Optional[bool] = None,
    disclosure_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a funder, file an ACTIVE firewall disclosure for the given beat,
    then clear the funder. Returns {"funder": ..., "disclosure": ...}.

    The disclosure is filed before the clearance because a funder whose
    recomputed score reaches the disclosure floor cannot be cleared without one.
    """
    overrides: Dict[str, Any] = {"legal_name": legal_name, "funder_type": funder_type}
    if affiliated:
        overrides["affiliated_coverage_area_id"] = coverage_area_id
    if self_attested_advocacy is not None:
        overrides["self_attested_advocacy"] = self_attested_advocacy
    funder = register_funder(**overrides)
    disclosure_overrides = (
        {"disclosure_text": disclosure_text} if disclosure_text else {}
    )
    disclosure = file_disclosure(
        funder["id"], coverage_area_id, funder["version"], **disclosure_overrides
    )
    extra: Dict[str, Any] = {}
    if audited_advocacy_index is not None:
        extra["audited_advocacy_index"] = audited_advocacy_index
    cleared = rule_on_funder(funder["id"], "CLEAR", basis, **extra)
    return {"funder": cleared, "disclosure": disclosure}


def setup_cleared_proposal(
    funder_id: str,
    fiscal_period_id: str,
    coverage_area_id: Optional[str] = None,
    **proposal_overrides,
) -> Dict[str, Any]:
    """Draft a proposal and walk it to CLEARED through independence review."""
    payload_overrides = dict(proposal_overrides)
    if coverage_area_id is not None:
        payload_overrides.setdefault("coverage_area_id", coverage_area_id)
    proposal = draft_proposal(funder_id, fiscal_period_id, **payload_overrides)
    proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")
    return review_proposal(proposal["id"], "CLEAR")


def setup_submitted_proposal(
    funder_id: str,
    fiscal_period_id: str,
    coverage_area_id: Optional[str] = None,
    **proposal_overrides,
) -> Dict[str, Any]:
    """Walk a proposal all the way to SUBMITTED."""
    cleared = setup_cleared_proposal(
        funder_id, fiscal_period_id, coverage_area_id, **proposal_overrides
    )
    return proposal_pipeline_action(cleared["id"], "SUBMIT")


def setup_awarded_restricted_proposal(
    requested_amount_cents: int = 350000,
    awarded_amount_cents: Optional[int] = None,
    award_date: str = "2026-08-15",
    reporting_cadence: str = "NONE",
    restriction_type: str = "PROGRAM_RESTRICTED",
    restriction_start_date: str = "2026-09-01",
    restriction_end_date: str = "2027-02-28",
    award_probability_bps: int = 6000,
    monthly_expense_base_cents: int = 200000,
    reserve_balance_cents: int = 500000,
    area_code: str = "HOUSING",
    legal_name: str = TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
    title: str = TEST_DEFAULTS["PROPOSAL_TITLE"],
    period: Optional[Dict[str, Any]] = None,
    area: Optional[Dict[str, Any]] = None,
    funder: Optional[Dict[str, Any]] = None,
    disclosure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A restricted grant in AWARDED with its reporting obligations generated.

    Builds the whole chain: fiscal period, beat, cleared funder with an ACTIVE
    disclosure for the pair, proposal drafted, cleared in independence review,
    submitted, and awarded.
    """
    if period is None:
        period = open_fiscal_period(
            monthly_expense_base_cents=monthly_expense_base_cents,
            reserve_balance_cents=reserve_balance_cents,
        )
    if area is None:
        area = register_coverage_area(area_code=area_code, name=area_code.title())
    if funder is None:
        pair = setup_disclosed_and_cleared_funder(
            area["id"], legal_name=legal_name
        )
        funder, disclosure = pair["funder"], pair["disclosure"]
    proposal = setup_submitted_proposal(
        funder["id"],
        period["id"],
        area["id"],
        title=title,
        requested_amount_cents=requested_amount_cents,
        restriction_type=restriction_type,
        restriction_start_date=restriction_start_date,
        restriction_end_date=restriction_end_date,
        reporting_cadence=reporting_cadence,
        award_probability_bps=award_probability_bps,
    )
    awarded = record_proposal_outcome(
        proposal["id"],
        "AWARDED",
        awarded_amount_cents=(
            requested_amount_cents
            if awarded_amount_cents is None
            else awarded_amount_cents
        ),
        award_date=award_date,
    )
    reports = list_proposal_reports(awarded["id"])
    return {
        "period": period,
        "area": area,
        "funder": funder,
        "disclosure": disclosure,
        "proposal": awarded,
        "reports": reports,
    }


def setup_awarded_unrestricted_proposal(
    requested_amount_cents: int = 350000,
    awarded_amount_cents: Optional[int] = None,
    award_date: str = "2026-08-01",
    reporting_cadence: str = "SEMIANNUAL",
    award_probability_bps: int = 5000,
    monthly_expense_base_cents: int = 200000,
    reserve_balance_cents: int = 500000,
    legal_name: str = TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
    title: str = TEST_DEFAULTS["PROPOSAL_TITLE"],
) -> Dict[str, Any]:
    """An UNRESTRICTED grant in AWARDED. No beat and no disclosure are involved."""
    period = open_fiscal_period(
        monthly_expense_base_cents=monthly_expense_base_cents,
        reserve_balance_cents=reserve_balance_cents,
    )
    funder = setup_cleared_funder(legal_name=legal_name)
    proposal = setup_submitted_proposal(
        funder["id"],
        period["id"],
        title=title,
        requested_amount_cents=requested_amount_cents,
        restriction_type="UNRESTRICTED",
        reporting_cadence=reporting_cadence,
        award_probability_bps=award_probability_bps,
    )
    awarded = record_proposal_outcome(
        proposal["id"],
        "AWARDED",
        awarded_amount_cents=(
            requested_amount_cents
            if awarded_amount_cents is None
            else awarded_amount_cents
        ),
        award_date=award_date,
    )
    return {
        "period": period,
        "funder": funder,
        "proposal": awarded,
        "reports": list_proposal_reports(awarded["id"]),
    }


def setup_released_award(
    release_amount_cents: int, reporting_cadence: str = "SEMIANNUAL", **kwargs
) -> Dict[str, Any]:
    """An AWARDED restricted grant with principal already released against its
    report buckets."""
    ctx = setup_awarded_restricted_proposal(reporting_cadence=reporting_cadence, **kwargs)
    ctx["proposal"] = release_funds(ctx["proposal"]["id"], release_amount_cents)
    ctx["reports"] = list_proposal_reports(ctx["proposal"]["id"])
    ctx["period"] = read_fiscal_period(ctx["period"]["id"])
    return ctx


def setup_delinquent_award(
    release_amount_cents: int = 210000,
    sweep_clock: str = "2027-04-15T00:00:00Z",
    reporting_cadence: str = "SEMIANNUAL",
    **kwargs,
) -> Dict[str, Any]:
    """A restricted grant whose first report has gone OVERDUE, suspending the
    proposal and clawing the released principal back out of the reserve."""
    ctx = setup_released_award(
        release_amount_cents, reporting_cadence=reporting_cadence, **kwargs
    )
    set_clock(sweep_clock)
    ctx["sweep"] = run_daily_sweep()
    ctx["proposal"] = read_proposal(ctx["proposal"]["id"])
    ctx["reports"] = list_proposal_reports(ctx["proposal"]["id"])
    ctx["period"] = read_fiscal_period(ctx["period"]["id"])
    ctx["funder"] = read_funder(ctx["funder"]["id"])
    return ctx


def setup_pending_member(
    tier_benefits: Optional[List[Dict[str, Any]]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An OPEN period, a PUBLISHED tier and one member enrolled on it, still
    PENDING because no contribution has settled yet."""
    period = open_fiscal_period(**(period_overrides or {}))
    tier = create_published_tier(benefits=tier_benefits, **(tier_overrides or {}))
    member = enrol_member(tier["id"], **(member_overrides or {}))
    return {"period": period, "tier": tier, "member": member}


def setup_active_member(
    amount_cents: Optional[int] = None,
    received_date: str = "2026-08-01",
    tier_benefits: Optional[List[Dict[str, Any]]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A member activated by the settlement of their first membership
    contribution, which is the only way PENDING becomes ACTIVE."""
    ctx = setup_pending_member(
        tier_benefits=tier_benefits,
        tier_overrides=tier_overrides,
        period_overrides=period_overrides,
        member_overrides=member_overrides,
    )
    amount = (
        ctx["tier"]["contribution_amount_cents"] if amount_cents is None else amount_cents
    )
    contribution = record_contribution(
        ctx["period"]["id"],
        "MEMBERSHIP",
        amount,
        member_id=ctx["member"]["id"],
        received_date=received_date,
    )
    ctx["contribution"] = settle_contribution(contribution["id"])
    ctx["member"] = read_member(ctx["member"]["id"])
    return ctx


def setup_gift_offer_in_review(
    offered_amount_cents: int = 200000,
    designation: str = "UNRESTRICTED",
    coverage_area_id: Optional[str] = None,
    period: Optional[Dict[str, Any]] = None,
    funder: Optional[Dict[str, Any]] = None,
    donor_conditions: Optional[str] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A gift offer sitting in INDEPENDENCE_REVIEW with its netting computed."""
    if period is None:
        period = open_fiscal_period(**(period_overrides or {}))
    if funder is None:
        funder = setup_cleared_funder()
    offer_overrides: Dict[str, Any] = {
        "offered_amount_cents": offered_amount_cents,
        "designation": designation,
    }
    if coverage_area_id is not None:
        offer_overrides["coverage_area_id"] = coverage_area_id
    if donor_conditions is not None:
        offer_overrides["donor_conditions"] = donor_conditions
    offer = record_gift_offer(funder["id"], period["id"], **offer_overrides)
    offer = submit_offer_for_review(offer["id"])
    return {"period": period, "funder": funder, "offer": offer}


def setup_cleared_gift_offer(**kwargs) -> Dict[str, Any]:
    """A gift offer cleared in independence review by a director who is not the
    soliciting officer."""
    ctx = setup_gift_offer_in_review(**kwargs)
    ctx["offer"] = review_gift_offer(ctx["offer"]["id"], "CLEAR")
    return ctx


def setup_collaboration(
    partners: Optional[List[Dict[str, Any]]] = None,
    activate: bool = False,
    period: Optional[Dict[str, Any]] = None,
    area: Optional[Dict[str, Any]] = None,
    area_code: str = "CLIMATE",
    period_overrides: Optional[Dict[str, Any]] = None,
    **collaboration_overrides,
) -> Dict[str, Any]:
    """A collaboration on a beat with the given partner newsrooms enrolled, and
    optionally activated so that the cost split has run."""
    if period is None:
        period = open_fiscal_period(**(period_overrides or {}))
    if area is None:
        area = register_coverage_area(area_code=area_code, name=area_code.title())
    collaboration = open_collaboration(
        area["id"], period["id"], **collaboration_overrides
    )
    created: List[Dict[str, Any]] = []
    for spec in partners or []:
        created.append(add_partner(collaboration["id"], **spec))
    if activate:
        collaboration = collaboration_action(collaboration["id"], "ACTIVATE")
    else:
        collaboration = read_collaboration(collaboration["id"])
    return {
        "period": period,
        "area": area,
        "collaboration": collaboration,
        "partners": list_partners(collaboration["id"]) if created else [],
    }


def setup_blocked_beat(
    area_code: str = "HOUSING",
    period: Optional[Dict[str, Any]] = None,
    legal_name: str = TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
) -> Dict[str, Any]:
    """A beat whose publication gate is BLOCKED because the only disclosure
    touching it was driven into REATTESTATION_REQUIRED by a funder restriction."""
    if period is None:
        period = open_fiscal_period()
    area = register_coverage_area(area_code=area_code, name=area_code.title())
    pair = setup_disclosed_and_cleared_funder(area["id"], legal_name=legal_name)
    funder = rule_on_funder(pair["funder"]["id"], "RESTRICT", "SELF_ATTESTED")
    return {
        "period": period,
        "area": read_coverage_area(area["id"]),
        "funder": funder,
        "disclosure": get_success_data(
            api_client.get_firewall_disclosure(pair["disclosure"]["id"], ED_HEADERS)
        ),
    }


def three_benefit_monthly_tier_benefits() -> List[Dict[str, Any]]:
    """Three benefits worth 1000 cents a year each, the case where rounding each
    benefit before summing gives 249 rather than 250."""
    return [
        benefit_payload("STICKER", "MERCH_DISCOUNT", 1000),
        benefit_payload("PIN", "MERCH_DISCOUNT", 1000),
        benefit_payload("CARD", "MERCH_DISCOUNT", 1000),
    ]
