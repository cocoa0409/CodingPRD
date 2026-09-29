"""Opening a gate on an empty checklist, the veto fork, and the kill cascade."""
import pytest

from test_helpers import (
    assert_gate_review,
    cast_vote,
    deliverable_by_type,
    intake_project,
    make_gate_chair_headers,
    open_case_with_line,
    open_gate_review,
    open_reset_window,
    present_presentation,
    project_deliverables,
    read_project,
    read_window,
    record_outcome,
    register_retailer,
    register_stage_gate,
    run_gate_session,
    schedule_gate_review,
    screen_project,
    set_clock,
    setup_screened_project,
    validate_paginated,
    validate_success,
    book_presentation,
)


def _empty_checklist_review():
    """A screened snack project with no evidence at all and a scheduled gate 2 review."""
    ctx = setup_screened_project(
        category="SNACK", project_type="LINE_EXTENSION",
        gate_overrides={"required_deliverable_types": [], "quorum_size": 1},
        project_overrides={"name": "Empty Checklist Probe"},
        owner_user_id="lead-ec", chair_user_id="chair-ec",
    )
    review = schedule_gate_review(
        ctx["project"]["id"], ctx["gate2"]["id"], chair_user_id="chair-ec",
        scheduled_at="2026-08-05T09:00:00Z",
    )
    ctx["review"] = review
    return ctx


def _fork_projects():
    """Two identical dairy projects screened against a gate whose FINANCE seat has a veto."""
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(
        gate_number=2, category="DAIRY", quorum_size=2, veto_functions=["FINANCE"],
    )
    projects = []
    for name, owner in (("Fork Probe A", "lead-pa"), ("Fork Probe B", "lead-pb")):
        project = intake_project(
            owner_user_id=owner, name=name, category="DAIRY", project_type="LINE_EXTENSION",
        )
        projects.append(screen_project(project["id"], chair_user_id="chair-d"))
    return gate, projects[0], projects[1]


def _review_with_rejecting_seat(gate, project, function, rationale, scheduled_at):
    review = schedule_gate_review(project["id"], gate["id"], chair_user_id="chair-d",
                                  scheduled_at=scheduled_at)
    open_gate_review(review["id"], chair_user_id="chair-d")
    cast_vote(review["id"], function=function, vote="REJECT", voter_user_id="rev-fin"
              if function == "FINANCE" else "rev-mkt", rationale=rationale)
    cast_vote(review["id"], function="OPERATIONS", vote="APPROVE", voter_user_id="rev-ops")
    return review


def _kill_cascade_setup(api):
    """A snack project authorised by a retailer and sitting in an IN_SESSION gate 3 review."""
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(gate_number=2, category="SNACK")
    gate3 = register_stage_gate(
        gate_number=3, category="SNACK", stage_from="PILOT_QUALIFIED",
        stage_to="LAUNCH_READY", veto_functions=["OPERATIONS"],
    )
    retailer = register_retailer(name="SnackMart", channel="GROCERY",
                                acv_contribution_pct=28.00, presentation_lead_days=21)
    window = open_reset_window(
        retailer["id"], category="SNACK", window_start="2026-10-12T00:00:00Z",
        window_end="2026-11-06T23:59:59Z", max_presentations=2,
    )
    project = intake_project(owner_user_id="lead-kc", name="Kill Cascade Probe",
                             category="SNACK", project_type="LINE_EXTENSION")
    screen_project(project["id"], chair_user_id="chair-kc")
    case, line = open_case_with_line(project["id"])
    gate2_review = run_gate_session(project["id"], gate2["id"], chair_user_id="chair-kc",
                                    scheduled_at="2026-08-04T09:00:00Z")
    spare_item = validate_success(
        api.create_deliverable(
            project["id"],
            {"gate_id": gate3["id"], "deliverable_type": "MARKETING_LAUNCH_PLAN",
             "owner_function": "MARKETING"},
            make_gate_chair_headers("chair-kc"),
        ),
        201,
    )
    presentation = book_presentation(
        project["id"], retailer["id"], window["id"], scheduled_at="2026-09-14T10:00:00Z",
        proposed_sku_count=3,
    )
    set_clock("2026-09-14T10:00:00Z")
    present_presentation(presentation["id"])
    presentation = record_outcome(presentation["id"], "ACCEPTED", accepted_sku_count=3)
    review = schedule_gate_review(project["id"], gate3["id"], chair_user_id="chair-kc",
                                  scheduled_at="2026-09-15T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-kc")
    cast_vote(review["id"], function="OPERATIONS", vote="REJECT", voter_user_id="rev-ops",
              rationale="Line capacity unavailable")
    return {
        "gate2": gate2, "gate3": gate3, "retailer": retailer, "window": window,
        "project": read_project(project["id"]), "business_case": case, "forecast_line": line,
        "gate2_review": gate2_review, "spare_item": spare_item,
        "presentation": presentation, "review": review,
    }


