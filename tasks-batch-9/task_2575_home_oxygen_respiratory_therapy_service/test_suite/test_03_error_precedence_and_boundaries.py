"""Global error-precedence ladder conflicts and inclusive-boundary arithmetic.

Two rule families are exercised here.  First, requests that violate two rules at
once: the PRD states one global evaluation order, so exactly one error may be
reported and it must be the one belonging to the earlier ladder position.
Clearing only the earlier violation and replaying a byte-identical request is
what makes the ordering observable.  Second, the inclusive boundaries the PRD
pins to a single integer point or a single hundredth: the saturation that
separates the three qualifying groups, and the documentation score that
separates a submittable certificate from a rejected one.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    INTAKE_COORDINATOR,
    RESPIRATORY_THERAPIST,
    USER_IDS,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_qualifying_test,
    assign_equipment,
    create_equipment_assignment_payload,
    create_qualifying_test_payload,
    make_branch,
    open_transfer,
    placements_for_contract,
    post_billing_month_payload,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    setup_admitted_patient,
    setup_cap_reached_contract,
    setup_drafted_cmn,
    setup_open_contract_with_pool,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─────────────────────────────────────────────────────────────────────────────
# Suspended billing outranks the exhausted capped-rental cap on a month post
# ─────────────────────────────────────────────────────────────────────────────


def test_suspended_billing_is_reported_before_the_exhausted_cap():
    """A month post that is both billing-suspended and past its cap reports the suspension.

    PRD: "When more than one rule could reject the same request, exactly one error is reported: the one belonging to the earliest position in the ladder below."

    Design: Difficulty/priority_pair_validation_conflict/suspended_billing_beats_cap_exhausted
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract = scenario["contract"]
    assert contract["billing_status"] == "CAP_REACHED", (
        "one posted month at cap_month_limit 1 leaves the billing dimension CAP_REACHED"
    )

    # Move the calendar into September and open a transfer, which suspends billing.
    advance_clock("2026-09-05T00:00:00Z")
    receiving_branch = make_branch(name="Sarasota", state_code="FL")
    open_transfer(scenario["patient"]["id"], receiving_branch["id"], "2026-09-30")

    contract = read_contract(contract["id"])
    assert contract["billing_status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "TRANSFER"

    # 2026-09 is one calendar month past first_service_month 2026-08, so the
    # service-month cap position is 2 against a cap limit of 1: both the
    # billing-state rule and the fiscal cap rule are violated by this one call.
    response = api_client.post_billing_month(
        contract["id"], post_billing_month_payload("2026-09"), BILLING_SPECIALIST
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_BILLING_SUSPENDED.value)


def test_no_month_is_written_when_the_suspended_post_is_refused():
    """A refused month post leaves the posted ledger and the lifetime paid total untouched.

    PRD: "It must be exactly `ACCRUING`: a contract sitting in `SUSPENDED` or `CAP_REACHED` cannot accept another month, and the attempt is refused with `ERR_CONTRACT_BILLING_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_billing_beats_cap_exhausted
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract = scenario["contract"]
    assert contract["monthly_allowable_cents"] == 5590, (
        "7752 * 1.00 * 0.7358 * 0.98 rounds half up to 5590 cents"
    )
    assert contract["lifetime_paid_cents"] == 5590, (
        "the first service month began on the 1st, so all 31 of 31 days bill"
    )

    advance_clock("2026-09-05T00:00:00Z")
    receiving_branch = make_branch(name="Sarasota", state_code="FL")
    open_transfer(scenario["patient"]["id"], receiving_branch["id"], "2026-09-30")

    response = api_client.post_billing_month(
        contract["id"], post_billing_month_payload("2026-09"), BILLING_SPECIALIST
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_BILLING_SUSPENDED.value)

    after = read_contract(contract["id"])
    assert after["posted_month_count"] == 1
    assert [element["service_month"] for element in after["posted_months"]] == ["2026-08"]
    assert after["lifetime_paid_cents"] == 5590
    assert after["last_posted_service_month"] == "2026-08"
    assert after["billing_status"] == "SUSPENDED"


def test_exhausted_cap_surfaces_once_the_transfer_suspension_is_withdrawn():
    """Withdrawing the transfer clears only the billing-state violation, exposing the cap rule.

    PRD: "When the effective position is **strictly above** `cap_month_limit`, nothing is posted at all and the request is refused with `ERR_CAP_MONTHS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_billing_beats_cap_exhausted
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract = scenario["contract"]
    patient_id = scenario["patient"]["id"]
    origin_branch_id = scenario["branch"]["id"]

    advance_clock("2026-09-05T00:00:00Z")
    receiving_branch = make_branch(name="Sarasota", state_code="FL")
    open_transfer(patient_id, receiving_branch["id"], "2026-09-30")

    first_attempt = api_client.post_billing_month(
        contract["id"], post_billing_month_payload("2026-09"), BILLING_SPECIALIST
    )
    validate_error(first_attempt, ApiErrorId.ERR_CONTRACT_BILLING_SUSPENDED.value)

    validate_success(api_client.cancel_transfer_request(patient_id, INTAKE_COORDINATOR))

    patient = read_patient(patient_id)
    assert patient["status"] == "ACTIVE"
    assert patient["branch_id"] == origin_branch_id
    assert patient["transfer_to_branch_id"] is None
    resumed = read_contract(contract["id"])
    assert resumed["billing_status"] == "ACCRUING"
    assert resumed["suspension_reason"] == "NONE"

    # The retry carries a byte-identical body; only the earlier violation is gone.
    retry = api_client.post_billing_month(
        contract["id"], post_billing_month_payload("2026-09"), BILLING_SPECIALIST
    )
    validate_error(retry, ApiErrorId.ERR_CAP_MONTHS_EXHAUSTED.value)

    after = read_contract(contract["id"])
    assert after["posted_month_count"] == 1
    assert after["lifetime_paid_cents"] == 5590
    assert after["last_posted_service_month"] == "2026-08"


# ─────────────────────────────────────────────────────────────────────────────
# Portable-not-indicated outranks an occupied placement role on assignment
# ─────────────────────────────────────────────────────────────────────────────


def _portable_pool_specs():
    """A fleet holding one stationary unit and two interchangeable portables, so
    the eligibility filter for the PORTABLE role always has a spare candidate."""
    return [
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
            "serial_number": "PC-2002",
            "model_code": "POC-3L",
            "equipment_class": "PORTABLE_CONCENTRATOR",
            "max_continuous_lpm": 3.0,
            "max_pulse_setting": 5,
            "pm_interval_days": 365,
            "next_pm_due_date": "2027-05-01",
        },
    ]


