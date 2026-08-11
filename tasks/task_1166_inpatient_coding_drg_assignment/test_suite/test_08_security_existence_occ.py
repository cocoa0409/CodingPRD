"""Auth/authentication ladder, cross-role denials, existence errors, OCC
stale-version guards, and the assign/release workload invariant."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_rebill_request_payload,
    get_success_data,
    make_auditor_headers,
    make_coder,
    make_coder_headers,
    make_clerk_headers,
    make_officer_headers,
    setup_assigned,
    setup_open_review,
    setup_submitted_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthenticationAndAuthorization:
    def test_list_accounts_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing or unknown `X-User-Role`, or a
        missing `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/list_accounts_unauthenticated
        """
        res = api.list_patient_accounts(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_create_coder_as_coder_forbidden(self, api, manager_headers):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of the caller's designated role
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/create_coder_as_coder_forbidden
        """
        caller = make_coder("E-VA2", credential="CCS", full_name="For Bidder")
        res = api.create_coder(
            {"employee_no": "E-VA2X", "full_name": "Nope", "credential": "CCA"},
            make_coder_headers(caller["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_create_assignment_forbidden_before_not_found(self, api, manager_headers):
        """PRD §2.8: "the failure reported is the earliest one on the following
        fixed ladder" — authorization (tier 2) precedes existence (tier 3), so
        a role-forbidden assignment create against a non-existent chart yields
        `ERR_FORBIDDEN`, not `ERR_CHART_NOT_FOUND`.

        Design: Corner/validations/create_assignment_forbidden_before_not_found
        """
        caller = make_coder("E-VA3", credential="CCS", full_name="Prio Auth")
        res = api.create_assignment(
            {
                "chart_id": NON_EXISTENT_UUID,
                "coder_id": caller["id"],
                "due_at": "2026-05-10T00:00:00Z",
            },
            make_coder_headers(caller["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_create_audit_as_clerk_forbidden(self, api, clerk_headers):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with `ERR_FORBIDDEN` (HTTP 403)" — audits
        are opened by Auditors only (§3.8).

        Design: Corner/rbac/create_audit_as_clerk_forbidden
        """
        subject = make_coder("E-RB2", credential="CCS", full_name="Sub Ject")
        res = api.create_audit(
            {
                "subject_coder_id": subject["id"],
                "window_start": "2026-04-01T00:00:00Z",
                "window_end": "2026-05-01T00:00:00Z",
                "sample_size": 3,
            },
            make_clerk_headers("clerk-rb2"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_create_rebill_as_officer_forbidden(self, api, manager_headers):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of the caller's designated role
        is rejected with `ERR_FORBIDDEN` (HTTP 403)" — and per §2.8 the
        authorization tier precedes existence, so the non-existent review id
        is never consulted.

        Design: Corner/rbac/create_rebill_as_officer_forbidden
        """
        account = get_success_data(
            api.create_patient_account(
                {
                    "mrn": "MRN-RB3",
                    "admit_at": "2026-04-20T08:00:00Z",
                    "patient_class": "INPATIENT",
                    "financial_class": "MEDICARE",
                    "total_charges_cents": 900000,
                },
                manager_headers,
            )
        )
        res = api.create_rebill_request(
            {
                "review_id": NON_EXISTENT_UUID,
                "delta_cents": -100,
                "expected_bill_version": account["version"],
            },
            make_officer_headers("officer-rb3"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestExistenceErrors:
    def test_get_unknown_assignment_not_found(self, api, manager_headers):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_ASSIGNMENT_NOT_FOUND` for assignments".

        Design: Corner/errors/get_unknown_assignment_not_found
        """
        res = api.get_assignment(NON_EXISTENT_UUID, manager_headers)
        validate_error(res, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND, expected_status=404)

    def test_regroup_unknown_case_not_found(self, api, manager_headers):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_CODED_CASE_NOT_FOUND` for coded cases" — and
        existence (tier 3) precedes the OCC tier (tier 5).

        Design: Corner/errors/regroup_unknown_case_not_found
        """
        account = get_success_data(
            api.create_patient_account(
                {
                    "mrn": "MRN-ER3",
                    "admit_at": "2026-04-20T08:00:00Z",
                    "patient_class": "INPATIENT",
                    "financial_class": "MEDICARE",
                    "total_charges_cents": 900000,
                },
                manager_headers,
            )
        )
        res = api.regroup_coded_case(
            NON_EXISTENT_UUID,
            {"expected_coded_case_version": account["version"]},
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_CODED_CASE_NOT_FOUND, expected_status=404)

    def test_complete_unknown_audit_not_found(self, api):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_AUDIT_NOT_FOUND` for coding audits".

        Design: Corner/errors/complete_unknown_audit_not_found
        """
        auditor = make_coder("E-ER4", credential="RHIA", full_name="Aud Itor")
        res = api.complete_audit(NON_EXISTENT_UUID, make_auditor_headers(auditor["id"]))
        validate_error(res, ApiErrorId.ERR_AUDIT_NOT_FOUND, expected_status=404)

    def test_resolve_unknown_finding_not_found(self, api):
        """PRD §2.8: "a referenced resource that does not exist yields its
        dedicated 404: ... `ERR_FINDING_NOT_FOUND` for audit findings".

        Design: Corner/errors/resolve_unknown_finding_not_found
        """
        auditor = make_coder("E-ER5", credential="RHIA", full_name="Aud Itor")
        res = api.resolve_finding(
            NON_EXISTENT_UUID, {"resolution": "DISMISS"},
            make_auditor_headers(auditor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FINDING_NOT_FOUND, expected_status=404)


class TestOccStaleVersion:
    def test_occ_regroup_stale_version_rejected(self, api, manager_headers):
        """PRD §2.7: "Regrouping a coded case requires the request to carry
        `expected_coded_case_version`, set to the value of the case's
        `version` the client last observed. If the case's current `version`
        has advanced beyond that — because another regroup or an audit-finding
        application has legitimately recomputed the grouping in the meantime —
        the regroup is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_regroup_stale_version_rejected
        """
        ctx = setup_submitted_case("MRN-XC1", "E-XC1", acuity="MEDICAL_LOW", credential="CCS")
        case = ctx["case"]
        stale = case["version"] - 1
        res = api.regroup_coded_case(
            case["id"], {"expected_coded_case_version": stale}, manager_headers
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_regroup_current_version_succeeds(self, api, manager_headers):
        """PRD §3.4: "A successful regroup recomputes `severity_level`,
        `relative_weight`, and `expected_reimbursement_cents` from the chart's
        current `ACTIVE` lines, increments the case's `version` by one".

        Design: Corner/cross_cutting_layers/occ_regroup_stale_version_rejected
        """
        ctx = setup_submitted_case("MRN-XC1B", "E-XC1B", acuity="MEDICAL_LOW", credential="CCS")
        case = ctx["case"]
        regrouped = validate_success(
            api.regroup_coded_case(
                case["id"], {"expected_coded_case_version": case["version"]},
                manager_headers,
            ),
            200,
        )
        assert regrouped["version"] == case["version"] + 1

    def test_occ_rebill_create_stale_version_rejected(self, api, clerk_headers, manager_headers):
        """PRD §2.7: "Creating a rebill request requires the request to carry
        `expected_bill_version`, set to the value of the bill's `version` the
        client last observed. If the bill's current `version` no longer matches
        — because another writer has moved the bill since, for example by
        creating a rebill that supersedes the client's plan — the creation is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_rebill_create_stale_version_rejected
        """
        ctx = setup_open_review(
            "MRN-XC2", "E-XC2",
            credential="RHIA", acuity="MEDICAL_HIGH", total_charges_cents=2000000,
            dx_lines=[
                {"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True},
                {"icd_code": "N18.6", "poa": "Y", "sequence": 2, "cc_level": "MCC"},
            ],
            payer_ref="PR-XC2",
        )
        res = api.create_rebill_request(
            create_rebill_request_payload(
                ctx["review"]["id"], -200000, ctx["bill_version"] - 1
            ),
            clerk_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        bill = get_success_data(api.get_bill(ctx["bill"]["id"], manager_headers))
        assert bill["status"] == "POST_PAYMENT_REVIEW"
        data, meta = validate_paginated(
            api.list_rebill_requests(manager_headers, params={"review_id": ctx["review"]["id"]})
        )
        assert data == [], "a stale rebill create must not produce a RebillRequest"


class TestAssignReleaseConservesWorkload:
    def test_assign_debits_workload_by_acuity_weight(self, api, manager_headers):
        """PRD §3.2: "Creation debits the assigned coder's `workload_units` by
        the chart's acuity weight — one unit for `MEDICAL_LOW`, two for
        `MEDICAL_HIGH`, three for `SURGICAL`".

        Design: Difficulty/compensating_invariant/assignment_assign_release_conserves_workload
        """
        ctx = setup_assigned(
            "MRN-CI2", "E-CI2",
            acuity="SURGICAL", credential="RHIA", financial_class="COMMERCIAL",
        )
        coder = get_success_data(api.get_coder(ctx["coder"]["id"], manager_headers))
        assert coder["workload_units"] == 3

    def test_release_credits_workload_back(self, api, manager_headers):
        """PRD §3.2: "Releasing an `ASSIGNED` assignment performs the
        compensating action: the coder's `workload_units` is credited back by
        the same weight, the assignment's `coder_id` is cleared to null, and
        the assignment returns to `QUEUED`."

        Design: Difficulty/compensating_invariant/assignment_assign_release_conserves_workload
        """
        ctx = setup_assigned(
            "MRN-CI2B", "E-CI2B",
            acuity="SURGICAL", credential="RHIA", financial_class="COMMERCIAL",
        )
        released = validate_success(
            api.release_assignment(ctx["assignment"]["id"], manager_headers), 200
        )
        assert released["status"] == "QUEUED"
        assert released["coder_id"] is None
        coder = get_success_data(api.get_coder(ctx["coder"]["id"], manager_headers))
        assert coder["workload_units"] == 0
