"""Tests for the two conserved quantities of PRD 2.8 across their compensating actions.

The party-pair restricted corpus is unchanged by executing a restricted-fund
transfer and by unwinding one (PRD 2.8, PRD 3.6), and the deal's seat ledger -
reserved_seat_pool plus the allocated_seats of every certified resolution -
always equals combined_board_seats across certification and rescission (PRD 2.8,
PRD 3.5). Both are read from the reconciliation dossier of PRD 3.9.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field,
    assert_money_equals,
    assert_null,
    assert_pair_corpus_equals,
    assert_seat_ledger_conserved,
)
from test_helpers.test_users import PLATFORM_ADMIN, make_board_secretary_headers

FUND_VALUE_CENTS = 62000000  # principal 50000000 plus appreciation 12000000


def _deal_with_a_granted_fund_and_a_held_continuity_task(api):
    """A STRUCTURE_SELECTED deal, a CONSENT_GRANTED fund and a HELD continuity task.

    The single CONSENT_GRANTED party fund leaves the deal RESTRICTED_PENDING per
    PRD 3.6, which is what makes the PROGRAM_CONTINUITY task of PRD 3.8 land HELD.
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    ctx["fund"] = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    ctx["task"] = fx.create_task(
        api,
        deal_id,
        workstream="PROGRAM_CONTINUITY",
        crew_code="CREW-PROG1",
        title="Rebadge afterschool sites",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )
    assert_field(ctx["task"], "status", "HELD")
    return ctx


def test_pair_restricted_corpus_is_identical_before_transfer_after_transfer_and_after_unwind(api):
    """The two parties' restricted corpus total is the same at all three instants.

    PRD 2.8 names the party-pair restricted corpus as conserved: "the sum of
    restricted_corpus_cents across a deal's two party organizations is unchanged by
    executing a restricted-fund transfer and by unwinding one, because a transfer
    only moves value from the holder's retained side to the recipient's received
    side of the same total". PRD 3.9 exposes that sum as the dossier's
    pair_restricted_corpus_cents. The fund holds principal 50000000 plus
    appreciation 12000000, so the conserved total is 62000000 cents throughout.

    Design: Difficulty/compensating_invariant/transfer_then_unwind_conserves_the_pair_restricted_corpus
    """
    ctx = _deal_with_a_granted_fund_and_a_held_continuity_task(api)
    deal_id = ctx["deal"]["id"]

    before = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(before, FUND_VALUE_CENTS)

    fx.transfer_fund(api, ctx["fund"]["id"], deal_id, "DONOR_CONSENT")
    after_transfer = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(after_transfer, FUND_VALUE_CENTS)

    fx.unwind_fund(api, ctx["fund"]["id"])
    after_unwind = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(after_unwind, FUND_VALUE_CENTS)

    assert (
        before["pair_restricted_corpus_cents"] == after_unwind["pair_restricted_corpus_cents"]
    ), "the unwind must restore the pair corpus to its pre-transfer value exactly"


