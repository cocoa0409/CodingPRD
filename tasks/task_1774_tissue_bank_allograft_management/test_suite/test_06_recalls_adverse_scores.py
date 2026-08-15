"""Recalls, adverse reaction cases, and the supplier qualification score
model: sweeps, reopen cycles, auto-suspension, and reinstatement gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    build_user_headers,
    create_document_payload,
    create_recall,
    create_shipment,
    get_success_data,
    issue_unit,
    make_manifest_item,
    release_units,
    report_adverse_reaction,
    setup_accepted_units,
    setup_available_units,
    setup_case,
    setup_freezer,
    setup_implanted_unit,
    setup_reservation,
    units_of_shipment,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
CO = TEST_USERS["compliance_headers"]
SURG = TEST_USERS["surgeon_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestRecallLifecycle:
    def test_recall_zero_match_auto_closes_no_match(self, api):
        """PRD §3.6: "If the sweep matches nothing, the recall closes itself
        immediately: it transitions from `DRAFT` straight to `CLOSED` with
        `closure_reason` `NO_MATCH`."

        Design: Corner/state_machines/recall_zero_match_auto_closes_no_match
        """
        supplier, _, _, units = setup_accepted_units()
        recall = create_recall(
            supplier["id"], lot_numbers=["L-UNKNOWN"],
            reason="Precautionary recall of unknown lot",
        )
        activated = validate_success(api.activate_recall(recall["id"], QM))
        assert activated["status"] == "CLOSED"
        assert activated["closure_reason"] == "NO_MATCH"
        assert activated["affected_unit_count"] == 0
        unit_after = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit_after["status"] == "QUARANTINED"
        assert unit_after["hold_reason"] == "NONE"

    def test_recall_close_blocked_until_units_disposed(self, api):
        """PRD §3.6: "It is defined only from `ACTIVE`
        (`ERR_RECALL_INVALID_STATE`), and it is refused with
        `ERR_RECALL_UNRESOLVED_UNITS` while any unit matching the recall's
        scope still sits in `QUARANTINED` with `hold_reason` `RECALL` — such
        units must first be released, returned to the supplier, discarded, or
        swept to expiry. A clean close moves the recall to `CLOSED` with
        `closure_reason` `RESOLVED` and recomputes the supplier's scores, the
        recall leaving the provisional model's active-recall term."

        Design: Corner/state_machines/recall_close_blocked_until_units_disposed
        """
        supplier, _, _, units = setup_available_units()
        recall = create_recall(supplier["id"], lot_numbers=["L1"],
                               reason="Lot L1 sterility failure")
        get_success_data(api.activate_recall(recall["id"], QM))
        held = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert held["status"] == "QUARANTINED"
        assert held["hold_reason"] == "RECALL"

        resp = api.close_recall(recall["id"], QM)
        validate_error(resp, ApiErrorId.ERR_RECALL_UNRESOLVED_UNITS)

        discarded = validate_success(
            api.discard_unit(units[0]["id"], {"reason": "Destroyed per recall R1"}, QM)
        )
        assert discarded["status"] == "DISCARDED"
        records = get_success_data(api.list_unit_disposition_records(units[0]["id"], QM))
        assert len(records) == 1
        assert records[0]["disposition_type"] == "DESTROYED"
        assert records[0]["status"] == "DRAFT"

        closed = validate_success(api.close_recall(recall["id"], QM))
        assert closed["status"] == "CLOSED"
        assert closed["closure_reason"] == "RESOLVED"

    def test_recall_close_from_draft_and_reactivate_blocked(self, api):
        """PRD §3.6: "Activation is where the recall bites, and it is defined
        only from `DRAFT` (`ERR_RECALL_INVALID_STATE` otherwise)."
        PRD §3.6: "It is defined only from `ACTIVE` (`ERR_RECALL_INVALID_STATE`)"

        Design: Corner/errors/error_recall_close_from_draft_and_reactivate_blocked
        """
        supplier, _, _, _ = setup_accepted_units()
        recall1 = create_recall(supplier["id"], lot_numbers=["L1"],
                                reason="Audit-triggered recall")
        recall2 = create_recall(supplier["id"], lot_numbers=["L2"],
                                reason="Second draft recall")
        validate_error(api.close_recall(recall2["id"], QM),
                       ApiErrorId.ERR_RECALL_INVALID_STATE)
        activated = validate_success(api.activate_recall(recall1["id"], QM))
        assert activated["status"] == "ACTIVE"
        validate_error(api.activate_recall(recall1["id"], QM),
                       ApiErrorId.ERR_RECALL_INVALID_STATE)


class TestAdverseReactionLifecycle:
    def test_adverse_resolve_by_reporting_user_blocked_sod(self, api):
        """PRD §3.7: "Resolution supplies an `outcome` of `CONFIRMED` or
        `UNCONFIRMED` plus `outcome_notes` of at least ten characters
        (`ERR_INVALID_REQUEST` on shorter notes), is permitted only from
        `UNDER_INVESTIGATION` (`ERR_ADVERSE_INVALID_STATE`), and observes the
        segregation rule of §2.10: the resolving officer must not be the
        `reporter_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/adverse_resolve_by_reporting_user_blocked_sod
        """
        bundle = setup_implanted_unit(via_reservation=False)
        case_id = bundle["case"]["id"]
        unit_id = bundle["unit"]["id"]
        adverse = report_adverse_reaction(case_id, unit_id)
        get_success_data(api.investigate_adverse_reaction(adverse["id"], CO))
        reporter_as_co = build_user_headers("surg-1", "ComplianceOfficer")
        resp = api.resolve_adverse_reaction(
            adverse["id"],
            {"outcome": "CONFIRMED",
             "outcome_notes": "Self-resolution attempt by reporter"},
            reporter_as_co,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_adverse_reaction(adverse["id"], CO))
        assert after["status"] == "UNDER_INVESTIGATION"

    def test_adverse_resolve_before_investigate_blocked(self, api):
        """PRD §3.7: "is permitted only from `UNDER_INVESTIGATION`
        (`ERR_ADVERSE_INVALID_STATE`)"
        PRD §3.7: "Opening an investigation is defined from `REPORTED` and from
        `REOPENED` alike — any other state fails with
        `ERR_ADVERSE_INVALID_STATE` — and moves the case to
        `UNDER_INVESTIGATION`."

        Design: Corner/errors/error_adverse_resolve_before_investigate_blocked
        """
        bundle = setup_implanted_unit(via_reservation=False)
        adverse = report_adverse_reaction(
            bundle["case"]["id"], bundle["unit"]["id"],
            reaction_type="OTHER", severity="MINOR",
            description="Unexpected febrile episode",
        )
        assert adverse["status"] == "REPORTED"
        resp = api.resolve_adverse_reaction(
            adverse["id"],
            {"outcome": "UNCONFIRMED",
             "outcome_notes": "Skipping investigation step"},
            CO,
        )
        validate_error(resp, ApiErrorId.ERR_ADVERSE_INVALID_STATE)

    def test_adverse_reopen_restores_supplier_score(self, api):
        """PRD §3.7: "Either closed state can be reopened by a
        `ComplianceOfficer` supplying a `reopen_reason` of at least ten
        characters, moving the case to `REOPENED` and incrementing
        `reopened_count` by one. Reopening a case that was `CLOSED_CONFIRMED`
        reverses its confirmed finding — both scores regain 20 points — and in
        either case the reopened case rejoins the provisional model's
        open-case term until it is resolved again."

        Design: Corner/errors/error_adverse_reopen_restores_supplier_score
        """
        bundle = setup_implanted_unit(via_reservation=False)
        supplier_id = bundle["supplier"]["id"]
        adverse = report_adverse_reaction(
            bundle["case"]["id"], bundle["unit"]["id"],
            description="Infection at graft site",
        )
        get_success_data(api.investigate_adverse_reaction(adverse["id"], CO))
        resolved = validate_success(
            api.resolve_adverse_reaction(
                adverse["id"],
                {"outcome": "CONFIRMED",
                 "outcome_notes": "Cultures confirm graft link"},
                CO,
            )
        )
        assert resolved["status"] == "CLOSED_CONFIRMED"
        mid = validate_success(api.get_supplier(supplier_id, CO))
        assert mid["qualification_score_final"] == 80

        reopened = validate_success(
            api.reopen_adverse_reaction(
                adverse["id"], {"reopen_reason": "Appeal granted by review board"}, CO
            )
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_count"] == 1
        supplier = validate_success(api.get_supplier(supplier_id, CO))
        assert supplier["qualification_score_final"] == 100
        assert supplier["qualification_score_provisional"] == 90
        assert supplier["status"] == "QUALIFIED"


class TestSupplierScoreDivergence:
    def _setup_open_adverse_and_active_recall(self, api):
        """One IMPLANTED unit, one REPORTED adverse case, one ACTIVE recall."""
        bundle = setup_implanted_unit(via_reservation=True)
        adverse = report_adverse_reaction(
            bundle["case"]["id"], bundle["unit"]["id"],
            description="Post-operative infection at graft site",
        )
        recall = create_recall(
            bundle["supplier"]["id"], lot_numbers=["L1"],
            reason="Sterility assurance letter from supplier",
        )
        activated = validate_success(api.activate_recall(recall["id"], QM))
        return bundle, adverse, activated

    def test_provisional_score_counts_open_items(self, api):
        """PRD §3.8: "The provisional score, `qualification_score_provisional`,
        is the early-warning figure. It starts from 100, subtracts 20 points
        for each confirmed finding (an adverse reaction case in
        `CLOSED_CONFIRMED` whose implicated unit traces back to this supplier),
        subtracts 15 points for each of the supplier's recalls currently
        `ACTIVE`, subtracts 10 points for each open adverse reaction case —
        those in `REPORTED`, `UNDER_INVESTIGATION`, or `REOPENED` — and
        subtracts 5 points for each expired-document event (a supplier document
        now in `EXPIRED`). The result is floored at 0."

        Design: Difficulty/dual_variant_calc/supplier_score_provisional_vs_final_diverge
        """
        bundle, _, activated = self._setup_open_adverse_and_active_recall(api)
        assert activated["status"] == "ACTIVE"
        assert activated["affected_unit_count"] == 1
        supplier = validate_success(api.get_supplier(bundle["supplier"]["id"], CO))
        # 100 - 10*1 open adverse - 15*1 active recall = 75
        assert supplier["qualification_score_provisional"] == 75

    def test_final_score_ignores_open_items(self, api):
        """PRD §3.8: "The final score, `qualification_score_final`, is the
        settled figure. It starts from 100, subtracts 20 points per confirmed
        finding and 5 points per expired-document event, and counts nothing
        else: open investigations and active recalls contribute only to the
        provisional figure. It too is floored at 0."

        Design: Difficulty/dual_variant_calc/supplier_score_provisional_vs_final_diverge
        """
        bundle, _, activated = self._setup_open_adverse_and_active_recall(api)
        supplier = validate_success(api.get_supplier(bundle["supplier"]["id"], CO))
        assert supplier["qualification_score_final"] == 100
        recall = validate_success(api.get_recall(activated["id"], QM))
        assert recall["status"] == "ACTIVE"
        assert recall["affected_unit_count"] == 1


class TestAdverseReopenCycle:
    def _run_full_cycle(self, api):
        """REPORTED -> UNDER_INVESTIGATION -> CLOSED_UNCONFIRMED -> REOPENED ->
        UNDER_INVESTIGATION -> CLOSED_CONFIRMED."""
        bundle = setup_implanted_unit(via_reservation=True)
        adverse = report_adverse_reaction(
            bundle["case"]["id"], bundle["unit"]["id"],
            reaction_type="REJECTION", description="Graft rejection observed post-op",
        )
        get_success_data(api.investigate_adverse_reaction(adverse["id"], CO))
        unconfirmed = validate_success(
            api.resolve_adverse_reaction(
                adverse["id"],
                {"outcome": "UNCONFIRMED",
                 "outcome_notes": "No link to graft established"},
                CO,
            )
        )
        assert unconfirmed["status"] == "CLOSED_UNCONFIRMED"
        get_success_data(
            api.reopen_adverse_reaction(
                adverse["id"], {"reopen_reason": "New serology evidence received"}, CO
            )
        )
        get_success_data(api.investigate_adverse_reaction(adverse["id"], CO))
        confirmed = validate_success(
            api.resolve_adverse_reaction(
                adverse["id"],
                {"outcome": "CONFIRMED",
                 "outcome_notes": "Serology confirms graft-versus-host link"},
                CO,
            )
        )
        return bundle, adverse, confirmed

    def test_reopen_cycle_traverses_all_states(self, api):
        """PRD §3.7: "Either closed state can be reopened by a
        `ComplianceOfficer` supplying a `reopen_reason` of at least ten
        characters, moving the case to `REOPENED` and incrementing
        `reopened_count` by one."
        PRD §3.7: "Opening an investigation is defined from `REPORTED` and from
        `REOPENED` alike — any other state fails with
        `ERR_ADVERSE_INVALID_STATE` — and moves the case to
        `UNDER_INVESTIGATION`."

        Design: Difficulty/non_linear_state_machine/adverse_reaction_reopen_cycle
        """
        _, adverse, confirmed = self._run_full_cycle(api)
        assert confirmed["status"] == "CLOSED_CONFIRMED"
        after = validate_success(api.get_adverse_reaction(adverse["id"], CO))
        assert after["status"] == "CLOSED_CONFIRMED"
        assert after["reopened_count"] == 1

    def test_reopen_cycle_scores_reflect_only_last_closure(self, api):
        """PRD §3.7: "A confirmed outcome moves the case to `CLOSED_CONFIRMED`,
        stamps `investigator_user_id`, and lands a confirmed finding on the
        supplier — both qualification scores drop by 20 points, and if the
        provisional score falls below the suspension threshold while the
        supplier is `QUALIFIED`, automatic suspension follows."
        PRD §3.8: "It starts from 100, subtracts 20 points per confirmed
        finding and 5 points per expired-document event, and counts nothing
        else: open investigations and active recalls contribute only to the
        provisional figure."

        Design: Difficulty/non_linear_state_machine/adverse_reaction_reopen_cycle
        """
        bundle, _, confirmed = self._run_full_cycle(api)
        supplier = validate_success(api.get_supplier(bundle["supplier"]["id"], CO))
        assert supplier["qualification_score_final"] == 80
        assert supplier["qualification_score_provisional"] == 80
        assert supplier["status"] == "QUALIFIED"


class TestConfirmedCascadeAutoSuspension:
    def _setup_two_implants_with_open_adverse_and_recall(self, api):
        """2 units IMPLANTED into two cases, both with REPORTED adverse cases,
        plus one ACTIVE recall matching both units (provisional 65)."""
        supplier, freezer, shipment, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        case1 = setup_case(patient_ref="P-1", or_room_id="OR-1")
        case2 = setup_case(patient_ref="P-2", or_room_id="OR-2")
        res1 = setup_reservation(case1["id"], units[0]["id"])
        res2 = setup_reservation(case2["id"], units[1]["id"])
        issue_unit(units[0]["id"], reservation_id=res1["id"])
        issue_unit(units[1]["id"], reservation_id=res2["id"])
        advance_clock("2026-08-10T11:00:00Z")
        get_success_data(
            api.record_implantation(case1["id"], {"tissue_unit_id": units[0]["id"]}, SURG)
        )
        get_success_data(
            api.record_implantation(case2["id"], {"tissue_unit_id": units[1]["id"]}, SURG)
        )
        ar1 = report_adverse_reaction(
            case1["id"], units[0]["id"],
            reaction_type="INFECTION", severity="CRITICAL",
            description="Deep surgical site infection confirmed",
        )
        ar2 = report_adverse_reaction(
            case2["id"], units[1]["id"],
            reaction_type="REJECTION", severity="MAJOR",
            description="Early graft rejection signs",
        )
        recall = create_recall(supplier["id"], lot_numbers=["L1"],
                               reason="Supplier sterility assurance failure")
        get_success_data(api.activate_recall(recall["id"], QM))
        return {
            "supplier": supplier, "freezer": freezer, "units": units,
            "case1": case1, "case2": case2, "ar1": ar1, "ar2": ar2,
            "recall": recall,
        }

    def test_confirmed_resolve_recomputes_scores_and_suspends(self, api):
        """PRD §3.7: "A confirmed outcome moves the case to `CLOSED_CONFIRMED`,
        stamps `investigator_user_id`, and lands a confirmed finding on the
        supplier — both qualification scores drop by 20 points, and if the
        provisional score falls below the suspension threshold while the
        supplier is `QUALIFIED`, automatic suspension follows."
        PRD §3.8: "The provisional score drives an automatic gate, evaluated on
        every score mutation: when a `QUALIFIED` supplier's
        `qualification_score_provisional` falls below 60, the supplier moves to
        `SUSPENDED` and `suspended_at` is stamped with the clock — no human
        decision is required."

        Design: Difficulty/transitive_cascade/confirmed_adverse_reaction_cascade_auto_suspends_supplier
        """
        ctx = self._setup_two_implants_with_open_adverse_and_recall(api)
        pre = validate_success(api.get_supplier(ctx["supplier"]["id"], CO))
        assert pre["status"] == "QUALIFIED"
        # 100 - 15 recall - 10*2 open adverse = 65
        assert pre["qualification_score_provisional"] == 65

        get_success_data(api.investigate_adverse_reaction(ctx["ar1"]["id"], CO))
        resolved = validate_success(
            api.resolve_adverse_reaction(
                ctx["ar1"]["id"],
                {"outcome": "CONFIRMED",
                 "outcome_notes": "Cultures match graft contamination"},
                CO,
            )
        )
        assert resolved["status"] == "CLOSED_CONFIRMED"
        post = validate_success(api.get_supplier(ctx["supplier"]["id"], CO))
        # 100 - 20 confirmed - 10 open - 15 recall = 55 -> auto-suspended
        assert post["qualification_score_provisional"] == 55
        assert post["qualification_score_final"] == 80
        assert post["status"] == "SUSPENDED"

    def test_auto_suspension_blocks_new_receipts(self, api):
        """PRD §3.8: "The same gate stands behind the document-expiry cascade
        of §3.1, and together they explain why shipments from a lapsed supplier
        begin failing at receipt creation and acceptance with
        `ERR_SUPPLIER_NOT_QUALIFIED` the moment coverage lapses."
        PRD §3.2: "The supplier must be `QUALIFIED` at receipt time —
        consignments from suspended, pending, or disqualified sources are
        refused with `ERR_SUPPLIER_NOT_QUALIFIED`."

        Design: Difficulty/transitive_cascade/confirmed_adverse_reaction_cascade_auto_suspends_supplier
        """
        ctx = self._setup_two_implants_with_open_adverse_and_recall(api)
        get_success_data(api.investigate_adverse_reaction(ctx["ar1"]["id"], CO))
        get_success_data(
            api.resolve_adverse_reaction(
                ctx["ar1"]["id"],
                {"outcome": "CONFIRMED",
                 "outcome_notes": "Cultures match graft contamination"},
                CO,
            )
        )
        resp = api.create_shipment(
            {
                "supplier_id": ctx["supplier"]["id"],
                "freezer_id": ctx["freezer"]["id"],
                "items": [make_manifest_item(lot_number="L2", serial_number="U-101")],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)
        ar2_after = validate_success(api.get_adverse_reaction(ctx["ar2"]["id"], CO))
        assert ar2_after["status"] == "REPORTED"


class TestScoreThresholdAndDocumentCascade:
    def test_reinstate_below_score_threshold(self, api):
        """PRD §3.1: "From `SUSPENDED`, reinstatement by a `ComplianceOfficer`
        re-applies the same documentary coverage check as approval
        (`ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED` on lapse) and additionally
        demands a `qualification_score_provisional` of at least 60; a weaker
        score is rejected with `ERR_SUPPLIER_SCORE_BELOW_THRESHOLD`."
        PRD §3.8: "The provisional score drives an automatic gate, evaluated on
        every score mutation: when a `QUALIFIED` supplier's
        `qualification_score_provisional` falls below 60, the supplier moves to
        `SUSPENDED` and `suspended_at` is stamped with the clock — no human
        decision is required."

        Design: Corner/errors/error_reinstate_below_score_threshold
        """
        # Supplier with required docs valid to 2027 and two ISO certificates
        # expiring on 2026-12-01 and 2026-12-15.
        supplier = get_success_data(api.create_supplier(
            {"legal_name": "Acme Tissue Source", "license_number": "LIC-001"}, QM))
        for doc_type, ref, vfrom, vto in [
            ("AATB_ACCREDITATION", "AATB-1", "2026-01-01T00:00:00Z", "2027-12-31T00:00:00Z"),
            ("FDA_REGISTRATION", "FDA-1", "2026-01-01T00:00:00Z", "2027-12-31T00:00:00Z"),
            ("ISO_CERTIFICATE", "ISO-1", "2026-06-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            ("ISO_CERTIFICATE", "ISO-2", "2026-12-02T00:00:00Z", "2026-12-15T00:00:00Z"),
        ]:
            doc = get_success_data(
                api.create_supplier_document(
                    supplier["id"],
                    create_document_payload(doc_type=doc_type, document_ref=ref,
                                            valid_from=vfrom, valid_to=vto),
                    QM,
                )
            )
            get_success_data(api.verify_document(supplier["id"], doc["id"], QM))
        get_success_data(api.approve_supplier(supplier["id"], CO))
        freezer = setup_freezer()
        shipment = create_shipment(
            supplier["id"], freezer["id"],
            [
                make_manifest_item(serial_number="U-001",
                                   expiration_at="2027-06-01T00:00:00Z"),
                make_manifest_item(serial_number="U-002",
                                   expiration_at="2027-06-01T00:00:00Z"),
            ],
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        units = release_units(units_of_shipment(shipment["id"]))
        case1 = setup_case(patient_ref="P-1", or_room_id="OR-1")
        case2 = setup_case(patient_ref="P-2", or_room_id="OR-2")
        issue_unit(units[0]["id"])
        issue_unit(units[1]["id"])
        advance_clock("2026-08-10T11:00:00Z")
        get_success_data(
            api.record_implantation(case1["id"], {"tissue_unit_id": units[0]["id"]}, SURG)
        )
        get_success_data(
            api.record_implantation(case2["id"], {"tissue_unit_id": units[1]["id"]}, SURG)
        )
        report_adverse_reaction(case1["id"], units[0]["id"],
                                description="Infection at graft site one")
        report_adverse_reaction(case2["id"], units[1]["id"],
                                reaction_type="REJECTION", severity="MINOR",
                                description="Mild rejection signs observed")
        recall = create_recall(supplier["id"], lot_numbers=["L1"],
                               reason="Supplier sterility audit finding")
        get_success_data(api.activate_recall(recall["id"], QM))

        # One ISO expiry: 100 - 15 - 20 - 5 = 60 -> still QUALIFIED.
        advance_clock("2026-12-02T00:00:00Z")
        at_60 = validate_success(api.get_supplier(supplier["id"], CO))
        assert at_60["qualification_score_provisional"] == 60
        assert at_60["status"] == "QUALIFIED"

        # Second ISO expiry: 55 < 60 -> auto-suspended.
        advance_clock("2026-12-16T00:00:00Z")
        at_55 = validate_success(api.get_supplier(supplier["id"], CO))
        assert at_55["qualification_score_provisional"] == 55
        assert at_55["status"] == "SUSPENDED"

        # Required docs still VERIFIED; the score gate blocks reinstatement.
        resp = api.reinstate_supplier(supplier["id"], CO)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_SCORE_BELOW_THRESHOLD)

    def test_document_expiry_equality_then_auto_suspend_cascade(self, api):
        """PRD §2.4: "The document sweep expires any `VERIFIED` supplier
        document whose validity end is now strictly behind the clock (a
        document whose `valid_to` equals the clock remains `VERIFIED`)"
        PRD §3.1: "The platform also suspends automatically when
        required-document coverage lapses — the moment the clock sweep expires
        the last `VERIFIED` `AATB_ACCREDITATION` or `FDA_REGISTRATION` document
        with no replacement of the same type valid on or after the clock"
        PRD §3.8: "It starts from 100, subtracts 20 points per confirmed
        finding and 5 points per expired-document event, and counts nothing
        else: open investigations and active recalls contribute only to the
        provisional figure."

        Design: Corner/calculations/document_expiry_equality_then_auto_suspend_cascade
        """
        supplier = get_success_data(api.create_supplier(
            {"legal_name": "Acme Tissue Source", "license_number": "LIC-001"}, QM))
        doc_a = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(doc_type="AATB_ACCREDITATION",
                                        document_ref="AATB-1"),
                QM,
            )
        )
        get_success_data(api.verify_document(supplier["id"], doc_a["id"], QM))
        doc_f = get_success_data(
            api.create_supplier_document(
                supplier["id"],
                create_document_payload(doc_type="FDA_REGISTRATION",
                                        document_ref="FDA-1",
                                        valid_to="2026-12-31T00:00:00Z"),
                QM,
            )
        )
        get_success_data(api.verify_document(supplier["id"], doc_f["id"], QM))
        get_success_data(api.approve_supplier(supplier["id"], CO))
        freezer = setup_freezer()

        # At clock == valid_to the document remains VERIFIED; supplier QUALIFIED.
        advance_clock("2026-12-31T00:00:00Z")
        docs = get_success_data(
            api.list_supplier_documents(supplier["id"], QM,
                                        params={"doc_type": "FDA_REGISTRATION"})
        )
        assert docs[0]["id"] == doc_f["id"]
        assert docs[0]["status"] == "VERIFIED"
        at_eq = validate_success(api.get_supplier(supplier["id"], CO))
        assert at_eq["status"] == "QUALIFIED"

        # One day past: FDA document EXPIRED, no covering replacement ->
        # auto-suspension cascade; one expired-document event on the final score.
        advance_clock("2027-01-01T00:00:00Z")
        after = validate_success(api.get_supplier(supplier["id"], CO))
        assert after["status"] == "SUSPENDED"
        assert after["qualification_score_final"] == 95

        resp = api.create_shipment(
            {
                "supplier_id": supplier["id"],
                "freezer_id": freezer["id"],
                "items": [make_manifest_item(lot_number="L9", serial_number="U-901",
                                             expiration_at="2027-06-01T00:00:00Z")],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)
