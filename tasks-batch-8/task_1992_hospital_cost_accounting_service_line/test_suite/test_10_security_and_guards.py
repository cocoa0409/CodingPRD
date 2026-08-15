"""Auth context, RBAC denials, OCC, and guard-rail errors (PRD §2.1, §2.9, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_case,
    create_draft_cost_model,
    create_overhead_center,
    create_service_line,
    setup_case_with_lines,
    setup_ortho_tdabc,
    validate_error,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]
SLM = TEST_USERS["service_line_manager_headers"]


class TestAuthContext:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        operator's capacity."
        PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api.list_service_lines({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbac:
    def test_cost_analyst_cannot_approve_cost_model(self, api):
        """PRD §3.2: "Approval is the `FinanceController`'s gate and moves the
        model `DRAFT → ACTIVE`."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS`; the per-endpoint role
        assignments appear in §4."

        Design: Corner/rbac/cost_analyst_cannot_approve_cost_model
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        model = create_draft_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")

        resp = api.approve_cost_model(model["id"], CA)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_finance_controller_cannot_create_case(self, api):
        """PRD §3.3: "Case capture is the `CostAnalyst`'s daily work."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS`; the per-endpoint role
        assignments appear in §4."

        Design: Corner/rbac/finance_controller_cannot_create_case
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        resp = api.create_case(
            {
                "service_line_id": sl["id"],
                "physician_id": "x",
                "drg_id": "y",
                "cost_model_id": "z",
                "period": "2026-08",
                "expected_reimbursement": 1.00,
            },
            FC,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_service_line_manager_read_only(self, api):
        """PRD §2.1: "A `ServiceLineManager` is a read-only consumer of entity
        data and reports."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS`; the per-endpoint role
        assignments appear in §4."

        Design: Corner/rbac/service_line_manager_read_only
        """
        resp = api.create_service_line(
            {"name": "Sneaky", "code": "SNEAK", "base_direct_cost": 1.00,
             "budgeted_volume": 1},
            SLM,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestOcc:
    def test_error_stale_model_version_occ_412(self, api):
        """PRD §2.9: "If that value no longer matches the model's current
        `version` — because another writer has advanced the model in the
        meantime, whether by approving a model, applying an earlier refresh, or
        any other version-advancing mutation — the request is rejected with
        `ERR_STALE_MODEL_VERSION` and HTTP status 412, and no change is applied."

        Design: Corner/errors/error_stale_model_version_occ_412
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00)
        case = setup_case_with_lines(scenario, [100])
        # The version observed at case creation (1) is stale: approving the model
        # advanced it to 2.
        stale_version = scenario["model_version"] - 1
        resp = api.post_case(case["id"], {"expected_model_version": stale_version}, CA)
        validate_error(resp, ApiErrorId.ERR_STALE_MODEL_VERSION, expected_status=412)


class TestGuardRails:
    def test_error_physician_has_open_cases(self, api):
        """PRD §3.1: "A physician may be deactivated — `ACTIVE` to `INACTIVE` —
        only while no `DRAFT` or `POSTED` case references them, else
        `ERR_PHYSICIAN_HAS_OPEN_CASES`; reactivation returns an `INACTIVE`
        physician to `ACTIVE` without preconditions."

        Design: Corner/errors/error_physician_has_open_cases
        """
        scenario = setup_ortho_tdabc()
        # DRAFT case owned by the scenario physician blocks deactivation.
        create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        resp = api.deactivate_physician(scenario["physician"]["id"], FC)
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_HAS_OPEN_CASES)

    def test_error_cost_center_in_use_on_archive(self, api):
        """PRD §3.1: "Archiving a cost center is refused with
        `ERR_COST_CENTER_IN_USE` when any cost model other than a `SUPERSEDED` or
        `ARCHIVED` one references the center as its overhead pool, or when any
        activity line on a `DRAFT` or `POSTED` case references it."

        Design: Corner/errors/error_cost_center_in_use_on_archive
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        # DRAFT model references the center as its overhead pool.
        create_draft_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")

        resp = api.archive_cost_center(cc_periop["id"], FC)
        validate_error(resp, ApiErrorId.ERR_COST_CENTER_IN_USE)
