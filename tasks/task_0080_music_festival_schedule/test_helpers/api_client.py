"""HTTP client for the Festival Program Schedule API.

Subclasses the framework's `GenericApiClient`, which provides the base
`_request()` method that handles the response-envelope unwrapping per the
PRD §2.2 contract.  Each method below is a thin wrapper around `_request`
that names the HTTP verb and the URL path; the body and headers pass
through unchanged.

Methods are grouped by the entity they operate on, matching the §4 endpoint
table of the PRD.  Each path string in this file is the verbatim path
template the PRD §4 table prescribes.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import os

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete API client.  One method per HTTP endpoint in the PRD §4 table.

    The base-class `_request(method, path, payload=None, headers=None,
    params=None)` returns the raw `requests.Response` object that the
    framework's validators consume.
    """

    # ------------------------------------------------------------------
    # Festivals
    # ------------------------------------------------------------------
    def create_festival(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/festivals", payload=payload, headers=headers)

    def list_festivals(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/festivals", headers=headers, params=params)

    def get_festival(self, festival_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}", headers=headers)

    def open_scheduling(self, festival_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/open-scheduling",
                             payload=payload or {}, headers=headers)

    def cancel_festival(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/cancel",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Exposure catalog
    # ------------------------------------------------------------------
    def seed_exposure_catalog(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/exposure-catalog",
                             payload=payload, headers=headers)

    def get_exposure_catalog(self, festival_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/exposure-catalog", headers=headers)

    def patch_exposure_catalog(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/festivals/{festival_id}/exposure-catalog",
                             payload=payload, headers=headers)

    def run_sponsor_allocation_sweep(self, festival_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/sponsor-allocation-sweep",
                             payload=payload or {}, headers=headers)

    # ------------------------------------------------------------------
    # Program versions
    # ------------------------------------------------------------------
    def create_program_version(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-versions",
                             payload=payload, headers=headers)

    def list_program_versions(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/program-versions",
                             headers=headers, params=params)

    def get_program_version(self, festival_id: str, version_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/program-versions/{version_id}", headers=headers)

    def submit_program_version_for_review(self, festival_id: str, version_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-versions/{version_id}/submit-for-review",
                             payload={}, headers=headers)

    def return_program_version_for_revision(self, festival_id: str, version_id: str,
                                            payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-versions/{version_id}/return-for-revision",
                             payload=payload, headers=headers)

    def publish_program_version(self, festival_id: str, version_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-versions/{version_id}/publish",
                             payload={}, headers=headers)

    def withdraw_program_version(self, festival_id: str, version_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-versions/{version_id}/withdraw",
                             payload={}, headers=headers)

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def create_stage(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/stages",
                             payload=payload, headers=headers)

    def list_stages(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/stages", headers=headers, params=params)

    def get_stage(self, festival_id: str, stage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/stages/{stage_id}", headers=headers)

    def patch_stage(self, festival_id: str, stage_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/festivals/{festival_id}/stages/{stage_id}",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Equipment kits
    # ------------------------------------------------------------------
    def create_equipment_kit(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/equipment-kits",
                             payload=payload, headers=headers)

    def list_equipment_kits(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/equipment-kits",
                             headers=headers, params=params)

    def get_equipment_kit(self, festival_id: str, kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/equipment-kits/{kit_id}", headers=headers)

    def patch_equipment_kit(self, festival_id: str, kit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/festivals/{festival_id}/equipment-kits/{kit_id}",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Artists (global catalog)
    # ------------------------------------------------------------------
    def create_artist(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/artists", payload=payload, headers=headers)

    def list_artists(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/artists", headers=headers, params=params)

    def get_artist(self, artist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def patch_artist(self, artist_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/artists/{artist_id}", payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Program items
    # ------------------------------------------------------------------
    def create_program_item(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items",
                             payload=payload, headers=headers)

    def list_program_items(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/program-items",
                             headers=headers, params=params)

    def get_program_item(self, festival_id: str, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/program-items/{item_id}", headers=headers)

    def patch_program_item(self, festival_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/festivals/{festival_id}/program-items/{item_id}",
                             payload=payload, headers=headers)

    def confirm_program_item(self, festival_id: str, item_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/confirm",
                             payload=payload or {}, headers=headers)

    def announce_program_item(self, festival_id: str, item_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/announce",
                             payload=payload or {}, headers=headers)

    def cancel_program_item(self, festival_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/cancel",
                             payload=payload, headers=headers)

    def recompute_program_item_priority(self, festival_id: str, item_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/recompute-priority",
                             payload={}, headers=headers)

    def waive_sound_check(self, festival_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/sound-check/waive",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Rider requirements
    # ------------------------------------------------------------------
    def create_rider(self, festival_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/riders",
                             payload=payload, headers=headers)

    def list_riders(self, festival_id: str, item_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/program-items/{item_id}/riders",
                             headers=headers, params=params)

    def fulfil_rider(self, festival_id: str, item_id: str, rider_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH",
                             f"/festivals/{festival_id}/program-items/{item_id}/riders/{rider_id}",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Sound-engineer teams
    # ------------------------------------------------------------------
    def create_sound_engineer_team(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/sound-engineer-teams",
                             payload=payload, headers=headers)

    def list_sound_engineer_teams(self, festival_id: str, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/sound-engineer-teams",
                             headers=headers, params=params)

    def get_sound_engineer_team(self, festival_id: str, team_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/sound-engineer-teams/{team_id}",
                             headers=headers)

    def withdraw_sound_engineer_team(self, festival_id: str, team_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/sound-engineer-teams/{team_id}/withdraw",
                             payload={}, headers=headers)

    # ------------------------------------------------------------------
    # Sound-check slots
    # ------------------------------------------------------------------
    def create_sound_check(self, festival_id: str, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/program-items/{item_id}/sound-checks",
                             payload=payload, headers=headers)

    def list_sound_checks(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/sound-checks",
                             headers=headers, params=params)

    def get_sound_check(self, festival_id: str, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/sound-checks/{slot_id}", headers=headers)

    def patch_sound_check(self, festival_id: str, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/festivals/{festival_id}/sound-checks/{slot_id}",
                             payload=payload, headers=headers)

    def complete_sound_check(self, festival_id: str, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/sound-checks/{slot_id}/complete",
                             payload={}, headers=headers)

    def cancel_sound_check(self, festival_id: str, slot_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/sound-checks/{slot_id}/cancel",
                             payload=payload or {}, headers=headers)

    # ------------------------------------------------------------------
    # Rehearsals
    # ------------------------------------------------------------------
    def create_rehearsal(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/rehearsals",
                             payload=payload, headers=headers)

    def list_rehearsals(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/rehearsals", headers=headers, params=params)

    def get_rehearsal(self, festival_id: str, rehearsal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/rehearsals/{rehearsal_id}", headers=headers)

    def cancel_rehearsal(self, festival_id: str, rehearsal_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/rehearsals/{rehearsal_id}/cancel",
                             payload=payload or {}, headers=headers)

    # ------------------------------------------------------------------
    # Ticket types and issuance
    # ------------------------------------------------------------------
    def create_ticket_type(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/ticket-types",
                             payload=payload, headers=headers)

    def list_ticket_types(self, festival_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/ticket-types",
                             headers=headers, params=params)

    def get_ticket_type(self, festival_id: str, ticket_type_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/ticket-types/{ticket_type_id}", headers=headers)

    def issue_tickets(self, festival_id: str, ticket_type_id: str,
                      payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/ticket-types/{ticket_type_id}/issue",
                             payload=payload, headers=headers)

    def suspend_ticket_type(self, festival_id: str, ticket_type_id: str,
                            headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/ticket-types/{ticket_type_id}/suspend",
                             payload=payload or {}, headers=headers)

    def resume_ticket_type(self, festival_id: str, ticket_type_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/ticket-types/{ticket_type_id}/resume",
                             payload={}, headers=headers)

    # ------------------------------------------------------------------
    # Sponsor tiers and exposure allocations
    # ------------------------------------------------------------------
    def create_sponsor_tier(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/sponsor-tiers",
                             payload=payload, headers=headers)

    def list_sponsor_tiers(self, festival_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/sponsor-tiers", headers=headers, params=params)

    def get_sponsor_tier(self, festival_id: str, tier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/sponsor-tiers/{tier_id}", headers=headers)

    def get_fulfilment_report(self, festival_id: str, tier_id: str, headers: Dict[str, str]):
        return self._request("GET",
                             f"/festivals/{festival_id}/sponsor-tiers/{tier_id}/fulfilment-report",
                             headers=headers)

    def create_exposure_allocation(self, festival_id: str, tier_id: str,
                                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST",
                             f"/festivals/{festival_id}/sponsor-tiers/{tier_id}/exposure-allocations",
                             payload=payload, headers=headers)

    def list_exposure_allocations(self, festival_id: str, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/exposure-allocations",
                             headers=headers, params=params)

    def get_exposure_allocation(self, festival_id: str, allocation_id: str, headers: Dict[str, str]):
        return self._request("GET",
                             f"/festivals/{festival_id}/exposure-allocations/{allocation_id}",
                             headers=headers)

    def deliver_exposure(self, festival_id: str, allocation_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST",
                             f"/festivals/{festival_id}/exposure-allocations/{allocation_id}/deliver",
                             payload=payload, headers=headers)

    def void_exposure_delivery(self, festival_id: str, allocation_id: str,
                               payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST",
                             f"/festivals/{festival_id}/exposure-allocations/{allocation_id}/void-delivery",
                             payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Schedule changes (the event-driven-sync surface)
    # ------------------------------------------------------------------
    def create_schedule_change(self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/schedule-changes",
                             payload=payload, headers=headers)

    def list_schedule_changes(self, festival_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/schedule-changes",
                             headers=headers, params=params)

    def get_schedule_change(self, festival_id: str, change_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/festivals/{festival_id}/schedule-changes/{change_id}", headers=headers)

    def apply_schedule_change(self, festival_id: str, change_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/festivals/{festival_id}/schedule-changes/{change_id}/apply",
                             payload=payload or {}, headers=headers)

    def reject_schedule_change(self, festival_id: str, change_id: str,
                               payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/schedule-changes/{change_id}/reject",
                             payload=payload, headers=headers)

    def revert_schedule_change(self, festival_id: str, change_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/festivals/{festival_id}/schedule-changes/{change_id}/revert",
                             payload={}, headers=headers)

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    def list_audit_entries(self, festival_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/festivals/{festival_id}/audit-entries",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Operator-only test endpoints under /_clock, /_events, /_sweep
    # ------------------------------------------------------------------
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload=payload, headers=headers)

    def get_clock(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/_clock", headers=headers, params=params)

    def sync_ack(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/sync-ack", payload=payload, headers=headers)

    def refund_confirmed(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/refund-confirmed", payload=payload, headers=headers)

    def run_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", payload=payload, headers=headers)


# Module-level singleton, instantiated lazily.  The framework's
# `GenericApiClient` reads the API_BASE_URL environment variable that the
# prd-bench-local-runner harness sets before the pytest subprocess starts.
api_client: ApiClient = ApiClient(base_url=os.environ.get("API_BASE_URL", "http://localhost:8080"))


__all__ = ["ApiClient", "api_client"]
