"""Role-based access control, authentication, and optimistic-concurrency control
on the booking-confirm path.

Covers corner-design rbac, errors, and cross_cutting OCC claims.
"""
from test_helpers import (
    validate_success, validate_error,
    make_ops_manager_headers, make_cashier_headers, make_guest_headers,
    create_venue, create_attraction, create_pricing_plan, create_heat, open_heat,
    create_guest, make_signed_guest, get_wallet_for_guest,
    create_heat_hold_booking, confirm_booking_heat, get_heat, get_booking,
    create_venue_payload, create_attraction_payload,
)

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()


# ───────────────────────────── Corner: rbac ──────────────────────────────────

def test_guest_cannot_create_venue(api):
    """PRD §2.1: "When a recognised role attempts an operation that its permissions
    do not cover, the request is rejected with ERR_FORBIDDEN."
    PRD §4 endpoints: "POST | /venues | Create a venue (posture OPEN) | OpsManager".

    Design: Corner/rbac/guest_cannot_create_venue
    """
    guest = create_guest(full_name="G", height_cm=175)
    res = api.create_venue(create_venue_payload(name="Hacker Venue"),
                           make_guest_headers(guest["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_cashier_cannot_create_attraction(api):
    """PRD §2.1: "a Cashier cannot change venue posture, attractions, pricing, or
    slot inventory."
    PRD §4 endpoints: "POST | /attractions | Create an attraction | OpsManager".

    Design: Corner/rbac/cashier_cannot_create_attraction
    """
    venue = create_venue(name="V", set_clock=None)
    res = api.create_attraction(
        create_attraction_payload(venue["id"], name="Karts", kind="GO_KART", lane_count=5), CASHIER)
    validate_error(res, "ERR_FORBIDDEN")


def test_guest_cannot_act_on_other_guest_wallet(api):
    """PRD §2.1: "a Guest may only read and act on resources it owns, where
    ownership is established through the guest_id of a booking, combo pass, waiver,
    or wallet ... A Guest attempting to read or mutate another guest's resource is
    rejected with ERR_FORBIDDEN".

    Design: Corner/rbac/guest_cannot_act_on_other_guest_wallet
    """
    ga = create_guest(full_name="A", height_cm=175)
    gb = create_guest(full_name="B", height_cm=175)
    wallet_b = get_wallet_for_guest(gb["id"])
    # Guest A (X-User-ID = A) tops up Guest B's wallet -> forbidden.
    res = api.top_up_wallet(wallet_b["id"], {"amount_cents": 1000}, make_guest_headers(ga["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ──────────────────────────── Corner: errors ─────────────────────────────────

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory
    HTTP headers: X-User-ID, identifying the acting principal, and X-User-Role ...
    If either header is missing, or X-User-Role does not name a role the system
    recognises, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    res = api.list_venues({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─────────────── Corner: cross_cutting (optimistic concurrency) ───────────────

def test_stale_heat_version_on_confirm_rejected(api):
    """PRD §2.8: "If the supplied value does not match the slot's current version —
    because another writer has confirmed a booking that consumed lanes or player
    spots and advanced the slot's version since the caller last read it — the
    confirm is rejected with ERR_STALE_SLOT_VERSION at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_heat_version_on_confirm_rejected
    """
    venue = create_venue(name="V", set_clock="2026-06-14T09:00:00Z")
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])
    heat = open_heat(heat["id"])
    heat_v_obs = heat["version"]
    g1 = make_signed_guest(full_name="G1", height_cm=180)
    g2 = make_signed_guest(full_name="G2", height_cm=180)

    bk1 = create_heat_hold_booking(venue["id"], g1["id"], heat["id"], plan["id"], party_size=1)
    bk2 = create_heat_hold_booking(venue["id"], g2["id"], heat["id"], plan["id"], party_size=1)
    # First confirm consumes a lane and advances Heat.version past heat_v_obs.
    confirm_booking_heat(bk1["id"], heat_v_obs)
    # Second confirm still cites the stale (pre-bump) version -> 412.
    res = api.confirm_booking(bk2["id"], {"expected_heat_version": heat_v_obs}, OPS)
    validate_error(res, "ERR_STALE_SLOT_VERSION")
    assert get_booking(bk2["id"])["status"] == "HOLD"


def test_correct_heat_version_confirms_and_bumps(api):
    """PRD §2.8: "Confirming a booking requires the caller to supply the current
    version of the slot the booking occupies: expected_heat_version when the
    booking occupies a heat".
    PRD §3.6: "the slot's committed counter rises by party_size and its available
    count is recomputed, the slot's version increments".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_heat_version_confirms
    """
    venue = create_venue(name="V", set_clock="2026-06-14T09:00:00Z")
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])
    heat = open_heat(heat["id"])
    g1 = make_signed_guest(full_name="G1", height_cm=180)
    g2 = make_signed_guest(full_name="G2", height_cm=180)

    bk1 = create_heat_hold_booking(venue["id"], g1["id"], heat["id"], plan["id"], party_size=1)
    confirm_booking_heat(bk1["id"], heat["version"])
    heat_v2 = get_heat(heat["id"])["version"]

    bk2 = create_heat_hold_booking(venue["id"], g2["id"], heat["id"], plan["id"], party_size=1)
    confirmed = validate_success(
        api.confirm_booking(bk2["id"], {"expected_heat_version": heat_v2}, OPS), 200)
    assert confirmed["status"] == "CONFIRMED"
    heat_final = get_heat(heat["id"])
    assert heat_final["lanes_committed"] == 2
    assert heat_final["version"] > heat_v2, "confirm bumps Heat.version (monotonic)"
