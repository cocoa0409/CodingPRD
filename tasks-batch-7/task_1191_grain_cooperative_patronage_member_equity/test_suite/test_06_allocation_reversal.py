"""Allocation reversal cascades and patronage-pool conservation
(PRD §2.9, §3.3)."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_year_with_deliveries, close_year_provisional, get_fiscal_year,
    get_allocation_for_member, list_member_certificates, get_member,
    TEST_USERS,
)

ACCOUNTANT = TEST_USERS["accountant_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

# Two equal-volume members, pool = round_half_up(100000 * 0.80) = 80000.
# Each share is exactly 0.5, so each gross allocation is exactly 40000:
# qualified slice round(40000 * 1.00 * 0.70) = 28000; cash round(28000*0.40)
# = 11200; qualified equity 16800; nonqualified 12000.


def _two_member_provisional_year():
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "m_a", "commodity": "CORN", "gross_bushels": 500},
            {"member_key": "m_b", "commodity": "CORN", "gross_bushels": 500},
        ],
        net_margin_cents=100000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.40,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    ctx["fiscal_year"] = fy
    return ctx


def test_reverse_allocation_keeps_pool_total(api):
    """PRD §3.3: "The provisional close first computes `patronage_pool_cents`:
    the year's `net_margin_cents` multiplied by one minus the
    `retained_reserve_pct`, rounded half-up to whole cents."
    PRD §3.3: "Reversal moves the allocation to `REVERSED`, revokes the
    certificates it produced (they move to `REVOKED` and their
    `outstanding_cents` is zeroed), and recomputes the member's equity
    balances."

    Design: Difficulty/compensating_invariant/patronage_pool_conservation_across_allocation_reverse
    """
    ctx = _two_member_provisional_year()
    fy = ctx["fiscal_year"]
    assert fy["patronage_pool_cents"] == 80000
    alloc_a = get_allocation_for_member(
        fy["id"], ctx["members"]["m_a"]["id"],
    )
    reversed_alloc = validate_success(
        api.reverse_allocation(alloc_a["id"], {"reason": "audit correction"},
                               ACCOUNTANT),
    )
    assert reversed_alloc["status"] == "REVERSED"
    after = get_fiscal_year(fy["id"])
    assert after["patronage_pool_cents"] == 80000, (
        "Pool total is a function of net margin and reserve; reversal must "
        f"not change it (got {after['patronage_pool_cents']})"
    )


def test_reverse_allocation_leaves_other_member_unchanged(api):
    """PRD §2.9: "For each fiscal year in `CLOSED_FINAL`, the sum over all
    allocations whose status is not `REVERSED` of each allocation's
    `cash_paid_cents` plus `qualified_equity_issued_cents` plus
    `nonqualified_allocation_cents` must equal the year's
    `patronage_pool_cents` exactly. Any reversal or amendment must re-balance
    the year's allocations so this equality continues to hold to the cent."

    Design: Difficulty/compensating_invariant/patronage_pool_conservation_across_allocation_reverse
    """
    ctx = _two_member_provisional_year()
    fy = ctx["fiscal_year"]
    alloc_a = get_allocation_for_member(
        fy["id"], ctx["members"]["m_a"]["id"],
    )
    validate_success(
        api.reverse_allocation(alloc_a["id"], {"reason": "audit correction"},
                               ACCOUNTANT),
    )
    alloc_b = get_allocation_for_member(
        fy["id"], ctx["members"]["m_b"]["id"],
    )
    # Equal shares: the untouched member's slices must not drift.
    assert alloc_b["status"] == "PROVISIONAL"
    assert alloc_b["cash_paid_cents"] == 11200
    assert alloc_b["qualified_equity_issued_cents"] == 16800
    assert alloc_b["nonqualified_allocation_cents"] == 12000


def test_reverse_allocation_revokes_certificates(api):
    """PRD §3.3: "Reversal moves the allocation to `REVERSED`, revokes the
    certificates it produced (they move to `REVOKED` and their
    `outstanding_cents` is zeroed), and recomputes the member's equity
    balances."

    Design: Difficulty/transitive_cascade/allocation_reversal_cascades_to_tax_form_void
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "solo", "commodity": "CORN", "gross_bushels": 500}],
        net_margin_cents=100000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.30,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    member = ctx["members"]["solo"]
    alloc = get_allocation_for_member(fy["id"], member["id"])
    certs = list_member_certificates(member["id"])
    assert len(certs) >= 1
    reversed_alloc = validate_success(
        api.reverse_allocation(alloc["id"], {"reason": "audit error"},
                               ACCOUNTANT),
    )
    assert reversed_alloc["status"] == "REVERSED"
    data, _ = validate_paginated(
        api.list_member_certificates(member["id"], TREASURER),
    )
    assert len(data) == len(certs)
    for cert in data:
        assert cert["status"] == "REVOKED", (
            f"Certificate {cert['id']} must be REVOKED, got {cert['status']}"
        )
        assert cert["outstanding_cents"] == 0, (
            f"Revoked certificate {cert['id']} must be zeroed, got "
            f"{cert['outstanding_cents']}"
        )


def test_reverse_allocation_recomputes_member_equity(api):
    """PRD §3.3: "Reversal moves the allocation to `REVERSED`, revokes the
    certificates it produced (they move to `REVOKED` and their
    `outstanding_cents` is zeroed), and recomputes the member's equity
    balances."

    Design: Difficulty/transitive_cascade/allocation_reversal_cascades_to_tax_form_void
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "solo", "commodity": "CORN", "gross_bushels": 500}],
        net_margin_cents=100000, retained_reserve_pct=0.20,
        qualified_payout_pct=0.30,
    )
    fy = close_year_provisional(ctx["fiscal_year"]["id"])
    member = ctx["members"]["solo"]
    alloc = get_allocation_for_member(fy["id"], member["id"])
    validate_success(
        api.reverse_allocation(alloc["id"], {"reason": "audit error"},
                               ACCOUNTANT),
    )
    after = get_member(member["id"])
    assert after["qualified_equity_cents"] == 0, (
        "With every certificate REVOKED, qualified equity must be 0; got "
        f"{after['qualified_equity_cents']}"
    )
    assert after["nonqualified_equity_cents"] == 0, (
        "With every certificate REVOKED, nonqualified equity must be 0; got "
        f"{after['nonqualified_equity_cents']}"
    )
