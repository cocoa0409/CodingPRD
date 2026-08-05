"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- PublicBody ----
    def create_public_body(self, payload, headers):
        return self._request("POST", "/public-bodies", payload, headers)

    def get_public_body(self, body_id, headers):
        return self._request("GET", f"/public-bodies/{body_id}", headers=headers)

    # ---- BodyMember ----
    def add_member(self, body_id, payload, headers):
        return self._request("POST", f"/public-bodies/{body_id}/members", payload, headers)

    def list_members(self, body_id, headers, params=None):
        return self._request("GET", f"/public-bodies/{body_id}/members",
                             headers=headers, params=params)

    # ---- Venue ----
    def add_venue(self, body_id, payload, headers):
        return self._request("POST", f"/public-bodies/{body_id}/venues", payload, headers)

    def list_venues(self, body_id, headers, params=None):
        return self._request("GET", f"/public-bodies/{body_id}/venues",
                             headers=headers, params=params)

    # ---- Meeting ----
    def create_meeting(self, body_id, payload, headers):
        return self._request("POST", f"/public-bodies/{body_id}/meetings", payload, headers)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/meetings/{meeting_id}", headers=headers)

    def list_meetings(self, body_id, headers, params=None):
        return self._request("GET", f"/public-bodies/{body_id}/meetings",
                             headers=headers, params=params)

    def transition_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/meetings/{meeting_id}/transition", payload, headers)

    def meeting_minutes(self, meeting_id, payload, headers):
        return self._request("POST", f"/meetings/{meeting_id}/minutes", payload, headers)

    # ---- AgendaItem ----
    def create_agenda_item(self, meeting_id, payload, headers):
        return self._request("POST", f"/meetings/{meeting_id}/agenda-items", payload, headers)

    def get_agenda_item(self, item_id, headers):
        return self._request("GET", f"/agenda-items/{item_id}", headers=headers)

    def list_agenda_items(self, meeting_id, headers, params=None):
        return self._request("GET", f"/meetings/{meeting_id}/agenda-items",
                             headers=headers, params=params)

    def transition_agenda_item(self, item_id, payload, headers):
        return self._request("POST", f"/agenda-items/{item_id}/transition", payload, headers)

    # ---- SpeakerSlip ----
    def create_speaker_slip(self, item_id, payload, headers):
        return self._request("POST", f"/agenda-items/{item_id}/speaker-slips", payload, headers)

    def list_speaker_slips(self, item_id, headers, params=None):
        return self._request("GET", f"/agenda-items/{item_id}/speaker-slips",
                             headers=headers, params=params)

    def transition_speaker_slip(self, slip_id, payload, headers):
        return self._request("POST", f"/speaker-slips/{slip_id}/transition", payload, headers)

    # ---- Motion ----
    def create_motion(self, item_id, payload, headers):
        return self._request("POST", f"/agenda-items/{item_id}/motions", payload, headers)

    def list_motions(self, item_id, headers, params=None):
        return self._request("GET", f"/agenda-items/{item_id}/motions",
                             headers=headers, params=params)

    def transition_motion(self, motion_id, payload, headers):
        return self._request("POST", f"/motions/{motion_id}/transition", payload, headers)

    def cast_vote(self, motion_id, payload, headers):
        return self._request("POST", f"/motions/{motion_id}/votes", payload, headers)

    # ---- Requester ----
    def create_requester(self, payload, headers):
        return self._request("POST", "/requesters", payload, headers)

    # ---- RecordsRequest ----
    def create_records_request(self, payload, headers):
        return self._request("POST", "/records-requests", payload, headers)

    def get_records_request(self, request_id, headers):
        return self._request("GET", f"/records-requests/{request_id}", headers=headers)

    def list_records_requests(self, headers, params=None):
        return self._request("GET", "/records-requests", headers=headers, params=params)

    def transition_records_request(self, request_id, payload, headers):
        return self._request("POST", f"/records-requests/{request_id}/transition", payload, headers)

    def determine_request(self, request_id, payload, headers):
        return self._request("POST", f"/records-requests/{request_id}/determination", payload, headers)

    def pay_request(self, request_id, payload, headers):
        return self._request("POST", f"/records-requests/{request_id}/payments", payload, headers)

    # ---- ResponsiveDocument ----
    def create_document(self, request_id, payload, headers):
        return self._request("POST", f"/records-requests/{request_id}/documents", payload, headers)

    def list_documents(self, request_id, headers, params=None):
        return self._request("GET", f"/records-requests/{request_id}/documents",
                             headers=headers, params=params)

    def transition_document(self, request_id, doc_id, payload, headers):
        return self._request("POST",
                             f"/records-requests/{request_id}/documents/{doc_id}/transition",
                             payload, headers)

    # ---- Appeal ----
    def create_appeal(self, request_id, payload, headers):
        return self._request("POST", f"/records-requests/{request_id}/appeals", payload, headers)

    def list_appeals(self, request_id, headers, params=None):
        return self._request("GET", f"/records-requests/{request_id}/appeals",
                             headers=headers, params=params)

    def transition_appeal(self, request_id, appeal_id, payload, headers):
        return self._request("POST",
                             f"/records-requests/{request_id}/appeals/{appeal_id}/transition",
                             payload, headers)


api_client = ApiClient()
