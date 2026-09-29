"""Corner cases where one row's transition reconciles a projection on its parent or
supersedes a sibling row in the same request."""

from test_helpers import (
    BalanceRecordStatus,
    ComplaintStatus,
    Disposition,
    assert_instant,
    assert_liters,
    factories,
    fixtures,
    get_success_data,
    make_service_technician_headers,
)


def test_the_second_applied_balance_repoints_the_line_and_supersedes_the_first(api):
    """PRD §3.5: "Applying advances the record `PROPOSED → APPLIED`, moves every other record
    on the same line that was `APPLIED` to `SUPERSEDED` in ascending `created_at` order, makes
    the line's `applied_psi` and `applied_co2_pct` resolve to this record's proposed figures,
    and increments the line's `version` by 1 again."
    PRD §3.5: "A surviving proposal is stored in `PROPOSED` with `proposed_by_technician_id`
    taken from `X-User-ID` and `decision_note` null, and — importantly — it increments the
    target line's `version` by 1."
    PRD §3.2: "A newly registered line opens in `IN_SERVICE` — the only other value `status`
    ever takes is `OUT_OF_SERVICE` — with `compliance_flag` `COMPLIANT`, `last_chemical_type`
    `NONE`, and `last_cleaned_at`, `next_due_at`, `applied_psi` and `applied_co2_pct` all null
    and `days_overdue` 0."

    Design: Corner/state_machines/corner_applying_a_second_balance_record_supersedes_the_first_on_that_line
    """
    ground = fixtures.setup_started_visit(api, venue_name="Anchor Alehouse", lot_specs=())
    line = ground["line"]
    technician_id = ground["technician"]["id"]
    assert line["version"] == 1
    assert line["applied_psi"] is None
    assert line["applied_co2_pct"] is None

    first = fixtures.propose_balance(
        api,
        ground["visit"]["id"],
        line["id"],
        1,
        technician_id,
        measured_temp_f=40.0,
        proposed_applied_psi=13.6,
        proposed_co2_pct=59.2,
    )
    applied_first = get_success_data(
        api.decide_balance_record(
            first["id"],
            factories.balance_decision_payload("APPLY", "first balance of the day"),
            make_service_technician_headers(technician_id),
        )
    )
    assert applied_first["status"] == BalanceRecordStatus.APPLIED
    after_first = fixtures.read_line(api, line["id"])
    assert after_first["applied_psi"] == 13.60
    assert after_first["applied_co2_pct"] == 59.2
    # One proposal plus one application moved the line's version twice.
    assert after_first["version"] == 3

    second = fixtures.propose_balance(
        api,
        ground["visit"]["id"],
        line["id"],
        3,
        technician_id,
        measured_temp_f=38.0,
        proposed_applied_psi=13.6,
        proposed_co2_pct=48.5,
    )
    applied_second = get_success_data(
        api.decide_balance_record(
            second["id"],
            factories.balance_decision_payload("APPLY", "recut after the cooler pulled down"),
            make_service_technician_headers(technician_id),
        )
    )

    assert applied_second["status"] == BalanceRecordStatus.APPLIED
    assert (
        fixtures.read_balance_record(api, first["id"])["status"]
        == BalanceRecordStatus.SUPERSEDED
    )
    after_second = fixtures.read_line(api, line["id"])
    assert after_second["applied_psi"] == 13.60
    # The projection now reads the newest applied record's blend, not the first's.
    assert after_second["applied_co2_pct"] == 48.5
    assert after_second["version"] == 5


def test_the_open_complaint_counter_follows_every_child_transition(api):
    """PRD §3.8: "The account's `open_complaint_count`, which counts complaints in `OPEN`,
    `DIAGNOSING`, `AWAITING_PARTS` or `ESCALATED`, is recomputed."
    PRD §3.8: "An escalation is the auditor handing the problem to the brewer: it is available
    from `DIAGNOSING` or `AWAITING_PARTS`, stamps `escalated_by_user_id` with the acting
    `X-User-ID`, and leaves the complaint counted in the account's `open_complaint_count`,
    because nothing has actually been fixed."
    PRD §3.8: "Reopening raises `reopen_count` by 1, resets `diagnostic_round` to 0 so a fresh
    set of three rounds becomes available, and clears `resolved_at`, `closed_by_user_id`,
    `measured_waste_liters`, `settled_yield_loss_liters` and `settled_yield_loss_cents` back to
    null."
    PRD §3.8: "What survives the loop is the intake snapshot: `reported_at`, `days_at_risk` and
    both provisional figures are never recomputed, so the estimate a reopened complaint carries
    is still the one struck the day it was first filed."

    Design: Corner/state_machines/corner_open_complaint_count_tracks_intake_resolution_escalation_and_reopen
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(
        api,
        venue_name="Anchor Alehouse",
        lines=(
            fixtures.DEFAULT_LINE,
            {
                "line_number": 2,
                "run_length_feet": 15,
                "vertical_rise_feet": 3,
                "inner_diameter_inches": 0.375,
                "beer_style_group": "ALE",
                "average_daily_throughput_liters": 8.0,
            },
        ),
    )
    account_id = venue["account"]["id"]
    assert venue["account"]["open_complaint_count"] == 0

    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    foamy = fixtures.file_complaint(api, account_id, venue["lines"][0]["id"], "FOAMY_POUR")
    slow = fixtures.file_complaint(api, account_id, venue["lines"][1]["id"], "SLOW_POUR")
    assert foamy["status"] == ComplaintStatus.OPEN
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 2
    intake_liters = foamy["provisional_yield_loss_liters"]
    intake_cents = foamy["provisional_yield_loss_cents"]
    intake_reported_at = foamy["reported_at"]
    intake_days_at_risk = foamy["days_at_risk"]

    # An escalation is only available once a round has been worked.
    fixtures.run_diagnostic_round(api, slow["id"])

    fixtures.set_clock(api, "2026-08-11T09:00:00Z")
    resolved = fixtures.close_complaint(
        api, foamy["id"], disposition=Disposition.RESOLVED, measured_waste_liters=4.0
    )
    assert resolved["status"] == ComplaintStatus.RESOLVED
    assert resolved["settled_yield_loss_liters"] is not None
    assert resolved["settled_yield_loss_cents"] is not None
    # A resolved complaint drops out of the count.
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 1

    escalated = fixtures.close_complaint(
        api, slow["id"], disposition=Disposition.ESCALATED, measured_waste_liters=2.5
    )
    assert escalated["status"] == ComplaintStatus.ESCALATED
    assert escalated["escalated_by_user_id"] == "auditor-1"
    # An escalated complaint is still an open complaint.
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 1

    fixtures.set_clock(api, "2026-08-12T09:00:00Z")
    reopened = fixtures.reopen_complaint(
        api, foamy["id"], account_id, "The foam came straight back on the next keg."
    )

    assert reopened["status"] == ComplaintStatus.OPEN
    assert reopened["reopen_count"] == 1
    assert reopened["diagnostic_round"] == 0
    assert reopened["settled_yield_loss_liters"] is None
    assert reopened["settled_yield_loss_cents"] is None
    assert reopened["resolved_at"] is None
    assert reopened["measured_waste_liters"] is None
    # The intake snapshot is never recomputed.
    assert_liters(reopened["provisional_yield_loss_liters"], intake_liters)
    assert reopened["provisional_yield_loss_cents"] == intake_cents
    assert reopened["days_at_risk"] == intake_days_at_risk
    assert_instant(reopened["reported_at"], intake_reported_at, label="reported_at")
    assert fixtures.read_account(api, account_id)["open_complaint_count"] == 2
