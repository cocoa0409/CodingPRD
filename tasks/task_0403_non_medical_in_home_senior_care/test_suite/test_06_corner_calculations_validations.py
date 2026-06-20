"""Breadth coverage of calculations and cross-entity validations (queue B: Corner).

Covers live-in per-day charge, voided mileage exclusion, duplicate-match,
clock-in client-state gate, mark-paid claim gate, depart-without-match, and
covered_pct range validation.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, setup_schedulable_scenario, create_agency,
    create_active_caregiver, create_active_client, create_client,
    create_published_plan, create_active_match, create_caregiver,
    schedule_visit, clock_in_visit, clock_out_visit,
    create_in_progress_visit, create_completed_visit,
    open_invoice, finalize_invoice, get_invoice,
    setup_submitted_claim,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# section: calculations
# ---------------------------------------------------------------------------
class TestCalculations:
    def test_live_in_visit_charge_per_started_day(self, api):
        """PRD §3.6: "For a LIVE_IN visit, the system counts the number of started 24-hour
        blocks by dividing billable_minutes by 1440 and rounding up to the next whole
        block, then multiplies that count of started days by the agency's live_in_day_rate
        and rounds half-up to 2 decimal places, ignoring any per-hour rate."

        Design: Corner/calculations/live_in_visit_charge_per_started_day
        """
        s = setup_schedulable_scenario(
            caregiver_overrides={"max_weekly_hours": 200},
            client_overrides={"requires_live_in": True})
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-02T12:00:00Z",
            "2026-06-01T09:00:00Z", billing_mode="LIVE_IN")
        done = validate_success(api.clock_out(
            v["id"], {"event_at": "2026-06-02T11:00:00Z"},
            make_caregiver_headers(cg["id"])))
        # 26h -> 1560 billable min -> ceil(1560/1440)=2 started days * 250 = 500.00.
        assert done["billable_minutes"] == 1560, \
            f"26h should give 1560 billable minutes, got {done['billable_minutes']}"
        assert done["visit_charge"] == pytest.approx(500.00, abs=0.01), \
            f"LIVE_IN charge should be 500.00 (2 days * 250), got {done['visit_charge']}"

    def test_voided_mileage_excluded_from_total(self, api):
        """PRD §3.8: "A Scheduler or AgencyAdmin may void a mileage entry, advancing its
        status from RECORDED to VOIDED, and VOIDED entries are excluded from all invoice
        mileage totals."

        Design: Corner/calculations/voided_mileage_excluded_from_total
        """
        set_clock("2026-06-01T07:00:00Z")
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z", "2026-06-01T09:00:00Z")
        cg_headers = make_caregiver_headers(cg["id"])
        me_keep = validate_success(api.create_mileage(
            v["id"], {"miles": 10, "purpose": "Keep"}, cg_headers), expected_status=201)
        me_void = validate_success(api.create_mileage(
            v["id"], {"miles": 10, "purpose": "Void"}, cg_headers), expected_status=201)
        clock_out_visit(v["id"], cg["id"], "2026-06-01T11:00:00Z")
        validate_success(api.void_mileage(me_void["id"], SCHEDULER))
        inv = open_invoice(s["agency"]["id"], cg["id"], cl["id"],
                           "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        finalized = validate_success(api.finalize_invoice(inv["id"], BILLING))
        # 10 * 0.70 = 7.00 each; only one counts -> mileage_total 7.00.
        assert me_keep["line_charge"] == pytest.approx(7.00, abs=0.01)
        assert finalized["mileage_total"] == pytest.approx(7.00, abs=0.01), \
            f"voided entry should be excluded -> 7.00, got {finalized['mileage_total']}"
        # Labor: 2h HOURLY -> 60.00; invoice_total 67.00.
        assert finalized["invoice_total"] == pytest.approx(67.00, abs=0.01)


# ---------------------------------------------------------------------------
# section: validations
# ---------------------------------------------------------------------------
class TestValidations:
    def test_duplicate_active_match_rejected(self, api):
        """PRD §3.4: "Fourth, no other ACTIVE match may already exist for this same
        caregiver_id and client_id pair, otherwise ERR_DUPLICATE_ACTIVE_MATCH."

        Design: Corner/validations/duplicate_active_match_rejected
        """
        agency = create_agency()
        cg = create_active_caregiver(agency["id"])
        cl = create_active_client(agency["id"])
        create_active_match(cg["id"], cl["id"], is_primary=False)
        mt2 = validate_success(api.create_match({
            "caregiver_id": cg["id"], "client_id": cl["id"]
        }, SCHEDULER), expected_status=201)
        resp = api.transition_match(mt2["id"], {"action": "ACTIVATE"}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_MATCH.value)
        fresh = validate_success(api.get_match(mt2["id"], SCHEDULER))
        assert fresh["match_status"] == "PROPOSED"

    def test_clockin_client_not_active_rejected(self, api):
        """PRD §3.6: "the client's status must be ACTIVE (otherwise
        ERR_CLIENT_NOT_SCHEDULABLE)".

        Design: Corner/validations/clockin_client_not_active_rejected
        """
        agency = create_agency()
        cg = create_active_caregiver(agency["id"])
        cl = create_client(agency["id"])  # stays INTAKE
        plan = create_published_plan(cl["id"])
        # Match can be activated while client is INTAKE.
        create_active_match(cg["id"], cl["id"], is_primary=True)
        v = schedule_visit(cg["id"], cl["id"], plan["id"],
                           "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        resp = api.clock_in(v["id"], {"event_at": "2026-06-01T09:00:00Z"},
                            make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_SCHEDULABLE.value)
        fresh = validate_success(api.get_visit(v["id"], SCHEDULER))
        assert fresh["status"] == "SCHEDULED"

    def test_mark_paid_blocked_while_claim_submitted(self, api):
        """PRD §3.10: "If any claim is assigned to this invoice, that claim must already be
        APPROVED or PAID, otherwise the payment is blocked with ERR_CLAIM_NOT_RESOLVED."

        Design: Corner/validations/mark_paid_blocked_while_claim_submitted
        """
        s = setup_submitted_claim()
        inv = s["invoice"]
        resp = api.transition_invoice(inv["id"], {"action": "MARK_PAID"}, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_RESOLVED.value)
        fresh = get_invoice(inv["id"])
        assert fresh["status"] == "ISSUED"

    def test_depart_without_active_match_rejected(self, api):
        """PRD §3.6: "Departure requires that the visit is SCHEDULED, otherwise
        ERR_INVALID_STATE, and that an ACTIVE match exists for the visit's caregiver_id and
        client_id, otherwise ERR_NO_ACTIVE_MATCH."

        Design: Corner/validations/depart_without_active_match_rejected
        """
        agency = create_agency()
        cg = create_active_caregiver(agency["id"])
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        # Only a PROPOSED match (never activated).
        validate_success(api.create_match({
            "caregiver_id": cg["id"], "client_id": cl["id"]
        }, SCHEDULER), expected_status=201)
        v = schedule_visit(cg["id"], cl["id"], plan["id"],
                           "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        resp = api.transition_visit(v["id"], {"action": "DEPART"},
                                    make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_MATCH.value)
        fresh = validate_success(api.get_visit(v["id"], SCHEDULER))
        assert fresh["status"] == "SCHEDULED"

    def test_covered_pct_out_of_range_rejected(self, api):
        """PRD §2.7: "A claim's covered_pct must be at least 0 and at most 1."

        Design: Corner/validations/covered_pct_out_of_range_rejected
        """
        from test_helpers import setup_issued_invoice_single_visit
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        resp = api.create_claim({
            "client_id": s["client"]["id"], "invoice_id": inv["id"],
            "insurer_name": "Ins", "policy_number": "P1",
            "covered_pct": 1.5, "daily_benefit_max": 500, "covered_days": 5,
            "expected_invoice_version": inv["version"],
        }, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
