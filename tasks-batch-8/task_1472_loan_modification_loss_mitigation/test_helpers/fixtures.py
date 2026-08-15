"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so nothing carries over). Setup
calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: Borrower is entity-backed, so every borrower-side call
uses make_borrower_headers(<actual Borrower.id>).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    FIXTURE_A_DOCS,
    FIXTURE_A_LOAN,
    FIXTURE_A_STATED_INCOME,
    FIXTURE_B_DOCS,
    FIXTURE_B_LOAN,
    FIXTURE_B_STATED_INCOME,
    FIXTURE_C_DOCS,
    FIXTURE_C_STATED_INCOME,
)
from .factories import (
    create_application_payload,
    create_borrower_payload,
    create_clock_payload,
    create_document_payload,
    create_escrow_analysis_payload,
    create_evaluation_payload,
    create_foreclosure_case_payload,
    create_loan_payload,
    create_modification_payload,
    create_payment_payload,
    create_program_option_payload,
    create_schedule_sale_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeal_reviewer_headers,
    make_borrower_headers,
    make_underwriter_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
OPS = TEST_USERS["ops_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
UW = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-call wrappers
# ---------------------------------------------------------------------------

def make_borrower(**overrides) -> dict:
    return get_success_data(
        api_client.create_borrower(create_borrower_payload(**overrides), ADMIN)
    )


def board_loan(borrower_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_loan(create_loan_payload(borrower_id, **overrides), ADMIN)
    )


def create_std_mod_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program_option(create_program_option_payload(**overrides), ADMIN)
    )


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), ADMIN))


def get_loan(loan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_loan(loan_id, headers or OPS))


def get_application(application_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_application(application_id, headers or UW))


def get_trial_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trial_plan(plan_id, headers or OPS))


def get_plan_payments(plan_id: str) -> list:
    data = get_success_data(api_client.list_trial_payments(plan_id, OPS))
    return sorted(data, key=lambda p: p["period_index"])


def get_denial_notice(notice_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_denial_notice(notice_id, headers or UW))


def get_foreclosure_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_foreclosure_case(case_id, headers or COUNSEL))


def get_modification(modification_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_modification(modification_id, headers or OPS))


def get_escrow_analysis(analysis_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_escrow_analysis(analysis_id, headers or OPS))


# ---------------------------------------------------------------------------
# Tier 1: intake building blocks
# ---------------------------------------------------------------------------

def submit_application(loan: dict, borrower_id: str,
                       hardship_type: str = "INCOME_REDUCTION",
                       stated_income: int = FIXTURE_A_STATED_INCOME) -> dict:
    # OCC guard (PRD 2.5): the client must supply the loan's CURRENT version.
    # Other flows (e.g. foreclosure referral, PRD 3.9) legitimately bump the
    # loan version after boarding, so re-read the loan instead of trusting a
    # possibly stale dict.
    current_version = get_loan(loan["id"])["version"]
    payload = create_application_payload(
        expected_loan_version=current_version,
        hardship_type=hardship_type,
        stated_monthly_income_cents=stated_income,
    )
    return get_success_data(
        api_client.create_application(loan["id"], payload, make_borrower_headers(borrower_id))
    )


def acknowledge(application_id: str) -> dict:
    return get_success_data(api_client.acknowledge_application(application_id, AGENT))


def submit_document(application_id: str, borrower_id: str, doc_type: str, **fields) -> dict:
    payload = create_document_payload(doc_type, **fields)
    return get_success_data(
        api_client.submit_document(
            application_id, payload, make_borrower_headers(borrower_id)
        )
    )


def accept_document(document_id: str) -> dict:
    return get_success_data(api_client.accept_document(document_id, AGENT))


def reject_document(document_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.reject_document(document_id, {"rejection_reason": reason}, AGENT)
    )


def submit_and_accept_documents(application_id: str, borrower_id: str,
                                docs: list, complete_at: str = None) -> list:
    """Submit every (doc_type, fields) spec, then accept them in order.

    When ``complete_at`` is given, the logical clock is pinned to that instant
    just before the final accept so the application's first completion anchor
    lands exactly there.
    """
    doc_ids = []
    for doc_type, fields in docs:
        doc = submit_document(application_id, borrower_id, doc_type, **fields)
        doc_ids.append(doc["id"])
    for i, doc_id in enumerate(doc_ids):
        if complete_at is not None and i == len(doc_ids) - 1:
            set_clock(complete_at)
        accept_document(doc_id)
    return doc_ids


