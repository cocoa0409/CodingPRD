"""Cross-entity state dependencies: the booking confirm gate reads Permit
state, the roster-attachment confirm gate reads the Animal's derived health
cert, and the add-on approval gate reads the assigned Handler's
certifications (PRD §3.4, §3.6).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Difficulty/cross_entity_state_dependency/confirm_requires_permit_issued
# =====================================================================
def _setup_quoted_booking_with_draft_permit():
    """QUOTED goat booking (deposit 4872 paid, VERIFIED insurance) on a venue
    whose jurisdiction requires an ANIMAL_EXHIBITION permit; the permit exists
    but is still DRAFT."""
    ctx = fx.setup_quoted_goat_booking(
        with_insurance=True,
        venue_overrides={
            "name": "County Fairground", "address": "4 Fair Rd",
            "distance_miles": 15, "max_guest_capacity": 300,
            "requires_animal_permit": True,
        },
    )
    fx.pay(ctx["booking"]["id"], ctx["customer"]["id"], 4872)
    ctx["permit"] = fx.create_permit(ctx["booking"]["id"])
    return ctx


def test_confirm_blocked_while_required_permit_not_issued(api):
    """PRD §3.6: "Every required permit type must have an `ISSUED` permit on
    the booking: an `ANIMAL_EXHIBITION` permit whenever the venue's
    `requires_animal_permit` flag is set, plus a `HEALTH_DEPT` permit whenever
    the `booking_type` is `SCHOOL_PROGRAM` or `LIBRARY_PROGRAM`
    (`ERR_PERMIT_NOT_ISSUED`)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_permit_issued
    """
    ctx = _setup_quoted_booking_with_draft_permit()
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    # The permit is DRAFT: no ISSUED ANIMAL_EXHIBITION permit exists.
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


def test_confirm_succeeds_once_permit_is_issued(api):
    """PRD §3.6: "Every required permit type must have an `ISSUED` permit on
    the booking: an `ANIMAL_EXHIBITION` permit whenever the venue's
    `requires_animal_permit` flag is set, plus a `HEALTH_DEPT` permit whenever
    the `booking_type` is `SCHOOL_PROGRAM` or `LIBRARY_PROGRAM`
    (`ERR_PERMIT_NOT_ISSUED`)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_permit_issued
    """
    ctx = _setup_quoted_booking_with_draft_permit()
    # Event 2026-06-17 vs clock 2026-05-10: well past the 336h lead time.
    fx.submit_permit(ctx["permit"]["id"], "coord-1")
    fx.decide_permit(ctx["permit"]["id"], "ISSUED", "officer-1")
    # The same confirm call now passes the permit gate.
    confirmed = validate_success(api.confirm_booking(
        ctx["booking"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


# =====================================================================
# Difficulty/cross_entity_state_dependency/booking_animal_confirm_requires_valid_health_cert
# =====================================================================
def _setup_booking_with_short_certed_goat():
    """Goat whose single PASS cert expires 2026-06-05, attached PROPOSED to a
    booking ending 2026-06-06T12:00:00Z."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000,
                                      valid_until="2026-06-05T00:00:00Z")
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T10:00:00Z", end_time="2026-06-06T12:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    ba = fx.attach_animal(booking["id"], goat["id"])
    return customer, booking, goat, ba


def test_animal_confirm_rejected_when_cert_expires_before_event_end(api):
    """PRD §3.4: "Third, the animal's `current_health_cert_expires_at` must be
    non-null and fall strictly after the booking's `end_time` — an animal
    without a health certificate valid beyond the event end is rejected with
    `ERR_HEALTH_CERT_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/booking_animal_confirm_requires_valid_health_cert
    """
    _, booking, goat, ba = _setup_booking_with_short_certed_goat()
    resp = api.confirm_booking_animal(booking["id"], ba["id"], fx.COORD)
    # cert horizon 2026-06-05 < booking end 2026-06-06T12:00
    validate_error(resp, ApiErrorId.ERR_HEALTH_CERT_EXPIRED)
    assert fx.get_animal(goat["id"])["status"] == "AVAILABLE"


def test_animal_confirm_succeeds_after_new_pass_extends_cert(api):
    """PRD §3.4: "Third, the animal's `current_health_cert_expires_at` must be
    non-null and fall strictly after the booking's `end_time` — an animal
    without a health certificate valid beyond the event end is rejected with
    `ERR_HEALTH_CERT_EXPIRED`."
    PRD §3.2: "Each animal also carries a derived
    `current_health_cert_expires_at`: the latest `valid_until` across all of
    its `PASS` records, or null when no `PASS` record exists."

    Design: Difficulty/cross_entity_state_dependency/booking_animal_confirm_requires_valid_health_cert
    """
    _, booking, goat, ba = _setup_booking_with_short_certed_goat()
    fx.add_health_record(goat["id"], result="PASS",
                         valid_until="2026-07-01T00:00:00Z",
                         exam_date="2026-05-20T00:00:00Z")
    goat_after = fx.get_animal(goat["id"])
    # Derived expiry recomputed as max(valid_until) over PASS records.
    assert goat_after["current_health_cert_expires_at"] is not None
    assert goat_after["current_health_cert_expires_at"].startswith("2026-07-01")

    confirmed = validate_success(
        api.confirm_booking_animal(booking["id"], ba["id"], fx.COORD))
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


# =====================================================================
# Difficulty/cross_entity_state_dependency/reptile_addon_requires_certified_handler
# =====================================================================
def _setup_booking_with_reptile_addon():
    ctx = fx.setup_draft_booking(guest_count=10)
    ctx["addon"] = fx.create_addon(
        ctx["booking"]["id"], ctx["customer"]["id"],
        "REPTILE_SHOW", 30, ctx["booking"]["version"],
    )
    return ctx


def test_reptile_addon_approval_rejected_without_certified_handler(api):
    """PRD §3.4: "a `REPTILE_SHOW` may be approved only when at least one
    `ASSIGNED` staff assignment on the booking belongs to a handler whose
    `certifications` include `REPTILE_CERTIFIED` (`ERR_NO_CERTIFIED_HANDLER`
    otherwise)"

    Design: Difficulty/cross_entity_state_dependency/reptile_addon_requires_certified_handler
    """
    ctx = _setup_booking_with_reptile_addon()
    resp = api.decide_addon(ctx["booking"]["id"], ctx["addon"]["id"],
                            {"decision": "APPROVED"}, fx.COORD)
    # No handler is assigned at all, so no REPTILE_CERTIFIED assignment exists.
    validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_HANDLER)


def test_reptile_addon_approved_once_certified_handler_assigned(api):
    """PRD §3.4: "a `REPTILE_SHOW` may be approved only when at least one
    `ASSIGNED` staff assignment on the booking belongs to a handler whose
    `certifications` include `REPTILE_CERTIFIED` (`ERR_NO_CERTIFIED_HANDLER`
    otherwise)"

    Design: Difficulty/cross_entity_state_dependency/reptile_addon_requires_certified_handler
    """
    ctx = _setup_booking_with_reptile_addon()
    rex = fx.create_handler("Rex", ["REPTILE_CERTIFIED"])
    fx.assign_handler(ctx["booking"]["id"], rex["id"], "LEAD")
    # The same decide call is now gated in by the linked handler's certs.
    decided = validate_success(api.decide_addon(
        ctx["booking"]["id"], ctx["addon"]["id"], {"decision": "APPROVED"},
        fx.COORD))
    assert decided["status"] == "APPROVED", decided["status"]
