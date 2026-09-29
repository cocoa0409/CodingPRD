"""
Immediate consistency: a write response is already final, and the very next
request — on the row, on its siblings, or through a filtered index — already
reflects it.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as A
from test_helpers import fixtures as FX
from test_helpers.test_users import CARE_HEADERS, make_guest_headers

# 2026-09-10 is a Thursday, whose day-of-week factor is 10000 basis points, and
# the service sits in the STANDARD demand tier, also 10000 — so a party of two
# pays the 12000-cent base per cover with no multiplier movement at all.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"


def _confirmed_world(api):
    """The published Thursday chain with one party-of-two hold, deposit paid."""
    world = FX.build_world(api)
    reservation = FX.hold_seats(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    FX.pay_deposit(api, reservation["id"], world["guest_id"])
    world["reservation"] = reservation
    world["guest_headers"] = make_guest_headers(world["guest_id"])
    return world


class TestWriteResponsesAreAlreadyFinal:
    """No field is left for a later pass to fill in."""

    def test_confirm_response_body_is_the_settled_row_not_a_pre_transition_snapshot(
        self, api
    ):
        """The confirm response itself already shows the frozen, cleared hold.

        "Confirming clears `hold_expires_at_utc` to null, sets `deposit_frozen`
        to true and so freezes `deposit_due_cents` against every later add-on or
        price change, debits `party_size` from the class's `seats_held` and
        credits the same count to `seats_sold` so that the pool total is
        unchanged, credits `party_size` to the service's `covers_confirmed`, and
        advances the reservation's `version` by one."

        Design: Corner/consistency_model/immediate_write_response_already_carries_every_recomputed_field_and_siblings_agree_at_once
        """
        world = _confirmed_world(api)
        written = FX.confirm(api, world["reservation"]["id"], world["guest_id"])

        A.assert_fulfillment_status(written, "CONFIRMED")
        assert written["deposit_frozen"] is True
        assert written["hold_expires_at_utc"] is None
        assert written["deposit_due_cents"] == 7722
        assert written["amount_paid_cents"] == 7722

        # The immediate re-read agrees field for field with the write body.
        reread = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        for field in (
            "fulfillment_status",
            "payment_status",
            "deposit_frozen",
            "hold_expires_at_utc",
            "deposit_due_cents",
            "amount_paid_cents",
            "version",
        ):
            assert reread[field] == written[field], (
                f"{field} disagreed between the confirm response and the very "
                f"next read: {written[field]!r} then {reread[field]!r}"
            )

    def test_confirm_siblings_agree_on_the_next_two_requests(self, api):
        """The seat move and the service roll-up are visible with no settling.

        "Parent-level roll-ups follow the same immediate-consistency
        discipline."

        Design: Corner/consistency_model/immediate_write_response_already_carries_every_recomputed_field_and_siblings_agree_at_once
        """
        world = _confirmed_world(api)
        FX.confirm(api, world["reservation"]["id"], world["guest_id"])

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=0, available=18, status="OPEN"
        )

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 2

    def test_cancel_response_body_already_carries_the_whole_settlement(self, api):
        """Cancel is the widest single write, and it returns a settled row.

        "When the settlement yields a refund strictly above zero **and** a
        retention strictly above zero, the reservation moves to
        `PARTIALLY_REFUNDED` and exactly one `FORFEITURE` row and one `REFUND`
        row are written, with `refunded_cents` plus `forfeited_cents` equal to
        `amount_paid_cents`."

        Design: Corner/consistency_model/immediate_write_response_already_carries_every_recomputed_field_and_siblings_agree_at_once
        """
        world = _confirmed_world(api)
        FX.confirm(api, world["reservation"]["id"], world["guest_id"])
        FX.set_clock(api, CANCEL_AT_48H)

        written = FX.cancel(api, world["reservation"]["id"], world["guest_id"])

        A.assert_fulfillment_status(written, "CANCELLED")
        A.assert_payment_status(written, "PARTIALLY_REFUNDED")
        assert written["forfeited_cents"] == 4361
        assert written["refunded_cents"] == 3361
        assert written["amount_paid_cents"] == 7722
        A.assert_settled_ledger_identity(written)

        reread = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        for field in (
            "fulfillment_status",
            "payment_status",
            "forfeited_cents",
            "refunded_cents",
            "amount_paid_cents",
            "cancel_settlement_basis",
            "version",
        ):
            assert reread[field] == written[field], (
                f"{field} disagreed between the cancel response and the very "
                f"next read: {written[field]!r} then {reread[field]!r}"
            )

    def test_every_sibling_of_the_cancel_is_current_on_the_next_request(self, api):
        """The class, the service, the ledger and the guest all move at once.

        "A service's `covers_confirmed` tracks the sum of party sizes over its
        reservations in `CONFIRMED`, `SEATED` or `COMPLETED`; its
        `gross_charged_cents` is the sum of inbound ledger magnitudes across its
        reservations; its `refunded_cents` and `forfeited_cents` are the
        corresponding outbound sums; and its `net_settled_cents` is
        `gross_charged_cents` minus `refunded_cents`."

        Design: Corner/consistency_model/immediate_write_response_already_carries_every_recomputed_field_and_siblings_agree_at_once
        """
        world = _confirmed_world(api)
        FX.confirm(api, world["reservation"]["id"], world["guest_id"])
        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, world["reservation"]["id"], world["guest_id"])

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=20, status="OPEN"
        )
        assert ticket_class["sell_through_bp"] == 0

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 0
        assert service["gross_charged_cents"] == 7722
        assert service["refunded_cents"] == 3361
        assert service["forfeited_cents"] == 4361
        assert service["net_settled_cents"] == 7722 - 3361

        rows = FX.ledger_rows(api, world["reservation"]["id"], world["guest_headers"])
        assert [row["kind"] for row in rows] == [
            "DEPOSIT_CHARGE",
            "FORFEITURE",
            "REFUND",
        ]
        A.assert_created_at_ascending(rows)

        # "After **every** `REFUND` row is written ... the refunded amount is
        # credited to that guest's `lifetime_refunded_cents`" — two hops away
        # and still current.
        guest = FX.read_guest(api, world["guest_id"], CARE_HEADERS)
        assert guest["lifetime_refunded_cents"] == 3361


def _two_booking_world(api):
    """The published Thursday chain with two registered guests and no bookings
    yet, so that every index reading below starts from a known baseline."""
    world = FX.build_world(api, guests=2)
    world["guest_one"] = world["guests"][0]
    world["guest_two"] = world["guests"][1]
    return world


class TestFilteredIndexesAreLiveOnTheNextRequest:
    """Reverse indexes and total counts never lag a write."""

    def test_service_index_is_empty_then_carries_the_new_row_immediately(self, api):
        """The row appears in its service index on the request after the create.

        "A reservation carries **two independent state dimensions on the same
        row**, and they advance on different triggers."

        Design: Corner/consistency_model/immediate_filtered_lists_and_total_counts_reflect_the_write_on_the_very_next_request
        """
        from prd_bench_local_runner.testing import validate_paginated

        world = _two_booking_world(api)

        rows, meta = validate_paginated(
            api.list_reservations(
                world["manager_headers"], {"service_id": world["service_id"]}
            )
        )
        assert rows == []
        A.assert_pagination_meta(
            meta, limit=10, offset=0, total_count=0, has_more=False
        )

        created = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_one"]["id"], party_size=2
        )

        rows, meta = validate_paginated(
            api.list_reservations(
                world["manager_headers"], {"service_id": world["service_id"]}
            )
        )
        A.assert_pagination_meta(
            meta, limit=10, offset=0, total_count=1, has_more=False
        )
        assert [row["id"] for row in rows] == [created["id"]]
        # The row reached through the index is the same revision the write
        # returned, not an earlier one.
        assert rows[0]["version"] == created["version"]
        A.assert_fulfillment_status(rows[0], "PENDING")
        A.assert_payment_status(rows[0], "UNPAID")

    def test_truncating_page_still_reports_the_true_total_count(self, api):
        """A page that shows one row still counts both, on the next request.

        "`total_count` is the number of rows matching the filter before the
        window is applied, and `has_more` is true when rows remain beyond the
        returned window."

        Design: Corner/consistency_model/immediate_filtered_lists_and_total_counts_reflect_the_write_on_the_very_next_request
        """
        from prd_bench_local_runner.testing import validate_paginated

        world = _two_booking_world(api)
        first = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_one"]["id"], party_size=2
        )
        second = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_two"]["id"], party_size=3
        )
        # The party of three is charged 36000 plus a 2610-cent service charge,
        # so its deposit is thirty percent of 38610.
        assert second["deposit_due_cents"] == 11583

        rows, meta = validate_paginated(
            api.list_reservations(
                world["manager_headers"],
                {"service_id": world["service_id"], "limit": 1, "offset": 0},
            )
        )
        A.assert_pagination_meta(meta, limit=1, offset=0, total_count=2, has_more=True)
        assert [row["id"] for row in rows] == [first["id"]]

        rows, meta = validate_paginated(
            api.list_reservations(
                world["manager_headers"],
                {"service_id": world["service_id"], "limit": 1, "offset": 1},
            )
        )
        A.assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
        assert [row["id"] for row in rows] == [second["id"]]

    def test_guest_index_isolates_the_new_row_immediately(self, api):
        """The guest_id index picks the second booking up with no lag.

        "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/consistency_model/immediate_filtered_lists_and_total_counts_reflect_the_write_on_the_very_next_request
        """
        from prd_bench_local_runner.testing import validate_paginated

        world = _two_booking_world(api)
        FX.hold_seats(
            api, world["ticket_class_id"], world["guest_one"]["id"], party_size=2
        )
        second = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_two"]["id"], party_size=3
        )

        rows, meta = validate_paginated(
            api.list_reservations(
                world["manager_headers"], {"guest_id": world["guest_two"]["id"]}
            )
        )
        A.assert_pagination_meta(
            meta, limit=10, offset=0, total_count=1, has_more=False
        )
        assert [row["id"] for row in rows] == [second["id"]]

    def test_ledger_index_is_live_on_the_request_after_the_cancel(self, api):
        """Both settlement rows are queryable immediately, in created_at order.

        "Rows are never edited and never deleted; a correction is always a new
        compensating row."

        Design: Corner/consistency_model/immediate_filtered_lists_and_total_counts_reflect_the_write_on_the_very_next_request
        """
        world = _two_booking_world(api)
        guest_id = world["guest_one"]["id"]
        guest_headers = make_guest_headers(guest_id)
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], guest_id, party_size=2
        )
        FX.pay_deposit(api, reservation["id"], guest_id)
        FX.confirm(api, reservation["id"], guest_id)
        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, reservation["id"], guest_id)

        rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert [row["kind"] for row in rows] == [
            "DEPOSIT_CHARGE",
            "FORFEITURE",
            "REFUND",
        ]
        A.assert_created_at_ascending(rows)
        refunds = [row for row in rows if row["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 3361
        assert refunds[0]["memo_code"] == "GUEST_CANCEL"
