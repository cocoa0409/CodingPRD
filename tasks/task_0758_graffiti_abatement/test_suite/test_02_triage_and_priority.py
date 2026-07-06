"""Triage scoring, repeat-hotspot posture, and the two severity indices.

Queue A (Difficulty): combinatorial_formula (priority score), dual_variant_calc
(rolling vs confirmed), boundary_precision_check (hotspot threshold).
Queue B (Corner): state_machines / triage idempotency.
"""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    register_owner, register_site, register_crew, register_material,
    file_report, triage, cost_recovery_for_work_order, material_lines,
    make_crew_lead_headers,
    create_report_payload, create_site_payload, create_work_order_payload,
    create_photo_payload,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


# --------------------------------------------------------------------------
# combinatorial_formula / priority_score_nonlinear_hotspot_multiplier
# --------------------------------------------------------------------------
def _public_hotspot_site_with_scored_report(api):
    """PUBLIC site driven to HOTSPOT by 3 reports; the third is HIGH/WALL/offensive."""
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    scored = file_report(api, site["id"], severity="HIGH", surface_type="WALL",
                         is_offensive=True, description="hateful tag")
    return site["id"], scored["id"]


def test_priority_score_nonlinear_hotspot_multiplier_value(api):
    """PRD §3.2: "Multiply that base by a surface-visibility factor determined by `surface_type`:
    a `SIGN` factor of 1.5, a `WALL` factor of 1.2, a `VEHICLE` factor of 1.1, a `FENCE` factor of
    1.0, and a `SIDEWALK` factor of 0.8."
    PRD §3.2: "To that product add a flat offensive bonus of 40 when the report's `is_offensive` is
    true (and nothing when it is false), and add a further flat public-property adjustment of 5 when
    the site's `ownership_type` is `PUBLIC` (and nothing when it is `PRIVATE`)."
    PRD §3.2: "Finally, multiply the whole sum by a posture multiplier read from the site's current
    `status`: 1.5 when the site is `HOTSPOT`, 1.2 when it is `MONITORED`, and 1.0 when it is `NORMAL`."

    Design: Difficulty/combinatorial_formula/priority_score_nonlinear_hotspot_multiplier
    """
    _, rep_id = _public_hotspot_site_with_scored_report(api)
    data = validate_success(api.triage_report(rep_id, CLERK), 200)
    # (50 * 1.2 + 40 + 5) * 1.5 = 157.50 ; a purely additive read would give 105.
    assert data["priority_score"] == pytest.approx(157.50, abs=0.01)


def test_priority_score_triage_reads_hotspot_posture(api):
    """PRD §3.1: "From `MONITORED`, once that count reaches 3 or more, the site becomes `HOTSPOT`."
    PRD §3.2: "**Triage** is the intake clerk's (or coordinator's) act of scoring a submitted report
    and advancing it `SUBMITTED → TRIAGED`; it is permitted only when the report is currently
    `SUBMITTED`, and it computes and stores the `priority_score`."

    Design: Difficulty/combinatorial_formula/priority_score_nonlinear_hotspot_multiplier
    """
    site_id, rep_id = _public_hotspot_site_with_scored_report(api)
    site = validate_success(api.get_site(site_id, COORD), 200)
    assert site["status"] == "HOTSPOT", "third in-window report must flip the site to HOTSPOT"
    data = validate_success(api.triage_report(rep_id, CLERK), 200)
    assert data["status"] == "TRIAGED"


