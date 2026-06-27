"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test). These helpers drive empty-DB -> a target precondition using
only PRD-declared endpoints, so individual tests can focus on assertions.

Identity threading: the Fiduciary role is entity-backed. After a fixture creates
a Fiduciary, every ownership-gated call uses make_fiduciary_headers(fiduciary_id)
with the actual id. Opaque roles (Judge/Petitioner/CourtExaminer/CourtClerk) use
stable operator ids so segregation-of-duties checks behave deterministically.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_judge_headers,
    make_petitioner_headers,
    make_examiner_headers,
    make_clerk_headers,
    make_fiduciary_headers,
)
from . import factories as F

# Stable operator ids for opaque roles (distinct so segregation checks pass).
JUDGE_ID = "judge-1"
PETITIONER_ID = "pet-1"
EXAMINER_ID = "exam-1"
CLERK_ID = "clerk-1"

JUDGE = make_judge_headers(JUDGE_ID)
CLERK = make_clerk_headers(CLERK_ID)
EXAMINER = make_examiner_headers(EXAMINER_ID)


def _petitioner(user_id=PETITIONER_ID):
    return make_petitioner_headers(user_id)


# ---------------------------------------------------------------------------
# Tier 0: base reference entities
# ---------------------------------------------------------------------------
def create_person(**overrides) -> dict:
    payload = F.create_protected_person_payload(**overrides)
    return get_success_data(api_client.create_protected_person(payload, CLERK))


def create_fiduciary(**overrides) -> dict:
    payload = F.create_fiduciary_payload(**overrides)
    return get_success_data(api_client.create_fiduciary(payload, CLERK))


def create_case(person_id, **overrides) -> dict:
    payload = F.create_case_payload(person_id, **overrides)
    return get_success_data(api_client.create_case(payload, CLERK))


# ---------------------------------------------------------------------------
# Tier 1: petition lifecycle to a chosen stop
# ---------------------------------------------------------------------------
def file_petition(case_id, fiduciary_id, petitioner_id=PETITIONER_ID, **overrides) -> dict:
    payload = F.create_petition_payload(case_id, fiduciary_id, **overrides)
    return get_success_data(
        api_client.create_petition(payload, _petitioner(petitioner_id))
    )


def petition_to_ready_for_hearing(
    case_type="GUARDIANSHIP",
    requested_authority="PERSON",
    finding="INCAPACITATED",
    recommended_scope="PERSON",
    person_overrides=None,
    fiduciary_overrides=None,
    petitioner_id=PETITIONER_ID,
    examiner_id=EXAMINER_ID,
):
    """Build person + fiduciary + case + petition, then walk the petition through
    probable-cause / order-evaluation / draft+file evaluation so the petition is
    READY_FOR_HEARING. Returns a dict of all created ids and entities."""
    person = create_person(**(person_overrides or {}))
    fiduciary = create_fiduciary(**(fiduciary_overrides or {}))
    case = create_case(person["id"], case_type=case_type)
    petition = file_petition(
        case["id"],
        fiduciary["id"],
        petitioner_id=petitioner_id,
        requested_authority=requested_authority,
    )
    api_client.find_probable_cause(petition["id"], JUDGE)
    api_client.order_evaluation(petition["id"], JUDGE)
    ev_payload = F.create_evaluation_payload(
        petition["id"], finding=finding, recommended_scope=recommended_scope
    )
    evaluation = get_success_data(
        api_client.create_evaluation(ev_payload, make_examiner_headers(examiner_id))
    )
    api_client.file_evaluation(evaluation["id"], make_examiner_headers(examiner_id))
    return {
        "person": person,
        "fiduciary": fiduciary,
        "case": case,
        "petition": petition,
        "evaluation": evaluation,
        "person_id": person["id"],
        "fiduciary_id": fiduciary["id"],
        "case_id": case["id"],
        "petition_id": petition["id"],
        "evaluation_id": evaluation["id"],
    }


def case_to_awaiting_appointment(**kwargs):
    """Petition granted -> case AWAITING_APPOINTMENT. Returns the same dict as
    petition_to_ready_for_hearing plus the granted petition."""
    ctx = petition_to_ready_for_hearing(**kwargs)
    api_client.grant_petition(ctx["petition_id"], JUDGE)
    return ctx


