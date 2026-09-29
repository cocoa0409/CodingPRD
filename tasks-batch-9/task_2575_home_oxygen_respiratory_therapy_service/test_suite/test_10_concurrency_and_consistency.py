"""Optimistic concurrency, threshold arithmetic on an intermediate value, and the
immediacy of the cascade consistency model.

Three families of rule are exercised here, all against a live server through the
shared ApiClient:

* the two optimistic-concurrency guards the PRD declares — the certificate
  draft's ``expected_patient_version`` against its parent patient and the travel
  request's ``expected_contract_version`` against its parent rental contract —
  including the fact that an absent version field is a request-shape failure that
  outranks the concurrency check, and that a refused write leaves the parent's
  revision counter and the child collection untouched;
* the travel supply waterfall's handling surcharge, which is a threshold read off
  ``cylinders_raw`` rather than off the authorized total, so it can neither
  compound on itself nor be re-keyed on trip length;
* the consistency model of the malfunction cascade: a TIER_1 report writes the
  placement, the fleet unit, the contract, its derived monthly allowable and the
  patient's safety posture, and every one of those is already visible to the very
  next request — including the money endpoint, which refuses the month because
  the recomputed allowable has already fallen to zero.

Every test builds its own state from an empty database with the logical clock at
its startup default.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    INTAKE_COORDINATOR,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    api_client,
    assert_placement,
    assert_risk_assessment_read,
    assert_travel_authorization,
    create_cmn_payload,
    create_travel_authorization_payload,
    malfunction_payload,
    post_billing_month_payload,
    read_contract,
    read_equipment_unit,
    read_patient,
    setup_contract_in_service,
    setup_open_contract,
    setup_qualifying_study,
    validate_error,
    validate_paginated,
    validate_success,
)

# A single stationary concentrator in the primary role on a competitive-bid
# contract prices at 7752 * 1.00 * 0.7358 * 0.98 = 5590 cents per month.
STATIONARY_PRIMARY_ALLOWABLE_CENTS = 5590


def test_certificate_draft_refuses_a_stale_patient_version_token():
    """A certificate draft carrying a patient version an earlier draft already spent is refused, and the refusal writes nothing.

    PRD: "If that value does not equal the patient's current `version`, the draft is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412) and no certificate row is written."

    Design: Corner/cross_cutting_complexity_layers/stale_patient_version_rejected_on_certificate_create
    """
    scenario = setup_qualifying_study(
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500}
    )
    patient_id = scenario["patient"]["id"]
    study_id = scenario["qualifying_test"]["id"]

    observed_version = scenario["patient"]["version"]
    assert observed_version == 1, "a patient's version starts at 1 on admission"

    first = validate_success(
        api_client.create_cmn(
            create_cmn_payload(patient_id, study_id, observed_version, prescribed_lpm=3.0),
            INTAKE_COORDINATOR,
        ),
        201,
    )

    # The child write moved the parent through the mirrored certificate status.
    after_first = read_patient(patient_id)
    assert after_first["version"] == observed_version + 1
    assert after_first["current_cmn_status"] == "DRAFT"

    # The same observed token is now spent: every other field in this body is legal.
    stale = api_client.create_cmn(
        create_cmn_payload(patient_id, study_id, observed_version, prescribed_lpm=4.0),
        INTAKE_COORDINATOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PATIENT_VERSION.value)

    # Omitting the field altogether is a request-shape failure, not a concurrency one.
    missing_payload = create_cmn_payload(patient_id, study_id, prescribed_lpm=4.0)
    missing_payload.pop("expected_patient_version")
    validate_error(
        api_client.create_cmn(missing_payload, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # Neither refusal touched the parent.
    after_refusals = read_patient(patient_id)
    assert after_refusals["version"] == observed_version + 1

    second = validate_success(
        api_client.create_cmn(
            create_cmn_payload(
                patient_id, study_id, after_refusals["version"], prescribed_lpm=4.0
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert float(second["prescribed_lpm"]) == 4.0

    rows, _meta = validate_paginated(
        api_client.list_cmns(INTAKE_COORDINATOR, params={"patient_id": patient_id})
    )
    assert {row["id"] for row in rows} == {first["id"], second["id"]}, (
        "neither rejected create may leave a partial certificate row behind"
    )

    # The token that worked one call earlier is itself already spent.
    validate_error(
        api_client.create_cmn(
            create_cmn_payload(
                patient_id, study_id, after_refusals["version"], prescribed_lpm=5.0
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
    )


def test_travel_request_refuses_a_stale_contract_version_token():
    """A travel-supply request carrying a contract version that a billing post already spent is refused, and no authorization row is written.

    PRD: "A value that does not equal the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and no authorization row is written."

    Design: Corner/cross_cutting_complexity_layers/stale_contract_version_rejected_on_travel_authorization_create
    """
    scenario = setup_contract_in_service(
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500}
    )
    contract_id = scenario["contract"]["id"]

    before = read_contract(contract_id)
    assert before["service_status"] == "IN_SERVICE"
    observed_version = before["version"]

    # A billing action under a different role spends the travel clerk's token.
    posted = validate_success(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        )
    )
    assert posted["lifetime_paid_cents"] == STATIONARY_PRIMARY_ALLOWABLE_CENTS
    assert posted["version"] == observed_version + 1
    current_version = posted["version"]

    stale = api_client.create_travel_authorization(
        contract_id,
        create_travel_authorization_payload(
            observed_version,
            depart_utc="2026-08-10T00:00:00Z",
            return_utc="2026-08-11T00:00:00Z",
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

    rows, _meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract_id}
        )
    )
    assert rows == [], "the refused travel request must write no authorization row"
    assert read_contract(contract_id)["version"] == current_version, (
        "the refused create must not advance the parent contract"
    )

    authorization = validate_success(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                current_version,
                depart_utc="2026-08-10T00:00:00Z",
                return_utc="2026-08-11T00:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert_travel_authorization(authorization)
    assert authorization["status"] == "REQUESTED"
    assert authorization["trip_hours"] == 24
    assert authorization["base_liters"] == 4320
    assert authorization["reserve_liters"] == 864
    assert authorization["required_liters"] == 5184
    assert authorization["cylinders_raw"] == 8
    assert authorization["supply_cylinders_authorized"] == 9
    assert read_contract(contract_id)["version"] == current_version + 1

    # A second request whose interval and supply are both legal is still masked
    # by the concurrency check, because the accepted create spent this token too.
    validate_error(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                current_version,
                depart_utc="2026-08-20T00:00:00Z",
                return_utc="2026-08-21T00:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
    )


def test_handling_surcharge_keys_on_the_raw_cylinder_count_not_on_trip_length():
    """The travel handling surcharge triggers on the pre-surcharge cylinder count, so it neither compounds on itself nor re-keys on trip hours.

    PRD: "`handling_surcharge_cylinders` is 1 when `cylinders_raw` is 6 or more, and 0 otherwise."

    Design: Corner/cross_cutting_complexity_layers/handling_surcharge_threshold_at_five_versus_six_raw_cylinders
    """
    scenario = setup_open_contract(
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
        cmn_overrides={"prescribed_lpm": 2.0, "hours_per_day": 24},
    )
    contract_id = scenario["contract"]["id"]

    # 23 hours: one cylinder below the threshold.
    twenty_three = validate_success(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                read_contract(contract_id)["version"],
                depart_utc="2026-08-02T00:00:00Z",
                return_utc="2026-08-02T23:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert twenty_three["trip_hours"] == 23
    assert float(twenty_three["altitude_factor"]) == 1.00
    assert float(twenty_three["effective_lpm"]) == 2.00
    assert twenty_three["base_liters"] == 2760
    assert twenty_three["reserve_liters"] == 552
    assert twenty_three["required_liters"] == 3312
    assert twenty_three["cylinders_raw"] == 5
    assert twenty_three["handling_surcharge_cylinders"] == 0
    assert twenty_three["supply_cylinders_authorized"] == 5

    # 24 hours: 144 litres more crosses a cylinder boundary, and that cylinder
    # crosses the surcharge threshold, so the authorization grows by two.
    twenty_four = validate_success(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                read_contract(contract_id)["version"],
                depart_utc="2026-08-05T00:00:00Z",
                return_utc="2026-08-06T00:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert twenty_four["trip_hours"] == 24
    assert twenty_four["base_liters"] == 2880
    assert twenty_four["reserve_liters"] == 576
    assert twenty_four["required_liters"] == 3456
    assert twenty_four["cylinders_raw"] == 6
    assert twenty_four["handling_surcharge_cylinders"] == 1
    assert twenty_four["supply_cylinders_authorized"] == 7
    # The surcharged total is itself at or above the threshold and yet the
    # surcharge stays at 1: the step reads the raw count, never its own output.
    assert twenty_four["supply_cylinders_authorized"] >= 6

    # 25 hours moves the reserve tier and adds 594 litres, yet the raw cylinder
    # count and therefore the surcharge and the total are unchanged.
    twenty_five = validate_success(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                read_contract(contract_id)["version"],
                depart_utc="2026-08-10T00:00:00Z",
                return_utc="2026-08-11T01:00:00Z",
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert twenty_five["trip_hours"] == 25
    assert twenty_five["base_liters"] == 3000
    assert twenty_five["reserve_liters"] == 1050
    assert twenty_five["required_liters"] == 4050
    assert twenty_five["required_liters"] - twenty_four["required_liters"] == 594
    assert twenty_five["cylinders_raw"] == 6
    assert twenty_five["handling_surcharge_cylinders"] == 1
    assert twenty_five["supply_cylinders_authorized"] == 7

    rows, _meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract_id, "limit": 100}
        )
    )
    assert len(rows) == 3, "three pairwise disjoint closed intervals coexist"
    assert {row["status"] for row in rows} == {"REQUESTED"}


def test_tier_one_malfunction_cascade_is_readable_on_the_very_next_request():
    """Every row a TIER_1 malfunction report touches — placement, fleet unit, contract, derived allowable and patient posture — answers its new value on the next read.

    PRD: "On a `TIER_1` report the placement additionally moves `PLACED → REMOVED` with `removal_reason` set to `MALFUNCTION` and `removed_at` set to the logical clock, the fleet unit it referenced moves `DEPLOYED → IN_QUARANTINE` with `quarantine_reason` set to `MALFUNCTION`, and the contract's `monthly_allowable_cents` is recomputed over what is left in the home — which drops the allowable, and may drop it to 0 if that was the only placed unit."

    Design: Corner/consistency_model/malfunction_cascade_is_readable_in_the_same_transaction
    """
    scenario = setup_contract_in_service(
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
        setup_overrides={"patient_teachback_score": 5},
    )
    contract_id = scenario["contract"]["id"]
    patient_id = scenario["patient"]["id"]
    unit_id = scenario["stationary_unit"]["id"]
    placement_id = scenario["placement"]["id"]

    before = read_contract(contract_id)
    assert before["monthly_allowable_cents"] == STATIONARY_PRIMARY_ALLOWABLE_CENTS
    assert before["service_status"] == "IN_SERVICE"

    # NO_FLOW alone grades TIER_1; the 90-minute gap grades it on the gap too.
    placement = validate_success(
        api_client.report_malfunction(
            placement_id,
            malfunction_payload(symptom="NO_FLOW", oxygen_gap_minutes=90),
            RESPIRATORY_THERAPIST,
        )
    )
    assert_placement(placement)
    assert placement["status"] == "REMOVED"
    assert placement["removal_reason"] == "MALFUNCTION"
    assert placement["last_severity_tier"] == "TIER_1"
    assert placement["last_symptom"] == "NO_FLOW"
    assert placement["malfunction_count"] == 1

    # The unit hop needs no sweep and no second call to become visible.
    unit = read_equipment_unit(unit_id)
    assert unit["status"] == "IN_QUARANTINE"
    assert unit["quarantine_reason"] == "MALFUNCTION"

    after = read_contract(contract_id)
    assert after["monthly_allowable_cents"] == 0, (
        "the derived allowable follows the now-empty PLACED set immediately"
    )
    assert after["service_status"] == "IN_SERVICE"
    assert after["billing_status"] == "ACCRUING"
    assert after["malfunction_count"] == 1
    assert after["cumulative_oxygen_gap_minutes"] == 90

    # Smoking 0, electrical 0, teach-back 0, flow 20 at 3.0 lpm and incident 30
    # for one report: the surveillance variant takes the largest factor and adds
    # five points for the second non-zero factor.
    patient = read_patient(patient_id)
    assert float(patient["oxygen_safety_risk_score"]) == 35.00
    assert patient["risk_variant_applied"] == "ONGOING_SURVEILLANCE"
    assert patient["compliance_hold"] is False

    risk = validate_success(
        api_client.get_patient_risk_assessment(patient_id, RESPIRATORY_THERAPIST)
    )
    assert_risk_assessment_read(risk)
    assert float(risk["factor_incident"]) == 30
    assert float(risk["factor_flow"]) == 20
    assert float(risk["ongoing_surveillance_score"]) == 35.00
    assert float(risk["initial_assessment_score"]) == 9.00
    assert float(risk["persisted_score"]) == 35.00
    assert risk["persisted_variant"] == "ONGOING_SURVEILLANCE"


def test_month_posting_immediately_after_a_tier_one_report_sees_the_empty_placed_set():
    """The money endpoint invoked straight after a TIER_1 report already reads the recomputed zero allowable and refuses the month.

    PRD: "Finally the contract must actually have something in the home: its `monthly_allowable_cents` must be greater than 0, or the post is refused with `ERR_NO_PLACED_EQUIPMENT`."

    Design: Corner/consistency_model/malfunction_cascade_is_readable_in_the_same_transaction
    """
    scenario = setup_contract_in_service(
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
        setup_overrides={"patient_teachback_score": 5},
    )
    contract_id = scenario["contract"]["id"]

    assert (
        read_contract(contract_id)["monthly_allowable_cents"]
        == STATIONARY_PRIMARY_ALLOWABLE_CENTS
    ), "the month would have billed 5590 cents against a stale allowable"

    validate_success(
        api_client.report_malfunction(
            scenario["placement"]["id"],
            malfunction_payload(symptom="NO_FLOW", oxygen_gap_minutes=90),
            RESPIRATORY_THERAPIST,
        )
    )

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_NO_PLACED_EQUIPMENT.value,
    )

    ledger = read_contract(contract_id)
    assert ledger["monthly_allowable_cents"] == 0
    assert ledger["posted_months"] == []
    assert ledger["posted_month_count"] == 0
    assert ledger["lifetime_paid_cents"] == 0
    assert ledger["last_posted_service_month"] is None
