"""Composite setup helpers.

Every helper builds its preconditions from scratch against a freshly restarted
server, using only PRD-declared endpoints. Setup calls use get_success_data()
so failures surface as clear "Setup failed" errors rather than confusing
assertion failures deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_addon_payload,
    create_animal_payload,
    create_booking_animal_payload,
    create_booking_payload,
    create_customer_payload,
    create_handler_payload,
    create_health_record_payload,
    create_insurance_certificate_payload,
    create_payment_payload,
    create_permit_payload,
    create_staff_assignment_payload,
    create_venue_payload,
    create_weather_assessment_payload,
)
from .test_users import (
    make_anonymous_headers,
    make_compliance_officer_headers,
    make_coordinator_headers,
    make_customer_headers,
    make_operator_headers,
    make_veterinarian_headers,
)

# Shared opaque-role headers (ids never compared to entity ids).
OP = make_operator_headers()
VET = make_veterinarian_headers()
COORD = make_coordinator_headers("coord-1")
OFFICER = make_compliance_officer_headers("officer-1")
ANON = make_anonymous_headers()

DEFAULT_CLOCK = "2026-05-10T00:00:00Z"
CERT_EXAM = "2026-05-09T00:00:00Z"
CERT_VALID = "2026-07-01T00:00:00Z"
INSURANCE_EXPIRY = "2027-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, OP)
    return get_success_data(resp)


def create_customer(email: str = None, full_name: str = None,
                    customer_type: str = "PRIVATE") -> dict:
    payload = create_customer_payload()
    if email is not None:
        payload["email"] = email
    if full_name is not None:
        payload["full_name"] = full_name
    payload["customer_type"] = customer_type
    resp = api_client.create_customer(payload, ANON)
    return get_success_data(resp)


def create_verified_certificate(customer_id: str, coverage_amount_cents: int = 500000,
                                expires_at: str = INSURANCE_EXPIRY) -> dict:
    """Submit a certificate as the owning customer, then verify it."""
    headers = make_customer_headers(customer_id)
    payload = create_insurance_certificate_payload(
        coverage_amount_cents=coverage_amount_cents, expires_at=expires_at,
    )
    cert = get_success_data(
        api_client.create_insurance_certificate(customer_id, payload, headers)
    )
    verified = get_success_data(
        api_client.verify_insurance_certificate(cert["id"], "VERIFIED", OFFICER)
    )
    return verified


def create_venue(customer_id: str, **overrides) -> dict:
    payload = create_venue_payload(**overrides)
    resp = api_client.create_venue(payload, make_customer_headers(customer_id))
    return get_success_data(resp)


def create_animal(name: str = "Gogo", species: str = "GOAT", weight_class: str = "SMALL",
                  temperament_tier: int = 3, base_event_fee_cents: int = 8000) -> dict:
    payload = create_animal_payload(
        name=name, species=species, weight_class=weight_class,
        temperament_tier=temperament_tier, base_event_fee_cents=base_event_fee_cents,
    )
    resp = api_client.create_animal(payload, OP)
    return get_success_data(resp)


def add_health_record(animal_id: str, result: str = "PASS",
                      valid_until: str = CERT_VALID, exam_date: str = CERT_EXAM,
                      notes: str = None) -> dict:
    payload = create_health_record_payload(
        exam_date=exam_date, result=result, valid_until=valid_until,
    )
    if notes is not None:
        payload["notes"] = notes
    resp = api_client.create_health_record(animal_id, payload, VET)
    return get_success_data(resp)


def create_certified_animal(name: str = "Gogo", species: str = "GOAT",
                            weight_class: str = "SMALL", temperament_tier: int = 3,
                            base_event_fee_cents: int = 8000,
                            valid_until: str = CERT_VALID) -> dict:
    """An animal carrying one PASS health record (certified through valid_until)."""
    animal = create_animal(name, species, weight_class, temperament_tier,
                           base_event_fee_cents)
    add_health_record(animal["id"], result="PASS", valid_until=valid_until)
    return animal


def create_handler(name: str = "Hank", certifications=None) -> dict:
    payload = create_handler_payload(
        name=name,
        certifications=certifications if certifications is not None else ["FIRST_AID"],
    )
    resp = api_client.create_handler(payload, OP)
    return get_success_data(resp)


def create_booking(customer_id: str, venue_id: str,
                   start_time: str = "2026-06-17T14:00:00Z",
                   end_time: str = "2026-06-17T16:00:00Z",
                   guest_count: int = 20, child_guest_count: int = 0,
                   booking_type: str = "PRIVATE_PARTY",
                   planned_handwash_stations: int = 1) -> dict:
    payload = create_booking_payload(
        venue_id=venue_id, start_time=start_time, end_time=end_time,
        guest_count=guest_count, child_guest_count=child_guest_count,
        booking_type=booking_type, planned_handwash_stations=planned_handwash_stations,
    )
    resp = api_client.create_booking(payload, make_customer_headers(customer_id))
    return get_success_data(resp)


def attach_animal(booking_id: str, animal_id: str, role: str = "PETTING_ZOO") -> dict:
    payload = create_booking_animal_payload(animal_id=animal_id, role=role)
    resp = api_client.attach_booking_animal(booking_id, payload, COORD)
    return get_success_data(resp)


def confirm_booking_animal(booking_id: str, booking_animal_id: str) -> dict:
    resp = api_client.confirm_booking_animal(booking_id, booking_animal_id, COORD)
    return get_success_data(resp)


def quote(booking_id: str) -> dict:
    resp = api_client.quote_booking(booking_id, COORD)
    return get_success_data(resp)


def pay(booking_id: str, customer_id: str, amount_cents: int,
        method: str = "CARD") -> dict:
    payload = create_payment_payload(amount_cents=amount_cents, method=method)
    resp = api_client.create_payment(
        booking_id, payload, make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def confirm_booking(booking_id: str, customer_id: str) -> dict:
    resp = api_client.confirm_booking(booking_id, make_customer_headers(customer_id))
    return get_success_data(resp)


def assign_handler(booking_id: str, handler_id: str, role: str = "LEAD") -> dict:
    payload = create_staff_assignment_payload(handler_id=handler_id, role=role)
    resp = api_client.create_staff_assignment(booking_id, payload, COORD)
    return get_success_data(resp)


def create_addon(booking_id: str, customer_id: str, addon_type: str,
                 duration_minutes: int, expected_booking_version: int) -> dict:
    payload = create_addon_payload(
        addon_type=addon_type, duration_minutes=duration_minutes,
        expected_booking_version=expected_booking_version,
    )
    resp = api_client.create_addon(booking_id, payload, make_customer_headers(customer_id))
    return get_success_data(resp)


def decide_addon(booking_id: str, addon_id: str, decision: str,
                 denial_reason: str = None) -> dict:
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    resp = api_client.decide_addon(booking_id, addon_id, payload, COORD)
    return get_success_data(resp)


def create_permit(booking_id: str, permit_type: str = "ANIMAL_EXHIBITION",
                  jurisdiction: str = "County Fair Board") -> dict:
    payload = create_permit_payload(permit_type=permit_type, jurisdiction=jurisdiction)
    resp = api_client.create_permit(booking_id, payload, COORD)
    return get_success_data(resp)


def submit_permit(permit_id: str, submitter_user_id: str = "coord-1") -> dict:
    resp = api_client.submit_permit(
        permit_id, make_coordinator_headers(submitter_user_id),
    )
    return get_success_data(resp)


def decide_permit(permit_id: str, decision: str, decider_user_id: str = "officer-1",
                  denial_reason: str = None) -> dict:
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    resp = api_client.decide_permit(
        permit_id, payload, make_compliance_officer_headers(decider_user_id),
    )
    return get_success_data(resp)


def issue_permit(booking_id: str, permit_type: str = "ANIMAL_EXHIBITION",
                 jurisdiction: str = "County Fair Board") -> dict:
    """Create -> submit -> ISSUED, with segregated submitter/decider ids."""
    permit = create_permit(booking_id, permit_type, jurisdiction)
    submit_permit(permit["id"], "coord-1")
    return decide_permit(permit["id"], "ISSUED", "officer-1")


def sign_waiver(booking_id: str, customer_id: str, count: int) -> dict:
    resp = api_client.sign_waiver(booking_id, count, make_customer_headers(customer_id))
    return get_success_data(resp)


def create_assessment(booking_id: str, assessed_at: str, verdict: str = "MANDATORY_HOLD",
                      forecast_temp_f: int = 38, forecast_precip_pct: int = 90,
                      wind_mph: int = 35) -> dict:
    payload = create_weather_assessment_payload(
        assessed_at=assessed_at, verdict=verdict, forecast_temp_f=forecast_temp_f,
        forecast_precip_pct=forecast_precip_pct, wind_mph=wind_mph,
    )
    resp = api_client.create_weather_assessment(booking_id, payload, COORD)
    return get_success_data(resp)


def get_booking(booking_id: str) -> dict:
    resp = api_client.get_booking(booking_id, COORD)
    return get_success_data(resp)


def get_animal(animal_id: str) -> dict:
    resp = api_client.get_animal(animal_id, OP)
    return get_success_data(resp)


def get_handler(handler_id: str) -> dict:
    resp = api_client.get_handler(handler_id, OP)
    return get_success_data(resp)


def list_ledger(booking_id: str) -> list:
    resp = api_client.list_ledger_entries(booking_id, COORD)
    return get_success_data(resp)


def list_booking_animals(booking_id: str) -> list:
    resp = api_client.list_booking_animals(booking_id, COORD)
    return get_success_data(resp)


def list_staff_assignments(booking_id: str) -> list:
    resp = api_client.list_staff_assignments(booking_id, COORD)
    return get_success_data(resp)


def get_waiver(booking_id: str, customer_id: str) -> dict:
    """Fetch the booking's single auto-created waiver (array of 0 or 1, PRD §3.6)."""
    resp = api_client.list_waivers(booking_id, make_customer_headers(customer_id))
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, \
        f"expected exactly one waiver for the booking, got {data!r}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 1/2 composite: the standard "goat fixture"
