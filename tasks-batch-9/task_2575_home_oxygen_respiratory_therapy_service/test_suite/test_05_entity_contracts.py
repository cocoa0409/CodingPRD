"""Entity contracts: creation, retrieval, listing, defaults, identity and uniqueness.

Every test builds all of its own state against an empty database whose logical
clock sits at its startup default of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    DELIVERY_DRIVER,
    INTAKE_COORDINATOR,
    PHYSICIAN,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    api_client,
    assert_branch,
    assert_clock_advance_result,
    assert_cmn,
    assert_equipment_unit,
    assert_immutable_record_fields,
    assert_pagination_meta,
    assert_patient,
    assert_qualifying_test,
    assert_request_meta,
    create_branch_payload,
    create_cmn_payload,
    create_delivery_route_payload,
    create_equipment_unit_payload,
    create_patient_payload,
    create_qualifying_test_payload,
    create_rental_contract_payload,
    create_route_stop_payload,
    is_valid_uuid,
    make_branch,
    make_delivery_route,
    make_equipment_unit,
    make_patient,
    read_equipment_unit,
    read_patient,
    retire_unit,
    set_clock_payload,
    setup_open_contract,
    setup_posted_month,
    setup_qualifying_study,
    update_patient_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical unresolvable identifier: no chain in this suite ever mints it.
MISSING_ID = "00000000-0000-0000-0000-0000000000ff"


def test_branch_registration_returns_all_declared_and_common_fields():
    """A registered branch echoes all six declared inputs plus the four common properties in the standard success envelope.

    PRD: "A `BranchManager` registers one by supplying a human-readable `name` of 1 to 120 characters and a `state_code` of exactly two uppercase letters identifying the US state it operates in."

    Design: Corner/entities/branch_creation_returns_every_declared_field_in_the_success_envelope
    """
    payload = create_branch_payload(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=True,
        refill_capacity_per_day=6,
        tank_exchange_buffer_minutes=45,
    )
    response = api_client.create_branch(payload, BRANCH_MANAGER)
    created = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert_request_meta(response)
    assert_branch(created)

    assert created["name"] == "Tampa Bay"
    assert created["state_code"] == "FL"
    assert created["competitive_bid_area"] is True
    assert created["liquid_oxygen_certified"] is True
    assert created["refill_capacity_per_day"] == 6
    assert created["tank_exchange_buffer_minutes"] == 45

    assert is_valid_uuid(created["id"])
    assert created["version"] == 1
    # created_at and updated_at come from the logical clock, not from wall time.
    assert created["created_at"].startswith("2026-08-01T00:00:00")
    assert created["updated_at"] == created["created_at"]

    read_response = api_client.get_branch(created["id"], BRANCH_MANAGER)
    read_back = validate_success(read_response)
    assert read_response.json()["response_type"] == "object"
    for field in (
        "id",
        "name",
        "state_code",
        "competitive_bid_area",
        "liquid_oxygen_certified",
        "refill_capacity_per_day",
        "tank_exchange_buffer_minutes",
        "created_at",
        "updated_at",
        "version",
    ):
        assert read_back[field] == created[field], f"{field} must round-trip unchanged"


def test_admitted_patient_reads_back_with_its_derived_defaults():
    """A freshly admitted patient round-trips with every derived field at its admission value.

    PRD: "On admission the patient's derived fields are all initialised: lifecycle `status` becomes `ACTIVE`, `current_cmn_status` becomes `NONE`, `oxygen_safety_risk_score` becomes 0.00, `risk_variant_applied` becomes `NONE` and `compliance_hold` becomes false."

    Design: Corner/entities/patient_creation_and_retrieval_round_trip
    """
    branch = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )

    payload = create_patient_payload(
        branch["id"],
        mrn="MRN-0200",
        full_name="Ada Kovac",
        payer_type="MEDICAID",
        mobility_profile="LIMITED_AMBULATORY",
        altitude_feet=1200,
    )
    admitted = validate_success(api_client.create_patient(payload, INTAKE_COORDINATOR), 201)
    fetched = validate_success(
        api_client.get_patient(admitted["id"], RESPIRATORY_THERAPIST)
    )

    assert_patient(admitted)
    assert_patient(fetched)

    for row in (admitted, fetched):
        assert row["mrn"] == "MRN-0200"
        assert row["full_name"] == "Ada Kovac"
        assert row["branch_id"] == branch["id"]
        assert row["payer_type"] == "MEDICAID"
        assert row["mobility_profile"] == "LIMITED_AMBULATORY"
        assert row["altitude_feet"] == 1200
        assert row["status"] == "ACTIVE"
        assert row.get("transfer_to_branch_id") is None
        assert row.get("transfer_effective_date") is None
        assert row["current_cmn_status"] == "NONE"
        assert float(row["oxygen_safety_risk_score"]) == 0.00
        assert row["risk_variant_applied"] == "NONE"
        assert row["compliance_hold"] is False

    assert fetched["id"] == admitted["id"]
    # A read is not a mutation, so the revision counter stays where the create left it.
    assert admitted["version"] == 1
    assert fetched["version"] == 1


def test_fleet_listing_filters_the_population_before_paginating():
    """The fleet list applies its branch and status filters before the page window, so total_count reports the filtered population.

    PRD: "The `meta` block of a list response carries all four pagination fields: `limit` and `offset` echo the effective values used for the page, `total_count` reports how many rows matched the filters before the page window was applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/equipment_unit_listing_with_filters_and_pagination
    """
    tampa = make_branch(name="Tampa Bay", state_code="FL", competitive_bid_area=True)
    sarasota = make_branch(
        name="Sarasota", state_code="FL", competitive_bid_area=False
    )

    make_equipment_unit(
        tampa["id"],
        serial_number="SC-1001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        next_pm_due_date="2027-06-01",
    )
    make_equipment_unit(
        tampa["id"],
        serial_number="SC-1002",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        next_pm_due_date="2027-05-01",
    )
    make_equipment_unit(
        tampa["id"],
        serial_number="PC-2001",
        model_code="POC-3L",
        equipment_class="PORTABLE_CONCENTRATOR",
        max_continuous_lpm=3.0,
        max_pulse_setting=5,
        next_pm_due_date="2027-06-01",
    )
    far_unit = make_equipment_unit(
        sarasota["id"],
        serial_number="SC-9001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        next_pm_due_date="2027-06-01",
    )

    first_response = api_client.list_equipment_units(
        BRANCH_MANAGER,
        params={"branch_id": tampa["id"], "status": "IN_STOCK", "limit": 2, "offset": 0},
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3)
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api_client.list_equipment_units(
            BRANCH_MANAGER,
            params={
                "branch_id": tampa["id"],
                "status": "IN_STOCK",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert len(second_rows) == 1
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3)
    assert second_meta["has_more"] is False

    paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert far_unit["id"] not in paged_ids, (
        "the branch filter is applied before the page window, so another branch's unit never appears"
    )
    assert len(set(paged_ids)) == 3

    model_rows, model_meta = validate_paginated(
        api_client.list_equipment_units(
            COMPLIANCE_AUDITOR, params={"model_code": "CONC-5L"}
        )
    )
    assert model_meta["total_count"] == 3, "the model filter crosses branches"
    assert_pagination_meta(model_meta, limit=10, offset=0, total_count=3)
    assert len(model_rows) == 3
    assert far_unit["id"] in [row["id"] for row in model_rows]


def test_out_of_range_pagination_arguments_are_refused():
    """A limit outside 1 through 100, or a negative offset, is refused before any row is read.

    PRD: "A `limit` that is not an integer in the range 1 through 100 inclusive, or an `offset` that is not an integer greater than or equal to 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/invalid_pagination_arguments_rejected
    """
    make_branch(name="Tampa Bay", state_code="FL")

    below_minimum = api_client.list_branches(BRANCH_MANAGER, params={"limit": 0})
    validate_error(below_minimum, ApiErrorId.ERR_INVALID_PAGINATION.value)
    assert below_minimum.json()["response_type"] == "error"

    above_maximum = api_client.list_branches(BRANCH_MANAGER, params={"limit": 101})
    validate_error(above_maximum, ApiErrorId.ERR_INVALID_PAGINATION.value)

    negative_offset = api_client.list_branches(BRANCH_MANAGER, params={"offset": -1})
    validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION.value)

    for rejected in (below_minimum, above_maximum, negative_offset):
        body = rejected.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert not isinstance(body["data"], list)

    rows, meta = validate_paginated(
        api_client.list_branches(BRANCH_MANAGER, params={"limit": 100, "offset": 0})
    )
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1)
    assert len(rows) == 1


def test_each_entity_reports_its_own_existence_error_on_read():
    """Every resource read answers an unresolvable path identifier with the existence error belonging to that path segment.

    PRD: "The full set of path-segment existence errors is: `ERR_BRANCH_NOT_FOUND` for a branch segment, `ERR_PATIENT_NOT_FOUND` for a patient segment, `ERR_QUALIFYING_TEST_NOT_FOUND` for a qualifying-study segment, `ERR_CMN_NOT_FOUND` for a certificate segment, `ERR_CONTRACT_NOT_FOUND` for a rental-contract segment, `ERR_EQUIPMENT_UNIT_NOT_FOUND` for a fleet-unit segment, `ERR_PLACEMENT_NOT_FOUND` for a placement segment, `ERR_ROUTE_NOT_FOUND` for a delivery-route segment, `ERR_ROUTE_STOP_NOT_FOUND` for a route-stop segment, `ERR_RECALL_NOTICE_NOT_FOUND` for a recall-notice segment, `ERR_TRAVEL_AUTHORIZATION_NOT_FOUND` for a travel-authorization segment, and `ERR_POSTED_MONTH_NOT_FOUND` for a posted-month segment. All are HTTP 404."

    Design: Corner/entities/not_found_on_get_by_id_for_every_entity
    """
    # Nothing is created, so every identifier below is unresolvable.
    reads = [
        (api_client.get_branch(MISSING_ID, BRANCH_MANAGER), ApiErrorId.ERR_BRANCH_NOT_FOUND),
        (api_client.get_patient(MISSING_ID, INTAKE_COORDINATOR), ApiErrorId.ERR_PATIENT_NOT_FOUND),
        (
            api_client.get_qualifying_test(MISSING_ID, INTAKE_COORDINATOR),
            ApiErrorId.ERR_QUALIFYING_TEST_NOT_FOUND,
        ),
        (api_client.get_cmn(MISSING_ID, PHYSICIAN), ApiErrorId.ERR_CMN_NOT_FOUND),
        (
            api_client.get_rental_contract(MISSING_ID, BILLING_SPECIALIST),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        ),
        (
            api_client.get_equipment_unit(MISSING_ID, BRANCH_MANAGER),
            ApiErrorId.ERR_EQUIPMENT_UNIT_NOT_FOUND,
        ),
        (
            api_client.get_placement(MISSING_ID, RESPIRATORY_THERAPIST),
            ApiErrorId.ERR_PLACEMENT_NOT_FOUND,
        ),
        (
            api_client.get_delivery_route(MISSING_ID, DELIVERY_DRIVER),
            ApiErrorId.ERR_ROUTE_NOT_FOUND,
        ),
        (
            api_client.get_route_stop(MISSING_ID, DELIVERY_DRIVER),
            ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND,
        ),
        (
            api_client.get_recall_notice(MISSING_ID, COMPLIANCE_AUDITOR),
            ApiErrorId.ERR_RECALL_NOTICE_NOT_FOUND,
        ),
        (
            api_client.get_travel_authorization(MISSING_ID, INTAKE_COORDINATOR),
            ApiErrorId.ERR_TRAVEL_AUTHORIZATION_NOT_FOUND,
        ),
    ]

    observed = []
    for response, expected_error in reads:
        validate_error(response, expected_error.value)
        body = response.json()
        assert response.status_code == 404, (
            f"{expected_error.value} is an HTTP 404, got {response.status_code}"
        )
        assert body["response_type"] == "error"
        observed.append(body["data"]["error_id"])

    assert len(set(observed)) == 11, (
        "each entity answers with its own existence error, never a shared generic 404"
    )


def test_unresolvable_body_references_report_their_own_errors():
    """A foreign key carried in the request body is resolved with the same rigour as a path identifier and reports the error belonging to that reference.

    PRD: "Identifiers supplied in a *request body* rather than in the path are checked later in the ladder (see §2.10) but reuse the same error identifiers: a body-supplied serving or receiving branch that does not resolve reports `ERR_BRANCH_NOT_FOUND`, a body-supplied patient reports `ERR_PATIENT_NOT_FOUND`, a body-supplied qualifying study reports `ERR_QUALIFYING_TEST_NOT_FOUND`, a body-supplied certificate reports `ERR_CMN_NOT_FOUND`, a body-supplied contract reports `ERR_CONTRACT_NOT_FOUND`, a body-supplied route reports `ERR_ROUTE_NOT_FOUND`, and a body-supplied predecessor unit reports `ERR_EQUIPMENT_UNIT_NOT_FOUND`."

    Design: Corner/entities/body_foreign_key_references_not_found_rejected
    """
    scenario = setup_open_contract(
        branch_overrides={
            "name": "Tampa Bay",
            "state_code": "FL",
            "competitive_bid_area": True,
            "liquid_oxygen_certified": False,
            "refill_capacity_per_day": 4,
            "tank_exchange_buffer_minutes": 30,
        },
        unit_specs=[],
        patient_overrides={
            "mrn": "MRN-0210",
            "full_name": "Bo Nilsen",
            "payer_type": "MEDICARE_COMPETITIVE_BID",
            "mobility_profile": "HOMEBOUND",
            "altitude_feet": 500,
        },
        contract_overrides={
            "pricing_basis": "COMPETITIVE_BID_SINGLE_PAYMENT",
            "cap_month_limit": 36,
        },
    )
    branch_id = scenario["branch"]["id"]
    patient_id = scenario["patient"]["id"]
    contract_id = scenario["contract"]["id"]
    route = make_delivery_route(branch_id)

    # A body-supplied branch that does not resolve.
    unresolvable_branch = api_client.create_patient(
        create_patient_payload(
            MISSING_ID,
            mrn="MRN-0211",
            full_name="Cy Odell",
            payer_type="MEDICAID",
            mobility_profile="HOMEBOUND",
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(unresolvable_branch, ApiErrorId.ERR_BRANCH_NOT_FOUND.value)
    _, patients_meta = validate_paginated(
        api_client.list_patients(INTAKE_COORDINATOR, params={"branch_id": branch_id})
    )
    assert patients_meta["total_count"] == 1, "the refused admission created no Patient row"

    # A body-supplied patient that does not resolve.
    unresolvable_patient = api_client.create_qualifying_test(
        create_qualifying_test_payload(MISSING_ID), INTAKE_COORDINATOR
    )
    validate_error(unresolvable_patient, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)
    _, tests_meta = validate_paginated(
        api_client.list_qualifying_tests(INTAKE_COORDINATOR, params={"patient_id": patient_id})
    )
    assert tests_meta["total_count"] == 1, "the refused study created no QualifyingTest row"

    # The body qualifying-study reference is resolved before the concurrency token
    # is compared, so a stale token cannot mask the missing study.
    assert read_patient(patient_id)["version"] > 1, (
        "the certificate chain has already advanced the patient, so version 1 is a stale token"
    )
    unresolvable_study = api_client.create_cmn(
        create_cmn_payload(
            patient_id,
            MISSING_ID,
            1,
            form_type="INITIAL",
            prescribed_lpm=3.0,
            hours_per_day=24,
            length_of_need_months=99,
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(unresolvable_study, ApiErrorId.ERR_QUALIFYING_TEST_NOT_FOUND.value)

    # A body-supplied certificate that does not resolve.
    unresolvable_cmn = api_client.create_rental_contract(
        create_rental_contract_payload(patient_id, MISSING_ID, pricing_basis="CASH"),
        BILLING_SPECIALIST,
    )
    validate_error(unresolvable_cmn, ApiErrorId.ERR_CMN_NOT_FOUND.value)
    _, contracts_meta = validate_paginated(
        api_client.list_rental_contracts(BILLING_SPECIALIST, params={"patient_id": patient_id})
    )
    assert contracts_meta["total_count"] == 1, "the refused contract created no RentalContract row"

    # Route and contract references are distinguished, one per request.
    unresolvable_route = api_client.create_route_stop(
        create_route_stop_payload(MISSING_ID, contract_id), BRANCH_MANAGER
    )
    validate_error(unresolvable_route, ApiErrorId.ERR_ROUTE_NOT_FOUND.value)

    unresolvable_contract = api_client.create_route_stop(
        create_route_stop_payload(route["id"], MISSING_ID), BRANCH_MANAGER
    )
    validate_error(unresolvable_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)

    # A body-supplied predecessor unit that does not resolve.
    unresolvable_predecessor = api_client.create_equipment_unit(
        create_equipment_unit_payload(
            branch_id, serial_number="SC-1099", replaces_unit_id=MISSING_ID
        ),
        BRANCH_MANAGER,
    )
    validate_error(unresolvable_predecessor, ApiErrorId.ERR_EQUIPMENT_UNIT_NOT_FOUND.value)
    _, units_meta = validate_paginated(
        api_client.list_equipment_units(BRANCH_MANAGER, params={"branch_id": branch_id})
    )
    assert units_meta["total_count"] == 0, "the refused registration created no EquipmentUnit row"


def test_reversing_a_month_absent_from_the_ledger_is_refused():
    """A reversal naming a month that the contract never posted is refused, and the ledger is untouched.

    PRD: "A `BillingSpecialist` reverses a posted month by naming it in the path; the month must match the `service_month` of an existing element of `posted_months`, or the request is refused with `ERR_POSTED_MONTH_NOT_FOUND`, and the contract must not be `CLOSED`."

    Design: Corner/entities/posted_month_not_found_on_reversal_rejected
    """
    scenario = setup_posted_month(
        service_month="2026-08",
        branch_overrides={
            "name": "Tampa Bay",
            "state_code": "FL",
            "competitive_bid_area": True,
            "liquid_oxygen_certified": False,
            "refill_capacity_per_day": 4,
            "tank_exchange_buffer_minutes": 30,
        },
        unit_specs=[
            {
                "serial_number": "SC-1001",
                "model_code": "CONC-5L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            }
        ],
        patient_overrides={
            "mrn": "MRN-0220",
            "full_name": "Dov Halper",
            "payer_type": "MEDICARE_COMPETITIVE_BID",
            "mobility_profile": "HOMEBOUND",
            "altitude_feet": 500,
        },
        contract_overrides={
            "pricing_basis": "COMPETITIVE_BID_SINGLE_PAYMENT",
            "cap_month_limit": 36,
        },
    )
    contract_id = scenario["contract"]["id"]

    posted = validate_success(api_client.get_rental_contract(contract_id, BILLING_SPECIALIST))
    assert posted["monthly_allowable_cents"] == 5590
    assert posted["posted_month_count"] == 1

    refused = api_client.reverse_billing_month(contract_id, "2026-07", BILLING_SPECIALIST)
    validate_error(refused, ApiErrorId.ERR_POSTED_MONTH_NOT_FOUND.value)
    assert refused.status_code == 404

    after = validate_success(api_client.get_rental_contract(contract_id, BILLING_SPECIALIST))
    assert after["posted_month_count"] == 1
    assert after["lifetime_paid_cents"] == 5590
    assert len(after["posted_months"]) == 1
    assert after["posted_months"][0]["service_month"] == "2026-08"
    assert after["last_posted_service_month"] == "2026-08"
    # A month absent from the ledger never reaches the fiscal cap rule.
    assert after["billing_status"] == "ACCRUING"


def test_omitting_a_required_field_refuses_the_create():
    """Omitting any field an endpoint declares required refuses the create and persists nothing.

    PRD: "17. `ERR_INVALID_REQUEST` — every field the endpoint declares as required is present, every supplied value matches its declared type, and every numeric value lies inside its declared range."

    Design: Corner/entities/missing_required_fields_rejected_on_create
    """
    branch = make_branch(name="Tampa Bay", state_code="FL")

    # mrn is required on patient admission.
    without_mrn = create_patient_payload(
        branch["id"],
        full_name="Eli Prakash",
        payer_type="MEDICAID",
        mobility_profile="HOMEBOUND",
    )
    without_mrn.pop("mrn")
    without_mrn.pop("altitude_feet")
    validate_error(
        api_client.create_patient(without_mrn, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # next_pm_due_date is required on fleet-unit registration, while
    # max_pulse_setting and pm_interval_days are optional.
    without_due_date = create_equipment_unit_payload(
        branch["id"],
        serial_number="SC-1001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
    )
    without_due_date.pop("next_pm_due_date")
    without_due_date.pop("max_pulse_setting")
    without_due_date.pop("pm_interval_days")
    validate_error(
        api_client.create_equipment_unit(without_due_date, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # driver_user_id is required on route planning.
    without_driver = create_delivery_route_payload(
        branch["id"],
        service_date="2026-08-01",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T22:00:00Z",
    )
    without_driver.pop("driver_user_id")
    validate_error(
        api_client.create_delivery_route(without_driver, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # name is required on branch registration.
    validate_error(
        api_client.create_branch({"state_code": "FL"}, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, patients_meta = validate_paginated(
        api_client.list_patients(INTAKE_COORDINATOR, params={"branch_id": branch["id"]})
    )
    assert patients_meta["total_count"] == 0, "a rejected create persists nothing"
    _, units_meta = validate_paginated(
        api_client.list_equipment_units(BRANCH_MANAGER, params={"branch_id": branch["id"]})
    )
    assert units_meta["total_count"] == 0, "a rejected create persists nothing"
    _, routes_meta = validate_paginated(
        api_client.list_delivery_routes(BRANCH_MANAGER, params={"branch_id": branch["id"]})
    )
    assert routes_meta["total_count"] == 0, "a rejected create persists nothing"


def test_omitted_optional_inputs_take_their_declared_defaults():
    """Optional inputs omitted at registration come back as their declared defaults rather than as null.

    PRD: "Four operating parameters may be supplied at registration and all four have defaults: `competitive_bid_area` marks whether the branch sits inside a Medicare competitive-bidding area and defaults to false; `liquid_oxygen_certified` marks whether the branch is licensed to fill and deliver liquid oxygen and defaults to false; `refill_capacity_per_day` caps how many portable-refill stops the branch can service on a single route and defaults to 4, accepting any value from 0 through 40; and `tank_exchange_buffer_minutes` sets the trailing turnaround buffer appended to every stop window on the branch's routes, defaulting to 30 minutes and accepting any value from 0 through 120."

    Design: Corner/entities/omitted_optional_fields_take_declared_defaults
    """
    branch = validate_success(
        api_client.create_branch({"name": "Ocala", "state_code": "FL"}, BRANCH_MANAGER), 201
    )
    assert branch["competitive_bid_area"] is False
    assert branch["liquid_oxygen_certified"] is False
    assert branch["refill_capacity_per_day"] == 4
    assert branch["tank_exchange_buffer_minutes"] == 30
    assert isinstance(branch["refill_capacity_per_day"], int)
    assert isinstance(branch["tank_exchange_buffer_minutes"], int)

    patient_payload = create_patient_payload(
        branch["id"],
        mrn="MRN-0230",
        full_name="Fern Okoro",
        payer_type="COMMERCIAL",
        mobility_profile="HOMEBOUND",
    )
    patient_payload.pop("altitude_feet")
    patient = validate_success(
        api_client.create_patient(patient_payload, INTAKE_COORDINATOR), 201
    )
    assert patient["altitude_feet"] == 0
    assert isinstance(patient["altitude_feet"], int)
    assert patient["status"] == "ACTIVE"
    assert patient["current_cmn_status"] == "NONE"
    assert patient["compliance_hold"] is False

    unit_payload = create_equipment_unit_payload(
        branch["id"],
        serial_number="SC-1001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        next_pm_due_date="2027-06-01",
    )
    unit_payload.pop("max_pulse_setting")
    unit_payload.pop("pm_interval_days")
    unit = validate_success(
        api_client.create_equipment_unit(unit_payload, BRANCH_MANAGER), 201
    )
    assert unit["max_pulse_setting"] == 0
    assert unit["pm_interval_days"] == 365
    assert isinstance(unit["max_pulse_setting"], int)
    assert isinstance(unit["pm_interval_days"], int)
    assert unit["status"] == "IN_STOCK"
    assert unit["quarantine_reason"] == "NONE"
    assert unit["replaces_unit_id"] is None
    assert unit["recall_remediated_at"] is None
    assert_equipment_unit(unit)


def test_client_supplied_computed_fields_are_ignored_on_create():
    """Computed and system-maintained fields sent by a client are discarded rather than rejected, and the server's own values are written.

    PRD: "Fields the endpoint does not declare are ignored, and system-maintained or computed fields are ignored when supplied."

    Design: Corner/entities/computed_and_system_field_extra_field_input_ignored
    """
    scenario = setup_qualifying_study(
        branch_overrides={
            "name": "Tampa Bay",
            "state_code": "FL",
            "competitive_bid_area": True,
            "liquid_oxygen_certified": False,
            "refill_capacity_per_day": 4,
            "tank_exchange_buffer_minutes": 30,
        },
        unit_specs=[],
        patient_overrides={
            "mrn": "MRN-0240",
            "full_name": "Gia Lund",
            "payer_type": "MEDICARE_COMPETITIVE_BID",
            "mobility_profile": "HOMEBOUND",
            "altitude_feet": 500,
        },
    )
    patient_id = scenario["patient"]["id"]
    current_version = read_patient(patient_id)["version"]

    payload = create_cmn_payload(
        patient_id,
        scenario["qualifying_test"]["id"],
        current_version,
        form_type="INITIAL",
        prescribed_lpm=3.0,
        hours_per_day=24,
        portable_prescribed=False,
        length_of_need_months=99,
        narrative_element_count=3,
        status="ACTIVE",
        documentation_score=12.5,
        revision_round=7,
        signed_by_user_id="u-phys-1",
        recert_due_date="2030-01-01",
    )
    created = validate_success(api_client.create_cmn(payload, INTAKE_COORDINATOR), 201)
    assert_cmn(created)

    assert created["status"] == "DRAFT", "the declared initial state wins over a client-supplied status"
    assert float(created["documentation_score"]) == 100.00
    assert created["revision_round"] == 0
    assert created["correction_notes"] is None
    assert created["void_reason"] is None
    assert created["submitted_by_user_id"] is None
    assert created["signed_by_user_id"] is None
    assert created["audited_by_user_id"] is None
    assert created["physician_signature_date"] is None
    assert created["initial_date"] is None
    assert created["recert_due_date"] is None

    assert read_patient(patient_id)["current_cmn_status"] == "DRAFT"


def test_identifiers_and_timestamps_come_from_the_server_and_logical_clock():
    """Identifiers, timestamps and versions are server-generated, timestamps read the logical clock, and advancing the clock never restamps existing rows.

    PRD: "Most resources additionally carry `updated_at` — same ISO 8601 UTC format with three fractional digits, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row, including mutations caused by a cascade from another entity rather than by a direct request."

    Design: Corner/entities/system_identifiers_and_timestamps_are_server_generated
    """
    branch = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )
    assert branch["created_at"].startswith("2026-08-01T00:00:00")

    advance = validate_success(
        api_client.set_clock(set_clock_payload("2026-08-04T09:30:00Z"), BRANCH_MANAGER)
    )
    assert_clock_advance_result(advance)
    assert advance["current_utc"].startswith("2026-08-04T09:30:00")
    assert advance["previous_utc"].startswith("2026-08-01T00:00:00")
    assert advance["expired_cmn_count"] == 0
    assert advance["suspended_contract_count"] == 0

    patient = validate_success(
        api_client.create_patient(
            create_patient_payload(
                branch["id"],
                mrn="MRN-0250",
                full_name="Hana Iqbal",
                payer_type="MEDICAID",
                mobility_profile="HOMEBOUND",
                altitude_feet=0,
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert is_valid_uuid(patient["id"])
    assert patient["created_at"].startswith("2026-08-04T09:30:00")
    assert patient["updated_at"] == patient["created_at"]
    assert patient["version"] == 1

    # Advancing the clock never restamps rows that already exist.
    assert validate_success(api_client.get_branch(branch["id"], BRANCH_MANAGER))[
        "created_at"
    ].startswith("2026-08-01T00:00:00")

    updated = validate_success(
        api_client.update_patient(
            patient["id"],
            update_patient_payload(full_name="Hana Iqbal-Reyes"),
            INTAKE_COORDINATOR,
        )
    )
    assert updated["id"] == patient["id"]
    assert updated["version"] == 2
    assert updated["created_at"] == patient["created_at"]
    assert updated["updated_at"].startswith("2026-08-04T09:30:00")


def test_unknown_enumerated_values_are_refused_in_bodies_and_filters():
    """An enumerated value outside its declared set is refused on a create body and on a list filter, and the enum check runs before any reference lookup.

    PRD: "18. `ERR_INVALID_ENUM_VALUE` — every supplied enumerated value is a member of that field's declared set. Applies to every creating and updating endpoint that accepts an enumerated field and to every list endpoint that accepts an enumerated filter."

    Design: Corner/entities/invalid_enum_values_rejected
    """
    branch = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )

    unknown_payer = api_client.create_patient(
        create_patient_payload(
            branch["id"],
            mrn="MRN-0260",
            full_name="Ivo Marek",
            payer_type="TRICARE",
            mobility_profile="HOMEBOUND",
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(unknown_payer, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)
    assert unknown_payer.status_code == 400

    # The same body also carries an unresolvable branch, yet the enum error is
    # the one reported because the enum check comes first.
    unknown_class = api_client.create_equipment_unit(
        create_equipment_unit_payload(
            MISSING_ID,
            serial_number="SC-1001",
            model_code="CONC-5L",
            equipment_class="HELIOX_TANK",
            max_continuous_lpm=5.0,
            next_pm_due_date="2027-06-01",
        ),
        BRANCH_MANAGER,
    )
    validate_error(unknown_class, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)
    assert unknown_class.json()["data"]["error_id"] != ApiErrorId.ERR_BRANCH_NOT_FOUND.value

    unknown_filter = api_client.list_equipment_units(
        BRANCH_MANAGER, params={"status": "BROKEN"}
    )
    validate_error(unknown_filter, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)
    assert unknown_filter.json()["response_type"] == "error", (
        "an unknown list filter is an error, not an empty 200 array"
    )

    _, patients_meta = validate_paginated(api_client.list_patients(INTAKE_COORDINATOR))
    assert patients_meta["total_count"] == 0
    _, units_meta = validate_paginated(api_client.list_equipment_units(BRANCH_MANAGER))
    assert units_meta["total_count"] == 0


def test_medical_record_number_and_serial_number_are_globally_unique():
    """A medical record number and a fleet serial number collide globally, so reusing either at a different branch is refused.

    PRD: "An `IntakeCoordinator` admits a patient by supplying an `mrn` — the medical record number, 1 to 40 characters, globally unique across all patients, with a collision rejected as `ERR_DUPLICATE_MRN` — a `full_name` of 1 to 120 characters, the `branch_id` of the branch that will serve them, a `payer_type` and a `mobility_profile`."

    Design: Corner/entities/duplicate_mrn_and_duplicate_serial_number_rejected
    """
    tampa = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )
    sarasota = make_branch(
        name="Sarasota",
        state_code="FL",
        competitive_bid_area=False,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )
    make_patient(
        tampa["id"],
        mrn="MRN-0270",
        full_name="Jo Vance",
        payer_type="MEDICARE_COMPETITIVE_BID",
        mobility_profile="HOMEBOUND",
        altitude_feet=500,
    )
    make_equipment_unit(
        tampa["id"],
        serial_number="SC-1001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        max_pulse_setting=0,
        pm_interval_days=365,
        next_pm_due_date="2027-06-01",
    )

    duplicate_mrn = api_client.create_patient(
        create_patient_payload(
            sarasota["id"],
            mrn="MRN-0270",
            full_name="Kim Sato",
            payer_type="COMMERCIAL",
            mobility_profile="ACTIVE_AMBULATORY",
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(duplicate_mrn, ApiErrorId.ERR_DUPLICATE_MRN.value)
    assert duplicate_mrn.status_code == 409

    duplicate_serial = api_client.create_equipment_unit(
        create_equipment_unit_payload(
            sarasota["id"],
            serial_number="SC-1001",
            model_code="CONC-5L",
            equipment_class="STATIONARY_CONCENTRATOR",
            max_continuous_lpm=5.0,
            next_pm_due_date="2027-06-01",
        ),
        BRANCH_MANAGER,
    )
    validate_error(duplicate_serial, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER.value)
    assert duplicate_serial.status_code == 409

    # Only the collision is refused, never the branch itself.
    second = validate_success(
        api_client.create_patient(
            create_patient_payload(
                sarasota["id"],
                mrn="MRN-0271",
                full_name="Kim Sato",
                payer_type="COMMERCIAL",
                mobility_profile="ACTIVE_AMBULATORY",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert second["mrn"] == "MRN-0271"
    assert second["branch_id"] == sarasota["id"]

    _, patients_meta = validate_paginated(api_client.list_patients(INTAKE_COORDINATOR))
    assert patients_meta["total_count"] == 2
    _, units_meta = validate_paginated(api_client.list_equipment_units(BRANCH_MANAGER))
    assert units_meta["total_count"] == 1


def test_qualifying_study_is_immutable_and_carries_no_version():
    """A recorded qualifying study exposes neither updated_at nor version, and its computed outputs are stamped once at creation.

    PRD: "A qualifying study is an immutable clinical record: once written it is never edited, so a `QualifyingTest` row carries only `id` and `created_at`, and both `updated_at` and `version` are absent from its representation entirely."

    Design: Corner/entities/qualifying_test_is_immutable_and_carries_no_version
    """
    branch = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )
    patient = make_patient(
        branch["id"],
        mrn="MRN-0280",
        full_name="Lev Arnaud",
        payer_type="MEDICARE_NON_BID",
        mobility_profile="HOMEBOUND",
        altitude_feet=500,
    )

    recorded = validate_success(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(
                patient["id"],
                test_type="RESTING_ROOM_AIR",
                spo2_percent=87,
                tested_at="2026-07-25T14:00:00Z",
                ordering_physician_npi="1234567893",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    fetched = validate_success(
        api_client.get_qualifying_test(recorded["id"], PHYSICIAN)
    )

    for row in (recorded, fetched):
        assert_qualifying_test(row)
        assert_immutable_record_fields(row)
        assert "updated_at" not in row
        assert "version" not in row
        assert row["qualifying_group"] == "GROUP_I"
        assert row["validity_days"] == 30
        assert row["test_validity_expires_at"].startswith("2026-08-24T14:00:00")
        assert row["desat_minutes"] == 0
        assert row["cor_pulmonale_or_edema"] is False
        assert row["pao2_mmhg"] is None
        assert row["spo2_percent"] == 87

    assert fetched["id"] == recorded["id"]
    assert fetched["created_at"] == recorded["created_at"]


def test_replacement_unit_must_name_an_out_of_service_predecessor():
    """A replacement unit may name a predecessor only while that predecessor sits out of service, and the reverse edge of the reference is queryable.

    PRD: "A named predecessor must resolve to a real unit and must currently sit in `IN_QUARANTINE` or `RETIRED` — naming a unit that is still healthy and in circulation is rejected with `ERR_REPLACED_UNIT_NOT_REPLACEABLE`."

    Design: Corner/entities/replaces_unit_id_self_reference_must_target_quarantined_or_retired_unit
    """
    branch = make_branch(
        name="Tampa Bay",
        state_code="FL",
        competitive_bid_area=True,
        liquid_oxygen_certified=False,
        refill_capacity_per_day=4,
        tank_exchange_buffer_minutes=30,
    )
    healthy = make_equipment_unit(
        branch["id"],
        serial_number="SC-1001",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        max_pulse_setting=0,
        pm_interval_days=365,
        next_pm_due_date="2027-06-01",
    )
    predecessor = make_equipment_unit(
        branch["id"],
        serial_number="SC-1002",
        model_code="CONC-5L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=5.0,
        max_pulse_setting=0,
        pm_interval_days=365,
        next_pm_due_date="2027-05-01",
    )
    retired = retire_unit(predecessor["id"])
    assert retired["status"] == "RETIRED"
    assert healthy["status"] == "IN_STOCK"

    refused = api_client.create_equipment_unit(
        create_equipment_unit_payload(
            branch["id"],
            serial_number="SC-1003",
            model_code="CONC-5L",
            equipment_class="STATIONARY_CONCENTRATOR",
            max_continuous_lpm=5.0,
            next_pm_due_date="2027-06-01",
            replaces_unit_id=healthy["id"],
        ),
        BRANCH_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_REPLACED_UNIT_NOT_REPLACEABLE.value)
    assert refused.status_code == 422

    successor = validate_success(
        api_client.create_equipment_unit(
            create_equipment_unit_payload(
                branch["id"],
                serial_number="SC-1005",
                model_code="CONC-5L",
                equipment_class="STATIONARY_CONCENTRATOR",
                max_continuous_lpm=5.0,
                next_pm_due_date="2027-06-01",
                replaces_unit_id=predecessor["id"],
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert successor["replaces_unit_id"] == predecessor["id"]
    assert successor["status"] == "IN_STOCK"
    assert successor["version"] == 1

    reverse_rows, reverse_meta = validate_paginated(
        api_client.list_equipment_units(
            BRANCH_MANAGER, params={"replaces_unit_id": predecessor["id"]}
        )
    )
    assert reverse_meta["total_count"] == 1
    assert [row["id"] for row in reverse_rows] == [successor["id"]]

    # Registering a successor never revives the predecessor.
    assert read_equipment_unit(predecessor["id"])["status"] == "RETIRED"
