"""Compensating invariants: accept/cancel and report voiding (PRD §3.3, §3.6)."""
from test_helpers import (
    validate_success,
    setup_distributor_film_theatre_screen,
    setup_proposed_booking,
    setup_in_play_agreement,
    file_and_submit_report,
    create_box_office_report_payload,
    get_success_data,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def test_accept_then_cancel_conserves_screens_committed_and_screen_status(api):
    """PRD §3.3: "On success the deal moves to `ACCEPTED`, the screen flips to `BOOKED`,
    the film's `screens_committed` increments by one".
    PRD §3.3: "Cancelling a previously accepted agreement unwinds every acceptance side
    effect: the screen returns to `AVAILABLE`, `screens_committed` decrements by one".
    The accept/cancel round trip leaves both quantities unchanged.

    Design: Difficulty/compensating_invariant/cancel_accept_conserves_screens_committed_and_screen_status
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    fid = env["film"]["id"]
    tid = env["theatre"]["id"]
    sid = env["screen"]["id"]
    ba = setup_proposed_booking(did, fid, tid, sid)

    film0 = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert film0["screens_committed"] == 0

    accepted = validate_success(api.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, EXHIBITOR
    ), 200)
    assert accepted["deal_status"] == "ACCEPTED"
    film1 = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert film1["screens_committed"] == 1, (
        f"accept must increment screens_committed to 1, got {film1['screens_committed']}"
    )
    screen1 = validate_success(api.get_screen(did, tid, sid, BOOKER), 200)
    assert screen1["status"] == "BOOKED"

    cancelled = validate_success(api.cancel_booking_agreement(did, ba["id"], BOOKER), 200)
    assert cancelled["deal_status"] == "CANCELLED"
    film2 = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert film2["screens_committed"] == 0, (
        f"cancel must restore screens_committed to 0, got {film2['screens_committed']}"
    )
    screen2 = validate_success(api.get_screen(did, tid, sid, BOOKER), 200)
    assert screen2["status"] == "AVAILABLE", (
        f"cancel must return the screen to AVAILABLE, got {screen2['status']}"
    )


def test_cancel_returns_undelivered_auto_created_shipment(api):
    """PRD §3.3: "a shipment record is auto-created in `QUEUED` with its
    `content_format` taken from the screen's `projection_format`".
    PRD §3.3: "Cancelling a previously accepted agreement unwinds every acceptance side
    effect: the screen returns to `AVAILABLE`, `screens_committed` decrements by one,
    any shipment not yet `DELIVERED` moves to `RETURNED`, any key in `ISSUED` or `LIVE`
    is `REVOKED`, and a `print_status` of `KEY_LIVE` rolls back to `DCP_DELIVERED`."
    The auto-created QUEUED shipment moves to RETURNED when the deal is cancelled.

    Design: Difficulty/compensating_invariant/cancel_accept_conserves_screens_committed_and_screen_status
    """
    env = setup_distributor_film_theatre_screen(
        screen_overrides={"projection_format": "DCP_4K"},
    )
    did = env["distributor"]["id"]
    ba = setup_proposed_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    validate_success(api.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, EXHIBITOR
    ), 200)

    shipments = api.list_dcp_shipments(did, ba["id"], BOOKER).json()["data"]
    assert len(shipments) == 1, f"acceptance must auto-create one shipment, got {len(shipments)}"
    assert shipments[0]["status"] == "QUEUED", (
        f"auto-created shipment must be QUEUED, got {shipments[0]['status']}"
    )
    assert shipments[0]["content_format"] == "DCP_4K", (
        f"content_format must come from the screen's projection_format, "
        f"got {shipments[0]['content_format']}"
    )

    validate_success(api.cancel_booking_agreement(did, ba["id"], BOOKER), 200)
    shipments_after = api.list_dcp_shipments(did, ba["id"], BOOKER).json()["data"]
    assert len(shipments_after) == 1
    assert shipments_after[0]["status"] == "RETURNED", (
        f"undelivered shipment must move to RETURNED on cancel, "
        f"got {shipments_after[0]['status']}"
    )


def test_void_submitted_report_recomputes_provisional_gross(api):
    """PRD §3.6: "A `Booker` may void a `SUBMITTED` report, but only while that week's
    settlement is still `PROVISIONAL`; voiding a submitted report recomputes the
    provisional settlement's gross with the voided report excluded."
    Reports 300000 + 200000 SUBMITTED -> provisional gross 500000; voiding the 200000
    report recomputes to 300000, exactly as if it had never existed.

    Design: Difficulty/compensating_invariant/void_report_conserves_settlement_gross
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 300000, 1500)
    r2 = file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 200000, 1000)

    before = api.list_settlements(did, baid, CLERK).json()["data"][-1]
    assert before["gross_cents"] == 500000, (
        f"Setup failed: provisional gross should be 500000, got {before['gross_cents']}"
    )

    voided = validate_success(
        api.void_box_office_report(did, baid, r2["id"], BOOKER), 200
    )
    assert voided["status"] == "VOIDED"

    after = api.list_settlements(did, baid, CLERK).json()["data"][-1]
    assert after["gross_cents"] == 300000, (
        f"voiding must exclude the report: expected 300000, got {after['gross_cents']}"
    )


def test_void_draft_report_excludes_it_from_provisional_gross(api):
    """PRD §3.6: "An `Exhibitor` may void a report still in `DRAFT`."
    PRD §3.7: "its gross sums reports in `DRAFT`, `SUBMITTED`, and `LOCKED` alike".
    A DRAFT report (400000) counts toward the provisional gross (500000 with a
    SUBMITTED 100000 report); once voided it is excluded, leaving 100000.

    Design: Difficulty/compensating_invariant/void_report_conserves_settlement_gross
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    r1 = get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=400000, admissions=1500
        ),
        EXHIBITOR,
    ))
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 100000, 500)

    before = api.list_settlements(did, baid, CLERK).json()["data"][-1]
    assert before["gross_cents"] == 500000, (
        f"Setup failed: provisional gross should include the DRAFT report, "
        f"got {before['gross_cents']}"
    )

    voided = validate_success(
        api.void_box_office_report(did, baid, r1["id"], EXHIBITOR), 200
    )
    assert voided["status"] == "VOIDED"

    after = api.list_settlements(did, baid, CLERK).json()["data"][-1]
    assert after["gross_cents"] == 100000, (
        f"voiding the DRAFT report must recompute the provisional gross to 100000, "
        f"got {after['gross_cents']}"
    )
