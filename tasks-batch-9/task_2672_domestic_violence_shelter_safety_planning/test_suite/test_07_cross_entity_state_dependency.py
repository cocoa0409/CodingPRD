"""Operations on one entity that are gated by the state of another: housing referrals
waiting on the survivor's safety plan, and a blocked component waiting on her posture.
"""

from test_helpers import (
    ApiErrorId,
    MODERATE_FACTORS,
    api_client,
    approve_screening,
    assert_bed_ledger_invariant,
    assert_component_scoring,
    assert_housing_referral,
    client_version,
    create_housing_referral_payload,
    create_plan_component_payload,
    create_safety_plan_payload,
    get_success_data,
    read_client,
    read_plan,
    read_unit,
    relocate,
    report_compromise,
    reserve_bed,
    seed_client_with_assessed_call,
    seed_draft_plan_by_disposition,
    seed_hotline_advocate,
    seed_hotline_call,
    seed_housing_specialist,
    seed_landlord_partner,
    seed_risk_assessment,
    seed_screening_request,
    seed_shelter_scene,
    seed_unit,
    read_partner,
    validate_error,
    validate_paginated,
    validate_success,
)

VOUCHER_REFERRAL = {"program_type": "TRANSITIONAL_HOUSING", "subsidy_type": "HOUSING_CHOICE_VOUCHER"}


def _draft_plan_and_waiting_partner():
    """An activatable but still DRAFT plan, plus the landlord the specialist wants to use."""
    advocate = seed_hotline_advocate("Rosa Marin")
    specialist = seed_housing_specialist("Omar Diaz")
    client, call, assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides={
            "client_code": "C-9301",
            "legal_name": "Nadia Roe",
            "household_size": 1,
            "minor_children_count": 0,
            "hmis_disclosure_consent": "DENIED",
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={
            "presenting_concerns": "Asking about rehousing options once the plan is written."
        },
    )
    seed_draft_plan_by_disposition(advocate, client["id"], call["id"])
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(
                client["id"], assessment["id"], client_version(client["id"], advocate.headers)
            ),
            advocate.headers,
        )
    )
    get_success_data(
        api_client.create_plan_component(
            plan["id"],
            create_plan_component_payload(
                "RELOCATION",
                detail="Short-term stay with her aunt while the lease is arranged.",
                target_completion_date="2026-08-20",
            ),
            advocate.headers,
        )
    )
    partner = seed_landlord_partner(
        specialist,
        name="Vista Rentals",
        units_pledged=4,
        accepts_subsidy_type="HOUSING_CHOICE_VOUCHER",
        base_incentive_cents=40000,
    )
    return advocate, specialist, client, plan, partner


def test_referral_create_is_refused_while_the_survivors_plan_is_still_draft():
    """Housing work may not run ahead of safety work.

    PRD: "The survivor must have exactly one safety plan in status `ACTIVE`; without one the
    referral is refused with `ERR_NO_ACTIVE_SAFETY_PLAN`, which is the mechanism that stops
    housing work from running ahead of safety work."

    Design: Difficulty/cross_entity_state_dependency/referral_creation_requires_client_active_safety_plan
    """
    _advocate, specialist, client, plan, partner = _draft_plan_and_waiting_partner()
    assert plan["status"] == "DRAFT"

    response = api_client.create_housing_referral(
        create_housing_referral_payload(client["id"], partner["id"], **VOUCHER_REFERRAL),
        specialist.headers,
    )

    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_SAFETY_PLAN.value, 409)
    rows, _meta = validate_paginated(
        api_client.list_housing_referrals(
            specialist.headers, params={"client_id": client["id"], "limit": 100, "offset": 0}
        )
    )
    assert rows == []
    assert read_partner(specialist, partner["id"])["units_committed"] == 0


