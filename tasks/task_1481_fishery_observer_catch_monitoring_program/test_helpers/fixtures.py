"""Composite setup helpers for the fishery observer program test suite.

Every helper builds its preconditions from scratch through the public API
(each test starts against an empty database) and fails loudly with a clear
"Setup step failed" message when a precondition cannot be reached, so tests
stay focused on assertions. Identity threading rule: calls gated on an
entity-backed actor always use make_*_headers(entity["id"]), never the
shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_coverage_plan_payload,
    create_debriefer_payload,
    create_deployment_payload,
    create_em_enrollment_payload,
    create_em_reviewer_payload,
    create_em_trip_payload,
    create_fishery_payload,
    create_harassment_report_payload,
    create_haul_sample_payload,
    create_observer_payload,
    create_safety_inspection_payload,
    create_vessel_operator_payload,
    create_vessel_payload,
)
from .test_users import (
    TEST_USERS,
    make_debriefer_headers,
    make_observer_headers,
    make_vessel_operator_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["program_coordinator_headers"]

DEFAULT_PERIOD_START = TEST_DEFAULTS["PLAN_PERIOD_START"]
DEFAULT_PERIOD_END = TEST_DEFAULTS["PLAN_PERIOD_END"]
DEFAULT_DEADLINE = TEST_DEFAULTS["NOTICE_RESPONSE_DEADLINE"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation helpers
# ---------------------------------------------------------------------------

def make_fishery(**overrides) -> dict:
    resp = api_client.create_fishery(create_fishery_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_operator(**overrides) -> dict:
    resp = api_client.create_vessel_operator(create_vessel_operator_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_observer(certification_level: str = "LEAD", **overrides) -> dict:
    resp = api_client.create_observer(
        create_observer_payload(certification_level=certification_level, **overrides), ADMIN
    )
    return get_success_data(resp)


def make_debriefer(**overrides) -> dict:
    resp = api_client.create_debriefer(create_debriefer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_em_reviewer(**overrides) -> dict:
    resp = api_client.create_em_reviewer(create_em_reviewer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_vessel(operator: dict, fishery: dict, *, activate: bool = True, **overrides) -> dict:
    """Register a vessel as its operator (ownership-gated call) and optionally
    have an administrator move it REGISTERED -> ACTIVE."""
    payload = create_vessel_payload(
        operator_id=operator["id"], fishery_id=fishery["id"], **overrides
    )
    vessel = get_success_data(
        api_client.create_vessel(payload, make_vessel_operator_headers(operator["id"]))
    )
    if activate:
        vessel = get_success_data(
            api_client.patch_vessel(vessel["id"], {"status": "ACTIVE"}, ADMIN)
        )
    return vessel


def make_coverage_plan(fishery: dict, **overrides) -> dict:
    payload = create_coverage_plan_payload(fishery_id=fishery["id"], **overrides)
    return get_success_data(api_client.create_coverage_plan(payload, COORD))


def publish_plan(plan_id: str) -> dict:
    return get_success_data(api_client.publish_coverage_plan(plan_id, {}, COORD))


def run_selection(plan_id: str,
                  notice_response_deadline: str = DEFAULT_DEADLINE,
                  expected_coverage_plan_version=None) -> dict:
    """Launch a selection run; reads the plan's current version when the caller
    does not pin one explicitly."""
    if expected_coverage_plan_version is None:
        plan = get_success_data(api_client.get_coverage_plan(plan_id, COORD))
        expected_coverage_plan_version = plan["version"]
    payload = {
        "notice_response_deadline": notice_response_deadline,
        "expected_coverage_plan_version": expected_coverage_plan_version,
    }
    return get_success_data(api_client.create_selection_run(plan_id, payload, COORD))


def make_completed_plan(fishery: dict, **plan_overrides) -> dict:
    """Plan published + one selection run executed -> SELECTION_COMPLETED."""
    plan = make_coverage_plan(fishery, **plan_overrides)
    publish_plan(plan["id"])
    run_selection(plan["id"])
    return get_success_data(api_client.get_coverage_plan(plan["id"], COORD))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: notice helpers
# ---------------------------------------------------------------------------

def get_notice_for_vessel(plan_id: str, vessel_id: str) -> dict:
    rows = get_success_data(
        api_client.list_selection_notices(
            COORD, params={"coverage_plan_id": plan_id, "vessel_id": vessel_id}
        )
    )
    assert len(rows) >= 1, (
        f"Setup failed: no selection notice for vessel {vessel_id} under plan {plan_id}"
    )
    return rows[0]


def accept_notice(notice_id: str, operator_id: str) -> dict:
    return get_success_data(
        api_client.accept_selection_notice(
            notice_id, {}, make_vessel_operator_headers(operator_id)
        )
    )


def setup_notice_scenario(*, coverage_target_pct: float = 0.30,
                          priority_gear: str = "TRAWL", gear_type: str = "TRAWL",
                          length_ft: float = 55,
                          projected_fleet_effort_days: int = 100,
                          projected_em_effort_days: int = 0,
                          period_start: str = DEFAULT_PERIOD_START,
                          period_end: str = DEFAULT_PERIOD_END,
                          observer_level: str = "LEAD",
                          with_debriefer: bool = True,
                          accept: bool = True,
                          notice_response_deadline: str = DEFAULT_DEADLINE,
                          declared_annual_revenue_cents=None) -> dict:
    """Fishery + operator + observer (+ debriefer) + ACTIVE vessel + plan
    published + selection run executed + the vessel's notice (ACCEPTED unless
    accept=False). Returns the full bundle."""
    fishery = make_fishery(
        coverage_target_pct=coverage_target_pct, priority_gear=priority_gear
    )
    operator = make_operator()
    observer = make_observer(certification_level=observer_level)
    debriefer = make_debriefer() if with_debriefer else None
    vessel = make_vessel(
        operator, fishery, gear_type=gear_type, length_ft=length_ft,
        declared_annual_revenue_cents=declared_annual_revenue_cents,
    )
    plan = make_coverage_plan(
        fishery,
        period_start=period_start,
        period_end=period_end,
        projected_fleet_effort_days=projected_fleet_effort_days,
        projected_em_effort_days=projected_em_effort_days,
    )
    publish_plan(plan["id"])
    run = run_selection(plan["id"], notice_response_deadline=notice_response_deadline)
    notice = get_notice_for_vessel(plan["id"], vessel["id"])
    if accept:
        accept_notice(notice["id"], operator["id"])
        notice = get_success_data(api_client.get_selection_notice(notice["id"], COORD))
    return {
        "fishery": fishery,
        "operator": operator,
        "observer": observer,
        "debriefer": debriefer,
        "vessel": vessel,
        "plan": get_success_data(api_client.get_coverage_plan(plan["id"], COORD)),
        "run": run,
        "notice": notice,
    }


# ---------------------------------------------------------------------------
# Tier 3: deployment lifecycle helpers
# ---------------------------------------------------------------------------

def create_deployment_for_notice(notice_id: str, observer_id: str,
                                 departure: str, return_date: str) -> dict:
    """Create a deployment, always reading the notice's fresh version first so
    the OCC check passes for a well-formed setup."""
    notice = get_success_data(api_client.get_selection_notice(notice_id, COORD))
    payload = create_deployment_payload(
        selection_notice_id=notice_id,
        observer_id=observer_id,
        scheduled_departure_date=departure,
        scheduled_return_date=return_date,
        expected_selection_notice_version=notice["version"],
    )
    return get_success_data(api_client.create_deployment(payload, COORD))


def record_pass_inspection(deployment_id: str, observer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_safety_inspection(
            deployment_id,
            create_safety_inspection_payload(**overrides),
            make_observer_headers(observer_id),
        )
    )


def record_fail_inspection(deployment_id: str, observer_id: str, **overrides) -> dict:
    defaults = {"comms_equipment_ok": False,
                "deficiency_notes": "VHF radio inoperable"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_safety_inspection(
            deployment_id,
            create_safety_inspection_payload(**defaults),
            make_observer_headers(observer_id),
        )
    )


def board_deployment(deployment_id: str, observer_id: str) -> dict:
    return get_success_data(
        api_client.board_deployment(deployment_id, {}, make_observer_headers(observer_id))
    )


def record_haul_sample(deployment_id: str, observer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_haul_sample(
            deployment_id,
            create_haul_sample_payload(**overrides),
            make_observer_headers(observer_id),
        )
    )


def return_deployment(deployment_id: str, observer_id: str, actual_return_date: str) -> dict:
    return get_success_data(
        api_client.return_deployment(
            deployment_id,
            {"actual_return_date": actual_return_date},
            make_observer_headers(observer_id),
        )
    )


def submit_data(deployment_id: str, observer_id: str) -> dict:
    return get_success_data(
        api_client.submit_deployment_data(
            deployment_id, {}, make_observer_headers(observer_id)
        )
    )


def assign_debriefer(deployment_id: str, debriefer_id: str) -> dict:
    return get_success_data(
        api_client.assign_debriefer(deployment_id, {"debriefer_id": debriefer_id}, COORD)
    )


def drive_deployment_to_validated(deployment_id: str, observer_id: str,
                                  debriefer_id: str, actual_return_date: str,
                                  *, haul_date: str,
                                  sampled_weight_kg=100,
                                  total_haul_weight_kg=500) -> dict:
    """safety PASS -> board -> one haul sample -> return -> submit-data ->
    assign debriefer -> verify sample -> validate-data. Ends DATA_VALIDATED."""
    deb = make_debriefer_headers(debriefer_id)
    record_pass_inspection(deployment_id, observer_id)
    board_deployment(deployment_id, observer_id)
    sample = record_haul_sample(
        deployment_id, observer_id,
        haul_date=haul_date,
        sampled_weight_kg=sampled_weight_kg,
        total_haul_weight_kg=total_haul_weight_kg,
    )
    return_deployment(deployment_id, observer_id, actual_return_date)
    submit_data(deployment_id, observer_id)
    assign_debriefer(deployment_id, debriefer_id)
    get_success_data(api_client.verify_haul_sample(sample["id"], {}, deb))
    validated = get_success_data(api_client.validate_data(deployment_id, {}, deb))
    return {"deployment": validated, "sample": sample}


def drive_deployment_to_closed(deployment_id: str, observer_id: str,
                               debriefer_id: str, actual_return_date: str,
                               *, haul_date: str,
                               sampled_weight_kg=100,
                               total_haul_weight_kg=500) -> dict:
    """Full lifecycle to CLOSED. Returns the closed deployment."""
    drive_deployment_to_validated(
        deployment_id, observer_id, debriefer_id, actual_return_date,
        haul_date=haul_date,
        sampled_weight_kg=sampled_weight_kg,
        total_haul_weight_kg=total_haul_weight_kg,
    )
    return get_success_data(api_client.close_deployment(deployment_id, {}, COORD))


def setup_closed_deployment_scenario(
        *, departure: str = "2026-09-10T00:00:00Z",
        return_date: str = "2026-09-19T00:00:00Z",
        haul_date: str = "2026-09-12T00:00:00Z", **scenario_kw) -> dict:
    """Accepted notice + one deployment driven to CLOSED. Returns bundle."""
    bundle = setup_notice_scenario(**scenario_kw)
    deployment = create_deployment_for_notice(
        bundle["notice"]["id"], bundle["observer"]["id"], departure, return_date
    )
    deployment = drive_deployment_to_closed(
        deployment["id"], bundle["observer"]["id"], bundle["debriefer"]["id"],
        return_date, haul_date=haul_date,
    )
    bundle["deployment"] = deployment
    bundle["notice"] = get_success_data(
        api_client.get_selection_notice(bundle["notice"]["id"], COORD)
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: invoice fixtures
# ---------------------------------------------------------------------------

def find_invoice_for_vessel(plan_id: str, vessel_id: str) -> dict:
    """Return the vessel's (single) invoice under the plan."""
    rows = get_success_data(
        api_client.list_invoices(
            COORD, params={"coverage_plan_id": plan_id, "vessel_id": vessel_id}
        )
    )
    assert len(rows) == 1, (
        f"Setup failed: expected exactly one invoice for vessel {vessel_id}, "
        f"got {len(rows)}"
    )
    return rows[0]


