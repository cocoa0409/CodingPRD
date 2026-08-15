"""Visit voids, line removal, and returns: reservation release and the
compensating stock / allowance-ledger invariants."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_lines,
    checkin_visit,
    create_partner,
    get_client,
    get_item,
    get_zone,
    issue_voucher,
    register_client,
    setup_stocked_items,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}
GOOD_BOTTOMS = {"category": "ADULT_BOTTOMS", "season": "ALL_SEASON",
                "quality_grade": "GOOD"}


class TestVisitVoid:
    def test_visit_void_releases_reservations(self, api):
        """PRD: "A `VolunteerLead` or `ProgramAdmin` may instead void a visit
        that is still `CHECKED_IN`, moving it to `VOIDED`. Every `ACTIVE` line on
        the visit becomes `RELEASED`, and each item those lines held returns from
        `RESERVED` to `STOCKED` with its `reserved_visit_id` cleared. A voucher
        redeemed on a voided visit stays `REDEEMED`; there is no un-redemption."

        Design: Corner/state_machines/visit_void_releases_reservations
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="ZV", capacity_items=5)
        headers = env["staff"]["headers"]
        partner = create_partner("Agency", 5)
        client = register_client("C", 2, None, headers)
        voucher = issue_voucher(partner, client["id"], bonus_items=2,
                                expires_at="2026-12-01T00:00:00Z")
        visit = checkin_visit(client["id"], headers, voucher_id=voucher["id"])
        line = add_line(visit["id"], env["items"][0]["id"], headers)

        voided = validate_success(api.void_visit(visit["id"], ADMIN), 200)
        assert voided["status"] == "VOIDED"

        line = validate_success(api.get_distribution_line(line["id"], ADMIN), 200)
        assert line["status"] == "RELEASED"
        item = get_item(env["items"][0]["id"])
        assert item["status"] == "STOCKED", "the reservation is released to the shelf"
        assert item["reserved_visit_id"] is None
        voucher = validate_success(api.get_voucher(voucher["id"], ADMIN), 200)
        assert voucher["status"] == "REDEEMED", "voiding does not un-redeem"


class TestReturnItemConservation:
    def test_checkout_and_return_conserve_zone_stock(self, api):
        """PRD: "Returning a line requires the line to be `DISTRIBUTED`
        (otherwise `ERR_INVALID_STATE`); the line becomes `RETURNED`, and the
        item moves from `DISTRIBUTED` back to `STOCKED` in the zone recorded as
        its `distributed_from_zone_id`, deliberately bypassing the capacity check
        so a return can never be stranded by a since-filled shelf. The item's
        `stocked_at` is refreshed, the zone's `current_stock` is incremented and
        its `posture` recomputed"

        Design: Difficulty/compensating_invariant/checkout_return_item_conservation
        """
        env = setup_stocked_items([dict(GOOD_TOPS) for _ in range(3)],
                                  zone_code="ZF", capacity_items=5)
        headers = env["staff"]["headers"]
        zone_id = env["zone"]["id"]
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        line1 = add_line(visit["id"], env["items"][0]["id"], headers)
        add_line(visit["id"], env["items"][1]["id"], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)
        assert get_zone(zone_id)["current_stock"] == 1, "2 distributed out of 3 stocked"

        returned = validate_success(api.return_distribution_line(line1["id"], headers),
                                    200)
        assert returned["status"] == "RETURNED"
        assert get_zone(zone_id)["current_stock"] == 2, (
            "the compensating action restores stock")

    def test_return_restores_item_to_origin_zone(self, api):
        """PRD: "the line becomes `RETURNED`, and the item moves from
        `DISTRIBUTED` back to `STOCKED` in the zone recorded as its
        `distributed_from_zone_id`, deliberately bypassing the capacity check so
        a return can never be stranded by a since-filled shelf."
        PRD: "A storage zone's `current_stock` counts the items physically
        assigned to it — those whose `storage_zone_id` names the zone and whose
        status is `STOCKED` or `RESERVED`."

        Design: Difficulty/compensating_invariant/checkout_return_item_conservation
        """
        env = setup_stocked_items([dict(GOOD_TOPS) for _ in range(3)],
                                  zone_code="ZF", capacity_items=5)
        headers = env["staff"]["headers"]
        zone_id = env["zone"]["id"]
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        line1 = add_line(visit["id"], env["items"][0]["id"], headers)
        add_line(visit["id"], env["items"][1]["id"], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)

        validate_success(api.return_distribution_line(line1["id"], headers), 200)

        item1 = get_item(env["items"][0]["id"])
        assert item1["status"] == "STOCKED"
        assert item1["storage_zone_id"] == zone_id, "returned to its origin zone"
        item2 = get_item(env["items"][1]["id"])
        assert item2["status"] == "DISTRIBUTED"
        # Conservation: 2 on the shelf + 1 distributed + 0 elsewhere == 3 created.
        zone = get_zone(zone_id)
        assert zone["current_stock"] == 2
        distributed = sum(
            1 for item in (item1, item2, get_item(env["items"][2]["id"]))
            if item["status"] == "DISTRIBUTED")
        assert zone["current_stock"] + distributed == 3


