"""Composite setup helpers.

The harness restarts the API before every test, so every helper here builds its
preconditions from scratch using only the endpoints the PRD declares.  The
logical clock reads exactly ``2026-08-01T00:00:00Z`` until an operator sets it,
which is the instant every default in this module is anchored to.

Naming follows the PRD's vocabulary: a file is opened on an *insured*, scored as
a *submission*, offered as a *quote*, negotiated *term* by *term*, bound into a
*policy* with its *coverage parts*, placed into a *tower* of *layers*, and then
worked as a *claim* with *defense invoices* and *settlement proposals*.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import find_part, find_term
from .factories import (
    allocate_invoice_payload,
    cancel_policy_payload,
    coverage_decision_payload,
    create_circumstance_report_payload,
    create_claim_payload,
    create_defense_invoice_payload,
    create_disclosure_package_payload,
    create_exclusion_term_payload,
    create_insured_payload,
    create_layer_payload,
    create_litigation_event_payload,
    create_quote_payload,
    create_runoff_endorsement_payload,
    create_settlement_proposal_payload,
    create_submission_payload,
    mature_circumstance_report_payload,
    premium_payment_payload,
    resolve_claim_payload,
    resolve_exclusion_term_payload,
    respond_settlement_proposal_payload,
    score_submission_payload,
    update_insured_payload,
)
from .test_users import (
    FIRST_ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    TEST_USERS,
    make_claims_adjuster_headers,
    make_compliance_officer_headers,
    make_risk_manager_headers,
    make_underwriter_headers,
)

UNDERWRITER = TEST_USERS["underwriter_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
SECOND_ADJUSTER = TEST_USERS["second_claims_adjuster_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_NOTICE_CLOCK = "2026-09-02T00:00:00Z"


def _as_list(value, default):
    if value is None:
        return [dict(d) for d in default]
    if isinstance(value, dict):
        return [value]
    return list(value)


# ─── Clock and epoch ─────────────────────────────────────────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Setting it records a new time but changes no record."""
    return get_success_data(api_client.set_clock(to_iso8601, COMPLIANCE))


def advance_epoch() -> dict:
    """Advance the system epoch, applying every time-driven transition in one pass."""
    return get_success_data(api_client.advance_epoch(COMPLIANCE))


# ─── Reads ───────────────────────────────────────────────────────────────────


def read_insured(insured_id: str) -> dict:
    return get_success_data(api_client.get_insured(insured_id, UNDERWRITER))


def read_submission(submission_id: str) -> dict:
    return get_success_data(api_client.get_submission(submission_id, UNDERWRITER))


def read_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, UNDERWRITER))


def read_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, UNDERWRITER))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, UNDERWRITER))


def read_layer(layer_id: str) -> dict:
    return get_success_data(api_client.get_layer(layer_id, UNDERWRITER))


def read_coverage_parts(policy_id: str) -> list:
    return get_success_data(api_client.list_coverage_parts(policy_id, UNDERWRITER))


def read_exclusion_terms(quote_id: str) -> list:
    return get_success_data(api_client.list_exclusion_terms(quote_id, UNDERWRITER))


def read_defense_invoices(claim_id: str) -> list:
    return get_success_data(api_client.list_defense_invoices(claim_id, UNDERWRITER))


def read_settlement_proposals(claim_id: str) -> list:
    return get_success_data(api_client.list_settlement_proposals(claim_id, UNDERWRITER))


def read_layers(policy_id: str) -> list:
    return get_success_data(
        api_client.list_layers(UNDERWRITER, params={"policy_id": policy_id, "limit": 100})
    )


def read_runoff_endorsements(policy_id: str) -> list:
    return get_success_data(api_client.list_runoff_endorsements(policy_id, UNDERWRITER))


def read_circumstance_reports(policy_id: str) -> list:
    return get_success_data(api_client.list_circumstance_reports(policy_id, UNDERWRITER))


# ─── Tier 1: single-step creations ───────────────────────────────────────────


