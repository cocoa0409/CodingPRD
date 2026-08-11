"""Role exclusivity and segregation of duties (PRD §2.1, §3.7, §4)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_distributor,
    setup_film,
    setup_theatre,
    setup_screen,
    setup_in_play_agreement,
    create_film_payload,
    create_booking_agreement_payload,
    create_dcp_shipment_payload,
    create_kdm_key_payload,
    close_week_with_reports,
    get_latest_settlement,
    make_booker_headers,
    make_settlement_clerk_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_exhibitor_cannot_create_film(api):
    """PRD §2.1: "A `Booker` is the distributor's negotiator: they register films,
    propose and counter booking terms, manage aggregate deals, shipments, keys, zone
    clearances, holdover decisions, and ancillary scheduling."
    PRD §2.1: "If the named role is not permitted to perform the requested operation,
    the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /distributors/{did}/films is authorized for Booker.

    Design: Corner/rbac/exhibitor_cannot_create_film
    """
    distributor = setup_distributor()
    res = api.create_film(distributor["id"], create_film_payload(), EXHIBITOR)
    validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_booker_cannot_settle_payment(api):
    """PRD §2.1: "A `SettlementClerk` runs the weekly close and settles money, subject
    to the segregation-of-duties rule in §3.7."
    PRD §2.1: "If the named role is not permitted to perform the requested operation,
    the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    PRD §4: POST .../settlements/{sid}/mark_settled is authorized for SettlementClerk.

    Design: Corner/rbac/booker_cannot_settle_payment
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 0, [(baid, 500000, 2000)])
    settlement = get_latest_settlement(did, baid)

    res = api.mark_settlement_settled(did, baid, settlement["id"], BOOKER)
    validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_sod_violation_same_user_creates_and_settles(api):
    """PRD §3.7: "Segregation of duties binds both settlement and dispute resolution:
    the clerk's `X-User-ID` must not be the identifier that created the underlying
    booking agreement, or the request fails with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_violation_same_user_creates_and_settles
    """
    creator = make_booker_headers("user-42")
    clerk_same_person = make_settlement_clerk_headers("user-42")
    clerk_other = make_settlement_clerk_headers("clerk-9")

    env = setup_in_play_agreement()
    did = env["distributor"]["id"]
    film = env["film"]
    theatre = env["theatre"]
    # The booking under settlement is created by user-42 acting as Booker.
    s2 = setup_screen(did, theatre["id"], auditorium_label="Auditorium SoD")
    ba = get_success_data(api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            film["id"], theatre["id"], s2["id"], per_capita_floor_cents=100
        ),
        creator,
    ))
    accepted = get_success_data(api.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, EXHIBITOR
    ))
    ship = get_success_data(api.create_dcp_shipment(
        did, ba["id"], create_dcp_shipment_payload(tracking_number="TN-SOD"), creator
    ))
    get_success_data(api.mark_dcp_delivered(did, ba["id"], ship["id"], EXHIBITOR))
    get_success_data(api.create_kdm_key(
        did, ba["id"], create_kdm_key_payload(screen_cert_fingerprint="FP-SOD"), creator
    ))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    live = get_success_data(api.get_booking_agreement(did, ba["id"], creator))
    assert live["deal_status"] == "IN_PLAY", f"Setup failed: {live['deal_status']}"

    close_week_with_reports(did, 0, [(ba["id"], 500000, 2000)])
    settlement = get_latest_settlement(did, ba["id"])

    res = api.mark_settlement_settled(did, ba["id"], settlement["id"], clerk_same_person)
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

    # A different clerk is not bound by the segregation rule for this agreement.
    settled = validate_success(
        api.mark_settlement_settled(did, ba["id"], settlement["id"], clerk_other), 200
    )
    assert settled["status"] == "SETTLED"


def test_auditor_read_only(api):
    """PRD §2.1: "An `Auditor` holds read-only access."
    PRD §2.1: "If the named role is not permitted to perform the requested operation,
    the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "All roles share read-only access to every resource through the list and
    read endpoints enumerated in §4."

    Design: Corner/rbac/auditor_read_only
    """
    distributor = setup_distributor()
    did = distributor["id"]

    res = api.create_film(did, create_film_payload(), AUDITOR)
    validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN)

    film = setup_film(did)
    read = validate_success(api.get_film(did, film["id"], AUDITOR), 200)
    assert read["id"] == film["id"]
    films, meta = validate_paginated(api.list_films(did, AUDITOR))
    assert any(f["id"] == film["id"] for f in films)