# ---------------------------------------------------------------------------
def setup_draft_booking(customer_email=None, with_insurance=False,
                        insurance_coverage=500000,
                        guest_count=20, child_guest_count=0,
                        planned_handwash_stations=1,
                        start_time="2026-06-17T14:00:00Z",
                        end_time="2026-06-17T16:00:00Z",
                        booking_type="PRIVATE_PARTY",
                        venue_overrides=None,
                        clock=DEFAULT_CLOCK):
    """Clock + customer (+ optional VERIFIED certificate) + venue + DRAFT booking.

    Returns {"customer", "venue", "booking", "certificate"}.
    """
    set_clock(clock)
    customer = create_customer(email=customer_email)
    certificate = None
    if with_insurance:
        certificate = create_verified_certificate(
            customer["id"], coverage_amount_cents=insurance_coverage,
        )
    venue = create_venue(customer["id"], **(venue_overrides or {}))
    booking = create_booking(
        customer["id"], venue["id"],
        start_time=start_time, end_time=end_time,
        guest_count=guest_count, child_guest_count=child_guest_count,
        booking_type=booking_type,
        planned_handwash_stations=planned_handwash_stations,
    )
    return {
        "customer": customer, "venue": venue, "booking": booking,
        "certificate": certificate,
    }


def setup_quoted_goat_booking(customer_email=None, with_insurance=False,
                              guest_count=20, child_guest_count=0,
                              planned_handwash_stations=1,
                              start_time="2026-06-17T14:00:00Z",
                              end_time="2026-06-17T16:00:00Z",
                              booking_type="PRIVATE_PARTY",
                              venue_overrides=None,
                              animal_overrides=None,
                              confirm_animal=True,
                              clock=DEFAULT_CLOCK):
    """Standard goat fixture driven to QUOTED.

    One SMALL tier-3 goat at 8000c with a PASS cert to 2026-07-01, attached
    (and optionally confirmed) to the booking, then quoted. For the default
    20-guest Wednesday booking the quote is 16240 with deposit 4872.

    Returns the setup_draft_booking dict plus "animal", "booking_animal",
    "quote".
    """
    ctx = setup_draft_booking(
        customer_email=customer_email, with_insurance=with_insurance,
        guest_count=guest_count, child_guest_count=child_guest_count,
        planned_handwash_stations=planned_handwash_stations,
        start_time=start_time, end_time=end_time, booking_type=booking_type,
        venue_overrides=venue_overrides, clock=clock,
    )
    ao = animal_overrides or {}
    animal = create_certified_animal(
        name=ao.get("name", "Gogo"), species=ao.get("species", "GOAT"),
        weight_class=ao.get("weight_class", "SMALL"),
        temperament_tier=ao.get("temperament_tier", 3),
        base_event_fee_cents=ao.get("base_event_fee_cents", 8000),
    )
    ctx["animal"] = animal
    ba = attach_animal(ctx["booking"]["id"], animal["id"])
    if confirm_animal:
        ba = confirm_booking_animal(ctx["booking"]["id"], ba["id"])
    ctx["booking_animal"] = ba
    ctx["quote"] = quote(ctx["booking"]["id"])
    return ctx


