"""Gate session sequencing, the closing ladder, the prerequisite graph and condition deadlines."""
import pytest

from test_helpers import (
    cast_vote,
    decide_deliverable,
    deliverable_payload,
    make_gate_chair_headers,
    open_case_with_line,
    open_gate_review,
    read_project,
    register_stage_gate,
    run_gate_session,
    schedule_gate_review,
    set_clock,
    setup_screened_project,
    submit_deliverable,
    validate_error,
    validate_paginated,
    validate_success,
)

CONDITIONS = "Confirm the co-packer allergen sanitation protocol"
CONDITIONS_DUE_AT = "2026-08-31T00:00:00Z"


def _screened_snack_project(gate_overrides=None, owner="lead-gs", chair="chair-gs"):
    """A snack project screened into SCREENED with a computed business case."""
    ctx = setup_screened_project(
        category="SNACK", project_type="LINE_EXTENSION",
        gate_overrides=gate_overrides,
        project_overrides={"name": "Toffee Crunch Bites"},
        owner_user_id=owner, chair_user_id=chair,
    )
    case, line = open_case_with_line(ctx["project"]["id"])
    ctx["business_case"] = case
    ctx["forecast_line"] = line
    return ctx


def _conditionally_passed_snack_project(owner="lead-cw", chair="chair-cw"):
    """A snack project carried through gate 2 on the conditional-pass branch."""
    ctx = _screened_snack_project(owner=owner, chair=chair)
    gate3 = register_stage_gate(gate_number=3, category="SNACK",
                                stage_from="PILOT_QUALIFIED", stage_to="LAUNCH_READY")
    review = run_gate_session(
        ctx["project"]["id"], ctx["gate2"]["id"],
        votes=(("OPERATIONS", "APPROVE_WITH_CONDITIONS", "rev-ops-cw"),),
        chair_user_id=chair,
        close_payload={"conditions": CONDITIONS, "conditions_due_at": CONDITIONS_DUE_AT},
    )
    ctx["gate3"] = gate3
    ctx["gate2_review"] = review
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def test_a_gate_out_of_turn_is_refused_although_the_project_holds_its_stage_from(
    api, portfolio_admin_headers
):
    """Gate 4 admits the project's SCREENED state yet is not the gate it owes next.

    PRD: "The gate's `gate_number` must equal the project's `next_gate_number`, else
    `ERR_GATE_SEQUENCE_VIOLATION` (409) — this is what stops a project skipping a gate, and what
    forces a recycled project to re-run the earlier gate."

    Design: Corner/errors/err_gate_open_ladder_refuses_out_of_turn_sessions
    """
    ctx = _screened_snack_project()
    later_gate = register_stage_gate(gate_number=4, category="SNACK", stage_from="SCREENED",
                                     stage_to="PILOT_QUALIFIED")
    review = schedule_gate_review(ctx["project"]["id"], later_gate["id"],
                                  chair_user_id="chair-gs")

    response = api.open_gate_review(review["id"], {}, make_gate_chair_headers("chair-gs"))

    validate_error(response, "ERR_GATE_SEQUENCE_VIOLATION", 409)
    refused = validate_success(api.get_gate_review(review["id"], portfolio_admin_headers))
    assert refused["status"] == "SCHEDULED"
    assert refused["readiness_index"] == pytest.approx(0.00, abs=0.01), (
        "a review that never opened has no frozen figures"
    )
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "SCREENED"
    assert project["next_gate_number"] == 2


def test_a_second_session_is_refused_while_one_review_is_already_open(
    api, portfolio_admin_headers
):
    """Two reviews of the same gate cannot both hold the room.

    PRD: "No other review of the same project may already be `IN_SESSION`, else
    `ERR_GATE_REVIEW_ALREADY_IN_SESSION` (409)."

    Design: Corner/errors/err_gate_open_ladder_refuses_out_of_turn_sessions
    """
    ctx = _screened_snack_project()
    first = schedule_gate_review(ctx["project"]["id"], ctx["gate2"]["id"],
                                 chair_user_id="chair-gs")
    second = schedule_gate_review(ctx["project"]["id"], ctx["gate2"]["id"],
                                  chair_user_id="chair-gs",
                                  scheduled_at="2026-08-06T09:00:00Z")
    opened = open_gate_review(first["id"], chair_user_id="chair-gs")
    assert opened["status"] == "IN_SESSION"

    response = api.open_gate_review(second["id"], {}, make_gate_chair_headers("chair-gs"))

    validate_error(response, "ERR_GATE_REVIEW_ALREADY_IN_SESSION", 409)
    assert validate_success(
        api.get_gate_review(second["id"], portfolio_admin_headers)
    )["status"] == "SCHEDULED", "the loser of the race stays scheduled"
    assert validate_success(
        api.get_gate_review(first["id"], portfolio_admin_headers)
    )["status"] == "IN_SESSION"


