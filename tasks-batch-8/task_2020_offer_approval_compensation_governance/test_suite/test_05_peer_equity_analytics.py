"""Peer-equity analytics: compa ratio vs percentile, midpoint ties, peer gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_offer_payload,
    create_open_requisition, create_candidate_recruited, create_peer_snapshots,
    create_draft_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]


def _skewed_setup(api):
    """Ten L4/T2 peers: nine at 10000000, one at 50000000; offer base 12500000."""
    req = create_open_requisition(
        HM, title="Analyst", department="FIN", role_level="L4", geo_tier="T2",
        annual_budget_cents=50000000, salary_min_cents=9000000,
        salary_mid_cents=12000000, salary_max_cents=15000000, headcount_authorized=1,
    )
    create_peer_snapshots("L4", "T2", [10000000] * 9 + [50000000])
    cand = create_candidate_recruited(REC, full_name="Cand B")
    offer = create_draft_offer(req, cand, REC, base_cents=12500000, bonus_target_pct=0,
                               equity_shares=0, equity_fmv_cents=0)
    return req, offer


def test_peer_equity_metrics_compa_vs_percentile_values(api):
    """PRD §3.3: "the peer mean is the sum of peer bases divided by the peer
    count, rounded half up to whole cents; `equity_compa_ratio` is the offer
    base divided by that mean, carried at four decimal places rounded half up;
    and `equity_percentile` is the midpoint percentile — take the count of peers
    strictly below the offer base, add half the count exactly equal to it,
    divide that sum by the peer count, then multiply by one hundred, with the
    single rounding half up to an integer from 0 to 100 applied at the end."

    Design: Difficulty/dual_variant_calc/peer_equity_compa_vs_percentile_flag_divergence
    """
    req, offer = _skewed_setup(api)
    fetched = validate_success(api.get_offer(offer["id"], REC))
    # mean = round_half_up((9*10000000 + 50000000)/10) = 14000000
    assert fetched["equity_compa_ratio"] == 0.8929
    # (9 + 0.5*0)/10 * 100 = 90
    assert fetched["equity_percentile"] == 90


def test_peer_equity_flag_divergence_drives_chain(api):
    """PRD §3.3: "`equity_compa_risk_flag` is true when the ratio is strictly
    below 0.85 or strictly above 1.15, and `equity_percentile_risk_flag` is true
    when the percentile is below 10 or at least 90 — a percentile of exactly 90
    flags."
    PRD §3.5: "If the offer's sign-on perk total exceeds 1,000,000 cents, or
    either equity risk flag is set, the chain must contain `CompAnalyst` —
    appended after the policy rows if absent."

    Design: Difficulty/dual_variant_calc/peer_equity_compa_vs_percentile_flag_divergence
    """
    req, offer = _skewed_setup(api)
    submitted = validate_success(api.submit_offer(offer["id"], REC))
    assert submitted["equity_compa_risk_flag"] is False
    assert submitted["equity_percentile_risk_flag"] is True
    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    roles = [s["required_role"] for s in sorted(steps, key=lambda s: s["sequence"])]
    # CompAnalyst is present only because of the percentile flag (no policy rows exist)
    assert roles == ["HiringManager", "CompAnalyst"]


def test_equity_percentile_tie_midpoint(api):
    """PRD §3.3: "`equity_percentile` is the midpoint percentile — take the
    count of peers strictly below the offer base, add half the count exactly
    equal to it, divide that sum by the peer count, then multiply by one
    hundred, with the single rounding half up to an integer from 0 to 100
    applied at the end."
    PRD §3.5: "Step zero is always the `HiringManager`."

    Design: Corner/calculations/equity_percentile_tie_midpoint
    """
    req = create_open_requisition(
        HM, title="Analyst", department="OPS", role_level="L3", geo_tier="T3",
        salary_min_cents=9000000, salary_mid_cents=12000000, salary_max_cents=15000000,
    )
    create_peer_snapshots("L3", "T3", [12000000, 12500000, 13000000])
    cand = create_candidate_recruited(REC, full_name="Cand PT")
    offer = create_draft_offer(req, cand, REC, base_cents=12500000)
    fetched = validate_success(api.get_offer(offer["id"], REC))
    # (1 + 0.5*1)/3 * 100 = 50; compa = 12500000/12500000 = 1.0000
    assert fetched["equity_percentile"] == 50
    assert fetched["equity_compa_ratio"] == 1.0000
    assert fetched["equity_compa_risk_flag"] is False
    assert fetched["equity_percentile_risk_flag"] is False
    validate_success(api.submit_offer(offer["id"], REC))
    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    assert len(steps) == 1
    assert steps[0]["required_role"] == "HiringManager"


def test_insufficient_peer_data_blocks_submit(api):
    """PRD §3.3: "With fewer than three matching snapshots, both
    `equity_compa_ratio` and `equity_percentile` are null and both risk flags
    are false; submission additionally refuses to proceed in this case (§3.5)."
    PRD §3.5: "At least three InternalEquitySnapshots must match the
    requisition's `role_level` and `geo_tier`, else `ERR_INSUFFICIENT_PEER_DATA`."

    Design: Corner/calculations/insufficient_peer_data_blocks_submit
    """
    req = create_open_requisition(HM, title="Principal", role_level="L6", geo_tier="T1")
    create_peer_snapshots("L6", "T1", [19000000, 19500000])
    cand = create_candidate_recruited(REC, full_name="Cand IP")
    resp = api.create_offer(
        create_offer_payload(requisition_id=req["id"], candidate_id=cand["id"], base_cents=18000000),
        REC,
    )
    offer = validate_success(resp, expected_status=201)
    assert offer["equity_compa_ratio"] is None
    assert offer["equity_percentile"] is None
    resp = api.submit_offer(offer["id"], REC)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PEER_DATA)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "DRAFT"
    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    assert steps == []
