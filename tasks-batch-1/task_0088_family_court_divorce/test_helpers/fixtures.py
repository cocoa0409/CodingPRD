"""Composite setup helpers for the Family Court Divorce API.

Each test runs against a freshly re-launched, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() (lenient 2xx) so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing assertion failure.

Ownership-gated calls (submit disclosure, propose/dispute/agree/revise plan) use
make_petitioner_headers / make_respondent_headers bound to the actual Party's
user_id (PRD §2.1 entity_backed:Party).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_petitioner_headers,
    make_respondent_headers,
    make_judge_headers,
    make_mediator_headers,
)
from . import factories as F
from .constants import (
    CA_WIDE_TIER,
    CA_FULL_TIERS,
    DEFAULT_MEDIATOR_USER_ID,
    DEFAULT_JUDGE_USER_ID,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — atomic creates
# ---------------------------------------------------------------------------
def register_schedule(state_code="CA", tiers=None, **overrides):
    """POST /api/guideline-schedules. Returns the schedule dict."""
    if tiers is None:
        tiers = [dict(t) for t in CA_WIDE_TIER]
    payload = F.guideline_schedule_payload(
        state_code=state_code, basic_obligation_tiers=tiers, **overrides)
    return get_success_data(_api.create_guideline_schedule(payload, CLERK))


def create_case(state_code="CA", marriage_months=84, caption="In re Marriage of Test",
                filing_fee_cents=43500, register=True, tiers=None, **overrides):
    """Register a schedule (optional) + open a case in FILED. Returns the case dict."""
    if register:
        register_schedule(state_code=state_code, tiers=tiers)
    payload = F.case_payload(state_code=state_code, marriage_months=marriage_months,
                             caption=caption, filing_fee_cents=filing_fee_cents, **overrides)
    return get_success_data(_api.create_case(payload, CLERK))


def add_petitioner(case_id, user_id="u-pet", gross_monthly_income_cents=800000, full_name="Pat"):
    return get_success_data(_api.create_party(
        F.party_payload(case_id, "PETITIONER", user_id,
                        gross_monthly_income_cents=gross_monthly_income_cents,
                        full_name=full_name), CLERK))


def add_respondent(case_id, user_id="u-res", gross_monthly_income_cents=400000, full_name="Robin"):
    return get_success_data(_api.create_party(
        F.party_payload(case_id, "RESPONDENT", user_id,
                        gross_monthly_income_cents=gross_monthly_income_cents,
                        full_name=full_name), CLERK))


def add_child(case_id, full_name="Child One", birth_year=2016):
    return get_success_data(_api.create_child(
        F.child_payload(case_id, full_name=full_name, birth_year=birth_year), CLERK))


def file_pleading(case_id, pleading_type, filed_by_party_id):
    return get_success_data(_api.create_pleading(
        F.pleading_payload(case_id, pleading_type, filed_by_party_id), CLERK))


def serve_pleading(pleading_id):
    return get_success_data(_api.serve_pleading(pleading_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 2 — case hierarchies / state progression
# ---------------------------------------------------------------------------
def setup_filed_case_with_petitioner(pet_gross=800000, **case_overrides):
    """Schedule + case FILED + petitioner + DRAFT PETITION (not yet served).
    Returns (case, pet, petition)."""
    case = create_case(**case_overrides)
    pet = add_petitioner(case["id"], gross_monthly_income_cents=pet_gross)
    petition = file_pleading(case["id"], "PETITION", pet["id"])
    return case, pet, petition


def setup_awaiting_response(pet_gross=800000, **case_overrides):
    """Case advanced to AWAITING_RESPONSE (petition served). Returns (case, pet, petition)."""
    case, pet, petition = setup_filed_case_with_petitioner(pet_gross=pet_gross, **case_overrides)
    serve_pleading(petition["id"])
    return case, pet, petition


def setup_default_pending(pet_gross=800000, res_gross=400000, with_respondent=True,
                          children=0, **case_overrides):
    """Default path: case in DEFAULT_PENDING (no answer; petition served, defaulted).
    Adds a respondent and optional children. Returns
    {case, pet, res, petition, children: [...]}."""
    case, pet, petition = setup_filed_case_with_petitioner(pet_gross=pet_gross, **case_overrides)
    res = add_respondent(case["id"], gross_monthly_income_cents=res_gross) if with_respondent else None
    serve_pleading(petition["id"])
    kids = [add_child(case["id"], full_name=f"Child {i+1}", birth_year=2016 + i)
            for i in range(children)]
    get_success_data(_api.default_case(case["id"], CLERK))
    return {"case": case, "pet": pet, "res": res, "petition": petition, "children": kids}


def setup_contested_discovery(pet_gross=800000, res_gross=400000, children=0, **case_overrides):
    """Contested path: case advanced to DISCOVERY (petition served, answer served, advance).
    Returns {case, pet, res, petition, answer, children: [...]}."""
    case, pet, petition = setup_filed_case_with_petitioner(pet_gross=pet_gross, **case_overrides)
    res = add_respondent(case["id"], gross_monthly_income_cents=res_gross)
    serve_pleading(petition["id"])
    answer = file_pleading(case["id"], "ANSWER", res["id"])
    serve_pleading(answer["id"])
    get_success_data(_api.advance_case(case["id"], {"to_status": "DISCOVERY"}, CLERK))
    kids = [add_child(case["id"], full_name=f"Child {i+1}", birth_year=2016 + i)
            for i in range(children)]
    return {"case": case, "pet": pet, "res": res, "petition": petition,
            "answer": answer, "children": kids}


# ---------------------------------------------------------------------------
# Tier 3 — disclosures
# ---------------------------------------------------------------------------
def create_disclosure(party_id, case_id, user_id, role, **fields):
    """Create a DRAFT disclosure owned by the given party's user_id."""
    payload = F.financial_disclosure_payload(party_id, case_id, **fields)
    headers = (make_petitioner_headers(user_id) if role == "PETITIONER"
               else make_respondent_headers(user_id))
    return get_success_data(_api.create_financial_disclosure(payload, headers))


