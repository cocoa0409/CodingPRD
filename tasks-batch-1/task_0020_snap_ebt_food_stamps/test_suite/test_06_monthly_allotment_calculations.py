"""Monthly allotment calculation tests: STANDARD vs EMERGENCY variant on the
same month, the round-then-subtract precision rule, the size-1/2 minimum
floor, the emergency-supplement min-floor branch, and the net-income clamp.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock, create_household, add_member,
    create_and_submit_application, approve_application,
    setup_household_with_active_card,
    create_monthly_allotment, issue_monthly_allotment,
    adjust_monthly_allotment, current_household_version,
    setup_active_proclamation,
)

CW = TEST_USERS["caseworker_headers"]
BI = TEST_USERS["benefit_issuer_headers"]


# ─── Difficulty / dual_variant_calc / monthly_allotment_standard_vs_emergency_on_same_month ──

def test_standard_then_emergency_adjust_yields_expected_supplement(api):
    """For a size-2 household in CA with net_income_cents=108200, the
    STANDARD variant alone produces standard=21040, emergency=0,
    issued_total=21040. After activating a state-CA proclamation for the
    benefit_month and calling /adjust on the ISSUED allotment, EMERGENCY
    contributes emergency=max(min_supplement_cents=9500, gap=53500-21040
    =32460)=32460 → standard_allotment_cents unchanged at 21040,
    emergency_supplement_cents=32460, issued_total_cents=53500.

    PRD §3.4: "The monthly-allotment calculation runs on `MonthlyAllotment`
    create, on issue, and on adjust. Its standard variant is computed every
    time. First, the effective size is the larger of 1 and the household's
    `size`. Second, the maximum allotment is read from a per-size tier
    table — 29,100 cents for size 1, 53,500 cents for size 2, 76,600 cents
    for size 3, 97,300 cents for size 4, 115,500 cents for size 5, and
    138,600 cents for size 6 — plus, for households larger than 6, an
    additional 21,100 cents per person beyond 6."
    PRD §3.4: "The emergency variant only contributes when an
    `EmergencyAllotmentProclamation` whose `status` is `ACTIVE` exists for
    the matching `state_code` and `benefit_month`. In that case the
    supplement is the larger of two values: the proclamation's
    `min_supplement_cents` (defaulting to 9,500 cents, $95.00, the
    federally mandated floor) and the gap between the maximum allotment
    and the standard allotment just computed. The result is written to
    `emergency_supplement_cents`."
    PRD §3.5: "After an allotment is `ISSUED`, a new proclamation may take
    effect for the household's `(state_code, benefit_month)`. Adjustment,
    also exclusive to the `BenefitIssuer` role, advances the allotment from
    `ISSUED` to `ADJUSTED`. It requires that the allotment is in `ISSUED`
    and that an `EmergencyAllotmentProclamation` reached `ACTIVE` for the
    household's `state_code` and the allotment's `benefit_month` after
    the allotment's `issued_at` timestamp. On success,
    `emergency_supplement_cents` is re-derived from §3.4 (and can only
    increase, because a proclamation has been added) and
    `issued_total_cents` is recomputed; `standard_allotment_cents` is left
    as it was at issuance and is not re-derived."

    Design: Difficulty/dual_variant_calc/monthly_allotment_standard_vs_emergency_on_same_month
    """
    set_clock("2026-07-01T00:00:00Z")
    hh = create_household(case_number="CA-100001", state_code="CA",
                          address_line="1 Main St", heap_recipient=False)
    add_member(hh["id"], full_name="M One", date_of_birth="1980-01-01",
               relationship="HEAD", monthly_earned_income_cents=160000,
               disabled=True)
    add_member(hh["id"], full_name="M Two", date_of_birth="1982-01-01",
               relationship="SPOUSE", monthly_earned_income_cents=0,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    validate_success(api.activate_ebt_card(cards[0]["id"], CW), 200)

    ma = create_monthly_allotment(hh["id"], "2026-07")
    assert ma["standard_allotment_cents"] == 21040, (
        f"pre-adjust standard must be 21040 (size-2 STANDARD on net=108200), "
        f"got {ma['standard_allotment_cents']}"
    )
    assert ma["emergency_supplement_cents"] == 0, (
        f"pre-adjust emergency must be 0 (no ACTIVE proclamation), "
        f"got {ma['emergency_supplement_cents']}"
    )
    assert ma["issued_total_cents"] == 21040

    hh_v = current_household_version(hh["id"])
    issue_monthly_allotment(ma["id"], hh_v)
    # Advance the clock so the proclamation activation timestamp is strictly
    # AFTER the allotment's issued_at, per PRD §3.5 "reached ACTIVE ... after
    # the allotment's issued_at timestamp".
    set_clock("2026-07-01T00:00:01Z")
    # Activate a proclamation AFTER issuance for (CA, 2026-07).
    setup_active_proclamation("CA", "2026-07", min_supplement_cents=9500)
    adjusted = adjust_monthly_allotment(ma["id"])
    assert adjusted["standard_allotment_cents"] == 21040, (
        f"post-adjust standard MUST stay at 21040 (PRD §3.5 forbids "
        f"re-deriving standard on adjust), got {adjusted['standard_allotment_cents']}"
    )
    assert adjusted["emergency_supplement_cents"] == 32460, (
        f"post-adjust emergency must be max(9500, gap=32460)=32460, "
        f"got {adjusted['emergency_supplement_cents']}"
    )
    assert adjusted["issued_total_cents"] == 53500


def test_no_active_proclamation_yields_zero_emergency_supplement(api):
    """When no ACTIVE proclamation matches the household's (state_code,
    benefit_month), the EMERGENCY variant contributes 0 — STANDARD is the
    entire allotment. This is the negative branch of the dual-variant rule
    and confirms the variant gate is keyed on proclamation status, not on
    the existence of the state at all.

    PRD §3.4: "The emergency variant only contributes when an
    `EmergencyAllotmentProclamation` whose `status` is `ACTIVE` exists for
    the matching `state_code` and `benefit_month`. In that case the
    supplement is the larger of two values: the proclamation's
    `min_supplement_cents` (defaulting to 9,500 cents, $95.00, the
    federally mandated floor) and the gap between the maximum allotment
    and the standard allotment just computed. The result is written to
    `emergency_supplement_cents`. When no `ACTIVE` proclamation matches,
    `emergency_supplement_cents` is 0. In either case, `issued_total_cents`
    is the sum of `standard_allotment_cents` and `emergency_supplement_cents`."

    Design: Difficulty/dual_variant_calc/monthly_allotment_standard_vs_emergency_on_same_month
    """
    set_clock("2026-07-01T00:00:00Z")
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-100002", state_code="CA",
        clock_iso="2026-07-01T00:00:00Z",
    )
    ma = create_monthly_allotment(hh["id"], "2026-07")
    assert ma["emergency_supplement_cents"] == 0, (
        f"without ACTIVE proclamation, emergency must be 0, "
        f"got {ma['emergency_supplement_cents']}"
    )
    assert ma["issued_total_cents"] == ma["standard_allotment_cents"], (
        f"issued_total must equal standard when emergency is 0; "
        f"std={ma['standard_allotment_cents']}, "
        f"emerg={ma['emergency_supplement_cents']}, "
        f"total={ma['issued_total_cents']}"
    )


# ─── Difficulty / combinatorial_formula / monthly_allotment_round_then_subtract_pinned ──

def test_size3_round_then_subtract_yields_pinned_value(api):
    """For size=3, gross=200001 (single earner, two disabled members), the
    sequence is: gross=200001 → earned_ded=floor(200001*0.20)=40000 →
    standard_deduction[3]=19800 → net=140201. Then standard =
    max_allotment[3]=76600 minus floor(140201*0.30)=42060 = 34540. The
    rejected subtract-then-floor order would give 34539; PRD §3.4 pins
    round-then-subtract.

    PRD §3.4: "The order is mandatory: the 30% product is truncated
    first, and the subtraction is performed second; truncating after
    subtraction would yield a different cent value and is not permitted."
    PRD §3.4: "Third, thirty percent of `Household.net_income_cents` is
    computed and truncated toward zero (equivalent to the floor of the
    cent-valued product); this is the benefit reduction. Fourth, the
    standard allotment is the maximum allotment minus the benefit
    reduction, but for households of size 1 or 2 it cannot drop below
    the minimum of 2,300 cents ($23.00). The result is written to
    `MonthlyAllotment.standard_allotment_cents`."

    Design: Difficulty/combinatorial_formula/monthly_allotment_round_then_subtract_pinned
    """
    set_clock("2026-07-01T00:00:00Z")
    hh = create_household(case_number="NY-300001", state_code="NY",
                          address_line="3 Pine Rd", heap_recipient=False)
    add_member(hh["id"], full_name="Earner", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=200001,
               disabled=True)
    add_member(hh["id"], full_name="Spouse", date_of_birth="1972-01-01",
               relationship="SPOUSE", monthly_earned_income_cents=0,
               disabled=True)
    add_member(hh["id"], full_name="Child A",
               date_of_birth="2015-01-01", relationship="CHILD")
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"], decision_reason="Income within limits")
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    validate_success(api.activate_ebt_card(cards[0]["id"], CW), 200)

    ma = create_monthly_allotment(hh["id"], "2026-07")
    assert ma["standard_allotment_cents"] == 34540, (
        f"round-then-subtract pinning must yield 34540 (NOT 34539); "
        f"got {ma['standard_allotment_cents']}"
    )
    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_after["net_income_cents"] == 140201, (
        f"BENEFIT_CALC net for gross=200001, size=3, heap=false must be "
        f"140201, got {hh_after['net_income_cents']}"
    )


def test_round_then_subtract_value_never_takes_subtract_then_round_form(api):
    """The same household; the asserted standard MUST NOT take the value
    associated with the rejected subtract-then-round order (34539). This is
    the complementary check that the implementation is on the right branch
    of the precision rule.

    PRD §3.4: "The order is mandatory: the 30% product is truncated
    first, and the subtraction is performed second; truncating after
    subtraction would yield a different cent value and is not permitted."

    Design: Difficulty/combinatorial_formula/monthly_allotment_round_then_subtract_pinned
    """
    set_clock("2026-08-01T00:00:00Z")
    hh = create_household(case_number="NY-300002", state_code="NY",
                          address_line="3a Pine Rd", heap_recipient=False)
    add_member(hh["id"], full_name="Earner", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=200001,
               disabled=True)
    add_member(hh["id"], full_name="Spouse", date_of_birth="1972-01-01",
               relationship="SPOUSE", monthly_earned_income_cents=0,
               disabled=True)
    add_member(hh["id"], full_name="Child A",
               date_of_birth="2015-01-01", relationship="CHILD")
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"], decision_reason="ok")
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    validate_success(api.activate_ebt_card(cards[0]["id"], CW), 200)
    ma = create_monthly_allotment(hh["id"], "2026-08")
    assert ma["standard_allotment_cents"] != 34539, (
        "subtract-then-round would yield 34539; the implementation must use "
        "the PRD-mandated round-then-subtract order."
    )


# ─── Corner / calculations / net_income_zero_when_deductions_exceed_gross ──

def test_net_income_clamped_at_zero_when_deductions_exceed_gross(api):
    """A size-1 household with earned=5000 has gross=5000 and total
    deductions = floor(5000*0.20) + 19800 = 1000 + 19800 = 20800. PRD
    §3.4's max(0, gross-deductions) clamps Household.net_income_cents to 0.

    PRD §3.4: "Sixth, net income is the larger of 0 and gross income
    minus total deductions; this value is written to
    `Household.net_income_cents`. Apart from the single truncation step
    on the earned-income deduction, no other rounding occurs."

    Design: Corner/calculations/net_income_zero_when_deductions_exceed_gross
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-100003", state_code="CA",
                          address_line="X", heap_recipient=False)
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=5000,
               disabled=True)
    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_after["gross_income_cents"] == 5000, \
        f"gross must equal sum of earned ACTIVE-member income, got {hh_after['gross_income_cents']}"
    assert hh_after["net_income_cents"] == 0, (
        f"net must clamp at 0 when deductions exceed gross, "
        f"got {hh_after['net_income_cents']}"
    )


