"""Grievance filing, negotiation, arbitration, and settlement cash (PRD §3.6)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def _staffing_bundle(name, fein, scope="THEATRICAL"):
    return th.create_staffing_production(name, fein, scope=scope)


def _filed_grievance(bundle, category="PAY", incident="2026-07-20",
                     description="Late payroll for week 30"):
    return th.file_grievance(bundle["production"], category=category,
                             incident_date=incident, description=description)


def test_reject_returns_to_investigating(api):
    """PRD §3.6: "A `REJECT` marks the proposal `REJECTED` and sends the
    grievance back to `INVESTIGATING`, completing one leg of the negotiation
    cycle."

    Design: Difficulty/non_linear_state_machine/grievance_settlement_negotiation_cycle
    """
    bundle = _staffing_bundle("Harbor Light LLC", "55-4444444")
    company = bundle["company"]
    grievance = _filed_grievance(bundle)
    grievance = th.accept_intake(grievance, "ur_1")
    grievance = th.propose_settlement(grievance, 50_000, grievance["version"], "ur_2")
    assert grievance["status"] == "PROPOSED_SETTLEMENT"

    rejected = th.respond_settlement(grievance, company, "REJECT")
    assert rejected["status"] == "INVESTIGATING"
    assert rejected["proposal_status"] == "REJECTED"


def test_second_proposal_accepted_and_paid_closes(api):
    """PRD §3.6: "An `ACCEPT` marks the proposal `ACCEPTED`, copies its amount
    into `settlement_agreed_cents`, and moves the grievance to `RESOLVED`" and
    "the payment that brings the paid total exactly level with the agreed
    amount closes the grievance automatically". After one REJECT leg the second
    proposal of 70,000 is accepted and paid in full.

    Design: Difficulty/non_linear_state_machine/grievance_settlement_negotiation_cycle
    """
    bundle = _staffing_bundle("Harbor Light LLC", "55-4444444")
    company = bundle["company"]
    grievance = _filed_grievance(bundle)
    grievance = th.accept_intake(grievance, "ur_1")
    grievance = th.propose_settlement(grievance, 50_000, grievance["version"], "ur_2")
    grievance = th.respond_settlement(grievance, company, "REJECT")

    grievance = th.propose_settlement(grievance, 70_000, grievance["version"], "ur_2")
    assert grievance["proposal_status"] == "OPEN"
    resolved = th.respond_settlement(grievance, company, "ACCEPT")
    assert resolved["status"] == "RESOLVED"
    assert resolved["settlement_agreed_cents"] == 70_000

    closed = th.pay_grievance(resolved, company, 70_000)
    assert closed["settlement_paid_cents"] == 70_000
    assert closed["status"] == "CLOSED"


def test_expired_window_beats_cross_reference(api, union_rep_headers):
    """PRD §2.10: "Business rules run last, in this fixed sequence: ... the
    grievance filing window (`ERR_FILING_WINDOW_EXPIRED`); cross-production
    references (`ERR_CROSS_PRODUCTION_REFERENCE`)". A filing that violates both
    (incident 2026-06-21 vs clock 2026-08-01, and a crew assignment of another
    production) reports the filing-window error.
    PRD §3.6: "The first pass sets a provisional deadline 30 days after the
    `incident_date`" and "a later filing is rejected with
    `ERR_FILING_WINDOW_EXPIRED` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/grievance_filing_temporal_beats_cross_production_referential
    """
    bundle = _staffing_bundle("Maple Gate LLC", "99-8888888")
    company = bundle["company"]
    production_a = bundle["production"]
    ca1 = th.hire_crew(production_a, company, "W-CAM-1", "CAMERA",
                       "CAMERA_OPERATOR", 100_000)
    production_b = th.create_production(company, "Maple B")
    bond_b = th.get_production_bond(production_b, company)
    th.post_bond(bond_b, company)

    resp = api.create_grievance(
        th.create_grievance_payload(
            production_id=production_b["id"], crew_assignment_id=ca1["id"],
            category="WORK_RULE", incident_date="2026-06-21",
            description="Cross-production reference with expired window",
        ),
        union_rep_headers,
    )
    th.validate_error(resp, E.ERR_FILING_WINDOW_EXPIRED)

    grievances, _ = th.validate_paginated(
        api.list_production_grievances(production_b["id"], th.owner_headers(company))
    )
    assert grievances == [], "rejected filing must not create a grievance"


def test_cross_production_reference_rejected_in_window(api, union_rep_headers):
    """PRD §3.6: "When `crew_assignment_id` is provided it must reference an
    assignment of the same production; a cross-production reference is
    `ERR_CROSS_PRODUCTION_REFERENCE` (HTTP 422)." With an in-window incident
    date (2026-07-20, deadline 2026-08-19 vs clock 2026-08-01), the referential
    violation surfaces on its own.

    Design: Difficulty/priority_pair_validation_conflict/grievance_filing_temporal_beats_cross_production_referential
    """
    bundle = _staffing_bundle("Maple Gate LLC", "99-8888888")
    company = bundle["company"]
    production_a = bundle["production"]
    ca1 = th.hire_crew(production_a, company, "W-CAM-1", "CAMERA",
                       "CAMERA_OPERATOR", 100_000)
    production_b = th.create_production(company, "Maple B")
    bond_b = th.get_production_bond(production_b, company)
    th.post_bond(bond_b, company)

    resp = api.create_grievance(
        th.create_grievance_payload(
            production_id=production_b["id"], crew_assignment_id=ca1["id"],
            category="WORK_RULE", incident_date="2026-07-20",
            description="Cross-production reference inside the window",
        ),
        union_rep_headers,
    )
    th.validate_error(resp, E.ERR_CROSS_PRODUCTION_REFERENCE)


def test_decide_before_escalation_rejected(api, arbitrator_headers):
    """PRD §3.6: "From `ESCALATED`, an `Arbitrator` decides the matter with an
    `award_cents` amount and optional `decision_notes`; deciding from any other
    state is `ERR_GRIEVANCE_STATE`."

    Design: Corner/state_machines/grievance_decide_before_escalation_rejected
    """
    bundle = _staffing_bundle("Jackpine LLC", "20-0000010")
    grievance = _filed_grievance(bundle, category="SAFETY",
                                 description="Unsafe rigging")

    resp = api.decide_grievance(grievance["id"], {"award_cents": 5_000},
                                arbitrator_headers)
    th.validate_error(resp, E.ERR_GRIEVANCE_STATE)

    grievances, _ = th.validate_paginated(api.list_production_grievances(
        bundle["production"]["id"], th.owner_headers(bundle["company"]),
    ))
    current = next(g for g in grievances if g["id"] == grievance["id"])
    assert current["status"] == "FILED", "rejected decide must not change state"


def test_respond_without_open_proposal_rejected(api):
    """PRD §3.6: "The producer answers an open proposal with a `decision` while
    the grievance is `PROPOSED_SETTLEMENT` and the proposal still `OPEN`."
    An INVESTIGATING grievance has no open proposal, so the respond call is a
    grievance from-state violation (`ERR_GRIEVANCE_STATE`, PRD §2.10).

    Design: Corner/state_machines/grievance_respond_without_open_proposal_rejected
    """
    bundle = _staffing_bundle("Tansy LLC", "20-0000020", scope="TELEVISION")
    grievance = _filed_grievance(bundle, category="CLASSIFICATION",
                                 description="Misclassified boom op")
    grievance = th.accept_intake(grievance, "ur_1")
    assert grievance["status"] == "INVESTIGATING"

    resp = api.respond_settlement(
        grievance["id"], {"decision": "ACCEPT"}, th.owner_headers(bundle["company"]),
    )
    th.validate_error(resp, E.ERR_GRIEVANCE_STATE)

    grievances, _ = th.validate_paginated(api.list_production_grievances(
        bundle["production"]["id"], th.owner_headers(bundle["company"]),
    ))
    current = next(g for g in grievances if g["id"] == grievance["id"])
    assert current["status"] == "INVESTIGATING"
    assert current["proposal_status"] == "NONE"


def test_escalate_supersedes_open_proposal(api):
    """PRD §3.6: "Either side may escalate: a `UnionRep` or a `ProducerRep`
    moves the grievance from `INVESTIGATING` or `PROPOSED_SETTLEMENT` to
    `ESCALATED`, superseding any still-`OPEN` proposal."

    Design: Corner/state_machines/escalate_supersedes_open_proposal
    """
    bundle = _staffing_bundle("Upland LLC", "20-0000021")
    company = bundle["company"]
    grievance = _filed_grievance(bundle, description="Rate dispute")
    grievance = th.accept_intake(grievance, "ur_1")
    grievance = th.propose_settlement(grievance, 50_000, grievance["version"], "ur_2")
    assert grievance["proposal_status"] == "OPEN"

    escalated = th.get_success_data(
        api.escalate_grievance(grievance["id"], th.owner_headers(company))
    )
    th.assert_grievance(escalated)
    assert escalated["status"] == "ESCALATED"
    assert escalated["proposal_status"] == "SUPERSEDED"
    assert escalated["settlement_agreed_cents"] == 0


def test_zero_award_closes_immediately(api, arbitrator_headers):
    """PRD §3.6: "The award is recorded as `settlement_agreed_cents`, the
    grievance moves to `DECIDED`, and an award of zero closes the grievance
    immediately with a posture recompute."

    Design: Corner/state_machines/arbitrator_zero_award_closes_grievance
    """
    bundle = _staffing_bundle("Vervain LLC", "20-0000022", scope="NEW_MEDIA")
    grievance = _filed_grievance(bundle, category="OTHER",
                                 description="Poster credit dispute")
    grievance = th.accept_intake(grievance, "ur_1")
    grievance = th.escalate_grievance(grievance, "ur_1")

    decided = th.get_success_data(api.decide_grievance(
        grievance["id"], {"award_cents": 0, "decision_notes": "No violation found"},
        arbitrator_headers,
    ))
    th.assert_grievance(decided)
    assert decided["status"] == "CLOSED"
    assert decided["settlement_agreed_cents"] == 0


def test_closing_grievances_restores_clear_posture(api, arbitrator_headers):
    """PRD §2.8: "the posture is `RESTRICTED` when at least one of three
    conditions holds: the count of the production's grievances in `FILED`,
    `INVESTIGATING`, `PROPOSED_SETTLEMENT`, or `ESCALATED` status reaches 2"
    and "If none of these holds, the posture is `CLEAR`." PRD §3.6: "an award
    of zero closes the grievance immediately with a posture recompute." With
    two open grievances the posture is RESTRICTED; closing one drops the open
    count to 1 — below the inclusive threshold of 2 — so the posture returns
    to CLEAR, and closing the second leaves it CLEAR.

    Design: Corner/state_machines/grievance_close_drops_posture_back_to_clear
    """
    bundle = _staffing_bundle("Oxslip LLC", "20-0000015")
    company, production = bundle["company"], bundle["production"]
    g1 = _filed_grievance(bundle, description="G1 meal penalties unpaid")
    g2 = th.file_grievance(production, category="WORK_RULE",
                           incident_date="2026-07-21",
                           description="G2 turnaround violations")
    assert th.get_production(production["id"], company)["compliance_posture"] == "RESTRICTED"

    for g in (g1,):
        g = th.accept_intake(g, "ur_1")
        g = th.escalate_grievance(g, "ur_1")
        closed = th.decide_grievance(g, 0)
        assert closed["status"] == "CLOSED", "zero award closes immediately"

    mid = th.get_production(production["id"], company)
    assert mid["compliance_posture"] == "CLEAR", (
        "open-grievance count 1 is below the inclusive threshold of 2")

    g2 = th.accept_intake(g2, "ur_1")
    g2 = th.escalate_grievance(g2, "ur_1")
    th.decide_grievance(g2, 0)

    final = th.get_production(production["id"], company)
    assert final["compliance_posture"] == "CLEAR"


def test_intake_unionrep_cannot_propose(api):
    """PRD §3.6: "Settlement proposals come from a different pair of hands —
    the proposing `UnionRep`'s `X-User-ID` must differ from `intake_user_id`,
    or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.6: "On success the grievance moves from `INVESTIGATING` to
    `PROPOSED_SETTLEMENT`".

    Design: Corner/validations/same_unionrep_propose_after_intake_rejected
    """
    bundle = _staffing_bundle("Fumitory LLC", "20-0000033")
    grievance = _filed_grievance(bundle, description="Missing meal penalties")
    grievance = th.accept_intake(grievance, "ur_1")

    resp = api.propose_settlement(
        grievance["id"],
        {"proposal_amount_cents": 50_000,
         "expected_grievance_version": grievance["version"]},
        th.make_union_rep_headers("ur_1"),
    )
    th.validate_error(resp, E.ERR_SEGREGATION_OF_DUTIES)

    proposed = th.propose_settlement(grievance, 50_000, grievance["version"], "ur_2")
    assert proposed["status"] == "PROPOSED_SETTLEMENT"
    assert proposed["proposal_amount_cents"] == 50_000


def test_overpayment_and_overrefund_rejected(api):
    """PRD §3.6: "a `ProducerRep` pays an `amount_cents` that must be greater
    than zero and must not push `settlement_paid_cents` past
    `settlement_agreed_cents` — a breach either way is `ERR_OVERPAYMENT`
    (HTTP 422)" and "a refund of an `amount_cents` that is greater than zero
    and no more than the current `settlement_paid_cents` reduces the paid
    total; anything else is `ERR_REFUND_EXCEEDS_PAID` (HTTP 422)."

    Design: Corner/validations/settlement_overpayment_and_overrefund_rejected
    """
    bundle = _staffing_bundle("Marestail LLC", "20-0000040", scope="NEW_MEDIA")
    company = bundle["company"]
    grievance = th.create_resolved_grievance(bundle, amount=70_000)

    resp = api.pay_grievance(grievance["id"], {"amount_cents": 70_001},
                             th.owner_headers(company))
    th.validate_error(resp, E.ERR_OVERPAYMENT)

    resp = api.refund_grievance(grievance["id"], {"amount_cents": 1},
                                th.owner_headers(company))
    th.validate_error(resp, E.ERR_REFUND_EXCEEDS_PAID)

    closed = th.pay_grievance(grievance, company, 70_000)
    assert closed["settlement_paid_cents"] == 70_000
    assert closed["status"] == "CLOSED"


def test_stale_proposal_version_rejected(api):
    """PRD §2.9: "Submitting a settlement proposal on a grievance requires
    `expected_grievance_version` holding the grievance's `version` as last
    observed" and "if the supplied value does not equal the entity's current
    `version` — because another writer has advanced the entity since the client
    last read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_stale_version_on_propose_settlement_rejected
    """
    bundle = _staffing_bundle("Xanthium LLC", "20-0000051")
    grievance = _filed_grievance(bundle, description="Rate underpayment")
    grievance = th.accept_intake(grievance, "ur_1")
    observed_version = grievance["version"]

    proposed = th.propose_settlement(grievance, 50_000, observed_version, "ur_2")
    assert proposed["status"] == "PROPOSED_SETTLEMENT"
    assert proposed["proposal_amount_cents"] == 50_000

    resp = api.propose_settlement(
        grievance["id"],
        {"proposal_amount_cents": 60_000,
         "expected_grievance_version": observed_version},
        th.make_union_rep_headers("ur_2"),
    )
    th.validate_error(resp, E.ERR_STALE_VERSION)

    grievances, _ = th.validate_paginated(api.list_production_grievances(
        bundle["production"]["id"], th.owner_headers(bundle["company"]),
    ))
    current = next(g for g in grievances if g["id"] == grievance["id"])
    assert current["proposal_amount_cents"] == 50_000, "stale proposal must not apply"


def test_pay_refund_net_conservation(api):
    """PRD §3.6: "Each payment accumulates into `settlement_paid_cents`" and
    "a refund of an `amount_cents` that is greater than zero and no more than
    the current `settlement_paid_cents` reduces the paid total". Paying 50,000
    then refunding 20,000 leaves the settlement cash balance at exactly
    30,000 — no drift.

    Design: Difficulty/compensating_invariant/grievance_settlement_pay_refund_conservation
    """
    bundle = _staffing_bundle("Umber Cove LLC", "18-0000007", scope="NEW_MEDIA")
    company = bundle["company"]
    grievance = th.create_resolved_grievance(bundle, amount=70_000)

    paid = th.pay_grievance(grievance, company, 50_000)
    assert paid["settlement_paid_cents"] == 50_000

    refunded = th.refund_grievance(paid, company, 20_000)
    assert refunded["settlement_paid_cents"] == 30_000, (
        "pay 50,000 + compensating refund 20,000 nets to 30,000"
    )


def test_final_payment_closes_grievance(api):
    """PRD §3.6: "Each payment accumulates into `settlement_paid_cents`, and
    the payment that brings the paid total exactly level with the agreed amount
    closes the grievance automatically and recomputes the production's posture
    as the open-grievance count drops." After pay 50,000 / refund 20,000, a
    final payment of 40,000 brings paid == agreed (70,000) and closes.

    Design: Difficulty/compensating_invariant/grievance_settlement_pay_refund_conservation
    """
    bundle = _staffing_bundle("Umber Cove LLC", "18-0000007", scope="NEW_MEDIA")
    company = bundle["company"]
    grievance = th.create_resolved_grievance(bundle, amount=70_000)

    paid = th.pay_grievance(grievance, company, 50_000)
    refunded = th.refund_grievance(paid, company, 20_000)
    closed = th.pay_grievance(refunded, company, 40_000)

    assert closed["settlement_paid_cents"] == 70_000
    assert closed["status"] == "CLOSED"


def test_filing_window_tolling_extends_deadline(api, union_rep_headers):
    """PRD §3.6: "Tolling then collects every force majeure event of the
    production — `ACTIVE` or `LIFTED` alike — each contributing the interval
    that runs from its `start_date` up to but not including its effective end"
    and "The second and final pass sets the deadline to the incident date plus
    30 days plus the tolling days. Filing is valid while the current clock date
    is on or before that deadline — the boundary is inclusive — and a later
    filing is rejected with `ERR_FILING_WINDOW_EXPIRED` (HTTP 422)."
    Incident 2026-07-05: production A's event [2026-07-01, 2026-07-10) tolls 5
    days (deadline 2026-08-09, filing at clock 2026-08-06 valid); production
    B's event [2026-07-01, 2026-07-03) does not intersect the window (deadline
    2026-08-04, filing expired).

    Design: Corner/validations/filing_window_tolling_extends_deadline
    """
    bundle = _staffing_bundle("Quince LLC", "20-0000044")
    company = bundle["company"]
    production_a = bundle["production"]
    production_b = th.create_production(company, "Quince B")
    bond_b = th.get_production_bond(production_b, company)
    th.post_bond(bond_b, company)

    th.set_clock("2026-08-06T00:00:00Z")
    fm_a = th.declare_force_majeure(production_a, "STRIKE",
                                    "2026-07-01", "2026-07-10")
    th.lift_force_majeure(fm_a)
    fm_b = th.declare_force_majeure(production_b, "STRIKE",
                                    "2026-07-01", "2026-07-03")
    th.lift_force_majeure(fm_b)

    filed = th.get_success_data(api.create_grievance(
        th.create_grievance_payload(
            production_id=production_a["id"], category="OTHER",
            incident_date="2026-07-05", description="Tolled window filing",
        ),
        union_rep_headers,
    ))
    th.assert_grievance(filed)
    assert filed["status"] == "FILED"

    resp = api.create_grievance(
        th.create_grievance_payload(
            production_id=production_b["id"], category="OTHER",
            incident_date="2026-07-05", description="Untolled window filing",
        ),
        union_rep_headers,
    )
    th.validate_error(resp, E.ERR_FILING_WINDOW_EXPIRED)


def test_unionrep_cannot_decide_grievance(api):
    """PRD §2.1: "A request whose role is authenticated but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD §3.6: "From `ESCALATED`, an `Arbitrator` decides the
    matter with an `award_cents` amount and optional `decision_notes`".

    Design: Corner/rbac/unionrep_cannot_decide_grievance
    """
    bundle = _staffing_bundle("Umbel LLC", "20-0000048")
    grievance = _filed_grievance(bundle, category="SAFETY",
                                 description="Heat safety")
    grievance = th.accept_intake(grievance, "ur_1")
    grievance = th.escalate_grievance(grievance, "ur_1")
    assert grievance["status"] == "ESCALATED"

    resp = api.decide_grievance(grievance["id"], {"award_cents": 5_000},
                                th.make_union_rep_headers("ur_3"))
    th.validate_error(resp, E.ERR_UNAUTHORIZED_ROLE)

    grievances, _ = th.validate_paginated(api.list_production_grievances(
        bundle["production"]["id"], th.owner_headers(bundle["company"]),
    ))
    current = next(g for g in grievances if g["id"] == grievance["id"])
    assert current["status"] == "ESCALATED", "denied decide must not change state"