def test_unresolved_conditions_block_the_next_gate_entirely(api, portfolio_admin_headers):
    """A conditional pass moves the project forward but bars the gate 3 session.

    PRD: "And `open_gate_conditions` on the project must be false, else
    `ERR_GATE_CONDITIONS_OPEN` (409) — unresolved conditions from an earlier conditional pass
    block the next gate entirely."

    Design: Corner/errors/err_gate_open_ladder_refuses_out_of_turn_sessions
    """
    ctx = _conditionally_passed_snack_project(owner="lead-gs", chair="chair-gs")
    assert ctx["gate2_review"]["decision"] == "CONDITIONAL_PASS"
    assert ctx["project"]["dev_status"] == "PILOT_QUALIFIED"
    assert ctx["project"]["next_gate_number"] == 3
    assert ctx["project"]["open_gate_conditions"] is True
    review = schedule_gate_review(ctx["project"]["id"], ctx["gate3"]["id"],
                                  chair_user_id="chair-gs")

    response = api.open_gate_review(review["id"], {}, make_gate_chair_headers("chair-gs"))

    validate_error(response, "ERR_GATE_CONDITIONS_OPEN", 409)
    assert validate_success(
        api.get_gate_review(review["id"], portfolio_admin_headers)
    )["status"] == "SCHEDULED"
    assert read_project(ctx["project"]["id"])["dev_status"] == "PILOT_QUALIFIED"


def test_a_close_under_quorum_reports_the_quorum_error_before_deriving_a_decision(
    api, portfolio_admin_headers
):
    """With a quorum of two, an empty ballot box and a lone REJECT both report quorum.

    PRD: "`vote_count` must be at least the gate's `quorum_size`, else `ERR_QUORUM_NOT_MET`
    (409) — and because quorum is checked **before the decision is derived**, a lone `REJECT`
    ballot under quorum reports the quorum error rather than killing the project."

    Design: Corner/errors/err_gate_close_ladder_refuses_thin_quorum_then_thin_readiness
    """
    ctx = _screened_snack_project(
        gate_overrides={"quorum_size": 2, "readiness_floor_index": 90.00},
        owner="lead-qc", chair="chair-qc",
    )
    review = schedule_gate_review(ctx["project"]["id"], ctx["gate2"]["id"],
                                  chair_user_id="chair-qc")
    open_gate_review(review["id"], chair_user_id="chair-qc")

    validate_error(
        api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-qc")),
        "ERR_QUORUM_NOT_MET",
        409,
    )
    cast_vote(review["id"], function="OPERATIONS", vote="REJECT", voter_user_id="rev-ops-qc")
    validate_error(
        api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-qc")),
        "ERR_QUORUM_NOT_MET",
        409,
    )

    held = validate_success(api.get_gate_review(review["id"], portfolio_admin_headers))
    assert held["status"] == "IN_SESSION"
    assert held["decision"] is None, "the lone rejection never killed the project"
    assert held["closed_at"] is None
    assert held["vote_count"] == 1
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "SCREENED"
    assert project["recycle_count"] == 0


