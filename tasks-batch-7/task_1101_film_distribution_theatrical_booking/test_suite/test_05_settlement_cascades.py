"""Transitive cascades from settlement actions (PRD §3.7, §3.8)."""
from test_helpers import (
    validate_success,
    setup_finalized_settlement,
    setup_screen,
    create_booking_agreement_payload,
    get_latest_settlement,
    close_week,
    ApiErrorId,
    validate_error,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def test_mark_settled_advances_weeks_played_and_recomputes_pct(api):
    """PRD §3.7: "Both actions advance the agreement's `weeks_played` by one and trigger
    recomputation of `current_week_rental_pct` for the coming week."
    Cascade link: Settlement FINALIZED -> SETTLED mutates the BookingAgreement
    (weeks_played 0 -> 1; current_week_rental_pct max(0.30, 0.60-0.05*1) = 0.55).

    Design: Difficulty/transitive_cascade/settle_cascade_settlement_to_agreement_to_screen_to_film
    """
    env = setup_finalized_settlement(
        booking_overrides={
            "min_weeks_committed": 1,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
            "per_capita_floor_cents": 100,
        }
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    settlement = env["settlement"]

    settled = validate_success(
        api.mark_settlement_settled(did, baid, settlement["id"], CLERK), 200
    )
    assert settled["status"] == "SETTLED", f"expected SETTLED, got {settled['status']}"

    ba = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert ba["weeks_played"] == 1, f"weeks_played must advance to 1, got {ba['weeks_played']}"
    assert ba["current_week_rental_pct"] == 0.55, (
        f"recompute must apply one week of decay: expected 0.55, "
        f"got {ba['current_week_rental_pct']}"
    )


def test_next_close_completes_agreement_and_frees_screen(api):
    """PRD §3.8: "An in-play agreement completes during the close when `weeks_played`
    has reached `min_weeks_committed`, no further holdover has been requested, and its
    latest settlement stands in `SETTLED` or `WRITTEN_OFF`."
    PRD §3.8: "Completion moves the deal to `COMPLETED`, frees the screen back to
    `AVAILABLE`, and decrements the film's `screens_committed` by one."

    Design: Difficulty/transitive_cascade/settle_cascade_settlement_to_agreement_to_screen_to_film
    """
    env = setup_finalized_settlement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    fid = env["film"]["id"]
    tid = env["theatre"]["id"]
    sid = env["screen"]["id"]

    film_before = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert film_before["screens_committed"] == 1

    settlement = env["settlement"]
    validate_success(api.mark_settlement_settled(did, baid, settlement["id"], CLERK), 200)
    close_week(did)

    ba = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert ba["deal_status"] == "COMPLETED", (
        f"close must complete the agreement once its commitment ran its course, "
        f"got {ba['deal_status']}"
    )
    screen = validate_success(api.get_screen(did, tid, sid, BOOKER), 200)
    assert screen["status"] == "AVAILABLE", (
        f"completion must free the screen, got {screen['status']}"
    )
    film_after = validate_success(api.get_film(did, fid, BOOKER), 200)
    assert film_after["screens_committed"] == 0, (
        f"completion must decrement screens_committed to 0, "
        f"got {film_after['screens_committed']}"
    )


def test_dispute_freezes_distributor_and_blocks_new_bookings(api):
    """PRD §3.7: "An `Exhibitor` who disputes a finalized settlement moves it to
    `DISPUTED`, and the cascade is immediate: the distributor's `lifecycle_posture`
    flips to `FROZEN`, blocking new booking creation, counter-offers, and acceptances
    with `ERR_DISTRIBUTOR_FROZEN` while any dispute stands open."

    Design: Difficulty/transitive_cascade/dispute_cascade_settlement_to_distributor_posture_to_new_booking_block
    """
    env = setup_finalized_settlement()
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    settlement = env["settlement"]
    screen2 = setup_screen(did, env["theatre"]["id"], auditorium_label="Auditorium 2")

    disputed = validate_success(
        api.dispute_settlement(did, baid, settlement["id"], EXHIBITOR), 200
    )
    assert disputed["status"] == "DISPUTED", f"expected DISPUTED, got {disputed['status']}"

    distributor = validate_success(api.get_distributor(did, CLERK), 200)
    assert distributor["lifecycle_posture"] == "FROZEN", (
        f"open dispute must freeze the distributor, got {distributor['lifecycle_posture']}"
    )

    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            env["film"]["id"], env["theatre"]["id"], screen2["id"],
            opening_date="2026-05-08T00:00:00Z",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_DISTRIBUTOR_FROZEN)


def test_resolving_last_dispute_restores_active_posture(api):
    """PRD §3.7: "A `SettlementClerk` — again not the agreement's creator — resolves the
    dispute, returning the settlement to `FINALIZED`, recomputing
    `final_distributor_payout_cents` with the resolution delta, and restoring the
    distributor to `ACTIVE` when no other `DISPUTED` settlement remains anywhere in its
    tree."

    Design: Difficulty/transitive_cascade/dispute_cascade_settlement_to_distributor_posture_to_new_booking_block
    """
    env = setup_finalized_settlement()
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    settlement = env["settlement"]
    screen2 = setup_screen(did, env["theatre"]["id"], auditorium_label="Auditorium 2")

    validate_success(api.dispute_settlement(did, baid, settlement["id"], EXHIBITOR), 200)
    resolved = validate_success(
        api.resolve_settlement_dispute(did, baid, settlement["id"], CLERK), 200
    )
    assert resolved["status"] == "FINALIZED", (
        f"resolution must return the settlement to FINALIZED, got {resolved['status']}"
    )

    distributor = validate_success(api.get_distributor(did, CLERK), 200)
    assert distributor["lifecycle_posture"] == "ACTIVE", (
        f"resolving the last open dispute must restore ACTIVE, "
        f"got {distributor['lifecycle_posture']}"
    )

    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            env["film"]["id"], env["theatre"]["id"], screen2["id"],
            opening_date="2026-05-08T00:00:00Z",
        ),
        BOOKER,
    )
    validate_success(res, 201)
