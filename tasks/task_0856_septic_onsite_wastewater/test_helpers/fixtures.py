"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API; nothing
is assumed to pre-exist on the server. Setup calls use the lenient validator so a
broken precondition surfaces as a clear setup failure rather than a confusing
assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import TEST_DEFAULTS
from .factories import (
    create_construction_permit_payload,
    create_contractor_payload,
    create_inspection_payload,
    create_operating_permit_payload,
    create_parcel_payload,
    create_perc_hole_payload,
    create_pumping_record_payload,
    create_repair_order_payload,
    create_site_evaluation_payload,
    create_system_design_payload,
    create_transfer_inspection_payload,
    create_water_sample_payload,
    create_well_payload,
    unique_apn,
    unique_license_number,
)
from .test_users import TEST_USERS, make_pumper_headers

APPLICANT = TEST_USERS["applicant_headers"]
DESIGNER = TEST_USERS["design_professional_headers"]
EHS_REVIEWER = TEST_USERS["ehs_reviewer_headers"]
EHS_FIELD = TEST_USERS["ehs_field_headers"]
HEALTH_OFFICER = TEST_USERS["health_officer_headers"]
RECORDS_CLERK = TEST_USERS["records_clerk_headers"]


# ── Tier 0: single-step creations and reads ───────────────────────────────────


def set_clock(api, to_iso8601, headers=None):
    """Move the logical clock and return the reported current_utc."""
    return get_success_data(api.set_clock(to_iso8601, headers or HEALTH_OFFICER))


def create_parcel(api, headers=None, **overrides):
    """Register a parcel. Defaults to a 40000 sqft lot owned by the shared Applicant."""
    payload = create_parcel_payload(**overrides)
    return get_success_data(api.create_parcel(payload, headers or APPLICANT))


def refresh_parcel(api, parcel_id, headers=None):
    return get_success_data(api.get_parcel(parcel_id, headers or HEALTH_OFFICER))


def refresh_well(api, well_id, headers=None):
    return get_success_data(api.get_well(well_id, headers or HEALTH_OFFICER))


def refresh_site_evaluation(api, site_evaluation_id, headers=None):
    return get_success_data(
        api.get_site_evaluation(site_evaluation_id, headers or HEALTH_OFFICER)
    )


def refresh_system_design(api, system_design_id, headers=None):
    return get_success_data(
        api.get_system_design(system_design_id, headers or HEALTH_OFFICER)
    )


def refresh_contractor(api, contractor_id, headers=None):
    return get_success_data(api.get_contractor(contractor_id, headers or HEALTH_OFFICER))


def refresh_construction_permit(api, permit_id, headers=None):
    return get_success_data(
        api.get_construction_permit(permit_id, headers or HEALTH_OFFICER)
    )


def refresh_inspection(api, inspection_id, headers=None):
    return get_success_data(api.get_inspection(inspection_id, headers or HEALTH_OFFICER))


def refresh_operating_permit(api, operating_permit_id, headers=None):
    return get_success_data(
        api.get_operating_permit(operating_permit_id, headers or HEALTH_OFFICER)
    )


def refresh_repair_order(api, repair_order_id, headers=None):
    return get_success_data(
        api.get_repair_order(repair_order_id, headers or HEALTH_OFFICER)
    )


def refresh_transfer_inspection(api, transfer_inspection_id, headers=None):
    return get_success_data(
        api.get_transfer_inspection(transfer_inspection_id, headers or HEALTH_OFFICER)
    )


def create_well(api, parcel_id, headers=None, **overrides):
    payload = create_well_payload(parcel_id, **overrides)
    return get_success_data(api.create_well(payload, headers or APPLICANT))


def post_water_sample(api, well_id, headers=None, **overrides):
    payload = create_water_sample_payload(**overrides)
    return get_success_data(api.create_water_sample(well_id, payload, headers or EHS_FIELD))


def create_active_contractor(api, headers=None, **overrides):
    """Register a licence. Defaults to a DUAL-class firm that does not lapse."""
    payload = create_contractor_payload(**overrides)
    return get_success_data(api.create_contractor(payload, headers or HEALTH_OFFICER))


# ── Tier 1: site-evaluation state progression ─────────────────────────────────


