"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/emissions"


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Emissions Monitoring API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ----------------------------------------------------------- facilities
    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def list_facilities(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/facilities", headers=headers, params=params)

    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def update_facility(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/facilities/{facility_id}", payload, headers
        )

    # ---------------------------------------------------------------- units
    def create_unit(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/facilities/{facility_id}/units", payload, headers
        )

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/units", headers=headers, params=params)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/units/{unit_id}", headers=headers)

    def set_unit_dispatch(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/units/{unit_id}/dispatch", payload, headers
        )

    # --------------------------------------------------- monitoring systems
    def install_monitoring_system(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/monitoring-systems", payload, headers
        )

    def list_monitoring_systems(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/monitoring-systems", headers=headers, params=params
        )

    def get_monitoring_system(self, system_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/monitoring-systems/{system_id}", headers=headers
        )

    def drive_qa_status(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/monitoring-systems/{system_id}/qa-status", payload, headers
        )

    # --------------------------------------------------- daily calibrations
    def record_daily_calibration(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/monitoring-systems/{system_id}/daily-calibrations",
            payload,
            headers,
        )

    def list_system_daily_calibrations(
        self, system_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/monitoring-systems/{system_id}/daily-calibrations",
            headers=headers,
            params=params,
        )

    def list_daily_calibrations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/daily-calibrations", headers=headers, params=params
        )

    def get_daily_calibration(self, calibration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/daily-calibrations/{calibration_id}", headers=headers
        )

    # ------------------------------------------------------------ RATA tests
    def schedule_rata_test(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/monitoring-systems/{system_id}/rata-tests",
            payload,
            headers,
        )

    def list_rata_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/rata-tests", headers=headers, params=params
        )

    def get_rata_test(self, rata_test_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/rata-tests/{rata_test_id}", headers=headers
        )

    def record_rata_runs(
        self, rata_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/rata-tests/{rata_test_id}/runs", payload, headers
        )

    def evaluate_rata_test(
        self, rata_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/rata-tests/{rata_test_id}/evaluate", payload, headers
        )

    def reschedule_rata_test(
        self, rata_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/rata-tests/{rata_test_id}/reschedule", payload, headers
        )

    # ---------------------------------------------------------- fuel samples
    def record_fuel_sample(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/fuel-samples", payload, headers
        )

    def list_fuel_samples(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/fuel-samples", headers=headers, params=params
        )

    def get_fuel_sample(self, fuel_sample_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/fuel-samples/{fuel_sample_id}", headers=headers
        )

    def record_fuel_analysis(
        self, fuel_sample_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/fuel-samples/{fuel_sample_id}/analysis", payload, headers
        )

    # ----------------------------------------------------- quarterly reports
    def open_quarterly_report(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/quarterly-reports", payload, headers
        )

    def list_quarterly_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/quarterly-reports", headers=headers, params=params
        )

    def get_quarterly_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/quarterly-reports/{report_id}", headers=headers
        )

    def validate_quarterly_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/quarterly-reports/{report_id}/validate", payload, headers
        )

    def submit_quarterly_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/quarterly-reports/{report_id}/submit", payload, headers
        )

    def sign_certification(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/quarterly-reports/{report_id}/certifications",
            payload,
            headers,
        )

    def list_report_certifications(
        self, report_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/quarterly-reports/{report_id}/certifications",
            headers=headers,
            params=params,
        )

    def list_certifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/certifications", headers=headers, params=params
        )

    def get_certification(self, certification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/certifications/{certification_id}", headers=headers
        )

    def revoke_certification(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certifications/{certification_id}/revoke",
            payload,
            headers,
        )

    def disposition_quarterly_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/quarterly-reports/{report_id}/disposition",
            payload,
            headers,
        )

    def reopen_quarterly_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/quarterly-reports/{report_id}/reopen", payload, headers
        )

    # ------------------------------------------------------- operating hours
    def append_operating_hour(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/operating-hours", payload, headers
        )

    def append_operating_hours_bulk(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/operating-hours/bulk", payload, headers
        )

    def list_operating_hours(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/operating-hours", headers=headers, params=params
        )

    def get_operating_hour(self, operating_hour_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/operating-hours/{operating_hour_id}", headers=headers
        )

    def run_missing_data_substitution(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/units/{unit_id}/missing-data/substitutions",
            payload,
            headers,
        )

    # --------------------------------------------------------- permit limits
    def create_permit_limit(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/permit-limits", payload, headers
        )

    def list_permit_limits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permit-limits", headers=headers, params=params
        )

    def get_permit_limit(self, permit_limit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/permit-limits/{permit_limit_id}", headers=headers
        )

    def evaluate_permit_limit(
        self, permit_limit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/permit-limits/{permit_limit_id}/evaluate",
            payload,
            headers,
        )

    # ------------------------------------------------ excess emission events
    def list_excess_emission_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/excess-emission-events", headers=headers, params=params
        )

    def get_excess_emission_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/excess-emission-events/{event_id}", headers=headers
        )

    def file_excess_emission_report(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/excess-emission-events/{event_id}/report",
            payload,
            headers,
        )

    def review_excess_emission_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/excess-emission-events/{event_id}/review",
            payload,
            headers,
        )

    def disposition_excess_emission_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/excess-emission-events/{event_id}/disposition",
            payload,
            headers,
        )

    # ----------------------------------------------------- allowance accounts
    def open_allowance_account(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/facilities/{facility_id}/allowance-accounts",
            payload,
            headers,
        )

    def list_allowance_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/allowance-accounts", headers=headers, params=params
        )

    def get_allowance_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/allowance-accounts/{account_id}", headers=headers
        )

    def run_true_up(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/allowance-accounts/{account_id}/true-up", payload, headers
        )

    # ------------------------------------------------- allowance transactions
    def propose_allowance_transaction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/allowance-transactions", payload, headers
        )

    def list_allowance_transactions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/allowance-transactions", headers=headers, params=params
        )

    def get_allowance_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/allowance-transactions/{transaction_id}", headers=headers
        )

    def transition_allowance_transaction(
        self, transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/allowance-transactions/{transaction_id}/transition",
            payload,
            headers,
        )

    # --------------------------------------------------------- control outages
    def plan_control_outage(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/control-outages", payload, headers
        )

    def list_control_outages(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/control-outages", headers=headers, params=params
        )

    def get_control_outage(self, outage_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/control-outages/{outage_id}", headers=headers
        )

    def transition_control_outage(
        self, outage_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/control-outages/{outage_id}/transition",
            payload,
            headers,
        )


api_client = ApiClient()
