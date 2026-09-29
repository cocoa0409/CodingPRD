"""A domain-shaped wrapper over the generic HTTP client.

Every collection is addressed from the flat ``/cpa`` root, so this client exposes
one named method per endpoint instead of letting tests assemble path strings.
Each method returns the raw response object; validation is the caller's job.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, JsonDict


class CpaApiClient:
    """Named access to the Regional CPA Settlement surface."""

    def __init__(self, client: Optional[GenericApiClient] = None) -> None:
        self.http = client or GenericApiClient()

    # -- raw escapes --------------------------------------------------------

    def get_raw(self, path: str, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(path, headers=headers, params=params)

    def post_raw(self, path: str, json: Optional[JsonDict] = None, headers: Optional[Headers] = None):
        return self.http.post(path, json=json, headers=headers)

    # -- logical clock ------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            json={"to_iso8601": to_iso8601},
            headers=headers,
        )

    # -- agreements ---------------------------------------------------------

    def create_agreement(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/agreements", json=payload, headers=headers)

    def list_agreements(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/agreements/{agreement_id}/activate", json={}, headers=headers
        )

    def terminate_agreement(
        self,
        agreement_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ):
        return self.http.post(
            f"{API_PREFIX}/agreements/{agreement_id}/terminate",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- extension negotiations --------------------------------------------

    def create_extension_negotiation(
        self, agreement_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.http.post(
            f"{API_PREFIX}/agreements/{agreement_id}/extension-negotiations",
            json=payload,
            headers=headers,
        )

    def list_extension_negotiations(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ):
        return self.http.get(
            f"{API_PREFIX}/extension-negotiations", headers=headers, params=params
        )

    def get_extension_negotiation(self, negotiation_id: str, headers: Optional[Headers] = None):
        return self.http.get(
            f"{API_PREFIX}/extension-negotiations/{negotiation_id}", headers=headers
        )

    def counter_negotiation(
        self, negotiation_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.http.post(
            f"{API_PREFIX}/extension-negotiations/{negotiation_id}/counter",
            json=payload,
            headers=headers,
        )

    def revise_offer(
        self, negotiation_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.http.post(
            f"{API_PREFIX}/extension-negotiations/{negotiation_id}/revise-offer",
            json=payload,
            headers=headers,
        )

    def accept_negotiation(self, negotiation_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/extension-negotiations/{negotiation_id}/accept",
            json={},
            headers=headers,
        )

    def withdraw_negotiation(self, negotiation_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/extension-negotiations/{negotiation_id}/withdraw",
            json={},
            headers=headers,
        )

    # -- crew bases ---------------------------------------------------------

    def create_crew_base(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/crew-bases", json=payload, headers=headers)

    def list_crew_bases(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/crew-bases", headers=headers, params=params)

    def get_crew_base(self, base_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/crew-bases/{base_id}", headers=headers)

    # -- aircraft -----------------------------------------------------------

    def create_aircraft(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/aircraft", json=payload, headers=headers)

    def list_aircraft(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/aircraft/{aircraft_id}", headers=headers)

    def induct_aircraft(self, aircraft_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/aircraft/{aircraft_id}/induct", json={}, headers=headers
        )

    def transition_aircraft(
        self, aircraft_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.http.post(
            f"{API_PREFIX}/aircraft/{aircraft_id}/transition", json=payload, headers=headers
        )

    def complete_transition(self, aircraft_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/aircraft/{aircraft_id}/complete-transition",
            json={},
            headers=headers,
        )

    # -- pilots -------------------------------------------------------------

    def create_pilot(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/pilots", json=payload, headers=headers)

    def list_pilots(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/pilots", headers=headers, params=params)

    def get_pilot(self, pilot_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/pilots/{pilot_id}", headers=headers)

    def advance_pilot(
        self,
        pilot_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ):
        return self.http.post(
            f"{API_PREFIX}/pilots/{pilot_id}/advance",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def attrite_pilot(self, pilot_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/pilots/{pilot_id}/attrite", json=payload, headers=headers
        )

    # -- schedule cycles ----------------------------------------------------

    def create_schedule_cycle(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/schedule-cycles", json=payload, headers=headers)

    def list_schedule_cycles(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ):
        return self.http.get(f"{API_PREFIX}/schedule-cycles", headers=headers, params=params)

    def get_schedule_cycle(self, cycle_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/schedule-cycles/{cycle_id}", headers=headers)

    def open_schedule_cycle(self, cycle_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/schedule-cycles/{cycle_id}/open", json={}, headers=headers
        )

    def close_schedule_cycle(self, cycle_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/schedule-cycles/{cycle_id}/close", json={}, headers=headers
        )

    def create_invoice(self, cycle_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/schedule-cycles/{cycle_id}/invoices", json=payload, headers=headers
        )

    # -- flight legs --------------------------------------------------------

    def create_flight_leg(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/flight-legs", json=payload, headers=headers)

    def list_flight_legs(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/flight-legs", headers=headers, params=params)

    def get_flight_leg(self, leg_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/flight-legs/{leg_id}", headers=headers)

    def complete_flight_leg(self, leg_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/flight-legs/{leg_id}/complete", json=payload, headers=headers
        )

    def cancel_flight_leg(self, leg_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/flight-legs/{leg_id}/cancel", json=payload, headers=headers
        )

    def reinstate_flight_leg(self, leg_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/flight-legs/{leg_id}/reinstate", json={}, headers=headers
        )

    # -- cancellation claims ------------------------------------------------

    def list_cancellation_claims(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ):
        return self.http.get(
            f"{API_PREFIX}/cancellation-claims", headers=headers, params=params
        )

    def get_cancellation_claim(self, claim_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/cancellation-claims/{claim_id}", headers=headers)

    def classify_claim(self, claim_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/cancellation-claims/{claim_id}/classify",
            json=payload,
            headers=headers,
        )

    def dispute_claim(self, claim_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/cancellation-claims/{claim_id}/dispute",
            json=payload,
            headers=headers,
        )

    def finalize_claim(
        self,
        claim_id: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ):
        return self.http.post(
            f"{API_PREFIX}/cancellation-claims/{claim_id}/finalize",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- pass-through claims ------------------------------------------------

    def create_pass_through_claim(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/pass-through-claims", json=payload, headers=headers
        )

    def list_pass_through_claims(
        self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None
    ):
        return self.http.get(
            f"{API_PREFIX}/pass-through-claims", headers=headers, params=params
        )

    def get_pass_through_claim(self, claim_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/pass-through-claims/{claim_id}", headers=headers)

    def submit_actual(self, claim_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/pass-through-claims/{claim_id}/submit-actual",
            json=payload,
            headers=headers,
        )

    def reconcile_pass_through(
        self, claim_id: str, payload: JsonDict, headers: Optional[Headers] = None
    ):
        return self.http.post(
            f"{API_PREFIX}/pass-through-claims/{claim_id}/reconcile",
            json=payload,
            headers=headers,
        )

    # -- scorecards ---------------------------------------------------------

    def list_scorecards(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/scorecards", headers=headers, params=params)

    def get_scorecard(self, scorecard_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/scorecards/{scorecard_id}", headers=headers)

    def recompute_scorecard(self, scorecard_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/scorecards/{scorecard_id}/recompute", json={}, headers=headers
        )

    # -- invoices -----------------------------------------------------------

    def list_invoices(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/invoices/{invoice_id}", headers=headers)

    def issue_final_invoice(self, invoice_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/invoices/{invoice_id}/issue-final", json={}, headers=headers
        )

    def void_invoice(self, invoice_id: str, payload: Optional[JsonDict] = None, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/invoices/{invoice_id}/void",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- brand audits -------------------------------------------------------

    def create_brand_audit(self, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(f"{API_PREFIX}/brand-audits", json=payload, headers=headers)

    def list_brand_audits(self, headers: Optional[Headers] = None, params: Optional[Dict[str, Any]] = None):
        return self.http.get(f"{API_PREFIX}/brand-audits", headers=headers, params=params)

    def get_brand_audit(self, audit_id: str, headers: Optional[Headers] = None):
        return self.http.get(f"{API_PREFIX}/brand-audits/{audit_id}", headers=headers)

    def acknowledge_brand_audit(self, audit_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/brand-audits/{audit_id}/acknowledge", json={}, headers=headers
        )

    def advance_remediation(self, audit_id: str, payload: JsonDict, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/brand-audits/{audit_id}/remediation", json=payload, headers=headers
        )

    def close_brand_audit(self, audit_id: str, headers: Optional[Headers] = None):
        return self.http.post(
            f"{API_PREFIX}/brand-audits/{audit_id}/close", json={}, headers=headers
        )


__all__ = ["CpaApiClient"]
