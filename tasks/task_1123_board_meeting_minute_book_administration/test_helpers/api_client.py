"""API client: one method per endpoint defined in the Board Governance PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Board Governance API client. All methods return requests.Response."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Corporations ---
    def create_corporation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/corporations", payload, headers)

    def list_corporations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/corporations", headers=headers, params=params)

    def get_corporation(self, corporation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/corporations/{corporation_id}", headers=headers)

    def run_checkpoint(self, corporation_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/corporations/{corporation_id}/run_checkpoint", headers=headers)

    # --- Bylaws ---
    def create_bylaws(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/bylaws", payload, headers)

    def list_bylaws(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/bylaws", headers=headers, params=params)

    def get_bylaws(self, bylaws_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bylaws/{bylaws_id}", headers=headers)

    def adopt_bylaws(self, bylaws_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bylaws/{bylaws_id}/adopt", payload, headers)

    # --- Directors ---
    def create_director(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/directors", payload, headers)

    def list_directors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/directors", headers=headers, params=params)

    def get_director(self, director_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/directors/{director_id}", headers=headers)

    def resign_director(self, director_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/directors/{director_id}/resign", headers=headers)

    def review_independence(self, director_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/directors/{director_id}/review_independence", payload, headers)

    # --- Committees ---
    def create_committee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/committees", payload, headers)

    def list_committees(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/committees", headers=headers, params=params)

    def get_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/committees/{committee_id}", headers=headers)

    def activate_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/committees/{committee_id}/activate", headers=headers)

    def dissolve_committee(self, committee_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/committees/{committee_id}/dissolve", headers=headers)

    # --- Committee memberships ---
    def create_committee_membership(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/committee_memberships", payload, headers)

    def list_committee_memberships(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/committee_memberships", headers=headers, params=params)

    def get_committee_membership(self, membership_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/committee_memberships/{membership_id}", headers=headers)

    def end_committee_membership(self, membership_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/committee_memberships/{membership_id}/end", headers=headers)

    # --- Meetings ---
    def create_meeting(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/meetings", payload, headers)

    def list_meetings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/meetings/{meeting_id}", headers=headers)

    def send_notices(self, meeting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/meetings/{meeting_id}/send_notices", headers=headers)

    def reschedule_meeting(self, meeting_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/meetings/{meeting_id}/reschedule", payload, headers)

    def cancel_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/meetings/{meeting_id}/cancel", headers=headers)

    def convene_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/meetings/{meeting_id}/convene", headers=headers)

    def adjourn_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/meetings/{meeting_id}/adjourn", headers=headers)

    # --- Meeting notices ---
    def list_meeting_notices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/meeting_notices", headers=headers, params=params)

    def get_meeting_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/meeting_notices/{notice_id}", headers=headers)

    def waive_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/meeting_notices/{notice_id}/waive", headers=headers)

    # --- Attendance ---
    def create_attendance_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/attendance_records", payload, headers)

    def list_attendance_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/attendance_records", headers=headers, params=params)

    def get_attendance_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/attendance_records/{record_id}", headers=headers)

    # --- Agenda items ---
    def create_agenda_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agenda_items", payload, headers)

    def list_agenda_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agenda_items", headers=headers, params=params)

    def get_agenda_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agenda_items/{item_id}", headers=headers)

    def include_agenda_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agenda_items/{item_id}/include", headers=headers)

    def drop_agenda_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agenda_items/{item_id}/drop", headers=headers)

    # --- Board packages ---
    def create_board_package(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/board_packages", payload, headers)

    def list_board_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/board_packages", headers=headers, params=params)

    def get_board_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/board_packages/{package_id}", headers=headers)

    def seal_board_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/board_packages/{package_id}/seal", headers=headers)

    def unseal_board_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/board_packages/{package_id}/unseal", headers=headers)

    def distribute_board_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/board_packages/{package_id}/distribute", headers=headers)

    # --- Package documents ---
    def create_package_document(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/package_documents", payload, headers)

    def list_package_documents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/package_documents", headers=headers, params=params)

    def get_package_document(self, document_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/package_documents/{document_id}", headers=headers)

    # --- Resolutions ---
    def create_resolution(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/resolutions", payload, headers)

    def list_resolutions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/resolutions", headers=headers, params=params)

    def get_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/resolutions/{resolution_id}", headers=headers)

    def table_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/table", headers=headers)

    def open_vote(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/open_vote", headers=headers)

    def close_vote(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/close_vote", headers=headers)

    def redraft_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/redraft", headers=headers)

    def circulate_consent(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/circulate_consent", headers=headers)

    def finalize_consent(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/resolutions/{resolution_id}/finalize_consent", headers=headers)

    # --- Vote records ---
    def create_vote_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vote_records", payload, headers)

    def list_vote_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vote_records", headers=headers, params=params)

    def get_vote_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vote_records/{record_id}", headers=headers)

    def recast_vote(self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/vote_records/{record_id}/recast", payload, headers)

    # --- Conflict disclosures ---
    def create_conflict_disclosure(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conflict_disclosures", payload, headers)

    def list_conflict_disclosures(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conflict_disclosures", headers=headers, params=params)

    def get_conflict_disclosure(self, disclosure_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conflict_disclosures/{disclosure_id}", headers=headers)

    def clear_conflict_disclosure(self, disclosure_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conflict_disclosures/{disclosure_id}/clear", headers=headers)

    # --- Minutes ---
    def list_minutes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/minutes", headers=headers, params=params)

    def get_minutes(self, minutes_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/minutes/{minutes_id}", headers=headers)

    def circulate_minutes(self, minutes_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/minutes/{minutes_id}/circulate", payload, headers)

    def approve_minutes(self, minutes_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/minutes/{minutes_id}/approve", headers=headers)

    def reject_minutes(self, minutes_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/minutes/{minutes_id}/reject", payload, headers)

    def redraft_minutes(self, minutes_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/minutes/{minutes_id}/redraft", payload, headers)

    def enter_book_minutes(self, minutes_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/minutes/{minutes_id}/enter_book", headers=headers)

    # --- Audit requests ---
    def create_audit_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/audit_requests", payload, headers)

    def list_audit_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit_requests", headers=headers, params=params)

    def get_audit_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit_requests/{request_id}", headers=headers)

    def reconstruct_audit_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/audit_requests/{request_id}/reconstruct", headers=headers)


api_client = ApiClient()
