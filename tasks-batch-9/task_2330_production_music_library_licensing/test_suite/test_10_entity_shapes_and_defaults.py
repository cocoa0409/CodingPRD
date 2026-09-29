"""Entity shapes: declared defaults, server-owned fields and reference resolution.

Every row in this catalogue arrives with a documented default vector, a set of
derived figures the client may never write, and exactly one not-found error for
each reference that fails to resolve. The tests here read those shapes straight
off the create and read endpoints of an empty database.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    Work,
    accept_sync_request,
    assert_cents_equal,
    assert_common_fields,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_status,
    assert_thin_record_fields,
    assert_three_fraction_timestamp,
    issue_per_use_license,
    new_active_agreement,
    new_active_blanket,
    new_composer,
    new_draft_agreement,
    new_licensee,
    new_tier,
    open_usage_report,
    quote_sync_request,
    review_sync_request,
    submit_sync_request,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_BLANKET_AGREEMENT_NOT_FOUND,
    ERR_COMPOSER_AGREEMENT_NOT_FOUND,
    ERR_COMPOSER_NOT_FOUND,
    ERR_COMPOSITION_NOT_FOUND,
    ERR_CUE_SHEET_PARENT_INVALID,
    ERR_LICENSE_TIER_NOT_FOUND,
    ERR_SEARCH_PROFILE_NOT_FOUND,
    ERR_VALIDATION,
)

# An identifier that matches no row of any entity.
MISSING_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _composer_and_draft_agreement(api):
    """A composer and the DRAFT agreement that will govern its works.

    Ingesting a work does not require the governing agreement to be ACTIVE;
    only cataloguing it does.
    """
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_draft_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    return composer, agreement


def _cataloged_harbour_lights(api):
    """A composer with an ACTIVE agreement and one CATALOGED work under it."""
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Harbour Lights",
                duration_sec=180,
                tempo_bpm=130,
                genre="CINEMATIC",
                mood_tags=["EPIC", "DARK"],
                instrumentation=["STRINGS", "BRASS"],
            ),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    return composer, agreement, composition


def _three_works_two_cataloged(api):
    """Works A, B and C ingested in that order; A and B are then catalogued."""
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    ingested = []
    for title, tempo, genre, moods, instruments in (
        ("Harbour Lights", 130, "CINEMATIC", ["EPIC"], ["STRINGS"]),
        ("Slate Horizon", 118, "CINEMATIC", ["HOPEFUL"], ["PIANO"]),
        ("Night Ferry", 92, "JAZZ", ["CALM"], ["PIANO"]),
    ):
        ingested.append(
            assert_created(
                api.create_composition(
                    build.composition_payload(
                        composer["id"],
                        agreement["id"],
                        title=title,
                        tempo_bpm=tempo,
                        genre=genre,
                        mood_tags=moods,
                        instrumentation=instruments,
                    ),
                    CATALOG_ADMIN,
                )
            )
        )
    for composition in ingested[:2]:
        assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    return composer, ingested


def _sync_request_ground(api):
    """A CATALOGED work, a FILM tier open at every scale, and a buyer with credit."""
    composer, agreement, composition = _cataloged_harbour_lights(api)
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api, legal_name="Northwind Pictures", licensee_type="PRODUCTION_COMPANY"
    )
    return {
        "composer": composer,
        "agreement": agreement,
        "composition": composition,
        "tier": tier,
        "licensee": licensee,
    }


def _minimal_sync_request_payload(ground):
    """Only the fields a sync request cannot default: no optional flag supplied."""
    return {
        "composition_id": ground["composition"]["id"],
        "licensee_id": ground["licensee"]["id"],
        "tier_id": ground["tier"]["id"],
        "media_type": "FILM",
        "distribution_scale": "NATIONAL",
        "requested_term_start": "2026-09-01T00:00:00Z",
        "requested_term_months": 24,
    }


def _blanket_reporting_ground(api):
    """Two catalogued works, an ACTIVE monthly blanket and its DUE report."""
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(
        api, composer["id"], sync_fee_share_pct=40.00, blanket_opt_in=True
    )
    works = []
    for title, tempo, instruments in (
        ("Harbour Lights", 130, ["STRINGS"]),
        ("Slate Horizon", 118, ["PIANO"]),
    ):
        created = assert_created(
            api.create_composition(
                build.composition_payload(
                    composer["id"],
                    agreement["id"],
                    title=title,
                    tempo_bpm=tempo,
                    instrumentation=instruments,
                ),
                CATALOG_ADMIN,
            )
        )
        works.append(assert_ok(api.catalog_composition(created["id"], None, CATALOG_ADMIN)))
    licensee = new_licensee(
        api, legal_name="Meridian Broadcasting", licensee_type="BROADCASTER"
    )
    blanket = new_active_blanket(api, licensee)
    open_usage_report(api, blanket)
    return {
        "composer": composer,
        "agreement": agreement,
        "work_a": works[0],
        "work_b": works[1],
        "licensee": licensee,
        "blanket": blanket,
    }


def _issued_license_on_work_a(api, ground):
    """Carry work A through the per-use conversation to an ISSUED licence."""
    work = Work(ground["composer"], ground["agreement"], ground["work_a"])
    deal = Deal(work, new_tier(api), ground["licensee"])
    submit_sync_request(api, deal)
    review_sync_request(api, deal)
    quote_sync_request(api, deal)
    accept_sync_request(api, deal)
    issue_per_use_license(api, deal)
    return deal.license


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


class TestComposerCreationDefaults:
    def test_optional_attributes_default_to_none_us_and_thirty_percent(self, api):
        """PRD §3.1: "Either a `CatalogAdmin` or a `RightsManager` creates one with a
        `display_name` — the credit name that will appear on cue sheets — and three
        optional attributes: `pro_affiliation`, naming the performing-rights society the
        composer is registered with, one of `ASCAP`, `BMI`, `SESAC`, `PRS` or `NONE` and
        defaulting to `NONE`; `payee_country`, an ISO-3166 alpha-2 code used for the
        withholding audit trail and defaulting to `US`; and `tax_withholding_pct`, the
        withholding rate applied to post-recoupment statement amounts, expressed as a
        fraction between 0.00 and 0.50 with exactly two decimals and defaulting to 0.30."

        Design: Corner/entities/composer_creation_applies_declared_defaults_and_system_fields
        """
        composer = assert_created(
            api.create_composer({"display_name": "Nadia Okoro"}, CATALOG_ADMIN)
        )

        assert composer["display_name"] == "Nadia Okoro"
        assert composer["pro_affiliation"] == "NONE"
        assert composer["payee_country"] == "US"
        assert composer["tax_withholding_pct"] == pytest.approx(0.30, abs=0.01)

    def test_freshly_created_composer_has_an_empty_money_picture(self, api, clock_origin):
        """PRD §3.1: "A freshly created composer has `accrued_unpaid_cents`,
        `outstanding_advance_cents` and `lifetime_paid_cents` all at 0,
        `latest_statement_period_end` null, and `version` 1."

        Design: Corner/entities/composer_creation_applies_declared_defaults_and_system_fields
        """
        composer = assert_created(
            api.create_composer({"display_name": "Nadia Okoro"}, CATALOG_ADMIN)
        )

        assert_cents_equal(composer["accrued_unpaid_cents"], 0, "accrued_unpaid_cents")
        assert_cents_equal(
            composer["outstanding_advance_cents"], 0, "outstanding_advance_cents"
        )
        assert_cents_equal(composer["lifetime_paid_cents"], 0, "lifetime_paid_cents")
        assert composer["latest_statement_period_end"] is None
        assert composer["version"] == 1
        assert_common_fields(composer)
        assert_three_fraction_timestamp(composer["created_at"])
        assert_same_instant(composer["created_at"], clock_origin)
        assert_same_instant(composer["updated_at"], clock_origin)


# ---------------------------------------------------------------------------
# Rate-card tier
# ---------------------------------------------------------------------------


class TestLicenseTierDefaultsAndSchemaRejections:
    def test_term_bounds_default_to_one_and_one_hundred_twenty(self, api):
        """PRD §3.4: "The quotable term is bounded by `min_term_months`, defaulting to 1,
        and `max_term_months`, defaulting to 120, both between 1 and 120 with the maximum
        at or above the minimum."

        Design: Corner/entities/license_tier_defaults_applied_then_out_of_range_values_rejected
        """
        tier = assert_created(
            api.create_license_tier(
                {
                    "code": "FILM-STD",
                    "media_type": "FILM",
                    "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
                    "base_rate_cents": 600000,
                },
                CATALOG_ADMIN,
            )
        )

        assert tier["min_term_months"] == 1
        assert tier["max_term_months"] == 120

    def test_eligibility_flags_default_to_per_use_only(self, api):
        """PRD §3.4: "Two booleans decide which kinds of deal may cite the tier:
        `per_use_eligible`, defaulting to true, and `blanket_eligible`, defaulting to
        false."

        Design: Corner/entities/license_tier_defaults_applied_then_out_of_range_values_rejected
        """
        tier = assert_created(
            api.create_license_tier(
                {
                    "code": "FILM-STD",
                    "media_type": "FILM",
                    "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
                    "base_rate_cents": 600000,
                },
                CATALOG_ADMIN,
            )
        )

        assert tier["per_use_eligible"] is True
        assert tier["blanket_eligible"] is False
        assert tier["version"] == 1
        assert_common_fields(tier)

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "code": "POD-STD",
                "media_type": "PODCAST",
                "allowed_scales": ["NATIONAL"],
                "base_rate_cents": 100000,
            },
            {
                "code": "ZERO-STD",
                "media_type": "GAME",
                "allowed_scales": ["LOCAL"],
                "base_rate_cents": 0,
            },
        ],
        ids=["media_type_outside_declared_set", "base_rate_not_above_zero"],
    )
    def test_out_of_range_tier_values_are_schema_rejections(self, api, payload):
        """PRD §2.6: "**Schema and type validation** — on every write endpoint: a
        required field is absent, a field has the wrong JSON type, an enum value falls
        outside its declared set, a numeric value falls outside its declared range, or an
        array breaches its member bounds → `ERR_VALIDATION` (422)."

        Design: Corner/entities/license_tier_defaults_applied_then_out_of_range_values_rejected
        """
        assert_declared_error(
            api.create_license_tier(payload, CATALOG_ADMIN), ERR_VALIDATION
        )


# ---------------------------------------------------------------------------
# Composition create and read
# ---------------------------------------------------------------------------


class TestCompositionIngestIgnoresServerOwnedFields:
    def test_status_axes_and_version_ignore_client_supplied_values(self, api):
        """PRD §3.2: "The work lands with `catalog_status` `INGESTED`,
        `availability_status` `AVAILABLE` and `version` 1."

        Design: Corner/entities/composition_system_and_computed_field_input_ignored
        """
        composer, agreement = _composer_and_draft_agreement(api)

        composition = assert_created(
            api.create_composition(
                {
                    "composer_id": composer["id"],
                    "agreement_id": agreement["id"],
                    "title": "Harbour Lights",
                    "duration_sec": 180,
                    "tempo_bpm": 130,
                    "genre": "CINEMATIC",
                    "mood_tags": ["EPIC", "DARK"],
                    "instrumentation": ["STRINGS", "BRASS"],
                    "catalog_status": "CATALOGED",
                    "availability_status": "RESTRICTED",
                    "active_license_count": 7,
                    "relevance_score": 99.99,
                    "version": 42,
                },
                CATALOG_ADMIN,
            )
        )

        assert_composition_axes(composition, "INGESTED", "AVAILABLE")
        assert composition["version"] == 1

    def test_derived_figures_and_relevance_score_start_empty(self, api):
        """PRD §3.2: "A fifth figure, `relevance_score`, exists only inside a
        facet-search response: on a single-work read and in every plain list, it is
        null."

        Design: Corner/entities/composition_system_and_computed_field_input_ignored
        """
        composer, agreement = _composer_and_draft_agreement(api)

        composition = assert_created(
            api.create_composition(
                {
                    "composer_id": composer["id"],
                    "agreement_id": agreement["id"],
                    "title": "Harbour Lights",
                    "duration_sec": 180,
                    "tempo_bpm": 130,
                    "genre": "CINEMATIC",
                    "mood_tags": ["EPIC", "DARK"],
                    "instrumentation": ["STRINGS", "BRASS"],
                    "active_license_count": 7,
                    "relevance_score": 99.99,
                },
                CATALOG_ADMIN,
            )
        )

        assert composition["relevance_score"] is None
        assert composition["active_license_count"] == 0
        assert composition["open_claim_count"] == 0
        assert composition["exclusive_block_until"] is None
        assert_credits_equal(
            composition["lifetime_performance_credits"], 0.00, "lifetime_performance_credits"
        )


class TestCatalogedCompositionRead:
    def test_single_read_returns_the_stored_facets_and_both_axes(self, api):
        """PRD §3.2: "Cataloguing is the gate to commerce, and it takes the work from
        `INGESTED` to `CATALOGED`."

        Design: Corner/entities/composition_retrieval_round_trip_carries_null_relevance_score
        """
        _composer, _agreement, composition = _cataloged_harbour_lights(api)

        read = assert_ok(api.get_composition(composition["id"], LICENSING_AGENT))

        assert read["title"] == "Harbour Lights"
        assert read["duration_sec"] == 180
        assert read["tempo_bpm"] == 130
        assert read["genre"] == "CINEMATIC"
        assert read["mood_tags"] == ["EPIC", "DARK"]
        assert read["instrumentation"] == ["STRINGS", "BRASS"]
        assert_composition_axes(read, "CATALOGED", "AVAILABLE")
        assert read["relevance_score"] is None

    def test_cataloguing_bumps_the_version_to_two(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation, and `version`, an integer that starts at 1
        when the row is created and increases by exactly 1 on every mutation of that
        row."

        Design: Corner/entities/composition_retrieval_round_trip_carries_null_relevance_score
        """
        _composer, _agreement, composition = _cataloged_harbour_lights(api)

        read = assert_ok(api.get_composition(composition["id"], LICENSING_AGENT))

        assert read["version"] == 2
        assert_common_fields(read)