def test_with_quorum_met_the_readiness_floor_refuses_the_close(api, portfolio_admin_headers):
    """The second ballot clears quorum and exposes a readiness index of 55.00 against a floor of 90.00.

    PRD: "Both passing branches — and only the passing branches — must clear three further bars,
    evaluated in this order: `deliverable_completeness_pct` must be exactly `100.00`, else
    `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422); `readiness_index` must be at least the gate's
    `readiness_floor_index`, else `ERR_GATE_READINESS_BELOW_FLOOR` (422); and the authoritative
    business case must clear all three financial hurdles, else `ERR_BUSINESS_CASE_HURDLE_NOT_MET`
    (422)."

    Design: Corner/errors/err_gate_close_ladder_refuses_thin_quorum_then_thin_readiness
    """
    ctx = _screened_snack_project(
        gate_overrides={"quorum_size": 2, "readiness_floor_index": 90.00},
        owner="lead-qc", chair="chair-qc",
    )
    review = schedule_gate_review(ctx["project"]["id"], ctx["gate2"]["id"],
                                  chair_user_id="chair-qc")
    open_gate_review(review["id"], chair_user_id="chair-qc")
    cast_vote(review["id"], function="OPERATIONS", vote="APPROVE", voter_user_id="rev-ops-qc")
    cast_vote(review["id"], function="FINANCE", vote="APPROVE", voter_user_id="rev-fin-qc")

    response = api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-qc"))

    validate_error(response, "ERR_GATE_READINESS_BELOW_FLOOR", 422)
    held = validate_success(api.get_gate_review(review["id"], portfolio_admin_headers))
    assert held["status"] == "IN_SESSION"
    assert held["decision"] is None
    assert held["vote_count"] == 2
    assert held["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "an empty required-types array is vacuously complete, so completeness masks nothing"
    )
    assert held["readiness_index"] == pytest.approx(55.00, abs=0.01)
    _, meta = validate_paginated(api.list_gate_votes(review["id"], portfolio_admin_headers))
    assert meta["total_count"] == 2
    assert read_project(ctx["project"]["id"])["dev_status"] == "SCREENED"


def test_submission_waits_for_the_prerequisite_to_be_settled(
    api, innovation_lead_headers, portfolio_admin_headers
):
    """The dependent item is refused until its prerequisite is approved, then submits cleanly.

    PRD: "Two further conditions apply: the item's prerequisite, if any, must itself be
    `APPROVED` or `WAIVED`, else `ERR_PREREQUISITE_NOT_SATISFIED` (409); and the owning project's
    `dev_status` must be neither `KILLED` nor `DISCONTINUED`."

    Design: Corner/errors/err_checklist_graph_guards_protect_order_and_uniqueness
    """
    ctx = _screened_snack_project(owner="lead-cg", chair="chair-cg")
    project_id = ctx["project"]["id"]
    first = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="MANUFACTURING_READINESS",
                                                   owner_function="OPERATIONS"),
                               innovation_lead_headers),
        201,
    )
    second = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="DISTRIBUTION_READINESS",
                                                   owner_function="SALES",
                                                   prerequisite_deliverable_id=first["id"]),
                               innovation_lead_headers),
        201,
    )

    validate_error(
        api.submit_deliverable(second["id"],
                               {"evidence_url": "https://evidence.example/distribution"},
                               innovation_lead_headers),
        "ERR_PREREQUISITE_NOT_SATISFIED",
        409,
    )
    blocked = validate_success(api.get_deliverable(second["id"], portfolio_admin_headers))
    assert blocked["status"] == "PENDING"
    assert blocked["submission_count"] == 0

    submit_deliverable(first["id"], submitter_user_id="lead-cg-sub")
    cleared = decide_deliverable(first["id"], "APPROVE", decider_user_id="rev-cg-dec")
    assert cleared["status"] == "APPROVED"
    released = validate_success(
        api.submit_deliverable(second["id"],
                               {"evidence_url": "https://evidence.example/distribution"},
                               innovation_lead_headers)
    )

    assert released["status"] == "SUBMITTED"
    assert released["submission_count"] == 1
    _, meta = validate_paginated(
        api.list_deliverables(portfolio_admin_headers, params={"project_id": project_id})
    )
    assert meta["total_count"] == 2


