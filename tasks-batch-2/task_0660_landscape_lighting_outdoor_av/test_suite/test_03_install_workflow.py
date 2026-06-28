"""Install job: the two-branch fork-join to ENERGIZED, the wiring-before-fixtures
safety gate, and terminal-state lockdown on cancel.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_project_with_transformer_and_zone,
    assign_fixtures_to_zone,
    setup_accepted_quote,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]


def _in_progress_job_with_one_fixture():
    """An IN_PROGRESS install job on a project with one STAGED transformer and
    one PLANNED zoned 80W fixture (PATH-80). Returns (ctx, job_id, fixture_id,
    transformer_id)."""
    ctx = setup_project_with_transformer_and_zone()
    fixtures = assign_fixtures_to_zone(ctx, [{"model_code": "PATH-80", "category": "PATH",
                                              "wattage_w": 80, "purchase_price_cents": 4000}])
    setup_accepted_quote(ctx, lines=[{"model_code": "PATH-80", "quantity": 1, "unit_price_cents": 4000}])
    job = validate_success(api_client.create_install_job(
        F.create_install_job_payload(ctx["project_id"], ctx["quote_id"]), TECH), expected_status=201)
    validate_success(api_client.start_install_job(job["id"], TECH))
    return ctx, job["id"], fixtures[0]["id"], ctx["tx_id"]


def test_fork_join_energizes_after_both_branches(api):
    """PRD §3.5: "When both branches have completed — `wiring_status` is `WIRED`
    and `fixtures_status` is `MOUNTED` — the join fires: the install job moves
    from `IN_PROGRESS` to `ENERGIZED` (terminal), and as a cascade the project's
    `commercial_status` advances from `ACCEPTED` to `INSTALLED`".

    Completing wiring then fixtures drives the join: job ENERGIZED, both branch
    flags advanced, project INSTALLED.

    Design: Difficulty/non_linear_state_machine/install_job_fork_join_energize
    """
    ctx, job_id, fixture_id, tx_id = _in_progress_job_with_one_fixture()
    validate_success(api.complete_wiring(job_id, TECH))
    job = validate_success(api.complete_fixtures(job_id, TECH))
    assert job["wiring_status"] == "WIRED", job["wiring_status"]
    assert job["fixtures_status"] == "MOUNTED", job["fixtures_status"]
    assert job["status"] == "ENERGIZED", job["status"]

    project = validate_success(api.get_project(ctx["project_id"], DESIGNER))
    assert project["commercial_status"] == "INSTALLED", project["commercial_status"]


def test_fork_join_branch_side_effects_energize_transformer_and_install_fixture(api):
    """PRD §3.5: "it sets `wiring_status` to `WIRED` and, as a cascade, energizes
    every transformer on the job's project that is currently `STAGED`, moving each
    from `STAGED` to `ENERGIZED`." and "Completing fixtures sets `fixtures_status`
    to `MOUNTED` and, as a cascade, transitions every fixture on the project that
    is `PLANNED` and has a non-null `zone_id` from `PLANNED` to `INSTALLED`".

    The wiring branch energizes the transformer; the fixtures branch installs the
    fixture — divergent per-branch side effects.

    Design: Difficulty/non_linear_state_machine/install_job_fork_join_energize
    """
    ctx, job_id, fixture_id, tx_id = _in_progress_job_with_one_fixture()
    validate_success(api.complete_wiring(job_id, TECH))

    tx_after_wiring = validate_success(api.get_transformer(tx_id, DESIGNER))
    assert tx_after_wiring["status"] == "ENERGIZED", tx_after_wiring["status"]

    validate_success(api.complete_fixtures(job_id, TECH))
    fixture = validate_success(api.get_fixture(fixture_id, DESIGNER))
    assert fixture["status"] == "INSTALLED", fixture["status"]


def test_complete_fixtures_before_wiring_rejected(api):
    """PRD §3.5: "completing the fixtures branch is allowed only while the job is
    `IN_PROGRESS` and `fixtures_status` is `PENDING`, and it additionally requires
    that `wiring_status` already be `WIRED`, since fixtures may only be mounted
    onto energized wiring. An attempt to complete fixtures before wiring is
    complete is rejected with `ERR_WIRING_NOT_COMPLETE`."

    Design: Corner/state_machines/complete_fixtures_before_wiring_returns_wiring_not_complete
    """
    ctx, job_id, fixture_id, tx_id = _in_progress_job_with_one_fixture()
    validate_error(api.complete_fixtures(job_id, TECH), ApiErrorId.ERR_WIRING_NOT_COMPLETE.value)
    job = validate_success(api.get_install_job(job_id, TECH))
    assert job["fixtures_status"] == "PENDING", job["fixtures_status"]


def test_cancel_energized_install_job_invalid_state(api):
    """PRD §3.5: "A scheduled job may instead be cancelled, moving it to
    `CANCELLED` (terminal)." and §3.5: "the install job moves from `IN_PROGRESS`
    to `ENERGIZED` (terminal)".

    Cancel is only defined from SCHEDULED; an ENERGIZED job cannot be cancelled.

    Design: Corner/state_machines/cancel_install_job_after_energized_invalid_state
    """
    ctx, job_id, fixture_id, tx_id = _in_progress_job_with_one_fixture()
    validate_success(api.complete_wiring(job_id, TECH))
    validate_success(api.complete_fixtures(job_id, TECH))
    validate_error(api.cancel_install_job(job_id, TECH), ApiErrorId.ERR_INVALID_STATE.value)
    job = validate_success(api.get_install_job(job_id, TECH))
    assert job["status"] == "ENERGIZED", job["status"]