def register_insured(**overrides) -> dict:
    """Register a prospective insured organisation."""
    return get_success_data(
        api_client.create_insured(create_insured_payload(**overrides), UNDERWRITER)
    )


def revise_insured(insured_id: str, expected_insured_version: int, **overrides) -> dict:
    """Revise an insured's control posture, market capitalisation or capacity cap."""
    return get_success_data(
        api_client.update_insured(
            insured_id,
            update_insured_payload(expected_insured_version, **overrides),
            COMPLIANCE,
        )
    )


def file_disclosure_package(insured_id: str, **overrides) -> dict:
    """File a fiscal-year financial and governance disclosure package."""
    return get_success_data(
        api_client.create_disclosure_package(
            insured_id, create_disclosure_package_payload(insured_id, **overrides),
            UNDERWRITER,
        )
    )


def file_litigation_event(insured_id: str, **overrides) -> dict:
    """Record a historical or pending litigation matter."""
    return get_success_data(
        api_client.create_litigation_event(
            insured_id, create_litigation_event_payload(insured_id, **overrides),
            UNDERWRITER,
        )
    )


def open_submission(insured_id: str, **overrides) -> dict:
    """Open a submission for management liability cover."""
    return get_success_data(
        api_client.create_submission(
            create_submission_payload(insured_id, **overrides), UNDERWRITER
        )
    )


def run_scoring(submission_id: str, variant: str = "INDICATIVE") -> dict:
    """Run the risk assessment on a submission under the requested variant."""
    return get_success_data(
        api_client.score_submission(
            submission_id, score_submission_payload(variant), UNDERWRITER
        )
    )


def issue_quote(submission_id: str, expected_submission_version: int = None,
                **overrides) -> dict:
    """Issue a quote on a scored submission under its current version token."""
    if expected_submission_version is None:
        expected_submission_version = read_submission(submission_id)["version"]
    return get_success_data(
        api_client.create_quote(
            submission_id,
            create_quote_payload(expected_submission_version, **overrides),
            UNDERWRITER,
        )
    )


def open_exclusion_term(quote_id: str, **overrides) -> dict:
    """Open negotiation on an additional exclusion wording."""
    return get_success_data(
        api_client.create_exclusion_term(
            quote_id, create_exclusion_term_payload(**overrides), UNDERWRITER
        )
    )


def conduct_term_of(quote_id: str) -> dict:
    """The CONDUCT term that issuing a quote automatically opens for the insurer."""
    return find_term(read_exclusion_terms(quote_id), "CONDUCT")


def resolve_term_as_insured(term_id: str, insured_id: str, resolution: str = "AGREE") -> dict:
    """Resolve a term from the buyer's side; the acting role must differ from
    ``last_actor_role``."""
    return get_success_data(
        api_client.resolve_exclusion_term(
            term_id, resolve_exclusion_term_payload(resolution),
            make_risk_manager_headers(insured_id),
        )
    )


def resolve_term_as_underwriter(term_id: str, resolution: str = "AGREE") -> dict:
    return get_success_data(
        api_client.resolve_exclusion_term(
            term_id, resolve_exclusion_term_payload(resolution), UNDERWRITER
        )
    )


def bind_quote(quote_id: str, insured_id: str) -> dict:
    """Accept the quote as the RiskManager that owns the insured."""
    return get_success_data(
        api_client.accept_quote(quote_id, make_risk_manager_headers(insured_id))
    )


# ─── Tier 2: entity hierarchy up to a scored submission ──────────────────────


def setup_insured_with_history(insured_overrides=None, package_overrides=None,
                              litigation_overrides=None) -> dict:
    """An insured with its disclosure packages and litigation history on file.

    ``package_overrides`` and ``litigation_overrides`` each accept a single
    override dict or a list of them; pass ``[]`` to file nothing.
    """
    insured = register_insured(**(insured_overrides or {}))
    packages = [
        file_disclosure_package(insured["id"], **o)
        for o in _as_list(package_overrides, [{}])
    ]
    events = [
        file_litigation_event(insured["id"], **o)
        for o in _as_list(litigation_overrides, [{}])
    ]
    return {"insured": insured, "packages": packages, "events": events}


