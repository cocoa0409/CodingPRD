"""Release windows: half-open overlap, temporal input rules, the confirm
title-state gate, self-inclusive demand pricing, and ops-run expiry."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_title,
    confirm_release_window,
    create_release_window,
    create_release_window_payload,
    create_title,
    get_release_window,
    ops_run,
    run_certification_chain,
    set_clock,
    setup_approved_title,
    transition_window,
    validate_error,
    validate_paginated,
    validate_success,
)

RM_HEADERS = TEST_USERS["release_manager_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


class TestWindowCreationRules:
    def test_temporal_input_rejected(self, api):
        """PRD §3.9: "The start must be strictly after the logical clock at
        creation (`ERR_WINDOW_IN_PAST`, HTTP 400), the end must be strictly
        after the start (`ERR_INVALID_REQUEST`)"

        Design: Corner/validations/window_temporal_input_rejected
        """
        title = create_title(title_code="VAL-WIN", platform_codes=["PC"],
                             cert_budget_total_cents=1000)
        # End precedes the start.
        resp = api.create_release_window(
            create_release_window_payload(
                title["id"], "PC", "LAUNCH",
                start_utc="2026-08-10T17:00:00Z", end_utc="2026-08-10T09:00:00Z",
            ),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Start exactly at the logical clock (the fixed startup default):
        # strictly-after is required.
        resp = api.create_release_window(
            create_release_window_payload(
                title["id"], "PC", "LAUNCH",
                start_utc="2026-08-01T00:00:00Z", end_utc="2026-08-02T00:00:00Z",
            ),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


class TestWindowOverlap:
    def _setup_first_window(self):
        title = create_title(title_code="OVL-WIN", platform_codes=["PC"],
                             cert_budget_total_cents=500000)
        w1 = create_release_window(
            title["id"], "PC", "LAUNCH",
            start_utc="2026-08-10T09:00:00Z", end_utc="2026-08-10T17:00:00Z",
        )
        return title, w1

    def test_adjacent_windows_do_not_conflict_but_straddling_does(self, api):
        """PRD §2.9: "Two windows on the same platform conflict only when
        each starts strictly before the other ends; windows that merely touch
        — the existing window's end exactly equals the new window's start, or
        vice versa — do not conflict."
        PRD §2.9: "A colliding reservation is rejected with
        `ERR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/release_window_half_open_adjacency
        """
        title, _w1 = self._setup_first_window()
        # Touching the existing window's end is not an overlap.
        w2 = api.create_release_window(
            create_release_window_payload(
                title["id"], "PC", "DAY_ONE_PATCH",
                start_utc="2026-08-10T17:00:00Z", end_utc="2026-08-11T09:00:00Z",
            ),
            RM_HEADERS,
        )
        validate_success(w2, expected_status=201)
        # Straddling the boundary collides.
        w3 = api.create_release_window(
            create_release_window_payload(
                title["id"], "PC", "HOTFIX_DEPLOY",
                start_utc="2026-08-10T16:00:00Z", end_utc="2026-08-10T18:00:00Z",
            ),
            RM_HEADERS,
        )
        validate_error(w3, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_only_reserved_or_confirmed_windows_participate(self, api):
        """PRD §2.9: "Only windows in `RESERVED` or `CONFIRMED` participate
        in overlap detection; expired, released, and consumed windows never
        block anything, and no buffer is applied to release windows."

        Design: Difficulty/resource_temporal_overlap/release_window_half_open_adjacency
        """
        title, _w1 = self._setup_first_window()
        validate_success(
            api.create_release_window(
                create_release_window_payload(
                    title["id"], "PC", "DAY_ONE_PATCH",
                    start_utc="2026-08-10T17:00:00Z",
                    end_utc="2026-08-11T09:00:00Z",
                ),
                RM_HEADERS,
            ),
            expected_status=201,
        )
        resp = api.create_release_window(
            create_release_window_payload(
                title["id"], "PC", "HOTFIX_DEPLOY",
                start_utc="2026-08-10T16:00:00Z", end_utc="2026-08-10T18:00:00Z",
            ),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
        _rows, meta = validate_paginated(
            api.list_release_windows(READER_HEADERS,
                                     params={"platform_code": "PC"})
        )
        assert meta["total_count"] == 2


class TestWindowConfirmGate:
    def _setup_reserved_launch_window_on_cert_title(self):
        """Title advanced to CERTIFICATION with a RESERVED LAUNCH window."""
        title = create_title(title_code="XDEP-WIN", cert_budget_total_cents=1_000_000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        advance_title(title["id"], "CERTIFICATION")
        window = create_release_window(
            title["id"], "PS5", "LAUNCH",
            start_utc="2026-08-10T09:00:00Z", end_utc="2026-08-10T17:00:00Z",
        )
        return title, window

    def test_confirm_requires_cert_approved_title(self, api):
        """PRD §3.9: "`LAUNCH` and `DAY_ONE_PATCH` windows confirm only for a
        `CERT_APPROVED` title (`ERR_TITLE_NOT_CERT_APPROVED`);
        `HOTFIX_DEPLOY` windows confirm only for a `LAUNCHED` title
        (`ERR_TITLE_NOT_LAUNCHED`)."

        Design: Difficulty/cross_entity_state_dependency/window_confirm_requires_cert_approved_title
        """
        _title, window = self._setup_reserved_launch_window_on_cert_title()
        resp = api.transition_release_window(
            window["id"], {"to_status": "CONFIRMED"}, RM_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_CERT_APPROVED)

    def test_confirm_succeeds_and_charges_fee_after_cert_approval(self, api):
        """PRD §3.9: "`LAUNCH` and `DAY_ONE_PATCH` windows confirm only for a
        `CERT_APPROVED` title (`ERR_TITLE_NOT_CERT_APPROVED`)"
        PRD §3.9: "The charged `fee_cents` is the window's own whole-hour
        length times 5000 cents per hour times the tier multiplier, rounded
        half-up to whole cents, and the budget must cover it
        (`ERR_CERT_BUDGET_EXCEEDED`); the fee charges directly to the title's
        spent partition."

        Design: Difficulty/cross_entity_state_dependency/window_confirm_requires_cert_approved_title
        """
        title, window = self._setup_reserved_launch_window_on_cert_title()
        run_certification_chain(title["id"], "PS5")
        advance_title(title["id"], "CERT_APPROVED")
        window = transition_window(window["id"], "CONFIRMED")
        assert window["status"] == "CONFIRMED"
        # 8h x 5000 x 1.00 — the only PS5 window in its ISO week (LOW tier).
        assert window["fee_cents"] == 40000


class TestWindowDemandFee:
    def _setup_two_confirmed_pc_windows(self):
        """CERT_APPROVED title with two CONFIRMED PC LAUNCH windows in ISO
        week 32: 24h (fee 120000, LOW) and 12h (fee 60000; 24+12 < 40)."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = setup_approved_title(title_code="COMB-WIN",
                                   cert_budget_total_cents=2_000_000,
                                   title_platform_codes=["PS5", "PC"])
        w1 = confirm_release_window(
            ctx["title"]["id"], "PC", "LAUNCH",
            start_utc="2026-08-03T18:00:00Z", end_utc="2026-08-04T18:00:00Z",
        )
        w2 = confirm_release_window(
            ctx["title"]["id"], "PC", "LAUNCH",
            start_utc="2026-08-05T00:00:00Z", end_utc="2026-08-05T12:00:00Z",
        )
        w3 = create_release_window(
            ctx["title"]["id"], "PC", "LAUNCH",
            start_utc="2026-08-05T18:00:00Z", end_utc="2026-08-06T02:00:00Z",
        )
        return ctx, w1, w2, w3

    def test_self_hours_count_toward_the_tier(self, api):
        """PRD §3.9: "the new window's own length is added, so the demand
        tier keys on the total including the window itself. Below 40 total
        hours the tier is LOW with multiplier 1.00; from 40 up to but not
        including 100 hours the tier is MEDIUM with multiplier 1.25; at 100
        hours or more the tier is HIGH with multiplier 1.50."

        Design: Difficulty/combinatorial_formula/window_demand_fee_self_inclusive_tier
        """
        _ctx, _w1, _w2, w3 = self._setup_two_confirmed_pc_windows()
        w3 = transition_window(w3["id"], "CONFIRMED")
        # 36 existing + 8 self = 44 >= 40 -> MEDIUM; 8 x 5000 x 1.25 = 50000.
        assert w3["fee_cents"] == 50000

    def test_low_tier_readings_and_rejected_alternative(self, api):
        """PRD §3.9: "every other window on the same platform in `RESERVED`
        or `CONFIRMED` whose start falls in that week contributes its
        whole-hour length; the new window's own length is added, so the
        demand tier keys on the total including the window itself."

        Design: Difficulty/combinatorial_formula/window_demand_fee_self_inclusive_tier
        """
        _ctx, w1, w2, w3 = self._setup_two_confirmed_pc_windows()
        # Earlier confirms keyed on 24h and 36h totals: both LOW.
        assert w1["fee_cents"] == 120000  # 24 x 5000 x 1.00
        assert w2["fee_cents"] == 60000   # 12 x 5000 x 1.00
        w3 = transition_window(w3["id"], "CONFIRMED")
        assert w3["fee_cents"] == 50000
        # Keying the tier on existing hours only (36 < 40, LOW) would charge
        # 40000 — the rejected reading.
        assert w3["fee_cents"] != 40000


class TestWindowExpiry:
    def test_ops_run_expires_windows_past_end(self, api):
        """PRD §2.4: "A second `PlatformAdmin`-only capability performs an
        ops-run checkpoint sweep over the logical clock: every release window
        still in `RESERVED` or `CONFIRMED` whose end has passed is moved to
        `EXPIRED` (a confirmed window forfeits its fee on expiry)"
        PRD §2.4: "The sweep is the only mechanism that applies these two
        time-driven effects."

        Design: Corner/cross_cutting_layers/ops_run_expires_stale_windows
        """
        title = create_title(title_code="LYR-EXP", platform_codes=["PC"],
                             cert_budget_total_cents=1000)
        window = create_release_window(
            title["id"], "PC", "LAUNCH",
            start_utc="2026-08-05T09:00:00Z", end_utc="2026-08-05T17:00:00Z",
        )
        set_clock("2026-08-06T00:00:01Z")
        # No lazy expiry on reads: only the ops-run sweep applies it.
        assert get_release_window(window["id"])["status"] == "RESERVED"
        ops_run()
        assert get_release_window(window["id"])["status"] == "EXPIRED"
