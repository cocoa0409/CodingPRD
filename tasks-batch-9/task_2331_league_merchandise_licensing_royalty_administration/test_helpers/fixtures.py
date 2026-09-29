"""Composite setup helpers.

Every helper builds its preconditions from scratch through the endpoints the PRD
declares — there is no back door into storage — and returns the parsed resource so a
test can read ids and versions from it. Helpers that act for a Licensee, a
ClubRepresentative or a PlayerAgent always thread the real resource id into the
identity headers, because those three roles are confined to their own record.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_INSTANT
from .factories import (
    activate_licensee_payload,
    advance_payment_payload,
    agreement_payload,
    audit_engagement_payload,
    authorization_status_payload,
    channel_line,
    clock_payload,
    club_mark_payload,
    club_payload,
    contract_status_payload,
    distribution_run_payload,
    dispute_payload,
    enforcement_action_payload,
    enforcement_status_payload,
    group_licensing_payload,
    individual_grant_payload,
    issue_findings_payload,
    jersey_category_payload,
    league_mark_payload,
    licensee_payload,
    licensee_status_payload,
    mark_status_payload,
    player_group_mark_payload,
    player_individual_mark_payload,
    player_payload,
    product_submission_payload,
    quarter_close_payload,
    report_review_decision_payload,
    retailer_authorization_payload,
    royalty_report_payload,
    run_version_payload,
    sample_review_payload,
    settle_payload,
    submission_review_decision_payload,
    territory_grant_payload,
)
from .test_users import (
    FIN_USER_ID,
    TEST_USERS,
    make_club_representative_headers,
    make_licensee_headers,
    make_player_agent_headers,
)

OPS = TEST_USERS["league_licensing_manager_headers"]
MCO = TEST_USERS["mark_compliance_officer_headers"]
FIN = TEST_USERS["finance_controller_headers"]
FIN_ALT = TEST_USERS["finance_controller_alt_headers"]
AUD = TEST_USERS["royalty_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — clock and reference data
# ---------------------------------------------------------------------------


def set_clock(instant: str = DEFAULT_CLOCK_INSTANT, headers: Optional[dict] = None) -> dict:
    """Pin the logical clock. Any role may set it."""
    return get_success_data(api_client.set_clock(clock_payload(instant), headers or OPS))


def create_category(payload: Dict[str, Any]) -> dict:
    return get_success_data(api_client.create_product_category(payload, OPS))


def create_jersey_category(**overrides) -> dict:
    """The tiered jersey category used by most money paths."""
    return create_category(jersey_category_payload(**overrides))


def create_club(**overrides) -> dict:
    return get_success_data(api_client.create_club(club_payload(**overrides), OPS))


def create_clubs(specs: List[Dict[str, Any]]) -> List[dict]:
    """Create several clubs in the given order."""
    return [create_club(**spec) for spec in specs]


def create_player(club_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_player(club_id, player_payload(**overrides), OPS))


def set_group_licensing(player_id: str, opt_in: bool, headers: Optional[dict] = None) -> dict:
    """Flip a player's group-licensing flag. The PlayerAgent acts for its own player."""
    return get_success_data(
        api_client.set_group_licensing(
            player_id,
            group_licensing_payload(opt_in),
            headers or make_player_agent_headers(player_id),
        )
    )


def grant_individual_category(
    player_id: str, category_id: str, granted: bool = True, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.set_individual_grant(
            player_id,
            individual_grant_payload(category_id, granted),
            headers or make_player_agent_headers(player_id),
        )
    )


def create_league_mark(**overrides) -> dict:
    return get_success_data(api_client.create_mark_right(league_mark_payload(**overrides), OPS))


def create_club_mark(club_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mark_right(club_mark_payload(club_id, **overrides), OPS)
    )


def create_player_group_mark(player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mark_right(player_group_mark_payload(player_id, **overrides), OPS)
    )


def create_player_individual_mark(player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mark_right(player_individual_mark_payload(player_id, **overrides), OPS)
    )


