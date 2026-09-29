"""API client: one method per endpoint defined in the PRD.

Every resource lives under the ``/casting`` prefix, with the sole exception of
the administrative logical-clock control at ``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/casting"


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods for the casting API."""

    # ------------------------------------------------------------ Production

    def create_production(self, payload, headers):
        return self._request("POST", f"{PREFIX}/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request(
            "GET", f"{PREFIX}/productions/{production_id}", headers=headers
        )

    def run_welfare_epoch(self, production_id, headers):
        return self._request(
            "POST", f"{PREFIX}/productions/{production_id}/welfare-run", {}, headers
        )

    # ------------------------------------------------------- WelfareProtocol

    def plan_welfare_protocol(self, production_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/productions/{production_id}/welfare-protocols",
            payload,
            headers,
        )

    def list_welfare_protocols(self, production_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/productions/{production_id}/welfare-protocols",
            headers=headers,
            params=params,
        )

    def activate_welfare_protocol(self, protocol_id, headers):
        return self._request(
            "POST", f"{PREFIX}/welfare-protocols/{protocol_id}/activate", {}, headers
        )

    def cancel_welfare_protocol(self, protocol_id, headers):
        return self._request(
            "POST", f"{PREFIX}/welfare-protocols/{protocol_id}/cancel", {}, headers
        )

    # -------------------------------------------------------------- Location

    def create_location(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locations", payload, headers)

    # ----------------------------------------------------------- CastingCall

    def create_casting_call(self, payload, headers):
        return self._request("POST", f"{PREFIX}/casting-calls", payload, headers)

    def list_casting_calls(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/casting-calls", headers=headers, params=params
        )

    def get_casting_call(self, call_id, headers):
        return self._request("GET", f"{PREFIX}/casting-calls/{call_id}", headers=headers)

    def publish_casting_call(self, call_id, headers):
        return self._request(
            "POST", f"{PREFIX}/casting-calls/{call_id}/publish", {}, headers
        )

    def close_casting_call(self, call_id, headers):
        return self._request(
            "POST", f"{PREFIX}/casting-calls/{call_id}/close", {}, headers
        )

    def list_casting_call_applicants(self, call_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/casting-calls/{call_id}/applicants",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------- Applicant

    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def withdraw_applicant(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applicants/{applicant_id}/withdraw", payload, headers
        )

    # ---------------------------------------------------------- ScreeningItem

    def create_screening_item(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applicants/{applicant_id}/screening-items", payload, headers
        )

    def list_screening_items(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/applicants/{applicant_id}/screening-items",
            headers=headers,
            params=params,
        )

    def record_screening_outcome(self, screening_item_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/screening-items/{screening_item_id}/record-outcome",
            payload,
            headers,
        )

    # -------------------------------------------------------- MinorProtection

    def create_minor_protection(self, applicant_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applicants/{applicant_id}/minor-protections",
            payload,
            headers,
        )

    def list_minor_protections(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/applicants/{applicant_id}/minor-protections",
            headers=headers,
            params=params,
        )

    def patch_minor_protection(self, packet_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/minor-protections/{packet_id}", payload, headers
        )

    def create_trust_deposit(self, packet_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/minor-protections/{packet_id}/trust-deposits",
            payload,
            headers,
        )

    # --------------------------------------------------- ParticipantAgreement

    def create_agreement(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-agreements", payload, headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/participant-agreements", headers=headers, params=params
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/participant-agreements/{agreement_id}", headers=headers
        )

    def send_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-agreements/{agreement_id}/send", {}, headers
        )

    def counter_offer_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/participant-agreements/{agreement_id}/counter-offer",
            payload,
            headers,
        )

    def revise_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/participant-agreements/{agreement_id}/revise",
            payload,
            headers,
        )

    def execute_agreement(self, agreement_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/participant-agreements/{agreement_id}/execute",
            {},
            headers,
        )

    def void_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-agreements/{agreement_id}/void", payload, headers
        )

    def list_negotiation_rounds(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/participant-agreements/{agreement_id}/negotiation-rounds",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------- PostObligation

    def list_post_obligations(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/participant-agreements/{agreement_id}/post-obligations",
            headers=headers,
            params=params,
        )

    def fulfill_post_obligation(self, obligation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/post-obligations/{obligation_id}/fulfill", {}, headers
        )

    # ------------------------------------------------------------- Complaint

    def file_complaint(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/participant-agreements/{agreement_id}/complaints",
            payload,
            headers,
        )

    def list_complaints(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/participant-agreements/{agreement_id}/complaints",
            headers=headers,
            params=params,
        )

    def triage_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/triage", {}, headers
        )

    def route_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/route", payload, headers
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------ ShootBlock

    def create_shoot_block(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shoot-blocks", payload, headers)

    def list_shoot_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shoot-blocks", headers=headers, params=params
        )

    def get_shoot_block(self, block_id, headers):
        return self._request("GET", f"{PREFIX}/shoot-blocks/{block_id}", headers=headers)

    def roll_shoot_block(self, block_id, headers):
        return self._request(
            "POST", f"{PREFIX}/shoot-blocks/{block_id}/roll", {}, headers
        )

    def wrap_shoot_block(self, block_id, headers):
        return self._request(
            "POST", f"{PREFIX}/shoot-blocks/{block_id}/wrap", {}, headers
        )

    def collect_release(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shoot-blocks/{block_id}/releases", payload, headers
        )

    def list_releases(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/shoot-blocks/{block_id}/releases",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------- logical clock

    def set_logical_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------- raw path escapes
    # Used only where a test must address a deliberately malformed or unknown
    # path that the typed helpers above would not construct.

    def get_path(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def post_path(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
