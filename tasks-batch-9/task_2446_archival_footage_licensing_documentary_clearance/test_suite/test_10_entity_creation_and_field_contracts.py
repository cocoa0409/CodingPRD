"""Entity creation, field contracts and graph-topology guards.

Every test in this module drives the Archival Clearance API through its own
endpoints only, using the helpers in `test_helpers`.
"""

from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    NON_EXISTENT_UUID,
    PRODUCTION_ADMIN,
    RATE_CARD_DEFAULTS,
    TEST_DEFAULTS,
    add_source_candidate,
    assert_asset_dimensions,
    assert_license,
    assert_negotiation_round,
    assert_production,
    assert_production_counters,
    assert_rate_card,
    assert_success_envelope_meta,
    create_archive,
    create_archive_with_rate_card,
    create_asset,
    create_asset_with_selected_source,
    create_asset_payload,
    create_eo_application_payload,
    create_license,
    create_license_payload,
    create_production_in_clearance,
    create_production_payload,
    create_rate_card_payload,
    create_source_candidate_payload,
    get_asset,
    get_license,
    get_production,
    pin_chart,
    post_licensor_round,
    post_producer_round,
    select_source_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Module-private setup chains ─────────────────────────────────────────────


def _setup_footage_licence_inputs(api):
    """A production in CLEARANCE, an ACTIVE archive on the standard card, and a
    45-second footage asset whose AVAILABLE candidate at that archive is SELECTED."""
    production = create_production_in_clearance(api)
    archive, card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Quarry blast")
    return production, archive, card, asset, candidate


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_production_creation_stamps_declared_system_fields(api):
    """A bare production comes back 201 with every system field at its declared value.

    PRD §3.1: "A new production is born in `DEVELOPMENT` with `posture` reading
    `OPEN`, with `asset_count`, `cleared_asset_count`, `open_asset_count`,
    `committed_fee_cents` and `sweep_epoch` all at zero, and with `version` at 1."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/production_creation_stamps_system_fields_and_declared_defaults
    """
    response = api.create_production(
        create_production_payload(title="Salt Flats",
                                  delivery_deadline_date="2027-06-30"),
        PRODUCTION_ADMIN)
    created = validate_success(response, 201)
    assert_success_envelope_meta(response)
    assert response.json()["response_type"] == "object"

    assert_production(created)
    assert created["status"] == "DEVELOPMENT"
    assert created["posture"] == "OPEN"
    assert created["asset_count"] == 0
    assert created["cleared_asset_count"] == 0
    assert created["open_asset_count"] == 0
    assert created["committed_fee_cents"] == 0
    assert created["sweep_epoch"] == 0
    assert created["version"] == 1

    reread = get_production(api, created["id"])
    assert reread["status"] == "DEVELOPMENT"
    assert reread["posture"] == "OPEN"
    assert_production_counters(reread, asset_count=0, cleared_asset_count=0,
                               open_asset_count=0)
    assert reread["committed_fee_cents"] == 0
    assert reread["sweep_epoch"] == 0
    assert reread["version"] == 1


def test_asset_creation_without_usage_purpose_is_rejected(api):
    """Omitting the required `usage_purpose` is a malformed body, not a silent default.

    PRD §3.1: "Each asset declares its `asset_type`, either `ARCHIVAL_FOOTAGE` or
    `MUSIC`; its `title` as the shot or cue title will appear on the cue sheet; its
    cut points `timecode_in_seconds` and `timecode_out_seconds` in whole seconds, the
    in-point being zero or greater and the out-point strictly greater than the
    in-point; and its `usage_purpose`, either `CRITICAL_COMMENTARY` or
    `ILLUSTRATIVE_BACKGROUND`, which later selects the fair-use weighting variant."
    PRD §2.12 rung 7: "The body is well formed: required fields present, enum values
    inside their declared domain, integers non-negative, ISO dates parseable,
    `timecode_out_seconds` strictly greater than `timecode_in_seconds`, and
    `term_months` at least 1 — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/asset_creation_missing_required_usage_purpose_rejected
    """
    production = create_production_in_clearance(api)
    version_before = get_production(api, production["id"])["version"]

    payload = create_asset_payload(asset_type="ARCHIVAL_FOOTAGE",
                                   title="Untitled roll",
                                   timecode_in_seconds=0,
                                   timecode_out_seconds=45)
    payload.pop("usage_purpose")
    response = api.create_asset(production["id"], payload, ARCHIVE_RESEARCHER)
    validate_error(response, "ERR_INVALID_REQUEST")
    assert response.json()["response_type"] == "error"

    rows, meta = validate_paginated(
        api.list_assets(PRODUCTION_ADMIN, params={"production_id": production["id"]}))
    assert rows == []
    assert meta["total_count"] == 0

    after = get_production(api, production["id"])
    assert_production_counters(after, asset_count=0, cleared_asset_count=0,
                               open_asset_count=0)
    assert after["version"] == version_before


