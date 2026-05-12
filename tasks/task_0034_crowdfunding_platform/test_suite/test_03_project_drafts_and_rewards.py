"""Project drafting, reward tier creation, add-on item creation.

PRD references:
  - §3.2 Drafting a Project, Defining Rewards, and Adding Add-Ons
  - §2.4 Common Resource Properties
  - §2.5 Optimistic Concurrency Control
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_add_on_item,
    assert_project,
    assert_reward,
    create_add_on_item_payload,
    create_draft_project,
    create_project_payload,
    create_reward_payload,
    create_verified_initiator,
    make_initiator_headers,
    patch_project_payload,
    validate_error,
    validate_success,
)


class TestDraftProject:
    def test_create_draft_project_persists_status_draft(self, api):
        """PRD §3.2: 'The new project is persisted in DRAFT status with
        provisional_raised_cents and final_raised_cents both zero, with
        last_update_published_at and rejection_reason null, and with the
        initiator_id pinned to the calling initiator's X-User-ID.'

        Claim: POST /projects returns DRAFT, zero counters, null fields.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        from test_helpers import add_hours, DEFAULT_NOW_ISO
        deadline = add_hours(DEFAULT_NOW_ISO, 240)
        payload = create_project_payload(
            title="My Project Title",
            category="TECH",
            funding_target_cents=500_000,
            deadline=deadline,
        )
        res = api.create_project(
            payload, make_initiator_headers(initiator["id"])
        )
        data = validate_success(res, expected_status=201)
        assert_project(data)
        assert data["status"] == "DRAFT"
        assert data["provisional_raised_cents"] == 0
        assert data["final_raised_cents"] == 0
        assert data["rejection_reason"] in (None, "")
        assert data["last_update_published_at"] in (None, "")
        assert data["initiator_id"] == initiator["id"]

    @pytest.mark.parametrize("category", ["TECH", "ART", "COMMUNITY"])
    def test_create_draft_project_accepts_each_category(self, api, category):
        """PRD §3.2: 'a category chosen from TECH, ART, or COMMUNITY (which
        will later drive the commission rate)'.

        Claim: each of the three categories is a valid input.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        from test_helpers import add_hours, DEFAULT_NOW_ISO
        deadline = add_hours(DEFAULT_NOW_ISO, 240)
        res = api.create_project(
            create_project_payload(
                category=category, deadline=deadline,
            ),
            make_initiator_headers(initiator["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["category"] == category

    def test_create_project_invalid_amount_zero_funding_target(self, api):
        """PRD §3.2: 'All three positive-amount checks — on
        funding_target_cents, pledge_amount_cents, and price_cents —
        surface as ERR_INVALID_AMOUNT if the supplied value is not
        strictly greater than zero.'

        Claim: funding_target_cents=0 → ERR_INVALID_AMOUNT.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        from test_helpers import add_hours, DEFAULT_NOW_ISO
        deadline = add_hours(DEFAULT_NOW_ISO, 240)
        res = api.create_project(
            create_project_payload(
                funding_target_cents=0, deadline=deadline,
            ),
            make_initiator_headers(initiator["id"]),
        )
        validate_error(res, "ERR_INVALID_AMOUNT")

    def test_patch_project_updates_title_in_draft(self, api):
        """PRD §3.2: 'While the project remains in DRAFT, the initiator may
        continue to edit it — adjusting title, description_md, media_uris,
        risk_disclosure, funding_model, funding_target_cents, or
        deadline — under optimistic concurrency.'

        Claim: PATCH /projects/{id} updates title; version increments.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        v0 = project["version"]
        res = api.patch_project(
            project["id"],
            {"title": "Renamed Project"},
            make_initiator_headers(initiator["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["title"] == "Renamed Project"
        assert data["version"] == v0 + 1, (
            "PRD §2.4: 'version is ... incremented by exactly one on every "
            "server-side mutation.'"
        )

    def test_patch_project_version_conflict(self, api):
        """PRD §2.5: 'When the request body includes version, the server
        compares it against the current persisted version of the target
        resource; on mismatch, the request is rejected with
        ERR_VERSION_CONFLICT (HTTP 409).'

        Claim: stale version → ERR_VERSION_CONFLICT.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        # Take a successful PATCH first so the persisted version advances.
        api.patch_project(
            project["id"],
            {"title": "First update"},
            make_initiator_headers(initiator["id"]),
        )
        # Now try a stale version.
        res = api.patch_project(
            project["id"],
            patch_project_payload(version=project["version"], title="Stale"),
            make_initiator_headers(initiator["id"]),
        )
        validate_error(res, "ERR_VERSION_CONFLICT")


