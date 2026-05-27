"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ── Decedent ────────────────────────────────────────────────────
    def create_decedent(self, payload, headers):
        return self._request("POST", "/decedents", payload, headers)

    def get_decedent(self, decedent_id, headers):
        return self._request("GET", f"/decedents/{decedent_id}", headers=headers)

    def register_death(self, decedent_id, payload, headers):
        return self._request(
            "POST", f"/decedents/{decedent_id}/register-death", payload, headers,
        )

    # ── Estate ──────────────────────────────────────────────────────
    def create_estate(self, payload, headers):
        return self._request("POST", "/estates", payload, headers)

    def get_estate(self, estate_id, headers):
        return self._request("GET", f"/estates/{estate_id}", headers=headers)

    def list_estates(self, headers, params=None):
        return self._request("GET", "/estates", headers=headers, params=params)

    def finalize_plan(self, estate_id, headers):
        return self._request(
            "POST", f"/estates/{estate_id}/finalize-plan", {}, headers,
        )

    def file_for_probate(self, estate_id, headers):
        return self._request(
            "POST", f"/estates/{estate_id}/file-for-probate", {}, headers,
        )

    def contest_estate(self, estate_id, expected_estate_version, reason, headers):
        return self._request(
            "POST", f"/estates/{estate_id}/contest",
            {"expected_estate_version": expected_estate_version, "reason": reason},
            headers,
        )

    def resolve_contest(self, estate_id, resolution_note, headers):
        return self._request(
            "POST", f"/estates/{estate_id}/resolve-contest",
            {"resolution_note": resolution_note}, headers,
        )

    def compute_intestacy_shares(self, estate_id, headers):
        return self._request(
            "POST", f"/estates/{estate_id}/compute-intestacy-shares", {}, headers,
        )

    def get_net_taxable_summary(self, estate_id, headers):
        return self._request(
            "GET", f"/estates/{estate_id}/net-taxable-summary", headers=headers,
        )

    # ── Asset ───────────────────────────────────────────────────────
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def patch_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/assets/{asset_id}", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def liquidate_asset(self, asset_id, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/liquidate", {}, headers,
        )

    # ── BeneficiaryDesignation ──────────────────────────────────────
    def create_beneficiary_designation(self, payload, headers):
        return self._request("POST", "/beneficiary-designations", payload, headers)

    def get_beneficiary_designation(self, designation_id, headers):
        return self._request(
            "GET", f"/beneficiary-designations/{designation_id}", headers=headers,
        )

    def list_beneficiary_designations(self, headers, params=None):
        return self._request(
            "GET", "/beneficiary-designations", headers=headers, params=params,
        )

    def activate_beneficiary_designation(self, designation_id, headers):
        return self._request(
            "POST", f"/beneficiary-designations/{designation_id}/activate",
            {}, headers,
        )

    def revoke_beneficiary_designation(
        self, designation_id, expected_estate_version, headers,
    ):
        return self._request(
            "POST", f"/beneficiary-designations/{designation_id}/revoke",
            {"expected_estate_version": expected_estate_version}, headers,
        )

    # ── Executor ────────────────────────────────────────────────────
    def create_executor(self, payload, headers):
        return self._request("POST", "/executors", payload, headers)

    def get_executor(self, executor_id, headers):
        return self._request("GET", f"/executors/{executor_id}", headers=headers)

    def list_executors(self, headers, params=None):
        return self._request("GET", "/executors", headers=headers, params=params)

    def accept_executor(self, executor_id, headers):
        return self._request(
            "POST", f"/executors/{executor_id}/accept", {}, headers,
        )

    def decline_executor(self, executor_id, headers):
        return self._request(
            "POST", f"/executors/{executor_id}/decline", {}, headers,
        )

    # ── PowerOfAttorney ─────────────────────────────────────────────
    def create_poa(self, payload, headers):
        return self._request("POST", "/powers-of-attorney", payload, headers)

    def get_poa(self, poa_id, headers):
        return self._request(
            "GET", f"/powers-of-attorney/{poa_id}", headers=headers,
        )

    def list_poas(self, headers, params=None):
        return self._request(
            "GET", "/powers-of-attorney", headers=headers, params=params,
        )

    def activate_poa(self, poa_id, payload, headers):
        return self._request(
            "POST", f"/powers-of-attorney/{poa_id}/activate", payload, headers,
        )

    def revoke_poa(self, poa_id, headers):
        return self._request(
            "POST", f"/powers-of-attorney/{poa_id}/revoke", {}, headers,
        )

    # ── EndOfLifeDirective ──────────────────────────────────────────
    def create_directive(self, payload, headers):
        return self._request("POST", "/directives", payload, headers)

    def get_directive(self, directive_id, headers):
        return self._request("GET", f"/directives/{directive_id}", headers=headers)

    def list_directives(self, headers, params=None):
        return self._request("GET", "/directives", headers=headers, params=params)

    def witness_directive(self, directive_id, headers):
        return self._request(
            "POST", f"/directives/{directive_id}/witness", {}, headers,
        )

    def notarize_directive(self, directive_id, headers):
        return self._request(
            "POST", f"/directives/{directive_id}/notarize", {}, headers,
        )

    def activate_directive(self, directive_id, headers):
        return self._request(
            "POST", f"/directives/{directive_id}/activate", {}, headers,
        )

    def revoke_directive(self, directive_id, headers):
        return self._request(
            "POST", f"/directives/{directive_id}/revoke", {}, headers,
        )

    # ── Guardianship ────────────────────────────────────────────────
    def create_guardianship(self, payload, headers):
        return self._request("POST", "/guardianships", payload, headers)

    def get_guardianship(self, guardianship_id, headers):
        return self._request(
            "GET", f"/guardianships/{guardianship_id}", headers=headers,
        )

    def list_guardianships(self, headers, params=None):
        return self._request(
            "GET", "/guardianships", headers=headers, params=params,
        )

    def review_guardianship(self, guardianship_id, decision, headers):
        return self._request(
            "POST", f"/guardianships/{guardianship_id}/review",
            {"decision": decision}, headers,
        )

    # ── CreditorClaim ───────────────────────────────────────────────
    def create_creditor_claim(self, payload, headers):
        return self._request("POST", "/creditor-claims", payload, headers)

    def get_creditor_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/creditor-claims/{claim_id}", headers=headers,
        )

    def list_creditor_claims(self, headers, params=None):
        return self._request(
            "GET", "/creditor-claims", headers=headers, params=params,
        )

    def allow_creditor_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/creditor-claims/{claim_id}/allow", {}, headers,
        )

    def disallow_creditor_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/creditor-claims/{claim_id}/disallow", {}, headers,
        )

    def pay_creditor_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/creditor-claims/{claim_id}/pay", {}, headers,
        )

    # ── ProbateOrder ────────────────────────────────────────────────
    def create_probate_order(self, payload, headers):
        return self._request("POST", "/probate-orders", payload, headers)

    def get_probate_order(self, order_id, headers):
        return self._request(
            "GET", f"/probate-orders/{order_id}", headers=headers,
        )

    def list_probate_orders(self, headers, params=None):
        return self._request(
            "GET", "/probate-orders", headers=headers, params=params,
        )

    def enter_probate_order(self, order_id, headers):
        return self._request(
            "POST", f"/probate-orders/{order_id}/enter", {}, headers,
        )

    def supersede_probate_order(self, order_id, reason, headers):
        return self._request(
            "POST", f"/probate-orders/{order_id}/supersede",
            {"reason": reason}, headers,
        )


api_client = ApiClient()
