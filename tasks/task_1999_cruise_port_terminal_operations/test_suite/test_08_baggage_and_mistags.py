"""Baggage handling: load/deliver cross-entity gates, the mistag recovery
loop, departure's open-mistag gate, and the no-show / carried-away cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    board_entry,
    check_bag,
    check_in_entry,
    depart_port_call,
    get_bag,
    get_manifest_entry,
    get_port_call,
    load_bag,
    make_vessel_agent_headers,
    offload_entry,
    screen_entry,
    setup_scheduled_call,
    setup_turnaround_with_entries,
    stage_bag,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["operator_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestBagLoadGate:
    def _setup(self):
        """Call TURNAROUND, case CLEARED; EMBARK entry SCREENED; bag STAGED."""
        ctx = setup_turnaround_with_entries(
            [{"ref": "P1", "direction": "EMBARK", "progress": "screened"}],
            vessel_name="MV Q", customs="cleared")
        bag = check_bag(ctx["entries"]["P1"]["id"], tag_code="TAG1")
        stage_bag(bag["id"])
        ctx["bag"] = bag
        return ctx

    def test_load_rejected_until_entry_embarked(self, api):
        """PRD §3.6: "**Loading** moves a `STAGED` bag to `LOADED` and is an
        embark-side act: the owning entry's `direction` must be `EMBARK`
        (`ERR_MANIFEST_DIRECTION` otherwise), the entry itself must be
        `EMBARKED` (`ERR_INVALID_STATE`), and the call must be `TURNAROUND`;
        each load adds one to the call's `bags_aboard`."

        Design: Difficulty/cross_entity_state_dependency/bag_load_gated_by_entry_embarked
        """
        ctx = self._setup()
        # The entry is SCREENED, not EMBARKED: the cross-entity gate fires.
        resp = api.load_baggage_item(ctx["bag"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_load_after_board_increments_bags_aboard(self, api):
        """PRD §3.6: "**Loading** moves a `STAGED` bag to `LOADED` and is an
        embark-side act: the owning entry's `direction` must be `EMBARK`
        (`ERR_MANIFEST_DIRECTION` otherwise), the entry itself must be
        `EMBARKED` (`ERR_INVALID_STATE`), and the call must be `TURNAROUND`;
        each load adds one to the call's `bags_aboard`."

        Design: Difficulty/cross_entity_state_dependency/bag_load_gated_by_entry_embarked
        """
        ctx = self._setup()
        board_entry(ctx["entries"]["P1"]["id"])
        loaded = load_bag(ctx["bag"]["id"])
        assert loaded["status"] == "LOADED"
        assert get_port_call(ctx["port_call"]["id"])["bags_aboard"] == 1


class TestAboardConservation:
    def _setup(self):
        """Three EMBARK entries EMBARKED; P2's bag LOADED."""
        ctx = setup_turnaround_with_entries(
            [{"ref": "P1", "direction": "EMBARK", "progress": "embarked"},
             {"ref": "P2", "direction": "EMBARK", "progress": "embarked"},
             {"ref": "P3", "direction": "EMBARK", "cabin_class": "PREMIUM",
              "progress": "embarked"}],
            vessel_name="MV T", customs="cleared")
        bag = check_bag(ctx["entries"]["P2"]["id"], tag_code="TAG-P2")
        stage_bag(bag["id"])
        load_bag(bag["id"])
        ctx["bag"] = bag
        return ctx

    def test_offload_compensates_headcount_and_bags(self, api):
        """PRD §3.5: "**offloading** an `EMBARKED` entry returns it to
        `CHECKED_IN`, is only possible while the call is `TURNAROUND`, subtracts
        one from `passengers_aboard`, and cascades — every bag of the entry
        currently `LOADED` becomes `OFFLOADED`, with `bags_aboard` decremented
        once per offloaded bag."

        Design: Difficulty/compensating_invariant/passengers_aboard_embark_offload_conservation
        """
        ctx = self._setup()
        pc_id = ctx["port_call"]["id"]
        baseline = get_port_call(pc_id)
        assert baseline["passengers_aboard"] == 3
        assert baseline["bags_aboard"] == 1

        offloaded = offload_entry(ctx["entries"]["P2"]["id"])
        assert offloaded["status"] == "CHECKED_IN"

        after = get_port_call(pc_id)
        assert after["passengers_aboard"] == 2
        assert after["bags_aboard"] == 0
        assert get_bag(ctx["bag"]["id"])["status"] == "OFFLOADED"

    def test_reboard_restores_headcount(self, api):
        """PRD §3.5: "The aboard counts are conserved across the board/offload
        pair."
        PRD §3.5: "**Boarding** moves it from `SCREENED` to `EMBARKED`,
        requires the call to be `TURNAROUND`, and requires the call's customs
        case to be `CLEARED` — otherwise `ERR_CUSTOMS_NOT_CLEARED`; each
        boarding adds one to the call's `passengers_aboard`."

        Design: Difficulty/compensating_invariant/passengers_aboard_embark_offload_conservation
        """
        ctx = self._setup()
        pc_id = ctx["port_call"]["id"]

        offload_entry(ctx["entries"]["P2"]["id"])
        screen_entry(ctx["entries"]["P2"]["id"])
        reboarded = board_entry(ctx["entries"]["P2"]["id"])
        assert reboarded["status"] == "EMBARKED"
        assert get_port_call(pc_id)["passengers_aboard"] == 3


