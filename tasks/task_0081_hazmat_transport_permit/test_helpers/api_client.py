"""HTTP client wrapper for the hazmat-transport-permit API surface.

Extends the local-runner framework's ``GenericApiClient`` with one method
per of the 37 PRD-declared endpoints across the seven aggregate clusters
(company, driver, vehicle-and-inspection, route, permit, trip-and-gps,
penalty-and-summary) plus the two test-mode endpoints
``POST /v1/_clock/advance`` and ``POST /v1/_sweep/run``.  Each method
takes the request's path-parameters, the optional body payload dict, the
auth-header dict, and the optional query-parameter dict, and returns the
raw ``requests.Response`` object the framework's validators consume.

Two out-of-band administrative affordances supplement the public surface
for test-harness use: ``admin_reset`` POSTs to a ``POST /v1/_admin/reset``
endpoint the implementation is expected to expose for inter-test
state-wipe, and ``admin_wallet_topup`` POSTs to a
``POST /v1/_admin/wallet-topup`` endpoint with the body
``{company_id, amount_cents}`` for the regulator-side-bookkeeping
simulation the PRD's §2.11 names as the wallet-side input the API
otherwise does not expose.  Both endpoints accept the
``TestHarness`` role headers.  If the implementation under test omits
either endpoint the corresponding fixture's ``get_success_data`` lifts
the resulting non-2xx into a clear ``Setup step failed`` assertion that
points at the missing affordance, rather than the silent
side-effect-leak between tests that the absence of a reset would
otherwise produce.

The ``Idempotency-Key`` header on the GPS-ingest endpoint is a separate
optional argument because it is not a body-field — the header travels
alongside the auth-header pair on the wire.

Every method is a thin one-line delegate to ``self._request`` and
returns the raw response object so the test layer can assert on the
status code via the framework's ``validate_success(response, 201)`` and
``validate_error(response, "ERR_X")`` validators uniformly.  The
docstrings paraphrase the PRD's §4 endpoint-reference row for the
endpoint in question.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .test_users import OPAQUE_TEST_HARNESS_ID, ROLE_TEST_HARNESS


# Standard test-harness identity header dict for the admin endpoints.
_TEST_HARNESS_HEADERS: Dict[str, str] = {
    "X-User-ID": OPAQUE_TEST_HARNESS_ID,
    "X-User-Role": ROLE_TEST_HARNESS,
}


class ApiClient(GenericApiClient):
    """One method per endpoint plus the two test-mode endpoints and the
    two admin affordances.  Inherits ``_request`` from the framework's
    ``GenericApiClient`` base.  The base reads the ``API_BASE_URL``
    environment variable (or falls back to ``http://localhost:10000``)
    at construction time, which is the local-runner framework's
    contract for telling tests where the server-under-test is reachable.
    """

    # ─── Company endpoints ─────────────────────────────────────────────

    def create_company(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies`` — the bootstrap company-application
        endpoint.  The operator's ``X-User-ID`` is the bootstrap-token
        identifier; the response carries the server-minted row's id."""
        return self._request("POST", "/v1/companies", payload, headers)

    def get_company(self, company_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/companies/{company_id}``."""
        return self._request("GET", f"/v1/companies/{company_id}", headers=headers)

    def list_companies(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """``GET /v1/companies`` with optional ``qualification_status``
        and ``company_id`` filters, the standard ``limit``/``offset``
        pagination."""
        return self._request("GET", "/v1/companies", headers=headers, params=params)

    def submit_company(self, company_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/submit`` — the operator's
        ``DRAFT→SUBMITTED`` transition (also handling the
        ``REVOKED→DRAFT→SUBMITTED`` cycle-reentry per the company's
        state-machine cycle prose)."""
        return self._request("POST", f"/v1/companies/{company_id}/submit", payload or {}, headers)

    def approve_company(self, company_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/approve`` — the regulator's
        ``SUBMITTED→APPROVED`` transition."""
        return self._request("POST", f"/v1/companies/{company_id}/approve", payload or {}, headers)

    def revoke_company(self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/revoke`` — the regulator's
        ``APPROVED→REVOKED`` transition with the required
        ``reason_note`` body field and the deferred cross-aggregate
        cascade onto the company's still-ACTIVE permits via the next
        verify-compliance call on each."""
        return self._request("POST", f"/v1/companies/{company_id}/revoke", payload, headers)

    # ─── Driver endpoints ──────────────────────────────────────────────

    def create_driver(self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/drivers`` — the operator
        registers a driver under their company.  Parent company must be
        ``APPROVED`` per the children-creation gate."""
        return self._request("POST", f"/v1/companies/{company_id}/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/drivers/{driver_id}``."""
        return self._request("GET", f"/v1/drivers/{driver_id}", headers=headers)

    def refresh_driver_endorsement(self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/drivers/{driver_id}/refresh-endorsement`` — the
        regulator's attestation endpoint with two mutually-exclusive
        body shapes (the attestation shape ``{endorsement_valid_until,
        endorsement_classes, version}`` for the
        ``NOT_ATTESTED→VALID`` or ``INVALID→VALID`` flip, the revoke
        shape ``{revoke: true, revoke_reason, version}`` for the
        manual ``VALID→INVALID`` flip)."""
        return self._request("POST", f"/v1/drivers/{driver_id}/refresh-endorsement", payload, headers)

    def get_driver_penalty_summary(self, driver_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/drivers/{driver_id}/penalty-summary`` — the
        digest of the driver's rolling-points standing, the
        endorsement status, the in-window active-and-upheld penalty
        lists, and the per-permit snapshot-vs-live endorsement flag
        pair surfacing the dual-variant disagreement-axis."""
        return self._request("GET", f"/v1/drivers/{driver_id}/penalty-summary", headers=headers)

    # ─── Vehicle and inspection endpoints ──────────────────────────────

    def create_vehicle(self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/vehicles``."""
        return self._request("POST", f"/v1/companies/{company_id}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/vehicles/{vehicle_id}`` — the read includes the
        three derived ``latest_inspection_id``,
        ``latest_inspection_outcome``, and
        ``latest_inspection_valid_until`` pointer fields refreshed by
        each inspection-append's atomic side-effect."""
        return self._request("GET", f"/v1/vehicles/{vehicle_id}", headers=headers)

    def create_inspection(self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/vehicles/{vehicle_id}/inspections`` — the regulator
        appends an inspection certificate.  The parent Vehicle row's
        derived latest-inspection pointers are atomically refreshed by
        the side-effect when the new inspection's ``inspected_at`` is
        the largest across the vehicle's history (tie-break:
        lexicographically larger ``id`` wins)."""
        return self._request("POST", f"/v1/vehicles/{vehicle_id}/inspections", payload, headers)

    def list_inspections(self, vehicle_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """``GET /v1/vehicles/{vehicle_id}/inspections`` — the
        ``inspected_at`` descending, ``id`` descending sorted list with
        the standard pagination and the optional ``outcome`` filter
        narrowing to ``PASSED``-or-``FAILED``-or-``CONDITIONAL``."""
        return self._request("GET", f"/v1/vehicles/{vehicle_id}/inspections", headers=headers, params=params)

    # ─── Route endpoints ───────────────────────────────────────────────

    def create_route(self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/companies/{company_id}/routes`` — the operator's
        new-route application in ``DRAFT``."""
        return self._request("POST", f"/v1/companies/{company_id}/routes", payload, headers)

    def get_route(self, route_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/routes/{route_id}``."""
        return self._request("GET", f"/v1/routes/{route_id}", headers=headers)

    def submit_route(self, route_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/routes/{route_id}/submit`` — the operator's
        ``DRAFT→SUBMITTED`` transition with the
        ``REJECTED→DRAFT→SUBMITTED`` internal-collapse on the reapply
        path mirroring the company's submit cycle."""
        return self._request("POST", f"/v1/routes/{route_id}/submit", payload or {}, headers)

    def approve_route(self, route_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/routes/{route_id}/approve`` — the regulator's
        ``SUBMITTED→APPROVED`` transition.  Reruns the two-time-point
        hazard-class-subset check against the parent company's
        ``hazard_classes_authorized`` as it stands at the approval
        moment, which may have narrowed since the operator's submit if
        the company-side regulator's revoke happened in the gap."""
        return self._request("POST", f"/v1/routes/{route_id}/approve", payload or {}, headers)

    def reject_route(self, route_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/routes/{route_id}/reject`` — the regulator's
        ``SUBMITTED→REJECTED`` transition with the required
        ``rejection_reason`` body field stored on the row for the
        operator's later reapply."""
        return self._request("POST", f"/v1/routes/{route_id}/reject", payload, headers)

    # ─── Permit endpoints ──────────────────────────────────────────────

    def create_permit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits`` — the operator's permit-application
        endpoint creating the new Permit row in ``DRAFT`` with the
        ``application_preview`` sub-object echoing the five-leg validity
        booleans computed at application time."""
        return self._request("POST", "/v1/permits", payload, headers)

    def get_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/permits/{permit_id}`` — the read embeds the
        on-disk snapshot's five-leg booleans verbatim plus the
        on-the-fly ``live_verdict`` and ``live_per_leg`` recomputed at
        the read moment.  The read never writes the snapshot back;
        only ``verify-compliance`` writes."""
        return self._request("GET", f"/v1/permits/{permit_id}", headers=headers)

    def list_permits(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """``GET /v1/permits`` — sorted ``created_at`` descending then
        ``id`` descending, with the optional ``company_id`` and
        ``lifecycle_status`` filters."""
        return self._request("GET", "/v1/permits", headers=headers, params=params)

    def issue_permit(self, permit_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits/{permit_id}/issue`` — the regulator's
        ``DRAFT→ACTIVE`` transition with the atomic wallet-debit by
        the ``annual_renewal_fee`` formula's output and the strict-
        snapshot write of the five validity-leg flags at the issue
        moment."""
        return self._request("POST", f"/v1/permits/{permit_id}/issue", payload or {}, headers)

    def verify_permit_compliance(self, permit_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits/{permit_id}/verify-compliance`` — the
        regulator's compliance-audit endpoint.  The response carries
        the ``transition_fired`` discriminator from the five-element
        enum ``{NO_CHANGE, ACTIVE_TO_SUSPENDED, SUSPENDED_TO_ACTIVE,
        ACTIVE_TO_EXPIRED, SUSPENDED_TO_EXPIRED}`` and the
        ``live_per_leg`` and ``snapshot_per_leg`` five-element boolean
        maps the dual-variant disagreement axis is observable on."""
        return self._request("POST", f"/v1/permits/{permit_id}/verify-compliance", payload or {}, headers)

    def renew_permit(self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits/{permit_id}/renew`` — the operator's
        renewal action.  The optional body fields are
        ``authorized_vehicle_ids``, ``authorized_driver_ids``, and
        ``hazard_classes`` (each replacing the current value with the
        same atomicity as the issue's initial-write), plus the optional
        ``version`` for OCC and the optional ``renew_note`` for the
        audit trail.  The handler extends ``valid_until`` by the
        constant ``PERMIT_DEFAULT_VALIDITY_DAYS`` from the prior
        ``valid_until`` (not from the current clock), debits the wallet
        by the fee, and appends an entry to the ``renewal_history``
        array.  The two renewal-window edges fire
        ``ERR_RENEWAL_TOO_EARLY`` (priority 541) and
        ``ERR_RENEWAL_AFTER_EXPIRY`` (priority 542) respectively."""
        return self._request("POST", f"/v1/permits/{permit_id}/renew", payload, headers)

    def void_issue_permit(self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits/{permit_id}/void-issue`` — the regulator's
        clerical-error reversal action gated to the 24-hour window from
        ``issued_at``.  The wallet is credited by the literal sum
        ``issue_fee_cents + sum(renewal_history[*].fee_cents)``, the
        ``lifecycle_status`` flips to ``VOIDED``, the on-row
        ``voided_at`` and ``void_refunded_cents`` audit fields are
        written, and every still-open child trip is cascade-aborted
        with ``abort_reason = PERMIT_SUSPENDED_CASCADE`` (the on-disk
        enum-economy discriminator value the abort-reason taxonomy of
        §2.8 reuses for the void's cascade flavour).  The required body
        field ``reason_note`` and the optional ``version`` complete the
        request."""
        return self._request("POST", f"/v1/permits/{permit_id}/void-issue", payload, headers)

    # ─── Trip endpoints ────────────────────────────────────────────────

    def create_trip(self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/permits/{permit_id}/trips`` — the operator's
        trip-scheduling under an ACTIVE permit.  The interval check on
        the new trip's ``[scheduled_departure_at,
        scheduled_arrival_at)`` half-open interval against every other
        trip's same-shape interval on the same ``vehicle_id`` across
        every permit is the vehicle-double-booking interval-arithmetic
        rule (the rule-8 overlap-A interval-semantics pin)."""
        return self._request("POST", f"/v1/permits/{permit_id}/trips", payload, headers)

    def get_trip(self, trip_id: str, headers: Dict[str, str]) -> requests.Response:
        """``GET /v1/trips/{trip_id}`` — the read includes the
        derived ``latest_gps_at`` cursor and the
        ``gps_violation_count`` integer the GPS-ingest's atomic
        side-effects maintain."""
        return self._request("GET", f"/v1/trips/{trip_id}", headers=headers)

    def depart_trip(self, trip_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/trips/{trip_id}/depart`` — the
        ``PLANNED→IN_TRANSIT`` transition.  Requires the parent
        permit's ``lifecycle_status`` to still be ``ACTIVE`` at the
        depart moment (a permit suspended in the gap between the
        trip-create and the depart call fires
        ``ERR_PERMIT_NOT_ACTIVE``).  The handler sets
        ``actual_departure_at = now()``."""
        return self._request("POST", f"/v1/trips/{trip_id}/depart", payload or {}, headers)

    def arrive_trip(self, trip_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/trips/{trip_id}/arrive`` — the
        ``IN_TRANSIT→COMPLETED`` transition.  The parent-permit-state
        check is permissive on a ``SUSPENDED`` parent (the suspension
        gates the GPS-stream's new writes but allows the operational
        wind-down attestation to proceed), but the terminal
        ``EXPIRED`` and ``VOIDED`` parent states have already
        cascade-aborted the trip so its own state-machine is in
        ``ABORTED`` by the time of the arrive attempt and the
        generic state-transition error fires."""
        return self._request("POST", f"/v1/trips/{trip_id}/arrive", payload or {}, headers)

    def abort_trip(self, trip_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/trips/{trip_id}/abort`` — the operator's explicit
        abort.  Works on both ``PLANNED`` and ``IN_TRANSIT`` source
        states, transitioning the trip to terminal ``ABORTED`` with
        ``abort_reason = OPERATOR_ABORT`` (the operator-initiated branch's
        discriminator value, distinct from the two cascade-branch
        discriminators that the parent-permit's terminal-or-void
        transitions write).  The required body ``reason_note`` carries
        the operator's audit-trail cause."""
        return self._request("POST", f"/v1/trips/{trip_id}/abort", payload, headers)

    # ─── GPS-stream endpoints ──────────────────────────────────────────

    def create_gps_report(
        self,
        trip_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        idempotency_key: Optional[str] = None,
    ) -> requests.Response:
        """``POST /v1/trips/{trip_id}/gps-reports`` — the operator's
        fleet-tracking back-end's GPS-sample append on the trip's
        append-only stream.  The optional ``Idempotency-Key`` HTTP
        header is the per-trip dedup-slot key — a second arrival on
        the same ``(trip_id, key)`` slot with the same body-hash
        replays the original 201 unchanged; with a different body-hash
        the second arrival is rejected with
        ``ERR_IDEMPOTENCY_KEY_REUSED`` 409.  The handler runs the
        ``gps_violation_classification`` calculation and, in the same
        atomic transaction, inserts zero, one, or two auto-Penalty
        rows (one per fired classifier flag, with the
        ``GPS_VIOLATION_SPEED_POINTS`` or
        ``GPS_VIOLATION_OFF_ROUTE_POINTS`` constant on the
        ``points_value``) attributed to the trip's ``driver_id``, and
        refreshes the parent Trip's derived ``latest_gps_at`` cursor
        (the strict-monotonicity-guaranteed advance) and
        ``gps_violation_count`` integer.

        The five priority-ordered safety-tier checks in the handler are
        the in-window check at 509, the strict-monotonicity check at
        512, and the parent-permit-active gate at 515.  A request that
        fails the in-window check first is reported with
        ``ERR_GPS_OUT_OF_WINDOW`` regardless of whether the other
        checks would also have failed; this is the rule-5
        priority-conflict-C precedence pin.
        """
        merged_headers = dict(headers)
        if idempotency_key is not None:
            merged_headers["Idempotency-Key"] = idempotency_key
        return self._request("POST", f"/v1/trips/{trip_id}/gps-reports", payload, merged_headers)

    def list_gps_reports(self, trip_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """``GET /v1/trips/{trip_id}/gps-reports`` — the sorted-by-
        ``reported_at``-ascending stream view with the standard
        pagination and the optional ``violation_only`` boolean filter
        narrowing to samples whose ``auto_penalty_ids`` is non-empty."""
        return self._request("GET", f"/v1/trips/{trip_id}/gps-reports", headers=headers, params=params)

    # ─── Penalty endpoints ─────────────────────────────────────────────

    def create_penalty(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/penalties`` — the regulator's manual-penalty
        issuance.  The body's ``subject_type`` is one of the three
        values ``DRIVER``, ``COMPANY``, ``VEHICLE`` from the
        penalty-subject taxonomy of PRD §2.8, the ``subject_id``
        resolves to a row of the corresponding entity table (the
        existence check fires the matching
        ``ERR_<ENTITY>_NOT_FOUND`` 404 on a non-resolving id), and
        the ``points_value`` is in the inclusive range
        ``[MANUAL_PENALTY_POINTS_MIN, MANUAL_PENALTY_POINTS_MAX]``.
        Only the ``DRIVER`` case drives the automatic-suspension
        cascade on the subject driver's endorsement and the deferred
        cascade onto the ACTIVE permits listing the driver."""
        return self._request("POST", "/v1/penalties", payload, headers)

    def uphold_penalty(self, penalty_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """``POST /v1/penalties/{penalty_id}/uphold`` — the regulator's
        appeal-uphold compensating action.  The handler flips the
        ``void_status`` from ``ACTIVE`` to the terminal ``UPHELD``,
        writes the ``upheld_at`` and ``upheld_by`` audit fields, and
        prepends the canonical ``"UPHELD-ON-APPEAL: "`` marker to the
        ``reason_note`` field carrying the body's ``uphold_reason``.
        The subject driver's ``current_rolling_points`` cache is
        recomputed (the function's filter excludes ``UPHELD`` rows so
        the upheld penalty's points are subtracted from the rolling
        total), but the driver's ``hazmat_endorsement_status`` is
        NOT auto-flipped back to ``VALID`` even when the
        post-recompute total has fallen below the threshold — the
        regulator's separate ``refresh-endorsement`` attestation is
        the required two-step reinstatement on the upward arm of the
        cascade, per the keep-the-regulator-in-the-loop convention of
        PRD §3.2.

        The appeal-window check at priority 513 is the boundary case
        of ``now() - observed_at <= APPEAL_WINDOW_DAYS`` (closed-right
        on the duration); a strictly-larger duration is rejected with
        ``ERR_APPEAL_WINDOW_CLOSED`` 409.  The same-state-machine
        guard requiring the source ``void_status`` to be ``ACTIVE``
        rejects an idempotent retry on an already-``UPHELD`` row with
        the generic ``ERR_INVALID_STATE_TRANSITION`` 409."""
        return self._request("POST", f"/v1/penalties/{penalty_id}/uphold", payload, headers)

    # ─── Test-mode clock-and-sweep endpoints ──────────────────────────

    def advance_clock(
        self,
        advance_seconds: float,
        run_sweep_after_advance: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """``POST /v1/_clock/advance`` — the deterministic logical-clock
        advance endpoint the test-harness role drives.  The body's
        ``advance_seconds`` is the non-negative number of seconds to
        add to the server-side clock variable, the ``run_sweep_after_advance``
        boolean controls whether the same call also runs the
        cascade-flushing daily sweep, and the response carries the
        pre-advance ``prior_now``, the post-advance ``new_now``, the
        ``advance_seconds_applied`` echo, and the ``sweep_summary``
        sub-object (null when the flag is false, the same structured
        payload the dedicated sweep endpoint returns when it is true)."""
        payload = {
            "advance_seconds": advance_seconds,
            "run_sweep_after_advance": run_sweep_after_advance,
        }
        return self._request(
            "POST",
            "/v1/_clock/advance",
            payload,
            headers if headers is not None else dict(_TEST_HARNESS_HEADERS),
        )

    def run_sweep(self, scope: str = "ALL", headers: Optional[Dict[str, str]] = None) -> requests.Response:
        """``POST /v1/_sweep/run`` — the deterministic daily-compliance
        sweep trigger.  The body's ``scope`` field is one of the three
        enum strings ``"ALL"``, ``"PERMITS_ONLY"``, ``"DRIVERS_ONLY"``
        from the ``SweepScope`` enum.  The response is the structured
        sweep-summary with the ``as_of_now`` echo, the per-permit and
        per-driver transition lists with their respective ``cause``
        and ``status_flip`` discriminators, and the ``n_permits_inspected``
        and ``n_drivers_inspected`` count fields."""
        payload = {"scope": scope}
        return self._request(
            "POST",
            "/v1/_sweep/run",
            payload,
            headers if headers is not None else dict(_TEST_HARNESS_HEADERS),
        )

    # ─── Out-of-band admin affordances ────────────────────────────────

    def admin_reset(self, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        """``POST /v1/_admin/reset`` — the test-harness-only
        in-memory-store wipe between tests.

        The PRD does not name this endpoint explicitly because the
        cross-test isolation contract is a test-harness affordance
        rather than a domain rule, but the orchestrator's overall test
        protocol assumes the implementation under test exposes it for
        the conftest's between-test autoreset fixture to call.  If the
        implementation omits the endpoint, the resulting non-2xx is
        lifted into a clear assertion-error by the
        ``get_success_data`` lenient validator in the conftest's
        fixture wrapper, naming the missing affordance.

        The request body is empty (no parameters — the reset wipes the
        entire in-memory state and re-initialises any singletons the
        implementation maintains).
        """
        return self._request(
            "POST",
            "/v1/_admin/reset",
            {},
            headers if headers is not None else dict(_TEST_HARNESS_HEADERS),
        )

    def admin_wallet_topup(
        self,
        company_id: str,
        amount_cents: int,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """``POST /v1/_admin/wallet-topup`` — the simulated regulator-
        side bookkeeping top-up the test layer uses to seed a company's
        ``wallet_balance_cents`` field before the fee-paying actions
        (permit-issue and permit-renew) can succeed.

        The PRD's §2.11 names the wallet-side top-up as an "out-of-band"
        action without a public API surface ("The wallet's individual
        top-up actions … are not modelled as an in-API operation in
        this scaffold"), but the standard test-suite pattern from the
        same paragraph is "to top up the wallet to a known integer at
        test setup time (the test fixtures' simulated regulator-side
        action)".  The closing-the-loop affordance the test harness
        therefore needs is a write endpoint that the test-harness-role
        principal can hit to set the wallet's value.  The conventional
        name for the endpoint is ``/v1/_admin/wallet-topup`` and the
        conventional body is the ``{company_id, amount_cents}`` pair.

        The request adds ``amount_cents`` to the named company's
        ``wallet_balance_cents`` field atomically (the regulator-side
        accumulator gets a corresponding implicit decrement, but the
        scaffold doesn't model the regulator-ledger as a separate
        entity so the API response carries only the company-side
        post-topup balance).  The response is the standard 200 success
        envelope with the updated company row's
        ``wallet_balance_cents`` and version-bumped audit fields.

        If the implementation under test does not expose this endpoint,
        the fixture's ``get_success_data`` lenient validator raises a
        clear ``Setup step failed`` error pointing at the missing
        affordance.  The fix on the implementation side is the same
        small endpoint the PRD's §2.11 prose conceptually names.
        """
        payload = {"company_id": company_id, "amount_cents": int(amount_cents)}
        return self._request(
            "POST",
            "/v1/_admin/wallet-topup",
            payload,
            headers if headers is not None else dict(_TEST_HARNESS_HEADERS),
        )

    # ─── Catch-all "raw" helpers for the omnibus RBAC matrix test ─────

    def raw_get(self, path: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Hit a verbatim path with a GET — used by the omnibus
        RBAC-matrix and the omnibus error-precedence tests where the
        path is the test-parameter rather than baked into a method
        name."""
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path: str, payload: Any, headers: Dict[str, str]) -> requests.Response:
        """Hit a verbatim path with a POST — used by the omnibus
        RBAC-matrix and the omnibus state-machine-transition-table
        tests where the (method, path) pair is the test-parameter."""
        return self._request("POST", path, payload, headers)

    # ─── Convenience listings of the 37 (method, path) cells ──────────

    # The full canonical table of (method, path-template) pairs the
    # PRD's §4 endpoint reference declares — used by the omnibus
    # RBAC matrix test to walk every cell.  The path templates include
    # the ``{id}`` placeholder strings the test substitutes with the
    # actual resource ids at parametrize-time.
    ENDPOINT_TABLE: List[Dict[str, str]] = [
        {"method": "POST", "path_tpl": "/v1/companies",                                 "name": "create_company"},
        {"method": "GET",  "path_tpl": "/v1/companies/{company_id}",                    "name": "get_company"},
        {"method": "GET",  "path_tpl": "/v1/companies",                                 "name": "list_companies"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/submit",             "name": "submit_company"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/approve",            "name": "approve_company"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/revoke",             "name": "revoke_company"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/drivers",            "name": "create_driver"},
        {"method": "GET",  "path_tpl": "/v1/drivers/{driver_id}",                       "name": "get_driver"},
        {"method": "POST", "path_tpl": "/v1/drivers/{driver_id}/refresh-endorsement",   "name": "refresh_driver_endorsement"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/vehicles",           "name": "create_vehicle"},
        {"method": "GET",  "path_tpl": "/v1/vehicles/{vehicle_id}",                     "name": "get_vehicle"},
        {"method": "POST", "path_tpl": "/v1/vehicles/{vehicle_id}/inspections",         "name": "create_inspection"},
        {"method": "GET",  "path_tpl": "/v1/vehicles/{vehicle_id}/inspections",         "name": "list_inspections"},
        {"method": "POST", "path_tpl": "/v1/companies/{company_id}/routes",             "name": "create_route"},
        {"method": "GET",  "path_tpl": "/v1/routes/{route_id}",                         "name": "get_route"},
        {"method": "POST", "path_tpl": "/v1/routes/{route_id}/submit",                  "name": "submit_route"},
        {"method": "POST", "path_tpl": "/v1/routes/{route_id}/approve",                 "name": "approve_route"},
        {"method": "POST", "path_tpl": "/v1/routes/{route_id}/reject",                  "name": "reject_route"},
        {"method": "POST", "path_tpl": "/v1/permits",                                   "name": "create_permit"},
        {"method": "GET",  "path_tpl": "/v1/permits/{permit_id}",                       "name": "get_permit"},
        {"method": "GET",  "path_tpl": "/v1/permits",                                   "name": "list_permits"},
        {"method": "POST", "path_tpl": "/v1/permits/{permit_id}/issue",                 "name": "issue_permit"},
        {"method": "POST", "path_tpl": "/v1/permits/{permit_id}/verify-compliance",     "name": "verify_permit_compliance"},
        {"method": "POST", "path_tpl": "/v1/permits/{permit_id}/renew",                 "name": "renew_permit"},
        {"method": "POST", "path_tpl": "/v1/permits/{permit_id}/void-issue",            "name": "void_issue_permit"},
        {"method": "POST", "path_tpl": "/v1/permits/{permit_id}/trips",                 "name": "create_trip"},
        {"method": "GET",  "path_tpl": "/v1/trips/{trip_id}",                           "name": "get_trip"},
        {"method": "POST", "path_tpl": "/v1/trips/{trip_id}/depart",                    "name": "depart_trip"},
        {"method": "POST", "path_tpl": "/v1/trips/{trip_id}/arrive",                    "name": "arrive_trip"},
        {"method": "POST", "path_tpl": "/v1/trips/{trip_id}/abort",                     "name": "abort_trip"},
        {"method": "POST", "path_tpl": "/v1/trips/{trip_id}/gps-reports",               "name": "create_gps_report"},
        {"method": "GET",  "path_tpl": "/v1/trips/{trip_id}/gps-reports",               "name": "list_gps_reports"},
        {"method": "POST", "path_tpl": "/v1/penalties",                                 "name": "create_penalty"},
        {"method": "POST", "path_tpl": "/v1/penalties/{penalty_id}/uphold",             "name": "uphold_penalty"},
        {"method": "GET",  "path_tpl": "/v1/drivers/{driver_id}/penalty-summary",       "name": "get_driver_penalty_summary"},
        {"method": "POST", "path_tpl": "/v1/_clock/advance",                            "name": "advance_clock"},
        {"method": "POST", "path_tpl": "/v1/_sweep/run",                                "name": "run_sweep"},
    ]


#: The module-level singleton the conftest.py's ``api`` pytest-fixture
#: hands out as the session-scoped client.  The base URL is read from
#: the ``API_BASE_URL`` environment variable that the local-runner
#: framework's outer harness sets before the pytest subprocess starts.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
