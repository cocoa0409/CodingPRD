"""Event phase ladder gates, uninspected-item blocking, and markdown windows."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_PRESALE_START,
    advance_phase,
    assert_markdown_rule,
    book_and_check_in,
    close_intake,
    create_event,
    create_item_for,
    create_markdown_rule_payload,
    create_slot,
    drop_off_item,
    get_event,
    inspect_pass,
    open_intake,
    open_transaction,
    register_consignor,
    register_volunteer,
    scan_barcode,
    set_clock,
    setup_item_on_floor,
    validate_error,
    validate_success,
)


class TestPhaseLadder:

    def test_advance_skipping_phase_rejected(self, api, organizer_headers):
        """PRD §2.7: "Phases advance only through an explicit advance-phase action naming the exact next phase in `to_phase`; attempting to skip a phase, or to advance into any phase other than the immediate successor, is rejected with `ERR_EVENT_PHASE_MISMATCH` (HTTP 409)."

        Design: Corner/state_machines/event_advance_skipping_phase_rejected
        """
        event = create_event()
        set_clock("2026-06-03T18:00:00Z")  # clock satisfies intake_end

        resp = api.advance_phase(event["id"], {"to_phase": "INTAKE_CLOSED"},
                                 organizer_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_PHASE_MISMATCH)
        assert get_event(event["id"])["phase"] == "DRAFT", (
            "A rejected advance must leave the phase unchanged"
        )

    def test_advance_to_presale_blocked_by_uninspected_items(self, api, organizer_headers):
        """PRD §3.5: "advancing the event from `INTAKE_CLOSED` to `PRESALE_DAY` requires the clock to have reached `presale_start` and also requires that no item of the event remain in `DROPPED_OFF`; any uninspected stragglers block the advance with `ERR_UNINSPECTED_ITEMS_REMAIN`."

        Design: Corner/state_machines/advance_to_presale_blocked_by_uninspected_items
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Ann")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], consignor["id"])
        item = create_item_for(consignor["id"], price_cents=500)
        drop_off_item(item["id"], consignor["id"])
        close_intake(event["id"])
        set_clock(CLOCK_PRESALE_START)

        resp = api.advance_phase(event["id"], {"to_phase": "PRESALE_DAY"},
                                 organizer_headers)
        validate_error(resp, ApiErrorId.ERR_UNINSPECTED_ITEMS_REMAIN)
        assert get_event(event["id"])["phase"] == "INTAKE_CLOSED", (
            "The advance must be blocked while an item remains DROPPED_OFF"
        )


