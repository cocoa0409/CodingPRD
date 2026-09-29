"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the /elevator-program prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/elevator-program"


class ApiClient(GenericApiClient):
    # ─── contracts ──────────────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", params or {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/activate", {}, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/terminate", {}, headers
        )

    # ─── cars ───────────────────────────────────────────────────────────────
    def create_car(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cars", payload, headers)

    def get_car(self, car_id, headers):
        return self._request("GET", f"{PREFIX}/cars/{car_id}", headers=headers)

    def list_cars(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cars", params or {}, headers)

    def get_uptime_report(self, car_id, period_month, headers):
        return self._request(
            "GET",
            f"{PREFIX}/cars/{car_id}/uptime-report",
            {"period_month": period_month},
            headers,
        )

    def decommission_car(self, car_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cars/{car_id}/decommission", {}, headers
        )

    # ─── maintenance visits ─────────────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/visits", params or {}, headers)

    def perform_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/visits/{visit_id}/perform", payload, headers
        )

    def verify_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/verify", {}, headers)

    def dispute_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/visits/{visit_id}/dispute", payload, headers
        )

    # ─── callbacks ──────────────────────────────────────────────────────────
    def create_callback(self, payload, headers):
        return self._request("POST", f"{PREFIX}/callbacks", payload, headers)

    def get_callback(self, callback_id, headers):
        return self._request(
            "GET", f"{PREFIX}/callbacks/{callback_id}", headers=headers
        )

    def list_callbacks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/callbacks", params or {}, headers)

    def fire_dispatch_callback(self, callback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/callbacks/{callback_id}/fire-dispatch", payload, headers
        )

    def arrive_callback(self, callback_id, headers):
        return self._request(
            "POST", f"{PREFIX}/callbacks/{callback_id}/arrive", {}, headers
        )

    def clear_callback(self, callback_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/callbacks/{callback_id}/clear", payload or {}, headers
        )

    # ─── state inspections ──────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inspections", params or {}, headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    def post_certificate(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/post-certificate", {}, headers
        )

    # ─── modernization projects ─────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", params or {}, headers)

    def approve_project(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/approve", {}, headers
        )

    def complete_project(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/complete", {}, headers
        )

    # ─── downtime windows ───────────────────────────────────────────────────
    def create_downtime_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/downtime-windows", payload, headers)

    def get_downtime_window(self, window_id, headers):
        return self._request(
            "GET", f"{PREFIX}/downtime-windows/{window_id}", headers=headers
        )

    def list_downtime_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/downtime-windows", params or {}, headers)

    def cancel_downtime_window(self, window_id, headers):
        return self._request(
            "POST", f"{PREFIX}/downtime-windows/{window_id}/cancel", {}, headers
        )

    # ─── spare parts ────────────────────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts", params or {}, headers)

    def obsolete_part(self, part_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/parts/{part_id}/obsolete", payload or {}, headers
        )

    # ─── part orders ────────────────────────────────────────────────────────
    def create_part_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/part-orders", payload, headers)

    def get_part_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/part-orders/{order_id}", headers=headers)

    def list_part_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/part-orders", params or {}, headers)

    def receive_part_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/part-orders/{order_id}/receive", {}, headers
        )

    # ─── penalty assessments ────────────────────────────────────────────────
    def create_penalty(self, payload, headers):
        return self._request("POST", f"{PREFIX}/penalties", payload, headers)

    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"{PREFIX}/penalties/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/penalties", params or {}, headers)

    def dispute_penalty(self, penalty_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/penalties/{penalty_id}/dispute", payload, headers
        )

    def resolve_penalty(self, penalty_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/penalties/{penalty_id}/resolve", payload, headers
        )

    # ─── renegotiation rounds ───────────────────────────────────────────────
    def create_renegotiation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/renegotiations", payload, headers)

    def get_renegotiation(self, round_id, headers):
        return self._request(
            "GET", f"{PREFIX}/renegotiations/{round_id}", headers=headers
        )

    def list_renegotiations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/renegotiations", params or {}, headers)

    def counter_renegotiation(self, round_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/renegotiations/{round_id}/counter", payload, headers
        )

    def accept_renegotiation(self, round_id, headers):
        return self._request(
            "POST", f"{PREFIX}/renegotiations/{round_id}/accept", {}, headers
        )

    def close_renegotiation(self, round_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/renegotiations/{round_id}/close", payload, headers
        )

    # ─── logical clock ──────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
