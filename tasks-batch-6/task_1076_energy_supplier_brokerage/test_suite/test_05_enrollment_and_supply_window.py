"""Enrollment overlap, the supply window, expiry, renewal, and rate alerts.

Queue A: the half-open supply-interval overlap and the exact-60-day renewal
boundary. Queue B: scheduled contract expiry, renewal successor creation, the
closed-window renewal rejection, and the market-drop rate alert.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


# ===========================================================================
# Difficulty: resource_temporal_overlap / contract_supply_interval_overlap_half_open
# ===========================================================================

def _verified_ctx(api, loa_expires="2028-06-01T00:00:00Z"):
    ctx = fx.setup_verified_account(api, with_manager=True, loa_expires=loa_expires)
    ctx["supplier"] = fx.new_supplier(api)
    ctx["supplier_headers"] = fx.make_supplier_headers(ctx["supplier"]["id"])
    return ctx


def _award_and_approve(api, ctx, start_date, term_months=12):
    hdr = ctx["agent_headers"]
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"], term_months_requested=term_months), hdr))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, hdr))
    v = fx.rfp_version(api, rfp["id"], hdr)
    quote = get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], ctx["supplier"]["id"], v, term_months=term_months),
        ctx["supplier_headers"]))
    get_success_data(api.shortlist_quote(quote["id"], hdr))
    contract = get_success_data(api.award_contract(
        fac.award_contract_payload(rfp["id"], ctx["account"]["id"], start_date=start_date,
                                   requested_switch_date=start_date), hdr))
    get_success_data(api.customer_decision(contract["id"], {"decision": "ACCEPT"}, ctx["customer_headers"]))
    return get_success_data(api.approve_contract(contract["id"], ctx["mgr1_headers"]))


def test_overlapping_supply_interval_rejected_at_submit_enrollment(api):
    """PRD §3.4: "the new contract's supply interval, running from its start_date
    inclusive to its end_date exclusive, may not overlap the interval of any other
    contract on the same account that is currently APPROVED, ENROLLMENT_SUBMITTED,
    or ACTIVE. ... any true overlap is rejected with ERR_CONTRACT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/contract_supply_interval_overlap_half_open
    """
    ctx = _verified_ctx(api)
    _award_and_approve(api, ctx, "2026-07-01T00:00:00Z")            # c1 [2026-07-01, 2027-07-01)
    c2 = _award_and_approve(api, ctx, "2027-01-01T00:00:00Z")       # c2 [2027-01-01, 2028-01-01) overlaps

    resp = api.submit_enrollment(c2["id"], ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_OVERLAP.value)
    after = get_success_data(api.get_contract(c2["id"], ctx["agent_headers"]))
    assert after["status"] == "APPROVED"


def test_adjacent_supply_interval_allowed_at_submit_enrollment(api):
    """PRD §3.4: "Because the interval is half-open, exact adjacency — where one
    contract's start_date equals another's end_date — is permitted".

    Design: Difficulty/resource_temporal_overlap/contract_supply_interval_overlap_half_open
    """
    ctx = _verified_ctx(api, loa_expires="2029-01-01T00:00:00Z")
    _award_and_approve(api, ctx, "2026-07-01T00:00:00Z")            # c1 [2026-07-01, 2027-07-01)
    c2 = _award_and_approve(api, ctx, "2027-07-01T00:00:00Z")       # c2 [2027-07-01, 2028-07-01) adjacent

    contract = get_success_data(api.submit_enrollment(c2["id"], ctx["agent_headers"]))
    assert contract["status"] == "ENROLLMENT_SUBMITTED"


# ===========================================================================
# Difficulty: boundary_precision_check / renewal_window_opens_at_exactly_60_days
# ===========================================================================

def test_renewal_window_opens_at_exactly_60_days(api):
    """PRD §3.4: "The renewal_window_open flag is true exactly when the gap from
    the current logical clock to end_date is 60 days or fewer, with the boundary
    inclusive (at exactly 60 days out, the window is open)."

    Design: Difficulty/boundary_precision_check/renewal_window_opens_at_exactly_60_days
    """
    ctx = fx.setup_active_contract(api)  # start 2026-07-01, term 12 -> end 2027-07-01
    fx.set_clock(api, "2027-05-02T00:00:00Z")  # exactly 60 days before end_date
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert contract["renewal_window_open"] is True
    assert contract["status"] == "ACTIVE"


def test_renewal_window_closed_at_61_days(api):
    """PRD §3.4: "The renewal_window_open flag is true exactly when the gap from
    the current logical clock to end_date is 60 days or fewer, with the boundary
    inclusive (at exactly 60 days out, the window is open)."

    Design: Difficulty/boundary_precision_check/renewal_window_opens_at_exactly_60_days
    """
    ctx = fx.setup_active_contract(api)  # end 2027-07-01
    fx.set_clock(api, "2027-05-01T00:00:00Z")  # 61 days before end_date -> still closed
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert contract["renewal_window_open"] is False


# ===========================================================================
# Corner: expiry, renewal, rate alert
# ===========================================================================

def test_active_contract_expires_via_run_scheduled(api):
    """PRD §3.7: "It expires every ACTIVE contract whose end_date the clock has
    reached or passed, moving each ACTIVE → EXPIRED."

    Design: Corner/state_machines/contract_expiry_via_run_scheduled
    """
    ctx = fx.setup_active_contract(api)  # end 2027-07-01
    fx.set_clock(api, "2027-07-02T00:00:00Z")
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert contract["status"] == "EXPIRED"


def test_renew_active_contract_creates_successor(api):
    """PRD §3.7: "it moves the original ACTIVE → RENEWED and creates a successor
    contract in PENDING_CUSTOMER whose renewed_from_contract_id points back to the
    original."

    Design: Corner/state_machines/renew_active_contract_creates_successor
    """
    ctx = fx.setup_active_contract(api, loa_expires="2028-06-01T00:00:00Z")
    fx.set_clock(api, "2027-05-02T00:00:00Z")
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    successor = get_success_data(api.renew_contract(
        ctx["contract"]["id"],
        {"start_date": "2027-07-01T00:00:00Z", "requested_switch_date": "2027-07-01T00:00:00Z",
         "estimated_annual_usage_kwh": 60000},
        ctx["agent_headers"]))
    assert successor["renewed_from_contract_id"] == ctx["contract"]["id"]
    assert successor["status"] == "PENDING_CUSTOMER"
    original = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert original["status"] == "RENEWED"


def test_renew_without_open_window_rejected(api):
    """PRD §3.7: "Renewing an ACTIVE contract is permitted only while its
    renewal_window_open is true (else ERR_RENEWAL_WINDOW_CLOSED)".

    Design: Corner/state_machines/renew_without_open_window_rejected
    """
    ctx = fx.setup_active_contract(api)  # clock at default 2026-05-01, window not open
    resp = api.renew_contract(
        ctx["contract"]["id"],
        {"start_date": "2027-07-01T00:00:00Z", "requested_switch_date": "2027-07-01T00:00:00Z",
         "estimated_annual_usage_kwh": 60000},
        ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)
    after = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert after["status"] == "ACTIVE"


def test_rate_alert_raised_on_market_drop(api):
    """PRD §3.4: "The rate_alert is set to RATE_DROP when a market rate has been
    observed for the contract's commodity and state ... and that observed rate is
    strictly below the contract's rate_mills_per_kwh reduced by 10 percent — that
    is, below the contract rate multiplied by nine-tenths and rounded half-up to a
    whole mill".

    Design: Corner/calculations/rate_alert_raised_on_market_drop
    """
    ctx = fx.setup_active_contract(api)  # contract rate 60 mills; threshold round(60*0.9)=54
    get_success_data(api.record_market_rate(
        {"commodity": "ELECTRICITY", "state_code": "TX", "rate_mills": 50}, ctx["ops_headers"]))
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ctx["agent_headers"]))
    assert contract["rate_alert"] == "RATE_DROP"