class TestMistagRecoveryLoop:
    def test_mistag_recover_restage_loop(self, api):
        """PRD §3.6: "A `TerminalOperator` may report a mistag on any bag in
        `CHECKED` or `STAGED`, optionally attaching a free-text `note`; the bag
        becomes `MISTAGGED`. Recovering the bag moves it to `RECOVERED`, and
        re-staging from `RECOVERED` carries no preconditions — the recovery loop
        `MISTAGGED` → `RECOVERED` → `STAGED` re-enters the normal flow at the
        staging step."

        Design: Corner/state_machines/baggage_mistag_recovery_loop
        """
        ctx = setup_scheduled_call()
        pc = ctx["port_call"]
        entry = add_manifest_entry(pc["id"], ctx["vessel"]["id"], "P1",
                                   direction="EMBARK")
        check_in_entry(entry["id"])
        bag = check_bag(entry["id"], tag_code="TAG1")

        staged = stage_bag(bag["id"])
        assert staged["status"] == "STAGED"

        mistagged = validate_success(
            api.report_mistag_baggage_item(
                bag["id"], OPERATOR,
                payload={"note": "tag reads different voyage"}))
        assert mistagged["status"] == "MISTAGGED"

        recovered = validate_success(api.recover_baggage_item(bag["id"], OPERATOR))
        assert recovered["status"] == "RECOVERED"

        restaged = stage_bag(bag["id"])
        assert restaged["status"] == "STAGED"


class TestBaggageDirectionGuards:
    def test_load_and_deliver_wrong_direction_rejected(self, api):
        """PRD §2.9: "7. Direction applicability: check-in, screen, board, and
        offload require an `EMBARK` entry; disembark, customs-hold, and
        customs-release require a `DEBARK` entry; loading a bag requires an
        `EMBARK` entry and delivering a bag requires a `DEBARK` entry —
        otherwise `ERR_MANIFEST_DIRECTION` (422). Direction is evaluated before
        state preconditions because the operation is undefined for the other
        direction's flow."
        PRD §3.6: "**Delivery** is the debark-side mirror: a `STAGED` bag
        becomes `DELIVERED` only when its owning entry's `direction` is `DEBARK`
        (`ERR_MANIFEST_DIRECTION` otherwise) and the entry has been `CLEARED` by
        customs — delivering before clearance is rejected with
        `ERR_CUSTOMS_NOT_CLEARED`."

        Design: Corner/validations/baggage_direction_guards
        """
        ctx = setup_turnaround_with_entries(
            [{"ref": "E1", "direction": "EMBARK", "progress": "checked_in"},
             {"ref": "D1", "direction": "DEBARK", "progress": "disembarked"}],
            customs="filed")
        bag_e = check_bag(ctx["entries"]["E1"]["id"], tag_code="BE1")
        stage_bag(bag_e["id"])
        bag_d = check_bag(ctx["entries"]["D1"]["id"], tag_code="BD1")
        stage_bag(bag_d["id"])

        # Load requires an EMBARK entry: the DEBARK bag is rejected.
        err1 = api.load_baggage_item(bag_d["id"], OPERATOR)
        validate_error(err1, ApiErrorId.ERR_MANIFEST_DIRECTION)

        # Deliver requires a DEBARK entry: the EMBARK bag is rejected with the
        # direction error, not the customs gate, even though its owning entry
        # is not CLEARED.
        err2 = api.deliver_baggage_item(bag_e["id"], OPERATOR)
        validate_error(err2, ApiErrorId.ERR_MANIFEST_DIRECTION)


class TestDepartMistagGate:
    def test_depart_blocked_until_mistags_resolved(self, api):
        """PRD §3.3: "From `TURNAROUND`, four conditions must hold, evaluated
        in pipeline order: the terminal's posture must not be `EMERGENCY`
        (`ERR_POSTURE_EMERGENCY`); the call's customs case must be `CLEARED`
        (`ERR_CUSTOMS_NOT_CLEARED`); no baggage item of the call may remain in
        `MISTAGGED` or `RECOVERED` (`ERR_OPEN_MISTAGS`); and every service order
        of the call must be in `COMPLETED`, `REJECTED`, or `CANCELLED`
        (`ERR_OPEN_SERVICE_ORDERS`)."
        PRD §3.6: "Mistags are not merely operational noise: departure is
        blocked while any bag of the call remains in `MISTAGGED` or `RECOVERED`
        (§3.3)."

        Design: Corner/errors/depart_blocked_by_open_mistags
        """
        ctx = setup_turnaround_with_entries(
            [{"ref": "P1", "direction": "EMBARK", "progress": "checked_in"}],
            customs="cleared")
        entry_id = ctx["entries"]["P1"]["id"]
        bag = check_bag(entry_id, tag_code="TAG1")
        stage_bag(bag["id"])
        screen_entry(entry_id)
        board_entry(entry_id)
        validate_success(api.report_mistag_baggage_item(bag["id"], OPERATOR))

        err1 = api.depart_port_call(ctx["port_call"]["id"],
                                    {"actual_etd": "2026-08-10T20:00:00Z"},
                                    HARBORMASTER)
        validate_error(err1, ApiErrorId.ERR_OPEN_MISTAGS)

        validate_success(api.recover_baggage_item(bag["id"], OPERATOR))
        err2 = api.depart_port_call(ctx["port_call"]["id"],
                                    {"actual_etd": "2026-08-10T20:00:00Z"},
                                    HARBORMASTER)
        validate_error(err2, ApiErrorId.ERR_OPEN_MISTAGS)

        stage_bag(bag["id"])
        departed = depart_port_call(ctx["port_call"]["id"],
                                    actual_etd="2026-08-10T20:00:00Z")
        assert departed["status"] == "DEPARTED"


