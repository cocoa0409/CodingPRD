"""Strategy activation and half-open window overlap rules (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    add_active_strategy,
    bootstrap_org,
    create_draft_strategy,
    mgr_headers,
    validate_error,
    validate_success,
)


class TestStrategyWindowOverlap:
    def _bundle_with_active_strategy(self):
        bundle = bootstrap_org()
        add_active_strategy(bundle, name="S1", effective_from="2026-01-01",
                            effective_to="2027-01-01")
        return bundle

    def test_overlapping_window_activation_rejected(self, api):
        """PRD §3.1: "no other `ACTIVE` strategy for the same organization may
        have a window overlapping this policy's `[effective_from,
        effective_to)` interval, where overlap of the half-open intervals is
        what matters; a violation fails as `ERR_STRATEGY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/strategy_window_overlap_interval_vs_interval
        """
        bundle = self._bundle_with_active_strategy()
        s2 = create_draft_strategy(bundle, name="S2", target_percentile=65,
                                   effective_from="2026-06-01",
                                   effective_to="2027-06-01")
        resp = api.activate_strategy(s2["id"], mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_STRATEGY_WINDOW_OVERLAP)

    def test_adjacent_half_open_windows_do_not_overlap(self, api):
        """PRD §3.1: "no other `ACTIVE` strategy for the same organization may
        have a window overlapping this policy's `[effective_from,
        effective_to)` interval, where overlap of the half-open intervals is
        what matters; a violation fails as `ERR_STRATEGY_WINDOW_OVERLAP`."

        Adjacent windows [2026-01-01, 2027-01-01) and [2027-01-01, 2028-01-01)
        share no calendar day under half-open semantics, so activation succeeds.

        Design: Difficulty/resource_temporal_overlap/strategy_window_overlap_interval_vs_interval
        """
        bundle = self._bundle_with_active_strategy()
        s3 = create_draft_strategy(bundle, name="S3", target_percentile=75,
                                   effective_from="2027-01-01",
                                   effective_to="2028-01-01")
        activated = validate_success(api.activate_strategy(s3["id"],
                                                           mgr_headers(bundle)))
        assert activated["status"] == "ACTIVE", (
            f"Adjacent half-open windows must not overlap; got "
            f"{activated['status']}")
