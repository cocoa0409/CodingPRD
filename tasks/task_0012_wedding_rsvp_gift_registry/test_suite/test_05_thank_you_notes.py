"""Thank-you notes: completion score (with pinned rounding order), empty-set
boundary, cross-entity blocked-by-purchase-state (note hard-deleted)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_purchase_payload,
    make_couple_headers,
    make_platform_integration_headers,
    set_clock,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_with_open_registry,
    bootstrap_confirmed_purchase,
    get_thank_you_note_for_purchase,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula / thank_you_completion_nested_rounding_order
# ─────────────────────────────────────────────────────────────────────────────

def test_thank_you_completion_nested_rounding_order(api):
    """PRD §3.6: "The weights are pinned: a `SENT` note counts for 1.00, a
    `DRAFTED` note counts for 0.40, and a `PENDING` note counts for 0.00."
    PRD §3.6: "The completion percentage `completion_pct`, when `n_total` is
    greater than zero, is the raw weighted sum divided by `n_total`,
    multiplied by 100, and then rounded half-up to exactly two decimal places
    (the rounding-order pin from §2.7 applies: aggregate at full precision,
    divide, multiply, and round only once at the end)."

    Design: Difficulty/combinatorial_formula/thank_you_completion_nested_rounding_order
    """
    set_clock("2027-02-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w3",
        clock_iso="2027-02-01T00:00:00Z",
        target_quantity=5,
        sku="BLENDER",
    )
    couple = make_couple_headers("couple_w3")
    integ = make_platform_integration_headers()

    purchases = []
    for ext, name, hour in [("A1", "Alice", 10), ("A2", "Bob", 11), ("A3", "Carol", 12)]:
        p = validate_success(api.create_purchase(
            item["id"],
            create_purchase_payload(
                platform_code="STORE_A", external_purchase_id=ext,
                purchaser_name=name, quantity=1,
                occurred_at=f"2027-02-02T{hour:02d}:00:00Z",
            ),
            integ,
        ), expected_status=201)
        purchases.append(p)

    # Look up each auto-created ThankYouNote.
    notes = [get_thank_you_note_for_purchase(wedding, p["id"]) for p in purchases]
    for n in notes:
        assert n is not None, "Every CONFIRMED purchase must have a PENDING ThankYouNote"

    # First note: draft then send (SENT).
    validate_success(api.draft_thank_you_note(notes[0]["id"], "Thank you Alice.", couple),
                     expected_status=200)
    validate_success(api.send_thank_you_note(notes[0]["id"], couple), expected_status=200)
    # Second note: draft only (DRAFTED).
    validate_success(api.draft_thank_you_note(notes[1]["id"], "Thank you Bob.", couple),
                     expected_status=200)
    # Third note: leave PENDING.

    report = validate_success(api.get_thank_you_report(wedding["id"], couple),
                              expected_status=200)
    assert report["n_total"] == 3
    assert report["n_sent"] == 1
    assert report["n_drafted"] == 1
    assert report["n_pending"] == 1
    # S_raw = 1*1.00 + 1*0.40 + 1*0.00 = 1.40 ; (1.40/3) * 100 ≈ 46.6666...
    # rounded half-up to 2 decimals = 46.67.
    assert report["completion_pct"] == pytest.approx(46.67, abs=0.005)
    assert report["is_complete"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / cross_entity_state_dependency / thank_you_draft_blocked_by_purchase_state
# ─────────────────────────────────────────────────────────────────────────────

def test_thank_you_draft_blocked_by_purchase_state(api):
    """PRD §3.6: "If a parent `Purchase` is cancelled and its `ThankYouNote`
    had previously been created, that note is hard-deleted as part of the
    cancel cascade (§3.5) — there is no soft-delete state for orphaned
    thank-yous."
    PRD §2.5: "The server validates path identifiers strictly left-to-right
    and returns `ERR_NOT_FOUND` (HTTP 404) for the **leftmost** identifier
    that fails to resolve to a live row."

    Design: Difficulty/cross_entity_state_dependency/thank_you_draft_blocked_by_purchase_state
    """
    set_clock("2028-01-01T00:00:00Z")
    wedding, item, purchase, note = bootstrap_confirmed_purchase(
        couple_user_id="couple_w14",
        clock_iso="2028-01-01T00:00:00Z",
        target_quantity=2,
        quantity=1,
    )
    couple = make_couple_headers("couple_w14")
    assert note is not None
    fulfilled_pre = validate_success(api.get_registry_item(item["id"], couple),
                                     expected_status=200)
    validate_success(api.cancel_purchase(
        purchase["id"], fulfilled_pre["version"], couple,
    ), expected_status=200)

    res = api.draft_thank_you_note(note["id"], "Thanks Fred", couple)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    after_purchase = validate_success(api.get_purchase(purchase["id"], couple),
                                      expected_status=200)
    assert after_purchase["status"] == "CANCELLED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations / thank_you_completion_empty_set_returns_one_hundred
# ─────────────────────────────────────────────────────────────────────────────

def test_thank_you_completion_empty_set_returns_one_hundred(api):
    """PRD §3.6: "When `n_total` is zero — a wedding with no confirmed
    purchases yet — `completion_pct` is exactly 100.00, on the principle
    that an empty registry is trivially complete."
    PRD §3.6: "The boundary flag `is_complete` is true if and only if
    `n_sent` equals `n_total` and `n_total` is strictly greater than zero."

    Design: Corner/calculations/thank_you_completion_empty_set_returns_one_hundred
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_zr")
    couple = make_couple_headers("couple_zr")

    report = validate_success(api.get_thank_you_report(wedding["id"], couple),
                              expected_status=200)
    assert report["n_total"] == 0
    assert report["n_sent"] == 0
    assert report["n_drafted"] == 0
    assert report["n_pending"] == 0
    assert report["completion_pct"] == pytest.approx(100.00, abs=0.005)
    assert report["is_complete"] is False
