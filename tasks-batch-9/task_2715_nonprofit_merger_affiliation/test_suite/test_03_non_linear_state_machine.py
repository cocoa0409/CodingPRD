"""Cyclic and fork-and-join state machines whose return state depends on history.

PRD 3.3 gives the letter of intent two independent state dimensions on one row
with a cyclic negotiation dimension. PRD 3.6 gives the restricted fund a
fork-and-join shape whose unwind return state is conditional on the branch the
fund actually travelled.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import TRUST_COUNSEL, make_strategy_officer_headers

ENDOWMENT = {
    "fund_type": "PERM_ENDOWMENT",
    "principal_cents": 50000000,
    "accumulated_appreciation_cents": 12000000,
    "historic_dollar_value_cents": 45000000,
    "restriction_purpose_code": "YM-MENTOR_STIPENDS",
}
JUDICIAL_RELEASE_CENTS = 20150000
FUND_VALUE_CENTS = 62000000


def _counter(api, ctx, note):
    return validate_success(
        api.counter_letter_of_intent(
            ctx["loi"]["id"],
            f.counter_payload(counter_note=note),
            make_strategy_officer_headers(ctx["org_b"]["id"]),
        )
    )


def _revise(api, ctx, split):
    return validate_success(
        api.revise_letter_of_intent(
            ctx["loi"]["id"],
            f.revise_payload(board_seat_split_initiator=split),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )


def test_two_counter_revise_laps_return_the_letter_to_issued(api):
    """Two full laps of the negotiation cycle end in ISSUED with a monotonic counter.

    PRD 3.3: "Countering an ISSUED letter with a counter_note advances it ISSUED ->
    COUNTERED, sets countered_by_party to TARGET, increases counter_round_count by
    one", and "The initiator organization revises a COUNTERED letter by supplying a
    new board_seat_split_initiator, which overwrites the stored value and returns the
    letter COUNTERED -> ISSUED ... The ISSUED -> COUNTERED -> ISSUED cycle may
    repeat as many times as the parties can stand." Revision "deliberately preserves
    the negotiation history": counter_round_count is left exactly as it was, so two
    laps leave it at 2 rather than resetting it, the second revision's split of 7
    overwrites the first revision's 9, and per PRD 2.4 the letter's version rises by
    exactly one on each of the four mutations to reach 5.

    Design: Difficulty/non_linear_state_machine/letter_of_intent_counter_revise_cycle_preserves_exclusivity_dimension
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    a.assert_field(ctx["loi"], "status", "ISSUED")
    a.assert_field(ctx["loi"], "counter_round_count", 0)

    lap1 = _counter(api, ctx, "Target seeks parity on the combined board")
    a.assert_field(lap1, "status", "COUNTERED")
    a.assert_field(lap1, "counter_round_count", 1)
    _revise(api, ctx, 9)
    lap2 = _counter(api, ctx, "Still short of parity")
    a.assert_field(lap2, "status", "COUNTERED")
    a.assert_field(lap2, "counter_round_count", 2)
    loi = _revise(api, ctx, 7)

    a.assert_field(loi, "status", "ISSUED")
    a.assert_field(loi, "counter_round_count", 2)
    a.assert_field(loi, "countered_by_party", "TARGET")
    a.assert_field(loi, "board_seat_split_initiator", 7)
    a.assert_version_is(loi, 5, "letter of intent")


def test_the_counter_revise_cycle_leaves_the_exclusivity_dimension_untouched(api):
    """Neither countering nor revising touches the confidentiality dimension of the letter.

    PRD 3.3: "a counter ... pointedly leaves exclusivity_status untouched at
    ACTIVE", and revision "deliberately preserves the negotiation history and the
    confidentiality clock: counter_round_count, exclusivity_start_date,
    exclusivity_end_date and exclusivity_status are all left exactly as they were."
    The window derived at issuance - "exclusivity_end_date is exclusivity_start_date
    advanced by exclusivity_days minus one calendar day", so 2026-08-01 plus 60 days
    minus one is 2026-09-29, rendered by expires_at at 00:00:00.000Z - therefore
    survives two full laps unchanged.

    Design: Difficulty/non_linear_state_machine/letter_of_intent_counter_revise_cycle_preserves_exclusivity_dimension
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    issued = ctx["loi"]
    a.assert_field(issued, "exclusivity_end_date", "2026-09-29")

    _counter(api, ctx, "Target seeks parity on the combined board")
    _revise(api, ctx, 9)
    _counter(api, ctx, "Still short of parity")
    loi = _revise(api, ctx, 7)

    a.assert_field(loi, "exclusivity_status", "ACTIVE")
    a.assert_field(loi, "exclusivity_start_date", "2026-08-01")
    a.assert_field(loi, "exclusivity_end_date", "2026-09-29")
    a.assert_field(loi, "exclusivity_end_date", issued["exclusivity_end_date"])
    a.assert_field(loi, "expires_at", "2026-09-29T00:00:00.000Z")
    a.assert_field(loi, "combined_board_seats", 15)


def test_the_counter_revise_cycle_never_touches_the_deal_row(api):
    """The negotiation cycle mutates only the letter, leaving the deal in LOI_NEGOTIATION.

    PRD 3.3: on countering, "The letter's own version rises by one; the deal row is
    not touched and stays in LOI_NEGOTIATION", and on revision "only the letter's
    version moves", "with the deal sitting in LOI_NEGOTIATION throughout". Two laps
    therefore leave the deal's status and its version - the pinning token of PRD 2.5
    - exactly where the issuance left them.

    Design: Difficulty/non_linear_state_machine/letter_of_intent_counter_revise_cycle_preserves_exclusivity_dimension
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    before = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(before, "status", "LOI_NEGOTIATION")

    _counter(api, ctx, "Target seeks parity on the combined board")
    _revise(api, ctx, 9)
    _counter(api, ctx, "Still short of parity")
    _revise(api, ctx, 7)

    after = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(after, "status", "LOI_NEGOTIATION")
    a.assert_version_is(after, before["version"], "restructuring")
    a.assert_field(after, "round_no", before["round_no"])


