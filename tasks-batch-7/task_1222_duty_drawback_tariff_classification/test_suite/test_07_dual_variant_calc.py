"""The two dual-variant calculations: the provisional-vs-final claim duty
valuation, and the accrued-vs-settled contingency fee."""
from test_helpers import ApiErrorId, add_certified_classification, add_claim, add_claim_line, add_export_shipment, add_import_entry, file_claim, onboard_client, record_payment, setup_approved_claim, TEST_USERS, get_invoice_for_claim, validate_error, validate_success

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _setup_provisional_vs_final():
    """Two byte-identical DIRECT claims on twin entries/exports; claim A is
    filed (claimed frozen), claim B stays DRAFT (estimate live)."""
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    entry_a = add_import_entry(client["id"], cls["id"], entry_number="E100")
    entry_b = add_import_entry(client["id"], cls["id"], entry_number="E200")
    export_a = add_export_shipment(client["id"], export_date="2026-04-01T00:00:00Z")
    export_b = add_export_shipment(client["id"], export_date="2026-04-02T00:00:00Z")
    claim_a = add_claim(
        client["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-03-31T00:00:00Z"
    )
    claim_b = add_claim(
        client["id"], period_start="2026-04-01T00:00:00Z", period_end="2026-06-30T00:00:00Z"
    )
    add_claim_line(claim_a["id"], entry_a["id"], export_a["id"], matched_quantity=40)
    line_b = add_claim_line(claim_b["id"], entry_b["id"], export_b["id"], matched_quantity=40)
    file_claim(claim_a["id"])
    return {
        "client": client,
        "classification": cls,
        "entry_a": entry_a,
        "entry_b": entry_b,
        "export_a": export_a,
        "export_b": export_b,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "line_b": line_b,
    }


def test_filed_claim_figure_survives_a_correction_to_its_twin_draft_claims_entry(api):
    """PRD 3.4: "On filing, the claim transitions `DRAFT → FILED`, `filed_at`
    and `filed_by_user_id` are stamped, and `claimed_duty_cents` is frozen as the
    sum of the then-current per-line `drawback_amount_cents` values."
    PRD 3.6: "Lines under filed claims are untouched by design: a filed claim's
    frozen `claimed_duty_cents` never moves."

    Design: Difficulty/dual_variant_calc/claim_estimate_provisional_vs_frozen_final
    """
    ctx = _setup_provisional_vs_final()

    entry_b = validate_success(
        api.get_import_entry(ctx["entry_b"]["id"], ANALYST)
    )
    validate_success(
        api.correct_import_entry(
            ctx["entry_b"]["id"],
            {"duty_paid_cents": 41250,
             "expected_import_entry_version": entry_b["version"]},
            ANALYST,
        )
    )

    claim_a = validate_success(api.get_claim(ctx["claim_a"]["id"], ANALYST))
    claim_b = validate_success(api.get_claim(ctx["claim_b"]["id"], ANALYST))
    assert claim_a["claimed_duty_cents"] == 32670, (
        f"frozen FINAL figure must not move; got {claim_a['claimed_duty_cents']}"
    )
    assert claim_b["estimate_cents"] == 16335, (
        f"PROVISIONAL estimate recomputes live: 0.99 * (41250/100) * 40 = 16335; "
        f"got {claim_b['estimate_cents']}"
    )

    entry_b_after = validate_success(api.get_import_entry(ctx["entry_b"]["id"], ANALYST))
    assert entry_b_after["drawback_eligible_duty_cents"] == 41250
    assert entry_b_after["unclaimed_duty_cents"] == 24915

    lines = validate_success(
        api.list_claim_lines(ANALYST, params={"claim_id": ctx["claim_b"]["id"]})
    )
    assert lines[0]["drawback_amount_cents"] == 16335


def test_provisional_estimate_moves_with_entry_correction_while_final_stays_frozen(api):
    """PRD 3.4: "While the claim is in `DRAFT`, its `estimate_cents` is a
    provisional figure: every line addition, line void, or correction to a
    referenced entry re-evaluates every `ACTIVE` line's refund formula live
    against the entry's current eligible-duty fields and re-sums the claim
    total."
    PRD 3.4: "From `FILED` onward the estimate is never recomputed and entry
    corrections against the claim's entries are locked per §2.9."

    Design: Difficulty/dual_variant_calc/claim_estimate_provisional_vs_frozen_final
    """
    ctx = _setup_provisional_vs_final()

    # Snapshot the draft claim's estimate before the correction.
    claim_b_before = validate_success(api.get_claim(ctx["claim_b"]["id"], ANALYST))
    assert claim_b_before["estimate_cents"] == 32670

    entry_b = validate_success(api.get_import_entry(ctx["entry_b"]["id"], ANALYST))
    validate_success(
        api.correct_import_entry(
            ctx["entry_b"]["id"],
            {"duty_paid_cents": 41250,
             "expected_import_entry_version": entry_b["version"]},
            ANALYST,
        )
    )

    claim_b_after = validate_success(api.get_claim(ctx["claim_b"]["id"], ANALYST))
    assert claim_b_after["estimate_cents"] == 16335, (
        "the draft claim's estimate must track the corrected entry"
    )
    assert claim_b_after["estimate_cents"] != claim_b_before["estimate_cents"]

    # The filed twin is locked: a correction attempt against ITS entry is refused.
    entry_a = validate_success(api.get_import_entry(ctx["entry_a"]["id"], ANALYST))
    res = api.correct_import_entry(
        ctx["entry_a"]["id"],
        {"duty_paid_cents": 41250,
         "expected_import_entry_version": entry_a["version"]},
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_ENTRY_LOCKED_BY_FILED_CLAIM)
    claim_a = validate_success(api.get_claim(ctx["claim_a"]["id"], ANALYST))
    assert claim_a["claimed_duty_cents"] == 32670


def test_accrued_fee_applies_the_realization_haircut_before_tiering(api):
    """PRD 3.7: "The accrued variant drives the client's
    `projected_fee_accrual_cents` while claims sit in `APPROVED`: the recovered
    amount for each such claim is its `approved_duty_cents` multiplied by 8000
    basis points and divided by 10000 — the 80% realization haircut reflecting
    that approved amounts are not yet cash — rounded half up, and the rate is
    the client's current `contingency_fee_bps`."
    PRD 3.1: "Because of the haircut, an identical approved-and-paid amount
    yields a lower accrual than the settled fee eventually invoiced."

    Design: Difficulty/dual_variant_calc/invoice_fee_accrued_vs_settled
    """
    ctx = setup_approved_claim(approved_duty_cents=32670)

    client = validate_success(api.get_client(ctx["client"]["id"], ADMIN))
    # fee(round_half_up(32670 * 8000/10000)) = fee(26136) = round_half_up(26136*0.25) = 6534
    assert client["projected_fee_accrual_cents"] == 6534, (
        f"ACCRUED variant must apply the 80% haircut first; got "
        f"{client['projected_fee_accrual_cents']}"
    )
    assert client["lifetime_recovered_cents"] == 0


def test_settled_fee_tiers_the_full_paid_amount_and_drains_the_accrual(api):
    """PRD 3.7: "The settled variant fires once, at invoice creation on claim
    payment: the recovered amount is the claim's `paid_duty_cents` and the rate
    is the invoice's `fee_bps_snapshot`."
    PRD 3.5: "Third, the client's aggregates move: `lifetime_recovered_cents`
    grows by `paid_duty_cents`, `projected_fee_accrual_cents` is recomputed
    because the claim has left the `APPROVED` accrual set, and the client's
    `version` increments."

    Design: Difficulty/dual_variant_calc/invoice_fee_accrued_vs_settled
    """
    ctx = setup_approved_claim(approved_duty_cents=32670)

    accrual_at_approved = validate_success(api.get_client(ctx["client"]["id"], ADMIN))[
        "projected_fee_accrual_cents"
    ]
    assert accrual_at_approved == 6534

    record_payment(ctx["claim"]["id"], 32670)
    invoice = get_invoice_for_claim(ctx["claim"]["id"])
    # round_half_up(32670 * 2500/10000) = round_half_up(8167.5) = 8168
    assert invoice["fee_cents"] == 8168, (
        f"SETTLED variant tiers the full paid amount (no haircut); got {invoice['fee_cents']}"
    )
    assert invoice["fee_cents"] > accrual_at_approved, (
        "identical approved == paid must yield a lower accrual than the settled fee"
    )

    client = validate_success(api.get_client(ctx["client"]["id"], ADMIN))
    assert client["projected_fee_accrual_cents"] == 0
    assert client["lifetime_recovered_cents"] == 32670
