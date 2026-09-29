"""Rule interactions along the proof, escape, budget, claim and runout ladders."""

import pytest

from test_helpers import (
    ApiErrorId,
    admin,
    api_client,
    append_depletion,
    approved_proof,
    approved_version,
    asset_with_obsolete_predecessor,
    assign_root_cause,
    clearance_payload,
    color_decision_payload,
    coord,
    create_plate_order_payload,
    create_printer_proof_payload,
    current_route,
    decide_color,
    decide_substrate,
    decide_task,
    depletion,
    depletion_records_payload,
    disposition_payload,
    disposition_reversal_payload,
    disposition_runout,
    in_review_version,
    legal,
    new_approved_brief,
    new_asset,
    new_claim,
    new_cleared_claim,
    new_escape,
    new_plate_order,
    new_printer,
    new_proof,
    new_runout,
    new_version,
    plate_orders_for_version,
    press_check_payload,
    printer_as,
    proofs_for_version,
    quality,
    raise_recovery_claim,
    read_asset,
    read_claim,
    read_escape,
    read_printer,
    read_proof,
    read_runout,
    read_version,
    recovery_claim_payload,
    reject_claim,
    release,
    release_payload,
    root_cause_payload,
    routes_for,
    set_clock,
    settle_escape,
    settle_payload,
    submit,
    submit_payload,
    substrate_decision_payload,
    tasks_by_discipline,
    validate_error,
    validate_paginated,
    verify,
)


class TestProofDimensionsCloseOnceThenTheWholeProofCloses:
    """Three refusals that look alike and are three different rules."""

    def test_the_closed_proof_outranks_the_closed_dimension(self):
        """A press check that was never required, a repeat colour call, a shut proof.

        PRD §3.6: "A press-check write is admissible only while `press_check_status`
        is `PRESS_CHECK_REQUIRED` or `PRESS_CHECK_SCHEDULED`; a track that reads
        `NOT_REQUIRED` or has already reached `PRESS_CHECK_ATTENDED` refuses the write
        with `ERR_PRESS_CHECK_NOT_REQUIRED`."

        PRD §3.6: "And while a proof is still `PROOF_IN_REVIEW`, a second colour
        decision on a proof whose `color_status` is no longer `COLOR_PENDING`, or a
        second substrate decision on a proof whose `substrate_status` is no longer
        `SUBSTRATE_PENDING`, is refused with `ERR_PROOF_DIMENSION_ALREADY_DECIDED`."

        Design: Corner/validations/each_proof_dimension_closes_once_and_the_whole_proof_closes_after_it_resolves
        """
        _brief, _asset, version = approved_version()
        assert version["requires_reverification"] is False
        printer = new_printer()

        proof = new_proof(version["id"], printer)
        assert proof["press_check_required"] is False
        assert proof["press_check_status"] == "NOT_REQUIRED"
        assert proof["effective_tolerance"] == pytest.approx(2.0, abs=0.01)
        assert proof["proof_state"] == "PROOF_IN_REVIEW"

        unwanted = api_client.book_press_check(
            proof["id"],
            press_check_payload(
                press_line_code="PRESS-1",
                press_check_start_utc="2026-08-12T08:00:00Z",
                press_check_end_utc="2026-08-12T12:00:00Z",
            ),
            quality(),
        )
        validate_error(unwanted, ApiErrorId.ERR_PRESS_CHECK_NOT_REQUIRED.value, 409)
        untouched = read_proof(proof["id"])
        assert untouched["press_check_status"] == "NOT_REQUIRED"
        assert untouched["press_line_code"] is None

        first_colour = decide_color(proof["id"], 1.20)
        assert first_colour["color_status"] == "COLOR_PASS"
        assert first_colour["measured_delta_e_max"] == pytest.approx(1.20, abs=0.01)
        assert first_colour["substrate_status"] == "SUBSTRATE_PENDING"
        assert first_colour["proof_state"] == "PROOF_IN_REVIEW"

        second_colour = api_client.decide_proof_color(
            proof["id"], color_decision_payload(1.90), quality()
        )
        validate_error(
            second_colour, ApiErrorId.ERR_PROOF_DIMENSION_ALREADY_DECIDED.value, 409
        )
        assert read_proof(proof["id"])["measured_delta_e_max"] == pytest.approx(
            1.20, abs=0.01
        )

        approved = decide_substrate(proof["id"], "SUBSTRATE_APPROVED")
        assert approved["substrate_status"] == "SUBSTRATE_APPROVED"
        assert approved["proof_state"] == "PROOF_APPROVED"

        shut = api_client.decide_proof_substrate(
            proof["id"], substrate_decision_payload("SUBSTRATE_REJECTED"), quality()
        )
        validate_error(shut, ApiErrorId.ERR_PROOF_STATE_INVALID.value, 409)

        final = read_proof(proof["id"])
        assert final["substrate_status"] == "SUBSTRATE_APPROVED"
        assert final["proof_state"] == "PROOF_APPROVED"


