"""Guest certificates and market listings.

Queue A: cesd_listing_requires_confirmed_reservation.
Queue B: guest-cert fee, run-cycle completion + cert-used corners.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_guest_certificate_payload,
    create_listing_payload,
    get_guest_certificate,
    issue_guest_cert,
    run_billing_cycle,
    set_clock,
    setup_confirmed_reservation,
    setup_held_reservation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── cesd_listing_requires_confirmed_reservation ──────────────────────────

def test_listing_on_held_reservation_rejected(api):
    """PRD §3.6: "A listing may be created only when the underlying reservation is
    CONFIRMED; attempting to list a reservation in any other state is rejected with
    ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/cesd_listing_requires_confirmed_reservation
    """
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    resp = api.create_listing(
        world["reservation"]["id"], create_listing_payload("RENTAL", ask_amount_cents=50000), world["member_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_listing_allowed_once_reservation_confirmed(api):
    """PRD §3.6: "A listing may be created only when the underlying reservation is
    CONFIRMED ... A new listing begins in LISTED status linked to its reservation by
    reservation_id."

    Design: Difficulty/cross_entity_state_dependency/cesd_listing_requires_confirmed_reservation
    """
    world = setup_confirmed_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    listing = validate_success(
        api.create_listing(
            world["reservation"]["id"], create_listing_payload("RENTAL", ask_amount_cents=50000), world["member_headers"]
        ),
        201,
    )
    assert listing["status"] == "LISTED"
    assert listing["listing_type"] == "RENTAL"


# ─── Queue B corners ──────────────────────────────────────────────────────

def test_guest_cert_charges_fixed_fee(api):
    """PRD §3.6: "Issuing a certificate charges a fixed fee of 50 points, recorded on
    the certificate as fee_points; the paying bucket's points_used rises by that fee ...
    the certificate is created in ISSUED status".

    Design: Corner/calculations/corner_guest_cert_fee_charged
    """
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    cert = validate_success(
        api.issue_guest_certificate(world["reservation"]["id"], create_guest_certificate_payload(guest_name="Guest"), world["member_headers"]),
        201,
    )
    assert cert["fee_points"] == 50
    assert cert["status"] == "ISSUED"
    bucket = validate_success(api.get_points_bucket(world["bucket"]["id"], ADMIN), 200)
    assert bucket["points_used"] == 1050  # 1000 reservation + 50 fee
    assert bucket["points_available"] == 3950


def test_run_cycle_completes_reservation_and_uses_cert(api):
    """PRD §3.10: "any CONFIRMED reservation whose check_out the clock has reached or
    passed moves to COMPLETED, and any ISSUED guest certificate on it moves to USED."

    Design: Corner/state_machines/corner_run_cycle_completes_reservation_and_uses_guest_cert
    """
    world = setup_confirmed_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    cert = issue_guest_cert(world["reservation"]["id"], world["member"]["id"], "Guest G")
    set_clock("2026-08-20T00:00:00Z")
    run_billing_cycle()
    res = validate_success(api.get_reservation(world["reservation"]["id"], ADMIN), 200)
    assert res["status"] == "COMPLETED"
    used_cert = get_guest_certificate(world["reservation"]["id"], cert["id"])
    assert used_cert["status"] == "USED"
