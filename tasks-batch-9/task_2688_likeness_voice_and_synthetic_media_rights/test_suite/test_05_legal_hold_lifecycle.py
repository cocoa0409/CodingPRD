"""Impoundment and release: what a legal hold restores, and what it never does."""

from test_helpers import assertions, fixtures

CLIP_SEVEN_DETECTION = {
    "detection_source": "MONITORING_FEED",
    "suspect_url": "https://example.net/clip-7",
    "detected_channel": "ADVERTISING",
    "detected_state_code": "CA",
    "detected_view_count": 8_000_000,
    "match_confidence": 0.9,
}

MANUAL_REPORT_DETECTION = {
    "detection_source": "MANUAL_REPORT",
    "suspect_url": "https://pirate.example/clip-9",
    "detected_channel": "ADVERTISING",
    "detected_state_code": "CA",
    "detected_view_count": 8_000_000,
    "match_confidence": 0.900,
}

LONG_RETENTION = {"biometric_retention_max_days": 3650}

SECOND_ASSET = {
    "asset_kind": "FACE_SCAN",
    "capture_ref": "cap-002",
    "storage_class": "COLD_ARCHIVE",
    "payload_digest": "sha256:bbb",
}


def _case_over_an_asset_already_mid_schedule():
    """One sample whose purge is already scheduled, with a takedown issued."""
    scenario = fixtures.campaign_stored_asset()
    fixtures.move_clock("2027-08-01T00:00:00Z", scenario["admin_headers"])
    fixtures.run_sweep(scenario)
    fixtures.open_case(scenario, CLIP_SEVEN_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    return scenario


def test_escalation_impounds_a_scheduled_asset_and_remembers_where_it_came_from():
    """The hold records PURGE_SCHEDULED, not the machine's initial state.

    The PRD states: "Because litigation is now live, hop two impounds evidence:
    every biometric asset of this case's talent whose `status` is `STORED` or
    `PURGE_SCHEDULED` moves to `LEGAL_HOLD`, recording `held_from_status` as
    exactly the status it left so the release can resume the same schedule, and
    leaving `purge_due_at` untouched; `legal_hold_applied_count` is set to the
    number of assets moved." The earlier sweep put the asset mid-schedule: "First,
    every asset in `STORED` whose `retention_until` is at or before the current
    logical instant moves to `PURGE_SCHEDULED` with `purge_due_at` set to
    `retention_until` advanced by seven days."

    Design: Difficulty/non_linear_state_machine/asset_legal_hold_round_trip_restores_purge_schedule
    """
    scenario = _case_over_an_asset_already_mid_schedule()

    scheduled = fixtures.refresh_asset(scenario)
    assert scheduled["status"] == "PURGE_SCHEDULED"
    assert scheduled["purge_due_at"] == "2027-08-08T00:00:00Z"

    fixtures.escalate_case(scenario)

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "LEGAL_HOLD"
    assert asset["held_from_status"] == "PURGE_SCHEDULED"
    assert asset["purge_due_at"] == "2027-08-08T00:00:00Z"

    case = fixtures.refresh_case(scenario)
    assert case["status"] == "LEGAL_ESCALATED"
    assert case["severity_score"] == 0.7850
    assert case["legal_hold_applied_count"] == 1

    talent = fixtures.read_talent(scenario)
    assertions.assert_posture(talent, "FROZEN")
    assertions.assert_talent_counters(talent, legal_hold_asset_count=1)


def test_release_resumes_the_interrupted_schedule_instead_of_returning_to_storage():
    """Closure lands the asset back in PURGE_SCHEDULED with its deadline intact.

    The PRD states: "Both escalated closures release what the escalation
    impounded, but only when no other infringement case of this same talent
    remains in `LEGAL_ESCALATED`: every biometric asset in `LEGAL_HOLD` returns to
    exactly its `held_from_status` — `LEGAL_HOLD → STORED` for one held from
    storage, `LEGAL_HOLD → PURGE_SCHEDULED` for one held mid-schedule — and every
    digital replica quarantined with `quarantine_reason` of `SOURCE_LEGAL_HOLD`
    returns to exactly its `held_from_status`, with `held_from_status` and
    `quarantine_reason` cleared on both."

    Design: Difficulty/non_linear_state_machine/asset_legal_hold_round_trip_restores_purge_schedule
    """
    scenario = _case_over_an_asset_already_mid_schedule()
    fixtures.escalate_case(scenario)

    fixtures.close_case(scenario, "SETTLED", headers=scenario["second_admin_headers"])

    asset = fixtures.refresh_asset(scenario)
    assert asset["status"] == "PURGE_SCHEDULED"
    assert asset["status"] != "STORED"
    assert asset["held_from_status"] is None
    assert asset["purge_due_at"] == "2027-08-08T00:00:00Z"
    assert asset["retention_until"] == "2027-08-01T00:00:00Z"

    case = fixtures.refresh_case(scenario)
    assert case["status"] == "CLOSED_SETTLED"
    assert case["closure_outcome"] == "SETTLED"
    assert case["legal_hold_applied_count"] == 1

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(talent, legal_hold_asset_count=0)
    assertions.assert_posture(talent, "CLEAR")


def _two_stored_assets_under_an_issued_license():
    """Two samples — only the first feeding the replica — and a live licence chain."""
    scenario = fixtures.campaign_issued_license(profile_overrides=LONG_RETENTION)
    fixtures.register_biometric_asset(scenario, SECOND_ASSET)
    return scenario


def test_escalation_impounds_every_stored_sample_and_cascades_to_the_licence():
    """Both samples go on hold, though only one of them trained the replica.

    The PRD states: "Because that material is impounded, hop three moves every
    digital replica of this talent whose `source_asset_ids` intersects the newly
    held assets and whose `status` is `BUILT` or `APPROVED_FOR_USE` to
    `QUARANTINED`, with `quarantine_reason` of `SOURCE_LEGAL_HOLD` and
    `held_from_status` recorded." Because a case is escalated, "If any infringement
    case of this talent has status `LEGAL_ESCALATED`, the posture is `FROZEN`."

    Design: Difficulty/compensating_invariant/legal_hold_counters_restored_while_removal_obligations_persist
    """
    scenario = _two_stored_assets_under_an_issued_license()
    first_asset, second_asset = scenario["assets"]

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(
        talent, legal_hold_asset_count=0, open_removal_obligation_count=0
    )
    assertions.assert_posture(talent, "CLEAR")
    for asset in (first_asset, second_asset):
        fresh = fixtures.refresh_asset(scenario, asset)
        assert fresh["status"] == "STORED"
        assert fresh["held_from_status"] is None
    assert fixtures.refresh_replica(scenario)["open_license_count"] == 1

    fixtures.open_case(scenario, MANUAL_REPORT_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)

    for asset in (first_asset, second_asset):
        fresh = fixtures.refresh_asset(scenario, asset)
        assert fresh["status"] == "LEGAL_HOLD"
        assert fresh["held_from_status"] == "STORED"

    case = fixtures.refresh_case(scenario)
    assert case["status"] == "LEGAL_ESCALATED"
    assert case["legal_hold_applied_count"] == 2

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "QUARANTINED"
    assert replica["quarantine_reason"] == "SOURCE_LEGAL_HOLD"
    assert replica["held_from_status"] == "APPROVED_FOR_USE"
    assert fixtures.refresh_performance(scenario)["review_status"] == "WITHDRAWN"

    license_row = fixtures.refresh_license(scenario)
    assert license_row["distribution_status"] == "REMOVAL_PENDING"
    assert license_row["removal_reason"] == "REPLICA_QUARANTINED"
    assert license_row["removal_deadline"] == "2026-08-15T00:00:00Z"

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(
        talent, legal_hold_asset_count=2, open_removal_obligation_count=1
    )
    assertions.assert_posture(talent, "FROZEN")


def test_closure_restores_the_holds_but_leaves_the_removal_obligation_standing():
    """The hold bookkeeping is conserved; the withdrawal and the removal are not.

    The PRD states: "Withdrawn performances and licenses in `REMOVAL_PENDING` are
    **not** restored: those hops are irreversible by design, because content that
    came out of distribution under a legal cloud does not go back automatically."
    So the posture cannot fall all the way back: "and when that escalated case is
    closed as `CLOSED_SETTLED` while two removal obligations are still open, the
    posture becomes `RESTRICTED` rather than `CLEAR`."

    Design: Difficulty/compensating_invariant/legal_hold_counters_restored_while_removal_obligations_persist
    """
    scenario = _two_stored_assets_under_an_issued_license()
    first_asset, second_asset = scenario["assets"]
    fixtures.open_case(scenario, MANUAL_REPORT_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)

    fixtures.close_case(scenario, "LITIGATED", headers=scenario["second_admin_headers"])

    for asset in (first_asset, second_asset):
        fresh = fixtures.refresh_asset(scenario, asset)
        assert fresh["status"] == "STORED"
        assert fresh["held_from_status"] is None

    replica = fixtures.refresh_replica(scenario)
    assert replica["status"] == "APPROVED_FOR_USE"
    assertions.assert_fields_null(replica, "quarantine_reason", "held_from_status")

    assert fixtures.refresh_performance(scenario)["review_status"] == "WITHDRAWN"
    assert fixtures.refresh_license(scenario)["distribution_status"] == "REMOVAL_PENDING"

    case = fixtures.refresh_case(scenario)
    assert case["status"] == "CLOSED_LITIGATED"
    assert case["closure_outcome"] == "LITIGATED"
    assert case["legal_hold_applied_count"] == 2

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(
        talent, legal_hold_asset_count=0, open_removal_obligation_count=1
    )
    assertions.assert_posture(talent, "RESTRICTED")


def test_only_the_licensees_removal_confirmation_clears_the_last_counter():
    """With the obligation discharged the posture finally returns to CLEAR.

    The PRD states: "Confirmation moves `distribution_status` `REMOVAL_PENDING →
    REMOVAL_CONFIRMED`, stamps `removal_confirmed_at` with the logical instant,
    decreases the talent's `open_removal_obligation_count` by one with the posture
    recomputed, decreases the replica's `open_license_count` by one, and advances
    the `version` of the license, the talent and the replica." None of this touches
    the ledger, whose roll-up stays at the four entries the chain already posted.

    Design: Difficulty/compensating_invariant/legal_hold_counters_restored_while_removal_obligations_persist
    """
    scenario = _two_stored_assets_under_an_issued_license()
    fixtures.open_case(scenario, MANUAL_REPORT_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    fixtures.escalate_case(scenario)
    fixtures.close_case(scenario, "LITIGATED", headers=scenario["second_admin_headers"])

    fixtures.confirm_removal(scenario)

    license_row = fixtures.refresh_license(scenario)
    assert license_row["distribution_status"] == "REMOVAL_CONFIRMED"
    assert license_row["removal_confirmed_at"] == "2026-08-01T00:00:00Z"
    assert license_row["compliance_status"] == "PENDING_LABEL"
    assert fixtures.refresh_replica(scenario)["open_license_count"] == 0

    talent = fixtures.read_talent(scenario)
    assertions.assert_talent_counters(
        talent, legal_hold_asset_count=0, open_removal_obligation_count=0
    )
    assertions.assert_posture(talent, "CLEAR")

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL", "REVERSAL"],
    )
    assertions.assert_ledger_sums_to(entries, 770_250)
    assert fixtures.refresh_grant(scenario)["total_compensation_cents"] == 770_250