def set_mark_status(
    mark_id: str, action: str, reason: Optional[str] = None, headers: Optional[dict] = None
) -> dict:
    payload = mark_status_payload(action)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.set_mark_right_status(mark_id, payload, headers or MCO))


def get_mark(mark_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_mark_right(mark_id, headers or OPS))


def get_player(player_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_player(player_id, headers or OPS))


def set_club_mark_status_as_club(
    mark_id: str, club_id: str, action: str, reason: Optional[str] = None
) -> dict:
    """A ClubRepresentative operating the lever on its own club-owned mark."""
    return set_mark_status(mark_id, action, reason, make_club_representative_headers(club_id))


# ---------------------------------------------------------------------------
# Tier 1 — licensee state progression
# ---------------------------------------------------------------------------


def create_prospect_licensee(**overrides) -> dict:
    return get_success_data(api_client.create_licensee(licensee_payload(**overrides), OPS))


def activate_licensee(licensee_id: str, vendor_compliance_certified: bool = True) -> dict:
    return get_success_data(
        api_client.set_licensee_status(
            licensee_id, activate_licensee_payload(vendor_compliance_certified), OPS
        )
    )


def create_active_licensee(vendor_compliance_certified: bool = True, **overrides) -> dict:
    """A licensee walked from PROSPECT to ACTIVE; the returned record is post-activation."""
    licensee = create_prospect_licensee(**overrides)
    return activate_licensee(licensee["id"], vendor_compliance_certified)


def suspend_licensee(licensee_id: str, reason: str = "Unresolved mark misuse notice") -> dict:
    """Suspension is a compliance action taken by a MarkComplianceOfficer."""
    return get_success_data(
        api_client.set_licensee_status(
            licensee_id, licensee_status_payload("SUSPEND", reason=reason), MCO
        )
    )


def reinstate_licensee(licensee_id: str) -> dict:
    return get_success_data(
        api_client.set_licensee_status(licensee_id, licensee_status_payload("REINSTATE"), OPS)
    )


def terminate_licensee(licensee_id: str, reason: str = "Licence programme wound down") -> dict:
    return get_success_data(
        api_client.set_licensee_status(
            licensee_id, licensee_status_payload("TERMINATE", reason=reason), OPS
        )
    )


def get_licensee(licensee_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_licensee(licensee_id, headers or OPS))


def licensee_version(licensee_id: str) -> int:
    return get_licensee(licensee_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2 — agreement hierarchy
# ---------------------------------------------------------------------------


def create_draft_agreement(licensee_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_agreement(agreement_payload(licensee_id, category_id, **overrides), OPS)
    )


def pay_advance(agreement_id: str, amount_cents: int, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_advance_payment(
            agreement_id, advance_payment_payload(amount_cents), headers or FIN
        )
    )


def grant_territory(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_territory_grant(agreement_id, territory_grant_payload(**overrides), OPS)
    )


def set_territory_grant_status(
    grant_id: str, action: str, reason: Optional[str] = None
) -> dict:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.set_territory_grant_status(grant_id, payload, OPS))


def submit_agreement_for_signature(agreement_id: str) -> dict:
    return get_success_data(
        api_client.set_contract_status(
            agreement_id, contract_status_payload("SUBMIT_FOR_SIGNATURE"), OPS
        )
    )


def activate_agreement(agreement_id: str, countersigned_by: str = "R. Vance") -> dict:
    return get_success_data(
        api_client.set_contract_status(
            agreement_id,
            contract_status_payload("ACTIVATE", countersigned_by=countersigned_by),
            OPS,
        )
    )


def suspend_agreement(agreement_id: str, reason: str = "Mark misuse under review") -> dict:
    """Contract suspension is performed by a MarkComplianceOfficer."""
    return get_success_data(
        api_client.set_contract_status(
            agreement_id, contract_status_payload("SUSPEND", reason=reason), MCO
        )
    )


def reinstate_agreement(agreement_id: str) -> dict:
    return get_success_data(
        api_client.set_contract_status(agreement_id, contract_status_payload("REINSTATE"), OPS)
    )


