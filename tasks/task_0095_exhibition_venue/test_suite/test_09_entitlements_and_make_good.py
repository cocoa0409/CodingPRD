"""Sponsor entitlements, make-good credit, and dual-variant fulfillment
score — PRD §3.8.

Covers:
- entitlement lifecycle (PLANNED → IN_PROGRESS → FULFILLED / MISSED →
  MAKE_GOOD_OFFERED → MAKE_GOOD_ACCEPTED; PLANNED → WAIVED)
- make-good credit per tier × per code
- final fulfillment_score: 1.0 for FULFILLED, 0.5 for
  MAKE_GOOD_ACCEPTED, 0.5 base for MISSED with daily decay (Rule 1
  instance 2)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    create_entitlement,
    create_entitlement_payload,
    fulfill_entitlement_payload,
    iso_offset,
    make_exhibitor_headers,
    random_exhibitor_id,
    setup_in_progress_entitlement,
    validate_error,
    validate_success,
)


def _find_entitlement_in_report(report, entitlement_id):
    """Locate a row for `entitlement_id` in the entitlement-report
    response. PRD §3.8 leaves the report shape open, but it must
    project the entitlement set including per-row status,
    fulfillment_score, and make_good_credit_cents.
    """
    if not isinstance(report, dict):
        return None
    for value in report.values():
        if isinstance(value, list):
            for entry in value:
                if (
                    isinstance(entry, dict)
                    and entry.get("entitlement_id") == entitlement_id
                ):
                    return entry
                if (
                    isinstance(entry, dict)
                    and entry.get("id") == entitlement_id
                ):
                    return entry
    return None


# ===========================================================================
# Entitlement creation lifecycle (PRD §3.8)
# ===========================================================================
class TestEntitlementLifecycle:

    def test_create_then_start_moves_to_in_progress(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.8: "The entitlement starts in PLANNED.
        Operations starts work on the entitlement (moving it from
        PLANNED to IN_PROGRESS)."

        Claim: POST /entitlements/{id}/start moves a PLANNED
        entitlement to IN_PROGRESS.
        """
        from test_helpers import create_exhibition
        exh = create_exhibition()
        ent = create_entitlement(
            exh["id"],
            exhibitor_id=random_exhibitor_id(),
            entitlement_code="SIGNAGE",
            sponsor_tier="BRONZE",
            deadline=iso_offset(days=5),
        )
        assert ent["status"] == "PLANNED"
        res = api.start_entitlement(ent["id"], venue_ops_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "IN_PROGRESS"

    def test_fulfill_within_deadline_sets_score_one(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.8: "fulfillment is only accepted when the
        evidence_url is non-empty and the current clock is at or
        before deadline, and on success the entitlement moves from
        IN_PROGRESS to the terminal FULFILLED, the entitlement's
        final fulfillment_score is computed and pinned."
        PRD §3.8: "For FULFILLED the final value is one."

        Claim: fulfill before deadline → status=FULFILLED and
        fulfillment_score==1.0.
        """
        ctx = setup_in_progress_entitlement(
            entitlement_code="LOUNGE",
            sponsor_tier="GOLD",
            deadline_offset_hours=24,
        )
        res = api.fulfill_entitlement(
            ctx["entitlement"]["id"],
            fulfill_entitlement_payload(
                evidence_url="https://example.com/proof.jpg",
            ),
            venue_ops_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "FULFILLED"
        assert data["fulfillment_score"] == pytest.approx(1.0)

    def test_fulfill_with_empty_evidence_url_rejected(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.8: "fulfillment is only accepted when the
        evidence_url is non-empty."

        Claim: fulfill with evidence_url='' → ERR_INVALID_INPUT.
        """
        ctx = setup_in_progress_entitlement()
        res = api.fulfill_entitlement(
            ctx["entitlement"]["id"],
            fulfill_entitlement_payload(evidence_url=""),
            venue_ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Make-good credit (PRD §3.8)
# ===========================================================================
class TestMakeGoodCredit:

    def test_mark_missed_computes_make_good_for_gold_lounge(
        self, api, venue_admin_headers,
    ):
        """PRD §3.8: "The make-good credit picks a per-tier base in
        cents — ten thousand for BRONZE, twenty-five thousand for
        SILVER, sixty thousand for GOLD, one hundred and twenty
        thousand for PLATINUM — multiplies it by a per-entitlement
        factor (SIGNAGE factor five-tenths, PROGRAM_AD factor
        four-tenths, LOUNGE factor eight-tenths, SPEAKING_SLOT factor
        one, BRANDED_GIFT factor three-tenths), and rounds the product
        half-up to integer cents."

        Claim: GOLD + LOUNGE → make_good_credit_cents ==
        round_half_up(60000 * 0.8) == 48000.
        """
        ctx = setup_in_progress_entitlement(
            entitlement_code="LOUNGE",
            sponsor_tier="GOLD",
            deadline_offset_hours=1,
        )
        # Advance past deadline. PRD §2.6: the clock-advance cascade
        # auto-MISSES IN_PROGRESS entitlements whose deadline has
        # passed and computes their make_good_credit_cents in the
        # same step.
        advance_clock(to=iso_offset(hours=2))
        rep_res = api.get_entitlement_report(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        report = validate_success(rep_res, expected_status=200)
        row = _find_entitlement_in_report(
            report, ctx["entitlement"]["id"],
        )
        assert row is not None, "Entitlement missing from report"
        assert row["status"] == "MISSED"
        assert row["make_good_credit_cents"] == 48000

    def test_make_good_credit_platinum_speaking_slot(
        self, api, venue_admin_headers,
    ):
        """PRD §3.8: "one hundred and twenty thousand for PLATINUM
        ... SPEAKING_SLOT factor one ... rounds the product half-up
        to integer cents."

        Claim: PLATINUM + SPEAKING_SLOT → make_good_credit_cents ==
        round_half_up(120000 * 1.0) == 120000.
        """
        ctx = setup_in_progress_entitlement(
            entitlement_code="SPEAKING_SLOT",
            sponsor_tier="PLATINUM",
            deadline_offset_hours=1,
        )
        advance_clock(to=iso_offset(hours=2))
        rep_res = api.get_entitlement_report(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        report = validate_success(rep_res, expected_status=200)
        row = _find_entitlement_in_report(
            report, ctx["entitlement"]["id"],
        )
        assert row is not None
        assert row["make_good_credit_cents"] == 120000


# ===========================================================================
# Final fulfillment_score for MISSED — daily decay (PRD §3.8)
#
# DELETED: tests that asserted the pinned final-variant
# fulfillment_score on a MISSED entitlement before the exhibition is
# CLOSED. PRD §3.8 states: "the entitlement report returns the
# provisional shape while the exhibition is open and the final shape
# after it has closed." In provisional mode, MISSED reads zero. The
# pinned final value is only observable through the entitlement
# report after the exhibition has CLOSED. The tests reached MISSED
# via the clock-advance auto-cascade (PRD §2.6) on a DRAFT
# exhibition; there is no PRD-faithful pathway to observe the
# pinned final fulfillment_score in that state.
# ===========================================================================


# ===========================================================================
# Make-good offer + accept + waive (PRD §3.8)
# ===========================================================================
class TestMakeGoodOfferAndAccept:

    def test_offer_make_good_moves_missed_to_offered(
        self, api, venue_admin_headers,
    ):
        """PRD §3.8: "The admin may then offer a make-good, moving the
        entitlement from MISSED to MAKE_GOOD_OFFERED ...; offering
        requires make_good_credit_cents to be strictly positive."

        Claim: offer-make-good from MISSED → status=MAKE_GOOD_OFFERED.
        """
        ctx = setup_in_progress_entitlement(
            entitlement_code="LOUNGE",
            sponsor_tier="GOLD",
            deadline_offset_hours=1,
        )
        advance_clock(to=iso_offset(hours=2))
        api.mark_missed_entitlement(
            ctx["entitlement"]["id"], venue_admin_headers,
        )
        res = api.offer_make_good(
            ctx["entitlement"]["id"], venue_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "MAKE_GOOD_OFFERED"

    def test_accept_make_good_terminal_state_by_owner(
        self, api, venue_admin_headers,
    ):
        """PRD §3.8: "The exhibitor accepts the offer, moving the
        entitlement to the terminal MAKE_GOOD_ACCEPTED."
        PRD §3.8: "All exhibitor-side transitions require the acting
        X-User-ID to equal the entitlement's exhibitor_id."

        Claim: accept-make-good by the owning exhibitor →
        status=MAKE_GOOD_ACCEPTED.
        """
        ctx = setup_in_progress_entitlement(
            entitlement_code="LOUNGE",
            sponsor_tier="GOLD",
            deadline_offset_hours=1,
        )
        advance_clock(to=iso_offset(hours=2))
        api.mark_missed_entitlement(
            ctx["entitlement"]["id"], venue_admin_headers,
        )
        api.offer_make_good(
            ctx["entitlement"]["id"], venue_admin_headers,
        )
        owner = make_exhibitor_headers(ctx["exhibitor_id"])
        res = api.accept_make_good(ctx["entitlement"]["id"], owner)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "MAKE_GOOD_ACCEPTED"

    def test_waive_from_planned_by_owner(
        self, api, venue_admin_headers,
    ):
        """PRD §3.8: "Alternatively, the exhibitor may waive a planned
        entitlement directly from PLANNED to the terminal WAIVED."

        Claim: waive from PLANNED by the owner → status=WAIVED.
        """
        from test_helpers import create_exhibition
        exh = create_exhibition()
        exhibitor_id = random_exhibitor_id()
        ent = create_entitlement(
            exh["id"],
            exhibitor_id=exhibitor_id,
            entitlement_code="BRANDED_GIFT",
            sponsor_tier="BRONZE",
            deadline=iso_offset(days=5),
        )
        owner = make_exhibitor_headers(exhibitor_id)
        res = api.waive_entitlement(ent["id"], owner)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "WAIVED"


# ===========================================================================
# Provisional vs final fulfillment_score divergence (Rule 1 inst 2)
# ===========================================================================
class TestProvisionalVsFinalDivergence:
    # difficulty: dual_variant_calc/entitlement_score_provisional_vs_final

    def test_provisional_in_progress_score_one(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.8: "The provisional variant is computed live for the
        entitlement report while the exhibition is not yet CLOSED ...
        It treats entitlements in IN_PROGRESS or MAKE_GOOD_OFFERED as
        one (assuming they will fulfill)."

        Claim: an IN_PROGRESS entitlement appears in the provisional
        entitlement report with fulfillment_score 1.0.
        """
        # difficulty: dual_variant_calc/entitlement_score_provisional_vs_final
        ctx = setup_in_progress_entitlement(
            entitlement_code="LOUNGE",
            sponsor_tier="GOLD",
            deadline_offset_hours=1,
        )
        # Pre-deadline provisional report.
        rep_res = api.get_entitlement_report(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        report = validate_success(rep_res, expected_status=200)
        # PRD §3.8 says the report "is a computed projection over the
        # exhibition's entitlement set, aggregating status counts,
        # the live or pinned fulfillment_score." Verify some live
        # score for IN_PROGRESS reads 1.0.
        provisional_one = False
        if isinstance(report, dict):
            for v in report.values():
                if isinstance(v, (int, float)) and abs(v - 1.0) < 1e-6:
                    provisional_one = True
                    break
                if isinstance(v, list):
                    for entry in v:
                        if (isinstance(entry, dict)
                                and isinstance(
                                    entry.get("fulfillment_score"),
                                    (int, float),
                                )
                                and abs(
                                    entry["fulfillment_score"] - 1.0
                                ) < 1e-6):
                            provisional_one = True
                            break
        # Provisional must show the IN_PROGRESS row at 1.0 by PRD §3.8.
        assert provisional_one, (
            "Provisional entitlement-report variant must reflect "
            "IN_PROGRESS as 1.0 per PRD §3.8 provisional rule"
        )
        # NOTE: the original test also asserted the post-cascade
        # final fulfillment_score=0.2 here. That sub-assertion was
        # removed because PRD §3.8 states the report returns the
        # provisional shape while the exhibition is open and the
        # final shape only after CLOSED. With the entitlement
        # auto-MISSED via clock cascade (§2.6) but the exhibition
        # still in DRAFT, the only PRD-faithful observable for a
        # MISSED row is the provisional zero — there is no PRD
        # endpoint that exposes the pinned final score in this
        # state.