def submit_disclosure(disclosure_id, user_id, role):
    headers = (make_petitioner_headers(user_id) if role == "PETITIONER"
               else make_respondent_headers(user_id))
    return get_success_data(_api.submit_financial_disclosure(disclosure_id, headers))


def verify_disclosure(disclosure_id):
    return get_success_data(_api.verify_financial_disclosure(disclosure_id, CLERK))


def submitted_disclosure(party_id, case_id, user_id, role, **fields):
    """Create + submit a disclosure (SUBMITTED). Returns the submitted disclosure dict."""
    fd = create_disclosure(party_id, case_id, user_id, role, **fields)
    return submit_disclosure(fd["id"], user_id, role)


def verified_disclosure(party_id, case_id, user_id, role, **fields):
    """Create + submit + verify a disclosure (VERIFIED). Returns the verified dict."""
    fd = create_disclosure(party_id, case_id, user_id, role, **fields)
    submit_disclosure(fd["id"], user_id, role)
    return verify_disclosure(fd["id"])


# ---------------------------------------------------------------------------
# Tier 3 — parenting plan
# ---------------------------------------------------------------------------
def propose_plan(case_id, proposed_by_party_id, proposer_user_id, proposer_role,
                 petitioner_overnights=110, respondent_overnights=255):
    headers = (make_petitioner_headers(proposer_user_id) if proposer_role == "PETITIONER"
               else make_respondent_headers(proposer_user_id))
    payload = F.parenting_plan_payload(case_id, proposed_by_party_id,
                                       petitioner_overnights, respondent_overnights)
    return get_success_data(_api.create_parenting_plan(payload, headers))


def agree_plan(plan_id, actor_user_id, actor_role):
    headers = (make_petitioner_headers(actor_user_id) if actor_role == "PETITIONER"
               else make_respondent_headers(actor_user_id))
    return get_success_data(_api.agree_parenting_plan(plan_id, headers))


# ---------------------------------------------------------------------------
# Tier 4 — mediation
# ---------------------------------------------------------------------------
def assign_mediator(case_id, mediator_user_id=DEFAULT_MEDIATOR_USER_ID):
    """Clerk assigns a mediator (DISCOVERY -> MEDIATION). Returns the case dict."""
    return get_success_data(_api.assign_mediator(
        case_id, {"mediator_user_id": mediator_user_id}, CLERK))


def schedule_session(case_id, mediator_user_id=DEFAULT_MEDIATOR_USER_ID,
                     scheduled_start="2026-07-01T09:00:00Z",
                     scheduled_end="2026-07-01T11:00:00Z"):
    payload = F.mediation_session_payload(case_id, mediator_user_id, scheduled_start, scheduled_end)
    return get_success_data(_api.create_mediation_session(payload, make_mediator_headers(mediator_user_id)))


def start_session(session_id, mediator_user_id=DEFAULT_MEDIATOR_USER_ID):
    return get_success_data(_api.start_mediation_session(session_id, make_mediator_headers(mediator_user_id)))


def conclude_session(session_id, outcome, mediator_user_id=DEFAULT_MEDIATOR_USER_ID):
    return get_success_data(_api.conclude_mediation_session(
        session_id, {"outcome": outcome}, make_mediator_headers(mediator_user_id)))


def setup_case_in_mediation(pet_gross=800000, res_gross=400000,
                            mediator_user_id=DEFAULT_MEDIATOR_USER_ID,
                            verify_respondent=False, children=0, **case_overrides):
    """Contested case -> DISCOVERY, both disclosures SUBMITTED (petitioner VERIFIED,
    respondent VERIFIED only if requested), mediator assigned (MEDIATION).
    Returns dict with case, pet, res, pet_fd, res_fd, plus children."""
    ctx = setup_contested_discovery(pet_gross=pet_gross, res_gross=res_gross,
                                    children=children, **case_overrides)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    pet_fd = create_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                               gross_monthly_income_cents=720000,
                               tax_withholding_cents=120000,
                               mandatory_retirement_cents=0, health_insurance_cents=0)
    submit_disclosure(pet_fd["id"], "u-pet", "PETITIONER")
    verify_disclosure(pet_fd["id"])
    res_fd = create_disclosure(res["id"], case["id"], "u-res", "RESPONDENT",
                               gross_monthly_income_cents=360000,
                               tax_withholding_cents=60000,
                               mandatory_retirement_cents=0, health_insurance_cents=0)
    submit_disclosure(res_fd["id"], "u-res", "RESPONDENT")
    if verify_respondent:
        verify_disclosure(res_fd["id"])
    assign_mediator(case["id"], mediator_user_id)
    ctx.update({"pet_fd": pet_fd, "res_fd": res_fd})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — support orders & court orders
