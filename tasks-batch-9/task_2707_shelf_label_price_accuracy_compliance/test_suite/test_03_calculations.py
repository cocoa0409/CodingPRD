"""Derived arithmetic: unit price, deadlines, error-rate variants, refunds, penalties and postures."""

import pytest

from test_helpers import (
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    assert_posture,
    expected_gross_error_rate_pct,
    expected_net_overcharge_rate_pct,
    expected_claimed_amount_cents,
    expected_occurrence_weighted_score,
    expected_penalty_component_cents,
    expected_penalty_exposure_cents,
    expected_task_weighted_score,
    expected_unit_price_display_cents,
    factories,
    unit_price_basis,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ERR_ASSOCIATE_INVALID_STATE
from test_helpers.constants import ROLE_CODE_LABEL_ASSOCIATE


class TestUnitPriceBasisSelection:
    def test_the_uom_rule_picks_the_divisor_and_a_weight_item_falls_back_to_pounds(
        self, api, build
    ):
        """Three jurisdictions divide the same style of line three different ways.

        PRD 3.3: "If the jurisdiction's rule is `PER_SINGLE_ITEM`, the basis
        quantity is 1 and the basis label is `EACH`, whatever the line's own unit
        of measure says."
        PRD 3.3: "If the rule is `PER_100_COUNT` **and** the line's unit of
        measure is in the count family, the basis quantity is the net content
        quantity divided by 100 and the basis label is `100CT`."
        PRD 3.3: "In every other case — that is, under
        `PER_UNIT_MEASURE_CANONICAL`, and also under `PER_100_COUNT` when the line
        is not a count item — the canonical basis for the line's family applies:
        for a weight line the basis label is `LB` and the basis quantity is the
        net content quantity divided by 16 when the unit of measure is `OZ` and
        the net content quantity unchanged when it is already `LB`; for a volume
        line the basis label is `GAL` and the basis quantity is the net content
        quantity divided by 128 when the unit of measure is `FL_OZ` and the net
        content quantity unchanged when it is already `GAL`; for a count line the
        basis label is `CT` and the basis quantity is the net content quantity
        unchanged; and for an `EACH` line the basis quantity is 1 with basis label
        `EACH`."
        PRD 3.3: "The number of decimal places retained on the **cent** figure is
        the jurisdiction's `unit_price_decimal_places` reduced by two, and never
        less than zero — so a jurisdiction printing dollars to two places rounds
        the cent figure to a whole number, while one printing dollars to three
        places retains one decimal on the cent figure."

        Design: Corner/Calculations/corner_unit_price_basis_rule_selects_the_divisor_and_the_fallback
        """
        rulebook = dict(unit_price_decimal_places=2, unit_price_rounding="ROUND_HALF_UP")
        jur_single = build.jurisdiction(
            code="US-SI",
            name="Single Item State",
            unit_price_uom_rule="PER_SINGLE_ITEM",
            **rulebook,
        )
        jur_hundred = build.jurisdiction(
            code="US-100",
            name="Per Hundred State",
            unit_price_uom_rule="PER_100_COUNT",
            **rulebook,
        )
        jur_canonical = build.jurisdiction(
            code="US-CA",
            name="Canonical State",
            unit_price_uom_rule="PER_UNIT_MEASURE_CANONICAL",
            **rulebook,
        )
        store_single = build.store(jur_single, store_number="S-SI")
        store_hundred = build.store(jur_hundred, store_number="S-100")
        store_canonical = build.store(jur_canonical, store_number="S-CAN")
        file_single = build.price_change_file(
            jur_single, [store_single], file_number="PCF-SI", priority="ROUTINE"
        )
        file_hundred = build.price_change_file(
            jur_hundred, [store_hundred], file_number="PCF-100", priority="ROUTINE"
        )
        file_canonical = build.price_change_file(
            jur_canonical, [store_canonical], file_number="PCF-CAN", priority="ROUTINE"
        )

        line_single = build.add_line(
            file_single["id"], "00000000002001", 1000, 1199, 12, "OZ",
            item_description="Cheese 12oz", category_code="DAIRY",
        )
        line_count = build.add_line(
            file_hundred["id"], "00000000002002", 1000, 1299, 250, "CT",
            item_description="Napkins 250ct", category_code="PAPER",
        )
        line_fallback = build.add_line(
            file_hundred["id"], "00000000002003", 499, 599, 26, "OZ",
            item_description="Coffee 26oz", category_code="GROCERY",
        )
        line_canonical = build.add_line(
            file_canonical["id"], "00000000002004", 499, 599, 26, "OZ",
            item_description="Coffee 26oz", category_code="GROCERY",
        )

        # PER_SINGLE_ITEM ignores the 12 OZ net content entirely.
        assert line_single["unit_price_basis_uom"] == "EACH"
        assert float(line_single["unit_price_basis_qty"]) == pytest.approx(1.0, abs=1e-6)
        assert_money_cents(line_single["unit_price_display_cents"], 1000)
        assert line_single["unit_price_display_cents"] == expected_unit_price_display_cents(
            1000, 12, "OZ", "PER_SINGLE_ITEM", 2, "ROUND_HALF_UP"
        )

        # PER_100_COUNT on a count item divides by one hundred.
        assert line_count["unit_price_basis_uom"] == "100CT"
        assert float(line_count["unit_price_basis_qty"]) == pytest.approx(2.5, abs=1e-6)
        assert_money_cents(line_count["unit_price_display_cents"], 400)

        # PER_100_COUNT on a weight item falls back to the canonical pound.
        assert line_fallback["unit_price_basis_uom"] == "LB"
        assert float(line_fallback["unit_price_basis_qty"]) == pytest.approx(1.625, abs=1e-6)
        assert_money_cents(line_fallback["unit_price_display_cents"], 307)
        assert line_fallback["unit_price_display_cents"] != 306, (
            "1.625 must not be rounded to 1.63 before the division"
        )

        # The fallback is indistinguishable from the canonical rule itself.
        assert line_canonical["unit_price_basis_uom"] == line_fallback["unit_price_basis_uom"]
        assert (
            line_canonical["unit_price_display_cents"]
            == line_fallback["unit_price_display_cents"]
            == 307
        )
        basis_qty, basis_uom = unit_price_basis(26, "OZ", "PER_100_COUNT")
        assert (float(basis_qty), basis_uom) == (1.625, "LB")


class TestLabelTaskDeadline:
    def test_due_at_advances_the_effective_date_and_the_overdue_boundary_is_inclusive(
        self, api, build
    ):
        """A 48-hour grace period puts due_at two days past the effective date.

        PRD 3.4: "`due_at` is the effective date of the batch that owns the line,
        advanced by the jurisdiction's grace period in hours — with the default
        grace period that is two days after the price becomes binding."
        PRD 3.4: "`overdue` is true when the current instant is at or after
        `due_at` **and** the placement axis reads either `UNPLACED` or `REJECTED`;
        it is re-derived on every read of the task and on every placement-axis
        transition, and instants are compared at millisecond resolution with the
        boundary counted as already overdue rather than still on time."
        PRD 3.4: "A task that has been placed or verified is never overdue no
        matter how late it was, which is the point: the flag measures outstanding
        exposure, not historical punctuality."

        Design: Corner/Calculations/corner_label_task_due_at_and_overdue_flag_at_the_exact_instant
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        staff = build.store_with_staff(jurisdiction_id)
        store_id = staff["store_id"]
        associate_id = staff["label_associate_id"]
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                dict(
                    item_upc="00000000002001",
                    new_retail_cents=1000,
                    old_retail_cents=1199,
                    net_content_qty=12,
                    net_content_uom="OZ",
                    item_description="Cheese 12oz",
                )
            ],
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        task = build.label_task(
            built["file_id"],
            store_id,
            built["line_ids"][0],
            staff["aisle_id"],
            associate_id,
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T10:00:00Z",
            expected_price_change_file_version=built["version"],
        )
        task_id = task["id"]

        # The scheduled end at 10:00 on the 2nd is not the deadline.
        assert_instant_is(task["due_at"], "2026-08-05T00:00:00Z")
        assert task["overdue"] is False

        build.set_clock("2026-08-04T23:59:59Z")
        assert build.read_task(task_id)["overdue"] is False

        build.set_clock("2026-08-05T00:00:00Z")
        assert build.read_task(task_id)["overdue"] is True
        overdue_before, meta_before = validate_paginated(
            api.list_label_tasks(build.admin, {"store_id": store_id, "overdue": "true"})
        )
        assert meta_before["total_count"] == 1
        assert [record["id"] for record in overdue_before] == [task_id]

        headers = build.associate_headers(associate_id)
        build.print_task(task_id, headers)
        placed = build.place_task(task_id, 1000, headers)

        # Same instant, but PLACED has left the {UNPLACED, REJECTED} set.
        assert placed["overdue"] is False
        assert build.read_task(task_id)["overdue"] is False
        overdue_after, meta_after = validate_paginated(
            api.list_label_tasks(build.admin, {"store_id": store_id, "overdue": "true"})
        )
        assert meta_after["total_count"] == 0
        assert overdue_after == []


class TestRateVariantSelection:
    def test_an_omitted_variant_takes_the_jurisdiction_default_while_an_explicit_one_overrides(
        self, api, build
    ):
        """Twin audits over identical evidence disagree only about the applied variant.

        PRD 3.5: "Two error rates are always computed and always stored,
        regardless of which one is going to be used."
        PRD 3.5: "An optional `rate_variant` of `GROSS_MISMATCH` or
        `NET_OVERCHARGE` may be supplied on the close request; when it is omitted,
        the jurisdiction's `default_rate_variant` decides."
        PRD 3.5: "The chosen variant is recorded in `rate_variant_applied`, and its
        value is copied into `error_rate_pct`, which is the **only** rate ever
        compared against the jurisdiction's threshold."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or above
        `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the comparison
        is inclusive, so a rate exactly equal to the threshold fails."

        Design: Corner/Calculations/corner_rate_variant_selection_falls_back_to_the_jurisdiction_default
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            default_rate_variant="NET_OVERCHARGE",
            scanner_error_rate_threshold_pct=25.0,
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        auditor_id = staff["auditor_id"]
        second_aisle = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        observations = [
            dict(item_upc="00000000002001", shelf_price_cents=1000, register_price_cents=1199),
            dict(item_upc="00000000002002", shelf_price_cents=1000, register_price_cents=900),
            dict(item_upc="00000000002003", shelf_price_cents=500, register_price_cents=500),
            dict(item_upc="00000000002004", shelf_price_cents=700, register_price_cents=700),
        ]
        default_audit = build.audit_with_scan_lines(
            store_id,
            staff["aisle_id"],
            auditor_id,
            observations,
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        explicit_audit = build.audit_with_scan_lines(
            store_id,
            second_aisle,
            auditor_id,
            observations,
            scan_window_start="2026-08-01T14:00:00Z",
            scan_window_end="2026-08-01T15:00:00Z",
        )
        auditor_headers = build.auditor(auditor_id)

        by_default = build.close_audit(default_audit["audit_id"], auditor_headers)
        by_request = build.close_audit(
            explicit_audit["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )

        assert by_default["rate_variant_applied"] == "NET_OVERCHARGE"
        assert_pct(by_default["error_rate_pct"], 0.00)
        assert by_default["outcome"] == "PASS"

        assert by_request["rate_variant_applied"] == "GROSS_MISMATCH"
        assert_pct(by_request["error_rate_pct"], 50.00)
        assert by_request["outcome"] == "FAIL"

        # Both rates sit on both audits whichever one was applied.
        for record in (by_default, by_request):
            assert_pct(record["gross_error_rate_pct"], expected_gross_error_rate_pct(1, 1, 4))
            assert_pct(
                record["net_overcharge_rate_pct"], expected_net_overcharge_rate_pct(1, 1, 4)
            )
            assert record["sample_size"] == 4
            assert record["overcharge_count"] == 1
            assert record["undercharge_count"] == 1

        summary = build.read_summary(store_id)
        assert summary["failed_audit_count_30d"] == 1
        assert_posture(summary, "RESTRICTED")


class TestRefundPolicyWaterfall:
    def test_each_policy_branch_applies_and_the_cap_lands_last_and_inclusively(
        self, api, build
    ):
        """Four claims against one audit walk all three policies and the cap edge.

        PRD 3.8: "The amount is derived from the scan line and the jurisdiction's
        `overcharge_refund_policy`, and the policy branch actually used is recorded
        on the claim as `policy_applied` so that a later audit of the audit can
        reproduce the arithmetic."
        PRD 3.8: "Under `REFUND_DIFFERENCE_ONLY` the gross amount is that variance
        alone."
        PRD 3.8: "Under `REFUND_DIFFERENCE_PLUS_FIXED` the gross amount is the
        variance plus the jurisdiction's `refund_fixed_bonus_cents` goodwill
        payment."
        PRD 3.8: "Under `ITEM_FREE_UP_TO_CAP` the customer keeps the item, so the
        gross amount is the full `register_price_cents` the customer was charged."
        PRD 3.8: "In all three branches the amount finally stored as
        `claimed_amount_cents` is the smaller of the gross amount and the
        jurisdiction's `refund_cap_cents`; the cap is applied last and is
        inclusive, so a gross amount exactly equal to the cap is paid in full."
        PRD 2.7: "`refund_liability_outstanding_cents` is the sum of the claimed
        amounts of this store's refund claims whose status is `PENDING` or
        `APPROVED`."

        Design: Corner/Calculations/corner_refund_policy_waterfall_and_inclusive_cap
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            overcharge_refund_policy="REFUND_DIFFERENCE_ONLY",
            refund_fixed_bonus_cents=500,
            refund_cap_cents=5000,
            refund_budget_per_audit_cents=100000,
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [
                dict(item_upc="00000000002001", shelf_price_cents=1000, register_price_cents=1199),
                dict(item_upc="00000000002002", shelf_price_cents=1000, register_price_cents=1199),
                dict(item_upc="00000000002003", shelf_price_cents=4000, register_price_cents=6000),
                dict(item_upc="00000000002004", shelf_price_cents=4000, register_price_cents=6000),
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_version = closed["version"]
        line_a, line_b, line_c, line_d = closed["scan_line_ids"]

        claim_a = build.refund_claim(line_a, "CUST-A", audit_version)
        build.amend_jurisdiction(
            jurisdiction_id, {"overcharge_refund_policy": "REFUND_DIFFERENCE_PLUS_FIXED"}
        )
        claim_b = build.refund_claim(line_b, "CUST-B", audit_version)
        build.amend_jurisdiction(
            jurisdiction_id, {"overcharge_refund_policy": "ITEM_FREE_UP_TO_CAP"}
        )
        claim_c = build.refund_claim(line_c, "CUST-C", audit_version)
        build.amend_jurisdiction(jurisdiction_id, {"refund_cap_cents": 6000})
        claim_d = build.refund_claim(line_d, "CUST-D", audit_version)

        assert claim_a["policy_applied"] == "REFUND_DIFFERENCE_ONLY"
        assert_money_cents(claim_a["claimed_amount_cents"], 199)
        assert claim_a["claimed_amount_cents"] == expected_claimed_amount_cents(
            1000, 1199, "REFUND_DIFFERENCE_ONLY", 5000, 500
        )

        assert claim_b["policy_applied"] == "REFUND_DIFFERENCE_PLUS_FIXED"
        assert_money_cents(claim_b["claimed_amount_cents"], 699)
        assert claim_b["claimed_amount_cents"] == expected_claimed_amount_cents(
            1000, 1199, "REFUND_DIFFERENCE_PLUS_FIXED", 5000, 500
        )

        # The 6000c item is trimmed to the 5000c cap, not to the 2000c variance.
        assert claim_c["policy_applied"] == "ITEM_FREE_UP_TO_CAP"
        assert_money_cents(claim_c["claimed_amount_cents"], 5000)

        # A gross amount exactly equal to the raised cap is paid in full.
        assert claim_d["policy_applied"] == "ITEM_FREE_UP_TO_CAP"
        assert_money_cents(claim_d["claimed_amount_cents"], 6000)
        assert claim_d["claimed_amount_cents"] == expected_claimed_amount_cents(
            4000, 6000, "ITEM_FREE_UP_TO_CAP", 6000, 500
        )

        # Filing claims never advances the audit, which is why one pin served all four.
        assert build.audit_version(closed["audit_id"]) == audit_version

        # The policy is frozen at creation, not re-derived on read.
        reread = build.read_claim(claim_a["id"])
        assert_money_cents(reread["claimed_amount_cents"], 199)
        assert reread["policy_applied"] == "REFUND_DIFFERENCE_ONLY"
        assert reread["status"] == "PENDING"

        summary = build.read_summary(store_id)
        assert_money_cents(
            summary["refund_liability_outstanding_cents"], 199 + 699 + 5000 + 6000
        )


class TestWaiverShrinksTheConsideredSet:
    def test_waiving_the_cheapest_finding_drops_the_tier_and_more_than_its_own_component(
        self, api, build
    ):
        """Three findings scale at 125; waiving the MINOR one falls back to 100.

        PRD 3.7: "The considered set is every finding of the inspection whose
        status is not `WAIVED`, and `finding_count` is the size of that set."
        PRD 3.7: "The **tier multiplier** is 100 percentage points when the
        considered set holds at most 2 findings, 125 when it holds at most 5, and
        150 beyond that."
        PRD 3.7: "An **audit aggravator** of 25 percentage points is added when the
        referenced evidence audit's outcome is `FAIL`, and 0 percentage points
        otherwise."
        PRD 3.7: "Each considered finding's `penalty_component_cents` is its
        severity weight — 1 for `MINOR`, 3 for `MAJOR`, 8 for `CRITICAL` —
        multiplied by the jurisdiction's `penalty_per_violation_cents`, multiplied
        by the smaller of the finding's `affected_item_count` and the per-finding
        item cap of 10."
        PRD 3.7: "Waiving is the branch with the widest financial reach: the reason
        is stored, the finding's `penalty_component_cents` is zeroed, the owning
        inspection's `finding_count` and `penalty_exposure_cents` are recomputed —
        and because the waived finding leaves the considered set, that
        recomputation can select a **lower** tier multiplier, so waiving the third
        finding of three moves the tier from 125 back to 100 and reduces the
        exposure by more than the waived finding's own component."

        Design: Corner/Calculations/corner_waiving_a_finding_shrinks_the_considered_set_and_drops_the_tier
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=2.0,
            penalty_per_violation_cents=5000,
            penalty_max_cents=2000000,
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [dict(item_upc="00000000002001", shelf_price_cents=500, register_price_cents=500)],
            rate_variant="GROSS_MISMATCH",
            audit_type="FOLLOW_UP",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        # A passing audit keeps the aggravator at zero, so the tier is the only mover.
        assert closed["audit"]["outcome"] == "PASS"

        issued = build.inspection_with_findings(
            store_id,
            closed["audit_id"],
            [
                factories.finding_input("SHELF_TAG_MISMATCH", "MAJOR", 4),
                factories.finding_input("SCANNER_ERROR_RATE", "MAJOR", 4),
                factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 1),
            ],
            inspector_ref="INS-88",
            inspection_date="2026-08-01T16:00:00Z",
        )
        three_findings = [
            dict(severity="MAJOR", affected_item_count=4),
            dict(severity="MAJOR", affected_item_count=4),
            dict(severity="MINOR", affected_item_count=1),
        ]
        assert issued["inspection"]["finding_count"] == 3
        assert_money_cents(issued["inspection"]["penalty_exposure_cents"], 156250)
        assert issued["inspection"]["penalty_exposure_cents"] == expected_penalty_exposure_cents(
            three_findings, 5000, 2000000, False
        )

        findings = {fid: build.read_finding(fid) for fid in issued["finding_ids"]}
        minor_id = next(
            fid for fid, record in findings.items() if record["severity"] == "MINOR"
        )
        major_ids = [fid for fid in findings if fid != minor_id]
        assert_money_cents(
            findings[minor_id]["penalty_component_cents"],
            expected_penalty_component_cents("MINOR", 5000, 1),
        )
        assert_money_cents(findings[minor_id]["penalty_component_cents"], 5000)

        build.transition_finding(
            minor_id,
            "WAIVED",
            waiver_reason="Formatting fixed while the inspector watched",
        )

        after = build.read_inspection(issued["inspection_id"])
        assert after["finding_count"] == 2
        assert_money_cents(after["penalty_exposure_cents"], 120000)
        assert after["penalty_exposure_cents"] == expected_penalty_exposure_cents(
            three_findings[:2], 5000, 2000000, False
        )
        # The 36250c fall is far more than the 5000c component that was waived.
        assert issued["inspection"]["penalty_exposure_cents"] - after["penalty_exposure_cents"] == 36250

        waived = build.read_finding(minor_id)
        assert waived["status"] == "WAIVED"
        assert waived["waiver_reason"] == "Formatting fixed while the inspector watched"
        assert_money_cents(waived["penalty_component_cents"], 0)

        for fid in major_ids:
            survivor = build.read_finding(fid)
            assert survivor["status"] == "OPEN"
            assert_money_cents(survivor["penalty_component_cents"], 60000)


class TestPostureWaterfall:
    def test_the_posture_walks_frozen_then_restricted_then_open_on_recounted_findings(
        self, api, build
    ):
        """Three open findings freeze the store and each waiver walks it back down.

        PRD 2.7: "The verdict is evaluated in a pinned order — the frozen tests
        first, then the restricted tests, then the fallthrough."
        PRD 2.7: "The posture becomes `FROZEN` when at least one escalated finding
        exists, **or** when the open finding count is at least 3, **or** when the
        thirty-day failed-audit count is at least 2."
        PRD 2.7: "Otherwise the posture becomes `RESTRICTED` when the open finding
        count is at least 1, **or** when the thirty-day failed-audit count is
        exactly 1, **or** when the label backlog is at least 5, **or** when at
        least one signage violation exists."
        PRD 2.7: "If none of those hold, the posture is `OPEN`."
        PRD 2.7: "`open_finding_count` is the number of inspection findings
        belonging to this store's inspections whose status is either `OPEN` or
        `REMEDIATION_PLANNED`."
        PRD 2.7: "`escalated_finding_count` is the number of findings belonging to
        this store's inspections whose status is `ESCALATED`."

        Design: Corner/Calculations/corner_posture_waterfall_walks_frozen_then_restricted_then_open
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", scanner_error_rate_threshold_pct=2.0
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [dict(item_upc="00000000002001", shelf_price_cents=500, register_price_cents=500)],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        at_start = build.read_summary(store_id)
        assert at_start["failed_audit_count_30d"] == 0
        assert at_start["open_finding_count"] == 0
        assert_posture(at_start, "OPEN")

        issued = build.inspection_with_findings(
            store_id,
            closed["audit_id"],
            [
                factories.finding_input("SHELF_TAG_MISMATCH", "MINOR", 1),
                factories.finding_input("UNIT_PRICE_FORMAT", "MINOR", 1),
                factories.finding_input("SIGNAGE_DISCLOSURE", "MINOR", 1),
            ],
            inspector_ref="INS-99",
            inspection_date="2026-08-01T16:00:00Z",
        )
        at_three = build.read_summary(store_id)
        assert at_three["open_finding_count"] == 3
        assert at_three["escalated_finding_count"] == 0
        assert at_three["failed_audit_count_30d"] == 0
        assert_posture(at_three, "FROZEN")

        reasons = [
            "Corrected on the spot",
            "Duplicate citation",
            "Sign was replaced before the visit",
        ]
        expected_walk = [(2, "RESTRICTED"), (1, "RESTRICTED"), (0, "OPEN")]
        for finding_id, reason, (open_count, posture) in zip(
            issued["finding_ids"], reasons, expected_walk
        ):
            build.transition_finding(finding_id, "WAIVED", waiver_reason=reason)
            summary = build.read_summary(store_id)
            assert summary["open_finding_count"] == open_count
            assert summary["escalated_finding_count"] == 0
            assert summary["signage_violation_count"] == 0
            assert summary["label_backlog_count"] == 0
            assert_posture(summary, posture)


class TestExceptionReportRanking:
    def test_all_three_tie_breaks_are_needed_to_order_the_category_breakdown(
        self, api, build
    ):
        """CANDY wins on rate, DAIRY on error count, APPAREL over BAKERY on spelling.

        PRD 3.9: "The qualifying audits are this store's audits whose status is
        `CLOSED` and whose closing instant falls at or after `period_start_at` and
        strictly before `period_end_at`; audits sitting in `OPEN`, `SCANNING` or
        `REOPENED` are excluded entirely, which means reopening an audit removes it
        from reports generated afterwards."
        PRD 3.9: "`audit_count` is the number of qualifying audits and
        `scan_line_count` is the total number of scan lines belonging to them."
        PRD 3.9: "Only groups whose sample size is at least 2 are eligible for the
        ranking — a single scan line is anecdote, not evidence."
        PRD 3.9: "The eligible groups are then ordered by error rate descending;
        ties are broken by error count descending; remaining ties are broken by
        `category_code` ascending in lexicographic byte order."
        PRD 3.9: "The ordered list is stored as `category_breakdown`, each element
        carrying `category_code`, `sample_size`, `error_count` and
        `error_rate_pct`."
        PRD 3.9: "The first element supplies `top_category_code` and
        `top_category_error_rate_pct`."
        PRD 3.9: "A new report starts `GENERATED` with `root_cause_code`,
        `remediation_owner_associate_id` and `closure_note` null."

        Design: Corner/Calculations/corner_exception_report_ranking_applies_all_three_tie_breaks
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", scanner_error_rate_threshold_pct=2.0
        )
        store_id = build.store(jurisdiction_id, store_number="S001")
        auditor_id = build.certified_auditor(store_id, employee_number="E-PA1")
        candy_aisle = build.aisle(store_id, aisle_code="A01", category_code="CANDY")
        dairy_aisle = build.aisle(store_id, aisle_code="A02", category_code="DAIRY")
        apparel_aisle = build.aisle(store_id, aisle_code="A03", category_code="APPAREL")
        bakery_aisle = build.aisle(store_id, aisle_code="A04", category_code="BAKERY")

        candy = build.audit_with_scan_lines(
            store_id,
            candy_aisle,
            auditor_id,
            [
                dict(item_upc="00000000004001", shelf_price_cents=100, register_price_cents=150),
                dict(item_upc="00000000004002", shelf_price_cents=100, register_price_cents=150),
            ],
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        dairy = build.audit_with_scan_lines(
            store_id,
            dairy_aisle,
            auditor_id,
            [
                dict(item_upc="00000000004003", shelf_price_cents=200, register_price_cents=250),
                dict(item_upc="00000000004004", shelf_price_cents=200, register_price_cents=250),
                dict(item_upc="00000000004005", shelf_price_cents=200, register_price_cents=200),
                dict(item_upc="00000000004006", shelf_price_cents=200, register_price_cents=200),
            ],
            scan_window_start="2026-08-01T10:00:00Z",
            scan_window_end="2026-08-01T11:00:00Z",
        )
        apparel = build.audit_with_scan_lines(
            store_id,
            apparel_aisle,
            auditor_id,
            [
                dict(item_upc="00000000004007", shelf_price_cents=900, register_price_cents=999),
                dict(item_upc="00000000004008", shelf_price_cents=900, register_price_cents=900),
            ],
            scan_window_start="2026-08-01T12:00:00Z",
            scan_window_end="2026-08-01T13:00:00Z",
        )
        bakery = build.audit_with_scan_lines(
            store_id,
            bakery_aisle,
            auditor_id,
            [
                dict(item_upc="00000000004009", shelf_price_cents=300, register_price_cents=350),
                dict(item_upc="00000000004010", shelf_price_cents=300, register_price_cents=300),
            ],
            scan_window_start="2026-08-01T14:00:00Z",
            scan_window_end="2026-08-01T15:00:00Z",
        )
        auditor_headers = build.auditor(auditor_id)
        for built in (candy, dairy, apparel, bakery):
            build.close_audit(built["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH")

        report = build.exception_report(
            store_id, "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )

        assert report["audit_count"] == 4
        assert report["scan_line_count"] == 10
        assert report["top_category_code"] == "CANDY"
        assert_pct(report["top_category_error_rate_pct"], 100.00)

        breakdown = report["category_breakdown"]
        assert [group["category_code"] for group in breakdown] == [
            "CANDY",
            "DAIRY",
            "APPAREL",
            "BAKERY",
        ]
        assert [
            (group["sample_size"], group["error_count"]) for group in breakdown
        ] == [(2, 2), (4, 2), (2, 1), (2, 1)]
        for group, rate in zip(breakdown, [100.00, 50.00, 50.00, 50.00]):
            assert_pct(group["error_rate_pct"], rate)

        assert report["status"] == "GENERATED"
        assert report["root_cause_code"] is None
        assert report["remediation_owner_associate_id"] is None
        assert report["closure_note"] is None


class TestAccountabilityVariantSwitch:
    def test_the_stored_score_survives_the_amendment_and_re_derives_at_the_next_trigger(
        self, api, build
    ):
        """Switching the variant leaves 95 standing until the next action fires.

        PRD 3.2: "Whenever an accountability action against the associate is
        created, completed or voided, and whenever one of their label tasks reaches
        a verified placement, the associate's `accountability_score` is
        recomputed."
        PRD 2.5: "Amending a jurisdiction is a live operation with cross-entity
        consequences, described in §3.1 and §3.6: because the required disclosure
        set is read from the jurisdiction at evaluation time rather than copied onto
        each sign, changing `signage_disclosure_codes` re-derives the
        missing-disclosure set and the compliance verdict of every non-removed sign
        in the jurisdiction and recomputes each affected store's posture."
        PRD 3.2: "The weight assigned to an action by its `action_type` is 5 for
        `COACHING`, 10 for `RETRAINING_ASSIGNED`, 15 for `WRITTEN_WARNING` and 25
        for `SUSPENSION`, and that weight is stored on the action itself as
        `score_weight`."
        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the sum
        of the weights of the outstanding actions, floored at zero — each issued
        action costs its flat weight regardless of how much correct work the
        associate has done."
        PRD 3.2: "Under `TASK_WEIGHTED`, the outstanding weight sum is first
        multiplied by 40, that product is then divided by the associate's verified
        placement count plus 4, the quotient is subtracted from 100, the difference
        is rounded half up to two decimal places, and the result is floored at
        zero."
        PRD 3.2: "The suspension floor is 80, and the comparison is **strict**: a
        recomputed score of exactly 80 does not suspend, a score of 79.99 does."
        PRD 3.2: "`issued_by_ref` records the acting operator's `X-User-ID`, or the
        literal string `system` when the action was created by a cascade rather
        than by a person."
        PRD 3.2: "Issuing an action against an already-`SUSPENDED` associate is
        refused with `ERR_ASSOCIATE_INVALID_STATE`."

        Design: Corner/Calculations/corner_accountability_variant_switch_reconciles_at_the_next_scoring_trigger
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", accountability_variant="OCCURRENCE_WEIGHTED"
        )
        store_id = build.store(jurisdiction_id, store_number="S001")
        manager_id = build.certified_manager(store_id, employee_number="E-SM1")
        associate_id = build.associate(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        certified = build.train(associate_id, "LABEL_101", 95)
        assert certified["training_status"] == "CERTIFIED"
        assert_pct(certified["accountability_score"], 100)

        manager_headers = build.manager(manager_id)
        coaching = build.issue_action(
            associate_id,
            "COACHING",
            trigger_code="VERIFICATION_REJECTED",
            actor_headers=manager_headers,
        )
        assert coaching["score_weight"] == 5
        assert coaching["issued_by_ref"] == manager_id
        assert coaching["status"] == "ISSUED"

        under_occurrence = build.read_associate(associate_id)
        assert_pct(under_occurrence["accountability_score"], 95)
        assert under_occurrence["accountability_score"] == pytest.approx(
            expected_occurrence_weighted_score(["COACHING"]), abs=0.01
        )
        assert under_occurrence["training_status"] == "CERTIFIED"

        build.amend_jurisdiction(
            jurisdiction_id, {"accountability_variant": "TASK_WEIGHTED"}
        )

        # The amendment re-derives signage and posture, never a stored score.
        after_amendment = build.read_associate(associate_id)
        assert_pct(after_amendment["accountability_score"], 95)
        assert after_amendment["training_status"] == "CERTIFIED"

        retraining = build.issue_action(
            associate_id,
            "RETRAINING_ASSIGNED",
            trigger_code="OVERDUE_LABEL_TASK",
            actor_headers=manager_headers,
        )
        assert retraining["score_weight"] == 10

        under_task_weighted = build.read_associate(associate_id)
        # 15 * 40 / (0 + 4) is 150, so the raw score is -50 and the floor clamps it.
        assert_pct(under_task_weighted["accountability_score"], 0.00)
        assert under_task_weighted["accountability_score"] == pytest.approx(
            expected_task_weighted_score(["COACHING", "RETRAINING_ASSIGNED"], 0), abs=0.01
        )
        assert under_task_weighted["training_status"] == "SUSPENDED"
        assert under_task_weighted["issued_action_count"] == 2
        assert under_task_weighted["verified_placement_count"] == 0

        refused = api.create_accountability_action(
            associate_id,
            factories.accountability_action_payload("COACHING", "AUDIT_FAIL"),
            manager_headers,
        )
        validate_error(refused, ERR_ASSOCIATE_INVALID_STATE, 409)
        ledger, meta = validate_paginated(
            api.list_associate_accountability_actions(associate_id, manager_headers)
        )
        assert meta["total_count"] == 2
        assert sorted(record["action_type"] for record in ledger) == [
            "COACHING",
            "RETRAINING_ASSIGNED",
        ]


class TestAuditFailureActionWaterfall:
    def test_the_action_type_waterfall_picks_the_first_matching_branch(self, api, build):
        """Coaching, then a written warning, then suspension, then nothing at all.

        PRD 3.5: "For an eligible candidate, the action's severity is chosen by a
        first-match waterfall."
        PRD 3.5: "If the candidate already has at least one accountability action
        with status `ISSUED` and `action_type` `WRITTEN_WARNING`, the new action's
        `action_type` is `SUSPENSION`."
        PRD 3.5: "Otherwise, if the audit's applied `error_rate_pct` is at or above
        twice the jurisdiction's threshold — a doubled-threshold test that is
        likewise inclusive, so exactly 4.00 percent against a 2.00 percent
        threshold qualifies — the new action's `action_type` is `WRITTEN_WARNING`."
        PRD 3.5: "Otherwise it is `COACHING`."
        PRD 3.5: "The action is created with its `associate_id` set to the
        accountable candidate just selected, its `trigger_code` set to
        `AUDIT_FAIL`, and its `issued_by_ref` set to the literal `system`."
        PRD 3.5: "The third hop applies the derived suspension: if the recomputed
        score is strictly below the floor of 80, the associate transitions
        `CERTIFIED → SUSPENDED`."
        PRD 3.5: "When the aisle has no assigned associate, or the referenced
        associate is already `SUSPENDED`, **no accountability action is created at
        all**: the audit still closes with `FAIL`, the store's failed-audit count
        still rises and its posture is still recomputed, and the failure is simply
        unattributed."

        Design: Corner/Calculations/corner_audit_failure_action_waterfall_picks_the_first_matching_branch
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=20.0,
            accountability_variant="OCCURRENCE_WEIGHTED",
        )
        store_id = build.store(jurisdiction_id, store_number="S001")
        label_id = build.certified_label_associate(store_id, employee_number="E-LA1")
        auditor_id = build.certified_auditor(store_id, employee_number="E-PA1")
        owned_one = build.aisle(
            store_id, aisle_code="A01", category_code="DAIRY", assigned_associate_id=label_id
        )
        owned_two = build.aisle(
            store_id, aisle_code="A02", category_code="BAKERY", assigned_associate_id=label_id
        )
        owned_three = build.aisle(
            store_id, aisle_code="A03", category_code="CANDY", assigned_associate_id=label_id
        )
        unowned = build.aisle(store_id, aisle_code="A04", category_code="PAPER")

        first_audit = build.audit_with_scan_lines(
            store_id,
            owned_one,
            auditor_id,
            [
                dict(item_upc="00000000005001", shelf_price_cents=100, register_price_cents=150),
                dict(item_upc="00000000005002", shelf_price_cents=100, register_price_cents=100),
                dict(item_upc="00000000005003", shelf_price_cents=100, register_price_cents=100),
                dict(item_upc="00000000005004", shelf_price_cents=100, register_price_cents=100),
            ],
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        second_audit = build.audit_with_scan_lines(
            store_id,
            owned_two,
            auditor_id,
            [
                dict(item_upc="00000000005005", shelf_price_cents=200, register_price_cents=250),
                dict(item_upc="00000000005006", shelf_price_cents=200, register_price_cents=200),
            ],
            scan_window_start="2026-08-01T10:00:00Z",
            scan_window_end="2026-08-01T11:00:00Z",
        )
        third_audit = build.audit_with_scan_lines(
            store_id,
            owned_three,
            auditor_id,
            [
                dict(item_upc="00000000005007", shelf_price_cents=300, register_price_cents=350),
            ],
            audit_type="FOLLOW_UP",
            scan_window_start="2026-08-01T12:00:00Z",
            scan_window_end="2026-08-01T13:00:00Z",
        )
        fourth_audit = build.audit_with_scan_lines(
            store_id,
            unowned,
            auditor_id,
            [
                dict(item_upc="00000000005008", shelf_price_cents=400, register_price_cents=450),
            ],
            audit_type="FOLLOW_UP",
            scan_window_start="2026-08-01T14:00:00Z",
            scan_window_end="2026-08-01T15:00:00Z",
        )
        auditor_headers = build.auditor(auditor_id)

        def ledger():
            records, meta = validate_paginated(
                api.list_associate_accountability_actions(label_id, auditor_headers)
            )
            return records, meta["total_count"]

        first_close = build.close_audit(
            first_audit["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_pct(first_close["error_rate_pct"], 25.00)
        assert first_close["outcome"] == "FAIL"
        records, total = ledger()
        assert total == 1
        # 25.00 is below the doubled 40.0 test, so the mildest branch wins.
        assert records[0]["action_type"] == "COACHING"
        assert records[0]["trigger_code"] == "AUDIT_FAIL"
        assert records[0]["issued_by_ref"] == "system"
        assert records[0]["associate_id"] == label_id

        second_close = build.close_audit(
            second_audit["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_pct(second_close["error_rate_pct"], 50.00)
        records, total = ledger()
        assert total == 2
        assert sorted(record["action_type"] for record in records) == [
            "COACHING",
            "WRITTEN_WARNING",
        ]
        after_two = build.read_associate(label_id)
        assert_pct(after_two["accountability_score"], 80)
        assert after_two["accountability_score"] == pytest.approx(
            expected_occurrence_weighted_score(["COACHING", "WRITTEN_WARNING"]), abs=0.01
        )
        # Exactly 80 is not strictly below 80.
        assert after_two["training_status"] == "CERTIFIED"

        third_close = build.close_audit(
            third_audit["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_pct(third_close["error_rate_pct"], 100.00)
        records, total = ledger()
        assert total == 3
        assert sorted(record["action_type"] for record in records) == [
            "COACHING",
            "SUSPENSION",
            "WRITTEN_WARNING",
        ]
        after_three = build.read_associate(label_id)
        assert_pct(after_three["accountability_score"], 55)
        assert after_three["training_status"] == "SUSPENDED"

        fourth_close = build.close_audit(
            fourth_audit["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_pct(fourth_close["error_rate_pct"], 100.00)
        assert fourth_close["outcome"] == "FAIL"
        records, total = ledger()
        assert total == 3

        summary = build.read_summary(store_id)
        assert summary["failed_audit_count_30d"] == 4
        assert_posture(summary, "FROZEN")
