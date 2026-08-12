"""Weight tickets: collection gating, certification bubble-up, contamination
multiplier, bulk-bonus threshold, and credit-creation gates."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_driver_headers, make_resident_headers,
    new_zone, new_resident, order_kit, dispatch_kit, deliver_kit, new_delivered_kit,
    new_pickup, route_pickup, collect_pickup, certify_ticket, new_credit,
    file_report, adjudicate_report, read_pickup, read_ticket, read_resident,
    ctx_collected, ctx_certified, ctx_credit, ctx_settled,
    create_contamination_report_payload, mark_collected_payload,
)

OP = TEST_USERS["zone_operator_headers"]
DRV = TEST_USERS["driver_headers"]


class TestCollectRequiresDeliveredKit:
    def test_dispatched_but_not_delivered_kit_blocks_collection(self, api):
        """PRD §3.3: "Marking collected requires the pickup to be in `ROUTED`,
        requires the caller's `X-User-ID` to equal the pickup's stored
        `driver_id`, and requires the resident to have at least one `BagKit` in
        `DELIVERED` — if no kit has been delivered the collection is rejected with
        `ERR_BAGS_NOT_DELIVERED`."

        Design: Difficulty/cross_entity_state_dependency/collect_requires_delivered_bag_kit
        """
        zone = new_zone("Zone CE1")
        resident = new_resident(zone["id"], "Jill Jett", "jill@x.com")
        kit = order_kit(resident["id"], "BIN")
        dispatch_kit(kit["id"])  # DISPATCHED, never delivered
        pickup = new_pickup(resident["id"], bags_claimed=3)
        route_pickup(pickup["id"], "drv-1", "2026-05-10")

        resp = api_client.mark_collected(
            pickup["id"], mark_collected_payload(provisional_weight_kg=10.0),
            make_driver_headers("drv-1"),
        )
        validate_error(resp, ApiErrorId.ERR_BAGS_NOT_DELIVERED)
        assert read_pickup(pickup["id"])["status"] == "ROUTED"

    def test_delivery_unblocks_collection_and_retires_kit(self, api):
        """PRD §3.3: "On success the pickup transitions from `ROUTED` to
        `COLLECTED`, a new `WeightTicket` is created with `source_type` set to
        `PICKUP_REQUEST`, `source_id` set to the pickup's `id`, and `status` set
        to `PROVISIONAL`, the ticket's `projected_credit_cents` is computed per
        the provisional variant described in §3.4, and every `DELIVERED` kit
        belonging to the resident auto-transitions to `RETIRED`."

        Design: Difficulty/cross_entity_state_dependency/collect_requires_delivered_bag_kit
        """
        zone = new_zone("Zone CE1")
        resident = new_resident(zone["id"], "Jill Jett", "jill@x.com")
        kit = order_kit(resident["id"], "BIN")
        dispatch_kit(kit["id"])
        pickup = new_pickup(resident["id"], bags_claimed=3)
        route_pickup(pickup["id"], "drv-1", "2026-05-10")

        resp = api_client.mark_collected(
            pickup["id"], mark_collected_payload(provisional_weight_kg=10.0),
            make_driver_headers("drv-1"),
        )
        validate_error(resp, ApiErrorId.ERR_BAGS_NOT_DELIVERED)

        delivered = deliver_kit(kit["id"])
        assert delivered["status"] == "DELIVERED"

        ticket = collect_pickup(pickup["id"], "drv-1", 10.0)
        assert ticket["status"] == "PROVISIONAL"
        assert read_pickup(pickup["id"])["status"] == "COLLECTED"

        kits, _ = validate_paginated(api_client.list_resident_bag_kits(resident["id"], OP))
        by_id = {k["id"]: k for k in kits}
        assert by_id[kit["id"]]["status"] == "RETIRED", "collection auto-retires DELIVERED kits"


def test_collect_retires_all_delivered_kits(api):
    """PRD §3.2: "the system also auto-retires every `DELIVERED` kit belonging to
    a resident the moment any of their pickups is marked collected."

    Design: Corner/state_machines/collect_retires_delivered_kits
    """
    zone = new_zone("Zone SM7")
    resident = new_resident(zone["id"], "Zack Z", "zack@x.com")
    k1 = order_kit(resident["id"], "BAG")
    k2 = order_kit(resident["id"], "BIN")
    dispatch_kit(k1["id"])
    deliver_kit(k1["id"])
    dispatch_kit(k2["id"])
    deliver_kit(k2["id"])
    pickup = new_pickup(resident["id"], bags_claimed=2)
    route_pickup(pickup["id"], "drv-1", "2026-05-10")

    collect_pickup(pickup["id"], "drv-1", 9.0)

    kits, _ = validate_paginated(api_client.list_resident_bag_kits(resident["id"], OP))
    by_id = {k["id"]: k["status"] for k in kits}
    assert by_id[k1["id"]] == "RETIRED" and by_id[k2["id"]] == "RETIRED", (
        f"both DELIVERED kits must auto-retire on collection: {by_id}"
    )


def test_certify_bubbles_pickup_to_weighed(api):
    """PRD §3.5: "On success the ticket transitions to `CERTIFIED`, `certified_at`
    is stamped with the current logical clock, and — when the ticket's
    `source_type` is `PICKUP_REQUEST` — the source pickup bubbles up from
    `COLLECTED` to `WEIGHED`."
    PRD §2.10: "The server starts with the logical clock fixed at exactly
    `2026-05-01T00:00:00Z`, and the clock never falls back to wall-clock time
    thereafter."

    Design: Corner/state_machines/certify_bubbles_pickup_to_weighed
    """
    ctx = ctx_collected(zone_name="Zone SM5", resident_name="Xena X", resident_email="xena@x.com")

    ticket = certify_ticket(ctx["ticket"]["id"], 12.5, "RESALE")
    assert ticket["status"] == "CERTIFIED"
    assert ticket["certified_at"] is not None and ticket["certified_at"].startswith(
        "2026-05-01T00:00:00"
    ), f"certified_at must read the default logical clock, got {ticket['certified_at']}"
    assert read_pickup(ctx["pickup"]["id"])["status"] == "WEIGHED"


def test_contamination_minor_multiplier_result(api):
    """PRD §2.6: "The contamination multiplier is keyed by the highest upheld
    severity: `NONE` multiplies the base by 1.0, `MINOR` by 0.9, `MAJOR` by 0.5,
    and `SEVERE` by 0.0."
    PRD §3.7: "Its `applied_severity` snapshots the ticket's current
    `highest_upheld_severity`."
    PRD §3.6: "An `UPHELD` `MAJOR` or `SEVERE` report on a ticket whose
    `source_type` is `PICKUP_REQUEST` increments the source pickup's resident's
    `strikes` by one."

    Design: Corner/calculations/contamination_minor_multiplier_result
    """
    ctx = ctx_certified(zone_name="Zone C1", resident_name="Ed E", resident_email="ed@x.com",
                        certified_weight_kg=12.5, grade="RESALE")
    report = file_report(ctx["ticket"]["id"], "MINOR", notes="slightly damp")
    adjudicate_report(report["id"], "UPHELD")

    credit = new_credit(ctx["ticket"]["id"])
    # base 1500 (12.5 * 120) -> after_contam 1350 (x0.9) -> uncapped bonus 135 -> 1485
    assert credit["projected_cents"] == 1485, (
        f"MINOR multiplier 0.9 must apply at credit creation: expected 1485, got {credit['projected_cents']}"
    )
    assert credit["applied_severity"] == "MINOR"
    assert read_ticket(ctx["ticket"]["id"])["status"] == "CERTIFIED", "MINOR never quarantines"
    assert read_resident(ctx["resident"]["id"])["strikes"] == 0, "MINOR never strikes"


def test_bulk_bonus_threshold_jump(api):
    """PRD §2.6: "A load whose certified weight is at least 20.0 kilograms earns a
    flat bulk bonus of 500 cents; loads below that threshold earn no bonus."
    PRD §3.7: "Its `projected_cents` is computed by the final-variant formula
    below but with the sponsor bonus uncapped — that is, base plus contamination
    adjustment plus bulk bonus plus the uncapped ten-percent sponsor bonus."

    Design: Corner/calculations/bulk_bonus_threshold_jump
    """
    zone = new_zone("Zone C2")
    resident = new_resident(zone["id"], "Flo F", "flo@x.com")
    k1 = order_kit(resident["id"], "BAG")
    dispatch_kit(k1["id"])
    deliver_kit(k1["id"])
    k2 = order_kit(resident["id"], "BIN")
    dispatch_kit(k2["id"])

    p1 = new_pickup(resident["id"], "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", 1)
    p2 = new_pickup(resident["id"], "2026-05-10T12:30:00Z", "2026-05-10T14:00:00Z", 1)
    route_pickup(p1["id"], "drv-1", "2026-05-10")
    t1 = collect_pickup(p1["id"], "drv-1", 19.99)  # retires DELIVERED k1
    deliver_kit(k2["id"])
    route_pickup(p2["id"], "drv-1", "2026-05-10")
    t2 = collect_pickup(p2["id"], "drv-1", 20.0)

    certify_ticket(t1["id"], 19.99, "RECYCLE")
    certify_ticket(t2["id"], 20.0, "RECYCLE")

    c1 = new_credit(t1["id"])
    # base round(19.99*45)=900, no bulk (19.99 < 20.0), bonus 90 -> 990
    assert c1["projected_cents"] == 990, f"below threshold: expected 990, got {c1['projected_cents']}"
    c2 = new_credit(t2["id"])
    # base 900 + bulk 500 (>= 20.0 inclusive) + bonus 90 -> 1490
    assert c2["projected_cents"] == 1490, f"at threshold: expected 1490, got {c2['projected_cents']}"


def test_credit_create_with_open_report_rejected(api):
    """PRD §3.7: "No `OPEN` contamination report may exist on the ticket —
    otherwise the create is rejected with `ERR_OPEN_REPORTS_REMAIN`."

    Design: Corner/validations/credit_create_with_open_report_rejected
    """
    ctx = ctx_certified(zone_name="Zone V6", resident_name="Lou L", resident_email="lou@x.com")
    file_report(ctx["ticket"]["id"], "MAJOR")  # left OPEN

    resp = api_client.create_diversion_credit(ctx["ticket"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_OPEN_REPORTS_REMAIN)


def test_report_after_settle_window_closed(api):
    """PRD §3.6: "The report window is open only while the ticket is `CERTIFIED`
    and no `SETTLED` credit exists on it — filing against a `PROVISIONAL`,
    `QUARANTINED`, or `VOIDED` ticket, or against a ticket whose credit has
    already settled, is rejected with `ERR_REPORT_WINDOW_CLOSED`."

    Design: Corner/validations/report_after_settle_window_closed
    """
    ctx = ctx_settled(zone_name="Zone V7", resident_name="Meg M", resident_email="meg@x.com",
                      fund_cents=100000)

    resp = api_client.create_contamination_report(
        ctx["ticket"]["id"], create_contamination_report_payload(severity="MAJOR"),
        TEST_USERS["inspector_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)


def test_duplicate_credit_rejected(api):
    """PRD §3.7: "No non-`VOIDED` credit may already exist for the ticket — a
    duplicate attempt is rejected with `ERR_CREDIT_EXISTS`."

    Design: Corner/validations/duplicate_credit_rejected
    """
    ctx = ctx_credit(zone_name="Zone V5", resident_name="Kim K", resident_email="kim@x.com")

    resp = api_client.create_diversion_credit(ctx["ticket"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_CREDIT_EXISTS)

    credits, meta = validate_paginated(
        api_client.list_ticket_diversion_credits(ctx["ticket"]["id"], OP)
    )
    assert len(credits) == 1 and meta["total_count"] == 1, "exactly one non-voided credit per ticket"
