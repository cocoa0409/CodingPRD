"""Work-order and discrepancy workflow tests: cyclic rework, reopen branch,
transitive cascades, and cross-entity state gates."""
from test_helpers import (
    SM,
    add_checklist_item,
    create_aircraft,
    create_logbook_entry_payload,
    create_mechanic,
    create_owner,
    create_slot,
    create_work_order,
    get_success_data,
    install_part,
    make_mechanic_headers,
    make_owner_headers,
    record_checklist_item,
    request_part,
    reset_clock,
    setup_wo_with_failed_inspection,
    source_and_receive_part,
    start_work_order,
    validate_error,
    validate_success,
    ApiErrorId,
)


class TestDiscrepancyReworkCycle:
    """Queue A: non_linear_state_machine / discrepancy_rectified_open_cycle."""

    def test_failed_verification_reopens_discrepancy(self, api):
        """PRD §3.6: "A failing outcome reopens the discrepancy to `OPEN` and
        begins a rework cycle — the aircraft's posture is recomputed at that
        point and may regress to `RESTRICTED` or `GROUNDED`."

        Design: Difficulty/non_linear_state_machine/discrepancy_rectified_open_cycle
        """
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection()
        mech_h = make_mechanic_headers(mechanic["id"])
        verifier = create_mechanic(certificate_class="IA")
        get_success_data(api.rectify_discrepancy(discrepancy["id"], mech_h))
        # Failed verification reopens the discrepancy to OPEN.
        reopened = validate_success(
            api.verify_discrepancy(
                discrepancy["id"],
                {"outcome": "FAIL", "verified_by_mechanic_id": verifier["id"]},
                make_mechanic_headers(verifier["id"]),
            ),
            200,
        )
        assert reopened["status"] == "OPEN", (
            f"failed verify must reopen to OPEN, got {reopened['status']}"
        )

    def test_reopened_discrepancy_restores_open_count_and_grounding(self, api):
        """PRD §3.6: "A failing outcome reopens the discrepancy to `OPEN` and
        begins a rework cycle — the aircraft's posture is recomputed at that
        point and may regress to `RESTRICTED` or `GROUNDED`."
        PRD §3.7: "The aircraft is `GROUNDED` whenever at least one `AD`
        directive stands `APPLICABLE_OPEN`, or at least one
        `AIRWORTHINESS`-severity discrepancy stands `OPEN`,
        `PENDING_OWNER_DECISION`, `APPROVED`, or `RECTIFIED`."

        Design: Difficulty/non_linear_state_machine/discrepancy_rectified_open_cycle
        """
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection()
        mech_h = make_mechanic_headers(mechanic["id"])
        verifier = create_mechanic(certificate_class="IA")
        get_success_data(api.rectify_discrepancy(discrepancy["id"], mech_h))
        get_success_data(
            api.verify_discrepancy(
                discrepancy["id"],
                {"outcome": "FAIL", "verified_by_mechanic_id": verifier["id"]},
                make_mechanic_headers(verifier["id"]),
            )
        )
        wo_after = get_success_data(api.get_work_order(wo["id"], mech_h))
        assert wo_after["open_discrepancy_count"] == 1, (
            f"reopened discrepancy restores open_discrepancy_count to 1, got {wo_after['open_discrepancy_count']}"
        )
        aircraft_after = get_success_data(api.get_aircraft(aircraft["id"], SM))
        # Auto-created checklist discrepancies are AIRWORTHINESS-severity, so
        # the reopened finding grounds the aircraft.
        assert aircraft_after["airworthiness_posture"] == "GROUNDED", (
            f"reopened AIRWORTHINESS discrepancy must ground the aircraft, got {aircraft_after['airworthiness_posture']}"
        )


