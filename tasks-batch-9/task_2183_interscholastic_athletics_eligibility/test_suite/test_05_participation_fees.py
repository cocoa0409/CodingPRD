"""Assessing the participation fee, and the payment / waiver / refund axis."""
from test_helpers import (
    ApiErrorId,
    assert_case_fee_ledger,
    assert_eligibility_case,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def _multi_sport_athlete():
    """A free/reduced-lunch athlete with a TIER_C case already on the books."""
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    tier_c = fx.create_season(sport="BASKETBALL", sport_tier="TIER_C")
    tier_a = fx.create_season(sport="FOOTBALL", sport_tier="TIER_A")
    student = fx.create_student(
        school["id"], full_name="Cora Diaz", birth_date="2009-03-11", grade_level=11,
        residency_verified=True, residency_verified_on="2026-08-10",
        free_reduced_lunch=True,
    )
    first_case = fx.create_case(school["id"], student["id"], tier_c["id"])
    return {"school": school, "tier_c": tier_c, "tier_a": tier_a,
            "student": student, "first_case": first_case}


def test_first_case_halves_the_tier_base_for_a_free_reduced_lunch_athlete(api):
    """PRD §3.3: "The starting figure is the season's tier base: 12345 cents for
    `TIER_A`, 8975 cents for `TIER_B`, and 6499 cents for `TIER_C`."
    PRD §3.3: "A multi-sport discount follows from that count, capped at two: no
    discount for a first case, a twenty-five percent discount when exactly one prior
    case is counted, and a forty percent discount when two or more are counted."
    PRD §3.3: "If the athlete carries `free_reduced_lunch`, that line item is then
    halved and rounded half up to whole cents again — this is the second rounding,
    taken on the already-rounded line item, never folded into the first."

    Design: Difficulty/combinatorial_formula/participation_fee_pins_per_line_rounding_before_the_family_cap
    """
    ctx = _multi_sport_athlete()

    case = fx.read_case(ctx["first_case"]["id"])

    assert_eligibility_case(case)
    assert case["fee_amount_cents"] == 3250, (
        "6499 with no multi-sport discount, halved and rounded half up, is 3250"
    )
    assert case["fee_outstanding_cents"] == 3250
    assert case["fee_status"] == "ASSESSED"


def test_second_case_rounds_per_line_and_lands_on_4630_not_4629(api):
    """PRD §3.3: "Applying the discount to the tier base and rounding half up to
    whole cents produces the line item — this is the first rounding."
    PRD §3.3: "Collapsing the two roundings into a single multiplication is wrong
    and is known to produce a different persisted figure: for a `TIER_A` season with
    exactly one prior case and free-or-reduced lunch, the pinned order gives 9259
    cents after the first rounding and 4630 cents after the second, while the
    collapsed reading would give 4629 cents."
    PRD §3.3: "Headroom is the school's `fee_cap_cents` minus the sum of
    `fee_amount_cents` over exactly the prior cases counted above; `fee_amount_cents`
    for the new case is the line item or that headroom, whichever is smaller, floored
    at 0 so it can never be negative."

    Design: Difficulty/combinatorial_formula/participation_fee_pins_per_line_rounding_before_the_family_cap
    """
    ctx = _multi_sport_athlete()

    second = validate_success(
        api.create_eligibility_case(
            {"student_id": ctx["student"]["id"], "sport_season_id": ctx["tier_a"]["id"]},
            fx.make_director_headers(ctx["school"]["id"]),
        ),
        201,
    )

    assert second["fee_amount_cents"] == 4630
    assert second["fee_amount_cents"] != 4629, (
        "the collapsed single-multiplication reading is the wrong one"
    )
    assert second["fee_outstanding_cents"] == 4630
    assert second["fee_status"] == "ASSESSED"


def test_paying_a_case_in_full_raises_the_schools_collected_cents(api):
    """PRD §3.5: "Every one of those four payment edges does the same three things:
    it increases `fee_paid_cents` by the amount received, recomputes
    `fee_outstanding_cents` (which lands at exactly 0 on the three settling edges),
    and increases the school's `fee_collected_cents` by the same amount received."
    PRD §2.9: "`fee_collected_cents` must at all times equal the sum, over every
    eligibility case belonging to a student of that school, of `fee_paid_cents` minus
    `fee_refunded_cents`."

    Design: Difficulty/compensating_invariant/fee_payment_then_refund_conserves_school_collected_cents
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Iris Pham",
                                birth_date="2009-11-02", grade_level=10,
                                residency_verified=True,
                                residency_verified_on="2026-08-10")
    case = fx.create_case(school["id"], student["id"], season["id"])
    assert fx.read_school(school["id"])["fee_collected_cents"] == 0

    paid = validate_success(
        api.create_fee_payment(case["id"], {"amount_cents": 12345},
                               fx.make_director_headers(school["id"])),
        200,
    )

    assert paid["fee_paid_cents"] == 12345
    assert paid["fee_outstanding_cents"] == 0
    assert paid["fee_status"] == "PAID"
    assert fx.read_school(school["id"])["fee_collected_cents"] == 12345


def test_refunding_the_case_returns_the_school_ledger_to_its_pre_payment_value(
    api, admin_headers
):
    """PRD §3.5: "A refund is declared only from `PAID`, and it returns everything
    collected: `fee_refunded_cents` is set equal to `fee_paid_cents`,
    `fee_outstanding_cents` is recomputed as `fee_amount_cents` less
    `fee_paid_cents`, less `fee_waived_cents`, plus `fee_refunded_cents`, the
    school's `fee_collected_cents` is decremented by the refunded cents, and the
    money axis moves `PAID → REFUNDED`."
    PRD §2.9: "After a pay-then-refund pair, the school's `fee_collected_cents`
    returns to its pre-payment value and the case's `fee_outstanding_cents` returns
    to `fee_amount_cents` less `fee_waived_cents`."

    Design: Difficulty/compensating_invariant/fee_payment_then_refund_conserves_school_collected_cents
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Iris Pham",
                                birth_date="2009-11-02", grade_level=10,
                                residency_verified=True,
                                residency_verified_on="2026-08-10")
    case = fx.create_case(school["id"], student["id"], season["id"])
    fx.pay_fee(case["id"], school["id"], 12345)
    assert fx.read_school(school["id"])["fee_collected_cents"] == 12345

    refunded = validate_success(
        api.create_fee_refund(case["id"], {"refund_reason": "season cancelled"},
                              admin_headers),
        200,
    )

    assert refunded["fee_status"] == "REFUNDED"
    assert refunded["fee_amount_cents"] == 12345
    assert refunded["fee_paid_cents"] == 12345
    assert refunded["fee_refunded_cents"] == 12345
    assert refunded["fee_waived_cents"] == 0
    assert refunded["fee_outstanding_cents"] == 12345
    assert_case_fee_ledger(refunded)
    assert fx.read_school(school["id"])["fee_collected_cents"] == 0


