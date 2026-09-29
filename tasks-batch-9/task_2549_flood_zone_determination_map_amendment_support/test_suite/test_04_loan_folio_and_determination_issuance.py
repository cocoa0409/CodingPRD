"""Loan folios and the determination itself.

A folio is the life-of-loan record a lender opens per loan; a determination is
the answer to "is this building in the flood hazard area?".  The checks here pin
what the server mints on a fresh folio, the coherence and geometry gates in front
of an issuance, the optimistic-concurrency token that guards it, and the exact
zero boundary where the geocoder's buffer straddles the SFHA line.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_determination,
    assert_loan_folio,
    correct_geocode,
    create_community,
    create_determination_payload,
    create_elevation_certificate_payload,
    create_lender,
    create_loan_folio_payload,
    create_property,
    create_structure,
    make_analyst_headers,
    make_lender_headers,
    publish_panel,
    read_folio,
    set_clock,
)

CLOCK = "2026-08-01T00:00:00Z"
CLOCK_STAMP = "2026-08-01T00:00:00.000Z"
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
ABSENT_UUID = "99999999-9999-4999-8999-999999999999"


def test_unknown_determination_id_returns_the_determination_not_found_error():
    """A syntactically valid but unknown path id yields the entity's own 404
    error_id, not a generic one and not a request-shape failure.

    PRD §2.5: "Fifth (5) every identifier in the URL path must resolve, validated left to right so that the leftmost unresolvable segment decides which not-found error is returned."
    PRD §5: "| `ERR_DETERMINATION_NOT_FOUND` | 404 |"
    PRD §5: "| `ERR_DISPUTE_NOT_FOUND` | 404 |"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/corner_determination_detail_unknown_id_returns_not_found
    """
    set_clock(CLOCK)

    response = api_client.get_determination(UNKNOWN_UUID, headers=make_analyst_headers())
    error = validate_error(response, ApiErrorId.ERR_DETERMINATION_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]
    # The error envelope carries the diagnosis only, never a partial entity.
    assert set(error) == {"error_id", "message"}

    # The same unknown id against a different collection names that collection.
    validate_error(
        api_client.get_dispute(UNKNOWN_UUID, headers=make_analyst_headers()),
        ApiErrorId.ERR_DISPUTE_NOT_FOUND.value,
        404,
    )


def test_every_detail_read_owns_a_distinct_not_found_error():
    """One unknown UUID probed against all eleven collections produces eleven
    different error_id values, while the list reads answer with an empty page.

    PRD §2.5: "Fifth (5) every identifier in the URL path must resolve, validated left to right so that the leftmost unresolvable segment decides which not-found error is returned."
    PRD §2.5: "Sixth (6) every foreign key supplied in the request body must resolve, validated in the order the fields are declared for that operation; both existence checks report the not-found error of the entity that failed to resolve, at HTTP 404."
    PRD §2.3: "Filters combine conjunctively, and a filter value that matches nothing yields an empty `data` array with `total_count` of 0 rather than an error."
    PRD §2.4: "All eleven entity types in this system — communities, lenders, map panels, properties, structures, loan folios, determinations, disputes, elevation certificates, map amendment requests and compliance notices — carry the full set, so no entity in this API is missing `updated_at` or `version`."

    Design: Corner/errors/corner_unknown_id_on_every_detail_read_returns_its_own_not_found_error
    """
    set_clock(CLOCK)
    headers = make_analyst_headers()

    detail_reads = (
        (api_client.get_community, ApiErrorId.ERR_COMMUNITY_NOT_FOUND),
        (api_client.get_lender, ApiErrorId.ERR_LENDER_NOT_FOUND),
        (api_client.get_map_panel, ApiErrorId.ERR_MAP_PANEL_NOT_FOUND),
        (api_client.get_property, ApiErrorId.ERR_PROPERTY_NOT_FOUND),
        (api_client.get_structure, ApiErrorId.ERR_STRUCTURE_NOT_FOUND),
        (api_client.get_loan_folio, ApiErrorId.ERR_LOAN_FOLIO_NOT_FOUND),
        (api_client.get_determination, ApiErrorId.ERR_DETERMINATION_NOT_FOUND),
        (api_client.get_dispute, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
        (api_client.get_elevation_certificate, ApiErrorId.ERR_ELEVATION_CERTIFICATE_NOT_FOUND),
        (api_client.get_map_amendment_request, ApiErrorId.ERR_MAP_AMENDMENT_REQUEST_NOT_FOUND),
        (api_client.get_compliance_notice, ApiErrorId.ERR_COMPLIANCE_NOTICE_NOT_FOUND),
    )
    seen = []
    for read, expected in detail_reads:
        error = validate_error(read(ABSENT_UUID, headers=headers), expected.value, 404)
        assert isinstance(error["message"], str) and error["message"]
        seen.append(error["error_id"])
    assert len(set(seen)) == 11, f"the eleven not-found errors must be distinct: {seen}"

    # An unknown filter value is an empty result set, never a 404.
    filtered_reads = (
        (api_client.list_lenders, None),
        (api_client.list_map_panels, {"community_id": ABSENT_UUID}),
        (api_client.list_loan_folios, {"lender_id": ABSENT_UUID}),
        (api_client.list_disputes, {"determination_id": ABSENT_UUID}),
        (api_client.list_elevation_certificates, {"structure_id": ABSENT_UUID}),
        (api_client.list_map_amendment_requests, {"determination_id": ABSENT_UUID}),
        (api_client.list_compliance_notices, {"loan_folio_id": ABSENT_UUID}),
    )
    for read, params in filtered_reads:
        rows, meta = validate_paginated(read(headers=headers, params=params))
        assert rows == []
        assert meta["total_count"] == 0

    # A body foreign key reports the owner of the key that failed to resolve.
    validate_error(
        api_client.create_structure(
            {
                "property_id": ABSENT_UUID,
                "structure_label": "Main dwelling",
                "occupancy_type": "SINGLE_FAMILY",
                "foundation_type": "SLAB",
                "replacement_cost_cents": 32000000,
                "sfha_offset_ft": -12.0,
            },
            headers=headers,
        ),
        ApiErrorId.ERR_PROPERTY_NOT_FOUND.value,
        404,
    )
    community = create_community()
    prop = create_property(community["id"])
    validate_error(
        api_client.create_loan_folio(
            {
                "lender_id": ABSENT_UUID,
                "property_id": prop["id"],
                "loan_number": "LN-4401",
                "borrower_user_id": "borrower-a",
                "principal_balance_cents": 28000000,
                "policy_anniversary_date": "2027-03-15T00:00:00Z",
            },
            headers=make_lender_headers(ABSENT_UUID),
        ),
        ApiErrorId.ERR_LENDER_NOT_FOUND.value,
        404,
    )

    # Path resolution precedes the projection's own state gate.
    validate_error(
        api_client.get_impact_analysis(ABSENT_UUID, headers=headers),
        ApiErrorId.ERR_MAP_PANEL_NOT_FOUND.value,
        404,
    )


def test_loan_folio_system_fields_are_minted_by_the_server():
    """A newly opened folio snapshots its escrow, takes both initial statuses and
    starts every derived counter at zero.

    PRD §3.5: "At creation the folio's `monitoring_status` is `ACTIVE` and its `insurance_status` is `NONE`; `initial_escrow_balance_cents` is snapshotted from `escrow_balance_cents` to anchor the conservation invariant of Section 2.10; `current_determination_id`, `required_coverage_cents`, `reported_coverage_cents`, `uninsured_exposure_cents`, `force_placed_premium_cents`, `force_placed_coverage_days`, `cumulative_earned_premium_cents`, `open_notice_count` and `pending_redetermination_count` all start empty or at zero, with `force_placed_at` null; `compliance_posture` is `COMPLIANT`, because with no determination yet the required coverage is zero; and the community's `active_folio_count` is re-counted."
    PRD §2.4: "`version` starts at 1 when the row is created and increases by exactly 1 on every mutation of that row; `updated_at` is refreshed to the current logical instant on every mutation."

    Design: Corner/entities/corner_loan_folio_system_fields_minted_by_server
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    prop = create_property(community["id"])

    folio = validate_success(
        api_client.create_loan_folio(
            {
                "lender_id": lender["id"],
                "property_id": prop["id"],
                "loan_number": "LN-4401",
                "borrower_user_id": "borrower-a",
                "principal_balance_cents": 28000000,
                "policy_anniversary_date": "2027-03-15T00:00:00Z",
                "escrow_balance_cents": 500000,
            },
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )
    assert_loan_folio(folio)

    assert folio["escrow_balance_cents"] == 500000
    assert folio["initial_escrow_balance_cents"] == 500000
    assert folio["monitoring_status"] == "ACTIVE"
    assert folio["insurance_status"] == "NONE"

    assert folio["current_determination_id"] is None
    assert folio["required_coverage_cents"] == 0
    assert folio["reported_coverage_cents"] == 0
    assert folio["uninsured_exposure_cents"] == 0
    assert folio["force_placed_premium_cents"] == 0
    assert folio["force_placed_coverage_days"] == 0
    assert folio["cumulative_earned_premium_cents"] == 0
    assert folio["open_notice_count"] == 0
    assert folio["pending_redetermination_count"] == 0
    assert folio["force_placed_at"] is None
    assert folio["compliance_posture"] == "COMPLIANT"

    assert folio["version"] == 1
    assert folio["created_at"] == CLOCK_STAMP
    assert folio["updated_at"] == CLOCK_STAMP

    parent = validate_success(
        api_client.get_community(community["id"], headers=make_analyst_headers())
    )
    assert parent["active_folio_count"] == 1


def test_determination_structure_must_belong_to_the_folios_property():
    """Both ids exist and both are individually valid, so the refusal comes purely
    from the coherence check between them.

    PRD §3.5: "The named structure must sit on the property the folio names, or the request is rejected with `ERR_STRUCTURE_FOLIO_MISMATCH` (HTTP 422)."
    PRD §2.5: "Sixteenth (16) a referenced elevation certificate must be validated, reporting `ERR_CERTIFICATE_NOT_VALIDATED`; seventeenth (17) supplied identifiers must be mutually coherent, reporting `ERR_STRUCTURE_FOLIO_MISMATCH`; eighteenth (18) the amendment type must match the structure's fill history, reporting `ERR_AMENDMENT_TYPE_MISMATCH`; nineteenth (19) the property must be geocoded, reporting `ERR_PROPERTY_NOT_GEOCODED`; twentieth (20) an effective panel must exist for the property, reporting `ERR_NO_EFFECTIVE_PANEL`."
    PRD §3.5: "The winning panel is recorded on the determination as `map_panel_id`, and the same selection rule runs when an elevation certificate is filed and on each re-determination inside a monitoring sweep."
    PRD §2.3: "Filters combine conjunctively, and a filter value that matches nothing yields an empty `data` array with `total_count` of 0 rather than an error."

    Design: Corner/validations/corner_determination_structure_must_belong_to_folio_property
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    panel = publish_panel(community["id"])

    property_a = create_property(community["id"])
    structure_a = create_structure(property_a["id"])
    folio_a = validate_success(
        api_client.create_loan_folio(
            create_loan_folio_payload(lender["id"], property_a["id"]),
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )

    property_b = create_property(
        community["id"],
        street_address="27 Bayfront Rd",
        latitude=25.7640,
        longitude=-80.1950,
        geocode_confidence_score=0.96,
    )
    structure_b = create_structure(
        property_b["id"],
        structure_label="Guest house",
        foundation_type="CRAWLSPACE",
        replacement_cost_cents=21000000,
    )

    validate_error(
        api_client.create_determination(
            create_determination_payload(
                folio_a["id"], structure_b["id"], folio_a["version"]
            ),
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_STRUCTURE_FOLIO_MISMATCH.value,
        422,
    )

    # Nothing was written, so the concurrency token captured earlier is still good.
    held = read_folio(folio_a["id"])
    assert held["current_determination_id"] is None
    assert held["version"] == folio_a["version"]

    determination = validate_success(
        api_client.create_determination(
            create_determination_payload(
                folio_a["id"], structure_a["id"], folio_a["version"]
            ),
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert_determination(determination)
    assert determination["structure_id"] == structure_a["id"]
    assert determination["map_panel_id"] == panel["id"]

    rows, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"structure_id": structure_b["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_determination_refused_while_the_property_is_unresolved():
    """A rooftop hit below the 0.60 confidence floor is still UNRESOLVED, and an
    unresolved parcel cannot carry a determination until it is corrected.

    PRD §3.4: "`geocode_status` is `GEOCODED` when, and only when, `geocode_method` is anything other than `FAILED` **and** `geocode_confidence_score` is at or above the confidence floor of 0.60; in every other case it is `UNRESOLVED`."
    PRD §3.4: "An unresolved property is unusable for the two operations that need to know where the building is: issuing a determination against it and filing an elevation certificate for one of its structures are both rejected with `ERR_PROPERTY_NOT_GEOCODED` (HTTP 422)."
    PRD §3.4: "`geocode_buffer_ft` is the positional buffer implied by the method: 0 feet for a `ROOFTOP` hit, 25 feet for a `PARCEL_CENTROID` hit, 250 feet for a `ZIP_CENTROID` hit, and 0 feet for a `FAILED` geocode."
    PRD §3.4: "In the first hop those four values replace the stored ones, `geocode_status` and `geocode_buffer_ft` are recomputed from them, and `geocode_corrected_count` is incremented by 1 to record how many accepted corrections this property has had."

    Design: Corner/validations/corner_determination_rejected_when_property_unresolved
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    publish_panel(community["id"])
    prop = create_property(
        community["id"],
        street_address="88 Marsh Ln",
        latitude=25.7500,
        longitude=-80.2000,
        geocode_method="ROOFTOP",
        geocode_confidence_score=0.40,
    )
    # The buffer follows the method; the status follows the confidence floor.
    assert prop["geocode_status"] == "UNRESOLVED"
    assert prop["geocode_buffer_ft"] == 0

    structure = create_structure(prop["id"])
    folio = validate_success(
        api_client.create_loan_folio(
            create_loan_folio_payload(lender["id"], prop["id"], loan_number="LN-4499"),
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )

    payload = create_determination_payload(folio["id"], structure["id"], folio["version"])
    validate_error(
        api_client.create_determination(payload, headers=make_analyst_headers()),
        ApiErrorId.ERR_PROPERTY_NOT_GEOCODED.value,
        422,
    )
    held = read_folio(folio["id"])
    assert held["current_determination_id"] is None
    assert held["version"] == folio["version"]
    _, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"loan_folio_id": folio["id"]}
        )
    )
    assert meta["total_count"] == 0

    # The floor is non-strict, so exactly 0.60 resolves the parcel.
    corrected = correct_geocode(
        prop["id"], geocode_method="ROOFTOP", geocode_confidence_score=0.60
    )
    assert corrected["geocode_status"] == "GEOCODED"
    assert corrected["geocode_corrected_count"] == 1

    determination = validate_success(
        api_client.create_determination(payload, headers=make_analyst_headers()), 201
    )
    assert determination["loan_folio_id"] == folio["id"]


