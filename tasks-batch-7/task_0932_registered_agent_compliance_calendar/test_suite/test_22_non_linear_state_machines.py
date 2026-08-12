"""True cycles: a registration returning to ACTIVE, and a capped escalation loop."""
from test_helpers import (
    DE_RULE_FULL,
    SOP,
    ApiErrorId,
    assert_same_instant,
    capture,
    draft_obligation_filing,
    escalate_sop,
    forward_sop,
    new_payment,
    read_filing,
    read_obligation,
    read_registration,
    read_sop,
    receive_sop,
    record_filing_outcome,
    scan_sop,
    set_clock,
    setup_active_home_registration,
    setup_delinquent_registration,
    submit_filing,
    validate_error,
    validate_paginated,
)


def _cured_registration_scene():
    """A DELINQUENT registration whose single obligation has a funded, submitted
    filing waiting on the jurisdiction's answer."""
    scene = setup_delinquent_registration(DE_RULE_FULL)
    obligation = read_obligation(scene["obligation"]["id"])
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT", expedite_tier="NONE")
    payment = new_payment(scene["client"]["id"], 29900)
    capture(payment["id"], 29900)
    submit_filing(filing["id"])
    scene["filing"] = filing
    return scene


def _escalated_to_the_cap_scene():
    """An ORDINARY document forwarded and escalated three times, sitting at the cap."""
    scene = setup_active_home_registration(DE_RULE_FULL)
    set_clock("2026-06-05T14:00:00Z")
    document = receive_sop(scene["registration"]["id"], "ORDINARY")
    scan_sop(document["id"], not_our_entity=False)
    set_clock("2026-06-08T10:00:00Z")
    forward_sop(document["id"])
    for instant in (
        "2026-06-09T10:00:00Z",
        "2026-06-09T14:00:00Z",
        "2026-06-10T10:00:00Z",
    ):
        set_clock(instant)
        escalate_sop(document["id"])
    scene["document"] = read_sop(document["id"])
    return scene


def test_registration_returns_from_delinquent_to_active_when_its_period_is_satisfied(api):
    """PRD §3.11: "When the last obligation of a `DELINQUENT` registration in status
    `DELINQUENT` leaves that status by reaching `SATISFIED` or `WAIVED`, the registration
    returns to `ACTIVE`. The condition is checked as a whole: the registration must be
    `DELINQUENT` and no obligation of it may remain in `DELINQUENT`."
    PRD §3.11: "The registration's `delinquency_rank` is then recomputed from whatever
    obligations remain open — it does not merely reset to 0 — the `version` increases by
    1, and the entity's posture and the client's rollup follow."
    PRD §2.11: "If no open obligation remains, the rank is 0."

    Design: Difficulty/non_linear_state_machine/registration_cycles_active_delinquent_active
    """
    scene = _cured_registration_scene()
    assert scene["registration"]["status"] == "DELINQUENT"

    record_filing_outcome(scene["filing"]["id"], "ACCEPTED")

    registration = read_registration(scene["registration"]["id"])
    assert registration["status"] == "ACTIVE"
    assert registration["delinquency_rank"] == 0


def test_the_accepted_filing_satisfies_the_period_it_was_lodged_against(api):
    """PRD §3.7: "when — and only when — the filing carries a `compliance_obligation_id`,
    the referenced obligation moves to `SATISFIED` with `satisfied_on` stamped at the
    current clock date and its `version` increased by 1, its pending reminder notices
    are suppressed, and if that leaves no obligation on the registration in `DELINQUENT`
    while the registration itself is `DELINQUENT`, the registration returns to `ACTIVE`,
    after which the entity's posture and the client's rollup are recomputed."
    PRD §3.7: "For a filing attached to an obligation, `state_fee_cents` is the
    obligation's `state_fee_cents` plus its `franchise_tax_cents` plus its
    `late_fee_cents` — the money owed to the jurisdiction for that period, lateness
    included — and `service_fee_cents` is the obligation's own `service_fee_cents`."

    Design: Difficulty/non_linear_state_machine/registration_cycles_active_delinquent_active
    """
    scene = _cured_registration_scene()

    record_filing_outcome(scene["filing"]["id"], "ACCEPTED")

    obligation = read_obligation(scene["obligation"]["id"])
    assert obligation["status"] == "SATISFIED"
    assert obligation["satisfied_on"] == "2027-04-15"

    filing = read_filing(scene["filing"]["id"])
    assert filing["status"] == "ACCEPTED"
    # 5000 state fee + 0 tax + 20000 flat late fee carried onto the filing, plus the
    # obligation's own 4900 service fee = 29900.
    assert filing["total_fee_cents"] == 29900


