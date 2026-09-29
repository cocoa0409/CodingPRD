"""Every declared error identifier answered from the request that provokes it.

The catalogue is deliberately fine-grained: each addressed entity owns its own
not-found identifier, each state machine owns its own state-invalid identifier,
and the shape guards that sit beside the schema pass own identifiers of their
own. These tests provoke each identifier from the smallest request that can
reach it, and check that the refused request left no trace behind.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    ACCOUNTANT_TWO,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    accept_sync_request,
    activate_license,
    assert_cents_equal,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_pct_equal,
    assert_same_instant,
    assert_statement_figures,
    assert_status,
    composition_version,
    finalize_statement,
    issue_per_use_license,
    ledger_entries,
    make_composer_headers,
    make_licensee_headers,
    new_active_agreement,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_cue_sheet,
    new_detected_claim,
    new_draft_agreement,
    new_draft_statement,
    new_fingerprint_match,
    new_issued_deal,
    new_licensee,
    new_noticed_claim,
    new_quoted_deal,
    new_tier,
    open_usage_report,
    quote_sync_request,
    read_agreement,
    read_claim,
    read_composer,
    read_composition,
    read_cue_sheet,
    read_statement,
    read_usage_report,
    review_sync_request,
    select_ledger_entries,
    submit_sync_request,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_ACTIVE_CLAIM_BLOCKS_LICENSE,
    ERR_AGREEMENT_STATE_INVALID,
    ERR_AMENDMENT_LIMIT_REACHED,
    ERR_BLANKET_AGREEMENT_NOT_FOUND,
    ERR_BLANKET_STATE_INVALID,
    ERR_CLAIM_STATE_INVALID,
    ERR_COMPOSER_AGREEMENT_NOT_FOUND,
    ERR_COMPOSER_NOT_AFFILIATED,
    ERR_COMPOSER_NOT_FOUND,
    ERR_COMPOSITION_HAS_ACTIVE_LICENSES,
    ERR_COMPOSITION_NOT_FOUND,
    ERR_COMPOSITION_STATE_INVALID,
    ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD,
    ERR_CONFIDENCE_BELOW_NOTICE_THRESHOLD,
    ERR_COVERAGE_DATES_INVALID,
    ERR_CUE_SHEET_HAS_NO_CREDITS,
    ERR_CUE_SHEET_NOT_FOUND,
    ERR_CUE_SHEET_STATE_INVALID,
    ERR_FINGERPRINT_MATCH_NOT_FOUND,
    ERR_INFRINGEMENT_CLAIM_NOT_FOUND,
    ERR_LEDGER_SOURCE_NOT_MANUAL,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSE_STATE_INVALID,
    ERR_LICENSE_TIER_NOT_FOUND,
    ERR_LICENSEE_NOT_FOUND,
    ERR_MATCH_ALREADY_CLAIMED,
    ERR_REPORT_HAS_NO_CUE_SHEETS,
    ERR_REPORT_STATE_INVALID,
    ERR_REVISION_LIMIT_REACHED,
    ERR_ROYALTY_LEDGER_ENTRY_NOT_FOUND,
    ERR_ROYALTY_STATEMENT_NOT_FOUND,
    ERR_SEARCH_PROFILE_NOT_FOUND,
    ERR_SETTLEMENT_BELOW_FLOOR,
    ERR_STATEMENT_NOT_PAYABLE,
    ERR_STATEMENT_STATE_INVALID,
    ERR_TIER_CODE_DUPLICATE,
    ERR_USAGE_REPORT_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WEIGHTS_NOT_100,
)

# Identifiers that are well-formed but match no row in a freshly launched service.
MISSING_ID = "00000000-0000-0000-0000-0000000000aa"
SECOND_MISSING_ID = "00000000-0000-0000-0000-0000000000ab"


class TestEveryNotFoundIdentifierBelongsToItsOwnEntity:
    def test_each_addressed_entity_answers_with_its_own_not_found_identifier(self, api):
        """PRD §2.7: "Identifiers in a URL path are resolved strictly left to right,
        and the request fails on the first identifier that matches no row, with the
        404 belonging to that entity."

        Design: Corner/errors/every_declared_not_found_id_is_reachable_from_its_own_path
        """
        probes = (
            (api.get_composer(MISSING_ID, CATALOG_ADMIN), ERR_COMPOSER_NOT_FOUND),
            (
                api.get_composer_agreement(MISSING_ID, RIGHTS_MANAGER),
                ERR_COMPOSER_AGREEMENT_NOT_FOUND,
            ),
            (api.get_composition(MISSING_ID, CATALOG_ADMIN), ERR_COMPOSITION_NOT_FOUND),
            (api.get_licensee(MISSING_ID, LICENSING_AGENT), ERR_LICENSEE_NOT_FOUND),
            (api.get_license_tier(MISSING_ID, LICENSING_AGENT), ERR_LICENSE_TIER_NOT_FOUND),
            (api.get_license(MISSING_ID, LICENSING_AGENT), ERR_LICENSE_NOT_FOUND),
            (
                api.get_blanket_agreement(MISSING_ID, LICENSING_AGENT),
                ERR_BLANKET_AGREEMENT_NOT_FOUND,
            ),
            (api.get_usage_report(MISSING_ID, RIGHTS_MANAGER), ERR_USAGE_REPORT_NOT_FOUND),
            (api.get_cue_sheet(MISSING_ID, RIGHTS_MANAGER), ERR_CUE_SHEET_NOT_FOUND),
            (
                api.get_fingerprint_match(MISSING_ID, CATALOG_ADMIN),
                ERR_FINGERPRINT_MATCH_NOT_FOUND,
            ),
            (
                api.get_infringement_claim(MISSING_ID, RIGHTS_MANAGER),
                ERR_INFRINGEMENT_CLAIM_NOT_FOUND,
            ),
            (
                api.get_royalty_statement(MISSING_ID, ACCOUNTANT_ONE),
                ERR_ROYALTY_STATEMENT_NOT_FOUND,
            ),
            (
                api.get_royalty_ledger_entry(MISSING_ID, ACCOUNTANT_ONE),
                ERR_ROYALTY_LEDGER_ENTRY_NOT_FOUND,
            ),
        )
        for response, error_id in probes:
            assert_declared_error(response, error_id)

    def test_the_singleton_search_profile_answers_before_it_has_ever_been_written(self, api):
        """PRD §2.7: "The singleton search profile has its own: reading the profile, or
        running a facet search, before the profile has ever been written yields
        `ERR_SEARCH_PROFILE_NOT_FOUND` (404)."

        Design: Corner/errors/every_declared_not_found_id_is_reachable_from_its_own_path
        """
        assert_declared_error(api.get_search_profile(CATALOG_ADMIN), ERR_SEARCH_PROFILE_NOT_FOUND)

    def test_body_foreign_keys_are_resolved_in_the_order_the_entity_declares_them(self, api):
        """PRD §2.7: "Foreign keys carried in a request body are resolved after path
        identifiers and before any authorization, state or business check, in the field
        order in which the receiving entity declares them."

        Design: Corner/errors/every_declared_not_found_id_is_reachable_from_its_own_path
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")

        orphan_agreement = build.composition_payload(
            composer["id"],
            MISSING_ID,
            title="Orphan Cue",
            duration_sec=90,
            tempo_bpm=100,
            genre="CINEMATIC",
            mood_tags=["CALM"],
            instrumentation=["PIANO"],
        )
        assert_declared_error(
            api.create_composition(orphan_agreement, CATALOG_ADMIN),
            ERR_COMPOSER_AGREEMENT_NOT_FOUND,
        )

        both_missing = dict(orphan_agreement, composer_id=SECOND_MISSING_ID)
        assert_declared_error(
            api.create_composition(both_missing, CATALOG_ADMIN), ERR_COMPOSER_NOT_FOUND
        )

        _rows, meta = assert_page(api.list_compositions({}, CATALOG_ADMIN))
        assert meta["total_count"] == 0, "a refused create writes no composition row"


