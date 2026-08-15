"""Age-rating filings (fees, bundle discount, uniqueness, decision RBAC) and
localization packs (independent axes, coverage lock threshold, locale
uniqueness) — the two readiness tracks of PRD §3.8."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_age_rating_filing,
    create_age_rating_payload,
    create_localization_pack,
    create_title,
    get_localization_pack,
    sign_off_pack,
    transition_filing,
    transition_pack_translation,
    validate_error,
    validate_success,
)

RM_HEADERS = TEST_USERS["release_manager_headers"]
PR_HEADERS = TEST_USERS["platform_reviewer_headers"]


class TestAgeRatingFees:
    def test_bundle_discount_engages_at_two_other_active_filings(self, api):
        """PRD §3.8: "The fee starts from a territory base — 40000 cents for
        `ESRB`, 25000 for `PEGI`, 18000 for `CERO`, and 15000 for `USK` — with
        a bundle discount of ten percent when the title already has at least
        two other filings in `FILED` or `GRANTED` at the instant of filing;
        the discount count is taken on the pre-filing state, and the charged
        `fee_cents` is the base times one minus the discount, rounded half-up
        to whole cents."

        Design: Corner/calculations/age_rating_bundle_tier_thresholds
        """
        title = create_title(title_code="CL-BND", cert_budget_total_cents=1_000_000)
        esrb = create_age_rating_filing(title["id"], "ESRB", ["VIOLENCE"])
        pegi = create_age_rating_filing(title["id"], "PEGI", ["VIOLENCE"])
        cero = create_age_rating_filing(title["id"], "CERO", ["VIOLENCE"])
        esrb = transition_filing(esrb["id"], "FILED")
        assert esrb["fee_cents"] == 40000  # 0 other active filings
        pegi = transition_filing(pegi["id"], "FILED")
        assert pegi["fee_cents"] == 25000  # 1 other: below the bundle tier
        cero = transition_filing(cero["id"], "FILED")
        # 2 others active: round_half_up(18000 x 0.9) = 16200
        assert cero["fee_cents"] == 16200

    def test_duplicate_active_filing_per_territory_rejected(self, api):
        """PRD §3.8: "At most one `DRAFT` or `FILED` filing may exist per
        title and territory (`ERR_DUPLICATE_FILING`)"

        Design: Corner/entities/duplicate_active_age_rating_filing_rejected
        """
        title = create_title(title_code="ENT-DUP2", cert_budget_total_cents=1000)
        create_age_rating_filing(title["id"], "ESRB", ["MILD_VIOLENCE"])
        resp = api.create_age_rating_filing(
            create_age_rating_payload(title["id"], "ESRB", ["VIOLENCE"]),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FILING)
        pegi = api.create_age_rating_filing(
            create_age_rating_payload(title["id"], "PEGI", ["VIOLENCE"]),
            RM_HEADERS,
        )
        validate_success(pegi, expected_status=201)


class TestAgeRatingDecisionRbac:
    def test_release_manager_cannot_grant_filing(self, api):
        """PRD §3.8: "The `PlatformReviewer` then decides `FILED` → `GRANTED`
        or `FILED` → `CHALLENGED`."
        PRD §2.1: "When a declared role attempts an operation reserved for a
        different role — including the per-transition role restrictions on
        lifecycle endpoints — the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rating_decide_forbidden_for_release_manager
        """
        title = create_title(title_code="RB-RAT", cert_budget_total_cents=100000)
        filing = create_age_rating_filing(title["id"], "ESRB",
                                          ["MILD_VIOLENCE"])
        transition_filing(filing["id"], "FILED")
        resp = api.transition_age_rating_filing(
            filing["id"], {"to_status": "GRANTED"}, RM_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        filing = transition_filing(filing["id"], "GRANTED", headers=PR_HEADERS)
        assert filing["status"] == "GRANTED"


class TestLocalizationAxes:
    def test_axes_evolve_independently(self, api):
        """PRD §3.8: "The axes evolve independently — signoff does not require
        the pack to be `LOCKED`, and locking does not require signoff; only
        the package submission gate of §3.5 couples them, demanding `LOCKED`
        and `SIGNED` on every required pack."
        PRD §3.8: "Coverage is computed as one hundred times the translated
        count divided by the corresponding total, rounded half-up to two
        decimal places — and reads exactly 100.00 whenever the corresponding
        asset total is zero."

        Design: Corner/state_machines/localization_axes_evolve_independently
        """
        title = create_title(title_code="SM-LOC", cert_budget_total_cents=1000)
        pack = create_localization_pack(title["id"], "fr-FR", is_required=True,
                                        text_asset_total=100,
                                        audio_asset_total=50)
        pack = sign_off_pack(pack["id"])
        assert pack["signoff_status"] == "SIGNED"
        assert pack["translation_status"] == "DRAFT"
        pack = transition_pack_translation(
            pack["id"], "TRANSLATING",
            translated_text_assets=40, translated_audio_assets=10,
        )
        assert pack["translation_status"] == "TRANSLATING"
        assert pack["signoff_status"] == "SIGNED"
        assert pack["text_coverage_pct"] == 40.00

    def test_lock_coverage_threshold_boundary(self, api):
        """PRD §3.8: "Locking requires coverage: after applying the call's
        counts, `text_coverage_pct` must be at least 98.00 and
        `audio_coverage_pct` at least 95.00, otherwise the transition is
        rejected with `ERR_COVERAGE_BELOW_LOCK_THRESHOLD`."
        PRD §3.8: "Coverage is computed as one hundred times the translated
        count divided by the corresponding total, rounded half-up to two
        decimal places — and reads exactly 100.00 whenever the corresponding
        asset total is zero."

        Design: Corner/calculations/lock_coverage_threshold_boundary
        """
        title = create_title(title_code="CL-COV", cert_budget_total_cents=1000)
        # Pack A lands exactly on both thresholds: 98.00 text, 95.00 audio.
        pack_a = create_localization_pack(title["id"], "fr-FR",
                                          is_required=True,
                                          text_asset_total=100,
                                          audio_asset_total=200)
        transition_pack_translation(pack_a["id"], "TRANSLATING",
                                    translated_text_assets=98,
                                    translated_audio_assets=190)
        transition_pack_translation(pack_a["id"], "LQA")
        # Pack B: 97.00 text; zero audio assets read exactly 100.00.
        pack_b = create_localization_pack(title["id"], "de-DE",
                                          is_required=False,
                                          text_asset_total=100,
                                          audio_asset_total=0)
        transition_pack_translation(pack_b["id"], "TRANSLATING",
                                    translated_text_assets=97,
                                    translated_audio_assets=0)
        transition_pack_translation(pack_b["id"], "LQA")
        pack_a = transition_pack_translation(pack_a["id"], "LOCKED")
        assert pack_a["translation_status"] == "LOCKED"
        resp = api.transition_localization_pack(
            pack_b["id"], {"axis": "TRANSLATION", "to_status": "LOCKED"},
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_LOCK_THRESHOLD)
        assert get_localization_pack(pack_b["id"])["translation_status"] == "LQA"

    def test_duplicate_locale_per_title_rejected(self, api):
        """PRD §3.8: "a BCP-47 `locale` tag (unique per title — duplicates
        are `ERR_DUPLICATE_LOCALE`)"

        Design: Corner/entities/duplicate_locale_pack_rejected
        """
        t1 = create_title(title_code="ENT-DUP3A", cert_budget_total_cents=1000)
        t2 = create_title(title_code="ENT-DUP3B", cert_budget_total_cents=1000)
        create_localization_pack(t1["id"], "fr-FR", is_required=True,
                                 text_asset_total=100, audio_asset_total=0)
        resp = api.create_localization_pack(
            {
                "title_id": t1["id"], "locale": "fr-FR", "is_required": False,
                "text_asset_total": 50, "audio_asset_total": 0,
            },
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOCALE)
        other = api.create_localization_pack(
            {
                "title_id": t2["id"], "locale": "fr-FR", "is_required": True,
                "text_asset_total": 80, "audio_asset_total": 0,
            },
            RM_HEADERS,
        )
        validate_success(other, expected_status=201)