def terminate_agreement(
    agreement_id: str, reason: str = "Counterfeit consent order", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.set_contract_status(
            agreement_id, contract_status_payload("TERMINATE", reason=reason), headers or OPS
        )
    )


def get_agreement(agreement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, headers or OPS))


def agreement_version(agreement_id: str) -> int:
    return get_agreement(agreement_id)["version"]


def setup_active_agreement(
    minimum_guarantee_cents: int = 1000000,
    required_advance_cents: int = 250000,
    advance_paid_cents: Optional[int] = None,
    category: Optional[dict] = None,
    licensee: Optional[dict] = None,
    territory: Optional[Dict[str, Any]] = None,
    **agreement_overrides,
) -> Dict[str, Any]:
    """Walk one agreement all the way to ACTIVE.

    Activation needs the whole drafting chain: the minimum guarantee at or above the
    category floor, the contracted advance fully paid, at least one GRANTED territory
    grant, and an ACTIVE licensee to countersign against.
    """
    category = category or create_jersey_category()
    licensee = licensee or create_active_licensee()
    agreement = create_draft_agreement(
        licensee["id"],
        category["id"],
        minimum_guarantee_cents=minimum_guarantee_cents,
        required_advance_cents=required_advance_cents,
        **agreement_overrides,
    )
    paid = required_advance_cents if advance_paid_cents is None else advance_paid_cents
    if paid:
        pay_advance(agreement["id"], paid)
    grant = grant_territory(agreement["id"], **(territory or {}))
    submit_agreement_for_signature(agreement["id"])
    agreement = activate_agreement(agreement["id"])
    return {
        "category": category,
        "licensee": licensee,
        "agreement": agreement,
        "territory_grant": grant,
    }


# ---------------------------------------------------------------------------
# Tier 2 — retailer authorizations
# ---------------------------------------------------------------------------


def create_retailer_authorization(
    licensee_id: str, expected_licensee_version: Optional[int] = None, **overrides
) -> dict:
    """Create a PENDING authorization, reading the licensee version immediately first."""
    version = (
        licensee_version(licensee_id)
        if expected_licensee_version is None
        else expected_licensee_version
    )
    return get_success_data(
        api_client.create_retailer_authorization(
            licensee_id, retailer_authorization_payload(version, **overrides), OPS
        )
    )


def set_authorization_status(
    authorization_id: str,
    action: str,
    reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = authorization_status_payload(action)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.set_retailer_authorization_status(
            authorization_id, payload, headers or OPS
        )
    )


def create_authorized_retailer_authorization(licensee_id: str, **overrides) -> dict:
    """Create the authorization and walk it from PENDING to AUTHORIZED."""
    authorization = create_retailer_authorization(licensee_id, **overrides)
    return set_authorization_status(authorization["id"], "APPROVE")


def get_authorization(authorization_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_retailer_authorization(authorization_id, headers or OPS)
    )


# ---------------------------------------------------------------------------
# Tier 3 — a fully licensed operation ready to report royalties
# ---------------------------------------------------------------------------


def setup_licensed_operation(
    closeout_allowed: bool = False,
    channel_class: str = "DEPARTMENT",
    sku_classes: Optional[List[str]] = None,
    retailer_name: str = "Metro Sports",
    **active_agreement_kwargs,
) -> Dict[str, Any]:
    """An ACTIVE agreement plus an AUTHORIZED retail account it can report through."""
    context = setup_active_agreement(**active_agreement_kwargs)
    authorization = create_authorized_retailer_authorization(
        context["licensee"]["id"],
        retailer_name=retailer_name,
        channel_class=channel_class,
        sku_classes=sku_classes,
        closeout_allowed=closeout_allowed,
    )
    context["authorization"] = authorization
    return context


# ---------------------------------------------------------------------------
# Tier 3 — royalty reports
# ---------------------------------------------------------------------------


