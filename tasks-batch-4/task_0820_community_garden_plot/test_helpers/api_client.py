"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Garden ----
    def create_garden(self, payload, headers):
        return self._request("POST", "/gardens", payload, headers)

    def get_garden(self, garden_id, headers):
        return self._request("GET", f"/gardens/{garden_id}", headers=headers)

    def list_garden_tools(self, garden_id, headers, params=None):
        return self._request("GET", f"/gardens/{garden_id}/tools",
                             headers=headers, params=params)

    def list_garden_shed_bookings(self, garden_id, headers, params=None):
        return self._request("GET", f"/gardens/{garden_id}/shed-bookings",
                             headers=headers, params=params)

    def expire_offers(self, garden_id, headers):
        return self._request("POST", f"/gardens/{garden_id}/expire-offers", {}, headers)

    # ---- Plot ----
    def create_plot(self, payload, headers):
        return self._request("POST", "/plots", payload, headers)

    def get_plot(self, plot_id, headers):
        return self._request("GET", f"/plots/{plot_id}", headers=headers)

    def list_plots(self, headers, params=None):
        return self._request("GET", "/plots", headers=headers, params=params)

    def offer_plot(self, plot_id, headers):
        return self._request("POST", f"/plots/{plot_id}/offer", {}, headers)

    def assign_plot(self, plot_id, payload, headers):
        return self._request("POST", f"/plots/{plot_id}/assign", payload, headers)

    # ---- Gardener ----
    def create_gardener(self, payload, headers):
        return self._request("POST", "/gardeners", payload, headers)

    def get_gardener(self, gardener_id, headers):
        return self._request("GET", f"/gardeners/{gardener_id}", headers=headers)

    def list_gardener_shed_bookings(self, gardener_id, headers, params=None):
        return self._request("GET", f"/gardeners/{gardener_id}/shed-bookings",
                             headers=headers, params=params)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def accept_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/accept", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    # ---- Assignment ----
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def request_renewal(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/request-renewal", {}, headers)

    def confirm_renewal(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm-renewal", {}, headers)

    def settle_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/settle", {}, headers)

    def forfeit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/forfeit", {}, headers)

    def pay_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/pay", payload, headers)

    def waive_fee(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/waive-fee", {}, headers)

    def refund_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/refund", payload, headers)

    # ---- WorkLog ----
    def create_work_log(self, payload, headers):
        return self._request("POST", "/work-logs", payload, headers)

    def list_work_logs(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/work-logs",
                             headers=headers, params=params)

    # ---- WaterReading ----
    def create_water_reading(self, payload, headers):
        return self._request("POST", "/water-readings", payload, headers)

    def list_water_readings(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/water-readings",
                             headers=headers, params=params)

    # ---- ComplianceCase ----
    def create_compliance_case(self, payload, headers):
        return self._request("POST", "/compliance-cases", payload, headers)

    def get_compliance_case(self, case_id, headers):
        return self._request("GET", f"/compliance-cases/{case_id}", headers=headers)

    def list_compliance_cases(self, headers, params=None):
        return self._request("GET", "/compliance-cases", headers=headers, params=params)

    def warn_case(self, case_id, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/warn", {}, headers)

    def resolve_case(self, case_id, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/resolve", {}, headers)

    def escalate_case(self, case_id, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/escalate", {}, headers)

    # ---- Tool ----
    def create_tool(self, payload, headers):
        return self._request("POST", "/tools", payload, headers)

    # ---- ToolLoan ----
    def create_tool_loan(self, payload, headers):
        return self._request("POST", "/tool-loans", payload, headers)

    def get_tool_loan(self, loan_id, headers):
        return self._request("GET", f"/tool-loans/{loan_id}", headers=headers)

    def list_tool_loans(self, headers, params=None):
        return self._request("GET", "/tool-loans", headers=headers, params=params)

    def return_tool_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/tool-loans/{loan_id}/return", payload, headers)

    # ---- ShedBooking ----
    def create_shed_booking(self, payload, headers):
        return self._request("POST", "/shed-bookings", payload, headers)


api_client = ApiClient()
