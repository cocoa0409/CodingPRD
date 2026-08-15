"""Biosecurity audits, quarantine branching, and house release (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    assert_house,
    record_audit,
    setup_harvested_flock,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["service_tech_headers"]


def _setup_house_in_downtime(api):
    """House harvested on 2026-09-10: DOWNTIME with downtime_until
    2026-09-24; logical clock at 2026-09-10."""
    ctx = setup_harvested_flock(grower_code="G-Q", full_name="Quarantine Grower",
                                contract_no="C-Q", group_code="WK-36",
                                week_ending_date="2026-10-10", flock_no="F-Q",
                                set_clock_to="2026-08-01T00:00:00Z")
    house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
    assert house["house_status"] == "DOWNTIME"
    assert house["downtime_until"] == "2026-09-24"
    return ctx


class TestHouseDowntimeQuarantineBranching:
    def test_fail_audit_forks_downtime_to_quarantine(self, api):
        """PRD §3.4: "A failing audit cascades immediately: the house moves
        `DOWNTIME` → `QUARANTINED` or `ACTIVE` → `QUARANTINED` depending on
        where it stood, and its `downtime_until` becomes the later of its
        current value and the audit date plus the quarantine days."

        Design: Difficulty/non_linear_state_machine/house_downtime_quarantine_branching
        """
        ctx = _setup_house_in_downtime(api)

        audit = validate_success(
            api.record_audit(ctx["house"]["id"],
                             {"audit_date": "2026-09-12", "result": "FAIL",
                              "quarantine_days": 21},
                             TECH),
            expected_status=201)
        assert audit["result"] == "FAIL"

        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert_house(house)
        assert house["house_status"] == "QUARANTINED"
        # max(2026-09-24 catch downtime, 2026-09-12 + 21d) -> 2026-10-03.
        assert house["downtime_until"] == "2026-10-03", \
            "the later of the catch downtime and the quarantine window wins"

    def test_pass_audit_then_release_rejoins_active(self, api):
        """PRD §3.4: "Releasing quarantine moves a house `QUARANTINED` →
        `ACTIVE`; it requires the existence of a `PASS` audit for the house
        dated on or after the `FAIL` audit that triggered the quarantine, and
        likewise clears `downtime_until` to null."

        Design: Difficulty/non_linear_state_machine/house_downtime_quarantine_branching
        """
        ctx = _setup_house_in_downtime(api)
        record_audit(ctx["house"]["id"], "2026-09-12", "FAIL", 21)
        record_audit(ctx["house"]["id"], "2026-09-20", "PASS", 0)

        released = validate_success(
            api.release_quarantine(ctx["house"]["id"], TECH))
        assert released["house_status"] == "ACTIVE"
        assert released["downtime_until"] is None, \
            "release clears the downtime window outright"

        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert house["house_status"] == "ACTIVE"
        assert house["downtime_until"] is None
