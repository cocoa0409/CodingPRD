"""Error breadth: one fixture drives six status families — 401, 403, 404, 412, 409 and 422 —
and every rejection carries the same envelope, a distinct identifier, and no state change."""
from test_helpers import (
    ADJUDICATOR,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_error_envelope,
    lot_version,
    read_listing,
    read_lot,
    read_plan,
    reimbursement_claim_payload,
    removal_order_payload,
    request_removal,
    setup_received_lot,
    validate_error,
    validate_paginated,
)


class TestEveryStatusFamilyUsesTheSameEnvelope:
    """A 60-unit lot with one requested removal, then seven deliberate failures."""

    def _sixty_units_with_a_five_unit_removal_already_requested(self) -> dict:
        ctx = setup_received_lot(units=60)
        ctx["stale_lot_version"] = lot_version(ctx["lot_id"], ctx["seller_id"])
        ctx["removal"] = request_removal(
            ctx["lot_id"], ctx["seller_id"], 5,
            expected_inventory_lot_version=ctx["stale_lot_version"],
            removal_method="DISPOSAL", unit_pool="FULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        return ctx

    def _seven_rejections(self, ctx: dict) -> list:
        return [
            (api_client.get_seller(ctx["seller_id"], {}),
             ApiErrorId.ERR_UNAUTHENTICATED.value, 401),
            (api_client.create_storage_billing_run(
                {"run_note": "seller tries to bill the platform"}, ctx["seller_headers"]),
             ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403),
            (api_client.get_reimbursement_claim(NON_EXISTENT_UUID, ADJUDICATOR),
             ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404),
            (api_client.create_removal_order(
                removal_order_payload(
                    ctx["lot_id"], ctx["stale_lot_version"], 5,
                    removal_method="DISPOSAL", unit_pool="FULFILLABLE",
                    removal_window_start="2026-09-10T00:00:00Z",
                    removal_window_end="2026-09-11T00:00:00Z",
                ),
                ctx["seller_headers"]),
             ApiErrorId.ERR_STALE_LOT_VERSION.value, 412),
            (api_client.ship_plan(ctx["plan"]["id"], {}, ctx["seller_headers"]),
             ApiErrorId.ERR_PLAN_NOT_CONFIRMED.value, 409),
            (api_client.reinstate_sku_listing(
                ctx["listing_id"], {}, ctx["seller_headers"]),
             ApiErrorId.ERR_LISTING_NOT_SUPPRESSED.value, 409),
            (api_client.file_reimbursement_claim(
                reimbursement_claim_payload(
                    ctx["lot_id"], "DAMAGED_WAREHOUSE", 5, 3, "EV-X"
                ),
                ctx["seller_headers"]),
             ApiErrorId.ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS.value, 422),
        ]

    def test_six_status_families_each_carry_their_own_identifier_and_a_message(self):
        """Missing headers, the wrong role, an unknown claim, a stale lot guard, two state
        refusals and an empty pool all answer in the same shape with seven distinct codes.

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."
        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/error_envelope_uniform_across_status_families_returns_4XX
        """
        ctx = self._sixty_units_with_a_five_unit_removal_already_requested()
        seen = []
        statuses = set()
        for response, expected_id, expected_status in self._seven_rejections(ctx):
            body = assert_error_envelope(response)
            assert response.status_code == expected_status, (
                f"{expected_id} must carry HTTP {expected_status}, "
                f"got {response.status_code}"
            )
            assert body["error_id"] == expected_id
            assert body["message"].strip()
            seen.append(body["error_id"])
            statuses.add(response.status_code)

        assert len(set(seen)) == 7, f"error ids must be pairwise distinct, got {seen}"
        assert sorted(statuses) == [401, 403, 404, 409, 412, 422]

    def test_none_of_the_seven_rejections_moves_any_state(self):
        """Only the setup removal ever touched the lot, so its version, its pools, the plan's
        status and the listing's status all stand exactly where they were.

        PRD 2.6: "Because several operations are guarded by many rules at once, the order of
        evaluation is part of the contract: the first rule that fails determines the response,
        and no later rule may mask an earlier one."
        PRD 2.10: "If `expected_inventory_lot_version` does not equal the lot's current
        `version`, the request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). A successful
        removal-order creation increments the lot's `version` by 1."

        Design: Corner/errors/error_envelope_uniform_across_status_families_returns_4XX
        """
        ctx = self._sixty_units_with_a_five_unit_removal_already_requested()
        for response, expected_id, expected_status in self._seven_rejections(ctx):
            validate_error(response, expected_id, expected_status)

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["version"] == ctx["stale_lot_version"] + 1
        assert lot["fulfillable_units"] == 55
        assert lot["units_reserved_for_removal"] == 5

        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["status"] == "RECEIVED_COMPLETE"
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["listing_status"] == "ACTIVE"

        _claims, claim_meta = validate_paginated(
            api_client.list_lot_reimbursement_claims(ctx["lot_id"], ctx["seller_headers"])
        )
        assert claim_meta["total_count"] == 0

        _orders, order_meta = validate_paginated(
            api_client.list_lot_removal_orders(ctx["lot_id"], ctx["seller_headers"])
        )
        assert order_meta["total_count"] == 1
