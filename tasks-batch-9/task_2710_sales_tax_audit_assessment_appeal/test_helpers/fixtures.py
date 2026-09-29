"""Composite setup helpers.

Every helper builds its state from scratch through PRD endpoints only: the
harness restarts the server and empties the database before each test, so
nothing may be carried over between tests.

All helpers use the lenient `get_success_data` validator so that a broken
precondition surfaces as a clear setup failure rather than a confusing
assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPEALS_OFFICER_USER_ID,
    BASE_LIMITATION_DAYS,
    COLLECTIONS_AGENT_USER_ID,
    DEFAULT_LOGICAL_CLOCK_DATE,
    LEAD_AUDITOR_USER_ID,
    OTHER_APPEALS_OFFICER_USER_ID,
    SUPERVISOR_USER_ID,
    TRIBUNAL_JUDGE_USER_ID,
    add_days,
    clock_instant,
    purchase_price_for_use_tax,
)

DEFAULT_CLOCK_DATE = DEFAULT_LOGICAL_CLOCK_DATE
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_appeals_officer_headers,
    make_collections_agent_headers,
    make_supervisor_headers,
    make_taxpayer_headers,
    make_tribunal_judge_headers,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]
TRIBUNAL = TEST_USERS["tax_tribunal_judge_headers"]

DEFAULT_SCOPE_START = "2026-01-01"
DEFAULT_SCOPE_END = "2026-06-30"
DEFAULT_POPULATION_BASE_CENTS = 10_000_000
DEFAULT_POPULATION_UNITS = 100
DEFAULT_INVOICE_DATE = "2026-03-02"
DEFAULT_INVOICE_AMOUNT_CENTS = 100_000


# --- Logical clock ---------------------------------------------------------

def set_clock(to_iso8601):
    """Move the logical clock to an explicit instant."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), SUPERVISOR)
    )


def set_clock_date(day):
    """Move the logical clock to midnight UTC on the given calendar date."""
    set_clock(clock_instant(day))
    return day


# --- Permit holders, information returns, projects and leads ---------------

def register_taxpayer(**overrides):
    return get_success_data(
        api_client.create_taxpayer(f.create_taxpayer_payload(**overrides), ANALYST)
    )


def register_taxpayers(count, **overrides):
    return [register_taxpayer(**overrides) for _ in range(count)]


def load_information_return(taxpayer_id, **overrides):
    return get_success_data(
        api_client.create_information_return(
            f.create_information_return_payload(taxpayer_id, **overrides), ANALYST
        )
    )


def rescore_screening(taxpayer_id):
    return get_success_data(api_client.rescore_screening(taxpayer_id, ANALYST))


def read_taxpayer(taxpayer_id, headers=None):
    return get_success_data(api_client.get_taxpayer(taxpayer_id, headers or ANALYST))


def create_industry_project(**overrides):
    return get_success_data(
        api_client.create_industry_project(
            f.create_industry_project_payload(**overrides), ANALYST
        )
    )


def read_industry_project(project_id):
    return get_success_data(api_client.get_industry_project(project_id, ANALYST))


def run_selection(project_id):
    """Start a scoring run. Callers read the resulting leads back through GET."""
    return get_success_data(api_client.create_selection_run(project_id, ANALYST))


def list_leads(**params):
    return get_success_data(api_client.list_audit_leads(ANALYST, params=params or None))


def read_lead(lead_id):
    return get_success_data(api_client.get_audit_lead(lead_id, ANALYST))


def decline_lead(lead_id, **overrides):
    return get_success_data(
        api_client.decline_audit_lead(lead_id, f.decline_lead_payload(**overrides), SUPERVISOR)
    )


def convert_lead(lead_id, lead_auditor_user_id=LEAD_AUDITOR_USER_ID, audit_type=...):
    """Convert a SELECTED lead. The response is the newly created audit."""
    return get_success_data(
        api_client.convert_audit_lead(
            lead_id, f.convert_lead_payload(lead_auditor_user_id, audit_type), SUPERVISOR
        )
    )


# --- Audits ---------------------------------------------------------------

