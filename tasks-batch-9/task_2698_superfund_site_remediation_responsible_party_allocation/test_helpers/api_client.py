"""API client: one method per endpoint in the PRD's endpoint reference.

Paths are rooted at the service root with no prefix, exactly as the PRD
tabulates them.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ sites
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def get_cost_ledger(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/cost-ledger", headers=headers)

    def list_on_npl(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/list-on-npl", payload, headers)

    # ----------------------------------------------------------------- parties
    def create_prp(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/prps", payload, headers)

    def list_site_prps(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/prps", headers=headers, params=params
        )

    def get_prp(self, prp_id, headers):
        return self._request("GET", f"/prps/{prp_id}", headers=headers)

    def issue_notice(self, prp_id, payload, headers):
        return self._request("POST", f"/prps/{prp_id}/notice", payload, headers)

    def record_response(self, prp_id, payload, headers):
        return self._request("POST", f"/prps/{prp_id}/response", payload, headers)

    def record_defunct(self, prp_id, payload, headers):
        return self._request("POST", f"/prps/{prp_id}/defunct", payload, headers)

    def list_prp_ownership_periods(self, prp_id, headers, params=None):
        return self._request(
            "GET", f"/prps/{prp_id}/ownership-periods", headers=headers, params=params
        )

    def list_prp_waste_in_records(self, prp_id, headers, params=None):
        return self._request(
            "GET", f"/prps/{prp_id}/waste-in-records", headers=headers, params=params
        )

    def list_prp_allocation_shares(self, prp_id, headers, params=None):
        return self._request(
            "GET", f"/prps/{prp_id}/allocation-shares", headers=headers, params=params
        )

    # -------------------------------------------------------- chain of title
    def create_ownership_period(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/ownership-periods", payload, headers
        )

    def list_site_ownership_periods(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/ownership-periods", headers=headers, params=params
        )

    # ------------------------------------------------------------ waste-in
    def create_waste_in_record(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/waste-in-records", payload, headers
        )

    def list_site_waste_in_records(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/waste-in-records", headers=headers, params=params
        )

    def get_waste_in_record(self, record_id, headers):
        return self._request("GET", f"/waste-in-records/{record_id}", headers=headers)

    def verify_waste_in_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/waste-in-records/{record_id}/verification", payload, headers
        )

    # ------------------------------------------------------- investigations
    def create_remedial_investigation(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/remedial-investigations", payload, headers
        )

    def list_site_remedial_investigations(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/remedial-investigations",
            headers=headers,
            params=params,
        )

    def get_remedial_investigation(self, ri_id, headers):
        return self._request(
            "GET", f"/remedial-investigations/{ri_id}", headers=headers
        )

    def create_sample(self, ri_id, payload, headers):
        return self._request(
            "POST", f"/remedial-investigations/{ri_id}/samples", payload, headers
        )

    def list_samples(self, ri_id, headers, params=None):
        return self._request(
            "GET",
            f"/remedial-investigations/{ri_id}/samples",
            headers=headers,
            params=params,
        )

    def submit_remedial_investigation(self, ri_id, headers, payload=None):
        return self._request(
            "POST", f"/remedial-investigations/{ri_id}/submission", payload or {}, headers
        )

    def review_remedial_investigation(self, ri_id, payload, headers):
        return self._request(
            "POST", f"/remedial-investigations/{ri_id}/review", payload, headers
        )

    def create_remedy_alternative(self, ri_id, payload, headers):
        return self._request(
            "POST",
            f"/remedial-investigations/{ri_id}/remedy-alternatives",
            payload,
            headers,
        )

    def list_remedy_alternatives(self, ri_id, headers, params=None):
        return self._request(
            "GET",
            f"/remedial-investigations/{ri_id}/remedy-alternatives",
            headers=headers,
            params=params,
        )

    def list_investigation_rods(self, ri_id, headers, params=None):
        return self._request(
            "GET",
            f"/remedial-investigations/{ri_id}/records-of-decision",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------- records of decision
    def create_record_of_decision(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/records-of-decision", payload, headers
        )

    def list_site_rods(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/records-of-decision",
            headers=headers,
            params=params,
        )

    def get_record_of_decision(self, rod_id, headers):
        return self._request("GET", f"/records-of-decision/{rod_id}", headers=headers)

    def open_comment_period(self, rod_id, headers, payload=None):
        return self._request(
            "POST", f"/records-of-decision/{rod_id}/comment-period", payload or {}, headers
        )

    def file_public_comment(self, rod_id, payload, headers):
        return self._request(
            "POST", f"/records-of-decision/{rod_id}/public-comments", payload, headers
        )

    def sign_record_of_decision(self, rod_id, payload, headers):
        return self._request(
            "POST", f"/records-of-decision/{rod_id}/signature", payload, headers
        )

    def get_selected_remedy(self, rod_id, headers, params=None):
        return self._request(
            "GET",
            f"/records-of-decision/{rod_id}/selected-remedy",
            headers=headers,
            params=params,
        )

    def list_rod_contracts(self, rod_id, headers, params=None):
        return self._request(
            "GET",
            f"/records-of-decision/{rod_id}/remediation-contracts",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- allocation rounds
    def create_allocation_round(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/allocation-rounds", payload, headers
        )

    def list_site_allocation_rounds(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/allocation-rounds",
            headers=headers,
            params=params,
        )

    def get_allocation_round(self, round_id, headers):
        return self._request("GET", f"/allocation-rounds/{round_id}", headers=headers)

    def open_balloting(self, round_id, headers, payload=None):
        return self._request(
            "POST", f"/allocation-rounds/{round_id}/balloting", payload or {}, headers
        )

    def cast_ballot(self, round_id, payload, headers):
        return self._request(
            "POST", f"/allocation-rounds/{round_id}/ballots", payload, headers
        )

    def reopen_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/allocation-rounds/{round_id}/reopening", payload, headers
        )

    def list_round_shares(self, round_id, headers, params=None):
        return self._request(
            "GET",
            f"/allocation-rounds/{round_id}/shares",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------ settlement instruments
    def create_consent_decree(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/consent-decrees", payload, headers
        )

    def list_site_consent_decrees(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/consent-decrees", headers=headers, params=params
        )

    def get_consent_decree(self, decree_id, headers):
        return self._request("GET", f"/consent-decrees/{decree_id}", headers=headers)

    def lodge_consent_decree(self, decree_id, headers, payload=None):
        return self._request(
            "POST", f"/consent-decrees/{decree_id}/lodging", payload or {}, headers
        )

    def enter_consent_decree(self, decree_id, payload, headers):
        return self._request(
            "POST", f"/consent-decrees/{decree_id}/entry", payload, headers
        )

    def record_compliance_event(self, decree_id, payload, headers):
        return self._request(
            "POST", f"/consent-decrees/{decree_id}/compliance-events", payload, headers
        )

    # ------------------------------------------------------ oversight costs
    def post_oversight_cost(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/oversight-costs", payload, headers
        )

    # --------------------------------------------------------- procurement
    def create_remediation_contract(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/remediation-contracts", payload, headers
        )

    def list_site_remediation_contracts(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/sites/{site_id}/remediation-contracts",
            headers=headers,
            params=params,
        )

    def get_remediation_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/remediation-contracts/{contract_id}", headers=headers
        )

    def award_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/remediation-contracts/{contract_id}/award", payload, headers
        )

    def create_work_window(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/remediation-contracts/{contract_id}/work-windows",
            payload,
            headers,
        )

    def list_work_windows(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/remediation-contracts/{contract_id}/work-windows",
            headers=headers,
            params=params,
        )

    def certify_construction_complete(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/remediation-contracts/{contract_id}/construction-completion",
            payload,
            headers,
        )

    # ------------------------------------------------------ five-year review
    def record_five_year_review(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/five-year-review", payload, headers
        )

    # -------------------------------------------------------- cost recovery
    def create_cost_recovery_action(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/cost-recovery-actions", payload, headers
        )

    def list_cost_recovery_actions(self, headers, params=None):
        return self._request(
            "GET", "/cost-recovery-actions", headers=headers, params=params
        )

    def get_cost_recovery_action(self, action_id, headers):
        return self._request(
            "GET", f"/cost-recovery-actions/{action_id}", headers=headers
        )

    def respond_to_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/cost-recovery-actions/{action_id}/response", payload, headers
        )

    def record_collection(self, action_id, payload, headers):
        return self._request(
            "POST", f"/cost-recovery-actions/{action_id}/collection", payload, headers
        )

    def void_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/cost-recovery-actions/{action_id}/voiding", payload, headers
        )


api_client = ApiClient()
