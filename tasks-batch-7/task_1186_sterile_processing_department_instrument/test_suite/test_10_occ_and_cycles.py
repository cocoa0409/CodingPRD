"""Optimistic concurrency on template updates, and the tray state machine's
cyclic loop: one physical tray running the full pipeline twice.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]


def test_occ_template_update_stale_version_rejected(api):
    """PRD §2.7: "Updating a tray template (`PUT /spd/tray-templates/{id}`)
    must carry `expected_template_version` equal to the template's current
    `version`. A successful update increments `TrayTemplate.version` by 1, so
    a subsequent update carrying an older observed version is deterministically
    rejected as stale." "a mismatch with the parent entity's current `version`
    is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_template_update_stale_version_rejected
    """
    tpl = fx.create_template(api)
    assert tpl["version"] == 1

    v2 = validate_success(
        api.update_tray_template(
            tpl["id"], {"name": "General v2", "expected_template_version": 1}, ADMIN
        )
    )
    assert v2["version"] == 2

    stale = api.update_tray_template(
        tpl["id"], {"name": "General v3", "expected_template_version": 1}, ADMIN
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestTrayCyclicLoopRepeatedCycle:
    """One tray runs the full decontamination-to-sterile loop twice (two
    tests, one design instance)."""

    def _run_second_loop(self, api, s):
        lz2 = fx.create_load(api, s.ster["id"], s.tech_a["id"],
                             planned_start_at="2026-05-01T03:00:00Z")
        fx.add_tray_to_load(api, lz2["id"], s.tz["id"], s.tech_a["id"])
        fx.start_load(api, lz2["id"], s.tech_a["id"])
        fx.complete_load(api, lz2["id"], s.tech_a["id"])
        fx.set_clock(api, "2026-05-01T06:00:00Z")
        bi = fx.first_bi_of_load(api, lz2["id"])
        fx.record_bi(api, bi["id"], "NEGATIVE")
        fx.release_load(api, lz2["id"], s.tech_s["id"])
        return lz2

    def test_first_loop_closed_then_tray_returns_to_sterile(self, api):
        """PRD §3.6: "`completed_at` is stamped, its `RESERVED` reservations
        move to `USED`, the trays they held move `IN_USE →
        AWAITING_DECONTAMINATION`". PRD §3.5: "Every member tray moves
        `IN_LOAD → STERILE`".

        Design: Difficulty/non_linear_state_machine/tray_cyclic_loop_repeated_cycle
        """
        s = fx.setup_tray_second_loop_scenario(api)
        rz = validate_success(api.get_tray_reservation(s.rz["id"], ADMIN))
        assert rz["status"] == "USED", "the first loop closed through case completion"
        before = validate_success(api.get_tray(s.tz["id"], ADMIN))
        assert before["status"] == "ASSEMBLED"
        assert before["cycles_completed"] == 1

        self._run_second_loop(api, s)
        after = validate_success(api.get_tray(s.tz["id"], ADMIN))
        assert after["status"] == "STERILE", "the second pass through the cycle"

    def test_second_release_increments_cycles_and_assigns_expiry(self, api):
        """PRD §3.5: "its `sterility_expires_at` is assigned per the
        shelf-life tiers of §2.10, its `cycles_completed` increments by 1";
        PRD §2.10: "A `WRAPPED` tray receives 720 hours (thirty days) of shelf
        life".

        Design: Difficulty/non_linear_state_machine/tray_cyclic_loop_repeated_cycle
        """
        s = fx.setup_tray_second_loop_scenario(api)
        self._run_second_loop(api, s)
        after = validate_success(api.get_tray(s.tz["id"], ADMIN))
        assert after["cycles_completed"] == 2, "incremented once per release"
        assert_instant_equals(after["sterility_expires_at"], "2026-05-31T06:00:00Z",
                              "released 2026-05-01T06:00:00Z + 720h WRAPPED")
