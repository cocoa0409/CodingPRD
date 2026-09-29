"""
Critical findings: three status dimensions on one record, none of them coupled.

PRD §3.5: "It is unusual in this system in that it carries **three independent
status dimensions on one record**, and none of them moves the others.
`finding_status` tracks the remediation lifecycle, `notification_status` tracks
progress along the notification chain, and `restriction_action` records whatever
restriction authority has been exercised."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"


def _immediate_finding_on_the_deck(client, roster, bridge):
    """
    An `ACCEPTED` report and an `IMMEDIATE` finding anchored to its deck row,
    which reports 50 units of severe quantity. Everything is stamped at the
    field-day instant so the owner deadline is exactly one day later.
    """
    report = fx.accepted_report(client, bridge["id"], roster, qa_clock=FIELD_DAY)
    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        report["inspection"]["id"],
        "IMMEDIATE",
        element_condition_id=report["elements"]["deck"]["id"],
    )
    return {"report": report, "finding": finding}


def test_a_new_finding_starts_at_the_origin_of_all_three_dimensions(
    client, roster, bridge
):
    """
    Creation places the finding at the start of each dimension independently and
    sets the owner deadline one day out from its own creation instant.

    PRD §3.5: "A new finding is created with `finding_status` `OPEN`,
    `notification_status` `PENDING` and `restriction_action` `NONE`."
    PRD §3.5: "Its `notification_due_at` is set to its own `created_at` plus 24
    hours — the deadline for reaching the bridge owner."
    PRD §3.5: "Two further fields start null and are populated only if authority
    is exercised: `restriction_authorized_by_id`, naming the district engineer who
    signed the restriction, and `restriction_imposed_at`, the instant it took
    effect."

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]

    assert finding["finding_status"] == "OPEN"
    assert finding["notification_status"] == "PENDING"
    assert finding["restriction_action"] == "NONE"
    assert finding["restriction_authorized_by_id"] is None
    assert finding["restriction_imposed_at"] is None
    assert finding["mitigation_note"] is None
    assert finding["resolution_note"] is None
    a.assert_instant_equals(finding["created_at"], FIELD_DAY, "created_at")
    a.assert_instant_equals(
        finding["notification_due_at"], "2026-09-03T12:00:00Z", "notification_due_at"
    )


def test_mitigating_moves_the_lifecycle_alone(client, roster, bridge):
    """
    Interim mitigation advances the remediation dimension and touches nothing
    else, so the notification chain stays where the owner notice left it and no
    restriction appears.

    PRD §3.5: "This advances `finding_status` `OPEN → MITIGATED` and does exactly
    nothing else: `notification_status` and `restriction_action` are untouched,
    and the finding continues to restrict the structure because a `MITIGATED`
    finding still counts as unresolved in the posture ladder."

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]

    fx.notify_owner(client, finding["id"], roster, channel="PHONE")
    notified = fx.read_finding(client, finding["id"])
    assert notified["notification_status"] == "OWNER_NOTIFIED"
    assert notified["finding_status"] == "OPEN"

    mitigated = fx.mitigate(client, finding["id"], roster)

    assert mitigated["finding_status"] == "MITIGATED"
    assert mitigated["notification_status"] == "OWNER_NOTIFIED"
    assert mitigated["restriction_action"] == "NONE"
    assert mitigated["mitigation_note"] is not None


def test_imposing_a_restriction_moves_the_authority_dimension_alone(
    client, roster, bridge
):
    """
    A restriction imposed on a mitigated finding leaves the remediation and
    notification dimensions exactly where they were, while the structure's
    posture and inspection cycle both tighten.

    PRD §3.5: "Escalating to `RESTRICT` is permitted only from
    `restriction_action` `NONE`. It stores `RESTRICT`, records
    `restriction_authorized_by_id` and stamps `restriction_imposed_at` from the
    logical clock."
    PRD §3.5: "a structure that was `OPEN` moves `OPEN → RESTRICTED` ... The
    structure's `inspection_interval_months` is re-derived with the posture floor
    applied, taking the smaller of its current interval and 6 months".

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]
    fx.notify_owner(client, finding["id"], roster, channel="PHONE")
    fx.mitigate(client, finding["id"], roster)

    restricted = fx.impose(client, finding["id"], roster, "RESTRICT")

    assert restricted["restriction_action"] == "RESTRICT"
    assert restricted["finding_status"] == "MITIGATED"
    assert restricted["notification_status"] == "OWNER_NOTIFIED"
    assert restricted["restriction_authorized_by_id"] == roster.district_id
    a.assert_instant_equals(
        restricted["restriction_imposed_at"], FIELD_DAY, "restriction_imposed_at"
    )

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "RESTRICTED"
    assert structure["inspection_interval_months"] == 6
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-03-02", "next_inspection_due_date"
    )


