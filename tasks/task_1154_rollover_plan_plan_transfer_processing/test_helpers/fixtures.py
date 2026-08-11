"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data so a
setup failure surfaces as a clear "Setup failed" message rather than a
confusing assertion error.

Segregation of duties (PRD §2.6): the processor who approves a case
(PROCESSOR_APPROVER_ID) is always different from the processor who moves its
money (PROCESSOR_MOVER_ID).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CANONICAL_BALANCES,
    PROCESSOR_APPROVER_ID,
    PROCESSOR_MOVER_ID,
)
from .factories import (
    create_account_payload,
    create_case_payload,
    create_loan_payload,
    create_participant_payload,
    create_plan_payload,
    create_redeposit_payload,
    create_verification_payload,
)
from .test_users import (
    make_admin_headers,
    make_operations_headers,
    make_participant_headers,
    make_processor_headers,
    make_tax_officer_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: atomic builders
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, make_operations_headers())
    return get_success_data(resp)


def make_plan(name="Plan A", plan_type="PLAN_401K", clock=None, **flag_overrides):
    """Create a plan (optionally setting the logical clock first)."""
    if clock is not None:
        set_logical_clock(clock)
    payload = create_plan_payload(plan_name=name, plan_type=plan_type, **flag_overrides)
    resp = api_client.create_plan(payload, make_admin_headers())
    return get_success_data(resp)


