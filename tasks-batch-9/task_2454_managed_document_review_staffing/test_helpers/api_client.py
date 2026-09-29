"""One method per endpoint of the managed document review staffing API.

Every path is absolute and every collection is a top-level peer; there is no
shared URL prefix. List helpers accept ``limit``, ``offset`` and the filters
their endpoint documents, and drop any argument left as ``None`` so the
server's own defaults are exercised.
"""

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def _query(**kwargs: Any) -> dict:
    """Drop unset query arguments so server defaults are exercised."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the review staffing API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(
        self, to_iso8601: str, headers: Optional[dict] = None
    ) -> requests.Response:
        """POST /_clock/set_current_utc — requires no authentication headers."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers if headers is not None else {"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload: dict, headers: dict) -> requests.Response:
        """POST /clients"""
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: dict) -> requests.Response:
        """GET /clients/{id}"""
        return self._request("GET", f"/clients/{client_id}", None, headers)

    # ------------------------------------------------------------------
    # Matters
    # ------------------------------------------------------------------
    def create_matter(self, payload: dict, headers: dict) -> requests.Response:
        """POST /matters"""
        return self._request("POST", "/matters", payload, headers)

    def get_matter(self, matter_id: str, headers: dict) -> requests.Response:
        """GET /matters/{id}"""
        return self._request("GET", f"/matters/{matter_id}", None, headers)

    def list_matters(
        self,
        headers: dict,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /matters"""
        return self._request(
            "GET",
            "/matters",
            None,
            headers,
            _query(
                client_id=client_id, status=status, limit=limit, offset=offset
            ),
        )

    def set_matter_suspension(
        self, matter_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /matters/{id}/suspension"""
        return self._request(
            "POST", f"/matters/{matter_id}/suspension", payload, headers
        )

    def close_matter(
        self, matter_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /matters/{id}/close"""
        return self._request(
            "POST", f"/matters/{matter_id}/close", payload or {}, headers
        )

    def get_spend_projection(
        self, matter_id: str, headers: dict, basis: Optional[str] = None
    ) -> requests.Response:
        """GET /matters/{id}/spend-projection"""
        return self._request(
            "GET",
            f"/matters/{matter_id}/spend-projection",
            None,
            headers,
            _query(basis=basis),
        )

    def list_matter_budget_ledger(
        self,
        matter_id: str,
        headers: dict,
        entry_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /matters/{id}/budget-ledger"""
        return self._request(
            "GET",
            f"/matters/{matter_id}/budget-ledger",
            None,
            headers,
            _query(entry_type=entry_type, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Review protocols
    # ------------------------------------------------------------------
    def create_protocol(
        self, matter_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /matters/{id}/protocols"""
        return self._request(
            "POST", f"/matters/{matter_id}/protocols", payload, headers
        )

    def get_protocol(self, protocol_id: str, headers: dict) -> requests.Response:
        """GET /protocols/{id}"""
        return self._request("GET", f"/protocols/{protocol_id}", None, headers)

    def list_protocols(
        self,
        headers: dict,
        matter_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /protocols"""
        return self._request(
            "GET",
            "/protocols",
            None,
            headers,
            _query(
                matter_id=matter_id, status=status, limit=limit, offset=offset
            ),
        )

    def submit_protocol(
        self, protocol_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /protocols/{id}/submit"""
        return self._request(
            "POST", f"/protocols/{protocol_id}/submit", payload or {}, headers
        )

    def decide_protocol(
        self, protocol_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /protocols/{id}/client-decision"""
        return self._request(
            "POST", f"/protocols/{protocol_id}/client-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Reviewers
    # ------------------------------------------------------------------
    def create_reviewer(self, payload: dict, headers: dict) -> requests.Response:
        """POST /reviewers"""
        return self._request("POST", "/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id: str, headers: dict) -> requests.Response:
        """GET /reviewers/{id}"""
        return self._request("GET", f"/reviewers/{reviewer_id}", None, headers)

    def list_reviewers(
        self,
        headers: dict,
        engagement_status: Optional[str] = None,
        credential_status: Optional[str] = None,
        tier: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /reviewers"""
        return self._request(
            "GET",
            "/reviewers",
            None,
            headers,
            _query(
                engagement_status=engagement_status,
                credential_status=credential_status,
                tier=tier,
                limit=limit,
                offset=offset,
            ),
        )

    def set_credential_status(
        self, reviewer_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /reviewers/{id}/credential-status"""
        return self._request(
            "POST", f"/reviewers/{reviewer_id}/credential-status", payload, headers
        )

    def list_scorecard_events(
        self,
        reviewer_id: str,
        headers: dict,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /reviewers/{id}/scorecard-events"""
        return self._request(
            "GET",
            f"/reviewers/{reviewer_id}/scorecard-events",
            None,
            headers,
            _query(event_type=event_type, limit=limit, offset=offset),
        )

    def get_scorecard(
        self, reviewer_id: str, headers: dict, weighting: Optional[str] = None
    ) -> requests.Response:
        """GET /reviewers/{id}/scorecard"""
        return self._request(
            "GET",
            f"/reviewers/{reviewer_id}/scorecard",
            None,
            headers,
            _query(weighting=weighting),
        )

    # ------------------------------------------------------------------
    # Conflicts screenings
    # ------------------------------------------------------------------
    def create_screening(self, payload: dict, headers: dict) -> requests.Response:
        """POST /conflicts-screenings"""
        return self._request("POST", "/conflicts-screenings", payload, headers)

    def get_screening(self, screening_id: str, headers: dict) -> requests.Response:
        """GET /conflicts-screenings/{id}"""
        return self._request(
            "GET", f"/conflicts-screenings/{screening_id}", None, headers
        )

    def list_screenings(
        self,
        headers: dict,
        reviewer_id: Optional[str] = None,
        matter_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /conflicts-screenings"""
        return self._request(
            "GET",
            "/conflicts-screenings",
            None,
            headers,
            _query(
                reviewer_id=reviewer_id,
                matter_id=matter_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def decide_screening(
        self, screening_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /conflicts-screenings/{id}/decision"""
        return self._request(
            "POST",
            f"/conflicts-screenings/{screening_id}/decision",
            payload,
            headers,
        )

    def rule_screening_waiver(
        self, screening_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /conflicts-screenings/{id}/waiver"""
        return self._request(
            "POST", f"/conflicts-screenings/{screening_id}/waiver", payload, headers
        )

    # ------------------------------------------------------------------
    # Confidentiality agreements
    # ------------------------------------------------------------------
    def create_agreement(self, payload: dict, headers: dict) -> requests.Response:
        """POST /confidentiality-agreements"""
        return self._request(
            "POST", "/confidentiality-agreements", payload, headers
        )

    def get_agreement(self, agreement_id: str, headers: dict) -> requests.Response:
        """GET /confidentiality-agreements/{id}"""
        return self._request(
            "GET", f"/confidentiality-agreements/{agreement_id}", None, headers
        )

    def list_agreements(
        self,
        headers: dict,
        reviewer_id: Optional[str] = None,
        matter_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /confidentiality-agreements"""
        return self._request(
            "GET",
            "/confidentiality-agreements",
            None,
            headers,
            _query(
                reviewer_id=reviewer_id,
                matter_id=matter_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def execute_agreement(
        self, agreement_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /confidentiality-agreements/{id}/execute"""
        return self._request(
            "POST",
            f"/confidentiality-agreements/{agreement_id}/execute",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Secure environment sessions
    # ------------------------------------------------------------------
    def create_session(self, payload: dict, headers: dict) -> requests.Response:
        """POST /sessions"""
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id: str, headers: dict) -> requests.Response:
        """GET /sessions/{id}"""
        return self._request("GET", f"/sessions/{session_id}", None, headers)

    def list_sessions(
        self,
        headers: dict,
        reviewer_id: Optional[str] = None,
        matter_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /sessions"""
        return self._request(
            "GET",
            "/sessions",
            None,
            headers,
            _query(
                reviewer_id=reviewer_id,
                matter_id=matter_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def set_session_lifecycle(
        self, session_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /sessions/{id}/lifecycle"""
        return self._request(
            "POST", f"/sessions/{session_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    def create_batch(
        self, matter_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /matters/{id}/batches"""
        return self._request(
            "POST", f"/matters/{matter_id}/batches", payload, headers
        )

    def get_batch(self, batch_id: str, headers: dict) -> requests.Response:
        """GET /batches/{id}"""
        return self._request("GET", f"/batches/{batch_id}", None, headers)

    def list_batches(
        self,
        headers: dict,
        matter_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /batches"""
        return self._request(
            "GET",
            "/batches",
            None,
            headers,
            _query(
                matter_id=matter_id, status=status, limit=limit, offset=offset
            ),
        )

    def dissolve_batch(
        self, batch_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /batches/{id}/dissolve"""
        return self._request(
            "POST", f"/batches/{batch_id}/dissolve", payload or {}, headers
        )

    def release_batch(
        self, batch_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /batches/{id}/release"""
        return self._request(
            "POST", f"/batches/{batch_id}/release", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def create_assignment(
        self, batch_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /batches/{id}/assignments"""
        return self._request(
            "POST", f"/batches/{batch_id}/assignments", payload, headers
        )

    def auto_assign(
        self, batch_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /batches/{id}/auto-assign"""
        return self._request(
            "POST", f"/batches/{batch_id}/auto-assign", payload, headers
        )

    def get_assignment(self, assignment_id: str, headers: dict) -> requests.Response:
        """GET /assignments/{id}"""
        return self._request("GET", f"/assignments/{assignment_id}", None, headers)

    def list_assignments(
        self,
        headers: dict,
        batch_id: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        reassigned_from_assignment_id: Optional[str] = None,
        status: Optional[str] = None,
        pass_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /assignments"""
        return self._request(
            "GET",
            "/assignments",
            None,
            headers,
            _query(
                batch_id=batch_id,
                reviewer_id=reviewer_id,
                reassigned_from_assignment_id=reassigned_from_assignment_id,
                status=status,
                pass_type=pass_type,
                limit=limit,
                offset=offset,
            ),
        )

    def list_assignment_budget_ledger(
        self,
        assignment_id: str,
        headers: dict,
        entry_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /assignments/{id}/budget-ledger"""
        return self._request(
            "GET",
            f"/assignments/{assignment_id}/budget-ledger",
            None,
            headers,
            _query(entry_type=entry_type, limit=limit, offset=offset),
        )

    def start_assignment(
        self, assignment_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /assignments/{id}/start"""
        return self._request(
            "POST", f"/assignments/{assignment_id}/start", payload or {}, headers
        )

    def record_progress(
        self, assignment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /assignments/{id}/progress"""
        return self._request(
            "POST", f"/assignments/{assignment_id}/progress", payload, headers
        )

    def submit_assignment(
        self, assignment_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        """POST /assignments/{id}/submit"""
        return self._request(
            "POST", f"/assignments/{assignment_id}/submit", payload or {}, headers
        )

    def void_assignment(
        self, assignment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /assignments/{id}/void"""
        return self._request(
            "POST", f"/assignments/{assignment_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Quality-control samples
    # ------------------------------------------------------------------
    def create_qc_sample(
        self, batch_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /batches/{id}/qc-samples"""
        return self._request(
            "POST", f"/batches/{batch_id}/qc-samples", payload, headers
        )

    def get_qc_sample(self, sample_id: str, headers: dict) -> requests.Response:
        """GET /qc-samples/{id}"""
        return self._request("GET", f"/qc-samples/{sample_id}", None, headers)

    def list_qc_samples(
        self,
        headers: dict,
        batch_id: Optional[str] = None,
        validated_by_reviewer_id: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /qc-samples"""
        return self._request(
            "GET",
            "/qc-samples",
            None,
            headers,
            _query(
                batch_id=batch_id,
                validated_by_reviewer_id=validated_by_reviewer_id,
                outcome=outcome,
                limit=limit,
                offset=offset,
            ),
        )

    def validate_qc_sample(
        self, sample_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /qc-samples/{id}/validate"""
        return self._request(
            "POST", f"/qc-samples/{sample_id}/validate", payload, headers
        )

    # ------------------------------------------------------------------
    # Privilege log entries
    # ------------------------------------------------------------------
    def create_privilege_entry(
        self, batch_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /batches/{id}/privilege-log-entries"""
        return self._request(
            "POST", f"/batches/{batch_id}/privilege-log-entries", payload, headers
        )

    def get_privilege_entry(self, entry_id: str, headers: dict) -> requests.Response:
        """GET /privilege-log-entries/{id}"""
        return self._request(
            "GET", f"/privilege-log-entries/{entry_id}", None, headers
        )

    def list_privilege_entries(
        self,
        headers: dict,
        matter_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        authored_by_reviewer_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        """GET /privilege-log-entries"""
        return self._request(
            "GET",
            "/privilege-log-entries",
            None,
            headers,
            _query(
                matter_id=matter_id,
                batch_id=batch_id,
                authored_by_reviewer_id=authored_by_reviewer_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def validate_privilege_entry(
        self, entry_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /privilege-log-entries/{id}/validate"""
        return self._request(
            "POST", f"/privilege-log-entries/{entry_id}/validate", payload, headers
        )

    def amend_privilege_entry(
        self, entry_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        """POST /privilege-log-entries/{id}/amend"""
        return self._request(
            "POST", f"/privilege-log-entries/{entry_id}/amend", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for header-level probes
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request; used for missing or unknown header probes."""
        return self._request(method, path, payload, headers, params)
