"""HTTP client for the fire-staffing-overtime API.

One method per endpoint declared by the PRD's endpoint table. Every method
returns the raw response so tests can assert both status codes and bodies.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fire-ops"


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the fire department staffing API."""

    # ------------------------------------------------------------------
    # Logical duty clock
    # ------------------------------------------------------------------
    def set_clock(self, now: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", {"now": now}, headers)

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def create_station(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/stations", payload, headers)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/stations/{station_id}", None, headers)

    def list_stations(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/stations", filters, headers)

    def get_overtime_forecast(
        self,
        station_id: str,
        headers: Dict[str, str],
        method: Optional[str] = None,
    ):
        params: Dict[str, Any] = {}
        if method is not None:
            params["method"] = method
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/overtime-forecast", params, headers
        )

    def get_academy_hiring_signal(self, station_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/academy-hiring-signal", None, headers
        )

    # ------------------------------------------------------------------
    # Apparatus
    # ------------------------------------------------------------------
    def create_apparatus(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/apparatus", payload, headers)

    def get_apparatus(self, apparatus_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/apparatus/{apparatus_id}", None, headers)

    def list_apparatus(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/apparatus", filters, headers)

    # ------------------------------------------------------------------
    # Firefighters
    # ------------------------------------------------------------------
    def create_firefighter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/firefighters", payload, headers)

    def get_firefighter(self, firefighter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/firefighters/{firefighter_id}", None, headers
        )

    def list_firefighters(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/firefighters", filters, headers)

    def set_availability(
        self, firefighter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/firefighters/{firefighter_id}/availability", payload, headers
        )

    # ------------------------------------------------------------------
    # Hiring rosters
    # ------------------------------------------------------------------
    def create_hiring_roster(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/hiring-rosters", payload, headers)

    def get_hiring_roster(self, hiring_roster_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/hiring-rosters/{hiring_roster_id}", None, headers
        )

    def list_hiring_rosters(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/hiring-rosters", filters, headers)

    # ------------------------------------------------------------------
    # Duty shifts
    # ------------------------------------------------------------------
    def create_duty_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/duty-shifts", payload, headers)

    def get_duty_shift(self, duty_shift_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/duty-shifts/{duty_shift_id}", None, headers
        )

    def list_duty_shifts(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/duty-shifts", filters, headers)

    def publish_duty_shift(
        self, duty_shift_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{duty_shift_id}/publish", payload or {}, headers
        )

    def staffing_run(
        self, duty_shift_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/duty-shifts/{duty_shift_id}/staffing-run",
            payload or {},
            headers,
        )

    def leave_adjudication(
        self, duty_shift_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/duty-shifts/{duty_shift_id}/leave-adjudication",
            payload or {},
            headers,
        )

    def company_closure(
        self, duty_shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/duty-shifts/{duty_shift_id}/company-closure",
            payload,
            headers,
        )

    def complete_duty_shift(
        self, duty_shift_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{duty_shift_id}/complete", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Shift assignments
    # ------------------------------------------------------------------
    def create_shift_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/shift-assignments", payload, headers)

    def get_shift_assignment(self, shift_assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/shift-assignments/{shift_assignment_id}", None, headers
        )

    def list_shift_assignments(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/shift-assignments", filters, headers)

    def cancel_shift_assignment(
        self, shift_assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/shift-assignments/{shift_assignment_id}/cancel",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Leave requests
    # ------------------------------------------------------------------
    def create_leave_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/leave-requests", payload, headers)

    def get_leave_request(self, leave_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/leave-requests/{leave_request_id}", None, headers
        )

    def list_leave_requests(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/leave-requests", filters, headers)

    def revoke_leave_request(
        self,
        leave_request_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PREFIX}/leave-requests/{leave_request_id}/revoke",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Trade requests
    # ------------------------------------------------------------------
    def create_trade_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/trade-requests", payload, headers)

    def get_trade_request(self, trade_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/trade-requests/{trade_request_id}", None, headers
        )

    def list_trade_requests(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/trade-requests", filters, headers)

    def countersign_trade_request(
        self,
        trade_request_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PREFIX}/trade-requests/{trade_request_id}/countersign",
            payload or {},
            headers,
        )

    def decide_trade_request(
        self, trade_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/trade-requests/{trade_request_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Vacancies
    # ------------------------------------------------------------------
    def get_vacancy(self, vacancy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/vacancies/{vacancy_id}", None, headers)

    def list_vacancies(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/vacancies", filters, headers)

    def offer_vacancy(
        self, vacancy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/vacancies/{vacancy_id}/offer", payload, headers
        )

    # ------------------------------------------------------------------
    # Overtime offers
    # ------------------------------------------------------------------
    def get_overtime_offer(self, overtime_offer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/overtime-offers/{overtime_offer_id}", None, headers
        )

    def list_overtime_offers(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/overtime-offers", filters, headers)

    def respond_to_offer(
        self, overtime_offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/overtime-offers/{overtime_offer_id}/response",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Work periods
    # ------------------------------------------------------------------
    def get_work_period(self, work_period_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/work-periods/{work_period_id}", None, headers
        )

    def list_work_periods(self, headers: Dict[str, str], **filters):
        return self._request("GET", f"{PREFIX}/work-periods", filters, headers)

    def hour_adjustment(
        self, work_period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/work-periods/{work_period_id}/hour-adjustment",
            payload,
            headers,
        )
