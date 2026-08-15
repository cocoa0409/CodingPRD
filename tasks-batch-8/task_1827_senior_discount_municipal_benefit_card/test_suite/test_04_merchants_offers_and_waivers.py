"""Merchant enrollment and termination cascades, offer window integrity
(half-open intervals), and fee waiver windows (closed intervals)
(PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_fee_waiver_grant,
    assert_merchant,
    create_fee_waiver_payload,
    create_merchant_payload,
    create_offer_payload,
    create_usage_transaction_payload,
    create_merchant,
    file_claim,
    list_claims,
    make_merchant_operator_headers,
    onboard_cardholder,
    post_transactions,
    set_clock,
    setup_merchant_with_offer,
    validate_error,
    validate_success,
)


def test_merchant_created_active_with_zero_reimbursed(api,
                                                      program_administrator_headers):
    """PRD §3.5: "A merchant is created `ACTIVE`."
    PRD §3.8: "On approval the claim stores `final_amount_cents` and binds
    `program_fund_id` to the resolved fund, the fund's `paid_cents` increases
    by the final amount — a fund mutation that increments the fund's `version`
    — and the merchant's `current_month_reimbursed_cents` is recomputed as the
    sum of `final_amount_cents` over the merchant's `APPROVED` claims whose
    approval timestamp falls inside the clock's current calendar month."
    A freshly enrolled merchant has no approved claims, so the sum is zero.

    Design: Corner/entities/merchant_created_active_with_zero_reimbursed
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_merchant(
        create_merchant_payload("Default Deli", 25, 50000),
        program_administrator_headers)
    merchant = validate_success(res, 201)
    assert_merchant(merchant)
    assert merchant["status"] == "ACTIVE"
    assert merchant["current_month_reimbursed_cents"] == 0


def test_offer_adjacent_windows_allowed(api):
    """PRD §3.5: "Two window rules guard creation, both tier seven in §2.10:
    `valid_from` must be strictly earlier than `valid_until` (otherwise
    `ERR_OFFER_WINDOW_INVALID`, HTTP 400), and the new window must not overlap
    any existing `ACTIVE` offer of the same merchant and category — overlap
    under the half-open convention is rejected with
    `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), while mere adjacency, one offer's
    `valid_until` equaling another's `valid_from`, is permitted."
    Offer A covers [2026-01-01, 2026-03-01) and offer B starts exactly where A
    ends: adjacency, permitted under half-open semantics.

    Design: Difficulty/resource_temporal_overlap/offer_half_open_window_adjacency_allowed
    """
    merchant = create_merchant(name="Overlap Outfit", reimbursement_rate_pct=25,
                               monthly_reimbursement_cap_cents=50000)
    m_h = make_merchant_operator_headers(merchant["id"])
    offer_a = validate_success(api.create_offer(
        merchant["id"],
        create_offer_payload("GROCERY", 10, 500, "2026-01-01", "2026-03-01"),
        m_h), 201)
    assert offer_a["status"] == "ACTIVE"
    offer_b = validate_success(api.create_offer(
        merchant["id"],
        create_offer_payload("GROCERY", 15, 500, "2026-03-01", "2026-05-01"),
        m_h), 201)
    assert offer_b["status"] == "ACTIVE", (
        "B.valid_from == A.valid_until is adjacency, allowed under half-open "
        "[valid_from, valid_until) semantics")


