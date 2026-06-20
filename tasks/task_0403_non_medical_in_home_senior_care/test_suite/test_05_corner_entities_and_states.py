"""Breadth coverage of entity creation and state-machine guards (queue B: Corner).

Covers creation defaults, required-field and type validation, parent existence,
idempotency / precondition / invalid-transition guards across the lifecycles.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_agency, create_caregiver, create_client, create_active_caregiver,
    create_active_client, create_published_plan, create_active_match,
    setup_issued_invoice_single_visit, set_clock, setup_schedulable_scenario,
    create_in_progress_visit, schedule_visit,
    open_invoice, finalize_invoice, assign_claim,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# section: entities
# ---------------------------------------------------------------------------
class TestEntityCreation:
    def test_create_caregiver_returns_pending_applicant_defaults(self, api):
        """PRD §3.2: "A newly registered caregiver always begins with background_tier of
        PENDING and employment_status of APPLICANT."
        PRD §3.2: "An optional max_weekly_hours caps how many billable hours may be
        scheduled for that caregiver within any one ISO week and defaults to 50."

        Design: Corner/entities/create_caregiver_returns_pending_applicant_defaults
        """
        agency = create_agency()
        cg = validate_success(api.create_caregiver({
            "agency_id": agency["id"], "full_name": "CG", "hire_state_code": "CA"
        }, ADMIN), expected_status=201)
        assert cg["background_tier"] == "PENDING"
        assert cg["employment_status"] == "APPLICANT"
        assert cg["max_weekly_hours"] == 50

    def test_get_caregiver_not_found(self, api):
        """PRD §2.5: "The request is rejected at the first identifier that does not
        resolve, and the error reflects which kind of resource was missing:
        ERR_AGENCY_NOT_FOUND, ERR_CAREGIVER_NOT_FOUND ... All of these existence failures
        carry HTTP status 404."

        Design: Corner/entities/get_caregiver_not_found
        """
        resp = api.get_caregiver(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_NOT_FOUND.value)

    def test_create_visit_missing_required_field(self, api):
        """PRD §2.6: "Fourth is request well-formedness — required fields present,
        enumerated values legal ... failing which the request is rejected with
        ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/create_visit_missing_required_field
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        # billing_mode omitted.
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"],
            "scheduled_start": "2026-06-01T09:00:00Z",
            "scheduled_end": "2026-06-01T11:00:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_visit_end_before_start_invalid(self, api):
        """PRD §2.7: "A visit's scheduled_end must be strictly later than its
        scheduled_start."

        Design: Corner/entities/create_visit_end_before_start_invalid
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T11:00:00Z",
            "scheduled_end": "2026-06-01T11:00:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_caregiver_unknown_agency_not_found(self, api):
        """PRD §2.5: "the system validates existence left to right: the agency first ...
        The request is rejected at the first identifier that does not resolve, and the
        error reflects which kind of resource was missing: ERR_AGENCY_NOT_FOUND".

        Design: Corner/entities/create_caregiver_unknown_agency_not_found
        """
        resp = api.create_caregiver({
            "agency_id": NON_EXISTENT_UUID, "full_name": "CG", "hire_state_code": "CA"
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_FOUND.value)

    def test_system_fields_generated_on_create(self, api):
        """PRD §3.3: "A client opens in INTAKE status with a continuity_score of 0."

        Design: Corner/entities/system_fields_generated_on_create
        """
        agency = create_agency()
        cl = validate_success(api.create_client({
            "agency_id": agency["id"], "full_name": "CL", "residence_state_code": "CA"
        }, ADMIN), expected_status=201)
        assert cl["status"] == "INTAKE"
        assert cl["continuity_score"] == 0


# ---------------------------------------------------------------------------
# section: state_machines
# ---------------------------------------------------------------------------
class TestStateMachineGuards:
    def test_clear_background_twice_returns_not_pending(self, api):
        """PRD §3.2: "Clearing background screening (action of CLEAR_BACKGROUND) requires
        that the caregiver's background_tier is currently PENDING; if it is not, the
        request is rejected with ERR_BACKGROUND_NOT_PENDING."

        Design: Corner/state_machines/clear_background_twice_returns_not_pending
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        validate_success(api.transition_caregiver(
            cg["id"], {"action": "CLEAR_BACKGROUND", "target_tier": "TIER_1"}, ADMIN))
        resp = api.transition_caregiver(
            cg["id"], {"action": "CLEAR_BACKGROUND", "target_tier": "TIER_2"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_NOT_PENDING.value)

    def test_activate_caregiver_without_background_cleared(self, api):
        """PRD §3.2: "Activation (action of ACTIVATE) is the cross-dimension guard: it
        succeeds only when background_tier is one of TIER_1, TIER_2, or TIER_3, otherwise
        it is rejected with ERR_BACKGROUND_NOT_CLEARED."

        Design: Corner/state_machines/activate_caregiver_without_background_cleared
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])  # still PENDING / APPLICANT
        resp = api.transition_caregiver(cg["id"], {"action": "ACTIVATE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_NOT_CLEARED.value)
        fresh = validate_success(api.get_caregiver(cg["id"], ADMIN))
        assert fresh["employment_status"] == "APPLICANT"

    def test_finalize_invoice_twice_returns_not_draft(self, api):
        """PRD §3.9: "Finalizing an invoice (the DRAFT → ISSUED transition ...) ... It
        requires that the invoice is DRAFT, otherwise ERR_INVOICE_NOT_DRAFT".

        Design: Corner/state_machines/finalize_invoice_twice_returns_not_draft
        """
        s = setup_issued_invoice_single_visit()
        resp = api.finalize_invoice(s["invoice"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DRAFT.value)

    def test_finalize_invoice_no_billable_visits(self, api):
        """PRD §3.9: "and that at least one COMPLETED visit falls inside the half-open
        window from period_start up to period_end for the invoice's caregiver_id and
        client_id, otherwise ERR_NO_BILLABLE_VISITS."

        Design: Corner/state_machines/finalize_invoice_no_billable_visits
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        cl = create_client(agency["id"])
        inv = open_invoice(agency["id"], cg["id"], cl["id"],
                           "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        resp = api.finalize_invoice(inv["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_VISITS.value)

    def test_clockout_when_not_in_progress(self, api):
        """PRD §3.6: "Clock-out requires that the visit is IN_PROGRESS, otherwise
        ERR_VISIT_NOT_IN_PROGRESS".

        Design: Corner/state_machines/clockout_when_not_in_progress
        """
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = schedule_visit(cg["id"], cl["id"], plan["id"],
                           "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        resp = api.clock_out(v["id"], {"event_at": "2026-06-01T10:00:00Z"},
                             make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_IN_PROGRESS.value)

    def test_clockout_event_before_clockin_invalid_window(self, api):
        """PRD §3.6: "and that the supplied event_at is strictly later than clock_in_at,
        otherwise ERR_INVALID_CLOCK_WINDOW."

        Design: Corner/state_machines/clockout_event_before_clockin_invalid_window
        """
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T10:00:00Z")
        resp = api.clock_out(v["id"], {"event_at": "2026-06-01T10:00:00Z"},
                             make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CLOCK_WINDOW.value)
        fresh = validate_success(api.get_visit(v["id"], SCHEDULER))
        assert fresh["status"] == "IN_PROGRESS"

    def test_approve_claim_not_submitted_invalid_state(self, api):
        """PRD §3.11: "Approving a submitted claim (action of APPROVE, SUBMITTED →
        APPROVED) requires the claim to be SUBMITTED, otherwise ERR_INVALID_STATE".

        Design: Corner/state_machines/approve_claim_not_submitted_invalid_state
        """
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        claim = assign_claim(s["client"]["id"], inv["id"], inv["version"])  # DRAFT
        resp = api.transition_claim(claim["id"], {"action": "APPROVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        fresh = validate_success(api.get_claim(claim["id"], BILLING))
        assert fresh["status"] == "DRAFT"

    def test_visit_reset_from_already_scheduled_invalid(self, api):
        """PRD §3.6: "Resetting a visit (action of RESET) is permitted from EN_ROUTE or
        IN_PROGRESS, otherwise ERR_INVALID_STATE".

        Design: Corner/state_machines/visit_reset_from_already_scheduled_invalid
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        v = schedule_visit(cg["id"], cl["id"], plan["id"],
                           "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        resp = api.transition_visit(v["id"], {"action": "RESET"}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        fresh = validate_success(api.get_visit(v["id"], SCHEDULER))
        assert fresh["status"] == "SCHEDULED"
