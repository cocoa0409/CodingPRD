"""Contract lifecycle: renewal-window boundary, referential-over-temporal priority,
term-overlap (closed) vs billing-overlap (half-open), review gating, and termination."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_active_contract, setup_service,
    new_vendor, new_contract, new_invoice, new_line_item, set_clock,
    TEST_USERS,
)

_SOURCING = TEST_USERS["sourcing_headers"]
_ANALYST = TEST_USERS["analyst_headers"]


# ---------------------------------------------------------------------------
# boundary_precision_check / renewal_window_open_inclusive_boundary
# ---------------------------------------------------------------------------

def test_renew_succeeds_at_window_open_boundary(api):
    """PRD §3.1: "the server's current instant must fall within the renewal window, meaning at or
    after the point renewal_notice_days before term_end and at or before term_end itself."
    PRD §3.1: "it pushes term_end forward by renewal_term_months months, increments renewal_count
    by one, and increments the contract's version."

    term_end 2026-12-31, notice 60 -> window opens 2026-11-01; renew at exactly that instant
    succeeds, renewal_count 1, term_end -> 2027-12-31.

    Design: Difficulty/boundary_precision_check/renewal_window_open_inclusive_boundary
    """
    base = setup_active_contract(api, contract_overrides={
        "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
        "renewal_notice_days": 60, "renewal_term_months": 12})
    set_clock(api, "2026-11-01T00:00:00Z")
    contract = validate_success(api.renew_contract(base["contract"]["id"], _SOURCING))
    assert contract["status"] == "ACTIVE", f"status should be ACTIVE, got {contract['status']}"
    assert contract["renewal_count"] == 1, f"renewal_count should be 1, got {contract['renewal_count']}"
    assert contract["term_end"].startswith("2027-12-31"), f"term_end should advance to 2027-12-31, got {contract['term_end']}"


def test_renew_rejected_one_day_before_window_open(api):
    """PRD §3.1: "Outside that window the renewal is rejected with ERR_OUTSIDE_RENEWAL_WINDOW; the
    auto_renew flag does not waive this check."

    Window opens 2026-11-01; at 2026-10-31 the renewal is outside the window.

    Design: Difficulty/boundary_precision_check/renewal_window_open_inclusive_boundary
    """
    base = setup_active_contract(api, contract_overrides={
        "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
        "renewal_notice_days": 60, "renewal_term_months": 12})
    set_clock(api, "2026-10-31T00:00:00Z")
    resp = api.renew_contract(base["contract"]["id"], _SOURCING)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_RENEWAL_WINDOW.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / renew_referential_beats_temporal_vendor_suspended
# ---------------------------------------------------------------------------

def _suspended_vendor_outside_window(api):
    base = setup_active_contract(api, contract_overrides={
        "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
        "renewal_notice_days": 60})
    validate_success(api.suspend_vendor(base["vendor"]["id"], _SOURCING))
    set_clock(api, "2026-10-31T00:00:00Z")
    return base


def test_renew_reports_vendor_suspended_over_outside_window(api):
    """PRD §2.9: "Cross-entity referential state — related entities are in the required states
    (vendor active for activate/renew ...), else ERR_VENDOR_SUSPENDED, ERR_CONTRACT_NOT_ACTIVE, or
    ERR_COST_CENTER_FROZEN (409)."
    PRD §3.1: "Renewing requires the contract to be ACTIVE (otherwise ERR_INVALID_STATE) and its
    vendor to be ACTIVE (otherwise ERR_VENDOR_SUSPENDED)."

    Vendor SUSPENDED (priority 6) and clock 2026-10-31 outside the window (priority 7): the
    referential check outranks the temporal one, so ERR_VENDOR_SUSPENDED is returned.

    Design: Difficulty/priority_pair_validation_conflict/renew_referential_beats_temporal_vendor_suspended
    """
    base = _suspended_vendor_outside_window(api)
    resp = api.renew_contract(base["contract"]["id"], _SOURCING)
    validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED.value)


def test_renew_referential_failure_leaves_contract_unchanged(api):
    """PRD §3.1: "A successful renewal is a self-loop — the contract stays ACTIVE — but it pushes
    term_end forward by renewal_term_months months, increments renewal_count by one, and
    increments the contract's version."

    Because renewal is rejected (ERR_VENDOR_SUSPENDED), the contract keeps renewal_count 0 and
    stays ACTIVE (no side effects fired).

    Design: Difficulty/priority_pair_validation_conflict/renew_referential_beats_temporal_vendor_suspended
    """
    base = _suspended_vendor_outside_window(api)
    api.renew_contract(base["contract"]["id"], _SOURCING)
    contract = validate_success(api.get_contract(base["contract"]["id"], _SOURCING))
    assert contract["renewal_count"] == 0, f"renewal_count should stay 0, got {contract['renewal_count']}"
    assert contract["status"] == "ACTIVE", f"status should stay ACTIVE, got {contract['status']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / invoice_review_requires_contract_active
# ---------------------------------------------------------------------------

def test_review_rejected_while_contract_draft(api):
    """PRD §3.4: "attempting review on an invoice not in RECEIVED is rejected with
    ERR_INVOICE_NOT_REVIEWABLE, and the parent contract must be ACTIVE or the review fails with
    ERR_CONTRACT_NOT_ACTIVE."

    Contract left DRAFT while the invoice is validly RECEIVED -> ERR_CONTRACT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/invoice_review_requires_contract_active
    """
    vendor = new_vendor(api)
    contract = new_contract(api, vendor["id"])  # DRAFT, not activated
    invoice = new_invoice(api, contract["id"])
    resp = api.review_invoice(invoice["id"], _ANALYST)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    fetched = validate_success(api.get_invoice(invoice["id"], _ANALYST))
    assert fetched["status"] == "RECEIVED", f"invoice should remain RECEIVED, got {fetched['status']}"


def test_review_succeeds_once_contract_active(api):
    """PRD §3.4: "Reviewing an invoice moves it from RECEIVED to UNDER_REVIEW"

    The same invoice reviews successfully once its parent contract is ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/invoice_review_requires_contract_active
    """
    base = setup_active_contract(api)
    invoice = new_invoice(api, base["contract"]["id"])
    reviewed = validate_success(api.review_invoice(invoice["id"], _ANALYST))
    assert reviewed["status"] == "UNDER_REVIEW", f"invoice should be UNDER_REVIEW, got {reviewed['status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / contract_term_overlap_closed_same_vendor
# ---------------------------------------------------------------------------

def test_activate_rejected_on_intersecting_term_same_vendor(api):
    """PRD §3.1: "if any other ACTIVE contract of the same vendor has a term whose closed interval
    intersects this contract's [term_start, term_end], activation is rejected with
    ERR_CONTRACT_TERM_OVERLAP."

    Active [2026-01-01, 2026-12-31]; second contract [2026-06-01, 2027-05-31] intersects.

    Design: Difficulty/resource_temporal_overlap/contract_term_overlap_closed_same_vendor
    """
    vendor = new_vendor(api)
    c1 = new_contract(api, vendor["id"], term_start="2026-01-01T00:00:00Z", term_end="2026-12-31T00:00:00Z",
                      renewal_notice_days=60)
    validate_success(api.activate_contract(c1["id"], _SOURCING))
    c2 = new_contract(api, vendor["id"], term_start="2026-06-01T00:00:00Z", term_end="2027-05-31T00:00:00Z",
                      renewal_notice_days=60)
    resp = api.activate_contract(c2["id"], _SOURCING)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_TERM_OVERLAP.value)
    fetched = validate_success(api.get_contract(c2["id"], _SOURCING))
    assert fetched["status"] == "DRAFT", f"second contract should remain DRAFT, got {fetched['status']}"


def test_activate_rejected_on_touching_endpoint_closed_interval(api):
    """PRD §3.1: "Because the intervals are closed, two terms that merely touch at an endpoint (one
    ending exactly when another begins) count as overlapping."

    Active [2026-01-01, 2026-12-31]; second contract begins exactly at 2026-12-31 -> overlap.

    Design: Difficulty/resource_temporal_overlap/contract_term_overlap_closed_same_vendor
    """
    vendor = new_vendor(api)
    c1 = new_contract(api, vendor["id"], term_start="2026-01-01T00:00:00Z", term_end="2026-12-31T00:00:00Z",
                      renewal_notice_days=60)
    validate_success(api.activate_contract(c1["id"], _SOURCING))
    c2 = new_contract(api, vendor["id"], term_start="2026-12-31T00:00:00Z", term_end="2027-12-31T00:00:00Z",
                      renewal_notice_days=60)
    resp = api.activate_contract(c2["id"], _SOURCING)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_TERM_OVERLAP.value)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / billing_period_overlap_half_open
# ---------------------------------------------------------------------------

def test_line_item_rejected_on_overlapping_billing_period(api):
    """PRD §3.4: "Two line items for the same service may not cover overlapping half-open periods;
    a new line whose period overlaps an existing line for that service is rejected with
    ERR_BILLING_PERIOD_OVERLAP."

    Existing [2026-06-01, 2026-07-01); a second [2026-06-15, 2026-07-15) overlaps.

    Design: Difficulty/resource_temporal_overlap/billing_period_overlap_half_open
    """
    base = setup_service(api)
    invoice = new_invoice(api, base["contract"]["id"], period_start="2026-06-01T00:00:00Z",
                          period_end="2026-07-31T00:00:00Z")
    new_line_item(api, invoice["id"], base["service"]["id"],
                  billing_period_start="2026-06-01T00:00:00Z", billing_period_end="2026-07-01T00:00:00Z",
                  billed_quantity=10, billed_amount_cents=10000)
    from test_helpers import create_line_item_payload
    resp = api.create_line_item(invoice["id"], create_line_item_payload(
        base["service"]["id"], billing_period_start="2026-06-15T00:00:00Z",
        billing_period_end="2026-07-15T00:00:00Z", billed_quantity=10, billed_amount_cents=10000), _ANALYST)
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value)


def test_line_item_allowed_on_abutting_billing_period(api):
    """PRD §3.4: "Because the interval is half-open, two lines that abut exactly (one ending where
    the next begins) do not overlap and are both allowed."

    Existing [2026-06-01, 2026-07-01); an adjacent [2026-07-01, 2026-08-01) is accepted.

    Design: Difficulty/resource_temporal_overlap/billing_period_overlap_half_open
    """
    base = setup_service(api)
    invoice = new_invoice(api, base["contract"]["id"], period_start="2026-06-01T00:00:00Z",
                          period_end="2026-08-31T00:00:00Z")
    new_line_item(api, invoice["id"], base["service"]["id"],
                  billing_period_start="2026-06-01T00:00:00Z", billing_period_end="2026-07-01T00:00:00Z",
                  billed_quantity=10, billed_amount_cents=10000)
    line2 = new_line_item(api, invoice["id"], base["service"]["id"],
                          billing_period_start="2026-07-01T00:00:00Z", billing_period_end="2026-08-01T00:00:00Z",
                          billed_quantity=10, billed_amount_cents=10000)
    assert line2["status"] == "BILLED", f"abutting line should be created BILLED, got {line2['status']}"


# ---------------------------------------------------------------------------
# Corner: state_machines / terminate_contract_retires_services
# ---------------------------------------------------------------------------

def test_terminate_contract_retires_services(api):
    """PRD §3.1: "Termination sets status to TERMINATED, and it cascades: every Service governed by
    the contract that is not already RETIRED is moved to RETIRED. The contract's
    monthly_committed_cost_cents is then recomputed (retired services no longer count)"

    One 2000x60 service (committed 120000) -> after terminate, committed 0 and service RETIRED.

    Design: Corner/state_machines/terminate_contract_retires_services
    """
    base = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 42})
    contract = validate_success(api.terminate_contract(base["contract"]["id"], _SOURCING))
    assert contract["status"] == "TERMINATED", f"contract should be TERMINATED, got {contract['status']}"
    assert contract["monthly_committed_cost_cents"] == 0, \
        f"committed should be 0, got {contract['monthly_committed_cost_cents']}"
    service = validate_success(api.get_service(base["service"]["id"], _ANALYST))
    assert service["status"] == "RETIRED", f"service should be RETIRED, got {service['status']}"