def test_asset_creation_with_non_increasing_timecodes_is_rejected(api):
    """Neither equal nor inverted timecodes may produce an asset.

    PRD §2.12 rung 7: "The body is well formed: required fields present, enum values
    inside their declared domain, integers non-negative, ISO dates parseable,
    `timecode_out_seconds` strictly greater than `timecode_in_seconds`, and
    `term_months` at least 1 — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/asset_inverted_timecodes_rejected_as_invalid_request
    """
    production = create_production_in_clearance(api)

    equal_timecodes = api.create_asset(
        production["id"],
        create_asset_payload(asset_type="ARCHIVAL_FOOTAGE", title="Zero length",
                             timecode_in_seconds=120, timecode_out_seconds=120,
                             usage_purpose="CRITICAL_COMMENTARY"),
        ARCHIVE_RESEARCHER)
    validate_error(equal_timecodes, "ERR_INVALID_REQUEST")

    inverted_timecodes = api.create_asset(
        production["id"],
        create_asset_payload(asset_type="MUSIC", title="Backwards cue",
                             timecode_in_seconds=200, timecode_out_seconds=100,
                             usage_purpose="ILLUSTRATIVE_BACKGROUND"),
        ARCHIVE_RESEARCHER)
    validate_error(inverted_timecodes, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(
        api.list_assets(PRODUCTION_ADMIN, params={"production_id": production["id"]}))
    assert rows == []
    assert meta["total_count"] == 0

    after = get_production(api, production["id"])
    assert_production_counters(after, asset_count=0, cleared_asset_count=0,
                               open_asset_count=0)


def test_rate_card_materialises_every_declared_multiplier_default(api):
    """A card published with only its four mandatory fields carries all declared defaults.

    PRD §3.2: "Everything else is optional and falls back to a declared default: the
    duration tiers are bounded by `tier1_max_seconds`, defaulting to 30 seconds, and
    `tier2_max_seconds`, defaulting to 120 seconds, with `tier2_rate_multiplier`
    defaulting to 1.25 and `tier3_rate_multiplier` defaulting to 1.60. The media
    multipliers are `media_multiplier_theatrical` at 1.40,
    `media_multiplier_broadcast` at 1.15, `media_multiplier_streaming` at 1.30 and
    `media_multiplier_all_media` at 1.75. The territory multipliers are
    `territory_multiplier_world` at 1.50 and `territory_multiplier_domestic` at 1.00.
    The term uplift `term_multiplier_per_year` defaults to 0.20 and is additive per
    licence year beyond the first. The window multipliers are
    `festival_window_multiplier` at 0.35 and `all_media_window_multiplier` at 1.00."
    PRD §2.5: "`archive_id` on a rate card ... [is] taken from the URL."

    Design: Corner/entities/rate_card_defaults_applied_when_every_multiplier_is_omitted
    """
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")

    response = api.create_rate_card(
        archive["id"],
        create_rate_card_payload(base_rate_per_30s_cents=60000,
                                 minimum_fee_cents=150000,
                                 festival_minimum_fee_cents=40000,
                                 effective_from_date="2026-01-01"),
        ARCHIVE_RESEARCHER)
    card = validate_success(response, 201)
    assert_rate_card(card)

    assert card["tier1_max_seconds"] == 30
    assert card["tier2_max_seconds"] == 120
    for field, expected in RATE_CARD_DEFAULTS.items():
        assert float(card[field]) == float(expected), (
            f"RateCard.{field} must default to {expected}, got {card[field]!r}")

    assert card["status"] == "ACTIVE"
    assert card["archive_id"] == archive["id"]
    assert card["base_rate_per_30s_cents"] == 60000
    assert card["minimum_fee_cents"] == 150000
    assert card["festival_minimum_fee_cents"] == 40000
    assert card["effective_from_date"] == "2026-01-01"
    assert card["version"] == 1

    rows, _meta = validate_paginated(
        api.list_archive_rate_cards(archive["id"], ARCHIVE_RESEARCHER))
    assert [row["id"] for row in rows] == [card["id"]]
    assert rows[0]["status"] == "ACTIVE"


def test_license_money_fields_are_resolved_server_side_at_creation(api):
    """A licence body names no money field: the card, the units and the fee are computed.

    PRD §3.3: "That resolved card's id is stamped onto the licence as `rate_card_id`,
    which is a computed field and never a client input."
    PRD §3.3: "The server stamps `billable_units` as the asset's `duration_seconds`
    divided by 30 and rounded *up* to a whole number, so a shot of any length between
    1 and 30 seconds bills as one unit and a 45-second shot bills as two. It then runs
    the rate-card pricing described below and stamps the result onto
    `rate_card_fee_cents`, initialises `current_proposed_fee_cents` to that same
    rate-card figure so that the standing proposal before any negotiation is the list
    price, sets `round_count` to zero, sets `mfn_topup_cents` and
    `mfn_benchmark_fee_cents` to zero, and leaves `executed_fee_cents` and
    `termination_reason` null."
    PRD §3.3: "Under `ALL_MEDIA_WINDOW` the window multiplier of 1.00 yields 362250
    cents, which clears the all-media floor of 150000."

    Design: Corner/entities/license_computed_money_fields_ignore_any_client_supplied_input
    """
    production, archive, card, asset, _candidate = _setup_footage_licence_inputs(api)

    response = api.create_license(
        create_license_payload(production["id"], asset["id"], archive["id"],
                               rights_leg="FOOTAGE", media="BROADCAST",
                               territory="WORLD", window_class="ALL_MEDIA_WINDOW",
                               term_months=36, term_start_date="2026-08-15",
                               term_end_date="2029-08-15"),
        CLEARANCE_SUPERVISOR)
    license_row = validate_success(response, 201)
    assert_license(license_row)

    assert license_row["rate_card_id"] == card["id"]
    assert license_row["billable_units"] == 2
    assert license_row["rate_card_fee_cents"] == TEST_DEFAULTS["all_media_window_fee_cents"]
    assert license_row["rate_card_fee_cents"] == 362250
    assert license_row["current_proposed_fee_cents"] == 362250
    assert license_row["executed_fee_cents"] is None
    assert license_row["termination_reason"] is None
    assert license_row["mfn_topup_cents"] == 0
    assert license_row["mfn_benchmark_fee_cents"] == 0
    assert license_row["mfn_requested"] is False
    assert license_row["round_count"] == 0
    assert license_row["status"] == "DRAFT"
    assert license_row["version"] == 1

    reread = get_license(api, license_row["id"])
    assert reread["rate_card_id"] == card["id"]
    assert reread["billable_units"] == 2
    assert reread["rate_card_fee_cents"] == 362250
    assert reread["executed_fee_cents"] is None

    assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION")
    assert get_production(api, production["id"])["committed_fee_cents"] == 0


def test_negotiation_rounds_are_append_only_without_version_or_updated_at(api):
    """The negotiation history exposes only id and created_at plus its own columns.

    PRD §2.4: "`NegotiationRound` is the single exception. A negotiation round is an
    append-only historical record that is never edited after it lands, so a round
    carries only `id` and `created_at`: it has **no** `updated_at` field and **no**
    `version` field."
    PRD §2.4: "What a round does carry is a copy of the parent's state at the moment
    it landed — `license_status_after` records the licence's `status` immediately
    after the round was applied, and `license_version_after` records the licence's
    `version` immediately after the round was applied."
    PRD §2.3: "the negotiation history of a licence is returned by `round_number`
    ascending, which replays the deal in the order it happened."

    Design: Corner/entities/negotiation_round_is_immutable_and_carries_no_version_field
    """
    production, archive, _card, asset, _candidate = _setup_footage_licence_inputs(api)
    license_row = create_license(api, production["id"], asset["id"], archive["id"])
    assert license_row["version"] == 1

    post_licensor_round(api, license_row["id"], archive["id"], 362250)
    post_producer_round(api, license_row["id"], 300000)

    response = api.list_negotiation_rounds(license_row["id"], PRODUCTION_ADMIN)
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 2

    for row in rows:
        assert_negotiation_round(row)
        assert "version" not in row
        assert "updated_at" not in row

    assert rows[0]["round_number"] == 1
    assert rows[0]["party"] == "LICENSOR"
    assert rows[0]["proposed_fee_cents"] == 362250
    assert rows[0]["license_status_after"] == "QUOTED"
    assert rows[0]["license_version_after"] == 2

    assert rows[1]["round_number"] == 2
    assert rows[1]["party"] == "PRODUCER"
    assert rows[1]["proposed_fee_cents"] == 300000
    assert rows[1]["license_status_after"] == "COUNTERED"
    assert rows[1]["license_version_after"] == 3

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "COUNTERED"
    assert reread["round_count"] == 2
    assert reread["current_proposed_fee_cents"] == 300000
    assert reread["version"] == 3


def test_unknown_ids_answer_with_the_entity_specific_not_found_code(api):
    """Each missing row answers with its own 404 identifier, addressed or referenced.

    PRD §2.5: "Each entity has its own not-found code:
    `ERR_PRODUCTION_NOT_FOUND`, `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §3.2: "The request names a single `source_candidate_id`; a candidate id that
    does not exist, or that belongs to some other asset, is answered with
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`."

    Design: Corner/entities/license_get_with_unknown_uuid_returns_not_found
    """
    production = create_production_in_clearance(api)
    archive = create_archive(api)
    asset = create_asset(api, production["id"], title="Orphan shot")
    # A real AVAILABLE candidate exists, so only the unknown candidate id is at fault.
    add_source_candidate(api, asset["id"], archive["id"])
    asset_version_before = get_asset(api, asset["id"])["version"]

    validate_error(api.get_license(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_LICENSE_NOT_FOUND")
    validate_error(api.get_asset(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_ASSET_NOT_FOUND")
    validate_error(
        api.select_source(asset["id"], select_source_payload(NON_EXISTENT_UUID),
                          ARCHIVE_RESEARCHER),
        "ERR_SOURCE_CANDIDATE_NOT_FOUND")

    after = get_asset(api, asset["id"])
    assert after["selected_source_candidate_id"] is None
    assert after["version"] == asset_version_before


def test_asset_listing_filters_then_pages_with_total_count_and_has_more(api):
    """An additive filter narrows the set that total_count and has_more are read over.

    PRD §2.3: "When a list is returned, the `meta` block carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the window is
    applied) and `has_more` (true when rows remain beyond the current window)."
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0; there is no upper bound on
    `offset`."
    PRD §2.3: "The asset collection accepts `production_id`,
    `selected_source_candidate_id`, `asset_type`, `licensing_status`,
    `depiction_status` and `rights_basis`."

    Design: Corner/entities/asset_listing_filters_and_paginates_with_total_count_and_has_more
    """
    production = create_production_in_clearance(api)
    first = create_asset(api, production["id"], title="Shot one")
    second = create_asset(api, production["id"], title="Shot two")
    third = create_asset(api, production["id"], title="Shot three")
    music = create_asset(api, production["id"], asset_type="MUSIC",
                         title="Title cue", timecode_in_seconds=0,
                         timecode_out_seconds=60,
                         usage_purpose="ILLUSTRATIVE_BACKGROUND")

    page_one_rows, page_one_meta = validate_paginated(api.list_assets(
        PRODUCTION_ADMIN,
        params={"production_id": production["id"], "asset_type": "ARCHIVAL_FOOTAGE",
                "limit": 2, "offset": 0}))
    assert [row["id"] for row in page_one_rows] == [first["id"], second["id"]]
    assert page_one_meta["limit"] == 2
    assert page_one_meta["offset"] == 0
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True

    page_two_rows, page_two_meta = validate_paginated(api.list_assets(
        PRODUCTION_ADMIN,
        params={"production_id": production["id"], "asset_type": "ARCHIVAL_FOOTAGE",
                "limit": 2, "offset": 2}))
    assert [row["id"] for row in page_two_rows] == [third["id"]]
    assert page_two_meta["limit"] == 2
    assert page_two_meta["offset"] == 2
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False

    filtered_ids = [row["id"] for row in page_one_rows + page_two_rows]
    assert music["id"] not in filtered_ids

    all_rows, all_meta = validate_paginated(api.list_assets(
        PRODUCTION_ADMIN, params={"production_id": production["id"]}))
    assert len(all_rows) == 4
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["total_count"] == 4
    assert all_meta["has_more"] is False
    assert [row["id"] for row in all_rows] == [
        first["id"], second["id"], third["id"], music["id"]]

    assert get_production(api, production["id"])["asset_count"] == 4


def test_source_candidate_under_unknown_parent_asset_is_not_found(api):
    """The nested parent is resolved before the body, and no orphan row is written.

    PRD §2.12 rung 5: "Every resource named by a path parameter exists — otherwise
    the entity's own not-found code. Applies to every operation with an `{id}` in its
    path."
    PRD §2.5: "Path parameters are resolved left to right, and the leftmost missing
    resource decides the error."

    Design: Corner/entities/source_candidate_under_nonexistent_parent_asset_returns_not_found
    """
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")

    response = api.create_source_candidate(
        NON_EXISTENT_UUID,
        create_source_candidate_payload(archive["id"], availability_status="AVAILABLE"),
        ARCHIVE_RESEARCHER)
    validate_error(response, "ERR_ASSET_NOT_FOUND")

    rows, meta = validate_paginated(
        api.list_archive_source_candidates(archive["id"], ARCHIVE_RESEARCHER))
    assert rows == []
    assert meta["total_count"] == 0


def test_license_creation_rejects_an_asset_of_another_production(api):
    """A cross-wired production/asset pair is a 422, not a 404 and not a licence.

    PRD §3.3: "Then the archive must be `ACTIVE` (`ERR_ARCHIVE_SUSPENDED`), the asset
    must belong to the named production (`ERR_ASSET_PRODUCTION_MISMATCH`), and the
    archive must have exactly one rate card in `ACTIVE` whose `effective_from_date`
    falls on or before the licence's `term_start_date` (`ERR_NO_ACTIVE_RATE_CARD`)."
    PRD §2.12 rung 17: "The referenced asset belongs to the referenced production,
    and a referenced clearance chart belongs to the production being addressed —
    otherwise `ERR_ASSET_PRODUCTION_MISMATCH`. Applies to licence creation and
    subject-release creation."

    Design: Corner/entities/license_rejects_an_asset_belonging_to_another_production
    """
    production_a = create_production_in_clearance(api, title="Film A")
    production_b = create_production_in_clearance(
        api, title="Film B", delivery_deadline_date="2027-07-31")
    archive, _card = create_archive_with_rate_card(api)
    asset_b, _candidate_b = create_asset_with_selected_source(
        api, production_b["id"], archive["id"], title="B roll")

    response = api.create_license(
        create_license_payload(production_a["id"], asset_b["id"], archive["id"],
                               rights_leg="FOOTAGE", media="BROADCAST",
                               territory="WORLD", window_class="ALL_MEDIA_WINDOW",
                               term_months=36, term_start_date="2026-08-15",
                               term_end_date="2029-08-15"),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_ASSET_PRODUCTION_MISMATCH")

    by_production, by_production_meta = validate_paginated(api.list_licenses(
        CLEARANCE_SUPERVISOR, params={"production_id": production_a["id"]}))
    assert by_production == []
    assert by_production_meta["total_count"] == 0

    by_asset, by_asset_meta = validate_paginated(api.list_licenses(
        CLEARANCE_SUPERVISOR, params={"asset_id": asset_b["id"]}))
    assert by_asset == []
    assert by_asset_meta["total_count"] == 0

    assert_asset_dimensions(get_asset(api, asset_b["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")


def test_eo_application_rejects_a_chart_of_another_production(api):
    """The chart/production mis-wire outranks the coverage-limit check on the same body.

    PRD §3.7: "The chart must belong to the addressed production, failing which the
    request is refused with `ERR_CHART_PRODUCTION_MISMATCH` (HTTP 422)."
    PRD §2.12 rung 19: "The referenced clearance chart belongs to the production of
    the E&O application or delivery package — otherwise
    `ERR_CHART_PRODUCTION_MISMATCH`. Applies to E&O application creation and
    delivery-package creation."
    PRD §2.12 rung 43: "`coverage_limit_cents` is at least 100000 and
    `retention_cents` is strictly less than `coverage_limit_cents` — otherwise
    `ERR_COVERAGE_LIMIT_INVALID`. Applies to E&O application creation."

    Design: Corner/entities/eo_application_rejects_a_chart_pinned_on_another_production
    """
    production_a = create_production_in_clearance(api, title="Film A")
    production_b = create_production_in_clearance(
        api, title="Film B", delivery_deadline_date="2027-07-31")
    chart_b = pin_chart(api, production_b["id"], chart_label="B v1")
    assert chart_b["status"] == "PINNED"

    response = api.create_eo_application(
        production_a["id"],
        create_eo_application_payload(chart_b["id"], coverage_limit_cents=50000,
                                      retention_cents=100000),
        PRODUCTION_ADMIN)
    validate_error(response, "ERR_CHART_PRODUCTION_MISMATCH")

    rows, meta = validate_paginated(api.list_eo_applications(
        PRODUCTION_ADMIN, params={"production_id": production_a["id"]}))
    assert rows == []
    assert meta["total_count"] == 0

    reread_chart = validate_success(
        api.get_clearance_chart(chart_b["id"], CLEARANCE_SUPERVISOR))
    assert reread_chart["status"] == "PINNED"
    assert reread_chart["production_id"] == production_b["id"]
