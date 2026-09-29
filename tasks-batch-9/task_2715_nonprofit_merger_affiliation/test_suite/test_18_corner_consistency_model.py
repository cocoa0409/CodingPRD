"""Consistency compliance tests: every side effect of a write is readable when it returns.

Every test in this module builds its own preconditions through the API, because
the harness restarts the server and empties the database before each test.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_seat_ledger_conserved,
    find_by_id,
)
from test_helpers.test_users import (
    DILIGENCE_LEAD_3,
    PLATFORM_ADMIN,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def test_the_certification_response_already_carries_the_seats_it_moved(api):
    """The certify response itself carries the allocated seats and the pinned evidentiary basis,
    the seat pool, the party's governance seats and the bubbled-up deal status are readable in
    the same instant, and a sweep afterwards changes nothing.

    PRD 3.5 says "Certification does four things at once": it moves the resolution
    "RECORDED to CERTIFIED", pins "composite_score and sequence_no from the deal's latest
    DILIGENCE_ADJUSTED alignment assessment into pinned_composite_score and
    pinned_assessment_sequence_no", draws the party's seats from the reserved pool - the seats
    due "are written to the resolution's allocated_seats, subtracted from the deal's
    reserved_seat_pool, and written to governance_seats on the approving party's organization" -
    and re-evaluates the deal so that "once both INITIATOR and TARGET hold a CERTIFIED
    resolution, the deal advances BOARD_APPROVAL to REGULATORY_REVIEW". PRD 3.5 makes the
    INITIATOR's share the governing letter's board_seat_split_initiator and the TARGET's share
    combined_board_seats less that figure, and PRD 2.8 holds the ledger identity after every
    certification. PRD 3.2 gives each snapshot a sequence_no of "one plus the count of prior
    snapshots of the same deal and the same variant", so the only diligence-adjusted snapshot is
    number 1, and its composite of 40.00 mission points, 0.00 overlap points and 20.00
    sustainability points is 60.00. PRD 2.4 says "Setting the clock does not itself apply any
    time-driven transition; the regulatory sweep described in 3.9 is what applies them", and
    PRD 3.9 reports the sweep as three id lists that are empty when nothing is due.

    Design: Corner/consistency_model/the_certification_response_already_carries_the_seats_it_moved
    """
    ctx = fx.setup_deal_board_approval(api)
    org_a, org_b, deal_id = ctx["org_a"], ctx["org_b"], ctx["deal"]["id"]
    so_a = make_strategy_officer_headers(org_a["id"])

    certified_i = validate_success(
        api.certify_board_approval(
            ctx["approval_initiator"]["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"),
            make_board_secretary_headers(org_a["id"]),
        )
    )
    assert_field(certified_i, "status", "CERTIFIED")
    assert_field(certified_i, "allocated_seats", 8)
    assert_decimal_equals(certified_i["pinned_composite_score"], 60.00, 2, "pinned_composite_score")
    assert_field(certified_i, "pinned_assessment_sequence_no", 1)

    assert_field(validate_success(api.get_restructuring(deal_id, so_a)), "reserved_seat_pool", 7)
    assert_field(validate_success(api.get_organization(org_a["id"], so_a)), "governance_seats", 8)

    certified_t = validate_success(
        api.certify_board_approval(
            ctx["approval_target"]["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-B-1", certifying_secretary_ref="SEC-B-2"),
            make_board_secretary_headers(org_b["id"]),
        )
    )
    assert_field(certified_t, "allocated_seats", 7)

    dossier_before = validate_success(api.get_dossier(deal_id, so_a))
    assert_field(dossier_before, "reserved_seat_pool", 0)
    assert_field(dossier_before, "certified_allocated_seats_total", 15)
    assert_field(dossier_before, "seat_ledger_total", 15)
    assert_field(dossier_before, "combined_board_seats", 15)
    assert_field(dossier_before, "deal_status", "REGULATORY_REVIEW")
    assert_seat_ledger_conserved(dossier_before)
    assert_decimal_equals(dossier_before["screening_composite_score"], 60.00, 2, "screening_composite_score")
    assert_decimal_equals(
        dossier_before["diligence_adjusted_composite_score"], 60.00, 2,
        "diligence_adjusted_composite_score",
    )
    assert_decimal_equals(dossier_before["composite_delta"], 0.00, 2, "composite_delta")

    version_before = fx.deal_version(api, deal_id)
    sweep = validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN))
    assert_field(sweep, "deemed_approved_filing_ids", [])
    assert_field(sweep, "lapsed_letter_of_intent_ids", [])
    assert_field(sweep, "expired_exclusivity_letter_of_intent_ids", [])

    dossier_after = validate_success(api.get_dossier(deal_id, so_a))
    assert dossier_after == dossier_before, "the sweep had nothing to do and changed no dossier figure"
    assert fx.deal_version(api, deal_id) == version_before, "the sweep did not touch the deal row"


def test_the_escalation_cascade_is_readable_before_any_sweep_runs(api):
    """One critical escalation rewrites the finding, the deal, the letter, both certified
    resolutions and both organizations' governance seats, and every one of those rows reads back
    correctly before any sweep runs - after which the sweep proves to be a no-op.

    PRD 3.4 says escalation is available while the deal is REGULATORY_REVIEW and that "Hop one
    always happens: the finding moves to ESCALATED and stores the reason". Where the severity is
    CRITICAL, "hop two reverts the deal to LOI_NEGOTIATION from whichever of those five statuses
    it held, increases round_no by one"; "Hop three follows from that revert: the deal's EXECUTED
    letter of intent becomes SUPERSEDED and its exclusivity_status becomes RELEASED"; "Hop four
    follows from the letter's supersession: every board approval of the deal in CERTIFIED becomes
    SUPERSEDED"; and "Hop five follows from those supersessions: each superseded approval returns
    its allocated_seats to the deal's reserved_seat_pool, sets its own allocated_seats to 0, and
    resets governance_seats to 0 on the corresponding party organization". The deal's
    "structure_type is deliberately retained across the revert". PRD 2.8 keeps the seat ledger
    identity after every supersession, and PRD 3.9 says the sweep applies only the three
    time-driven transitions and reports them as three id lists - a SUPERSEDED letter can neither
    lapse nor expire and there is no filing to deem, so all three are empty and nothing moves.

    Design: Corner/consistency_model/the_escalation_cascade_is_readable_before_any_sweep_runs
    """
    ctx = fx.setup_deal_regulatory_review(api)
    org_a, org_b, deal_id = ctx["org_a"], ctx["org_b"], ctx["deal"]["id"]
    so_a = make_strategy_officer_headers(org_a["id"])
    critical = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="LITIGATION",
                severity="CRITICAL",
                summary="Undisclosed wage and hour class action served on the target",
                exposure_cents=18000000,
            ),
            DILIGENCE_LEAD_3,
        ),
        201,
    )

    escalated = validate_success(
        api.escalate_diligence_request(
            critical["id"],
            f.diligence_escalate_payload(
                escalation_reason="Counsel requires the litigation to be resolved before any closing"
            ),
            DILIGENCE_LEAD_3,
        )
    )
    assert_field(escalated, "status", "ESCALATED")
    assert_field(
        escalated,
        "escalation_reason",
        "Counsel requires the litigation to be resolved before any closing",
    )

    deal = validate_success(api.get_restructuring(deal_id, so_a))
    assert_field(deal, "status", "LOI_NEGOTIATION")
    assert_field(deal, "round_no", 2)
    assert_field(deal, "reserved_seat_pool", 15)
    assert_field(deal, "structure_type", "MERGER")

    letters, _lmeta = validate_paginated(api.list_deal_letters_of_intent(deal_id, so_a))
    assert len(letters) == 1, f"the deal holds exactly one letter, got {len(letters)}"
    assert_field(letters[0], "status", "SUPERSEDED")
    assert_field(letters[0], "exclusivity_status", "RELEASED")

    approvals, _ameta = validate_paginated(api.list_deal_board_approvals(deal_id, so_a))
    assert len(approvals) == 2, f"the deal holds exactly two resolutions, got {len(approvals)}"
    for approval_id in (ctx["approval_initiator"]["id"], ctx["approval_target"]["id"]):
        row = find_by_id(approvals, approval_id)
        assert_field(row, "status", "SUPERSEDED")
        assert_field(row, "allocated_seats", 0)
    assert_field(validate_success(api.get_organization(org_a["id"], so_a)), "governance_seats", 0)
    assert_field(validate_success(api.get_organization(org_b["id"], so_a)), "governance_seats", 0)

    dossier_before = validate_success(api.get_dossier(deal_id, so_a))
    assert_field(dossier_before, "deal_status", "LOI_NEGOTIATION")
    assert_field(dossier_before, "round_no", 2)
    assert_field(dossier_before, "reserved_seat_pool", 15)
    assert_field(dossier_before, "certified_allocated_seats_total", 0)
    assert_field(dossier_before, "seat_ledger_total", 15)
    assert_field(dossier_before, "structure_type", "MERGER")
    assert_seat_ledger_conserved(dossier_before)

    version_before = fx.deal_version(api, deal_id)
    sweep = validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN))
    assert_field(sweep, "deemed_approved_filing_ids", [])
    assert_field(sweep, "lapsed_letter_of_intent_ids", [])
    assert_field(sweep, "expired_exclusivity_letter_of_intent_ids", [])

    dossier_after = validate_success(api.get_dossier(deal_id, so_a))
    assert dossier_after == dossier_before, "the sweep had nothing to do and changed no dossier figure"
    assert fx.deal_version(api, deal_id) == version_before, "the sweep did not touch the deal row"