class TestCompositionListing:
    def test_limit_and_offset_window_the_filtered_set(self, api):
        """PRD §2.3: "Both are echoed back in the envelope's `meta` object alongside
        `total_count`, the number of rows matching the filter before the page window is
        applied, and `has_more`, which is true when rows remain after the current
        window."

        Design: Corner/entities/composition_listing_pagination_envelope_and_status_filter
        """
        _composer, works = _three_works_two_cataloged(api)

        first_rows, first_meta = assert_page(
            api.list_compositions({"limit": 2, "offset": 0}, CATALOG_ADMIN)
        )
        second_rows, second_meta = assert_page(
            api.list_compositions({"limit": 2, "offset": 2}, CATALOG_ADMIN)
        )

        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_rows) == 2

        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_rows) == 1

        paged_ids = {row["id"] for row in first_rows} | {row["id"] for row in second_rows}
        assert paged_ids == {work["id"] for work in works}

    def test_catalog_status_and_composer_filters_narrow_the_result(self, api):
        """PRD §3.2: "Works can be read individually or listed with filters on
        `composer_id`, `agreement_id`, `catalog_status`, `availability_status`, `limit`
        and `offset`, which is how the catalogue is walked by composer or by agreement."

        Design: Corner/entities/composition_listing_pagination_envelope_and_status_filter
        """
        composer, works = _three_works_two_cataloged(api)

        cataloged_rows, cataloged_meta = assert_page(
            api.list_compositions({"catalog_status": "CATALOGED"}, CATALOG_ADMIN)
        )
        ingested_rows, ingested_meta = assert_page(
            api.list_compositions(
                {"composer_id": composer["id"], "catalog_status": "INGESTED"}, CATALOG_ADMIN
            )
        )

        assert cataloged_meta["total_count"] == 2
        assert cataloged_meta["has_more"] is False
        assert {row["id"] for row in cataloged_rows} == {works[0]["id"], works[1]["id"]}

        assert ingested_meta["total_count"] == 1
        assert len(ingested_rows) == 1
        assert ingested_rows[0]["id"] == works[2]["id"]


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


