"""Work orders: quote arithmetic, SLA clock bases, confirmation gates,
amendments under OCC, expiry sweep, and SLA breach sweep (PRD §3.2, §2.5, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_work_order,
    confirm_order,
    conform_track,
    create_cleared_media,
    create_client,
    create_media,
    create_track,
    create_work_order,
    deliver_order,
    finalize_qc,
    get_success_data,
    make_client_headers,
    quote_order,
    run_sweep,
    set_clock,
    setup_in_production_order,
    start_production,
    track_submit_and_enqueue,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import EDITOR, INTAKE, OPS, SCHED

MONDAY = "2026-08-03T10:00:00Z"


def _quote_price(api, work_order_id):
    data = validate_success(api.quote_work_order(work_order_id, INTAKE))
    assert_work_order(data)
    return data


class TestSlaClockBasis:
    """Difficulty: two orders, identical duration and confirm instant, diverge
    purely because the tier selects the clock basis."""

    def _confirm_pair(self, api):
        set_clock(MONDAY)
        client = create_client(name="FCC Client", compliance_standard="FCC_BROADCAST")
        m_a = create_cleared_media(client["id"], title="Prog A", duration_seconds=3600,
                                   frame_rate="FPS_29_97_DF")
        m_b = create_cleared_media(client["id"], title="Prog B", duration_seconds=3600,
                                   frame_rate="FPS_29_97_DF")
        wo_a = create_work_order(client["id"], m_a["id"], turnaround_tier="EXPRESS")
        quote_order(wo_a["id"])
        wo_b = create_work_order(client["id"], m_b["id"], turnaround_tier="RUSH")
        quote_order(wo_b["id"])
        due_a = validate_success(
            api.confirm_work_order(wo_a["id"], make_client_headers(client["id"])))
        due_b = validate_success(
            api.confirm_work_order(wo_b["id"], make_client_headers(client["id"])))
        return due_a, due_b

    def test_express_uses_business_hours(self, api):
        """PRD §3.2: "`STANDARD` and `EXPRESS` consume hours only inside business
        windows — Monday through Friday, 09:00 up to 17:00 UTC, eight hours per
        day, weekends skipped — and if confirmation lands outside a window, the
        clock starts at the next window open."
        PRD §3.2: "For `EXPRESS`, it is 48 hours covering the first sixty
        minutes, plus 12 hours per further started hour."

        Design: Difficulty/dual_variant_calc/sla_clock_basis_business_vs_wall
        """
        due_a, _ = self._confirm_pair(api)
        # 60-minute EXPRESS order confirmed Mon 10:00: 7h Mon + 40h Tue-Mon + 1h Tue.
        assert_same_instant(due_a["due_at"], "2026-08-11T10:00:00Z")

    def test_rush_uses_wall_clock_and_diverges(self, api):
        """PRD §3.2: "`RUSH` and `SAME_DAY` consume wall-clock hours
        continuously, weekends included."
        PRD §3.2: "For `RUSH`, it is 24 hours covering the first thirty minutes,
        plus 6 hours for each further started thirty-minute block."

        Design: Difficulty/dual_variant_calc/sla_clock_basis_business_vs_wall
        """
        due_a, due_b = self._confirm_pair(api)
        # 60-minute RUSH order: 24h + 6h * ceil(30/30) = 30 wall hours.
        assert_same_instant(due_b["due_at"], "2026-08-04T16:00:00Z")
        assert due_a["due_at"] != due_b["due_at"], (
            "identical inputs must diverge under the tier-selected clock basis"
        )


class TestQuoteEvaluationOrder:
    """Difficulty: multiplier-before-discount pinned; ytd read at quote time."""

    def _setup_ytd_client_and_second_order(self, api):
        set_clock(MONDAY)
        client = create_client(name="508 Client", compliance_standard="SECTION_508")
        # Deliver one 300000-second STANDARD order for THIS client.
        m_1 = create_cleared_media(client["id"], title="Long Program",
                                   duration_seconds=300000, frame_rate="FPS_24")
        wo_1 = create_work_order(client["id"], m_1["id"], turnaround_tier="STANDARD")
        quote_order(wo_1["id"])
        confirm_order(wo_1["id"], client["id"])
        start_production(wo_1["id"])
        t_1 = create_track(wo_1["id"], author="editor-1")
        track_submit_and_enqueue(t_1["id"], author="editor-1")
        finalize_qc(t_1["id"], total_words=40000, minor_errors=100)
        conform_track(t_1["id"], author="editor-1")
        deliver_order(wo_1["id"])
        # Fresh 91-minute (5460s) EXPRESS order in DRAFT.
        m_2 = create_cleared_media(client["id"], title="Show 91",
                                   duration_seconds=5460, frame_rate="FPS_24")
        wo_2 = create_work_order(client["id"], m_2["id"], turnaround_tier="EXPRESS")
        return client, wo_1, wo_2

    def test_ytd_reconciles_on_deliver(self, api):
        """PRD §3.2: "the client's `ytd_completed_minutes` grows by the program's
        `duration_seconds` divided by sixty and rounded up to a whole minute."

        Design: Difficulty/combinatorial_formula/quote_evaluation_order_pinned
        """
        client, _, _ = self._setup_ytd_client_and_second_order(api)
        fetched = validate_success(api.get_client(client["id"], OPS))
        assert fetched["ytd_completed_minutes"] == 5000, (
            f"expected ceil(300000/60) == 5000 ytd minutes, got {fetched['ytd_completed_minutes']}"
        )

    def test_quote_multiplies_before_discounting(self, api):
        """PRD §3.2: "Applying the multiplier before the discount is mandatory;
        reversing those two steps changes the cents whenever the tiered amount
        times the discount percentage is non-integral."
        PRD §3.2: "Fourth, a volume discount is read from the owning client's
        `ytd_completed_minutes` **as it stands at quote time**: at least 10000
        minutes earns ten percent off, at least 5000 earns five percent,
        otherwise none".

        Design: Difficulty/combinatorial_formula/quote_evaluation_order_pinned
        """
        _, _, wo_2 = self._setup_ytd_client_and_second_order(api)
        quoted = _quote_price(api, wo_2["id"])
        # duration 91m -> 10500 + 18000 + 250 = 28750; *1.50 = 43125;
        # 5% off -> ROUND_HALF_UP(40968.75) = 40969; + 15000 setup = 55969.
        assert quoted["quoted_price_cents"] == 55969, (
            f"pinned evaluation order yields 55969, got {quoted['quoted_price_cents']}"
        )


class TestQuoteBrackets:
    def test_bracket_boundary_90_vs_91(self, api):
        """PRD §3.2: "Second, a duration charge accumulates across three marginal
        brackets: the first thirty minutes at 350 cents each, the next sixty
        minutes at 300 cents each, and every minute beyond ninety at 250 cents
        each."
        PRD §3.2: "Fifth, `quoted_price_cents` is the sum of a 15000-cent setup
        fee, the discounted amount, and a language fee of 5000 cents for any
        `language` other than en-US (zero for en-US)."

        Design: Corner/calculations/quote_bracket_boundary_90_vs_91
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        m_90 = create_media(client["id"], title="M90", duration_seconds=5400,
                            frame_rate="FPS_24")
        m_91 = create_media(client["id"], title="M91", duration_seconds=5460,
                            frame_rate="FPS_24")
        wo_90 = create_work_order(client["id"], m_90["id"], turnaround_tier="STANDARD")
        wo_91 = create_work_order(client["id"], m_91["id"], turnaround_tier="STANDARD")
        q_90 = _quote_price(api, wo_90["id"])
        q_91 = _quote_price(api, wo_91["id"])
        # 90 min: 10500 + 18000 = 28500; *1.00; +15000 -> 43500 (no third bracket).
        assert q_90["quoted_price_cents"] == 43500
        # 91 min: one minute at the 250c marginal rate -> 28750 + 15000 -> 43750.
        assert q_91["quoted_price_cents"] == 43750

    def test_volume_discount_boundary_4999_vs_5000(self, api):
        """PRD §3.2: "Fourth, a volume discount is read from the owning client's
        `ytd_completed_minutes` **as it stands at quote time**: at least 10000
        minutes earns ten percent off, at least 5000 earns five percent,
        otherwise none; the discounted amount is again rounded half-up to a
        whole cent."

        Design: Corner/calculations/quote_volume_discount_boundary
        """
        set_clock(MONDAY)

        def _client_with_ytd(long_duration_seconds):
            client = create_client(name="Vol", compliance_standard="INTERNAL")
            m1 = create_cleared_media(client["id"], title="Long",
                                      duration_seconds=long_duration_seconds,
                                      frame_rate="FPS_24")
            wo1 = create_work_order(client["id"], m1["id"], turnaround_tier="STANDARD")
            quote_order(wo1["id"])
            confirm_order(wo1["id"], client["id"])
            start_production(wo1["id"])
            t1 = create_track(wo1["id"], author="editor-1")
            track_submit_and_enqueue(t1["id"], author="editor-1")
            finalize_qc(t1["id"], total_words=10000, minor_errors=100)
            conform_track(t1["id"], author="editor-1")
            deliver_order(wo1["id"])
            return client

        client_a = _client_with_ytd(299940)   # ceil -> 4999 minutes
        client_b = _client_with_ytd(300000)   # exactly 5000 minutes
        for client, expected in ((client_a, 25500), (client_b, 24975)):
            m2 = create_media(client["id"], title="Short", duration_seconds=1800,
                              frame_rate="FPS_24")
            wo2 = create_work_order(client["id"], m2["id"], turnaround_tier="STANDARD")
            q = _quote_price(api, wo2["id"])
            assert q["quoted_price_cents"] == expected, (
                f"30-minute STANDARD quote must be {expected}, got {q['quoted_price_cents']}"
            )