def test_approved_waiver_zeroes_the_balance_and_leaves_the_cash_ledger_alone(
    api, admin_headers
):
    """PRD §3.5: "A `decision` of `APPROVE` moves `WAIVER_REQUESTED → WAIVED`:
    `fee_waived_cents` is set to whatever `fee_outstanding_cents` stood at in that
    moment, `fee_outstanding_cents` drops to 0, and the school's
    `fee_collected_cents` is left completely untouched, because waived money was
    never collected."
    PRD §3.5: "A payment that is strictly less than the outstanding balance moves
    the money axis `ASSESSED → PARTIALLY_PAID`."

    Design: Corner/state_machines/waiver_approval_zeroes_the_balance_without_touching_the_school_cash_ledger
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Rae Kimura",
                                birth_date="2009-05-14", grade_level=10)
    case = fx.create_case(school["id"], student["id"], season["id"])
    fx.pay_fee(case["id"], school["id"], 5000)
    validate_success(
        api.create_fee_waiver_request(
            case["id"], {"waiver_reason": "documented family hardship"},
            fx.make_director_headers(school["id"]),
        ),
        200,
    )

    waived = validate_success(
        api.create_fee_waiver_decision(
            case["id"], {"decision": "APPROVE", "decision_note": "hardship verified"},
            admin_headers,
        ),
        200,
    )

    assert waived["fee_status"] == "WAIVED"
    assert waived["fee_waived_cents"] == 7345
    assert waived["fee_paid_cents"] == 5000
    assert waived["fee_outstanding_cents"] == 0
    assert fx.read_school(school["id"])["fee_collected_cents"] == 5000


def test_family_cap_clamps_the_second_case_to_zero_and_opens_it_paid(api):
    """PRD §3.3: "Headroom is the school's `fee_cap_cents` minus the sum of
    `fee_amount_cents` over exactly the prior cases counted above; `fee_amount_cents`
    for the new case is the line item or that headroom, whichever is smaller, floored
    at 0 so it can never be negative."
    PRD §3.3: "Where the arithmetic lands on 0 — because the cap is already
    exhausted, or the school's cap is itself 0 — the case is initialised straight to
    `PAID` on its fee axis with `fee_paid_cents` 0 and `fee_outstanding_cents` 0;
    otherwise it is initialised to `ASSESSED`."

    Design: Corner/calculations/family_fee_cap_clamps_the_second_case_to_zero_and_marks_it_paid
    """
    school = fx.create_school(name="North High", fee_cap_cents=3250)
    tier_c = fx.create_season(sport="BASKETBALL", sport_tier="TIER_C")
    tier_a = fx.create_season(sport="FOOTBALL", sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Wren Oyelaran",
                                birth_date="2009-05-14", grade_level=10,
                                free_reduced_lunch=True)
    first = fx.create_case(school["id"], student["id"], tier_c["id"])

    second = validate_success(
        api.create_eligibility_case(
            {"student_id": student["id"], "sport_season_id": tier_a["id"]},
            fx.make_director_headers(school["id"]),
        ),
        201,
    )

    assert first["fee_amount_cents"] == 3250
    assert second["fee_amount_cents"] == 0
    assert second["fee_outstanding_cents"] == 0
    assert second["fee_status"] == "PAID"
    assert second["fee_paid_cents"] == 0
    assert fx.read_school(school["id"])["fee_collected_cents"] == 0


def test_paying_one_cent_more_than_the_balance_is_an_overpayment(api):
    """PRD §3.5: "The amount must be strictly greater than 0 and no greater than
    the case's current `fee_outstanding_cents`; anything outside that half-open range
    — zero, negative, or more than is owed — is refused with `ERR_FEE_OVERPAYMENT`
    and HTTP 422, which is the only 422 in the fee flow besides refunds."

    Design: Corner/errors/paying_one_cent_more_than_the_balance_returns_fee_overpayment
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Fin Alvarez",
                                birth_date="2009-05-14", grade_level=10)
    case = fx.create_case(school["id"], student["id"], season["id"])

    response = api.create_fee_payment(
        case["id"], {"amount_cents": 12346}, fx.make_director_headers(school["id"])
    )

    validate_error(response, ApiErrorId.ERR_FEE_OVERPAYMENT.value, 422)
    after = fx.read_case(case["id"])
    assert after["fee_paid_cents"] == 0
    assert after["fee_status"] == "ASSESSED"
    assert fx.read_school(school["id"])["fee_collected_cents"] == 0


def test_refunding_a_zero_fee_case_is_stopped_by_the_fiscal_guard(api, admin_headers):
    """PRD §3.5: "One fiscal guard sits in front of all of that: `fee_paid_cents`
    minus `fee_refunded_cents` must be strictly above 0, and if it is not, the answer
    is `ERR_NOTHING_TO_REFUND` with HTTP 422."
    PRD §3.5: "A zero-fee case is precisely the interesting case here — it sits at
    `PAID` with nothing ever collected, so it passes the state gate and is turned
    away by the fiscal guard rather than by a state error."

    Design: Corner/errors/refunding_a_zero_fee_case_returns_nothing_to_refund
    """
    school = fx.create_school(name="Free High", fee_cap_cents=0)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Gil Nakamura",
                                birth_date="2009-05-14", grade_level=10)
    case = fx.create_case(school["id"], student["id"], season["id"])
    assert case["fee_amount_cents"] == 0
    assert case["fee_status"] == "PAID"

    response = api.create_fee_refund(
        case["id"], {"refund_reason": "nothing was ever collected"}, admin_headers
    )

    validate_error(response, ApiErrorId.ERR_NOTHING_TO_REFUND.value, 422)
    assert fx.read_case(case["id"])["fee_status"] == "PAID"
