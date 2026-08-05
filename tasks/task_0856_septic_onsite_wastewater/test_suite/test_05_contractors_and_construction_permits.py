"""Licensed firms, permit issue and the two compensating ledgers."""

from test_helpers import (
    ApiErrorId,
    assert_construction_permit,
    assert_contractor,
    assert_parcel_ledger_invariants,
    create_active_contractor,
    create_approved_system_design,
    create_contractor_payload,
    issue_construction_permit,
    refresh_construction_permit,
    refresh_contractor,
    refresh_inspection,
    refresh_parcel,
    refresh_system_design,
    schedule_inspection,
    set_clock,
    setup_permitted_parcel,
    unique_apn,
    unique_license_number,
    validate_error,
    validate_success,
)


def test_licence_number_is_globally_unique(api, health_officer_headers):
    """PRD §3.5: "Trade name and licence number must both be non-empty, and the licence
    number is globally unique across the register; a duplicate is refused with
    `ERR_DUPLICATE_LICENSE_NUMBER`."

    Design: Corner/entities/corner_duplicate_contractor_license_number_is_rejected
    """
    number = unique_license_number("LIC-0856-Z")
    first = create_active_contractor(
        api,
        business_name="First Septic",
        license_number=number,
        license_class="INSTALLER",
        license_expires_on="2030-01-01T00:00:00Z",
        bond_amount_cents=1000000,
    )
    assert_contractor(first)

    clash = api.create_contractor(
        create_contractor_payload(
            business_name="Second Septic",
            license_number=number,
            license_class="PUMPER",
            license_expires_on="2031-01-01T00:00:00Z",
            bond_amount_cents=2000000,
        ),
        health_officer_headers,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER.value, 409)
    assert refresh_contractor(api, first["id"])["business_name"] == "First Septic"


def test_licence_lapses_only_strictly_after_its_expiry_instant(api, health_officer_headers):
    """PRD §3.5: "Otherwise, if the logical clock has moved strictly past
    `license_expires_on`, the effective posture is `EXPIRED` even though the
    administrative status still reads `ACTIVE`."
    PRD §3.5: "The expiry comparison is strict: a clock standing exactly on
    `license_expires_on` still leaves the licence active."

    Design: Corner/entities/corner_contractor_effective_status_expires_strictly_after_license_date
    """
    contractor = create_active_contractor(
        api,
        business_name="Edge Septic",
        license_number=unique_license_number("LIC-0856-Y"),
        license_class="DUAL",
        license_expires_on="2026-06-01T00:00:00Z",
        bond_amount_cents=1000000,
    )

    set_clock(api, "2026-06-01T00:00:00Z")
    on_the_instant = refresh_contractor(api, contractor["id"], health_officer_headers)
    assert on_the_instant["effective_status"] == "ACTIVE"
    assert on_the_instant["status"] == "ACTIVE"

    set_clock(api, "2026-06-01T00:00:01Z")
    one_second_later = refresh_contractor(api, contractor["id"], health_officer_headers)
    assert one_second_later["effective_status"] == "EXPIRED"
    assert one_second_later["status"] == "ACTIVE", (
        "the administrative status is untouched by the passage of the clock"
    )


