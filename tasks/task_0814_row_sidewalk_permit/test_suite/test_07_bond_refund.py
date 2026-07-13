"""Restoration-bond refund waterfall: the provisional preview at
request-restoration, the authoritative final refund at release, and the
money-conservation invariant."""
from test_helpers import (
    get_success_data,
    TEST_USERS,
    assert_bond_money_conserved,
    fixtures,
)

REVIEWER_1 = TEST_USERS["reviewer_headers"]


def test_provisional_refund_recomputed_on_request_restoration(api):
    """PRD §3.7: "The **provisional variant** is recomputed each time a closure
    enters `RESTORATION_PENDING` via a restoration request: it sums the
    `estimated_deficiency_cents` of the permit's closures currently in
    `RESTORATION_PENDING`, and its result is stored as the bond's
    `provisional_refund_cents` as a preview."

    Design: Difficulty/dual_variant_calc/bond_provisional_vs_final_refund_on_bond
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api, posted_cents=80000)
    fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 10000)
    bonds = get_success_data(api.list_bond(ctx["permit_id"], REVIEWER_1))
    assert bonds[0]["provisional_refund_cents"] == 70000


def test_final_refund_and_forfeit_on_release(api):
    """PRD §3.7: "The **final variant** is computed at bond release: it sums the
    `assessed_deficiency_cents` of the permit's closures in `RESTORED`, and its
    result is stored as the bond's `refunded_cents`, with `forfeited_cents` set to
    `posted_cents` minus that refund."

    Design: Difficulty/dual_variant_calc/bond_provisional_vs_final_refund_on_bond
    """
    ctx = fixtures.setup_closure_signed_off_ready_for_release(
        api, posted_cents=80000, estimated_deficiency_cents=10000, assessed_deficiency_cents=25000
    )
    released = get_success_data(api.release_bond(ctx["bond_id"], REVIEWER_1))
    assert released["refunded_cents"] == 55000
    assert released["forfeited_cents"] == 25000


def test_bond_release_conserves_money(api):
    """PRD §3.3: "Across a bond's life the invariant `held_cents` plus
    `refunded_cents` plus `forfeited_cents` always equals the original
    `posted_cents`."

    Design: Difficulty/compensating_invariant/bond_money_conservation_on_release
    """
    ctx = fixtures.setup_closure_signed_off_ready_for_release(
        api, posted_cents=80000, estimated_deficiency_cents=10000, assessed_deficiency_cents=25000
    )
    released = get_success_data(api.release_bond(ctx["bond_id"], REVIEWER_1))
    assert released["posted_cents"] == 80000
    assert released["refunded_cents"] == 55000
    assert released["forfeited_cents"] == 25000


def test_bond_release_sets_held_to_zero_and_balances(api):
    """PRD §3.7: "On release the final refund is computed as above,
    `forfeited_cents` is set to `posted_cents` minus `refunded_cents`, and
    `held_cents` is set to 0."

    Design: Difficulty/compensating_invariant/bond_money_conservation_on_release
    """
    ctx = fixtures.setup_closure_signed_off_ready_for_release(
        api, posted_cents=80000, estimated_deficiency_cents=10000, assessed_deficiency_cents=25000
    )
    released = get_success_data(api.release_bond(ctx["bond_id"], REVIEWER_1))
    assert released["held_cents"] == 0
    assert_bond_money_conserved(released)
