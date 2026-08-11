"""Pump-order PATCH: optimistic concurrency, member ownership, re-pricing."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_prescription,
    create_pump_item,
    create_pump_order_payload,
    make_member_headers,
    set_clock,
    setup_pending_order,
    setup_pending_order_verified,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPumpOrderOcc:
    def test_second_patch_with_stale_version_rejected(self, api, care_coordinator_headers):
        """PRD §2.4: "Updating a pump order requires `expected_pump_order_version`,
        carrying the `version` of the `PumpOrder` the client last observed. If the order's
        current `version` differs — because a qualification, a cascade, or another writer
        advanced it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), rather
        than silently overwriting state the client never saw."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_pump_order_patch
        """
        ctx = setup_pending_order()
        observed_version = ctx["order"]["version"]
        first = validate_success(
            api.patch_pump_order(
                ctx["order"]["id"],
                {"shipping_address": "20 V St Apt 2",
                 "expected_pump_order_version": observed_version},
                care_coordinator_headers,
            ), 200
        )
        assert first["shipping_address"] == "20 V St Apt 2"

        res = api.patch_pump_order(
            ctx["order"]["id"],
            {"shipping_address": "20 V St Apt 3",
             "expected_pump_order_version": observed_version},
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_stale_patch_leaves_order_at_first_write(self, api, care_coordinator_headers):
        """PRD §2.4: "a `version` integer that starts at 1 on creation and increments by
        exactly 1 on every state transition, compensating action, cascade touch, or field
        mutation of that entity."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_pump_order_patch
        """
        ctx = setup_pending_order()
        observed_version = ctx["order"]["version"]
        validate_success(
            api.patch_pump_order(
                ctx["order"]["id"],
                {"shipping_address": "20 V St Apt 2",
                 "expected_pump_order_version": observed_version},
                care_coordinator_headers,
            ), 200
        )
        api.patch_pump_order(
            ctx["order"]["id"],
            {"shipping_address": "20 V St Apt 3",
             "expected_pump_order_version": observed_version},
            care_coordinator_headers,
        )
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["version"] == observed_version + 1
        assert order["shipping_address"] == "20 V St Apt 2"


class TestMemberOwnershipPath:
    def test_member_creates_and_patches_own_order(self, api, care_coordinator_headers):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
        acting `Member`; ownership checks on any resource that references a `Member`
        compare the resource's `member_id` field (or the member id carried in the path) to
        `X-User-ID`."
        PRD §3.2: "The same actors may also revise the order's pump model or
        `shipping_address` while it is `PENDING_QUALIFICATION`."

        Design: Corner/rbac/member_creates_and_patches_own_order
        """
        ctx = setup_pending_order_verified()
        alt_pump = create_pump_item(sku="PUMP-ALT", name="AltPump", unit_price_cents=32000)
        member_headers = make_member_headers(ctx["member"]["id"])
        order = validate_success(
            api.create_pump_order(
                {
                    "member_id": ctx["member"]["id"],
                    "policy_id": ctx["policy"]["id"],
                    "prescription_id": ctx["rx"]["id"],
                    "pump_item_id": ctx["pump"]["id"],
                    "shipping_address": "19 V St",
                },
                member_headers,
            ), 201
        )
        patched = validate_success(
            api.patch_pump_order(
                order["id"],
                {"pump_item_id": alt_pump["id"],
                 "expected_pump_order_version": order["version"]},
                member_headers,
            ), 200
        )
        assert patched["pump_item_id"] == alt_pump["id"]
        assert patched["version"] == order["version"] + 1

    def test_member_pump_swap_reprices_primary_line(self, api, care_coordinator_headers):
        """PRD §3.2: "Swapping `pump_item_id` re-prices the primary line and re-runs the
        bundle discount".

        Design: Corner/rbac/member_creates_and_patches_own_order
        """
        ctx = setup_pending_order_verified()
        alt_pump = create_pump_item(sku="PUMP-ALT", name="AltPump", unit_price_cents=32000)
        member_headers = make_member_headers(ctx["member"]["id"])
        order = validate_success(
            api.create_pump_order(
                {
                    "member_id": ctx["member"]["id"],
                    "policy_id": ctx["policy"]["id"],
                    "prescription_id": ctx["rx"]["id"],
                    "pump_item_id": ctx["pump"]["id"],
                    "shipping_address": "19 V St",
                },
                member_headers,
            ), 201
        )
        patched = validate_success(
            api.patch_pump_order(
                order["id"],
                {"pump_item_id": alt_pump["id"],
                 "expected_pump_order_version": order["version"]},
                member_headers,
            ), 200
        )
        assert patched["merchandise_subtotal_cents"] == 32000


class TestQualifyValidationPriority:
    def test_state_error_wins_over_temporal_on_cancelled_order(
        self, api, insurance_specialist_headers, care_coordinator_headers
    ):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, evaluated
        in strict priority order. When several violations exist, the earliest category wins
        and determines the error returned" — state preconditions (category 6) precede
        temporal rules (category 8), so a cancelled order reports ERR_INVALID_STATE even
        when its prescription's expiration has also passed.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_qualify_cancelled_order
        """
        ctx = setup_pending_order_verified()
        validate_success(api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers),
                         200)
        set_clock("2026-10-02T00:00:00Z")  # past the prescription's 2026-10-01 expiration
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "CANCELLED"

    def test_state_error_fires_regardless_of_temporal_condition(
        self, api, insurance_specialist_headers, care_coordinator_headers
    ):
        """PRD §3.8: "A patient or coordinator may cancel a pump order while it is
        `PENDING_QUALIFICATION` or `QUALIFIED`; anything further along is locked
        (`ERR_INVALID_STATE`)." Terminal-state lockdown is a pure state precondition,
        independent of any temporal rule.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_qualify_cancelled_order
        """
        ctx = setup_pending_order_verified()
        validate_success(api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers),
                         200)
        # Clock stays at the startup instant (2026-05-01), well before expiration.
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestOrderListPagination:
    def test_pump_order_list_paginates(self, api, care_coordinator_headers):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and
        `offset`. The `limit` parameter defaults to 10, must be at least 1, and must be at
        most 100. The `offset` parameter defaults to 0. Results are always sorted by
        `created_at` in ascending order. The `meta` block of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`".

        Design: Corner/endpoints/pump_order_list_filter_and_pagination
        """
        member_ctx = setup_pending_order_verified(
            policy_overrides={"pump_allowance_per_period": 2}
        )
        # One order already exists from setup; add a second with a fresh prescription.
        rx2 = create_prescription(member_ctx["member"]["id"], issued_date="2026-04-16")
        validate_success(
            api.create_pump_order(
                create_pump_order_payload(
                    member_ctx["member"]["id"], member_ctx["policy"]["id"], rx2["id"],
                    member_ctx["pump"]["id"], shipping_address="16 V St",
                ),
                care_coordinator_headers,
            ), 201
        )
        data, meta = validate_paginated(
            api.list_pump_orders(care_coordinator_headers, params={"limit": 1, "offset": 0})
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        data2, meta2 = validate_paginated(
            api.list_pump_orders(care_coordinator_headers, params={"limit": 1, "offset": 1})
        )
        assert len(data2) == 1
        assert meta2["has_more"] is False
