"""Approval-chain construction: multi-input routing, band boundaries, policies."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, create_draft_offer, create_offer_with_perks,
    create_policy, setup_exception_policy_rows,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _chain_roles(api, offer_id):
    steps = validate_success(api.list_approval_steps(offer_id, REC))
    ordered = sorted(steps, key=lambda s: s["sequence"])
    return [s["required_role"] for s in ordered], ordered


def _setup_multi_input(api):
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Staff Eng", headcount_authorized=2)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand D")
    offer, _ = create_offer_with_perks(
        req, cand,
        [{"kind": "SIGN_ON", "amount_cents": 1500000, "clawback_months": 12, "clawback_variant": "FULL_CLIFF"}],
        REC,
        base_cents=26000000, bonus_target_pct=0.10, equity_shares=0, equity_fmv_cents=0,
    )
    return offer


def test_chain_resolves_four_routing_inputs(api):
    """PRD §3.5: "Then every `ACTIVE` ApprovalPolicy row whose
    `min_band_severity` is at or below the offer's band severity contributes its
    `required_role` ... each role is appended only if not already in the chain —
    deduplication keeps the earliest occurrence. Two escalation rules follow. If
    the offer's sign-on perk total exceeds 1,000,000 cents, or either equity
    risk flag is set, the chain must contain `CompAnalyst` — appended after the
    policy rows if absent. If `total_cash_cents` reaches 30,000,000 cents, the
    chain must contain `VPPeople` — appended last if absent."

    Design: Difficulty/combinatorial_formula/approval_chain_multi_input_routing
    """
    offer = _setup_multi_input(api)
    submitted = validate_success(api.submit_offer(offer["id"], REC))
    assert submitted["band"] == "EXCEPTION"
    assert submitted["total_cash_cents"] == 30100000
    # 26000000 / 19500000 = 1.3333 > 1.15
    assert submitted["equity_compa_risk_flag"] is True
    roles, _ = _chain_roles(api, offer["id"])
    assert roles == ["HiringManager", "CompAnalyst", "DepartmentDirector", "VPPeople"]


def test_chain_step_zero_actionable_rest_waiting(api):
    """PRD §3.5: "the entries receive `sequence` values from zero upward, each
    becoming an ApprovalStep whose `offer_id` points back to the offer, with
    sequence zero starting `ACTIONABLE` and every later step `WAITING`."

    Design: Difficulty/combinatorial_formula/approval_chain_multi_input_routing
    """
    offer = _setup_multi_input(api)
    validate_success(api.submit_offer(offer["id"], REC))
    _, ordered = _chain_roles(api, offer["id"])
    assert [s["sequence"] for s in ordered] == [0, 1, 2, 3]
    assert ordered[0]["status"] == "ACTIONABLE"
    assert all(s["status"] == "WAITING" for s in ordered[1:])


def test_band_boundary_at_salary_max_and_tolerance_submit_side(api):
    """PRD §3.3: "A base at or below `salary_max_cents` — including exactly the
    minimum or exactly the maximum — classifies `IN_BAND`. A base above the
    maximum but not above one hundred ten percent of it classifies `ABOVE_BAND`".

    Design: Difficulty/boundary_precision_check/band_boundary_at_salary_max_and_tolerance
    """
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Eng Pool", annual_budget_cents=100000000,
                                  headcount_authorized=3)
    create_standard_peers(base_list=(19000000, 20000000, 21500000))
    cand_p = create_candidate_recruited(REC, full_name="Cand P")
    cand_q = create_candidate_recruited(REC, full_name="Cand Q")
    offer_p = create_draft_offer(req, cand_p, REC, base_cents=21000000)
    offer_q = create_draft_offer(req, cand_q, REC, base_cents=21000001)

    sub_p = validate_success(api.submit_offer(offer_p["id"], REC))
    assert sub_p["band"] == "IN_BAND"
    roles_p, _ = _chain_roles(api, offer_p["id"])
    assert roles_p == ["HiringManager"]

    sub_q = validate_success(api.submit_offer(offer_q["id"], REC))
    assert sub_q["band"] == "ABOVE_BAND"
    roles_q, _ = _chain_roles(api, offer_q["id"])
    assert roles_q == ["HiringManager", "CompAnalyst"]


def test_band_boundary_exception_one_cent_over_tolerance(api):
    """PRD §3.3: "a base exactly equal to that one-hundred-ten-percent product
    is still `ABOVE_BAND`. Anything beyond classifies `EXCEPTION`, subject to
    the hard cap above."

    Design: Difficulty/boundary_precision_check/band_boundary_at_salary_max_and_tolerance
    """
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Eng Pool", annual_budget_cents=100000000,
                                  headcount_authorized=3)
    create_standard_peers(base_list=(19000000, 20000000, 21500000))
    cand_r = create_candidate_recruited(REC, full_name="Cand R")
    offer_r = create_draft_offer(req, cand_r, REC, base_cents=23100001)

    sub_r = validate_success(api.submit_offer(offer_r["id"], REC))
    assert sub_r["band"] == "EXCEPTION"
    roles_r, _ = _chain_roles(api, offer_r["id"])
    assert roles_r == ["HiringManager", "CompAnalyst", "DepartmentDirector", "VPPeople"]


def test_signon_tier_boundary_at_30m_routes_vp(api):
    """PRD §3.5: "If `total_cash_cents` reaches 30,000,000 cents, the chain must
    contain `VPPeople` — appended last if absent."
    PRD §3.3: "a `total_cash_cents` of at least 30,000,000 cents (three hundred
    thousand dollars) — the boundary value included — demands VP review."

    Design: Difficulty/combinatorial_formula/signon_tier_self_referential_evaluation_order
    """
    req = create_open_requisition(HM, annual_budget_cents=80000000, headcount_authorized=2)
    create_standard_peers()
    cand_a = create_candidate_recruited(REC, full_name="Cand F")
    offer_a, _ = create_offer_with_perks(
        req, cand_a,
        [{"kind": "SIGN_ON", "amount_cents": 2000000, "clawback_months": 24, "clawback_variant": "FULL_CLIFF"}] * 4,
        REC,
        base_cents=20000000, bonus_target_pct=0.10,
    )
    sub_a = validate_success(api.submit_offer(offer_a["id"], REC))
    # 20000000 + 2000000 + 4*2000000 == 30000000 — boundary included
    assert sub_a["total_cash_cents"] == 30000000
    roles_a, _ = _chain_roles(api, offer_a["id"])
    assert roles_a == ["HiringManager", "CompAnalyst", "VPPeople"]


def test_signon_tier_one_cent_below_30m_skips_vp(api):
    """PRD §3.3: "a `total_cash_cents` of at least 30,000,000 cents (three
    hundred thousand dollars) — the boundary value included — demands VP
    review." (29,999,999 cents does not reach the boundary.)
    PRD §3.5: "If the offer's sign-on perk total exceeds 1,000,000 cents ... the
    chain must contain `CompAnalyst`".

    Design: Difficulty/combinatorial_formula/signon_tier_self_referential_evaluation_order
    """
    req = create_open_requisition(HM, annual_budget_cents=80000000, headcount_authorized=2)
    create_standard_peers()
    cand_b = create_candidate_recruited(REC, full_name="Cand G")
    offer_b, _ = create_offer_with_perks(
        req, cand_b,
        [{"kind": "SIGN_ON", "amount_cents": 2000000, "clawback_months": 24, "clawback_variant": "FULL_CLIFF"}] * 3
        + [{"kind": "SIGN_ON", "amount_cents": 1999999, "clawback_months": 24, "clawback_variant": "FULL_CLIFF"}],
        REC,
        base_cents=20000000, bonus_target_pct=0.10,
    )
    sub_b = validate_success(api.submit_offer(offer_b["id"], REC))
    assert sub_b["total_cash_cents"] == 29999999
    roles_b, _ = _chain_roles(api, offer_b["id"])
    # sign-on total 7999999 > 1000000 keeps CompAnalyst; tier not crossed, no VPPeople
    assert roles_b == ["HiringManager", "CompAnalyst"]


def test_band_below_min_policy_routing(api):
    """PRD §3.2: "Severity is numeric under the hood — `IN_BAND` is severity
    one, `BELOW_MIN` and `ABOVE_BAND` are both severity two, and `EXCEPTION` is
    severity three — and a row applies to any offer whose band severity is at
    least the row's `min_band_severity`. A row keyed at `EXCEPTION` therefore
    catches only exception-band offers, while a row keyed at `BELOW_MIN` or
    `ABOVE_BAND` catches below-minimum, above-band, and exception offers alike."

    Design: Corner/calculations/band_below_min_policy_routing
    """
    create_policy("ABOVE_BAND", "CompAnalyst", 1, ADMIN)
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [14000000, 14000000, 14000000])
    cand = create_candidate_recruited(REC, full_name="Cand BM")
    offer = create_draft_offer(req, cand, REC, base_cents=14000000)
    sub = validate_success(api.submit_offer(offer["id"], REC))
    assert sub["band"] == "BELOW_MIN"
    assert sub["equity_compa_ratio"] == 1.0000
    assert sub["equity_percentile"] == 50
    assert sub["equity_compa_risk_flag"] is False
    assert sub["equity_percentile_risk_flag"] is False
    roles, _ = _chain_roles(api, offer["id"])
    assert roles == ["HiringManager", "CompAnalyst"]


def test_policy_deactivate_excludes_from_chain(api):
    """PRD §3.5: "Then every `ACTIVE` ApprovalPolicy row whose
    `min_band_severity` is at or below the offer's band severity contributes its
    `required_role`".
    PRD §3.2: "Rows are created `ACTIVE` and may later be deactivated to
    `INACTIVE`."

    Design: Corner/calculations/policy_deactivate_excludes_from_chain
    """
    pol = create_policy("ABOVE_BAND", "CompAnalyst", 1, ADMIN)
    req = create_open_requisition(HM, annual_budget_cents=80000000)
    # peers chosen so compa == 1.0000 and percentile == 50: neutral flags
    create_peer_snapshots("L5", "T1", [20000000, 21000001, 22000000])
    cand = create_candidate_recruited(REC, full_name="Cand PD")
    offer = create_draft_offer(req, cand, REC, base_cents=21000001)
    get_success_data(api.deactivate_approval_policy(pol["id"], ADMIN))
    sub = validate_success(api.submit_offer(offer["id"], REC))
    assert sub["band"] == "ABOVE_BAND"
    assert sub["equity_compa_risk_flag"] is False
    assert sub["equity_percentile_risk_flag"] is False
    roles, _ = _chain_roles(api, offer["id"])
    assert roles == ["HiringManager"]
    pol_after = validate_success(api.list_approval_policies(ADMIN, params={"status": "INACTIVE"}))
    assert any(p["id"] == pol["id"] for p in pol_after)


def test_steps_and_events_ordering(api):
    """PRD §3.5: "the entries receive `sequence` values from zero upward".
    PRD §2.9: "Every Offer owns an append-only sequence of OfferEvent records,
    ordered by a `sequence` that starts at 1 and increases monotonically per
    offer ... The trail is readable per offer, paginated, and filterable by
    `event_type`."

    Design: Corner/endpoints/steps_and_events_ordering
    """
    create_policy("ABOVE_BAND", "CompAnalyst", 1, ADMIN)
    req = create_open_requisition(HM, annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand OR")
    offer = create_draft_offer(req, cand, REC, base_cents=22000000)
    validate_success(api.submit_offer(offer["id"], REC))

    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    assert [s["sequence"] for s in steps] == [0, 1]
    assert [s["required_role"] for s in steps] == ["HiringManager", "CompAnalyst"]

    events = validate_success(api.list_offer_events(offer["id"], REC))
    seqs = [e["sequence"] for e in events]
    assert seqs == sorted(seqs) and seqs[0] == 1
    types = [e["event_type"] for e in events]
    assert types[0] == "OFFER_CREATED"
    assert types[1] == "SUBMITTED"

    filtered = validate_success(api.list_offer_events(offer["id"], REC, params={"event_type": "SUBMITTED"}))
    assert len(filtered) == 1
    assert filtered[0]["event_type"] == "SUBMITTED"


def test_immediate_read_after_submit(api):
    """PRD §2.8: "Two standing aggregates live on every requisition:
    `committed_budget_cents`, the sum of the fully loaded annual cost over
    exactly those of its offers in `PENDING_APPROVAL`, `APPROVED`,
    `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` status,
    recomputed in full — never incrementally adjusted — whenever an offer enters
    or leaves that counted set".
    PRD §3.5: "with sequence zero starting `ACTIONABLE` and every later step
    `WAITING`."

    Design: Corner/consistency_model/immediate_read_after_submit
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand IC")
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    sub = validate_success(api.submit_offer(offer["id"], REC))
    assert sub["status"] == "PENDING_APPROVAL"
    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    assert steps[0]["sequence"] == 0
    assert steps[0]["status"] == "ACTIONABLE"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    # fully = 20000000 + 6000000 benefits = 26000000
    assert req_after["committed_budget_cents"] == 26000000
