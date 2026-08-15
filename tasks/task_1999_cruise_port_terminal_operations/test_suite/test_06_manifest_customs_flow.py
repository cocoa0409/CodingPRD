"""Passenger flow and customs coordination: direction-parallel flows, the
customs case re-file cycle, hold cascades, boarding gates, screening
preconditions, and departure's customs gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    arrive_port_call,
    begin_turnaround,
    board_entry,
    check_in_entry,
    clear_customs_case,
    create_confirmed_assignment,
    create_customs_case,
    create_open_lane,
    create_port_call,
    customs_release_entry,
    depart_port_call,
    disembark_entry,
    file_customs_case,
    get_customs_case,
    get_manifest_entry,
    get_port_call,
    screen_entry,
    setup_base,
    setup_scheduled_call,
    setup_turnaround_call,
    validate_error,
    validate_paginated,
    validate_success,
)

CUSTOMS = TEST_USERS["customs_headers"]
OPERATOR = TEST_USERS["operator_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


def _setup_arrived_with_debark_entries(vessel_name, second_cabin="STANDARD"):
    """Call ARRIVED; customs case FILED; D1 DISEMBARKED; D2 still ABOARD."""
    ctx = setup_base(vessel_name=vessel_name)
    pc = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                          voyage_ref="V1", booked_embark_pax=100,
                          booked_debark_pax=100)
    ctx["port_call"] = pc
    ves = ctx["vessel"]["id"]
    e1 = add_manifest_entry(pc["id"], ves, "D1", direction="DEBARK")
    e2 = add_manifest_entry(pc["id"], ves, "D2", direction="DEBARK",
                            cabin_class=second_cabin)
    cc = create_customs_case(pc["id"])
    file_customs_case(cc["id"])
    ctx["assignment"] = create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
    ctx["port_call"] = arrive_port_call(pc["id"])
    disembark_entry(e1["id"])
    ctx["e1"] = e1
    ctx["e2"] = e2
    ctx["customs_case"] = cc
    return ctx


class TestCustomsCaseRefileCycle:
    def test_hold_blocks_disembark_until_refiled(self, api):
        """PRD §3.5: "The call must be `ARRIVED` or `TURNAROUND`, and the
        call's customs case must be `FILED` or `CLEARED`: while the case is
        `HELD` the disembark is rejected with `ERR_CUSTOMS_HOLD_ACTIVE`, and a
        case that has not yet reached `FILED` fails the same gate with
        `ERR_CUSTOMS_NOT_CLEARED`."
        PRD §3.5: "A `HELD` case can be re-filed back to `FILED` with no
        preconditions, and this revision loop — `FILED` → `HELD` → `FILED` —
        re-allows disembarkation each time around."

        Design: Difficulty/non_linear_state_machine/customs_case_refile_cycle
        """
        ctx = _setup_arrived_with_debark_entries("MV F")
        cc_id = ctx["customs_case"]["id"]

        validate_success(api.hold_customs_case(
            cc_id, {"reason": "agriculture inspection"}, CUSTOMS))
        assert get_customs_case(cc_id)["status"] == "HELD"

        blocked = api.disembark_manifest_entry(ctx["e2"]["id"], OPERATOR)
        validate_error(blocked, ApiErrorId.ERR_CUSTOMS_HOLD_ACTIVE)

        file_customs_case(cc_id)
        assert get_customs_case(cc_id)["status"] == "FILED"

        disembarked = disembark_entry(ctx["e2"]["id"])
        assert disembarked["status"] == "DISEMBARKED"

    def test_refiled_case_clears_to_terminal(self, api):
        """PRD §3.5: "**Clearing** moves a `FILED` case to its terminal state
        `CLEARED`. Clearing the case does not release entries already `HELD`;
        each held passenger needs an individual `customs-release`."
        PRD §3.5: "A `HELD` case can be re-filed back to `FILED` with no
        preconditions, and this revision loop — `FILED` → `HELD` → `FILED` —
        re-allows disembarkation each time around."

        Design: Difficulty/non_linear_state_machine/customs_case_refile_cycle
        """
        ctx = _setup_arrived_with_debark_entries("MV F2")
        cc_id = ctx["customs_case"]["id"]

        validate_success(api.hold_customs_case(cc_id, {"reason": "hold"}, CUSTOMS))
        file_customs_case(cc_id)
        cleared = clear_customs_case(cc_id)
        assert cleared["status"] == "CLEARED"
        assert get_customs_case(cc_id)["status"] == "CLEARED"


class TestDirectionParallelFlows:
    def test_cross_direction_actions_rejected(self, api):
        """PRD §2.9: "7. Direction applicability: check-in, screen, board, and
        offload require an `EMBARK` entry; disembark, customs-hold, and
        customs-release require a `DEBARK` entry; loading a bag requires an
        `EMBARK` entry and delivering a bag requires a `DEBARK` entry —
        otherwise `ERR_MANIFEST_DIRECTION` (422). Direction is evaluated before
        state preconditions because the operation is undefined for the other
        direction's flow."

        Design: Difficulty/non_linear_state_machine/manifest_entry_direction_parallel_flows
        """
        ctx = setup_scheduled_call(vessel_name="MV G")
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        ee = add_manifest_entry(pc["id"], ves, "E1", direction="EMBARK")
        ed = add_manifest_entry(pc["id"], ves, "D1", direction="DEBARK")

        err1 = api.check_in_manifest_entry(ed["id"], OPERATOR)
        validate_error(err1, ApiErrorId.ERR_MANIFEST_DIRECTION)

        err2 = api.disembark_manifest_entry(ee["id"], OPERATOR)
        validate_error(err2, ApiErrorId.ERR_MANIFEST_DIRECTION)

    def test_each_direction_flow_reaches_its_terminal_state(self, api):
        """PRD §3.5: "The `direction` selects the entire flow: an `EMBARK`
        entry begins in `BOOKED`; a `DEBARK` entry begins `ABOARD`."
        PRD §3.5: "The terminal states of a manifest entry are `EMBARKED`,
        `NO_SHOW`, `CLEARED`, `CARRIED_AWAY`, and `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/manifest_entry_direction_parallel_flows
        """
        ctx = setup_scheduled_call(vessel_name="MV G3")
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        ee = add_manifest_entry(pc["id"], ves, "E1", direction="EMBARK")
        ed = add_manifest_entry(pc["id"], ves, "D1", direction="DEBARK")
        check_in_entry(ee["id"])
        create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
        cc = create_customs_case(pc["id"])
        file_customs_case(cc["id"])
        create_open_lane(ctx["terminal"]["id"], officers_assigned=2)
        arrive_port_call(pc["id"])
        screen_entry(ee["id"])
        begin_turnaround(pc["id"])
        clear_customs_case(cc["id"])

        boarded = board_entry(ee["id"])
        assert boarded["status"] == "EMBARKED"

        disembarked = disembark_entry(ed["id"])
        assert disembarked["status"] == "DISEMBARKED"
        cleared_entry = customs_release_entry(ed["id"])
        assert cleared_entry["status"] == "CLEARED"


class TestCustomsHoldCascade:
    def test_hold_records_reason_and_holds_disembarked_entries(self, api):
        """PRD §3.5: "**Holding** moves a `FILED` case to `HELD`, records the
        payload's `reason` as `hold_reason`, and cascades: every `DEBARK`
        manifest entry of the call currently `DISEMBARKED` becomes `HELD`."

        Design: Difficulty/transitive_cascade/customs_hold_cascade
        """
        ctx = _setup_arrived_with_debark_entries("MV J")
        held = validate_success(api.hold_customs_case(
            ctx["customs_case"]["id"], {"reason": "manifest discrepancy"},
            CUSTOMS))
        assert held["status"] == "HELD"
        assert held["hold_reason"] == "manifest discrepancy"
        assert get_manifest_entry(ctx["e1"]["id"])["status"] == "HELD"

    def test_hold_leaves_aboard_entries_untouched(self, api):
        """PRD §3.5: "**Holding** moves a `FILED` case to `HELD`, records the
        payload's `reason` as `hold_reason`, and cascades: every `DEBARK`
        manifest entry of the call currently `DISEMBARKED` becomes `HELD`."

        Design: Difficulty/transitive_cascade/customs_hold_cascade
        """
        ctx = _setup_arrived_with_debark_entries("MV J2",
                                                 second_cabin="PREMIUM")
        validate_success(api.hold_customs_case(
            ctx["customs_case"]["id"], {"reason": "manifest discrepancy"},
            CUSTOMS))
        assert get_manifest_entry(ctx["e2"]["id"])["status"] == "ABOARD"


class TestBoardGates:
    def _setup_screened_entry(self):
        """Call ARRIVED with one SCREENED EMBARK entry; customs case FILED."""
        ctx = setup_scheduled_call(vessel_name="MV O", booked_embark_pax=100,
                                   booked_debark_pax=100)
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        e1 = add_manifest_entry(pc["id"], ves, "P1", direction="EMBARK")
        check_in_entry(e1["id"])
        ctx["assignment"] = create_confirmed_assignment(pc["id"],
                                                        ctx["berth"]["id"])
        cc = create_customs_case(pc["id"])
        file_customs_case(cc["id"])
        create_open_lane(ctx["terminal"]["id"], officers_assigned=2)
        ctx["port_call"] = arrive_port_call(pc["id"])
        screen_entry(e1["id"])
        ctx["e1"] = e1
        ctx["customs_case"] = cc
        return ctx

    def test_board_rejected_while_call_not_in_turnaround(self, api):
        """PRD §3.5: "**Boarding** moves it from `SCREENED` to `EMBARKED`,
        requires the call to be `TURNAROUND`, and requires the call's customs
        case to be `CLEARED` — otherwise `ERR_CUSTOMS_NOT_CLEARED`; each
        boarding adds one to the call's `passengers_aboard`."
        PRD §2.9: "8. State preconditions: the target entity is in a state from
        which the requested transition exists, including parent-state gates on
        child creation — otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/board_gated_by_call_and_customs
        """
        ctx = self._setup_screened_entry()
        # Call is ARRIVED, not TURNAROUND: the state gate fires.
        resp = api.board_manifest_entry(ctx["e1"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_board_rejected_until_customs_cleared_then_boards(self, api):
        """PRD §3.5: "**Boarding** moves it from `SCREENED` to `EMBARKED`,
        requires the call to be `TURNAROUND`, and requires the call's customs
        case to be `CLEARED` — otherwise `ERR_CUSTOMS_NOT_CLEARED`; each
        boarding adds one to the call's `passengers_aboard`."

        Design: Difficulty/cross_entity_state_dependency/board_gated_by_call_and_customs
        """
        ctx = self._setup_screened_entry()
        begin_turnaround(ctx["port_call"]["id"])

        # Case still FILED: the customs gate fires.
        resp = api.board_manifest_entry(ctx["e1"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CUSTOMS_NOT_CLEARED)

        clear_customs_case(ctx["customs_case"]["id"])
        boarded = board_entry(ctx["e1"]["id"])
        assert boarded["status"] == "EMBARKED"
        assert get_port_call(ctx["port_call"]["id"])["passengers_aboard"] == 1


class TestScreeningAndCaseCreation:
    def test_screen_requires_open_staffed_lane(self, api):
        """PRD §3.5: "**Screening** moves it from `CHECKED_IN` to `SCREENED`,
        requires the call to be `ARRIVED` or `TURNAROUND`, and additionally
        requires at least one `OPEN` screening lane of the terminal with at
        least one officer assigned — otherwise `ERR_SCREENING_CAPACITY`."

        Design: Corner/validations/screen_requires_open_lane
        """
        ctx = setup_scheduled_call()
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        e1 = add_manifest_entry(pc["id"], ves, "P1", direction="EMBARK")
        check_in_entry(e1["id"])
        create_confirmed_assignment(pc["id"], ctx["berth"]["id"])
        arrive_port_call(pc["id"])

        resp = api.screen_manifest_entry(e1["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SCREENING_CAPACITY)

    def test_second_customs_case_rejected(self, api):
        """PRD §3.5: "There is at most one case per port call — a second
        attempt is rejected with `ERR_DUPLICATE_CUSTOMS_CASE` — and it may be
        created while the call is `SCHEDULED`, `DELAYED`, `ARRIVED`, or
        `TURNAROUND`."

        Design: Corner/validations/duplicate_customs_case_rejected
        """
        ctx = setup_scheduled_call()
        create_customs_case(ctx["port_call"]["id"])
        resp = api.create_customs_case(ctx["port_call"]["id"], CUSTOMS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CUSTOMS_CASE)

    def test_depart_requires_customs_cleared(self, api):
        """PRD §3.3: "From `TURNAROUND`, four conditions must hold, evaluated
        in pipeline order: the terminal's posture must not be `EMERGENCY`
        (`ERR_POSTURE_EMERGENCY`); the call's customs case must be `CLEARED`
        (`ERR_CUSTOMS_NOT_CLEARED`); no baggage item of the call may remain in
        `MISTAGGED` or `RECOVERED` (`ERR_OPEN_MISTAGS`); and every service order
        of the call must be in `COMPLETED`, `REJECTED`, or `CANCELLED`
        (`ERR_OPEN_SERVICE_ORDERS`)."

        Design: Corner/errors/depart_requires_customs_cleared
        """
        ctx = setup_turnaround_call(customs="filed")
        resp = api.depart_port_call(ctx["port_call"]["id"],
                                    {"actual_etd": "2026-08-10T20:00:00Z"},
                                    HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_CUSTOMS_NOT_CLEARED)

        clear_customs_case(ctx["customs_case"]["id"])
        departed = depart_port_call(ctx["port_call"]["id"],
                                    actual_etd="2026-08-10T20:00:00Z")
        assert departed["status"] == "DEPARTED"


class TestManifestListing:
    def test_manifest_list_filters_combine(self, api):
        """PRD §3.5: "Entries may be listed with `port_call_id`, `status`, and
        `direction` filters."

        Design: Corner/endpoints/manifest_list_filters_combine
        """
        ctx = setup_scheduled_call()
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        e1 = add_manifest_entry(pc["id"], ves, "E1", direction="EMBARK",
                                cabin_class="STANDARD")
        add_manifest_entry(pc["id"], ves, "E2", direction="EMBARK",
                           cabin_class="PREMIUM")
        add_manifest_entry(pc["id"], ves, "D1", direction="DEBARK")
        check_in_entry(e1["id"])

        _, meta_emb = validate_paginated(
            api.list_manifest_entries(OPERATOR, params={"port_call_id": pc["id"],
                                                        "direction": "EMBARK"}))
        assert meta_emb["total_count"] == 2

        _, meta_ci = validate_paginated(
            api.list_manifest_entries(OPERATOR, params={"port_call_id": pc["id"],
                                                        "status": "CHECKED_IN"}))
        assert meta_ci["total_count"] == 1

        _, meta_both = validate_paginated(
            api.list_manifest_entries(OPERATOR, params={"port_call_id": pc["id"],
                                                        "direction": "EMBARK",
                                                        "status": "BOOKED"}))
        assert meta_both["total_count"] == 1
