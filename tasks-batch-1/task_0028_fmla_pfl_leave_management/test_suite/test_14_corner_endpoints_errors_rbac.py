"""Corner — endpoints, errors, rbac, cross_cutting_complexity_layers sections.

`leave_case_denied_terminal_lockdown`, `error_employee_terminated_already_in_difficulty`,
`error_stale_version_via_recertification_already_in_difficulty`,
`occ_leave_case_approve_already_in_difficulty`, and
`derived_field_employer_pfl_enabled_recomputed_from_state` are all `excluded_because:`
stubs and NOT translated — the cited difficulty-design instances own the
assertions.
"""
from test_helpers import (
    ApiErrorId,
    apply_payment_payload,
    approve_case_payload,
    build_user_headers,
    create_employee,
    create_employer,
    create_employer_payload,
    create_employee_payload,
    create_provider,
    get_case,
    patch_health_enrollment_payload,
    record_interval,
    seed_historic_interval,
    seed_historic_interval_payload,
    set_clock,
    set_clock_payload,
    setup_approved_case,
    setup_case_in_certification_pending,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Endpoints ───────────────────────────────────────────────────────────────


class TestClockAdvanceNoEligibleLedgersReturnsEmptyArray:
    def test_clock_advance_on_empty_db_returns_current_utc_and_empty_array(self, api):
        """PRD §3.8: "The first is a clock-advance capability that accepts `to_iso8601` and sets the server's logical clock to that instant; on success the response carries the new `current_utc` and the `delinquent_ledger_ids` array of every ledger row that flipped to `DELINQUENT` as a side effect (per §3.7)."

        Design: Corner/endpoints/clock_advance_no_eligible_ledgers_returns_empty_array
        """
        res = api.set_clock(
            set_clock_payload("2030-01-01T00:00:00.000Z"),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["current_utc"] == "2030-01-01T00:00:00.000Z"
        assert data["delinquent_ledger_ids"] == [], (
            f"empty DB → no ledgers to flip; got {data['delinquent_ledger_ids']!r}"
        )


class TestSeedHistoricEndpointBypassesPoolCharge:
    def test_seed_historic_interval_accepts_direct_fmla_charge(self, api):
        """PRD §3.8: "The second is a historic-interval seeding capability that creates a `LeaveInterval` directly with caller-supplied `fmla_hours_charged` and `pfl_hours_charged`, bypassing the standard waterfall calculation; the seeded values are added directly to the parent case's `fmla_hours_charged` and `pfl_hours_charged` running totals."

        Design: Corner/endpoints/seed_historic_endpoint_bypasses_pool_charge
        """
        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        res = api.seed_historic_interval(
            seed_historic_interval_payload(
                bundle.case["id"],
                "2026-03-01T00:00:00.000Z",
                "2026-03-15T00:00:00.000Z",
                100,
                100,
                0,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        seeded = validate_success(res, expected_status=201)
        assert seeded["fmla_hours_charged"] == 100, (
            f"seed-historic must accept fmla_hours_charged directly; got {seeded['fmla_hours_charged']!r}"
        )
        assert seeded["status"] == "RECORDED"
        case_after = get_case(bundle.case["id"])
        assert case_after["fmla_hours_charged"] == 100, (
            f"case totals incremented by seeded amount; got {case_after['fmla_hours_charged']!r}"
        )


class TestFkFilteredListIntervalsByCase:
    def test_list_intervals_filter_by_case_returns_only_that_case_intervals(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Results are returned in ascending order of `created_at`."

        Design: Corner/endpoints/fk_filtered_list_intervals_by_case
        """
        # Build two approved cases on the same employer, each with one interval.
        bundle_a = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        # Reuse employer/provider for a second worker is non-trivial; just build
        # a second independent approved case.
        bundle_b = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        int_a = record_interval(
            bundle_a.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        int_b = record_interval(
            bundle_b.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        res = api.list_intervals(
            TEST_USERS["hr_admin_headers"],
            params={"leave_case_id": bundle_a.case["id"]},
        )
        data, _meta = validate_paginated(res)
        ids = [r["id"] for r in data]
        assert int_a["id"] in ids
        assert int_b["id"] not in ids, (
            f"filter by case A must NOT include intervals from case B; got ids={ids}"
        )
        assert len(data) == 1


# ─── Errors ──────────────────────────────────────────────────────────────────


class TestErrorStaleVersionOnEmployeeHealthEnrollment:
    def test_second_patch_with_stale_expected_version_returns_stale_version(self, api):
        """PRD §2.8: "The second guarded write is the employee health-enrollment toggle: the request must carry `expected_employee_version` matching the target `Employee`'s current `version`. If a prior writer toggled the same flag and bumped the employee's version (say from 5 to 6) while the current writer is still holding version 5, the second writer is deterministically rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_employee_health_enrollment
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(employer["id"])
        version_initial = emp["version"]
        # First PATCH bumps version.
        from test_helpers import patch_health_enrollment

        after1 = patch_health_enrollment(emp["id"], False, version_initial)
        assert after1["version"] > version_initial
        # Second PATCH carrying the STALE original version → ERR_STALE_VERSION.
        res = api.patch_employee_health_enrollment(
            emp["id"],
            patch_health_enrollment_payload(True, version_initial),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ─── RBAC ────────────────────────────────────────────────────────────────────


class TestEmployeeCannotApproveLeaveCase:
    def test_employee_role_cannot_call_approve_endpoint(self, api):
        """PRD §4 (endpoint table): "POST | `/leave/cases/{id}/approve` | Approve a case once its certification is `COMPLETE` (OCC-guarded). | `HRAdmin`"
        PRD §2.1: "A request whose `X-User-Role` is not on the endpoint's permitted-role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/employee_cannot_approve_leave_case
        """
        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        # Build a separate APPROVED-pending case for the Employee role to attack —
        # we already have one APPROVED, but to exercise the role check we attempt
        # approve again from Employee headers. Per PRD §4, approve is HRAdmin-only.
        from test_helpers import make_employee_headers, setup_case_in_certification_pending

        # We need a case in CERTIFICATION_PENDING with a COMPLETE cert.
        base = setup_case_in_certification_pending(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        from test_helpers import (
            mark_certification_complete,
            receive_certification,
            submit_certification,
        )

        cert = submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=4,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
        )
        receive_certification(cert["id"])
        mark_certification_complete(cert["id"])
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case_version_post_eligibility"]),
            make_employee_headers(base["employee"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestMissingAuthHeadersReturnsUnauthenticated:
    def test_request_without_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every API call must carry two HTTP headers: `X-User-ID`, the identifier of the calling principal, and `X-User-Role`, the role the principal is acting under for this request. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        res = api.create_employer(
            create_employer_payload(),
            headers={},  # no X-User-ID, no X-User-Role
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestHealthcareProviderCannotApprove:
    def test_healthcare_provider_role_cannot_call_approve_endpoint(self, api):
        """PRD §4 (endpoint table): "POST | `/leave/cases/{id}/approve` | Approve a case once its certification is `COMPLETE` (OCC-guarded). | `HRAdmin`"
        PRD §2.1: "A request whose `X-User-Role` is not on the endpoint's permitted-role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/healthcare_provider_cannot_approve
        """
        from test_helpers import (
            make_provider_headers,
            mark_certification_complete,
            receive_certification,
            submit_certification,
        )

        base = setup_case_in_certification_pending(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        cert = submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=4,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
        )
        receive_certification(cert["id"])
        mark_certification_complete(cert["id"])
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case_version_post_eligibility"]),
            make_provider_headers(base["provider"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestPlatformAdminCannotCreateEmployee:
    def test_platform_admin_role_cannot_call_create_employee(self, api):
        """PRD §4 (endpoint table): "POST | `/leave/employees` | Create an employee under an employer. | `HRAdmin`"
        PRD §2.1: "A request whose `X-User-Role` is not on the endpoint's permitted-role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/platform_admin_cannot_create_employee
        """
        employer = create_employer(state_code="FED")
        res = api.create_employee(
            create_employee_payload(employer["id"]),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


# ─── Cross-cutting complexity ────────────────────────────────────────────────


class TestPflConcurrentPinnedAtApprovalNotRecomputed:
    def test_pfl_concurrent_stamped_at_approve_remains_after_employee_mutation(self, api):
        """PRD §3.4: "the server stamps `pfl_concurrent` on the case using the rule: `pfl_concurrent` is true when the employer's `pfl_enabled` is true, the employee's `home_state_code` equals the employer's `state_code`, and the case's `qualifying_reason` is one of `OWN_SERIOUS_HEALTH_CONDITION`, `FAMILY_SERIOUS_HEALTH_CONDITION`, or `NEW_CHILD_BONDING`; the flag is pinned at approval and never changes thereafter."

        Design: Corner/cross_cutting_complexity_layers/case_pfl_concurrent_pinned_at_approval_not_recomputed
        """
        # CA employer + CA employee + OWN_SERIOUS_HEALTH_CONDITION → pfl_concurrent=true at approve.
        bundle = setup_approved_case(
            employer_state="CA",
            employee_home_state="CA",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        assert bundle.case["pfl_concurrent"] is True
        # PATCH the employee's health-enrollment flag — bumps employee.version.
        # The pinned pfl_concurrent flag on the case must NOT change.
        from test_helpers import patch_health_enrollment

        emp_v0 = bundle.employee["version"]
        patch_health_enrollment(bundle.employee["id"], False, emp_v0)
        case_after_patch = get_case(bundle.case["id"])
        assert case_after_patch["pfl_concurrent"] is True, (
            f"pfl_concurrent is pinned at approval and must not be recomputed; "
            f"got {case_after_patch['pfl_concurrent']!r}"
        )