class TestRewardTiers:
    def test_create_reward_returns_initial_inventory_zero(self, api):
        """PRD §3.2: 'The reward's inventory_claimed is a system-maintained
        counter that starts at zero.'

        Claim: created reward has inventory_claimed=0.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        res = api.create_reward(
            project["id"],
            create_reward_payload(
                tier_label="Tier-A", pledge_amount_cents=10_000,
                reward_type="DIGITAL", inventory_limit=50,
            ),
            make_initiator_headers(initiator["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_reward(data)
        assert data["inventory_claimed"] == 0
        assert data["inventory_limit"] == 50

    def test_create_reward_unlimited_inventory_null(self, api):
        """PRD §3.2: 'an optional inventory_limit (null means unlimited)'.

        Claim: omitted inventory_limit → null in response.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        res = api.create_reward(
            project["id"],
            create_reward_payload(
                tier_label="Unlimited", pledge_amount_cents=1_000,
                reward_type="DIGITAL",
            ),
            make_initiator_headers(initiator["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data.get("inventory_limit") in (None,)

    def test_duplicate_tier_label_rejected(self, api):
        """PRD §3.2: 'Each reward carries a tier_label that must be unique
        within the project (a duplicate is rejected with
        ERR_DUPLICATE_TIER_LABEL)'.

        Claim: second reward with same tier_label → ERR_DUPLICATE_TIER_LABEL.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        api.create_reward(
            project["id"],
            create_reward_payload(
                tier_label="Bronze", pledge_amount_cents=1_000,
                reward_type="DIGITAL",
            ),
            make_initiator_headers(initiator["id"]),
        )
        res = api.create_reward(
            project["id"],
            create_reward_payload(
                tier_label="Bronze", pledge_amount_cents=2_000,
                reward_type="DIGITAL",
            ),
            make_initiator_headers(initiator["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_TIER_LABEL")

    def test_reward_zero_pledge_rejected(self, api):
        """PRD §3.2: 'All three positive-amount checks — on
        funding_target_cents, pledge_amount_cents, and price_cents —
        surface as ERR_INVALID_AMOUNT if the supplied value is not
        strictly greater than zero.'

        Claim: pledge_amount_cents=0 → ERR_INVALID_AMOUNT.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        res = api.create_reward(
            project["id"],
            create_reward_payload(
                tier_label="Cheap", pledge_amount_cents=0,
                reward_type="DIGITAL",
            ),
            make_initiator_headers(initiator["id"]),
        )
        validate_error(res, "ERR_INVALID_AMOUNT")


class TestAddOnItems:
    def test_create_add_on_item_initial_inventory_zero(self, api):
        """PRD §3.2: 'their inventory_claimed aggregates unit counts across
        all non-terminal or charged orders.' (Initial value is zero by
        construction; PRD §2.4 covers default 0 for system-maintained
        counters via the entity invariant in §3.2.)

        Claim: a freshly-created add-on item has inventory_claimed=0.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        res = api.create_add_on_item(
            project["id"],
            create_add_on_item_payload(
                name="Sticker Pack", price_cents=500,
                requires_shipping=True, inventory_limit=200,
            ),
            make_initiator_headers(initiator["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_add_on_item(data)
        assert data["inventory_claimed"] == 0
        assert data["price_cents"] == 500
        assert data["requires_shipping"] is True

    def test_add_on_zero_price_rejected(self, api):
        """PRD §3.2: 'All three positive-amount checks — on
        funding_target_cents, pledge_amount_cents, and price_cents —
        surface as ERR_INVALID_AMOUNT if the supplied value is not
        strictly greater than zero.'

        Claim: price_cents=0 → ERR_INVALID_AMOUNT.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(initiator=initiator)
        res = api.create_add_on_item(
            project["id"],
            create_add_on_item_payload(
                name="Free?", price_cents=0,
            ),
            make_initiator_headers(initiator["id"]),
        )
        validate_error(res, "ERR_INVALID_AMOUNT")