class TestMissingReferencesReturnTheirOwnNotFound:
    @pytest.mark.parametrize(
        "endpoint, error_id",
        [
            ("get_composer", ERR_COMPOSER_NOT_FOUND),
            ("get_composer_agreement", ERR_COMPOSER_AGREEMENT_NOT_FOUND),
            ("get_composition", ERR_COMPOSITION_NOT_FOUND),
            ("get_license_tier", ERR_LICENSE_TIER_NOT_FOUND),
        ],
    )
    def test_unknown_path_identifier_returns_the_addressed_entity_not_found(
        self, api, endpoint, error_id
    ):
        """PRD §2.6: "**Path entity exists** — on every endpoint with a path parameter:
        the identifier in the path matches no row of the addressed entity → the matching
        not-found error (404)."

        Design: Corner/entities/reference_ids_that_do_not_exist_return_the_declared_404_not_found
        """
        _composer_and_draft_agreement(api)

        assert_declared_error(
            getattr(api, endpoint)(MISSING_ID, CATALOG_ADMIN), error_id
        )

    @pytest.mark.parametrize(
        "bad_field, error_id",
        [
            ("composer_id", ERR_COMPOSER_NOT_FOUND),
            ("agreement_id", ERR_COMPOSER_AGREEMENT_NOT_FOUND),
        ],
    )
    def test_unknown_body_foreign_key_returns_the_referenced_entity_not_found(
        self, api, bad_field, error_id
    ):
        """PRD §2.6: "**Body reference exists** — on every write endpoint carrying a
        foreign key in its body: a body foreign key matches no row of the referenced
        entity → the matching not-found error (404)."

        Design: Corner/entities/reference_ids_that_do_not_exist_return_the_declared_404_not_found
        """
        composer, agreement = _composer_and_draft_agreement(api)
        payload = build.composition_payload(
            composer["id"],
            agreement["id"],
            title="Ghost Work",
            duration_sec=120,
            tempo_bpm=100,
            genre="FOLK",
            mood_tags=["CALM"],
            instrumentation=["GUITAR"],
        )
        payload[bad_field] = MISSING_ID

        assert_declared_error(api.create_composition(payload, CATALOG_ADMIN), error_id)

        _rows, meta = assert_page(api.list_compositions({"limit": 100}, CATALOG_ADMIN))
        assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Sync request
