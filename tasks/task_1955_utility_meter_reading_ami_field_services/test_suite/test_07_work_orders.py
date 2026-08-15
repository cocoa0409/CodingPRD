"""Field work orders: lifecycle, completion cascades, OCC, dispatch conflicts.

Covers PRD section 3.7 plus the enrollment/campaign cascade links of
section 3.8.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_route_payload,
    create_field_technician_payload,
    create_meter,
    create_route_payload,
    create_work_order_payload,
    dispatch_order_to,
    dispatch_work_order_payload,
    enroll_payload,
    generate_estimate_for_stop,
    get_account,
    get_campaign,
    get_enrollment,
    get_investigation,
    get_meter,
    get_route_stops,
    get_stop,
    get_work_order,
    ingest_ami_read,
    make_field_technician_headers,
    make_investigator_headers,
    mark_stop_no_read_as,
    open_investigation,
    reassign_route_payload,
    reschedule_work_order_payload,
    rework_payload,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_ami_account_with_history,
    setup_failed_meter_in_open_campaign,
    setup_in_progress_route,
    setup_no_read_pending_stop,
    start_order_as,
    validate_error,
    validate_paginated,
    validate_success,
    advance_investigation_to_pending_disposition,
    create_billing_period,
    create_route,
    open_period_window,
    get_route,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]


def _exchange_order_in_progress(api, account_number="C-0034", cycle_code="C34"):
    """Account with installed meter m1 plus spare m2; EXCHANGE order for m1
    dispatched and started. Returns (account, m1, m2, wo, tech)."""
    set_logical_clock("2026-08-01T00:00:00Z")
    tech = validate_success(
        api.create_field_technician(
            create_field_technician_payload(display_name="Rework Tech"), ADMIN
        ),
        201,
    )
    account, m1 = setup_account_with_installed_meter(
        account_number, cycle_code, service_address="34 Rework Rd"
    )
    m2 = create_meter(f"{account_number}-SPARE", "HANDHELD")
    wo = validate_success(
        api.create_work_order(
            create_work_order_payload(
                "EXCHANGE",
                account["id"],
                meter_id=m1["id"],
                scheduled_date="2026-08-10",
                work_shift="AM",
            ),
            DISPATCHER,
        ),
        201,
    )
    dispatch_order_to(wo["id"], tech["id"])
    start_order_as(wo["id"], tech["id"])
    return account, m1, m2, wo, tech


class TestWorkOrderLifecycle:
    def test_work_order_rework_cycle_returns_to_dispatched(self, api):
        """PRD section 3.7: "After completion, quality control takes over. A
        `MeterOpsAdmin` verifies a `COMPLETED` order, moving it to the
        terminal `VERIFIED` state; alternatively they may request rework with
        a `rework_reason`, moving it to `REWORK`, from which it can be
        dispatched again. One caveat governs rework of an exchange: the meter
        swap effects persist through rework — rework re-dispatches field
        verification only, and undoing a swap requires a second `EXCHANGE`
        order."
        PRD section 2.5: "`version` (integer): a system-managed integer that
        increments with every modification to the resource, including
        modifications applied automatically by the system cascades described
        throughout this document."

        Design: Corner/state_machines/work_order_rework_cycle_returns_to_dispatched
        """
        _account, m1, m2, wo, tech = _exchange_order_in_progress(api)
        completed = validate_success(
            api.complete_work_order(
                wo["id"],
                {
                    "new_meter_id": m2["id"],
                    "old_final_read_value": 999,
                    "new_initial_read_value": 0,
                },
                make_field_technician_headers(tech["id"]),
            ),
            200,
        )
        assert completed["work_order_status"] == "COMPLETED"

        validate_success(
            api.request_work_order_rework(wo["id"], rework_payload("SEAL_MISSING"), ADMIN), 200
        )
        redispatched = dispatch_order_to(wo["id"], tech["id"])
        assert redispatched["work_order_status"] == "DISPATCHED"
        # create v1, dispatch v2, start v3, complete v4, rework v5, dispatch v6
        assert redispatched["version"] == 6

        # swap effects persist through rework
        assert get_meter(m1["id"])["meter_status"] == "REMOVED"
        assert get_meter(m2["id"])["meter_status"] == "IN_SERVICE"

    def test_work_order_verified_terminal_lockdown(self, api, dispatcher_headers):
        """PRD section 3.7: "A `MeterOpsAdmin` verifies a `COMPLETED` order,
        moving it to the terminal `VERIFIED` state"
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/work_order_verified_terminal_lockdown
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Verify Tech"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "C-0035", "C35", meter_type="AMI", service_address="35 Verify Rd"
        )
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "ENDPOINT_SWAP",
                    account["id"],
                    meter_id=m1["id"],
                    scheduled_date="2026-08-10",
                    work_shift="PM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        dispatch_order_to(wo["id"], tech["id"])
        start_order_as(wo["id"], tech["id"])
        validate_success(
            api.complete_work_order(wo["id"], {}, make_field_technician_headers(tech["id"])),
            200,
        )
        verified = validate_success(api.verify_work_order(wo["id"], ADMIN), 200)
        assert verified["work_order_status"] == "VERIFIED"

        res_cancel = api.cancel_work_order(wo["id"], dispatcher_headers)
        validate_error(res_cancel, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        res_rework = api.request_work_order_rework(wo["id"], rework_payload("TOO_LATE"), ADMIN)
        validate_error(res_rework, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert get_work_order(wo["id"])["work_order_status"] == "VERIFIED"

    def test_occ_work_order_reschedule_stale_version(self, api, dispatcher_headers):
        """PRD section 2.7: "Rescheduling a work order
        (`POST /work-orders/{id}/reschedule`) requires
        `expected_work_order_version` matching the work order's current
        `version`. Reschedule supersedes the prior schedule from `OPEN` or
        `DISPATCHED` without a state change, so a stale-version reschedule
        would otherwise silently overwrite a newer schedule."
        PRD section 2.7: "if another writer has advanced the resource's
        `version` since the client last read it, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting
        a state it has not observed."

        Design: Corner/complexity_layers/occ_work_order_reschedule_stale_version
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, m1 = setup_account_with_installed_meter(
            "C-0131", "CE3", service_address="131 Occ Rd"
        )
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE",
                    account["id"],
                    meter_id=m1["id"],
                    scheduled_date="2026-08-10",
                    work_shift="AM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        original_version = wo["version"]

        rescheduled = validate_success(
            api.reschedule_work_order(
                wo["id"],
                reschedule_work_order_payload("2026-08-12", "PM", original_version),
                dispatcher_headers,
            ),
            200,
        )
        assert rescheduled["scheduled_date"] == "2026-08-12"
        assert rescheduled["work_shift"] == "PM"
        assert rescheduled["work_order_status"] == "OPEN"
        assert rescheduled["version"] == original_version + 1

        stale = api.reschedule_work_order(
            wo["id"],
            reschedule_work_order_payload("2026-08-13", "AM", original_version),
            dispatcher_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert get_work_order(wo["id"])["scheduled_date"] == "2026-08-12"


class TestWorkOrderCreationGates:
    def test_work_order_create_on_suspended_account_rejected(self, api, dispatcher_headers):
        """PRD section 3.7: "Two cross-cutting gates also apply: the account
        must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the
        evidence-preservation hold of §3.6 blocks `EXCHANGE` and
        `ENDPOINT_SWAP` creation for a suspected meter
        (`ERR_EVIDENCE_PRESERVATION_HOLD`)."

        Design: Corner/validations/work_order_create_on_suspended_account_rejected
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0090", "C90", service_address="90 Susp Rd"
        )
        validate_success(api.suspend_service_account(account["id"], ADMIN), 200)

        res = api.create_work_order(
            create_work_order_payload(
                "EXCHANGE",
                account["id"],
                meter_id=m1["id"],
                scheduled_date="2026-08-10",
                work_shift="AM",
            ),
            dispatcher_headers,
        )
        validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, 409)

    def test_work_order_create_exchange_blocked_by_evidence_hold(self, api, dispatcher_headers):
        """PRD section 3.6: "While any investigation for the meter remains
        non-terminal, new `EXCHANGE` or `ENDPOINT_SWAP` work orders for that
        meter — and any attempt to enroll the meter in a replacement campaign
        — are rejected with `ERR_EVIDENCE_PRESERVATION_HOLD` (HTTP 409),
        preserving the physical evidence."
        PRD section 3.6: "Clearing the investigation moves it from
        `PENDING_DISPOSITION` to `CLEARED` and returns the meter's
        `tamper_status` from `SUSPECTED` to `NONE`, lifting the
        evidence-preservation hold."

        Design: Corner/validations/work_order_create_exchange_blocked_by_evidence_hold
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0100", "CB1", service_address="100 Hold Rd"
        )
        inv = open_investigation(account["id"], m1["id"], opened_by="inv-701")
        assert get_meter(m1["id"])["tamper_status"] == "SUSPECTED"

        res = api.create_work_order(
            create_work_order_payload(
                "EXCHANGE",
                account["id"],
                meter_id=m1["id"],
                scheduled_date="2026-08-10",
                work_shift="AM",
            ),
            dispatcher_headers,
        )
        validate_error(res, ApiErrorId.ERR_EVIDENCE_PRESERVATION_HOLD.value, 409)

        # Resolve the investigation: the hold lifts.
        advance_investigation_to_pending_disposition(inv["id"], "inv-701")
        validate_success(
            api.clear_investigation(inv["id"], make_investigator_headers("inv-701")), 200
        )
        assert get_meter(m1["id"])["tamper_status"] == "NONE"

        created = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE",
                    account["id"],
                    meter_id=m1["id"],
                    scheduled_date="2026-08-10",
                    work_shift="AM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        assert created["work_order_status"] == "OPEN"


class TestExchangeCompletionGates:
    def test_exchange_new_meter_same_as_old_rejected(self, api):
        """PRD section 3.7: "The new meter must be `IN_STOCK` and different
        from the meter being removed (`ERR_METER_NOT_AVAILABLE_FOR_INSTALL`,
        HTTP 409), and `old_final_read_value` must clear the rollback rule
        (`ERR_READ_ROLLBACK`)."

        Design: Corner/validations/exchange_new_meter_same_as_old_rejected
        """
        _account, m1, _m2, wo, tech = _exchange_order_in_progress(
            api, account_number="C-0074", cycle_code="C74"
        )
        res = api.complete_work_order(
            wo["id"],
            {
                "new_meter_id": m1["id"],
                "old_final_read_value": 10,
                "new_initial_read_value": 10,
            },
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_METER_NOT_AVAILABLE_FOR_INSTALL.value, 409)
        assert get_meter(m1["id"])["meter_status"] == "IN_SERVICE"
        assert get_work_order(wo["id"])["work_order_status"] == "IN_PROGRESS"

    def test_exchange_final_read_rollback_rejected(self, api):
        """PRD section 2.9: "Meter registers move in one direction. Every
        `read_value`, `old_final_read_value`, and `reread_value` is a
        non-negative integer number of kWh, and any value presented below the
        account's `last_validated_read_value` (when that field is set) is
        rejected with `ERR_READ_ROLLBACK` (HTTP 422). This rollback screen
        applies uniformly to field read capture, AMI head-end ingestion,
        re-read completion, and meter-exchange completion."

        Design: Corner/calculations/exchange_final_read_rollback_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="RB Tech"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "C-0066", "C61", meter_type="AMI", service_address="66 Rollback Ave"
        )
        m2 = create_meter("SN-RB-2", "AMI")
        ingest_ami_read(m1["id"], 10000, "2026-08-02T10:00:00Z")

        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE",
                    account["id"],
                    meter_id=m1["id"],
                    scheduled_date="2026-08-10",
                    work_shift="AM",
                ),
                DISPATCHER,
            ),
            201,
        )
        dispatch_order_to(wo["id"], tech["id"])
        start_order_as(wo["id"], tech["id"])

        res = api.complete_work_order(
            wo["id"],
            {
                "new_meter_id": m2["id"],
                "old_final_read_value": 9999,
                "new_initial_read_value": 0,
            },
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_READ_ROLLBACK.value, 422)
        assert get_meter(m1["id"])["meter_status"] == "IN_SERVICE"
        assert get_meter(m2["id"])["meter_status"] == "IN_STOCK"
        assert get_work_order(wo["id"])["work_order_status"] == "IN_PROGRESS"


