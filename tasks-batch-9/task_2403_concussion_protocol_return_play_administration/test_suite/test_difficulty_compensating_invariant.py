"""
Two conserved quantities and the compensating writes that keep them true.

Money: the club's outstanding ledger must always equal the sum over its counted
audits, so vacating one audit must remove exactly that audit's line.  Counts: the
roster slot pool must always sum to its declared total, so a released exemption
must return exactly one slot.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_club_posture,
    assert_exemption_slots,
    assert_fine_ledger_reconciles,
    assert_instant,
)
from test_helpers.test_users import ADMIN, AUDITOR_A, AUDITOR_B


def _setup_two_priced_audits(api):
    """
    One club carrying two priced audits: 15000000 at TIER_0 and 2250000 at the
    TIER_1 the first audit put the club on.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    audit_a = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    priced_a = fx.issue_findings(
        api, audit_a["id"], ["MISSED_MANDATORY_REMOVAL"], 0, issuer_headers=AUDITOR_B
    )
    audit_b = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    priced_b = fx.issue_findings(
        api, audit_b["id"], ["LATE_INJURY_REPORT"], 0, issuer_headers=AUDITOR_B
    )

    assert priced_a["assessed_fine_cents"] == 15000000
    # Priced at the TIER_1 the club held with this audit excluded: 1500000 x 1.50.
    assert priced_b["escalation_tier_at_issuance"] == "TIER_1"
    assert priced_b["assessed_fine_cents"] == 2250000

    return {"club_id": club["id"], "audit_a_id": audit_a["id"], "audit_b_id": audit_b["id"]}


def _club_audits(api, club_id):
    audits, _ = validate_paginated(api.list_protocol_audits(ADMIN, club_id=club_id))
    return audits


# ─── Money: the ledger is vacated by exactly one line ────────────────────────

def test_dismissing_one_audit_removes_only_its_own_line_from_the_ledger(api):
    """
    The dismissal takes the ledger back to the figure it held before that audit
    was priced — neither to zero nor leaving the vacated line behind.

    PRD §3.10: "Because the audit now leaves both included sets,
    `compliance_score` and `outstanding_fine_cents` return to the values they held
    before the findings were issued, `escalation_tier` and the club's `status` are
    re-derived from the restored score, and any case that the sanction had frozen is
    restored to its recorded `frozen_from_status`."

    Design: Difficulty/compensating_invariant/dismissed_audit_vacates_club_fine_ledger_without_drift
    """
    ctx = _setup_two_priced_audits(api)

    # 100 - 18 - 6 = 76; 15000000 + 2250000 = 17250000.
    before = fx.read_club(api, ctx["club_id"])
    assert_club_posture(
        before,
        compliance_score=76,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=17250000,
    )
    assert before["open_violation_count"] == 2
    assert_fine_ledger_reconciles(before, _club_audits(api, ctx["club_id"]))

    dismissed = fx.close_audit(
        api,
        ctx["audit_b_id"],
        disposition="DISMISSED",
        closing_note="report was filed on time, portal timestamp corrected",
    )
    assert dismissed["status"] == "CLOSED_DISMISSED"
    assert dismissed["disposition"] == "DISMISSED"
    assert dismissed["assessed_fine_cents"] == 0

    after = fx.read_club(api, ctx["club_id"])
    assert_club_posture(
        after,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
    )
    assert after["open_violation_count"] == 1
    assert_fine_ledger_reconciles(after, _club_audits(api, ctx["club_id"]))


def test_upholding_the_other_audit_keeps_its_line_and_only_moves_the_adjudicated_score(api):
    """
    Closing the surviving audit as upheld leaves the ledger exactly where the
    dismissal left it, while the adjudicated score finally absorbs the weights.

    PRD §3.10: "Because `CLOSED_UPHELD` sits inside both included sets,
    `compliance_score` and `outstanding_fine_cents` do not move; what changes is that
    `adjudicated_compliance_score` now drops to absorb the audit's weights and
    `open_violation_count` falls by 1."

    Design: Difficulty/compensating_invariant/dismissed_audit_vacates_club_fine_ledger_without_drift
    """
    ctx = _setup_two_priced_audits(api)
    fx.close_audit(
        api,
        ctx["audit_b_id"],
        disposition="DISMISSED",
        closing_note="report was filed on time, portal timestamp corrected",
    )

    upheld = fx.close_audit(api, ctx["audit_a_id"], disposition="UPHELD")
    assert upheld["status"] == "CLOSED_UPHELD"
    assert upheld["assessed_fine_cents"] == 15000000

    club = fx.read_club(api, ctx["club_id"])
    assert_club_posture(
        club,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
    )
    assert club["adjudicated_compliance_score"] == 82
    assert club["open_violation_count"] == 0
    assert_fine_ledger_reconciles(club, _club_audits(api, ctx["club_id"]))


# ─── Counts: the slot pool is conserved across grant and release ─────────────

def test_the_slot_pool_sums_to_its_total_across_the_grant_and_the_release(api):
    """
    Granting the exemption moves one slot from available to used and returning the
    player to contact moves it back, with the pool summing to its total at every
    observation.

    PRD §2.9: "The two counters are conserved: at every observable instant they sum
    to `exemption_slots_total`, and the used count never leaves the range from 0 to
    the total inclusive."

    Design: Difficulty/compensating_invariant/exemption_release_conserves_club_slot_pool
    """
    ctx = fx.setup_case_with_approved_clearance(api)
    assert_exemption_slots(fx.read_club(api, ctx["club_h_id"]), used=0, available=3, total=3)

    validate_success(api.grant_roster_exemption(ctx["case_id"], ctx["club_h_headers"]))
    assert fx.read_case(api, ctx["case_id"])["roster_exemption_status"] == "GRANTED"
    assert_exemption_slots(fx.read_club(api, ctx["club_h_id"]), used=1, available=2, total=3)

    validate_success(
        api.return_to_contact(
            ctx["case_id"],
            f.return_to_contact_payload("full clearance, unrestricted contact"),
            ctx["doc_h_headers"],
        )
    )

    assert_exemption_slots(fx.read_club(api, ctx["club_h_id"]), used=0, available=3, total=3)


def test_returning_to_contact_releases_the_exemption_as_a_compensating_write(api):
    """
    The release is a consequence of the clearance itself: the case reaches contact,
    the exemption moves to released and the player becomes available again.

    PRD §3.7: "Where the case held a roster exemption, that exemption moves `GRANTED
    → RELEASED` as a compensating release: the club's `exemption_slots_used`
    decreases by 1 and `exemption_slots_available` increases by 1."

    Design: Difficulty/compensating_invariant/exemption_release_conserves_club_slot_pool
    """
    ctx = fx.setup_case_with_approved_clearance(api)
    validate_success(api.grant_roster_exemption(ctx["case_id"], ctx["club_h_headers"]))

    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "APPROVED"
    assert_instant(clearance["expires_at"], "2026-10-04T12:00:00.000Z")

    validate_success(
        api.return_to_contact(
            ctx["case_id"],
            f.return_to_contact_payload("full clearance, unrestricted contact"),
            ctx["doc_h_headers"],
        )
    )

    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "CLEARED_FOR_CONTACT"
    assert case["roster_exemption_status"] == "RELEASED"
    assert_instant(case["cleared_for_contact_at"], "2026-09-28T12:00:00.000Z")
    assert case["heightened_review_required"] is False

    assert fx.read_player(api, ctx["player_id"])["availability_status"] == "AVAILABLE"
