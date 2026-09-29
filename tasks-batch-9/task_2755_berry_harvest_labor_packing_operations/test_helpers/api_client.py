"""
One method per endpoint of the Berry Harvest Ops API (PRD section 4).

All fifty-eight endpoints are mounted under the ``/berry-ops`` prefix and are
addressed at the top level: PRD section 1 states "every resource is addressed
at the top level, and relationships are carried as explicit identifiers in
request bodies rather than as nested collection paths".

Every method returns the raw ``requests.Response`` so that tests can assert
on status codes as well as on bodies.

Timestamp hygiene: the PRD renders instants "with exactly three fractional
digits", but comparisons of *domain* instants that the caller supplied (a
`cool_start_at`, a `shipped_at`) must not depend on how many fractional
digits the server chose to echo. ``canonical_instant`` normalises any RFC
3339 UTC instant to a fixed millisecond rendering so tests can compare the
value they sent against the value they read back.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?:[Zz]|\+00:00)$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an RFC 3339 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Sub-second width is not part of the identity of an instant, so a value
    echoed as ``2026-08-03T09:00:00Z`` and one echoed as
    ``2026-08-03T09:00:00.000Z`` canonicalise to the same string. Values
    that are not instants (including ``None``) are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two RFC 3339 UTC renderings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Typed facade over the fifty-eight endpoints of PRD section 4."""

    # ─── Production blocks ────────────────────────────────────────────────

    def create_block(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/blocks — register a production block."""
        return self._request("POST", f"{BASE}/blocks", payload, headers)

    def get_block(self, block_id: str, headers: Dict[str, str]):
        """GET /berry-ops/blocks/{block_id}."""
        return self._request("GET", f"{BASE}/blocks/{block_id}", None, headers)

    def list_blocks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/blocks — filterable by variety, posture or water status."""
        return self._request("GET", f"{BASE}/blocks", params, headers)

    def quarantine_block(
        self, block_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/blocks/{block_id}/quarantine."""
        return self._request(
            "POST", f"{BASE}/blocks/{block_id}/quarantine", payload, headers
        )

    def clear_block(
        self,
        block_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/blocks/{block_id}/clear."""
        return self._request(
            "POST", f"{BASE}/blocks/{block_id}/clear", payload or {}, headers
        )

    def get_traceability_summary(self, block_id: str, headers: Dict[str, str]):
        """GET /berry-ops/blocks/{block_id}/traceability-summary."""
        return self._request(
            "GET", f"{BASE}/blocks/{block_id}/traceability-summary", None, headers
        )

    # ─── Agricultural water register ──────────────────────────────────────

    def create_water_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/water-tests — record one agricultural-water sample."""
        return self._request("POST", f"{BASE}/water-tests", payload, headers)

    def get_water_test(self, water_test_id: str, headers: Dict[str, str]):
        """GET /berry-ops/water-tests/{water_test_id}."""
        return self._request(
            "GET", f"{BASE}/water-tests/{water_test_id}", None, headers
        )

    def list_water_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/water-tests — ordered by sample_date then created_at."""
        return self._request("GET", f"{BASE}/water-tests", params, headers)

    # ─── Crews ────────────────────────────────────────────────────────────

    def create_crew(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/crews — recruit a harvest crew."""
        return self._request("POST", f"{BASE}/crews", payload, headers)

    def get_crew(self, crew_id: str, headers: Dict[str, str]):
        """GET /berry-ops/crews/{crew_id} — includes the wage ledger."""
        return self._request("GET", f"{BASE}/crews/{crew_id}", None, headers)

    def list_crews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/crews — filterable by labor_program or status."""
        return self._request("GET", f"{BASE}/crews", params, headers)

    def record_support_plan(
        self, crew_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/crews/{crew_id}/support-plan."""
        return self._request(
            "POST", f"{BASE}/crews/{crew_id}/support-plan", payload, headers
        )

    def certify_crew(
        self,
        crew_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/crews/{crew_id}/certify."""
        return self._request(
            "POST", f"{BASE}/crews/{crew_id}/certify", payload or {}, headers
        )

    def release_crew(
        self,
        crew_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/crews/{crew_id}/release."""
        return self._request(
            "POST", f"{BASE}/crews/{crew_id}/release", payload or {}, headers
        )

    # ─── Pickers ──────────────────────────────────────────────────────────

    def create_picker(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/pickers — register a picker on a crew."""
        return self._request("POST", f"{BASE}/pickers", payload, headers)

    def get_picker(self, picker_id: str, headers: Dict[str, str]):
        """GET /berry-ops/pickers/{picker_id} — includes lifetime productivity."""
        return self._request("GET", f"{BASE}/pickers/{picker_id}", None, headers)

    def list_pickers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/pickers — filterable to one crew."""
        return self._request("GET", f"{BASE}/pickers", params, headers)

    def record_hygiene_training(
        self, picker_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/pickers/{picker_id}/hygiene-training."""
        return self._request(
            "POST", f"{BASE}/pickers/{picker_id}/hygiene-training", payload, headers
        )

    # ─── Cooling tunnels ──────────────────────────────────────────────────

    def create_cooling_tunnel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/cooling-tunnels — register a forced-air tunnel."""
        return self._request("POST", f"{BASE}/cooling-tunnels", payload, headers)

    def get_cooling_tunnel(self, cooling_tunnel_id: str, headers: Dict[str, str]):
        """GET /berry-ops/cooling-tunnels/{cooling_tunnel_id}."""
        return self._request(
            "GET", f"{BASE}/cooling-tunnels/{cooling_tunnel_id}", None, headers
        )

    def list_cooling_tunnels(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /berry-ops/cooling-tunnels — takes no filter."""
        return self._request("GET", f"{BASE}/cooling-tunnels", params, headers)

    # ─── Harvest windows ──────────────────────────────────────────────────

    def create_harvest_window(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/harvest-windows — plan a harvest window."""
        return self._request("POST", f"{BASE}/harvest-windows", payload, headers)

    def get_harvest_window(self, harvest_window_id: str, headers: Dict[str, str]):
        """GET /berry-ops/harvest-windows/{harvest_window_id}."""
        return self._request(
            "GET", f"{BASE}/harvest-windows/{harvest_window_id}", None, headers
        )

    def list_harvest_windows(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /berry-ops/harvest-windows — filterable by block, crew or status."""
        return self._request("GET", f"{BASE}/harvest-windows", params, headers)

    def confirm_harvest_window(
        self,
        harvest_window_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/harvest-windows/{harvest_window_id}/confirm."""
        return self._request(
            "POST",
            f"{BASE}/harvest-windows/{harvest_window_id}/confirm",
            payload or {},
            headers,
        )

    def open_harvest_window(
        self,
        harvest_window_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/harvest-windows/{harvest_window_id}/open."""
        return self._request(
            "POST",
            f"{BASE}/harvest-windows/{harvest_window_id}/open",
            payload or {},
            headers,
        )

    def close_harvest_window(
        self,
        harvest_window_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/harvest-windows/{harvest_window_id}/close."""
        return self._request(
            "POST",
            f"{BASE}/harvest-windows/{harvest_window_id}/close",
            payload or {},
            headers,
        )

    def resume_harvest_window(
        self,
        harvest_window_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/harvest-windows/{harvest_window_id}/resume."""
        return self._request(
            "POST",
            f"{BASE}/harvest-windows/{harvest_window_id}/resume",
            payload or {},
            headers,
        )

    def cancel_harvest_window(
        self, harvest_window_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/harvest-windows/{harvest_window_id}/cancel."""
        return self._request(
            "POST",
            f"{BASE}/harvest-windows/{harvest_window_id}/cancel",
            payload,
            headers,
        )

    # ─── Pick sessions ────────────────────────────────────────────────────

    def create_pick_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/pick-sessions — open a picker's day on an OPEN window."""
        return self._request("POST", f"{BASE}/pick-sessions", payload, headers)

    def get_pick_session(self, pick_session_id: str, headers: Dict[str, str]):
        """GET /berry-ops/pick-sessions/{pick_session_id}."""
        return self._request(
            "GET", f"{BASE}/pick-sessions/{pick_session_id}", None, headers
        )

    def list_pick_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /berry-ops/pick-sessions — the only channel for cascade-touched rows."""
        return self._request("GET", f"{BASE}/pick-sessions", params, headers)

    def tally_pick_session(
        self, pick_session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/pick-sessions/{pick_session_id}/tally."""
        return self._request(
            "POST", f"{BASE}/pick-sessions/{pick_session_id}/tally", payload, headers
        )

    def approve_pick_session(
        self,
        pick_session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/pick-sessions/{pick_session_id}/approve."""
        return self._request(
            "POST",
            f"{BASE}/pick-sessions/{pick_session_id}/approve",
            payload or {},
            headers,
        )

    def dispute_pick_session(
        self, pick_session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/pick-sessions/{pick_session_id}/dispute."""
        return self._request(
            "POST", f"{BASE}/pick-sessions/{pick_session_id}/dispute", payload, headers
        )

    # ─── Payroll runs ─────────────────────────────────────────────────────

    def create_payroll_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/payroll-runs — open a draft pay period."""
        return self._request("POST", f"{BASE}/payroll-runs", payload, headers)

    def get_payroll_run(self, payroll_run_id: str, headers: Dict[str, str]):
        """GET /berry-ops/payroll-runs/{payroll_run_id}."""
        return self._request(
            "GET", f"{BASE}/payroll-runs/{payroll_run_id}", None, headers
        )

    def list_payroll_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/payroll-runs — filterable by crew or status."""
        return self._request("GET", f"{BASE}/payroll-runs", params, headers)

    def lock_payroll_run(
        self,
        payroll_run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/payroll-runs/{payroll_run_id}/lock."""
        return self._request(
            "POST",
            f"{BASE}/payroll-runs/{payroll_run_id}/lock",
            payload or {},
            headers,
        )

    def settle_payroll_run(
        self,
        payroll_run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/payroll-runs/{payroll_run_id}/settle."""
        return self._request(
            "POST",
            f"{BASE}/payroll-runs/{payroll_run_id}/settle",
            payload or {},
            headers,
        )

    # ─── Fruit lots ───────────────────────────────────────────────────────

    def create_fruit_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/fruit-lots — record a field-packed lot."""
        return self._request("POST", f"{BASE}/fruit-lots", payload, headers)

    def get_fruit_lot(self, fruit_lot_id: str, headers: Dict[str, str]):
        """GET /berry-ops/fruit-lots/{fruit_lot_id}."""
        return self._request("GET", f"{BASE}/fruit-lots/{fruit_lot_id}", None, headers)

    def list_fruit_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /berry-ops/fruit-lots — the only channel for a repack child lot."""
        return self._request("GET", f"{BASE}/fruit-lots", params, headers)

    def start_cooling(
        self, fruit_lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/fruit-lots/{fruit_lot_id}/start-cooling."""
        return self._request(
            "POST", f"{BASE}/fruit-lots/{fruit_lot_id}/start-cooling", payload, headers
        )

    def complete_cooling(
        self, fruit_lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/fruit-lots/{fruit_lot_id}/complete-cooling."""
        return self._request(
            "POST",
            f"{BASE}/fruit-lots/{fruit_lot_id}/complete-cooling",
            payload,
            headers,
        )

    def repack_fruit_lot(
        self, fruit_lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/fruit-lots/{fruit_lot_id}/repack — returns the child lot."""
        return self._request(
            "POST", f"{BASE}/fruit-lots/{fruit_lot_id}/repack", payload, headers
        )

    def reject_fruit_lot(
        self, fruit_lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/fruit-lots/{fruit_lot_id}/reject."""
        return self._request(
            "POST", f"{BASE}/fruit-lots/{fruit_lot_id}/reject", payload, headers
        )

    # ─── Buyer commitments ────────────────────────────────────────────────

    def create_buyer_commitment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/buyer-commitments — register a buyer program."""
        return self._request("POST", f"{BASE}/buyer-commitments", payload, headers)

    def get_buyer_commitment(self, buyer_commitment_id: str, headers: Dict[str, str]):
        """GET /berry-ops/buyer-commitments/{buyer_commitment_id}."""
        return self._request(
            "GET", f"{BASE}/buyer-commitments/{buyer_commitment_id}", None, headers
        )

    def list_buyer_commitments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /berry-ops/buyer-commitments — filterable by variety or status."""
        return self._request("GET", f"{BASE}/buyer-commitments", params, headers)

    def settle_buyer_commitment(
        self,
        buyer_commitment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /berry-ops/buyer-commitments/{buyer_commitment_id}/settle."""
        return self._request(
            "POST",
            f"{BASE}/buyer-commitments/{buyer_commitment_id}/settle",
            payload or {},
            headers,
        )

    # ─── Lot allocations ──────────────────────────────────────────────────

    def create_lot_allocation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/lot-allocations — pledge pounds to a commitment."""
        return self._request("POST", f"{BASE}/lot-allocations", payload, headers)

    def get_lot_allocation(self, lot_allocation_id: str, headers: Dict[str, str]):
        """GET /berry-ops/lot-allocations/{lot_allocation_id}."""
        return self._request(
            "GET", f"{BASE}/lot-allocations/{lot_allocation_id}", None, headers
        )

    def list_lot_allocations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /berry-ops/lot-allocations — the only channel for released lines."""
        return self._request("GET", f"{BASE}/lot-allocations", params, headers)

    def ship_lot_allocation(
        self, lot_allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/lot-allocations/{lot_allocation_id}/ship."""
        return self._request(
            "POST",
            f"{BASE}/lot-allocations/{lot_allocation_id}/ship",
            payload,
            headers,
        )

    def release_lot_allocation(
        self, lot_allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /berry-ops/lot-allocations/{lot_allocation_id}/release."""
        return self._request(
            "POST",
            f"{BASE}/lot-allocations/{lot_allocation_id}/release",
            payload,
            headers,
        )

    # ─── The logical clock ────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        """POST /berry-ops/_clock/set_current_utc — move the logical UTC clock."""
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /berry-ops/_clock/set_current_utc with a caller-shaped body."""
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )
