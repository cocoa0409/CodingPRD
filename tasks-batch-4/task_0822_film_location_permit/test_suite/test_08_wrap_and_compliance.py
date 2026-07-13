"""Wrap-close reconciliation, the deposit conserved quantity, compliance scoring, and submit boundary."""
import test_helpers as th
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId


class TestComplianceProvisionalVsFinal:
    def test_provisional_score_excludes_open_application(self, api):
        """PRD §3.8: "The PROVISIONAL variant is derived at read time whenever a production
        company is fetched, using only the counters currently persisted — that is, reflecting
        only applications that have already closed, and excluding any open application that has
        not yet wrapped."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_final
        """
        ctx = th.setup_wrap_requested_application(api, company_name="Beta Pictures")
        company = get_success_data(api.get_production_company(ctx["pc_id"], th.make_coordinator_headers()))
        assert company["compliance_score"] == 100

    def test_final_score_reflects_wrap_increments(self, api):
        """PRD §3.8: "If the actual_end_at is later than permitted_end_at, the owning
        ProductionCompany's late_wrap_count is incremented by one. If damage_cost_cents is
        greater than zero, the company's damage_incident_count is incremented by one."
        PRD §3.8: "A production company's compliance_score is a weighted standing figure derived
        from its three counters: starting at 100, subtract 10 points for each unit of
        late_wrap_count, 15 points for each unit of damage_incident_count, and 20 points for each
        unit of missed_notification_count, then clamp the result to the inclusive range from 0 to
        100."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_final
        """
        ctx = th.setup_wrap_requested_application(api, company_name="Beta2 Pictures")
        th.wrap_close(api, ctx["app_id"], ctx["officer_id"],
                      actual_end_at="2026-06-01T21:00:00Z", damages_reported=True, damage_cost_cents=5000)
        company = get_success_data(api.get_production_company(ctx["pc_id"], th.make_coordinator_headers()))
        assert company["late_wrap_count"] == 1
        assert company["damage_incident_count"] == 1
        assert company["compliance_score"] == 75


class TestDepositHeldConservation:
    def test_refund_and_penalty_computed_at_wrap_close(self, api):
        """PRD §3.8: "The overage is the time by which actual_end_at exceeds permitted_end_at,
        floored at zero seconds — if the shoot ended at or before its permitted end there is no
        overage."
        PRD §3.8: "The refund is then the deposit currently held minus what is owed: a gross
        refund equal to deposit_held_cents minus damage_cost_cents minus late_wrap_penalty_cents.
        deposit_refund_cents is stamped as that gross refund, but never below zero ..."

        Design: Difficulty/compensating_invariant/deposit_held_conservation
        """
        ctx = th.setup_wrap_requested_application(api, company_name="P9a Co")
        resp = api.wrap_close_application(
            ctx["app_id"],
            {"actual_end_at": "2026-06-01T18:00:00Z", "damages_reported": True, "damage_cost_cents": 2000},
            th.make_field_officer_headers(ctx["officer_id"]),
        )
        data = validate_success(resp, 200)
        assert data["late_wrap_penalty_cents"] == 0
        assert data["deposit_refund_cents"] == 6240

    def test_deposit_held_conserved_after_refund(self, api):
        """PRD §2.9: "deposit_held_cents is the running sum of DEPOSIT debit amounts minus the
        sum of REFUND credit amounts for the application — that is, the deposit money the city
        currently holds."
        PRD §3.8: "The system creates a REFUND LedgerEntry with direction CREDIT and amount_cents
        equal to deposit_refund_cents, and decrements deposit_held_cents by that same refund
        amount."

        Design: Difficulty/compensating_invariant/deposit_held_conservation
        """
        ctx = th.setup_wrap_requested_application(api, company_name="P9a2 Co")
        resp = api.wrap_close_application(
            ctx["app_id"],
            {"actual_end_at": "2026-06-01T18:00:00Z", "damages_reported": True, "damage_cost_cents": 2000},
            th.make_field_officer_headers(ctx["officer_id"]),
        )
        data = validate_success(resp, 200)
        # Paid 8240, refunded 6240, so 2000 remains held (== retained damage + penalty).
        assert data["deposit_held_cents"] == 2000


class TestSubmitZeroLocations:
    def test_submit_without_locations_rejected(self, api):
        """PRD §3.3: "Two preconditions gate a first submission: the application must have at
        least one LocationDetail — a submission against an application with zero locations is
        rejected with ERR_NO_LOCATIONS (HTTP 422) ..."

        Design: Difficulty/boundary_precision_check/submit_zero_locations_empty_set
        """
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="P6b", contact_email="6b@x.test", primary_contact="G")
        app = th.make_application(api, pc["id"], title="P6b", synopsis="x")
        resp = api.submit_application(app["id"], {}, th.make_production_company_headers(pc["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_LOCATIONS.value)

    def test_submit_without_locations_leaves_draft(self, api):
        """PRD §3.3: "Two preconditions gate a first submission: the application must have at
        least one LocationDetail — a submission against an application with zero locations is
        rejected with ERR_NO_LOCATIONS (HTTP 422) ..."

        Design: Difficulty/boundary_precision_check/submit_zero_locations_empty_set
        """
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="P6b2", contact_email="6b2@x.test", primary_contact="G2")
        app = th.make_application(api, pc["id"], title="P6b2", synopsis="x")
        api.submit_application(app["id"], {}, th.make_production_company_headers(pc["id"]))
        after = get_success_data(api.get_application(app["id"], th.make_coordinator_headers()))
        assert after["status"] == "DRAFT"


def test_wrap_request_deposit_unpaid(api):
    """PRD §3.8: "It carries one fiscal precondition: the deposit must have been paid, meaning
    the application's deposit_held_cents is at least its deposit_cents; if not, the wrap request
    is rejected with ERR_DEPOSIT_UNPAID (HTTP 402)."

    Design: Corner/validations/wrap_request_deposit_unpaid
    """
    ctx = th.setup_issued_application(api, company_name="Dep Co")  # ISSUED, no DEPOSIT paid
    resp = api.wrap_request_application(ctx["app_id"], {}, th.make_production_company_headers(ctx["pc_id"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNPAID.value)
