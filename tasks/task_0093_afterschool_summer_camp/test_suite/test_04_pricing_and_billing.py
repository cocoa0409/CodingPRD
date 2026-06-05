"""Tuition pricing, scholarships, the household sibling discount, invoice totals, and billing.

Covers difficulty combinatorial-formula and dual-variant instances (line tuition rounding
order, sibling-discount evaluation order, provisional-vs-final divergence), the
transitive-cascade and compensating-invariant scholarship instances, and the corner
calculation / validation / billing instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_payment_payload,
    create_enrollment_payload,
    finalize_invoice_payload,
    make_guardian_headers,
    assert_payment,
    assert_invoice_total_floor,
    # fixtures
    create_guardian,
    setup_eligible_child,
    setup_open_session_with_offering,
    setup_confirmed_enrollment,
    setup_finalized_invoice,
    get_offering,
    get_invoice,
    get_enrollment,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ---------------------------------------------------------------------------
# Line tuition: scale-then-round-then-add surcharge (difficulty combinatorial)
# ---------------------------------------------------------------------------
def test_line_tuition_rounds_before_adding_camp_surcharge(api):
    """PRD §3.6: "multiply the base by one minus the child's approved_discount_pct ..., and
    round that scaled amount to whole cents using round-half-up. Then, and only then, add
    the program-type surcharge: a CAMP program adds a flat materials surcharge of 1,500
    cents per enrolled week on top of the scholarship-reduced amount ... The rounding order
    is pinned: scale by the discount and round first, then add the surcharge — never the
    reverse." (base 19999, PARTIAL 0.5 -> round_half_up(9999.5)=10000, +1500 = 11500.)

    Design: Difficulty/combinatorial_formula/line_tuition_scale_then_round_then_add_surcharge
    """
    eligible = setup_eligible_child(with_scholarship_tier="PARTIAL", approve_scholarship=True)
    gid = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Odd Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 19999},
    )
    e = enroll_child(gid, eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"])
    assert e["status"] == "CONFIRMED", f"expected CONFIRMED, got {e['status']}"
    assert e["provisional_tuition_cents"] == 11500, (
        f"round_half_up(19999*0.5)=10000 + 1500 surcharge = 11500, got {e['provisional_tuition_cents']}"
    )


def test_full_scholarship_zeros_base_but_keeps_camp_surcharge(api):
    """PRD §3.6: "FULL maps to 1.0 (the full base waived)." and "a CAMP program adds a flat
    materials surcharge of 1,500 cents per enrolled week on top of the scholarship-reduced
    amount". (round_half_up(20000*0)=0, +1500 = 1500.)

    Design: Corner/calculations/full_scholarship_zeroes_tuition_keeps_camp_surcharge
    """
    eligible = setup_eligible_child(with_scholarship_tier="FULL", approve_scholarship=True)
    gid = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Full Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
    )
    e = enroll_child(gid, eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"])
    assert e["provisional_tuition_cents"] == 1500, (
        f"FULL scholarship zeros base, CAMP surcharge 1500 remains, got {e['provisional_tuition_cents']}"
    )


# ---------------------------------------------------------------------------
# Sibling discount: sum-then-round evaluation order (difficulty combinatorial)
# ---------------------------------------------------------------------------
def test_sibling_discount_sum_then_round_two_children(api):
    """PRD §3.6: "identify the anchor child — the one whose single most expensive
    provisional line is the largest of all the children's ... — and exclude that anchor;
    every other distinct child is eligible. For each eligible child, take that child's
    single highest provisional_tuition_cents line on this invoice. Sum those per-child
    highest lines across all eligible children, multiply the sum by the sibling discount
    rate of 0.10 (ten percent), and round the single summed product half-up to whole cents".
    PRD §3.6: "total_due_cents is the subtotal minus sibling_discount_cents, floored at 0."
    (Lines 21500 (anchor) and 11500 (eligible): round_half_up(0.10*11500)=1150; subtotal
    33000; total 31850.)

    Design: Difficulty/combinatorial_formula/sibling_discount_sum_then_round_evaluation_order
    """
    guardian = create_guardian()
    gid = guardian["id"]
    # Two distinct children of the one guardian, both fully eligible, no scholarships.
    child_a = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Anchor", "birth_date": "2016-01-01"}
    )["child"]
    child_b = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Sib", "birth_date": "2016-02-01"}
    )["child"]
    # Two CAMP sessions in one program: expensive (base 20000 -> line 21500) and cheap (10000 -> 11500).
    program = api_client.create_program(
        create_program_payload(name="Sib Camp", program_type="CAMP"), DIRECTOR
    ).json()["data"]
    s_exp = api_client.create_session(
        create_session_payload(program["id"], title="Expensive", base_weekly_tuition_cents=20000), DIRECTOR
    ).json()["data"]
    s_cheap = api_client.create_session(
        create_session_payload(program["id"], title="Cheap", base_weekly_tuition_cents=10000), DIRECTOR
    ).json()["data"]
    # Both offerings share the same week_start: PRD §3.7 keys the draft invoice on the
    # guardian + the offering's billing period (a year-and-week tag), and PRD §3.6 computes
    # the sibling discount over the CONFIRMED lines of a SINGLE draft invoice — so the two
    # siblings must enroll in the same billing week to share one invoice. The week-overlap
    # check (PRD §3.4) is per-child, so two distinct children in the same week do not clash.
    wo_exp = api_client.create_weekly_offering({"session_id": s_exp["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    wo_cheap = api_client.create_weekly_offering({"session_id": s_cheap["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(s_exp["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(s_cheap["id"], DIRECTOR), 200)
    # Child A on expensive week (anchor line 21500).
    ea = enroll_child(gid, child_a["id"], wo_exp["id"], get_offering(wo_exp["id"])["version"])
    invoice_id = ea["invoice_id"]
    # Child B on cheap week (eligible sibling line 11500), same guardian + same period -> same invoice.
    enroll_child(gid, child_b["id"], wo_cheap["id"], get_offering(wo_cheap["id"])["version"])
    inv = get_invoice(invoice_id)
    assert inv["subtotal_cents"] == 33000, f"expected subtotal 33000, got {inv['subtotal_cents']}"
    assert inv["sibling_discount_cents"] == 1150, f"expected sibling discount 1150, got {inv['sibling_discount_cents']}"
    assert inv["total_due_cents"] == 31850, f"expected total 31850, got {inv['total_due_cents']}"
    assert_invoice_total_floor(inv)


def test_single_child_invoice_has_no_sibling_discount(api):
    """PRD §3.6: "Count the distinct children among those confirmed lines: if fewer than
    two distinct children appear, sibling_discount_cents is 0."
    PRD §3.6: "total_due_cents is the subtotal minus sibling_discount_cents, floored at 0."

    Design: Corner/calculations/single_child_no_sibling_discount
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Solo Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    inv = get_invoice(scene["invoice_id"])
    assert inv["sibling_discount_cents"] == 0, f"single child must have 0 sibling discount, got {inv['sibling_discount_cents']}"
    assert inv["subtotal_cents"] == 15000, f"expected subtotal 15000, got {inv['subtotal_cents']}"
    assert inv["total_due_cents"] == 15000, f"expected total 15000, got {inv['total_due_cents']}"


