"""Settlement computation: commission dual-variant, pinned evaluation order,
dispute/recompute cycle, sales-ledger compensation, SoD and OCC on approve, and
the end-event attendance gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_treasurer_headers, make_vendor_headers,
    create_settlement_approve_payload,
    compute_settlement, post_sale, get_settlement_for_assignment,
    setup_computed_ctx, setup_live_ctx, sell_ticket, reset_clock,
    api_client,
)

# Commission fixture: 11 ledger rows of 10,001 cents each -> gross 110,011.
#   Quoted (per-row, chronological): rows 1-9 at 10% round to 1000 each (9000);
#     row 10 straddles 100,000 -> round(9991*0.10) + round(10*0.12) = 999 + 1 = 1000;
#     row 11 above the threshold at 12% -> round(10001*0.12) = 1200.
#     Total quoted commission = 11200.
#   Final (aggregate): round(100000*0.10) + round(10011*0.12) = 10000 + 1201 = 11201.
SALES_11_ROWS = (10001,) * 11
GROSS_EXPECTED = 110011
COMMISSION_QUOTED = 11200
COMMISSION_FINAL = 11201
NET_EXPECTED = 98811  # 110011 - 11200 - 0 (booth fee already paid in full)


# ─── Commission dual variant across the settlement lifecycle ────────────────

def test_computed_settlement_uses_chronological_per_row_commission(api):
    """PRD §3.7: "Second, `commission_cents`, by the quoted (per-row) variant: the
    rows are walked in the same chronological order while a running cumulative gross
    is maintained; the applicable percentage for every row is `commission_pct_anchor`
    when the booth's tier is `ANCHOR` and `commission_pct_standard` otherwise; the
    first 100,000 cents of cumulative gross — one thousand dollars — are charged at
    that base percentage, and anything above the threshold is charged at two
    percentage points more."
    PRD §3.7: "A single row that straddles the threshold is split: the portion
    bringing the cumulative total up to 100,000 cents is rounded half-up at the base
    percentage, and the remainder is rounded half-up at the bumped percentage; every
    row's commission is rounded half-up to integer cents as it is processed, and a
    cumulative gross of exactly 100,000 cents is charged entirely at the base
    percentage."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverge
    """
    ctx = setup_computed_ctx(sales_cents=SALES_11_ROWS)
    computed = ctx["computed_settlement"]
    assert computed["status"] == "COMPUTED"
    assert computed["gross_sales_cents"] == GROSS_EXPECTED
    assert computed["commission_cents"] == COMMISSION_QUOTED, (
        f"quoted (per-row) commission must be 11200, got {computed['commission_cents']}"
    )


def test_mark_paid_requotes_commission_on_aggregate(api):
    """PRD §3.7: "At that moment the commission is re-quoted by the final
    (aggregate) variant and persisted as the audit figure: the assignment's whole
    ledger is netted into a single gross total with compensations included; if that
    total exceeds 100,000 cents, the commission is the base percentage on the first
    100,000 cents rounded half-up, plus the bumped percentage — base plus two
    percentage points — on the remainder, rounded half-up; otherwise it is the base
    percentage on the whole total, rounded half-up once."
    PRD §3.7: "Marking a settlement paid requires it to be `APPROVED`, else
    `ERR_SETTLEMENT_NOT_PAYABLE`, and moves it to `PAID`."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverge
    """
    ctx = setup_computed_ctx(sales_cents=SALES_11_ROWS)
    event_id = ctx["event"]["id"]
    settlement = ctx["computed_settlement"]
    approved = validate_success(
        api_client.approve_settlement(
            event_id, settlement["id"],
            create_settlement_approve_payload(settlement["version"]),
            TEST_USERS["treasurer_headers"],
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    paid = validate_success(
        api_client.mark_paid_settlement(event_id, settlement["id"],
                                        TEST_USERS["treasurer_headers"]),
        200,
    )
    assert paid["status"] == "PAID"
    assert paid["commission_cents"] == COMMISSION_FINAL, (
        f"final (aggregate) commission persisted at PAID must be 11201, got "
        f"{paid['commission_cents']}"
    )


# ─── Pinned evaluation order: gross -> commission -> outstanding fee -> net ──

def test_net_payout_computed_in_pinned_order(api):
    """PRD §3.7: "Third, the outstanding booth fee is taken as the final booth fee
    minus what has already been paid, never below zero."
    PRD §3.7: "Finally, `net_payout_cents` is the gross minus the commission minus
    the outstanding booth fee."

    Design: Difficulty/combinatorial_formula/settlement_net_payout_pinned_evaluation_order
    """
    ctx = setup_computed_ctx(sales_cents=SALES_11_ROWS)
    computed = ctx["computed_settlement"]
    assert computed["gross_sales_cents"] == GROSS_EXPECTED
    assert computed["commission_cents"] == COMMISSION_QUOTED
    assert computed["net_payout_cents"] == NET_EXPECTED, (
        f"net must be gross - commission - outstanding(0) = 98811, got "
        f"{computed['net_payout_cents']}"
    )


def test_net_payout_below_threshold_simple_case(api):
    """PRD §3.7: "Third, the outstanding booth fee is taken as the final booth fee
    minus what has already been paid, never below zero."
    PRD §3.7: "Finally, `net_payout_cents` is the gross minus the commission minus
    the outstanding booth fee."

    Design: Difficulty/combinatorial_formula/settlement_net_payout_pinned_evaluation_order
    """
    # One 50,000-cent sale at the standard 10%: commission 5000, net 45000.
    ctx = setup_computed_ctx(sales_cents=(50000,))
    computed = ctx["computed_settlement"]
    assert computed["gross_sales_cents"] == 50000
    assert computed["commission_cents"] == 5000
    assert computed["net_payout_cents"] == 45000


# ─── Dispute / recompute cycle ──────────────────────────────────────────────

def test_dispute_returns_settlement_to_computed_on_recompute(api):
    """PRD §3.7: "A vendor who disagrees with a computed settlement — verified by
    ownership, the caller's `X-User-ID` matching the VendorProfile `id` behind the
    underlying application — may dispute it, optionally with a `reason`, moving it
    from `COMPUTED` to `DISPUTED`."
    PRD §3.7: "Dispute is not a dead end: the treasurer recomputes, moving the
    settlement back to `COMPUTED`, and the `DISPUTED` → `COMPUTED` loop may cycle
    indefinitely until the parties converge."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recompute_cycle
    """
    ctx = setup_computed_ctx(sales_cents=(50000,))
    event_id = ctx["event"]["id"]
    settlement = ctx["computed_settlement"]

    disputed = validate_success(
        api_client.dispute_settlement(
            event_id, settlement["id"],
            make_vendor_headers(ctx["vendor"]["id"]),
            payload={"reason": "incorrect commission"},
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED"

    recomputed = compute_settlement(event_id, settlement["id"])
    assert recomputed["status"] == "COMPUTED"
    assert recomputed["gross_sales_cents"] == 50000


def test_dispute_recompute_cycle_repeats(api):
    """PRD §3.7: "Dispute is not a dead end: the treasurer recomputes, moving the
    settlement back to `COMPUTED`, and the `DISPUTED` → `COMPUTED` loop may cycle
    indefinitely until the parties converge."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recompute_cycle
    """
    ctx = setup_computed_ctx(sales_cents=(50000,))
    event_id = ctx["event"]["id"]
    settlement = ctx["computed_settlement"]
    vendor_headers = make_vendor_headers(ctx["vendor"]["id"])

    for reason in ("incorrect commission", "still wrong"):
        disputed = validate_success(
            api_client.dispute_settlement(event_id, settlement["id"],
                                          vendor_headers, payload={"reason": reason}),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        recomputed = compute_settlement(event_id, settlement["id"])
        assert recomputed["status"] == "COMPUTED", (
            "each treasurer recompute must return the settlement to COMPUTED"
        )

    final = get_success_data(api_client.get_settlement(
        event_id, settlement["id"], TEST_USERS["treasurer_headers"]))
    assert final["status"] == "COMPUTED"


# ─── Sales-ledger compensation (gross conservation) ─────────────────────────

def test_exact_reversal_nets_gross_to_zero(api):
    """PRD §3.7: "First, `gross_sales_cents`: the assignment's ledger rows are
    walked in chronological order — by `recorded_at` ascending, ties broken by
    `created_at` ascending — and each row's signed `gross_cents` accumulates,
    compensation rows subtracting as their negative amounts land; the accumulated
    gross is then floored at zero, since excess refunds are tracked separately
    rather than driving the gross negative."
    PRD §3.7: "Ending moves the posture from `LIVE` to `SETTLEMENT` and, in the same
    act, synthesizes one Settlement in `PENDING` status for every BoothAssignment
    still `ACTIVE`."

    Design: Difficulty/compensating_invariant/sales_ledger_gross_conservation_across_reversal
    """
    ctx = setup_live_ctx()
    event_id = ctx["event"]["id"]
    sale = post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"], 7500)
    reversal = post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"],
                         -7500, reversal_of_entry_id=sale["id"])
    assert reversal.get("reversal_of_entry_id") == sale["id"]

    reset_clock("2026-06-02T00:00:00Z")
    get_success_data(api_client.end_event(event_id, ctx["coordinator_headers"]))
    settlement = get_settlement_for_assignment(event_id, ctx["assignment"]["id"])
    computed = compute_settlement(event_id, settlement["id"])
    assert computed["gross_sales_cents"] == 0, (
        f"a +7500 sale compensated by its -7500 reversal must net to 0, got "
        f"{computed['gross_sales_cents']}"
    )


def test_partial_reversal_leaves_remaining_gross(api):
    """PRD §3.7: "First, `gross_sales_cents`: the assignment's ledger rows are
    walked in chronological order — by `recorded_at` ascending, ties broken by
    `created_at` ascending — and each row's signed `gross_cents` accumulates,
    compensation rows subtracting as their negative amounts land; the accumulated
    gross is then floored at zero, since excess refunds are tracked separately
    rather than driving the gross negative."

    Design: Difficulty/compensating_invariant/sales_ledger_gross_conservation_across_reversal
    """
    ctx = setup_live_ctx()
    event_id = ctx["event"]["id"]
    sale = post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"], 7500)
    post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"], 2500)
    post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"], -7500,
              reversal_of_entry_id=sale["id"])

    reset_clock("2026-06-02T00:00:00Z")
    get_success_data(api_client.end_event(event_id, ctx["coordinator_headers"]))
    settlement = get_settlement_for_assignment(event_id, ctx["assignment"]["id"])
    computed = compute_settlement(event_id, settlement["id"])
    assert computed["gross_sales_cents"] == 2500, (
        f"7500 + 2500 - 7500 must leave gross 2500, got {computed['gross_sales_cents']}"
    )
    assert computed["commission_cents"] == 250


# ─── Corner: ANCHOR tier commission override ────────────────────────────────

def test_anchor_booth_uses_reduced_commission(api):
    """PRD §3.7: "Second, `commission_cents`, by the quoted (per-row) variant: the
    rows are walked in the same chronological order while a running cumulative gross
    is maintained; the applicable percentage for every row is `commission_pct_anchor`
    when the booth's tier is `ANCHOR` and `commission_pct_standard` otherwise; the
    first 100,000 cents of cumulative gross — one thousand dollars — are charged at
    that base percentage, and anything above the threshold is charged at two
    percentage points more."

    Design: Corner/calculations/anchor_tier_uses_reduced_commission
    """
    ctx = setup_computed_ctx(
        sales_cents=(50000,),
        booth_specs=({"code": "A-01", "tier": "ANCHOR", "footprint_sqm": 25,
                      "price_cents": 8000},),
        app_tier="ANCHOR",
    )
    computed = ctx["computed_settlement"]
    assert computed["gross_sales_cents"] == 50000
    # ANCHOR tier applies commission_pct_anchor (0.05), not the standard 0.10.
    assert computed["commission_cents"] == 2500, (
        f"ANCHOR commission must be 50000 * 0.05 = 2500, got "
        f"{computed['commission_cents']}"
    )


# ─── Corner: segregation of duties on settlement approval ───────────────────

def test_settlement_approver_must_not_be_event_coordinator(api):
    """PRD §3.7: "The segregation-of-duties rule then applies: the approver's
    `X-User-ID` — recorded on the settlement as `approved_by_user_id` — must differ
    from the identifier of the coordinator who created the event, else
    `ERR_SOD_VIOLATION`."

    Design: Corner/rbac/segregation_of_duties_settlement_approver
    """
    ctx = setup_computed_ctx(sales_cents=(1000,),
                             coordinator_user_id="coordinator-X")
    settlement = ctx["computed_settlement"]
    res = api_client.approve_settlement(
        ctx["event"]["id"], settlement["id"],
        create_settlement_approve_payload(settlement["version"]),
        make_treasurer_headers("coordinator-X"),
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)


# ─── Corner: OCC on settlement approval ─────────────────────────────────────

def test_approve_with_stale_settlement_version_rejected(api):
    """PRD §2.8: "Approving a settlement requires the request to carry
    `expected_settlement_version`, holding the Settlement `version` the treasurer
    last observed; a mismatch with the settlement's current `version` is likewise
    rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the treasurer to re-read
    the figures before blessing them."

    Design: Corner/cross_cutting_complexity_layers/occ_settlement_approve_stale
    """
    ctx = setup_computed_ctx(sales_cents=(1000,))
    event_id = ctx["event"]["id"]
    stale_version = ctx["computed_settlement"]["version"]

    # Dispute + recompute mutate the settlement, advancing its version twice.
    validate_success(
        api_client.dispute_settlement(event_id, ctx["settlement"]["id"],
                                      make_vendor_headers(ctx["vendor"]["id"])),
        200,
    )
    compute_settlement(event_id, ctx["settlement"]["id"])

    res = api_client.approve_settlement(
        event_id, ctx["settlement"]["id"],
        create_settlement_approve_payload(stale_version),
        TEST_USERS["treasurer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_approve_with_current_settlement_version_succeeds(api):
    """PRD §2.8: "Approving a settlement requires the request to carry
    `expected_settlement_version`, holding the Settlement `version` the treasurer
    last observed; a mismatch with the settlement's current `version` is likewise
    rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the treasurer to re-read
    the figures before blessing them."
    PRD §3.7: "A successful approval moves the settlement to `APPROVED` and, as with
    any mutation, increments its `version` and refreshes `updated_at`."

    Design: Corner/cross_cutting_complexity_layers/occ_settlement_approve_stale
    """
    ctx = setup_computed_ctx(sales_cents=(1000,))
    event_id = ctx["event"]["id"]
    settlement = ctx["computed_settlement"]
    approved = validate_success(
        api_client.approve_settlement(
            event_id, settlement["id"],
            create_settlement_approve_payload(settlement["version"]),
            TEST_USERS["treasurer_headers"],
        ),
        200,
    )
    assert approved["status"] == "APPROVED"


# ─── Corner: end-event attendance gate ──────────────────────────────────────

def test_end_event_rejected_while_guest_on_site(api):
    """PRD §3.7: "Ending requires the logical clock to have reached `closes_at`,
    and it requires every guest to have left — any Attendance row with a null
    `exited_at` rejects the move with `ERR_UNRESOLVED_ATTENDANCE`."

    Design: Corner/cross_cutting_complexity_layers/posture_driven_gating_end_event_requires_no_onsite
    """
    ctx = setup_live_ctx()
    event_id = ctx["event"]["id"]
    ticket = sell_ticket(event_id, kind="GA")
    validate_success(
        api_client.redeem_ticket(event_id, ticket["id"],
                                 TEST_USERS["gate_agent_headers"]),
        200,
    )
    reset_clock("2026-06-02T00:00:00Z")
    # The guest never scanned out: their Attendance row still has exited_at null.
    res = api_client.end_event(event_id, ctx["coordinator_headers"])
    validate_error(res, ApiErrorId.ERR_UNRESOLVED_ATTENDANCE, expected_status=409)
