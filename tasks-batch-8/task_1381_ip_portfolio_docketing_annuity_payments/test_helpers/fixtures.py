"""Composite setup helpers.

Each helper builds a reachable system state using only PRD-declared endpoints,
so tests can focus on assertions. All setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    US_RULE_PAYLOAD,
    EP_RULE_PAYLOAD,
    create_jurisdiction_rule_payload,
    create_client_payload,
    create_contact_payload,
    create_counsel_firm_payload,
    create_inventor_payload,
    create_family_payload,
    create_application_payload,
    create_docket_entry_payload,
    create_office_action_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_approver_headers,
    make_outside_counsel_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]
MGR2 = TEST_USERS["manager2_headers"]
REC = TEST_USERS["records_headers"]
FIN = TEST_USERS["finance_headers"]
ANY = TEST_USERS["any_headers"]


def _ok(resp, label):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({label}): expected object payload, got {data!r}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: configuration + base tree
# ---------------------------------------------------------------------------

def create_us_rule(**overrides):
    """Create the canonical US jurisdiction rule. Returns the rule dict."""
    payload = create_jurisdiction_rule_payload(**overrides)
    return _ok(api_client.create_jurisdiction_rule(payload, ADMIN), "create_us_rule")


def create_rule(payload):
    return _ok(api_client.create_jurisdiction_rule(payload, ADMIN), "create_rule")


def create_client(display_name="Test Client"):
    return _ok(api_client.create_client(create_client_payload(display_name=display_name), ADMIN), "create_client")


def create_contact(client_id, full_name="C Approver", email="ca@x.com"):
    return _ok(
        api_client.create_contact(client_id, create_contact_payload(full_name=full_name, email=email), ADMIN),
        "create_contact",
    )


def create_family(client_id, budget_cap_cents=1000000, title="Test Family",
                  first_priority_date="2026-01-15", headers=None):
    return _ok(
        api_client.create_family(
            client_id,
            create_family_payload(
                title=title,
                first_priority_date=first_priority_date,
                budget_cap_cents=budget_cap_cents,
            ),
            headers or MGR,
        ),
        "create_family",
    )


def create_application(family_id, headers=None, **overrides):
    return _ok(
        api_client.create_application(family_id, create_application_payload(**overrides), headers or CLERK),
        "create_application",
    )


# ---------------------------------------------------------------------------
# Tier 2: application state progression
# ---------------------------------------------------------------------------

def create_pending_application(family_id, **overrides):
    """Create an application and file it (DRAFT -> PENDING)."""
    app = create_application(family_id, **overrides)
    filed = _ok(api_client.file_application(app["id"], CLERK), "file_application")
    return filed


def create_granted_application(family_id, grant_date="2026-03-01", **overrides):
    """Create -> file -> grant. Returns the GRANTED application."""
    app = create_pending_application(family_id, **overrides)
    granted = _ok(
        api_client.grant_application(app["id"], {"grant_date": grant_date}, CLERK),
        "grant_application",
    )
    return granted


def list_obligations(application_id):
    data = get_success_data(api_client.list_annuity_obligations_of_application(application_id, ANY))
    assert isinstance(data, list), f"Setup failed (list_obligations): {data!r}"
    return data


def get_obligation(obligation_id):
    return _ok(api_client.get_annuity_obligation(obligation_id, ANY), "get_obligation")


def get_application(application_id):
    return _ok(api_client.get_application(application_id, ANY), "get_application")


def get_family(family_id):
    return _ok(api_client.get_family(family_id, ANY), "get_family")


# ---------------------------------------------------------------------------
# Tier 3: authorization workflow shortcuts
# ---------------------------------------------------------------------------

def request_authorization(obligation_id, amount_cents, requester_headers=None):
    """Create a PaymentAuthorization for a SCHEDULED obligation (OCC read inside).

    Returns (authorization, obligation_version_before).
    """
    ob = get_obligation(obligation_id)
    version = ob["version"]
    au = _ok(
        api_client.create_authorization(
            obligation_id,
            {"amount_cents": amount_cents, "expected_annuity_obligation_version": version},
            requester_headers or MGR,
        ),
        "create_authorization",
    )
    return au, version


def approve_authorization(authorization_id, contact_id):
    return _ok(
        api_client.approve_authorization(authorization_id, make_client_approver_headers(contact_id)),
        "approve_authorization",
    )


def release_authorization(authorization_id):
    return _ok(api_client.release_authorization(authorization_id, FIN), "release_authorization")


def authorize_obligation(obligation_id, amount_cents, contact_id, requester_headers=None):
    """Request + approve. Returns the APPROVED authorization."""
    au, _ = request_authorization(obligation_id, amount_cents, requester_headers)
    approve_authorization(au["id"], contact_id)
    return au


def instruct_obligation(obligation_id, amount_cents, contact_id, requester_headers=None):
    """Request + approve + release + instruct-payment. Returns the authorization."""
    au = authorize_obligation(obligation_id, amount_cents, contact_id, requester_headers)
    release_authorization(au["id"])
    _ok(api_client.instruct_payment(obligation_id, FIN), "instruct_payment")
    return au


# ---------------------------------------------------------------------------
# Tier 4: full-world composites used across many scenarios
# ---------------------------------------------------------------------------

def setup_world_us(budget_cap_cents=1000000, client_name="WorldCo"):
    """US rule + client + contact + family. Returns dict of the created rows."""
    create_us_rule()
    client = create_client(client_name)
    contact = create_contact(client["id"])
    family = create_family(client["id"], budget_cap_cents=budget_cap_cents)
    return {"client": client, "contact": contact, "family": family}


def setup_world_with_granted_app(budget_cap_cents=1000000, client_name="WorldCo",
                                 grant_date="2026-03-01", **app_overrides):
    """US world + one GRANTED application. Returns world dict including app + obligations."""
    world = setup_world_us(budget_cap_cents=budget_cap_cents, client_name=client_name)
    app = create_granted_application(world["family"]["id"], grant_date=grant_date, **app_overrides)
    world["application"] = app
    world["obligations"] = list_obligations(app["id"])
    return world


def setup_ep_world_with_authorized_y1():
    """EP rule (fx 10255, tiers 10000/1000/3000 for years 1/2/3) + one GRANTED
    LARGE EP application (grant 2026-03-01) whose year-1 obligation is
    AUTHORIZED at 10255; years 2 and 3 remain SCHEDULED.

    Returns dict with family, application, obligations list and authorization.
    """
    create_rule(EP_RULE_PAYLOAD)
    client = create_client("Acme EP")
    contact = create_contact(client["id"])
    family = create_family(client["id"], budget_cap_cents=1000000)
    app = create_granted_application(
        family["id"],
        grant_date="2026-03-01",
        jurisdiction="EP",
        application_number="EP-1",
    )
    obligations = list_obligations(app["id"])
    au = authorize_obligation(obligations[0]["id"], 10255, contact["id"])
    return {
        "client": client,
        "contact": contact,
        "family": family,
        "application": app,
        "obligations": list_obligations(app["id"]),
        "authorization": au,
    }


def setup_oa_response_entry(world_application_id, mail_date="2026-05-20"):
    """Record a NON_FINAL_REJECTION office action and return (action, entry)."""
    action = _ok(
        api_client.create_office_action(
            world_application_id,
            create_office_action_payload(mail_date=mail_date),
            CLERK,
        ),
        "create_office_action",
    )
    entry = _ok(api_client.get_docket_entry(action["docket_entry_id"], ANY), "get_oa_entry")
    return action, entry


def setup_counsel_firm(accredited=("US",), display_name="Firm US"):
    return _ok(
        api_client.create_counsel_firm(
            create_counsel_firm_payload(display_name=display_name,
                                        accredited_jurisdictions=list(accredited)),
            ADMIN,
        ),
        "create_counsel_firm",
    )


def send_instruction(application_id, firm, instruction_type="FILING", due_date="2026-09-01",
                     docket_entry_id=None):
    """Create + send an instruction. Returns the SENT instruction."""
    payload = {
        "counsel_firm_id": firm["id"],
        "instruction_type": instruction_type,
        "due_date": due_date,
    }
    if docket_entry_id is not None:
        payload["docket_entry_id"] = docket_entry_id
    ins = _ok(api_client.create_instruction(application_id, payload, CLERK), "create_instruction")
    sent = _ok(api_client.send_instruction(ins["id"], CLERK), "send_instruction")
    return sent


def acknowledge_instruction(instruction_id, firm_id):
    return _ok(
        api_client.acknowledge_instruction(instruction_id, make_outside_counsel_headers(firm_id)),
        "acknowledge_instruction",
    )


def confirm_instruction(instruction_id, firm_id):
    return _ok(
        api_client.confirm_instruction(instruction_id, make_outside_counsel_headers(firm_id)),
        "confirm_instruction",
    )


def propose_review(application_id, rationale="prune low value", headers=None):
    """Create an AbandonmentReview with a fresh OCC read. Returns the PROPOSED review."""
    app = get_application(application_id)
    return _ok(
        api_client.create_abandonment_review(
            application_id,
            {"rationale": rationale, "expected_application_version": app["version"]},
            headers or MGR,
        ),
        "create_abandonment_review",
    )


def propose_and_submit_review(application_id, submitter_headers=None):
    """Create + submit a review. Returns the UNDER_REVIEW review."""
    review = propose_review(application_id)
    return _ok(
        api_client.submit_abandonment_review(review["id"], submitter_headers or MGR),
        "submit_abandonment_review",
    )


def approved_review(application_id, family_id=None, enter_pruning=False):
    """Create + submit (mgr-1) + approve (mgr-2). Returns the APPROVED review."""
    if enter_pruning and family_id is not None:
        _ok(api_client.enter_pruning_review(family_id, MGR), "enter_pruning_review")
    review = propose_review(application_id, headers=MGR)
    _ok(api_client.submit_abandonment_review(review["id"], MGR), "submit_review")
    return _ok(api_client.approve_abandonment_review(review["id"], MGR2), "approve_review")


def set_clock(to_iso8601):
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set_clock")
