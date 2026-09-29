"""Marginal bands, step fees, run-scoped input sets and half-cent ties."""

import pytest

from test_helpers import (
    ELEMENT_ORDER,
    ApiErrorId,
    all_elements_passing,
    api_client,
    approved_proof,
    approved_version,
    assign_root_cause,
    asset_with_obsolete_predecessor,
    coord,
    create_plate_order_payload,
    current_route,
    decide_task,
    disposition_runout,
    element_check_by_code,
    in_review_version,
    new_escape,
    new_printer,
    new_runout,
    raise_recovery_claim,
    read_asset,
    read_printer,
    read_proof,
    read_route,
    read_version,
    regulatory,
    released_version,
    set_clock,
    settle_escape,
    tasks_by_discipline,
    validate_error,
    validate_paginated,
    validate_success,
    verified_version,
    verify,
    waiver_payload,
)


class TestPlateCostLadder:
    """One approved proof, several plate counts, one marginal rate table."""

    def _orderable(self):
        _brief, asset, version = approved_version()
        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert proof["proof_state"] == "PROOF_APPROVED"
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0
        return asset, version, printer, proof

    def _order(self, version, printer, proof, plate_set_count, expedite=False):
        return validate_success(
            api_client.create_plate_order(
                create_plate_order_payload(
                    version["id"],
                    printer["id"],
                    proof["id"],
                    plate_set_count=plate_set_count,
                    expedite=expedite,
                ),
                coord(),
            ),
            201,
        )

    def test_the_expedite_surcharge_is_keyed_on_plates_plus_setup(self):
        """Six plates straddle two bands; ten reach the third and the large setup fee.

        PRD §3.7: "When `expedite` is true, `expedite_fee_cents` is a quarter of the
        sum of `plate_subtotal_cents` and `setup_fee_cents`, rounded half up to a whole
        cent — the surcharge is keyed on plates plus setup and is never re-fed into the
        band selection or the setup threshold — and when `expedite` is false it is 0."

        Design: Corner/calculations/plate_cost_sums_three_marginal_bands_a_step_setup_fee_and_a_surcharge_on_both
        """
        asset, version, printer, proof = self._orderable()

        six = self._order(version, printer, proof, 6)
        # 4 * 18000 + 2 * 15500 = 103000.
        assert six["plate_subtotal_cents"] == 103000
        assert six["setup_fee_cents"] == 60000
        assert six["expedite_fee_cents"] == 0
        assert six["cost_cents"] == 163000
        assert six["status"] == "ORDERED"
        assert six["auto_cancelled"] is False
        assert six["cancel_reason"] is None
        assert six["expedite"] is False

        ten = self._order(version, printer, proof, 10, expedite=True)
        # 72000 + 62000 + 26000 = 160000, then a quarter of 250000.
        assert ten["plate_subtotal_cents"] == 160000
        assert ten["setup_fee_cents"] == 90000
        assert ten["expedite_fee_cents"] == 62500
        assert ten["cost_cents"] == 312500

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 475500
        for order in (six, ten):
            assert order["printer_proof_id"] == proof["id"]
            assert order["artwork_version_id"] == version["id"]

    def test_the_setup_fee_steps_at_nine_plates_while_the_band_rate_does_not(self):
        """The eighth plate is still 15500; the ninth adds 13000 and 30000 of setup.

        PRD §3.7: "On top of that sits `setup_fee_cents`, which is 60000 cents for a
        set of 8 plates or fewer and 90000 cents for a set of 9 or more."

        Design: Corner/calculations/setup_fee_steps_between_eight_and_nine_plates_while_the_band_rate_does_not
        """
        asset, version, printer, proof = self._orderable()

        eight = self._order(version, printer, proof, 8)
        assert eight["plate_subtotal_cents"] == 134000
        assert eight["setup_fee_cents"] == 60000
        assert eight["cost_cents"] == 194000

        nine = self._order(version, printer, proof, 9)
        assert nine["plate_subtotal_cents"] == 147000
        assert nine["setup_fee_cents"] == 90000
        assert nine["cost_cents"] == 237000

        assert nine["plate_subtotal_cents"] - eight["plate_subtotal_cents"] == 13000
        assert nine["setup_fee_cents"] - eight["setup_fee_cents"] == 30000
        assert eight["expedite_fee_cents"] == 0
        assert nine["expedite_fee_cents"] == 0
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 431000

    def test_the_marginal_plate_is_charged_at_its_own_band_rate(self):
        """The fifth plate costs 15500 and does not re-price the first four.

        PRD §3.7: "Cost is a marginal ladder in which each plate is priced at the rate
        of the band it lands in, not at a single blended rate."

        Design: Corner/calculations/the_fifth_plate_is_priced_at_the_band_two_rate_not_at_the_average_rate
        """
        asset, version, printer, proof = self._orderable()

        four = self._order(version, printer, proof, 4)
        assert four["plate_subtotal_cents"] == 72000
        assert four["setup_fee_cents"] == 60000
        assert four["cost_cents"] == 132000

        five = self._order(version, printer, proof, 5)
        assert five["plate_subtotal_cents"] == 87500
        assert five["plate_subtotal_cents"] != 90000
        assert five["plate_subtotal_cents"] != 77500
        assert five["setup_fee_cents"] == 60000
        assert five["cost_cents"] == 147500

        assert four["expedite"] is False
        assert five["expedite"] is False
        assert four["expedite_fee_cents"] == 0
        assert five["expedite_fee_cents"] == 0
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 279500