# ---------------------------------------------------------------------------


class TestSyncRequestCreationShape:
    @pytest.mark.parametrize("omitted", ["tier_id", "requested_term_months"])
    def test_omitting_a_required_field_is_a_schema_rejection(self, api, omitted):
        """PRD §2.6: "**Schema and type validation** — on every write endpoint: a
        required field is absent, a field has the wrong JSON type, an enum value falls
        outside its declared set, a numeric value falls outside its declared range, or an
        array breaches its member bounds → `ERR_VALIDATION` (422)."

        Design: Corner/entities/sync_request_missing_required_fields_rejected
        """
        ground = _sync_request_ground(api)
        payload = _minimal_sync_request_payload(ground)
        del payload[omitted]

        assert_declared_error(
            api.create_sync_request(payload, LICENSING_AGENT), ERR_VALIDATION
        )

    def test_new_request_lands_submitted_with_no_quote(self, api):
        """PRD §3.4: "A new request lands in `SUBMITTED` with `revision_round` 0 and
        every quote field null."

        Design: Corner/entities/sync_request_missing_required_fields_rejected
        """
        ground = _sync_request_ground(api)

        request = assert_created(
            api.create_sync_request(_minimal_sync_request_payload(ground), LICENSING_AGENT)
        )

        assert_status(request, "SUBMITTED")
        assert request["revision_round"] == 0
        assert request["quoted_fee_cents"] is None
        assert request["quoted_spend_basis_cents"] is None
        assert request["quoted_discount_pct"] is None
        assert request["quote_expires_at"] is None
        assert request["license_id"] is None

    def test_optional_deliverable_flags_default_to_off(self, api):
        """PRD §3.4: "Five optional flags describe the deliverable and the deal shape:
        `exclusive_requested`, defaulting to false, asking for media-and-scale
        exclusivity for the term; `custom_edit_requested`, defaulting to false, requiring
        an edit pass before delivery; `stems_requested`, defaulting to false, adding the
        multitrack stems to the deliverable; `alternate_lengths_sec`, an array of 0 to 4
        requested cut-down lengths in seconds with each member between 5 and 300,
        defaulting to empty; and `rush_requested`, defaulting to false, accepting a rush
        surcharge."

        Design: Corner/entities/sync_request_missing_required_fields_rejected
        """
        ground = _sync_request_ground(api)

        request = assert_created(
            api.create_sync_request(_minimal_sync_request_payload(ground), LICENSING_AGENT)
        )

        assert request["exclusive_requested"] is False
        assert request["custom_edit_requested"] is False
        assert request["stems_requested"] is False
        assert request["alternate_lengths_sec"] == []
        assert request["rush_requested"] is False
        assert request["brief_note"] is None