# ─── Corner / calculations / monthly_allotment_min_floor_2300_for_size_1_high_income ──

def test_min_floor_2300_applies_for_size_1_high_income(api):
    """Construct a size-1 household whose net produces a negative
    max_allotment - 30%*net subtraction. PRD §3.4 floors the result at
    2300 for size 1 or 2.

    Numerically: gross=169125 (heap=false). earned_ded=floor(33825)=33825.
    standard_ded[1]=19800. SUA=0. net=169125-33825-19800=115500. Since
    LIMIT_CHECK==BENEFIT_CALC under heap=false and 115500<=117500, the
    approve precondition passes. Then standard = max(2300, 29100-
    floor(0.3*115500)) = max(2300, 29100-34650) = max(2300, -5550) = 2300.

    PRD §3.4: "Fourth, the standard allotment is the maximum allotment
    minus the benefit reduction, but for households of size 1 or 2 it
    cannot drop below the minimum of 2,300 cents ($23.00). The result
    is written to `MonthlyAllotment.standard_allotment_cents`."

    Design: Corner/calculations/monthly_allotment_min_floor_2300_for_size_1_high_income
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-100004", state_code="CA",
                          address_line="X", heap_recipient=False)
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=169125,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    hh_after = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_after["net_income_cents"] == 115500, (
        f"sanity: net for size=1, gross=169125, heap=false must be 115500, "
        f"got {hh_after['net_income_cents']}"
    )
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    validate_success(api.activate_ebt_card(cards[0]["id"], CW), 200)
    ma = create_monthly_allotment(hh["id"], "2026-09")
    assert ma["standard_allotment_cents"] == 2300, (
        f"standard must be floored at 2300 for size 1, got {ma['standard_allotment_cents']}"
    )


# ─── Corner / calculations / emergency_supplement_uses_min_floor_when_gap_smaller ──

def test_emergency_uses_min_floor_when_gap_is_zero(api):
    """For size=1, net=0, heap=false: standard = max(2300, 29100-0) =
    29100. gap = max_allotment - standard = 29100 - 29100 = 0. With a
    proclamation min_supplement_cents=9500 active, EMERGENCY supplement =
    max(9500, 0) = 9500. issued_total_cents = 29100 + 9500 = 38600.

    PRD §3.4: "The emergency variant only contributes when an
    `EmergencyAllotmentProclamation` whose `status` is `ACTIVE` exists for
    the matching `state_code` and `benefit_month`. In that case the
    supplement is the larger of two values: the proclamation's
    `min_supplement_cents` (defaulting to 9,500 cents, $95.00, the
    federally mandated floor) and the gap between the maximum allotment
    and the standard allotment just computed. The result is written to
    `emergency_supplement_cents`."

    Design: Corner/calculations/emergency_supplement_uses_min_floor_when_gap_smaller
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="CA-100005", state_code="CA",
                          address_line="X", heap_recipient=False)
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=0,
               disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    setup_active_proclamation("CA", "2026-09", min_supplement_cents=9500)
    ma = create_monthly_allotment(hh["id"], "2026-09")
    assert ma["standard_allotment_cents"] == 29100, \
        f"standard for size=1, net=0 must be 29100, got {ma['standard_allotment_cents']}"
    assert ma["emergency_supplement_cents"] == 9500, (
        f"emergency must be max(min_supplement=9500, gap=0)=9500, "
        f"got {ma['emergency_supplement_cents']}"
    )
    assert ma["issued_total_cents"] == 38600, (
        f"issued_total = standard + emergency = 29100 + 9500 = 38600, "
        f"got {ma['issued_total_cents']}"
    )
