"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh server). Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear error
naming the step that failed, not as a confusing assertion failure.

Identity threading: BSAAnalyst / QAReviewer / BSAManager are entity-backed
roles (PRD §2.1), so every ownership-gated call is made with headers bound to
the actual Analyst.id created in create_staff().
"""
from typing import List, NamedTuple, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import NARRATIVE_CONTINUING, NARRATIVE_STANDARD
from .factories import (
    assign_case_payload,
    complete_review_payload,
    create_account_payload,
    create_case_payload,
    create_customer_payload,
    create_info_share_payload,
    create_le_inquiry_payload,
    create_sar_payload,
    create_scenario_payload,
    create_transaction_payload,
    dismiss_alert_payload,
    evaluate_payload,
    link_alert_payload,
    link_inquiry_payload,
    propose_decision_payload,
    propose_threshold_payload,
    respond_inquiry_payload,
    sar_decision_payload,
    sar_qa_review_payload,
    case_qa_review_payload,
    update_narrative_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_manager_headers,
    make_qa_reviewer_headers,
)


class Staff(NamedTuple):
    """The three Analyst rows used across the workflow, with role headers
    already bound to their real ids (entity-backed roles, PRD §2.1)."""

    analyst_id: str
    qa_id: str
    manager_id: str
    analyst: dict   # BSAAnalyst headers for analyst_id
    qa: dict        # QAReviewer headers for qa_id
    manager: dict   # BSAManager headers for manager_id
    admin: dict     # ComplianceAdmin opaque headers


def create_staff(analyst_capacity: int = 10,
                 qa_capacity: int = 10,
                 manager_capacity: int = 10) -> Staff:
    """Register the analyst/QA/manager roster. Returns ids + bound headers."""
    admin = TEST_USERS["compliance_admin_headers"]
    an = get_success_data(api_client.create_analyst(
        {"full_name": "Ann Analyst", "capacity_max_cases": analyst_capacity}, admin))
    qa = get_success_data(api_client.create_analyst(
        {"full_name": "Quinn QA", "capacity_max_cases": qa_capacity}, admin))
    mg = get_success_data(api_client.create_analyst(
        {"full_name": "Meg Manager", "capacity_max_cases": manager_capacity}, admin))
    return Staff(
        analyst_id=an["id"],
        qa_id=qa["id"],
        manager_id=mg["id"],
        analyst=make_analyst_headers(an["id"]),
        qa=make_qa_reviewer_headers(qa["id"]),
        manager=make_manager_headers(mg["id"]),
        admin=admin,
    )


# ---------------------------------------------------------------------------
# Clock / sweep
# ---------------------------------------------------------------------------

def set_clock(staff: Staff, to_iso8601: str) -> dict:
    """Move the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, staff.admin))


def run_sweep(staff: Staff) -> dict:
    """Run the daily compliance sweep (PRD §2.5). Returns the summary counts."""
    return get_success_data(api_client.run_daily_sweep(staff.admin))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def create_customer(staff: Staff, **overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), staff.admin))


def create_account(staff: Staff, customer_id: str, account_number: str = "ACC-0001") -> dict:
    return get_success_data(api_client.create_account(
        customer_id, create_account_payload(account_number=account_number), staff.admin))


def post_transaction(staff: Staff, account_id: str, **overrides) -> dict:
    return get_success_data(api_client.post_transaction(
        account_id, create_transaction_payload(**overrides), staff.admin))


def post_cash_deposits(staff: Staff, account_id: str,
                       deposits: List[tuple]) -> List[dict]:
    """Post a series of transactions. Each deposit is a tuple
    (amount_cents, posted_at, counterparty_country, channel)."""
    posted = []
    for amount_cents, posted_at, country, channel in deposits:
        posted.append(post_transaction(
            staff, account_id,
            amount_cents=amount_cents, txn_type="CASH_DEPOSIT", direction="CREDIT",
            counterparty_country=country, posted_at=posted_at, channel=channel))
    return posted


# ---------------------------------------------------------------------------
# Monitoring scenarios & threshold tuning lifecycle
# ---------------------------------------------------------------------------

def create_scenario(staff: Staff, **overrides) -> dict:
    """Create a DRAFT monitoring scenario."""
    return get_success_data(
        api_client.create_scenario(create_scenario_payload(**overrides), staff.admin))


def propose_threshold(staff: Staff, scenario: dict, **overrides) -> dict:
    """Propose a threshold version (OCC on the scenario's current version)."""
    return get_success_data(api_client.propose_threshold(
        scenario["id"],
        propose_threshold_payload(scenario["version"], **overrides),
        staff.analyst))


def approve_and_activate_scenario(staff: Staff, scenario: dict) -> dict:
    """Activate a DRAFT (or resume a SUSPENDED) scenario. Returns the scenario."""
    return get_success_data(api_client.activate_scenario(scenario["id"], staff.manager))


def create_active_scenario(staff: Staff, activate_threshold: bool = True,
                           **threshold_overrides) -> Tuple[dict, dict]:
    """Full tuning lifecycle: DRAFT scenario + PROPOSED -> APPROVED threshold,
    scenario ACTIVE, and (by default) the threshold ACTIVE. Returns
    (scenario, threshold) as of the end of the chain."""
    scenario = create_scenario(
        staff,
        **{k: threshold_overrides.pop(k) for k in (
            "scenario_code", "name", "applies_to_txn_types", "direction_filter",
            "baseline_weight_amount", "baseline_weight_velocity",
            "baseline_weight_geo", "stale_alert_days",
        ) if k in threshold_overrides},
    )
    threshold = propose_threshold(staff, scenario, **threshold_overrides)
    get_success_data(api_client.approve_threshold(threshold["id"], staff.manager))
    scenario = approve_and_activate_scenario(staff, scenario)
    if activate_threshold:
        threshold = get_success_data(
            api_client.activate_threshold(threshold["id"], staff.manager))
        scenario = get_success_data(api_client.get_scenario(scenario["id"], staff.admin))
    return scenario, threshold


def evaluate(staff: Staff, scenario_id: str, account_id: str,
             evaluated_at: Optional[str] = None) -> dict:
    """Run one scenario evaluation for an account. Returns the evaluate payload."""
    return get_success_data(api_client.evaluate_scenario(
        scenario_id, evaluate_payload(account_id, evaluated_at), staff.admin))


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def generate_alert(staff: Staff, scenario_id: str, account_id: str,
                   evaluated_at: Optional[str] = None) -> dict:
    """Evaluate and return the generated Alert resource (assumes the trigger fires)."""
    result = evaluate(staff, scenario_id, account_id, evaluated_at)
    assert result.get("alert_created") is True, (
        f"Setup failed: evaluation did not fire for account {account_id}: {result}"
    )
    return get_success_data(api_client.get_alert(result["alert_id"], staff.admin))


def triage_alert(staff: Staff, alert_id: str) -> dict:
    return get_success_data(api_client.triage_alert(alert_id, staff.analyst))


def dismiss_alert(staff: Staff, alert_id: str,
                  rationale: str = "Matches known payroll pattern") -> dict:
    return get_success_data(api_client.dismiss_alert(
        alert_id, dismiss_alert_payload(dismissal_rationale=rationale), staff.analyst))


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def create_case(staff: Staff, customer_id: str,
                source_alert_id: Optional[str] = None,
                as_manager: bool = False) -> dict:
    payload = create_case_payload(customer_id)
    if source_alert_id is not None:
        payload["source_alert_id"] = source_alert_id
    headers = staff.manager if as_manager else staff.analyst
    return get_success_data(api_client.create_case(payload, headers))


def assign_case(staff: Staff, case_id: str, analyst_id: Optional[str] = None) -> dict:
    return get_success_data(api_client.assign_case(
        case_id, assign_case_payload(analyst_id or staff.analyst_id), staff.manager))


def start_investigation(staff: Staff, case_id: str) -> dict:
    return get_success_data(api_client.start_investigation(case_id, staff.analyst))


def record_sar_decision(staff: Staff, case: dict, decision: str,
                        rationale: str = "Unexplained structuring pattern") -> dict:
    return get_success_data(api_client.record_sar_decision(
        case["id"],
        sar_decision_payload(decision, case["version"], decision_rationale=rationale),
        staff.analyst))


