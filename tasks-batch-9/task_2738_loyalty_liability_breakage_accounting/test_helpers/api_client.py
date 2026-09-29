"""
One typed method per endpoint of the Loyalty Liability & Breakage Accounting API.

Every method returns the raw ``requests.Response`` so a test can assert on the
status code as well as the body. Query filters are passed as keyword arguments
and any left as ``None`` are dropped so that an omitted filter is genuinely
absent from the query string rather than sent as the literal "None".

Timestamp hygiene: an implementation is free to serialise an instant as
``2028-08-04T00:00:00Z`` or ``2028-08-04T00:00:00.000Z`` or with a ``+00:00``
offset. Those are the same instant, so this client canonicalises every ISO-8601
string inside the envelope's ``data`` payload to a single form before a test ever
sees it. The envelope's ``meta`` block is deliberately left untouched, because
the contract pins the format of ``api_request_timestamp`` itself, and
``response.text`` always remains the untouched wire bytes.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# ─── Timestamp canonicalisation ──────────────────────────────────────────────
_ISO_INSTANT = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"[Tt ]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?P<frac>\.\d+)?"
    r"(?P<zone>[Zz]|[+-]\d{2}:?\d{2})$"
)

_UTC_ZONES = {"z", "+00:00", "-00:00", "+0000", "-0000"}


def canonical_timestamp(value: str) -> str:
    """
    Reduce one ISO-8601 UTC instant to a single spelling.

    A zero fractional part is dropped, a non-zero one is normalised to exactly
    three digits, and a zero UTC offset becomes ``Z``. A string that is not a
    UTC instant — a date, a non-UTC offset, free text — is returned unchanged.
    """
    match = _ISO_INSTANT.match(value)
    if not match:
        return value
    if match.group("zone").lower() not in _UTC_ZONES:
        return value

    fraction = match.group("frac") or ""
    if fraction:
        digits = fraction[1:]
        if set(digits) == {"0"}:
            fraction = ""
        else:
            fraction = "." + (digits + "000")[:3]
    return f"{match.group('date')}T{match.group('time')}{fraction}Z"


def canonicalize(value: Any) -> Any:
    """Apply :func:`canonical_timestamp` to every string inside a parsed body."""
    if isinstance(value, str):
        return canonical_timestamp(value)
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {key: canonicalize(item) for key, item in value.items()}
    return value


def _canonical_body(body: Any) -> Any:
    """Canonicalise the envelope's data payload, leaving meta as the wire had it."""
    if isinstance(body, dict) and "data" in body:
        canonical = dict(body)
        canonical["data"] = canonicalize(body["data"])
        return canonical
    return canonicalize(body)


def _install_canonical_json(response: requests.Response) -> requests.Response:
    """Replace ``response.json`` with a timestamp-canonicalising parser."""
    parse = response.json

    def _json(**kwargs: Any) -> Any:
        return _canonical_body(parse(**kwargs))

    response.json = _json  # type: ignore[method-assign]
    return response


