"""The fraud-hold cycle, the ladder position of the claim state check, and the
divergence between the two fraud-score variants."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_claim_payload,
    assert_reserve_ledger,
    clear_hold,
    create_claim,
    create_claimant,
    create_program,
    create_sku,
    deny_payload,
    hold_claim,
    make_brand_protection_analyst_headers,
    make_warranty_administrator_headers,
    read_claim,
    read_claimant,
    read_program,
    read_sku,
    set_clock,
    setup_warranty_scenario,
    validate_error,
    validate_success,
)

WA_1 = make_warranty_administrator_headers("wa-1")
WA_2 = make_warranty_administrator_headers("wa-2")
BP_1 = make_brand_protection_analyst_headers("bp-1")

HANDLE_LINE = {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1}

BRANDED_PLIER = {
    "sku_code": "PL-10-BR",
    "tool_family": "PLIER",
    "channel": "BRANDED",
    "nominal_size_mm": 10,
    "alloy_grade": "S2",
    "list_price_cents": 2400,
    "warranty_tier": "LIFETIME",
}


# ---------------------------------------------------------------------------
# SUBMITTED -> FRAUD_HOLD -> SUBMITTED -> FRAUD_HOLD -> DENIED_FRAUD
# ---------------------------------------------------------------------------


def _submitted_claim_with_one_line():
    return setup_warranty_scenario(lines=(HANDLE_LINE,))


def test_a_hold_records_the_acting_administrator_and_raises_the_open_hold_count():
    """wa-1 places the hold, so wa-1 is stamped onto the claim and the programme
    counts one open hold.

    PRD §3.8: "The hold moves the claim `SUBMITTED → FRAUD_HOLD`, stores the
    supplied `hold_reason`, and records the acting `X-User-ID` in
    `held_by_user_id`."

    Design: Difficulty/non_linear_state_machine/claim_fraud_hold_cycle_back_to_submitted
    """
    ctx = _submitted_claim_with_one_line()
    assert ctx["claim"]["status"] == "SUBMITTED"

    held = hold_claim(ctx["claim"]["id"], WA_1, hold_reason="SERIAL_PATTERN_REVIEW")

    assert held["status"] == "FRAUD_HOLD"
    assert held["hold_reason"] == "SERIAL_PATTERN_REVIEW"
    assert held["held_by_user_id"] == "wa-1"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 1


def test_clearing_a_hold_returns_the_claim_but_retains_the_holder():
    """A different administrator clears the hold; the claim goes back to the
    queue flagged as cleared, yet the original holder stays on the row so the
    duty separation still binds at approval time.

    PRD §3.8: "Clearing moves the claim `FRAUD_HOLD → SUBMITTED`, sets
    `fraud_cleared` to true, and clears `hold_reason` to null — but **retains**
    `held_by_user_id`, because the duty separation must still bind at approval
    time."

    Design: Difficulty/non_linear_state_machine/claim_fraud_hold_cycle_back_to_submitted
    """
    ctx = _submitted_claim_with_one_line()
    hold_claim(ctx["claim"]["id"], WA_1, hold_reason="SERIAL_PATTERN_REVIEW")

    cleared = clear_hold(ctx["claim"]["id"], WA_2, clearance_note="Independent review complete")

    assert cleared["status"] == "SUBMITTED"
    assert cleared["fraud_cleared"] is True
    assert cleared["hold_reason"] is None
    assert cleared["held_by_user_id"] == "wa-1"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 0


def test_the_hold_cycle_is_repeatable_and_a_fraud_denial_closes_it():
    """A second hold, this time by an analyst, replaces the recorded holder; the
    fraud denial then takes the claim to its own terminal state and drops the
    hold from the queue.

    PRD §3.8: "Fraud denial applies to a `FRAUD_HOLD` claim, records the supplied
    `denial_code`, moves the claim `FRAUD_HOLD → DENIED_FRAUD` so that fraud
    outcomes stay separately auditable, recomputes the claimant's
    `fraud_risk_score_adjudication`, increments the claim's `version`, and
    additionally recomputes the programme's `open_hold_count` downward with a
    `version` increment because a hold has left the queue."

    Design: Difficulty/non_linear_state_machine/claim_fraud_hold_cycle_back_to_submitted
    """
    ctx = _submitted_claim_with_one_line()
    claim_id = ctx["claim"]["id"]
    hold_claim(claim_id, WA_1, hold_reason="SERIAL_PATTERN_REVIEW")
    clear_hold(claim_id, WA_2, clearance_note="Independent review complete")

    reheld = hold_claim(claim_id, BP_1, hold_reason="SECOND_REVIEW")
    assert reheld["status"] == "FRAUD_HOLD"
    assert reheld["hold_reason"] == "SECOND_REVIEW"
    assert reheld["held_by_user_id"] == "bp-1"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 1

    denied = validate_success(
        api_client.deny_fraud_warranty_claim(
            claim_id, deny_payload(denial_code="FRAUD_CONFIRMED"), BP_1
        )
    )

    assert denied["status"] == "DENIED_FRAUD"
    assert denied["denial_code"] == "FRAUD_CONFIRMED"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 0


def test_no_reserve_money_moves_anywhere_in_the_hold_cycle():
    """The claim carries a frozen 681 cent charge from its single line throughout,
    but nothing is ever debited because the claim was never approved.

    PRD §2.9: "A warranty programme is funded once with `reserve_funded_cents`,
    immutable thereafter, and at every instant `reserve_funded_cents` equals
    `reserve_balance_cents` plus the sum of the `reserve_charge_cents` of the
    programme's claims that are currently in `APPROVED` or `FULFILLED` status."

    Design: Difficulty/non_linear_state_machine/claim_fraud_hold_cycle_back_to_submitted
    """
    ctx = _submitted_claim_with_one_line()
    claim_id = ctx["claim"]["id"]
    program_id = ctx["program"]["id"]
    assert read_program(program_id)["reserve_balance_cents"] == 5_000_000

    for step in (
        lambda: hold_claim(claim_id, WA_1, hold_reason="SERIAL_PATTERN_REVIEW"),
        lambda: clear_hold(claim_id, WA_2, clearance_note="Independent review complete"),
        lambda: hold_claim(claim_id, BP_1, hold_reason="SECOND_REVIEW"),
        lambda: validate_success(
            api_client.deny_fraud_warranty_claim(
                claim_id, deny_payload(denial_code="FRAUD_CONFIRMED"), BP_1
            )
        ),
    ):
        step()
        program = read_program(program_id)
        assert program["reserve_balance_cents"] == 5_000_000
        assert program["reserve_funded_cents"] == 5_000_000

    claim = read_claim(claim_id)
    assert claim["reserve_charge_cents"] == 681
    assert_reserve_ledger(read_program(program_id), [claim])


# ---------------------------------------------------------------------------
# Claim state outranks the fiscal rule
# ---------------------------------------------------------------------------


def _held_claim_against_a_thin_reserve():
    """A 500 cent programme against a claim whose 681 cent charge it cannot
    cover, with the claim parked on fraud hold."""
    ctx = setup_warranty_scenario(
        program_overrides={"program_code": "LIFETIME-THIN", "reserve_funded_cents": 500},
        lines=(HANDLE_LINE,),
    )
    ctx["claim"] = hold_claim(ctx["claim"]["id"], WA_1, hold_reason="MANUAL_REVIEW")
    return ctx


def test_a_held_claim_reports_its_state_error_rather_than_the_reserve_shortfall():
    """Both faults are live at once — wrong status and an unaffordable charge —
    and the status check sits higher on the ladder.

    PRD §3.8: "**Approval** is the heaviest operation in the system. It is a
    `WarrantyAdministrator` act carrying `expected_program_version`, and it is
    gated by eight checks in this exact order."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_reserve_fiscal
    """
    ctx = _held_claim_against_a_thin_reserve()
    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] < ctx["claim"]["reserve_charge_cents"]

    body = validate_error(
        api_client.approve_warranty_claim(
            ctx["claim"]["id"], approve_claim_payload(program["version"]), WA_2
        ),
        ApiErrorId.ERR_CLAIM_STATE_INVALID,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_RESERVE_INSUFFICIENT


def test_the_refused_approval_moves_neither_reserve_money_nor_units():
    """After the refusal the claim is still held, its charge is still frozen at
    681 cents, and both ledgers are exactly where they were.

    PRD §2.7: "The stale-version check sits **after** the addressed entity's
    state precondition but **before** every business rule, so a claim in the
    wrong status reports its state error even when the supplied programme version
    is also stale, while a claim in the right status with a stale version reports
    the version error even when its reserve charge also exceeds the balance."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_reserve_fiscal
    """
    ctx = _held_claim_against_a_thin_reserve()
    program = read_program(ctx["program"]["id"])
    validate_error(
        api_client.approve_warranty_claim(
            ctx["claim"]["id"], approve_claim_payload(program["version"]), WA_2
        ),
        ApiErrorId.ERR_CLAIM_STATE_INVALID,
    )

    claim = read_claim(ctx["claim"]["id"])
    assert claim["status"] == "FRAUD_HOLD"
    assert claim["reserve_charge_cents"] == 681

    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 500
    assert read_sku(ctx["sku"]["id"])["units_reserved"] == 0


# ---------------------------------------------------------------------------
# Intake window versus lifetime membership
# ---------------------------------------------------------------------------


def _three_claims_across_fourteen_months():
    """One claim outside the trailing year, one inside it, and a third filed at
    the default clock reading."""
    sku = create_sku(**BRANDED_PLIER)
    program = create_program(program_code="LIFETIME-1", reserve_funded_cents=5_000_000,
                             fraud_score_threshold=60)
    claimant = create_claimant(email="c1@example.com", claimant_type="CONSUMER")

    set_clock("2025-06-01T00:00:00Z")
    claim_a = create_claim(
        claimant["id"], sku["id"], program["id"], serial_code="SN-A", claim_reason="BREAKAGE"
    )
    set_clock("2026-03-01T00:00:00Z")
    claim_b = create_claim(
        claimant["id"],
        sku["id"],
        program["id"],
        serial_code="SN-B",
        claim_reason="MECHANISM_FAILURE",
    )
    set_clock("2026-08-01T00:00:00Z")
    claim_c = create_claim(
        claimant["id"], sku["id"], program["id"], serial_code="SN-C", claim_reason="CORROSION"
    )
    return {
        "sku": sku,
        "program": program,
        "claimant": claimant,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "claim_c": claim_c,
    }


def test_the_intake_window_excludes_a_claim_older_than_the_trailing_year():
    """Only the March claim and the new one fall inside the 365 day look-back, so
    the frozen intake score is two claims at nine points each.

    PRD §3.7: "The **intake variant** takes the claimant's claims created within
    the trailing 365 days measured back from the logical clock's current reading,
    in any status other than `REVOKED` — that is, `SUBMITTED`, `FRAUD_HOLD`,
    `APPROVED`, `FULFILLED`, `DENIED` or `DENIED_FRAUD` — together with the claim
    now being created."

    Design: Difficulty/dual_variant_calc/claimant_fraud_intake_vs_adjudication_divergence
    """
    ctx = _three_claims_across_fourteen_months()

    assert ctx["claim_c"]["fraud_score_at_intake"] == 18
    assert ctx["claim_c"]["status"] == "SUBMITTED"

    claimant = read_claimant(ctx["claimant"]["id"])
    assert claimant["fraud_risk_score_intake"] == 18
    assert claimant["lifetime_claim_count"] == 3


def test_the_adjudication_variant_counts_every_claim_the_claimant_ever_filed():
    """Placing the newest claim on hold recomputes the adjudication score over
    all three claims, so the two variants read 18 and 27 side by side.

    PRD §3.8: "Because the two variants differ in window, in membership and in
    the counterfeit term, the same claimant will routinely show different values
    in `fraud_risk_score_intake` and `fraud_risk_score_adjudication`, and both
    are visible side by side on the claimant record."

    Design: Difficulty/dual_variant_calc/claimant_fraud_intake_vs_adjudication_divergence
    """
    ctx = _three_claims_across_fourteen_months()

    held = hold_claim(ctx["claim_c"]["id"], WA_1, hold_reason="MANUAL_REVIEW")
    assert held["status"] == "FRAUD_HOLD"
    assert held["held_by_user_id"] == "wa-1"

    claimant = read_claimant(ctx["claimant"]["id"])
    assert claimant["fraud_risk_score_intake"] == 18
    assert claimant["fraud_risk_score_adjudication"] == 27
    assert claimant["fraud_risk_score_intake"] != claimant["fraud_risk_score_adjudication"]

    assert read_claim(ctx["claim_a"]["id"])["status"] == "SUBMITTED"
    assert read_claim(ctx["claim_b"]["id"])["status"] == "SUBMITTED"
