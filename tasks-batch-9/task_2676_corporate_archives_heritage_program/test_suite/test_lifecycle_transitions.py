"""Non-linear lifecycles: a revision loop, two independent axes, a fork-join."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    COUNSEL_A_ID,
    DIRECTOR_A,
    DIRECTOR_A_ID,
    DIRECTOR_B,
    DIRECTOR_B_ID,
    factories as f,
    fixtures as fx,
    ok,
)


def _request_sent_back_for_changes(client):
    """An EXTERNAL_RESEARCHER request over two items, screened CHANGES_REQUESTED."""
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "sensitivity_level": "INTERNAL"},
            {"unit_count": 6, "sensitivity_level": "INTERNAL"},
        ],
        series_overrides={"sensitivity_ceiling": "INTERNAL"},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="CHANGES_REQUESTED",
        requester_overrides={"requester_class": "EXTERNAL_RESEARCHER",
                             "nda_on_file": False},
    )
    return holding, case


def test_requester_revision_returns_the_request_to_screening(client):
    """PRD §3.7: "When and only when the decision is `CHANGES_REQUESTED`, the parent
    request moves `SCREENING → CHANGES_REQUESTED`."
    PRD §3.7: "On success the request returns to `SCREENING`, `revision_round`
    increments by 1, `requested_page_count` and `prelim_risk_score` are both recomputed
    from the revised item set, and every screening on the request in `OPEN` or in
    `COMPLETED` moves to `SUPERSEDED` with `superseded_reason` set to
    `REQUESTER_REVISION`."

    Design: Difficulty/non_linear_state_machine/access_request_revision_cycle_returns_to_screening
    """
    holding, case = _request_sent_back_for_changes(client)
    assert case.request["status"] == "CHANGES_REQUESTED"
    assert case.request["revision_round"] == 0
    assert case.request["requested_page_count"] == 88

    revised = ok(
        client.revise_access_request(
            case.request_id,
            f.revise_payload([holding.items[0]["id"]]),
            case.requester_headers,
        )
    )
    assert revised["status"] == "SCREENING"
    assert revised["revision_round"] == 1
    assert revised["requested_page_count"] == 22
    assert revised["prelim_risk_score"] == 45


def test_requester_revision_supersedes_the_completed_screening(client):
    """PRD §3.7: "The requester answers a changes-requested screening with a
    **revision**, which is the one operation exclusive to the `Requester` role."
    PRD §3.7: "On success the request returns to `SCREENING`, `revision_round`
    increments by 1, `requested_page_count` and `prelim_risk_score` are both recomputed
    from the revised item set, and every screening on the request in `OPEN` or in
    `COMPLETED` moves to `SUPERSEDED` with `superseded_reason` set to
    `REQUESTER_REVISION`."

    Design: Difficulty/non_linear_state_machine/access_request_revision_cycle_returns_to_screening
    """
    holding, case = _request_sent_back_for_changes(client)

    ok(
        client.revise_access_request(
            case.request_id,
            f.revise_payload([holding.items[0]["id"]]),
            case.requester_headers,
        )
    )

    retired = fx.read_screening(client, case.screening_id)
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_reason"] == "REQUESTER_REVISION"


def test_transcription_axis_advances_while_consent_is_still_pending(client):
    """PRD §3.8: "Starting a draft moves transcription `NOT_STARTED → DRAFT`; marking
    reviewed moves it `DRAFT → REVIEWED`. Both leave `consent_status` untouched, which
    means drafting a transcript is entirely legal while consent is still `PENDING`."
    PRD §3.8: "When consent is `WITHDRAWN`, or still `PENDING`, the release state is
    `WITHHELD` regardless of transcription."

    Design: Difficulty/non_linear_state_machine/oral_history_two_independent_state_axes_advance_separately
    """
    holding = fx.make_holding(client)
    interview = fx.make_interview(client, holding.accession_id)
    assert interview["consent_status"] == "PENDING"
    assert interview["transcription_status"] == "NOT_STARTED"
    assert interview["release_state"] == "WITHHELD"

    fx.transcription(client, interview["id"], "START_DRAFT")
    reviewed = fx.transcription(client, interview["id"], "MARK_REVIEWED")

    assert reviewed["transcription_status"] == "REVIEWED"
    assert reviewed["consent_status"] == "PENDING"
    assert reviewed["release_state"] == "WITHHELD"


def test_signing_consent_then_approving_the_transcript_reaches_public(client):
    """PRD §3.8: "Every consent action recomputes `release_state` and leaves
    `transcription_status` completely untouched."
    PRD §3.8: "When consent is `SIGNED`, the release state is `PUBLIC` if transcription
    has reached `APPROVED` **and** either there is no embargo or the logical clock
    stands at or after `embargo_until`; failing that, it is `RESEARCH_ROOM_ONLY` if
    transcription has reached `REVIEWED` or `APPROVED`; and `WITHHELD` in every
    remaining case."

    Design: Difficulty/non_linear_state_machine/oral_history_two_independent_state_axes_advance_separately
    """
    holding = fx.make_holding(client)
    interview = fx.make_interview(client, holding.accession_id)
    fx.transcription(client, interview["id"], "START_DRAFT")
    fx.transcription(client, interview["id"], "MARK_REVIEWED")

    signed = fx.consent(client, interview["id"], "SIGN")
    assert signed["consent_status"] == "SIGNED"
    assert signed["transcription_status"] == "REVIEWED"
    assert signed["release_state"] == "RESEARCH_ROOM_ONLY"

    approved = fx.transcription(client, interview["id"], "APPROVE")
    assert approved["transcription_status"] == "APPROVED"
    assert approved["release_state"] == "PUBLIC"
    assert approved["withdrawal_count"] == 0


def _donation_proposal(client):
    """A SUBMITTED donation-route proposal over all four units of one item."""
    holding = fx.make_holding(client, item_specs=[{"unit_count": 4}])
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        units=4,
        route="DONATION",
        recipient_repository="County Heritage Archive",
    )
    return holding, proposal


def test_heritage_first_branch_reaches_the_dual_clearance_join(client):
    """PRD §3.9: "**Fork branch B is heritage clearance**, granted by the
    `ArchivesDirector`. It is declared from `SUBMITTED`, advancing the proposal to
    `HERITAGE_CLEARED`, and equally from `LEGAL_CLEARED`, advancing it to the join state
    `DUALLY_CLEARED`."
    PRD §3.9: "Both paths stamp `heritage_cleared_by` from `X-User-ID` and store the
    optional `clearance_note`."
    PRD §3.9: "The two branches are symmetric: `SUBMITTED → LEGAL_CLEARED →
    DUALLY_CLEARED` and `SUBMITTED → HERITAGE_CLEARED → DUALLY_CLEARED` are equally
    valid routes to the join, and neither branch may be granted twice."

    Design: Difficulty/non_linear_state_machine/deaccession_fork_join_two_clearances_then_execute
    """
    _, proposal = _donation_proposal(client)

    heritage = ok(client.heritage_clearance(proposal["id"], DIRECTOR_A))
    assert heritage["status"] == "HERITAGE_CLEARED"
    assert heritage["heritage_cleared_by"] == DIRECTOR_A_ID
    assert heritage["legal_cleared_by"] is None

    joined = ok(client.legal_clearance(proposal["id"], COUNSEL_A))
    assert joined["status"] == "DUALLY_CLEARED"
    assert joined["legal_cleared_by"] == COUNSEL_A_ID

    approved = ok(client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by"] == DIRECTOR_B_ID
    assert approved["stale_finding_aid_count"] == 0
    assert approved["revalidated_request_count"] == 0


def test_executed_donation_moves_every_unit_off_the_shelf(client):
    """PRD §3.9: "On the `DONATION` route, the same unit movement occurs,
    `transfer_reference` records the receiving repository's receipt, and
    `recipient_repository` is copied onto the item's audit trail so the external
    custodian is permanently traceable."
    PRD §3.9: "The item's destination depends on what is left: when `units_on_shelf`
    reaches exactly 0 the item lands in the terminal `DEACCESSIONED`; when units remain,
    the item returns to `ACCESSIONED`, which is how a partial deaccession works."

    Design: Difficulty/non_linear_state_machine/deaccession_fork_join_two_clearances_then_execute
    """
    holding, proposal = _donation_proposal(client)
    ok(client.heritage_clearance(proposal["id"], DIRECTOR_A))
    ok(client.legal_clearance(proposal["id"], COUNSEL_A))
    ok(client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B))

    executed = ok(
        client.execute_deaccession_proposal(
            proposal["id"], f.execute_payload("DON-RCPT-2026-0007"), ARCHIVIST_A
        )
    )
    assert executed["status"] == "EXECUTED"
    assert executed["transfer_reference"] == "DON-RCPT-2026-0007"

    item = fx.read_item(client, holding.item_id)
    assert item["units_on_shelf"] == 0
    assert item["units_on_loan"] == 0
    assert item["units_deaccessioned"] == 4
    assert item["status"] == "DEACCESSIONED"
