"""Composite setup helpers for the gas leak survey integrity program tests.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the server is relaunched with an empty database before every test). Identity
threading follows PRD §2.1: every role is entity-backed, so each created
personnel record's id is threaded into its role headers.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_apply_permit_payload,
    create_assignment_payload,
    create_calibration_payload,
    create_compliance_officer_payload,
    create_compliance_report_payload,
    create_cp_reading_payload,
    create_field_technician_payload,
    create_instrument_payload,
    create_leak_payload,
    create_pipe_segment_payload,
    create_regrade_payload,
    create_repair_crew_payload,
    create_schedule_repair_payload,
    create_simple_personnel_payload,
    create_snapshot_payload,
    create_survey_route_payload,
    create_survey_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_calibration_tech_headers,
    make_compliance_officer_headers,
    make_dispatch_coordinator_headers,
    make_field_technician_headers,
    make_integrity_analyst_headers,
)

BOOTSTRAP_IA_HEADERS = TEST_USERS["integrity_analyst_headers"]
DEFAULT_WINDOW = ("2026-07-01T00:00:00Z", "2026-12-31T23:59:59Z")


# ---------------------------------------------------------------------------
# Tier 0: org bootstrap (clock + one persisted record per role)
# ---------------------------------------------------------------------------

def make_org(
    clock: str = DEFAULT_CLOCK,
    qualified_methods=("WALKING",),
    jurisdiction_scope=("PHMSA", "STATE_PUC"),
) -> dict:
    """Pin the logical clock and provision one record per role.

    Returns a context dict with the records and their role headers.
    """
    get_success_data(api_client.set_clock({"to_iso8601": clock}, BOOTSTRAP_IA_HEADERS))

    # PRD §3.3 requires employee_code uniqueness, and a single test may build
    # more than one org against the same server boot — uniquify per call.
    tag = uuid.uuid4().hex[:8]
    ia = get_success_data(api_client.create_integrity_analyst(
        create_simple_personnel_payload(
            employee_code=f"IA-{tag}", full_name="Analyst One"),
        BOOTSTRAP_IA_HEADERS,
    ))
    ia_h = make_integrity_analyst_headers(ia["id"])

    ft = get_success_data(api_client.create_field_technician(
        create_field_technician_payload(
            employee_code=f"FT-{tag}",
            qualified_methods=list(qualified_methods)),
        ia_h,
    ))
    ct = get_success_data(api_client.create_calibration_tech(
        create_simple_personnel_payload(
            employee_code=f"CT-{tag}", full_name="Cal One"),
        ia_h,
    ))
    dc = get_success_data(api_client.create_dispatch_coordinator(
        create_simple_personnel_payload(
            employee_code=f"DC-{tag}", full_name="Disp One"),
        ia_h,
    ))
    co = get_success_data(api_client.create_compliance_officer(
        create_compliance_officer_payload(
            employee_code=f"CO-{tag}",
            jurisdiction_scope=list(jurisdiction_scope)),
        ia_h,
    ))

    return {
        "ia": ia, "ft": ft, "ct": ct, "dc": dc, "co": co,
        "ia_h": ia_h,
        "ft_h": make_field_technician_headers(ft["id"]),
        "ct_h": make_calibration_tech_headers(ct["id"]),
        "dc_h": make_dispatch_coordinator_headers(dc["id"]),
        "co_h": make_compliance_officer_headers(co["id"]),
    }


def set_clock(ctx: dict, to_iso8601: str):
    """Advance the logical clock as the org's IntegrityAnalyst (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ctx["ia_h"]))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators layered on the org
# ---------------------------------------------------------------------------

def make_instrument(
    ctx: dict,
    serial_number: str = "I-CGI-1",
    instrument_type: str = "CGI",
    calibrate: bool = True,
    reference_gas_ppm: float = 100.0,
    observed_ppm: float = 100.0,
) -> dict:
    """Create an instrument via the CalibrationTech; optionally record a passing calibration."""
    instrument = get_success_data(api_client.create_instrument(
        create_instrument_payload(serial_number=serial_number, instrument_type=instrument_type),
        ctx["ct_h"],
    ))
    if calibrate:
        get_success_data(api_client.calibrate_instrument(
            instrument["id"],
            create_calibration_payload(
                reference_gas_ppm=reference_gas_ppm, observed_ppm=observed_ppm,
            ),
            ctx["ct_h"],
        ))
        instrument = get_success_data(api_client.get_instrument(instrument["id"], ctx["ct_h"]))
    ctx["instrument"] = instrument
    return instrument


