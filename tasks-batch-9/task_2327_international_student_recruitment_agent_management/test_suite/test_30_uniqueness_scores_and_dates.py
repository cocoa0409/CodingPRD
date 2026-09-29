"""Record-level refusals on creation: duplicates, incoherent dates, bad scores.

Uniqueness has two different scopes, date coherence is checked inside the record
alone, the training bar is inclusive at eighty, and no caller-supplied date may
run ahead of the logical clock.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant, assert_score_2dp
from test_helpers.test_users import COMPLIANCE, OFFICER


class TestUniquenessHasTwoScopes:
    def test_a_repeated_program_code_and_a_repeated_live_module_both_conflict(
        self, client
    ):
        """One scope is global, the other is per agency and module.

        "A `RecruitmentOfficer` creates one with a `code` that is unique across
        programs"

        "A duplicate `code` is `ERR_DUPLICATE_RESOURCE`"

        "An agency may hold at most one certification in `VALID` status per module; a
        second live record for the same module is `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_program_code_and_certification_rejected
        """
        fx.create_program(client, code="MSCS-2026")
        agency = fx.register_agency(
            client, legal_name="Duplicate Scope Agency", complete_diligence=False
        )
        first_certification = fx.record_certification(
            client, agency["id"], C.MODULE_PROGRAM_ACCURACY, 92, C.DEFAULT_CLOCK_DATE
        )

        repeated_code = client.create_program(
            F.program_payload(
                code="MSCS-2026",
                name="MSc Computer Science (duplicate)",
                annual_tuition_cents=2100000,
            ),
            OFFICER,
        )
        validate_error(repeated_code, E.ERR_DUPLICATE_RESOURCE, 409)

        repeated_module = client.record_certification(
            agency["id"],
            F.certification_payload(C.MODULE_PROGRAM_ACCURACY, 95, C.DEFAULT_CLOCK_DATE),
            OFFICER,
        )
        validate_error(repeated_module, E.ERR_DUPLICATE_RESOURCE, 409)

        records, meta = validate_paginated(
            client.list_certifications(agency["id"], OFFICER)
        )
        assert meta["total_count"] == 1
        assert records[0]["id"] == first_certification["id"]
        assert records[0]["score"] == 92


class TestProgramDatesMustCohere:
    def test_a_census_before_teaching_and_a_persistence_check_on_the_census_are_refused(
        self, client
    ):
        """Two incoherent variants fail, the corrected third is stored.

        "`census_date` is the enrollment census, which must be on or after
        `term_start_date`"

        "`persistence_check_date` is the earliest date student persistence may be
        confirmed and must be strictly after `census_date`."

        "an incoherent date set — a census before term start, or a persistence check
        not strictly after the census — is `ERR_TERM_WINDOW_INVALID`."

        Design: Corner/validations/program_term_window_incoherent_rejected
        """
        census_too_early = client.create_program(
            F.program_payload(
                code="BAD-1",
                name="Census Before Term Start",
                annual_tuition_cents=2000000,
                term_start_date="2026-09-01",
                census_date="2026-08-15",
                persistence_check_date="2027-02-15",
            ),
            OFFICER,
        )
        validate_error(census_too_early, E.ERR_TERM_WINDOW_INVALID, 422)

        persistence_on_census = client.create_program(
            F.program_payload(
                code="BAD-2",
                name="Persistence Equals Census",
                annual_tuition_cents=2000000,
                term_start_date="2026-09-01",
                census_date="2026-09-30",
                persistence_check_date="2026-09-30",
            ),
            OFFICER,
        )
        validate_error(persistence_on_census, E.ERR_TERM_WINDOW_INVALID, 422)

        accepted = validate_success(
            client.create_program(
                F.program_payload(
                    code="GOOD-1",
                    name="Coherent Program",
                    annual_tuition_cents=2000000,
                    term_start_date="2026-09-01",
                    census_date="2026-09-30",
                    persistence_check_date="2027-02-15",
                ),
                OFFICER,
            ),
            201,
        )
        assert accepted["commission_eligible"] is True

        stored = validate_success(client.get_program(accepted["id"], OFFICER))
        assert stored["census_date"] == "2026-09-30"
        assert stored["persistence_check_date"] == "2027-02-15"


class TestTrainingScoreFloorIsInclusive:
    def test_seventy_nine_is_refused_and_eighty_is_stored(self, client):
        """The bar is a floor, not a strict threshold.

        "A score below 80 is refused with `ERR_TRAINING_SCORE_INSUFFICIENT`"

        Design: Corner/validations/training_certification_below_passing_score_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Passing Bar Agency", complete_diligence=False
        )

        below = client.record_certification(
            agency["id"],
            F.certification_payload(C.MODULE_PROGRAM_ACCURACY, 79, C.DEFAULT_CLOCK_DATE),
            OFFICER,
        )
        validate_error(below, E.ERR_TRAINING_SCORE_INSUFFICIENT, 422)

        exactly_at_the_bar = fx.record_certification(
            client, agency["id"], C.MODULE_PROGRAM_ACCURACY, 80, C.DEFAULT_CLOCK_DATE
        )
        assert exactly_at_the_bar["status"] == C.CERT_VALID
        assert exactly_at_the_bar["score"] == 80

        _, meta = validate_paginated(
            client.list_certifications(agency["id"], OFFICER)
        )
        assert meta["total_count"] == 1


class TestNoDateMayRunAheadOfTheClock:
    def test_tomorrows_incident_and_tomorrows_training_are_both_refused_today(
        self, client
    ):
        """The same date becomes acceptable once the clock reaches it.

        "the `occurred_on` date on which the conduct took place, which may not be
        later than the current logical-clock date and is refused with
        `ERR_FUTURE_DATE_NOT_ALLOWED` if it is"

        "an `issued_on` later than the current logical-clock date is refused with
        `ERR_FUTURE_DATE_NOT_ALLOWED`"

        "The incident lands in `status` `REPORTED` and contributes nothing to risk
        until it is adjudicated."

        Design: Corner/validations/future_dated_incident_and_certification_rejected
        """
        agency = fx.register_agency(
            client, legal_name="Clock Bound Agency", complete_diligence=False
        )

        future_incident = client.file_incident(
            F.incident_payload(
                agency["id"],
                category=C.INCIDENT_PROHIBITED_CLAIM,
                severity=C.SEVERITY_LOW,
                occurred_on="2026-08-02",
                source=C.SOURCE_STUDENT_COMPLAINT,
            ),
            COMPLIANCE,
        )
        validate_error(future_incident, E.ERR_FUTURE_DATE_NOT_ALLOWED, 422)

        future_certification = client.record_certification(
            agency["id"],
            F.certification_payload(C.MODULE_VISA_INTEGRITY, 90, "2026-08-02"),
            OFFICER,
        )
        validate_error(future_certification, E.ERR_FUTURE_DATE_NOT_ALLOWED, 422)

        advanced = fx.set_clock(client, "2026-08-02T00:00:00Z", COMPLIANCE)
        assert_instant(advanced["current_utc"], "2026-08-02T00:00:00Z", "current_utc")

        now_acceptable = fx.file_incident(
            client,
            agency["id"],
            category=C.INCIDENT_PROHIBITED_CLAIM,
            severity=C.SEVERITY_LOW,
            occurred_on="2026-08-02",
            source=C.SOURCE_STUDENT_COMPLAINT,
        )
        assert now_acceptable["occurred_on"] == "2026-08-02"
        assert now_acceptable["status"] == C.INCIDENT_REPORTED

        assert_score_2dp(
            fx.read_agency(client, agency["id"])["rolling_risk_score"],
            0.00,
            "rolling_risk_score",
        )