def raw_json(response: requests.Response) -> Any:
    """The body exactly as the wire delivered it, with no canonicalisation."""
    return requests.Response.json(response)


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is None so an omitted filter is truly omitted."""
    if not params:
        return None
    cleaned = {key: value for key, value in params.items() if value is not None}
    return cleaned or None


class ApiClient(GenericApiClient):
    """The endpoint surface of the API under test."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(method, path, payload, headers, params)
        return _install_canonical_json(response)

    # ─── Escape hatch ────────────────────────────────────────────────────────
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Call an arbitrary method and path, for probes no typed method covers."""
        return self._request(method, path, payload, headers, params)

    # ─── The logical clock ───────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers=None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── LoyaltyProgram ──────────────────────────────────────────────────────
    def create_program(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/programs", _clean(filters), headers)

    def get_program(self, program_id, headers=None) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def activate_program(self, program_id, payload=None, headers=None) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/activate", payload, headers)

    def suspend_program(self, program_id, payload=None, headers=None) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/suspend", payload, headers)

    def close_program(self, program_id, payload=None, headers=None) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/close", payload, headers)

    # ─── StateExpiryRule ─────────────────────────────────────────────────────
    def create_state_expiry_rule(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/state-expiry-rules", payload, headers)

    def list_state_expiry_rules(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/state-expiry-rules", _clean(filters), headers)

    def get_state_expiry_rule(self, rule_id, headers=None) -> requests.Response:
        return self._request("GET", f"/state-expiry-rules/{rule_id}", None, headers)

    # ─── Cohort ──────────────────────────────────────────────────────────────
    def create_cohort(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/cohorts", payload, headers)

    def list_cohorts(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/cohorts", _clean(filters), headers)

    def get_cohort(self, cohort_id, headers=None) -> requests.Response:
        return self._request("GET", f"/cohorts/{cohort_id}", None, headers)

    # ─── Member ──────────────────────────────────────────────────────────────
    def create_member(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/members", _clean(filters), headers)

    def get_member(self, member_id, headers=None) -> requests.Response:
        return self._request("GET", f"/members/{member_id}", None, headers)

    # ─── AccountingPeriod ────────────────────────────────────────────────────
    def create_period(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/accounting-periods", payload, headers)

    def list_periods(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/accounting-periods", _clean(filters), headers)

    def get_period(self, period_id, headers=None) -> requests.Response:
        return self._request("GET", f"/accounting-periods/{period_id}", None, headers)

    def get_liability_rollforward(self, period_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"/accounting-periods/{period_id}/liability-rollforward", None, headers
        )

    def soft_close_period(self, period_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/accounting-periods/{period_id}/soft-close", payload, headers
        )

    def reopen_period(self, period_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/accounting-periods/{period_id}/reopen", payload, headers
        )

    def hard_close_period(self, period_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/accounting-periods/{period_id}/hard-close", payload, headers
        )

    def run_expiry_sweep(self, period_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/accounting-periods/{period_id}/expiry-sweep", payload, headers
        )

    # ─── PartnerAgreement ────────────────────────────────────────────────────
    def create_agreement(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/partner-agreements", payload, headers)

    def list_agreements(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/partner-agreements", _clean(filters), headers)

    def get_agreement(self, agreement_id, headers=None) -> requests.Response:
        return self._request("GET", f"/partner-agreements/{agreement_id}", None, headers)

    def terminate_agreement(self, agreement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/terminate", payload, headers
        )

    # ─── PointLot ────────────────────────────────────────────────────────────
    def create_point_lot(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/point-lots", payload, headers)

    def list_point_lots(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/point-lots", _clean(filters), headers)

    def get_point_lot(self, lot_id, headers=None) -> requests.Response:
        return self._request("GET", f"/point-lots/{lot_id}", None, headers)

    def list_lot_allocations(self, lot_id, headers=None, **filters) -> requests.Response:
        return self._request(
            "GET", f"/point-lots/{lot_id}/allocations", _clean(filters), headers
        )

    # ─── RedemptionEvent ─────────────────────────────────────────────────────
    def create_redemption(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/redemption-events", payload, headers)

    def list_redemptions(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/redemption-events", _clean(filters), headers)

    def get_redemption(self, redemption_id, headers=None) -> requests.Response:
        return self._request("GET", f"/redemption-events/{redemption_id}", None, headers)

    def list_redemption_allocations(self, redemption_id, headers=None, **filters) -> requests.Response:
        return self._request(
            "GET",
            f"/redemption-events/{redemption_id}/allocations",
            _clean(filters),
            headers,
        )

    def allocate_redemption(self, redemption_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/redemption-events/{redemption_id}/allocate", payload, headers
        )

    def fulfill_redemption(self, redemption_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/redemption-events/{redemption_id}/fulfill", payload, headers
        )

    def reverse_redemption(self, redemption_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/redemption-events/{redemption_id}/reverse", payload, headers
        )

    # ─── BreakageEstimate ────────────────────────────────────────────────────
    def create_estimate(self, program_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/breakage-estimates", payload, headers
        )

    def list_estimates(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/breakage-estimates", _clean(filters), headers)

    def get_estimate(self, estimate_id, headers=None) -> requests.Response:
        return self._request("GET", f"/breakage-estimates/{estimate_id}", None, headers)

    def get_sensitivity(self, estimate_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"/breakage-estimates/{estimate_id}/sensitivity", None, headers
        )

    def submit_estimate(self, estimate_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/breakage-estimates/{estimate_id}/submit", payload, headers
        )

    def reject_estimate(self, estimate_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/breakage-estimates/{estimate_id}/reject", payload, headers
        )

    def approve_estimate(self, estimate_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/breakage-estimates/{estimate_id}/approve", payload, headers
        )

    # ─── SettlementStatement ─────────────────────────────────────────────────
    def create_statement(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/settlement-statements", payload, headers)

    def list_statements(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/settlement-statements", _clean(filters), headers)

    def get_statement(self, statement_id, headers=None) -> requests.Response:
        return self._request("GET", f"/settlement-statements/{statement_id}", None, headers)

    def issue_statement(self, statement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/issue", payload, headers
        )

    def dispute_statement(self, statement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/dispute", payload, headers
        )

    def resolve_statement(self, statement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/resolve", payload, headers
        )

    def pay_statement(self, statement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/pay", payload, headers
        )

    def write_off_statement(self, statement_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/write-off", payload, headers
        )

    # ─── ProgramChangeOrder ──────────────────────────────────────────────────
    def create_change_order(self, payload, headers=None) -> requests.Response:
        return self._request("POST", "/program-change-orders", payload, headers)

    def list_change_orders(self, headers=None, **filters) -> requests.Response:
        return self._request("GET", "/program-change-orders", _clean(filters), headers)

    def get_change_order(self, order_id, headers=None) -> requests.Response:
        return self._request("GET", f"/program-change-orders/{order_id}", None, headers)

    def approve_change_order(self, order_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/program-change-orders/{order_id}/approve", payload, headers
        )

    def apply_change_order(self, order_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST", f"/program-change-orders/{order_id}/apply", payload, headers
        )


# The single client every test shares.
api_client = ApiClient()