def make_segment(ctx: dict, **overrides) -> dict:
    segment = get_success_data(api_client.create_pipe_segment(
        create_pipe_segment_payload(**overrides), ctx["ia_h"],
    ))
    ctx.setdefault("segments", []).append(segment)
    return segment


def make_route(
    ctx: dict,
    segment_ids,
    route_code: str = "R-1",
    survey_method: str = "WALKING",
    window=DEFAULT_WINDOW,
    dispatch: bool = True,
) -> dict:
    """Create a route, attach the given segments in order, optionally dispatch it."""
    route = get_success_data(api_client.create_survey_route(
        create_survey_route_payload(
            route_code=route_code,
            survey_method=survey_method,
            scheduled_window_start=window[0],
            scheduled_window_end=window[1],
        ),
        ctx["dc_h"],
    ))
    for index, segment_id in enumerate(segment_ids, start=1):
        get_success_data(api_client.add_route_segment_assignment(
            route["id"],
            create_assignment_payload(segment_id, sequence_index=index),
            ctx["dc_h"],
        ))
    if dispatch:
        route = get_success_data(api_client.dispatch_route(route["id"], ctx["dc_h"]))
    ctx["route"] = route
    return route


def make_run(
    ctx: dict,
    route_id: str,
    instrument_id: str,
    distance_covered_feet: float = 1000.0,
    submit: bool = True,
    accept: bool = False,
) -> dict:
    """Create a survey run as the org's FieldTechnician; optionally submit/accept it."""
    run = get_success_data(api_client.create_survey_run(
        create_survey_run_payload(
            route_id, instrument_id, distance_covered_feet=distance_covered_feet,
        ),
        ctx["ft_h"],
    ))
    if submit:
        run = get_success_data(api_client.submit_run(run["id"], ctx["ft_h"]))
    if accept:
        run = get_success_data(api_client.accept_run(run["id"], ctx["ia_h"]))
    ctx["run"] = run
    return run


def make_leak(ctx: dict, segment_id: str, run_id: str, **overrides) -> dict:
    leak = get_success_data(api_client.create_leak(
        create_leak_payload(segment_id, run_id, **overrides), ctx["ft_h"],
    ))
    ctx.setdefault("leaks", []).append(leak)
    return leak


def make_crew(ctx: dict, **overrides) -> dict:
    crew = get_success_data(api_client.create_repair_crew(
        create_repair_crew_payload(**overrides), ctx["dc_h"],
    ))
    ctx["crew"] = crew
    return crew


def make_snapshot(ctx: dict, label: str, kind: str) -> dict:
    return get_success_data(api_client.create_risk_model_snapshot(
        create_snapshot_payload(snapshot_label=label, snapshot_kind=kind), ctx["ia_h"],
    ))


# ---------------------------------------------------------------------------
# Tier 2: composite survey preambles (org + instrument + segment + route + run)
# ---------------------------------------------------------------------------

def setup_dispatched_route(
    segment_overrides=None,
    route_code: str = "R-1",
    window=DEFAULT_WINDOW,
    extra_segments=None,
) -> dict:
    """Org + calibrated CGI instrument + segment(s) + DISPATCHED route covering them."""
    ctx = make_org()
    make_instrument(ctx, serial_number=f"I-{route_code}")
    segment = make_segment(ctx, **(segment_overrides or {}))
    segment_ids = [segment["id"]]
    for extra in (extra_segments or []):
        segment_ids.append(make_segment(ctx, **extra)["id"])
    make_route(ctx, segment_ids, route_code=route_code, window=window)
    return ctx


def setup_submitted_run(
    distance_covered_feet: float = 1000.0,
    segment_overrides=None,
    route_code: str = "R-1",
    window=DEFAULT_WINDOW,
) -> dict:
    """Dispatched route + a SUBMITTED survey run by the org's FieldTechnician."""
    ctx = setup_dispatched_route(
        segment_overrides=segment_overrides, route_code=route_code, window=window,
    )
    make_run(ctx, ctx["route"]["id"], ctx["instrument"]["id"], distance_covered_feet)
    return ctx