def _one_row_in_seven_state_machines(api):
    """A DRAFT agreement, a CATALOGED work, an ACTIVE licence, an ACTIVE blanket
    agreement, a DUE report, a COLLECTED cue sheet and a DETECTED claim."""
    idle_composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    draft_agreement = new_draft_agreement(api, idle_composer["id"])

    work = new_cataloged_work(
        api,
        {"display_name": "Tomas Reyes", "pro_affiliation": "BMI"},
        None,
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )

    deal = Deal(work, tier, licensee)
    submit_sync_request(
        api,
        deal,
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-08-01T00:00:00Z",
        requested_term_months=12,
    )
    review_sync_request(api, deal)
    quote_sync_request(api, deal, 14)
    accept_sync_request(api, deal)
    issue_per_use_license(api, deal)
    activate_license(api, deal)

    blanket = new_active_blanket(api, licensee, usage_cap_minutes=60)
    open_usage_report(api, blanket)

    cue_sheet = new_cue_sheet(
        api,
        [build.cue(work.composition_id, "THEME", 30)],
        license_id=deal.license_id,
        production_title="Evening Bulletin",
        broadcast_date="2026-08-12T00:00:00Z",
        market_tier="NETWORK",
    )
    _match, claim = new_detected_claim(
        api,
        work.composition_id,
        source_platform="UGC_VIDEO",
        source_reference="vid-77120",
        matched_seconds=45,
        confidence_pct=96.0,
    )

    return {
        "idle_composer": idle_composer,
        "draft_agreement": draft_agreement,
        "work": work,
        "deal": deal,
        "blanket": blanket,
        "cue_sheet": cue_sheet,
        "claim": claim,
    }


