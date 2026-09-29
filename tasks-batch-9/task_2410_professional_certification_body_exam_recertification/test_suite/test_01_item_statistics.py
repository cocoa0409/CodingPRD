"""Item statistics: the two accumulator bases and the responses floor."""

import pytest

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import PSYCHOMETRICIAN_ID, make_psychometrician_headers

PSY = make_psychometrician_headers(PSYCHOMETRICIAN_ID)

PRETEST_BATCH = f.response_batch_payload(is_pretest=True, response_count=20, correct_count=18,
                                         upper_n=6, upper_correct=6, lower_n=6, lower_correct=5)
OPERATIONAL_BATCH = f.response_batch_payload(is_pretest=False, response_count=20,
                                             correct_count=10, upper_n=5, upper_correct=5,
                                             lower_n=5, lower_correct=1)


def _programme_with_approved_item(api, credential_code, name, stat_basis, stem):
    program = fx.active_program(api, name=name, credential_code=credential_code,
                               psychometric_stat_basis=stat_basis)
    item = fx.approved_item(api, program["id"], stem=stem)
    return program, item


class TestItemStatisticsAccumulatorBasis:
    """One pair of accumulator histories, two programme-level answers."""

    def test_pooled_basis_merges_pretest_evidence_and_computes_both_statistics(self, api):
        """Under POOLED the working totals are the sums of the pretest and
        operational accumulators, so 28 correct out of 40 responses gives a
        p_value of 0.7000 and an upper-minus-lower discrimination of 0.4545.

        PRD §3.3: "Under the `POOLED` basis, each working total is the sum of the
        corresponding pretest and operational accumulators".

        Design: Difficulty/dual_variant_calc/item_statistics_pooled_vs_operational_only_diverge_on_identical_accumulators
        """
        program, item = _programme_with_approved_item(
            api, "CPX", "Certified Practitioner X", "POOLED", "Pooled-basis anchor item")

        validate_success(api.ingest_response_batch(item["id"], PRETEST_BATCH, PSY), 200)
        pooled = validate_success(
            api.ingest_response_batch(item["id"], OPERATIONAL_BATCH, PSY), 200)

        assert pooled["pretest_response_count"] == 20
        assert pooled["operational_response_count"] == 20
        assert pooled["stat_basis_applied"] == "POOLED"
        assert pooled["p_value"] == pytest.approx(0.7000, abs=1e-9)
        assert pooled["discrimination_index"] == pytest.approx(0.4545, abs=1e-9)
        ax.assert_item_stat_precision(pooled["p_value"])
        ax.assert_item_stat_precision(pooled["discrimination_index"])
        assert pooled["flag_reason"] is None
        assert pooled["status"] == "OPERATIONAL"

    def test_operational_only_basis_ignores_the_same_pretest_evidence_entirely(self, api):
        """Under OPERATIONAL_ONLY the identical twelve accumulators yield only 20
        working responses, which is below the floor of 30, so both statistics stay
        null and the item is stranded in PRETEST.

        PRD §3.3: "Pretest evidence is ignored entirely under this basis, even in
        the common case where it holds the bulk of the responses."

        PRD §3.3: "If the working response total is strictly less than the
        program's `min_responses_for_stats`, or the upper-group size is zero, or
        the lower-group size is zero, then `stat_basis_applied` is set to
        `INSUFFICIENT_DATA` and both `p_value` and `discrimination_index` are set
        to null".

        Design: Difficulty/dual_variant_calc/item_statistics_pooled_vs_operational_only_diverge_on_identical_accumulators
        """
        program, item = _programme_with_approved_item(
            api, "CPY", "Certified Practitioner Y", "OPERATIONAL_ONLY",
            "Operational-only anchor item")

        validate_success(api.ingest_response_batch(item["id"], PRETEST_BATCH, PSY), 200)
        withheld = validate_success(
            api.ingest_response_batch(item["id"], OPERATIONAL_BATCH, PSY), 200)

        assert withheld["pretest_response_count"] == 20
        assert withheld["operational_response_count"] == 20
        assert withheld["stat_basis_applied"] == "INSUFFICIENT_DATA"
        assert withheld["p_value"] is None
        assert withheld["discrimination_index"] is None
        assert withheld["status"] == "PRETEST"

    def test_only_the_pooled_programme_reaches_a_complete_blueprint(self, api):
        """The basis flag decides whether the item ever crosses the operational
        boundary, and therefore whether the owning programme's blueprint is
        covered at all.

        PRD §3.3: "A `PRETEST → OPERATIONAL` or `FLAGGED → OPERATIONAL` move
        increases the program's `operational_item_count` by 1 and then recomputes
        `deficient_domain_codes` and `blueprint_posture`".

        Design: Difficulty/dual_variant_calc/item_statistics_pooled_vs_operational_only_diverge_on_identical_accumulators
        """
        pooled_program, pooled_item = _programme_with_approved_item(
            api, "CPX", "Certified Practitioner X", "POOLED", "Pooled-basis anchor item")
        strict_program, strict_item = _programme_with_approved_item(
            api, "CPY", "Certified Practitioner Y", "OPERATIONAL_ONLY",
            "Operational-only anchor item")

        for item_id in (pooled_item["id"], strict_item["id"]):
            validate_success(api.ingest_response_batch(item_id, PRETEST_BATCH, PSY), 200)
            validate_success(api.ingest_response_batch(item_id, OPERATIONAL_BATCH, PSY), 200)

        pooled_after = fx.read_program(api, pooled_program["id"])
        strict_after = fx.read_program(api, strict_program["id"])

        assert pooled_after["operational_item_count"] == 1
        assert pooled_after["deficient_domain_codes"] == []
        assert pooled_after["blueprint_posture"] == "COMPLETE"
        ax.assert_blueprint_posture_agrees_with_counts(pooled_after)

        assert strict_after["operational_item_count"] == 0
        assert strict_after["deficient_domain_codes"] == ["D1"]
        assert strict_after["blueprint_posture"] == "DEFICIENT"
        ax.assert_blueprint_posture_agrees_with_counts(strict_after)