def test_a_gate_with_an_empty_checklist_opens_at_full_completeness(api):
    """An empty required list is vacuously complete, not zero.

    PRD: "If the gate's `required_deliverable_types` array is empty the value is `100.00` — an
    empty checklist is vacuously complete, not zero and not a division error."

    Design: Difficulty/boundary_precision_check/empty_required_checklist_is_vacuously_complete
    """
    ctx = _empty_checklist_review()

    opened = validate_success(
        api.open_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-ec"))
    )

    assert_gate_review(opened)
    assert opened["status"] == "IN_SESSION"
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)
    assert opened["deliverable_completeness_pct"] != pytest.approx(0.00, abs=0.001)
    _, meta = validate_paginated(
        api.list_deliverables(
            make_gate_chair_headers("chair-ec"),
            params={"project_id": ctx["project"]["id"], "gate_id": ctx["gate2"]["id"]},
        )
    )
    assert meta["total_count"] == 0, (
        "the 100.00 came from the empty checklist rule, not from counting rows"
    )


def test_the_readiness_index_of_an_empty_checklist_rests_on_completeness_alone(api):
    """With no concept test, case or formulation the index is the completeness term only.

    PRD: "Those four — completeness, concept, hurdle, yield, in that order — are combined under
    a weight vector chosen by the project's `project_type`: `NEW_BRAND` weights them 0.35, 0.30,
    0.20 and 0.15; `LINE_EXTENSION` weights them 0.30, 0.25, 0.25 and 0.20; `RENOVATION`
    weights them 0.40, 0.20, 0.20 and 0.20."

    Design: Difficulty/boundary_precision_check/empty_required_checklist_is_vacuously_complete
    """
    ctx = _empty_checklist_review()

    opened = validate_success(
        api.open_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-ec"))
    )

    assert opened["readiness_index"] == pytest.approx(30.00, abs=0.01), (
        "0.30 * 100.00 with concept, hurdle and yield all 0.00 and a snack factor of 1.00"
    )
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)


def test_a_rejection_from_a_veto_seat_kills_the_project(api):
    """FINANCE holds the veto, so its REJECT ends the project outright.

    PRD: "- **`IN_SESSION → KILLED`** when at least one `REJECT` ballot came from a seat listed
    in `veto_functions`. `decision` becomes `KILLED` and the full kill cascade runs."

    Design: Difficulty/non_linear_state_machine/gate_review_veto_fork_divergent_project_outcomes
    """
    gate, project_a, _ = _fork_projects()
    review = _review_with_rejecting_seat(
        gate, project_a, "FINANCE", "Margin thesis unproven", "2026-08-05T09:00:00Z"
    )

    closed = validate_success(
        api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-d"))
    )

    assert closed["status"] == "KILLED"
    assert closed["decision"] == "KILLED"
    assert closed["vote_count"] == 2
    project = read_project(project_a["id"])
    assert project["dev_status"] == "KILLED"
    assert project["recycle_count"] == 0


def test_a_rejection_from_a_non_veto_seat_recycles_the_project(api):
    """MARKETING has no veto, so its REJECT recycles instead of killing.

    PRD: "- **`IN_SESSION → RECYCLED`** when at least one ballot is `REJECT` and no rejecting
    ballot came from a seat listed in the gate's `veto_functions`. `decision` becomes
    `RECYCLED`, `closed_at` and `chair_user_id` are stamped, and the project steps **back** one
    stage."

    Design: Difficulty/non_linear_state_machine/gate_review_veto_fork_divergent_project_outcomes
    """
    gate, _, project_b = _fork_projects()
    review = _review_with_rejecting_seat(
        gate, project_b, "MARKETING", "Positioning needs rework", "2026-08-05T11:00:00Z"
    )

    closed = validate_success(
        api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-d"))
    )

    assert closed["status"] == "RECYCLED"
    assert closed["decision"] == "RECYCLED"
    assert closed["vote_count"] == 2
    project = read_project(project_b["id"])
    assert project["dev_status"] == "SCREENED", (
        "recycling a gate whose stage_from is SCREENED self-loops at the floor"
    )
    assert project["recycle_count"] == 1
    assert project["next_gate_number"] == 2


