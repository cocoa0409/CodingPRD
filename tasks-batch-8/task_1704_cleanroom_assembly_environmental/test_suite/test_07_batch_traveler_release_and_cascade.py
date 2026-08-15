"""Assembly batches and travelers: step ordering, performer rules, release
gating with OCC, terminal lockdown, and the CONFIRMED-impact shutdown cascade."""
from test_helpers import (
    QA,
    ApiErrorId,
    add_sampling_point,
    add_traveler,
    approve_investigation,
    assert_batch,
    assert_traveler,
    certify_room,
    close_excursion,
    complete_traveler,
    create_batch,
    create_qualified_personnel,
    create_room,
    get_success_data,
    make_production_operator_headers,
    make_qa_headers,
    open_investigation,
    record_excursion_sample,
    release_batch,
    setup_batch_with_travelers,
    setup_certified_room,
    setup_complete_batch,
    stage_transfer,
    start_traveler,
    validate_error,
    validate_success,
)

RELEASER = "qa-releaser-1"


def _certified_room_with_operator(room_code):
    room = setup_certified_room(
        room_code=room_code, iso_class="ISO_8",
        particle_alert_limit=3500000, particle_action_limit=3520000,
        viable_alert_limit=100, viable_action_limit=200)
    personnel, _qual = create_qualified_personnel(
        room["id"], employee_code=f"EMP-{room_code}", full_name="Batch Operator")
    return room, personnel