class TestResponseFloorAndFourDecimalRounding:
    """29 responses withhold statistics; the 30th computes them."""

    def test_twenty_nine_pooled_responses_leave_both_statistics_null(self, api):
        """The floor is compared strictly, so 29 responses against a floor of 30
        withhold the statistics while the first pretest batch still promotes the
        item out of APPROVED.

        PRD §3.3: "An `APPROVED` item receiving its first batch with `is_pretest`
        true moves `APPROVED → PRETEST`."

        Design: Difficulty/boundary_precision_check/item_statistics_gate_at_29_versus_30_pooled_responses_and_four_dp_p_value
        """
        program = fx.active_program(api, psychometric_stat_basis="POOLED")
        item = fx.approved_item(api, program["id"], stem="Boundary item")

        below = validate_success(api.ingest_response_batch(
            item["id"],
            f.response_batch_payload(is_pretest=True, response_count=29, correct_count=19,
                                     upper_n=10, upper_correct=9, lower_n=10, lower_correct=3),
            PSY), 200)

        assert below["pretest_response_count"] == 29
        assert below["stat_basis_applied"] == "INSUFFICIENT_DATA"
        assert below["p_value"] is None
        assert below["discrimination_index"] is None
        assert below["flag_reason"] is None
        assert below["status"] == "PRETEST"

        program_after = fx.read_program(api, program["id"])
        assert program_after["operational_item_count"] == 0
        assert program_after["blueprint_posture"] == "DEFICIENT"

    def test_thirtieth_response_crosses_the_floor_and_rounds_half_up_to_four_decimals(self, api):
        """A working total of exactly 30 computes, and 20/30 is carried as 0.6667
        rather than the 0.6666 that truncation would produce.

        PRD §3.3: "Because the floor comparison is strict, a working response
        total of exactly `min_responses_for_stats` — 30 responses under the
        default — does compute statistics rather than withholding them."

        PRD §2.6: "an item's `p_value` and `discrimination_index` are each rounded
        half up to four decimals".

        Design: Difficulty/boundary_precision_check/item_statistics_gate_at_29_versus_30_pooled_responses_and_four_dp_p_value
        """
        program = fx.active_program(api, psychometric_stat_basis="POOLED")
        item = fx.approved_item(api, program["id"], stem="Boundary item")

        validate_success(api.ingest_response_batch(
            item["id"],
            f.response_batch_payload(is_pretest=True, response_count=29, correct_count=19,
                                     upper_n=10, upper_correct=9, lower_n=10, lower_correct=3),
            PSY), 200)
        at_floor = validate_success(api.ingest_response_batch(
            item["id"],
            f.response_batch_payload(is_pretest=True, response_count=1, correct_count=1,
                                     upper_n=0, upper_correct=0, lower_n=0, lower_correct=0),
            PSY), 200)

        assert at_floor["pretest_response_count"] == 30
        assert at_floor["pretest_correct_count"] == 20
        assert at_floor["pretest_upper_n"] == 10
        assert at_floor["pretest_lower_n"] == 10
        assert at_floor["stat_basis_applied"] == "POOLED"
        assert at_floor["p_value"] == pytest.approx(0.6667, abs=1e-9)
        assert at_floor["p_value"] != pytest.approx(0.6666, abs=1e-9)
        assert at_floor["discrimination_index"] == pytest.approx(0.6000, abs=1e-9)
        ax.assert_item_stat_precision(at_floor["p_value"])

    def test_crossing_the_floor_promotes_the_item_and_covers_the_blueprint(self, api):
        """With sufficient data and no flag the item becomes operational, which
        cascades into the programme's coverage fields.

        PRD §3.3: "a null `flag_reason` moves the item `PRETEST → OPERATIONAL`".

        Design: Difficulty/boundary_precision_check/item_statistics_gate_at_29_versus_30_pooled_responses_and_four_dp_p_value
        """
        program = fx.active_program(api, psychometric_stat_basis="POOLED")
        item = fx.approved_item(api, program["id"], stem="Boundary item")

        validate_success(api.ingest_response_batch(
            item["id"],
            f.response_batch_payload(is_pretest=True, response_count=29, correct_count=19,
                                     upper_n=10, upper_correct=9, lower_n=10, lower_correct=3),
            PSY), 200)
        promoted = validate_success(api.ingest_response_batch(
            item["id"],
            f.response_batch_payload(is_pretest=True, response_count=1, correct_count=1,
                                     upper_n=0, upper_correct=0, lower_n=0, lower_correct=0),
            PSY), 200)

        assert promoted["flag_reason"] is None
        assert promoted["status"] == "OPERATIONAL"
        ax.assert_item(promoted)

        program_after = fx.read_program(api, program["id"])
        assert program_after["operational_item_count"] == 1
        assert program_after["deficient_domain_codes"] == []
        assert program_after["blueprint_posture"] == "COMPLETE"
