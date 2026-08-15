"""Authentication, role authorization, segregation of duties, and validation
priority ordering."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_rectification_ok,
    build_user_headers,
    claim_rectified_ok,
    create_plan,
    create_vessel,
    create_voyage_payload,
    find_report,
    get_deficiency,
    get_success_data,
    get_voyage_version,
    list_inspections,
    make_flag_surveyor_headers,
    make_psc_officer_headers,
    make_vessel_master_headers,
    post_ballast_event,
    record_inspection,
    rectify_deficiency_to_rectified,
    set_clock,
    setup_psc_exceeded_deficiency,
    setup_voyage_in_progress,
    submit_plan,
    submit_report_ok,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api, shore_officer_headers):
        """PRD section 2.1: "Every request must carry two headers: `X-User-ID`
        identifying the acting principal, and `X-User-Role` naming the principal's
        role. A request missing either header, or carrying an unrecognized role, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_401
        """
        create_vessel(imo_number="9100056", vessel_name="MV Garganey", bwms_type="NONE",
                      gross_tonnage=8000, keel_laid_date="2016-01-01T00:00:00Z",
                      ballast_capacity_m3=4000)

        # An unrecognized role name is equivalent to missing authentication.
        resp = api.list_vessels(build_user_headers("anon-1", "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

        # Missing both headers outright.
        resp = api.list_vessels({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_vessel_master_cannot_approve_plan_returns_403(self, api, vessel_master_headers,
                                                           flag_surveyor_headers):
        """PRD section 4: "| POST | /vessels/{vessel_id}/plans/{plan_id}/approve | Approve a submitted plan, superseding any prior | FlagSurveyor |"
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/vessel_master_cannot_approve_plan_returns_403
        """
        vessel = create_vessel(imo_number="9100057", vessel_name="MV Hobbyist")
        plan = create_plan(vessel["id"], plan_revision=1)
        submit_plan(vessel["id"], plan["id"])

        resp = api.approve_plan(vessel["id"], plan["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        current = get_success_data(api.get_plan(vessel["id"], plan["id"], flag_surveyor_headers))
        assert current["status"] == "SUBMITTED", "denied approval must leave the plan SUBMITTED"

    def test_shore_officer_cannot_verify_deficiency_returns_403(self, api,
                                                                shore_officer_headers):
        """PRD section 4: "| POST | /vessels/{vessel_id}/deficiencies/{deficiency_id}/verify | PSC verifies rectification | PSCOfficer |"
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/shore_officer_cannot_verify_deficiency_returns_403
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100058", vessel_name="MV Inia", voyage_number="V9701"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-10"]
        )
        rectify_deficiency_to_rectified(vessel["id"], deficiency["id"],
                                        claimer_user_id="master-1")

        # A different X-User-ID than the claimer, so only the role gate can fire.
        resp = api.verify_deficiency(vessel["id"], deficiency["id"], shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_psc_officer_cannot_submit_report_returns_403(self, api, psc_officer_headers,
                                                          flag_surveyor_headers):
        """PRD section 4: "| POST | /vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/submit | Submit a DRAFT report | VesselMaster |"
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/psc_officer_cannot_submit_report_returns_403
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100059", vessel_name="MV Jacana", voyage_number="V9702",
            arrived_at="2026-08-10T00:00:00Z",
        )
        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")

        resp = api.submit_report(vessel["id"], voyage["id"], report["id"],
                                 {"payload_summary": {"note": "psc attempt"}},
                                 psc_officer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        current = [r for r in
                   get_success_data(api.list_reports(vessel["id"], voyage["id"],
                                                     flag_surveyor_headers))
                   if r["id"] == report["id"]][0]
        assert current["status"] == "DRAFT", "denied submission must leave the report DRAFT"

    def test_flag_surveyor_cannot_record_ballast_event_returns_403(self, api,
                                                                   flag_surveyor_headers):
        """PRD section 4: "| POST | /vessels/{vessel_id}/voyages/{voyage_id}/ballast-events | Record a ballast water event | VesselMaster |"
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/flag_surveyor_cannot_record_ballast_event_returns_403
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100060", vessel_name="MV Killdeer", voyage_number="V9703"
        )
        version = get_voyage_version(vessel["id"], voyage["id"])
        resp = api.create_ballast_event(
            vessel["id"], voyage["id"],
            {"event_kind": "UPTAKE", "occurred_at": "2026-07-28T06:00:00Z",
             "tank_id": "T1", "volume_m3": 100, "salinity_ppt": 32.0,
             "source_port_locode": "USNYC", "expected_voyage_version": version},
            flag_surveyor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_platform_admin_cannot_create_voyage_returns_403(self, api, platform_admin_headers):
        """PRD section 4: "| POST | /vessels/{vessel_id}/voyages | Create a voyage in PENDING | ShoreComplianceOfficer, VesselMaster |"
        PRD section 2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an
        opaque operator identifier not tied to any persisted entity; the platform
        administrator owns only the test-driving clock endpoint and otherwise shares
        read access."

        Design: Corner/rbac/platform_admin_cannot_create_voyage_returns_403
        """
        vessel = create_vessel(imo_number="9100061", vessel_name="MV Lorikeet",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        resp = api.create_voyage(
            vessel["id"],
            create_voyage_payload(voyage_number="V9704",
                                  crosses_captain_of_port_zones=False),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestSegregationOfDuties:
    def test_sod_deficiency_verify_same_user_returns_403(self, api):
        """PRD section 2.9: "The same `X-User-ID` may not both claim a deficiency
        rectified and verify that same deficiency."
        PRD section 2.9: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_deficiency_verify_same_user_returns_403
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100062", vessel_name="MV Moorhen", voyage_number="V9705"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-11"]
        )
        rectify_deficiency_to_rectified(vessel["id"], deficiency["id"],
                                        claimer_user_id="master-1")

        # PSCOfficer is a legal verifying role, but this is the claimer's X-User-ID.
        resp = api.verify_deficiency(vessel["id"], deficiency["id"],
                                     make_psc_officer_headers("master-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        current = get_deficiency(vessel["id"], deficiency["id"])
        assert current["rectification_status"] == "RECTIFIED"

    def test_sod_inspection_record_evaluate_same_user_returns_403(self, api):
        """PRD section 2.9: "The same `X-User-ID` may not both record a sampling
        inspection and evaluate that same inspection."
        PRD section 2.9: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_inspection_record_evaluate_same_user_returns_403
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100063", vessel_name="MV Nuthatch", voyage_number="V9706"
        )
        # FlagSurveyor may both record and evaluate by role; the SoD rule keys on
        # the X-User-ID instead.
        inspection = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=12.0,
            tss=10.0, findings=["BWMS-12"], recorder_user_id="fs-dual",
        )

        resp = api.evaluate_inspection(vessel["id"], voyage["id"], inspection["id"],
                                       make_flag_surveyor_headers("fs-dual"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        current = [i for i in list_inspections(vessel["id"], voyage["id"])
                   if i["id"] == inspection["id"]][0]
        assert current["status"] == "RECORDED", (
            "denied evaluation must leave the inspection RECORDED"
        )


class TestValidationPriorityOrdering:
    def _setup_rectified_deficiency(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000011", vessel_name="MV Kestrel", voyage_number="V6001"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-04"]
        )
        rectify_deficiency_to_rectified(vessel["id"], deficiency["id"],
                                        claimer_user_id="master-1")
        return vessel, deficiency

    def test_verify_with_wrong_role_and_same_user_yields_unauthorized(self, api):
        """PRD section 2.10: "When a request triggers multiple validation failures,
        they surface in a fixed priority order so the client sees the most fundamental
        problem first: authentication (401) before authorization (403), authorization
        before path resolution (404), path resolution before state-machine legality
        (409), state-machine legality before segregation-of-duties and vessel-frozen
        business-safety checks, and those before temporal, constraint, referential,
        and fiscal checks on the request payload."

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_segregation_of_duties
        """
        vessel, deficiency = self._setup_rectified_deficiency()
        # VesselMaster may never verify (authorization failure) AND master-1 is the
        # claimer (segregation-of-duties failure). Authorization is the earlier
        # priority family and wins.
        resp = api.verify_deficiency(vessel["id"], deficiency["id"],
                                     make_vessel_master_headers("master-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_unauthorized_verify_leaves_deficiency_rectified(self, api):
        """PRD section 2.10: "authentication (401) before authorization (403),
        authorization before path resolution (404), path resolution before
        state-machine legality (409)"
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_segregation_of_duties
        """
        vessel, deficiency = self._setup_rectified_deficiency()
        resp = api.verify_deficiency(vessel["id"], deficiency["id"],
                                     make_vessel_master_headers("master-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        current = get_deficiency(vessel["id"], deficiency["id"])
        assert current["rectification_status"] == "RECTIFIED", (
            "a request denied at the authorization gate must not mutate the deficiency"
        )


class TestExistenceBeforeState:
    def _setup_two_vessels_one_submitted_report(self):
        from test_helpers import (
            create_voyage, depart_voyage, setup_vessel_with_approved_plan,
        )

        vessel_a, plan_a = setup_vessel_with_approved_plan(
            imo_number="9000013", vessel_name="MV Merlin"
        )
        vessel_b = create_vessel(imo_number="9000014", vessel_name="MV Nighthawk")
        voyage_a = create_voyage(vessel_a["id"], voyage_number="V6003",
                                 arrived_at="2026-08-10T00:00:00Z")
        depart_voyage(vessel_a["id"], voyage_a["id"])
        report = find_report(vessel_a["id"], voyage_a["id"], "PRE_ARRIVAL")
        submit_report_ok(vessel_a["id"], voyage_a["id"], report["id"])
        return vessel_a, vessel_b, voyage_a, report

    def test_submit_report_under_wrong_vessel_returns_not_found(self, api,
                                                                vessel_master_headers):
        """PRD section 2.10: "authorization before path resolution (404), path
        resolution before state-machine legality (409)"
        PRD section 2.5: "Path parameters are validated left to right: each segment's
        identifier must resolve to an existing entity, and each child must belong to
        the ancestor named to its left. A failure at any segment is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_hierarchy_mismatch
        """
        vessel_a, vessel_b, voyage_a, report = (
            self._setup_two_vessels_one_submitted_report()
        )
        # The report is already SUBMITTED (a state violation if addressed correctly)
        # AND addressed under the wrong vessel (an existence failure). Existence wins.
        resp = api.submit_report(vessel_b["id"], voyage_a["id"], report["id"],
                                 {"payload_summary": {"note": "duplicate under wrong vessel"}},
                                 vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_wrong_vessel_submit_leaves_report_submitted(self, api, vessel_master_headers,
                                                         flag_surveyor_headers):
        """PRD section 2.5: "A failure at any segment is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."
        PRD section 2.10: "authorization before path resolution (404), path resolution
        before state-machine legality (409)"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_hierarchy_mismatch
        """
        vessel_a, vessel_b, voyage_a, report = (
            self._setup_two_vessels_one_submitted_report()
        )
        resp = api.submit_report(vessel_b["id"], voyage_a["id"], report["id"],
                                 {"payload_summary": {"note": "duplicate under wrong vessel"}},
                                 vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        current = [r for r in
                   get_success_data(api.list_reports(vessel_a["id"], voyage_a["id"],
                                                     flag_surveyor_headers))
                   if r["id"] == report["id"]][0]
        assert current["status"] == "SUBMITTED", (
            "a request denied at path resolution must not mutate the report"
        )