class TestMarkdownWindows:

    def test_invalid_window_rejected(self, api, organizer_headers):
        """PRD §3.1: "The window must be internally valid — `effective_from` strictly before `effective_to` — or the create is rejected with `ERR_INVALID_TIME_WINDOW`; the same error applies to any windowed resource whose start is not strictly before its end."

        Design: Corner/entities/markdown_rule_invalid_window_rejected
        """
        event = create_event()
        resp = api.create_markdown_rule(
            create_markdown_rule_payload(
                event["id"],
                effective_from="2026-06-06T00:00:00Z",
                effective_to="2026-06-05T00:00:00Z",
                discount_pct=50,
            ),
            organizer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_overlap_rejected_but_adjacent_allowed(self, api, organizer_headers):
        """PRD §3.1: "Within one event, markdown windows must not overlap: a new rule is rejected with `ERR_MARKDOWN_WINDOW_OVERLAP` whenever an existing rule's `effective_from` falls before the new rule's `effective_to` and the new rule's `effective_from` falls before the existing rule's `effective_to`."
        PRD §3.1: "Because windows are half-open, back-to-back windows — one rule's `effective_to` exactly equal to the next rule's `effective_from` — are allowed, and this non-overlap guarantee means at most one markdown rule is ever in effect at a scan instant."

        Design: Corner/complexity_layers/markdown_overlap_rejected_but_adjacent_allowed
        """
        event = create_event()
        r1 = validate_success(
            api.create_markdown_rule(
                create_markdown_rule_payload(
                    event["id"], "2026-06-05T00:00:00Z", "2026-06-06T00:00:00Z", 25
                ),
                organizer_headers,
            ),
            expected_status=201,
        )
        assert_markdown_rule(r1)

        overlapping = api.create_markdown_rule(
            create_markdown_rule_payload(
                event["id"], "2026-06-05T12:00:00Z", "2026-06-07T00:00:00Z", 50
            ),
            organizer_headers,
        )
        validate_error(overlapping, ApiErrorId.ERR_MARKDOWN_WINDOW_OVERLAP)

        adjacent = validate_success(
            api.create_markdown_rule(
                create_markdown_rule_payload(
                    event["id"], "2026-06-06T00:00:00Z", "2026-06-07T00:00:00Z", 50
                ),
                organizer_headers,
            ),
            expected_status=201,
        )
        assert adjacent["discount_pct"] == 50, (
            "A back-to-back window (effective_from == prior effective_to) must be allowed"
        )


class TestMarkdownAtScan:

    def test_markdown_skipped_for_discount_ineligible_item(self, api, organizer_headers):
        """PRD §3.8: "the `markdown_pct_applied` is the `discount_pct` of the event's markdown rule whose window contains the scan instant — `effective_from` inclusive, `effective_to` exclusive — and 0 when no rule matches or when the item's `discount_eligible` flag is false, regardless of any matching window."

        Design: Corner/calculations/markdown_skipped_for_discount_ineligible_item
        """
        ctx = setup_item_on_floor(
            price_cents=1000,
            item_overrides={"title": "NoReduce", "discount_eligible": False},
            markdown={
                "effective_from": "2026-06-05T00:00:00Z",
                "effective_to": "2026-06-08T00:00:00Z",
                "discount_pct": 50,
            },
        )
        tx = open_transaction(ctx["event"]["id"])
        line = scan_barcode(tx["id"], ctx["barcode"])

        assert line["markdown_pct_applied"] == 0, (
            "A discount-ineligible item must ignore even an active markdown rule"
        )
        assert line["line_price_cents"] == 1000
        assert line["final_line_cents"] == 1000

    def test_markdown_window_boundary_half_open(self, api, organizer_headers):
        """PRD §3.8: "the `markdown_pct_applied` is the `discount_pct` of the event's markdown rule whose window contains the scan instant — `effective_from` inclusive, `effective_to` exclusive — and 0 when no rule matches or when the item's `discount_eligible` flag is false, regardless of any matching window."
        PRD §3.8: "The `line_price_cents` is the tag price reduced by that percentage, rounded half-up to whole cents."

        Design: Corner/calculations/markdown_window_boundary_half_open
        """
        # sale_start set equal to the markdown's effective_from so a scan can
        # land exactly on the window's inclusive boundary.
        event = create_event(sale_start="2026-06-05T00:00:00Z")
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Ann")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], consignor["id"])
        item_a = create_item_for(consignor["id"], price_cents=1000, title="A")
        item_b = create_item_for(consignor["id"], price_cents=1000, title="B")
        drop_off_item(item_a["id"], consignor["id"])
        drop_off_item(item_b["id"], consignor["id"])
        inspector = register_volunteer(event["id"], "Insp Ira")
        inspect_pass(item_a["id"], inspector["id"])
        inspect_pass(item_b["id"], inspector["id"])
        validate_success(
            api.create_markdown_rule(
                create_markdown_rule_payload(
                    event["id"], "2026-06-05T00:00:00Z", "2026-06-06T00:00:00Z", 10
                ),
                organizer_headers,
            ),
            expected_status=201,
        )
        close_intake(event["id"])
        set_clock(CLOCK_PRESALE_START)
        advance_phase(event["id"], "PRESALE_DAY")
        set_clock("2026-06-05T00:00:00Z")  # == effective_from and == sale_start
        advance_phase(event["id"], "SALE_ACTIVE")

        tx = open_transaction(event["id"])
        line_a = scan_barcode(tx["id"], item_a["barcode"])
        assert line_a["markdown_pct_applied"] == 10, (
            "A scan exactly at effective_from (inclusive) must get the markdown"
        )
        assert line_a["line_price_cents"] == 900  # 1000 * 0.90

        set_clock("2026-06-06T00:00:00Z")  # == effective_to (exclusive)
        line_b = scan_barcode(tx["id"], item_b["barcode"])
        assert line_b["markdown_pct_applied"] == 0, (
            "A scan exactly at effective_to (exclusive) must get no markdown"
        )
        assert line_b["line_price_cents"] == 1000
