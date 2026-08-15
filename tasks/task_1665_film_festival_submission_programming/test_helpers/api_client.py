"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving (logical clock / payment simulator) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/festival/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def simulate_payment(self, fee_payment_id, outcome, headers):
        return self._request(
            "POST", "/festival/_payments/simulate",
            {"fee_payment_id": fee_payment_id, "outcome": outcome}, headers,
        )

    # --- FestivalEdition ---
    def create_edition(self, payload, headers):
        return self._request("POST", "/festival/editions", payload, headers)

    def get_edition(self, edition_id, headers):
        return self._request("GET", f"/festival/editions/{edition_id}", headers=headers)

    def advance_edition(self, edition_id, to_status, headers):
        return self._request(
            "POST", f"/festival/editions/{edition_id}/advance",
            {"to_status": to_status}, headers,
        )

    def issue_invitations(self, edition_id, headers):
        return self._request(
            "POST", f"/festival/editions/{edition_id}/issue-invitations", {}, headers,
        )

    # --- CategoryConfig ---
    def create_category_config(self, payload, headers):
        return self._request("POST", "/festival/category-configs", payload, headers)

    def list_category_configs(self, edition_id, headers, params=None):
        return self._request(
            "GET", f"/festival/editions/{edition_id}/category-configs",
            headers=headers, params=params,
        )

    # --- Submitter ---
    def create_submitter(self, payload, headers):
        return self._request("POST", "/festival/submitters", payload, headers)

    def get_submitter(self, submitter_id, headers):
        return self._request("GET", f"/festival/submitters/{submitter_id}", headers=headers)

    # --- Programmer ---
    def create_programmer(self, payload, headers):
        return self._request("POST", "/festival/programmers", payload, headers)

    def get_programmer(self, programmer_id, headers):
        return self._request("GET", f"/festival/programmers/{programmer_id}", headers=headers)

    def update_programmer(self, programmer_id, payload, headers):
        return self._request(
            "PATCH", f"/festival/programmers/{programmer_id}", payload, headers,
        )

    # --- Submission ---
    def create_submission(self, payload, headers):
        return self._request("POST", "/festival/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/festival/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/festival/submissions", headers=headers, params=params)

    def update_submission(self, submission_id, payload, headers):
        return self._request(
            "PATCH", f"/festival/submissions/{submission_id}", payload, headers,
        )

    def checkout_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/festival/submissions/{submission_id}/checkout", {}, headers,
        )

    def withdraw_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/festival/submissions/{submission_id}/withdraw", {}, headers,
        )

    def decide_eligibility(self, submission_id, decision, headers, reason=None):
        payload = {"decision": decision}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/festival/submissions/{submission_id}/eligibility-decision",
            payload, headers,
        )

    def resubmit_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/festival/submissions/{submission_id}/resubmit", {}, headers,
        )

    # --- FeePayment ---
    def get_fee_payment(self, payment_id, headers):
        return self._request("GET", f"/festival/fee-payments/{payment_id}", headers=headers)

    def list_fee_payments(self, headers, params=None):
        return self._request("GET", "/festival/fee-payments", headers=headers, params=params)

    def refund_payment(self, payment_id, reason, headers):
        return self._request(
            "POST", f"/festival/fee-payments/{payment_id}/refund",
            {"reason": reason}, headers,
        )

    # --- ScreenerAssignment / Score ---
    def create_screener_assignment(self, payload, headers):
        return self._request("POST", "/festival/screener-assignments", payload, headers)

    def get_screener_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/festival/screener-assignments/{assignment_id}", headers=headers,
        )

    def list_screener_assignments(self, headers, params=None):
        return self._request(
            "GET", "/festival/screener-assignments", headers=headers, params=params,
        )

    def recuse_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/festival/screener-assignments/{assignment_id}/recuse", {}, headers,
        )

    def create_score(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/festival/screener-assignments/{assignment_id}/scores",
            payload, headers,
        )

    def list_assignment_scores(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/festival/screener-assignments/{assignment_id}/scores",
            headers=headers, params=params,
        )

    def get_score(self, score_id, headers):
        return self._request("GET", f"/festival/scores/{score_id}", headers=headers)

    def update_score(self, score_id, payload, headers):
        return self._request("PATCH", f"/festival/scores/{score_id}", payload, headers)

    # --- Slate / SlateEntry ---
    def create_slate(self, payload, headers):
        return self._request("POST", "/festival/slates", payload, headers)

    def get_slate(self, slate_id, headers):
        return self._request("GET", f"/festival/slates/{slate_id}", headers=headers)

    def list_slates(self, headers, params=None):
        return self._request("GET", "/festival/slates", headers=headers, params=params)

    def deliberate_slate(self, slate_id, headers):
        return self._request(
            "POST", f"/festival/slates/{slate_id}/deliberate", {}, headers,
        )

    def add_slate_entry(self, slate_id, payload, headers):
        return self._request(
            "POST", f"/festival/slates/{slate_id}/entries", payload, headers,
        )

    def list_entries_of_slate(self, slate_id, headers, params=None):
        return self._request(
            "GET", f"/festival/slates/{slate_id}/entries", headers=headers, params=params,
        )

    def delete_slate_entry(self, slate_id, entry_id, headers):
        return self._request(
            "DELETE", f"/festival/slates/{slate_id}/entries/{entry_id}", headers=headers,
        )

    def lock_slate(self, slate_id, headers):
        return self._request("POST", f"/festival/slates/{slate_id}/lock", {}, headers)

    def reopen_slate(self, slate_id, headers):
        return self._request("POST", f"/festival/slates/{slate_id}/reopen", {}, headers)

    def get_slate_entry(self, entry_id, headers):
        return self._request("GET", f"/festival/slate-entries/{entry_id}", headers=headers)

    def list_slate_entries(self, headers, params=None):
        return self._request("GET", "/festival/slate-entries", headers=headers, params=params)

    def respond_to_entry(self, entry_id, accept, headers):
        return self._request(
            "POST", f"/festival/slate-entries/{entry_id}/respond",
            {"accept": accept}, headers,
        )

    # --- Venue / ScreeningSlot ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/festival/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/festival/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/festival/venues", headers=headers, params=params)

    def create_screening_slot(self, payload, headers):
        return self._request("POST", "/festival/screening-slots", payload, headers)

    def get_screening_slot(self, slot_id, headers):
        return self._request("GET", f"/festival/screening-slots/{slot_id}", headers=headers)

    def list_screening_slots(self, headers, params=None):
        return self._request(
            "GET", "/festival/screening-slots", headers=headers, params=params,
        )

    def hold_slot(self, slot_id, slate_entry_id, headers):
        return self._request(
            "POST", f"/festival/screening-slots/{slot_id}/hold",
            {"slate_entry_id": slate_entry_id}, headers,
        )

    def confirm_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/festival/screening-slots/{slot_id}/confirm", {}, headers,
        )

    def release_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/festival/screening-slots/{slot_id}/release", {}, headers,
        )

    def cancel_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/festival/screening-slots/{slot_id}/cancel", {}, headers,
        )

    def mark_slot_played(self, slot_id, headers):
        return self._request(
            "POST", f"/festival/screening-slots/{slot_id}/mark-played", {}, headers,
        )

    # --- TravelPackage ---
    def get_travel_package(self, package_id, headers):
        return self._request(
            "GET", f"/festival/travel-packages/{package_id}", headers=headers,
        )

    def list_travel_packages(self, headers, params=None):
        return self._request(
            "GET", "/festival/travel-packages", headers=headers, params=params,
        )

    def submit_travel_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/submit", payload, headers,
        )

    def approve_travel_package(self, package_id, expected_edition_version, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/approve",
            {"expected_edition_version": expected_edition_version}, headers,
        )

    def request_travel_changes(self, package_id, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/request-changes", {}, headers,
        )

    def mark_travel_booked(self, package_id, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/mark-booked", {}, headers,
        )

    def cancel_travel_package(self, package_id, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/cancel", {}, headers,
        )

    def reconcile_travel_package(self, package_id, headers):
        return self._request(
            "POST", f"/festival/travel-packages/{package_id}/reconcile", {}, headers,
        )

    # --- ExhibitionAgreement ---
    def get_exhibition_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/festival/exhibition-agreements/{agreement_id}", headers=headers,
        )

    def list_exhibition_agreements(self, headers, params=None):
        return self._request(
            "GET", "/festival/exhibition-agreements", headers=headers, params=params,
        )

    def issue_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/festival/exhibition-agreements/{agreement_id}/issue",
            payload, headers,
        )

    def sign_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/festival/exhibition-agreements/{agreement_id}/sign", {}, headers,
        )

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/festival/exhibition-agreements/{agreement_id}/amend",
            payload, headers,
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/festival/exhibition-agreements/{agreement_id}/terminate",
            {}, headers,
        )

    # --- Juror / Award / JuryVote ---
    def create_juror(self, payload, headers):
        return self._request("POST", "/festival/jurors", payload, headers)

    def get_juror(self, juror_id, headers):
        return self._request("GET", f"/festival/jurors/{juror_id}", headers=headers)

    def list_jurors(self, headers, params=None):
        return self._request("GET", "/festival/jurors", headers=headers, params=params)

    def list_juror_ballots(self, juror_id, headers, params=None):
        return self._request(
            "GET", f"/festival/jurors/{juror_id}/ballots", headers=headers, params=params,
        )

    def create_award(self, payload, headers):
        return self._request("POST", "/festival/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/festival/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/festival/awards", headers=headers, params=params)

    def open_voting(self, award_id, headers):
        return self._request(
            "POST", f"/festival/awards/{award_id}/open-voting", {}, headers,
        )

    def cast_ballot(self, award_id, ranked_submission_ids, headers):
        return self._request(
            "POST", f"/festival/awards/{award_id}/ballots",
            {"ranked_submission_ids": ranked_submission_ids}, headers,
        )

    def list_award_ballots(self, award_id, headers, params=None):
        return self._request(
            "GET", f"/festival/awards/{award_id}/ballots", headers=headers, params=params,
        )

    def get_award_standings(self, award_id, headers):
        return self._request(
            "GET", f"/festival/awards/{award_id}/standings", headers=headers,
        )

    def tally_award(self, award_id, headers):
        return self._request("POST", f"/festival/awards/{award_id}/tally", {}, headers)

    def announce_award(self, award_id, headers):
        return self._request("POST", f"/festival/awards/{award_id}/announce", {}, headers)

    def disburse_award(self, award_id, headers):
        return self._request("POST", f"/festival/awards/{award_id}/disburse", {}, headers)


api_client = ApiClient()
