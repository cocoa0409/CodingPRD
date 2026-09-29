"""API client: one method per endpoint the PRD defines.

Also holds the timestamp canonicaliser. The PRD renders instants as ISO 8601
UTC with three fractional digits; tests compare instants through
``canonical_instant()`` so that an equivalent rendering of the same moment
(``Z`` vs ``+00:00``, or a differing number of fractional digits) never fails a
comparison on formatting alone.
"""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Returns the input untouched when it is not a parseable instant (None,
    a date-only string, or anything else), so callers can pass through
    optional fields safely.
    """
    if not isinstance(value, str) or "T" not in value:
        return value
    text = value.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


class ApiClient(GenericApiClient):
    # --- Logical clock test hook ---
    def set_current_utc(self, current_utc: str, headers=None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers or {"Content-Type": "application/json"},
        )

    # --- Installations ---
    def create_installation(self, payload, headers):
        return self._request("POST", "/installations", payload, headers)

    def get_installation(self, installation_id, headers):
        return self._request(
            "GET", f"/installations/{installation_id}", headers=headers
        )

    def list_installation_bah_rates(self, installation_id, headers, params=None):
        return self._request(
            "GET",
            f"/installations/{installation_id}/bah-rates",
            headers=headers,
            params=params,
        )

    def run_waitlist_offer_run(self, installation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/installations/{installation_id}/waitlist-offer-run",
            payload,
            headers,
        )

    def run_allotment_run(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/installations/{installation_id}/allotment-run", payload, headers
        )

    # --- BAH rates ---
    def create_bah_rate(self, payload, headers):
        return self._request("POST", "/bah-rates", payload, headers)

    # --- Housing units ---
    def create_housing_unit(self, payload, headers):
        return self._request("POST", "/housing-units", payload, headers)

    def get_housing_unit(self, housing_unit_id, headers):
        return self._request(
            "GET", f"/housing-units/{housing_unit_id}", headers=headers
        )

    def list_housing_units(self, headers, params=None):
        return self._request("GET", "/housing-units", headers=headers, params=params)

    def set_housing_unit_status(self, housing_unit_id, payload, headers):
        return self._request(
            "POST", f"/housing-units/{housing_unit_id}/status", payload, headers
        )

    # --- Service members and dependents ---
    def create_service_member(self, payload, headers):
        return self._request("POST", "/service-members", payload, headers)

    def get_service_member(self, service_member_id, headers):
        return self._request(
            "GET", f"/service-members/{service_member_id}", headers=headers
        )

    def list_service_member_dependents(self, service_member_id, headers, params=None):
        return self._request(
            "GET",
            f"/service-members/{service_member_id}/dependents",
            headers=headers,
            params=params,
        )

    def record_orders(self, service_member_id, payload, headers):
        return self._request(
            "POST", f"/service-members/{service_member_id}/orders", payload, headers
        )

    def create_dependent(self, payload, headers):
        return self._request("POST", "/dependents", payload, headers)

    # --- Waitlist applications ---
    def create_waitlist_application(self, payload, headers):
        return self._request("POST", "/waitlist-applications", payload, headers)

    def get_waitlist_application(self, application_id, headers):
        return self._request(
            "GET", f"/waitlist-applications/{application_id}", headers=headers
        )

    def list_waitlist_applications(self, headers, params=None):
        return self._request(
            "GET", "/waitlist-applications", headers=headers, params=params
        )

    def recertify_waitlist_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/waitlist-applications/{application_id}/recertify",
            payload,
            headers,
        )

    def accept_offer(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/waitlist-applications/{application_id}/accept-offer",
            payload,
            headers,
        )

    def decline_offer(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/waitlist-applications/{application_id}/decline-offer",
            payload,
            headers,
        )

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def list_lease_move_in_inspections(self, lease_id, headers, params=None):
        return self._request(
            "GET",
            f"/leases/{lease_id}/move-in-inspections",
            headers=headers,
            params=params,
        )

    def list_lease_allotment_transactions(self, lease_id, headers, params=None):
        return self._request(
            "GET",
            f"/leases/{lease_id}/allotment-transactions",
            headers=headers,
            params=params,
        )

    def redetermine_rent(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/rent-redetermination", payload, headers
        )

    def move_in(self, lease_id, headers, payload=None):
        return self._request("POST", f"/leases/{lease_id}/move-in", payload, headers)

    def give_termination_notice(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/termination-notice", payload, headers
        )

    def terminate_lease(self, lease_id, headers, payload=None):
        return self._request("POST", f"/leases/{lease_id}/terminate", payload, headers)

    # --- Move-in inspections ---
    def create_move_in_inspection(self, payload, headers):
        return self._request("POST", "/move-in-inspections", payload, headers)

    def get_move_in_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/move-in-inspections/{inspection_id}", headers=headers
        )

    def log_deficiencies(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/move-in-inspections/{inspection_id}/deficiencies", payload, headers
        )

    def tenant_acknowledge(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"/move-in-inspections/{inspection_id}/tenant-acknowledge",
            payload,
            headers,
        )

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/assign", payload, headers
        )

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/start", payload, headers
        )

    def complete_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def reopen_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/reopen", payload, headers
        )

    def escalate_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/escalate", payload, headers
        )

    # --- Hazard cases ---
    def create_hazard_case(self, payload, headers):
        return self._request("POST", "/hazard-cases", payload, headers)

    def get_hazard_case(self, hazard_case_id, headers):
        return self._request("GET", f"/hazard-cases/{hazard_case_id}", headers=headers)

    def list_hazard_cases(self, headers, params=None):
        return self._request("GET", "/hazard-cases", headers=headers, params=params)

    def assess_hazard_case(self, hazard_case_id, payload, headers):
        return self._request(
            "POST", f"/hazard-cases/{hazard_case_id}/assess", payload, headers
        )

    def certify_clearance(self, hazard_case_id, payload, headers):
        return self._request(
            "POST", f"/hazard-cases/{hazard_case_id}/clearance", payload, headers
        )

    def void_hazard_case(self, hazard_case_id, payload, headers):
        return self._request(
            "POST", f"/hazard-cases/{hazard_case_id}/void", payload, headers
        )

    # --- Displacement lodgings ---
    def create_displacement_lodging(self, payload, headers):
        return self._request("POST", "/displacement-lodgings", payload, headers)

    def get_displacement_lodging(self, lodging_id, headers):
        return self._request(
            "GET", f"/displacement-lodgings/{lodging_id}", headers=headers
        )

    def list_displacement_lodgings(self, headers, params=None):
        return self._request(
            "GET", "/displacement-lodgings", headers=headers, params=params
        )

    def close_displacement_lodging(self, lodging_id, payload, headers):
        return self._request(
            "POST", f"/displacement-lodgings/{lodging_id}/close", payload, headers
        )

    # --- Dispute cases ---
    def create_dispute_case(self, payload, headers):
        return self._request("POST", "/dispute-cases", payload, headers)

    def get_dispute_case(self, dispute_case_id, headers):
        return self._request(
            "GET", f"/dispute-cases/{dispute_case_id}", headers=headers
        )

    def list_dispute_cases(self, headers, params=None):
        return self._request("GET", "/dispute-cases", headers=headers, params=params)

    def propose_resolution(self, dispute_case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{dispute_case_id}/propose-resolution", payload, headers
        )

    def respond_to_proposal(self, dispute_case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{dispute_case_id}/respond", payload, headers
        )

    def decide_escalated_dispute(self, dispute_case_id, payload, headers):
        return self._request(
            "POST",
            f"/dispute-cases/{dispute_case_id}/installation-decision",
            payload,
            headers,
        )

    # --- Reinvestment accounts ---
    def create_reinvestment_account(self, payload, headers):
        return self._request("POST", "/reinvestment-accounts", payload, headers)

    def get_reinvestment_account(self, account_id, headers):
        return self._request(
            "GET", f"/reinvestment-accounts/{account_id}", headers=headers
        )

    def list_reinvestment_accounts(self, headers, params=None):
        return self._request(
            "GET", "/reinvestment-accounts", headers=headers, params=params
        )

    def authorize_expenditure(self, account_id, payload, headers):
        return self._request(
            "POST", f"/reinvestment-accounts/{account_id}/expenditures", payload, headers
        )

    def run_metrics_run(self, account_id, payload, headers):
        return self._request(
            "POST", f"/reinvestment-accounts/{account_id}/metrics-run", payload, headers
        )

    # --- Raw escape hatch for header-omission tests ---
    def raw_post(self, path: str, payload=None, headers: Optional[dict] = None):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers: Optional[dict] = None, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
