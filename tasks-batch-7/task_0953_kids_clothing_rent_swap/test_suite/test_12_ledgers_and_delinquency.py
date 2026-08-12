"""The two ledgers: charges, credits, the pinned application waterfall,
optimistic concurrency on the member and the delinquency threshold."""

from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    assert_charge_entry,
    assert_credit_conservation,
    assert_credit_entry,
    assert_same_instant,
    activate_pause,
    allocate_unit,
    api_client,
    apply_credit,
    create_box,
    create_open_cycle,
    create_style,
    create_swap_request,
    create_unit,
    get_charge_entry,
    get_credit_entry,
    get_cycle,
    get_member,
    grant_credit,
    list_charge_entries,
    list_credit_entries,
    make_member_headers,
    raise_charge,
    request_pause,
    set_clock,
    setup_plan_and_member,
    validate_error,
    validate_success,
)


class TestLedgerEntryShapes:
    def test_a_fresh_charge_owes_its_full_amount(self, api):
        """PRD §3.11: "A charge entry carries `member_id`, an optional `cycle_id`
        that is null for charges not tied to a cycle, a `charge_type` drawn from
        `PLAN_CHARGE`, `PROTECTION_FEE`, `LATE_FEE`, `DAMAGE_FEE`,
        `SHIPPING_FEE`, `LOST_LIABILITY`, `BUYOUT_PRICE` and `SURCHARGE`, a
        gross `amount_cents`, a `credit_applied_cents` that starts at 0, and a
        `net_due_cents` that is `amount_cents` less `credit_applied_cents`,
        floored at zero."
        PRD §3.11: "such an entry is created `ASSESSED` with `net_due_cents`
        equal to `amount_cents`, the member's `outstanding_balance_cents` is
        recomputed, and the member may fall `ACTIVE → DELINQUENT` with the full
        cascade of §3.1."

        Design: Corner/entities/corner_charge_entry_net_due_mirrors_amount_before_any_credit
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        entry = validate_success(
            api.create_charge_adjustment(member["id"],
                                         {"charge_type": "SHIPPING_FEE",
                                          "amount_cents": 1800}, BILLING),
            201,
        )
        assert_charge_entry(entry)
        assert entry["amount_cents"] == 1800
        assert entry["credit_applied_cents"] == 0
        assert entry["net_due_cents"] == 1800
        assert entry["status"] == "ASSESSED"
        assert entry["charge_type"] == "SHIPPING_FEE"

        after = get_member(member["id"])
        assert after["outstanding_balance_cents"] == 1800
        assert after["status"] == "ACTIVE"

    def test_a_granted_credit_expires_one_hundred_and_eighty_days_later(self, api):
        """PRD §3.11: "Expiry is `granted_at` plus `CREDIT_EXPIRY_DAYS`, 180
        days, plus `paused_days_extension` days; credit is usable **strictly
        before** that instant."
        PRD §3.11: "such an entry is created `AVAILABLE` with `remaining_cents`
        equal to `amount_cents`, `granted_at` at the logical clock and
        `expires_at` derived — and **auto-apply deliberately does not fire for
        operator grants**, unlike a trade-in finalisation, which does auto-apply
        when the member's `auto_apply_credit` is true."
        PRD §3.11: "a `paused_days_extension` that starts at 0, and a
        `revoke_reason` that starts null."

        Design: Corner/entities/corner_credit_entry_expiry_computed_from_grant_instant
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        entry = validate_success(
            api.create_credit_adjustment(member["id"],
                                         {"amount_cents": 2500, "reason": "goodwill"},
                                         BILLING),
            201,
        )
        assert_credit_entry(entry)
        assert entry["amount_cents"] == 2500
        assert entry["remaining_cents"] == 2500
        assert entry["status"] == "AVAILABLE"
        assert_same_instant(entry["granted_at"], "2026-05-01T00:00:00.000Z",
                            "CreditLedgerEntry.granted_at")
        assert_same_instant(entry["expires_at"], "2026-10-28T00:00:00.000Z",
                            "CreditLedgerEntry.expires_at")
        assert entry["paused_days_extension"] == 0
        assert get_member(member["id"])["credit_balance_cents"] == 2500

    def test_a_pause_pushes_the_expiry_instant_out_by_its_days(self, api):
        """PRD §3.10: "A successful activation moves the request `REQUESTED →
        ACTIVE`, moves the member `ACTIVE → PAUSED`, computes the proration
        credit, and grants every one of the member's credit entries whose
        `status` is `AVAILABLE` or `PARTIALLY_APPLIED` a `paused_days_extension`
        equal to `days_requested`. **Credit does not age during a pause.**"
        PRD §3.11: "Where no pause intervened the 180-day window simply runs on
        wall time; where a pause was activated while the entry stood `AVAILABLE`
        or `PARTIALLY_APPLIED`, the expiry instant moves out by exactly that
        pause's `days_requested`."

        Design: Corner/calculations/corner_calc_credit_expiry_is_extended_by_a_pause
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        credit = grant_credit(member["id"], 3000)
        pause = request_pause(member["id"], "2026-05-05T00:00:00Z", 14)

        activate_pause(pause["id"])

        after = get_credit_entry(credit["id"])
        assert after["paused_days_extension"] == 14
        assert_same_instant(after["expires_at"], "2026-11-11T00:00:00.000Z",
                            "CreditLedgerEntry.expires_at")
        assert after["status"] == "AVAILABLE"
        assert after["remaining_cents"] == 3000
        assert get_member(member["id"])["status"] == "PAUSED"


class TestCreditApplication:
    def test_the_charge_type_order_is_a_total_order_not_a_queue(self, api):
        """PRD §3.11: "**Charges** are taken in the order of their `charge_type`
        within `CREDIT_APPLICATION_ORDER` — `PLAN_CHARGE` first, then
        `PROTECTION_FEE`, then `LATE_FEE`, then `DAMAGE_FEE`, then
        `SHIPPING_FEE`, then `LOST_LIABILITY`, then `BUYOUT_PRICE` — with ties
        inside a bucket broken by `created_at` ascending. That bucket order is a
        total order and is **never** re-sorted by amount."
        PRD §3.11: "A charge whose `net_due_cents` reaches zero becomes
        `SETTLED`; a charge that received some credit but still owes becomes
        `PARTIALLY_SETTLED`; a charge that received nothing stays `ASSESSED`."
        PRD §3.11: "a credit whose `remaining_cents` reaches zero becomes
        `APPLIED`, otherwise it becomes `PARTIALLY_APPLIED`."

        Design: Corner/calculations/corner_calc_credit_applies_to_plan_charge_before_an_older_late_fee
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        late_fee = raise_charge(member["id"], "LATE_FEE", 1000)
        plan_charge = raise_charge(member["id"], "PLAN_CHARGE", 1000)
        credit = grant_credit(member["id"], 1000)

        apply_credit(member["id"], plan_charge["id"])

        settled = get_charge_entry(plan_charge["id"])
        assert settled["credit_applied_cents"] == 1000
        assert settled["net_due_cents"] == 0
        assert settled["status"] == "SETTLED"

        untouched = get_charge_entry(late_fee["id"])
        assert untouched["credit_applied_cents"] == 0
        assert untouched["net_due_cents"] == 1000
        assert untouched["status"] == "ASSESSED"

        assert get_credit_entry(credit["id"])["status"] == "APPLIED"
        assert get_member(member["id"])["outstanding_balance_cents"] == 1000

    def test_applying_an_expired_credit_is_refused(self, api):
        """PRD §2.6 rung 58: "A `CreditLedgerEntry` may be applied only while the
        logical clock is strictly before its `expires_at` and its `status` is
        `AVAILABLE` or `PARTIALLY_APPLIED`. Otherwise `ERR_CREDIT_EXPIRED`
        (409). Applies to
        `POST /kidswear/members/{member_id}/credit-applications`. Shared: credit
        granted by Pipeline T is spent against Pipeline R charges under this same
        rung."
        PRD §3.11: "An application against an entry that is expired, `APPLIED`,
        `EXPIRED` or `REVOKED` is refused with `ERR_CREDIT_EXPIRED`, and an
        application attempted while the member's `credit_balance_cents` is zero
        is refused with `ERR_INSUFFICIENT_CREDIT`."

        Design: Corner/validations/corner_val_credit_application_after_expiry_is_rejected
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        credit = grant_credit(member["id"], 3000)
        charge = raise_charge(member["id"], "LATE_FEE", 1000)
        set_clock("2026-10-29T00:00:00Z")
        version = get_member(member["id"])["version"]

        resp = api.create_credit_application(
            member["id"],
            {"charge_entry_id": charge["id"], "expected_member_version": version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXPIRED.value, 409)

        after_credit = get_credit_entry(credit["id"])
        assert_same_instant(after_credit["expires_at"], "2026-10-28T00:00:00.000Z",
                            "CreditLedgerEntry.expires_at")
        assert after_credit["remaining_cents"] == 3000
        assert get_charge_entry(charge["id"])["net_due_cents"] == 1000

    def test_applying_with_an_empty_credit_ledger_is_refused(self, api):
        """PRD §2.6 rung 59: "The member's `credit_balance_cents` must be
        strictly greater than zero for a credit application. Otherwise
        `ERR_INSUFFICIENT_CREDIT` (409). Applies to
        `POST /kidswear/members/{member_id}/credit-applications`."
        PRD §3.11: "an application attempted while the member's
        `credit_balance_cents` is zero is refused with
        `ERR_INSUFFICIENT_CREDIT`."

        Design: Corner/validations/corner_val_credit_application_with_no_credit_is_rejected
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        charge = raise_charge(member["id"], "SHIPPING_FEE", 1000)
        version = get_member(member["id"])["version"]

        resp = api.create_credit_application(
            member["id"],
            {"charge_entry_id": charge["id"], "expected_member_version": version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value, 409)
        assert get_member(member["id"])["credit_balance_cents"] == 0
        assert get_charge_entry(charge["id"])["status"] == "ASSESSED"

    def test_a_stale_member_version_is_refused_at_the_concurrency_gate(self, api):
        """PRD §2.8: "A `POST /kidswear/members/{member_id}/credit-applications`
        request must carry `expected_member_version` holding the client's last
        observed `version` of the target `Member`. A mismatch is rejected with
        `ERR_STALE_MEMBER_VERSION` (HTTP 412), because a prior application
        consumes credit from the same ledger and a stale writer would compute
        its application against a balance that has already been spent. A
        successful application increments the member's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_stale_member_version_on_credit_application
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        credit = grant_credit(member["id"], 5000)
        first_charge = raise_charge(member["id"], "PLAN_CHARGE", 1000)
        second_charge = raise_charge(member["id"], "LATE_FEE", 1000)
        stale_version = get_member(member["id"])["version"]
        apply_credit(member["id"], first_charge["id"], stale_version)

        resp = api.create_credit_application(
            member["id"],
            {"charge_entry_id": second_charge["id"],
             "expected_member_version": stale_version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value, 412)

        assert get_charge_entry(first_charge["id"])["status"] == "SETTLED"
        untouched = get_charge_entry(second_charge["id"])
        assert untouched["status"] == "ASSESSED"
        assert untouched["credit_applied_cents"] == 0
        assert get_credit_entry(credit["id"])["remaining_cents"] == 4000
        assert get_member(member["id"])["credit_balance_cents"] == 4000

    def test_a_member_may_not_waive_a_charge_on_their_own_account(self, api):
        """PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.11: "A `BillingAgent` may also waive an open charge by supplying a
        `waive_reason`, which moves it to `WAIVED` with `net_due_cents` set to
        0, recomputes the outstanding balance, and may return the member
        `DELINQUENT → ACTIVE`."

        Design: Corner/rbac/corner_rbac_member_cannot_waive_their_own_charge
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        charge = raise_charge(member["id"], "DAMAGE_FEE", 1500)

        resp = api.waive_charge_entry(charge["id"],
                                      {"waive_reason": "I would rather not pay"},
                                      make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)

        assert get_charge_entry(charge["id"])["status"] == "ASSESSED"
        assert get_member(member["id"])["outstanding_balance_cents"] == 1500

    def test_waiving_a_waived_charge_is_refused(self, api):
        """PRD §2.6 rung 60: "A `ChargeLedgerEntry` must have `status` `ASSESSED`
        or `PARTIALLY_SETTLED` to receive credit or to be waived. Otherwise
        `ERR_CHARGE_NOT_OPEN` (409). Applies to
        `POST /kidswear/members/{member_id}/credit-applications` and
        `POST /kidswear/charge-entries/{charge_entry_id}/waive`."
        PRD §3.11: "Waiving or crediting a charge whose `status` is already
        `SETTLED` or `WAIVED` is refused with `ERR_CHARGE_NOT_OPEN`."

        Design: Corner/validations/corner_val_waiving_an_already_waived_charge_is_rejected
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        charge = raise_charge(member["id"], "DAMAGE_FEE", 2000)
        validate_success(api.waive_charge_entry(charge["id"],
                                                {"waive_reason": "goodwill"}, BILLING))

        resp = api.waive_charge_entry(charge["id"],
                                      {"waive_reason": "second attempt"}, BILLING)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_OPEN.value, 409)

        after = get_charge_entry(charge["id"])
        assert after["status"] == "WAIVED"
        assert after["net_due_cents"] == 0
        assert get_member(member["id"])["outstanding_balance_cents"] == 0


class TestDerivedBalances:
    def test_the_credit_balance_is_recomputed_not_patched(self, api):
        """PRD §3.1: "`credit_balance_cents` is the sum of `remaining_cents`
        across the member's credit entries whose `status` is `AVAILABLE` or
        `PARTIALLY_APPLIED`, and `outstanding_balance_cents` is the sum of
        `net_due_cents` across the member's charge entries whose `status` is
        `ASSESSED` or `PARTIALLY_SETTLED`."
        PRD §3.11: "A `BillingAgent` may expire an entry whose instant has
        passed, or revoke one with a `revoke_reason`; both recompute the
        member's `credit_balance_cents`."

        Design: Corner/cross_cutting_complexity_layers/corner_ccl_derived_field_reconciliation_on_credit_revocation
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        first = grant_credit(member["id"], 1500, "first goodwill")
        second = grant_credit(member["id"], 2500, "second goodwill")
        assert get_member(member["id"])["credit_balance_cents"] == 4000

        validate_success(api.revoke_credit_entry(first["id"],
                                                 {"revoke_reason": "granted in error"},
                                                 BILLING))

        revoked = get_credit_entry(first["id"])
        assert revoked["status"] == "REVOKED"
        assert revoked["remaining_cents"] == 1500
        assert get_credit_entry(second["id"])["status"] == "AVAILABLE"
        assert get_member(member["id"])["credit_balance_cents"] == 2500

    def test_the_delinquency_line_is_reached_at_exactly_the_threshold(self, api):
        """PRD §3.1: "Standing is re-evaluated on **every** change to
        `outstanding_balance_cents`, and the two comparators are deliberately
        asymmetric. An `ACTIVE` member whose outstanding balance reaches or
        exceeds `DELINQUENCY_THRESHOLD_CENTS`, which is 15000 cents, becomes
        `DELINQUENT`. A `DELINQUENT` member whose outstanding balance falls
        **strictly below** 15000 cents returns to `ACTIVE`. A balance of exactly
        15000 cents therefore keeps a delinquent member delinquent."

        Design: Corner/cross_cutting_complexity_layers/corner_ccl_threshold_boundary_at_exactly_the_delinquency_line
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        raise_charge(member["id"], "DAMAGE_FEE", 14999)

        before = get_member(member["id"])
        assert before["outstanding_balance_cents"] == 14999
        assert before["status"] == "ACTIVE"

        last_cent = raise_charge(member["id"], "LATE_FEE", 1)

        after = get_member(member["id"])
        assert after["outstanding_balance_cents"] == 15000
        assert after["status"] == "DELINQUENT"
        assert get_charge_entry(last_cent["id"])["amount_cents"] == 1


class TestStandingPreEmptsTheWindowGate:
    def _delinquent_with_a_closed_window(self, sku, email):
        plan, member = setup_plan_and_member(
            plan={"slots_per_box": 1, "swaps_per_cycle": 2},
            member={"auto_apply_credit": False, "email": email},
        )
        style = create_style(sku=sku, name="Prio Two Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        raise_charge(member["id"], "DAMAGE_FEE", 20000)
        set_clock("2026-05-22T00:00:00Z")
        return {"member": member, "cycle": cycle, "item": item, "style": style}

    def test_the_standing_gate_reports_delinquency_not_a_closed_window(self, api):
        """PRD §2.5: "**G4_STANDING precedes G5_PAUSE.** A `CANCELLED` member who
        also holds an `ACTIVE` pause receives `ERR_MEMBER_CANCELLED`, never
        `ERR_MEMBER_PAUSED`."
        PRD §2.6 rung 16: "The owning member's `status` is not `DELINQUENT`.
        Otherwise `ERR_MEMBER_DELINQUENT` (409). Applies to exactly these five
        endpoints and no others: `POST /kidswear/boxes/{box_id}/allocate`,
        `POST /kidswear/cycles/{cycle_id}/swap-requests`,
        `POST /kidswear/box-items/{box_item_id}/buy-out`,
        `POST /kidswear/capsules/{capsule_id}/allocations`, and
        `POST /kidswear/trade-in-submissions/{submission_id}/issue-label`."
        PRD §2.6 rung 33: "A swap may be created or submitted only while the
        logical clock is on or before the cycle's `swap_by_at`; the boundary is
        **inclusive**, so a swap submitted at exactly `swap_by_at` is accepted.
        Otherwise `ERR_SWAP_WINDOW_CLOSED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/member_delinquent_wins_over_swap_window_closed
        """
        world = self._delinquent_with_a_closed_window("SKU-P2-5", "prio2@kidswear.test")
        version = get_cycle(world["cycle"]["id"])["version"]

        resp = api.create_swap_request(
            world["cycle"]["id"],
            {"return_box_item_ids": [world["item"]["id"]],
             "requested_style_ids": [world["style"]["id"]],
             "expected_cycle_version": version},
            make_member_headers(world["member"]["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_MEMBER_DELINQUENT.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_SWAP_WINDOW_CLOSED.value

    def test_the_delinquency_cascade_had_already_held_the_cycle(self, api):
        """PRD §3.1: "Falling into `DELINQUENT` cascades: every `OPEN` or
        `SWAP_CLOSED` cycle of the member moves to `HELD`; every box item of the
        member still in `ALLOCATED` moves to `CANCELLED`; each such item's
        reserved unit returns from `RESERVED` to `IN_STOCK`; a `DRAFT` box moves
        to `CANCELLED` as its allocated items are cancelled; and the member's
        `version` increments by 1."
        PRD §3.11: "such an entry is created `ASSESSED` with `net_due_cents`
        equal to `amount_cents`, the member's `outstanding_balance_cents` is
        recomputed, and the member may fall `ACTIVE → DELINQUENT` with the full
        cascade of §3.1."

        Design: Difficulty/priority_pair_validation_conflict/member_delinquent_wins_over_swap_window_closed
        """
        world = self._delinquent_with_a_closed_window("SKU-P2B-5", "prio2b@kidswear.test")

        member = get_member(world["member"]["id"])
        assert member["status"] == "DELINQUENT"
        assert member["outstanding_balance_cents"] == 25000
        assert get_cycle(world["cycle"]["id"])["status"] == "HELD"


class TestMonetaryCreditConservation:
    def _granted_applied_and_revoked(self, email):
        _, member = setup_plan_and_member(
            member={"auto_apply_credit": False, "email": email}
        )
        credit = grant_credit(member["id"], 5000)
        charge = raise_charge(member["id"], "DAMAGE_FEE", 3000)
        apply_credit(member["id"], charge["id"])
        validate_success(api_client.revoke_credit_entry(
            credit["id"], {"revoke_reason": "audit adjustment"}, BILLING))
        return member, credit, charge

    def test_the_application_settles_the_charge_and_leaves_a_remainder(self, api):
        """PRD §3.11: "For each charge in turn, credit entries are drawn in that
        order while the charge still has money due, each draw taking the smaller
        of the credit's `remaining_cents` and the charge's `net_due_cents`. The
        drawn amount is subtracted from `remaining_cents` and added to
        `credit_applied_cents`; a credit whose `remaining_cents` reaches zero
        becomes `APPLIED`, otherwise it becomes `PARTIALLY_APPLIED`."
        PRD §3.11: "A charge whose `net_due_cents` reaches zero becomes
        `SETTLED`; a charge that received some credit but still owes becomes
        `PARTIALLY_SETTLED`; a charge that received nothing stays `ASSESSED`."

        Design: Difficulty/compensating_invariant/credit_grant_application_then_revocation_conserves_monetary_credit
        """
        member, credit, charge = self._granted_applied_and_revoked("cons2@kidswear.test")

        after_charge = get_charge_entry(charge["id"])
        assert after_charge["credit_applied_cents"] == 3000
        assert after_charge["net_due_cents"] == 0
        assert after_charge["status"] == "SETTLED"

        after_credit = get_credit_entry(credit["id"])
        assert after_credit["amount_cents"] == 5000
        assert after_credit["remaining_cents"] == 2000

    def test_revoking_the_remainder_creates_and_destroys_no_cent(self, api):
        """PRD §2.10: "For each `Member`, the sum of `amount_cents` over every one
        of that member's credit entries equals the sum of `remaining_cents` over
        entries whose `status` is `AVAILABLE` or `PARTIALLY_APPLIED`, plus the
        sum of `credit_applied_cents` over all of that member's charges, plus
        the sum of `remaining_cents` over entries whose `status` is `EXPIRED` or
        `REVOKED`. Credit is neither created nor destroyed by an application; it
        changes bucket."
        PRD §3.1: "`credit_balance_cents` is the sum of `remaining_cents` across
        the member's credit entries whose `status` is `AVAILABLE` or
        `PARTIALLY_APPLIED`, and `outstanding_balance_cents` is the sum of
        `net_due_cents` across the member's charge entries whose `status` is
        `ASSESSED` or `PARTIALLY_SETTLED`."

        Design: Difficulty/compensating_invariant/credit_grant_application_then_revocation_conserves_monetary_credit
        """
        member, credit, _ = self._granted_applied_and_revoked("cons2b@kidswear.test")

        after_credit = get_credit_entry(credit["id"])
        assert after_credit["status"] == "REVOKED"
        assert after_credit["remaining_cents"] == 2000

        after_member = get_member(member["id"])
        assert after_member["credit_balance_cents"] == 0
        assert after_member["outstanding_balance_cents"] == 0

        assert_credit_conservation(
            list_credit_entries(member_id=member["id"]),
            list_charge_entries(member_id=member["id"]),
        )
