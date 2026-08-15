"""Composite setup helpers.

Multi-step arrangements shared by the test suite: reference data (substation,
policy, asset), certified technicians, outage windows driven through their
lifecycle, work-order chains, relay-setting review chains, spare logistics, and
environmental inspections. All helpers use the lenient setup validator so
setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .factories import (
    create_asset_payload,
    create_certification_payload,
    create_defect_payload,
    create_environmental_inspection_payload,
    create_outage_window_payload,
    create_policy_payload,
    create_relay_setting_payload,
    create_spare_reservation_payload,
    create_spare_unit_payload,
    create_substation_payload,
    create_switching_step_payload,
    create_technician_payload,
    create_test_event_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_technician_headers

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
SUP2 = TEST_USERS["supervisor_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Reference data (PRD §3.1)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.7). OperationsManager-only."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def create_substation(**overrides) -> dict:
    resp = api_client.create_substation(create_substation_payload(**overrides), OPS)
    return get_success_data(resp)


def create_policy(asset_class="POWER_TRANSFORMER", **overrides) -> dict:
    resp = api_client.create_asset_class_policy(
        create_policy_payload(asset_class, **overrides), OPS
    )
    return get_success_data(resp)


def create_asset(substation_id, asset_class="POWER_TRANSFORMER", **overrides) -> dict:
    resp = api_client.create_asset(
        create_asset_payload(substation_id, asset_class, **overrides), OPS
    )
    return get_success_data(resp)


def setup_asset(asset_class="POWER_TRANSFORMER", **asset_overrides) -> dict:
    """Substation + matching class policy + one asset. Returns dict of all three."""
    sub = create_substation()
    policy = create_policy(asset_class)
    asset = create_asset(sub["id"], asset_class, **asset_overrides)
    return {"substation": sub, "policy": policy, "asset": asset}


# ---------------------------------------------------------------------------
# Technicians and certifications (PRD §3.9)
# ---------------------------------------------------------------------------

def create_technician(**overrides) -> dict:
    resp = api_client.create_technician(create_technician_payload(**overrides), OPS)
    return get_success_data(resp)


def grant_certification(technician_id, cert_type="NETA_LEVEL_2", **overrides) -> dict:
    resp = api_client.create_certification(
        technician_id, create_certification_payload(cert_type, **overrides), OPS
    )
    return get_success_data(resp)


def create_certified_technician(cert_type="NETA_LEVEL_2", **cert_overrides):
    """Technician + one certification. Returns (technician, technician_headers).

    The headers carry the real Technician.id because Technician identity is
    entity-backed (PRD §2.1) and ownership-gated calls compare against it.
    """
    tech = create_technician()
    grant_certification(tech["id"], cert_type, **cert_overrides)
    return tech, make_technician_headers(tech["id"])


# ---------------------------------------------------------------------------
# Outage windows and switching (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def create_outage_window(
    substation_id,
    asset_id,
    start_ts,
    end_ts,
    purpose="Planned maintenance",
    requester_id="coord-1",
) -> dict:
    payload = create_outage_window_payload(
        substation_id, asset_id, start_ts, end_ts, purpose=purpose
    )
    headers = build_user_headers(requester_id, "OutageCoordinator")
    return get_success_data(api_client.create_outage_window(payload, headers))


def add_switching_step(outage_window_id, sequence_no=1, description=None) -> dict:
    payload = create_switching_step_payload(
        sequence_no, description=description or f"Step {sequence_no}"
    )
    return get_success_data(api_client.create_switching_step(outage_window_id, payload, COORD))


def approve_outage_window(outage_window_id, approver_id="ops-mgr-1") -> dict:
    headers = build_user_headers(approver_id, "OperationsManager")
    return get_success_data(api_client.approve_outage_window(outage_window_id, headers))


def begin_switching(outage_window_id, supervisor_id="sup-1") -> dict:
    headers = build_user_headers(supervisor_id, "SwitchingSupervisor")
    return get_success_data(api_client.begin_switching(outage_window_id, headers))


def execute_step(step_id, supervisor_id="sup-1") -> dict:
    headers = build_user_headers(supervisor_id, "SwitchingSupervisor")
    return get_success_data(api_client.execute_switching_step(step_id, headers))


def verify_step(step_id, supervisor_id="sup-2") -> dict:
    headers = build_user_headers(supervisor_id, "SwitchingSupervisor")
    return get_success_data(api_client.verify_switching_step(step_id, headers))


def execute_and_verify_step(step_id, executor_id="sup-1", verifier_id="sup-2") -> dict:
    execute_step(step_id, executor_id)
    return verify_step(step_id, verifier_id)


def setup_approved_window(
    start_ts,
    end_ts,
    *,
    asset_class="POWER_TRANSFORMER",
    asset_overrides=None,
    with_step=True,
    requester_id="coord-1",
    approver_id="ops-mgr-1",
) -> dict:
    """Substation + policy + asset + REQUESTED window (+ one step) + approve.

    Returns dict with substation, policy, asset, window (APPROVED) and
    window_version (the window's version after approval).
    """
    base = setup_asset(asset_class, **(asset_overrides or {}))
    window = create_outage_window(
        base["substation"]["id"], base["asset"]["id"], start_ts, end_ts,
        requester_id=requester_id,
    )
    step = add_switching_step(window["id"], 1) if with_step else None
    approved = approve_outage_window(window["id"], approver_id)
    return {
        **base,
        "window": approved,
        "window_version": approved["version"],
        "step": step,
    }


def setup_switching_window(
    start_ts,
    end_ts,
    clock_ts,
    *,
    asset_class="POWER_TRANSFORMER",
    asset_overrides=None,
    num_steps=1,
    supervisor_id="sup-1",
) -> dict:
    """Approved window -> set clock inside the window -> begin-switching.

    Returns the setup dict plus the SWITCHING window and created steps.
    """
    setup = setup_approved_window(
        start_ts, end_ts, asset_class=asset_class, asset_overrides=asset_overrides,
        with_step=False,
    )
    steps = [add_switching_step(setup["window"]["id"], i + 1) for i in range(num_steps)]
    # Steps may only be added while REQUESTED or APPROVED; approve happened
    # already above, so re-approve state is untouched — steps added post-approve
    # are still on an APPROVED window, which is permitted.
    set_clock(clock_ts)
    window = begin_switching(setup["window"]["id"], supervisor_id)
    return {**setup, "steps": steps, "window": window}


# ---------------------------------------------------------------------------
# Test events, review, defects (PRD §3.4, §3.6)
# ---------------------------------------------------------------------------

def create_test_event(asset_id, tech_headers, test_type="OIL_MOISTURE", **overrides) -> dict:
    payload = create_test_event_payload(asset_id, test_type, **overrides)
    return get_success_data(api_client.create_test_event(payload, tech_headers))


def submit_test_event(test_event_id, tech_headers) -> dict:
    return get_success_data(api_client.submit_test_event(test_event_id, tech_headers))


def review_test_event(test_event_id, decision="ACCEPT", review_note=None) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_test_event(test_event_id, payload, COMPLIANCE))


def create_accepted_test_event(asset_id, tech_headers, test_type="OIL_MOISTURE", **overrides) -> dict:
    """Create -> submit -> ACCEPT. Returns the ACCEPTED test event."""
    event = create_test_event(asset_id, tech_headers, test_type, **overrides)
    submit_test_event(event["id"], tech_headers)
    return review_test_event(event["id"], "ACCEPT")


def create_defect(asset_id, tech_headers, severity="C2", **overrides) -> dict:
    payload = create_defect_payload(asset_id, severity, **overrides)
    return get_success_data(api_client.create_defect(payload, tech_headers))


# ---------------------------------------------------------------------------
# Work orders (PRD §3.6)
# ---------------------------------------------------------------------------

def create_work_order(defect_id, assigned_technician_id, estimated_hours=4, **overrides) -> dict:
    payload = create_work_order_payload(
        defect_id, assigned_technician_id, estimated_hours=estimated_hours, **overrides
    )
    return get_success_data(api_client.create_work_order(payload, OPS))


def schedule_work_order(work_order_id, outage_window_id, expected_version) -> dict:
    payload = {
        "outage_window_id": outage_window_id,
        "expected_outage_window_version": expected_version,
    }
    return get_success_data(api_client.schedule_work_order(work_order_id, payload, COORD))


def setup_defect_with_work_order(
    *, asset_class="POWER_TRANSFORMER", asset_overrides=None,
    severity="C2", estimated_hours=4,
) -> dict:
    """Asset + technician + defect (OPEN) + DRAFT work order for it."""
    base = setup_asset(asset_class, **(asset_overrides or {}))
    tech = create_technician()
    tech_headers = make_technician_headers(tech["id"])
    defect = create_defect(base["asset"]["id"], tech_headers, severity)
    work_order = create_work_order(defect["id"], tech["id"], estimated_hours)
    return {**base, "technician": tech, "tech_headers": tech_headers,
            "defect": defect, "work_order": work_order}


def setup_scheduled_work_order(
    window_start,
    window_end,
    *,
    asset_class="POWER_TRANSFORMER",
    asset_overrides=None,
    severity="C2",
    estimated_hours=4,
    with_step=True,
) -> dict:
    """Work order in SCHEDULED state inside an APPROVED window.

    Chain: asset + tech + defect + DRAFT work order + window (+ step) +
    approve + schedule (OCC on the window version captured after approval).
    """
    ctx = setup_defect_with_work_order(
        asset_class=asset_class, asset_overrides=asset_overrides,
        severity=severity, estimated_hours=estimated_hours,
    )
    window = create_outage_window(
        ctx["substation"]["id"], ctx["asset"]["id"], window_start, window_end
    )
    step = add_switching_step(window["id"], 1) if with_step else None
    approved = approve_outage_window(window["id"], "ops-mgr-1")
    scheduled = schedule_work_order(
        ctx["work_order"]["id"], window["id"], approved["version"]
    )
    return {**ctx, "window": approved, "window_version": approved["version"],
            "step": step, "work_order": scheduled}


def setup_work_order_in_progress(
    window_start,
    window_end,
    clock_ts,
    *,
    asset_class="POWER_TRANSFORMER",
    asset_overrides=None,
    severity="C2",
    estimated_hours=4,
) -> dict:
    """Work order driven to IN_PROGRESS: scheduled -> clock into the window ->
    begin-switching -> start (assignee only, window de-energized)."""
    ctx = setup_scheduled_work_order(
        window_start, window_end,
        asset_class=asset_class, asset_overrides=asset_overrides,
        severity=severity, estimated_hours=estimated_hours,
    )
    set_clock(clock_ts)
    begin_switching(ctx["window"]["id"], "sup-1")
    started = get_success_data(
        api_client.start_work_order(ctx["work_order"]["id"], ctx["tech_headers"])
    )
    return {**ctx, "work_order": started}


def complete_work_order(work_order_id, tech_headers, labor_lines, parts_lines) -> dict:
    payload = {"labor_lines": labor_lines, "parts_lines": parts_lines}
    return get_success_data(api_client.complete_work_order(work_order_id, payload, tech_headers))


# ---------------------------------------------------------------------------
# Spare logistics (PRD §3.7)
# ---------------------------------------------------------------------------

def create_spare_unit(**overrides) -> dict:
    return get_success_data(api_client.create_spare_unit(create_spare_unit_payload(**overrides), OPS))


def create_spare_reservation(start_ts, end_ts, **overrides) -> dict:
    payload = create_spare_reservation_payload(start_ts, end_ts, **overrides)
    return get_success_data(api_client.create_spare_reservation(payload, COORD))


# ---------------------------------------------------------------------------
# Relay settings (PRD §3.8)
# ---------------------------------------------------------------------------

def setup_relay_domain(**asset_overrides) -> dict:
    """Substation + RELAY policy + RELAY asset + author technician (no cert
    needed to draft/submit) + verifier technician holding ACTIVE NETA_LEVEL_4.

    Returns asset, author (+headers), verifier (+headers).
    """
    base = setup_asset("RELAY", **asset_overrides)
    author = create_technician()
    verifier, verifier_headers = create_certified_technician("NETA_LEVEL_4")
    return {
        **base,
        "author": author,
        "author_headers": make_technician_headers(author["id"]),
        "verifier": verifier,
        "verifier_headers": verifier_headers,
    }


def create_verified_relay_setting(
    asset_id,
    author_headers,
    verifier_headers,
    *,
    pickup_a=80,
    setting_group="G1",
    time_dial=2.0,
    curve="IEC_SI",
) -> dict:
    """Draft -> submit (author) -> verify (NETA_LEVEL_4 non-author)."""
    payload = create_relay_setting_payload(
        asset_id, setting_group=setting_group, pickup_a=pickup_a,
        time_dial=time_dial, curve=curve,
    )
    setting = get_success_data(api_client.create_relay_setting(payload, author_headers))
    get_success_data(api_client.submit_relay_setting(setting["id"], author_headers))
    return get_success_data(api_client.verify_relay_setting(setting["id"], verifier_headers))


def activate_relay_setting(setting_id, activator_headers, expected_asset_version) -> dict:
    payload = {"expected_asset_version": expected_asset_version}
    return get_success_data(
        api_client.activate_relay_setting(setting_id, payload, activator_headers)
    )


# ---------------------------------------------------------------------------
# Environmental inspections (PRD §3.10)
# ---------------------------------------------------------------------------

def create_environmental_inspection(substation_id, **overrides) -> dict:
    payload = create_environmental_inspection_payload(**overrides)
    return get_success_data(
        api_client.create_environmental_inspection(substation_id, payload, COMPLIANCE)
    )
