"""Notice order gating, lifecycle edges, lazy expiry, and the logical clock
default (PRD §2.5, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_party,
    create_project,
    create_verified_project,
    get_company,
    get_notice,
    get_project,
    make_customer_admin_headers,
    order_notice,
    publish_rule,
    record_span,
    serve_notice,
    set_clock,
    setup_verified_ca_project,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import create_notice_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


def test_notice_serve_twice_rejected():
    """PRD §3.4: "A successful serve moves the notice `DRAFT` → `SERVED`" and
    PRD §2.10: "when no specific state error applies, the generic
    `ERR_INVALID_STATE` is used."

    Design: Corner/state_machines/notice_serve_twice_rejected
    """
    ctx = setup_verified_ca_project(name="NS Job")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])
    serve_notice(notice["id"], "2026-05-20")

    res = api.serve_notice(notice["id"], {"served_at": "2026-05-21"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    fetched = get_notice(notice["id"])
    assert fetched["status"] == "SERVED"
    assert fetched["served_at"] == "2026-05-20"


def test_notice_proof_on_draft_rejected():
    """PRD §3.4: "Proof can only be recorded on a notice whose `status` is
    `SERVED`; against any other state it fails with `ERR_NOTICE_NOT_SERVED`
    (HTTP 409)."

    Design: Corner/state_machines/notice_proof_on_draft_rejected
    """
    ctx = setup_verified_ca_project(name="NP Job")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])

    res = api.record_notice_proof(
        notice["id"], {"result": "DELIVERED", "proof_url": "https://proof/x"},
        _OPS_AGENT,
    )
    validate_error(res, ApiErrorId.ERR_NOTICE_NOT_SERVED)
    assert get_notice(notice["id"])["status"] == "DRAFT"


def test_notice_clock_expiry_and_terminal_lockdown():
    """PRD §3.4: "a `DRAFT` notice whose `service_deadline` falls behind the
    logical clock auto-expires — lazily, on its next read or mutation — moving
    to `EXPIRED`, decrementing both open-notice counters" and "The full state
    space of a notice order is `DRAFT`, `SERVED`, `PROOF_CONFIRMED`,
    `DELIVERY_FAILED`, and `EXPIRED`, with `PROOF_CONFIRMED` and `EXPIRED`
    terminal."

    Design: Corner/state_machines/notice_clock_expiry_and_terminal_lockdown
    """
    ctx = setup_verified_ca_project(name="NE Job")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])
    assert notice["service_deadline"] == "2026-05-22"
    set_clock("2026-05-23T00:00:00Z")

    assert get_notice(notice["id"])["status"] == "EXPIRED"

    res = api.reprepare_notice(
        notice["id"], make_customer_admin_headers(ctx["company"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_insufficient_balance_notice_create_rejected():
    """PRD §3.4: "the company's `prepaid_balance_cents` must cover the quoted
    fee (`ERR_INSUFFICIENT_BALANCE`, HTTP 402)."

    Design: Corner/validations/insufficient_balance_notice_create_rejected
    """
    ctx = setup_verified_ca_project(name="IB Job", seed_balance_cents=1000)

    res = api.create_notice(
        create_notice_payload(ctx["project"]["id"], ctx["parties"]["OWNER"]["id"]),
        make_customer_admin_headers(ctx["company"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE)
    assert get_company(ctx["company"]["id"])["prepaid_balance_cents"] == 1000


def test_notice_recipient_from_other_project_rejected():
    """PRD §3.4: "the recipient must exist, belong to the same project
    (`ERR_PARTY_PROJECT_MISMATCH`, HTTP 422), and be `VERIFIED`
    (`ERR_PARTY_NOT_VERIFIED`, HTTP 409)"

    Design: Corner/validations/notice_recipient_from_other_project_rejected
    """
    company = create_company(name="XM Co", seed_balance_cents=1000000)
    publish_rule()
    project_a, _parties_a = create_verified_project(company["id"], name="XM A")
    record_span(project_a["id"], company["id"])
    project_b = create_project(company["id"], name="XM B")
    other_owner = create_party(project_b["id"], company["id"], "OWNER", verify=True)

    res = api.create_notice(
        create_notice_payload(project_a["id"], other_owner["id"]),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PARTY_PROJECT_MISMATCH)


def test_delivery_method_not_allowed_rejected():
    """PRD §3.4: "the `delivery_method` must appear in the effective rule's
    `allowed_delivery_methods` (`ERR_DELIVERY_METHOD_NOT_ALLOWED`, HTTP 422)"

    Design: Corner/validations/delivery_method_not_allowed_rejected
    """
    company = create_company(name="DM Co", seed_balance_cents=1000000)
    publish_rule(allowed_delivery_methods=["CERTIFIED_MAIL"])
    project, parties = create_verified_project(company["id"], name="DM Job")
    record_span(project["id"], company["id"])

    res = api.create_notice(
        create_notice_payload(
            project["id"], parties["OWNER"]["id"],
            delivery_method="EMAIL_STATUTORY",
        ),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DELIVERY_METHOD_NOT_ALLOWED)


def test_notice_create_without_active_span_rejected():
    """PRD §3.3: "Any operation whose deadline arithmetic requires furnishing
    dates fails fast when the project has no `ACTIVE` span: ordering a
    preliminary notice, and creating or serving a stop notice, are rejected
    with `ERR_NO_ACTIVE_SPAN` (HTTP 409)."

    Design: Corner/validations/notice_create_without_active_span_rejected
    """
    company = create_company(name="NA Co", seed_balance_cents=1000000)
    publish_rule()
    project, parties = create_verified_project(company["id"], name="NA Job")
    # no furnishing span recorded

    res = api.create_notice(
        create_notice_payload(project["id"], parties["OWNER"]["id"]),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_SPAN)


def test_prelim_deadline_business_day_basis():
    """PRD §2.6: "Under the `BUSINESS` basis only days that are neither Saturday
    nor Sunday count, and the platform observes no holiday calendar."
    PRD §3.3: "`prelim_notice_deadline`, the `first_furnishing_date` plus the
    rule's `prelim_days` counted on its `prelim_day_basis`"

    Design: Corner/calculations/prelim_deadline_business_day_basis
    """
    company = create_company(name="FL Co", seed_balance_cents=1000000)
    publish_rule(state_code="FL", prelim_days=5, prelim_day_basis="BUSINESS")
    project, parties = create_verified_project(
        company["id"], name="FL Job", state_code="FL", county="Dade"
    )
    # first furnishing Friday 2026-05-01; 5 business days -> Friday 2026-05-08
    record_span(project["id"], company["id"],
                start_date="2026-05-01", end_date="2026-05-20")

    n1 = order_notice(project["id"], company["id"], parties["OWNER"]["id"])
    n2 = order_notice(project["id"], company["id"], parties["GC"]["id"])
    assert n1["service_deadline"] == "2026-05-08"

    served = serve_notice(n1["id"], "2026-05-08")
    assert served["status"] == "SERVED"

    res = api.serve_notice(n2["id"], {"served_at": "2026-05-09"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_NOTICE_DEADLINE_PASSED)


def test_clock_default_fixed_at_startup():
    """PRD §2.5: "At server start the logical clock reads exactly
    2026-05-01T00:00:00Z, and it advances only when a `PlatformAdmin` invokes
    the clock-setting capability with a `to_iso8601` instant"

    Design: Corner/cross_cutting_layers/clock_default_fixed_at_startup
    """
    ctx = setup_verified_ca_project(name="CK Job")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])
    assert notice["service_deadline"] == "2026-05-22"

    # no set_current_utc call: the default clock (2026-05-01) precedes the
    # deadline, so no lazy expiry may fire regardless of wall-clock time.
    fetched = get_notice(notice["id"])
    assert fetched["status"] == "DRAFT"


def test_immediate_consistency_on_mutation_responses():
    """PRD §1: "every mutation and all of its cascading side effects are visible
    within that request's own response — there is no eventual consistency
    anywhere in the system."
    PRD §3.4: "The fee is debited from the company's `prepaid_balance_cents` at
    creation, incrementing the company's `version` by one"

    Design: Corner/consistency_model/immediate_consistency_on_mutation_responses
    """
    ctx = setup_verified_ca_project(name="IM Job", seed_balance_cents=1000000)

    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])
    # OWNER + CERTIFIED_MAIL: 1499 + 899 = 2398 debited at creation
    assert notice["fee_cents"] == 2398
    assert get_company(ctx["company"]["id"])["prepaid_balance_cents"] == 997602

    served = serve_notice(notice["id"], "2026-05-20")
    assert served["status"] == "SERVED"
    assert served["served_at"] == "2026-05-20"