def read_audit(audit_id, headers=None):
    return get_success_data(api_client.get_audit(audit_id, headers or SUPERVISOR))


def scope_audit(audit_id, scope_period_start, scope_period_end, audit_type="DESK"):
    return get_success_data(
        api_client.scope_audit(
            audit_id,
            f.scope_audit_payload(scope_period_start, scope_period_end, audit_type),
            AUDITOR,
        )
    )


def project_sample(audit_id):
    return get_success_data(api_client.project_sample(audit_id, AUDITOR))


def close_fieldwork(audit_id, closing_user_id=SUPERVISOR_USER_ID, fraud_indicator=...):
    return get_success_data(
        api_client.close_fieldwork(
            audit_id,
            f.close_fieldwork_payload(fraud_indicator),
            make_supervisor_headers(closing_user_id),
        )
    )


def reopen_fieldwork(audit_id, **overrides):
    return get_success_data(
        api_client.reopen_fieldwork(audit_id, f.reopen_fieldwork_payload(**overrides), SUPERVISOR)
    )


def abandon_audit(audit_id, **overrides):
    return get_success_data(
        api_client.abandon_audit(audit_id, f.abandon_audit_payload(**overrides), SUPERVISOR)
    )


def liability_preview(audit_id):
    return get_success_data(api_client.get_liability_preview(audit_id, SUPERVISOR))


# --- Statute waivers ------------------------------------------------------

def draft_waiver(audit_id, covers_period_end, extended_to_date, **overrides):
    return get_success_data(
        api_client.create_statute_waiver(
            f.create_statute_waiver_payload(
                audit_id, covers_period_end, extended_to_date, **overrides
            ),
            AUDITOR,
        )
    )


def execute_waiver(waiver_id, taxpayer_id, signed_date):
    return get_success_data(
        api_client.execute_statute_waiver(
            waiver_id, f.execute_waiver_payload(signed_date), make_taxpayer_headers(taxpayer_id)
        )
    )


def void_waiver(waiver_id, **overrides):
    return get_success_data(
        api_client.void_statute_waiver(waiver_id, f.void_waiver_payload(**overrides), SUPERVISOR)
    )


# --- Sampling agreements --------------------------------------------------

def default_strata(
    scope_period_start=DEFAULT_SCOPE_START,
    scope_period_end=DEFAULT_SCOPE_END,
    population_base_amount_cents=DEFAULT_POPULATION_BASE_CENTS,
    population_unit_count=DEFAULT_POPULATION_UNITS,
):
    """One stratum tiling the whole scope: half-open, last end is scope end + 1 day."""
    return [
        f.stratum(
            scope_period_start,
            add_days(scope_period_end, 1),
            population_base_amount_cents,
            population_unit_count,
        )
    ]


def propose_agreement(audit, strata=None, **overrides):
    strata = strata if strata is not None else default_strata(
        audit["scope_period_start"], audit["scope_period_end"]
    )
    return get_success_data(
        api_client.create_sampling_agreement(
            f.create_sampling_agreement_payload(
                audit["id"], audit["version"], strata, **overrides
            ),
            AUDITOR,
        )
    )