def qa_review_case(staff: Staff, case_id: str, outcome: str,
                   notes: Optional[str] = None) -> dict:
    payload = case_qa_review_payload(outcome)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.review_case_qa(case_id, payload, staff.qa))


def drive_case_to_investigating(staff: Staff, customer_id: str,
                                source_alert_id: Optional[str] = None) -> dict:
    """Create -> assign -> start-investigation. Returns the INVESTIGATING case."""
    case = create_case(staff, customer_id, source_alert_id=source_alert_id)
    assign_case(staff, case["id"])
    return start_investigation(staff, case["id"])


def drive_case_to_sar_in_progress(staff: Staff, customer_id: str,
                                  rationale: str = "Unexplained structuring pattern") -> dict:
    """Full path to SAR_IN_PROGRESS via a SAR_REQUIRED decision."""
    case = drive_case_to_investigating(staff, customer_id)
    return record_sar_decision(staff, case, "SAR_REQUIRED", rationale=rationale)


def drive_case_to_pending_qa(staff: Staff, customer_id: str,
                             rationale: str = "Documented legitimate activity") -> dict:
    """Full path to PENDING_QA via a NO_SAR decision."""
    case = drive_case_to_investigating(staff, customer_id)
    return record_sar_decision(staff, case, "NO_SAR", rationale=rationale)


def drive_case_to_closed_no_sar(staff: Staff, customer_id: str) -> dict:
    """Full NO_SAR path through case QA PASS. Returns the CLOSED case."""
    case = drive_case_to_pending_qa(staff, customer_id)
    return qa_review_case(staff, case["id"], "PASS")


# ---------------------------------------------------------------------------
# SAR reports
# ---------------------------------------------------------------------------

def create_sar_draft(staff: Staff, case_id: str,
                     activity_start_date: str = "2026-03-10",
                     activity_end_date: str = "2026-04-10",
                     subject_unidentified: Optional[bool] = None) -> dict:
    payload = create_sar_payload(activity_start_date, activity_end_date)
    if subject_unidentified is not None:
        payload["subject_unidentified"] = subject_unidentified
    return get_success_data(api_client.create_sar_report(case_id, payload, staff.analyst))


def write_narrative(staff: Staff, sar: dict, text: str = NARRATIVE_STANDARD,
                    activity_start_date: Optional[str] = None,
                    activity_end_date: Optional[str] = None) -> dict:
    """Edit the narrative (OCC on the SAR's current version). Returns the SAR."""
    payload = update_narrative_payload(sar["version"], narrative=text)
    if activity_start_date is not None:
        payload["activity_start_date"] = activity_start_date
    if activity_end_date is not None:
        payload["activity_end_date"] = activity_end_date
    return get_success_data(api_client.update_sar_narrative(sar["id"], payload, staff.analyst))


def submit_sar_for_qa(staff: Staff, sar_id: str) -> dict:
    return get_success_data(api_client.submit_sar_for_qa(sar_id, staff.analyst))


def qa_review_sar(staff: Staff, sar_id: str, outcome: str,
                  notes: Optional[str] = None) -> dict:
    payload = sar_qa_review_payload(outcome)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.review_sar_qa(sar_id, payload, staff.qa))


def approve_sar(staff: Staff, sar_id: str) -> dict:
    return get_success_data(api_client.approve_sar(sar_id, staff.manager))


def drive_sar_to_approved(staff: Staff, case_id: str,
                          activity_start_date: str = "2026-03-10",
                          activity_end_date: str = "2026-04-10",
                          subject_unidentified: Optional[bool] = None,
                          narrative: str = NARRATIVE_STANDARD) -> dict:
    """DRAFT -> narrative -> IN_QA -> QA_PASSED -> APPROVED. Returns the SAR."""
    sar = create_sar_draft(staff, case_id, activity_start_date, activity_end_date,
                           subject_unidentified)
    sar = write_narrative(staff, sar, narrative)
    sar = submit_sar_for_qa(staff, sar["id"])
    sar = qa_review_sar(staff, sar["id"], "PASS")
    return approve_sar(staff, sar["id"])


class FiledSar(NamedTuple):
    case: dict
    sar: dict


