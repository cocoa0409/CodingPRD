"""Trip request lifecycle: auto-approval, charter quote rule, decline loop, RBAC."""
from test_helpers import (
    validate_success, validate_error,
    setup_owner_and_aircraft, setup_pending_agreement,
    create_trip, create_trip_payload,
    make_owner_headers, UNKNOWN_UUID, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]


def test_owner_use_trip_auto_approves_on_create(api):
    """PRD §3.4: "New trips start in `REQUESTED`. An `OWNER_USE` trip
    auto-approves at creation, transitioning immediately from `REQUESTED` to
    `APPROVED`."

    Design: Corner/state_machines/owner_use_trip_auto_approves_on_create
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N250JX")
    res = api.create_trip(
        create_trip_payload(
            aircraft["id"], trip_use="OWNER_USE",
            departure_at="2026-08-06T08:00:00Z", block_hours_est=3.0,
        ),
        FO,
    )
    trip = validate_success(res, 201)
    assert trip["status"] == "APPROVED", (
        f"OWNER_USE trip must auto-approve at creation, got {trip['status']}"
    )


def test_charter_trip_without_quote_rejected(api):
    """PRD §3.4: "A `CHARTER` trip must also carry `charter_quote_cents` — the
    price quoted to the charter customer — and omitting it is rejected with
    `ERR_QUOTE_REQUIRED`."

    Design: Corner/entities/trip_charter_without_quote_rejected
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N240JX")
    res = api.create_trip(
        create_trip_payload(
            aircraft["id"], trip_use="CHARTER",
            departure_at="2026-08-06T08:00:00Z", block_hours_est=5.0,
            arrive_icao="KMIA",
        ),
        FO,
    )
    validate_error(res, "ERR_QUOTE_REQUIRED", expected_status=422)

    # The same payload as OWNER_USE needs no quote and auto-approves.
    owner_use = validate_success(
        api.create_trip(
            create_trip_payload(
                aircraft["id"], trip_use="OWNER_USE",
                departure_at="2026-08-06T08:00:00Z", block_hours_est=5.0,
                arrive_icao="KMIA",
            ),
            FO,
        ),
        201,
    )
    assert owner_use["status"] == "APPROVED"


def test_trip_decline_after_approve_rejected(api):
    """PRD §3.4: "The owner may instead decline the charter, moving it to
    `DECLINED` and recording the supplied `reason` in `decline_reason`; only
    `CHARTER` trips may be declined, and declining an `OWNER_USE` trip is
    `ERR_TRIP_INVALID_STATE`."

    Design: Corner/state_machines/trip_decline_after_approve_rejected
    """
    scenario = setup_pending_agreement(tail_number="N260JX")
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]
    trip = create_trip(
        aircraft_id, trip_use="CHARTER", departure_at="2026-08-06T08:00:00Z",
        block_hours_est=5.0, charter_quote_cents=900000, arrive_icao="KMIA",
    )
    validate_success(api.approve_trip(trip["id"], make_owner_headers(owner_id)), 200)

    res = api.decline_trip(
        trip["id"], {"reason": "changed my mind"}, make_owner_headers(owner_id)
    )
    validate_error(res, "ERR_TRIP_INVALID_STATE", expected_status=409)

    current = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current["status"] == "APPROVED"