class TestStateInvalidFamilyIsEntitySpecific:
    def test_each_state_machine_answers_with_its_own_state_invalid_identifier(self, api):
        """PRD §2.6: "**Target state precondition** — on every action endpoint that
        drives a state machine: the target row's state field is not among the states the
        transition accepts → the entity's state-invalid error (409), namely
        `ERR_AGREEMENT_STATE_INVALID`, `ERR_COMPOSITION_STATE_INVALID`,
        `ERR_SYNC_REQUEST_STATE_INVALID`, `ERR_LICENSE_STATE_INVALID`,
        `ERR_BLANKET_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
        `ERR_CUE_SHEET_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or
        `ERR_STATEMENT_STATE_INVALID`."

        Design: Corner/errors/state_invalid_family_is_entity_specific_across_eight_machines
        """
        ground = _one_row_in_seven_state_machines(api)
        idle_composer = ground["idle_composer"]
        work = ground["work"]
        version_before = composition_version(api, work.composition_id)

        assert_declared_error(
            api.sign_agreement(
                ground["draft_agreement"]["id"],
                {"signature_name": "Nadia Okoro"},
                make_composer_headers(idle_composer["id"]),
            ),
            ERR_AGREEMENT_STATE_INVALID,
        )
        assert_declared_error(
            api.catalog_composition(work.composition_id, None, CATALOG_ADMIN),
            ERR_COMPOSITION_STATE_INVALID,
        )
        assert_declared_error(
            api.activate_license(ground["deal"].license_id, None, LICENSING_AGENT),
            ERR_LICENSE_STATE_INVALID,
        )
        assert_declared_error(
            api.activate_blanket_agreement(
                ground["blanket"].agreement_id, None, LICENSING_AGENT
            ),
            ERR_BLANKET_STATE_INVALID,
        )
        assert_declared_error(
            api.accept_usage_report(ground["blanket"].usage_report_id, None, RIGHTS_MANAGER),
            ERR_REPORT_STATE_INVALID,
        )
        assert_declared_error(
            api.record_society_decision(
                ground["cue_sheet"]["id"], {"decision": "ACCEPT"}, RIGHTS_MANAGER
            ),
            ERR_CUE_SHEET_STATE_INVALID,
        )
        assert_declared_error(
            api.dispute_claim(
                ground["claim"]["id"],
                {"dispute_note": "Licensee claims a valid blanket"},
                RIGHTS_MANAGER,
            ),
            ERR_CLAIM_STATE_INVALID,
        )

        assert_status(read_agreement(api, ground["draft_agreement"]["id"]), "DRAFT")
        assert composition_version(api, work.composition_id) == version_before, (
            "a refused catalogue attempt may not bump the work's version"
        )
        report = read_usage_report(api, ground["blanket"].usage_report_id)
        assert_status(report, "DUE")
        assert report["pool_allocations"] == [], "a refused acceptance computes no pool"
        assert_status(read_cue_sheet(api, ground["cue_sheet"]["id"]), "COLLECTED")
        assert_status(read_claim(api, ground["claim"]["id"]), "DETECTED")

    def test_paying_a_draft_statement_answers_the_state_error_not_the_payability_error(
        self, api
    ):
        """PRD §3.9: "Finalizing twice, paying a `DRAFT` statement, or acting at all on a
        `PAID` one, is refused with `ERR_STATEMENT_STATE_INVALID`."

        Design: Corner/errors/state_invalid_family_is_entity_specific_across_eight_machines
        """
        composer = new_composer(api, display_name="Tomas Reyes", pro_affiliation="BMI")
        statement = new_draft_statement(
            api,
            composer["id"],
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
        )

        assert_declared_error(
            api.pay_royalty_statement(
                statement["id"], {"payment_reference": "wire-0001"}, ACCOUNTANT_ONE
            ),
            ERR_STATEMENT_STATE_INVALID,
        )
        assert_status(read_statement(api, statement["id"]), "DRAFT")