def setup_scored_submission(insured_overrides=None, package_overrides=None,
                            litigation_overrides=None, submission_overrides=None,
                            variant: str = "INDICATIVE") -> dict:
    """An insured with disclosures and litigation on file and a scored submission."""
    scenario = setup_insured_with_history(
        insured_overrides, package_overrides, litigation_overrides
    )
    submission = open_submission(scenario["insured"]["id"], **(submission_overrides or {}))
    submission = run_scoring(submission["id"], variant)
    scenario["submission"] = submission
    return scenario


def setup_offered_quote(quote_overrides=None, extra_terms=None, **kwargs) -> dict:
    """A scored submission with a quote in ``OFFERED`` and its automatic CONDUCT term.

    ``extra_terms`` is a list of exclusion-term override dicts to open on the quote.
    """
    scenario = setup_scored_submission(**kwargs)
    quote = issue_quote(scenario["submission"]["id"], **(quote_overrides or {}))
    scenario["quote"] = quote
    scenario["conduct_term"] = conduct_term_of(quote["id"])
    scenario["extra_terms"] = [
        open_exclusion_term(quote["id"], **o) for o in (extra_terms or [])
    ]
    return scenario


# ─── Tier 3: full lifecycle up to a bound policy ─────────────────────────────


def setup_bound_policy(conduct_resolution: str = "AGREE", agreed_terms=None,
                       rejected_terms=None, **kwargs) -> dict:
    """A bound policy with its coverage parts.

    ``agreed_terms`` and ``rejected_terms`` are lists of exclusion-term override
    dicts opened on the quote and then resolved ``AGREE`` / ``REJECT`` by the
    insured's risk manager before the quote is accepted.
    """
    extra = list(agreed_terms or []) + list(rejected_terms or [])
    scenario = setup_offered_quote(extra_terms=extra, **kwargs)
    insured_id = scenario["insured"]["id"]
    resolve_term_as_insured(scenario["conduct_term"]["id"], insured_id, conduct_resolution)
    resolved = []
    for index, term in enumerate(scenario["extra_terms"]):
        resolution = "AGREE" if index < len(agreed_terms or []) else "REJECT"
        resolved.append(resolve_term_as_insured(term["id"], insured_id, resolution))
    scenario["extra_terms"] = resolved
    scenario["policy"] = bind_quote(scenario["quote"]["id"], insured_id)
    scenario["coverage_parts"] = read_coverage_parts(scenario["policy"]["id"])
    return scenario


def setup_paid_policy(**kwargs) -> dict:
    """A bound policy whose gross premium has been paid in full."""
    scenario = setup_bound_policy(**kwargs)
    policy = scenario["policy"]
    scenario["policy"] = get_success_data(
        api_client.create_premium_payment(
            policy["id"], premium_payment_payload(policy["gross_premium_usd"]),
            make_risk_manager_headers(scenario["insured"]["id"]),
        )
    )
    return scenario


def setup_delinquent_policy(due_date_clock: str = "2026-08-31T00:00:00Z", **kwargs) -> dict:
    """A bound policy the epoch advance has flagged ``DELINQUENT`` on its
    ``premium_due_date``."""
    scenario = setup_bound_policy(**kwargs)
    set_clock(due_date_clock)
    scenario["ops_run"] = advance_epoch()
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


def setup_cancelled_policy(effective_date: str, cancelled_reason: str = "INSURED_REQUEST",
                           **kwargs) -> dict:
    """A bound policy cancelled mid-term with its unearned premium credited."""
    scenario = setup_bound_policy(**kwargs)
    scenario["policy"] = get_success_data(
        api_client.cancel_policy(
            scenario["policy"]["id"],
            cancel_policy_payload(effective_date, cancelled_reason), COMPLIANCE,
        )
    )
    return scenario