class TestVerificationRunIsACleanSlate:
    """The score's input set is scoped to the current run, and the old rows are gone."""

    FAILING_ZONE = {"zone_mm2": 120, "position": "BACK_PANEL_LOWER_RIGHT"}

    def test_the_second_run_deletes_the_first_and_never_double_counts_it(self):
        """The run-1 row is unreachable and the score still reads 90.0, not 80.0.

        PRD §3.4: "Every run is a clean slate. The run first deletes every element
        verdict row of this version belonging to an earlier run, then increments the
        version's `check_run_no` by 1, then writes exactly one fresh row per entry of the
        owning brief's `required_element_codes` — each stamped with the new
        `check_run_no`."

        Design: Corner/calculations/a_second_verification_run_replaces_the_first_and_the_score_ignores_the_old_rows
        """
        _brief, _asset, version = verified_version(
            mandatory_elements=all_elements_passing(date_code_zone=self.FAILING_ZONE)
        )
        stale = element_check_by_code(version["id"], "DATE_CODE_ZONE")
        assert stale["check_run_no"] == 1

        second_run = verify(version["id"])
        assert second_run["state"] == "ELEMENTS_VERIFIED"
        assert second_run["check_run_no"] == 2

        validate_error(
            api_client.waive_element_check(
                stale["id"],
                waiver_payload(
                    waiver_justification=(
                        "Waiving the verdict captured from the first run."
                    )
                ),
                regulatory(),
            ),
            ApiErrorId.ERR_ELEMENT_CHECK_NOT_FOUND.value,
            404,
        )

        old_rows, old_meta = validate_paginated(
            api_client.list_element_checks(
                coord(),
                params={"artwork_version_id": version["id"], "check_run_no": 1},
            )
        )
        assert old_rows == []
        assert old_meta["total_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_element_checks(
                coord(),
                params={"artwork_version_id": version["id"], "limit": 100},
            )
        )
        assert len(rows) == 7
        assert meta["total_count"] == 7
        assert [row["element_code"] for row in rows] == ELEMENT_ORDER
        assert all(row["check_run_no"] == 2 for row in rows)

        failing = [row for row in rows if row["result"] == "FAIL"]
        assert len(failing) == 1
        assert failing[0]["element_code"] == "DATE_CODE_ZONE"
        assert failing[0]["severity"] == "MAJOR"
        assert failing[0]["deduction_points"] == pytest.approx(10.0, abs=0.01)
        passing = [row for row in rows if row["result"] == "PASS"]
        assert len(passing) == 6
        for row in passing:
            assert row["deduction_points"] == pytest.approx(0.0, abs=0.01)

        scored = read_version(version["id"])
        assert scored["check_run_no"] == 2
        assert scored["failed_element_count"] == 1
        assert scored["waived_element_count"] == 0
        assert scored["compliance_score"] == pytest.approx(90.0, abs=0.01)

        waived = validate_success(
            api_client.waive_element_check(
                failing[0]["id"],
                waiver_payload(
                    waiver_justification=(
                        "Date code prints inside the varnish-free window on this"
                        " dieline."
                    )
                ),
                regulatory(),
            ),
            200,
        )
        assert waived["result"] == "WAIVED"
        assert waived["deduction_points"] == pytest.approx(5.0, abs=0.01)

        rescored = read_version(version["id"])
        assert rescored["compliance_score"] == pytest.approx(95.0, abs=0.01)
        assert rescored["failed_element_count"] == 0


