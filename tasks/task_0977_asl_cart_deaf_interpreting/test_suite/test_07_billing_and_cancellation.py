"""Billing: provisional estimate vs final invoice, pinned rounding order, capped
travel/mileage, billable floor, VRI platform fee, corrected times, the verification
gate, and the tiered cancellation fee."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_org_requester_headers,
    make_interpreter_headers,
    set_clock,
    create_org,
    create_vri_rate_card,
    create_vri_interpreter,
    create_submitted_vri_request,
    offer_to,
    accept_assignment,
    confirm_assignment,
    get_assignment,
    get_request,
    get_encounter_of,
    verify_encounter,
    setup_offered_assignment,
    setup_confirmed_assignment,
    setup_completed_encounter,
    setup_generated_invoice,
    drive_to_checkout,
    assert_invoice,
    assert_invoice_invariants,
    find_line,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ─── Difficulty: dual_variant_calc / billing estimate vs final ───────

def test_provisional_estimate_computed_at_offer_time():
    """PRD §3.4: "The scheduled duration in minutes — the gap between `scheduled_end`
    and `scheduled_start`, rounded up to a whole minute — is compared against
    `pinned_minimum_billable_minutes`, and the larger of the two is the estimated
    billable time. The labor estimate multiplies that billable time by
    `pinned_hourly_rate_cents` per hour and rounds half-up to whole cents. The travel
    estimate is zero for VRI and otherwise a flat sixty estimated travel minutes —
    exactly one hour at the pinned travel rate, rounded half-up. The mileage estimate
    is zero for VRI and otherwise multiplies the pinned per-mile rate by the lesser
    of the request's `estimated_mileage` and the 200-mile cap, rounded half-up."
    (150 scheduled minutes -> labor 22500 + travel 3000 + mileage 10 x 70 = 700.)

    Design: Difficulty/dual_variant_calc/billing_estimate_vs_final_diverge_on_actuals
    """
    ctx = setup_offered_assignment()
    assert ctx["assignment"]["estimated_cost_cents"] == 26200, (
        f"provisional variant must be 26200, got {ctx['assignment']['estimated_cost_cents']}"
    )


def test_final_invoice_diverges_from_provisional_estimate():
    """PRD §3.7: "The `LABOR` line is always present: its quantity is the encounter's
    `billable_minutes` and its amount is that time at the pinned hourly rate, rounded
    half-up. The `TRAVEL_TIME` and `MILEAGE` lines reimburse the check-out claims
    under their caps — travel time capped at 240 minutes and mileage at 200 miles,
    both forced to zero for VRI — each rounded half-up per line."
    (Actual 130 minutes -> LABOR 19500; claimed 90 travel minutes -> 4500; claimed
    12 miles -> 840; the final variant totals 24840, diverging from the 26200
    provisional estimate.)

    Design: Difficulty/dual_variant_calc/billing_estimate_vs_final_diverge_on_actuals
    """
    ctx = setup_generated_invoice()  # 130 actual min, claims 90 min / 12 mi
    invoice = ctx["invoice"]
    assert_invoice(invoice)
    assert_invoice_invariants(invoice)
    assert invoice["subtotal_cents"] == 24840
    labor = find_line(invoice, "LABOR")
    assert labor["quantity"] == 130 and labor["amount_cents"] == 19500
    asg = get_assignment(ctx["assignment"]["id"])
    assert asg["estimated_cost_cents"] == 26200
    assert invoice["subtotal_cents"] != asg["estimated_cost_cents"], (
        "the two valid variants disagree whenever actuals differ from the schedule"
    )


# ─── Difficulty: combinatorial_formula / rounding order ──────────────

def _rounding_ctx():
    """Full flow with hourly 8999 / mileage 65, 130 actual minutes, claims 90/10.5.
    Hourly 8999 and mileage 65 make the per-line rounding order visible:
    LABOR round(130 x 8999 / 60) = round(19497.8333) = 19498; TRAVEL 4500 exact;
    MILEAGE round(10.5 x 65) = round(682.5) = 683."""
    ctx = setup_confirmed_assignment(
        rate_card_overrides={"hourly_rate_cents": 8999,
                             "mileage_rate_cents_per_mile": 65},
    )
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 10.5})
    verify_encounter(ctx)
    ctx["invoice"] = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    return ctx


def test_invoice_line_rounding_per_line_values():
    """PRD §2.6: "Every computed cent amount is rounded half-up to a whole cent, and
    rounding is applied per component before any summation: each invoice line is
    rounded to integer cents first and the subtotal is the sum of those
    already-rounded line amounts, never a sum of unrounded amounts rounded once at
    the end."
    (LABOR round_half_up(19497.8333) = 19498; MILEAGE round_half_up(682.5) = 683;
    TRAVEL_TIME 4500.)

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
    """
    ctx = _rounding_ctx()
    invoice = ctx["invoice"]
    assert find_line(invoice, "LABOR")["amount_cents"] == 19498
    assert find_line(invoice, "MILEAGE")["amount_cents"] == 683
    assert find_line(invoice, "TRAVEL_TIME")["amount_cents"] == 4500
    assert invoice["subtotal_cents"] == 24681


def test_invoice_subtotal_is_not_sum_then_round():
    """PRD §2.6: "Sum-then-round of the same inputs can differ by cents; this
    platform pins round-per-line-then-sum." (Sum-then-round of
    19497.8333 + 4500 + 682.5 = 24680.3333 would produce 24680; the pinned order
    yields 24681 — exactly one cent apart.)

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
    """
    ctx = _rounding_ctx()
    invoice = ctx["invoice"]
    assert_invoice_invariants(invoice)
    assert invoice["subtotal_cents"] == 24681
    assert invoice["subtotal_cents"] != 24680, (
        "24680 is the sum-then-round answer the platform explicitly rejects"
    )


# ─── Difficulty: combinatorial_formula / nested-min caps ─────────────

def _setup_capped_claims_invoice():
    """Claims deliberately exceed both caps: travel 300 min (cap 240), mileage
    250 mi (cap 200)."""
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 300, "mileage_claimed": 250})
    verify_encounter(ctx)
    ctx["invoice"] = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    return ctx


def test_travel_and_mileage_lines_capped():
    """PRD §3.7: "The `TRAVEL_TIME` and `MILEAGE` lines reimburse the check-out
    claims under their caps — travel time capped at 240 minutes and mileage at 200
    miles, both forced to zero for VRI — each rounded half-up per line."
    (min(300, 240) = 240 min at 3000/h -> 12000; min(250, 200) = 200 mi at 70/mi
    -> 14000.)

    Design: Difficulty/combinatorial_formula/travel_and_mileage_caps_nested_min
    """
    invoice = _setup_capped_claims_invoice()["invoice"]
    travel = find_line(invoice, "TRAVEL_TIME")
    assert travel["quantity"] == 240 and travel["amount_cents"] == 12000
    mileage = find_line(invoice, "MILEAGE")
    assert mileage["quantity"] == 200 and mileage["amount_cents"] == 14000


def test_travel_and_mileage_caps_subtotal():
    """PRD §3.7: "The `subtotal_cents` is the sum of the per-line rounded amounts —
    round per line, then sum, per §2.6." (LABOR 19500 + capped TRAVEL_TIME 12000 +
    capped MILEAGE 14000 = 45500, not the uncapped 15000/17500 reading.)

    Design: Difficulty/combinatorial_formula/travel_and_mileage_caps_nested_min
    """
    invoice = _setup_capped_claims_invoice()["invoice"]
    assert invoice["subtotal_cents"] == 45500
    assert_invoice_invariants(invoice)


# ─── Corner calculations ─────────────────────────────────────────────

def test_billable_minutes_floor_at_minimum():
    """PRD §3.5: check-out "sets `billable_minutes` to the greater of
    `actual_minutes` and the assignment's `pinned_minimum_billable_minutes`".
    PRD §3.7: "The `LABOR` line is always present: its quantity is the encounter's
    `billable_minutes` and its amount is that time at the pinned hourly rate, rounded
    half-up." (A 45-minute encounter bills max(45, 120) = 120 minutes: 120 x
    9000/60 = 18000, not 45 x 150 = 6750.)

    Design: Corner/calculations/billable_minutes_floor_at_minimum
    """
    ctx = setup_confirmed_assignment(request_overrides={"estimated_mileage": 0})
    drive_to_checkout(ctx, check_out_time="2026-06-10T14:45:00Z")  # 45 minutes
    verify_encounter(ctx)
    enc = ctx["encounter"]
    assert enc["actual_minutes"] == 45
    assert enc["billable_minutes"] == 120, "the 120-minute minimum floors billing"
    invoice = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    assert invoice["subtotal_cents"] == 18000
    labor = find_line(invoice, "LABOR")
    assert labor["quantity"] == 120 and labor["amount_cents"] == 18000


def test_platform_fee_uses_actual_not_billable_minutes():
    """PRD §3.7: "The `PLATFORM_FEE` line exists only for VRI and is computed on the
    encounter's `actual_minutes` at the pinned per-minute fee — actual minutes, never
    the minimum-inflated billable figure." (A 20-minute VRI encounter bills LABOR at
    the 30-minute minimum: 30 x 4500/60 = 2250; PLATFORM_FEE is 20 x 15 = 300, not
    30 x 15 = 450; subtotal 2550.)

    Design: Corner/calculations/platform_fee_uses_actual_not_billable_minutes
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="State Univ", org_type="EDUCATION")
    create_vri_rate_card()
    interp = create_vri_interpreter()
    req = create_submitted_vri_request(org["id"])
    asg = offer_to(req["id"], interp["id"])
    accept_assignment(asg)
    confirm_assignment(asg)
    set_clock("2026-06-15T10:00:00Z")
    get_success_data(api_client.check_in_assignment(
        asg["id"], make_interpreter_headers(interp["id"])))
    set_clock("2026-06-15T10:20:00Z")
    get_success_data(api_client.check_out_assignment(
        asg["id"], {}, make_interpreter_headers(interp["id"])))
    enc = get_encounter_of(asg["id"])
    assert enc["actual_minutes"] == 20 and enc["billable_minutes"] == 30
    get_success_data(api_client.verify_encounter(
        enc["id"], {}, make_org_requester_headers(org["id"])))
    invoice = get_success_data(api_client.generate_invoice(
        {"assignment_id": asg["id"]}, CLERK))
    labor = find_line(invoice, "LABOR")
    assert labor["quantity"] == 30 and labor["amount_cents"] == 2250
    fee = find_line(invoice, "PLATFORM_FEE")
    assert fee["quantity"] == 20 and fee["amount_cents"] == 300, (
        "PLATFORM_FEE multiplies ACTUAL minutes, not the minimum-inflated billable"
    )
    assert invoice["subtotal_cents"] == 2550


