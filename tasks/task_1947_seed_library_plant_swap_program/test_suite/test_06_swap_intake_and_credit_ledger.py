"""Swap intake screening, per-item credit valuation, caps, and the credit
ledger."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_credit_entry,
    create_member,
    create_site,
    create_swap_event,
    create_variety,
    get_credit_summary,
    make_member_headers,
    publish_event,
    setup_intake_open_event,
    submit_and_accept,
    submit_item,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPerItemRoundingThenSum:
    def _setup(self):
        ctx = setup_intake_open_event()
        v1 = create_variety(
            variety_name="V", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        v2 = create_variety(
            variety_name="V2", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        return ctx, v1, v2, member

    def test_cutting_excellent_rounds_half_up_per_item(self):
        """PRD §3.6: "the base value for its type — 2 for a seed packet, 5 for
        a plant start, 3 for a cutting — is multiplied by its condition factor
        — one and a half for `EXCELLENT`, exactly one for `GOOD`, one half for
        `FAIR` — and the product is rounded half up to a whole credit; a
        variety flagged rare adds a flat 2-credit bonus on top."

        CUTTING x EXCELLENT: round_half_up(3 * 1.5) = round_half_up(4.5) = 5.

        Design: Difficulty/combinatorial_formula/swap_credit_per_item_round_then_sum_mode_b
        """
        ctx, v1, v2, member = self._setup()
        item1 = submit_item(
            ctx["event"]["id"], member["id"], v1["id"], "CUTTING", "EXCELLENT"
        )
        assert item1["credit_value"] == 5, (
            f"Expected per-item round_half_up(4.5)=5, got "
            f"{item1['credit_value']}"
        )
        item2 = submit_item(
            ctx["event"]["id"], member["id"], v2["id"], "CUTTING", "EXCELLENT"
        )
        assert item2["credit_value"] == 5

    def test_earned_total_sums_per_item_rounded_values(self):
        """PRD §2.6: "Swap-credit valuations round each item's credit to a
        whole integer, half up, before any summation."
        PRD §3.6: "Acceptance moves the item to `ACCEPTED` and immediately pays
        for it: a `CreditEntry` of type `EARNED` for the item's `credit_value`
        is appended against the member and scoped to the event, with a
        system-generated provenance `note`, and the member's earned total and
        balance are recomputed."

        Two CUTTING/EXCELLENT items earn 5 + 5 = 10; the unpinned
        sum-then-round order would give round_half_up(9.0) = 9.

        Design: Difficulty/combinatorial_formula/swap_credit_per_item_round_then_sum_mode_b
        """
        ctx, v1, v2, member = self._setup()
        submit_and_accept(
            ctx["event"]["id"], member["id"], v1["id"], "CUTTING", "EXCELLENT"
        )
        submit_and_accept(
            ctx["event"]["id"], member["id"], v2["id"], "CUTTING", "EXCELLENT"
        )
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 10, (
            f"Per-item rounding then sum gives 10 (sum-then-round would be "
            f"9), got {summary['credits_earned_total']}"
        )
        assert summary["credits_balance"] == 10


class TestSafetyVsFiscalPriority:
    def _setup_member_at_cap(self):
        """Member earned exactly 25 credits at the event (10 + 10 + 5); an
        invasive variety is also catalogued."""
        ctx = setup_intake_open_event()
        vr1 = create_variety(
            variety_name="VR", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        vr2 = create_variety(
            variety_name="VR2", category="NATIVE", approved_zones=["ZONE_5A"],
            rarity_flag=True,
        )
        vn = create_variety(
            variety_name="VN", category="FLOWER", approved_zones=["ZONE_5A"]
        )
        vi = create_variety(
            variety_name="VI", category="FLOWER", approved_zones=["ZONE_5A"],
            invasive_flag=True,
        )
        member = create_member(ctx["site"]["id"])
        # 8 + 2 rarity = 10 each; then 5 -> exactly 25.
        submit_and_accept(
            ctx["event"]["id"], member["id"], vr1["id"], "PLANT_START",
            "EXCELLENT",
        )
        submit_and_accept(
            ctx["event"]["id"], member["id"], vr2["id"], "PLANT_START",
            "EXCELLENT",
        )
        submit_and_accept(
            ctx["event"]["id"], member["id"], vn["id"], "PLANT_START", "GOOD"
        )
        return ctx, member, vi, vn

    def test_invasive_item_at_cap_reports_safety_error(self):
        """PRD §2.9: "Every guarded request passes through a fixed sequence of
        validation bands, and an earlier failure masks every later check — the
        response carries the first failing rule's error, never a later one."
        PRD §3.6: "The safety screens run next, in order: an invasive variety
        is refused with `ERR_INVASIVE_SPECIES_BLOCKED`, and a variety whose
        `approved_zones` does not contain the event site's `region_zone` is
        refused with `ERR_REGION_NOT_APPROVED`."

        Member already at the 25-credit cap submits an invasive item: the
        safety screen fires before the fiscal cap.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_intake
        """
        ctx, member, vi, _ = self._setup_member_at_cap()
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 25, (
            "exactly reaching the cap is allowed"
        )
        resp = api_client.submit_intake_item(
            ctx["event"]["id"],
            {
                "member_id": member["id"],
                "variety_id": vi["id"],
                "item_type": "CUTTING",
                "condition": "FAIR",
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVASIVE_SPECIES_BLOCKED)

    def test_clean_item_over_cap_reports_cap_error(self):
        """PRD §3.6: "Before the submission is stored, the event credit cap
        applies to the request as a whole: the member's credits already earned
        at this event plus the submission's total must not exceed 25. Reaching
        exactly 25 is allowed; exceeding it rejects the entire submission with
        `ERR_EVENT_CREDIT_CAP_EXCEEDED` — there is no partial acceptance."

        Member at exactly 25 submits a clean 2-credit item: the cap fires once
        the safety screen passes.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_intake
        """
        ctx, member, _, vn = self._setup_member_at_cap()
        resp = api_client.submit_intake_item(
            ctx["event"]["id"],
            {
                "member_id": member["id"],
                "variety_id": vn["id"],
                "item_type": "CUTTING",
                "condition": "FAIR",
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_CREDIT_CAP_EXCEEDED)


class TestIntakeGatedByEventState:
    def test_submission_against_scheduled_event_rejected(self):
        """PRD §3.6: "Submission against an event that is not `INTAKE_OPEN` is
        refused with `ERR_EVENT_NOT_INTAKE_OPEN`."

        Event published (SCHEDULED) but intake never opened.

        Design: Difficulty/cross_entity_state_dependency/intake_gated_by_swapevent_state
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_5A")
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        event = create_swap_event(site["id"])
        publish_event(event["id"])
        member = create_member(site["id"])
        resp = api_client.submit_intake_item(
            event["id"],
            {
                "member_id": member["id"],
                "variety_id": variety["id"],
                "item_type": "SEED_PACKET",
                "condition": "GOOD",
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_INTAKE_OPEN)

    def test_submission_against_draft_event_rejected(self):
        """PRD §3.6: "Submission against an event that is not `INTAKE_OPEN` is
        refused with `ERR_EVENT_NOT_INTAKE_OPEN`."

        Event still in DRAFT (never published).

        Design: Difficulty/cross_entity_state_dependency/intake_gated_by_swapevent_state
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_5A")
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        event = create_swap_event(site["id"])
        member = create_member(site["id"])
        resp = api_client.submit_intake_item(
            event["id"],
            {
                "member_id": member["id"],
                "variety_id": variety["id"],
                "item_type": "SEED_PACKET",
                "condition": "GOOD",
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_INTAKE_OPEN)


class TestDuplicateIntakeItem:
    def test_second_identical_item_rejected_while_twin_submitted(self):
        """PRD §3.6: "A duplicate check follows: the same member submitting the
        same item type of the same variety at the same event is rejected with
        `ERR_DUPLICATE_INTAKE_ITEM` while a non-terminal twin — one still
        `SUBMITTED` or `ACCEPTED` — exists."

        Design: Corner/validations/val_duplicate_intake_item_rejected
        """
        ctx = setup_intake_open_event()
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_item(
            ctx["event"]["id"], member["id"], variety["id"], "SEED_PACKET",
            "GOOD",
        )
        resp = api_client.submit_intake_item(
            ctx["event"]["id"],
            {
                "member_id": member["id"],
                "variety_id": variety["id"],
                "item_type": "SEED_PACKET",
                "condition": "EXCELLENT",
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INTAKE_ITEM)


class TestRedemptionCeilings:
    def test_over_redemption_rejected_exact_amount_drains(self):
        """PRD §3.6: "Three ceilings bind the amount, all enforced under
        `ERR_INSUFFICIENT_CREDITS`: the amount must be at least 1, must not
        exceed the member's overall `credits_balance`, and must not exceed the
        event-scoped remainder — the credits the member has earned at this
        event minus those already redeemed at this event."

        Member earned 2 (SEED_PACKET/GOOD): redeeming 3 rejected, redeeming
        exactly 2 succeeds and drains the balance.

        Design: Corner/validations/val_insufficient_credits_on_redeem
        """
        ctx = setup_intake_open_event()
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], variety["id"], "SEED_PACKET",
            "GOOD",
        )
        resp = api_client.redeem_credits(
            ctx["event"]["id"],
            {"member_id": member["id"], "credits": 3},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)
        resp = api_client.redeem_credits(
            ctx["event"]["id"],
            {"member_id": member["id"], "credits": 2},
            make_member_headers(member["id"]),
        )
        data = validate_success(resp, 200)
        assert data["credits_balance"] == 0, (
            "exact-amount redemption drains the balance"
        )


class TestCreditEntryLedger:
    def test_earned_entry_appended_and_rows_are_append_only(self):
        """PRD §3.6: "Acceptance moves the item to `ACCEPTED` and immediately
        pays for it: a `CreditEntry` of type `EARNED` for the item's
        `credit_value` is appended against the member and scoped to the event,
        with a system-generated provenance `note`, and the member's earned
        total and balance are recomputed."
        PRD §2.4: "One deliberate exception exists: `CreditEntry` is an
        append-only ledger row and carries only `id` and `created_at`. It has
        no `updated_at` and no `version`, because ledger entries are never
        modified after being appended."

        SEED_PACKET/GOOD on a non-rare variety earns round_half_up(2*1.0) = 2.

        Design: Corner/entities/entity_credit_entry_immutable_append_only
        """
        ctx = setup_intake_open_event()
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], variety["id"], "SEED_PACKET",
            "GOOD",
        )
        resp = api_client.list_credit_entries(
            ADMIN, params={"member_id": member["id"]}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        entry = data[0]
        assert entry["entry_type"] == "EARNED"
        assert entry["credits"] == 2
        assert_credit_entry(entry)


class TestCreditSummaryComputedRead:
    def test_summary_reflects_earn_and_redeem_immediately(self):
        """PRD §3.6: "A member's credit summary — `credits_earned_total`,
        `credits_redeemed_total`, `credits_expired_total`,
        `credits_revoked_total`, and `credits_balance` — is a computed read
        over that ledger".

        Earn 2 then redeem 2: earned 2, redeemed 2, balance 0.

        Design: Corner/endpoints/ep_computed_read_credit_summary
        """
        ctx = setup_intake_open_event()
        variety = create_variety(
            category="FLOWER", approved_zones=["ZONE_5A"]
        )
        member = create_member(ctx["site"]["id"])
        submit_and_accept(
            ctx["event"]["id"], member["id"], variety["id"], "SEED_PACKET",
            "GOOD",
        )
        resp = api_client.redeem_credits(
            ctx["event"]["id"],
            {"member_id": member["id"], "credits": 2},
            make_member_headers(member["id"]),
        )
        validate_success(resp, 200)
        summary = get_credit_summary(member["id"])
        assert summary["credits_earned_total"] == 2
        assert summary["credits_redeemed_total"] == 2
        assert summary["credits_balance"] == 0
