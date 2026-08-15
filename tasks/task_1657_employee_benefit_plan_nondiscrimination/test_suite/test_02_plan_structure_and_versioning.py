"""Plan/version/year structure: parent chains, uniqueness, amendments (PRD §2.9, §3.1-§3.4)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_employer_payload,
    create_plan_payload,
    create_plan_version_payload,
    create_plan_year_payload,
    create_census_employee_payload,
    create_compensation_record_payload,
    create_contribution_payload,
    assert_plan_version,
    setup_employer_plan_version_year,
    create_employer,
    create_plan_for,
    create_adopted_version,
    create_plan_year_for,
    open_census,
    add_employee,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestParentChainAndUniqueness:
    def test_child_creation_requires_existing_parent_chain(self):
        """PRD §2.9: "Identifiers in a path are resolved left to right: the employer,
        then the plan beneath that employer, then the plan year beneath that plan, then
        the child beneath that plan year. If any identifier does not resolve, or a child
        exists but hangs off a different parent than the path claims, the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/child_creation_requires_existing_parent_chain
        """
        resp = api_client.create_plan(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            create_plan_payload(plan_name="Ghost"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_existence_checked_before_state(self):
        """PRD §2.8: "Authentication comes first (headers present, role declared), then
        authorization (the role may invoke this endpoint), then existence — every
        identifier in the path must resolve, left to right, through its parent chain."

        Design: Corner/validations/existence_checked_before_state
        """
        resp = api_client.file_plan_year("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_ein_across_employers_rejected(self):
        """PRD §3.1: "The `ein` is the nine-digit federal employer identification number
        — exactly nine digits — and must be unique across all employers; a duplicate is
        rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/validations/duplicate_ein_across_employers_rejected
        """
        api_client.create_employer(
            create_employer_payload(legal_name="Lima2 Corp", ein="500000002"), PLATFORM
        )
        resp = api_client.create_employer(
            create_employer_payload(
                legal_name="Lima2 Clone", ein="500000002", entity_type="LLC"
            ),
            PLATFORM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)

    def test_duplicate_ssn_scoped_to_plan_year(self):
        """PRD §3.4: "The `ssn` is nine digits and unique within the plan year —
        duplicates are rejected with `ERR_DUPLICATE`."

        Design: Corner/validations/duplicate_ssn_within_plan_year_rejected
        """
        employer = create_employer(legal_name="Kilo2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Kilo2 401k")
        py1 = create_plan_year_for(plan["id"], year_label=2026)
        py2 = create_plan_year_for(
            plan["id"], year_label=2027, year_start="2027-01-01", year_end="2027-12-31"
        )
        open_census(py1["id"])
        open_census(py2["id"])
        add_employee(py1["id"], ssn="500000001", full_name="Sam")

        dup = api_client.create_census_employee(
            py1["id"],
            create_census_employee_payload(ssn="500000001", full_name="Sam Dup"),
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE, expected_status=409)

        other_year = api_client.create_census_employee(
            py2["id"],
            create_census_employee_payload(ssn="500000001", full_name="Sam Other Year"),
            ADMIN,
        )
        validate_success(other_year, expected_status=201)


class TestEmployerArchiveAndPlanTermination:
    def test_archived_employer_blocks_plan_creation(self):
        """PRD §3.1: "Once an employer is `ARCHIVED`, creating a plan beneath it is
        rejected with `ERR_EMPLOYER_ARCHIVED` (HTTP 409)."

        Design: Corner/errors/error_employer_archived_blocks_plan_creation
        """
        employer = create_employer(legal_name="Charlie3a Corp")
        archived = validate_success(api_client.archive_employer(employer["id"], PLATFORM))
        assert archived["status"] == "ARCHIVED"

        resp = api_client.create_plan(
            employer["id"], create_plan_payload(plan_name="Late Plan"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYER_ARCHIVED, expected_status=409)

    def test_terminated_plan_blocks_child_creation(self):
        """PRD §3.2: "Creating a plan version or a plan year under a `TERMINATED` plan
        is rejected with `ERR_PLAN_TERMINATED` (HTTP 409)."
        PRD §3.9: "moving it to `TERMINATED`, cascading the parent plan's `status` to
        `TERMINATED` (which, per §3.2, thereafter blocks new versions and years under it
        with `ERR_PLAN_TERMINATED`)"

        Design: Corner/errors/error_plan_terminated_blocks_child_creation
        """
        employer = create_employer(legal_name="Alpha3 Corp")
        plan = create_plan_for(employer["id"], plan_name="Alpha3 401k")
        py = create_plan_year_for(plan["id"])
        validate_success(api_client.terminate_plan_year(py["id"], ADMIN))

        plan_data = validate_success(api_client.get_plan(plan["id"], AUDITOR))
        assert plan_data["status"] == "TERMINATED"

        v_resp = api_client.create_plan_version(
            plan["id"], create_plan_version_payload(effective_start="2027-01-01",
                                                    effective_end="2027-12-31"), ADMIN
        )
        validate_error(v_resp, ApiErrorId.ERR_PLAN_TERMINATED, expected_status=409)
        y_resp = api_client.create_plan_year(
            plan["id"], create_plan_year_payload(year_label=2027), ADMIN
        )
        validate_error(y_resp, ApiErrorId.ERR_PLAN_TERMINATED, expected_status=409)


class TestPlanVersionRules:
    def test_sh_match_formula_required_for_match_designs(self):
        """PRD §3.2: "Whenever `safe_harbor_design` is `BASIC_MATCH` or
        `ENHANCED_MATCH`, the request must also carry `sh_match_formula`, a descriptor
        such as "100% of first 3% + 50% of next 2%"; the formula is required for exactly
        those two designs and forbidden to be absent only for them, so a missing formula
        under a match design — or any missing required field, undeclared enum member,
        ill-typed value, malformed date, or out-of-range percentage — is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/conditional_field_sh_match_formula_required
        """
        employer = create_employer(legal_name="Romeo2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Romeo2 401k")
        resp = api_client.create_plan_version(
            plan["id"],
            {
                "effective_start": "2026-01-01",
                "effective_end": "2026-12-31",
                "comp_definition": "W2",
                "safe_harbor_design": "BASIC_MATCH",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_amendment_without_target_rejected(self):
        """PRD §3.2: "An amendment with nothing to amend (no overlapping `ADOPTED`
        version exists), or any adoption that would leave two `ADOPTED` intervals
        overlapping after truncation, is rejected with `ERR_VERSION_INTERVAL_CONFLICT`
        (HTTP 409)."

        Design: Corner/validations/amendment_without_target_rejected
        """
        employer = create_employer(legal_name="Sierra2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Sierra2 401k")
        version = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2026-06-01",
                    comp_definition="SEC415",
                    is_amendment=True,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api_client.adopt_plan_version(version["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VERSION_INTERVAL_CONFLICT, expected_status=409)

    def test_amendment_adoption_truncates_prior_version(self):
        """PRD §3.2: "when an amendment (one with `is_amendment` true) overlaps an
        existing `ADOPTED` version, adoption truncates the prior version's
        `effective_end` to the amendment's `effective_start`, and if that truncation
        empties the prior interval — the prior start falls at or after the amendment's
        start — the prior version cascades `ADOPTED` → `SUPERSEDED`."

        Design: Corner/endpoints/amendment_adoption_truncates_prior_version
        """
        employer = create_employer(legal_name="Yankee2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Yankee2 401k")
        v1 = create_adopted_version(plan["id"])
        v2 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2026-07-01",
                    comp_definition="SEC415",
                    is_amendment=True,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        adopted = validate_success(api_client.adopt_plan_version(v2["id"], ADMIN))
        assert adopted["status"] == "ADOPTED"

        v1_after = validate_success(api_client.get_plan_version(v1["id"], AUDITOR))
        assert v1_after["effective_end"] == "2026-07-01", (
            f"prior version effective_end must truncate to the amendment start, "
            f"got {v1_after['effective_end']}"
        )
        assert v1_after["status"] == "ADOPTED"

    def test_amendment_fully_covering_supersedes_prior(self):
        """PRD §3.2: "if that truncation empties the prior interval — the prior start
        falls at or after the amendment's start — the prior version cascades `ADOPTED` →
        `SUPERSEDED`."

        Design: Corner/endpoints/amendment_fully_covering_supersedes_prior
        """
        employer = create_employer(legal_name="Zulu2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Zulu2 401k")
        v1 = create_adopted_version(plan["id"])
        v2 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    comp_definition="SEC3401",
                    safe_harbor_design="QNEC_3PCT",
                    is_amendment=True,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        adopted = validate_success(api_client.adopt_plan_version(v2["id"], ADMIN))
        assert adopted["status"] == "ADOPTED"
        assert adopted["safe_harbor_design"] == "QNEC_3PCT"

        v1_after = validate_success(api_client.get_plan_version(v1["id"], AUDITOR))
        assert v1_after["status"] == "SUPERSEDED"

    def test_half_open_interval_adjacency_allowed_overlap_rejected(self):
        """PRD §3.2: "A plan version carries `effective_start` and `effective_end` dates
        bounding the half-open interval over which its provisions govern — the start is
        inclusive, the end exclusive, and a null `effective_end` marks the current
        version"
        PRD §3.2: "Two `ADOPTED` versions of the same plan may never overlap"

        Design: Difficulty/resource_temporal_overlap/plan_version_half_open_interval_overlap
        """
        employer = create_employer(legal_name="Oscar Corp")
        plan = create_plan_for(employer["id"], plan_name="Oscar 401k")
        v1 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2026-01-01", effective_end="2027-01-01"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(api_client.adopt_plan_version(v1["id"], ADMIN))

        # Adjacent: starts exactly at V1's exclusive end -> allowed
        v2 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2027-01-01", effective_end="2027-12-31",
                    comp_definition="SEC415",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        adopted_v2 = validate_success(api_client.adopt_plan_version(v2["id"], ADMIN))
        assert adopted_v2["status"] == "ADOPTED"

        # Interior overlap with V1 -> rejected
        v3 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2026-06-01", effective_end="2027-05-31",
                    comp_definition="SEC3401",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api_client.adopt_plan_version(v3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VERSION_INTERVAL_CONFLICT, expected_status=409)

    def test_adjacent_touching_endpoint_is_not_overlap(self):
        """PRD §3.2: "bounding the half-open interval over which its provisions govern —
        the start is inclusive, the end exclusive"

        Design: Difficulty/resource_temporal_overlap/plan_version_half_open_interval_overlap
        """
        employer = create_employer(legal_name="Oscar Adjacent Corp")
        plan = create_plan_for(employer["id"], plan_name="Oscar Adjacent 401k")
        v1 = create_adopted_version(
            plan["id"], effective_start="2026-01-01", effective_end="2027-01-01"
        )
        v2 = validate_success(
            api_client.create_plan_version(
                plan["id"],
                create_plan_version_payload(
                    effective_start="2027-01-01", effective_end="2027-12-31"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        adopted = validate_success(api_client.adopt_plan_version(v2["id"], ADMIN))
        assert_plan_version(adopted)
        assert adopted["status"] == "ADOPTED"
        v1_after = validate_success(api_client.get_plan_version(v1["id"], AUDITOR))
        assert v1_after["status"] == "ADOPTED"
        assert v1_after["effective_end"] == "2027-01-01"


class TestFkReverseReachability:
    def test_fk_reverse_reachability_lists(self):
        """PRD §2.9: "Paths in this API are hierarchical — an employer contains plans, a
        plan contains versions and plan years, a plan year contains census employees,
        test runs, corrections, and elections, and a census employee contains
        compensation records and contributions."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        employer = create_employer(legal_name="Xray2 Corp")
        plan = create_plan_for(employer["id"], plan_name="Xray2 401k")
        version = validate_success(
            api_client.create_plan_version(plan["id"], create_plan_version_payload(), ADMIN),
            expected_status=201,
        )
        py = create_plan_year_for(plan["id"])
        open_census(py["id"])
        emp = add_employee(py["id"], ssn="600000501", full_name="Xena",
                           date_of_birth="1990-01-01", date_of_hire="2021-01-01")
        comp = validate_success(
            api_client.create_compensation_record(
                emp["id"], create_compensation_record_payload(amount_cents=9000000), ADMIN
            ),
            expected_status=201,
        )
        contrib = validate_success(
            api_client.create_contribution(
                emp["id"], create_contribution_payload(amount_cents=450000), ADMIN
            ),
            expected_status=201,
        )

        def _ids(resp):
            data, _meta = validate_paginated(resp)
            return [row["id"] for row in data]

        assert plan["id"] in _ids(api_client.list_plans_of_employer(employer["id"], AUDITOR))
        assert version["id"] in _ids(api_client.list_plan_versions(plan["id"], AUDITOR))
        assert py["id"] in _ids(api_client.list_plan_years_of_plan(plan["id"], AUDITOR))
        assert emp["id"] in _ids(api_client.list_census_employees(py["id"], AUDITOR))
        assert comp["id"] in _ids(api_client.list_compensation_records(emp["id"], AUDITOR))
        assert contrib["id"] in _ids(api_client.list_contributions(emp["id"], AUDITOR))
