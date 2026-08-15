"""Deadline extensions: windows, eligibility, caps, grants, and the hard stop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_extension,
    decide_extension,
    get_holdback,
    get_work_order,
    list_extensions,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
BUYER = TEST_USERS["buyer_1_headers"]
SELLER = TEST_USERS["seller_1_headers"]


class TestExtensionWindows:
    def test_extension_window_open_on_deadline_date(self, api):
        """PRD §3.6: "the request must arrive while the clock date is on or before the `effective_deadline_date` — a request lodged on the deadline date itself is allowed, one lodged after it fails with `ERR_EXTENSION_WINDOW_CLOSED`"

        Design: Corner/validations/extension_window_open_on_deadline_date
        """
        ctx = setup_active_holdback(repair_scope="Siding")
        set_logical_clock("2026-09-15T12:00:00Z")

        created = validate_success(
            api.create_extension_request(
                {"holdback_id": ctx["holdback"]["id"], "reason": "WEATHER_EXTERIOR",
                 "requested_days": 3, "evidence_ref": "NOAA log"},
                SELLER),
            201,
        )
        assert created["status"] == "PENDING"

    def test_extension_after_deadline_rejected(self, api):
        """PRD §3.6: "the request must arrive while the clock date is on or before the `effective_deadline_date` — a request lodged on the deadline date itself is allowed, one lodged after it fails with `ERR_EXTENSION_WINDOW_CLOSED`"

        One day past the effective deadline the create fails.

        Design: Corner/validations/extension_after_deadline_rejected
        """
        ctx = setup_active_holdback(repair_scope="Siding")
        set_logical_clock("2026-09-16T00:00:00Z")

        resp = api.create_extension_request(
            {"holdback_id": ctx["holdback"]["id"], "reason": "WEATHER_EXTERIOR",
             "requested_days": 3, "evidence_ref": "NOAA log"},
            BUYER,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED)

    def test_weather_extension_requires_exterior_flag(self, api):
        """PRD §3.6: "a `WEATHER_EXTERIOR` request requires the holdback's `exterior_work_flag` to be true, failing with `ERR_EXTENSION_NOT_WEATHER_ELIGIBLE` on interior-only scopes"

        Design: Corner/validations/weather_extension_requires_exterior_flag
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z",
                                    repair_scope="Interior drywall",
                                    exterior_work_flag=False)

        resp = api.create_extension_request(
            {"holdback_id": ctx["holdback"]["id"], "reason": "WEATHER_EXTERIOR",
             "requested_days": 5, "evidence_ref": "NOAA log"},
            BUYER,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_WEATHER_ELIGIBLE)


