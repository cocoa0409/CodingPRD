"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() so setup failures surface as clear "Setup failed" errors.

The building blocks walk the domain pipeline:
    subject -> referral -> ACCEPT -> case -> assign -> evidence -> submit-review
    -> adjudicate -> overpayment -> months -> calculate -> establish -> demand
    -> recovery-plan -> transaction
plus the disqualification / ADH-hearing branch off a SUBSTANTIATED case.

A `ctx` dict threads the created resources between steps; keys include:
    subject, referral, case, overpayment, months, disqualification, hearing,
    recovery_plan, transaction
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_investigator_headers,
    make_adjudicator_headers,
    DEFAULT_INVESTIGATOR_ID,
    DEFAULT_ADJUDICATOR_ID,
)
from .factories import (
    create_subject_payload,
    create_referral_payload,
    decide_referral_payload,
    create_case_payload,
    assign_case_payload,
    adjudicate_case_payload,
    create_evidence_payload,
    create_overpayment_payload,
    create_month_payload,
    create_disqualification_payload,
    create_hearing_payload,
    decide_hearing_payload,
    create_recovery_plan_payload,
    create_transaction_payload,
    set_clock_payload,
    DEFAULT_MONTHS,
)

_INTAKE = TEST_USERS["intake_headers"]
_SUPERVISOR = TEST_USERS["supervisor_headers"]
_RECOVERY = TEST_USERS["recovery_officer_headers"]


# --------------------------------------------------------------------------- #
# Primitive steps
# --------------------------------------------------------------------------- #
def register_subject(api, program="SNAP", name="Test Subject", ssn_last4="1234"):
    resp = api.create_subject(
        create_subject_payload(name=name, ssn_last4=ssn_last4, primary_program=program),
        _INTAKE,
    )
    return get_success_data(resp)


def file_referral(api, subject_id, program="SNAP", source="DATA_MATCH", summary="Allegation"):
    resp = api.create_referral(
        create_referral_payload(subject_id, program=program, source=source, allegation_summary=summary),
        _INTAKE,
    )
    return get_success_data(resp)


def accept_referral(api, referral_id):
    resp = api.decide_referral(referral_id, decide_referral_payload("ACCEPT"), _INTAKE)
    return get_success_data(resp)


def open_case(api, referral_id):
    resp = api.create_case(create_case_payload(referral_id), TEST_USERS["investigator_headers"])
    return get_success_data(resp)


