"""Centres, machines, accounts, stores and visits: transitions and their guards.

The network's machines are guarded by counters — machines installed, machines
out of service, containers in a bin — and their invalid transitions have to be
told apart from the counter refusals that look similar.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_stamped_at,
    make_center_headers,
    make_retailer_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestActivationNeedsAFleet:
    """A centre with no machine cannot open its doors."""

    def test_activation_is_refused_until_a_machine_is_installed(self, api):
        """The empty centre stays PROVISIONAL with an empty drawer, then activates.

        PRD: "Activation with `ACTIVATE` by a `ProgramAdmin` moves the centre
        `PROVISIONAL → OPERATIONAL` and requires `machine_count` to be at least 1; a centre
        with no machine installed is refused with `ERR_CENTER_HAS_NO_MACHINE`."

        PRD: "Activation copies `opening_cash_cents` into `cash_drawer_balance_cents` and
        clears `suspension_reason` to null."

        Design: Corner/state_machines/center_activate_without_machine_returns_center_has_no_machine
        """
        h.set_clock(api, INSTANT)
        center = h.create_center(
            api,
            site_name="Bend Redemption Center",
            accepted_materials=["PET_PLASTIC"],
            opening_cash_cents=50000,
        )

        response = api.post_center_status_change(
            center["id"], f.center_status_change_payload("ACTIVATE"), ADMIN_HEADERS
        )
        validate_error(
            response,
            ApiErrorId.ERR_CENTER_HAS_NO_MACHINE.value,
            expected_status=409,
        )

        refused = h.read_center(api, center["id"], ADMIN_HEADERS)
        assert refused["status"] == "PROVISIONAL"
        assert refused["cash_drawer_balance_cents"] == 0
        assert refused["machine_count"] == 0
        assert refused["version"] == 1

        h.install_machine(api, center["id"])
        activated = h.activate_center(api, center["id"])

        assert activated["status"] == "OPERATIONAL"
        assert activated["machine_count"] == 1
        assert activated["cash_drawer_balance_cents"] == 50000
        assert activated["suspension_reason"] is None
        assert activated["version"] == 3


class TestProvisionalCentreOffersOnlyActivation:
    """From PROVISIONAL no other centre action is declared."""

    def test_reinstate_close_and_suspend_are_all_invalid_from_provisional(self, api):
        """Three undeclared actions each report the centre-state error, not a guard error.

        PRD: "Requesting a centre action that is not declared from the centre's current
        `status` is refused with `ERR_INVALID_CENTER_STATE`."

        Design: Corner/state_machines/center_reinstate_and_close_from_provisional_are_invalid
        """
        h.set_clock(api, INSTANT)
        center = h.create_center(
            api,
            site_name="Bend Redemption Center",
            accepted_materials=["PET_PLASTIC"],
        )
        h.install_machine(api, center["id"])

        for action in ("REINSTATE", "CLOSE", "SUSPEND"):
            response = api.post_center_status_change(
                center["id"], f.center_status_change_payload(action), ADMIN_HEADERS
            )
            validate_error(
                response,
                ApiErrorId.ERR_INVALID_CENTER_STATE.value,
                expected_status=409,
            )

        stored = h.read_center(api, center["id"], ADMIN_HEADERS)
        assert stored["status"] == "PROVISIONAL"
        assert stored["suspension_reason"] is None
        assert stored["version"] == 2


class TestClosureCascades:
    """One CLOSE retires a fleet and frees the stores that leaned on the centre."""

    def test_close_retires_the_machines_and_reobligates_only_its_own_store(self, api):
        """Store A loses the exemption it held against the closed centre; store B keeps its own.

        PRD: "The cascades are, first, that every non-`RETIRED` machine of the centre moves
        to `RETIRED`; and second, that every store whose `nearest_center_id` names this centre
        moves `EXEMPT → OBLIGATED` and has `nearest_center_id`,
        `nearest_center_distance_miles` and `exemption_granted_at` cleared to null."

        PRD: "Each cascaded machine and each cascaded store is mutated in its own right,
        with `updated_at` refreshed and `version` incremented."

        Design: Corner/state_machines/center_close_retires_machines_and_reobligates_exempt_store
        """
        h.set_clock(api, INSTANT)
        center_a = h.create_center(
            api, site_name="Bend Redemption Center", x_miles=0.0, y_miles=0.0
        )
        machine_a1 = h.install_machine(api, center_a["id"], asset_tag="RVM-1001")
        machine_a2 = h.install_machine(
            api, center_a["id"], asset_tag="RVM-1002", accepted_material="ALUMINUM"
        )
        h.activate_center(api, center_a["id"])

        store_a = h.create_retailer(
            api, store_name="Bend Market", x_miles=1.0, y_miles=1.0, store_area_sqft=6000
        )
        h.exemption_action(
            api, store_a["id"], "CLAIM_EXEMPTION", make_retailer_headers(store_a["id"])
        )

        center_b = h.create_center(
            api, site_name="Redmond Redemption Center", x_miles=0.2, y_miles=0.0
        )
        machine_b1 = h.install_machine(api, center_b["id"], asset_tag="RVM-2001")
        h.activate_center(api, center_b["id"])

        store_b = h.create_retailer(
            api,
            store_name="Redmond Market",
            x_miles=0.2,
            y_miles=0.1,
            store_area_sqft=4000,
        )
        exempt_b = h.exemption_action(
            api, store_b["id"], "CLAIM_EXEMPTION", make_retailer_headers(store_b["id"])
        )
        assert exempt_b["nearest_center_id"] == center_b["id"]

        closed = h.center_status_change(api, center_a["id"], "CLOSE")

        assert closed["status"] == "CLOSED"
        assert closed["machine_count"] == 0
        headers_a = make_center_headers(center_a["id"])
        assert h.read_machine(api, machine_a1["id"], headers_a)["status"] == "RETIRED"
        assert h.read_machine(api, machine_a2["id"], headers_a)["status"] == "RETIRED"

        freed = h.read_retailer(api, store_a["id"], ADMIN_HEADERS)
        assert freed["obligation_status"] == "OBLIGATED"
        assert freed["nearest_center_id"] is None
        assert freed["nearest_center_distance_miles"] is None
        assert freed["exemption_granted_at"] is None
        assert freed["version"] == 3

        untouched = h.read_retailer(api, store_b["id"], ADMIN_HEADERS)
        assert untouched["obligation_status"] == "EXEMPT"
        assert untouched["nearest_center_id"] == center_b["id"]
        assert untouched["version"] == 2

        headers_b = make_center_headers(center_b["id"])
        assert h.read_machine(api, machine_b1["id"], headers_b)["status"] == "IDLE"
        assert h.read_center(api, center_b["id"], headers_b)["status"] == "OPERATIONAL"


class TestFleetDownSuspension:
    """The centre follows its fleet down only when the last machine goes."""

    def test_the_second_machine_suspends_the_centre_and_blocks_reinstatement(self, api):
        """One machine out leaves the centre open; both out suspends it and locks REINSTATE.

        PRD: "A third path is not requested by anyone — when a machine event leaves every
        non-`RETIRED` machine of the centre in `OUT_OF_SERVICE`, that is, when
        `out_of_service_machine_count` equals `machine_count` and `machine_count` is at least
        1, the server itself moves the centre `OPERATIONAL → SUSPENDED` with
        `suspension_reason` `MACHINE_FLEET_DOWN`."

        PRD: "Reinstatement with `REINSTATE`, a `ProgramAdmin` prerogative, moves the centre
        `SUSPENDED → OPERATIONAL` and clears `suspension_reason` to null, but only while
        `out_of_service_machine_count` is strictly less than `machine_count`; asking to
        reinstate a site whose whole fleet is still down is refused with
        `ERR_MACHINE_FLEET_DOWN`."

        Design: Corner/state_machines/whole_machine_fleet_out_of_service_suspends_center_and_blocks_reinstate
        """
        h.set_clock(api, INSTANT)
        center = h.create_center(
            api,
            site_name="Bend Redemption Center",
            accepted_materials=["ALUMINUM", "PET_PLASTIC"],
        )
        first = h.install_machine(api, center["id"], asset_tag="RVM-1001")
        second = h.install_machine(
            api, center["id"], asset_tag="RVM-1002", accepted_material="ALUMINUM"
        )
        h.activate_center(api, center["id"])
        headers = make_center_headers(center["id"])

        h.machine_event(api, first["id"], "TAKE_OUT_OF_SERVICE", headers)
        assert h.read_machine(api, first["id"], headers)["status"] == "OUT_OF_SERVICE"
        half_down = h.read_center(api, center["id"], headers)
        assert half_down["status"] == "OPERATIONAL"
        assert half_down["out_of_service_machine_count"] == 1
        assert half_down["suspension_reason"] is None

        h.machine_event(api, second["id"], "TAKE_OUT_OF_SERVICE", headers)
        all_down = h.read_center(api, center["id"], headers)
        assert all_down["status"] == "SUSPENDED"
        assert all_down["machine_count"] == 2
        assert all_down["out_of_service_machine_count"] == 2
        assert all_down["suspension_reason"] == "MACHINE_FLEET_DOWN"

        refused = api.post_center_status_change(
            center["id"], f.center_status_change_payload("REINSTATE"), ADMIN_HEADERS
        )
        validate_error(
            refused, ApiErrorId.ERR_MACHINE_FLEET_DOWN.value, expected_status=409
        )

        returned = h.machine_event(api, second["id"], "RETURN_TO_SERVICE", headers)
        assert returned["status"] == "IDLE"
        assert returned["jam_count_today"] == 0
        assert returned["jam_day"] is None
        assert h.read_center(api, center["id"], headers)[
            "out_of_service_machine_count"
        ] == 1

        reinstated = h.center_status_change(api, center["id"], "REINSTATE")
        assert reinstated["status"] == "OPERATIONAL"
        assert reinstated["suspension_reason"] is None


class TestBinFullCycle:
    """A bin declaration is legitimate only while the bin is actually full."""

    def test_emptying_the_bin_makes_the_same_declaration_premature(self, api):
        """Counting fills the 50-container bin; after EMPTY_BIN the declaration is refused.

        PRD: "On a machine-counted visit the whole `raw_accepted_count` is added to the
        serving machine's `bin_filled_count`, which is what eventually makes a bin-full
        declaration legitimate."

        PRD: "Declaring a bin full moves the machine `IDLE → BIN_FULL` and is only accepted
        when `bin_filled_count` has reached or passed `bin_capacity_containers`; a premature
        declaration is refused with `ERR_INVALID_MACHINE_STATE`. Emptying the bin moves the
        machine `BIN_FULL → IDLE` and resets `bin_filled_count` to 0."

        Design: Corner/state_machines/bin_full_cycle_zeroes_bin_filled_count_and_then_refuses_reentry
        """
        world = h.build_world(
            api,
            center_overrides={
                "site_name": "Bend Redemption Center",
                "accepted_materials": ["PET_PLASTIC"],
                "accepts_all_materials": False,
            },
            machine_overrides={"bin_capacity_containers": 50},
        )
        h.create_counted_center_visit(
            api, world.center_id, world.machine_id, world.product_id, [50]
        )

        filled = h.read_machine(api, world.machine_id, world.center_headers)
        assert filled["bin_filled_count"] == 50
        assert filled["status"] == "IDLE"

        declared = h.machine_event(
            api, world.machine_id, "BIN_FULL", world.center_headers
        )
        assert declared["status"] == "BIN_FULL"
        assert declared["bin_filled_count"] == 50

        emptied = h.machine_event(
            api, world.machine_id, "EMPTY_BIN", world.center_headers
        )
        assert emptied["status"] == "IDLE"
        assert emptied["bin_filled_count"] == 0

        response = api.post_machine_event(
            world.machine_id,
            f.machine_event_payload("BIN_FULL"),
            world.center_headers,
        )
        validate_error(
            response,
            ApiErrorId.ERR_INVALID_MACHINE_STATE.value,
            expected_status=409,
        )

        unchanged = h.read_machine(api, world.machine_id, world.center_headers)
        assert unchanged["status"] == "IDLE"
        assert unchanged["bin_filled_count"] == 0
        assert unchanged["version"] == emptied["version"]


class TestSecondAccountClosure:
    """Closing a closed account is an undeclared transition, not a standing refusal."""

    def test_the_second_close_reports_the_account_state_and_does_not_bump_the_version(
        self, api
    ):
        """CLOSE succeeds once, disenrols the holder, and is then undeclared.

        PRD: "On success `bag_drop_enrolled` is set to false in both branches. Requesting a
        status change that is not declared from the account's current `status` — closing a
        `CLOSED` account, or flagging a `FLAGGED` one — is refused with
        `ERR_INVALID_ACCOUNT_STATE`."

        Design: Corner/state_machines/closing_an_already_closed_account_returns_invalid_account_state
        """
        h.set_clock(api, INSTANT)
        account = h.create_account(api, bag_drop_enrolled=True)

        closed = validate_success(
            api.post_account_status_change(
                account["id"],
                f.account_status_change_payload("CLOSE"),
                ADMIN_HEADERS,
            )
        )
        assert closed["status"] == "CLOSED"
        assert closed["bag_drop_enrolled"] is False
        assert closed["version"] == 2

        response = api.post_account_status_change(
            account["id"], f.account_status_change_payload("CLOSE"), ADMIN_HEADERS
        )
        validate_error(
            response,
            ApiErrorId.ERR_INVALID_ACCOUNT_STATE.value,
            expected_status=409,
        )

        assert h.read_account(api, account["id"], ADMIN_HEADERS)["version"] == 2


class TestRepeatedExemptionAction:
    """An exemption action undeclared from the store's standing never re-runs the search."""

    def test_a_second_claim_and_a_revoke_on_an_obligated_peer_are_both_refused(
        self, api
    ):
        """The granted exemption is not re-stamped, and the peer store keeps its obligation.

        PRD: "On success the server writes `nearest_center_id` and
        `nearest_center_distance_miles` from the selected centre and stamps
        `exemption_granted_at` with the current logical instant."

        PRD: "Requesting an exemption action not declared from the store's current
        `obligation_status` — claiming while already `EXEMPT`, or revoking while already
        `OBLIGATED` — is refused with `ERR_INVALID_OBLIGATION_STATE`."

        Design: Corner/state_machines/claiming_exemption_twice_returns_invalid_obligation_state
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api, {"site_name": "Bend Redemption Center", "x_miles": 0.0, "y_miles": 0.0}
        )
        center = fleet["center"]
        store_a = h.create_retailer(
            api, store_name="Bend Market", x_miles=1.0, y_miles=1.0, store_area_sqft=6000
        )
        store_b = h.create_retailer(
            api,
            store_name="Bend Grocery",
            x_miles=0.5,
            y_miles=0.5,
            store_area_sqft=3000,
        )

        exempt = h.exemption_action(
            api, store_a["id"], "CLAIM_EXEMPTION", make_retailer_headers(store_a["id"])
        )
        assert exempt["obligation_status"] == "EXEMPT"
        assert exempt["nearest_center_id"] == center["id"]
        assert exempt["nearest_center_distance_miles"] == 1.41
        assert_stamped_at(exempt["exemption_granted_at"], INSTANT)
        assert exempt["version"] == 2

        second_claim = api.post_exemption_action(
            store_a["id"],
            f.exemption_action_payload("CLAIM_EXEMPTION"),
            make_retailer_headers(store_a["id"]),
        )
        validate_error(
            second_claim,
            ApiErrorId.ERR_INVALID_OBLIGATION_STATE.value,
            expected_status=409,
        )
        assert h.read_retailer(api, store_a["id"], ADMIN_HEADERS)["version"] == 2

        revoke = api.post_exemption_action(
            store_b["id"], f.exemption_action_payload("REVOKE_EXEMPTION"), ADMIN_HEADERS
        )
        validate_error(
            revoke,
            ApiErrorId.ERR_INVALID_OBLIGATION_STATE.value,
            expected_status=409,
        )

        peer = h.read_retailer(api, store_b["id"], ADMIN_HEADERS)
        assert peer["obligation_status"] == "OBLIGATED"
        assert peer["nearest_center_id"] is None
        assert peer["version"] == 1


class TestCountedIsTerminalForCounting:
    """COUNTED closes the counting dimension while payout stays live."""

    def test_a_second_close_and_a_late_lot_are_both_refused(self, api, world):
        """The current expected_visit_version does not reopen a closed count.

        PRD: "The visit's `count_status` matches the requested transition's originating
        state → otherwise `ERR_INVALID_COUNT_STATE` (HTTP 409). Applies to lot addition and
        close-count."

        PRD: "Adding a lot to a visit whose `count_status` is neither `OPEN` nor `COUNTING` —
        a `JAM_HOLD` visit awaiting a jam clear, or an already `COUNTED` visit — is refused
        with `ERR_INVALID_COUNT_STATE`."

        Design: Corner/state_machines/second_close_count_and_late_lot_return_invalid_count_state
        """
        visit = h.open_center_machine_visit(
            api, world.center_id, world.machine_id
        )
        h.add_lot(
            api,
            visit["id"],
            world.product_id,
            100,
            world.center_headers,
            out_of_state_marked_quantity=0,
            contaminated_quantity=0,
        )
        counted = h.close_count(api, visit["id"], world.center_headers)

        validate_error(
            api.close_count(visit["id"], world.center_headers),
            ApiErrorId.ERR_INVALID_COUNT_STATE.value,
            expected_status=409,
        )
        validate_error(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(world.product_id, 5, counted["version"]),
                world.center_headers,
            ),
            ApiErrorId.ERR_INVALID_COUNT_STATE.value,
            expected_status=409,
        )

        stored = h.read_visit(api, visit["id"], world.center_headers)
        assert stored["count_status"] == "COUNTED"
        assert stored["payout_status"] == "PENDING"
        assert stored["presented_total"] == 100
        assert stored["payable_count"] == 100
        assert stored["payout_cents"] == 1000
        assert_stamped_at(stored["counted_at"], INSTANT)
        assert stored["version"] == counted["version"]

        _, meta = validate_paginated(
            api.list_visit_lots(visit["id"], world.center_headers)
        )
        assert meta["total_count"] == 1


class TestWithholdAndReleaseLeaveTheCountAlone:
    """The payout axis can walk PENDING → WITHHELD → PENDING → APPROVED on its own."""

    def test_the_valuation_is_never_recomputed_while_the_payout_axis_moves(
        self, api, world
    ):
        """Three payout actions later the count is still COUNTED with the same figures.

        PRD: "A visit carries two independent state dimensions, and it is worth being
        explicit about that: `count_status` moves over `OPEN`, `COUNTING`, `JAM_HOLD` and
        `COUNTED`, terminating at `COUNTED`, while `payout_status` moves over `PENDING`,
        `WITHHELD`, `APPROVED`, `PAID` and `REVERSED`, terminating at `REVERSED`."

        PRD: "Releasing sets `fraud_hold` back to false and `withhold_reason` back to null,
        and recomputes the centre's `withheld_visit_count`."

        Design: Corner/state_machines/withhold_then_release_hold_leaves_the_count_dimension_untouched
        """
        counted = h.create_counted_center_visit(
            api, world.center_id, world.machine_id, world.product_id, [100]
        )
        assert counted["payout_cents"] == 1000

        withheld = h.payout_action(
            api, counted["id"], "WITHHOLD", world.center_headers, "manual review"
        )
        assert withheld["payout_status"] == "WITHHELD"
        assert withheld["count_status"] == "COUNTED"

        released = h.payout_action(api, counted["id"], "RELEASE_HOLD", ADMIN_HEADERS)
        assert released["payout_status"] == "PENDING"
        assert released["withhold_reason"] is None
        assert released["count_status"] == "COUNTED"

        approved = h.payout_action(
            api, counted["id"], "APPROVE", world.center_headers
        )
        assert approved["payout_status"] == "APPROVED"
        assert approved["count_status"] == "COUNTED"

        for stage in (withheld, released, approved):
            assert stage["payable_count"] == 100
            assert stage["payout_cents"] == 1000
            assert_stamped_at(stage["counted_at"], INSTANT)

        center = h.read_center(api, world.center_id, world.center_headers)
        assert center["cash_drawer_balance_cents"] == 50000
        assert center["withheld_visit_count"] == 0
