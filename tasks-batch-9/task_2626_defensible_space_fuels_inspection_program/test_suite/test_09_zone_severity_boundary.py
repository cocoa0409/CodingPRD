"""The per-zone severity ladder and its three separate rounding depths."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_ZONE_ALREADY_EVALUATED,
    add_zone,
    assert_zone_grade,
    create_inspector,
    create_parcel,
    open_cycle,
    schedule_inspection,
    serve_notice,
    zone_payload,
)
from test_helpers.test_users import make_inspector_headers

WINDOWS = (
    ("2026-08-20T15:00:00Z", "2026-08-20T17:00:00Z"),
    ("2026-08-21T15:00:00Z", "2026-08-21T17:00:00Z"),
    ("2026-08-22T15:00:00Z", "2026-08-22T17:00:00Z"),
)


def _three_noticed_visits(client):
    """Three noticed inspections on one slope-30 parcel, one per calendar day.

    Because a zone may carry only one evaluation per inspection, each boundary
    measurement needs its own visit.  The parcel's slope_pct of 30 puts it on
    moderate ground, so the slope factor is 1.25 and zone one requires 37.5 feet.
    """
    cycle = open_cycle(client, notice_lead_days=10)
    inspector = create_inspector(client)
    parcel = create_parcel(client, slope_pct=30)
    visits = []
    for start, end in WINDOWS:
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc=start,
            scheduled_end_utc=end,
        )
        visits.append(serve_notice(client, inspection["id"]))
    return {"inspector": inspector, "parcel": parcel, "visits": visits}


class TestZoneSeverityBoundary:
    """A deficit ratio of exactly 0.6000 is the last MAJOR ratio, not the first
    CRITICAL one."""

    def test_ratio_of_exactly_0_6000_bands_major_and_its_neighbours_split(
        self, client
    ):
        """15.0 feet against a 37.5-foot requirement is MAJOR; 14.9 tips CRITICAL
        and 15.1 stays MAJOR with a smaller ratio.

        PRD: "deficit_ratio expresses that shortfall as a fraction of the
        requirement - the deficit divided by the required clearance, rounded half
        up to four decimal places."

        PRD: "deficiency_severity then bands the ratio, with the upper edge of
        each band inclusive: a ratio of exactly 0.0000 is NONE, a ratio at or
        below 0.2500 is MINOR, a ratio at or below 0.6000 is MAJOR, and anything
        larger is CRITICAL. A ratio of exactly 0.2500 is MINOR, and a ratio of
        exactly 0.6000 is MAJOR."

        PRD: "The ratio is first scaled to a percentage by multiplying by 100 and
        weighted by the zone's importance - the ember zone carries a weight of
        1.50 because embers landing against the wall are what actually ignite
        houses, zone one carries 1.00, and zone two carries 0.60 - and that
        product is rounded half up to two decimals and capped at 100.00."

        PRD: "ERR_ZONE_ALREADY_EVALUATED when a zone already carries an evaluation
        on the same inspection"

        Design: Difficulty/boundary_precision_check/zone_severity_major_at_exact_0_6000_deficit_ratio
        """
        world = _three_noticed_visits(client)
        inspector_id = world["inspector"]["id"]
        first, second, third = world["visits"]

        on_the_edge = add_zone(client, first["id"], inspector_id, "ZONE_1", 15.0)
        assert_zone_grade(
            on_the_edge,
            required_ft=37.5,
            deficit_ft=22.5,
            ratio=0.6000,
            severity="MAJOR",
            points=60.00,
        )
        assert on_the_edge["deficiency_severity"] != "CRITICAL"

        # 22.6 / 37.5 is 0.602666..., which rounds up and crosses the band.
        just_over = add_zone(client, second["id"], inspector_id, "ZONE_1", 14.9)
        assert_zone_grade(
            just_over,
            required_ft=37.5,
            deficit_ft=22.6,
            ratio=0.6027,
            severity="CRITICAL",
            points=60.27,
        )

        just_under = add_zone(client, third["id"], inspector_id, "ZONE_1", 15.1)
        assert_zone_grade(
            just_under,
            required_ft=37.5,
            deficit_ft=22.4,
            ratio=0.5973,
            severity="MAJOR",
            points=59.73,
        )

        # Each boundary case needed its own visit for exactly this reason.
        validate_error(
            client.create_zone_evaluation(
                first["id"],
                zone_payload("ZONE_1", 20.0),
                headers=make_inspector_headers(inspector_id),
            ),
            ERR_ZONE_ALREADY_EVALUATED,
        )

    def test_ember_zone_rounds_the_requirement_and_the_points_half_up(self, client):
        """5 times 1.25 is 6.25, which must become 6.3, and 30.945 points must
        become 30.95.

        PRD: "That factor multiplies the zone's base requirement - 5 feet for the
        ember zone, 30 feet for zone one, and 100 feet for zone two - and the
        product, rounded half up to one decimal place, becomes
        required_clearance_ft."

        PRD: "deficit_ft is how far short the owner fell: the required clearance
        minus the measured clearance, floored at 0 so that clearing more than
        required never produces a negative deficit, carried to one decimal place."

        PRD: "a ratio at or below 0.2500 is MINOR"

        Design: Difficulty/boundary_precision_check/zone_severity_major_at_exact_0_6000_deficit_ratio
        """
        world = _three_noticed_visits(client)
        first = world["visits"][0]

        ember = add_zone(
            client, first["id"], world["inspector"]["id"], "ZONE_0_EMBER", 5.0
        )
        assert_zone_grade(
            ember,
            required_ft=6.3,
            deficit_ft=1.3,
            ratio=0.2063,
            severity="MINOR",
            points=30.95,
        )
        assert ember["required_clearance_ft"] != 6.2
        assert ember["points"] != 30.94
