"""Enforcement: LPR outcomes, citation fine escalation, the appeal fork-join, the
appeal→citation→balance cascade, citation-pay OCC, and balance consistency.

PRD §3.8 governs LPR; §3.9 citations, escalation, and appeals.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_garage_with_zone,
    setup_issued_citation,
    setup_submitted_appeal,
    create_motorist,
    request_permit,
    activate_permit,
    create_plate_read,
    create_zone,
    issue_citation,
    issue_n_citations_same_plate,
    submit_appeal,
    decide_appeal,
    get_citation,
    get_motorist,
    set_clock,
    make_motorist_headers,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ---------------------------------------------------------------------------
# Citation fine escalation
# ---------------------------------------------------------------------------
def test_citation_fine_first_offense_vs_repeat_offender(api):
    """PRD §3.9: "The escalation multiplier tiers on that prior count: zero priors
    apply a multiplier of 1.00, exactly one prior applies 1.50, exactly two priors
    apply 2.00, and three or more priors apply 3.00".
    PRD §3.9: "The `amount_due_cents` is the `base_fine_cents` multiplied by the
    applicable multiplier, rounded to the nearest whole cent using round-half-up."

    First citation (0 priors) base 5000 → 5000; second (1 prior) → 7500.

    Design: Difficulty/dual_variant_calc/citation_fine_first_offense_vs_repeat_offender
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    r1 = create_plate_read(garage["id"], "DUP111", zone["id"], "2026-06-01T08:00:00Z")
    c1 = issue_citation(garage["id"], "DUP111", r1["id"], base_fine_cents=5000)
    assert c1["amount_due_cents"] == 5000
    assert c1["prior_citation_count"] == 0

    r2 = create_plate_read(garage["id"], "DUP111", zone["id"], "2026-06-01T09:00:00Z")
    c2 = issue_citation(garage["id"], "DUP111", r2["id"], base_fine_cents=5000)
    assert c2["amount_due_cents"] == 7500
    assert c2["prior_citation_count"] == 1


