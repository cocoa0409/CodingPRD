"""Two roles whose identifier names a stored row, and the rows they are allowed to touch.

Holding the role is never enough for either of them. A `Vendor` may act only on the work
order that carries its own identifier, and a `Prospect` may cancel only the booking that
carries its own -- while the `LeasingAgent`, who is not identity-bound at all, may cancel
anyone's.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_NOT_ASSIGNED_VENDOR,
    ERR_NOT_SLOT_OWNER,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    SLOT_AVAILABLE,
    SLOT_BOOKED,
    WO_ACCEPTED,
    WO_COMPLETED,
    WO_DISPATCHED,
)
from test_helpers.test_users import make_vendor_headers


def test_the_second_vendor_holds_the_same_role_and_certification_and_still_may_not_act(api):
    """Only the identifier written onto the row may accept it, complete it, or release its crew.

    PRD SS2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting vendor row.
    Ownership checks on a work order compare the work order's `vendor_id` to `X-User-ID`: a vendor
    may accept or complete only work orders whose `vendor_id` equals its own identifier, and a
    mismatch is `ERR_NOT_ASSIGNED_VENDOR` (HTTP 403)."  PRD SS3.4 repeats it for acceptance: "A
    dispatched vendor accepts its assignment itself: the acting role is `Vendor` and its `X-User-ID`
    must equal the work order's `vendor_id`, otherwise the request is refused with
    `ERR_NOT_ASSIGNED_VENDOR`. Acceptance moves the work order `DISPATCHED -> ACCEPTED` and changes
    no money and no capacity -- the crew days were already committed at dispatch."  Completion is
    PRD SS3.4's: "a vendor-channel work order is completed from `ACCEPTED` by the assigned `Vendor`
    ... The work order moves `ACCEPTED` -> `COMPLETED` on the vendor channel ... and stores both
    reported values. Crew capacity is released only on the vendor channel: the assigned vendor's
    `committed_crew_days` decreases by this work order's `crew_days`".  The unchanged figures are
    PRD SS3.4's creation defaults -- "`actual_cost_cents` 0, `completed_on` the empty string" -- and
    the variance is the PRD's own worked number: "Continuing the interior-paint example whose
    benchmark was 292176, a quote of 300000 gives 268 basis points and is accepted against a
    tolerance of 1000."  The ledger that must not move for the bystander is PRD SS2.9's: "For every
    vendor, `committed_crew_days` always equals the sum of `crew_days` over that vendor's work orders
    whose `status` is `DISPATCHED` or `ACCEPTED`."

    Design: Corner/rbac/vendor_role_may_only_act_on_its_own_assigned_work_order
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    vendors = x.two_certified_vendors(api, market["id"])
    assigned = make_vendor_headers(vendors.cheap.vendor_id)
    bystander = make_vendor_headers(vendors.pricey.vendor_id)

    order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"], paint["id"], work_type="TURN", fulfillment_channel="VENDOR"
            ),
            x.OPS,
        )
    )
    dispatched = ok(
        api.dispatch_work_order(
            order["id"], {"vendor_id": vendors.cheap.vendor_id}, x.OPS
        )
    )
    assert_fields(
        dispatched,
        status=WO_DISPATCHED,
        vendor_id=vendors.cheap.vendor_id,
        crew_days=9,
        variance_bps=268,
    )

    failed(api.accept_work_order(order["id"], {}, bystander), ERR_NOT_ASSIGNED_VENDOR)
    still_dispatched = ok(api.get_work_order(order["id"], x.OPS))
    assert_fields(
        still_dispatched, status=WO_DISPATCHED, vendor_id=vendors.cheap.vendor_id
    )

    accepted = ok(api.accept_work_order(order["id"], {}, assigned))
    assert_fields(accepted, status=WO_ACCEPTED, vendor_id=vendors.cheap.vendor_id)
    assert_fields(
        ok(api.get_vendor(vendors.cheap.vendor_id, x.VENDOR_MANAGER)),
        committed_crew_days=9,
    )

    failed(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(300000, "2026-08-12"), bystander
        ),
        ERR_NOT_ASSIGNED_VENDOR,
    )
    unfinished = ok(api.get_work_order(order["id"], x.OPS))
    assert_fields(unfinished, status=WO_ACCEPTED)
    assert_money_group(unfinished, actual_cost_cents=0)
    assert_absent_or_empty(unfinished, "completed_on")

    completed = ok(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(300000, "2026-08-12"), assigned
        )
    )
    assert_fields(
        completed, status=WO_COMPLETED, completed_on="2026-08-12", variance_bps=268
    )
    assert_money_group(completed, actual_cost_cents=300000)
    assert_fields(
        ok(api.get_vendor(vendors.cheap.vendor_id, x.VENDOR_MANAGER)),
        committed_crew_days=0,
    )
    assert_fields(
        ok(api.get_vendor(vendors.pricey.vendor_id, x.VENDOR_MANAGER)),
        committed_crew_days=0,
    )


