"""Requests that break two rules at once, where the earlier rule must answer.

Each pair here is built so that one single call violates both a higher-precedence
and a lower-precedence check, and a control call violates only the lower one — so
the answered error proves the ordering rather than a single-error coincidence.
"""

from test_helpers import (
    CATALOG_ADMIN,
    LICENSING_AGENT,
    advance_clock,
    assert_created,
    assert_credit_exposure,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_status,
    composition_version,
    make_licensee_headers,
    new_active_agreement,
    new_composer,
    new_licensee,
    new_tier,
    read_licensee,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_COMPOSITION_NOT_LICENSABLE,
    ERR_COMPOSITION_VERSION_CONFLICT,
    ERR_QUOTE_EXPIRED,
    ERR_TERM_OUTSIDE_TIER_RANGE,
)


def _two_reviewed_requests_on_a_short_term_tier(api):
    """Two reviewed 24-month requests priced from a tier capped at 12 months.

    Both works sit under the same ACTIVE agreement. Work A is retired after its
    request was reviewed, so A's quote breaks the licensable rule and the term
    range at once; work B stays catalogued and breaks the term range only.
    """
    composer = new_composer(api, display_name="Greta Halloran", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)

    compositions = []
    for title, instrumentation in (
        ("Ember Room", ["PIANO", "GUITAR"]),
        ("Ember Room Alt", ["PIANO"]),
    ):
        created = assert_created(
            api.create_composition(
                build.composition_payload(
                    composer["id"],
                    agreement["id"],
                    title=title,
                    duration_sec=140,
                    tempo_bpm=88,
                    genre="JAZZ",
                    mood_tags=["CALM"],
                    instrumentation=instrumentation,
                ),
                CATALOG_ADMIN,
            )
        )
        compositions.append(
            assert_ok(api.catalog_composition(created["id"], None, CATALOG_ADMIN))
        )

    tier = new_tier(
        api,
        code="BTV-SHORT",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL"],
        base_rate_cents=300000,
        min_term_months=1,
        max_term_months=12,
        per_use_eligible=True,
        blanket_eligible=False,
    )
    licensee = new_licensee(
        api,
        legal_name="Quarry Films",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=5000000,
    )

    requests = []
    for composition in compositions:
        request = assert_created(
            api.create_sync_request(
                build.sync_request_payload(
                    composition["id"],
                    licensee["id"],
                    tier["id"],
                    media_type="BROADCAST_TV",
                    distribution_scale="NATIONAL",
                    requested_term_start="2026-09-01T00:00:00Z",
                    requested_term_months=24,
                ),
                LICENSING_AGENT,
            )
        )
        requests.append(assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT)))

    retired = assert_ok(
        api.retire_composition(compositions[0]["id"], {"reason": "master lost"}, CATALOG_ADMIN)
    )

    return {
        "composer": composer,
        "agreement": agreement,
        "tier": tier,
        "licensee": licensee,
        "retired_composition": retired,
        "live_composition": compositions[1],
        "request_on_retired_work": requests[0],
        "request_on_live_work": requests[1],
    }


