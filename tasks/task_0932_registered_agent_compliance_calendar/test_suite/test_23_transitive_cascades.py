"""Chains where each hop is caused by the hop before it."""
from test_helpers import (
    ADMIN,
    DE_RULE_FULL,
    SOP,
    assert_same_instant,
    capture,
    draft_obligation_filing,
    escalate_sop,
    new_payment,
    read_client,
    read_entity,
    read_filing,
    read_obligation,
    read_registration,
    read_sop,
    record_filing_outcome,
    set_clock,
    setup_delinquent_registration,
    setup_forwarded_sop,
    submit_filing,
    validate_paginated,
)


def _submitted_filing_on_a_delinquent_registration():
    """An ACTIVE entity whose only registration is DELINQUENT, with the period's
    filing funded and lodged and every reminder already sent."""
    scene = setup_delinquent_registration(DE_RULE_FULL, activate_entity=True)
    obligation = read_obligation(scene["obligation"]["id"])
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", expedite_tier="NONE")
    payment = new_payment(scene["client"]["id"], 29900)
    capture(payment["id"], 29900)
    submit_filing(filing["id"])
    scene["filing"] = filing
    return scene


def _once_escalated_document():
    """A forwarded document that has already drawn one escalation."""
    scene = setup_forwarded_sop(DE_RULE_FULL)
    set_clock("2026-06-09T10:00:00Z")
    escalate_sop(scene["document"]["id"])
    scene["document"] = read_sop(scene["document"]["id"])
    return scene


def test_acceptance_drives_the_filing_the_period_and_the_registration(api):
    """PRD §2.12: "Hop one moves the `Filing` from `SUBMITTED` to `ACCEPTED`. Hop two,
    taken only when that filing carries a `compliance_obligation_id`, drives the
    referenced obligation to `SATISFIED`. Hop three suppresses every still-pending
    reminder notice of that obligation. Hop four, taken only when the obligation's
    registration is in status `DELINQUENT` and no obligation on that registration
    remains in status `DELINQUENT` after hop two, returns the registration from
    `DELINQUENT` to `ACTIVE`."
    PRD §3.6: "When an obligation reaches `SATISFIED`, `WAIVED` or `VOIDED`, every
    notice of that obligation in `PENDING` moves to `SUPPRESSED` and every notice in
    `SENT` also moves to `SUPPRESSED`; each such move increases that notice's `version`
    by 1."

    Design: Difficulty/transitive_cascade/filing_acceptance_cascades_five_hops_to_client_rollup
    """
    scene = _submitted_filing_on_a_delinquent_registration()

    record_filing_outcome(scene["filing"]["id"], "ACCEPTED")

    filing = read_filing(scene["filing"]["id"])
    assert filing["status"] == "ACCEPTED"
    assert filing["outcome_recorded_on"] == "2027-04-15"

    assert read_obligation(scene["obligation"]["id"])["status"] == "SATISFIED"

    reminders, meta = validate_paginated(
        api.list_reminders(scene["obligation"]["id"], ADMIN)
    )
    assert meta["total_count"] == 5
    assert all(row["status"] == "SUPPRESSED" for row in reminders)

    registration = read_registration(scene["registration"]["id"])
    assert registration["status"] == "ACTIVE"
    assert registration["delinquency_rank"] == 0


def test_the_same_acceptance_reaches_the_entity_posture_and_the_client_rollup(api):
    """PRD §2.12: "Hop five recomputes the owning legal entity's `compliance_posture`
    and then the owning client's portfolio rollup."
    PRD §2.11: "An entity's `compliance_posture` is the rank-to-status reading of the
    largest `delinquency_rank` across all of that entity's registrations, taken over
    registrations in any status."
    PRD §2.11: "A client's `portfolio_delinquency_status` is the rank-to-status reading
    of the largest `delinquency_rank` across all registrations of all of that client's
    legal entities, again over registrations in any status, and a client with no
    registrations reads `CURRENT`."

    Design: Difficulty/transitive_cascade/filing_acceptance_cascades_five_hops_to_client_rollup
    """
    scene = _submitted_filing_on_a_delinquent_registration()
    assert read_client(scene["client"]["id"])["portfolio_delinquency_status"] == "DELINQUENT"
    assert read_entity(scene["entity"]["id"])["compliance_posture"] == "DELINQUENT"

    record_filing_outcome(scene["filing"]["id"], "ACCEPTED")

    assert read_entity(scene["entity"]["id"])["compliance_posture"] == "CURRENT"
    client = read_client(scene["client"]["id"])
    assert client["portfolio_delinquency_status"] == "CURRENT"
    assert client["portfolio_open_obligation_count"] == 0
    assert client["portfolio_outstanding_cents"] == 0


def test_escalating_mints_an_event_and_re_arms_the_acknowledgment_clock(api):
    """PRD §3.9: "On success the document's status becomes `ESCALATED` — from
    `FORWARDED` it is a transition, and from `ESCALATED` it is a self-loop — and
    `escalation_level` increases by one."
    PRD §3.9: "A `SopEscalationEvent` is created recording the `sop_document_id`, the
    new `level`, `raised_at` stamped from the logical clock, and a `channel` fixed by
    that level: `EMAIL` at level 1, `PHONE` at level 2 and `ACCOUNT_MANAGER` at level 3."
    PRD §3.9: "`ack_deadline_at` is then re-armed to the current instant advanced by 4
    business hours, and the document's `version` increases by 1."

    Design: Difficulty/transitive_cascade/sop_escalation_cascades_to_client_portfolio_risk_flag
    """
    scene = _once_escalated_document()

    set_clock("2026-06-09T14:00:00Z")
    escalate_sop(scene["document"]["id"])

    document = read_sop(scene["document"]["id"])
    assert document["escalation_level"] == 2
    assert document["status"] == "ESCALATED"
    # 4 business hours from Tuesday 14:00: 3 hours to 17:00, then 1 hour from 09:00
    # Wednesday lands at 2026-06-10T10:00Z.
    assert_same_instant(
        document["ack_deadline_at"], "2026-06-10T10:00:00Z", "ack_deadline_at"
    )

    rows, meta = validate_paginated(api.list_sop_escalations(document["id"], SOP))
    assert meta["total_count"] == 2
    second = [row for row in rows if row["level"] == 2]
    assert len(second) == 1
    assert second[0]["channel"] == "PHONE"
    assert_same_instant(second[0]["raised_at"], "2026-06-09T14:00:00Z", "raised_at")


def test_the_second_escalation_raises_the_clients_portfolio_risk_flag(api):
    """PRD §2.11: "`sop_open_escalation_count` is the number of escalation events whose
    service-of-process document is still in status `FORWARDED` or `ESCALATED`, counted
    across every registration of the client. `portfolio_risk_flag` is true exactly when
    `sop_open_escalation_count` has reached 2 or more, and false below that."
    PRD §3.9: "The owning client's `sop_open_escalation_count` increases and
    `portfolio_risk_flag` is re-evaluated, becoming true once that count has reached 2."

    Design: Difficulty/transitive_cascade/sop_escalation_cascades_to_client_portfolio_risk_flag
    """
    scene = _once_escalated_document()
    before = read_client(scene["client"]["id"])
    assert before["sop_open_escalation_count"] == 1
    assert before["portfolio_risk_flag"] is False

    set_clock("2026-06-09T14:00:00Z")
    escalate_sop(scene["document"]["id"])

    after = read_client(scene["client"]["id"])
    assert after["sop_open_escalation_count"] == 2
    assert after["portfolio_risk_flag"] is True