def test_portable_not_indicated_is_reported_before_the_occupied_portable_role():
    """A portable request for a homebound patient whose portable role is filled reports the clinical rule.

    PRD: "A portable request for a `HOMEBOUND` patient, or for a certificate that does not prescribe portable, is rejected with `ERR_PORTABLE_NOT_INDICATED`."

    Design: Difficulty/priority_pair_validation_conflict/portable_not_indicated_beats_role_occupied
    """
    scenario = setup_open_contract_with_pool(
        _portable_pool_specs(),
        prescribed_lpm=3.0,
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
    )
    contract_id = scenario["contract"]["id"]
    patient_id = scenario["patient"]["id"]

    reserved = assign_equipment(contract_id, "PORTABLE")
    assert reserved["role"] == "PORTABLE"
    assert reserved["status"] == "RESERVED"

    # Reassessment finds the patient homebound, so portable is no longer indicated
    # while the PORTABLE role remains occupied by the reserved placement.
    validate_success(
        api_client.update_patient(
            patient_id, {"mobility_profile": "HOMEBOUND"}, INTAKE_COORDINATOR
        )
    )

    response = api_client.create_equipment_assignment(
        contract_id, create_equipment_assignment_payload("PORTABLE"), RESPIRATORY_THERAPIST
    )
    validate_error(response, ApiErrorId.ERR_PORTABLE_NOT_INDICATED.value)