def setup_confirmed_goat_booking(deposit_cents=4872, **kwargs):
    """Standard goat fixture driven to CONFIRMED (deposit paid).

    Returns the setup_quoted_goat_booking dict plus "confirmed".
    """
    kwargs.setdefault("with_insurance", True)
    ctx = setup_quoted_goat_booking(**kwargs)
    pay(ctx["booking"]["id"], ctx["customer"]["id"], deposit_cents)
    ctx["confirmed"] = confirm_booking(ctx["booking"]["id"], ctx["customer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_completed_two_animal_booking():
    """Screening/audited divergence scenario (PRD §3.4 screening vs §3.8 audited).

    Saturday 2026-06-13 booking, 30 guests / 0 children / 2 planned stations,
    goat SMALL tier3 8000c + sheep MEDIUM tier2 9000c both CONFIRMED, quoted
    29637 (screening 87), deposit 8891 paid, CONFIRMED, 1 handler assigned,
    balance 20746 paid, dispatched, arrived, started with 2 actual stations.

    Returns ctx with "customer", "venue", "animals", "booking", "handler".
    The booking is left IN_PROGRESS, ready for complete.
    """
    set_clock(DEFAULT_CLOCK)
    customer = create_customer()
    create_verified_certificate(customer["id"], coverage_amount_cents=500000)
    venue = create_venue(customer["id"])
    goat = create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    sheep = create_certified_animal("Shelly", "SHEEP", "MEDIUM", 2, 9000)
    booking = create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-13T14:00:00Z", end_time="2026-06-13T16:00:00Z",
        guest_count=30, child_guest_count=0, planned_handwash_stations=2,
    )
    for animal in (goat, sheep):
        ba = attach_animal(booking["id"], animal["id"])
        confirm_booking_animal(booking["id"], ba["id"])
    quoted = quote(booking["id"])
    assert quoted["quoted_total_cents"] == 29637, quoted["quoted_total_cents"]
    pay(booking["id"], customer["id"], 8891)
    confirm_booking(booking["id"], customer["id"])
    handler = create_handler("Hank", ["FIRST_AID"])
    assign_handler(booking["id"], handler["id"], "LEAD")
    pay(booking["id"], customer["id"], 20746)
    get_success_data(api_client.dispatch_booking(booking["id"], COORD))
    get_success_data(api_client.arrive_booking(booking["id"], COORD))
    get_success_data(api_client.start_event(booking["id"], 2, COORD))
    return {
        "customer": customer, "venue": venue, "animals": {"goat": goat, "sheep": sheep},
        "booking": booking, "quoted": quoted, "handler": handler,
    }


def setup_completed_three_animal_booking_then_fail_rabbit():
    """Quote-vs-final divergence scenario (PRD §3.4 provisional vs §3.8 final).

    Saturday 2026-06-06 booking, 30 guests / 12 children / 2 planned stations,
    goat 8000c + sheep 9000c + rabbit 4000c all CONFIRMED, quoted 34375,
    deposit 10313 paid, CONFIRMED, waiver completed (12 signatures), 2 handlers
    assigned, balance 24062 paid, event run to COMPLETED with 45 attendees,
    then the rabbit receives a FAIL health record (quarantine cascade removes
    its attachment). Booking is left COMPLETED, ready for finalize-invoice.

    Returns ctx with "customer", "animals" (goat/sheep/rabbit),
    "booking_animals" (goat/sheep/rabbit), "booking", "quoted".
    """
    set_clock(DEFAULT_CLOCK)
    customer = create_customer()
    create_verified_certificate(customer["id"], coverage_amount_cents=500000)
    venue = create_venue(customer["id"])
    goat = create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    sheep = create_certified_animal("Shelly", "SHEEP", "MEDIUM", 2, 9000)
    rabbit = create_certified_animal("Bun", "RABBIT", "SMALL", 3, 4000)
    booking = create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T14:00:00Z", end_time="2026-06-06T16:00:00Z",
        guest_count=30, child_guest_count=12, planned_handwash_stations=2,
    )
    booking_animals = {}
    for key, animal in (("goat", goat), ("sheep", sheep), ("rabbit", rabbit)):
        ba = attach_animal(booking["id"], animal["id"])
        booking_animals[key] = confirm_booking_animal(booking["id"], ba["id"])
    quoted = quote(booking["id"])
    assert quoted["quoted_total_cents"] == 34375, quoted["quoted_total_cents"]
    pay(booking["id"], customer["id"], 10313)
    confirm_booking(booking["id"], customer["id"])
    sign_waiver(booking["id"], customer["id"], 12)
    h1 = create_handler("Hank", ["FIRST_AID"])
    h2 = create_handler("Hana", ["FIRST_AID"])
    assign_handler(booking["id"], h1["id"], "LEAD")
    assign_handler(booking["id"], h2["id"], "ASSISTANT")
    pay(booking["id"], customer["id"], 24062)
    get_success_data(api_client.dispatch_booking(booking["id"], COORD))
    get_success_data(api_client.arrive_booking(booking["id"], COORD))
    get_success_data(api_client.start_event(booking["id"], 2, COORD))
    get_success_data(api_client.complete_booking(booking["id"], 45, COORD))
    # Post-completion: the rabbit fails a vet exam; the quarantine cascade
    # removes its roster attachment (PRD §3.2).
    add_health_record(
        rabbit["id"], result="FAIL",
        valid_until="2026-06-06T18:00:00Z", exam_date="2026-06-06T18:00:00Z",
    )
    return {
        "customer": customer, "venue": venue,
        "animals": {"goat": goat, "sheep": sheep, "rabbit": rabbit},
        "booking_animals": booking_animals,
        "booking": booking, "quoted": quoted,
    }


