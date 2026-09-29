"""Cross-cutting compliance tests: version pinning and derived-field reconciliation.

Every test in this module builds its own preconditions through the API, because
the harness restarts the server and empties the database before each test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STALE_RESTRUCTURING_VERSION
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_money_equals,
    assert_pair_corpus_equals,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def test_letter_of_intent_occ_pins_the_deal_version_the_writer_saw(api):
    """Letter issuance pins the deal version: a token from before the previous letter is
    stale, a withdrawal of that letter leaves the token current because it touches only the
    letter row, and the successful issuance then invalidates the token it consumed.

    PRD 2.5 says POST /letters-of-intent carries "expected_restructuring_version", which must
    equal the deal's current version, and a mismatch is refused with
    ERR_STALE_RESTRUCTURING_VERSION while the request "increments nothing and mutates nothing";
    the pin is evaluated once per request. PRD 3.3 says withdrawal "touches only the letter row
    and its version", moving the letter to WITHDRAWN with "exclusivity_status set to RELEASED",
    and that a newly issued letter lands "with status ISSUED, exclusivity_status ACTIVE,
    counter_round_count at 0" and "copies the deal's current round_no into its own round_no",
    while "the deal's version rises by exactly one for the request". PRD 3.3 also derives
    "exclusivity_end_date is exclusivity_start_date advanced by exclusivity_days minus one
    calendar day" with "expires_at renders that end date at 00:00:00.000Z", and exempts "a
    repeat window with the same counterparty" from the cooling-off period entirely.

    Design: Corner/cross_cutting_complexity_layers/letter_of_intent_occ_pins_the_deal_version_the_writer_saw
    """
    ctx = fx.setup_deal_rationale_built(api)
    org_a, deal_id = ctx["org_a"], ctx["deal"]["id"]
    so_a = make_strategy_officer_headers(org_a["id"])
    rv_a = fx.deal_version(api, deal_id)
    loi = validate_success(
        api.create_letter_of_intent(f.letter_of_intent_payload(deal_id, rv_a), so_a), 201
    )

    validate_error(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal_id, rv_a, board_seat_split_initiator=9, exclusivity_days=45
            ),
            so_a,
        ),
        ERR_STALE_RESTRUCTURING_VERSION,
    )
    v2 = fx.deal_version(api, deal_id)
    assert v2 == 3, f"the refused issuance incremented nothing, expected version 3, got {v2}"
    rows, _meta = validate_paginated(api.list_deal_letters_of_intent(deal_id, so_a))
    assert len(rows) == 1, f"the refusal created no letter, got {len(rows)} rows"

    withdrawn = validate_success(
        api.withdraw_letter_of_intent(
            loi["id"],
            f.withdraw_payload(withdrawal_reason="Seat split reopened by the initiator board"),
            so_a,
        )
    )
    assert_field(withdrawn, "status", "WITHDRAWN")
    assert_field(withdrawn, "exclusivity_status", "RELEASED")
    assert_version_is(withdrawn, 2, "letter of intent")
    v3 = fx.deal_version(api, deal_id)
    assert v3 == v2, f"a letter-only write leaves the deal token at {v2}, got {v3}"

    loi2 = validate_success(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal_id, v3, board_seat_split_initiator=9, exclusivity_days=45
            ),
            so_a,
        ),
        201,
    )
    assert_field(loi2, "status", "ISSUED")
    assert_field(loi2, "exclusivity_status", "ACTIVE")
    assert_field(loi2, "round_no", 1)
    assert_field(loi2, "counter_round_count", 0)
    assert_field(loi2, "exclusivity_end_date", "2026-09-14")
    assert_field(loi2, "expires_at", "2026-09-14T00:00:00.000Z")

    validate_error(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal_id, v3, board_seat_split_initiator=9, exclusivity_days=45
            ),
            so_a,
        ),
        ERR_STALE_RESTRUCTURING_VERSION,
    )
    v4 = fx.deal_version(api, deal_id)
    assert v4 == v3 + 1, f"exactly one increment for the one successful parent write, got {v4}"
    rows_after, _meta_after = validate_paginated(api.list_deal_letters_of_intent(deal_id, so_a))
    assert len(rows_after) == 2, f"the deal holds exactly two letters, got {len(rows_after)}"
    assert_field(fx.read_deal(api, deal_id), "status", "LOI_NEGOTIATION")


def test_board_approval_occ_pins_the_deal_version_the_board_deliberated_over(api):
    """Board approval recording pins the deal version, so the second board to write on a token
    read before the first board voted is refused as stale, and each successful write moves the
    deal version by exactly one even when it also drives a status transition.

    PRD 2.5 says POST /board-approvals carries "expected_restructuring_version", evaluated once
    per request against the deal's current version, and a mismatch answers
    ERR_STALE_RESTRUCTURING_VERSION while the request "increments nothing and mutates nothing".
    PRD 3.5 derives the tally: "eligible_seats is seats_total less recusals", "votes_cast is
    votes_for plus votes_against", "approval_ratio is votes_for divided by votes_cast, rounded
    half up to four decimal places", required_ratio "0.6667 for a MERGER", and the comparison is
    inclusive, "so a merger carried eight votes to four yields 0.6667 and passes"; an APPROVED
    decision lands the resolution in RECORDED. It also says "Recording the deal's first
    resolution advances it STRUCTURE_SELECTED to BOARD_APPROVAL; recording a later resolution
    for the same approving_party supersedes that party's prior resolution in RECORDED or
    CERTIFIED, returning its allocated_seats to reserved_seat_pool", and that "Either way the
    deal's version rises by exactly one for the request". PRD 3.3 seeds reserved_seat_pool from
    the executed letter's combined_board_seats, and PRD 2.8 conserves that ledger, so with no
    certification the pool stays whole.

    Design: Corner/cross_cutting_complexity_layers/board_approval_occ_pins_the_deal_version_the_board_deliberated_over
    """
    ctx = fx.setup_deal_structure_selected(api)
    org_a, org_b, deal_id = ctx["org_a"], ctx["org_b"], ctx["deal"]["id"]
    sec_a = make_board_secretary_headers(org_a["id"])
    sec_b = make_board_secretary_headers(org_b["id"])

    v1 = fx.deal_version(api, deal_id, sec_a)
    assert v1 == 6, f"the deal reaches STRUCTURE_SELECTED on version 6, got {v1}"
    ba_1 = validate_success(
        api.create_board_approval(f.board_approval_payload(deal_id, v1, "INITIATOR"), sec_a), 201
    )
    assert_field(ba_1, "status", "RECORDED")
    assert_field(ba_1, "decision", "APPROVED")
    assert_decimal_equals(ba_1["approval_ratio"], 0.7143, 4, "approval_ratio")
    assert_field(fx.read_deal(api, deal_id), "status", "BOARD_APPROVAL")
    v2 = fx.deal_version(api, deal_id, sec_b)
    assert v2 == v1 + 1, (
        f"the create and its status transition are one increment, expected {v1 + 1}, got {v2}"
    )

    target_payload = dict(
        seats_total=12,
        recusals=0,
        votes_for=8,
        votes_against=4,
        abstentions=0,
        conflict_disclosures_count=0,
        recording_secretary_ref="SEC-B-1",
    )
    validate_error(
        api.create_board_approval(
            f.board_approval_payload(deal_id, v1, "TARGET", **target_payload), sec_b
        ),
        ERR_STALE_RESTRUCTURING_VERSION,
    )
    rows, _meta = validate_paginated(api.list_deal_board_approvals(deal_id, sec_b))
    assert len(rows) == 1, f"the stale target vote created nothing, got {len(rows)} rows"
    assert fx.deal_version(api, deal_id, sec_b) == v2, "the refusal left the deal version alone"

    ba_2 = validate_success(
        api.create_board_approval(
            f.board_approval_payload(deal_id, v2, "TARGET", **target_payload), sec_b
        ),
        201,
    )
    assert_field(ba_2, "status", "RECORDED")
    assert_decimal_equals(ba_2["approval_ratio"], 0.6667, 4, "approval_ratio")

    revote_payload = dict(
        seats_total=15,
        recusals=0,
        votes_for=12,
        votes_against=3,
        abstentions=0,
        conflict_disclosures_count=0,
        recording_secretary_ref="SEC-A-3",
    )
    validate_error(
        api.create_board_approval(
            f.board_approval_payload(deal_id, v2, "INITIATOR", **revote_payload), sec_a
        ),
        ERR_STALE_RESTRUCTURING_VERSION,
    )
    v3 = fx.deal_version(api, deal_id, sec_a)
    assert v3 == v2 + 1, f"only the target's successful vote incremented, expected {v2 + 1}, got {v3}"

    ba_3 = validate_success(
        api.create_board_approval(
            f.board_approval_payload(deal_id, v3, "INITIATOR", **revote_payload), sec_a
        ),
        201,
    )
    assert_field(ba_3, "status", "RECORDED")
    assert_decimal_equals(ba_3["approval_ratio"], 0.8000, 4, "approval_ratio")
    v4 = fx.deal_version(api, deal_id, sec_a)
    assert v4 == v3 + 1, f"three successful writes from {v1}, expected {v3 + 1}, got {v4}"

    final_rows, _final_meta = validate_paginated(api.list_deal_board_approvals(deal_id, sec_a))
    assert len(final_rows) == 3, f"the deal holds exactly three resolutions, got {len(final_rows)}"
    superseded = find_by_id(final_rows, ba_1["id"])
    assert_field(superseded, "status", "SUPERSEDED")
    assert_field(superseded, "allocated_seats", 0)
    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "reserved_seat_pool", 15)
    assert_field(deal, "status", "BOARD_APPROVAL")


def test_restricted_corpus_reconciles_after_create_transfer_unwind_and_retransfer(api):
    """An organization's restricted corpus is recomputed from the three-part sum at every fund
    mutation, so it is right after registration, after a transfer moves value, after an unwind
    retracts that transfer and after the transfer is reapplied on both sides of the pair.

    PRD 3.1 says restricted_corpus_cents "is recomputed on every restricted-fund mutation" and
    "is the sum of three disjoint contributions": for a fund held by this organization whose
    transfer_status is anything other than TRANSFERRED, "principal_cents plus its
    accumulated_appreciation_cents"; for a held fund that is TRANSFERRED, "only that fund's
    retained_amount_cents"; and for any fund "whose recipient is this organization and whose
    transfer_status is TRANSFERRED, add that fund's transferred_amount_cents". PRD 3.6 fixes
    transferable_amount_cents on a granted consent "at the full fund value - principal_cents plus
    accumulated_appreciation_cents", writes on transfer "transferred_amount_cents equal to the
    previously fixed transferable_amount_cents, and retained_amount_cents equal to the fund value
    less what moved", and on unwind returns the fund "TRANSFERRED to CONSENT_GRANTED", clears the
    two amounts to 0, "increases unwind_count by one" and "deliberately leaves
    transferable_amount_cents at its pre-transfer value". Each of those two writes raises "the
    fund's version and the deal's version" by one and touches no deal status. PRD 3.6 counts as
    unresolved every party fund "whose transfer_status is neither TRANSFERRED nor RETAINED" and
    reads the posture as RESTRICTED_PENDING while that count exceeds zero and CLEARED once it
    reaches zero, and PRD 2.8 holds the pair total invariant throughout.

    Design: Corner/cross_cutting_complexity_layers/restricted_corpus_reconciles_after_create_transfer_unwind_and_retransfer
    """
    ctx = fx.setup_deal_structure_selected(api)
    org_a, org_b, deal_id = ctx["org_a"], ctx["org_b"], ctx["deal"]["id"]

    def corpus(org_id):
        org = validate_success(api.get_organization(org_id, PLATFORM_ADMIN))
        return org["restricted_corpus_cents"]

    f1 = fx.create_fund(
        api,
        org_a["id"],
        fund_name="Mentor Scholarship Fund",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        restriction_purpose_code="SC-SCHOLARSHIPS",
    )
    f2 = fx.create_fund(
        api,
        org_b["id"],
        fund_name="Harbor Family Bequest",
        principal_cents=20000000,
        accumulated_appreciation_cents=0,
        restriction_purpose_code="SC-FAMILY_SUPPORT",
    )
    assert_money_equals(corpus(org_a["id"]), 62000000, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 20000000, "target restricted_corpus_cents")
    dossier = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(dossier, 82000000)
    assert_field(dossier, "unresolved_restricted_fund_count", 2)
    assert_field(dossier, "restricted_asset_posture", "RESTRICTED_PENDING")

    validate_success(api.seek_consent(f1["id"], f.seek_consent_payload(), TRUST_COUNSEL))
    granted = validate_success(
        api.record_consent(f1["id"], f.record_consent_payload("GRANTED"), TRUST_COUNSEL)
    )
    assert_money_equals(granted["transferable_amount_cents"], 62000000, "transferable_amount_cents")
    assert_money_equals(corpus(org_a["id"]), 62000000, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 20000000, "target restricted_corpus_cents")

    before_transfer = fx.deal_version(api, deal_id)
    transferred = fx.transfer_fund(api, f1["id"], deal_id)
    assert_money_equals(transferred["transferred_amount_cents"], 62000000, "transferred_amount_cents")
    assert_money_equals(transferred["retained_amount_cents"], 0, "retained_amount_cents")
    assert_money_equals(corpus(org_a["id"]), 0, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 82000000, "target restricted_corpus_cents")
    dossier = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(dossier, 82000000)
    assert_field(dossier, "unresolved_restricted_fund_count", 1)
    assert_field(dossier, "restricted_asset_posture", "RESTRICTED_PENDING")
    assert fx.deal_version(api, deal_id) == before_transfer + 1, "the transfer is one deal increment"

    before_unwind = fx.deal_version(api, deal_id)
    unwound = fx.unwind_fund(api, f1["id"])
    assert_field(unwound, "transfer_status", "CONSENT_GRANTED")
    assert_money_equals(unwound["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_money_equals(unwound["retained_amount_cents"], 0, "retained_amount_cents")
    assert_field(unwound, "unwind_count", 1)
    assert_money_equals(unwound["transferable_amount_cents"], 62000000, "transferable_amount_cents")
    assert_money_equals(corpus(org_a["id"]), 62000000, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 20000000, "target restricted_corpus_cents")
    assert_field(fx.read_deal(api, deal_id), "unresolved_restricted_fund_count", 2)
    assert fx.deal_version(api, deal_id) == before_unwind + 1, "the unwind is one deal increment"

    validate_success(
        api.seek_consent(f2["id"], f.seek_consent_payload(consent_method="ELECTRONIC"), TRUST_COUNSEL)
    )
    validate_success(api.record_consent(f2["id"], f.record_consent_payload("GRANTED"), TRUST_COUNSEL))
    moved_back = fx.transfer_fund(api, f2["id"], deal_id)
    assert_field(moved_back, "transferred_to_org_id", org_a["id"])
    assert_money_equals(corpus(org_a["id"]), 82000000, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 0, "target restricted_corpus_cents")

    fx.transfer_fund(api, f1["id"], deal_id)
    assert_money_equals(corpus(org_a["id"]), 20000000, "initiator restricted_corpus_cents")
    assert_money_equals(corpus(org_b["id"]), 62000000, "target restricted_corpus_cents")
    dossier = fx.dossier(api, deal_id)
    assert_pair_corpus_equals(dossier, 82000000)
    assert_field(dossier, "unresolved_restricted_fund_count", 0)
    assert_field(dossier, "restricted_asset_posture", "CLEARED")
    assert_field(fx.read_deal(api, deal_id), "status", "STRUCTURE_SELECTED")