def test_determination_refused_when_no_panel_is_yet_in_force():
    """The only panel for the parcel is EFFECTIVE but future-dated, so the panel
    selector's candidate set is empty: existence is not the same as being in force.

    PRD §3.5: "It considers only map panels whose `revision_status` is `EFFECTIVE`, whose community matches the property's community, whose `map_panel_number` matches the property's, and whose `effective_date` is at or before the current logical instant; panels in `PRELIMINARY`, `APPEAL_OPEN`, `LFD_ISSUED` or `SUPERSEDED` never qualify."
    PRD §3.5: "If no panel qualifies, the operation fails with `ERR_NO_EFFECTIVE_PANEL` (HTTP 422)."
    PRD §3.5: "The winning panel is recorded on the determination as `map_panel_id`, and the same selection rule runs when an elevation certificate is filed and on each re-determination inside a monitoring sweep."

    Design: Corner/validations/corner_determination_rejected_when_no_panel_is_yet_effective
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    panel = publish_panel(community["id"], effective_date="2027-01-01T00:00:00Z")
    # Published as a first sequence, so it is in force as a row but not yet in time.
    assert panel["revision_status"] == "EFFECTIVE"

    prop = create_property(community["id"])
    assert prop["geocode_status"] == "GEOCODED"
    structure = create_structure(prop["id"])
    folio = validate_success(
        api_client.create_loan_folio(
            create_loan_folio_payload(lender["id"], prop["id"]),
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )

    payload = create_determination_payload(folio["id"], structure["id"], folio["version"])
    validate_error(
        api_client.create_determination(payload, headers=make_analyst_headers()),
        ApiErrorId.ERR_NO_EFFECTIVE_PANEL.value,
        422,
    )
    # A certificate needs a panel base flood elevation to convert against, so the
    # same selector refuses it for the same reason.
    validate_error(
        api_client.create_elevation_certificate(
            create_elevation_certificate_payload(structure["id"]),
            headers=make_analyst_headers("analyst-2"),
        ),
        ApiErrorId.ERR_NO_EFFECTIVE_PANEL.value,
        422,
    )

    # The comparison is non-strict: the panel qualifies on its own effective_date.
    set_clock("2027-01-01T00:00:00Z")
    determination = validate_success(
        api_client.create_determination(payload, headers=make_analyst_headers()), 201
    )
    assert determination["map_panel_id"] == panel["id"]


def test_second_origination_is_refused_but_a_life_of_loan_review_is_not():
    """The once-per-folio ceiling is keyed on ``determination_type``: a second
    ORIGINATION is refused while a review determination on the same folio and
    structure supersedes the first.

    PRD §3.5: "A second `ORIGINATION` determination on a folio that already has a `current_determination_id` is rejected with `ERR_ORIGINATION_ALREADY_COMPLETE` (HTTP 409) — origination happens once per folio."
    PRD §3.5: "Any prior determination for the same folio and structure that was in `ISSUED` or `FLAGGED_FOR_REVIEW` is moved to `SUPERSEDED` with its `superseded_at` set to the current logical instant, and the new row names it in `supersedes_determination_id`; on the flagged path the retired row keeps the `flagged_reason` it was carrying and the folio's `pending_redetermination_count` is decremented, while on the plain issued path there is no flagged reason to carry."
    PRD §3.5: "An `INSIDE` classification takes the panel's `zone_code` as the determination's `zone_code` and sets `sfha_flag` true."

    Design: Corner/validations/corner_second_origination_determination_rejected
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    publish_panel(community["id"])
    prop = create_property(community["id"])
    structure = create_structure(prop["id"])
    folio = validate_success(
        api_client.create_loan_folio(
            create_loan_folio_payload(lender["id"], prop["id"]),
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )
    first = validate_success(
        api_client.create_determination(
            create_determination_payload(folio["id"], structure["id"], folio["version"]),
            headers=make_analyst_headers(),
        ),
        201,
    )
    current_version = read_folio(folio["id"])["version"]

    # The version supplied is current, so this is not a concurrency failure.
    validate_error(
        api_client.create_determination(
            create_determination_payload(folio["id"], structure["id"], current_version),
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_ORIGINATION_ALREADY_COMPLETE.value,
        409,
    )
    held = read_folio(folio["id"])
    assert held["current_determination_id"] == first["id"]
    assert validate_success(
        api_client.get_determination(first["id"], headers=make_analyst_headers())
    )["status"] == "ISSUED"

    second = validate_success(
        api_client.create_determination(
            create_determination_payload(
                folio["id"], structure["id"], current_version,
                determination_type="LIFE_OF_LOAN_REVIEW",
            ),
            headers=make_analyst_headers(),
        ),
        201,
    )
    assert second["determination_type"] == "LIFE_OF_LOAN_REVIEW"
    assert second["supersedes_determination_id"] == first["id"]

    retired = validate_success(
        api_client.get_determination(first["id"], headers=make_analyst_headers())
    )
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_at"] == CLOCK_STAMP
    assert read_folio(folio["id"])["current_determination_id"] == second["id"]

    # An unambiguous inside read reproduces the same answer either way.
    assert second["zone_code"] == first["zone_code"] == "AE"
    assert second["sfha_flag"] is True and first["sfha_flag"] is True


def test_stale_folio_version_is_rejected_and_the_version_advances_per_write():
    """The concurrency token is stale by exactly one after the origination write,
    which is the smallest detectable amount, and every accepted write moves it on.

    PRD §2.6: "The determination-issuing operation therefore requires `expected_loan_folio_version` as a mandatory, non-optional field of its request body, carrying the `version` of the target loan folio as the client last observed it."
    PRD §2.6: "If that value does not equal the folio's current `version`, the request is rejected with `ERR_STALE_LOAN_FOLIO_VERSION` at HTTP 412 and nothing is written."
    PRD §2.6: "Because a successful issuance increments the folio's `version` by 1, replaying the same request body a second time necessarily fails this check."
    PRD §2.5: "Fourth (4) the request shape must be valid: no unknown body or query fields, all required fields present, every enumeration value within its declared range, integers non-negative where declared non-negative, decimals within their declared scale, `limit` within 1 through 100 and `offset` zero or greater — reported as `ERR_INVALID_REQUEST`."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_folio_version_is_rejected_and_the_version_advances_per_write
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    publish_panel(community["id"])
    prop = create_property(community["id"])
    structure = create_structure(prop["id"])
    folio = validate_success(
        api_client.create_loan_folio(
            create_loan_folio_payload(lender["id"], prop["id"]),
            headers=make_lender_headers(lender["id"]),
        ),
        201,
    )
    version_0 = folio["version"]
    first = validate_success(
        api_client.create_determination(
            create_determination_payload(folio["id"], structure["id"], version_0),
            headers=make_analyst_headers(),
        ),
        201,
    )

    review_at_v0 = create_determination_payload(
        folio["id"], structure["id"], version_0,
        determination_type="LIFE_OF_LOAN_REVIEW",
    )
    validate_error(
        api_client.create_determination(review_at_v0, headers=make_analyst_headers()),
        ApiErrorId.ERR_STALE_LOAN_FOLIO_VERSION.value,
        412,
    )

    after_first = read_folio(folio["id"])
    version_1 = after_first["version"]
    assert version_1 == version_0 + 1
    assert after_first["current_determination_id"] == first["id"]
    _, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"loan_folio_id": folio["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected write left no trace"

    review_at_v1 = create_determination_payload(
        folio["id"], structure["id"], version_1,
        determination_type="LIFE_OF_LOAN_REVIEW",
    )
    second = validate_success(
        api_client.create_determination(review_at_v1, headers=make_analyst_headers()), 201
    )
    assert second["supersedes_determination_id"] == first["id"]
    assert validate_success(
        api_client.get_determination(first["id"], headers=make_analyst_headers())
    )["status"] == "SUPERSEDED"

    version_2 = read_folio(folio["id"])["version"]
    assert version_2 == version_1 + 1

    # The guard is on the token, not on the payload: the byte-identical replay fails.
    validate_error(
        api_client.create_determination(review_at_v1, headers=make_analyst_headers()),
        ApiErrorId.ERR_STALE_LOAN_FOLIO_VERSION.value,
        412,
    )

    # Omitting the token is a shape failure, not a blind write.
    blind = {
        "loan_folio_id": folio["id"],
        "structure_id": structure["id"],
        "determination_type": "LIFE_OF_LOAN_REVIEW",
    }
    validate_error(
        api_client.create_determination(blind, headers=make_analyst_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )


def test_buffered_offset_landing_exactly_on_zero_is_indeterminate_on_both_sides():
    """Four buildings on one buffered parcel straddle the hazard boundary: a tenth
    of a foot inside is INSIDE, a tenth outside is OUTSIDE, and both exact-zero
    cases fall to INDETERMINATE, which origination resolves conservatively.

    PRD §3.5: "The applicable buffer in feet is the sum of the property's method-derived positional buffer — 0 for `ROOFTOP`, 25 for `PARCEL_CENTROID`, 250 for `ZIP_CENTROID`, 0 for `FAILED` — and the governing panel's `horizontal_uncertainty_ft`."
    PRD §3.5: "The structure's `position_class` is then `INSIDE` when the effective offset plus the buffer is strictly less than zero; otherwise `OUTSIDE` when the effective offset minus the buffer is strictly greater than zero; and otherwise `INDETERMINATE`, which is the case where the buffer straddles the boundary."
    PRD §3.5: "Both comparisons are exact decimal comparisons against zero and both are strict, so an effective offset whose buffered value lands exactly on zero yields `INDETERMINATE` rather than a definite side."
    PRD §3.5: "Under the strict variant — used for every `ORIGINATION` determination, for every `DISPUTE_REVISION` determination, and for every prospective evaluation performed by the preliminary-map projection of Section 3.3 — an `INDETERMINATE` result resolves conservatively to the panel's `zone_code` with `sfha_flag` true, so that whenever the buffer straddles the boundary the lender is told insurance is mandatory."
    PRD §3.5: "An `OUTSIDE` classification sets `zone_code` to `X` and `sfha_flag` false — `X` is a determination-only zone value that no panel ever carries, so the determination's `zone_code` ranges over `A`, `AE`, `AO`, `AH`, `VE` and `X`."
    PRD §3.6: "`required_coverage_cents` is then the smallest of three integer amounts: the folio's `principal_balance_cents`, the structure's `replacement_cost_cents`, and that cap."
    PRD §3.5: "A folio whose `insurance_status` is `NONE` moves `NONE → NOT_REQUIRED` when the incoming current determination has `mandatory_purchase_flag` false; that transition sets `required_coverage_cents` to 0, sets `uninsured_exposure_cents` to 0, and recomputes `compliance_posture` to `COMPLIANT`."

    Design: Difficulty/boundary_precision_check/geocode_buffer_two_sided_exact_zero_boundary
    """
    set_clock(CLOCK)
    community = create_community()
    lender = create_lender()
    publish_panel(
        community["id"], sfha_boundary_shift_ft=0.0, horizontal_uncertainty_ft=0.0
    )
    prop = create_property(
        community["id"],
        street_address="402 Marsh Lane",
        latitude=25.7700,
        longitude=-80.2000,
        geocode_method="PARCEL_CENTROID",
        geocode_confidence_score=0.72,
    )
    # 25 feet of positional buffer plus 0 feet of cartographic uncertainty.
    assert prop["geocode_status"] == "GEOCODED"
    assert prop["geocode_buffer_ft"] == 25

    offsets = (-25.1, -25.0, 25.0, 25.1)
    results = {}
    for index, offset in enumerate(offsets, start=1):
        structure = create_structure(
            prop["id"],
            structure_label=f"Unit {index} (offset {offset})",
            replacement_cost_cents=30000000,
            sfha_offset_ft=offset,
        )
        folio = validate_success(
            api_client.create_loan_folio(
                create_loan_folio_payload(
                    lender["id"], prop["id"],
                    loan_number=f"LN-B{index}",
                    borrower_user_id=f"borrower-b{index}",
                    principal_balance_cents=20000000,
                ),
                headers=make_lender_headers(lender["id"]),
            ),
            201,
        )
        determination = validate_success(
            api_client.create_determination(
                create_determination_payload(folio["id"], structure["id"], folio["version"]),
                headers=make_analyst_headers(),
            ),
            201,
        )
        assert_determination(determination)
        results[offset] = (determination, read_folio(folio["id"]))

    # -25.1 + 25 == -0.1, strictly below zero.
    inside, inside_folio = results[-25.1]
    assert inside["position_class"] == "INSIDE"
    assert inside["zone_code"] == "AE"
    assert inside["sfha_flag"] is True
    assert inside["base_flood_elevation_ft"] == 7.75

    # -25.0 + 25 == 0.0 and 25.0 - 25 == 0.0: neither strict comparison is met.
    for offset in (-25.0, 25.0):
        straddling, _ = results[offset]
        assert straddling["position_class"] == "INDETERMINATE", offset
        # Origination is the strict variant, so ambiguity resolves to the panel.
        assert straddling["zone_code"] == "AE", offset
        assert straddling["sfha_flag"] is True, offset
        assert straddling["base_flood_elevation_ft"] == 7.75, offset

    # 25.1 - 25 == 0.1, strictly above zero.
    outside, outside_folio = results[25.1]
    assert outside["position_class"] == "OUTSIDE"
    assert outside["zone_code"] == "X"
    assert outside["sfha_flag"] is False
    assert outside["base_flood_elevation_ft"] is None

    # min(20,000,000 principal, 30,000,000 replacement, 25,000,000 cap).
    assert inside_folio["required_coverage_cents"] == 20000000
    assert inside_folio["insurance_status"] == "NONE"
    for offset in (-25.0, 25.0):
        _, folio = results[offset]
        assert folio["required_coverage_cents"] == 20000000, offset
        assert folio["insurance_status"] == "NONE", offset
    assert outside_folio["required_coverage_cents"] == 0
    assert outside_folio["insurance_status"] == "NOT_REQUIRED"
