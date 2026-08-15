"""Composite setup helpers.

Multi-step PRD workflows (plan lifecycle, agreement FMV chain, capture crediting,
statement approval chain, supervision allocation, dispute resolution, plan-change
succession) are encapsulated here so tests focus on assertions. Every helper builds
its preconditions from scratch through PRD-declared endpoints, because each test
runs against a freshly started server with an empty database.

Setup calls use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AGREEMENT_EFFECTIVE_DATE,
    APP_BASE_SALARY_CENTS,
    APP_PERIOD_DRAW_CENTS,
    BASE_SALARY_CENTS,
    CLOCK_START,
    DEFAULT_CPT_CODE,
    DEFAULT_RATE_WRVU,
    FMV_CAP_CENTS,
    FISCAL_YEAR_END,
    FISCAL_YEAR_START,
    PERIOD_DRAW_CENTS,
    QUALITY_POOL_CENTS,
    RATE_WINDOW_FROM,
    RATE_WINDOW_TO,
    TIERS_SINGLE,
    TIERS_THREE,
)
from .factories import (
    clock_payload,
    create_agreement_payload,
    create_capture_payload,
    create_comp_plan_payload,
    create_cpt_rate_payload,
    create_dispute_payload,
    create_pcr_payload,
    create_physician_payload,
    create_scorecard_payload,
    create_statement_payload,
    create_supervision_assignment_payload,
    create_trueup_run_payload,
    fmv_review_payload,
    resolve_payload,
    review_decision_payload,
)
from .test_users import TEST_USERS, make_physician_headers

# Role headers used across fixtures (opaque roles, PRD §2.1).
ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]        # an_1 — creator side of SoD handoffs
ANALYST_2 = TEST_USERS["analyst_2_headers"]    # an_2
OFFICER = TEST_USERS["compliance_officer_headers"]   # co_1
COMMITTEE = TEST_USERS["committee_headers"]          # cc_1
COMMITTEE_9 = TEST_USERS["committee_9_headers"]      # cc_9 — finalizer/resolver side

_DEFAULT_RATE = {
    "cpt_code": DEFAULT_CPT_CODE,
    "wrvu_value": DEFAULT_RATE_WRVU,
    "effective_from": RATE_WINDOW_FROM,
    "effective_to": RATE_WINDOW_TO,
}


def _copy_tiers(tiers):
    return [dict(t) for t in tiers]


# ─── Tier 0: clock and roster ─────────────────────────────

def set_clock(to_iso8601=CLOCK_START):
    """Drive the logical clock (PRD §2.4). Returns the clock payload."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def register_physician(npi, full_name="Dr Test", specialty="IM",
                       provider_type="PHYSICIAN", fte=1.0, hire_date="2019-01-01"):
    """Register a clinician in the roster (PRD §3.1). Returns the Physician."""
    payload = create_physician_payload(
        npi=npi, full_name=full_name, specialty=specialty,
        provider_type=provider_type, fte=fte, hire_date=hire_date,
    )
    return get_success_data(api_client.create_physician(payload, ADMIN))


# ─── Tier 1: plan state progression ───────────────────────

def create_draft_plan(name="FY2026 Plan", tiers=None, rates="default", **plan_cfg):
    """Create a DRAFT plan, then add rate rows (default: 99213 covering the year).

    rates="default" -> one standard row; rates=[] -> no rows; otherwise an
    iterable of create_cpt_rate_payload kwargs.
    Returns (plan, rate_ids).
    """
    payload = create_comp_plan_payload(name=name, tiers=_copy_tiers(tiers or TIERS_SINGLE),
                                       **plan_cfg)
    plan = get_success_data(api_client.create_comp_plan(payload, ANALYST))
    if rates == "default":
        rates = [dict(_DEFAULT_RATE)]
    rate_ids = []
    for rate in rates:
        row = get_success_data(
            api_client.create_cpt_rate(plan["id"], create_cpt_rate_payload(**rate), ANALYST)
        )
        rate_ids.append(row["id"])
    return plan, rate_ids


def create_pending_review_plan(**kwargs):
    """DRAFT -> PENDING_REVIEW (PRD §3.2)."""
    plan, rate_ids = create_draft_plan(**kwargs)
    plan = get_success_data(api_client.submit_plan_review(plan["id"], ANALYST))
    return plan, rate_ids


def create_fmv_approved_plan(**kwargs):
    """DRAFT -> PENDING_REVIEW -> FMV_APPROVED (PRD §3.2)."""
    plan, rate_ids = create_pending_review_plan(**kwargs)
    plan = get_success_data(
        api_client.plan_review_decision(plan["id"], review_decision_payload("APPROVED"), OFFICER)
    )
    return plan, rate_ids


