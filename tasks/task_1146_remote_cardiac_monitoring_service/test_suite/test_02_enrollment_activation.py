"""Enrollment reservation protocol, education, activation, and order lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_episode,
    assert_iso_prefix,
    create_enrollment_payload,
    create_order_payload,
    make_physician_headers,
    read_device,
    read_enrollment,
    read_episode,
    read_order,
    register_device,
    register_patient,
    register_physician,
    setup_educated_enrollment,
    setup_monitoring_episode,
    setup_open_order,
    validate_error,
    validate_success,
)

COORD_HEADERS = TEST_USERS["enrollment_coordinator_headers"]


class TestEnrollmentInitialState:
    def test_enrollment_initial_state_and_device_reservation(self, api):
        """PRD §3.2: "The new enrollment begins `INITIATED` with `order_id`
        pointing at its order, `education_completed` false, `attempts_count` 0,
        and `episode_id` null."
        PRD §3.2: "A successful reservation moves the device to `RESERVED`,
        increments the order's `version`, and supersedes any prior non-terminal
        enrollment of the same order: each prior enrollment in `INITIATED`,
        `EDUCATED`, or `ACTIVATION_FAILED` moves to `ABORTED`, and any device
        those enrollments held is released back to `IN_STOCK`."

        Design: Corner/state_machines/enrollment_initial_state_and_defaults
        """
        ctx = setup_open_order(prescribed_days=7)
        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        assert enrollment["status"] == "INITIATED"
        assert enrollment["education_completed"] is False
        assert enrollment["attempts_count"] == 0
        assert enrollment["order_id"] == ctx["order"]["id"]
        assert enrollment.get("episode_id") is None
        device = read_device(ctx["device"]["id"])
        assert device["status"] == "RESERVED", f"device must be RESERVED, got {device['status']}"


class TestActivationGates:
    def test_activate_before_education_rejected(self, api):
        """PRD §3.3: "The enrollment must be `EDUCATED`; activating earlier is
        rejected with `ERR_EDUCATION_INCOMPLETE` (HTTP 422)."

        Design: Corner/state_machines/activate_before_education_rejected
        """
        ctx = setup_open_order(prescribed_days=7)
        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        resp = api.activate_enrollment(
            enrollment["id"], {"baseline_signal_quality": 90}, COORD_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_EDUCATION_INCOMPLETE)
        assert read_enrollment(enrollment["id"])["status"] == "INITIATED"

    def test_activate_second_monitoring_episode_rejected(self, api):
        """PRD §3.3: "At the temporal rung, the patient must not already have
        another episode in clinical status `MONITORING` — one patient, one live
        stream — else the activation is rejected with
        `ERR_ACTIVE_EPISODE_EXISTS` (HTTP 409)."

        Design: Corner/validations/active_episode_exists_conflict
        """
        patient = register_patient()
        physician = register_physician()
        device1 = register_device()
        device2 = register_device()
        order1 = validate_success(
            api.create_order(
                create_order_payload(patient["id"], prescribed_days=7),
                make_physician_headers(physician["id"]),
            ),
            201,
        )
        e1 = validate_success(
            api.create_enrollment(
                order1["id"], create_enrollment_payload(device1["id"], order1["version"]), COORD_HEADERS
            ),
            201,
        )
        validate_success(api.complete_education(e1["id"], {"education_method": "VIDEO"}, COORD_HEADERS))
        validate_success(
            api.activate_enrollment(e1["id"], {"baseline_signal_quality": 90}, COORD_HEADERS)
        )

        order2 = validate_success(
            api.create_order(
                create_order_payload(patient["id"], prescribed_days=7),
                make_physician_headers(physician["id"]),
            ),
            201,
        )
        e2 = validate_success(
            api.create_enrollment(
                order2["id"], create_enrollment_payload(device2["id"], order2["version"]), COORD_HEADERS
            ),
            201,
        )
        validate_success(api.complete_education(e2["id"], {"education_method": "PHONE"}, COORD_HEADERS))
        resp = api.activate_enrollment(e2["id"], {"baseline_signal_quality": 90}, COORD_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_EPISODE_EXISTS)
        assert read_device(device2["id"])["status"] == "RESERVED", (
            "rejected activation must leave the second device RESERVED"
        )


class TestActivationFailureRetryCycle:
    def test_activation_failed_then_retry(self, api):
        """PRD §3.3: "When the baseline reading is below 40, activation fails
        cleanly instead: the device is pulled from service into `REFURBISHING`
        with `refurbishment_due_at` set 48 hours out, the enrollment moves to
        `ACTIVATION_FAILED`, and its `attempts_count` increments by one."
        PRD §3.3: "Recovery is a retry: the coordinator supplies a replacement
        `device_id`, which is vetted by the same stock, refurbishment-buffer,
        and category rules as the original reservation, the new device moves to
        `RESERVED`, and the enrollment returns to `INITIATED` with
        `education_completed` retained — the patient is not re-taught, only
        re-hooked."

        Design: Corner/state_machines/activation_failed_retry_cycle
        """
        ctx = setup_educated_enrollment(
            prescribed_days=7, clock="2026-05-01T09:00:00Z", education_method="IN_PERSON"
        )
        device2 = register_device()
        enrollment_id = ctx["enrollment"]["id"]

        failed = validate_success(
            api.activate_enrollment(enrollment_id, {"baseline_signal_quality": 39}, COORD_HEADERS)
        )
        assert failed["status"] == "ACTIVATION_FAILED"
        assert failed["attempts_count"] == 1
        device1 = read_device(ctx["device"]["id"])
        assert device1["status"] == "REFURBISHING"
        assert_iso_prefix(
            device1["refurbishment_due_at"], "2026-05-03T09:00:00", "refurbishment_due_at"
        )

        retried = validate_success(
            api.retry_enrollment(enrollment_id, {"device_id": device2["id"]}, COORD_HEADERS)
        )
        assert retried["status"] == "INITIATED"
        assert retried["education_completed"] is True, "education is retained across retry"
        assert retried["device_id"] == device2["id"]
        assert read_device(device2["id"])["status"] == "RESERVED"


class TestAbortAndCancel:
    def test_abort_terminal_lockdown_rejected(self, api):
        """PRD §3.2: "Independently, a coordinator may abort any single
        non-terminal enrollment directly, with the same per-enrollment effect:
        `ABORTED`, and its reserved device released."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/abort_terminal_lockdown_rejected
        """
        ctx = setup_open_order(prescribed_days=7)
        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        validate_success(api.abort_enrollment(enrollment["id"], COORD_HEADERS))
        resp = api.abort_enrollment(enrollment["id"], COORD_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_order_cancel_conditional_cascade(self, api):
        """PRD §3.2: "Cancellation cascades: every non-terminal enrollment of
        the order (`INITIATED`, `EDUCATED`, or `ACTIVATION_FAILED`) moves to
        `ABORTED`, their `RESERVED` devices return to `IN_STOCK`, and the
        order's `version` increments."
        PRD §3.2: "an order already `IN_SERVICE` must first run its episode to
        a terminal state, and cancelling one is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_cancel_conditional_cascade
        """
        patient1 = register_patient()
        patient2 = register_patient()
        physician = register_physician()
        dr_headers = make_physician_headers(physician["id"])
        device1 = register_device()
        device2 = register_device()

        order1 = validate_success(
            api.create_order(create_order_payload(patient1["id"], prescribed_days=7), dr_headers), 201
        )
        e1 = validate_success(
            api.create_enrollment(
                order1["id"], create_enrollment_payload(device1["id"], order1["version"]), COORD_HEADERS
            ),
            201,
        )
        validate_success(api.complete_education(e1["id"], {"education_method": "VIDEO"}, COORD_HEADERS))

        order2 = validate_success(
            api.create_order(create_order_payload(patient2["id"], prescribed_days=7), dr_headers), 201
        )
        e2 = validate_success(
            api.create_enrollment(
                order2["id"], create_enrollment_payload(device2["id"], order2["version"]), COORD_HEADERS
            ),
            201,
        )
        validate_success(api.complete_education(e2["id"], {"education_method": "VIDEO"}, COORD_HEADERS))
        validate_success(api.activate_enrollment(e2["id"], {"baseline_signal_quality": 90}, COORD_HEADERS))

        cancelled = validate_success(api.cancel_order(order1["id"], dr_headers))
        assert cancelled["status"] == "CANCELLED"
        assert read_enrollment(e1["id"])["status"] == "ABORTED"
        assert read_device(device1["id"])["status"] == "IN_STOCK"

        resp = api.cancel_order(order2["id"], dr_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReservationValidation:
    def test_device_category_mismatch_rejected(self, api):
        """PRD §3.2: "Finally, at the constraint rung, the device's `model`
        must equal the order's `monitor_type` — Holter with Holter, event with
        event, implantable with implantable — else the create fails with
        `ERR_DEVICE_CATEGORY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/device_category_mismatch_rejected
        """
        patient = register_patient()
        physician = register_physician()
        holter = register_device(model="HOLTER")
        order = validate_success(
            api.create_order(
                create_order_payload(patient["id"], monitor_type="EVENT", prescribed_days=7),
                make_physician_headers(physician["id"]),
            ),
            201,
        )
        resp = api.create_enrollment(
            order["id"],
            create_enrollment_payload(holter["id"], order["version"]),
            COORD_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DEVICE_CATEGORY_MISMATCH)
        assert read_device(holter["id"])["status"] == "IN_STOCK"

    def test_device_not_in_stock_deployed_rejected(self, api):
        """PRD §3.2: "At the state rung, the device must not already be
        committed: a device in `RESERVED`, `DEPLOYED`, `RETURN_IN_TRANSIT`, or
        `LOST` is rejected with `ERR_DEVICE_NOT_IN_STOCK` (HTTP 409), and a
        stale `expected_order_version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/validations/device_not_in_stock_deployed_rejected
        """
        ctx_a = setup_monitoring_episode(prescribed_days=7)
        patient_b = register_patient()
        order_b = validate_success(
            api.create_order(
                create_order_payload(patient_b["id"], prescribed_days=7),
                make_physician_headers(ctx_a["physician"]["id"]),
            ),
            201,
        )
        resp = api.create_enrollment(
            order_b["id"],
            create_enrollment_payload(ctx_a["device"]["id"], order_b["version"]),
            COORD_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_IN_STOCK)


class TestEnrollmentOptimisticConcurrency:
    def test_enrollment_create_stale_order_version_rejected(self, api):
        """PRD §2.6: "If that value does not match the order's current
        `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/enrollment_create_stale_order_version_rejected
        """
        ctx = setup_open_order(prescribed_days=7)
        device2 = register_device()
        first = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        assert first["status"] == "INITIATED"

        resp = api.create_enrollment(
            ctx["order"]["id"],
            create_enrollment_payload(device2["id"], ctx["order"]["version"]),
            COORD_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert read_device(device2["id"])["status"] == "IN_STOCK", (
            "rejected write must not reserve the device"
        )

    def test_enrollment_create_bumps_order_version(self, api):
        """PRD §3.2: "A successful reservation moves the device to `RESERVED`,
        increments the order's `version`, and supersedes any prior non-terminal
        enrollment of the same order: each prior enrollment in `INITIATED`,
        `EDUCATED`, or `ACTIVATION_FAILED` moves to `ABORTED`, and any device
        those enrollments held is released back to `IN_STOCK`."
        PRD §3.2: "A new order is `OPEN` with `version` 1."

        Design: Corner/complexity_layers/enrollment_create_bumps_order_version
        """
        ctx = setup_open_order(prescribed_days=7)
        assert ctx["order"]["version"] == 1
        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        assert enrollment["status"] == "INITIATED"
        order_after = read_order(ctx["order"]["id"])
        assert order_after["version"] == 2, (
            f"order version must increment by exactly 1, got {order_after['version']}"
        )

    def test_enrollment_create_supersedes_prior_nonterminal(self, api):
        """PRD §3.2: "A successful reservation moves the device to `RESERVED`,
        increments the order's `version`, and supersedes any prior non-terminal
        enrollment of the same order: each prior enrollment in `INITIATED`,
        `EDUCATED`, or `ACTIVATION_FAILED` moves to `ABORTED`, and any device
        those enrollments held is released back to `IN_STOCK`."

        Design: Corner/complexity_layers/enrollment_create_supersedes_prior_nonterminal
        """
        ctx = setup_open_order(prescribed_days=7)
        device2 = register_device()
        e1 = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        fresh_order = read_order(ctx["order"]["id"])
        e2 = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(device2["id"], fresh_order["version"]),
                COORD_HEADERS,
            ),
            201,
        )
        assert e2["status"] == "INITIATED"
        assert e2["device_id"] == device2["id"]
        assert read_enrollment(e1["id"])["status"] == "ABORTED"
        assert read_device(ctx["device"]["id"])["status"] == "IN_STOCK"
        assert read_device(device2["id"])["status"] == "RESERVED"


class TestActivationConsistency:
    def test_same_request_side_effect_visibility(self, api):
        """PRD §3.3: "In the same motion the enrollment moves to `ACTIVATED`
        with its `episode_id` populated, the device moves from `RESERVED` to
        `DEPLOYED`, and the order moves from `OPEN` to `IN_SERVICE` (a mutation
        that bumps its `version`)."
        PRD §3.3: "When the baseline reading is at least 40, activation
        succeeds as an atomic bundle: a monitoring episode is created with
        `enrollment_id` naming the activating enrollment, `patient_id`
        denormalized from the order for query isolation, `monitor_type` copied
        from the order, `started_at` set to the logical clock,
        `scheduled_end_at` set to `started_at` plus the order's
        `prescribed_days`, `clinical_status` `MONITORING`, `compliance_status`
        `COMPLIANT`, `strike_count` 0, the derived counters
        `transmission_count`, `unacknowledged_critical_count`, and
        `total_billed_cents` all at 0, and `completed_at` null."

        Design: Corner/consistency_model/same_request_side_effect_visibility
        """
        ctx = setup_educated_enrollment(prescribed_days=7, clock="2026-05-01T08:00:00Z")
        activated = validate_success(
            api.activate_enrollment(
                ctx["enrollment"]["id"], {"baseline_signal_quality": 90}, COORD_HEADERS
            )
        )
        assert activated["status"] == "ACTIVATED"
        assert activated["episode_id"], "activate response must carry the minted episode_id"

        episode = read_episode(activated["episode_id"])
        assert_episode(episode)
        assert_iso_prefix(episode["started_at"], "2026-05-01T08:00:00", "started_at")
        assert_iso_prefix(episode["scheduled_end_at"], "2026-05-08T08:00:00", "scheduled_end_at")
        assert episode["clinical_status"] == "MONITORING"
        assert episode["compliance_status"] == "COMPLIANT"
        assert episode["strike_count"] == 0
        assert read_order(ctx["order"]["id"])["status"] == "IN_SERVICE"

    def test_episode_complete_bubbles_order_fulfilled(self, api):
        """PRD §3.7: "Completion shares the resume precondition — zero `OPEN`
        compliance events, else `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422) — and
        on success stamps `completed_at` from the clock, moves
        `clinical_status` to the named terminal state, and bubbles the parent
        order from `IN_SERVICE` to `FULFILLED`."

        Design: Corner/state_machines/episode_complete_bubbles_order_fulfilled
        """
        ctx = setup_monitoring_episode(prescribed_days=7)
        completed = validate_success(
            api.complete_episode(ctx["episode_id"], {"reason": "TERMINATED_EARLY"}, COORD_HEADERS)
        )
        assert completed["clinical_status"] == "TERMINATED_EARLY"
        assert_iso_prefix(completed["completed_at"], "2026-05-01T00:00:00", "completed_at")
        assert read_order(ctx["order"]["id"])["status"] == "FULFILLED", (
            "episode completion must bubble the order to FULFILLED"
        )