def test_verify_with_corrected_times_recomputes_billable():
    """PRD §3.7: "The requester may attach corrected times — a `corrected_start`
    strictly before the `corrected_end`, with the corrected end not in the future —
    in which case `actual_minutes` and `billable_minutes` are recomputed from the
    corrections under the same rounding and minimum-minute rules as check-out."
    (Correcting 14:00-16:10 to 14:05-16:05 gives 120 actual minutes; billable stays
    max(120, 120) = 120; invoice 18000 + 4500 + 840 = 23340 instead of 24840.)

    Design: Corner/endpoints/verify_with_corrected_times_recomputes_billable
    """
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    set_clock("2026-06-10T16:30:00Z")
    enc = get_success_data(api_client.verify_encounter(
        ctx["encounter"]["id"],
        {"corrected_start": "2026-06-10T14:05:00Z",
         "corrected_end": "2026-06-10T16:05:00Z"},
        make_org_requester_headers(ctx["org"]["id"]),
    ))
    assert enc["actual_minutes"] == 120, "recomputed from the corrected times"
    assert enc["billable_minutes"] == 120
    invoice = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    assert invoice["subtotal_cents"] == 23340
    assert find_line(invoice, "LABOR")["amount_cents"] == 18000
    assert find_line(invoice, "TRAVEL_TIME")["amount_cents"] == 4500
    assert find_line(invoice, "MILEAGE")["amount_cents"] == 840


