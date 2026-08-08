"""Stewardship: the operating permit's two dimensions, the servicing interval, pump-outs."""

from test_helpers import (
    ApiErrorId,
    assert_operating_permit,
    assert_pumping_record,
    create_active_contractor,
    create_pumping_record_payload,
    file_pumping_record,
    make_pumper_headers,
    refresh_operating_permit,
    set_clock,
    setup_operating_parcel,
    setup_permitted_parcel,
    unique_apn,
    unique_license_number,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_operating_permit_requires_a_completed_construction_permit(api, applicant_headers, health_officer_headers):
    """PRD §3.7: "Once a construction permit reaches `COMPLETED`, a `HealthOfficer`
    issues the operating permit that licenses the system to run, naming the
    `construction_permit_id` it follows and the `household_size` the permit is rated
    for, which must be between 1 and 12 inclusive. A construction permit in any other
    status is refused with `ERR_CONSTRUCTION_NOT_COMPLETED`."

    Design: Corner/validations/corner_operating_permit_requires_completed_construction_permit
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V7"),
        site_address="60 Premature Path",
    )
    refused = api.create_operating_permit(
        {"construction_permit_id": ctx["construction_permit_id"], "household_size": 4},
        health_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CONSTRUCTION_NOT_COMPLETED.value, 409)

    _, meta = validate_paginated(
        api.list_operating_permits(
            health_officer_headers,
            params={"construction_permit_id": ctx["construction_permit_id"]},
        )
    )
    assert meta["total_count"] == 0


def test_servicing_tier_lower_bound_is_inclusive_at_two_hundred_gallons_per_person(api, applicant_headers, health_officer_headers):
    """PRD §3.7: "At 200 or more but under 300, 36 months. At 125 or more but under 200,
    24 months. Below 125, 12 months. Each band is inclusive of its lower bound, so
    exactly 200.0 gallons per person selects 36 months while 199.99 selects 24."
    PRD §3.7: "The register copies `parcel_id` from the completed construction permit
    and snapshots `tank_capacity_gal` from the system design behind it, stamps
    `issued_on` with the logical clock, sets `expires_on` to five years after
    `issued_on`, starts `status` at `ACTIVE` with `monitoring_required` false and
    `last_pumped_on` null, and derives the servicing schedule."

    Design: Corner/calculations/corner_pumping_interval_tier_lower_bound_inclusive_at_two_hundred_gallons_per_person
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-C8"),
        site_address="53 Interval Isle",
        household_size=5,
        tank_capacity_gal=1000,
    )
    permit = validate_success(
        api.get_operating_permit(ctx["operating_permit_id"], health_officer_headers), 200
    )
    assert_operating_permit(permit)

    assert permit["household_size"] == 5
    assert permit["tank_capacity_gal"] == 1000
    assert permit["pumping_interval_months"] == 36, "1000 over 5 is exactly 200.0 gallons per person"
    assert permit["next_pumping_due_on"] == "2029-05-01T00:00:00.000Z"
    assert permit["issued_on"] == "2026-05-01T00:00:00.000Z"
    assert permit["expires_on"] == "2031-05-01T00:00:00.000Z"
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["monitoring_required"] is False


