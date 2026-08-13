"""Ginning charge tiering and rounding, the complete-ginning cascade to the
grower balance, the append-only ledger shape, and adjustment reversal."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    TEST_USERS,
    assert_balance_equals_ledger,
    assert_instant_equal,
    assert_ledger_entry,
    bales_by_tag,
    complete_ginning,
    create_grower,
    create_grower_payload,
    create_module,
    create_shift,
    get_bale,
    get_grower,
    get_module,
    gin_module,
    list_ledger_entries,
    list_module_bales,
    post_adjustment,
    queue_module,
    set_clock,
    start_ginning,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _ginning_entries(grower_id):
    return [e for e in list_ledger_entries(grower_id=grower_id)
            if e["entry_type"] == "GINNING_CHARGE"]


class TestGrowerDefaults:
    def test_grower_create_defaults_applied(self, api):
        """PRD: "Registration accepts an optional `patronage_rate`; when omitted
        it defaults to 0.20, the fraction of season ginning charges returned to
        the grower as patronage at settlement. The new grower's
        `credit_balance_cents` starts at 0."

        Design: Corner/entities/grower_create_defaults_and_computed_input_ignored
        """
        grower = validate_success(api.create_grower(
            create_grower_payload(membership_number="MB-C01",
                                  legal_name="Default Farm"), ADMIN),
            expected_status=201)
        assert grower["credit_balance_cents"] == 0
        assert grower["patronage_rate"] == 0.20
        fetched = get_grower(grower["id"])
        assert fetched["credit_balance_cents"] == 0
        assert fetched["patronage_rate"] == 0.20


class TestLedgerEntryShape:
    def test_ledger_entry_is_append_only_shape(self, api):
        """PRD: "One entity deviates: `LedgerEntry` is an append-only event log
        carrying only `id` and `created_at`. It has no `updated_at` and no
        `version`; entries are never modified after posting."
        PRD: "an accountant may also post a manual ledger adjustment — a signed
        `amount_cents` with a `season` and `memo` — which lands as an
        `ADJUSTMENT` entry"

        Design: Corner/entities/ledger_entry_has_no_version_field
        """
        grower = create_grower("MB-C03", "Ledger Farm")
        entry = validate_success(api.create_ledger_adjustment(
            grower["id"], {"season": "2026", "amount_cents": 250,
                           "memo": "opening correction"}, ACCOUNTANT),
            expected_status=201)
        assert_ledger_entry(entry)
        assert entry["entry_type"] == "ADJUSTMENT"
        assert entry["amount_cents"] == 250
        assert entry["season"] == "2026"
        assert entry["grower_id"] == grower["id"]

        fetched = validate_success(api.get_ledger_entry(entry["id"], ACCOUNTANT))
        assert_ledger_entry(fetched)


class TestGinningChargeTiering:
    def test_tier_straddle_and_grower_balance(self, api):
        """PRD: "The co-op charges 11.5 cents per pound for a grower's first
        100,000 lint pounds in a season and 9.5 cents per pound beyond that.
        The split is computed marginally per module: take the grower's lint
        pounds from modules of the same season already `GINNED` strictly
        earlier by `ginned_at` (ties broken by module `created_at` ascending)
        as the cumulative base; the current module's first pounds, up to
        whatever remains of the 100,000-pound tier, bill at 11.5 cents, and
        the rest bills at 9.5 cents."
        PRD: "The posting immediately recomputes the grower's
        `credit_balance_cents`."

        Design: Difficulty/combinatorial_formula/ginning_charge_tier_straddle_and_rounding_order
        """
        gt = create_grower("MB-300", "Tier Farm")
        shift = create_shift("2026", "STAND-C")
        ma = create_module(gt["id"], ticket_number="T-1", module_tag="MT-A",
                           gross_weight_lbs=62001)
        mb = create_module(gt["id"], ticket_number="T-2", module_tag="MT-B",
                           gross_weight_lbs=71000)
        # A ginned first (created_at tiebreak under a shared logical clock)
        gin_module(ma["id"], shift["id"], [("B-A1", 30001), ("B-A2", 30000)])
        gin_module(mb["id"], shift["id"], [("B-B1", 35000), ("B-B2", 35000)])

        entries = _ginning_entries(gt["id"])
        amounts = sorted(e["amount_cents"] for e in entries)
        # module A: 60001 lbs all tier 1: 60001*11.5 = 690011.5 -> 690012
        # module B: cumulative 60001 -> 39999 lbs at 11.5 + 30001 lbs at 9.5
        #           = 459988.5 + 285009.5 = 744998
        assert amounts == [-744998, -690012], f"unexpected charges {amounts}"
        assert len(entries) == 2
        grower = get_grower(gt["id"])
        assert grower["credit_balance_cents"] == -1435010
        assert_balance_equals_ledger(grower, list_ledger_entries(grower_id=gt["id"]))

    def test_per_module_rounding_not_per_bale(self, api):
        """PRD: "Rounding is pinned per module: each module's charge is rounded
        individually, and the grower's season total is the plain sum of those
        rounded module charges — never rounded per bale, and never computed by
        rounding a season-level raw sum."

        Design: Difficulty/combinatorial_formula/ginning_charge_tier_straddle_and_rounding_order
        """
        gc = create_grower("MB-301", "Round Farm")
        shift = create_shift("2026", "STAND-C")
        mc = create_module(gc["id"], ticket_number="T-1", module_tag="MT-C",
                           gross_weight_lbs=11000)
        gin_module(mc["id"], shift["id"], [("B-C1", 301), ("B-C2", 301)])

        entries = _ginning_entries(gc["id"])
        assert len(entries) == 1
        # 602 lbs * 11.5 = 6923.0 rounded once per module; per-bale rounding
        # would give 2 * round(301*11.5) = 2 * 3462 = 6924
        assert entries[0]["amount_cents"] == -6923
        assert get_grower(gc["id"])["credit_balance_cents"] == -6923

    def test_charge_depends_on_chronological_ginning_order(self, api):
        """PRD: "The split is computed marginally per module: take the grower's
        lint pounds from modules of the same season already `GINNED` strictly
        earlier by `ginned_at` (ties broken by module `created_at` ascending)
        as the cumulative base"

        Design: Difficulty/combinatorial_formula/ginning_charge_tier_straddle_and_rounding_order
        """
        gr = create_grower("MB-303", "Order Farm")
        shift = create_shift("2026", "STAND-C2")
        # big module ginned first (70000 lbs), 60001-lb module ginned second;
        # the logical clock strictly orders ginned_at.
        m_big = create_module(gr["id"], ticket_number="T-1", module_tag="MT-BIG",
                              gross_weight_lbs=71000)
        m_small = create_module(gr["id"], ticket_number="T-2",
                                module_tag="MT-SMALL", gross_weight_lbs=62001)
        gin_module(m_big["id"], shift["id"], [("B-BIG1", 35000), ("B-BIG2", 35000)])
        set_clock("2026-08-02T00:00:00Z")
        gin_module(m_small["id"], shift["id"], [("B-SM1", 30001), ("B-SM2", 30000)])

        entries = _ginning_entries(gr["id"])
        amounts = sorted(e["amount_cents"] for e in entries)
        # first module: 70000 lbs all tier 1 -> 805000
        # second module: cumulative 70000 -> 30000 at 11.5 + 30001 at 9.5
        #              = 345000 + 285009.5 = 630009.5 -> 630010
        assert amounts == [-805000, -630010], f"unexpected charges {amounts}"
        assert get_grower(gr["id"])["credit_balance_cents"] == -1435010


class TestCompleteGinningCascade:
    def test_module_and_bale_hops(self, api):
        """PRD: "On success the module transitions `GINNING → GINNED`, records
        `ginned_at` from the logical clock, and captures `ginned_by_user_id` as
        the acting `X-User-ID`"
        PRD: "One `Bale` is created per payload entry, each carrying a
        `module_id` back-reference to the module that produced it and starting
        with `classing_status` of `UNCLASSED` and `custody_status` of
        `ON_GIN_FLOOR`, and the module's `actual_lint_lbs` becomes the sum of
        its bales' weights"
        PRD: "Before any clock call is made, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/transitive_cascade/complete_ginning_charge_cascade_to_grower_balance
        """
        gx = create_grower("MB-500", "Cascade Farm")
        shift = create_shift("2026", "STAND-G")
        mx = create_module(gx["id"], ticket_number="T-1", module_tag="MT-X")
        queue_module(mx["id"], shift["id"])
        start_ginning(mx["id"])
        module = complete_ginning(mx["id"], [("B-X1", 500)],
                                  operator_user_id="gin-op-7")
        assert module["status"] == "GINNED"
        assert module["ginned_by_user_id"] == "gin-op-7"
        assert_instant_equal(module["ginned_at"], CLOCK_DEFAULT_ISO)
        assert module["actual_lint_lbs"] == 500

        bales = list_module_bales(mx["id"])
        assert len(bales) == 1
        bale = bales[0]
        assert bale["module_id"] == mx["id"]
        assert bale["classing_status"] == "UNCLASSED"
        assert bale["custody_status"] == "ON_GIN_FLOOR"

    def test_ledger_and_balance_hops(self, api):
        """PRD: "The module's charge is rounded half-up to whole cents and
        posted as a single `LedgerEntry` of type `GINNING_CHARGE` with a
        negative `amount_cents` and a `memo` naming the module ticket."
        PRD: "The posting immediately recomputes the grower's
        `credit_balance_cents`."
        PRD: "A `Grower`'s `credit_balance_cents` is a read-only running balance
        that starts at 0 at registration and equals the sum of `amount_cents`
        across every `LedgerEntry` posted for that grower."

        Design: Difficulty/transitive_cascade/complete_ginning_charge_cascade_to_grower_balance
        """
        gx = create_grower("MB-500", "Cascade Farm")
        shift = create_shift("2026", "STAND-G")
        mx = create_module(gx["id"], ticket_number="T-1", module_tag="MT-X")
        gin_module(mx["id"], shift["id"], [("B-X1", 500)],
                   operator_user_id="gin-op-7")

        entries = list_ledger_entries(grower_id=gx["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert_ledger_entry(entry)
        assert entry["entry_type"] == "GINNING_CHARGE"
        assert entry["amount_cents"] == -5750  # 500 lbs * 11.5c
        assert entry["season"] == "2026"

        grower = get_grower(gx["id"])
        assert grower["credit_balance_cents"] == -5750
        assert_balance_equals_ledger(grower, entries)


class TestAdjustmentReversal:
    def test_adjustment_posts_and_recomputes_balance(self, api):
        """PRD: "an accountant may also post a manual ledger adjustment — a
        signed `amount_cents` with a `season` and `memo` — which lands as an
        `ADJUSTMENT` entry, recomputes the grower's balance"
        PRD: "A `Grower`'s `credit_balance_cents` is a read-only running balance
        that starts at 0 at registration and equals the sum of `amount_cents`
        across every `LedgerEntry` posted for that grower."

        Design: Difficulty/compensating_invariant/ledger_adjustment_reversal_conserves_grower_balance
        """
        ga = create_grower("MB-911", "Adjust Farm")
        post_adjustment(ga["id"], 1000, memo="correct ticket weight")
        grower = get_grower(ga["id"])
        assert grower["credit_balance_cents"] == 1000
        assert_balance_equals_ledger(grower, list_ledger_entries(grower_id=ga["id"]))

    def test_reversal_restores_balance_and_entries_persist(self, api):
        """PRD: "entries are never modified after posting."
        PRD: "A `Grower`'s `credit_balance_cents` is a read-only running balance
        that starts at 0 at registration and equals the sum of `amount_cents`
        across every `LedgerEntry` posted for that grower."

        Design: Difficulty/compensating_invariant/ledger_adjustment_reversal_conserves_grower_balance
        """
        ga = create_grower("MB-911", "Adjust Farm")
        e1 = post_adjustment(ga["id"], 1000, memo="correct ticket weight")
        e2 = post_adjustment(ga["id"], -1000, memo="reverse ticket weight correction")

        grower = get_grower(ga["id"])
        assert grower["credit_balance_cents"] == 0, (
            "the +1000/-1000 pair leaves the balance exactly at its pre-pair value")

        entries = list_ledger_entries(grower_id=ga["id"])
        assert len(entries) == 2
        by_id = {e["id"]: e for e in entries}
        assert by_id[e1["id"]]["amount_cents"] == 1000
        assert by_id[e2["id"]]["amount_cents"] == -1000
        assert all(e["entry_type"] == "ADJUSTMENT" for e in entries)


class TestDuplicateBaleTag:
    def test_duplicate_bale_tag_across_growers_rejected(self, api):
        """PRD: "The operator submits a `bales` list, one entry per produced
        bale, each carrying a globally unique `bale_tag` and an actual lint
        scale weight `net_weight_lbs` of at least 1."
        PRD: "a tag already seen anywhere — including twice inside the same
        payload — fails with `ERR_DUPLICATE_BALE_TAG` (HTTP 409)."
        PRD: "On success the module transitions `GINNING → GINNED`"

        Design: Corner/validations/duplicate_bale_tag_across_growers_rejected
        """
        g1 = create_grower("MB-C54A", "Tag A")
        g2 = create_grower("MB-C54B", "Tag B")
        shift = create_shift("2026", "STAND-TG")
        m1 = create_module(g1["id"], ticket_number="T-1", module_tag="MT-TG-A")
        m2 = create_module(g2["id"], ticket_number="T-1", module_tag="MT-TG-B")
        gin_module(m1["id"], shift["id"], [("B-DUP", 500)])
        queue_module(m2["id"], shift["id"])
        start_ginning(m2["id"])

        resp = api.complete_ginning(
            m2["id"], {"bales": [{"bale_tag": "B-DUP", "net_weight_lbs": 500},
                                 {"bale_tag": "B-NEW", "net_weight_lbs": 500}]},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALE_TAG)

        assert get_module(m2["id"])["status"] == "GINNING", "rejection is atomic"
        assert list_module_bales(m2["id"]) == [], "B-NEW was not created either"


class TestImmediateConsistency:
    def test_complete_ginning_response_reflects_post_state(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD: "Every ledger posting recomputes the balance immediately, inside
        the same request, so the response of any mutating call reflects the new
        balance."
        PRD: "a `version` integer that increments by exactly 1 on every
        mutation of that resource"

        Design: Corner/consistency_model/create_response_reflects_post_state
        """
        g = create_grower("MB-C90", "Immediate Farm")
        shift = create_shift("2026", "STAND-IM")
        module = create_module(g["id"], ticket_number="T-1", module_tag="MT-IM")
        queue_module(module["id"], shift["id"])
        started = start_ginning(module["id"])
        pre_version = started["version"]

        completed = validate_success(api.complete_ginning(
            module["id"], {"bales": [{"bale_tag": "B-IM1", "net_weight_lbs": 500}]},
            OPERATOR))
        assert completed["status"] == "GINNED"
        assert completed["actual_lint_lbs"] == 500
        assert completed["ginned_by_user_id"] == "gin-op-1"
        assert completed["version"] == pre_version + 1
