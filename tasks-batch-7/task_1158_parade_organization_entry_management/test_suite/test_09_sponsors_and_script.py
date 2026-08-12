"""Sponsor packages and the announcer script: per-item rounding, allocated
seconds, tier-minimum finalization, and conditional references."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_sponsor, assert_script_item,
)

COMMITTEE = th.make_committee_admin_headers()


class TestScriptRounding:
    """Difficulty: script_seconds_per_item_round_then_sum.
    Two SPONSOR_READ items of 0.759 minutes each round to 46 s per item; the
    sponsor total is 92 s (sum-then-round would give 91 s)."""

    def _setup(self, api):
        parade = th.create_parade(name="Script Parade")
        sponsor = th.create_active_sponsor(parade["id"], tier="GOLD",
                                           sponsor_name="Acme Corp")
        item1 = th.create_approved_sponsor_read(parade["id"], sponsor["id"], 0.759, 1)
        item2 = th.create_approved_sponsor_read(parade["id"], sponsor["id"], 0.759, 2)
        return parade, sponsor, item1, item2

    def test_each_item_rounds_half_up_individually(self, api):
        """PRD §3.8: "Every item's `duration_seconds` is derived by multiplying
        its `duration_minutes` by sixty and rounding half-up to a whole second,
        per item."

        Design: Difficulty/combinatorial_formula/script_seconds_per_item_round_then_sum
        """
        _, _, item1, item2 = self._setup(api)
        for item in (item1, item2):
            assert_script_item(item)
            assert item["duration_seconds"] == 46, (
                f"round_half_up(0.759 x 60 = 45.54) must be 46, got {item['duration_seconds']}"
            )

    def test_totals_sum_already_rounded_item_values(self, api):
        """PRD §3.8: "Totals are then built by summing those already-rounded
        item values; rounding the summed minutes once instead is forbidden,
        because the two orders produce different totals."
        PRD §3.8: "The sponsor-level aggregate `allocated_seconds` sums
        `duration_seconds` over the package's `SPONSOR_READ` items in
        `APPROVED` or `LOCKED` status, and the parade-level
        `sponsor_seconds_allocated` does the same across the whole edition."

        Design: Difficulty/combinatorial_formula/script_seconds_per_item_round_then_sum
        """
        parade, sponsor, _, _ = self._setup(api)
        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], COMMITTEE))
        assert sponsor_after["allocated_seconds"] == 92, (
            f"46 + 46 = 92 per-item-then-sum (sum-then-round would give 91), "
            f"got {sponsor_after['allocated_seconds']}"
        )
        parade_after = validate_success(api.get_parade(parade["id"], COMMITTEE))
        assert parade_after["sponsor_seconds_allocated"] == 92


class TestScriptSecondsInvariant:
    """Difficulty: script_item_add_then_cancel_restores_sponsor_seconds."""

    def _setup(self, api, parade_name):
        parade = th.create_parade(name=parade_name)
        sponsor = th.create_active_sponsor(parade["id"], tier="GOLD",
                                           sponsor_name="Steady Gold")
        th.create_approved_sponsor_read(parade["id"], sponsor["id"], 1.0, 1)
        th.create_approved_sponsor_read(parade["id"], sponsor["id"], 1.0, 2)
        return parade, sponsor

    def test_approve_adds_item_seconds(self, api):
        """PRD §3.8: "Approving moves an item from `DRAFT` to `APPROVED` — only
        while the parade is unfrozen — and recomputes both second counters when
        the item is a `SPONSOR_READ`."

        Design: Difficulty/compensating_invariant/script_item_add_then_cancel_restores_sponsor_seconds
        """
        parade, sponsor = self._setup(api, "Seconds Parade")
        baseline = validate_success(api.get_sponsor(sponsor["id"], COMMITTEE))
        assert baseline["allocated_seconds"] == 120

        item3 = th.create_approved_sponsor_read(parade["id"], sponsor["id"], 1.0, 3)
        after = validate_success(api.get_sponsor(sponsor["id"], COMMITTEE))
        assert after["allocated_seconds"] == 180, (
            f"approving a third 60 s item must add exactly 60, got {after['allocated_seconds']}"
        )
        assert item3["status"] == "APPROVED"

    def test_compensating_cancel_restores_sponsor_and_parade_seconds(self, api):
        """PRD §3.8: "Cancelling moves an item from `DRAFT` or `APPROVED` to
        `CANCELLED`, terminal, and likewise recomputes the counters for sponsor
        reads."

        Design: Difficulty/compensating_invariant/script_item_add_then_cancel_restores_sponsor_seconds
        """
        parade, sponsor = self._setup(api, "Seconds Parade 2")
        item3 = th.create_approved_sponsor_read(parade["id"], sponsor["id"], 1.0, 3)
        cancelled = validate_success(api.cancel_script_item(item3["id"], COMMITTEE))
        assert cancelled["status"] == "CANCELLED"

        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], COMMITTEE))
        assert sponsor_after["allocated_seconds"] == 120, (
            f"the compensating cancel must restore the 120 s baseline exactly, "
            f"got {sponsor_after['allocated_seconds']}"
        )
        parade_after = validate_success(api.get_parade(parade["id"], COMMITTEE))
        assert parade_after["sponsor_seconds_allocated"] == 120


class TestFinalizeScriptGate:
    """Difficulty: gold_sponsor_exactly_120_seconds_passes."""

    def _gold_parade_with_reads(self, api, name, durations):
        parade = th.create_parade(name=name)
        sponsor = th.create_active_sponsor(parade["id"], tier="GOLD",
                                           sponsor_name=f"Gold {name}")
        for i, duration in enumerate(durations, start=1):
            th.create_approved_sponsor_read(parade["id"], sponsor["id"], duration, i)
        return parade

    def test_gold_at_exactly_120_seconds_finalizes(self, api):
        """PRD §3.8: "Before the show goes on, the committee finalizes the
        script — a gate that verifies every `ACTIVE` sponsor package of the
        parade has accumulated at least its tier minimum of recognized airtime:
        120 seconds for `GOLD`, 60 for `SILVER`, and 30 for `BRONZE`, with the
        boundary inclusive so that exactly the minimum passes."
        PRD §3.8: "Any shortfall rejects the finalization with
        `ERR_SPONSOR_MINUTES_UNMET` (HTTP 422); success sets the parade's
        `script_finalized` flag to true."

        Design: Difficulty/boundary_precision_check/gold_sponsor_exactly_120_seconds_passes
        """
        parade = self._gold_parade_with_reads(api, "Sponsor Parade A", [1.0, 1.0])
        finalized = validate_success(api.finalize_script(parade["id"], COMMITTEE))
        assert finalized["script_finalized"] is True, (
            "exactly 120 allocated seconds meets the inclusive GOLD >= 120 gate"
        )

    def test_gold_at_119_seconds_rejected(self, api):
        """PRD §3.8: "Any shortfall rejects the finalization with
        `ERR_SPONSOR_MINUTES_UNMET` (HTTP 422); success sets the parade's
        `script_finalized` flag to true."

        Design: Difficulty/boundary_precision_check/gold_sponsor_exactly_120_seconds_passes
        """
        # 60 + round_half_up(0.98 x 60) = 60 + 59 = 119 seconds < 120.
        parade = self._gold_parade_with_reads(api, "Sponsor Parade B", [1.0, 0.98])
        resp = api.finalize_script(parade["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_MINUTES_UNMET)

        after = validate_success(api.get_parade(parade["id"], COMMITTEE))
        assert after["script_finalized"] is False


class TestScriptItemReferences:

    def test_sponsor_read_missing_sponsor_id_rejected(self, api):
        """PRD §3.8: "Two conditional references apply: a `SPONSOR_READ` item
        must carry a `sponsor_id` naming an `ACTIVE` sponsor package of the
        same parade, and an `ENTRY_INTRO` item must carry an `entry_id` naming
        an entry of the same parade — omitting the required reference is a
        schema failure (`ERR_VALIDATION`), while pointing it at the wrong
        target is a state failure (`ERR_INVALID_STATE`)."

        Design: Corner/validations/sponsor_read_item_missing_required_sponsor_id_returns_invalid_request
        """
        parade = th.create_parade(name="Cond Parade")
        payload = {"item_type": "SPONSOR_READ", "sequence_index": 1, "duration_minutes": 1.0}
        resp = api.create_script_item(parade["id"], payload, COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