def create_appointment(case_id, fiduciary_id) -> dict:
    payload = F.create_appointment_payload(case_id, fiduciary_id)
    return get_success_data(api_client.create_appointment(payload, JUDGE))


def get_bond_for_appointment(appointment_id) -> dict:
    data, _ = _list(api_client.list_bonds, JUDGE, {"appointment_id": appointment_id})
    return data[0]


def _list(method, headers, params):
    resp = method(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]


def post_and_approve_bond(appointment_id, fiduciary_id, posted_amount_cents=10_000_000) -> dict:
    bond = get_bond_for_appointment(appointment_id)
    api_client.post_bond(
        bond["id"],
        F.post_bond_payload(posted_amount_cents=posted_amount_cents),
        make_fiduciary_headers(fiduciary_id),
    )
    api_client.approve_bond(bond["id"], JUDGE)
    return bond


# ---------------------------------------------------------------------------
# Tier 2/3: qualify -> ACTIVE case
# ---------------------------------------------------------------------------
def active_case(
    case_type="GUARDIANSHIP",
    requested_authority=None,
    finding="INCAPACITATED",
    recommended_scope=None,
    person_overrides=None,
    fiduciary_kind="PROFESSIONAL",
):
    """Drive empty-DB -> a fully ACTIVE case with a qualified fiduciary.

    For bond-requiring cases (CONSERVATORSHIP/PLENARY) the bond is posted and
    approved before qualify. Returns a dict with person/fiduciary/case/petition/
    evaluation/appointment ids and entities.
    """
    requires_bond = case_type in ("CONSERVATORSHIP", "PLENARY")
    if requested_authority is None:
        requested_authority = {
            "GUARDIANSHIP": "PERSON",
            "CONSERVATORSHIP": "ESTATE",
            "PLENARY": "BOTH",
        }[case_type]
    if recommended_scope is None:
        recommended_scope = requested_authority

    ctx = case_to_awaiting_appointment(
        case_type=case_type,
        requested_authority=requested_authority,
        finding=finding,
        recommended_scope=recommended_scope,
        person_overrides=person_overrides,
        fiduciary_overrides={"fiduciary_kind": fiduciary_kind},
    )
    appointment = create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    ctx["appointment"] = appointment
    ctx["appointment_id"] = appointment["id"]
    if requires_bond:
        ctx["bond"] = post_and_approve_bond(appointment["id"], ctx["fiduciary_id"])
        ctx["bond_id"] = ctx["bond"]["id"]
    api_client.qualify_appointment(appointment["id"], JUDGE)
    return ctx


def open_restricted_account(case_id, fiduciary_id) -> dict:
    payload = F.create_restricted_account_payload(case_id)
    return get_success_data(
        api_client.create_restricted_account(payload, make_fiduciary_headers(fiduciary_id))
    )


def fund_account_via_inventory(case_id, fiduciary_id, liquid_assets_cents) -> dict:
    """Create + file + approve an inventory whose liquid_assets fund the account.
    Returns the inventory entity. Requires an OPEN restricted account to exist."""
    inv_payload = F.create_inventory_payload(case_id, liquid_assets_cents=liquid_assets_cents)
    inventory = get_success_data(
        api_client.create_inventory(inv_payload, make_fiduciary_headers(fiduciary_id))
    )
    api_client.file_inventory(inventory["id"], make_fiduciary_headers(fiduciary_id))
    api_client.approve_inventory(inventory["id"], JUDGE)
    return inventory


def current_case_version(case_id) -> int:
    return get_success_data(api_client.get_case(case_id, JUDGE))["version"]


def create_approved_budget(
    case_id,
    fiduciary_id,
    period_year=2026,
    care_cap_cents=0,
    medical_cap_cents=0,
    admin_cap_cents=0,
) -> dict:
    """Draft -> submit -> approve (OCC-guarded) a budget. Returns the budget."""
    bud_payload = F.create_budget_payload(
        case_id,
        period_year=period_year,
        care_cap_cents=care_cap_cents,
        medical_cap_cents=medical_cap_cents,
        admin_cap_cents=admin_cap_cents,
    )
    budget = get_success_data(
        api_client.create_budget(bud_payload, make_fiduciary_headers(fiduciary_id))
    )
    api_client.submit_budget(budget["id"], make_fiduciary_headers(fiduciary_id))
    cv = current_case_version(case_id)
    api_client.approve_budget(budget["id"], F.approve_budget_payload(cv), JUDGE)
    return budget


