"""Cross-cutting layers: optimistic concurrency and derived-field reconciliation.

Three mechanisms are traced here rather than one workflow. The version token on a
composer guards the ledger snapshot a statement is built from; the version on a
composition moves on every mutation and holds still on every read; and the
derived figures on a work and on a composer are recomputed from their declared
input sets as cue sheets and claims move through their states.
"""

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    assert_cents_equal,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_statement_figures,
    assert_status,
    assert_thin_record_fields,
    assert_three_fraction_timestamp,
    composer_version,
    composition_version,
    ledger_entries,
    make_licensee_headers,
    new_active_agreement,
    new_cataloged_work,
    new_composer,
    new_licensee,
    new_tier,
    read_composer,
    read_composition,
)
from test_helpers import factories as build


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _composer_with_a_ledger_read_gone_stale(api):
    """A composer whose version was read after 40000 landed but before 10000 did.

    Both appends are manual adjustments, so each one moves the composer's money
    picture and therefore its `version`; the token the caller holds is one
    behind by the time it is presented.
    """
    composer = new_composer(
        api,
        display_name="Nadia Okoro",
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.30,
    )
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer["id"], 40000, memo="Catalogue bonus"),
            ACCOUNTANT_ONE,
        )
    )
    observed_version = composer_version(api, composer["id"])
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer["id"], 10000, memo="Late correction"),
            ACCOUNTANT_ONE,
        )
    )
    return composer, observed_version


def _accepted_film_request_on_a_cataloged_work(api):
    """A CATALOGED work under an ACTIVE agreement plus an ACCEPTED FILM request.

    The work has been written twice — ingest and catalogue — so its `version`
    reads 2 before the trigger walk starts.
    """
    composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement = new_active_agreement(
        api,
        composer["id"],
        writer_share_pct=50.00,
        publisher_share_pct=50.00,
        sync_fee_share_pct=40.00,
    )
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Harbour Lights",
                duration_sec=180,
                tempo_bpm=130,
                genre="CINEMATIC",
                mood_tags=["EPIC"],
                instrumentation=["STRINGS"],
            ),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api,
        legal_name="Northwind Pictures",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=90000000,
    )
    request = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                composition["id"],
                licensee["id"],
                tier["id"],
                media_type="FILM",
                distribution_scale="NATIONAL",
                requested_term_start="2026-08-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(api.review_sync_request(request["id"], None, LICENSING_AGENT))
    assert_ok(api.quote_sync_request(request["id"], build.quote_payload(14), LICENSING_AGENT))
    request = assert_ok(
        api.accept_sync_request(request["id"], None, make_licensee_headers(licensee["id"]))
    )
    return {
        "composer": composer,
        "agreement": agreement,
        "composition": composition,
        "tier": tier,
        "licensee": licensee,
        "sync_request": request,
    }


def _issued_film_license(api):
    """The accepted FILM request carried into an ISSUED per-use licence."""
    ground = _accepted_film_request_on_a_cataloged_work(api)
    ground["license"] = assert_created(
        api.create_license(
            build.per_use_license_payload(
                ground["sync_request"]["id"],
                composition_version(api, ground["composition"]["id"]),
            ),
            LICENSING_AGENT,
        )
    )
    return ground


def _notice_and_settle_a_ugc_detection(api, composition_id):
    """Record a 120-second UGC detection, claim it, notice it and settle it."""
    match = assert_created(
        api.create_fingerprint_match(
            build.fingerprint_match_payload(
                composition_id,
                source_platform="UGC_VIDEO",
                source_reference="ugc://clip/88421",
                matched_seconds=120,
                confidence_pct=99.0,
            ),
            CATALOG_ADMIN,
        )
    )
    claim = assert_created(
        api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
    )
    assert_ok(api.notice_claim(claim["id"], {"notice_channel": "DMCA_WEBFORM"}, RIGHTS_MANAGER))
    settled = assert_ok(
        api.settle_claim(claim["id"], build.settle_claim_payload("STATUTORY"), RIGHTS_MANAGER)
    )
    return match, claim, settled


# ---------------------------------------------------------------------------
# Optimistic concurrency on the composer ledger snapshot
# ---------------------------------------------------------------------------


