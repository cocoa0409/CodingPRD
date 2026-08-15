"""Composite setup helpers for the sewer CCTV rehabilitation test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: ownership-gated calls always use make_*_headers(tech_id)
with the actual Technician.id created earlier in the same fixture.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CERT_VALID_UNTIL,
    CYCLE_END,
    CYCLE_START,
    DEFAULT_CLOCK,
    SCHEDULED_AT,
)
from .factories import (
    create_bypass_payload,
    create_cycle_payload,
    create_defect_payload,
    create_district_payload,
    create_flow_period_payload,
    create_inspection_payload,
    create_lateral_payload,
    create_notice_payload,
    create_plan_payload,
    create_segment_payload,
    create_technician_payload,
    create_warranty_case_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_coder_headers,
    make_crew_lead_headers,
    make_qa_reviewer_headers,
)

ENGINEER = TEST_USERS["engineer_headers"]
CSR = TEST_USERS["csr_headers"]

# A single grade-3 structural point defect: structural_grade 3 with exactly one
# structural observation graded >= 3 — eligible for SPOT_REPAIR (PRD §3.4).
DEFECT_G3_POINT = {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 3,
                   "distance_m": 10, "clock_position": 6}
# Grade-2 structural point defect: structural_grade 2 — eligible for CIPP_LINING.
DEFECT_G2_POINT = {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                   "distance_m": 10, "clock_position": 6}
# Grade-4 structural point defect (FULL_REPLACE setups).
DEFECT_G4_POINT = {"pacp_code": "B", "family": "STRUCTURAL", "grade": 4,
                   "distance_m": 60, "clock_position": 12}


# ---------------------------------------------------------------------------
# Tier 0: atomic helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ENGINEER)
    )


def create_district(**overrides) -> dict:
    return get_success_data(api_client.create_district(create_district_payload(**overrides), ENGINEER))


def create_technician(capabilities, *, cert_expires_at=CERT_VALID_UNTIL, **overrides) -> dict:
    payload = create_technician_payload(
        nassco_cert_expires_at=cert_expires_at, capabilities=capabilities, **overrides
    )
    return get_success_data(api_client.create_technician(payload, ENGINEER))


def create_open_cycle(district_id, *, window_start=CYCLE_START, window_end=CYCLE_END, **overrides) -> dict:
    cycle = get_success_data(
        api_client.create_inspection_cycle(
            district_id, create_cycle_payload(window_start=window_start, window_end=window_end, **overrides), ENGINEER
        )
    )
    return get_success_data(api_client.open_inspection_cycle(cycle["id"], ENGINEER))


def create_segment(district_id, **overrides) -> dict:
    return get_success_data(api_client.create_segment(district_id, create_segment_payload(**overrides), ENGINEER))


def create_lateral(segment_id, **overrides) -> dict:
    return get_success_data(api_client.create_lateral(segment_id, create_lateral_payload(**overrides), ENGINEER))


def schedule_inspection(segment_id, cycle_id, coder_id, *, scheduled_at=SCHEDULED_AT,
                        purpose="BASELINE") -> dict:
    """Create a CctvInspection in SCHEDULED."""
    payload = create_inspection_payload(cycle_id, coder_id, scheduled_at=scheduled_at, purpose=purpose)
    return get_success_data(api_client.create_cctv_inspection(segment_id, payload, ENGINEER))


def start_inspection(inspection_id, coder_id) -> dict:
    return get_success_data(api_client.start_inspection(inspection_id, make_coder_headers(coder_id)))


def begin_coding(inspection_id, coder_id) -> dict:
    return get_success_data(api_client.begin_coding(inspection_id, make_coder_headers(coder_id)))


def drive_inspection_to_coding(inspection_id, coder_id) -> dict:
    """SCHEDULED -> IN_PROGRESS -> CODING."""
    start_inspection(inspection_id, coder_id)
    return begin_coding(inspection_id, coder_id)


def add_defects(inspection_id, coder_id, defects) -> list:
    headers = make_coder_headers(coder_id)
    return [
        get_success_data(api_client.create_defect(inspection_id, d, headers))
        for d in defects
    ]


def submit_for_qa(inspection_id, coder_id) -> dict:
    return get_success_data(api_client.submit_qa(inspection_id, make_coder_headers(coder_id)))


def certify_inspection(inspection_id, qa_id) -> dict:
    return get_success_data(api_client.certify_inspection(inspection_id, make_qa_reviewer_headers(qa_id)))


def reject_inspection(inspection_id, qa_id, reason="recheck") -> dict:
    return get_success_data(
        api_client.reject_inspection(inspection_id, make_qa_reviewer_headers(qa_id), {"reason": reason})
    )


def get_segment(segment_id) -> dict:
    return get_success_data(api_client.get_segment(segment_id, ENGINEER))


def get_plan(plan_id) -> dict:
    return get_success_data(api_client.get_rehab_plan(plan_id, ENGINEER))


def get_work_order(work_order_id) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, ENGINEER))


def get_district(district_id) -> dict:
    return get_success_data(api_client.get_district(district_id, ENGINEER))


# ---------------------------------------------------------------------------
# Tier 1/2: certified-inspection setup (the pipeline's entry point)
# ---------------------------------------------------------------------------

def setup_certified_segment(*, defects=None, material="VCP", diameter_mm=200, length_m=100,
                            install_year=1980, purpose="BASELINE", budget_cents=100_000_000,
                            ii_reduction_target_pct=25, district_overrides=None,
                            clock=DEFAULT_CLOCK, cycle_start=CYCLE_START, cycle_end=CYCLE_END,
                            cert_expires_at=CERT_VALID_UNTIL, scheduled_at=SCHEDULED_AT,
                            segment_ref=None) -> dict:
    """District + coder + QA + OPEN cycle + segment + one inspection driven all
    the way to CERTIFIED with the given defect observations.

    Returns ctx dict: district, coder, qa, cycle, segment (post-certification),
    inspection (CERTIFIED).
    """
    if defects is None:
        defects = [DEFECT_G3_POINT]
    set_clock(clock)
    d_kwargs = {"budget_cents": budget_cents, "ii_reduction_target_pct": ii_reduction_target_pct}
    d_kwargs.update(district_overrides or {})
    district = create_district(**d_kwargs)
    coder = create_technician(["CODER"], cert_expires_at=cert_expires_at)
    qa = create_technician(["QA_REVIEWER"], cert_expires_at=cert_expires_at)
    cycle = create_open_cycle(district["id"], window_start=cycle_start, window_end=cycle_end)
    seg_kwargs = {"diameter_mm": diameter_mm, "material": material,
                  "length_m": length_m, "install_year": install_year}
    if segment_ref is not None:
        seg_kwargs["segment_ref"] = segment_ref
    segment = create_segment(district["id"], **seg_kwargs)
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"],
                                     scheduled_at=scheduled_at, purpose=purpose)
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"], defects)
    submit_for_qa(inspection["id"], coder["id"])
    inspection = certify_inspection(inspection["id"], qa["id"])
    return {
        "district": district,
        "coder": coder,
        "qa": qa,
        "cycle": cycle,
        "segment": get_segment(segment["id"]),
        "inspection": inspection,
    }


# ---------------------------------------------------------------------------
# Tier 2/3: plans, work orders, line items
# ---------------------------------------------------------------------------

def create_plan(segment_id, inspection_id, method) -> dict:
    return get_success_data(
        api_client.create_rehab_plan(segment_id, create_plan_payload(method, inspection_id), ENGINEER)
    )


def propose_plan(plan_id) -> dict:
    return get_success_data(api_client.propose_plan(plan_id, ENGINEER))


def approve_plan(plan_id) -> dict:
    """Approve with the plan's CURRENT version (OCC guard, PRD §2.9)."""
    current = get_plan(plan_id)
    return get_success_data(
        api_client.approve_plan(plan_id, {"expected_plan_version": current["version"]}, ENGINEER)
    )


