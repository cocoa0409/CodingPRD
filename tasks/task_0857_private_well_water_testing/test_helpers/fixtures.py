"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to drive the system into
the states the tests assert against (an ACTIVE well, a RESULTED sample, an open
contamination case with an active advisory, and so on). Setup calls use the
lenient get_success_data() so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.

Identity threading: Applicant and Driller are entity-backed, so every
ownership-gated call uses make_applicant_headers(applicant_id) or
make_driller_headers(driller_id) with the acting entity's own id.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_driller_headers,
    make_lab_analyst_headers,
    make_health_officer_headers,
)

OFFICER = TEST_USERS["health_officer_headers"]
LAB = TEST_USERS["lab_analyst_headers"]


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_aquifer(api, **overrides) -> dict:
    return get_success_data(api.create_aquifer(f.aquifer_payload(**overrides), OFFICER))


def create_applicant(api, **overrides) -> dict:
    return get_success_data(api.create_applicant(f.applicant_payload(**overrides), OFFICER))


def create_driller(api, **overrides) -> dict:
    return get_success_data(api.create_driller(f.driller_payload(**overrides), OFFICER))


def create_well(api, applicant_id, aquifer_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    return get_success_data(
        api.create_well(f.well_payload(applicant_id, aquifer_id, **overrides), headers)
    )


def create_submitted_permit(api, well_id, applicant_id, driller_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    payload = f.construction_permit_payload(well_id, applicant_id, driller_id, **overrides)
    return get_success_data(api.create_construction_permit(payload, headers))


def pay_permit(api, permit_id, applicant_id) -> dict:
    return get_success_data(api.pay_permit(permit_id, make_applicant_headers(applicant_id)))


def approve_permit(api, permit_id) -> dict:
    return get_success_data(api.approve_permit(permit_id, OFFICER))


def issue_permit(api, permit_id) -> dict:
    return get_success_data(api.issue_permit(permit_id, OFFICER))


def file_driller_log(api, permit_id, driller_id, **overrides) -> dict:
    headers = make_driller_headers(driller_id)
    payload = f.driller_log_payload(permit_id, driller_id, **overrides)
    return get_success_data(api.create_driller_log(payload, headers))


# --------------------------------------------------------------------------
# Tier 1/2/3: bring a well all the way to ACTIVE
# --------------------------------------------------------------------------
def setup_active_well(
    api,
    *,
    aquifer_sensitivity="HIGH",
    intended_use="DOMESTIC",
    min_setback_septic_ft=50,
    min_setback_property_line_ft=10,
    proposed_depth_ft=250,
    total_depth_ft=320,
    setback_septic_ft=60,
    setback_property_line_ft=15,
    scheduled_start="2026-05-10T08:00:00Z",
    scheduled_end="2026-05-11T17:00:00Z",
    completed_on="2026-05-11T18:00:00Z",
    expedite=False,
) -> SimpleNamespace:
    """Create aquifer + applicant + driller + well, then pay/approve/issue the
    construction permit and file the completion log so the well ends ACTIVE.

    Returns a namespace with the created entities and their ids plus ready-made
    applicant/driller headers. The well is re-fetched so registry_status reads
    ACTIVE.
    """
    aquifer = create_aquifer(
        api,
        sensitivity=aquifer_sensitivity,
        min_setback_septic_ft=min_setback_septic_ft,
        min_setback_property_line_ft=min_setback_property_line_ft,
    )
    applicant = create_applicant(api)
    driller = create_driller(api)
    well = create_well(api, applicant["id"], aquifer["id"], intended_use=intended_use)
    permit = create_submitted_permit(
        api,
        well["id"],
        applicant["id"],
        driller["id"],
        proposed_depth_ft=proposed_depth_ft,
        setback_septic_ft=setback_septic_ft,
        setback_property_line_ft=setback_property_line_ft,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        expedite=expedite,
    )
    pay_permit(api, permit["id"], applicant["id"])
    approve_permit(api, permit["id"])
    issue_permit(api, permit["id"])
    file_driller_log(api, permit["id"], driller["id"],
                     total_depth_ft=total_depth_ft, completed_on=completed_on)
    well = get_success_data(api.get_well(well["id"], OFFICER))
    permit = get_success_data(api.get_construction_permit(permit["id"], OFFICER))
    return SimpleNamespace(
        aquifer=aquifer,
        applicant=applicant,
        driller=driller,
        well=well,
        permit=permit,
        aquifer_id=aquifer["id"],
        applicant_id=applicant["id"],
        driller_id=driller["id"],
        well_id=well["id"],
        permit_id=permit["id"],
        applicant_headers=make_applicant_headers(applicant["id"]),
        driller_headers=make_driller_headers(driller["id"]),
    )


# --------------------------------------------------------------------------
# Sample pipeline helpers
# --------------------------------------------------------------------------
def submit_sample(api, well_id, applicant_id, **overrides) -> dict:
    """POST /water-samples for an ACTIVE well (status SUBMITTED)."""
    headers = make_applicant_headers(applicant_id)
    payload = f.water_sample_payload(well_id, applicant_id, **overrides)
    return get_success_data(api.create_water_sample(payload, headers))


def submit_sample_in_analysis(api, well_id, applicant_id, **overrides) -> dict:
    """Submit a sample and advance it SUBMITTED -> RECEIVED -> IN_ANALYSIS."""
    sample = submit_sample(api, well_id, applicant_id, **overrides)
    get_success_data(api.receive_sample(sample["id"], LAB))
    get_success_data(api.begin_analysis(sample["id"], LAB))
    return get_success_data(api.get_water_sample(sample["id"], OFFICER))


def record_result(api, sample_id, **overrides) -> dict:
    """POST /sample-results against an IN_ANALYSIS sample (moves it RESULTED)."""
    payload = f.sample_result_payload(sample_id, **overrides)
    return get_success_data(api.create_sample_result(payload, LAB))


def resulted_sample(api, well_id, applicant_id, result_overrides=None, **sample_overrides):
    """Submit -> receive -> begin-analysis -> record result. Returns (sample, result)."""
    sample = submit_sample_in_analysis(api, well_id, applicant_id, **sample_overrides)
    result = record_result(api, sample["id"], **(result_overrides or {}))
    sample = get_success_data(api.get_water_sample(sample["id"], OFFICER))
    return sample, result


# --------------------------------------------------------------------------
# Tier 4/5: contamination-cascade scenarios
# --------------------------------------------------------------------------
def setup_well_with_cascade_case(
    api,
    *,
    collected_on="2026-05-12T00:00:00Z",
    analyzed_on="2026-05-13T00:00:00Z",
) -> SimpleNamespace:
    """Drive an ACTIVE well into the confirmed-UNSAFE contamination cascade.

    Records a first result with total coliform PRESENT, which auto-opens a
    contamination case (OPEN) and auto-issues one ACTIVE advisory, taking the
    well to potability UNSAFE with active_advisory_count 1. Returns a namespace
    carrying the well, the triggering sample/result, and the auto-opened
    case + auto-issued advisory (fetched via their list endpoints).
    """
    ctx = setup_active_well(api)
    sample, result = resulted_sample(
        api, ctx.well_id, ctx.applicant_id,
        result_overrides={"bacteria_coliform": "PRESENT", "ecoli": "ABSENT",
                          "nitrate_mg_l": 1.0, "lead_ppb": 1.0, "analyzed_on": analyzed_on},
        requested_analytes=["BACTERIA"], collected_on=collected_on,
    )
    cases, _ = _list(api.list_contamination_cases(OFFICER, params={"well_id": ctx.well_id}))
    advisories, _ = _list(api.list_advisories(OFFICER, params={"well_id": ctx.well_id}))
    ctx.sample = sample
    ctx.result = result
    ctx.case = cases[0] if cases else None
    ctx.advisory = advisories[0] if advisories else None
    ctx.well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    return ctx


def advance_case_to_resolved(api, case_id, officer_id):
    """Walk a case OPEN -> INVESTIGATING -> MITIGATION -> RESOLVED as one officer."""
    headers = make_health_officer_headers(officer_id)
    for to_status in ("INVESTIGATING", "MITIGATION", "RESOLVED"):
        get_success_data(api.transition_case(case_id, {"to_status": to_status}, headers))
    return get_success_data(api.get_contamination_case(case_id, OFFICER))


# --------------------------------------------------------------------------
# Real-estate requirement helpers
# --------------------------------------------------------------------------
def setup_requirement_with_safe_sample(
    api,
    *,
    collected_on="2026-05-01T00:00:00Z",
    closing_date="2026-07-30T00:00:00Z",
    analyzed_on="2026-05-02T00:00:00Z",
    transaction_type="SALE",
    result_overrides=None,
) -> SimpleNamespace:
    """ACTIVE well + a RESULTED sample + an OPEN real-estate requirement.

    By default the sample grades confirmed SAFE and lies exactly inside the
    validity window. Callers override collected_on / closing_date / the result
    to exercise the window and safety branches. Returns a namespace carrying the
    well, the sample, and the requirement (with its captured version).
    """
    ctx = setup_active_well(api)
    sample, result = resulted_sample(
        api, ctx.well_id, ctx.applicant_id,
        result_overrides={**{"nitrate_mg_l": 2.0, "lead_ppb": 2.0, "analyzed_on": analyzed_on},
                          **(result_overrides or {})},
        sample_type="REAL_ESTATE",
        requested_analytes=["BACTERIA", "NITRATE", "LEAD"],
        collected_on=collected_on,
    )
    requirement = get_success_data(api.create_real_estate_requirement(
        f.real_estate_requirement_payload(
            ctx.well_id, ctx.applicant_id,
            transaction_type=transaction_type, closing_date=closing_date),
        ctx.applicant_headers,
    ))
    ctx.sample = sample
    ctx.result = result
    ctx.requirement = requirement
    ctx.requirement_id = requirement["id"]
    ctx.requirement_version = requirement["version"]
    return ctx


def _list(response):
    """Return (data_list, meta) from a raw list response using lenient parsing."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# --------------------------------------------------------------------------
# Submitted-permit scenario (pre-payment / pre-approval)
# --------------------------------------------------------------------------
def setup_submitted_permit(
    api,
    *,
    aquifer_sensitivity="HIGH",
    intended_use="DOMESTIC",
    min_setback_septic_ft=50,
    min_setback_property_line_ft=10,
    proposed_depth_ft=250,
    setback_septic_ft=60,
    setback_property_line_ft=15,
    scheduled_start="2026-05-10T08:00:00Z",
    scheduled_end="2026-05-11T17:00:00Z",
    expedite=False,
) -> SimpleNamespace:
    """aquifer + applicant + driller + PROPOSED well + a SUBMITTED (unpaid)
    construction permit. Returns a namespace with the entities and their ids."""
    aquifer = create_aquifer(
        api,
        sensitivity=aquifer_sensitivity,
        min_setback_septic_ft=min_setback_septic_ft,
        min_setback_property_line_ft=min_setback_property_line_ft,
    )
    applicant = create_applicant(api)
    driller = create_driller(api)
    well = create_well(api, applicant["id"], aquifer["id"], intended_use=intended_use)
    permit = create_submitted_permit(
        api,
        well["id"],
        applicant["id"],
        driller["id"],
        proposed_depth_ft=proposed_depth_ft,
        setback_septic_ft=setback_septic_ft,
        setback_property_line_ft=setback_property_line_ft,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        expedite=expedite,
    )
    return SimpleNamespace(
        aquifer=aquifer,
        applicant=applicant,
        driller=driller,
        well=well,
        permit=permit,
        aquifer_id=aquifer["id"],
        applicant_id=applicant["id"],
        driller_id=driller["id"],
        well_id=well["id"],
        permit_id=permit["id"],
        applicant_headers=make_applicant_headers(applicant["id"]),
        driller_headers=make_driller_headers(driller["id"]),
    )


# --------------------------------------------------------------------------
# Manual contamination case + advisory helpers
# --------------------------------------------------------------------------
def create_well_only(api, *, aquifer_sensitivity="LOW", intended_use="DOMESTIC") -> SimpleNamespace:
    """aquifer + applicant + a PROPOSED well (no permit). For advisory / manual
    contamination-case scenarios that do not need an ACTIVE well."""
    aquifer = create_aquifer(api, sensitivity=aquifer_sensitivity)
    applicant = create_applicant(api)
    well = create_well(api, applicant["id"], aquifer["id"], intended_use=intended_use)
    return SimpleNamespace(
        aquifer=aquifer, applicant=applicant, well=well,
        aquifer_id=aquifer["id"], applicant_id=applicant["id"], well_id=well["id"],
        applicant_headers=make_applicant_headers(applicant["id"]),
    )


def open_manual_case(api, well_id, officer_id, severity="HIGH", **overrides) -> dict:
    """POST /contamination-cases as the given officer (status OPEN)."""
    headers = make_health_officer_headers(officer_id)
    payload = f.contamination_case_payload(well_id, severity=severity, **overrides)
    return get_success_data(api.create_contamination_case(payload, headers))