class TestNegotiationRoundCapsRefuseTheFourthAttempt:
    def test_a_fourth_revision_is_refused_and_leaves_the_quote_standing(self, api):
        """PRD §3.4: "The request is refused with `ERR_REVISION_LIMIT_REACHED` once
        `revision_round` has reached 3."

        Design: Corner/errors/revision_and_amendment_round_caps_refuse_the_fourth_attempt
        """
        deal = new_quoted_deal(
            api,
            {
                "composer_overrides": {
                    "display_name": "Nadia Okoro",
                    "pro_affiliation": "ASCAP",
                },
                "title": "Harbour Lights",
                "duration_sec": 180,
                "tempo_bpm": 130,
            },
            {
                "code": "FILM-STD",
                "media_type": "FILM",
                "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
                "base_rate_cents": 600000,
            },
            {
                "legal_name": "Northwind Pictures",
                "licensee_type": "PRODUCTION_COMPANY",
                "credit_limit_cents": 90000000,
            },
            14,
            media_type="FILM",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        )

        rounds = (
            ("Shorten the term", {"revised_term_months": 6}),
            ("Drop to local", {"revised_distribution_scale": "LOCAL"}),
            ("Back to national", {"revised_distribution_scale": "NATIONAL"}),
        )
        for expected_round, (note, revision) in enumerate(rounds, start=1):
            revised = assert_ok(
                api.request_sync_revision(
                    deal.sync_request_id,
                    build.revision_payload(note, **revision),
                    deal.licensee_headers,
                )
            )
            assert_status(revised, "REVISION_REQUESTED")
            assert revised["revision_round"] == expected_round
            assert_ok(
                api.quote_sync_request(
                    deal.sync_request_id, build.quote_payload(14), LICENSING_AGENT
                )
            )

        assert_declared_error(
            api.request_sync_revision(
                deal.sync_request_id,
                build.revision_payload("One more look", revised_term_months=12),
                deal.licensee_headers,
            ),
            ERR_REVISION_LIMIT_REACHED,
        )

        reread = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
        assert_status(reread, "QUOTED")
        assert reread["revision_round"] == 3, "a refused revision consumes no round"

    def test_a_fifth_proposal_is_refused_because_only_acceptance_consumes_a_round(self, api):
        """PRD §3.1: "The proposed writer and publisher shares must themselves add to
        exactly 100.00, again on pain of `ERR_SHARE_SPLIT_NOT_100`, and the amendment is
        refused with `ERR_AMENDMENT_LIMIT_REACHED` when `amendment_round` has already
        reached 3."

        Design: Corner/errors/revision_and_amendment_round_caps_refuse_the_fourth_attempt
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
        agreement = new_active_agreement(api, composer["id"], sync_fee_share_pct=40.00)
        composer_headers = make_composer_headers(composer["id"])

        def propose(writer, publisher, sync):
            return api.create_amendment(
                agreement["id"],
                build.amendment_payload(
                    proposed_writer_share_pct=writer,
                    proposed_publisher_share_pct=publisher,
                    proposed_sync_fee_share_pct=sync,
                ),
                RIGHTS_MANAGER,
            )

        def decide(decision):
            return assert_ok(
                api.decide_amendment(
                    agreement["id"], {"decision": decision}, composer_headers
                )
            )

        assert_ok(propose(55.00, 45.00, 42.00))
        accepted = decide("ACCEPT")
        assert_status(accepted, "ACTIVE")
        assert_pct_equal(accepted["writer_share_pct"], 55.00, "writer_share_pct")
        assert_pct_equal(accepted["sync_fee_share_pct"], 42.00, "sync_fee_share_pct")
        assert accepted["amendment_round"] == 1
        for field in (
            "pending_writer_share_pct",
            "pending_publisher_share_pct",
            "pending_sync_fee_share_pct",
            "pending_holdback_days",
        ):
            assert accepted[field] is None, f"{field} must be cleared after a decision"

        assert_ok(propose(70.00, 30.00, 60.00))
        rejected = decide("REJECT")
        assert_status(rejected, "ACTIVE")
        assert_pct_equal(rejected["writer_share_pct"], 55.00, "writer_share_pct")
        assert rejected["amendment_round"] == 1, "a rejected proposal consumes no round"

        assert_ok(propose(60.00, 40.00, 45.00))
        second = decide("ACCEPT")
        assert second["amendment_round"] == 2
        assert_pct_equal(second["writer_share_pct"], 60.00, "writer_share_pct")

        assert_ok(propose(65.00, 35.00, 50.00))
        third = decide("ACCEPT")
        assert third["amendment_round"] == 3
        assert_pct_equal(third["writer_share_pct"], 65.00, "writer_share_pct")

        assert_declared_error(propose(50.00, 50.00, 40.00), ERR_AMENDMENT_LIMIT_REACHED)

        final = read_agreement(api, agreement["id"])
        assert_status(final, "ACTIVE")
        assert final["amendment_round"] == 3
        assert_pct_equal(final["writer_share_pct"], 65.00, "writer_share_pct")
        assert_pct_equal(final["publisher_share_pct"], 35.00, "publisher_share_pct")
        assert_pct_equal(final["sync_fee_share_pct"], 50.00, "sync_fee_share_pct")


def _work_for_detection(api):
    """A catalogued work under an ACTIVE agreement, ready to be detected on."""
    return new_cataloged_work(
        api,
        {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )


class TestClaimConfidenceDuplicateAndSettlementGuards:
    def test_confidence_below_seventy_cannot_open_a_claim_at_all(self, api):
        """PRD §3.8: "The match's `confidence_pct` must be at least 70.0, and a lower
        confidence is refused with `ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD`."

        Design: Corner/errors/claim_confidence_duplicate_and_settlement_floor_guards_all_fire
        """
        work = _work_for_detection(api)
        low = new_fingerprint_match(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-low",
            matched_seconds=30,
            confidence_pct=65.0,
        )

        assert_declared_error(
            api.create_infringement_claim({"fingerprint_match_id": low["id"]}, RIGHTS_MANAGER),
            ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD,
        )
        _rows, meta = assert_page(api.list_infringement_claims({}, RIGHTS_MANAGER))
        assert meta["total_count"] == 0, "a refused claim writes no row"

        mid = new_fingerprint_match(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-mid",
            matched_seconds=30,
            confidence_pct=84.9,
        )
        claim = assert_created(
            api.create_infringement_claim({"fingerprint_match_id": mid["id"]}, RIGHTS_MANAGER)
        )
        assert_status(claim, "DETECTED")

    def test_confidence_that_opened_a_claim_can_still_be_too_low_for_notice(self, api):
        """PRD §3.8: "Notice demands more confidence than claim creation did:
        `confidence_pct` must be at least 85.0, and anything lower is refused with
        `ERR_CONFIDENCE_BELOW_NOTICE_THRESHOLD`."

        Design: Corner/errors/claim_confidence_duplicate_and_settlement_floor_guards_all_fire
        """
        work = _work_for_detection(api)
        _match, claim = new_detected_claim(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-mid",
            matched_seconds=30,
            confidence_pct=84.9,
        )

        assert_declared_error(
            api.notice_claim(claim["id"], {"notice_channel": "EMAIL"}, RIGHTS_MANAGER),
            ERR_CONFIDENCE_BELOW_NOTICE_THRESHOLD,
        )
        assert_status(read_claim(api, claim["id"]), "DETECTED")
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "AVAILABLE"
        )

    def test_a_second_claim_on_the_same_detection_is_refused(self, api):
        """PRD §3.8: "And no other claim may already cite the same match, on pain of
        `ERR_MATCH_ALREADY_CLAIMED`."

        Design: Corner/errors/claim_confidence_duplicate_and_settlement_floor_guards_all_fire
        """
        work = _work_for_detection(api)
        match, _claim = new_detected_claim(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-mid",
            matched_seconds=30,
            confidence_pct=84.9,
        )

        assert_declared_error(
            api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER),
            ERR_MATCH_ALREADY_CLAIMED,
        )
        _rows, meta = assert_page(api.list_infringement_claims({}, RIGHTS_MANAGER))
        assert meta["total_count"] == 1, "the duplicate claim writes no second row"

    def test_a_negotiated_settlement_must_reach_the_floor_or_name_no_amount_at_all(self, api):
        """PRD §3.8: "On the negotiated basis it is `negotiated_amount_cents`, which must
        be at least `settlement_floor_cents` — equality is accepted — and a lower amount,
        or a negotiated basis with the amount omitted altogether, is refused with
        `ERR_SETTLEMENT_BELOW_FLOOR`."

        Design: Corner/errors/claim_confidence_duplicate_and_settlement_floor_guards_all_fire
        """
        work = _work_for_detection(api)
        new_detected_claim(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-mid",
            matched_seconds=30,
            confidence_pct=84.9,
        )
        _high_match, high_claim = new_noticed_claim(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-high",
            matched_seconds=45,
            confidence_pct=96.0,
        )
        assert_status(high_claim, "NOTICED")
        restricted = read_composition(api, work.composition_id)
        assert_composition_axes(restricted, "CATALOGED", "RESTRICTED")
        assert restricted["open_claim_count"] == 1, "only NOTICED claims are counted open"

        assert_declared_error(
            api.settle_claim(
                high_claim["id"],
                build.settle_claim_payload("NEGOTIATED", negotiated_amount_cents=1),
                RIGHTS_MANAGER,
            ),
            ERR_SETTLEMENT_BELOW_FLOOR,
        )
        assert_declared_error(
            api.settle_claim(
                high_claim["id"], build.settle_claim_payload("NEGOTIATED"), RIGHTS_MANAGER
            ),
            ERR_SETTLEMENT_BELOW_FLOOR,
        )
        assert_status(read_claim(api, high_claim["id"]), "NOTICED")

        settled = assert_ok(
            api.settle_claim(
                high_claim["id"], build.settle_claim_payload("STATUTORY"), RIGHTS_MANAGER
            )
        )
        assert_status(settled, "SETTLED")
        assert_cents_equal(
            settled["settlement_amount_cents"],
            settled["statutory_amount_cents"],
            "settlement_amount_cents",
        )

        released = read_composition(api, work.composition_id)
        assert_composition_axes(released, "CATALOGED", "AVAILABLE")
        assert released["open_claim_count"] == 0, "a DETECTED claim never counted as open"


class TestRegistrationAndSubmissionGates:
    def test_a_sheet_whose_credits_round_to_zero_cannot_be_registered(self, api):
        """PRD §3.7: "It is reachable from `COLLECTED` and from `REJECTED_BY_SOCIETY`,
        both landing in `REGISTERED`, and is guarded twice: `total_credits` must be
        greater than 0.00, otherwise `ERR_CUE_SHEET_HAS_NO_CREDITS`, and every cited
        work's composer must have a `pro_affiliation` other than `NONE`, otherwise
        `ERR_COMPOSER_NOT_AFFILIATED` — an unaffiliated writer cannot be registered
        anywhere."

        Design: Corner/errors/registration_gates_require_credits_affiliation_and_at_least_one_sheet
        """
        deal = new_issued_deal(
            api,
            {
                "composer_overrides": {
                    "display_name": "Nadia Okoro",
                    "pro_affiliation": "ASCAP",
                },
                "title": "Harbour Lights",
            },
            {
                "code": "FILM-STD",
                "media_type": "FILM",
                "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
                "base_rate_cents": 600000,
            },
            {
                "legal_name": "Meridian Broadcasting",
                "licensee_type": "BROADCASTER",
                "credit_limit_cents": 10000000,
            },
            media_type="FILM",
            distribution_scale="NATIONAL",
        )

        sheet = new_cue_sheet(
            api,
            [build.cue(deal.composition_id, "LOGO", 1)],
            license_id=deal.license_id,
            production_title="Station Ident",
            broadcast_date="2026-08-05T00:00:00Z",
            market_tier="DIGITAL",
        )
        assert sheet["total_seconds"] == 1
        assert_credits_equal(sheet["total_credits"], 0.00, "total_credits")

        assert_declared_error(
            api.register_cue_sheet(
                sheet["id"], {"society_reference": "ASCAP-2026-0001"}, RIGHTS_MANAGER
            ),
            ERR_CUE_SHEET_HAS_NO_CREDITS,
        )
        assert_status(read_cue_sheet(api, sheet["id"]), "COLLECTED")

    def test_a_sheet_citing_an_unaffiliated_writer_cannot_be_registered(self, api):
        """PRD §3.7: "It is reachable from `COLLECTED` and from `REJECTED_BY_SOCIETY`,
        both landing in `REGISTERED`, and is guarded twice: `total_credits` must be
        greater than 0.00, otherwise `ERR_CUE_SHEET_HAS_NO_CREDITS`, and every cited
        work's composer must have a `pro_affiliation` other than `NONE`, otherwise
        `ERR_COMPOSER_NOT_AFFILIATED` — an unaffiliated writer cannot be registered
        anywhere."

        Design: Corner/errors/registration_gates_require_credits_affiliation_and_at_least_one_sheet
        """
        unaffiliated = new_cataloged_work(
            api,
            {"display_name": "Iris Vandenberg", "pro_affiliation": "NONE"},
            None,
            title="Unregistered Pulse",
            duration_sec=120,
            tempo_bpm=105,
            genre="ELECTRONIC",
            mood_tags=["TENSE"],
            instrumentation=["SYNTH"],
        )
        blanket = new_active_blanket(api, usage_cap_minutes=60)
        open_usage_report(api, blanket)

        sheet = new_cue_sheet(
            api,
            [build.cue(unaffiliated.composition_id, "THEME", 30)],
            usage_report_id=blanket.usage_report_id,
            production_title="Late Feature",
            broadcast_date="2026-08-06T00:00:00Z",
            market_tier="NETWORK",
        )
        assert_credits_equal(sheet["total_credits"], 1.00, "total_credits")

        assert_declared_error(
            api.register_cue_sheet(
                sheet["id"], {"society_reference": "ASCAP-2026-0002"}, RIGHTS_MANAGER
            ),
            ERR_COMPOSER_NOT_AFFILIATED,
        )
        assert_status(read_cue_sheet(api, sheet["id"]), "COLLECTED")
        assert (
            select_ledger_entries(
                ledger_entries(api, unaffiliated.composer_id), source_type="PERFORMANCE"
            )
            == []
        ), "a refused registration recognizes no performance money"

    def test_a_report_carrying_no_cue_sheet_cannot_be_submitted(self, api):
        """PRD §3.6: "Submission is reachable from `DUE` and from `REJECTED`, both landing
        in `SUBMITTED`, and requires at least one cue sheet to be attached to the report,
        otherwise `ERR_REPORT_HAS_NO_CUE_SHEETS`."

        Design: Corner/errors/registration_gates_require_credits_affiliation_and_at_least_one_sheet
        """
        work = new_cataloged_work(
            api,
            {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
            None,
            title="Harbour Lights",
        )
        blanket = new_active_blanket(api, usage_cap_minutes=60)
        open_usage_report(api, blanket)
        august_report = blanket.usage_report
        september_report = assert_created(
            api.create_usage_report(
                build.usage_report_payload(
                    blanket.agreement_id,
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-30T00:00:00Z",
                ),
                LICENSING_AGENT,
            )
        )
        new_cue_sheet(
            api,
            [build.cue(work.composition_id, "THEME", 30)],
            usage_report_id=august_report["id"],
            production_title="Evening Bulletin",
            broadcast_date="2026-08-07T00:00:00Z",
            market_tier="NETWORK",
        )

        licensee_headers = make_licensee_headers(blanket.licensee_id)
        assert_declared_error(
            api.submit_usage_report(september_report["id"], None, licensee_headers),
            ERR_REPORT_HAS_NO_CUE_SHEETS,
        )
        assert_status(read_usage_report(api, september_report["id"]), "DUE")

        submitted = assert_ok(
            api.submit_usage_report(august_report["id"], None, licensee_headers)
        )
        assert_status(submitted, "SUBMITTED")


class TestRetirementAndExclusivityGatesReadOtherEntities:
    def test_retirement_is_refused_while_a_licence_is_live_and_allowed_once_revoked(self, api):
        """PRD §3.2: "It is refused with `ERR_COMPOSITION_HAS_ACTIVE_LICENSES` while
        `active_license_count` is greater than 0 — a work under a live licence cannot be
        pulled."

        Design: Corner/errors/retire_and_exclusive_claim_gates_depend_on_other_entities
        """
        deal = new_issued_deal(
            api,
            {
                "composer_overrides": {
                    "display_name": "Nadia Okoro",
                    "pro_affiliation": "ASCAP",
                },
                "title": "Harbour Lights",
            },
            {
                "code": "FILM-STD",
                "media_type": "FILM",
                "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
                "base_rate_cents": 600000,
            },
            {
                "legal_name": "Northwind Pictures",
                "licensee_type": "PRODUCTION_COMPANY",
                "credit_limit_cents": 90000000,
            },
            media_type="FILM",
            distribution_scale="NATIONAL",
        )

        assert_declared_error(
            api.retire_composition(
                deal.composition_id, {"reason": "Composer requested removal"}, CATALOG_ADMIN
            ),
            ERR_COMPOSITION_HAS_ACTIVE_LICENSES,
        )
        blocked = read_composition(api, deal.composition_id)
        assert_composition_axes(blocked, "CATALOGED", "AVAILABLE")
        assert blocked["active_license_count"] == 1

        revoked = assert_ok(
            api.revoke_license(
                deal.license_id, {"reason": "Settled out of court"}, RIGHTS_MANAGER
            )
        )
        assert_status(revoked, "REVOKED")
        assert read_composition(api, deal.composition_id)["active_license_count"] == 0

        retired = assert_ok(
            api.retire_composition(
                deal.composition_id, {"reason": "Composer requested removal"}, CATALOG_ADMIN
            )
        )
        assert_composition_axes(retired, "RETIRED", "WITHDRAWN")

    def test_an_open_claim_blocks_only_the_exclusive_issuance(self, api):
        """PRD §3.5: "If the source request had `exclusive_requested` true and the work's
        `open_claim_count` is greater than 0 — that is, some claim on it sits in `NOTICED`
        or `DISPUTED` — issuance is refused with `ERR_ACTIVE_CLAIM_BLOCKS_LICENSE`;
        non-exclusive issuance on a `RESTRICTED` work remains perfectly legal."

        Design: Corner/errors/retire_and_exclusive_claim_gates_depend_on_other_entities
        """
        work = new_cataloged_work(
            api,
            {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
            {"sync_fee_share_pct": 40.00},
            title="Copper Skyline",
            duration_sec=150,
            tempo_bpm=110,
            genre="ROCK",
            mood_tags=["UPLIFTING"],
            instrumentation=["GUITAR"],
        )
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
        new_noticed_claim(
            api,
            work.composition_id,
            source_platform="BROADCAST",
            source_reference="as-run-4471",
            matched_seconds=60,
            confidence_pct=97.5,
        )
        restricted = read_composition(api, work.composition_id)
        assert_composition_axes(restricted, "CATALOGED", "RESTRICTED")
        assert restricted["open_claim_count"] == 1

        exclusive = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            exclusive,
            media_type="FILM",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
            exclusive_requested=True,
        )
        review_sync_request(api, exclusive)
        quote_sync_request(api, exclusive, 14)
        accept_sync_request(api, exclusive)

        shared = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            shared,
            media_type="FILM",
            distribution_scale="LOCAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        )
        review_sync_request(api, shared)
        quote_sync_request(api, shared, 14)
        accept_sync_request(api, shared)

        version = composition_version(api, work.composition_id)
        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(exclusive.sync_request_id, version),
                LICENSING_AGENT,
            ),
            ERR_ACTIVE_CLAIM_BLOCKS_LICENSE,
        )
        refused = assert_ok(api.get_sync_request(exclusive.sync_request_id, LICENSING_AGENT))
        assert refused["license_id"] is None, "a refused issuance links no licence"

        issued = assert_created(
            api.create_license(
                build.per_use_license_payload(shared.sync_request_id, version), LICENSING_AGENT
            )
        )
        assert_status(issued, "ISSUED")
        assert issued["is_exclusive"] is False

        reread = read_composition(api, work.composition_id)
        assert reread["exclusive_block_until"] is None, (
            "a non-exclusive licence contributes no block to the work"
        )
        assert reread["active_license_count"] == 1


class TestShapeAndUniquenessGuardsRefuseMalformedWrites:
    def test_only_the_adjustment_origin_may_be_appended_by_hand(self, api, clock_origin):
        """PRD §3.9: "A `RoyaltyAccountant` may append an entry supplying `composer_id`,
        `source_type`, `amount_cents` and `memo`, but the origin must be `ADJUSTMENT`;
        every other origin is produced solely by the workflows above and is refused here
        with `ERR_LEDGER_SOURCE_NOT_MANUAL`."

        Design: Corner/errors/uniqueness_source_and_schema_guards_refuse_malformed_writes
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")

        for source_type, memo in (
            ("SYNC_FEE", "Hand-posted sync fee"),
            ("PERFORMANCE", "Hand-posted performance"),
        ):
            assert_declared_error(
                api.create_royalty_ledger_entry(
                    build.ledger_entry_payload(
                        composer["id"], 1000, source_type=source_type, memo=memo
                    ),
                    ACCOUNTANT_ONE,
                ),
                ERR_LEDGER_SOURCE_NOT_MANUAL,
            )
        assert ledger_entries(api, composer["id"]) == [], (
            "a refused append writes no ledger row"
        )

        entry = assert_created(
            api.create_royalty_ledger_entry(
                build.ledger_entry_payload(
                    composer["id"], 1000, source_type="ADJUSTMENT", memo="Rounding correction"
                ),
                ACCOUNTANT_ONE,
            )
        )
        assert entry["source_type"] == "ADJUSTMENT"
        assert entry["statement_id"] is None
        assert_same_instant(entry["accrual_recognized_at"], clock_origin)
        assert_same_instant(entry["cash_recognized_at"], clock_origin)

    def test_facet_weights_must_add_to_exactly_one_hundred(self, api):
        """PRD §3.3: "A `CatalogAdmin` writes it with the four facet weights
        `weight_mood`, `weight_genre`, `weight_instrumentation` and `weight_tempo`, each a
        whole number from 0 through 100, which must add to exactly 100 or the write is
        refused with `ERR_WEIGHTS_NOT_100`."

        Design: Corner/errors/uniqueness_source_and_schema_guards_refuse_malformed_writes
        """
        assert_declared_error(
            api.put_search_profile(
                build.search_profile_payload(
                    weight_mood=30,
                    weight_genre=30,
                    weight_instrumentation=30,
                    weight_tempo=20,
                    tempo_tolerance_bpm=8,
                ),
                CATALOG_ADMIN,
            ),
            ERR_WEIGHTS_NOT_100,
        )

        written = assert_ok(
            api.put_search_profile(
                build.search_profile_payload(
                    weight_mood=40,
                    weight_genre=30,
                    weight_instrumentation=20,
                    weight_tempo=10,
                    tempo_tolerance_bpm=8,
                ),
                CATALOG_ADMIN,
            )
        )
        assert written["weight_mood"] == 40
        assert written["weight_genre"] == 30
        assert written["weight_instrumentation"] == 20
        assert written["weight_tempo"] == 10
        assert written["tempo_tolerance_bpm"] == 8

        reread = assert_ok(api.get_search_profile(CATALOG_ADMIN))
        assert reread["weight_mood"] == 40, "the refused write left nothing behind"
        assert reread["weight_tempo"] == 10

    def test_a_rate_card_code_may_not_be_reused(self, api):
        """PRD §2.6: "Three further request-shape rules sit outside the numbered ladder
        because they are shape checks rather than business rules and are evaluated with
        the schema pass: a licence creation whose supplied fields do not match its
        declared mode is refused with `ERR_LICENSE_MODE_FIELDS_INVALID` (422); a rate-card
        row reusing an existing code is refused with `ERR_TIER_CODE_DUPLICATE` (409); and
        a manual ledger append whose economic origin is anything other than the
        adjustment origin is refused with `ERR_LEDGER_SOURCE_NOT_MANUAL` (422)."

        Design: Corner/errors/uniqueness_source_and_schema_guards_refuse_malformed_writes
        """
        first = new_tier(
            api,
            code="FILM-STD",
            media_type="FILM",
            allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
            base_rate_cents=600000,
        )

        assert_declared_error(
            api.create_license_tier(
                build.license_tier_payload(
                    code="FILM-STD",
                    media_type="GAME",
                    allowed_scales=["LOCAL"],
                    base_rate_cents=250000,
                ),
                CATALOG_ADMIN,
            ),
            ERR_TIER_CODE_DUPLICATE,
        )

        reread = assert_ok(api.get_license_tier(first["id"], LICENSING_AGENT))
        assert reread["media_type"] == "FILM", "the refused row did not overwrite the first"
        assert_cents_equal(reread["base_rate_cents"], 600000, "base_rate_cents")

    @pytest.mark.parametrize(
        "coverage_start, coverage_end",
        [
            ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            ("2026-09-01T00:00:00Z", "2026-08-01T00:00:00Z"),
        ],
    )
    def test_coverage_must_end_after_it_starts(self, api, coverage_start, coverage_end):
        """PRD §3.6: "A `coverage_end` at or before `coverage_start` is refused with
        `ERR_COVERAGE_DATES_INVALID`."

        Design: Corner/errors/uniqueness_source_and_schema_guards_refuse_malformed_writes
        """
        licensee = new_licensee(
            api,
            legal_name="Meridian Broadcasting",
            licensee_type="BROADCASTER",
            credit_limit_cents=10000000,
        )

        assert_declared_error(
            api.create_blanket_agreement(
                build.blanket_agreement_payload(
                    licensee["id"],
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                    usage_cap_minutes=60,
                ),
                LICENSING_AGENT,
            ),
            ERR_COVERAGE_DATES_INVALID,
        )
        _rows, meta = assert_page(api.list_blanket_agreements({}, LICENSING_AGENT))
        assert meta["total_count"] == 0, "a refused draft writes no blanket agreement"

    def test_undeclared_enum_members_and_out_of_range_amounts_answer_the_schema_error(
        self, api
    ):
        """PRD §2.6: "**Schema and type validation** — on every write endpoint: a required
        field is absent, a field has the wrong JSON type, an enum value falls outside its
        declared set, a numeric value falls outside its declared range, or an array
        breaches its member bounds → `ERR_VALIDATION` (422)."

        Design: Corner/errors/uniqueness_source_and_schema_guards_refuse_malformed_writes
        """
        assert_declared_error(
            api.create_license_tier(
                build.license_tier_payload(
                    code="HOLO-01",
                    media_type="HOLOGRAM",
                    allowed_scales=["LOCAL"],
                    base_rate_cents=100000,
                ),
                CATALOG_ADMIN,
            ),
            ERR_VALIDATION,
        )
        assert_declared_error(
            api.create_licensee(
                build.licensee_payload(
                    legal_name="Museum of Sound",
                    licensee_type="MUSEUM",
                    credit_limit_cents=10000,
                ),
                LICENSING_AGENT,
            ),
            ERR_VALIDATION,
        )
        assert_declared_error(
            api.create_licensee(
                build.licensee_payload(
                    legal_name="Negative Credit Studio",
                    licensee_type="AGENCY",
                    credit_limit_cents=-5,
                ),
                LICENSING_AGENT,
            ),
            ERR_VALIDATION,
        )


