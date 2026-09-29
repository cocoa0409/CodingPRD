"""Two validation pairs whose ordering is only visible when both defects are live."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_ABATEMENT_CAP_EXCEEDED,
    ERR_INSPECTOR_NOT_CERTIFIED,
    ERR_INSPECTOR_WINDOW_CONFLICT,
    ERR_NOTICE_NOT_OVERDUE,
    advance_cycle,
    authorize_payload,
    create_inspector,
    create_moderate_parcel,
    create_parcel,
    failed_world,
    get_notice,
    inspection_payload,
    list_inspections,
    list_orders,
    open_cycle,
    schedule_inspection,
    set_clock,
    very_high_parcel_payload,
)
from test_helpers.test_users import FIRE_MARSHAL_HEADERS, PROGRAM_ADMIN_HEADERS


class TestNoticeStateOutranksAbatementCap:
    """Gate 10 at 409 beats gate 25 at 422, despite the smaller status code."""

    def test_state_gate_answers_first_then_the_cap_becomes_reachable(self, client):
        """A notice still inside its compliance window reports ERR_NOTICE_NOT_OVERDUE
        even though the estimate also breaks the 750,000-cent ceiling.

        PRD: "A FireMarshal exercises it against a notice standing in OVERDUE, and
        an attempt against a notice in any other state - including one still
        inside its compliance window - is refused with ERR_NOTICE_NOT_OVERDUE."

        PRD: "The marshal supplies estimated_cost_cents, the district's own
        estimate of the job, which may not be negative and may not exceed the
        per-order abatement ceiling of 750,000 cents, that is 7,500 dollars; a
        larger estimate answers ERR_ABATEMENT_CAP_EXCEEDED."

        PRD: "State gate - the target resource is in a state from which the
        requested transition is declared, including any attempt to leave a
        terminal state."

        Design: Difficulty/priority_pair_validation_conflict/notice_not_overdue_outranks_abatement_cap_exceeded_rejected
        """
        world = failed_world(client, fail_at="2026-08-22T00:00:00Z")
        notice_id = world["notice"]["id"]
        assert world["notice"]["status"] == "ISSUED"

        validate_error(
            client.authorize_abatement(
                notice_id, authorize_payload(900000), headers=FIRE_MARSHAL_HEADERS
            ),
            ERR_NOTICE_NOT_OVERDUE,
        )
        assert get_notice(client, notice_id)["status"] == "ISSUED"
        rows, _meta = list_orders(client, violation_notice_id=notice_id)
        assert rows == [], "a refused authorization must create no order"

        # Repair only the state; the identical payload now reaches gate 25.
        set_clock(client, "2026-10-01T00:00:00Z")
        advance_cycle(client, world["cycle"]["id"])
        assert get_notice(client, notice_id)["status"] == "OVERDUE"
        validate_error(
            client.authorize_abatement(
                notice_id, authorize_payload(900000), headers=FIRE_MARSHAL_HEADERS
            ),
            ERR_ABATEMENT_CAP_EXCEEDED,
        )
        rows, _meta = list_orders(client, violation_notice_id=notice_id)
        assert rows == []

    def test_the_ceiling_itself_is_inclusive_on_an_overdue_notice(self, client):
        """Exactly 750,000 cents is inside the ceiling, so the same repaired
        request succeeds and produces an AUTHORIZED order.

        PRD: "which may not be negative and may not exceed the per-order abatement
        ceiling of 750,000 cents, that is 7,500 dollars; a larger estimate answers
        ERR_ABATEMENT_CAP_EXCEEDED."

        PRD: "Abatement estimate cap - estimated_cost_cents may not exceed the
        district's per-order abatement ceiling."

        Design: Difficulty/priority_pair_validation_conflict/notice_not_overdue_outranks_abatement_cap_exceeded_rejected
        """
        world = failed_world(client, fail_at="2026-08-22T00:00:00Z")
        notice_id = world["notice"]["id"]

        set_clock(client, "2026-10-01T00:00:00Z")
        advance_cycle(client, world["cycle"]["id"])
        order = validate_success(
            client.authorize_abatement(
                notice_id, authorize_payload(750000), headers=FIRE_MARSHAL_HEADERS
            ),
            201,
        )
        assert order["status"] == "AUTHORIZED"
        assert order["estimated_cost_cents"] == 750000
        assert order["violation_notice_id"] == notice_id
        assert get_notice(client, notice_id)["status"] == "ABATEMENT_AUTHORIZED"


def _certification_world(client):
    """Two active inspectors, one already-booked MODERATE parcel and a VERY_HIGH one.

    insp1 holds only ADVANCED certification while insp2 holds WUI_SPECIALIST, and
    each already occupies 2026-08-20T15:00Z-17:00Z on the moderate parcel, so the
    same requested window collides for either of them.
    """
    cycle = open_cycle(client)
    advanced = create_inspector(client, certification_level="ADVANCED")
    specialist = create_inspector(client, certification_level="WUI_SPECIALIST")
    moderate = create_moderate_parcel(client)
    very_high = create_parcel(client, very_high_parcel_payload())

    for inspector in (advanced, specialist):
        schedule_inspection(
            client,
            moderate["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
    return {
        "cycle": cycle,
        "advanced": advanced,
        "specialist": specialist,
        "very_high": very_high,
    }


class TestInspectorCertificationOutranksWindowConflict:
    """Gate 13 at 422 beats gate 20 at 409: the winner carries the larger status."""

    def test_certification_answers_before_the_occupation_conflict(self, client):
        """A VERY_HIGH parcel handed to an ADVANCED inspector reports
        ERR_INSPECTOR_NOT_CERTIFIED even though the window also overlaps.

        PRD: "a parcel sitting in a VERY_HIGH hazard zone may only be assigned to
        an inspector holding WUI_SPECIALIST certification; a BASIC or ADVANCED
        inspector on such a parcel is refused with ERR_INSPECTOR_NOT_CERTIFIED."

        PRD: "the requested window is treated as half-open, occupying every
        instant from scheduled_start_utc inclusive up to scheduled_end_utc
        exclusive, and it must not intersect the half-open window of any other
        inspection assigned to the same inspector that still stands in SCHEDULED,
        NOTICED or ACCESS_DENIED."

        PRD: "Inspector certification - a parcel whose hazard_zone is VERY_HIGH
        may only be inspected by an inspector whose certification_level is
        WUI_SPECIALIST."

        Design: Difficulty/priority_pair_validation_conflict/inspector_not_certified_outranks_window_conflict_rejected
        """
        world = _certification_world(client)
        parcel_id = world["very_high"]["id"]

        validate_error(
            client.create_inspection(
                inspection_payload(
                    parcel_id,
                    world["cycle"]["id"],
                    world["advanced"]["id"],
                    "2026-08-20T16:00:00Z",
                    "2026-08-20T18:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INSPECTOR_NOT_CERTIFIED,
        )

        # Removing only the temporal collision leaves the same 422 standing.
        validate_error(
            client.create_inspection(
                inspection_payload(
                    parcel_id,
                    world["cycle"]["id"],
                    world["advanced"]["id"],
                    "2026-08-20T18:00:00Z",
                    "2026-08-20T20:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INSPECTOR_NOT_CERTIFIED,
        )

        rows, _meta = list_inspections(client, parcel_id=parcel_id)
        assert rows == [], "neither refusal may leave an inspection behind"

    def test_the_occupation_conflict_is_reachable_for_a_certified_inspector(
        self, client
    ):
        """With certification satisfied the same colliding window reports the 409,
        while exact adjacency to the existing visit is accepted.

        PRD: "Any real overlap is refused with ERR_INSPECTOR_WINDOW_CONFLICT."

        PRD: "Because the window is half-open, exact adjacency is fine - a new
        visit starting at the precise instant an existing one ends, or ending at
        the precise instant an existing one begins, does not conflict."

        PRD: "Inspector occupation conflict - the new half-open inspection window
        must not intersect another live window of the same inspector."

        Design: Difficulty/priority_pair_validation_conflict/inspector_not_certified_outranks_window_conflict_rejected
        """
        world = _certification_world(client)
        parcel_id = world["very_high"]["id"]

        validate_error(
            client.create_inspection(
                inspection_payload(
                    parcel_id,
                    world["cycle"]["id"],
                    world["specialist"]["id"],
                    "2026-08-20T16:00:00Z",
                    "2026-08-20T18:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INSPECTOR_WINDOW_CONFLICT,
        )

        booked = schedule_inspection(
            client,
            parcel_id,
            world["cycle"]["id"],
            world["specialist"]["id"],
            scheduled_start_utc="2026-08-20T17:00:00Z",
            scheduled_end_utc="2026-08-20T19:00:00Z",
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["inspector_id"] == world["specialist"]["id"]
