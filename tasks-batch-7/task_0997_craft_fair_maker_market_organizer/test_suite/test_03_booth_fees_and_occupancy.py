"""Booth fee dual-variant (per-line vs sum-then-round), booth occupancy as an
aggregate-capacity rule, fee-charge conservation across pay+forfeit, and the
payment deadline."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    make_vendor_headers,
    assert_booth_fee_charge,
    create_event, create_zone, create_booth, create_vendor,
    open_applications, create_application, submit_application,
    close_applications, post_jury_scores, decide_application,
    begin_scheduling, get_assignment_for_app, pay_assignment,
    forfeit_assignment, list_charges, charge_by_kind,
    reset_clock, setup_approved_ctx, setup_paid_ctx,
    api_client,
)

# Tie-sensitive fee fixture: base=12333, tier=CORNER (x1.25), category=FOOD (+10%).
#   PROVISIONAL (per-line): round(12333*1.25) + round(12333*0.10)
#                         = 15416 + 1233 = 16649
#   FINAL (sum-then-round): round(12333*1.25 + 12333*0.10)
#                         = round(16649.55) = 16650
FEE_ZONE = {"label": "Food Court", "weather_exposure": "COVERED",
            "category": "FOOD", "category_cap": 5}
FEE_BOOTH = {"code": "FC-01", "tier": "CORNER", "footprint_sqm": 12,
             "price_cents": 12333}
FEE_APP = {"app_category": "FOOD", "app_tier": "CORNER"}
PROVISIONAL_EXPECTED = 16649
FINAL_EXPECTED = 16650


def _fee_ctx(**kwargs):
    merged = dict(zone_overrides=FEE_ZONE, booth_specs=[FEE_BOOTH], **FEE_APP)
    merged.update(kwargs)
    return merged


# ─── Dual variant: provisional quote vs final charge ────────────────────────

def test_provisional_booth_fee_uses_per_line_rounding(api):
    """PRD §3.3: "The quote takes the booth's base `price_cents`, applies a tier
    multiplier of 1.00 for `STANDARD`, 1.25 for `CORNER`, or 1.60 for `ANCHOR`, and
    applies a category uplift of ten percent for `FOOD` zones, five percent for
    `MIXED` zones, and no uplift otherwise — a booth's zone lineage is readable
    through its system-maintained `booth_zone_id`; the tier component — base
    multiplied by the tier multiplier — is rounded half-up to integer cents, the
    uplift component — base multiplied by the uplift percentage — is likewise
    rounded half-up to integer cents, and the provisional amount is the sum of those
    two rounded components, with `rounding_trace` recording `per_line_then_sum`."

    Design: Difficulty/dual_variant_calc/booth_fee_provisional_vs_final_diverge
    """
    ctx = setup_approved_ctx(**_fee_ctx())
    charges = list_charges(ctx["event"]["id"], ctx["assignment"]["id"])
    provisional = charge_by_kind(charges, "PROVISIONAL")
    assert len(provisional) == 1, f"expected one PROVISIONAL row, got {charges}"
    assert_booth_fee_charge(provisional[0])
    assert provisional[0]["amount_cents"] == PROVISIONAL_EXPECTED, (
        f"per-line provisional fee must be 16649, got {provisional[0]['amount_cents']}"
    )


def test_final_booth_fee_diverges_by_one_cent_after_pay(api):
    """PRD §3.5: "Payment mints the final booth fee: a `FINAL` BoothFeeCharge
    computed by the sum-then-round order — the exact total of base times the tier
    multiplier plus base times the category uplift, rounded half-up to integer cents
    in a single rounding — with `rounding_trace` recording `sum_then_round`."
    PRD §3.5: "On tie-sensitive base prices the final charge can differ from the
    provisional quote by a cent either way; the `PROVISIONAL` row is never altered
    and remains for audit."

    Design: Difficulty/dual_variant_calc/booth_fee_provisional_vs_final_diverge
    """
    ctx = setup_paid_ctx(**_fee_ctx())
    assert ctx["paid_assignment"]["status"] == "ACTIVE"
    charges = list_charges(ctx["event"]["id"], ctx["assignment"]["id"])
    provisional = charge_by_kind(charges, "PROVISIONAL")
    final = charge_by_kind(charges, "FINAL")
    assert len(provisional) == 1 and len(final) == 1, (
        f"expected one PROVISIONAL and one FINAL row, got {charges}"
    )
    assert provisional[0]["amount_cents"] == PROVISIONAL_EXPECTED, (
        "PROVISIONAL row must remain unaltered for audit"
    )
    assert final[0]["amount_cents"] == FINAL_EXPECTED, (
        f"sum-then-round final fee must be 16650, got {final[0]['amount_cents']}"
    )


# ─── Pinned rounding orders (audit trace) ───────────────────────────────────

def test_provisional_charge_records_per_line_trace(api):
    """PRD §2.7: "The **provisional** booth fee rounds each component to integer
    cents first and then sums the components; its `rounding_trace` audit string
    records `per_line_then_sum`."

    Design: Difficulty/combinatorial_formula/booth_fee_rounding_order_pinned
    """
    ctx = setup_approved_ctx(**_fee_ctx())
    charges = list_charges(ctx["event"]["id"], ctx["assignment"]["id"])
    provisional = charge_by_kind(charges, "PROVISIONAL")
    assert len(provisional) == 1
    assert provisional[0]["amount_cents"] == PROVISIONAL_EXPECTED
    assert provisional[0]["rounding_trace"] == "per_line_then_sum", (
        f"provisional rounding_trace must be per_line_then_sum, got "
        f"{provisional[0].get('rounding_trace')}"
    )


def test_final_charge_records_sum_then_round_trace(api):
    """PRD §2.7: "The **final** booth fee sums the exact, unrounded components and
    rounds once at the end; its `rounding_trace` records `sum_then_round`."
    PRD §3.5: "On tie-sensitive base prices the final charge can differ from the
    provisional quote by a cent either way; the `PROVISIONAL` row is never altered
    and remains for audit."

    Design: Difficulty/combinatorial_formula/booth_fee_rounding_order_pinned
    """
    ctx = setup_paid_ctx(**_fee_ctx())
    charges = list_charges(ctx["event"]["id"], ctx["assignment"]["id"])
    final = charge_by_kind(charges, "FINAL")
    provisional = charge_by_kind(charges, "PROVISIONAL")
    assert len(final) == 1, "payment must mint exactly one FINAL charge"
    assert final[0]["rounding_trace"] == "sum_then_round", (
        f"final rounding_trace must be sum_then_round, got "
        f"{final[0].get('rounding_trace')}"
    )
    assert final[0]["amount_cents"] == FINAL_EXPECTED
    assert len(provisional) == 1 and provisional[0]["amount_cents"] == PROVISIONAL_EXPECTED


# ─── Booth occupancy: aggregate-capacity (boolean) semantics ────────────────

def test_second_approval_on_occupied_booth_rejected(api):
    """PRD §3.5: "The booth-occupancy invariant underpins all of this: at most one
    assignment in `PENDING_PAYMENT` or `ACTIVE` may exist per booth at any moment —
    a boolean occupancy rule, deliberately distinct from the time-interval rule for
    load slots below."
    PRD §3.3: "The checks guarding a decision run in a fixed order, so that earlier
    failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."

    Design: Difficulty/resource_temporal_overlap/booth_assignment_aggregate_capacity_semantics
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="DoubleBook Fair")
    zone = create_zone(event["id"], coordinator, category_cap=5)
    create_booth(event["id"], zone["id"], coordinator, code="H-01")
    v1, v2 = create_vendor(), create_vendor()
    open_applications(event["id"], coordinator)
    app1 = create_application(event["id"], v1)
    submit_application(event["id"], app1["id"], v1["id"])
    app2 = create_application(event["id"], v2)
    submit_application(event["id"], app2["id"], v2["id"])
    close_applications(event["id"], coordinator)
    post_jury_scores(event["id"], app1["id"], cards=((9, 9, 9), (9, 9, 9)))
    post_jury_scores(event["id"], app2["id"])

    res1 = decide_application(event["id"], app1["id"], "APPROVE", coordinator)
    validate_success(res1, 200)
    assignment = get_assignment_for_app(event["id"], app1["id"], coordinator)
    assert assignment["status"] == "PENDING_PAYMENT"

    # The only booth matching (CERAMICS, STANDARD) is already occupied by a
    # PENDING_PAYMENT assignment, so the second approval has no grantable booth.
    res2 = decide_application(event["id"], app2["id"], "APPROVE", coordinator)
    validate_error(res2, ApiErrorId.ERR_BOOTH_DOUBLE_BOOKED, expected_status=409)