def test_unwind_restores_the_fund_row_and_both_party_corpora(api):
    """Unwinding returns the fund to its pre-transfer branch state and both corpus figures.

    PRD 3.6 states that a fund transferred on DONOR_CONSENT returns "TRANSFERRED ->
    CONSENT_GRANTED", that the unwind "clears transferred_to_org_id,
    transfer_restructuring_id and transfer_basis to null, sets
    transferred_amount_cents and retained_amount_cents both to 0, and increases
    unwind_count by one", that it "deliberately leaves transferable_amount_cents at
    its pre-transfer value, so a re-transfer releases the identical amount", and
    that "both parties' restricted_corpus_cents are recomputed and land back on
    their exact pre-transfer values".

    Design: Difficulty/compensating_invariant/transfer_then_unwind_conserves_the_pair_restricted_corpus
    """
    ctx = _deal_with_a_granted_fund_and_a_held_continuity_task(api)
    deal_id = ctx["deal"]["id"]
    fx.transfer_fund(api, ctx["fund"]["id"], deal_id, "DONOR_CONSENT")

    unwound = fx.unwind_fund(api, ctx["fund"]["id"])

    assert_field(unwound, "transfer_status", "CONSENT_GRANTED")
    assert_money_equals(
        unwound["transferable_amount_cents"], FUND_VALUE_CENTS, "transferable_amount_cents"
    )
    assert_money_equals(unwound["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_money_equals(unwound["retained_amount_cents"], 0, "retained_amount_cents")
    assert_field(unwound, "unwind_count", 1)
    assert_null(unwound, "transferred_to_org_id")
    assert_null(unwound, "transfer_restructuring_id")
    assert_null(unwound, "transfer_basis")

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_money_equals(
        org_a["restricted_corpus_cents"], FUND_VALUE_CENTS, "org_a.restricted_corpus_cents"
    )
    assert_money_equals(org_b["restricted_corpus_cents"], 0, "org_b.restricted_corpus_cents")


def test_unwind_returns_the_program_continuity_task_to_held(api):
    """The unwind reverts the posture and pulls the released continuity task back to HELD.

    PRD 3.6 states that on an unwind "the deal's unresolved_restricted_fund_count
    and restricted_asset_posture are recomputed, reverting CLEARED ->
    RESTRICTED_PENDING; and every integration task of that deal whose workstream is
    PROGRAM_CONTINUITY and whose status is PLANNED returns PLANNED -> HELD with
    held_reason set to RESTRICTED_ASSETS_UNRESOLVED". The transfer had released
    that very task under hop four of the same section.

    Design: Difficulty/compensating_invariant/transfer_then_unwind_conserves_the_pair_restricted_corpus
    """
    ctx = _deal_with_a_granted_fund_and_a_held_continuity_task(api)
    deal_id = ctx["deal"]["id"]

    fx.transfer_fund(api, ctx["fund"]["id"], deal_id, "DONOR_CONSENT")
    released = validate_success(api.get_integration_task(ctx["task"]["id"], PLATFORM_ADMIN))
    assert_field(released, "status", "PLANNED")
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "CLEARED")

    fx.unwind_fund(api, ctx["fund"]["id"])

    task = validate_success(api.get_integration_task(ctx["task"]["id"], PLATFORM_ADMIN))
    assert_field(task, "status", "HELD")
    assert_field(task, "held_reason", "RESTRICTED_ASSETS_UNRESOLVED")

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")
    assert_field(deal, "unresolved_restricted_fund_count", 1)


def _certify_both_boards(api, ctx):
    """Certify the initiator's and then the target's RECORDED resolution."""
    ctx["approval_initiator"] = validate_success(
        api.certify_board_approval(
            ctx["approval_initiator"]["id"],
            f.certify_payload(
                fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"
            ),
            make_board_secretary_headers(ctx["org_a"]["id"]),
        )
    )
    ctx["approval_target"] = validate_success(
        api.certify_board_approval(
            ctx["approval_target"]["id"],
            f.certify_payload(
                fiduciary_memo_ref="MEMO-B-1", certifying_secretary_ref="SEC-B-2"
            ),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        )
    )
    return ctx


def test_seat_ledger_total_holds_across_certification_and_rescission(api):
    """The seat ledger equals combined_board_seats before, between and after the compensation.

    PRD 2.8 states that "the sum of reserved_seat_pool and the allocated_seats of
    every certified board approval of that deal always equals
    combined_board_seats, from the moment a letter is executed onward". PRD 3.5
    draws the initiator's 8 seats and the target's combined_board_seats less that
    split, 7, out of the pool at certification, and rescission "returns its
    allocated_seats to reserved_seat_pool", so the pool reads 15, then 0, then 7
    while the ledger total stays at 15.

    Design: Difficulty/compensating_invariant/certify_then_rescind_conserves_the_seat_ledger_total
    """
    ctx = fx.setup_deal_board_approval(api)
    deal_id = ctx["deal"]["id"]

    before = fx.dossier(api, deal_id)
    assert_seat_ledger_conserved(before)
    assert_field(before, "reserved_seat_pool", 15)
    assert_field(before, "certified_allocated_seats_total", 0)
    assert_field(before, "seat_ledger_total", 15)

    ctx = _certify_both_boards(api, ctx)
    between = fx.dossier(api, deal_id)
    assert_seat_ledger_conserved(between)
    assert_field(between, "reserved_seat_pool", 0)
    assert_field(between, "certified_allocated_seats_total", 15)
    assert_field(between, "seat_ledger_total", 15)

    validate_success(
        api.rescind_board_approval(
            ctx["approval_target"]["id"],
            f.rescind_payload(),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        )
    )
    after = fx.dossier(api, deal_id)
    assert_seat_ledger_conserved(after)
    assert_field(after, "reserved_seat_pool", 7)
    assert_field(after, "certified_allocated_seats_total", 8)
    assert_field(after, "seat_ledger_total", 15)


def test_rescission_returns_exactly_the_seats_it_drew_and_resets_governance_seats(api):
    """Rescission returns the target's 7 seats and zeroes that party's governance seats only.

    PRD 3.5 allocates the target "the deal's combined_board_seats less that same
    board_seat_split_initiator", writing the figure to allocated_seats, subtracting
    it from reserved_seat_pool and writing it to governance_seats on the approving
    party's organization. Rescission "moves the resolution CERTIFIED -> RESCINDED,
    returns its allocated_seats to reserved_seat_pool, zeroes its own
    allocated_seats, and resets governance_seats to 0 on that party", leaving the
    initiator's certified 8 seats untouched.

    Design: Difficulty/compensating_invariant/certify_then_rescind_conserves_the_seat_ledger_total
    """
    ctx = fx.setup_deal_board_approval(api)
    deal_id = ctx["deal"]["id"]
    ctx = _certify_both_boards(api, ctx)

    assert_field(ctx["approval_initiator"], "status", "CERTIFIED")
    assert_field(ctx["approval_initiator"], "allocated_seats", 8)
    assert_field(ctx["approval_target"], "status", "CERTIFIED")
    assert_field(ctx["approval_target"], "allocated_seats", 7)

    rescinded = validate_success(
        api.rescind_board_approval(
            ctx["approval_target"]["id"],
            f.rescind_payload(),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        )
    )

    assert_field(rescinded, "status", "RESCINDED")
    assert_field(rescinded, "allocated_seats", 0)

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_field(org_a, "governance_seats", 8)
    assert_field(org_b, "governance_seats", 0)

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "reserved_seat_pool", 7)
    assert_field(deal, "combined_board_seats", 15)


