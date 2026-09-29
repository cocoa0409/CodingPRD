"""Financial assurance: a coverage timeline that must union, and a clamped bond.

Covers the closed-interval contiguity of the certificate set against the permit
term, and the three paths of the bond requirement formula.
"""
from test_helpers import (
    ApiErrorId,
    create_outfitter,
    create_published_assessment,
    create_screened_application,
    create_use_area,
    create_approved_operating_plan,
    file_bond,
    file_insurance_certificate,
    issue_permit,
    list_bonds,
    list_insurance_certificates,
    read_permit,
    set_clock,
    setup_issued_permit,
    staff_roster_to_party_size,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]

BIRCH = {
    "legal_name": "Birch Bend Guides LLC",
    "ein": "410000002",
    "contact_email": "ops@birch.example",
    "prequalification_insurance_verified": True,
}
CEDAR = {
    "legal_name": "Cedar Creek Guides LLC",
    "ein": "410000003",
    "contact_email": "ops@cedar.example",
    "prequalification_insurance_verified": True,
}
WILLOW_AREA = {
    "area_code": "WIL-02",
    "name": "Willow Divide",
    "total_allocated_service_days": 2000,
    "reserved_admin_service_days": 0,
}


def _two_season_permit_with_a_one_day_hole():
    """An ISSUED permit whose term spans two calendar years, covered by two
    certificates that leave 2028-01-01 uncovered."""
    context = setup_issued_permit(
        permit_overrides={
            "term_start_date": "2027-01-01",
            "term_end_date": "2028-12-31",
        }
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    staff_roster_to_party_size(context)
    create_approved_operating_plan(permit_id, outfitter_id, 2027)
    file_bond(
        permit_id,
        outfitter_id,
        bond_amount_cents=1_000_000,
        effective_date="2027-01-01",
        expiration_date="2029-12-31",
    )
    context["c1"] = file_insurance_certificate(
        permit_id,
        outfitter_id,
        coverage_amount_cents=100_000_000,
        effective_date="2027-01-01",
        expiration_date="2027-12-31",
    )
    context["c2"] = file_insurance_certificate(
        permit_id,
        outfitter_id,
        coverage_amount_cents=100_000_000,
        effective_date="2028-01-02",
        expiration_date="2028-12-31",
    )
    return context


def test_a_single_uncovered_day_inside_the_term_blocks_activation_on_its_own_rule():
    """PRD §3.6: "Continuity asks whether the `ACTIVE` certificate set leaves any uncovered
    calendar day in the closed interval from `term_start_date` to `term_end_date`; certificate
    intervals are closed, and two certificates are contiguous when the later one's
    `effective_date` falls on or before the day after the earlier one's `expiration_date`, so a
    single uncovered day is a gap and yields `ERR_INSURANCE_COVERAGE_GAP`."
    PRD §3.6: "Sufficiency asks whether the sum of `coverage_amount_cents` over the permit's
    `ACTIVE` `GENERAL_LIABILITY` certificates reaches the area's `min_liability_coverage_cents`
    with `additional_insured_endorsed` true on each; failing that is
    `ERR_INSURANCE_COVERAGE_INSUFFICIENT`."
    PRD §3.6: "`bond_current` is always evaluated against the permit's *current* requirement, and
    is true exactly when some `ACTIVE` bond on the permit carries a `bond_amount_cents` at or
    above it."

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_closed_interval_contiguity
    """
    context = _two_season_permit_with_a_one_day_hole()
    permit_id = context["permit"]["id"]

    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_INSURANCE_COVERAGE_GAP,
    )

    permit = read_permit(permit_id)
    assert permit["administrative_status"] == "ISSUED"
    assert permit["insurance_current"] is True, (
        "the existence test passes while the interval union still has a hole"
    )
    assert permit["bond_current"] is True
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["indemnification_acknowledged"] is True
    assert permit["authorized_client_capacity_total"] == 12
    assert context["use_area"]["party_size_max"] == 12
    version_before_c3 = permit["version"]

    certificates, meta = list_insurance_certificates(permit_id)
    assert meta["total_count"] == 2
    assert [row["status"] for row in certificates] == ["ACTIVE", "ACTIVE"]

    c3 = file_insurance_certificate(
        context["permit"]["id"],
        context["outfitter"]["id"],
        coverage_amount_cents=100_000_000,
        effective_date="2028-01-01",
        expiration_date="2028-12-31",
    )
    assert c3["status"] == "ACTIVE"

    after, _meta = list_insurance_certificates(permit_id)
    by_id = {row["id"]: row for row in after}
    assert by_id[context["c1"]["id"]]["status"] == "ACTIVE", (
        "a certificate merely followed in time is not superseded"
    )
    assert by_id[context["c2"]["id"]]["status"] == "SUPERSEDED", (
        "the new closed interval fully contains C2, which shares its coverage_type"
    )
    assert read_permit(permit_id)["version"] == version_before_c3 + 1

    activated = validate_success(api_client.activate_permit(permit_id, OFFICER))
    assert activated["administrative_status"] == "ACTIVE"
    assert activated["insurance_current"] is True