class TestOwnerReopenBranch:
    """Queue A: non_linear_state_machine / workorder_awaiting_approval_reopen_branch."""

    def test_owner_reopen_reverts_wo_to_in_progress(self, api):
        """PRD §3.5: "reopening the inspection moves it from
        `AWAITING_OWNER_APPROVAL` to `IN_PROGRESS`, and every
        `PENDING_OWNER_DECISION` discrepancy reverts to `OPEN` for
        re-inspection."

        Design: Difficulty/non_linear_state_machine/workorder_awaiting_approval_reopen_branch
        """
        # Low cap (10000) forces the over-cap discrepancy into
        # PENDING_OWNER_DECISION and the WO into AWAITING_OWNER_APPROVAL.
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
            owner_cap=10000
        )
        wo_before = get_success_data(api.get_work_order(wo["id"], SM))
        assert wo_before["status"] == "AWAITING_OWNER_APPROVAL"
        reverted = validate_success(
            api.reopen_inspection(wo["id"], make_owner_headers(owner["id"])), 200
        )
        assert reverted["status"] == "IN_PROGRESS", (
            f"owner reopen must revert to IN_PROGRESS, got {reverted['status']}"
        )

    def test_owner_reopen_reverts_pending_discrepancies_to_open(self, api):
        """PRD §3.5: "reopening the inspection moves it from
        `AWAITING_OWNER_APPROVAL` to `IN_PROGRESS`, and every
        `PENDING_OWNER_DECISION` discrepancy reverts to `OPEN` for
        re-inspection."

        Design: Difficulty/non_linear_state_machine/workorder_awaiting_approval_reopen_branch
        """
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
            owner_cap=10000
        )
        get_success_data(api.reopen_inspection(wo["id"], make_owner_headers(owner["id"])))
        after = get_success_data(
            api.get_discrepancy(discrepancy["id"], make_mechanic_headers(mechanic["id"]))
        )
        assert after["status"] == "OPEN", (
            f"PENDING_OWNER_DECISION discrepancy must revert to OPEN, got {after['status']}"
        )


