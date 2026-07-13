"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before every
test. Setup calls use get_success_data (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_defendant_headers,
    make_probation_officer_headers,
)
from .factories import (
    create_defendant_payload,
    create_case_payload,
    create_charge_payload,
    create_courtroom_payload,
    create_arraignment_payload,
    create_diversion_payload,
    create_service_site_payload,
    create_service_assignment_payload,
    create_amnesty_program_payload,
    create_installment_plan_payload,
    create_payment_payload,
    plea_payload,
    progress_payload,
)

CLERK = "court_clerk_headers"
JUDGE = "judge_headers"
CASHIER = "cashier_headers"
ADMIN = "court_admin_headers"


def _d(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Low-level fetch helpers (some entities have no single-GET endpoint).
# --------------------------------------------------------------------------

def fetch_ledger(api, case_id, headers=None):
    headers = headers or TEST_USERS[CLERK]
    arr = _d(api.get_case_ledger_account(case_id, headers))
    assert arr, f"no ledger account found for case {case_id}"
    return arr[0]


def refetch_ledger(api, account_id, headers=None):
    headers = headers or TEST_USERS[CASHIER]
    return _d(api.get_ledger_account(account_id, headers))


def fetch_diversion(api, case_id, diversion_id, headers=None):
    headers = headers or TEST_USERS[CLERK]
    items = _d(api.list_diversion_agreements(case_id, headers))
    for it in items:
        if it["id"] == diversion_id:
            return it
    return items[0]


def fetch_assignment(api, assignment_id, headers=None):
    headers = headers or TEST_USERS[CLERK]
    return _d(api.get_service_assignment(assignment_id, headers))


def fetch_warrant(api, case_id, warrant_id, headers=None):
    headers = headers or TEST_USERS[CLERK]
    items = _d(api.list_warrants(case_id, headers))
    for it in items:
        if it["id"] == warrant_id:
            return it
    return items[0]


def fetch_plan(api, account_id, plan_id, headers=None):
    headers = headers or TEST_USERS[CLERK]
    items = _d(api.list_installment_plans(account_id, headers))
    for it in items:
        if it["id"] == plan_id:
            return it
    return items[0]


def set_clock(api, iso8601):
    api.set_clock(iso8601, TEST_USERS[ADMIN])


def pay(api, account_id, amount, headers=None):
    headers = headers or TEST_USERS[CASHIER]
    return _d(api.create_payment(account_id, create_payment_payload(amount), headers))


# --------------------------------------------------------------------------
# Tier 1/2 — Arraigned case (case ARRAIGNED + provisional LedgerAccount).
# --------------------------------------------------------------------------

def setup_arraigned_case(
    api,
    *,
    charges=None,
    plea="GUILTY",
    offense_date="2026-03-01",
    citation_number="C-0001",
    prior_diversion_count=None,
    buffer_minutes=None,
    room_code="RM",
    room_name="Room",
    scheduled_start="2026-03-05T10:00:00Z",
    scheduled_end="2026-03-05T10:30:00Z",
):
    """Register defendant, docket case, add charge(s), schedule an arraignment,
    and (unless plea is None) enter the plea so the case is ARRAIGNED with a
    PROVISIONAL LedgerAccount. Returns a context dict."""
    clerk = TEST_USERS[CLERK]
    admin = TEST_USERS[ADMIN]

    dpayload = create_defendant_payload()
    if prior_diversion_count is not None:
        dpayload["prior_diversion_count"] = prior_diversion_count
    defendant = _d(api.create_defendant(dpayload, clerk))
    def_headers = make_defendant_headers(defendant["id"])

    case = _d(api.create_case(
        create_case_payload(defendant["id"], citation_number=citation_number,
                            offense_date=offense_date),
        clerk,
    ))

    if charges is None:
        charges = [{}]
    charge_objs = []
    for c in charges:
        charge_objs.append(_d(api.create_charge(case["id"], create_charge_payload(**c), clerk)))

    room_payload = create_courtroom_payload(name=room_name, room_code=room_code)
    if buffer_minutes is not None:
        room_payload["changeover_buffer_minutes"] = buffer_minutes
    courtroom = _d(api.create_courtroom(room_payload, admin))

    arraignment = _d(api.create_arraignment(
        case["id"],
        create_arraignment_payload(courtroom["id"], scheduled_start=scheduled_start,
                                   scheduled_end=scheduled_end),
        clerk,
    ))

    ctx = {
        "defendant": defendant,
        "def_headers": def_headers,
        "case": case,
        "charges": charge_objs,
        "courtroom": courtroom,
        "arraignment": arraignment,
        "ledger_account": None,
    }

    if plea is not None:
        _d(api.enter_plea(arraignment["id"], plea_payload(plea), def_headers))
        ctx["case"] = _d(api.get_case(case["id"], clerk))
        ctx["ledger_account"] = fetch_ledger(api, case["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 3 — Diversion granted / accepted.
# --------------------------------------------------------------------------

def setup_granted_diversion(api, *, diversion_overrides=None, **case_kwargs):
    """Arraigned (GUILTY) case + granted diversion. Case DIVERSION_GRANTED,
    LedgerAccount ASSESSED (final assessment). Returns ctx with 'diversion'."""
    ctx = setup_arraigned_case(api, **case_kwargs)
    judge = TEST_USERS[JUDGE]
    diversion = _d(api.grant_diversion(
        ctx["case"]["id"],
        create_diversion_payload(**(diversion_overrides or {})),
        judge,
    ))
    ctx["diversion"] = diversion
    ctx["case"] = _d(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]))
    ctx["ledger_account"] = fetch_ledger(api, ctx["case"]["id"])
    return ctx


def setup_accepted_diversion(api, **kwargs):
    """Granted diversion + defendant acceptance. DiversionAgreement IN_PROGRESS."""
    ctx = setup_granted_diversion(api, **kwargs)
    _d(api.accept_diversion(ctx["diversion"]["id"], ctx["def_headers"]))
    ctx["diversion"] = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 4 — Service assignment ready for verification.
# --------------------------------------------------------------------------

def setup_service_ready(
    api,
    *,
    pay_ledger,
    mandated_service_hours=10,
    required_class_sessions=0,
    program_fee=100,
    required_hours=10,
    hours_logged=10,
    site_capacity=5,
    creator_officer_id="po_1",
    assignment_type="COMMUNITY_SERVICE",
    site_type="COMMUNITY_SERVICE",
    session_start="2026-03-10T09:00:00Z",
    session_end="2026-03-10T19:00:00Z",
):
    """Accepted diversion, optionally settled ledger, plus one service assignment
    created by `creator_officer_id` and progressed to `hours_logged` (IN_PROGRESS
    when hours_logged>0). Returns ctx with 'site', 'assignment', 'ledger_account'."""
    ctx = setup_accepted_diversion(api, diversion_overrides={
        "mandated_service_hours": mandated_service_hours,
        "required_class_sessions": required_class_sessions,
        "program_fee": program_fee,
    })
    account = ctx["ledger_account"]
    if pay_ledger:
        pay(api, account["id"], account["assessed_amount"])

    admin = TEST_USERS[ADMIN]
    site = _d(api.create_service_site(
        create_service_site_payload(name="Site", site_type=site_type,
                                    concurrent_capacity=site_capacity),
        admin,
    ))
    officer = make_probation_officer_headers(creator_officer_id)
    assignment = _d(api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            site["id"], assignment_type=assignment_type, required_hours=required_hours,
            session_start=session_start, session_end=session_end),
        officer,
    ))
    if hours_logged and hours_logged > 0:
        _d(api.progress_assignment(assignment["id"], progress_payload(hours_logged), officer))
        assignment = fetch_assignment(api, assignment["id"])

    ctx["site"] = site
    ctx["assignment"] = assignment
    ctx["creator_officer_id"] = creator_officer_id
    ctx["ledger_account"] = refetch_ledger(api, account["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 5 — Failed-to-comply / warrant / reinstatement setup.
# --------------------------------------------------------------------------

def setup_failed_case(
    api,
    *,
    with_amnesty=False,
    amnesty_overrides=None,
    with_plan=False,
    plan_installments=6,
    program_deadline="2026-06-01T00:00:00Z",
    warrant_clock="2026-07-01T00:00:00Z",
    mandated_service_hours=10,
    program_fee=100,
):
    """Accepted diversion, optionally with an ACTIVE installment plan and/or a
    created amnesty program, then advance the clock past the deadline and issue a
    warrant. Case FAILED_TO_COMPLY, diversion DEFAULTED, warrant ISSUED. Returns
    ctx with 'warrant' and (optionally) 'amnesty', 'plan', 'plan_after_warrant'."""
    ctx = setup_accepted_diversion(api, diversion_overrides={
        "mandated_service_hours": mandated_service_hours,
        "required_class_sessions": 0,
        "program_fee": program_fee,
        "program_deadline": program_deadline,
    })
    cashier = TEST_USERS[CASHIER]
    judge = TEST_USERS[JUDGE]
    admin = TEST_USERS[ADMIN]
    account = ctx["ledger_account"]

    if with_plan:
        acct = refetch_ledger(api, account["id"])
        plan = _d(api.create_installment_plan(
            account["id"],
            create_installment_plan_payload(plan_installments, acct["version"]),
            cashier,
        ))
        ctx["plan"] = plan

    if with_amnesty:
        amnesty = _d(api.create_amnesty_program(
            create_amnesty_program_payload(**(amnesty_overrides or {})), admin))
        ctx["amnesty"] = amnesty

    set_clock(api, warrant_clock)
    warrant = _d(api.issue_warrant(ctx["case"]["id"], judge))
    ctx["warrant"] = warrant
    ctx["case"] = _d(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]))
    ctx["diversion"] = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    if with_plan:
        ctx["plan_after_warrant"] = fetch_plan(api, account["id"], ctx["plan"]["id"])
    ctx["ledger_account"] = refetch_ledger(api, account["id"])
    return ctx


