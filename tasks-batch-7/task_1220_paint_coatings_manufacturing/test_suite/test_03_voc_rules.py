"""VOC rule governance: half-open window overlap, adjacency, and the
wildcard-versus-state scoping of the overlap key."""

import test_helpers as fx
from test_helpers import ApiErrorId, REGULATORY_CLERK, validate_error, validate_success


def test_voc_rule_adjacent_window_activates(api):
    """PRD §3.2: "Activation is refused with `ERR_INVALID_REQUEST` if the
    window itself is malformed, and refused with `ERR_VOC_RULE_OVERLAP` if
    any already-`ACTIVE` rule with the same category and state code has a
    half-open window that intersects the new rule's window — where
    intersection respects the half-open semantics, so two rules whose windows
    merely touch, one ending exactly when the other begins, are allowed to
    coexist."

    Design: Difficulty/resource_temporal_overlap/voc_rule_half_open_window_overlap
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    r1 = fx.create_active_voc_rule(
        category="NONFLAT", state_code="CA", max_voc_gpl=100,
        effective_from="2026-01-01", effective_to="2027-06-01",
    )
    assert r1["status"] == "ACTIVE"

    # The successor starts exactly when R1 ends: adjacency, not overlap.
    r2 = fx.create_active_voc_rule(
        category="NONFLAT", state_code="CA", max_voc_gpl=50,
        effective_from="2027-06-01",
    )
    assert r2["status"] == "ACTIVE"


def test_voc_rule_intersecting_window_rejected_but_wildcard_coexists(api):
    """PRD §3.2: "Activation is refused with `ERR_INVALID_REQUEST` if the
    window itself is malformed, and refused with `ERR_VOC_RULE_OVERLAP` if
    any already-`ACTIVE` rule with the same category and state code has a
    half-open window that intersects the new rule's window — where
    intersection respects the half-open semantics, so two rules whose windows
    merely touch, one ending exactly when the other begins, are allowed to
    coexist."
    PRD §3.2: "Each rule pairs a `category` — one of the five product
    categories — with a `state_code`, either a two-letter state code or the
    wildcard `*` for the national fallback, and sets `max_voc_gpl`, the
    maximum VOC grams per liter the rule allows."

    Design: Difficulty/resource_temporal_overlap/voc_rule_half_open_window_overlap
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    fx.create_active_voc_rule(
        category="NONFLAT", state_code="CA", max_voc_gpl=100,
        effective_from="2026-01-01", effective_to="2027-06-01",
    )
    fx.create_active_voc_rule(
        category="NONFLAT", state_code="CA", max_voc_gpl=50,
        effective_from="2027-06-01",
    )

    # R3's window [2027-05-01, 2028-01-01) genuinely intersects R2's window.
    r3 = validate_success(
        api.create_voc_rule(
            fx.create_voc_rule_payload(
                category="NONFLAT", state_code="CA", max_voc_gpl=60,
                effective_from="2027-05-01", effective_to="2028-01-01",
            ),
            REGULATORY_CLERK,
        ),
        expected_status=201,
    )
    overlap = api.activate_voc_rule(r3["id"], REGULATORY_CLERK)
    validate_error(overlap, ApiErrorId.ERR_VOC_RULE_OVERLAP.value, 409)

    # A wildcard rule geometrically overlapping both CA rules is keyed on a
    # different (category, state_code) pair and activates cleanly.
    r4 = fx.create_active_voc_rule(
        category="NONFLAT", state_code="*", max_voc_gpl=250,
        effective_from="2026-06-01", effective_to="2027-01-01",
    )
    assert r4["status"] == "ACTIVE"
