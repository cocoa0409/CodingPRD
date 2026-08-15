"""Contract lifecycle: revision loop, countersign OCC, escalator variants,
installment split, terminal lockdown, version increments."""
import pytest

from test_helpers import (
    ApiErrorId,
    countersign_contract,
    create_active_sponsor,
    create_countersigned_contract,
    create_draft_contract,
    create_venue,
    get_success_data,
    list_contract_invoices,
    make_sponsor_contact_headers,
    propose_contract,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import SALES, activate_contract


def _expected_compound_total(base, pct, first, last):
    total = 0
    for season in range(first, last + 1):
        k = season - first
        total += int(base * ((1 + pct) ** k) + 0.5)
    return total


def _expected_simple_total(base, pct, first, last):
    total = 0
    for season in range(first, last + 1):
        k = season - first
        total += int(base * (1 + pct * k) + 0.5)
    return total


class TestEscalatorDualVariant:
    """Difficulty rule dual_variant_calc, contract-fee domain."""

    def _setup_two_contracts(self, api):
        venue = create_venue()
        s1 = create_active_sponsor(legal_name="FizzCo Beverages LLC")
        s2 = create_active_sponsor(legal_name="SparkWater Inc",
                                   display_name="SparkWater")
        common = dict(term_first_season=2026, term_last_season=2028,
                      base_fee_cents=10_000_000, escalator_pct=0.03)
        c1 = create_countersigned_contract(venue["id"], s1["id"],
                                           title="Naming Rights COMPOUND",
                                           escalator_mode="COMPOUND", **common)
        c2 = create_countersigned_contract(venue["id"], s2["id"],
                                           title="Naming Rights SIMPLE",
                                           escalator_mode="SIMPLE", **common)
        return venue, s1, s2, c1, c2

    def test_compound_vs_simple_scheduled_total(self, api):
        """PRD §3.3: "Under `COMPOUND`, the fee for a season is
        `base_fee_cents` multiplied by one-plus-`escalator_pct` raised to the
        power of the season index, rounded half-up to whole cents. Under
        `SIMPLE`, the fee is `base_fee_cents` multiplied by the quantity one
        plus `escalator_pct` times the season index, rounded half-up to whole
        cents."
        PRD §3.3: "The contract's `scheduled_total_cents` is then the sum of
        the season fees over every season of the term, both ends included, a
        sum of already-rounded whole-cent values."

        Design: Difficulty/dual_variant_calc/escalator_compound_vs_simple_contract_fee
        """
        _v, _s1, _s2, c1, c2 = self._setup_two_contracts(api)

        got_c1 = validate_success(api.get_contract(c1["id"], SALES))
        got_c2 = validate_success(api.get_contract(c2["id"], SALES))
        # COMPOUND: 10,000,000 + 10,300,000 + 10,609,000 = 30,909,000
        assert got_c1["scheduled_total_cents"] == 30_909_000
        # SIMPLE: 10,000,000 + 10,300,000 + 10,600,000 = 30,900,000
        assert got_c2["scheduled_total_cents"] == 30_900_000
        assert got_c1["scheduled_total_cents"] != got_c2["scheduled_total_cents"]

    def test_compound_vs_simple_signing_installment(self, api):
        """PRD §3.3: "The signing installment's `amount_cents` is forty percent
        of the scheduled total, rounded half-up to whole cents; the mid-season
        installment is thirty percent of the scheduled total, rounded half-up;
        the post-season installment is whatever remains — the scheduled total
        minus the first two amounts — so the final installment absorbs the
        rounding remainder."

        Design: Difficulty/dual_variant_calc/escalator_compound_vs_simple_contract_fee
        """
        _v, _s1, _s2, c1, c2 = self._setup_two_contracts(api)

        inv1 = list_contract_invoices(c1["id"])
        inv2 = list_contract_invoices(c2["id"])
        assert inv1[0]["installment_label"] == "SIGNING"
        assert inv2[0]["installment_label"] == "SIGNING"
        # round_half_up(30,909,000 * 0.40) = 12,363,600
        assert inv1[0]["amount_cents"] == 12_363_600
        # round_half_up(30,900,000 * 0.40) = 12,360,000
        assert inv2[0]["amount_cents"] == 12_360_000


class TestInstallmentRemainderAbsorption:
    """Difficulty rule combinatorial_formula, nested-rounding mode."""

    def _setup_odd_total(self, api):
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_countersigned_contract(
            venue["id"], sponsor["id"], title="Odd-Total Naming",
            term_first_season=2026, term_last_season=2026,
            base_fee_cents=9_999_999, escalator_pct=0, escalator_mode="SIMPLE")
        return venue, sponsor, contract

    def test_installment_split_remainder_absorption_amounts(self, api):
        """PRD §3.3: "The signing installment's `amount_cents` is forty percent
        of the scheduled total, rounded half-up to whole cents; the mid-season
        installment is thirty percent of the scheduled total, rounded half-up;
        the post-season installment is whatever remains — the scheduled total
        minus the first two amounts — so the final installment absorbs the
        rounding remainder."

        Design: Difficulty/combinatorial_formula/installment_split_remainder_absorption
        """
        _v, _s, contract = self._setup_odd_total(api)
        invoices = list_contract_invoices(contract["id"])
        assert len(invoices) == 3
        # round_half_up(9,999,999 * 0.40) = 4,000,000
        assert invoices[0]["amount_cents"] == 4_000_000
        # round_half_up(9,999,999 * 0.30) = 3,000,000
        assert invoices[1]["amount_cents"] == 3_000_000
        # remainder: 9,999,999 - 4,000,000 - 3,000,000 = 2,999,999
        assert invoices[2]["amount_cents"] == 2_999_999

    def test_installment_split_remainder_absorption_labels_and_sum(self, api):
        """PRD §3.3: "exactly three `DRAFT` invoices are created — `SIGNING`
        with `installment_seq` 1, `MID_SEASON` with `installment_seq` 2, and
        `POST_SEASON` with `installment_seq` 3."
        PRD §3.3: "Rounding all three lines independently could land a cent
        either side of the total; the pinned order — first line rounded, second
        line rounded, third line as remainder — is the contract."

        Design: Difficulty/combinatorial_formula/installment_split_remainder_absorption
        """
        _v, _s, contract = self._setup_odd_total(api)
        invoices = list_contract_invoices(contract["id"])
        assert [i["installment_label"] for i in invoices] == [
            "SIGNING", "MID_SEASON", "POST_SEASON"]
        assert [i["installment_seq"] for i in invoices] == [1, 2, 3]
        assert sum(i["amount_cents"] for i in invoices) == 9_999_999
        got = validate_success(api.get_contract(contract["id"], SALES))
        assert got["scheduled_total_cents"] == 9_999_999


class TestRevisionCycle:
    """Difficulty rule non_linear_state_machine (contract revision half)."""

    def test_draft_proposed_revision_cycle(self, api):
        """PRD §3.3: "The draft loop is deliberately cyclic. Proposing
        (`PROPOSE`) moves `DRAFT` to `PROPOSED` and again requires an `ACTIVE`
        sponsor (`ERR_SPONSOR_NOT_ACTIVE`); revising (`REVISE`) moves
        `PROPOSED` back to `DRAFT`; the pair may cycle any number of times."

        Design: Difficulty/non_linear_state_machine/contract_revision_cycle_and_parallel_rights_dimension
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        p1 = propose_contract(contract["id"])
        assert p1["contract_status"] == "PROPOSED"
        back = get_success_data(api.transition_contract(
            contract["id"], {"action": "REVISE"}, SALES))
        assert back["contract_status"] == "DRAFT"
        p2 = propose_contract(contract["id"])
        assert p2["contract_status"] == "PROPOSED"
        signed = countersign_contract(contract["id"], sponsor["id"],
                                      p2["version"])
        assert signed["contract_status"] == "COUNTERSIGNED"

    def test_revision_loop_preserves_editability_in_draft(self, api):
        """PRD §3.3: "While the contract is `DRAFT`, the seller may edit its
        commercial terms — `title`, either term boundary, `base_fee_cents`,
        `escalator_pct`, or `escalator_mode` — and every successful edit
        increments the contract's `version`, which is exactly what the
        countersignature guard keys on."

        Design: Difficulty/non_linear_state_machine/contract_revision_cycle_and_parallel_rights_dimension
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028,
                                         base_fee_cents=10_000_000)
        propose_contract(contract["id"])
        get_success_data(api.transition_contract(contract["id"],
                                                 {"action": "REVISE"}, SALES))
        patched = get_success_data(api.patch_contract(
            contract["id"], {"base_fee_cents": 11_000_000}, SALES))
        assert patched["base_fee_cents"] == 11_000_000
        p2 = propose_contract(contract["id"])
        signed = countersign_contract(contract["id"], sponsor["id"],
                                      p2["version"])
        # SIMPLE mode, escalator 0: scheduled total == base fee for 1-season
        # term? term 2026-2028, escalator 0 -> 3 * 11,000,000 = 33,000,000.
        assert signed["scheduled_total_cents"] == 33_000_000


