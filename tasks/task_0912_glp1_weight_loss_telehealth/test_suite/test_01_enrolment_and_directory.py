"""Enrolment, the clinical directory, physical stock and the response envelope."""

from test_helpers import (
    NO_AUTH_HEADERS,
    assert_patient,
    assert_provider,
    assert_supply_lot,
    create_patient_payload,
    create_supply_lot_payload,
    enroll_patient,
    make_patient_headers,
    open_screening,
    platform_admin_headers,
    record_supply_lot,
    register_clinician,
    register_pharmacy,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_enrol_member_computes_live_bmi_and_seeds_defaults(api):
    """PRD §3.1: "The body-mass index is computed by converting the height from
    centimetres to metres — dividing `height_cm` by 100 — squaring that figure,
    dividing `weight_kg` by the square, and rounding the quotient half-up to
    exactly one decimal place."
    PRD §3.1: "Three derived values are written at enrolment and are visible on
    every read of the member. `current_bmi` is the member's live body-mass index;
    `eligibility_status` starts at `NOT_SCREENED`; and the two lifetime billing
    counters, `lifetime_charged_cents` and `lifetime_credited_cents`, both start
    at zero."
    PRD §2.5: "`version` (integer): a counter that begins at 1 and increments by
    1 on every mutation of the row."

    Design: Corner/entities/patient_creation_returns_computed_bmi_and_defaults
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_patient(
        create_patient_payload(
            email="corner1@example.com",
            full_name="Corner One",
            state_code="CA",
            height_cm=170,
            weight_kg=95.0,
            payment_mode="CASH",
            comorbidity_codes=["HYPERTENSION"],
        ),
        platform_admin_headers(),
    )
    member = validate_success(response, 201)

    assert_patient(member)
    assert member["current_bmi"] == 32.9, (
        f"95.0 kg at 170 cm rounds to 32.9, got {member['current_bmi']}"
    )
    assert member["eligibility_status"] == "NOT_SCREENED"
    assert member["lifetime_charged_cents"] == 0
    assert member["lifetime_credited_cents"] == 0
    assert member["version"] == 1


def test_member_read_reflects_the_latest_weigh_in(api):
    """PRD §3.1: "A member or their clinician may record a new weigh-in at any
    time by submitting a fresh `weight_kg`; the service recomputes `current_bmi`
    on the spot from the new weight and the unchanged height, refreshes
    `updated_at`, and increments the member's `version`."

    Design: Corner/entities/patient_retrieval_returns_stored_row
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(
        email="corner2@example.com", full_name="Corner Two", weight_kg=95.0
    )

    api.update_patient_vitals(
        member["id"], {"weight_kg": 90.0}, make_patient_headers(member["id"])
    )

    stored = validate_success(api.get_patient(member["id"], platform_admin_headers()))
    assert_patient(stored)
    assert stored["weight_kg"] == 90.0
    assert stored["current_bmi"] == 31.1, (
        f"90.0 kg at 170 cm rounds to 31.1, got {stored['current_bmi']}"
    )
    assert stored["version"] == 2


def test_supply_lot_list_filtered_to_one_pharmacy_paginates(api):
    """PRD §2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10, may be no smaller than 1 and no larger than 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope; `total_count` reflects the
    number of records matching the filters before pagination is applied, and
    `has_more` is true when records remain beyond the current page."

    Design: Corner/entities/supply_lot_listing_paginates_with_total_count
    """
    pharmacy = register_pharmacy(name="Bay Compounding")
    for code, strength in (("P-1", 0.25), ("P-2", 0.5), ("P-3", 1.0)):
        record_supply_lot(
            pharmacy["id"], lot_code=code, strength_mg=strength, total_units=10
        )

    response = api.list_supply_lots(
        platform_admin_headers(),
        params={"pharmacy_id": pharmacy["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 2, f"limit 2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert response.json()["response_type"] == "array"


def test_unknown_member_identifier_returns_patient_not_found(api):
    """PRD §2.6: "A Patient that does not resolve yields
    `ERR_PATIENT_NOT_FOUND`."

    Design: Corner/entities/patient_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.get_patient(
        "11111111-2222-3333-4444-555555555555", platform_admin_headers()
    )

    validate_error(response, "ERR_PATIENT_NOT_FOUND")
    assert response.json()["response_type"] == "error"


def test_recorded_lot_opens_with_every_unit_available(api):
    """PRD §3.1: "When the lot is recorded, `available_units` is initialised to
    `total_units` while `reserved_units` and `dispensed_units` both start at zero
    — the opening position of the conservation identity described in §2.10."

    Design: Corner/entities/supply_lot_available_units_initialised_from_total_units
    """
    pharmacy = register_pharmacy(name="Bay Compounding")

    response = api.create_supply_lot(
        create_supply_lot_payload(
            pharmacy["id"], lot_code="P-9", strength_mg=0.25, total_units=18
        ),
        platform_admin_headers(),
    )
    lot = validate_success(response, 201)

    assert_supply_lot(lot)
    assert lot["total_units"] == 18
    assert lot["available_units"] == 18
    assert lot["reserved_units"] == 0
    assert lot["dispensed_units"] == 0


def test_clinician_without_npi_is_refused_while_coach_is_accepted(api):
    """PRD §3.1: "An `npi` — the national provider identifier — is mandatory when
    `provider_type` is `CLINICIAN`; a request registering a clinician without one
    is rejected with `ERR_VALIDATION`."
    PRD §3.1: "Each carries a `full_name`, a `licensed_state_codes` array of
    two-letter state codes (defaulting to the empty list) naming where that
    practitioner may see members, and a `status` of `ACTIVE` or `SUSPENDED` that
    defaults to `ACTIVE`."

    Design: Corner/entities/clinician_without_npi_rejected
    """
    set_clock("2026-06-01T00:00:00Z")

    refused = api.create_provider(
        {
            "full_name": "Dr No Npi",
            "provider_type": "CLINICIAN",
            "licensed_state_codes": ["CA"],
        },
        platform_admin_headers(),
    )
    validate_error(refused, "ERR_VALIDATION")

    accepted = api.create_provider(
        {
            "full_name": "Coach No Npi",
            "provider_type": "COACH",
            "licensed_state_codes": ["CA"],
        },
        platform_admin_headers(),
    )
    coach = validate_success(accepted, 201)
    assert_provider(coach)
    assert coach["provider_type"] == "COACH"
    assert coach["status"] == "ACTIVE"


def test_lot_citing_an_unknown_pharmacy_returns_pharmacy_resource_not_found(api):
    """PRD §2.6: "A Pharmacy or a Supply Lot yields
    `ERR_PHARMACY_RESOURCE_NOT_FOUND`."
    PRD §2.7: "**Body reference existence.** Every foreign identifier supplied in
    a request body resolves to an existing row, routed to the 404 codes of §2.6.
    This applies to the nine creation operations that carry references: opening a
    screening, booking a consult, issuing a prescription, filing a prior
    authorisation, creating a pharmacy order, starting a subscription, filing a
    check-in, booking a coaching session, and recording a supply lot."

    Design: Corner/entities/supply_lot_parent_pharmacy_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_supply_lot(
        {
            "pharmacy_id": "99999999-8888-7777-6666-555555555555",
            "lot_code": "GHOST",
            "strength_mg": 0.25,
            "total_units": 5,
            "window_capacity_units": 5,
            "expires_at": "2026-12-31T00:00:00Z",
            "status": "RELEASED",
        },
        platform_admin_headers(),
    )
    validate_error(response, "ERR_PHARMACY_RESOURCE_NOT_FOUND")

    rows, meta = validate_paginated(api.list_supply_lots(platform_admin_headers()))
    assert meta["total_count"] == 0, "a refused lot must not be written"


def test_envelope_shape_on_object_and_array_reads(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/endpoints/response_envelope_shape_on_object_and_array_reads
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(email="env1@example.com", full_name="Env One")
    clinician = register_clinician()
    open_screening(member["id"], clinician["id"])

    single = api.get_patient(member["id"], platform_admin_headers())
    single_body = single.json()
    single_data = validate_success(single)
    assert single_body["response_type"] == "object"
    assert single_data["id"] == member["id"]
    assert single_body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(single_body["meta"]["api_request_timestamp"], str)

    listed = api.list_screenings(
        platform_admin_headers(), params={"patient_id": member["id"]}
    )
    listed_body = listed.json()
    rows, meta = validate_paginated(listed)
    assert listed_body["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert listed_body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(listed_body["meta"]["api_request_timestamp"], str)


def test_limit_above_one_hundred_is_refused_and_one_hundred_is_accepted(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is a validation failure and is rejected with `ERR_VALIDATION`
    (400)."

    Design: Corner/endpoints/pagination_limit_above_maximum_rejected
    """
    pharmacy = register_pharmacy(name="Bay Compounding")
    record_supply_lot(pharmacy["id"], lot_code="PG-1", total_units=5, window_capacity_units=5)

    refused = api.list_supply_lots(
        platform_admin_headers(), params={"pharmacy_id": pharmacy["id"], "limit": 101}
    )
    validate_error(refused, "ERR_VALIDATION")

    accepted = api.list_supply_lots(
        platform_admin_headers(), params={"pharmacy_id": pharmacy["id"], "limit": 100}
    )
    rows, meta = validate_paginated(accepted)
    assert meta["total_count"] == 1


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the capacity the caller is
    acting in. If either header is absent, or if `X-User-Role` is not one of the six
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    member = enroll_patient(email="rb1@example.com", full_name="Rb One")

    anonymous = api.get_patient(member["id"], NO_AUTH_HEADERS)
    validate_error(anonymous, "ERR_UNAUTHENTICATED")

    authenticated = api.get_patient(member["id"], platform_admin_headers())
    data = validate_success(authenticated)
    assert data["id"] == member["id"]


def test_unknown_identifiers_route_to_collection_scoped_not_found_codes(api):
    """PRD §2.6: "A Provider that does not resolve yields
    `ERR_PROVIDER_NOT_FOUND` — this covers `provider_id`,
    `prescriber_provider_id`, `second_signer_provider_id` and
    `coach_provider_id` alike."
    PRD §2.6: "An Eligibility Screening, Consult, Prescription, Titration Step or
    Check-In yields `ERR_CLINICAL_RECORD_NOT_FOUND`."
    PRD §2.6: "A Prior Authorization or Pharmacy Order yields
    `ERR_FULFILLMENT_RECORD_NOT_FOUND`."
    PRD §2.6: "A Subscription, Billing Cycle or Coaching Session yields
    `ERR_BILLING_RECORD_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_collection_scoped_not_found_errors
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(email="nf1@example.com", full_name="Nf One")
    ghost = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    booking = api.create_consult(
        {
            "patient_id": member["id"],
            "provider_id": ghost,
            "scheduled_start_at": "2026-06-03T15:00:00Z",
            "scheduled_end_at": "2026-06-03T15:30:00Z",
        },
        make_patient_headers(member["id"]),
    )
    validate_error(booking, "ERR_PROVIDER_NOT_FOUND")

    validate_error(
        api.get_prescription(ghost, platform_admin_headers()),
        "ERR_CLINICAL_RECORD_NOT_FOUND",
    )
    validate_error(
        api.get_pharmacy_order(ghost, platform_admin_headers()),
        "ERR_FULFILLMENT_RECORD_NOT_FOUND",
    )
    validate_error(
        api.get_subscription(ghost, platform_admin_headers()),
        "ERR_BILLING_RECORD_NOT_FOUND",
    )
