"""Install start state/weather precedence, inspection punchlist boundary, and the two
distinct temporal-overlap interval semantics (crew half-open vs site buffered closed).
Translates Difficulty queue rules priority_pair_validation_conflict (state_beats_weather
instance only), boundary_precision_check (inspection_fail_zero_punchlist instance), and
resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_crew_payload, create_install_job_payload, create_weather_payload,
    create_inspection_fail_payload,
    setup_manufacture_ready, setup_installing_project, setup_inspecting_project,
    set_clock, TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
MF = TEST_USERS["manufacturer_headers"]
IM = TEST_USERS["install_manager_headers"]
INS = TEST_USERS["inspector_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 5: priority_pair_validation_conflict — state_beats_weather_on_install_start
# (the crew_cert_beats_window instance is SKIPPED: PRD §2.7 groups all domain
#  business rules together without pinning ERR_CREW_NOT_CERTIFIED before
#  ERR_INVALID_WINDOW, so the outcome is not uniquely derivable.)
# ─────────────────────────────────────────────────────────────────────────

def test_install_start_state_beats_weather(api):
    """PRD §2.7: "State legality — whether the target entity is in a state from which the
    requested transition is allowed — is fifth, yielding `ERR_INVALID_STATE` (HTTP 409).
    The optimistic-concurrency check on quote acceptance is sixth, yielding
    `ERR_STALE_PROJECT_VERSION`. Only after these gates do the domain-specific business rules
    (engineering ratings, weather safety, crew certification and availability, scheduling
    windows, permit expiry and resubmission caps, HOA and engineering permit gates, financing
    principal and down-payment limits, and punchlist rules) apply."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_weather_on_install_start
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, crew, ij = setup_installing_project()
    # Start it (progress IN_PROGRESS), then raise a weather hold.
    get_success_data(api.start_install_job(ij["id"], IM))
    held = get_success_data(api.set_install_job_weather(
        ij["id"], create_weather_payload("WEATHER_HOLD"), IM))
    assert held["progress_status"] == "IN_PROGRESS" and held["weather_status"] == "WEATHER_HOLD"
    # Starting again: progress is not SCHEDULED (state, 5th) AND weather is WEATHER_HOLD
    # (weather safety, a business rule). State legality is checked first -> ERR_INVALID_STATE.
    res = api.start_install_job(ij["id"], IM)
    validate_error(res, "ERR_INVALID_STATE")


def test_install_start_state_conflict_preserves_status(api):
    """PRD §3.6: "Starting the install moves `progress_status` `SCHEDULED → IN_PROGRESS`. It
    requires the job to be `SCHEDULED`, the weather to be `CLEAR`, and the `forecast_wind_mph`
    to be at most the assigned crew's `max_wind_mph`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_weather_on_install_start
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, crew, ij = setup_installing_project()
    get_success_data(api.start_install_job(ij["id"], IM))
    get_success_data(api.set_install_job_weather(
        ij["id"], create_weather_payload("WEATHER_HOLD"), IM))
    res = api.start_install_job(ij["id"], IM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────
# Rule 6: boundary_precision_check — inspection_fail_zero_punchlist_rejected
# ─────────────────────────────────────────────────────────────────────────

def test_inspection_fail_zero_punchlist_rejected(api):
    """PRD §3.7: "The punchlist count is the discriminator: a fail submitted with fewer than
    one punchlist item is rejected with `ERR_PUNCHLIST_REQUIRED` (HTTP 422), which equally
    guards the symmetric expectation that a pass carries zero punchlist items."

    Design: Difficulty/boundary_precision_check/inspection_fail_zero_punchlist_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, ij, ins = setup_inspecting_project()
    res = api.fail_inspection(ins["id"], create_inspection_fail_payload(0), INS)
    validate_error(res, "ERR_PUNCHLIST_REQUIRED")