def test_only_the_rejecting_seat_separates_a_killed_from_a_recycled_project(api):
    """Two identically balloted reviews diverge solely on which function rejected.

    PRD: "Recycling a gate whose `stage_from` is `SCREENED` would step below the floor, so
    `dev_status` self-loops `SCREENED → SCREENED`, `next_gate_number` stays 2, and
    `recycle_count` still increments."

    Design: Difficulty/non_linear_state_machine/gate_review_veto_fork_divergent_project_outcomes
    """
    gate, project_a, project_b = _fork_projects()
    review_a = _review_with_rejecting_seat(
        gate, project_a, "FINANCE", "Margin thesis unproven", "2026-08-05T09:00:00Z"
    )
    closed_a = validate_success(
        api.close_gate_review(review_a["id"], {}, make_gate_chair_headers("chair-d"))
    )
    review_b = _review_with_rejecting_seat(
        gate, project_b, "MARKETING", "Positioning needs rework", "2026-08-05T11:00:00Z"
    )
    closed_b = validate_success(
        api.close_gate_review(review_b["id"], {}, make_gate_chair_headers("chair-d"))
    )

    assert (closed_a["decision"], closed_b["decision"]) == ("KILLED", "RECYCLED")
    assert closed_a["vote_count"] == closed_b["vote_count"] == 2
    assert read_project(project_a["id"])["dev_status"] == "KILLED"
    assert read_project(project_b["id"])["dev_status"] == "SCREENED"
    assert read_project(project_a["id"])["recycle_count"] == 0
    assert read_project(project_b["id"])["recycle_count"] == 1


def test_a_vetoed_gate_three_withdraws_the_accepted_presentation(api):
    """The kill cascade reaches the retailer's accepted trade presentation.

    PRD: "Every trade presentation of the project whose `status` is `PLANNED`, `PRESENTED`,
    `DEFERRED` or `ACCEPTED` moves to `WITHDRAWN`, each one decrementing its reset window's
    `booked_slot_count`, and each one that was `ACCEPTED` also reducing the project's
    `authorized_acv_pct` by that retailer's `acv_contribution_pct`."

    Design: Difficulty/transitive_cascade/gate_kill_cascade_releases_retailer_slot
    """
    ctx = _kill_cascade_setup(api)
    assert ctx["presentation"]["status"] == "ACCEPTED"

    closed = validate_success(
        api.close_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-kc"))
    )

    assert closed["status"] == "KILLED"
    assert closed["decision"] == "KILLED"
    assert closed["vote_count"] == 1
    assert read_project(ctx["project"]["id"])["dev_status"] == "KILLED"
    presentation = validate_success(
        api.get_sell_in_presentation(ctx["presentation"]["id"],
                                     make_gate_chair_headers("chair-kc"))
    )
    assert presentation["status"] == "WITHDRAWN"


def test_the_kill_cascade_releases_the_window_slot_and_the_authorized_acv(api):
    """The slot counter and the ACV total both return to zero.

    PRD: "Finally the commercial track is reset: `commercial_status` returns to `NOT_STARTED`,
    and `launch_date` and `shelf_reset_window_id` are cleared to null."

    Design: Difficulty/transitive_cascade/gate_kill_cascade_releases_retailer_slot
    """
    ctx = _kill_cascade_setup(api)
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1
    assert read_project(ctx["project"]["id"])["authorized_acv_pct"] == pytest.approx(
        28.00, abs=0.01
    )

    validate_success(
        api.close_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-kc"))
    )

    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 0
    project = read_project(ctx["project"]["id"])
    assert project["authorized_acv_pct"] == pytest.approx(0.00, abs=0.01)
    assert project["commercial_status"] == "NOT_STARTED"
    assert project["launch_date"] is None
    assert project["shelf_reset_window_id"] is None


def test_the_kill_cascade_cancels_open_checklist_items_but_spares_closed_reviews(api):
    """Live checklist items are cancelled while the passed gate 2 review stands.

    PRD: "Every checklist item on the project whose `status` is `PENDING`, `SUBMITTED` or
    `REJECTED` moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/gate_kill_cascade_releases_retailer_slot
    """
    ctx = _kill_cascade_setup(api)
    assert ctx["spare_item"]["status"] == "PENDING"

    validate_success(
        api.close_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-kc"))
    )

    cancelled = deliverable_by_type(
        ctx["project"]["id"], "MARKETING_LAUNCH_PLAN", gate_id=ctx["gate3"]["id"]
    )
    assert cancelled["status"] == "CANCELLED"
    assert all(item["status"] == "CANCELLED"
               for item in project_deliverables(ctx["project"]["id"])), (
        "no live checklist item survives the kill"
    )
    gate2_review = validate_success(
        api.get_gate_review(ctx["gate2_review"]["id"], make_gate_chair_headers("chair-kc"))
    )
    assert gate2_review["status"] == "PASSED", "a closed review is not touched by the cascade"
