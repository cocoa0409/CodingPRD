"""Cross-cutting layers: OCC, derived-field reconciliation, scheduled actions,
immediate consistency (PRD §2.2, §2.7, §2.9, §3.5, §3.9)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_distributor,
    setup_market,
    setup_film,
    setup_theatre,
    setup_distributor_film_theatre_screen,
    setup_proposed_booking,
    setup_accepted_booking,
    setup_kdm_issued_booking,
    setup_ancillary_released_film,
    setup_committed_marketing_commitment,
    create_marketing_commitment_payload,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
MARKETING = TEST_USERS["marketing_lead_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_counter_with_stale_version_rejected(api):
    """PRD §2.7: "A counter-offer on a booking agreement must carry
    `expected_booking_agreement_version`, equal to the agreement's current `version`
    as the client last read it. If the agreement's version has since advanced —
    because another writer countered, accepted, or otherwise mutated it — the
    counter-offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_counter
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_proposed_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    stale_version = ba["version"]
    # A first counter-offer advances the agreement's version.
    countered = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {
            "expected_booking_agreement_version": stale_version,
            "week_one_rental_pct": 0.55,
            "rental_decay_per_week": 0.04,
            "floor_pct": 0.28,
            "per_capita_floor_cents": 90,
        },
        EXHIBITOR,
    ), 200)
    assert countered["version"] == stale_version + 1

    res = api.counter_booking_agreement(
        did, ba["id"],
        {
            "expected_booking_agreement_version": stale_version,
            "week_one_rental_pct": 0.50,
            "rental_decay_per_week": 0.04,
            "floor_pct": 0.25,
            "per_capita_floor_cents": 85,
        },
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_open_release_with_stale_film_version_rejected(api):
    """PRD §2.7: "Opening a film's release must carry `expected_film_version`, matching
    the film's current `version`. Because every booking acceptance advances the film's
    committed-screen count and version, a release decision made from a stale read is
    rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the booker to re-read the
    film before judging whether the wide-release gate is met."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_open_release
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    film = env["film"]
    stale_film_version = film["version"]
    # A booking acceptance advances the film's version.
    setup_accepted_booking(did, film["id"], env["theatre"]["id"], env["screen"]["id"])

    res = api.open_release(
        did, film["id"], {"expected_film_version": stale_film_version}, BOOKER
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_market_coop_committed_reconciles_on_cancel(api):
    """PRD §3.9: "A successful commit moves the commitment to `COMMITTED` and adds its
    `committed_cents` to the market's `coop_committed_cents`."
    PRD §3.9: "A `MarketingLead` may cancel a commitment from `DRAFT` or `COMMITTED`
    provided nothing has been spent — `spent_cents` must be zero — and cancelling a
    `COMMITTED` commitment decrements `coop_committed_cents` accordingly."

    Design: Corner/cross_cutting_layers/derived_field_market_coop_committed_reconciles_on_cancel
    """
    distributor = setup_distributor()
    did = distributor["id"]
    market = setup_market(did, weekly_coop_budget_cents=500000)
    film = setup_film(did)
    theatre = setup_theatre(did)
    mc = setup_committed_marketing_commitment(
        did, market["id"], film["id"], theatre["id"], committed_cents=100000
    )
    assert mc["status"] == "COMMITTED"

    before = validate_success(api.get_market(did, market["id"], AUDITOR), 200)
    assert before["coop_committed_cents"] == 100000, (
        f"commit must add to coop_committed_cents, got {before['coop_committed_cents']}"
    )

    cancelled = validate_success(
        api.cancel_marketing_commitment(did, market["id"], mc["id"], MARKETING), 200
    )
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_market(did, market["id"], AUDITOR), 200)
    assert after["coop_committed_cents"] == 0, (
        f"cancelling a COMMITTED commitment must decrement coop_committed_cents, "
        f"got {after['coop_committed_cents']}"
    )


def test_scheduled_ancillary_handoff_fires_at_window_end(api):
    """PRD §3.9: "The handoff itself is automatic: once the logical clock reaches
    `theatrical_window_end` and the film stands in `ANCILLARY_PENDING` with at least
    one `SCHEDULED` window, every scheduled window moves to `HANDED_OFF` with
    `actual_start_utc` stamped, and when the last scheduled window hands off the film
    moves to `ANCILLARY_RELEASED`."

    Design: Corner/cross_cutting_layers/scheduled_ancillary_handoff_fires_at_window_end
    """
    env = setup_ancillary_released_film()
    did = env["distributor"]["id"]
    fid = env["film"]["id"]
    awid = env["window"]["id"]

    window = validate_success(api.get_ancillary_window(did, fid, awid, AUDITOR), 200)
    assert window["status"] == "HANDED_OFF", (
        f"window must hand off once the clock passes the window end, "
        f"got {window['status']}"
    )
    assert str(window["actual_start_utc"]).startswith("2026-08-01"), (
        f"actual_start_utc must be stamped at handoff, got {window['actual_start_utc']}"
    )
    film = validate_success(api.get_film(did, fid, AUDITOR), 200)
    assert film["lifecycle_status"] == "ANCILLARY_RELEASED"


def test_kdm_expires_at_exactly_valid_until_half_open(api):
    """PRD §3.5: "when the clock reaches `valid_until_utc` the key becomes `EXPIRED` —
    the end boundary is exclusive, so at exactly that instant the key is no longer
    valid."
    PRD §2.9: "KDM validity windows use a **half-open interval**: `valid_from_utc` is
    inclusive and `valid_until_utc` is exclusive."
    One second before the boundary the key is LIVE; at the boundary it is EXPIRED.

    Design: Corner/cross_cutting_layers/kdm_expiry_at_exactly_valid_until_half_open
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba, ship, kdm = setup_kdm_issued_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        valid_from_utc="2026-05-01T00:00:00Z",
        valid_until_utc="2026-05-08T00:00:00Z",
    )
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-07T23:59:59Z"}, ADMIN))
    before = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], AUDITOR), 200)
    assert before["status"] == "LIVE", (
        f"one second before valid_until the key must be LIVE, got {before['status']}"
    )

    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-08T00:00:00Z"}, ADMIN))
    after = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], AUDITOR), 200)
    assert after["status"] == "EXPIRED", (
        f"at exactly valid_until the key must be EXPIRED, got {after['status']}"
    )


def test_accept_response_reflects_post_state_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.3: "On success the deal moves to `ACCEPTED`, the screen flips to `BOOKED`,
    the film's `screens_committed` increments by one, the agreement's `version`
    increments, and the print axis fires: a shipment record is auto-created in `QUEUED`
    with its `content_format` taken from the screen's `projection_format`, and
    `print_status` advances from `NOT_ORDERED` to `DCP_QUEUED`."

    Design: Corner/consistency_model/immediate_consistency_accept_visible_in_same_response
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_proposed_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    accepted = validate_success(api.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, EXHIBITOR
    ), 200)
    assert accepted["deal_status"] == "ACCEPTED", (
        f"the accept response must carry the post-state, got {accepted['deal_status']}"
    )
    assert accepted["print_status"] == "DCP_QUEUED", (
        f"the print-axis cascade must be visible in the same response, "
        f"got {accepted['print_status']}"
    )
    assert accepted["version"] == ba["version"] + 1, (
        f"the version increment must be atomic with the transition, "
        f"got {accepted['version']} (was {ba['version']})"
    )
