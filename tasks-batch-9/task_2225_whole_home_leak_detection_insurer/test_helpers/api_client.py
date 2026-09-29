"""API client: one method per endpoint listed in the PRD (§4).

Every route is mounted at the root, so the paths below are the paths the PRD
prints.  The logical-clock capability is a route like any other.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Homeowner accounts
    # ------------------------------------------------------------------
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    def deactivate_homeowner(self, homeowner_id, payload, headers):
        return self._request(
            "POST", f"/homeowners/{homeowner_id}/deactivate", payload, headers
        )

    def create_emergency_contact(self, homeowner_id, payload, headers):
        return self._request(
            "POST", f"/homeowners/{homeowner_id}/emergency-contacts", payload, headers
        )

    def list_emergency_contacts(self, homeowner_id, headers, params=None):
        return self._request(
            "GET",
            f"/homeowners/{homeowner_id}/emergency-contacts",
            headers=headers,
            params=params,
        )

    def list_homeowner_properties(self, homeowner_id, headers, params=None):
        return self._request(
            "GET",
            f"/homeowners/{homeowner_id}/properties",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Properties and irrigation windows
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_property_devices(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/devices", headers=headers, params=params
        )

    def create_irrigation_window(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/irrigation-windows", payload, headers
        )

    def list_irrigation_windows(self, property_id, headers, params=None):
        return self._request(
            "GET",
            f"/properties/{property_id}/irrigation-windows",
            headers=headers,
            params=params,
        )

    def list_property_policies(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/policies", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def verify_install(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/verify-install", payload, headers
        )

    def create_telemetry_reading(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/telemetry", payload, headers
        )

    def list_telemetry_readings(self, device_id, headers, params=None):
        return self._request(
            "GET", f"/devices/{device_id}/telemetry", headers=headers, params=params
        )

    def list_baseline_profiles(self, device_id, headers, params=None):
        return self._request(
            "GET",
            f"/devices/{device_id}/baseline-profiles",
            headers=headers,
            params=params,
        )

    def get_health_summary(self, device_id, headers, params=None):
        return self._request(
            "GET", f"/devices/{device_id}/health-summary", headers=headers, params=params
        )

    def send_valve_command(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/valve-commands", payload, headers
        )

    def set_monitor_mode(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/monitor-mode", payload, headers
        )

    def push_firmware_update(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/firmware-updates", payload, headers
        )

    # ------------------------------------------------------------------
    # Anomaly events and escalation tickets
    # ------------------------------------------------------------------
    def get_anomaly_event(self, event_id, headers):
        return self._request("GET", f"/anomaly-events/{event_id}", headers=headers)

    def list_anomaly_events(self, headers, params=None):
        return self._request("GET", "/anomaly-events", headers=headers, params=params)

    def submit_event_feedback(self, event_id, payload, headers):
        return self._request(
            "POST", f"/anomaly-events/{event_id}/feedback", payload, headers
        )

    def resolve_anomaly_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/anomaly-events/{event_id}/resolve", payload, headers
        )

    def get_escalation_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/escalation-tickets/{ticket_id}", headers=headers
        )

    def list_escalation_tickets(self, headers, params=None):
        return self._request(
            "GET", "/escalation-tickets", headers=headers, params=params
        )

    def acknowledge_escalation_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/escalation-tickets/{ticket_id}/acknowledge", payload, headers
        )

    # ------------------------------------------------------------------
    # Insurer credit program
    # ------------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def create_credit_attestation(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/credit-attestations", payload, headers
        )

    def list_credit_attestations(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/policies/{policy_id}/credit-attestations",
            headers=headers,
            params=params,
        )

    def finalize_credit_attestation(self, attestation_id, payload, headers):
        return self._request(
            "POST", f"/credit-attestations/{attestation_id}/finalize", payload, headers
        )

    # ------------------------------------------------------------------
    # Reimbursement claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/decision", payload, headers)

    # ------------------------------------------------------------------
    # Device transfers
    # ------------------------------------------------------------------
    def create_device_transfer(self, payload, headers):
        return self._request("POST", "/device-transfers", payload, headers)

    def get_device_transfer(self, transfer_id, headers):
        return self._request("GET", f"/device-transfers/{transfer_id}", headers=headers)

    def list_device_transfers(self, headers, params=None):
        return self._request("GET", "/device-transfers", headers=headers, params=params)

    def accept_device_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/device-transfers/{transfer_id}/accept", payload, headers
        )

    # ------------------------------------------------------------------
    # Operator sweep and the logical clock
    # ------------------------------------------------------------------
    def run_ops_sweep(self, payload, headers):
        return self._request("POST", "/ops-sweeps", payload, headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