class TestTravelerCompletion:
    def test_traveler_complete_by_different_user_rejected(self, api):
        """PRD §3.6: "Completing a step belongs to the same operator who
        started it: the step must stand `IN_PROGRESS`
        (`ERR_TRAVELER_NOT_IN_PROGRESS`), and the completer's `X-User-ID` must
        equal the step's `performed_by_user_id`
        (`ERR_TRAVELER_PERFORMER_MISMATCH`)."

        Design: Corner/state_machines/traveler_complete_by_different_user_rejected
        """
        room, personnel = _certified_room_with_operator("CR-S2")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      batch_number="B-S2")
        start_traveler(travelers[0]["id"], personnel["id"])

        resp = api.complete_traveler(
            travelers[0]["id"], make_production_operator_headers("op-s2b"))
        validate_error(resp, ApiErrorId.ERR_TRAVELER_PERFORMER_MISMATCH)
        traveler = get_success_data(api.get_traveler(travelers[0]["id"], QA))
        assert traveler["status"] == "IN_PROGRESS"
        assert traveler["performed_by_user_id"] == personnel["id"]

    def test_complete_pending_traveler_rejected(self, api):
        """PRD §3.6: "Completing a step belongs to the same operator who
        started it: the step must stand `IN_PROGRESS`
        (`ERR_TRAVELER_NOT_IN_PROGRESS`), and the completer's `X-User-ID` must
        equal the step's `performed_by_user_id`
        (`ERR_TRAVELER_PERFORMER_MISMATCH`)."

        Design: Corner/errors/error_traveler_not_in_progress_on_complete
        """
        room = create_room(room_code="CR-ERB", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        batch = create_batch(room["id"], batch_number="B-ERB",
                             product_code="PWB-ERB")
        traveler = add_traveler(batch["id"], step_sequence=1,
                                step_description="Never started")
        assert traveler["status"] == "PENDING"

        resp = api.complete_traveler(
            traveler["id"], make_production_operator_headers("op-erb"))
        validate_error(resp, ApiErrorId.ERR_TRAVELER_NOT_IN_PROGRESS)


class TestTravelerStepOrder:
    def test_traveler_step_order_enforced(self, api):
        """PRD §3.6: "every sibling step with a lower `step_sequence` must
        already be `COMPLETE` or `VOID`, so steps execute in ascending order
        (`ERR_TRAVELER_STEP_ORDER`)"
        PRD §3.6: "A successful start anchors `performed_by_user_id` to the
        operator's `X-User-ID`, and the batch's first step start automatically
        moves the batch from `OPEN` to `IN_PROGRESS`."

        Design: Corner/state_machines/traveler_step_order_enforced
        """
        room, personnel = _certified_room_with_operator("CR-S3")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      num_steps=2,
                                                      batch_number="B-S3")
        step1, step2 = travelers

        resp = api.start_traveler(
            step2["id"], make_production_operator_headers(personnel["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAVELER_STEP_ORDER)

        start_traveler(step1["id"], personnel["id"])
        complete_traveler(step1["id"], personnel["id"])
        started = validate_success(api.start_traveler(
            step2["id"], make_production_operator_headers(personnel["id"])), 200)
        assert started["status"] == "IN_PROGRESS", (
            "step 2 starts once the lower step is COMPLETE")


class TestBatchRelease:
    def test_batch_release_happy_path_increments_version(self, api):
        """PRD §3.6: "A released batch moves to terminal `RELEASED`, and its
        `version` increments by one."
        PRD §2.9: "Releasing an assembly batch likewise requires the request to
        carry `expected_batch_version` matching the batch's current `version`."

        Design: Corner/state_machines/batch_release_happy_path_and_version_increment
        """
        room, personnel = _certified_room_with_operator("CR-S4")
        batch = setup_complete_batch(room["id"], personnel, batch_number="B-S4")
        assert batch["status"] == "COMPLETE"
        version_before = batch["version"]

        released = release_batch(batch, releaser_id=RELEASER)
        assert_batch(released)
        assert released["status"] == "RELEASED"
        assert released["version"] == version_before + 1, (
            "release increments the batch version by exactly one")

    def test_released_batch_rejects_second_release(self, api):
        """PRD §3.6: "The batch must stand `COMPLETE`
        (`ERR_BATCH_NOT_COMPLETE`), with `ERR_BATCH_TRAVELERS_UNSETTLED`
        guarding the attempt whenever any traveler still stands `PENDING` or
        `IN_PROGRESS`".
        PRD §3.6: "A released batch moves to terminal `RELEASED`, and its
        `version` increments by one."

        Design: Corner/state_machines/release_terminal_state_lockdown
        """
        room, personnel = _certified_room_with_operator("CR-S5")
        batch = setup_complete_batch(room["id"], personnel, batch_number="B-S5")
        release_batch(batch, releaser_id=RELEASER)

        current = get_success_data(api.get_batch(batch["id"], QA))
        assert current["status"] == "RELEASED"
        resp = api.release_batch(
            batch["id"], {"expected_batch_version": current["version"]},
            make_qa_headers(RELEASER))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_COMPLETE)
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == "RELEASED"

    def test_release_with_stale_batch_version_rejected(self, api):
        """PRD §2.9: "Releasing an assembly batch likewise requires the request
        to carry `expected_batch_version` matching the batch's current
        `version`. A mismatch — possible, for example, after a room shutdown
        cascade parked the batch on hold and back, or after a traveler
        completion advanced the batch — is rejected with
        `ERR_STALE_BATCH_VERSION` (HTTP 412)."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation, including mutations caused by
        automatic cascades and derived-field recomputation."

        Design: Corner/cross_cutting/occ_stale_batch_version_on_release
        """
        room, personnel = _certified_room_with_operator("CR-X1")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      num_steps=2,
                                                      batch_number="B-X1")
        step1, step2 = travelers
        start_traveler(step1["id"], personnel["id"])
        complete_traveler(step1["id"], personnel["id"])

        observed = get_success_data(api.get_batch(batch["id"], QA))
        stale_version = observed["version"]

        start_traveler(step2["id"], personnel["id"])
        complete_traveler(step2["id"], personnel["id"])
        batch_now = get_success_data(api.get_batch(batch["id"], QA))
        assert batch_now["status"] == "COMPLETE", (
            "every traveler settled with at least one COMPLETE")
        assert batch_now["version"] > stale_version, (
            "the auto-transition to COMPLETE advanced the batch version")

        resp = api.release_batch(
            batch["id"], {"expected_batch_version": stale_version},
            make_qa_headers(RELEASER))
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == "COMPLETE"

    def test_release_in_progress_batch_rejected_not_complete(self, api):
        """PRD §3.6: "The batch must stand `COMPLETE`
        (`ERR_BATCH_NOT_COMPLETE`), with `ERR_BATCH_TRAVELERS_UNSETTLED`
        guarding the attempt whenever any traveler still stands `PENDING` or
        `IN_PROGRESS`".

        Design: Corner/errors/error_batch_travelers_unsettled_on_early_release
        """
        room, personnel = _certified_room_with_operator("CR-ERA")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      batch_number="B-ERA")
        start_traveler(travelers[0]["id"], personnel["id"])
        current = get_success_data(api.get_batch(batch["id"], QA))
        assert current["status"] == "IN_PROGRESS"

        resp = api.release_batch(
            batch["id"], {"expected_batch_version": current["version"]},
            make_qa_headers(RELEASER))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_COMPLETE)
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == (
            "IN_PROGRESS")

    def test_resume_batch_not_on_hold_rejected(self, api):
        """PRD §3.6: "A batch parked at `ON_HOLD` by the shutdown cascade can
        be resumed by QA once the room is again `IN_CONTROL`: resume requires
        the batch to stand `ON_HOLD` (`ERR_BATCH_NOT_ON_HOLD`) and the room
        posture gate (`ERR_ROOM_NOT_IN_CONTROL`), and it returns the batch to
        `IN_PROGRESS` with `hold_reason` cleared."

        Design: Corner/errors/error_batch_not_on_hold_on_resume
        """
        room = create_room(room_code="CR-ER1", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        batch = create_batch(room["id"], batch_number="B-ER1",
                             product_code="PWB-ER1")
        assert batch["status"] == "OPEN"

        resp = api.resume_batch(batch["id"], QA)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_ON_HOLD)