def create_report(
    agreement_id: str,
    period_quarter: str,
    channel_lines: List[Dict[str, Any]],
    licensee_id: Optional[str] = None,
    expected_agreement_version: Optional[int] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Open a DRAFT report, reading the agreement version immediately first."""
    version = (
        agreement_version(agreement_id)
        if expected_agreement_version is None
        else expected_agreement_version
    )
    if headers is None:
        headers = make_licensee_headers(licensee_id) if licensee_id else FIN
    return get_success_data(
        api_client.create_royalty_report(
            royalty_report_payload(agreement_id, period_quarter, channel_lines, version), headers
        )
    )


def simple_report_lines(
    authorization_id: str,
    gross_sales_cents: int,
    units: int = 1000,
    channel_class: str = "DEPARTMENT",
    closeout_sales_cents: int = 0,
    deductions_cents: int = 0,
) -> List[Dict[str, Any]]:
    """One channel line against one authorized retail account."""
    return [
        channel_line(
            authorization_id,
            gross_sales_cents,
            units=units,
            channel_class=channel_class,
            closeout_sales_cents=closeout_sales_cents,
            deductions_cents=deductions_cents,
        )
    ]


def file_report(report_id: str, licensee_id: str) -> dict:
    """Filing is the licensee's act."""
    return get_success_data(
        api_client.file_royalty_report(report_id, None, make_licensee_headers(licensee_id))
    )


def accept_report(report_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_report_review_decision(
            report_id, report_review_decision_payload("ACCEPT"), headers or FIN
        )
    )


def return_report(
    report_id: str, reason: str = "Channel mix needs restating", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.create_report_review_decision(
            report_id,
            report_review_decision_payload("RETURN", reason=reason),
            headers or FIN,
        )
    )


def get_report(report_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_royalty_report(report_id, headers or OPS))


def setup_filed_report(
    period_quarter: str = "2026Q2",
    gross_sales_cents: int = 1000000,
    units: int = 1000,
    channel_class: str = "DEPARTMENT",
    closeout_sales_cents: int = 0,
    deductions_cents: int = 0,
    context: Optional[Dict[str, Any]] = None,
    **operation_kwargs,
) -> Dict[str, Any]:
    """A licensed operation with one report walked to FILED."""
    context = context or setup_licensed_operation(**operation_kwargs)
    lines = simple_report_lines(
        context["authorization"]["id"],
        gross_sales_cents,
        units=units,
        channel_class=channel_class,
        closeout_sales_cents=closeout_sales_cents,
        deductions_cents=deductions_cents,
    )
    report = create_report(
        context["agreement"]["id"], period_quarter, lines, context["licensee"]["id"]
    )
    context["report"] = file_report(report["id"], context["licensee"]["id"])
    return context


def setup_accepted_report(
    period_quarter: str = "2026Q2",
    accept_headers: Optional[dict] = None,
    **filed_kwargs,
) -> Dict[str, Any]:
    """A report walked all the way to ACCEPTED, so its ledger posting has landed."""
    context = setup_filed_report(period_quarter=period_quarter, **filed_kwargs)
    context["report"] = accept_report(context["report"]["id"], accept_headers)
    context["agreement"] = get_agreement(context["agreement"]["id"])
    return context


# ---------------------------------------------------------------------------
# Tier 3 — product submissions
# ---------------------------------------------------------------------------


def create_submission(
    agreement_id: str, licensee_id: str, mark_ids: List[str], **overrides
) -> dict:
    return get_success_data(
        api_client.create_product_submission(
            agreement_id,
            product_submission_payload(mark_ids, **overrides),
            make_licensee_headers(licensee_id),
        )
    )


def revise_submission(submission_id: str, licensee_id: str, **fields) -> dict:
    return get_success_data(
        api_client.patch_product_submission(
            submission_id, dict(fields), make_licensee_headers(licensee_id)
        )
    )


def submit_submission(submission_id: str, licensee_id: str) -> dict:
    return get_success_data(
        api_client.submit_product_submission(
            submission_id, None, make_licensee_headers(licensee_id)
        )
    )


def submission_decision(submission_id: str, decision: str, headers: Optional[dict] = None, **extra) -> dict:
    payload = submission_review_decision_payload(decision, **extra)
    return get_success_data(
        api_client.create_submission_review_decision(submission_id, payload, headers or OPS)
    )


def record_sample_review(
    submission_id: str,
    verdict: str,
    defect_codes: Optional[List[str]] = None,
    note: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = sample_review_payload(verdict, defect_codes)
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_sample_review(submission_id, payload, headers or MCO)
    )


def get_submission(submission_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_product_submission(submission_id, headers or OPS))


def setup_submission_in_review(
    mark_ids: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    sample_required: bool = False,
    **submission_overrides,
) -> Dict[str, Any]:
    """A submission on an ACTIVE agreement walked to IN_REVIEW."""
    context = context or setup_active_agreement()
    if mark_ids is None:
        mark = create_league_mark()
        context["league_mark"] = mark
        mark_ids = [mark["id"]]
    submission = create_submission(
        context["agreement"]["id"],
        context["licensee"]["id"],
        mark_ids,
        sample_required=sample_required,
        **submission_overrides,
    )
    submit_submission(submission["id"], context["licensee"]["id"])
    context["submission"] = submission_decision(submission["id"], "BEGIN_REVIEW")
    return context


def setup_approved_submission(
    mark_ids: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    **submission_overrides,
) -> Dict[str, Any]:
    """A submission walked to APPROVED, so the agreement carries one approved SKU."""
    context = setup_submission_in_review(
        mark_ids=mark_ids, context=context, sample_required=False, **submission_overrides
    )
    context["submission"] = submission_decision(context["submission"]["id"], "APPROVE")
    context["agreement"] = get_agreement(context["agreement"]["id"])
    return context


def setup_submission_awaiting_sample(
    mark_ids: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    **submission_overrides,
) -> Dict[str, Any]:
    """A submission walked to SAMPLE_REQUESTED, ready for a physical inspection."""
    context = setup_submission_in_review(
        mark_ids=mark_ids, context=context, sample_required=True, **submission_overrides
    )
    context["submission"] = submission_decision(context["submission"]["id"], "REQUEST_SAMPLE")
    return context


# ---------------------------------------------------------------------------
# Tier 4 — risk factors and threshold targeting
# ---------------------------------------------------------------------------


def create_enforcement_action(**overrides) -> dict:
    return get_success_data(
        api_client.create_enforcement_action(enforcement_action_payload(**overrides), MCO)
    )


def advance_enforcement(action_id: str, action: str, **extra) -> dict:
    return get_success_data(
        api_client.set_enforcement_action_status(
            action_id, enforcement_status_payload(action, **extra), MCO
        )
    )


def order_seizure(
    action_id: str, seized_units: int = 100, seizure_authority: str = "US Marshals"
) -> dict:
    return advance_enforcement(
        action_id,
        "ORDER_SEIZURE",
        seized_units=seized_units,
        seizure_authority=seizure_authority,
    )


def create_seizure_factor(
    licensee_id: str,
    venue_reference: str = "marketplace-listing-4102",
    target_name: str = "BargainShield",
    seized_units: int = 100,
    estimated_units: int = 120,
) -> dict:
    """One counterfeit seizure dated at the clock's quarter, naming this licensee.

    A seizure factor is worth 15 points to the rolling compliance risk index.
    """
    action = create_enforcement_action(
        venue_reference=venue_reference,
        target_name=target_name,
        estimated_units=estimated_units,
        suspected_licensee_id=licensee_id,
    )
    advance_enforcement(action["id"], "INVESTIGATE")
    return order_seizure(action["id"], seized_units=seized_units)


def create_seizure_factors(licensee_id: str, count: int) -> List[dict]:
    """Stack several seizure factors to drive the stored index into a chosen band."""
    return [
        create_seizure_factor(
            licensee_id,
            venue_reference=f"marketplace-listing-{4100 + index}",
            target_name=f"BargainShield {index + 1}",
        )
        for index in range(count)
    ]


def get_risk_index(
    licensee_id: str, params: Optional[Dict[str, Any]] = None, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.get_licensee_risk_index(licensee_id, headers or OPS, params)
    )


# ---------------------------------------------------------------------------
# Tier 4 — audit engagements
# ---------------------------------------------------------------------------


def create_audit_engagement(
    agreement_id: str, scope_quarters: List[str], headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.create_audit_engagement(
            audit_engagement_payload(agreement_id, scope_quarters), headers or AUD
        )
    )


def begin_fieldwork(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.begin_fieldwork(engagement_id, None, headers or AUD))


def issue_findings(
    engagement_id: str, audited_quarters: List[Dict[str, Any]], headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.issue_findings(
            engagement_id, issue_findings_payload(audited_quarters), headers or AUD
        )
    )


def dispute_engagement(engagement_id: str, licensee_id: str, **overrides) -> dict:
    """Only the owning licensee disputes issued findings."""
    return get_success_data(
        api_client.dispute_engagement(
            engagement_id, dispute_payload(**overrides), make_licensee_headers(licensee_id)
        )
    )


def settle_engagement(
    engagement_id: str,
    settlement_basis: str = "FINDINGS",
    negotiated_cents: Optional[int] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Settlement is the controller's act, and must not be the findings issuer."""
    return get_success_data(
        api_client.settle_engagement(
            engagement_id,
            settle_payload(settlement_basis, negotiated_cents),
            headers or FIN_ALT,
        )
    )


def close_engagement(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.close_engagement(engagement_id, None, headers or AUD))


def get_engagement(engagement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_audit_engagement(engagement_id, headers or AUD))


def setup_engagement_with_findings(
    audited_quarters: List[Dict[str, Any]],
    scope_quarters: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    accept_headers: Optional[dict] = None,
    **accepted_report_kwargs,
) -> Dict[str, Any]:
    """An accepted report pulled into audit with a findings block already issued."""
    if context is None:
        period = (scope_quarters or ["2026Q2"])[0]
        context = setup_accepted_report(
            period_quarter=period, accept_headers=accept_headers, **accepted_report_kwargs
        )
    scope = scope_quarters or [context["report"]["period_quarter"]]
    engagement = create_audit_engagement(context["agreement"]["id"], scope)
    begin_fieldwork(engagement["id"])
    context["engagement"] = issue_findings(engagement["id"], audited_quarters)
    return context


# ---------------------------------------------------------------------------
# Tier 5 — quarter close and central distribution
# ---------------------------------------------------------------------------


def quarter_close(as_of_quarter: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.quarter_close(quarter_close_payload(as_of_quarter), headers or OPS)
    )


def create_distribution_run(
    period_quarter: str, league_admin_rate_bps: int = 800, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.create_distribution_run(
            distribution_run_payload(period_quarter, league_admin_rate_bps), headers or FIN
        )
    )


def get_run(run_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_distribution_run(run_id, headers or FIN))


def run_version(run_id: str) -> int:
    return get_run(run_id)["version"]


def lock_run(
    run_id: str, expected_run_version: Optional[int] = None, headers: Optional[dict] = None
) -> dict:
    version = run_version(run_id) if expected_run_version is None else expected_run_version
    return get_success_data(
        api_client.lock_distribution_run(run_id, run_version_payload(version), headers or FIN)
    )


def unlock_run(run_id: str, headers: Optional[dict] = None) -> dict:
    """Unlocking carries no version field of its own."""
    return get_success_data(api_client.unlock_distribution_run(run_id, None, headers or FIN))


def distribute_run(
    run_id: str, expected_run_version: Optional[int] = None, headers: Optional[dict] = None
) -> dict:
    version = run_version(run_id) if expected_run_version is None else expected_run_version
    return get_success_data(
        api_client.distribute_run(run_id, run_version_payload(version), headers or FIN)
    )


def list_club_distributions(
    params: Optional[Dict[str, Any]] = None, headers: Optional[dict] = None
):
    return api_client.list_club_distributions(headers or FIN, params)


def setup_locked_run(
    period_quarter: str = "2026Q2", league_admin_rate_bps: int = 800, **overrides
) -> dict:
    run = create_distribution_run(period_quarter, league_admin_rate_bps, **overrides)
    return lock_run(run["id"])


__all__ = [name for name in dir() if not name.startswith("_")]
