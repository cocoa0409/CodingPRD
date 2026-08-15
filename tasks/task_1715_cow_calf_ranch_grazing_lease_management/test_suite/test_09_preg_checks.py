"""Pregnancy checks: creation gate, accounting identity, rate computation,
finalize cascade, and terminal idempotency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_pct1,
    create_breeding_season,
    create_herd_group,
    create_preg_check_payload,
    create_ranch,
    drive_season_to_gestation,
    finalize_preg_check_payload,
    get_herd_group,
    get_success_data,
    setup_ranch_with_group,
    validate_error,
    validate_success,
)

HERD_MGR = TEST_USERS["herd_manager_headers"]


def _season_in_gestation(exposed_head_count=40):
    ranch, group = setup_ranch_with_group(head_count=60)
    season = drive_season_to_gestation(ranch["id"], group["id"],
                                       exposed_head_count=exposed_head_count)
    return ranch, group, season


class TestPregFinalize:
    def test_finalize_computes_rate_and_cascades(self, api):
        """PRD §3.5: "A finalized check computes its `pregnancy_rate_pct` — null
        while the check sits in `DRAFT` — as 100 multiplied by `pregnant_count`
        and divided by `exposed_head_count`, rounded half-up to 1 decimal
        place."
        PRD §3.5: "Two cascades follow at the same moment: the `open_count` is
        added onto the bred herd group's `marked_open_head`, flagging those head
        as cull candidates, and the season itself moves from `PREG_CHECK` to
        `CLOSED`, its terminal state."

        Design: Corner/calculations/preg_finalize_accounting_and_rate
        """
        ranch, group, season = _season_in_gestation()
        pc = get_success_data(api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), HERD_MGR))
        assert pc["check_status"] == "DRAFT"
        assert pc["exposed_head_count"] == 40, "snapshot of the season exposure"
        assert pc["pregnancy_rate_pct"] is None

        done = validate_success(api.finalize_preg_check(
            pc["id"], finalize_preg_check_payload(36, 3, 1), HERD_MGR))
        assert done["check_status"] == "FINALIZED"
        assert_pct1(done["pregnancy_rate_pct"], 90.0, "100 x 36 / 40")
        assert get_herd_group(group["id"])["marked_open_head"] == 3
        season_after = get_success_data(api.get_breeding_season(season["id"],
                                                                HERD_MGR))
        assert season_after["season_status"] == "CLOSED"

    def test_count_mismatch_rejected(self, api):
        """PRD §3.5: "The `HerdManager` supplies `pregnant_count`, `open_count`,
        and `dead_count`, and the three must sum exactly to the check's
        snapshotted `exposed_head_count` — any other arithmetic is rejected with
        `ERR_PREG_COUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/preg_count_mismatch_rejected
        """
        ranch, _group, season = _season_in_gestation()
        pc = get_success_data(api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), HERD_MGR))
        # 36 + 3 + 0 = 39 != 40 exposed.
        resp = api.finalize_preg_check(
            pc["id"], finalize_preg_check_payload(36, 3, 0), HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_PREG_COUNT_MISMATCH,
                       expected_status=422)
        after = get_success_data(api.get_preg_check(pc["id"], HERD_MGR))
        assert after["check_status"] == "DRAFT"

    def test_double_finalize_rejected_and_not_reapplied(self, api):
        """PRD §3.5: "The finalized check, in `FINALIZED`, is likewise
        terminal."
        PRD §2.8: "Terminal-state rejection: a resource that has reached a
        terminal state refuses all further transitions (`ERR_ALREADY_TERMINAL`)."

        Design: Corner/state_machines/preg_check_double_finalize_rejected
        """
        ranch, group, season = _season_in_gestation()
        pc = get_success_data(api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), HERD_MGR))
        validate_success(api.finalize_preg_check(
            pc["id"], finalize_preg_check_payload(36, 3, 1), HERD_MGR))

        resp = api.finalize_preg_check(
            pc["id"], finalize_preg_check_payload(36, 3, 1), HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert get_herd_group(group["id"])["marked_open_head"] == 3, (
            "side effects applied exactly once, not re-applied"
        )


class TestPregCheckCreationGates:
    def test_preg_check_wrong_season_state_rejected(self, api):
        """PRD §3.5: "A season still in any other state refuses the check with
        `ERR_SEASON_NOT_IN_GESTATION` (HTTP 400)"

        Design: Corner/validations/preg_check_wrong_season_state_rejected
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=25)
        assert season["season_status"] == "PLANNED"
        resp = api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_IN_GESTATION,
                       expected_status=400)

    def test_second_preg_check_rejected(self, api):
        """PRD §3.5: "because exactly one pregnancy check may exist per season,
        a second attempt against the same season fails with
        `ERR_PREG_CHECK_ALREADY_EXISTS` (HTTP 409)"
        PRD §2.8: "the first failing check determines the returned error — later
        checks are never evaluated once an earlier one has failed." Creating the
        first check pushes the season from `GESTATION` into `PREG_CHECK`
        (§3.5), so on a second attempt the gestation state gate (cascade
        priority 8) fails before the one-per-season uniqueness rule (priority
        17) is ever evaluated, and the surfaced error is
        `ERR_SEASON_NOT_IN_GESTATION`.

        Design: Corner/validations/second_preg_check_rejected
        """
        ranch, _group, season = _season_in_gestation(exposed_head_count=25)
        first = get_success_data(api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"]), HERD_MGR))
        assert first["check_status"] == "DRAFT"
        resp = api.create_preg_check(
            create_preg_check_payload(season["id"], ranch["id"],
                                      check_date="2026-09-10"), HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_IN_GESTATION,
                       expected_status=400)
