"""Quote conversation: send, revision loop, approval, rejection, cancellation.

Translates the difficulty `non_linear_state_machine` quote-revision instance plus
corner `state_machines` quote-related instances.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_mechanic_headers,
    setup_quoted_request, send_quote, _sr_version,
    create_approve_quote_payload,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ── Difficulty: quote revision cycle SENT -> REVISION_REQUESTED -> SUPERSEDED ──

def test_quote_revision_replacement_supersedes_prior(api):
    """PRD §3.2: "sending a quote while the request is `QUOTED` and the prior quote sits
    in `REVISION_REQUESTED` supersedes that prior quote (moving it from
    `REVISION_REQUESTED` to `SUPERSEDED` and bumping its version), publishes the new
    quote in `SENT`, and increments the request's `version`."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revision_sent
    """
    ctx = setup_quoted_request(estimated_labor_hours=2.0, estimated_parts_cents=5000,
                               labor_rate_cents_per_hour=9000, email="m5@x.com")
    q5a, customer, mechanic, sr = (ctx["quote"], ctx["customer"], ctx["mechanic"],
                                   ctx["service_request"])
    get_success_data(api.request_revision(q5a["id"], make_customer_headers(customer["id"])))

    q5b = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=1.5,
                     estimated_parts_cents=3000, labor_rate_cents_per_hour=9000,
                     diagnosis_text="v2 cheaper")

    prior = validate_success(api.get_quote(q5a["id"], DISPATCHER), 200)
    replacement = validate_success(api.get_quote(q5b["id"], DISPATCHER), 200)
    assert prior["status"] == "SUPERSEDED"
    assert replacement["status"] == "SENT"


def test_quote_revision_keeps_request_quoted_and_prices_replacement(api):
    """PRD §3.2: "This revision loop may cycle `SENT → REVISION_REQUESTED → SENT` any
    number of rounds while the request remains in `QUOTED`."
    PRD §3.3: "The grand total is then the discounted (or undiscounted) labour figure
    plus the estimated parts cents plus the tow fee cents, each of the latter two added
    as-is without further rounding."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revision_sent
    """
    ctx = setup_quoted_request(estimated_labor_hours=2.0, estimated_parts_cents=5000,
                               labor_rate_cents_per_hour=9000, email="m5b@x.com")
    q5a, customer, mechanic, sr = (ctx["quote"], ctx["customer"], ctx["mechanic"],
                                   ctx["service_request"])
    get_success_data(api.request_revision(q5a["id"], make_customer_headers(customer["id"])))
    q5b = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=1.5,
                     estimated_parts_cents=3000, labor_rate_cents_per_hour=9000,
                     diagnosis_text="v2 cheaper")

    replacement = validate_success(api.get_quote(q5b["id"], DISPATCHER), 200)
    assert replacement["quoted_total_cents"] == 16500
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "QUOTED"


# ── Corner: cancel from QUOTED supersedes the SENT quote ──

def test_cancel_quoted_request_supersedes_sent_quote(api):
    """PRD §3.2: "Cancelling moves any quote currently in `SENT` or `REVISION_REQUESTED`
    to `SUPERSEDED`, moves the request to `CANCELLED`, and increments the request's
    `version`."

    Design: Corner/state_machines/cancel_quoted_request_supersedes_sent_quote
    """
    ctx = setup_quoted_request(email="c11@x.com")
    customer, quote, sr = ctx["customer"], ctx["quote"], ctx["service_request"]
    res = api.cancel_service_request(sr["id"], make_customer_headers(customer["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "SUPERSEDED"


# ── Corner: approving a quote that is no longer SENT is an invalid state ──

def test_approve_rejected_quote_invalid_state(api):
    """PRD §3.2: "Approving a quote ... is permitted only when the request is in
    `QUOTED`, the target quote is in `SENT`".
    PRD §3.2: "Any attempt to drive a quote or request from a state where the move is
    undefined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_quote_from_intake_request_invalid_state
    """
    ctx = setup_quoted_request(email="c8@x.com")
    customer, quote, sr = ctx["customer"], ctx["quote"], ctx["service_request"]
    cust_headers = make_customer_headers(customer["id"])
    get_success_data(api.reject_quote(quote["id"], cust_headers))

    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version), cust_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "REJECTED"
