"""Composite setup helpers for the HELOC platform.

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_loan_officer_headers,
    make_loan_servicer_headers,
)
from .factories import (
    create_borrower_payload,
    create_property_payload,
    create_index_rate_payload,
    create_heloc_payload,
    create_covenant_payload,
    create_draw_payload,
    create_payment_payload,
    clock_payload,
)

OFFICER = TEST_USERS["loan_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


# --- Low-level building blocks ---------------------------------------------

def set_clock(to_iso8601):
    """Set the system logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), SERVICER))


def publish_index(rate_bps=850, effective_date="2026-01-01T00:00:00Z"):
    """Publish a PRIME index rate. Returns the IndexRate dict."""
    return get_success_data(
        api_client.create_index_rate(
            create_index_rate_payload(rate_bps=rate_bps, effective_date=effective_date),
            SERVICER,
        )
    )


def create_borrower(**overrides):
    return get_success_data(
        api_client.create_borrower(create_borrower_payload(**overrides), OFFICER)
    )


def create_property(**overrides):
    return get_success_data(
        api_client.create_property(create_property_payload(**overrides), OFFICER)
    )


def create_heloc(borrower_id, property_id, **overrides):
    return get_success_data(
        api_client.create_heloc(
            create_heloc_payload(borrower_id, property_id, **overrides), OFFICER
        )
    )


def attach_covenant(heloc_id, covenant_type, threshold_value):
    return get_success_data(
        api_client.create_covenant(
            heloc_id, create_covenant_payload(covenant_type, threshold_value), OFFICER
        )
    )


def attach_full_covenant_set(
    heloc_id,
    cltv_threshold=9900,
    dscr_threshold=100,
    delinquency_threshold=60,
):
    """Attach one covenant of each required type (PRD §3.3 activation precondition).
    Default thresholds are deliberately non-breaching so activation succeeds.
    Returns dict of {covenant_type: covenant_dict}."""
    return {
        "MAX_CLTV": attach_covenant(heloc_id, "MAX_CLTV", cltv_threshold),
        "MIN_DSCR": attach_covenant(heloc_id, "MIN_DSCR", dscr_threshold),
        "MAX_DELINQUENCY_DAYS": attach_covenant(
            heloc_id, "MAX_DELINQUENCY_DAYS", delinquency_threshold
        ),
    }


# --- Tier 1/2: build an APPLICATION-stage line (covenants attached) ---------

def setup_application_line(
    *,
    clock="2026-01-01T00:00:00Z",
    index_rate_bps=850,
    index_effective="2026-01-01T00:00:00Z",
    publish_index_rate=True,
    borrower_overrides=None,
    property_overrides=None,
    heloc_overrides=None,
    cltv_threshold=9900,
    dscr_threshold=100,
    delinquency_threshold=60,
    attach_covenants=True,
):
    """Create borrower + property + heloc (APPLICATION) and (optionally) attach the
    full covenant set. Does NOT activate. Returns a context dict with all entities."""
    set_clock(clock)
    index = publish_index(index_rate_bps, index_effective) if publish_index_rate else None
    borrower = create_borrower(**(borrower_overrides or {}))
    prop = create_property(**(property_overrides or {}))
    heloc = create_heloc(borrower["id"], prop["id"], **(heloc_overrides or {}))
    covenants = {}
    if attach_covenants:
        covenants = attach_full_covenant_set(
            heloc["id"], cltv_threshold, dscr_threshold, delinquency_threshold
        )
    return {
        "index": index,
        "borrower": borrower,
        "property": prop,
        "heloc": heloc,
        "covenants": covenants,
    }


# --- Tier 1/3: build an activated DRAW-stage line --------------------------

def setup_active_line(
    *,
    activate_user_id=None,
    **kwargs,
):
    """Build an APPLICATION line then activate it to DRAW (PRD §3.3).

    activate_user_id, when supplied, controls the activating officer's opaque
    X-User-ID so segregation-of-duties tests can later compare against it.
    Returns the context dict from setup_application_line, with heloc refreshed
    to its activated state and an extra 'officer_user_id' key.
    """
    ctx = setup_application_line(**kwargs)
    if activate_user_id is not None:
        officer_headers = make_loan_officer_headers(activate_user_id)
    else:
        officer_headers = OFFICER
    activated = get_success_data(
        api_client.activate_heloc(ctx["heloc"]["id"], officer_headers)
    )
    ctx["heloc"] = activated
    ctx["officer_user_id"] = activate_user_id
    return ctx


def book_draw(heloc_id, amount_cents):
    """Book a draw against a DRAW-stage line. Returns the Draw dict."""
    return get_success_data(
        api_client.create_draw(heloc_id, create_draw_payload(amount_cents), SERVICER)
    )


def post_payment(heloc_id, amount_cents):
    """Post a payment (waterfall). Returns the Payment dict."""
    return get_success_data(
        api_client.create_payment(heloc_id, create_payment_payload(amount_cents), SERVICER)
    )


def advance_clock(heloc_id, to_iso8601):
    """Advance a line's billing clock; returns the updated heloc dict."""
    return get_success_data(
        api_client.advance_clock(heloc_id, clock_payload(to_iso8601), SERVICER)
    )


def evaluate_covenant(heloc_id, covenant_id):
    return get_success_data(api_client.evaluate_covenant(heloc_id, covenant_id, SERVICER))


def revalue_property(property_id, **overrides):
    return get_success_data(api_client.update_property(property_id, overrides, SERVICER))


# --- Tier 4: targeted scenarios used by multiple instances ------------------

def setup_drawn_line_with_accrual(
    *,
    draw_amount=200000,
    accrual_clock="2026-01-31T00:00:00Z",
    credit_limit_cents=50000000,
    margin_bps=150,
    rate_ceiling_bps=1800,
    index_rate_bps=850,
):
    """Active DRAW line; one draw at 2026-01-01; clock advanced (no payment yet) so
    chronological interest has accrued. Returns the context dict plus the draw under
    'draw'. APR 1000bps over 30 days on 200000 -> 1644 accrued (PRD §3.5)."""
    ctx = setup_active_line(
        index_rate_bps=index_rate_bps,
        heloc_overrides={
            "credit_limit_cents": credit_limit_cents,
            "margin_bps": margin_bps,
            "rate_ceiling_bps": rate_ceiling_bps,
        },
    )
    ctx["draw"] = book_draw(ctx["heloc"]["id"], draw_amount)
    set_clock(accrual_clock)
    return ctx


def setup_frozen_line_via_cltv_breach(
    *,
    cltv_threshold=8500,
    draw_amount=90000000,
    credit_limit_cents=95000000,
    activate_user_id=None,
):
    """Active DRAW line breached on MAX_CLTV (cltv 9000 > 8500) so the line is FROZEN
    and the covenant BREACHED (PRD §3.8). Returns context with 'cltv_covenant' and
    refreshed 'heloc'."""
    ctx = setup_active_line(
        cltv_threshold=cltv_threshold,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": credit_limit_cents},
        activate_user_id=activate_user_id,
    )
    book_draw(ctx["heloc"]["id"], draw_amount)
    cov = ctx["covenants"]["MAX_CLTV"]
    ctx["cltv_covenant"] = evaluate_covenant(ctx["heloc"]["id"], cov["id"])
    ctx["heloc"] = get_success_data(
        api_client.get_heloc(ctx["heloc"]["id"], SERVICER)
    )
    return ctx