# ---------------------------------------------------------------------------
# The two thin append-only records
# ---------------------------------------------------------------------------


class TestThinAppendOnlyRecords:
    def test_fingerprint_match_carries_no_version_and_no_updated_at(self, api, clock_origin):
        """PRD §2.4: "A fingerprint match carries only `id` and `created_at` — it has no
        `updated_at` and no `version`, and no endpoint updates it."

        Design: Corner/entities/fingerprint_match_and_ledger_entry_are_immutable_without_version
        """
        _composer, _agreement, composition = _cataloged_harbour_lights(api)

        match = assert_created(
            api.create_fingerprint_match(
                {
                    "composition_id": composition["id"],
                    "source_platform": "UGC_VIDEO",
                    "source_reference": "vid-88121",
                    "matched_seconds": 120,
                    "confidence_pct": 96.0,
                },
                CATALOG_ADMIN,
            )
        )
        read = assert_ok(api.get_fingerprint_match(match["id"], RIGHTS_MANAGER))

        for row in (match, read):
            assert_thin_record_fields(row)
            assert row["matched_seconds"] == 120
            assert row["confidence_pct"] == pytest.approx(96.0, abs=0.01)
            assert_three_fraction_timestamp(row["detected_at"])
            assert_same_instant(row["detected_at"], clock_origin)

    def test_manual_ledger_entry_carries_no_version_and_no_updated_at(
        self, api, clock_origin
    ):
        """PRD §2.4: "A royalty ledger entry likewise carries only `id` and `created_at`,
        with no `updated_at` and no `version`; it is immutable except for two narrowly
        scoped stamps, `statement_id` when a statement sweeps it and `cash_recognized_at`
        when the underlying money is collected, and neither stamp produces a version
        because the entry has none."

        Design: Corner/entities/fingerprint_match_and_ledger_entry_are_immutable_without_version
        """
        composer, _agreement, _composition = _cataloged_harbour_lights(api)

        entry = assert_created(
            api.create_royalty_ledger_entry(
                {
                    "composer_id": composer["id"],
                    "source_type": "ADJUSTMENT",
                    "amount_cents": 5000,
                    "memo": "goodwill adjustment",
                },
                ACCOUNTANT_ONE,
            )
        )
        read = assert_ok(api.get_royalty_ledger_entry(entry["id"], ACCOUNTANT_ONE))

        for row in (entry, read):
            assert_thin_record_fields(row)
            assert row["source_type"] == "ADJUSTMENT"
            assert_cents_equal(row["amount_cents"], 5000, "amount_cents")
            assert row["source_ref_id"] is None
            assert row["statement_id"] is None
            assert_same_instant(row["accrual_recognized_at"], clock_origin)
            assert_same_instant(row["cash_recognized_at"], clock_origin)


