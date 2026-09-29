"""Single requests whose consequences propagate through dependent hops.

PRD 2.8 warns that "Where they do, the specification names every hop, and an
implementation that applies only the first hop is incomplete. Two cascades run
deep enough to deserve names of their own: escalating a critical diligence
finding reaches five hops, described in 3.4, and executing a restricted-fund
transfer reaches four, described in 3.6."
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    DILIGENCE_LEAD,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
)

CRITICAL_FINDING = {
    "workstream": "RESTRICTED_FUNDS",
    "severity": "CRITICAL",
    "summary": "Endowment corpus pledged as loan collateral without donor authority",
    "exposure_cents": 4000000,
}
TRANSFERABLE_CENTS = 62000000


def _certified_deal_with_finding(api, **finding_overrides):
    """A REGULATORY_REVIEW deal holding two CERTIFIED resolutions and one OPEN finding."""
    ctx = fx.setup_deal_regulatory_review(api)
    assert ctx["deal"]["status"] == "REGULATORY_REVIEW"
    payload = dict(CRITICAL_FINDING)
    payload.update(finding_overrides)
    ctx["critical"] = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(ctx["deal"]["id"], **payload), DILIGENCE_LEAD
        ),
        201,
    )
    ctx["deal"] = fx.read_deal(api, ctx["deal"]["id"])
    return ctx


def _escalate(api, ctx):
    return validate_success(
        api.escalate_diligence_request(
            ctx["critical"]["id"], f.diligence_escalate_payload(), DILIGENCE_LEAD
        )
    )


def _letters(api, ctx):
    rows, _meta = validate_paginated(
        api.list_deal_letters_of_intent(ctx["deal"]["id"], PLATFORM_ADMIN)
    )
    return rows


def _approvals(api, ctx):
    rows, _meta = validate_paginated(
        api.list_deal_board_approvals(ctx["deal"]["id"], PLATFORM_ADMIN)
    )
    return rows


def test_escalating_a_critical_finding_reverts_the_deal_and_bumps_the_round(api):
    """Hops one and two: the finding escalates and the deal falls back to LOI_NEGOTIATION.

    PRD 3.4: "Hop one always happens: the finding moves to ESCALATED and stores the
    reason ... If severity is CRITICAL, hop two reverts the deal to LOI_NEGOTIATION
    from whichever of those five statuses it held, increases round_no by one, and
    bumps the deal's version by one." PRD 3.4 also states that "The deal's
    structure_type is deliberately retained across the revert, which is what forces
    the next round's letter to propose the same structure", so a deal escalated out
    of REGULATORY_REVIEW comes back at round_no 2 still committed to MERGER.

    Design: Difficulty/transitive_cascade/critical_escalation_five_hop_cascade_unwinds_letter_approvals_and_seats
    """
    ctx = _certified_deal_with_finding(api)
    before = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(before, "round_no", 1)

    finding = _escalate(api, ctx)
    a.assert_field(finding, "status", "ESCALATED")
    a.assert_field(
        finding, "escalation_reason", "Exposure exceeds the board risk tolerance"
    )

    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "status", "LOI_NEGOTIATION")
    a.assert_field(deal, "round_no", 2)
    a.assert_field(deal, "structure_type", "MERGER")
    a.assert_version_is(deal, before["version"] + 1, "restructuring")


def test_the_revert_supersedes_the_executed_letter_and_the_certified_approvals(api):
    """Hops three and four: the executed letter and both certified resolutions are superseded.

    PRD 3.4: "Hop three follows from that revert: the deal's EXECUTED letter of
    intent becomes SUPERSEDED and its exclusivity_status becomes RELEASED. Hop four
    follows from the letter's supersession: every board approval of the deal in
    CERTIFIED becomes SUPERSEDED." PRD 3.3 confirms the same chain from the letter's
    side: "An EXECUTED letter moves to SUPERSEDED with exclusivity_status set to
    RELEASED when a critical diligence finding is escalated ... and that supersession
    in turn drives the certified board approvals of the same deal into supersession
    as well."

    Design: Difficulty/transitive_cascade/critical_escalation_five_hop_cascade_unwinds_letter_approvals_and_seats
    """
    ctx = _certified_deal_with_finding(api)
    a.assert_field(ctx["approval_initiator"], "status", "CERTIFIED")
    a.assert_field(ctx["approval_target"], "status", "CERTIFIED")

    _escalate(api, ctx)

    letter = a.find_by_id(_letters(api, ctx), ctx["loi"]["id"])
    assert letter is not None, "the deal's letter of intent must still be readable"
    a.assert_field(letter, "status", "SUPERSEDED")
    a.assert_field(letter, "exclusivity_status", "RELEASED")

    approvals = _approvals(api, ctx)
    initiator = a.find_by_id(approvals, ctx["approval_initiator"]["id"])
    target = a.find_by_id(approvals, ctx["approval_target"]["id"])
    a.assert_field(initiator, "status", "SUPERSEDED")
    a.assert_field(target, "status", "SUPERSEDED")


def test_the_supersessions_return_every_seat_to_the_reserved_pool(api):
    """Hop five: the superseded approvals hand their seats back and zero both seat counters.

    PRD 3.4: "Hop five follows from those supersessions: each superseded approval
    returns its allocated_seats to the deal's reserved_seat_pool, sets its own
    allocated_seats to 0, and resets governance_seats to 0 on the corresponding party
    organization." With the executed letter's split of 8 of 15 seats the initiator
    held 8 and the target the remaining 7, leaving the pool at 0; after the cascade
    the pool holds all 15 again. PRD 2.8 makes that checkable: "the sum of
    reserved_seat_pool and the allocated_seats of every certified board approval of
    that deal always equals combined_board_seats".

    Design: Difficulty/transitive_cascade/critical_escalation_five_hop_cascade_unwinds_letter_approvals_and_seats
    """
    ctx = _certified_deal_with_finding(api)
    a.assert_field(ctx["approval_initiator"], "allocated_seats", 8)
    a.assert_field(ctx["approval_target"], "allocated_seats", 7)
    a.assert_field(fx.read_deal(api, ctx["deal"]["id"]), "reserved_seat_pool", 0)
    a.assert_seat_ledger_conserved(fx.dossier(api, ctx["deal"]["id"]))

    _escalate(api, ctx)

    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "reserved_seat_pool", 15)
    a.assert_field(deal, "combined_board_seats", 15)
    approvals = _approvals(api, ctx)
    a.assert_field(a.find_by_id(approvals, ctx["approval_initiator"]["id"]), "allocated_seats", 0)
    a.assert_field(a.find_by_id(approvals, ctx["approval_target"]["id"]), "allocated_seats", 0)
    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    a.assert_field(org_a, "governance_seats", 0)
    a.assert_field(org_b, "governance_seats", 0)
    dossier = fx.dossier(api, ctx["deal"]["id"])
    a.assert_field(dossier, "certified_allocated_seats_total", 0)
    a.assert_seat_ledger_conserved(dossier)


def test_escalating_a_non_critical_finding_stops_at_the_first_hop(api):
    """A HIGH finding escalates alone and leaves every other row in the system untouched.

    PRD 3.4: "Whether the remaining four hops happen depends entirely on the
    finding's severity. If severity is anything other than CRITICAL the cascade stops
    right there and no other row in the system is touched - the deal is left exactly
    as it was." A HIGH finding escalated out of REGULATORY_REVIEW therefore reaches
    ESCALATED while the deal keeps its status, round_no and version, the letter stays
    EXECUTED with ACTIVE exclusivity, both resolutions stay CERTIFIED and the seat
    ledger stays fully allocated.

    Design: Difficulty/transitive_cascade/critical_escalation_five_hop_cascade_unwinds_letter_approvals_and_seats
    """
    ctx = _certified_deal_with_finding(api, severity="HIGH")
    before = fx.read_deal(api, ctx["deal"]["id"])

    finding = _escalate(api, ctx)
    a.assert_field(finding, "status", "ESCALATED")

    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "status", "REGULATORY_REVIEW")
    a.assert_field(deal, "round_no", 1)
    a.assert_version_is(deal, before["version"], "restructuring")
    a.assert_field(deal, "reserved_seat_pool", 0)
    letter = a.find_by_id(_letters(api, ctx), ctx["loi"]["id"])
    a.assert_field(letter, "status", "EXECUTED")
    a.assert_field(letter, "exclusivity_status", "ACTIVE")
    approvals = _approvals(api, ctx)
    a.assert_field(a.find_by_id(approvals, ctx["approval_initiator"]["id"]), "status", "CERTIFIED")
    a.assert_field(a.find_by_id(approvals, ctx["approval_target"]["id"]), "allocated_seats", 7)


def _fund_and_tasks(api, ctx):
    """Register a consented fund at the initiator, then a held continuity task and a staffing task."""
    ctx["fund"] = fx.setup_fund_consent_granted(
        api,
        ctx["org_a"]["id"],
        fund_name="Nakamura Family Program Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=0,
        restriction_purpose_code="YM-YOUTH_PROGRAMS",
        restriction_conflict=False,
        donor_of_record_reachable=True,
    )
    a.assert_money_equals(
        ctx["fund"]["transferable_amount_cents"], TRANSFERABLE_CENTS, "transferable_amount_cents"
    )
    a.assert_field(
        fx.read_deal(api, ctx["deal"]["id"]), "restricted_asset_posture", "RESTRICTED_PENDING"
    )
    ctx["task_continuity"] = fx.create_task(
        api,
        ctx["deal"]["id"],
        workstream="PROGRAM_CONTINUITY",
        crew_code="CREW-PROG1",
        title="Rebadge afterschool sites",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )
    ctx["task_staffing"] = fx.create_task(
        api,
        ctx["deal"]["id"],
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Harmonise pay bands",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-15",
    )
    return ctx


def _task(api, task_id):
    return validate_success(api.get_integration_task(task_id, INTEGRATION_MANAGER))


def test_the_transfer_releases_the_held_continuity_task_and_leaves_the_staffing_task_alone(api):
    """Hop four: only the held program-continuity task is released, and only because the posture cleared.

    PRD 3.6: "Hop four follows because the posture became CLEARED: every integration
    task of that deal whose workstream is PROGRAM_CONTINUITY and whose status is HELD
    moves HELD -> PLANNED with held_reason cleared to null." PRD 3.8 explains the held
    state it starts from: "Where the workstream is PROGRAM_CONTINUITY and the deal's
    restricted_asset_posture is RESTRICTED_PENDING or BLOCKED, the task is created
    directly in HELD with held_reason set to RESTRICTED_ASSETS_UNRESOLVED ... Every
    other combination of workstream and posture creates the task in PLANNED with
    held_reason null." The staffing task was therefore already PLANNED before the
    transfer and is untouched by it.

    Design: Difficulty/transitive_cascade/restricted_fund_transfer_four_hop_cascade_releases_held_continuity_task
    """
    ctx = _fund_and_tasks(api, fx.setup_deal_structure_selected(api))
    a.assert_field(ctx["task_continuity"], "status", "HELD")
    a.assert_field(ctx["task_continuity"], "held_reason", "RESTRICTED_ASSETS_UNRESOLVED")
    a.assert_field(ctx["task_staffing"], "status", "PLANNED")
    a.assert_null(ctx["task_staffing"], "held_reason")

    fx.transfer_fund(api, ctx["fund"]["id"], ctx["deal"]["id"], basis="DONOR_CONSENT")

    continuity = _task(api, ctx["task_continuity"]["id"])
    a.assert_field(continuity, "status", "PLANNED")
    a.assert_null(continuity, "held_reason")
    staffing = _task(api, ctx["task_staffing"]["id"])
    a.assert_field(staffing, "status", "PLANNED")
    a.assert_null(staffing, "held_reason")


def test_the_transfer_writes_every_hop_one_column_on_the_fund(api):
    """Hop one: the fund moves to TRANSFERRED with the authority, the recipient and both amounts.

    PRD 3.6: "Hop one moves the fund to TRANSFERRED and writes transfer_basis,
    transfer_restructuring_id naming the authorising deal, transferred_to_org_id set
    to the counterparty organization, transferred_amount_cents equal to the previously
    fixed transferable_amount_cents, and retained_amount_cents equal to the fund value
    less what moved." A consented TEMP_RESTRICTED fund of 50000000 principal and
    12000000 appreciation released its whole 62000000-cent value, so the initiator's
    fund moves the full amount to the target and retains nothing.

    Design: Difficulty/transitive_cascade/restricted_fund_transfer_four_hop_cascade_releases_held_continuity_task
    """
    ctx = _fund_and_tasks(api, fx.setup_deal_structure_selected(api))

    fund = fx.transfer_fund(api, ctx["fund"]["id"], ctx["deal"]["id"], basis="DONOR_CONSENT")

    a.assert_field(fund, "transfer_status", "TRANSFERRED")
    a.assert_field(fund, "transfer_basis", "DONOR_CONSENT")
    a.assert_field(fund, "transfer_restructuring_id", ctx["deal"]["id"])
    a.assert_field(fund, "transferred_to_org_id", ctx["org_b"]["id"])
    a.assert_money_equals(
        fund["transferred_amount_cents"], TRANSFERABLE_CENTS, "transferred_amount_cents"
    )
    a.assert_money_equals(fund["retained_amount_cents"], 0, "retained_amount_cents")
    a.assert_money_equals(
        fund["transferable_amount_cents"], TRANSFERABLE_CENTS, "transferable_amount_cents"
    )


def test_the_transfer_moves_the_corpus_between_the_parties_and_clears_the_posture(api):
    """Hops two and three: both parties re-derive their corpus and the deal's posture clears.

    PRD 3.6: "Hop two follows because value has moved: restricted_corpus_cents is
    recomputed on both party organizations by the three-part sum of 3.1 ... their pair
    total is unchanged ... Hop three follows because the party corpus figures changed:
    the deal recomputes unresolved_restricted_fund_count and restricted_asset_posture,
    and the posture flips RESTRICTED_PENDING -> CLEARED at the moment the unresolved
    count reaches zero." Per PRD 3.1 the holder now contributes only
    retained_amount_cents, namely 0, while the recipient picks up
    transferred_amount_cents of 62000000, so the pair total of 62000000 that PRD 2.8
    conserves is unchanged.

    Design: Difficulty/transitive_cascade/restricted_fund_transfer_four_hop_cascade_releases_held_continuity_task
    """
    ctx = _fund_and_tasks(api, fx.setup_deal_structure_selected(api))
    a.assert_pair_corpus_equals(fx.dossier(api, ctx["deal"]["id"]), TRANSFERABLE_CENTS)

    fx.transfer_fund(api, ctx["fund"]["id"], ctx["deal"]["id"], basis="DONOR_CONSENT")

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    a.assert_money_equals(org_a["restricted_corpus_cents"], 0, "org_a.restricted_corpus_cents")
    a.assert_money_equals(
        org_b["restricted_corpus_cents"], TRANSFERABLE_CENTS, "org_b.restricted_corpus_cents"
    )
    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "unresolved_restricted_fund_count", 0)
    a.assert_field(deal, "restricted_asset_posture", "CLEARED")
    a.assert_pair_corpus_equals(fx.dossier(api, ctx["deal"]["id"]), TRANSFERABLE_CENTS)


def test_a_transfer_that_leaves_a_fund_unresolved_never_reaches_hop_four(api):
    """The continuity task stays held while a second party fund is still unresolved.

    PRD 3.6: the posture "flips RESTRICTED_PENDING -> CLEARED at the moment the
    unresolved count reaches zero", where "unresolved_restricted_fund_count is the
    number of those funds whose transfer_status is neither TRANSFERRED nor RETAINED",
    and hop four runs only "because the posture became CLEARED". With a second fund of
    10000000 cents still sitting in HELD the count is 1 after the transfer, so the
    posture remains RESTRICTED_PENDING and the held program-continuity task is not
    released - while the pair corpus of 72000000 cents is still conserved across the
    move.

    Design: Difficulty/transitive_cascade/restricted_fund_transfer_four_hop_cascade_releases_held_continuity_task
    """
    ctx = _fund_and_tasks(api, fx.setup_deal_structure_selected(api))
    fx.create_fund(
        api,
        ctx["org_a"]["id"],
        fund_name="Okafor Scholarship Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=10000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="YM-MENTOR_STIPENDS",
    )
    a.assert_pair_corpus_equals(fx.dossier(api, ctx["deal"]["id"]), 72000000)

    fx.transfer_fund(api, ctx["fund"]["id"], ctx["deal"]["id"], basis="DONOR_CONSENT")

    deal = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(deal, "unresolved_restricted_fund_count", 1)
    a.assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")
    continuity = _task(api, ctx["task_continuity"]["id"])
    a.assert_field(continuity, "status", "HELD")
    a.assert_field(continuity, "held_reason", "RESTRICTED_ASSETS_UNRESOLVED")
    a.assert_pair_corpus_equals(fx.dossier(api, ctx["deal"]["id"]), 72000000)
