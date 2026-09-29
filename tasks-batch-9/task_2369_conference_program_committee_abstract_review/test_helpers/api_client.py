"""API client: one method per endpoint declared by the PRD endpoint table."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Conference ───────────────────────────────────────────────────────
    def create_conference(self, payload, headers):
        return self._request("POST", "/conferences", payload, headers)

    def list_conferences(self, headers, params=None):
        return self._request("GET", "/conferences", headers=headers, params=params)

    def get_conference(self, conference_id, headers):
        return self._request("GET", f"/conferences/{conference_id}", headers=headers)

    def get_capacity_summary(self, conference_id, headers):
        return self._request(
            "GET", f"/conferences/{conference_id}/capacity-summary", headers=headers
        )

    def transition_conference(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/conferences/{conference_id}/status-transitions", payload, headers
        )

    # ── SubmissionCategory ───────────────────────────────────────────────
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    # ── Author ───────────────────────────────────────────────────────────
    def create_author(self, payload, headers):
        return self._request("POST", "/authors", payload, headers)

    def list_authors(self, headers, params=None):
        return self._request("GET", "/authors", headers=headers, params=params)

    def get_author(self, author_id, headers):
        return self._request("GET", f"/authors/{author_id}", headers=headers)

    def register_author(self, author_id, payload, headers):
        return self._request(
            "POST", f"/authors/{author_id}/registration", payload, headers
        )

    # ── Abstract ─────────────────────────────────────────────────────────
    def create_abstract(self, payload, headers):
        return self._request("POST", "/abstracts", payload, headers)

    def list_abstracts(self, headers, params=None):
        return self._request("GET", "/abstracts", headers=headers, params=params)

    def get_abstract(self, abstract_id, headers):
        return self._request("GET", f"/abstracts/{abstract_id}", headers=headers)

    def revise_abstract(self, abstract_id, payload, headers):
        return self._request(
            "POST", f"/abstracts/{abstract_id}/revisions", payload, headers
        )

    def transition_abstract(self, abstract_id, payload, headers):
        return self._request(
            "POST", f"/abstracts/{abstract_id}/status-transitions", payload, headers
        )

    def decide_abstract(self, abstract_id, payload, headers):
        return self._request(
            "POST", f"/abstracts/{abstract_id}/decision", payload, headers
        )

    def create_review_assignment(self, abstract_id, payload, headers):
        return self._request(
            "POST", f"/abstracts/{abstract_id}/review-assignments", payload, headers
        )

    def press_action(self, abstract_id, payload, headers):
        return self._request(
            "POST", f"/abstracts/{abstract_id}/press-actions", payload, headers
        )

    # ── CommitteeMember ──────────────────────────────────────────────────
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/committee-members", payload, headers)

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/committee-members", headers=headers, params=params)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/committee-members/{member_id}", headers=headers)

    def update_committee_member(self, member_id, payload, headers):
        return self._request(
            "PATCH", f"/committee-members/{member_id}", payload, headers
        )

    def transition_committee_member(self, member_id, payload, headers):
        return self._request(
            "POST",
            f"/committee-members/{member_id}/status-transitions",
            payload,
            headers,
        )

    # ── ConflictDeclaration ──────────────────────────────────────────────
    def create_conflict_declaration(self, payload, headers):
        return self._request("POST", "/conflict-declarations", payload, headers)

    def list_conflict_declarations(self, headers, params=None):
        return self._request(
            "GET", "/conflict-declarations", headers=headers, params=params
        )

    def get_conflict_declaration(self, declaration_id, headers):
        return self._request(
            "GET", f"/conflict-declarations/{declaration_id}", headers=headers
        )

    # ── Review ───────────────────────────────────────────────────────────
    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def submit_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/reviews/{review_id}/submission", payload, headers
        )

    def decline_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/decline", payload, headers)

    # ── DiscrepancyCase ──────────────────────────────────────────────────
    def list_discrepancy_cases(self, headers, params=None):
        return self._request("GET", "/discrepancy-cases", headers=headers, params=params)

    def get_discrepancy_case(self, case_id, headers):
        return self._request("GET", f"/discrepancy-cases/{case_id}", headers=headers)

    def assign_arbiter(self, case_id, payload, headers):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/arbiter", payload, headers
        )

    def resolve_discrepancy_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/resolution", payload, headers
        )

    # ── Session ──────────────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def transition_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/status-transitions", payload, headers
        )

    def create_session_slot(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/slots", payload, headers
        )

    # ── SessionSlot ──────────────────────────────────────────────────────
    def list_session_slots(self, headers, params=None):
        return self._request("GET", "/session-slots", headers=headers, params=params)

    def get_session_slot(self, slot_id, headers):
        return self._request("GET", f"/session-slots/{slot_id}", headers=headers)

    def transition_session_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/session-slots/{slot_id}/status-transitions", payload, headers
        )

    # ── CmeAccreditation ─────────────────────────────────────────────────
    def create_accreditation(self, payload, headers):
        return self._request("POST", "/accreditations", payload, headers)

    def list_accreditations(self, headers, params=None):
        return self._request("GET", "/accreditations", headers=headers, params=params)

    def get_accreditation(self, accreditation_id, headers):
        return self._request(
            "GET", f"/accreditations/{accreditation_id}", headers=headers
        )

    def validate_accreditation(self, accreditation_id, payload, headers):
        return self._request(
            "POST", f"/accreditations/{accreditation_id}/validation", payload, headers
        )

    # ── DisclosureStatement ──────────────────────────────────────────────
    def create_disclosure_statement(self, payload, headers):
        return self._request("POST", "/disclosure-statements", payload, headers)

    def list_disclosure_statements(self, headers, params=None):
        return self._request(
            "GET", "/disclosure-statements", headers=headers, params=params
        )

    def get_disclosure_statement(self, disclosure_id, headers):
        return self._request(
            "GET", f"/disclosure-statements/{disclosure_id}", headers=headers
        )

    def adjudicate_disclosure_statement(self, disclosure_id, payload, headers):
        return self._request(
            "POST",
            f"/disclosure-statements/{disclosure_id}/adjudication",
            payload,
            headers,
        )

    # ── ProgramChangeRequest ─────────────────────────────────────────────
    def create_program_change_request(self, payload, headers):
        return self._request("POST", "/program-change-requests", payload, headers)

    def list_program_change_requests(self, headers, params=None):
        return self._request(
            "GET", "/program-change-requests", headers=headers, params=params
        )

    def get_program_change_request(self, request_id, headers):
        return self._request(
            "GET", f"/program-change-requests/{request_id}", headers=headers
        )

    def adjudicate_program_change_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/program-change-requests/{request_id}/adjudication",
            payload,
            headers,
        )


api_client = ApiClient()
