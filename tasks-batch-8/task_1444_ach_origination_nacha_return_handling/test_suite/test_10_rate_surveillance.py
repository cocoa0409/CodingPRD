"""Unauthorized return-rate surveillance: dual windows, breach threshold, cases."""
from test_helpers import (
    assert_return_rate_snapshot,
    compute_snapshot_ok,
    create_active_originator,
    define_next_day_window,
    dispatch_batch_ok,
    entry_payload,
    get_success_data,
    make_entry_batch,
    read_entry,
    read_originator,
    register_return_ok,
    set_clock,
    setup_file_with_entries,
    setup_released_file,
    setup_settled_file,
    setup_standard_environment,
    validate_success,
)
from test_helpers import RISK_OFFICER


def _setup_trailing_mtd_divergence():
    """July: 40 DEBIT entries settled, one R07 return. August: 62 DEBIT entries
    dispatched (first_transmitted_at stamped) but not settled. Snapshot is taken
    at 2026-08-10T09:00:00Z, so the half-open 60-day window still includes the
    July activity while the August month-to-date window excludes the return."""
    define_next_day_window()
    org = create_active_originator("Acme Payroll", ["CCD", "PPD"],
                                   exposure_limit_cents=100_000_000)
    set_clock("2026-07-15T09:00:00Z")  # Wednesday
    _, _, july_entries = setup_settled_file(
        org, make_entry_batch(40, "DEBIT", 1_000, "ac"),
        effective_date="2026-07-15")
    set_clock("2026-07-15T11:00:00Z")
    register_return_ok(july_entries[0]["id"], "R07")

    set_clock("2026-08-10T09:00:00Z")  # Monday
    _, august_batch = setup_released_file(
        org, make_entry_batch(62, "DEBIT", 1_000, "ac2"),
        effective_date="2026-08-10")
    dispatch_batch_ok(august_batch)
    return org


class TestTrailingVsMtdDivergence:
    def test_same_population_yields_divergent_window_rates(self, api):
        """PRD 3.8: "The trailing variant counts, over the originator's `DEBIT`
        entries, the unauthorized return cases — those whose `is_unauthorized`
        holds, meaning codes `R05`, `R07`, and `R10` — whose `received_at` falls
        in the half-open window from sixty days before the computation instant
        up through that instant; an item exactly sixty days old is excluded."
        PRD 3.8: "The month-to-date variant repeats the same measurement over
        the closed window from the first day of the computation instant's UTC
        calendar month at 00:00:00.000Z through the computation instant — both
        ends inclusive — persisting `unauth_returns_mtd`, `debits_mtd`, and
        `rate_bps_mtd`."

        Design: Difficulty/dual_variant_calc/unauth_rate_trailing_vs_mtd_divergence
        """
        org = _setup_trailing_mtd_divergence()

        snap = validate_success(
            api.create_return_rate_snapshot(org["id"], RISK_OFFICER), 201)
        assert_return_rate_snapshot(snap)
        # round_half_up(10000 * 1 / 102) = 98; August has 0 returns / 62 debits.
        assert snap["unauth_returns_60d"] == 1
        assert snap["debits_60d"] == 102
        assert snap["rate_bps_trailing_60d"] == 98
        assert snap["unauth_returns_mtd"] == 0
        assert snap["debits_mtd"] == 62
        assert snap["rate_bps_mtd"] == 0

    def test_trailing_variant_alone_drives_breach_and_originator_fields(
            self, api):
        """PRD 3.8: "its `breach` flag is true when either rate is strictly
        greater than fifty basis points — half a percent; a rate of exactly
        fifty basis points does not breach."
        PRD 3.8: "Computing a snapshot also refreshes the originator's own
        `unauth_rate_bps_trailing` and `unauth_rate_bps_mtd` fields — the same
        two fields that unauthorized return registration refreshes per §3.6."

        Design: Difficulty/dual_variant_calc/unauth_rate_trailing_vs_mtd_divergence
        """
        org = _setup_trailing_mtd_divergence()

        snap = validate_success(
            api.create_return_rate_snapshot(org["id"], RISK_OFFICER), 201)
        # 98 bps > 50 bps on the trailing variant; the MTD variant is 0.
        assert snap["breach"] is True

        after = read_originator(org["id"])
        assert after["unauth_rate_bps_trailing"] == 98
        assert after["unauth_rate_bps_mtd"] == 0


