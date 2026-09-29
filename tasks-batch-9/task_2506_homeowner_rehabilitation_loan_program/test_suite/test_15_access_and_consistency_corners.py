"""Who may act, on whose rows, against which observed version — and when it lands."""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_applicant,
    assert_change_order,
    assert_complaint_case,
    assert_contractor,
    assert_instant,
    assert_performance_score_clamped,
    assert_program_year,
    assert_rehab_application,
    assert_unset,
    assert_work_write_up,
    build_user_headers,
    create_applicant_payload,
    create_change_order_payload,
    create_complaint_payload,
    create_contractor_payload,
    create_inspection_payload,
    create_write_up_payload,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
    OPERATOR_READ_HEADERS,
)
from test_helpers.fixtures import (
    INSPECTOR,
    INTAKE,
    PROGRAM_MANAGER,
    REHAB,
    build_applicant,
    build_application,
    build_verified_applicant,
    complete_initial_inspection,
    record_lien,
    refresh_application,
    refresh_contractor,
    refresh_loan,
    set_contractor_status,
    setup_case,
    verify_application_ownership,
)

COMPLAINTS = [
    {
        "defect_category": "WORKMANSHIP",
        "description": "Ridge shingles lifting at the north slope",
    },
    {
        "defect_category": "INCOMPLETE_WORK",
        "description": "Gutter run never installed on the rear elevation",
    },
    {
        "defect_category": "MATERIAL_DEFECT",
        "description": "Underlayment is not the specified grade",
    },
]
SCORE_WALK = [
    (1, 85, "APPROVED"),
    (2, 65, "APPROVED"),
    (3, 45, "PROBATION"),
]


def _file_complaint(contractor_id, application_id, body):
    """File one warranty complaint and return the created row."""
    return validate_success(
        api_client.create_complaint(
            create_complaint_payload(contractor_id, application_id, **body),
            REHAB,
        ),
        201,
    )


def _file_complaints(contractor_id, application_id, count):
    """File the first `count` warranty complaints and return the created rows."""
    return [
        _file_complaint(contractor_id, application_id, body)
        for body in COMPLAINTS[:count]
    ]


