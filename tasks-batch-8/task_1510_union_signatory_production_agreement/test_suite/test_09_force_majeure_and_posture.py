"""Force majeure suspension/restoration and compliance-posture gating (PRD §2.8, §3.8)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_adjacent_force_majeure_events_allowed(api):
    """PRD §3.8: "Adjacency is allowed: a new event whose start date equals
    another event's effective end does not overlap it."
    [2026-08-05, 2026-08-08) followed by [2026-08-08, 2026-08-10) touch but do
    not overlap. PRD §3.8: "If no other event of the production remains
    `ACTIVE`, the production returns from `SUSPENDED` to the status preserved
    in `pre_suspension_status` (`STAFFING` or `IN_PRODUCTION`)".

    Design: Difficulty/resource_temporal_overlap/force_majeure_half_open_interval_overlap
    """
    bundle = th.create_in_production("Sumac Trail LLC", "16-0000005",
                                     title="Sumac Ridge")
    production = bundle["production"]
    company = bundle["company"]

    fm1 = th.declare_force_majeure(production, "STRIKE", "2026-08-05", "2026-08-08")
    th.set_clock("2026-08-08T00:00:00Z")
    th.lift_force_majeure(fm1)

    fm2 = th.declare_force_majeure(production, "NATURAL_DISASTER",
                                   "2026-08-08", "2026-08-10")
    th.assert_force_majeure_event(fm2)
    assert fm2["status"] == "ACTIVE", "adjacent start == prior effective end is allowed"

    th.set_clock("2026-08-10T00:00:00Z")
    th.lift_force_majeure(fm2)
    restored = th.get_production(production["id"], company)
    assert restored["status"] == "IN_PRODUCTION", "restored after each lift"


def test_overlapping_event_rejected_even_after_lift(api):
    """PRD §3.8: "The new event's interval — running from its `start_date` up
    to but not including its `end_date`, or indefinitely when `end_date` is
    null — must not intersect any existing event of the same production,
    `ACTIVE` or `LIFTED`, where each existing event's effective end is its
    `end_date` if set, else its `lifted_date`." and "A genuine intersection is
    rejected with `ERR_FM_OVERLAP` (HTTP 409)."
    [2026-08-09, 2026-08-12) intersects the already-LIFTED [2026-08-08,
    2026-08-10) by one day.

    Design: Difficulty/resource_temporal_overlap/force_majeure_half_open_interval_overlap
    """
    bundle = th.create_in_production("Sumac Trail LLC", "16-0000005",
                                     title="Sumac Ridge")
    production = bundle["production"]
    company = bundle["company"]

    fm1 = th.declare_force_majeure(production, "STRIKE", "2026-08-05", "2026-08-08")
    th.set_clock("2026-08-08T00:00:00Z")
    th.lift_force_majeure(fm1)
    fm2 = th.declare_force_majeure(production, "NATURAL_DISASTER",
                                   "2026-08-08", "2026-08-10")
    th.set_clock("2026-08-10T00:00:00Z")
    th.lift_force_majeure(fm2)

    resp = api.create_force_majeure_event(
        th.create_force_majeure_event_payload(
            production_id=production["id"], event_type="OTHER",
            start_date="2026-08-09", end_date="2026-08-12",
        ),
        th.make_union_rep_headers("ur_1"),
    )
    th.validate_error(resp, E.ERR_FM_OVERLAP)


def test_declare_suspends_and_lift_restores(api):
    """PRD §3.8: "On success the production moves to `SUSPENDED`, its
    immediately prior status is recorded in `pre_suspension_status`, and its
    posture recomputes to `FROZEN` for as long as any event remains `ACTIVE`."
    PRD §3.8: "An `ACTIVE` event moves to `LIFTED` ... with `lifted_date`
    stamped from the logical clock. If no other event of the production remains
    `ACTIVE`, the production returns from `SUSPENDED` to the status preserved
    in `pre_suspension_status` (`STAFFING` or `IN_PRODUCTION`), and
    `pre_suspension_status` is cleared back to null."

    Design: Corner/state_machines/force_majeure_suspend_freeze_then_lift_restore
    """
    bundle = th.create_in_production("Pearly LLC", "20-0000016",
                                     title="Pearly Gates")
    production, company = bundle["production"], bundle["company"]
    th.set_clock("2026-08-08T00:00:00Z")

    fm = th.declare_force_majeure(production, "STRIKE", "2026-08-08", "2026-08-09")
    frozen = th.get_production(production["id"], company)
    assert frozen["status"] == "SUSPENDED"
    assert frozen["compliance_posture"] == "FROZEN"

    lifted = th.lift_force_majeure(fm)
    assert lifted["status"] == "LIFTED"
    assert lifted["lifted_date"] is not None
    assert str(lifted["lifted_date"]).startswith("2026-08-08"), (
        "lifted_date is stamped from the logical clock (set to 2026-08-08)"
    )

    restored = th.get_production(production["id"], company)
    assert restored["status"] == "IN_PRODUCTION"
    assert restored["compliance_posture"] == "CLEAR"
    assert restored.get("pre_suspension_status") is None


def test_declare_on_registered_rejected(api, union_rep_headers):
    """PRD §3.8: "Declaration requires the production to be `STAFFING` or
    `IN_PRODUCTION` (`ERR_PRODUCTION_STATE` otherwise)."

    Design: Corner/state_machines/fm_declare_before_bond_rejected
    """
    company, _ = th.create_signatory_company("Sorghum LLC", "20-0000019")
    production = th.create_production(company, "Sorghum Row")  # bond PENDING

    resp = api.create_force_majeure_event(
        th.create_force_majeure_event_payload(
            production_id=production["id"], event_type="STRIKE",
            start_date="2026-08-05", end_date="2026-08-06",
        ),
        union_rep_headers,
    )
    th.validate_error(resp, E.ERR_PRODUCTION_STATE)

    current = th.get_production(production["id"], company)
    assert current["status"] == "REGISTERED", "rejected declaration must not change state"


def test_double_lift_rejected(api):
    """PRD §3.8: "An `ACTIVE` event moves to `LIFTED` — lifting from any other
    state is `ERR_FM_STATE`" and "`LIFTED` is terminal."

    Design: Corner/state_machines/fm_double_lift_rejected
    """
    bundle = th.create_staffing_production("Woad LLC", "20-0000023",
                                           title="Woad Blue")
    fm = th.declare_force_majeure(bundle["production"], "NATURAL_DISASTER",
                                  "2026-08-05", "2026-08-06")
    th.lift_force_majeure(fm)

    resp = api.lift_force_majeure_event(fm["id"], th.make_union_rep_headers("ur_1"))
    th.validate_error(resp, E.ERR_FM_STATE)

    events, _ = th.validate_paginated(api.list_production_force_majeure_events(
        bundle["production"]["id"], th.owner_headers(bundle["company"]),
    ))
    current = next(e for e in events if e["id"] == fm["id"])
    assert current["status"] == "LIFTED", "rejected second lift must not change state"


def test_second_grievance_restricts_posture(api):
    """PRD §2.8: "the posture is `RESTRICTED` when at least one of three
    conditions holds: the count of the production's grievances in `FILED`,
    `INVESTIGATING`, `PROPOSED_SETTLEMENT`, or `ESCALATED` status reaches 2"
    and "The grievance-count threshold is inclusive: exactly 2 open grievances
    already restrict the production."

    Design: Corner/cross_cutting_layers/posture_grievance_count_threshold_inclusive
    """
    bundle = th.create_staffing_production("Yellowroot LLC", "20-0000052",
                                           title="Yellow Root", scope="NEW_MEDIA")
    production, company = bundle["production"], bundle["company"]

    th.file_grievance(production, category="OTHER", incident_date="2026-07-20",
                      description="G1")
    mid = th.get_production(production["id"], company)
    assert mid["compliance_posture"] == "CLEAR", "1 open grievance is below threshold"

    th.file_grievance(production, category="PAY", incident_date="2026-07-21",
                      description="G2")
    after = th.get_production(production["id"], company)
    assert after["compliance_posture"] == "RESTRICTED", "2 >= 2 restricts"


def test_restricted_blocks_hiring_not_logging(api):
    """PRD §2.8: "Hiring crew and starting production both require `CLEAR`: a
    `RESTRICTED` posture rejects them with `ERR_POSTURE_RESTRICTED` (HTTP 409)"
    and "Creating, submitting, or voiding work day logs, creating or submitting
    contribution reports, and transitioning crew assignments require only that
    the posture not be `FROZEN`, and are rejected with `ERR_POSTURE_FROZEN`
    while it is."

    Design: Corner/cross_cutting_layers/posture_restricted_blocks_hiring_not_logging
    """
    bundle = th.create_in_production("Bugbane LLC", "20-0000054",
                                     title="Bugbane Plot", activate=("W-CAM-1",))
    production, company = bundle["production"], bundle["company"]
    th.file_grievance(production, category="WORK_RULE", incident_date="2026-07-20",
                      description="G1 turnaround")
    th.file_grievance(production, category="PAY", incident_date="2026-07-21",
                      description="G2 penalties")
    assert th.get_production(production["id"], company)["compliance_posture"] == "RESTRICTED"

    resp = api.create_crew_assignment(
        th.create_crew_assignment_payload(
            production_id=production["id"], crew_member_ref="W-CAM-2",
            department="CAMERA", classification="CAMERA_OPERATOR",
            daily_rate_cents=100_000,
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_POSTURE_RESTRICTED)

    log = th.record_log(bundle["assignments"]["W-CAM-1"], company, "2026-08-10")
    assert log["status"] == "OPEN", "logging continues under RESTRICTED"


def test_closed_production_start_rejected(api):
    """PRD §3.8: "Success moves the production to `CLOSED`, which is terminal."
    PRD §3.4: "The production must be `STAFFING` (`ERR_PRODUCTION_STATE`
    otherwise)" — a CLOSED production is not STAFFING, so start-production is
    rejected and the terminal state is unchanged.

    Design: Corner/state_machines/closed_production_start_rejected_terminal_lockdown
    """
    bundle = th.setup_closed_production(legal_name="Milkweed LLC",
                                        fein="20-0000013", title="Milk Run")
    production, company = bundle["production"], bundle["company"]
    assert production["status"] == "CLOSED"

    resp = api.start_production(production["id"], th.owner_headers(company))
    th.validate_error(resp, E.ERR_PRODUCTION_STATE)

    current = th.get_production(production["id"], company)
    assert current["status"] == "CLOSED", "CLOSED is terminal"
