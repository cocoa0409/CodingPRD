"""Cross-entity state dependencies, interval semantics and compensating pairs.

Three families of rule are exercised here, all against a live server through the
shared ApiClient:

* a row whose own transition is legal is refused because of the state of a
  *different* row it points at — a rental contract's resume blocked by an expired
  certificate, and a requested travel authorization blocked by a patient who has
  crossed the compliance-hold threshold;
* two contended resources with deliberately opposite interval semantics — the
  delivery route's buffered half-open stop windows against the rental contract's
  closed, unbuffered travel intervals;
* two compensating pairs and the quantity each conserves — the branch's in-stock
  equipment pool across assign/release, and the money ledger across
  post/reverse.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    INTAKE_COORDINATOR,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    advance_clock,
    api_client,
    assign_equipment,
    create_route_stop_payload,
    create_travel_authorization_payload,
    deny_travel_payload,
    file_malfunction,
    placements_for_contract,
    post_month,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_placement,
    read_route,
    read_travel_authorization,
    release_placement,
    request_travel,
    reverse_month,
    setup_contract_in_service,
    setup_in_service_with_planning_route,
    setup_open_contract,
    setup_requested_travel,
    setup_reserved_equipment,
    validate_error,
    validate_paginated,
    validate_success,
)

# One 5.0 lpm stationary concentrator is the whole fleet for the expiry chain.
_SINGLE_STATIONARY_FLEET = [
    {
        "serial_number": "SC-1001",
        "model_code": "CONC-5L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    }
]

# A 10.0 lpm stationary concentrator, wide enough for a 7.0 lpm prescription.
_HIGH_FLOW_STATIONARY_FLEET = [
    {
        "serial_number": "SC-1010",
        "model_code": "CONC-10L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 10.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    }
]


def _short_certificate_in_service():
    """An IN_SERVICE contract whose certificate declares a three-month length of
    need, so its recertification due date lands on 2026-11-01."""
    return setup_contract_in_service(
        unit_specs=_SINGLE_STATIONARY_FLEET,
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
        cmn_overrides={"length_of_need_months": 3},
    )


def test_resume_billing_refused_because_linked_certificate_has_expired():
    """A suspended contract may not resume billing while the certificate it hangs off is EXPIRED.

    PRD: "Resuming is requested, by a `BillingSpecialist`, and it carries four preconditions beyond the contract not being `CLOSED`: the billing dimension must be `SUSPENDED`; the linked certificate must be back to `ACTIVE`, or the resume is refused with `ERR_CMN_NOT_ACTIVE`; the patient must be `ACTIVE`; and no placement on the contract may still sit in `RECALLED_OUT_OF_SERVICE`, or the resume is refused with `ERR_CONTRACT_HAS_RECALLED_EQUIPMENT`."

    Design: Difficulty/cross_entity_state_dependency/billing_resume_blocked_when_linked_cmn_expired
    """
    scenario = _short_certificate_in_service()
    contract_id = scenario["contract"]["id"]

    cmn = read_cmn(scenario["cmn"]["id"])
    assert cmn["initial_date"] == "2026-08-01"
    assert cmn["recert_due_date"] == "2026-11-01"
    assert float(cmn["documentation_score"]) == 95.00

    sweep = advance_clock("2026-11-02T00:00:00Z")
    assert sweep["expired_cmn_count"] == 1
    assert sweep["suspended_contract_count"] == 1

    suspended = read_contract(contract_id)
    assert suspended["billing_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "CMN_EXPIRED"

    # Nothing about the contract itself blocks the resume: it is one month of
    # thirty-six into its cap, no placement is recalled and the patient is ACTIVE.
    cap = validate_success(api_client.get_cap_summary(contract_id, BILLING_SPECIALIST))
    assert cap["effective_position"] == 1
    assert cap["cap_month_limit"] == 36
    assert cap["months_remaining"] == 35
    assert read_patient(scenario["patient"]["id"])["status"] == "ACTIVE"

    refused = api_client.resume_billing(contract_id, BILLING_SPECIALIST)
    validate_error(refused, ApiErrorId.ERR_CMN_NOT_ACTIVE.value)

    unchanged = read_contract(contract_id)
    assert unchanged["billing_status"] == "SUSPENDED"
    assert unchanged["suspension_reason"] == "CMN_EXPIRED"
    assert unchanged["version"] == suspended["version"]


def test_clock_sweep_expires_the_certificate_and_suspends_its_contract():
    """The expiry sweep moves the certificate to EXPIRED, mirrors it onto the patient and suspends the contract with CMN_EXPIRED.

    PRD: "That move suspends every rental contract hanging off the certificate whose billing dimension is `ACCRUING` or `CAP_REACHED`, setting each contract's suspension reason to `CMN_EXPIRED` and incrementing each contract's `version`; it mirrors `EXPIRED` onto the patient when the certificate is the patient's newest; and it increments the certificate's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/billing_resume_blocked_when_linked_cmn_expired
    """
    scenario = _short_certificate_in_service()
    contract_before = read_contract(scenario["contract"]["id"])
    assert contract_before["billing_status"] == "ACCRUING"
    assert contract_before["suspension_reason"] == "NONE"

    sweep = advance_clock("2026-11-02T00:00:00Z")
    assert sweep["current_utc"].startswith("2026-11-02T00:00:00")
    assert sweep["previous_utc"].startswith("2026-08-01T00:00:00")
    assert sweep["expired_cmn_count"] == 1
    assert sweep["suspended_contract_count"] == 1

    cmn = read_cmn(scenario["cmn"]["id"])
    assert cmn["status"] == "EXPIRED"
    assert read_patient(scenario["patient"]["id"])["current_cmn_status"] == "EXPIRED"

    contract_after = read_contract(scenario["contract"]["id"])
    assert contract_after["billing_status"] == "SUSPENDED"
    assert contract_after["suspension_reason"] == "CMN_EXPIRED"
    assert contract_after["version"] > contract_before["version"]


def test_certificate_expiry_stops_the_money_without_pulling_the_oxygen():
    """Certificate expiry moves only the billing dimension: the service dimension, the placement, the deployed unit and the monthly allowable all stay put.

    PRD: "The **monthly allowable** is the contract's per-month price before any proration, and it is recomputed at five moments: when the contract enters service, when it returns after a pickup, on either resume-billing transition, when a reserved placement is released, and when a Class I recall pulls placements out of service."

    Design: Difficulty/cross_entity_state_dependency/billing_resume_blocked_when_linked_cmn_expired
    """
    scenario = _short_certificate_in_service()
    contract_id = scenario["contract"]["id"]
    placement_id = scenario["placement"]["id"]
    unit_id = scenario["stationary_unit"]["id"]

    before = read_contract(contract_id)
    assert before["monthly_allowable_cents"] == 5590
    assert before["service_status"] == "IN_SERVICE"
    assert read_placement(placement_id)["status"] == "PLACED"
    assert read_equipment_unit(unit_id)["status"] == "DEPLOYED"

    advance_clock("2026-11-02T00:00:00Z")

    after = read_contract(contract_id)
    assert after["billing_status"] == "SUSPENDED"
    assert after["service_status"] == "IN_SERVICE"
    assert after["monthly_allowable_cents"] == 5590
    assert read_placement(placement_id)["status"] == "PLACED"
    assert read_equipment_unit(unit_id)["status"] == "DEPLOYED"


def _requested_travel_for_high_flow_patient():
    """An IN_SERVICE contract for a 7.0 lpm prescription whose in-home teach-back
    scored 3, carrying one REQUESTED travel authorization for a 12-hour trip."""
    return setup_requested_travel(
        travel_overrides={
            "depart_utc": "2026-08-10T12:00:00Z",
            "return_utc": "2026-08-11T00:00:00Z",
            "destination_altitude_feet": 500,
        },
        unit_specs=_HIGH_FLOW_STATIONARY_FLEET,
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
        cmn_overrides={"prescribed_lpm": 7.0},
        setup_overrides={
            "patient_teachback_score": 3,
            "education_topics_covered": ["EQUIPMENT_OPERATION", "FIRE_SAFETY"],
        },
    )


def test_travel_approval_refused_once_a_malfunction_sets_the_compliance_hold():
    """A REQUESTED travel authorization becomes un-approvable purely because the patient's recomputed risk posture set the compliance hold.

    PRD: "Approval moves the authorization `REQUESTED → APPROVED` and stamps `decided_by_user_id` with the manager's `X-User-ID`, but only when the linked contract's billing dimension is not `SUSPENDED`, its service dimension is exactly `IN_SERVICE`, and the patient is not on compliance hold — an authorization for a patient whose risk posture has crossed the hold threshold is refused with `ERR_PATIENT_ON_COMPLIANCE_HOLD` even though the request itself was accepted earlier, because the posture may have moved in between."

    Design: Difficulty/cross_entity_state_dependency/travel_approval_blocked_when_patient_on_compliance_hold
    """
    scenario = _requested_travel_for_high_flow_patient()
    authorization_id = scenario["travel_authorization"]["id"]

    patient_before = read_patient(scenario["patient"]["id"])
    assert float(patient_before["oxygen_safety_risk_score"]) == 24.00
    assert patient_before["risk_variant_applied"] == "INITIAL_ASSESSMENT"
    assert patient_before["compliance_hold"] is False

    authorization = read_travel_authorization(authorization_id)
    assert authorization["status"] == "REQUESTED"
    assert authorization["supply_cylinders_authorized"] == 10

    file_malfunction(scenario["placement"]["id"], symptom="LEAK", oxygen_gap_minutes=5)

    patient_after = read_patient(scenario["patient"]["id"])
    assert float(patient_after["oxygen_safety_risk_score"]) == 70.00
    assert patient_after["risk_variant_applied"] == "ONGOING_SURVEILLANCE"
    assert patient_after["compliance_hold"] is True

    refused = api_client.approve_travel_authorization(authorization_id, BRANCH_MANAGER)
    validate_error(refused, ApiErrorId.ERR_PATIENT_ON_COMPLIANCE_HOLD.value)

    unchanged = read_travel_authorization(authorization_id)
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["decided_by_user_id"] is None
    assert unchanged["supply_cylinders_authorized"] == 10
    assert unchanged["depart_utc"].startswith("2026-08-10T12:00:00")
    assert unchanged["return_utc"].startswith("2026-08-11T00:00:00")


def test_tier_three_malfunction_raises_the_hold_without_pulling_the_equipment():
    """A TIER_3 report leaves the placement and the unit in service while the ongoing-surveillance rescore reaches the hold threshold of exactly 70.00.

    PRD: "`TIER_2` and `TIER_3` reports leave both the placement and the unit exactly where they are, in service; only the counters and the risk score move."

    Design: Difficulty/cross_entity_state_dependency/travel_approval_blocked_when_patient_on_compliance_hold
    """
    scenario = _requested_travel_for_high_flow_patient()
    placement_id = scenario["placement"]["id"]
    unit_id = scenario["stationary_unit"]["id"]

    report = file_malfunction(placement_id, symptom="LEAK", oxygen_gap_minutes=5)
    assert report["last_severity_tier"] == "TIER_3"
    assert report["last_symptom"] == "LEAK"

    placement = read_placement(placement_id)
    assert placement["status"] == "PLACED"
    assert placement["removal_reason"] == "NONE"
    assert placement["malfunction_count"] == 1
    assert read_equipment_unit(unit_id)["status"] == "DEPLOYED"

    contract = read_contract(scenario["contract"]["id"])
    assert contract["malfunction_count"] == 1
    assert contract["cumulative_oxygen_gap_minutes"] == 5

    patient = read_patient(scenario["patient"]["id"])
    assert float(patient["oxygen_safety_risk_score"]) == 70.00
    assert patient["compliance_hold"] is True


def test_denial_stays_available_while_the_patient_is_on_compliance_hold():
    """Only three operations are blocked by the hold, so a pending travel authorization can still be denied rather than being deadlocked.

    PRD: "While the hold is set, three operations are blocked with `ERR_PATIENT_ON_COMPLIANCE_HOLD`: no new equipment may be assigned for the patient's contract, no new travel supply may be requested, and no pending travel authorization may be approved."

    Design: Difficulty/cross_entity_state_dependency/travel_approval_blocked_when_patient_on_compliance_hold
    """
    scenario = _requested_travel_for_high_flow_patient()
    authorization_id = scenario["travel_authorization"]["id"]

    file_malfunction(scenario["placement"]["id"], symptom="LEAK", oxygen_gap_minutes=5)
    assert read_patient(scenario["patient"]["id"])["compliance_hold"] is True

    refused = api_client.approve_travel_authorization(authorization_id, BRANCH_MANAGER)
    validate_error(refused, ApiErrorId.ERR_PATIENT_ON_COMPLIANCE_HOLD.value)

    denied = validate_success(
        api_client.deny_travel_authorization(
            authorization_id, deny_travel_payload(), BRANCH_MANAGER
        )
    )
    assert denied["status"] == "DENIED"
    assert read_travel_authorization(authorization_id)["status"] == "DENIED"


def _in_service_with_empty_route_on_the_fifteenth():
    """An IN_SERVICE contract on a branch whose trailing turnaround buffer is 30
    minutes, plus a second empty route in PLANNING for 2026-08-15."""
    return setup_in_service_with_planning_route(
        service_date="2026-08-15",
        shift_start_utc="2026-08-15T12:00:00Z",
        shift_end_utc="2026-08-15T22:00:00Z",
        unit_specs=_SINGLE_STATIONARY_FLEET,
        patient_overrides={"mobility_profile": "HOMEBOUND", "altitude_feet": 500},
    )


def test_tank_exchange_rejected_inside_the_trailing_buffer_of_an_earlier_stop():
    """A stop starting after a predecessor's own window end but inside its trailing turnaround buffer conflicts.

    PRD: "The buffered span is treated as **half-open** — it includes its start instant and excludes its buffered end instant — and it must not intersect the buffered half-open span of any other stop on the same route that is still in `PLANNED`."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_window_with_trailing_buffer
    """
    scenario = _in_service_with_empty_route_on_the_fifteenth()
    contract_id = scenario["contract"]["id"]
    route_id = scenario["planning_route"]["id"]
    assert scenario["branch"]["tank_exchange_buffer_minutes"] == 30

    first = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                route_id,
                contract_id,
                stop_type="TANK_EXCHANGE",
                window_start_utc="2026-08-15T13:00:00Z",
                window_end_utc="2026-08-15T14:00:00Z",
                service_minutes=45,
                cylinders_requested=2,
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert first["status"] == "PLANNED"
    assert first["liters_committed"] == 1360

    # 14:15Z is past the predecessor's own window_end_utc of 14:00Z, but still
    # inside its buffered span, which runs to 14:30Z.
    refused = api_client.create_route_stop(
        create_route_stop_payload(
            route_id,
            contract_id,
            stop_type="TANK_EXCHANGE",
            window_start_utc="2026-08-15T14:15:00Z",
            window_end_utc="2026-08-15T15:00:00Z",
            service_minutes=45,
            cylinders_requested=2,
        ),
        BRANCH_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_ROUTE_STOP_WINDOW_CONFLICT.value)

    route = read_route(route_id)
    assert route["planned_stop_count"] == 1
    assert route["total_o2_liters_committed"] == 1360

    rows, meta = validate_paginated(
        api_client.list_route_stops(BRANCH_MANAGER, params={"route_id": route_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


def test_tank_exchange_accepted_exactly_at_the_buffered_end_instant():
    """Adjacency is legal on a route: a stop starting exactly on the predecessor's buffered end instant is accepted and the litres roll up.

    PRD: "Because the spans are half-open, adjacency does not conflict: a new stop whose `window_start_utc` falls exactly on an existing stop's buffered end instant is accepted."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_window_with_trailing_buffer
    """
    scenario = _in_service_with_empty_route_on_the_fifteenth()
    contract_id = scenario["contract"]["id"]
    route_id = scenario["planning_route"]["id"]

    validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                route_id,
                contract_id,
                stop_type="TANK_EXCHANGE",
                window_start_utc="2026-08-15T13:00:00Z",
                window_end_utc="2026-08-15T14:00:00Z",
                service_minutes=45,
                cylinders_requested=2,
            ),
            BRANCH_MANAGER,
        ),
        201,
    )

    # One second earlier still lies inside the half-open buffered span.
    just_inside = api_client.create_route_stop(
        create_route_stop_payload(
            route_id,
            contract_id,
            stop_type="TANK_EXCHANGE",
            window_start_utc="2026-08-15T14:29:59Z",
            window_end_utc="2026-08-15T15:30:00Z",
            service_minutes=45,
            cylinders_requested=2,
        ),
        BRANCH_MANAGER,
    )
    validate_error(just_inside, ApiErrorId.ERR_ROUTE_STOP_WINDOW_CONFLICT.value)

    adjacent = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                route_id,
                contract_id,
                stop_type="TANK_EXCHANGE",
                window_start_utc="2026-08-15T14:30:00Z",
                window_end_utc="2026-08-15T15:30:00Z",
                service_minutes=45,
                cylinders_requested=2,
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert adjacent["status"] == "PLANNED"
    assert adjacent["sequence_index"] == 2
    assert adjacent["liters_committed"] == 1360

    route = read_route(route_id)
    assert route["planned_stop_count"] == 2
    assert route["total_o2_liters_committed"] == 2720
    assert route["refill_slots_used"] == 0


def _contract_for_a_travelling_patient():
    """An open contract for a 1.0 lpm lifetime prescription, no equipment and no
    route — a travel authorization needs neither."""
    return setup_open_contract(
        unit_specs=[],
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY", "altitude_feet": 500},
        cmn_overrides={"prescribed_lpm": 1.0},
    )


def test_second_trip_departing_when_the_first_returns_is_a_conflict():
    """Travel intervals are closed and unbuffered, so a trip departing on the exact instant an existing trip returns collides.

    PRD: "Because the intervals are closed, **touching endpoints do conflict** — a new authorization departing at exactly the instant an existing one returns is rejected with `ERR_TRAVEL_INTERVAL_CONFLICT` — and no buffer is applied."

    Design: Difficulty/resource_temporal_overlap/travel_authorization_closed_interval_touching_endpoints_conflict
    """
    scenario = _contract_for_a_travelling_patient()
    contract_id = scenario["contract"]["id"]

    first = request_travel(
        scenario["contract"],
        depart_utc="2026-08-10T00:00:00Z",
        return_utc="2026-08-12T00:00:00Z",
        destination_altitude_feet=500,
    )
    assert first["status"] == "REQUESTED"
    assert first["trip_hours"] == 48
    assert first["supply_cylinders_authorized"] == 7

    version_after_first = read_contract(contract_id)["version"]

    refused = api_client.create_travel_authorization(
        contract_id,
        create_travel_authorization_payload(
            version_after_first,
            depart_utc="2026-08-12T00:00:00Z",
            return_utc="2026-08-13T00:00:00Z",
            destination_altitude_feet=500,
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(refused, ApiErrorId.ERR_TRAVEL_INTERVAL_CONFLICT.value)

    rows, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract_id}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]
    assert read_contract(contract_id)["version"] == version_after_first


def test_one_second_of_separation_makes_the_next_trip_authorizable():
    """Moving the departure one second past the previous return clears the closed-interval conflict, and the rejected attempt left the contract version untouched.

    PRD: "And the trip must not collide with another trip: the new authorization's **closed** interval from `depart_utc` through `return_utc` must not intersect the closed interval of any existing authorization on the same contract whose status is `REQUESTED` or `APPROVED`."

    Design: Difficulty/resource_temporal_overlap/travel_authorization_closed_interval_touching_endpoints_conflict
    """
    scenario = _contract_for_a_travelling_patient()
    contract_id = scenario["contract"]["id"]

    request_travel(
        scenario["contract"],
        depart_utc="2026-08-10T00:00:00Z",
        return_utc="2026-08-12T00:00:00Z",
        destination_altitude_feet=500,
    )
    version_after_first = read_contract(contract_id)["version"]

    touching = api_client.create_travel_authorization(
        contract_id,
        create_travel_authorization_payload(
            version_after_first,
            depart_utc="2026-08-12T00:00:00Z",
            return_utc="2026-08-13T00:00:00Z",
            destination_altitude_feet=500,
        ),
        INTAKE_COORDINATOR,
    )
    validate_error(touching, ApiErrorId.ERR_TRAVEL_INTERVAL_CONFLICT.value)

    # The very same version token still works, which is only possible because the
    # refused write never touched the contract.
    second = validate_success(
        api_client.create_travel_authorization(
            contract_id,
            create_travel_authorization_payload(
                version_after_first,
                depart_utc="2026-08-12T00:00:01Z",
                return_utc="2026-08-13T00:00:00Z",
                destination_altitude_feet=500,
            ),
            INTAKE_COORDINATOR,
        ),
        201,
    )
    assert second["status"] == "REQUESTED"
    assert second["trip_hours"] == 23
    assert float(second["altitude_factor"]) == 1.00
    assert float(second["effective_lpm"]) == 1.00
    assert second["base_liters"] == 1380
    assert second["reserve_liters"] == 276
    assert second["required_liters"] == 1656
    assert second["cylinders_raw"] == 3
    assert second["handling_surcharge_cylinders"] == 0
    assert second["supply_cylinders_authorized"] == 3

    rows, meta = validate_paginated(
        api_client.list_travel_authorizations(
            INTAKE_COORDINATOR, params={"contract_id": contract_id}
        )
    )
    assert meta["total_count"] == 2
    assert read_contract(contract_id)["version"] == version_after_first + 1


def _two_reserved_units_before_setup():
    """An open contract holding a RESERVED stationary placement and a RESERVED
    portable placement, drawn from a branch whose whole fleet is those two units."""
    return setup_reserved_equipment(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY", "altitude_feet": 500},
        cmn_overrides={"prescribed_lpm": 3.0, "portable_prescribed": True},
    )


def _in_stock_unit_ids(branch_id):
    rows, meta = validate_paginated(
        api_client.list_equipment_units(
            BRANCH_MANAGER, params={"branch_id": branch_id, "status": "IN_STOCK"}
        )
    )
    return {row["id"] for row in rows}, meta["total_count"]


def test_releasing_both_reservations_restores_the_branch_in_stock_pool():
    """Assign and release compensate exactly: the branch ends holding the same in-stock units it began with.

    PRD: "The invariant that makes this a true compensating pair is that the branch's in-stock count for the unit's model code returns to exactly its pre-assignment value."

    Design: Difficulty/compensating_invariant/assign_then_release_restores_branch_in_stock_pool
    """
    scenario = _two_reserved_units_before_setup()
    branch_id = scenario["branch"]["id"]
    stationary_id = scenario["stationary_unit"]["id"]
    portable_id = scenario["portable_unit"]["id"]

    assert read_equipment_unit(stationary_id)["status"] == "RESERVED"
    assert read_equipment_unit(portable_id)["status"] == "RESERVED"
    ids_while_reserved, count_while_reserved = _in_stock_unit_ids(branch_id)
    assert count_while_reserved == 0
    assert ids_while_reserved == set()

    stationary_placement, portable_placement = scenario["placements"]
    release_placement(portable_placement["id"])
    release_placement(stationary_placement["id"])

    assert read_equipment_unit(stationary_id)["status"] == "IN_STOCK"
    assert read_equipment_unit(portable_id)["status"] == "IN_STOCK"
    ids_after_release, count_after_release = _in_stock_unit_ids(branch_id)
    assert count_after_release == 2
    assert ids_after_release == {stationary_id, portable_id}


def test_released_placements_are_kept_as_removed_history_and_cost_nothing():
    """A released reservation is retained as a REMOVED row stamped RELEASED, and the contract's price stays at zero because nothing was ever placed.

    PRD: "It moves the placement `RESERVED → REMOVED` with `removal_reason` set to `RELEASED` and `removed_at` set to the logical clock, returns the unit `RESERVED → IN_STOCK` in its owning branch's pool, recomputes the contract's monthly allowable, and increments the `version` of the placement, the unit and the contract by 1 each."

    Design: Difficulty/compensating_invariant/assign_then_release_restores_branch_in_stock_pool
    """
    scenario = _two_reserved_units_before_setup()
    contract_id = scenario["contract"]["id"]
    stationary_placement, portable_placement = scenario["placements"]

    before = read_contract(contract_id)
    assert before["monthly_allowable_cents"] == 0
    assert before["first_service_month"] is None

    for placement in (portable_placement, stationary_placement):
        released = release_placement(placement["id"])
        assert released["status"] == "REMOVED"
        assert released["removal_reason"] == "RELEASED"
        assert released["removed_at"].startswith("2026-08-01T00:00:00")
        assert released["version"] > placement["version"]

    rows, meta = validate_paginated(
        api_client.list_placements(
            RESPIRATORY_THERAPIST, params={"contract_id": contract_id}
        )
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {"REMOVED"}

    after = read_contract(contract_id)
    assert after["monthly_allowable_cents"] == 0
    assert after["first_service_month"] is None


def test_reassignment_over_the_restored_pool_selects_the_same_stationary_unit():
    """Selection over the restored pool is deterministic: the primary-stationary role picks the same concentrator again and cannot touch the portable unit.

    PRD: "The permitted classes per role are fixed: `PRIMARY_STATIONARY` admits `STATIONARY_CONCENTRATOR` and `LIQUID_RESERVOIR`; `PORTABLE` admits `PORTABLE_CONCENTRATOR`, `LIQUID_PORTABLE` and `COMPRESSED_CYLINDER`; and `BACKUP` admits `COMPRESSED_CYLINDER` and `STATIONARY_CONCENTRATOR`."

    Design: Difficulty/compensating_invariant/assign_then_release_restores_branch_in_stock_pool
    """
    scenario = _two_reserved_units_before_setup()
    contract_id = scenario["contract"]["id"]
    stationary_id = scenario["stationary_unit"]["id"]
    portable_id = scenario["portable_unit"]["id"]
    stationary_placement, portable_placement = scenario["placements"]

    release_placement(portable_placement["id"])
    release_placement(stationary_placement["id"])

    reassigned = assign_equipment(contract_id, role="PRIMARY_STATIONARY")
    assert reassigned["id"] != stationary_placement["id"]
    assert reassigned["equipment_unit_id"] == stationary_id
    assert reassigned["status"] == "RESERVED"
    assert read_equipment_unit(stationary_id)["status"] == "RESERVED"
    assert read_equipment_unit(portable_id)["status"] == "IN_STOCK"

    rows, meta = validate_paginated(
        api_client.list_placements(
            RESPIRATORY_THERAPIST, params={"contract_id": contract_id}
        )
    )
    assert meta["total_count"] == 3
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["REMOVED", "REMOVED", "RESERVED"]


def _in_service_with_stationary_and_portable():
    """An IN_SERVICE contract carrying both a placed stationary concentrator and a
    placed portable concentrator, priced at 6913 cents a month."""
    return setup_contract_in_service(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY", "altitude_feet": 500},
        cmn_overrides={"prescribed_lpm": 3.0, "portable_prescribed": True},
        stop_overrides={"cylinders_requested": 2},
    )


def test_posting_the_first_service_month_records_the_full_prorated_amount():
    """Posting the month service began appends one ledger element and moves lifetime_paid_cents by exactly that amount.

    PRD: "A successful post appends one element to `posted_months`, and that element records four things: the `service_month` it covers, the `amount_cents` computed above, the `days_in_service` used in the proration, and the `posted_at` instant taken from the logical clock."

    Design: Difficulty/compensating_invariant/post_then_reverse_billing_month_restores_lifetime_paid_cents
    """
    scenario = _in_service_with_stationary_and_portable()
    contract_id = scenario["contract"]["id"]

    before = read_contract(contract_id)
    assert before["monthly_allowable_cents"] == 6913
    assert before["first_service_month"] == "2026-08"
    assert before["lifetime_paid_cents"] == 0
    assert before["posted_month_count"] == 0
    assert before["posted_months"] == []
    assert before["last_posted_service_month"] is None

    posted = post_month(contract_id, "2026-08")
    assert posted["billing_status"] == "ACCRUING"
    assert posted["lifetime_paid_cents"] == 6913
    assert posted["posted_month_count"] == 1
    assert posted["last_posted_service_month"] == "2026-08"
    assert len(posted["posted_months"]) == 1
    element = posted["posted_months"][0]
    assert element["service_month"] == "2026-08"
    # Service began on the 1st of a 31-day month: 31 - 1 + 1 days of service.
    assert element["days_in_service"] == 31
    assert element["amount_cents"] == 6913
    assert element["posted_at"].startswith("2026-08-01T00:00:00")


def test_reversing_the_only_posted_month_returns_the_ledger_to_zero():
    """Reversal is the compensating counterpart of posting: the ledger returns to empty with no residual cent.

    PRD: "Every reversal removes the element whose `service_month` equals the named month, decrements `posted_month_count` by 1, decreases `lifetime_paid_cents` by **exactly the removed element's `amount_cents`**, recomputes `last_posted_service_month` over the remaining elements (leaving it null when none remain), and increments the contract's `version` by 1."

    Design: Difficulty/compensating_invariant/post_then_reverse_billing_month_restores_lifetime_paid_cents
    """
    scenario = _in_service_with_stationary_and_portable()
    contract_id = scenario["contract"]["id"]

    posted = post_month(contract_id, "2026-08")
    assert posted["lifetime_paid_cents"] == 6913

    reversed_contract = reverse_month(contract_id, "2026-08")
    assert reversed_contract["lifetime_paid_cents"] == 0
    assert reversed_contract["posted_month_count"] == 0
    assert reversed_contract["posted_months"] == []
    assert reversed_contract["last_posted_service_month"] is None
    assert reversed_contract["billing_status"] == "ACCRUING"
    assert reversed_contract["version"] > posted["version"]
    # Reversing a month never re-prices the equipment in the home.
    assert reversed_contract["monthly_allowable_cents"] == 6913


def test_post_reverse_and_repost_leaves_the_money_and_the_equipment_untouched():
    """A post, reverse and re-post cycle lands lifetime_paid_cents back on exactly the same integer, and the compensation touches no equipment state.

    PRD: "Because the decrease uses the stored amount rather than a recomputation, posting a month and then reversing it returns `lifetime_paid_cents` to its exact prior integer value even if the monthly allowable has changed in between — the quantity is conserved."

    Design: Difficulty/compensating_invariant/post_then_reverse_billing_month_restores_lifetime_paid_cents
    """
    scenario = _in_service_with_stationary_and_portable()
    contract_id = scenario["contract"]["id"]
    unit_ids = [unit["id"] for unit in scenario["units"]]
    placement_ids = [placement["id"] for placement in placements_for_contract(contract_id)]

    post_month(contract_id, "2026-08")
    reverse_month(contract_id, "2026-08")
    reposted = post_month(contract_id, "2026-08")

    assert reposted["lifetime_paid_cents"] == 6913
    assert reposted["posted_month_count"] == 1
    assert reposted["last_posted_service_month"] == "2026-08"
    assert reposted["posted_months"][0]["amount_cents"] == 6913
    assert reposted["monthly_allowable_cents"] == 6913

    for placement_id in placement_ids:
        assert read_placement(placement_id)["status"] == "PLACED"
    for unit_id in unit_ids:
        assert read_equipment_unit(unit_id)["status"] == "DEPLOYED"