def test_offer_overlap_rejected_and_scoped_per_category(api):
    """PRD §3.5: "Two window rules guard creation, both tier seven in §2.10:
    `valid_from` must be strictly earlier than `valid_until` (otherwise
    `ERR_OFFER_WINDOW_INVALID`, HTTP 400), and the new window must not overlap
    any existing `ACTIVE` offer of the same merchant and category — overlap
    under the half-open convention is rejected with
    `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), while mere adjacency, one offer's
    `valid_until` equaling another's `valid_from`, is permitted."
    Offer C [2026-02-15, 2026-04-01) genuinely overlaps the existing GROCERY
    offer; offer D's PHARMACY window is a separate merchant+category scope.

    Design: Difficulty/resource_temporal_overlap/offer_half_open_window_adjacency_allowed
    """
    merchant = create_merchant(name="Overlap Outfit", reimbursement_rate_pct=25,
                               monthly_reimbursement_cap_cents=50000)
    m_h = make_merchant_operator_headers(merchant["id"])
    validate_success(api.create_offer(
        merchant["id"],
        create_offer_payload("GROCERY", 10, 500, "2026-01-01", "2026-03-01"),
        m_h), 201)

    res = api.create_offer(
        merchant["id"],
        create_offer_payload("GROCERY", 20, 500, "2026-02-15", "2026-04-01"),
        m_h)
    validate_error(res, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP)

    offer_d = validate_success(api.create_offer(
        merchant["id"],
        create_offer_payload("PHARMACY", 20, 500, "2026-02-01", "2026-02-20"),
        m_h), 201)
    assert offer_d["status"] == "ACTIVE", (
        "overlap is scoped per merchant and category: PHARMACY is separate")


def test_offer_window_inverted_rejected(api):
    """PRD §3.5: "Two window rules guard creation, both tier seven in §2.10:
    `valid_from` must be strictly earlier than `valid_until` (otherwise
    `ERR_OFFER_WINDOW_INVALID`, HTTP 400), and the new window must not overlap
    any existing `ACTIVE` offer of the same merchant and category — overlap
    under the half-open convention is rejected with
    `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), while mere adjacency, one offer's
    `valid_until` equaling another's `valid_from`, is permitted."

    Design: Corner/validations/offer_window_inverted_rejected
    """
    merchant = create_merchant(name="Window Works", reimbursement_rate_pct=25,
                               monthly_reimbursement_cap_cents=50000)
    res = api.create_offer(
        merchant["id"],
        create_offer_payload("RETAIL", 10, 500, "2026-05-01", "2026-01-01"),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_OFFER_WINDOW_INVALID)


def test_offer_auto_retires_then_usage_finds_none(api):
    """PRD §3.5: "Once the clock date reaches an offer's `valid_until`, the
    offer retires automatically to `RETIRED`."
    PRD §3.6: "If no offer covers the sale, the transaction is rejected with
    `ERR_NO_ACTIVE_OFFER` (HTTP 422)."
    The exclusive upper bound: at clock date 2026-08-01 the offer with
    valid_until 2026-08-01 no longer covers the sale.

    Design: Corner/state_machines/offer_auto_retires_at_valid_until_then_usage_finds_none
    """
    onboard = onboard_cardholder(full_name="Offer Otto",
                                 residency_address="37 Expire St")
    merchant, offer = setup_merchant_with_offer(
        merchant_overrides={"name": "Expiry Eats"},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100,
                         "valid_from": "2026-01-01", "valid_until": "2026-08-01"})

    set_clock("2026-08-01T00:00:00Z")
    offers = validate_success(
        api.list_offers(merchant["id"],
                        make_merchant_operator_headers(merchant["id"])), 200)
    retired = [o for o in offers if o["id"] == offer["id"]][0]
    assert retired["status"] == "RETIRED", (
        "clock date >= valid_until retires the offer (exclusive upper bound)")

    res = api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_OFFER)


