"""Meter readings, monthly netting variants, and the append-only ledger."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    api_client,
    assert_ledger_balances_consistent,
    assert_ledger_entry,
    assert_meter_reading,
    create_meter_reading_payload,
    drive_to_pto_granted,
    drive_to_screen_passed,
    get_account,
    get_application,
    get_success_data,
    list_ledger_entries,
    post_reading,
    schedule_and_complete_exchange,
    setup_program_with_grid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]

AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEPTEMBER = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
OCTOBER = ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")


def _pto_ready(name, program_overrides=None, tariff_overrides=None):
    """Program + account + application in PTO_GRANTED. Returns (sc, ctx, app)."""
    sc = setup_program_with_grid(
        name,
        program_overrides=program_overrides or {},
        tariff_overrides=tariff_overrides or {})
    ctx = add_customer_account(sc, "1")
    result = drive_to_pto_granted(sc, ctx, size=10_000, production=15_000_000)
    return sc, ctx, result["app"]


def _readings_for(api, account_id):
    data, _meta = validate_paginated(api.list_meter_readings(
        ADMIN, params={"service_account_id": account_id}))
    return data


class TestNettingVariants:
    def _build_variant_pair(self):
        """ENERGY_BANKING and MONETARY_CREDIT programs, identically
        configured, each with an application in PTO_GRANTED."""
        pair = {}
        for key, overrides in (
                ("e", {"metering_variant": "ENERGY_BANKING",
                       "true_up_mode": "BANK_ROLLOVER"}),
                ("m", {"metering_variant": "MONETARY_CREDIT",
                       "true_up_mode": "AVOIDED_COST_PAYOUT"})):
            sc, ctx, app = _pto_ready(key.upper(), program_overrides=overrides)
            pair[key] = {"sc": sc, "ctx": ctx, "app": app}
        return pair

    def test_identical_readings_diverge_between_variants(self, api):
        """PRD §3.9: "Identical readings therefore produce different bills and
        balances under the two variants, which is why the program's
        `metering_variant` is fixed at configuration time."
        PRD §3.9: "Under the `ENERGY_BANKING` variant, energy offsets energy.
        The period's net is the import minus the export. When the net is
        positive, the draw is the smaller of the account's `banked_wh` and the
        net; a positive draw posts a `BANK_DRAW` entry with zero cents and the
        drawn watt-hours negative in `quantity_wh`, and the bill is the
        remaining unbanked energy converted to cents at the import rate,
        rounded half-up, with `bank_drawn_wh` recording the draw."

        Design: Difficulty/dual_variant_calc/dvc_monthly_netting_energy_banking_vs_monetary_credit
        """
        pair = self._build_variant_pair()
        r = {}
        for key in ("e", "m"):
            acct = pair[key]["ctx"]["account"]["id"]
            r[key + "1"] = post_reading(acct, *AUGUST, 500_000, 800_000)

        # R1: surplus 300,000 Wh on both; both bills are zero.
        assert r["e1"]["bill_cents"] == 0
        assert r["m1"]["bill_cents"] == 0
        acct_e = get_account(pair["e"]["ctx"]["account"]["id"])
        acct_m = get_account(pair["m"]["ctx"]["account"]["id"])
        assert acct_e["banked_wh"] == 300_000
        assert acct_e["credit_balance_cents"] == 0
        assert acct_m["credit_balance_cents"] == 3_600
        assert acct_m["banked_wh"] == 0

        for key in ("e", "m"):
            acct = pair[key]["ctx"]["account"]["id"]
            r[key + "2"] = post_reading(acct, *SEPTEMBER, 700_000, 0)

        # R2: import 700,000 Wh.
        # ENERGY_BANKING draws the whole 300 kWh bank and bills 400 kWh.
        assert r["e2"]["bill_cents"] == 12_000
        assert r["e2"]["bank_drawn_wh"] == 300_000
        # MONETARY_CREDIT bills 700 kWh raw (21,000) minus the 3,600 draw.
        assert r["m2"]["bill_cents"] == 17_400
        assert r["m2"]["credit_applied_cents"] == 3_600

        acct_e = get_account(pair["e"]["ctx"]["account"]["id"])
        acct_m = get_account(pair["m"]["ctx"]["account"]["id"])
        assert acct_e["banked_wh"] == 0
        assert acct_m["credit_balance_cents"] == 0

        assert (get_application(pair["e"]["app"]["id"])["application_status"]
                == "OPERATING")
        assert (get_application(pair["m"]["app"]["id"])["application_status"]
                == "OPERATING")

    def test_variant_ledger_entry_shapes(self, api):
        """PRD §3.9: "Under the `MONETARY_CREDIT` variant, the raw bill is the
        billable import converted to cents at the tariff's import rate with a
        round-half-up; the surplus is converted to cents at the export rate
        with its own round-half-up and, when positive, posted as an
        `EXPORT_SURPLUS_CREDIT` ledger entry carrying the credit in
        `amount_cents` and the surplus watt-hours in `quantity_wh`."
        PRD §3.9: "When the net is zero or negative, the surplus — the negation
        of the net — is deposited: a positive deposit posts a `BANK_DEPOSIT`
        entry with zero cents and the deposited watt-hours positive in
        `quantity_wh`, the bill is zero, and `bank_deposited_wh` records the
        deposit. Either way `credit_applied_cents` is zero."

        Design: Difficulty/dual_variant_calc/dvc_monthly_netting_energy_banking_vs_monetary_credit
        """
        pair = self._build_variant_pair()
        r_e = post_reading(pair["e"]["ctx"]["account"]["id"], *AUGUST,
                           500_000, 800_000)
        r_m = post_reading(pair["m"]["ctx"]["account"]["id"], *AUGUST,
                           500_000, 800_000)

        # ENERGY_BANKING: pure energy entry, zero cents.
        entries_e = list_ledger_entries(pair["e"]["ctx"]["account"]["id"])
        assert len(entries_e) == 1
        assert_ledger_entry(entries_e[0])
        assert entries_e[0]["entry_type"] == "BANK_DEPOSIT"
        assert entries_e[0]["amount_cents"] == 0
        assert entries_e[0]["quantity_wh"] == 300_000
        assert entries_e[0]["meter_reading_id"] == r_e["id"]
        assert r_e["credit_applied_cents"] == 0
        assert r_e["bank_deposited_wh"] == 300_000
        assert r_e["bank_drawn_wh"] == 0

        # MONETARY_CREDIT: monetary credit entry, energy bank untouched.
        entries_m = list_ledger_entries(pair["m"]["ctx"]["account"]["id"])
        assert len(entries_m) == 1
        assert entries_m[0]["entry_type"] == "EXPORT_SURPLUS_CREDIT"
        assert entries_m[0]["amount_cents"] == 3_600
        assert entries_m[0]["quantity_wh"] == 300_000
        assert entries_m[0]["meter_reading_id"] == r_m["id"]
        assert r_m["bank_drawn_wh"] == 0
        assert r_m["bank_deposited_wh"] == 0


class TestNestedMinMaxPartialDraw:
    def test_partial_bank_draw_leaves_billable_remainder(self, api):
        """PRD §3.9: "When the net is positive, the draw is the smaller of the
        account's `banked_wh` and the net; a positive draw posts a `BANK_DRAW`
        entry with zero cents and the drawn watt-hours negative in
        `quantity_wh`, and the bill is the remaining unbanked energy converted
        to cents at the import rate, rounded half-up, with `bank_drawn_wh`
        recording the draw."

        Design: Difficulty/combinatorial_formula/cf_monthly_netting_nested_min_max_partial_draw
        """
        sc, ctx, _app = _pto_ready(
            "EB", program_overrides={"metering_variant": "ENERGY_BANKING",
                                     "true_up_mode": "BANK_ROLLOVER"})
        acct = ctx["account"]["id"]
        # R1 banks 100,000 Wh (bill 0).
        r1 = post_reading(acct, *AUGUST, 900_000, 1_000_000)
        assert r1["bill_cents"] == 0
        assert r1["bank_deposited_wh"] == 100_000

        # R2 draws min(100,000, 700,000) = 100,000 and bills 600,000 Wh.
        r2 = post_reading(acct, *SEPTEMBER, 700_000, 0)
        assert r2["bill_cents"] == 18_000
        assert r2["bank_drawn_wh"] == 100_000
        assert get_account(acct)["banked_wh"] == 0

        entries = list_ledger_entries(acct)
        by_type = {(e["entry_type"], e["quantity_wh"]) for e in entries}
        assert ("BANK_DEPOSIT", 100_000) in by_type
        assert ("BANK_DRAW", -100_000) in by_type

    def test_smaller_bank_draws_down_to_zero(self, api):
        """PRD §3.9: "When the net is positive, the draw is the smaller of the
        account's `banked_wh` and the net"

        Design: Difficulty/combinatorial_formula/cf_monthly_netting_nested_min_max_partial_draw
        """
        sc, ctx, _app = _pto_ready(
            "EB2", program_overrides={"metering_variant": "ENERGY_BANKING",
                                      "true_up_mode": "BANK_ROLLOVER"})
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 50_000)  # bank 50,000 Wh
        r2 = post_reading(acct, *SEPTEMBER, 700_000, 0)
        # draw = min(50,000, 700,000) = 50,000; billable 650,000 Wh at
        # 30,000 mc/kWh -> 19,500 cents.
        assert r2["bank_drawn_wh"] == 50_000
        assert r2["bill_cents"] == 19_500
        assert get_account(acct)["banked_wh"] == 0


class TestReadingPostCascade:
    def test_reading_posts_ledger_and_flips_operating(self, api):
        """PRD §3.9: "Each new reading is created in `reading_status` `POSTED`,
        and the first reading to post also flips the account's application
        from `PTO_GRANTED` to `OPERATING`."
        PRD §3.9: "A tariff schedule of the account's program must be effective
        at `period_start` (`ERR_NO_EFFECTIVE_TARIFF`), and the reading pins
        that tariff into its `tariff_id` for netting."

        Design: Difficulty/transitive_cascade/tc_reading_post_ledger_balance_cascade
        """
        sc, ctx, app = _pto_ready("RLC")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 500_000, 800_000)
        assert_meter_reading(r1)
        assert r1["reading_status"] == "POSTED"
        assert r1["bill_cents"] == 0

        entries = list_ledger_entries(acct)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "EXPORT_SURPLUS_CREDIT"
        assert entry["amount_cents"] == 3_600
        assert entry["quantity_wh"] == 300_000
        assert entry["meter_reading_id"] == r1["id"]

        account = get_account(acct)
        assert account["credit_balance_cents"] == 3_600
        assert account["banked_wh"] == 0
        assert get_application(app["id"])["application_status"] == "OPERATING"
        assert r1["tariff_id"] == sc["tariff"]["id"]

    def test_energy_banking_first_reading_cascade(self, api):
        """PRD §3.9: "the first reading to post also flips the account's
        application from `PTO_GRANTED` to `OPERATING`."
        PRD §2.8: "Entries created by monthly netting reference their
        `meter_reading_id` and leave `annual_reconciliation_id` null; entries
        created by annual settlement reference their `annual_reconciliation_id`
        and leave `meter_reading_id` null."

        Design: Difficulty/transitive_cascade/tc_reading_post_ledger_balance_cascade
        """
        sc, ctx, app = _pto_ready(
            "RLC2", program_overrides={"metering_variant": "ENERGY_BANKING",
                                       "true_up_mode": "BANK_ROLLOVER"})
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 0, 100_000)
        assert r1["reading_status"] == "POSTED"
        assert r1["bank_deposited_wh"] == 100_000

        entries = list_ledger_entries(acct)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "BANK_DEPOSIT"
        assert entry["amount_cents"] == 0
        assert entry["quantity_wh"] == 100_000
        assert entry["meter_reading_id"] == r1["id"]
        assert entry["annual_reconciliation_id"] is None

        account = get_account(acct)
        assert account["credit_balance_cents"] == 0
        assert account["banked_wh"] == 100_000
        assert get_application(app["id"])["application_status"] == "OPERATING"
        assert r1["tariff_id"] == sc["tariff"]["id"]


class TestPostVoidConservation:
    def test_post_then_void_restores_zero_balance(self, api):
        """PRD §2.8: "Because the ledger is append-only, corrections follow an
        invariant: voiding or superseding a meter reading appends `REVERSAL`
        entries whose `amount_cents` and `quantity_wh` are the exact negation
        of that reading's original entries, so a posting followed by its
        reversal leaves both balances unchanged."
        PRD §3.9: "a technician may void a `POSTED` reading by supplying a
        `reason`, moving it to `VOIDED` with the same compensating `REVERSAL`
        entries."

        Design: Difficulty/compensating_invariant/ci_reading_post_void_ledger_conservation
        """
        sc, ctx, app = _pto_ready("CONS")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 500_000, 800_000)
        assert get_account(acct)["credit_balance_cents"] == 3_600

        r1 = validate_success(
            api.void_meter_reading(r1["id"], "misread dial", TECHNICIAN))
        assert r1["reading_status"] == "VOIDED"

        account = get_account(acct)
        assert account["credit_balance_cents"] == 0, (
            "exactly the pre-reading balance")
        entries = list_ledger_entries(acct)
        assert len(entries) == 2
        assert {(e["entry_type"], e["amount_cents"]) for e in entries} == {
            ("EXPORT_SURPLUS_CREDIT", 3_600), ("REVERSAL", -3_600)}
        assert_ledger_balances_consistent(entries, account)
        # The OPERATING flip is terminal and does not revert on void.
        assert get_application(app["id"])["application_status"] == "OPERATING"

    def test_void_restores_a_nonzero_prior_balance(self, api):
        """PRD §2.8: "voiding or superseding a meter reading appends
        `REVERSAL` entries whose `amount_cents` and `quantity_wh` are the exact
        negation of that reading's original entries, so a posting followed by
        its reversal leaves both balances unchanged."

        Design: Difficulty/compensating_invariant/ci_reading_post_void_ledger_conservation
        """
        sc, ctx, _app = _pto_ready("CONS2")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 0, 100_000)  # +1,200 cents
        # R2: raw bill 15,000; the bank covers min(1,200, 15,000) = 1,200.
        r2 = post_reading(acct, *SEPTEMBER, 500_000, 0)
        assert r2["credit_applied_cents"] == 1_200
        assert r2["bill_cents"] == 13_800
        assert get_account(acct)["credit_balance_cents"] == 0

        r2 = validate_success(
            api.void_meter_reading(r2["id"], "wrong meter", TECHNICIAN))
        assert r2["reading_status"] == "VOIDED"

        account = get_account(acct)
        assert account["credit_balance_cents"] == 1_200, (
            "voiding the second reading restores the balance it drew down")
        r1_after = validate_success(api.get_meter_reading(r1["id"], ADMIN))
        assert r1_after["reading_status"] == "POSTED"
        entries = list_ledger_entries(acct)
        assert len(entries) == 3
        assert_ledger_balances_consistent(entries, account)


class TestExactPeriodSupersede:
    def test_equal_period_supersedes_with_reversal_entries(self, api):
        """PRD §3.9: "Period uniqueness is exact-match semantics: a new reading
        whose `period_start` and `period_end` exactly equal an existing
        `POSTED` reading's supersedes it — the old reading moves to
        `SUPERSEDED` and `REVERSAL` entries negate its ledger postings"

        Design: Corner/cross_cutting_complexity_layers/cc_reading_exact_period_supersedes_with_reversal
        """
        sc, ctx, _app = _pto_ready("SUP")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 0, 100_000)  # +1,200 cents
        r2 = post_reading(acct, *AUGUST, 0, 50_000)   # +600 cents, supersedes

        r1_after = validate_success(api.get_meter_reading(r1["id"], ADMIN))
        assert r1_after["reading_status"] == "SUPERSEDED"
        assert r2["reading_status"] == "POSTED"

        account = get_account(acct)
        assert account["credit_balance_cents"] == 600, (
            "1,200 posted, -1,200 reversal, +600 replacement")
        entries = list_ledger_entries(acct)
        assert [(e["entry_type"], e["amount_cents"]) for e in entries] == [
            ("EXPORT_SURPLUS_CREDIT", 1_200),
            ("REVERSAL", -1_200),
            ("EXPORT_SURPLUS_CREDIT", 600)], (
            "append-only history: original, reversal, replacement")
        assert_ledger_balances_consistent(entries, account)


class TestReadingOptimisticConcurrency:
    def test_stale_account_version_rejected(self, api):
        """PRD §2.9: "Posting a meter reading requires the request to carry
        `expected_account_version`, holding the `version` of the target service
        account as the client last observed it; a mismatch with the account's
        current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_reading_stale_version_rejected
        """
        sc, ctx, _app = _pto_ready("OC2")
        acct = ctx["account"]["id"]
        stale_version = get_account(acct)["version"]
        post_reading(acct, *AUGUST, 500_000, 0)  # bumps the account version

        resp = api.create_meter_reading(
            create_meter_reading_payload(
                acct, stale_version, period_start=SEPTEMBER[0],
                period_end=SEPTEMBER[1], import_wh=400_000, export_wh=0),
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, 412)
        assert len(_readings_for(api, acct)) == 1


class TestReadingPeriodOverlap:
    def test_partial_overlap_rejected_boundary_touch_allowed(self, api):
        """PRD §3.9: "a period that only partially overlaps a `POSTED` reading
        is rejected with `ERR_READING_PERIOD_OVERLAP`"
        PRD §3.9: "a half-open billing window from `period_start` (inclusive)
        to `period_end` (exclusive, and strictly after the start)"

        Design: Corner/errors/err_reading_period_overlap_partial
        """
        sc, ctx, _app = _pto_ready("RO")
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 500_000, 0)

        # [2026-08-15, 2026-09-15) intersects the POSTED August window.
        resp = api.create_meter_reading(
            create_meter_reading_payload(
                acct, get_account(acct)["version"],
                period_start="2026-08-15T00:00:00Z",
                period_end="2026-09-15T00:00:00Z",
                import_wh=100_000, export_wh=0),
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_READING_PERIOD_OVERLAP, 422)

        # A period starting exactly at the prior period_end merely touches it.
        r3 = post_reading(acct, *SEPTEMBER, 100_000, 0)
        assert r3["reading_status"] == "POSTED"


class TestReadingAccountGates:
    def test_reading_requires_net_metering_status(self, api):
        """PRD §3.9: "Two cross-entity gates run in a pinned order: the
        account's `metering_status` must be `NET_METERING` first
        (`ERR_ACCOUNT_NOT_NET_METERING`), and only then is `account_status`
        checked for `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`)."

        Design: Corner/validations/v_reading_requires_net_metering_status
        """
        sc = setup_program_with_grid("NM")
        ctx = add_customer_account(sc, "1")
        app = drive_to_screen_passed(sc, ctx, size=10_000,
                                     production=15_000_000)
        # A completed bidirectional exchange alone does not unlock readings.
        schedule_and_complete_exchange(app["id"])
        acct = ctx["account"]["id"]
        resp = api.create_meter_reading(
            create_meter_reading_payload(
                acct, get_account(acct)["version"], import_wh=500_000,
                export_wh=100_000),
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_NET_METERING, 422)
        assert get_account(acct)["metering_status"] == "STANDARD"

    def test_reading_rejected_when_no_tariff_effective_at_period_start(
            self, api):
        """PRD §3.9: "A tariff schedule of the account's program must be
        effective at `period_start` (`ERR_NO_EFFECTIVE_TARIFF`), and the
        reading pins that tariff into its `tariff_id` for netting."

        Design: Corner/validations/v_reading_period_no_effective_tariff
        """
        sc, ctx, _app = _pto_ready(
            "NT",
            tariff_overrides={"effective_to": "2026-09-01T00:00:00Z"})
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 500_000, 0)  # August is inside the window

        resp = api.create_meter_reading(
            create_meter_reading_payload(
                acct, get_account(acct)["version"], period_start=OCTOBER[0],
                period_end=OCTOBER[1], import_wh=400_000, export_wh=0),
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_TARIFF, 422)

    def test_suspended_net_metering_account_blocks_readings(self, api):
        """PRD §3.2: "The dimensions evolve in parallel: an account may
        legitimately be `SUSPENDED` while `NET_METERING`."
        PRD §3.2: "an administrator may suspend an `ACTIVE` account (moving it
        to `SUSPENDED`, which blocks both application submissions and meter
        readings)"

        Design: Corner/state_machines/sm_parallel_dimensions_suspend_while_net_metering
        """
        sc, ctx, _app = _pto_ready("PD")
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 500_000, 800_000)  # -> OPERATING, +3,600

        get_success_data(api.suspend_service_account(acct, ADMIN))
        account = get_account(acct)
        assert account["account_status"] == "SUSPENDED"
        assert account["metering_status"] == "NET_METERING", (
            "the metering dimension is unaffected by suspension")

        resp = api.create_meter_reading(
            create_meter_reading_payload(
                acct, get_account(acct)["version"], period_start=SEPTEMBER[0],
                period_end=SEPTEMBER[1], import_wh=100_000, export_wh=0),
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 422)

        get_success_data(api.reactivate_service_account(acct, ADMIN))
        account = get_account(acct)
        assert account["account_status"] == "ACTIVE"
        assert account["metering_status"] == "NET_METERING"


class TestImmediateConsistency:
    def test_reading_response_and_account_reread_are_immediate(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.8: "The account's `credit_balance_cents` is the sum of
        `amount_cents` over every ledger entry the account has ever posted."

        Design: Corner/consistency_model/cm_immediate_read_after_write
        """
        sc, ctx, _app = _pto_ready("CM")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 0, 100_000)
        assert r1["bill_cents"] == 0, (
            "the create response already carries the computed bill")
        assert r1["tariff_id"] == sc["tariff"]["id"]
        assert get_account(acct)["credit_balance_cents"] == 1_200, (
            "the recomputed balance is visible on the immediate re-read")


class TestLedgerEntryShape:
    def test_ledger_entry_has_no_version_or_updated_at(self, api):
        """PRD §2.5: "The credit ledger is the deliberate exception: a
        `CreditLedgerEntry` is immutable and append-only, so it carries only
        `id` and `created_at` — both `updated_at` and `version` are absent."

        Design: Corner/entities/e_ledger_entry_has_no_version_field
        """
        sc, ctx, _app = _pto_ready("LED")
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 100_000)

        entries = list_ledger_entries(acct)
        assert len(entries) == 1
        entry = entries[0]
        assert_ledger_entry(entry)
        assert "version" not in entry
        assert "updated_at" not in entry
        for key in ("id", "created_at", "entry_type", "amount_cents",
                    "quantity_wh", "posted_at", "service_account_id"):
            assert key in entry, f"ledger entry missing {key}"
