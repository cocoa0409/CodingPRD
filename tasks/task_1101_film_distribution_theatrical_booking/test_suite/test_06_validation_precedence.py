"""Validation precedence pairs from the fixed global order (PRD §2.11)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_distributor_film_theatre_screen,
    setup_accepted_booking,
    setup_delivered_booking,
    setup_proposed_booking,
    create_kdm_key_payload,
    setup_screen,
    ApiErrorId,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_state_violation_beats_fiscal_violation_on_counter(api):
    """PRD §2.11: "Where several guards apply to one operation, they are evaluated in a
    fixed global order, and the first failing guard produces the error:"
    PRD §2.11: "5. State-machine validity — the resource is in a state from which the
    requested transition exists (`ERR_INVALID_STATE`)."
    PRD §2.11: "16. Rental-term validity (`ERR_INVALID_RENTAL_TERMS`)."
    A counter-offer against an ACCEPTED agreement (no such transition) that also
    carries floor_pct > week_one_rental_pct must report the state violation.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_invalid_state_beats_invalid_rental_terms
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_accepted_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    res = api.counter_booking_agreement(
        did, ba["id"],
        {
            "expected_booking_agreement_version": ba["version"],
            "week_one_rental_pct": 0.50,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.70,
            "per_capita_floor_cents": 100,
        },
        EXHIBITOR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_state_violation_beats_over_max_rental_pct_on_counter(api):
    """PRD §2.11: "5. State-machine validity — the resource is in a state from which the
    requested transition exists (`ERR_INVALID_STATE`)." precedes "16. Rental-term
    validity (`ERR_INVALID_RENTAL_TERMS`)." in the fixed global order.
    A counter-offer against an ACCEPTED agreement whose week_one_rental_pct exceeds the
    0.95 admissible maximum must still report the state violation.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_invalid_state_beats_invalid_rental_terms
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_accepted_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    res = api.counter_booking_agreement(
        did, ba["id"],
        {
            "expected_booking_agreement_version": ba["version"],
            "week_one_rental_pct": 0.96,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
            "per_capita_floor_cents": 100,
        },
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def _setup_two_bookings_one_with_key(api):
    """BA1 (screen 1) carries an ISSUED key on fingerprint FP-1 covering
    [2026-05-08, 2026-05-15); BA2 (screen 2) is accepted but never shipped, so
    its print axis stands at DCP_QUEUED."""
    env = setup_distributor_film_theatre_screen(
        film_overrides={"target_release_date": "2026-05-08T00:00:00Z"},
    )
    did = env["distributor"]["id"]
    tid = env["theatre"]["id"]
    fid = env["film"]["id"]
    s2 = setup_screen(did, tid, auditorium_label="Auditorium 2")

    ba1, ship1 = setup_delivered_booking(
        did, fid, tid, env["screen"]["id"], opening_date="2026-05-08T00:00:00Z"
    )
    validate_success(api.create_kdm_key(
        did, ba1["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-08T00:00:00Z",
            valid_until_utc="2026-05-15T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    ), 201)

    ba2 = setup_accepted_booking(
        did, fid, tid, s2["id"], opening_date="2026-05-08T00:00:00Z"
    )
    ba2 = validate_success(api.get_booking_agreement(did, ba2["id"], BOOKER), 200)
    assert ba2["print_status"] == "DCP_QUEUED", (
        f"Setup failed: BA2 print axis is {ba2['print_status']}"
    )
    return env, ba1, ba2


def test_kdm_window_conflict_beats_print_readiness(api):
    """PRD §2.11: "7. KDM window conflict on the same screen (`ERR_KDM_WINDOW_CONFLICT`)."
    precedes "8. Print readiness — the print axis permits key issuance
    (`ERR_PRINT_NOT_READY`)."
    Issuing a key whose window overlaps another issued key on the same screen while
    the print axis is not yet delivered must report the window conflict.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_kdm_window_over_dcp_prereq
    """
    env, ba1, ba2 = _setup_two_bookings_one_with_key(api)
    did = env["distributor"]["id"]
    res = api.create_kdm_key(
        did, ba2["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-10T00:00:00Z",
            valid_until_utc="2026-05-20T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_KDM_WINDOW_CONFLICT)


def test_kdm_window_conflict_beats_print_readiness_late_overlap(api):
    """PRD §2.11: "7. KDM window conflict on the same screen (`ERR_KDM_WINDOW_CONFLICT`)."
    precedes "8. Print readiness — the print axis permits key issuance
    (`ERR_PRINT_NOT_READY`)."
    A window overlapping only the tail of an existing key on the same screen still
    reports the window conflict even though the print gate would also fail.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_kdm_window_over_dcp_prereq
    """
    env, ba1, ba2 = _setup_two_bookings_one_with_key(api)
    did = env["distributor"]["id"]
    res = api.create_kdm_key(
        did, ba2["id"],
        create_kdm_key_payload(
            valid_from_utc="2026-05-14T00:00:00Z",
            valid_until_utc="2026-05-22T00:00:00Z",
            screen_cert_fingerprint="FP-1",
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_KDM_WINDOW_CONFLICT)
