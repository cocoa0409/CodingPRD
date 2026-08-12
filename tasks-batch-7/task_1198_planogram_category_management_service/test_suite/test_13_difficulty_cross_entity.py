"""Difficulty: cross_entity_state_dependency — submit gated by category open; schedule gated by planogram approved."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_reset_project_payload,
    create_store_payload,
    make_category_captain_headers,
    setup_draft_planogram_with_line,
    validate_error,
    validate_success,
)


class TestPlanogramSubmitGatedByCategoryOpen:
    def test_submit_rejected_when_category_locked(self, api, category_manager_headers):
        """PRD §3.5: "Submission is a `CategoryCaptain` action — the retailer
        deliberately delegates authorship — and the category must be `OPEN`,
        else `ERR_CATEGORY_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/planogram_submit_gated_by_category_open
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line()
        rid, cid, pgid, sid = retailer["id"], category["id"], pg["id"], supplier["id"]
        # Lock the category — even though PG is a valid DRAFT, submission must fail.
        validate_success(api.lock_category(rid, cid, category_manager_headers))
        captain_headers = make_category_captain_headers(sid)
        resp = api.submit_planogram(rid, cid, pgid, captain_headers)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_LOCKED)

    def test_submit_rejected_when_category_locked_state_unchanged(self, api, category_manager_headers):
        """PRD §3.1: "while a category is `LOCKED`, no new product may be cut
        in under it and no planogram may be submitted for review under it —
        any attempt at either is rejected with `ERR_CATEGORY_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/planogram_submit_gated_by_category_open
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line()
        rid, cid, pgid, sid = retailer["id"], category["id"], pg["id"], supplier["id"]
        validate_success(api.lock_category(rid, cid, category_manager_headers))
        captain_headers = make_category_captain_headers(sid)
        validate_error(
            api.submit_planogram(rid, cid, pgid, captain_headers),
            ApiErrorId.ERR_CATEGORY_LOCKED,
        )
        # Planogram state must not have advanced
        pg_now = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))
        assert pg_now["status"] == "DRAFT"


class TestResetScheduleGatedByPlanogramApproved:
    def test_schedule_rejected_when_planogram_is_draft(self, api, reset_coordinator_headers):
        """PRD §3.9: "Scheduling also re-verifies that the referenced planogram
        is `APPROVED` or `ACTIVE`; a project pointing at anything else is
        rejected with `ERR_VALIDATION`."
        PRD §3.5: "A `CategoryCaptain` may return an `IN_REVIEW` planogram to
        `DRAFT` at will, and may likewise return an `APPROVED` planogram to
        `DRAFT` provided the planogram has never been `ACTIVE`"."

        Design: Difficulty/cross_entity_state_dependency/reset_project_schedule_gated_by_planogram_approved
        """
        # Build an APPROVED planogram so creation succeeds, then return it to
        # DRAFT before scheduling so the schedule-time check fires.
        from test_helpers import setup_approved_planogram
        retailer, category, supplier, product, pg, line = setup_approved_planogram()
        rid, cid, pgid, sid = retailer["id"], category["id"], pg["id"], supplier["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pg["id"], store["id"]),
                reset_coordinator_headers,
            ),
            expected_status=201,
        )
        # Captain returns planogram to DRAFT (it has never been ACTIVE)
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.return_planogram_to_draft(rid, cid, pgid, captain_headers))
        # Now schedule: re-verification must reject with ERR_VALIDATION.
        resp = api.schedule_reset_project(
            rid, cid, rp["id"], {"expected_reset_project_version": rp["version"]}, reset_coordinator_headers
        )
        # PRD §3.9 explicitly pins ERR_VALIDATION for this failure mode.
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_schedule_succeeds_when_planogram_approved(self, api, reset_coordinator_headers):
        """PRD §3.9: "Scheduling — moving a project from `PROPOSED` to
        `SCHEDULED` — belongs to the `ResetCoordinator` and is OCC-guarded by
        `expected_reset_project_version`. ... Scheduling also re-verifies that
        the referenced planogram is `APPROVED` or `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/reset_project_schedule_gated_by_planogram_approved
        """
        from test_helpers import setup_approved_planogram
        retailer, category, supplier, product, pg, line = setup_approved_planogram()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pg["id"], store["id"]),
                reset_coordinator_headers,
            ),
            expected_status=201,
        )
        resp = api.schedule_reset_project(
            rid, cid, rp["id"], {"expected_reset_project_version": rp["version"]}, reset_coordinator_headers
        )
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
