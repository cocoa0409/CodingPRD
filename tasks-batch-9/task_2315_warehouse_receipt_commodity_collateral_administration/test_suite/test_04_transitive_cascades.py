"""
Multi-hop cascades: a bin going out of condition reaching the lender's credit
line, and a critical examination finding reaching the deposit tickets.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    SECOND_REGULATOR_HEADERS,
    SECOND_REGULATOR_USER_ID,
)


class TestBinImpairmentCascade:
    @pytest.fixture
    def impaired_chain(self, api, base_full, set_clock, assess_bin):
        """A perfected mark-to-market lien, then the bin goes out of condition."""
        set_clock("2026-08-20T09:00:00Z")
        lien = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"], base_full["lender_id"]
                ),
                base_full["lender_headers"],
            ),
            201,
        )
        get_success_data(
            api.perfect_lien(
                lien["id"], f.perfect_payload(), base_full["lender_headers"]
            ),
            200,
        )
        assessed_bin = assess_bin(
            base_full["warehouse_id"], base_full["bin_id"], 16.0, 70
        )
        return {"lien_id": lien["id"], "bin": assessed_bin, "scenario": base_full}

    def test_out_of_condition_bin_flips_the_receipt_quality_flag_to_impaired(
        self, api, impaired_chain
    ):
        """
        A 16.0 percent moisture reading puts the bin OUT_OF_CONDITION, and the
        first cascade hop recomputes the quality flag of every issued receipt on
        that bin to IMPAIRED.

        PRD: "Every `ISSUED` receipt on that bin recomputes `quality_flag` to
        `IMPAIRED`."

        Design: Difficulty/transitive_cascade/bin_out_of_condition_impairs_receipt_then_lien_then_lender_credit
        """
        scenario = impaired_chain["scenario"]
        assert_fields_equal(
            impaired_chain["bin"],
            {"condition_state": "OUT_OF_CONDITION", "last_moisture_pct": 16.0},
        )

        receipt = get_success_data(
            api.get_receipt(scenario["receipt_id"], scenario["operator_headers"]), 200
        )
        assert receipt["quality_flag"] == "IMPAIRED"

    def test_impairment_revalues_the_perfected_lien_and_the_lenders_committed_advance(
        self, api, impaired_chain
    ):
        """
        The impairment adds 2500 basis points of discount, so eligible value
        falls to 320288, the admin fee to 801, the warehouseman lien to 11809,
        net collateral to 308479 and the limit to 215935 — leaving the 250000
        principal 34065 cents short — and the lender's committed advance follows
        the new limit down while the lien stays PERFECTED.

        PRD: "Every `PERFECTED` lien on those receipts is revalued, its
        `grade_discount_bps` gaining the 2500-basis-point impairment penalty,
        which lowers `eligible_value_cents`, lowers `advance_limit_cents`, and
        may flip `margin_status` to `DEFICIENT`."

        Design: Difficulty/transitive_cascade/bin_out_of_condition_impairs_receipt_then_lien_then_lender_credit
        """
        scenario = impaired_chain["scenario"]
        lien = get_success_data(
            api.get_collateral_lien(
                impaired_chain["lien_id"], scenario["lender_headers"]
            ),
            200,
        )
        assert_fields_equal(
            lien,
            {
                "grade_discount_bps": 2500,
                "eligible_value_cents": 320288,
                "admin_fee_cents": 801,
                "warehouseman_lien_cents": 11809,
                "net_collateral_cents": 308479,
                "advance_limit_cents": 215935,
                "margin_deficiency_cents": 34065,
                "margin_status": "DEFICIENT",
                "lien_state": "PERFECTED",
            },
        )

        lender = get_success_data(
            api.get_party(scenario["lender_id"], scenario["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 215935, "available_credit_cents": 49784065},
        )

    def test_out_of_condition_bin_drops_sound_physical_and_restricts_the_posture(
        self, api, impaired_chain
    ):
        """
        The same assessment removes the bin's entire 949 bushels from the sound
        physical figure while leaving the system physical figure at 949, so the
        position variance of -949 exceeds the 500-bushel tolerance and the
        posture becomes RESTRICTED.

        PRD: "Finally the warehouse's `sound_physical_bushels` drops by this
        bin's entire `stored_bushels`, which moves `position_variance_bushels`
        and may push `operational_posture` to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/bin_out_of_condition_impairs_receipt_then_lien_then_lender_credit
        """
        scenario = impaired_chain["scenario"]
        warehouse = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], scenario["operator_headers"]),
            200,
        )
        assert_fields_equal(
            warehouse,
            {
                "sound_physical_bushels": 0,
                "system_physical_bushels": 949,
                "position_variance_bushels": -949,
                "examination_tolerance_bushels": 500,
                "operational_posture": "RESTRICTED",
            },
        )


class TestCriticalExaminationCascade:
    @pytest.fixture
    def critical_chain(self, api, base_full, weighed_ticket, submitted_report):
        """
        A second load left WEIGHED on the same bin, and a submitted report whose
        549-bushel count discrepancy refers it for examination; then a second
        regulator records a CRITICAL result.
        """
        second_ticket = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-05T16:00:00Z",
            fill_end_at="2026-08-05T17:00:00Z",
        )
        report = submitted_report(base_full["warehouse_id"], 400, 949)
        assert report["report_state"] == "UNDER_EXAMINATION"

        examined = get_success_data(
            api.examine_position_report(
                report["id"],
                f.examine_report_payload(
                    "CRITICAL", findings_note="unexplained 549-bushel shortage"
                ),
                SECOND_REGULATOR_HEADERS,
            ),
            200,
        )
        return {
            "second_ticket_id": second_ticket["id"],
            "report": examined,
            "scenario": base_full,
        }

    def test_critical_result_rejects_the_report_and_records_the_examining_regulator(
        self, critical_chain
    ):
        """
        The declared 400 physical bushels against 949 on the books is a
        549-bushel discrepancy that exceeds the 500-bushel tolerance, so the
        report was referred for examination and the second regulator's CRITICAL
        finding moves it to REJECTED under that regulator's identity.

        PRD: "`CRITICAL` moves the report to `REJECTED` and, on top of the
        deficient effects, escalates: the warehouse's `license_state` moves from
        `LICENSED` to `SUSPENDED`, `operational_posture` becomes `CLOSED`, and
        every deposit ticket of that warehouse in `ticket_state` `WEIGHED` moves
        to `REJECTED`."

        Design: Difficulty/transitive_cascade/critical_examination_suspends_license_then_closes_posture_then_rejects_weighed_tickets
        """
        assert_fields_equal(
            critical_chain["report"],
            {
                "report_state": "REJECTED",
                "examination_result": "CRITICAL",
                "examined_by_user_id": SECOND_REGULATOR_USER_ID,
                "count_discrepancy_bushels": -549,
                "examination_tolerance_bushels": 500,
                "examination_required": True,
            },
        )

    def test_critical_result_suspends_the_licence_and_closes_the_posture(
        self, api, critical_chain
    ):
        """
        The escalation reaches the warehouse row itself: the licence leaves
        LICENSED for SUSPENDED and the derived posture closes, while the
        insolvency dimension is untouched.

        PRD: "If `license_state` is anything other than `LICENSED`, or
        `insolvency_state` is anything other than `SOLVENT`, the posture is
        `CLOSED`."

        Design: Difficulty/transitive_cascade/critical_examination_suspends_license_then_closes_posture_then_rejects_weighed_tickets
        """
        warehouse = get_success_data(
            api.get_warehouse(
                critical_chain["scenario"]["warehouse_id"], REGULATOR_HEADERS
            ),
            200,
        )
        assert_fields_equal(
            warehouse,
            {
                "license_state": "SUSPENDED",
                "insolvency_state": "SOLVENT",
                "operational_posture": "CLOSED",
            },
        )

    def test_the_suspension_cascade_rejects_only_the_still_weighed_ticket(
        self, api, critical_chain
    ):
        """
        The load still on the scale is rejected with the suspension reason,
        while the already-receipted ticket and its issued receipt are left
        exactly where they were, because the depositors' grain is still in the
        bin.

        PRD: "Tickets already `ACCEPTED` and receipts already `ISSUED` are
        deliberately left untouched — the stored obligation survives suspension,
        because the depositors' grain is still in the bins."

        Design: Difficulty/transitive_cascade/critical_examination_suspends_license_then_closes_posture_then_rejects_weighed_tickets
        """
        scenario = critical_chain["scenario"]
        headers = scenario["operator_headers"]

        second_ticket = get_success_data(
            api.get_deposit_ticket(critical_chain["second_ticket_id"], headers), 200
        )
        assert_fields_equal(
            second_ticket,
            {"ticket_state": "REJECTED", "rejection_reason": "LICENSE_SUSPENDED"},
        )

        first_ticket = get_success_data(
            api.get_deposit_ticket(scenario["ticket_id"], headers), 200
        )
        assert first_ticket["ticket_state"] == "RECEIPTED"

        receipt = get_success_data(api.get_receipt(scenario["receipt_id"], headers), 200)
        assert_fields_equal(
            receipt, {"receipt_state": "ISSUED", "quantity_bushels": 949}
        )
