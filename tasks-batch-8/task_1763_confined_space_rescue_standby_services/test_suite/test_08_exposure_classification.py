"""Entrant exposure classification: the TWA8 and PEAK_CEILING variants
(PRD §3.7)."""
from datetime import datetime

from test_helpers import (
    post_reading,
    read_permit,
    read_roster_entry,
    roster_checkin,
    schedule_roster,
    set_clock,
    setup_active_permit,
)

DAY = "2026-08-03"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _schedule_crew(ctx, start=f"{DAY}T10:00:00Z", end=f"{DAY}T18:30:00Z"):
    """Schedule the attendant + entrant pair (both 10:00-18:30 by default)."""
    team = ctx["team"]
    att_entry = schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                                team["attendant"]["id"],
                                assignment_role="ATTENDANT",
                                scheduled_start_at=start,
                                scheduled_end_at=end)
    ent_entry = schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                                team["entrant"]["id"],
                                assignment_role="ENTRANT",
                                scheduled_start_at=start,
                                scheduled_end_at=end)
    return att_entry, ent_entry


def _drive_reading_stream(ctx):
    """Walk the shared stream: 8 ppm for 240 minutes, then 2 ppm.

    Attendant and entrant go ON_DUTY at 10:00; CONTINUOUS readings post at
    10:00 (8 ppm), 14:00 (2 ppm), and 18:00 (2 ppm); the duty window observed
    at 18:00 is exactly [10:00, 18:00) = 480 minutes.
    """
    team = ctx["team"]
    permit_id = ctx["permit"]["id"]
    att_entry, ent_entry = _schedule_crew(ctx)
    set_clock(f"{DAY}T10:00:00Z")
    roster_checkin(att_entry["id"], team["supervisor_headers"])
    roster_checkin(ent_entry["id"], team["supervisor_headers"])
    post_reading(permit_id, team["attendant_headers"],
                 reading_kind="CONTINUOUS", h2s_ppm=8)
    set_clock(f"{DAY}T14:00:00Z")
    post_reading(permit_id, team["attendant_headers"],
                 reading_kind="CONTINUOUS", h2s_ppm=2)
    set_clock(f"{DAY}T18:00:00Z")
    post_reading(permit_id, team["attendant_headers"],
                 reading_kind="CONTINUOUS", h2s_ppm=2)
    return ent_entry


class TestExposureStandardDivergence:
    def test_twa8_space_classifies_action(self, api):
        """PRD §3.7: "Under the `TWA8` variant — which accumulates dose over
        time — an entry is `EXCEEDANCE` when its rounded time-weighted average
        is at least 10 ppm, `ACTION` when at least 5 ppm, and otherwise `OK`."
        and "The same reading stream can classify differently under the two
        variants: readings of 8 ppm for 240 minutes followed by 2 ppm for 240
        minutes yield a time-weighted average of exactly 5.0 ppm (`ACTION`
        under `TWA8`) while the peak is 8 (`OK` under `PEAK_CEILING`)."

        Design: Difficulty/dual_variant_calc/exposure_standard_twa8_vs_peak_divergence
        """
        ctx = setup_active_permit(at=f"{DAY}T05:30:00Z",
                                  space_overrides={"exposure_standard": "TWA8"})
        ent_entry = _drive_reading_stream(ctx)
        entrant = read_roster_entry(ent_entry["id"])
        assert entrant["exposure_twa_ppm"] == 5.0, (
            "(8*240 + 2*240) / 480 = 5.0")
        assert entrant["exposure_peak_ppm"] == 8
        assert entrant["exposure_class"] == "ACTION", (
            "TWA8 standard: 5.0 >= 5 classifies ACTION")
        assert entrant["status"] == "ON_DUTY", (
            "ACTION does not auto-relieve; only EXCEEDANCE does")

    def test_peak_ceiling_space_classifies_ok(self, api):
        """PRD §3.7: "Under the `PEAK_CEILING` variant — which reacts only to
        the maximum instantaneous reading — an entry is `EXCEEDANCE` when its
        peak is at least 15 ppm, `ACTION` when at least 10 ppm, and otherwise
        `OK`. All thresholds are inclusive." and "The same reading stream can
        classify differently under the two variants: readings of 8 ppm for 240
        minutes followed by 2 ppm for 240 minutes yield a time-weighted average
        of exactly 5.0 ppm (`ACTION` under `TWA8`) while the peak is 8 (`OK`
        under `PEAK_CEILING`)."

        Design: Difficulty/dual_variant_calc/exposure_standard_twa8_vs_peak_divergence
        """
        ctx = setup_active_permit(
            at=f"{DAY}T05:30:00Z",
            space_overrides={"exposure_standard": "PEAK_CEILING"})
        ent_entry = _drive_reading_stream(ctx)
        entrant = read_roster_entry(ent_entry["id"])
        assert entrant["exposure_twa_ppm"] == 5.0, (
            "the dose is computed regardless of the space's standard")
        assert entrant["exposure_peak_ppm"] == 8
        assert entrant["exposure_class"] == "OK", (
            "PEAK_CEILING standard: peak 8 < 10 classifies OK — the identical "
            "reading stream diverges from the TWA8 space's ACTION")