class TestSlaWeekendRollover:
    def test_express_friday_confirm_rolls_over_weekend(self, api):
        """PRD §3.2: "`STANDARD` and `EXPRESS` consume hours only inside business
        windows — Monday through Friday, 09:00 up to 17:00 UTC, eight hours per
        day, weekends skipped — and if confirmation lands outside a window, the
        clock starts at the next window open."
        PRD §3.2: "For `EXPRESS`, it is 48 hours covering the first sixty
        minutes, plus 12 hours per further started hour."

        Design: Corner/calculations/sla_weekend_rollover_business_hours
        """
        # Friday 16:00, one business hour left; the clock is set BEFORE quoting
        # so the 72-hour quote expiry (PRD §3.2) does not lapse before confirm.
        set_clock("2026-08-07T16:00:00Z")
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_cleared_media(client["id"], duration_seconds=1800)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="EXPRESS")
        quote_order(wo["id"])
        confirmed = validate_success(
            api.confirm_work_order(wo["id"], make_client_headers(client["id"])))
        # 1h Fri + 40h the following Mon-Fri + 7h the final Monday.
        assert_same_instant(confirmed["due_at"], "2026-08-17T16:00:00Z")


class TestSameDayTierDuration:
    def test_sameday_boundary_60_ok_61_rejected(self, api):
        """PRD §2.8: "The `SAME_DAY` tier is reserved for short programs: a work
        order naming `SAME_DAY` for media longer than sixty minutes is rejected
        at creation, and again at amendment, with `ERR_TIER_DURATION_INCOMPATIBLE`
        (HTTP 422)."

        Design: Corner/entities/work_order_sameday_tier_duration_boundary
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        m_ok = create_media(client["id"], title="Exactly60", duration_seconds=3600)
        m_over = create_media(client["id"], title="SixtyOne", duration_seconds=3660)
        ok = validate_success(api.create_work_order(
            {"client_id": client["id"], "media_asset_id": m_ok["id"],
             "service_type": "CAPTIONS", "turnaround_tier": "SAME_DAY",
             "language": "en-US"}, INTAKE), expected_status=201)
        assert ok["order_status"] == "DRAFT"
        resp = api.create_work_order(
            {"client_id": client["id"], "media_asset_id": m_over["id"],
             "service_type": "CAPTIONS", "turnaround_tier": "SAME_DAY",
             "language": "en-US"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_TIER_DURATION_INCOMPATIBLE)


class TestComputedFieldsIgnored:
    def test_injected_quoted_price_is_overwritten_by_quote(self, api):
        """PRD §3.2: "The quote computes `quoted_price_cents` and sets
        `quote_expires_at` to seventy-two hours after the quote instant."

        Design: Corner/entities/work_order_computed_fields_input_ignored
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_media(client["id"], duration_seconds=3600)
        payload = {"client_id": client["id"], "media_asset_id": media["id"],
                   "service_type": "CAPTIONS", "turnaround_tier": "EXPRESS",
                   "language": "en-US", "quoted_price_cents": 999}
        wo = validate_success(api.create_work_order(payload, INTAKE), expected_status=201)
        quoted = _quote_price(api, wo["id"])
        # 60 min EXPRESS: 19500 * 1.5 = 29250; + 15000 = 44250.
        assert quoted["quoted_price_cents"] == 44250, (
            "the server-computed quote must replace any client-supplied value"
        )