def run_waterfall(application_id: str, underwriter_user_id: str = "uw_1") -> dict:
    """Fetch the application's current version and run the evaluation (OCC)."""
    app = get_application(application_id)
    payload = create_evaluation_payload(app["version"])
    return get_success_data(
        api_client.run_evaluation(
            application_id, payload, make_underwriter_headers(underwriter_user_id)
        )
    )


def plan_for_application(application_id: str) -> dict:
    plans = get_success_data(
        api_client.list_trial_plans(OPS, params={"application_id": application_id})
    )
    assert len(plans) == 1, f"expected exactly one trial plan, got {len(plans)}"
    return plans[0]


# ---------------------------------------------------------------------------
# Tier 2: complete applications (per-economics fixtures)
# ---------------------------------------------------------------------------

def setup_complete_application(economics: str = "A", complete_at: str = None,
                               hardship_type: str = "INCOME_REDUCTION",
                               with_program: bool = True,
                               loan_overrides: dict = None,
                               program_overrides: dict = None,
                               docs: list = None) -> dict:
    """Borrower + loan + (optional) STD_MOD program + application walked to
    COMPLETE_PACKAGE via document acceptance.

    economics: "A" (offer via rate reduction), "B" (forbearance solves to
    target), "C" (denial economics on fixture B terms).
    """
    econ = {
        "A": (FIXTURE_A_LOAN, FIXTURE_A_STATED_INCOME, FIXTURE_A_DOCS),
        "B": (FIXTURE_B_LOAN, FIXTURE_B_STATED_INCOME, FIXTURE_B_DOCS),
        "C": (FIXTURE_B_LOAN, FIXTURE_C_STATED_INCOME, FIXTURE_C_DOCS),
    }[economics]
    loan_fields, stated_income, doc_specs = econ
    if docs is not None:
        doc_specs = docs
    loan_fields = dict(loan_fields)
    if loan_overrides:
        loan_fields.update(loan_overrides)

    borrower = make_borrower()
    loan = board_loan(borrower["id"], **loan_fields)
    program = (
        create_std_mod_program(**(program_overrides or {})) if with_program else None
    )
    application = submit_application(
        loan, borrower["id"], hardship_type=hardship_type, stated_income=stated_income
    )
    acknowledge(application["id"])
    submit_and_accept_documents(
        application["id"], borrower["id"], doc_specs, complete_at=complete_at
    )
    application = get_application(application["id"])
    assert application["status"] == "COMPLETE_PACKAGE", (
        f"setup failed: application is {application['status']}, expected COMPLETE_PACKAGE"
    )
    return {
        "borrower": borrower,
        "loan": get_loan(loan["id"]),
        "program": program,
        "application": application,
    }


# ---------------------------------------------------------------------------
# Tier 3: evaluation / offer / trial lifecycle
# ---------------------------------------------------------------------------

def setup_offered_plan(economics: str = "A", complete_at: str = None,
                       eval_at: str = None, **kwargs) -> dict:
    """COMPLETE_PACKAGE application + OFFER evaluation + OFFERED plan."""
    scenario = setup_complete_application(
        economics=economics, complete_at=complete_at, **kwargs
    )
    if eval_at is not None:
        set_clock(eval_at)
    evaluation = run_waterfall(scenario["application"]["id"])
    assert evaluation["result"] == "OFFER", (
        f"setup failed: evaluation result is {evaluation['result']}, expected OFFER"
    )
    scenario["evaluation"] = evaluation
    scenario["plan"] = plan_for_application(scenario["application"]["id"])
    scenario["payments"] = get_plan_payments(scenario["plan"]["id"])
    scenario["application"] = get_application(scenario["application"]["id"])
    return scenario


def setup_active_trial(economics: str = "A", complete_at: str = None,
                       eval_at: str = None, **kwargs) -> dict:
    """OFFERED plan accepted by the borrower -> plan ACTIVE, app TRIAL_ACTIVE."""
    scenario = setup_offered_plan(
        economics=economics, complete_at=complete_at, eval_at=eval_at, **kwargs
    )
    plan = get_success_data(
        api_client.accept_trial_plan(
            scenario["plan"]["id"], make_borrower_headers(scenario["borrower"]["id"])
        )
    )
    scenario["plan"] = plan
    scenario["payments"] = get_plan_payments(plan["id"])
    scenario["application"] = get_application(scenario["application"]["id"])
    return scenario


