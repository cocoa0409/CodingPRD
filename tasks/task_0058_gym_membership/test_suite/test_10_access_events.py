"""Access-events: turnstile entries and the family-share rule.

PRD §3.10.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA, SO,
    access_card,
    create_funded_member,
    create_per_visit_card_type,
    get_card,
    issue_and_activate_card,
    setup_member_with_active_card,
    validate_error,
    validate_success,
)


# ===========================================================================
# Visit consumption (PRD §3.10)
# ===========================================================================
class TestAccessEventVisitConsumption:

    def test_visit_increments_visits_consumed(self, api):
        """PRD §3.10: 'On success, the card's visits_consumed is
        incremented by one.'"""
        ct, member, card = setup_member_with_active_card(
            category="PER_VISIT",
            card_type_overrides={"visit_quota": 10},
        )
        access_card(card, member)
        after = get_card(card["id"])
        assert after["visits_consumed"] == 1

# ===========================================================================
# Family-share rule (PRD §3.10)
# ===========================================================================
class TestFamilyShareRule:

    def test_non_family_member_rejected(self, api):
        """PRD §3.10: 'When the acting member_id differs from
        Card.holder_member_id, the family-share rule applies: the
        holder and the acting member must share a non-null
        family_group_id, otherwise ERR_FAMILY_SHARE_NOT_AUTHORIZED.'"""
        ct, holder, card = setup_member_with_active_card(
            category="PER_VISIT",
            card_type_overrides={"visit_quota": 5},
            member_overrides={"family_group_id": "FAM_A"},
        )
        intruder = create_funded_member(
            wallet_balance_cents=10_000,
            family_group_id="FAM_B",
        )
        res = api.create_access_event(
            {"card_id": card["id"], "member_id": intruder["id"]},
            SO,
        )
        validate_error(res, ApiErrorId.ERR_FAMILY_SHARE_NOT_AUTHORIZED.value)
