"""Personal property inventory: claim/unclaim custody conservation, returns,
and the fifteen-day retention window on disposal."""
from test_helpers import (
    ApiErrorId,
    create_property_item_payload,
    list_property_items,
    make_agent_headers,
    make_borrower_headers,
    rm_headers,
    set_clock,
    setup_case_collateral_secured,
    validate_error,
    validate_success,
)

FAIR_APPRAISAL = {
    "odometer": 40_000,
    "condition_grade": "FAIR",
    "trade_in_value_cents": 600_000,
    "auction_guide_low_cents": 450_000,
}


def _secured_case_with_items(api, descriptions, borrower_name, vin):
    ctx = setup_case_collateral_secured(
        borrower_overrides={"full_name": borrower_name, "email": f"{borrower_name.lower()}@x.com"},
        loan_overrides={"vin": vin,
                        "principal_balance_cents": 500_000, "apr_bps": 900,
                        "monthly_payment_cents": 20_000, "missed_installments": 2,
                        "accrued_interest_cents": 8_000, "late_fees_cents": 3_000},
        appraisal_overrides=FAIR_APPRAISAL)
    items = []
    for desc in descriptions:
        payload = {"description": desc}
        if desc == "tools":
            payload["estimated_value_cents"] = 15_000
        resp = api.create_property_item(
            ctx["case"]["id"], payload, make_agent_headers(ctx["agent"]["id"]))
        items.append(validate_success(resp, expected_status=201))
    return ctx, items


class TestClaimReturnFlow:
    def test_property_claim_then_return_happy_path(self, api):
        """PRD §3.4: "The borrower who owns the case may claim an `INVENTORIED`
        item, moving it to `CLAIMED` and recording themselves in
        `claimed_by_borrower_id`"
        PRD §3.4: "The agent holding the case's `SECURED` assignment marks a
        `CLAIMED` item handed back, moving it to `RETURNED`"
        PRD §3.4: "every item created increments the case's
        `property_item_count` by one, and that counter is never decremented"

        Design: Corner/state_machines/property_claim_then_return_happy_path
        """
        ctx, items = _secured_case_with_items(api, ["child seat"], "PR", "VIN00000000000051")
        item = items[0]
        assert item["status"] == "INVENTORIED"

        claimed = validate_success(api.claim_property_item(
            item["id"], make_borrower_headers(ctx["borrower"]["id"])))
        assert claimed["status"] == "CLAIMED"
        assert claimed["claimed_by_borrower_id"] == ctx["borrower"]["id"]

        returned = validate_success(api.mark_item_returned(
            item["id"], make_agent_headers(ctx["agent"]["id"])))
        assert returned["status"] == "RETURNED"

        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["property_item_count"] == 1


class TestRetentionWindow:
    def test_dispose_before_retention_window_fails(self, api):
        """PRD §3.4: "may dispose of an `INVENTORIED` item only once the
        retention window has elapsed: at least fifteen days must have passed
        since `collateral_secured_at`, else the disposal is rejected with
        `ERR_PROPERTY_RETENTION_ACTIVE` (HTTP 422) — a temporal check evaluated
        after the item-state guard."

        Design: Corner/validations/dispose_before_retention_window_fails
        """
        ctx, items = _secured_case_with_items(api, ["sunglasses"], "RT", "VIN00000000000062")
        item = items[0]
        # Secured 2026-05-16; day 4 of the window.
        set_clock("2026-05-20T00:00:00Z")
        resp = api.dispose_property_item(item["id"], make_agent_headers(ctx["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROPERTY_RETENTION_ACTIVE)
        # Boundary: exactly secured_at + 15 days is allowed ("at least").
        set_clock("2026-05-31T00:00:00Z")
        disposed = validate_success(api.dispose_property_item(
            item["id"], make_agent_headers(ctx["agent"]["id"])))
        assert disposed["status"] == "DISPOSED"

    def test_dispose_claimed_item_invalid_state(self, api):
        """PRD §3.4: "The borrower who owns the case may claim an `INVENTORIED`
        item, moving it to `CLAIMED` ... (an item in any other status rejects
        with `ERR_INVALID_ITEM_STATE`..."
        PRD §3.4: "may dispose of an `INVENTORIED` item only once the retention
        window has elapsed: at least fifteen days must have passed since
        `collateral_secured_at`, else the disposal is rejected with
        `ERR_PROPERTY_RETENTION_ACTIVE` (HTTP 422) — a temporal check evaluated
        after the item-state guard."

        Design: Corner/validations/dispose_claimed_item_invalid_state
        """
        ctx, items = _secured_case_with_items(api, ["wallet"], "DC2", "VIN00000000000063")
        item = items[0]
        validate_success(api.claim_property_item(
            item["id"], make_borrower_headers(ctx["borrower"]["id"])))
        set_clock("2026-06-01T00:00:00Z")  # retention long past; state guard still fires first
        resp = api.dispose_property_item(item["id"], make_agent_headers(ctx["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ITEM_STATE)
        current = [i for i in list_property_items(ctx["case"]["id"]) if i["id"] == item["id"]][0]
        assert current["status"] == "CLAIMED"


class TestClaimUnclaimConservesCustody:
    def test_claim_unclaim_round_trip_restores_item_state(self, api):
        """PRD §3.4: "A claim can be withdrawn, moving the item from `CLAIMED`
        back to `INVENTORIED` and clearing `claimed_by_borrower_id` — but only
        by the borrower recorded on the claim."

        Design: Difficulty/compensating_invariant/claim_unclaim_conserves_property_custody
        """
        ctx, items = _secured_case_with_items(
            api, ["laptop", "jacket", "tools"], "PP", "VIN00000000000037")
        item = items[0]
        claimed = validate_success(api.claim_property_item(
            item["id"], make_borrower_headers(ctx["borrower"]["id"])))
        assert claimed["status"] == "CLAIMED"
        assert claimed["claimed_by_borrower_id"] == ctx["borrower"]["id"]
        back = validate_success(api.unclaim_property_item(
            item["id"], make_borrower_headers(ctx["borrower"]["id"])))
        assert back["status"] == "INVENTORIED"
        assert back.get("claimed_by_borrower_id") is None

    def test_claim_unclaim_pair_conserves_property_item_count(self, api):
        """PRD §3.4: "every item created increments the case's
        `property_item_count` by one, and that counter is never decremented —
        it is the anchor of the custody invariant that every item ever
        inventoried remains accounted for."

        Design: Difficulty/compensating_invariant/claim_unclaim_conserves_property_custody
        """
        ctx, items = _secured_case_with_items(
            api, ["laptop", "jacket", "tools"], "PP", "VIN00000000000037")
        case_id = ctx["case"]["id"]
        before = validate_success(api.get_recovery_case(case_id, rm_headers()))
        assert before["property_item_count"] == 3

        borrower_h = make_borrower_headers(ctx["borrower"]["id"])
        validate_success(api.claim_property_item(items[0]["id"], borrower_h))
        mid = validate_success(api.get_recovery_case(case_id, rm_headers()))
        assert mid["property_item_count"] == 3
        validate_success(api.unclaim_property_item(items[0]["id"], borrower_h))

        after = validate_success(api.get_recovery_case(case_id, rm_headers()))
        assert after["property_item_count"] == 3
        profile = {}
        for i in list_property_items(case_id):
            profile[i["status"]] = profile.get(i["status"], 0) + 1
        assert profile == {"INVENTORIED": 3}, (
            "custody profile identical to before the claim/unclaim pair")
