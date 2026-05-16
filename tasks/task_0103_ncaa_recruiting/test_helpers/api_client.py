"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request (except GET /_clock).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Program — PRD §3.1
    # =======================================================================
    def create_program(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/programs/{program_id}", headers=headers,
        )

    def list_programs(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/programs", headers=headers, params=params,
        )

    # =======================================================================
    # RecruitingCalendar — PRD §3.1
    # =======================================================================
    def create_recruiting_calendar(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/recruiting-calendars", payload, headers,
        )

    def get_recruiting_calendar(self, calendar_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"/recruiting-calendars/{calendar_id}", headers=headers,
        )

    def list_recruiting_calendars(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/recruiting-calendars",
            headers=headers, params=params,
        )

    # =======================================================================
    # Athlete — PRD §3.2
    # =======================================================================
    def create_athlete(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/athletes", payload, headers)

    def get_athlete(self, athlete_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/athletes/{athlete_id}", headers=headers,
        )

    def list_athletes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/athletes", headers=headers, params=params,
        )

    def transition_athlete(self, athlete_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/athletes/{athlete_id}/state", payload, headers,
        )

    # =======================================================================
    # EligibilityRecord — PRD §3.2
    # =======================================================================
    def create_eligibility_record(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/eligibility-records", payload, headers,
        )

    def get_eligibility_record(self, record_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/eligibility-records/{record_id}", headers=headers,
        )

    # =======================================================================
    # ScholarshipSlot — PRD §3.3
    # =======================================================================
    def create_scholarship_slot(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/scholarship-slots", payload, headers,
        )

    def get_scholarship_slot(self, slot_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/scholarship-slots/{slot_id}", headers=headers,
        )

    def list_scholarship_slots(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/scholarship-slots", headers=headers, params=params,
        )

    def transition_scholarship_slot(self, slot_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/scholarship-slots/{slot_id}/state",
            payload, headers,
        )

    # =======================================================================
    # RecruitingContact — PRD §3.8
    # =======================================================================
    def create_recruiting_contact(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/recruiting-contacts", payload, headers,
        )

    def get_recruiting_contact(self, contact_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/recruiting-contacts/{contact_id}", headers=headers,
        )

    def list_recruiting_contacts(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/recruiting-contacts",
            headers=headers, params=params,
        )

    # =======================================================================
    # NILDeal — PRD §3.5, §3.6
    # =======================================================================
    def create_nil_deal(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/nil-deals", payload, headers)

    def get_nil_deal(self, deal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/nil-deals/{deal_id}", headers=headers,
        )

    def list_nil_deals(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/nil-deals", headers=headers, params=params,
        )

    def patch_nil_deal(self, deal_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/nil-deals/{deal_id}", payload, headers,
        )

    def transition_nil_deal(self, deal_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/nil-deals/{deal_id}/state", payload, headers,
        )

    # =======================================================================
    # TransferPortalEntry — PRD §3.4
    # =======================================================================
    def create_transfer_portal_entry(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/transfer-portal-entries", payload, headers,
        )

    def get_transfer_portal_entry(self, entry_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/transfer-portal-entries/{entry_id}", headers=headers,
        )

    def list_transfer_portal_entries(self, headers: Dict[str, str],
                                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transfer-portal-entries",
            headers=headers, params=params,
        )

    def transition_transfer_portal_entry(self, entry_id: str,
                                         payload: Dict[str, Any],
                                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-portal-entries/{entry_id}/state",
            payload, headers,
        )

    # =======================================================================
    # ComplianceViolation — PRD §3.7
    # =======================================================================
    def create_violation(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/violations/{violation_id}", headers=headers,
        )

    def list_violations(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/violations", headers=headers, params=params,
        )

    def transition_violation(self, violation_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/violations/{violation_id}/state", payload, headers,
        )

    # =======================================================================
    # Clock — PRD §2.10
    # =======================================================================
    def get_clock(self, headers: Optional[Dict[str, str]] = None):
        # PRD §2.1: "The sole exception is the read-side clock endpoint,
        # which is open". Headers are optional.
        return self._request(
            "GET", "/_clock", headers=(headers or {}),
        )

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
