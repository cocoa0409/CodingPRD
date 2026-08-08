"""Composite setup helpers.

The server database is reset before every test, so each helper builds all of its
preconditions from scratch using only PRD-declared endpoints. Setups use the
lenient get_success_data() validator so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing assertion. Ownership-gated Holder /
Owner / RecoveryAgent calls always use headers built from the acting entity's real
id (see test_users.make_*_headers).
"""
from prd_bench_local_runner.testing import get_success_data
from . import factories as f
from .test_users import (
    TEST_USERS, make_holder_headers, make_owner_headers,
    make_recovery_agent_headers, make_examiner_headers, make_approver_headers,
)

ADMIN = TEST_USERS["state_admin_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_holder(api, **overrides):
    return get_success_data(api.create_holder(f.create_holder_payload(**overrides), ADMIN))


def create_property_type(api, **overrides):
    return get_success_data(api.create_property_type(f.create_property_type_payload(**overrides), ADMIN))


def create_state_account(api, state_code="CA", **overrides):
    return get_success_data(api.create_state_account(
        f.create_state_account_payload(state_code, **overrides), ADMIN))


def create_owner(api, **overrides):
    return get_success_data(api.create_owner(f.create_owner_payload(**overrides), ADMIN))


def create_recovery_firm(api, **overrides):
    return get_success_data(api.create_recovery_firm(f.create_recovery_firm_payload(**overrides), ADMIN))


def create_property(api, holder_id, property_type_id, **overrides):
    hh = make_holder_headers(holder_id)
    return get_success_data(api.create_property(
        f.create_property_payload(holder_id, property_type_id, **overrides), hh))


def make_dormant(api, holder_id, property_id):
    hh = make_holder_headers(holder_id)
    return get_success_data(api.evaluate_dormancy(property_id, hh))


# ---------------------------------------------------------------------------
# Escheat pipeline: create -> dormant -> (notice) -> report -> attach -> submit
# -> begin-review -> accept, leaving one property ESCHEATED and custody credited.
# ---------------------------------------------------------------------------
def escheat_property(api, *, amount_cents=100000, interest_bearing=True,
                     dormancy_basis="LAST_ACTIVITY", state_code="CA",
                     incorporation_state="NY", clock="2026-07-15T00:00:00Z",
                     due_diligence=False, dd_min_days=0, pt_code="AC01",
                     dormancy_period_years=3,
                     last_activity_date="2020-01-01T00:00:00Z",
                     issue_date="2020-01-01T00:00:00Z",
                     report_year=2026):
    """Run the full escheat pipeline for one property and return a context dict:
    {holder, pt, state_account, holder_headers, property, report_id, remitted}.

    `clock`, when set, is applied after any due-diligence notice is sent (so the
    notice `sent_at` remains at the earlier logical instant) and before the report
    total is computed, controlling the accrued statutory interest.
    """
    holder = create_holder(api, incorporation_state=incorporation_state)
    pt = create_property_type(api, code=pt_code, dormancy_basis=dormancy_basis,
                              interest_bearing=interest_bearing,
                              dormancy_period_years=dormancy_period_years,
                              due_diligence_required=due_diligence,
                              due_diligence_min_days=dd_min_days)
    sa = create_state_account(api, state_code)
    hh = make_holder_headers(holder["id"])

    prop_payload = f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state=state_code,
        amount_cents=amount_cents, last_activity_date=last_activity_date)
    if dormancy_basis == "ISSUANCE":
        prop_payload["issue_date"] = issue_date
    prop = get_success_data(api.create_property(prop_payload, hh))

    get_success_data(api.evaluate_dormancy(prop["id"], hh))
    if due_diligence:
        get_success_data(api.create_notice(prop["id"], f.notice_payload("MAIL"), hh))
    if clock:
        set_clock(api, clock)

    report = get_success_data(api.create_report(
        f.create_report_payload(holder["id"], state_code, report_year), hh))
    report = get_success_data(api.add_property(
        report["id"], f.add_property_payload(prop["id"], report["version"]), hh))
    declared = report["total_remitted_cents"]
    get_success_data(api.submit_report(report["id"], {"declared_total_cents": declared}, hh))
    ex = make_examiner_headers()
    get_success_data(api.begin_review(report["id"], ex))
    get_success_data(api.accept_report(report["id"], ex))
    prop = get_success_data(api.get_property(prop["id"], hh))
    return {
        "holder": holder,
        "pt": pt,
        "state_account": sa,
        "holder_headers": hh,
        "property": prop,
        "report_id": report["id"],
        "state_code": state_code,
        "remitted": prop["remitted_amount_cents"],
    }