def test_countering_a_countered_letter_is_refused_on_the_negotiation_dimension(api):
    """A second counter without an intervening revision is refused as an invalid letter state.

    PRD 3.3: "a counter attempted against a letter that is not ISSUED, or whose
    window is no longer ACTIVE, answers ERR_INVALID_LETTER_STATE." The cycle only
    re-admits a counter once the initiator's revision has returned the letter
    COUNTERED -> ISSUED, so countering a COUNTERED letter is refused and the row is
    left as it was.

    Design: Difficulty/non_linear_state_machine/letter_of_intent_counter_revise_cycle_preserves_exclusivity_dimension
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    countered = _counter(api, ctx, "Target seeks parity on the combined board")
    a.assert_field(countered, "status", "COUNTERED")

    response = api.counter_letter_of_intent(
        ctx["loi"]["id"],
        f.counter_payload(counter_note="Target counters again"),
        make_strategy_officer_headers(ctx["org_b"]["id"]),
    )
    validate_error(response, err.ERR_INVALID_LETTER_STATE, 409)

    loi = _revise(api, ctx, 9)
    a.assert_field(loi, "status", "ISSUED")
    a.assert_field(loi, "counter_round_count", 1)
    a.assert_field(loi, "exclusivity_status", "ACTIVE")


def _judicial_fund(api, ctx):
    """Register a conflicted endowment at the initiator and walk it to MODIFIED."""
    fund = fx.create_fund(
        api,
        ctx["org_a"]["id"],
        fund_name="Jarvis Endowment",
        restriction_conflict=True,
        donor_of_record_reachable=True,
        **ENDOWMENT,
    )
    validate_success(api.seek_consent(fund["id"], f.seek_consent_payload(), TRUST_COUNSEL))
    denied = validate_success(
        api.record_consent(fund["id"], f.record_consent_payload("DENIED"), TRUST_COUNSEL)
    )
    a.assert_field(denied, "transfer_status", "CONSENT_DENIED")
    validate_success(api.file_petition(fund["id"], f.file_petition_payload(), TRUST_COUNSEL))
    modified = validate_success(
        api.record_court_decision(
            fund["id"],
            f.court_decision_payload(
                "GRANTED_WITH_CONDITIONS", modified_purpose_code="YM-YOUTH_PROGRAMS"
            ),
            TRUST_COUNSEL,
        )
    )
    a.assert_field(modified, "transfer_status", "MODIFIED")
    return modified


def test_unwinding_a_judicial_transfer_returns_the_fund_to_modified(api):
    """A fund that reached TRANSFERRED through the court returns to MODIFIED, not CONSENT_GRANTED.

    PRD 3.6: "The return state is conditional on the authority that was used: a fund
    transferred on DONOR_CONSENT returns TRANSFERRED -> CONSENT_GRANTED, and one
    transferred on JUDICIAL_MODIFICATION returns TRANSFERRED -> MODIFIED." A fund
    whose restriction conflicts "may not move on a DONOR_CONSENT basis at all" and
    so must travel HELD -> CONSENT_SOUGHT -> CONSENT_DENIED -> PETITION_FILED ->
    MODIFIED -> TRANSFERRED; the unwind must therefore rejoin the judicial branch it
    came from, keeping consent_decision at DENIED and court_decision at
    GRANTED_WITH_CONDITIONS as the record of the route travelled.

    Design: Difficulty/non_linear_state_machine/restricted_fund_petition_branch_returns_to_modified_not_consent_granted
    """
    ctx = fx.setup_deal_structure_selected(api)
    fund = _judicial_fund(api, ctx)
    transferred = fx.transfer_fund(
        api, fund["id"], ctx["deal"]["id"], basis="JUDICIAL_MODIFICATION"
    )
    a.assert_field(transferred, "transfer_status", "TRANSFERRED")

    unwound = fx.unwind_fund(api, fund["id"])

    a.assert_field(unwound, "transfer_status", "MODIFIED")
    assert unwound["transfer_status"] != "CONSENT_GRANTED", (
        "the consent branch was never granted, so the unwind may not land there"
    )
    a.assert_field(unwound, "consent_decision", "DENIED")
    a.assert_field(unwound, "court_decision", "GRANTED_WITH_CONDITIONS")
    a.assert_field(unwound, "modified_purpose_code", "YM-YOUTH_PROGRAMS")


def test_the_unwind_freezes_the_release_amount_and_clears_the_transfer_columns(api):
    """The unwind zeroes the moved amounts and clears the transfer columns but keeps the release figure.

    PRD 3.6: the unwind "clears transferred_to_org_id, transfer_restructuring_id and
    transfer_basis to null, sets transferred_amount_cents and retained_amount_cents
    both to 0, and increases unwind_count by one. It deliberately leaves
    transferable_amount_cents at its pre-transfer value, so a re-transfer releases
    the identical amount rather than recomputing it against possibly restated
    inputs." For this permanent endowment the judicial rule froze that figure at
    62000000 minus 45000000 plus seven percent of 45000000 truncated, namely
    20150000 cents, and the round trip must leave it exactly there.

    Design: Difficulty/non_linear_state_machine/restricted_fund_petition_branch_returns_to_modified_not_consent_granted
    """
    ctx = fx.setup_deal_structure_selected(api)
    fund = _judicial_fund(api, ctx)
    a.assert_money_equals(
        fund["transferable_amount_cents"], JUDICIAL_RELEASE_CENTS, "transferable_amount_cents"
    )
    transferred = fx.transfer_fund(
        api, fund["id"], ctx["deal"]["id"], basis="JUDICIAL_MODIFICATION"
    )
    a.assert_money_equals(
        transferred["transferred_amount_cents"],
        JUDICIAL_RELEASE_CENTS,
        "transferred_amount_cents",
    )

    unwound = fx.unwind_fund(api, fund["id"])

    a.assert_field(unwound, "transfer_status", "MODIFIED")
    a.assert_money_equals(
        unwound["transferable_amount_cents"],
        JUDICIAL_RELEASE_CENTS,
        "transferable_amount_cents after unwind",
    )
    a.assert_money_equals(unwound["transferred_amount_cents"], 0, "transferred_amount_cents")
    a.assert_money_equals(unwound["retained_amount_cents"], 0, "retained_amount_cents")
    a.assert_null(unwound, "transferred_to_org_id")
    a.assert_null(unwound, "transfer_restructuring_id")
    a.assert_null(unwound, "transfer_basis")
    a.assert_field(unwound, "unwind_count", 1)
    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")
    a.assert_field(deal, "unresolved_restricted_fund_count", 1)


def test_unwinding_a_consent_transfer_returns_the_fund_to_consent_granted(api):
    """The same unwind endpoint returns a consent-based transfer to CONSENT_GRANTED instead.

    PRD 3.6: "a fund transferred on DONOR_CONSENT returns TRANSFERRED ->
    CONSENT_GRANTED, and one transferred on JUDICIAL_MODIFICATION returns
    TRANSFERRED -> MODIFIED." An unconflicted endowment that travelled HELD ->
    CONSENT_SOUGHT -> CONSENT_GRANTED -> TRANSFERRED therefore comes back to
    CONSENT_GRANTED with court_decision still null, releasing "the entire fund value:
    principal_cents plus accumulated_appreciation_cents" of 62000000 cents on a
    re-transfer, which is what distinguishes the two return states rather than the
    unwind request itself.

    Design: Difficulty/non_linear_state_machine/restricted_fund_petition_branch_returns_to_modified_not_consent_granted
    """
    ctx = fx.setup_deal_structure_selected(api)
    fund = fx.setup_fund_consent_granted(
        api,
        ctx["org_a"]["id"],
        fund_name="Delaney Endowment",
        restriction_conflict=False,
        **ENDOWMENT,
    )
    a.assert_field(fund, "transfer_status", "CONSENT_GRANTED")
    fx.transfer_fund(api, fund["id"], ctx["deal"]["id"], basis="DONOR_CONSENT")

    unwound = fx.unwind_fund(api, fund["id"])

    a.assert_field(unwound, "transfer_status", "CONSENT_GRANTED")
    assert unwound["transfer_status"] != "MODIFIED", (
        "no petition was ever filed, so the unwind may not land on the judicial branch"
    )
    a.assert_field(unwound, "consent_decision", "GRANTED")
    a.assert_null(unwound, "court_decision")
    a.assert_null(unwound, "transfer_basis")
    a.assert_money_equals(
        unwound["transferable_amount_cents"], FUND_VALUE_CENTS, "transferable_amount_cents"
    )
    a.assert_field(unwound, "unwind_count", 1)