def pay_on_time(payment: dict, borrower_id: str, use_due_date_clock: bool = True) -> dict:
    """Pay the scheduled amount; pins the clock to the due date by default so
    the payment is exactly on time (inclusive boundary)."""
    if use_due_date_clock:
        set_clock(f"{payment['due_date']}T00:00:00Z")
    return get_success_data(
        api_client.pay_trial_payment(
            payment["id"],
            create_payment_payload(payment["scheduled_amount_cents"]),
            make_borrower_headers(borrower_id),
        )
    )


def pay_plan_in_full(scenario: dict, use_due_date_clock: bool = True) -> dict:
    """Resolve all three scheduled payments on time; completes the plan."""
    for payment in scenario["payments"]:
        pay_on_time(payment, scenario["borrower"]["id"], use_due_date_clock)
    scenario["plan"] = get_trial_plan(scenario["plan"]["id"])
    scenario["application"] = get_application(scenario["application"]["id"])
    scenario["loan"] = get_loan(scenario["loan"]["id"])
    return scenario


def setup_completed_trial(economics: str = "A", complete_at: str = None,
                          eval_at: str = None, **kwargs) -> dict:
    """Full trial: 3 x PAID_ON_TIME -> plan COMPLETED, app TRIAL_PASSED,
    loan workout MOD_PENDING with suspense applied."""
    scenario = setup_active_trial(
        economics=economics, complete_at=complete_at, eval_at=eval_at, **kwargs
    )
    scenario = pay_plan_in_full(scenario)
    assert scenario["plan"]["status"] == "COMPLETED", (
        f"setup failed: plan is {scenario['plan']['status']}, expected COMPLETED"
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: permanent modification lifecycle
# ---------------------------------------------------------------------------

def create_modification_for(scenario: dict) -> dict:
    return get_success_data(
        api_client.create_modification(
            scenario["loan"]["id"],
            create_modification_payload(scenario["plan"]["id"]),
            OPS,
        )
    )


def setup_modification(status: str = "DRAFT", economics: str = "B",
                       record_at: str = None, **kwargs) -> dict:
    """Completed trial + modification walked to the requested state.

    status: DRAFT | DOCS_SENT | SIGNED | RECORDED.
    """
    scenario = setup_completed_trial(economics=economics, **kwargs)
    modification = create_modification_for(scenario)
    scenario["modification"] = modification
    if status in ("DOCS_SENT", "SIGNED", "RECORDED"):
        get_success_data(api_client.send_modification_docs(modification["id"], OPS))
    if status in ("SIGNED", "RECORDED"):
        get_success_data(
            api_client.sign_modification(
                modification["id"], make_borrower_headers(scenario["borrower"]["id"])
            )
        )
    if status == "RECORDED":
        if record_at is not None:
            set_clock(record_at)
        scenario["modification"] = get_success_data(
            api_client.record_modification(modification["id"], OPS)
        )
        scenario["loan"] = get_loan(scenario["loan"]["id"])
        scenario["application"] = get_application(scenario["application"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: denial / appeal / foreclosure composites
# ---------------------------------------------------------------------------

def refer_and_schedule(scenario: dict, sale_date: str,
                       county: str = "Fulton", docket_number: str = "FC-0001") -> dict:
    """Refer the loan to foreclosure and schedule a sale (call BEFORE the
    application exists so no dual-tracking gate fires)."""
    case = get_success_data(
        api_client.create_foreclosure_case(
            scenario["loan"]["id"],
            create_foreclosure_case_payload(county=county, docket_number=docket_number),
            COUNSEL,
        )
    )
    case = get_success_data(
        api_client.schedule_sale(
            case["id"], create_schedule_sale_payload(sale_date), COUNSEL
        )
    )
    scenario["case"] = case
    return scenario


def refer_only(scenario: dict, county: str = "Maricopa",
               docket_number: str = "FC-0002") -> dict:
    """Refer the loan to foreclosure without scheduling a sale."""
    case = get_success_data(
        api_client.create_foreclosure_case(
            scenario["loan"]["id"],
            create_foreclosure_case_payload(county=county, docket_number=docket_number),
            COUNSEL,
        )
    )
    scenario["case"] = case
    return scenario


def setup_offered_plan_with_scheduled_sale(sale_date: str,
                                           economics: str = "A",
                                           county: str = "Clark",
                                           docket_number: str = "FC-800",
                                           eval_at: str = None) -> dict:
    """Foreclosure case referred and sale scheduled BEFORE any application
    exists, then the application is walked to EVALUATED_OFFER (OFFERED plan)."""
    borrower = make_borrower()
    econ = {"A": (FIXTURE_A_LOAN, FIXTURE_A_STATED_INCOME, FIXTURE_A_DOCS)}[economics]
    loan_fields, stated_income, doc_specs = econ
    loan = board_loan(borrower["id"], **dict(loan_fields))
    program = create_std_mod_program()
    scenario = {"borrower": borrower, "loan": loan, "program": program}
    refer_and_schedule(scenario, sale_date, county=county, docket_number=docket_number)
    application = submit_application(
        loan, borrower["id"], stated_income=stated_income
    )
    acknowledge(application["id"])
    submit_and_accept_documents(application["id"], borrower["id"], doc_specs)
    if eval_at is not None:
        set_clock(eval_at)
    evaluation = run_waterfall(application["id"])
    assert evaluation["result"] == "OFFER", (
        f"setup failed: evaluation result is {evaluation['result']}, expected OFFER"
    )
    scenario["evaluation"] = evaluation
    scenario["plan"] = plan_for_application(application["id"])
    scenario["payments"] = get_plan_payments(scenario["plan"]["id"])
    scenario["application"] = get_application(application["id"])
    scenario["loan"] = get_loan(loan["id"])
    return scenario


def setup_denial(sale_date: str = None, complete_at: str = None,
                 denied_at: str = "2026-08-10T00:00:00Z",
                 underwriter_user_id: str = "uw_1") -> dict:
    """Fixture C economics -> DENIAL evaluation -> ISSUED denial notice.

    When ``sale_date`` is given, a foreclosure case is referred and the sale
    scheduled BEFORE the application is submitted (so referral/scheduling
    gates pass), exercising the appeal-eligibility rule against it.
    """
    borrower = make_borrower()
    loan = board_loan(borrower["id"], **FIXTURE_B_LOAN)
    program = create_std_mod_program()
    scenario = {"borrower": borrower, "loan": loan, "program": program}

    if sale_date is not None:
        refer_and_schedule(scenario, sale_date)

    application = submit_application(
        loan, borrower["id"], hardship_type="UNEMPLOYMENT",
        stated_income=FIXTURE_C_STATED_INCOME,
    )
    acknowledge(application["id"])
    submit_and_accept_documents(
        application["id"], borrower["id"], FIXTURE_C_DOCS, complete_at=complete_at
    )
    set_clock(denied_at)
    evaluation = run_waterfall(application["id"], underwriter_user_id=underwriter_user_id)
    assert evaluation["result"] == "DENIAL", (
        f"setup failed: evaluation result is {evaluation['result']}, expected DENIAL"
    )
    scenario["evaluation"] = evaluation
    scenario["application"] = get_application(application["id"])
    scenario["loan"] = get_loan(loan["id"])
    notices = get_success_data(
        api_client.list_application_denial_notices(application["id"], UW)
    )
    assert len(notices) == 1, f"setup failed: expected 1 denial notice, got {len(notices)}"
    scenario["notice"] = notices[0]
    return scenario


def setup_appeal(scenario: dict, appeal_at: str = "2026-08-12T00:00:00Z",
                 grounds: str = "please review") -> dict:
    """File a borrower appeal against the scenario's ISSUED denial notice."""
    set_clock(appeal_at)
    appeal = get_success_data(
        api_client.submit_appeal(
            scenario["notice"]["id"],
            {"grounds": grounds},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
    )
    scenario["appeal"] = appeal
    scenario["notice"] = get_denial_notice(scenario["notice"]["id"])
    scenario["application"] = get_application(scenario["application"]["id"])
    return scenario


def decide(scenario: dict, outcome: str, reviewer_user_id: str = "rev_1") -> dict:
    return get_success_data(
        api_client.decide_appeal(
            scenario["appeal"]["id"],
            {"outcome": outcome},
            make_appeal_reviewer_headers(reviewer_user_id),
        )
    )