def generate_invoice_for_vessel(plan_id: str, vessel_id: str) -> dict:
    """Run invoice generation and return the vessel's invoice."""
    get_success_data(api_client.generate_invoices(plan_id, {}, COORD))
    return find_invoice_for_vessel(plan_id, vessel_id)


def setup_issued_invoice_scenario(*, issue_clock: str = "2026-09-25T00:00:00Z",
                                  issue: bool = True, **scenario_kw) -> dict:
    """One CLOSED 10-day deployment + its generated invoice (ISSUED by the
    default coordinator identity unless issue=False, which leaves it DRAFT)."""
    bundle = setup_closed_deployment_scenario(**scenario_kw)
    invoice = generate_invoice_for_vessel(bundle["plan"]["id"], bundle["vessel"]["id"])
    if issue:
        set_clock(issue_clock)
        invoice = get_success_data(api_client.issue_invoice(invoice["id"], {}, COORD))
    bundle["invoice"] = invoice
    return bundle


def setup_two_vessel_billed_scenario(*, length_a: float = 50,
                                     length_b: float = 30,
                                     declared_revenue_b=None) -> dict:
    """Two vessels (defaults: one STANDARD-length, one SMALL_VESSEL-length),
    each with one CLOSED 10-day deployment under the same plan; invoices
    generated. Returns bundle with both invoices."""
    fishery = make_fishery(coverage_target_pct=0.30, priority_gear="LONGLINE",
                           region="Gulf of Alaska")
    operator = make_operator()
    obs_a = make_observer()
    obs_b = make_observer()
    debriefer = make_debriefer()
    vessel_a = make_vessel(operator, fishery, length_ft=length_a, gear_type="LONGLINE")
    vessel_b = make_vessel(
        operator, fishery, length_ft=length_b, gear_type="LONGLINE",
        declared_annual_revenue_cents=declared_revenue_b,
    )
    plan = make_coverage_plan(
        fishery, projected_fleet_effort_days=200, projected_em_effort_days=0
    )
    publish_plan(plan["id"])
    run = run_selection(plan["id"])
    notice_a = get_notice_for_vessel(plan["id"], vessel_a["id"])
    notice_b = get_notice_for_vessel(plan["id"], vessel_b["id"])
    accept_notice(notice_a["id"], operator["id"])
    accept_notice(notice_b["id"], operator["id"])
    dep_a = create_deployment_for_notice(
        notice_a["id"], obs_a["id"],
        "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
    )
    drive_deployment_to_closed(
        dep_a["id"], obs_a["id"], debriefer["id"], "2026-09-19T00:00:00Z",
        haul_date="2026-09-12T00:00:00Z",
    )
    dep_b = create_deployment_for_notice(
        notice_b["id"], obs_b["id"],
        "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
    )
    drive_deployment_to_closed(
        dep_b["id"], obs_b["id"], debriefer["id"], "2026-09-19T00:00:00Z",
        haul_date="2026-09-12T00:00:00Z",
    )
    generation = get_success_data(api_client.generate_invoices(plan["id"], {}, COORD))
    rows_a = get_success_data(
        api_client.list_invoices(
            COORD, params={"coverage_plan_id": plan["id"], "vessel_id": vessel_a["id"]}
        )
    )
    rows_b = get_success_data(
        api_client.list_invoices(
            COORD, params={"coverage_plan_id": plan["id"], "vessel_id": vessel_b["id"]}
        )
    )
    assert len(rows_a) == 1 and len(rows_b) == 1, (
        "Setup failed: expected one invoice per vessel"
    )
    return {
        "fishery": fishery, "operator": operator, "debriefer": debriefer,
        "observer_a": obs_a, "observer_b": obs_b,
        "vessel_a": vessel_a, "vessel_b": vessel_b,
        "plan": get_success_data(api_client.get_coverage_plan(plan["id"], COORD)),
        "run": run,
        "notice_a": notice_a, "notice_b": notice_b,
        "deployment_a": dep_a, "deployment_b": dep_b,
        "generation": generation,
        "invoice_a": rows_a[0], "invoice_b": rows_b[0],
    }


