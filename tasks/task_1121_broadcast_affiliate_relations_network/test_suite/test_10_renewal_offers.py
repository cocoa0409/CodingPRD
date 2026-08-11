"""RenewalOffer negotiation: alternating turns, SoD, OCC, branching.

Covers difficulty renewal_offer_branching_fork, sod_beat_referential_exclusivity;
corner renewal_withdraw_sod_proposer_only, err_stale_agreement_version_occ,
rate_sum_constraint_invalid_enum_term_length,
optimistic_concurrency_version_increments_on_mutation.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_renewal_offer_payload,
    get_success_data,
    setup_basic_scenario,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import create_renewal_offer


def _setup_renewal_eligible_scenario(api, leverage_tier="MAJOR"):
    """ACTIVE agreement whose term_end is within 180 days of the logical
    clock, so the first renewal offer transitions it to RENEWAL_NEGOTIATION
    (PRD §3.2).
    """
    return setup_basic_scenario(
        clock_iso="2026-08-01T00:00:00Z",
        leverage_tier=leverage_tier,
        term_start_utc="2025-01-01T00:00:00Z",
        term_end_utc="2026-12-31T00:00:00Z",
    )


class TestRenewalOfferVersionIncrements:
    def test_offer_creation_increments_agreement_version(self, api):
        """PRD §3.4: "The first offer posted against an `ACTIVE` or
        `EXPIRING` agreement moves the agreement into `RENEWAL_NEGOTIATION`,
        increments its `renewal_round_count`, increments its `version`".

        Design: Corner/cross_cutting_layers/optimistic_concurrency_version_increments_on_mutation
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        ag_v0 = scenario["agreement"]["version"]
        create_renewal_offer(
            nid, sid, scenario["agreement"]["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag_v0,
        )
        ag_after = validate_success(
            api_client.get_agreement(nid, sid, scenario["agreement"]["id"], nar)
        )
        assert ag_after["version"] == ag_v0 + 1, (
            f"Agreement version must bump by exactly 1 on offer creation; "
            f"was {ag_v0}, now {ag_after['version']}"
        )


class TestRenewalOfferSoD:
    def test_proposer_cannot_accept_own_offer(self, api):
        """PRD §3.4: "**Accept** ... is permitted only when the caller's role
        is not the offer's `proposed_by_role` — the proposer cannot accept
        their own offer." Rejection: `ERR_SOD_VIOLATION` (HTTP 403).

        Design: Difficulty/priority_pair_validation_conflict/sod_beat_referential_exclusivity
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        ag_v = scenario["agreement"]["version"]
        offer = create_renewal_offer(
            nid, sid, scenario["agreement"]["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag_v,
        )
        # NetworkAffiliateRelations attempts to accept its own offer.
        resp = api_client.accept_renewal_offer(
            nid, sid, scenario["agreement"]["id"], offer["id"], nar
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_only_proposer_can_withdraw(self, api):
        """PRD §3.4: "**Withdraw** ... is permitted only when the caller's
        role equals `proposed_by_role` — only the proposer may retract their
        own offer."

        Design: Corner/state_machines/renewal_withdraw_sod_proposer_only
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        sgo = scenario["sgo_headers"]
        ag_v = scenario["agreement"]["version"]
        offer = create_renewal_offer(
            nid, sid, scenario["agreement"]["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag_v,
        )
        # StationGroupOwner (counterparty) attempts to withdraw.
        resp = api_client.withdraw_renewal_offer(
            nid, sid, scenario["agreement"]["id"], offer["id"], sgo
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


class TestRenewalOfferSoDSecondWitness:
    def test_proposer_cannot_reject_own_offer(self, api):
        """PRD §3.4: "**Reject** moves the offer from `PROPOSED` to
        `REJECTED`, again requiring that the caller's role differ from
        `proposed_by_role`." Rejection: `ERR_SOD_VIOLATION` (HTTP 403).

        Design: Difficulty/priority_pair_validation_conflict/sod_beat_referential_exclusivity
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        ag_v = scenario["agreement"]["version"]
        offer = create_renewal_offer(
            nid, sid, scenario["agreement"]["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag_v,
        )
        # Same role attempts to reject its own offer.
        resp = api_client.reject_renewal_offer(
            nid, sid, scenario["agreement"]["id"], offer["id"], nar
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


class TestRenewalOfferOCC:
    def test_stale_agreement_version_rejected(self, api):
        """PRD §2.6: "posting a new offer under an agreement requires the
        request body to carry `expected_agreement_version`, matching the
        current `version` of the parent `AffiliationAgreement`. A mismatch is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_agreement_version_occ
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        sgo = scenario["sgo_headers"]
        ag_v = scenario["agreement"]["version"]
        # First offer (NAR) succeeds and bumps agreement version.
        create_renewal_offer(
            nid, sid, scenario["agreement"]["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag_v,
        )
        # Second offer (SGO) reuses the stale ag_v.
        resp = api_client.create_renewal_offer(
            nid, sid, scenario["agreement"]["id"],
            create_renewal_offer_payload(
                proposed_by_role="STATION_GROUP_OWNER",
                proposed_reverse_comp_pct=0.35,
                proposed_retrans_share_pct=0.65,
                proposed_term_months=24,
                expected_agreement_version=ag_v,
            ),
            sgo,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)


class TestRenewalOfferBranching:
    def test_reject_branch_keeps_agreement_in_renewal_negotiation(self, api):
        """PRD §3.4: "**Reject** moves the offer from `PROPOSED` to
        `REJECTED`, again requiring that the caller's role differ from
        `proposed_by_role`." This branch is divergent from ACCEPT — the
        agreement remains in RENEWAL_NEGOTIATION (no cascade to ACTIVE).

        Design: Difficulty/non_linear_state_machine/renewal_offer_branching_fork
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        sgo = scenario["sgo_headers"]
        ag = scenario["agreement"]
        offer = create_renewal_offer(
            nid, sid, ag["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag["version"],
        )
        # SGO rejects (caller role differs from proposer).
        rejected = get_success_data(
            api_client.reject_renewal_offer(nid, sid, ag["id"], offer["id"], sgo)
        )
        assert rejected["status"] == "REJECTED"
        # Agreement remains in RENEWAL_NEGOTIATION (reject branch).
        ag_after = validate_success(api_client.get_agreement(nid, sid, ag["id"], nar))
        assert ag_after["status"] == "RENEWAL_NEGOTIATION", (
            f"Reject branch does not return agreement to ACTIVE; got "
            f"{ag_after['status']!r}"
        )

    def test_accept_supersedes_other_proposed_offer(self, api):
        """PRD §3.4: "Acceptance cascades: the parent agreement's
        `reverse_comp_pct` is overwritten with the offer's
        `proposed_reverse_comp_pct` ...; the agreement itself moves from
        `RENEWAL_NEGOTIATION` back to `ACTIVE`; every other offer on the
        same agreement in `PROPOSED` or `COUNTERED` flips to `SUPERSEDED`".

        Design: Difficulty/non_linear_state_machine/renewal_offer_branching_fork
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        sgo = scenario["sgo_headers"]
        ag = scenario["agreement"]
        # First offer: NAR.
        offer1 = create_renewal_offer(
            nid, sid, ag["id"], nar,
            proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
            proposed_reverse_comp_pct=0.45,
            proposed_retrans_share_pct=0.55,
            proposed_term_months=24,
            expected_agreement_version=ag["version"],
        )
        ag_v1 = validate_success(api_client.get_agreement(nid, sid, ag["id"], nar))["version"]
        # Second offer: SGO (alternating-turn).
        offer2 = create_renewal_offer(
            nid, sid, ag["id"], sgo,
            proposed_by_role="STATION_GROUP_OWNER",
            proposed_reverse_comp_pct=0.35,
            proposed_retrans_share_pct=0.65,
            proposed_term_months=36,
            expected_agreement_version=ag_v1,
        )
        # NAR (counterparty to SGO) accepts offer2.
        accepted = get_success_data(
            api_client.accept_renewal_offer(nid, sid, ag["id"], offer2["id"], nar)
        )
        assert accepted["status"] == "ACCEPTED"
        # Offer1 must now be SUPERSEDED.
        offer1_after = validate_success(
            api_client.get_renewal_offer(nid, sid, ag["id"], offer1["id"], nar)
        )
        assert offer1_after["status"] == "SUPERSEDED", (
            f"Prior PROPOSED offer must flip to SUPERSEDED on acceptance; "
            f"got {offer1_after['status']!r}"
        )
        # Agreement adopts the accepted offer's terms.
        ag_after = validate_success(api_client.get_agreement(nid, sid, ag["id"], nar))
        assert ag_after["status"] == "ACTIVE"
        assert ag_after["reverse_comp_pct"] == pytest.approx(0.35), (
            f"Agreement must adopt offer2's reverse_comp_pct 0.35; got "
            f"{ag_after['reverse_comp_pct']!r}"
        )


class TestRenewalOfferTermLength:
    def test_invalid_term_length_rejected(self, api):
        """PRD §3.4: "a `proposed_term_months` drawn from the closed set
        {12, 24, 36, 48, 60}. Terms outside this set are rejected with
        `ERR_INVALID_TERM_LENGTH` (HTTP 422)."

        Design: Corner/entities/rate_sum_constraint_invalid_enum_term_length
        """
        scenario = _setup_renewal_eligible_scenario(api)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        nar = scenario["nar_headers"]
        ag_v = scenario["agreement"]["version"]
        resp = api_client.create_renewal_offer(
            nid, sid, scenario["agreement"]["id"],
            create_renewal_offer_payload(
                proposed_by_role="NETWORK_AFFILIATE_RELATIONS",
                proposed_reverse_comp_pct=0.45,
                proposed_retrans_share_pct=0.55,
                proposed_term_months=18,  # outside the closed set
                expected_agreement_version=ag_v,
            ),
            nar,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_LENGTH)
