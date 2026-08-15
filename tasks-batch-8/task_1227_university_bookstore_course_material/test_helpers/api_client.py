"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/bookstore/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- terms ---
    def create_term(self, payload, headers):
        return self._request("POST", "/bookstore/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/bookstore/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/bookstore/terms/{term_id}", headers=headers)

    def open_adoption(self, term_id, headers):
        return self._request(
            "POST", f"/bookstore/terms/{term_id}/open-adoption", {}, headers
        )

    def close_adoption(self, term_id, headers):
        return self._request(
            "POST", f"/bookstore/terms/{term_id}/close-adoption", {}, headers
        )

    def open_sales(self, term_id, headers):
        return self._request(
            "POST", f"/bookstore/terms/{term_id}/open-sales", {}, headers
        )

    def run_census_billing(self, term_id, headers):
        return self._request(
            "POST", f"/bookstore/terms/{term_id}/run-census-billing", {}, headers
        )

    def open_buyback(self, term_id, headers):
        return self._request(
            "POST", f"/bookstore/terms/{term_id}/open-buyback", {}, headers
        )

    def close_term(self, term_id, headers):
        return self._request("POST", f"/bookstore/terms/{term_id}/close", {}, headers)

    # --- publishers & agreements ---
    def create_publisher(self, payload, headers):
        return self._request("POST", "/bookstore/publishers", payload, headers)

    def list_publishers(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/publishers", headers=headers, params=params
        )

    def get_publisher(self, publisher_id, headers):
        return self._request(
            "GET", f"/bookstore/publishers/{publisher_id}", headers=headers
        )

    def create_agreement(self, publisher_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/publishers/{publisher_id}/agreements",
            payload, headers,
        )

    def list_agreements(self, publisher_id, headers, params=None):
        return self._request(
            "GET", f"/bookstore/publishers/{publisher_id}/agreements",
            headers=headers, params=params,
        )

    # --- titles & wholesale quotes ---
    def create_title(self, payload, headers):
        return self._request("POST", "/bookstore/titles", payload, headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/bookstore/titles", headers=headers, params=params)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/bookstore/titles/{title_id}", headers=headers)

    def create_wholesale_quote(self, title_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/titles/{title_id}/wholesale-quotes",
            payload, headers,
        )

    def list_wholesale_quotes(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/bookstore/titles/{title_id}/wholesale-quotes",
            headers=headers, params=params,
        )

    # --- faculty & students ---
    def create_faculty(self, payload, headers):
        return self._request("POST", "/bookstore/faculty", payload, headers)

    def get_faculty(self, faculty_id, headers):
        return self._request("GET", f"/bookstore/faculty/{faculty_id}", headers=headers)

    def create_student(self, payload, headers):
        return self._request("POST", "/bookstore/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/bookstore/students/{student_id}", headers=headers)

    def adjust_aid(self, student_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/students/{student_id}/aid-adjustments",
            payload, headers,
        )

    # --- sections & enrollments ---
    def create_section(self, payload, headers):
        return self._request("POST", "/bookstore/sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/bookstore/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/bookstore/sections/{section_id}", headers=headers)

    def open_section(self, section_id, headers):
        return self._request(
            "POST", f"/bookstore/sections/{section_id}/open", {}, headers
        )

    def lock_section(self, section_id, headers):
        return self._request(
            "POST", f"/bookstore/sections/{section_id}/lock", {}, headers
        )

    def enroll_student(self, section_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/sections/{section_id}/enrollments",
            payload, headers,
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/bookstore/enrollments/{enrollment_id}", headers=headers
        )

    def drop_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/bookstore/enrollments/{enrollment_id}/drop", {}, headers
        )

    # --- adoptions ---
    def create_adoption(self, payload, headers):
        return self._request("POST", "/bookstore/adoptions", payload, headers)

    def list_adoptions(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/adoptions", headers=headers, params=params
        )

    def get_adoption(self, adoption_id, headers):
        return self._request(
            "GET", f"/bookstore/adoptions/{adoption_id}", headers=headers
        )

    def patch_adoption(self, adoption_id, payload, headers):
        return self._request(
            "PATCH", f"/bookstore/adoptions/{adoption_id}", payload, headers
        )

    def submit_adoption(self, adoption_id, headers):
        return self._request(
            "POST", f"/bookstore/adoptions/{adoption_id}/submit", {}, headers
        )

    def start_review_adoption(self, adoption_id, headers):
        return self._request(
            "POST", f"/bookstore/adoptions/{adoption_id}/start-review", {}, headers
        )

    def approve_adoption(self, adoption_id, headers):
        return self._request(
            "POST", f"/bookstore/adoptions/{adoption_id}/approve", {}, headers
        )

    def return_adoption(self, adoption_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/adoptions/{adoption_id}/return", payload, headers
        )

    def get_adoption_buy_plan(self, adoption_id, headers):
        return self._request(
            "GET", f"/bookstore/adoptions/{adoption_id}/buy-plan", headers=headers
        )

    # --- buy plans ---
    def get_buy_plan(self, plan_id, headers):
        return self._request("GET", f"/bookstore/buy-plans/{plan_id}", headers=headers)

    def patch_buy_plan(self, plan_id, payload, headers):
        return self._request(
            "PATCH", f"/bookstore/buy-plans/{plan_id}", payload, headers
        )

    def commit_buy_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/buy-plans/{plan_id}/commit", payload, headers
        )

    def receive_buy_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/buy-plans/{plan_id}/receive", payload, headers
        )

    def cancel_buy_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/bookstore/buy-plans/{plan_id}/cancel", {}, headers
        )

    # --- orders & order lines ---
    def create_order(self, payload, headers):
        return self._request("POST", "/bookstore/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/bookstore/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/bookstore/orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/bookstore/orders/{order_id}/lines", headers=headers, params=params
        )

    def list_all_order_lines(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/order-lines", headers=headers, params=params
        )

    def get_order_line(self, line_id, headers):
        return self._request(
            "GET", f"/bookstore/order-lines/{line_id}", headers=headers
        )

    def return_order_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/orders/{order_id}/lines/{line_id}/return",
            payload, headers,
        )

    # --- inclusive-access charges ---
    def list_ia_charges(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/inclusive-access-charges", headers=headers, params=params
        )

    def get_ia_charge(self, charge_id, headers):
        return self._request(
            "GET", f"/bookstore/inclusive-access-charges/{charge_id}", headers=headers
        )

    def opt_out_ia_charge(self, charge_id, headers):
        return self._request(
            "POST", f"/bookstore/inclusive-access-charges/{charge_id}/opt-out",
            {}, headers,
        )

    def revoke_opt_out_ia_charge(self, charge_id, headers):
        return self._request(
            "POST",
            f"/bookstore/inclusive-access-charges/{charge_id}/revoke-opt-out",
            {}, headers,
        )

    def refund_ia_charge(self, charge_id, headers):
        return self._request(
            "POST", f"/bookstore/inclusive-access-charges/{charge_id}/refund",
            {}, headers,
        )

    # --- buyback tickets ---
    def create_buyback_ticket(self, payload, headers):
        return self._request("POST", "/bookstore/buyback-tickets", payload, headers)

    def list_buyback_tickets(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/buyback-tickets", headers=headers, params=params
        )

    def get_buyback_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/bookstore/buyback-tickets/{ticket_id}", headers=headers
        )

    def accept_buyback_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/bookstore/buyback-tickets/{ticket_id}/accept", {}, headers
        )

    def pay_buyback_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/bookstore/buyback-tickets/{ticket_id}/pay", {}, headers
        )

    def reject_buyback_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/bookstore/buyback-tickets/{ticket_id}/reject", payload, headers
        )

    # --- commission statements ---
    def create_commission_statement(self, payload, headers):
        return self._request(
            "POST", "/bookstore/commission-statements", payload, headers
        )

    def list_commission_statements(self, headers, params=None):
        return self._request(
            "GET", "/bookstore/commission-statements", headers=headers, params=params
        )

    def get_commission_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/bookstore/commission-statements/{statement_id}", headers=headers
        )

    def issue_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/bookstore/commission-statements/{statement_id}/issue",
            {}, headers,
        )

    def settle_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/bookstore/commission-statements/{statement_id}/settle",
            {}, headers,
        )


api_client = ApiClient()
