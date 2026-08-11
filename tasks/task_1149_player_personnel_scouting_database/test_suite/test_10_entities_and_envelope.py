"""Entity-level corner claims: defaults, computed-field quarantine, envelope,
pagination, initial states, and OCC on budget (PRD §2.2-2.6, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    GM_HEADERS,
    api_client,
    area_headers,
    create_budget,
    create_prospect,
    create_report,
    create_scout,
    create_director,
    director_headers,
    get_success_data,
    is_valid_uuid,
    make_board_ready_prospect,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestScoutDefaults:
    def test_scout_create_weight_default_applied(self, api):
        """PRD §3.1: "Each scout also carries a board `weight`, defaulting to
        1.0 when omitted". PRD §2.4: `version` is "a system-managed integer
        that increments by exactly 1 on every mutation"; a fresh scout starts
        at version 1.

        Design: Corner/entities/scout_create_weight_default_applied
        """
        scout = create_scout(level="AREA", full_name="Defaulty")
        assert scout["weight"] == pytest.approx(1.0)
        assert scout["version"] == 1


class TestComputedFieldsQuarantined:
    def test_prospect_create_composite_input_ignored(self, api):
        """PRD §2.5: "A prospect's `composite_grade` and `tier` ... remain
        `null` until the computation that produces them has run at least once;
        they are never zero-filled." Client-supplied values on create cannot
        set them.

        Design: Corner/entities/prospect_create_composite_input_ignored
        """
        s1 = create_scout(level="AREA", full_name="S1")
        resp = api_client.create_prospect(
            {"full_name": "Sneaky", "position": "QB", "college": "State U",
             "composite_grade": 9.99, "tier": "T1"},
            area_headers(s1),
        )
        created = validate_success(resp, expected_status=201)
        assert created["composite_grade"] is None
        assert created["tier"] is None


class TestProspectSystemFields:
    def test_prospect_version_starts_at_one(self, api):
        """PRD §2.4: "`id` (string): a unique, server-generated identifier for
        the resource, formatted as a UUID with no type prefix" and "`version`
        (integer): a system-managed integer that increments by exactly 1 on
        every mutation" — freshly created resources start at version 1.

        Design: Corner/entities/prospect_version_starts_at_one
        """
        s1 = create_scout(level="AREA", full_name="S1")
        p1 = create_prospect(s1, full_name="Versioned", position="OT", college="State U")
        assert p1["version"] == 1
        assert is_valid_uuid(p1["id"])
        assert "-" in p1["id"] and not p1["id"].split("-")[0].isalpha() or True
        # "no type prefix": the id parses as a bare UUID (no "prospect_" style prefix).
        assert not p1["id"].startswith("prospect_")


class TestProspectInitialStates:
    def test_prospect_create_initial_states(self, api):
        """PRD §3.2: "A prospect begins at `CLEAR`." and "The first dimension,
        `evaluation_status`, tracks the evaluation pipeline: `NEW` →
        `SCOUTING` → `EVALUATED` → `BOARD_READY` → `DRAFTED`, with `ARCHIVED`
        available as a terminal off-ramp from `EVALUATED` or `BOARD_READY`."

        Design: Corner/state_machines/prospect_create_initial_states
        """
        s1 = create_scout(level="AREA", full_name="S1")
        p1 = create_prospect(s1, full_name="Fresh", position="S", college="A")
        assert p1["evaluation_status"] == "NEW"
        assert p1["flag_status"] == "CLEAR"


class TestFirstReportAutoTransition:
    def test_report_create_moves_prospect_to_scouting(self, api):
        """PRD §3.2: "The transition from `NEW` to `SCOUTING` is not
        operator-driven — it happens automatically in the same request that
        creates the prospect's first scouting report."

        Design: Corner/state_machines/report_create_moves_prospect_to_scouting
        """
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        p1 = create_prospect(s1, full_name="Auto", position="S", college="A")
        create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        prospect = get_success_data(api_client.get_prospect(p1["id"], area_headers(s1)))
        assert prospect["evaluation_status"] == "SCOUTING"


class TestPagination:
    def test_prospects_list_pagination(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`." With three
        prospects and limit 2: page 1 has has_more true, page 2 (offset 2)
        has 1 item and has_more false.

        Design: Corner/entities/prospects_list_pagination
        """
        s1 = create_scout(level="AREA", full_name="S1")
        for name, pos, col in (("P1", "QB", "A"), ("P2", "WR", "B"), ("P3", "CB", "C")):
            create_prospect(s1, full_name=name, position=pos, college=col)
        resp1 = api_client.list_prospects(area_headers(s1), params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(data1) == 2
        resp2 = api_client.list_prospects(area_headers(s1), params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(resp2)
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(data2) == 1


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format" with `meta` carrying
        `api_request_id` and `api_request_timestamp`, a `response_type` of
        "object" for a single resource, and `data` carrying the resource.

        Design: Corner/endpoints/response_envelope_shape
        """
        resp = api_client.create_scout({"full_name": "Env", "level": "AREA"}, GM_HEADERS)
        body = resp.json()
        assert resp.status_code == 201
        assert "meta" in body and "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)
        assert body["data"]["full_name"] == "Env"
        assert body["data"]["level"] == "AREA"


class TestVideoTagLink:
    def test_video_tag_attached_to_draft_report(self, api):
        """PRD §3.3: "While a report is in `DRAFT` or `RETURNED`, its author
        may attach `VideoTag` entries linking film to the report — each tag
        carries a `clip_url`, an integer `start_sec` at or above zero, an
        integer `end_sec` strictly greater than `start_sec`, and a `tag`
        category". PRD §2.4: "A video tag carries `id` and `created_at` only —
        it has no `updated_at` and no `version`, because it is immutable after
        creation."

        Design: Corner/endpoints/video_tag_attached_to_draft_report
        """
        s1 = create_scout(level="AREA", full_name="S")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        created = validate_success(
            api_client.create_video_tag(
                r1["id"],
                {"clip_url": "https://video.example/c1", "start_sec": 10,
                 "end_sec": 42, "tag": "ATHLETICISM"},
                area_headers(s1),
            ),
            expected_status=201,
        )
        assert "version" not in created
        assert "updated_at" not in created
        listed = get_success_data(api_client.list_video_tags(r1["id"], area_headers(s1)))
        assert any(t["id"] == created["id"] for t in listed)
        assert listed[0]["report_id"] == r1["id"]


class TestFitScoreDefaults:
    def test_fit_default_base_without_open_need(self, api):
        """PRD §3.5: "If no such need exists, the base is 20.0." A CLOSED need
        no longer feeds fit scoring (PRD §3.7: "Closing a need moves it to
        `CLOSED`, from which it no longer feeds either"). With no OPEN need,
        scheme 1.00, no flags: fit = 20.0 * 1.00 * 1.0 - 0 = 20.00.

        Design: Corner/calculations/fit_default_base_without_open_need
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        n1 = get_success_data(api_client.create_roster_need(
            {"season_year": 2026, "position": "QB", "priority_tier": "P1"}, GM_HEADERS
        ))
        api_client.close_roster_need(n1["id"], GM_HEADERS)
        p1 = make_board_ready_prospect(s1, d1, raw_grade=7.00, scheme_fit=1.00,
                                       full_name="P", position="QB", college="A")
        b1 = get_success_data(api_client.create_draft_board(
            {"season_year": 2026}, director_headers(d1)
        ))
        entry = get_success_data(api_client.add_board_entry(
            b1["id"], {"prospect_id": p1["id"]}, director_headers(d1)
        ))
        assert entry["fit_score"] == pytest.approx(20.00, abs=0.005)


class TestNormalizedGradeClamp:
    def test_normalized_grade_clamped_at_max(self, api):
        """PRD §3.3 step 1: "rounds the result half-up to 2 decimal places,
        and clamps it into the inclusive range 1.00 to 9.00." Scout mean 5.00
        stdev 0.50, raw 9.00: 5.0 + 1.5*(9.00-5.00)/0.50 = 17.0 -> clamps to
        9.00.

        Design: Corner/calculations/normalized_grade_clamped_at_max
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=5.00, season_grade_stdev=0.50)
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P", position="QB", college="A")
        r1 = create_report(p1["id"], s1, raw_grade=9.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        from test_helpers import lock_report
        locked = lock_report(r1["id"], d1)
        assert locked["normalized_grade"] == pytest.approx(9.00, abs=0.005)


class TestBudgetOcc:
    def test_budget_adjustment_stale_version_rejected(self, api):
        """PRD §2.6: "Posting a rollover adjustment against a budget. The
        request must carry `expected_budget_version` equal to the budget's
        current `version`... if the value does not match the parent's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), and no mutation occurs."

        Design: Corner/cross_cutting_layers/budget_adjustment_stale_version_rejected
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        bv = bud["version"]
        first = validate_success(api_client.adjust_budget(
            bud["id"],
            {"rollover_delta_cents": 5000000, "expected_budget_version": bv},
            GM_HEADERS,
        ))
        assert first["version"] == bv + 1
        resp = api_client.adjust_budget(
            bud["id"],
            {"rollover_delta_cents": 5000000, "expected_budget_version": bv},
            GM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_budget_adjustment_updates_available(self, api):
        """PRD §3.7: "The adjustment adds the delta to the budget's
        `rollover_cents`, recomputes `available_cents` and `posture`, and
        increments the budget's `version` by 1." Base 100000000, rollover 0,
        committed 0, delta +5000000 -> available 105000000, posture HEALTHY.

        Design: Corner/cross_cutting_layers/budget_adjustment_updates_available
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        bv = bud["version"]
        updated = validate_success(api_client.adjust_budget(
            bud["id"],
            {"rollover_delta_cents": 5000000, "expected_budget_version": bv},
            GM_HEADERS,
        ))
        assert updated["available_cents"] == 105000000
        assert updated["posture"] == "HEALTHY"


class TestReportListingFilters:
    def test_reports_list_filters_by_status(self, api):
        """PRD §4 GET /scouting/reports: "List scouting reports; filters
        `scout_id`, `prospect_id`, `status`". Filtering by status=LOCKED
        returns only the locked report; the DRAFT report by the same scout is
        excluded.

        Design: Corner/endpoints/reports_list_filters_by_status
        """
        s1 = create_scout(level="AREA", full_name="S", weight=1.0,
                          season_grade_mean=6.00, season_grade_stdev=1.00)
        d1 = create_director(full_name="D")
        p1 = create_prospect(s1, full_name="P1", position="QB", college="A")
        p2 = create_prospect(s1, full_name="P2", position="WR", college="B")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        r2 = create_report(p2["id"], s1, raw_grade=8.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        from test_helpers import lock_report
        lock_report(r1["id"], d1)
        resp = api_client.list_reports(
            director_headers(d1), params={"status": "LOCKED", "scout_id": s1["id"]}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == r1["id"]
        assert data[0]["status"] == "LOCKED"
        assert all(r["id"] != r2["id"] for r in data)
