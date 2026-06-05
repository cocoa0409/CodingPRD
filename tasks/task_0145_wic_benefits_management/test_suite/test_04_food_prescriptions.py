"""Food prescription issuance: per-category cap, FULL vs PRORATED rounding order,
the category-food mismatch gate, the EBT top-up, and OCC on participant version
(PRD §3.7, §2.7).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_certified_participant,
    setup_certified_with_prescription_and_redemption,
    get_participant_version,
    make_cpa_headers,
)

CPA1 = make_cpa_headers("cpa-1")

# A PREGNANT FULL package of MILK6/EGGS2/JUICE3 caps MILK at 4 and JUICE at 2:
# 4*350 + 2*300 + 2*250 = 2500 cents.
PREG_LINE_ITEMS = [
    {"food_category": "MILK", "requested_units": 6},
    {"food_category": "EGGS", "requested_units": 2},
    {"food_category": "JUICE", "requested_units": 3},
]


class TestPrescribedValue:
    def test_full_value_applies_min_cap_per_item(self, api):
        """PRD §3.7: "The number of units actually issued for a line item is the
        smaller of the requested units and that category cap. Under FULL issuance
        the issued units equal that capped number directly."
        PRD §3.7: "A PREGNANT participant may receive up to 4 MILK, 2 EGGS, 2
        JUICE, 3 CEREAL, and 11 FRUIT_VEG."
        PRD §3.7: "MILK 350, EGGS 300, JUICE 250".

        Design: Difficulty/combinatorial_formula/prescribed_value_min_cap_three_inputs
        """
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="SNAP",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2002",
        )
        rx = validate_success(api.create_food_prescription(
            {
                "certification_id": ctx["certification"]["id"],
                "issuance_mode": "FULL",
                "line_items": PREG_LINE_ITEMS,
                "expected_participant_version": ctx["participant"]["version"],
            },
            CPA1,
        ), 201)
        assert rx["prescribed_value_cents"] == 2500, (
            f"capped FULL value expected 2500, got {rx['prescribed_value_cents']}"
        )

    def test_full_issuance_caps_balance_units_per_category(self, api):
        """PRD §3.7: "the issued units are added to the per-category balance_units
        map".
        PRD §3.7: "The number of units actually issued for a line item is the
        smaller of the requested units and that category cap. Under FULL issuance
        the issued units equal that capped number directly."
        PRD §3.7: "A PREGNANT participant may receive up to 4 MILK, 2 EGGS, 2
        JUICE, 3 CEREAL, and 11 FRUIT_VEG."

        Design: Difficulty/combinatorial_formula/prescribed_value_min_cap_three_inputs
        """
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="SNAP",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2032",
        )
        validate_success(api.create_food_prescription(
            {
                "certification_id": ctx["certification"]["id"],
                "issuance_mode": "FULL",
                "line_items": PREG_LINE_ITEMS,
                "expected_participant_version": ctx["participant"]["version"],
            },
            CPA1,
        ), 201)
        ebts, _ = validate_paginated(
            api.list_ebt_accounts(CPA1, params={"participant_id": ctx["participant"]["id"]})
        )
        balance = ebts[0]["balance_units"]
        # MILK requested 6 capped to 4; EGGS 2; JUICE requested 3 capped to 2
        assert balance.get("MILK") == 4
        assert balance.get("EGGS") == 2
        assert balance.get("JUICE") == 2

    def test_prorated_floors_per_item_then_sums(self, api):
        """PRD §3.7: "Under PRORATED issuance the issued units are prorated by how
        much of the issuance month remains: the server computes the number of days
        in the calendar month of the agency's current_utc, computes the days
        remaining as that month length minus the day-of-month of current_utc plus
        one (inclusive of the current day), forms the factor as days-remaining
        divided by days-in-month, multiplies the capped units by that factor, and
        floors the result to a whole number of units."
        PRD §3.7: "under proration the per-item floor is applied before pricing,
        and only then are the item values summed".

        Design: Difficulty/combinatorial_formula/prorated_floor_per_item_then_sum
        """
        # clock 2026-03-20: March has 31 days, days_remaining = 31-20+1 = 12,
        # factor 12/31. MILK floor(4*12/31)=1 -> 350; EGGS floor(2*12/31)=0;
        # JUICE floor(2*12/31)=0. Total = 350.
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="TANF",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")],
            clock_iso="2026-03-20T00:00:00.000Z", ssn_last4="2003",
        )
        rx = validate_success(api.create_food_prescription(
            {
                "certification_id": ctx["certification"]["id"],
                "issuance_mode": "PRORATED",
                "line_items": PREG_LINE_ITEMS,
                "expected_participant_version": ctx["participant"]["version"],
            },
            CPA1,
        ), 201)
        assert rx["prescribed_value_cents"] == 350, (
            f"PRORATED floor-per-item value expected 350, got {rx['prescribed_value_cents']}"
        )

    def test_prorated_balance_units_reflect_floored_units(self, api):
        """PRD §3.7: "multiplies the capped units by that factor, and floors the
        result to a whole number of units."
        PRD §3.7: "the issued units are added to the per-category balance_units
        map".

        Design: Difficulty/combinatorial_formula/prorated_floor_per_item_then_sum
        """
        # clock 2026-03-20, factor 12/31: MILK floor(4*12/31)=1, EGGS/JUICE floor to 0
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="TANF",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")],
            clock_iso="2026-03-20T00:00:00.000Z", ssn_last4="2033",
        )
        validate_success(api.create_food_prescription(
            {
                "certification_id": ctx["certification"]["id"],
                "issuance_mode": "PRORATED",
                "line_items": PREG_LINE_ITEMS,
                "expected_participant_version": ctx["participant"]["version"],
            },
            CPA1,
        ), 201)
        ebts, _ = validate_paginated(
            api.list_ebt_accounts(CPA1, params={"participant_id": ctx["participant"]["id"]})
        )
        balance = ebts[0]["balance_units"]
        assert balance.get("MILK") == 1, f"MILK floored units expected 1, got {balance.get('MILK')}"
        # EGGS and JUICE floor to 0 units — absent from or zero in the balance map
        assert balance.get("EGGS", 0) == 0
        assert balance.get("JUICE", 0) == 0


class TestPrescribedVsRedeemedDivergence:
    def test_forward_authorization_differs_from_drawdown(self, api):
        """PRD §3.7: "The prescription's prescribed_value_cents is the sum of the
        per-item values across all line items".
        PRD §3.8: "redeemed_value_cents is the cumulative value of redeemed units
        drawn down in chronological order".
        PRD §3.8: "remaining_value_cents equals issued_value_cents minus
        redeemed_value_cents minus voided_value_cents".

        Design: Difficulty/dual_variant_calc/prescribed_value_vs_ebt_redeemed_value_diverges
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["ANEMIA"],
            income_records=[(200000, "MONTHLY")], ssn_last4="2001",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        assert ctx["prescription"]["prescribed_value_cents"] == 2500
        ebt = ctx["ebt_account"]
        # 4 MILK redeemed -> 4*350 = 1400
        assert ebt["redeemed_value_cents"] == 1400
        assert ebt["remaining_value_cents"] == 1100

    def test_issued_total_equals_forward_authorization(self, api):
        """PRD §3.7: "Issuing the prescription tops up the participant's EbtAccount:
        the prescribed value is added to the account's issued_value_cents".
        PRD §3.8: "issued_value_cents is the cumulative value of all units issued
        onto the account across food prescriptions".

        Design: Difficulty/dual_variant_calc/prescribed_value_vs_ebt_redeemed_value_diverges
        """
        ctx = setup_certified_with_prescription_and_redemption(
            line_items=PREG_LINE_ITEMS, redeem_category="MILK", redeem_units=4,
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["ANEMIA"],
            income_records=[(200000, "MONTHLY")], ssn_last4="2021",
            clock_iso="2026-03-02T00:00:00.000Z",
        )
        ebt = ctx["ebt_account"]
        # forward authorization (issued) 2500 diverges from the chronological
        # draw-down (redeemed) 1400
        assert ebt["issued_value_cents"] == 2500
        assert ebt["redeemed_value_cents"] == 1400
        assert ebt["issued_value_cents"] != ebt["redeemed_value_cents"]