def test_inspection_fail_zero_punchlist_leaves_result_scheduled(api):
    """PRD §3.7: "An `Inspector` resolves a `SCHEDULED` inspection one of two ways."
    PRD §3.7: "a fail submitted with fewer than one punchlist item is rejected with
    `ERR_PUNCHLIST_REQUIRED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/inspection_fail_zero_punchlist_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, ij, ins = setup_inspecting_project()
    api.fail_inspection(ins["id"], create_inspection_fail_payload(0), INS)
    body = api.list_project_inspections(pj["id"], IM).json()
    after = [x for x in body["data"] if x["id"] == ins["id"]][0]
    assert after["result"] == "SCHEDULED", after


# ─────────────────────────────────────────────────────────────────────────
# Rule 8: resource_temporal_overlap
# ─────────────────────────────────────────────────────────────────────────

def test_crew_double_booked_overlap_rejected(api):
    """PRD §3.6: "The crew must not be double-booked: no other non-terminal install job on
    the same crew may have a half-open window overlapping the requested half-open window, with
    no buffer or adjacency allowance — a job ending exactly when another begins does not
    conflict — and a violation yields `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_half_open_no_buffer
    """
    set_clock("2026-05-01T00:00:00Z")
    # Project A: install job 08:00..17:00 on the shared crew.
    ho_a, pj_a, crew, ij_a = setup_installing_project(
        crew_overrides={"name": "Shared Crew"},
        scheduled_start="2026-05-02T08:00:00Z", scheduled_end="2026-05-02T17:00:00Z")
    # Project B (different project), same crew, IN_MANUFACTURE/READY.
    ho_b, pj_b, mo_b = setup_manufacture_ready(
        homeowner_overrides={"email": "b@x.com"},
        project_overrides={"address_line": "16B"})
    # 12:00..20:00 overlaps the existing 08:00..17:00 on the same crew.
    res = api.create_install_job(create_install_job_payload(
        pj_b["id"], crew["id"], "2026-05-02T12:00:00Z", "2026-05-02T20:00:00Z"), IM)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED")


def test_crew_adjacency_at_end_does_not_conflict(api):
    """PRD §3.6: "with no buffer or adjacency allowance — a job ending exactly when another
    begins does not conflict — and a violation yields `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_half_open_no_buffer
    """
    set_clock("2026-05-01T00:00:00Z")
    ho_a, pj_a, crew, ij_a = setup_installing_project(
        crew_overrides={"name": "Shared Crew"},
        scheduled_start="2026-05-02T08:00:00Z", scheduled_end="2026-05-02T17:00:00Z")
    ho_b, pj_b, mo_b = setup_manufacture_ready(
        homeowner_overrides={"email": "b2@x.com"},
        project_overrides={"address_line": "16B"})
    # Starts exactly at 17:00 (prior job's end): half-open adjacency allowed, no buffer.
    ij_b = validate_success(api.create_install_job(create_install_job_payload(
        pj_b["id"], crew["id"], "2026-05-02T17:00:00Z", "2026-05-02T23:00:00Z"), IM), 201)
    assert ij_b["progress_status"] == "SCHEDULED", ij_b


# NOTE: Two site-buffer tests were removed here. They scheduled a SECOND install job on a
# project that the first scheduling had already advanced IN_MANUFACTURE -> INSTALLING, then
# asserted ERR_SITE_WINDOW_CONFLICT. PRD §3.6 permits scheduling only "with the project
# IN_MANUFACTURE", and PRD §2.7 fixes state legality (ERR_INVALID_STATE, 5th) strictly before
# the scheduling-window business rules. A PRD-faithful implementation therefore returns
# ERR_INVALID_STATE on a second schedule against an INSTALLING project, and there is no
# PRD-documented flow that places a project back in IN_MANUFACTURE while a non-terminal
# install job still exists — so the site-rest assertion is not uniquely derivable (ERROR
# PRECEDENCE collapse). Deleted per the PRD-First contract.