class TestChangeoverHalfCentTie:
    """A five-unit scrap lands the surcharge on an exact half cent."""

    def test_ten_point_five_cents_rounds_up_to_eleven(self):
        """210 cents at five percent is 10.5, which must store as 11 and total 221.

        PRD §3.8: "`changeover_expedite_cents` is the base multiplied by the tier
        percentage, rounded half up to a whole cent, and `total_changeover_cost_cents` is
        `changeover_base_cents` plus `changeover_expedite_cents`."

        Design: Corner/calculations/changeover_surcharge_of_ten_point_five_cents_rounds_up_to_eleven
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        assert asset["standard_unit_cost_cents"] == 42
        set_clock("2026-08-10T00:00:00Z")

        runout = new_runout(
            asset,
            v1,
            on_hand_qty=5,
            weekly_usage_qty=100,
            runout_start_utc="2026-08-10T00:00:00Z",
        )
        assert runout["state"] == "PLANNED"
        assert runout["remaining_qty"] == 5
        assert runout["projected_runout_date"] == "2026-08-17"
        assert runout["actual_runout_date"] is None
        assert runout["disposition"] is None

        scrapped = disposition_runout(
            runout["id"], "SCRAP", units_scrapped=5, units_reworked=0
        )
        assert scrapped["state"] == "SCRAPPED"
        assert scrapped["units_scrapped"] == 5
        assert scrapped["units_reworked"] == 0
        assert scrapped["material_writeoff_cents"] == 210
        assert scrapped["relabel_cost_cents"] == 0
        assert scrapped["changeover_base_cents"] == 210
        assert scrapped["changeover_expedite_cents"] == 11
        assert scrapped["changeover_expedite_cents"] != 10
        assert scrapped["total_changeover_cost_cents"] == 221

        after = read_asset(asset["id"])
        assert after["obsolete_units_total"] == 5
        assert after["changeover_cost_committed_cents"] == 221
        assert after["obsolescence_state"] == "SUPERSEDED"
        assert read_version(v1["id"])["state"] == "OBSOLETE"


class TestProbationThresholdIsStrict:
    """A penalty of exactly 30.0 points lands the score on the threshold itself."""

    def test_a_score_of_exactly_seventy_leaves_the_vendor_certified(self):
        """13000 units and a PACKING catch total 30.0 points, so 70.0 is not below.

        PRD §3.9: "Third, if the new score is **strictly** below 70.0 the vendor moves
        `CERTIFIED → PROBATION`; a score of exactly 70.0 stays `CERTIFIED`."

        Design: Corner/calculations/a_penalty_landing_exactly_on_seventy_leaves_the_printer_certified
        """
        _brief, _asset, version, printer, proof = released_version()
        escape = new_escape(
            version["id"], printer, discovered_stage="PACKING", units_affected=13000
        )
        assert escape["investigation_fee_cents"] == 60000

        assign_root_cause(escape["id"], "PRINTER", 1.00)
        claimed = raise_recovery_claim(escape["id"])
        # 546000 reprint + 91000 scrap + 0 freight + 60000 investigation at share 1.00.
        assert claimed["provisional_recovery_cents"] == 697000
        assert claimed["liability_cap_applied"] is False

        set_clock("2026-08-20T00:00:00Z")
        settled = settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=800000,
            actual_scrap_cost_cents=91000,
            actual_expedite_freight_cents=25000,
            settlement_note="Printer accepted full responsibility.",
        )
        assert settled["state"] == "SETTLED"
        assert settled["resolution"] == "SETTLED"
        assert settled["settled_at"].startswith("2026-08-20T00:00:00")
        assert settled["final_recovery_cents"] == 976000
        assert settled["recovery_variance_cents"] == 279000
        assert settled["liability_cap_applied"] is False

        vendor = read_printer(printer["id"])
        assert vendor["performance_score"] == pytest.approx(70.0, abs=0.01)
        assert vendor["certification_status"] == "CERTIFIED"
        assert vendor["escape_count"] == 1
        assert vendor["recovery_balance_cents"] == 976000

        assert read_proof(proof["id"])["requires_recheck"] is False
        assert read_version(version["id"])["state"] == "RELEASED_TO_PRINT"


class TestConditionalCountsAsApproving:
    """A conditional verdict resolves its stage and is counted at the same time."""

    CONDITION = "BRAND_LOGO_CLEARSPACE"

    def test_the_stage_advances_yet_the_condition_survives_to_the_version(self):
        """One conditional verdict raises the count and sets re-verification on approval.

        PRD §3.5: "It also sets `requires_reverification` to true when the pass's
        `conditional_count` is greater than zero, and leaves it false when no conditional
        decision was recorded — the flag that later blocks release until a fresh
        verification run clears it."

        Design: Corner/calculations/conditional_counts_as_approving_for_stage_resolution_but_still_raises_the_conditional_count
        """
        _brief, asset, version = in_review_version()
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])

        conditional = decide_task(
            tasks["BRAND"],
            "CONDITIONAL",
            comment="Approved subject to logo clear-space correction.",
            condition_code=self.CONDITION,
        )
        assert conditional["decision"] == "CONDITIONAL"
        assert conditional["condition_code"] == self.CONDITION

        waiting = read_route(route["id"])
        assert waiting["status"] == "IN_PROGRESS"
        assert waiting["current_stage_no"] == 1
        assert waiting["conditional_count"] == 1

        for discipline in ("REGULATORY", "LEGAL", "QUALITY"):
            assert decide_task(tasks[discipline], "APPROVED")["decision"] == "APPROVED"

        closed = read_route(route["id"])
        assert closed["status"] == "COMPLETE_APPROVED"
        assert closed["current_stage_no"] == 3
        assert closed["conditional_count"] == 1
        assert closed["completed_at"].startswith("2026-08-01T00:00:00")

        after = read_version(version["id"])
        assert after["state"] == "APPROVED"
        assert after["requires_reverification"] is True
        assert after["open_condition_codes"] == [self.CONDITION]
        assert after["approved_at"].startswith("2026-08-01T00:00:00")

        owning = read_asset(asset["id"])
        assert owning["current_approved_version_id"] == version["id"]
        assert owning["obsolescence_state"] == "ACTIVE"
