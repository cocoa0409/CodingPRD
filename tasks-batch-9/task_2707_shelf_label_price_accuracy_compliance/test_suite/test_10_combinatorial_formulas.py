"""Formulas whose inputs interact: one division then one rounding, tiered penalties, pinned settlement."""

from test_helpers import (
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    expected_assessed_penalty_cents,
    expected_penalty_component_cents,
    expected_penalty_exposure_cents,
    expected_refund_credit_cents,
    expected_unit_price_display_cents,
    factories,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ERR_PENALTY_OVERRIDE_TOO_HIGH
from test_helpers.constants import (
    PENALTY_ITEM_CAP,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)

MATCHING_FILLER_CENTS = [299, 199, 399, 259]


def _one_overcharge_sample(sample_size, upc_prefix):
    """One OVERCHARGE line followed by ``sample_size - 1`` matching lines."""
    sample = [
        {
            "item_upc": upc_prefix + "1",
            "shelf_price_cents": 949,
            "register_price_cents": 1099,
        }
    ]
    for index in range(sample_size - 1):
        price = MATCHING_FILLER_CENTS[index]
        sample.append(
            {
                "item_upc": upc_prefix + str(index + 2),
                "shelf_price_cents": price,
                "register_price_cents": price,
            }
        )
    return sample


CHEDDAR_26_OZ = {
    "item_upc": "00000000000201",
    "item_description": "Cheddar block 26oz",
    "category_code": "DAIRY",
    "old_retail_cents": 549,
    "new_retail_cents": 499,
    "net_content_qty": 26,
    "net_content_uom": "OZ",
}
JUICE_48_FL_OZ = {
    "item_upc": "00000000000202",
    "item_description": "Juice 48 fl oz",
    "category_code": "DAIRY",
    "old_retail_cents": 1399,
    "new_retail_cents": 1299,
    "net_content_qty": 48,
    "net_content_uom": "FL_OZ",
}
BUTTER_12_OZ = {
    "item_upc": "00000000000203",
    "item_description": "Butter 12oz",
    "category_code": "DAIRY",
    "old_retail_cents": 1099,
    "new_retail_cents": 1000,
    "net_content_qty": 12,
    "net_content_uom": "OZ",
}
SINGLE_DONUT = {
    "item_upc": "00000000000204",
    "item_description": "Single donut",
    "category_code": "BAKERY",
    "old_retail_cents": 399,
    "new_retail_cents": 349,
    "net_content_qty": 1,
    "net_content_uom": "EACH",
}


class TestUnitPriceDividesBeforeRounding:
    def test_the_basis_stays_unrounded_so_twenty_six_ounces_prints_three_hundred_and_seven(
        self, build
    ):
        """Rounding the 1.625 LB basis first would print 306; the pinned order prints 307.

        PRD 3.3: "The computation has exactly one division and exactly one rounding,
        in that order, and the order is normative."
        PRD 3.3: "The first step selects the basis, and **nothing is rounded in this
        step**."
        PRD 3.3: "The two conversion constants are the sixteen ounces in a pound and
        the one hundred twenty-eight fluid ounces in a gallon."
        PRD 3.3: "Otherwise the second step performs the single division: the new
        retail in cents divided by the basis quantity, evaluated at full precision as
        an exact rational with no truncation."
        PRD 3.3: "The number of decimal places retained on the **cent** figure is the
        jurisdiction's `unit_price_decimal_places` reduced by two, and never less than
        zero — so a jurisdiction printing dollars to two places rounds the cent figure
        to a whole number, while one printing dollars to three places retains one
        decimal on the cent figure."
        PRD 3.3: "The rounded result is stored as `unit_price_display_cents`; the
        basis quantity is stored exactly as computed, never rounded, to as many as six
        fractional digits, as `unit_price_basis_qty`; and the basis label is stored as
        `unit_price_basis_uom`."

        Design: Difficulty/combinatorial_formula/unit_price_display_nested_rounding_order_divides_before_rounding
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            unit_price_uom_rule="PER_UNIT_MEASURE_CANONICAL",
            unit_price_decimal_places=2,
            unit_price_rounding="ROUND_HALF_UP",
            grace_period_hours=48,
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        record = build.price_change_file(
            jurisdiction_id,
            [store_id],
            "2026-08-03T00:00:00Z",
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        file_id = record["id"]

        cheddar = build.add_line(file_id, **CHEDDAR_26_OZ)
        assert cheddar["unit_price_basis_uom"] == "LB"
        assert float(cheddar["unit_price_basis_qty"]) == 1.625
        assert cheddar["unit_price_display_cents"] == 307
        assert cheddar["unit_price_display_cents"] != 306
        assert cheddar["unit_price_display_cents"] == expected_unit_price_display_cents(
            499, 26, "OZ"
        )

        juice = build.add_line(file_id, **JUICE_48_FL_OZ)
        assert juice["unit_price_basis_uom"] == "GAL"
        assert float(juice["unit_price_basis_qty"]) == 0.375
        assert juice["unit_price_display_cents"] == 3464
        assert juice["unit_price_display_cents"] == expected_unit_price_display_cents(
            1299, 48, "FL_OZ"
        )

        butter = build.add_line(file_id, **BUTTER_12_OZ)
        assert butter["unit_price_basis_uom"] == "LB"
        assert float(butter["unit_price_basis_qty"]) == 0.75
        assert butter["unit_price_display_cents"] == 1333
        assert butter["unit_price_display_cents"] == expected_unit_price_display_cents(
            1000, 12, "OZ"
        )

        donut = build.add_line(file_id, **SINGLE_DONUT)
        assert donut["unit_price_basis_uom"] == "EACH"
        assert float(donut["unit_price_basis_qty"]) == 1
        assert donut["unit_price_display_cents"] == 349

        assert build.read_file(file_id)["line_count"] == 4

    def test_the_retained_cent_decimal_and_the_rounding_mode_move_only_the_quotient(
        self, build
    ):
        """Three decimal places keep one cent decimal; ceiling lifts the same quotient by a cent.

        PRD 3.3: "The computation has exactly one division and exactly one rounding,
        in that order, and the order is normative."
        PRD 3.3: "The first step selects the basis, and **nothing is rounded in this
        step**."
        PRD 3.3: "The number of decimal places retained on the **cent** figure is the
        jurisdiction's `unit_price_decimal_places` reduced by two, and never less than
        zero — so a jurisdiction printing dollars to two places rounds the cent figure
        to a whole number, while one printing dollars to three places retains one
        decimal on the cent figure."
        PRD 3.3: "The rounding mode is the jurisdiction's own `unit_price_rounding`,
        either half up or ceiling."
        PRD 3.3: "Three fields on every line — `unit_price_display_cents`,
        `unit_price_basis_qty` and `unit_price_basis_uom` — are derived from the line's
        net content and the jurisdiction's display rulebook, and they are computed the
        moment the line is created and recomputed for every live line when the batch is
        distributed."

        Design: Difficulty/combinatorial_formula/unit_price_display_nested_rounding_order_divides_before_rounding
        """
        arms = {}
        for code, name, store_number, decimal_places, rounding in (
            ("US-CA", "California", "S001", 3, "ROUND_HALF_UP"),
            ("US-NY", "New York", "S002", 2, "ROUND_CEILING"),
        ):
            jurisdiction_id = build.jurisdiction(
                code=code,
                name=name,
                unit_price_uom_rule="PER_UNIT_MEASURE_CANONICAL",
                unit_price_decimal_places=decimal_places,
                unit_price_rounding=rounding,
            )
            store_id = build.store(
                jurisdiction_id, store_number=store_number, name="Bay Street"
            )
            record = build.price_change_file(
                jurisdiction_id,
                [store_id],
                "2026-08-03T00:00:00Z",
                file_number="PCF-" + code,
                priority="ROUTINE",
            )
            cheddar = build.add_line(record["id"], **CHEDDAR_26_OZ)
            butter = build.add_line(record["id"], **BUTTER_12_OZ)
            distributed = build.distribute(record["id"])
            assert distributed["status"] == "DISTRIBUTED"
            arms[rounding] = {
                "file_id": record["id"],
                "cheddar": cheddar,
                "butter": butter,
                "cheddar_after": build.read_line(cheddar["id"]),
                "butter_after": build.read_line(butter["id"]),
                "decimal_places": decimal_places,
            }

        half_up = arms["ROUND_HALF_UP"]
        assert float(half_up["cheddar"]["unit_price_basis_qty"]) == 1.625
        assert half_up["cheddar"]["unit_price_basis_uom"] == "LB"
        assert float(half_up["cheddar"]["unit_price_display_cents"]) == 307.1
        assert float(
            half_up["cheddar"]["unit_price_display_cents"]
        ) == expected_unit_price_display_cents(
            499, 26, "OZ", decimal_places=3, rounding="ROUND_HALF_UP"
        )
        assert float(half_up["butter"]["unit_price_display_cents"]) == 1333.3
        assert float(
            half_up["butter"]["unit_price_display_cents"]
        ) == expected_unit_price_display_cents(
            1000, 12, "OZ", decimal_places=3, rounding="ROUND_HALF_UP"
        )

        ceiling = arms["ROUND_CEILING"]
        assert float(ceiling["cheddar"]["unit_price_basis_qty"]) == 1.625
        assert ceiling["cheddar"]["unit_price_display_cents"] == 308
        assert ceiling["cheddar"][
            "unit_price_display_cents"
        ] == expected_unit_price_display_cents(
            499, 26, "OZ", decimal_places=2, rounding="ROUND_CEILING"
        )
        assert ceiling["butter"]["unit_price_display_cents"] == 1334
        assert ceiling["butter"][
            "unit_price_display_cents"
        ] == expected_unit_price_display_cents(
            1000, 12, "OZ", decimal_places=2, rounding="ROUND_CEILING"
        )

        for arm in arms.values():
            for key in ("cheddar", "butter"):
                before = arm[key]
                after = arm[key + "_after"]
                assert (
                    after["unit_price_display_cents"]
                    == before["unit_price_display_cents"]
                )
                assert float(after["unit_price_basis_qty"]) == float(
                    before["unit_price_basis_qty"]
                )
                assert after["unit_price_basis_uom"] == before["unit_price_basis_uom"]


def _by_code_and_count(rows):
    """Findings keyed by ``(finding_code, affected_item_count)`` — list order is not declared."""
    return {(row["finding_code"], row["affected_item_count"]): row for row in rows}


class TestPenaltyExposureInteractions:
    def test_the_item_cap_the_tier_the_aggravator_and_the_ceiling_all_bite_at_once(
        self, api, build, officer_headers
    ):
        """Raw 150000 scales by 150 to 225000 and is clamped to 200000; a waiver drops the tier.

        PRD 3.7: "Each considered finding's `penalty_component_cents` is its severity
        weight — 1 for `MINOR`, 3 for `MAJOR`, 8 for `CRITICAL` — multiplied by the
        jurisdiction's `penalty_per_violation_cents`, multiplied by the smaller of the
        finding's `affected_item_count` and the per-finding item cap of 10."
        PRD 3.7: "The **tier multiplier** is 100 percentage points when the considered
        set holds at most 2 findings, 125 when it holds at most 5, and 150 beyond that."
        PRD 3.7: "An **audit aggravator** of 25 percentage points is added when the
        referenced evidence audit's outcome is `FAIL`, and 0 percentage points
        otherwise."
        PRD 3.7: "The exposure finally stored as `penalty_exposure_cents` is the
        smaller of the scaled total and the jurisdiction's `penalty_max_cents`."
        PRD 3.7: "Waiving is the branch with the widest financial reach: the reason is
        stored, the finding's `penalty_component_cents` is zeroed, the owning
        inspection's `finding_count` and `penalty_exposure_cents` are recomputed — and
        because the waived finding leaves the considered set, that recomputation can
        select a **lower** tier multiplier, so waiving the third finding of three moves
        the tier from 125 back to 100 and reduces the exposure by more than the waived
        finding's own component."

        Design: Difficulty/combinatorial_formula/penalty_exposure_tier_item_cap_aggravator_and_ceiling_interact
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
            penalty_per_violation_cents=5000,
            penalty_max_cents=200000,
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        evidence = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            _one_overcharge_sample(4, "0000000000010"),
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert_pct(evidence["audit"]["error_rate_pct"], 25.00)
        assert evidence["audit"]["outcome"] == "FAIL"

        issued = build.inspection_with_findings(
            store_id,
            evidence["audit_id"],
            [
                factories.finding_input("SHELF_TAG_MISMATCH", "MAJOR", 4, "A01"),
                factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 12, "A01"),
                factories.finding_input("EXPIRED_SIGNAGE", "CRITICAL", 1, "A01"),
            ],
            inspector_ref="INSP-9001",
            inspection_date="2026-08-02T09:00:00Z",
        )
        inspection = issued["inspection"]
        assert inspection["status"] == "FINDINGS_ISSUED"
        assert inspection["finding_count"] == 3
        assert_money_cents(inspection["penalty_exposure_cents"], 200000)
        assert_money_cents(
            inspection["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [
                    {"severity": "MAJOR", "affected_item_count": 4},
                    {"severity": "MINOR", "affected_item_count": 12},
                    {"severity": "CRITICAL", "affected_item_count": 1},
                ],
                5000,
                200000,
                True,
            ),
        )

        rows, meta = validate_paginated(
            api.list_inspection_findings(issued["inspection_id"], officer_headers)
        )
        assert meta["total_count"] == 3
        findings = _by_code_and_count(rows)
        major = findings[("SHELF_TAG_MISMATCH", 4)]
        minor = findings[("UNIT_PRICE_FORMAT", 12)]
        critical = findings[("EXPIRED_SIGNAGE", 1)]
        assert_money_cents(major["penalty_component_cents"], 60000)
        assert_money_cents(minor["penalty_component_cents"], 50000)
        assert minor["penalty_component_cents"] != 60000
        assert_money_cents(critical["penalty_component_cents"], 40000)
        assert_money_cents(
            minor["penalty_component_cents"],
            expected_penalty_component_cents("MINOR", 5000, PENALTY_ITEM_CAP),
        )

        waived = build.transition_finding(
            minor["id"],
            "WAIVED",
            waiver_reason="Unit price format corrected before inspection closed",
        )
        assert waived["status"] == "WAIVED"
        assert_money_cents(waived["penalty_component_cents"], 0)

        after = build.read_inspection(issued["inspection_id"])
        assert after["finding_count"] == 2
        assert_money_cents(after["penalty_exposure_cents"], 125000)
        assert_money_cents(
            after["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [
                    {"severity": "MAJOR", "affected_item_count": 4},
                    {"severity": "CRITICAL", "affected_item_count": 1},
                ],
                5000,
                200000,
                True,
            ),
        )
        assert_money_cents(
            build.read_finding(major["id"])["penalty_component_cents"], 60000
        )
        assert_money_cents(
            build.read_finding(critical["id"])["penalty_component_cents"], 40000
        )

    def test_one_floor_after_the_sum_beats_per_finding_floors_across_the_tier_ladder(
        self, api, build, officer_headers
    ):
        """A seven-cent unit makes the scaled total fractional at tiers 150 and 125.

        PRD 3.7: "Each considered finding's `penalty_component_cents` is its severity
        weight — 1 for `MINOR`, 3 for `MAJOR`, 8 for `CRITICAL` — multiplied by the
        jurisdiction's `penalty_per_violation_cents`, multiplied by the smaller of the
        finding's `affected_item_count` and the per-finding item cap of 10."
        PRD 3.7: "The raw total is the sum of those components, taken **before** any
        scaling."
        PRD 3.7: "The scaled total is that raw total multiplied by the tier multiplier
        plus the aggravator, divided by 100, with a single **floor** applied to the
        result — one floor, after the sum, never per finding, because per-finding
        floors would lose up to one cent per finding."
        PRD 3.7: "An **audit aggravator** of 25 percentage points is added when the
        referenced evidence audit's outcome is `FAIL`, and 0 percentage points
        otherwise."
        PRD 3.7: "The **tier multiplier** is 100 percentage points when the considered
        set holds at most 2 findings, 125 when it holds at most 5, and 150 beyond that."

        Design: Difficulty/combinatorial_formula/penalty_exposure_tier_item_cap_aggravator_and_ceiling_interact
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=60.0,
            default_rate_variant="GROSS_MISMATCH",
            penalty_per_violation_cents=7,
            penalty_max_cents=2000000,
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        evidence = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            _one_overcharge_sample(4, "0000000000011"),
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert_pct(evidence["audit"]["error_rate_pct"], 25.00)
        assert evidence["audit"]["outcome"] == "PASS"

        severities = [
            ("UNIT_PRICE_FORMAT", "MINOR", 10),
            ("UNIT_PRICE_FORMAT", "MINOR", 11),
            ("SHELF_TAG_MISMATCH", "CRITICAL", 1),
            ("SIGNAGE_DISCLOSURE", "MINOR", 1),
            ("EXPIRED_SIGNAGE", "MINOR", 1),
            ("SCANNER_ERROR_RATE", "MINOR", 1),
        ]
        issued = build.inspection_with_findings(
            store_id,
            evidence["audit_id"],
            [
                factories.finding_input(code, severity, count, "A01")
                for code, severity, count in severities
            ],
            inspector_ref="INSP-9002",
            inspection_date="2026-08-02T09:00:00Z",
        )
        inspection = issued["inspection"]
        assert inspection["finding_count"] == 6
        assert_money_cents(inspection["penalty_exposure_cents"], 325)
        assert inspection["penalty_exposure_cents"] != 324
        assert_money_cents(
            inspection["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [
                    {"severity": severity, "affected_item_count": count}
                    for _code, severity, count in severities
                ],
                7,
                2000000,
                False,
            ),
        )

        rows, meta = validate_paginated(
            api.list_inspection_findings(issued["inspection_id"], officer_headers)
        )
        assert meta["total_count"] == 6
        findings = _by_code_and_count(rows)
        capped_at_ten = findings[("UNIT_PRICE_FORMAT", 10)]
        above_the_cap = findings[("UNIT_PRICE_FORMAT", 11)]
        assert_money_cents(capped_at_ten["penalty_component_cents"], 70)
        assert_money_cents(above_the_cap["penalty_component_cents"], 70)
        assert_money_cents(
            findings[("SHELF_TAG_MISMATCH", 1)]["penalty_component_cents"], 56
        )
        for code in ("SIGNAGE_DISCLOSURE", "EXPIRED_SIGNAGE", "SCANNER_ERROR_RATE"):
            assert_money_cents(findings[(code, 1)]["penalty_component_cents"], 7)

        build.transition_finding(
            findings[("SCANNER_ERROR_RATE", 1)]["id"],
            "WAIVED",
            waiver_reason="Scanner error rate finding withdrawn by the regulator",
        )
        five_left = build.read_inspection(issued["inspection_id"])
        assert five_left["finding_count"] == 5
        assert_money_cents(five_left["penalty_exposure_cents"], 262)
        assert five_left["penalty_exposure_cents"] != 260

        for code in ("EXPIRED_SIGNAGE", "SIGNAGE_DISCLOSURE"):
            build.transition_finding(
                findings[(code, 1)]["id"],
                "WAIVED",
                waiver_reason="Signage citation withdrawn by the regulator",
            )
        build.transition_finding(
            capped_at_ten["id"],
            "WAIVED",
            waiver_reason="Duplicate unit price citation withdrawn",
        )
        two_left = build.read_inspection(issued["inspection_id"])
        assert two_left["finding_count"] == 2
        assert_money_cents(two_left["penalty_exposure_cents"], 126)
        assert_money_cents(
            two_left["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [
                    {"severity": "MINOR", "affected_item_count": 11},
                    {"severity": "CRITICAL", "affected_item_count": 1},
                ],
                7,
                2000000,
                False,
            ),
        )


FOUR_LINE_EVIDENCE = [
    {
        "item_upc": "00000000000101",
        "shelf_price_cents": 949,
        "register_price_cents": 1099,
    },
    {
        "item_upc": "00000000000102",
        "shelf_price_cents": 500,
        "register_price_cents": 650,
    },
    {
        "item_upc": "00000000000103",
        "shelf_price_cents": 199,
        "register_price_cents": 199,
    },
    {
        "item_upc": "00000000000104",
        "shelf_price_cents": 399,
        "register_price_cents": 399,
    },
]

SETTLEMENT_RULEBOOK = {
    "scanner_error_rate_threshold_pct": 25.0,
    "default_rate_variant": "GROSS_MISMATCH",
    "overcharge_refund_policy": "REFUND_DIFFERENCE_PLUS_FIXED",
    "refund_fixed_bonus_cents": 500,
    "refund_cap_cents": 5000,
    "refund_budget_per_audit_cents": 100000,
    "penalty_per_violation_cents": 5000,
    "penalty_max_cents": 2000000,
}


class TestFiveStepSettlementOrder:
    def test_the_pinned_order_yields_exposure_137500_credit_487_and_assessed_137013(
        self, build
    ):
        """One pass through penalty, liability, credit, assessed and ledger — no feedback.

        PRD 3.8: "Under `REFUND_DIFFERENCE_PLUS_FIXED` the gross amount is the
        variance plus the jurisdiction's `refund_fixed_bonus_cents` goodwill
        payment."
        PRD 3.7: "On acceptance, the settlement runs exactly once, top to bottom,
        with no iteration and no feedback from a later step into an earlier one."
        PRD 3.7: "Step one recomputes `penalty_exposure_cents` from the inspection's
        **current** findings, using the tier and cap rules above."
        PRD 3.7: "Step two computes `refund_liability_cents` as the sum of the
        claimed amounts of every refund claim whose scan line belongs to this
        inspection's evidence audit and whose status is `APPROVED` or `PAID`; claims
        that are `PENDING` or `DENIED` are excluded."
        PRD 3.7: "Step three computes `refund_credit_cents` as the smaller of two
        independently floored candidates: seventy-five percent of the refund
        liability, floored; and fifty percent of the penalty exposure, floored."
        PRD 3.7: "Step four sets `assessed_penalty_cents`: if the adjudication
        supplied an override, that override is used verbatim; otherwise it is the
        refund credit subtracted from the penalty exposure, with the difference
        floored at zero."
        PRD 3.7: "Step five raises the store's `cumulative_penalty_exposure_cents`
        by the assessed penalty."
        PRD 3.7: "The credit computed in step three never re-enters step one's tier
        selection."
        PRD 3.7: "The inspection then stamps `closed_at` with the current instant,
        advances its `version` by one, moves to `CLOSED` — its only terminal state —
        and the store's posture is recomputed."
        PRD 3.8: "A store manager approves a `PENDING` claim, moving it `PENDING →
        APPROVED`; the store's outstanding liability is unchanged by approval,
        because `PENDING` and `APPROVED` are both outstanding."

        Design: Difficulty/combinatorial_formula/inspection_net_settlement_pinned_order_breaks_apparent_circularity
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", **SETTLEMENT_RULEBOOK)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        evidence = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINE_EVIDENCE,
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert_pct(evidence["audit"]["error_rate_pct"], 50.00)
        assert evidence["audit"]["outcome"] == "FAIL"

        first = build.approved_claim(
            evidence["scan_line_ids"][0], "CUST-1", evidence["version"], manager_id
        )
        assert_money_cents(first["filed"]["claimed_amount_cents"], 650)
        assert first["filed"]["policy_applied"] == "REFUND_DIFFERENCE_PLUS_FIXED"
        assert first["claim"]["status"] == "APPROVED"

        second = build.refund_claim(
            evidence["scan_line_ids"][1],
            "CUST-2",
            build.audit_version(evidence["audit_id"]),
        )
        assert_money_cents(second["claimed_amount_cents"], 650)
        assert second["status"] == "PENDING"

        issued = build.inspection_with_findings(
            store_id,
            evidence["audit_id"],
            [
                factories.finding_input("SHELF_TAG_MISMATCH", "MAJOR", 4, "A01"),
                factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 12, "A01"),
            ],
            inspector_ref="INSP-9003",
            inspection_date="2026-08-02T09:00:00Z",
        )
        inspection_id = issued["inspection_id"]
        assert issued["inspection"]["finding_count"] == 2
        assert_money_cents(issued["inspection"]["penalty_exposure_cents"], 137500)
        assert_money_cents(
            issued["inspection"]["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [
                    {"severity": "MAJOR", "affected_item_count": 4},
                    {"severity": "MINOR", "affected_item_count": 12},
                ],
                5000,
                2000000,
                True,
            ),
        )

        for finding_id in issued["finding_ids"]:
            remediated = build.remediate_finding(
                finding_id, "REPRINT_SHELF_TAG", "PHOTO-9003", manager_id
            )
            assert remediated["status"] == "REMEDIATED"

        build.submit_response(
            inspection_id,
            "Shelf tags reprinted and unit price format corrected chain-wide",
            build.inspection_version(inspection_id),
            manager_id,
        )
        closed = build.adjudicate(inspection_id, "ACCEPT")

        assert_money_cents(closed["penalty_exposure_cents"], 137500)
        assert_money_cents(closed["refund_liability_cents"], 650)
        assert_money_cents(closed["refund_credit_cents"], 487)
        assert closed["refund_credit_cents"] != 68750
        assert_money_cents(closed["assessed_penalty_cents"], 137013)
        assert closed["status"] == "CLOSED"
        assert_instant_is(closed["closed_at"], "2026-08-01T00:00:00Z")

        assert_money_cents(
            closed["refund_credit_cents"], expected_refund_credit_cents(650, 137500)
        )
        assert_money_cents(
            closed["assessed_penalty_cents"],
            expected_assessed_penalty_cents(137500, 487),
        )

        store = build.read_store(store_id)
        assert_money_cents(store["cumulative_penalty_exposure_cents"], 137013)
        assert_money_cents(store["refund_liability_outstanding_cents"], 1300)

        settled = build.read_inspection(inspection_id)
        assert_money_cents(settled["penalty_exposure_cents"], 137500)
        assert settled["version"] == closed["version"]

    def test_only_approved_and_paid_claims_feed_step_two_and_an_override_replaces_step_four(
        self, api, build, officer_headers
    ):
        """A denied and a pending claim are invisible to the credit; an override wins outright.

        PRD 3.7: "Step two computes `refund_liability_cents` as the sum of the
        claimed amounts of every refund claim whose scan line belongs to this
        inspection's evidence audit and whose status is `APPROVED` or `PAID`; claims
        that are `PENDING` or `DENIED` are excluded."
        PRD 3.7: "Step three computes `refund_credit_cents` as the smaller of two
        independently floored candidates: seventy-five percent of the refund
        liability, floored; and fifty percent of the penalty exposure, floored."
        PRD 3.7: "Each candidate is floored on its own before the smaller is chosen."
        PRD 3.7: "Step four sets `assessed_penalty_cents`: if the adjudication
        supplied an override, that override is used verbatim; otherwise it is the
        refund credit subtracted from the penalty exposure, with the difference
        floored at zero."
        PRD 3.7: "Step five raises the store's `cumulative_penalty_exposure_cents`
        by the assessed penalty."
        PRD 3.7: "The request may optionally supply an `assessed_penalty_cents`
        override, which may not exceed the freshly recomputed exposure; a higher
        override is refused with `ERR_PENALTY_OVERRIDE_TOO_HIGH`."
        PRD 3.8: "A store manager denies a claim, moving it to `DENIED` from either
        `PENDING` or `APPROVED` — the two source states behave identically — storing
        the `denial_reason` and recomputing the store's
        `refund_liability_outstanding_cents`, from which this claim's amount now
        departs."
        PRD 3.8: "A customer service desk operator pays an `APPROVED` claim, moving
        it `APPROVED → PAID`, stamping `paid_at` with the current instant, and
        recomputing both the store's `refund_liability_outstanding_cents` — from
        which the amount now leaves — and its `refund_paid_total_cents`, into which
        the amount now enters."

        Design: Difficulty/combinatorial_formula/inspection_net_settlement_pinned_order_breaks_apparent_circularity
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", **SETTLEMENT_RULEBOOK)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        first_aisle = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        second_aisle = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        manager_headers = build.manager(manager_id)

        evidence = build.closed_audit(
            store_id,
            aisle_id=first_aisle,
            auditor_associate_id=auditor_id,
            observations=[
                {
                    "item_upc": "00000000000301",
                    "shelf_price_cents": 1000,
                    "register_price_cents": 3000,
                },
                {
                    "item_upc": "00000000000302",
                    "shelf_price_cents": 1500,
                    "register_price_cents": 3500,
                },
                {
                    "item_upc": "00000000000303",
                    "shelf_price_cents": 2000,
                    "register_price_cents": 4000,
                },
                {
                    "item_upc": "00000000000304",
                    "shelf_price_cents": 199,
                    "register_price_cents": 299,
                },
            ],
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert evidence["audit"]["outcome"] == "FAIL"
        lines = evidence["scan_line_ids"]
        audit_version = evidence["version"]

        approved = build.approved_claim(lines[0], "CUST-1", audit_version, manager_id)
        assert_money_cents(approved["claim"]["claimed_amount_cents"], 2500)
        assert approved["claim"]["status"] == "APPROVED"

        paid = build.paid_claim(lines[1], "CUST-2", audit_version, manager_id)
        assert_money_cents(paid["claim"]["claimed_amount_cents"], 2500)
        assert paid["claim"]["status"] == "PAID"

        denied_filed = build.refund_claim(lines[2], "CUST-3", audit_version)
        denied = build.settle_claim(
            denied_filed["id"],
            "DENIED",
            manager_headers,
            denial_reason="Customer could not produce the receipt",
        )
        assert denied["status"] == "DENIED"
        assert_money_cents(denied["claimed_amount_cents"], 2500)

        pending = build.refund_claim(lines[3], "CUST-4", audit_version)
        assert pending["status"] == "PENDING"
        assert_money_cents(pending["claimed_amount_cents"], 600)

        before = build.read_store(store_id)
        assert_money_cents(before["refund_liability_outstanding_cents"], 3100)
        assert_money_cents(before["refund_paid_total_cents"], 2500)

        filtered = build.inspection_with_findings(
            store_id,
            evidence["audit_id"],
            [factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 1, "A01")],
            inspector_ref="INSP-9004",
            inspection_date="2026-08-02T09:00:00Z",
        )
        filtered_id = filtered["inspection_id"]
        assert_money_cents(filtered["inspection"]["penalty_exposure_cents"], 6250)
        build.remediate_finding(
            filtered["finding_ids"][0], "REPRINT_UNIT_PRICE", "PHOTO-9004", manager_id
        )
        build.submit_response(
            filtered_id,
            "Unit price format corrected on the single affected tag",
            build.inspection_version(filtered_id),
            manager_id,
        )
        settled = build.adjudicate(filtered_id, "ACCEPT")

        assert_money_cents(settled["penalty_exposure_cents"], 6250)
        assert_money_cents(settled["refund_liability_cents"], 5000)
        assert settled["refund_liability_cents"] != 8100
        assert_money_cents(settled["refund_credit_cents"], 3125)
        assert settled["refund_credit_cents"] != 3750
        assert_money_cents(
            settled["refund_credit_cents"], expected_refund_credit_cents(5000, 6250)
        )
        assert_money_cents(settled["assessed_penalty_cents"], 3125)
        assert settled["status"] == "CLOSED"
        assert_money_cents(
            build.read_store(store_id)["cumulative_penalty_exposure_cents"], 3125
        )

        clean_evidence = build.closed_audit(
            store_id,
            aisle_id=second_aisle,
            auditor_associate_id=auditor_id,
            observations=[
                {
                    "item_upc": "00000000000311",
                    "shelf_price_cents": 199,
                    "register_price_cents": 299,
                }
            ],
            audit_type="REGULATORY",
            scan_window_start="2026-08-02T08:00:00Z",
            scan_window_end="2026-08-02T10:00:00Z",
        )
        assert clean_evidence["audit"]["outcome"] == "FAIL"
        overridden = build.inspection_with_findings(
            store_id,
            clean_evidence["audit_id"],
            [factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 1, "A02")],
            inspector_ref="INSP-9005",
            inspection_date="2026-08-03T09:00:00Z",
        )
        overridden_id = overridden["inspection_id"]
        assert_money_cents(overridden["inspection"]["penalty_exposure_cents"], 6250)
        build.remediate_finding(
            overridden["finding_ids"][0],
            "REPRINT_UNIT_PRICE",
            "PHOTO-9005",
            manager_id,
        )
        build.submit_response(
            overridden_id,
            "Unit price format corrected in the bakery aisle",
            build.inspection_version(overridden_id),
            manager_id,
        )
        validate_error(
            api.adjudicate_inspection(
                overridden_id,
                factories.adjudicate_payload("ACCEPT", assessed_penalty_cents=6251),
                officer_headers,
            ),
            ERR_PENALTY_OVERRIDE_TOO_HIGH,
            422,
        )
        accepted = build.adjudicate(
            overridden_id, "ACCEPT", assessed_penalty_cents=1000
        )
        assert_money_cents(accepted["penalty_exposure_cents"], 6250)
        assert_money_cents(accepted["refund_liability_cents"], 0)
        assert_money_cents(accepted["refund_credit_cents"], 0)
        assert_money_cents(accepted["assessed_penalty_cents"], 1000)
        assert accepted["assessed_penalty_cents"] != 6250
        assert_money_cents(
            accepted["assessed_penalty_cents"],
            expected_assessed_penalty_cents(6250, 0, 1000),
        )
        assert accepted["status"] == "CLOSED"

        after = build.read_store(store_id)
        assert_money_cents(after["cumulative_penalty_exposure_cents"], 4125)
        assert_money_cents(after["refund_liability_outstanding_cents"], 3100)
        assert_money_cents(after["refund_paid_total_cents"], 2500)