def test_neither_a_back_edge_nor_a_self_edge_may_close_the_prerequisite_chain(
    api, innovation_lead_headers, portfolio_admin_headers
):
    """A three-item chain refuses both the loop-closing edge and the shortest loop of all.

    PRD: "Either way, if the named prerequisite does not resolve the answer is
    `ERR_PREREQUISITE_NOT_FOUND` (404), and if the proposed edge would close a loop in the
    project's existing prerequisite chain the answer is `ERR_DELIVERABLE_CYCLE` (409) — a
    self-edge is the shortest such loop and is rejected on exactly the same footing as a longer
    one, so the server walks the whole chain rather than only comparing the two endpoints."

    Design: Corner/errors/err_checklist_graph_guards_protect_order_and_uniqueness
    """
    ctx = _screened_snack_project(owner="lead-cy", chair="chair-cy")
    project_id = ctx["project"]["id"]
    gate_id = ctx["gate2"]["id"]
    first = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(gate_id,
                                                   deliverable_type="MANUFACTURING_READINESS",
                                                   owner_function="OPERATIONS"),
                               innovation_lead_headers),
        201,
    )
    second = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(gate_id,
                                                   deliverable_type="DISTRIBUTION_READINESS",
                                                   owner_function="SALES",
                                                   prerequisite_deliverable_id=first["id"]),
                               innovation_lead_headers),
        201,
    )
    third = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(gate_id,
                                                   deliverable_type="MARKETING_LAUNCH_PLAN",
                                                   owner_function="MARKETING",
                                                   prerequisite_deliverable_id=second["id"]),
                               innovation_lead_headers),
        201,
    )

    validate_error(
        api.set_deliverable_prerequisite(first["id"],
                                         {"prerequisite_deliverable_id": third["id"]},
                                         innovation_lead_headers),
        "ERR_DELIVERABLE_CYCLE",
        409,
    )
    validate_error(
        api.set_deliverable_prerequisite(first["id"],
                                         {"prerequisite_deliverable_id": first["id"]},
                                         innovation_lead_headers),
        "ERR_DELIVERABLE_CYCLE",
        409,
    )

    head = validate_success(api.get_deliverable(first["id"], portfolio_admin_headers))
    assert head["prerequisite_deliverable_id"] is None, "the chain still has a head"
    assert validate_success(
        api.get_deliverable(third["id"], portfolio_admin_headers)
    )["prerequisite_deliverable_id"] == second["id"]
    _, meta = validate_paginated(
        api.list_deliverables(portfolio_admin_headers, params={"project_id": project_id})
    )
    assert meta["total_count"] == 3


def test_a_regulatory_clearance_item_can_never_be_waived(
    api, innovation_lead_headers, gate_chair_headers, portfolio_admin_headers
):
    """The chair may waive a readiness plan but never the regulatory clearance.

    PRD: "The one exception is absolute: a `REGULATORY_CLEARANCE` item can never be waived, and
    the attempt answers `ERR_REGULATORY_WAIVER_FORBIDDEN` (409)."

    Design: Corner/errors/err_checklist_graph_guards_protect_order_and_uniqueness
    """
    ctx = _screened_snack_project(owner="lead-rw", chair="chair-1")
    project_id = ctx["project"]["id"]
    regulatory = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="REGULATORY_CLEARANCE",
                                                   owner_function="REGULATORY"),
                               innovation_lead_headers),
        201,
    )
    manufacturing = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="MANUFACTURING_READINESS",
                                                   owner_function="OPERATIONS"),
                               innovation_lead_headers),
        201,
    )

    response = api.waive_deliverable(
        regulatory["id"], {"reason": "Claims cleared verbally by counsel"}, gate_chair_headers
    )

    validate_error(response, "ERR_REGULATORY_WAIVER_FORBIDDEN", 409)
    assert validate_success(
        api.get_deliverable(regulatory["id"], portfolio_admin_headers)
    )["status"] == "PENDING"
    waived = validate_success(
        api.waive_deliverable(manufacturing["id"],
                              {"reason": "Existing line qualification carried over"},
                              gate_chair_headers)
    )
    assert waived["status"] == "WAIVED", "the prohibition is specific to regulatory clearance"


