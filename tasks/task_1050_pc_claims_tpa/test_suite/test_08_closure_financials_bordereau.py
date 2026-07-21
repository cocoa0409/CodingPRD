"""Claim closure preconditions, referential-vs-temporal validation priority, the
provisional/developed financial snapshot, and bordereau per-claim rounding.

Translates cross_entity_state_dependency (litigation), priority_pair_validation_conflict
(referential vs temporal), dual_variant_calc (financials), combinatorial_formula and
boundary_precision (bordereau) difficulty instances plus closure corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    make_adjuster_headers,
    setup_evaluated_claim, create_litigation_case, create_pending_payment,
    create_subrogation_case, setup_claim_with_paid_indemnity,
    create_standing_data, create_account, create_policy, create_vendor,
    create_claim, create_adjuster_assignment, create_vendor_assignment,
    post_reserve_change, create_bordereau, get_claim,
    create_assignment_payload,
)

CM = TEST_USERS["claims_manager_headers"]


# --------------------------------------------------------------------------- #
# Closure blocked by dependent-entity state
# --------------------------------------------------------------------------- #
def test_close_blocked_by_open_litigation(api):
    """PRD §3.9: "Four preconditions guard closure: every litigation case on the claim must be
    terminal — `SETTLED`, `DISMISSED`, or `JUDGMENT` — otherwise `ERR_LITIGATION_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/claim_close_blocked_by_open_litigation
    """
    env = setup_evaluated_claim(api, account_overrides={"account_code": "CE2"},
                                claim_overrides={"coverage_type": "LIABILITY"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    create_litigation_case(api, claim_id)
    validate_error(api.transition_claim(claim_id, "CLOSED", adj), "ERR_LITIGATION_OPEN")


def test_open_litigation_leaves_claim_evaluated(api):
    """PRD §3.7: "while a case remains `OPEN` or `IN_SUIT` it is non-terminal and blocks claim
    closure (§3.9)."

    Design: Difficulty/cross_entity_state_dependency/claim_close_blocked_by_open_litigation
    """
    env = setup_evaluated_claim(api, account_overrides={"account_code": "CE2b"},
                                claim_overrides={"coverage_type": "LIABILITY"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    create_litigation_case(api, claim_id)
    validate_error(api.transition_claim(claim_id, "CLOSED", adj), "ERR_LITIGATION_OPEN")
    assert get_claim(api, claim_id, adj)["status"] == "EVALUATED"


def test_close_blocked_by_pending_payment(api):
    """PRD §3.9: "no payment may be `PENDING_APPROVAL` or `APPROVED`, otherwise
    `ERR_PAYMENT_PENDING`".

    Design: Corner/state_machines/claim_close_blocked_by_pending_payment
    """
    env = setup_evaluated_claim(api, account_overrides={"account_code": "C-PP"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    create_pending_payment(api, claim_id, adj, 100000)
    validate_error(api.transition_claim(claim_id, "CLOSED", adj), "ERR_PAYMENT_PENDING")
    assert get_claim(api, claim_id, adj)["status"] == "EVALUATED"


def test_close_blocked_by_open_subrogation(api):
    """PRD §3.9: "no subrogation case may be `OPEN`, `DEMAND_SENT`, or `NEGOTIATING`,
    otherwise `ERR_SUBROGATION_OPEN`".

    Design: Corner/state_machines/close_blocked_by_open_subrogation
    """
    env = setup_evaluated_claim(api, account_overrides={"account_code": "C-SO"},
                                claim_overrides={"coverage_type": "AUTO"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    sub = create_subrogation_case(api, claim_id, adj, demand_cents=100000)
    validate_success(api.transition_subrogation_case(sub["id"], "DEMAND_SENT", adj), 200)
    validate_error(api.transition_claim(claim_id, "CLOSED", adj), "ERR_SUBROGATION_OPEN")


# --------------------------------------------------------------------------- #
# Referential (credential) beats temporal (window) on vendor assignment
# --------------------------------------------------------------------------- #
def _setup_referential_vs_temporal(api, account_code, policy_number):
    account = create_account(api, account_code=account_code)
    policy = create_policy(api, account["id"], policy_number=policy_number)
    vendor = create_vendor(api, name="Auto Only", vendor_type="APPRAISER",
                           credentialed_coverages=["AUTO"])
    claim1 = create_claim(api, policy["id"], CM, coverage_type="AUTO", claimant_name="A")
    claim2 = create_claim(api, policy["id"], CM, coverage_type="PROPERTY", claimant_name="B")
    create_vendor_assignment(api, claim1["id"], vendor["id"], CM,
                             inspection_start="2026-06-17T09:00:00Z",
                             inspection_end="2026-06-17T11:00:00Z")
    return claim2, vendor


def test_vendor_credential_error_precedes_window_conflict(api):
    """PRD §2.8: "policy active, vendor credentialed, assignee shape correct, yielding
    `ERR_POLICY_INACTIVE`, `ERR_VENDOR_NOT_CREDENTIALED`, or `ERR_ASSIGNEE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_vendor_assignment
    """
    claim2, vendor = _setup_referential_vs_temporal(api, "PP2", "P-PP2")
    # Not credentialed for PROPERTY (pri 7) AND window overlaps the vendor's active window (pri 9).
    payload = create_assignment_payload(
        claim2["id"], "VENDOR", vendor_id=vendor["id"], scope="APPRAISAL",
        inspection_start="2026-06-17T10:00:00Z", inspection_end="2026-06-17T12:00:00Z")
    validate_error(api.create_assignment(payload, CM), "ERR_VENDOR_NOT_CREDENTIALED")


def test_referential_conflict_creates_no_assignment(api):
    """PRD §2.8: "the checks are evaluated in a fixed priority order and the first failure
    determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_vendor_assignment
    """
    claim2, vendor = _setup_referential_vs_temporal(api, "PP2b", "P-PP2b")
    payload = create_assignment_payload(
        claim2["id"], "VENDOR", vendor_id=vendor["id"], scope="APPRAISAL",
        inspection_start="2026-06-17T10:00:00Z", inspection_end="2026-06-17T12:00:00Z")
    validate_error(api.create_assignment(payload, CM), "ERR_VENDOR_NOT_CREDENTIALED")
    data, _ = validate_paginated(api.list_assignments(CM, params={"claim_id": claim2["id"]}))
    assert len(data) == 0


# --------------------------------------------------------------------------- #
# Provisional vs developed financial snapshot
# --------------------------------------------------------------------------- #
def test_financials_provisional_vs_developed_incurred(api):
    """PRD §3.9: "The **developed** basis applies an incurred-but-not-reported tail: the
    developed outstanding is the greater of the set case reserves and 15 percent of the paid
    total (that product rounded half up), and the developed gross incurred is the paid total
    plus that developed outstanding."

    Design: Difficulty/dual_variant_calc/claim_incurred_provisional_vs_developed
    """
    env = setup_claim_with_paid_indemnity(api, amount_cents=600000,
                                          account_overrides={"account_code": "DV1"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    fin = validate_success(api.get_claim_financials(claim_id, adj), 200)
    # reserves released to 0 at issuance; developed floor = round(600000*0.15) = 90000.
    assert fin["gross_incurred_provisional_cents"] == 600000
    assert fin["gross_incurred_developed_cents"] == 690000


def test_financials_snapshot_paid_and_net(api):
    """PRD §3.9: "It returns `paid_total_cents` (the two paid buckets combined),
    `outstanding_reserve_cents` (the two case reserves combined), `gross_incurred_provisional_cents`
    (paid total plus the case reserves exactly as set — the same basis stored in the claim's
    `gross_incurred_cents`), `gross_incurred_developed_cents`, and `net_incurred_cents`."

    Design: Difficulty/dual_variant_calc/claim_incurred_provisional_vs_developed
    """
    env = setup_claim_with_paid_indemnity(api, amount_cents=600000,
                                          account_overrides={"account_code": "DV1b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    fin = validate_success(api.get_claim_financials(claim_id, adj), 200)
    assert fin["paid_total_cents"] == 600000
    assert fin["outstanding_reserve_cents"] == 0
    assert fin["net_incurred_cents"] == 600000


# --------------------------------------------------------------------------- #
# Bordereau: per-claim round-then-sum
# --------------------------------------------------------------------------- #
def _setup_two_small_reserve_claims(api, account_code, policy_number):
    account, policy, adjuster = create_standing_data(
        api, {"account_code": account_code}, {"policy_number": policy_number})
    adj = make_adjuster_headers(adjuster["id"])
    claim_a = create_claim(api, policy["id"], adj, claimant_name="A")
    create_adjuster_assignment(api, claim_a["id"], adjuster["id"], adj,
                               inspection_start="2026-06-16T09:00:00Z",
                               inspection_end="2026-06-16T10:00:00Z")
    claim_b = create_claim(api, policy["id"], adj, claimant_name="B")
    create_adjuster_assignment(api, claim_b["id"], adjuster["id"], adj,
                               inspection_start="2026-06-16T13:00:00Z",
                               inspection_end="2026-06-16T14:00:00Z")
    post_reserve_change(api, claim_a["id"], adj, 150)
    post_reserve_change(api, claim_b["id"], adj, 150)
    return account


def test_bordereau_rounds_each_claim_before_summing(api):
    """PRD §3.9: "The rounding order is pinned: each claim is rounded to whole dollars first
    and the rounded per-claim figures are then summed — the system never sums raw cents and
    rounds once."

    Design: Difficulty/combinatorial_formula/bordereau_rounding_order_per_claim_first
    """
    account = _setup_two_small_reserve_claims(api, "CF2", "P-CF2")
    report = validate_success(api.create_bordereau_report({
        "client_account_id": account["id"], "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z", "basis": "PROVISIONAL"}, CM), 201)
    # each claim gross_incurred_cents=150 -> round(1.50)=2 dollars; 2+2 = 4 (not round(300/100)=3).
    assert report["total_claim_count"] == 2
    assert report["total_incurred_dollars"] == 4


def test_bordereau_reports_zero_paid_for_reserve_only_claims(api):
    """PRD §3.9: "and separately converts its paid total (`paid_indemnity_cents` plus
    `paid_expense_cents`, divided by 100, rounded half up) and its `recovered_cents` (divided
    by 100, rounded half up)."

    Design: Difficulty/combinatorial_formula/bordereau_rounding_order_per_claim_first
    """
    account = _setup_two_small_reserve_claims(api, "CF2b", "P-CF2b")
    report = validate_success(api.create_bordereau_report({
        "client_account_id": account["id"], "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z", "basis": "PROVISIONAL"}, CM), 201)
    assert report["total_claim_count"] == 2
    assert report["total_paid_dollars"] == 0


# --------------------------------------------------------------------------- #
# Bordereau: empty candidate set
# --------------------------------------------------------------------------- #
def test_empty_bordereau_has_zero_claim_count(api):
    """PRD §3.9: "The report records `total_claim_count` as the number of in-scope claims."

    Design: Difficulty/boundary_precision_check/bordereau_empty_period_zero_totals
    """
    account = create_account(api, account_code="BP2", name="Empty Co")
    report = validate_success(api.create_bordereau_report({
        "client_account_id": account["id"], "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z", "basis": "PROVISIONAL"}, CM), 201)
    assert report["total_claim_count"] == 0


def test_empty_bordereau_has_zero_dollar_totals(api):
    """PRD §3.9: "These per-claim dollar figures are summed to yield `total_incurred_dollars`,
    `total_paid_dollars`, and `total_recovered_dollars`."

    Design: Difficulty/boundary_precision_check/bordereau_empty_period_zero_totals
    """
    account = create_account(api, account_code="BP2b", name="Empty Co")
    report = validate_success(api.create_bordereau_report({
        "client_account_id": account["id"], "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z", "basis": "PROVISIONAL"}, CM), 201)
    assert report["total_incurred_dollars"] == 0
    assert report["total_paid_dollars"] == 0
    assert report["total_recovered_dollars"] == 0
