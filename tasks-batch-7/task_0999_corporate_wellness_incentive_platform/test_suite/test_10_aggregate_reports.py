"""De-identified cohort reporting: k-anonymity, aggregates, publish guard (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_employee,
    create_employer,
    create_enrollment,
    create_active_program,
    create_report_payload,
    setup_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestExactKBoundary:
    """Difficulty instance: exactly k cohort members publishes; comparison is >=."""

    def test_exact_k_cohort_generates_report(self, api):
        """PRD §3.9: "The k-anonymity guard of §2.11 applies at this point: a cohort
        smaller than the employer's `k_anonymity_threshold` is refused with
        `ERR_COHORT_TOO_SMALL` and no report is persisted, while a cohort of
        exactly the threshold proceeds."

        Design: Difficulty/boundary_precision_check/report_generated_at_exact_k_cohort
        """
        ctx = setup_cohort(5)  # five ACTIVE ENG enrollments; employer k == 5
        validate_success(api.close_program(ctx["program"]["id"], BA), 200)

        report = validate_success(
            api.create_aggregate_report(
                create_report_payload(ctx["program"]["id"], "ENG"), BA
            ),
            201,
        )
        assert report["status"] == "GENERATED"
        assert report["cohort_size"] == 5, "exactly the k_anonymity_threshold proceeds"

    def test_exact_k_report_zero_aggregates(self, api):
        """PRD §3.9: "For a surviving cohort, three aggregates are computed:
        `avg_settled_points`, the mean of the cohort's `points_balance_settled`
        rounded half-up to two decimal places; `participation_rate`, the fraction
        of the cohort holding at least one `COMPLETED` challenge participation,
        rounded half-up to four decimal places; and `tobacco_rate`, the fraction of
        the cohort whose employee's `tobacco_attested` is true, likewise rounded
        half-up to four decimal places."

        Design: Difficulty/boundary_precision_check/report_generated_at_exact_k_cohort
        """
        ctx = setup_cohort(5)
        validate_success(api.close_program(ctx["program"]["id"], BA), 200)

        report = validate_success(
            api.create_aggregate_report(
                create_report_payload(ctx["program"]["id"], "ENG"), BA
            ),
            201,
        )
        assert report["avg_settled_points"] == 0, "all five balances are 0"
        assert report["participation_rate"] == 0, "nobody holds a COMPLETED participation"
        assert report["tobacco_rate"] == 0, "nobody attested tobacco"


class TestCohortBelowK:
    def test_cohort_below_k_rejected(self, api):
        """PRD §2.11: "Every employer declares a `k_anonymity_threshold`, the minimum
        cohort size for which a report may be generated. If the computed cohort is
        smaller than this threshold, report generation is refused with
        `ERR_COHORT_TOO_SMALL` and no report record is persisted at all..."
        PRD §3.9: "The cohort is the set of the program's enrollments whose
        employee's `department` equals the report's `department` and whose
        `participation_status` is `ACTIVE`, `SUSPENDED`, or `TERMINATED`;
        `cohort_size` counts it."

        Design: Corner/errors/cohort_below_k_rejected
        """
        ctx = setup_cohort(4)  # four ACTIVE ENG enrollments
        # A fifth ENG enrollment that stays INVITED is excluded from the cohort.
        employee_5 = create_employee(ctx["employer"]["id"], n=5)
        create_enrollment(ctx["program"]["id"], employee_5["id"])
        validate_success(api.close_program(ctx["program"]["id"], BA), 200)

        res = api.create_aggregate_report(
            create_report_payload(ctx["program"]["id"], "ENG"), BA
        )
        validate_error(res, ApiErrorId.ERR_COHORT_TOO_SMALL, expected_status=422)

        _data, meta = validate_paginated(
            api.list_program_aggregate_reports(ctx["program"]["id"], BA)
        )
        assert meta["total_count"] == 0, "no report record may be persisted"


class TestPublishAfterSettle:
    def test_report_publish_after_settle_rejected(self, api):
        """PRD §3.9: "Publication moves `GENERATED → PUBLISHED` and requires the
        program still to be `CLOSED`; if the program has since settled, publication
        is rejected with `ERR_PROGRAM_ALREADY_SETTLED`."

        Design: Corner/endpoints/report_publish_after_settle_rejected
        """
        employer = create_employer(k_anonymity_threshold=1)
        program = create_active_program(employer["id"])
        ctx = setup_cohort(1, employer=employer, program=program)
        validate_success(api.close_program(program["id"], BA), 200)

        report = validate_success(
            api.create_aggregate_report(create_report_payload(program["id"], "ENG"), BA),
            201,
        )
        assert report["status"] == "GENERATED"

        settled = validate_success(api.settle_program(program["id"], BA), 200)
        assert settled["status"] == "SETTLED", "no awards exist, so settle is permitted"

        res = api.publish_aggregate_report(report["id"], BA)
        validate_error(res, ApiErrorId.ERR_PROGRAM_ALREADY_SETTLED, expected_status=409)

        reports, _meta = validate_paginated(
            api.list_program_aggregate_reports(program["id"], BA)
        )
        by_id = {r["id"]: r for r in reports}
        assert by_id[report["id"]]["status"] == "GENERATED", "report must be unchanged"