def setup_accepted_run(
    distance_covered_feet: float = 1000.0,
    segment_overrides=None,
    route_code: str = "R-1",
    window=DEFAULT_WINDOW,
) -> dict:
    """Submitted run accepted by the org's IntegrityAnalyst (segregation preserved)."""
    ctx = setup_submitted_run(
        distance_covered_feet=distance_covered_feet,
        segment_overrides=segment_overrides,
        route_code=route_code,
        window=window,
    )
    ctx["run"] = get_success_data(api_client.accept_run(ctx["run"]["id"], ctx["ia_h"]))
    return ctx


def setup_open_leak(
    leak_overrides=None,
    segment_overrides=None,
    route_code: str = "R-1",
    accept_run: bool = True,
    distance_covered_feet: float = 1000.0,
) -> dict:
    """Full survey preamble + one OPEN leak (defaults grade G2 on non-HCA)."""
    if accept_run:
        ctx = setup_accepted_run(
            distance_covered_feet=distance_covered_feet,
            segment_overrides=segment_overrides,
            route_code=route_code,
        )
    else:
        ctx = setup_submitted_run(
            distance_covered_feet=distance_covered_feet,
            segment_overrides=segment_overrides,
            route_code=route_code,
        )
    segment = ctx["segments"][0]
    ctx["leak"] = make_leak(ctx, segment["id"], ctx["run"]["id"], **(leak_overrides or {}))
    return ctx


def setup_completed_route(
    segment_overrides=None,
    route_code: str = "R-1",
    distance_covered_feet: float = 1000.0,
    pre_complete=None,
) -> dict:
    """Route driven IN_PROGRESS -> COMPLETED with one ACCEPTED run.

    pre_complete: optional callable(ctx) invoked after the run is accepted but
    before the route completes (e.g., to register a leak or CP reading that
    must exist at completion time).
    """
    ctx = setup_dispatched_route(segment_overrides=segment_overrides, route_code=route_code)
    get_success_data(api_client.start_route(ctx["route"]["id"], ctx["ft_h"]))
    make_run(ctx, ctx["route"]["id"], ctx["instrument"]["id"], distance_covered_feet,
             submit=True, accept=True)
    if pre_complete is not None:
        pre_complete(ctx)
    ctx["route"] = get_success_data(api_client.complete_route(ctx["route"]["id"], ctx["ft_h"]))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: repair lifecycle
# ---------------------------------------------------------------------------

def setup_repair_order(
    leak_overrides=None,
    repair_method: str = "CLAMP",
    segment_overrides=None,
    route_code: str = "R-1",
) -> dict:
    """OPEN leak + schedule-repair: returns ctx with order in PENDING_DISPATCH."""
    ctx = setup_open_leak(
        leak_overrides=leak_overrides, segment_overrides=segment_overrides, route_code=route_code,
    )
    order = get_success_data(api_client.schedule_repair(
        ctx["leak"]["id"],
        create_schedule_repair_payload(ctx["leak"]["version"], repair_method=repair_method),
        ctx["dc_h"],
    ))
    ctx["order"] = order
    return ctx


def setup_dispatched_repair(
    leak_overrides=None,
    repair_method: str = "CLAMP",
    crew_overrides=None,
    segment_overrides=None,
    route_code: str = "R-1",
) -> dict:
    """Repair order dispatched to an explicitly named crew."""
    ctx = setup_repair_order(
        leak_overrides=leak_overrides, repair_method=repair_method,
        segment_overrides=segment_overrides, route_code=route_code,
    )
    crew = make_crew(ctx, **(crew_overrides or {}))
    ctx["order"] = get_success_data(api_client.dispatch_repair_order(
        ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"],
    ))
    return ctx


def setup_completed_repair(
    leak_overrides=None,
    repair_method: str = "CLAMP",
    crew_overrides=None,
    segment_overrides=None,
    route_code: str = "R-1",
) -> dict:
    """Order driven to WORK_COMPLETE; the leak is REPAIRED_PENDING_VERIFICATION."""
    ctx = setup_dispatched_repair(
        leak_overrides=leak_overrides, repair_method=repair_method,
        crew_overrides=crew_overrides, segment_overrides=segment_overrides,
        route_code=route_code,
    )
    get_success_data(api_client.arrive_on_site(ctx["order"]["id"], ctx["dc_h"]))
    ctx["order"] = get_success_data(api_client.mark_work_complete(ctx["order"]["id"], ctx["dc_h"]))
    return ctx