class TestAuthenticationPrecedesEverything:
    """The role header is the first thing read, and an unknown role is not a role."""

    def test_a_read_with_no_role_header_is_unauthenticated(self, program_year):
        """A caller who names no role is turned away before the row is even addressed.

        PRD: "The `X-User-Role` header is present and names one of the seven roles
        — otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/a_request_with_a_missing_x_user_role_header_is_unauthenticated
        """
        program_year_id = program_year["id"]

        anonymous = api_client.get_program_year(
            program_year_id, {"X-User-ID": "is-1"}
        )

        validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)
        validate_error(
            api_client.get_program_year(
                program_year_id, build_user_headers("is-1", "Auditor")
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.get_program_year(
                program_year_id, build_user_headers("is-1", "")
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        readable = validate_success(
            api_client.get_program_year(program_year_id, INTAKE), 200
        )

        assert_program_year(readable)
        assert readable["id"] == program_year_id, (
            "The very same read succeeds once the caller names a declared role"
        )
        assert readable["fiscal_year"] == 2026


class TestExclusiveWriteOperations:
    """A write endpoint belongs to one role, and seniority does not enter into it."""

    def test_an_inspector_cannot_open_a_household_file(self, program_year):
        """The role is judged before the body, and no role outranks another.

        PRD: "The caller's role appears in the addressed endpoint's authorized-role
        list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."

        PRD: "Role authorization is decided from the endpoint's authorized-role
        list alone, before any row is loaded, so that a caller in a forbidden role
        cannot use the response to probe whether a record exists."

        Design: Corner/rbac/an_inspector_cannot_create_an_applicant_forbidden
        """
        payload = create_applicant_payload(program_year["id"])

        refused = api_client.create_applicant(payload, INSPECTOR)

        validate_error(refused, "ERR_FORBIDDEN_ROLE", 403)
        _, meta = validate_paginated(
            api_client.list_applicants(INTAKE, {"program_year_id": program_year["id"]})
        )
        assert meta["total_count"] == 0, (
            f"The refusal registers no household, got {meta['total_count']}"
        )
        malformed = dict(payload)
        malformed.pop("household_size")
        validate_error(
            api_client.create_applicant(malformed, INSPECTOR),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.create_applicant(payload, PROGRAM_MANAGER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        accepted = validate_success(api_client.create_applicant(payload, INTAKE), 201)

        assert_applicant(accepted)
        assert accepted["eligibility_status"] == "APPLIED", (
            "The body was always well formed; only the caller's role was wrong"
        )
        assert accepted["household_size"] == 4

    def test_the_intake_specialist_is_barred_from_the_field_work_and_the_list(
        self, ownership_verified_application
    ):
        """The exclusion runs both ways: intake cannot inspect or enrol a firm.

        PRD: "The caller's role appears in the addressed endpoint's authorized-role
        list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."

        Design: Corner/rbac/an_inspector_cannot_create_an_applicant_forbidden
        """
        application_id = ownership_verified_application["id"]
        window = create_inspection_payload(application_id)
        firm_payload = create_contractor_payload(legal_name="Borough Builders Inc")

        validate_error(
            api_client.create_inspection(window, INTAKE), "ERR_FORBIDDEN_ROLE", 403
        )
        validate_error(
            api_client.create_contractor(firm_payload, INTAKE),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        _, inspection_meta = validate_paginated(
            api_client.list_inspections(INSPECTOR, {"application_id": application_id})
        )
        _, firm_meta = validate_paginated(api_client.list_contractors(PROGRAM_MANAGER))
        assert inspection_meta["total_count"] == 0, (
            f"No window is reserved by the refusal, got {inspection_meta['total_count']}"
        )
        assert firm_meta["total_count"] == 0, (
            f"No firm joins the list by the refusal, got {firm_meta['total_count']}"
        )

        reserved = validate_success(api_client.create_inspection(window, INSPECTOR), 201)
        enrolled = validate_success(
            api_client.create_contractor(firm_payload, PROGRAM_MANAGER), 201
        )

        assert reserved["status"] == "SCHEDULED", (
            "The identical window is accepted from the role that owns the endpoint"
        )
        assert_contractor(enrolled)
        assert enrolled["approved_list_status"] == "APPROVED"


class TestSharedReadsAndTheirLimits:
    """Shared is not universal: the sharing is drawn per endpoint, not per record."""

    def test_every_operator_reads_the_program_year_but_the_two_parties_do_not(
        self, program_year, application
    ):
        """Five operator identities read one ledger; the household reads its own case.

        PRD: "A caller whose role is not listed for the addressed endpoint receives
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD: "The remaining five roles are opaque operator identities."

        Design: Corner/rbac/read_endpoints_are_shared_across_every_operator_role
        """
        program_year_id = program_year["id"]

        bodies = [
            validate_success(
                api_client.get_program_year(program_year_id, headers), 200
            )
            for headers in OPERATOR_READ_HEADERS
        ]

        assert len(bodies) == 5
        assert_program_year(bodies[0])
        for body in bodies[1:]:
            assert body == bodies[0], (
                "Every operator role sees one and the same ledger, got "
                f"{body} against {bodies[0]}"
            )
        validate_error(
            api_client.get_program_year(
                program_year_id, TEST_USERS["applicant_headers"]
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.get_program_year(
                program_year_id, TEST_USERS["contractor_headers"]
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        own_case = validate_success(
            api_client.get_application(
                application["id"], make_applicant_headers(application["applicant_id"])
            ),
            200,
        )

        assert_rehab_application(own_case)
        assert own_case["id"] == application["id"], (
            "The household is listed on its own case's read even though it may not "
            "read the program year"
        )


class TestPerRecordScopeForHouseholds:
    """The household role is entity-backed, so authorisation is decided per row."""

    def test_a_household_cannot_read_another_households_case(self, program_year):
        """One household's identity does not reach the neighbour's file.

        PRD: "An entity-backed caller addresses only its own rows — otherwise
        `ERR_OWNERSHIP_MISMATCH` (403). This scoping applies to five operations:
        reading one rehabilitation application, reading one loan, submitting a bid,
        creating a draw request, and reading one complaint case."

        PRD: "An entity-backed caller that addresses another party's record
        receives `ERR_OWNERSHIP_MISMATCH` (HTTP 403), which does not disclose
        whether the record exists."

        Design: Corner/rbac/an_applicant_cannot_read_another_households_application
        """
        household_a = build_verified_applicant(
            program_year["id"], full_name="Household A"
        )
        household_b = build_applicant(
            program_year["id"],
            full_name="Household B",
            household_size=3,
            wage_income_cents=6_000_000,
        )
        case = build_application(household_a["id"], address_line1="18 Larkspur Ave")

        trespass = api_client.get_application(
            case["id"], make_applicant_headers(household_b["id"])
        )

        validate_error(trespass, "ERR_OWNERSHIP_MISMATCH", 403)

        own = validate_success(
            api_client.get_application(
                case["id"], make_applicant_headers(household_a["id"])
            ),
            200,
        )

        assert own["id"] == case["id"]
        assert own["applicant_id"] == household_a["id"], (
            "The owning household reads the same row the neighbour was refused"
        )
        assert own["workflow_state"] == "INTAKE"


class TestOptimisticConcurrencyOnObservedParents:
    """A create that supersedes a parent must have observed that parent's last state."""

    def test_a_case_version_captured_at_intake_is_two_writes_stale(self, program_year):
        """Ownership verification and the inspection cascade both moved the case.

        PRD: "A `POST /rehab/write-ups` request must carry
        `expected_application_version` matching the target `RehabApplication`'s
        current `version`."

        PRD: "If any writer has advanced the application's `version` since the
        client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP
        412) and no write-up is opened."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_application_version_blocks_the_write_up_revision
        """
        household = build_verified_applicant(program_year["id"])
        case = build_application(household["id"], year_built=1995)
        stale_version = case["version"]
        verify_application_ownership(case["id"])
        complete_initial_inspection(case["id"])

        refused = api_client.create_write_up(
            create_write_up_payload(case["id"], stale_version), REHAB
        )

        validate_error(refused, "ERR_STALE_VERSION", 412)
        _, meta = validate_paginated(
            api_client.list_write_ups(REHAB, {"application_id": case["id"]})
        )
        assert meta["total_count"] == 0, (
            f"The stale create opens no scope, got {meta['total_count']}"
        )
        fresh = refresh_application(case["id"])
        assert fresh["version"] == stale_version + 2, (
            "Verifying ownership and recording the finding each advanced the case, "
            f"so the observed {stale_version} is two writes behind {fresh['version']}"
        )
        assert fresh["workflow_state"] == "INSPECTED"

        opened = validate_success(
            api_client.create_write_up(
                create_write_up_payload(case["id"], fresh["version"]), REHAB
            ),
            201,
        )

        assert_work_write_up(opened)
        assert opened["state"] == "DRAFT"
        assert opened["revision_number"] == 1, (
            f"A first scope opens at revision one, got {opened['revision_number']}"
        )
        assert opened["work_item_count"] == 0
        assert_unset(opened, "approved_by_user_id")

    def test_a_loan_version_captured_before_recording_no_longer_carries_a_change_order(
        self,
    ):
        """Recording the lien moved the note, so the observed version is spent.

        PRD: "A `POST /rehab/change-orders` request must carry
        `expected_loan_version` matching the target `RehabLoan`'s current
        `version`."

        PRD: "If the loan's `version` has advanced since the client last read it,
        the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_application_version_blocks_the_write_up_revision
        """
        case = setup_case(
            stage="structured",
            loan_overrides={"structure_type": "DEFERRED", "forgiveness_term_months": 60},
        )
        loan_id = case["loan"]["id"]
        stale_version = case["loan"]["version"]
        record_lien(loan_id)

        refused = api_client.create_change_order(
            create_change_order_payload(
                loan_id,
                stale_version,
                amount_delta_cents=300_000,
                justification="Concealed rafter rot found on demolition",
            ),
            REHAB,
        )

        validate_error(refused, "ERR_STALE_VERSION", 412)
        _, meta = validate_paginated(
            api_client.list_change_orders(REHAB, {"loan_id": loan_id})
        )
        assert meta["total_count"] == 0, (
            f"The stale create files no change order, got {meta['total_count']}"
        )
        current = refresh_loan(loan_id)
        assert current["status"] == "LIEN_RECORDED"
        assert current["version"] > stale_version, (
            "Recording advanced the note past the observed version "
            f"{stale_version}, got {current['version']}"
        )

        submitted = validate_success(
            api_client.create_change_order(
                create_change_order_payload(
                    loan_id,
                    current["version"],
                    amount_delta_cents=300_000,
                    justification="Concealed rafter rot found on demolition",
                ),
                REHAB,
            ),
            201,
        )

        assert_change_order(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["cumulative_delta_pct"] == pytest.approx(0.0, abs=0.01)
        assert submitted["amount_delta_cents"] == 300_000


class TestCumulativeComplaintThreshold:
    """The demotion is a running total, not a reaction to any single complaint."""

    def test_the_third_open_complaint_is_the_one_that_demotes_the_firm(
        self, complaint_ready_case
    ):
        """The score walks 100, 85, 65, 45 and the standing moves only at the end.

        PRD: "A firm's `performance_score` starts from a base of 100, loses 20
        points for each open complaint, loses 15 points for each sanction recorded
        in `sanction_count`, and gains 5 points for each completed rehabilitation
        counted in `on_time_completion_count`, where the completion credit stops
        accumulating after four completions."

        PRD: "A score strictly below 50 demotes an `APPROVED` firm to `PROBATION`
        automatically."

        Design: Corner/cross_cutting_complexity_layers/the_third_open_complaint_tips_the_performance_score_below_the_probation_threshold
        """
        case = complaint_ready_case
        firm_id = case["contractor"]["id"]
        application_id = case["application"]["id"]
        closed_case = case["application"]
        assert closed_case["workflow_state"] == "CLOSED"
        assert closed_case["warranty_expires_at"].startswith("2027-10-30"), (
            "Twelve months after the 2026-10-30 completion, got "
            f"{closed_case['warranty_expires_at']}"
        )
        assert case["loan"]["status"] == "SERVICING"
        assert case["contractor"]["on_time_completion_count"] == 1
        assert case["contractor"]["performance_score"] == 100, (
            "The single completion credit is clamped back to 100, got "
            f"{case['contractor']['performance_score']}"
        )
        assert case["contractor"]["approved_list_status"] == "APPROVED"

        for body, (
            expected_open,
            expected_score,
            expected_standing,
        ) in zip(COMPLAINTS[:3], SCORE_WALK):
            complaint = _file_complaint(firm_id, application_id, body)
            assert_complaint_case(complaint)
            assert complaint["status"] == "FILED"
            assert_instant(complaint, "filed_at", "2026-08-01T00:00:00Z")
            assert complaint["warranty_expires_at"] == closed_case[
                "warranty_expires_at"
            ], (
                "The filing snapshots the window that governed it, got "
                f"{complaint['warranty_expires_at']}"
            )
            assert_unset(complaint, "remedy_deadline_at")
            assert_unset(complaint, "resolved_at")
            firm = refresh_contractor(firm_id)
            assert firm["open_complaint_count"] == expected_open
            assert firm["performance_score"] == expected_score, (
                f"With {expected_open} open complaints and one completion the score "
                f"is {expected_score}, got {firm['performance_score']}"
            )
            assert firm["approved_list_status"] == expected_standing, (
                f"At a score of {expected_score} the standing is "
                f"{expected_standing}, got {firm['approved_list_status']}"
            )
            assert_performance_score_clamped(firm["performance_score"])

    def test_resolving_one_complaint_lifts_the_score_but_not_the_standing(
        self, complaint_ready_case
    ):
        """Recovery of the score is automatic; recovery of the standing is not.

        PRD: "Promotion is never automatic: only an explicit standing change by a
        `ProgramManager` can restore a firm to `APPROVED`, and that restoration
        from `PROBATION` requires the firm's `performance_score` to be at or above
        50."

        PRD: "Both of those closing outcomes stamp `resolved_at` from the logical
        clock and recompute the firm's `open_complaint_count` and
        `performance_score`, and both are terminal."

        Design: Corner/cross_cutting_complexity_layers/the_third_open_complaint_tips_the_performance_score_below_the_probation_threshold
        """
        case = complaint_ready_case
        firm_id = case["contractor"]["id"]
        filed = _file_complaints(firm_id, case["application"]["id"], 3)
        assert refresh_contractor(firm_id)["approved_list_status"] == "PROBATION"
        notified = validate_success(
            api_client.notify_complaint(filed[0]["id"], PROGRAM_MANAGER), 200
        )
        assert notified["status"] == "CONTRACTOR_NOTIFIED"

        resolved = validate_success(
            api_client.resolve_complaint(
                filed[0]["id"],
                {
                    "resolution": "REMEDIED",
                    "resolution_note": "Shingles re-nailed and inspected",
                },
                PROGRAM_MANAGER,
            ),
            200,
        )

        assert resolved["status"] == "REMEDIED"
        assert_instant(resolved, "resolved_at", "2026-08-01T00:00:00Z")
        recovered = refresh_contractor(firm_id)
        assert recovered["open_complaint_count"] == 2, (
            "The remedied complaint no longer counts as open, got "
            f"{recovered['open_complaint_count']}"
        )
        assert recovered["performance_score"] == 65, (
            f"Two open complaints and one completion score 65, got "
            f"{recovered['performance_score']}"
        )
        assert recovered["approved_list_status"] == "PROBATION", (
            "The score recovered on its own but the standing did not"
        )

        restored = set_contractor_status(firm_id, "APPROVED", "Remediation accepted")

        assert restored["approved_list_status"] == "APPROVED", (
            "Only the explicit standing change walks the firm back onto the list"
        )
        assert restored["performance_score"] == 65, (
            "The manual restoration does not rewrite the score, got "
            f"{restored['performance_score']}"
        )
        assert restored["open_complaint_count"] == 2


class TestImmediateDerivation:
    """A 200 means the derived figures are already in the body that answered."""

    def test_the_certifying_response_already_carries_every_derived_figure(
        self, program_year
    ):
        """No later read populates anything the certification itself did not.

        PRD: "When they do, every affected row's `updated_at` and `version`
        advance, and the cascade is applied in full within the same request — the
        consistency model is immediate, never deferred."

        PRD: "In either outcome the four computed figures are stored,
        `verified_by_user_id` is set to the acting `X-User-ID`, and the household's
        `version` advances by one."

        Design: Corner/consistency_model/every_derived_value_is_already_correct_in_the_writing_responses_own_body
        """
        household = build_applicant(
            program_year["id"],
            wage_income_cents=7_000_000,
            household_assets_cents=5_000_000,
            dependents_count=2,
        )

        certified = validate_success(
            api_client.verify_income(household["id"], INTAKE), 200
        )

        assert_applicant(certified)
        assert certified["annual_income_cents"] == 7_020_000, (
            "The writing response itself carries the certified income, got "
            f"{certified['annual_income_cents']}"
        )
        assert certified["income_limit_cents"] == 9_000_000
        assert certified["ami_percent"] == pytest.approx(78.0, abs=0.01)
        assert certified["income_category"] == "LOW"
        assert certified["eligibility_status"] == "INCOME_VERIFIED"

        read_back = validate_success(
            api_client.get_applicant(household["id"], PROGRAM_MANAGER), 200
        )

        assert read_back == certified, (
            "The immediate read is field-for-field the body already returned, got "
            f"{read_back} against {certified}"
        )
        rows, meta = validate_paginated(
            api_client.list_applicants(INTAKE, {"income_category": "LOW"})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [household["id"]], (
            "The banded filter already matches on the first read after the write"
        )
