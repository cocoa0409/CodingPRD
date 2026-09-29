"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/vote-by-mail"


class ApiClient(GenericApiClient):
    # --- Logical clock ---------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Elections ------------------------------------------------------------
    def create_election(self, payload, headers):
        return self._request("POST", f"{BASE}/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"{BASE}/elections/{election_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", f"{BASE}/elections", headers=headers, params=params)

    def advance_posture(self, election_id, payload, headers):
        return self._request("POST", f"{BASE}/elections/{election_id}/posture-advance",
                             payload, headers)

    def get_accountability(self, election_id, headers):
        return self._request("GET", f"{BASE}/elections/{election_id}/accountability",
                             headers=headers)

    def run_canvass_sweep(self, election_id, payload, headers):
        return self._request("POST", f"{BASE}/elections/{election_id}/canvass-sweep",
                             payload, headers)

    def create_separation_run(self, election_id, payload, headers):
        return self._request("POST", f"{BASE}/elections/{election_id}/separation-runs",
                             payload, headers)

    def create_observer_session(self, election_id, payload, headers):
        return self._request("POST", f"{BASE}/elections/{election_id}/observer-sessions",
                             payload, headers)

    # --- Voters ---------------------------------------------------------------
    def create_voter(self, payload, headers):
        return self._request("POST", f"{BASE}/voters", payload, headers)

    def get_voter(self, voter_id, headers):
        return self._request("GET", f"{BASE}/voters/{voter_id}", headers=headers)

    def list_voters(self, headers, params=None):
        return self._request("GET", f"{BASE}/voters", headers=headers, params=params)

    def create_enrollment(self, voter_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/voters/{voter_id}/permanent-absentee-enrollments",
            payload, headers)

    # --- Permanent absentee enrollments ---------------------------------------
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{BASE}/permanent-absentee-enrollments/{enrollment_id}",
                             headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{BASE}/permanent-absentee-enrollments",
                             headers=headers, params=params)

    def reinstate_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/permanent-absentee-enrollments/{enrollment_id}/reinstate",
            payload, headers)

    def delete_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("DELETE", f"{BASE}/permanent-absentee-enrollments/{enrollment_id}",
                             payload, headers)

    # --- Reviewers ------------------------------------------------------------
    def create_reviewer(self, payload, headers):
        return self._request("POST", f"{BASE}/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"{BASE}/reviewers/{reviewer_id}", headers=headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", f"{BASE}/reviewers", headers=headers, params=params)

    def create_training_completion(self, reviewer_id, payload, headers):
        return self._request("POST", f"{BASE}/reviewers/{reviewer_id}/training-completions",
                             payload, headers)

    # --- Ballot requests ------------------------------------------------------
    def create_ballot_request(self, payload, headers):
        return self._request("POST", f"{BASE}/ballot-requests", payload, headers)

    def get_ballot_request(self, request_id, headers):
        return self._request("GET", f"{BASE}/ballot-requests/{request_id}", headers=headers)

    def list_ballot_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/ballot-requests", headers=headers, params=params)

    def approve_ballot_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{BASE}/ballot-requests/{request_id}/approve",
                             payload or {}, headers)

    def reject_ballot_request(self, request_id, payload, headers):
        return self._request("POST", f"{BASE}/ballot-requests/{request_id}/reject",
                             payload, headers)

    def address_recheck(self, request_id, headers, payload=None):
        return self._request("POST", f"{BASE}/ballot-requests/{request_id}/address-recheck",
                             payload or {}, headers)

    # --- Address verifications -------------------------------------------------
    def get_address_verification(self, verification_id, headers):
        return self._request("GET", f"{BASE}/address-verifications/{verification_id}",
                             headers=headers)

    def list_address_verifications(self, headers, params=None):
        return self._request("GET", f"{BASE}/address-verifications", headers=headers,
                             params=params)

    def submit_address_result(self, verification_id, payload, headers):
        return self._request("POST", f"{BASE}/address-verifications/{verification_id}/results",
                             payload, headers)

    # --- Mailing batches -------------------------------------------------------
    def create_mailing_batch(self, payload, headers):
        return self._request("POST", f"{BASE}/mailing-batches", payload, headers)

    def get_mailing_batch(self, batch_id, headers):
        return self._request("GET", f"{BASE}/mailing-batches/{batch_id}", headers=headers)

    def list_mailing_batches(self, headers, params=None):
        return self._request("GET", f"{BASE}/mailing-batches", headers=headers, params=params)

    def add_packet(self, batch_id, payload, headers):
        return self._request("POST", f"{BASE}/mailing-batches/{batch_id}/packets",
                             payload, headers)

    def seal_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"{BASE}/mailing-batches/{batch_id}/seal",
                             payload or {}, headers)

    def dispatch_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"{BASE}/mailing-batches/{batch_id}/dispatch",
                             payload or {}, headers)

    def cancel_batch(self, batch_id, payload, headers):
        return self._request("POST", f"{BASE}/mailing-batches/{batch_id}/cancel",
                             payload, headers)

    # --- Ballot packets --------------------------------------------------------
    def get_ballot_packet(self, packet_id, headers):
        return self._request("GET", f"{BASE}/ballot-packets/{packet_id}", headers=headers)

    def list_ballot_packets(self, headers, params=None):
        return self._request("GET", f"{BASE}/ballot-packets", headers=headers, params=params)

    def mark_packet_undeliverable(self, packet_id, payload, headers):
        return self._request("POST", f"{BASE}/ballot-packets/{packet_id}/undeliverable",
                             payload, headers)

    # --- Return envelopes ------------------------------------------------------
    def create_return_envelope(self, payload, headers):
        return self._request("POST", f"{BASE}/return-envelopes", payload, headers)

    def get_return_envelope(self, envelope_id, headers):
        return self._request("GET", f"{BASE}/return-envelopes/{envelope_id}", headers=headers)

    def list_return_envelopes(self, headers, params=None):
        return self._request("GET", f"{BASE}/return-envelopes", headers=headers, params=params)

    def open_signature_review(self, envelope_id, headers, payload=None):
        return self._request("POST", f"{BASE}/return-envelopes/{envelope_id}/signature-reviews",
                             payload or {}, headers)

    def create_cure_notice(self, envelope_id, headers, payload=None):
        return self._request("POST", f"{BASE}/return-envelopes/{envelope_id}/cure-notices",
                             payload or {}, headers)

    def create_remake(self, envelope_id, payload, headers):
        return self._request("POST", f"{BASE}/return-envelopes/{envelope_id}/remakes",
                             payload, headers)

    def file_challenge(self, envelope_id, payload, headers):
        return self._request("POST", f"{BASE}/return-envelopes/{envelope_id}/challenges",
                             payload, headers)

    def adjudicate_challenge(self, envelope_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/return-envelopes/{envelope_id}/challenge-adjudication",
            payload, headers)

    def count_envelope(self, envelope_id, headers, payload=None):
        return self._request("POST", f"{BASE}/return-envelopes/{envelope_id}/count",
                             payload or {}, headers)

    # --- Signature reviews -----------------------------------------------------
    def get_signature_review(self, review_id, headers):
        return self._request("GET", f"{BASE}/signature-reviews/{review_id}", headers=headers)

    def list_signature_reviews(self, headers, params=None):
        return self._request("GET", f"{BASE}/signature-reviews", headers=headers, params=params)

    def submit_signature_decision(self, review_id, payload, headers):
        return self._request("POST", f"{BASE}/signature-reviews/{review_id}/decision",
                             payload, headers)

    # --- Cure notices and evidence ---------------------------------------------
    def get_cure_notice(self, notice_id, headers):
        return self._request("GET", f"{BASE}/cure-notices/{notice_id}", headers=headers)

    def list_cure_notices(self, headers, params=None):
        return self._request("GET", f"{BASE}/cure-notices", headers=headers, params=params)

    def submit_cure_evidence(self, notice_id, payload, headers):
        return self._request("POST", f"{BASE}/cure-notices/{notice_id}/evidence",
                             payload, headers)

    def adjudicate_cure_notice(self, notice_id, payload, headers):
        return self._request("POST", f"{BASE}/cure-notices/{notice_id}/adjudicate",
                             payload, headers)

    def get_cure_evidence(self, evidence_id, headers):
        return self._request("GET", f"{BASE}/cure-evidence/{evidence_id}", headers=headers)

    def list_cure_evidence(self, headers, params=None):
        return self._request("GET", f"{BASE}/cure-evidence", headers=headers, params=params)

    # --- Remake records --------------------------------------------------------
    def get_remake_record(self, remake_id, headers):
        return self._request("GET", f"{BASE}/remake-records/{remake_id}", headers=headers)

    def list_remake_records(self, headers, params=None):
        return self._request("GET", f"{BASE}/remake-records", headers=headers, params=params)

    def complete_remake(self, remake_id, payload, headers):
        return self._request("POST", f"{BASE}/remake-records/{remake_id}/complete",
                             payload, headers)

    def void_remake(self, remake_id, payload, headers):
        return self._request("POST", f"{BASE}/remake-records/{remake_id}/void",
                             payload, headers)

    # --- Observer sessions -----------------------------------------------------
    def get_observer_session(self, session_id, headers):
        return self._request("GET", f"{BASE}/observer-sessions/{session_id}", headers=headers)

    def list_observer_sessions(self, headers, params=None):
        return self._request("GET", f"{BASE}/observer-sessions", headers=headers, params=params)

    def check_in_observer(self, session_id, headers, payload=None):
        return self._request("POST", f"{BASE}/observer-sessions/{session_id}/check-in",
                             payload or {}, headers)

    def revoke_observer_session(self, session_id, payload, headers):
        return self._request("POST", f"{BASE}/observer-sessions/{session_id}/revoke",
                             payload, headers)

    # --- Transparency log ------------------------------------------------------
    def get_transparency_entry(self, entry_id, headers):
        return self._request("GET", f"{BASE}/transparency-log/{entry_id}", headers=headers)

    def list_transparency_log(self, headers, params=None):
        return self._request("GET", f"{BASE}/transparency-log", headers=headers, params=params)


api_client = ApiClient()