# ---------------------------------------------------------------------------
# Tier 5: delinquency / harassment / EM composite fixtures
# ---------------------------------------------------------------------------

def setup_delinquent_operator_scenario(*, with_open_deployment: bool = False,
                                       reactivate_vessel: bool = False) -> dict:
    """Closed 10-day deployment D1 -> invoice generated -> issued at clock
    2026-09-25 (due 2026-10-25) -> clock advanced to 2026-10-26 -> ops run
    fires the delinquency cascade. Optionally pre-creates a second SCHEDULED
    deployment D2 before the run (cascade target), and optionally reactivates
    the vessel manually after the cascade."""
    bundle = setup_issued_invoice_scenario()
    if with_open_deployment:
        obs2 = make_observer()
        deployment2 = create_deployment_for_notice(
            bundle["notice"]["id"], obs2["id"],
            "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z",
        )
        bundle["observer2"] = obs2
        bundle["deployment2"] = deployment2
    set_clock("2026-10-26T00:00:00Z")
    bundle["ops_result"] = get_success_data(api_client.ops_run({}, ADMIN))
    if reactivate_vessel:
        bundle["vessel"] = get_success_data(
            api_client.patch_vessel(bundle["vessel"]["id"], {"status": "ACTIVE"}, ADMIN)
        )
    return bundle