class TestExtensionGrantMath:
    def test_nested_min_caps_partial_grant(self, api):
        """PRD §3.6: "A grant is computed, never taken at face value: the granted days are the smallest of four quantities — the `requested_days`; a per-request cap of 21 days when the reason is `WEATHER_EXTERIOR` and 7 days for any other reason; the remaining lifetime allowance, which is 45 days minus the sum of granted days across all previously `GRANTED` requests of the holdback; and the hard-stop headroom, the number of whole days from the current `effective_deadline_date` to the `hard_stop_date`."

        After a 14-day grant (min(14, 21, 45, 30)), a 21-day weather request is
        clamped by hard-stop headroom: min(21, 21, 31, 16) == 16.

        Design: Difficulty/combinatorial_formula/extension_grant_nested_min_caps
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z",
                                    repair_scope="Exterior paint and siding")
        hb_id = ctx["holdback"]["id"]

        ext1 = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                                requested_days=14, evidence_ref="NOAA storm log A")
        granted1 = decide_extension(ext1["id"], "GRANTED")
        assert granted1["granted_days"] == 14, "min(14, 21, 45, 30)"

        ext2 = create_extension(hb_id, SELLER, reason="WEATHER_EXTERIOR",
                                requested_days=21, evidence_ref="NOAA storm log B")
        granted2 = decide_extension(ext2["id"], "GRANTED")
        assert granted2["granted_days"] == 16, (
            "min(21, 21, 31, 16) — clamped by hard_stop headroom, not requested or cap"
        )

    def test_nested_min_caps_cumulative_deadline(self, api):
        """PRD §3.6: "Otherwise the request stores its computed `granted_days`, stamps `decided_at`, and the holdback absorbs the extension: `granted_extension_days` grows by the granted amount, `effective_deadline_date` is recomputed as `work_deadline_date` plus the total granted days"
        PRD §3.6: "The hard stop is absolute — no sequence of grants may push the effective deadline past `hard_stop_date`."

        After grants of 14 and 16 the cumulative extension is 30 days and the
        effective deadline lands exactly on the 2026-10-15 hard stop.

        Design: Difficulty/combinatorial_formula/extension_grant_nested_min_caps
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z",
                                    repair_scope="Exterior paint and siding")
        hb_id = ctx["holdback"]["id"]

        ext1 = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                                requested_days=14, evidence_ref="NOAA storm log A")
        decide_extension(ext1["id"], "GRANTED")
        ext2 = create_extension(hb_id, SELLER, reason="WEATHER_EXTERIOR",
                                requested_days=21, evidence_ref="NOAA storm log B")
        decide_extension(ext2["id"], "GRANTED")

        hb = get_holdback(hb_id)
        assert hb["granted_extension_days"] == 30
        assert hb["effective_deadline_date"] == "2026-10-15", (
            "2026-09-15 + 14d + 16d lands exactly on the hard stop"
        )

    def test_non_weather_extension_capped_at_seven(self, api):
        """PRD §3.6: "a per-request cap of 21 days when the reason is `WEATHER_EXTERIOR` and 7 days for any other reason"

        A 14-day SUPPLY_DELAY request clamps to 7 even though the total cap
        (45) and hard-stop headroom (30) allow more.

        Design: Corner/validations/non_weather_extension_capped_at_seven
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z")
        ext = create_extension(ctx["holdback"]["id"], BUYER, reason="SUPPLY_DELAY",
                               requested_days=14, evidence_ref="supplier letter")
        granted = decide_extension(ext["id"], "GRANTED")
        assert granted["granted_days"] == 7, "min(14, 7, 45, 30)"
        assert get_holdback(ctx["holdback"]["id"])["effective_deadline_date"] == "2026-09-22"

    def test_hard_stop_zero_grant_rejected(self, api):
        """PRD §3.6: "If that computed grant is not at least one full day, the grant is rejected with `ERR_EXTENSION_EXCEEDS_HARD_STOP` and nothing changes."

        With the deadline equal to the hard stop the headroom is zero, so the
        grant fails and the request stays PENDING with granted_days null.

        Design: Corner/validations/hard_stop_zero_grant_rejected
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z",
                                    repair_scope="Drywall",
                                    hard_stop_date="2026-09-15",
                                    exterior_work_flag=False)
        ext = create_extension(ctx["holdback"]["id"], BUYER, reason="OTHER",
                               requested_days=7, evidence_ref="owner note")

        resp = api.decide_extension_request(ext["id"], {"decision": "GRANTED"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_EXCEEDS_HARD_STOP)

        exts = {e["id"]: e for e in list_extensions(ctx["holdback"]["id"])}
        assert exts[ext["id"]]["status"] == "PENDING"
        assert exts[ext["id"]]["granted_days"] is None

    def test_effective_deadline_reconciles_after_grant(self, api):
        """PRD §3.6: "`granted_extension_days` grows by the granted amount, `effective_deadline_date` is recomputed as `work_deadline_date` plus the total granted days, and the work order's `completion_deadline_date` mirrors the new effective deadline."
        PRD §3.3: "its `completion_deadline_date` always mirrors the holdback's `effective_deadline_date`, including after extensions."

        Design: Corner/complexity_layers/effective_deadline_reconciles_after_grant
        """
        ctx = setup_engagement(clock="2026-09-01T00:00:00Z", repair_scope="Siding")
        hb_id = ctx["holdback"]["id"]
        assert ctx["work_order"]["completion_deadline_date"] == "2026-09-15"

        ext = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                               requested_days=10, evidence_ref="NOAA log")
        granted = decide_extension(ext["id"], "GRANTED")
        assert granted["granted_days"] == 10

        hb = get_holdback(hb_id)
        assert hb["granted_extension_days"] == 10
        assert hb["effective_deadline_date"] == "2026-09-25"
        wo = get_work_order(hb_id)
        assert wo["completion_deadline_date"] == "2026-09-25", (
            "the work order mirrors the extended deadline"
        )


