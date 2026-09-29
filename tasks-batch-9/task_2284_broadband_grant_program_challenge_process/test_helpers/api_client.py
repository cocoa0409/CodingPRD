"""API client: one method per endpoint defined in the PRD.

The whole grant surface is mounted under ``/broadband``; the logical-clock
setter is mounted outside it at ``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient

BROADBAND = "/broadband"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------- programs
    def create_program(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/programs/{program_id}", headers=headers
        )

    def list_programs(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/programs", headers=headers, params=params
        )

    def open_challenge_window(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/programs/{program_id}/open-challenge-window",
            payload if payload is not None else {},
            headers,
        )

    def close_challenge_window(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/programs/{program_id}/close-challenge-window",
            payload if payload is not None else {},
            headers,
        )

    def open_scoring(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/programs/{program_id}/open-scoring",
            payload if payload is not None else {},
            headers,
        )

    def close_allocation(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/programs/{program_id}/close-allocation",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ locations
    def create_location(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/locations/{location_id}", headers=headers
        )

    def list_locations(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/locations", headers=headers, params=params
        )

    def list_location_claims_of_location(self, location_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/locations/{location_id}/location-claims",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- challenges
    def create_challenge(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/challenges", payload, headers)

    def get_challenge(self, challenge_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/challenges/{challenge_id}", headers=headers
        )

    def list_challenges(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/challenges", headers=headers, params=params
        )

    def append_challenge_evidence(self, challenge_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/evidence",
            payload,
            headers,
        )

    def list_challenge_evidence(self, challenge_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/challenges/{challenge_id}/evidence",
            headers=headers,
            params=params,
        )

    def triage_challenge(self, challenge_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/triage",
            payload if payload is not None else {},
            headers,
        )

    def close_rebuttal(self, challenge_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/close-rebuttal",
            payload if payload is not None else {},
            headers,
        )

    def request_additional_evidence(self, challenge_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/request-additional-evidence",
            payload,
            headers,
        )

    def determine_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/determine",
            payload,
            headers,
        )

    def resubmit_challenge(self, challenge_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/challenges/{challenge_id}/resubmit",
            payload if payload is not None else {},
            headers,
        )

    # ---------------------------------------------------------- subgrantees
    def create_subgrantee(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/subgrantees", payload, headers)

    def get_subgrantee(self, subgrantee_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/subgrantees/{subgrantee_id}", headers=headers
        )

    def list_subgrantees(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/subgrantees", headers=headers, params=params
        )

    def begin_capability_review(self, subgrantee_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/subgrantees/{subgrantee_id}/begin-capability-review",
            payload if payload is not None else {},
            headers,
        )

    def record_capability_determination(self, subgrantee_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/subgrantees/{subgrantee_id}/record-capability-determination",
            payload,
            headers,
        )

    def submit_remediation(self, subgrantee_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/subgrantees/{subgrantee_id}/submit-remediation",
            payload,
            headers,
        )

    # --------------------------------------------------------- applications
    def create_application(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def return_application_for_cure(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/applications/{application_id}/return-for-cure",
            payload,
            headers,
        )

    def select_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/applications/{application_id}/select",
            payload if payload is not None else {},
            headers,
        )

    def list_application_location_claims(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/applications/{application_id}/location-claims",
            headers=headers,
            params=params,
        )

    def list_application_score_sheets(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/applications/{application_id}/score-sheets",
            headers=headers,
            params=params,
        )

    def list_application_awards(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/applications/{application_id}/awards",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------ location claims
    def create_location_claim(self, payload, headers):
        return self._request(
            "POST", f"{BROADBAND}/location-claims", payload, headers
        )

    # ---------------------------------------------------------- score sheets
    def create_score_sheet(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/score-sheets", payload, headers)

    # --------------------------------------------------------------- awards
    def create_award(self, payload, headers):
        return self._request("POST", f"{BROADBAND}/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request(
            "GET", f"{BROADBAND}/awards/{award_id}", headers=headers
        )

    def list_awards(self, headers, params=None):
        return self._request(
            "GET", f"{BROADBAND}/awards", headers=headers, params=params
        )

    def authorize_construction(self, award_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/authorize-construction",
            payload if payload is not None else {},
            headers,
        )

    def terminate_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"{BROADBAND}/awards/{award_id}/terminate", payload, headers
        )

    def list_ledger_entries(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/awards/{award_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------- environmental review
    def create_environmental_review(self, award_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/environmental-review",
            payload,
            headers,
        )

    def list_environmental_review(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/awards/{award_id}/environmental-review",
            headers=headers,
            params=params,
        )

    def record_environmental_determination(self, award_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/environmental-review/determination",
            payload,
            headers,
        )

    def clear_environmental_review(self, award_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/environmental-review/clear",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------------- milestones
    def create_milestone(self, award_id, payload, headers):
        return self._request(
            "POST", f"{BROADBAND}/awards/{award_id}/milestones", payload, headers
        )

    def list_milestones(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/awards/{award_id}/milestones",
            headers=headers,
            params=params,
        )

    def submit_milestone_evidence(self, award_id, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/milestones/{milestone_id}/submit-evidence",
            payload,
            headers,
        )

    def verify_milestone(self, award_id, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/milestones/{milestone_id}/verify",
            payload,
            headers,
        )

    def disburse_milestone(self, award_id, milestone_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/milestones/{milestone_id}/disburse",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------- compliance audits
    def create_compliance_audit(self, award_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits",
            payload,
            headers,
        )

    def list_compliance_audits(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"{BROADBAND}/awards/{award_id}/compliance-audits",
            headers=headers,
            params=params,
        )

    def record_audit_result(self, award_id, audit_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits/{audit_id}/record-result",
            payload,
            headers,
        )

    def issue_clawback_notice(self, award_id, audit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits/{audit_id}"
            f"/issue-clawback-notice",
            payload if payload is not None else {},
            headers,
        )

    def appeal_clawback(self, award_id, audit_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits/{audit_id}/appeal",
            payload,
            headers,
        )

    def resolve_clawback(self, award_id, audit_id, payload, headers):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits/{audit_id}"
            f"/resolve-clawback",
            payload,
            headers,
        )

    def verify_remediation(self, award_id, audit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BROADBAND}/awards/{award_id}/compliance-audits/{audit_id}"
            f"/verify-remediation",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
