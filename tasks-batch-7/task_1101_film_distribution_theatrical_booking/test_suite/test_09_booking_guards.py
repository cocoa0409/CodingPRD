"""Cross-entity booking gates: film lifecycle and DCP delivery (PRD §3.3, §3.5)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_distributor_film_theatre_screen,
    setup_accepted_booking,
    create_booking_agreement_payload,
    create_dcp_shipment_payload,
    create_kdm_key_payload,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_booking_creation_rejected_when_film_pulled(api):
    """PRD §3.3: "the film's lifecycle must be `PRE_RELEASE`, `IN_RELEASE`, or
    `HOLDOVER_PHASE`, failing with `ERR_FILM_NOT_BOOKABLE` otherwise".
    PRD §3.2: "A `Booker` may pull a film from `PRE_RELEASE`, `IN_RELEASE`, or
    `HOLDOVER_PHASE` to the terminal `PULLED` state".
    A booking proposal naming a PULLED film is rejected.

    Design: Difficulty/cross_entity_state_dependency/booking_accept_gated_on_film_lifecycle
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    fid = env["film"]["id"]
    pulled = validate_success(api.pull_film(did, fid, BOOKER), 200)
    assert pulled["lifecycle_status"] == "PULLED", (
        f"Setup failed: expected PULLED, got {pulled['lifecycle_status']}"
    )
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            fid, env["theatre"]["id"], env["screen"]["id"]
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_FILM_NOT_BOOKABLE)


def test_booking_creation_rejected_when_film_ancillary_pending(api):
    """PRD §3.3: "the film's lifecycle must be `PRE_RELEASE`, `IN_RELEASE`, or
    `HOLDOVER_PHASE`, failing with `ERR_FILM_NOT_BOOKABLE` otherwise".
    A film standing in ANCILLARY_PENDING is outside the bookable set, so a booking
    proposal naming it is rejected.

    Design: Difficulty/cross_entity_state_dependency/booking_accept_gated_on_film_lifecycle
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    fid = env["film"]["id"]
    film = validate_success(api.open_release(
        did, fid, {"expected_film_version": env["film"]["version"]}, BOOKER
    ), 200)
    assert film["lifecycle_status"] == "IN_RELEASE"
    # The handoff request may be made once the clock is within seven days of the
    # theatrical window end (PRD §3.9); window end here is 2026-07-30.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-07-24T00:00:00Z"}, ADMIN))
    film = validate_success(api.request_ancillary_handoff(did, fid, BOOKER), 200)
    assert film["lifecycle_status"] == "ANCILLARY_PENDING", (
        f"Setup failed: expected ANCILLARY_PENDING, got {film['lifecycle_status']}"
    )
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            fid, env["theatre"]["id"], env["screen"]["id"]
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_FILM_NOT_BOOKABLE)


def test_kdm_issuance_rejected_while_shipment_in_transit(api):
    """PRD §3.5: "Issuance requires the print axis at `DCP_DELIVERED` — otherwise
    `ERR_PRINT_NOT_READY`"
    A shipment has been dispatched (print axis DCP_SHIPPED) but not delivered, so key
    issuance is rejected.

    Design: Difficulty/cross_entity_state_dependency/kdm_issue_gated_on_dcp_delivery
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_accepted_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    ship = get_success_data(api.create_dcp_shipment(
        did, ba["id"], create_dcp_shipment_payload(tracking_number="TN-G1"), BOOKER
    ))
    assert ship["status"] == "IN_TRANSIT"
    ba_now = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
    assert ba_now["print_status"] == "DCP_SHIPPED", (
        f"Setup failed: print axis is {ba_now['print_status']}"
    )
    res = api.create_kdm_key(
        did, ba["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-08T00:00:00Z",
            valid_until_utc="2026-05-15T00:00:00Z",
            screen_cert_fingerprint="FP-GATE-1",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_PRINT_NOT_READY)


def test_kdm_issuance_rejected_before_any_shipment(api):
    """PRD §3.5: "Issuance requires the print axis at `DCP_DELIVERED` — otherwise
    `ERR_PRINT_NOT_READY`"
    The print axis still stands at DCP_QUEUED (acceptance queued a print but no
    shipment was ever dispatched), so key issuance is rejected.

    Design: Difficulty/cross_entity_state_dependency/kdm_issue_gated_on_dcp_delivery
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_accepted_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    assert ba["print_status"] == "DCP_QUEUED", (
        f"Setup failed: print axis is {ba['print_status']}"
    )
    res = api.create_kdm_key(
        did, ba["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-08T00:00:00Z",
            valid_until_utc="2026-05-15T00:00:00Z",
            screen_cert_fingerprint="FP-GATE-2",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_PRINT_NOT_READY)