def create_draft_site_evaluation(api, parcel_id, headers=None, **overrides):
    payload = create_site_evaluation_payload(parcel_id, **overrides)
    return get_success_data(api.create_site_evaluation(payload, headers or DESIGNER))


def add_perc_hole(api, site_evaluation_id, headers=None, **overrides):
    payload = create_perc_hole_payload(**overrides)
    return get_success_data(
        api.add_perc_hole(site_evaluation_id, payload, headers or DESIGNER)
    )


def create_submitted_site_evaluation(
    api,
    parcel_id,
    *,
    holes=None,
    designer_headers=None,
    **overrides,
):
    """Open an evaluation, append readings, and submit it for review.

    `holes` is a list of perc-hole payload override dicts; it defaults to a single
    valid reading of 132 minutes over 6 inches, a certified rate of 22.00 min/in.
    """
    designer_headers = designer_headers or DESIGNER
    evaluation = create_draft_site_evaluation(
        api, parcel_id, headers=designer_headers, **overrides
    )
    for index, hole in enumerate(holes if holes is not None else [{}], start=1):
        hole_payload = dict(hole)
        hole_payload.setdefault("hole_number", index)
        add_perc_hole(api, evaluation["id"], headers=designer_headers, **hole_payload)
    return get_success_data(
        api.submit_site_evaluation(evaluation["id"], designer_headers)
    )


def create_approved_site_evaluation(
    api,
    parcel_id,
    *,
    holes=None,
    designer_headers=None,
    reviewer_headers=None,
    review_note="Accepted",
    **overrides,
):
    """Walk an evaluation DRAFT -> SUBMITTED -> APPROVED. Returns the approved record."""
    submitted = create_submitted_site_evaluation(
        api, parcel_id, holes=holes, designer_headers=designer_headers, **overrides
    )
    return get_success_data(
        api.review_site_evaluation(
            submitted["id"],
            {"decision": "APPROVE", "review_note": review_note},
            reviewer_headers or EHS_REVIEWER,
        )
    )


# ── Tier 2: system-design state progression ───────────────────────────────────


def create_draft_system_design(
    api, site_evaluation_id, expected_version, designer_headers=None, **overrides
):
    payload = create_system_design_payload(
        site_evaluation_id, expected_version, **overrides
    )
    return get_success_data(
        api.create_system_design(payload, designer_headers or DESIGNER)
    )


def draw_design_from_evaluation(api, site_evaluation_id, designer_headers=None, **overrides):
    """Re-read the evaluation for its current version, then draw a design from it."""
    designer_headers = designer_headers or DESIGNER
    evaluation = refresh_site_evaluation(api, site_evaluation_id, designer_headers)
    return create_draft_system_design(
        api,
        site_evaluation_id,
        evaluation["version"],
        designer_headers=designer_headers,
        **overrides,
    )


def create_approved_system_design(
    api,
    site_evaluation_id,
    *,
    designer_headers=None,
    reviewer_headers=None,
    **overrides,
):
    """Draw a design and walk it DRAFT -> UNDER_REVIEW -> APPROVED."""
    designer_headers = designer_headers or DESIGNER
    design = draw_design_from_evaluation(
        api, site_evaluation_id, designer_headers=designer_headers, **overrides
    )
    get_success_data(api.submit_system_design(design["id"], designer_headers))
    return get_success_data(
        api.review_system_design(
            design["id"], {"decision": "APPROVE"}, reviewer_headers or EHS_REVIEWER
        )
    )


# ── Tier 3: construction permit and inspection lifecycle ──────────────────────


def issue_construction_permit(
    api, system_design_id, contractor_id, officer_headers=None, **overrides
):
    payload = create_construction_permit_payload(
        system_design_id, contractor_id, **overrides
    )
    return get_success_data(
        api.create_construction_permit(payload, officer_headers or HEALTH_OFFICER)
    )


def schedule_inspection(api, construction_permit_id, inspector_headers=None, **overrides):
    payload = create_inspection_payload(construction_permit_id, **overrides)
    return get_success_data(
        api.create_inspection(payload, inspector_headers or EHS_FIELD)
    )


def record_result(api, inspection_id, result, inspector_headers=None, deficiency_codes=None):
    payload = {"result": result}
    if deficiency_codes is not None:
        payload["deficiency_codes"] = deficiency_codes
    return get_success_data(
        api.record_inspection_result(
            inspection_id, payload, inspector_headers or EHS_FIELD
        )
    )


