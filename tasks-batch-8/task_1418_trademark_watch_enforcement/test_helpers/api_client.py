"""API client: one method per endpoint defined in the PRD (all under /brand)."""
from prd_bench_local_runner.testing import GenericApiClient

# Action endpoints whose PRD input list is empty still receive an empty JSON
# object so the request always carries a parseable body.
EMPTY = {}


class ApiClient(GenericApiClient):
    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/brand/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/brand/clients/{client_id}", headers=headers)

    # --- TrademarkRecord ---
    def create_trademark_record(self, payload, headers):
        return self._request("POST", "/brand/trademark-records", payload, headers)

    def list_trademark_records(self, headers, params=None):
        return self._request("GET", "/brand/trademark-records", headers=headers, params=params)

    def get_trademark_record(self, record_id, headers):
        return self._request("GET", f"/brand/trademark-records/{record_id}", headers=headers)

    def publish_record(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/publish", payload, headers)

    def register_record(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/register", payload, headers)

    # --- WatchAlert ---
    def create_watch_alert(self, payload, headers):
        return self._request("POST", "/brand/watch-alerts", payload, headers)

    def list_watch_alerts(self, headers, params=None):
        return self._request("GET", "/brand/watch-alerts", headers=headers, params=params)

    def get_watch_alert(self, alert_id, headers):
        return self._request("GET", f"/brand/watch-alerts/{alert_id}", headers=headers)

    def triage_alert(self, alert_id, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/triage", EMPTY, headers)

    def assess_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/assess", payload, headers)

    def escalate_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/escalate", payload, headers)

    def monitor_alert(self, alert_id, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/monitor", EMPTY, headers)

    def dismiss_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/dismiss", payload, headers)

    # --- EnforcementMatter ---
    def list_enforcement_matters(self, headers, params=None):
        return self._request("GET", "/brand/enforcement-matters", headers=headers, params=params)

    def get_enforcement_matter(self, matter_id, headers):
        return self._request("GET", f"/brand/enforcement-matters/{matter_id}", headers=headers)

    def resolve_matter(self, matter_id, payload, headers):
        return self._request("POST", f"/brand/enforcement-matters/{matter_id}/resolve", payload, headers)

    def reopen_matter(self, matter_id, headers):
        return self._request("POST", f"/brand/enforcement-matters/{matter_id}/reopen", EMPTY, headers)

    # --- Deadline ---
    def docket_deadline(self, matter_id, payload, headers):
        return self._request("POST", f"/brand/enforcement-matters/{matter_id}/deadlines", payload, headers)

    def list_deadlines(self, headers, params=None):
        return self._request("GET", "/brand/deadlines", headers=headers, params=params)

    def get_deadline(self, deadline_id, headers):
        return self._request("GET", f"/brand/deadlines/{deadline_id}", headers=headers)

    def verify_deadline(self, deadline_id, headers):
        return self._request("POST", f"/brand/deadlines/{deadline_id}/verify", EMPTY, headers)

    def extend_deadline(self, deadline_id, payload, headers):
        return self._request("POST", f"/brand/deadlines/{deadline_id}/extend", payload, headers)

    def satisfy_deadline(self, deadline_id, payload, headers):
        return self._request("POST", f"/brand/deadlines/{deadline_id}/satisfy", payload, headers)

    # --- CeaseDesistLetter ---
    def draft_letter(self, matter_id, payload, headers):
        return self._request("POST", f"/brand/enforcement-matters/{matter_id}/cease-desist-letters", payload, headers)

    def list_letters(self, headers, params=None):
        return self._request("GET", "/brand/cease-desist-letters", headers=headers, params=params)

    def get_letter(self, letter_id, headers):
        return self._request("GET", f"/brand/cease-desist-letters/{letter_id}", headers=headers)

    def submit_letter_review(self, letter_id, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/submit-review", EMPTY, headers)

    def approve_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/approve", payload, headers)

    def issue_letter(self, letter_id, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/issue", EMPTY, headers)

    def record_letter_response(self, letter_id, payload, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/record-response", payload, headers)

    def reissue_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/reissue", payload, headers)

    def escalate_letter_litigation(self, letter_id, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/escalate-litigation", EMPTY, headers)

    def void_letter(self, letter_id, headers):
        return self._request("POST", f"/brand/cease-desist-letters/{letter_id}/void", EMPTY, headers)

    # --- TakedownFiling ---
    def create_takedown_filing(self, alert_id, payload, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/takedown-filings", payload, headers)

    def list_takedown_filings(self, headers, params=None):
        return self._request("GET", "/brand/takedown-filings", headers=headers, params=params)

    def get_takedown_filing(self, filing_id, headers):
        return self._request("GET", f"/brand/takedown-filings/{filing_id}", headers=headers)

    def file_takedown(self, filing_id, headers):
        return self._request("POST", f"/brand/takedown-filings/{filing_id}/file", EMPTY, headers)

    def record_platform_response(self, filing_id, payload, headers):
        return self._request("POST", f"/brand/takedown-filings/{filing_id}/platform-response", payload, headers)

    def appeal_takedown(self, filing_id, headers):
        return self._request("POST", f"/brand/takedown-filings/{filing_id}/appeal", EMPTY, headers)

    # --- CoexistenceAgreement ---
    def create_coexistence_agreement(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/coexistence-agreements", payload, headers)

    def list_coexistence_agreements(self, headers, params=None):
        return self._request("GET", "/brand/coexistence-agreements", headers=headers, params=params)

    def get_coexistence_agreement(self, agreement_id, headers):
        return self._request("GET", f"/brand/coexistence-agreements/{agreement_id}", headers=headers)

    def propose_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/brand/coexistence-agreements/{agreement_id}/propose", payload, headers)

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/brand/coexistence-agreements/{agreement_id}/counter", payload, headers)

    def execute_agreement(self, agreement_id, headers):
        return self._request("POST", f"/brand/coexistence-agreements/{agreement_id}/execute", EMPTY, headers)

    def breach_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/brand/coexistence-agreements/{agreement_id}/breach", payload, headers)

    def cure_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/brand/coexistence-agreements/{agreement_id}/cure", payload, headers)

    # --- UseEvidenceItem ---
    def collect_evidence(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/evidence-items", payload, headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/brand/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, item_id, headers):
        return self._request("GET", f"/brand/evidence-items/{item_id}", headers=headers)

    def verify_evidence(self, item_id, headers):
        return self._request("POST", f"/brand/evidence-items/{item_id}/verify", EMPTY, headers)

    def reject_evidence(self, item_id, payload, headers):
        return self._request("POST", f"/brand/evidence-items/{item_id}/reject", payload, headers)

    # --- MaintenanceFiling ---
    def create_maintenance_filing(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/maintenance-filings", payload, headers)

    def list_maintenance_filings(self, headers, params=None):
        return self._request("GET", "/brand/maintenance-filings", headers=headers, params=params)

    def get_maintenance_filing(self, filing_id, headers):
        return self._request("GET", f"/brand/maintenance-filings/{filing_id}", headers=headers)

    def submit_maintenance_filing(self, filing_id, headers):
        return self._request("POST", f"/brand/maintenance-filings/{filing_id}/submit", EMPTY, headers)

    def office_decision_maintenance_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/brand/maintenance-filings/{filing_id}/office-decision", payload, headers)

    # --- ClearanceSearch ---
    def create_clearance_search(self, payload, headers):
        return self._request("POST", "/brand/clearance-searches", payload, headers)

    def list_clearance_searches(self, headers, params=None):
        return self._request("GET", "/brand/clearance-searches", headers=headers, params=params)

    def get_clearance_search(self, search_id, headers):
        return self._request("GET", f"/brand/clearance-searches/{search_id}", headers=headers)

    def add_conflict_hit(self, search_id, payload, headers):
        return self._request("POST", f"/brand/clearance-searches/{search_id}/conflict-hits", payload, headers)

    def dispose_hit(self, search_id, payload, headers):
        return self._request("POST", f"/brand/clearance-searches/{search_id}/dispose-hit", payload, headers)

    def finalize_clearance_search(self, search_id, headers):
        return self._request("POST", f"/brand/clearance-searches/{search_id}/finalize", EMPTY, headers)

    # --- CustomsRecordation ---
    def create_customs_recordation(self, record_id, payload, headers):
        return self._request("POST", f"/brand/trademark-records/{record_id}/customs-recordations", payload, headers)

    def list_customs_recordations(self, headers, params=None):
        return self._request("GET", "/brand/customs-recordations", headers=headers, params=params)

    def get_customs_recordation(self, recordation_id, headers):
        return self._request("GET", f"/brand/customs-recordations/{recordation_id}", headers=headers)

    # --- CounterfeitReferral ---
    def create_counterfeit_referral(self, alert_id, payload, headers):
        return self._request("POST", f"/brand/watch-alerts/{alert_id}/counterfeit-referrals", payload, headers)

    def list_counterfeit_referrals(self, headers, params=None):
        return self._request("GET", "/brand/counterfeit-referrals", headers=headers, params=params)

    def get_counterfeit_referral(self, referral_id, headers):
        return self._request("GET", f"/brand/counterfeit-referrals/{referral_id}", headers=headers)

    def refer_referral(self, referral_id, headers):
        return self._request("POST", f"/brand/counterfeit-referrals/{referral_id}/refer", EMPTY, headers)

    def acknowledge_referral(self, referral_id, headers):
        return self._request("POST", f"/brand/counterfeit-referrals/{referral_id}/acknowledge", EMPTY, headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/brand/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