class TestTerminalLockdownAndPatchGate:
    def test_contract_terminal_lockdown_and_patch_gate(self, api):
        """PRD §2.12: "**State-machine legality** — the target entity's own
        lifecycle permits the requested action from its current state,
        including terminal-state lockdown and compound state preconditions
        expressed as `ERR_INVALID_STATE`."
        PRD §3.3: "While the contract is `DRAFT`, the seller may edit its
        commercial terms"

        Design: Corner/state_machines/contract_terminal_lockdown_and_patch_gate
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        proposed = propose_contract(contract["id"])

        # PATCH outside DRAFT (contract is PROPOSED)
        resp_patch = api.patch_contract(contract["id"],
                                        {"base_fee_cents": 11_000_000}, SALES)
        validate_error(resp_patch, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)

        signed = countersign_contract(contract["id"], sponsor["id"],
                                      proposed["version"])
        activate_contract(signed["id"])
        get_success_data(api.transition_contract(signed["id"],
                                                 {"action": "TERMINATE"}, SALES))

        # PROPOSE on a TERMINATED contract
        resp_term = api.transition_contract(signed["id"], {"action": "PROPOSE"},
                                            SALES)
        validate_error(resp_term, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)


class TestCountersignOwnershipAndOcc:
    def test_countersign_by_other_sponsor_forbidden(self, api):
        """PRD §2.1: "Countersigning a contract requires the contract's
        `sponsor_id` to equal `X-User-ID`"
        PRD §3.3: "the caller's `X-User-ID` must equal the contract's
        `sponsor_id` (`ERR_FORBIDDEN`)"

        Design: Corner/validations/countersign_by_other_sponsor_forbidden
        """
        venue = create_venue()
        s1 = create_active_sponsor(legal_name="FizzCo Beverages LLC")
        s2 = create_active_sponsor(legal_name="SparkWater Inc",
                                   display_name="SparkWater")
        contract = create_draft_contract(venue["id"], s1["id"],
                                         term_last_season=2028)
        proposed = propose_contract(contract["id"])

        resp = api.countersign_contract(
            contract["id"],
            {"expected_contract_version": proposed["version"]},
            make_sponsor_contact_headers(s2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        got = validate_success(api.get_contract(contract["id"], SALES))
        assert got["contract_status"] == "PROPOSED"

    def test_countersign_stale_version_returns_412(self, api):
        """PRD §2.11: "A request to countersign a contract (`POST
        /contracts/{contract_id}/countersign`) must carry
        `expected_contract_version`, holding the contract `version` the sponsor
        last observed. If the contract's current `version` differs — for
        example because a sales edit to the commercial terms advanced it after
        the proposal was read — the countersign is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412), since the sponsor would
        otherwise be signing terms they never saw."

        Design: Corner/validations/countersign_stale_version_returns_412
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028,
                                         escalator_pct=0.03,
                                         escalator_mode="COMPOUND")
        proposed1 = propose_contract(contract["id"])
        stale_version = proposed1["version"]

        # Advance the version: REVISE -> PATCH -> PROPOSE
        get_success_data(api.transition_contract(contract["id"],
                                                 {"action": "REVISE"}, SALES))
        get_success_data(api.patch_contract(contract["id"],
                                            {"base_fee_cents": 11_000_000},
                                            SALES))
        proposed2 = propose_contract(contract["id"])
        fresh_version = proposed2["version"]
        assert fresh_version > stale_version

        resp = api.countersign_contract(
            contract["id"], {"expected_contract_version": stale_version},
            make_sponsor_contact_headers(sponsor["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION,
                       expected_status=412)

        ok = validate_success(api.countersign_contract(
            contract["id"], {"expected_contract_version": fresh_version},
            make_sponsor_contact_headers(sponsor["id"])))
        assert ok["contract_status"] == "COUNTERSIGNED"
        # COMPOUND 3% over 2026-2028 at base 11,000,000:
        # 11,000,000 + 11,330,000 + 11,669,900 = 33,999,900
        assert ok["scheduled_total_cents"] == 33_999_900


class TestVersionIncrements:
    def test_occ_version_increments_on_each_write(self, api):
        """PRD §2.10: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource and underpins the
        optimistic concurrency guards of §2.11."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_each_write
        """
        venue = create_venue()
        sponsor = create_active_sponsor()

        created = validate_success(api.create_contract(
            {
                "venue_id": venue["id"],
                "sponsor_id": sponsor["id"],
                "title": "Naming",
                "term_first_season": 2026,
                "term_last_season": 2028,
                "base_fee_cents": 10_000_000,
                "escalator_pct": 0.03,
                "escalator_mode": "COMPOUND",
            }, SALES), expected_status=201)
        assert created["version"] == 1
        cid = created["id"]

        v2 = validate_success(api.transition_contract(
            cid, {"action": "PROPOSE"}, SALES))["version"]
        v3 = validate_success(api.transition_contract(
            cid, {"action": "REVISE"}, SALES))["version"]
        v4 = validate_success(api.patch_contract(
            cid, {"title": "Naming v2"}, SALES))["version"]
        v5 = validate_success(api.transition_contract(
            cid, {"action": "PROPOSE"}, SALES))["version"]
        v6 = validate_success(api.countersign_contract(
            cid, {"expected_contract_version": v5},
            make_sponsor_contact_headers(sponsor["id"])))["version"]

        assert (v2, v3, v4, v5, v6) == (2, 3, 4, 5, 6), (
            f"expected +1 per mutation, got {(v2, v3, v4, v5, v6)}")