def test_a_second_live_item_of_the_same_type_on_the_same_gate_is_a_duplicate(
    api, innovation_lead_headers, portfolio_admin_headers
):
    """A different owning function does not make a second manufacturing item admissible.

    PRD: "A live item already occupying the same combination of `project_id`, `gate_id` and
    `deliverable_type` makes the request a duplicate, rejected with
    `ERR_DUPLICATE_DELIVERABLE_TYPE`."

    Design: Corner/errors/err_checklist_graph_guards_protect_order_and_uniqueness
    """
    ctx = _screened_snack_project(owner="lead-du", chair="chair-du")
    project_id = ctx["project"]["id"]
    validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="MANUFACTURING_READINESS",
                                                   owner_function="OPERATIONS"),
                               innovation_lead_headers),
        201,
    )

    response = api.create_deliverable(
        project_id,
        deliverable_payload(ctx["gate2"]["id"],
                            deliverable_type="MANUFACTURING_READINESS",
                            owner_function="QUALITY"),
        innovation_lead_headers,
    )

    validate_error(response, "ERR_DUPLICATE_DELIVERABLE_TYPE", 409)
    accepted = validate_success(
        api.create_deliverable(project_id,
                               deliverable_payload(ctx["gate2"]["id"],
                                                   deliverable_type="DISTRIBUTION_READINESS",
                                                   owner_function="SALES"),
                               innovation_lead_headers),
        201,
    )
    assert accepted["deliverable_type"] == "DISTRIBUTION_READINESS"
    _, meta = validate_paginated(
        api.list_deliverables(portfolio_admin_headers, params={"project_id": project_id})
    )
    assert meta["total_count"] == 2, "the duplicate type was never stored"


def test_expiry_is_refused_before_and_at_the_conditions_deadline(
    api, portfolio_admin_headers
):
    """The deadline instant itself is still on time, so expiry is not yet due.

    PRD: "If instead the deadline lapses, a `PortfolioAdmin` expires the conditions: the current
    instant must have passed `conditions_due_at`, else `ERR_CONDITIONS_NOT_DUE` (409)."

    Design: Corner/errors/err_conditions_window_swaps_at_the_due_instant
    """
    ctx = _conditionally_passed_snack_project()
    review_id = ctx["gate2_review"]["id"]
    assert ctx["gate2_review"]["conditions_due_at"] == CONDITIONS_DUE_AT

    validate_error(api.expire_gate_conditions(review_id, {}, portfolio_admin_headers),
                   "ERR_CONDITIONS_NOT_DUE", 409)
    set_clock(CONDITIONS_DUE_AT)
    validate_error(api.expire_gate_conditions(review_id, {}, portfolio_admin_headers),
                   "ERR_CONDITIONS_NOT_DUE", 409)

    held = validate_success(api.get_gate_review(review_id, portfolio_admin_headers))
    assert held["status"] == "CONDITIONAL_PASS"
    assert held["decision"] == "CONDITIONAL_PASS"
    project = read_project(ctx["project"]["id"])
    assert project["open_gate_conditions"] is True
    assert project["dev_status"] == "PILOT_QUALIFIED"
    assert project["recycle_count"] == 0


def test_one_second_past_the_deadline_clearing_is_refused_and_expiry_recycles(
    api, portfolio_admin_headers
):
    """A single second flips the window: the chair is too late and the admin is finally due.

    PRD: "The current instant must not have passed `conditions_due_at` — the deadline instant
    itself still counts as on time — else `ERR_CONDITIONS_DUE_PASSED` (409); and the gate
    checklist's `deliverable_completeness_pct` must be `100.00` at clearing time, else
    `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422)."

    PRD: "Expiry takes the review `CONDITIONAL_PASS → RECYCLED`, sets `open_gate_conditions` to
    false, steps the project back one stage by the same ladder-and-floor rule as a recycled
    close, and increments `recycle_count`."

    Design: Corner/errors/err_conditions_window_swaps_at_the_due_instant
    """
    ctx = _conditionally_passed_snack_project()
    review_id = ctx["gate2_review"]["id"]
    set_clock("2026-08-31T00:00:01Z")

    validate_error(
        api.clear_gate_conditions(review_id,
                                  {"resolution_note": "Protocol signed by the co-packer"},
                                  make_gate_chair_headers("chair-cw")),
        "ERR_CONDITIONS_DUE_PASSED",
        409,
    )
    expired = validate_success(
        api.expire_gate_conditions(review_id, {}, portfolio_admin_headers)
    )

    assert expired["status"] == "RECYCLED"
    assert expired["decision"] == "RECYCLED"
    project = read_project(ctx["project"]["id"])
    assert project["open_gate_conditions"] is False
    assert project["dev_status"] == "SCREENED", (
        "the recycle stepped back to the floor below the gate's stage_from"
    )
    assert project["next_gate_number"] == 2
    assert project["recycle_count"] == 1