# ---------------------------------------------------------------------------
# Usage report parentage
# ---------------------------------------------------------------------------


class TestUsageReportBlanketParent:
    def test_unknown_blanket_agreement_is_rejected_as_not_found(self, api):
        """PRD §2.7: "Each entity has exactly one not-found error:
        `ERR_COMPOSER_NOT_FOUND`, `ERR_COMPOSER_AGREEMENT_NOT_FOUND`,
        `ERR_COMPOSITION_NOT_FOUND`, `ERR_LICENSE_TIER_NOT_FOUND`,
        `ERR_LICENSEE_NOT_FOUND`, `ERR_SYNC_REQUEST_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
        `ERR_BLANKET_AGREEMENT_NOT_FOUND`, `ERR_USAGE_REPORT_NOT_FOUND`,
        `ERR_CUE_SHEET_NOT_FOUND`, `ERR_FINGERPRINT_MATCH_NOT_FOUND`,
        `ERR_INFRINGEMENT_CLAIM_NOT_FOUND`, `ERR_ROYALTY_STATEMENT_NOT_FOUND` and
        `ERR_ROYALTY_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/entities/usage_report_parent_must_exist_else_blanket_not_found
        """
        licensee = new_licensee(
            api, legal_name="Meridian Broadcasting", licensee_type="BROADCASTER"
        )
        blanket = assert_created(
            api.create_blanket_agreement(
                build.blanket_agreement_payload(licensee["id"]), LICENSING_AGENT
            )
        )

        assert_declared_error(
            api.create_usage_report(
                {
                    "blanket_agreement_id": MISSING_ID,
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-08-31T00:00:00Z",
                },
                LICENSING_AGENT,
            ),
            ERR_BLANKET_AGREEMENT_NOT_FOUND,
        )

        _rows, meta = assert_page(
            api.list_usage_reports(
                {"blanket_agreement_id": blanket["id"], "limit": 100}, LICENSING_AGENT
            )
        )
        assert meta["total_count"] == 0

    def test_report_on_its_blanket_parent_lands_due_with_zero_pool_figures(self, api):
        """PRD §3.6: "New reports land in `DUE` with zero pool figures and an empty
        `pool_allocations` array."

        Design: Corner/entities/usage_report_parent_must_exist_else_blanket_not_found
        """
        licensee = new_licensee(
            api, legal_name="Meridian Broadcasting", licensee_type="BROADCASTER"
        )
        blanket = assert_created(
            api.create_blanket_agreement(
                build.blanket_agreement_payload(licensee["id"]), LICENSING_AGENT
            )
        )

        report = assert_created(
            api.create_usage_report(
                {
                    "blanket_agreement_id": blanket["id"],
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-08-31T00:00:00Z",
                },
                LICENSING_AGENT,
            )
        )

        assert_status(report, "DUE")
        assert report["blanket_agreement_id"] == blanket["id"]
        assert_cents_equal(report["pool_cents"], 0, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 0, "pool_admin_fee_cents")
        assert_cents_equal(
            report["pool_distributable_cents"], 0, "pool_distributable_cents"
        )
        assert report["pool_allocations"] == []
        assert report["reported_minutes_total"] == 0
        assert_credits_equal(
            report["reported_credits_total"], 0.00, "reported_credits_total"
        )
        assert report["resubmission_count"] == 0
        assert report["submitted_at"] is None
        assert report["accepted_at"] is None
        assert report["rejection_reason"] is None