def test_merchant_termination_cascades_offers_and_claims(api,
                                                         program_administrator_headers):
    """PRD §3.5: "Termination, also an administrator action, requires the
    merchant to be `ACTIVE` (otherwise `ERR_MERCHANT_NOT_ACTIVE`, HTTP 409)
    and moves the merchant to the terminal `TERMINATED` status with two
    cascades: every `ACTIVE` offer of the merchant becomes `RETIRED`, and
    every still-`SUBMITTED` reimbursement claim of the merchant is denied with
    `denial_reason` recorded as `MERCHANT_TERMINATED`."

    Design: Corner/state_machines/merchant_termination_cascades_offers_and_claims
    """
    onboard = onboard_cardholder(full_name="Term Tee", residency_address="36 End Blvd")
    merchant, offer = setup_merchant_with_offer(
        merchant_overrides={"name": "Term Traders", "reimbursement_rate_pct": 50},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    set_clock("2026-08-05T10:00:00Z")
    post_transactions(onboard["card"]["id"], merchant["id"], 1, 1000)
    set_clock("2026-09-01T00:00:00Z")
    claim = file_claim(merchant["id"], "2026-08")
    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_amount_cents"] == 50, (
        "one line: round_half_up(100 * 50 / 100) = 50")

    terminated = validate_success(
        api.terminate_merchant(merchant["id"], program_administrator_headers), 200)
    assert terminated["status"] == "TERMINATED"

    offers = validate_success(
        api.list_offers(merchant["id"], program_administrator_headers), 200)
    offer_after = [o for o in offers if o["id"] == offer["id"]][0]
    assert offer_after["status"] == "RETIRED", "termination retires ACTIVE offers"

    claims = list_claims(merchant["id"])
    claim_after = [c for c in claims if c["id"] == claim["id"]][0]
    assert claim_after["status"] == "DENIED"
    assert claim_after["denial_reason"] == "MERCHANT_TERMINATED"


def test_terminated_merchant_blocks_usage(api, program_administrator_headers):
    """PRD §3.5: "A terminated merchant can no longer record usage, publish
    offers, or file claims — each such attempt is rejected with
    `ERR_MERCHANT_NOT_ACTIVE`."
    Card and cardholder are both in good standing, so the pinned
    card -> cardholder -> merchant order reaches the merchant check.

    Design: Corner/validations/merchant_terminated_blocks_usage
    """
    onboard = onboard_cardholder(full_name="Term Usage",
                                 residency_address="50 Closed St")
    merchant, _ = setup_merchant_with_offer(
        merchant_overrides={"name": "Soon Closed"},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    validate_success(
        api.terminate_merchant(merchant["id"], program_administrator_headers), 200)

    res = api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_MERCHANT_NOT_ACTIVE)


def test_waiver_touching_dates_conflict(api, program_administrator_headers):
    """PRD §3.5: "Granting requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`). The
    interval must be well formed — `start_date` on or before `end_date`, else
    `ERR_WAIVER_WINDOW_INVALID` (HTTP 400) — and must not overlap any existing
    grant of the same cardholder and waiver type; because waiver intervals are
    closed, even touching dates conflict, and an overlap is rejected with
    `ERR_WAIVER_WINDOW_OVERLAP` (HTTP 409)."
    Waiver B starts on 2026-01-31, the day waiver A ends: under closed
    intervals the shared date is a conflict.

    Design: Difficulty/resource_temporal_overlap/waiver_closed_interval_touching_conflicts
    """
    onboard = onboard_cardholder(full_name="Wendy Waiver",
                                 residency_address="16 Transit Way")
    ch_id = onboard["cardholder"]["id"]
    waiver_a = validate_success(api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("TRANSIT_FARE", "2026-01-01", "2026-01-31"),
        program_administrator_headers), 201)
    assert_fee_waiver_grant(waiver_a)

    res = api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("TRANSIT_FARE", "2026-01-31", "2026-02-28"),
        program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_WAIVER_WINDOW_OVERLAP)