def test_a_fourth_escalation_is_refused_at_the_cap(api):
    """PRD §3.9: "and `escalation_level` must be strictly below 3, else
    `ERR_SOP_ESCALATION_CAP_REACHED`."
    PRD §3.9: "A `SopEscalationEvent` is created recording the `sop_document_id`, the
    new `level`, `raised_at` stamped from the logical clock, and a `channel` fixed by
    that level: `EMAIL` at level 1, `PHONE` at level 2 and `ACCOUNT_MANAGER` at level 3."

    Design: Difficulty/non_linear_state_machine/sop_document_cycles_forwarded_escalated_forwarded_under_cap
    """
    scene = _escalated_to_the_cap_scene()
    assert scene["document"]["escalation_level"] == 3

    set_clock("2026-06-10T14:00:00Z")
    response = api.escalate_sop_document(scene["document"]["id"], SOP)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SOP_ESCALATION_CAP_REACHED.value)
    assert read_sop(scene["document"]["id"])["escalation_level"] == 3

    rows, meta = validate_paginated(
        api.list_sop_escalations(scene["document"]["id"], SOP)
    )
    assert meta["total_count"] == 3
    assert sorted(row["level"] for row in rows) == [1, 2, 3]
    by_level = {row["level"]: row["channel"] for row in rows}
    assert by_level == {1: "EMAIL", 2: "PHONE", 3: "ACCOUNT_MANAGER"}


def test_the_document_re_enters_forwarded_even_though_escalation_is_capped(api):
    """PRD §3.9: "This same action is also how a document is re-forwarded after an
    escalation, so it is accepted from `SCANNED` and from `ESCALATED`; from any other
    status it is rejected with `ERR_INVALID_STATE`."
    PRD §3.9: "On a re-forward out of `ESCALATED`, `escalation_level` is deliberately
    left unchanged: the escalations already raised are not forgiven by a fresh forward."
    PRD §3.9: "`forwarded_late` is then set to true when `forwarded_at` is **strictly**
    later than `forward_deadline_at`, and false otherwise — forwarding exactly at the
    deadline instant is on time."
    PRD §3.9: "`ack_deadline_at` is set to `forwarded_at` advanced by 8 business hours."

    Design: Difficulty/non_linear_state_machine/sop_document_cycles_forwarded_escalated_forwarded_under_cap
    """
    scene = _escalated_to_the_cap_scene()

    set_clock("2026-06-10T14:00:00Z")
    reforwarded = forward_sop(scene["document"]["id"])

    assert reforwarded["status"] == "FORWARDED"
    assert reforwarded["escalation_level"] == 3
    assert_same_instant(
        reforwarded["forwarded_at"], "2026-06-10T14:00:00Z", "forwarded_at"
    )
    # The ordinary deadline was 2026-06-09T14:00Z, so this forward is strictly late.
    assert reforwarded["forwarded_late"] is True
    # 8 business hours from Wednesday 14:00: 3 hours to 17:00, then 5 hours from
    # 09:00 Thursday lands at 2026-06-11T14:00Z.
    assert_same_instant(
        reforwarded["ack_deadline_at"], "2026-06-11T14:00:00Z", "ack_deadline_at"
    )