def test_permit_fee_rounds_each_loaded_line_item_before_summing(api, applicant_headers):
    """PRD §3.5: "The first is a base plan-review charge of 45000 cents. The second is
    a flow charge: the design's `design_flow_gpd` multiplied by 65 cents per gallon per
    day."
    PRD §3.5: "**The rounding order is pinned:** multiply each line item by 1.0675,
    round *that line* half up to whole cents, and only then sum the four rounded lines
    to obtain `fee_cents`. Summing the raw lines and applying the loading once at the
    end is wrong and produces a different total."

    Design: Difficulty/combinatorial_formula/construction_permit_fee_rounds_each_line_item_before_summing
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CF2"),
        site_address="4 Fee Street",
    )
    permit = ctx["construction_permit"]
    assert_construction_permit(permit)

    assert permit["fee_cents"] == 73018, (
        "48037.5 rounds to 48038 and 24979.5 rounds to 24980, summing to 73018"
    )
    assert permit["fee_cents"] != 73017, (
        "73017 is the sum-then-round total and must not be produced"
    )


def test_permit_issue_charges_the_parcel_and_mints_the_permit_number(api, applicant_headers):
    """PRD §3.1: "`fees_assessed_cents` is the lifetime total of permit fees charged to
    the parcel and grows by a permit's `fee_cents` when that permit is issued."
    PRD §3.5: "The permit number is formed as the parcel's county code, then a hyphen,
    then the letters `CP`, then a hyphen, then a zero-padded six-digit sequence number;
    the sequence is the count of construction permits already issued in that same
    county plus one, so the first permit ever issued in county `WA` is numbered
    `WA-CP-000001`."

    Design: Difficulty/combinatorial_formula/construction_permit_fee_rounds_each_line_item_before_summing
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CF2B"),
        county_code="OR",
        site_address="4 Fee Street",
    )
    permit = ctx["construction_permit"]
    assert permit["permit_number"] == "OR-CP-000001"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["fees_assessed_cents"] == 73018
    assert parcel["fee_balance_cents"] == 73018
    assert_parcel_ledger_invariants(parcel)


def test_parcel_window_collides_on_an_exact_endpoint_touch(api, applicant_headers, health_officer_headers):
    """PRD §3.5: "Two closed windows collide when the new window's `valid_from` is at or
    before the existing permit's `valid_until` *and* the existing permit's `valid_from`
    is at or before the new window's `valid_until`. There is no buffer of any kind, and
    because both endpoints are included, a new window beginning at the exact instant an
    existing one ends does collide — deliberately unlike the contractor calendar rule of
    §3.6, where exact adjacency is permitted."

    Design: Difficulty/resource_temporal_overlap/parcel_construction_window_closed_interval_rejects_exact_endpoint_touch
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TO2"),
        site_address="17 Window Way",
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    second_design = create_approved_system_design(
        api, ctx["site_evaluation_id"], drainfield_x_ft=250, drainfield_y_ft=0
    )

    refused = api.create_construction_permit(
        {
            "system_design_id": second_design["id"],
            "contractor_id": ctx["contractor_id"],
            "valid_from": "2026-12-01T00:00:00Z",
            "valid_until": "2027-06-01T00:00:00Z",
        },
        health_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value, 409)


def test_parcel_window_one_day_later_clears_the_conflict(api, applicant_headers, health_officer_headers):
    """PRD §3.5: "Every other construction permit on the same parcel whose status is
    `ISSUED`, `UNDER_CONSTRUCTION` or `COVER_PASSED` occupies the parcel over its own
    closed window; permits that are `COMPLETED`, `VOIDED` or `EXPIRED` release it."
    PRD §3.1: "it is re-derived from scratch as the sum of `design_flow_gpd` over every
    construction permit on the parcel whose status is `ISSUED`, `UNDER_CONSTRUCTION`,
    `COVER_PASSED` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/parcel_construction_window_closed_interval_rejects_exact_endpoint_touch
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-TO2B"),
        county_code="OR",
        site_address="17 Window Way",
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    second_design = create_approved_system_design(
        api, ctx["site_evaluation_id"], drainfield_x_ft=250, drainfield_y_ft=0
    )

    second_permit = validate_success(
        api.create_construction_permit(
            {
                "system_design_id": second_design["id"],
                "contractor_id": ctx["contractor_id"],
                "valid_from": "2026-12-02T00:00:00Z",
                "valid_until": "2027-06-02T00:00:00Z",
            },
            health_officer_headers,
        ),
        201,
    )
    assert second_permit["status"] == "ISSUED"
    assert second_permit["permit_number"] == "OR-CP-000002"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["permitted_design_flow_gpd"] == 720
    assert parcel["fees_assessed_cents"] == 146036


