"""Insurance: the per-line-then-sum reimbursement arithmetic, the annual cap, the
adjudication branches, and the order-version guard on claim filing."""

from test_helpers import (
    ApiErrorId,
    adjudicate_approved,
    assert_insurance_claim,
    claim_for,
    confirm_order,
    create_insurance_claim_payload,
    file_insurance_claim,
    new_order,
    read_claim,
    read_order,
    read_policy,
    reimburse_claim,
    setup_confirmed_order,
    setup_out_of_network_claim_ready,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BENEFITS


def _in_network_confirmed_order():
    """A 15,000c in-network plan, a 19,500c frame and a 6,000c M160 blank, confirmed —
    the ESTIMATED benefit_applied_cents lands at 17,900."""
    return setup_confirmed_order(
        policy={
            "network": "IN_NETWORK",
            "frame_allowance_cents": 15000,
            "lens_copay_cents": 2500,
            "annual_max_cents": 30000,
        },
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M160", "base_price_cents": 6000, "material_index": 1.60},
        prescription={
            "od_sphere": -2.00,
            "od_cylinder": 0.00,
            "os_sphere": -2.00,
            "os_cylinder": 0.00,
            "pd_mm": 62.0,
        },
    )


# ═════════════════════════════════════════════════════════════════════════════
# Out-of-network reimbursement — round EACH line, THEN sum
# ═════════════════════════════════════════════════════════════════════════════

def test_reimbursement_rounds_each_service_line_before_summing(api):
    """PRD §3.8: "For each line, the schedule cap is the value the policy's
    `oon_fee_schedule` maps the line's `code` to, or zero when the map has no entry for that
    code. The eligible amount for the line is the smaller of the line's `billed_cents` and
    that schedule cap. The line's reimbursement is the eligible amount multiplied by the
    policy's `oon_reimburse_pct` and rounded half up to whole cents. Those per-line
    reimbursements are then added together."
    PRD §3.8: "**The rounding order is pinned and consequential**: rounding each line and then
    summing produces a different total than summing the raw products and rounding once, and
    only the first is correct."

    Two lines each eligible for 4,999c at 0.75: rounding per line gives 3,749 + 3,749 == 7,498.
    Summing the raw products first would give round(9,998 * 0.75) == round(7,498.5) == 7,499 —
    which is the wrong answer.

    Design: Difficulty/combinatorial_formula/oon_reimbursement_rounds_per_line_then_sums
    """
    scenario = setup_out_of_network_claim_ready(
        service_lines=[
            {"code": "92004", "billed_cents": 4999},
            {"code": "V2020", "billed_cents": 4999},
        ],
        allowed_amount_cents=7498,
    )
    claim = scenario["claim"]

    resp = api.reimburse_insurance_claim(claim["id"], BENEFITS)
    reimbursed = validate_success(resp, 200)

    assert_insurance_claim(reimbursed)
    assert reimbursed["reimbursed_amount_cents"] == 7498, "never 7,499"
    assert reimbursed["status"] == "REIMBURSED"
    assert read_policy(scenario["policy"]["id"])["annual_reimbursed_cents"] == 7498


def test_an_out_of_network_approval_never_re_quotes_the_parent_order(api):
    """PRD §3.8: "**`OUT_OF_NETWORK`.** The claim's `approved_amount_cents` is zero and the
    parent order is **not** re-quoted at all; its `quote_variant` stays `ESTIMATED`.
    Out-of-network money moves through reimbursement, not through the order."
    PRD §3.6: "**Step four: the benefit waterfall.** If the customer has no
    `insurance_policy_id`, or if their policy's `network` is `OUT_OF_NETWORK`, then
    `benefit_frame_cents` and `benefit_lens_cents` are both zero: an out-of-network plan pays
    the member afterwards, never the retailer at the counter."

    The out-of-network member still owes the full 19,500c at the counter — the plan pays them
    back later, through the claim.

    Design: Difficulty/combinatorial_formula/oon_reimbursement_rounds_per_line_then_sums
    """
    scenario = setup_out_of_network_claim_ready(
        service_lines=[
            {"code": "92004", "billed_cents": 4999},
            {"code": "V2020", "billed_cents": 4999},
        ],
        allowed_amount_cents=7498,
    )
    reimburse_claim(scenario["claim"]["id"])

    order = read_order(scenario["order"]["id"])
    assert order["quote_variant"] == "ESTIMATED"
    assert order["benefit_applied_cents"] == 0
    assert order["customer_due_cents"] == 19500, "the 0c M150 blank leaves only the frame"


def test_reimbursement_clamps_at_the_remaining_annual_headroom(api):
    """PRD §3.8: "The claim's `reimbursed_amount_cents` is the smaller of that total and the
    policy's remaining annual headroom — `annual_max_cents` minus `annual_reimbursed_cents` —
    so a claim may be paid out only partially when it exhausts the year. The policy's
    `annual_reimbursed_cents` is then increased by exactly the amount paid, and the claim's
    `version` increments."

    The line reimburses 3,749 but only 3,000 of headroom exists.

    Design: Corner/calculations/oon_reimbursement_clamps_at_remaining_annual_max
    """
    scenario = setup_out_of_network_claim_ready(
        service_lines=[{"code": "92004", "billed_cents": 4999}],
        annual_max_cents=3000,
        oon_fee_schedule={"92004": 5000},
        allowed_amount_cents=4999,
    )

    resp = api.reimburse_insurance_claim(scenario["claim"]["id"], BENEFITS)
    reimbursed = validate_success(resp, 200)

    assert reimbursed["reimbursed_amount_cents"] == 3000
    assert reimbursed["status"] == "REIMBURSED"
    assert read_policy(scenario["policy"]["id"])["annual_reimbursed_cents"] == 3000


def test_a_service_code_absent_from_the_schedule_contributes_nothing(api):
    """PRD §3.1: "`oon_fee_schedule` is a map from service code to the maximum eligible amount
    in cents for that code — for instance a schedule that allows five thousand cents against
    code `92004` — and it defaults to an empty map; **a code absent from the map is eligible
    for zero cents**, which means an out-of-network claim filed against an empty schedule
    reimburses nothing at all."
    PRD §3.8: "For each line, the schedule cap is the value the policy's `oon_fee_schedule`
    maps the line's `code` to, or zero when the map has no entry for that code."

    The scheduled line pays 3,749; the unscheduled 9,999c line pays exactly nothing.

    Design: Corner/calculations/oon_service_code_absent_from_schedule_contributes_zero
    """
    scenario = setup_out_of_network_claim_ready(
        service_lines=[
            {"code": "92004", "billed_cents": 4999},
            {"code": "Z9999", "billed_cents": 9999},
        ],
        oon_fee_schedule={"92004": 5000},
        allowed_amount_cents=4999,
    )

    reimbursed = reimburse_claim(scenario["claim"]["id"])

    assert reimbursed["reimbursed_amount_cents"] == 3749
    assert read_policy(scenario["policy"]["id"])["annual_reimbursed_cents"] == 3749


def test_a_fully_consumed_annual_max_blocks_a_second_reimbursement(api):
    """PRD §3.8: "The attempt is refused with `ERR_INVALID_STATE` when the policy's `network`
    is `IN_NETWORK` — in-network claims are never reimbursed to the member — and refused with
    `ERR_ANNUAL_MAX_EXCEEDED` when the policy has no headroom, meaning its `annual_max_cents`
    minus its `annual_reimbursed_cents` is zero or below."

    The check demands headroom greater than zero, so an exhausted plan blocks outright rather
    than paying a zero-cent claim.

    Design: Corner/errors/annual_max_exhausted_returns_annual_max_exceeded
    """
    scenario = setup_out_of_network_claim_ready(
        service_lines=[{"code": "92004", "billed_cents": 4999}],
        annual_max_cents=3000,
        oon_fee_schedule={"92004": 5000},
        allowed_amount_cents=4999,
    )
    first = reimburse_claim(scenario["claim"]["id"])
    assert first["reimbursed_amount_cents"] == 3000
    assert read_policy(scenario["policy"]["id"])["annual_reimbursed_cents"] == 3000

    # A second order on the same exhausted plan, taken through to an approved claim.
    second_order = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["frame"]["id"],
        scenario["material"]["id"],
    )
    second_order = confirm_order(second_order["id"], scenario["customer"]["id"])
    second_claim = file_insurance_claim(
        second_order["id"],
        second_order["version"],
        [{"code": "92004", "billed_cents": 4999}],
    )
    second_claim = adjudicate_approved(second_claim["id"], 4999)

    resp = api.reimburse_insurance_claim(second_claim["id"], BENEFITS)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_MAX_EXCEEDED.value)

    assert read_claim(second_claim["id"])["status"] == "ADJUDICATED_APPROVED"
    assert read_policy(scenario["policy"]["id"])["annual_reimbursed_cents"] == 3000


