"""Lifecycle structure: initial states, terminal lockdown, cascades (PRD §3)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_distributor,
    setup_market,
    setup_film,
    setup_theatre,
    setup_screen,
    setup_proposed_booking,
    setup_completed_booking,
    setup_distributor_film_theatre_screen,
    setup_kdm_issued_booking,
    setup_ancillary_released_film,
    create_zone_clearance_payload,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_film_initial_state_is_pre_release(api):
    """PRD §3.2: "New films carry `lifecycle_status` `PRE_RELEASE` and a
    `screens_committed` count of 0".

    Design: Corner/state_machines/film_initial_state_is_pre_release
    """
    distributor = setup_distributor()
    film = setup_film(distributor["id"])
    assert film["lifecycle_status"] == "PRE_RELEASE"

    read = validate_success(api.get_film(distributor["id"], film["id"], BOOKER), 200)
    assert read["lifecycle_status"] == "PRE_RELEASE"


def test_film_terminal_ancillary_released_lockdown(api):
    """PRD §3.2: "A `Booker` may pull a film from `PRE_RELEASE`, `IN_RELEASE`, or
    `HOLDOVER_PHASE` to the terminal `PULLED` state" — no pull transition exists from
    ANCILLARY_RELEASED.
    PRD §2.11: "5. State-machine validity — the resource is in a state from which the
    requested transition exists (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/film_terminal_ancillary_released_lockdown
    """
    env = setup_ancillary_released_film()
    did = env["distributor"]["id"]
    fid = env["film"]["id"]
    assert env["film"]["lifecycle_status"] == "ANCILLARY_RELEASED"

    res = api.pull_film(did, fid, BOOKER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert after["lifecycle_status"] == "ANCILLARY_RELEASED"


def test_booking_cancel_from_completed_returns_invalid_state(api):
    """PRD §3.3: "A `Booker` may cancel an agreement from `PROPOSED`, `COUNTERED`, or
    `ACCEPTED`; agreements in `IN_PLAY`, `HELD_OVER`, or `COMPLETED` cannot be
    cancelled and such attempts fail with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/booking_cancel_from_completed_returns_invalid_state
    """
    env = setup_completed_booking()
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    tid = env["theatre"]["id"]
    sid = env["screen"]["id"]
    assert env["booking"]["deal_status"] == "COMPLETED"

    res = api.cancel_booking_agreement(did, baid, BOOKER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert after["deal_status"] == "COMPLETED", "a rejected cancel must not mutate the deal"
    screen = validate_success(api.get_screen(did, tid, sid, BOOKER), 200)
    assert screen["status"] == "AVAILABLE", "completion already freed the screen; cancel must not change it"


def test_zone_clearance_overrule_cascades_to_proposed_bookings(api):
    """PRD §3.9: "overruling reverses the grant, moves the original to `OVERRULED`,
    creates a superseding clearance whose `parent_dispute_id` points at the original,
    and cancels every `PROPOSED` or `COUNTERED` agreement belonging to the originally
    granted theatre."

    Design: Corner/state_machines/zone_clearance_overrule_cascades_to_proposed_bookings
    """
    distributor = setup_distributor()
    did = distributor["id"]
    market = setup_market(did)
    film = setup_film(did, target_release_date="2026-06-01T00:00:00Z")
    t1 = setup_theatre(did, name="Cleared House")
    s1 = setup_screen(did, t1["id"])
    ba = setup_proposed_booking(
        did, film["id"], t1["id"], s1["id"], opening_date="2026-06-01T00:00:00Z"
    )
    zc = get_success_data(api.create_zone_clearance(
        did, market["id"],
        create_zone_clearance_payload(film["id"], t1["id"]),
        BOOKER,
    ))
    get_success_data(api.challenge_zone_clearance(did, market["id"], zc["id"], EXHIBITOR))

    ruled = validate_success(api.rule_zone_clearance(
        did, market["id"], zc["id"], {"ruling": "OVERRULED"}, BOOKER
    ), 200)
    assert ruled["status"] == "OVERRULED", f"expected OVERRULED, got {ruled['status']}"

    ba_after = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
    assert ba_after["deal_status"] == "CANCELLED", (
        f"overruling must cancel the granted theatre's PROPOSED agreement, "
        f"got {ba_after['deal_status']}"
    )

    children = api.list_zone_clearance_children(did, zc["id"], BOOKER).json()["data"]
    assert len(children) >= 1, "overruling must create a superseding clearance"
    assert all(c.get("parent_dispute_id") == zc["id"] for c in children), (
        "superseding clearance's parent_dispute_id must point at the original"
    )


def test_extend_rejected_after_key_expires(api):
    """PRD §3.5: "Extending a key from `ISSUED` requires the new `valid_until_utc` to be
    strictly later than the current one; extending from `LIVE` requires only that the
    key still be live." — no extension transition exists from `EXPIRED`.
    PRD §2.11: "5. State-machine validity — the resource is in a state from which the
    requested transition exists (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/invalid_kdm_extend_when_status_expired
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba, ship, kdm = setup_kdm_issued_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        valid_from_utc="2026-05-01T00:00:00Z",
        valid_until_utc="2026-05-08T00:00:00Z",
    )
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-08T00:00:00Z"}, ADMIN))
    expired = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert expired["status"] == "EXPIRED", (
        f"Setup failed: at exactly valid_until the key must be EXPIRED, got {expired['status']}"
    )

    res = api.extend_kdm_key(
        did, ba["id"], kdm["id"], {"valid_until_utc": "2026-05-22T00:00:00Z"}, BOOKER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