def test_citation_fine_ceiling_tier_at_three_priors(api):
    """PRD §3.9: "three or more priors apply 3.00, with the ceiling locked at 3.00
    from the third prior onward."
    PRD §3.9: "At issue time the server counts the prior citations for the same
    plate whose `status` is `ISSUED` or `UPHELD`".

    With exactly 3 prior ISSUED citations, the 4th locks at 3.00x: 5000 → 15000.

    Design: Corner/calculations/citation_fine_ceiling_tier_at_three_priors
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    issue_n_citations_same_plate(garage["id"], zone["id"], "CEI111", 3, base_fine_cents=5000)
    r4 = create_plate_read(garage["id"], "CEI111", zone["id"], "2026-06-01T11:30:00Z")
    c4 = issue_citation(garage["id"], "CEI111", r4["id"], base_fine_cents=5000)
    assert c4["prior_citation_count"] == 3
    assert c4["amount_due_cents"] == 15000


# ---------------------------------------------------------------------------
# LPR enforcement outcomes
# ---------------------------------------------------------------------------
def test_lpr_wrong_zone_violation_points_at_out_of_zone_permit(api):
    """PRD §3.8: "If no in-zone permit matches, the system looks for an `ACTIVE`
    permit bound to the plate in a different zone of the same garage; if one exists,
    the outcome is `VIOLATION_WRONG_ZONE` with that out-of-zone permit's id."

    Design: Corner/calculations/lpr_wrong_zone_violation_outcome
    """
    set_clock("2026-06-01T10:00:00Z")
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5,
                                      zone_overrides={"code": "Z1"})
    garage, zone1 = facility["garage"], facility["zone"]
    zone2 = create_zone(garage["id"], facility["rate_plan"]["id"], code="Z2",
                        zone_type="MIXED", permit_capacity=5)
    motorist = create_motorist("wrz@x.com", default_plate="WRZ111")
    permit = request_permit(zone1["id"], motorist["id"], "WRZ111")
    activate_permit(permit["id"], zone1["version"])

    read = create_plate_read(garage["id"], "WRZ111", zone2["id"], "2026-06-01T10:30:00Z")
    assert read["enforcement_outcome"] == "VIOLATION_WRONG_ZONE"
    assert read["matched_permit_id"] == permit["id"]


def test_lpr_compliant_via_open_session(api):
    """PRD §3.8: "First, if there is an `OPEN` access session in the read's garage
    for the same plate, the outcome is `COMPLIANT` with a null `matched_permit_id` —
    a transient parker mid-stay is compliant even without a permit."

    Design: Corner/calculations/lpr_compliant_via_open_session
    """
    from test_helpers import setup_transient_facility, open_session
    set_clock("2026-06-01T10:00:00Z")
    facility = setup_transient_facility(num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                        monthly_permit_cents=9000, grace_minutes=15)
    garage, zone = facility["garage"], facility["zone"]
    open_session(garage["id"], "CMP222", "2026-06-01T10:00:00Z")
    read = create_plate_read(garage["id"], "CMP222", zone["id"], "2026-06-01T10:30:00Z")
    assert read["enforcement_outcome"] == "COMPLIANT"
    assert read["matched_permit_id"] is None


# ---------------------------------------------------------------------------
# Appeal fork-join and cascades
# ---------------------------------------------------------------------------
def test_appeal_fork_join_uphold_dismisses_vs_dismiss_upholds(api):
    """PRD §3.9: "When the decision upholds the appeal, the appeal moves from
    `SUBMITTED` to `UPHELD`, and as a cascade the linked citation transitions from
    `ISSUED` to `DISMISSED`; because a dismissed citation no longer counts, the
    motorist's `outstanding_balance_cents` is recomputed downward".
    PRD §3.9: "When the decision dismisses the appeal, the appeal moves from
    `SUBMITTED` to `DISMISSED`, and the linked citation transitions from `ISSUED` to
    `UPHELD`; the citation still stands, so the motorist's balance is unchanged."

    C1 (5000) appeal UPHELD → DISMISSED; C2 (7500) appeal DISMISSED → UPHELD;
    balance = 7500.

    Design: Difficulty/non_linear_state_machine/citation_fork_join_via_appeal_branches
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    motorist = create_motorist("frk@x.com", default_plate="FRK111")
    r1 = create_plate_read(garage["id"], "FRK111", zone["id"], "2026-06-01T08:00:00Z")
    c1 = issue_citation(garage["id"], "FRK111", r1["id"], base_fine_cents=5000)
    r2 = create_plate_read(garage["id"], "FRK111", zone["id"], "2026-06-01T09:00:00Z")
    c2 = issue_citation(garage["id"], "FRK111", r2["id"], base_fine_cents=5000)
    assert c1["amount_due_cents"] == 5000 and c2["amount_due_cents"] == 7500

    a1 = submit_appeal(c1["id"], motorist["id"], reason="not me")
    a2 = submit_appeal(c2["id"], motorist["id"], reason="broken sign")
    decide_appeal(a1["id"], "UPHELD")
    decide_appeal(a2["id"], "DISMISSED")

    assert get_citation(c1["id"])["status"] == "DISMISSED"
    assert get_citation(c2["id"])["status"] == "UPHELD"
    assert get_motorist(motorist["id"])["outstanding_balance_cents"] == 7500


def test_appeal_uphold_cascades_citation_dismissed_then_balance_down(api):
    """PRD §3.9: "the linked citation transitions from `ISSUED` to `DISMISSED`;
    because a dismissed citation no longer counts, the motorist's
    `outstanding_balance_cents` is recomputed downward, dropping that citation's
    `amount_due_cents` from the sum."

    One ISSUED citation (5000, balance 5000); appeal UPHELD → citation DISMISSED →
    balance 0.

    Design: Difficulty/transitive_cascade/appeal_uphold_cascades_citation_then_balance_depth2
    """
    ctx = setup_submitted_appeal(plate="APL111", base_fine_cents=5000, email="apl@x.com")
    motorist, citation, appeal = ctx["motorist"], ctx["citation"], ctx["appeal"]
    assert get_motorist(motorist["id"])["outstanding_balance_cents"] == 5000

    decided = decide_appeal(appeal["id"], "UPHELD")
    assert decided["status"] == "UPHELD"
    assert get_citation(citation["id"])["status"] == "DISMISSED"
    assert get_motorist(motorist["id"])["outstanding_balance_cents"] == 0


