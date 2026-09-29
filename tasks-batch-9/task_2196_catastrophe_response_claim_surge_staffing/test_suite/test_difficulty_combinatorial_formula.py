"""Queue A — rule_id: combinatorial_formula.

Multi-input formulas whose pinned evaluation order is observable: round-per-line
then sum (advance cap), tier keyed on the pre-premium subtotal (deployment cost),
and the five-input non-linear severity composite.
"""
from test_helpers import validate_success
from test_helpers.assertions import assert_claim, assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CE_OTHER = make_claims_examiner_headers("ce_9")


# ---------------------------------------------------------------------------
# Instance 1 — advance_cap_round_each_coverage_line_then_sum_mode_b
# ---------------------------------------------------------------------------
def _claim_with_third_decimal_lines(api):
    """CAT-2026-201 DECLARED (WILDFIRE/CA @ 0.5000); one claim whose four
    coverage lines each produce a third decimal digit in their advance product."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-201",
                "peril_type": "WILDFIRE",
                "jurisdiction_state": "CA",
                "event_start_utc": "2026-07-28T00:00:00.000Z",
                "exposure_count": 400,
                "avg_insured_value": 300000,
                "expected_severity_index": 0.5000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-8010",
                "loss_state": "CA",
                "loss_date_utc": "2026-07-29T00:00:00.000Z",
                "reported_loss_amount": 95000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 40000,
                        "deductible_amount": 0,
                        "estimated_damage_amount": 30000.03,
                    },
                    {
                        "coverage_code": "CONTENTS",
                        "limit_amount": 25000,
                        "deductible_amount": 0,
                        "estimated_damage_amount": 20000.03,
                    },
                    {
                        "coverage_code": "ALE",
                        "limit_amount": 12000,
                        "deductible_amount": 0,
                        "estimated_damage_amount": 10000.02,
                    },
                    {
                        "coverage_code": "OTHER_STRUCTURES",
                        "limit_amount": 18000,
                        "deductible_amount": 0,
                        "estimated_damage_amount": 15000.03,
                    },
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    return event, triaged


def test_advance_cap_rounds_each_coverage_line_before_summing(api):
    """PRD §3.8: "For each coverage line, in the array order supplied at intake,
    take the line's `estimated_damage_amount` capped at its `limit_amount`, subtract
    its `deductible_amount`, floor the result at zero, multiply by the line's advance
    percentage — 30 percent for `DWELLING`, 25 percent for `CONTENTS`, 50 percent for
    `ALE`, and 20 percent for `OTHER_STRUCTURES` — and **round that line to 2 decimal
    places immediately**."
    PRD §3.8: "Sum the already-rounded line values to get the line-derived cap."
    PRD §3.8: "Multiply the line-derived cap by the tier multiplier for the claim's
    `triage_tier` — 1.00 for `CAT_SEVERE`, 0.85 for `COMPLEX`, 0.60 for `STANDARD`,
    0.40 for `FAST_TRACK` — and round to 2 decimal places."
    PRD §3.6: "Clamp the result so it is not below 0 and not above 100, and only then
    round half up to 2 decimal places — a single rounding, applied after the clamp."

    Design: Difficulty/combinatorial_formula/advance_cap_round_each_coverage_line_then_sum_mode_b
    """
    _, claim = _claim_with_third_decimal_lines(api)

    assert_claim(claim)
    assert_money_equals(claim["severity_score"], 100.00, "severity_score")
    assert claim["triage_tier"] == "CAT_SEVERE"
    # 9000.01 + 5000.01 + 5000.01 + 3000.01 = 22000.04, not round(22000.0325) = 22000.03.
    assert_money_equals(claim["advance_cap"], 22000.04, "advance_cap")
    assert claim["advance_cap"] != 22000.03


def test_advance_issued_at_the_line_rounded_cap_moves_reserve_and_paid(api):
    """PRD §3.8: "The headroom is the `advance_cap` less the claim's
    `advance_paid_total`, rounded to 2 decimal places; if the headroom is 0.00 or less
    the issuance is refused with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422) — the
    exact-zero-headroom case is a rejection, not a zero-dollar payment."
    PRD §3.8: "Otherwise the issued `amount` is the lesser of the `requested_amount`
    and the headroom."
    PRD §3.8: "The claim's `advance_paid_total`, `paid_amount` and `case_reserve` and
    the event's `paid_total` and `case_reserve_total` are all recomputed — but the
    event's `incurred_total` is **unchanged**, because the two movements on the entry
    are equal and opposite."

    Design: Difficulty/combinatorial_formula/advance_cap_round_each_coverage_line_then_sum_mode_b
    """
    event, claim = _claim_with_third_decimal_lines(api)

    advance = validate_success(
        api.create_advance_payment(
            {
                "claim_id": claim["id"],
                "requested_amount": 30000,
                "basis": "STRUCTURE_PARTIAL",
            },
            CE_OTHER,
        ),
        201,
    )

    assert_money_equals(advance["amount"], 22000.04, "amount")
    assert advance["status"] == "ISSUED"
    refreshed = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(refreshed["advance_paid_total"], 22000.04, "advance_paid_total")
    assert_money_equals(refreshed["paid_amount"], 22000.04, "paid_amount")
    # basis max(95000.00, raw eligible sum 75000.11) * 0.85 = 80750.00, less the advance.
    assert_money_equals(refreshed["case_reserve"], 58749.96, "case_reserve")
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["incurred_total"], 80750.00, "incurred_total")


# ---------------------------------------------------------------------------
# Instance 2 — deployment_surge_premium_tier_keyed_on_subtotal_not_total_mode_c
# ---------------------------------------------------------------------------
def _deployment_with_subtotal_19500(api):
    """CAT-2026-202 DECLARED; STAFF adjuster 1500/200; ACTIVE 5-room block at
    250/night; FIELD deployment 2026-09-01 -> 2026-09-11 reserving 1 room."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-202",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-25T00:00:00.000Z",
                "exposure_count": 500,
                "avg_insured_value": 150000,
                "expected_severity_index": 0.1000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Stan Staff",
                "employment_type": "STAFF",
                "home_state": "TX",
                "licensed_states": ["TX"],
                "license_expiry_utc": "2027-12-31T00:00:00.000Z",
                "max_open_claims": 20,
                "daily_rate": 1500,
                "per_diem_rate": 200,
                "desk_certified": False,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Prairie Lodge",
                "city": "Lubbock",
                "rooms_total": 5,
                "nightly_rate": 250,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-15T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-11T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    return event, block, deployment


