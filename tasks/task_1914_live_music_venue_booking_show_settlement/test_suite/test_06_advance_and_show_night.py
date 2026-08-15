"""Advance checklist gates the ON_SALE -> ADVANCED transition."""
from test_helpers import (
    PM,
    ApiErrorId,
    advance_show,
    complete_all_advance_items,
    create_on_sale_show,
    get_show,
    set_clock,
    validate_error,
    validate_success,
)


def test_advance_complete_requires_checklist_all_true(api):
    """PRD §3.5: "When every item stands complete, the `ProductionManager`
    completes the advance, moving the show from `ON_SALE` to `ADVANCED`;
    the transition requires `all_complete` to be true and rejects
    otherwise."

    Design: Difficulty/cross_entity_state_dependency/advance_complete_requires_checklist_all_true
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
    )
    # Complete 5 of 6 items — leave w9 untouched.
    for item in ("hospitality", "tech", "backline",
                 "production_requirements", "insurance_cert"):
        validate_success(api.complete_advance_item(show["id"], item, PM), 200)

    checklist = validate_success(api.get_show_advance(show["id"], PM), 200)
    assert checklist["all_complete"] is False

    resp = api.complete_advance(show["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_show(show["id"])["status"] == "ON_SALE"


def test_advance_complete_succeeds_when_all_items_true(api):
    """PRD §3.5: "When every item stands complete, the `ProductionManager`
    completes the advance, moving the show from `ON_SALE` to `ADVANCED`; the
    transition requires `all_complete` to be true and rejects otherwise."

    Design: Difficulty/cross_entity_state_dependency/advance_complete_requires_checklist_all_true
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
    )
    advance_show(show["id"])
    checklist = validate_success(api.get_show_advance(show["id"], PM), 200)
    assert checklist["all_complete"] is True
    assert get_show(show["id"])["status"] == "ADVANCED"
