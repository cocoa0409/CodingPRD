"""Breadth coverage of RBAC, listing/pagination, not-found errors, and the
cross-cutting concurrency / derived-field layers (queue B: Corner).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    set_clock, create_agency, create_caregiver, create_client,
    create_active_caregiver, create_active_client, create_published_plan,
    create_active_match, schedule_visit, create_in_progress_visit,
    create_completed_visit, open_invoice, finalize_invoice, get_invoice,
    assign_claim, submit_claim,
    setup_schedulable_scenario, setup_issued_invoice_single_visit,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]

# Anonymous headers: no X-User-ID / X-User-Role.
ANON = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# section: rbac
# ---------------------------------------------------------------------------
class TestRbac:
    def test_scheduler_cannot_create_caregiver(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted
        to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN_ROLE."
        PRD §4 endpoint table: POST /caregivers is authorized for AgencyAdmin only.

        Design: Corner/rbac/scheduler_cannot_create_caregiver
        """
        agency = create_agency()
        resp = api.create_caregiver({
            "agency_id": agency["id"], "full_name": "CG", "hire_state_code": "CA"
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_caregiver_cannot_finalize_invoice(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted
        to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN_ROLE."
        PRD §4 endpoint table: POST /invoices/{id}/finalize is authorized for
        BillingClerk, AgencyAdmin.

        Design: Corner/rbac/caregiver_cannot_finalize_invoice
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        cl = create_client(agency["id"])
        inv = open_invoice(agency["id"], cg["id"], cl["id"],
                           "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        resp = api.finalize_invoice(inv["id"], make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, the request is rejected
        with ERR_MISSING_AUTH."

        Design: Corner/rbac/missing_auth_header_rejected
        """
        resp = api.list_caregivers(ANON)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ---------------------------------------------------------------------------
# section: endpoints
# ---------------------------------------------------------------------------
class TestListingAndComputed:
    def test_list_visits_paginated_envelope(self, api):
        """PRD §2.3: "The limit parameter caps the number of items returned ... Every list
        response includes limit, offset, total_count, and has_more inside the meta object
        of the envelope."

        Design: Corner/endpoints/list_visits_paginated_envelope
        """
        set_clock("2026-06-01T07:00:00Z")
        agency = create_agency()
        cg = create_caregiver(agency["id"], max_weekly_hours=50)
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        schedule_visit(cg["id"], cl["id"], plan["id"],
                       "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        schedule_visit(cg["id"], cl["id"], plan["id"],
                       "2026-06-02T09:00:00Z", "2026-06-02T11:00:00Z")
        resp = api.list_visits(SCHEDULER,
                               params={"caregiver_id": cg["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
        assert meta["has_more"] is True, f"has_more should be True, got {meta['has_more']}"
        assert len(data) == 1, f"limit=1 should return 1 item, got {len(data)}"

    def test_list_care_plans_subresource_for_client(self, api):
        """PRD §2.3: "Unless an endpoint states otherwise, list results are sorted by their
        creation timestamp in ascending order. Every list response includes limit, offset,
        total_count, and has_more inside the meta object of the envelope."
        PRD §3.3: "Care is organized through a CarePlan, a sub-resource of a client".

        Design: Corner/endpoints/list_care_plans_subresource_for_client
        """
        agency = create_agency()
        cl = create_client(agency["id"])
        validate_success(api.create_care_plan(
            cl["id"], {"title": "P1"}, SCHEDULER), expected_status=201)
        validate_success(api.create_care_plan(
            cl["id"], {"title": "P2"}, SCHEDULER), expected_status=201)
        resp = api.list_care_plans(cl["id"], SCHEDULER)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, \
            f"client should have 2 care plans, got {meta['total_count']}"

    def test_care_task_count_increments_and_decrements(self, api):
        """PRD §3.3: "Adding a task increments the parent plan's task_count. Removing a
        task sets its status to REMOVED and decrements the parent's task_count; the
        task_count is, by definition, the number of non-REMOVED tasks on the plan, so
        removed tasks are excluded from it."

        Design: Corner/endpoints/care_task_count_increments_and_decrements
        """
        agency = create_agency()
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        validate_success(api.create_care_task(
            plan["id"], {"category": "ADL", "name": "Bathing"}, SCHEDULER),
            expected_status=201)
        t2 = validate_success(api.create_care_task(
            plan["id"], {"category": "IADL", "name": "Grocery",
                         "requires_companion_errand": True}, SCHEDULER),
            expected_status=201)
        removed = validate_success(api.delete_care_task(plan["id"], t2["id"], SCHEDULER))
        assert removed["status"] == "REMOVED"
        fresh_plan = validate_success(api.get_care_plan(plan["id"], SCHEDULER))
        assert fresh_plan["task_count"] == 1, \
            f"task_count should be 1 after removing one of two, got {fresh_plan['task_count']}"


# ---------------------------------------------------------------------------
# section: errors
# ---------------------------------------------------------------------------
class TestErrors:
    def test_invoice_not_found_on_get(self, api):
        """PRD §2.5: "The request is rejected at the first identifier that does not
        resolve, and the error reflects which kind of resource was missing: ...
        ERR_INVOICE_NOT_FOUND ... All of these existence failures carry HTTP status 404."

        Design: Corner/errors/invoice_not_found_on_get
        """
        resp = api.get_invoice(NON_EXISTENT_UUID, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# section: cross_cutting_complexity_layers
# ---------------------------------------------------------------------------
class TestConcurrencyAndDerived:
    def test_occ_stale_invoice_version_on_claim_assign(self, api):
        """PRD §2.9: "When expected_invoice_version does not equal the invoice's current
        version, the create is rejected with ERR_STALE_INVOICE_VERSION at HTTP 412. On a
        successful claim assignment the invoice's version is itself incremented by one, so
        a second assignment that reused the same observed version would then fail the
        check."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_claim_assign
        """
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        observed = inv["version"]
        claim1 = assign_claim(s["client"]["id"], inv["id"], observed)
        submit_claim(claim1["id"])  # bumps invoice version
        # Re-using the stale observed version must fail.
        resp = api.create_claim({
            "client_id": s["client"]["id"], "invoice_id": inv["id"],
            "insurer_name": "Ins2", "policy_number": "P2",
            "covered_pct": 0.60, "daily_benefit_max": 500, "covered_days": 5,
            "expected_invoice_version": observed,
        }, BILLING)
        validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION.value)

    def test_occ_correct_invoice_version_succeeds(self, api):
        """PRD §2.9: "A request that creates a claim must carry expected_invoice_version,
        and that value must equal the current version of the target invoice named by
        invoice_id."
        PRD §3.11: "A claim opens with a status of DRAFT and a covered_amount of 0."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_invoice_version_succeeds
        """
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        claim = validate_success(api.create_claim({
            "client_id": s["client"]["id"], "invoice_id": inv["id"],
            "insurer_name": "Ins", "policy_number": "P1",
            "covered_pct": 0.50, "daily_benefit_max": 500, "covered_days": 5,
            "expected_invoice_version": inv["version"],
        }, BILLING), expected_status=201)
        assert claim["status"] == "DRAFT"

    def test_continuity_score_recomputed_on_clockout(self, api):
        """PRD §3.7: "The second term is reliability: the count of completed visits divided
        by the count of terminal visits ... The final continuity_score weights the
        continuity ratio at 0.6 and reliability at 0.4 ... and rounds the result half-up to
        2 decimal places."

        Design: Corner/cross_cutting_complexity_layers/continuity_score_recomputed_on_clockout
        """
        set_clock("2026-06-01T07:00:00Z")
        s = setup_schedulable_scenario(caregiver_overrides={"max_weekly_hours": 50})
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v1 = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z", "2026-06-01T09:00:00Z")
        v2 = schedule_visit(cg["id"], cl["id"], plan["id"],
                            "2026-06-02T09:00:00Z", "2026-06-02T11:00:00Z")
        validate_success(api.transition_visit(v2["id"], {"action": "MARK_MISSED"}, SCHEDULER))
        validate_success(api.clock_out(
            v1["id"], {"event_at": "2026-06-01T11:00:00Z"},
            make_caregiver_headers(cg["id"])))
        fresh = validate_success(api.get_client(cl["id"], SCHEDULER))
        # 1 completed by primary (ratio 1), 1 missed -> reliability 1/2 = 0.5.
        # score = 0.6*1 + 0.4*0.5 = 0.80.
        assert fresh["continuity_score"] == pytest.approx(0.80, abs=0.001), \
            f"continuity_score should be 0.80, got {fresh['continuity_score']}"