def create_work_order(plan_id, crew_lead_id) -> dict:
    return get_success_data(
        api_client.create_work_order(plan_id, create_work_order_payload(crew_lead_id), ENGINEER)
    )


def add_line_item(work_order_id, pay_item_code, scheduled_qty, unit_price_cents) -> dict:
    """Add a line item with the work order's CURRENT version (OCC guard)."""
    current = get_work_order(work_order_id)
    payload = {
        "pay_item_code": pay_item_code,
        "scheduled_qty": scheduled_qty,
        "unit_price_cents": unit_price_cents,
        "expected_work_order_version": current["version"],
    }
    return get_success_data(api_client.create_line_item(work_order_id, payload, ENGINEER))


def setup_plan_with_work_order(*, method="SPOT_REPAIR", lines=None, approve=True,
                               crew_cert_expires_at=None, cert_kwargs=None) -> dict:
    """Certified segment + plan (proposed) [+ approval + work order + line items].

    PRD §3.5: a work order is issued under an APPROVED plan, so the work order
    and its line items are staged only after the plan is approved. With
    approve=False the plan remains PROPOSED and no work order is created
    (ctx["work_order"] is None and ctx["lines"] is []).

    lines: list of (pay_item_code, scheduled_qty, unit_price_cents) tuples.
    Returns ctx with crew, plan, work_order (refreshed), lines.
    """
    cert_kwargs = dict(cert_kwargs or {})
    ctx = setup_certified_segment(**cert_kwargs)
    crew = create_technician(
        ["CREW_LEAD"],
        cert_expires_at=crew_cert_expires_at or cert_kwargs.get("cert_expires_at", CERT_VALID_UNTIL),
    )
    plan = propose_plan(create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], method)["id"])
    work_order = None
    line_objs = []
    if approve:
        plan = approve_plan(plan["id"])
        work_order = create_work_order(plan["id"], crew["id"])
        for code, qty, price in (lines or []):
            line_objs.append(add_line_item(work_order["id"], code, qty, price))
    ctx.update({
        "crew": crew,
        "plan": get_plan(plan["id"]),
        "work_order": get_work_order(work_order["id"]) if work_order else None,
        "lines": line_objs,
    })
    return ctx