# --------------------------------------------------------------------------
# dual_variant_calc / hotspot_rolling_vs_confirmed_on_site
# --------------------------------------------------------------------------
def test_hotspot_rolling_index_counts_all_statuses(api):
    """PRD §3.1: "Each report contributes a severity weight — `LOW` weighs 1, `MEDIUM` weighs 2,
    `HIGH` weighs 4, and `SEVERE` weighs 8."
    PRD §3.1: "The `hotspot_severity_index_rolling` is the sum of those weights over **every** report
    of the site whose `created_at` lies in the 90-day window, regardless of report status, giving a
    live picture of current pressure."

    Design: Difficulty/dual_variant_calc/hotspot_rolling_vs_confirmed_on_site
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    file_report(api, site["id"], severity="HIGH", surface_type="WALL")
    file_report(api, site["id"], severity="MEDIUM", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="SIDEWALK", reported_via="WEB")
    data = validate_success(api.get_site(site["id"], COORD), 200)
    assert data["hotspot_severity_index_rolling"] == 7  # 4 + 2 + 1


def test_hotspot_confirmed_index_counts_only_remediated(api):
    """PRD §3.1: "The `hotspot_severity_index_confirmed` is the sum of the same weights but only over
    the in-window reports whose `status` is `REMEDIATED`, giving an effectiveness picture of work
    actually completed."
    PRD §3.1: "The `hotspot_severity_index_rolling` is the sum of those weights over **every** report
    of the site whose `created_at` lies in the 90-day window, regardless of report status, giving a
    live picture of current pressure."

    Design: Difficulty/dual_variant_calc/hotspot_rolling_vs_confirmed_on_site
    """
    owner = register_owner(api)
    site = register_site(api, ownership_type="PRIVATE", property_owner_id=owner["id"])
    crew = register_crew(api)
    material = register_material(api, unit_cost_cents=1200, quantity_available=10.0)
    rep_high = file_report(api, site["id"], severity="HIGH", surface_type="WALL")
    file_report(api, site["id"], severity="MEDIUM", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="SIDEWALK", reported_via="WEB")
    triage(api, rep_high["id"])
    wo = validate_success(api.create_work_order(create_work_order_payload(
        rep_high["id"], crew["id"], estimated_labor_hours=2.0,
        material_lines=material_lines(material["id"], 1.0)), COORD), 201)
    ch = make_crew_lead_headers(crew["id"])
    validate_success(api.upload_photo(wo["id"], create_photo_payload("BEFORE", "http://p/b.jpg"), ch), 201)
    validate_success(api.start_work_order(wo["id"], ch), 200)
    validate_success(api.upload_photo(wo["id"], create_photo_payload("AFTER", "http://p/a.jpg"), ch), 201)
    validate_success(api.complete_work_order(wo["id"], {"actual_labor_hours": 2.0}, ch), 200)

    data = validate_success(api.get_site(site["id"], COORD), 200)
    assert data["hotspot_severity_index_confirmed"] == 4  # only the REMEDIATED HIGH report
    assert data["hotspot_severity_index_rolling"] == 7    # all three still in window


# --------------------------------------------------------------------------
# boundary_precision_check / hotspot_threshold_third_report_flips_hotspot
# --------------------------------------------------------------------------
def test_hotspot_threshold_third_report_flips_to_hotspot(api):
    """PRD §3.1: "From `MONITORED`, once that count reaches 3 or more, the site becomes `HOTSPOT`."

    Design: Difficulty/boundary_precision_check/hotspot_threshold_third_report_flips_hotspot
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    third = validate_success(api.create_report(
        create_report_payload(site["id"], severity="MEDIUM", surface_type="WALL"), CLERK), 201)
    assert third["status"] == "SUBMITTED"
    data = validate_success(api.get_site(site["id"], COORD), 200)
    assert data["report_count_90d"] == 3
    assert data["status"] == "HOTSPOT"


def test_hotspot_threshold_second_report_only_monitored(api):
    """PRD §3.1: "From `NORMAL`, once the count of reports in the 90-day window reaches exactly 2,
    the site becomes `MONITORED`."

    Design: Difficulty/boundary_precision_check/hotspot_threshold_third_report_flips_hotspot
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    data = validate_success(api.get_site(site["id"], COORD), 200)
    assert data["report_count_90d"] == 2
    assert data["status"] == "MONITORED"


# --------------------------------------------------------------------------
# Corner: state_machines / triage_already_triaged_returns_invalid_state
# --------------------------------------------------------------------------
def test_triage_already_triaged_returns_invalid_state(api):
    """PRD §2.10: "Sixth is the generic state guard: if the target resource is not in a state from
    which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.2: "it is permitted only when the report is currently `SUBMITTED`, and it computes and
    stores the `priority_score`."

    Design: Corner/state_machines/triage_already_triaged_returns_invalid_state
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    rep = validate_success(api.create_report(
        create_report_payload(site["id"], severity="LOW", surface_type="WALL"), CLERK), 201)
    validate_success(api.triage_report(rep["id"], CLERK), 200)
    resp = api.triage_report(rep["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
