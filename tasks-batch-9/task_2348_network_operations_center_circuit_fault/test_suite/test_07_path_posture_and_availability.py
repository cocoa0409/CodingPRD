"""Historical path availability and the soft retirement of a hop.

Two legs that failed at different times tell two different stories depending on
the accounting variant asked for, and retiring one of those legs has to leave the
evidence readable while every derived count moves.
"""

from test_helpers import (
    ADMIN_HEADERS,
    SHIFT_LEAD_HEADERS,
    advance_clock,
    assert_availability_pct,
    assert_circuit_posture,
    assert_minutes,
    assert_page,
    assert_path_posture,
    availability_params,
    build_ewt_two_leg,
    clear_alarm,
    get_success_data,
    path_segment_payload,
    raise_alarm,
    read_circuit,
    read_path,
    read_segment,
    validate_paginated,
    validate_success,
)

PERIOD_START = "2026-08-10T00:00:00Z"
PERIOD_END = "2026-08-10T06:00:00Z"


def _two_non_overlapping_leg_outages(api) -> dict:
    """Fail LEG_A for two hours, then LEG_B for one hour, with no overlap."""
    state = build_ewt_two_leg(api, PERIOD_START)

    alarm_a = raise_alarm(api, PERIOD_START, source_circuit_id=state["circuit_a_id"])
    advance_clock(api, "2026-08-10T02:00:00Z")
    clear_alarm(api, alarm_a["id"], "2026-08-10T02:00:00Z")

    advance_clock(api, "2026-08-10T03:00:00Z")
    alarm_b = raise_alarm(
        api, "2026-08-10T03:00:00Z", source_circuit_id=state["circuit_b_id"]
    )
    advance_clock(api, "2026-08-10T04:00:00Z")
    clear_alarm(api, alarm_b["id"], "2026-08-10T04:00:00Z")

    advance_clock(api, PERIOD_END)
    state["alarm_a_id"] = alarm_a["id"]
    state["alarm_b_id"] = alarm_b["id"]
    return state


def _availability(api, path_id: str, basis: str) -> dict:
    """Ask for the six-hour history of a path under one accounting variant."""
    return get_success_data(
        api.get_path_availability(
            path_id,
            SHIFT_LEAD_HEADERS,
            params=availability_params(PERIOD_START, PERIOD_END, basis),
        )
    )


class TestAvailabilityAccountingVariants:
    """The same downtime evidence yields two different path availabilities."""

    def test_intersection_finds_no_instant_when_both_legs_were_down(self, api):
        """Non-overlapping leg outages intersect to nothing, so the path was never down.

        PRD 3.2: "Under `INTERSECTION`, `path_down_minutes` is the total length of the intersection of every leg's merged union — the path is down only over instants when every leg was simultaneously down — and `availability_pct` is 100 minus the ratio of `path_down_minutes` to `period_minutes` expressed as a percentage, rounded half up to three decimal places."
        PRD 3.2: "All intervals belonging to hops in the same leg are merged into a disjoint union, and the total length of that union is the leg's entry in `leg_down_minutes`, which is reported per leg."

        Design: Difficulty/dual_variant_calc/path_availability_intersection_vs_best_leg_basis
        """
        state = _two_non_overlapping_leg_outages(api)
        report = _availability(api, state["path_id"], "INTERSECTION")

        assert_minutes(report["period_minutes"], 360.00, "period_minutes")
        assert_minutes(
            report["leg_down_minutes"]["LEG_A"], 120.00, "leg_down_minutes.LEG_A"
        )
        assert_minutes(
            report["leg_down_minutes"]["LEG_B"], 60.00, "leg_down_minutes.LEG_B"
        )
        assert_minutes(report["path_down_minutes"], 0.00, "path_down_minutes")
        assert_availability_pct(report["availability_pct"], 100.000, "availability_pct")

    def test_best_leg_attributes_the_healthiest_leg_total_to_the_path(self, api):
        """The one-hour leg outage becomes the whole path's downtime: 83.333 percent.

        PRD 3.2: "Under `BEST_LEG`, `path_down_minutes` is instead the smallest `leg_down_minutes` across the legs: each leg is scored independently and the healthiest leg's total is attributed to the path regardless of whether the outages overlapped in time, which for non-overlapping leg outages yields a strictly larger `path_down_minutes` than `INTERSECTION` on identical data."
        PRD 3.2: "`availability_pct` is computed the same way in both variants."

        Design: Difficulty/dual_variant_calc/path_availability_intersection_vs_best_leg_basis
        """
        state = _two_non_overlapping_leg_outages(api)
        report = _availability(api, state["path_id"], "BEST_LEG")

        assert_minutes(report["period_minutes"], 360.00, "period_minutes")
        assert_minutes(report["path_down_minutes"], 60.00, "path_down_minutes")
        assert_availability_pct(report["availability_pct"], 83.333, "availability_pct")
        assert report["path_down_minutes"] > 0, (
            "the healthiest leg still contributes downtime under this variant"
        )

    def test_both_variants_report_the_same_per_leg_evidence(self, api):
        """Only the last step differs: the legs, the period and the basis echo agree.

        PRD 3.2: "The two variants differ only in how leg downtime becomes path downtime, and they can differ sharply on the same data."
        PRD 3.2: "The report echoes the `basis` used and reports `period_minutes`, the length of the requested window in minutes; minute quantities are carried to two decimal places and the percentage to three."

        Design: Difficulty/dual_variant_calc/path_availability_intersection_vs_best_leg_basis
        """
        state = _two_non_overlapping_leg_outages(api)
        intersection = _availability(api, state["path_id"], "INTERSECTION")
        best_leg = _availability(api, state["path_id"], "BEST_LEG")

        assert intersection["basis"] == "INTERSECTION", (
            f"the report echoes the requested basis, got {intersection['basis']!r}"
        )
        assert best_leg["basis"] == "BEST_LEG", (
            f"the report echoes the requested basis, got {best_leg['basis']!r}"
        )
        for label in ("LEG_A", "LEG_B"):
            assert_minutes(
                best_leg["leg_down_minutes"][label],
                intersection["leg_down_minutes"][label],
                f"leg_down_minutes.{label} under BEST_LEG",
            )
        assert_minutes(
            best_leg["period_minutes"],
            intersection["period_minutes"],
            "period_minutes under BEST_LEG",
        )
        assert best_leg["path_down_minutes"] > intersection["path_down_minutes"], (
            "for non-overlapping leg outages BEST_LEG must report strictly more "
            "path downtime than INTERSECTION"
        )

        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="PROTECTED",
            active_leg_count=2,
            healthy_leg_count=2,
        )