def test_waiver_overlap_scoped_per_waiver_type(api, program_administrator_headers):
    """PRD §3.5: "Granting requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`). The
    interval must be well formed — `start_date` on or before `end_date`, else
    `ERR_WAIVER_WINDOW_INVALID` (HTTP 400) — and must not overlap any existing
    grant of the same cardholder and waiver type; because waiver intervals are
    closed, even touching dates conflict, and an overlap is rejected with
    `ERR_WAIVER_WINDOW_OVERLAP` (HTTP 409)."
    A FACILITY_FEE grant inside the TRANSIT_FARE window is a different
    cardholder+waiver_type scope and is permitted.

    Design: Difficulty/resource_temporal_overlap/waiver_closed_interval_touching_conflicts
    """
    onboard = onboard_cardholder(full_name="Wendy Waiver",
                                 residency_address="16 Transit Way")
    ch_id = onboard["cardholder"]["id"]
    validate_success(api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("TRANSIT_FARE", "2026-01-01", "2026-01-31"),
        program_administrator_headers), 201)

    waiver_c = validate_success(api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("FACILITY_FEE", "2026-01-15", "2026-02-15"),
        program_administrator_headers), 201)
    assert waiver_c["waiver_type"] == "FACILITY_FEE", (
        "overlap scope is per cardholder and waiver type")


def test_waiver_window_inverted_rejected(api, program_administrator_headers):
    """PRD §3.5: "Granting requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`). The
    interval must be well formed — `start_date` on or before `end_date`, else
    `ERR_WAIVER_WINDOW_INVALID` (HTTP 400) — and must not overlap any existing
    grant of the same cardholder and waiver type; because waiver intervals are
    closed, even touching dates conflict, and an overlap is rejected with
    `ERR_WAIVER_WINDOW_OVERLAP` (HTTP 409)."

    Design: Corner/validations/waiver_window_inverted_rejected
    """
    onboard = onboard_cardholder(full_name="Waiver Wendy",
                                 residency_address="47 Bus Blvd")
    res = api.grant_fee_waiver(
        onboard["cardholder"]["id"],
        create_fee_waiver_payload("TRANSIT_FARE", "2026-02-01", "2026-01-01"),
        program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_WAIVER_WINDOW_INVALID)


def test_fee_waiver_on_revoked_cardholder_rejected(api, fraud_analyst_headers,
                                                   program_administrator_headers):
    """PRD §3.5: "Granting requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`)."
    The cardholder here has been revoked; the waiver window itself is well
    formed, so the standing check is what fires.

    Design: Difficulty/cross_entity_state_dependency/fee_waiver_requires_cardholder_standing
    """
    onboard = onboard_cardholder(full_name="Waiver Gate",
                                 residency_address="15 Grant Ave")
    ch_id = onboard["cardholder"]["id"]
    revoked = validate_success(
        api.revoke_cardholder(ch_id, "confirmed duplicate identity",
                              fraud_analyst_headers), 200)
    assert revoked["status"] == "REVOKED"

    res = api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("TRANSIT_FARE", "2026-09-01", "2026-09-30"),
        program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_CARDHOLDER_NOT_ACTIVE)

    grants = validate_success(
        api.list_fee_waivers(ch_id, program_administrator_headers), 200)
    assert grants == [], "no fee waiver grant was persisted"


def test_fee_waiver_on_active_cardholder_succeeds(api,
                                                  program_administrator_headers):
    """PRD §3.5: "Granting requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`)."
    Control for the revoked-cardholder case: the identical well-formed window
    succeeds for a member in ACTIVE standing.

    Design: Difficulty/cross_entity_state_dependency/fee_waiver_requires_cardholder_standing
    """
    onboard = onboard_cardholder(full_name="Waiver Gate",
                                 residency_address="15 Grant Ave")
    ch_id = onboard["cardholder"]["id"]
    assert onboard["cardholder"]["status"] == "ACTIVE"

    grant = validate_success(api.grant_fee_waiver(
        ch_id,
        create_fee_waiver_payload("TRANSIT_FARE", "2026-09-01", "2026-09-30"),
        program_administrator_headers), 201)
    assert_fee_waiver_grant(grant)
    assert grant["waiver_type"] == "TRANSIT_FARE"
    assert grant["start_date"] == "2026-09-01"
    assert grant["end_date"] == "2026-09-30"