def test_surge_premium_tier_is_keyed_on_the_pre_premium_subtotal(api):
    """PRD §3.5: "Step four picks the tier **from that subtotal alone, never from
    the post-premium total**, so no iteration is needed and the answer is
    well-defined in a single pass: a subtotal of 20000.00 or more is `TIER_HIGH` at a
    premium rate of 11 percent; a subtotal of 5000.00 or more but below 20000.00 is
    `TIER_MID` at 6 percent; anything below 5000.00 is `TIER_NONE` at zero."
    PRD §3.5: "The surge premium is the subtotal multiplied by that rate, rounded to
    2 decimal places, and the total is the rounded sum of subtotal and premium."

    Design: Difficulty/combinatorial_formula/deployment_surge_premium_tier_keyed_on_subtotal_not_total_mode_c
    """
    _, _, deployment = _deployment_with_subtotal_19500(api)

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    # labour 15000.00 + per-diem 2000.00 + housing 2500.00 = subtotal 19500.00
    # -> TIER_MID 6% -> premium 1170.00 -> total 20670.00. A fixed-point
    # re-derivation from the 20670.00 total would have stamped TIER_HIGH / 21645.00.
    assert_money_equals(confirmed["provisional_cost"], 20670.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_MID"
    assert confirmed["provisional_cost"] != 21645.00
    assert confirmed["status"] == "CONFIRMED"


def test_confirmation_draws_the_reserved_room_from_the_block(api):
    """PRD §3.5: "It adds the deployment's `rooms_reserved` to the block's
    `rooms_occupied` and recomputes `rooms_available`, taking the block
    `ACTIVE → EXHAUSTED` if availability lands on zero."

    Design: Difficulty/combinatorial_formula/deployment_surge_premium_tier_keyed_on_subtotal_not_total_mode_c
    """
    _, block, deployment = _deployment_with_subtotal_19500(api)

    validate_success(api.confirm_deployment(deployment["id"], DC))

    refreshed = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed["rooms_occupied"] == 1
    assert refreshed["rooms_available"] == 4
    assert refreshed["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Instance 3 — claim_severity_five_input_nonlinear_conditional_branches_mode_a
# ---------------------------------------------------------------------------
def _earthquake_restricted_claim(api):
    """CAT-2026-203 DECLARED (EARTHQUAKE/CA @ 0.2500); one RESTRICTED-access claim
    with three coverage lines totalling 300000 of limit and an ALE line."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-203",
                "peril_type": "EARTHQUAKE",
                "jurisdiction_state": "CA",
                "event_start_utc": "2026-07-31T00:00:00.000Z",
                "exposure_count": 800,
                "avg_insured_value": 400000,
                "expected_severity_index": 0.2500,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-8020",
                "loss_state": "CA",
                "loss_date_utc": "2026-07-31T00:00:00.000Z",
                "reported_loss_amount": 90000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 200000,
                        "deductible_amount": 2000,
                        "estimated_damage_amount": 90000,
                    },
                    {
                        "coverage_code": "CONTENTS",
                        "limit_amount": 70000,
                        "deductible_amount": 1000,
                        "estimated_damage_amount": 20000,
                    },
                    {
                        "coverage_code": "ALE",
                        "limit_amount": 30000,
                        "deductible_amount": 0,
                        "estimated_damage_amount": 15000,
                    },
                ],
                "event_id": event["id"],
                "access_status": "RESTRICTED",
            },
            CE,
        ),
        201,
    )
    return event, claim


def test_severity_composite_combines_five_inputs_non_linearly(api):
    """PRD §3.6: "Start from the claim's exposure: sum `limit_amount` across every
    coverage line, divide the `reported_loss_amount` by that total (or by 1 if the
    total is smaller than 1, which protects the division), cap the resulting ratio at
    1, and multiply by 100 to get the base."
    PRD §3.6: "Multiply the base by the peril weight of the parent event's
    `peril_type` — 1.15 for `HURRICANE`, 1.25 for `WILDFIRE`, 1.20 for `FLOOD`, 0.95
    for `HAIL`, 0.90 for `WINTER_STORM`, and 1.30 for `EARTHQUAKE`."
    PRD §3.6: "To that product add the access adjustment for the claim's
    `access_status`: nothing for `ACCESSIBLE`, 6 points for `RESTRICTED`, and 12
    points for `INACCESSIBLE`."
    PRD §3.6: "Add a further 10 points when any coverage line has a `coverage_code`
    of `ALE` and an `estimated_damage_amount` greater than zero, and nothing
    otherwise."
    PRD §3.6: "Finally add 20 times the parent event's `expected_severity_index`."
    PRD §3.6: "The score then selects the band recorded in `triage_tier`: a score of
    75.00 or more is `CAT_SEVERE`, a score of 50.00 or more but below 75.00 is
    `COMPLEX`, a score of 25.00 or more but below 50.00 is `STANDARD`, and anything
    below 25.00 is `FAST_TRACK`."

    Design: Difficulty/combinatorial_formula/claim_severity_five_input_nonlinear_conditional_branches_mode_a
    """
    _, claim = _earthquake_restricted_claim(api)

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    # base 30.00 * 1.30 = 39.00; +6.00 RESTRICTED; +10.00 ALE; +5.00 index term.
    assert_money_equals(triaged["severity_score"], 60.00, "severity_score")
    assert triaged["triage_tier"] == "COMPLEX"
    assert triaged["handling_status"] == "TRIAGED"
    assert triaged["payment_status"] == "NONE"


def test_triage_stamps_mode_reserve_and_deadline_from_the_same_score(api):
    """PRD §3.6: "In every remaining case the mode is `FIELD`."
    PRD §3.6: "First compute the eligible damage of each coverage line as the line's
    `estimated_damage_amount` capped at its `limit_amount`, less its
    `deductible_amount`, with a floor of zero; sum those **raw, unrounded** line
    values; take the greater of that sum and the claim's `reported_loss_amount` as the
    basis; multiply the basis by the tier reserve factor for the claim's
    `triage_tier` — 0.85 for `CAT_SEVERE`, 0.65 for `COMPLEX`, 0.45 for `STANDARD`,
    0.25 for `FAST_TRACK` — and round half up to 2 decimal places **once, at the
    end**."
    PRD §3.2: "The base deadline is that anchor advanced by 15 whole days."
    PRD §3.1: "`case_reserve_total` and `paid_total` are the sums of the case-reserve
    and paid movements of every ledger entry belonging to the event, each to 2 decimal
    places, and `incurred_total` is their sum — the conserved quantity of §2.10."

    Design: Difficulty/combinatorial_formula/claim_severity_five_input_nonlinear_conditional_branches_mode_a
    """
    event, claim = _earthquake_restricted_claim(api)

    triaged = validate_success(api.triage_claim(claim["id"], CE))

    assert triaged["inspection_mode"] == "FIELD"
    # raw eligible sum 88000 + 19000 + 15000 = 122000.00 > reported 90000.00; * 0.65.
    assert_money_equals(triaged["case_reserve"], 79300.00, "case_reserve")
    assert triaged["deadline_utc"] == "2026-08-16T00:00:00.000Z"
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["case_reserve_total"], 79300.00, "case_reserve_total")