def setup_filed_sar(staff: Staff, customer_id: str,
                    activity_start_date: str = "2026-03-10",
                    activity_end_date: str = "2026-04-10",
                    subject_unidentified: Optional[bool] = None,
                    narrative: str = NARRATIVE_STANDARD,
                    file_clock: Optional[str] = None) -> FiledSar:
    """Full pipeline: case -> SAR_IN_PROGRESS -> SAR draft -> APPROVED -> FILED.

    If file_clock is given, the logical clock is moved there before filing.
    Returns (case, sar) with the SAR in FILED state.
    """
    case = drive_case_to_sar_in_progress(staff, customer_id)
    sar = drive_sar_to_approved(staff, case["id"], activity_start_date,
                                activity_end_date, subject_unidentified, narrative)
    if file_clock is not None:
        set_clock(staff, file_clock)
    sar = get_success_data(api_client.file_sar(sar["id"], staff.manager))
    return FiledSar(case=case, sar=sar)


def first_continuing_review(staff: Staff, sar_id: str) -> dict:
    """Fetch the first continuing review of a SAR (list endpoint, first row)."""
    data, _meta = validate_paginated(
        api_client.list_continuing_reviews(sar_id, staff.analyst))
    assert data, f"Setup failed: no continuing review exists for SAR {sar_id}"
    return data[0]


def start_and_complete_review(staff: Staff, review_id: str, outcome: str) -> dict:
    """SCHEDULED -> IN_PROGRESS -> COMPLETED with the given outcome."""
    get_success_data(api_client.start_continuing_review(review_id, staff.analyst))
    return get_success_data(api_client.complete_continuing_review(
        review_id, complete_review_payload(outcome), staff.analyst))


# ---------------------------------------------------------------------------
# Law-enforcement inquiries
# ---------------------------------------------------------------------------

def create_le_inquiry(staff: Staff, subject_customer_id: str,
                      agency_name: str = "FBI", inquiry_reference: str = "LE-1") -> dict:
    return get_success_data(api_client.create_le_inquiry(
        create_le_inquiry_payload(
            subject_customer_id, agency_name=agency_name,
            inquiry_reference=inquiry_reference),
        staff.admin))


def link_inquiry_to_case(staff: Staff, inquiry_id: str, case_id: str) -> dict:
    return get_success_data(api_client.link_inquiry_to_case(
        inquiry_id, link_inquiry_payload(case_id), staff.admin))


def respond_and_close_inquiry(staff: Staff, inquiry_id: str) -> dict:
    get_success_data(api_client.respond_to_inquiry(
        inquiry_id, respond_inquiry_payload(), staff.manager))
    return get_success_data(api_client.close_inquiry(inquiry_id, staff.manager))


# ---------------------------------------------------------------------------
# 314(b) information sharing
# ---------------------------------------------------------------------------

def create_info_share(staff: Staff, subject_customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_info_share(
        create_info_share_payload(subject_customer_id, **overrides), staff.analyst))


# ---------------------------------------------------------------------------
# Account decisioning
# ---------------------------------------------------------------------------

def propose_decision(staff: Staff, account_id: str, decision: str = "EXIT",
                     rationale: str = "Confirmed structuring; relationship not retainable") -> dict:
    return get_success_data(api_client.propose_account_decision(
        account_id, propose_decision_payload(decision=decision, rationale=rationale),
        staff.analyst))


def propose_and_approve_decision(staff: Staff, account_id: str,
                                 decision: str = "EXIT",
                                 rationale: str = "Confirmed structuring; relationship not retainable") -> dict:
    proposed = propose_decision(staff, account_id, decision, rationale)
    return get_success_data(
        api_client.approve_account_decision(proposed["id"], staff.manager))


# ---------------------------------------------------------------------------
# Tier 4/5 composites: the heavy end-to-end chains shared by several tests
# ---------------------------------------------------------------------------

#: Three cash deposits totalling 1,200,000 cents — fires the default
#: 1,000,000-cent / 3-count threshold (PRD §3.3, both comparisons inclusive).
DEFAULT_FIRING_DEPOSITS = [
    (400_000, "2026-04-28T10:00:00Z", "US", "BRANCH"),
    (400_000, "2026-04-29T10:00:00Z", "US", "BRANCH"),
    (400_000, "2026-04-30T10:00:00Z", "US", "ATM"),
]


