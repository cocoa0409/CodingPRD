"""Lab work orders, the remake cycle and founding the device."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approx_mm,
    assert_appliance,
    assert_calendar_date,
    assert_is_null,
    assert_lab_order,
    build_scenario,
    create_appliance_payload,
    create_lab_order_payload,
    open_and_accept_lab_case,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_appliance_cannot_be_founded_on_a_merely_shipped_lab_order(api):
    """PRD §2.6 rung 12: "an appliance creation requires the lab order to be
    `RECEIVED_ACCEPTED`"
    PRD §3.5: "`ACCEPTED` moves the order `SHIPPED → RECEIVED_ACCEPTED`, which is terminal and
    which is the only state from which a device may be founded."

    Design: Difficulty/cross_entity_state_dependency/appliance_create_requires_received_accepted_lab_order
    """
    scenario = build_scenario("lab_shipped")
    lot = validate_success(
        api.create_appliance_lot(
            {"manufacturer": "SomnoCorp", "lot_code": "LOT-A"}, scenario["admin_headers"]
        ),
        201,
    )
    validate_error(
        api.create_appliance(
            create_appliance_payload(scenario["lo_id"], lot["id"]),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    lab_order = validate_success(
        api.get_lab_order(scenario["lo_id"], scenario["dent_headers"])
    )
    assert lab_order["status"] == "SHIPPED"


def test_appliance_is_founded_once_the_dentist_accepts_the_fit(api):
    """PRD §3.5: "`ACCEPTED` moves the order `SHIPPED → RECEIVED_ACCEPTED`, which is terminal and
    which is the only state from which a device may be founded."
    PRD §3.5: "Creation copies `patient_id` from the lab order's referral, and `appliance_kind`
    and `max_protrusive_mm` from the lab order itself, and derives `hcpcs_code`: `E0486` for a
    `CUSTOM_FABRICATED` device, `A9270` for a `PREFABRICATED` one."

    Design: Difficulty/cross_entity_state_dependency/appliance_create_requires_received_accepted_lab_order
    """
    scenario = build_scenario("lab_shipped")
    lot = validate_success(
        api.create_appliance_lot(
            {"manufacturer": "SomnoCorp", "lot_code": "LOT-A"}, scenario["admin_headers"]
        ),
        201,
    )
    received = validate_success(
        api.receive_lab_order(
            scenario["lo_id"], {"fit_outcome": "ACCEPTED"}, scenario["dent_headers"]
        )
    )
    assert received["status"] == "RECEIVED_ACCEPTED"

    appliance = validate_success(
        api.create_appliance(
            create_appliance_payload(scenario["lo_id"], lot["id"]),
            scenario["dent_headers"],
        ),
        201,
    )
    assert_appliance(appliance)
    assert appliance["lifecycle_status"] == "FABRICATED"
    assert appliance["appliance_kind"] == "CUSTOM_FABRICATED"
    assert appliance["hcpcs_code"] == "E0486"
    assert appliance["max_protrusive_mm"] == approx_mm(8.00)


def test_appliance_derives_its_computed_fields_from_the_lab_case(api):
    """PRD §3.5: "Creation copies `patient_id` from the lab order's referral, and
    `appliance_kind` and `max_protrusive_mm` from the lab order itself, and derives
    `hcpcs_code`: `E0486` for a `CUSTOM_FABRICATED` device, `A9270` for a `PREFABRICATED` one."
    PRD §3.5: "The new device starts on all three of its axes at once — `lifecycle_status`
    `FABRICATED`, `device_hold_status` `NONE`, `recall_status` `NOT_SCHEDULED` — with
    `applied_visit_count` and `recall_cycle_index` at 0 and every date field null."

    Design: Corner/entities/appliance_computed_fields_are_derived_not_supplied
    """
    scenario = build_scenario("fabricated")
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert_appliance(appliance)
    assert appliance["appliance_kind"] == "CUSTOM_FABRICATED"
    assert appliance["hcpcs_code"] == "E0486"
    assert appliance["patient_id"] == scenario["pat_id"]
    assert appliance["max_protrusive_mm"] == approx_mm(8.00)
    assert_is_null(appliance["current_advancement_mm"], "Appliance.current_advancement_mm")
    assert appliance["lifecycle_status"] == "FABRICATED"
    assert appliance["device_hold_status"] == "NONE"
    assert appliance["recall_status"] == "NOT_SCHEDULED"


def test_lab_remake_cycle_reruns_fabrication_and_counts_the_remake(api):
    """PRD §3.5: "`REMAKE_REQUIRED` moves it `SHIPPED → REMAKE_REQUIRED` and clears `shipped_on`
    and `turnaround_on_time` back to null, because the shipment that was measured no longer
    counts."
    PRD §3.5: "From `REMAKE_REQUIRED` the dentist submits again — the same capability, with the
    referral still required to be `ACCEPTED` — which returns the order to `IN_FABRICATION`,
    raises `remake_count` by 1, resets `submitted_on` to the current clock date and recomputes
    `promised_ship_date` from it."
    PRD §3.5: "Shipping moves the order `IN_FABRICATION → SHIPPED` and sets `turnaround_on_time`
    to true exactly when `shipped_on` is not later than `promised_ship_date`, and to false
    otherwise."

    Design: Corner/state_machines/lab_order_remake_cycle_increments_remake_count
    """
    scenario = build_scenario("referral_accepted")
    set_clock("2026-05-04T00:00:00Z")
    lab_order = validate_success(
        api.create_lab_order(
            create_lab_order_payload(scenario["ref_id"], scenario["lab_id"]),
            scenario["dent_headers"],
        ),
        201,
    )
    validate_success(
        api.submit_lab_order(lab_order["id"], {}, scenario["dent_headers"])
    )
    validate_success(
        api.ship_lab_order(
            lab_order["id"], {"shipped_on": "2026-05-15"}, scenario["lab_headers"]
        )
    )
    remade = validate_success(
        api.receive_lab_order(
            lab_order["id"], {"fit_outcome": "REMAKE_REQUIRED"}, scenario["dent_headers"]
        )
    )
    assert remade["status"] == "REMAKE_REQUIRED"
    assert_is_null(remade["shipped_on"], "LabOrder.shipped_on")

    refabricating = validate_success(
        api.submit_lab_order(
            lab_order["id"], {"promised_turnaround_days": 7}, scenario["dent_headers"]
        )
    )
    assert refabricating["status"] == "IN_FABRICATION"
    assert refabricating["remake_count"] == 1
    assert_calendar_date(
        refabricating["promised_ship_date"], "2026-05-11", "LabOrder.promised_ship_date"
    )

    shipped = validate_success(
        api.ship_lab_order(
            lab_order["id"], {"shipped_on": "2026-05-08"}, scenario["lab_headers"]
        )
    )
    assert shipped["turnaround_on_time"] is True

    accepted = validate_success(
        api.receive_lab_order(
            lab_order["id"], {"fit_outcome": "ACCEPTED"}, scenario["dent_headers"]
        )
    )
    assert accepted["status"] == "RECEIVED_ACCEPTED"
    assert_lab_order(accepted)


def test_lab_order_without_max_protrusive_range_is_a_validation_failure(api):
    """PRD §2.6 rung 7: "Every field marked required in the endpoint's input list is present and
    carries the declared JSON type — otherwise `ERR_VALIDATION` (400). Applies to every
    endpoint."
    PRD §3.5: "Two measurements come off the articulator: `max_protrusive_mm`, the maximum
    protrusive range in millimetres, which must lie between 4.00 and 12.00 inclusive and be an
    exact multiple of 0.25, and which becomes the hard physical ceiling for every advancement
    that follows; and the optional `retruded_position_mm`, the retruded contact position
    reference, defaulting to 0.00."

    Design: Corner/entities/create_lab_order_missing_required_field_returns_validation
    """
    scenario = build_scenario("referral_accepted")
    validate_error(
        api.create_lab_order(
            {
                "referral_id": scenario["ref_id"],
                "lab_provider_id": scenario["lab_id"],
                "appliance_kind": "CUSTOM_FABRICATED",
                "capture_method": "DIGITAL_SCAN",
            },
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )
    rows, _meta = validate_paginated(
        api.list_lab_orders(scenario["dent_headers"], {"referral_id": scenario["ref_id"]})
    )
    assert rows == [], "the refused request must not create a lab order row"


def test_bad_enum_member_and_out_of_range_number_take_different_identifiers(api):
    """PRD §2.8: "Exactly the following request-body fields route an unrecognised value to
    `ERR_INVALID_ENUM` (HTTP 422), and **no other field in this API routes there**:"
    PRD §2.8: "Any *other* malformed input is `ERR_VALIDATION` (400) at rung 7 or rung 9 and
    never `ERR_INVALID_ENUM`: a wrong JSON type, a number outside its declared domain, a
    malformed date, an unknown field, and every free-text field — including
    `remediation_action`, `narrative`, `dispute_reason`, `scope_note`, `material`, `notes`,
    `reason` supplied alongside a referral decision, `state_license`, `dme_supplier_number`,
    `manufacturer`, `notice_reference`, `lot_code`, `serial_number`, `full_name`, `name`, `mrn`,
    `npi` and `denial_error_id`."

    Design: Corner/validations/invalid_enum_member_and_out_of_range_number_take_different_error_ids
    """
    scenario = build_scenario("referral_accepted")
    validate_error(
        api.create_lab_order(
            create_lab_order_payload(
                scenario["ref_id"], scenario["lab_id"], capture_method="LASER_HOLOGRAM"
            ),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
    )
    validate_error(
        api.create_lab_order(
            create_lab_order_payload(
                scenario["ref_id"], scenario["lab_id"], max_protrusive_mm=3.75
            ),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )
    rows, _meta = validate_paginated(
        api.list_lab_orders(scenario["dent_headers"], {"referral_id": scenario["ref_id"]})
    )
    assert rows == [], "neither malformed request may create a lab order row"


def test_second_live_device_for_one_patient_is_refused(api):
    """PRD §3.5: "Both fabrication and delivery are refused with `ERR_ACTIVE_APPLIANCE_EXISTS`
    when the patient already holds a *different* appliance whose `lifecycle_status` is
    `DELIVERED`, `IN_TITRATION`, `TITRATION_SUSPENDED`, `TITRATION_PLATEAU`, `EFFICACY_PENDING`
    or `ACTIVE_THERAPY`."
    PRD §3.5: "The single exception is a declared replacement: the fabrication request supplies,
    or the delivery's row already carries, a `replaces_appliance_id` naming that very device, and
    that device is itself in `ACTIVE_THERAPY` or `RETIRED`."

    Design: Corner/validations/second_live_appliance_for_one_patient_is_refused
    """
    scenario = build_scenario("delivered")
    second_case = open_and_accept_lab_case(scenario, shipped_on="2026-05-16")
    validate_error(
        api.create_appliance(
            create_appliance_payload(
                second_case["id"], scenario["lot_id"], serial_number="SN-0002"
            ),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_ACTIVE_APPLIANCE_EXISTS.value,
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "DELIVERED"
    rows, meta = validate_paginated(
        api.list_appliances(scenario["dent_headers"], {"patient_id": scenario["pat_id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_appliance_list_filtered_by_lot_carries_the_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger than 100;
    `offset` defaults to 0 and may be no smaller than 0."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` — the
    number of rows matching the filters *before* the page window is applied — and `has_more`,
    which is true exactly when `offset` plus the number of returned rows is less than
    `total_count`."

    Design: Corner/entities/list_appliances_filtered_by_lot_uses_pagination_envelope
    """
    scenario = build_scenario("fabricated")
    response = api.list_appliances(scenario["dent_headers"], {"lot_id": scenario["lot_id"]})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(rows) == 1 and rows[0]["id"] == scenario["app_id"]