def test_rejected_portable_request_reserves_no_further_unit():
    """A rejected portable assignment writes no placement and leaves the spare portable in stock.

    PRD: "Before the selection runs, four guards apply: the contract's billing dimension must not be `CLOSED` (`ERR_CONTRACT_CLOSED`); its certificate must be `ACTIVE` (`ERR_CMN_NOT_ACTIVE`); the patient must be `ACTIVE` (`ERR_PATIENT_NOT_ACTIVE`) and must not be on compliance hold (`ERR_PATIENT_ON_COMPLIANCE_HOLD`); and the requested role must not already be filled — a contract that already holds a placement in `RESERVED` or `PLACED` for that same role is rejected with `ERR_ROLE_ALREADY_OCCUPIED`."

    Design: Difficulty/priority_pair_validation_conflict/portable_not_indicated_beats_role_occupied
    """
    scenario = setup_open_contract_with_pool(
        _portable_pool_specs(),
        prescribed_lpm=3.0,
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
    )
    contract_id = scenario["contract"]["id"]
    spare_portable = scenario["units_by_serial"]["PC-2002"]

    assign_equipment(contract_id, "PORTABLE")
    validate_success(
        api_client.update_patient(
            scenario["patient"]["id"],
            {"mobility_profile": "HOMEBOUND"},
            INTAKE_COORDINATOR,
        )
    )

    response = api_client.create_equipment_assignment(
        contract_id, create_equipment_assignment_payload("PORTABLE"), RESPIRATORY_THERAPIST
    )
    validate_error(response, ApiErrorId.ERR_PORTABLE_NOT_INDICATED.value)

    placements = placements_for_contract(contract_id)
    assert len(placements) == 1, "no second placement row may be created"
    assert read_equipment_unit(spare_portable["id"])["status"] == "IN_STOCK"


def test_occupied_portable_role_surfaces_once_mobility_is_restored():
    """Restoring the ambulatory mobility profile clears only the clinical rule, exposing the role guard.

    PRD: "When more than one rule could reject the same request, exactly one error is reported: the one belonging to the earliest position in the ladder below."

    Design: Difficulty/priority_pair_validation_conflict/portable_not_indicated_beats_role_occupied
    """
    scenario = setup_open_contract_with_pool(
        _portable_pool_specs(),
        prescribed_lpm=3.0,
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
    )
    contract_id = scenario["contract"]["id"]
    patient_id = scenario["patient"]["id"]
    chosen_portable = scenario["units_by_serial"]["PC-2001"]
    spare_portable = scenario["units_by_serial"]["PC-2002"]

    reserved = assign_equipment(contract_id, "PORTABLE")
    # Both portables leave zero headroom against a 3.0 lpm prescription, so the
    # tie-break takes the later next_pm_due_date: PC-2001 at 2027-06-01.
    assert reserved["equipment_unit_id"] == chosen_portable["id"]

    validate_success(
        api_client.update_patient(
            patient_id, {"mobility_profile": "HOMEBOUND"}, INTAKE_COORDINATOR
        )
    )
    first_attempt = api_client.create_equipment_assignment(
        contract_id, create_equipment_assignment_payload("PORTABLE"), RESPIRATORY_THERAPIST
    )
    validate_error(first_attempt, ApiErrorId.ERR_PORTABLE_NOT_INDICATED.value)

    validate_success(
        api_client.update_patient(
            patient_id, {"mobility_profile": "ACTIVE_AMBULATORY"}, INTAKE_COORDINATOR
        )
    )
    retry = api_client.create_equipment_assignment(
        contract_id, create_equipment_assignment_payload("PORTABLE"), RESPIRATORY_THERAPIST
    )
    validate_error(retry, ApiErrorId.ERR_ROLE_ALREADY_OCCUPIED.value)

    placements = placements_for_contract(contract_id)
    assert len(placements) == 1
    assert placements[0]["id"] == reserved["id"]
    assert placements[0]["role"] == "PORTABLE"
    assert placements[0]["status"] == "RESERVED"
    assert placements[0]["equipment_unit_id"] == chosen_portable["id"]
    assert read_equipment_unit(spare_portable["id"])["status"] == "IN_STOCK"


# ─────────────────────────────────────────────────────────────────────────────
# The saturation boundary between the three qualifying groups
# ─────────────────────────────────────────────────────────────────────────────