def test_approval_skips_occupied_booth_then_pool_exhausted(api):
    """PRD §3.3: "The system grants a booth by selector policy: among booths whose
    zone category matches the `requested_category`, whose `tier` matches the
    `requested_tier`, and which are unoccupied, it chooses the lowest-priced; ties
    break by booth `code` in ascending order, and any remaining tie by the booth's
    `created_at` in ascending order."
    PRD §3.5: "The booth-occupancy invariant underpins all of this: at most one
    assignment in `PENDING_PAYMENT` or `ACTIVE` may exist per booth at any moment —
    a boolean occupancy rule, deliberately distinct from the time-interval rule for
    load slots below."

    Design: Difficulty/resource_temporal_overlap/booth_assignment_aggregate_capacity_semantics
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="Pool Fair")
    zone = create_zone(event["id"], coordinator, category_cap=5)
    cheap = create_booth(event["id"], zone["id"], coordinator,
                         code="H-01", price_cents=4000)
    dear = create_booth(event["id"], zone["id"], coordinator,
                        code="H-02", price_cents=6000)
    vendors = [create_vendor() for _ in range(3)]
    open_applications(event["id"], coordinator)
    apps = []
    for v in vendors:
        app = create_application(event["id"], v)
        submit_application(event["id"], app["id"], v["id"])
        apps.append(app)
    close_applications(event["id"], coordinator)
    for app in apps:
        post_jury_scores(event["id"], app["id"])

    res1 = decide_application(event["id"], apps[0]["id"], "APPROVE", coordinator)
    validate_success(res1, 200)
    first = get_assignment_for_app(event["id"], apps[0]["id"], coordinator)
    assert first["booth_id"] == cheap["id"], (
        "selector must grant the lowest-priced matching unoccupied booth"
    )

    res2 = decide_application(event["id"], apps[1]["id"], "APPROVE", coordinator)
    validate_success(res2, 200)
    second = get_assignment_for_app(event["id"], apps[1]["id"], coordinator)
    assert second["booth_id"] == dear["id"], (
        "with the cheapest booth occupied, the selector takes the next unoccupied one"
    )

    res3 = decide_application(event["id"], apps[2]["id"], "APPROVE", coordinator)
    validate_error(res3, ApiErrorId.ERR_BOOTH_DOUBLE_BOOKED, expected_status=409)


# ─── Fee-charge conservation across pay + forfeit ───────────────────────────

def test_pay_then_forfeit_conserves_fee_total(api):
    """PRD §3.5: "A forfeited assignment mints a `REFUND` charge returning whatever
    was paid (zero when nothing was), clears the booth's `assigned_application_id`,
    cancels any Settlement tied to the assignment, and runs the waitlist promotion
    scan."
    PRD §3.5: "Payment mints the final booth fee: a `FINAL` BoothFeeCharge computed
    by the sum-then-round order — the exact total of base times the tier multiplier
    plus base times the category uplift, rounded half-up to integer cents in a single
    rounding — with `rounding_trace` recording `sum_then_round`."

    Design: Difficulty/compensating_invariant/booth_fee_charge_conservation_across_forfeit
    """
    # STANDARD booth priced 5000, no uplift: FINAL == 5000; REFUND == -5000.
    ctx = setup_paid_ctx()
    event_id = ctx["event"]["id"]
    forfeited = forfeit_assignment(event_id, ctx["assignment"]["id"],
                                   ctx["vendor"]["id"])
    assert forfeited["status"] == "FORFEITED"
    charges = list_charges(event_id, ctx["assignment"]["id"])
    final = charge_by_kind(charges, "FINAL")
    refund = charge_by_kind(charges, "REFUND")
    assert len(final) == 1 and final[0]["amount_cents"] == 5000
    assert len(refund) == 1, "forfeiture must mint a REFUND charge"
    assert refund[0]["amount_cents"] == -5000
    net = sum(c["amount_cents"] for c in final + refund)
    assert net == 0, (
        f"FINAL + REFUND must net to zero across the assignment, got {net}"
    )


def test_conservation_holds_on_rounding_sensitive_fee(api):
    """PRD §3.5: "A forfeited assignment mints a `REFUND` charge returning whatever
    was paid (zero when nothing was), clears the booth's `assigned_application_id`,
    cancels any Settlement tied to the assignment, and runs the waitlist promotion
    scan."
    PRD §3.5: "On tie-sensitive base prices the final charge can differ from the
    provisional quote by a cent either way; the `PROVISIONAL` row is never altered
    and remains for audit."

    Design: Difficulty/compensating_invariant/booth_fee_charge_conservation_across_forfeit
    """
    # CORNER/FOOD booth priced 12333: FINAL == 16650 while PROVISIONAL == 16649;
    # the REFUND compensates the FINAL (what was actually paid), not the quote.
    ctx = setup_paid_ctx(**_fee_ctx())
    event_id = ctx["event"]["id"]
    forfeited = forfeit_assignment(event_id, ctx["assignment"]["id"],
                                   ctx["vendor"]["id"])
    assert forfeited["status"] == "FORFEITED"
    charges = list_charges(event_id, ctx["assignment"]["id"])
    final = charge_by_kind(charges, "FINAL")
    refund = charge_by_kind(charges, "REFUND")
    provisional = charge_by_kind(charges, "PROVISIONAL")
    assert len(final) == 1 and final[0]["amount_cents"] == 16650
    assert len(refund) == 1 and refund[0]["amount_cents"] == -16650, (
        "REFUND must return what was paid — the FINAL amount, not the quote"
    )
    assert final[0]["amount_cents"] + refund[0]["amount_cents"] == 0
    assert len(provisional) == 1 and provisional[0]["amount_cents"] == 16649, (
        "PROVISIONAL row is never altered and remains for audit"
    )
    booth = get_success_data(api_client.get_booth(ctx["booths"][0]["id"],
                                                  ctx["coordinator_headers"]))
    assert booth.get("assigned_application_id") is None, (
        "forfeiture clears the booth's assigned_application_id"
    )


# ─── Payment deadline ───────────────────────────────────────────────────────

def test_pay_after_payment_window_rejected(api):
    """PRD §3.5: "Payment moves the assignment from `PENDING_PAYMENT` to `ACTIVE`
    and is guarded, in order, by the posture gate — the event must be in
    `SCHEDULING`, `LIVE`, or `WEATHER_HOLD` — by the payment window (the logical
    clock must be on or before `payment_due_at`; a later attempt is rejected with
    `ERR_PAYMENT_WINDOW_EXPIRED`), and by a fresh occupancy check on the booth
    (another assignment in `PENDING_PAYMENT` or `ACTIVE` on the same booth rejects
    the payment with `ERR_BOOTH_DOUBLE_BOOKED`)."
    PRD §2.5: "Advancing the clock is not inert: it triggers the sweep that forfeits
    any booth assignment whose payment deadline has passed, and it triggers the
    automatic close of the application window when the clock reaches the window's
    end."

    Design: Corner/validations/payment_window_expired
    """
    ctx = setup_approved_ctx()  # PENDING_PAYMENT; assigned at 2026-05-01, due +72h
    event_id = ctx["event"]["id"]
    # Advancing past the 72-hour deadline triggers the forfeit sweep; the late pay
    # is then rejected either by the payment-window rule or by the state gate.
    reset_clock("2026-05-05T00:00:00Z")
    res = api_client.pay_assignment(event_id, ctx["assignment"]["id"],
                                    make_vendor_headers(ctx["vendor"]["id"]))
    actual = validate_error_is_one_of(
        res, [ApiErrorId.ERR_PAYMENT_WINDOW_EXPIRED, ApiErrorId.ERR_INVALID_STATE]
    )
    assert actual in ("ERR_PAYMENT_WINDOW_EXPIRED", "ERR_INVALID_STATE")