class AlertScenario(NamedTuple):
    scenario: dict
    threshold: dict
    customer: dict
    accounts: List[dict]
    alerts: List[dict]  # one NEW alert per account


def setup_alert_scenario(staff: Staff,
                         deposits_per_account: Optional[List[List[tuple]]] = None,
                         evaluated_at: Optional[str] = "2026-05-01T00:00:00Z",
                         scenario_overrides: Optional[dict] = None,
                         threshold_overrides: Optional[dict] = None) -> AlertScenario:
    """Scenario with an ACTIVE threshold plus one account per deposit set, each
    evaluated into an alert. `evaluated_at=None` evaluates at the current
    logical clock (move the clock beforehand to control the window end)."""
    if deposits_per_account is None:
        deposits_per_account = [list(DEFAULT_FIRING_DEPOSITS)]
    customer = create_customer(staff)
    accounts = [
        create_account(staff, customer["id"], f"ACC-{7100 + i}")
        for i in range(len(deposits_per_account))
    ]
    scenario, threshold = create_active_scenario(
        staff, **(scenario_overrides or {}), **(threshold_overrides or {}))
    alerts = []
    for account, deposits in zip(accounts, deposits_per_account):
        post_cash_deposits(staff, account["id"], deposits)
        alerts.append(generate_alert(staff, scenario["id"], account["id"], evaluated_at))
    return AlertScenario(scenario=scenario, threshold=threshold,
                         customer=customer, accounts=accounts, alerts=alerts)


def close_cases_no_sar(staff: Staff, customer_id: str, count: int) -> List[dict]:
    """Create and fully close `count` cases via the NO_SAR path (PRD §3.4).

    Each case traverses OPEN -> ASSIGNED -> INVESTIGATING -> PENDING_QA ->
    CLOSED, so each closed case counts as one completed work item for the
    monthly QA quota (PRD §3.10).
    """
    return [drive_case_to_closed_no_sar(staff, customer_id) for _ in range(count)]


class DeadlineBranchScenario(NamedTuple):
    customer: dict
    alert: dict
    case_identified: dict      # had the linked alert; SAR filed from it
    case_unidentified: dict    # no linked alerts
    sar_identified: dict       # FILED; deadline = detection + 30d
    sar_unidentified: dict     # DRAFT; subject_unidentified; deadline = detection + 60d
    sar_continuing: dict       # DRAFT continuing SAR; deadline = prior filed_at + 120d
    review: dict               # the COMPLETED first review of the filed SAR