class TestAdEvaluationCascade:
    """Queue A: transitive_cascade / ad_evaluation_grounds_aircraft_cascades."""

    def _setup_wo_in_work_in_progress_with_pending_ad(self, api):
        """WO driven to WORK_IN_PROGRESS with all discrepancies VERIFIED, plus
        a registered AD still in PENDING_EVALUATION."""
        from test_helpers import (
            add_checklist_item,
            create_directive_payload,
            rectify_and_verify,
        )
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        verifier = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-AD",
                           starts_at="2026-08-10T08:00:00Z",
                           ends_at="2026-08-10T17:00:00Z",
                           daily_rate_cents=10000)
        wo = create_work_order(aircraft["id"], slot, mechanic["id"])
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        rectify_and_verify(wo["id"], discrepancies[0]["id"], mechanic, verifier)
        get_success_data(api.begin_work(wo["id"], mech_h))
        directive = get_success_data(
            api.create_directive(create_directive_payload(aircraft["id"]), SM)
        )
        return owner, aircraft, mechanic, wo, directive

    def test_applicable_open_ad_grounds_aircraft(self, api):
        """PRD §3.4: "an `AD` found `APPLICABLE_OPEN` grounds the aircraft
        immediately through the posture derivation described in §3.7, while
        service bulletins, being advisory, never ground."

        Design: Difficulty/transitive_cascade/ad_evaluation_grounds_aircraft_cascades
        """
        owner, aircraft, mechanic, wo, directive = (
            self._setup_wo_in_work_in_progress_with_pending_ad(api)
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                make_mechanic_headers(mechanic["id"]),
            )
        )
        aircraft_after = get_success_data(api.get_aircraft(aircraft["id"], SM))
        assert aircraft_after["airworthiness_posture"] == "GROUNDED", (
            f"APPLICABLE_OPEN AD must ground the aircraft, got {aircraft_after['airworthiness_posture']}"
        )

    def test_grounded_aircraft_blocks_ready_for_rts(self, api):
        """PRD §3.7: "every `AD` directive on the aircraft must stand
        `COMPLIED` or `NOT_APPLICABLE`. A failure of this regulatory gate is
        `ERR_AIRWORTHINESS_BLOCKED`, and the aircraft's posture is recomputed
        on success."

        Design: Difficulty/transitive_cascade/ad_evaluation_grounds_aircraft_cascades
        """
        owner, aircraft, mechanic, wo, directive = (
            self._setup_wo_in_work_in_progress_with_pending_ad(api)
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                make_mechanic_headers(mechanic["id"]),
            )
        )
        res = api.ready_for_rts(wo["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_AIRWORTHINESS_BLOCKED)
        wo_after = get_success_data(api.get_work_order(wo["id"], SM))
        assert wo_after["status"] == "WORK_IN_PROGRESS", (
            f"blocked ready-for-rts must leave WO in WORK_IN_PROGRESS, got {wo_after['status']}"
        )


class TestPartInstallRectifyVerifyChain:
    """Queue A: transitive_cascade / part_install_rectify_verify_chain."""

    def _setup_approved_discrepancy_with_received_part(self, api):
        """WO in WORK_IN_PROGRESS with one APPROVED discrepancy and one
        RECEIVED part linked to it."""
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        verifier = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-CHAIN",
                           starts_at="2026-08-10T08:00:00Z",
                           ends_at="2026-08-10T17:00:00Z",
                           daily_rate_cents=10000)
        wo = create_work_order(aircraft["id"], slot, mechanic["id"])
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        discrepancy = discrepancies[0]
        part = request_part(discrepancy["id"], mechanic, part_number="PN-X",
                            condition="NEW", unit_cost_cents=5000, quantity=1)
        source_and_receive_part(part["id"])
        get_success_data(api.begin_work(wo["id"], mech_h))
        return owner, aircraft, mechanic, verifier, wo, discrepancy, part

    def test_install_then_rectify_then_verify_chain(self, api):
        """PRD §3.6: "Installation re-evaluates the parent discrepancy's
        progress: when every part on an approved discrepancy is installed, the
        finding becomes eligible for rectification."
        PRD §3.6: "A passing outcome moves the discrepancy to `VERIFIED`,
        decrementing the work order's `open_discrepancy_count` and incrementing
        its `verified_discrepancy_count`."

        Design: Difficulty/transitive_cascade/part_install_rectify_verify_chain
        """
        owner, aircraft, mechanic, verifier, wo, discrepancy, part = (
            self._setup_approved_discrepancy_with_received_part(api)
        )
        mech_h = make_mechanic_headers(mechanic["id"])
        installed = validate_success(api.install_part(part["id"], mech_h), 200)
        assert installed["status"] == "INSTALLED", (
            f"install must move part to INSTALLED, got {installed['status']}"
        )
        from test_helpers import rectify_and_verify
        verified = rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
        assert verified["status"] == "VERIFIED", (
            f"chain must end VERIFIED, got {verified['status']}"
        )

    def test_verify_cascades_work_order_counts(self, api):
        """PRD §3.6: "A passing outcome moves the discrepancy to `VERIFIED`,
        decrementing the work order's `open_discrepancy_count` and incrementing
        its `verified_discrepancy_count`."

        Design: Difficulty/transitive_cascade/part_install_rectify_verify_chain
        """
        owner, aircraft, mechanic, verifier, wo, discrepancy, part = (
            self._setup_approved_discrepancy_with_received_part(api)
        )
        mech_h = make_mechanic_headers(mechanic["id"])
        get_success_data(api.install_part(part["id"], mech_h))
        from test_helpers import rectify_and_verify
        rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
        wo_after = get_success_data(api.get_work_order(wo["id"], mech_h))
        assert wo_after["open_discrepancy_count"] == 0, (
            f"open count must drop to 0, got {wo_after['open_discrepancy_count']}"
        )
        assert wo_after["verified_discrepancy_count"] == 1, (
            f"verified count must rise to 1, got {wo_after['verified_discrepancy_count']}"
        )


class TestRtsGatedByAircraftPosture:
    """Queue A: cross_entity_state_dependency / workorder_rts_gated_by_aircraft_posture."""

    def _setup_ready_for_rts_then_ground(self, api):
        """WO driven to READY_FOR_RTS with RTS logbook entry, then a pop-up AD
        is evaluated APPLICABLE_OPEN, grounding the aircraft."""
        from test_helpers import create_directive_payload, setup_wo_ready_for_rts
        owner, aircraft, mechanic, verifier, slot, wo = setup_wo_ready_for_rts()
        mech_h = make_mechanic_headers(mechanic["id"])
        get_success_data(
            api.create_logbook_entry(
                create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
                mech_h,
            )
        )
        directive = get_success_data(
            api.create_directive(create_directive_payload(aircraft["id"]), SM)
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                mech_h,
            )
        )
        return owner, aircraft, mechanic, wo

    def test_return_to_service_blocked_by_grounded_posture(self, api):
        """PRD §3.7: "The aircraft's `airworthiness_posture` must stand
        `AIRWORTHY`."
        PRD §3.7: "Taken together, the regulatory airworthiness gate
        `ERR_AIRWORTHINESS_BLOCKED` guards four operations: declaring
        readiness, returning to service, verifying a rectified discrepancy, and
        appending a logbook entry."

        Design: Difficulty/cross_entity_state_dependency/workorder_rts_gated_by_aircraft_posture
        """
        owner, aircraft, mechanic, wo = self._setup_ready_for_rts_then_ground(api)
        res = api.return_to_service(wo["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_AIRWORTHINESS_BLOCKED)

    def test_blocked_rts_leaves_work_order_ready_for_rts(self, api):
        """PRD §3.7: "The aircraft's `airworthiness_posture` must stand
        `AIRWORTHY`."

        Design: Difficulty/cross_entity_state_dependency/workorder_rts_gated_by_aircraft_posture
        """
        owner, aircraft, mechanic, wo = self._setup_ready_for_rts_then_ground(api)
        api.return_to_service(wo["id"], make_mechanic_headers(mechanic["id"]))
        wo_after = get_success_data(api.get_work_order(wo["id"], SM))
        assert wo_after["status"] == "READY_FOR_RTS", (
            f"blocked RTS must leave WO READY_FOR_RTS, got {wo_after['status']}"
        )


class TestPartInstallGatedByDiscrepancyStatus:
    """Queue A: cross_entity_state_dependency / part_install_gated_by_discrepancy_status."""

    def _setup_pending_discrepancy_with_received_part(self, api):
        """WO in AWAITING_OWNER_APPROVAL with one over-cap discrepancy in
        PENDING_OWNER_DECISION and a RECEIVED part linked to it."""
        reset_clock()
        owner = create_owner(approval_cap_cents=10000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-GATE",
                           starts_at="2026-08-10T08:00:00Z",
                           ends_at="2026-08-10T17:00:00Z",
                           daily_rate_cents=10000)
        wo = create_work_order(aircraft["id"], slot, mechanic["id"])
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        discrepancy = discrepancies[0]
        part = request_part(discrepancy["id"], mechanic, part_number="PN-H",
                            condition="NEW", unit_cost_cents=5000, quantity=1)
        source_and_receive_part(part["id"])
        return owner, aircraft, mechanic, wo, discrepancy, part

    def test_install_rejected_when_discrepancy_pending(self, api):
        """PRD §3.6: "a `Mechanic` installs it, moving `RECEIVED` to
        `INSTALLED`, which requires the parent discrepancy to stand `APPROVED`
        and re-checks traceability for `OVERHAUL` and `SERVICEABLE` parts,
        again failing with `ERR_TRACEABILITY_MISSING` when the document
        reference is empty."

        Design: Difficulty/cross_entity_state_dependency/part_install_gated_by_discrepancy_status
        """
        owner, aircraft, mechanic, wo, discrepancy, part = (
            self._setup_pending_discrepancy_with_received_part(api)
        )
        res = api.install_part(part["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_install_leaves_part_received(self, api):
        """PRD §3.6: "a `Mechanic` installs it, moving `RECEIVED` to
        `INSTALLED`, which requires the parent discrepancy to stand `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/part_install_gated_by_discrepancy_status
        """
        owner, aircraft, mechanic, wo, discrepancy, part = (
            self._setup_pending_discrepancy_with_received_part(api)
        )
        api.install_part(part["id"], make_mechanic_headers(mechanic["id"]))
        part_after = get_success_data(api.get_part(part["id"], make_mechanic_headers(mechanic["id"])))
        assert part_after["status"] == "RECEIVED", (
            f"rejected install must leave part RECEIVED, got {part_after['status']}"
        )