def test_category_food_mismatch_rejected(api):
    """PRD §3.7: "If a line item names a food_category for which the participant's
    category has no cap, the issuance is rejected with ERR_CATEGORY_FOOD_MISMATCH."

    Design: Corner/calculations/food_category_mismatch_for_category
    """
    ctx = setup_certified_participant(
        category="CHILD", adjunctive_program="SNAP", household_size=3,
        risk_factor_codes=["ANEMIA"], income_records=[(100000, "MONTHLY")],
        clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="4446",
    )
    p_ver = get_participant_version(ctx["participant"]["id"])
    resp = api.create_food_prescription(
        {
            "certification_id": ctx["certification"]["id"],
            "issuance_mode": "FULL",
            "line_items": [{"food_category": "INFANT_FORMULA", "requested_units": 5}],
            "expected_participant_version": p_ver,
        },
        CPA1,
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_FOOD_MISMATCH.value)


def test_stale_participant_version_on_second_issuance_rejected(api):
    """PRD §2.7: "Issuing a food prescription requires expected_participant_version
    in the request body, carrying the client's last observed version of the
    Participant."
    PRD §2.7: "If expected_participant_version does not match the participant's
    current version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_participant_version_on_food_prescription
    """
    ctx = setup_certified_participant(
        category="PREGNANT", adjunctive_program="MEDICAID",
        household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
        income_records=[(150000, "MONTHLY")],
        clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="1515",
    )
    p_ver_pre = get_participant_version(ctx["participant"]["id"])
    # first issuance bumps participant.version
    validate_success(api.create_food_prescription(
        {
            "certification_id": ctx["certification"]["id"],
            "issuance_mode": "FULL",
            "line_items": [{"food_category": "MILK", "requested_units": 4}],
            "expected_participant_version": p_ver_pre,
        },
        CPA1,
    ), 201)
    # second issuance reuses the stale pre-issuance version
    resp = api.create_food_prescription(
        {
            "certification_id": ctx["certification"]["id"],
            "issuance_mode": "FULL",
            "line_items": [{"food_category": "EGGS", "requested_units": 2}],
            "expected_participant_version": p_ver_pre,
        },
        CPA1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