def create_active_plan(**kwargs):
    """Full plan lifecycle to ACTIVE (PRD §3.2). Returns (plan, rate_ids)."""
    plan, rate_ids = create_fmv_approved_plan(**kwargs)
    plan = get_success_data(api_client.activate_plan(plan["id"], COMMITTEE))
    return plan, rate_ids


# ─── Tier 2: agreement FMV chain ──────────────────────────

def create_agreement(physician_id, plan_id, base_salary_cents=BASE_SALARY_CENTS,
                     period_draw_cents=PERIOD_DRAW_CENTS,
                     effective_date=AGREEMENT_EFFECTIVE_DATE, extra_fields=None):
    """Enroll a physician into a plan (PRD §3.3). Returns the DRAFT agreement."""
    payload = create_agreement_payload(
        physician_id=physician_id, plan_id=plan_id,
        base_salary_cents=base_salary_cents, period_draw_cents=period_draw_cents,
        effective_date=effective_date,
    )
    if extra_fields:
        payload.update(extra_fields)
    return get_success_data(api_client.create_agreement(payload, ANALYST))


def create_pending_fmv_agreement(physician_id, plan_id, **kwargs):
    agreement = create_agreement(physician_id, plan_id, **kwargs)
    return get_success_data(api_client.submit_fmv(agreement["id"], ANALYST))


def create_fmv_approved_agreement(physician_id, plan_id, benchmark_percentile=55, **kwargs):
    """DRAFT -> PENDING_FMV -> FMV_APPROVED (PRD §3.3)."""
    agreement = create_pending_fmv_agreement(physician_id, plan_id, **kwargs)
    return get_success_data(
        api_client.fmv_review(
            agreement["id"], fmv_review_payload("APPROVED", benchmark_percentile), OFFICER
        )
    )


def create_effective_agreement(physician_id, plan_id, benchmark_percentile=55, **kwargs):
    """Full agreement chain to EFFECTIVE; requires the plan to be ACTIVE (PRD §3.3)."""
    agreement = create_fmv_approved_agreement(
        physician_id, plan_id, benchmark_percentile, **kwargs
    )
    return get_success_data(api_client.activate_agreement(agreement["id"], COMMITTEE))


def setup_active_plan_with_effective_agreement(npi="1000001001", fte=1.0,
                                               provider_type="PHYSICIAN",
                                               plan_name="Scenario Plan",
                                               tiers=None, rates="default",
                                               agreement_overrides=None, **plan_cfg):
    """The canonical scenario: ACTIVE plan + physician + EFFECTIVE agreement.

    Sets the logical clock to 2026-01-01 first so FMV freshness holds.
    Returns {"plan", "physician", "agreement"}.
    """
    set_clock()
    physician = register_physician(npi=npi, provider_type=provider_type, fte=fte)
    plan, rate_ids = create_active_plan(name=plan_name, tiers=tiers, rates=rates, **plan_cfg)
    agreement = create_effective_agreement(
        physician["id"], plan["id"], **(agreement_overrides or {})
    )
    return {"plan": plan, "physician": physician, "agreement": agreement,
            "rate_ids": rate_ids}


# ─── Tier 3: production capture and statement lifecycles ──

def post_capture(agreement_id, cpt_code=DEFAULT_CPT_CODE, units=10,
                 service_date="2026-02-10", posting_date="2026-02-10"):
    """Post a CLINICAL capture (born POSTED/UNCREDITED, PRD §3.4)."""
    payload = create_capture_payload(
        cpt_code=cpt_code, units=units, service_date=service_date, posting_date=posting_date
    )
    return get_success_data(api_client.create_capture(agreement_id, payload, ANALYST))


def validate_capture(capture_id):
    """POSTED -> VALIDATED and UNCREDITED -> CREDITED (PRD §3.4)."""
    return get_success_data(api_client.validate_capture(capture_id, ANALYST))


def create_validated_capture(agreement_id, **kwargs):
    capture = post_capture(agreement_id, **kwargs)
    return validate_capture(capture["id"])


def generate_statement(agreement_id, period_year=2026, period_month=2):
    """Generate a DRAFT statement (PRD §3.7)."""
    payload = create_statement_payload(period_year=period_year, period_month=period_month)
    return get_success_data(api_client.create_statement(agreement_id, payload, ANALYST))


def create_under_review_statement(agreement_id, period_year=2026, period_month=2):
    """DRAFT -> UNDER_REVIEW (PRD §3.7)."""
    stmt = generate_statement(agreement_id, period_year, period_month)
    return get_success_data(api_client.submit_statement_review(stmt["id"], ANALYST))


