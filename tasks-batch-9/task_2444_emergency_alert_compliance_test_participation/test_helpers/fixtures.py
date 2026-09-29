"""Composite setup helpers for the EAS Compliance API.

Every helper here drives the public API only, uses the lenient
``get_success_data`` validator so a broken precondition reports as a setup
failure, and builds its state from scratch: the harness restarts the server
before every test, so each test begins against an empty database with the
logical clock at its startup default.

Tier 1  — state progression (plan activation, device readiness, ...)
Tier 2  — entity hierarchy (plan + station + device + assignments)
Tier 3  — lifecycle shortcuts (test event through READY / LOGGED / FILED,
          outage through the repair cycle, inspection through RESPONDED)
Tier 4  — accumulation and threshold targeting (penalty points, silence
          deductions, posture driven to an exact band)
Tier 5  — terminal states (accepted / reversed filings, closed outages,
          closed inspections, superseded plans)
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SOURCE_CALL_SIGNS, TEST_DEFAULTS
from .factories import (
    accessibility_payload,
    alert_event_payload,
    device_payload,
    draft_response_payload,
    equipment_outage_payload,
    filing_record_payload,
    inspection_request_payload,
    monitoring_assignment_payload,
    readiness_check_payload,
    relay_rule_payload,
    state_plan_payload,
    station_payload,
    test_event_payload,
    test_log_entry_payload,
    wireless_alert_notice_payload,
)
from .test_users import (
    ADMIN,
    ENGINEER,
    ENGINEER_USER_ID,
    INSPECTOR,
    OFFICER,
    OFFICER_USER_ID,
)

# Canonical window used by most test-event fixtures.
DEFAULT_WINDOW_START = "2026-08-12T00:00:00Z"
DEFAULT_WINDOW_END = "2026-08-12T01:00:00Z"
DEFAULT_LOG_INSTANT = "2026-08-12T00:30:00Z"
# window_end_at + FILING_DUE_DAYS (5) for the canonical window.
DEFAULT_FILING_DEADLINE = "2026-08-17T01:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — primitives and state progression
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=ADMIN):
    """Move the logical clock. Mutates no entity and fires no recompute."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def create_plan(required_source_types=("PEP",), mandatory_relay_event_codes=(), **overrides):
    """Create a DRAFT state plan."""
    payload = state_plan_payload(
        required_source_types=list(required_source_types),
        mandatory_relay_event_codes=list(mandatory_relay_event_codes),
        **overrides,
    )
    return get_success_data(api_client.create_state_plan(payload, ADMIN))


def create_active_plan(required_source_types=("PEP",), mandatory_relay_event_codes=(), **overrides):
    """Create a plan and activate it, so it binds the stations hanging off it."""
    plan = create_plan(required_source_types, mandatory_relay_event_codes, **overrides)
    return get_success_data(api_client.activate_state_plan(plan["id"], ADMIN))


def register_station(
    plan_id,
    call_sign=None,
    service_type=None,
    engineer_user_ids=None,
    certification_officer_user_id=None,
    **overrides,
):
    """Register a station under a plan with the canonical operator roster."""
    payload = station_payload(
        plan_id,
        call_sign=call_sign or TEST_DEFAULTS["CALL_SIGN"],
        service_type=service_type or TEST_DEFAULTS["SERVICE_TYPE"],
        engineer_user_ids=list(engineer_user_ids or [ENGINEER_USER_ID]),
        certification_officer_user_id=certification_officer_user_id or OFFICER_USER_ID,
        **overrides,
    )
    return get_success_data(api_client.create_station(payload, ADMIN))


def register_device(station_id, headers=ENGINEER, **overrides):
    """Register a device; it lands in REGISTERED with readiness_check_passed false."""
    return get_success_data(
        api_client.create_device(device_payload(station_id, **overrides), headers)
    )


