"""Geocoding parcels and cataloguing the buildings on them.

The positional evidence recorded here is what every later determination stands
on, so these checks pin the derived geocode fields, the shape rules that guard
them, the reverse-reachable structure listing, and the two-hop cascade a
corrected geocode fires.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_property,
    assert_structure,
    correct_geocode,
    create_community,
    create_property,
    create_structure,
    make_analyst_headers,
    make_borrower_headers,
    make_lender_headers,
    read_folio,
    run_monitoring,
    set_clock,
    setup_base_chain,
)

CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_property_geocode_fields_computed_from_method_and_score():
    """``geocode_status`` and ``geocode_buffer_ft`` are derived from the method
    and the confidence score, and the two derivations are independent.

    PRD §3.4: "`geocode_status` is `GEOCODED` when, and only when, `geocode_method` is anything other than `FAILED` **and** `geocode_confidence_score` is at or above the confidence floor of 0.60; in every other case it is `UNRESOLVED`."
    PRD §3.4: "`geocode_buffer_ft` is the positional buffer implied by the method: 0 feet for a `ROOFTOP` hit, 25 feet for a `PARCEL_CENTROID` hit, 250 feet for a `ZIP_CENTROID` hit, and 0 feet for a `FAILED` geocode."
    PRD §3.4: "`structure_count` starts at 0 and is thereafter a re-count of the structures on this property."

    Design: Corner/entities/corner_property_geocode_fields_computed_from_method_and_score
    """
    set_clock(CLOCK)
    community = create_community()

    below_floor = validate_success(
        api_client.create_property(
            {
                "community_id": community["id"],
                "street_address": "77 Inland Ave",
                "city": "Miami",
                "postal_code": "33101",
                "map_panel_number": "12086C0312K",
                "latitude": 25.800000,
                "longitude": -80.300000,
                "geocode_method": "ZIP_CENTROID",
                "geocode_confidence_score": 0.55,
            },
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert_property(below_floor)
    assert below_floor["geocode_buffer_ft"] == 250
    assert below_floor["geocode_status"] == "UNRESOLVED", "0.55 is below the 0.60 floor"
    assert below_floor["geocode_corrected_count"] == 0
    assert below_floor["structure_count"] == 0

    at_floor = validate_success(
        api_client.create_property(
            {
                "community_id": community["id"],
                "street_address": "78 Inland Ave",
                "city": "Miami",
                "postal_code": "33101",
                "map_panel_number": "12086C0312K",
                "latitude": 25.800100,
                "longitude": -80.300100,
                "geocode_method": "ZIP_CENTROID",
                "geocode_confidence_score": 0.60,
            },
            headers=make_analyst_headers(),
        ),
        201,
    )
    # Exactly at the floor is GEOCODED, and the buffer is unchanged: the two
    # computed fields do not depend on each other.
    assert at_floor["geocode_status"] == "GEOCODED"
    assert at_floor["geocode_buffer_ft"] == 250


def test_property_invalid_geocode_method_enum_rejected():
    """An out-of-range enum value and an out-of-range decimal both fail the same
    shape check, and neither payload is persisted.

    PRD §3.4: "`geocode_method` must be one of `ROOFTOP`, `PARCEL_CENTROID`, `ZIP_CENTROID` or `FAILED`."
    PRD §2.5: "Fourth (4) the request shape must be valid: no unknown body or query fields, all required fields present, every enumeration value within its declared range, integers non-negative where declared non-negative, decimals within their declared scale, `limit` within 1 through 100 and `offset` zero or greater — reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_property_invalid_geocode_method_enum_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    base = {
        "community_id": community["id"],
        "street_address": "11 Bayfront Rd",
        "city": "Miami",
        "postal_code": "33101",
        "map_panel_number": "12086C0312K",
        "latitude": 25.761700,
        "longitude": -80.191800,
        "geocode_method": "ROOFTOP",
        "geocode_confidence_score": 0.95,
    }

    validate_error(
        api_client.create_property(
            dict(base, geocode_method="STREET_INTERPOLATED"), headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_property(
            dict(base, geocode_confidence_score=1.40), headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api_client.list_properties(
            headers=make_analyst_headers(), params={"community_id": community["id"]}
        )
    )
    assert meta["total_count"] == 0, "neither rejected payload may be persisted"


def test_out_of_range_confidence_score_is_invalid_request():
    """An out-of-domain confidence score is a 400 shape failure, while an
    in-range but sub-floor score is accepted and only refused later, at
    determination time, as a business failure.

    PRD §3.4: "A `ProviderAnalyst` registers a parcel by supplying the owning `community_id`, the situs `street_address`, `city` and `postal_code`, the `map_panel_number` of the FIRM sheet the parcel falls on — which is what later joins the parcel to a map panel within its community — and the geocoder's output: `latitude` and `longitude` each carried to 6 decimal places, a `geocode_method` naming the positional method the geocoder actually resolved, and a `geocode_confidence_score` carried to 2 decimal places which must be between 0.00 and 1.00 inclusive."
    PRD §3.4: "An unresolved property is unusable for the two operations that need to know where the building is: issuing a determination against it and filing an elevation certificate for one of its structures are both rejected with `ERR_PROPERTY_NOT_GEOCODED` (HTTP 422)."

    Design: Corner/errors/corner_out_of_range_confidence_score_is_invalid_request
    """
    set_clock(CLOCK)
    community = create_community()
    base = {
        "community_id": community["id"],
        "street_address": "11 Bayfront Rd",
        "city": "Miami",
        "postal_code": "33101",
        "map_panel_number": "12086C0312K",
        "latitude": 25.761700,
        "longitude": -80.191800,
        "geocode_method": "ROOFTOP",
    }

    validate_error(
        api_client.create_property(
            dict(base, geocode_confidence_score=1.50), headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_property(
            dict(base, geocode_confidence_score=-0.10), headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_property(
            dict(base, geocode_method="DWELLING", geocode_confidence_score=0.95),
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    accepted = validate_success(
        api_client.create_property(
            dict(base, geocode_confidence_score=0.95), headers=make_analyst_headers()
        ),
        201,
    )
    assert accepted["geocode_status"] == "GEOCODED"
    assert accepted["geocode_buffer_ft"] == 0

    # In range but below the floor: accepted at 201, refused only downstream.
    sub_floor = validate_success(
        api_client.create_property(
            dict(base, street_address="12 Bayfront Rd", geocode_confidence_score=0.40),
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert sub_floor["geocode_status"] == "UNRESOLVED"


def test_properties_list_pagination_envelope():
    """Three parcels read two at a time pin ``total_count``, ``has_more`` and the
    page window independently of the filter.

    PRD §2.3: "`limit` controls page size; it defaults to 10, must be at least 1, and may not exceed 100."
    PRD §2.3: "`offset` controls the starting position; it defaults to 0 and must be zero or greater."
    PRD §2.3: "Collections are always returned sorted by `created_at` ascending, and the `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/corner_properties_list_pagination_envelope
    """
    set_clock(CLOCK)
    community = create_community()
    first = create_property(community["id"], street_address="1 Bayfront Rd")
    second = create_property(
        community["id"], street_address="2 Bayfront Rd", latitude=25.761800
    )
    third = create_property(
        community["id"], street_address="3 Bayfront Rd", latitude=25.761900
    )

    borrower_headers = make_borrower_headers("borrower-a")
    page1, meta1 = validate_paginated(
        api_client.list_properties(
            headers=borrower_headers,
            params={"community_id": community["id"], "limit": 2, "offset": 0},
        )
    )
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = validate_paginated(
        api_client.list_properties(
            headers=borrower_headers,
            params={"community_id": community["id"], "limit": 2, "offset": 2},
        )
    )
    assert meta2["limit"] == 2
    assert meta2["offset"] == 2
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1

    seen = [row["id"] for row in page1] + [row["id"] for row in page2]
    assert len(set(seen)) == 3, "no row may repeat across pages"
    assert set(seen) == {first["id"], second["id"], third["id"]}
    # created_at ascending across the two windows.
    assert seen == [first["id"], second["id"], third["id"]]

    unpaged, meta3 = validate_paginated(
        api_client.list_properties(headers=borrower_headers)
    )
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0
    assert meta3["total_count"] == 3
    assert meta3["has_more"] is False
    assert len(unpaged) == 3


def test_structure_create_missing_required_field_rejected():
    """Omitting ``replacement_cost_cents`` — a required input with no default —
    is a shape failure ahead of any foreign-key or business check, and it leaves
    the parent's derived count untouched.

    PRD §3.4: "Each structure carries a `structure_label` distinguishing it from its siblings on the same parcel (`PRINCIPAL_RESIDENCE` is the typical value), an `occupancy_type` that must be one of `SINGLE_FAMILY`, `TWO_TO_FOUR_FAMILY`, `OTHER_RESIDENTIAL` or `NON_RESIDENTIAL` and which selects the building coverage cap, a `foundation_type` that must be one of `SLAB`, `CRAWLSPACE`, `BASEMENT` or `PIER_PILE` as recorded on the elevation certificate, a `replacement_cost_cents` figure that must be strictly greater than zero, and `sfha_offset_ft` — the signed horizontal distance in feet from the SFHA boundary as digitised on the community's first-sequence FIRM, where a negative value places the building inside the hazard area, a positive value places it outside, and zero puts it exactly on the boundary."
    PRD §2.5: "Fourth (4) the request shape must be valid: no unknown body or query fields, all required fields present, every enumeration value within its declared range, integers non-negative where declared non-negative, decimals within their declared scale, `limit` within 1 through 100 and `offset` zero or greater — reported as `ERR_INVALID_REQUEST`."
    PRD §3.4: "Adding a structure re-counts the parent property's `structure_count`."

    Design: Corner/entities/corner_structure_create_missing_required_field_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    prop = create_property(community["id"])

    validate_error(
        api_client.create_structure(
            {
                "property_id": prop["id"],
                "structure_label": "Main dwelling",
                "occupancy_type": "SINGLE_FAMILY",
                "foundation_type": "SLAB",
                "sfha_offset_ft": -12.0,
            },
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    # An unknown extra field fails the same rung.
    validate_error(
        api_client.create_structure(
            {
                "property_id": prop["id"],
                "structure_label": "Main dwelling",
                "occupancy_type": "SINGLE_FAMILY",
                "foundation_type": "SLAB",
                "replacement_cost_cents": 32_000_000,
                "sfha_offset_ft": -12.0,
                "elevation_certificate_note": "not a declared field",
            },
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api_client.list_structures(
            headers=make_analyst_headers(), params={"property_id": prop["id"]}
        )
    )
    assert meta["total_count"] == 0
    reread = validate_success(
        api_client.get_property(prop["id"], headers=make_analyst_headers())
    )
    assert reread["structure_count"] == 0


def test_structure_unknown_property_fk_returns_not_found():
    """A body foreign key that does not resolve is the referenced entity's own
    404, and the shape check still runs first.

    PRD §2.8: "Each entity type has its own not-found error, returned at HTTP 404 whenever an identifier — whether it arrived in the path or as a foreign key in the request body — names no such row."
    PRD §2.8: "An unresolvable community identifier reports `ERR_COMMUNITY_NOT_FOUND`; a lender identifier reports `ERR_LENDER_NOT_FOUND`; a map panel identifier, including a `supersedes_panel_id` that names nothing, reports `ERR_MAP_PANEL_NOT_FOUND`; a property identifier reports `ERR_PROPERTY_NOT_FOUND`; a structure identifier reports `ERR_STRUCTURE_NOT_FOUND`; a loan folio identifier reports `ERR_LOAN_FOLIO_NOT_FOUND`; a determination identifier reports `ERR_DETERMINATION_NOT_FOUND`; a dispute identifier reports `ERR_DISPUTE_NOT_FOUND`; an elevation certificate identifier reports `ERR_ELEVATION_CERTIFICATE_NOT_FOUND`; a map amendment request identifier reports `ERR_MAP_AMENDMENT_REQUEST_NOT_FOUND`; and a compliance notice identifier reports `ERR_COMPLIANCE_NOTICE_NOT_FOUND`."
    PRD §2.5: "Sixth (6) every foreign key supplied in the request body must resolve, validated in the order the fields are declared for that operation; both existence checks report the not-found error of the entity that failed to resolve, at HTTP 404."

    Design: Corner/entities/corner_structure_unknown_property_fk_returns_not_found
    """
    set_clock(CLOCK)
    create_community()
    payload = {
        "property_id": UNKNOWN_UUID,
        "structure_label": "Main dwelling",
        "occupancy_type": "SINGLE_FAMILY",
        "foundation_type": "SLAB",
        "replacement_cost_cents": 32_000_000,
        "sfha_offset_ft": -12.0,
    }

    validate_error(
        api_client.create_structure(payload, headers=make_analyst_headers()),
        ApiErrorId.ERR_PROPERTY_NOT_FOUND.value,
        404,
    )
    # Priority 4 precedes priority 6: a bad enum alongside the bad FK wins.
    validate_error(
        api_client.create_structure(
            dict(payload, occupancy_type="MIXED_USE"), headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api_client.list_structures(headers=make_analyst_headers())
    )
    assert meta["total_count"] == 0


def test_structures_filtered_list_reverse_lookup_by_property():
    """The ``property_id`` filter partitions two parcels' structures exactly, and
    combining it with an occupancy filter narrows conjunctively.

    PRD §2.3: "Filters combine conjunctively, and a filter value that matches nothing yields an empty `data` array with `total_count` of 0 rather than an error."
    PRD §2.3: "The specific filter names available on each collection are the foreign keys and status enumerations of the underlying entity, namely `state_code` and `participation_status` on communities; `community_id`, `supersedes_panel_id`, `map_panel_number` and `revision_status` on map panels; `community_id`, `map_panel_number` and `geocode_status` on properties; `property_id`, `elevation_source_certificate_id` and `occupancy_type` on structures; `lender_id`, `property_id`, `current_determination_id`, `compliance_posture` and `insurance_status` on loan folios; `loan_folio_id`, `structure_id`, `map_panel_id`, `supersedes_determination_id`, `status` and `determination_type` on determinations; `determination_id`, `revised_determination_id`, `status` and `basis` on disputes; `structure_id`, `dispute_id`, `reference_panel_id` and `status` on elevation certificates; `determination_id`, `elevation_certificate_id`, `status` and `request_type` on map amendment requests; and `loan_folio_id`, `determination_id`, `notice_type` and `status` on compliance notices."
    PRD §3.4: "Adding a structure re-counts the parent property's `structure_count`."

    Design: Corner/entities/corner_structures_filtered_list_reverse_lookup_by_property
    """
    set_clock(CLOCK)
    community = create_community()
    prop_a = create_property(community["id"], street_address="11 Bayfront Rd")
    prop_b = create_property(
        community["id"], street_address="12 Bayfront Rd", latitude=25.762000
    )
    a_main = create_structure(prop_a["id"], structure_label="A main")
    a_garage = create_structure(
        prop_a["id"],
        structure_label="A detached garage",
        occupancy_type="NON_RESIDENTIAL",
        replacement_cost_cents=4_000_000,
    )
    b_main = create_structure(
        prop_b["id"],
        structure_label="B main",
        foundation_type="CRAWLSPACE",
        replacement_cost_cents=28_000_000,
        sfha_offset_ft=40.0,
    )
    assert_structure(b_main)

    lender_headers = make_lender_headers("lender-not-a-real-row")
    a_rows, a_meta = validate_paginated(
        api_client.list_structures(
            headers=lender_headers, params={"property_id": prop_a["id"]}
        )
    )
    assert a_meta["total_count"] == 2
    assert a_meta["has_more"] is False
    assert {row["id"] for row in a_rows} == {a_main["id"], a_garage["id"]}

    b_rows, b_meta = validate_paginated(
        api_client.list_structures(
            headers=lender_headers,
            params={"property_id": prop_b["id"], "occupancy_type": "SINGLE_FAMILY"},
        )
    )
    assert b_meta["total_count"] == 1
    assert b_rows[0]["id"] == b_main["id"]

    # The derived counts agree with the filtered lists.
    assert validate_success(
        api_client.get_property(prop_a["id"], headers=lender_headers)
    )["structure_count"] == 2
    assert validate_success(
        api_client.get_property(prop_b["id"], headers=lender_headers)
    )["structure_count"] == 1

    _all_rows, all_meta = validate_paginated(
        api_client.list_structures(headers=lender_headers)
    )
    assert all_meta["total_count"] == 3, "the filter narrows; the list is not pre-scoped"


def test_geocode_correction_flags_issued_determination():
    """Correcting a parcel's geocode replaces the four positional inputs and then
    flags every determination issued against its structures, with
    ``flagged_reason`` GEOCODE_CORRECTION and the governing panel untouched.

    PRD §3.4: "The correction supplies a fresh `latitude`, `longitude`, `geocode_method` and `geocode_confidence_score`, all four required."
    PRD §3.4: "In the first hop those four values replace the stored ones, `geocode_status` and `geocode_buffer_ft` are recomputed from them, and `geocode_corrected_count` is incremented by 1 to record how many accepted corrections this property has had."
    PRD §3.4: "In the second hop, because the parcel has effectively moved, every determination in `status` `ISSUED` that was issued against a structure of this property moves `ISSUED → FLAGGED_FOR_REVIEW` with `flagged_reason` set to `GEOCODE_CORRECTION`, and each affected folio re-counts `pending_redetermination_count` and recomputes `compliance_posture`."
    PRD §3.6: "Third, if `pending_redetermination_count` is greater than zero the posture is `REVIEW_PENDING`."
    PRD §3.7: "When the re-classification reproduces both the flagged determination's `zone_code` and its `sfha_flag`, nothing of substance has changed and the determination returns `FLAGGED_FOR_REVIEW → ISSUED`: `flagged_reason` is cleared to null, `map_panel_id` is repointed at the panel the re-selection chose, the folio's `pending_redetermination_count` is decremented and its `compliance_posture` recomputed."

    Design: Corner/state_machines/corner_geocode_correction_flags_issued_determination
    """
    chain = setup_base_chain(
        clock=CLOCK,
        property_overrides={
            "latitude": 25.760000,
            "longitude": -80.190000,
            "geocode_method": "ZIP_CENTROID",
            "geocode_confidence_score": 0.80,
        },
        structure_overrides={"sfha_offset_ft": -500.0},
    )
    determination = chain["determination"]
    assert determination["status"] == "ISSUED"
    assert determination["zone_code"] == "AE"
    assert determination["sfha_flag"] is True

    corrected = correct_geocode(
        chain["property"]["id"],
        latitude=25.761700,
        longitude=-80.191800,
        geocode_method="ROOFTOP",
        geocode_confidence_score=0.97,
    )
    # Hop 1.
    assert corrected["geocode_method"] == "ROOFTOP"
    assert corrected["geocode_confidence_score"] == 0.97
    assert corrected["geocode_buffer_ft"] == 0
    assert corrected["geocode_status"] == "GEOCODED"
    assert corrected["geocode_corrected_count"] == 1
    assert corrected["latitude"] == 25.761700

    # Hop 2.
    flagged = validate_success(
        api_client.get_determination(determination["id"], headers=make_analyst_headers())
    )
    assert flagged["status"] == "FLAGGED_FOR_REVIEW"
    assert flagged["flagged_reason"] == "GEOCODE_CORRECTION"
    folio = read_folio(chain["folio"]["id"])
    assert folio["pending_redetermination_count"] == 1
    assert folio["compliance_posture"] == "REVIEW_PENDING"

    # The correction cascade never touches panels, and flagging is not a re-read.
    assert flagged["map_panel_id"] == chain["panel"]["id"]
    panel = validate_success(
        api_client.get_map_panel(chain["panel"]["id"], headers=make_analyst_headers())
    )
    assert panel["revision_status"] == "EFFECTIVE"
    assert flagged["zone_code"] == "AE"
    assert flagged["sfha_flag"] is True

    # The lenient re-read reproduces (AE, true), so the sweep clears the flag.
    counters = run_monitoring()
    assert counters["determinations_scanned"] == 1
    assert counters["redeterminations_cleared"] == 1
    assert counters["redeterminations_issued"] == 0
    cleared = validate_success(
        api_client.get_determination(determination["id"], headers=make_analyst_headers())
    )
    assert cleared["status"] == "ISSUED"
    assert cleared["flagged_reason"] is None
