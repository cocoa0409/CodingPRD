"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/royalties"


class ApiClient(GenericApiClient):
    # ─── RightsHolder ─────────────────────────────────

    def create_rights_holder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rights-holders", payload, headers)

    def get_rights_holder(self, holder_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rights-holders/{holder_id}", headers=headers
        )

    # ─── Work ─────────────────────────────────────────

    def create_work(self, payload, headers):
        return self._request("POST", f"{PREFIX}/works", payload, headers)

    def get_work(self, work_id, headers):
        return self._request("GET", f"{PREFIX}/works/{work_id}", headers=headers)

    def list_works(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/works", headers=headers, params=params)

    # ─── AccountingPeriod ─────────────────────────────

    def create_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/periods", payload, headers)

    def get_period(self, period_id, headers):
        return self._request("GET", f"{PREFIX}/periods/{period_id}", headers=headers)

    def close_period(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/periods/{period_id}/close", {}, headers
        )

    # ─── UsageBatch ───────────────────────────────────

    def create_usage_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/usage-batches", payload, headers)

    def get_usage_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/usage-batches/{batch_id}", headers=headers
        )

    def list_usage_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/usage-batches", headers=headers, params=params
        )

    def append_usage_line(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-batches/{batch_id}/lines", payload, headers
        )

    def seal_usage_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-batches/{batch_id}/seal", {}, headers
        )

    def match_usage_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-batches/{batch_id}/match", {}, headers
        )

    # ─── UsageLine ────────────────────────────────────

    def get_usage_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/usage-lines/{line_id}", headers=headers)

    def list_usage_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/usage-lines", headers=headers, params=params
        )

    # ─── RightsRegistration ───────────────────────────

    def create_rights_registration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rights-registrations", payload, headers)

    def get_rights_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rights-registrations/{registration_id}", headers=headers
        )

    def list_rights_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rights-registrations", headers=headers, params=params
        )

    def review_rights_registration(self, registration_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rights-registrations/{registration_id}/review", {}, headers
        )

    def request_registration_evidence(self, registration_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rights-registrations/{registration_id}/request-evidence",
            {},
            headers,
        )

    def submit_registration_evidence(self, registration_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rights-registrations/{registration_id}/evidence",
            {},
            headers,
        )

    def approve_rights_registration(self, registration_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rights-registrations/{registration_id}/approve",
            {},
            headers,
        )

    def reject_rights_registration(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rights-registrations/{registration_id}/reject",
            payload,
            headers,
        )

    def dispute_rights_registration(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rights-registrations/{registration_id}/dispute",
            payload,
            headers,
        )

    # ─── RoyaltyPool ──────────────────────────────────

    def create_pool(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"{PREFIX}/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pools", headers=headers, params=params)

    def calculate_pool(self, pool_id, headers):
        return self._request(
            "POST", f"{PREFIX}/pools/{pool_id}/calculate", {}, headers
        )

    def finalize_pool(self, pool_id, headers):
        return self._request("POST", f"{PREFIX}/pools/{pool_id}/finalize", {}, headers)

    # ─── RoyaltyStatement / StatementLine ─────────────

    def create_statement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/statements/{statement_id}", headers=headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/statements", headers=headers, params=params
        )

    def issue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/issue", {}, headers
        )

    def get_statement_line(self, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/statement-lines/{line_id}", headers=headers
        )

    def list_statement_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/statement-lines", headers=headers, params=params
        )

    # ─── AuditEngagement ──────────────────────────────

    def create_audit_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-engagements", payload, headers)

    def get_audit_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/audit-engagements/{engagement_id}", headers=headers
        )

    def list_audit_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/audit-engagements", headers=headers, params=params
        )

    def produce_audit_data(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-engagements/{engagement_id}/data-productions",
            payload,
            headers,
        )

    def record_audit_findings(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-engagements/{engagement_id}/findings",
            payload,
            headers,
        )

    def settle_audit_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-engagements/{engagement_id}/settle",
            payload,
            headers,
        )

    # ─── RateSchedule ─────────────────────────────────

    def create_rate_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-schedules/{schedule_id}", headers=headers
        )

    def promulgate_rate_schedule(self, schedule_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/rate-schedules/{schedule_id}/promulgate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
