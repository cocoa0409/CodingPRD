"""RBAC gates, optimistic concurrency guards, and write-response consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjust_invoice,
    amend_gang,
    berth_vessel,
    create_invoice,
    create_vessel,
    create_vessel_call_payload,
    enter_timesheet,
    get_gang,
    get_invoice,
    get_worker,
    register_worker,
    run_dispatch,
    set_worker_status,
    setup_completed_gang,
    setup_dispatched_gang,
    setup_placed_gang,
    submit_timesheet,
    validate_error,
    validate_success,
    api_client,
)

ADMIN = TEST_USERS["admin_headers"]
SUPT = TEST_USERS["superintendent_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]
PAYROLL = TEST_USERS["payroll_headers"]

HOLDMAN_SPEC = {"full_name": "W One", "registration_number": "R001",
                "classification": "HOLDMAN", "registered_on": "2010-01-01",
                "base_hourly_rate_cents": 4000}


class TestAuthentication:

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_vessel_call(
            create_vessel_call_payload(vessel_name="MV NoAuth",
                                       voyage_number="R-501"),
            headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleGates:

    def test_dispatcher_forbidden_from_vessel_create(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4); a request whose role is not admitted is rejected with `ERR_FORBIDDEN` (403)."
        The §4 endpoint table admits only StevedoreAdmin to POST /api/vessel-calls.

        Design: Corner/rbac/dispatcher_forbidden_from_vessel_create
        """
        resp = api.create_vessel_call(
            create_vessel_call_payload(vessel_name="MV Denied",
                                       voyage_number="R-502"),
            DISP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_clerk_forbidden_from_dispatch_batch(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4); a request whose role is not admitted is rejected with `ERR_FORBIDDEN` (403)."
        The §4 endpoint table admits only LaborHallDispatcher to POST /api/gang-orders/{id}/dispatch-batch.

        Design: Corner/rbac/billing_clerk_forbidden_from_dispatch_batch
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV RoleB", "voyage_number": "R-504"})
        gang = get_gang(ns.gang["id"])
        resp = api.dispatch_batch(
            gang["id"], {"expected_gang_order_version": gang["version"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = get_gang(gang["id"])
        assert after["status"] == "PLACED"
        assert after["offered_count"] == 0

    def test_foreman_forbidden_from_timesheet_approve(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in §4); a request whose role is not admitted is rejected with `ERR_FORBIDDEN` (403)."
        The §4 endpoint table admits only PayrollClerk to POST /api/timesheet-entries/{id}/approve.

        Design: Corner/rbac/foreman_forbidden_from_timesheet_approve
        """
        from test_helpers import make_foreman_headers, get_timesheet_entry
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Role", "voyage_number": "R-503"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMAN_SPEC)])
        t1 = enter_timesheet(ns.gang["id"], ns.workers[0]["id"], ns.foreman_id,
                             work_minutes=120, meal_break_taken=True)
        submit_timesheet(t1["id"], ns.foreman_id)

        # Even the submitting foreman is rejected at the role gate.
        resp = api_client.approve_timesheet_entry(
            t1["id"], make_foreman_headers(ns.foreman_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_timesheet_entry(t1["id"])["status"] == "SUBMITTED"


class TestGangOrderOcc:

    def test_occ_second_dispatch_batch_with_stale_version_rejected(self, api):
        """PRD §2.6: "Running a dispatch batch against a gang order requires `expected_gang_order_version` carrying the gang order's `version` as the client last observed it; if the order's version has advanced since that read — for instance because an amendment changed its terms or an earlier batch already ran — the request is rejected with `ERR_STALE_GANG_ORDER_VERSION` (412)."
        PRD §3.3: "Every batch increments the order's `version` by one, which is why a second batch built on a pre-batch read fails the concurrency check."

        Design: Corner/cross_cutting_complexity_layers/occ_second_dispatch_batch_with_stale_version_rejected
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Occ1", "voyage_number": "X-601"},
            gang_overrides={"required_headcount": 2})
        register_worker(**dict(HOLDMAN_SPEC))
        register_worker(full_name="W Two", registration_number="R002",
                        classification="HOLDMAN", registered_on="2015-06-01",
                        base_hourly_rate_cents=4000)

        observed_version = ns.gang["version"]
        first = run_dispatch(ns.gang["id"])
        assert first["version"] == observed_version + 1
        assert first["offered_count"] == 2

        replay = api.dispatch_batch(
            ns.gang["id"], {"expected_gang_order_version": observed_version}, DISP)
        validate_error(replay, ApiErrorId.ERR_STALE_GANG_ORDER_VERSION)

        after = get_gang(ns.gang["id"])
        assert after["version"] == observed_version + 1
        assert after["offered_count"] == 2

    def test_occ_amend_with_stale_version_rejected(self, api):
        """PRD §2.6: "Amending a gang order's requirements carries the same field and the same rejection."
        PRD §3.2: "an amendment against any other state is rejected with `ERR_INVALID_STATE`, and one carrying a version the server has already advanced past is rejected with `ERR_STALE_GANG_ORDER_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_amend_with_stale_version_rejected
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Occ2", "voyage_number": "X-602"},
            gang_overrides={"required_headcount": 1})
        register_worker(**dict(HOLDMAN_SPEC))
        stale_version = ns.gang["version"]
        run_dispatch(ns.gang["id"])  # advances the version

        resp = amend_gang(ns.gang["id"], stale_version, required_headcount=3)
        validate_error(resp, ApiErrorId.ERR_STALE_GANG_ORDER_VERSION)

        after = get_gang(ns.gang["id"])
        assert after["required_headcount"] == 1
        assert after["version"] == stale_version + 1

    def test_occ_correct_version_amend_succeeds_and_increments(self, api):
        """PRD §3.2: "Every accepted amendment increments the order's `version` by one."
        PRD §2.4: "`version` is a system-managed integer that increments with every modification and anchors the optimistic concurrency rules of §2.6."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_amend_succeeds_and_increments
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Occ3", "voyage_number": "X-603"},
            gang_overrides={"required_headcount": 1})
        before = ns.gang["version"]

        resp = amend_gang(ns.gang["id"], before, required_headcount=3)
        amended = validate_success(resp)
        assert amended["required_headcount"] == 3
        assert amended["version"] == before + 1, (
            "immediate consistency: the write response shows the bumped version")


class TestWorkerAndInvoiceOcc:

    def test_occ_worker_status_replay_with_stale_version_rejected(self, api):
        """PRD §3.3: "A `StevedoreAdmin` changes a worker's `status` — to `ACTIVE`, `SUSPENDED`, or `INACTIVE` — with `expected_worker_version` attached; a stale version is rejected with `ERR_STALE_WORKER_VERSION` (412), and every accepted change increments the worker's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_worker_status_replay_with_stale_version_rejected
        """
        w1 = register_worker(**dict(HOLDMAN_SPEC))
        observed = w1["version"]

        suspended = validate_success(
            set_worker_status(w1["id"], "SUSPENDED", observed))
        assert suspended["version"] == observed + 1

        replay = set_worker_status(w1["id"], "ACTIVE", observed)
        validate_error(replay, ApiErrorId.ERR_STALE_WORKER_VERSION)

        after = get_worker(w1["id"])
        assert after["status"] == "SUSPENDED"
        assert after["version"] == observed + 1

    def test_occ_invoice_adjustment_replay_with_stale_version_rejected(self, api):
        """PRD §3.9: "An adjustment carries `adjustment_cents`, a free-text `reason`, and `expected_invoice_version`; a version that no longer matches is rejected with `ERR_STALE_INVOICE_VERSION` (412). Every accepted adjustment adds its `adjustment_cents` into `adjustment_total_cents`, recomputes the totals, and increments the invoice's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_invoice_adjustment_replay_with_stale_version_rejected
        """
        vessel = create_vessel(vessel_name="MV Occ4", voyage_number="X-604")
        berth_vessel(vessel["id"])
        invoice = create_invoice(vessel["id"])
        observed = invoice["version"]

        first = validate_success(
            adjust_invoice(invoice["id"], 500, "Documentation fee",
                           expected_version=observed))
        assert first["adjustment_total_cents"] == 500
        assert first["version"] == observed + 1

        replay = adjust_invoice(invoice["id"], 500, "Documentation fee",
                                expected_version=observed)
        validate_error(replay, ApiErrorId.ERR_STALE_INVOICE_VERSION)

        after = get_invoice(invoice["id"])
        assert after["adjustment_total_cents"] == 500, (
            "the replayed adjustment must not double-apply")


class TestSchemaBeatsState:

    def _setup_completed_one_man_gang(self):
        return setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Prio3", "voyage_number": "P-113"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMAN_SPEC)])

    def test_schema_error_beats_state_error_on_amend(self, api):
        """PRD §2.5: "When several checks would fail on the same request, the failure that surfaces is determined by a fixed priority order — the first failing check wins and later checks are never evaluated for that request."
        PRD §2.5: "4. **Schema.** Required fields are present, enum values are in range, and numeric ranges hold."
        PRD §3.2: "The order names its `shift_window_id`, a `gang_type` of `CRANE_GANG`, `HOLD_GANG`, `LASHING_GANG`, `DRIVING_GANG`, or `GENERAL`, a `required_classification` of `CRANE_OPERATOR`, `HOLDMAN`, `LASHER`, `DRIVER`, or `CLERK` that defines dispatch eligibility, a `required_headcount` of at least one, a `required_equipment_type` of `SHIP_CRANE`, `RTG`, `FORKLIFT`, or `TRACTOR`, and a `required_equipment_count` of zero or more units of that type that must be covered before work may start."

        Design: Difficulty/priority_pair_validation_conflict/schema_error_beats_state_error_on_amend
        """
        ns = self._setup_completed_one_man_gang()
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "COMPLETED"

        # Out-of-range headcount (schema, tier 4) against a terminal gang
        # (state, tier 6): the schema failure surfaces first.
        resp = amend_gang(gang["id"], gang["version"], required_headcount=-5)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_schema_priority_leaves_completed_gang_untouched(self, api):
        """PRD §3.2: "While an order is in `PLACED`, `DISPATCHING`, `SHORT_MANNED`, or `MANNED`, the superintendent may amend its requirements — a payload optionally carrying a new `required_headcount` or `required_equipment_count`, and always carrying `expected_gang_order_version`; an amendment against any other state is rejected with `ERR_INVALID_STATE`, and one carrying a version the server has already advanced past is rejected with `ERR_STALE_GANG_ORDER_VERSION` (412)."
        PRD §3.2: "The order names its `shift_window_id`, a `gang_type` of `CRANE_GANG`, `HOLD_GANG`, `LASHING_GANG`, `DRIVING_GANG`, or `GENERAL`, a `required_classification` of `CRANE_OPERATOR`, `HOLDMAN`, `LASHER`, `DRIVER`, or `CLERK` that defines dispatch eligibility, a `required_headcount` of at least one, a `required_equipment_type` of `SHIP_CRANE`, `RTG`, `FORKLIFT`, or `TRACTOR`, and a `required_equipment_count` of zero or more units of that type that must be covered before work may start."

        Design: Difficulty/priority_pair_validation_conflict/schema_error_beats_state_error_on_amend
        """
        ns = self._setup_completed_one_man_gang()
        gang = get_gang(ns.gang["id"])

        resp = amend_gang(gang["id"], gang["version"], required_headcount=-5)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        after = get_gang(gang["id"])
        assert after["status"] == "COMPLETED"
        assert after["required_headcount"] == 1
        assert after["version"] == gang["version"]


class TestImmediateConsistency:

    def test_mutations_are_visible_in_the_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.2: "Every accepted amendment increments the order's `version` by one."

        Design: Corner/consistency_model/mutations_are_visible_in_the_same_response
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Imm", "voyage_number": "X-701"},
            gang_overrides={"required_headcount": 1})
        before = ns.gang["version"]

        resp = amend_gang(ns.gang["id"], before, required_headcount=3)
        body = validate_success(resp)
        assert body["required_headcount"] == 3
        assert body["version"] == before + 1

        reread = get_gang(ns.gang["id"])
        assert reread["required_headcount"] == body["required_headcount"]
        assert reread["version"] == body["version"], (
            "no drift between the write response and a subsequent read")
