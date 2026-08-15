"""Vessel lifecycle, safe-manning compliance, rotation plans, and the OCC
guards on billet revision and plan creation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    activate_vessel,
    api_client,
    confirm_assignment,
    create_activated_mariner,
    create_manning_slot,
    create_rotation_plan,
    create_rotation_plan_payload,
    create_union_hall,
    create_vessel,
    get_vessel,
    make_union_dispatcher_headers,
    propose_assignment,
    set_clock,
    setup_active_vessel_with_slot,
    setup_confirmed_assignment,
    setup_onboard_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]
CAPTAIN = TEST_USERS["port_captain_headers"]


class TestVesselActivation:

    def test_vessel_activate_requires_manning_slot_rejected(self):
        """PRD section 3.6: "Activation moves `REGISTERED` to `ACTIVE` and
        requires at least one `ACTIVE` billet, else `ERR_NO_MANNING_SLOTS`;
        it recomputes posture."

        Design: Corner/state_machines/vessel_activate_requires_manning_slot_rejected
        """
        vessel = create_vessel(vessel_class="OSV")
        resp = api_client.activate_vessel(vessel["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_MANNING_SLOTS)

        create_manning_slot(
            vessel["id"], position_code="MASTER", min_rank_grade=8,
            required_endorsement_code="MASTER_UNL",
            is_critical_position=True, standard_tour_days=120)
        activated = validate_success(api_client.activate_vessel(vessel["id"], ADMIN))
        assert activated["status"] == "ACTIVE"


class TestMarkUnderwayComplianceGate:

    def test_vessel_mark_underway_critical_shortage_rejected(self):
        """PRD section 3.6: "Marking a vessel underway — a `PortCaptain`
        action moving `ACTIVE` to `UNDERWAY` — proceeds freely from
        `COMPLIANT`, proceeds from `DEFICIENT` only when a non-empty
        `waiver_justification` is supplied, and is always rejected from
        `CRITICAL_SHORTAGE` with `ERR_VESSEL_NOT_COMPLIANT`"
        PRD section 3.6: "The vessel's `compliance_posture` is
        `CRITICAL_SHORTAGE` when any `ACTIVE` billet flagged
        `is_critical_position` is uncovered, else `DEFICIENT` when any
        `ACTIVE` billet is uncovered, else `COMPLIANT`."

        Design: Corner/errors/vessel_mark_underway_critical_shortage_rejected
        """
        vessel = create_vessel()
        slot = create_manning_slot(
            vessel["id"], position_code="MASTER", min_rank_grade=8,
            required_endorsement_code="MASTER_UNL",
            is_critical_position=True, standard_tour_days=120)
        activated = validate_success(api_client.activate_vessel(vessel["id"], ADMIN))
        assert activated["compliance_posture"] == "CRITICAL_SHORTAGE", \
            "critical billet uncovered at activation"

        resp = api_client.mark_vessel_underway(
            vessel["id"], {"waiver_justification": "short coastal hop"},
            CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_COMPLIANT)

        snapshot = validate_success(
            api_client.get_manning_compliance(vessel["id"], CAPTAIN))
        assert snapshot["posture"] == "CRITICAL_SHORTAGE"
        assert slot["id"] in snapshot["uncovered_critical_slot_ids"]

    def test_vessel_mark_underway_deficient_requires_waiver(self):
        """PRD section 3.6: "Marking a vessel underway — a `PortCaptain`
        action moving `ACTIVE` to `UNDERWAY` — proceeds freely from
        `COMPLIANT`, proceeds from `DEFICIENT` only when a non-empty
        `waiver_justification` is supplied, and is always rejected from
        `CRITICAL_SHORTAGE` with `ERR_VESSEL_NOT_COMPLIANT`"

        Design: Corner/errors/vessel_mark_underway_deficient_requires_waiver
        """
        vessel = create_vessel()
        critical_slot = create_manning_slot(
            vessel["id"], position_code="AB", is_critical_position=True)
        create_manning_slot(
            vessel["id"], position_code="COOK", rank_track="STEWARD",
            min_rank_grade=1, required_endorsement_code="COOK_CERT",
            is_critical_position=False)
        activate_vessel(vessel["id"])
        create_rotation_plan(vessel["id"])
        # Cover only the critical billet: sign the mariner on.
        mariner = create_activated_mariner()
        assignment = propose_assignment(mariner["id"], critical_slot["id"])
        confirm_assignment(assignment["id"])
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api_client.sign_on_assignment(assignment["id"], CREWING))

        snapshot = validate_success(
            api_client.get_manning_compliance(vessel["id"], CAPTAIN))
        assert snapshot["posture"] == "DEFICIENT", \
            f"critical covered, non-critical COOK open, got {snapshot['posture']}"
        assert snapshot["slots_covered"] == 1
        assert snapshot["slots_total"] == 2

        resp = api_client.mark_vessel_underway(vessel["id"], {}, CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_COMPLIANT)

        underway = validate_success(
            api_client.mark_vessel_underway(
                vessel["id"],
                {"waiver_justification":
                 "cook billet waived for 30 days per flag dispensation"},
                CAPTAIN))
        assert underway["status"] == "UNDERWAY"


class TestRotationPlanLifecycle:

    def test_rotation_plan_supersede_and_archive_cycle(self):
        """PRD section 3.6: "because the new plan is immediately `ACTIVE` and
        supersedes the vessel's prior `ACTIVE` plan — at most one plan per
        vessel is ever `ACTIVE`"
        PRD section 3.6: "A superseded plan can later be moved from
        `SUPERSEDED` to `ARCHIVED` by a `CrewingManager`; plans are listed per
        vessel, filterable by `status`."
        PRD section 2.5: "The target entity must be in the state the
        transition requires, else `ERR_INVALID_STATE` or the
        transition-specific error"

        Design: Corner/state_machines/rotation_plan_supersede_and_archive_cycle
        """
        env = setup_active_vessel_with_slot(with_rotation_plan=False)
        vessel = env["vessel"]
        p1 = create_rotation_plan(vessel["id"])
        assert p1["status"] == "ACTIVE"

        p2 = create_rotation_plan(
            vessel["id"], effective_from="2026-10-01T00:00:00Z",
            effective_to="2027-10-01T00:00:00Z", standard_tour_days=60,
            max_handover_overlap_days=2)
        assert p2["status"] == "ACTIVE"

        plans = validate_success(api_client.list_rotation_plans(vessel["id"], CREWING))
        by_id = {p["id"]: p for p in plans}
        assert by_id[p1["id"]]["status"] == "SUPERSEDED", \
            "creating P2 supersedes the prior ACTIVE plan"

        archived = validate_success(
            api_client.archive_rotation_plan(vessel["id"], p1["id"], CREWING))
        assert archived["status"] == "ARCHIVED"

        resp = api_client.archive_rotation_plan(vessel["id"], p2["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOptimisticConcurrency:

    def test_occ_slot_revision_stale_version(self):
        """PRD section 2.8: "Revising a manning billet requires
        `expected_manning_slot_version`, carrying the client's last observed
        `version` of that ManningSlot. If the slot's current `version` no
        longer matches — because another writer has changed the billet since
        the caller last observed it — the revision is based on a stale
        safe-manning document and is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_slot_revision_stale_version
        """
        vessel = create_vessel()
        slot = create_manning_slot(vessel["id"])
        observed_version = slot["version"]

        first = validate_success(
            api_client.update_manning_slot(
                vessel["id"], slot["id"],
                {"min_rank_grade": 5,
                 "expected_manning_slot_version": observed_version},
                CAPTAIN))
        assert first["version"] == observed_version + 1
        assert first["min_rank_grade"] == 5, "the first revision wins"

        resp = api_client.update_manning_slot(
            vessel["id"], slot["id"],
            {"min_rank_grade": 7,
             "expected_manning_slot_version": observed_version},
            CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        final = validate_success(
            api_client.get_manning_slot(vessel["id"], slot["id"], CAPTAIN))
        assert final["min_rank_grade"] == 5, "the stale write had no effect"
        assert final["version"] == observed_version + 1

    def test_occ_rotation_plan_create_stale_version(self):
        """PRD section 2.8: "Creating a rotation plan for a vessel requires
        `expected_vessel_version`, carrying the client's last observed
        `version` of that Vessel. Because plan creation legitimately
        supersedes the vessel's prior active plan, a mismatch means another
        writer has already created or otherwise changed rotation state since
        the caller last observed the vessel, and the new plan would supersede
        a plan the caller never saw; the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_rotation_plan_create_stale_version
        """
        env = setup_active_vessel_with_slot(with_rotation_plan=False)
        vessel = env["vessel"]
        observed_version = vessel["version"]

        p1 = create_rotation_plan(vessel["id"], vessel_version=observed_version)
        assert p1["status"] == "ACTIVE"

        # The P1 create advanced the vessel version; replaying the same
        # observed version is stale.
        resp = api_client.create_rotation_plan(
            vessel["id"],
            create_rotation_plan_payload(
                observed_version, effective_from="2026-09-01T00:00:00Z",
                effective_to="2027-09-01T00:00:00Z", standard_tour_days=60,
                max_handover_overlap_days=2),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        plans = validate_success(api_client.list_rotation_plans(vessel["id"], CREWING))
        assert len(plans) == 1 and plans[0]["id"] == p1["id"], \
            "no supersede chain may be created by the stale write"
        assert plans[0]["status"] == "ACTIVE"


class TestSlotAndVesselStateGates:

    def test_vessel_not_active_blocks_rotation_plan(self):
        """PRD section 3.6: "A `CrewingManager` creates a plan for a vessel —
        the vessel must be `ACTIVE` or `UNDERWAY`, else
        `ERR_VESSEL_NOT_ACTIVE`"

        Design: Corner/errors/vessel_not_active_blocks_rotation_plan
        """
        vessel = create_vessel()
        create_manning_slot(vessel["id"])
        current = get_vessel(vessel["id"])
        resp = api_client.create_rotation_plan(
            vessel["id"],
            create_rotation_plan_payload(current["version"]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_VESSEL_NOT_ACTIVE)

    def test_slot_not_active_blocks_assignment(self):
        """PRD section 3.7: "the creation-time gate battery rejects: a vessel
        not in `ACTIVE` or `UNDERWAY` (`ERR_VESSEL_NOT_ACTIVE`); a billet not
        in `ACTIVE` status (`ERR_SLOT_NOT_ACTIVE`)"
        PRD section 3.6: "Retiring a billet moves `ACTIVE` to the terminal
        `RETIRED` under the same open-assignment embargo
        (`ERR_SLOT_HAS_OPEN_ASSIGNMENTS`)"

        Design: Corner/errors/slot_not_active_blocks_assignment
        """
        ctx = setup_confirmed_assignment()
        slot = ctx["slot"]
        # Cancel the only open assignment so the billet can be retired.
        validate_success(api_client.cancel_assignment(ctx["assignment"]["id"],
                                                      CREWING))
        retired = validate_success(
            api_client.retire_manning_slot(ctx["vessel"]["id"], slot["id"],
                                           CAPTAIN))
        assert retired["status"] == "RETIRED"

        resp = api_client.create_assignment(
            {
                "mariner_id": ctx["mariner"]["id"],
                "manning_slot_id": slot["id"],
                "assignment_channel": "DIRECT_HIRE",
                "sign_on_date": "2026-08-10T00:00:00Z",
                "planned_relief_date": "2026-11-10T00:00:00Z",
                "local_join": True,
            },
            CREWING)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_ACTIVE)

    def test_slot_retire_blocked_by_open_assignment(self):
        """PRD section 3.6: "Retiring a billet moves `ACTIVE` to the terminal
        `RETIRED` under the same open-assignment embargo
        (`ERR_SLOT_HAS_OPEN_ASSIGNMENTS`) and recomputes the vessel's
        `compliance_posture`, `slots_total`, and `slots_covered`."

        Design: Corner/errors/slot_retire_blocked_by_open_assignment
        """
        ctx = setup_confirmed_assignment()
        resp = api_client.retire_manning_slot(
            ctx["vessel"]["id"], ctx["slot"]["id"], CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_SLOT_HAS_OPEN_ASSIGNMENTS)

        validate_success(api_client.cancel_assignment(ctx["assignment"]["id"],
                                                      CREWING))
        retired = validate_success(
            api_client.retire_manning_slot(ctx["vessel"]["id"],
                                           ctx["slot"]["id"], CAPTAIN))
        assert retired["status"] == "RETIRED"

    def test_active_crew_aboard_blocks_layup_and_terminate(self):
        """PRD section 3.6: "Laying up — `ACTIVE` to `LAID_UP`, again a
        `PortCaptain` action — requires that no assignment on any of the
        vessel's slots be `ONBOARD`, else `ERR_ACTIVE_CREW_ABOARD`"
        PRD section 3.1: "Termination is allowed from `ACTIVE` or `SUSPENDED`
        and is blocked while any assignment of the mariner is `ONBOARD`,
        rejected with `ERR_ACTIVE_CREW_ABOARD`."

        Design: Corner/errors/active_crew_aboard_blocks_layup_and_terminate
        """
        ctx = setup_onboard_assignment()
        resp = api_client.lay_up_vessel(ctx["vessel"]["id"], CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CREW_ABOARD)

        resp = api_client.terminate_mariner(ctx["mariner"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CREW_ABOARD)


class TestSlotCoverageConservation:

    def _setup_handover(self):
        """Vessel with one critical AB slot; M1 ONBOARD [08-10, 11-10);
        M2 CONFIRMED incoming [11-08, 02-08) local join (2-day handover)."""
        ctx = setup_onboard_assignment()
        m2 = create_activated_mariner()
        incoming = propose_assignment(
            m2["id"], ctx["slot"]["id"],
            sign_on_date="2026-11-08T00:00:00Z",
            planned_relief_date="2027-02-08T00:00:00Z", local_join=True,
            relief_of_assignment_id=ctx["assignment"]["id"])
        incoming = confirm_assignment(incoming["id"])
        return {**ctx, "m2": m2, "incoming": incoming,
                "outgoing": ctx["assignment"]}

    def test_coverage_holds_through_handover_overlap(self):
        """PRD section 3.6: "A billet's `current_coverage` is `COVERED`
        exactly when an assignment on that slot is `ONBOARD`, and `UNCOVERED`
        otherwise. `slots_total` counts the vessel's `ACTIVE` billets;
        `slots_covered` counts those that are `COVERED`."

        Design: Difficulty/compensating_invariant/slot_onboard_count_relief_conservation
        """
        ctx = self._setup_handover()
        vessel_id = ctx["vessel"]["id"]

        probe1 = validate_success(api_client.get_manning_compliance(vessel_id,
                                                                    CAPTAIN))
        assert probe1["posture"] == "COMPLIANT"
        assert probe1["slots_covered"] == 1, "one ONBOARD before the handover"

        # Incoming signs on: two assignments ONBOARD on the same billet.
        set_clock("2026-11-08T00:00:00Z")
        validate_success(
            api_client.sign_on_assignment(ctx["incoming"]["id"], CAPTAIN))
        probe2 = validate_success(api_client.get_manning_compliance(vessel_id,
                                                                    CAPTAIN))
        assert probe2["posture"] == "COMPLIANT"
        assert probe2["slots_covered"] == 1, \
            "coverage invariant holds with two ONBOARD during the handover"

    def test_coverage_holds_after_relief_completes_handover(self):
        """PRD section 3.7: "auto-creates a repatriation travel booking under
        the relieved assignment (direction `REPATRIATION`, status `QUOTED`,
        empty `legs`, payer `VESSEL_OWNER`), and leaves the billet `COVERED`
        through the incoming on-board assignment while the vessel's posture is
        recomputed."

        Design: Difficulty/compensating_invariant/slot_onboard_count_relief_conservation
        """
        ctx = self._setup_handover()
        vessel_id = ctx["vessel"]["id"]
        set_clock("2026-11-08T00:00:00Z")
        validate_success(
            api_client.sign_on_assignment(ctx["incoming"]["id"], CAPTAIN))

        relieved = validate_success(
            api_client.relieve_assignment(ctx["outgoing"]["id"], CREWING))
        assert relieved["assignment_status"] == "RELIEVED"

        probe3 = validate_success(api_client.get_manning_compliance(vessel_id,
                                                                    CAPTAIN))
        assert probe3["posture"] == "COMPLIANT"
        assert probe3["slots_covered"] == 1, \
            "steady-state exactly one ONBOARD restored after the relieve"

        incoming = validate_success(
            api_client.get_assignment(ctx["incoming"]["id"], CREWING))
        assert incoming["assignment_status"] == "ONBOARD", \
            "the relief now holds the billet"


class TestNotFoundCatalogSweep:

    def test_not_found_catalog_sweep(self):
        """PRD section 2.5: "Identifiers in the URL are resolved strictly left
        to right; the first identifier that does not correspond to an existing
        resource yields that resource's dedicated 404 — for example, a
        credential action under a non-existent mariner fails with
        `ERR_MARINER_NOT_FOUND` before the credential id is ever examined"

        Design: Corner/errors/not_found_catalog_sweep
        """
        ctx = setup_confirmed_assignment()
        vessel_id = ctx["vessel"]["id"]
        mariner_id = ctx["mariner"]["id"]
        assignment_id = ctx["assignment"]["id"]
        plan_id = ctx["plan"]["id"]
        hall = create_union_hall()

        B = NON_EXISTENT_UUID  # well-formed but non-existent
        checks = [
            (api_client.get_vessel(B, ADMIN),
             ApiErrorId.ERR_VESSEL_NOT_FOUND),
            (api_client.get_credential(B, OFFICER),
             ApiErrorId.ERR_CREDENTIAL_NOT_FOUND),
            (api_client.record_drug_test_result(
                mariner_id, B,
                {"result": "NEGATIVE",
                 "collected_date": "2026-05-01T00:00:00Z"}, OFFICER),
             ApiErrorId.ERR_DRUG_TEST_NOT_FOUND),
            (api_client.get_course(B, ADMIN),
             ApiErrorId.ERR_TRAINING_COURSE_NOT_FOUND),
            (api_client.get_enrollment(B, ADMIN),
             ApiErrorId.ERR_TRAINING_ENROLLMENT_NOT_FOUND),
            (api_client.get_union_hall(B, ADMIN),
             ApiErrorId.ERR_UNION_HALL_NOT_FOUND),
            (api_client.get_assignment(B, CREWING),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api_client.book_travel_booking(assignment_id, B, CREWING),
             ApiErrorId.ERR_TRAVEL_BOOKING_NOT_FOUND),
            (api_client.archive_rotation_plan(vessel_id, B, CREWING),
             ApiErrorId.ERR_ROTATION_PLAN_NOT_FOUND),
            (api_client.update_manning_slot(
                vessel_id, B,
                {"expected_manning_slot_version":
                 get_vessel(vessel_id)["version"]},
                CAPTAIN),
             ApiErrorId.ERR_MANNING_SLOT_NOT_FOUND),
            (api_client.extend_registration_dues(
                hall["id"], B,
                {"new_dues_current_until": "2027-01-01T00:00:00Z"},
                make_union_dispatcher_headers(hall["id"])),
             ApiErrorId.ERR_UNION_REGISTRATION_NOT_FOUND),
            (api_client.submit_sea_service_record(mariner_id, B, OFFICER),
             ApiErrorId.ERR_SEA_SERVICE_RECORD_NOT_FOUND),
            (api_client.suspend_medical_certificate(mariner_id, B, OFFICER),
             ApiErrorId.ERR_MEDICAL_CERTIFICATE_NOT_FOUND),
        ]
        for resp, expected in checks:
            validate_error(resp, expected)