class TestTravelerVoid:
    def test_void_in_progress_traveler_rejected(self, api):
        """PRD §3.6: "QA may void a step while it is `PENDING`; voiding from
        any other state fails with `ERR_TRAVELER_NOT_VOIDABLE`."

        Design: Corner/errors/error_traveler_not_voidable_when_in_progress
        """
        room, personnel = _certified_room_with_operator("CR-ERC")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      batch_number="B-ERC")
        start_traveler(travelers[0]["id"], personnel["id"])

        resp = api.void_traveler(travelers[0]["id"], QA)
        validate_error(resp, ApiErrorId.ERR_TRAVELER_NOT_VOIDABLE)
        assert get_success_data(api.get_traveler(travelers[0]["id"], QA))["status"] == (
            "IN_PROGRESS")


class TestTravelerStartPostureGate:
    def _room_with_open_alert_and_batch(self, api):
        """Certified room whose posture is raised by an open ALERT excursion,
        with a batch and one PENDING traveler."""
        room = setup_certified_room(room_code="CR-M")
        point = add_sampling_point(room["id"], point_code="SP-M", metric="VIABLE")
        personnel, _qual = create_qualified_personnel(
            room["id"], employee_code="EMP-M", full_name="Em Operator")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      batch_number="B-M")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 75, sampled_at="2026-08-01T11:00:00Z")
        room_now = get_success_data(api.get_room(room["id"], QA))
        assert room_now["environment_posture"] == "ALERT"
        return room, personnel, batch, travelers[0], excursion_id

    def test_traveler_start_blocked_when_room_posture_raised(self, api):
        """PRD §3.6: "Starting a step is the operator's act and is gated four
        ways: the batch must stand `OPEN` or `IN_PROGRESS`
        (`ERR_BATCH_NOT_STARTABLE`); the room's posture must be `IN_CONTROL`
        (`ERR_ROOM_NOT_IN_CONTROL`); every sibling step with a lower
        `step_sequence` must already be `COMPLETE` or `VOID`, so steps execute
        in ascending order (`ERR_TRAVELER_STEP_ORDER`); and the starting
        operator must hold a `QUALIFIED`, unexpired gowning qualification for
        the room (`ERR_GOWNING_NOT_QUALIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/traveler_start_gated_on_room_posture
        """
        room, personnel, batch, traveler, _exc = (
            self._room_with_open_alert_and_batch(api))

        resp = api.start_traveler(
            traveler["id"], make_production_operator_headers(personnel["id"]))
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_IN_CONTROL)
        assert get_success_data(api.get_traveler(traveler["id"], QA))["status"] == (
            "PENDING")
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == "OPEN", (
            "no auto-transition fires when the start is rejected")

    def test_traveler_start_succeeds_after_posture_recovers(self, api):
        """PRD §3.6: "A successful start anchors `performed_by_user_id` to the
        operator's `X-User-ID`, and the batch's first step start automatically
        moves the batch from `OPEN` to `IN_PROGRESS`."
        PRD §2.7: "Closing the last open alert excursion while certification
        stands `CERTIFIED` returns the room from `ALERT` to `IN_CONTROL`".

        Design: Difficulty/cross_entity_state_dependency/traveler_start_gated_on_room_posture
        """
        room, personnel, batch, traveler, excursion_id = (
            self._room_with_open_alert_and_batch(api))

        close_excursion(excursion_id,
                        root_cause="Investigation narrative for CR-M alert",
                        investigator_id="qa-m1", approver_id="qa-m2")
        room_now = get_success_data(api.get_room(room["id"], QA))
        assert room_now["environment_posture"] == "IN_CONTROL"

        started = validate_success(api.start_traveler(
            traveler["id"], make_production_operator_headers(personnel["id"])), 200)
        assert_traveler(started)
        assert started["status"] == "IN_PROGRESS"
        assert started["performed_by_user_id"] == personnel["id"]
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == (
            "IN_PROGRESS")