# ---------------------------------------------------------------------------
# Cue-sheet parentage
# ---------------------------------------------------------------------------


class TestCueSheetParentage:
    @pytest.mark.parametrize("parents", ["both", "neither"])
    def test_a_sheet_without_exactly_one_parent_is_refused(self, api, parents):
        """PRD §3.7: "Supplying both, or neither, is refused with
        `ERR_CUE_SHEET_PARENT_INVALID`."

        Design: Corner/entities/cue_sheet_requires_exactly_one_parent_else_rejected
        """
        ground = _blanket_reporting_ground(api)
        payload = {
            "production_title": "Coastal Nights S01E01",
            "broadcast_date": "2026-08-10T00:00:00Z",
            "market_tier": "NETWORK",
            "cues": [
                {
                    "composition_id": ground["work_a"]["id"],
                    "usage_type": "THEME",
                    "duration_sec": 45,
                }
            ],
        }
        if parents == "both":
            payload["license_id"] = _issued_license_on_work_a(api, ground)["id"]
            payload["usage_report_id"] = ground["blanket"].usage_report_id

        assert_declared_error(
            api.create_cue_sheet(payload, LICENSING_AGENT), ERR_CUE_SHEET_PARENT_INVALID
        )

    def test_a_usage_report_parent_alone_collects_cues_over_two_works(self, api):
        """PRD §3.7: "Exactly one of `license_id` and `usage_report_id` must be supplied:
        the first for per-use reporting against a single licence, the second for blanket
        reporting against a period."

        Design: Corner/entities/cue_sheet_requires_exactly_one_parent_else_rejected
        """
        ground = _blanket_reporting_ground(api)

        sheet = assert_created(
            api.create_cue_sheet(
                {
                    "production_title": "Coastal Nights S01E01",
                    "broadcast_date": "2026-08-10T00:00:00Z",
                    "market_tier": "NETWORK",
                    "cues": [
                        {
                            "composition_id": ground["work_a"]["id"],
                            "usage_type": "THEME",
                            "duration_sec": 45,
                        },
                        {
                            "composition_id": ground["work_b"]["id"],
                            "usage_type": "BACKGROUND",
                            "duration_sec": 60,
                        },
                    ],
                    "usage_report_id": ground["blanket"].usage_report_id,
                },
                LICENSING_AGENT,
            )
        )

        assert sheet["usage_report_id"] == ground["blanket"].usage_report_id
        assert sheet["license_id"] is None
        assert_status(sheet, "COLLECTED")
        assert sheet["total_seconds"] == 105
        assert set(sheet["credits_by_composition"]) == {
            ground["work_a"]["id"],
            ground["work_b"]["id"],
        }