def test_coverage_may_stop_exactly_on_the_terms_last_day_but_may_not_start_a_day_late():
    """PRD §3.6: "Continuity asks whether the `ACTIVE` certificate set leaves any uncovered
    calendar day in the closed interval from `term_start_date` to `term_end_date`; certificate
    intervals are closed, and two certificates are contiguous when the later one's
    `effective_date` falls on or before the day after the earlier one's `expiration_date`, so a
    single uncovered day is a gap and yields `ERR_INSURANCE_COVERAGE_GAP`."
    PRD §3.6: "Supersession is deliberately narrow: an existing `ACTIVE` certificate on the same
    permit moves to `SUPERSEDED` only when the new certificate shares its `coverage_type` **and**
    the new closed interval fully contains the existing one."
    PRD §3.6: "A renewal certificate that merely follows the old one in time therefore leaves the
    earlier certificate `ACTIVE`, which is exactly what allows a contiguous chain of same-type
    certificates to cover a multi-year term."

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_closed_interval_contiguity
    """
    context = setup_issued_permit(
        permit_overrides={
            "term_start_date": "2027-01-01",
            "term_end_date": "2028-12-31",
        }
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    staff_roster_to_party_size(context)
    create_approved_operating_plan(permit_id, outfitter_id, 2027)
    file_bond(
        permit_id,
        outfitter_id,
        bond_amount_cents=1_000_000,
        effective_date="2027-01-01",
        expiration_date="2029-12-31",
    )

    late = file_insurance_certificate(
        permit_id,
        outfitter_id,
        coverage_amount_cents=100_000_000,
        effective_date="2027-01-02",
        expiration_date="2028-12-31",
    )
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_INSURANCE_COVERAGE_GAP,
    )
    assert read_permit(permit_id)["administrative_status"] == "ISSUED"

    containing = file_insurance_certificate(
        permit_id,
        outfitter_id,
        coverage_amount_cents=100_000_000,
        effective_date="2027-01-01",
        expiration_date="2028-12-31",
    )
    rows, meta = list_insurance_certificates(permit_id)
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[late["id"]]["status"] == "SUPERSEDED"
    assert by_id[containing["id"]]["status"] == "ACTIVE"

    activated = validate_success(api_client.activate_permit(permit_id, OFFICER))
    assert activated["administrative_status"] == "ACTIVE", (
        "coverage running exactly from term_start_date to term_end_date is sufficient"
    )
    assert activated["insurance_current"] is True
    assert activated["bond_current"] is True


