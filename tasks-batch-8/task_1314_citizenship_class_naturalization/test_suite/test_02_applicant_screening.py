"""Applicant intake and eligibility screening (PRD §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_applicant,
    assert_fee_waiver_request,
    assert_same_instant,
    assert_screening,
    create_fee_waiver,
    create_program,
    create_screening,
    is_iso8601_timestamp,
    register_applicant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestApplicantIntake:
    def test_applicant_creation_initial_state_and_system_fields(self, api):
        """PRD §3.2: "A new applicant begins at stage `REGISTERED`, with
        `current_screening_id` null and `voter_registration_referred` false."
        PRD §3.2: "An `IntakeCoordinator` registers each new applicant with a
        `full_name`, an `email`, a `date_of_birth`, and an optional
        `preferred_language` that defaults to "en"."

        Design: Corner/entities/applicant_creation_initial_state_and_system_fields
        """
        create_program()
        data = validate_success(
            api.create_applicant(
                {"full_name": "New Person", "email": "np@example.org",
                 "date_of_birth": "1990-05-05"},
                COORD,
            ),
            201,
        )
        assert_applicant(data)
        assert data["stage"] == "REGISTERED"
        assert data["voter_registration_referred"] is False
        assert data["current_screening_id"] is None
        assert data["preferred_language"] == "en"
        assert data["version"] == 1
        assert is_iso8601_timestamp(data["created_at"])

    def test_applicant_missing_required_email_returns_invalid_request(self, api):
        """PRD §2.9: "Required fields present, types correct, enum members valid,
        integer ranges respected — a `household_size` outside 1 to 12, an
        `english_level` outside 0 to 4, an `end_minute` not later than `start_minute`
        — rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/applicant_missing_required_email_returns_invalid_request
        """
        create_program()
        response = api.create_applicant({"full_name": "No Email"}, COORD)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_applicant_returns_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve to an existing
        resource rejects the request with `ERR_NOT_FOUND`, and no later identifier is
        examined."

        Design: Corner/entities/get_nonexistent_applicant_returns_not_found
        """
        create_program()
        response = api.get_applicant(NON_EXISTENT_UUID, COORD)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestScreeningCreation:
    def test_screening_invalid_request_english_level_out_of_range(self, api):
        """PRD §2.9: "Required fields present, types correct, enum members valid,
        integer ranges respected — a `household_size` outside 1 to 12, an
        `english_level` outside 0 to 4, an `end_minute` not later than `start_minute`
        — rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/screening_invalid_request_english_level_out_of_range
        """
        create_program()
        applicant = register_applicant()
        payload = {
            "expected_applicant_version": applicant["version"],
            "marital_to_citizen": False,
            "lpr_months": 80,
            "continuous_residence_months": 61,
            "physical_presence_days": 1000,
            "age_years": 36,
            "english_level": 5,
            "civics_practice_pct": 50,
            "has_legal_flag": False,
        }
        response = api.create_screening(applicant["id"], payload, COORD)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    def test_screening_presence_days_913_boundary(self, api):
        """PRD §3.2: "The residence requirement is 36 months when the applicant is
        married to a citizen, otherwise 60 months; the physical presence requirement
        is 548 days when married to a citizen, otherwise 913 days."
        PRD §3.2: "All boundaries are inclusive: meeting a requirement exactly
        satisfies it."
        PRD §3.2: "When the new outcome is `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` and
        the applicant is still `REGISTERED`, the stage advances automatically to
        `SCREENED`."

        Design: Corner/calculations/screening_presence_days_913_boundary
        """
        create_program()
        applicant_met = register_applicant(full_name="P913")
        met = create_screening(
            applicant_met["id"], continuous_residence_months=60,
            physical_presence_days=913, age_years=36, english_level=1,
            civics_practice_pct=0,
        )
        assert_screening(met)
        assert met["outcome"] == "ELIGIBLE", "913 days meets the 913-day requirement"

        applicant_short = register_applicant(full_name="P912")
        short = create_screening(
            applicant_short["id"], continuous_residence_months=60,
            physical_presence_days=912, age_years=36, english_level=1,
            civics_practice_pct=0,
        )
        assert short["outcome"] == "NOT_ELIGIBLE", "912 days fails the requirement"

        assert api.get_applicant(applicant_met["id"], COORD).json()["data"]["stage"] == "SCREENED"
        assert api.get_applicant(applicant_short["id"], COORD).json()["data"]["stage"] == "REGISTERED", (
            "no stage bump for a NOT_ELIGIBLE outcome"
        )

    def test_screening_english_exemption_age_55(self, api):
        """PRD §3.2: "Otherwise, when `english_level` is at least 1, the outcome is
        `ELIGIBLE`. Otherwise, when `age_years` is at least 55 and `lpr_months` is at
        least 180, the outcome is `ELIGIBLE_WITH_EXEMPTION`. In every remaining case
        the outcome is `NOT_ELIGIBLE`."

        Design: Corner/calculations/screening_english_exemption_age_55
        """
        create_program()
        older = register_applicant(full_name="Older", date_of_birth="1971-01-01")
        exempt = create_screening(
            older["id"], lpr_months=180, continuous_residence_months=70,
            physical_presence_days=1000, age_years=55, english_level=0,
            civics_practice_pct=0,
        )
        assert exempt["outcome"] == "ELIGIBLE_WITH_EXEMPTION"

        younger = register_applicant(full_name="Younger", date_of_birth="1972-06-01")
        not_eligible = create_screening(
            younger["id"], lpr_months=180, continuous_residence_months=70,
            physical_presence_days=1000, age_years=54, english_level=0,
            civics_practice_pct=0,
        )
        assert not_eligible["outcome"] == "NOT_ELIGIBLE", (
            "age 54 misses the 55-year exemption boundary"
        )

    def test_screening_second_create_supersedes_first(self, api):
        """PRD §3.2: "Creating a new screening for an applicant supersedes the old:
        any prior `ACTIVE` screening flips to `SUPERSEDED` (terminal),
        `current_screening_id` repoints to the new record, and the applicant's
        `version` increments by one."

        Design: Corner/state_machines/screening_second_create_supersedes_first
        """
        create_program()
        applicant = register_applicant()
        first = create_screening(applicant["id"])
        assert first["status"] == "ACTIVE"

        second = create_screening(
            applicant["id"], marital_to_citizen=True, lpr_months=40,
            continuous_residence_months=37, physical_presence_days=600,
            age_years=36, english_level=1, civics_practice_pct=10,
        )
        assert_screening(second)
        assert second["status"] == "ACTIVE"
        assert second["outcome"] == "ELIGIBLE", (
            "marital rule: residence 37 >= 36 and presence 600 >= 548"
        )

        rows, meta = validate_paginated(api.list_screenings(applicant["id"], COORD))
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "ACTIVE"

        applicant_after = api.get_applicant(applicant["id"], COORD).json()["data"]
        assert applicant_after["current_screening_id"] == second["id"]
        assert applicant_after["version"] == applicant["version"] + 2, (
            "each screening write increments the applicant version by one"
        )

    def test_immediate_consistency_computed_fields_in_create_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "Every screening is born `ACTIVE` with an `expires_at` set to its
        creation clock time plus 180 days."
        PRD §3.7: "The second derived value is `required_document_count`: exactly 2
        when the request is benefit-based, otherwise the household size plus one."

        Design: Corner/consistency_model/immediate_consistency_computed_fields_in_create_response
        """
        create_program()
        applicant = register_applicant()
        payload = {
            "expected_applicant_version": applicant["version"],
            "marital_to_citizen": False,
            "lpr_months": 80,
            "continuous_residence_months": 61,
            "physical_presence_days": 1000,
            "age_years": 36,
            "english_level": 2,
            "civics_practice_pct": 50,
            "has_legal_flag": False,
        }
        screening = validate_success(
            api.create_screening(applicant["id"], payload, COORD), 201
        )
        assert_screening(screening)
        assert screening["outcome"] == "ELIGIBLE", "outcome computed inline at creation"
        assert_same_instant(
            screening["expires_at"], "2027-01-28T00:00:00Z",
            "expires_at must equal the creation clock time (2026-08-01) plus 180 days",
        )

        waiver = validate_success(
            api.create_fee_waiver_request(
                applicant["id"],
                {"household_size": 3, "self_reported_income_cents": 2000000,
                 "self_reported_benefit": False},
                COORD,
            ),
            201,
        )
        assert_fee_waiver_request(waiver)
        assert waiver["required_document_count"] == 4, (
            "household size 3 plus one, computed inline on the creation response"
        )