def create_finalized_statement(agreement_id, period_year=2026, period_month=2,
                               finalizer=None):
    """Full statement approval chain to FINALIZED (PRD §3.7). The finalizer must
    differ from the analyst who generated the statement (PRD §2.8)."""
    stmt = create_under_review_statement(agreement_id, period_year, period_month)
    return get_success_data(
        api_client.finalize_statement(stmt["id"], finalizer or COMMITTEE_9)
    )


def create_scorecard(agreement_id, period="2026-02", measures=None):
    payload = create_scorecard_payload(period=period, measures=measures or [
        {"measure_code": "M1", "weight": 50, "threshold_score": 80, "score": 85},
    ])
    return get_success_data(api_client.create_scorecard(agreement_id, payload, ANALYST))


# ─── Tier 4: supervision scenarios ────────────────────────

def create_supervision_assignment(supervisor_physician_id, app_physician_id,
                                  start_date="2026-01-01", end_date="2026-12-31",
                                  credit_pct=0.5, supervised_fte=0.5):
    payload = create_supervision_assignment_payload(
        supervisor_physician_id=supervisor_physician_id,
        app_physician_id=app_physician_id,
        start_date=start_date, end_date=end_date,
        credit_pct=credit_pct, supervised_fte=supervised_fte,
    )
    return get_success_data(api_client.create_supervision_assignment(payload, ANALYST))


def setup_supervision_scenario(supervisor_count=1, credit_pcts=(0.5,),
                               supervised_ftes=(0.5,), windows=None,
                               npi_base=1000002000, app_base_salary=APP_BASE_SALARY_CENTS):
    """ACTIVE plan + N supervisors + one APP, every party EFFECTIVE on the plan,
    plus one ACTIVE assignment per supervisor (PRD §3.5).

    Returns {"plan", "supervisors", "app", "agr_sups", "agr_app", "assignments"}.
    """
    set_clock()
    supervisors = [
        register_physician(npi=str(npi_base + i), full_name=f"Dr Sup {i}",
                           provider_type="PHYSICIAN")
        for i in range(supervisor_count)
    ]
    app = register_physician(npi=str(npi_base + 100), full_name="NP App",
                             specialty="APP-NP", provider_type="APP")
    plan, _ = create_active_plan(name="Supervision Plan")
    agr_sups = [create_effective_agreement(s["id"], plan["id"]) for s in supervisors]
    agr_app = create_effective_agreement(
        app["id"], plan["id"], benchmark_percentile=40,
        base_salary_cents=app_base_salary, period_draw_cents=APP_PERIOD_DRAW_CENTS,
    )
    windows = windows or [("2026-01-01", "2026-12-31")] * supervisor_count
    assignments = []
    for i, sup in enumerate(supervisors):
        if i < len(credit_pcts):
            assignments.append(create_supervision_assignment(
                sup["id"], app["id"], start_date=windows[i][0], end_date=windows[i][1],
                credit_pct=credit_pcts[i],
                supervised_fte=supervised_ftes[i] if i < len(supervised_ftes) else 0.5,
            ))
    return {"plan": plan, "supervisors": supervisors, "app": app,
            "agr_sups": agr_sups, "agr_app": agr_app, "assignments": assignments}


# ─── Tier 5: disputes ─────────────────────────────────────

def file_capture_dispute(physician_id, capture_id, reason="questioning the entry"):
    """Physician files a CAPTURE dispute (born FILED, PRD §3.8). Identity is
    entity-backed: headers carry the filing physician's own id."""
    payload = create_dispute_payload(
        subject_type="CAPTURE", subject_capture_id=capture_id, reason=reason
    )
    return get_success_data(
        api_client.create_dispute(payload, make_physician_headers(physician_id))
    )


def create_dispute_under_review(physician_id, capture_id, reason="questioning the entry"):
    """FILED -> UNDER_REVIEW (PRD §3.8)."""
    dispute = file_capture_dispute(physician_id, capture_id, reason)
    return get_success_data(api_client.start_dispute_review(dispute["id"], ANALYST))


def accept_dispute(dispute_id, resolver=None):
    """Resolve ACCEPTED (PRD §3.8); resolver defaults to a committee member who is
    not the capture's creator (segregation of duties, PRD §2.8)."""
    return get_success_data(
        api_client.resolve_dispute(dispute_id, resolve_payload("ACCEPTED"),
                                   resolver or COMMITTEE_9)
    )


def reject_dispute(dispute_id, resolver=None):
    return get_success_data(
        api_client.resolve_dispute(dispute_id, resolve_payload("REJECTED"),
                                   resolver or COMMITTEE_9)
    )


