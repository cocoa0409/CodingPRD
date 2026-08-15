"""Composite setup helpers for the payroll domain.

Every fixture builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. All setup calls use get_success_data()
so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_engagement_payload,
    create_garnishment_order_payload,
    create_grievance_case_payload,
    create_pay_batch_payload,
    create_performer_payload,
    create_production_payload,
    create_residual_obligation_payload,
    create_timecard_payload,
    create_union_agreement_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["payroll_admin_headers"]
ACCOUNTANT = TEST_USERS["production_accountant_headers"]
CLERK = TEST_USERS["payroll_clerk_headers"]
SUPERVISOR = TEST_USERS["payroll_supervisor_headers"]
AUDITOR = TEST_USERS["union_auditor_headers"]


# ----------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ----------------------------------------------------------------------

def create_agreement(**overrides) -> dict:
    """Create a DRAFT union agreement. Returns the agreement."""
    payload = create_union_agreement_payload(**overrides)
    return get_success_data(api_client.create_union_agreement(payload, ADMIN))


def create_ratified_agreement(**overrides) -> dict:
    """Create + ratify a union agreement. Returns the RATIFIED agreement."""
    agr = create_agreement(**overrides)
    return get_success_data(api_client.ratify_union_agreement(agr["id"], ADMIN))


def create_production(agreement_id, **overrides) -> dict:
    """Create a PRE_PRODUCTION production."""
    payload = create_production_payload(agreement_id, **overrides)
    return get_success_data(api_client.create_production(payload, ADMIN))


def create_shooting_production(agreement_id, **overrides) -> dict:
    """Create a production and advance it PRE_PRODUCTION -> SHOOTING."""
    prod = create_production(agreement_id, **overrides)
    return get_success_data(api_client.advance_production(prod["id"], ADMIN))


def create_performer(**overrides) -> dict:
    payload = create_performer_payload(**overrides)
    return get_success_data(api_client.create_performer(payload, ADMIN))


def create_draft_engagement(production_id, agreement_id, performer_id,
                            **overrides) -> dict:
    payload = create_engagement_payload(production_id, agreement_id,
                                        performer_id, **overrides)
    return get_success_data(api_client.create_engagement(payload, ACCOUNTANT))


def create_active_engagement(production_id, agreement_id, performer_id,
                             **overrides) -> dict:
    """Create -> submit -> approve. Returns the ACTIVE engagement."""
    eng = create_draft_engagement(production_id, agreement_id, performer_id,
                                  **overrides)
    get_success_data(api_client.submit_engagement(eng["id"], ACCOUNTANT))
    return get_success_data(api_client.approve_engagement(eng["id"], SUPERVISOR))


def get_engagement(engagement_id) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, CLERK))


def get_production(production_id) -> dict:
    return get_success_data(api_client.get_production(production_id, ADMIN))


def get_timecard(timecard_id) -> dict:
    return get_success_data(api_client.get_timecard(timecard_id, CLERK))


def get_performer(performer_id) -> dict:
    return get_success_data(api_client.get_performer(performer_id, ADMIN))


def get_pay_batch(batch_id) -> dict:
    return get_success_data(api_client.get_pay_batch(batch_id, CLERK))


def get_residual(obligation_id) -> dict:
    return get_success_data(api_client.get_residual_obligation(obligation_id, CLERK))


def get_garnishment_order(order_id) -> dict:
    return get_success_data(api_client.get_garnishment_order(order_id, ADMIN))


def list_pay_lines(params=None) -> list:
    data, _meta = validate_paginated(api_client.list_pay_lines(CLERK, params=params))
    return data


def list_all_penalty_assessments() -> list:
    data, _meta = validate_paginated(api_client.list_penalty_assessments(CLERK))
    return data


def list_all_timecards() -> list:
    data, _meta = validate_paginated(api_client.list_timecards(CLERK))
    return data


def list_all_engagements() -> list:
    data, _meta = validate_paginated(api_client.list_engagements(CLERK))
    return data


def list_all_residuals() -> list:
    data, _meta = validate_paginated(api_client.list_residual_obligations(CLERK))
    return data


# ----------------------------------------------------------------------
# Tier 2: standard scenario (agreement RATIFIED + production SHOOTING +
#         performer + engagement ACTIVE)
# ----------------------------------------------------------------------

def setup_standard(**engagement_overrides) -> dict:
    """RATIFIED agreement, SHOOTING production, performer, ACTIVE engagement.

    Returns {"agr": ..., "prod": ..., "perf": ..., "eng": ...} with full
    response bodies for each resource.
    """
    agr = create_ratified_agreement()
    prod = create_shooting_production(agr["id"])
    perf = create_performer()
    eng = create_active_engagement(prod["id"], agr["id"], perf["id"],
                                   **engagement_overrides)
    return {"agr": agr, "prod": prod, "perf": perf, "eng": eng}


# ----------------------------------------------------------------------
# Tier 3: timecard lifecycle shortcuts
# ----------------------------------------------------------------------

def create_timecard(engagement_id, **overrides) -> dict:
    """Create a SUBMITTED/UNBATCHED timecard (default: the TC-A card)."""
    payload = create_timecard_payload(engagement_id, **overrides)
    return get_success_data(api_client.create_timecard(payload, ACCOUNTANT))


def create_approved_timecard(engagement_id, **overrides) -> dict:
    """Create + approve a timecard. Returns the APPROVED timecard."""
    tc = create_timecard(engagement_id, **overrides)
    return get_success_data(api_client.approve_timecard(tc["id"], CLERK))


def setup_with_approved_timecard(**engagement_overrides) -> dict:
    """Standard scenario plus one APPROVED TC-A timecard."""
    ctx = setup_standard(**engagement_overrides)
    ctx["tc"] = create_approved_timecard(ctx["eng"]["id"])
    return ctx


# ----------------------------------------------------------------------
# Tier 3: residual lifecycle shortcuts
# ----------------------------------------------------------------------

def create_residual(engagement_id, **overrides) -> dict:
    """Create a REPORTED residual obligation."""
    payload = create_residual_obligation_payload(engagement_id, **overrides)
    return get_success_data(api_client.create_residual_obligation(payload, ACCOUNTANT))


def create_calculated_residual(engagement_id, **overrides) -> dict:
    res = create_residual(engagement_id, **overrides)
    return get_success_data(api_client.calculate_residual_obligation(res["id"], CLERK))


def create_approved_residual(engagement_id, **overrides) -> dict:
    res = create_calculated_residual(engagement_id, **overrides)
    return get_success_data(api_client.approve_residual_obligation(res["id"], SUPERVISOR))


# ----------------------------------------------------------------------
# Tier 3: garnishment orders
# ----------------------------------------------------------------------

def create_garnishment(performer_id, **overrides) -> dict:
    payload = create_garnishment_order_payload(performer_id, **overrides)
    return get_success_data(api_client.create_garnishment_order(payload, ADMIN))


def setup_garnishments_o1_o2(performer_id) -> tuple:
    """O1: CHILD_SUPPORT priority 1, 20% of disposable; O2: CREDITOR_JUDGMENT
    priority 2, fixed 5000. Returns (o1, o2)."""
    o1 = create_garnishment(performer_id, creditor_name="County CSA",
                            order_type="CHILD_SUPPORT", priority_rank=1,
                            pct_of_disposable=0.20)
    o2 = create_garnishment(performer_id, creditor_name="Collections Inc",
                            order_type="CREDITOR_JUDGMENT", priority_rank=2,
                            fixed_amount_cents=5000)
    return o1, o2


# ----------------------------------------------------------------------
# Tier 4/5: pay batch lifecycle (close / approve / recall / disburse)
# ----------------------------------------------------------------------

def create_open_batch(**overrides) -> dict:
    """Create an OPEN pay batch as the shared clerk user (clerk-1)."""
    payload = create_pay_batch_payload(**overrides)
    return get_success_data(api_client.create_pay_batch(payload, CLERK))


def setup_closed_batch_with_tca(with_garnishments=False) -> dict:
    """Standard + approved TC-A + batch created (as clerk-1) and closed.

    Returns ctx with keys agr/prod/perf/eng/tc/bat/lines and optionally
    g1/g2 when with_garnishments is True.
    """
    ctx = setup_with_approved_timecard()
    if with_garnishments:
        ctx["g1"], ctx["g2"] = setup_garnishments_o1_o2(ctx["perf"]["id"])
    ctx["bat"] = create_open_batch()
    get_success_data(api_client.close_pay_batch(ctx["bat"]["id"], CLERK))
    ctx["bat"] = get_pay_batch(ctx["bat"]["id"])
    ctx["lines"] = list_pay_lines()
    return ctx


def setup_approved_batch_with_tca(with_garnishments=False) -> dict:
    """Closed batch approved by the supervisor (sup-1 != clerk-1, SoD)."""
    ctx = setup_closed_batch_with_tca(with_garnishments=with_garnishments)
    get_success_data(api_client.approve_pay_batch(ctx["bat"]["id"], SUPERVISOR))
    ctx["bat"] = get_pay_batch(ctx["bat"]["id"])
    return ctx


def setup_disbursed_batch_with_tca(with_garnishments=False) -> dict:
    """Full lifecycle through DISBURSED. Returns ctx with bat/lines/etc."""
    ctx = setup_approved_batch_with_tca(with_garnishments=with_garnishments)
    get_success_data(api_client.disburse_pay_batch(ctx["bat"]["id"], SUPERVISOR))
    ctx["bat"] = get_pay_batch(ctx["bat"]["id"])
    ctx["lines"] = list_pay_lines()
    return ctx


# ----------------------------------------------------------------------
# Tier 3: grievance lifecycle shortcuts
# ----------------------------------------------------------------------

def create_grievance(engagement_id, **overrides) -> dict:
    """File a grievance as the shared auditor (aud-1). Returns FILED case."""
    payload = create_grievance_case_payload(engagement_id, **overrides)
    return get_success_data(api_client.create_grievance_case(payload, AUDITOR))


def create_under_review_grievance(engagement_id, **overrides) -> dict:
    grv = create_grievance(engagement_id, **overrides)
    return get_success_data(api_client.respond_grievance_case(
        grv["id"], "reviewing timecard audit", CLERK))


def get_grievance(case_id) -> dict:
    return get_success_data(api_client.get_grievance_case(case_id, CLERK))