def test_the_bond_requirement_takes_all_three_of_its_paths_and_freezes_each_figure():
    """PRD §3.6: "The requirement is derived from the permit: the raw amount is
    `authorized_service_days` multiplied by 5000 cents per service day, then clamped into the
    closed range from a floor of 250000 cents to a ceiling of 5000000 cents. That figure is
    written onto the bond row as `required_amount_cents` and frozen there for the audit record, so
    a later change to `authorized_service_days` never rewrites a filed bond's stored requirement —
    while `bond_current` is always evaluated against the permit's *current* requirement, and is
    true exactly when some `ACTIVE` bond on the permit carries a `bond_amount_cents` at or above
    it. A bond exactly equal to the requirement satisfies it."
    PRD §3.6: "Only `ACTIVE` bonds count; `SUPERSEDED` and `EXPIRED` bonds never satisfy the
    requirement, and both are terminal. Unlike insurance, bond supersession is unconditional:
    filing a new bond moves *any* prior `ACTIVE` bond on that permit to `SUPERSEDED`, because the
    program requires exactly one bond in force at a time rather than a layered set."
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`."

    Design: Corner/calculations/bond_requirement_clamps_at_the_floor_and_the_ceiling_constants
    """
    set_clock()
    bear = create_use_area()
    create_published_assessment(bear["id"], determined_capacity_service_days=900)
    willow = create_use_area(**WILLOW_AREA)
    create_published_assessment(willow["id"], determined_capacity_service_days=2000)

    alpine = create_outfitter()
    birch = create_outfitter(**BIRCH)
    cedar = create_outfitter(**CEDAR)

    alpine_permit = issue_permit(
        create_screened_application(
            alpine["id"], bear["id"], requested_service_days=200
        )["id"]
    )
    birch_permit = issue_permit(
        create_screened_application(
            birch["id"],
            bear["id"],
            requested_service_days=40,
            proposed_activity_type="FISHING",
        )["id"]
    )
    cedar_permit = issue_permit(
        create_screened_application(
            cedar["id"],
            willow["id"],
            requested_service_days=1200,
            proposed_activity_type="MOUNTAINEERING",
        )["id"]
    )
    assert alpine_permit["authorized_service_days"] == 200
    assert birch_permit["authorized_service_days"] == 40
    assert cedar_permit["authorized_service_days"] == 1200

    inside_band = file_bond(
        alpine_permit["id"], alpine["id"], bond_amount_cents=1_000_000
    )
    assert inside_band["required_amount_cents"] == 1_000_000
    assert inside_band["status"] == "ACTIVE"
    assert read_permit(alpine_permit["id"])["bond_current"] is True, (
        "an amount exactly equal to the requirement satisfies it"
    )

    clamped_up = file_bond(
        birch_permit["id"], birch["id"], bond_amount_cents=200_000
    )
    assert clamped_up["required_amount_cents"] == 250_000, (
        "the raw 40 * 5000 = 200000 is clamped up to the 250000 floor"
    )
    assert read_permit(birch_permit["id"])["bond_current"] is False

    repaired = file_bond(
        birch_permit["id"], birch["id"], bond_amount_cents=250_000
    )
    assert repaired["required_amount_cents"] == 250_000
    assert read_permit(birch_permit["id"])["bond_current"] is True

    bonds, meta = list_bonds(birch_permit["id"])
    assert meta["total_count"] == 2
    assert [row["id"] for row in bonds] == [clamped_up["id"], repaired["id"]]
    assert bonds[0]["status"] == "SUPERSEDED"
    assert bonds[0]["required_amount_cents"] == 250_000, (
        "the superseded row keeps its frozen requirement for the audit record"
    )
    assert bonds[1]["status"] == "ACTIVE"

    clamped_down = file_bond(
        cedar_permit["id"], cedar["id"], bond_amount_cents=5_000_000
    )
    assert clamped_down["required_amount_cents"] == 5_000_000, (
        "the raw 1200 * 5000 = 6000000 is clamped down to the 5000000 ceiling"
    )
    assert read_permit(cedar_permit["id"])["bond_current"] is True

    for permit_id in (alpine_permit["id"], birch_permit["id"], cedar_permit["id"]):
        after = read_permit(permit_id)
        assert after["administrative_status"] == "ISSUED"
        assert after["insurance_current"] is False
        assert after["compliance_status"] == "PROBATION", (
            "every bond write re-derives compliance, which the missing insurance drives"
        )
