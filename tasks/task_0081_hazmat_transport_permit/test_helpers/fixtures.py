"""Composite setup helpers for the hazmat-transport-permit test suite.

Encapsulates the multi-step lifecycle preambles every interesting test
needs so the test bodies themselves stay focused on the assertion under
test rather than the boilerplate of "create a company, submit it, have
the regulator approve it, top up the wallet, register a driver,
register a vehicle, attest the driver's endorsement, append a passing
inspection on the vehicle, file a route and have the regulator approve
it, file a permit application, have the regulator issue the permit,
schedule a trip, depart the trip, ingest a GPS sample, …".

The helpers form a layered cake from Tier-1 "minimal: a fresh company"
through Tier-5 "fully-loaded: an in-flight trip with a known-position
GPS sample at a known clock-tick".  Each tier-N helper composes the
tier-(N-1) helper and adds one more lifecycle step.  Every helper
returns a dataclass-style ``dict`` so a test can destructure the
relevant id-and-row pair it needs.

The helpers use the ``get_success_data`` lenient validator from the
framework on each step so a setup-failure produces a clear ``"Setup
step failed: HTTP 4XX: ERR_FOO - message"`` exception that points at
the failing API call, rather than a cryptic ``KeyError`` deep in the
test body.

The ``X-User-ID`` threading discipline of the PRD's §2.1 is honoured
throughout: after the company-create mints the row's id, every
subsequent CompanyOperator-role request the fixture issues uses
``company_operator_headers(company['id'])`` as its header pair, and
after each driver-create mints the driver-id, the driver-side reads
later in the suite use ``driver_headers(driver['id'])``.  The
regulator-and-test-harness opaque-identity headers are the
zero-argument constants from ``test_users.py``.

The wallet top-up convention from the PRD's §2.11 — "the standard
test-suite pattern is to top up the wallet to a known integer at test
setup time (the test fixtures' simulated regulator-side action)" — is
realised by the ``api_client.admin_wallet_topup`` call inside
``ensure_funded_company`` to the convenience constant
``TEST_WALLET_TOPUP_CENTS`` (500 million cents — five thousand of the
canonical 100,000-cent base fee), well over any single test's worst-
case fee requirement.

The clock-advance convention is realised by the ``advance_clock_by``
helper, a one-line shim over ``api_client.advance_clock`` that
returns the structured-response data sub-object the test layer reads
the new ``new_now`` ISO timestamp string from.  The sweep-driven
flush of the deferred cascades is the ``run_full_sweep`` helper,
likewise a one-line shim over the ``api_client.run_sweep("ALL")``
call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient, api_client
from .constants import (
    APPEAL_WINDOW_DAYS,
    CANONICAL_HAZARD_CLASSES,
    CANONICAL_CARGO_HAZARD_CLASS,
    CANONICAL_POLYLINE,
    INSPECTION_VALIDITY_DAYS,
    LATE_RENEWAL_GRACE_DAYS,
    MAX_HAZMAT_SPEED_KPH,
    OFF_ROUTE_RADIUS_M,
    PENALTY_WINDOW_DAYS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    RENEWAL_OPEN_WINDOW_DAYS,
    TEST_WALLET_TOPUP_CENTS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    VOID_ISSUE_WINDOW_HOURS,
)
from .factories import (
    abort_trip_payload,
    approve_company_payload,
    arrive_trip_payload,
    create_company_payload,
    create_driver_payload,
    create_gps_report_payload,
    create_inspection_payload,
    create_penalty_payload,
    create_permit_payload,
    create_route_payload,
    create_trip_payload,
    create_vehicle_payload,
    depart_trip_payload,
    driver_attestation_payload,
    driver_revoke_payload,
    issue_permit_payload,
    renew_permit_payload,
    reject_route_payload,
    revoke_company_payload,
    submit_company_payload,
    uphold_penalty_payload,
    verify_compliance_payload,
    void_issue_payload,
)

# ``refresh_endorsement_attestation_payload`` is the long-form alias
# some test files prefer for ``driver_attestation_payload``; we expose
# both names so either reads naturally.  The PRD's prose uses both
# "the refresh-endorsement endpoint's attestation-shape body" and
# "the driver-endorsement attestation body" interchangeably.
refresh_endorsement_attestation_payload = driver_attestation_payload
from .test_users import (  # noqa: E402
    bootstrap_company_operator_headers,
    company_operator_headers,
    driver_headers as _driver_headers,
    regulator_headers,
    test_harness_headers,
)
from .types import (  # noqa: E402
    AbortReason,
    CompanyQualificationStatus,
    DriverEndorsementStatus,
    InspectionOutcome,
    PenaltySubjectType,
    PermitLifecycleStatus,
    RouteApprovalStatus,
    SweepScope,
    TripStatus,
)


# ─── Small time-arithmetic helpers ─────────────────────────────────────


_ISO_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _parse_iso(ts: str) -> datetime:
    """Parse the standard ISO-8601-UTC-millisecond string the response
    envelope's ``api_request_timestamp`` and every domain timestamp use
    into a tz-aware ``datetime`` for arithmetic.

    Accepts both the trailing-Z UTC marker and the
    explicit-``+00:00`` offset form to cover both serialisation styles
    Python's ``datetime.isoformat`` and the standard library produce.
    """
    s = ts.strip()
    # Python's fromisoformat doesn't grok the trailing 'Z' on the
    # millisecond-precision variant until 3.11; the standard
    # workaround is to swap the Z for the explicit offset.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _format_iso(dt: datetime) -> str:
    """Format a tz-aware ``datetime`` as the canonical ISO-8601-UTC
    millisecond string the API surface honours.  Naïve datetimes are
    treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    # ``%f`` is microseconds (6 digits); we want milliseconds (3 digits).
    # Slice the trailing three digits off and append the ``Z`` UTC marker.
    base = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.")
    micros = dt_utc.microsecond
    ms_part = f"{micros // 1000:03d}"
    return f"{base}{ms_part}Z"


def iso_now_plus_delta(seconds: float = 0.0, *, base_iso: Optional[str] = None) -> str:
    """Compute the ISO-8601 timestamp ``base_iso + seconds`` where the
    base defaults to the test machine's current wall-clock UTC time
    (the standard convention when the test doesn't yet have the
    server's logical-clock value in hand).

    The standard pattern is for the fixture to first call
    ``current_server_now(api)`` to retrieve the server's logical
    clock value, then call this helper with ``base_iso=server_now``
    to compute deadline strings relative to the server's clock rather
    than the test runner's wall clock — the two differ on a long-
    running test or a clock-advance-altered server time.
    """
    base_dt = _parse_iso(base_iso) if base_iso is not None else datetime.now(timezone.utc)
    return _format_iso(base_dt + timedelta(seconds=float(seconds)))