def create_ready_device(station_id, headers=ENGINEER, **overrides):
    """Register a device and pass its readiness check so it reaches READY."""
    device = register_device(station_id, headers=headers, **overrides)
    return get_success_data(
        api_client.readiness_check_device(device["id"], readiness_check_payload(), headers)
    )


def station_version(station_id, headers=ENGINEER) -> int:
    """Read the station's current version for the monitoring-assignment guard."""
    return get_success_data(api_client.get_station(station_id, headers))["version"]


def test_event_version(event_id, headers=OFFICER) -> int:
    """Read the test event's current version for the filing guard."""
    return get_success_data(api_client.get_test_event(event_id, headers))["version"]


def assign_source(
    station_id, device_id, source_type="PEP", source_call_sign=None, headers=ENGINEER, **overrides
):
    """Create a monitoring assignment, reading the station version immediately before
    the write so the optimistic-concurrency guard is always fresh."""
    payload = monitoring_assignment_payload(
        station_id,
        device_id,
        station_version(station_id, headers),
        source_type=source_type,
        **overrides,
    )
    if source_call_sign is not None:
        payload["source_call_sign"] = source_call_sign
    return get_success_data(api_client.create_monitoring_assignment(payload, headers))


def create_relay_rule(plan_id, **overrides):
    """Create an ACTIVE relay rule on a plan."""
    return get_success_data(
        api_client.create_relay_rule(relay_rule_payload(plan_id, **overrides), ADMIN)
    )


def create_retired_relay_rule(plan_id, **overrides):
    """Create a relay rule and retire it out of the selector's candidate pool."""
    rule = create_relay_rule(plan_id, **overrides)
    return get_success_data(api_client.retire_relay_rule(rule["id"], ADMIN))


def record_wireless_notice(station_id, wea_sent_at, **overrides):
    """Record a wireless alert notice, which enters phase B for later alerts."""
    return get_success_data(
        api_client.create_wireless_alert_notice(
            wireless_alert_notice_payload(station_id, wea_sent_at, **overrides), ADMIN
        )
    )


def log_alert(station_id, received_at, headers=ENGINEER, **overrides):
    """Log a received alert; suppression and relay selection settle inside the create."""
    return get_success_data(
        api_client.create_alert_event(
            alert_event_payload(station_id, received_at, **overrides), headers
        )
    )


def verify_alert_accessibility(alert_id, headers=ENGINEER, **overrides):
    """Record the three accessibility measurements on an unverified alert."""
    return get_success_data(
        api_client.verify_accessibility(alert_id, accessibility_payload(**overrides), headers)
    )


def station_summary(station_id, headers=ADMIN):
    """Read every input the station's current compliance score consumed."""
    return get_success_data(api_client.get_compliance_summary(station_id, headers))


def run_log_review(station_id, headers=ADMIN):
    """Run the four-phase station log review."""
    return get_success_data(api_client.run_log_review(station_id, headers))


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------
def setup_station(
    required_source_types=("PEP",),
    covered_source_types=None,
    mandatory_relay_event_codes=(),
    call_sign=None,
    service_type=None,
    engineer_user_ids=None,
    certification_officer_user_id=None,
    engineer_headers=ENGINEER,
    plan_overrides=None,
    device_overrides=None,
):
    """Active plan + station + one READY device + one ACTIVE assignment per covered
    source type.

    Returns a context dict with keys ``plan``, ``station``, ``station_id``,
    ``device``, ``device_id``, ``devices`` and ``assignments`` (mapping source
    type to the assignment row).
    """
    plan = create_active_plan(
        required_source_types, mandatory_relay_event_codes, **(plan_overrides or {})
    )
    station = register_station(
        plan["id"],
        call_sign=call_sign,
        service_type=service_type,
        engineer_user_ids=engineer_user_ids,
        certification_officer_user_id=certification_officer_user_id,
    )
    device = create_ready_device(
        station["id"], headers=engineer_headers, **(device_overrides or {})
    )
    covered = (
        list(required_source_types)
        if covered_source_types is None
        else list(covered_source_types)
    )
    assignments = {}
    for source_type in covered:
        assignments[source_type] = assign_source(
            station["id"],
            device["id"],
            source_type=source_type,
            source_call_sign=SOURCE_CALL_SIGNS.get(source_type),
            headers=engineer_headers,
        )
    return {
        "plan": plan,
        "plan_id": plan["id"],
        "station": station,
        "station_id": station["id"],
        "device": device,
        "device_id": device["id"],
        "devices": [device],
        "assignments": assignments,
        "engineer_headers": engineer_headers,
    }


def add_ready_device(ctx, headers=None, **overrides):
    """Add another READY device to an existing station context."""
    device = create_ready_device(
        ctx["station_id"], headers=headers or ctx.get("engineer_headers", ENGINEER), **overrides
    )
    ctx["devices"].append(device)
    return device


def add_registered_device(ctx, headers=None, **overrides):
    """Add a device that stays in REGISTERED, i.e. inside the readiness denominator
    but not counted as ready."""
    device = register_device(
        ctx["station_id"], headers=headers or ctx.get("engineer_headers", ENGINEER), **overrides
    )
    ctx["devices"].append(device)
    return device


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------
def schedule_test_event(
    station_id,
    window_start_at=DEFAULT_WINDOW_START,
    window_end_at=DEFAULT_WINDOW_END,
    test_type="WEEKLY",
    headers=ADMIN,
):
    """Schedule a test window; filing_deadline_at is derived as window_end_at + 5 days."""
    return get_success_data(
        api_client.create_test_event(
            test_event_payload(
                station_id,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                test_type=test_type,
            ),
            headers,
        )
    )


def evaluate_readiness(event_id, headers=ENGINEER):
    """Evaluate pre-test readiness inside the readiness window."""
    return get_success_data(api_client.evaluate_readiness(event_id, headers))


def setup_ready_test_event(
    ctx=None,
    window_start_at=DEFAULT_WINDOW_START,
    window_end_at=DEFAULT_WINDOW_END,
    evaluate_at=DEFAULT_LOG_INSTANT,
    test_type="WEEKLY",
    **station_kwargs,
):
    """Station + scheduled test event evaluated to READY.

    The default single-device, fully covered station scores 40 + 40 + 0 = 80.00,
    which is exactly the inclusive pass threshold.
    """
    ctx = ctx or setup_station(**station_kwargs)
    event = schedule_test_event(
        ctx["station_id"], window_start_at, window_end_at, test_type=test_type
    )
    set_clock(evaluate_at)
    event = evaluate_readiness(event["id"], ctx.get("engineer_headers", ENGINEER))
    ctx["test_event"] = event
    ctx["test_event_id"] = event["id"]
    return ctx


def append_log_entry(event_id, device_id, entry_kind="TRANSMISSION", headers=ENGINEER, **overrides):
    """Append one log line to a READY test event."""
    return get_success_data(
        api_client.create_test_log_entry(
            test_log_entry_payload(event_id, device_id, entry_kind=entry_kind, **overrides),
            headers,
        )
    )


def setup_logged_test_event(
    ctx=None,
    window_start_at=DEFAULT_WINDOW_START,
    window_end_at=DEFAULT_WINDOW_END,
    log_at=DEFAULT_LOG_INSTANT,
    receipt_source_types=None,
    test_type="WEEKLY",
    close=True,
    **station_kwargs,
):
    """Station + test event taken READY, one TRANSMISSION line plus one RECEIPT line
    per covered source type, then the logging phase closed to LOGGED."""
    ctx = setup_ready_test_event(
        ctx,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        evaluate_at=log_at,
        test_type=test_type,
        **station_kwargs,
    )
    engineer_headers = ctx.get("engineer_headers", ENGINEER)
    entries = [
        append_log_entry(
            ctx["test_event_id"], ctx["device_id"], "TRANSMISSION", headers=engineer_headers
        )
    ]
    sources = (
        list(ctx["assignments"].keys())
        if receipt_source_types is None
        else list(receipt_source_types)
    )
    for source_type in sources:
        entries.append(
            append_log_entry(
                ctx["test_event_id"],
                ctx["device_id"],
                "RECEIPT",
                headers=engineer_headers,
                source_call_sign=SOURCE_CALL_SIGNS.get(source_type),
            )
        )
    ctx["log_entries"] = entries
    if close:
        ctx["test_event"] = get_success_data(
            api_client.close_logging(ctx["test_event_id"], engineer_headers)
        )
    return ctx


def file_results(event_id, headers=OFFICER, note=None, expected_version=None):
    """File post-test results, reading the test event's version immediately before
    the write unless an explicit (possibly stale) version is supplied."""
    version = (
        expected_version
        if expected_version is not None
        else test_event_version(event_id, headers)
    )
    payload = filing_record_payload(event_id, version)
    if note is not None:
        payload["attestation_note"] = note
    return get_success_data(api_client.create_filing_record(payload, headers))


def setup_submitted_filing(
    ctx=None, file_at=None, officer_headers=OFFICER, **logged_kwargs
):
    """Everything through a SUBMITTED filing record on a LOGGED test event."""
    ctx = ctx if ctx and "test_event_id" in ctx else setup_logged_test_event(ctx, **logged_kwargs)
    if file_at is not None:
        set_clock(file_at)
    filing = file_results(ctx["test_event_id"], headers=officer_headers)
    ctx["filing"] = filing
    ctx["filing_id"] = filing["id"]
    return ctx


def setup_accepted_filing(ctx=None, file_at=None, officer_headers=OFFICER, **logged_kwargs):
    """Everything through an ACCEPTED filing, which is what makes the station
    eligible for the certified scoring variant."""
    ctx = setup_submitted_filing(
        ctx, file_at=file_at, officer_headers=officer_headers, **logged_kwargs
    )
    ctx["filing"] = get_success_data(api_client.accept_filing(ctx["filing_id"], ADMIN))
    return ctx


def setup_certified_station_with_penalty(
    file_at="2026-08-17T02:00:00Z", **logged_kwargs
):
    """A CERTIFIED station carrying exactly one late filing's penalty points.

    Files one day past the canonical deadline (2026-08-17T01:00:00Z) with one
    TRANSMISSION and one RECEIPT line, so penalty_points is 0.94, and accepts it.
    """
    return setup_accepted_filing(file_at=file_at, **logged_kwargs)


def setup_outage(device_id, detected_at, headers=ENGINEER, **overrides):
    """File an equipment outage, which runs the full four-hop outage cascade."""
    return get_success_data(
        api_client.create_equipment_outage(
            equipment_outage_payload(device_id, detected_at, **overrides), headers
        )
    )


def setup_outage_in_repair(device_id, detected_at, headers=ENGINEER, **overrides):
    """Outage filed and moved to REPAIR_IN_PROGRESS (repair_cycle_count stays 0)."""
    outage = setup_outage(device_id, detected_at, headers=headers, **overrides)
    return get_success_data(api_client.start_repair(outage["id"], headers))


def setup_restored_outage(
    device_id, detected_at, restored_at, headers=ENGINEER, **overrides
):
    """Outage driven to RESTORED with both downtime figures computed at `restored_at`."""
    outage = setup_outage_in_repair(device_id, detected_at, headers=headers, **overrides)
    set_clock(restored_at)
    return get_success_data(api_client.restore_outage(outage["id"], headers))


def setup_closed_outage(device_id, detected_at, restored_at, headers=ENGINEER, **overrides):
    """Outage driven to CLOSED, which returns the device to READY and moves its
    SUSPENDED assignments to SILENT."""
    outage = setup_restored_outage(
        device_id, detected_at, restored_at, headers=headers, **overrides
    )
    return get_success_data(api_client.close_outage(outage["id"], ADMIN))


def setup_inspection(station_id, requested_document_kinds=None, headers=INSPECTOR):
    """Open a public-file inspection request; response_due_at is requested_at + 7 days."""
    payload = inspection_request_payload(station_id)
    if requested_document_kinds is not None:
        payload["requested_document_kinds"] = list(requested_document_kinds)
    return get_success_data(api_client.create_inspection_request(payload, headers))


def setup_drafted_inspection(
    station_id,
    requested_document_kinds=None,
    provided_document_kinds=None,
    engineer_headers=ENGINEER,
    inspector_headers=INSPECTOR,
):
    """Inspection request drafted by an engineer, landing in RESPONSE_DRAFTED."""
    request = setup_inspection(station_id, requested_document_kinds, inspector_headers)
    provided = (
        list(request["requested_document_kinds"])
        if provided_document_kinds is None
        else list(provided_document_kinds)
    )
    return get_success_data(
        api_client.draft_response(
            request["id"], draft_response_payload(provided), engineer_headers
        )
    )


def setup_responded_inspection(
    station_id,
    requested_document_kinds=None,
    provided_document_kinds=None,
    engineer_headers=ENGINEER,
    officer_headers=OFFICER,
    inspector_headers=INSPECTOR,
):
    """Inspection request submitted by the certifying officer, landing in RESPONDED
    with completeness_score computed."""
    drafted = setup_drafted_inspection(
        station_id,
        requested_document_kinds,
        provided_document_kinds,
        engineer_headers,
        inspector_headers,
    )
    return get_success_data(api_client.submit_response(drafted["id"], officer_headers))


def setup_closed_inspection(
    station_id,
    requested_document_kinds=None,
    provided_document_kinds=None,
    engineer_headers=ENGINEER,
    officer_headers=OFFICER,
    inspector_headers=INSPECTOR,
):
    """Inspection request driven to a terminal closed status."""
    responded = setup_responded_inspection(
        station_id,
        requested_document_kinds,
        provided_document_kinds,
        engineer_headers,
        officer_headers,
        inspector_headers,
    )
    return get_success_data(api_client.close_inspection(responded["id"], inspector_headers))


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------
def add_silence_padding_assignments(ctx, source_types=("SATELLITE", "LP1", "LP2")):
    """Add assignments for source types the plan does not require.

    Each one is worth 10.00 points of silence deduction once a log review flags it,
    while coverage of the required sources is untouched.
    """
    padding = []
    for source_type in source_types:
        padding.append(
            assign_source(
                ctx["station_id"],
                ctx["device_id"],
                source_type=source_type,
                source_call_sign=SOURCE_CALL_SIGNS.get(source_type),
                headers=ctx.get("engineer_headers", ENGINEER),
            )
        )
    ctx.setdefault("padding_assignments", []).extend(padding)
    return padding


def flag_silence(ctx, review_at):
    """Move the clock past the eight-day silence horizon and run a log review so the
    padding assignments are flagged SILENT."""
    set_clock(review_at)
    return run_log_review(ctx["station_id"])


def drive_station_to_suspended_filings(
    ctx=None, review_at="2026-08-13T00:00:00Z", padding=("SATELLITE", "LP1", "LP2")
):
    """Drive a station to SUSPENDED_FILINGS through the silence sweep alone.

    Three silent assignments cost 30.00 points, landing the score on 70.00, which
    is below the 75.00 WATCH floor. Required-source coverage never lapses.
    """
    ctx = ctx or setup_station()
    add_silence_padding_assignments(ctx, padding)
    ctx["log_review"] = flag_silence(ctx, review_at)
    return ctx


def drive_station_to_watch_via_missing_source(ctx=None):
    """Decommission the only assignment covering a required source, costing 25.00
    points and landing the station on 75.00 / WATCH."""
    ctx = ctx or setup_station()
    source_type = next(iter(ctx["assignments"]))
    assignment = ctx["assignments"][source_type]
    get_success_data(
        api_client.decommission_assignment(
            assignment["id"], ctx.get("engineer_headers", ENGINEER)
        )
    )
    return ctx