class TestProbationAndSubstrateGateDifferentCallSets:
    """One suspended vendor, one healthy vendor, two printer-scoped refusals."""

    def _suspended_and_healthy(self):
        _brief, asset, version = approved_version()
        cascade = new_printer(
            name="Cascade Print Co", certified_substrates=["COATED_PAPER"]
        )
        proof = approved_proof(version["id"], cascade)
        assert proof["proof_state"] == "PROOF_APPROVED"
        version = release(version["id"])
        assert version["state"] == "RELEASED_TO_PRINT"

        harbour = new_printer(
            name="Harbour Litho Ltd", certified_substrates=["COATED_PAPER"]
        )

        escape = new_escape(
            version["id"],
            cascade,
            discovered_stage="DISTRIBUTION",
            units_affected=13000,
            defect_code="OLD_ARTWORK_USED",
        )
        assert escape["investigation_fee_cents"] == 150000
        assign_root_cause(escape["id"], "PRINTER", 1.00)
        raise_recovery_claim(escape["id"])
        settled = settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=500000,
            actual_scrap_cost_cents=50000,
            actual_expedite_freight_cents=0,
            settlement_note="Printer invoices reconciled.",
        )
        # 500000 + 50000 + 0 + 150000 at a share of 1.00.
        assert settled["final_recovery_cents"] == 700000
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0
        return asset, version, cascade, proof, harbour

    def test_probation_reaches_the_plate_order_and_certification_reaches_only_the_proof(
        self,
    ):
        """The suspended vendor is shut out twice; the healthy one only lacks FILM.

        PRD §3.6: "The `substrate_code` must appear in the vendor's
        `certified_substrates`, else `ERR_SUBSTRATE_NOT_CERTIFIED`, and the vendor's
        `certification_status` must read `CERTIFIED`, else `ERR_PRINTER_ON_PROBATION`."

        PRD §3.9: "A vendor on `PROBATION` can accept neither new proof submissions
        nor new plate orders, both being refused with `ERR_PRINTER_ON_PROBATION`."

        Design: Corner/validations/probation_blocks_new_proofs_and_plate_orders_while_an_uncertified_substrate_blocks_only_the_proof
        """
        asset, version, cascade, proof, harbour = self._suspended_and_healthy()

        blocked_proof = api_client.create_printer_proof(
            create_printer_proof_payload(
                version["id"], cascade["id"], proof_note="Contract proof."
            ),
            printer_as(cascade),
        )
        validate_error(blocked_proof, ApiErrorId.ERR_PRINTER_ON_PROBATION.value, 422)
        assert len(proofs_for_version(version["id"])) == 1

        blocked_order = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], cascade["id"], proof["id"], plate_set_count=6
            ),
            coord(),
        )
        validate_error(blocked_order, ApiErrorId.ERR_PRINTER_ON_PROBATION.value, 422)
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        wrong_substrate = api_client.create_printer_proof(
            create_printer_proof_payload(
                version["id"],
                harbour["id"],
                substrate_code="FILM",
                proof_note="Contract proof.",
            ),
            printer_as(harbour),
        )
        validate_error(
            wrong_substrate, ApiErrorId.ERR_SUBSTRATE_NOT_CERTIFIED.value, 422
        )

        admitted = new_proof(version["id"], harbour, proof_note="Contract proof.")
        assert admitted["proof_no"] == 2
        assert admitted["proof_state"] == "PROOF_IN_REVIEW"
        assert admitted["effective_tolerance"] == pytest.approx(2.0, abs=0.01)

        suspended = read_printer(cascade["id"])
        assert suspended["certification_status"] == "PROBATION"
        assert suspended["performance_score"] == pytest.approx(66.0, abs=0.01)

        healthy = read_printer(harbour["id"])
        assert healthy["certification_status"] == "CERTIFIED"
        assert healthy["performance_score"] == pytest.approx(100.0, abs=0.01)
        assert healthy["escape_count"] == 0