def test_the_same_referral_create_succeeds_once_that_plan_reaches_active():
    """Nothing about the payload changes; only the other entity's status does.

    PRD: "The referral is stamped with `created_by_staff_id` from the acting specialist and
    starts at `SUBMITTED` with `monthly_rent_cents` null, `incentive_fee_cents` null,
    `incentive_tier_applied` null, `rejection_reason` null, `lease_start_date` null,
    `withdraw_count` 0 and `version` 1."

    Design: Difficulty/cross_entity_state_dependency/referral_creation_requires_client_active_safety_plan
    """
    advocate, specialist, client, plan, partner = _draft_plan_and_waiting_partner()
    validate_error(
        api_client.create_housing_referral(
            create_housing_referral_payload(client["id"], partner["id"], **VOUCHER_REFERRAL),
            specialist.headers,
        ),
        ApiErrorId.ERR_NO_ACTIVE_SAFETY_PLAN.value,
        409,
    )
    activated = get_success_data(api_client.activate_safety_plan(plan["id"], advocate.headers))
    assert activated["status"] == "ACTIVE"
    assert activated["coverage_score"] == 1.05

    response = api_client.create_housing_referral(
        create_housing_referral_payload(client["id"], partner["id"], **VOUCHER_REFERRAL),
        specialist.headers,
    )

    referral = validate_success(response, 201)
    assert_housing_referral(referral)
    assert referral["status"] == "SUBMITTED"
    assert referral["incentive_fee_cents"] is None
    assert referral["incentive_tier_applied"] is None
    assert referral["withdraw_count"] == 0
    after = read_partner(specialist, partner["id"])
    assert after["units_committed"] == 0
    assert after["units_available"] == 4


def _sealed_client_with_a_blocked_component():
    """An ACTIVE two-component plan wrecked by a compromise, leaving one BLOCKED row."""
    scene = seed_shelter_scene(
        shelter_overrides={
            "name": "Elm House",
            "nightly_rate_cents": 8000,
            "weekend_surcharge_cents": 2000,
            "child_supplement_cents": 1000,
        },
        unit_overrides={"unit_label": "B1", "unit_type": "STANDARD", "bed_capacity": 2},
    )
    spare_unit = seed_unit(
        scene.manager,
        scene.shelter["id"],
        unit_label="B2",
        unit_type="STANDARD",
        bed_capacity=2,
    )
    advocate = scene.advocate
    client, first_call, assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides={
            "client_code": "C-9401",
            "legal_name": "Nadia Roe",
            "household_size": 1,
            "minor_children_count": 0,
            "hmis_disclosure_consent": "DENIED",
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={
            "presenting_concerns": "Wants a plan and a bed; unsure about telling her manager."
        },
    )
    seed_draft_plan_by_disposition(advocate, client["id"], first_call["id"])
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(
                client["id"], assessment["id"], client_version(client["id"], advocate.headers)
            ),
            advocate.headers,
        )
    )
    communication = get_success_data(
        api_client.create_plan_component(
            plan["id"],
            create_plan_component_payload(
                "COMMUNICATION",
                detail="Second prepaid handset kept at her aunt's flat.",
                target_completion_date="2026-08-14",
            ),
            advocate.headers,
        )
    )
    workplace = get_success_data(
        api_client.create_plan_component(
            plan["id"],
            create_plan_component_payload(
                "WORKPLACE_NOTIFICATION",
                detail="Tell the shift supervisor and remove her name from the public rota.",
                target_completion_date="2026-08-18",
            ),
            advocate.headers,
        )
    )
    plan = get_success_data(api_client.activate_safety_plan(plan["id"], advocate.headers))
    assert plan["coverage_score"] == 1.58
    second_call = seed_hotline_call(
        advocate, client["id"], presenting_concerns="Calling back to take the bed that was offered."
    )
    seed_risk_assessment(advocate, second_call["id"], **MODERATE_FACTORS)
    request = seed_screening_request(
        advocate,
        client["id"],
        second_call["id"],
        scene.shelter["id"],
        requested_entry_date="2026-08-10",
    )
    approve_screening(scene.manager, request["id"], advocate.id)
    admission = get_success_data(
        reserve_bed(
            scene, request["id"], entry_date="2026-08-10", planned_exit_date="2026-08-15"
        )
    )
    get_success_data(report_compromise(scene, admission["id"], compromise_source="DATA_BREACH"))
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"
    assert read_plan(plan["id"], advocate.headers)["coverage_score"] == 0.88
    return scene, spare_unit, client, plan, communication, workplace, admission


