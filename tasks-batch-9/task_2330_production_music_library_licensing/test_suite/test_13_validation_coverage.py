"""Rule-by-rule coverage of the refusals the validation ladder declares.

Every class here drives one gate to its declared error on a backdrop that is
otherwise legal, and pairs each refusal with the control call that satisfies the
same gate — so the answered error identifies the rule rather than the request.
Where one call breaks two rules at once the earlier rung must answer, because
PRD §2.6 returns the error of the first rule violated.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    accept_sync_request,
    advance_clock,
    assert_blanket_axes,
    assert_cents_equal,
    assert_composition_axes,
    assert_created,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_statement_figures,
    assert_status,
    assert_sweep_lists,
    composer_version,
    issue_per_use_license,
    ledger_entries,
    make_licensee_headers,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_cue_sheet,
    new_draft_blanket,
    new_ingested_work,
    new_licensee,
    new_tier,
    open_usage_report,
    quote_sync_request,
    read_blanket_agreement,
    read_composition,
    read_license,
    read_licensee,
    review_sync_request,
    select_ledger_entries,
    submit_sync_request,
    submit_usage_report,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_CLOCK_REWIND,
    ERR_COVERAGE_WINDOW_PASSED,
    ERR_CUE_COMPOSITION_NOT_COVERED,
    ERR_CUE_SHEET_PARENT_INVALID,
    ERR_DELIVERABLE_COUNT_SHORT,
    ERR_EDIT_PASS_REQUIRED,
    ERR_LICENSE_NOT_ISSUED,
    ERR_LICENSEE_MISMATCH,
    ERR_METADATA_INCOMPLETE,
    ERR_NO_EDIT_WORK_REQUESTED,
    ERR_PAYMENT_EXCEEDS_FEE,
    ERR_REPORT_PERIOD_DUPLICATE,
    ERR_REPORT_PERIOD_INVALID,
    ERR_SCALE_NOT_ALLOWED_FOR_TIER,
    ERR_SHARE_SPLIT_NOT_100,
    ERR_STATEMENT_NO_ACTIVITY,
    ERR_STATEMENT_PERIOD_OVERLAP,
    ERR_SYNC_REQUEST_NOT_FOUND,
    ERR_SYNC_REQUEST_STATE_INVALID,
    ERR_TERM_NOT_STARTED,
    ERR_TERM_OUTSIDE_TIER_RANGE,
    ERR_UNAUTHORIZED,
    ERR_WORK_FOR_HIRE_TERMS_INVALID,
)

# An identifier that matches no row of any entity.
_UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"

# The composer whose paperwork every class in this file starts from.
_COMPOSER = {"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"}


def _film_work(api, **agreement_overrides):
    """A catalogued FILM-ready work under an ACTIVE royalty-split agreement."""
    return new_cataloged_work(
        api,
        composer_overrides=dict(_COMPOSER),
        agreement_overrides=dict(sync_fee_share_pct=40.00, **agreement_overrides),
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )


def _film_tier(api, **overrides):
    """A FILM tier open to every distribution scale at 600000 cents."""
    terms = {
        "code": "FILM-STD",
        "media_type": "FILM",
        "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
        "base_rate_cents": 600000,
        "min_term_months": 1,
        "max_term_months": 120,
    }
    terms.update(overrides)
    return new_tier(api, **terms)


def _accepted_film_deal(api, licensee=None, tier=None, work=None, **request_overrides):
    """A FILM request carried SUBMITTED -> UNDER_REVIEW -> QUOTED -> ACCEPTED."""
    deal = Deal(
        work or _film_work(api),
        tier or _film_tier(api),
        licensee or new_licensee(api, legal_name="Northwind Pictures", credit_limit_cents=10000000),
    )
    payload = dict(
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
    )
    payload.update(request_overrides)
    quote_valid_days = payload.pop("quote_valid_days", 14)
    submit_sync_request(api, deal, **payload)
    review_sync_request(api, deal)
    quote_sync_request(api, deal, quote_valid_days)
    return accept_sync_request(api, deal)


class TestAgreementTermConsistency:
    """The share-split rule and the work-for-hire cross-check on drafting."""

    @pytest.mark.parametrize(
        "terms",
        [
            pytest.param(
                {
                    "agreement_type": "WORK_FOR_HIRE",
                    "writer_share_pct": 0.00,
                    "publisher_share_pct": 100.00,
                    "sync_fee_share_pct": 10.00,
                    "buyout_fee_cents": 500000,
                },
                id="work_for_hire_keeps_a_sync_share",
            ),
            pytest.param(
                {
                    "agreement_type": "WORK_FOR_HIRE",
                    "writer_share_pct": 0.00,
                    "publisher_share_pct": 100.00,
                    "sync_fee_share_pct": 0.00,
                    "buyout_fee_cents": 0,
                },
                id="work_for_hire_pays_no_buyout",
            ),
            pytest.param(
                {
                    "agreement_type": "ROYALTY_SPLIT",
                    "writer_share_pct": 50.00,
                    "publisher_share_pct": 50.00,
                    "sync_fee_share_pct": 40.00,
                    "buyout_fee_cents": 250000,
                },
                id="royalty_split_carries_a_buyout",
            ),
        ],
    )
    def test_inconsistent_buyout_and_sync_share_combinations_are_refused(self, api, terms):
        """PRD §3.1: "Those last two fields are cross-checked: a `WORK_FOR_HIRE`
        agreement must have a `sync_fee_share_pct` of exactly 0 and a
        `buyout_fee_cents` strictly greater than 0, while a `ROYALTY_SPLIT` agreement
        must have a `buyout_fee_cents` of exactly 0; any other combination is refused
        with `ERR_WORK_FOR_HIRE_TERMS_INVALID`."

        Design: Corner/validations/agreement_term_consistency_violations_map_to_declared_errors
        """
        composer = new_composer(api, **_COMPOSER)

        response = api.create_composer_agreement(
            build.royalty_split_agreement_payload(composer["id"], **terms), RIGHTS_MANAGER
        )
        assert_declared_error(response, ERR_WORK_FOR_HIRE_TERMS_INVALID)

        _rows, meta = assert_page(
            api.list_composer_agreements({"composer_id": composer["id"]}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 0, "a refused draft must not persist an agreement"

    def test_writer_and_publisher_shares_must_add_to_exactly_one_hundred(self, api):
        """PRD §3.1: "Performance money is divided by `writer_share_pct` and
        `publisher_share_pct`, the composer's and the library's shares, each between
        0.00 and 100.00 with two decimals; the two must add to exactly 100.00 or the
        request is refused with `ERR_SHARE_SPLIT_NOT_100`."

        Design: Corner/validations/agreement_term_consistency_violations_map_to_declared_errors
        """
        composer = new_composer(api, **_COMPOSER)

        response = api.create_composer_agreement(
            build.royalty_split_agreement_payload(
                composer["id"], writer_share_pct=60.00, publisher_share_pct=30.00
            ),
            RIGHTS_MANAGER,
        )
        assert_declared_error(response, ERR_SHARE_SPLIT_NOT_100)

    def test_share_split_answers_before_the_work_for_hire_cross_check(self, api):
        """PRD §2.6: "The service therefore evaluates a single, totally ordered ladder
        of 51 checks and returns the error of the **first** rule violated; no later
        rule can mask an earlier one."

        Design: Corner/validations/agreement_term_consistency_violations_map_to_declared_errors
        """
        composer = new_composer(api, **_COMPOSER)

        # Shares of 60.00 + 30.00 break the split rule while a work-for-hire deal
        # carrying a 12.00 sync share and no buyout breaks the cross-check as well.
        both_broken = api.create_composer_agreement(
            build.royalty_split_agreement_payload(
                composer["id"],
                agreement_type="WORK_FOR_HIRE",
                writer_share_pct=60.00,
                publisher_share_pct=30.00,
                sync_fee_share_pct=12.00,
                buyout_fee_cents=0,
                exclusivity="EXCLUSIVE",
            ),
            RIGHTS_MANAGER,
        )
        assert_declared_error(both_broken, ERR_SHARE_SPLIT_NOT_100)

        # The control: the same terms with a lawful split surface the later rule.
        only_terms_broken = api.create_composer_agreement(
            build.royalty_split_agreement_payload(
                composer["id"],
                agreement_type="WORK_FOR_HIRE",
                writer_share_pct=0.00,
                publisher_share_pct=100.00,
                sync_fee_share_pct=12.00,
                buyout_fee_cents=0,
                exclusivity="EXCLUSIVE",
            ),
            RIGHTS_MANAGER,
        )
        assert_declared_error(only_terms_broken, ERR_WORK_FOR_HIRE_TERMS_INVALID)

    def test_a_consistent_work_for_hire_draft_is_the_only_row_persisted(self, api):
        """PRD §3.1: "Those last two fields are cross-checked: a `WORK_FOR_HIRE`
        agreement must have a `sync_fee_share_pct` of exactly 0 and a
        `buyout_fee_cents` strictly greater than 0, while a `ROYALTY_SPLIT` agreement
        must have a `buyout_fee_cents` of exactly 0; any other combination is refused
        with `ERR_WORK_FOR_HIRE_TERMS_INVALID`."

        Design: Corner/validations/agreement_term_consistency_violations_map_to_declared_errors
        """
        composer = new_composer(api, **_COMPOSER)

        assert_declared_error(
            api.create_composer_agreement(
                build.royalty_split_agreement_payload(
                    composer["id"], buyout_fee_cents=250000
                ),
                RIGHTS_MANAGER,
            ),
            ERR_WORK_FOR_HIRE_TERMS_INVALID,
        )
        assert_declared_error(
            api.create_composer_agreement(
                build.royalty_split_agreement_payload(
                    composer["id"], writer_share_pct=60.00, publisher_share_pct=30.00
                ),
                RIGHTS_MANAGER,
            ),
            ERR_SHARE_SPLIT_NOT_100,
        )

        agreement = assert_created(
            api.create_composer_agreement(
                build.royalty_split_agreement_payload(
                    composer["id"],
                    agreement_type="WORK_FOR_HIRE",
                    writer_share_pct=0.00,
                    publisher_share_pct=100.00,
                    sync_fee_share_pct=0.00,
                    buyout_fee_cents=500000,
                    exclusivity="EXCLUSIVE",
                    holdback_days=45,
                    blanket_opt_in=False,
                ),
                RIGHTS_MANAGER,
            )
        )
        assert_status(agreement, "DRAFT")
        assert_cents_equal(agreement["buyout_fee_cents"], 500000, "buyout_fee_cents")
        assert agreement["sync_fee_share_pct"] == pytest.approx(0.00, abs=0.01)
        assert agreement["holdback_days"] == 45
        assert agreement["blanket_opt_in"] is False
        assert agreement["version"] == 1

        _rows, meta = assert_page(
            api.list_composer_agreements({"composer_id": composer["id"]}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 1, "only the accepted draft may persist a row"


class TestCatalogingMetadataGate:
    """Both facet arrays must carry a member before a work may be catalogued."""

    def test_cataloging_is_refused_while_either_facet_array_is_empty(self, api):
        """PRD §3.2: "And the tagging must be complete: `mood_tags` must have at least
        one member and `instrumentation` must have at least one member, otherwise the
        request is refused with `ERR_METADATA_INCOMPLETE`."

        Design: Corner/validations/cataloging_requires_complete_metadata_then_succeeds_after_patch
        """
        work = new_ingested_work(
            api,
            composer_overrides=dict(_COMPOSER),
            title="Untagged Bed",
            duration_sec=120,
            tempo_bpm=100,
            genre="CINEMATIC",
            mood_tags=[],
            instrumentation=[],
        )

        assert_declared_error(
            api.catalog_composition(work.composition_id, None, CATALOG_ADMIN),
            ERR_METADATA_INCOMPLETE,
        )
        untouched = read_composition(api, work.composition_id)
        assert_composition_axes(untouched, "INGESTED", "AVAILABLE")
        assert untouched["version"] == 1

        assert_ok(
            api.update_composition(work.composition_id, {"mood_tags": ["CALM"]}, CATALOG_ADMIN)
        )
        assert_declared_error(
            api.catalog_composition(work.composition_id, None, CATALOG_ADMIN),
            ERR_METADATA_INCOMPLETE,
        )
        still_ingested = read_composition(api, work.composition_id)
        assert_composition_axes(still_ingested, "INGESTED", "AVAILABLE")
        assert still_ingested["version"] == 2

    def test_metadata_revisions_bump_version_without_moving_either_status_axis(self, api):
        """PRD §3.2: "Metadata can be corrected in place: a `CatalogAdmin` may revise
        `title`, `tempo_bpm`, `genre`, `mood_tags` and `instrumentation`, which
        refreshes `updated_at` and increments `version`. Neither status axis is ever
        changed by a metadata revision."

        Design: Corner/validations/cataloging_requires_complete_metadata_then_succeeds_after_patch
        """
        work = new_ingested_work(
            api,
            composer_overrides=dict(_COMPOSER),
            title="Untagged Bed",
            duration_sec=120,
            tempo_bpm=100,
            genre="CINEMATIC",
            mood_tags=[],
            instrumentation=[],
        )

        moods = assert_ok(
            api.update_composition(work.composition_id, {"mood_tags": ["CALM"]}, CATALOG_ADMIN)
        )
        assert moods["mood_tags"] == ["CALM"]
        assert moods["version"] == 2
        assert_composition_axes(moods, "INGESTED", "AVAILABLE")

        instruments = assert_ok(
            api.update_composition(
                work.composition_id,
                {"instrumentation": ["PIANO", "STRINGS"], "tempo_bpm": 96},
                CATALOG_ADMIN,
            )
        )
        assert instruments["instrumentation"] == ["PIANO", "STRINGS"]
        assert instruments["tempo_bpm"] == 96
        assert instruments["version"] == 3
        assert_composition_axes(instruments, "INGESTED", "AVAILABLE")

        cataloged = assert_ok(api.catalog_composition(work.composition_id, None, CATALOG_ADMIN))
        assert_composition_axes(cataloged, "CATALOGED", "AVAILABLE")
        assert cataloged["version"] == 4


class TestTierScaleMediaAndTermRange:
    """A narrow tier refuses the wrong scale, the wrong media and the wrong term."""

    @pytest.mark.parametrize(
        "media_type, distribution_scale",
        [
            pytest.param("FILM", "WORLDWIDE", id="scale_outside_allowed_scales"),
            pytest.param("GAME", "NATIONAL", id="media_type_disagrees_with_tier"),
        ],
    )
    def test_request_creation_refuses_a_scale_or_media_the_tier_does_not_carry(
        self, api, media_type, distribution_scale
    ):
        """PRD §3.4: "Two checks guard creation: the work must be `CATALOGED` and not
        `WITHDRAWN`, or the request is refused with `ERR_COMPOSITION_NOT_LICENSABLE`;
        and the requested `distribution_scale` must be a member of the tier's
        `allowed_scales` while the requested `media_type` must equal the tier's own
        `media_type`, or the request is refused with `ERR_SCALE_NOT_ALLOWED_FOR_TIER`."

        Design: Corner/validations/tier_scale_media_and_term_range_rules_map_to_declared_errors
        """
        work = _film_work(api)
        tier = _film_tier(
            api,
            code="FILM-NAT",
            allowed_scales=["NATIONAL"],
            min_term_months=6,
            max_term_months=24,
        )
        licensee = new_licensee(
            api, legal_name="Northwind Pictures", credit_limit_cents=10000000
        )

        response = api.create_sync_request(
            build.sync_request_payload(
                work.composition_id,
                licensee["id"],
                tier["id"],
                media_type=media_type,
                distribution_scale=distribution_scale,
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
        assert_declared_error(response, ERR_SCALE_NOT_ALLOWED_FOR_TIER)

        _rows, meta = assert_page(
            api.list_sync_requests({"licensee_id": licensee["id"]}, LICENSING_AGENT)
        )
        assert meta["total_count"] == 0, "a refused sync request must not persist a row"

    def test_term_range_is_checked_at_quote_time_rather_than_at_creation(self, api):
        """PRD §3.4: "It requires the work to be `CATALOGED` with `availability_status`
        in `AVAILABLE` or `RESTRICTED`, failing with `ERR_COMPOSITION_NOT_LICENSABLE`;
        it requires the governing agreement to be `ACTIVE`, failing with
        `ERR_AGREEMENT_NOT_ACTIVE`; and it requires `requested_term_months` to lie
        within the tier's `min_term_months` and `max_term_months` inclusive, failing
        with `ERR_TERM_OUTSIDE_TIER_RANGE`."

        Design: Corner/validations/tier_scale_media_and_term_range_rules_map_to_declared_errors
        """
        work = _film_work(api)
        tier = _film_tier(
            api,
            code="FILM-NAT",
            allowed_scales=["NATIONAL"],
            min_term_months=6,
            max_term_months=24,
        )
        licensee = new_licensee(
            api, legal_name="Northwind Pictures", credit_limit_cents=10000000
        )

        out_of_range = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            out_of_range,
            media_type="FILM",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=36,
        )
        assert_status(out_of_range.sync_request, "SUBMITTED")
        assert out_of_range.sync_request["requested_term_months"] == 36
        review_sync_request(api, out_of_range)

        assert_declared_error(
            api.quote_sync_request(
                out_of_range.sync_request_id, build.quote_payload(14), LICENSING_AGENT
            ),
            ERR_TERM_OUTSIDE_TIER_RANGE,
        )
        unpriced = assert_ok(
            api.get_sync_request(out_of_range.sync_request_id, LICENSING_AGENT)
        )
        assert_status(unpriced, "UNDER_REVIEW")
        assert unpriced["quoted_fee_cents"] is None

        in_range = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            in_range,
            media_type="FILM",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        )
        review_sync_request(api, in_range)
        quote_sync_request(api, in_range, 14)
        assert_status(in_range.sync_request, "QUOTED")
        # 600000 * 2.20 FILM * 1.00 NATIONAL * 1.00 term = 1320000, less the 5.00%
        # volume discount of 66000.
        assert_cents_equal(in_range.sync_request["quoted_fee_cents"], 1254000, "quoted_fee_cents")
        assert in_range.sync_request["quoted_discount_pct"] == pytest.approx(5.00, abs=0.01)


class TestAcceptPriorityLadder:
    """One endpoint, four backdrops, four different rungs answering."""

    def _submitted_request_and_a_rival_licensee(self, api):
        work = _film_work(api)
        tier = _film_tier(api)
        licensee = new_licensee(
            api, legal_name="Northwind Pictures", credit_limit_cents=10000000
        )
        rival = new_licensee(
            api,
            legal_name="Harbour Media",
            licensee_type="AGENCY",
            credit_limit_cents=10000000,
        )
        deal = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            deal,
            media_type="FILM",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        )
        return deal, rival

    def test_unknown_path_identifier_answers_before_the_role_check(self, api):
        """PRD §2.6: "**Path entity exists** — on every endpoint with a path parameter:
        the identifier in the path matches no row of the addressed entity → the
        matching not-found error (404)."

        Design: Corner/validations/accept_priority_ladder_not_found_then_unauthorized_then_mismatch
        """
        self._submitted_request_and_a_rival_licensee(api)

        # CatalogAdmin is not among the accept endpoint's roles, yet the missing row
        # is the earlier rung and must answer.
        response = api.accept_sync_request(_UNKNOWN_ID, None, CATALOG_ADMIN)
        assert_declared_error(response, ERR_SYNC_REQUEST_NOT_FOUND)

    def test_a_role_outside_the_endpoint_answers_before_ownership_and_state(self, api):
        """PRD §2.6: "**Role permitted** — on every endpoint: `X-User-Role` is absent
        or is not among the endpoint's roles → `ERR_UNAUTHORIZED` (403)."

        Design: Corner/validations/accept_priority_ladder_not_found_then_unauthorized_then_mismatch
        """
        deal, _rival = self._submitted_request_and_a_rival_licensee(api)

        response = api.accept_sync_request(deal.sync_request_id, None, CATALOG_ADMIN)
        assert_declared_error(response, ERR_UNAUTHORIZED)

    def test_a_rival_licensee_answers_before_the_state_precondition(self, api):
        """PRD §2.6: "**Licensee ownership** — on sync-request creation, quote
        acceptance and revision requests, usage-report creation and submission, and
        cue-sheet creation: role `Licensee` acting where the target row's licensee,
        reached directly or through the blanket agreement or licence, is not
        `X-User-ID` → `ERR_LICENSEE_MISMATCH` (403)."

        Design: Corner/validations/accept_priority_ladder_not_found_then_unauthorized_then_mismatch
        """
        deal, rival = self._submitted_request_and_a_rival_licensee(api)

        response = api.accept_sync_request(
            deal.sync_request_id, None, make_licensee_headers(rival["id"])
        )
        assert_declared_error(response, ERR_LICENSEE_MISMATCH)

    def test_the_owning_licensee_finally_meets_the_state_error(self, api):
        """PRD §3.4: "`DECLINED` and `DELIVERED` are terminal, and any action attempted
        on a request in a state the transition does not accept is refused with
        `ERR_SYNC_REQUEST_STATE_INVALID`."

        Design: Corner/validations/accept_priority_ladder_not_found_then_unauthorized_then_mismatch
        """
        deal, _rival = self._submitted_request_and_a_rival_licensee(api)

        response = api.accept_sync_request(
            deal.sync_request_id, None, make_licensee_headers(deal.licensee_id)
        )
        assert_declared_error(response, ERR_SYNC_REQUEST_STATE_INVALID)

        unchanged = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
        assert_status(unchanged, "SUBMITTED")
        assert_cents_equal(
            read_licensee(api, deal.licensee_id)["reserved_spend_cents"], 0, "reserved_spend_cents"
        )


class TestCueSheetParentAndCoverage:
    """Exactly one parent, and a coverage rule that changes meaning with it."""

    def _both_parents_ground(self, api):
        """A licensee holding an ISSUED per-use licence and an ACTIVE blanket period.

        The licensed work is blanket-opted-in; a second work sits under an agreement
        whose `blanket_opt_in` is false.
        """
        licensee = new_licensee(
            api,
            legal_name="Meridian Broadcasting",
            licensee_type="BROADCASTER",
            credit_limit_cents=10000000,
        )
        deal = _accepted_film_deal(api, licensee=licensee)
        issue_per_use_license(api, deal)

        opted_out = new_cataloged_work(
            api,
            composer_overrides={"display_name": "Tomas Reyes", "pro_affiliation": "BMI"},
            agreement_overrides={"blanket_opt_in": False},
            title="Opt Out Groove",
            duration_sec=150,
            tempo_bpm=110,
            genre="ROCK",
            mood_tags=["QUIRKY"],
            instrumentation=["GUITAR"],
        )

        blanket = new_active_blanket(api, licensee=licensee, usage_cap_minutes=3)
        open_usage_report(api, blanket)
        return deal, opted_out, blanket

    @pytest.mark.parametrize("parents", ["both", "neither"])
    def test_a_sheet_must_hang_off_exactly_one_parent(self, api, parents):
        """PRD §3.7: "Exactly one of `license_id` and `usage_report_id` must be
        supplied: the first for per-use reporting against a single licence, the second
        for blanket reporting against a period. Supplying both, or neither, is refused
        with `ERR_CUE_SHEET_PARENT_INVALID`."

        Design: Corner/validations/cue_sheet_parent_and_coverage_rules_enforced_per_parent_kind
        """
        deal, _opted_out, blanket = self._both_parents_ground(api)
        cues = [build.cue(deal.composition_id, "THEME", 30)]

        payload = build.cue_sheet_payload(
            cues,
            license_id=deal.license_id if parents == "both" else None,
            usage_report_id=blanket.usage_report_id if parents == "both" else None,
            production_title="Parentage Probe",
            broadcast_date="2026-08-10T00:00:00Z",
        )
        assert_declared_error(
            api.create_cue_sheet(payload, LICENSING_AGENT), ERR_CUE_SHEET_PARENT_INVALID
        )

        _rows, meta = assert_page(api.list_cue_sheets(None, RIGHTS_MANAGER))
        assert meta["total_count"] == 0, "a refused cue sheet must not persist a row"

    def test_under_a_licence_parent_every_cue_must_cite_the_licensed_work(self, api):
        """PRD §3.7: "Under a licence parent, every cue must cite the very work that
        licence covers, and any other work is refused with
        `ERR_CUE_COMPOSITION_NOT_COVERED`."

        Design: Corner/validations/cue_sheet_parent_and_coverage_rules_enforced_per_parent_kind
        """
        deal, opted_out, _blanket = self._both_parents_ground(api)

        response = api.create_cue_sheet(
            build.cue_sheet_payload(
                [
                    build.cue(deal.composition_id, "THEME", 30),
                    build.cue(opted_out.composition_id, "BACKGROUND", 30),
                ],
                license_id=deal.license_id,
                production_title="Wrong Work Under Licence",
                broadcast_date="2026-08-10T00:00:00Z",
            ),
            LICENSING_AGENT,
        )
        assert_declared_error(response, ERR_CUE_COMPOSITION_NOT_COVERED)

        covered = new_cue_sheet(
            api,
            [build.cue(deal.composition_id, "THEME", 30)],
            license_id=deal.license_id,
            production_title="Licensed Work Under Licence",
            broadcast_date="2026-08-10T00:00:00Z",
        )
        assert covered["license_id"] == deal.license_id
        assert covered["usage_report_id"] is None
        assert_status(covered, "COLLECTED")
        assert_credits_equal(covered["total_credits"], 1.00, "total_credits")
        assert covered["total_seconds"] == 30

    def test_under_a_report_parent_an_opted_out_work_is_refused(self, api):
        """PRD §3.7: "Under a usage-report parent, a cue may not cite a work whose
        `availability_status` is `WITHDRAWN`, nor a work whose governing agreement has
        `blanket_opt_in` false — a composer who opted out of blanket exploitation is
        not swept into a broadcaster's pool — and either case is refused with the same
        `ERR_CUE_COMPOSITION_NOT_COVERED`, with array members checked in order."

        Design: Corner/validations/cue_sheet_parent_and_coverage_rules_enforced_per_parent_kind
        """
        deal, opted_out, blanket = self._both_parents_ground(api)

        response = api.create_cue_sheet(
            build.cue_sheet_payload(
                [build.cue(opted_out.composition_id, "FEATURE", 30)],
                usage_report_id=blanket.usage_report_id,
                production_title="Opted Out Under Report",
                broadcast_date="2026-08-10T00:00:00Z",
            ),
            LICENSING_AGENT,
        )
        assert_declared_error(response, ERR_CUE_COMPOSITION_NOT_COVERED)

        opted_in = new_cue_sheet(
            api,
            [build.cue(deal.composition_id, "FEATURE", 30)],
            usage_report_id=blanket.usage_report_id,
            production_title="Opted In Under Report",
            broadcast_date="2026-08-10T00:00:00Z",
        )
        assert opted_in["usage_report_id"] == blanket.usage_report_id
        assert opted_in["license_id"] is None
        assert_credits_equal(opted_in["total_credits"], 0.65, "total_credits")

        rows, meta = assert_page(
            api.list_cue_sheets({"usage_report_id": blanket.usage_report_id}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 1, "the refused sheet left no row behind"
        assert rows[0]["id"] == opted_in["id"]


class TestUsageReportPeriodRules:
    """Cadence boundaries, and the status filter behind the duplicate rule."""

    def _active_monthly_blanket(self, api):
        work = _film_work(api)
        licensee = new_licensee(
            api,
            legal_name="Meridian Broadcasting",
            licensee_type="BROADCASTER",
            credit_limit_cents=10000000,
        )
        blanket = new_active_blanket(api, licensee=licensee, usage_cap_minutes=60)
        return work, blanket

    @pytest.mark.parametrize(
        "period_start, period_end",
        [
            pytest.param(
                "2026-08-15T00:00:00Z", "2026-09-14T00:00:00Z", id="start_off_the_cadence_boundary"
            ),
            pytest.param(
                "2026-08-01T00:00:00Z", "2026-08-30T00:00:00Z", id="end_does_not_match_cadence"
            ),
            pytest.param(
                "2027-08-01T00:00:00Z", "2027-08-31T00:00:00Z", id="period_outside_coverage"
            ),
        ],
    )
    def test_period_must_be_a_cadence_window_inside_coverage(
        self, api, period_start, period_end
    ):
        """PRD §3.6: "A report is created by the `Licensee` or a `LicensingAgent` with
        the `blanket_agreement_id`, a `period_start` that must be exactly a cadence
        boundary derived from `coverage_start`, and a `period_end` that must be exactly
        that boundary advanced by one cadence and pulled back one day; a period that is
        not a cadence boundary, whose end does not match the cadence, or that falls
        outside the coverage interval, is refused with `ERR_REPORT_PERIOD_INVALID`."

        Design: Corner/validations/report_period_cadence_and_duplicate_rules_enforced
        """
        _work, blanket = self._active_monthly_blanket(api)

        response = api.create_usage_report(
            build.usage_report_payload(
                blanket.agreement_id, period_start=period_start, period_end=period_end
            ),
            LICENSING_AGENT,
        )
        assert_declared_error(response, ERR_REPORT_PERIOD_INVALID)

        _rows, meta = assert_page(
            api.list_usage_reports({"blanket_agreement_id": blanket.agreement_id}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 0, "a refused period must not persist a report"

    def test_duplicate_period_is_refused_while_due_and_allowed_after_rejection(self, api):
        """PRD §3.6: "A second report for the same period is refused with
        `ERR_REPORT_PERIOD_DUPLICATE` when an existing report for that agreement with
        the same `period_start` sits in `DUE`, `SUBMITTED` or `ACCEPTED` — which is what
        allows a rejected period to be re-created."

        Design: Corner/validations/report_period_cadence_and_duplicate_rules_enforced
        """
        work, blanket = self._active_monthly_blanket(api)
        open_usage_report(api, blanket)
        first = blanket.usage_report
        assert_status(first, "DUE")
        assert first["reported_minutes_total"] == 0
        assert_credits_equal(first["reported_credits_total"], 0.00, "reported_credits_total")
        assert first["pool_allocations"] == []

        assert_declared_error(
            api.create_usage_report(
                build.usage_report_payload(blanket.agreement_id), LICENSING_AGENT
            ),
            ERR_REPORT_PERIOD_DUPLICATE,
        )

        new_cue_sheet(
            api,
            [build.cue(work.composition_id, "THEME", 30)],
            usage_report_id=blanket.usage_report_id,
            production_title="Evening Bulletin",
            broadcast_date="2026-08-12T00:00:00Z",
        )
        submit_usage_report(api, blanket)
        assert_status(blanket.usage_report, "SUBMITTED")
        assert blanket.usage_report["resubmission_count"] == 0

        rejected = assert_ok(
            api.reject_usage_report(
                blanket.usage_report_id,
                {"reason": "Cue durations disagree with the as-run log"},
                RIGHTS_MANAGER,
            )
        )
        assert_status(rejected, "REJECTED")
        assert rejected["rejection_reason"] == "Cue durations disagree with the as-run log"
        assert rejected["pool_allocations"] == []

        reopened = assert_created(
            api.create_usage_report(
                build.usage_report_payload(blanket.agreement_id), LICENSING_AGENT
            )
        )
        assert reopened["id"] != first["id"]
        assert_status(reopened, "DUE")
        assert reopened["period_start"].startswith("2026-08-01")

        _rows, meta = assert_page(
            api.list_usage_reports({"blanket_agreement_id": blanket.agreement_id}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 2


class TestStatementPeriodAndActivityGates:
    """Windows may not overlap, and emptiness only bites at finalization."""

    def _composer_with_one_adjustment(self, api):
        composer = new_composer(
            api, display_name="Nadia Okoro", pro_affiliation="ASCAP", tax_withholding_pct=0.30
        )
        assert_created(
            api.create_royalty_ledger_entry(
                build.ledger_entry_payload(
                    composer["id"], 40000, memo="Library-wide catalogue bonus"
                ),
                ACCOUNTANT_ONE,
            )
        )
        return composer

    def test_a_partially_overlapping_window_is_refused(self, api):
        """PRD §3.9: "Periods may not overlap: another statement for the same composer
        covering an overlapping window, both endpoints inclusive, is refused with
        `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Corner/validations/statement_period_overlap_and_no_activity_rules_enforced
        """
        composer = self._composer_with_one_adjustment(api)

        august = assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], composer_version(api, composer["id"])),
                ACCOUNTANT_ONE,
            )
        )
        assert_statement_figures(
            august,
            gross_cents=40000,
            recouped_cents=0,
            withholding_cents=12000,
            net_payable_cents=28000,
            payout_status="PAYABLE",
            line_count=1,
        )
        assert_status(august, "DRAFT")

        overlapping = api.create_royalty_statement(
            build.statement_payload(
                composer["id"],
                composer_version(api, composer["id"]),
                period_start="2026-08-15T00:00:00Z",
                period_end="2026-09-15T00:00:00Z",
            ),
            ACCOUNTANT_ONE,
        )
        assert_declared_error(overlapping, ERR_STATEMENT_PERIOD_OVERLAP)

        _rows, meta = assert_page(
            api.list_royalty_statements({"composer_id": composer["id"]}, ACCOUNTANT_ONE)
        )
        assert meta["total_count"] == 1, "a refused window must not persist a statement"

    def test_an_empty_window_is_created_and_only_refused_at_finalization(self, api):
        """PRD §3.9: "Finalization is the point of no return: `DRAFT → FINALIZED`
        records `finalized_by_user_id` from the acting `X-User-ID` and `finalized_at`
        from the clock, and is refused with `ERR_STATEMENT_NO_ACTIVITY` when
        `payout_status` reads `NO_ACTIVITY`, since there is nothing to state."

        Design: Corner/validations/statement_period_overlap_and_no_activity_rules_enforced
        """
        composer = self._composer_with_one_adjustment(api)

        august = assert_created(
            api.create_royalty_statement(
                build.statement_payload(composer["id"], composer_version(api, composer["id"])),
                ACCOUNTANT_ONE,
            )
        )
        october = assert_created(
            api.create_royalty_statement(
                build.statement_payload(
                    composer["id"],
                    composer_version(api, composer["id"]),
                    period_start="2026-10-01T00:00:00Z",
                    period_end="2026-10-31T00:00:00Z",
                ),
                ACCOUNTANT_ONE,
            )
        )
        assert_statement_figures(
            october,
            gross_cents=0,
            recouped_cents=0,
            withholding_cents=0,
            net_payable_cents=0,
            payout_status="NO_ACTIVITY",
            line_count=0,
        )
        assert_status(october, "DRAFT")

        assert_declared_error(
            api.finalize_royalty_statement(october["id"], None, ACCOUNTANT_ONE),
            ERR_STATEMENT_NO_ACTIVITY,
        )
        assert_status(
            assert_ok(api.get_royalty_statement(october["id"], ACCOUNTANT_ONE)), "DRAFT"
        )

        finalized = assert_ok(
            api.finalize_royalty_statement(august["id"], None, ACCOUNTANT_ONE)
        )
        assert_status(finalized, "FINALIZED")


class TestDeliveryGating:
    """Four rules keyed off the same three deliverable flags on sibling requests."""

    def _flagless_and_edit_requests(self, api):
        """Request B asks for stems and one alternate; request A asks for no edit work."""
        work = _film_work(api)
        tier = _film_tier(api)
        licensee = new_licensee(
            api, legal_name="Northwind Pictures", credit_limit_cents=20000000
        )
        with_edit_work = _accepted_film_deal(
            api,
            licensee=licensee,
            tier=tier,
            work=work,
            stems_requested=True,
            alternate_lengths_sec=[30],
        )
        flagless = _accepted_film_deal(
            api, licensee=licensee, tier=tier, work=work, distribution_scale="LOCAL"
        )
        return flagless, with_edit_work

    def test_a_flagless_request_cannot_start_an_edit_pass(self, api):
        """PRD §3.5: "A `CatalogAdmin` may start an edit pass, moving `ACCEPTED →
        EDIT_IN_PROGRESS` with an optional `edit_note`; this is allowed only when there
        is edit work to do, meaning `custom_edit_requested` is true, or
        `stems_requested` is true, or `alternate_lengths_sec` has at least one member.
        Otherwise it is refused with `ERR_NO_EDIT_WORK_REQUESTED`."

        Design: Corner/validations/edit_pass_license_and_deliverable_gating_conditional_on_request_flags
        """
        flagless, _with_edit_work = self._flagless_and_edit_requests(api)

        assert_declared_error(
            api.start_sync_request_edit(
                flagless.sync_request_id, {"edit_note": "Trim the intro"}, CATALOG_ADMIN
            ),
            ERR_NO_EDIT_WORK_REQUESTED,
        )
        assert_status(
            assert_ok(api.get_sync_request(flagless.sync_request_id, LICENSING_AGENT)),
            "ACCEPTED",
        )

    def test_nothing_is_delivered_before_a_licence_exists(self, api):
        """PRD §3.5: "Delivery, also by a `CatalogAdmin`, is reachable from either
        `ACCEPTED` or `EDIT_IN_PROGRESS` and takes a `delivered_asset_count` and an
        optional `delivery_note`; both paths require the request's `license_id` to be
        non-null, since nothing may be handed over before a licence exists, and a null
        one is refused with `ERR_LICENSE_NOT_ISSUED`."

        Design: Corner/validations/edit_pass_license_and_deliverable_gating_conditional_on_request_flags
        """
        flagless, _with_edit_work = self._flagless_and_edit_requests(api)

        # The flagless request never asked for edit work, so the edit-pass rule does
        # not fire and the licence rule is the first one violated.
        assert_declared_error(
            api.deliver_sync_request(
                flagless.sync_request_id, build.deliver_payload(1), CATALOG_ADMIN
            ),
            ERR_LICENSE_NOT_ISSUED,
        )

    def test_a_requested_edit_pass_may_not_be_skipped(self, api):
        """PRD §3.5: "Arriving straight from `ACCEPTED` is legal only when no edit work
        was ever asked for — `custom_edit_requested` false, `stems_requested` false, and
        `alternate_lengths_sec` empty — and an attempt to skip a requested edit pass is
        refused with `ERR_EDIT_PASS_REQUIRED`; on that path `delivered_asset_count` need
        only be at least 1, and a value below 1 is refused with `ERR_VALIDATION`."

        Design: Corner/validations/edit_pass_license_and_deliverable_gating_conditional_on_request_flags
        """
        _flagless, with_edit_work = self._flagless_and_edit_requests(api)

        # No licence exists either, but PRD §2.6 places the edit-pass rule above the
        # licence rule, so the edit-pass error must answer.
        assert_declared_error(
            api.deliver_sync_request(
                with_edit_work.sync_request_id, build.deliver_payload(3), CATALOG_ADMIN
            ),
            ERR_EDIT_PASS_REQUIRED,
        )

        started = assert_ok(
            api.start_sync_request_edit(
                with_edit_work.sync_request_id,
                {"edit_note": "Bounce stems and a 30s cutdown"},
                CATALOG_ADMIN,
            )
        )
        assert_status(started, "EDIT_IN_PROGRESS")

        # With the edit-pass gate satisfied the next rung surfaces.
        assert_declared_error(
            api.deliver_sync_request(
                with_edit_work.sync_request_id, build.deliver_payload(3), CATALOG_ADMIN
            ),
            ERR_LICENSE_NOT_ISSUED,
        )

    def test_the_count_must_cover_master_stems_and_every_alternate(self, api):
        """PRD §3.5: "Arriving from `EDIT_IN_PROGRESS`, the count must cover the full
        deliverable set: at least 1 for the master, plus 1 more when `stems_requested`
        is true, plus one more for each member of `alternate_lengths_sec`; anything
        short is refused with `ERR_DELIVERABLE_COUNT_SHORT`."

        Design: Corner/validations/edit_pass_license_and_deliverable_gating_conditional_on_request_flags
        """
        _flagless, with_edit_work = self._flagless_and_edit_requests(api)
        # Issuance comes first: PRD §3.5 says a per-use licence request "carries the
        # `sync_request_id` of an `ACCEPTED` sync request", so the licence has to be
        # issued before the edit pass moves the request out of `ACCEPTED`.  Delivery
        # from `EDIT_IN_PROGRESS` still sees a non-null `license_id`.
        issue_per_use_license(api, with_edit_work)
        assert_status(with_edit_work.license, "ISSUED")
        assert_status(
            assert_ok(
                api.start_sync_request_edit(
                    with_edit_work.sync_request_id,
                    {"edit_note": "Bounce stems and a 30s cutdown"},
                    CATALOG_ADMIN,
                )
            ),
            "EDIT_IN_PROGRESS",
        )

        assert_declared_error(
            api.deliver_sync_request(
                with_edit_work.sync_request_id, build.deliver_payload(2), CATALOG_ADMIN
            ),
            ERR_DELIVERABLE_COUNT_SHORT,
        )
        assert_status(
            assert_ok(api.get_sync_request(with_edit_work.sync_request_id, LICENSING_AGENT)),
            "EDIT_IN_PROGRESS",
        )

        delivered = assert_ok(
            api.deliver_sync_request(
                with_edit_work.sync_request_id, build.deliver_payload(3), CATALOG_ADMIN
            )
        )
        assert_status(delivered, "DELIVERED")
        assert delivered["delivered_asset_count"] == 3


class TestLicensePaymentCollection:
    """The over-collection guard, probed around a fee of 1254000 cents."""

    def _issued_film_license(self, api):
        deal = _accepted_film_deal(api)
        issue_per_use_license(api, deal)
        # 600000 * 2.20 FILM * 1.00 NATIONAL * 1.00 term = 1320000 less the 5.00%
        # volume discount, and 40.00% of that fee is the composer's sync share.
        assert_cents_equal(deal.license["final_fee_cents"], 1254000, "final_fee_cents")
        assert_cents_equal(
            deal.license["composer_sync_share_cents"], 501600, "composer_sync_share_cents"
        )
        return deal

    @pytest.mark.parametrize(
        "amount_cents",
        [pytest.param(1254001, id="one_cent_over_the_fee"), pytest.param(0, id="not_positive")],
    )
    def test_a_non_positive_or_over_collecting_payment_is_refused(self, api, amount_cents):
        """PRD §3.5: "A payment that is not strictly positive, or that would push
        `collected_amount_cents` past `final_fee_cents`, is refused with
        `ERR_PAYMENT_EXCEEDS_FEE`."

        Design: Corner/validations/license_payment_collection_boundaries_enforced_across_installments
        """
        deal = self._issued_film_license(api)

        assert_declared_error(
            api.record_license_payment(
                deal.license_id, {"amount_cents": amount_cents}, ACCOUNTANT_ONE
            ),
            ERR_PAYMENT_EXCEEDS_FEE,
        )
        untouched = read_license(api, deal.license_id)
        assert_cents_equal(untouched["collected_amount_cents"], 0, "collected_amount_cents")
        assert untouched["collected_at"] is None

    def test_the_cumulative_total_is_what_breaches_the_fee(self, api):
        """PRD §3.5: "A payment that is not strictly positive, or that would push
        `collected_amount_cents` past `final_fee_cents`, is refused with
        `ERR_PAYMENT_EXCEEDS_FEE`."

        Design: Corner/validations/license_payment_collection_boundaries_enforced_across_installments
        """
        deal = self._issued_film_license(api)

        part = assert_ok(
            api.record_license_payment(
                deal.license_id, {"amount_cents": 254000}, ACCOUNTANT_ONE
            )
        )
        assert_cents_equal(part["collected_amount_cents"], 254000, "collected_amount_cents")
        assert part["collected_at"] is None
        assert_status(part, "ISSUED")

        # 254000 already collected plus 1000001 exceeds the fee by one cent.
        assert_declared_error(
            api.record_license_payment(
                deal.license_id, {"amount_cents": 1000001}, ACCOUNTANT_ONE
            ),
            ERR_PAYMENT_EXCEEDS_FEE,
        )
        assert_cents_equal(
            read_license(api, deal.license_id)["collected_amount_cents"],
            254000,
            "collected_amount_cents",
        )

    def test_the_completing_installment_stamps_collection_and_the_cash_instant(
        self, api, clock_origin
    ):
        """PRD §3.5: "When `collected_amount_cents` first reaches `final_fee_cents`, the
        licence's `collected_at` is stamped from the clock and the cash instant is
        stamped on this licence's sync-fee ledger entry — which is precisely what makes
        that amount visible to a cash-basis statement."

        Design: Corner/validations/license_payment_collection_boundaries_enforced_across_installments
        """
        deal = self._issued_film_license(api)
        composer_id = deal.work.composer_id

        assert_ok(
            api.record_license_payment(
                deal.license_id, {"amount_cents": 254000}, ACCOUNTANT_ONE
            )
        )
        before = select_ledger_entries(
            ledger_entries(api, composer_id), source_type="SYNC_FEE"
        )
        assert len(before) == 1
        assert before[0]["cash_recognized_at"] is None

        settled = assert_ok(
            api.record_license_payment(
                deal.license_id, {"amount_cents": 1000000}, ACCOUNTANT_ONE
            )
        )
        assert_cents_equal(settled["collected_amount_cents"], 1254000, "collected_amount_cents")
        assert_same_instant(settled["collected_at"], clock_origin)

        after = select_ledger_entries(
            ledger_entries(api, composer_id), source_type="SYNC_FEE"
        )
        assert len(after) == 1
        assert_cents_equal(after[0]["amount_cents"], 501600, "sync fee amount_cents")
        assert_same_instant(after[0]["cash_recognized_at"], clock_origin)


class TestActivationTemporalGates:
    """A licence may not activate too early, a blanket may not activate too late."""

    def _issued_license_and_draft_blanket(self, api):
        licensee = new_licensee(
            api,
            legal_name="Meridian Broadcasting",
            licensee_type="BROADCASTER",
            credit_limit_cents=10000000,
        )
        deal = _accepted_film_deal(
            api, licensee=licensee, requested_term_start="2026-10-01T00:00:00Z"
        )
        issue_per_use_license(api, deal)
        blanket = new_draft_blanket(
            api,
            licensee=licensee,
            coverage_start="2026-08-01T00:00:00Z",
            coverage_end="2026-09-01T00:00:00Z",
            usage_cap_minutes=60,
        )
        return deal, blanket

    def test_a_licence_cannot_be_activated_before_its_term_start(self, api):
        """PRD §3.5: "Activation is a formality with a date check: `ISSUED → ACTIVE` is
        allowed only once the current logical clock date has reached `term_start`, and
        an earlier attempt is refused with `ERR_TERM_NOT_STARTED`."

        Design: Corner/validations/activation_temporal_gates_and_clock_rewind_enforced
        """
        deal, _blanket = self._issued_license_and_draft_blanket(api)

        assert_declared_error(
            api.activate_license(deal.license_id, None, LICENSING_AGENT), ERR_TERM_NOT_STARTED
        )
        assert_status(read_license(api, deal.license_id), "ISSUED")

        sweep = advance_clock(api, "2026-09-01T00:00:00Z")
        assert_sweep_lists(
            sweep,
            expired_license_ids=[],
            expired_blanket_agreement_ids=[],
            delinquent_blanket_agreement_ids=[],
        )
        assert_declared_error(
            api.activate_license(deal.license_id, None, LICENSING_AGENT), ERR_TERM_NOT_STARTED
        )

        advance_clock(api, "2026-10-01T00:00:00Z")
        activated = assert_ok(api.activate_license(deal.license_id, None, LICENSING_AGENT))
        assert_status(activated, "ACTIVE")

    def test_a_blanket_cannot_be_activated_once_coverage_end_is_reached(self, api):
        """PRD §3.6: "Activation moves `coverage_status` `DRAFT → ACTIVE` and is refused
        with `ERR_COVERAGE_WINDOW_PASSED` when the current logical clock date has
        already reached `coverage_end`."

        Design: Corner/validations/activation_temporal_gates_and_clock_rewind_enforced
        """
        _deal, blanket = self._issued_license_and_draft_blanket(api)

        advance_clock(api, "2026-09-01T00:00:00Z")
        assert_declared_error(
            api.activate_blanket_agreement(blanket.agreement_id, None, LICENSING_AGENT),
            ERR_COVERAGE_WINDOW_PASSED,
        )
        assert_blanket_axes(
            read_blanket_agreement(api, blanket.agreement_id), "DRAFT", "COMPLIANT"
        )

    def test_the_logical_clock_refuses_to_rewind(self, api):
        """PRD §2.5: "Time only moves forward: a `to_iso8601` earlier than the current
        value is refused with `ERR_CLOCK_REWIND` (HTTP 422)."

        Design: Corner/validations/activation_temporal_gates_and_clock_rewind_enforced
        """
        advance_clock(api, "2026-09-01T00:00:00Z")
        advance_clock(api, "2026-10-01T00:00:00Z")

        assert_declared_error(
            api.set_clock("2026-09-15T00:00:00Z", CATALOG_ADMIN), ERR_CLOCK_REWIND
        )

        # Re-submitting the current instant is not a rewind, and reports the clock the
        # refused call left in place.
        unchanged = assert_ok(api.set_clock("2026-10-01T00:00:00Z", CATALOG_ADMIN))
        assert_same_instant(unchanged["current_utc"], "2026-10-01T00:00:00Z")