class TestLicensableOutranksTierTermRangeOnQuote:
    def test_retired_work_answers_the_licensable_error_not_the_term_range_error(self, api):
        """PRD §2.6: "The service therefore evaluates a single, totally ordered ladder
        of 51 checks and returns the error of the **first** rule violated; no later
        rule can mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/quote_cross_entity_licensable_outranks_business_term_range
        """
        ground = _two_reviewed_requests_on_a_short_term_tier(api)

        response = api.quote_sync_request(
            ground["request_on_retired_work"]["id"], build.quote_payload(14), LICENSING_AGENT
        )
        assert_declared_error(response, ERR_COMPOSITION_NOT_LICENSABLE)

    def test_term_range_error_surfaces_when_only_the_later_rule_is_violated(self, api):
        """PRD §3.4: "It requires the work to be `CATALOGED` with `availability_status`
        in `AVAILABLE` or `RESTRICTED`, failing with `ERR_COMPOSITION_NOT_LICENSABLE`;
        it requires the governing agreement to be `ACTIVE`, failing with
        `ERR_AGREEMENT_NOT_ACTIVE`; and it requires `requested_term_months` to lie
        within the tier's `min_term_months` and `max_term_months` inclusive, failing
        with `ERR_TERM_OUTSIDE_TIER_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/quote_cross_entity_licensable_outranks_business_term_range
        """
        ground = _two_reviewed_requests_on_a_short_term_tier(api)

        response = api.quote_sync_request(
            ground["request_on_live_work"]["id"], build.quote_payload(14), LICENSING_AGENT
        )
        assert_declared_error(response, ERR_TERM_OUTSIDE_TIER_RANGE)

    def test_neither_refused_quote_reserves_credit_or_moves_the_request(self, api):
        """PRD §3.4: "Quoting also raises the licensee's `reserved_spend_cents` by
        `quoted_fee_cents` and lowers `credit_available_cents` by the same amount."

        Design: Difficulty/priority_pair_validation_conflict/quote_cross_entity_licensable_outranks_business_term_range
        """
        ground = _two_reviewed_requests_on_a_short_term_tier(api)

        assert_declared_error(
            api.quote_sync_request(
                ground["request_on_retired_work"]["id"], build.quote_payload(14), LICENSING_AGENT
            ),
            ERR_COMPOSITION_NOT_LICENSABLE,
        )
        assert_declared_error(
            api.quote_sync_request(
                ground["request_on_live_work"]["id"], build.quote_payload(14), LICENSING_AGENT
            ),
            ERR_TERM_OUTSIDE_TIER_RANGE,
        )

        for key in ("request_on_retired_work", "request_on_live_work"):
            reread = assert_ok(api.get_sync_request(ground[key]["id"], LICENSING_AGENT))
            assert_status(reread, "UNDER_REVIEW")
            assert reread["quoted_fee_cents"] is None, "a refused quote writes no fee"

        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 0, 0, 5000000)


def _accepted_deal_with_stale_version_and_expired_quote(api):
    """An ACCEPTED request whose quote has lapsed and whose work has moved on.

    The work's version is captured at cataloguing and then bumped by a metadata
    revision, so the captured token is one behind; the clock is then pushed past
    `quote_expires_at`, so a single issuance breaks both rules at once.
    """
    composer = new_composer(api, display_name="Dario Neves", pro_affiliation="SESAC")
    agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Rua Azul",
                duration_sec=200,
                tempo_bpm=104,
                genre="FOLK",
                mood_tags=["HOPEFUL"],
                instrumentation=["GUITAR"],
            ),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    stale_version = composition["version"]

    tier = new_tier(
        api,
        code="BTV-STD",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=300000,
        min_term_months=1,
        max_term_months=120,
        per_use_eligible=True,
        blanket_eligible=False,
    )
    licensee = new_licensee(
        api, legal_name="Azul Media", licensee_type="AGENCY", credit_limit_cents=5000000
    )

    request = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                composition["id"],
                licensee["id"],
                tier["id"],
                media_type="BROADCAST_TV",
                distribution_scale="NATIONAL",
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT))
    request = assert_ok(
        api.quote_sync_request(request["id"], build.quote_payload(14), LICENSING_AGENT)
    )
    request = assert_ok(
        api.accept_sync_request(request["id"], None, make_licensee_headers(licensee["id"]))
    )

    assert_ok(
        api.update_composition(
            composition["id"], {"title": "Rua Azul (Remaster)"}, CATALOG_ADMIN
        )
    )
    advance_clock(api, "2026-08-20T00:00:00Z")

    return {
        "composer": composer,
        "agreement": agreement,
        "composition": composition,
        "stale_version": stale_version,
        "tier": tier,
        "licensee": licensee,
        "sync_request": request,
    }