class TestStatementCreationGuardsTheComposerLedgerSnapshot:
    def test_stale_composer_token_from_an_intervening_append_is_refused(self, api):
        """PRD §2.10: "If that value differs from the composer's current `version` —
        which advances whenever the composer's ledger or advance position moves — the
        request is refused with `ERR_COMPOSER_VERSION_CONFLICT` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_composer_version_refuses_statement_then_fresh_version_succeeds
        """
        composer, observed_version = _composer_with_a_ledger_read_gone_stale(api)

        refused = api.create_royalty_statement(
            build.statement_payload(composer["id"], observed_version), ACCOUNTANT_ONE
        )
        assert_declared_error(refused, "ERR_COMPOSER_VERSION_CONFLICT")

        rows, meta = assert_page(
            api.list_royalty_ledger_entries(
                {"composer_id": composer["id"], "limit": 100}, ACCOUNTANT_ONE
            )
        )
        assert meta["total_count"] == 2, "the two appends must both still be on the ledger"
        for entry in rows:
            assert_thin_record_fields(entry)
            assert entry["statement_id"] is None, "a refused statement sweeps nothing"

        statements, statement_meta = assert_page(
            api.list_royalty_statements({"composer_id": composer["id"]}, ACCOUNTANT_ONE)
        )
        assert statement_meta["total_count"] == 0
        assert statements == []

    def test_retry_with_the_fresh_token_sweeps_the_current_ledger(self, api):
        """PRD §3.9: "The sweep set is every ledger entry belonging to this composer
        whose `statement_id` is still null, whose origin is neither `ADVANCE` nor
        `ADVANCE_RECOUP`, and whose relevant timestamp falls inside the window; entries
        are taken in `created_at` ascending order."

        Design: Corner/cross_cutting_complexity_layers/stale_composer_version_refuses_statement_then_fresh_version_succeeds
        """
        composer, observed_version = _composer_with_a_ledger_read_gone_stale(api)
        assert_declared_error(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], observed_version), ACCOUNTANT_ONE
            ),
            "ERR_COMPOSER_VERSION_CONFLICT",
        )

        fresh_version = composer_version(api, composer["id"])
        statement = assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], fresh_version), ACCOUNTANT_ONE
            )
        )
        assert_status(statement, "DRAFT")
        assert_statement_figures(
            statement,
            gross_cents=50000,
            recouped_cents=0,
            withholding_cents=15000,
            net_payable_cents=35000,
            payout_status="PAYABLE",
            line_count=2,
        )

        rows = ledger_entries(api, composer["id"])
        assert len(rows) == 2
        for entry in rows:
            assert entry["statement_id"] == statement["id"]

    def test_successful_statement_creation_advances_the_composer_version_once(self, api):
        """PRD §2.10: "Every successful statement creation increments the composer's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/stale_composer_version_refuses_statement_then_fresh_version_succeeds
        """
        composer, _observed_version = _composer_with_a_ledger_read_gone_stale(api)

        fresh_version = composer_version(api, composer["id"])
        assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], fresh_version), ACCOUNTANT_ONE
            )
        )

        after = read_composer(api, composer["id"])
        assert after["version"] == fresh_version + 1
        assert_composer_money(
            after,
            accrued_unpaid_cents=0,
            outstanding_advance_cents=0,
            lifetime_paid_cents=0,
        )


# ---------------------------------------------------------------------------
# Version movement on a composition: writes move it, reads do not
# ---------------------------------------------------------------------------