class TestExtensionDecisionDiscipline:
    def test_extension_double_decide_rejected(self, api):
        """PRD §3.6: "The request must be `PENDING`; re-deciding a decided or cancelled request is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/extension_double_decide_rejected
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z",
                                    repair_scope="Siding")
        ext = create_extension(ctx["holdback"]["id"], BUYER,
                               reason="WEATHER_EXTERIOR", requested_days=5,
                               evidence_ref="NOAA log")
        granted = decide_extension(ext["id"], "GRANTED")
        assert granted["granted_days"] == 5

        again = api.decide_extension_request(ext["id"], {"decision": "DENIED"}, OFFICER)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        exts = {e["id"]: e for e in list_extensions(ctx["holdback"]["id"])}
        assert exts[ext["id"]]["status"] == "GRANTED"
        assert exts[ext["id"]]["granted_days"] == 5

    def test_pending_constraint_wins_over_temporal_window(self, api):
        """PRD §2.9: "When several checks could fail on the same request, the server evaluates them in a fixed order and returns the error of the first check that fails; later checks are never evaluated once an earlier one has fired."
        PRD §2.9: "Cardinality and uniqueness on creation endpoints: one holdback per escrow file (`ERR_HOLDBACK_ALREADY_EXISTS`), one `SUBMITTED` bid per contractor per holdback (`ERR_BID_ALREADY_SUBMITTED`), no bid creation once a selection exists (`ERR_WORK_ORDER_EXISTS`), one `SUBMITTED` draw at a time (`ERR_DRAW_ALREADY_OPEN`), one `PENDING` extension at a time (`ERR_EXTENSION_ALREADY_PENDING`), one `OPEN` dispute at a time (`ERR_DISPUTE_ALREADY_OPEN`) — all HTTP 409."
        PRD §2.9: "Temporal windows: extension creation requires the clock date on or before the effective deadline (`ERR_EXTENSION_WINDOW_CLOSED`)"

        With one extension still PENDING and the clock past the deadline, the
        cardinality check (listed ahead of temporal windows) reports first.

        Design: Difficulty/priority_pair_validation_conflict/extension_pending_constraint_before_temporal
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z")
        hb_id = ctx["holdback"]["id"]

        set_logical_clock("2026-09-10T00:00:00Z")
        ext1 = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                                requested_days=5, evidence_ref="NOAA log")
        set_logical_clock("2026-09-16T00:00:00Z")

        resp = api.create_extension_request(
            {"holdback_id": hb_id, "reason": "SUPPLY_DELAY", "requested_days": 3,
             "evidence_ref": "supplier letter"},
            SELLER,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_PENDING)

    def test_pending_extension_untouched_by_rejected_second_create(self, api):
        """PRD §3.6: "at most one `PENDING` request may exist at a time (`ERR_EXTENSION_ALREADY_PENDING`)."
        PRD §2.9: "Cardinality and uniqueness on creation endpoints: one holdback per escrow file (`ERR_HOLDBACK_ALREADY_EXISTS`), one `SUBMITTED` bid per contractor per holdback (`ERR_BID_ALREADY_SUBMITTED`), no bid creation once a selection exists (`ERR_WORK_ORDER_EXISTS`), one `SUBMITTED` draw at a time (`ERR_DRAW_ALREADY_OPEN`), one `PENDING` extension at a time (`ERR_EXTENSION_ALREADY_PENDING`), one `OPEN` dispute at a time (`ERR_DISPUTE_ALREADY_OPEN`) — all HTTP 409."

        After the rejected second create (past the deadline), the original
        request is still the only extension and remains PENDING.

        Design: Difficulty/priority_pair_validation_conflict/extension_pending_constraint_before_temporal
        """
        ctx = setup_active_holdback(clock="2026-09-01T00:00:00Z")
        hb_id = ctx["holdback"]["id"]

        set_logical_clock("2026-09-10T00:00:00Z")
        ext1 = create_extension(hb_id, BUYER, reason="WEATHER_EXTERIOR",
                                requested_days=5, evidence_ref="NOAA log")
        set_logical_clock("2026-09-16T00:00:00Z")
        api.create_extension_request(
            {"holdback_id": hb_id, "reason": "SUPPLY_DELAY", "requested_days": 3,
             "evidence_ref": "supplier letter"},
            SELLER,
        )

        exts = list_extensions(hb_id)
        assert len(exts) == 1, "no second request was created"
        assert exts[0]["id"] == ext1["id"]
        assert exts[0]["status"] == "PENDING"
        assert get_holdback(hb_id)["status"] == "ACTIVE"