class TestCompositionVersionConflictOutranksQuoteExpiryOnIssuance:
    def test_stale_version_token_answers_before_the_lapsed_quote(self, api):
        """PRD §2.6: "The service therefore evaluates a single, totally ordered ladder
        of 51 checks and returns the error of the **first** rule violated; no later
        rule can mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/issuance_occ_conflict_outranks_temporal_quote_expiry
        """
        ground = _accepted_deal_with_stale_version_and_expired_quote(api)

        response = api.create_license(
            build.per_use_license_payload(
                ground["sync_request"]["id"], ground["stale_version"]
            ),
            LICENSING_AGENT,
        )
        assert_declared_error(response, ERR_COMPOSITION_VERSION_CONFLICT)

    def test_expired_quote_surfaces_once_the_version_token_is_refreshed(self, api):
        """PRD §3.5: "The quote must not have gone stale: a logical clock later than
        `quote_expires_at` means `ERR_QUOTE_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/issuance_occ_conflict_outranks_temporal_quote_expiry
        """
        ground = _accepted_deal_with_stale_version_and_expired_quote(api)

        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    ground["sync_request"]["id"], ground["stale_version"]
                ),
                LICENSING_AGENT,
            ),
            ERR_COMPOSITION_VERSION_CONFLICT,
        )

        fresh_version = composition_version(api, ground["composition"]["id"])
        assert fresh_version == ground["stale_version"] + 1, (
            "the metadata revision bumped the work's version and the refused "
            "issuance did not"
        )

        retry = api.create_license(
            build.per_use_license_payload(ground["sync_request"]["id"], fresh_version),
            LICENSING_AGENT,
        )
        assert_declared_error(retry, ERR_QUOTE_EXPIRED)

    def test_metadata_revision_is_the_only_version_bump_the_work_records(self, api):
        """PRD §3.2: "Metadata can be corrected in place: a `CatalogAdmin` may revise
        `title`, `tempo_bpm`, `genre`, `mood_tags` and `instrumentation`, which
        refreshes `updated_at` and increments `version`."

        Design: Difficulty/priority_pair_validation_conflict/issuance_occ_conflict_outranks_temporal_quote_expiry
        """
        ground = _accepted_deal_with_stale_version_and_expired_quote(api)

        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    ground["sync_request"]["id"], ground["stale_version"]
                ),
                LICENSING_AGENT,
            ),
            ERR_COMPOSITION_VERSION_CONFLICT,
        )
        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    ground["sync_request"]["id"],
                    composition_version(api, ground["composition"]["id"]),
                ),
                LICENSING_AGENT,
            ),
            ERR_QUOTE_EXPIRED,
        )

        assert composition_version(api, ground["composition"]["id"]) == (
            ground["stale_version"] + 1
        ), "neither refused issuance may bump the work's version"

    def test_refused_issuance_leaves_the_accepted_reservation_intact(self, api):
        """PRD §3.4: "The reservation stays on the licensee until a licence is actually
        issued from the request."

        Design: Difficulty/priority_pair_validation_conflict/issuance_occ_conflict_outranks_temporal_quote_expiry
        """
        ground = _accepted_deal_with_stale_version_and_expired_quote(api)

        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    ground["sync_request"]["id"], ground["stale_version"]
                ),
                LICENSING_AGENT,
            ),
            ERR_COMPOSITION_VERSION_CONFLICT,
        )
        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    ground["sync_request"]["id"],
                    composition_version(api, ground["composition"]["id"]),
                ),
                LICENSING_AGENT,
            ),
            ERR_QUOTE_EXPIRED,
        )

        reread = assert_ok(api.get_sync_request(ground["sync_request"]["id"], LICENSING_AGENT))
        assert_status(reread, "ACCEPTED")
        assert reread["license_id"] is None, "no licence may exist for a refused issuance"

        rows, _meta = assert_page(
            api.list_licenses({"sync_request_id": ground["sync_request"]["id"]}, LICENSING_AGENT)
        )
        assert rows == [], "a refused issuance writes no licence row"

        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 0, 390000, 4610000)