class TestTypedCompletions:
    def test_tamper_check_complete_requires_evidence_gathering(self, api):
        """PRD section 3.7: "Completing a `TAMPER_CHECK` order requires
        `evidence_note`. The linked investigation must be in
        `EVIDENCE_GATHERING` (`ERR_INVALID_STATE_TRANSITION` otherwise), and
        completion appends the note to the investigation's `evidence_notes`."

        Design: Corner/validations/tamper_check_complete_requires_evidence_gathering
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="TC Tech"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "C-0103", "CB4", service_address="103 TC Rd"
        )
        inv = open_investigation(account["id"], m1["id"], opened_by="inv-111")
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "TAMPER_CHECK",
                    account["id"],
                    meter_id=m1["id"],
                    investigation_id=inv["id"],
                    scheduled_date="2026-08-10",
                    work_shift="PM",
                ),
                DISPATCHER,
            ),
            201,
        )
        dispatch_order_to(wo["id"], tech["id"])
        start_order_as(wo["id"], tech["id"])

        # Investigation still OPEN: completion is cross-gated on it.
        res = api.complete_work_order(
            wo["id"], {"evidence_note": "seal intact"}, make_field_technician_headers(tech["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        validate_success(
            api.begin_evidence(inv["id"], make_investigator_headers("inv-111")), 200
        )
        completed = validate_success(
            api.complete_work_order(
                wo["id"],
                {"evidence_note": "seal intact"},
                make_field_technician_headers(tech["id"]),
            ),
            200,
        )
        assert completed["work_order_status"] == "COMPLETED"
        assert "seal intact" in get_investigation(inv["id"])["evidence_notes"]

    def test_reread_complete_rejected_after_stop_already_estimated(self, api):
        """PRD section 3.7: "Completing a `RE_READ` order requires
        `reread_value` and `reread_at`. The linked stop must be
        `NO_READ_PENDING` (`ERR_STOP_NOT_ACTIONABLE`), and `reread_value` must
        clear the rollback rule against the account's
        `last_validated_read_value` (`ERR_READ_ROLLBACK`)."

        Design: Corner/validations/reread_complete_rejected_after_stop_already_estimated
        """
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter, period, route, stop, tech = setup_no_read_pending_stop(
            "C-0104",
            "CB5",
            [(9700, "2026-06-01T10:00:00Z"), (10000, "2026-07-01T10:00:00Z")],
            window_open="2026-07-22",
            window_close="2026-07-28",
            period_start="2026-07-01",
            period_end="2026-07-31",
            bill_run_date="2026-07-31",
            scheduled_date="2026-07-22",
            open_clock="2026-07-22T08:00:00Z",
            degraded_snapshots=["2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"],
        )
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "RE_READ",
                    account["id"],
                    route_stop_id=stop["id"],
                    scheduled_date="2026-07-23",
                    work_shift="AM",
                ),
                DISPATCHER,
            ),
            201,
        )
        dispatch_order_to(wo["id"], tech["id"])
        start_order_as(wo["id"], tech["id"])

        # The billing side resolves the stop before the technician reports back.
        generate_estimate_for_stop(stop["id"])
        assert get_stop(stop["id"])["stop_status"] == "ESTIMATED"

        res = api.complete_work_order(
            wo["id"],
            {"reread_value": 10050, "reread_at": "2026-07-23T09:00:00Z"},
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STOP_NOT_ACTIONABLE.value, 409)
        assert get_stop(stop["id"])["stop_status"] == "ESTIMATED"


class TestWorkOrderListing:
    def test_work_order_filtered_list_by_technician_and_status(self, api, dispatcher_headers):
        """PRD section 3.7: "the work-order list filters by
        `service_account_id`, `meter_id`, `technician_id`, `route_stop_id`,
        `investigation_id`, `campaign_enrollment_id`, `new_meter_id`,
        `work_order_status`, or `work_order_type`."

        Design: Corner/endpoints/work_order_filtered_list_by_technician_and_status
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        t1 = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Filter T1"), ADMIN
            ),
            201,
        )
        t2 = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Filter T2"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "C-0110", "CC1", service_address="110 Filter Rd"
        )
        wo_1 = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE", account["id"], meter_id=m1["id"],
                    scheduled_date="2026-08-10", work_shift="AM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        wo_2 = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "ENDPOINT_SWAP", account["id"], meter_id=m1["id"],
                    scheduled_date="2026-08-11", work_shift="AM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        wo_3 = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "ENDPOINT_SWAP", account["id"], meter_id=m1["id"],
                    scheduled_date="2026-08-10", work_shift="PM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        dispatch_order_to(wo_1["id"], t1["id"])
        dispatch_order_to(wo_2["id"], t1["id"])
        validate_success(api.cancel_work_order(wo_2["id"], dispatcher_headers), 200)
        dispatch_order_to(wo_3["id"], t2["id"])

        data, meta = validate_paginated(
            api.list_work_orders(
                dispatcher_headers,
                params={"technician_id": t1["id"], "work_order_status": "DISPATCHED"},
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == wo_1["id"]

        data, meta = validate_paginated(
            api.list_work_orders(dispatcher_headers, params={"technician_id": t1["id"]})
        )
        assert meta["total_count"] == 2
        assert {w["id"] for w in data} == {wo_1["id"], wo_2["id"]}


class TestDispatchCancelConservation:
    def _dispatched_order_and_full_route(self, api):
        """Technician with a dispatched AM order on 2026-08-10 and an
        unassigned FULL route the same day. Returns (tech, account, meter, wo, route)."""
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Tech Twelve"), ADMIN
            ),
            201,
        )
        account, meter = setup_account_with_installed_meter(
            "A-9201", "C21", service_address="71 Poplar St"
        )
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE", account["id"], meter_id=meter["id"],
                    scheduled_date="2026-08-10", work_shift="AM",
                ),
                DISPATCHER,
            ),
            201,
        )
        period = create_billing_period(
            "C21", "2026-08-01", "2026-08-31", "2026-08-10", "2026-08-14", "2026-08-31"
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-10", route_shift="FULL"),
                DISPATCHER,
            ),
            201,
        )
        return tech, account, meter, wo, route

    def test_dispatched_order_blocks_full_shift_route(self, api):
        """PRD section 2.8: "One technician cannot hold two commitments on the
        same date whose shift intervals overlap — an `AM` commitment and a
        `PM` commitment on the same date are adjacent, not overlapping, and
        are allowed. Violations surface as `ERR_TECHNICIAN_WINDOW_CONFLICT`
        (HTTP 409) at route assignment and reassignment and at work-order
        dispatch and reschedule."

        Design: Difficulty/compensating_invariant/dispatch_cancel_conserves_technician_commitment_slot
        """
        tech, _account, _meter, wo, route = self._dispatched_order_and_full_route(api)
        dispatch_order_to(wo["id"], tech["id"])

        res = api.assign_route(route["id"], assign_route_payload(tech["id"]), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_TECHNICIAN_WINDOW_CONFLICT.value, 409)
        assert get_route(route["id"])["route_status"] == "DRAFT"

    def test_cancel_restores_technician_commitment_slot(self, api):
        """PRD section 3.7: "Cancelling is available from `OPEN`,
        `DISPATCHED`, or `REWORK` and lands the order in the terminal
        `CANCELLED` state."
        PRD section 2.8: "One technician cannot hold two commitments on the
        same date whose shift intervals overlap — an `AM` commitment and a
        `PM` commitment on the same date are adjacent, not overlapping, and
        are allowed. Violations surface as `ERR_TECHNICIAN_WINDOW_CONFLICT`
        (HTTP 409) at route assignment and reassignment and at work-order
        dispatch and reschedule."

        Design: Difficulty/compensating_invariant/dispatch_cancel_conserves_technician_commitment_slot
        """
        tech, _account, _meter, wo, route = self._dispatched_order_and_full_route(api)
        dispatch_order_to(wo["id"], tech["id"])
        validate_error(
            api.assign_route(route["id"], assign_route_payload(tech["id"]), DISPATCHER),
            ApiErrorId.ERR_TECHNICIAN_WINDOW_CONFLICT.value,
            409,
        )

        cancelled = validate_success(api.cancel_work_order(wo["id"], DISPATCHER), 200)
        assert cancelled["work_order_status"] == "CANCELLED"

        assigned = validate_success(
            api.assign_route(route["id"], assign_route_payload(tech["id"]), DISPATCHER), 200
        )
        assert assigned["route_status"] == "ASSIGNED"
        assert assigned["technician_id"] == tech["id"]

        _data, meta = validate_paginated(
            api.list_work_orders(
                DISPATCHER,
                params={"technician_id": tech["id"], "work_order_status": "DISPATCHED"},
            )
        )
        assert meta["total_count"] == 0


