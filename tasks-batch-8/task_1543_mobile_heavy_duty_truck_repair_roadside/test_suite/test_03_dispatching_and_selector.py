"""Dispatching: state gates, ownership, availability, OCC, and the
dispatch-suggestion selector."""
from test_helpers import (
    TEST_USERS,
    accept_dispatch,
    advance_clock,
    complete_dispatch,
    create_dispatch,
    create_dispatch_payload,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_call,
    get_success_data,
    intake_call,
    open_triaged_call,
    start_repair,
    stock_van,
    complete_repair,
    triage_call,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestDispatchCreateStateGate:
    def test_dispatch_create_requires_call_triaged(self, api):
        """PRD: "Dispatch creation is a `Dispatcher` (or `OpsAdmin`) action
        against a `TRIAGED` call" — against a call still `RECEIVED` the create
        fails state-machine legality with `ERR_INVALID_STATE`.

        Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_call_triaged
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, _th = create_technician()
        advance_clock("2026-08-05T09:00:00Z")
        call = intake_call(veh["id"])

        resp = api.create_dispatch(
            call["id"],
            create_dispatch_payload(
                tech["id"], call["version"],
                window_start_at="2026-08-05T10:00:00Z",
                window_end_at="2026-08-05T12:00:00Z"),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_dispatch_create_rejection_leaves_call_untouched(self, api):
        """PRD: "Dispatch creation is a `Dispatcher` (or `OpsAdmin`) action
        against a `TRIAGED` call" — the rejected create leaves the call in
        `RECEIVED` with no dispatch created.

        Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_call_triaged
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, _th = create_technician()
        advance_clock("2026-08-05T09:00:00Z")
        call = intake_call(veh["id"])

        resp = api.create_dispatch(
            call["id"],
            create_dispatch_payload(
                tech["id"], call["version"],
                window_start_at="2026-08-05T10:00:00Z",
                window_end_at="2026-08-05T12:00:00Z"),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_call(call["id"])
        assert after["status"] == "RECEIVED"
        assert after["version"] == call["version"], (
            "a rejected dispatch create must not mutate the call")
        _data, meta = validate_paginated(api.list_dispatches(DISPATCHER))
        assert meta["total_count"] == 0


class TestDispatchOwnershipAndAvailability:
    def test_technician_cannot_accept_other_technicians_dispatch(self, api):
        """PRD: "Accepting requires the actor to be the dispatch's own
        technician (`ERR_FORBIDDEN_OWNERSHIP` otherwise)".

        Design: Corner/rbac/technician_cannot_accept_other_technicians_dispatch
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        spare, spare_headers = create_technician(full_name="Sam Spare")
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DRIVABLE")
        dispatch = create_dispatch(call["id"], tech["id"],
                                   "2026-08-05T09:00:00Z",
                                   "2026-08-05T13:00:00Z")

        resp = api.accept_dispatch(dispatch["id"], spare_headers)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        current = get_success_data(api.get_dispatch(dispatch["id"], DISPATCHER))
        assert current["status"] == "PROPOSED"

    def test_technician_accept_while_on_dispatch_rejected(self, api):
        """PRD: "Accepting requires the actor to be the dispatch's own
        technician (`ERR_FORBIDDEN_OWNERSHIP` otherwise) and to currently be
        `AVAILABLE` (`ERR_TECHNICIAN_NOT_AVAILABLE` otherwise)".

        Design: Corner/consistency_model/technician_accept_while_on_dispatch_rejected
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        advance_clock("2026-08-05T08:30:00Z")
        call_a = open_triaged_call(veh_a["id"], severity="DRIVABLE",
                                   breakdown_location_text="site A")
        dispatch_a = create_dispatch(call_a["id"], tech["id"],
                                     "2026-08-05T09:00:00Z",
                                     "2026-08-05T13:00:00Z")
        accept_dispatch(dispatch_a["id"], tech_headers)

        call_b = open_triaged_call(veh_b["id"], severity="DRIVABLE",
                                   breakdown_location_text="site B")
        dispatch_b = create_dispatch(call_b["id"], tech["id"],
                                     "2026-08-05T14:00:00Z",
                                     "2026-08-05T16:00:00Z")
        resp = api.accept_dispatch(dispatch_b["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_AVAILABLE)
        current = get_success_data(api.get_dispatch(dispatch_b["id"], DISPATCHER))
        assert current["status"] == "PROPOSED"


class TestDispatchCompletionGate:
    def test_dispatch_complete_requires_finished_work(self, api):
        """PRD: "Completing the dispatch — permitted only once the call has
        reached `REPAIR_COMPLETED`, `TOW_IN_PROGRESS`, or `TOWED`
        (`ERR_INVALID_STATE` otherwise)".

        Design: Corner/state_machines/dispatch_complete_requires_finished_work
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DRIVABLE")
        call, dispatch = drive_call_on_site(
            call, tech["id"], tech_headers, "2026-08-05T09:00:00Z",
            "2026-08-05T13:00:00Z", arrive_at="2026-08-05T09:40:00Z")

        resp = api.complete_dispatch(dispatch["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_dispatch(dispatch["id"], DISPATCHER))
        assert current["status"] == "ON_SITE"
        tech_now = get_success_data(api.get_technician(tech["id"], DISPATCHER))
        assert tech_now["status"] == "ON_DISPATCH"


class TestDispatchActiveExclusivity:
    def test_dispatch_create_while_one_active_rejected(self, api):
        """PRD: dispatch creation is "refused when the call already has a
        dispatch in `ACCEPTED`, `EN_ROUTE`, or `ON_SITE`, rejected with
        `ERR_DISPATCH_ACTIVE`".

        Design: Corner/errors/dispatch_create_while_one_active_rejected
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician()
        spare, _sh = create_technician(full_name="Sam Spare")
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DRIVABLE")
        dispatch = create_dispatch(call["id"], tech["id"],
                                   "2026-08-05T09:00:00Z",
                                   "2026-08-05T13:00:00Z")
        accept_dispatch(dispatch["id"], tech_headers)

        resp = api.create_dispatch(
            call["id"],
            create_dispatch_payload(
                spare["id"], get_call(call["id"])["version"],
                window_start_at="2026-08-05T14:00:00Z",
                window_end_at="2026-08-05T16:00:00Z"),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_ACTIVE)


class TestDispatchCreateOcc:
    def test_occ_stale_dispatch_create_rejected_then_supersedes(self, api):
        """PRD: "If the value does not match the call's current `version` —
        because the call has been mutated since the client last read it, for
        example by another estimate or dispatch being created — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)." and "A successful
        creation ... supersedes any prior `PROPOSED` dispatch of the same call
        to `SUPERSEDED`".

        Design: Corner/cross_cutting_layers/occ_stale_dispatch_create_rejected_then_supersedes
        """
        create_standard_rate_card()
        veh = create_vehicle()
        tech, _th = create_technician()
        spare, _sh = create_technician(full_name="Sam Spare")
        advance_clock("2026-08-05T09:00:00Z")
        call = intake_call(veh["id"])
        triaged = triage_call(call["id"], severity="DRIVABLE")
        first = create_dispatch(call["id"], tech["id"],
                                "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z")
        fresh_version = get_call(call["id"])["version"]

        stale = api.create_dispatch(
            call["id"],
            create_dispatch_payload(
                spare["id"], triaged["version"],
                window_start_at="2026-08-05T14:00:00Z",
                window_end_at="2026-08-05T16:00:00Z"),
            DISPATCHER)
        assert stale.status_code == 412
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        created = validate_success(api.create_dispatch(
            call["id"],
            create_dispatch_payload(
                spare["id"], fresh_version,
                window_start_at="2026-08-05T14:00:00Z",
                window_end_at="2026-08-05T16:00:00Z"),
            DISPATCHER), 201)
        assert created["status"] == "PROPOSED"
        old = get_success_data(api.get_dispatch(first["id"], DISPATCHER))
        assert old["status"] == "SUPERSEDED", (
            "the prior PROPOSED dispatch is superseded by the newer create")


class TestDispatchSelector:
    def test_dispatch_selector_ranking_idle_time_then_created_at(self, api):
        """PRD: "Ranking is ascending by three keys in order: first the count
        of the technician's dispatches currently in `PROPOSED`, `ACCEPTED`,
        `EN_ROUTE`, or `ON_SITE`; then the technician's most recent
        `completed_at` across completed dispatches, with a technician who has
        never completed a dispatch sorting first; then the technician's own
        `created_at` as the final tie-break."

        Design: Corner/calculations/dispatch_selector_ranking_idle_time_then_created_at
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        t_early, h_early = create_technician(full_name="Early Ed")
        t_mid, h_mid = create_technician(full_name="Mid Mike")
        t_late, h_late = create_technician(full_name="Late Lou")
        for tech in (t_early, t_mid, t_late):
            stock_van(tech["id"], part_number=f"ALT-{tech['employee_code']}",
                      qty_on_hand=5)
        advance_clock("2026-08-04T07:00:00Z")
        # Give T_LATE one COMPLETED dispatch so his last_completed_at is set.
        old_call = open_triaged_call(
            veh_b["id"], severity="DEFERRED",
            breakdown_location_text="site old",
            symptom_description="old job for the late tech")
        old_call, old_dispatch = drive_call_on_site(
            old_call, t_late["id"], h_late, "2026-08-04T07:00:00Z",
            "2026-08-04T08:00:00Z", depart_at=None,
            arrive_at="2026-08-04T07:30:00Z", actual_travel_miles=10)
        diagnose_call(old_call["id"], h_late, diagnosis_summary="fuse")
        start_repair(old_call["id"], h_late)
        complete_repair(old_call["id"], h_late, 0.5, 90020)
        complete_dispatch(old_dispatch["id"], h_late)

        call = open_triaged_call(veh_a["id"], severity="DRIVABLE",
                                 breakdown_location_text="site new")
        suggestion = validate_success(
            api.get_dispatch_suggestion(call["id"], DISPATCHER))
        assert suggestion["candidate_technician_id"] == t_early["id"], (
            "the never-dispatched pair ties on (0, NULL) and created_at "
            "breaks the tie toward the earliest-created technician")
        assert suggestion["ranked_technician_ids"] == [
            t_early["id"], t_mid["id"], t_late["id"]], (
            "a technician with a completed dispatch sorts after the "
            "never-dispatched pair")

    def test_dispatch_selector_empty_pool_rejected(self, api):
        """PRD: "When the eligible pool is empty the read is rejected with
        `ERR_NO_ELIGIBLE_TECHNICIAN`."

        Design: Corner/calculations/dispatch_selector_empty_pool_rejected
        """
        veh = create_vehicle()
        create_technician()  # ENGINE-only; the call will require TIRES
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], symptom_category="TIRE_BLOWOUT",
                                 severity="BLOCKING",
                                 symptom_description="shredded drive tire")

        resp = api.get_dispatch_suggestion(call["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TECHNICIAN)

    def test_selector_requires_stocked_part_class_on_van(self, api):
        """PRD: eligibility requires that the technician's "van carries at
        least one unit of a stock item in that class" when the call's required
        part class is not `NONE`.

        Design: Corner/calculations/selector_requires_stocked_part_class_on_van
        """
        veh = create_vehicle()
        tech, _th = create_technician()
        item = stock_van(tech["id"], qty_on_hand=0)
        advance_clock("2026-08-05T09:00:00Z")
        call = open_triaged_call(veh["id"], severity="DRIVABLE")

        resp = api.get_dispatch_suggestion(call["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TECHNICIAN)

        get_success_data(api.adjust_van_stock(
            item["id"], {"qty_delta": 2, "reason": "restock from depot"}, OPS))
        suggestion = validate_success(
            api.get_dispatch_suggestion(call["id"], DISPATCHER))
        assert suggestion["candidate_technician_id"] == tech["id"]


class TestTechnicianStatusMachine:
    def test_technician_set_status_on_dispatch_rejected(self, api):
        """PRD: "the fourth status, `ON_DISPATCH`, is system-managed only —
        set when the technician accepts a dispatch and cleared when the
        dispatch completes" — a self-service transition targeting it is not a
        declared transition and fails `ERR_INVALID_STATE`.

        Design: Corner/state_machines/technician_set_status_on_dispatch_rejected
        """
        tech, tech_headers = create_technician()
        resp = api.set_technician_status(tech["id"],
                                         {"to_status": "ON_DISPATCH"},
                                         tech_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_technician(tech["id"], DISPATCHER))
        assert current["status"] == "AVAILABLE"
