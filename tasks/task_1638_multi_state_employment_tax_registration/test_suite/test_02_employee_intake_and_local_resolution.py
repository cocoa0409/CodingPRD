"""Employee intake side effects and local jurisdiction resolution."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    create_employee,
    create_employee_payload,
    create_local_agency,
    create_work_location,
    get_success_data,
    override_local_assignment_payload,
    setup_employee_at_location,
    validate_error,
    validate_success,
)


class TestEmployeeIntake:
    def test_employee_creation_starts_active(self, api):
        """PRD §3.2: "The employee starts `ACTIVE`."
        PRD §3.2: "Creation automatically runs local jurisdiction resolution and
        creates the employee's initial LocalAssignment with `resolution_source`
        `AUTO_GEOCODE`, covering from `hire_date`."

        Design: Corner/entities/employee_creation_auto_creates_initial_assignment
        """
        location = create_work_location("OR")
        res = api.create_employee(
            create_employee_payload(location["id"], employee_ref="E-2001",
                                    full_name="AC One"),
            ANALYST,
        )
        employee = validate_success(res, 201)
        assert employee["status"] == "ACTIVE"

    def test_employee_creation_auto_creates_initial_assignment(self, api):
        """PRD §3.2: "Creation automatically runs local jurisdiction resolution and
        creates the employee's initial LocalAssignment with `resolution_source`
        `AUTO_GEOCODE`, covering from `hire_date`."
        PRD §3.2: "An empty candidate set yields a null agency — a valid outcome
        meaning no local tax applies"

        Design: Corner/entities/employee_creation_auto_creates_initial_assignment
        """
        location = create_work_location("OR")
        employee = create_employee(location["id"], employee_ref="E-2001",
                                   full_name="AC One", resident_state_code="OR",
                                   annual_wage_cents=3_000_000)
        assignments = validate_success(
            api.list_local_assignments(ANALYST, params={"employee_id": employee["id"]})
        )
        assert len(assignments) == 1, (
            f"expected exactly one initial assignment, got {len(assignments)}"
        )
        assignment = assignments[0]
        assert assignment["resolution_source"] == "AUTO_GEOCODE"
        assert assignment["effective_from"] == "2026-08-01T00:00:00Z"
        assert assignment["status"] == "CURRENT"
        assert assignment["work_location_id"] == location["id"]
        assert assignment["resident_agency_id"] is None
        assert assignment["work_agency_id"] is None

    def test_employee_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.2: "The payload carries an external `employee_ref` (unique across
        employees), `full_name`, the `resident_state_code`, an optional
        `resident_locality_code` (an uppercase locality token matching agency
        `locality_code` values), the `hire_date` (an ISO date at midnight UTC — day
        attribution starts here), `annual_wage_cents` (the annualized wage in cents,
        which must be greater than zero), and `current_work_location_id`."
        PRD §2.9: "Malformed bodies, invalid enum values, non-positive amounts, missing
        required fields, a notice with no link, an inactive target work location, and a
        certificate-form mismatch fall through to `ERR_INVALID_REQUEST` (HTTP 400), the
        catch-all rejection."

        Design: Corner/entities/employee_missing_required_field_returns_invalid_request
        """
        location = create_work_location("OR")
        payload = create_employee_payload(location["id"], employee_ref="E-2002",
                                          full_name="AC Two")
        payload.pop("annual_wage_cents")
        res = api.create_employee(payload, ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestLocalJurisdictionResolution:
    def _setup_philly_candidates(self):
        city = create_local_agency(
            state_code="PA", locality_code="PHILADELPHIA",
            agency_name="Philly Wage Tax", resident_rate_bp=375,
            nonresident_rate_bp=344, precedence_rank=10,
        )
        postal = create_local_agency(
            state_code="PA", locality_code="19103",
            agency_name="Philly 19103 District", resident_rate_bp=380,
            nonresident_rate_bp=340, precedence_rank=10,
        )
        statewide = create_local_agency(
            state_code="PA", locality_code="PA-ALL",
            agency_name="PA Statewide Local", resident_rate_bp=100,
            nonresident_rate_bp=100, precedence_rank=50,
        )
        location = create_work_location("PA")
        return city, postal, statewide, location

    def test_local_resolution_postal_specificity_wins_rank_tie(self, api):
        """PRD §3.2: "Work-side candidates are active `LOCAL` agencies of the work
        location's state whose `locality_code` matches any of three tokens: the
        location's `postal_code` (a postal match, specificity 0), the uppercased
        location `city` (a city match, specificity 1), or the statewide token
        (specificity 2)."
        PRD §3.2: "On both sides, candidates rank by ascending `precedence_rank`, then
        ascending specificity, then ascending `created_at`; the first row wins and is
        recorded as `work_agency_id` or `resident_agency_id` respectively."

        Design: Corner/calculations/local_resolution_specificity_breaks_rank_tie
        """
        city, postal, statewide, location = self._setup_philly_candidates()
        employee = create_employee(
            location["id"], employee_ref="E-3004", full_name="AM One",
            resident_state_code="NJ", annual_wage_cents=3_000_000,
        )
        assignments = validate_success(
            api.list_local_assignments(ANALYST, params={"employee_id": employee["id"]})
        )
        assert len(assignments) == 1
        assert assignments[0]["work_agency_id"] == postal["id"], (
            "rank tie 10 == 10 broken by postal specificity 0 over city specificity 1"
        )

    def test_local_resolution_empty_resident_side_yields_null(self, api):
        """PRD §3.2: "An empty candidate set yields a null agency — a valid outcome
        meaning no local tax applies — and the human-readable `precedence_trace`
        records the ranking, noting `NONE_FOUND` for a side with no candidate."

        Design: Corner/calculations/local_resolution_specificity_breaks_rank_tie
        """
        city, postal, statewide, location = self._setup_philly_candidates()
        employee = create_employee(
            location["id"], employee_ref="E-3004", full_name="AM One",
            resident_state_code="NJ", annual_wage_cents=3_000_000,
        )
        assignments = validate_success(
            api.list_local_assignments(ANALYST, params={"employee_id": employee["id"]})
        )
        assert len(assignments) == 1
        assert assignments[0]["resident_agency_id"] is None, (
            "no NJ LOCAL agency exists, so the resident side candidate set is empty"
        )


class TestAssignmentOverrideOcc:
    def test_occ_assignment_override_stale_employee(self, api, tax_director_headers):
        """PRD §2.8: "A manual LocalAssignment override
        (`POST /etax/local-assignments/override`) requires `expected_employee_version`
        matching the Employee's current `version`, since an override legitimately
        truncates the employee's current assignment segment."
        PRD §2.8: "if that value does not match the parent entity's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_assignment_override_stale_employee
        """
        scenario = setup_employee_at_location(work_state="OR", resident_state="OR",
                                              employee_ref="E-7002")
        employee = scenario["employee"]
        location = scenario["location"]
        first = api.override_local_assignment(
            override_local_assignment_payload(
                employee["id"], location["id"], employee["version"],
                effective_from="2026-08-15T00:00:00Z", override_reason="Audit correction",
            ),
            tax_director_headers,
        )
        override_one = validate_success(first, 201)
        assert override_one["resolution_source"] == "MANUAL_OVERRIDE"
        fresh = get_success_data(api.get_employee(employee["id"], tax_director_headers))
        assert fresh["version"] == employee["version"] + 1, (
            "PRD §3.2: the override 'increments the employee's `version`'"
        )
        stale = api.override_local_assignment(
            override_local_assignment_payload(
                employee["id"], location["id"], employee["version"],
                effective_from="2026-09-01T00:00:00Z",
                override_reason="Second correction",
            ),
            tax_director_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
