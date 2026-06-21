"""Markdown schedule transitions, price cascades onto holds, and OCC create-supersede.

Queue A (Difficulty): transitive_cascade (markdown activate -> style -> hold).
Queue B (Corner): state_machines (unschedule revert), validations (not effective),
cross_cutting_complexity_layers (OCC stale / fresh-version supersede).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_markdown_schedule_payload,
    create_boutique, create_customer, create_style, create_variant,
    create_fitting_room, create_hold, create_scheduled_markdown, create_active_markdown,
)

MERCH = TEST_USERS["merchandiser_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]


# ─── Queue A: transitive_cascade (markdown -> style -> hold) ──────────────

def test_markdown_activate_refreshes_live_hold_price(api):
    """PRD §3.5: "Activation computes the schedule's `applied_price_cents`, writes it
    onto the style's `current_price_cents`".
    PRD §3.5: "Activation then cascades: for every `ACTIVE` or `EXTENDED` fitting-room
    hold whose variant belongs to this style, the hold's `held_price_cents` is refreshed
    to the new `current_price_cents`".

    A live hold snapshotted held_price 10000; activating a SEASONAL 30% markdown writes
    Style.current_price_cents=7000 and refreshes the hold's held_price_cents to 7000.

    Design: Difficulty/transitive_cascade/markdown_activate_cascade_depth3_style_price_to_hold
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=10000, category="DRESSES", season="WINTER")
    variant = create_variant(style["id"], size="M", color="Black", on_hand=5)
    room = create_fitting_room(bq["id"])
    hold = create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)
    assert hold["held_price_cents"] == 10000

    v0 = style["version"]
    create_active_markdown(style["id"], v0, phase="SEASONAL", markdown_pct=30, effective_date=0)

    style_after = get_success_data(api.get_style(style["id"], MERCH))
    assert style_after["current_price_cents"] == 7000

    hold_after = get_success_data(api.get_hold(hold["id"], ASSOCIATE))
    assert hold_after["held_price_cents"] == 7000


def test_markdown_activate_writes_clearance_basis_to_style(api):
    """PRD §3.5: "Activation computes the schedule's applied_price_cents, writes it onto
    the style's current_price_cents, and — if the phase is CLEARANCE — sets the style's
    clearance flag true."

    Activating a SEASONAL 30% on list 10000 writes current_price_cents=7000 and leaves
    clearance false (the cascade's source price write).

    Design: Difficulty/transitive_cascade/markdown_activate_cascade_depth3_style_price_to_hold
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=10000, category="DRESSES", season="WINTER")
    create_variant(style["id"], size="M", color="Black", on_hand=5)

    active = create_active_markdown(style["id"], style["version"],
                                    phase="SEASONAL", markdown_pct=30, effective_date=0)
    assert active["applied_price_cents"] == 7000

    style_after = get_success_data(api.get_style(style["id"], MERCH))
    assert style_after["current_price_cents"] == 7000
    assert style_after["clearance"] is False


# ─── Queue B: state_machines (unschedule revert) ──────────────────────────

def test_unschedule_reverts_to_draft_and_clears_projection(api):
    """PRD §3.5: "Scheduling a markdown (DRAFT -> SCHEDULED) computes its
    projected_price_cents, a provisional forward-looking preview, while un-scheduling
    it (SCHEDULED -> DRAFT) clears projected_price_cents back to null."

    A SCHEDULED markdown with a projected price reverts to DRAFT with
    projected_price_cents null on unschedule.

    Design: Corner/state_machines/markdown_revert_scheduled_to_draft_clears_projection
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=8000, category="TOPS", season="SPRING")
    scheduled = create_scheduled_markdown(style["id"], style["version"],
                                          phase="SEASONAL", markdown_pct=25, effective_date=0)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["projected_price_cents"] is not None

    reverted = validate_success(api.unschedule_markdown(scheduled["id"], MERCH), 200)
    assert reverted["status"] == "DRAFT"
    assert reverted["projected_price_cents"] is None


# ─── Queue B: validations (markdown not effective) ────────────────────────

def test_activate_before_effective_date_rejected(api):
    """PRD §3.5: "Activation (SCHEDULED -> ACTIVE) is permitted only when the boutique's
    current_business_date has reached or passed the schedule's effective_date; an early
    activation is rejected with ERR_MARKDOWN_NOT_EFFECTIVE (HTTP 409)."

    A schedule with effective_date 5 activated while the clock is at 0 is rejected with
    ERR_MARKDOWN_NOT_EFFECTIVE.

    Design: Corner/validations/markdown_activate_before_effective_date_rejected
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=8000, category="TOPS", season="SPRING")
    scheduled = create_scheduled_markdown(style["id"], style["version"],
                                          phase="SEASONAL", markdown_pct=20, effective_date=5)

    res = api.activate_markdown(scheduled["id"], MERCH)
    validate_error(res, ApiErrorId.ERR_MARKDOWN_NOT_EFFECTIVE.value)


# ─── Queue B: cross_cutting_complexity_layers (OCC) ───────────────────────

def test_markdown_create_with_stale_style_version_rejected(api):
    """PRD §2.7: "A create-markdown-schedule request must therefore carry an
    expected_style_version field whose value is the client's last observed version of
    the target Style. If that value does not match the style's current version ...
    the create is rejected with ERR_STALE_STYLE_VERSION (HTTP 412)".
    PRD §3.5: "Creation places the schedule in DRAFT status and supersedes any prior
    DRAFT or SCHEDULED schedule of the same style ... the create also increments the
    style's version by one."

    A first create bumps Style.version; a second create reusing the stale v0 is rejected
    with ERR_STALE_STYLE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_style_version_on_markdown_create
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=8000, category="TOPS", season="SPRING")
    v0 = style["version"]

    get_success_data(api.create_markdown_schedule(
        create_markdown_schedule_payload(style["id"], v0, phase="SEASONAL",
                                         markdown_pct=20, effective_date=0), MERCH))

    res = api.create_markdown_schedule(
        create_markdown_schedule_payload(style["id"], v0, phase="SEASONAL",
                                         markdown_pct=30, effective_date=0), MERCH)
    validate_error(res, ApiErrorId.ERR_STALE_STYLE_VERSION.value)


def test_markdown_create_with_fresh_version_supersedes_prior(api):
    """PRD §3.5: "Creation places the schedule in DRAFT status and supersedes any prior
    DRAFT or SCHEDULED schedule of the same style so that at most one schedule is live
    per style; the create also increments the style's version by one."
    PRD §3.5: "A schedule may also be retired to SUPERSEDED by the system when a newer
    schedule is created against the same style (from DRAFT or SCHEDULED)".

    Re-reading Style.version after the first create and passing the fresh version on a
    second create succeeds (DRAFT) and supersedes the prior DRAFT schedule.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_style_version_succeeds_and_supersedes
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=8000, category="TOPS", season="SPRING")
    v0 = style["version"]

    md1 = get_success_data(api.create_markdown_schedule(
        create_markdown_schedule_payload(style["id"], v0, phase="SEASONAL",
                                         markdown_pct=20, effective_date=0), MERCH))
    v1 = get_success_data(api.get_style(style["id"], MERCH))["version"]

    md2 = validate_success(api.create_markdown_schedule(
        create_markdown_schedule_payload(style["id"], v1, phase="SEASONAL",
                                         markdown_pct=30, effective_date=0), MERCH), 201)
    assert md2["status"] == "DRAFT"

    md1_after = get_success_data(api.get_markdown_schedule(md1["id"], MERCH))
    assert md1_after["status"] == "SUPERSEDED"