def setup_runoff_policy(tail_years: int = 1,
                        change_of_control_date: str = "2026-12-01T00:00:00Z",
                        control_status: str = "ACQUIRED", **kwargs) -> dict:
    """A bound policy moved into ``RUNOFF`` by a change-of-control endorsement."""
    scenario = setup_bound_policy(**kwargs)
    insured = read_insured(scenario["insured"]["id"])
    scenario["insured"] = revise_insured(
        insured["id"], insured["version"],
        control_status=control_status, change_of_control_date=change_of_control_date,
    )
    scenario["endorsement"] = get_success_data(
        api_client.create_runoff_endorsement(
            scenario["policy"]["id"], create_runoff_endorsement_payload(tail_years),
            COMPLIANCE,
        )
    )
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


# ─── Tier 3: tower placement ─────────────────────────────────────────────────


def subscribe_layer(policy_id: str, **overrides) -> dict:
    """Subscribe one band into the policy's tower."""
    return get_success_data(
        api_client.create_layer(
            policy_id, create_layer_payload(policy_id, **overrides), UNDERWRITER
        )
    )


def setup_policy_with_primary_layer(**kwargs) -> dict:
    """A bound policy carrying a fully subscribed primary layer at attachment 0."""
    scenario = setup_bound_policy(**kwargs)
    policy = scenario["policy"]
    scenario["primary_layer"] = subscribe_layer(
        policy["id"], attachment_point_usd=0,
        limit_usd=policy["shared_aggregate_limit_usd"], participation_pct=1.0,
    )
    scenario["policy"] = read_policy(policy["id"])
    return scenario


def setup_policy_with_sealed_tower(**kwargs) -> dict:
    """A bound policy whose tower is contiguous from 0, fully subscribed to the
    programme target, and sealed."""
    scenario = setup_policy_with_primary_layer(**kwargs)
    policy = scenario["policy"]
    primary = scenario["primary_layer"]
    excess_limit = policy["program_target_limit_usd"] - policy["shared_aggregate_limit_usd"]
    scenario["excess_layer"] = None
    if excess_limit > 0:
        scenario["excess_layer"] = subscribe_layer(
            policy["id"], carrier_name="Zurich Excess",
            attachment_point_usd=policy["shared_aggregate_limit_usd"],
            limit_usd=excess_limit, participation_pct=1.0,
            underlying_layer_id=primary["id"],
        )
    scenario["policy"] = get_success_data(
        api_client.seal_tower(policy["id"], UNDERWRITER)
    )
    return scenario


# ─── Tier 4: notice, coverage and defense advancement ────────────────────────


def notice_claim(policy_id: str, insured_id: str, **overrides) -> dict:
    """Notice a claim first made against the insured during the policy period."""
    return get_success_data(
        api_client.create_claim(
            policy_id, create_claim_payload(policy_id, **overrides),
            make_risk_manager_headers(insured_id),
        )
    )


def setup_policy_with_claim(notice_clock: str = DEFAULT_NOTICE_CLOCK,
                            claim_overrides=None, policy_scenario=None, **kwargs) -> dict:
    """A bound policy with one claim in ``NOTICED``.

    The clock is moved inside the claims-made window before notice, because the
    reading must be at or after ``period_start`` and strictly before ``period_end``.
    """
    scenario = policy_scenario or setup_bound_policy(**kwargs)
    if notice_clock:
        set_clock(notice_clock)
    scenario["claim"] = notice_claim(
        scenario["policy"]["id"], scenario["insured"]["id"], **(claim_overrides or {})
    )
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