def _held_statement(api):
    """A composer whose only ledger entry is 2000 cents, swept into a DRAFT statement."""
    composer = new_composer(
        api,
        display_name="Nadia Okoro",
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.00,
    )
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer["id"], 2000, memo="Small catalogue bonus"),
            ACCOUNTANT_ONE,
        )
    )
    statement = new_draft_statement(api, composer["id"])
    return composer, statement


class TestHeldStatementFinalizesButCannotBePaid:
    def test_a_net_below_the_minimum_payout_is_held_yet_still_finalizes(self, api):
        """PRD §3.9: "`payout_status` is `NO_ACTIVITY` when `gross_cents` is 0,
        `HELD_BELOW_MINIMUM` when `net_payable_cents` is below the minimum payout of 2500
        cents, and `PAYABLE` otherwise."

        Design: Corner/errors/statement_held_below_minimum_finalizes_but_cannot_be_paid
        """
        _composer, statement = _held_statement(api)

        assert_statement_figures(
            statement,
            gross_cents=2000,
            recouped_cents=0,
            withholding_cents=0,
            net_payable_cents=2000,
            payout_status="HELD_BELOW_MINIMUM",
            line_count=1,
        )
        assert_status(statement, "DRAFT")

        finalized = finalize_statement(api, statement["id"])
        assert_status(finalized, "FINALIZED")

    def test_a_held_statement_refuses_payment_and_pays_the_composer_nothing(self, api):
        """PRD §3.9: "Two guards apply, in this order: `payout_status` must read
        `PAYABLE`, so a statement that is `HELD_BELOW_MINIMUM` or has no activity is
        refused with `ERR_STATEMENT_NOT_PAYABLE`; and the acting `X-User-ID` must differ
        from `finalized_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/statement_held_below_minimum_finalizes_but_cannot_be_paid
        """
        composer, statement = _held_statement(api)
        finalize_statement(api, statement["id"])

        assert_declared_error(
            api.pay_royalty_statement(
                statement["id"], {"payment_reference": "wire-2026-08-0001"}, ACCOUNTANT_TWO
            ),
            ERR_STATEMENT_NOT_PAYABLE,
        )

        reread = read_statement(api, statement["id"])
        assert_status(reread, "FINALIZED")
        assert reread["paid_at"] is None
        assert reread["paid_by_user_id"] is None
        assert_composer_money(read_composer(api, composer["id"]), lifetime_paid_cents=0)