def setup_deadline_branch_scenario(staff: Staff) -> DeadlineBranchScenario:
    """Build the three SAR-deadline branches of PRD §2.8 side by side.

    - SAR1 (identified subject, case has a LINKED alert created at the default
      clock 2026-05-01) is filed at 2026-05-05; deadline 2026-05-31.
    - SAR2 belongs to a second case with no alerts (detection = case created_at
      == 2026-05-01) and is drafted with subject_unidentified=true; deadline
      2026-06-30.
    - SAR3 is the continuing draft produced by completing SAR1's review with
      FILE_CONTINUING_SAR; deadline = 2026-05-05 + 120d = 2026-09-02.
    """
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-3001")
    scenario, _threshold = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (500_000, "2026-04-28T10:00:00Z", "US", "BRANCH"),
        (500_000, "2026-04-29T10:00:00Z", "US", "BRANCH"),
        (300_000, "2026-04-30T10:00:00Z", "US", "ATM"),
    ])
    alert = generate_alert(staff, scenario["id"], account["id"], "2026-05-01T00:00:00Z")
    triage_alert(staff, alert["id"])

    case_identified = create_case(staff, customer["id"], source_alert_id=alert["id"])
    case_unidentified = create_case(staff, customer["id"])
    get_success_data(api_client.link_alert_to_case(
        alert["id"], link_alert_payload(case_identified["id"]), staff.analyst))

    # Case 1: SAR_REQUIRED -> SAR1 -> approve -> file at 2026-05-05.
    assign_case(staff, case_identified["id"])
    case_identified = start_investigation(staff, case_identified["id"])
    case_identified = record_sar_decision(staff, case_identified, "SAR_REQUIRED")
    sar1 = drive_sar_to_approved(staff, case_identified["id"])
    set_clock(staff, "2026-05-05T00:00:00Z")
    sar1 = get_success_data(api_client.file_sar(sar1["id"], staff.manager))
    qa_review_case(staff, case_identified["id"], "PASS")

    review = first_continuing_review(staff, sar1["id"])
    review = start_and_complete_review(staff, review["id"], "FILE_CONTINUING_SAR")
    sar3 = get_success_data(
        api_client.get_sar_report(review["created_continuing_sar_id"], staff.analyst))

    # Case 2: unidentified-subject initial SAR.
    assign_case(staff, case_unidentified["id"])
    case_unidentified = start_investigation(staff, case_unidentified["id"])
    case_unidentified = record_sar_decision(
        staff, case_unidentified, "SAR_REQUIRED",
        rationale="Subject unidentified; continuing structured activity suspected")
    sar2 = create_sar_draft(staff, case_unidentified["id"], "2026-04-11",
                            "2026-05-01", subject_unidentified=True)

    return DeadlineBranchScenario(
        customer=customer, alert=alert,
        case_identified=get_success_data(api_client.get_case(case_identified["id"], staff.analyst)),
        case_unidentified=get_success_data(api_client.get_case(case_unidentified["id"], staff.analyst)),
        sar_identified=get_success_data(api_client.get_sar_report(sar1["id"], staff.analyst)),
        sar_unidentified=get_success_data(api_client.get_sar_report(sar2["id"], staff.analyst)),
        sar_continuing=sar3,
        review=get_success_data(api_client.get_continuing_review(review["id"], staff.analyst)),
    )


class ExitCascadeScenario(NamedTuple):
    customer: dict
    account: dict
    alert: dict          # UNDER_TRIAGE alert of the customer
    info_share: dict     # DRAFT 314(b) share of the customer
    decision: dict       # EXIT decision, APPROVED and not yet executed


def setup_exit_cascade_scenario(staff: Staff) -> ExitCascadeScenario:
    """Customer with exactly one account, one UNDER_TRIAGE alert, one DRAFT
    314(b) share, and an APPROVED EXIT decision awaiting execution (PRD §3.9)."""
    alert_scenario = setup_alert_scenario(staff)
    customer = alert_scenario.customer
    account = alert_scenario.accounts[0]
    alert = triage_alert(staff, alert_scenario.alerts[0]["id"])
    info_share = create_info_share(staff, customer["id"],
                                   certified_at="2026-04-01T00:00:00Z")
    decision = propose_and_approve_decision(staff, account["id"], "EXIT")
    return ExitCascadeScenario(customer=customer, account=account, alert=alert,
                               info_share=info_share, decision=decision)


class RiskCascadeScenario(NamedTuple):
    customer: dict
    account: dict
    sar_first: dict       # FILED at 2026-05-05 (risk 350 / MEDIUM — no cascade)
    case_second: dict     # SAR_IN_PROGRESS for the second filing
    sar_second: dict      # APPROVED at 2026-05-06, ready to file


def setup_risk_cascade_scenario(staff: Staff) -> RiskCascadeScenario:
    """One OPEN account; SAR1 already FILED (score 350, MEDIUM, account still
    OPEN); SAR2 APPROVED — filing it lifts the score to 600 and crosses the
    rating into HIGH, which must restrict the OPEN account (PRD §2.6, §3.5)."""
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-5001")
    first = setup_filed_sar(staff, customer["id"],
                            file_clock="2026-05-05T00:00:00Z")
    # Second, adjacent activity window (starts the day after SAR1's end).
    case_second = drive_case_to_sar_in_progress(
        staff, customer["id"], "Continued structuring after first filing")
    sar_second = drive_sar_to_approved(
        staff, case_second["id"], "2026-04-11", "2026-05-01",
        narrative=NARRATIVE_CONTINUING)
    set_clock(staff, "2026-05-06T00:00:00Z")
    return RiskCascadeScenario(
        customer=customer, account=account, sar_first=first.sar,
        case_second=case_second, sar_second=sar_second)

