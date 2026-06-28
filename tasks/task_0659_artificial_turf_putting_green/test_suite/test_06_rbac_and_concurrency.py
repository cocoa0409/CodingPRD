"""Role-based access control (peer roles, ownership) and optimistic concurrency
on quote acceptance.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── Corner: rbac ────────────────────────────────────────────────────────────
def test_scheduler_cannot_create_design(api):
    """PRD §2.1: "When a role is authenticated but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "The `SalesRep` role owns the pre-sale pipeline — customers, site
    measures, design layouts, base-prep scopes, quotes, and warranty plans."

    Design: Corner/rbac/scheduler_cannot_create_design
    """
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    resp = api_client.create_design_layout(
        project["id"],
        {
            "site_measure_id": measure["id"],
            "turf_product_id": turf["id"],
            "infill_product_id": infill["id"],
            "variant": "STANDARD",
        },
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_accept_other_customers_quote(api):
    """PRD §2.1: "a `Customer` may act only on a project they own, where ownership
    means the project's `customer_id` equals the caller's `X-User-ID`. A `Customer`
    who targets a project that is not theirs is rejected with
    `ERR_NOT_PROJECT_OWNER`."

    Design: Corner/rbac/customer_cannot_accept_other_customers_quote
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    qid = ctx["quote"]["id"]
    other = fx.create_customer(full_name="Other B", email="otherb@x.com")
    v = fx.project_version(pid)
    resp = api_client.accept_quote(
        pid, qid, f.accept_quote_payload(v), make_customer_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value)
    quote = validate_success(api_client.get_quote(pid, qid, SALES))
    assert quote["status"] == "SENT"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and
    `X-User-Role`, which declares the capacity in which they are acting. A request
    missing either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.list_projects({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Corner: cross_cutting_complexity_layers (OCC) ───────────────────────────
def test_stale_then_fresh_quote_accept(api):
    """PRD §2.8: "A customer accepting a sent quote must supply
    `expected_project_version` in the request body, carrying the `version` of the
    `Project` as the client last observed it. If that value does not match the
    project's current `version`, the acceptance is rejected with
    `ERR_STALE_PROJECT_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_quote_accept
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD", quote_overrides={"deposit_pct": 0.30})
    pid = ctx["project"]["id"]
    q1 = ctx["quote"]["id"]
    cust_id = ctx["customer"]["id"]
    # Capture a version, then create + send a sibling quote which bumps the project version.
    v_stale = fx.project_version(pid)
    q2 = fx.create_quote(pid, ctx["design"]["id"], ctx["scope"]["id"], deposit_pct=0.40)
    fx.send_quote(pid, q2["id"])
    # Stale accept rejected.
    resp = api_client.accept_quote(
        pid, q1, f.accept_quote_payload(v_stale), make_customer_headers(cust_id)
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)
    # Fresh accept succeeds.
    v_fresh = fx.project_version(pid)
    accepted = validate_success(
        api_client.accept_quote(pid, q1, f.accept_quote_payload(v_fresh), make_customer_headers(cust_id))
    )
    assert accepted["status"] == "ACCEPTED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["finance_status"] == "DEPOSIT_DUE"


def test_fresh_version_accept_advances_finance(api):
    """PRD §3.6: "Acceptance moves the quote from `SENT` to `ACCEPTED`; voids every
    other non-terminal quote on the project (any sibling quote in `DRAFT`, `SENT`,
    or `REVISED` moves to `VOID`); advances the project's `finance_status` from
    `UNBILLED` to `DEPOSIT_DUE`; and increments both the quote's `version` and the
    project's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_quote_accept
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD", quote_overrides={"deposit_pct": 0.30})
    pid = ctx["project"]["id"]
    qid = ctx["quote"]["id"]
    cust_id = ctx["customer"]["id"]
    v = fx.project_version(pid)
    accepted = validate_success(
        api_client.accept_quote(pid, qid, f.accept_quote_payload(v), make_customer_headers(cust_id))
    )
    assert accepted["status"] == "ACCEPTED"
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["finance_status"] == "DEPOSIT_DUE"