class TestReturnAllowanceLedger:
    def test_return_decrements_items_in_30d(self, api):
        """PRD: "Two rolling counters are maintained on the client record:
        `visits_in_30d`, the number of the client's own visits that reached
        `CHECKED_OUT` with a `checked_out_at` inside the trailing 30 days, and
        `items_in_30d`, the number of lines in `DISTRIBUTED` status on those
        in-window visits."
        PRD: "The item's `stocked_at` is refreshed, the zone's `current_stock` is
        incremented and its `posture` recomputed, and the client's `items_in_30d`
        is recomputed — a returned line no longer counts against the rolling
        30-day item tally."

        Design: Difficulty/compensating_invariant/checkout_return_allowance_ledger_conservation
        """
        env = setup_stocked_items([dict(GOOD_BOTTOMS) for _ in range(3)],
                                  zone_code="ZG", capacity_items=10)
        headers = env["staff"]["headers"]
        client = register_client("C", 3, None, headers)
        visit = checkin_visit(client["id"], headers)
        assert visit["general_allowance"] == 12, "min(24, min(16, 8 + 2*2))"
        lines = add_lines(visit["id"], [item["id"] for item in env["items"]], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)
        client = get_client(client["id"])
        assert client["items_in_30d"] == 3
        assert client["visits_in_30d"] == 1

        validate_success(api.return_distribution_line(lines[1]["id"], headers), 200)
        client = get_client(client["id"])
        assert client["items_in_30d"] == 2, "the return compensates the ledger"

    def test_return_does_not_refund_visit_counter(self, api):
        """PRD: "Two rolling counters are maintained on the client record:
        `visits_in_30d`, the number of the client's own visits that reached
        `CHECKED_OUT` with a `checked_out_at` inside the trailing 30 days, and
        `items_in_30d`, the number of lines in `DISTRIBUTED` status on those
        in-window visits."

        Design: Difficulty/compensating_invariant/checkout_return_allowance_ledger_conservation
        """
        env = setup_stocked_items([dict(GOOD_BOTTOMS) for _ in range(3)],
                                  zone_code="ZG", capacity_items=10)
        headers = env["staff"]["headers"]
        client = register_client("C", 3, None, headers)
        visit = checkin_visit(client["id"], headers)
        lines = add_lines(visit["id"], [item["id"] for item in env["items"]], headers)
        validate_success(api.checkout_visit(visit["id"], headers), 200)
        validate_success(api.return_distribution_line(lines[1]["id"], headers), 200)

        client = get_client(client["id"])
        assert client["visits_in_30d"] == 1, "the visit stayed CHECKED_OUT"
        assert client["items_in_30d"] == 2
