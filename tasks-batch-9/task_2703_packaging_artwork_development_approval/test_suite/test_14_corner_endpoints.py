"""Whole-call shapes: partial edits, action chains, batch appends and parent joins."""

import pytest

from test_helpers import (
    ELEMENT_ORDER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    all_elements_passing,
    api_client,
    append_depletion,
    approved_proof,
    approved_version,
    asset_with_obsolete_predecessor,
    assign_root_cause,
    cancel_plate_order_payload,
    coord,
    create_plate_order_payload,
    current_route,
    decide_brief,
    decide_task,
    depletion,
    depletion_records_payload,
    dispute_escape,
    element_check_by_code,
    new_approved_brief,
    new_asset,
    new_brief,
    new_escape,
    new_plate_order,
    new_printer,
    new_runout,
    new_version,
    patch_brief,
    patch_version,
    raise_recovery_claim,
    read_asset,
    read_brief,
    read_escape,
    read_plate_order,
    read_printer,
    read_runout,
    read_version,
    released_version,
    settle_escape,
    submit,
    tasks_by_discipline,
    validate_error,
    validate_paginated,
    verify,
    waive_check,
)


class TestBriefPatchIsAWholesaleFieldOverwrite:
    """One PATCH surface, three outcomes: partial write, unknown key, closed state."""

    RENAMED = "Northgate Cocoa Carton 340g Relaunch"

    def test_the_patch_touches_only_its_own_fields_and_stops_at_approval(self):
        """Two supplied fields move, four are untouched, and approval closes the door.

        PRD §3.1: "While it remains in `DRAFT` the coordinator may revise its
        `product_name`, `market_codes`, `language_codes`, `required_element_codes`,
        `structural_spec` and `net_contents_declaration`, each optional and each
        overwriting the stored value wholesale; the edit refreshes `updated_at` and
        increments `version` by 1."

        PRD §3.1: "Once the brief has left `DRAFT` no edit is possible and the attempt
        is refused with `ERR_BRIEF_STATE_INVALID`."

        Design: Corner/endpoints/patch_brief_overwrites_only_the_supplied_fields_and_rejects_unknown_keys_once_approved
        """
        brief = new_brief()
        assert brief["status"] == "DRAFT"
        assert brief["version"] == 1
        assert brief["asset_count"] == 0
        assert brief["market_codes"] == ["US"]
        assert brief["language_codes"] == ["en"]

        patched = patch_brief(
            brief["id"],
            {"product_name": self.RENAMED, "market_codes": ["US", "CA"]},
        )
        assert patched["product_name"] == self.RENAMED
        assert patched["market_codes"] == ["US", "CA"]
        assert patched["language_codes"] == ["en"]
        assert patched["required_element_codes"] == list(ELEMENT_ORDER)
        assert patched["structural_spec"]["component_type"] == "CARTON"
        assert patched["structural_spec"]["dimensions_mm"] == {
            "l": 120,
            "w": 60,
            "h": 200,
        }
        assert patched["structural_spec"]["substrate_class"] == "COATED_PAPER"
        assert patched["structural_spec"]["print_process"] == "OFFSET"
        assert patched["net_contents_declaration"]["metric_value"] == 340
        assert patched["net_contents_declaration"]["metric_uom"] == "G"
        assert patched["net_contents_declaration"]["us_value"] == 12
        assert patched["net_contents_declaration"]["us_uom"] == "OZ"
        assert patched["regulatory_scheme"] == "FDA_FOOD"
        assert patched["status"] == "DRAFT"
        assert patched["version"] == 2

        echoed = read_brief(brief["id"])
        assert echoed["product_name"] == self.RENAMED
        assert echoed["market_codes"] == ["US", "CA"]
        assert echoed["language_codes"] == ["en"]
        assert echoed["version"] == 2

        validate_error(
            api_client.patch_brief(
                brief["id"],
                {"product_name": "Rejected by the schema", "promo_flag": True},
                coord(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        untouched = read_brief(brief["id"])
        assert untouched["product_name"] == self.RENAMED
        assert untouched["version"] == 2
        assert untouched["status"] == "DRAFT"

        approved = decide_brief(brief["id"], "APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u_reg"
        assert approved["version"] == 3

        validate_error(
            api_client.patch_brief(
                brief["id"], {"product_name": "Too late to rename"}, coord()
            ),
            ApiErrorId.ERR_BRIEF_STATE_INVALID.value,
            409,
        )
        closing = read_brief(brief["id"])
        assert closing["product_name"] == self.RENAMED
        assert closing["market_codes"] == ["US", "CA"]
        assert closing["status"] == "APPROVED"
        assert closing["version"] == 3


class TestPatchOfARevisionRequestedVersionDoesNotRescore:
    """The edit repairs the very element that failed, yet the score stays stale."""

    def test_the_repair_lands_but_the_figures_wait_for_the_next_run(self):
        """87.5 and run 1 survive the PATCH; only verify-elements moves them to 100.0.

        PRD §3.3: "Editing is deliberately inert with respect to compliance: it refreshes
        `updated_at` and increments `version` by 1 but does **not** re-run verification,
        so `compliance_score` keeps its stale value until the next verification run
        recomputes it."

        PRD §3.4: "from `REVISION_REQUESTED` it re-runs and likewise leaves the state
        unchanged — re-verification explicitly does **not** clear a requested revision,
        which still has to be re-opened separately"

        Design: Corner/endpoints/patch_of_a_revision_requested_version_rewrites_the_payload_without_rescoring_it
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        version = new_version(
            asset,
            mandatory_elements=all_elements_passing(
                allergen_statement={
                    "text": "Contains milk and soya.",
                    "allergen_emphasis": False,
                }
            ),
        )

        verified = verify(version["id"])
        assert verified["state"] == "ELEMENTS_VERIFIED"
        assert verified["check_run_no"] == 1
        assert verified["failed_element_count"] == 1
        assert verified["compliance_score"] == pytest.approx(75.0, abs=0.01)

        failing = element_check_by_code(version["id"], "ALLERGEN_STATEMENT")
        assert failing["result"] == "FAIL"
        assert failing["severity"] == "CRITICAL"
        waived = waive_check(
            failing["id"],
            waiver_justification=(
                "Bold allergen emphasis accepted as a documented residual risk for"
                " this print run."
            ),
        )
        assert waived["result"] == "WAIVED"
        assert waived["deduction_points"] == pytest.approx(12.5, abs=0.01)

        scored = read_version(version["id"])
        assert scored["compliance_score"] == pytest.approx(87.5, abs=0.01)
        assert scored["failed_element_count"] == 0
        assert scored["waived_element_count"] == 1
        assert scored["check_run_no"] == 1

        submit(version["id"])
        route = current_route(version["id"])
        tasks = tasks_by_discipline(route["id"])
        decide_task(
            tasks["BRAND"],
            "REJECTED",
            comment="Allergen emphasis must be printed, not waived.",
        )

        bounced = read_version(version["id"])
        assert bounced["state"] == "REVISION_REQUESTED"
        assert bounced["revision_cycle_count"] == 1
        assert bounced["compliance_score"] == pytest.approx(87.5, abs=0.01)
        assert bounced["failed_element_count"] == 0
        assert bounced["waived_element_count"] == 1
        assert bounced["check_run_no"] == 1
        before = bounced["version"]

        patched = patch_version(
            version["id"],
            {
                "mandatory_elements": all_elements_passing(),
                "reason_for_change_code": "ERROR_CORRECTION",
                "change_description": (
                    "Allergen panel reset to bold emphasis after the brand rejection."
                ),
            },
        )
        assert patched["reason_for_change_code"] == "ERROR_CORRECTION"
        assert patched["change_description"].startswith("Allergen panel reset")
        assert patched["state"] == "REVISION_REQUESTED"
        assert patched["compliance_score"] == pytest.approx(87.5, abs=0.01)
        assert patched["failed_element_count"] == 0
        assert patched["waived_element_count"] == 1
        assert patched["check_run_no"] == 1
        assert patched["revision_cycle_count"] == 1
        assert patched["version"] == before + 1

        still_waived = element_check_by_code(version["id"], "ALLERGEN_STATEMENT")
        assert still_waived["result"] == "WAIVED"
        assert still_waived["check_run_no"] == 1

        rerun = verify(version["id"])
        assert rerun["state"] == "REVISION_REQUESTED"
        assert rerun["check_run_no"] == 2
        assert rerun["compliance_score"] == pytest.approx(100.0, abs=0.01)
        assert rerun["failed_element_count"] == 0
        assert rerun["waived_element_count"] == 0

        repaired = element_check_by_code(version["id"], "ALLERGEN_STATEMENT")
        assert repaired["result"] == "PASS"
        assert repaired["check_run_no"] == 2
        assert repaired["deduction_points"] == pytest.approx(0.0, abs=0.01)
        assert repaired["detail"] == "OK"


class TestEscapeActionsWalkDisputeRevisionAndWriteoff:
    """Four action endpoints in sequence, and the vendor scorecard never moves."""

    def test_a_disputed_claim_is_reapportioned_then_abandoned(self):
        """697000 is withdrawn to null, re-raised at 348500, then written off to 0.

        PRD §3.9: "Apportionment is admissible from `OPEN`, moving the escape
        `OPEN → ROOT_CAUSE_ASSIGNED`, and also from `DISPUTED`, moving it
        `DISPUTED → ROOT_CAUSE_ASSIGNED` and overwriting the earlier `root_cause_party`,
        `printer_share_pct` and `investigation_note`; on that revising path
        `provisional_recovery_cents` is cleared back to null and `liability_cap_applied`
        back to false, because the prior claim basis has been withdrawn."

        PRD §3.9: "The vendor's `recovery_balance_cents` and `performance_score` are both
        left entirely unchanged, and no scorecard penalty is computed."

        Design: Corner/endpoints/escape_action_endpoints_walk_dispute_revision_and_writeoff_without_touching_the_printer
        """
        _brief, asset, version, printer, _proof = released_version()
        assert read_asset(asset["id"])["standard_unit_cost_cents"] == 42
        assert printer["recovery_liability_cap_cents"] == 5000000
        assert printer["performance_score"] == pytest.approx(100.0, abs=0.01)

        escape = new_escape(
            version["id"], printer, discovered_stage="PACKING", units_affected=13000
        )
        assert escape["state"] == "OPEN"
        assert escape["investigation_fee_cents"] == 60000
        assert escape["dispute_count"] == 0
        assert escape["provisional_recovery_cents"] is None

        assigned = assign_root_cause(escape["id"], "PRINTER", 1.00)
        assert assigned["state"] == "ROOT_CAUSE_ASSIGNED"
        assert assigned["printer_share_pct"] == pytest.approx(1.00, abs=0.01)

        first = raise_recovery_claim(escape["id"])
        # 546000 reprint + 91000 scrap + 0 freight + 60000 investigation at share 1.00.
        assert first["state"] == "RECOVERY_CLAIMED"
        assert first["provisional_recovery_cents"] == 697000
        assert first["liability_cap_applied"] is False

        disputed = dispute_escape(
            escape["id"],
            printer,
            dispute_reason="The brand supplied the superseded plate file.",
        )
        assert disputed["state"] == "DISPUTED"
        assert disputed["dispute_count"] == 1
        assert disputed["dispute_reason"] == (
            "The brand supplied the superseded plate file."
        )
        assert disputed["provisional_recovery_cents"] == 697000

        revised = assign_root_cause(
            escape["id"],
            "SHARED",
            0.50,
            investigation_note=(
                "Plate file error shared between the brand studio and the press."
            ),
        )
        assert revised["state"] == "ROOT_CAUSE_ASSIGNED"
        assert revised["root_cause_party"] == "SHARED"
        assert revised["printer_share_pct"] == pytest.approx(0.50, abs=0.01)
        assert revised["provisional_recovery_cents"] is None
        assert revised["liability_cap_applied"] is False
        assert revised["dispute_count"] == 1

        second = raise_recovery_claim(escape["id"])
        # 273000 + 45500 + 0 + 30000, each line rounded before the four are summed.
        assert second["state"] == "RECOVERY_CLAIMED"
        assert second["provisional_recovery_cents"] == 348500
        assert second["liability_cap_applied"] is False

        written_off = settle_escape(escape["id"], "WRITTEN_OFF")
        assert written_off["state"] == "WRITTEN_OFF"
        assert written_off["resolution"] == "WRITTEN_OFF"
        assert written_off["final_recovery_cents"] == 0
        assert written_off["recovery_variance_cents"] == -348500
        assert written_off["settled_at"].startswith("2026-08-01T00:00:00")

        vendor = read_printer(printer["id"])
        assert vendor["performance_score"] == pytest.approx(100.0, abs=0.01)
        assert vendor["certification_status"] == "CERTIFIED"
        assert vendor["recovery_balance_cents"] == 0
        assert vendor["escape_count"] == 1

        closing = read_escape(escape["id"])
        assert closing["state"] == "WRITTEN_OFF"
        assert closing["provisional_recovery_cents"] == 348500
        assert closing["final_recovery_cents"] == 0
        assert closing["dispute_count"] == 1
        assert read_version(version["id"])["state"] == "RELEASED_TO_PRINT"


class TestDepletionBatchIsAtomicAndChronological:
    """One accepted batch of three, then two refused batches that write nothing."""

    def test_the_batch_lands_whole_and_out_of_order_weeks_are_refused(self):
        """Three weeks replay to 8900 and 3700; a descending pair and a replayed week fail.

        PRD §3.8: "Ordering is strictly enforced so that the stored array is always
        already sorted: within the submitted batch the `week_start_utc` values must be
        strictly ascending, and every submitted `week_start_utc` must be strictly later
        than the greatest `week_start_utc` already stored."

        PRD §3.8: "This forward-looking projection is blind to actuals: it never reads
        `depletion_records`, and once written it is never revised for the life of the
        runout, however far the observed burn diverges from the plan."

        Design: Corner/endpoints/depletion_batch_is_all_or_nothing_and_is_replayed_in_one_chronological_order
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        runout = new_runout(
            asset,
            v1,
            on_hand_qty=20000,
            weekly_usage_qty=3000,
            runout_start_utc="2026-08-03T00:00:00Z",
        )
        assert runout["state"] == "PLANNED"
        assert runout["remaining_qty"] == 20000
        assert runout["depletion_records"] == []
        assert runout["trailing_avg_usage_qty"] is None
        assert runout["actual_runout_date"] is None
        # 20000 over 3000 a week rounds up to seven whole weeks from 2026-08-03.
        assert runout["projected_runout_date"] == "2026-09-21"
        assert runout["version"] == 1

        appended = append_depletion(
            runout["id"],
            [
                depletion("2026-08-03T00:00:00Z", 2000),
                depletion("2026-08-10T00:00:00Z", 5000),
                depletion("2026-08-17T00:00:00Z", 4100),
            ],
        )
        assert appended["state"] == "MONITORING"
        assert len(appended["depletion_records"]) == 3
        assert [row["units_consumed"] for row in appended["depletion_records"]] == [
            2000,
            5000,
            4100,
        ]
        assert appended["remaining_qty"] == 8900
        # The mean of the last three weeks: 11100 over three.
        assert appended["trailing_avg_usage_qty"] == 3700
        # 8900 over 3700 rounds up to three extra weeks past 2026-08-24.
        assert appended["actual_runout_date"] == "2026-09-14"
        assert appended["projected_runout_date"] == "2026-09-21"
        assert appended["version"] == 2

        validate_error(
            api_client.append_depletion_records(
                runout["id"],
                depletion_records_payload(
                    [
                        depletion("2026-08-31T00:00:00Z", 1200),
                        depletion("2026-08-24T00:00:00Z", 1300),
                    ]
                ),
                coord(),
            ),
            ApiErrorId.ERR_DEPLETION_RECORD_OUT_OF_ORDER.value,
            409,
        )
        after_descending = read_runout(runout["id"])
        assert len(after_descending["depletion_records"]) == 3
        assert after_descending["remaining_qty"] == 8900
        assert after_descending["version"] == 2

        validate_error(
            api_client.append_depletion_records(
                runout["id"],
                depletion_records_payload([depletion("2026-08-10T00:00:00Z", 900)]),
                coord(),
            ),
            ApiErrorId.ERR_DEPLETION_RECORD_OUT_OF_ORDER.value,
            409,
        )

        closing = read_runout(runout["id"])
        assert closing["state"] == "MONITORING"
        assert len(closing["depletion_records"]) == 3
        assert [row["units_consumed"] for row in closing["depletion_records"]] == [
            2000,
            5000,
            4100,
        ]
        assert closing["remaining_qty"] == 8900
        assert closing["trailing_avg_usage_qty"] == 3700
        assert closing["actual_runout_date"] == "2026-09-14"
        assert closing["projected_runout_date"] == "2026-09-21"
        assert closing["disposition"] is None
        assert closing["version"] == 2


class TestPlateOrderResolvesThreeParentsIndependently:
    """Three body references, three distinct 404s, then one order that joins all three."""

    def test_each_dangling_reference_reports_its_own_collection(self):
        """Version, printer and proof each answer for themselves before the order lands.

        PRD §2.5: "Nested and referenced resources are resolved strictly from left to
        right along the URL, and only afterwards from the request body."

        PRD §2.5: "Because resolution is ordered, a request that names both a missing
        printer and a missing proof reports whichever appears first in the left-to-right
        walk."

        Design: Corner/endpoints/plate_order_links_three_parents_and_each_dangling_reference_raises_its_own_404
        """
        _brief, asset, version = approved_version()
        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert proof["proof_state"] == "PROOF_APPROVED"

        validate_error(
            api_client.create_plate_order(
                create_plate_order_payload(
                    NON_EXISTENT_UUID, printer["id"], proof["id"]
                ),
                coord(),
            ),
            ApiErrorId.ERR_ARTWORK_VERSION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_plate_order(
                create_plate_order_payload(
                    version["id"], NON_EXISTENT_UUID, proof["id"]
                ),
                coord(),
            ),
            ApiErrorId.ERR_PRINTER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_plate_order(
                create_plate_order_payload(
                    version["id"], printer["id"], NON_EXISTENT_UUID
                ),
                coord(),
            ),
            ApiErrorId.ERR_PRINTER_PROOF_NOT_FOUND.value,
            404,
        )
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        order = new_plate_order(version["id"], printer, proof, plate_set_count=6)
        assert order["artwork_version_id"] == version["id"]
        assert order["printer_id"] == printer["id"]
        assert order["printer_proof_id"] == proof["id"]
        assert order["plate_set_count"] == 6
        assert order["plate_subtotal_cents"] == 103000
        assert order["setup_fee_cents"] == 60000
        assert order["expedite_fee_cents"] == 0
        assert order["cost_cents"] == 163000
        assert order["status"] == "ORDERED"
        assert order["auto_cancelled"] is False
        assert order["cancel_reason"] is None
        assert order["cancelled_at"] is None

        rows, meta = validate_paginated(
            api_client.list_plate_orders(
                coord(), params={"printer_proof_id": proof["id"]}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == order["id"]
        assert rows[0]["cost_cents"] == 163000

        single = read_plate_order(order["id"])
        assert single["id"] == order["id"]
        assert single["artwork_version_id"] == version["id"]
        assert single["printer_id"] == printer["id"]
        assert single["printer_proof_id"] == proof["id"]
        assert single["cost_cents"] == 163000
        assert single["status"] == "ORDERED"

        owning = read_asset(asset["id"])
        assert owning["committed_plate_cost_cents"] == 163000
        assert owning["plate_budget_cents"] == 500000

        validate_error(
            api_client.cancel_plate_order(
                NON_EXISTENT_UUID, cancel_plate_order_payload(), coord()
            ),
            ApiErrorId.ERR_PLATE_ORDER_NOT_FOUND.value,
            404,
        )
        assert read_plate_order(order["id"])["status"] == "ORDERED"
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 163000


class TestAssetCountAndUnitCostAreDerivedReads:
    """Two child creates, two component types, and nothing the caller supplied."""

    def test_the_count_climbs_and_each_component_prices_itself(self):
        """asset_count walks 0, 1, 2 while a CARTON reads 42 and a LABEL reads 9.

        PRD §3.3: "The asset's `standard_unit_cost_cents` is derived from its component
        and is not supplied by the caller: a `CARTON` costs 42 cents per unit, a `LABEL`
        9 cents, a `FILM` 15 cents and a `SHIPPER` 120 cents."

        PRD §3.3: "A new asset begins with `obsolescence_state` `ACTIVE`, a
        `version_counter` of 0, a null `current_approved_version_id`, and all three of its
        conserved ledgers — `committed_plate_cost_cents`, `obsolete_units_total` and
        `changeover_cost_committed_cents` — at 0."

        Design: Corner/endpoints/brief_asset_count_and_asset_derived_fields_are_computed_reads_not_stored_totals
        """
        brief = new_approved_brief(
            market_codes=["US", "CA"], language_codes=["en", "fr"]
        )
        assert brief["status"] == "APPROVED"
        assert brief["asset_count"] == 0

        carton = new_asset(
            brief["id"],
            market_code="US",
            component_type="CARTON",
            language_codes=["en"],
        )
        assert carton["brief_id"] == brief["id"]
        assert carton["market_code"] == "US"
        assert carton["component_type"] == "CARTON"
        assert carton["language_codes"] == ["en"]
        assert carton["standard_unit_cost_cents"] == 42
        assert carton["obsolescence_state"] == "ACTIVE"
        assert carton["version_counter"] == 0
        assert carton["current_approved_version_id"] is None
        assert carton["committed_plate_cost_cents"] == 0
        assert carton["obsolete_units_total"] == 0
        assert carton["changeover_cost_committed_cents"] == 0
        assert carton["brand_critical_color"] is False
        assert read_brief(brief["id"])["asset_count"] == 1

        label = new_asset(
            brief["id"],
            market_code="CA",
            component_type="LABEL",
            language_codes=["en", "fr"],
        )
        assert label["market_code"] == "CA"
        assert label["component_type"] == "LABEL"
        assert label["language_codes"] == ["en", "fr"]
        assert label["standard_unit_cost_cents"] == 9
        assert label["obsolescence_state"] == "ACTIVE"
        assert label["version_counter"] == 0
        assert label["current_approved_version_id"] is None
        assert label["committed_plate_cost_cents"] == 0
        assert label["obsolete_units_total"] == 0
        assert label["changeover_cost_committed_cents"] == 0
        assert read_brief(brief["id"])["asset_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_artwork_assets(coord(), params={"brief_id": brief["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [carton["id"], label["id"]]
        assert [row["component_type"] for row in rows] == ["CARTON", "LABEL"]
        assert [row["standard_unit_cost_cents"] for row in rows] == [42, 9]
        assert [row["market_code"] for row in rows] == ["US", "CA"]