def test_trip_approve_nonexistent_returns_not_found(api):
    """PRD §2.8: "Third, every path identifier and every body-supplied
    foreign-key reference — `owner_id`, `aircraft_id`, `trip_id`,
    `crew_member_id`, the entries of `record_ids`, and so on — must resolve to
    an existing resource, validated left-to-right along the path; any
    unresolved reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/trip_approve_nonexistent_returns_not_found
    """
    owner, _aircraft = setup_owner_and_aircraft(tail_number="N150JB")
    res = api.approve_trip(UNKNOWN_UUID, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def _setup_requested_charter(api):
    """PENDING agreement + CHARTER trip (quote 800000) in REQUESTED."""
    scenario = setup_pending_agreement(tail_number="N600JX")
    trip = create_trip(
        scenario["aircraft"]["id"], trip_use="CHARTER",
        departure_at="2026-08-06T08:00:00Z", block_hours_est=6.0,
        charter_quote_cents=800000, arrive_icao="KMIA",
    )
    assert trip["status"] == "REQUESTED"
    return scenario, trip


def test_charter_decline_records_reason(api):
    """PRD §3.4: "The owner may instead decline the charter, moving it to
    `DECLINED` and recording the supplied `reason` in `decline_reason`; only
    `CHARTER` trips may be declined, and declining an `OWNER_USE` trip is
    `ERR_TRIP_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/trip_charter_decline_resubmit_cycle
    """
    scenario, trip = _setup_requested_charter(api)
    owner_id = scenario["owner"]["id"]

    declined = validate_success(
        api.decline_trip(
            trip["id"], {"reason": "quote below market"},
            make_owner_headers(owner_id),
        ),
        200,
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "quote below market"


def test_charter_resubmit_clears_reason_and_applies_new_quote(api):
    """PRD §3.4: "A `DECLINED` trip is not dead. Resubmission — by the
    `FlightOpsManager` or the owner — moves it back to `REQUESTED`; any of
    `departure_at`, `block_hours_est`, or `charter_quote_cents` supplied in the
    resubmission replace the stored values, and `decline_reason` is cleared. A
    resubmitted `CHARTER` trip therefore re-enters the owner-approval queue."

    Design: Difficulty/non_linear_state_machine/trip_charter_decline_resubmit_cycle
    """
    scenario, trip = _setup_requested_charter(api)
    owner_id = scenario["owner"]["id"]
    validate_success(
        api.decline_trip(
            trip["id"], {"reason": "quote below market"},
            make_owner_headers(owner_id),
        ),
        200,
    )

    resubmitted = validate_success(
        api.resubmit_trip(trip["id"], {"charter_quote_cents": 900000}, FO), 200
    )
    assert resubmitted["status"] == "REQUESTED"
    assert resubmitted["charter_quote_cents"] == 900000
    assert resubmitted.get("decline_reason") is None, (
        "resubmit must clear decline_reason"
    )

    approved = validate_success(
        api.approve_trip(trip["id"], make_owner_headers(owner_id)), 200
    )
    assert approved["status"] == "APPROVED"


def test_flight_ops_cannot_approve_charter_trip(api):
    """PRD §2.1: "When the acting role is not listed among an endpoint's
    authorized roles, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /trips/{id}/approve is authorized for Owner only.

    Design: Corner/rbac/flight_ops_cannot_approve_charter_trip
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N490JX")
    trip = create_trip(
        aircraft["id"], trip_use="CHARTER", departure_at="2026-08-06T08:00:00Z",
        block_hours_est=5.0, charter_quote_cents=900000, arrive_icao="KMIA",
    )

    res = api.approve_trip(trip["id"], FO)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    current = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current["status"] == "REQUESTED"


def test_non_owner_user_cannot_approve_charter_trip(api):
    """PRD §3.4: "A `CHARTER` trip waits for the owner: approval by the owner
    moves it `REQUESTED → APPROVED`, and the acting `X-User-ID` must equal the
    aircraft agreement's `owner_id` or the call is refused with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/non_owner_user_cannot_approve_charter_trip
    """
    scenario = setup_pending_agreement(tail_number="N500JB")
    trip = create_trip(
        scenario["aircraft"]["id"], trip_use="CHARTER",
        departure_at="2026-08-06T08:00:00Z", block_hours_est=5.0,
        charter_quote_cents=900000, arrive_icao="KMIA",
    )

    impostor_headers = make_owner_headers(UNKNOWN_UUID)
    res = api.approve_trip(trip["id"], impostor_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    current = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current["status"] == "REQUESTED"