def setup_harassment_under_review_scenario(*, clock: str = "2026-09-12T00:00:00Z") -> dict:
    """Deployment AT_SEA (2026-09-10..2026-09-19), logical clock moved forward,
    harassment report filed by the deployment's observer and moved
    FILED -> UNDER_REVIEW."""
    bundle = setup_notice_scenario()
    obs_id = bundle["observer"]["id"]
    deployment = create_deployment_for_notice(
        bundle["notice"]["id"], obs_id,
        "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
    )
    record_pass_inspection(deployment["id"], obs_id)
    board_deployment(deployment["id"], obs_id)
    set_clock(clock)
    report = get_success_data(
        api_client.create_harassment_report(
            deployment["id"],
            create_harassment_report_payload(),
            make_observer_headers(obs_id),
        )
    )
    get_success_data(api_client.start_harassment_review(report["id"], {}, COORD))
    bundle["deployment"] = deployment
    bundle["report"] = report
    return bundle


def setup_em_active_vessel_scenario() -> dict:
    """Vessel ACTIVE with an EM enrollment approved and activated, so the
    vessel's monitoring_mode is ELECTRONIC_MONITORING."""
    fishery = make_fishery()
    operator = make_operator()
    vessel = make_vessel(operator, fishery)
    op_headers = make_vessel_operator_headers(operator["id"])
    enrollment = get_success_data(
        api_client.create_em_enrollment(
            create_em_enrollment_payload(vessel_id=vessel["id"]), op_headers
        )
    )
    get_success_data(api_client.approve_em_enrollment(enrollment["id"], {}, ADMIN))
    enrollment = get_success_data(
        api_client.activate_em_enrollment(enrollment["id"], {}, COORD)
    )
    return {
        "fishery": fishery, "operator": operator, "vessel": vessel,
        "enrollment": enrollment,
    }


def setup_em_trip_in_review_scenario(*, video_hours: float = 100.0,
                                     departure: str = "2026-10-01T00:00:00Z",
                                     return_date: str = "2026-10-08T00:00:00Z") -> dict:
    """EM-active vessel + reviewer + trip declared, footage submitted, reviewer
    assigned (IN_REVIEW)."""
    bundle = setup_em_active_vessel_scenario()
    reviewer = make_em_reviewer()
    op_headers = make_vessel_operator_headers(bundle["operator"]["id"])
    trip = get_success_data(
        api_client.create_em_trip(
            create_em_trip_payload(
                vessel_id=bundle["vessel"]["id"],
                departure_date=departure,
                return_date=return_date,
            ),
            op_headers,
        )
    )
    trip = get_success_data(
        api_client.submit_footage(trip["id"], {"video_hours": video_hours}, op_headers)
    )
    trip = get_success_data(
        api_client.assign_reviewer(trip["id"], {"reviewer_id": reviewer["id"]}, COORD)
    )
    bundle["reviewer"] = reviewer
    bundle["trip"] = trip
    return bundle
