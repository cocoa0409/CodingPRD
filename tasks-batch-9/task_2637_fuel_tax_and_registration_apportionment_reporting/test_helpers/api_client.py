"""Typed client for the Fuel Tax and Registration Apportionment API.

One method per documented operation. Every method returns the raw
``requests.Response`` so that callers can assert on both success and error
envelopes. Optional body fields are omitted entirely when not supplied, which
matters because unknown fields are rejected and an explicit null is not the
same as an absent field for the fields that are only sometimes required.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` (Ellipsis)."""
    return {k: v for k, v in payload.items() if v is not ...}


class ApportionmentClient(GenericApiClient):
    """All 50 operations of the apportionment surface."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------

    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/jurisdictions", payload, headers=headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/jurisdictions", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Weight group fees
    # ------------------------------------------------------------------

    def create_weight_group_fee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/weight-group-fees", payload, headers=headers)

    def get_weight_group_fee(self, fee_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/weight-group-fees/{fee_id}", headers=headers)

    def list_weight_group_fees(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/weight-group-fees", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------

    def create_carrier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/carriers", payload, headers=headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/carriers/{carrier_id}", headers=headers)

    def list_carriers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/carriers", headers=headers, params=params)

    def list_carrier_drivers(
        self,
        carrier_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            f"{API_PREFIX}/carriers/{carrier_id}/drivers", headers=headers, params=params
        )

    def list_carrier_audit_selections(
        self,
        carrier_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            f"{API_PREFIX}/carriers/{carrier_id}/audit-selections",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------

    def create_driver(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/drivers", payload, headers=headers)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------

    def create_vehicle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/vehicles", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Trip records
    # ------------------------------------------------------------------

    def create_trip_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/trip-records", payload, headers=headers)

    def get_trip_record(self, trip_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/trip-records/{trip_id}", headers=headers)

    def list_trip_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/trip-records", headers=headers, params=params)

    def list_trip_mileage_legs(
        self,
        trip_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            f"{API_PREFIX}/trip-records/{trip_id}/mileage-legs",
            headers=headers,
            params=params,
        )

    def reconstruct_trip_record(
        self,
        trip_id: str,
        headers: Dict[str, str],
        reconstructed_legs: Any = ...,
        supporting_document_reference: Any = ...,
        **extra: Any,
    ):
        payload = _compact(
            {
                "reconstructed_legs": reconstructed_legs,
                "supporting_document_reference": supporting_document_reference,
            }
        )
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/trip-records/{trip_id}/reconstruct", payload, headers=headers
        )

    def review_trip_record(
        self,
        trip_id: str,
        headers: Dict[str, str],
        decision: Any = ...,
        review_note: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"decision": decision, "review_note": review_note})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/trip-records/{trip_id}/review", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Fuel purchases
    # ------------------------------------------------------------------

    def create_fuel_purchase(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/fuel-purchases", payload, headers=headers)

    def get_fuel_purchase(self, purchase_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/fuel-purchases/{purchase_id}", headers=headers)

    def list_fuel_purchases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/fuel-purchases", headers=headers, params=params)

    def disallow_fuel_purchase(
        self,
        purchase_id: str,
        headers: Dict[str, str],
        disallow_reason_code: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"disallow_reason_code": disallow_reason_code})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/fuel-purchases/{purchase_id}/disallow",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Quarterly fuel tax returns
    # ------------------------------------------------------------------

    def create_fuel_tax_return(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/fuel-tax-returns", payload, headers=headers)

    def get_fuel_tax_return(self, return_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/fuel-tax-returns/{return_id}", headers=headers)

    def list_fuel_tax_returns(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/fuel-tax-returns", headers=headers, params=params)

    def list_return_jurisdiction_lines(
        self,
        return_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            f"{API_PREFIX}/fuel-tax-returns/{return_id}/jurisdiction-lines",
            headers=headers,
            params=params,
        )

    def prepare_fuel_tax_return(
        self,
        return_id: str,
        headers: Dict[str, str],
        expected_carrier_version: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"expected_carrier_version": expected_carrier_version})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/fuel-tax-returns/{return_id}/prepare", payload, headers=headers
        )

    def review_fuel_tax_return(
        self,
        return_id: str,
        headers: Dict[str, str],
        decision: Any = ...,
        review_note: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"decision": decision, "review_note": review_note})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/fuel-tax-returns/{return_id}/review", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Registration applications
    # ------------------------------------------------------------------

    def create_registration_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/registration-applications", payload, headers=headers
        )

    def get_registration_application(
        self, application_id: str, headers: Dict[str, str]
    ):
        return self.get(
            f"{API_PREFIX}/registration-applications/{application_id}", headers=headers
        )

    def list_registration_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/registration-applications", headers=headers, params=params
        )

    def add_distance_schedule_line(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/registration-applications/{application_id}/distance-schedule",
            payload,
            headers=headers,
        )

    def list_distance_schedule_lines(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self.get(
            f"{API_PREFIX}/registration-applications/{application_id}/distance-schedule",
            headers=headers,
            params=params,
        )

    def submit_registration_application(
        self, application_id: str, headers: Dict[str, str], **extra: Any
    ):
        return self.post(
            f"{API_PREFIX}/registration-applications/{application_id}/submit",
            dict(extra),
            headers=headers,
        )

    def review_registration_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        decision: Any = ...,
        review_note: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"decision": decision, "review_note": review_note})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/registration-applications/{application_id}/review",
            payload,
            headers=headers,
        )

    def issue_credentials(
        self,
        application_id: str,
        headers: Dict[str, str],
        valid_from_date: Any = ...,
        valid_to_date: Any = ...,
        **extra: Any,
    ):
        payload = _compact(
            {"valid_from_date": valid_from_date, "valid_to_date": valid_to_date}
        )
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/registration-applications/{application_id}/issue-credentials",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Fleet change requests
    # ------------------------------------------------------------------

    def create_fleet_change_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(f"{API_PREFIX}/fleet-change-requests", payload, headers=headers)

    def get_fleet_change_request(self, change_id: str, headers: Dict[str, str]):
        return self.get(
            f"{API_PREFIX}/fleet-change-requests/{change_id}", headers=headers
        )

    def list_fleet_change_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/fleet-change-requests", headers=headers, params=params
        )

    def decide_fleet_change_request(
        self,
        change_id: str,
        headers: Dict[str, str],
        decision: Any = ...,
        decision_note: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"decision": decision, "decision_note": decision_note})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/fleet-change-requests/{change_id}/decide",
            payload,
            headers=headers,
        )

    def reverse_fleet_change_request(
        self,
        change_id: str,
        headers: Dict[str, str],
        reversal_reason_code: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"reversal_reason_code": reversal_reason_code})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/fleet-change-requests/{change_id}/reverse",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def get_credential(self, credential_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/credentials/{credential_id}", headers=headers)

    def list_credentials(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/credentials", headers=headers, params=params)

    def distribute_credential(
        self,
        credential_id: str,
        headers: Dict[str, str],
        distributed_to_driver_id: Any = ...,
        **extra: Any,
    ):
        payload = _compact({"distributed_to_driver_id": distributed_to_driver_id})
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/credentials/{credential_id}/distribute",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Audit selections
    # ------------------------------------------------------------------

    def create_audit_selection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/audit-selections", payload, headers=headers)

    def retention_review_audit_selection(
        self,
        selection_id: str,
        headers: Dict[str, str],
        expected_records_count: Any = ...,
        records_missing_count: Any = ...,
        **extra: Any,
    ):
        payload = _compact(
            {
                "expected_records_count": expected_records_count,
                "records_missing_count": records_missing_count,
            }
        )
        payload.update(extra)
        return self.post(
            f"{API_PREFIX}/audit-selections/{selection_id}/retention-review",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for shape-violation tests
    # ------------------------------------------------------------------

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("POST", path, payload=payload, headers=headers)


ALL_LIST_PATHS: List[str] = [
    f"{API_PREFIX}/jurisdictions",
    f"{API_PREFIX}/weight-group-fees",
    f"{API_PREFIX}/carriers",
    f"{API_PREFIX}/vehicles",
    f"{API_PREFIX}/trip-records",
    f"{API_PREFIX}/fuel-purchases",
    f"{API_PREFIX}/fuel-tax-returns",
    f"{API_PREFIX}/registration-applications",
    f"{API_PREFIX}/fleet-change-requests",
    f"{API_PREFIX}/credentials",
]
