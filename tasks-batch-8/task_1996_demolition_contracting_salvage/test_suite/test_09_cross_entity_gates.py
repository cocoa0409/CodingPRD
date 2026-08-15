"""Cross-entity state gates: abatement clearance gated by the parent survey."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_structure_survey_payload, create_abatement_payload,
    make_abatement_supervisor_headers,
    create_project, create_and_complete_survey,
)

SURVEYOR = TEST_USERS["surveyor_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]


class TestAbatementClearanceGate:
    def test_abatement_clearance_requires_survey_complete(self):
        """PRD §3.2: "When the work is done, the same role requests clearance,
        moving the order to `CLEARANCE_PENDING` — but only if the parent
        structure survey is already `COMPLETE`; requesting clearance against a
        survey still `IN_PROGRESS` is rejected with `ERR_SURVEY_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/abatement_clearance_requires_survey_complete
        """
        project = create_project(name="Gate Lot", address="67 Elm St", lot_area_sqft=20000)
        survey = get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        ab = get_success_data(
            api_client.create_abatement(
                survey["id"],
                create_abatement_payload(material_type="LEAD_PAINT",
                                         description="window trim",
                                         containment_method="chemical strip"),
                SURVEYOR,
            )
        )
        starter = make_abatement_supervisor_headers("ga-s-1")
        get_success_data(api_client.transition_abatement(ab["id"], {"action": "START"}, starter))
        resp = api_client.transition_abatement(ab["id"], {"action": "REQUEST_CLEARANCE"}, starter)
        validate_error(resp, ApiErrorId.ERR_SURVEY_INCOMPLETE)
        listed = get_success_data(api_client.list_abatements(survey["id"], SURVEYOR))
        assert listed[0]["status"] == "ABATEMENT_ACTIVE"

    def test_abatement_clearance_allowed_after_survey_complete(self):
        """PRD §3.2: "When the work is done, the same role requests clearance,
        moving the order to `CLEARANCE_PENDING` — but only if the parent
        structure survey is already `COMPLETE`; requesting clearance against a
        survey still `IN_PROGRESS` is rejected with `ERR_SURVEY_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/abatement_clearance_requires_survey_complete
        """
        project = create_project(name="GateOk", address="67B Elm St", lot_area_sqft=20000)
        survey = create_and_complete_survey(project["id"], hazmat_found=True)
        ab = get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        starter = make_abatement_supervisor_headers("ga-s-2")
        get_success_data(api_client.transition_abatement(ab["id"], {"action": "START"}, starter))
        ok = get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "REQUEST_CLEARANCE"}, starter)
        )
        assert ok["status"] == "CLEARANCE_PENDING"