class TestExchangeCascade:
    def _exchange_cascade_scenario(self, api):
        """FAILED AMI meter enrolled in an OPEN single-enrollment campaign;
        EXCHANGE order for the meter IN_PROGRESS. Completes the exchange.
        Returns (account, m1, m2, campaign, enrollment, enrollment_wo_id, comms_before)."""
        set_logical_clock("2026-07-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Tech Four"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "A-6001", "C12", meter_type="AMI", service_address="11 Maple Dr"
        )
        m2 = create_meter("SN-X-2", "AMI")
        # misses 07-02/03/04 -> NON_COMMUNICATING since 07-04; 07-17 is 13 days
        # (stays); 07-18 is exactly 14 days -> FAILED.
        for at in [
            "2026-07-02T00:00:00Z",
            "2026-07-03T00:00:00Z",
            "2026-07-04T00:00:00Z",
            "2026-07-17T00:00:00Z",
            "2026-07-18T00:00:00Z",
        ]:
            run_ops_snapshot(at)
        comms_before = get_meter(m1["id"])["endpoint_comms_status"]

        campaign = validate_success(
            api.create_replacement_campaign(
                {"campaign_name": "FY26 Endpoint Refresh", "quota": 2}, ADMIN
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)
        enrollments = validate_success(
            api.enroll_meters(campaign["id"], enroll_payload([m1["id"]]), ADMIN), 201
        )
        enrollment = enrollments[0]
        enrollment_wo_id = enrollment["work_order_id"]
        assert enrollment_wo_id is not None

        xwo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE", account["id"], meter_id=m1["id"],
                    scheduled_date="2026-08-10", work_shift="AM",
                ),
                DISPATCHER,
            ),
            201,
        )
        dispatch_order_to(xwo["id"], tech["id"])
        start_order_as(xwo["id"], tech["id"])
        validate_success(
            api.complete_work_order(
                xwo["id"],
                {
                    "new_meter_id": m2["id"],
                    "old_final_read_value": 4321,
                    "new_initial_read_value": 0,
                },
                make_field_technician_headers(tech["id"]),
            ),
            200,
        )
        return account, m1, m2, campaign, enrollment, enrollment_wo_id, comms_before

    def test_exchange_completion_swaps_meters(self, api):
        """PRD section 3.7: "The cascade runs in order: an auto-validated
        `EXCHANGE_FINAL` read is created on the old meter and an
        auto-validated `EXCHANGE_INITIAL` read on the new meter; the old meter
        moves from `IN_SERVICE` to `REMOVED` with its
        `installed_service_account_id` cleared to null; the new meter moves
        from `IN_STOCK` to `IN_SERVICE` with `installed_service_account_id`
        set to the account; the account's `current_meter_id` recomputes; and
        then the removed meter's replacement-program cascade runs — any
        enrollment for that meter in `ENROLLED` or `WORK_ORDER_CREATED`
        transitions to `WITHDRAWN`, its `OPEN` or `DISPATCHED` work order
        transitions to `CANCELLED`, and the owning campaign recomputes its
        counts and auto-completes when every enrollment is terminal and at
        least one exists (§3.8)."

        Design: Difficulty/transitive_cascade/exchange_completion_cascades_through_enrollment_to_campaign_completion
        """
        account, m1, m2, _campaign, _enr, _enr_wo, comms_before = (
            self._exchange_cascade_scenario(api)
        )
        assert comms_before == "FAILED"

        old_meter = get_meter(m1["id"])
        assert old_meter["meter_status"] == "REMOVED"
        assert old_meter["installed_service_account_id"] is None

        new_meter = get_meter(m2["id"])
        assert new_meter["meter_status"] == "IN_SERVICE"
        assert new_meter["installed_service_account_id"] == account["id"]

        assert get_account(account["id"])["current_meter_id"] == m2["id"]

        # auto-validated exchange reads exist on both meters
        final_reads, meta_final = validate_paginated(
            api.list_reads(ADMIN, params={"meter_id": m1["id"]})
        )
        assert meta_final["total_count"] == 1
        assert final_reads[0]["read_source"] == "EXCHANGE_FINAL"
        assert final_reads[0]["read_status"] == "VALIDATED"
        assert final_reads[0]["read_value"] == 4321

        initial_reads, meta_initial = validate_paginated(
            api.list_reads(ADMIN, params={"meter_id": m2["id"]})
        )
        assert meta_initial["total_count"] == 1
        assert initial_reads[0]["read_source"] == "EXCHANGE_INITIAL"
        assert initial_reads[0]["read_status"] == "VALIDATED"
        assert initial_reads[0]["read_value"] == 0

    def test_exchange_completion_cascades_to_campaign_completion(self, api):
        """PRD section 3.8: "Withdrawal arrives by cascade — the meter being
        removed through an exchange, the meter's `tamper_status` flipping to
        `SUSPECTED`, or the campaign closing — moving an enrollment in
        `ENROLLED` or `WORK_ORDER_CREATED` to `WITHDRAWN` and cancelling its
        linked `OPEN` or `DISPATCHED` work order."
        PRD section 3.8: "After any enrollment status change, the campaign
        checks for completion: when at least one enrollment exists and every
        enrollment is in `REPLACED` or `WITHDRAWN`, the campaign moves itself
        from `OPEN` to the terminal `COMPLETED`."

        Design: Difficulty/transitive_cascade/exchange_completion_cascades_through_enrollment_to_campaign_completion
        """
        _account, _m1, _m2, campaign, enrollment, enrollment_wo_id, _comms = (
            self._exchange_cascade_scenario(api)
        )
        assert get_enrollment(enrollment["id"])["enrollment_status"] == "WITHDRAWN"
        assert get_work_order(enrollment_wo_id)["work_order_status"] == "CANCELLED"

        campaign_after = get_campaign(campaign["id"])
        assert campaign_after["campaign_status"] == "COMPLETED"
        assert campaign_after["withdrawn_count"] == 1
        assert campaign_after["replaced_count"] == 0
        assert campaign_after["enrolled_count"] == 0