class TestConfirmedImpactShutdownCascade:
    def _drive_room_to_shutdown(self, api):
        """Certified room -> ACTION excursion -> CONFIRMED approval. Returns
        the context dict with the batch and staged transfer pre-cascade ids."""
        room = setup_certified_room(room_code="CR-G")
        point = add_sampling_point(room["id"], point_code="SP-G", metric="PARTICLE")
        personnel, _qual = create_qualified_personnel(
            room["id"], employee_code="EMP-G", full_name="Gee Operator")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      batch_number="B-G")
        start_traveler(travelers[0]["id"], personnel["id"])
        batch = get_success_data(api.get_batch(batch["id"], QA))
        assert batch["status"] == "IN_PROGRESS"
        transfer = stage_transfer(room["id"], material_lot="LOT-G",
                                  item_description="Housing", dwell_minutes=30,
                                  wiped_down=True)
        _sample, excursion_id = record_excursion_sample(
            point["id"], 400000, sampled_at="2026-08-01T12:00:00Z",
            tech_user_id="tech-g")
        investigation = open_investigation(
            excursion_id,
            root_cause="Confirmed product impact from seal breach",
            product_impact="CONFIRMED", disposition="REJECT",
            investigator_id="qa-g1")
        approve_investigation(investigation["id"], approver_id="qa-g2")
        return {
            "room_id": room["id"], "batch_id": batch["id"],
            "transfer_id": transfer["id"], "excursion_id": excursion_id,
            "investigation_id": investigation["id"],
        }

    def test_confirmed_impact_approval_shuts_down_room_and_closes_excursion(
            self, api):
        """PRD §3.4: "Approval moves the investigation to terminal `APPROVED`
        and the parent excursion from `UNDER_INVESTIGATION` to `CLOSED`, then
        recomputes the room posture."
        PRD §3.4: "When the approved `product_impact` is `CONFIRMED`, the room
        enters `SHUTDOWN` and the cascade fires atomically within the same
        request".

        Design: Difficulty/transitive_cascade/confirmed_excursion_cascades_to_shutdown_holds_and_transfer_rejection
        """
        ctx = self._drive_room_to_shutdown(api)
        investigation = get_success_data(
            api.get_investigation(ctx["investigation_id"], QA))
        assert investigation["status"] == "APPROVED"
        excursion = get_success_data(api.get_excursion(ctx["excursion_id"], QA))
        assert excursion["status"] == "CLOSED"
        room = get_success_data(api.get_room(ctx["room_id"], QA))
        assert room["environment_posture"] == "SHUTDOWN"

    def test_confirmed_impact_cascade_holds_batches_and_rejects_transfers(
            self, api):
        """PRD §3.4: "When the approved `product_impact` is `CONFIRMED`, the
        room enters `SHUTDOWN` and the cascade fires atomically within the same
        request: every assembly batch of the room standing `OPEN` or
        `IN_PROGRESS` moves to `ON_HOLD` with `hold_reason` set to
        `EXCURSION_PRODUCT_IMPACT`, and every material transfer of the room
        still `STAGED` moves to `REJECTED`."

        Design: Difficulty/transitive_cascade/confirmed_excursion_cascades_to_shutdown_holds_and_transfer_rejection
        """
        ctx = self._drive_room_to_shutdown(api)
        batch = get_success_data(api.get_batch(ctx["batch_id"], QA))
        assert batch["status"] == "ON_HOLD"
        assert batch["hold_reason"] == "EXCURSION_PRODUCT_IMPACT"
        transfer = get_success_data(
            api.get_material_transfer(ctx["transfer_id"], QA))
        assert transfer["status"] == "REJECTED"

    def test_traveler_start_rejected_while_batch_on_hold(self, api):
        """PRD §3.6: "Starting a step is the operator's act and is gated four
        ways: the batch must stand `OPEN` or `IN_PROGRESS`
        (`ERR_BATCH_NOT_STARTABLE`); the room's posture must be `IN_CONTROL`
        (`ERR_ROOM_NOT_IN_CONTROL`); every sibling step with a lower
        `step_sequence` must already be `COMPLETE` or `VOID`, so steps execute
        in ascending order (`ERR_TRAVELER_STEP_ORDER`); and the starting
        operator must hold a `QUALIFIED`, unexpired gowning qualification for
        the room (`ERR_GOWNING_NOT_QUALIFIED`)."
        PRD §2.7: "Recovery from `SHUTDOWN` requires both halves together: zero
        excursions of the room in `OPEN` or `UNDER_INVESTIGATION`, and a fresh
        passing certification recorded after the confirmed-impact approval."
        PRD §3.6: "A batch parked at `ON_HOLD` by the shutdown cascade can be
        resumed by QA once the room is again `IN_CONTROL`: resume requires the
        batch to stand `ON_HOLD` (`ERR_BATCH_NOT_ON_HOLD`) and the room posture
        gate (`ERR_ROOM_NOT_IN_CONTROL`), and it returns the batch to
        `IN_PROGRESS` with `hold_reason` cleared."

        Design: Corner/errors/error_batch_not_startable_when_on_hold
        """
        room = setup_certified_room(room_code="CR-ERG")
        point = add_sampling_point(room["id"], point_code="SP-ERG", metric="PARTICLE")
        personnel, _qual = create_qualified_personnel(
            room["id"], employee_code="EMP-ERG", full_name="Erg Op")
        batch, travelers = setup_batch_with_travelers(room["id"], personnel,
                                                      num_steps=2,
                                                      batch_number="B-ERG")
        start_traveler(travelers[0]["id"], personnel["id"])
        _sample, excursion_id = record_excursion_sample(
            point["id"], 400000, sampled_at="2026-08-01T12:00:00Z",
            tech_user_id="tech-erg")
        investigation = open_investigation(
            excursion_id, root_cause="Confirmed impact for ERG cascade",
            product_impact="CONFIRMED", disposition="REWORK",
            investigator_id="qa-erg1")
        approve_investigation(investigation["id"], approver_id="qa-erg2")
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == "ON_HOLD"

        # Fresh PASS recorded after the confirmed-impact approval with zero
        # open excursions: the room recovers to IN_CONTROL.
        certify_room(room["id"], executed_at="2026-08-01T18:00:00Z",
                     location_mean_values=[10, 20])
        room_now = get_success_data(api.get_room(room["id"], QA))
        assert room_now["environment_posture"] == "IN_CONTROL"
        assert get_success_data(api.get_batch(batch["id"], QA))["status"] == (
            "ON_HOLD"), "the hold survives recertification; resume is explicit"

        resp = api.start_traveler(
            travelers[1]["id"], make_production_operator_headers(personnel["id"]))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_STARTABLE)
