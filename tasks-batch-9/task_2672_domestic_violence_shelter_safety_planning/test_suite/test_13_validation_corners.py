"""Corner readings of the validation catalogue: uniqueness scopes that differ per rule, the
subsidy and pledge guards on housing work, the caseload ceiling, the two date windows that
point in opposite directions, the two unit-fitness rules and the same-unit relocation bar.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MODERATE_FACTORS,
    ApiErrorId,
    api_client,
    create_client_payload,
    create_plan_component_payload,
    create_shelter_unit_payload,
    create_wellness_check_payload,
    decide_screening,
    dispose_call,
    file_case,
    get_success_data,
    match_referral,
    read_admission,
    read_client,
    read_partner,
    read_plan,
    read_shelter,
    read_staff,
    read_unit,
    relocate,
    report_compromise,
    reserve_bed,
    seed_active_plan,
    seed_approved_screening,
    seed_client,
    seed_client_with_assessed_call,
    seed_hotline_advocate,
    seed_housing_specialist,
    seed_imminent_client,
    seed_landlord_partner,
    seed_legal_advocate,
    seed_plan_with_components,
    seed_protective_order_case,
    seed_reserved_admission,
    seed_screening_request,
    seed_shelter,
    seed_shelter_manager,
    seed_shelter_scene,
    seed_unit,
    submit_referral,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)

CEDAR_RATES = {
    "name": "Cedar House",
    "confidential_location": True,
    "nightly_rate_cents": 8500,
    "weekend_surcharge_cents": 2500,
    "child_supplement_cents": 1200,
}
STANDARD_A1 = {"unit_label": "A1", "unit_type": "STANDARD", "bed_capacity": 4}
PAGE = {"limit": 10, "offset": 0}
STAY = {"entry_date": "2026-08-07", "planned_exit_date": "2026-08-12"}


def test_a_client_code_is_unique_agency_wide_but_a_unit_label_only_within_its_shelter():
    """One rule, two scopes: the repeated label is refused in Cedar House and accepted in Birch.

    PRD: "The `client_code` is the identifier that appears in every artefact that ever leaves
    the agency, and it must be unique across every survivor record regardless of that record's
    status; a collision is refused with `ERR_DUPLICATE_RESOURCE`."

    PRD: "Each carries a `unit_label` of between 1 and 20 characters, unique within that
    facility — a repeat label is `ERR_DUPLICATE_RESOURCE` — a `bed_capacity` of between 1 and 8
    physical beds, and a `unit_type` that encodes accessibility and family-composition fitness
    in a single value."

    Design: Corner/validations/duplicate_client_code_and_duplicate_unit_label_rejected
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    manager = seed_shelter_manager("Dana Whit", max_caseload=20)
    client = seed_client(
        advocate, client_code="C-4001", legal_name="Hope Lyle", household_size=2,
        minor_children_count=0,
    )
    cedar = seed_shelter(manager, **CEDAR_RATES)
    a1 = seed_unit(manager, cedar["id"], **STANDARD_A1)
    birch = seed_shelter(manager, name="Birch House")

    repeated_code = api_client.create_client(
        create_client_payload(
            client_code="C-4001", legal_name="Different Person", household_size=3
        ),
        advocate.headers,
    )
    repeated_label = api_client.create_shelter_unit(
        cedar["id"],
        create_shelter_unit_payload(unit_label="A1", unit_type="FAMILY_SUITE", bed_capacity=3),
        manager.headers,
    )
    free_label = api_client.create_shelter_unit(
        birch["id"],
        create_shelter_unit_payload(unit_label="A1", unit_type="STANDARD", bed_capacity=2),
        manager.headers,
    )

    validate_error(repeated_code, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)
    validate_error(repeated_label, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)
    accepted = validate_success(free_label, 201)
    assert read_client(client["id"])["legal_name"] == "Hope Lyle"
    survivor_unit = read_unit(manager, a1["id"])
    assert survivor_unit["unit_type"] == "STANDARD"
    assert survivor_unit["bed_capacity"] == 4
    assert accepted["unit_label"] == "A1"
    assert accepted["bed_capacity"] == 2
    assert read_shelter(manager, cedar["id"])["total_bed_capacity"] == 4
    assert read_shelter(manager, birch["id"])["total_bed_capacity"] == 2