def _setup_two_hundred_settled_debits():
    org = setup_standard_environment("Xi Inc", exposure_limit_cents=100_000_000)
    _, _, entries = setup_settled_file(
        org, make_entry_batch(200, "DEBIT", 1_000, "xi"))
    return org, entries


class TestExactlyFiftyBpsBoundary:
    def test_exactly_50_bps_does_not_breach(self, api):
        """PRD 3.8: "its `breach` flag is true when either rate is strictly
        greater than fifty basis points — half a percent; a rate of exactly
        fifty basis points does not breach."
        PRD 3.8: "The trailing rate, `rate_bps_trailing_60d`, is zero when the
        denominator is zero and is otherwise ten thousand times the numerator
        divided by the denominator, rounded half-up to an integer basis-point
        value; the underlying counts are persisted as `unauth_returns_60d` and
        `debits_60d`."

        Design: Difficulty/boundary_precision_check/unauth_rate_exactly_50_bps_no_breach
        """
        org, entries = _setup_two_hundred_settled_debits()
        register_return_ok(entries[0]["id"], "R07")  # 1 / 200 = exactly 50 bps

        snap = validate_success(
            api.create_return_rate_snapshot(org["id"], RISK_OFFICER), 201)
        assert snap["rate_bps_trailing_60d"] == 50
        assert snap["breach"] is False

        cases = get_success_data(api.list_risk_cases(org["id"], RISK_OFFICER))
        assert cases == [], "no RATE_BREACH case at exactly 50 bps"

    def test_second_return_flips_breach_and_auto_opens_case(self, api):
        """PRD 3.8: "Whenever a snapshot's `breach` is true and no `OPEN`
        RiskCase with `source` of `RATE_BREACH` exists for the originator, the
        system auto-opens one; the originator rate-field mutation at
        return-registration time triggers the same conditional creation, so
        surveillance fires from both the officer's explicit measurement and the
        inbound return stream."

        Design: Difficulty/boundary_precision_check/unauth_rate_exactly_50_bps_no_breach
        """
        org, entries = _setup_two_hundred_settled_debits()
        register_return_ok(entries[0]["id"], "R07")
        register_return_ok(entries[1]["id"], "R07")  # 2 / 200 = 100 bps

        snap = validate_success(
            api.create_return_rate_snapshot(org["id"], RISK_OFFICER), 201)
        assert snap["rate_bps_trailing_60d"] == 100
        assert snap["breach"] is True

        cases = get_success_data(api.list_risk_cases(org["id"], RISK_OFFICER))
        assert len(cases) == 1
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["source"] == "RATE_BREACH"


def _setup_forty_settled_debits():
    org = setup_standard_environment("Kappa LLC", exposure_limit_cents=100_000_000)
    _, _, entries = setup_settled_file(
        org, make_entry_batch(40, "DEBIT", 1_000, "kp"))
    return org, entries