class TestConfirmGates:
    def test_confirm_requires_media_cleared(self, api):
        """PRD §3.2: "Confirmation is the client's act: a `ClientContact` whose
        `X-User-ID` equals the order's `client_id` confirms a `QUOTED` order,
        provided the client is `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`), the
        confirm instant precedes `quote_expires_at` (at or after expiry the
        attempt is rejected with `ERR_QUOTE_EXPIRED`, HTTP 409), and the
        referenced media asset is `CLEARED` (else `ERR_MEDIA_NOT_CLEARED`,
        HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_media_cleared
        """
        set_clock(MONDAY)
        client = create_client(name="FCC Client", compliance_standard="FCC_BROADCAST")
        media = create_media(client["id"], duration_seconds=3600)
        get_success_data(api.begin_inspection(media["id"], INTAKE))  # left INSPECTING
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        resp = api.confirm_work_order(wo["id"], make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_MEDIA_NOT_CLEARED)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["order_status"] == "QUOTED"

    def test_confirm_succeeds_once_media_cleared(self, api):
        """PRD §3.2: "Confirmation runs the turnaround-window calculation and
        stamps `due_at`."
        PRD §3.2: "For `STANDARD`, the allowance is 120 hours covering the first
        sixty minutes, plus 24 additional hours for each further started hour of
        program."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_media_cleared
        """
        set_clock(MONDAY)
        client = create_client(name="FCC Client", compliance_standard="FCC_BROADCAST")
        media = create_media(client["id"], duration_seconds=3600)
        get_success_data(api.begin_inspection(media["id"], INTAKE))
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        validate_error(api.confirm_work_order(wo["id"], make_client_headers(client["id"])),
                       ApiErrorId.ERR_MEDIA_NOT_CLEARED)
        get_success_data(api.clear_media(media["id"], INTAKE))
        confirmed = validate_success(
            api.confirm_work_order(wo["id"], make_client_headers(client["id"])))
        assert confirmed["order_status"] == "CONFIRMED"
        # STANDARD 60 min = 120 business hours from Mon 10:00 -> Mon 2026-08-24 10:00.
        assert_same_instant(confirmed["due_at"], "2026-08-24T10:00:00Z")

    def test_temporal_beats_referential_on_confirm(self, api):
        """PRD §2.4: "Requests are validated in a fixed order, and the first
        failing check determines the rejection: authentication of the two
        headers comes first, then role authorization, then resolution of path
        identifiers and body foreign keys from left to right (a dangling
        reference yields `ERR_NOT_FOUND`), then entity-backed ownership
        (`ERR_FORBIDDEN_OWNERSHIP`), then request shape and field constraints
        (`ERR_VALIDATION`), then optimistic concurrency, then state-machine
        admissibility (`ERR_INVALID_TRANSITION`), then segregation-of-duties and
        compliance rules, then temporal windows, then capacity and geometry
        constraints, and finally linked-entity state preconditions."
        PRD §3.2: "the confirm instant precedes `quote_expires_at` (at or after
        expiry the attempt is rejected with `ERR_QUOTE_EXPIRED`, HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_confirm
        """
        set_clock(MONDAY)
        client = create_client(name="FCC Client", compliance_standard="FCC_BROADCAST")
        media = create_media(client["id"], duration_seconds=3600)
        get_success_data(api.begin_inspection(media["id"], INTAKE))  # never cleared
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        set_clock("2026-08-06T10:00:00Z")  # exactly quote_expires_at
        resp = api.confirm_work_order(wo["id"], make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)

    def test_temporal_rejection_leaves_order_quoted(self, api):
        """PRD §3.2: "the confirm instant precedes `quote_expires_at` (at or
        after expiry the attempt is rejected with `ERR_QUOTE_EXPIRED`,
        HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_confirm
        """
        set_clock(MONDAY)
        client = create_client(name="FCC Client", compliance_standard="FCC_BROADCAST")
        media = create_media(client["id"], duration_seconds=3600)
        get_success_data(api.begin_inspection(media["id"], INTAKE))
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        set_clock("2026-08-06T10:00:00Z")
        validate_error(api.confirm_work_order(wo["id"], make_client_headers(client["id"])),
                       ApiErrorId.ERR_QUOTE_EXPIRED)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["order_status"] == "QUOTED", (
            "the sweep never ran, so the order stays QUOTED after the failed confirm"
        )

    def test_confirm_twice_invalid(self, api):
        """PRD §2.4: "then state-machine admissibility (`ERR_INVALID_TRANSITION`)".
        PRD §3.2: "Confirmation runs the turnaround-window calculation and
        stamps `due_at`."

        Design: Corner/state_machines/work_order_confirm_twice_invalid
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_cleared_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        first = validate_success(
            api.confirm_work_order(wo["id"], make_client_headers(client["id"])))
        assert first["order_status"] == "CONFIRMED"
        assert_same_instant(first["due_at"], "2026-08-24T10:00:00Z")
        resp = api.confirm_work_order(wo["id"], make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert_same_instant(after["due_at"], "2026-08-24T10:00:00Z")

    def test_suspended_client_blocked_confirm_and_live(self, api):
        """PRD §3.1: "A client that is not `ACTIVE` cannot confirm quotes and
        cannot have live events scheduled — both attempts are rejected with
        `ERR_CLIENT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/suspended_client_blocked_confirm_and_live
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_cleared_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quote_order(wo["id"])
        get_success_data(api.suspend_client(client["id"], OPS))

        resp1 = api.confirm_work_order(wo["id"], make_client_headers(client["id"]))
        validate_error(resp1, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)
        resp2 = api.create_live_event(
            {"client_id": client["id"], "title": "E", "channel_id": "CH1",
             "start_at": "2026-08-10T14:00:00Z", "end_at": "2026-08-10T15:00:00Z",
             "required_certification": "CERT_CBC"}, SCHED)
        validate_error(resp2, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["order_status"] == "QUOTED"
        events = get_success_data(api.list_live_events(OPS, params={"client_id": client["id"]}))
        assert isinstance(events, list) and len(events) == 0


class TestDeliverGate:
    def test_deliver_before_ready_invalid(self, api):
        """PRD §3.2: "Delivery is an `OperationsManager` act that moves
        `READY_FOR_DELIVERY` → `DELIVERED`".
        PRD §2.4: "then state-machine admissibility (`ERR_INVALID_TRANSITION`)".

        Design: Corner/state_machines/work_order_deliver_before_ready_invalid
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL",
                                        turnaround_tier="STANDARD")
        resp = api.deliver_work_order(ctx["work_order"]["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        after = validate_success(api.get_work_order(ctx["work_order"]["id"], OPS))
        assert after["order_status"] == "IN_PRODUCTION"
        assert after["delivered_at"] is None


class TestAmendOcc:
    def test_amend_requotes_and_bumps_version(self, api):
        """PRD §3.2: "An `IntakeCoordinator` may also amend a `DRAFT` or `QUOTED`
        order's `turnaround_tier` or `language` under the OCC rule of §2.5;
        amendment increments the order's `version`, and when the order is
        `QUOTED` the quote is recomputed and `quote_expires_at` resets to
        seventy-two hours from the amendment."

        Design: Corner/cross_cutting_layers/occ_work_order_amend_stale
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="EXPRESS")
        quoted = _quote_price(api, wo["id"])
        assert quoted["quoted_price_cents"] == 44250
        amended = validate_success(api.amend_work_order(
            wo["id"],
            {"turnaround_tier": "RUSH",
             "expected_work_order_version": quoted["version"]},
            INTAKE))
        # 60 min RUSH: 19500 * 2.0 = 39000; + 15000 = 54000.
        assert amended["quoted_price_cents"] == 54000
        assert amended["turnaround_tier"] == "RUSH"
        assert amended["version"] == quoted["version"] + 1, (
            "amendment must increment the work order version by exactly one"
        )

    def test_amend_with_stale_version_rejected(self, api):
        """PRD §2.5: "Amending a work order's `turnaround_tier` or `language`
        likewise requires `expected_work_order_version` to match the order's
        current `version`; a mismatch is rejected with
        `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_work_order_amend_stale
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="EXPRESS")
        quoted = _quote_price(api, wo["id"])
        get_success_data(api.amend_work_order(
            wo["id"], {"turnaround_tier": "RUSH",
                       "expected_work_order_version": quoted["version"]}, INTAKE))
        resp = api.amend_work_order(
            wo["id"], {"language": "es-US",
                       "expected_work_order_version": quoted["version"]}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["language"] == "en-US", "the rejected amend must not apply"

    def test_immediate_read_after_amend(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "when the order is `QUOTED` the quote is recomputed and
        `quote_expires_at` resets to seventy-two hours from the amendment."

        Design: Corner/consistency_model/immediate_read_after_amend
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="EXPRESS")
        quoted = _quote_price(api, wo["id"])
        assert quoted["quoted_price_cents"] == 44250
        amended = validate_success(api.amend_work_order(
            wo["id"], {"turnaround_tier": "RUSH",
                       "expected_work_order_version": quoted["version"]}, INTAKE))
        assert amended["turnaround_tier"] == "RUSH"
        assert amended["quoted_price_cents"] == 54000
        fetched = validate_success(api.get_work_order(wo["id"], SCHED))
        assert fetched["turnaround_tier"] == amended["turnaround_tier"]
        assert fetched["quoted_price_cents"] == amended["quoted_price_cents"]


class TestSweeps:
    def test_quote_expiry_sweep_and_requote(self, api):
        """PRD §2.7: "quotes past their expiry move `QUOTED` → `QUOTE_EXPIRED`".
        PRD §3.2: "Quoting is performed by an `IntakeCoordinator` and moves
        `DRAFT` → `QUOTED` or, for an expired quote, `QUOTE_EXPIRED` → `QUOTED`
        — re-quoting is always permitted. The quote computes `quoted_price_cents`
        and sets `quote_expires_at` to seventy-two hours after the quote instant."

        Design: Corner/validations/quote_expiry_sweep_and_requote
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="STANDARD")
        quoted = _quote_price(api, wo["id"])
        assert_same_instant(quoted["quote_expires_at"], "2026-08-06T10:00:00Z")

        set_clock("2026-08-06T10:00:00Z")
        sweep = run_sweep()
        assert sweep["expired_quote_count"] == 1
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["order_status"] == "QUOTE_EXPIRED"

        requoted = _quote_price(api, wo["id"])
        assert requoted["order_status"] == "QUOTED"
        assert_same_instant(requoted["quote_expires_at"], "2026-08-09T10:00:00Z")

    def test_sweep_sla_breach_marking(self, api):
        """PRD §2.7: "work orders whose `due_at` has passed while the order sits
        `CONFIRMED`, `IN_PRODUCTION`, or `READY_FOR_DELIVERY` are marked with
        `sla_breached` set true".
        PRD §3.2: "For `RUSH`, it is 24 hours covering the first thirty minutes,
        plus 6 hours for each further started thirty-minute block."

        Design: Corner/cross_cutting_layers/sweep_sla_breach_marking
        """
        set_clock(MONDAY)
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        media = create_cleared_media(client["id"], duration_seconds=3600)
        wo = create_work_order(client["id"], media["id"], turnaround_tier="RUSH")
        quote_order(wo["id"])
        confirm_order(wo["id"], client["id"])
        start_production(wo["id"])

        set_clock("2026-08-04T15:59:59Z")  # one second before due_at 16:00:00
        sweep0 = run_sweep()
        assert sweep0["sla_breach_count"] == 0
        set_clock("2026-08-04T16:00:01Z")  # one second after due_at
        sweep1 = run_sweep()
        assert sweep1["sla_breach_count"] == 1
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["sla_breached"] is True
