"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Client accounts ---
    def create_client(self, payload, headers):
        return self._request("POST", "/bpp/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/bpp/clients/{client_id}", headers=headers)

    def list_client_forecasts(self, client_id, headers, params=None):
        return self._request("GET", f"/bpp/clients/{client_id}/accrual-forecasts",
                             headers=headers, params=params)

    def list_client_audit_events(self, client_id, headers, params=None):
        return self._request("GET", f"/bpp/clients/{client_id}/audit-events",
                             headers=headers, params=params)

    def publish_forecast(self, client_id, payload, headers):
        return self._request("POST", f"/bpp/clients/{client_id}/accrual-forecasts",
                             payload, headers)

    # --- Operators ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/bpp/operators", payload, headers)

    # --- Jurisdictions and class rules ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/bpp/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/bpp/jurisdictions/{jurisdiction_id}", headers=headers)

    def create_class_rule(self, payload, headers):
        return self._request("POST", "/bpp/class-rules", payload, headers)

    def list_class_rules(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/bpp/jurisdictions/{jurisdiction_id}/class-rules",
                             headers=headers, params=params)

    # --- Assets and disposals ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/bpp/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/bpp/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/bpp/assets", headers=headers, params=params)

    def classify_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/bpp/assets/{asset_id}/classify", payload, headers)

    def create_disposal(self, asset_id, payload, headers):
        return self._request("POST", f"/bpp/assets/{asset_id}/disposals", payload, headers)

    def list_disposals(self, asset_id, headers, params=None):
        return self._request("GET", f"/bpp/assets/{asset_id}/disposals",
                             headers=headers, params=params)

    def reverse_disposal(self, disposal_id, headers):
        return self._request("POST", f"/bpp/disposals/{disposal_id}/reverse", {}, headers)

    # --- Renditions ---
    def create_rendition(self, payload, headers):
        return self._request("POST", "/bpp/renditions", payload, headers)

    def get_rendition(self, rendition_id, headers):
        return self._request("GET", f"/bpp/renditions/{rendition_id}", headers=headers)

    def list_renditions(self, headers, params=None):
        return self._request("GET", "/bpp/renditions", headers=headers, params=params)

    def generate_lines(self, rendition_id, headers):
        return self._request("POST", f"/bpp/renditions/{rendition_id}/generate-lines",
                             {}, headers)

    def file_rendition(self, rendition_id, headers):
        return self._request("POST", f"/bpp/renditions/{rendition_id}/file", {}, headers)

    def amend_rendition(self, rendition_id, payload, headers):
        return self._request("POST", f"/bpp/renditions/{rendition_id}/amendments",
                             payload, headers)

    # --- Filing extensions ---
    def create_extension(self, rendition_id, payload, headers):
        return self._request("POST", f"/bpp/renditions/{rendition_id}/extensions",
                             payload, headers)

    def list_extensions(self, rendition_id, headers, params=None):
        return self._request("GET", f"/bpp/renditions/{rendition_id}/extensions",
                             headers=headers, params=params)

    # --- Assessment notices ---
    def create_notice(self, rendition_id, payload, headers):
        return self._request("POST", f"/bpp/renditions/{rendition_id}/assessment-notices",
                             payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/bpp/assessment-notices/{notice_id}", headers=headers)

    def list_notices(self, rendition_id, headers, params=None):
        return self._request("GET", f"/bpp/renditions/{rendition_id}/assessment-notices",
                             headers=headers, params=params)

    def accept_notice(self, notice_id, headers):
        return self._request("POST", f"/bpp/assessment-notices/{notice_id}/accept",
                             {}, headers)

    # --- Appeals ---
    def create_appeal(self, notice_id, payload, headers):
        return self._request("POST", f"/bpp/assessment-notices/{notice_id}/appeals",
                             payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/bpp/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, notice_id, headers, params=None):
        return self._request("GET", f"/bpp/assessment-notices/{notice_id}/appeals",
                             headers=headers, params=params)

    def schedule_hearing(self, appeal_id, payload, headers):
        return self._request("POST", f"/bpp/appeals/{appeal_id}/schedule-hearing",
                             payload, headers)

    def record_decision(self, appeal_id, payload, headers):
        return self._request("POST", f"/bpp/appeals/{appeal_id}/record-decision",
                             payload, headers)

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/bpp/appeals/{appeal_id}/resolve", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/bpp/appeals/{appeal_id}/withdraw", {}, headers)

    def close_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/bpp/appeals/{appeal_id}/close", payload, headers)

    # --- Tax bills and payment scheduling ---
    def create_tax_bill(self, notice_id, payload, headers):
        return self._request("POST", f"/bpp/assessment-notices/{notice_id}/tax-bills",
                             payload, headers)

    def get_tax_bill(self, bill_id, headers):
        return self._request("GET", f"/bpp/tax-bills/{bill_id}", headers=headers)

    def list_tax_bills(self, notice_id, headers, params=None):
        return self._request("GET", f"/bpp/assessment-notices/{notice_id}/tax-bills",
                             headers=headers, params=params)

    def validate_bill(self, bill_id, headers):
        return self._request("POST", f"/bpp/tax-bills/{bill_id}/validate", {}, headers)

    def create_payment_schedule(self, bill_id, payload, headers):
        return self._request("POST", f"/bpp/tax-bills/{bill_id}/payment-schedule",
                             payload, headers)

    def cancel_payment_schedule(self, bill_id, headers):
        return self._request("POST", f"/bpp/tax-bills/{bill_id}/payment-schedule/cancel",
                             {}, headers)

    def pay_installment(self, bill_id, payload, headers):
        return self._request("POST", f"/bpp/tax-bills/{bill_id}/pay-installment",
                             payload, headers)

    # --- Exemptions ---
    def create_exemption_application(self, asset_id, payload, headers):
        return self._request("POST", f"/bpp/assets/{asset_id}/exemption-applications",
                             payload, headers)

    def get_exemption_application(self, application_id, headers):
        return self._request("GET", f"/bpp/exemption-applications/{application_id}",
                             headers=headers)

    def list_exemption_applications(self, asset_id, headers, params=None):
        return self._request("GET", f"/bpp/assets/{asset_id}/exemption-applications",
                             headers=headers, params=params)

    def submit_exemption_application(self, application_id, headers):
        return self._request("POST",
                             f"/bpp/exemption-applications/{application_id}/submit",
                             {}, headers)

    def review_exemption_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/bpp/exemption-applications/{application_id}/review",
                             payload, headers)

    def exemption_compliance(self, application_id, payload, headers):
        return self._request("POST",
                             f"/bpp/exemption-applications/{application_id}/compliance",
                             payload, headers)

    # --- Abatements ---
    def create_abatement(self, asset_id, payload, headers):
        return self._request("POST", f"/bpp/assets/{asset_id}/abatements", payload, headers)

    def get_abatement(self, agreement_id, headers):
        return self._request("GET", f"/bpp/abatements/{agreement_id}", headers=headers)

    def list_abatements(self, asset_id, headers, params=None):
        return self._request("GET", f"/bpp/assets/{asset_id}/abatements",
                             headers=headers, params=params)

    def recertify_abatement(self, agreement_id, payload, headers):
        return self._request("POST", f"/bpp/abatements/{agreement_id}/recertify",
                             payload, headers)

    def terminate_abatement(self, agreement_id, headers):
        return self._request("POST", f"/bpp/abatements/{agreement_id}/terminate",
                             {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/bpp/_clock/set-current-utc", payload, headers)


api_client = ApiClient()
