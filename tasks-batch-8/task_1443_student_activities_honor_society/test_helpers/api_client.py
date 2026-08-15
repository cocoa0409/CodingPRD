"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Chapter ---
    def create_chapter(self, payload, headers):
        return self._request("POST", "/chapters", payload, headers)

    def get_chapter(self, chapter_id, headers):
        return self._request("GET", f"/chapters/{chapter_id}", headers=headers)

    def list_chapters(self, headers, params=None):
        return self._request("GET", "/chapters", headers=headers, params=params)

    def activate_chapter(self, chapter_id, headers):
        return self._request("POST", f"/chapters/{chapter_id}/activate",
                             headers=headers)

    def suspend_chapter(self, chapter_id, headers):
        return self._request("POST", f"/chapters/{chapter_id}/suspend",
                             headers=headers)

    def reinstate_chapter(self, chapter_id, headers):
        return self._request("POST", f"/chapters/{chapter_id}/reinstate",
                             headers=headers)

    def dissolve_chapter(self, chapter_id, headers):
        return self._request("POST", f"/chapters/{chapter_id}/dissolve",
                             headers=headers)

    def get_chapter_standing(self, chapter_id, headers):
        return self._request("GET", f"/chapters/{chapter_id}/standing",
                             headers=headers)

    # --- Member ---
    def create_member(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/members",
                             payload, headers)

    def get_member(self, chapter_id, member_id, headers):
        return self._request("GET",
                             f"/chapters/{chapter_id}/members/{member_id}",
                             headers=headers)

    def list_members(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/members",
                             headers=headers, params=params)

    def get_member_standing(self, chapter_id, member_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/members/{member_id}/standing",
            headers=headers)

    def nominate_member(self, chapter_id, member_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/nominate",
            headers=headers)

    def reinstate_member(self, chapter_id, member_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/reinstate",
            headers=headers)

    def dismiss_member(self, chapter_id, member_id, payload, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/dismiss",
            payload, headers)

    def graduate_member(self, chapter_id, member_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/graduate",
            headers=headers)

    # --- MembershipCycle ---
    def create_cycle(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/membership-cycles",
                             payload, headers)

    def get_cycle(self, chapter_id, cycle_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/membership-cycles/{cycle_id}",
            headers=headers)

    def list_cycles(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/membership-cycles",
                             headers=headers, params=params)

    def open_nominations(self, chapter_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/open-nominations",
            headers=headers)

    def close_nominations(self, chapter_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/close-nominations",
            headers=headers)

    def induct_cycle(self, chapter_id, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/induct",
            payload, headers)

    def close_cycle(self, chapter_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/close",
            headers=headers)

    def cancel_cycle(self, chapter_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/cancel",
            headers=headers)

    # --- CycleApplication ---
    def list_applications(self, chapter_id, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/applications",
            headers=headers, params=params)

    def get_application(self, chapter_id, cycle_id, application_id, headers):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/applications/{application_id}",
            headers=headers)

    def approve_application(self, chapter_id, cycle_id, application_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/applications/{application_id}/approve",
            headers=headers)

    def reject_application(self, chapter_id, cycle_id, application_id, payload,
                           headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/applications/{application_id}/reject",
            payload, headers)

    def withdraw_application(self, chapter_id, cycle_id, application_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/membership-cycles/{cycle_id}/applications/{application_id}/withdraw",
            headers=headers)

    # --- ServiceHourEntry ---
    def create_service_entry(self, chapter_id, member_id, payload, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries",
            payload, headers)

    def list_service_entries(self, chapter_id, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries",
            headers=headers, params=params)

    def get_service_entry(self, chapter_id, member_id, entry_id, headers):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries/{entry_id}",
            headers=headers)

    def verify_service_entry(self, chapter_id, member_id, entry_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries/{entry_id}/verify",
            headers=headers)

    def reject_service_entry(self, chapter_id, member_id, entry_id, payload,
                             headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries/{entry_id}/reject",
            payload, headers)

    def void_service_entry(self, chapter_id, member_id, entry_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/service-hour-entries/{entry_id}/void",
            headers=headers)

    # --- OfficerElection ---
    def create_election(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/elections",
                             payload, headers)

    def get_election(self, chapter_id, election_id, headers):
        return self._request("GET",
                             f"/chapters/{chapter_id}/elections/{election_id}",
                             headers=headers)

    def list_elections(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/elections",
                             headers=headers, params=params)

    def open_election(self, chapter_id, election_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/elections/{election_id}/open",
            headers=headers)

    def tally_election(self, chapter_id, election_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/elections/{election_id}/tally",
            headers=headers)

    def certify_election(self, chapter_id, election_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/elections/{election_id}/certify",
            headers=headers)

    def void_election(self, chapter_id, election_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/elections/{election_id}/void",
            headers=headers)

    # --- ElectionVote ---
    def cast_vote(self, chapter_id, election_id, payload, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/elections/{election_id}/votes",
            payload, headers)

    def list_votes(self, chapter_id, election_id, headers, params=None):
        return self._request(
            "GET", f"/chapters/{chapter_id}/elections/{election_id}/votes",
            headers=headers, params=params)

    # --- OfficerRole ---
    def list_officer_roles(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/officer-roles",
                             headers=headers, params=params)

    def get_officer_role(self, chapter_id, role_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/officer-roles/{role_id}",
            headers=headers)

    def resign_officer_role(self, chapter_id, role_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/officer-roles/{role_id}/resign",
            headers=headers)

    def remove_officer_role(self, chapter_id, role_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/officer-roles/{role_id}/remove",
            headers=headers)

    # --- MeetingMinutes ---
    def create_minutes(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/meeting-minutes",
                             payload, headers)

    def get_minutes(self, chapter_id, minutes_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/meeting-minutes/{minutes_id}",
            headers=headers)

    def list_minutes(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/meeting-minutes",
                             headers=headers, params=params)

    def submit_minutes(self, chapter_id, minutes_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/meeting-minutes/{minutes_id}/submit",
            headers=headers)

    def approve_minutes(self, chapter_id, minutes_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/meeting-minutes/{minutes_id}/approve",
            headers=headers)

    def amend_minutes(self, chapter_id, minutes_id, payload, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/meeting-minutes/{minutes_id}/amend",
            payload, headers)

    # --- FundraiserRequest ---
    def create_fundraiser(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/fundraiser-requests",
                             payload, headers)

    def get_fundraiser(self, chapter_id, fundraiser_id, headers):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}",
            headers=headers)

    def list_fundraisers(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/fundraiser-requests",
                             headers=headers, params=params)

    def submit_fundraiser(self, chapter_id, fundraiser_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/submit",
            headers=headers)

    def advisor_approve_fundraiser(self, chapter_id, fundraiser_id, payload,
                                   headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/advisor-approve",
            payload, headers)

    def director_approve_fundraiser(self, chapter_id, fundraiser_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/director-approve",
            headers=headers)

    def reject_fundraiser(self, chapter_id, fundraiser_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/reject",
            headers=headers)

    def execute_fundraiser(self, chapter_id, fundraiser_id, payload, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/execute",
            payload, headers)

    def close_fundraiser(self, chapter_id, fundraiser_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fundraiser-requests/{fundraiser_id}/close",
            headers=headers)

    # --- FundLedgerEntry ---
    def list_ledger_entries(self, chapter_id, headers, params=None):
        return self._request("GET",
                             f"/chapters/{chapter_id}/fund-ledger-entries",
                             headers=headers, params=params)

    def get_ledger_entry(self, chapter_id, entry_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/fund-ledger-entries/{entry_id}",
            headers=headers)

    def clear_ledger_entry(self, chapter_id, entry_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fund-ledger-entries/{entry_id}/clear",
            headers=headers)

    def void_ledger_entry(self, chapter_id, entry_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/fund-ledger-entries/{entry_id}/void",
            headers=headers)

    # --- DuesPayment ---
    def create_dues_payment(self, chapter_id, member_id, payload, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/dues-payments",
            payload, headers)

    def list_dues_payments(self, chapter_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/chapters/{chapter_id}/members/{member_id}/dues-payments",
            headers=headers, params=params)

    def get_dues_payment(self, chapter_id, member_id, payment_id, headers):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/members/{member_id}/dues-payments/{payment_id}",
            headers=headers)

    def remit_dues_payment(self, chapter_id, member_id, payment_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/dues-payments/{payment_id}/remit",
            headers=headers)

    def void_dues_payment(self, chapter_id, member_id, payment_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/dues-payments/{payment_id}/void",
            headers=headers)

    def refund_dues_payment(self, chapter_id, member_id, payment_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/dues-payments/{payment_id}/refund",
            headers=headers)

    # --- ProbationCase ---
    def create_probation_case(self, chapter_id, member_id, payload, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/members/{member_id}/probation-cases",
            payload, headers)

    def list_probation_cases(self, chapter_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/chapters/{chapter_id}/members/{member_id}/probation-cases",
            headers=headers, params=params)

    def get_probation_case(self, chapter_id, member_id, case_id, headers):
        return self._request(
            "GET",
            f"/chapters/{chapter_id}/members/{member_id}/probation-cases/{case_id}",
            headers=headers)

    def appeal_probation_case(self, chapter_id, member_id, case_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/probation-cases/{case_id}/appeal",
            headers=headers)

    def resolve_probation_case(self, chapter_id, member_id, case_id, payload,
                               headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/probation-cases/{case_id}/resolve",
            payload, headers)

    def dismiss_probation_case(self, chapter_id, member_id, case_id, headers):
        return self._request(
            "POST",
            f"/chapters/{chapter_id}/members/{member_id}/probation-cases/{case_id}/dismiss-case",
            headers=headers)

    # --- AthleticsCalendarBlock ---
    def create_athletics_block(self, chapter_id, payload, headers):
        return self._request("POST", f"/chapters/{chapter_id}/athletics-blocks",
                             payload, headers)

    def list_athletics_blocks(self, chapter_id, headers, params=None):
        return self._request("GET", f"/chapters/{chapter_id}/athletics-blocks",
                             headers=headers, params=params)

    def get_athletics_block(self, chapter_id, block_id, headers):
        return self._request(
            "GET", f"/chapters/{chapter_id}/athletics-blocks/{block_id}",
            headers=headers)

    def cancel_athletics_block(self, chapter_id, block_id, headers):
        return self._request(
            "POST", f"/chapters/{chapter_id}/athletics-blocks/{block_id}/cancel",
            headers=headers)

    # --- Flat top-level read endpoints (PRD section 4) ---
    def get_member_flat(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members_flat(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_cycle_flat(self, cycle_id, headers):
        return self._request("GET", f"/membership-cycles/{cycle_id}",
                             headers=headers)

    def list_cycles_flat(self, headers, params=None):
        return self._request("GET", "/membership-cycles", headers=headers,
                             params=params)

    def get_application_flat(self, application_id, headers):
        return self._request("GET", f"/cycle-applications/{application_id}",
                             headers=headers)

    def list_applications_flat(self, headers, params=None):
        return self._request("GET", "/cycle-applications", headers=headers,
                             params=params)

    def get_service_entry_flat(self, entry_id, headers):
        return self._request("GET", f"/service-hour-entries/{entry_id}",
                             headers=headers)

    def list_service_entries_flat(self, headers, params=None):
        return self._request("GET", "/service-hour-entries", headers=headers,
                             params=params)

    def get_election_flat(self, election_id, headers):
        return self._request("GET", f"/officer-elections/{election_id}",
                             headers=headers)

    def list_elections_flat(self, headers, params=None):
        return self._request("GET", "/officer-elections", headers=headers,
                             params=params)

    def get_vote_flat(self, vote_id, headers):
        return self._request("GET", f"/election-votes/{vote_id}", headers=headers)

    def list_votes_flat(self, headers, params=None):
        return self._request("GET", "/election-votes", headers=headers,
                             params=params)

    def get_officer_role_flat(self, role_id, headers):
        return self._request("GET", f"/officer-roles/{role_id}", headers=headers)

    def list_officer_roles_flat(self, headers, params=None):
        return self._request("GET", "/officer-roles", headers=headers,
                             params=params)

    def get_minutes_flat(self, minutes_id, headers):
        return self._request("GET", f"/meeting-minutes/{minutes_id}",
                             headers=headers)

    def list_minutes_flat(self, headers, params=None):
        return self._request("GET", "/meeting-minutes", headers=headers,
                             params=params)

    def get_fundraiser_flat(self, fundraiser_id, headers):
        return self._request("GET", f"/fundraiser-requests/{fundraiser_id}",
                             headers=headers)

    def list_fundraisers_flat(self, headers, params=None):
        return self._request("GET", "/fundraiser-requests", headers=headers,
                             params=params)

    def get_ledger_entry_flat(self, entry_id, headers):
        return self._request("GET", f"/fund-ledger-entries/{entry_id}",
                             headers=headers)

    def list_ledger_entries_flat(self, headers, params=None):
        return self._request("GET", "/fund-ledger-entries", headers=headers,
                             params=params)

    def get_dues_payment_flat(self, payment_id, headers):
        return self._request("GET", f"/dues-payments/{payment_id}",
                             headers=headers)

    def list_dues_payments_flat(self, headers, params=None):
        return self._request("GET", "/dues-payments", headers=headers,
                             params=params)

    def get_probation_case_flat(self, case_id, headers):
        return self._request("GET", f"/probation-cases/{case_id}",
                             headers=headers)

    def list_probation_cases_flat(self, headers, params=None):
        return self._request("GET", "/probation-cases", headers=headers,
                             params=params)

    def get_athletics_block_flat(self, block_id, headers):
        return self._request("GET", f"/athletics-blocks/{block_id}",
                             headers=headers)

    def list_athletics_blocks_flat(self, headers, params=None):
        return self._request("GET", "/athletics-blocks", headers=headers,
                             params=params)


api_client = ApiClient()
