"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers,
        )

    # ------------------------------------------------------------------
    # ServiceProviderProfile
    # ------------------------------------------------------------------
    def create_provider(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict):
        return self._request("GET", f"/dmca/providers/{provider_id}", headers=headers)

    def list_providers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/dmca/providers", headers=headers, params=params)

    def publish_provider_contact(self, provider_id: str, public_contact_url: str,
                                 headers: Dict):
        return self._request(
            "POST", f"/dmca/providers/{provider_id}/publish-contact",
            {"public_contact_url": public_contact_url}, headers,
        )

    def list_provider_designated_agents(self, provider_id: str, headers: Dict,
                                        params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/providers/{provider_id}/designated-agents",
            headers=headers, params=params,
        )

    def list_provider_policies(self, provider_id: str, headers: Dict,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/providers/{provider_id}/repeat-infringer-policies",
            headers=headers, params=params,
        )

    def list_provider_safe_harbor_audits(self, provider_id: str, headers: Dict,
                                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/providers/{provider_id}/safe-harbor-audits",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # DesignatedAgent
    # ------------------------------------------------------------------
    def create_designated_agent(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/designated-agents", payload, headers)

    def get_designated_agent(self, agent_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/designated-agents/{agent_id}", headers=headers,
        )

    def submit_designated_agent(self, agent_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/designated-agents/{agent_id}/submit", {}, headers,
        )

    def register_designated_agent(self, agent_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/dmca/designated-agents/{agent_id}/register", payload, headers,
        )

    def lapse_designated_agent(self, agent_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/designated-agents/{agent_id}/lapse", {}, headers,
        )

    # ------------------------------------------------------------------
    # RepeatInfringerPolicy
    # ------------------------------------------------------------------
    def create_policy(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/repeat-infringer-policies", payload, headers)

    def get_policy(self, policy_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/repeat-infringer-policies/{policy_id}", headers=headers,
        )

    def publish_policy(self, policy_id: str, expected_provider_version: int,
                       headers: Dict):
        return self._request(
            "POST", f"/dmca/repeat-infringer-policies/{policy_id}/publish",
            {"expected_provider_version": expected_provider_version}, headers,
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    def create_account(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict):
        return self._request("GET", f"/dmca/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/dmca/accounts", headers=headers, params=params)

    def list_account_content_items(self, account_id: str, headers: Dict,
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/accounts/{account_id}/content-items",
            headers=headers, params=params,
        )

    def list_account_strikes(self, account_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/accounts/{account_id}/strikes",
            headers=headers, params=params,
        )

    def list_account_termination_cases(self, account_id: str, headers: Dict,
                                       params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/accounts/{account_id}/termination-cases",
            headers=headers, params=params,
        )

    def get_account_strike_summary(self, account_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/accounts/{account_id}/strike-summary", headers=headers,
        )

    def reinstate_account(self, account_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/accounts/{account_id}/reinstate", {}, headers,
        )

    # ------------------------------------------------------------------
    # ContentItem
    # ------------------------------------------------------------------
    def create_content_item(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/content-items", payload, headers)

    def get_content_item(self, item_id: str, headers: Dict):
        return self._request("GET", f"/dmca/content-items/{item_id}", headers=headers)

    def purge_content_item(self, item_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/content-items/{item_id}/purge", {}, headers,
        )

    # ------------------------------------------------------------------
    # RightsHolder
    # ------------------------------------------------------------------
    def create_rights_holder(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/rights-holders", payload, headers)

    def get_rights_holder(self, rights_holder_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/rights-holders/{rights_holder_id}", headers=headers,
        )

    def list_rights_holders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/dmca/rights-holders", headers=headers, params=params,
        )

    def enroll_rights_holder(self, rights_holder_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/rights-holders/{rights_holder_id}/enroll", {}, headers,
        )

    def promote_rights_holder_tier(self, rights_holder_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/rights-holders/{rights_holder_id}/promote-tier", {}, headers,
        )

    def suspend_rights_holder(self, rights_holder_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/rights-holders/{rights_holder_id}/suspend", {}, headers,
        )

    def list_rights_holder_reference_files(self, rights_holder_id: str, headers: Dict,
                                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/rights-holders/{rights_holder_id}/reference-files",
            headers=headers, params=params,
        )

    def list_rights_holder_ingestion_batches(self, rights_holder_id: str, headers: Dict,
                                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/rights-holders/{rights_holder_id}/ingestion-batches",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # ReferenceFile
    # ------------------------------------------------------------------
    def create_reference_file(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/reference-files", payload, headers)

    def get_reference_file(self, reference_file_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/reference-files/{reference_file_id}", headers=headers,
        )

    def activate_reference_file(self, reference_file_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/reference-files/{reference_file_id}/activate", {}, headers,
        )

    # ------------------------------------------------------------------
    # IngestionBatch
    # ------------------------------------------------------------------
    def create_ingestion_batch(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/ingestion-batches", payload, headers)

    def get_ingestion_batch(self, batch_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/ingestion-batches/{batch_id}", headers=headers,
        )

    def complete_ingestion_batch(self, batch_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/ingestion-batches/{batch_id}/complete", {}, headers,
        )

    def reject_ingestion_batch(self, batch_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/ingestion-batches/{batch_id}/reject", {}, headers,
        )

    # ------------------------------------------------------------------
    # TakedownNotice
    # ------------------------------------------------------------------
    def create_notice(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/notices", payload, headers)

    def get_notice(self, notice_id: str, headers: Dict):
        return self._request("GET", f"/dmca/notices/{notice_id}", headers=headers)

    def list_notices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/dmca/notices", headers=headers, params=params)

    def validate_notice(self, notice_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/notices/{notice_id}/validate", {}, headers,
        )

    def process_notice(self, notice_id: str, headers: Dict):
        return self._request("POST", f"/dmca/notices/{notice_id}/process", {}, headers)

    def withdraw_notice(self, notice_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/notices/{notice_id}/withdraw", {}, headers,
        )

    # ------------------------------------------------------------------
    # NoticeClaim
    # ------------------------------------------------------------------
    def get_claim(self, claim_id: str, headers: Dict):
        return self._request("GET", f"/dmca/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/dmca/claims", headers=headers, params=params)

    def list_claim_strikes(self, claim_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/dmca/claims/{claim_id}/strikes", headers=headers, params=params,
        )

    def uphold_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/dmca/claims/{claim_id}/uphold", {}, headers)

    def restore_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/dmca/claims/{claim_id}/restore", {}, headers)

    # ------------------------------------------------------------------
    # CounterNotice
    # ------------------------------------------------------------------
    def create_counter_notice(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/counter-notices", payload, headers)

    def get_counter_notice(self, counter_notice_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/counter-notices/{counter_notice_id}", headers=headers,
        )

    def list_counter_notices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/dmca/counter-notices", headers=headers, params=params,
        )

    def validate_counter_notice(self, counter_notice_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/counter-notices/{counter_notice_id}/validate", {}, headers,
        )

    def forward_counter_notice(self, counter_notice_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/counter-notices/{counter_notice_id}/forward", {}, headers,
        )

    def record_suit_notice(self, counter_notice_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/counter-notices/{counter_notice_id}/record-suit-notice",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # StrikeRecord
    # ------------------------------------------------------------------
    def get_strike(self, strike_id: str, headers: Dict):
        return self._request("GET", f"/dmca/strikes/{strike_id}", headers=headers)

    # ------------------------------------------------------------------
    # TerminationCase
    # ------------------------------------------------------------------
    def get_termination_case(self, case_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/termination-cases/{case_id}", headers=headers,
        )

    def execute_termination_case(self, case_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/termination-cases/{case_id}/execute", {}, headers,
        )

    def file_termination_appeal(self, case_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/termination-cases/{case_id}/file-appeal", {}, headers,
        )

    def decide_termination_appeal(self, case_id: str, decision: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/termination-cases/{case_id}/decide-appeal",
            {"decision": decision}, headers,
        )

    # ------------------------------------------------------------------
    # MisrepresentationCase
    # ------------------------------------------------------------------
    def create_misrepresentation_case(self, payload: Dict, headers: Dict):
        return self._request("POST", "/dmca/misrepresentation-cases", payload, headers)

    def get_misrepresentation_case(self, case_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/misrepresentation-cases/{case_id}", headers=headers,
        )

    def list_misrepresentation_cases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/dmca/misrepresentation-cases", headers=headers, params=params,
        )

    def substantiate_misrepresentation_case(self, case_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/misrepresentation-cases/{case_id}/substantiate", {}, headers,
        )

    def dismiss_misrepresentation_case(self, case_id: str, headers: Dict):
        return self._request(
            "POST", f"/dmca/misrepresentation-cases/{case_id}/dismiss", {}, headers,
        )

    # ------------------------------------------------------------------
    # SafeHarborAudit
    # ------------------------------------------------------------------
    def create_safe_harbor_audit(self, provider_id: str, headers: Dict):
        return self._request(
            "POST", "/dmca/safe-harbor-audits", {"provider_id": provider_id}, headers,
        )

    def get_safe_harbor_audit(self, audit_id: str, headers: Dict):
        return self._request(
            "GET", f"/dmca/safe-harbor-audits/{audit_id}", headers=headers,
        )


api_client = ApiClient()