class TestCompositionVersionMovesOnlyOnWrites:
    def test_metadata_revision_increments_the_version_and_leaves_both_axes_alone(self, api):
        """PRD §3.2: "Metadata can be corrected in place: a `CatalogAdmin` may revise
        `title`, `tempo_bpm`, `genre`, `mood_tags` and `instrumentation`, which refreshes
        `updated_at` and increments `version`."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_writes_and_holds_still_on_reads
        """
        ground = _accepted_film_request_on_a_cataloged_work(api)
        composition_id = ground["composition"]["id"]

        before = read_composition(api, composition_id)
        assert before["version"] == 2, "one ingest write plus one catalogue write"

        patched = assert_ok(
            api.update_composition(
                composition_id,
                {"title": "Harbour Lights (Trailer Mix)", "tempo_bpm": 132},
                CATALOG_ADMIN,
            )
        )
        assert patched["version"] == 3
        assert patched["title"] == "Harbour Lights (Trailer Mix)"
        assert patched["tempo_bpm"] == 132
        assert_composition_axes(patched, "CATALOGED", "AVAILABLE")

    def test_reads_of_the_work_never_advance_its_version(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation, and `version`, an integer that starts at 1
        when the row is created and increases by exactly 1 on every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_writes_and_holds_still_on_reads
        """
        ground = _accepted_film_request_on_a_cataloged_work(api)
        composition_id = ground["composition"]["id"]

        assert_ok(
            api.update_composition(
                composition_id,
                {"title": "Harbour Lights (Trailer Mix)", "tempo_bpm": 132},
                CATALOG_ADMIN,
            )
        )
        assert read_composition(api, composition_id)["version"] == 3
        rows, _meta = assert_page(
            api.list_compositions({"composer_id": ground["composer"]["id"]}, CATALOG_ADMIN)
        )
        assert rows[0]["version"] == 3, "a filtered list is a read like any other"

        assert_created(
            api.create_license(
                build.per_use_license_payload(ground["sync_request"]["id"], 3), LICENSING_AGENT
            )
        )
        assert read_composition(api, composition_id)["version"] == 4
        reread = assert_ok(api.get_composition(composition_id, RIGHTS_MANAGER))
        assert reread["version"] == 4, "a second read from another role must not move it"

    def test_guarded_issuance_increments_the_parent_composition_version(self, api):
        """PRD §2.10: "Every successful issuance increments the composition's `version`."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_writes_and_holds_still_on_reads
        """
        ground = _accepted_film_request_on_a_cataloged_work(api)
        composition_id = ground["composition"]["id"]
        observed_version = composition_version(api, composition_id)

        license_row = assert_created(
            api.create_license(
                build.per_use_license_payload(ground["sync_request"]["id"], observed_version),
                LICENSING_AGENT,
            )
        )
        assert_status(license_row, "ISSUED")
        assert_cents_equal(license_row["final_fee_cents"], 1254000, "final_fee_cents")

        after = read_composition(api, composition_id)
        assert after["version"] == observed_version + 1
        assert after["active_license_count"] == 1


# ---------------------------------------------------------------------------
# Derived figures reconcile from their declared input sets
# ---------------------------------------------------------------------------


class TestDerivedFiguresReconcileAcrossSourceMovements:
    def test_lifetime_performance_credits_counts_only_filed_cue_sheets(self, api, clock_origin):
        """PRD §3.2: "`lifetime_performance_credits` is the sum, over cue sheets in
        `REGISTERED` or `ACCEPTED_BY_SOCIETY`, of the credits that sheet attributes to
        this work, carried at 2 decimals."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_source_insert_registration_and_settlement
        """
        ground = _issued_film_license(api)
        composition_id = ground["composition"]["id"]

        before = read_composition(api, composition_id)
        assert before["active_license_count"] == 1
        assert before["open_claim_count"] == 0
        assert_credits_equal(before["lifetime_performance_credits"], 0.00)
        assert_composition_axes(before, "CATALOGED", "AVAILABLE")

        sheet = assert_created(
            api.create_cue_sheet(
                build.cue_sheet_payload(
                    [build.cue(composition_id, "THEME", 30)],
                    license_id=ground["license"]["id"],
                    production_title="Harbour Lights Trailer",
                    market_tier="NETWORK",
                ),
                LICENSING_AGENT,
            )
        )
        assert_status(sheet, "COLLECTED")
        assert_credits_equal(sheet["total_credits"], 1.00, "total_credits")
        assert_credits_equal(
            sheet["credits_by_composition"][composition_id], 1.00, "credits_by_composition"
        )
        assert_credits_equal(
            read_composition(api, composition_id)["lifetime_performance_credits"],
            0.00,
            "credits from a COLLECTED sheet",
        )

        registered = assert_ok(
            api.register_cue_sheet(
                sheet["id"], {"society_reference": "ASCAP-2026-000001"}, RIGHTS_MANAGER
            )
        )
        assert_status(registered, "REGISTERED")
        assert registered["registration_round"] == 1
        assert_credits_equal(
            read_composition(api, composition_id)["lifetime_performance_credits"],
            1.00,
            "credits from a REGISTERED sheet",
        )

        accepted = assert_ok(
            api.record_society_decision(sheet["id"], {"decision": "ACCEPT"}, RIGHTS_MANAGER)
        )
        assert_status(accepted, "ACCEPTED_BY_SOCIETY")
        assert_credits_equal(
            read_composition(api, composition_id)["lifetime_performance_credits"],
            1.00,
            "acceptance must not double the credits",
        )

        performance = assert_single_ledger_entry(
            ledger_entries(api, ground["composer"]["id"]), "PERFORMANCE", 625, sheet["id"]
        )
        assert_three_fraction_timestamp(performance["cash_recognized_at"])
        assert_same_instant(performance["cash_recognized_at"], clock_origin)

    def test_open_claim_count_ignores_a_detection_and_a_detected_claim(self, api):
        """PRD §3.2: "`open_claim_count` is the number of claims on this work in
        `NOTICED` or `DISPUTED`."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_source_insert_registration_and_settlement
        """
        work = new_cataloged_work(api)
        composition_id = work.composition_id

        match = assert_created(
            api.create_fingerprint_match(
                build.fingerprint_match_payload(
                    composition_id,
                    source_platform="UGC_VIDEO",
                    source_reference="ugc://clip/88421",
                    matched_seconds=120,
                    confidence_pct=99.0,
                ),
                CATALOG_ADMIN,
            )
        )
        assert_thin_record_fields(match)
        after_match = read_composition(api, composition_id)
        assert after_match["open_claim_count"] == 0, "a detection alone is not a claim"
        assert_composition_axes(after_match, "CATALOGED", "AVAILABLE")

        claim = assert_created(
            api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
        )
        assert_status(claim, "DETECTED")
        assert_cents_equal(claim["statutory_amount_cents"], 120000, "statutory_amount_cents")
        assert_cents_equal(claim["settlement_floor_cents"], 36000, "settlement_floor_cents")
        after_claim = read_composition(api, composition_id)
        assert after_claim["open_claim_count"] == 0, "DETECTED is outside NOTICED and DISPUTED"
        assert_composition_axes(after_claim, "CATALOGED", "AVAILABLE")

        noticed = assert_ok(
            api.notice_claim(claim["id"], {"notice_channel": "DMCA_WEBFORM"}, RIGHTS_MANAGER)
        )
        assert_status(noticed, "NOTICED")
        after_notice = read_composition(api, composition_id)
        assert after_notice["open_claim_count"] == 1
        assert_composition_axes(after_notice, "CATALOGED", "RESTRICTED")

    def test_settlement_recomputes_the_count_downward_and_restores_availability(self, api):
        """PRD §3.8: "Settlement finally returns the work from `RESTRICTED` to
        `AVAILABLE`, but only once `open_claim_count` has reached 0 — a second open claim
        on the same work keeps it restricted."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_source_insert_registration_and_settlement
        """
        work = new_cataloged_work(api)
        composition_id = work.composition_id

        _match, _claim, settled = _notice_and_settle_a_ugc_detection(api, composition_id)
        assert_status(settled, "SETTLED")
        assert_cents_equal(settled["settlement_amount_cents"], 120000, "settlement_amount_cents")
        assert settled["settlement_basis"] == "STATUTORY"
        assert settled["settlement_collected"] is True

        after = read_composition(api, composition_id)
        assert after["open_claim_count"] == 0
        assert_composition_axes(after, "CATALOGED", "AVAILABLE")

    def test_accrued_unpaid_cents_sums_the_three_unswept_recognitions(self, api):
        """PRD §3.1: "`accrued_unpaid_cents` is the sum of the signed amounts of every
        ledger entry belonging to this composer that has not yet been swept into a
        statement and whose economic origin is neither an advance nor an advance
        recoupment."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_source_insert_registration_and_settlement
        """
        ground = _issued_film_license(api)
        composition_id = ground["composition"]["id"]
        composer_id = ground["composer"]["id"]

        sheet = assert_created(
            api.create_cue_sheet(
                build.cue_sheet_payload(
                    [build.cue(composition_id, "THEME", 30)],
                    license_id=ground["license"]["id"],
                    production_title="Harbour Lights Trailer",
                    market_tier="NETWORK",
                ),
                LICENSING_AGENT,
            )
        )
        assert_ok(
            api.register_cue_sheet(
                sheet["id"], {"society_reference": "ASCAP-2026-000001"}, RIGHTS_MANAGER
            )
        )
        _match, claim, settled = _notice_and_settle_a_ugc_detection(api, composition_id)
        assert_cents_equal(settled["composer_share_cents"], 48000, "composer_share_cents")

        entries = ledger_entries(api, composer_id)
        assert_single_ledger_entry(entries, "SYNC_FEE", 501600, ground["license"]["id"])
        assert_single_ledger_entry(entries, "PERFORMANCE", 625, sheet["id"])
        assert_single_ledger_entry(entries, "SETTLEMENT", 48000, claim["id"])
        assert_composer_money(read_composer(api, composer_id), accrued_unpaid_cents=550225)