def test_due_soon_window_boundaries_are_inclusive_on_both_sides(api, applicant_headers):
    """PRD §3.7: "Take the whole days from the logical clock to `next_pumping_due_on`,
    flooring the exact difference, so that the figure is negative once the deadline has
    passed. A negative figure makes the posture `DELINQUENT`. A figure from 0 through 90
    inclusive makes it `DUE_SOON`. Anything above 90 makes it `COMPLIANT`. The
    boundaries are inclusive on both sides of the due-soon window: exactly 90 days out
    is `DUE_SOON`, 91 days out is `COMPLIANT`, and exactly 0 days out — the deadline day
    itself — is still `DUE_SOON`."

    Design: Corner/calculations/corner_pumping_compliance_window_boundary_ninety_one_days_versus_ninety_days
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-C7"),
        site_address="52 Deadline Down",
    )
    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["pumping_interval_months"] == 36
    assert permit["next_pumping_due_on"] == "2029-05-01T00:00:00.000Z"

    set_clock(api, "2029-01-30T00:00:00Z")
    at_91_days = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert at_91_days["compliance_status"] == "COMPLIANT"
    assert at_91_days["status"] == "ACTIVE"

    set_clock(api, "2029-01-31T00:00:00Z")
    at_90_days = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert at_90_days["compliance_status"] == "DUE_SOON"
    assert at_90_days["status"] == "ACTIVE"

    set_clock(api, "2029-05-02T00:00:00Z")
    past_deadline = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert past_deadline["compliance_status"] == "DELINQUENT"
    assert past_deadline["status"] == "ACTIVE"


def test_administrative_moves_leave_the_compliance_posture_untouched(api, applicant_headers, health_officer_headers):
    """PRD §3.7: "An `ACTIVE` permit may perfectly well be `DELINQUENT`, and a
    `SUSPENDED` permit may be `COMPLIANT`. A change along one dimension never rewrites
    the other: administratively suspending a permit leaves its compliance posture
    untouched, and a pump-out that restores compliance does not reinstate a suspended
    permit."
    PRD §3.7: "Suspension moves `ACTIVE → SUSPENDED` and, as a cascade, moves every
    transfer inspection citing this permit whose status is `REQUESTED` to `BLOCKED`."

    Design: Difficulty/non_linear_state_machine/operating_permit_status_and_compliance_axes_move_independently
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-NL2"),
        site_address="7 Parallel Place",
    )
    set_clock(api, "2029-06-01T00:00:00Z")
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["compliance_status"] == "DELINQUENT"

    suspended = validate_success(
        api.set_operating_permit_status(
            ctx["operating_permit_id"], {"action": "SUSPEND"}, health_officer_headers
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["compliance_status"] == "DELINQUENT"

    reinstated = validate_success(
        api.set_operating_permit_status(
            ctx["operating_permit_id"], {"action": "REINSTATE"}, health_officer_headers
        ),
        200,
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["compliance_status"] == "DELINQUENT"


def test_pump_out_restores_compliance_without_moving_the_administrative_status(api, applicant_headers):
    """PRD §3.7: "Filing refreshes the permit: `last_pumped_on` becomes the record's
    `pumped_on`, `pumping_interval_months` and `next_pumping_due_on` are re-derived from
    the new anchor, and `compliance_status` is re-derived, which ordinarily carries the
    permit `DELINQUENT → COMPLIANT` or `DUE_SOON → COMPLIANT`."
    PRD §3.7: "The deadline `next_pumping_due_on` is then the anchor advanced by
    `pumping_interval_months` **calendar months**, where the anchor is `last_pumped_on`
    when a pump-out has been recorded and `issued_on` when none has."

    Design: Difficulty/non_linear_state_machine/operating_permit_status_and_compliance_axes_move_independently
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-NL2B"),
        site_address="7 Parallel Place",
        license_expires_on="2035-01-01T00:00:00Z",
    )
    set_clock(api, "2029-06-01T00:00:00Z")
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["compliance_status"] == "DELINQUENT"

    record = file_pumping_record(
        api,
        ctx["operating_permit_id"],
        ctx["contractor_id"],
        pumped_on="2029-06-01T00:00:00Z",
        gallons_removed=900,
        sludge_depth_in=12.5,
        scum_depth_in=4.0,
    )
    assert_pumping_record(record)

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["status"] == "ACTIVE", "a pump-out never moves the administrative dimension"
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["last_pumped_on"] == "2029-06-01T00:00:00.000Z"
    assert permit["pumping_interval_months"] == 36
    assert permit["next_pumping_due_on"] == "2032-06-01T00:00:00.000Z"


def test_pumper_without_a_pumping_licence_class_is_refused(api, applicant_headers, health_officer_headers):
    """PRD §2.1: "Separately, licence class is enforced against the acting or named
    contractor: a `Pumper` filing a pump-out record must be a `Contractor` whose
    `license_class` is `PUMPER` or `DUAL`, and a construction permit naming an installer
    requires that contractor's `license_class` to be `INSTALLER` or `DUAL`. Either
    mismatch is refused with `ERR_LICENSE_CLASS_MISMATCH` (HTTP 403)."
    PRD §3.7: "The register takes `contractor_id` from the acting `X-User-ID` rather
    than from the payload, and marks the record `accepted` true"

    Design: Corner/validations/corner_pumper_without_pumper_license_class_is_rejected
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-V14"),
        site_address="67 Class Corner",
    )
    installer_only = create_active_contractor(
        api,
        business_name="Installer Only",
        license_number=unique_license_number("LIC-0856-AK"),
        license_class="INSTALLER",
        bond_amount_cents=1000000,
    )
    set_clock(api, "2026-05-03T00:00:00Z")

    payload = create_pumping_record_payload(
        ctx["operating_permit_id"],
        pumped_on="2026-05-03T00:00:00Z",
        gallons_removed=900,
        sludge_depth_in=10.0,
        scum_depth_in=3.0,
    )
    refused = api.create_pumping_record(payload, make_pumper_headers(installer_only["id"]))
    validate_error(refused, ApiErrorId.ERR_LICENSE_CLASS_MISMATCH.value, 403)

    accepted = validate_success(
        api.create_pumping_record(payload, make_pumper_headers(ctx["contractor_id"])), 201
    )
    assert accepted["contractor_id"] == ctx["contractor_id"]

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["last_pumped_on"] == "2026-05-03T00:00:00.000Z"
    assert permit["next_pumping_due_on"] == "2029-05-03T00:00:00.000Z"

    _, meta = validate_paginated(
        api.list_pumping_records(
            health_officer_headers, params={"operating_permit_id": ctx["operating_permit_id"]}
        )
    )
    assert meta["total_count"] == 1
