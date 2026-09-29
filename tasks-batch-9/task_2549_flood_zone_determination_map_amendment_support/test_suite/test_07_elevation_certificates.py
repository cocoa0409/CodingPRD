"""Elevation certificates: the datum conversion, its review, and what it writes.

A certificate is the only evidence that can move a building's recorded elevation,
and it earns that authority through a four-step conversion whose order is pinned
and a review that is walled off from whoever filed it.  Filing converts; only a
validating review publishes.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ANALYST_USER_ID,
    BORROWER_USER_ID,
    REVIEWER_USER_ID,
    ApiErrorId,
    api_client,
    assert_determination,
    assert_elevation_certificate,
    create_community,
    create_elevation_certificate_payload,
    create_property,
    create_structure,
    file_certificate,
    make_agency_headers,
    make_analyst_headers,
    make_borrower_headers,
    make_lender_headers,
    make_reviewer_headers,
    publish_panel,
    read_folio,
    review_certificate,
    set_clock,
    setup_base_chain,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_freeboard_rounds_the_converted_elevation_before_it_subtracts_the_bfe():
    """A survey of 8.94 ft in Florida against a base flood elevation of 7.75 ft is
    the case that separates the two rounding orders: the pinned order clears the
    panel by a tenth of a foot, the rejected one lands exactly on it.

    PRD §2.7: "Elevations, boundary offsets and freeboard figures are measured in feet: raw surveyed elevations and panel base flood elevations are carried to 2 decimal places, while every converted elevation and every freeboard figure is rounded to 1 decimal place using round-half-up."
    PRD §2.7: "Where a rounding step is described as happening before a subtraction, that order is mandatory: rounding after the subtraction instead produces a different answer at the tenth-of-a-foot scale, and because amendment eligibility turns on whether a freeboard figure is strictly above zero, the difference between the two orders is the difference between a grant and a rejection rather than a cosmetic one."
    PRD §3.8: "Vertical datums differ by region, and the shift from NGVD29 to NAVD88 is selected by the community's `state_code`: −2.44 feet in `CA`, −1.15 feet in `FL`, −0.87 feet in `TX`, and −0.55 feet in `NC`."
    PRD §3.8: "Step one shifts each raw survey value into NAVD88 by adding the offset."
    PRD §3.8: "Step two rounds each shifted value to 1 decimal place half-up, producing `converted_lowest_floor_ft` from `raw_lowest_floor_elevation_ft` and `converted_lag_ft` from `raw_lowest_adjacent_grade_ft` — the rounding happens here, before any subtraction."
    PRD §3.8: "Step three subtracts the reference panel's `base_flood_elevation_ft`, which carries 2 decimal places, from each already-rounded converted value."
    PRD §3.8: "Step four rounds each difference to 1 decimal place half-up, producing `freeboard_ft` from the lowest floor and `lag_freeboard_ft` from the lowest adjacent grade."
    PRD §3.8: "A newly filed certificate is stored in `status` `SUBMITTED` with `submitted_by_user_id` set to the acting `X-User-ID` — the anchor of the certificate-review segregation-of-duties check — and with `rejection_reason` and `reviewed_by_user_id` null."

    Design: Difficulty/combinatorial_formula/elevation_freeboard_nested_rounding_order_pinned
    """
    set_clock(CLOCK)
    community = create_community(state_code="FL")
    panel = publish_panel(community["id"], base_flood_elevation_ft=7.75)
    prop = create_property(community["id"])
    structure = create_structure(prop["id"])

    certificate = file_certificate(
        structure["id"],
        surveyor_license_number="FL-PSM-8841",
        survey_date="2026-07-01T00:00:00Z",
        datum="NGVD29",
        raw_lowest_floor_elevation_ft=8.94,
        raw_lowest_adjacent_grade_ft=8.90,
        machinery_elevation_ft=9.50,
    )
    assert_elevation_certificate(certificate)

    # Step one and two: 8.94 - 1.15 == 7.79, rounded to 7.8.
    assert certificate["converted_lowest_floor_ft"] == 7.8
    # 8.90 - 1.15 == 7.75 exactly, and the midpoint rounds up.
    assert certificate["converted_lag_ft"] == 7.8
    # Steps three and four run on the ROUNDED 7.8: 7.8 - 7.75 == 0.05 -> 0.1.
    # Subtracting first would give 8.94 - 1.15 - 7.75 == 0.04 -> 0.0.
    assert certificate["freeboard_ft"] == 0.1
    assert certificate["freeboard_ft"] != 0.0
    assert certificate["lag_freeboard_ft"] == 0.1
    assert certificate["lag_freeboard_ft"] != 0.0

    assert certificate["reference_panel_id"] == panel["id"]
    assert certificate["status"] == "SUBMITTED"
    assert certificate["submitted_by_user_id"] == ANALYST_USER_ID
    assert certificate["rejection_reason"] is None
    assert certificate["reviewed_by_user_id"] is None

    # Filing converts; it does not publish.
    unwritten = validate_success(
        api_client.get_structure(structure["id"], headers=make_analyst_headers())
    )
    assert unwritten["lowest_floor_elevation_ft"] is None
    assert unwritten["lowest_adjacent_grade_ft"] is None
    assert unwritten["elevation_source_certificate_id"] is None


def test_the_datum_offset_is_chosen_by_state_and_zero_for_a_navd88_survey():
    """Two certificates carrying the same raw numbers diverge by a foot because one
    declares the older datum and one does not, and each still rounds twice — once
    on the shifted elevation and once on the difference.

    PRD §3.8: "Vertical datums differ by region, and the shift from NGVD29 to NAVD88 is selected by the community's `state_code`: −2.44 feet in `CA`, −1.15 feet in `FL`, −0.87 feet in `TX`, and −0.55 feet in `NC`."
    PRD §3.8: "When the certificate's `datum` is `NGVD29` that state-specific offset applies; when it is already `NAVD88` the offset is zero."
    PRD §3.8: "The conversion then proceeds in four steps and the order is mandatory."
    PRD §3.8: "Step two rounds each shifted value to 1 decimal place half-up, producing `converted_lowest_floor_ft` from `raw_lowest_floor_elevation_ft` and `converted_lag_ft` from `raw_lowest_adjacent_grade_ft` — the rounding happens here, before any subtraction."
    PRD §3.8: "Step four rounds each difference to 1 decimal place half-up, producing `freeboard_ft` from the lowest floor and `lag_freeboard_ft` from the lowest adjacent grade."
    PRD §3.8: "Rounding the difference once, instead of rounding the converted value first, produces a different answer at the tenth-of-a-foot scale, and because amendment eligibility requires a freeboard figure strictly above zero, the two orders differ by grant versus rejection rather than by a cosmetic tenth."
    PRD §3.8: "The structure's property must be geocoded, failing which the rejection is `ERR_PROPERTY_NOT_GEOCODED`, and an effective panel must exist for that property, failing which the rejection is `ERR_NO_EFFECTIVE_PANEL`; the panel chosen by the same effective-panel rule used for determinations is recorded on the certificate as `reference_panel_id` and supplies the base flood elevation the freeboard figures are measured against."

    Design: Corner/calculations/corner_datum_conversion_rounds_twice_at_one_decimal
    """
    set_clock(CLOCK)
    community = create_community(
        community_id_code="480296", name="Harris County TX", state_code="TX",
        participation_status="REGULAR",
    )
    panel = publish_panel(
        community["id"], map_panel_number="48201C0455L", revision_sequence=1,
        zone_code="AE", base_flood_elevation_ft=8.05,
        effective_date="2019-11-15T00:00:00Z",
    )
    prop = create_property(
        community["id"], street_address="902 Buffalo Bayou Dr", city="Houston",
        postal_code="77002", map_panel_number="48201C0455L",
        latitude=29.7604, longitude=-95.3698, geocode_method="ROOFTOP",
        geocode_confidence_score=0.94,
    )
    structure = create_structure(
        prop["id"], replacement_cost_cents=29000000, sfha_offset_ft=-8.0
    )

    shifted = file_certificate(
        structure["id"],
        surveyor_license_number="TX-RPLS-5512",
        survey_date="2026-07-01T00:00:00Z",
        datum="NGVD29",
        raw_lowest_floor_elevation_ft=9.06,
        raw_lowest_adjacent_grade_ft=8.94,
    )
    assert_elevation_certificate(shifted)
    # Texas shifts by -0.87: 9.06 - 0.87 == 8.19, rounded to 8.2.
    assert shifted["converted_lowest_floor_ft"] == 8.2
    # 8.2 - 8.05 == 0.15 -> 0.2.  A single terminal rounding of 8.19 - 8.05
    # would have produced 0.1.
    assert shifted["freeboard_ft"] == 0.2
    # 8.94 - 0.87 == 8.07 -> 8.1, and 8.1 - 8.05 == 0.05 rounds half UP.
    assert shifted["converted_lag_ft"] == 8.1
    assert shifted["lag_freeboard_ft"] == 0.1
    assert shifted["reference_panel_id"] == panel["id"]
    assert shifted["status"] == "SUBMITTED"

    unshifted = file_certificate(
        structure["id"],
        surveyor_license_number="TX-RPLS-5512",
        survey_date="2026-07-01T00:00:00Z",
        datum="NAVD88",
        raw_lowest_floor_elevation_ft=9.06,
        raw_lowest_adjacent_grade_ft=8.94,
    )
    # Already in NAVD88, so the state offset is irrelevant: 9.06 -> 9.1.
    assert unshifted["converted_lowest_floor_ft"] == 9.1
    assert unshifted["freeboard_ft"] == 1.1
    assert unshifted["converted_lag_ft"] == 8.9
    assert unshifted["lag_freeboard_ft"] == 0.9
    assert unshifted["reference_panel_id"] == panel["id"]

    # Neither filing published anything: the conversion lives on the certificate.
    still_unsurveyed = validate_success(
        api_client.get_structure(structure["id"], headers=make_analyst_headers())
    )
    assert still_unsurveyed["lowest_floor_elevation_ft"] is None
    assert still_unsurveyed["elevation_source_certificate_id"] is None


def test_certificate_filing_is_shared_between_two_roles_but_its_review_is_not():
    """The borrower and the provider analyst may both file, and their filings are
    arithmetically identical; the review is exclusive to the independent reviewer
    even for the certificate the provider's own side filed.

    PRD §3.8: "A surveyed elevation certificate is the only evidence that can move a building's recorded elevation, and either a `Borrower` or a `ProviderAnalyst` may file one."
    PRD §3.8: "A `Borrower` filer must be the borrower named on the relevant folio or the filing is rejected with `ERR_BORROWER_NOT_ON_LOAN`."
    PRD §3.8: "Only a `ProviderReviewer` may review, the certificate must be in `SUBMITTED` (reviewing one already `VALIDATED` or `REJECTED` is rejected with `ERR_INVALID_CERTIFICATE_STATE`), and the acting `X-User-ID` must differ from `submitted_by_user_id` or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.5: "Third (3) the caller's role must appear in the target endpoint's authorised role list, reporting `ERR_FORBIDDEN_ROLE`."
    PRD §3.8: "The two branches are deliberately asymmetric in what they write, and both write `reviewed_by_user_id` with the acting `X-User-ID`."

    Design: Corner/rbac/corner_certificate_filing_is_shared_but_its_review_is_not
    """
    chain = setup_base_chain(clock=CLOCK, with_determination=False)
    structure_id = chain["structure"]["id"]
    survey = {
        "surveyor_license_number": "FL-PSM-7781",
        "survey_date": "2026-07-02T00:00:00Z",
        "datum": "NGVD29",
        "raw_lowest_floor_elevation_ft": 9.34,
        "raw_lowest_adjacent_grade_ft": 9.14,
    }

    borrower_filed = file_certificate(
        structure_id, headers=make_borrower_headers(BORROWER_USER_ID), **survey
    )
    analyst_filed = file_certificate(
        structure_id, headers=make_analyst_headers("analyst-9"), **survey
    )
    assert borrower_filed["submitted_by_user_id"] == BORROWER_USER_ID
    assert analyst_filed["submitted_by_user_id"] == "analyst-9"

    # Authorship changes nothing about the arithmetic.
    for row in (borrower_filed, analyst_filed):
        assert_elevation_certificate(row)
        assert row["status"] == "SUBMITTED"
        assert row["converted_lowest_floor_ft"] == 8.2
        assert row["converted_lag_ft"] == 8.0
        assert row["freeboard_ft"] == 0.5
        assert row["lag_freeboard_ft"] == 0.3

    # Shared does not mean public.
    for headers in (
        make_reviewer_headers(),
        make_agency_headers(),
        make_lender_headers(chain["lender"]["id"]),
    ):
        validate_error(
            api_client.create_elevation_certificate(
                create_elevation_certificate_payload(structure_id, **survey),
                headers=headers,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    reviewed = review_certificate(analyst_filed["id"], decision="VALIDATED")
    assert reviewed["status"] == "VALIDATED"
    assert reviewed["reviewed_by_user_id"] == REVIEWER_USER_ID

    # The other row is still open, and no other role may act on it.
    for headers in (
        make_analyst_headers(),
        make_agency_headers(),
        make_lender_headers(chain["lender"]["id"]),
        make_borrower_headers(BORROWER_USER_ID),
    ):
        validate_error(
            api_client.review_elevation_certificate(
                borrower_filed["id"], {"decision": "VALIDATED"}, headers=headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
    assert validate_success(
        api_client.get_elevation_certificate(
            borrower_filed["id"], headers=make_analyst_headers()
        )
    )["status"] == "SUBMITTED"

    published = validate_success(
        api_client.get_structure(structure_id, headers=make_analyst_headers())
    )
    assert published["elevation_source_certificate_id"] == analyst_filed["id"]
    assert published["lowest_floor_elevation_ft"] == 8.2
    assert published["lowest_adjacent_grade_ft"] == 8.0


def test_validating_a_certificate_publishes_elevations_and_recomputes_only_freeboard():
    """Validation is the single path that moves a building's recorded elevation, and
    it recomputes the determination's freeboard while leaving the classification
    exactly where the boundary geometry put it.

    PRD §3.8: "On `VALIDATED` the certificate moves `SUBMITTED → VALIDATED` and the surveyed elevations are published onto the structure: `lowest_floor_elevation_ft` takes the certificate's `converted_lowest_floor_ft`, `lowest_adjacent_grade_ft` takes its `converted_lag_ft`, and `elevation_source_certificate_id` is set to this certificate's identifier, recording which certificate is the source of truth for those numbers."
    PRD §3.8: "The folio's current determination then recomputes its own `freeboard_ft` from the newly populated `lowest_floor_elevation_ft`; its `zone_code`, `sfha_flag` and `position_class` are explicitly **not** recomputed, because a survey tells you how high the building is, not where it sits relative to the boundary."
    PRD §3.5: "The determination's `freeboard_ft` is the structure's `lowest_floor_elevation_ft` minus that snapshotted base flood elevation, rounded to 1 decimal place half-up; when either input is null — an unsurveyed structure, or a building outside the SFHA — `freeboard_ft` is null."
    PRD §3.8: "The two branches are deliberately asymmetric in what they write, and both write `reviewed_by_user_id` with the acting `X-User-ID`."

    Design: Corner/state_machines/corner_certificate_validation_writes_structure_elevations
    """
    chain = setup_base_chain(
        clock=CLOCK, community_overrides={"participation_status": "REGULAR"}
    )
    structure_id = chain["structure"]["id"]
    determination = chain["determination"]

    # An unsurveyed structure carries no freeboard at all.
    assert determination["freeboard_ft"] is None
    assert determination["base_flood_elevation_ft"] == 7.75
    assert determination["sfha_flag"] is True

    certificate = file_certificate(
        structure_id,
        headers=make_borrower_headers(BORROWER_USER_ID),
        surveyor_license_number="FL-LS-7781",
        survey_date="2026-07-01T00:00:00Z",
        datum="NGVD29",
        raw_lowest_floor_elevation_ft=8.94,
        raw_lowest_adjacent_grade_ft=8.90,
    )
    assert certificate["converted_lowest_floor_ft"] == 7.8
    assert certificate["converted_lag_ft"] == 7.8

    validated = review_certificate(certificate["id"], decision="VALIDATED")
    assert_elevation_certificate(validated)
    assert validated["status"] == "VALIDATED"
    assert validated["reviewed_by_user_id"] == REVIEWER_USER_ID
    assert validated["rejection_reason"] is None
    assert validated["freeboard_ft"] == 0.1
    assert validated["lag_freeboard_ft"] == 0.1
    assert validated["reference_panel_id"] == chain["panel"]["id"]

    structure = validate_success(
        api_client.get_structure(structure_id, headers=make_analyst_headers())
    )
    assert structure["lowest_floor_elevation_ft"] == 7.8
    assert structure["lowest_adjacent_grade_ft"] == 7.8
    assert structure["elevation_source_certificate_id"] == certificate["id"]

    recomputed = validate_success(
        api_client.get_determination(determination["id"], headers=make_analyst_headers())
    )
    assert_determination(recomputed)
    # round_half_up(7.8 - 7.75, 1) == 0.1, on the published elevation.
    assert recomputed["freeboard_ft"] == 0.1
    # Evidence of height, not of position: the classification is untouched.
    assert recomputed["zone_code"] == "AE"
    assert recomputed["sfha_flag"] is True
    assert recomputed["position_class"] == "INSIDE"
    assert recomputed["status"] == "ISSUED"

    folio = read_folio(chain["folio"]["id"])
    assert folio["required_coverage_cents"] == 25000000
    assert folio["compliance_posture"] == "NOTICE_DUE"


def test_reviewing_an_already_validated_certificate_is_refused_as_terminal():
    """A validating review is not replayable: the second review of the same row is
    refused on state, whatever decision it carries, and neither the certificate
    nor the elevations it published are rewritten.

    PRD §3.8: "Only a `ProviderReviewer` may review, the certificate must be in `SUBMITTED` (reviewing one already `VALIDATED` or `REJECTED` is rejected with `ERR_INVALID_CERTIFICATE_STATE`), and the acting `X-User-ID` must differ from `submitted_by_user_id` or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "`VALIDATED` and `REJECTED` are both terminal."
    PRD §2.5: "Eleventh (11), the target entity must be in a state from which the requested transition is declared, reporting the invalid-state error for that entity type at HTTP 409."
    PRD §2.4: "`version` starts at 1 when the row is created and increases by exactly 1 on every mutation of that row; `updated_at` is refreshed to the current logical instant on every mutation."

    Design: Corner/state_machines/corner_second_certificate_review_rejected_as_terminal
    """
    set_clock(CLOCK)
    community = create_community(state_code="FL")
    publish_panel(community["id"], base_flood_elevation_ft=7.75)
    prop = create_property(community["id"])
    structure = create_structure(prop["id"])

    # Filed by an analyst, so no folio or determination is in play: the corner
    # isolates the lockdown from the freeboard side effect.
    certificate = file_certificate(
        structure["id"],
        headers=make_analyst_headers("analyst-2"),
        surveyor_license_number="FL-LS-7781",
        survey_date="2026-07-01T00:00:00Z",
        datum="NGVD29",
        raw_lowest_floor_elevation_ft=8.94,
        raw_lowest_adjacent_grade_ft=8.90,
    )
    validated = review_certificate(certificate["id"], decision="VALIDATED")
    assert validated["status"] == "VALIDATED"
    settled_version = validated["version"]

    for payload in (
        {"decision": "REJECTED", "rejection_reason": "SURVEY_STALE"},
        {"decision": "VALIDATED"},
    ):
        validate_error(
            api_client.review_elevation_certificate(
                certificate["id"], payload, headers=make_reviewer_headers()
            ),
            ApiErrorId.ERR_INVALID_CERTIFICATE_STATE.value,
            409,
        )

    replayed = validate_success(
        api_client.get_elevation_certificate(
            certificate["id"], headers=make_analyst_headers()
        )
    )
    assert replayed["status"] == "VALIDATED"
    assert replayed["rejection_reason"] is None
    assert replayed["reviewed_by_user_id"] == REVIEWER_USER_ID
    assert replayed["version"] == settled_version

    unchanged = validate_success(
        api_client.get_structure(structure["id"], headers=make_analyst_headers())
    )
    assert unchanged["lowest_floor_elevation_ft"] == 7.8
    assert unchanged["lowest_adjacent_grade_ft"] == 7.8
    assert unchanged["elevation_source_certificate_id"] == certificate["id"]