# ---------------------------------------------------------------------------
# Provisional vs final divergence on scholarship revoke then finalize (difficulty dual-variant)
# ---------------------------------------------------------------------------
def test_provisional_and_final_after_scholarship_revoke_then_finalize(api):
    """PRD §3.6: "Revoking an approved award ... a compensating re-price restores each DRAFT
    invoice line for the child to its undiscounted provisional_tuition_cents".
    PRD §3.6: "The final variant snapshots the discount at the moment the invoice is
    finalized, writes it to final_tuition_cents, and freezes it, so subsequent scholarship
    changes no longer move it." (CAMP base 20000, scholarship revoked before finalize, so
    both provisional and final reflect the undiscounted line 21500.)

    Design: Difficulty/dual_variant_calc/tuition_provisional_vs_final_on_enrollment
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Summer Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="PARTIAL",
        approve_scholarship=True,
    )
    gid = scene["guardian"]["id"]
    invoice_id = scene["invoice_id"]
    # Revoke the scholarship (re-prices line back to undiscounted 21500).
    validate_success(api.revoke_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    inv = get_invoice(invoice_id)
    validate_success(api.finalize_invoice(invoice_id, finalize_invoice_payload(inv["version"]), BILLING), 200)
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["final_tuition_cents"] == 21500, f"final tuition expected 21500, got {e['final_tuition_cents']}"
    assert e["provisional_tuition_cents"] == 21500, f"provisional tuition expected 21500, got {e['provisional_tuition_cents']}"
    inv2 = get_invoice(invoice_id)
    assert inv2["subtotal_cents"] == 21500, f"finalized subtotal expected 21500, got {inv2['subtotal_cents']}"


# ---------------------------------------------------------------------------
# Scholarship approve depth-3 reprice to total_due (difficulty transitive cascade)
# ---------------------------------------------------------------------------
def test_scholarship_approval_repricing_lowers_subtotal_and_total(api):
    """PRD §3.6: "Approving an award ... triggers a three-link cascade for the awarded
    child: first, every DRAFT invoice that holds a CONFIRMED enrollment for that child
    re-runs the provisional line price on those lines with the newly locked discount;
    second, each touched line's new provisional_tuition_cents feeds the invoice's subtotal,
    lowering subtotal_cents; third, the invoice re-derives total_due_cents from the new
    subtotal and the current sibling discount." (CAMP base 20000; PARTIAL approval ->
    round_half_up(20000*0.5)=10000 +1500 = 11500.)

    Design: Difficulty/transitive_cascade/scholarship_approve_depth3_reprice_to_total_due
    """
    # CONFIRMED first (line 21500), scholarship REQUESTED but NOT yet approved.
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Sch Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="PARTIAL",
        approve_scholarship=False,
    )
    invoice_id = scene["invoice_id"]
    validate_success(api.approve_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["provisional_tuition_cents"] == 11500, f"reprice expected 11500, got {e['provisional_tuition_cents']}"
    inv = get_invoice(invoice_id)
    assert inv["subtotal_cents"] == 11500, f"subtotal after reprice expected 11500, got {inv['subtotal_cents']}"
    assert inv["total_due_cents"] == 11500, f"total after reprice expected 11500, got {inv['total_due_cents']}"


# ---------------------------------------------------------------------------
# Scholarship revoke restores subtotal (difficulty compensating invariant)
# ---------------------------------------------------------------------------
def test_scholarship_approve_then_revoke_restores_subtotal(api):
    """PRD §3.6: "on revocation the award goes to REVOKED, approved_discount_pct resets to
    0, and a compensating re-price restores each DRAFT invoice line for the child to its
    undiscounted provisional_tuition_cents, after which each touched invoice re-runs its
    totals — so revoking an approval returns the books exactly to where they would have
    stood without it." (CAMP base 20000: 21500 -> 11500 on approve -> 21500 on revoke.)

    Design: Difficulty/compensating_invariant/scholarship_revoke_restores_invoice_subtotal
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Comp Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="PARTIAL",
        approve_scholarship=False,
    )
    invoice_id = scene["invoice_id"]
    # Approve then revoke.
    validate_success(api.approve_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    validate_success(api.revoke_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    inv = get_invoice(invoice_id)
    assert inv["subtotal_cents"] == 21500, f"subtotal must return to 21500 after revoke, got {inv['subtotal_cents']}"
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["provisional_tuition_cents"] == 21500, (
        f"provisional must be restored to 21500 after revoke, got {e['provisional_tuition_cents']}"
    )


# ---------------------------------------------------------------------------
# Billing: payment immutability, overpayment, withdraw-billed, empty finalize
# ---------------------------------------------------------------------------
def test_payment_is_immutable_record(api):
    """PRD §2.4: "a Payment, a WeatherEvent, and an AuditEntry are immutable once written,
    so each carries only an id and a created_at — they have neither an updated_at nor a
    version field, and nothing in the system mutates them after creation."
    PRD §3.7: "A BillingAdmin records Payments against a finalized invoice, each carrying
    the invoice_id, an amount_cents of at least 1, and a method of CARD, ACH, or WALLET."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    scene = setup_finalized_invoice(session_overrides={"base_weekly_tuition_cents": 15000})
    invoice_id = scene["invoice"]["id"]
    resp = api.create_payment(create_payment_payload(invoice_id, 15000, method="CARD"), BILLING)
    data = validate_success(resp, 201)
    assert_payment(data)
    assert data["amount_cents"] == 15000, f"expected payment amount 15000, got {data['amount_cents']}"


def test_payment_exceeding_balance_rejected(api):
    """PRD §3.7: "A payment may not exceed the invoice's outstanding balance — the
    total_due_cents minus the amount_paid_cents already recorded — and an overpayment is
    rejected with ERR_OVERPAYMENT." (total_due 15000, payment 16000.)

    Design: Corner/validations/overpayment_rejected
    """
    scene = setup_finalized_invoice(
        program_overrides={"name": "Op Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    invoice_id = scene["invoice"]["id"]
    resp = api.create_payment(create_payment_payload(invoice_id, 16000, method="CARD"), BILLING)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_withdraw_billed_enrollment_rejected(api):
    """PRD §3.4: "A CONFIRMED enrollment can be withdrawn only while its invoice is still
    DRAFT; an attempt to withdraw a seat whose invoice has already been billed is rejected
    with ERR_ENROLLMENT_BILLED."

    Design: Corner/validations/withdraw_billed_enrollment_rejected
    """
    scene = setup_finalized_invoice(
        program_overrides={"name": "Wb Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    gid = scene["guardian"]["id"]
    gh = make_guardian_headers(gid)
    resp = api.withdraw_enrollment(scene["enrollment"]["id"], gh)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_BILLED.value)


def test_finalize_invoice_with_zero_confirmed_lines_rejected(api):
    """PRD §3.7: "A BillingAdmin finalizes a draft invoice, advancing it DRAFT -> FINALIZED,
    but only when it holds at least one CONFIRMED enrollment line; a finalize with zero
    confirmed lines is rejected with ERR_NO_CONFIRMED_LINES".

    Design: Difficulty/boundary_precision_check/empty_invoice_finalize_zero_confirmed_lines
    """
    # One CONFIRMED enrollment creates a DRAFT invoice, then withdraw it -> zero confirmed lines.
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Empty Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
    )
    gid = scene["guardian"]["id"]
    gh = make_guardian_headers(gid)
    invoice_id = scene["invoice_id"]
    validate_success(api.withdraw_enrollment(scene["enrollment"]["id"], gh), 200)
    inv = get_invoice(invoice_id)
    resp = api.finalize_invoice(invoice_id, finalize_invoice_payload(inv["version"]), BILLING)
    validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_LINES.value)
