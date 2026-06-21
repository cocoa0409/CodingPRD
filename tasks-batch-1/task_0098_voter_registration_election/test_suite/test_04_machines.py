"""Voting machines, failure reporting, and backup activation.

Covers the backup selector (hit and empty-pool miss), the fail-then-repair
compensating invariant on idle-backup state, the retire-blocked-by-active-backup
guard, OCC on failure reports, and machine list filtering.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
    factories,
)
from test_helpers.test_users import ADMIN, PW1

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Backup selector — empty pool (Difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
def test_failure_with_no_backup_records_no_backup_available(api):
    """PRD §3.6: "If no backup is available, the failure is still recorded with a
    null backup_machine_id and a resolution of NO_BACKUP_AVAILABLE — the absence
    of a backup is an outcome, not an error."

    Design: Difficulty/boundary_precision_check/backup_selector_empty_pool_no_backup_available
    """
    election, precinct, primary = fixtures.setup_precinct_with_primary()
    payload = factories.create_machine_failure_payload(primary["id"], primary["version"])
    data = validate_success(api.create_machine_failure(payload, PW1), 201)
    assert data["resolution"] == "NO_BACKUP_AVAILABLE"
    assert data["backup_machine_id"] is None
    m = validate_success(api.get_voting_machine(primary["id"], ADMIN), 200)
    assert m["status"] == "FAILED", "the failure is still recorded and the primary moves to FAILED"


def test_failure_with_only_a_primary_finds_no_backup(api):
    """PRD §3.9: "It ranks them by capacity descending — activating the
    highest-throughput backup first ... If there are no idle operational backups,
    the outcome is NO_BACKUP_AVAILABLE and no error is raised; the failure row is
    recorded regardless."

    Design: Difficulty/boundary_precision_check/backup_selector_empty_pool_no_backup_available
    """
    election, precinct, primary = fixtures.setup_precinct_with_primary()
    failure = fixtures.report_machine_failure(primary["id"], primary["version"])
    assert failure["resolution"] == "NO_BACKUP_AVAILABLE"
    # The failure row is persisted and readable.
    fetched = validate_success(api.get_machine_failure(failure["id"], ADMIN), 200)
    assert fetched["machine_id"] == primary["id"]
    assert fetched["backup_machine_id"] is None


def test_failure_with_idle_backup_activates_highest_capacity(api):
    """PRD §3.9: "It ranks them by capacity descending — activating the
    highest-throughput backup first — breaking ties by created_at ascending (the
    oldest backup). The first candidate after this ordering is activated."
    PRD §3.6: "If a backup is chosen, the selector sets that backup's
    backup_for_machine_id to the failed machine's identity, records the chosen
    machine in the failure's backup_machine_id, and sets the failure's resolution
    to BACKUP_ACTIVATED."

    Design: Corner/state_machines/report_failure_activates_backup_cross_entity
    """
    election, precinct, primary = fixtures.setup_precinct_with_primary()
    # Two idle backups: capacity 25 and capacity 40 -> the cap-40 must win.
    fixtures.create_voting_machine(precinct["id"], serial="M-2", role="BACKUP", capacity=25)
    m3 = fixtures.create_voting_machine(precinct["id"], serial="M-3", role="BACKUP", capacity=40)
    payload = factories.create_machine_failure_payload(primary["id"], primary["version"])
    data = validate_success(api.create_machine_failure(payload, PW1), 201)
    assert data["resolution"] == "BACKUP_ACTIVATED"
    assert data["backup_machine_id"] == m3["id"], "highest-capacity backup is activated"
    backup = validate_success(api.get_voting_machine(m3["id"], ADMIN), 200)
    assert backup["backup_for_machine_id"] == primary["id"]
    p = validate_success(api.get_voting_machine(primary["id"], ADMIN), 200)
    assert p["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Fail-then-repair conserves idle-backup state (Difficulty: compensating_invariant)
# ---------------------------------------------------------------------------
def test_repair_clears_covering_backup_link(api):
    """PRD §3.6: "A PollWorker repairs a failed machine back to service, moving it
    FAILED -> OPERATIONAL; as a compensating action, if some backup is currently
    covering this machine (its backup_for_machine_id points at this machine), that
    backup's backup_for_machine_id is cleared, releasing it to idle."

    Design: Difficulty/compensating_invariant/fail_then_repair_conserves_backup_idle_state
    """
    election, precinct, primary, backup, failure = fixtures.setup_failed_primary_with_backup()
    # Confirm the backup is currently covering the primary.
    covering = validate_success(api.get_voting_machine(backup["id"], ADMIN), 200)
    assert covering["backup_for_machine_id"] == primary["id"]
    data = validate_success(
        api.transition_voting_machine(primary["id"], {"target_status": "OPERATIONAL"}, PW1), 200
    )
    assert data["status"] == "OPERATIONAL"
    released = validate_success(api.get_voting_machine(backup["id"], ADMIN), 200)
    assert released["backup_for_machine_id"] is None, "repair releases the covering backup to idle"


def test_fail_then_repair_round_trips_primary_to_operational(api):
    """PRD §3.6: "A PollWorker repairs a failed machine back to service, moving it
    FAILED -> OPERATIONAL; as a compensating action, if some backup is currently
    covering this machine (its backup_for_machine_id points at this machine), that
    backup's backup_for_machine_id is cleared, releasing it to idle."

    Design: Difficulty/compensating_invariant/fail_then_repair_conserves_backup_idle_state
    """
    election, precinct, primary, backup, failure = fixtures.setup_failed_primary_with_backup()
    failed = validate_success(api.get_voting_machine(primary["id"], ADMIN), 200)
    assert failed["status"] == "FAILED"
    repaired = validate_success(
        api.transition_voting_machine(primary["id"], {"target_status": "OPERATIONAL"}, PW1), 200
    )
    assert repaired["status"] == "OPERATIONAL", "FAILED -> OPERATIONAL repair round-trips the primary"


# ---------------------------------------------------------------------------
# Retire guard (Corner: validations) + OCC (Corner: cross_cutting)
# ---------------------------------------------------------------------------
def test_retire_active_backup_returns_backup_in_use(api):
    """PRD §3.6: "A machine in any of OPERATIONAL, FAILED, or REPLACED may be
    retired to the terminal RETIRED state by either a PollWorker or an
    ElectionAdmin, but retirement is blocked while the machine is still serving as
    the active backup of a machine that remains FAILED; such an attempt is refused
    with ERR_BACKUP_IN_USE."

    Design: Corner/validations/retire_active_backup_returns_backup_in_use
    """
    election, precinct, primary, backup, failure = fixtures.setup_failed_primary_with_backup()
    resp = api.transition_voting_machine(backup["id"], {"target_status": "RETIRED"}, ADMIN)
    validate_error(resp, ERR.ERR_BACKUP_IN_USE.value)
    after = validate_success(api.get_voting_machine(backup["id"], ADMIN), 200)
    assert after["status"] == "OPERATIONAL", "the blocked retire leaves the backup OPERATIONAL"


def test_machine_failure_with_stale_version_rejected(api):
    """PRD §2.8: "A request to report a machine failure must include
    expected_machine_version, carrying the version of the target VotingMachine as
    the client last observed it. If that value does not match the machine's
    current version, the report is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_machine_version_on_failure_report
    """
    election, precinct, primary = fixtures.setup_precinct_with_primary()
    stale = primary["version"] - 1
    payload = factories.create_machine_failure_payload(primary["id"], stale)
    validate_error(api.create_machine_failure(payload, PW1), ERR.ERR_STALE_VERSION.value)
    m = validate_success(api.get_voting_machine(primary["id"], ADMIN), 200)
    assert m["status"] == "OPERATIONAL", "a stale failure report leaves the machine OPERATIONAL"

# NOTE (skipped instance):
# Corner/endpoints/get_voting_machines_filtered_by_precinct_reverse_reach asserts that
# GET /voting-machines?precinct_id= returns the precinct's machines. PRD prose never
# states that this endpoint accepts a precinct_id query filter — the §4 table row
# "List voting machines" is endpoint-titular only (fails C2), and no §3.6 sentence
# commits to the filter parameter. Two PRD-only implementers could legitimately diverge
# (filtered vs. unfiltered list), so the claim is not uniquely derivable. Skipped per the
# PRD-first Core rule rather than shipping a weak/under-determined assertion.