def assign_case(api, case_id, investigator_id=DEFAULT_INVESTIGATOR_ID):
    resp = api.assign_case(
        case_id,
        assign_case_payload(investigator_user_id=investigator_id),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def add_evidence(api, case_id, investigator_id=DEFAULT_INVESTIGATOR_ID, kind="DOCUMENT", description="Record"):
    resp = api.create_evidence(
        case_id,
        create_evidence_payload(kind=kind, description=description),
        make_investigator_headers(investigator_id),
    )
    return get_success_data(resp)


def submit_review(api, case_id, investigator_id=DEFAULT_INVESTIGATOR_ID):
    resp = api.submit_review(case_id, make_investigator_headers(investigator_id))
    return get_success_data(resp)


def adjudicate(api, case_id, decision):
    resp = api.adjudicate_case(case_id, adjudicate_case_payload(decision), _SUPERVISOR)
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Case-stage composites
# --------------------------------------------------------------------------- #
def create_open_case(api, program="SNAP", source="DATA_MATCH", subject=None):
    """Open a fresh case. Pass an existing `subject` to reuse it (e.g. for
    same-subject scenarios like overlapping recovery plans)."""
    if subject is None:
        subject = register_subject(api, program=program)
    referral = file_referral(api, subject["id"], program=program, source=source)
    accept_referral(api, referral["id"])
    case = open_case(api, referral["id"])
    return {"subject": subject, "referral": referral, "case": case}


def create_investigation_case(api, program="SNAP", source="DATA_MATCH",
                              investigator_id=DEFAULT_INVESTIGATOR_ID, subject=None):
    ctx = create_open_case(api, program=program, source=source, subject=subject)
    ctx["case"] = assign_case(api, ctx["case"]["id"], investigator_id=investigator_id)
    return ctx


def create_pending_review_case(api, program="SNAP", source="DATA_MATCH",
                               investigator_id=DEFAULT_INVESTIGATOR_ID, subject=None):
    ctx = create_investigation_case(api, program=program, source=source,
                                    investigator_id=investigator_id, subject=subject)
    add_evidence(api, ctx["case"]["id"], investigator_id=investigator_id)
    ctx["case"] = submit_review(api, ctx["case"]["id"], investigator_id=investigator_id)
    return ctx


def create_substantiated_case(api, program="SNAP", source="DATA_MATCH",
                              investigator_id=DEFAULT_INVESTIGATOR_ID, subject=None):
    ctx = create_pending_review_case(api, program=program, source=source,
                                     investigator_id=investigator_id, subject=subject)
    ctx["case"] = adjudicate(api, ctx["case"]["id"], "SUBSTANTIATE")
    return ctx


# --------------------------------------------------------------------------- #
# Overpayment-stage composites
# --------------------------------------------------------------------------- #
def _add_months(api, overpayment_id, months):
    created = []
    for m in months:
        resp = api.create_month(overpayment_id, create_month_payload(**m), TEST_USERS["investigator_headers"])
        created.append(get_success_data(resp))
    return created


def add_draft_overpayment(api, ctx, claim_type="IHE", months=None):
    """Attach a DRAFT overpayment (optionally with month line items) to ctx['case']."""
    resp = api.create_overpayment(
        create_overpayment_payload(ctx["case"]["id"], claim_type=claim_type),
        TEST_USERS["investigator_headers"],
    )
    op = get_success_data(resp)
    ctx["overpayment"] = op
    if months:
        ctx["months"] = _add_months(api, op["id"], months)
    return ctx


def add_calculated_overpayment(api, ctx, claim_type="IHE", months=None):
    months = DEFAULT_MONTHS if months is None else months
    add_draft_overpayment(api, ctx, claim_type=claim_type, months=months)
    resp = api.calculate_overpayment(ctx["overpayment"]["id"], TEST_USERS["investigator_headers"])
    ctx["overpayment"] = get_success_data(resp)
    return ctx


def add_established_overpayment(api, ctx):
    resp = api.establish_overpayment(ctx["overpayment"]["id"], _SUPERVISOR)
    ctx["overpayment"] = get_success_data(resp)
    return ctx


def add_demanded_overpayment(api, ctx):
    resp = api.demand_overpayment(ctx["overpayment"]["id"], _RECOVERY)
    ctx["overpayment"] = get_success_data(resp)
    return ctx


def add_recovery_plan(api, ctx, **plan_overrides):
    resp = api.create_recovery_plan(
        create_recovery_plan_payload(ctx["overpayment"]["id"], **plan_overrides),
        _RECOVERY,
    )
    ctx["recovery_plan"] = get_success_data(resp)
    # Overpayment has moved to IN_RECOVERY; refresh the cached copy.
    ctx["overpayment"] = get_success_data(api.get_overpayment(ctx["overpayment"]["id"], _SUPERVISOR))
    return ctx


# --------------------------------------------------------------------------- #
# High-level end-to-end overpayment fixtures
# --------------------------------------------------------------------------- #
def setup_calculated_overpayment(api, claim_type="IHE", months=None, substantiate=True,
                                 program="SNAP", source="DATA_MATCH", subject=None):
    """SUBSTANTIATED (or PENDING_REVIEW when substantiate=False) case + a CALCULATED
    overpayment of the given claim_type and month set."""
    if substantiate:
        ctx = create_substantiated_case(api, program=program, source=source, subject=subject)
    else:
        ctx = create_pending_review_case(api, program=program, source=source, subject=subject)
    add_calculated_overpayment(api, ctx, claim_type=claim_type, months=months)
    return ctx


def setup_established_overpayment(api, claim_type="IHE", months=None, program="SNAP",
                                  source="DATA_MATCH", subject=None):
    ctx = setup_calculated_overpayment(api, claim_type=claim_type, months=months,
                                       substantiate=True, program=program, source=source,
                                       subject=subject)
    add_established_overpayment(api, ctx)
    return ctx


def setup_demanded_overpayment(api, claim_type="IHE", months=None, program="SNAP",
                               source="DATA_MATCH", subject=None):
    ctx = setup_established_overpayment(api, claim_type=claim_type, months=months,
                                        program=program, source=source, subject=subject)
    add_demanded_overpayment(api, ctx)
    return ctx


def setup_overpayment_in_recovery(api, claim_type="IHE", months=None, program="SNAP",
                                  source="DATA_MATCH", plan_overrides=None, subject=None):
    ctx = setup_demanded_overpayment(api, claim_type=claim_type, months=months,
                                     program=program, source=source, subject=subject)
    add_recovery_plan(api, ctx, **(plan_overrides or {}))
    return ctx


# --------------------------------------------------------------------------- #
# Disqualification / hearing branch (off a SUBSTANTIATED case)
# --------------------------------------------------------------------------- #
def add_proposed_disqualification(api, ctx):
    resp = api.create_disqualification(
        create_disqualification_payload(ctx["case"]["id"]),
        TEST_USERS["investigator_headers"],
    )
    ctx["disqualification"] = get_success_data(resp)
    return ctx


def add_adh_referred_disqualification(api, ctx, investigator_id=DEFAULT_INVESTIGATOR_ID):
    add_proposed_disqualification(api, ctx)
    resp = api.refer_adh(ctx["disqualification"]["id"], make_investigator_headers(investigator_id))
    ctx["disqualification"] = get_success_data(resp)
    return ctx


def add_scheduled_hearing(api, ctx, scheduled_date="2026-05-15T09:00:00Z"):
    resp = api.create_hearing(
        create_hearing_payload(ctx["disqualification"]["id"], scheduled_date=scheduled_date),
        TEST_USERS["adjudicator_headers"],
    )
    ctx["hearing"] = get_success_data(resp)
    return ctx


def add_held_hearing(api, ctx, adjudicator_id=DEFAULT_ADJUDICATOR_ID, scheduled_date="2026-05-15T09:00:00Z"):
    add_scheduled_hearing(api, ctx, scheduled_date=scheduled_date)
    resp = api.hold_hearing(ctx["hearing"]["id"], make_adjudicator_headers(adjudicator_id))
    ctx["hearing"] = get_success_data(resp)
    return ctx


def add_decided_ipv_hearing(api, ctx, adjudicator_id=DEFAULT_ADJUDICATOR_ID):
    add_held_hearing(api, ctx, adjudicator_id=adjudicator_id)
    resp = api.decide_hearing(
        ctx["hearing"]["id"], decide_hearing_payload("IPV"), make_adjudicator_headers(adjudicator_id)
    )
    ctx["hearing"] = get_success_data(resp)
    return ctx


def setup_held_hearing(api, investigator_id=DEFAULT_INVESTIGATOR_ID):
    """SUBSTANTIATED case -> PROPOSED -> ADH_REFERRED disqualification -> SCHEDULED -> HELD hearing."""
    ctx = create_substantiated_case(api, investigator_id=investigator_id)
    add_adh_referred_disqualification(api, ctx, investigator_id=investigator_id)
    add_held_hearing(api, ctx)
    return ctx


def setup_imposed_disqualification(api, investigator_id=DEFAULT_INVESTIGATOR_ID):
    """SUBSTANTIATED case with a first-offense IMPOSED disqualification (prior_ipv_count == 1)."""
    ctx = setup_held_hearing(api, investigator_id=investigator_id)
    add_decided_ipv_hearing(api, ctx)
    return ctx


# --------------------------------------------------------------------------- #
# Clock helper
# --------------------------------------------------------------------------- #
def advance_clock(api, to_iso8601):
    resp = api.set_clock(set_clock_payload(to_iso8601), _SUPERVISOR)
    return get_success_data(resp)
