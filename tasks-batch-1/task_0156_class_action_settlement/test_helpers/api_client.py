"""API client: one method per endpoint defined in the PRD."""
import time

from requests.exceptions import ConnectionError as RequestsConnectionError
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # The runner restarts the server (per-test-server isolation) before every
        # test. The first request after a restart can race a stale keep-alive
        # socket left in the pooled session, surfacing as a BadStatusLine /
        # ConnectionError. Send `Connection: close` so no socket is reused, and
        # retry once on a connection-level failure (test_helpers-only; no impl or
        # assertion change).
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        last_exc = None
        for attempt in range(2):
            try:
                return super()._request(method, path, payload, hdrs, params)
            except RequestsConnectionError as exc:
                last_exc = exc
                self.session.close()
                time.sleep(0.1)
        raise last_exc
    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Settlement ───────────────────────────────────────────────────────
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def open_notice(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/open-notice", {}, headers
        )

    def open_claims(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/open-claims", {}, headers
        )

    def close_claims(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/close-claims", {}, headers
        )

    def begin_distribution(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/begin-distribution", {}, headers
        )

    def reconcile(self, settlement_id, expected_settlement_version, headers):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/reconcile",
            {"expected_settlement_version": expected_settlement_version},
            headers,
        )

    def close_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/close", {}, headers
        )

    def get_ledger_balance(self, settlement_id, headers):
        return self._request(
            "GET", f"/settlements/{settlement_id}/ledger-balance", headers=headers
        )

    def list_ledger_entries(self, settlement_id, headers, params=None):
        return self._request(
            "GET",
            f"/settlements/{settlement_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    # ─── ClassMember + NoticeRecord ───────────────────────────────────────
    def create_class_member(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/class-members", payload, headers
        )

    def get_class_member(self, member_id, headers):
        return self._request("GET", f"/class-members/{member_id}", headers=headers)

    def list_class_members(self, headers, params=None):
        return self._request("GET", "/class-members", headers=headers, params=params)

    def create_notice(self, member_id, payload, headers):
        return self._request(
            "POST", f"/class-members/{member_id}/notices", payload, headers
        )

    def list_notices(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/class-members/{member_id}/notices", headers=headers, params=params
        )

    def file_claim_self_serve(self, member_id, payload, headers):
        return self._request(
            "POST", f"/class-members/{member_id}/file-claim", payload, headers
        )

    # ─── Claim + Deficiency ───────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def validate_claim(self, claim_id, recognized_loss_cents, headers):
        return self._request(
            "POST",
            f"/claims/{claim_id}/validate",
            {"recognized_loss_cents": recognized_loss_cents},
            headers,
        )

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reject", {}, headers)

    def cure_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/cure", {}, headers)

    def raise_deficiency(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/deficiencies", payload, headers
        )

    def list_deficiencies(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/claims/{claim_id}/deficiencies", headers=headers, params=params
        )

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    # ─── OptOut + Objection ───────────────────────────────────────────────
    def create_opt_out(self, payload, headers):
        return self._request("POST", "/opt-outs", payload, headers)

    def get_opt_out(self, opt_out_id, headers):
        return self._request("GET", f"/opt-outs/{opt_out_id}", headers=headers)

    def list_opt_outs(self, headers, params=None):
        return self._request("GET", "/opt-outs", headers=headers, params=params)

    def finalize_opt_out(self, opt_out_id, headers):
        return self._request("POST", f"/opt-outs/{opt_out_id}/finalize", {}, headers)

    def revoke_opt_out(self, opt_out_id, headers):
        return self._request("POST", f"/opt-outs/{opt_out_id}/revoke", {}, headers)

    def create_objection(self, payload, headers):
        return self._request("POST", "/objections", payload, headers)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"/objections/{objection_id}", headers=headers)

    def list_objections(self, headers, params=None):
        return self._request("GET", "/objections", headers=headers, params=params)

    def rule_objection(self, objection_id, ruling, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/rule", {"ruling": ruling}, headers
        )

    def withdraw_objection(self, objection_id, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/withdraw", {}, headers
        )

    # ─── DistributionBatch + Payment + TaxForm ────────────────────────────
    def create_distribution_batch(self, payload, headers):
        return self._request("POST", "/distribution-batches", payload, headers)

    def get_distribution_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/distribution-batches/{batch_id}", headers=headers
        )

    def list_distribution_batches(self, headers, params=None):
        return self._request(
            "GET", "/distribution-batches", headers=headers, params=params
        )

    def compute_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/distribution-batches/{batch_id}/compute", {}, headers
        )

    def post_batch(self, batch_id, expected_settlement_version, headers):
        return self._request(
            "POST",
            f"/distribution-batches/{batch_id}/post",
            {"expected_settlement_version": expected_settlement_version},
            headers,
        )

    def void_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/distribution-batches/{batch_id}/void", {}, headers
        )

    def reverse_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/distribution-batches/{batch_id}/reverse", {}, headers
        )

    def list_batch_payments(self, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution-batches/{batch_id}/payments",
            headers=headers,
            params=params,
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_tax_form(self, tax_form_id, headers):
        return self._request("GET", f"/tax-forms/{tax_form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/tax-forms", headers=headers, params=params)

    def correct_tax_form(self, tax_form_id, headers):
        return self._request("POST", f"/tax-forms/{tax_form_id}/correct", {}, headers)

    # ─── CyPresDesignation ────────────────────────────────────────────────
    def create_cy_pres_designation(self, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/cy-pres-designations",
            payload,
            headers,
        )

    def get_cy_pres_designation(self, designation_id, headers):
        return self._request(
            "GET", f"/cy-pres-designations/{designation_id}", headers=headers
        )

    def list_cy_pres_designations(self, settlement_id, headers, params=None):
        return self._request(
            "GET",
            f"/settlements/{settlement_id}/cy-pres-designations",
            headers=headers,
            params=params,
        )

    def approve_cy_pres_designation(self, designation_id, headers):
        return self._request(
            "POST", f"/cy-pres-designations/{designation_id}/approve", {}, headers
        )

    def revoke_cy_pres_designation(self, designation_id, headers):
        return self._request(
            "POST", f"/cy-pres-designations/{designation_id}/revoke", {}, headers
        )


api_client = ApiClient()