def counter_agreement(agreement_id, taxpayer_id, **overrides):
    return get_success_data(
        api_client.counter_sampling_agreement(
            agreement_id,
            f.counter_agreement_payload(**overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def revise_agreement(agreement_id, **overrides):
    return get_success_data(
        api_client.revise_sampling_agreement(
            agreement_id, f.revise_agreement_payload(**overrides), AUDITOR
        )
    )


def agree_agreement(agreement_id, taxpayer_id, **overrides):
    return get_success_data(
        api_client.agree_sampling_agreement(
            agreement_id,
            f.agree_agreement_payload(**overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def read_agreement(agreement_id):
    return get_success_data(api_client.get_sampling_agreement(agreement_id, AUDITOR))


# --- Findings -------------------------------------------------------------

def draw_sample_unit(
    agreement_id,
    stratum_index=0,
    invoice_date=DEFAULT_INVOICE_DATE,
    invoice_amount_cents=DEFAULT_INVOICE_AMOUNT_CENTS,
    **overrides,
):
    return get_success_data(
        api_client.create_sample_unit(
            f.create_sample_unit_payload(
                agreement_id, stratum_index, invoice_date, invoice_amount_cents, **overrides
            ),
            AUDITOR,
        )
    )


def redetermine_sample_unit(sample_unit_id, error_class, **overrides):
    return get_success_data(
        api_client.redetermine_sample_unit(
            sample_unit_id,
            f.redetermine_sample_unit_payload(error_class, **overrides),
            AUDITOR,
        )
    )


def read_sample_unit(sample_unit_id):
    return get_success_data(api_client.get_sample_unit(sample_unit_id, AUDITOR))


def file_certificate(audit_id, **overrides):
    return get_success_data(
        api_client.create_exemption_certificate(
            f.create_exemption_certificate_payload(audit_id, **overrides), AUDITOR
        )
    )


def review_certificate(certificate_id, determination, **overrides):
    return get_success_data(
        api_client.review_exemption_certificate(
            certificate_id, f.review_certificate_payload(determination, **overrides), AUDITOR
        )
    )


def cure_certificate(certificate_id, taxpayer_id, **overrides):
    return get_success_data(
        api_client.cure_exemption_certificate(
            certificate_id,
            f.cure_certificate_payload(**overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def read_certificate(certificate_id):
    return get_success_data(api_client.get_exemption_certificate(certificate_id, AUDITOR))


def record_purchase(audit_id, invoice_date, purchase_price_cents, **overrides):
    return get_success_data(
        api_client.create_use_tax_purchase(
            f.create_use_tax_purchase_payload(
                audit_id, invoice_date, purchase_price_cents, **overrides
            ),
            AUDITOR,
        )
    )


def reclassify_purchase(purchase_id, asset_class, **overrides):
    return get_success_data(
        api_client.reclassify_use_tax_purchase(
            purchase_id, f.reclassify_use_tax_purchase_payload(asset_class, **overrides), AUDITOR
        )
    )


def read_purchase(purchase_id):
    return get_success_data(api_client.get_use_tax_purchase(purchase_id, AUDITOR))


# --- Assessments, ledger, appeals and collection --------------------------

def draft_assessment(audit_id, **overrides):
    return get_success_data(
        api_client.create_assessment(f.create_assessment_payload(audit_id, **overrides), SUPERVISOR)
    )


def recompute_assessment(assessment_id):
    return get_success_data(api_client.recompute_assessment(assessment_id, SUPERVISOR))


def issue_assessment(assessment_id, notice_mailed_date):
    return get_success_data(
        api_client.issue_assessment(
            assessment_id, f.issue_assessment_payload(notice_mailed_date), SUPERVISOR
        )
    )


def read_assessment(assessment_id, headers=None):
    return get_success_data(api_client.get_assessment(assessment_id, headers or SUPERVISOR))


def abate_penalty(assessment_id, abatement_factors):
    return get_success_data(
        api_client.abate_penalty(
            assessment_id, f.abate_penalty_payload(abatement_factors), SUPERVISOR
        )
    )


def finalize_assessment(assessment_id):
    return get_success_data(api_client.finalize_assessment(assessment_id, SUPERVISOR))


def refer_to_collections(assessment_id, **overrides):
    return get_success_data(
        api_client.refer_to_collections(
            assessment_id, f.collection_referral_payload(**overrides), COLLECTIONS
        )
    )


def post_payment_adjustment(assessment_id, expected_assessment_version, amount_cents):
    return get_success_data(
        api_client.create_assessment_adjustment(
            f.create_assessment_adjustment_payload(
                assessment_id, expected_assessment_version, amount_cents
            ),
            SUPERVISOR,
        )
    )


def reverse_adjustment(adjustment_id, **overrides):
    return get_success_data(
        api_client.reverse_assessment_adjustment(
            adjustment_id, f.reverse_adjustment_payload(**overrides), SUPERVISOR
        )
    )


def list_adjustments(**params):
    return get_success_data(
        api_client.list_assessment_adjustments(SUPERVISOR, params=params or None)
    )


def file_protest(assessment_id, taxpayer_id, forum="INFORMAL_CONFERENCE", **overrides):
    return get_success_data(
        api_client.create_appeal_proceeding(
            f.create_appeal_proceeding_payload(assessment_id, forum=forum, **overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def decide_proceeding(proceeding_id, outcome, officer_user_id=APPEALS_OFFICER_USER_ID, **overrides):
    return get_success_data(
        api_client.decide_appeal_proceeding(
            proceeding_id,
            f.decision_payload(outcome, **overrides),
            make_appeals_officer_headers(officer_user_id),
        )
    )


def decide_tribunal_proceeding(proceeding_id, outcome, judge_user_id=TRIBUNAL_JUDGE_USER_ID, **overrides):
    return get_success_data(
        api_client.decide_appeal_proceeding(
            proceeding_id,
            f.decision_payload(outcome, **overrides),
            make_tribunal_judge_headers(judge_user_id),
        )
    )


def read_proceeding(proceeding_id):
    return get_success_data(api_client.get_appeal_proceeding(proceeding_id, SUPERVISOR))


def request_installment_plan(assessment_id, monthly_installment_cents, term_months, **overrides):
    return get_success_data(
        api_client.create_payment_arrangement(
            f.installment_plan_payload(
                assessment_id, monthly_installment_cents, term_months, **overrides
            ),
            COLLECTIONS,
        )
    )


def request_offer_in_compromise(assessment_id, offer_amount_cents, **overrides):
    return get_success_data(
        api_client.create_payment_arrangement(
            f.offer_in_compromise_payload(assessment_id, offer_amount_cents, **overrides),
            COLLECTIONS,
        )
    )


def approve_arrangement(arrangement_id, agent_user_id=COLLECTIONS_AGENT_USER_ID):
    return get_success_data(
        api_client.approve_payment_arrangement(
            arrangement_id, make_collections_agent_headers(agent_user_id)
        )
    )


def pay_arrangement(arrangement_id, amount_cents):
    return get_success_data(
        api_client.create_arrangement_payment(
            arrangement_id, f.arrangement_payment_payload(amount_cents), COLLECTIONS
        )
    )


def default_arrangement(arrangement_id, **overrides):
    return get_success_data(
        api_client.default_payment_arrangement(
            arrangement_id, f.default_arrangement_payload(**overrides), COLLECTIONS
        )
    )


def read_arrangement(arrangement_id):
    return get_success_data(api_client.get_payment_arrangement(arrangement_id, COLLECTIONS))


# ==========================================================================
# Composite chains
# ==========================================================================

DEFAULT_TAX_DEFICIENCY_CENTS = 1_000_000


def leads_by_rank(leads):
    """Leads ordered by their 1-based rank_position."""
    return sorted(leads, key=lambda lead: lead["rank_position"])


def setup_project_with_scored_leads(taxpayer_specs=None, project_overrides=None, run=True):
    """Register permit holders in one industry, open a project and score it.

    Returns a context carrying `taxpayers`, `project` and `leads`.
    """
    specs = taxpayer_specs if taxpayer_specs is not None else [{}]
    taxpayers = [register_taxpayer(**spec) for spec in specs]
    project = create_industry_project(**(project_overrides or {}))
    if run:
        run_selection(project["id"])
        project = read_industry_project(project["id"])
    leads = list_leads(industry_project_id=project["id"])
    return {
        "taxpayers": taxpayers,
        "taxpayer": taxpayers[0] if taxpayers else None,
        "project": project,
        "leads": leads,
    }


def setup_converted_audit(
    taxpayer_overrides=None,
    project_overrides=None,
    lead_auditor_user_id=LEAD_AUDITOR_USER_ID,
    audit_type=...,
):
    """Permit holder + project + scoring run + conversion. Audit lands in PLANNED."""
    ctx = setup_project_with_scored_leads([taxpayer_overrides or {}], project_overrides)
    selected = [lead for lead in ctx["leads"] if lead["status"] == "SELECTED"]
    assert selected, "Setup failed: the scoring run selected no lead to convert"
    lead = selected[0]
    audit = convert_lead(lead["id"], lead_auditor_user_id, audit_type)
    ctx.update(
        {
            "lead": lead,
            "audit": audit,
            "lead_auditor_user_id": lead_auditor_user_id,
            "taxpayer_headers": make_taxpayer_headers(ctx["taxpayer"]["id"]),
        }
    )
    return ctx


def setup_scoped_audit(
    scope_period_start=DEFAULT_SCOPE_START,
    scope_period_end=DEFAULT_SCOPE_END,
    audit_type="DESK",
    **kwargs,
):
    """Audit scoped over a known period, so base_statute_expiry_date is fixed."""
    ctx = setup_converted_audit(**kwargs)
    ctx["audit"] = scope_audit(
        ctx["audit"]["id"], scope_period_start, scope_period_end, audit_type
    )
    return ctx


def setup_proposed_methodology(
    methodology="RATIO_ESTIMATION",
    confidence_level_bp=9_500,
    minimum_sample_size=1,
    strata=None,
    **kwargs,
):
    """Scoped audit with one PROPOSED sampling agreement tiling the whole scope."""
    ctx = setup_scoped_audit(**kwargs)
    ctx["agreement"] = propose_agreement(
        ctx["audit"],
        strata=strata,
        methodology=methodology,
        confidence_level_bp=confidence_level_bp,
        minimum_sample_size=minimum_sample_size,
    )
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def setup_agreed_methodology(**kwargs):
    """Agreed methodology, which opens fieldwork on the audit."""
    ctx = setup_proposed_methodology(**kwargs)
    ctx["agreement"] = agree_agreement(ctx["agreement"]["id"], ctx["taxpayer"]["id"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def setup_audit_with_findings(
    tax_deficiency_cents=DEFAULT_TAX_DEFICIENCY_CENTS,
    sample_unit_specs=None,
    purchase_specs=None,
    run_projection=True,
    **kwargs,
):
    """Fieldwork audit carrying a determined sample and its use-tax findings.

    By default the sample carries one NO_ERROR unit (so the projection is zero)
    and one CONSUMABLE purchase whose use tax is exactly `tax_deficiency_cents`,
    which makes the assessed deficiency of downstream fixtures predictable.
    """
    ctx = setup_agreed_methodology(**kwargs)
    audit = ctx["audit"]
    specs = sample_unit_specs if sample_unit_specs is not None else [{"error_class": "NO_ERROR"}]
    ctx["sample_units"] = [draw_sample_unit(ctx["agreement"]["id"], **spec) for spec in specs]
    if purchase_specs is None:
        purchase_specs = (
            [
                {
                    "invoice_date": audit["scope_period_start"],
                    "purchase_price_cents": purchase_price_for_use_tax(tax_deficiency_cents),
                    "asset_class": "CONSUMABLE",
                }
            ]
            if tax_deficiency_cents
            else []
        )
    ctx["purchases"] = [record_purchase(audit["id"], **spec) for spec in purchase_specs]
    ctx["audit"] = project_sample(audit["id"]) if run_projection else read_audit(audit["id"])
    return ctx


def setup_review_complete_audit(fraud_indicator=..., closing_user_id=SUPERVISOR_USER_ID, **kwargs):
    """Fieldwork closed by a supervisor who is not the audit's lead auditor."""
    ctx = setup_audit_with_findings(**kwargs)
    ctx["audit"] = close_fieldwork(ctx["audit"]["id"], closing_user_id, fraud_indicator)
    return ctx


def setup_draft_assessment(draft_clock_day=None, **kwargs):
    """Draft notice. The clock defaults to the scope's last day, so interest is zero."""
    ctx = setup_review_complete_audit(**kwargs)
    day = draft_clock_day or ctx["audit"]["scope_period_end"]
    ctx["clock_date"] = set_clock_date(day)
    ctx["assessment"] = draft_assessment(ctx["audit"]["id"])
    return ctx


def setup_issued_assessment(issue_clock_day=None, **kwargs):
    """Issued notice: notice_mailed_date is the logical clock date at issuance."""
    ctx = setup_draft_assessment(**kwargs)
    if issue_clock_day and issue_clock_day != ctx["clock_date"]:
        ctx["clock_date"] = set_clock_date(issue_clock_day)
    ctx["assessment"] = issue_assessment(ctx["assessment"]["id"], ctx["clock_date"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def setup_final_assessment(**kwargs):
    """Issued notice finalized after the protest window closes, closing the audit."""
    ctx = setup_issued_assessment(**kwargs)
    ctx["clock_date"] = set_clock_date(
        add_days(ctx["assessment"]["protest_deadline_date"], 1)
    )
    ctx["assessment"] = finalize_assessment(ctx["assessment"]["id"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    ctx["taxpayer"] = read_taxpayer(ctx["taxpayer"]["id"])
    return ctx


def open_second_audit_for_taxpayer(ctx, project_overrides=None):
    """Once the holder's earlier audit is CLOSED, score and convert it again."""
    project = create_industry_project(**(project_overrides or {}))
    run_selection(project["id"])
    leads = list_leads(
        industry_project_id=project["id"], taxpayer_id=ctx["taxpayer"]["id"], status="SELECTED"
    )
    assert leads, "Setup failed: the permit holder was not selected a second time"
    return convert_lead(leads[0]["id"])


def stale_the_findings(ctx, purchase_price_cents=16_000):
    """Reopen fieldwork and move one finding, so the cascade stales the draft."""
    reopen_fieldwork(ctx["audit"]["id"])
    ctx["purchases"].append(
        record_purchase(
            ctx["audit"]["id"], ctx["audit"]["scope_period_start"], purchase_price_cents
        )
    )
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    if ctx.get("assessment"):
        ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx


# --- Statute waiver chains ------------------------------------------------

def setup_waiver_draft(extended_to_date=None, extra_days=180, **kwargs):
    """Scoped audit with one DRAFTED waiver extending past the current expiry."""
    ctx = setup_scoped_audit(**kwargs)
    audit = ctx["audit"]
    target = extended_to_date or add_days(audit["statute_expiry_date"], extra_days)
    ctx["waiver"] = draft_waiver(audit["id"], audit["scope_period_end"], target)
    ctx["extended_to_date"] = target
    return ctx


def setup_executed_waiver(sign_day=None, **kwargs):
    """Waiver signed by the owning taxpayer on the logical clock date."""
    ctx = setup_waiver_draft(**kwargs)
    ctx["clock_date"] = set_clock_date(sign_day or DEFAULT_CLOCK_DATE)
    ctx["waiver"] = execute_waiver(
        ctx["waiver"]["id"], ctx["taxpayer"]["id"], ctx["clock_date"]
    )
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def setup_expired_statute_audit(**kwargs):
    """Scoped audit whose limitation period has run out against the clock."""
    ctx = setup_scoped_audit(**kwargs)
    ctx["clock_date"] = set_clock_date(add_days(ctx["audit"]["statute_expiry_date"], 1))
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def base_expiry_for(scope_period_end=DEFAULT_SCOPE_END):
    """The base limitation date: the scope's last day advanced by 1,095 days."""
    return add_days(scope_period_end, BASE_LIMITATION_DAYS)


# --- Appeal chains --------------------------------------------------------

def setup_open_proceeding(forum="INFORMAL_CONFERENCE", file_clock_day=None, **kwargs):
    """Issued notice under protest at the named forum."""
    ctx = setup_issued_assessment(**kwargs)
    if file_clock_day:
        ctx["clock_date"] = set_clock_date(file_clock_day)
    ctx["proceeding"] = file_protest(
        ctx["assessment"]["id"], ctx["taxpayer"]["id"], forum=forum
    )
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx


def setup_decided_proceeding(
    outcome="SUSTAINED",
    officer_user_id=APPEALS_OFFICER_USER_ID,
    decide_clock_day=None,
    decision_overrides=None,
    **kwargs,
):
    """Protest decided at the informal conference with the requested outcome."""
    ctx = setup_open_proceeding(**kwargs)
    if decide_clock_day:
        ctx["clock_date"] = set_clock_date(decide_clock_day)
    ctx["proceeding"] = decide_proceeding(
        ctx["proceeding"]["id"], outcome, officer_user_id, **(decision_overrides or {})
    )
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    ctx["taxpayer"] = read_taxpayer(ctx["taxpayer"]["id"])
    return ctx


def escalate_proceeding(ctx, forum, file_clock_day=None):
    """File the next rung of the ladder against the predecessor already decided."""
    if file_clock_day:
        ctx["clock_date"] = set_clock_date(file_clock_day)
    ctx["predecessor"] = ctx["proceeding"]
    ctx["proceeding"] = file_protest(
        ctx["assessment"]["id"],
        ctx["taxpayer"]["id"],
        forum=forum,
        predecessor_proceeding_id=ctx["predecessor"]["id"],
    )
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx


def setup_administrative_appeal_open(**kwargs):
    """Informal conference decided SUSTAINED, then the administrative appeal filed."""
    ctx = setup_decided_proceeding(outcome="SUSTAINED", **kwargs)
    return escalate_proceeding(ctx, "ADMINISTRATIVE_APPEAL")


def setup_tribunal_open(**kwargs):
    """Both lower rungs decided, with the tax tribunal proceeding open."""
    ctx = setup_administrative_appeal_open(**kwargs)
    ctx["proceeding"] = decide_proceeding(
        ctx["proceeding"]["id"], "SUSTAINED", OTHER_APPEALS_OFFICER_USER_ID
    )
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return escalate_proceeding(ctx, "TAX_TRIBUNAL")


# --- Collection chains ----------------------------------------------------

def setup_referred_assessment(**kwargs):
    """Issued notice handed to enforced collection, which posts the statutory fee."""
    ctx = setup_issued_assessment(**kwargs)
    ctx["assessment"] = refer_to_collections(ctx["assessment"]["id"])
    ctx["taxpayer"] = read_taxpayer(ctx["taxpayer"]["id"])
    return ctx


def setup_requested_installment_plan(monthly_installment_cents=None, term_months=1, **kwargs):
    """Issued notice with an installment plan sitting at REQUESTED."""
    ctx = setup_issued_assessment(**kwargs)
    balance = ctx["assessment"]["balance_due_cents"]
    monthly = (
        monthly_installment_cents
        if monthly_installment_cents is not None
        else -(-balance // term_months)
    )
    ctx["arrangement"] = request_installment_plan(
        ctx["assessment"]["id"], monthly, term_months
    )
    return ctx


def setup_approved_installment_plan(**kwargs):
    """Installment plan approved, which moves the collection axis to ARRANGED."""
    ctx = setup_requested_installment_plan(**kwargs)
    ctx["arrangement"] = approve_arrangement(ctx["arrangement"]["id"])
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx


def minimum_acceptable_offer(balance_due_cents):
    """Smallest offer satisfying offer * 10000 >= 2000 * balance, exactly."""
    return -(-balance_due_cents * 2_000 // 10_000)


def setup_requested_offer_in_compromise(
    offer_amount_cents=None, hardship_documented=True, **kwargs
):
    """Issued notice with an offer in compromise sitting at REQUESTED."""
    ctx = setup_issued_assessment(**kwargs)
    balance = ctx["assessment"]["balance_due_cents"]
    offer = (
        offer_amount_cents
        if offer_amount_cents is not None
        else minimum_acceptable_offer(balance)
    )
    ctx["arrangement"] = request_offer_in_compromise(
        ctx["assessment"]["id"], offer, hardship_documented=hardship_documented
    )
    return ctx


def setup_approved_offer_in_compromise(**kwargs):
    """Offer in compromise approved past the statutory minimum and hardship gate."""
    ctx = setup_requested_offer_in_compromise(**kwargs)
    ctx["arrangement"] = approve_arrangement(ctx["arrangement"]["id"])
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx
