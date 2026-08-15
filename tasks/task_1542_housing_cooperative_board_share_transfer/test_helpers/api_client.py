"""API client: one method per endpoint defined in the PRD (section 4).

All routes live under the /cooperatives mount, including the flat
cross-cooperative read aliases of section 2.10.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Cooperative + logical clock
    # ------------------------------------------------------------------
    def create_cooperative(self, payload, headers):
        return self._request("POST", "/cooperatives", payload, headers)

    def get_cooperative(self, coop_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}", headers=headers)

    def list_cooperatives(self, headers, params=None):
        return self._request("GET", "/cooperatives", headers=headers, params=params)

    def set_clock(self, coop_id, to_iso8601, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------
    def create_unit(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/units", payload, headers)

    def list_units(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/units",
                             headers=headers, params=params)

    def get_unit(self, coop_id, unit_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/units/{unit_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Shareholders
    # ------------------------------------------------------------------
    def create_shareholder(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/shareholders",
                             payload, headers)

    def list_shareholders(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/shareholders",
                             headers=headers, params=params)

    def get_shareholder(self, coop_id, shareholder_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/shareholders/{shareholder_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Share ledger entries
    # ------------------------------------------------------------------
    def create_share_ledger_entry(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/share-ledger-entries",
                             payload, headers)

    def list_share_ledger_entries(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/share-ledger-entries",
                             headers=headers, params=params)

    def get_share_ledger_entry(self, coop_id, entry_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/share-ledger-entries/{entry_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # Charge schedules
    # ------------------------------------------------------------------
    def create_charge_schedule(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/charge-schedules",
                             payload, headers)

    def list_charge_schedules(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/charge-schedules",
                             headers=headers, params=params)

    def get_charge_schedule(self, coop_id, schedule_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/charge-schedules/{schedule_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # Maintenance charges + payments
    # ------------------------------------------------------------------
    def list_maintenance_charges(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/maintenance-charges",
                             headers=headers, params=params)

    def get_maintenance_charge(self, coop_id, charge_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/maintenance-charges/{charge_id}",
            headers=headers)

    def post_payment(self, coop_id, charge_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/maintenance-charges/{charge_id}/payments",
            payload, headers)

    def void_payment(self, coop_id, payment_id, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/payments/{payment_id}/void",
                             {}, headers)

    def get_payment(self, coop_id, payment_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/payments/{payment_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Arrears actions
    # ------------------------------------------------------------------
    def create_arrears_action(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/arrears-actions",
                             payload, headers)

    def list_arrears_actions(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/arrears-actions",
                             headers=headers, params=params)

    def get_arrears_action(self, coop_id, action_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/arrears-actions/{action_id}",
                             headers=headers)

    def escalate_arrears_action(self, coop_id, action_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/arrears-actions/{action_id}/escalate",
            {}, headers)

    def withdraw_arrears_action(self, coop_id, action_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/arrears-actions/{action_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Purchase applications
    # ------------------------------------------------------------------
    def create_purchase_application(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/purchase-applications",
                             payload, headers)

    def list_purchase_applications(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/purchase-applications",
                             headers=headers, params=params)

    def get_purchase_application(self, coop_id, app_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/purchase-applications/{app_id}",
            headers=headers)

    def submit_purchase_application(self, coop_id, app_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/purchase-applications/{app_id}/submit",
            {}, headers)

    def certify_purchase_application(self, coop_id, app_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/purchase-applications/{app_id}/certify",
            {}, headers)

    def request_info(self, coop_id, app_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/purchase-applications/{app_id}/request-info",
            payload, headers)

    def submit_info(self, coop_id, app_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/purchase-applications/{app_id}/submit-info",
            payload, headers)

    def schedule_interview(self, coop_id, app_id, payload, headers):
        return self._request(
            "POST",
            f"/cooperatives/{coop_id}/purchase-applications/{app_id}/schedule-interview",
            payload, headers)

    def record_transfer(self, coop_id, app_id, payload, headers):
        return self._request(
            "POST",
            f"/cooperatives/{coop_id}/purchase-applications/{app_id}/record-transfer",
            payload, headers)

    def withdraw_purchase_application(self, coop_id, app_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/purchase-applications/{app_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Interviews
    # ------------------------------------------------------------------
    def list_interviews(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/interviews",
                             headers=headers, params=params)

    def get_interview(self, coop_id, interview_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/interviews/{interview_id}",
                             headers=headers)

    def complete_interview(self, coop_id, interview_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/interviews/{interview_id}/complete",
            payload, headers)

    def cancel_interview(self, coop_id, interview_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/interviews/{interview_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Resolutions + votes
    # ------------------------------------------------------------------
    def create_resolution(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/resolutions",
                             payload, headers)

    def list_resolutions(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/resolutions",
                             headers=headers, params=params)

    def get_resolution(self, coop_id, resolution_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/resolutions/{resolution_id}",
                             headers=headers)

    def cast_vote(self, coop_id, resolution_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/resolutions/{resolution_id}/vote",
            payload, headers)

    def withdraw_resolution(self, coop_id, resolution_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/resolutions/{resolution_id}/withdraw",
            {}, headers)

    def list_resolution_votes(self, coop_id, resolution_id, headers, params=None):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/resolutions/{resolution_id}/votes",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Sublet agreements
    # ------------------------------------------------------------------
    def create_sublet_agreement(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/sublet-agreements",
                             payload, headers)

    def list_sublet_agreements(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/sublet-agreements",
                             headers=headers, params=params)

    def get_sublet_agreement(self, coop_id, sublet_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/sublet-agreements/{sublet_id}",
            headers=headers)

    def submit_sublet(self, coop_id, sublet_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/sublet-agreements/{sublet_id}/submit",
            {}, headers)

    def reject_sublet(self, coop_id, sublet_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/sublet-agreements/{sublet_id}/reject",
            {}, headers)

    def terminate_sublet_early(self, coop_id, sublet_id, headers):
        return self._request(
            "POST",
            f"/cooperatives/{coop_id}/sublet-agreements/{sublet_id}/terminate-early",
            {}, headers)

    # ------------------------------------------------------------------
    # Alteration agreements
    # ------------------------------------------------------------------
    def create_alteration_agreement(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/alteration-agreements",
                             payload, headers)

    def list_alteration_agreements(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/alteration-agreements",
                             headers=headers, params=params)

    def get_alteration_agreement(self, coop_id, alteration_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/alteration-agreements/{alteration_id}",
            headers=headers)

    def submit_alteration(self, coop_id, alteration_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/alteration-agreements/{alteration_id}/submit",
            {}, headers)

    def start_alteration_work(self, coop_id, alteration_id, headers):
        return self._request(
            "POST",
            f"/cooperatives/{coop_id}/alteration-agreements/{alteration_id}/start-work",
            {}, headers)

    def complete_alteration(self, coop_id, alteration_id, headers):
        return self._request(
            "POST",
            f"/cooperatives/{coop_id}/alteration-agreements/{alteration_id}/complete",
            {}, headers)

    def abandon_alteration(self, coop_id, alteration_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/alteration-agreements/{alteration_id}/abandon",
            {}, headers)

    # ------------------------------------------------------------------
    # Meetings + ballots
    # ------------------------------------------------------------------
    def create_meeting(self, coop_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/meetings", payload, headers)

    def list_meetings(self, coop_id, headers, params=None):
        return self._request("GET", f"/cooperatives/{coop_id}/meetings",
                             headers=headers, params=params)

    def get_meeting(self, coop_id, meeting_id, headers):
        return self._request("GET", f"/cooperatives/{coop_id}/meetings/{meeting_id}",
                             headers=headers)

    def send_meeting_notice(self, coop_id, meeting_id, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/meetings/{meeting_id}/send-notice",
            {}, headers)

    def open_meeting(self, coop_id, meeting_id, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/meetings/{meeting_id}/open",
                             {}, headers)

    def close_meeting(self, coop_id, meeting_id, payload, headers):
        return self._request("POST", f"/cooperatives/{coop_id}/meetings/{meeting_id}/close",
                             payload, headers)

    def cast_ballot(self, coop_id, meeting_id, payload, headers):
        return self._request(
            "POST", f"/cooperatives/{coop_id}/meetings/{meeting_id}/ballots",
            payload, headers)

    def list_ballots(self, coop_id, meeting_id, headers, params=None):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/meetings/{meeting_id}/ballots",
            headers=headers, params=params)

    def get_ballot(self, coop_id, meeting_id, ballot_id, headers):
        return self._request(
            "GET", f"/cooperatives/{coop_id}/meetings/{meeting_id}/ballots/{ballot_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # Flat cross-cooperative read aliases (section 2.10)
    # ------------------------------------------------------------------
    def flat_get_unit(self, unit_id, headers):
        return self._request("GET", f"/cooperatives/units/{unit_id}", headers=headers)

    def flat_list_units(self, headers, params=None):
        return self._request("GET", "/cooperatives/units", headers=headers, params=params)

    def flat_get_shareholder(self, shareholder_id, headers):
        return self._request("GET", f"/cooperatives/shareholders/{shareholder_id}",
                             headers=headers)

    def flat_list_shareholders(self, headers, params=None):
        return self._request("GET", "/cooperatives/shareholders", headers=headers,
                             params=params)

    def flat_get_share_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/cooperatives/share-ledger-entries/{entry_id}",
                             headers=headers)

    def flat_list_share_ledger_entries(self, headers, params=None):
        return self._request("GET", "/cooperatives/share-ledger-entries", headers=headers,
                             params=params)

    def flat_get_charge_schedule(self, schedule_id, headers):
        return self._request("GET", f"/cooperatives/charge-schedules/{schedule_id}",
                             headers=headers)

    def flat_list_charge_schedules(self, headers, params=None):
        return self._request("GET", "/cooperatives/charge-schedules", headers=headers,
                             params=params)

    def flat_get_maintenance_charge(self, charge_id, headers):
        return self._request("GET", f"/cooperatives/maintenance-charges/{charge_id}",
                             headers=headers)

    def flat_list_maintenance_charges(self, headers, params=None):
        return self._request("GET", "/cooperatives/maintenance-charges", headers=headers,
                             params=params)

    def flat_get_payment(self, payment_id, headers):
        return self._request("GET", f"/cooperatives/payments/{payment_id}", headers=headers)

    def flat_list_payments(self, headers, params=None):
        return self._request("GET", "/cooperatives/payments", headers=headers,
                             params=params)

    def flat_get_arrears_action(self, action_id, headers):
        return self._request("GET", f"/cooperatives/arrears-actions/{action_id}",
                             headers=headers)

    def flat_list_arrears_actions(self, headers, params=None):
        return self._request("GET", "/cooperatives/arrears-actions", headers=headers,
                             params=params)

    def flat_get_purchase_application(self, app_id, headers):
        return self._request("GET", f"/cooperatives/purchase-applications/{app_id}",
                             headers=headers)

    def flat_list_purchase_applications(self, headers, params=None):
        return self._request("GET", "/cooperatives/purchase-applications", headers=headers,
                             params=params)

    def flat_get_interview(self, interview_id, headers):
        return self._request("GET", f"/cooperatives/interviews/{interview_id}",
                             headers=headers)

    def flat_list_interviews(self, headers, params=None):
        return self._request("GET", "/cooperatives/interviews", headers=headers,
                             params=params)

    def flat_get_resolution(self, resolution_id, headers):
        return self._request("GET", f"/cooperatives/resolutions/{resolution_id}",
                             headers=headers)

    def flat_list_resolutions(self, headers, params=None):
        return self._request("GET", "/cooperatives/resolutions", headers=headers,
                             params=params)

    def flat_get_resolution_vote(self, vote_id, headers):
        return self._request("GET", f"/cooperatives/resolution-votes/{vote_id}",
                             headers=headers)

    def flat_list_resolution_votes(self, headers, params=None):
        return self._request("GET", "/cooperatives/resolution-votes", headers=headers,
                             params=params)

    def flat_get_sublet_agreement(self, sublet_id, headers):
        return self._request("GET", f"/cooperatives/sublet-agreements/{sublet_id}",
                             headers=headers)

    def flat_list_sublet_agreements(self, headers, params=None):
        return self._request("GET", "/cooperatives/sublet-agreements", headers=headers,
                             params=params)

    def flat_get_alteration_agreement(self, alteration_id, headers):
        return self._request("GET", f"/cooperatives/alteration-agreements/{alteration_id}",
                             headers=headers)

    def flat_list_alteration_agreements(self, headers, params=None):
        return self._request("GET", "/cooperatives/alteration-agreements", headers=headers,
                             params=params)

    def flat_get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/cooperatives/meetings/{meeting_id}", headers=headers)

    def flat_list_meetings(self, headers, params=None):
        return self._request("GET", "/cooperatives/meetings", headers=headers,
                             params=params)

    def flat_get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/cooperatives/ballots/{ballot_id}", headers=headers)

    def flat_list_ballots(self, headers, params=None):
        return self._request("GET", "/cooperatives/ballots", headers=headers,
                             params=params)


api_client = ApiClient()