class TestRetiringAHop:
    """Deleting a hop is a retirement, not an erasure."""

    def test_deleting_a_hop_keeps_the_row_and_drops_it_from_every_count(self, api):
        """The retired row still reads back, while the path falls to one active leg.

        PRD 3.2: "Retiring a hop does not delete the row — historical alarms must stay explicable — it flips `segment_state` to `RETIRED`, which removes the hop from every count and from every derivation from that moment on."
        PRD 3.2: "`monitored_segment_count` is the number of `ACTIVE` hops whose target has `monitoring_state` `MONITORED`, counted per hop rather than per leg."

        Design: Corner/endpoints/corner_delete_path_segment_retires_row_and_rederives_posture
        """
        state = build_ewt_two_leg(api, "2026-08-31T00:00:00Z")

        retired = validate_success(
            api.delete_path_segment(state["segment_b_id"], ADMIN_HEADERS)
        )["data"]
        assert retired["segment_state"] == "RETIRED", (
            f"deletion retires the hop, got {retired['segment_state']}"
        )

        still_readable = read_segment(api, state["segment_b_id"])
        assert still_readable["segment_state"] == "RETIRED", (
            "the retired hop must still resolve so historical alarms stay explicable"
        )
        assert still_readable["leg_group"] == "LEG_B", (
            "retirement does not rewrite what the hop described"
        )

        rows, meta = validate_paginated(
            api.list_path_segments(
                SHIFT_LEAD_HEADERS,
                params={
                    "application_path_id": state["path_id"],
                    "segment_state": "ACTIVE",
                },
            )
        )
        assert_page(meta, total_count=1)
        assert rows[0]["id"] == state["segment_a_id"], (
            "only the surviving hop is still active"
        )

        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="PROTECTED",
            active_leg_count=1,
            healthy_leg_count=1,
            monitored_segment_count=1,
        )

    def test_retirement_rederives_the_flags_and_frees_the_position(self, api):
        """Neither circuit becomes a risk, and the vacated leg position can be refilled.

        PRD 3.2: "Both adding and retiring a hop re-derive the parent path's leg counts and `posture` and re-derive `spof_flag` on every circuit reachable from the path's remaining `ACTIVE` hops; adding a hop advances the path's `version` by 1, and retiring one advances both the hop's `version` and the path's `version` by 1 each."
        PRD 3.2: "The triple of path, leg and sequence position must be unoccupied among `ACTIVE` hops, and a collision is `ERR_SEGMENT_POSITION_TAKEN`."

        Design: Corner/endpoints/corner_delete_path_segment_retires_row_and_rederives_posture
        """
        state = build_ewt_two_leg(api, "2026-08-31T00:00:00Z")
        path_before = read_path(api, state["path_id"])

        validate_success(api.delete_path_segment(state["segment_b_id"], ADMIN_HEADERS))

        for label in ("circuit_a_id", "circuit_b_id"):
            assert_circuit_posture(
                read_circuit(api, state[label]),
                operational_state="UP",
                spof_flag=False,
            )

        path_after = read_path(api, state["path_id"])
        assert path_after["version"] == path_before["version"] + 1, (
            f"retiring a hop advances the path version once, "
            f"got {path_after['version']} from {path_before['version']}"
        )
        assert read_segment(api, state["segment_b_id"])["version"] == 2, (
            "the retired hop's own version advances with the retirement"
        )

        refilled = validate_success(
            api.create_path_segment(
                path_segment_payload(
                    state["path_id"],
                    leg_group="LEG_B",
                    sequence_index=1,
                    circuit_id=state["circuit_b_id"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )["data"]
        assert refilled["segment_state"] == "ACTIVE", (
            "the vacated position accepts a new active hop"
        )
        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="PROTECTED",
            active_leg_count=2,
            healthy_leg_count=2,
            monitored_segment_count=2,
        )