def record_coverage_decision(claim_id: str, decision: str = "ACCEPT_WITH_ROR",
                             adjuster_user_id: str = FIRST_ADJUSTER_USER_ID,
                             **overrides) -> dict:
    """Accept coverage under a reservation of rights, or deny coverage."""
    return get_success_data(
        api_client.create_coverage_decision(
            claim_id, coverage_decision_payload(decision, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def setup_claim_with_coverage_accepted(allocation_method: str = "RELATIVE_EXPOSURE",
                                       **kwargs) -> dict:
    """A claim moved ``NOTICED -> COVERAGE_ACCEPTED`` with its allocation method frozen."""
    scenario = setup_policy_with_claim(**kwargs)
    scenario["claim"] = record_coverage_decision(
        scenario["claim"]["id"], "ACCEPT_WITH_ROR", allocation_method=allocation_method
    )
    return scenario


def submit_defense_invoice(claim_id: str, insured_id: str, **overrides) -> dict:
    """Submit a defense counsel invoice split into covered, uncovered and mixed."""
    return get_success_data(
        api_client.create_defense_invoice(
            claim_id, create_defense_invoice_payload(claim_id, **overrides),
            make_risk_manager_headers(insured_id),
        )
    )


def allocate_defense_invoice(invoice_id: str, claim_id: str,
                             expected_claim_version: int = None,
                             adjuster_user_id: str = FIRST_ADJUSTER_USER_ID) -> dict:
    """Allocate a submitted invoice and advance the covered portion."""
    if expected_claim_version is None:
        expected_claim_version = read_claim(claim_id)["version"]
    return get_success_data(
        api_client.allocate_defense_invoice(
            invoice_id, allocate_invoice_payload(expected_claim_version),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def setup_claim_with_submitted_invoice(invoice_overrides=None, **kwargs) -> dict:
    """A claim in ``COVERAGE_ACCEPTED`` carrying one invoice in ``SUBMITTED``."""
    scenario = setup_claim_with_coverage_accepted(**kwargs)
    scenario["invoice"] = submit_defense_invoice(
        scenario["claim"]["id"], scenario["insured"]["id"], **(invoice_overrides or {})
    )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_claim_with_advanced_invoice(invoice_overrides=None,
                                      adjuster_user_id: str = FIRST_ADJUSTER_USER_ID,
                                      **kwargs) -> dict:
    """A claim in ``DEFENSE_ADVANCING`` whose invoice has been allocated."""
    scenario = setup_claim_with_submitted_invoice(invoice_overrides=invoice_overrides,
                                                  **kwargs)
    scenario["invoice"] = allocate_defense_invoice(
        scenario["invoice"]["id"], scenario["claim"]["id"],
        adjuster_user_id=adjuster_user_id,
    )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    scenario["coverage_parts"] = read_coverage_parts(scenario["policy"]["id"])
    return scenario


# ─── Tier 5: settlement, consent and funding ─────────────────────────────────


def recommend_settlement(claim_id: str, recommended_amount_usd: float,
                         expected_claim_version: int = None,
                         adjuster_user_id: str = FIRST_ADJUSTER_USER_ID) -> dict:
    """Recommend a settlement amount to the insured for consent."""
    if expected_claim_version is None:
        expected_claim_version = read_claim(claim_id)["version"]
    return get_success_data(
        api_client.create_settlement_proposal(
            claim_id,
            create_settlement_proposal_payload(recommended_amount_usd,
                                               expected_claim_version),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def respond_to_settlement(proposal_id: str, insured_id: str, response: str,
                          **overrides) -> dict:
    """Consent to or refuse the recommended settlement."""
    return get_success_data(
        api_client.respond_settlement_proposal(
            proposal_id, respond_settlement_proposal_payload(response, **overrides),
            make_risk_manager_headers(insured_id),
        )
    )


def fund_resolution(claim_id: str, final_resolution_amount_usd: float,
                    adjuster_user_id: str = SECOND_ADJUSTER_USER_ID, **overrides) -> dict:
    """Fund the resolution of a claim. The funding adjuster must differ from the
    adjuster who recommended the settlement."""
    return get_success_data(
        api_client.resolve_claim(
            claim_id, resolve_claim_payload(final_resolution_amount_usd, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def setup_claim_in_settlement_pending(recommended_amount_usd: float = 1_500_000,
                                      adjuster_user_id: str = FIRST_ADJUSTER_USER_ID,
                                      from_advanced: bool = False, **kwargs) -> dict:
    """A claim in ``SETTLEMENT_PENDING`` with a proposal in ``RECOMMENDED``."""
    if from_advanced:
        scenario = setup_claim_with_advanced_invoice(**kwargs)
    else:
        scenario = setup_claim_with_coverage_accepted(**kwargs)
    scenario["proposal"] = recommend_settlement(
        scenario["claim"]["id"], recommended_amount_usd,
        adjuster_user_id=adjuster_user_id,
    )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_claim_with_answered_proposal(response: str = "CONSENT",
                                       recommended_amount_usd: float = 1_500_000,
                                       **kwargs) -> dict:
    """A claim in ``SETTLEMENT_PENDING`` whose newest proposal has been consented
    to or refused, so the hammer cap is stored and the resolution may be funded."""
    scenario = setup_claim_in_settlement_pending(
        recommended_amount_usd=recommended_amount_usd, **kwargs
    )
    scenario["proposal"] = respond_to_settlement(
        scenario["proposal"]["id"], scenario["insured"]["id"], response
    )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_settled_claim(final_resolution_amount_usd: float,
                        response: str = "CONSENT",
                        recommended_amount_usd: float = 1_500_000, **kwargs) -> dict:
    """A claim funded through to ``SETTLED`` with the indemnity split across parts."""
    scenario = setup_claim_with_answered_proposal(
        response=response, recommended_amount_usd=recommended_amount_usd, **kwargs
    )
    scenario["claim"] = fund_resolution(
        scenario["claim"]["id"], final_resolution_amount_usd
    )
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    scenario["coverage_parts"] = read_coverage_parts(scenario["policy"]["id"])
    scenario["proposal"] = read_settlement_proposals(scenario["claim"]["id"])[-1]
    return scenario


# ─── Tier 4: circumstance reporting ──────────────────────────────────────────


def report_circumstance(policy_id: str, insured_id: str, **overrides) -> dict:
    """Report a circumstance that may give rise to a claim, fixing an in-period
    notice date."""
    return get_success_data(
        api_client.create_circumstance_report(
            policy_id, create_circumstance_report_payload(**overrides),
            make_risk_manager_headers(insured_id),
        )
    )


def mature_circumstance(report_id: str, **overrides) -> dict:
    """Mature a reported circumstance into a claim whose notice date relates back."""
    return get_success_data(
        api_client.mature_circumstance_report(
            report_id, mature_circumstance_report_payload(**overrides), ADJUSTER
        )
    )


def setup_policy_with_circumstance_report(report_clock: str = DEFAULT_NOTICE_CLOCK,
                                          report_overrides=None,
                                          policy_scenario=None, **kwargs) -> dict:
    """A bound policy carrying one circumstance report in ``REPORTED``."""
    scenario = policy_scenario or setup_bound_policy(**kwargs)
    if report_clock:
        set_clock(report_clock)
    scenario["circumstance_report"] = report_circumstance(
        scenario["policy"]["id"], scenario["insured"]["id"], **(report_overrides or {})
    )
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


# ─── Targeting helpers ───────────────────────────────────────────────────────


def side_c_part(scenario_or_parts) -> dict:
    parts = scenario_or_parts["coverage_parts"] if isinstance(scenario_or_parts, dict) \
        else scenario_or_parts
    return find_part(parts, "SIDE_C")


def side_b_part(scenario_or_parts) -> dict:
    parts = scenario_or_parts["coverage_parts"] if isinstance(scenario_or_parts, dict) \
        else scenario_or_parts
    return find_part(parts, "SIDE_B")


def side_a_part(scenario_or_parts) -> dict:
    parts = scenario_or_parts["coverage_parts"] if isinstance(scenario_or_parts, dict) \
        else scenario_or_parts
    return find_part(parts, "SIDE_A")


THREE_PACKAGE_HISTORY = [
    # FY2025 — financial subscore 24, governance subscore 22.
    {
        "fiscal_year": 2025, "filed_date": "2026-03-01T00:00:00Z",
        "restatement_flag": True, "material_weakness_count": 1,
        "going_concern_flag": False, "negative_operating_cash_flow_flag": False,
        "debt_to_equity": 1.1, "independent_director_ratio": 0.40,
        "dual_class_shares_flag": False, "staggered_board_flag": False,
        "combined_ceo_chair_flag": True, "auditor_change_flag": False,
    },
    # FY2024 — financial subscore 48, governance subscore 26. The financial
    # maximum and the governance maximum therefore come from different packages.
    {
        "fiscal_year": 2024, "filed_date": "2025-03-01T00:00:00Z",
        "restatement_flag": True, "material_weakness_count": 0,
        "going_concern_flag": True, "negative_operating_cash_flow_flag": True,
        "debt_to_equity": 2.4, "independent_director_ratio": 0.40,
        "dual_class_shares_flag": False, "staggered_board_flag": False,
        "combined_ceo_chair_flag": False, "auditor_change_flag": True,
    },
    # FY2023 — financial subscore 0, governance subscore 6.
    {
        "fiscal_year": 2023, "filed_date": "2024-03-01T00:00:00Z",
        "restatement_flag": False, "material_weakness_count": 0,
        "going_concern_flag": False, "negative_operating_cash_flow_flag": False,
        "debt_to_equity": 0.9, "independent_director_ratio": 0.60,
        "dual_class_shares_flag": False, "staggered_board_flag": True,
        "combined_ceo_chair_flag": False, "auditor_change_flag": False,
    },
]

# The litigation history that carries the UNDERWRITTEN variant to 35.5 units:
# a securities class action inside the full-weight recency band, a resolved
# merger objection in the half-weight band, and one unresolved employment
# matter that also attracts the open-litigation surcharge.
THREE_EVENT_HISTORY = [
    {
        "case_type": "SECURITIES_CLASS_ACTION", "filed_date": "2024-06-15T00:00:00Z",
        "resolved_date": "2025-01-15T00:00:00Z", "indemnity_paid_usd": 4_000_000,
        "outcome": "SETTLED",
    },
    {
        "case_type": "MERGER_OBJECTION", "filed_date": "2021-03-01T00:00:00Z",
        "resolved_date": "2021-09-01T00:00:00Z", "indemnity_paid_usd": 0,
        "outcome": "DISMISSED",
    },
    {
        "case_type": "EMPLOYMENT_PRACTICES", "filed_date": "2026-01-10T00:00:00Z",
        "resolved_date": None, "indemnity_paid_usd": 0, "outcome": "PENDING",
    },
]

__all__ = [
    "UNDERWRITER", "ADJUSTER", "SECOND_ADJUSTER", "COMPLIANCE",
    "DEFAULT_NOTICE_CLOCK", "THREE_PACKAGE_HISTORY", "THREE_EVENT_HISTORY",
    "set_clock", "advance_epoch",
    "read_insured", "read_submission", "read_quote", "read_policy", "read_claim",
    "read_layer", "read_coverage_parts", "read_exclusion_terms",
    "read_defense_invoices", "read_settlement_proposals", "read_layers",
    "read_runoff_endorsements", "read_circumstance_reports",
    "register_insured", "revise_insured", "file_disclosure_package",
    "file_litigation_event", "open_submission", "run_scoring", "issue_quote",
    "open_exclusion_term", "conduct_term_of", "resolve_term_as_insured",
    "resolve_term_as_underwriter", "bind_quote",
    "setup_insured_with_history", "setup_scored_submission", "setup_offered_quote",
    "setup_bound_policy", "setup_paid_policy", "setup_delinquent_policy",
    "setup_cancelled_policy", "setup_runoff_policy",
    "subscribe_layer", "setup_policy_with_primary_layer",
    "setup_policy_with_sealed_tower",
    "notice_claim", "setup_policy_with_claim", "record_coverage_decision",
    "setup_claim_with_coverage_accepted", "submit_defense_invoice",
    "allocate_defense_invoice", "setup_claim_with_submitted_invoice",
    "setup_claim_with_advanced_invoice",
    "recommend_settlement", "respond_to_settlement", "fund_resolution",
    "setup_claim_in_settlement_pending", "setup_claim_with_answered_proposal",
    "setup_settled_claim",
    "report_circumstance", "mature_circumstance",
    "setup_policy_with_circumstance_report",
    "side_a_part", "side_b_part", "side_c_part",
]