class TestExposureAutoRelief:
    def test_exposure_exceedance_auto_relief(self, api):
        """PRD §3.7: "Under the `TWA8` variant — which accumulates dose over
        time — an entry is `EXCEEDANCE` when its rounded time-weighted average
        is at least 10 ppm, `ACTION` when at least 5 ppm, and otherwise `OK`."
        and "Whenever an entry's class becomes `EXCEEDANCE`, the entry is
        auto-relieved: `ON_DUTY` to `RELIEVED` with `checked_out_at` set to the
        trigger timestamp, and exposure fields finalized for the duty window."
        PRD §3.6: "computes `within_limits`: true exactly when `o2_pct` is at
        least 19.5 and at most 23.5, `lel_pct` is at most 10, `h2s_ppm` is at
        most 10, and `co_ppm` is at most 35 — all bounds inclusive."

        Design: Corner/calculations/corner_exposure_exceedance_auto_relief
        """
        ctx = setup_active_permit(at=f"{DAY}T09:30:00Z",
                                  planned_start_at=f"{DAY}T09:00:00Z",
                                  planned_end_at=f"{DAY}T20:00:00Z",
                                  standby_start_at=f"{DAY}T09:00:00Z",
                                  standby_end_at=f"{DAY}T20:00:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]
        att_entry, ent_entry = _schedule_crew(ctx)

        set_clock(f"{DAY}T10:00:00Z")
        roster_checkin(att_entry["id"], team["supervisor_headers"])
        roster_checkin(ent_entry["id"], team["supervisor_headers"])
        # 10 ppm is inside the inclusive alarm band (<= 10) yet accumulates to
        # the TWA8 exceedance threshold over the full normalized window.
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="CONTINUOUS", h2s_ppm=10)

        set_clock(f"{DAY}T18:00:00Z")
        # The 18:00 clock advance recomputes exposure over the 480-minute
        # duty window [10:00, 18:00): 10 ppm * 480 / 480 = 10.0.
        entrant = read_roster_entry(ent_entry["id"])
        assert entrant["exposure_twa_ppm"] == 10.0
        assert entrant["exposure_class"] == "EXCEEDANCE", (
            "10.0 >= 10: the inclusive threshold classifies EXCEEDANCE")
        assert entrant["status"] == "RELIEVED", (
            "EXCEEDANCE auto-relieves without any alarm")
        assert _ts(entrant["checked_out_at"]) == _ts(f"{DAY}T18:00:00Z")
        assert read_permit(permit_id)["status"] == "ACTIVE", (
            "h2s 10 <= 10 is within alarm limits: exposure relief does NOT "
            "suspend the permit")