def test_voiding_a_permit_returns_the_fee_balance_to_its_pre_issue_value(api, applicant_headers, health_officer_headers):
    """PRD §3.1: "The **money-conservation property** mirrors the flow one: issuing a
    permit whose fee is some number of cents and then voiding that permit must leave
    `fee_balance_cents` exactly where it started, while `fees_assessed_cents` and
    `fees_credited_cents` have each grown by that same number of cents."
    PRD §3.5: "The parcel's `fees_credited_cents` grows by exactly this permit's
    `fee_cents` and `fee_balance_cents` is re-derived, restoring the money-conservation
    property of §3.1."

    Design: Difficulty/compensating_invariant/void_permit_conserves_parcel_money_ledger
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CI1"),
        site_address="18 Ledger Lane",
    )
    before_issue_balance = 0

    validate_success(
        api.void_construction_permit(
            ctx["construction_permit_id"],
            {"reason": "Applicant withdrew the application"},
            health_officer_headers,
        ),
        200,
    )

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["fees_assessed_cents"] == 73018
    assert parcel["fees_credited_cents"] == 73018
    assert parcel["fees_paid_cents"] == 0
    assert parcel["fee_balance_cents"] == before_issue_balance
    assert_parcel_ledger_invariants(parcel)


def test_voiding_a_permit_returns_the_design_to_approved(api, applicant_headers, health_officer_headers):
    """PRD §3.5: "A void moves the permit to `VOIDED`, which is terminal, and carries
    four consequences."
    PRD §3.5: "The cited design returns `PERMITTED → APPROVED`, so it may be permitted
    afresh."

    Design: Difficulty/compensating_invariant/void_permit_conserves_parcel_money_ledger
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CI1B"),
        site_address="18 Ledger Lane",
    )
    assert refresh_system_design(api, ctx["system_design_id"])["status"] == "PERMITTED"

    voided = validate_success(
        api.void_construction_permit(
            ctx["construction_permit_id"],
            {"reason": "Applicant withdrew the application"},
            health_officer_headers,
        ),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert refresh_system_design(api, ctx["system_design_id"])["status"] == "APPROVED"


def test_voiding_one_of_two_permits_releases_exactly_its_own_flow(api, applicant_headers, health_officer_headers):
    """PRD §3.1: "Permits that have gone `VOIDED` or `EXPIRED` are excluded from that
    sum, which is what gives the register its **flow-conservation property**: issuing a
    permit for some quantity of flow and then voiding that same permit must leave
    `permitted_design_flow_gpd` exactly equal to its value before the issue, not merely
    close to it."
    PRD §3.5: "The parcel's `permitted_design_flow_gpd` is re-derived, which releases
    this permit's flow because a `VOIDED` permit is outside the summed set."

    Design: Difficulty/compensating_invariant/void_permit_conserves_parcel_hydraulic_design_flow
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CI2"),
        site_address="19 Flow Field",
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    assert refresh_parcel(api, ctx["parcel_id"])["permitted_design_flow_gpd"] == 360

    large_design = create_approved_system_design(
        api,
        ctx["site_evaluation_id"],
        bedrooms=5,
        tank_capacity_gal=1500,
        drainfield_x_ft=250,
        drainfield_y_ft=0,
    )
    assert large_design["design_flow_gpd"] == 600
    assert large_design["required_drainfield_sqft"] == 1000

    large_permit = issue_construction_permit(
        api,
        large_design["id"],
        ctx["contractor_id"],
        valid_from="2027-01-01T00:00:00Z",
        valid_until="2027-06-01T00:00:00Z",
    )
    assert refresh_parcel(api, ctx["parcel_id"])["permitted_design_flow_gpd"] == 960

    validate_success(
        api.void_construction_permit(
            large_permit["id"], {"reason": "Second dwelling cancelled"}, health_officer_headers
        ),
        200,
    )

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["permitted_design_flow_gpd"] == 360, (
        "exactly the value held before the second permit was issued"
    )
    assert parcel["max_design_flow_gpd"] == 1500, "the allowance is untouched by issue or void"
    assert refresh_construction_permit(api, ctx["construction_permit_id"])["status"] == "ISSUED"


def test_voiding_the_larger_permit_credits_only_its_own_fee(api, applicant_headers, health_officer_headers):
    """PRD §3.5: "The second is a flow charge: the design's `design_flow_gpd` multiplied
    by 65 cents per gallon per day."
    PRD §3.1: "`fees_credited_cents` is the lifetime total of reversals and grows by a
    permit's `fee_cents` when that permit is voided. The outstanding `fee_balance_cents`
    is then the assessed total less the paid total less the credited total."

    Design: Difficulty/compensating_invariant/void_permit_conserves_parcel_hydraulic_design_flow
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-CI2B"),
        site_address="19 Flow Field",
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    large_design = create_approved_system_design(
        api,
        ctx["site_evaluation_id"],
        bedrooms=5,
        tank_capacity_gal=1500,
        drainfield_x_ft=250,
        drainfield_y_ft=0,
    )
    large_permit = issue_construction_permit(
        api,
        large_design["id"],
        ctx["contractor_id"],
        valid_from="2027-01-01T00:00:00Z",
        valid_until="2027-06-01T00:00:00Z",
    )
    assert large_permit["fee_cents"] == 89671, "48038 plus the 41633 loaded 600 gpd flow line"

    validate_success(
        api.void_construction_permit(
            large_permit["id"], {"reason": "Second dwelling cancelled"}, health_officer_headers
        ),
        200,
    )
    assert refresh_construction_permit(api, large_permit["id"])["status"] == "VOIDED"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["fees_assessed_cents"] == 162689
    assert parcel["fees_credited_cents"] == 89671
    assert parcel["fee_balance_cents"] == 73018
    assert_parcel_ledger_invariants(parcel)


def test_clock_past_valid_until_expires_the_permit_and_cancels_its_scheduled_visit(api, applicant_headers):
    """PRD §3.5: "When the logical clock advances strictly past a permit's `valid_until`
    while that permit is `ISSUED` or `UNDER_CONSTRUCTION`, it moves to `EXPIRED`, which
    is terminal; its flow is released from the parcel ledger and its `SCHEDULED`
    inspections are cancelled."
    PRD §3.5: "Note the asymmetry with a void: expiry cancels only `SCHEDULED`
    inspections and issues no fee credit, whereas a void cancels `SCHEDULED` and
    `FAILED` inspections alike and does credit the fee."

    Design: Corner/state_machines/corner_clock_advance_past_valid_until_expires_permit_and_cancels_scheduled_inspection
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-S10"),
        site_address="41 Expiry End",
        permit_valid_from="2026-05-01T00:00:00Z",
        permit_valid_until="2026-06-01T00:00:00Z",
    )
    inspection = schedule_inspection(
        api,
        ctx["construction_permit_id"],
        inspection_type="COVER",
        scheduled_start="2026-05-20T09:00:00Z",
        scheduled_end="2026-05-20T10:00:00Z",
    )
    assert refresh_construction_permit(api, ctx["construction_permit_id"])["status"] == "UNDER_CONSTRUCTION"

    set_clock(api, "2026-06-02T00:00:00Z")

    assert refresh_construction_permit(api, ctx["construction_permit_id"])["status"] == "EXPIRED"
    assert refresh_inspection(api, inspection["id"])["status"] == "CANCELLED"

    parcel = refresh_parcel(api, ctx["parcel_id"])
    assert parcel["permitted_design_flow_gpd"] == 0
    assert parcel["fees_assessed_cents"] == 73018
    assert parcel["fees_credited_cents"] == 0, "expiry issues no fee credit"
    assert parcel["fee_balance_cents"] == 73018
    assert refresh_system_design(api, ctx["system_design_id"])["status"] == "PERMITTED"