# ---------------------------------------------------------------------------
# Tier 4: a funded, budgeted, spendable case (the common heavy setup)
# ---------------------------------------------------------------------------
def funded_conservatorship(
    funding_cents=5_000_000,
    care_cap_cents=5_000_000,
    medical_cap_cents=0,
    admin_cap_cents=0,
    period_year=2026,
    fiduciary_kind="PROFESSIONAL",
    person_overrides=None,
):
    """ACTIVE CONSERVATORSHIP, OPEN restricted account funded to `funding_cents`,
    and an APPROVED budget with the given caps. Returns a dict including
    account, budget, and the case version observed after the budget approval.
    """
    if person_overrides is None:
        person_overrides = {"liquid_estate_cents": 8_000_000}
    ctx = active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind=fiduciary_kind,
        person_overrides=person_overrides,
    )
    fid = ctx["fiduciary_id"]
    ctx["account"] = open_restricted_account(ctx["case_id"], fid)
    ctx["account_id"] = ctx["account"]["id"]
    if funding_cents > 0:
        ctx["inventory"] = fund_account_via_inventory(ctx["case_id"], fid, funding_cents)
    ctx["budget"] = create_approved_budget(
        ctx["case_id"],
        fid,
        period_year=period_year,
        care_cap_cents=care_cap_cents,
        medical_cap_cents=medical_cap_cents,
        admin_cap_cents=admin_cap_cents,
    )
    ctx["budget_id"] = ctx["budget"]["id"]
    return ctx


def create_expenditure(case_id, budget_id, fiduciary_id, **overrides) -> dict:
    """Create an expenditure with a freshly-read case version. Returns the entity."""
    cv = current_case_version(case_id)
    payload = F.create_expenditure_payload(case_id, budget_id, cv, **overrides)
    return get_success_data(
        api_client.create_expenditure(payload, make_fiduciary_headers(fiduciary_id))
    )


def disburse(expenditure_id, fiduciary_id):
    return api_client.disburse_expenditure(expenditure_id, make_fiduciary_headers(fiduciary_id))


def create_and_disburse_expenditure(case_id, budget_id, fiduciary_id, **overrides) -> dict:
    """Create (auto-APPROVED path) then disburse. Returns the disbursed entity."""
    exp = create_expenditure(case_id, budget_id, fiduciary_id, **overrides)
    return get_success_data(disburse(exp["id"], fiduciary_id))


# ---------------------------------------------------------------------------
# Accounting helpers
# ---------------------------------------------------------------------------
def create_accounting(case_id, fiduciary_id, **overrides) -> dict:
    payload = F.create_accounting_payload(case_id, **overrides)
    return get_success_data(
        api_client.create_accounting(payload, make_fiduciary_headers(fiduciary_id))
    )


def create_and_submit_accounting(case_id, fiduciary_id, **overrides) -> dict:
    """Create + submit. Returns the SUBMITTED accounting (with derived figures)."""
    ar = create_accounting(case_id, fiduciary_id, **overrides)
    return get_success_data(
        api_client.submit_accounting(ar["id"], make_fiduciary_headers(fiduciary_id))
    )


# ---------------------------------------------------------------------------
# Care-plan helpers
# ---------------------------------------------------------------------------
def create_active_care_plan(case_id, fiduciary_id, **overrides) -> dict:
    payload = F.create_care_plan_payload(case_id, **overrides)
    cp = get_success_data(
        api_client.create_care_plan(payload, make_fiduciary_headers(fiduciary_id))
    )
    api_client.activate_care_plan(cp["id"], make_fiduciary_headers(fiduciary_id))
    return cp


# ---------------------------------------------------------------------------
# Review helpers
# ---------------------------------------------------------------------------
def schedule_review(case_id, subject_kind, subject_ref_id, **overrides) -> dict:
    payload = F.create_review_payload(case_id, subject_kind, subject_ref_id, **overrides)
    return get_success_data(api_client.create_review(payload, JUDGE))


def set_clock(to_iso8601):
    return api_client.set_clock(to_iso8601, CLERK)