# ---------------------------------------------------------------------------
# The singleton search profile
# ---------------------------------------------------------------------------


class TestSearchProfileSingleton:
    def test_reading_the_profile_before_it_has_been_written_is_not_found(self, api):
        """PRD §3.3: "Searching or reading the profile before it has ever been written
        yields `ERR_SEARCH_PROFILE_NOT_FOUND`."

        Design: Corner/entities/search_profile_singleton_is_replaced_by_put_and_missing_profile_not_found
        """
        assert_declared_error(
            api.get_search_profile(CATALOG_ADMIN), ERR_SEARCH_PROFILE_NOT_FOUND
        )

    def test_first_write_applies_the_two_optional_defaults(self, api):
        """PRD §3.3: "Two further knobs are optional: `tempo_tolerance_bpm`, the
        beat-per-minute distance at which tempo proximity decays to zero, a whole number
        from 1 through 60 defaulting to 20; and `restricted_availability_factor`, the
        multiplier applied to the weighted score of a work whose rights axis reads
        `RESTRICTED`, a value from 0.00 through 1.00 with two decimals defaulting to
        0.60."

        Design: Corner/entities/search_profile_singleton_is_replaced_by_put_and_missing_profile_not_found
        """
        profile = assert_ok(
            api.put_search_profile(
                {
                    "weight_mood": 40,
                    "weight_genre": 25,
                    "weight_instrumentation": 20,
                    "weight_tempo": 15,
                },
                CATALOG_ADMIN,
            )
        )

        assert profile["tempo_tolerance_bpm"] == 20
        assert profile["restricted_availability_factor"] == pytest.approx(0.60, abs=0.01)
        assert profile["version"] == 1

    def test_second_write_replaces_the_same_singleton_row(self, api):
        """PRD §3.3: "The first write creates the profile and every later write replaces
        it wholesale."

        Design: Corner/entities/search_profile_singleton_is_replaced_by_put_and_missing_profile_not_found
        """
        first = assert_ok(
            api.put_search_profile(
                {
                    "weight_mood": 40,
                    "weight_genre": 25,
                    "weight_instrumentation": 20,
                    "weight_tempo": 15,
                },
                CATALOG_ADMIN,
            )
        )
        second = assert_ok(
            api.put_search_profile(
                {
                    "weight_mood": 0,
                    "weight_genre": 0,
                    "weight_instrumentation": 0,
                    "weight_tempo": 100,
                    "tempo_tolerance_bpm": 40,
                    "restricted_availability_factor": 0.25,
                },
                CATALOG_ADMIN,
            )
        )
        read = assert_ok(api.get_search_profile(LICENSING_AGENT))

        assert second["id"] == first["id"]
        assert read["id"] == first["id"]
        assert read["weight_mood"] == 0
        assert read["weight_genre"] == 0
        assert read["weight_instrumentation"] == 0
        assert read["weight_tempo"] == 100
        assert read["tempo_tolerance_bpm"] == 40
        assert read["restricted_availability_factor"] == pytest.approx(0.25, abs=0.01)
        assert read["version"] == 2


# ---------------------------------------------------------------------------
# Licensee credit exposure
# ---------------------------------------------------------------------------


class TestLicenseeCreditExposureAtCreation:
    def test_a_new_account_has_its_whole_limit_available(self, api):
        """PRD §3.4: "A new account starts with `committed_spend_cents` at 0,
        `reserved_spend_cents` at 0 and `credit_available_cents` equal to
        `credit_limit_cents`."

        Design: Corner/entities/licensee_creation_initializes_credit_exposure_aggregates
        """
        licensee = assert_created(
            api.create_licensee(
                {
                    "legal_name": "Northwind Pictures",
                    "licensee_type": "PRODUCTION_COMPANY",
                    "credit_limit_cents": 780000,
                },
                LICENSING_AGENT,
            )
        )

        assert_credit_exposure(licensee, 0, 0, 780000)
        assert licensee["licensee_type"] == "PRODUCTION_COMPANY"
        assert licensee["version"] == 1
