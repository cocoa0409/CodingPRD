"""Cascading penalties (adjudication and operator void) and reporting-period
windows, close gating, and frozen aggregates."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    new_zone, new_resident, new_delivered_kit, new_pickup, route_pickup,
    collect_pickup, certify_ticket, new_credit, finalize_credit, settle_credit,
    new_fund, new_dropbox, post_reading, collect_box, file_report,
    adjudicate_report, run_selector, accept_assignment, complete_assignment,
    new_reporting_period, set_clock, deliver_kit, order_kit, dispatch_kit,
    read_ticket, read_credit, read_fund, read_partner, read_pickup, read_resident,
    read_period, create_reporting_period_payload,
    ctx_finalized, ctx_certified,
    assert_fund_ledger_invariant,
)

OP = TEST_USERS["zone_operator_headers"]


class TestSevereAdjudicationCascade:
    def _setup(self):
        """Partner completes the assignment; fund holds a FINALIZED credit of 1650."""
        ctx = ctx_finalized(zone_name="Zone TC1", resident_name="Eli Ebb",
                            resident_email="eli@x.com", fund_cents=100000,
                            certified_weight_kg=12.5, grade="RESALE",
                            partner={"name": "BrandBack", "partner_type": "BRAND",
                                     "accepted_grades": ["RESALE"], "capacity_kg": 1000})
        a = run_selector(ctx["ticket"]["id"])
        accept_assignment(a["id"], ctx["partner"]["id"])
        complete_assignment(a["id"], ctx["partner"]["id"])
        ctx["report"] = file_report(ctx["ticket"]["id"], "SEVERE", notes="oil-soaked bale")
        return ctx

    def test_ticket_quarantined_and_credit_voided(self, api):
        """PRD §3.6: "When a `SEVERE` report is upheld on a `CERTIFIED` ticket,
        the ticket transitions from `CERTIFIED` to `QUARANTINED`."
        PRD §3.6: "Any `DiversionCredit` on the ticket in `PROVISIONAL`,
        `DISPUTED`, or `FINALIZED` transitions to `VOIDED`; if the credit had
        `has_hold` set to true, the sponsor-fund hold is released by reducing the
        fund's `held_cents` by `gross_cents` and raising `available_cents` by the
        same amount, and `has_hold` flips to false."

        Design: Difficulty/transitive_cascade/severe_adjudication_ticket_credit_fund_cascade
        """
        ctx = self._setup()
        report = adjudicate_report(ctx["report"]["id"], "UPHELD")
        assert report["status"] == "ADJUDICATED"
        assert report["outcome"] == "UPHELD"

        assert read_ticket(ctx["ticket"]["id"])["status"] == "QUARANTINED"
        credit = read_credit(ctx["credit"]["id"])
        assert credit["status"] == "VOIDED", "credit voided by the ticket quarantine"
        assert credit["has_hold"] is False

    def test_fund_released_partner_quarantined_resident_struck(self, api):
        """PRD §3.6: "Any partner holding an `ACCEPTED` or `COMPLETED` assignment
        on this ticket transitions to `QUARANTINED` from either `ELIGIBLE` or
        `SUSPENDED`."
        PRD §3.6: "An `UPHELD` `MAJOR` or `SEVERE` report on a ticket whose
        `source_type` is `PICKUP_REQUEST` increments the source pickup's
        resident's `strikes` by one."
        PRD §2.8: "Voiding or quarantining a credit releases the hold:
        `held_cents` decreases by `gross_cents` and `available_cents` rises by the
        same amount."

        Design: Difficulty/transitive_cascade/severe_adjudication_ticket_credit_fund_cascade
        """
        ctx = self._setup()
        adjudicate_report(ctx["report"]["id"], "UPHELD")

        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0 and fund["available_cents"] == 100000
        assert_fund_ledger_invariant(fund)
        assert read_partner(ctx["partner"]["id"])["status"] == "QUARANTINED"
        resident = read_resident(ctx["resident"]["id"])
        assert resident["strikes"] == 1
        assert resident["status"] == "ACTIVE"


class TestTicketVoidCascade:
    def _setup(self):
        return ctx_finalized(zone_name="Zone TC2", resident_name="Fay Fenn",
                             resident_email="fay@x.com", fund_cents=100000,
                             certified_weight_kg=12.5, grade="RESALE")

    def test_void_cascades_to_credit(self, api):
        """PRD §3.6: "The same cascade shape applies when a `ZoneOperator` voids a
        ticket directly. Any non-settled credit on the ticket transitions to
        `VOIDED` with the hold release described above, and any `PENDING`
        assignment transitions to `DECLINED` with `decline_reason` set to
        `SYSTEM_QUARANTINE`."
        PRD §3.5: "Voiding is permitted from either `CERTIFIED` or `QUARANTINED`
        and is rejected with `ERR_INVALID_STATE` from any other state"

        Design: Difficulty/transitive_cascade/ticket_void_credit_fund_release_cascade
        """
        ctx = self._setup()
        ticket = validate_success(api_client.void_ticket(ctx["ticket"]["id"], OP))
        assert ticket["status"] == "VOIDED"

        credit = read_credit(ctx["credit"]["id"])
        assert credit["status"] == "VOIDED"
        assert credit["has_hold"] is False

    def test_void_restores_fund_and_leaves_pickup_weighed(self, api):
        """PRD §2.8: "Voiding or quarantining a credit releases the hold:
        `held_cents` decreases by `gross_cents` and `available_cents` rises by the
        same amount."
        PRD §3.5: "On success the ticket transitions to `CERTIFIED`,
        `certified_at` is stamped with the current logical clock, and — when the
        ticket's `source_type` is `PICKUP_REQUEST` — the source pickup bubbles up
        from `COLLECTED` to `WEIGHED`."

        Design: Difficulty/transitive_cascade/ticket_void_credit_fund_release_cascade
        """
        ctx = self._setup()
        api_client.void_ticket(ctx["ticket"]["id"], OP)

        fund = read_fund(ctx["fund"]["id"])
        assert fund["held_cents"] == 0
        assert fund["paid_cents"] == 0
        assert fund["available_cents"] == 100000, "hold release fully restores the fund"
        assert_fund_ledger_invariant(fund)
        assert read_pickup(ctx["pickup"]["id"])["status"] == "WEIGHED", (
            "no bubble-up revert is declared for a ticket void"
        )


def test_period_overlap_rejected_adjacency_allowed(api):
    """PRD §3.8: "The new period's half-open window — beginning at `period_start`
    inclusive and ending at `period_end` exclusive — must not overlap any other
    period of the same zone. Adjacency is permitted: a prior period whose
    `period_end` equals the new period's `period_start` does not conflict. Any
    true overlap is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Corner/validations/period_overlap_rejected_adjacency_allowed
    """
    zone = new_zone("Zone V9")
    new_reporting_period(zone["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")

    resp = api_client.create_reporting_period(
        zone["id"],
        create_reporting_period_payload(
            period_start="2026-05-15T00:00:00Z", period_end="2026-06-15T00:00:00Z"
        ),
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)

    adjacent = validate_success(api_client.create_reporting_period(
        zone["id"],
        create_reporting_period_payload(
            period_start="2026-06-01T00:00:00Z", period_end="2026-07-01T00:00:00Z"
        ),
        OP,
    ), 201)
    assert adjacent["status"] == "OPEN"


def test_period_close_with_provisional_ticket_rejected(api):
    """PRD §3.8: "Closing is rejected with `ERR_PERIOD_NOT_OPEN` when the period
    is not `OPEN`, and with `ERR_OPEN_TICKETS_REMAIN` when any `WeightTicket`
    whose source belongs to this zone is still in `PROVISIONAL` — the zone must
    finish certifying (or voiding) every outstanding load before the period can
    be reported on."

    Design: Corner/validations/period_close_with_provisional_ticket_rejected
    """
    zone = new_zone("Zone V10")
    resident = new_resident(zone["id"], "Ned N", "ned@x.com")
    new_delivered_kit(resident["id"], "BAG")
    pickup = new_pickup(resident["id"], bags_claimed=4)
    route_pickup(pickup["id"], "drv-1", "2026-05-10")
    collect_pickup(pickup["id"], "drv-1", 16.0)  # PROVISIONAL, never certified
    period = new_reporting_period(zone["id"])

    resp = api_client.close_reporting_period(period["id"], OP)
    validate_error(resp, ApiErrorId.ERR_OPEN_TICKETS_REMAIN)
    assert read_period(period["id"])["status"] == "OPEN"


def test_reporting_period_close_aggregates_and_freeze(api):
    """PRD §3.8: "The window used for every field is the half-open interval
    starting at `period_start` inclusive and ending at `period_end` exclusive."
    PRD §3.8: "The `total_certified_weight_kg` is the sum of `certified_weight_kg`
    over zone tickets whose `certified_at` falls in the window, regardless of
    their later status."
    PRD §3.8: "Once frozen, the aggregates never change: subsequent
    certifications, settlements, adjudications, or voids do not rewrite a closed
    period."

    Design: Corner/calculations/reporting_period_close_aggregates_and_freeze
    """
    zone = new_zone("Zone C3")
    fund = new_fund(zone["id"], 100000)
    resident = new_resident(zone["id"], "Gia G", "gia@x.com")
    k1 = new_delivered_kit(resident["id"], "BAG")

    # Pickup P1: collected, certified 12.5 RESALE at 2026-05-10, credit settled 2026-05-15.
    p1 = new_pickup(resident["id"], "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z", 10)
    route_pickup(p1["id"], "drv-1", "2026-05-10")
    t1 = collect_pickup(p1["id"], "drv-1", 40.0)
    set_clock("2026-05-10T00:00:00Z")
    certify_ticket(t1["id"], 12.5, "RESALE")
    c1 = new_credit(t1["id"])
    finalize_credit(c1["id"])
    set_clock("2026-05-15T00:00:00Z")
    settle_credit(c1["id"])

    # Fresh kit for the second pickup; drop box collected at 2026-05-20.
    k2 = order_kit(resident["id"], "BAG")
    dispatch_kit(k2["id"])
    deliver_kit(k2["id"])
    box = new_dropbox(zone["id"], "Box-R", "City Hall")
    post_reading(box["id"], 90.0, "2026-05-20T06:00:00Z")
    set_clock("2026-05-20T00:00:00Z")
    t2 = collect_box(box["id"], 55.0)
    certify_ticket(t2["id"], 8.0, "RESALE")

    # Pickup P2's ticket certified at exactly the exclusive window end.
    p2 = new_pickup(resident["id"], "2026-05-21T10:00:00Z", "2026-05-21T12:00:00Z", 5)
    route_pickup(p2["id"], "drv-1", "2026-05-21")
    t3 = collect_pickup(p2["id"], "drv-1", 20.0)
    set_clock("2026-06-01T00:00:00Z")
    certify_ticket(t3["id"], 6.0, "RECYCLE")

    period = new_reporting_period(zone["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")
    closed = validate_success(api_client.close_reporting_period(period["id"], OP))
    assert closed["status"] == "CLOSED"
    agg = closed["aggregates"]
    assert agg["total_certified_weight_kg"] == pytest.approx(20.5), (
        "12.5 + 8.0; the ticket certified exactly at period_end is excluded"
    )
    assert agg["diverted_weight_kg"] == pytest.approx(20.5)
    assert agg["credits_settled_count"] == 1
    assert agg["credits_settled_cents"] == 1650
    assert agg["charity_paid_cents"] == 0
    assert agg["severe_reports_count"] == 0
    assert agg["box_collections_count"] == 1

    # Post-close mutation must not rewrite the frozen aggregates.
    c2 = new_credit(t2["id"])
    finalize_credit(c2["id"])
    settle_credit(c2["id"])
    assert read_period(period["id"])["aggregates"] == agg, (
        "frozen aggregates must be byte-identical after a later settlement"
    )