def _component(plan_id, headers, component_id):
    rows = get_success_data(
        api_client.list_plan_components(plan_id, headers, params={"limit": 100, "offset": 0})
    )
    return [row for row in rows if row["id"] == component_id][0]


def test_blocked_component_cannot_be_implemented_while_the_client_is_sealed():
    """The component's own transition is legal; the survivor's posture forbids it.

    PRD: "From `BLOCKED` it is allowed only once the plan's client is no longer `SEALED`;
    attempting it while the client is still sealed is refused with
    `ERR_CONFIDENTIALITY_HOLD`, and since the only route out of `SEALED` for a compromised
    household is a completed relocation, that is the practical precondition."

    Design: Difficulty/cross_entity_state_dependency/blocked_component_implement_requires_client_out_of_sealed
    """
    scene, _spare_unit, _client, plan, _communication, workplace, _admission = (
        _sealed_client_with_a_blocked_component()
    )
    blocked = _component(plan["id"], scene.advocate.headers, workplace["id"])
    assert blocked["status"] == "BLOCKED"

    response = api_client.implement_plan_component(
        plan["id"], workplace["id"], scene.advocate.headers
    )

    validate_error(response, ApiErrorId.ERR_CONFIDENTIALITY_HOLD.value, 409)
    unchanged = _component(plan["id"], scene.advocate.headers, workplace["id"])
    assert_component_scoring(unchanged, 20, 0.0, "BLOCKED")
    assert read_plan(plan["id"], scene.advocate.headers)["coverage_score"] == 0.88


def test_completing_the_relocation_unseals_the_client_and_unblocks_the_component():
    """Moving the household is what changes the other entity's state, and only then does
    the same implement call succeed.

    PRD: "The client's `confidentiality_posture` is re-derived, and with no remaining
    compromised admission and no denied homeless-data-system export, `SEALED` falls back to
    `HEIGHTENED` or `NORMAL` — which is precisely what unblocks the `BLOCKED`
    workplace-notification component and lets the author implement it."

    Design: Difficulty/cross_entity_state_dependency/blocked_component_implement_requires_client_out_of_sealed
    """
    scene, spare_unit, client, plan, _communication, workplace, admission = (
        _sealed_client_with_a_blocked_component()
    )
    validate_error(
        api_client.implement_plan_component(plan["id"], workplace["id"], scene.advocate.headers),
        ApiErrorId.ERR_CONFIDENTIALITY_HOLD.value,
        409,
    )

    relocated = validate_success(relocate(scene, admission["id"], spare_unit["id"]), 200)

    assert relocated["location_security_status"] == "RELOCATED"
    assert relocated["shelter_unit_id"] == spare_unit["id"]
    assert relocated["prior_unit_id"] == scene.unit["id"]
    assert read_client(client["id"])["confidentiality_posture"] == "NORMAL"
    vacated = read_unit(scene.manager, scene.unit["id"])
    destination = read_unit(scene.manager, spare_unit["id"])
    assert vacated["reserved_beds"] == 0
    assert vacated["status"] == "AVAILABLE"
    assert destination["reserved_beds"] == 1
    assert destination["status"] == "HOLD"
    assert_bed_ledger_invariant(vacated)
    assert_bed_ledger_invariant(destination)
    implemented = validate_success(
        api_client.implement_plan_component(plan["id"], workplace["id"], scene.advocate.headers),
        200,
    )
    assert_component_scoring(implemented, 20, 2.0, "IMPLEMENTED")
    scored_plan = read_plan(plan["id"], scene.advocate.headers)
    assert scored_plan["coverage_score"] == 2.88
    assert scored_plan["status"] == "UNDER_REVISION"
