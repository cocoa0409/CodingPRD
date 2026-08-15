"""Platform baseline: envelopes, pagination, 404s, authentication, and RBAC."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    confirm_grading_run,
    farm_payload,
    get_lot,
    grading_submit_payload,
    is_valid_uuid,
    setup_confirmed_lot,
    setup_laying_flock,
    setup_laying_flock_with_production,
    validate_error,
    validate_paginated,
    validate_success,
    walk_audit_to_findings,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    CONTRACT_MANAGER,
    GRADER,
    QA_MANAGER,
    setup_farm,
)

TEST_ADMIN = TEST_USERS["platform_admin_headers"]
TEST_FM = TEST_USERS["farm_manager_headers"]


class TestFarmCreation:
    def test_farm_creation_defaults_and_envelope(self, api):
        """PRD §3.1: "A new farm's `compliance_posture` starts at `CLEAR`, and
        its `active_flock_count` starts at zero"
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.5: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/farm_creation_defaults_and_envelope
        """
        resp = api.create_farm(
            farm_payload(name="Default Farm", certification_program="CAGE_FREE",
                         daily_overhead_cents=9000),
            TEST_ADMIN,
        )
        body = resp.json()
        assert body.get("response_type") == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)

        data = validate_success(resp, 201)
        assert data["compliance_posture"] == "CLEAR"
        assert data["active_flock_count"] == 0
        assert isinstance(data["version"], int), (
            "every resource carries a system-managed integer version"
        )
        assert is_valid_uuid(data["id"])


class TestNotFound:
    def test_house_get_missing_returns_not_found(self, api):
        """PRD §2.9: "Existence checking validates the path identifier first
        and then any foreign-key identifiers in the body, working left to
        right, and the first identifier that does not resolve to an existing
        resource produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/house_get_missing_returns_not_found
        """
        resp = api.get_house(NON_EXISTENT_UUID, TEST_FM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestLotListing:
    def test_lot_list_pagination_and_filter(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "the egg-lot list breaks `created_at` ties by size-class
        rank in descending order, so `JUMBO` lots precede `XLARGE`, then
        `LARGE`, `MEDIUM`, `SMALL`, and finally `PEEWEE` (lots created
        together share pack timestamps)"
        PRD §2.3: "List endpoints also accept optional equality filters named
        after the resource's own fields"

        Design: Corner/entities/lot_list_pagination_and_filter
        """
        ctx = setup_laying_flock_with_production(
            [{"lay_date": "2026-07-31", "eggs_collected": 480, "rejected_eggs": 0}]
        )
        run, lots = confirm_grading_run(
            ctx["flock"]["id"], "A", 480,
            submit_counts=grading_submit_payload(large_count=240, jumbo_count=240),
        )
        assert len(lots) == 2

        page1, meta1 = validate_paginated(
            api.list_lots(QA_MANAGER, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["size_class"] == "JUMBO", (
            "the size-class rank tie-break puts JUMBO before LARGE"
        )

        page2, meta2 = validate_paginated(
            api.list_lots(QA_MANAGER, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["size_class"] == "LARGE"

        filtered, meta3 = validate_paginated(
            api.list_lots(QA_MANAGER, params={"lifecycle_status": "FRESH"})
        )
        assert meta3["total_count"] == 2
        assert {lot["lifecycle_status"] for lot in filtered} == {"FRESH"}


class TestAuthentication:
    def test_request_without_declared_role_unauthenticated(self, api):
        """PRD §2.1: "A request that arrives without these headers, or whose
        declared role is not one of the six declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.2: All error responses follow the standard envelope with
        response_type "error" and a data object carrying error_id and message.

        Design: Corner/rbac/request_without_declared_role_unauthenticated
        """
        resp = api.create_farm(
            farm_payload(name="Nope Farm", daily_overhead_cents=1),
            build_user_headers("intruder-1", "Anonymous"),
        )
        assert resp.json().get("response_type") == "error"
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleEnforcement:
    def test_grader_cannot_release_lot(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted on the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`QAManager` is the quality-assurance authority: it confirms
        or voids grading runs, records laboratory results, and releases,
        holds, or clears holds on egg lots."
        PRD §4: POST /api/lots/{lotId}/release — Authorized Role(s): QAManager.

        Design: Corner/rbac/grader_cannot_release_lot
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        resp = api.release_lot(lot_id, GRADER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_lot(lot_id)["lifecycle_status"] == "FRESH"

    def test_contract_manager_cannot_close_audit(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted on the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`ComplianceOfficer` owns audits and recalls, and shares
        salmonella-test scheduling with `QualityGrader`."
        PRD §4: POST /api/compliance-audits/{complianceAuditId}/close —
        Authorized Role(s): ComplianceOfficer.

        Design: Corner/rbac/contract_manager_cannot_close_audit
        """
        farm = setup_farm()
        audit = walk_audit_to_findings(farm["id"])
        resp = api.close_compliance_audit(
            audit["id"], {"outcome": "PASSED"}, CONTRACT_MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(
            api.get_compliance_audit(audit["id"], COMPLIANCE_OFFICER)
        )
        assert after["status"] == "FINDINGS_RECORDED"

    def test_sod_grading_confirm_same_user_rejected(self, api):
        """PRD §3.4: "Confirmation is a different desk: a `QAManager` confirms
        a `SUBMITTED` run, and the confirming `X-User-ID` must differ from
        `submitted_by`, else `ERR_SOD_VIOLATION` (HTTP 403)"
        PRD §2.1: "The single exception to this opacity is the pair of
        segregation-of-duties checks, which compare `X-User-ID` strings stored
        on the resource: the operator confirming a grading run must not be the
        operator recorded in that run's `submitted_by`"

        Design: Corner/rbac/sod_grading_confirm_same_user_rejected
        """
        ctx = setup_laying_flock_with_production(
            [{"lay_date": "2026-07-31", "eggs_collected": 240, "rejected_eggs": 0}]
        )
        operator7_grader = build_user_headers("operator-7", "QualityGrader")
        run = validate_success(
            api.create_grading_run(
                {"flock_id": ctx["flock"]["id"], "grade": "A", "eggs_to_grade": 240},
                operator7_grader,
            ),
            201,
        )
        validate_success(
            api.submit_grading_run(
                run["id"], grading_submit_payload(large_count=240), operator7_grader
            )
        )

        operator7_qa = build_user_headers("operator-7", "QAManager")
        resp = api.confirm_grading_run(run["id"], operator7_qa)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        after = validate_success(api.get_grading_run(run["id"], QA_MANAGER))
        assert after["status"] == "SUBMITTED"