def test_org_requester_cannot_verify_other_orgs_encounter():
    """PRD §2.1: "When `X-User-Role` is `OrgRequester`, `X-User-ID` is the `id` of
    the acting RequestingOrg; ownership checks on any resource that references a
    RequestingOrg compare the resource's foreign-key field (for example `org_id` on
    a request, complaint, or credit memo, or the owning organization reached through
    an assignment, encounter, or invoice) to `X-User-ID`, and a mismatch is rejected
    with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD §3.7: "The owning `OrgRequester` verifies a live encounter".

    Design: Corner/rbac/org_requester_cannot_verify_other_orgs_encounter
    """
    ctx = setup_completed_encounter()  # org1's encounter, unverified
    other_org = create_org(name="Other Org", org_type="GENERAL")
    resp = api_client.verify_encounter(
        ctx["encounter"]["id"], {}, make_org_requester_headers(other_org["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    enc = get_encounter_of(ctx["assignment"]["id"])
    assert enc["verified"] is False, "a foreign-org verify must not take effect"


# ─── Difficulty: cross_entity_state_dependency / verification gate ───

def _setup_unverified_completed_encounter():
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    return ctx


def test_generate_blocked_until_encounter_verified():
    """PRD §3.7: "Generation requires the assignment to be `COMPLETED` (otherwise
    `ERR_INVALID_REQUEST`) and its encounter verified (otherwise
    `ERR_ENCOUNTER_NOT_VERIFIED`)".
    PRD §3.5: "The request deliberately remains `IN_PROGRESS` — it cannot complete
    until the encounter is verified."

    Design: Difficulty/cross_entity_state_dependency/encounter_verification_gates_request_completion_and_invoice
    """
    ctx = _setup_unverified_completed_encounter()
    assert ctx["assignment"]["status"] == "COMPLETED"
    resp = api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_VERIFIED)
    assert get_request(ctx["request"]["id"])["status"] == "IN_PROGRESS", (
        "assignment COMPLETED alone does not complete the request"
    )


def test_verification_unblocks_completion_and_billing():
    """PRD §3.7: "Verification bubbles the request from `IN_PROGRESS` to
    `COMPLETED`." and "Either way, the request cannot reach `COMPLETED` — and the
    encounter cannot be billed — until verification has happened."

    Design: Difficulty/cross_entity_state_dependency/encounter_verification_gates_request_completion_and_invoice
    """
    ctx = _setup_unverified_completed_encounter()
    verify_encounter(ctx)
    assert get_request(ctx["request"]["id"])["status"] == "COMPLETED"
    invoice = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    assert invoice["issue_status"] == "DRAFT"
    assert invoice["subtotal_cents"] == 24840


# ─── Difficulty: boundary_precision_check / cancellation fee ─────────

def _setup_confirmed_then_cancel_at(clock_time: str):
    """CONFIRMED assignment for the standard June-10 14:00 booking; the logical
    clock parked at `clock_time`; then the requester cancels the assignment."""
    ctx = setup_confirmed_assignment()
    set_clock(clock_time)
    cancelled = get_success_data(api_client.cancel_assignment(
        ctx["assignment"]["id"], make_org_requester_headers(ctx["org"]["id"])))
    ctx["assignment"] = cancelled
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx


def test_cancellation_fee_exactly_48h_notice_is_zero():
    """PRD §3.6: "Notice of at least `pinned_cancel_full_refund_notice_hours` — the
    boundary is inclusive — means a fee of zero." and "Notice is measured in exact
    seconds between the cancellation moment and the `scheduled_start`; the
    assignment records it in hours as `cancel_notice_hours`, and the actor is
    recorded in `cancelled_by`".
    (Exactly 48.000h of notice on a card with a 48h full-refund window.)

    Design: Difficulty/boundary_precision_check/cancellation_fee_exactly_48h_notice_is_zero
    """
    ctx = _setup_confirmed_then_cancel_at("2026-06-08T14:00:00Z")
    asg = ctx["assignment"]
    assert asg["status"] == "CANCELLED"
    assert asg["cancelled_by"] == "REQUESTER"
    assert asg["cancel_notice_hours"] == 48.0
    assert asg["cancellation_fee_cents"] == 0, "48h notice is inside the free window"


def test_cancellation_fee_zero_creates_no_fee_invoice():
    """PRD §3.6: "Cancelling a `CONFIRMED` request cancels its `CONFIRMED` or
    `EN_ROUTE` assignment with the tiered fee, and when that fee is greater than
    zero the platform creates a fee-only invoice in `DRAFT` whose single line is
    the fee and whose `encounter_id` is null." (Fee zero -> no invoice.)
    PRD §3.6: "Cancelling an assignment directly, a requester-side cancellation
    additionally cancels the request on the same terms".

    Design: Difficulty/boundary_precision_check/cancellation_fee_exactly_48h_notice_is_zero
    """
    ctx = _setup_confirmed_then_cancel_at("2026-06-08T14:00:00Z")
    rows = get_success_data(api_client.list_assignment_invoices(
        ctx["assignment"]["id"], ADMIN))
    assert rows == [], "a zero fee creates no fee-only invoice"
    req = ctx["request"]
    assert req["status"] == "CANCELLED"
    assert req["cancellation_fee_cents"] == 0


def test_cancellation_fee_exactly_24h_notice_partial_tier():
    """PRD §3.6: "Notice shorter than that but at least
    `pinned_cancel_partial_notice_hours` yields a fee of `pinned_late_cancel_fee_pct`
    times the minimum charge, rounded half-up." and "when that fee is greater than
    zero the platform creates a fee-only invoice in `DRAFT` whose single line is the
    fee and whose `encounter_id` is null."
    PRD §3.7: "A cancellation-fee-only invoice carries a single `CANCELLATION_FEE`
    line equal to the assignment's `cancellation_fee_cents`."
    (Exactly 24h notice -> round_half_up(0.5 x 18000) = 9000.)

    Design: Corner/calculations/cancellation_fee_exactly_24h_notice_partial_tier
    """
    ctx = setup_confirmed_assignment(request_overrides={
        "scheduled_start": "2026-06-15T14:00:00Z",
        "scheduled_end": "2026-06-15T15:00:00Z",
        "estimated_mileage": 5,
    })
    set_clock("2026-06-14T14:00:00Z")  # exactly 24h before the start
    cancelled = get_success_data(api_client.cancel_assignment(
        ctx["assignment"]["id"],
        make_org_requester_headers(ctx["org"]["id"]),
        {"reason": "Patient discharged"}))
    assert cancelled["cancel_notice_hours"] == 24.0
    assert cancelled["cancellation_fee_cents"] == 9000, (
        "24h notice sits in the partial tier: 0.5 x 18000 minimum charge"
    )
    req = get_request(ctx["request"]["id"])
    assert req["status"] == "CANCELLED"
    assert req["cancellation_fee_cents"] == 9000
    rows = get_success_data(api_client.list_assignment_invoices(
        ctx["assignment"]["id"], ADMIN))
    assert len(rows) == 1, "a positive fee materializes one fee-only invoice"
    fee_invoice = rows[0]
    assert fee_invoice["issue_status"] == "DRAFT"
    assert fee_invoice["encounter_id"] is None
    assert len(fee_invoice["line_items"]) == 1
    line = fee_invoice["line_items"][0]
    assert line["kind"] == "CANCELLATION_FEE" and line["amount_cents"] == 9000
    assert fee_invoice["subtotal_cents"] == 9000
