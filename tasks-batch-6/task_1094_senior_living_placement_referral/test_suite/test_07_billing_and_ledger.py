"""Invoice issue/accept/dispute/adjust/pay/void, the move-out clawback cascade,
and the append-only fee ledger.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    set_clock, build_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: move-out depth-3 clawback cascade (>=2 tests).
# ---------------------------------------------------------------------------

def test_move_out_full_clawback_reverses_recognized_fee(api):
    """PRD §3.13: "the clawback percentage is 1.00 when `days_resided` is at most 30
    ... The `clawback_amount_cents` is the placement's `final_fee_cents` multiplied
    by that percentage, rounded half up to whole cents. When it is greater than 0
    the referral invoice moves to `CLAWED_BACK` and the placement's billing axis
    moves to `CLAWED_BACK`."

    Design: Difficulty/transitive_cascade/move_out_depth3_chain_from_inventory_release_to_clawback_ledger_entry
    """
    sc = build_scenario(api, "paid")
    set_clock(api, "2026-07-10T09:00:00Z")
    validate_success(api.move_out(sc["placement"]["id"], {"move_out_date": "2026-07-10", "reason_code": "HOSPITALIZATION"}, sc["cm_headers"]))
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "MOVED_OUT"
    assert p["days_resided"] == 20
    assert p["clawback_amount_cents"] == 180583
    assert p["billing_status"] == "CLAWED_BACK"
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "CLAWED_BACK"
    assert inv["net_recognized_fee_cents"] == 0


def test_move_out_clawback_books_ledger_and_frees_unit(api):
    """PRD §3.13: "**Level 3**, caused by a positive clawback, appends a `CLAWBACK`
    ledger entry whose `amount_cents` is the negative of `clawback_amount_cents`,
    decreases the community's `fee_balance_cents` by `clawback_amount_cents`, and
    recomputes the invoice's `net_recognized_fee_cents`."

    Design: Difficulty/transitive_cascade/move_out_depth3_chain_from_inventory_release_to_clawback_ledger_entry
    """
    sc = build_scenario(api, "paid")
    set_clock(api, "2026-07-10T09:00:00Z")
    validate_success(api.move_out(sc["placement"]["id"], {"move_out_date": "2026-07-10", "reason_code": "HOSPITALIZATION"}, sc["cm_headers"]))
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == -180583
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv["occupied_units"] == 0 and inv["available_units"] == 5
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"placement_id": sc["placement"]["id"]}))
    assert len(rows) == 3
    clawbacks = [r for r in rows if r["entry_type"] == "CLAWBACK"]
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -180583
    assert clawbacks[0]["balance_after_cents"] == -180583


# ---------------------------------------------------------------------------
# Difficulty: void restores the fee balance to its pre-issue value (>=2 tests).
# ---------------------------------------------------------------------------

def test_invoice_void_restores_community_fee_balance(api):
    """PRD §3.12: "Voiding ... appends a `WRITE_OFF` ledger entry of negative
    `final_fee_cents`, decreases the community's `fee_balance_cents` by
    `final_fee_cents`, recomputes `net_recognized_fee_cents`, moves the invoice to
    `VOIDED`, and moves the placement's billing axis `INVOICED → VOIDED`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_community_fee_balance_to_pre_issue_value
    """
    sc = build_scenario(api, "issued")
    validate_success(api.void_invoice(sc["invoice"]["id"], {"reason_code": "DUPLICATE_BILLING"}, sc["billing"]))
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 0
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "VOIDED"
    assert inv["net_recognized_fee_cents"] == 0
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["billing_status"] == "VOIDED"
    assert p["residency_status"] == "MOVED_IN"


def test_invoice_void_ledger_is_accrual_then_write_off(api):
    """PRD §3.13: "A community's `fee_balance_cents` is the running total of
    `amount_cents` over all its entries, processed in ascending `created_at` order
    ... Each entry's `balance_after_cents` records the running total immediately
    after it is applied."

    Design: Difficulty/compensating_invariant/invoice_void_restores_community_fee_balance_to_pre_issue_value
    """
    sc = build_scenario(api, "issued")
    validate_success(api.void_invoice(sc["invoice"]["id"], {"reason_code": "DUPLICATE_BILLING"}, sc["billing"]))
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"invoice_id": sc["invoice"]["id"]}))
    assert len(rows) == 2
    assert rows[0]["entry_type"] == "ACCRUAL"
    assert rows[0]["amount_cents"] == 180583 and rows[0]["balance_after_cents"] == 180583
    assert rows[1]["entry_type"] == "WRITE_OFF"
    assert rows[1]["amount_cents"] == -180583 and rows[1]["balance_after_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: invoice guards.
# ---------------------------------------------------------------------------

def test_paying_accepted_invoice_with_wrong_amount_rejected(api):
    """PRD §3.12: "Paying requires the invoice to be `ACCEPTED` and the community
    manager to own it, and the body's `amount_cents` must exactly equal the
    invoice's `final_fee_cents`, else `ERR_INVOICE_AMOUNT_MISMATCH`."

    Design: Corner/validations/paying_an_accepted_invoice_with_the_wrong_amount_returns_amount_mismatch
    """
    sc = build_scenario(api, "accepted")
    resp = api.pay_invoice(sc["invoice"]["id"], {"amount_cents": 180000}, sc["cm_headers"])
    validate_error(resp, ApiErrorId.ERR_INVOICE_AMOUNT_MISMATCH)
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "ACCEPTED"
    assert inv["paid_amount_cents"] == 0
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 180583
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"invoice_id": sc["invoice"]["id"]}))
    assert len(rows) == 1 and rows[0]["entry_type"] == "ACCRUAL"


def test_accepting_a_draft_invoice_rejected(api):
    """PRD §3.12: "Accepting moves an `ISSUED` invoice to `ACCEPTED`."
    PRD §3.12: "Any of these invoice actions attempted from a state outside its
    from-set yields `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/validations/accepting_a_draft_invoice_returns_invoice_invalid_state
    """
    sc = build_scenario(api, "moved_in")
    resp = api.accept_invoice(sc["invoice"]["id"], sc["cm_headers"])
    validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "DRAFT"
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["billing_status"] == "INVOICE_DRAFTED"
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 0


def test_third_dispute_round_returns_dispute_limit_exceeded(api):
    """PRD §3.12: "Disputing an `ISSUED` invoice records a `dispute_reason` and a
    `claimed_rate_cents`, moves it `ISSUED → DISPUTED`, and is permitted only while
    `adjustment_count` is strictly below the dispute-round cap of 2, else
    `ERR_DISPUTE_LIMIT_EXCEEDED`."

    Design: Corner/validations/third_dispute_round_returns_dispute_limit_exceeded
    """
    sc = build_scenario(api, "issued")
    inv_id = sc["invoice"]["id"]
    cm, billing = sc["cm_headers"], sc["billing"]
    validate_success(api.dispute_invoice(inv_id, {"dispute_reason": "Too high.", "claimed_rate_cents": 460000}, cm))
    validate_success(api.adjust_invoice(inv_id, {"adjusted_rate_cents": 460000, "note": "round 1"}, billing))
    validate_success(api.dispute_invoice(inv_id, {"dispute_reason": "Still high.", "claimed_rate_cents": 450000}, cm))
    validate_success(api.adjust_invoice(inv_id, {"adjusted_rate_cents": 450000, "note": "round 2"}, billing))
    resp = api.dispute_invoice(inv_id, {"dispute_reason": "One more look.", "claimed_rate_cents": 440000}, cm)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_LIMIT_EXCEEDED)
    inv = validate_success(api.get_invoice(inv_id, ADMIN))
    assert inv["status"] == "ISSUED"
    assert inv["adjustment_count"] == 2
    assert inv["final_fee_cents"] == 162525
    assert inv["net_recognized_fee_cents"] == 162525
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 162525
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"invoice_id": inv_id}))
    assert [(r["entry_type"], r["amount_cents"]) for r in rows] == [
        ("ACCRUAL", 180583), ("ADJUSTMENT", -14446), ("ADJUSTMENT", -3612)]


def test_issuing_an_invoice_after_move_out_rejected(api):
    """PRD §3.12: "A billing specialist issues a `DRAFT` invoice, but only while the
    linked placement's residency is `MOVED_IN` or `RESIDENT_CONFIRMED`, else
    `ERR_PLACEMENT_NOT_MOVED_IN`".

    Design: Corner/validations/issuing_an_invoice_after_move_out_returns_placement_not_moved_in
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-10T09:00:00Z")
    validate_success(api.move_out(sc["placement"]["id"], {"move_out_date": "2026-07-10", "reason_code": "HOSPITALIZATION"}, sc["cm_headers"]))
    resp = api.issue_invoice(sc["invoice"]["id"], sc["billing"])
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_MOVED_IN)
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "MOVED_OUT" and p["days_resided"] == 20
    assert p["clawback_amount_cents"] == 0
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "DRAFT"
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 0
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"placement_id": sc["placement"]["id"]}))
    assert rows == []


def test_move_out_dated_before_move_in_rejected(api):
    """PRD §3.13: "`move_out_date` must be on or after the `actual_move_in_date` and
    on or before the logical clock's current UTC calendar date, else
    `ERR_MOVE_OUT_DATE_INVALID`."

    Design: Corner/validations/move_out_dated_before_move_in_returns_move_out_date_invalid
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-10T09:00:00Z")
    resp = api.move_out(sc["placement"]["id"], {"move_out_date": "2026-06-10", "reason_code": "HOSPITALIZATION"}, sc["cm_headers"])
    validate_error(resp, ApiErrorId.ERR_MOVE_OUT_DATE_INVALID)
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "MOVED_IN"
    assert p["move_out_date"] is None and p["days_resided"] is None
    assert p["clawback_amount_cents"] == 0
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv["occupied_units"] == 1 and inv["available_units"] == 4


# ---------------------------------------------------------------------------
# Corner: referral-fee calculation edges.
# ---------------------------------------------------------------------------

def test_clawback_is_full_at_exactly_thirty_days(api):
    """PRD §3.13: "both boundaries are inclusive, so exactly 30 days is a full
    clawback and exactly 90 days is a half clawback."

    Design: Corner/calculations/clawback_is_full_at_exactly_thirty_days_of_residency
    """
    sc = build_scenario(api, "paid")
    set_clock(api, "2026-07-20T09:00:00Z")
    validate_success(api.move_out(sc["placement"]["id"], {"move_out_date": "2026-07-20", "reason_code": "MOVED_TO_FAMILY"}, sc["cm_headers"]))
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["days_resided"] == 30
    assert p["clawback_amount_cents"] == 180583
    assert p["billing_status"] == "CLAWED_BACK"
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "CLAWED_BACK"
    assert inv["net_recognized_fee_cents"] == 0
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == -180583
    rows, _ = validate_paginated(api.list_ledger_entries(
        ADMIN, params={"placement_id": sc["placement"]["id"], "entry_type": "CLAWBACK"}))
    assert len(rows) == 1 and rows[0]["amount_cents"] == -180583


def test_referral_fee_final_raised_to_minimum_clamp(api):
    """PRD §3.11: "Sum the three components, then clamp the total to lie between a
    floor of 150000 cents and a ceiling of 900000 cents — the clamp is applied last,
    to the summed total only."

    Design: Corner/calculations/referral_fee_final_is_raised_to_the_minimum_fee_clamp
    """
    sc = build_scenario(
        api, "moved_in",
        community_overrides={"name": "Bluebonnet Villas", "contract_tier": "STANDARD",
                             "referral_fee_pct": 0.85},
        inventory_overrides={"care_level": "INDEPENDENT_LIVING", "monthly_rate_cents": 300000},
        care_level="INDEPENDENT_LIVING",
        placement_overrides={"contracted_monthly_rate_cents": 300000},
        actual_care_level="INDEPENDENT_LIVING")
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["estimated_fee_cents"] == 255000
    assert p["final_fee_cents"] == 150000
    rows, _ = validate_paginated(api.list_invoices(sc["billing"], params={"placement_id": p["id"]}))
    assert len(rows) == 1
    assert rows[0]["final_fee_cents"] == 150000 and rows[0]["status"] == "DRAFT"