def accumulate_recent_alerts(ctx, received_at, count=1, sequence_prefix="KSRDY"):
    """Log `count` alerts inside the recent-activity window, each with its own
    originator_sequence so duplicate suppression never fires."""
    alerts = []
    for index in range(count):
        alerts.append(
            log_alert(
                ctx["station_id"],
                received_at,
                headers=ctx.get("engineer_headers", ENGINEER),
                originator_sequence=f"{sequence_prefix}-{index:04d}",
            )
        )
    ctx.setdefault("alerts", []).extend(alerts)
    return alerts


def setup_mandatory_relay_pending_alert(
    ctx=None, received_at="2026-08-12T00:00:00Z", event_code="TOR", **station_kwargs
):
    """A station carrying one alert in RELAY_PENDING whose effective class is
    MANDATORY — that is, one unconfirmed mandatory relay for the filing penalty."""
    ctx = ctx or setup_station(mandatory_relay_event_codes=(event_code,), **station_kwargs)
    create_relay_rule(
        ctx["plan_id"],
        event_code=event_code,
        fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        relay_class="MANDATORY",
        priority=10,
        forward_delay_seconds=30,
    )
    alert = log_alert(
        ctx["station_id"],
        received_at,
        headers=ctx.get("engineer_headers", ENGINEER),
        event_code=event_code,
        originator_sequence="KSMAN-0001",
    )
    ctx.setdefault("alerts", []).append(alert)
    ctx["mandatory_alert"] = alert
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — terminal states
# ---------------------------------------------------------------------------
def supersede_plan(state_code=None, plan_version_label=None, required_source_types=("PEP", "NWS")):
    """Activate a successor plan for the same state code, firing the three-hop
    plan-supersede cascade. Returns the successor plan."""
    return create_active_plan(
        required_source_types,
        state_code=state_code or TEST_DEFAULTS["STATE_CODE"],
        plan_version_label=plan_version_label or TEST_DEFAULTS["SUCCESSOR_PLAN_LABEL"],
    )


def setup_reversed_filing(ctx=None, reversal_reason="ATTESTATION_WITHDRAWN", **kwargs):
    """A filing driven to the terminal REVERSED status, which withdraws its
    contribution to the station's penalty ledger."""
    ctx = setup_accepted_filing(ctx, **kwargs)
    ctx["filing"] = get_success_data(
        api_client.reverse_filing(
            ctx["filing_id"], {"reversal_reason": reversal_reason}, ADMIN
        )
    )
    return ctx


def setup_failed_unfiled_test_event(
    ctx=None,
    window_start_at=DEFAULT_WINDOW_START,
    window_end_at=DEFAULT_WINDOW_END,
    evaluate_at=DEFAULT_LOG_INSTANT,
    review_at="2026-08-19T00:00:00Z",
    **station_kwargs,
):
    """A test event abandoned in READY past its filing deadline and swept to
    FAILED_UNFILED by the log review's second phase."""
    ctx = setup_ready_test_event(
        ctx,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        evaluate_at=evaluate_at,
        **station_kwargs,
    )
    set_clock(review_at)
    ctx["log_review"] = run_log_review(ctx["station_id"])
    ctx["test_event"] = get_success_data(
        api_client.get_test_event(ctx["test_event_id"], ADMIN)
    )
    return ctx


def setup_decommissioned_assignment(ctx=None, source_type=None):
    """An assignment parked in DECOMMISSIONED, ready to be reinstated."""
    ctx = ctx or setup_station()
    source_type = source_type or next(iter(ctx["assignments"]))
    assignment = ctx["assignments"][source_type]
    ctx["assignments"][source_type] = get_success_data(
        api_client.decommission_assignment(
            assignment["id"], ctx.get("engineer_headers", ENGINEER)
        )
    )
    return ctx
