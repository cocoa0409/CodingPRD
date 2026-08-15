"""Passenger manifest and TSA screening lifecycle, overflight permit
decisions and duplicates, and the clock-driven expiry sweeps for both."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_trip, add_passenger, screen_passenger, create_permit, decide_permit,
    set_clock, setup_quoted_trip,
    make_ops_admin_headers, make_compliance_officer_headers,
    make_sales_agent_headers,
)

OPS_ADMIN = make_ops_admin_headers()
COMPLIANCE_OFFICER = make_compliance_officer_headers()
SALES_AGENT = make_sales_agent_headers()


def _quoted_trip(passenger_count=1, international=False, customer_name="Cust X",
                 departure_at="2026-08-10T10:00:00Z"):
    destination = "MMCZ" if international else "KTEB"
    return setup_quoted_trip(legs=((60, "REVENUE", False),),
                             departure_at=departure_at,
                             passenger_count=passenger_count,
                             international=international,
                             destination_icao=destination,
                             customer_name=customer_name)[0]


# ---------------------------------------------------------------------------
# Queue B: state_machines / screen_denied_again_rejected
# ---------------------------------------------------------------------------

def test_screen_denied_passenger_again_rejected(api):
    """PRD §3.7: "Only a passenger in `PENDING` or `EXPIRED` may be screened
    — screening a `CLEARED` or `DENIED` passenger is rejected with
    `ERR_PASSENGER_NOT_SCREENABLE`."

    Design: Corner/state_machines/screen_denied_again_rejected
    """
    trip = _quoted_trip(customer_name="Cust SD")
    pax = add_passenger(trip["id"], full_name="Pax SD", date_of_birth="1975-03-03")
    denied = screen_passenger(pax["id"], "DENIED")
    assert denied["tsa_status"] == "DENIED"
    resp = api_client.screen_passenger(pax["id"], {"outcome": "CLEARED"}, COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_PASSENGER_NOT_SCREENABLE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / permit_decide_twice_rejected
# ---------------------------------------------------------------------------

def test_permit_decide_twice_rejected(api):
    """PRD §3.7: "A `ComplianceOfficer` decides it by supplying a `decision`
    of `GRANTED` or `DENIED`; only a `REQUESTED` permit may be decided
    (`ERR_PERMIT_NOT_DECIDABLE` otherwise)."

    Design: Corner/state_machines/permit_decide_twice_rejected
    """
    trip = _quoted_trip(passenger_count=0, international=True, customer_name="Cust PD")
    permit = create_permit(trip["id"], country_code="MX", permit_type="LANDING")
    granted = decide_permit(permit["id"], "GRANTED")
    assert granted["status"] == "GRANTED"
    resp = api_client.decide_overflight_permit(
        permit["id"], {"decision": "DENIED"}, COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_DECIDABLE)


# ---------------------------------------------------------------------------
# Queue B: errors / duplicate_permit_rejected
# ---------------------------------------------------------------------------

def test_duplicate_permit_rejected(api):
    """PRD §3.7: "Duplicates are refused: a second permit for the same trip,
    country, and type while one already sits in `REQUESTED` or `GRANTED` is
    rejected with `ERR_DUPLICATE_PERMIT`."

    Design: Corner/errors/duplicate_permit_rejected
    """
    trip = _quoted_trip(passenger_count=0, international=True, customer_name="Cust DU")
    create_permit(trip["id"], country_code="MX", permit_type="LANDING", required=True)
    resp = api_client.create_overflight_permit(
        {"trip_request_id": trip["id"], "country_code": "MX",
         "permit_type": "LANDING", "required": True},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERMIT)


# ---------------------------------------------------------------------------
# Queue B: endpoints / fk_reverse_manifest_listing
# ---------------------------------------------------------------------------

def test_trip_manifest_lists_exactly_its_passengers(api):
    """PRD §4: the endpoint table lists "List the manifest of a trip" among
    the trip sub-resource listings.
    PRD §3.7: "A new passenger starts with `tsa_status` `PENDING` and a null
    `screened_at`."

    Design: Corner/endpoints/fk_reverse_manifest_listing
    """
    # PRD section 3.7: passengers may be added only while the trip is QUOTED
    # or BOOKED — the manifest setup must start from a quoted trip.
    trip = _quoted_trip(passenger_count=2, customer_name="Cust FK")
    pax1 = add_passenger(trip["id"], full_name="Pax A", date_of_birth="1990-01-01")
    pax2 = add_passenger(trip["id"], full_name="Pax B", date_of_birth="1992-02-02")
    rows, meta = validate_paginated(api_client.list_passengers(trip["id"], OPS_ADMIN))
    assert meta["total_count"] == 2
    assert {p["id"] for p in rows} == {pax1["id"], pax2["id"]}
    assert all(p["tsa_status"] == "PENDING" for p in rows)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / tsa_expiry_via_clock
# ---------------------------------------------------------------------------

def test_tsa_clearance_expires_after_72_hours(api):
    """PRD §3.7: "Clearances age out: when a clock advance carries the
    logical clock more than 72 hours past `screened_at`, the sweep of §2.4
    moves the passenger from `CLEARED` to `EXPIRED`, from which a fresh
    screening decision can clear them again."

    Design: Corner/complexity_layers/tsa_expiry_via_clock
    """
    trip = _quoted_trip(customer_name="Cust TS")
    pax = add_passenger(trip["id"], full_name="Pax TS", date_of_birth="1993-03-03")
    cleared = screen_passenger(pax["id"], "CLEARED")  # screened at 2026-08-01T00:00:00Z
    assert cleared["tsa_status"] == "CLEARED"
    set_clock("2026-08-04T01:00:00Z")  # 73 hours later
    after = validate_success(api_client.get_passenger(pax["id"], OPS_ADMIN), 200)
    assert after["tsa_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / permit_expiry_via_clock
# ---------------------------------------------------------------------------

def test_permit_expires_30_days_after_decision(api):
    """PRD §3.7: "Grants lapse with time: when the logical clock advances
    more than 30 days past `decided_at`, the sweep moves the permit from
    `GRANTED` to `EXPIRED`."

    Design: Corner/complexity_layers/permit_expiry_via_clock
    """
    trip = _quoted_trip(passenger_count=0, international=True, customer_name="Cust PE",
                        departure_at="2026-10-10T10:00:00Z")
    permit = create_permit(trip["id"], country_code="MX", permit_type="LANDING")
    granted = decide_permit(permit["id"], "GRANTED")  # decided at 2026-08-01T00:00:00Z
    assert granted["status"] == "GRANTED"
    set_clock("2026-09-01T00:00:00Z")  # 31 days later
    after = validate_success(api_client.get_overflight_permit(permit["id"], OPS_ADMIN), 200)
    assert after["status"] == "EXPIRED"