def test_duplicate_provider_npi_is_a_duplicate_identifier(api):
    """PRD §2.9: "Four identifiers are unique, each within its own entity, and a collision on any
    of them is `ERR_DUPLICATE_IDENTIFIER` (HTTP 409): a provider's `npi`, a patient's `mrn`, an
    appliance lot's `lot_code` and an appliance's `serial_number`. Comparison is exact string
    equality and is case-sensitive, so `LOT-88a` and `LOT-88A` are distinct lot codes."

    Design: Corner/entities/duplicate_provider_npi_returns_duplicate_identifier
    """
    scenario = build_scenario("cast")
    validate_error(
        api.create_provider(
            {"npi": "1000000001", "full_name": "Dr Other", "provider_type": "DENTIST"},
            scenario["admin_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
    )
    unchanged = validate_success(
        api.get_provider(scenario["phys_id"], scenario["admin_headers"])
    )
    assert unchanged["full_name"] == "Dr Sleep"


def test_patient_registration_applies_its_declared_defaults(api):
    """PRD §3.1: "Two further inputs shape the money and the clinical fork downstream:
    `deductible_remaining_cents`, the unmet medical deductible in cents, defaulting to 0 and
    never negative; and `epworth_score`, the Epworth Sleepiness Scale score captured at intake,
    defaulting to 0 and confined to the range 0 through 24 inclusive. Finally, every patient
    carries `records_frozen`, computed and initialised to false."
    PRD §3.1: "A `Patient` carries an `mrn` — the medical record number, unique across all
    patients — plus `full_name` and `date_of_birth`, and binds two benefits: `medical_payer_id`,
    the medical benefit that adjudicates oral appliance claims, and the optional
    `dental_payer_id`, recorded for completeness and defaulting to null."

    Design: Corner/entities/create_patient_applies_declared_defaults
    """
    scenario = build_scenario("cast")
    patient = validate_success(
        api.create_patient(
            {
                "mrn": "MRN-777",
                "full_name": "Default Dan",
                "date_of_birth": "1980-01-01",
                "medical_payer_id": scenario["payer_med_id"],
            },
            scenario["coord_headers"],
        ),
        201,
    )
    assert patient["deductible_remaining_cents"] == 0
    assert patient["epworth_score"] == 0
    assert_is_null(patient["dental_payer_id"], "Patient.dental_payer_id")
    assert patient["records_frozen"] is False
    assert patient["version"] == 1


def test_patient_registration_with_an_unknown_payer_is_a_record_not_found(api):
    """PRD §2.6 rung 4: "Every foreign key supplied in the request body resolves, validated in
    the order the fields are declared in the endpoint's input list, so the first unresolvable
    reference in that order is the one reported. `patient_id` gives `ERR_PATIENT_NOT_FOUND`;
    `provider_id`, `referring_physician_id`, `treating_dentist_id`, `ordering_physician_id`,
    `lab_provider_id` and `performed_by_dentist_id` give `ERR_PROVIDER_NOT_FOUND`; `referral_id`
    gives `ERR_REFERRAL_NOT_FOUND`; `appliance_id`, `replaces_appliance_id` and
    `loaner_appliance_id` give `ERR_APPLIANCE_NOT_FOUND`; and `payer_id`, `diagnostic_study_id`,
    `efficacy_study_id`, `written_order_id`, `prior_auth_id`, `lab_order_id`, `lot_id` and
    `repair_order_id` give `ERR_RECORD_NOT_FOUND`. All HTTP 404."

    Design: Corner/entities/create_patient_with_unknown_payer_returns_record_not_found
    """
    validate_error(
        api.create_patient(
            {
                "mrn": "MRN-778",
                "full_name": "Orphan Olive",
                "date_of_birth": "1980-01-01",
                "medical_payer_id": "00000000-0000-4000-8000-000000000999",
            },
            TEST_USERS["clinic_coordinator_headers"],
        ),
        ApiErrorId.ERR_RECORD_NOT_FOUND.value,
    )
    rows, meta = validate_paginated(
        api.list_patients(TEST_USERS["clinic_coordinator_headers"])
    )
    assert meta["total_count"] == 0 and rows == []
