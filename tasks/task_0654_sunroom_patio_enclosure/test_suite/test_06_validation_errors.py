"""Business-rule validation errors: downpayment, HOA gate, weather, crew inactive, invalid
window, permit expiry, resubmit cap. Translates Corner queue section validations.

The financing_principal_exceeded_declines instance is SKIPPED: PRD §3.3 simultaneously says
the decline branch sets the status to DECLINED (a 200 outcome) and that the attempt "surfaces
ERR_PRINCIPAL_EXCEEDED (HTTP 422)" — two PRD-only readers could ship either observable
outcome, so it is not uniquely derivable.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_financing_payload, create_permit_decide_payload, create_crew_payload,
    create_install_job_payload, create_manufacture_order_payload,
    setup_permitting_project, setup_permit_in_review, setup_installing_project,
    setup_manufacture_ready, setup_approved_to_build,
    make_homeowner_headers, set_clock, TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
PO = TEST_USERS["permit_officer_headers"]
MF = TEST_USERS["manufacturer_headers"]
IM = TEST_USERS["install_manager_headers"]


def test_financing_downpayment_exceeds_total_rejected(api):
    """PRD §3.3: "A down payment greater than the accepted quote's `total_cents` would yield a
    negative principal and is rejected at submission with `ERR_DOWNPAYMENT_EXCEEDS_TOTAL`
    (HTTP 422)."

    Design: Corner/validations/financing_downpayment_exceeds_total_rejected
    """
    # SCREEN_ROOM/ALUMINUM, 60x144 -> total 290250.
    ho, pj, m, q = setup_permitting_project(
        project_overrides={"structure_type": "SCREEN_ROOM", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 60, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    res = api.create_financing_application(
        create_financing_payload(pj["id"], q["id"], down_payment_cents=2000000,
                                 term_months=12, credit_score=720),
        make_homeowner_headers(ho["id"]))
    validate_error(res, "ERR_DOWNPAYMENT_EXCEEDS_TOTAL")


def test_hoa_not_approved_blocks_permit_approval(api):
    """PRD §3.4: "if `hoa_required` is true, `hoa_status` must be `HOA_APPROVED`, otherwise the
    approval is rejected with `ERR_HOA_NOT_APPROVED` (HTTP 409)"

    Design: Corner/validations/hoa_not_approved_blocks_permit_approval
    """
    # HOA-governed, low load (no engineering) THREE_SEASON; permit IN_REVIEW, hoa_status PENDING.
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"hoa_governed": True, "ground_snow_load_psf": 10,
                             "design_wind_speed_mph": 90},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    assert pa["hoa_required"] is True, pa
    assert pa["hoa_status"] == "PENDING", pa
    res = api.decide_permit(pa["id"], create_permit_decide_payload("APPROVED"), PO)
    validate_error(res, "ERR_HOA_NOT_APPROVED")


def test_weather_unsafe_start_blocked(api):
    """PRD §3.6: "an attempt to start or complete while the weather is `WEATHER_HOLD`, or to
    start while the forecast wind exceeds the crew's `max_wind_mph`, is rejected with
    `ERR_WEATHER_UNSAFE` (HTTP 409)."

    Design: Corner/validations/weather_unsafe_start_blocked
    """
    set_clock("2026-05-01T00:00:00Z")
    # crew max 40, forecast 50 -> exceeds, weather CLEAR.
    ho, pj, crew, ij = setup_installing_project(
        crew_overrides={"name": "Crew Lo", "max_wind_mph": 40},
        install_job_overrides={"forecast_wind_mph": 50},
    )
    res = api.start_install_job(ij["id"], IM)
    validate_error(res, "ERR_WEATHER_UNSAFE")
    body = api.list_project_install_jobs(pj["id"], IM).json()
    after = [x for x in body["data"] if x["id"] == ij["id"]][0]
    assert after["progress_status"] == "SCHEDULED", after


def test_crew_inactive_assignment_rejected(api):
    """PRD §3.6: "The assigned crew must be active; an inactive crew yields `ERR_CREW_INACTIVE`
    (HTTP 422)."

    Design: Corner/validations/crew_inactive_assignment_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, mo = setup_manufacture_ready(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    crew = get_success_data(api.create_crew(create_crew_payload(name="Crew Off", active=False), IM))
    res = api.create_install_job(create_install_job_payload(
        pj["id"], crew["id"], "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z"), IM)
    validate_error(res, "ERR_CREW_INACTIVE")


def test_install_invalid_window_rejected(api):
    """PRD §3.6: "The window must be valid: `scheduled_start` strictly before `scheduled_end`,
    otherwise `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/install_invalid_window_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, mo = setup_manufacture_ready(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    crew = get_success_data(api.create_crew(create_crew_payload(name="Crew Z"), IM))
    # zero-length window: start == end.
    res = api.create_install_job(create_install_job_payload(
        pj["id"], crew["id"], "2026-05-02T08:00:00Z", "2026-05-02T08:00:00Z"), IM)
    validate_error(res, "ERR_INVALID_WINDOW")


def test_permit_expired_blocks_manufacture(api):
    """PRD §3.5: "Creation is blocked if the project's approved permit has lapsed: when the
    logical clock is at or past the permit's `expires_at`, the order is rejected with
    `ERR_PERMIT_EXPIRED` (HTTP 409)."

    Design: Corner/validations/permit_expired_blocks_manufacture
    """
    set_clock("2026-05-01T00:00:00Z")
    # Permit APPROVED at 2026-05-01 -> expires_at 2026-05-01 + 180d. Advance past it.
    ho, pj, q, pa = setup_approved_to_build(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    set_clock("2026-11-01T00:00:00Z")
    res = api.create_manufacture_order(create_manufacture_order_payload(pj["id"], q["id"]), MF)
    validate_error(res, "ERR_PERMIT_EXPIRED")
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "APPROVED_TO_BUILD", pj_after


def test_resubmit_limit_reached_rejected(api):
    """PRD §3.4: "A resubmission attempted at or above 3 prior resubmissions is rejected with
    `ERR_RESUBMIT_LIMIT` (HTTP 409)."
    PRD §3.4: "A `Homeowner` may resubmit a `REJECTED` permit, sending it
    `REJECTED → SUBMITTED`, provided its `resubmission_count` is below the cap of 3;
    resubmission increments `resubmission_count` by one."

    Design: Corner/validations/resubmit_limit_reached_rejected
    """
    ho, pj, q, pa = setup_permit_in_review(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    hh = make_homeowner_headers(ho["id"])
    # reject -> resubmit three times to reach resubmission_count 3, leaving it REJECTED.
    for _ in range(3):
        get_success_data(api.decide_permit(pa["id"], create_permit_decide_payload("REJECTED"), PO))
        get_success_data(api.resubmit_permit(pa["id"], hh))
        get_success_data(api.begin_permit_review(pa["id"], PO))
    get_success_data(api.decide_permit(pa["id"], create_permit_decide_payload("REJECTED"), PO))
    pa_now = get_success_data(api.get_permit_application(pa["id"], PO))
    assert pa_now["resubmission_count"] == 3 and pa_now["status"] == "REJECTED", pa_now
    res = api.resubmit_permit(pa["id"], hh)
    validate_error(res, "ERR_RESUBMIT_LIMIT")
