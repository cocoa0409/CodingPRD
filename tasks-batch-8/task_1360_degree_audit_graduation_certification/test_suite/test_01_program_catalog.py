"""Program catalog versioning: creation validation, half-open catalog ranges,
closed honors-policy ranges, declaration bounds, retirement, and withdrawn
declarations (PRD §2.8, §3.1, §3.3).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_honors_policy_payload,
    create_program_payload,
    create_student_program_payload,
    declare,
    get_student_program,
    make_program,
    make_student,
    run_audit,
    validate_error,
    validate_success,
)


class TestProgramCreationValidation:
    def test_create_program_missing_min_gpa_rejected(self, api, registrar_headers):
        """PRD §3.1: "Each program version is created with a `program_code`
        shared across all versions of the same program (for example, BS-CS), a
        display `name`, a `degree_type` of `ASSOCIATE`, `BACHELOR`, or `MASTER`,
        the degree-wide minimums `min_total_credits` and `min_gpa`, and the
        half-open catalog range `catalog_year_start` / `catalog_year_end`
        described in §2.8."
        PRD §2.7: "a structurally malformed payload — a missing required field,
        an invalid enum member, or a payload that mismatches the requested kind,
        such as a what-if audit without its target or a waiver without its
        amount — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/program_create_missing_required_field
        """
        payload = create_program_payload(program_code="BS-MIS")
        del payload["min_gpa"]
        res = api.create_program(payload, registrar_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestCatalogRangeOverlap:
    def test_adjacent_catalog_ranges_accepted(self, api, registrar_headers):
        """PRD §2.8: "Two versions sharing the same `program_code` may not claim
        overlapping ranges; adjacency is explicitly allowed, so one version's
        `catalog_year_end` may equal the next version's `catalog_year_start`
        without conflict."

        Design: Difficulty/resource_temporal_overlap/program_catalog_halfopen_overlap
        """
        v1 = validate_success(api.create_program(
            create_program_payload(
                program_code="BS-OV", name="V1",
                catalog_year_start=2024, catalog_year_end=2027),
            registrar_headers), 201)
        assert v1["status"] == "ACTIVE"

        # Adjacency at 2027 (end == start) is not an overlap under half-open semantics.
        v2 = validate_success(api.create_program(
            create_program_payload(
                program_code="BS-OV", name="V2",
                catalog_year_start=2027, catalog_year_end=2030),
            registrar_headers), 201)
        assert v2["id"] != v1["id"]

    def test_overlapping_catalog_range_rejected(self, api, registrar_headers):
        """PRD §2.8: "Two versions sharing the same `program_code` may not claim
        overlapping ranges; adjacency is explicitly allowed, so one version's
        `catalog_year_end` may equal the next version's `catalog_year_start`
        without conflict. An overlapping claim is rejected with
        `ERR_CATALOG_RANGE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/program_catalog_halfopen_overlap
        """
        validate_success(api.create_program(
            create_program_payload(
                program_code="BS-OV", name="V1",
                catalog_year_start=2024, catalog_year_end=2027),
            registrar_headers), 201)
        validate_success(api.create_program(
            create_program_payload(
                program_code="BS-OV", name="V2",
                catalog_year_start=2027, catalog_year_end=2030),
            registrar_headers), 201)

        # [2026,2029) overlaps both existing versions in their interiors.
        res = api.create_program(
            create_program_payload(
                program_code="BS-OV", name="V3",
                catalog_year_start=2026, catalog_year_end=2029),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_CATALOG_RANGE_OVERLAP.value, expected_status=409)


class TestHonorsPolicyRangeOverlap:
    def test_year_adjacent_policies_accepted(self, api, registrar_headers):
        """PRD §2.8: "A policy covers the **closed, inclusive** range from
        `effective_first_year` through `effective_last_year`", and adjacent but
        disjoint year ranges share no year, so they do not collide.

        Design: Difficulty/resource_temporal_overlap/honors_policy_closed_range_overlap
        """
        program = make_program(
            program_code="BS-POL", catalog_year_start=2024, catalog_year_end=2030)
        p1 = validate_success(api.create_honors_policy(
            program["id"],
            create_honors_policy_payload(
                honors_gpa_basis="INSTITUTIONAL",
                effective_first_year=2024, effective_last_year=2026,
                residency_min_credits=10),
            registrar_headers), 201)
        p2 = validate_success(api.create_honors_policy(
            program["id"],
            create_honors_policy_payload(
                honors_gpa_basis="CUMULATIVE",
                effective_first_year=2027, effective_last_year=2030,
                residency_min_credits=10),
            registrar_headers), 201)
        assert p1["id"] != p2["id"]

    def test_shared_boundary_year_rejected(self, api, registrar_headers):
        """PRD §2.8: "Two policies of the same program may not overlap, and
        because the interval is closed, a shared boundary year *is* an overlap:
        a policy ending in 2024 collides with one beginning in 2024. A colliding
        policy is rejected with `ERR_POLICY_RANGE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/honors_policy_closed_range_overlap
        """
        program = make_program(
            program_code="BS-POL", catalog_year_start=2024, catalog_year_end=2030)
        validate_success(api.create_honors_policy(
            program["id"],
            create_honors_policy_payload(
                effective_first_year=2024, effective_last_year=2026,
                residency_min_credits=10),
            registrar_headers), 201)
        validate_success(api.create_honors_policy(
            program["id"],
            create_honors_policy_payload(
                effective_first_year=2027, effective_last_year=2030,
                residency_min_credits=10),
            registrar_headers), 201)

        # [2026,2028] shares year 2026 with the first policy and 2027/2028 with the second.
        res = api.create_honors_policy(
            program["id"],
            create_honors_policy_payload(
                cum_threshold=3.4, magna_threshold=3.7, summa_threshold=3.85,
                effective_first_year=2026, effective_last_year=2028,
                residency_min_credits=10),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_POLICY_RANGE_OVERLAP.value, expected_status=409)


class TestDeclarationCatalogYearBounds:
    def test_catalog_year_half_open_bounds(self, api, registrar_headers):
        """PRD §3.3: "And the `catalog_year` must fall within the version's
        half-open range — at least `catalog_year_start` and strictly less than
        `catalog_year_end` — or the declaration is rejected with
        `ERR_CATALOG_YEAR_OUT_OF_RANGE`."

        Design: Corner/entities/catalog_year_bounds_checked_on_declare
        """
        program = make_program(
            program_code="BS-BND", catalog_year_start=2024, catalog_year_end=2028)
        s1 = make_student(student_number="S-B1", legal_name="B One")
        s2 = make_student(student_number="S-B2", legal_name="B Two")

        # Lower bound is inclusive: catalog_year == catalog_year_start is accepted.
        sp = validate_success(api.declare_program(
            s1["id"], create_student_program_payload(program["id"], catalog_year=2024),
            registrar_headers), 201)
        assert sp["status"] == "ACTIVE"

        # Upper bound is exclusive: catalog_year == catalog_year_end is rejected.
        res = api.declare_program(
            s2["id"], create_student_program_payload(program["id"], catalog_year=2028),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_CATALOG_YEAR_OUT_OF_RANGE.value, expected_status=422)


class TestRetiredProgramGuards:
    def test_retire_once_then_state_and_referential_errors(self, api, registrar_headers):
        """PRD §3.1: "A `RegistrarStaff` operator retires a program version,
        moving it from `ACTIVE` to `RETIRED`; attempting the transition on a
        version that is not `ACTIVE` is rejected with `ERR_PROGRAM_INVALID_STATE`.
        Retirement closes the door only to new commitments: existing declarations
        under the retired version remain fully auditable to completion, while new
        declarations — and what-if analyses that name the retired version as
        their target — are refused with `ERR_PROGRAM_RETIRED`."

        Design: Corner/state_machines/retired_program_guards
        """
        program = make_program(program_code="BS-RT")
        student = make_student(student_number="S-RT", legal_name="Ree Tyre")

        retired = validate_success(api.retire_program(program["id"], registrar_headers), 200)
        assert retired["status"] == "RETIRED"

        res = api.retire_program(program["id"], registrar_headers)
        validate_error(res, ApiErrorId.ERR_PROGRAM_INVALID_STATE.value, expected_status=409)

        res = api.declare_program(
            student["id"],
            create_student_program_payload(program["id"], catalog_year=2024),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_PROGRAM_RETIRED.value, expected_status=409)


class TestWithdrawnDeclarationGuards:
    def test_audit_on_withdrawn_declaration_rejected(self, api, registrar_headers):
        """PRD §3.3: "Once a declaration is `WITHDRAWN` or `COMPLETED` it is
        closed to new work: running an audit against it, filing an exception on
        it, creating a graduation application for it, or attempting to withdraw
        it again are all rejected with `ERR_STUDENT_PROGRAM_NOT_ACTIVE`."

        Design: Corner/state_machines/withdrawn_student_program_blocks_audit
        """
        program = make_program(program_code="BS-WD")
        student = make_student(student_number="S-WD", legal_name="Wade Drew")
        sp = declare(student["id"], program["id"], catalog_year=2024)

        withdrawn = validate_success(
            api.withdraw_student_program(sp["id"], registrar_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.create_audit(
            sp["id"],
            {"audit_kind": "STANDARD",
             "expected_student_program_version": withdrawn["version"]},
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_STUDENT_PROGRAM_NOT_ACTIVE.value, expected_status=409)
        after = get_student_program(sp["id"])
        assert after["status"] == "WITHDRAWN"