class TestEscapeLifecycleRefusesFourWays:
    """Order, apportionment arithmetic and an asymmetric liability cap."""

    def _open_escape_under_a_small_cap(self):
        _brief, _asset, version = approved_version()
        printer = new_printer(recovery_liability_cap_cents=500000)
        approved_proof(version["id"], printer)
        version = release(version["id"])

        escape = new_escape(
            version["id"], printer, discovered_stage="MARKET", units_affected=13000
        )
        assert escape["state"] == "OPEN"
        assert escape["investigation_fee_cents"] == 150000
        assert escape["provisional_recovery_cents"] is None
        return printer, escape

    def test_the_cap_clamps_a_provisional_claim_but_refuses_a_settlement(self):
        """787000 clamps to 500000; 800000 is refused; 470000 settles negative.

        PRD §3.9: "Share and party must be consistent, and an inconsistency is
        `ERR_SHARE_INCONSISTENT_WITH_PARTY`: a `PRINTER` root cause requires a share of
        exactly 1.00, a `BRAND` or `AGENCY` root cause requires exactly 0.00, and a
        `SHARED` root cause requires a share strictly greater than 0.00 and strictly
        less than 1.00 — the endpoints are excluded on `SHARED` precisely because they
        belong to the unambiguous parties."

        PRD §3.9: "At settlement the liability cap is **not** silently applied: if the
        pre-clamp sum exceeds the vendor's `recovery_liability_cap_cents` the settlement
        is refused with `ERR_RECOVERY_EXCEEDS_LIABILITY_CAP`, so that the apportionment
        can instead be revised through the dispute cycle."

        Design: Corner/validations/escape_lifecycle_refuses_out_of_order_claims_impossible_shares_and_over_cap_settlements
        """
        printer, escape = self._open_escape_under_a_small_cap()

        premature = api_client.raise_recovery_claim(
            escape["id"], recovery_claim_payload(escape["version"]), quality()
        )
        validate_error(premature, ApiErrorId.ERR_ESCAPE_STATE_INVALID.value, 409)

        for party, share in (("PRINTER", 0.60), ("SHARED", 0.00)):
            impossible = api_client.assign_root_cause(
                escape["id"],
                root_cause_payload(
                    party, share, investigation_note="Apportionment draft."
                ),
                quality(),
            )
            validate_error(
                impossible, ApiErrorId.ERR_SHARE_INCONSISTENT_WITH_PARTY.value, 422
            )
        assert read_escape(escape["id"])["state"] == "OPEN"

        assigned = assign_root_cause(
            escape["id"],
            "PRINTER",
            1.00,
            investigation_note=(
                "Wrong allergen text traced to the printer plate archive."
            ),
        )
        assert assigned["state"] == "ROOT_CAUSE_ASSIGNED"
        assert assigned["printer_share_pct"] == pytest.approx(1.00, abs=0.01)

        claimed = raise_recovery_claim(escape["id"])
        # 546000 + 91000 + 0 + 150000 is 787000 gross, clamped to the 500000 cap.
        assert claimed["state"] == "RECOVERY_CLAIMED"
        assert claimed["provisional_recovery_cents"] == 500000
        assert claimed["liability_cap_applied"] is True

        over_cap = api_client.settle_escape(
            escape["id"],
            settle_payload(
                "SETTLED",
                actual_reprint_cost_cents=600000,
                actual_scrap_cost_cents=50000,
                actual_expedite_freight_cents=0,
                settlement_note="First invoice bundle.",
            ),
            admin(),
        )
        validate_error(
            over_cap, ApiErrorId.ERR_RECOVERY_EXCEEDS_LIABILITY_CAP.value, 422
        )
        assert read_escape(escape["id"])["state"] == "RECOVERY_CLAIMED"

        settled = settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=300000,
            actual_scrap_cost_cents=20000,
            actual_expedite_freight_cents=0,
            settlement_note="Revised invoice bundle inside the cap.",
        )
        # 300000 + 20000 + 0 + 150000 sits inside the cap, 30000 below the clamp.
        assert settled["state"] == "SETTLED"
        assert settled["final_recovery_cents"] == 470000
        assert settled["recovery_variance_cents"] == -30000

        vendor = read_printer(printer["id"])
        assert vendor["performance_score"] == pytest.approx(64.0, abs=0.01)
        assert vendor["certification_status"] == "PROBATION"
        assert vendor["recovery_balance_cents"] == 470000