# ═════════════════════════════════════════════════════════════════════════════
# Adjudication branches
# ═════════════════════════════════════════════════════════════════════════════

def test_reimbursing_an_in_network_claim_is_an_invalid_state(api):
    """PRD §3.8: "**Reimbursement.** An `ADJUDICATED_APPROVED` claim on an `OUT_OF_NETWORK`
    policy is paid by a `BenefitsAdmin`, advancing it `ADJUDICATED_APPROVED → REIMBURSED`. The
    attempt is refused with `ERR_INVALID_STATE` when the policy's `network` is `IN_NETWORK` —
    in-network claims are never reimbursed to the member — and refused with
    `ERR_ANNUAL_MAX_EXCEEDED` when the policy has no headroom, meaning its `annual_max_cents`
    minus its `annual_reimbursed_cents` is zero or below."
    PRD §3.8: "Under `FINAL`, `benefit_applied_cents` is replaced by the smaller of the
    `ESTIMATED` `benefit_applied_cents` and the claim's `allowed_amount_cents`;
    `customer_due_cents` becomes the net amount (the subtotal less the discount) minus that new
    `benefit_applied_cents` minus the already-committed `fsa_applied_cents`; and the order's
    `quote_variant` becomes `FINAL`."

    Design: Corner/errors/reimbursing_an_in_network_claim_returns_invalid_state
    """
    scenario = _in_network_confirmed_order()
    claim = claim_for(scenario["order"]["id"])
    adjudicate_approved(claim["id"], 12000)

    resp = api.reimburse_insurance_claim(claim["id"], BENEFITS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_claim(claim["id"])
    assert after["status"] == "ADJUDICATED_APPROVED"
    assert after["reimbursed_amount_cents"] == 0

    order = read_order(scenario["order"]["id"])
    assert order["quote_variant"] == "FINAL", "the in-network approval did re-quote the order"
    assert order["benefit_applied_cents"] == 12000, "min(17,900 estimated, 12,000 allowed)"


def test_denying_a_claim_without_a_reason_is_an_invalid_request(api):
    """PRD §3.8: "A `decision` of `DENIED` advances the claim `SUBMITTED → ADJUDICATED_DENIED`
    and requires a `denial_reason`; a denial without one is refused with
    `ERR_INVALID_REQUEST`."
    PRD §3.8: "Note what a denial does **not** do: the reserved frame benefit **stays
    reserved** on the policy. Only a void releases it."

    Design: Corner/errors/claim_denial_without_reason_returns_invalid_request
    """
    scenario = _in_network_confirmed_order()
    claim = claim_for(scenario["order"]["id"])

    resp = api.adjudicate_insurance_claim(claim["id"], {"decision": "DENIED"}, BENEFITS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    after = read_claim(claim["id"])
    assert after["status"] == "SUBMITTED"
    assert after["reserved_frame_benefit_cents"] == 15000
    assert read_policy(scenario["policy"]["id"])["frame_allowance_remaining_cents"] == 0


def test_adjudicating_an_unknown_claim_is_a_claim_not_found(api):
    """PRD §2.9: "**Path existence.** Every resource named in the URL path exists, validated
    left to right, so that the leftmost missing identifier is the one reported. The not-found
    codes are `ERR_CUSTOMER_NOT_FOUND`, `ERR_FRAME_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`,
    `ERR_KIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND` and `ERR_APPOINTMENT_NOT_FOUND`, all
    HTTP 404."

    Design: Corner/errors/adjudicating_an_unknown_claim_returns_claim_not_found
    """
    resp = api.adjudicate_insurance_claim(
        "11111111-1111-4111-8111-111111111111",
        {"decision": "APPROVED", "allowed_amount_cents": 100},
        BENEFITS,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)


# ═════════════════════════════════════════════════════════════════════════════
# The order-version guard on claim filing
# ═════════════════════════════════════════════════════════════════════════════

def test_re_filing_a_claim_with_a_spent_order_version_is_rejected(api):
    """PRD §2.7: "Filing an insurance claim — `POST /optical/insurance-claims` — requires a
    non-optional `expected_order_version` field in the request body, carrying the `version` of
    the target `Order` as the client last observed it. If that value does not equal the order's
    current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §3.8: "The order's `active_claim_id` is repointed at the new claim and the order's
    `version` increments — which is precisely why the next filing needs a fresh
    `expected_order_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_on_claim_create_returns_412
    """
    scenario = _in_network_confirmed_order()
    order = scenario["order"]
    confirmed_version = order["version"]

    first = file_insurance_claim(
        order["id"], confirmed_version, [{"code": "92004", "billed_cents": 4000}]
    )

    resp = api.create_insurance_claim(
        create_insurance_claim_payload(
            order["id"],
            confirmed_version,  # the very version that just worked — now stale
            [{"code": "92004", "billed_cents": 4000}],
        ),
        BENEFITS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)

    assert read_claim(first["id"])["status"] == "SUBMITTED", "the first filing stands"
    assert read_order(order["id"])["active_claim_id"] == first["id"]
    assert read_policy(scenario["policy"]["id"])["frame_allowance_remaining_cents"] == 0

    _rows, meta = validate_paginated(
        api.list_insurance_claims(BENEFITS, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 2, "the VOIDed auto-claim and the first explicit filing"