def complete_construction(
    api,
    construction_permit_id,
    *,
    inspector_headers=None,
    cover_start="2026-05-01T09:00:00Z",
    cover_end="2026-05-01T10:00:00Z",
    final_start="2026-05-02T09:00:00Z",
    final_end="2026-05-02T10:00:00Z",
):
    """Pass a COVER then a FINAL inspection, carrying the permit through to COMPLETED.

    Returns (cover_inspection, final_inspection) as recorded after their verdicts.
    """
    inspector_headers = inspector_headers or EHS_FIELD
    cover = schedule_inspection(
        api,
        construction_permit_id,
        inspector_headers=inspector_headers,
        inspection_type="COVER",
        scheduled_start=cover_start,
        scheduled_end=cover_end,
    )
    cover = record_result(api, cover["id"], "PASS", inspector_headers)
    final = schedule_inspection(
        api,
        construction_permit_id,
        inspector_headers=inspector_headers,
        inspection_type="FINAL",
        scheduled_start=final_start,
        scheduled_end=final_end,
    )
    final = record_result(api, final["id"], "PASS", inspector_headers)
    return cover, final


def issue_operating_permit(api, construction_permit_id, officer_headers=None, **overrides):
    payload = create_operating_permit_payload(construction_permit_id, **overrides)
    return get_success_data(
        api.create_operating_permit(payload, officer_headers or HEALTH_OFFICER)
    )


# ── Tier 4: end-to-end scenario builders ──────────────────────────────────────


def setup_permitted_parcel(
    api,
    *,
    existing_parcel=None,
    apn=None,
    county_code="OR",
    site_address="1 Register Road",
    lot_size_sqft=None,
    water_source="PUBLIC_WATER",
    applicant_headers=None,
    designer_headers=None,
    reviewer_headers=None,
    officer_headers=None,
    holes=None,
    soil_group="LOAMY",
    depth_to_limiting_layer_in=None,
    system_type="CONVENTIONAL",
    bedrooms=None,
    tank_capacity_gal=None,
    drainfield_x_ft=150,
    drainfield_y_ft=0,
    license_class="DUAL",
    license_expires_on=None,
    permit_valid_from=None,
    permit_valid_until=None,
):
    """Parcel -> APPROVED evaluation -> APPROVED design -> ISSUED construction permit.

    Returns a dict carrying every record built along the way.
    """
    parcel = existing_parcel or create_parcel(
        api,
        headers=applicant_headers or APPLICANT,
        apn=apn or unique_apn(),
        county_code=county_code,
        site_address=site_address,
        lot_size_sqft=lot_size_sqft or TEST_DEFAULTS["LOT_SIZE_SQFT"],
        water_source=water_source,
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=holes,
        designer_headers=designer_headers,
        reviewer_headers=reviewer_headers,
        soil_group=soil_group,
        depth_to_limiting_layer_in=(
            depth_to_limiting_layer_in
            if depth_to_limiting_layer_in is not None
            else TEST_DEFAULTS["DEPTH_TO_LIMITING_LAYER_IN"]
        ),
    )
    design = create_approved_system_design(
        api,
        evaluation["id"],
        designer_headers=designer_headers,
        reviewer_headers=reviewer_headers,
        system_type=system_type,
        bedrooms=bedrooms if bedrooms is not None else TEST_DEFAULTS["BEDROOMS"],
        tank_capacity_gal=(
            tank_capacity_gal
            if tank_capacity_gal is not None
            else TEST_DEFAULTS["TANK_CAPACITY_GAL"]
        ),
        drainfield_x_ft=drainfield_x_ft,
        drainfield_y_ft=drainfield_y_ft,
    )
    contractor = create_active_contractor(
        api,
        headers=officer_headers,
        license_number=unique_license_number(),
        license_class=license_class,
        license_expires_on=license_expires_on or TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
    )
    permit = issue_construction_permit(
        api,
        design["id"],
        contractor["id"],
        officer_headers=officer_headers,
        valid_from=permit_valid_from or TEST_DEFAULTS["PERMIT_VALID_FROM"],
        valid_until=permit_valid_until or TEST_DEFAULTS["PERMIT_VALID_UNTIL"],
    )
    return {
        "parcel": parcel,
        "parcel_id": parcel["id"],
        "site_evaluation": evaluation,
        "site_evaluation_id": evaluation["id"],
        "system_design": design,
        "system_design_id": design["id"],
        "contractor": contractor,
        "contractor_id": contractor["id"],
        "construction_permit": permit,
        "construction_permit_id": permit["id"],
        "applicant_headers": applicant_headers or APPLICANT,
    }


