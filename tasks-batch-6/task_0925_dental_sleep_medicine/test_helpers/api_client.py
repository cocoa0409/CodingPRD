"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------------- providers
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # ----------------------------------------------------------------- payers
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # --------------------------------------------------------------- patients
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ---------------------------------------------------------- sleep studies
    def create_sleep_study(self, payload, headers):
        return self._request("POST", "/sleep-studies", payload, headers)

    def get_sleep_study(self, study_id, headers):
        return self._request("GET", f"/sleep-studies/{study_id}", headers=headers)

    def list_sleep_studies(self, headers, params=None):
        return self._request("GET", "/sleep-studies", headers=headers, params=params)

    def post_sleep_study_results(self, study_id, payload, headers):
        return self._request(
            "POST", f"/sleep-studies/{study_id}/results", payload, headers
        )

    def reorder_sleep_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/sleep-studies/{study_id}/reorder", payload, headers
        )

    # -------------------------------------------------------------- referrals
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def respond_to_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/respond", payload, headers
        )

    # --------------------------------------------------------- written orders
    def create_written_order(self, payload, headers):
        return self._request("POST", "/written-orders", payload, headers)

    def get_written_order(self, written_order_id, headers):
        return self._request(
            "GET", f"/written-orders/{written_order_id}", headers=headers
        )

    def list_written_orders(self, headers, params=None):
        return self._request("GET", "/written-orders", headers=headers, params=params)

    def sign_written_order(self, written_order_id, payload, headers):
        return self._request(
            "POST", f"/written-orders/{written_order_id}/sign", payload, headers
        )

    # ------------------------------------------------------------ prior auths
    def create_prior_auth(self, payload, headers):
        return self._request("POST", "/prior-auths", payload, headers)

    def get_prior_auth(self, prior_auth_id, headers):
        return self._request("GET", f"/prior-auths/{prior_auth_id}", headers=headers)

    def list_prior_auths(self, headers, params=None):
        return self._request("GET", "/prior-auths", headers=headers, params=params)

    def decide_prior_auth(self, prior_auth_id, payload, headers):
        return self._request(
            "POST", f"/prior-auths/{prior_auth_id}/decision", payload, headers
        )

    def appeal_prior_auth(self, prior_auth_id, payload, headers):
        return self._request(
            "POST", f"/prior-auths/{prior_auth_id}/appeal", payload, headers
        )

    # ------------------------------------------------------------- lab orders
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/lab-orders", payload, headers)

    def get_lab_order(self, lab_order_id, headers):
        return self._request("GET", f"/lab-orders/{lab_order_id}", headers=headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def submit_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/submit", payload, headers
        )

    def ship_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/ship", payload, headers
        )

    def receive_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/receive", payload, headers
        )

    # --------------------------------------------------------- appliance lots
    def create_appliance_lot(self, payload, headers):
        return self._request("POST", "/appliance-lots", payload, headers)

    def get_appliance_lot(self, lot_id, headers):
        return self._request("GET", f"/appliance-lots/{lot_id}", headers=headers)

    def recall_appliance_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/appliance-lots/{lot_id}/recall", payload, headers
        )

    # ------------------------------------------------------------- appliances
    def create_appliance(self, payload, headers):
        return self._request("POST", "/appliances", payload, headers)

    def get_appliance(self, appliance_id, headers):
        return self._request("GET", f"/appliances/{appliance_id}", headers=headers)

    def list_appliances(self, headers, params=None):
        return self._request("GET", "/appliances", headers=headers, params=params)

    def deliver_appliance(self, appliance_id, payload, headers):
        return self._request(
            "POST", f"/appliances/{appliance_id}/deliver", payload, headers
        )

    def capture_proof_of_delivery(self, appliance_id, payload, headers):
        return self._request(
            "POST", f"/appliances/{appliance_id}/proof-of-delivery", payload, headers
        )

    def declare_plateau(self, appliance_id, payload, headers):
        return self._request(
            "POST", f"/appliances/{appliance_id}/plateau", payload, headers
        )

    def remediate_recall(self, appliance_id, payload, headers):
        return self._request(
            "POST", f"/appliances/{appliance_id}/recall-remediate", payload, headers
        )

    def perform_recall_check(self, appliance_id, payload, headers):
        return self._request(
            "POST", f"/appliances/{appliance_id}/recall-check", payload, headers
        )

    def get_adherence_summary(self, appliance_id, headers):
        return self._request(
            "GET", f"/appliances/{appliance_id}/adherence-summary", headers=headers
        )

    # -------------------------------------------------------- titration visits
    def create_titration_visit(self, payload, headers):
        return self._request("POST", "/titration-visits", payload, headers)

    def get_titration_visit(self, visit_id, headers):
        return self._request("GET", f"/titration-visits/{visit_id}", headers=headers)

    def list_titration_visits(self, headers, params=None):
        return self._request(
            "GET", "/titration-visits", headers=headers, params=params
        )

    def apply_titration_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/titration-visits/{visit_id}/apply", payload, headers
        )

    # ----------------------------------------------------- adherence downloads
    def create_adherence_download(self, payload, headers):
        return self._request("POST", "/adherence-downloads", payload, headers)

    def get_adherence_download(self, adherence_download_id, headers):
        return self._request(
            "GET", f"/adherence-downloads/{adherence_download_id}", headers=headers
        )

    def list_adherence_downloads(self, headers, params=None):
        return self._request(
            "GET", "/adherence-downloads", headers=headers, params=params
        )

    # -------------------------------------------------------- efficacy reports
    def create_efficacy_report(self, payload, headers):
        return self._request("POST", "/efficacy-reports", payload, headers)

    def get_efficacy_report(self, report_id, headers):
        return self._request("GET", f"/efficacy-reports/{report_id}", headers=headers)

    def list_efficacy_reports(self, headers, params=None):
        return self._request("GET", "/efficacy-reports", headers=headers, params=params)

    def submit_efficacy_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/efficacy-reports/{report_id}/submit", payload, headers
        )

    def physician_respond_to_efficacy_report(self, report_id, payload, headers):
        return self._request(
            "POST",
            f"/efficacy-reports/{report_id}/physician-response",
            payload,
            headers,
        )

    # ----------------------------------------------------------------- claims
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def appeal_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/appeal", payload, headers)

    # ---------------------------------------------------------- repair orders
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request(
            "GET", f"/repair-orders/{repair_order_id}", headers=headers
        )

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def complete_repair_order(self, repair_order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/complete", payload, headers
        )

    # ------------------------------------------------------------ audit holds
    def create_audit_hold(self, payload, headers):
        return self._request("POST", "/audit-holds", payload, headers)

    def get_audit_hold(self, audit_hold_id, headers):
        return self._request("GET", f"/audit-holds/{audit_hold_id}", headers=headers)

    def list_audit_holds(self, headers, params=None):
        return self._request("GET", "/audit-holds", headers=headers, params=params)

    def close_audit_hold(self, audit_hold_id, payload, headers):
        return self._request(
            "POST", f"/audit-holds/{audit_hold_id}/close", payload, headers
        )


api_client = ApiClient()
