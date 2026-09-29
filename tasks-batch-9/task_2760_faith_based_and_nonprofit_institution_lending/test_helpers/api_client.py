"""
Endpoint client for the Faith-Based and Nonprofit Institution Lending API.

One method per endpoint in PRD §4 (sixty in total). Every method returns the
raw ``requests.Response`` so tests can assert HTTP status codes directly.

Timestamp discipline
--------------------
PRD §2.4 mandates "an ISO 8601 UTC timestamp with exactly three
fractional-second digits", while client-supplied instants in PRD §2.5 are
written without a fractional part (for example ``2026-08-01T00:00:00Z``). Tests
must therefore never compare timestamp strings byte-for-byte: use
``canonical_iso`` (or ``assert_iso_equal`` in ``assertions``) so that a
difference of sub-second width alone can never be reported as a defect.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_ISO_PARTS = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_iso(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    A missing fractional part becomes ``.000``; a longer one is truncated to
    three digits; a shorter one is right-padded. ``None`` passes through so a
    null field can still be compared. Anything that is not a recognisable
    ISO 8601 instant is returned unchanged, which keeps assertion failures
    readable instead of masking them.
    """
    if value is None or not isinstance(value, str):
        return value
    match = _ISO_PARTS.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint."""

    # ─── Institutions ─────────────────────────────────────────────────────
    def create_institution(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/institutions", payload, headers)

    def get_institution(self, institution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/institutions/{institution_id}", None, headers)

    def list_institutions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/institutions", params, headers)

    # ─── Giving periods ───────────────────────────────────────────────────
    def create_giving_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/giving-periods", payload, headers)

    def get_giving_period(self, giving_period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/giving-periods/{giving_period_id}", None, headers)

    def list_giving_periods(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/giving-periods", params, headers)

    # ─── Governance authorizations ────────────────────────────────────────
    def create_governance_authorization(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/governance-authorizations", payload, headers)

    def get_governance_authorization(self, governance_authorization_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/governance-authorizations/{governance_authorization_id}", None, headers
        )

    def list_governance_authorizations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/governance-authorizations", params, headers)

    def submit_governance_authorization(
        self,
        governance_authorization_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/governance-authorizations/{governance_authorization_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def board_verify_governance_authorization(
        self, governance_authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/governance-authorizations/{governance_authorization_id}/board-verification",
            payload,
            headers,
        )

    def denominational_decision(
        self, governance_authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/governance-authorizations/{governance_authorization_id}/denominational-decision",
            payload,
            headers,
        )

    def return_governance_authorization_to_draft(
        self, governance_authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/governance-authorizations/{governance_authorization_id}/return-to-draft",
            payload,
            headers,
        )

    # ─── Pledge campaigns ─────────────────────────────────────────────────
    def create_pledge_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pledge-campaigns", payload, headers)

    def get_pledge_campaign(self, pledge_campaign_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pledge-campaigns/{pledge_campaign_id}", None, headers)

    def list_pledge_campaigns(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pledge-campaigns", params, headers)

    def close_pledge_campaign(
        self,
        pledge_campaign_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/pledge-campaigns/{pledge_campaign_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def get_campaign_valuation(
        self, pledge_campaign_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/pledge-campaigns/{pledge_campaign_id}/valuation", params, headers
        )

    # ─── Pledges ──────────────────────────────────────────────────────────
    def create_pledge(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pledges/{pledge_id}", None, headers)

    def list_pledges(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pledges", params, headers)

    def record_pledge_payment(self, pledge_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pledges/{pledge_id}/payments", payload, headers)

    def lapse_pledge(self, pledge_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pledges/{pledge_id}/lapse", payload, headers)

    def reinstate_pledge(self, pledge_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/pledges/{pledge_id}/reinstate", payload, headers)

    # ─── Collateral assets ────────────────────────────────────────────────
    def create_collateral_asset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/collateral-assets", payload, headers)

    def get_collateral_asset(self, collateral_asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/collateral-assets/{collateral_asset_id}", None, headers)

    def list_collateral_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/collateral-assets", params, headers)

    def assign_collateral_asset(
        self, collateral_asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/collateral-assets/{collateral_asset_id}/assignments", payload, headers
        )

    def release_collateral_asset(
        self, collateral_asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/collateral-assets/{collateral_asset_id}/release", payload, headers
        )

    # ─── Loan applications ────────────────────────────────────────────────
    def create_loan_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/loan-applications", payload, headers)

    def get_loan_application(self, loan_application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/loan-applications/{loan_application_id}", None, headers)

    def list_loan_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/loan-applications", params, headers)

    def submit_underwriting(
        self,
        loan_application_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/loan-applications/{loan_application_id}/submit-underwriting",
            payload if payload is not None else {},
            headers,
        )

    def committee_referral(
        self,
        loan_application_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/loan-applications/{loan_application_id}/committee-referral",
            payload if payload is not None else {},
            headers,
        )

    def committee_decision(
        self, loan_application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/loan-applications/{loan_application_id}/committee-decision", payload, headers
        )

    def get_underwriting_summary(
        self, loan_application_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/loan-applications/{loan_application_id}/underwriting-summary",
            params,
            headers,
        )

    # ─── Loans ────────────────────────────────────────────────────────────
    def create_loan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/loans/{loan_id}", None, headers)

    def list_loans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/loans", params, headers)

    def record_loan_payment(self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/loans/{loan_id}/payments", payload, headers)

    def construction_completion(self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/construction-completion", payload, headers
        )

    # ─── Draw requests ────────────────────────────────────────────────────
    def create_draw_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/draw-requests", payload, headers)

    def get_draw_request(self, draw_request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/draw-requests/{draw_request_id}", None, headers)

    def list_draw_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/draw-requests", params, headers)

    def approve_draw_request(
        self, draw_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/draw-requests/{draw_request_id}/approve", payload, headers)

    def disburse_draw_request(
        self,
        draw_request_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/draw-requests/{draw_request_id}/disburse",
            payload if payload is not None else {},
            headers,
        )

    def reject_draw_request(
        self, draw_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/draw-requests/{draw_request_id}/reject", payload, headers)

    def void_draw_request(self, draw_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/draw-requests/{draw_request_id}/void", payload, headers)

    def reinstate_draw_request(
        self, draw_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/draw-requests/{draw_request_id}/reinstate", payload, headers)

    # ─── Covenants ────────────────────────────────────────────────────────
    def create_covenant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/covenants", payload, headers)

    def get_covenant(self, covenant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/covenants/{covenant_id}", None, headers)

    def list_covenants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/covenants", params, headers)

    def run_covenant_test(self, covenant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/covenants/{covenant_id}/tests", payload, headers)

    def cure_covenant(self, covenant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/covenants/{covenant_id}/cure", payload, headers)

    def waive_covenant(self, covenant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/covenants/{covenant_id}/waive", payload, headers)

    # ─── Workout plans ────────────────────────────────────────────────────
    def create_workout_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/workout-plans", payload, headers)

    def get_workout_plan(self, workout_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/workout-plans/{workout_plan_id}", None, headers)

    def list_workout_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/workout-plans", params, headers)

    def approve_workout_plan(
        self,
        workout_plan_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/workout-plans/{workout_plan_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
