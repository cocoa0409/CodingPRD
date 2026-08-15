"""Difficulty queue A — dual_variant_calc instances (pinned vs current SLA;
tat_total vs tat_clean)."""
import pytest

from test_helpers import (
    assert_instant_equal,
    CLOCK_T0800,
    api_client,
    create_clean_request_payload,
    create_outbreak_event_payload,
    get_success_data,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_all_standards,
    create_bed,
    create_request,
    create_standard,
    create_unit,
    seed_supplies,
    setup_outbreak_active,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


class TestSlaPinnedVsCurrentDivergesOnOutbreak:
    def test_pinned_target_frozen_while_current_estimate_diverges(self, api):
        """PRD §3.3: "The pinned `sla_target_minutes` is the effective time
        standard evaluated at that moment: the `base_minutes` of the clean
        type's standard row, multiplied by the row's `outbreak_multiplier_bps`
        divided by 10000 when the unit's posture is `OUTBREAK` at evaluation
        time, and taken unmultiplied otherwise; the raw value is rounded
        half-up to whole minutes."
        PRD §3.3: "Separately, every read of a request exposes
        `current_estimate_minutes`: the same formula evaluated against the
        clean type's *current* standard row and the unit's *current* posture,
        so the estimate diverges from the pin whenever a standard was edited or
        an outbreak was activated or lifted after pinning."

        Design: Difficulty/dual_variant_calc/sla_pinned_vs_current_estimate_diverges_on_outbreak
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies("DISINFECTANT", "CLOTH")
        b1 = create_bed(unit["id"], "B1", "STANDARD")
        r1 = create_request(b1["id"], "ROUTINE")
        assert r1["sla_target_minutes"] == 45

        setup_outbreak_active(unit["id"], pathogen_class="NOROVIRUS")

        b2 = create_bed(unit["id"], "B2", "STANDARD")
        r2 = create_request(b2["id"], "ROUTINE")

        r1_after = get_success_data(api.get_clean_request(r1["id"], ANY))
        assert r1_after["sla_target_minutes"] == 45
        # round_half_up(45 * 15000/10000) = round_half_up(67.5) = 68.
        assert r1_after["current_estimate_minutes"] == 68
        assert r1_after["pinned_with_outbreak"] is False

        assert r2["sla_target_minutes"] == 68
        assert r2["pinned_with_outbreak"] is True

        unit_after = get_success_data(api.get_unit(unit["id"], ANY))
        assert unit_after["outbreak_posture"] == "OUTBREAK"

    def test_post_outbreak_creation_pins_with_multiplier(self, api):
        """PRD §3.3: "The pinned `sla_target_minutes` is the effective time
        standard evaluated at that moment: the `base_minutes` of the clean
        type's standard row, multiplied by the row's `outbreak_multiplier_bps`
        divided by 10000 when the unit's posture is `OUTBREAK` at evaluation
        time, and taken unmultiplied otherwise."
        PRD §3.3: "The pin also snapshots the inputs that produced it:
        `pinned_base_minutes`, `pinned_outbreak_multiplier_bps`, and
        `pinned_with_outbreak` recording whether the outbreak multiplier
        applied."

        Design: Difficulty/dual_variant_calc/sla_pinned_vs_current_estimate_diverges_on_outbreak
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies("DISINFECTANT", "CLOTH")
        setup_outbreak_active(unit["id"], pathogen_class="NOROVIRUS")

        bed = create_bed(unit["id"], "B1", "STANDARD")
        req = create_request(bed["id"], "ROUTINE")
        assert req["sla_target_minutes"] == 68
        assert req["pinned_base_minutes"] == 45
        assert req["pinned_outbreak_multiplier_bps"] == 15000
        assert req["pinned_with_outbreak"] is True
        assert_instant_equal(req["sla_due_at"], "2026-08-01T09:08:00Z")


class TestTurnaroundTotalVsCleanVariants:
    def test_tat_variants_differ_by_queue_wait(self, api):
        """PRD §3.7: "`tat_total_minutes` is the guest-flow figure: whole
        minutes, rounded down, from the bed's `last_discharge_at` — or from the
        bed's own `created_at` when it was never discharged — to
        `last_ready_at`. `tat_clean_minutes` is the EVS execution figure: whole
        minutes, rounded down, from the verifying request's `first_started_at`
        to its `verified_at`. Both derive from the same lifecycle events, so
        they must differ numerically whenever the request waited in queue
        before starting."

        Design: Difficulty/dual_variant_calc/turnaround_total_vs_clean_variants
        """
        ctx = setup_basic_scenario()
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        # Request created 08:00; starts 08:30 (30 min queue wait).
        set_clock("2026-08-01T08:30:00Z")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T09:15:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=200)

        bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed["bed_status"] == "READY"
        # Bed created 08:00 (never discharged) -> coalesce to created_at.
        assert bed["tat_total_minutes"] == 75
        assert bed["tat_clean_minutes"] == 45
        assert bed["tat_total_minutes"] != bed["tat_clean_minutes"]

    def test_snapshot_reports_both_tat_series(self, api):
        """PRD §3.9: "Over the set of the unit's requests whose `verified_at`
        falls inside the window, the snapshot records `verified_count`, the
        `sla_breach_count` of set members whose `verified_at` came after their
        `sla_due_at`, and four percentile fields: `tat_total_p50_minutes`,
        `tat_total_p90_minutes`, `tat_clean_p50_minutes`, and
        `tat_clean_p90_minutes`."

        Design: Difficulty/dual_variant_calc/turnaround_total_vs_clean_variants
        """
        ctx = setup_basic_scenario()
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        set_clock("2026-08-01T08:30:00Z")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T09:15:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=200)

        # The snapshot window is [unit.created_at, run clock) — end-exclusive
        # per PRD §3.9 — so the run must happen after the 09:15 verification
        # for the request to fall inside the window.
        set_clock("2026-08-01T10:00:00Z")
        snap = get_success_data(api.run_ops_run(ctx["unit"]["id"], ADMIN))
        assert snap["verified_count"] == 1
        assert snap["tat_total_p50_minutes"] == 75
        assert snap["tat_clean_p50_minutes"] == 45
