"""Incident creation, defaults, transition targeting, and single-incident reads.

Covers corner-design instances under sections `entities` and `validations`
that concern the Incident aggregate itself.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_incident,
    create_incident_payload,
    TEST_USERS,
)

EOC = TEST_USERS["eoc_manager_headers"]


def test_create_incident_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created incident starts with `op_status` of `MONITORING`,
    `activation_level` of `LEVEL_3`, `declaration_status` of `INELIGIBLE`, and every
    rolled-up aggregate — `total_committed_cost`, `total_actual_cost`,
    `federal_share_estimated`, `federal_share_actual`, and `total_verified_damage` — at zero."
    PRD §3.1: "an anticipated `declaration_category` (`EMERGENCY` or `MAJOR_DISASTER`,
    defaulting to `EMERGENCY`)"

    Design: Corner/entities/create_incident_returns_201_with_defaults
    """
    data = validate_success(
        api.create_incident(create_incident_payload(name="New Watch", hazard_type="FLOOD"), EOC),
        expected_status=201,
    )
    assert_incident(data)
    assert data["op_status"] == "MONITORING", f"expected MONITORING, got {data['op_status']}"
    assert data["activation_level"] == "LEVEL_3", f"expected LEVEL_3, got {data['activation_level']}"
    assert data["declaration_status"] == "INELIGIBLE"
    assert data["declaration_category"] == "EMERGENCY"
    assert data["total_committed_cost"] == 0
    assert data["total_verified_damage"] == 0


def test_get_incident_not_found_returns_404(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_INCIDENT_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_RESOURCE_POOL_NOT_FOUND`, `ERR_RESOURCE_REQUEST_NOT_FOUND`,
    `ERR_IAP_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_SHELTER_NOT_FOUND`, `ERR_MUTUAL_AID_NOT_FOUND`,
    `ERR_DAMAGE_ASSESSMENT_NOT_FOUND`, and `ERR_COST_RECORD_NOT_FOUND`. All are returned with HTTP 404."

    Design: Corner/entities/get_incident_not_found_returns_404
    """
    validate_error(
        api.get_incident(NON_EXISTENT_UUID, EOC),
        ApiErrorId.ERR_INCIDENT_NOT_FOUND.value,
    )


def test_incident_transition_missing_target(api):
    """PRD §3.1: "A transition request that supplies neither `to_status` nor
    `to_activation_level` is rejected with `ERR_MISSING_TRANSITION_TARGET`, and a
    `to_activation_level` that is not one of the three levels, or a level change
    attempted while the incident is not `ACTIVATED`, is rejected with `ERR_INVALID_ACTIVATION_LEVEL`."

    Design: Corner/validations/incident_transition_missing_target
    """
    inc = get_success_data(api.create_incident(create_incident_payload(name="Target Ctx"), EOC))
    validate_error(
        api.transition_incident(inc["id"], {}, EOC),
        ApiErrorId.ERR_MISSING_TRANSITION_TARGET.value,
    )
