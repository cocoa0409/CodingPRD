"""Promoter hold negotiation: the PENDING<->COUNTERED cycle and hold expiry
(PRD §3.3).
"""
from datetime import datetime

from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show, place_hold, get_hold,
    counter_hold_once, respond_counter_payload, set_clock,
    assert_promoter_hold, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestPromoterHoldCyclicCounterLoop:
    def _stage_held_show(self, api):
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TCyc"},
            market_overrides={"market_code": "BOS", "metro_name": "Boston",
                              "radius_miles": 40},
            venue_overrides={"venue_name": "Garden", "capacity": 900,
                             "available_dates": ["2026-08-10"]})
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-10", on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=7000)
        hold = place_hold(tid, show["id"], guarantee_cents=900000, versus_pct=75)
        assert hold["status"] == "PENDING"
        assert hold["counter_count"] == 0
        return tid, show, hold

    def test_counter_then_reject_counter_loops_back_to_pending(self, api):
        """PRD §3.3: "A successful counter increments `counter_count` by one,
        extends `hold_expires_at` by a further 24 hours, and increments the
        show's `version` by one." And: "The response carries an
        `accept_counter` flag: when true, the hold's terms are replaced by the
        countered `guarantee_cents` and `versus_pct`; when false, the original
        terms stand and the promoter may counter again."

        Design: Difficulty/non_linear_state_machine/promoter_hold_cyclic_counter_loop
        """
        tid, show, hold = self._stage_held_show(api)

        countered = counter_hold_once(tid, show["id"], hold["id"],
                                      guarantee_cents=950000, versus_pct=78)
        assert_promoter_hold(countered)
        assert countered["status"] == "COUNTERED"
        assert countered["counter_count"] == 1
        # Expiry extended by a further 24 hours from the 72-hour placement TTL:
        # placed 2026-06-01T00:00:00Z -> 2026-06-04T00:00:00Z -> +24h.
        assert _parse_iso(countered["hold_expires_at"]) == _parse_iso(
            "2026-06-05T00:00:00Z"), countered["hold_expires_at"]

        responded = validate_success(
            api.respond_counter(tid, show["id"], hold["id"],
                                respond_counter_payload(accept_counter=False), TM))
        assert responded["status"] == "PENDING", "COUNTERED loops back to PENDING"
        # accept_counter=false: original terms stand
        assert responded["guarantee_cents"] == 900000
        assert responded["versus_pct"] == 75

    def test_two_full_counter_rounds_and_accepted_terms(self, api):
        """PRD §3.3: "**Responding to a counter** is the manager's move from
        `COUNTERED` back to `PENDING`, again only while the hold is unexpired.
        The response carries an `accept_counter` flag: when true, the hold's
        terms are replaced by the countered `guarantee_cents` and `versus_pct`;
        when false, the original terms stand and the promoter may counter
        again."

        Design: Difficulty/non_linear_state_machine/promoter_hold_cyclic_counter_loop
        """
        tid, show, hold = self._stage_held_show(api)

        # Round 1: PENDING -> COUNTERED -> PENDING (terms unchanged)
        c1 = counter_hold_once(tid, show["id"], hold["id"],
                               guarantee_cents=950000, versus_pct=78)
        assert c1["counter_count"] == 1
        s2 = validate_success(
            api.respond_counter(tid, show["id"], hold["id"],
                                respond_counter_payload(accept_counter=False), TM))
        assert s2["status"] == "PENDING"

        # Round 2: PENDING -> COUNTERED -> PENDING (terms replaced)
        c2 = counter_hold_once(tid, show["id"], hold["id"],
                               guarantee_cents=975000, versus_pct=80)
        assert c2["counter_count"] == 2, "the exchange cycles PENDING<->COUNTERED"
        s3 = validate_success(
            api.respond_counter(tid, show["id"], hold["id"],
                                respond_counter_payload(accept_counter=True), TM))
        assert s3["status"] == "PENDING"
        assert s3["guarantee_cents"] == 975000, (
            "accept_counter=true replaces the hold terms with the countered values")
        assert s3["versus_pct"] == 80


class TestHoldExpiry:
    def test_hold_expires_at_exactly_expiry_instant(self, api):
        """PRD §3.3: "A fresh hold is `PENDING` with `counter_count` at zero and
        a `hold_expires_at` set exactly 72 hours after placement." And:
        "whenever the logical clock reaches `hold_expires_at` — at exactly the
        expiry instant the hold is expired, not one second earlier — a hold
        still in `PENDING` or `COUNTERED` becomes `EXPIRED`, releasing the
        venue date if it was soft-blocked."

        Design: Corner/calculations/hold_expiry_at_exactly_expires_at
        """
        staged = create_staged_tour(start_clock="2026-06-01T00:00:00Z")
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=5000)
        hold = place_hold(tid, show["id"], guarantee_cents=100000, versus_pct=70)
        assert hold["status"] == "PENDING"
        # 72 hours after placement at 2026-06-01T00:00:00Z
        assert _parse_iso(hold["hold_expires_at"]) == _parse_iso("2026-06-04T00:00:00Z")

        # One second before expiry: still PENDING ("not one second earlier")
        set_clock("2026-06-03T23:59:59Z")
        before = get_hold(tid, show["id"], hold["id"])
        assert before["status"] == "PENDING"

        # At exactly the expiry instant: EXPIRED
        set_clock("2026-06-04T00:00:00Z")
        after = get_hold(tid, show["id"], hold["id"])
        assert after["status"] == "EXPIRED"

        # An expired hold can no longer be accepted: PRD §2.10 — "Sixth,
        # whether the target entity is in a permissible state for the
        # requested transition (`ERR_INVALID_STATE`)."
        res = api.accept_hold(tid, show["id"], hold["id"], PROMOTER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