def test_rescission_reverts_the_deal_from_regulatory_review_to_board_approval(api):
    """Losing one certification reverts the deal's own progression as well as the ledger.

    PRD 3.5 advances the deal "BOARD_APPROVAL -> REGULATORY_REVIEW" once both
    INITIATOR and TARGET hold a CERTIFIED resolution, and on rescission states that
    "because the both-parties-certified condition no longer holds, a deal sitting in
    REGULATORY_REVIEW reverts REGULATORY_REVIEW -> BOARD_APPROVAL". Both parties are
    incorporated in CA, one of the five attorney-general review states of PRD 3.2,
    so ag_review_required is true and the deal does rest in REGULATORY_REVIEW.

    Design: Difficulty/compensating_invariant/certify_then_rescind_conserves_the_seat_ledger_total
    """
    ctx = fx.setup_deal_board_approval(api)
    deal_id = ctx["deal"]["id"]
    ctx = _certify_both_boards(api, ctx)
    assert_field(fx.read_deal(api, deal_id), "status", "REGULATORY_REVIEW")

    validate_success(
        api.rescind_board_approval(
            ctx["approval_target"]["id"],
            f.rescind_payload(),
            make_board_secretary_headers(ctx["org_b"]["id"]),
        )
    )

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "status", "BOARD_APPROVAL")
    assert_seat_ledger_conserved(fx.dossier(api, deal_id))
