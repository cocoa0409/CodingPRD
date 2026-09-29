"""
One method per endpoint declared in PRD.md §4.

Every path is served under the `/portfolio` prefix, with the sole exception of
the logical-clock endpoint `POST /_clock/set_current_utc` (§4 preamble).
"""

from prd_bench_local_runner.testing import GenericApiClient


class GroundLeaseApiClient(GenericApiClient):
    # ---------------- logical clock (§2.5) ----------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---------------- lessees (§3.1) ----------------
    def create_lessee(self, payload, headers):
        return self._request("POST", "/portfolio/lessees", payload, headers)

    def get_lessee(self, lessee_id, headers):
        return self._request("GET", f"/portfolio/lessees/{lessee_id}", None, headers)

    def list_lessees(self, headers, params=None):
        return self._request("GET", "/portfolio/lessees", params, headers)

    # ---------------- leases (§3.1) ----------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/portfolio/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/portfolio/leases/{lease_id}", None, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/portfolio/leases", params, headers)

    def amend_terms(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/terms", payload, headers
        )

    def file_insurance_endorsement(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/insurance-endorsements", payload, headers
        )

    def post_rent_charge(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/rent-charges", payload, headers
        )

    def get_rent_summary(self, lease_id, headers):
        return self._request(
            "GET", f"/portfolio/leases/{lease_id}/rent-summary", None, headers
        )

    # ---------------- leasehold mortgages (§3.2) ----------------
    def record_mortgage(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/leasehold-mortgages", payload, headers
        )

    def get_mortgage(self, mortgage_id, headers):
        return self._request(
            "GET", f"/portfolio/leasehold-mortgages/{mortgage_id}", None, headers
        )

    def list_mortgages(self, headers, params=None):
        return self._request("GET", "/portfolio/leasehold-mortgages", params, headers)

    def elect_new_lease(self, mortgage_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/leasehold-mortgages/{mortgage_id}/new-lease-election",
            payload,
            headers,
        )

    # ---------------- rent revaluations (§3.3) ----------------
    def open_revaluation(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/rent-revaluations", payload, headers
        )

    def get_revaluation(self, revaluation_id, headers):
        return self._request(
            "GET", f"/portfolio/rent-revaluations/{revaluation_id}", None, headers
        )

    def list_revaluations(self, headers, params=None):
        return self._request("GET", "/portfolio/rent-revaluations", params, headers)

    def lodge_appraisal(self, revaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/rent-revaluations/{revaluation_id}/appraisals",
            payload,
            headers,
        )

    def exchange_proposals(self, revaluation_id, headers):
        return self._request(
            "POST", f"/portfolio/rent-revaluations/{revaluation_id}/exchange", {}, headers
        )

    def open_next_round(self, revaluation_id, headers):
        return self._request(
            "POST", f"/portfolio/rent-revaluations/{revaluation_id}/rounds", {}, headers
        )

    def settle_revaluation(self, revaluation_id, headers):
        return self._request(
            "POST", f"/portfolio/rent-revaluations/{revaluation_id}/settle", {}, headers
        )

    def refer_to_arbitration(self, revaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/rent-revaluations/{revaluation_id}/arbitration-referrals",
            payload,
            headers,
        )

    def get_appraisal(self, appraisal_id, headers):
        return self._request(
            "GET", f"/portfolio/appraisal-submissions/{appraisal_id}", None, headers
        )

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/portfolio/appraisal-submissions", params, headers)

    def get_arbitration(self, arbitration_id, headers):
        return self._request(
            "GET", f"/portfolio/arbitrations/{arbitration_id}", None, headers
        )

    def list_arbitrations(self, headers, params=None):
        return self._request("GET", "/portfolio/arbitrations", params, headers)

    def render_award(self, arbitration_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/arbitrations/{arbitration_id}/award", payload, headers
        )

    # ---------------- percentage rent statements (§3.4) ----------------
    def file_statement(self, payload, headers):
        return self._request(
            "POST", "/portfolio/percentage-rent-statements", payload, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/portfolio/percentage-rent-statements/{statement_id}", None, headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/percentage-rent-statements", params, headers
        )

    def assess_statement(self, statement_id, headers):
        return self._request(
            "POST",
            f"/portfolio/percentage-rent-statements/{statement_id}/assess",
            {},
            headers,
        )

    def audit_statement(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/percentage-rent-statements/{statement_id}/audit",
            payload,
            headers,
        )

    # ---------------- alteration requests (§3.5) ----------------
    def create_alteration(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/alteration-requests", payload, headers
        )

    def get_alteration(self, alteration_id, headers):
        return self._request(
            "GET", f"/portfolio/alteration-requests/{alteration_id}", None, headers
        )

    def list_alterations(self, headers, params=None):
        return self._request("GET", "/portfolio/alteration-requests", params, headers)

    def decide_alteration(self, alteration_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/alteration-requests/{alteration_id}/decision",
            payload,
            headers,
        )

    def revoke_alteration_approval(self, alteration_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/alteration-requests/{alteration_id}/revoke-approval",
            payload,
            headers,
        )

    # ---------------- transfer requests (§3.6) ----------------
    def create_transfer(self, payload, headers):
        return self._request("POST", "/portfolio/transfer-requests", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"/portfolio/transfer-requests/{transfer_id}", None, headers
        )

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/portfolio/transfer-requests", params, headers)

    def decide_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/transfer-requests/{transfer_id}/decision", payload, headers
        )

    def pay_transfer_fee(self, transfer_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/transfer-requests/{transfer_id}/fee-payments",
            payload,
            headers,
        )

    # ---------------- default notices (§3.7) ----------------
    def serve_default_notice(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/default-notices", payload, headers
        )

    def get_default_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/portfolio/default-notices/{notice_id}", None, headers
        )

    def list_default_notices(self, headers, params=None):
        return self._request("GET", "/portfolio/default-notices", params, headers)

    def lessee_cure(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/default-notices/{notice_id}/lessee-cure", payload, headers
        )

    def mortgagee_cure(self, notice_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/default-notices/{notice_id}/mortgagee-cure",
            payload,
            headers,
        )

    def terminate_lease(self, notice_id, headers):
        return self._request(
            "POST", f"/portfolio/default-notices/{notice_id}/terminate", {}, headers
        )

    # ---------------- loss events (§3.8) ----------------
    def report_loss_event(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/loss-events", payload, headers
        )

    def get_loss_event(self, loss_event_id, headers):
        return self._request(
            "GET", f"/portfolio/loss-events/{loss_event_id}", None, headers
        )

    def list_loss_events(self, headers, params=None):
        return self._request("GET", "/portfolio/loss-events", params, headers)

    def adjust_loss_event(self, loss_event_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/loss-events/{loss_event_id}/adjust", payload, headers
        )

    def elect_loss_outcome(self, loss_event_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/loss-events/{loss_event_id}/election", payload, headers
        )

    def allocate_proceeds(self, loss_event_id, headers):
        return self._request(
            "POST", f"/portfolio/loss-events/{loss_event_id}/allocate", {}, headers
        )

    def rescind_allocation(self, loss_event_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/loss-events/{loss_event_id}/rescind-allocation",
            payload,
            headers,
        )

    # ---------------- reversion assessments (§3.9) ----------------
    def open_reversion_assessment(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/leases/{lease_id}/reversion-assessments", payload, headers
        )

    def get_reversion_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/portfolio/reversion-assessments/{assessment_id}", None, headers
        )

    def list_reversion_assessments(self, headers, params=None):
        return self._request("GET", "/portfolio/reversion-assessments", params, headers)

    def record_inspection(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/reversion-assessments/{assessment_id}/inspection",
            payload,
            headers,
        )

    def apply_holdback(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/reversion-assessments/{assessment_id}/holdback",
            payload,
            headers,
        )

    def close_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/portfolio/reversion-assessments/{assessment_id}/close", {}, headers
        )

    # ---------------- estoppel certificates (§3.2) ----------------
    def issue_estoppel(self, payload, headers):
        return self._request(
            "POST", "/portfolio/estoppel-certificates", payload, headers
        )

    def get_estoppel(self, certificate_id, headers):
        return self._request(
            "GET", f"/portfolio/estoppel-certificates/{certificate_id}", None, headers
        )

    def list_estoppels(self, headers, params=None):
        return self._request("GET", "/portfolio/estoppel-certificates", params, headers)

    # ---------------- administration sweep (§3.10) ----------------
    def run_administration(self, headers):
        return self._request("POST", "/portfolio/administration-runs", {}, headers)
