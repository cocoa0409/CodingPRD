"""One method per endpoint of the Vehicle Distribution & Port Processing API.

Every method returns the raw ``requests.Response`` so a test can assert on the
status code and the error envelope as well as on the success payload.  Every
method takes the acting identity, because the contract requires both identity
headers on every request, reads included.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    PATH_ACCESSORY_KITS,
    PATH_ACCESSORY_WORK_ORDERS,
    PATH_BERTHS,
    PATH_CARRIER_CLAIMS,
    PATH_CENTERS,
    PATH_CLOCK_READ,
    PATH_CLOCK_SET,
    PATH_DAMAGE_SURVEYS,
    PATH_DEALERS,
    PATH_HOLD_ORDERS,
    PATH_QUALITY_INSPECTIONS,
    PATH_RELEASE_ORDERS,
    PATH_REPAIR_ORDERS,
    PATH_TRUCK_CARRIERS,
    PATH_VEHICLES,
    PATH_VESSELS,
)
from .test_users import TestUser


class VpcApiClient(GenericApiClient):
    """Endpoint-per-method client for the ``/vpc`` surface."""

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    def call(
        self,
        method: str,
        path: str,
        *,
        user: Optional[TestUser] = None,
        payload: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send one request.

        ``user`` supplies the two identity headers.  ``headers`` overrides them
        outright, which is how the malformed-identity cases are exercised.
        """
        if headers is None:
            headers = user.headers() if user is not None else {}
        return self._request(method, path, payload=payload, headers=headers, params=params)

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_CLOCK_SET, user=user, payload={"current_utc": current_utc}, **kw)

    def get_clock(self, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", PATH_CLOCK_READ, user=user, **kw)

    # ------------------------------------------------------------------
    # processing centers
    # ------------------------------------------------------------------
    def create_center(self, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_CENTERS, user=user, payload=payload, **kw)

    def get_center(self, center_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_CENTERS}/{center_id}", user=user, **kw)

    def list_centers(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_CENTERS, user=user, params=params, **kw)

    def get_dwell_metrics(self, center_id: str, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_CENTERS}/{center_id}/dwell-metrics", user=user, params=params, **kw)

    # ------------------------------------------------------------------
    # berths
    # ------------------------------------------------------------------
    def create_berth(self, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_BERTHS, user=user, payload=payload, **kw)

    def get_berth(self, berth_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_BERTHS}/{berth_id}", user=user, **kw)

    def list_berths(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_BERTHS, user=user, params=params, **kw)

    def patch_berth(self, berth_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        """A berth carries no update operation; used to prove the absence."""
        return self.call("PATCH", f"{PATH_BERTHS}/{berth_id}", user=user, payload=payload, **kw)

    def put_berth(self, berth_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("PUT", f"{PATH_BERTHS}/{berth_id}", user=user, payload=payload, **kw)

    def delete_berth(self, berth_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("DELETE", f"{PATH_BERTHS}/{berth_id}", user=user, **kw)

    # ------------------------------------------------------------------
    # vessels / voyages
    # ------------------------------------------------------------------
    def create_vessel(self, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_VESSELS, user=user, payload=payload, **kw)

    def get_vessel(self, vessel_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_VESSELS}/{vessel_id}", user=user, **kw)

    def list_vessels(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_VESSELS, user=user, params=params, **kw)

    def start_discharge(self, vessel_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VESSELS}/{vessel_id}/start-discharge", user=user, payload={}, **kw)

    def complete_discharge(self, vessel_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VESSELS}/{vessel_id}/complete-discharge", user=user, payload={}, **kw)

    def discharge_vehicle(self, vessel_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VESSELS}/{vessel_id}/vehicles", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # vehicles
    # ------------------------------------------------------------------
    def get_vehicle(self, vehicle_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_VEHICLES}/{vehicle_id}", user=user, **kw)

    def list_vehicles(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_VEHICLES, user=user, params=params, **kw)

    def prep_complete(self, vehicle_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/prep-complete", user=user, payload={}, **kw)

    # ------------------------------------------------------------------
    # damage surveys
    # ------------------------------------------------------------------
    def create_survey(self, vehicle_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/damage-surveys", user=user, payload=payload, **kw)

    def get_survey(self, survey_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_DAMAGE_SURVEYS}/{survey_id}", user=user, **kw)

    def list_surveys(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_DAMAGE_SURVEYS, user=user, params=params, **kw)

    def submit_survey(self, survey_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_DAMAGE_SURVEYS}/{survey_id}/submit", user=user, payload={}, **kw)

    def file_claim(self, survey_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_DAMAGE_SURVEYS}/{survey_id}/claims", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # carrier claims
    # ------------------------------------------------------------------
    def get_claim(self, claim_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_CARRIER_CLAIMS}/{claim_id}", user=user, **kw)

    def list_claims(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_CARRIER_CLAIMS, user=user, params=params, **kw)

    def carrier_response(self, claim_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_CARRIER_CLAIMS}/{claim_id}/carrier-response", user=user, payload=payload, **kw)

    def resubmit_claim(self, claim_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_CARRIER_CLAIMS}/{claim_id}/resubmit", user=user, payload=payload, **kw)

    def settle_claim(self, claim_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_CARRIER_CLAIMS}/{claim_id}/settle", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # repair orders
    # ------------------------------------------------------------------
    def create_repair_order(self, vehicle_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/repair-orders", user=user, payload=payload, **kw)

    def get_repair_order(self, repair_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_REPAIR_ORDERS}/{repair_order_id}", user=user, **kw)

    def list_repair_orders(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_REPAIR_ORDERS, user=user, params=params, **kw)

    def authorize_repair(self, repair_order_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_REPAIR_ORDERS}/{repair_order_id}/authorize", user=user, payload=payload, **kw)

    def complete_repair(self, repair_order_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_REPAIR_ORDERS}/{repair_order_id}/complete", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # accessory kits and work orders
    # ------------------------------------------------------------------
    def create_kit(self, center_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_CENTERS}/{center_id}/accessory-kits", user=user, payload=payload, **kw)

    def get_kit(self, kit_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_ACCESSORY_KITS}/{kit_id}", user=user, **kw)

    def list_kits(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_ACCESSORY_KITS, user=user, params=params, **kw)

    def create_work_order(self, vehicle_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/accessory-work-orders", user=user, payload=payload, **kw)

    def get_work_order(self, work_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_ACCESSORY_WORK_ORDERS}/{work_order_id}", user=user, **kw)

    def list_work_orders(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_ACCESSORY_WORK_ORDERS, user=user, params=params, **kw)

    def kit_work_order(self, work_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_ACCESSORY_WORK_ORDERS}/{work_order_id}/kit", user=user, payload={}, **kw)

    def install_work_order(self, work_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_ACCESSORY_WORK_ORDERS}/{work_order_id}/install", user=user, payload={}, **kw)

    def void_work_order(self, work_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_ACCESSORY_WORK_ORDERS}/{work_order_id}/void", user=user, payload={}, **kw)

    # ------------------------------------------------------------------
    # quality inspections
    # ------------------------------------------------------------------
    def open_inspection(self, vehicle_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/quality-inspections", user=user, payload={}, **kw)

    def get_inspection(self, inspection_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_QUALITY_INSPECTIONS}/{inspection_id}", user=user, **kw)

    def list_inspections(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_QUALITY_INSPECTIONS, user=user, params=params, **kw)

    def complete_inspection(self, inspection_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_QUALITY_INSPECTIONS}/{inspection_id}/complete", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # hold orders
    # ------------------------------------------------------------------
    def apply_hold(self, center_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_CENTERS}/{center_id}/hold-orders", user=user, payload=payload, **kw)

    def get_hold(self, hold_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_HOLD_ORDERS}/{hold_order_id}", user=user, **kw)

    def list_holds(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_HOLD_ORDERS, user=user, params=params, **kw)

    def lift_hold(self, hold_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_HOLD_ORDERS}/{hold_order_id}/lift", user=user, payload={}, **kw)

    # ------------------------------------------------------------------
    # dealers and carriers
    # ------------------------------------------------------------------
    def create_dealer(self, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_DEALERS, user=user, payload=payload, **kw)

    def get_dealer(self, dealer_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_DEALERS}/{dealer_id}", user=user, **kw)

    def list_dealers(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_DEALERS, user=user, params=params, **kw)

    def create_carrier(self, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", PATH_TRUCK_CARRIERS, user=user, payload=payload, **kw)

    def get_carrier(self, carrier_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_TRUCK_CARRIERS}/{carrier_id}", user=user, **kw)

    def list_carriers(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_TRUCK_CARRIERS, user=user, params=params, **kw)

    def patch_carrier(self, carrier_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("PATCH", f"{PATH_TRUCK_CARRIERS}/{carrier_id}", user=user, payload=payload, **kw)

    # ------------------------------------------------------------------
    # allocation and release
    # ------------------------------------------------------------------
    def allocate(self, vehicle_id: str, payload: Dict[str, Any], user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_VEHICLES}/{vehicle_id}/allocations", user=user, payload=payload, **kw)

    def get_release_order(self, release_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("GET", f"{PATH_RELEASE_ORDERS}/{release_order_id}", user=user, **kw)

    def list_release_orders(self, user: TestUser, params: Optional[Dict[str, Any]] = None, **kw) -> requests.Response:
        return self.call("GET", PATH_RELEASE_ORDERS, user=user, params=params, **kw)

    def dispatch(self, release_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_RELEASE_ORDERS}/{release_order_id}/dispatch", user=user, payload={}, **kw)

    def gate_out(self, release_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_RELEASE_ORDERS}/{release_order_id}/gate-out", user=user, payload={}, **kw)

    def cancel_release_order(self, release_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_RELEASE_ORDERS}/{release_order_id}/cancel", user=user, payload={}, **kw)

    def confirm_delivery(self, release_order_id: str, user: TestUser, **kw) -> requests.Response:
        return self.call("POST", f"{PATH_RELEASE_ORDERS}/{release_order_id}/delivery-confirmation", user=user, payload={}, **kw)