class TestUnauthorizedReturnAutoCase:
    def test_unauthorized_return_recomputes_originator_rate(self, api):
        """PRD 3.6: "Registration creates a **ReturnCase** whose `entry_id`
        records the returned entry and whose `disposition` opens at `OPEN`:
        `received_at` is the logical-clock timestamp, `is_unauthorized` is true
        exactly when the code is `R05`, `R07`, or `R10`"
        PRD 3.6: "When the return is unauthorized, registration additionally
        recomputes both unauthorized return rates at the current clock and
        writes them to the originator's `unauth_rate_bps_trailing` and
        `unauth_rate_bps_mtd`"

        Design: Difficulty/transitive_cascade/unauthorized_return_rate_breach_auto_case
        """
        org, entries = _setup_forty_settled_debits()

        case = register_return_ok(entries[0]["id"], "R07")
        assert case["is_unauthorized"] is True
        assert case["disposition"] == "OPEN"
        assert read_entry(entries[0]["id"])["status"] == "RETURNED"

        after = read_originator(org["id"])
        # round_half_up(10000 * 1 / 40) = 250 bps on both variants (same month).
        assert after["unauth_rate_bps_trailing"] == 250

    def test_breach_auto_opens_rate_breach_risk_case(self, api, risk_officer_headers):
        """PRD 3.6: "if the recomputed figures breach the §3.8 threshold and no
        open rate-breach risk case exists for the originator, one is auto-opened
        on the spot."

        Design: Difficulty/transitive_cascade/unauthorized_return_rate_breach_auto_case
        """
        org, entries = _setup_forty_settled_debits()
        before = get_success_data(api.list_risk_cases(org["id"],
                                                      risk_officer_headers))
        assert before == []

        register_return_ok(entries[0]["id"], "R07")

        cases = get_success_data(api.list_risk_cases(org["id"],
                                                     risk_officer_headers))
        assert len(cases) == 1, "exactly one case auto-opened by the rate breach"
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["source"] == "RATE_BREACH"


def test_rate_denominator_counts_only_transmitted_debits(api):
    """PRD 3.8: "The denominator counts the originator's `DEBIT` entries whose
    `first_transmitted_at` falls in that same half-open window."

    Design: Corner/calculations/rate_denominator_counts_only_transmitted_debits
    """
    org = setup_standard_environment("Denom Co")
    # File A: one DEBIT + one CREDIT, both settled. File B: a DEBIT entry that
    # is never released, so it never receives first_transmitted_at.
    _, _, entries_a = setup_settled_file(org, [
        entry_payload("DEBIT", 1_000, "dn-1"),
        entry_payload("CREDIT", 1_000, "dn-2"),
    ])
    setup_file_with_entries(org, [entry_payload("DEBIT", 1_000, "dn-3")])

    register_return_ok(entries_a[0]["id"], "R05")

    snap = compute_snapshot_ok(org["id"])
    assert_return_rate_snapshot(snap)
    # The settled CREDIT and the never-transmitted DEBIT are both excluded.
    assert snap["debits_60d"] == 1
    assert snap["unauth_returns_60d"] == 1
    assert snap["rate_bps_trailing_60d"] == 10_000
    assert snap["breach"] is True


def test_snapshot_immutable_and_zero_denominator(api, risk_officer_headers):
    """PRD 2.5: "A ReturnRateSnapshot is an immutable audit record, and a
    GlPosting is an append-only ledger event; each carries only `id` and
    `created_at`, and both `updated_at` and `version` are absent from them."
    PRD 3.8: "The trailing rate, `rate_bps_trailing_60d`, is zero when the
    denominator is zero and is otherwise ten thousand times the numerator
    divided by the denominator, rounded half-up to an integer basis-point value"

    Design: Corner/entities/snapshot_and_posting_are_immutable_event_records
    """
    org = create_active_originator("Imm Co", ["PPD"], exposure_limit_cents=1_000_000)

    snap = validate_success(
        api.create_return_rate_snapshot(org["id"], risk_officer_headers), 201)
    assert_return_rate_snapshot(snap)
    assert "version" not in snap, "immutable audit record exposes no version"
    assert "updated_at" not in snap
    assert snap["debits_60d"] == 0
    assert snap["rate_bps_trailing_60d"] == 0
    assert snap["rate_bps_mtd"] == 0
    assert snap["breach"] is False

    rows = get_success_data(
        api.list_return_rate_snapshots(org["id"], risk_officer_headers))
    assert len(rows) == 1
    assert rows[0]["id"] == snap["id"]