def test_saturation_of_88_percent_is_a_group_i_hit():
    """A documented saturation of 88 percent sits on the inclusive Group I bound.

    PRD: "A study is a Group I hit when either the saturation is present and is at most 88 percent, or the partial pressure is present and is at most 55 millimetres of mercury."

    Design: Difficulty/boundary_precision_check/spo2_88_qualifies_group_i_89_requires_cor_pulmonale
    """
    scenario = setup_admitted_patient(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    payload = create_qualifying_test_payload(
        scenario["patient"]["id"],
        test_type="RESTING_ROOM_AIR",
        spo2_percent=88,
        tested_at="2026-07-25T14:00:00Z",
        cor_pulmonale_or_edema=False,
    )

    study = validate_success(
        api_client.create_qualifying_test(payload, INTAKE_COORDINATOR), 201
    )
    assert_qualifying_test(study)
    assert study["qualifying_group"] == "GROUP_I"
    assert study["validity_days"] == 30, "a resting-room-air study is current for 30 days"
    assert study["test_validity_expires_at"].startswith("2026-08-24T14:00:00"), (
        "30 whole days added to tested_at, with no rounding"
    )


def test_saturation_of_89_percent_without_a_secondary_finding_is_non_qualifying():
    """One saturation point above the Group I bound, with no secondary finding, qualifies for nothing.

    PRD: "A study that is neither a Group I hit nor a borderline study with a secondary finding is `NON_QUALIFYING`."

    Design: Difficulty/boundary_precision_check/spo2_88_qualifies_group_i_89_requires_cor_pulmonale
    """
    scenario = setup_admitted_patient(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    payload = create_qualifying_test_payload(
        scenario["patient"]["id"],
        test_type="RESTING_ROOM_AIR",
        spo2_percent=89,
        tested_at="2026-07-25T15:00:00Z",
        cor_pulmonale_or_edema=False,
    )

    study = validate_success(
        api_client.create_qualifying_test(payload, INTAKE_COORDINATOR), 201
    )
    assert_qualifying_test(study)
    assert study["qualifying_group"] == "NON_QUALIFYING"
    assert study["cor_pulmonale_or_edema"] is False


def test_saturation_of_89_percent_with_cor_pulmonale_is_group_ii():
    """The same borderline saturation becomes Group II when the chart documents cor pulmonale.

    PRD: "A borderline study whose chart also documents cor pulmonale or dependent edema is `GROUP_II`."

    Design: Difficulty/boundary_precision_check/spo2_88_qualifies_group_i_89_requires_cor_pulmonale
    """
    scenario = setup_admitted_patient(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    payload = create_qualifying_test_payload(
        scenario["patient"]["id"],
        test_type="RESTING_ROOM_AIR",
        spo2_percent=89,
        tested_at="2026-07-25T16:00:00Z",
        cor_pulmonale_or_edema=True,
    )

    study = validate_success(
        api_client.create_qualifying_test(payload, INTAKE_COORDINATOR), 201
    )
    assert_qualifying_test(study)
    assert study["qualifying_group"] == "GROUP_II"
    assert study["cor_pulmonale_or_edema"] is True


def test_one_saturation_point_separates_all_three_qualifying_groups():
    """Studies at 88, 89 and 89-with-cor-pulmonale land on three different groups.

    PRD: "Otherwise the borderline Group II test is evaluated: a study is borderline when either the saturation is present and is exactly 89 percent, or the partial pressure is present and lies inside the inclusive range 56 through 59 millimetres of mercury."

    Design: Difficulty/boundary_precision_check/spo2_88_qualifies_group_i_89_requires_cor_pulmonale
    """
    scenario = setup_admitted_patient(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"}
    )
    patient_id = scenario["patient"]["id"]

    groups = {}
    for spo2, tested_at, secondary_finding in (
        (88, "2026-07-25T14:00:00Z", False),
        (89, "2026-07-25T15:00:00Z", False),
        (89, "2026-07-25T16:00:00Z", True),
    ):
        payload = create_qualifying_test_payload(
            patient_id,
            test_type="RESTING_ROOM_AIR",
            spo2_percent=spo2,
            tested_at=tested_at,
            cor_pulmonale_or_edema=secondary_finding,
        )
        study = validate_success(
            api_client.create_qualifying_test(payload, INTAKE_COORDINATOR), 201
        )
        groups[(spo2, secondary_finding)] = study["qualifying_group"]

    assert groups[(88, False)] == "GROUP_I"
    assert groups[(89, False)] == "NON_QUALIFYING"
    assert groups[(89, True)] == "GROUP_II"

    rows, meta = validate_paginated(
        api_client.list_qualifying_tests(
            INTAKE_COORDINATOR, params={"patient_id": patient_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(row["qualifying_group"] for row in rows) == [
        "GROUP_I",
        "GROUP_II",
        "NON_QUALIFYING",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# The documentation score boundary at the inclusive pass threshold of 85.00
# ─────────────────────────────────────────────────────────────────────────────


def test_documentation_score_of_seven_documented_hours_rounds_to_84_38():
    """Seven documented hours a day score 84.375, which one final half-up rounding carries to 84.38.

    PRD: "The six components are added together **at unlimited precision** and the sum is rounded half up to two decimal places exactly once, at the very end."

    Design: Difficulty/boundary_precision_check/documentation_score_exactly_85_passes_submit_84_38_fails
    """
    scenario = setup_drafted_cmn(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={
            "prescribed_lpm": 3.0,
            "hours_per_day": 7,
            "portable_prescribed": True,
            "length_of_need_months": 6,
            "narrative_element_count": 3,
        },
    )

    # 30 group + 20 currency + 15 * 7 / 24 usage + 20 narrative + 10 portable + 0 duration.
    assert round(float(scenario["cmn"]["documentation_score"]), 2) == 84.38
    assert scenario["cmn"]["status"] == "DRAFT"


def test_documentation_score_of_eight_documented_hours_is_exactly_85():
    """Eight documented hours a day put the usage component at a whole 5 points and the score at 85.00.

    PRD: "Take the documented hours per day, capped at 24, divide by 24, and multiply by 15."

    Design: Difficulty/boundary_precision_check/documentation_score_exactly_85_passes_submit_84_38_fails
    """
    scenario = setup_drafted_cmn(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={
            "prescribed_lpm": 3.0,
            "hours_per_day": 8,
            "portable_prescribed": True,
            "length_of_need_months": 6,
            "narrative_element_count": 3,
        },
    )

    # 30 + 20 + 5 + 20 + 10 + 0 = 85.0 exactly, one hour of use above the 84.38 case.
    assert round(float(scenario["cmn"]["documentation_score"]), 2) == 85.00
    assert scenario["cmn"]["status"] == "DRAFT"


def test_submission_is_refused_one_hundredth_below_the_pass_threshold():
    """A certificate scoring 84.38 cannot be submitted and stays in draft, unstamped.

    PRD: "Submission by an `IntakeCoordinator` advances the certificate `DRAFT → SUBMITTED` and is guarded by four preconditions beyond the state itself: the linked study's group must not be `NON_QUALIFYING`; the logical clock must be at or before the study's expiry instant plus the 15-day grace period, or the submission fails with `ERR_QUALIFYING_TEST_STALE`; the freshly recomputed documentation score must have reached the pass threshold of 85.00, or the submission fails with `ERR_DOCUMENTATION_INCOMPLETE`; and the patient must be `ACTIVE`."

    Design: Difficulty/boundary_precision_check/documentation_score_exactly_85_passes_submit_84_38_fails
    """
    scenario = setup_drafted_cmn(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={
            "prescribed_lpm": 3.0,
            "hours_per_day": 7,
            "portable_prescribed": True,
            "length_of_need_months": 6,
            "narrative_element_count": 3,
        },
    )
    cmn_id = scenario["cmn"]["id"]
    assert round(float(scenario["cmn"]["documentation_score"]), 2) == 84.38

    response = api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE.value)

    after = read_cmn(cmn_id)
    assert after["status"] == "DRAFT"
    assert after["submitted_by_user_id"] is None
    assert round(float(after["documentation_score"]), 2) == 84.38


def test_submission_is_accepted_at_exactly_the_pass_threshold():
    """A certificate scoring exactly 85.00 clears the inclusive threshold and reaches submitted.

    PRD: "On success the score is recomputed and persisted, `submitted_by_user_id` is stamped with the acting operator's `X-User-ID`, the patient's mirrored certificate status becomes `SUBMITTED` when this is the patient's newest certificate, and the certificate's `version` increments by 1."

    Design: Difficulty/boundary_precision_check/documentation_score_exactly_85_passes_submit_84_38_fails
    """
    scenario = setup_drafted_cmn(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={
            "prescribed_lpm": 3.0,
            "hours_per_day": 8,
            "portable_prescribed": True,
            "length_of_need_months": 6,
            "narrative_element_count": 3,
        },
    )
    cmn_id = scenario["cmn"]["id"]
    drafted_version = scenario["cmn"]["version"]

    submitted = validate_success(api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == USER_IDS["IntakeCoordinator"]
    assert round(float(submitted["documentation_score"]), 2) == 85.00
    assert submitted["version"] == drafted_version + 1
