"""Crew assignments, minimum staffing, and start-of-photography gating (PRD §3.4)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_start_on_registered_reports_state_error_not_staffing(api):
    """PRD §2.10: "State gates come after those, in this sequence:
    production-state gating (`ERR_PRODUCTION_STATE`)" and "Business rules run
    last, in this fixed sequence: minimum staffing (`ERR_MIN_STAFF_UNMET`)".
    PRD §3.4: "The production must be `STAFFING` (`ERR_PRODUCTION_STATE`
    otherwise)". A start call on a REGISTERED production (bond never posted)
    with zero crew violates both gates; the production-state gate reports first.

    Design: Difficulty/priority_pair_validation_conflict/start_production_state_error_beats_staffing_safety
    """
    company, _ = th.create_signatory_company("Larch Films LLC", "88-7777777")
    production = th.create_production(company, "Larch Hollow")  # bond PENDING

    resp = api.start_production(production["id"], th.owner_headers(company))
    th.validate_error(resp, E.ERR_PRODUCTION_STATE)

    current = th.get_production(production["id"], company)
    assert current["status"] == "REGISTERED", "rejected start must not change state"


def test_start_with_state_fixed_reports_staffing_error(api):
    """PRD §2.10: "Business rules run last, in this fixed sequence: minimum
    staffing (`ERR_MIN_STAFF_UNMET`)". Once the production-state gate passes
    (bond posted, production STAFFING), the same zero-crew start reaches the
    staffing rule and fails there — confirming the earlier rejection was the
    state gate's, per the pinned ordering.
    PRD §3.4: "any department one short fails the whole check with
    `ERR_MIN_STAFF_UNMET` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/start_production_state_error_beats_staffing_safety
    """
    bundle = th.create_staffing_production("Larch Films LLC", "88-7777777",
                                           title="Larch Hollow")
    company, production = bundle["company"], bundle["production"]

    resp = api.start_production(production["id"], th.owner_headers(company))
    th.validate_error(resp, E.ERR_MIN_STAFF_UNMET)

    current = th.get_production(production["id"], company)
    assert current["status"] == "STAFFING"


def test_min_staffing_inclusive_boundary(api):
    """PRD §3.4: "Counting only assignments in `HIRED` or `ACTIVE` within each
    department ... an `ULTRA_LOW_BUDGET` production needs at least one crew
    member in each of `CAMERA`, `GRIP_ELECTRIC`, and `SOUND`" and "The boundary
    is inclusive — a count exactly equal to a department minimum passes — and
    any department one short fails the whole check with `ERR_MIN_STAFF_UNMET`
    (HTTP 422)."

    Design: Corner/calculations/min_staffing_minimum_boundary_inclusive
    """
    bundle = th.create_staffing_production("Dittany LLC", "20-0000029",
                                           title="Dittany Hill", scope="NEW_MEDIA")
    company, production, owner = bundle["company"], bundle["production"], bundle["owner"]
    th.hire_crew(production, company, "W-CAM-1", "CAMERA", "CAMERA_OPERATOR", 100_000)
    th.hire_crew(production, company, "W-SND-1", "SOUND", "BOOM_OPERATOR", 80_000)

    resp = api.start_production(production["id"], owner)
    th.validate_error(resp, E.ERR_MIN_STAFF_UNMET)  # GRIP_ELECTRIC is one short

    th.hire_crew(production, company, "W-GRIP-1", "GRIP_ELECTRIC", "GAFFER", 90_000)
    started = th.get_success_data(api.start_production(production["id"], owner))
    assert started["status"] == "IN_PRODUCTION", (
        "exactly-minimum staffing passes the inclusive boundary"
    )


def test_activate_requires_in_production(api):
    """PRD §3.4: "Activation — `HIRED` to `ACTIVE` — requires the production to
    be `IN_PRODUCTION` (`ERR_PRODUCTION_STATE` otherwise) and its posture not
    `FROZEN`."

    Design: Corner/state_machines/crew_activate_before_in_production_rejected
    """
    bundle = th.create_staffing_production("Quaking Aspen LLC", "20-0000017",
                                           title="Quake Line", scope="NEW_MEDIA")
    company, production = bundle["company"], bundle["production"]
    assignment = th.hire_crew(production, company, "W-CAM-1", "CAMERA",
                              "CAMERA_OPERATOR", 100_000)

    resp = api.transition_crew_assignment(
        assignment["id"], {"to_state": "ACTIVE"}, th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_PRODUCTION_STATE)

    current = th.validate_success(
        api.get_crew_assignment(assignment["id"], th.owner_headers(company))
    )
    assert current["status"] == "HIRED", "rejected activation must not change state"


def test_wrapped_assignment_terminal(api):
    """PRD §3.4: "Any transition attempted from the terminal states `WRAPPED`
    or `TERMINATED` is rejected with `ERR_ASSIGNMENT_STATE` (HTTP 409)."

    Design: Corner/state_machines/wrapped_assignment_further_transition_rejected
    """
    bundle = th.create_in_production("Rushmore LLC", "20-0000018",
                                     title="Rush More")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]
    cam = th.transition_assignment(cam, company, "WRAPPED")
    assert cam["status"] == "WRAPPED"

    resp = api.transition_crew_assignment(
        cam["id"], {"to_state": "TERMINATED"}, th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_ASSIGNMENT_STATE)

    current = th.validate_success(
        api.get_crew_assignment(cam["id"], th.owner_headers(company))
    )
    assert current["status"] == "WRAPPED", "terminal state must not change"


def test_duplicate_active_assignment_then_rehire(api):
    """PRD §3.4: "At most one assignment per production and `crew_member_ref`
    may be live — that is, in `HIRED` or `ACTIVE` status — and a duplicate is
    rejected with `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` (HTTP 409)."
    After the first assignment is TERMINATED the ref is no longer live, so
    re-hiring the same `crew_member_ref` succeeds.

    Design: Corner/validations/duplicate_active_assignment_rejected_then_rehire_allowed
    """
    bundle = th.create_staffing_production("Jacob's Ladder LLC", "20-0000037",
                                           title="Jacob Run")
    company, production = bundle["company"], bundle["production"]
    first = th.hire_crew(production, company, "W-CAM-1", "CAMERA",
                         "CAMERA_OPERATOR", 100_000)

    resp = api.create_crew_assignment(
        th.create_crew_assignment_payload(
            production_id=production["id"], crew_member_ref="W-CAM-1",
            department="CAMERA", classification="DIRECTOR_OF_PHOTOGRAPHY",
            daily_rate_cents=110_000,
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_DUPLICATE_ACTIVE_ASSIGNMENT)

    th.transition_assignment(first, company, "TERMINATED")
    rehired = th.hire_crew(production, company, "W-CAM-1", "CAMERA",
                           "DIRECTOR_OF_PHOTOGRAPHY", 110_000)
    th.assert_crew_assignment(rehired)
    assert rehired["status"] == "HIRED"
    assert rehired["id"] != first["id"]
