"""API client: one method per endpoint defined in the PRD.

The whole API is mounted under the /recycling prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/recycling"


class ApiClient(GenericApiClient):
    """One method per row of the PRD endpoint table."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------- facilities
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def get_capacity_projection(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/facilities/{facility_id}/capacity-projection",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ suppliers
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{PREFIX}/suppliers/{supplier_id}", headers=headers)

    def create_quality_strike(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/suppliers/{supplier_id}/quality-strikes", payload, headers
        )

    # --------------------------------------------------- metal index prices
    def create_metal_index_price(self, payload, headers):
        return self._request("POST", f"{PREFIX}/metal-index-prices", payload, headers)

    def list_metal_index_prices(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/metal-index-prices", headers=headers, params=params
        )

    # ----------------------------------------------------- permit allotments
    def create_permit_allotment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permit-allotments", payload, headers)

    def list_permit_allotments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permit-allotments", headers=headers, params=params
        )

    def get_permit_allotment(self, allotment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/permit-allotments/{allotment_id}", headers=headers
        )

    def suspend_permit_allotment(self, allotment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-allotments/{allotment_id}/suspend", payload, headers
        )

    # ----------------------------------------------------- processing lines
    def create_processing_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/processing-lines", payload, headers)

    def list_processing_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/processing-lines", headers=headers, params=params
        )

    def get_processing_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/processing-lines/{line_id}", headers=headers)

    def replumb_processing_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/processing-lines/{line_id}/replumb", payload, headers
        )

    # -------------------------------------------------------------- intakes
    def create_intake(self, payload, headers):
        return self._request("POST", f"{PREFIX}/intakes", payload, headers)

    def list_intakes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/intakes", headers=headers, params=params)

    def get_intake(self, intake_id, headers):
        return self._request("GET", f"{PREFIX}/intakes/{intake_id}", headers=headers)

    def identify_chemistry(self, intake_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intakes/{intake_id}/identify-chemistry", payload, headers
        )

    def discharge_intake(self, intake_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intakes/{intake_id}/discharge", payload, headers
        )

    def package_intake(self, intake_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intakes/{intake_id}/package", payload, headers
        )

    def submit_manifest(self, intake_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intakes/{intake_id}/manifests", payload, headers
        )

    def list_manifests(self, intake_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/intakes/{intake_id}/manifests", headers=headers, params=params
        )

    def close_manifest(self, intake_id, manifest_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/intakes/{intake_id}/manifests/{manifest_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def reject_manifest(self, intake_id, manifest_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/intakes/{intake_id}/manifests/{manifest_id}/reject",
            payload,
            headers,
        )

    def release_intake(self, intake_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/intakes/{intake_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def create_module(self, intake_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intakes/{intake_id}/modules", payload, headers
        )

    # -------------------------------------------------------------- modules
    def list_modules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/modules", headers=headers, params=params)

    def get_module(self, module_id, headers):
        return self._request("GET", f"{PREFIX}/modules/{module_id}", headers=headers)

    def create_triage_decision(self, module_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/modules/{module_id}/triage-decisions", payload, headers
        )

    def list_triage_decisions(self, module_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/modules/{module_id}/triage-decisions",
            headers=headers,
            params=params,
        )

    def ship_module(self, module_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/modules/{module_id}/ship", payload, headers
        )

    # ------------------------------------------------------------ campaigns
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}", headers=headers)

    def start_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/campaigns/{campaign_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def cancel_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/cancel", payload, headers
        )

    def create_lot(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/lots", payload, headers
        )

    # ----------------------------------------------------------------- lots
    def list_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}", headers=headers)

    def charge_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/charge", payload, headers)

    def create_recovery_output(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/recovery-outputs", payload, headers
        )

    def list_recovery_outputs(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lots/{lot_id}/recovery-outputs", headers=headers, params=params
        )

    def finalize_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/finalize", payload, headers)

    def void_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/void", payload, headers)

    def create_discharge_event(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/discharge-events", payload, headers
        )

    # ----------------------------------------------------- discharge events
    def list_discharge_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/discharge-events", headers=headers, params=params
        )

    def get_discharge_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/discharge-events/{event_id}", headers=headers
        )

    def void_discharge_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/discharge-events/{event_id}/void", payload, headers
        )

    # ------------------------------------------------------------ passports
    def issue_passport(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/passports", payload, headers)

    def list_passports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/passports", headers=headers, params=params)

    def get_passport(self, passport_id, headers):
        return self._request("GET", f"{PREFIX}/passports/{passport_id}", headers=headers)

    def revoke_passport(self, passport_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/passports/{passport_id}/revoke", payload, headers
        )

    # ---------------------------------------------------------- settlements
    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers
        )

    def post_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/settlements/{settlement_id}/post",
            payload if payload is not None else {},
            headers,
        )

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/dispute", payload, headers
        )

    def record_umpire_assay(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/umpire-assay", payload, headers
        )

    def apply_umpire(self, settlement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/settlements/{settlement_id}/apply-umpire",
            payload if payload is not None else {},
            headers,
        )

    def settle_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/settle", payload, headers
        )

    def void_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/void", payload, headers
        )


api_client = ApiClient()