def mobilize(work_order_id, crew_id) -> dict:
    return get_success_data(api_client.mobilize_work_order(work_order_id, make_crew_lead_headers(crew_id)))


def begin_work(work_order_id, crew_id) -> dict:
    return get_success_data(api_client.begin_work(work_order_id, make_crew_lead_headers(crew_id)))


def report_installed(work_order_id, crew_id, line_id, installed_qty) -> dict:
    return get_success_data(
        api_client.update_line_item(
            work_order_id, line_id, {"installed_qty": installed_qty}, make_crew_lead_headers(crew_id)
        )
    )


def submit_punch(work_order_id, crew_id) -> dict:
    return get_success_data(api_client.submit_punch(work_order_id, make_crew_lead_headers(crew_id)))


def complete_work_order(work_order_id, crew_id) -> dict:
    return get_success_data(api_client.complete_work_order(work_order_id, make_crew_lead_headers(crew_id)))


# ---------------------------------------------------------------------------
# Tier 3/5: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_completed_spot_repair(*, lines=None, installed_qtys=None, cert_kwargs=None) -> dict:
    """Full SPOT_REPAIR lifecycle to WorkOrder COMPLETED (plan COMPLETED,
    segment REHABILITATED). installed_qtys defaults to scheduled quantities.
    """
    lines = lines or [("SPOT-EA", 1, 250000)]
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=lines, approve=True,
                                     cert_kwargs=cert_kwargs)
    wo_id = ctx["work_order"]["id"]
    crew_id = ctx["crew"]["id"]
    mobilize(wo_id, crew_id)
    begin_work(wo_id, crew_id)
    qtys = installed_qtys if installed_qtys is not None else [q for _, q, _ in lines]
    for line, qty in zip(ctx["lines"], qtys):
        report_installed(wo_id, crew_id, line["id"], qty)
    submit_punch(wo_id, crew_id)
    complete_work_order(wo_id, crew_id)
    ctx.update({
        "work_order": get_work_order(wo_id),
        "plan": get_plan(ctx["plan"]["id"]),
        "segment": get_segment(ctx["segment"]["id"]),
        "district": get_district(ctx["district"]["id"]),
    })
    return ctx


def setup_cipp_ready_to_complete(*, lateral_addresses=("10 Main St", "12 Main St"),
                                 line=("CIPP-8IN-LF", 100, 8000), cert_kwargs=None) -> dict:
    """CIPP_LINING work order in PUNCH_LIST with every completion gate satisfied:
    laterals created and reinstated, POST_CIPP inspection CERTIFIED.
    """
    ck = {"material": "PVC", "defects": [DEFECT_G2_POINT]}
    ck.update(cert_kwargs or {})
    ctx = setup_plan_with_work_order(method="CIPP_LINING", lines=[line], approve=True, cert_kwargs=ck)
    wo_id = ctx["work_order"]["id"]
    crew_id = ctx["crew"]["id"]
    segment_id = ctx["segment"]["id"]
    laterals = [create_lateral(segment_id, address=a, connection_type="WYE") for a in lateral_addresses]
    mobilize(wo_id, crew_id)
    begin_work(wo_id, crew_id)
    report_installed(wo_id, crew_id, ctx["lines"][0]["id"], line[1])
    crew_headers = make_crew_lead_headers(crew_id)
    for lat in laterals:
        get_success_data(api_client.reinstate_lateral(segment_id, lat["id"], crew_headers))
    post = schedule_inspection(segment_id, ctx["cycle"]["id"], ctx["coder"]["id"],
                               scheduled_at="2026-08-10T12:00:00Z", purpose="POST_CIPP")
    drive_inspection_to_coding(post["id"], ctx["coder"]["id"])
    add_defects(post["id"], ctx["coder"]["id"],
                [{"pacp_code": "OBN", "family": "OM", "grade": 1, "distance_m": 5, "clock_position": 0}])
    submit_for_qa(post["id"], ctx["coder"]["id"])
    post = certify_inspection(post["id"], ctx["qa"]["id"])
    submit_punch(wo_id, crew_id)
    ctx.update({
        "laterals": laterals,
        "post_inspection": post,
        "work_order": get_work_order(wo_id),
    })
    return ctx


