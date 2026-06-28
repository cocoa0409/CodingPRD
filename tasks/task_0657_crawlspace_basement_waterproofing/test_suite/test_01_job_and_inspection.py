"""Job creation/validation and inspection severity assessment.

Covers Corner queue: entities (job creation defaults, required fields, enum,
not-found, FK-not-found, homeowner immutability), calculations (severity variants),
and state_machines (inspection invalid transition, supersede side effect).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_job, assert_homeowner, assert_inspection,
    create_homeowner_payload, create_job_payload, create_inspection_payload,
    create_homeowner, create_job, create_finalized_inspection,
    TEST_USERS, MISSING_UUID,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]


class TestJobCreation:
    def test_create_job_returns_201_with_system_defaults(self, api):
        """PRD §3.1: "A freshly created Job opens in lifecycle status `LEAD` with
        financing status `NONE`, an `assessment_severity` of `NONE`, and an
        `open_claim_count` of 0."
        PRD §2.4: "`version`, an integer that starts at 1 and increments by 1 on
        every mutation."

        Design: Corner/entities/create_job_returns_201_with_system_defaults
        """
        ho = create_homeowner()
        res = api.create_job(
            create_job_payload(ho["id"], property_address="100 St",
                               structure_type="CRAWLSPACE", footprint_sqft=900), EST)
        job = validate_success(res, 201)
        assert_job(job)
        assert job["lifecycle_status"] == "LEAD"
        assert job["financing_status"] == "NONE"
        assert job["assessment_severity"] == "NONE"
        assert job["open_claim_count"] == 0
        assert job["version"] == 1

    def test_create_job_missing_footprint_returns_invalid_request(self, api):
        """PRD §2.7: "the request's own shape — required fields present and well-typed,
        enum values legal — is checked, yielding `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "Opening a Job records the `homeowner_id` of the owner, the
        `property_address`, the `structure_type` ... and the `footprint_sqft`, the
        conditioned floor area used in pricing, which must be at least 1."

        Design: Corner/entities/create_job_missing_required_field_returns_invalid_request
        """
        ho = create_homeowner()
        res = api.create_job(
            {"homeowner_id": ho["id"], "property_address": "101 St",
             "structure_type": "BASEMENT"}, EST)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_create_job_invalid_structure_type_returns_invalid_request(self, api):
        """PRD §2.7: "the request's own shape — required fields present and well-typed,
        enum values legal — is checked, yielding `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "the `structure_type` (one of `CRAWLSPACE`, `BASEMENT`, or `COMBINED`)".

        Design: Corner/entities/create_job_invalid_enum_structure_type_returns_invalid_request
        """
        ho = create_homeowner()
        res = api.create_job(
            create_job_payload(ho["id"], property_address="102 St",
                               structure_type="GARAGE", footprint_sqft=700), EST)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_get_nonexistent_job_returns_not_found(self, api):
        """PRD §2.6: "The system resolves these identifiers left to right and rejects
        the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does
        not correspond to an existing resource."

        Design: Corner/entities/get_job_nonexistent_id_returns_not_found
        """
        res = api.get_job(MISSING_UUID, EST)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_create_job_unknown_homeowner_fk_returns_fk_not_found(self, api):
        """PRD §2.6: "any foreign-key field supplied in a request body — such as a
        `homeowner_id` ... that names another resource — must reference an existing
        resource of the correct type; a dangling body reference is rejected with
        `ERR_FK_NOT_FOUND` (HTTP 422)."

        Design: Corner/entities/create_job_unknown_homeowner_fk_returns_fk_not_found
        """
        res = api.create_job(
            create_job_payload(MISSING_UUID, property_address="103 St",
                               structure_type="CRAWLSPACE", footprint_sqft=700), EST)
        validate_error(res, "ERR_FK_NOT_FOUND", expected_status=422)


class TestHomeownerImmutability:
    def test_homeowner_read_has_no_version_field(self, api):
        """PRD §2.4: "The `Homeowner` record is the sole exception: it carries only `id`
        and `created_at`. A `Homeowner` has no `updated_at` and no `version` field at all."

        Design: Corner/entities/homeowner_immutable_no_version_field
        """
        ho = create_homeowner(credit_band="NEAR_PRIME")
        res = api.get_homeowner(ho["id"], EST)
        data = validate_success(res, 200)
        assert_homeowner(data)
        assert data["credit_band"] == "NEAR_PRIME"
        assert "version" not in data, "Homeowner must not carry a version field"
        assert "updated_at" not in data, "Homeowner must not carry an updated_at field"


class TestSeverityAssessment:
    def test_severity_pure_threshold_low_no_standing_water(self, api):
        """PRD §3.2: "if `moisture_pct` is at least 60, the score gains 1 point" and
        "the `structural_findings_count`, but capped at a maximum of 4 counted findings,
        is multiplied by 2 points each and added to the score."
        PRD §3.2: "otherwise a score of at least 1 maps to `LOW`".
        PRD §3.2: "if standing water was observed and there was at least one structural
        finding and the base mapping landed at `LOW` or `NONE`, the severity is forced
        up to `MODERATE`. In every other case — no standing water ... the override does
        nothing and the base mapping stands."

        Design: Corner/calculations/severity_pure_threshold_no_standing_water
        """
        # moisture 50 (<60, +0) + 1 structural (1*2=2) => score 2 => LOW;
        # standing_water false so no override.
        ho = create_homeowner()
        job = create_job(ho["id"], footprint_sqft=700, structure_type="CRAWLSPACE")
        draft = get_success_data(api.create_inspection(
            job["id"],
            create_inspection_payload(moisture_pct=50, structural_findings_count=1,
                                      standing_water=False), INS))
        final = validate_success(api.finalize_inspection(job["id"], draft["id"], INS), 200)
        assert_inspection(final)
        assert final["severity"] == "LOW"

    def test_severity_severe_threshold_exact_boundary(self, api):
        """PRD §3.2: "if `moisture_pct` is at least 80, the score gains 3 points" and
        "the `structural_findings_count`, but capped at a maximum of 4 counted findings,
        is multiplied by 2 points each and added to the score."
        PRD §3.2: "a score of at least 7 maps to `SEVERE`".

        Design: Corner/calculations/severity_severe_threshold_exact
        """
        # moisture 80 (+3) + 2 structural (min(2,4)*2=4) => score 7 == SEVERE_THRESHOLD => SEVERE.
        ho = create_homeowner()
        job = create_job(ho["id"], footprint_sqft=900, structure_type="COMBINED")
        draft = get_success_data(api.create_inspection(
            job["id"],
            create_inspection_payload(moisture_pct=80, structural_findings_count=2), INS))
        final = validate_success(api.finalize_inspection(job["id"], draft["id"], INS), 200)
        assert final["severity"] == "SEVERE"


class TestInspectionStateMachine:
    def test_finalize_already_finalized_inspection_returns_invalid_state(self, api):
        """PRD §3.2: "Finalizing an inspection — permitted only while it is in `DRAFT`,
        otherwise rejected with `ERR_INVALID_STATE` — moves it to `FINALIZED` and computes
        its `severity`."

        Design: Corner/state_machines/finalize_already_finalized_inspection_returns_invalid_state
        """
        ho = create_homeowner()
        job = create_job(ho["id"], footprint_sqft=700, structure_type="CRAWLSPACE")
        draft = get_success_data(api.create_inspection(
            job["id"], create_inspection_payload(moisture_pct=50,
                                                 structural_findings_count=0), INS))
        validate_success(api.finalize_inspection(job["id"], draft["id"], INS), 200)
        res = api.finalize_inspection(job["id"], draft["id"], INS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_new_inspection_supersedes_prior_finalized(self, api):
        """PRD §3.2: "On every finalize, if a prior `FINALIZED` inspection already exists
        on the same Job, that earlier inspection is moved to `SUPERSEDED` (with its own
        `version` incremented), and the Job's `assessment_severity` is set to the severity
        just computed."

        Design: Corner/state_machines/new_inspection_supersedes_prior_finalized
        """
        ho = create_homeowner()
        job = create_job(ho["id"], footprint_sqft=1000, structure_type="COMBINED")
        draft1 = get_success_data(api.create_inspection(
            job["id"], create_inspection_payload(moisture_pct=40,
                                                 structural_findings_count=0), INS))
        insp1 = validate_success(api.finalize_inspection(job["id"], draft1["id"], INS), 200)
        # second inspection: moisture 85 (+3) + 3 structural (min(3,4)*2=6) => score 9 => SEVERE
        draft2 = get_success_data(api.create_inspection(
            job["id"], create_inspection_payload(moisture_pct=85,
                                                 structural_findings_count=3), INS))
        insp2 = validate_success(api.finalize_inspection(job["id"], draft2["id"], INS), 200)

        assert insp2["severity"] == "SEVERE"
        prior = validate_success(api.get_inspection(insp1["id"], INS), 200)
        assert prior["status"] == "SUPERSEDED"
        job_after = validate_success(api.get_job(job["id"], EST), 200)
        assert job_after["assessment_severity"] == "SEVERE"