def add_post_repair_survey(ctx: dict, route_code: str = "R-POST") -> dict:
    """A second route over the same segment with an ACCEPTED, leak-free run."""
    segment = ctx["segments"][0]
    route = make_route(ctx, [segment["id"]], route_code=route_code)
    run = make_run(
        ctx, route["id"], ctx["instrument"]["id"],
        distance_covered_feet=segment.get("length_feet", 1000.0),
        submit=True, accept=True,
    )
    ctx["post_repair_run"] = run
    return run


def setup_verifiable_leak(**kwargs) -> dict:
    """Completed repair + ACCEPTED post-repair leak-free survey (PRD §3.7 gate satisfied)."""
    ctx = setup_completed_repair(**kwargs)
    add_post_repair_survey(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: excavation permit track
# ---------------------------------------------------------------------------

def setup_granted_permit(
    expires_at: str = "2026-12-31T23:59:59Z",
    leak_overrides=None,
    segment_overrides=None,
    route_code: str = "R-1",
) -> dict:
    """G1 leak + CUT_AND_REPLACE order + ExcavationPermit granted by the officer."""
    g1_defaults = {
        "concentration_ppm": 50000.0,
        "distance_to_building_feet": 2.0,
        "bar_hole_reading_pct_lel": 50.0,
        "is_migration_evidence": True,
    }
    g1_defaults.update(leak_overrides or {})
    ctx = setup_repair_order(
        leak_overrides=g1_defaults,
        repair_method="CUT_AND_REPLACE",
        segment_overrides=segment_overrides,
        route_code=route_code,
    )
    permit = get_success_data(api_client.apply_permit(
        ctx["order"]["id"],
        create_apply_permit_payload(
            permit_number=f"PERMIT-{route_code}", expires_at=expires_at,
        ),
        ctx["co_h"],
    ))
    permit = get_success_data(api_client.grant_permit(permit["id"], ctx["co_h"]))
    ctx["permit"] = permit
    ctx["order"] = get_success_data(api_client.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: compliance report lifecycle
# ---------------------------------------------------------------------------

def setup_draft_report(
    period=("2026-01-01T00:00:00Z", "2026-06-30T23:59:59Z"),
    regulator: str = "PHMSA",
    jurisdiction_scope=("PHMSA", "STATE_PUC"),
) -> dict:
    """Org + CURRENT LEAK_SECTION and CP_SECTION snapshots + DRAFT report."""
    ctx = make_org(jurisdiction_scope=jurisdiction_scope)
    ctx["snap_leak"] = make_snapshot(ctx, "leak-section", "LEAK_SECTION")
    ctx["snap_cp"] = make_snapshot(ctx, "cp-section", "CP_SECTION")
    report = get_success_data(api_client.create_compliance_report(
        create_compliance_report_payload(
            reporting_period_start=period[0],
            reporting_period_end=period[1],
            regulator=regulator,
        ),
        ctx["co_h"],
    ))
    ctx["report"] = report
    return ctx


def setup_pending_review_report(**kwargs) -> dict:
    """DRAFT report with snapshots bound and submit-for-review accepted (snapshots PINNED)."""
    ctx = setup_draft_report(**kwargs)
    report = ctx["report"]
    bound = get_success_data(api_client.bind_snapshots(
        report["id"],
        {
            "leak_section_snapshot_id": ctx["snap_leak"]["id"],
            "cp_section_snapshot_id": ctx["snap_cp"]["id"],
            "expected_report_version": report["version"],
        },
        ctx["co_h"],
    ))
    ctx["report"] = get_success_data(api_client.submit_for_review(
        report["id"], {"expected_report_version": bound["version"]}, ctx["co_h"],
    ))
    return ctx


def setup_submitted_report(**kwargs) -> dict:
    """Report filed with the regulator (SUBMITTED)."""
    ctx = setup_pending_review_report(**kwargs)
    ctx["report"] = get_success_data(api_client.submit_to_regulator(
        ctx["report"]["id"], ctx["co_h"],
    ))
    return ctx