# ---------------------------------------------------------------------------
# Warranty chain
# ---------------------------------------------------------------------------

def open_warranty_case(ctx, *, clock, scheduled_at="2026-09-02T08:00:00Z",
                       defect_summary="defect observed after rehabilitation") -> dict:
    """Open a warranty case on the ctx segment (creates the linked WARRANTY_RE
    inspection in SCHEDULED). Advances the logical clock first."""
    set_clock(clock)
    payload = create_warranty_case_payload(
        ctx["work_order"]["id"], ctx["cycle"]["id"], ctx["coder"]["id"],
        defect_summary=defect_summary, scheduled_at=scheduled_at,
    )
    return get_success_data(api_client.create_warranty_case(ctx["segment"]["id"], payload, ENGINEER))


def drive_reinspection_to_certified(case, coder_id, qa_id, defects) -> dict:
    """Drive the case's linked WARRANTY_RE inspection to CERTIFIED. The case
    follows OPENED -> RE_INSPECTION automatically when the inspection starts."""
    re_inspection_id = case["re_inspection_id"]
    drive_inspection_to_coding(re_inspection_id, coder_id)
    add_defects(re_inspection_id, coder_id, defects)
    submit_for_qa(re_inspection_id, coder_id)
    return certify_inspection(re_inspection_id, qa_id)


# ---------------------------------------------------------------------------
# Bypass helpers
# ---------------------------------------------------------------------------

def create_bypass_plan(work_order_id, crew_id, *, window_start, window_end, pump_capacity_gpm) -> dict:
    payload = create_bypass_payload(window_start=window_start, window_end=window_end,
                                    pump_capacity_gpm=pump_capacity_gpm)
    return get_success_data(
        api_client.create_bypass_plan(work_order_id, payload, make_crew_lead_headers(crew_id))
    )


def approve_bypass_plan(bypass_plan_id) -> dict:
    return get_success_data(api_client.approve_bypass_plan(bypass_plan_id, ENGINEER))


# ---------------------------------------------------------------------------
# Customer notice setup
# ---------------------------------------------------------------------------

def setup_notice_ctx(*, event_start, address="11 Elm St", channel="EMAIL",
                     notice_lead_hours=48, clock=DEFAULT_CLOCK) -> dict:
    """Approved CIPP plan + ISSUED work order + matching active lateral + one
    QUEUED notice for the given event_start."""
    ctx = setup_plan_with_work_order(
        method="CIPP_LINING",
        lines=None,
        approve=True,
        cert_kwargs={
            "material": "PVC",
            "defects": [DEFECT_G2_POINT],
            "clock": clock,
            "district_overrides": {"notice_lead_hours": notice_lead_hours},
        },
    )
    create_lateral(ctx["segment"]["id"], address=address, connection_type="WYE")
    notice = get_success_data(
        api_client.create_customer_notice(
            ctx["work_order"]["id"], create_notice_payload(address, channel, event_start), CSR
        )
    )
    ctx["notice"] = notice
    return ctx


# ---------------------------------------------------------------------------
# Flow monitoring helpers
# ---------------------------------------------------------------------------

def create_flow_period(district_id, *, basin_label, phase, window_start, window_end) -> dict:
    payload = create_flow_period_payload(basin_label=basin_label, phase=phase,
                                         window_start=window_start, window_end=window_end)
    return get_success_data(api_client.create_flow_period(district_id, payload, ENGINEER))


def activate_flow_period(period_id) -> dict:
    return get_success_data(api_client.activate_flow_period(period_id, ENGINEER))


def close_flow_period(period_id, dry_weather_avg_gpm, peak_storm_gpm) -> dict:
    payload = {"dry_weather_avg_gpm": dry_weather_avg_gpm, "peak_storm_gpm": peak_storm_gpm}
    return get_success_data(api_client.close_flow_period(period_id, payload, ENGINEER))


def analyze_flow_period(period_id) -> dict:
    return get_success_data(api_client.analyze_flow_period(period_id, ENGINEER))


def create_closed_period(district_id, *, basin_label, phase, window_start, window_end,
                         dry_weather_avg_gpm, peak_storm_gpm) -> dict:
    period = create_flow_period(district_id, basin_label=basin_label, phase=phase,
                                window_start=window_start, window_end=window_end)
    activate_flow_period(period["id"])
    return close_flow_period(period["id"], dry_weather_avg_gpm, peak_storm_gpm)
