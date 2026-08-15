"""Cancellation policy: notice-tier boundaries, cascades to orders and grants,
and immediate read-after-write consistency."""

from test_helpers import (
    create_grant,
    create_order,
    get_grant,
    get_invoice,
    get_order,
    org_headers,
    quote_order,
    set_clock,
    setup_approved_event,
    setup_confirmed_event,
    validate_success,
)


class TestCancellationNoticeBoundaries:
    def test_cancel_at_exactly_72h_notice_is_free_and_voids(self, api):
        """PRD §3.4: "A cancellation made exactly 72 hours before the start is
        free, while one made exactly 24 hours before falls into the half-fee
        tier."
        PRD §3.4: "For an event with a live invoice, the invoice is voided when
        the fee is zero and no order has been fulfilled; otherwise the invoice
        is finalized with a total consisting of the cancellation fee plus the
        fulfilled service charges plus any accrued deposit forfeits, with the
        room charge line excluded and no insurance surcharge applied."

        Design: Difficulty/boundary_precision_check/cancel_notice_exactly_72h_free_exactly_24h_half
        """
        scn = setup_approved_event(
            org_overrides={"name": "Dept Phil", "contact_email": "phil@univ.edu"},
            event_overrides={
                "title": "E72",
                "expected_attendance": 10,
                "start_at": "2026-09-14T14:00:00Z",
                "end_at": "2026-09-14T16:00:00Z",
            },
        )
        assert scn.invoice["total_cents"] == 10000, "two off-peak buckets at 5000"

        # Exactly 72 hours before the 2026-09-14T14:00 start.
        set_clock("2026-09-11T14:00:00Z")
        cancelled = validate_success(
            api.cancel_event(scn.event["id"], org_headers(scn.org)), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CLIENT"
        assert cancelled["cancellation_fee_cents"] == 0, "72h boundary is free"

        invoice = get_invoice(scn.invoice["id"])
        assert invoice["status"] == "VOIDED"

    def test_cancel_at_exactly_24h_notice_lands_in_half_fee_tier(self, api):
        """PRD §3.4: "Notice of at least 72 hours is free; notice of at least 24
        hours but less than 72 hours incurs half the base, expressed as 5000
        basis points; notice under 24 hours incurs the full base, expressed as
        10000 basis points."
        PRD §3.4: "A cancellation made exactly 72 hours before the start is
        free, while one made exactly 24 hours before falls into the half-fee
        tier."

        Design: Difficulty/boundary_precision_check/cancel_notice_exactly_72h_free_exactly_24h_half
        """
        scn = setup_approved_event(
            org_overrides={"name": "Dept Phil", "contact_email": "phil@univ.edu"},
            event_overrides={
                "title": "E24",
                "expected_attendance": 10,
                "start_at": "2026-09-15T14:00:00Z",
                "end_at": "2026-09-15T16:00:00Z",
            },
        )
        assert scn.invoice["total_cents"] == 10000

        # Exactly 24 hours before the 2026-09-15T14:00 start.
        set_clock("2026-09-14T14:00:00Z")
        cancelled = validate_success(
            api.cancel_event(scn.event["id"], org_headers(scn.org)), 200
        )
        assert cancelled["cancellation_fee_cents"] == 5000, "half of base 10000"

        invoice = get_invoice(scn.invoice["id"])
        assert invoice["status"] == "FINALIZED"
        assert invoice["cancellation_fee_cents"] == 5000
        assert invoice["total_cents"] == 5000


def test_client_cancel_cascades_order_and_grant_without_waiver(api):
    """PRD §3.4: "All of the event's non-terminal service orders move to
    `CANCELLED`, with `fee_waived` set true for every reason except `CLIENT`,
    and its access grants still in `REQUESTED` are revoked."
    PRD §3.5: "it is true only when the cancellation came from a system cascade
    — a bump, an admin or suspension cancellation, or event completion — and
    false for requester-initiated cancels and for orders swept aside by a
    no-show."
    PRD §3.4: "applied to a pinned base equal to the provisional invoice's
    `room_charge_cents` plus its `service_charge_cents` — a snapshot, never
    recomputed at cancel time."

    Design: Corner/cross_cutting_layers/client_cancel_cascades_order_and_grant_without_waiver
    """
    scn = setup_confirmed_event(
        event_overrides={
            "expected_attendance": 5,
            "start_at": "2026-09-16T14:00:00Z",
            "end_at": "2026-09-16T16:00:00Z",
        }
    )
    order = create_order(
        scn.event["id"], scn.org, category="AV", quantity=1,
        service_start_at="2026-09-16T13:30:00Z",
        service_end_at="2026-09-16T14:30:00Z",
    )
    quote_order(order["id"], 1500)
    grant = create_grant(scn.event["id"], scn.org, grant_type="CARD_ACCESS")

    # 23 hours before the start: under-24h tier takes the full pinned base
    # (room 10000 + quoted service 1500).
    set_clock("2026-09-15T15:00:00Z")
    cancelled = validate_success(
        api.cancel_event(scn.event["id"], org_headers(scn.org)), 200
    )
    assert cancelled["cancellation_fee_cents"] == 11500

    invoice = get_invoice(scn.invoice["id"])
    assert invoice["status"] == "FINALIZED"
    assert invoice["total_cents"] == 11500
    assert invoice["insurance_surcharge_cents"] == 0

    order_after = get_order(order["id"])
    assert order_after["status"] == "CANCELLED"
    assert order_after["fee_waived"] is False, "CLIENT-cancel cascade"

    assert get_grant(grant["id"])["status"] == "REVOKED"


def test_cancel_response_and_invoice_read_are_immediately_consistent(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "one made exactly 24 hours before falls into the half-fee tier"

    Design: Corner/consistency_model/immediate_read_after_write_on_cancel
    """
    scn = setup_approved_event(
        room_overrides={
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
        event_overrides={"expected_attendance": 5},
    )
    assert scn.invoice["total_cents"] == 1000

    # Exactly 24h notice: half tier over the 1000-cent provisional base.
    set_clock("2026-09-13T14:00:00Z")
    cancelled = validate_success(
        api.cancel_event(scn.event["id"], org_headers(scn.org)), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 500

    invoice = get_invoice(scn.invoice["id"])
    assert invoice["status"] == "FINALIZED"
    assert invoice["total_cents"] == 500