def test_reporting_to_the_federal_tier_moves_the_notification_dimension_alone(
    client, roster, bridge
):
    """
    The second link of the chain advances only the notification dimension: the
    finding is still mitigated and still restricting.

    PRD §3.5: "The chain must be walked in tier order and neither tier may be
    walked twice: the `BRIDGE_OWNER` tier advances the finding `PENDING →
    OWNER_NOTIFIED`, and only from `OWNER_NOTIFIED` may the `FHWA` tier advance it
    to `FHWA_REPORTED`."

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]
    fx.notify_owner(client, finding["id"], roster, channel="PHONE")
    fx.mitigate(client, finding["id"], roster)
    fx.impose(client, finding["id"], roster, "RESTRICT")

    fx.notify_fhwa(client, finding["id"], roster, channel="PORTAL")

    reported = fx.read_finding(client, finding["id"])
    assert reported["notification_status"] == "FHWA_REPORTED"
    assert reported["finding_status"] == "MITIGATED"
    assert reported["restriction_action"] == "RESTRICT"


def test_both_chain_links_are_logged_on_time_against_the_owner_deadline(
    client, roster, bridge
):
    """
    Lateness is an owner-tier concept only: the owner notice sent well inside the
    24-hour window is on time, and the federal notice records `late` false by
    rule.

    PRD §3.5: "A log entry's `late` is true when its `tier` is `BRIDGE_OWNER` and
    its `sent_at` falls strictly after the finding's `notification_due_at`; an
    owner notice sent at exactly the deadline instant is on time, and one sent a
    single second later is late. An `FHWA`-tier log entry always records `late` as
    false."
    PRD §2.5: "A notification log entry is an immutable audit record: it carries
    `id` and `created_at` only."

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]
    fx.notify_owner(client, finding["id"], roster, channel="PHONE")
    fx.notify_fhwa(client, finding["id"], roster, channel="PORTAL")

    logs = fx.logs_for_finding(client, finding["id"])
    assert len(logs) == 2
    a.assert_ascending_created_at(logs)

    owner_log, fhwa_log = logs
    assert owner_log["tier"] == "BRIDGE_OWNER"
    assert owner_log["channel"] == "PHONE"
    assert owner_log["late"] is False
    a.assert_instant_equals(owner_log["sent_at"], FIELD_DAY, "owner sent_at")
    a.assert_notification_log_shape(owner_log)

    assert fhwa_log["tier"] == "FHWA"
    assert fhwa_log["late"] is False
    a.assert_notification_log_shape(fhwa_log)

    assert fx.read_finding(client, finding["id"])["notification_late"] is False


def test_resolution_lifts_the_restriction_while_the_authority_record_remains(
    client, roster, bridge
):
    """
    Closing the finding out unwinds the structure but does not rewrite history:
    the restriction that was exercised stays on the record for audit even though
    it no longer contributes to the posture ladder.

    PRD §3.5: "Resolution stores the `resolution_note`, sets `finding_status` to
    `RESOLVED` (its terminal value), and then unwinds the structure:
    `open_critical_finding_count` is recomputed, `service_posture` is recomputed —
    and because a `RESOLVED` finding no longer contributes its
    `restriction_action`, the restriction or closure is lifted".
    PRD §2.11: "A finding whose `finding_status` has reached `RESOLVED` stops
    contributing entirely, even though its `restriction_action` remains on the
    record for audit purposes."

    Design: Difficulty/non_linear_state_machine/critical_finding_independent_status_dimensions
    """
    finding = _immediate_finding_on_the_deck(client, roster, bridge)["finding"]
    fx.notify_owner(client, finding["id"], roster, channel="PHONE")
    fx.mitigate(client, finding["id"], roster)
    fx.impose(client, finding["id"], roster, "RESTRICT")
    fx.notify_fhwa(client, finding["id"], roster, channel="PORTAL")

    resolved = fx.resolve(client, finding["id"], roster)

    assert resolved["finding_status"] == "RESOLVED"
    assert resolved["restriction_action"] == "RESTRICT", (
        "the exercised authority stays on the record after resolution"
    )
    assert resolved["notification_status"] == "FHWA_REPORTED"
    assert resolved["resolution_note"] is not None

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "OPEN"
    assert structure["open_critical_finding_count"] == 0
    assert structure["inspection_interval_months"] == 12
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-09-02", "next_inspection_due_date"
    )