def setup_confirmed_sheep_booking(clock=DEFAULT_CLOCK,
                                  start_time="2026-06-17T14:00:00Z",
                                  end_time="2026-06-17T16:00:00Z",
                                  venue_overrides=None,
                                  with_permit=False):
    """Sheep fixture driven to CONFIRMED (quoted 17270, deposit 5181 paid).

    One MEDIUM tier-3 sheep at 9000c. When with_permit is set, the venue
    requires an ANIMAL_EXHIBITION permit and an ISSUED permit is created
    before confirmation.

    Returns ctx with "customer", "venue", "animal", "booking", "quote",
    "confirmed", and optionally "permit".
    """
    ctx = setup_draft_booking(
        with_insurance=True, guest_count=20, child_guest_count=0,
        planned_handwash_stations=1, start_time=start_time, end_time=end_time,
        venue_overrides=venue_overrides, clock=clock,
    )
    sheep = create_certified_animal("Shelly", "SHEEP", "MEDIUM", 3, 9000)
    ctx["animal"] = sheep
    ba = attach_animal(ctx["booking"]["id"], sheep["id"])
    ctx["booking_animal"] = confirm_booking_animal(ctx["booking"]["id"], ba["id"])
    ctx["quote"] = quote(ctx["booking"]["id"])
    assert ctx["quote"]["quoted_total_cents"] == 17270, ctx["quote"]["quoted_total_cents"]
    pay(ctx["booking"]["id"], ctx["customer"]["id"], 5181)
    if with_permit:
        ctx["permit"] = issue_permit(ctx["booking"]["id"])
    ctx["confirmed"] = confirm_booking(ctx["booking"]["id"], ctx["customer"]["id"])
    return ctx
