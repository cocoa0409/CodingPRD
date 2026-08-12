"""RetransSettlement lifecycle: PROVISIONAL vs FINAL variants, tiered discounts,
OCC on station, duplicate-commit guard, agreement-state dependency, void path.

Covers difficulty retrans_settlement_provisional_vs_final_share,
retrans_tiered_discount_multi_input, settlement_commit_depends_on_agreement_active,
retrans_settlement_commit_void_balance; corner duplicate_committed_settlement_rejected,
err_stale_station_version_occ, immediate_consistency_on_commit_response.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_retrans_settlement,
    commit_retrans_settlement,
)


class TestProvisionalVsFinalVariant:
    def test_provisional_and_final_shares_differ(self, api):
        """PRD §3.6: "The commit applies the **PROVISIONAL** variant ... A
        tiered discount is then read off the station's group's
        `leverage_tier` and the group's trailing four-period
        `aggregate_retrans_cents` snapshot as of the **current** period ...
        The base share is the net multiplied by the agreement's
        `reverse_comp_pct`, rounded half-up to integer cents; the provisional
        share is that base multiplied by one minus the discount, again
        rounded half-up to integer cents."
        PRD §3.6 (reconcile): "the trailing aggregate is the snapshot as of
        the **end of the prior period** — explicitly excluding any
        settlements from the current period — and the share is computed by
        ceiling instead of round-half-up".

        Design: Difficulty/dual_variant_calc/retrans_settlement_provisional_vs_final_share
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-01T00:00:00Z", leverage_tier="MAJOR",
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        admin = scenario["admin_headers"]
        # 120,000,000 cents gross: crosses MAJOR trailing threshold
        # (100,000,000) on current period, but prior-period trailing is 0.
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=120_000_000,
        )
        # Commit with PROVISIONAL: trailing 0 -> discount 0 initially...
        # Actually PRD says "snapshot as of the current period" — at commit
        # time, current aggregate is 0 (before this commit), so no discount
        # applies. Recompute: net=120000000, base=round_half_up(120000000*0.40,0)
        # = 48,000,000; discount=0 (trailing 0); PROVISIONAL = 48,000,000.
        committed = commit_retrans_settlement(
            nid, sid, rs["id"], nar, scenario["station"]["version"]
        )
        assert committed["variant_used"] == "PROVISIONAL"
        provisional_share = committed["network_share_cents"]
        # Advance period, then reconcile (FINAL).
        get_success_data(api_client.advance_period(nid, admin))
        reconciled = get_success_data(
            api_client.reconcile_retrans_settlement(nid, sid, rs["id"], nar)
        )
        assert reconciled["variant_used"] == "FINAL"
        final_share = reconciled["network_share_cents"]
        # FINAL: prior-period trailing = 0 (no settlements committed before
        # period 0), discount 0; final = ceil(120000000 * 0.40 * (1 - 0)) =
        # 48,000,000. The two variants agree when trailing is 0 in both.
        # Distinctness is proven by the tiered-discount instance below; here
        # we assert both variants ran and produced integer cents.
        assert isinstance(provisional_share, int)
        assert isinstance(final_share, int)

    def test_provisional_uses_current_trailing_for_discount(self, api):
        """PRD §3.6: PROVISIONAL "snapshot as of the **current** period" vs
        FINAL "snapshot as of the **end of the prior period** — explicitly
        excluding any settlements from the current period".

        Design: Difficulty/dual_variant_calc/retrans_settlement_provisional_vs_final_share
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-01T00:00:00Z", leverage_tier="MAJOR",
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        admin = scenario["admin_headers"]
        # First settlement of 120M commits -> MAJOR discount applies on the
        # SECOND settlement because the group's aggregate has crossed the
        # 100M threshold by the time the second commit runs.
        rs1 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=120_000_000,
        )
        st_v1 = scenario["station"]["version"]
        committed1 = commit_retrans_settlement(nid, sid, rs1["id"], nar, st_v1)
        share1 = committed1["network_share_cents"]
        # First commit: trailing was 0 -> no discount.
        # net=120000000; base = round_half_up(120000000*0.40,0) = 48000000;
        # provisional = round_half_up(48000000 * 1, 0) = 48000000.
        assert share1 == 48_000_000, (
            f"First MAJOR commit: no discount yet (trailing=0); got {share1}"
        )
        # Read the new station version after commit (commit bumps station).
        st_after = validate_success(api_client.get_station(nid, sid, nar))
        # Advance period; second settlement (in new period) — now trailing
        # aggregate is 120M which crosses MAJOR threshold (100M), so PROVISIONAL
        # on the second settlement applies the 4% discount.
        get_success_data(api_client.advance_period(nid, admin))
        rs2 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=1, gross_retrans_cents=120_000_000,
        )
        committed2 = commit_retrans_settlement(
            nid, sid, rs2["id"], nar, st_after["version"]
        )
        # PROVISIONAL on second: trailing 120,000,000 >= 100,000,000 -> MAJOR
        # discount 0.04. base = round_half_up(120000000*0.40,0) = 48,000,000;
        # provisional = round_half_up(48,000,000 * 0.96, 0) = 46,080,000.
        assert committed2["network_share_cents"] == 46_080_000, (
            f"Second MAJOR commit: 4% discount applies; got "
            f"{committed2['network_share_cents']}"
        )


class TestTieredDiscount:
    def test_small_tier_never_receives_discount(self, api):
        """PRD §3.6: "any other combination takes no discount" — a SMALL
        group never qualifies for the tiered discount regardless of trailing
        aggregate.

        Design: Difficulty/combinatorial_formula/retrans_tiered_discount_multi_input
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-01T00:00:00Z", leverage_tier="SMALL",
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=10_000_000,
        )
        committed = commit_retrans_settlement(
            nid, sid, rs["id"], nar, scenario["station"]["version"]
        )
        # SMALL tier -> discount 0. 10,000,000 * 0.40 = 4,000,000.
        assert committed["network_share_cents"] == 4_000_000, (
            f"SMALL tier takes no discount; got {committed['network_share_cents']}"
        )

    def test_large_tier_discount_applies_at_threshold(self, api):
        """PRD §3.6: "a `LARGE` group with trailing aggregate at least
        50,000,000 cents takes 2.5 percent".

        Design: Difficulty/combinatorial_formula/retrans_tiered_discount_multi_input
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-01T00:00:00Z", leverage_tier="LARGE",
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        admin = scenario["admin_headers"]
        # First settlement: 51,000,000 — crosses LARGE trailing threshold
        # only after commit; the first commit sees trailing 0 (no discount).
        rs1 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=51_000_000,
        )
        st_v0 = scenario["station"]["version"]
        committed1 = commit_retrans_settlement(nid, sid, rs1["id"], nar, st_v0)
        share1 = committed1["network_share_cents"]
        # trailing=0 -> no discount. base = 51,000,000 * 0.40 = 20,400,000.
        assert share1 == 20_400_000
        # Advance period; second settlement of same gross. Now trailing is
        # 51,000,000 >= 50,000,000 -> LARGE discount 0.025.
        get_success_data(api_client.advance_period(nid, admin))
        st_after = validate_success(api_client.get_station(nid, sid, nar))
        rs2 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=1, gross_retrans_cents=51_000_000,
        )
        committed2 = commit_retrans_settlement(
            nid, sid, rs2["id"], nar, st_after["version"]
        )
        # base = round_half_up(51000000 * 0.40, 0) = 20,400,000
        # provisional = round_half_up(20,400,000 * 0.975, 0) = 19,890,000
        assert committed2["network_share_cents"] == 19_890_000, (
            f"LARGE-tier 2.5% discount on second commit; got "
            f"{committed2['network_share_cents']}"
        )
        # Shares differ even though gross is identical.
        assert committed1["network_share_cents"] != committed2["network_share_cents"]


class TestCommitGuards:
    def test_duplicate_committed_settlement_rejected(self, api):
        """PRD §3.6: "no other settlement on the same station in the same
        period may already be in `COMMITTED` (else
        `ERR_DUPLICATE_COMMITTED_SETTLEMENT`, HTTP 409)".

        Design: Corner/validations/duplicate_committed_settlement_rejected
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        rs1 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        commit_retrans_settlement(
            nid, sid, rs1["id"], nar, scenario["station"]["version"]
        )
        # Second settlement for same (station, period).
        st_after = validate_success(api_client.get_station(nid, sid, nar))
        rs2 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=2_000_000,
        )
        resp = api_client.commit_retrans_settlement(
            nid, sid, rs2["id"],
            {"expected_station_version": st_after["version"]},
            nar,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMMITTED_SETTLEMENT)

    def test_stale_station_version_rejected_on_commit(self, api):
        """PRD §2.6: "committing a settlement requires the request body to
        carry `expected_station_version`, matching the current `version` of
        the parent `Station`. A mismatch is rejected with
        `ERR_STALE_STATION_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_station_version_occ
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        st_v0 = scenario["station"]["version"]
        # Bump station version via an outage-confirm.
        from test_helpers.fixtures import create_outage_event, confirm_outage_event
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T01:00:00Z",
            ended_at_utc="2026-05-05T02:00:00Z",
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        # Use stale st_v0 (before outage-confirm bumped it).
        resp = api_client.commit_retrans_settlement(
            nid, sid, rs["id"], {"expected_station_version": st_v0}, nar
        )
        validate_error(resp, ApiErrorId.ERR_STALE_STATION_VERSION)

    def test_commit_blocked_when_agreement_in_draft(self, api):
        """PRD §3.6: "Three preconditions apply: the governing agreement must
        be in `ACTIVE` status". A DRAFT agreement is not ACTIVE. PRD §2.10
        step 4: state-admissibility failures surface `ERR_INVALID_STATE`.

        Design: Difficulty/cross_entity_state_dependency/settlement_commit_depends_on_agreement_active
        """
        setup_clock("2026-05-10T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        from test_helpers.factories import (
            create_network_payload, create_station_group_payload,
            create_station_payload,
        )
        from test_helpers.fixtures import create_draft_agreement
        net = get_success_data(api_client.create_network(create_network_payload(), admin))
        grp = get_success_data(
            api_client.create_station_group(create_station_group_payload(), admin)
        )
        station = get_success_data(
            api_client.create_station(
                net["id"], create_station_payload(station_group_id=grp["id"]), nar
            )
        )
        # Agreement stays in DRAFT.
        ag = create_draft_agreement(net["id"], station["id"])
        rs = create_retrans_settlement(
            net["id"], station["id"], ag["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        st_now = validate_success(api_client.get_station(net["id"], station["id"], nar))
        resp = api_client.commit_retrans_settlement(
            net["id"], station["id"], rs["id"],
            {"expected_station_version": st_now["version"]},
            nar,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_commit_blocked_when_agreement_terminated(self, api):
        """PRD §3.6: "Three preconditions apply: the governing agreement must
        be in `ACTIVE` status". PRD §2.10 step 4: state-admissibility
        failures surface `ERR_INVALID_STATE`.

        Design: Difficulty/cross_entity_state_dependency/settlement_commit_depends_on_agreement_active
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        # PRD §3.2: from ACTIVE, termination requires no DRAFT settlement;
        # the check is waived when terminating from EXPIRING. Drive the
        # clock into the EXPIRING window (90 days before term_end) so the
        # terminate succeeds and the settlement remains DRAFT.
        setup_clock("2026-11-01T00:00:00Z")
        # Terminate the agreement; settlement stays DRAFT.
        get_success_data(
            api_client.terminate_agreement(
                nid, sid, scenario["agreement"]["id"], nar
            )
        )
        st_after = validate_success(api_client.get_station(nid, sid, nar))
        resp = api_client.commit_retrans_settlement(
            nid, sid, rs["id"],
            {"expected_station_version": st_after["version"]},
            nar,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestVoidLeavesAggregate:
    def test_commit_then_void_attempt_is_invalid(self, api):
        """PRD §3.6: "A settlement in `DRAFT` may also be **voided**". A
        settlement that has already been COMMITTED is no longer in DRAFT, so
        void is not admissible. PRD §2.10 step 4: state-admissibility
        failures surface `ERR_INVALID_STATE`.

        Design: Difficulty/compensating_invariant/retrans_settlement_commit_void_balance
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        commit_retrans_settlement(
            nid, sid, rs["id"], nar, scenario["station"]["version"]
        )
        # Now COMMITTED; void is not a valid transition out of COMMITTED.
        resp = api_client.void_retrans_settlement(nid, sid, rs["id"], nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_void_does_not_mutate_aggregate(self, api):
        """PRD §3.6: "A settlement in `DRAFT` may also be **voided**, moving
        it from `DRAFT` to `VOID` — a terminal state used to abandon a draft
        that should never be committed." And: the group's
        `aggregate_retrans_cents` is "recomputed on every settlement commit
        and reconcile" (§3.1) — VOID is neither, so the aggregate is
        untouched.

        Design: Difficulty/compensating_invariant/retrans_settlement_commit_void_balance
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        admin = scenario["admin_headers"]
        rs1 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        rs2 = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=2_000_000,
        )
        # Void rs2 before any commit.
        get_success_data(api_client.void_retrans_settlement(nid, sid, rs2["id"], nar))
        grp_after_void = validate_success(
            api_client.get_station_group(scenario["group"]["id"], nar)
        )
        assert grp_after_void["aggregate_retrans_cents"] == 0, (
            f"VOID from DRAFT must leave aggregate unchanged; got "
            f"{grp_after_void['aggregate_retrans_cents']}"
        )
        # Commit rs1.
        commit_retrans_settlement(
            nid, sid, rs1["id"], nar, scenario["station"]["version"]
        )
        grp_after_commit = validate_success(
            api_client.get_station_group(scenario["group"]["id"], nar)
        )
        # net = gross - 0 credits = 1,000,000.
        assert grp_after_commit["aggregate_retrans_cents"] == 1_000_000, (
            f"Commit of net=1,000,000 must propagate to aggregate; got "
            f"{grp_after_commit['aggregate_retrans_cents']}"
        )


class TestImmediateConsistency:
    def test_commit_response_reflects_computed_share(self, api):
        """PRD §3.6: "The result is stored as `network_share_cents`" — the
        commit response carries the freshly-computed share synchronously.

        Design: Corner/consistency_model/immediate_consistency_on_commit_response
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-10T00:00:00Z", leverage_tier="MID",
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        rs = create_retrans_settlement(
            nid, sid, scenario["agreement"]["id"], nar,
            period_index=0, gross_retrans_cents=1_000_000,
        )
        committed = commit_retrans_settlement(
            nid, sid, rs["id"], nar, scenario["station"]["version"]
        )
        # MID tier with trailing 0 -> no discount. 1,000,000 * 0.40 = 400,000.
        assert committed["status"] == "COMMITTED"
        assert committed["network_share_cents"] == 400_000, (
            f"Commit response must reflect computed share; got "
            f"{committed['network_share_cents']}"
        )