# ─── Tier 5: true-up runs ─────────────────────────────────

def create_trueup_run(plan_id, as_of_period="2026-06"):
    payload = create_trueup_run_payload(as_of_period=as_of_period)
    return get_success_data(api_client.create_trueup_run(plan_id, payload, ANALYST))


def create_posted_trueup_run(plan_id, as_of_period="2026-06"):
    run = create_trueup_run(plan_id, as_of_period)
    return get_success_data(api_client.post_trueup_run(run["id"], COMMITTEE))


# ─── Tier 5: plan change requests ─────────────────────────

def setup_successor_pair(p1_name="P1", p2_name="P2", p1_cfg=None, p2_cfg=None):
    """P1 ACTIVE and P2 FMV_APPROVED with supersedes_plan_id == P1 (PRD §3.9).
    Returns (p1, p2)."""
    p1, _ = create_active_plan(name=p1_name, **(p1_cfg or {}))
    p2_cfg = {"quality_pool_cents": 120000,
              "tiers": [{"tier_code": "T1", "threshold_wrvu": 0,
                         "conversion_factor_cents": 4700, "tier_bonus_cents": 0}],
              **(p2_cfg or {})}
    p2, _ = create_fmv_approved_plan(name=p2_name, supersedes_plan_id=p1["id"], **p2_cfg)
    return p1, p2


def create_pcr(plan_id, successor_plan_id, effective_date="2026-03-01",
               summary="plan change", expected_comp_plan_version=None):
    """Propose a plan change (born PROPOSED, PRD §3.9). Fetches the plan's current
    version for the OCC field when not supplied (PRD §2.6)."""
    if expected_comp_plan_version is None:
        plan = get_success_data(api_client.get_comp_plan(plan_id, ANALYST))
        expected_comp_plan_version = plan["version"]
    payload = create_pcr_payload(
        plan_id=plan_id, successor_plan_id=successor_plan_id,
        effective_date=effective_date, summary=summary,
        expected_comp_plan_version=expected_comp_plan_version,
    )
    return get_success_data(api_client.create_plan_change_request(payload, ANALYST))


def setup_pcr_communicated(acknowledge=True, with_capture_and_statement=False,
                           effective_date="2026-03-01", npi="1000003001"):
    """Full plan-change setup to COMMUNICATED (PRD §3.9):

    P1 ACTIVE with physician PH EFFECTIVE (optionally with a validated capture and
    a DRAFT 2026-02 statement); P2 FMV_APPROVED successor; PCR created, MODELED
    (modeled_delta_cents captured), COMMUNICATED, optionally acknowledged by PH.

    Returns {"plan", "successor", "physician", "agreement", "pcr",
             "modeled_delta_cents", "capture", "statement"} (last two optional).
    """
    set_clock()
    physician = register_physician(npi=npi, full_name="Dr Change")
    plan, _ = create_active_plan(name="Changed Plan")
    agreement = create_effective_agreement(physician["id"], plan["id"])
    capture = statement = None
    if with_capture_and_statement:
        capture = create_validated_capture(agreement["id"])
        statement = generate_statement(agreement["id"], 2026, 2)
    successor, _ = create_fmv_approved_plan(
        name="Successor Plan", quality_pool_cents=120000,
        tiers=[{"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4700,
                "tier_bonus_cents": 0}],
        supersedes_plan_id=plan["id"],
    )
    pcr = create_pcr(plan["id"], successor["id"], effective_date=effective_date)
    modeled = get_success_data(api_client.model_plan_change(pcr["id"], ANALYST))
    pcr = get_success_data(api_client.communicate_plan_change(pcr["id"], ANALYST))
    if acknowledge:
        get_success_data(
            api_client.acknowledge_plan_change(pcr["id"], make_physician_headers(physician["id"]))
        )
        pcr = get_success_data(api_client.get_plan_change_request(pcr["id"], ANALYST))
    return {"plan": plan, "successor": successor, "physician": physician,
            "agreement": agreement, "pcr": pcr,
            "modeled_delta_cents": modeled.get("modeled_delta_cents"),
            "capture": capture, "statement": statement}


def setup_pcr_activated(**kwargs):
    """COMMUNICATED -> EFFECTIVE: clock advanced to the effective date, then the
    committee activates, firing the succession cascade (PRD §3.9)."""
    scenario = setup_pcr_communicated(**kwargs)
    set_clock("2026-03-01T00:00:00Z")
    pcr = get_success_data(api_client.activate_plan_change(scenario["pcr"]["id"], COMMITTEE))
    scenario["pcr"] = pcr
    return scenario
