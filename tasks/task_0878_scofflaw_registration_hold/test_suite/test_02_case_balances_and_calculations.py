"""Case-ledger balances, late-penalty rounding, threshold boundary, waterfall, referral snapshot.

Covers difficulty rules dual_variant_calc, combinatorial_formula, boundary_precision_check
plus corner calculations (payment waterfall, referral snapshot).
"""
import pytest

from test_helpers import (
    validate_success, TEST_USERS,
    setup_owner_vehicle_case, setup_case_with_violations, file_violation, file_dispute,
    get_case, set_clock, make_owner_headers,
)

EO = TEST_USERS["enforcement_officer_headers"]
COLLECTIONS = TEST_USERS["collections_admin_headers"]


# ─── dual_variant_calc / assessed_vs_collectible_balance ───────────────────

def _assessed_collectible_case():
    """One case: v1 30000 OUTSTANDING, v2 20000 -> DISPUTED. No late penalty."""
    owner, vehicle, case, violations = setup_case_with_violations(0, 0)
    v1 = file_violation(case["id"], fine_amount_cents=30000)
    v2 = file_violation(case["id"], fine_amount_cents=20000)
    file_dispute(v2["id"], owner["id"])
    return owner, case, v1, v2


def test_assessed_balance_includes_disputed_citation(api):
    """PRD §3.3: "balance (assessed_balance_cents) is the total exposure
    and sums the current due of every citation that is OUTSTANDING or DISPUTED."

    Design: Difficulty/dual_variant_calc/assessed_vs_collectible_balance
    """
    _, case, _, _ = _assessed_collectible_case()
    fresh = get_case(case["id"])
    assert fresh["assessed_balance_cents"] == 50000


def test_collectible_balance_excludes_disputed_citation(api):
    """PRD §3.3: "balance (collectible_balance_cents) is what the agency
    may currently collect and sums the current due of only the OUTSTANDING citations,
    excluding disputed ones entirely."

    Design: Difficulty/dual_variant_calc/assessed_vs_collectible_balance
    """
    _, case, _, _ = _assessed_collectible_case()
    fresh = get_case(case["id"])
    assert fresh["collectible_balance_cents"] == 30000
    assert fresh["collectible_balance_cents"] != fresh["assessed_balance_cents"]


# ─── combinatorial_formula / late_penalty_round_each_then_sum ──────────────

def _overdue_pair_case():
    """Two OUTSTANDING violations of 3333, due 2026-05-15, clock advanced to 2026-06-01."""
    owner, vehicle, case, violations = setup_case_with_violations(
        2, 3333, due_at="2026-05-15T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    return case, violations


def test_collectible_rounds_late_penalty_per_violation_then_sums(api):
    """PRD §2.6: "Where a rule requires summing several rounded quantities (for example,
    a late penalty computed for each of several violations), the rounding is applied to
    each per-violation quantity first and the rounded quantities are then summed; the
    system never sums raw fines first and applies the rate to the aggregate."

    Design: Difficulty/combinatorial_formula/late_penalty_round_each_then_sum
    """
    case, _ = _overdue_pair_case()
    fresh = get_case(case["id"])
    # per violation: round_half_up(3333*0.25)=833; current_due=4166; sum=8332
    assert fresh["collectible_balance_cents"] == 8332


def test_late_penalty_per_violation_value(api):
    """PRD §3.2: "is 25% of the fine (LATE_PENALTY_PCT is 0.25), rounded
    half up, but only once the logical clock has reached or passed the violation's due_at
    and only while the violation is in OUTSTANDING or DISPUTED status;"

    Design: Difficulty/combinatorial_formula/late_penalty_round_each_then_sum
    """
    case, violations = _overdue_pair_case()
    for v in violations:
        fresh = validate_success(api.get_violation(v["id"], EO), 200)
        assert fresh["late_penalty_cents"] == 833


# ─── boundary_precision_check / scofflaw_amount_threshold_boundary ─────────

def test_collectible_exactly_at_amount_threshold_becomes_scofflaw(api):
    """PRD §2.7: "A case becomes a scofflaw when its collectible balance reaches at least
    50,000 cents (five hundred dollars) — the SCOFFLAW_AMOUNT_THRESHOLD_CENTS — or when
    its outstanding_count reaches at least five outstanding citations"

    Design: Difficulty/boundary_precision_check/scofflaw_amount_threshold_boundary
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=25000)
    file_violation(case["id"], fine_amount_cents=25000)
    fresh = get_case(case["id"])
    assert fresh["collectible_balance_cents"] == 50000
    assert fresh["case_status"] == "SCOFFLAW"


def test_collectible_one_below_amount_threshold_stays_compliant(api):
    """PRD §2.7: "The program's coercive powers switch on at fixed breakpoints, all
    evaluated inclusively (a case exactly at a breakpoint has crossed it)."

    Design: Difficulty/boundary_precision_check/scofflaw_amount_threshold_boundary
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=25000)
    file_violation(case["id"], fine_amount_cents=24999)  # total 49999, count 2
    fresh = get_case(case["id"])
    assert fresh["collectible_balance_cents"] == 49999
    assert fresh["case_status"] == "COMPLIANT"


# ─── corner: payment waterfall oldest-first ────────────────────────────────

def test_payment_waterfall_pays_oldest_citation_first(api):
    """PRD §3.4: "The payment is allocated by a waterfall across the case's OUTSTANDING
    citations, processed oldest first: candidates are ordered by issued_at ascending,
    ties broken by created_at ascending — never by id."

    Design: Corner/calculations/payment_waterfall_oldest_first
    """
    owner, _, case = setup_owner_vehicle_case()
    v1 = file_violation(case["id"], fine_amount_cents=10000, issued_at="2026-05-01T00:00:00Z")
    v2 = file_violation(case["id"], fine_amount_cents=10000, issued_at="2026-05-10T00:00:00Z")
    validate_success(api.create_payment(
        case["id"], {"amount_cents": 10000, "method": "CASH"},
        make_owner_headers(owner["id"])), 201)
    assert validate_success(api.get_violation(v1["id"], EO), 200)["status"] == "PAID"
    assert validate_success(api.get_violation(v2["id"], EO), 200)["status"] == "OUTSTANDING"
    assert get_case(case["id"])["collectible_balance_cents"] == 10000


# ─── corner: referral snapshot + IN_COLLECTIONS ────────────────────────────

def test_referral_snapshots_collectible_and_moves_to_in_collections(api):
    """PRD §3.9: "Referral creates a CollectionsReferral in REFERRED status, snapshots
    referred_amount_cents from the case's collectible balance at that instant, records
    referred_at, moves every OUTSTANDING citation on the case to IN_COLLECTIONS,
    recomputes the balances (collectible now excludes those citations)"

    Design: Corner/calculations/referral_amount_snapshot_and_in_collections
    """
    _, _, case, _ = setup_case_with_violations(5, 12000)
    set_clock("2026-08-01T00:00:00Z")  # oldest citation now >= 90 days old
    referral = validate_success(api.create_collections_referral(
        case["id"], {"agency_name": "ACME Collections"}, COLLECTIONS), 201)
    assert referral["referred_amount_cents"] == 60000
    assert referral["status"] == "REFERRED"
    assert get_case(case["id"])["collectible_balance_cents"] == 0
