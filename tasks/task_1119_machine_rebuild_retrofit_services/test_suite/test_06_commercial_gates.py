"""Commercial gates on the quote lifecycle: staleness, approval preconditions,
the referential-before-fiscal ordering, and the sourcing approval gate."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    make_customer_headers,
    validate_error,
)


def test_part_line_added_after_compute_makes_quote_stale(api):
    """PRD §3.4: "The new line is born `PENDING`, and if the project has already computed at least one quote, adding the line raises `quote_stale` to `true`."
    PRD §3.3: "Approval is then the customer's act: the caller's `X-User-ID` must equal the project's `customer_id`, the quote must still be unstale (again `ERR_QUOTE_STALE`), and — as the final fiscal gate of the validation cascade — `quote_price_cents` must not exceed the customer's `credit_limit_cents`, failing which the approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/quote_approve_referential_beats_fiscal
    """
    ctx = fx.setup_project_decided()
    project_id = ctx.project["id"]
    fx.compute_quote(project_id)
    fx.send_quote(project_id)

    fx.add_part_line(project_id, ctx.parts[0]["id"], 1)
    stale_view = fx.get_project(project_id)
    assert stale_view["quote_stale"] is True
    assert stale_view["commercial_status"] == "QUOTE_SENT"

    res = api.approve_quote(project_id, make_customer_headers(ctx.customer["id"]))
    validate_error(res, ApiErrorId.ERR_QUOTE_STALE.value)


def test_stale_quote_error_precedes_credit_limit_error(api):
    """PRD §2.8: "Every request passes through a fixed cascade of validation gates, evaluated in the order below. When several gates would fail, the earliest failing gate's error is the one reported, so higher-priority failures are never masked by lower-priority ones."
    PRD §2.8: "The ordering has observable consequences: a stale version surfaces as a 412 before any state-machine complaint; a claim filed after the warranty has lapsed reports `ERR_WARRANTY_EXPIRED` before its drift magnitude is ever examined; and the credit-limit check at quote approval is the last gate, so every state and referential problem surfaces first."

    Design: Difficulty/priority_pair_validation_conflict/quote_approve_referential_beats_fiscal
    """
    # A zero credit limit arms the fiscal gate under any configuration: the
    # computed quote always exceeds it because the pinned line prices alone
    # are positive. The stale quote arms the referential gate at the same time.
    ctx = fx.setup_project_decided(customer_overrides={"credit_limit_cents": 0})
    project_id = ctx.project["id"]
    project = fx.compute_quote(project_id)
    assert project["quote_price_cents"] > 0
    fx.send_quote(project_id)
    fx.add_part_line(project_id, ctx.parts[0]["id"], 1)
    assert fx.get_project(project_id)["quote_stale"] is True

    res = api.approve_quote(project_id, make_customer_headers(ctx.customer["id"]))
    validate_error(res, ApiErrorId.ERR_QUOTE_STALE.value)


def test_credit_limit_exceeded_on_approve(api):
    """PRD §3.3: "Approval is then the customer's act: the caller's `X-User-ID` must equal the project's `customer_id`, the quote must still be unstale (again `ERR_QUOTE_STALE`), and — as the final fiscal gate of the validation cascade — `quote_price_cents` must not exceed the customer's `credit_limit_cents`, failing which the approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_exceeded_on_approve
    """
    # Zero credit limit: the fresh quote necessarily exceeds it because the
    # pinned line prices alone keep quote_price_cents strictly positive.
    ctx = fx.setup_project_decided(customer_overrides={"credit_limit_cents": 0})
    project_id = ctx.project["id"]
    project = fx.compute_quote(project_id)
    assert project["quote_price_cents"] > 0
    fx.send_quote(project_id)
    assert fx.get_project(project_id)["quote_stale"] is False

    res = api.approve_quote(project_id, make_customer_headers(ctx.customer["id"]))
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    after = fx.get_project(project_id)
    assert after["commercial_status"] == "QUOTE_SENT"


def test_begin_sourcing_requires_approved_quote_rejected(api):
    """PRD §3.4: "The commercial dimension must already be `APPROVED`, otherwise the attempt fails with `ERR_COMMERCIAL_NOT_APPROVED`."

    Design: Corner/validations/begin_sourcing_requires_approved_quote_rejected
    """
    ctx = fx.setup_project_decided()
    project_id = ctx.project["id"]
    fx.compute_quote(project_id)
    fx.send_quote(project_id)
    assert fx.get_project(project_id)["commercial_status"] == "QUOTE_SENT"

    res = api.begin_sourcing(project_id, PM)
    validate_error(res, ApiErrorId.ERR_COMMERCIAL_NOT_APPROVED.value)

    after = fx.get_project(project_id)
    assert after["work_status"] == "DECIDED"