def test_appeal_decide_on_paid_citation_returns_invalid_state(api):
    """PRD §3.9: "Deciding requires the appeal to be `SUBMITTED` and its linked
    citation to still be `ISSUED`."

    Appeal submitted while citation ISSUED, then citation PAID; deciding the appeal
    is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/appeal_decide_depends_on_citation_state_pair
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    motorist = create_motorist("ces@x.com", default_plate="CES111")
    r = create_plate_read(garage["id"], "CES111", zone["id"], "2026-06-01T08:00:00Z")
    citation = issue_citation(garage["id"], "CES111", r["id"], base_fine_cents=5000)
    appeal = submit_appeal(citation["id"], motorist["id"], reason="later")
    # Pay the citation (ISSUED -> PAID) before the appeal is decided.
    paid = validate_success(api.pay_citation(
        citation["id"], {"expected_citation_version": citation["version"]},
        make_motorist_headers(motorist["id"]),
    ))
    assert paid["status"] == "PAID"

    resp = api.decide_appeal(appeal["id"], {"decision": "UPHELD"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_citation(citation["id"])["status"] == "PAID"


# ---------------------------------------------------------------------------
# Citation pay OCC + balance consistency
# ---------------------------------------------------------------------------
def test_pay_citation_stale_version_returns_412(api):
    """PRD §2.8: "Paying a citation requires `expected_citation_version` holding the
    client's last observed `version` of the citation being paid. If it does not
    equal the citation's current `version`, the payment is rejected with
    `ERR_STALE_ZONE_VERSION` (HTTP 412)."

    Citation version captured, then a dismissed appeal flips it ISSUED→UPHELD
    (bumping version); paying with the old version → 412.

    Design: Corner/cross_cutting_complexity_layers/citation_pay_stale_version_returns_412
    """
    ctx = setup_submitted_appeal(plate="STC111", base_fine_cents=5000, email="stc@x.com")
    citation, appeal, motorist = ctx["citation"], ctx["appeal"], ctx["motorist"]
    stale_v = citation["version"]
    decide_appeal(appeal["id"], "DISMISSED")  # ISSUED -> UPHELD, bumps citation version
    resp = api.pay_citation(citation["id"], {"expected_citation_version": stale_v},
                            make_motorist_headers(motorist["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_ZONE_VERSION.value)
    assert get_citation(citation["id"])["status"] == "UPHELD"


def test_issued_citation_balance_visible_immediately(api):
    """PRD §3.9: "Issuing a citation recomputes the cited motorist's
    `outstanding_balance_cents`, since the new `ISSUED` citation now counts toward
    it."
    PRD §2.7: "A motorist's `outstanding_balance_cents` is the sum of
    `amount_due_cents` across that motorist's citations whose `status` is `ISSUED` or
    `UPHELD`."

    Design: Corner/consistency_model/derived_balance_visible_immediately_after_citation
    """
    ctx = setup_issued_citation(plate="IMB111", base_fine_cents=5000, email="imb@x.com")
    assert get_motorist(ctx["motorist"]["id"])["outstanding_balance_cents"] == 5000


def test_appeal_uphold_balance_drops_by_citation_amount(api):
    """PRD §3.9: "the linked citation transitions from `ISSUED` to `DISMISSED`;
    because a dismissed citation no longer counts, the motorist's
    `outstanding_balance_cents` is recomputed downward, dropping that citation's
    `amount_due_cents` from the sum."

    Second translation of the depth-2 cascade with a non-default fine (8000): the
    dismissal drops exactly amount_due_cents (8000) from the balance.

    Design: Difficulty/transitive_cascade/appeal_uphold_cascades_citation_then_balance_depth2
    """
    ctx = setup_submitted_appeal(plate="APD111", base_fine_cents=8000, email="apd@x.com")
    motorist, citation, appeal = ctx["motorist"], ctx["citation"], ctx["appeal"]
    assert get_motorist(motorist["id"])["outstanding_balance_cents"] == 8000
    decided = decide_appeal(appeal["id"], "UPHELD")
    assert decided["status"] == "UPHELD"
    assert get_citation(citation["id"])["status"] == "DISMISSED"
    assert get_motorist(motorist["id"])["outstanding_balance_cents"] == 0