def test_only_the_booking_prospect_or_any_leasing_agent_may_release_the_window(api):
    """The window changes hands twice and the home's counter tracks every hand-off.

    PRD SS2.1: "When `X-User-Role` is `Prospect`, `X-User-ID` is the `id` of the acting prospect
    row. Ownership checks compare a showing slot's `prospect_id`, or a rental application's
    `prospect_id`, to `X-User-ID`, and a mismatch is `ERR_NOT_SLOT_OWNER` (HTTP 403)."  PRD SS3.7
    scopes that check to the prospect alone: "From `BOOKED` the window returns `BOOKED` ->
    `AVAILABLE`, its `prospect_id` is cleared, the `reason` is stored in `cancel_reason`, and the
    home's `booked_showing_count` decreases by 1, restoring the count invariant; the acting role may
    be the booking `Prospect`, whose `X-User-ID` must equal the stored `prospect_id`, or a
    `LeasingAgent`."  Booking is PRD SS3.7's: "A prospect books for itself: the acting role is
    `Prospect`, the payload names `prospect_id`, and `X-User-ID` must equal that identifier or the
    request is refused with `ERR_NOT_SLOT_OWNER`. ... Finally it requires the home's
    `leasing_posture` to be `OPEN` or `RESTRICTED` ... A successful booking moves the window
    `AVAILABLE -> BOOKED`, stores the `prospect_id`, and increases the home's `booked_showing_count`
    by 1."  The counter is a conserved quantity, PRD SS2.9: "For every home, `booked_showing_count`
    always equals the number of showing windows on that home whose `status` is `BOOKED`. Booking
    increments it by 1; releasing a booked window back to the calendar ... decrements it by 1."

    Design: Corner/rbac/prospect_may_only_cancel_the_slot_it_booked
    """
    # The design index names an access mode of ``SELF_SHOWING``.  PRD SS3.7 enumerates the
    # field exhaustively -- the agent is "choosing the `access_mode` a prospect will use to
    # enter: `SMART_LOCK`, `LOCKBOX` or `AGENT_ESCORT`" -- so ``SELF_SHOWING`` is not a legal
    # value and no outcome can be derived for it.  The window is published as ``SMART_LOCK``,
    # which is the unattended mode the scenario means; nothing else about it changes.
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    first = x.verified_prospect(api, market["id"])
    second = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p4@example.com",
            "full_name": "Peter Four",
            "phone": "+1-404-555-0104",
            "declared_monthly_income_cents": 900000,
            "credit_tier": "A",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 9600,
            "verified_monthly_income_cents": 800000,
            "device_reputation_bps": 9200,
            "ip_geo_distance_km": 5,
        },
    )

    slot = created(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-08-05T15:00:00Z",
                ends_at="2026-08-05T15:30:00Z",
            ),
            x.AGENT,
        )
    )
    booked = ok(
        api.book_showing_slot(
            slot["id"], f.book_slot_payload(first.prospect_id), first.headers
        )
    )
    assert_fields(booked, status=SLOT_BOOKED, prospect_id=first.prospect_id)
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=1)

    failed(
        api.cancel_showing_slot(
            slot["id"], f.cancel_slot_payload("Not my appointment"), second.headers
        ),
        ERR_NOT_SLOT_OWNER,
    )
    intact = ok(api.get_showing_slot(slot["id"], x.AGENT))
    assert_fields(intact, status=SLOT_BOOKED, prospect_id=first.prospect_id)
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=1)

    released = ok(
        api.cancel_showing_slot(
            slot["id"], f.cancel_slot_payload("Schedule conflict"), first.headers
        )
    )
    assert_fields(released, status=SLOT_AVAILABLE, cancel_reason="Schedule conflict")
    assert_absent_or_empty(released, "prospect_id")
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=0)

    rebooked = ok(
        api.book_showing_slot(
            slot["id"], f.book_slot_payload(second.prospect_id), second.headers
        )
    )
    assert_fields(rebooked, status=SLOT_BOOKED, prospect_id=second.prospect_id)
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=1)

    withdrawn = ok(
        api.cancel_showing_slot(
            slot["id"],
            f.cancel_slot_payload("Home withdrawn from the market for the day"),
            x.AGENT,
        )
    )
    assert_fields(withdrawn, status=SLOT_AVAILABLE)
    assert_absent_or_empty(withdrawn, "prospect_id")
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=0)
