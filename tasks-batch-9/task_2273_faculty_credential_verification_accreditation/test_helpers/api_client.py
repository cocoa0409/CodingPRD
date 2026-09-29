"""Typed wrapper over every endpoint declared in PRD section 4."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per PRD section 4 row, in the order the table declares them."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers = None):
        return self.post("/_clock/set_current_utc", json=payload, headers=headers)

    def get_clock(self, headers: Headers = None):
        return self.get("/_clock", headers=headers)

    # ------------------------------------------------------------------
    # Disciplines
    # ------------------------------------------------------------------
    def create_discipline(self, payload: Payload, headers: Headers = None):
        return self.post("/disciplines", json=payload, headers=headers)

    def update_discipline(
        self, discipline_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(f"/disciplines/{discipline_id}", json=payload, headers=headers)

    def get_discipline(self, discipline_id: str, headers: Headers = None):
        return self.get(f"/disciplines/{discipline_id}", headers=headers)

    def list_disciplines(self, headers: Headers = None, params: Params = None):
        return self.get("/disciplines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload: Payload, headers: Headers = None):
        return self.post("/programs", json=payload, headers=headers)

    def get_program(self, program_id: str, headers: Headers = None):
        return self.get(f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Headers = None, params: Params = None):
        return self.get("/programs", headers=headers, params=params)

    def get_program_adequacy(
        self, program_id: str, headers: Headers = None, params: Params = None
    ):
        return self.get(
            f"/programs/{program_id}/adequacy", headers=headers, params=params
        )

    def submit_launch_review(
        self, program_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/programs/{program_id}/launch-review", json=payload, headers=headers
        )

    def decide_launch(self, program_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/programs/{program_id}/launch-decision", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Terms
    # ------------------------------------------------------------------
    def create_term(self, payload: Payload, headers: Headers = None):
        return self.post("/terms", json=payload, headers=headers)

    def get_term(self, term_id: str, headers: Headers = None):
        return self.get(f"/terms/{term_id}", headers=headers)

    def list_terms(self, headers: Headers = None, params: Params = None):
        return self.get("/terms", headers=headers, params=params)

    def set_term_status(self, term_id: str, payload: Payload, headers: Headers = None):
        return self.post(f"/terms/{term_id}/status", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Faculty members
    # ------------------------------------------------------------------
    def create_faculty_member(self, payload: Payload, headers: Headers = None):
        return self.post("/faculty-members", json=payload, headers=headers)

    def update_faculty_member(
        self, faculty_member_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/faculty-members/{faculty_member_id}", json=payload, headers=headers
        )

    def get_faculty_member(self, faculty_member_id: str, headers: Headers = None):
        return self.get(f"/faculty-members/{faculty_member_id}", headers=headers)

    def list_faculty_members(self, headers: Headers = None, params: Params = None):
        return self.get("/faculty-members", headers=headers, params=params)

    def separate_faculty_member(
        self, faculty_member_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/faculty-members/{faculty_member_id}/separation",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Credential records
    # ------------------------------------------------------------------
    def create_credential_record(self, payload: Payload, headers: Headers = None):
        return self.post("/credential-records", json=payload, headers=headers)

    def get_credential_record(self, record_id: str, headers: Headers = None):
        return self.get(f"/credential-records/{record_id}", headers=headers)

    def list_credential_records(self, headers: Headers = None, params: Params = None):
        return self.get("/credential-records", headers=headers, params=params)

    def list_faculty_credential_records(
        self, faculty_member_id: str, headers: Headers = None, params: Params = None
    ):
        return self.get(
            f"/faculty-members/{faculty_member_id}/credential-records",
            headers=headers,
            params=params,
        )

    def set_transcript_status(
        self, record_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/credential-records/{record_id}/transcript", json=payload, headers=headers
        )

    def decide_verification(
        self, record_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/credential-records/{record_id}/verification",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Credential evaluations
    # ------------------------------------------------------------------
    def create_credential_evaluation(self, payload: Payload, headers: Headers = None):
        return self.post("/credential-evaluations", json=payload, headers=headers)

    def get_credential_evaluation(self, evaluation_id: str, headers: Headers = None):
        return self.get(f"/credential-evaluations/{evaluation_id}", headers=headers)

    def list_credential_evaluations(
        self, headers: Headers = None, params: Params = None
    ):
        return self.get("/credential-evaluations", headers=headers, params=params)

    def set_evaluation_status(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/credential-evaluations/{evaluation_id}/status",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Course sections
    # ------------------------------------------------------------------
    def create_course_section(self, payload: Payload, headers: Headers = None):
        return self.post("/course-sections", json=payload, headers=headers)

    def get_course_section(self, section_id: str, headers: Headers = None):
        return self.get(f"/course-sections/{section_id}", headers=headers)

    def list_course_sections(self, headers: Headers = None, params: Params = None):
        return self.get("/course-sections", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Course assignments
    # ------------------------------------------------------------------
    def create_course_assignment(self, payload: Payload, headers: Headers = None):
        return self.post("/course-assignments", json=payload, headers=headers)

    def get_course_assignment(self, assignment_id: str, headers: Headers = None):
        return self.get(f"/course-assignments/{assignment_id}", headers=headers)

    def list_course_assignments(self, headers: Headers = None, params: Params = None):
        return self.get("/course-assignments", headers=headers, params=params)

    def list_section_assignments(
        self, section_id: str, headers: Headers = None, params: Params = None
    ):
        return self.get(
            f"/course-sections/{section_id}/course-assignments",
            headers=headers,
            params=params,
        )

    def open_remediation(
        self, assignment_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/course-assignments/{assignment_id}/remediation",
            json=payload,
            headers=headers,
        )

    def reverify_assignment(
        self, assignment_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/course-assignments/{assignment_id}/reverification",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def withdraw_assignment(
        self, assignment_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/course-assignments/{assignment_id}/withdrawal",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Tested-experience justifications
    # ------------------------------------------------------------------
    def create_justification(self, payload: Payload, headers: Headers = None):
        return self.post(
            "/tested-experience-justifications", json=payload, headers=headers
        )

    def update_justification(
        self, justification_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/tested-experience-justifications/{justification_id}",
            json=payload,
            headers=headers,
        )

    def get_justification(self, justification_id: str, headers: Headers = None):
        return self.get(
            f"/tested-experience-justifications/{justification_id}", headers=headers
        )

    def list_justifications(self, headers: Headers = None, params: Params = None):
        return self.get(
            "/tested-experience-justifications", headers=headers, params=params
        )

    def set_justification_status(
        self, justification_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/tested-experience-justifications/{justification_id}/status",
            json=payload,
            headers=headers,
        )

    def review_justification(
        self, justification_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/tested-experience-justifications/{justification_id}/review",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def decide_justification(
        self, justification_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/tested-experience-justifications/{justification_id}/decision",
            json=payload,
            headers=headers,
        )

    def revise_justification(
        self, justification_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/tested-experience-justifications/{justification_id}/revision",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Faculty rosters
    # ------------------------------------------------------------------
    def create_roster(self, payload: Payload, headers: Headers = None):
        return self.post("/faculty-rosters", json=payload, headers=headers)

    def get_roster(self, roster_id: str, headers: Headers = None):
        return self.get(f"/faculty-rosters/{roster_id}", headers=headers)

    def list_rosters(self, headers: Headers = None, params: Params = None):
        return self.get("/faculty-rosters", headers=headers, params=params)

    def list_roster_entries(
        self, roster_id: str, headers: Headers = None, params: Params = None
    ):
        return self.get(
            f"/faculty-rosters/{roster_id}/entries", headers=headers, params=params
        )

    def generate_roster(
        self, roster_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/faculty-rosters/{roster_id}/generate",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def certify_roster(
        self, roster_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/faculty-rosters/{roster_id}/certification",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Faculty contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload: Payload, headers: Headers = None):
        return self.post("/faculty-contracts", json=payload, headers=headers)

    def get_contract(self, contract_id: str, headers: Headers = None):
        return self.get(f"/faculty-contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers: Headers = None, params: Params = None):
        return self.get("/faculty-contracts", headers=headers, params=params)

    def countersign_contract(
        self, contract_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/faculty-contracts/{contract_id}/countersignature",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def void_contract(
        self, contract_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self.post(
            f"/faculty-contracts/{contract_id}/void",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Professional-development records
    # ------------------------------------------------------------------
    def create_pd_record(self, payload: Payload, headers: Headers = None):
        return self.post("/pd-records", json=payload, headers=headers)

    def get_pd_record(self, pd_record_id: str, headers: Headers = None):
        return self.get(f"/pd-records/{pd_record_id}", headers=headers)

    def list_pd_records(self, headers: Headers = None, params: Params = None):
        return self.get("/pd-records", headers=headers, params=params)

    def set_pd_record_status(
        self, pd_record_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/pd-records/{pd_record_id}/status", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Accreditor reviews
    # ------------------------------------------------------------------
    def create_review(self, payload: Payload, headers: Headers = None):
        return self.post("/accreditor-reviews", json=payload, headers=headers)

    def get_review(self, review_id: str, headers: Headers = None):
        return self.get(f"/accreditor-reviews/{review_id}", headers=headers)

    def list_reviews(self, headers: Headers = None, params: Params = None):
        return self.get("/accreditor-reviews", headers=headers, params=params)

    def set_review_status(
        self, review_id: str, payload: Payload, headers: Headers = None
    ):
        return self.post(
            f"/accreditor-reviews/{review_id}/status", json=payload, headers=headers
        )

    def issue_findings(self, review_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/accreditor-reviews/{review_id}/findings", json=payload, headers=headers
        )

    def submit_response(self, review_id: str, payload: Payload, headers: Headers = None):
        return self.post(
            f"/accreditor-reviews/{review_id}/response", json=payload, headers=headers
        )


api_client = ApiClient()
