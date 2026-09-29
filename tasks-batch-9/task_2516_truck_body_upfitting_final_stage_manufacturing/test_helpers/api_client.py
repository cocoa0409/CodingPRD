"""One method per endpoint of PRD §4.

Every method returns the raw ``requests.Response`` so that tests can assert on
HTTP status codes as well as on the response envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class UpfitApiClient(GenericApiClient):
    """Typed surface for the Truck Body Upfitting API."""

    # ------------------------------------------------------------------
    # Logical clock (§2.4) — the one path outside the /upfit prefix.
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ------------------------------------------------------------------
    # Chassis models
    # ------------------------------------------------------------------
    def create_chassis_model(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/chassis-models", payload, headers)

    def get_chassis_model(self, chassis_model_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/chassis-models/{chassis_model_id}", None, headers
        )

    def list_chassis_models(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/chassis-models", None, headers, params)

    # ------------------------------------------------------------------
    # Body specs
    # ------------------------------------------------------------------
    def create_body_spec(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/body-specs", payload, headers)

    def get_body_spec(self, body_spec_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/body-specs/{body_spec_id}", None, headers)

    def list_body_specs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/body-specs", None, headers, params)

    # ------------------------------------------------------------------
    # Equipment specs
    # ------------------------------------------------------------------
    def create_equipment_spec(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/equipment-specs", payload, headers)

    def get_equipment_spec(self, equipment_spec_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/equipment-specs/{equipment_spec_id}", None, headers
        )

    def list_equipment_specs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/equipment-specs", None, headers, params)

    # ------------------------------------------------------------------
    # Work bays
    # ------------------------------------------------------------------
    def create_work_bay(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/work-bays", payload, headers)

    def set_work_bay_status(self, work_bay_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/work-bays/{work_bay_id}/set-status", payload, headers
        )

    def get_work_bay(self, work_bay_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/work-bays/{work_bay_id}", None, headers)

    def list_work_bays(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/work-bays", None, headers, params)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/customers/{customer_id}", None, headers)

    def list_customers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/customers", None, headers, params)

    # ------------------------------------------------------------------
    # Build configurations
    # ------------------------------------------------------------------
    def create_build_configuration(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/build-configurations", payload, headers)

    def publish_build_configuration(self, build_configuration_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/build-configurations/{build_configuration_id}/publish",
            payload or {},
            headers,
        )

    def deprecate_build_configuration(self, build_configuration_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/build-configurations/{build_configuration_id}/deprecate",
            payload or {},
            headers,
        )

    def get_build_configuration(self, build_configuration_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/build-configurations/{build_configuration_id}",
            None,
            headers,
        )

    def list_build_configurations(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/build-configurations", None, headers, params)

    # ------------------------------------------------------------------
    # Chassis custody
    # ------------------------------------------------------------------
    def receive_chassis(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/chassis", payload, headers)

    def inspect_chassis(self, chassis_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/chassis/{chassis_id}/inspect", payload, headers
        )

    def quarantine_chassis(self, chassis_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/chassis/{chassis_id}/quarantine", payload, headers
        )

    def return_chassis(self, chassis_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/chassis/{chassis_id}/return", payload, headers
        )

    def get_chassis(self, chassis_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/chassis/{chassis_id}", None, headers)

    def list_chassis(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/chassis", None, headers, params)

    # ------------------------------------------------------------------
    # Upfit orders
    # ------------------------------------------------------------------
    def create_upfit_order(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/upfit-orders", payload, headers)

    def submit_engineering(self, upfit_order_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/submit-engineering",
            payload or {},
            headers,
        )

    def request_rework(self, upfit_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/request-rework",
            payload,
            headers,
        )

    def allocate_chassis(self, upfit_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/allocate-chassis",
            payload,
            headers,
        )

    def patch_body_mount(self, upfit_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/body-mount",
            payload,
            headers,
        )

    def release_order(self, upfit_order_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/release",
            payload or {},
            headers,
        )

    def body_install(self, upfit_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/body-install",
            payload,
            headers,
        )

    def deliver_order(self, upfit_order_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/deliver",
            payload or {},
            headers,
        )

    def cancel_order(self, upfit_order_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/cancel",
            payload,
            headers,
        )

    def get_upfit_order(self, upfit_order_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/upfit-orders/{upfit_order_id}", None, headers
        )

    def list_upfit_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/upfit-orders", None, headers, params)

    def weight_projection(self, upfit_order_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"{API_PREFIX}/upfit-orders/{upfit_order_id}/weight-projection",
            None,
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # Equipment installations
    # ------------------------------------------------------------------
    def create_equipment_installation(self, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/equipment-installations", payload, headers
        )

    def install_equipment(self, equipment_installation_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-installations/{equipment_installation_id}/install",
            payload,
            headers,
        )

    def commission_equipment(self, equipment_installation_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-installations/{equipment_installation_id}/commission",
            payload or {},
            headers,
        )

    def decommission_equipment(
        self, equipment_installation_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-installations/{equipment_installation_id}/decommission",
            payload,
            headers,
        )

    def remove_equipment(self, equipment_installation_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-installations/{equipment_installation_id}/remove",
            payload,
            headers,
        )

    def get_equipment_installation(self, equipment_installation_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/equipment-installations/{equipment_installation_id}",
            None,
            headers,
        )

    def list_equipment_installations(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/equipment-installations", None, headers, params
        )

    # ------------------------------------------------------------------
    # Electrical interfaces
    # ------------------------------------------------------------------
    def create_electrical_interface(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/electrical-interfaces", payload, headers)

    def approve_interface(self, electrical_interface_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/electrical-interfaces/{electrical_interface_id}/approve",
            payload or {},
            headers,
        )

    def reject_interface(self, electrical_interface_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/electrical-interfaces/{electrical_interface_id}/reject",
            payload,
            headers,
        )

    def get_electrical_interface(self, electrical_interface_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/electrical-interfaces/{electrical_interface_id}",
            None,
            headers,
        )

    def list_electrical_interfaces(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/electrical-interfaces", None, headers, params
        )

    # ------------------------------------------------------------------
    # Build slots
    # ------------------------------------------------------------------
    def create_build_slot(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/build-slots", payload, headers)

    def start_build_slot(self, build_slot_id: str, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/build-slots/{build_slot_id}/start", payload or {}, headers
        )

    def close_build_slot(self, build_slot_id: str, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/build-slots/{build_slot_id}/close", payload or {}, headers
        )

    def cancel_build_slot(self, build_slot_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/build-slots/{build_slot_id}/cancel", payload, headers
        )

    def get_build_slot(self, build_slot_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/build-slots/{build_slot_id}", None, headers)

    def list_build_slots(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/build-slots", None, headers, params)

    # ------------------------------------------------------------------
    # Weight certifications
    # ------------------------------------------------------------------
    def create_weight_certification(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/weight-certifications", payload, headers)

    def approve_weight_certification(self, weight_certification_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/weight-certifications/{weight_certification_id}/approve",
            payload or {},
            headers,
        )

    def get_weight_certification(self, weight_certification_id: str, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/weight-certifications/{weight_certification_id}",
            None,
            headers,
        )

    def list_weight_certifications(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/weight-certifications", None, headers, params
        )

    # ------------------------------------------------------------------
    # Compliance labels
    # ------------------------------------------------------------------
    def create_compliance_label(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/compliance-labels", payload, headers)

    def get_compliance_label(self, compliance_label_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/compliance-labels/{compliance_label_id}", None, headers
        )

    def list_compliance_labels(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/compliance-labels", None, headers, params)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/warranty-claims", payload, headers)

    def inspect_warranty_claim(self, warranty_claim_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{warranty_claim_id}/inspect",
            payload,
            headers,
        )

    def adjudicate_warranty_claim(self, warranty_claim_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{warranty_claim_id}/adjudicate",
            payload or {},
            headers,
        )

    def dispute_warranty_claim(self, warranty_claim_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{warranty_claim_id}/dispute",
            payload,
            headers,
        )

    def pay_warranty_claim(self, warranty_claim_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{warranty_claim_id}/pay",
            payload or {},
            headers,
        )

    def get_warranty_claim(self, warranty_claim_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/warranty-claims/{warranty_claim_id}", None, headers
        )

    def list_warranty_claims(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/warranty-claims", None, headers, params)
