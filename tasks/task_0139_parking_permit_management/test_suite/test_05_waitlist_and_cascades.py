"""Permit waitlists and the promotion cascade: depth-3 revoke→capacity→promotion,
the manual promote endpoint, and cancellation lockdown after promotion.

PRD §3.4 governs the waitlist and the promotion cascade.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_garage_with_zone,
    create_motorist,
    request_permit,
    activate_permit,
    add_waitlist_entry,
    get_zone,
    get_waitlist_entry,
    make_motorist_headers,
)

ADMIN = TEST_USERS["facility_admin_headers"]


def test_revoke_cascades_capacity_then_lowest_sequence_promotion(api):
    """PRD §3.3: "Revocation lowers the zone's `permits_active_count` by one and,
    because a slot has been freed, triggers the waitlist promotion cascade".
    PRD §3.4: "promotion selects the `WAITING` entry with the lowest `sequence` for
    the zone, and proceeds only when that entry is genuinely the lowest-sequence
    waiter and the zone's `permits_active_count` is below its `permit_capacity`."
    PRD §3.4: "Promotion creates a brand-new `Permit` in `REQUESTED` status, copying
    the entry's `zone_id`, `motorist_id`, and `plate` onto it; sets the entry's
    `status` to `PROMOTED`; and records the new permit's id in the entry's
    `promoted_permit_id`."

    Revoking the only ACTIVE permit promotes W1 (lower sequence), leaving W2 WAITING.

    Design: Difficulty/transitive_cascade/revoke_cascades_capacity_then_waitlist_promotion_depth3
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    m0 = create_motorist("m0@x.com", default_plate="AAA000")
    m1 = create_motorist("m1@x.com", default_plate="BBB111")
    m2 = create_motorist("m2@x.com", default_plate="CCC222")
    p = request_permit(zone["id"], m0["id"], "AAA000")
    activate_permit(p["id"], zone["version"])
    w1 = add_waitlist_entry(zone["id"], m1["id"], "BBB111")
    w2 = add_waitlist_entry(zone["id"], m2["id"], "CCC222")

    revoked = validate_success(api.revoke_permit(p["id"], ADMIN))
    assert revoked["status"] == "REVOKED"
    w1_now = get_waitlist_entry(w1["id"])
    w2_now = get_waitlist_entry(w2["id"])
    assert w1_now["status"] == "PROMOTED"
    assert w2_now["status"] == "WAITING"
    assert w1_now["promoted_permit_id"], "promoted_permit_id must be a non-null Permit id"
    # Promotion creates only a REQUESTED permit; the freed slot is not re-consumed.
    assert get_zone(zone["id"])["permits_active_count"] == 0


def test_manual_promote_waitlist_creates_requested_permit(api):
    """PRD §3.4: "it can also be driven manually by a `FacilityAdmin` operator
    action that promotes the lowest-sequence waiting entry if capacity is free; the
    manual action is idempotent and safe to retry."
    PRD §3.4: "Promotion creates a brand-new `Permit` in `REQUESTED` status, copying
    the entry's `zone_id`, `motorist_id`, and `plate` onto it; sets the entry's
    `status` to `PROMOTED`; and records the new permit's id in the entry's
    `promoted_permit_id`."

    Design: Corner/cross_cutting_complexity_layers/manual_promote_waitlist_creates_requested_permit
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    m1 = create_motorist("pw1@x.com", default_plate="PWL111")
    w1 = add_waitlist_entry(zone["id"], m1["id"], "PWL111")
    promoted = validate_success(api.promote_waitlist(zone["id"], ADMIN))
    assert promoted["status"] == "PROMOTED"
    w1_now = get_waitlist_entry(w1["id"])
    assert w1_now["status"] == "PROMOTED"
    assert w1_now["promoted_permit_id"], "promoted_permit_id must be a non-null Permit id"


def test_cancel_promoted_waitlist_entry_returns_invalid_state(api):
    """PRD §3.4: "A `Motorist` may cancel their own `WAITING` entry, moving it from
    `WAITING` to `CANCELLED`; this requires the entry to be `WAITING` and the acting
    motorist to own it, failing with `ERR_INVALID_STATE` or `ERR_NOT_RESOURCE_OWNER`
    respectively."

    A PROMOTED entry is no longer WAITING, so cancel → ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_waitlist_entry_from_promoted_returns_invalid_state
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    m0 = create_motorist("wl0@x.com", default_plate="WL0111")
    m1 = create_motorist("wl1@x.com", default_plate="WL1111")
    p = request_permit(zone["id"], m0["id"], "WL0111")
    activate_permit(p["id"], zone["version"])
    w1 = add_waitlist_entry(zone["id"], m1["id"], "WL1111")
    validate_success(api.revoke_permit(p["id"], ADMIN))  # promotes w1
    assert get_waitlist_entry(w1["id"])["status"] == "PROMOTED"

    resp = api.cancel_waitlist_entry(w1["id"], make_motorist_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_waitlist_entry(w1["id"])["status"] == "PROMOTED"
