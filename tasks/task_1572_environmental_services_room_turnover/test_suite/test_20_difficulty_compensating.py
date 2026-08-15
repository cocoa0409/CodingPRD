"""Difficulty queue A — compensating_invariant instances (supply reserve/release;
staff active-count conservation)."""
from test_helpers import (
    CLOCK_T0800,
    api_client,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_bed,
    create_request,
    start_request,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


class TestSupplyReserveReleaseConservesQuantities:
    def test_reserve_then_release_restores_on_hand_and_reserved(self, api):
        """PRD §3.5: "Cancelling a started clean is the abort path. A
        dispatcher cancelling an `IN_PROGRESS` request releases the reservation
        without consuming anything: `supply_reserved` flips to false and each
        reserved quantity drops, but `on_hand_quantity` is untouched and no
        ledger entries are written, since nothing was used."
        PRD §3.5: "On success the request ... sets `supply_reserved` true,
        raises each bill-of-materials item's `reserved_quantity` by its line
        quantity."

        Design: Difficulty/compensating_invariant/supply_reserve_release_conserves_quantities
        """
        ctx = setup_basic_scenario()
        sd = ctx["supplies"]["DISINFECTANT"]
        sc = ctx["supplies"]["CLOTH"]

        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])

        mid_d = get_success_data(api.get_supply_item(sd["id"], ANY))
        assert mid_d["on_hand_quantity"] == 100
        assert mid_d["reserved_quantity"] == 2

        # Cancel from IN_PROGRESS releases without consuming.
        get_success_data(api.cancel_clean_request(req["id"], DISPATCHER))
        after_d = get_success_data(api.get_supply_item(sd["id"], ANY))
        assert after_d["on_hand_quantity"] == 100
        assert after_d["reserved_quantity"] == 0
        after_c = get_success_data(api.get_supply_item(sc["id"], ANY))
        assert after_c["on_hand_quantity"] == 200
        assert after_c["reserved_quantity"] == 0

    def test_reserve_then_consume_debits_both_fields(self, api):
        """PRD §3.5: "Completion stamps `completed_at`, ... and settles the
        supply reservation: `supply_reserved` flips to false, and for each
        bill-of-materials line the item's `reserved_quantity` drops by the line
        quantity while its `on_hand_quantity` drops by the same amount, each
        drop materialized as a `CONSUME` ledger entry carrying the request's
        `clean_request_id`."
        PRD §2.9: "A supply item's `on_hand_quantity` is, at all times, the sum
        of the `quantity_delta` values across every ledger entry recorded for
        that item."

        Design: Difficulty/compensating_invariant/supply_reserve_release_conserves_quantities
        """
        ctx = setup_basic_scenario()
        sd = ctx["supplies"]["DISINFECTANT"]
        sc = ctx["supplies"]["CLOTH"]
        bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

        req = create_request(bed2["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T08:45:00Z")
        complete_request(req["id"], ctx["tech"]["id"])

        d = get_success_data(api.get_supply_item(sd["id"], ANY))
        assert d["on_hand_quantity"] == 98
        assert d["reserved_quantity"] == 0
        c = get_success_data(api.get_supply_item(sc["id"], ANY))
        assert c["on_hand_quantity"] == 196
        assert c["reserved_quantity"] == 0

        entries, _ = validate_paginated(
            api.list_supply_ledger_entries(ANY, params={"supply_item_id": sd["id"]})
        )
        total = sum(e["quantity_delta"] for e in entries)
        assert total == 98


class TestStaffActiveCountAssignUnassignConserved:
    def test_assign_unassign_pair_conserves_active_count(self, api):
        """PRD §3.4: "A successful assignment stamps `assigned_staff_id`, sets
        the planned window, raises the staff member's derived
        `active_clean_count` — the count of their requests in `ASSIGNED` or
        `IN_PROGRESS` — by one."
        PRD §3.4: "**Unassigning** returns an `ASSIGNED` request to `QUEUED`,
        clearing `assigned_staff_id` and the planned window, dropping the staff
        member's active count by one in compensation, and incrementing the
        request's `version`."

        Design: Difficulty/compensating_invariant/staff_active_count_assign_unassign_conserved
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

        before = get_success_data(api.get_staff(tech["id"], ANY))
        assert before["active_clean_count"] == 0

        r1 = create_request(ctx["bed"]["id"], "ROUTINE")
        r2 = create_request(bed2["id"], "ROUTINE")
        assign_request(r1["id"], tech["id"], planned_start_at="2026-08-01T09:00:00Z")
        assign_request(r2["id"], tech["id"], planned_start_at="2026-08-01T10:00:00Z")
        mid = get_success_data(api.get_staff(tech["id"], ANY))
        assert mid["active_clean_count"] == 2

        get_success_data(api.unassign_clean_request(r1["id"], DISPATCHER))
        after = get_success_data(api.get_staff(tech["id"], ANY))
        assert after["active_clean_count"] == 1

        r1_after = get_success_data(api.get_clean_request(r1["id"], ANY))
        assert r1_after["status"] == "QUEUED"
        assert r1_after["assigned_staff_id"] is None
        r2_after = get_success_data(api.get_clean_request(r2["id"], ANY))
        assert r2_after["status"] == "ASSIGNED"

    def test_derived_count_equals_live_filtered_query(self, api):
        """PRD §3.4: "raises the staff member's derived `active_clean_count` —
        the count of their requests in `ASSIGNED` or `IN_PROGRESS` — by one."
        PRD §3.3: "the queue listing also filters by `bed_id`, `status`,
        `assigned_staff_id`, and `priority_tier`."

        Design: Difficulty/compensating_invariant/staff_active_count_assign_unassign_conserved
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        bed2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")

        r1 = create_request(ctx["bed"]["id"], "ROUTINE")
        r2 = create_request(bed2["id"], "ROUTINE")
        assign_request(r1["id"], tech["id"], planned_start_at="2026-08-01T09:00:00Z")
        assign_request(r2["id"], tech["id"], planned_start_at="2026-08-01T10:00:00Z")
        get_success_data(api.unassign_clean_request(r1["id"], DISPATCHER))

        staff = get_success_data(api.get_staff(tech["id"], ANY))
        listed, meta = validate_paginated(
            api.list_clean_requests(
                ANY, params={"assigned_staff_id": tech["id"], "status": "ASSIGNED"}
            )
        )
        assert len(listed) == 1
        assert listed[0]["id"] == r2["id"]
        assert staff["active_clean_count"] == len(listed)
