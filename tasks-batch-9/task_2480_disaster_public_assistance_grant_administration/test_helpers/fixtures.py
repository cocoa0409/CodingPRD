"""Composite setup helpers.

Every test starts against an empty database, so every precondition has to be
built here from scratch using only PRD-declared endpoints.  These helpers use
the lenient `get_success_data()` validator so a broken precondition surfaces as
a setup failure rather than a confusing assertion further down.

Layering:
  * step helpers   — one API call each (`create_disaster`, `screen_facility`, ...)
  * scenario helpers — the recurring multi-call chains
    (`setup_eligible_applicant`, `setup_submitted_project`,
     `setup_validated_project`, `setup_obligated_project`,
     `setup_finalized_deobligation`, ...)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    appeal_payload,
    applicant_payload,
    contract_payload,
    cost_line_item_payload,
    damage_site_payload,
    deobligation_payload,
    disaster_payload,
    drawdown_payload,
    equipment_resource_payload,
    facility_payload,
    insurance_policy_payload,
    labor_resource_payload,
    progress_report_payload,
    project_payload,
)
from .test_users import (
    ADJUDICATOR_USER_ID,
    AUDITOR_USER_ID,
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    SPECIALIST_USER_ID,
    TEST_USERS,
    make_adjudicator_headers,
    make_applicant_agent_headers,
    make_auditor_headers,
    make_grants_officer_headers,
    make_specialist_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
OFFICER = TEST_USERS["grants_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_grants_officer_headers"]
ADJUDICATOR = TEST_USERS["adjudicator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Returns the `{current_utc}` payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Step helpers — one API call each
# ---------------------------------------------------------------------------
def create_disaster(**overrides) -> dict:
    return get_success_data(api_client.create_disaster(disaster_payload(**overrides), ADMIN))


def get_disaster(disaster_id: str) -> dict:
    return get_success_data(api_client.get_disaster(disaster_id, ADMIN))


def close_obligations(disaster_id: str) -> dict:
    return get_success_data(api_client.close_obligations(disaster_id, ADMIN))


def create_applicant(disaster_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(applicant_payload(disaster_id, **overrides), ADMIN)
    )


def get_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, ADMIN))


def determine_eligibility(
    applicant_id: str,
    decision: str = "ELIGIBLE",
    rationale: str = "Legal responsibility and cost documentation verified.",
    specialist_user_id: str = SPECIALIST_USER_ID,
) -> dict:
    return get_success_data(
        api_client.determine_eligibility(
            applicant_id,
            {"decision": decision, "rationale": rationale},
            make_specialist_headers(specialist_user_id),
        )
    )


def reporting_sweep(applicant_id: str) -> dict:
    return get_success_data(api_client.reporting_sweep(applicant_id, ADMIN))


def create_facility(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(
            facility_payload(applicant_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def screen_facility(facility_id: str, specialist_user_id: str = SPECIALIST_USER_ID) -> dict:
    return get_success_data(
        api_client.screen_facility(facility_id, make_specialist_headers(specialist_user_id))
    )


def amend_facility(facility_id: str, applicant_id: str, **patch) -> dict:
    return get_success_data(
        api_client.amend_facility(facility_id, patch, make_applicant_agent_headers(applicant_id))
    )


def create_damage_site(facility_id: str, applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_damage_site(
            damage_site_payload(facility_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def validate_damage_site(
    damage_site_id: str, validated_loss_cents: int, specialist_user_id: str = SPECIALIST_USER_ID
) -> dict:
    return get_success_data(
        api_client.validate_damage_site(
            damage_site_id,
            {"decision": "VALIDATE", "validated_loss_cents": validated_loss_cents},
            make_specialist_headers(specialist_user_id),
        )
    )


def reject_damage_site(
    damage_site_id: str, rejection_reason: str, specialist_user_id: str = SPECIALIST_USER_ID
) -> dict:
    return get_success_data(
        api_client.validate_damage_site(
            damage_site_id,
            {"decision": "REJECT", "rejection_reason": rejection_reason},
            make_specialist_headers(specialist_user_id),
        )
    )


def create_labor_resource(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_force_account_resource(
            labor_resource_payload(applicant_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def create_equipment_resource(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_force_account_resource(
            equipment_resource_payload(applicant_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_force_account_resource(resource_id: str) -> dict:
    return get_success_data(api_client.get_force_account_resource(resource_id, ADMIN))


def create_contract(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            contract_payload(applicant_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def review_procurement(contract_id: str, specialist_user_id: str = SPECIALIST_USER_ID) -> dict:
    return get_success_data(
        api_client.review_procurement(contract_id, make_specialist_headers(specialist_user_id))
    )


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))


def create_reviewed_contract(applicant_id: str, **overrides) -> dict:
    """Create a contract and run procurement review on it."""
    contract = create_contract(applicant_id, **overrides)
    return review_procurement(contract["id"])


def create_insurance_policy(facility_id: str, applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_policy(
            insurance_policy_payload(facility_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_insurance_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_insurance_policy(policy_id, ADMIN))


def record_settlement(
    policy_id: str,
    settlement_amount_cents: int,
    settled_at: str,
    officer_user_id: str = GRANTS_OFFICER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.record_settlement(
            policy_id,
            {
                "settlement_amount_cents": settlement_amount_cents,
                "settled_at": settled_at,
            },
            make_grants_officer_headers(officer_user_id),
        )
    )


def create_project(applicant_id: str, facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(
            project_payload(applicant_id, facility_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, ADMIN))


def submit_project(project_id: str, applicant_id: str) -> dict:
    return get_success_data(
        api_client.submit_project(project_id, make_applicant_agent_headers(applicant_id))
    )


def issue_rfi(project_id: str, question: str, specialist_user_id: str = SPECIALIST_USER_ID) -> dict:
    return get_success_data(
        api_client.issue_rfi(
            project_id, {"question": question}, make_specialist_headers(specialist_user_id)
        )
    )


def respond_to_rfi(
    project_id: str, applicant_id: str, response: str, revised_estimate_cents: int = None
) -> dict:
    payload = {"response": response}
    if revised_estimate_cents is not None:
        payload["revised_estimate_cents"] = revised_estimate_cents
    return get_success_data(
        api_client.respond_to_rfi(project_id, payload, make_applicant_agent_headers(applicant_id))
    )


def create_cost_line_item(project_id: str, applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cost_line_item(
            cost_line_item_payload(project_id, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def review_cost_line_item(
    cost_line_item_id: str, specialist_user_id: str = SPECIALIST_USER_ID
) -> dict:
    return get_success_data(
        api_client.review_cost_line_item(
            cost_line_item_id, make_specialist_headers(specialist_user_id)
        )
    )


def get_cost_line_item(cost_line_item_id: str) -> dict:
    return get_success_data(api_client.get_cost_line_item(cost_line_item_id, ADMIN))


def cost_review(
    project_id: str,
    decision: str = "VALIDATE",
    denial_reason: str = None,
    specialist_user_id: str = SPECIALIST_USER_ID,
) -> dict:
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.cost_review(project_id, payload, make_specialist_headers(specialist_user_id))
    )


def obligate_project(project_id: str, officer_user_id: str = GRANTS_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.obligate_project(project_id, make_grants_officer_headers(officer_user_id))
    )


def request_closeout(project_id: str, applicant_id: str) -> dict:
    return get_success_data(
        api_client.request_closeout(project_id, make_applicant_agent_headers(applicant_id))
    )


def certify_closeout(
    project_id: str,
    audit_finding: str = "Documented costs reconcile to the approved scope.",
    auditor_user_id: str = AUDITOR_USER_ID,
) -> dict:
    return get_success_data(
        api_client.certify_closeout(
            project_id, {"audit_finding": audit_finding}, make_auditor_headers(auditor_user_id)
        )
    )


def create_drawdown(
    applicant_id: str,
    project_id: str,
    requested_cents: int,
    expected_applicant_version: int = None,
) -> dict:
    if expected_applicant_version is None:
        expected_applicant_version = get_applicant(applicant_id)["version"]
    return get_success_data(
        api_client.create_drawdown(
            drawdown_payload(
                applicant_id, project_id, requested_cents, expected_applicant_version
            ),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_drawdown(drawdown_id: str) -> dict:
    return get_success_data(api_client.get_drawdown(drawdown_id, ADMIN))


def disburse_drawdown(
    drawdown_id: str,
    officer_user_id: str = SECOND_GRANTS_OFFICER_USER_ID,
    decision: str = "PAY",
    rejection_reason: str = None,
) -> dict:
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.disburse_drawdown(
            drawdown_id, payload, make_grants_officer_headers(officer_user_id)
        )
    )


def refund_drawdown(drawdown_id: str, applicant_id: str, refund_cents: int) -> dict:
    return get_success_data(
        api_client.refund_drawdown(
            drawdown_id, {"refund_cents": refund_cents}, make_applicant_agent_headers(applicant_id)
        )
    )


def create_progress_report(applicant_id: str, quarter_label: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_progress_report(
            progress_report_payload(applicant_id, quarter_label, **overrides),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_progress_report(progress_report_id: str) -> dict:
    return get_success_data(api_client.get_progress_report(progress_report_id, ADMIN))


def submit_progress_report(
    progress_report_id: str,
    applicant_id: str,
    expenditures_to_date_cents: int = 0,
    pct_complete: float = 50,
) -> dict:
    return get_success_data(
        api_client.submit_progress_report(
            progress_report_id,
            {
                "expenditures_to_date_cents": expenditures_to_date_cents,
                "pct_complete": pct_complete,
            },
            make_applicant_agent_headers(applicant_id),
        )
    )


def create_deobligation(
    project_id: str,
    amount_cents: int,
    reason: str = "SCOPE_REDUCTION",
    expected_project_version: int = None,
    headers: dict = None,
) -> dict:
    if expected_project_version is None:
        expected_project_version = get_project(project_id)["version"]
    return get_success_data(
        api_client.create_deobligation(
            deobligation_payload(project_id, amount_cents, expected_project_version, reason),
            headers or OFFICER,
        )
    )


def get_deobligation(deobligation_id: str) -> dict:
    return get_success_data(api_client.get_deobligation(deobligation_id, ADMIN))


def finalize_deobligation(
    deobligation_id: str, officer_user_id: str = GRANTS_OFFICER_USER_ID
) -> dict:
    return get_success_data(
        api_client.finalize_deobligation(
            deobligation_id, make_grants_officer_headers(officer_user_id)
        )
    )


def file_appeal(
    deobligation_id: str,
    applicant_id: str,
    relief_requested_cents: int,
    grounds: str = "The reduction misreads the documented scope of work.",
    prior_appeal_id: str = None,
) -> dict:
    return get_success_data(
        api_client.create_appeal(
            appeal_payload(deobligation_id, relief_requested_cents, grounds, prior_appeal_id),
            make_applicant_agent_headers(applicant_id),
        )
    )


def get_appeal(appeal_id: str) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, ADMIN))


def decide_appeal(
    appeal_id: str,
    decision: str,
    relief_granted_cents: int = None,
    decision_rationale: str = "Reviewed the administrative record in full.",
    adjudicator_user_id: str = ADJUDICATOR_USER_ID,
) -> dict:
    payload = {"decision": decision, "decision_rationale": decision_rationale}
    if relief_granted_cents is not None:
        payload["relief_granted_cents"] = relief_granted_cents
    return get_success_data(
        api_client.decide_appeal(
            appeal_id, payload, make_adjudicator_headers(adjudicator_user_id)
        )
    )


# ---------------------------------------------------------------------------
# Scenario helpers — the recurring multi-call chains
# ---------------------------------------------------------------------------
def setup_declaration(clock: str = None, **disaster_overrides) -> dict:
    """Set the logical clock and declare one disaster.

    Returns {"disaster": ...}.
    """
    set_clock(clock or TEST_DEFAULTS["CLOCK"])
    return {"disaster": create_disaster(**disaster_overrides)}


def setup_eligible_applicant(
    clock: str = None, disaster_overrides: dict = None, applicant_overrides: dict = None
) -> dict:
    """Clock + declaration + applicant determined ELIGIBLE.

    Returns {"disaster", "applicant", "agent"} where `agent` is the applicant's
    own `ApplicantAgent` header dict.
    """
    scenario = setup_declaration(clock, **(disaster_overrides or {}))
    applicant = create_applicant(scenario["disaster"]["id"], **(applicant_overrides or {}))
    applicant = determine_eligibility(applicant["id"])
    scenario["applicant"] = applicant
    scenario["agent"] = make_applicant_agent_headers(applicant["id"])
    return scenario


def setup_eligible_facility(
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
) -> dict:
    """Eligible applicant plus one facility screened ELIGIBLE.

    Returns {"disaster", "applicant", "agent", "facility"}.
    """
    scenario = setup_eligible_applicant(clock, disaster_overrides, applicant_overrides)
    facility = create_facility(scenario["applicant"]["id"], **(facility_overrides or {}))
    scenario["facility"] = screen_facility(facility["id"])
    return scenario


def setup_drafted_project(
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
) -> dict:
    """Eligible applicant + eligible facility + one DRAFT project.

    Returns {"disaster", "applicant", "agent", "facility", "project"}.
    """
    scenario = setup_eligible_facility(
        clock, disaster_overrides, applicant_overrides, facility_overrides
    )
    scenario["project"] = create_project(
        scenario["applicant"]["id"], scenario["facility"]["id"], **(project_overrides or {})
    )
    return scenario


def setup_submitted_project(
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
) -> dict:
    """A project walked all the way to UNDER_REVIEW."""
    scenario = setup_drafted_project(
        clock, disaster_overrides, applicant_overrides, facility_overrides, project_overrides
    )
    scenario["project"] = submit_project(
        scenario["project"]["id"], scenario["applicant"]["id"]
    )
    return scenario


def setup_validated_project(
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
    line_items: list = None,
) -> dict:
    """A project walked to VALIDATED, optionally with reviewed cost lines.

    `line_items` is a list of `create_cost_line_item` override dicts; each line
    is created and then individually reviewed, so cost review is not blocked by
    an unreviewed claim.  When `line_items` is None the project is validated on
    its estimate alone.

    Returns the submitted-project scenario plus {"lines": [...]}.
    """
    scenario = setup_submitted_project(
        clock, disaster_overrides, applicant_overrides, facility_overrides, project_overrides
    )
    lines = []
    for spec in line_items or []:
        line = create_cost_line_item(
            scenario["project"]["id"], scenario["applicant"]["id"], **spec
        )
        lines.append(review_cost_line_item(line["id"]))
    scenario["lines"] = lines
    scenario["project"] = cost_review(scenario["project"]["id"])
    return scenario


def setup_obligated_project(
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
    line_items: list = None,
    officer_user_id: str = GRANTS_OFFICER_USER_ID,
) -> dict:
    """A project walked all the way to OBLIGATED.

    Returns the validated-project scenario with `project` refreshed to its
    obligated state.
    """
    scenario = setup_validated_project(
        clock,
        disaster_overrides,
        applicant_overrides,
        facility_overrides,
        project_overrides,
        line_items,
    )
    scenario["project"] = obligate_project(scenario["project"]["id"], officer_user_id)
    scenario["applicant"] = get_applicant(scenario["applicant"]["id"])
    scenario["disaster"] = get_disaster(scenario["disaster"]["id"])
    return scenario


def setup_proposed_deobligation(
    amount_cents: int,
    reason: str = "SCOPE_REDUCTION",
    headers: dict = None,
    **scenario_kwargs,
) -> dict:
    """An obligated project carrying one PROPOSED determination.

    Returns the obligated-project scenario plus {"deobligation": ...}.
    """
    scenario = setup_obligated_project(**scenario_kwargs)
    scenario["deobligation"] = create_deobligation(
        scenario["project"]["id"], amount_cents, reason, headers=headers
    )
    scenario["project"] = get_project(scenario["project"]["id"])
    scenario["applicant"] = get_applicant(scenario["applicant"]["id"])
    return scenario


def setup_finalized_deobligation(
    amount_cents: int,
    reason: str = "SCOPE_REDUCTION",
    headers: dict = None,
    officer_user_id: str = GRANTS_OFFICER_USER_ID,
    **scenario_kwargs,
) -> dict:
    """An obligated project carrying one FINAL determination with an open
    appeal window.

    Returns the obligated-project scenario plus {"deobligation": ...}.
    """
    scenario = setup_proposed_deobligation(
        amount_cents, reason, headers=headers, **scenario_kwargs
    )
    scenario["deobligation"] = finalize_deobligation(
        scenario["deobligation"]["id"], officer_user_id
    )
    scenario["project"] = get_project(scenario["project"]["id"])
    scenario["applicant"] = get_applicant(scenario["applicant"]["id"])
    return scenario


def setup_appeal_under_review(
    amount_cents: int,
    relief_requested_cents: int = None,
    reason: str = "SCOPE_REDUCTION",
    **scenario_kwargs,
) -> dict:
    """A FINAL determination with one SUBMITTED first-level appeal on it.

    Returns the finalized-determination scenario plus {"appeal": ...}.
    """
    scenario = setup_finalized_deobligation(amount_cents, reason, **scenario_kwargs)
    scenario["appeal"] = file_appeal(
        scenario["deobligation"]["id"],
        scenario["applicant"]["id"],
        relief_requested_cents if relief_requested_cents is not None else amount_cents,
    )
    return scenario


def setup_paid_drawdown(
    requested_cents: int,
    officer_user_id: str = SECOND_GRANTS_OFFICER_USER_ID,
    **scenario_kwargs,
) -> dict:
    """An obligated project whose applicant has drawn and been paid cash.

    Returns the obligated-project scenario plus {"drawdown": ...}.
    """
    scenario = setup_obligated_project(**scenario_kwargs)
    drawdown = create_drawdown(
        scenario["applicant"]["id"], scenario["project"]["id"], requested_cents
    )
    scenario["drawdown"] = disburse_drawdown(drawdown["id"], officer_user_id)
    scenario["applicant"] = get_applicant(scenario["applicant"]["id"])
    scenario["disaster"] = get_disaster(scenario["disaster"]["id"])
    return scenario


def setup_project_with_labor_claim(
    resource_overrides: dict = None,
    line_overrides: dict = None,
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
) -> dict:
    """A submitted project plus one labor resource and one unreviewed
    FORCE_ACCOUNT_LABOR claim against it.

    Returns {"disaster", "applicant", "agent", "facility", "project",
             "resource", "line"}.
    """
    scenario = setup_submitted_project(
        clock, disaster_overrides, applicant_overrides, facility_overrides, project_overrides
    )
    scenario["resource"] = create_labor_resource(
        scenario["applicant"]["id"], **(resource_overrides or {})
    )
    spec = {
        "cost_type": "FORCE_ACCOUNT_LABOR",
        "force_account_resource_id": scenario["resource"]["id"],
    }
    spec.update(line_overrides or {})
    scenario["line"] = create_cost_line_item(
        scenario["project"]["id"], scenario["applicant"]["id"], **spec
    )
    return scenario


def setup_project_with_equipment_claim(
    resource_overrides: dict = None,
    line_overrides: dict = None,
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
) -> dict:
    """A submitted project plus one equipment resource and one unreviewed
    FORCE_ACCOUNT_EQUIPMENT claim against it."""
    scenario = setup_submitted_project(
        clock, disaster_overrides, applicant_overrides, facility_overrides, project_overrides
    )
    scenario["resource"] = create_equipment_resource(
        scenario["applicant"]["id"], **(resource_overrides or {})
    )
    spec = {
        "cost_type": "FORCE_ACCOUNT_EQUIPMENT",
        "force_account_resource_id": scenario["resource"]["id"],
    }
    spec.update(line_overrides or {})
    scenario["line"] = create_cost_line_item(
        scenario["project"]["id"], scenario["applicant"]["id"], **spec
    )
    return scenario


def setup_project_with_contract_claim(
    contract_overrides: dict = None,
    line_overrides: dict = None,
    run_procurement_review: bool = True,
    clock: str = None,
    disaster_overrides: dict = None,
    applicant_overrides: dict = None,
    facility_overrides: dict = None,
    project_overrides: dict = None,
) -> dict:
    """A submitted project plus one contract (optionally already reviewed) and
    one unreviewed CONTRACT claim against it."""
    scenario = setup_submitted_project(
        clock, disaster_overrides, applicant_overrides, facility_overrides, project_overrides
    )
    contract = create_contract(scenario["applicant"]["id"], **(contract_overrides or {}))
    if run_procurement_review:
        contract = review_procurement(contract["id"])
    scenario["contract"] = contract
    spec = {"cost_type": "CONTRACT", "contract_id": contract["id"]}
    spec.update(line_overrides or {})
    scenario["line"] = create_cost_line_item(
        scenario["project"]["id"], scenario["applicant"]["id"], **spec
    )
    return scenario


def setup_closeout_requested_project(
    line_items: list = None,
    closeout_line_items: list = None,
    **scenario_kwargs,
) -> dict:
    """An obligated project moved to CLOSEOUT_REQUESTED.

    `line_items` are documented before cost review (and so form the obligation
    basis); `closeout_line_items` are documented after obligation and reviewed
    before the closeout request, so they form the final documented-cost set.
    """
    scenario = setup_obligated_project(line_items=line_items, **scenario_kwargs)
    extra = []
    for spec in closeout_line_items or []:
        line = create_cost_line_item(
            scenario["project"]["id"], scenario["applicant"]["id"], **spec
        )
        extra.append(review_cost_line_item(line["id"]))
    scenario["closeout_lines"] = extra
    scenario["project"] = request_closeout(
        scenario["project"]["id"], scenario["applicant"]["id"]
    )
    return scenario
