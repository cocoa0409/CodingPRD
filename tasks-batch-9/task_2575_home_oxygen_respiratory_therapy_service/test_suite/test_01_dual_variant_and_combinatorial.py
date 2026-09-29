"""Dual-variant calculations and pinned-order combinatorial formulas.

Four rules are exercised here:

* the cap month position, computed either on the service-month basis or on the
  paid-month basis according to the contract's ``pricing_basis``;
* the patient's oxygen safety risk score, computed either as the
  initial-assessment weighted average or as the ongoing-surveillance
  worst-factor-plus-escalation rule over one identical factor vector;
* the monthly allowable, whose equipment line items are rounded to whole cents
  before they are summed;
* the travel supply waterfall, whose handling surcharge reads the raw cylinder
  count rather than the authorized total.

Every test builds its own state: the API server is restarted before each one, so
the database is empty and the logical clock reads its startup default.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    INTAKE_COORDINATOR,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_cap_summary_read,
    assert_patient,
    assert_placement,
    assert_rental_contract,
    assert_risk_assessment_read,
    assert_travel_authorization,
    assign_equipment,
    complete_in_home_setup,
    complete_setup_payload,
    create_travel_authorization_payload,
    dispatch_route,
    drive_cmn_to_active,
    file_malfunction,
    lock_route,
    make_cmn,
    make_delivery_route,
    make_patient,
    make_qualifying_test,
    make_rental_contract,
    make_route_stop,
    placement_for_role,
    post_billing_month_payload,
    post_month,
    read_contract,
    read_patient,
    setup_contract_in_service,
    setup_dispatched_setup_stop,
    setup_open_contract,
    validate_error,
    validate_success,
)

# Four fleet units so that two contracts at the same branch can each take a
# stationary concentrator in the primary role and a portable concentrator in the
# portable role.  SC-1001 and PC-2001 carry the later preventive-maintenance due
# date, so the selection tie-break prefers them first.
FOUR_UNIT_FLEET = [
    {
        "serial_number": "SC-1001",
        "model_code": "CONC-5L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    },
    {
        "serial_number": "PC-2001",
        "model_code": "POC-3L",
        "equipment_class": "PORTABLE_CONCENTRATOR",
        "max_continuous_lpm": 3.0,
        "max_pulse_setting": 5,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    },
    {
        "serial_number": "SC-1002",
        "model_code": "CONC-5L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-05-01",
    },
    {
        "serial_number": "PC-2002",
        "model_code": "POC-3L",
        "equipment_class": "PORTABLE_CONCENTRATOR",
        "max_continuous_lpm": 3.0,
        "max_pulse_setting": 5,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-05-01",
    },
]

# One 10.0 lpm stationary concentrator, adequate for a 7.0 lpm prescription.
HIGH_FLOW_FLEET = [
    {
        "serial_number": "SC-1010",
        "model_code": "CONC-10L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 10.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    },
]


def _two_contracts_on_diverging_bases() -> dict:
    """Two patients at one branch, each holding a contract that entered service
    on 2026-08-01 with a stationary and a portable unit placed, each carrying a
    cap-month limit of 3 and a single posted service month of 2026-08.

    Contract A is priced on the competitive-bid single payment, contract B on
    the adjusted fee schedule, so the two contracts read the same ledger through
    different cap-month bases.  The clock is left at 2026-10-15, so September was
    skipped by both.
    """
    scenario = setup_contract_in_service(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        unit_specs=FOUR_UNIT_FLEET,
        patient_overrides={
            "mrn": "MRN-0001",
            "full_name": "Ada Reyes",
            "payer_type": "MEDICARE_COMPETITIVE_BID",
            "mobility_profile": "ACTIVE_AMBULATORY",
            "altitude_feet": 500,
        },
        cmn_overrides={"portable_prescribed": True},
        contract_overrides={
            "pricing_basis": "COMPETITIVE_BID_SINGLE_PAYMENT",
            "cap_month_limit": 3,
        },
        stop_overrides={"cylinders_requested": 2},
    )
    branch_id = scenario["branch"]["id"]

    patient_b = make_patient(
        branch_id,
        mrn="MRN-0002",
        full_name="Ben Okafor",
        payer_type="MEDICARE_NON_BID",
        mobility_profile="ACTIVE_AMBULATORY",
        altitude_feet=500,
    )
    test_b = make_qualifying_test(patient_b["id"])
    cmn_b = make_cmn(
        read_patient(patient_b["id"]), test_b["id"], portable_prescribed=True
    )
    drive_cmn_to_active(cmn_b["id"])
    contract_b = make_rental_contract(
        patient_b["id"],
        cmn_b["id"],
        pricing_basis="FEE_SCHEDULE_ADJUSTED",
        cap_month_limit=3,
    )
    assign_equipment(contract_b["id"], "PRIMARY_STATIONARY")
    assign_equipment(contract_b["id"], "PORTABLE")

    route_b = make_delivery_route(
        branch_id,
        service_date="2026-08-01",
        shift_start_utc="2026-08-01T12:00:00Z",
        shift_end_utc="2026-08-01T22:00:00Z",
    )
    stop_b = make_route_stop(
        route_b["id"],
        contract_b["id"],
        stop_type="SETUP_DELIVERY",
        window_start_utc="2026-08-01T14:30:00Z",
        window_end_utc="2026-08-01T15:30:00Z",
        service_minutes=60,
        cylinders_requested=2,
    )
    lock_route(route_b["id"])
    dispatch_route(route_b["id"])
    complete_in_home_setup(stop_b["id"])

    contract_a_id = scenario["contract"]["id"]
    post_month(contract_a_id, "2026-08")
    post_month(contract_b["id"], "2026-08")
    advance_clock("2026-10-15T00:00:00Z")

    return {
        "branch": scenario["branch"],
        "contract_a_id": contract_a_id,
        "contract_b_id": contract_b["id"],
    }


def _post_month_response(contract_id: str, service_month: str):
    return api_client.post_billing_month(
        contract_id, post_billing_month_payload(service_month), BILLING_SPECIALIST
    )


def test_cap_summary_reports_both_basis_positions_and_the_one_pricing_selects():
    """Two contracts with the same ledger report identical basis positions and
    diverge only in the effective cap position their pricing basis selects.

    PRD: "The divergence is real and reachable on identical data: a contract with `first_service_month` of `2026-08` and a single posted month of `2026-08`, posting `2026-10`, sits at effective position 3 under the service-month basis but position 2 under the paid-month basis."

    Design: Difficulty/dual_variant_calc/cap_position_variant_divergence_bid_vs_fee_schedule
    """
    env = _two_contracts_on_diverging_bases()

    validate_success(_post_month_response(env["contract_a_id"], "2026-10"))
    validate_success(_post_month_response(env["contract_b_id"], "2026-10"))

    summary_a = validate_success(
        api_client.get_cap_summary(env["contract_a_id"], BILLING_SPECIALIST)
    )
    summary_b = validate_success(
        api_client.get_cap_summary(env["contract_b_id"], BILLING_SPECIALIST)
    )
    assert_cap_summary_read(summary_a)
    assert_cap_summary_read(summary_b)

    # The candidate month is the last posted service month for both contracts.
    assert summary_a["candidate_service_month"] == "2026-10"
    assert summary_b["candidate_service_month"] == "2026-10"

    # Identical data yields identical positions under each basis.
    assert summary_a["service_month_basis_position"] == 3
    assert summary_b["service_month_basis_position"] == 3
    assert summary_a["paid_month_basis_position"] == 2
    assert summary_b["paid_month_basis_position"] == 2

    # Only the selected basis differs.
    assert summary_a["variant_applied"] == "SERVICE_MONTH_BASIS"
    assert summary_a["effective_position"] == 3
    assert summary_a["months_remaining"] == 0
    assert summary_b["variant_applied"] == "PAID_MONTH_BASIS"
    assert summary_b["effective_position"] == 2
    assert summary_b["months_remaining"] == 1


def test_competitive_bid_contract_reaches_cap_where_fee_schedule_keeps_accruing():
    """Posting October drives the competitive-bid contract to CAP_REACHED while
    the fee-schedule contract with the same ledger stays ACCRUING.

    PRD: "Because whether a given month lands on the self-loop or on the advance to `CAP_REACHED` depends on which basis the pricing selects, two contracts with identical posted history and identical cap limits can be in different billing states after posting the same month."

    Design: Difficulty/dual_variant_calc/cap_position_variant_divergence_bid_vs_fee_schedule
    """
    env = _two_contracts_on_diverging_bases()

    contract_a = validate_success(_post_month_response(env["contract_a_id"], "2026-10"))
    contract_b = validate_success(_post_month_response(env["contract_b_id"], "2026-10"))
    assert_rental_contract(contract_a)
    assert_rental_contract(contract_b)

    # The service-month basis counts the skipped September, so October is the
    # third rental month and lands exactly on the limit of 3.
    assert contract_a["billing_status"] == "CAP_REACHED"
    # The paid-month basis never counted September, so October is only the
    # second paid month and the contract remains on the self-loop.
    assert contract_b["billing_status"] == "ACCRUING"

    assert contract_a["monthly_allowable_cents"] == 6913
    assert contract_a["lifetime_paid_cents"] == 13826
    assert contract_a["posted_month_count"] == 2
    assert contract_b["monthly_allowable_cents"] == 8502
    assert contract_b["lifetime_paid_cents"] == 17004
    assert contract_b["posted_month_count"] == 2


def test_capped_bid_contract_refuses_november_while_fee_schedule_still_posts_it():
    """A contract already at CAP_REACHED cannot accept another month, while the
    paid-month-basis contract posts November and only then reaches its cap.

    PRD: "It must be exactly `ACCRUING`: a contract sitting in `SUSPENDED` or `CAP_REACHED` cannot accept another month, and the attempt is refused with `ERR_CONTRACT_BILLING_SUSPENDED`."

    Design: Difficulty/dual_variant_calc/cap_position_variant_divergence_bid_vs_fee_schedule
    """
    env = _two_contracts_on_diverging_bases()

    validate_success(_post_month_response(env["contract_a_id"], "2026-10"))
    validate_success(_post_month_response(env["contract_b_id"], "2026-10"))
    advance_clock("2026-11-05T00:00:00Z")

    validate_error(
        _post_month_response(env["contract_a_id"], "2026-11"),
        ApiErrorId.ERR_CONTRACT_BILLING_SUSPENDED.value,
    )
    contract_a = read_contract(env["contract_a_id"])
    assert contract_a["posted_month_count"] == 2
    assert contract_a["lifetime_paid_cents"] == 13826
    assert contract_a["last_posted_service_month"] == "2026-10"

    contract_b = validate_success(_post_month_response(env["contract_b_id"], "2026-11"))
    assert_rental_contract(contract_b)
    assert contract_b["billing_status"] == "CAP_REACHED"
    assert contract_b["posted_month_count"] == 3
    assert contract_b["lifetime_paid_cents"] == 25506
    assert contract_b["last_posted_service_month"] == "2026-11"


def _homebound_patient_in_service() -> dict:
    """One homebound patient at 500 feet on a 7.0 litre-per-minute prescription,
    whose in-home setup passed on smoking but failed the electrical inspection
    and recorded a teach-back score of 2.

    A single stationary concentrator is placed; portable oxygen is not indicated
    for a homebound patient, so no portable role is filled.
    """
    return setup_contract_in_service(
        roles=["PRIMARY_STATIONARY"],
        unit_specs=HIGH_FLOW_FLEET,
        patient_overrides={
            "mrn": "MRN-0010",
            "full_name": "Cora Vance",
            "mobility_profile": "HOMEBOUND",
            "altitude_feet": 500,
        },
        test_overrides={"spo2_percent": 85},
        cmn_overrides={"prescribed_lpm": 7.0, "portable_prescribed": False},
        setup_overrides={
            "smoking_in_home": False,
            "electrical_pass": False,
            "patient_teachback_score": 2,
        },
    )


def test_setup_completion_persists_the_initial_assessment_weighted_average():
    """Closing the in-home setup stores the weighted average of the five oxygen
    safety factors, which dilutes the single failed electrical inspection.

    PRD: "The **initial-assessment variant** is a weighted average of those five factors: the smoking factor at weight 0.30, the electrical factor at 0.15, the teach-back factor at 0.15, the flow factor at 0.30 and the incident factor at 0.10."

    Design: Difficulty/dual_variant_calc/patient_risk_variant_divergence_initial_vs_surveillance
    """
    scenario = _homebound_patient_in_service()

    patient = read_patient(scenario["patient"]["id"])
    assert_patient(patient)
    # electrical 100 at 0.15, teach-back 60 at 0.15, flow 60 at 0.30.
    assert float(patient["oxygen_safety_risk_score"]) == 42.00
    assert patient["risk_variant_applied"] == "INITIAL_ASSESSMENT"
    assert patient["compliance_hold"] is False


def test_malfunction_report_reassesses_the_same_home_under_ongoing_surveillance():
    """Filing a malfunction report against a placed unit rewrites the same
    factor vector under the harsher surveillance rule and freezes the account.

    PRD: "The patient's safety posture is then recomputed under the **ongoing-surveillance** variant, `risk_variant_applied` is set to `ONGOING_SURVEILLANCE`, and `compliance_hold` is re-evaluated — which is how a run of incidents eventually freezes the account."

    Design: Difficulty/dual_variant_calc/patient_risk_variant_divergence_initial_vs_surveillance
    """
    scenario = _homebound_patient_in_service()
    placement_id = placement_for_role(
        scenario["contract"]["id"], "PRIMARY_STATIONARY"
    )["id"]

    file_malfunction(placement_id, symptom="LEAK", oxygen_gap_minutes=5)

    patient = read_patient(scenario["patient"]["id"])
    assert_patient(patient)
    # The worst factor is the failed electrical inspection at 100, and four
    # non-zero factors push the escalation past the cap.
    assert float(patient["oxygen_safety_risk_score"]) == 100.00
    assert patient["risk_variant_applied"] == "ONGOING_SURVEILLANCE"
    assert patient["compliance_hold"] is True

    # A leak with a five-minute gap grades TIER_3, which pulls nothing.
    placement = placement_for_role(scenario["contract"]["id"], "PRIMARY_STATIONARY")
    assert_placement(placement)
    assert placement["status"] == "PLACED"
    assert placement["last_symptom"] == "LEAK"
    assert placement["last_severity_tier"] == "TIER_3"

    contract = read_contract(scenario["contract"]["id"])
    assert contract["malfunction_count"] == 1
    assert contract["cumulative_oxygen_gap_minutes"] == 5


def test_risk_read_shows_both_variants_diverging_over_one_factor_vector():
    """The computed risk read evaluates both variants over the same five
    factors, showing how far apart they land on identical data.

    PRD: "On identical factor values the two variants can diverge dramatically: a factor vector of smoking 0, electrical 100, teach-back 60, flow 60 and incident 30 yields 45.00 under the initial-assessment variant and 100.00 under ongoing surveillance."

    Design: Difficulty/dual_variant_calc/patient_risk_variant_divergence_initial_vs_surveillance
    """
    scenario = _homebound_patient_in_service()
    placement_id = placement_for_role(
        scenario["contract"]["id"], "PRIMARY_STATIONARY"
    )["id"]
    file_malfunction(placement_id, symptom="LEAK", oxygen_gap_minutes=5)

    assessment = validate_success(
        api_client.get_patient_risk_assessment(
            scenario["patient"]["id"], RESPIRATORY_THERAPIST
        )
    )
    assert_risk_assessment_read(assessment)

    assert float(assessment["factor_smoking"]) == 0
    assert float(assessment["factor_electrical"]) == 100
    assert float(assessment["factor_teachback"]) == 60
    assert float(assessment["factor_flow"]) == 60
    assert float(assessment["factor_incident"]) == 30

    assert float(assessment["initial_assessment_score"]) == 45.00
    assert float(assessment["ongoing_surveillance_score"]) == 100.00
    assert (
        float(assessment["ongoing_surveillance_score"])
        - float(assessment["initial_assessment_score"])
        == 55.00
    )

    # The read persists nothing: what is stored is what the malfunction wrote.
    assert float(assessment["persisted_score"]) == 100.00
    assert assessment["persisted_variant"] == "ONGOING_SURVEILLANCE"
    assert assessment["compliance_hold"] is True


# The two units a fee-schedule contract needs to hold a stationary concentrator
# in the primary role alongside a portable concentrator in the portable role.
TWO_UNIT_FLEET = FOUR_UNIT_FLEET[:2]


def _fee_schedule_contract_awaiting_setup() -> dict:
    """An ambulatory patient on a fee-schedule-adjusted contract with a
    stationary and a portable concentrator reserved, and a setup-delivery stop
    waiting on a dispatched route.
    """
    return setup_dispatched_setup_stop(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        unit_specs=TWO_UNIT_FLEET,
        patient_overrides={
            "mrn": "MRN-0020",
            "full_name": "Dina Halpert",
            "mobility_profile": "ACTIVE_AMBULATORY",
            "altitude_feet": 500,
        },
        cmn_overrides={"prescribed_lpm": 3.0, "portable_prescribed": True},
        contract_overrides={
            "pricing_basis": "FEE_SCHEDULE_ADJUSTED",
            "cap_month_limit": 36,
        },
    )


def test_fee_schedule_monthly_allowable_rounds_each_line_before_summing():
    """The stationary and portable lines are each rounded to whole cents before
    they are added, so the allowable lands one cent below the sum-then-round
    figure.

    PRD: "Summing the lines at full precision and rounding once at the end is a different and explicitly rejected order: a fee-schedule-adjusted contract holding a stationary concentrator in the primary role alongside a portable concentrator in the portable role produces per-line values of 6875 and 1627 for a total of 8502 cents, whereas sum-then-round would have produced 8503."

    Design: Difficulty/combinatorial_formula/monthly_allowable_per_line_rounding_order_fee_schedule
    """
    scenario = _fee_schedule_contract_awaiting_setup()

    validate_success(
        api_client.complete_setup(
            scenario["stop"]["id"], complete_setup_payload(), RESPIRATORY_THERAPIST
        )
    )

    contract = validate_success(
        api_client.get_rental_contract(scenario["contract"]["id"], BILLING_SPECIALIST)
    )
    assert_rental_contract(contract)
    # 6875 for the stationary line plus 1627 for the portable line.
    assert contract["monthly_allowable_cents"] == 8502
    assert contract["monthly_allowable_cents"] != 8503


def test_entering_service_places_both_roles_and_stamps_the_first_service_month():
    """Closing a passing setup moves the contract into service, places every
    reserved unit and recomputes the allowable over the newly placed equipment.

    PRD: "The contract moves `PENDING_SETUP → IN_SERVICE`, and a chain of consequences follows in the same request: the stop is stamped `COMPLETED` with `safety_result` `PASS`, `completed_at` set to the logical clock and `completed_by_user_id` set to the therapist's `X-User-ID`; the stop's safety findings count is computed; the contract's `first_service_month` is stamped with the `YYYY-MM` of the logical clock, permanently marking the month service began; every placement on the contract that is `RESERVED` moves `RESERVED → PLACED` with `placed_at` set to the logical clock; every fleet unit those placements reference moves `RESERVED → DEPLOYED`; the contract's monthly allowable is recomputed over the newly placed equipment; the patient's safety posture is recomputed under the initial-assessment variant, with `risk_variant_applied` set to `INITIAL_ASSESSMENT` and the compliance hold re-evaluated; the route is bubbled up to `COMPLETED` if every one of its stops is now terminal; and the `version` of the stop, the contract, each placement, each unit and the patient all increment by 1."

    Design: Difficulty/combinatorial_formula/monthly_allowable_per_line_rounding_order_fee_schedule
    """
    scenario = _fee_schedule_contract_awaiting_setup()

    validate_success(
        api_client.complete_setup(
            scenario["stop"]["id"], complete_setup_payload(), RESPIRATORY_THERAPIST
        )
    )

    contract = read_contract(scenario["contract"]["id"])
    assert_rental_contract(contract)
    assert contract["service_status"] == "IN_SERVICE"
    assert contract["first_service_month"] == "2026-08"
    assert contract["monthly_allowable_cents"] == 8502

    for role in ("PRIMARY_STATIONARY", "PORTABLE"):
        placement = placement_for_role(contract["id"], role)
        assert_placement(placement)
        assert placement["status"] == "PLACED", f"the {role} unit must be placed"


def test_first_service_month_posts_the_per_line_rounded_allowable_in_full():
    """A contract that entered service on the first of the month bills every day
    of that month, so the ledger records the per-line-rounded allowable exactly.

    PRD: "A contract that entered service on the 10th of a 31-day month therefore has 22 days of service in that month, and one that entered service on the 1st has the full 31."

    Design: Difficulty/combinatorial_formula/monthly_allowable_per_line_rounding_order_fee_schedule
    """
    scenario = _fee_schedule_contract_awaiting_setup()
    complete_in_home_setup(scenario["stop"]["id"])

    contract = validate_success(
        _post_month_response(scenario["contract"]["id"], "2026-08")
    )
    assert_rental_contract(contract)

    assert contract["posted_month_count"] == 1
    posted = contract["posted_months"][0]
    assert posted["service_month"] == "2026-08"
    assert posted["days_in_service"] == 31
    assert posted["amount_cents"] == 8502
    assert contract["lifetime_paid_cents"] == 8502


def _travelling_patient_contract() -> dict:
    """An ambulatory patient living at 500 feet on a 1.0 litre-per-minute
    prescription for 24 hours a day, with an open contract and no equipment yet
    in the home: travel supply is computed from the certificate alone.
    """
    return setup_open_contract(
        patient_overrides={
            "mrn": "MRN-0030",
            "full_name": "Elias Moreau",
            "mobility_profile": "ACTIVE_AMBULATORY",
            "altitude_feet": 500,
        },
        cmn_overrides={
            "prescribed_lpm": 1.0,
            "hours_per_day": 24,
            "portable_prescribed": False,
        },
        contract_overrides={
            "pricing_basis": "COMPETITIVE_BID_SINGLE_PAYMENT",
            "cap_month_limit": 36,
        },
    )


def _authorize_travel(contract: dict, depart: str, ret: str):
    return api_client.create_travel_authorization(
        contract["id"],
        create_travel_authorization_payload(
            contract["version"],
            depart_utc=depart,
            return_utc=ret,
            destination_altitude_feet=500,
        ),
        INTAKE_COORDINATOR,
    )


def test_forty_hour_trip_authorizes_five_cylinders_with_no_handling_surcharge():
    """A forty-hour trip to the patient's own elevation needs five E-cylinders,
    and a raw count of five attracts no handling surcharge.

    PRD: "A raw count of 5 therefore attracts no surcharge even though adding one would have crossed the threshold."

    Design: Difficulty/combinatorial_formula/travel_cylinder_pinned_evaluation_order_with_surcharge
    """
    scenario = _travelling_patient_contract()
    contract = read_contract(scenario["contract"]["id"])

    authorization = validate_success(
        _authorize_travel(
            contract, "2026-08-10T00:00:00Z", "2026-08-11T16:00:00Z"
        ),
        201,
    )
    assert_travel_authorization(authorization)

    assert authorization["trip_hours"] == 40
    # Travelling to the patient's own elevation gains nothing.
    assert float(authorization["altitude_factor"]) == 1.00
    assert float(authorization["effective_lpm"]) == 1.00
    assert authorization["base_liters"] == 2400
    assert authorization["reserve_liters"] == 840
    assert authorization["required_liters"] == 3240
    assert authorization["cylinders_raw"] == 5
    assert authorization["handling_surcharge_cylinders"] == 0
    assert authorization["supply_cylinders_authorized"] == 5
    assert authorization["status"] == "REQUESTED"


def test_forty_eight_hour_trip_adds_one_handling_cylinder_to_a_raw_six():
    """Eight more hours of travel push the raw cylinder count from five to six,
    which crosses the handling threshold and adds a further cylinder.

    PRD: "`handling_surcharge_cylinders` is 1 when `cylinders_raw` is 6 or more, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/travel_cylinder_pinned_evaluation_order_with_surcharge
    """
    scenario = _travelling_patient_contract()
    contract = read_contract(scenario["contract"]["id"])
    version_before = contract["version"]

    short_trip = validate_success(
        _authorize_travel(
            contract, "2026-08-10T00:00:00Z", "2026-08-11T16:00:00Z"
        ),
        201,
    )
    contract = read_contract(contract["id"])
    assert contract["version"] == version_before + 1

    long_trip = validate_success(
        _authorize_travel(
            contract, "2026-08-20T00:00:00Z", "2026-08-22T00:00:00Z"
        ),
        201,
    )
    assert_travel_authorization(long_trip)

    assert long_trip["trip_hours"] == 48
    assert long_trip["base_liters"] == 2880
    assert long_trip["reserve_liters"] == 1008
    assert long_trip["required_liters"] == 3888
    assert long_trip["cylinders_raw"] == 6
    assert long_trip["handling_surcharge_cylinders"] == 1
    assert long_trip["supply_cylinders_authorized"] == 7

    # One extra raw cylinder plus the surcharge it triggers: two cylinders more
    # than the shorter trip on the same prescription.
    assert (
        long_trip["supply_cylinders_authorized"]
        - short_trip["supply_cylinders_authorized"]
        == 2
    )
    assert long_trip["status"] == "REQUESTED"
    assert short_trip["status"] == "REQUESTED"

    contract = read_contract(contract["id"])
    assert contract["version"] == version_before + 2


def test_forty_hour_trip_reserves_thirty_five_percent_of_its_base_litres():
    """The reserve tier is keyed on the whole trip hours, so a forty-hour trip
    reserves thirty-five percent of its base litres rather than twenty.

    PRD: "The reserve percentage is 20 percent when the trip hours are 24 or fewer, 35 percent when they are more than 24 and no more than 72, and 50 percent otherwise."

    Design: Difficulty/combinatorial_formula/travel_cylinder_pinned_evaluation_order_with_surcharge
    """
    scenario = _travelling_patient_contract()
    contract = read_contract(scenario["contract"]["id"])

    authorization = validate_success(
        _authorize_travel(
            contract, "2026-08-10T00:00:00Z", "2026-08-11T16:00:00Z"
        ),
        201,
    )
    assert_travel_authorization(authorization)

    assert authorization["trip_hours"] == 40
    assert authorization["base_liters"] == 2400
    # Thirty-five percent of 2400 litres, floored.
    assert authorization["reserve_liters"] == 840
    # Twenty percent would have reserved only 480 litres.
    assert authorization["reserve_liters"] != 480
    assert (
        authorization["required_liters"]
        == authorization["base_liters"] + authorization["reserve_liters"]
    )
