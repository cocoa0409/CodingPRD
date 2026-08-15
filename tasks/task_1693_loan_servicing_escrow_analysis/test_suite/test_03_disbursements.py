"""Disbursement scheduling, release gates, SoD, OCC patch, ledger effects."""
from test_helpers import (
    CO1,
    DP1,
    DP2,
    EA1,
    ApiErrorId,
    assert_balance_conservation,
    assert_disbursement,
    create_disbursement_payload,
    create_line_item_payload,
    create_unverified_payee,
    get_account,
    get_ledger,
    get_success_data,
    patch_disbursement_payload,
    post_deposit,
    release_disbursement,
    schedule_disbursement,
    set_clock,
    setup_account_with_scheduled_disbursement,
    setup_active_account,
    setup_released_disbursement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDisbursementCreation:
    def test_disbursement_born_scheduled_with_sod_anchor(self, api):
        """PRD: "The new disbursement is `SCHEDULED`, with
        `scheduled_by_user_id` anchored to the creator, `released_by_user_id`,
        `released_at`, `cleared_at`, `returned_at`, and `ledger_entry_id` all
        null, and `late_release` false."

        Design: Corner/state_machines/disbursement_created_in_scheduled
        """
        ctx = setup_active_account(loan_number="LN-SM-1")
        resp = api.create_disbursement(
            ctx["account"]["id"],
            create_disbursement_payload(ctx["line_items"][0]["id"],
                                        ctx["payee"]["id"]),
            DP1)
        disb = validate_success(resp, 201)
        assert_disbursement(disb)
        assert disb["status"] == "SCHEDULED"
        assert disb["scheduled_by_user_id"] == "dp_1"
        assert disb["released_by_user_id"] is None
        assert disb["released_at"] is None
        assert disb["cleared_at"] is None
        assert disb["returned_at"] is None
        assert disb["ledger_entry_id"] is None
        assert disb["late_release"] is False

    def test_create_with_unknown_line_item_reference_rejected(self, api):
        """PRD: "then body foreign-key references such as `payee_id`,
        `line_item_id`, and `disbursement_id` (`ERR_REFERENCE_NOT_FOUND`,
        HTTP 422)"

        Design: Corner/validations/disbursement_create_bad_line_item_not_found
        """
        ctx = setup_active_account(loan_number="LN-VAL-17")
        resp = api.create_disbursement(
            ctx["account"]["id"],
            create_disbursement_payload(
                "00000000-0000-4000-8000-000000000000", ctx["payee"]["id"]),
            DP1)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_create_disbursement_with_unverified_payee_rejected(self, api):
        """PRD: "the `payee_id` (which must be `VERIFIED` at creation)"

        Design: Difficulty/cross_entity_state_dependency/disbursement_create_requires_verified_payee
        """
        ctx = setup_active_account(loan_number="LN-XDS-1")
        unverified = create_unverified_payee()

        resp = api.create_disbursement(
            ctx["account"]["id"],
            create_disbursement_payload(ctx["line_items"][0]["id"],
                                        unverified["id"]),
            DP1)
        validate_error(resp, ApiErrorId.ERR_PAYEE_NOT_VERIFIED)

        payee_after = validate_success(api.get_payee(unverified["id"], EA1), 200)
        assert payee_after["verification_status"] == "PENDING_VERIFICATION"

    def test_create_line_item_with_unverified_payee_rejected(self, api):
        """PRD: "Creating a line item names the payee via `payee_id` (the
        payee must be `VERIFIED`, else `ERR_PAYEE_NOT_VERIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/disbursement_create_requires_verified_payee
        """
        ctx = setup_active_account(loan_number="LN-XDS-1B")
        unverified = create_unverified_payee()

        # FLOOD_INSURANCE: not among STANDARD_LINE_ITEMS, so the
        # ERR_DUPLICATE_LINE_ITEM_TYPE uniqueness gate (which §2.9 orders
        # before cross-entity state requirements) does not pre-empt the
        # payee-verified check under test.
        resp = api.create_line_item(
            ctx["account"]["id"],
            create_line_item_payload(unverified["id"],
                                     expense_type="FLOOD_INSURANCE",
                                     expected_annual_amount_cents=120_000,
                                     installments_per_year=1,
                                     first_due_date="2027-03-01"),
            EA1)
        validate_error(resp, ApiErrorId.ERR_PAYEE_NOT_VERIFIED)


class TestDisbursementReleaseGates:
    def test_release_one_day_early_rejected_on_date_succeeds(self, api):
        """PRD: "The current date must be on or after `scheduled_release_date`,
        else `ERR_RELEASE_TOO_EARLY`."

        Design: Corner/validations/release_too_early_and_exact_date_boundary
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-VAL-5")
        set_clock("2026-08-09T00:00:00Z")
        resp = api.release_disbursement(disb["id"], DP2)
        validate_error(resp, ApiErrorId.ERR_RELEASE_TOO_EARLY)

        set_clock("2026-08-10T00:00:00Z")
        released = validate_success(api.release_disbursement(disb["id"], DP2), 200)
        assert released["status"] == "RELEASED", (
            "release on exactly the scheduled_release_date is allowed (>= boundary)")

    def test_release_while_loan_onboarding_rejected(self, api):
        """PRD: "whereas disbursement release, insurance policy creation,
        reinstatement, force-placement charging, and borrower deposits all
        require the loan to be `ACTIVE` and are otherwise rejected with
        `ERR_LOAN_NOT_ACTIVE`."

        Design: Corner/validations/release_with_onboarding_loan_rejected
        """
        ctx = setup_active_account(loan_number="LN-VAL-16", activate_loan=False)
        disb = schedule_disbursement(
            ctx["account"]["id"], ctx["line_items"][0]["id"], ctx["payee"]["id"],
            amount_cents=30_000, due_date="2026-08-20",
            scheduled_release_date="2026-08-10")
        set_clock("2026-08-10T00:00:00Z")

        resp = api.release_disbursement(disb["id"], DP2)
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "SCHEDULED", "rejected release changes nothing"

    def test_scheduler_cannot_release_own_disbursement(self, api):
        """PRD: "The releasing processor's `X-User-ID` must differ from
        `scheduled_by_user_id`, else `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/sod_disbursement_self_release_rejected
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-RBAC-3")
        set_clock("2026-08-10T00:00:00Z")

        resp = api.release_disbursement(disb["id"], DP1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        released = validate_success(api.release_disbursement(disb["id"], DP2), 200)
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "dp_2"

    def test_cancel_from_released_rejected(self, api):
        """PRD: "Either the scheduler or a peer may cancel from `SCHEDULED` or
        `BLOCKED`, landing in the terminal `CANCELLED`."
        PRD: "then from-state validity for the attempted transition
        (`ERR_INVALID_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/cancel_released_disbursement_rejected
        """
        ctx, disb = setup_released_disbursement(loan_number="LN-SM-2")

        resp = api.cancel_disbursement(disb["id"], DP1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "RELEASED", "disbursement stays RELEASED"
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 70_000, (
            "no compensating entry is posted by the rejected cancel")


class TestReleaseShortfallAdvanceCascade:
    def test_release_posts_disbursement_entry_and_zero_floors_balance(self, api):
        """PRD: "A successful release posts a `DISBURSEMENT` ledger entry of
        negative `amount_cents` effective today"
        PRD: "the post-release balance never drops below 0"

        Design: Difficulty/transitive_cascade/release_shortfall_advance_depth2_cascade
        """
        ctx, disb = setup_released_disbursement(
            loan_number="LN-CAS-2", deposit_amount=50_000,
            disbursement_amount=70_000)
        acct_id = ctx["account"]["id"]

        entries = get_ledger(acct_id)
        debits = [e for e in entries if e["entry_type"] == "DISBURSEMENT"]
        assert len(debits) == 1 and debits[0]["amount_cents"] == -70_000
        assert debits[0]["running_balance_cents"] == -20_000, (
            "link 1: the debit replays to -20000 before the compensating advance")

        account = get_account(acct_id)
        assert account["balance_cents"] == 0, "post-release balance never below 0"
        assert_balance_conservation(account, entries)

    def test_shortfall_auto_creates_advance_with_compensating_entry(self, api):
        """PRD: "If the debit would drive the balance below zero, the system
        fronts the difference: it creates an `EscrowAdvance` with `reason`
        `DISBURSEMENT_SHORTFALL`, `disbursement_id` pointing at this
        disbursement, and an `amount_cents` equal to the disbursement amount
        reduced by any positive pre-release balance ... and posts an
        `ADVANCE_ISSUED` entry of positive that amount"

        Design: Difficulty/transitive_cascade/release_shortfall_advance_depth2_cascade
        """
        ctx, disb = setup_released_disbursement(
            loan_number="LN-CAS-2", deposit_amount=50_000,
            disbursement_amount=70_000)
        acct_id = ctx["account"]["id"]

        advances, _ = validate_paginated(api.list_advances(acct_id, EA1))
        assert len(advances) == 1, "exactly one auto-advance is created"
        adv = advances[0]
        assert adv["amount_cents"] == 20_000, (
            "advance covers the shortfall: 70000 minus the 50000 positive balance")
        assert adv["reason"] == "DISBURSEMENT_SHORTFALL"
        assert adv["disbursement_id"] == disb["id"]
        assert adv["status"] == "OUTSTANDING"

        issued = [e for e in get_ledger(acct_id)
                  if e["entry_type"] == "ADVANCE_ISSUED"]
        assert len(issued) == 1 and issued[0]["amount_cents"] == 20_000
        assert issued[0]["source_entity_id"] == adv["id"]


class TestReleaseReturnConservation:
    def test_release_debits_balance_and_ledger_stays_conserved(self, api):
        """PRD: "it always equals the sum of `amount_cents` over every ledger
        entry posted to that account"
        PRD: "A successful release posts a `DISBURSEMENT` ledger entry of
        negative `amount_cents` effective today"

        Design: Difficulty/compensating_invariant/disbursement_release_return_balance_conservation
        """
        ctx, disb = setup_released_disbursement(loan_number="LN-INV-1",
                                                disbursement_amount=70_000)
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 30_000, (
            "release of 70000 against a 100000 balance leaves 30000")
        assert_balance_conservation(account, get_ledger(ctx["account"]["id"]))

    def test_mark_returned_restores_balance_exactly(self, api):
        """PRD: "A disbursement marked `RETURNED` posts a compensating
        `DISBURSEMENT_RETURN` entry of positive `amount_cents` effective today,
        restoring ledger conservation"

        Design: Difficulty/compensating_invariant/disbursement_release_return_balance_conservation
        """
        ctx, disb = setup_released_disbursement(loan_number="LN-INV-1")
        acct_id = ctx["account"]["id"]

        returned = validate_success(api.mark_returned_disbursement(disb["id"], DP2), 200)
        assert returned["status"] == "RETURNED"
        assert returned["returned_at"] is not None

        account = get_account(acct_id)
        assert account["balance_cents"] == 100_000, (
            "the compensating return restores the pre-release balance exactly")
        entries = get_ledger(acct_id)
        types = [e["entry_type"] for e in entries]
        assert types == ["DEPOSIT", "DISBURSEMENT", "DISBURSEMENT_RETURN"], (
            f"expected exactly 3 entries in chronological order, got {types}")
        assert_balance_conservation(account, entries)

        advances, _ = validate_paginated(api.list_advances(acct_id, EA1))
        assert advances == [], "no advance residue remains after the return"


class TestComplianceHoldParallelDimensions:
    def test_hold_blocks_release_while_account_status_moves_freely(self, api):
        """PRD: "While `hold_status` is `COMPLIANCE_HOLD`, three operations are
        blocked with `ERR_ACCOUNT_ON_HOLD`: releasing a disbursement, computing
        an analysis, and finalizing an analysis."
        PRD: "The two evolve independently: a compliance hold never blocks
        deposits, line-item maintenance, or `account_status` moves, and
        suspension never blocks hold placement."

        Design: Difficulty/non_linear_state_machine/escrow_account_parallel_status_dimensions
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-PAR-1")
        acct_id = ctx["account"]["id"]

        get_success_data(api.hold_escrow_account(acct_id, CO1))
        # account_status keeps moving while the hold is in place.
        get_success_data(api.suspend_escrow_account(acct_id, CO1))
        account = get_success_data(api.reinstate_escrow_account(acct_id, CO1))
        assert account["account_status"] == "ACTIVE"
        assert account["hold_status"] == "COMPLIANCE_HOLD", (
            "the hold dimension is untouched by the suspend/reinstate cycle")

        set_clock("2026-08-10T00:00:00Z")
        resp = api.release_disbursement(disb["id"], DP2)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "SCHEDULED", (
            "the hold gates the release action, not the disbursement row")

    def test_release_succeeds_after_hold_released(self, api):
        """PRD: "and release the hold (`COMPLIANCE_HOLD` → `NONE`)"
        PRD: "A successful release posts a `DISBURSEMENT` ledger entry of
        negative `amount_cents` effective today"

        Design: Difficulty/non_linear_state_machine/escrow_account_parallel_status_dimensions
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-PAR-1")
        acct_id = ctx["account"]["id"]
        get_success_data(api.hold_escrow_account(acct_id, CO1))
        get_success_data(api.suspend_escrow_account(acct_id, CO1))
        get_success_data(api.reinstate_escrow_account(acct_id, CO1))
        set_clock("2026-08-10T00:00:00Z")
        validate_error(api.release_disbursement(disb["id"], DP2),
                       ApiErrorId.ERR_ACCOUNT_ON_HOLD)

        get_success_data(api.release_hold_escrow_account(acct_id, CO1))
        released = validate_success(api.release_disbursement(disb["id"], DP2), 200)
        assert released["status"] == "RELEASED"

        account = get_account(acct_id)
        assert account["balance_cents"] == 70_000, (
            "100000 deposit minus the released 30000")
        assert account["account_status"] == "ACTIVE"
        assert account["hold_status"] == "NONE"


class TestReleaseValidationPriority:
    def test_blocked_disbursement_release_reports_state_not_temporal(self, api):
        """PRD: "When several checks could reject the same request, they are
        evaluated in a fixed priority order so the surfaced error is
        deterministic:"
        PRD: "then from-state validity for the attempted transition
        (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); then the compliance-hold
        gate (`ERR_ACCOUNT_ON_HOLD`); then the loan-active gate
        (`ERR_LOAN_NOT_ACTIVE`); then segregation of duties
        (`ERR_SOD_VIOLATION`); then the force-placement notice windows
        (`ERR_NOTICE_WINDOW_NOT_MET`, `ERR_REMINDER_TOO_EARLY`); then the
        active-coverage bar (`ERR_ACTIVE_COVERAGE_EXISTS`); then the remaining
        temporal gates (`ERR_RELEASE_TOO_EARLY`,
        `ERR_EFFECTIVE_DATE_NOT_REACHED`, `ERR_EXTENSION_WINDOW_PASSED`,
        `ERR_PROJECTION_START_INVALID`)"

        Design: Difficulty/priority_pair_validation_conflict/release_cancelled_early_state_beats_temporal
        """
        # Disbursement in BLOCKED (payee suspended) with its release date still
        # in the future: both the state rule and the temporal rule are
        # violated; the state rule is evaluated first, so it surfaces.
        ctx = setup_active_account(loan_number="LN-PRI-1",
                                   deposits=[(100_000, "2026-08-05")])
        disb = schedule_disbursement(
            ctx["account"]["id"], ctx["line_items"][0]["id"], ctx["payee"]["id"],
            amount_cents=30_000, due_date="2026-12-20",
            scheduled_release_date="2026-12-01")
        get_success_data(api.suspend_payee(ctx["payee"]["id"], CO1))
        disb_blocked = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_blocked["status"] == "BLOCKED"

        resp = api.release_disbursement(disb["id"], DP2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "BLOCKED", "state unchanged"

    def test_scheduled_disbursement_release_too_early_reports_temporal(self, api):
        """PRD: "The current date must be on or after `scheduled_release_date`,
        else `ERR_RELEASE_TOO_EARLY`."

        Design: Difficulty/priority_pair_validation_conflict/release_cancelled_early_state_beats_temporal
        """
        # Twin of the cancelled case with the state rule satisfied: only the
        # temporal rule can fire, so it surfaces on its own.
        ctx = setup_active_account(loan_number="LN-PRI-1T",
                                   deposits=[(100_000, "2026-08-05")])
        disb = schedule_disbursement(
            ctx["account"]["id"], ctx["line_items"][0]["id"], ctx["payee"]["id"],
            amount_cents=30_000, due_date="2026-12-20",
            scheduled_release_date="2026-12-01")

        resp = api.release_disbursement(disb["id"], DP2)
        validate_error(resp, ApiErrorId.ERR_RELEASE_TOO_EARLY)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "SCHEDULED"


class TestDisbursementPatchOcc:
    def test_stale_patch_rejected_after_successful_patch(self, api):
        """PRD: "Rescheduling or re-amounting a disbursement requires
        `expected_disbursement_version` equal to the disbursement's current
        `version`."
        PRD: "the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_disbursement_patch_stale_version
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-OCC-2", due_date="2026-12-20",
            scheduled_release_date="2026-12-01")
        observed_version = disb["version"]

        patched = validate_success(api.patch_disbursement(
            disb["id"],
            patch_disbursement_payload(observed_version, amount_cents=31_000),
            DP1), 200)
        assert patched["amount_cents"] == 31_000
        assert patched["version"] == observed_version + 1, (
            "a successful patch increments the disbursement version by 1")

        resp = api.patch_disbursement(
            disb["id"],
            patch_disbursement_payload(observed_version, amount_cents=32_000),
            DP1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["amount_cents"] == 31_000, "the stale write is not applied"


class TestDisbursementListing:
    def test_list_pagination_limit_offset(self, api):
        """PRD: "List endpoints accept the query parameters `limit` and
        `offset`."
        PRD: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/disbursement_list_pagination
        """
        ctx = setup_active_account(loan_number="LN-EP-1")
        acct_id = ctx["account"]["id"]
        for due, rel in (("2026-12-20", "2026-12-01"), ("2027-01-20", "2027-01-01"),
                         ("2027-02-20", "2027-02-01")):
            schedule_disbursement(acct_id, ctx["line_items"][0]["id"],
                                  ctx["payee"]["id"], due_date=due,
                                  scheduled_release_date=rel)

        page1, meta1 = validate_paginated(
            api.list_disbursements(acct_id, EA1, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_disbursements(acct_id, EA1, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_created_disbursement_immediately_visible(self, api):
        """PRD: "Every mutation is immediately visible"

        Design: Corner/consistency_model/immediate_read_after_write
        """
        ctx = setup_active_account(loan_number="LN-CON-1")
        disb = schedule_disbursement(ctx["account"]["id"], ctx["line_items"][0]["id"],
                                     ctx["payee"]["id"])

        fetched = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert fetched["status"] == "SCHEDULED"
        assert fetched["amount_cents"] == 30_000
        assert fetched["scheduled_by_user_id"] == "dp_1"

        listed, meta = validate_paginated(
            api.list_disbursements(ctx["account"]["id"], EA1))
        assert meta["total_count"] == 1
        assert [d["id"] for d in listed] == [disb["id"]]


class TestLedgerListing:
    def test_ledger_filters_by_entry_type_and_conserves_balance(self, api):
        """PRD: "The account's ledger listing is always chronological in that
        same order and may be filtered by `entry_type`."
        PRD: "it always equals the sum of `amount_cents` over every ledger
        entry posted to that account"

        Design: Corner/endpoints/ledger_filter_by_entry_type
        """
        ctx, disb = setup_released_disbursement(
            loan_number="LN-EP-2", deposit_amount=50_000,
            disbursement_amount=70_000)
        acct_id = ctx["account"]["id"]
        # Second deposit: the recovery waterfall absorbs 20000 of it.
        post_deposit(acct_id, 40_000, "2026-08-11")

        deposits, _ = validate_paginated(
            api.list_ledger(acct_id, EA1, params={"entry_type": "DEPOSIT"}))
        assert len(deposits) == 2
        assert all(e["entry_type"] == "DEPOSIT" for e in deposits)
        assert sorted(e["amount_cents"] for e in deposits) == [40_000, 50_000]

        entries = get_ledger(acct_id)
        assert [e["entry_type"] for e in entries] == [
            "DEPOSIT", "DISBURSEMENT", "ADVANCE_ISSUED", "DEPOSIT",
            "ADVANCE_RECOVERY",
        ], "unfiltered ledger lists every entry chronologically"
        account = get_account(acct_id)
        assert account["balance_cents"] == 20_000
        assert_balance_conservation(account, entries)
