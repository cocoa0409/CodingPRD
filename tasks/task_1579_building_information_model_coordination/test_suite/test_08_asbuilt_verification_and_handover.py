"""As-built verification with its tolerance boundary, and the closeout
handover lifecycle with its aggregate gates and facilities decision loop."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_phase_to,
    approve_takeoff,
    assign_clash,
    create_and_accept_model,
    create_as_built,
    create_handover,
    create_model,
    create_partner,
    create_project,
    create_takeoff,
    get_handover,
    import_clash,
    make_facilities_manager_headers,
    make_takeoff_element,
    make_trade_model_author_headers,
    mark_handover_ready,
    release_fed,
    resolve_clash,
    setup_closeout_project_with_verified_asbuilt,
    setup_released_fed_with_approved_takeoff,
    setup_running_run,
    submit_as_built,
    submit_model,
    transmit_handover,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_as_built,
    verify_clash,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]
FM1 = TEST_USERS["facilities_manager_headers"]  # operator "fm-1"


class TestAsBuiltVerification:
    def test_asbuilt_reject_resubmit_cycle_and_tolerance_boundary(self, api):
        """PRD §3.7: "The supplied `verification_deviation_mm` is compared
        against a tolerance of 25.0 mm: a deviation of at most 25.0 mm —
        exactly 25.0 included — verifies the record into its terminal
        `FIELD_VERIFIED` state, while anything beyond rejects it to
        `REJECTED`. Either way, the measured deviation is recorded on the
        record."
        PRD §3.7: "Submitting moves the as-built from `DRAFT` — or, in the
        field-rework loop, from `REJECTED` — into `SUBMITTED`, with any other
        from-state rejected as `ERR_AS_BUILT_NOT_SUBMITTABLE`"
        PRD §3.7: "Verification is the `VDCManager`'s call and requires
        `SUBMITTED` (`ERR_AS_BUILT_NOT_SUBMITTED`)."

        Design: Corner/state_machines/asbuilt_reject_resubmit_cycle_and_tolerance_boundary
        """
        project = create_project("SM13")
        partner = create_partner(project["id"])
        model = create_and_accept_model(project["id"], partner["id"])
        advance_phase_to(project["id"], "CONSTRUCTION_ADMINISTRATION")
        as_built = create_as_built(project["id"], model["id"], partner["id"],
                                   notes="initial survey")

        # Verify requires SUBMITTED.
        e1 = api.verify_as_built_model(
            as_built["id"], {"verification_deviation_mm": 10.0}, VDC)
        validate_error(e1, ApiErrorId.ERR_AS_BUILT_NOT_SUBMITTED)

        submitted = submit_as_built(as_built["id"], partner["id"])
        assert submitted["status"] == "SUBMITTED"

        # Submit is not idempotent.
        e2 = api.submit_as_built_model(
            as_built["id"], make_trade_model_author_headers(partner["id"]))
        validate_error(e2, ApiErrorId.ERR_AS_BUILT_NOT_SUBMITTABLE)

        # 30.0 > 25.0: rejected, deviation recorded.
        rejected = verify_as_built(as_built["id"], 30.0)
        assert rejected["status"] == "REJECTED"
        assert rejected["verification_deviation_mm"] == pytest.approx(30.0,
                                                                      abs=1e-6)

        # Field-rework loop: REJECTED -> SUBMITTED.
        resubmitted = submit_as_built(as_built["id"], partner["id"])
        assert resubmitted["status"] == "SUBMITTED"

        # Exactly 25.0 verifies (inclusive boundary).
        verified = verify_as_built(as_built["id"], 25.0)
        assert verified["status"] == "FIELD_VERIFIED"
        assert verified["verification_deviation_mm"] == pytest.approx(25.0,
                                                                      abs=1e-6)

    def test_asbuilt_basis_model_not_accepted_rejected(self, api):
        """PRD §3.7: "the basis model must be `ACCEPTED` or `SUPERSEDED`
        (`ERR_MODEL_NOT_ACCEPTED`) in the same project
        (`ERR_CROSS_PROJECT_REFERENCE`)."

        Design: Corner/validations/asbuilt_basis_model_not_accepted_rejected
        """
        project = create_project("V15")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"],
                             life_safety_elements=1, life_safety_compliant=1,
                             envelope_elements=0, envelope_compliant=0,
                             finish_elements=0, finish_compliant=0)
        submit_model(model["id"], partner["id"])  # SUBMITTED, never accepted
        advance_phase_to(project["id"], "CONSTRUCTION_ADMINISTRATION")

        resp = api.create_as_built_model(
            project["id"],
            {"trade_model_id": model["id"],
             "field_verification_notes": "premature"},
            make_trade_model_author_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_MODEL_NOT_ACCEPTED)

        _, meta = validate_paginated(
            api.list_as_built_models(VDC,
                                     params={"project_id": project["id"]}))
        assert meta["total_count"] == 0, "no as-built persisted"


class TestHandoverGates:
    def test_handover_ready_requires_asbuilts_verified(self, api):
        """PRD §3.8: "at least one as-built model must exist in the project
        and every as-built in the project must be `FIELD_VERIFIED`
        (`ERR_AS_BUILTS_NOT_VERIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/handover_ready_requires_asbuilts_verified
        """
        ws = setup_released_fed_with_approved_takeoff("CE2")
        pid = ws["project"]["id"]
        advance_phase_to(pid, "CLOSEOUT")
        as_built = create_as_built(pid, ws["model"]["id"], ws["partner"]["id"],
                                   notes="pour card verified")
        submit_as_built(as_built["id"], ws["partner"]["id"])
        handover = create_handover(pid, ws["takeoff"]["id"], label="H1")

        # The project's only as-built is merely SUBMITTED: mark-ready fails.
        e1 = api.mark_handover_ready(handover["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_AS_BUILTS_NOT_VERIFIED)
        assert get_handover(handover["id"])["status"] == "ASSEMBLING"

        # Verifying the as-built clears the gate; the handover's own fields
        # never changed.
        verify_as_built(as_built["id"], 20.0)
        ready = mark_handover_ready(handover["id"])
        assert ready["status"] == "READY"

    def test_handover_ready_requires_at_least_one_asbuilt(self, api):
        """PRD §3.8: "at least one as-built model must exist in the project
        and every as-built in the project must be `FIELD_VERIFIED`
        (`ERR_AS_BUILTS_NOT_VERIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/handover_ready_requires_asbuilts_verified
        """
        ws = setup_released_fed_with_approved_takeoff("CE2B")
        pid = ws["project"]["id"]
        advance_phase_to(pid, "CLOSEOUT")
        handover = create_handover(pid, ws["takeoff"]["id"], label="H1")

        # Phase CLOSEOUT and takeoff APPROVED gates are satisfied; with zero
        # as-built models the existence half of the as-built gate fails.
        resp = api.mark_handover_ready(handover["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_AS_BUILTS_NOT_VERIFIED)
        assert get_handover(handover["id"])["status"] == "ASSEMBLING"

    def test_handover_markready_aggregate_gates(self, api):
        """PRD §3.8: "it applies four aggregate gates: the project phase must
        be `CLOSEOUT` (`ERR_PHASE_REQUIREMENT_NOT_MET`); the referenced
        takeoff must be `APPROVED` (`ERR_TAKEOFF_NOT_APPROVED`); at least one
        as-built model must exist in the project and every as-built in the
        project must be `FIELD_VERIFIED` (`ERR_AS_BUILTS_NOT_VERIFIED`); and
        no clash anywhere in the project may sit in `NEW`, `ASSIGNED`,
        `RESOLVED`, or `REOPENED` (`ERR_OPEN_CLASHES_REMAIN`)."
        PRD §3.4: "A `BIMCoordinator` opens a **ClashDetectionRun** on a
        `FROZEN` assembly — any other assembly state draws
        `ERR_FED_NOT_FROZEN`"

        Design: Corner/validations/handover_markready_aggregate_gates
        """
        ws = setup_running_run("V16")
        pid = ws["project"]["id"]
        # One open MINOR clash (severity-scoped: only CRITICAL blocks the
        # assembly release gate).
        clash = import_clash(ws["run"]["id"], "G/1", 0.0)
        takeoff = create_takeoff(pid, ws["fed"]["id"], "GROSS",
                                 [make_takeoff_element("E1", 2.0, 0.0)])
        assert takeoff["status"] == "EXTRACTED"
        advance_phase_to(pid, "CLOSEOUT")
        as_built = create_as_built(pid, ws["model"]["id"], ws["partner"]["id"])
        submit_as_built(as_built["id"], ws["partner"]["id"])
        verify_as_built(as_built["id"], 10.0)
        handover = create_handover(pid, takeoff["id"], label="H1")

        # Two aggregate gates fail at once (takeoff not APPROVED, one open
        # clash). The PRD fixes no order between these sibling gates, so
        # either error satisfies the contract.
        e1 = api.mark_handover_ready(handover["id"], COORD)
        validate_error_is_one_of(
            e1, [ApiErrorId.ERR_TAKEOFF_NOT_APPROVED,
                 ApiErrorId.ERR_OPEN_CLASHES_REMAIN])

        # The assembly release gate is severity-scoped: an open MINOR clash
        # does not block it.
        released = release_fed(ws["fed"]["id"])
        assert released["status"] == "RELEASED"

        # Runs require FROZEN, not RELEASED.
        e_run = api.create_clash_run(ws["fed"]["id"], {"tolerance_mm": 5.0},
                                     COORD)
        validate_error(e_run, ApiErrorId.ERR_FED_NOT_FROZEN)

        approve_takeoff(takeoff["id"])

        # Now only the open-clash gate fails.
        e2 = api.mark_handover_ready(handover["id"], COORD)
        validate_error(e2, ApiErrorId.ERR_OPEN_CLASHES_REMAIN)

        # Closing the clash clears the last gate.
        assign_clash(clash["id"], ws["partner"]["id"])
        resolve_clash(clash["id"], ws["partner"]["id"], 1.0)
        verify_clash(clash["id"], 0.0)
        ready = mark_handover_ready(handover["id"])
        assert ready["status"] == "READY"


class TestHandoverLifecycle:
    def test_handover_full_cycle_with_facilities_rejection_loop(self, api):
        """PRD §3.8: "Marking the package ready is allowed from `ASSEMBLING`
        — or, in the facilities-rejection rework loop, from `FM_REJECTED` —
        with any other state rejected as `ERR_HANDOVER_NOT_ASSEMBLING`"
        PRD §3.8: "Transmitting a `READY` package — any other state draws
        `ERR_HANDOVER_NOT_READY` — stamps `transmitted_at` from the logical
        clock and moves it to `TRANSMITTED`."
        PRD §3.8: "responding requires `TRANSMITTED`
        (`ERR_HANDOVER_NOT_TRANSMITTED`), and the supplied `decision` of
        `ACCEPT` lands the package in its terminal `FM_ACCEPTED` state while
        `REJECT` returns it to `FM_REJECTED`, from which the mark-ready
        rework loop begins again; any other decision value is
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/handover_full_cycle_with_facilities_rejection_loop
        """
        ws = setup_closeout_project_with_verified_asbuilt("SM15")
        handover = create_handover(ws["project"]["id"], ws["takeoff"]["id"],
                                   label="H1")
        assert handover["status"] == "ASSEMBLING"

        # Transmit requires READY.
        e1 = api.transmit_handover_package(handover["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_HANDOVER_NOT_READY)

        ready = mark_handover_ready(handover["id"])
        assert ready["status"] == "READY"

        # Respond requires TRANSMITTED; an out-of-range decision value is a
        # request-shape failure regardless.
        e2 = api.respond_handover_package(handover["id"], {"decision": "ACCEPT"},
                                          FM1)
        validate_error(e2, ApiErrorId.ERR_HANDOVER_NOT_TRANSMITTED)
        e2b = api.respond_handover_package(handover["id"], {"decision": "MAYBE"},
                                           FM1)
        validate_error(e2b, ApiErrorId.ERR_INVALID_REQUEST)

        transmitted = transmit_handover(handover["id"])
        assert transmitted["status"] == "TRANSMITTED"
        assert transmitted["transmitted_at"] is not None

        rejected = validate_success(api.respond_handover_package(
            handover["id"], {"decision": "REJECT"}, FM1))
        assert rejected["status"] == "FM_REJECTED"
        assert rejected["fm_decision_by_user_id"] == "fm-1"

        # Facilities-rejection rework loop: FM_REJECTED -> READY -> ...
        ready2 = mark_handover_ready(handover["id"])
        assert ready2["status"] == "READY"
        transmit_handover(handover["id"])
        accepted = validate_success(api.respond_handover_package(
            handover["id"], {"decision": "ACCEPT"},
            make_facilities_manager_headers("fm-2")))
        assert accepted["status"] == "FM_ACCEPTED"
        assert accepted["fm_decision_by_user_id"] == "fm-2"

        # FM_ACCEPTED is terminal: the rework loop is closed.
        e3 = api.mark_handover_ready(handover["id"], COORD)
        validate_error(e3, ApiErrorId.ERR_HANDOVER_NOT_ASSEMBLING)
