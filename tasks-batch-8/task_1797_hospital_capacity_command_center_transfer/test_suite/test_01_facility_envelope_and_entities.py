"""Facility provisioning, response envelope shape, and entity-level corner cases."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_bed,
    assert_facility,
    assert_transfer_request,
    create_admission_payload,
    create_bed_payload,
    create_facility_payload,
    create_transfer_request_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestFacilityCreation:
    def test_facility_create_success_with_defaults(self, api):
        """PRD §3.1: "A new facility starts with every computed counter at zero,
        `diversion_status` of `ACCEPTING`, `diversion_recommended` false, and
        `next_elective_window_start` null."
        PRD §3.2: "When a facility has no staffed beds at all, both scores are
        zero and `diversion_recommended` is false."
        PRD §2.5: "`id` (string): a unique, server-generated identifier
        formatted as a UUID, with no type prefix."

        Design: Corner/entities/facility_create_success_with_defaults
        """
        set_clock()
        resp = api.create_facility(
            create_facility_payload(name="General", region="R9"), ADMIN)
        facility = validate_success(resp, 201)
        assert_facility(facility)
        assert facility["diversion_status"] == "ACCEPTING"
        assert facility["diversion_recommended"] is False
        assert facility["staffed_beds"] == 0
        assert facility["occupied_beds"] == 0
        assert facility["held_beds"] == 0
        assert facility["available_beds"] == 0
        assert facility["out_of_service_beds"] == 0
        assert facility["boarding_waiters"] == 0
        assert facility["active_inbound_transfers"] == 0
        assert facility["load_score_raw"] == 0
        assert facility["load_score_weighted"] == 0
        assert facility["next_elective_window_start"] is None
        assert facility["version"] == 1
        assert is_valid_uuid(facility["id"])

    def test_facility_get_not_found_returns_404(self, api):
        """PRD §2.7: "The first identifier in the path that does not resolve to
        an existing resource produces that resource type's 404 error".

        Design: Corner/entities/facility_get_not_found_returns_404
        """
        resp = api.get_facility(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", COORD)
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)


class TestBedRegistration:
    def test_bed_create_invalid_enum_rejected(self, api):
        """PRD §2.8: "Next comes request-body well-formedness — required fields
        present, types correct, enum values valid".
        PRD §5: `ERR_INVALID_REQUEST` is HTTP 400.

        Design: Corner/entities/bed_create_invalid_enum_rejected
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Enum Fac", region="R1"), ADMIN))
        payload = create_bed_payload(
            unit="C-1", label="B1", service="CARDIAC",
            max_acuity="ACUITY_9_IMPOSSIBLE", isolation_capability="NONE")
        resp = api.create_bed(facility["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_bed_staffed_and_turnover_defaults_applied(self, api):
        """PRD §3.1: "The optional `staffed` flag defaults to true — unstaffed
        beds are excluded from load denominators, occupancy figures, and the
        selector — and the optional `turnover_minutes` cleaning buffer defaults
        to 45. A newly registered bed starts in `AVAILABLE` status".

        Design: Corner/entities/bed_staffed_and_turnover_defaults_applied
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Def Fac", region="R1"), ADMIN))
        resp = api.create_bed(
            facility["id"],
            create_bed_payload(unit="C-1", label="B1", service="CARDIAC",
                               max_acuity="ACUITY_1_CRITICAL",
                               isolation_capability="NONE"),
            ADMIN)
        bed = validate_success(resp, 201)
        assert_bed(bed)
        assert bed["staffed"] is True, "staffed defaults to true"
        assert bed["turnover_minutes"] == 45, "turnover_minutes defaults to 45"
        assert bed["status"] == "AVAILABLE"


class TestAdmissionValidation:
    def test_admission_missing_required_bed_id_rejected(self, api):
        """PRD §3.6: "a `BedManager` may direct-admit a patient into a facility
        by naming the target `bed_id` along with `patient_ref`, `acuity`,
        `isolation_need`, and `service`."
        PRD §2.8: "Next comes request-body well-formedness — required fields
        present, types correct, enum values valid".

        Design: Corner/entities/admission_missing_required_bed_id_rejected
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Req Fac", region="R1"), ADMIN))
        payload = {
            "patient_ref": "PX",
            "acuity": "ACUITY_3_MEDICAL_SURGICAL",
            "isolation_need": "NONE",
            "service": "MEDICAL",
        }
        resp = api.create_admission(facility["id"], payload, BED_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_nested_child_under_wrong_parent_returns_child_404(self, api):
        """PRD §2.7: "A child identifier that exists but belongs to a different
        facility than the path's facility is reported with the child resource's
        404, not the facility's".

        Design: Corner/entities/nested_child_under_wrong_parent_returns_child_404
        """
        fac_a = get_success_data(api.create_facility(
            create_facility_payload(name="Fac A", region="R1"), ADMIN))
        fac_b = get_success_data(api.create_facility(
            create_facility_payload(name="Fac B", region="R1"), ADMIN))
        bed_a = get_success_data(api.create_bed(
            fac_a["id"],
            create_bed_payload(unit="C-1", label="B1", service="CARDIAC",
                               max_acuity="ACUITY_1_CRITICAL",
                               isolation_capability="NONE"),
            ADMIN))
        resp = api.create_admission(
            fac_b["id"],
            create_admission_payload(bed_a["id"], patient_ref="PX"),
            BED_MGR)
        validate_error(resp, ApiErrorId.ERR_BED_NOT_FOUND)


class TestTransferRequestIntake:
    def test_transfer_request_system_fields_ignore_client_input(self, api):
        """PRD §3.3: "The request is created in `INTAKE` status with the
        coordinator's `X-User-ID` recorded as `intake_coordinator_id`,
        `consult_count` at zero, and no `accepting_physician_id`,
        `consult_deadline`, `decline_reason`, or `assigned_bed_id`".

        Design: Corner/entities/transfer_request_computed_and_system_fields_ignored_input_ignored
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Sys Fac", region="R1"), ADMIN))
        payload = create_transfer_request_payload(
            patient_ref="PS1", service="CARDIAC", priority="URGENT")
        # Client attempts to smuggle system-managed fields; they must be ignored.
        payload["status"] = "COMPLETED"
        payload["consult_count"] = 99
        from test_helpers import make_coordinator_headers
        resp = api.create_transfer_request(
            facility["id"], payload, make_coordinator_headers("coord_9"))
        request = validate_success(resp, 201)
        assert_transfer_request(request)
        assert request["status"] == "INTAKE", "client-supplied status ignored"
        assert request["consult_count"] == 0, "client-supplied consult_count ignored"
        assert request["intake_coordinator_id"] == "coord_9", (
            "intake_coordinator_id comes from the X-User-ID header, not the payload")


class TestListingPagination:
    def test_beds_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/beds_list_pagination_envelope
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Page Fac", region="R1"), ADMIN))
        for i in range(1, 4):
            unit = "C-1" if i < 3 else "C-2"
            get_success_data(api.create_bed(
                facility["id"],
                create_bed_payload(unit=unit, label=f"B{i}", service="CARDIAC",
                                   max_acuity="ACUITY_1_CRITICAL",
                                   isolation_capability="NONE"),
                ADMIN))
        resp = api.list_beds(facility["id"], COORD,
                             params={"limit": 2, "offset": 2})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, "offset 2 of 3 beds yields exactly one row"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 2
        assert meta["offset"] == 2


class TestResponseEnvelope:
    def test_success_and_error_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format" with meta.api_request_id,
        meta.api_request_timestamp, response_type, and data.
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and data.error_id
        plus data.message.

        Design: Corner/endpoints/success_and_error_envelope_shape
        """
        resp = api.create_facility(
            create_facility_payload(name="Env Fac", region="R1"), ADMIN)
        facility = validate_success(resp, 201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == facility["id"]

        err_resp = api.get_facility(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", COORD)
        err = validate_error(err_resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_FACILITY_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"]
