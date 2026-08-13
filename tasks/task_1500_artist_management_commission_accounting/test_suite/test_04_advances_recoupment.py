"""Advances, the recoupment waterfall (FIFO vs PRO_RATA), the settle cascade,
and the principal partition invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_advance_partition,
    create_and_verify_event,
    get_success_data,
    issue_advance,
    get_advance,
    refresh_artist,
    report_event,
    setup_artist_team,
    settle_event,
    validate_error,
    validate_success,
    verify_event,
)

ADMIN = TEST_USERS["firm_admin_headers"]


def _setup_two_advance_artist(api, stage_name, recoupment_policy):
    """Artist with Advance A 50000 @100% (issued 2026-01-05), Advance B 60000
    @50% (issued 2026-02-01), both cross-collateralized, and a VERIFIED TOURING
    event gross 94118 (commission 14118, cash share on full receipt 80000)."""
    sc = setup_artist_team(stage_name=stage_name,
                               recoupment_policy=recoupment_policy)
    adv_a = issue_advance(sc, principal_cents=50000, issued_date="2026-01-05",
                          recoup_pct_bps=10000, applies_to_income_types=[])
    adv_b = issue_advance(sc, principal_cents=60000, issued_date="2026-02-01",
                          recoup_pct_bps=5000, applies_to_income_types=[])
    event = create_and_verify_event(sc, gross_amount_cents=94118,
                                    recognition_date="2026-03-10",
                                    source_name=f"Promoter {stage_name}")
    assert event["commission_amount_cents"] == 14118
    return sc, adv_a, adv_b, event


class TestWaterfallPolicyVariants:
    def test_fifo_waterfall_allocation(self, api):
        """PRD: "Under the `FIFO` policy the oldest advance eats first: each
        advance in order takes the smaller of its `outstanding_cents` and the
        remaining cash share times its `recoup_pct_bps` divided by 10000, rounded
        half up"
        PRD: "With a cash share of 80000, advance A outstanding 50000 at 100%
        takes 50000, then advance B outstanding 60000 at 50% takes 15000, for a
        total recouped of 65000."

        Design: Difficulty/dual_variant_calc/advance_waterfall_fifo_vs_pro_rata
        """
        sc, adv_a, adv_b, event = _setup_two_advance_artist(api, "Fifo Act", "FIFO")
        settled = settle_event(sc, event["id"], "2026-03-12", 94118)

        a = get_advance(sc, adv_a["id"])
        assert a["recouped_cents"] == 50000
        assert a["outstanding_cents"] == 0
        assert a["status"] == "RECOUPED"
        b = get_advance(sc, adv_b["id"])
        assert b["recouped_cents"] == 15000, "50% of the remaining 30000"
        assert b["outstanding_cents"] == 45000
        assert b["status"] == "ACTIVE"
        assert settled["recouped_amount_cents"] == 65000
        assert settled["artist_payable_cents"] == 15000

    def test_pro_rata_waterfall_allocation(self, api):
        """PRD: "Under the `PRO_RATA` policy, nothing is recouped when the
        eligible outstanding total is zero; otherwise each advance's raw share is
        the cash share times its `outstanding_cents` divided by the total
        outstanding, rounded down — except the last advance in order, which
        receives the remainder of the cash share after the earlier shares"
        PRD: "With the same inputs, A's raw share is 36363 applied in full, while
        B's raw share is 43637 of which 21819 applies at 50%, for a total recouped
        of 58182."

        Design: Difficulty/dual_variant_calc/advance_waterfall_fifo_vs_pro_rata
        """
        sc, adv_a, adv_b, event = _setup_two_advance_artist(
            api, "Pro Act", "PRO_RATA")
        settled = settle_event(sc, event["id"], "2026-03-12", 94118)

        a = get_advance(sc, adv_a["id"])
        assert a["recouped_cents"] == 36363, "share floor(80000*50000/110000) @100%"
        assert a["status"] == "ACTIVE"
        b = get_advance(sc, adv_b["id"])
        assert b["recouped_cents"] == 21819, "share 43637 @50% -> round_half_up(21818.5)"
        assert b["status"] == "ACTIVE"
        assert settled["recouped_amount_cents"] == 58182
        assert settled["artist_payable_cents"] == 21818

        # Identical inputs under FIFO recoup 65000: the policy variant gap is 6818.
        sc_f, adv_fa, adv_fb, event_f = _setup_two_advance_artist(
            api, "Fifo Twin", "FIFO")
        settle_event(sc_f, event_f["id"], "2026-03-12", 94118)
        fifo_a = get_advance(sc_f, adv_fa["id"])
        fifo_b = get_advance(sc_f, adv_fb["id"])
        assert (fifo_a["recouped_cents"] + fifo_b["recouped_cents"]
                - a["recouped_cents"] - b["recouped_cents"]) == 6818


class TestFifoMinScopeAndOrdering:
    def test_fifo_min_scope_ordering(self, api):
        """PRD: "Eligible advances are the artist's `ACTIVE` advances whose
        `applies_to_income_types` is empty or contains the event's income type,
        walked in order of `issued_date` ascending with ties broken by
        `created_at` ascending — never by id."
        PRD: "each advance in order takes the smaller of its `outstanding_cents`
        and the remaining cash share times its `recoup_pct_bps` divided by 10000,
        rounded half up"

        Design: Difficulty/combinatorial_formula/waterfall_mode_a_min_scope_order
        """
        sc = setup_artist_team(stage_name="Water Act", recoupment_policy="FIFO")
        adv1 = issue_advance(sc, 20000, "2026-01-05", recoup_pct_bps=10000,
                             applies_to_income_types=[])
        adv2 = issue_advance(sc, 10000, "2026-01-10", recoup_pct_bps=5000,
                             applies_to_income_types=["TOURING"])
        adv3 = issue_advance(sc, 90000, "2026-02-01", recoup_pct_bps=10000,
                             applies_to_income_types=[])
        event = create_and_verify_event(sc, gross_amount_cents=94118,
                                        recognition_date="2026-03-10",
                                        source_name="Promoter W")
        assert event["commission_amount_cents"] == 14118

        settled = settle_event(sc, event["id"], "2026-03-12", 94118)

        a1 = get_advance(sc, adv1["id"])
        assert (a1["recouped_cents"], a1["outstanding_cents"], a1["status"]) == (
            20000, 0, "RECOUPED"), "A1 took min(20000, 80000) first"
        a2 = get_advance(sc, adv2["id"])
        assert (a2["recouped_cents"], a2["outstanding_cents"], a2["status"]) == (
            10000, 0, "RECOUPED"), "A2 took min(10000, round_half_up(60000*0.5))"
        a3 = get_advance(sc, adv3["id"])
        assert (a3["recouped_cents"], a3["outstanding_cents"], a3["status"]) == (
            50000, 40000, "ACTIVE"), "A3 took min(90000, remaining 50000)"
        assert settled["recouped_amount_cents"] == 80000
        assert settled["artist_payable_cents"] == 0

    def test_advance_scope_excludes_other_income_types(self, api):
        """PRD: "an empty list means the advance is cross-collateralized against
        all four income types, while a non-empty list restricts recoupment to the
        listed types."

        Design: Difficulty/combinatorial_formula/waterfall_mode_a_min_scope_order
        """
        sc = setup_artist_team(stage_name="Scope Act", recoupment_policy="FIFO",
                                   income_types=("TOURING", "RECORDING"))
        adv1 = issue_advance(sc, 20000, "2026-01-05", recoup_pct_bps=10000,
                             applies_to_income_types=[])
        adv2 = issue_advance(sc, 10000, "2026-01-10", recoup_pct_bps=5000,
                             applies_to_income_types=["TOURING"])
        adv3 = issue_advance(sc, 90000, "2026-02-01", recoup_pct_bps=10000,
                             applies_to_income_types=[])
        # RECORDING event at 2000bps: commission 6000, cash share 24000.
        event = create_and_verify_event(sc, gross_amount_cents=30000,
                                        recognition_date="2026-03-10",
                                        income_type="RECORDING",
                                        source_name="Label W")

        settled = settle_event(sc, event["id"], "2026-03-12", 30000)

        a1 = get_advance(sc, adv1["id"])
        assert (a1["recouped_cents"], a1["status"]) == (20000, "RECOUPED")
        a2 = get_advance(sc, adv2["id"])
        assert (a2["recouped_cents"], a2["outstanding_cents"], a2["status"]) == (
            0, 10000, "ACTIVE"), "TOURING-scoped A2 is not eligible for RECORDING"
        a3 = get_advance(sc, adv3["id"])
        assert (a3["recouped_cents"], a3["outstanding_cents"]) == (4000, 86000)
        assert settled["recouped_amount_cents"] == 24000
        assert settled["artist_payable_cents"] == 0


class TestSettleCascade:
    def _setup_cascade(self, api):
        """Artist + advance 40000 @100% + VERIFIED event 94118 (cash 80000)."""
        sc = setup_artist_team(stage_name="Casc Act", recoupment_policy="FIFO")
        advance = issue_advance(sc, 40000, "2026-01-05", recoup_pct_bps=10000,
                                applies_to_income_types=[])
        event = create_and_verify_event(sc, gross_amount_cents=94118,
                                        recognition_date="2026-03-10",
                                        source_name="Promoter Ca")
        return sc, advance, event

    def test_settle_flips_advance_to_recouped(self, api):
        """PRD: "In both policies an advance whose `outstanding_cents` reaches
        zero through the waterfall moves from `ACTIVE` to `RECOUPED`; the event's
        `recouped_amount_cents` is the total taken, and `artist_payable_cents` is
        the cash share minus it."

        Design: Difficulty/transitive_cascade/settle_advance_recoup_artist_cascade
        """
        sc, advance, event = self._setup_cascade(api)
        settled = settle_event(sc, event["id"], "2026-03-12", 94118)

        after = get_advance(sc, advance["id"])
        assert after["recouped_cents"] == 40000, "Waterfall took min(40000, 80000)"
        assert after["outstanding_cents"] == 0
        assert after["status"] == "RECOUPED", "Flipped by the waterfall mutation"
        assert settled["recouped_amount_cents"] == 40000
        assert settled["artist_payable_cents"] == 40000
        assert settled["received_amount_cents"] == 94118
        assert settled["received_date"] == "2026-03-12"

    def test_settle_recomputes_artist_ledger(self, api):
        """PRD: "The cascade continues outward: any advance whose outstanding
        balance reaches zero flips to `RECOUPED`, the artist's aggregates are
        recomputed with a `version` increment"
        PRD: "`unrecouped_advance_balance_cents` — the sum of `outstanding_cents`
        over the artist's advances in `ACTIVE` status."

        Design: Difficulty/transitive_cascade/settle_advance_recoup_artist_cascade
        """
        sc, advance, event = self._setup_cascade(api)
        pre = refresh_artist(sc)
        assert pre["unrecouped_advance_balance_cents"] == 40000
        pre_version = pre["version"]

        settle_event(sc, event["id"], "2026-03-12", 94118)

        post = refresh_artist(sc)
        assert post["unrecouped_advance_balance_cents"] == 0
        assert post["version"] == pre_version + 1, (
            "The artist's version increments when the aggregates recompute"
        )


class TestPrincipalPartitionInvariant:
    def _setup_partition(self, api):
        """Artist + FIFO agreement; advance 100000 @100%; VERIFIED event 94118
        (cash share 80000)."""
        sc = setup_artist_team(stage_name="Part Act", recoupment_policy="FIFO")
        advance = issue_advance(sc, 100000, "2026-01-05", recoup_pct_bps=10000,
                                applies_to_income_types=[])
        event = create_and_verify_event(sc, gross_amount_cents=94118,
                                        recognition_date="2026-03-10",
                                        source_name="Promoter Pa")
        return sc, advance, event

    def test_partition_holds_after_settle(self, api):
        """PRD: "it moves the full `outstanding_cents` into `written_off_cents`,
        zeroes the outstanding (preserving the identity that principal equals
        recouped plus outstanding plus written-off)"

        Design: Difficulty/compensating_invariant/advance_principal_partition_invariant
        """
        sc, advance, event = self._setup_partition(api)
        settle_event(sc, event["id"], "2026-03-12", 94118)

        after = get_advance(sc, advance["id"])
        assert after["recouped_cents"] == 80000
        assert after["outstanding_cents"] == 20000
        assert after["written_off_cents"] == 0
        assert_advance_partition(after)
        assert after["status"] == "ACTIVE"

    def test_partition_holds_after_write_off(self, api):
        """PRD: "it moves the full `outstanding_cents` into `written_off_cents`,
        zeroes the outstanding (preserving the identity that principal equals
        recouped plus outstanding plus written-off), and moves the advance to
        `WRITTEN_OFF`, recomputing the artist's aggregate and incrementing the
        artist's `version`."

        Design: Difficulty/compensating_invariant/advance_principal_partition_invariant
        """
        sc, advance, event = self._setup_partition(api)
        settle_event(sc, event["id"], "2026-03-12", 94118)
        written = validate_success(api.write_off_advance(advance["id"], ADMIN))

        assert written["recouped_cents"] == 80000
        assert written["outstanding_cents"] == 0
        assert written["written_off_cents"] == 20000
        assert written["status"] == "WRITTEN_OFF"
        assert_advance_partition(written), "No drift from the forward+compensating pair"

        artist = refresh_artist(sc)
        assert artist["unrecouped_advance_balance_cents"] == 0

    def test_write_off_recouped_advance_rejected(self, api):
        """PRD: "writing off requires `ACTIVE` status with a positive outstanding
        balance — a wrong state or a zero balance fails with `ERR_INVALID_STATE`"

        Design: Corner/endpoints/write_off_recouped_advance_rejected
        """
        sc = setup_artist_team(stage_name="Paid Act", recoupment_policy="FIFO")
        advance = issue_advance(sc, 50000, "2026-01-05", recoup_pct_bps=10000,
                                applies_to_income_types=[])
        # Cash share 80000 recoups the whole 50000 advance.
        event = create_and_verify_event(sc, gross_amount_cents=94118,
                                        recognition_date="2026-03-10",
                                        source_name="PPd")
        settle_event(sc, event["id"], "2026-03-12", 94118)
        settled_advance = get_advance(sc, advance["id"])
        assert settled_advance["status"] == "RECOUPED"

        resp = api.write_off_advance(advance["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_advance(sc, advance["id"])
        assert after["written_off_cents"] == 0
        assert after["status"] == "RECOUPED"
