"""Invoices, payments, and the fiscal ledger: gates, boundaries, compensation."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    create_event_invoice_payload, create_period_invoice_payload,
    create_true_up_payload,
    setup_client, setup_site, setup_contract, link_site, activate_contract,
    setup_active_per_push, setup_active_hourly, setup_storm_event, set_clock,
    post_observation, verify_event, setup_completed_visit, setup_billable_visit,
    setup_event_invoice, setup_issued_event_invoice, schedule_visit,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CREW = TEST_USERS["crew_lead_headers"]

_OBS = [("NOAA", "2026-12-10T07:30:00Z", 2.0), ("DTN", "2026-12-10T08:00:00Z", 2.1)]


def _billable_ctx(api, client_name="Invoice Co", credit_limit_cents=10_000_000,
                  per_push_rate_cents=45_000):
    """Active PER_PUSH contract; one verified billable visit. Returns (ctx, event, visit)."""
    ctx = setup_active_per_push(client_name=client_name, trigger_depth_inches=1.0,
                                per_push_rate_cents=per_push_rate_cents,
                                credit_limit_cents=credit_limit_cents)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, _OBS)
    return ctx, event, visit


def test_event_invoice_generation_gated_on_storm_event_verified(api):
    """PRD §3.7: "An `EVENT` invoice requires `storm_event_id` and requires that event to be `VERIFIED` or `CLOSED`, failing as `ERR_EVENT_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/invoice_generation_gated_on_storm_event_verified
    """
    ctx = setup_active_per_push(client_name="Gatekeeper Props",
                                trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    setup_completed_visit(ctx, event)  # COMPLETED but event still REPORTED

    validate_error(
        api.create_invoice(
            create_event_invoice_payload(ctx["contract"]["id"], event["id"]),
            DISPATCH),
        ApiErrorId.ERR_EVENT_NOT_VERIFIED)


def test_event_invoice_generation_succeeds_after_verification(api):
    """PRD §3.7: "An `EVENT` invoice requires `storm_event_id` and requires that event to be `VERIFIED` or `CLOSED`, failing as `ERR_EVENT_NOT_VERIFIED`."
    PRD §3.7: "An invoice is born `DRAFT`; its `lines` contain, for each eligible visit in `BILLABLE_CONFIRMED` belonging to the contract, one `SERVICE` line carrying the visit's `billable_amount_cents` plus one `MATERIAL` line when the visit's `material_cost_cents` is greater than zero."

    Design: Difficulty/cross_entity_state_dependency/invoice_generation_gated_on_storm_event_verified
    """
    ctx, event, visit = _billable_ctx(api, client_name="Gatekeeper Props")
    invoice = validate_success(
        api.create_invoice(
            create_event_invoice_payload(ctx["contract"]["id"], event["id"]),
            DISPATCH), 201)
    assert invoice["status"] == "DRAFT"
    assert invoice["total_cents"] == 45_000, "one SERVICE line at the push rate"


def test_duplicate_event_invoice_rejected(api):
    """PRD §3.7: "Uniqueness is enforced per contract: one non-`VOIDED` `EVENT` invoice per storm event, and one non-`VOIDED` `PERIOD` invoice per `period_start`, failing as `ERR_DUPLICATE_INVOICE`."

    Design: Corner/validations/duplicate_event_invoice_rejected
    """
    ctx, event, _ = _billable_ctx(api, client_name="Dup Inv Co")
    first = setup_event_invoice(ctx, event)
    assert first["status"] == "DRAFT"
    validate_error(
        api.create_invoice(
            create_event_invoice_payload(ctx["contract"]["id"], event["id"]),
            DISPATCH),
        ApiErrorId.ERR_DUPLICATE_INVOICE)


def test_issue_invoice_with_zero_lines_returns_invoice_empty(api):
    """PRD §3.7: "The invoice must contain at least one line, failing as `ERR_INVOICE_EMPTY`."
    PRD §3.7: "When the trigger is not met, or execution ends anywhere other than `COMPLETED`, the visit falls to `NON_BILLABLE`."

    Design: Corner/validations/issue_invoice_with_zero_lines_returns_invoice_empty
    """
    ctx = setup_active_per_push(client_name="Empty Co", trigger_depth_inches=2.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=0.5)
    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 0.5)
    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 0.5)
    verify_event(event["id"])  # verified 0.5 < trigger 2.0 -> nothing billable

    invoice = setup_event_invoice(ctx, event)
    assert invoice["subtotal_cents"] == 0
    validate_error(api.issue_invoice(invoice["id"], DISPATCH),
                   ApiErrorId.ERR_INVOICE_EMPTY)


def test_hourly_period_invoice_half_open_boundary(api):
    """PRD §3.7: "A `PERIOD` invoice requires `period_start` and `period_end`, and covers visits whose `completed_at` falls at or after `period_start` and strictly before `period_end` — a half-open window."
    PRD §3.7: "When the visit's `actual_start_at` hour in UTC is 22, 23, or 0 through 5, `night_premium_applied` is true and the summed base is multiplied by one plus `night_premium_pct`, with the final amount rounded half-up — the premium rounds last."

    Design: Corner/calculations/hourly_period_invoice_half_open_boundary
    """
    ctx = setup_active_hourly(client_name="Period Co", trigger_depth_inches=1.0)
    # vIn: completes exactly at the period start 2026-12-01T00:00:00Z (included).
    set_clock("2026-11-30T23:00:00Z")
    e_in = setup_storm_event(window_start="2026-11-30T12:00:00Z",
                             window_end="2026-11-30T18:00:00Z")
    v_in = schedule_visit(e_in["id"], ctx["contract_site"]["id"],
                          scheduled_start="2026-11-30T23:00:00Z",
                          scheduled_end="2026-12-01T00:00:00Z")
    get_success_data(api.start_visit(v_in["id"], CREW))
    set_clock("2026-12-01T00:00:00Z")
    get_success_data(api.complete_visit(v_in["id"], CREW))
    post_observation(e_in["id"], "NOAA", "2026-11-30T17:00:00Z", 2.0)
    post_observation(e_in["id"], "DTN", "2026-11-30T17:30:00Z", 2.1)
    verify_event(e_in["id"])

    # vOut: completes exactly at the period end 2027-01-01T00:00:00Z (excluded).
    set_clock("2026-12-31T23:00:00Z")
    e_out = setup_storm_event(window_start="2026-12-31T12:00:00Z",
                              window_end="2026-12-31T18:00:00Z")
    v_out = schedule_visit(e_out["id"], ctx["contract_site"]["id"],
                           scheduled_start="2026-12-31T23:00:00Z",
                           scheduled_end="2027-01-01T00:00:00Z")
    get_success_data(api.start_visit(v_out["id"], CREW))
    set_clock("2027-01-01T00:00:00Z")
    get_success_data(api.complete_visit(v_out["id"], CREW))
    post_observation(e_out["id"], "NOAA", "2026-12-31T17:00:00Z", 2.0)
    post_observation(e_out["id"], "DTN", "2026-12-31T17:30:00Z", 2.1)
    verify_event(e_out["id"])

    invoice = validate_success(api.create_invoice(
        create_period_invoice_payload(ctx["contract"]["id"],
                                      "2026-12-01T00:00:00Z",
                                      "2027-01-01T00:00:00Z"),
        DISPATCH), 201)
    service_visits = [l for l in invoice["lines"] if l.get("kind") == "SERVICE"
                      or l.get("type") == "SERVICE"]
    assert invoice["subtotal_cents"] == 15_000, (
        "only vIn (completed exactly at period_start, night-started 23:00) is in "
        "the half-open window: 60 tier-1 min = 12000c, premium last -> 15000")
    assert len(invoice["lines"]) == 1, "vOut completed exactly at period_end is excluded"


def test_draft_invoice_reconciles_when_second_visit_confirms(api):
    """PRD §3.7: "While `DRAFT`, the lines recompute live on every underlying visit billing change."
    PRD §3.5: "When the storm event is already `VERIFIED` or `CLOSED`, billing evaluates immediately at completion — the visit moves from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE` with the second- and third-level cascades of §3.3."

    Design: Corner/calculations/draft_invoice_reconciles_when_second_visit_confirms
    """
    ctx, event, _ = _billable_ctx(api, client_name="Reconcile Co")
    invoice = setup_event_invoice(ctx, event)
    assert invoice["subtotal_cents"] == 45_000

    # PRD §3.5 buffer: the first visit occupies 09:00-10:00 at this site, so the
    # second must start at least ninety minutes after 10:00 — exactly 90 is legal.
    v2 = schedule_visit(event["id"], ctx["contract_site"]["id"],
                        scheduled_start="2026-12-10T11:30:00Z",
                        scheduled_end="2026-12-10T12:00:00Z")
    set_clock("2026-12-10T11:30:00Z")
    get_success_data(api.start_visit(v2["id"], CREW))
    set_clock("2026-12-10T12:00:00Z")
    completed = get_success_data(api.complete_visit(v2["id"], CREW))
    assert completed["billing_status"] == "BILLABLE_CONFIRMED", (
        "event already VERIFIED -> billing evaluates immediately at completion")

    invoice_after = validate_success(api.get_invoice(invoice["id"], DISPATCH), 200)
    assert invoice_after["subtotal_cents"] == 90_000, (
        "the DRAFT invoice recomputed live without any regeneration call")


def test_credit_limit_equality_boundary(api):
    """PRD §3.7: "the client's `credit_exposure_cents` plus the invoice's `total_cents` must be less than or equal to the client's `credit_limit_cents`, failing as `ERR_CLIENT_CREDIT_EXCEEDED`"
    PRD §3.1: "the issue-time fiscal gate in §3.7 compares against this figure with a less-than-or-equal test, so exposure may equal the limit but never exceed it."

    Design: Corner/validations/credit_limit_equality_boundary
    """
    ctx, event1, _ = _billable_ctx(api, client_name="Credit Edge Co",
                                   credit_limit_cents=45_000)
    invoice1 = setup_issued_event_invoice(ctx, event1)
    assert invoice1["status"] == "ISSUED", (
        "exposure_after 45000 == credit_limit 45000 is allowed (inclusive <=)")

    # Second event with its own billable visit would push exposure to 90000.
    event2 = setup_storm_event(window_start="2026-12-12T00:00:00Z",
                               window_end="2026-12-12T06:00:00Z")
    setup_billable_visit(
        ctx, event2,
        [("NOAA", "2026-12-12T05:00:00Z", 2.0), ("DTN", "2026-12-12T05:30:00Z", 2.1)],
        scheduled_start="2026-12-12T09:00:00Z",
        scheduled_end="2026-12-12T10:00:00Z",
        start_at="2026-12-12T09:05:00Z", complete_at="2026-12-12T10:00:00Z")
    invoice2 = setup_event_invoice(ctx, event2)

    validate_error(api.issue_invoice(invoice2["id"], DISPATCH),
                   ApiErrorId.ERR_CLIENT_CREDIT_EXCEEDED)

    client = validate_success(api.get_client(ctx["client"]["id"], DISPATCH), 200)
    assert client["credit_exposure_cents"] == 45_000, (
        "no partial mutation on the rejected issue")


def test_pay_partial_then_exact_remaining_and_overpay_rejected(api):
    """PRD §3.7: "carrying `amount_cents`, which must be greater than zero and no more than the remaining balance — `total_cents` minus `paid_cents` — failing as `ERR_OVERPAYMENT`. A partial payment moves `ISSUED` to `PARTIALLY_PAID`, and further partial payments keep the invoice in `PARTIALLY_PAID` while reducing the remainder. A payment exactly equal to the remaining balance settles the invoice to `PAID`"

    Design: Corner/validations/pay_partial_then_exact_remaining_and_overpay_rejected
    """
    ctx, event, _ = _billable_ctx(api, client_name="Pay Co")
    invoice = setup_issued_event_invoice(ctx, event)

    partial = validate_success(
        api.pay_invoice(invoice["id"], {"amount_cents": 20_000}, DISPATCH), 200)
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["paid_cents"] == 20_000

    validate_error(api.pay_invoice(invoice["id"], {"amount_cents": 25_001}, DISPATCH),
                   ApiErrorId.ERR_OVERPAYMENT)

    paid = validate_success(
        api.pay_invoice(invoice["id"], {"amount_cents": 25_000}, DISPATCH), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 45_000, "equality completes the invoice"


def test_void_invoice_with_payments_rejected(api):
    """PRD §3.7: "Voiding an `ISSUED`, `PARTIALLY_PAID`, or `PARTIALLY_CREDITED` invoice — three sibling branches with identical guards — requires `paid_cents` to be exactly zero, failing as `ERR_INVOICE_HAS_PAYMENTS`"

    Design: Corner/validations/void_invoice_with_payments_rejected
    """
    ctx, event, _ = _billable_ctx(api, client_name="HasPays Co")
    invoice = setup_issued_event_invoice(ctx, event)
    get_success_data(api.pay_invoice(invoice["id"], {"amount_cents": 10_000}, DISPATCH))

    validate_error(api.void_invoice(invoice["id"], DISPATCH),
                   ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)

    after = validate_success(api.get_invoice(invoice["id"], DISPATCH), 200)
    assert after["status"] == "PARTIALLY_PAID"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / invoice_issue_state_vs_fiscal_priority
# ---------------------------------------------------------------------------

def _setup_fiscally_blocked_invoice(api):
    """Client credit_limit 40000 (below the 45000 invoice total); DRAFT invoice."""
    ctx, event, _ = _billable_ctx(api, client_name="Tight Budget LLC",
                                  credit_limit_cents=40_000)
    return ctx, setup_event_invoice(ctx, event)


def test_issue_single_fiscal_failure_returns_credit_exceeded(api):
    """PRD §3.7: "And the client's `credit_exposure_cents` plus the invoice's `total_cents` must be less than or equal to the client's `credit_limit_cents`, failing as `ERR_CLIENT_CREDIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/invoice_issue_state_vs_fiscal_priority
    """
    _, invoice = _setup_fiscally_blocked_invoice(api)
    validate_error(api.issue_invoice(invoice["id"], DISPATCH),
                   ApiErrorId.ERR_CLIENT_CREDIT_EXCEEDED)


def test_issue_voided_invoice_state_tier_beats_fiscal_tier(api):
    """PRD §2.8: "Every request is checked against the following tiers in the order listed, and when several checks would fail at once, the earliest tier in this order produces the returned error."
    PRD §2.8: "Fifth, state legality: the target resource's state machine must allow the requested transition, failing as `ERR_INVALID_STATE`, and a resource already in a terminal state rejects every transition with `ERR_ALREADY_TERMINAL`."
    PRD §2.8: "Twenty-first and last, the fiscal gates, failing as `ERR_CLIENT_CREDIT_EXCEEDED`, `ERR_OVERPAYMENT`, `ERR_INVOICE_HAS_PAYMENTS`, or `ERR_SETTLEMENT_MISMATCH`."
    PRD §3.7: "Issuing moves `DRAFT` to `ISSUED`" — a VOIDED invoice has no issue transition, so the tier-5 state error pre-empts the tier-21 fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/invoice_issue_state_vs_fiscal_priority
    """
    _, invoice = _setup_fiscally_blocked_invoice(api)
    # Void the DRAFT invoice ("A DRAFT invoice may be voided freely" — PRD §3.7).
    get_success_data(api.void_invoice(invoice["id"], DISPATCH))

    resp = api.issue_invoice(invoice["id"], DISPATCH)
    error_id = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])
    assert error_id != ApiErrorId.ERR_CLIENT_CREDIT_EXCEEDED, (
        "the tier-5 state check must pre-empt the tier-21 fiscal gate")


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / billed_cents_conserved_by_issue_then_void
# ---------------------------------------------------------------------------

def test_issue_accumulates_billed_cents_and_exposure(api):
    """PRD §3.7: "the contract's `season_billed_cents` grows by `total_cents` and the client's `credit_exposure_cents` grows by the same amount"
    PRD §3.7: "every line visit moves from `BILLABLE_CONFIRMED` to `INVOICED`"
    PRD §3.7: "`season_billed_cents` sums `total_cents` over the contract's invoices in `ISSUED`, `PARTIALLY_CREDITED`, `PARTIALLY_PAID`, or `PAID`"

    Design: Difficulty/compensating_invariant/billed_cents_conserved_by_issue_then_void
    """
    ctx, event, visit = _billable_ctx(api, client_name="Balance Sheet Co")
    invoice = setup_issued_event_invoice(ctx, event)
    assert invoice["status"] == "ISSUED"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billed_cents"] == 45_000
    client = validate_success(api.get_client(ctx["client"]["id"], DISPATCH), 200)
    assert client["credit_exposure_cents"] == 45_000

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "INVOICED"


def test_issue_then_void_restores_billed_cents_and_exposure_to_zero(api):
    """PRD §3.7: "The compensation is symmetric: the contract's `season_billed_cents` and the client's `credit_exposure_cents` each drop by `total_cents`, every line visit returns from `INVOICED` to `BILLABLE_CONFIRMED`, and the contract's `version` increments by one."
    PRD §2.9: "recomputed immediately whenever an underlying fact changes; consistency is immediate, never deferred."

    Design: Difficulty/compensating_invariant/billed_cents_conserved_by_issue_then_void
    """
    ctx, event, visit = _billable_ctx(api, client_name="Balance Sheet Co")
    invoice = setup_issued_event_invoice(ctx, event)

    voided = validate_success(api.void_invoice(invoice["id"], DISPATCH), 200)
    assert voided["status"] == "VOIDED"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billed_cents"] == 0, (
        "sum over non-voided issued invoices is empty -> zero drift")
    client = validate_success(api.get_client(ctx["client"]["id"], DISPATCH), 200)
    assert client["credit_exposure_cents"] == 0

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "BILLABLE_CONFIRMED"


def test_immediate_visibility_of_ledger_sync_after_issue(api):
    """PRD §2.9: "The contract's derived accumulator fields — `season_billable_push_count`, `season_billable_minutes`, `season_billed_cents`, `unbilled_billable_cents`, `season_sla_miss_count`, and `overage_active` — together with the client's `credit_exposure_cents`, are recomputed immediately whenever an underlying fact changes; consistency is immediate, never deferred."
    PRD §3.7: "`unbilled_billable_cents` sums `billable_amount_cents` plus `material_cost_cents` over visits sitting in `BILLABLE_CONFIRMED`"

    Design: Corner/consistency_model/immediate_visibility_of_ledger_sync_after_issue
    """
    ctx, event, visit = _billable_ctx(api, client_name="Consistent Co")
    invoice = setup_event_invoice(ctx, event)
    get_success_data(api.issue_invoice(invoice["id"], DISPATCH))

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billed_cents"] == 45_000
    assert contract["unbilled_billable_cents"] == 0

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "INVOICED"


def test_contract_type_forbids_wrong_invoice_kind_and_trueup(api):
    """PRD §3.7: "an `EVENT` invoice bills a single storm and is for `PER_PUSH` contracts; a `PERIOD` invoice bills a time window and is for `HOURLY` contracts; any other pairing fails as `ERR_CONTRACT_TYPE_FORBIDS`."
    PRD §3.9: "A true-up against a non-`SEASONAL` contract fails as `ERR_CONTRACT_TYPE_FORBIDS`; against a contract not yet `EXPIRED` it fails as `ERR_INVALID_STATE`."
    PRD §2.8: "Thirteenth, contract-type conditional operations: event invoices, period invoices, and true-ups each belong to exactly one contract type, failing as `ERR_CONTRACT_TYPE_FORBIDS`."

    Design: Corner/validations/contract_type_forbids_wrong_invoice_kind_and_trueup
    """
    client = setup_client(name="Typed Co")
    site_h = setup_site(client["id"], name="Hourly Lot", address="1 Type St")
    site_p = setup_site(client["id"], name="Push Lot", address="2 Type St")
    k_hourly = setup_contract(client["id"], contract_type="HOURLY",
                              hourly_rate_cents=12_000, hourly_tier2_rate_cents=6_000,
                              require_photo_verification=False)
    link_site(k_hourly["id"], site_h["id"])
    activate_contract(k_hourly["id"])
    k_push = setup_contract(client["id"], contract_type="PER_PUSH",
                            per_push_rate_cents=45_000, require_photo_verification=False)
    link_site(k_push["id"], site_p["id"])
    k_push = activate_contract(k_push["id"])

    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()

    # EVENT invoice against a HOURLY contract.
    validate_error(api.create_invoice(
        create_event_invoice_payload(k_hourly["id"], event["id"]), DISPATCH),
        ApiErrorId.ERR_CONTRACT_TYPE_FORBIDS)

    # True-up against a PER_PUSH contract.
    validate_error(api.create_true_up(
        create_true_up_payload(k_push["id"], k_push["version"]), DISPATCH),
        ApiErrorId.ERR_CONTRACT_TYPE_FORBIDS)