# --------------------------------------------------------------------------
# Courtroom booking helper (temporal-overlap tests).
# --------------------------------------------------------------------------

def setup_room_with_booking(
    api,
    *,
    buffer_minutes=15,
    existing_start="2026-03-20T10:00:00Z",
    existing_end="2026-03-20T10:30:00Z",
):
    """A courtroom that already hosts one arraignment, plus a second docketed
    case ready to book. Returns (courtroom, case_to_book)."""
    clerk = TEST_USERS[CLERK]
    admin = TEST_USERS[ADMIN]
    room = _d(api.create_courtroom(
        create_courtroom_payload(name="Room O", room_code="O",
                                 changeover_buffer_minutes=buffer_minutes),
        admin,
    ))
    d1 = _d(api.create_defendant(create_defendant_payload(email="one@x.com"), clerk))
    c1 = _d(api.create_case(create_case_payload(d1["id"], citation_number="C-A"), clerk))
    _d(api.create_arraignment(
        c1["id"],
        create_arraignment_payload(room["id"], scheduled_start=existing_start,
                                   scheduled_end=existing_end),
        clerk,
    ))
    d2 = _d(api.create_defendant(create_defendant_payload(email="two@x.com"), clerk))
    c2 = _d(api.create_case(create_case_payload(d2["id"], citation_number="C-B"), clerk))
    return room, c2