def setup_operating_parcel(
    api,
    *,
    household_size=None,
    inspector_headers=None,
    cover_start="2026-05-01T09:00:00Z",
    cover_end="2026-05-01T10:00:00Z",
    final_start="2026-05-02T09:00:00Z",
    final_end="2026-05-02T10:00:00Z",
    **permit_overrides,
):
    """A fully permitted parcel whose construction is COMPLETED and whose
    OperatingPermit has been issued and is ACTIVE.

    Returns the dict from setup_permitted_parcel enriched with the two inspections
    and the operating permit.
    """
    ctx = setup_permitted_parcel(api, **permit_overrides)
    cover, final = complete_construction(
        api,
        ctx["construction_permit_id"],
        inspector_headers=inspector_headers,
        cover_start=cover_start,
        cover_end=cover_end,
        final_start=final_start,
        final_end=final_end,
    )
    operating_permit = issue_operating_permit(
        api,
        ctx["construction_permit_id"],
        officer_headers=permit_overrides.get("officer_headers"),
        household_size=(
            household_size
            if household_size is not None
            else TEST_DEFAULTS["HOUSEHOLD_SIZE"]
        ),
    )
    ctx.update(
        {
            "cover_inspection": cover,
            "cover_inspection_id": cover["id"],
            "final_inspection": final,
            "final_inspection_id": final["id"],
            "operating_permit": operating_permit,
            "operating_permit_id": operating_permit["id"],
        }
    )
    return ctx


def pay_parcel_fees_in_full(api, parcel_id, payer_headers=None):
    """Settle whatever the parcel currently owes so fee_balance_cents reaches zero."""
    payer_headers = payer_headers or APPLICANT
    parcel = refresh_parcel(api, parcel_id, payer_headers)
    outstanding = parcel["fee_balance_cents"]
    if outstanding == 0:
        return parcel
    return get_success_data(
        api.record_fee_payment(parcel_id, {"amount_cents": outstanding}, payer_headers)
    )


def request_transfer_inspection(
    api, parcel_id, operating_permit_id, requester_headers=None, **overrides
):
    """Re-read the parcel for its current version, then open a transfer request."""
    requester_headers = requester_headers or APPLICANT
    parcel = refresh_parcel(api, parcel_id, requester_headers)
    payload = create_transfer_inspection_payload(
        parcel_id, operating_permit_id, parcel["version"], **overrides
    )
    return get_success_data(
        api.create_transfer_inspection(payload, requester_headers)
    )


def open_repair_order(api, operating_permit_id, reporter_headers=None, **overrides):
    payload = create_repair_order_payload(operating_permit_id, **overrides)
    return get_success_data(api.create_repair_order(payload, reporter_headers or EHS_FIELD))


def open_and_issue_repair_order(
    api, operating_permit_id, reporter_headers=None, officer_headers=None, **overrides
):
    """Open a failure investigation and issue it, starting the enforcement cascade."""
    order = open_repair_order(
        api, operating_permit_id, reporter_headers=reporter_headers, **overrides
    )
    return get_success_data(
        api.issue_repair_order(order["id"], officer_headers or HEALTH_OFFICER)
    )


def file_pumping_record(api, operating_permit_id, contractor_id, **overrides):
    """File a pump-out as the named Contractor, whose id is the Pumper's X-User-ID."""
    payload = create_pumping_record_payload(operating_permit_id, **overrides)
    return get_success_data(
        api.create_pumping_record(payload, make_pumper_headers(contractor_id))
    )


def condemn_parcel_well(api, well_id, collected_at="2026-05-01T06:00:00Z", nitrate_mg_l=2.0):
    """Post an UNSAFE sample so the well is CONDEMNED and the parcel flag is raised."""
    return post_water_sample(
        api,
        well_id,
        collected_at=collected_at,
        nitrate_mg_l=nitrate_mg_l,
        coliform_present=True,
    )
