"""Artists, contracts, and the dual-variant weekly pay quote."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_artist,
    create_contract_payload,
    create_production,
    setup_mixed_status_week,
    setup_night_boundary_week,
    setup_overtime_week,
    setup_pay_week_projected_vs_final,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["contracts_officer_headers"]
CD = TEST_USERS["casting_director_headers"]
ANY = TEST_USERS["any_headers"]


class TestContractDefaults:
    def test_contract_create_rest_floor_default_applied(self, api):
        """PRD §3.4: "Engaging an artist for a production creates a contract with the `production_id`, the `artist_id`, an `engagement_type` of `PRINCIPAL`, `COVER`, `CHORUS`, or `ORCHESTRA`, an `hourly_rate_cents` greater than zero, a `weekly_hours_cap` greater than zero marking the regular hours before overtime tiers apply, and an optional `rest_floor_hours` — the minimum rest between committed calls — which defaults to 12 hours when omitted."
        PRD §3.4: "Contracts begin in `DRAFT`."

        Design: Corner/entities/contract_create_rest_floor_default_applied
        """
        production = create_production(title="Giselle", build_budget_cents=50_000_000)
        artist = create_artist(full_name="Anna Principal")
        payload = create_contract_payload(production["id"], artist["id"])
        assert "rest_floor_hours" not in payload
        resp = api.create_contract(payload, CO)
        data = validate_success(resp, 201)
        assert data["rest_floor_hours"] == 12, "omitted rest_floor_hours defaults to 12"
        assert data["status"] == "DRAFT", "contracts begin in DRAFT"


class TestContractRbac:
    def test_casting_director_cannot_create_contract_rejected(self, api):
        """PRD §2.1: "If the role is declared but is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/casting_director_cannot_create_contract_rejected
        """
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        artist = create_artist(full_name="Anna Principal")
        payload = create_contract_payload(production["id"], artist["id"])
        resp = api.create_contract(payload, CD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestArtistListing:
    def test_artists_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 and must be at least 1 and at most 100; `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/artists_list_pagination_envelope
        """
        create_artist(full_name="Artist One", discipline="SOPRANO", union_code="AGMA")
        create_artist(full_name="Artist Two", discipline="TENOR", union_code="AFM")
        resp = api.list_artists(ANY, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 1, "limit=1 returns exactly one item"
        assert meta["total_count"] == 2, "two artists registered"
        assert meta["has_more"] is True, "one more page remains"
        assert meta["limit"] == 1 and meta["offset"] == 0
        assert isinstance(resp.json()["meta"].get("api_request_id"), str)


class TestWeeklyPayVariants:
    def test_artist_pay_final_variant_completed_only(self, api):
        """PRD §3.4: "The two variants differ only in which calls are included: `PROJECTED` counts calls in `PUBLISHED` or `COMPLETED`, so scheduled-but-unplayed hours count; `FINAL` counts only `COMPLETED` calls, so identical week data yields strictly lower final pay whenever any `PUBLISHED` call exists."

        Week: 12h + 12h + 15h (ends 23:00, night premium) COMPLETED; 4h PUBLISHED.
        FINAL: 39h -> 30*8000 + 9*12000 OT1 + 1*1500 night = 349,500.

        Design: Difficulty/dual_variant_calc/artist_pay_projected_vs_final
        """
        scenario = setup_pay_week_projected_vs_final()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01", mode="FINAL")
        quote = validate_success(resp, 200)
        assert quote["final_hours"] == 39, "FINAL counts only COMPLETED calls (12+12+15)"
        assert quote["final_pay_cents"] == 349_500, (
            "30*8000 regular + 9*12000 OT1 + 1*1500 night premium"
        )

    def test_artist_pay_projected_includes_published(self, api):
        """PRD §3.4: "The quote takes a `week_start` and an optional `mode` of `PROJECTED` or `FINAL`, and always reports both variants side by side — `projected_hours` and `projected_pay_cents` against `final_hours` and `final_pay_cents` — so scheduled-but-unplayed work can be compared against actuals."
        PRD §3.4: "`PROJECTED` counts calls in `PUBLISHED` or `COMPLETED`, so scheduled-but-unplayed hours count; `FINAL` counts only `COMPLETED` calls, so identical week data yields strictly lower final pay whenever any `PUBLISHED` call exists."

        PROJECTED: 43h -> 30*8000 + 10*12000 OT1 + 3*16000 OT2 + 1500 night = 409,500.

        Design: Difficulty/dual_variant_calc/artist_pay_projected_vs_final
        """
        scenario = setup_pay_week_projected_vs_final()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01", mode="PROJECTED")
        quote = validate_success(resp, 200)
        assert quote["projected_hours"] == 43, "PROJECTED adds the 4h PUBLISHED call"
        assert quote["projected_pay_cents"] == 409_500, (
            "30*8000 regular + 10*12000 OT1 + 3*16000 OT2 + 1500 night premium"
        )
        assert quote["projected_pay_cents"] != quote["final_pay_cents"], (
            "variants diverge for the identical contract and week"
        )
        assert quote["final_pay_cents"] == 349_500


class TestOvertimeTierFormula:
    def test_overtime_tiers_and_night_premium_final_pay(self, api):
        """PRD §3.4: "the first overtime tier, comprising the hours beyond the cap up to a span of ten hours, is paid at one and a half times the base rate; the second overtime tier, comprising any hours beyond the cap plus that ten-hour first tier, is paid at double the base rate."
        PRD §3.4: "On top of the tiered pay, each night call — an included call whose `ends_at` time-of-day, taken in UTC, falls at or after 23:00 and before midnight — adds a flat premium of 1,500 cents."

        Week: 12h COMPLETED (ends 20:00) + 11h COMPLETED (ends 23:00); rate 5,000,
        cap 10. FINAL: 10*5000 + 10*7500 + 3*10000 + 1500 = 156,500.

        Design: Difficulty/combinatorial_formula/overtime_tiered_pay_with_night_premium
        """
        scenario = setup_overtime_week()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01", mode="FINAL")
        quote = validate_success(resp, 200)
        assert quote["final_hours"] == 23
        assert quote["final_pay_cents"] == 156_500, (
            "10*5000 regular + 10*7500 OT1 + 3*10000 OT2 + 1500 night premium"
        )

    def test_projected_equals_final_when_no_published_calls(self, api):
        """PRD §3.4: "The two variants differ only in which calls are included: `PROJECTED` counts calls in `PUBLISHED` or `COMPLETED`, so scheduled-but-unplayed hours count; `FINAL` counts only `COMPLETED` calls, so identical week data yields strictly lower final pay whenever any `PUBLISHED` call exists."

        With both calls COMPLETED and no PUBLISHED call in the week, the two
        inclusion sets coincide, so both variants report 23h and 156,500 cents.

        Design: Difficulty/combinatorial_formula/overtime_tiered_pay_with_night_premium
        """
        scenario = setup_overtime_week()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01")
        quote = validate_success(resp, 200)
        assert quote["projected_hours"] == 23
        assert quote["final_hours"] == 23
        assert quote["projected_pay_cents"] == 156_500
        assert quote["final_pay_cents"] == 156_500, (
            "no PUBLISHED call exists, so the variants agree exactly"
        )


class TestPayQuoteInputSet:
    def test_pay_quote_input_set_excludes_draft_calls(self, api):
        """PRD §3.4: "The two variants differ only in which calls are included: `PROJECTED` counts calls in `PUBLISHED` or `COMPLETED`, so scheduled-but-unplayed hours count; `FINAL` counts only `COMPLETED` calls, so identical week data yields strictly lower final pay whenever any `PUBLISHED` call exists."

        Week: 12h COMPLETED + 12h PUBLISHED + 12h DRAFT. DRAFT hours are invisible
        to both variants: projected 24h (192,000), final 12h (96,000); all hours
        are regular (cap 30) and no call ends in the night window.

        Design: Corner/calculations/pay_quote_input_set_excludes_draft_calls
        """
        scenario = setup_mixed_status_week()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01")
        quote = validate_success(resp, 200)
        assert quote["projected_hours"] == 24, "COMPLETED + PUBLISHED; DRAFT excluded"
        assert quote["final_hours"] == 12, "COMPLETED only"
        assert quote["projected_pay_cents"] == 192_000, "24 * 8000, no overtime, no night"
        assert quote["final_pay_cents"] == 96_000, "12 * 8000"

    def test_night_premium_applied_only_at_2300_boundary(self, api):
        """PRD §3.4: "On top of the tiered pay, each night call — an included call whose `ends_at` time-of-day, taken in UTC, falls at or after 23:00 and before midnight — adds a flat premium of 1,500 cents."

        Week: 12h COMPLETED (ends 20:00, no premium) + 15h COMPLETED (ends 23:00,
        premium). Total 27h under the 30h cap, so no overtime contaminates the
        assertion: FINAL pay = 27*8000 + 1*1500 = 217,500.

        Design: Corner/calculations/night_premium_applied_only_at_2300_boundary
        """
        scenario = setup_night_boundary_week()
        contract = scenario["contract"]
        resp = api.get_pay_quote(contract["id"], ANY, week_start="2026-06-01", mode="FINAL")
        quote = validate_success(resp, 200)
        assert quote["final_hours"] == 27
        assert quote["final_pay_cents"] == 217_500, (
            "27 * 8000 + exactly one 1500 night premium (the 23:00-ending call only)"
        )
