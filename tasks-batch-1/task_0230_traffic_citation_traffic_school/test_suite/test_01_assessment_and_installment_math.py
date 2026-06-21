"""Assessment arithmetic and installment-schedule math.

Covers the combinatorial-formula difficulty instances (surcharge rounding order,
floor base + remainder-to-final) and the dual-variant installment-schedule vs
chronological-balance divergence, plus the corner computed-balance instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_jurisdiction_payload,
    create_driver_payload,
    create_citation_payload,
    create_charge_payload,
    create_installment_plan_payload,
    create_payment_payload,
    TEST_USERS,
    make_driver_headers,
)
from test_helpers.fixtures import (
    create_jurisdiction,
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_citation_with_active_plan,
    set_clock,
    list_installments_for_plan,
    CLERK,
)


def test_assessed_total_surcharge_rounded_before_court_fee_add(api):
    """PRD §3.3: "the surcharge is the base fine multiplied by the jurisdiction's
    surcharge fraction, rounded half-up to a whole cent; the assessed total is then
    the base fine plus the flat court fee plus that rounded surcharge."
    PRD §3.3: "the evaluation order is pinned — the surcharge is rounded *before*
    the integer court fee is added, so the court fee never sits inside the rounding
    boundary."

    Design: Difficulty/combinatorial_formula/assessed_total_surcharge_rounded_before_court_fee_add
    """
    jur, driver = setup_jurisdiction_and_driver(
        jurisdiction_overrides={
            "name": "Court B", "state_code": "NV", "surcharge_pct": 0.225
        }
    )
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC22107", description="Unsafe turn",
            base_fine_cents=9990, points=0,
        ),
        CLERK,
    )
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    # surcharge = round_half_up(9990 * 0.225) = round_half_up(2247.75) = 2248
    # assessed_total = 9990 + 5000 + 2248 = 17238
    assert assessed["assessed_total_cents"] == 17238
    assert assessed["balance_cents"] == 17238
    assert assessed["financial_status"] == "ASSESSED"


def test_assessed_total_default_surcharge_rounding(api):
    """PRD §3.3: "the surcharge is the base fine multiplied by the jurisdiction's
    surcharge fraction, rounded half-up to a whole cent; the assessed total is then
    the base fine plus the flat court fee plus that rounded surcharge."

    Design: Difficulty/combinatorial_formula/assessed_total_surcharge_rounded_before_court_fee_add
    """
    # Jurisdiction A: surcharge_pct 0.20, base 20000 -> surcharge 4000,
    # assessed_total = 20000 + 5000 + 4000 = 29000.
    _, _, assessed = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    assert assessed["assessed_total_cents"] == 29000
    assert assessed["balance_cents"] == 29000


def test_installment_floor_base_with_remainder_to_final(api):
    """PRD §3.5: "The nominal per-installment base is the principal divided by the
    term count, taking the floor (the integer quotient), and is stored as
    `installment_cents`. The whole-number remainder left over — the principal minus
    the base times the term count — is not spread across the schedule; instead the
    final installment absorbs the entire remainder."
    PRD §3.5: "each of the first term-count-minus-one installments is scheduled for
    the base amount, and the last installment is scheduled for the base plus the
    remainder."

    Design: Difficulty/combinatorial_formula/installment_floor_base_with_remainder_to_final
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit["id"], CLERK)  # assessed_total 29000
    set_clock("2026-02-11T00:00:00Z")
    after_penalty = validate_success(api.apply_late_penalty(cit["id"], CLERK), 200)
    # balance 29000 + 3000 = 32000; principal = 32000 + 2500 = 34500 over 7 terms
    plan = validate_success(
        api.create_installment_plan(
            cit["id"],
            create_installment_plan_payload(7, after_penalty["version"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    assert plan["principal_cents"] == 34500
    # base = floor(34500 / 7) = 4928; remainder = 34500 - 4928*7 = 4
    assert plan["installment_cents"] == 4928
    installments = list_installments_for_plan(plan["id"])
    amounts = [i["amount_cents"] for i in installments]
    assert amounts == [4928, 4928, 4928, 4928, 4928, 4928, 4932]


def test_installment_schedule_sums_to_principal(api):
    """PRD §3.5: "the sum of the scheduled installment amounts equals
    `principal_cents` exactly by construction, because the base covers every term
    and the remainder is folded into the last."

    Design: Difficulty/combinatorial_formula/installment_floor_base_with_remainder_to_final
    """
    # Jurisdiction A assessed_total 29000; principal = 29000 + 2500 = 31499? no:
    # principal = balance(29000) + setup 2500 = 31500 over term 4.
    jur, driver, cit, plan, installments = setup_citation_with_active_plan(term_count=4)
    total = sum(i["amount_cents"] for i in installments)
    assert total == plan["principal_cents"]


def test_installment_schedule_diverges_from_chronological_citation_balance(api):
    """PRD §3.4: "That balance is always the frozen `assessed_total_cents` plus
    accumulated `penalty_cents` minus `amount_paid_cents`, where `amount_paid_cents`
    is the chronological running sum of every `POSTED` payment for the citation,
    ordered by `posted_at` ascending; reversed payments are excluded from the sum."
    PRD §3.5: "The schedule is forward-looking and never mutates: the sum of the
    scheduled installment amounts equals `principal_cents` exactly by construction,
    because the base covers every term and the remainder is folded into the last."
    PRD §3.5: "The citation's `balance_cents`, by contrast, is the chronological
    applied view — it reflects only payments that have actually posted and diverges
    from the schedule the moment an installment is missed or only partially paid."

    Design: Difficulty/dual_variant_calc/installment_schedule_vs_chronological_citation_balance
    """
    # Citation with one charge base 19999 -> assessed_total 28999.
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    api.create_charge(
        create_charge_payload(
            cit["id"], description="Unsafe speed",
            base_fine_cents=19999, points=1,
        ),
        CLERK,
    )
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    assert assessed["balance_cents"] == 28999
    plan = validate_success(
        api.create_installment_plan(
            cit["id"],
            create_installment_plan_payload(4, assessed["version"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # principal = 28999 + 2500 = 31499; base floor(31499/4) = 7874; remainder 3 -> final 7877
    assert plan["principal_cents"] == 31499
    assert plan["installment_cents"] == 7874
    installments = list_installments_for_plan(plan["id"])
    inst1 = installments[0]
    # Pay installment 1 (7874).
    validate_success(
        api.create_payment(
            cit["id"],
            create_payment_payload(7874, method="CARD", installment_id=inst1["id"]),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    citation = validate_success(api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200)
    # chronological balance = 28999 - 7874 = 21125
    assert citation["balance_cents"] == 21125
    plan_after = validate_success(api.get_installment_plan(plan["id"], make_driver_headers(driver["id"])), 200)
    assert plan_after["principal_cents"] == 31499
    # remaining scheduled = 7874 + 7874 + 7877 = 23625 != 21125
    remaining = sum(
        i["amount_cents"]
        for i in list_installments_for_plan(plan["id"])
        if i["status"] == "SCHEDULED"
    )
    assert remaining == 23625
    assert citation["balance_cents"] != remaining


def test_installment_schedule_static_while_balance_moves(api):
    """PRD §3.5: "The plan schedule and the citation balance are deliberately two
    different views of the same debt."
    PRD §3.5: "The schedule stands still; the citation balance is what moves."

    Design: Difficulty/dual_variant_calc/installment_schedule_vs_chronological_citation_balance
    """
    jur, driver, cit, plan, installments = setup_citation_with_active_plan(term_count=4)
    principal_before = plan["principal_cents"]
    cents_before = plan["installment_cents"]
    # A free-form partial payment changes the chronological citation balance.
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(5000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    plan_after = validate_success(
        api.get_installment_plan(plan["id"], make_driver_headers(driver["id"])), 200
    )
    # Frozen schedule values are unchanged.
    assert plan_after["principal_cents"] == principal_before
    assert plan_after["installment_cents"] == cents_before
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    # Chronological balance moved (29000 - 5000 = 24000), diverging from the schedule.
    assert citation["balance_cents"] == 24000


def test_computed_balance_equals_assessed_total_after_assessment(api):
    """PRD §3.3: "The citation's `balance_cents` is set equal to
    `assessed_total_cents`, `financial_status` becomes `ASSESSED`, and the
    citation's `version` increases by one."

    Design: Corner/entities/computed_balance_ignores_client_supplied_balance
    """
    _, _, assessed = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    assert assessed["balance_cents"] == 29000
    assert assessed["base_fine_cents"] == 20000


def test_charge_recomputes_citation_base_fine(api):
    """PRD §3.3: "Each new charge recomputes the citation's `base_fine_cents` as the
    sum of its charges' base fines."

    Design: Corner/entities/computed_balance_ignores_client_supplied_balance
    """
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(create_citation_payload(driver["id"]), CLERK), 201
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.create_charge(
        create_charge_payload(
            cit["id"], violation_code="VC22107", description="Turn",
            base_fine_cents=5000, points=0,
        ),
        CLERK,
    )
    refreshed = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert refreshed["base_fine_cents"] == 25000