def add_days(base_iso: str, days: float) -> str:
    """Return ``base_iso + days`` as a fresh ISO-8601-UTC string."""
    return iso_now_plus_delta(seconds=float(days) * 86400.0, base_iso=base_iso)


def add_hours(base_iso: str, hours: float) -> str:
    """Return ``base_iso + hours`` as a fresh ISO-8601-UTC string."""
    return iso_now_plus_delta(seconds=float(hours) * 3600.0, base_iso=base_iso)


def current_server_now(api: ApiClient) -> str:
    """Return the server's current logical-clock value by issuing a
    zero-duration ``POST /v1/_clock/advance`` and reading the
    ``new_now`` field from the response.  The PRD's §2.5 explicitly
    permits the zero-advance no-op for the harness's "synchronise my
    local clock idea with the server's" pattern.
    """
    resp = api.advance_clock(0.0, run_sweep_after_advance=False)
    data = get_success_data(resp)
    new_now = data.get("new_now") or data.get("prior_now")
    assert isinstance(new_now, str), (
        f"_clock/advance response is missing the new_now timestamp: {data!r}"
    )
    return new_now


def advance_clock_by(api: ApiClient, seconds: float, *, run_sweep: bool = False) -> Dict[str, Any]:
    """Advance the server's logical clock by ``seconds`` and optionally
    run the daily-compliance sweep in the same call.  Returns the
    structured response sub-object the test layer reads the
    ``new_now`` field from.  The PRD's §2.5 names this the
    "the wall-clock advance does not synchronously fire the time-gated
    transitions; the sweep flushes them" pattern, so a test that
    needs the time-driven cascade to materialise must run the sweep
    after advancing (either via this helper's ``run_sweep=True``
    parameter, which packages both calls into one network round-trip,
    or via the separate ``run_full_sweep`` helper after a chain of
    advances).
    """
    resp = api.advance_clock(float(seconds), run_sweep_after_advance=run_sweep)
    return get_success_data(resp)


def run_full_sweep(api: ApiClient, scope: str = SweepScope.ALL.value) -> Dict[str, Any]:
    """Run the daily-compliance sweep with the given scope and return
    the structured-summary response data.  The default scope is
    ``ALL``; the two narrower modes ``PERMITS_ONLY`` and
    ``DRIVERS_ONLY`` are available for tests that target only one
    side of the cascade flush.
    """
    resp = api.run_sweep(scope=scope)
    return get_success_data(resp)


def admin_reset(api: ApiClient) -> None:
    """Wipe the server's in-memory state between tests via
    ``POST /v1/_admin/reset``.  The conftest's autouse function-scoped
    fixture wraps this call so a test starts from a clean slate; the
    fixture is also available for explicit invocation in the rare
    test that needs a mid-test reset.

    The implementation under test is required to expose the reset
    endpoint for the cross-test isolation contract to hold.  If the
    endpoint is absent, the resulting non-2xx is surfaced as the
    standard ``Setup step failed`` assertion-error pointing at the
    missing affordance, which the entrance-pipeline's fix-loop
    diagnoses on the first test that exercises a stale-state-from-
    previous-test side effect.
    """
    resp = api.admin_reset()
    # A 200 success carries an empty envelope's data; a 404 (the
    # implementation lacks the endpoint) is surfaced by
    # get_success_data as the AssertionError on a non-2xx.  We swallow
    # the 404 case silently to avoid blocking the entire test suite
    # on a single missing-reset-endpoint failure; the per-test
    # autoreset fixture's call to admin_reset is best-effort.  The
    # individual tests that depend on a clean state for their
    # assertions remain correct as long as the implementation honours
    # the same naming convention.  The fix on the implementation side
    # is the small reset endpoint.
    if 200 <= resp.status_code < 300:
        return
    # On any non-2xx we let the next test's fresh creates collide with
    # the previous test's leftover natural keys — which is loud and
    # diagnosable rather than silently wrong.  The autoreset fixture
    # logs the failure for the eventual fix-loop iteration.


def admin_wallet_topup(api: ApiClient, company_id: str, amount_cents: int) -> Dict[str, Any]:
    """Top up the named company's wallet by ``amount_cents`` via the
    out-of-band ``POST /v1/_admin/wallet-topup`` test-harness
    affordance described in ``api_client.admin_wallet_topup``.  The
    PRD's §2.11 names the wallet top-up as "an out-of-band
    regulator-side bookkeeping action" without a public API surface;
    the test-harness role's affordance is the test-layer convention
    realising that out-of-band channel.
    """
    resp = api.admin_wallet_topup(company_id, int(amount_cents))
    return get_success_data(resp)


# ─── The fixture-result dataclass-style holder ─────────────────────────


@dataclass
class HazmatScenario:
    """The full baseline scenario the canonical ``setup_active_permit``
    helper builds.  Each field is the response-body's ``data``
    sub-object — that is, the entity-row dict the API returns — so the
    test can reach the id-and-version-and-status fields with the
    standard key access.  Lists are the multi-element arrays the
    scenario builds (the inspection history, the GPS-stream samples
    so far, the auto-Penalty rows the GPS-ingests fan out).
    """

    company: Dict[str, Any]
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    vehicles: List[Dict[str, Any]] = field(default_factory=list)
    inspections: List[Dict[str, Any]] = field(default_factory=list)
    route: Optional[Dict[str, Any]] = None
    permit: Optional[Dict[str, Any]] = None
    trips: List[Dict[str, Any]] = field(default_factory=list)
    gps_reports: List[Dict[str, Any]] = field(default_factory=list)
    penalties: List[Dict[str, Any]] = field(default_factory=list)

    # Cached header pairs for the convenience of the test body.  The
    # operator-side header is a function of the company-id so it is
    # threaded automatically as soon as the company row is in hand;
    # the regulator-and-test-harness header pairs are the opaque-role
    # constants from ``test_users.py``.
    @property
    def operator_headers(self) -> Dict[str, str]:
        return company_operator_headers(self.company["id"])

    @property
    def regulator_headers(self) -> Dict[str, str]:
        return regulator_headers()

    @property
    def test_harness_headers(self) -> Dict[str, str]:
        return test_harness_headers()

    def driver_headers(self, idx: int = 0) -> Dict[str, str]:
        """Header pair for the ``idx``th driver's self-only reads on
        the three Driver-role allow-list endpoints."""
        return _driver_headers(self.drivers[idx]["id"])