# ---------------------------------------------------------------------------
# Claim lifecycle helpers built on top of an escheated property.
# ---------------------------------------------------------------------------
def file_firm_claim(api, ctx, *, contract_fee_pct=0.10, max_fee_pct=0.10, owner=None, firm=None):
    """File a FIRM claim on ctx['property']; returns the claim dict, and stores
    owner/firm/recovery_headers back on ctx."""
    owner = owner or create_owner(api)
    firm = firm or create_recovery_firm(api, max_fee_pct=max_fee_pct)
    ra = make_recovery_agent_headers(firm["id"])
    claim = get_success_data(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "FIRM",
                               recovery_firm_id=firm["id"], contract_fee_pct=contract_fee_pct), ra))
    ctx.update(owner=owner, firm=firm, recovery_headers=ra, claim=claim)
    return claim


def file_owner_claim(api, ctx, *, owner=None):
    """File an OWNER claim on ctx['property']; returns the claim dict."""
    owner = owner or create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = get_success_data(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh))
    ctx.update(owner=owner, owner_headers=oh, claim=claim)
    return claim


def setup_filed_firm_claim(api, *, amount_cents=100000, interest_bearing=True,
                           contract_fee_pct=0.10, clock="2026-07-15T00:00:00Z"):
    ctx = escheat_property(api, amount_cents=amount_cents,
                           interest_bearing=interest_bearing, clock=clock)
    file_firm_claim(api, ctx, contract_fee_pct=contract_fee_pct)
    return ctx


def setup_examined_firm_claim(api, *, examiner_id="exam-1", **kw):
    ctx = setup_filed_firm_claim(api, **kw)
    ctx["claim"] = get_success_data(api.examine_claim(ctx["claim"]["id"], make_examiner_headers(examiner_id)))
    ctx["examiner_id"] = examiner_id
    return ctx


def setup_approved_firm_claim(api, *, examiner_id="exam-1", approver_id="appr-1", **kw):
    ctx = setup_examined_firm_claim(api, examiner_id=examiner_id, **kw)
    ctx["claim"] = get_success_data(api.approve_claim(ctx["claim"]["id"], make_approver_headers(approver_id)))
    ctx["approver_id"] = approver_id
    return ctx


def setup_paid_firm_claim(api, *, examiner_id="exam-1", approver_id="appr-1", **kw):
    ctx = setup_approved_firm_claim(api, examiner_id=examiner_id, approver_id=approver_id, **kw)
    ctx["claim"] = get_success_data(api.pay_claim(ctx["claim"]["id"], make_approver_headers(approver_id)))
    return ctx


# ---------------------------------------------------------------------------
# Report drafting helpers (no escheat) — for OCC / attach / submit-gate tests.
# ---------------------------------------------------------------------------
def setup_draft_report_with_property(api, *, interest_bearing=False,
                                     dormancy_basis="ISSUANCE", amount_cents=50000,
                                     state_code="CA", report_state=None,
                                     due_diligence=False, dd_min_days=0,
                                     clock=None, report_year=2026):
    """Create a holder + property type + one DORMANT (or DUE_DILIGENCE) property,
    a DRAFT report, and attach the property. Returns a context dict with the
    attached-report version. report_state defaults to state_code."""
    report_state = report_state or state_code
    holder = create_holder(api)
    pt = create_property_type(api, code="MO02" if dormancy_basis == "ISSUANCE" else "AC01",
                              dormancy_basis=dormancy_basis, interest_bearing=interest_bearing,
                              due_diligence_required=due_diligence, due_diligence_min_days=dd_min_days)
    hh = make_holder_headers(holder["id"])
    prop_payload = f.create_property_payload(holder["id"], pt["id"],
                                             owner_last_known_state=state_code,
                                             amount_cents=amount_cents)
    if dormancy_basis == "ISSUANCE":
        prop_payload["issue_date"] = "2020-01-01T00:00:00Z"
    prop = get_success_data(api.create_property(prop_payload, hh))
    get_success_data(api.evaluate_dormancy(prop["id"], hh))
    if due_diligence:
        get_success_data(api.create_notice(prop["id"], f.notice_payload("MAIL"), hh))
    if clock:
        set_clock(api, clock)
    report = get_success_data(api.create_report(
        f.create_report_payload(holder["id"], report_state, report_year), hh))
    attached = get_success_data(api.add_property(
        report["id"], f.add_property_payload(prop["id"], report["version"]), hh))
    return {
        "holder": holder,
        "pt": pt,
        "holder_headers": hh,
        "property": prop,
        "report_id": report["id"],
        "report_version": attached["version"],
        "total_remitted_cents": attached["total_remitted_cents"],
        "state_code": state_code,
    }


def setup_open_audit_case(api, *, holder=None, examiner_id="exam-1"):
    """Create a holder and open one audit case (holder.audit_hold becomes true)."""
    holder = holder or create_holder(api)
    case = get_success_data(api.create_audit_case(
        f.create_audit_case_payload(holder["id"]), make_examiner_headers(examiner_id)))
    return {"holder": holder, "audit_case": case, "holder_headers": make_holder_headers(holder["id"])}
