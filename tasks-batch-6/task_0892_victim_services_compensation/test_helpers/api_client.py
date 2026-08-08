"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program -----------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/compensation/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/compensation/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/compensation/programs", headers=headers, params=params)

    def transition_program(self, program_id, payload, headers):
        return self._request("POST", f"/compensation/programs/{program_id}/transition", payload, headers)

    # --- VictimCase --------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/compensation/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/compensation/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/compensation/cases", headers=headers, params=params)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/compensation/cases/{case_id}/transition", payload, headers)

    def list_case_notifications(self, case_id, headers, params=None):
        return self._request("GET", f"/compensation/cases/{case_id}/notifications", headers=headers, params=params)

    # --- Claim -------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/compensation/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/compensation/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/compensation/claims", headers=headers, params=params)

    def transition_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/compensation/claims/{claim_id}/transition", payload, headers)

    # --- CollateralSource --------------------------------------------------
    def create_collateral_source(self, payload, headers):
        return self._request("POST", "/compensation/collateral-sources", payload, headers)

    def get_collateral_source(self, cs_id, headers):
        return self._request("GET", f"/compensation/collateral-sources/{cs_id}", headers=headers)

    def list_collateral_sources(self, headers, params=None):
        return self._request("GET", "/compensation/collateral-sources", headers=headers, params=params)

    def transition_collateral_source(self, cs_id, payload, headers):
        return self._request("POST", f"/compensation/collateral-sources/{cs_id}/transition", payload, headers)

    # --- Award -------------------------------------------------------------
    def create_award(self, payload, headers):
        return self._request("POST", "/compensation/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/compensation/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/compensation/awards", headers=headers, params=params)

    def transition_award(self, award_id, payload, headers):
        return self._request("POST", f"/compensation/awards/{award_id}/transition", payload, headers)

    # --- Disbursement ------------------------------------------------------
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/compensation/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/compensation/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/compensation/disbursements", headers=headers, params=params)

    def transition_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/compensation/disbursements/{disbursement_id}/transition", payload, headers)

    # --- RestitutionRecovery ----------------------------------------------
    def create_recovery(self, payload, headers):
        return self._request("POST", "/compensation/recoveries", payload, headers)

    def get_recovery(self, recovery_id, headers):
        return self._request("GET", f"/compensation/recoveries/{recovery_id}", headers=headers)

    def list_recoveries(self, headers, params=None):
        return self._request("GET", "/compensation/recoveries", headers=headers, params=params)

    def transition_recovery(self, recovery_id, payload, headers):
        return self._request("POST", f"/compensation/recoveries/{recovery_id}/transition", payload, headers)

    # --- RecoveryReceipt ---------------------------------------------------
    def create_receipt(self, recovery_id, payload, headers):
        return self._request("POST", f"/compensation/recoveries/{recovery_id}/receipts", payload, headers)

    def list_receipts(self, recovery_id, headers, params=None):
        return self._request("GET", f"/compensation/recoveries/{recovery_id}/receipts", headers=headers, params=params)

    def transition_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/compensation/receipts/{receipt_id}/transition", payload, headers)

    # --- Appeal ------------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/compensation/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/compensation/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/compensation/appeals", headers=headers, params=params)

    def transition_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/compensation/appeals/{appeal_id}/transition", payload, headers)

    # --- Notification ------------------------------------------------------
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/compensation/notifications/{notification_id}", headers=headers)

    # --- Logical clock (test-driving) --------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/compensation/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