# ---------------------------------------------------------------------------
def create_support_order(case_id, support_type, payor_party_id, payee_party_id, variant):
    return get_success_data(_api.create_support_order(
        F.support_order_payload(case_id, support_type, payor_party_id, payee_party_id, variant),
        CLERK))


def draft_court_order(case_id, order_kind, support_order_ids, **kw):
    """Draft a court order. Judge drafts FINAL_JUDGMENT; clerk drafts TEMPORARY."""
    headers = make_judge_headers(kw.pop("judge_user_id", DEFAULT_JUDGE_USER_ID)) \
        if order_kind == "FINAL_JUDGMENT" else CLERK
    return get_success_data(_api.create_court_order(
        F.court_order_payload(case_id, order_kind, support_order_ids, **kw), headers))


def enter_temporary_order(order_id, judge_user_id=DEFAULT_JUDGE_USER_ID):
    return get_success_data(_api.enter_court_order(order_id, {}, make_judge_headers(judge_user_id)))


def advance_case(case_id, to_status):
    """Clerk-driven administrative status advance. Returns the case dict."""
    return get_success_data(_api.advance_case(case_id, {"to_status": to_status}, CLERK))


def current_case_version(case_id):
    case = get_success_data(_api.get_case(case_id, CLERK))
    return case["version"]


def setup_default_awaiting_judgment_with_temp_order(**case_overrides):
    """DEFAULT path through to AWAITING_JUDGMENT with a TEMPORARY CourtOrder already
    ENTERED (CHILD order ACTIVE @ 150000) and a FINAL CHILD SupportOrder CALCULATED
    @ 100000, plus a DRAFT FINAL_JUDGMENT superseding the temporary order.

    Income: declared gross 800000/400000 -> temporary tier2 base 150000;
    verified net 600000/300000 -> final tier1 base 100000.
    Returns dict: case, pet, res, plan, temp_child, temp_order, final_child, final_order.
    """
    ctx = setup_default_pending(pet_gross=800000, res_gross=400000, children=2,
                                tiers=[dict(t) for t in CA_FULL_TIERS], **case_overrides)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    # TEMPORARY CHILD order (declared gross): tier2 base 150000.
    temp_child = create_support_order(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY")
    temp_order = draft_court_order(case["id"], "TEMPORARY", [temp_child["id"]])
    enter_temporary_order(temp_order["id"])
    # Verify both parties so FINAL math (net) is available and the FINAL_JUDGMENT can enter.
    verified_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                        gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                        mandatory_retirement_cents=0, health_insurance_cents=0)
    verified_disclosure(res["id"], case["id"], "u-res", "RESPONDENT",
                        gross_monthly_income_cents=360000, tax_withholding_cents=60000,
                        mandatory_retirement_cents=0, health_insurance_cents=0)
    get_success_data(_api.advance_case(case["id"], {"to_status": "AWAITING_JUDGMENT"}, CLERK))
    final_child = create_support_order(case["id"], "CHILD", pet["id"], res["id"], "FINAL")
    final_order = draft_court_order(case["id"], "FINAL_JUDGMENT", [final_child["id"]],
                                    parenting_plan_id=plan["id"],
                                    supersedes_order_id=temp_order["id"])
    return {"case": case, "pet": pet, "res": res, "plan": plan,
            "temp_child": temp_child, "temp_order": temp_order,
            "final_child": final_child, "final_order": final_order}


def setup_default_awaiting_judgment_final_only(**case_overrides):
    """DEFAULT path to AWAITING_JUDGMENT (petitioner verified only), one child, a
    TEMPORARY CHILD SupportOrder CALCULATED, and a DRAFT FINAL_JUDGMENT referencing it.
    Returns dict: case, pet, res, plan, support, final_order.
    Used for OCC / forbidden-role / SoD-style enter tests where the support order is
    intentionally left CALCULATED (no temporary order entered)."""
    ctx = setup_default_pending(pet_gross=800000, res_gross=400000, children=1, **case_overrides)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    verified_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                        gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                        mandatory_retirement_cents=0, health_insurance_cents=0)
    get_success_data(_api.advance_case(case["id"], {"to_status": "AWAITING_JUDGMENT"}, CLERK))
    support = create_support_order(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY")
    final_order = draft_court_order(case["id"], "FINAL_JUDGMENT", [support["id"]],
                                    parenting_plan_id=plan["id"])
    return {"case": case, "pet": pet, "res": res, "plan": plan,
            "support": support, "final_order": final_order}
