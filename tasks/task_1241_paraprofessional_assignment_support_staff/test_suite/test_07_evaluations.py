"""Evaluations: authoring ownership, segregation of duties on countersign, and the
acknowledge / dispute / resolve branches (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_plan,
    create_evaluation,
    create_evaluation_payload,
    create_para,
    make_building_admin_headers,
    make_para_headers,
    make_teacher_headers,
    setup_countersigned_evaluation,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


def test_evaluation_submit_restricted_to_author(api):
    """PRD §3.8: "Submission moves an evaluation from `DRAFT` to `SUBMITTED` and is restricted to the author — `X-User-ID` must equal `created_by_user_id`, else `ERR_EVALUATION_NOT_OWN`."

    Design: Corner/rbac/evaluation_submit_by_other_teacher_returns_not_own
    """
    plan, building, _ = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    ev = create_evaluation(plan["id"], p1["id"], author_headers=make_teacher_headers("teacher-1"))

    resp = api.submit_evaluation(ev["id"], make_teacher_headers("teacher-2"))
    validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_OWN)
    after = validate_success(api.get_evaluation(ev["id"], ANY))
    assert after["status"] == "DRAFT"


def test_countersign_by_author_rejected_as_self_countersign(api):
    """PRD §3.8: "Countersigning moves a `SUBMITTED` evaluation to `COUNTERSIGNED` under an explicit segregation of duties: the acting `BuildingAdministrator` must not be the author, so `X-User-ID` equal to `created_by_user_id` is rejected with `ERR_EVALUATION_SELF_COUNTERSIGN` (HTTP 403); on success the administrator’s `X-User-ID` is written to `countersigned_by_user_id`."

    Design: Corner/rbac/countersign_same_user_as_author_rejected
    """
    plan, building, _ = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    ev = create_evaluation(
        plan["id"], p1["id"], author_headers=make_teacher_headers("teacher-1"),
        professionalism_score=3, instructional_support_score=3, comments="mid",
    )
    validate_success(api.submit_evaluation(ev["id"], make_teacher_headers("teacher-1")))

    # Correct role, but X-User-ID equals the authoring teacher's id
    resp = api.countersign_evaluation(ev["id"], make_building_admin_headers("teacher-1"))
    validate_error(resp, ApiErrorId.ERR_EVALUATION_SELF_COUNTERSIGN)


def test_evaluation_acknowledge_and_dispute_resolve_paths(api):
    """PRD §3.8: "The evaluated para then responds personally — both acknowledgement and dispute require `X-User-ID` to equal the evaluation’s `para_id`, else `ERR_EVALUATION_NOT_OWN` — moving the evaluation from `COUNTERSIGNED` to `ACKNOWLEDGED`, which is terminal, or to `DISPUTED`. A `BuildingAdministrator` resolves a `DISPUTED` evaluation into the terminal `RESOLVED` state, recording the request’s `resolution_note` on the record."
    PRD §3.8: "Countersigning moves a `SUBMITTED` evaluation to `COUNTERSIGNED` under an explicit segregation of duties: the acting `BuildingAdministrator` must not be the author, so `X-User-ID` equal to `created_by_user_id` is rejected with `ERR_EVALUATION_SELF_COUNTERSIGN` (HTTP 403); on success the administrator’s `X-User-ID` is written to `countersigned_by_user_id`."

    Design: Corner/rbac/evaluation_full_and_dispute_paths
    """
    scenario = setup_countersigned_evaluation()
    plan, p1, ev1 = scenario["plan"], scenario["p1"], scenario["ev"]
    assert ev1["status"] == "COUNTERSIGNED"
    assert ev1["countersigned_by_user_id"] == "admin-9"

    # Branch 1: acknowledge -> ACKNOWLEDGED (terminal)
    acked = validate_success(
        api.acknowledge_evaluation(ev1["id"], make_para_headers(p1["id"]))
    )
    assert acked["status"] == "ACKNOWLEDGED"

    # Branch 2: dispute -> DISPUTED -> resolve -> RESOLVED with resolution_note
    ev2 = create_evaluation(
        plan["id"], p1["id"], author_headers=make_teacher_headers("teacher-1"),
        professionalism_score=2, instructional_support_score=2, comments="concerns",
    )
    validate_success(api.submit_evaluation(ev2["id"], make_teacher_headers("teacher-1")))
    validate_success(api.countersign_evaluation(ev2["id"], make_building_admin_headers("admin-9")))
    disputed = validate_success(api.dispute_evaluation(ev2["id"], make_para_headers(p1["id"])))
    assert disputed["status"] == "DISPUTED"
    resolved = validate_success(
        api.resolve_evaluation(
            ev2["id"],
            {"resolution_note": "reviewed with principal; scores stand"},
            make_building_admin_headers("admin-9"),
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_note"] == "reviewed with principal; scores stand"


def test_acknowledged_evaluation_is_terminal(api):
    """PRD §3.8: "Any evaluation transition attempted from a state that does not declare it is `ERR_EVALUATION_INVALID_STATE`."
    PRD §3.8: "The evaluated para then responds personally — both acknowledgement and dispute require `X-User-ID` to equal the evaluation’s `para_id`, else `ERR_EVALUATION_NOT_OWN` — moving the evaluation from `COUNTERSIGNED` to `ACKNOWLEDGED`, which is terminal, or to `DISPUTED`."

    Design: Corner/state_machines/evaluation_terminal_lockdown
    """
    scenario = setup_countersigned_evaluation()
    p1, ev = scenario["p1"], scenario["ev"]
    acked = validate_success(api.acknowledge_evaluation(ev["id"], make_para_headers(p1["id"])))
    assert acked["status"] == "ACKNOWLEDGED"

    resp = api.dispute_evaluation(ev["id"], make_para_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_EVALUATION_INVALID_STATE)
    after = validate_success(api.get_evaluation(ev["id"], ANY))
    assert after["status"] == "ACKNOWLEDGED"
