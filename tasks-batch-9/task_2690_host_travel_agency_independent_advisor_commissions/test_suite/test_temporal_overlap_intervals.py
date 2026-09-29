"""Two different interval conventions: closed credential coverage, half-open travel."""
from test_helpers import (
    advisor_credentials,
    api_client,
    cancel_booking,
    client_bookings,
    create_booking_payload,
    decide_credential,
    eo_policy_credential_payload,
    file_credential,
    make_advisor_headers,
    new_advisor,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    read_advisor,
    seller_of_travel_credential_payload,
    setup_active_advisor,
    validate_error,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _draft_advisor_with_one_verified_registration():
    """A draft advisor holding a verified New York registration that runs to
    2027-06-30, plus an E&O filing still awaiting review."""
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    registration = file_credential(
        advisor["id"],
        seller_of_travel_credential_payload(
            jurisdiction_state_code="NY",
            credential_number="NY-SOT-40118",
            effective_on="2026-09-01",
            expires_on="2027-06-30",
        ),
    )
    registration = decide_credential(registration["id"], "VERIFY")
    pending_eo = file_credential(
        advisor["id"],
        eo_policy_credential_payload(
            credential_number="EO-99881",
            effective_on="2026-09-01",
            expires_on="2027-09-01",
        ),
    )
    return {
        "advisor": advisor,
        "registration": registration,
        "pending_eo": pending_eo,
    }


def _file_registration(advisor_id, number, effective_on, expires_on, state="NY"):
    return api_client.create_compliance_credential(
        advisor_id,
        seller_of_travel_credential_payload(
            jurisdiction_state_code=state,
            credential_number=number,
            effective_on=effective_on,
            expires_on=expires_on,
        ),
        make_advisor_headers(advisor_id),
    )


def test_a_registration_period_starting_on_the_old_expiry_instant_collides():
    """PRD §3.3: "Note the deliberate strictness at the touching boundary: a new period
    whose `effective_on` falls exactly on an existing period's `expires_on` *is* a
    conflict, because a registration period must be handed over cleanly with no shared
    instant."

    Design: Difficulty/resource_temporal_overlap/credential_coverage_closed_interval_touching_endpoints_collide
    """
    scenario = _draft_advisor_with_one_verified_registration()
    advisor_id = scenario["advisor"]["id"]
    assert scenario["registration"]["status"] == "VERIFIED"

    validate_error(
        _file_registration(advisor_id, "NY-SOT-40119", "2027-06-30", "2027-12-31"),
        "ERR_CREDENTIAL_COVERAGE_OVERLAP",
        409,
    )

    accepted = validate_success(
        _file_registration(advisor_id, "NY-SOT-40120", "2027-07-01", "2027-12-31"),
        201,
    )
    assert accepted["status"] == "PENDING_REVIEW"
    assert read_advisor(advisor_id)["status"] == "DRAFT"


def test_the_coverage_key_and_the_pending_row_both_decide_the_collision():
    """PRD §3.3: "Two credentials are compared when they belong to the same advisor,
    carry the same `credential_type`, and share the same coverage key — the coverage key
    being `jurisdiction_state_code` for a registration, `supplier_id` for an
    accreditation, and nothing at all (a single shared key) for E&O policies and training
    certificates."

    Design: Difficulty/resource_temporal_overlap/credential_coverage_closed_interval_touching_endpoints_collide
    """
    scenario = _draft_advisor_with_one_verified_registration()
    advisor_id = scenario["advisor"]["id"]

    other_state = validate_success(
        _file_registration(
            advisor_id, "FL-ST-88120", "2026-09-01", "2027-12-31", state="FL"
        ),
        201,
    )
    assert other_state["status"] == "PENDING_REVIEW"

    validate_error(
        api_client.create_compliance_credential(
            advisor_id,
            eo_policy_credential_payload(
                credential_number="EO-99882",
                effective_on="2027-01-01",
                expires_on="2027-12-31",
            ),
            make_advisor_headers(advisor_id),
        ),
        "ERR_CREDENTIAL_COVERAGE_OVERLAP",
        409,
    )

    validate_success(
        _file_registration(advisor_id, "NY-SOT-40120", "2027-07-01", "2027-12-31"),
        201,
    )

    assert len(advisor_credentials(advisor_id)) == 4
    assert read_advisor(advisor_id)["status"] == "DRAFT"


def _client_allowed_two_concurrent_trips():
    """An accredited advisor whose only client may hold two overlapping trips."""
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=new_split_schedule(
            name="Standard 2026",
            tiers=STANDARD_TIERS,
            platform_fee_tiers=FLAT_FEE_TIERS,
            chargeback_retention_pct=0.10,
        ),
        suppliers=[supplier],
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=2,
    )
    return {"advisor": ctx["advisor"], "client": client, "supplier": supplier}


def _submit(scenario, start, end):
    return new_booking(
        scenario["advisor"]["id"],
        scenario["supplier"]["id"],
        scenario["client"]["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date=start,
        travel_end_date=end,
    )


def _submission_response(scenario, start, end):
    return api_client.create_booking(
        create_booking_payload(
            scenario["advisor"]["id"],
            scenario["supplier"]["id"],
            scenario["client"]["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=1_000_000,
            travel_start_date=start,
            travel_end_date=end,
        ),
        make_advisor_headers(scenario["advisor"]["id"]),
    )


def test_capacity_bounds_overlaps_while_adjacency_is_always_permitted():
    """PRD §3.5: "Because the comparison is strict at both ends, back-to-back trips do
    not collide: an existing booking whose `travel_end_date` falls exactly on the new
    booking's `travel_start_date` leaves the two windows disjoint, and a client with the
    default capacity of 1 can still hold an unbroken chain of consecutive trips."

    Design: Difficulty/resource_temporal_overlap/client_travel_window_half_open_aggregate_capacity
    """
    scenario = _client_allowed_two_concurrent_trips()
    _submit(scenario, "2026-10-01", "2026-10-10")
    _submit(scenario, "2026-10-05", "2026-10-15")

    validate_error(
        _submission_response(scenario, "2026-10-08", "2026-10-12"),
        "ERR_TRAVEL_WINDOW_CONFLICT",
        409,
    )

    adjacent = validate_success(
        _submission_response(scenario, "2026-10-15", "2026-10-20"), 201
    )
    assert adjacent["booking_status"] == "SUBMITTED"


def test_a_cancelled_trip_stops_occupying_the_calendar():
    """PRD §3.5: "Cancelled bookings never occupy the calendar."

    Design: Difficulty/resource_temporal_overlap/client_travel_window_half_open_aggregate_capacity
    """
    scenario = _client_allowed_two_concurrent_trips()
    _submit(scenario, "2026-10-01", "2026-10-10")
    middle = _submit(scenario, "2026-10-05", "2026-10-15")
    validate_error(
        _submission_response(scenario, "2026-10-08", "2026-10-12"),
        "ERR_TRAVEL_WINDOW_CONFLICT",
        409,
    )
    _submit(scenario, "2026-10-15", "2026-10-20")

    cancelled = cancel_booking(
        middle["id"], scenario["advisor"]["id"], "CLIENT_INITIATED"
    )
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["commission_status"] == "PENDING"

    freed = validate_success(
        _submission_response(scenario, "2026-10-08", "2026-10-12"), 201
    )
    assert freed["booking_status"] == "SUBMITTED"

    assert len(client_bookings(scenario["client"]["id"])) == 4
    assert read_advisor(scenario["advisor"]["id"])["production_ytd_provisional_cents"] == 300_000
