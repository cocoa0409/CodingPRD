"""Validation pipeline ordering and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_confirmed_equipment_assignment,
    create_equipment_unit,
    create_job,
    create_permit_payload,
    create_site_with_active_schedule,
    get_success_data,
    schedule_and_mobilize,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


class TestValidationPipelineOrder:
    def test_shape_error_beats_existence_error_on_job_create(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the first failing check determines the error returned: ... 3.
        **Request shape** — required fields are present, types are valid, enum
        membership is valid ... else `ERR_INVALID_REQUEST`. 4. **Existence** —
        path identifiers and body foreign keys reference existing resources,
        validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/validations/shape_error_beats_existence_error_on_job_create
        """
        resp = api.create_job(
            {
                "site_id": NON_EXISTENT_UUID,
                "job_type": "BOGUS",
                "pricing_mode": "UNIT_RATE",
                "description": "double violation",
            },
            PM,
        )
        assert resp.status_code == 400
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestImmediateConsistency:
    def test_mutation_visible_in_same_response(self, api):
        """PRD §2.4: "Consistency is immediate rather than eventual".

        Design: Corner/consistency_model/immediate_mutation_visible_in_same_response_and_read
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit(unit_code="VAC-02")
        job = create_job(site["id"], description="consistency probe")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        permit = get_success_data(
            api.create_permit(create_permit_payload(job["id"]), FS)
        )
        assert permit["status"] == "ISSUED"
        activated = validate_success(api.activate_permit(permit["id"], FS), 200)
        assert activated["status"] == "ACTIVE"

    def test_read_after_write_consistent_in_list(self, api):
        """PRD §2.4: "Consistency is immediate rather than eventual: derived
        values such as a job's accrued standby total or a facility's reserved
        tonnage are recomputed inside the triggering write, never deferred to a
        later pass."

        Design: Corner/consistency_model/immediate_mutation_visible_in_same_response_and_read
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit(unit_code="VAC-02")
        job = create_job(site["id"])
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        permit = get_success_data(
            api.create_permit(create_permit_payload(job["id"]), FS)
        )
        get_success_data(api.activate_permit(permit["id"], FS))
        data, meta = validate_paginated(api.list_permits(PM, params={"job_id": job["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == permit["id"]
        assert data[0]["status"] == "ACTIVE"