class TestBudgetBoundaryIsInclusive:
    """A perfectly funded order lands exactly on the ceiling and is admitted."""

    def test_an_order_that_consumes_the_budget_exactly_is_funded(self):
        """163000 of budget funds a 163000 order, and the cheapest follow-up is not.

        PRD §3.7: "The asset's plate budget is checked last of all, after every safety
        and referential rule: the asset's current `committed_plate_cost_cents` plus the
        new order's `cost_cents` must not exceed the asset's `plate_budget_cents`, and a
        breach is `ERR_PLATE_BUDGET_EXCEEDED`."

        Design: Corner/validations/a_plate_order_consuming_the_budget_exactly_is_admitted_and_the_next_one_is_not
        """
        _brief, asset, version = approved_version(
            asset_overrides={"plate_budget_cents": 163000}
        )
        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        exact = new_plate_order(version["id"], printer, proof, plate_set_count=6)
        assert exact["cost_cents"] == 163000
        assert exact["status"] == "ORDERED"

        funded = read_asset(asset["id"])
        assert funded["committed_plate_cost_cents"] == 163000
        assert funded["plate_budget_cents"] == 163000

        # The cheapest possible order is still 18000 of plate plus a 60000 setup.
        cheapest = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], printer["id"], proof["id"], plate_set_count=1
            ),
            coord(),
        )
        validate_error(cheapest, ApiErrorId.ERR_PLATE_BUDGET_EXCEEDED.value, 422)

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 163000
        rows = plate_orders_for_version(version["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == exact["id"]
        assert rows[0]["status"] == "ORDERED"


class TestBudgetIsAnAggregateOverTheAssetLedger:
    """Four affordable orders where only the running total refuses the last."""

    def test_the_fourth_order_is_refused_by_the_sum_of_the_first_three(self):
        """489000 of live commitments leaves no room for the cheapest possible order.

        PRD §2.9: "An asset's `committed_plate_cost_cents` is the sum of `cost_cents`
        over that asset's plate orders whose `status` is `ORDERED`, so cancelled orders
        leave the ledger."

        PRD §3.7: "A successful order is created with `status` `ORDERED`, credits the
        asset's `committed_plate_cost_cents` by its `cost_cents` and increments the
        asset's `version` by 1."

        Design: Corner/validations/three_individually_affordable_plate_orders_exhaust_the_budget_for_the_fourth
        """
        _brief, asset, version = approved_version()
        assert read_asset(asset["id"])["plate_budget_cents"] == 500000
        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        orders = [
            new_plate_order(version["id"], printer, proof, plate_set_count=6)
            for _ in range(3)
        ]
        for order in orders:
            assert order["cost_cents"] == 163000
            assert order["status"] == "ORDERED"
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 489000

        fourth = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], printer["id"], proof["id"], plate_set_count=1
            ),
            coord(),
        )
        validate_error(fourth, ApiErrorId.ERR_PLATE_BUDGET_EXCEEDED.value, 422)

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 489000
        rows, meta = validate_paginated(
            api_client.list_plate_orders(
                coord(),
                params={"artwork_version_id": version["id"], "limit": 100},
            )
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert all(row["status"] == "ORDERED" for row in rows)
        assert {row["id"] for row in rows} == {order["id"] for order in orders}


class TestRunoutStateOutranksUnitConservation:
    """A completed runout refuses three writes with one error id."""

    def test_the_lifecycle_refusal_surfaces_ahead_of_the_payload_arithmetic(self):
        """Scrapping 50 units out of a remaining 0 reports the state, not the sum.

        PRD §2.7: "When a request violates more than one rule, the response is
        determined by the **first** rule violated in the following fixed order, not by
        whichever check the implementation happens to run first."

        PRD §3.8: "Either form is admissible only while the runout is `PLANNED` or
        `MONITORING`, else `ERR_RUNOUT_STATE_INVALID`."

        Design: Corner/validations/runout_state_outranks_unit_conservation_on_an_already_completed_runout
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        set_clock("2026-08-10T00:00:00Z")

        runout = new_runout(
            asset,
            v1,
            on_hand_qty=0,
            weekly_usage_qty=2500,
            runout_start_utc="2026-08-10T00:00:00Z",
        )
        assert runout["state"] == "RUNOUT_COMPLETE"
        assert runout["disposition"] == "RUNOUT"
        assert runout["remaining_qty"] == 0
        assert runout["reversal_count"] == 0

        scrap = api_client.disposition_runout(
            runout["id"],
            disposition_payload("SCRAP", units_scrapped=50, units_reworked=0),
            coord(),
        )
        validate_error(scrap, ApiErrorId.ERR_RUNOUT_STATE_INVALID.value, 409)

        append = api_client.append_depletion_records(
            runout["id"],
            depletion_records_payload([depletion("2026-08-17T00:00:00Z", 100)]),
            coord(),
        )
        validate_error(append, ApiErrorId.ERR_RUNOUT_STATE_INVALID.value, 409)

        reversal = api_client.reverse_runout_disposition(
            runout["id"], disposition_reversal_payload(), admin()
        )
        validate_error(reversal, ApiErrorId.ERR_RUNOUT_STATE_INVALID.value, 409)

        final = read_runout(runout["id"])
        assert final["state"] == "RUNOUT_COMPLETE"
        assert final["disposition"] == "RUNOUT"
        assert final["units_scrapped"] == 0
        assert final["units_reworked"] == 0
        assert final["reversal_count"] == 0
        assert final["depletion_records"] == []

        owning = read_asset(asset["id"])
        assert owning["obsolete_units_total"] == 0
        assert owning["changeover_cost_committed_cents"] == 0


class TestSubmitReadsThreeFactsOutOfTheClaimAggregate:
    """Four identical versions distinguished only by the claim each cites."""

    def _four_versions_one_per_claim(self):
        brief = new_approved_brief(market_codes=["US", "CA"], language_codes=["en"])
        asset = new_asset(brief["id"], market_code="US", language_codes=["en"])

        never_cleared = new_claim(claim_code="CLM-NAS-01", market_code="US")
        assert never_cleared["legal_status"] == "DRAFT"

        foreign = new_cleared_claim(
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-09-01T00:00:00Z",
            claim_code="CLM-GF-01",
            claim_text="Gluten free.",
            claim_type="FREE_FROM",
            market_code="CA",
            substantiation_ref="DOSSIER-GF-2026-01",
        )
        lapsing = new_cleared_claim(
            cleared_from_utc="2026-07-01T00:00:00Z",
            cleared_until_utc="2026-08-01T00:00:00Z",
            claim_code="CLM-ORG-01",
            claim_text="Made with organic cocoa.",
            claim_type="ORGANIC",
            market_code="US",
            substantiation_ref="DOSSIER-ORG-2026-01",
        )
        live = new_cleared_claim(
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-09-01T00:00:00Z",
            claim_code="CLM-FIB-01",
            claim_text="High in fibre.",
            claim_type="NUTRIENT_CONTENT",
            market_code="US",
            substantiation_ref="DOSSIER-FIB-2026-01",
        )

        versions = []
        for claim in (never_cleared, foreign, lapsing, live):
            drafted = new_version(read_asset(asset["id"]), claim_ids=[claim["id"]])
            verified = verify(drafted["id"])
            assert verified["state"] == "ELEMENTS_VERIFIED"
            # Two markets on the brief charge a 2.5-point breadth penalty.
            assert verified["compliance_score"] == pytest.approx(97.5, abs=0.01)
            versions.append(verified)
        return versions

    def test_legal_status_market_and_window_produce_three_different_refusals(self):
        """Only the US claim whose window still contains the moved clock routes.

        PRD §3.5: "Every entry of `claim_ids` must resolve to a claim whose
        `legal_status` is `CLEARED`, else `ERR_CLAIM_NOT_CLEARED`; each such claim's
        clearance window must contain the current logical-clock instant, meaning the
        clock is at or after `cleared_from_utc` and strictly before `cleared_until_utc`,
        else `ERR_CLAIM_CLEARANCE_EXPIRED`."

        PRD §3.5: "And each claim's own `market_code` must equal the owning asset's
        `market_code`, else `ERR_CLAIM_MARKET_MISMATCH`."

        Design: Corner/validations/submit_reads_three_different_facts_out_of_the_claim_aggregate
        """
        v_draft, v_foreign, v_lapsed, v_live = self._four_versions_one_per_claim()
        set_clock("2026-08-05T00:00:00Z")

        refusals = (
            (v_draft, ApiErrorId.ERR_CLAIM_NOT_CLEARED.value),
            (v_foreign, ApiErrorId.ERR_CLAIM_MARKET_MISMATCH.value),
            (v_lapsed, ApiErrorId.ERR_CLAIM_CLEARANCE_EXPIRED.value),
        )
        for version, error_id in refusals:
            refused = api_client.submit_artwork_version(
                version["id"], submit_payload(), coord()
            )
            validate_error(refused, error_id, 422)

            stalled = read_version(version["id"])
            assert stalled["state"] == "ELEMENTS_VERIFIED"
            assert stalled["route_count"] == 0
            assert routes_for(version["id"]) == []

        routed = submit(v_live["id"])
        assert routed["state"] == "IN_REVIEW"
        assert routed["route_count"] == 1
        assert len(routes_for(v_live["id"])) == 1


class TestReleaseWaitsOnTheReverificationFlag:
    """One conditional verdict, one blocked release, one clearing run."""

    CONDITION = "DATE_CODE_PRESS_CHECK"

    def test_a_fresh_verification_run_clears_the_flag_but_not_the_audit_trail(self):
        """Release is refused, re-verification flips the flag, release then lands.

        PRD §3.7: "The version's `requires_reverification` must be false, else
        `ERR_REVERIFICATION_REQUIRED`, so an approval that carried any conditional
        decision cannot reach plates until a fresh verification run has cleared the
        flag."

        PRD §3.4: "It is admissible from four states and its effect on `state` differs
        in each: from `DRAFT` it advances the version `DRAFT → ELEMENTS_VERIFIED`; from
        `ELEMENTS_VERIFIED` it re-runs and leaves the state unchanged, which is what an
        author does after editing the payload; from `REVISION_REQUESTED` it re-runs and
        likewise leaves the state unchanged — re-verification explicitly does **not**
        clear a requested revision, which still has to be re-opened separately; and from
        `APPROVED` it is admissible only when `requires_reverification` is true, in which
        case it re-runs and then sets that flag back to false."

        Design: Corner/validations/release_is_blocked_only_while_a_conditional_approval_is_outstanding
        """
        _brief, _asset, version = in_review_version()
        tasks = tasks_by_discipline(current_route(version["id"])["id"])
        decide_task(tasks["BRAND"], "APPROVED")
        decide_task(tasks["REGULATORY"], "APPROVED")
        decide_task(tasks["LEGAL"], "APPROVED")
        decide_task(tasks["QUALITY"], "CONDITIONAL", condition_code=self.CONDITION)

        conditioned = read_version(version["id"])
        assert conditioned["state"] == "APPROVED"
        assert conditioned["requires_reverification"] is True
        assert conditioned["open_condition_codes"] == [self.CONDITION]
        assert conditioned["check_run_no"] == 1
        assert conditioned["released_at"] is None

        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert proof["proof_state"] == "PROOF_APPROVED"

        blocked = api_client.release_to_print(
            version["id"], release_payload(), coord()
        )
        validate_error(blocked, ApiErrorId.ERR_REVERIFICATION_REQUIRED.value, 422)
        assert read_version(version["id"])["released_at"] is None
        assert read_version(version["id"])["state"] == "APPROVED"

        cleared = verify(
            version["id"],
            verification_note="Re-verification clearing the conditional approval.",
        )
        assert cleared["state"] == "APPROVED"
        assert cleared["check_run_no"] == 2
        assert cleared["requires_reverification"] is False
        assert cleared["compliance_score"] == pytest.approx(100.0, abs=0.01)
        assert cleared["open_condition_codes"] == [self.CONDITION]

        released = release(version["id"])
        assert released["state"] == "RELEASED_TO_PRINT"
        assert released["released_at"].startswith("2026-08-01T00:00:00")

        rows, meta = validate_paginated(
            api_client.list_element_checks(
                coord(),
                params={"artwork_version_id": version["id"], "limit": 100},
            )
        )
        assert len(rows) == 7
        assert meta["total_count"] == 7
        assert all(row["check_run_no"] == 2 for row in rows)


class TestReleaseWaitsOnADerivedProofVerdict:
    """A proof that exists, and is refused, because its verdict resolved against it."""

    def test_a_rejected_proof_is_no_authorisation_and_a_second_proof_is(self):
        """2.50 against a tolerance of 2.0 shuts the proof while substrate is pending.

        PRD §3.6: "If `color_status` is `COLOR_FAIL` or `substrate_status` is
        `SUBSTRATE_REJECTED`, the proof is `PROOF_REJECTED` — and this holds even while
        another dimension is still pending, so a colour failure fixes the outcome
        immediately without waiting for the substrate judgement."

        PRD §3.7: "And at least one proof of the version must read `PROOF_APPROVED`,
        else `ERR_PROOF_NOT_APPROVED`."

        Design: Corner/validations/release_and_plate_orders_wait_on_a_derived_proof_verdict_not_on_the_proof_existing
        """
        _brief, asset, version = approved_version()
        assert version["requires_reverification"] is False
        printer = new_printer()

        rejected = new_proof(version["id"], printer, proof_note="Contract proof.")
        assert rejected["effective_tolerance"] == pytest.approx(2.0, abs=0.01)
        failed = decide_color(rejected["id"], 2.50)
        assert failed["color_status"] == "COLOR_FAIL"
        assert failed["substrate_status"] == "SUBSTRATE_PENDING"
        assert failed["proof_state"] == "PROOF_REJECTED"

        blocked_release = api_client.release_to_print(
            version["id"], release_payload(), coord()
        )
        validate_error(blocked_release, ApiErrorId.ERR_PROOF_NOT_APPROVED.value, 422)
        assert read_version(version["id"])["state"] == "APPROVED"

        blocked_order = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], printer["id"], rejected["id"], plate_set_count=6
            ),
            coord(),
        )
        validate_error(blocked_order, ApiErrorId.ERR_PROOF_NOT_APPROVED.value, 422)
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

        replacement = new_proof(version["id"], printer, proof_note="Contract proof.")
        assert replacement["proof_no"] == 2
        decide_color(replacement["id"], 1.20)
        resolved = decide_substrate(replacement["id"], "SUBSTRATE_APPROVED")
        assert resolved["proof_state"] == "PROOF_APPROVED"
        assert resolved["effective_tolerance"] == pytest.approx(2.0, abs=0.01)

        released = release(version["id"])
        assert released["state"] == "RELEASED_TO_PRINT"

        order = new_plate_order(
            version["id"], printer, replacement, plate_set_count=6
        )
        assert order["cost_cents"] == 163000
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 163000

        stale = read_proof(rejected["id"])
        assert stale["proof_state"] == "PROOF_REJECTED"
        assert stale["substrate_status"] == "SUBSTRATE_PENDING"


class TestRejectedIsTerminalForAClaimFromEitherDirection:
    """Withdrawal from cleared, abandonment from draft, and no way back."""

    def test_the_withdrawn_window_survives_and_neither_claim_can_be_recleared(self):
        """One endpoint, two arrival paths into REJECTED, two identical refusals.

        PRD §3.2: "A claim already in `CLEARED` may also be withdrawn, moving
        `CLEARED → REJECTED` with the same requirement; withdrawal deliberately
        **retains** the stored `cleared_from_utc` and `cleared_until_utc` for audit
        rather than nulling them."

        PRD §3.2: "`REJECTED` is terminal in both forms: any further clearance decision
        on a rejected claim is `ERR_CLAIM_STATE_INVALID`."

        Design: Corner/validations/rejected_is_terminal_for_a_claim_from_either_direction
        """
        cleared = new_cleared_claim(
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-09-01T00:00:00Z",
            claim_code="CLM-NAS-01",
            claim_type="NUTRIENT_CONTENT",
            market_code="US",
        )
        assert cleared["legal_status"] == "CLEARED"
        assert cleared["version"] == 2
        assert cleared["usage_count"] == 0

        drafted = new_claim(
            claim_code="CLM-GF-01",
            claim_text="Gluten free.",
            claim_type="FREE_FROM",
            market_code="US",
            substantiation_ref="DOSSIER-GF-2026-01",
        )
        assert drafted["legal_status"] == "DRAFT"
        assert drafted["version"] == 1
        assert drafted["cleared_from_utc"] is None
        assert drafted["cleared_until_utc"] is None

        withdrawn = reject_claim(
            cleared["id"],
            rejection_reason="Substantiation dossier retracted by the supplier.",
        )
        assert withdrawn["legal_status"] == "REJECTED"
        assert len(withdrawn["rejection_reason"]) > 0
        assert withdrawn["cleared_by_user_id"] == "u_legal"
        # PRD §2.4: timestamps are rendered with three fractional digits.
        assert withdrawn["cleared_from_utc"] == "2026-08-01T00:00:00.000Z"
        assert withdrawn["cleared_until_utc"] == "2026-09-01T00:00:00.000Z"

        recleared = api_client.decide_claim_clearance(
            cleared["id"],
            clearance_payload(
                "CLEARED",
                cleared_from_utc="2026-09-01T00:00:00Z",
                cleared_until_utc="2026-10-01T00:00:00Z",
            ),
            legal(),
        )
        validate_error(recleared, ApiErrorId.ERR_CLAIM_STATE_INVALID.value, 409)
        assert read_claim(cleared["id"])["legal_status"] == "REJECTED"

        abandoned = reject_claim(
            drafted["id"],
            rejection_reason="Never substantiated; abandoned before review.",
        )
        assert abandoned["legal_status"] == "REJECTED"
        assert abandoned["cleared_from_utc"] is None
        assert abandoned["cleared_until_utc"] is None

        first_clearance = api_client.decide_claim_clearance(
            drafted["id"],
            clearance_payload(
                "CLEARED",
                cleared_from_utc="2026-08-01T00:00:00Z",
                cleared_until_utc="2026-09-01T00:00:00Z",
            ),
            legal(),
        )
        validate_error(first_clearance, ApiErrorId.ERR_CLAIM_STATE_INVALID.value, 409)
        assert read_claim(drafted["id"])["legal_status"] == "REJECTED"

        # Two successful decisions on one claim, one on the other, and no refusal bumps.
        assert read_claim(cleared["id"])["version"] == 3
        assert read_claim(drafted["id"])["version"] == 2


class TestDepletionOrderAndUnitConservation:
    """Ascending weeks, an exact partition of the residue, and the money that follows."""

    def _monitoring_runout(self):
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        assert asset["standard_unit_cost_cents"] == 42
        assert asset["obsolete_units_total"] == 0
        assert asset["changeover_cost_committed_cents"] == 0
        set_clock("2026-08-03T00:00:00Z")

        runout = new_runout(
            asset,
            v1,
            on_hand_qty=20000,
            weekly_usage_qty=3000,
            runout_start_utc="2026-08-03T00:00:00Z",
        )
        assert runout["state"] == "PLANNED"
        # Seven whole weeks of plan from 2026-08-03.
        assert runout["projected_runout_date"] == "2026-09-21"
        assert runout["depletion_records"] == []
        return asset, v1, runout

    def test_descending_weeks_are_refused_and_the_split_must_partition_the_residue(self):
        """Two ordering refusals, two conservation refusals, then a priced scrap.

        PRD §3.8: "Ordering is strictly enforced so that the stored array is always
        already sorted: within the submitted batch the `week_start_utc` values must be
        strictly ascending, and every submitted `week_start_utc` must be strictly later
        than the greatest `week_start_utc` already stored."

        PRD §3.8: "A `SCRAP` disposition writes off what is left and therefore requires
        both `units_scrapped` and `units_reworked` in the payload — omitting either is
        `ERR_INVALID_REQUEST` — and requires their sum to equal `remaining_qty`
        **exactly**, neither more nor less; any other sum is
        `ERR_UNIT_CONSERVATION_VIOLATION`."

        Design: Corner/validations/depletion_weeks_must_ascend_and_a_scrap_split_must_conserve_every_remaining_unit
        """
        asset, v1, runout = self._monitoring_runout()

        descending = api_client.append_depletion_records(
            runout["id"],
            depletion_records_payload(
                [
                    depletion("2026-08-10T00:00:00Z", 4000),
                    depletion("2026-08-03T00:00:00Z", 3000),
                ]
            ),
            coord(),
        )
        validate_error(
            descending, ApiErrorId.ERR_DEPLETION_RECORD_OUT_OF_ORDER.value, 409
        )
        assert read_runout(runout["id"])["depletion_records"] == []

        monitoring = append_depletion(
            runout["id"],
            [
                depletion("2026-08-03T00:00:00Z", 3000),
                depletion("2026-08-10T00:00:00Z", 4000),
            ],
        )
        assert monitoring["state"] == "MONITORING"
        assert monitoring["remaining_qty"] == 13000
        assert monitoring["trailing_avg_usage_qty"] == 3500
        # Anchor 2026-08-17 plus four extrapolated weeks at 3500 a week.
        assert monitoring["actual_runout_date"] == "2026-09-14"
        assert monitoring["projected_runout_date"] == "2026-09-21"
        assert len(monitoring["depletion_records"]) == 2

        repeated = api_client.append_depletion_records(
            runout["id"],
            depletion_records_payload([depletion("2026-08-10T00:00:00Z", 2000)]),
            coord(),
        )
        validate_error(
            repeated, ApiErrorId.ERR_DEPLETION_RECORD_OUT_OF_ORDER.value, 409
        )
        assert read_runout(runout["id"])["remaining_qty"] == 13000

        overshoot = api_client.disposition_runout(
            runout["id"],
            disposition_payload("SCRAP", units_scrapped=13000, units_reworked=1),
            coord(),
        )
        validate_error(
            overshoot, ApiErrorId.ERR_UNIT_CONSERVATION_VIOLATION.value, 422
        )

        premature = api_client.disposition_runout(
            runout["id"], disposition_payload("RUNOUT"), coord()
        )
        validate_error(
            premature, ApiErrorId.ERR_UNIT_CONSERVATION_VIOLATION.value, 422
        )
        assert read_runout(runout["id"])["state"] == "MONITORING"

        scrapped = disposition_runout(
            runout["id"], "SCRAP", units_scrapped=10000, units_reworked=3000
        )
        assert scrapped["state"] == "SCRAPPED"
        assert scrapped["units_scrapped"] == 10000
        assert scrapped["units_reworked"] == 3000
        assert scrapped["material_writeoff_cents"] == 420000
        assert scrapped["relabel_cost_cents"] == 54000
        assert scrapped["changeover_base_cents"] == 474000
        # A base below 500000 attracts the 5 percent tier.
        assert scrapped["changeover_expedite_cents"] == 23700
        assert scrapped["total_changeover_cost_cents"] == 497700

        owning = read_asset(asset["id"])
        assert owning["obsolete_units_total"] == 10000
        assert owning["changeover_cost_committed_cents"] == 497700
        assert owning["obsolescence_state"] == "SUPERSEDED"
        assert read_version(v1["id"])["state"] == "OBSOLETE"