def test_a_second_component_of_one_domain_is_refused_and_the_score_does_not_double():
    """The uniqueness scope is the plan-and-domain pair, and the rejected call adds no coverage.

    PRD: "Each component carries the `safety_plan_id` of the plan it belongs to, and the pair of
    `safety_plan_id` and `component_type` is unique: a plan may hold at most one component per
    domain, and a second component of the same `component_type` on the same plan is refused with
    `ERR_DUPLICATE_RESOURCE`."

    PRD: "Each component's `subscore` is its `weight_effective` multiplied by its status factor,
    divided by 10, and rounded half up to two decimal places."

    Design: Corner/validations/second_component_of_the_same_type_on_one_plan_rejected
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    client, plan, components = seed_plan_with_components(
        advocate,
        client_overrides={
            "client_code": "C-4002",
            "legal_name": "Iris Poole",
            "household_size": 2,
            "minor_children_count": 0,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        component_types=("COMMUNICATION",),
        component_overrides={
            "COMMUNICATION": {
                "detail": "A prepaid handset the abuser has never seen.",
                "target_completion_date": "2026-08-22",
            }
        },
    )
    assert read_client(client["id"])["current_risk_band"] == "MODERATE"
    assert components[0]["subscore"] == 0.88
    before = read_plan(plan["id"], advocate.headers)
    assert before["coverage_score"] == 0.88

    response = api_client.create_plan_component(
        plan["id"],
        create_plan_component_payload(
            "COMMUNICATION",
            detail="A second phone, duplicate entry.",
            target_completion_date="2026-08-22",
        ),
        advocate.headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)
    rows, meta = validate_paginated(
        api_client.list_plan_components(plan["id"], advocate.headers, params=dict(PAGE))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == components[0]["id"]
    assert rows[0]["status"] == "DRAFT"
    after = read_plan(plan["id"], advocate.headers)
    assert after["coverage_score"] == 0.88
    assert after["version"] == before["version"]


def test_a_referral_must_carry_the_subsidy_its_partner_accepts():
    """The plan gate is satisfied, so the subsidy rule is the one that speaks.

    PRD: "And the referral's `subsidy_type` must equal the partner's `accepts_subsidy_type`; a
    mismatch is `ERR_SUBSIDY_TYPE_MISMATCH`."

    PRD: "The referral is stamped with `created_by_staff_id` from the acting specialist and
    starts at `SUBMITTED` with `monthly_rent_cents` null, `incentive_fee_cents` null,
    `incentive_tier_applied` null, `rejection_reason` null, `lease_start_date` null,
    `withdraw_count` 0 and `version` 1."

    Design: Corner/validations/referral_subsidy_type_must_match_the_partner_and_is_rejected_otherwise
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    specialist = seed_housing_specialist("Omar Diaz", max_caseload=15)
    client, plan, _components = seed_active_plan(
        advocate,
        client_overrides={
            "client_code": "C-4003",
            "legal_name": "Jae Hollis",
            "household_size": 2,
            "minor_children_count": 0,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        component_types=("RELOCATION",),
    )
    partner = seed_landlord_partner(
        specialist,
        name="Vista Rentals",
        units_pledged=4,
        accepts_subsidy_type="RAPID_REHOUSING_SUBSIDY",
        base_incentive_cents=40000,
    )
    assert plan["status"] == "ACTIVE"
    assert plan["coverage_score"] == 1.05

    wrong_subsidy = api_client.create_housing_referral(
        {
            "client_id": client["id"],
            "landlord_partner_id": partner["id"],
            "program_type": "RAPID_REHOUSING",
            "subsidy_type": "HOUSING_CHOICE_VOUCHER",
        },
        specialist.headers,
    )

    validate_error(wrong_subsidy, ApiErrorId.ERR_SUBSIDY_TYPE_MISMATCH.value, 422)
    accepted = submit_referral(
        specialist,
        client["id"],
        partner["id"],
        program_type="RAPID_REHOUSING",
        subsidy_type="RAPID_REHOUSING_SUBSIDY",
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["incentive_fee_cents"] is None
    assert accepted["incentive_tier_applied"] is None
    assert accepted["withdraw_count"] == 0
    assert accepted["created_by_staff_id"] == specialist.id
    ledger = read_partner(specialist, partner["id"])
    assert ledger["units_committed"] == 0
    assert ledger["units_available"] == 4
    assert ledger["incentive_accrued_cents"] == 0


def test_a_one_unit_partner_is_exhausted_by_its_first_match():
    """Pledge exhaustion, not a stale version, is what refuses the second match.

    PRD: "Four business preconditions apply beyond that guard, and they are evaluated in the
    global order of §2.7: the survivor's `confidentiality_posture` must not be `SEALED`, or the
    match is refused with `ERR_CONFIDENTIALITY_HOLD`; the survivor must still have exactly one
    `ACTIVE` safety plan, or `ERR_NO_ACTIVE_SAFETY_PLAN`; the partner's `accepts_subsidy_type`
    must still equal the referral's `subsidy_type`; and the partner's `units_available` must be
    at least 1, or the match is refused with `ERR_LANDLORD_NO_UNITS_AVAILABLE`."

    PRD: "The tier is read *before* this referral is counted as a commitment."

    Design: Corner/validations/landlord_with_zero_units_available_rejects_the_next_match
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    specialist = seed_housing_specialist("Omar Diaz", max_caseload=15)
    client, _plan, _components = seed_active_plan(
        advocate,
        client_overrides={
            "client_code": "C-4004",
            "legal_name": "Kira Sands",
            "household_size": 2,
            "minor_children_count": 0,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        component_types=("RELOCATION",),
    )
    partner = seed_landlord_partner(
        specialist,
        name="Solo Holdings",
        units_pledged=1,
        accepts_subsidy_type="RAPID_REHOUSING_SUBSIDY",
        base_incentive_cents=40000,
    )
    first = submit_referral(
        specialist, client["id"], partner["id"], program_type="TRANSITIONAL_HOUSING"
    )
    second = submit_referral(
        specialist, client["id"], partner["id"], program_type="TRANSITIONAL_HOUSING"
    )
    matched = get_success_data(
        match_referral(specialist, first["id"], partner["id"], monthly_rent_cents=140000)
    )
    assert matched["incentive_fee_cents"] == 40000
    assert matched["incentive_tier_applied"] == "BASE"
    exhausted = read_partner(specialist, partner["id"])
    assert exhausted["units_available"] == 0
    assert exhausted["units_committed"] == 1
    assert exhausted["engagement_score"] == 100.0
    assert exhausted["incentive_tier"] == "PLATINUM"

    response = match_referral(
        specialist,
        second["id"],
        partner["id"],
        monthly_rent_cents=138000,
        expected_landlord_partner_version=exhausted["version"],
    )

    validate_error(response, ApiErrorId.ERR_LANDLORD_NO_UNITS_AVAILABLE.value, 409)
    survivor = get_success_data(
        api_client.get_housing_referral(second["id"], specialist.headers)
    )
    assert survivor["status"] == "SUBMITTED"
    assert survivor["incentive_fee_cents"] is None
    assert read_partner(specialist, partner["id"])["incentive_accrued_cents"] == 40000


def test_an_advocate_with_a_ceiling_of_one_cannot_take_a_second_approval():
    """The ceiling bites while the wellness posture is still open.

    PRD: "And it requires that the named advocate's `active_caseload_count` be strictly below
    their `max_caseload`; an advocate already at or over their ceiling is refused with
    `ERR_CASELOAD_LIMIT_EXCEEDED`."

    PRD: "It counts the screening requests whose `assigned_advocate_id` is this member and whose
    `status` is `APPROVED` or `ADMITTED`, excluding any request for which a shelter admission
    exists that has already reached `EXITED`."

    Design: Corner/validations/advocate_at_the_caseload_ceiling_rejected_on_the_second_approval
    """
    scene = seed_shelter_scene(
        shelter_overrides=dict(CEDAR_RATES),
        unit_overrides=dict(STANDARD_A1),
        advocate_overrides={"full_name": "Rosa Marin", "max_caseload": 1},
    )
    requests = []
    for code, name in (("C-4005", "Lena Roque"), ("C-4006", "Mira Okon")):
        client, call, _assessment = seed_client_with_assessed_call(
            scene.advocate,
            client_overrides={
                "client_code": code,
                "legal_name": name,
                "household_size": 2,
                "minor_children_count": 0,
            },
            assessment_overrides=dict(MODERATE_FACTORS),
        )
        requests.append(
            seed_screening_request(
                scene.advocate,
                client["id"],
                call["id"],
                scene.shelter["id"],
                requested_entry_date="2026-08-07",
            )
        )
    first, second = requests
    validate_success(
        decide_screening(
            scene.manager, first["id"], "APPROVE", assigned_advocate_id=scene.advocate.id
        ),
        200,
    )
    loaded = read_staff(scene.advocate.id)
    assert loaded["active_caseload_count"] == 1
    assert loaded["secondary_trauma_index"] == 2.5
    assert loaded["wellness_posture"] == "OPEN"

    response = decide_screening(
        scene.manager, second["id"], "APPROVE", assigned_advocate_id=scene.advocate.id
    )

    validate_error(response, ApiErrorId.ERR_CASELOAD_LIMIT_EXCEEDED.value, 409)
    untouched = get_success_data(
        api_client.get_screening_request(second["id"], scene.manager.headers)
    )
    assert untouched["status"] == "PENDING"
    assert untouched["assigned_advocate_id"] is None
    assert untouched["decided_at"] is None
    assert untouched["version"] == 1
    after = read_staff(scene.advocate.id)
    assert after["active_caseload_count"] == 1
    assert after["secondary_trauma_index"] == 2.5


def test_one_date_rule_points_backwards_for_a_debrief_and_forwards_for_a_hearing():
    """A wellness check may not be dated after the clock; a hearing must start after it.

    PRD: "Each check names the `staff_member_id` it covers through the path it is filed under,
    and carries `checked_on_utc` — when the debrief actually happened, which may not be later
    than the logical clock reading, on pain of `ERR_INVALID_DATE_WINDOW` — plus
    `exposure_hours`, the hours of direct survivor-contact exposure in the review window,
    accepted from 0 to 200 with one decimal place, and `distress_scale`, the member's
    self-reported distress on an integer scale from 0 for none to 10 for severe."

    PRD: "The hearing window is inclusive at both ends, `hearing_end_utc` must be strictly after
    `hearing_start_utc`, and `hearing_start_utc` must be strictly after the current logical
    clock reading — a hearing cannot be filed into the past or into the present instant."

    Design: Corner/validations/future_dated_wellness_check_and_past_dated_hearing_rejected
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    legal = seed_legal_advocate("Nils Berg", max_caseload=12)
    client = seed_client(
        advocate, client_code="C-4007", legal_name="Nora Blaise", household_size=2,
        minor_children_count=0,
    )
    case = seed_protective_order_case(legal, client["id"], order_type="EMERGENCY_EX_PARTE")

    future_check = api_client.create_wellness_check(
        advocate.id,
        create_wellness_check_payload(
            checked_on_utc="2026-08-05T00:00:00Z", exposure_hours=4.0, distress_scale=3
        ),
        ADMIN_HEADERS,
    )
    past_hearing = file_case(
        legal, case["id"], legal.id, "2026-07-30T09:00:00Z", "2026-07-30T10:00:00Z"
    )
    inverted_window = file_case(
        legal, case["id"], legal.id, "2026-08-05T10:00:00Z", "2026-08-05T09:00:00Z"
    )

    validate_error(future_check, ApiErrorId.ERR_INVALID_DATE_WINDOW.value, 422)
    validate_error(past_hearing, ApiErrorId.ERR_INVALID_DATE_WINDOW.value, 422)
    validate_error(inverted_window, ApiErrorId.ERR_INVALID_DATE_WINDOW.value, 422)
    member = read_staff(advocate.id)
    assert member["last_wellness_check_at"] is None
    assert member["secondary_trauma_index"] == 0.0
    unfiled = get_success_data(
        api_client.get_protective_order_case(case["id"], legal.headers)
    )
    assert unfiled["status"] == "PETITION_DRAFTED"
    assert unfiled["filed_court"] is None
    assert unfiled["version"] == 1
    assert read_client(client["id"])["protective_order_active"] is False


def test_the_imminent_bar_stops_the_warm_hand_off_and_nothing_else():
    """The same IMMINENT call is refused a referral and then accepted for a written plan.

    PRD: "It is also the only branch carrying a safety precondition: a warm hand-off may not be
    used to close an imminent-danger call, so if the client's `current_risk_band` is `IMMINENT`
    the disposition is refused with `ERR_IMMINENT_RISK_REFERRAL_FORBIDDEN`."

    PRD: "It recomputes `resource_referral_count` on the survivor record as the number of that
    client's hotline calls now sitting in status `RESOURCE_REFERRED`."

    Design: Corner/validations/imminent_risk_band_blocks_only_the_resource_referred_branch
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    imminent_client, imminent_call, imminent_assessment = seed_imminent_client(
        advocate,
        client_code="C-4008",
        legal_name="Odile Ferro",
        household_size=2,
        minor_children_count=0,
    )
    moderate_client, moderate_call, moderate_assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides={
            "client_code": "C-4009",
            "legal_name": "Perla Nunes",
            "household_size": 2,
            "minor_children_count": 0,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
    )
    assert imminent_assessment["danger_score"] == 100.0
    assert imminent_assessment["risk_band"] == "IMMINENT"
    assert moderate_assessment["danger_score"] == 48.4
    assert moderate_assessment["risk_band"] == "MODERATE"

    refused = dispose_call(advocate, imminent_call["id"], "RESOURCE_REFERRED")
    allowed = dispose_call(advocate, moderate_call["id"], "RESOURCE_REFERRED")
    planned = dispose_call(advocate, imminent_call["id"], "SAFETY_PLAN_ONLY")

    validate_error(refused, ApiErrorId.ERR_IMMINENT_RISK_REFERRAL_FORBIDDEN.value, 409)
    handed_off = validate_success(allowed, 200)
    assert handed_off["status"] == "RESOURCE_REFERRED"
    assert validate_success(planned, 200)["status"] == "SAFETY_PLAN_ONLY"
    referred_survivor = read_client(moderate_client["id"])
    assert referred_survivor["resource_referral_count"] == 1
    assert referred_survivor["status"] == "ACTIVE"
    assert referred_survivor["confidentiality_posture"] == "NORMAL"
    imminent_survivor = read_client(imminent_client["id"])
    assert imminent_survivor["resource_referral_count"] == 0
    assert imminent_survivor["confidentiality_posture"] == "HEIGHTENED"
    rows, meta = validate_paginated(
        api_client.list_safety_plans(
            advocate.headers, params=dict(PAGE, client_id=imminent_client["id"])
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "DRAFT"


def test_a_standard_room_with_four_free_beds_fits_neither_household():
    """Both fitness rules bind on a unit that has plenty of room, so neither is a capacity error.

    PRD: "A household whose `accessibility_required` is true may only be placed in a unit whose
    `unit_type` is `ADA_ACCESSIBLE`; any other unit type is `ERR_UNIT_ACCESSIBILITY_MISMATCH`."

    PRD: "A household whose `minor_children_count` is greater than zero may only be placed in a
    unit whose `unit_type` is `ADA_ACCESSIBLE` or `FAMILY_SUITE`; a `STANDARD` unit is
    `ERR_UNIT_COMPOSITION_MISMATCH`."

    Design: Corner/validations/standard_unit_rejects_accessibility_and_family_households
    """
    scene = seed_shelter_scene(
        shelter_overrides=dict(CEDAR_RATES), unit_overrides=dict(STANDARD_A1)
    )
    _client_a, _call_a, accessible_request = seed_approved_screening(
        scene,
        client_overrides={
            "client_code": "C-4010",
            "legal_name": "Quilla Reyes",
            "household_size": 2,
            "minor_children_count": 0,
            "accessibility_required": True,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        request_overrides={"requested_entry_date": "2026-08-07"},
    )
    _client_b, _call_b, family_request = seed_approved_screening(
        scene,
        client_overrides={
            "client_code": "C-4011",
            "legal_name": "Rina Vasco",
            "household_size": 3,
            "minor_children_count": 1,
            "accessibility_required": False,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        request_overrides={"requested_entry_date": "2026-08-07"},
    )
    version_before = unit_version(scene.manager, scene.unit["id"])

    accessibility_refusal = reserve_bed(
        scene, accessible_request["id"], expected_shelter_unit_version=version_before, **STAY
    )
    composition_refusal = reserve_bed(
        scene, family_request["id"], expected_shelter_unit_version=version_before, **STAY
    )

    validate_error(
        accessibility_refusal, ApiErrorId.ERR_UNIT_ACCESSIBILITY_MISMATCH.value, 422
    )
    validate_error(composition_refusal, ApiErrorId.ERR_UNIT_COMPOSITION_MISMATCH.value, 422)
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 0
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 4
    assert unit["status"] == "AVAILABLE"
    assert unit["version"] == version_before
    for request in (accessible_request, family_request):
        assert (
            get_success_data(
                api_client.get_screening_request(request["id"], scene.manager.headers)
            )["status"]
            == "APPROVED"
        )
    _rows, meta = validate_paginated(
        api_client.list_shelter_admissions(scene.manager.headers, params=dict(PAGE))
    )
    assert meta["total_count"] == 0


def test_a_relocation_must_actually_move_the_household_to_another_room():
    """Naming the current unit with its correct version is a same-unit refusal, not a stale guard.

    PRD: "The destination must be a unit other than the one the admission already occupies, or
    the request is refused with `ERR_SAME_UNIT_RELOCATION`, and it must belong to a facility, or
    the request is `ERR_CROSS_REFERENCE_MISMATCH`."

    PRD: "*Link two* sets the survivor's `confidentiality_posture` to `SEALED`, since a
    compromised admission is one of the two conditions that seal a record."

    Design: Corner/validations/relocation_to_the_same_unit_rejected
    """
    scene = seed_shelter_scene(
        shelter_overrides=dict(CEDAR_RATES), unit_overrides=dict(STANDARD_A1)
    )
    spare_unit = seed_unit(
        scene.manager, scene.shelter["id"], unit_label="A2", unit_type="STANDARD",
        bed_capacity=4,
    )
    scene, client, _request, admission = seed_reserved_admission(
        scene=scene,
        client_overrides={
            "client_code": "C-4012",
            "legal_name": "Sable Ines",
            "household_size": 2,
            "minor_children_count": 0,
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        admission_overrides=dict(STAY),
    )
    get_success_data(
        report_compromise(scene, admission["id"], compromise_source="DATA_BREACH")
    )
    occupied_version = unit_version(scene.manager, scene.unit["id"])

    response = relocate(
        scene,
        admission["id"],
        scene.unit["id"],
        expected_shelter_unit_version=occupied_version,
    )

    validate_error(response, ApiErrorId.ERR_SAME_UNIT_RELOCATION.value, 422)
    stuck = read_admission(scene.manager, admission["id"])
    assert stuck["location_security_status"] == "COMPROMISED"
    assert stuck["compromise_source"] == "DATA_BREACH"
    assert stuck["prior_unit_id"] is None
    assert stuck["shelter_unit_id"] == scene.unit["id"]
    origin = read_unit(scene.manager, scene.unit["id"])
    assert origin["reserved_beds"] == 2
    assert origin["available_beds"] == 2
    assert origin["status"] == "HOLD"
    assert origin["version"] == occupied_version
    untouched = read_unit(scene.manager, spare_unit["id"])
    assert untouched["reserved_beds"] == 0
    assert untouched["available_beds"] == 4
    assert untouched["status"] == "AVAILABLE"
    assert untouched["version"] == 1
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"