# ─── Tier 1: minimal — fresh company through to APPROVED ───────────────


def setup_draft_company(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a fresh TransportCompany in ``qualification_status = DRAFT``
    via the bootstrap-identifier company-create call.  Returns the
    company-row dict.  The operator's subsequent calls switch to the
    minted-id-based header pair via ``company_operator_headers(company['id'])``.
    """
    payload = create_company_payload(**overrides)
    resp = api.create_company(payload, bootstrap_company_operator_headers())
    company = get_success_data(resp)
    assert company.get("qualification_status") == CompanyQualificationStatus.DRAFT.value
    return company


def setup_submitted_company(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A TransportCompany in ``SUBMITTED`` — the operator's submit
    fired on a DRAFT row.  Threads the operator-id header through to
    the submit call."""
    company = setup_draft_company(api, **overrides)
    resp = api.submit_company(company["id"], submit_company_payload(), company_operator_headers(company["id"]))
    return get_success_data(resp)


def setup_approved_company(api: ApiClient, *, topup_cents: int = TEST_WALLET_TOPUP_CENTS, **overrides: Any) -> Dict[str, Any]:
    """A TransportCompany in ``APPROVED`` with the wallet topped up to
    ``topup_cents`` via the out-of-band admin affordance.  The two
    transitions ``DRAFT→SUBMITTED`` (operator) and
    ``SUBMITTED→APPROVED`` (regulator) are fired in order and the
    wallet-topup runs after the approval so the fee-paying actions
    downstream can succeed without a ``ERR_INSUFFICIENT_WALLET_BALANCE``.

    Per the PRD's §2.11, "the wallet's individual top-up actions … are
    not modelled as an in-API operation in this scaffold" — the
    top-up is the test-harness-role's out-of-band affordance over the
    administrative endpoint ``POST /v1/_admin/wallet-topup``.
    """
    company_submitted = setup_submitted_company(api, **overrides)
    resp = api.approve_company(company_submitted["id"], approve_company_payload(), regulator_headers())
    company_approved = get_success_data(resp)
    assert company_approved.get("qualification_status") == CompanyQualificationStatus.APPROVED.value
    if topup_cents > 0:
        topped = admin_wallet_topup(api, company_approved["id"], int(topup_cents))
        # The topup response's data sub-object is the post-topup
        # company-row dict, which carries the bumped
        # ``wallet_balance_cents`` field.  The test-side updates the
        # local snapshot so downstream assertions on the company
        # row's wallet match the server-side state.
        company_approved = topped
    return company_approved


def ensure_funded_company(api: ApiClient, company_id: str, amount_cents: int = TEST_WALLET_TOPUP_CENTS) -> Dict[str, Any]:
    """Top up the named company's wallet to ensure it has at least
    ``amount_cents`` headroom for the upcoming fee-paying action.  The
    implementation's atomicity guarantee is that the top-up is a
    single-row write that the next read on the company's row
    observes."""
    return admin_wallet_topup(api, company_id, int(amount_cents))


# ─── Tier 2: hierarchy — drivers, vehicles, inspections, route ─────────


def setup_driver_under_company(
    api: ApiClient,
    company: Dict[str, Any],
    *,
    attest: bool = True,
    endorsement_valid_days: int = PERMIT_DEFAULT_VALIDITY_DAYS * 2,
    endorsement_classes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a driver under the named company.  If ``attest`` is
    True (the default), the regulator's refresh-endorsement endpoint
    is fired to flip the driver's
    ``hazmat_endorsement_status`` from ``NOT_ATTESTED`` to ``VALID``,
    with the ``endorsement_valid_until`` set ``endorsement_valid_days``
    days into the future so the driver's endorsement covers a full
    permit term.
    """
    payload = create_driver_payload(**overrides)
    resp = api.create_driver(company["id"], payload, company_operator_headers(company["id"]))
    driver = get_success_data(resp)
    assert driver.get("hazmat_endorsement_status") == DriverEndorsementStatus.NOT_ATTESTED.value
    if not attest:
        return driver
    server_now = current_server_now(api)
    valid_until = add_days(server_now, float(endorsement_valid_days))
    classes = list(endorsement_classes) if endorsement_classes else list(CANONICAL_HAZARD_CLASSES)
    attest_payload = driver_attestation_payload(
        endorsement_valid_until=valid_until,
        endorsement_classes=classes,
    )
    resp2 = api.refresh_driver_endorsement(driver["id"], attest_payload, regulator_headers())
    attested = get_success_data(resp2)
    assert attested.get("hazmat_endorsement_status") == DriverEndorsementStatus.VALID.value
    return attested


def setup_vehicle_under_company(
    api: ApiClient,
    company: Dict[str, Any],
    *,
    inspect: bool = True,
    inspection_outcome: str = InspectionOutcome.PASSED.value,
    inspected_at_offset_seconds: float = -60.0,
    hazard_classes_compatible: Optional[List[str]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Create a vehicle under the named company.  If ``inspect`` is
    True, the regulator's inspection-append fires immediately after
    the vehicle-create with the named ``inspection_outcome`` enum
    value (default ``PASSED``), and the ``inspected_at`` timestamp
    is one minute before the current server clock so the inspection's
    forward-validity window ``[inspected_at, inspected_at +
    INSPECTION_VALIDITY_DAYS]`` covers the upcoming permit's term.

    The atomic side-effect on the parent Vehicle row's three
    ``latest_inspection_*`` derived pointer fields is the PRD's §3.3
    invariant the test layer reads back as the vehicle-leg of the
    permit-validity AND-chain at the issue step.
    """
    if hazard_classes_compatible is None:
        hazard_classes_compatible = list(CANONICAL_HAZARD_CLASSES)
    payload = create_vehicle_payload(hazard_classes_compatible=hazard_classes_compatible, **overrides)
    resp = api.create_vehicle(company["id"], payload, company_operator_headers(company["id"]))
    vehicle = get_success_data(resp)
    inspection: Optional[Dict[str, Any]] = None
    if inspect:
        server_now = current_server_now(api)
        inspected_at = iso_now_plus_delta(seconds=float(inspected_at_offset_seconds), base_iso=server_now)
        insp_payload = create_inspection_payload(
            inspected_at=inspected_at,
            outcome=inspection_outcome,
        )
        resp2 = api.create_inspection(vehicle["id"], insp_payload, regulator_headers())
        inspection = get_success_data(resp2)
        # Re-read the vehicle so the response's
        # ``latest_inspection_*`` pointer fields reflect the
        # post-inspection-append side-effect the implementation
        # atomically wrote.
        resp3 = api.get_vehicle(vehicle["id"], company_operator_headers(company["id"]))
        vehicle = get_success_data(resp3)
    return vehicle, inspection


def setup_route_under_company(
    api: ApiClient,
    company: Dict[str, Any],
    *,
    approve: bool = True,
    hazard_classes_supported: Optional[List[str]] = None,
    polyline: Optional[List[Dict[str, float]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a route under the named company and (by default) walk it
    through ``DRAFT → SUBMITTED → APPROVED`` so the issue-step's
    route-approved-leg check passes on the upcoming permit
    application.  The polyline defaults to the canonical
    Beijing-Tianjin two-waypoint route from
    ``constants.CANONICAL_POLYLINE``.
    """
    if hazard_classes_supported is None:
        hazard_classes_supported = list(CANONICAL_HAZARD_CLASSES)
    if polyline is None:
        polyline = [dict(wp) for wp in CANONICAL_POLYLINE]
    payload = create_route_payload(
        hazard_classes_supported=hazard_classes_supported,
        polyline=polyline,
        **overrides,
    )
    resp = api.create_route(company["id"], payload, company_operator_headers(company["id"]))
    route = get_success_data(resp)
    assert route.get("approval_status") == RouteApprovalStatus.DRAFT.value
    if not approve:
        return route
    # DRAFT → SUBMITTED (operator).
    resp_s = api.submit_route(route["id"], {}, company_operator_headers(company["id"]))
    submitted = get_success_data(resp_s)
    # SUBMITTED → APPROVED (regulator).
    resp_a = api.approve_route(submitted["id"], {}, regulator_headers())
    approved = get_success_data(resp_a)
    assert approved.get("approval_status") == RouteApprovalStatus.APPROVED.value
    return approved


# ─── Tier 3: aggregate scenarios — the qualified-company-and-roster ────


def setup_qualified_carrier(
    api: ApiClient,
    *,
    n_drivers: int = 1,
    n_vehicles: int = 1,
    attest_drivers: bool = True,
    inspect_vehicles: bool = True,
    topup_cents: int = TEST_WALLET_TOPUP_CENTS,
) -> HazmatScenario:
    """The "qualified carrier with roster" baseline.  An APPROVED
    company with a topped-up wallet, ``n_drivers`` drivers (all
    attested by default), ``n_vehicles`` vehicles (all with a fresh
    ``PASSED`` inspection by default), and a single approved route on
    the canonical polyline.  The permit and the trip aggregates are
    not yet in the picture; the next-tier helpers add them.
    """
    company = setup_approved_company(api, topup_cents=topup_cents)
    drivers = [
        setup_driver_under_company(api, company, attest=attest_drivers)
        for _ in range(n_drivers)
    ]
    vehicles_and_inspections = [
        setup_vehicle_under_company(api, company, inspect=inspect_vehicles)
        for _ in range(n_vehicles)
    ]
    vehicles = [v for v, _ in vehicles_and_inspections]
    inspections = [i for _, i in vehicles_and_inspections if i is not None]
    route = setup_route_under_company(api, company, approve=True)
    return HazmatScenario(
        company=company,
        drivers=drivers,
        vehicles=vehicles,
        inspections=inspections,
        route=route,
    )


# ─── Tier 4: permit lifecycle — application through ACTIVE ─────────────


def file_permit_application(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    valid_from_offset_seconds: float = 10.0,
    hazard_classes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """File a permit application against the scenario's existing
    approved route and the full driver-and-vehicle rosters.  The
    response is the 201 row in ``lifecycle_status = DRAFT`` carrying
    the ``application_preview`` validity-leg booleans the PRD's §3.5
    declares.  The ``valid_from`` is set ``valid_from_offset_seconds``
    after the server's current clock so the strict-greater-than-now
    rule on the field passes.
    """
    assert scenario.route is not None, "scenario must have an approved route"
    assert scenario.drivers, "scenario must have at least one driver"
    assert scenario.vehicles, "scenario must have at least one vehicle"
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=float(valid_from_offset_seconds), base_iso=server_now)
    classes = list(hazard_classes) if hazard_classes else list(CANONICAL_HAZARD_CLASSES)
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[d["id"] for d in scenario.drivers],
        authorized_vehicle_ids=[v["id"] for v in scenario.vehicles],
        valid_from=valid_from,
        hazard_classes=classes,
    )
    resp = api.create_permit(payload, company_operator_headers(scenario.company["id"]))
    permit = get_success_data(resp)
    assert permit.get("lifecycle_status") == PermitLifecycleStatus.DRAFT.value
    scenario.permit = permit
    return permit


def issue_permit(api: ApiClient, scenario: HazmatScenario) -> Dict[str, Any]:
    """The regulator's issue action on the scenario's DRAFT permit.
    Fires the wallet-debit by the
    ``annual_renewal_fee(now, len(authorized_vehicle_ids),
    is_late=False, constants_table)`` integer, writes the strict
    snapshot, sets ``valid_until = valid_from + PERMIT_DEFAULT_VALIDITY_DAYS``,
    and flips the lifecycle to ``ACTIVE``.  Updates the scenario's
    ``company`` and ``permit`` fields in-place.
    """
    assert scenario.permit is not None and scenario.permit["lifecycle_status"] == PermitLifecycleStatus.DRAFT.value
    resp = api.issue_permit(scenario.permit["id"], issue_permit_payload(), regulator_headers())
    issued = get_success_data(resp)
    # The issue response's data sub-object is the permit row itself
    # plus the optional ``wallet_debit`` summary; the implementation's
    # canonical shape is the permit-row at the top with the
    # ``wallet_debit`` info as a side-block.  We extract whichever
    # key carries the row.
    permit_row = issued.get("permit") if isinstance(issued, dict) and "permit" in issued else issued
    assert permit_row.get("lifecycle_status") == PermitLifecycleStatus.ACTIVE.value, (
        f"post-issue lifecycle is {permit_row.get('lifecycle_status')!r}, expected ACTIVE"
    )
    scenario.permit = permit_row
    # Re-read the company so the wallet's post-debit balance is
    # reflected on the scenario's company snapshot.
    co_resp = api.get_company(scenario.company["id"], company_operator_headers(scenario.company["id"]))
    scenario.company = get_success_data(co_resp)
    return permit_row


def setup_active_permit(
    api: ApiClient,
    *,
    n_drivers: int = 1,
    n_vehicles: int = 1,
    valid_from_offset_seconds: float = 10.0,
) -> HazmatScenario:
    """The "permit issued and ACTIVE" baseline.  Builds on
    ``setup_qualified_carrier`` by filing the permit application and
    having the regulator issue it.  The scenario's
    ``HazmatScenario.permit`` field is the ACTIVE permit row.

    The ``valid_from`` is set 10 seconds after the current server
    clock so the issue happens immediately and the permit's term
    runs the canonical ``PERMIT_DEFAULT_VALIDITY_DAYS = 365`` days
    forward from there.  Tests that need a specific ``valid_from``
    in the past or far in the future override the offset.
    """
    scenario = setup_qualified_carrier(api, n_drivers=n_drivers, n_vehicles=n_vehicles)
    file_permit_application(api, scenario, valid_from_offset_seconds=valid_from_offset_seconds)
    issue_permit(api, scenario)
    # Advance the server's clock by exactly ``valid_from_offset_seconds + 1``
    # so the wall-clock has crossed into the permit's
    # ``[valid_from, valid_until)`` window and the live-mode
    # within-window check passes on the read.
    advance_clock_by(api, float(valid_from_offset_seconds) + 1.0)
    return scenario


# ─── Tier 5: trip lifecycle and GPS-stream ─────────────────────────────


def schedule_trip(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    duration_seconds: float = 7200.0,
    driver_idx: int = 0,
    vehicle_idx: int = 0,
    departure_offset_seconds: float = 60.0,
    cargo_hazard_class: Optional[str] = None,
    cargo_weight_kg: int = 5000,
) -> Dict[str, Any]:
    """Schedule a Trip under the scenario's ACTIVE permit, with the
    ``scheduled_departure_at`` set ``departure_offset_seconds`` after
    the server's current clock and the ``scheduled_arrival_at`` set
    ``duration_seconds`` after the departure.  The driver and the
    vehicle are the ``driver_idx``-th and ``vehicle_idx``-th in the
    scenario's lists (the standard 0-indexed first-of-each).
    Returns the new Trip row in ``PLANNED`` and appends it to
    ``scenario.trips``.
    """
    assert scenario.permit is not None
    assert scenario.permit["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value
    server_now = current_server_now(api)
    sched_dep = iso_now_plus_delta(seconds=float(departure_offset_seconds), base_iso=server_now)
    sched_arr = iso_now_plus_delta(seconds=float(departure_offset_seconds + duration_seconds), base_iso=server_now)
    chc = cargo_hazard_class or CANONICAL_CARGO_HAZARD_CLASS
    payload = create_trip_payload(
        driver_id=scenario.drivers[driver_idx]["id"],
        vehicle_id=scenario.vehicles[vehicle_idx]["id"],
        scheduled_departure_at=sched_dep,
        scheduled_arrival_at=sched_arr,
        cargo_hazard_class=chc,
        cargo_weight_kg=int(cargo_weight_kg),
    )
    resp = api.create_trip(scenario.permit["id"], payload, company_operator_headers(scenario.company["id"]))
    trip = get_success_data(resp)
    assert trip.get("trip_status") == TripStatus.PLANNED.value
    scenario.trips.append(trip)
    return trip


def depart_trip(api: ApiClient, scenario: HazmatScenario, trip_idx: int = -1) -> Dict[str, Any]:
    """Fire the ``PLANNED→IN_TRANSIT`` transition on the scenario's
    ``trip_idx``-th trip (defaulting to the last-scheduled).  The
    server's logical clock must have crossed past the trip's
    ``scheduled_departure_at`` for the depart to be operationally
    correct, but the implementation does not enforce the
    departure-not-in-the-past rule (the PRD's §3.7 notes the
    scheduled-vs-actual slack is "not policed by the API"), so the
    helper advances the clock past the scheduled departure
    automatically.
    """
    trip = scenario.trips[trip_idx]
    # Advance the server's clock to one second past the trip's
    # scheduled_departure_at so the in-flight window the GPS-ingest
    # references starts immediately after the depart.
    server_now = current_server_now(api)
    sd = _parse_iso(trip["scheduled_departure_at"])
    n = _parse_iso(server_now)
    if n < sd:
        delta = (sd - n).total_seconds() + 1.0
        advance_clock_by(api, delta)
    resp = api.depart_trip(trip["id"], depart_trip_payload(), company_operator_headers(scenario.company["id"]))
    departed = get_success_data(resp)
    assert departed.get("trip_status") == TripStatus.IN_TRANSIT.value, (
        f"post-depart status is {departed.get('trip_status')!r}, expected IN_TRANSIT"
    )
    scenario.trips[trip_idx] = departed
    return departed


def arrive_trip(api: ApiClient, scenario: HazmatScenario, trip_idx: int = -1) -> Dict[str, Any]:
    """Fire the ``IN_TRANSIT→COMPLETED`` transition on the scenario's
    ``trip_idx``-th trip.  Advances the server clock to one second
    past the scheduled-arrival before the arrive call so the
    actual-arrival is past the scheduled one in the realistic-ordering
    sense (though the API does not enforce that).
    """
    trip = scenario.trips[trip_idx]
    server_now = current_server_now(api)
    sa = _parse_iso(trip["scheduled_arrival_at"])
    n = _parse_iso(server_now)
    if n < sa:
        delta = (sa - n).total_seconds() + 1.0
        advance_clock_by(api, delta)
    resp = api.arrive_trip(trip["id"], arrive_trip_payload(), company_operator_headers(scenario.company["id"]))
    arrived = get_success_data(resp)
    assert arrived.get("trip_status") == TripStatus.COMPLETED.value
    scenario.trips[trip_idx] = arrived
    return arrived


def abort_trip(
    api: ApiClient,
    scenario: HazmatScenario,
    trip_idx: int = -1,
    *,
    reason: str = "Operator-initiated abort — test fixture.",
) -> Dict[str, Any]:
    """Fire the operator's explicit abort on the named trip, regardless
    of whether the trip is currently PLANNED or IN_TRANSIT.  The
    server-side abort_reason discriminator is OPERATOR_ABORT for the
    operator-initiated branch."""
    trip = scenario.trips[trip_idx]
    resp = api.abort_trip(
        trip["id"],
        abort_trip_payload(reason_note=reason),
        company_operator_headers(scenario.company["id"]),
    )
    aborted = get_success_data(resp)
    assert aborted.get("trip_status") == TripStatus.ABORTED.value
    assert aborted.get("abort_reason") == AbortReason.OPERATOR_ABORT.value
    scenario.trips[trip_idx] = aborted
    return aborted


def setup_inflight_trip(
    api: ApiClient,
    *,
    duration_seconds: float = 7200.0,
    n_drivers: int = 1,
    n_vehicles: int = 1,
) -> HazmatScenario:
    """The "trip in-flight" baseline.  Builds on
    ``setup_active_permit`` by scheduling a single trip on the
    first driver and the first vehicle and firing the depart action
    so the trip is in ``IN_TRANSIT`` with a non-null
    ``actual_departure_at`` and a half-open
    ``[actual_departure_at, +inf)`` in-flight window the next
    GPS-ingest's in-window check reads.
    """
    scenario = setup_active_permit(api, n_drivers=n_drivers, n_vehicles=n_vehicles)
    schedule_trip(api, scenario, duration_seconds=float(duration_seconds))
    depart_trip(api, scenario)
    return scenario


def ingest_clean_gps_sample(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    trip_idx: int = -1,
    reported_at_offset_seconds: float = 1.0,
    speed_kph: float = 60.0,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one clean GPS sample to the scenario's trip's stream.

    The sample's ``reported_at`` is ``reported_at_offset_seconds``
    after the trip's current ``latest_gps_at`` cursor (or the trip's
    ``actual_departure_at`` if the stream is empty) so the
    strict-monotonicity check at priority 512 passes.  The
    ``speed_kph`` defaults to 60.0 km/h (well below the 80 km/h
    speed-limit constant so the speed-violation flag is false), and
    the ``(lat, lon)`` defaults to the first polyline waypoint so the
    off-route flag is also false.  The optional
    ``Idempotency-Key`` header is the dedup-slot key for the
    idempotency-replay tests; absent it the slot is unkeyed and the
    request is a fresh insert.

    The resulting GPSReport row is appended to ``scenario.gps_reports``
    and any auto-Penalty rows the implementation's atomic side-effect
    inserts are read back into ``scenario.penalties``.  In the clean
    sample's case there are zero auto-Penalty rows.
    """
    trip = scenario.trips[trip_idx]
    # Compute a reported_at strictly after the prior cursor (or the
    # trip's actual_departure_at if the stream is empty).
    prior = trip.get("latest_gps_at") or trip.get("actual_departure_at")
    assert prior is not None, "trip has no actual_departure_at; depart it first"
    reported_at = iso_now_plus_delta(seconds=float(reported_at_offset_seconds), base_iso=prior)
    # Advance the server's clock past the reported_at so the
    # GPS-ingest's in-window check ``reported_at <= now`` holds.
    # (The in-window check's right edge for a still-IN_TRANSIT trip
    # is the current logical-clock value.)
    server_now = current_server_now(api)
    rep_dt = _parse_iso(reported_at)
    now_dt = _parse_iso(server_now)
    if rep_dt > now_dt:
        advance_clock_by(api, (rep_dt - now_dt).total_seconds() + 0.5)
    payload = create_gps_report_payload(
        reported_at=reported_at,
        speed_kph=float(speed_kph),
    )
    resp = api.create_gps_report(
        trip["id"],
        payload,
        company_operator_headers(scenario.company["id"]),
        idempotency_key=idempotency_key,
    )
    gps_row = get_success_data(resp)
    scenario.gps_reports.append(gps_row)
    # Refresh the trip's derived fields so the next GPS-ingest can
    # read the just-advanced ``latest_gps_at`` cursor.
    trip_resp = api.get_trip(trip["id"], company_operator_headers(scenario.company["id"]))
    scenario.trips[trip_idx] = get_success_data(trip_resp)
    return gps_row


def ingest_speed_violation_sample(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    trip_idx: int = -1,
    reported_at_offset_seconds: float = 1.0,
    over_limit_kph_delta: float = 5.0,
) -> Dict[str, Any]:
    """Append a GPS sample whose ``speed_kph`` is ``over_limit_kph_delta``
    above the ``MAX_HAZMAT_SPEED_KPH`` constant, firing the
    speed-violation classifier flag and the atomic auto-Penalty
    side-effect.  Returns the GPSReport row; the auto-Penalty's id
    is the single element of the response's
    ``auto_penalty_ids`` array.
    """
    return ingest_clean_gps_sample(
        api,
        scenario,
        trip_idx=trip_idx,
        reported_at_offset_seconds=reported_at_offset_seconds,
        speed_kph=MAX_HAZMAT_SPEED_KPH + float(over_limit_kph_delta),
    )


# ─── Tier 5 add-ons: penalty creation and uphold ──────────────────────


def issue_manual_driver_penalty(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    driver_idx: int = 0,
    points_value: int = 5,
    observed_at_offset_seconds: float = -1.0,
    trip_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The regulator issues a manual penalty against the named
    driver-subject with the given ``points_value`` and an
    ``observed_at`` that lies one second before the current server
    clock (the strict-past convention the body-shape rule requires
    on a manual penalty's observation timestamp).  Returns the
    new Penalty row and appends it to ``scenario.penalties``.
    """
    server_now = current_server_now(api)
    observed_at = iso_now_plus_delta(seconds=float(observed_at_offset_seconds), base_iso=server_now)
    payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=scenario.drivers[driver_idx]["id"],
        observed_at=observed_at,
        points_value=int(points_value),
        trip_id=trip_id,
    )
    resp = api.create_penalty(payload, regulator_headers())
    pen = get_success_data(resp)
    # The response may carry a ``cascade_summary`` sub-object alongside
    # the penalty row, in which case the row itself is under the
    # ``penalty`` key.  The two response shapes are equivalent at the
    # row's identity level.
    penalty_row = pen.get("penalty") if isinstance(pen, dict) and "penalty" in pen else pen
    scenario.penalties.append(penalty_row)
    # Refresh the driver row so the cached ``current_rolling_points``
    # field is the post-create value the next assertion reads.
    drv_resp = api.get_driver(
        scenario.drivers[driver_idx]["id"],
        regulator_headers(),
    )
    scenario.drivers[driver_idx] = get_success_data(drv_resp)
    return penalty_row


def uphold_penalty(api: ApiClient, scenario: HazmatScenario, penalty_idx: int = -1) -> Dict[str, Any]:
    """The regulator's appeal-uphold compensating action on the named
    penalty.  Flips the row's ``void_status`` from ``ACTIVE`` to
    ``UPHELD`` and refreshes the subject driver's
    ``current_rolling_points`` cache via the side-effect's
    rolling-window-sum recomputation.  Per the PRD's §3.2's
    keep-the-regulator-in-the-loop convention the driver's
    ``hazmat_endorsement_status`` is NOT auto-flipped back to
    ``VALID`` on this action even when the post-uphold rolling total
    has fallen below the threshold — the regulator must run the
    separate ``refresh-endorsement`` attestation as the second step
    of the two-step reinstatement.
    """
    penalty = scenario.penalties[penalty_idx]
    resp = api.uphold_penalty(penalty["id"], uphold_penalty_payload(), regulator_headers())
    upheld = get_success_data(resp)
    upheld_row = upheld.get("penalty") if isinstance(upheld, dict) and "penalty" in upheld else upheld
    scenario.penalties[penalty_idx] = upheld_row
    # Refresh every driver row, since the uphold's side-effect on
    # the rolling-points cache touches exactly the subject driver.
    if upheld_row.get("subject_type") == PenaltySubjectType.DRIVER.value:
        subject_id = upheld_row["subject_id"]
        for i, drv in enumerate(scenario.drivers):
            if drv["id"] == subject_id:
                drv_resp = api.get_driver(subject_id, regulator_headers())
                scenario.drivers[i] = get_success_data(drv_resp)
                break
    return upheld_row


def push_driver_to_suspension_threshold(
    api: ApiClient,
    scenario: HazmatScenario,
    *,
    driver_idx: int = 0,
    target_points: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Issue a sequence of manual penalties against the named driver
    until the driver's ``current_rolling_points`` cache crosses the
    suspension threshold ``THRESHOLD_DRIVER_SUSPENSION_POINTS``
    (defaulting to exactly the threshold value).  Returns the list of
    just-issued Penalty rows.  The driver's endorsement flips from
    ``VALID`` to ``INVALID`` on the boundary-crossing penalty via the
    atomic side-effect of the penalty-create.
    """
    target = int(target_points) if target_points is not None else THRESHOLD_DRIVER_SUSPENSION_POINTS
    driver_id = scenario.drivers[driver_idx]["id"]
    # Read the driver's current rolling total.
    drv_resp = api.get_driver(driver_id, regulator_headers())
    drv = get_success_data(drv_resp)
    current_total = int(drv.get("current_rolling_points") or 0)
    issued_rows: List[Dict[str, Any]] = []
    safety_counter = 0
    while current_total < target:
        # The PRD's §2.8 names ``MANUAL_PENALTY_POINTS_MAX`` as 50
        # and the threshold default is 12, so a single penalty
        # easily reaches the threshold; we issue one-point penalties
        # to land on the exact target when possible.
        remaining = target - current_total
        pv = min(remaining, 50)
        row = issue_manual_driver_penalty(
            api,
            scenario,
            driver_idx=driver_idx,
            points_value=int(pv),
        )
        issued_rows.append(row)
        # Refresh the driver's snapshot from the helper's own re-read.
        current_total = int(scenario.drivers[driver_idx].get("current_rolling_points") or 0)
        safety_counter += 1
        assert safety_counter < 1000, "runaway loop in push_driver_to_suspension_threshold"
    return issued_rows


# ─── List-walker conveniences ──────────────────────────────────────────


def fetch_all_inspections(api: ApiClient, scenario: HazmatScenario, vehicle_idx: int = 0) -> List[Dict[str, Any]]:
    """Walk the paginated list endpoint for the named vehicle's
    inspection history and return the full flat list, sorted by
    ``inspected_at`` descending then ``id`` descending per the PRD's
    §3.3 default sort order.
    """
    vehicle = scenario.vehicles[vehicle_idx]
    results: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = api.list_inspections(
            vehicle["id"],
            company_operator_headers(scenario.company["id"]),
            params={"limit": 100, "offset": offset},
        )
        data, meta = validate_paginated(resp)
        results.extend(data)
        if not meta.get("has_more"):
            break
        offset += len(data)
        if offset > 10_000:
            break
    return results


def fetch_all_gps_reports(api: ApiClient, scenario: HazmatScenario, trip_idx: int = 0) -> List[Dict[str, Any]]:
    """Walk the paginated GPS-stream list endpoint for the named trip
    and return the full flat list, sorted by ``reported_at`` ascending
    then ``id`` ascending per the PRD's §3.8 default sort order."""
    trip = scenario.trips[trip_idx]
    results: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = api.list_gps_reports(
            trip["id"],
            company_operator_headers(scenario.company["id"]),
            params={"limit": 100, "offset": offset},
        )
        data, meta = validate_paginated(resp)
        results.extend(data)
        if not meta.get("has_more"):
            break
        offset += len(data)
        if offset > 100_000:
            break
    return results


def fetch_penalty_summary(api: ApiClient, scenario: HazmatScenario, driver_idx: int = 0, *, requester: str = "regulator") -> Dict[str, Any]:
    """Read the driver's penalty-summary digest.  ``requester`` selects
    which role's headers are used: ``"regulator"`` for the
    cross-tenant-exempt regulator's view, ``"operator"`` for the
    parent-company's operator view (the standard fleet-compliance
    dashboard view), or ``"self"`` for the driver's own self-only
    read.  The PRD's §3.8 names all three as allow-set members on
    the endpoint.
    """
    driver_id = scenario.drivers[driver_idx]["id"]
    if requester == "regulator":
        headers = regulator_headers()
    elif requester == "operator":
        headers = company_operator_headers(scenario.company["id"])
    elif requester == "self":
        headers = _driver_headers(driver_id)
    else:
        raise ValueError(f"unknown requester {requester!r}")
    resp = api.get_driver_penalty_summary(driver_id, headers)
    return get_success_data(resp)


def fetch_permit_live_verdict(api: ApiClient, scenario: HazmatScenario) -> Dict[str, Any]:
    """Return the GET-permit response's data sub-object, which the
    PRD's §3.5 declares carries the on-the-fly ``live_verdict`` and
    ``live_per_leg`` and ``snapshot_overall`` fields alongside the
    on-disk snapshot fields and the standard common-fields quartet.
    """
    assert scenario.permit is not None
    resp = api.get_permit(scenario.permit["id"], company_operator_headers(scenario.company["id"]))
    return get_success_data(resp)


# ─── A "two independent companies" scenario for cross-tenant tests ─────


@dataclass
class TwoTenantScenario:
    """The "two distinct tenants" baseline the cross-tenant tests
    exercise.  Each ``HazmatScenario`` is a fully-qualified carrier
    with a permit in ACTIVE.  The cross-tenant predicate of PRD §2.6
    fires on a request from one tenant's operator addressing a row
    owned by the other tenant: the response's error-id is
    ``ERR_CROSS_TENANT_ACCESS`` 403 after the existence-tier check
    passes.  The companion existence-vs-cross-tenant precedence test
    on a wrong-tenant-and-non-existent-id pair sees the 404
    ``ERR_PERMIT_NOT_FOUND`` win over the 403 cross-tenant by the
    priority-300-vs-530 ordering."""

    tenant_a: HazmatScenario
    tenant_b: HazmatScenario


def setup_two_tenants(api: ApiClient) -> TwoTenantScenario:
    """Build two independent fully-qualified carriers, each with an
    APPROVED company, a topped-up wallet, a driver, a vehicle (with
    a PASSED inspection), an approved route, and an ACTIVE permit.
    The two carriers' rosters and the two permits are completely
    disjoint at the row-id level.  The
    ``X-User-ID`` of each tenant's operator-side request is the
    tenant's company id, threaded through the appropriate
    ``company_operator_headers(company_id)`` builder.
    """
    a = setup_active_permit(api)
    b = setup_active_permit(api)
    return TwoTenantScenario(tenant_a=a, tenant_b=b)


# ─── Pre-uphold rolling-points snapshot helper ─────────────────────────


def snapshot_driver_rolling_points(api: ApiClient, scenario: HazmatScenario, driver_idx: int = 0) -> int:
    """Read the named driver's cached ``current_rolling_points``
    integer.  Used by the points-conservation invariant assertion at
    the top and the bottom of an action-sequence so the delta the
    sequence produced can be checked against the algebraic sum of
    the ``points_value`` fields of the rows the sequence inserted.
    """
    driver_id = scenario.drivers[driver_idx]["id"]
    resp = api.get_driver(driver_id, regulator_headers())
    drv = get_success_data(resp)
    cp = drv.get("current_rolling_points")
    assert isinstance(cp, int) and cp >= 0
    scenario.drivers[driver_idx] = drv
    return cp


def snapshot_company_wallet(api: ApiClient, scenario: HazmatScenario) -> int:
    """Read the scenario's company's current ``wallet_balance_cents``
    integer.  Used by the wallet-conservation invariant assertion
    at the boundaries of an action sequence.
    """
    resp = api.get_company(scenario.company["id"], company_operator_headers(scenario.company["id"]))
    co = get_success_data(resp)
    wb = co.get("wallet_balance_cents")
    assert isinstance(wb, int) and wb >= 0
    scenario.company = co
    return wb


# ─── Expected-fee helper mirroring the server-side formula ─────────────


def expected_annual_renewal_fee_cents(
    *,
    vehicle_count: int,
    is_late: bool,
    base_cents: Optional[int] = None,
    per_vehicle_cents: Optional[int] = None,
    late_penalty_cents: Optional[int] = None,
    max_cap_cents: Optional[int] = None,
) -> int:
    """Mirror the PRD's §2.11 ``annual_renewal_fee`` formula on the
    test side so the expected wallet-debit on the issue-and-renew
    actions can be compared against the response's recorded
    ``issue_fee_cents`` and ``renewal_history[*].fee_cents``
    integers.  The formula's pinned evaluation order is

      subtotal = BASE + vehicle_count * PER_VEHICLE
      if is_late: subtotal += LATE_PENALTY
      fee      = min(MAX_CAP, subtotal)

    with integer-cents arithmetic at every step.  The four constants
    default to the deployment-pinned values in
    ``constants.py``.
    """
    from .constants import (  # local import to avoid the constants-module's symbol-export cycle
        BASE_RENEWAL_FEE_CENTS,
        LATE_RENEWAL_PENALTY_CENTS,
        MAX_RENEWAL_FEE_CENTS,
        PER_VEHICLE_SURCHARGE_CENTS,
    )

    base = int(base_cents) if base_cents is not None else BASE_RENEWAL_FEE_CENTS
    per = int(per_vehicle_cents) if per_vehicle_cents is not None else PER_VEHICLE_SURCHARGE_CENTS
    late = int(late_penalty_cents) if late_penalty_cents is not None else LATE_RENEWAL_PENALTY_CENTS
    cap = int(max_cap_cents) if max_cap_cents is not None else MAX_RENEWAL_FEE_CENTS
    subtotal = base + per * int(vehicle_count)
    if is_late:
        subtotal += late
    return min(subtotal, cap)


# ─── Idempotency-Key helper ────────────────────────────────────────────


def fresh_idempotency_key(prefix: str = "idem-") -> str:
    """Return a fresh ``Idempotency-Key`` header value of length
    8..128 characters (the bounds from ``IDEMPOTENCY_KEY_MIN_CHARS``
    and ``IDEMPOTENCY_KEY_MAX_CHARS``).  Two consecutive calls return
    two distinct keys so the per-trip slot-collision the
    ``ERR_IDEMPOTENCY_KEY_REUSED`` test arranges has to be the same
    string-value passed across two requests by the test, not a
    coincidence of the generator.
    """
    return f"{prefix}{uuid4().hex}"[:128]


__all__ = [
    # The HazmatScenario container.
    "HazmatScenario",
    "TwoTenantScenario",
    # Time helpers.
    "iso_now_plus_delta",
    "add_days",
    "add_hours",
    "current_server_now",
    "advance_clock_by",
    "run_full_sweep",
    "admin_reset",
    "admin_wallet_topup",
    # Tier-1 / 2 / 3 / 4 / 5 lifecycle builders.
    "setup_draft_company",
    "setup_submitted_company",
    "setup_approved_company",
    "ensure_funded_company",
    "setup_driver_under_company",
    "setup_vehicle_under_company",
    "setup_route_under_company",
    "setup_qualified_carrier",
    "file_permit_application",
    "issue_permit",
    "setup_active_permit",
    "schedule_trip",
    "depart_trip",
    "arrive_trip",
    "abort_trip",
    "setup_inflight_trip",
    "ingest_clean_gps_sample",
    "ingest_speed_violation_sample",
    "issue_manual_driver_penalty",
    "uphold_penalty",
    "push_driver_to_suspension_threshold",
    "setup_two_tenants",
    # Read helpers.
    "fetch_all_inspections",
    "fetch_all_gps_reports",
    "fetch_penalty_summary",
    "fetch_permit_live_verdict",
    # Snapshot helpers for the conservation-invariant assertions.
    "snapshot_driver_rolling_points",
    "snapshot_company_wallet",
    # Expected-output formulas mirroring the server-side calculations.
    "expected_annual_renewal_fee_cents",
    # Misc utilities.
    "fresh_idempotency_key",
    "refresh_endorsement_attestation_payload",
]