def make_participant(clock=None, **overrides):
    if clock is not None:
        set_logical_clock(clock)
    resp = api_client.create_participant(create_participant_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def make_account(participant_id, plan_id, initial_balances=None):
    payload = create_account_payload(participant_id, plan_id)
    if initial_balances is not None:
        payload["initial_balances"] = initial_balances
    resp = api_client.create_account(payload, make_admin_headers())
    return get_success_data(resp)


def make_loan(account_id, **overrides):
    resp = api_client.create_loan(account_id, create_loan_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def participant_headers(participant) -> dict:
    """Ownership-correct headers for the Participant role."""
    return make_participant_headers(participant["id"])


def get_case(case_id):
    resp = api_client.get_rollover_case(case_id, make_processor_headers(PROCESSOR_APPROVER_ID))
    return get_success_data(resp)


def get_account(account_id):
    resp = api_client.get_account(account_id, make_processor_headers(PROCESSOR_APPROVER_ID))
    return get_success_data(resp)


def list_case_documents(case_id):
    resp = api_client.list_case_documents(case_id, make_processor_headers(PROCESSOR_APPROVER_ID))
    docs, _meta = validate_paginated(resp)
    return docs


def list_source_rows(account_id):
    resp = api_client.list_source_balances(account_id, make_processor_headers(PROCESSOR_APPROVER_ID))
    rows, _meta = validate_paginated(resp)
    return rows


def source_rows_by_type(account_id) -> dict:
    """Money-source rows of an account keyed by source_type."""
    return {row["source_type"]: row for row in list_source_rows(account_id)}


def list_case_tax_forms(case_id, form_type=None):
    params = {"rollover_case_id": case_id}
    if form_type is not None:
        params["form_type"] = form_type
    resp = api_client.list_tax_forms(make_tax_officer_headers(), params=params)
    forms, meta = validate_paginated(resp)
    return forms, meta


def list_participant_5498s(participant_id):
    resp = api_client.list_tax_forms(
        make_tax_officer_headers(),
        params={"participant_id": participant_id, "form_type": "FORM_5498"},
    )
    forms, meta = validate_paginated(resp)
    return forms, meta


# ---------------------------------------------------------------------------
# Tier 1: case lifecycle drivers
# ---------------------------------------------------------------------------

def settle_case_documents(case_id, participant_id, reviewer_id=PROCESSOR_APPROVER_ID):
    """Submit every outstanding required document as the owning participant,
    then accept each as the reviewing processor. After acceptance of every
    document the case is approval-ready (PRD §3.4)."""
    docs = list_case_documents(case_id)
    p_headers = make_participant_headers(participant_id)
    r_headers = make_processor_headers(reviewer_id)
    for doc in docs:
        if doc["status"] in ("REQUIRED", "REJECTED"):
            resp = api_client.submit_document(doc["id"], p_headers)
            get_success_data(resp)
    for doc in docs:
        resp = api_client.review_document(doc["id"], {"decision": "ACCEPTED"}, r_headers)
        get_success_data(resp)
    return list_case_documents(case_id)


def submit_case(case_id, participant_id):
    resp = api_client.submit_case(case_id, make_participant_headers(participant_id))
    return get_success_data(resp)


def approve_case(case_id, approver_id=PROCESSOR_APPROVER_ID):
    resp = api_client.decide_eligibility(
        case_id, {"decision": "APPROVE"}, make_processor_headers(approver_id)
    )
    return get_success_data(resp)


def open_outbound_case(account, participant, case_type, requested_amount_cents=None,
                       receiving_institution_name="External IRA Trust", **extra):
    """Create + submit + settle docs + APPROVE for DIRECT/INDIRECT outbound
    cases. Returns the approved (ELIGIBLE) case."""
    payload = create_case_payload(
        case_type,
        source_account_id=account["id"],
        receiving_institution_name=receiving_institution_name,
    )
    if requested_amount_cents is not None:
        payload["requested_amount_cents"] = requested_amount_cents
    if case_type == "INDIRECT_ROLLOVER_OUT":
        payload["withholding_acknowledged"] = True
    payload.update(extra)
    resp = api_client.create_rollover_case(payload, participant_headers(participant))
    case = get_success_data(resp)
    submit_case(case["id"], participant["id"])
    settle_case_documents(case["id"], participant["id"])
    return approve_case(case["id"])


def assemble_and_issue(case_id, method="CHECK", mover_id=PROCESSOR_MOVER_ID):
    """Assemble the disbursement (ELIGIBLE case) and issue it. Returns the
    ISSUED disbursement."""
    m_headers = make_processor_headers(mover_id)
    resp = api_client.assemble_disbursement(case_id, {"method": method}, m_headers)
    disb = get_success_data(resp)
    resp = api_client.issue_disbursement(disb["id"], m_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: full scenario builders
# ---------------------------------------------------------------------------

def build_approved_indirect_case(balances=None, requested_amount_cents=None,
                                 clock="2026-05-01T00:00:00Z", plan_flags=None,
                                 participant_overrides=None):
    """Plan + SEPARATED participant + account + approved (ELIGIBLE)
    INDIRECT_ROLLOVER_OUT case. Approver is proc-1; money must be moved by
    proc-2. Returns a bundle dict."""
    flags = plan_flags or {}
    plan = make_plan(clock=clock, **flags)
    participant = make_participant(**(participant_overrides or {}))
    account = make_account(participant["id"], plan["id"],
                           balances if balances is not None else CANONICAL_BALANCES)
    case = open_outbound_case(account, participant, "INDIRECT_ROLLOVER_OUT",
                              requested_amount_cents=requested_amount_cents)
    return {"plan": plan, "participant": participant, "account": account, "case": case}


def build_issued_indirect_case(balances=None, requested_amount_cents=None,
                               clock="2026-06-01T00:00:00Z", method="CHECK",
                               receiving_plan_type=None):
    """Approved indirect case + issued disbursement (case AWAITING_REDEPOSIT).
    Optionally creates a second (IRA) plan and an empty receiving account for
    the same participant. Returns a bundle dict."""
    bundle = build_approved_indirect_case(
        balances=balances, requested_amount_cents=requested_amount_cents, clock=clock
    )
    bundle["disbursement"] = assemble_and_issue(bundle["case"]["id"], method=method)
    if receiving_plan_type is not None:
        ira_plan = make_plan(name="IRA Plan", plan_type=receiving_plan_type)
        bundle["receiving_plan"] = ira_plan
        bundle["receiving_account"] = make_account(bundle["participant"]["id"], ira_plan["id"], [])
    return bundle


def build_approved_direct_case(balances=None, requested_amount_cents=None,
                               clock="2026-05-01T00:00:00Z", method=None):
    """Plan + SEPARATED participant + account + approved (ELIGIBLE)
    DIRECT_ROLLOVER_OUT case. Returns a bundle dict."""
    plan = make_plan(clock=clock)
    participant = make_participant()
    account = make_account(participant["id"], plan["id"],
                           balances if balances is not None else CANONICAL_BALANCES)
    case = open_outbound_case(account, participant, "DIRECT_ROLLOVER_OUT",
                              requested_amount_cents=requested_amount_cents)
    return {"plan": plan, "participant": participant, "account": account, "case": case}


def open_verification(case_id, direction="OUTBOUND", method="PLAN_LETTER"):
    resp = api_client.create_case_verification(
        case_id, create_verification_payload(direction, method),
        make_processor_headers(PROCESSOR_APPROVER_ID),
    )
    return get_success_data(resp)


def complete_verification(ver_id, outcome="VERIFIED"):
    resp = api_client.complete_verification(
        ver_id, {"outcome": outcome}, make_processor_headers(PROCESSOR_APPROVER_ID)
    )
    return get_success_data(resp)


def build_issued_direct_case(balances=None, requested_amount_cents=None,
                             clock="2026-06-01T00:00:00Z", method="WIRE"):
    """Approved direct case + OUTBOUND verification VERIFIED + issued
    disbursement (case DISBURSED, DRAFT 1099-R drafted). Returns a bundle."""
    bundle = build_approved_direct_case(
        balances=balances, requested_amount_cents=requested_amount_cents, clock=clock
    )
    ver = open_verification(bundle["case"]["id"], "OUTBOUND")
    complete_verification(ver["id"], "VERIFIED")
    bundle["verification"] = ver
    bundle["disbursement"] = assemble_and_issue(bundle["case"]["id"], method=method)
    return bundle


def build_plan_transfer_acceptance(source_balances=None, receiving_plan_flags=None,
                                   clock="2026-05-01T00:00:00Z"):
    """Plans A and B + participant + canonical source account + empty receiving
    account at plan B + PLAN_TRANSFER case approved (ACCEPTANCE_PENDING).
    Returns a bundle dict."""
    plan_a = make_plan(name="Plan A", clock=clock)
    plan_b = make_plan(name="Plan B", **(receiving_plan_flags or {}))
    participant = make_participant()
    a1 = make_account(participant["id"], plan_a["id"],
                      source_balances if source_balances is not None else CANONICAL_BALANCES)
    a1b = make_account(participant["id"], plan_b["id"], [])
    payload = create_case_payload(
        "PLAN_TRANSFER",
        source_account_id=a1["id"],
        receiving_plan_id=plan_b["id"],
        receiving_account_id=a1b["id"],
    )
    resp = api_client.create_rollover_case(payload, participant_headers(participant))
    case = get_success_data(resp)
    submit_case(case["id"], participant["id"])
    settle_case_documents(case["id"], participant["id"])
    case = approve_case(case["id"])
    return {"plan_a": plan_a, "plan_b": plan_b, "participant": participant,
            "source_account": a1, "receiving_account": a1b, "case": case}


def build_rollover_in_acceptance(clock="2026-05-01T00:00:00Z", plan_flags=None):
    """Plan B + participant + empty receiving account + ROLLOVER_IN case with
    its SOURCE_PLAN_STATEMENT accepted and an INBOUND verification VERIFIED,
    approved (ACCEPTANCE_PENDING). Returns a bundle dict."""
    plan_b = make_plan(name="Plan B", clock=clock, **(plan_flags or {}))
    participant = make_participant()
    a2 = make_account(participant["id"], plan_b["id"], [])
    payload = create_case_payload(
        "ROLLOVER_IN",
        receiving_account_id=a2["id"],
        receiving_institution_name="Old Employer 401k Trust",
    )
    resp = api_client.create_rollover_case(payload, participant_headers(participant))
    case = get_success_data(resp)
    submit_case(case["id"], participant["id"])
    settle_case_documents(case["id"], participant["id"])
    ver = open_verification(case["id"], "INBOUND", method="THIRD_PARTY_REGISTRY")
    complete_verification(ver["id"], "VERIFIED")
    case = approve_case(case["id"])
    return {"plan_b": plan_b, "participant": participant, "receiving_account": a2,
            "case": case, "verification": ver}


def build_conversion_case(balances=None, requested_amount_cents=3000000,
                          clock="2026-05-01T00:00:00Z", approve=True):
    """Plan + ACTIVE participant (dob 1970-01-01) + account +
    IN_PLAN_ROTH_CONVERSION case; when approve=True the case is ELIGIBLE.
    Returns a bundle dict."""
    plan = make_plan(clock=clock)
    participant = make_participant(
        full_name="Con Vert", date_of_birth="1970-01-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    rows = balances if balances is not None else [
        {"source_type": "PRE_TAX", "balance_cents": 3000000, "basis_cents": 0, "vested_pct": 100},
    ]
    account = make_account(participant["id"], plan["id"], rows)
    payload = create_case_payload(
        "IN_PLAN_ROTH_CONVERSION",
        source_account_id=account["id"],
        receiving_account_id=account["id"],
        requested_amount_cents=requested_amount_cents,
    )
    resp = api_client.create_rollover_case(payload, participant_headers(participant))
    case = get_success_data(resp)
    submit_case(case["id"], participant["id"])
    if approve:
        case = approve_case(case["id"])
    return {"plan": plan, "participant": participant, "account": account, "case": case}