class TestDepartureCascades:
    def test_depart_marks_no_show_and_offloads_bags(self, api):
        """PRD §3.3: "Departure releases the berth — the `ACTIVE` assignment
        becomes `RELEASED` and the terminal's occupancy and posture are
        recomputed — and then cascades through the manifests: the call's
        `EMBARK` entries still in `BOOKED`, `CHECKED_IN`, or `SCREENED` become
        `NO_SHOW`, and its `DEBARK` entries still `ABOARD` become
        `CARRIED_AWAY`."
        PRD §3.3: "Each newly `NO_SHOW` entry's bags in `CHECKED` or `STAGED`
        become `OFFLOADED`, and any bag of such an entry still `LOADED` is
        likewise offloaded, decrementing `bags_aboard` per bag."

        Design: Corner/state_machines/depart_no_show_cascade
        """
        ctx = setup_turnaround_with_entries(
            [{"ref": "P1", "direction": "EMBARK", "progress": "checked_in"}],
            customs="cleared")
        entry_id = ctx["entries"]["P1"]["id"]
        bag = check_bag(entry_id, tag_code="TAG1")
        stage_bag(bag["id"])

        departed = depart_port_call(ctx["port_call"]["id"],
                                    actual_etd="2026-08-10T20:00:00Z")
        assert departed["status"] == "DEPARTED"
        assert get_manifest_entry(entry_id)["status"] == "NO_SHOW"
        assert get_bag(bag["id"])["status"] == "OFFLOADED"
        assert get_port_call(ctx["port_call"]["id"])["passengers_aboard"] == 0

    def test_debark_entry_carried_away_at_depart(self, api):
        """PRD §3.3: "Departure releases the berth — the `ACTIVE` assignment
        becomes `RELEASED` and the terminal's occupancy and posture are
        recomputed — and then cascades through the manifests: the call's
        `EMBARK` entries still in `BOOKED`, `CHECKED_IN`, or `SCREENED` become
        `NO_SHOW`, and its `DEBARK` entries still `ABOARD` become
        `CARRIED_AWAY`."

        Design: Corner/state_machines/debark_entry_carried_away_at_depart
        """
        ctx = setup_turnaround_with_entries(
            [{"ref": "D1", "direction": "DEBARK"}],
            customs="cleared")

        depart_port_call(ctx["port_call"]["id"],
                         actual_etd="2026-08-10T20:00:00Z")
        assert get_manifest_entry(ctx["entries"]["D1"]["id"])["status"] == "CARRIED_AWAY"


class TestDuplicateOperationalKeys:
    def test_duplicate_passenger_ref_and_tag_rejected(self, api):
        """PRD §3.5: "Each entry carries a `passenger_ref` that must be unique
        within its port call (duplicates are rejected with
        `ERR_DUPLICATE_MANIFEST_REF`), a `direction`, and a `cabin_class` of
        `STANDARD`, `PREMIUM`, or `CREW`."
        PRD §3.6: "Bags are checked by a `TerminalOperator` against the
        passenger movement that owns them: the payload names the
        `manifest_entry_id` and a `tag_code` that must be unique within the
        port call, with duplicates rejected as `ERR_DUPLICATE_TAG`."

        Design: Corner/validations/duplicate_operational_keys_rejected
        """
        ctx = setup_scheduled_call()
        pc = ctx["port_call"]
        ves = ctx["vessel"]["id"]
        entry = add_manifest_entry(pc["id"], ves, "P1", direction="EMBARK")
        check_bag(entry["id"], tag_code="TAG1")

        err1 = api.create_manifest_entry(
            pc["id"],
            {"passenger_ref": "P1", "direction": "DEBARK",
             "cabin_class": "PREMIUM"},
            make_vessel_agent_headers(ves))
        validate_error(err1, ApiErrorId.ERR_DUPLICATE_MANIFEST_REF)

        err2 = api.create_baggage_item(
            {"manifest_entry_id": entry["id"], "tag_code": "TAG1"}, OPERATOR)
        validate_error(err2, ApiErrorId.ERR_DUPLICATE_TAG)
