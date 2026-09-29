"""Dual-variant arithmetic and the exact boundaries where a verdict flips."""

from test_helpers import (
    assert_instant_is,
    assert_pct,
    assert_posture,
    expected_gross_error_rate_pct,
    expected_net_overcharge_rate_pct,
    expected_occurrence_weighted_score,
    expected_task_weighted_score,
    factories,
    pct,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ERR_NO_QUALIFYING_AUDIT_DATA
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)

FIVE_LINE_SAMPLE = [
    {
        "item_upc": "00000000000101",
        "shelf_price_cents": 949,
        "register_price_cents": 1099,
    },
    {
        "item_upc": "00000000000102",
        "shelf_price_cents": 500,
        "register_price_cents": 400,
    },
    {
        "item_upc": "00000000000103",
        "shelf_price_cents": 299,
        "register_price_cents": 299,
    },
    {
        "item_upc": "00000000000104",
        "shelf_price_cents": 199,
        "register_price_cents": 199,
    },
    {
        "item_upc": "00000000000105",
        "shelf_price_cents": 399,
        "register_price_cents": 399,
    },
]


class TestGrossMismatchVariant:
    def test_gross_mismatch_counts_the_undercharge_too_and_drives_the_store_to_restricted(
        self, api, build, officer_headers
    ):
        """Both rates are stored, but only the applied one is compared to the threshold.

        PRD 3.5: "Two error rates are always computed and always stored,
        regardless of which one is going to be used."
        PRD 3.5: "The sample size is the count of every scan line belonging to the
        audit, with no status filter of any kind, because the evidence is
        immutable and therefore the set is exactly what was posted."
        PRD 3.5: "The overcharge and undercharge counts are the counts of those
        lines classified `OVERCHARGE` and `UNDERCHARGE` respectively."
        PRD 3.5: "The **gross mismatch** rate, stored as `gross_error_rate_pct`,
        is the overcharge count plus the undercharge count, divided by the sample
        size, multiplied by 100, and rounded half up to two decimal places."
        PRD 3.5: "The chosen variant is recorded in `rate_variant_applied`, and
        its value is copied into `error_rate_pct`, which is the **only** rate ever
        compared against the jurisdiction's threshold."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or
        above `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the
        comparison is inclusive, so a rate exactly equal to the threshold fails."
        PRD 3.5: "When the aisle has no assigned associate, or the referenced
        associate is already `SUSPENDED`, **no accountability action is created at
        all**: the audit still closes with `FAIL`, the store's failed-audit count
        still rises and its posture is still recomputed, and the failure is
        simply unattributed."
        PRD 2.6: "Otherwise the posture becomes `RESTRICTED` when the open finding
        count is at least 1, **or** when the thirty-day failed-audit count is
        exactly 1, **or** when the label backlog is at least 5, **or** when at
        least one signage violation exists."

        Design: Difficulty/dual_variant_calc/audit_error_rate_gross_vs_net_variant_divergence
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
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
        auditor_headers = build.auditor(auditor_id)

        built = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            FIVE_LINE_SAMPLE,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        classifications = [line["classification"] for line in built["scan_lines"]]
        assert classifications == [
            "OVERCHARGE",
            "UNDERCHARGE",
            "MATCH",
            "MATCH",
            "MATCH",
        ]

        closed = build.close_audit(
            built["audit_id"], auditor_headers, "GROSS_MISMATCH"
        )
        assert closed["sample_size"] == 5
        assert closed["overcharge_count"] == 1
        assert closed["undercharge_count"] == 1
        assert_pct(closed["gross_error_rate_pct"], 40.00)
        assert_pct(closed["gross_error_rate_pct"], expected_gross_error_rate_pct(1, 1, 5))
        assert_pct(closed["net_overcharge_rate_pct"], 0.00)
        assert_pct(
            closed["net_overcharge_rate_pct"], expected_net_overcharge_rate_pct(1, 1, 5)
        )
        assert_pct(closed["error_rate_pct"], 40.00)
        assert closed["rate_variant_applied"] == "GROSS_MISMATCH"
        assert closed["outcome"] == "FAIL"

        store = build.read_store(store_id)
        assert store["failed_audit_count_30d"] == 1
        assert_posture(store, "RESTRICTED")

        rows, meta = validate_paginated(
            api.list_associate_accountability_actions(auditor_id, officer_headers)
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestNetOverchargeVariant:
    def test_the_same_five_observations_pass_under_net_overcharge_and_fail_under_gross(
        self, api, build, officer_headers
    ):
        """One undercharge nets away one overcharge, so the floored numerator is zero.

        PRD 3.5: "The **net overcharge** rate, stored as `net_overcharge_rate_pct`,
        is the undercharge count subtracted from the overcharge count with the
        difference floored at zero, divided by the sample size, multiplied by 100,
        and rounded half up to two decimal places."
        PRD 3.5: "An optional `rate_variant` of `GROSS_MISMATCH` or
        `NET_OVERCHARGE` may be supplied on the close request; when it is omitted,
        the jurisdiction's `default_rate_variant` decides."
        PRD 3.5: "The difference between the variants is not cosmetic: gross
        mismatch counts every discrepancy, so undercharges that cost the customer
        nothing still inflate the rate, while net overcharge nets undercharges
        against overcharges and floors at zero, meaning an identical set of
        observations can pass under one variant and fail under the other."
        PRD 3.5: "Closing also stamps `closed_at` with the current instant and
        refreshes the audited aisle's `last_audit_closed_at` to the same instant."

        Design: Difficulty/dual_variant_calc/audit_error_rate_gross_vs_net_variant_divergence
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_one = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        aisle_two = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )

        gross = build.closed_audit(
            store_id,
            aisle_one,
            auditor_id,
            FIVE_LINE_SAMPLE,
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        net = build.closed_audit(
            store_id,
            aisle_two,
            auditor_id,
            FIVE_LINE_SAMPLE,
            rate_variant="NET_OVERCHARGE",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        gross_audit = build.read_audit(gross["audit_id"])
        net_audit = build.read_audit(net["audit_id"])

        assert gross_audit["sample_size"] == net_audit["sample_size"] == 5
        assert gross_audit["overcharge_count"] == net_audit["overcharge_count"] == 1
        assert gross_audit["undercharge_count"] == net_audit["undercharge_count"] == 1
        for audit in (gross_audit, net_audit):
            assert_pct(audit["gross_error_rate_pct"], 40.00)
            assert_pct(audit["net_overcharge_rate_pct"], 0.00)

        assert net_audit["rate_variant_applied"] == "NET_OVERCHARGE"
        assert_pct(net_audit["error_rate_pct"], 0.00)
        assert net_audit["outcome"] == "PASS"
        assert gross_audit["rate_variant_applied"] == "GROSS_MISMATCH"
        assert_pct(gross_audit["error_rate_pct"], 40.00)
        assert gross_audit["outcome"] == "FAIL"
        assert_pct(
            pct(gross_audit["error_rate_pct"]) - pct(net_audit["error_rate_pct"]), 40.00
        )

        assert_instant_is(gross_audit["closed_at"], "2026-08-01T00:00:00Z")
        assert_instant_is(
            build.read_aisle(aisle_one)["last_audit_closed_at"], "2026-08-01T00:00:00Z"
        )
        assert_instant_is(
            build.read_aisle(aisle_two)["last_audit_closed_at"], "2026-08-01T00:00:00Z"
        )

        store = build.read_store(store_id)
        assert store["failed_audit_count_30d"] == 1
        assert_posture(store, "RESTRICTED")

        rows, meta = validate_paginated(
            api.list_associate_accountability_actions(auditor_id, officer_headers)
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestAccountabilityVariantDivergence:
    def test_one_identical_coaching_action_suspends_only_under_the_task_weighted_variant(
        self, build
    ):
        """Two jurisdictions, one weight of 5, and two different certification standings.

        PRD 2.5: "`accountability_variant` selects the associate scoring variant and
        is either `OCCURRENCE_WEIGHTED` (the default) or `TASK_WEIGHTED`."
        PRD 3.2: "The weight assigned to an action by its `action_type` is 5 for
        `COACHING`, 10 for `RETRAINING_ASSIGNED`, 15 for `WRITTEN_WARNING` and 25 for
        `SUSPENSION`, and that weight is stored on the action itself as
        `score_weight`."
        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the sum of
        the weights of the outstanding actions, floored at zero — each issued action
        costs its flat weight regardless of how much correct work the associate has
        done."
        PRD 3.2: "Under `TASK_WEIGHTED`, the outstanding weight sum is first
        multiplied by 40, that product is then divided by the associate's verified
        placement count plus 4, the quotient is subtracted from 100, the difference
        is rounded half up to two decimal places, and the result is floored at zero."
        PRD 3.2: "The suspension floor is 80, and the comparison is **strict**: a
        recomputed score of exactly 80 does not suspend, a score of 79.99 does."
        PRD 3.2: "A newly issued action starts `ISSUED`, has its `score_weight`
        computed from its `action_type`, and immediately re-derives the target
        associate's `issued_action_count` and `accountability_score` — which can
        drive the `CERTIFIED → SUSPENDED` transition and its whole downstream chain
        inside the very same request."

        Design: Difficulty/dual_variant_calc/accountability_score_occurrence_vs_task_weighted_divergence
        """
        occurrence_jurisdiction = build.jurisdiction(
            code="US-CA",
            name="California",
            accountability_variant="OCCURRENCE_WEIGHTED",
            scanner_error_rate_threshold_pct=25.0,
        )
        task_jurisdiction = build.jurisdiction(
            code="US-NY",
            name="New York",
            accountability_variant="TASK_WEIGHTED",
            scanner_error_rate_threshold_pct=25.0,
        )
        occurrence_store = build.store(
            occurrence_jurisdiction, store_number="S001", name="Bay Street"
        )
        task_store = build.store(
            task_jurisdiction, store_number="S002", name="Hudson Yards"
        )
        occurrence_associate = build.certified(
            occurrence_store,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        task_associate = build.certified(
            task_store,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Nina Label",
        )
        assert build.read_associate(occurrence_associate)["verified_placement_count"] == 0
        assert build.read_associate(task_associate)["verified_placement_count"] == 0

        occurrence_action = build.issue_action(
            occurrence_associate, "COACHING", source_ref="manual-review-1"
        )
        task_action = build.issue_action(
            task_associate, "COACHING", source_ref="manual-review-2"
        )
        assert occurrence_action["score_weight"] == 5
        assert task_action["score_weight"] == 5
        assert occurrence_action["status"] == "ISSUED"
        assert task_action["status"] == "ISSUED"

        occurrence_record = build.read_associate(occurrence_associate)
        task_record = build.read_associate(task_associate)
        assert occurrence_record["verified_placement_count"] == 0
        assert task_record["verified_placement_count"] == 0
        assert occurrence_record["issued_action_count"] == 1
        assert task_record["issued_action_count"] == 1

        assert_pct(occurrence_record["accountability_score"], 95)
        assert_pct(
            occurrence_record["accountability_score"],
            expected_occurrence_weighted_score(["COACHING"]),
        )
        assert occurrence_record["training_status"] == "CERTIFIED"

        assert_pct(task_record["accountability_score"], 50.00)
        assert_pct(
            task_record["accountability_score"],
            expected_task_weighted_score(["COACHING"], 0),
        )
        assert task_record["training_status"] == "SUSPENDED"

    def test_a_single_verified_placement_moves_only_the_task_weighted_denominator(
        self, build
    ):
        """Occurrence weighting ignores demonstrated work; task weighting divides by count plus four.

        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the sum of
        the weights of the outstanding actions, floored at zero — each issued action
        costs its flat weight regardless of how much correct work the associate has
        done."
        PRD 3.2: "Under `TASK_WEIGHTED`, the outstanding weight sum is first
        multiplied by 40, that product is then divided by the associate's verified
        placement count plus 4, the quotient is subtracted from 100, the difference
        is rounded half up to two decimal places, and the result is floored at zero."
        PRD 3.2: "The verified placement count used here is the number of label tasks
        whose `placed_by_associate_id` is this associate and whose placement axis
        reads `VERIFIED`."
        PRD 3.4: "Within the same request it also recomputes the **placer's**
        `verified_placement_count` — not the verifier's — because that counter feeds
        the task-weighted accountability variant, and it recomputes the store's label
        backlog and then its posture."

        Design: Difficulty/dual_variant_calc/accountability_score_occurrence_vs_task_weighted_divergence
        """
        scores = {}
        for code, name, variant, store_number, file_number in (
            ("US-CA", "California", "OCCURRENCE_WEIGHTED", "S001", "PCF-1"),
            ("US-NY", "New York", "TASK_WEIGHTED", "S002", "PCF-2"),
        ):
            jurisdiction_id = build.jurisdiction(
                code=code, name=name, accountability_variant=variant
            )
            store_id = build.store(
                jurisdiction_id, store_number=store_number, name="Bay Street"
            )
            associate_id = build.certified(
                store_id,
                ROLE_CODE_LABEL_ASSOCIATE,
                employee_number="E-LA1",
                full_name="Lena Label",
            )
            manager_id = build.certified(
                store_id,
                ROLE_CODE_STORE_MANAGER,
                employee_number="E-SM1",
                full_name="Sam Manager",
            )
            aisle_id = build.aisle(
                store_id,
                aisle_code="A01",
                category_code="DAIRY",
                assigned_associate_id=associate_id,
            )
            built = build.distributed_file(
                jurisdiction_id,
                [store_id],
                [
                    {
                        "item_upc": "00000000030001",
                        "new_retail_cents": 449,
                        "old_retail_cents": 499,
                        "net_content_qty": 1,
                        "net_content_uom": "GAL",
                        "item_description": "Milk 1 GAL",
                        "category_code": "DAIRY",
                    }
                ],
                file_number=file_number,
            )
            placed = build.placed_task(
                built["file_id"],
                store_id,
                built["line_ids"][0],
                aisle_id,
                associate_id,
                449,
                scheduled_start_at="2026-08-03T08:00:00Z",
                scheduled_end_at="2026-08-03T10:00:00Z",
                expected_price_change_file_version=built["version"],
            )
            assert placed["task"]["placed_by_associate_id"] == associate_id
            verified = build.verify_task(placed["task_id"], build.manager(manager_id))
            assert verified["placement_status"] == "VERIFIED"

            after_verification = build.read_associate(associate_id)
            assert after_verification["verified_placement_count"] == 1
            assert_pct(after_verification["accountability_score"], 100)
            assert after_verification["training_status"] == "CERTIFIED"

            action = build.issue_action(
                associate_id, "COACHING", source_ref="manual-review-1"
            )
            assert action["score_weight"] == 5
            record = build.read_associate(associate_id)
            assert record["verified_placement_count"] == 1
            scores[variant] = record

        assert_pct(scores["OCCURRENCE_WEIGHTED"]["accountability_score"], 95)
        assert_pct(
            scores["OCCURRENCE_WEIGHTED"]["accountability_score"],
            expected_occurrence_weighted_score(["COACHING"]),
        )
        assert scores["OCCURRENCE_WEIGHTED"]["training_status"] == "CERTIFIED"

        assert_pct(scores["TASK_WEIGHTED"]["accountability_score"], 60.00)
        assert_pct(
            scores["TASK_WEIGHTED"]["accountability_score"],
            expected_task_weighted_score(["COACHING"], 1),
        )
        assert scores["TASK_WEIGHTED"]["training_status"] == "SUSPENDED"


MATCHING_FILLER = [
    ("00000000000702", 299),
    ("00000000000703", 199),
    ("00000000000704", 399),
    ("00000000000705", 259),
]


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
        _, price = MATCHING_FILLER[index]
        sample.append(
            {
                "item_upc": upc_prefix + str(index + 2),
                "shelf_price_cents": price,
                "register_price_cents": price,
            }
        )
    return sample


class TestAuditThresholdInclusiveBoundary:
    def test_twenty_then_exactly_twenty_five_then_thirty_three_point_three_three(
        self, build
    ):
        """Equality fails, and the compared rate is the half-up two-decimal value.

        PRD 3.5: "The **gross mismatch** rate, stored as `gross_error_rate_pct`, is
        the overcharge count plus the undercharge count, divided by the sample size,
        multiplied by 100, and rounded half up to two decimal places."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or above
        `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the comparison is
        inclusive, so a rate exactly equal to the threshold fails."
        PRD 2.5: "`scanner_error_rate_threshold_pct` is the inclusive failure
        threshold for an audit's error rate; it must be greater than 0, at most 100,
        carry at most two decimals, and defaults to 2.0."
        PRD 2.6: "The posture becomes `FROZEN` when at least one escalated finding
        exists, **or** when the open finding count is at least 3, **or** when the
        thirty-day failed-audit count is at least 2."

        Design: Difficulty/boundary_precision_check/audit_outcome_threshold_is_inclusive_at_exactly_the_percentage
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        auditor_headers = build.auditor(auditor_id)

        audits = {}
        for aisle_code, sample_size, upc_prefix in (
            ("A01", 5, "0000000000070"),
            ("A02", 4, "0000000000071"),
            ("A03", 3, "0000000000072"),
        ):
            aisle_id = build.aisle(
                store_id, aisle_code=aisle_code, category_code="DAIRY"
            )
            audits[aisle_code] = build.audit_with_scan_lines(
                store_id,
                aisle_id,
                auditor_id,
                _one_overcharge_sample(sample_size, upc_prefix),
                scan_window_start="2026-08-01T08:00:00Z",
                scan_window_end="2026-08-01T09:00:00Z",
            )

        below = build.close_audit(audits["A01"]["audit_id"], auditor_headers)
        assert below["sample_size"] == 5
        assert below["overcharge_count"] == 1
        assert below["undercharge_count"] == 0
        assert_pct(below["error_rate_pct"], 20.00)
        assert below["outcome"] == "PASS"
        assert build.read_store(store_id)["failed_audit_count_30d"] == 0

        at_threshold = build.close_audit(audits["A02"]["audit_id"], auditor_headers)
        assert at_threshold["sample_size"] == 4
        assert at_threshold["overcharge_count"] == 1
        assert_pct(at_threshold["error_rate_pct"], 25.00)
        assert at_threshold["outcome"] == "FAIL"
        after_one_failure = build.read_store(store_id)
        assert after_one_failure["failed_audit_count_30d"] == 1
        assert_posture(after_one_failure, "RESTRICTED")

        above = build.close_audit(audits["A03"]["audit_id"], auditor_headers)
        assert above["sample_size"] == 3
        assert above["overcharge_count"] == 1
        assert_pct(above["error_rate_pct"], 33.33)
        assert above["outcome"] == "FAIL"

        for closed in (below, at_threshold, above):
            assert closed["rate_variant_applied"] == "GROSS_MISMATCH"
            assert_pct(closed["gross_error_rate_pct"], pct(closed["error_rate_pct"]))
            assert_pct(
                closed["net_overcharge_rate_pct"], pct(closed["error_rate_pct"])
            )
            assert_pct(
                closed["gross_error_rate_pct"],
                expected_gross_error_rate_pct(1, 0, closed["sample_size"]),
            )

        final_store = build.read_store(store_id)
        assert final_store["failed_audit_count_30d"] == 2
        assert_posture(final_store, "FROZEN")

    def test_the_rounded_value_and_not_the_raw_quotient_is_what_meets_the_threshold(
        self, build
    ):
        """Thirty-three point three three fails a 33.33 threshold and passes a 33.34 one.

        PRD 3.5: "The **gross mismatch** rate, stored as `gross_error_rate_pct`, is
        the overcharge count plus the undercharge count, divided by the sample size,
        multiplied by 100, and rounded half up to two decimal places."
        PRD 3.5: "The chosen variant is recorded in `rate_variant_applied`, and its
        value is copied into `error_rate_pct`, which is the **only** rate ever
        compared against the jurisdiction's threshold."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or above
        `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the comparison is
        inclusive, so a rate exactly equal to the threshold fails."
        PRD 2.6: "Otherwise the posture becomes `RESTRICTED` when the open finding
        count is at least 1, **or** when the thirty-day failed-audit count is exactly
        1, **or** when the label backlog is at least 5, **or** when at least one
        signage violation exists."

        Design: Difficulty/boundary_precision_check/audit_outcome_threshold_is_inclusive_at_exactly_the_percentage
        """
        outcomes = {}
        for code, name, store_number, threshold in (
            ("US-CA", "California", "S001", 33.33),
            ("US-NY", "New York", "S002", 33.34),
        ):
            jurisdiction_id = build.jurisdiction(
                code=code,
                name=name,
                scanner_error_rate_threshold_pct=threshold,
                default_rate_variant="GROSS_MISMATCH",
            )
            store_id = build.store(
                jurisdiction_id, store_number=store_number, name="Bay Street"
            )
            aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
            auditor_id = build.certified(
                store_id,
                ROLE_CODE_PRICE_AUDITOR,
                module_code="AUDIT_101",
                employee_number="E-PA1",
                full_name="Pat Auditor",
            )
            closed = build.closed_audit(
                store_id,
                aisle_id,
                auditor_id,
                _one_overcharge_sample(3, "0000000000073"),
                scan_window_start="2026-08-01T08:00:00Z",
                scan_window_end="2026-08-01T09:00:00Z",
            )["audit"]
            assert closed["sample_size"] == 3
            assert closed["overcharge_count"] == 1
            assert closed["undercharge_count"] == 0
            assert_pct(closed["error_rate_pct"], 33.33)
            assert_pct(closed["gross_error_rate_pct"], 33.33)
            assert closed["rate_variant_applied"] == "GROSS_MISMATCH"
            outcomes[threshold] = (closed, build.read_store(store_id))

        exactly_at, at_store = outcomes[33.33]
        assert exactly_at["outcome"] == "FAIL"
        assert at_store["failed_audit_count_30d"] == 1
        assert_posture(at_store, "RESTRICTED")

        just_under, under_store = outcomes[33.34]
        assert just_under["outcome"] == "PASS"
        assert under_store["failed_audit_count_30d"] == 0
        assert_posture(under_store, "OPEN")


class TestExceptionReportWindowAndSampleFloor:
    def _store_with_two_closed_audits(self, build):
        """A store whose BAKERY audit closes on 08-05 with one line and DAIRY on 08-10 with two."""
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=60.0,
            default_rate_variant="GROSS_MISMATCH",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        dairy_aisle = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        bakery_aisle = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        auditor_headers = build.auditor(auditor_id)

        bakery_audit = build.audit_with_scan_lines(
            store_id,
            bakery_aisle,
            auditor_id,
            [
                {
                    "item_upc": "00000000000901",
                    "shelf_price_cents": 349,
                    "register_price_cents": 499,
                }
            ],
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        dairy_audit = build.audit_with_scan_lines(
            store_id,
            dairy_aisle,
            auditor_id,
            [
                {
                    "item_upc": "00000000000911",
                    "shelf_price_cents": 949,
                    "register_price_cents": 1099,
                },
                {
                    "item_upc": "00000000000912",
                    "shelf_price_cents": 299,
                    "register_price_cents": 299,
                },
            ],
            scan_window_start="2026-08-01T10:00:00Z",
            scan_window_end="2026-08-01T11:00:00Z",
        )
        build.set_clock("2026-08-05T00:00:00Z")
        bakery_closed = build.close_audit(bakery_audit["audit_id"], auditor_headers)
        assert_instant_is(bakery_closed["closed_at"], "2026-08-05T00:00:00Z")
        build.set_clock("2026-08-10T00:00:00Z")
        dairy_closed = build.close_audit(dairy_audit["audit_id"], auditor_headers)
        assert_instant_is(dairy_closed["closed_at"], "2026-08-10T00:00:00Z")
        build.set_clock("2026-08-20T00:00:00Z")
        return store_id

    def test_the_lower_bound_admits_the_audit_the_upper_bound_rejects_and_a_lone_line_is_dropped(
        self, api, build, officer_headers
    ):
        """Three windows over the same two audits: 201, 422 and 201 with the anecdote discarded.

        PRD 3.9: "A compliance officer or store manager generates a report by naming
        the `store_id` and a half-open reporting window as `period_start_at`
        (inclusive) and `period_end_at` (exclusive, strictly after the start)."
        PRD 3.9: "The qualifying audits are this store's audits whose status is
        `CLOSED` and whose closing instant falls at or after `period_start_at` and
        strictly before `period_end_at`; audits sitting in `OPEN`, `SCANNING` or
        `REOPENED` are excluded entirely, which means reopening an audit removes it
        from reports generated afterwards."
        PRD 3.9: "`audit_count` is the number of qualifying audits and
        `scan_line_count` is the total number of scan lines belonging to them."
        PRD 3.9: "Only groups whose sample size is at least 2 are eligible for the
        ranking — a single scan line is anecdote, not evidence."
        PRD 3.9: "The ordered list is stored as `category_breakdown`, each element
        carrying `category_code`, `sample_size`, `error_count` and `error_rate_pct`."
        PRD 3.9: "When no category is eligible — because the window caught no closed
        audits, or every category had a single line — the report is **not** created
        and the request fails with `ERR_NO_QUALIFYING_AUDIT_DATA`."

        Design: Difficulty/boundary_precision_check/exception_report_min_sample_and_half_open_window_boundaries
        """
        store_id = self._store_with_two_closed_audits(build)

        lower_bound = build.exception_report(
            store_id, "2026-08-10T00:00:00Z", "2026-08-15T00:00:00Z"
        )
        assert lower_bound["audit_count"] == 1
        assert lower_bound["scan_line_count"] == 2
        assert lower_bound["status"] == "GENERATED"
        assert lower_bound["top_category_code"] == "DAIRY"
        assert_pct(lower_bound["top_category_error_rate_pct"], 50.00)
        assert len(lower_bound["category_breakdown"]) == 1
        only_group = lower_bound["category_breakdown"][0]
        assert only_group["category_code"] == "DAIRY"
        assert only_group["sample_size"] == 2
        assert only_group["error_count"] == 1
        assert_pct(only_group["error_rate_pct"], 50.00)

        validate_error(
            api.create_exception_report(
                factories.exception_report_payload(
                    store_id, "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z"
                ),
                officer_headers,
            ),
            ERR_NO_QUALIFYING_AUDIT_DATA,
            422,
        )
        rows, meta = validate_paginated(
            api.list_exception_reports(officer_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [lower_bound["id"]]

        both = build.exception_report(
            store_id, "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z"
        )
        assert both["audit_count"] == 2
        assert both["scan_line_count"] == 3
        assert len(both["category_breakdown"]) == 1
        assert both["category_breakdown"][0]["category_code"] == "DAIRY"
        assert both["category_breakdown"][0]["sample_size"] == 2
        assert both["top_category_code"] == "DAIRY"
        assert_pct(both["top_category_error_rate_pct"], 50.00)
        assert "BAKERY" not in [
            group["category_code"] for group in both["category_breakdown"]
        ]

    def test_the_window_edges_are_decided_to_the_second_and_a_one_second_window_qualifies(
        self, api, build, officer_headers
    ):
        """A window one second wide admits the audit that closed on its lower edge.

        PRD 3.9: "A compliance officer or store manager generates a report by naming
        the `store_id` and a half-open reporting window as `period_start_at`
        (inclusive) and `period_end_at` (exclusive, strictly after the start)."
        PRD 3.9: "The qualifying audits are this store's audits whose status is
        `CLOSED` and whose closing instant falls at or after `period_start_at` and
        strictly before `period_end_at`; audits sitting in `OPEN`, `SCANNING` or
        `REOPENED` are excluded entirely, which means reopening an audit removes it
        from reports generated afterwards."
        PRD 3.9: "Only groups whose sample size is at least 2 are eligible for the
        ranking — a single scan line is anecdote, not evidence."
        PRD 3.9: "When no category is eligible — because the window caught no closed
        audits, or every category had a single line — the report is **not** created
        and the request fails with `ERR_NO_QUALIFYING_AUDIT_DATA`."
        PRD 3.9: "Only one report may exist per store-and-period triple, a repeat
        yielding `ERR_DUPLICATE_RESOURCE`."

        Design: Difficulty/boundary_precision_check/exception_report_min_sample_and_half_open_window_boundaries
        """
        store_id = self._store_with_two_closed_audits(build)

        one_second = build.exception_report(
            store_id, "2026-08-10T00:00:00Z", "2026-08-10T00:00:01Z"
        )
        assert one_second["audit_count"] == 1
        assert one_second["scan_line_count"] == 2
        assert one_second["top_category_code"] == "DAIRY"
        assert_pct(one_second["top_category_error_rate_pct"], 50.00)
        assert_instant_is(one_second["period_start_at"], "2026-08-10T00:00:00Z")
        assert_instant_is(one_second["period_end_at"], "2026-08-10T00:00:01Z")

        validate_error(
            api.create_exception_report(
                factories.exception_report_payload(
                    store_id, "2026-08-10T00:00:01Z", "2026-08-15T00:00:00Z"
                ),
                officer_headers,
            ),
            ERR_NO_QUALIFYING_AUDIT_DATA,
            422,
        )

        widened = build.exception_report(
            store_id, "2026-08-05T00:00:00Z", "2026-08-10T00:00:01Z"
        )
        assert widened["audit_count"] == 2
        assert widened["scan_line_count"] == 3
        assert len(widened["category_breakdown"]) == 1
        assert widened["category_breakdown"][0]["category_code"] == "DAIRY"
        assert widened["category_breakdown"][0]["error_count"] == 1
        assert widened["id"] != one_second["id"]

        rows, meta = validate_paginated(
            api.list_exception_reports(officer_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted(
            [one_second["id"], widened["id"]]
        )
