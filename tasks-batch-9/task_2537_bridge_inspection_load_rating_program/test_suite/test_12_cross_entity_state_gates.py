"""
Gates that read another entity's state: a rating's source report, and a
submission's statewide scour-plan compliance.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import program_admin_headers

FIELD_DAY = "2026-09-02T12:00:00Z"


# ─── A rating written against a report that is only submitted ───────────────
def _submitted_but_unaccepted_report(client, roster, bridge):
    """A baseline report taken as far as `SUBMITTED` and deliberately left there."""
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)
    submitted = fx.submit_report(client, draft["inspection"]["id"], roster)
    return {"inspection": submitted, "elements": draft["elements"]}


def test_a_rating_cannot_be_written_from_a_report_awaiting_review(
    client, roster, bridge
):
    """
    The source report has passed submission but not review, and the rating create
    is refused on that other entity's state.

    PRD §3.4: "The source report must be an `ACCEPTED` inspection belonging to the
    same structure the rating is being written against; a report on a different
    structure, or one that has not been accepted, is rejected with
    `ERR_RATING_SOURCE_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/load_rating_create_requires_accepted_source_inspection
    """
    setup = _submitted_but_unaccepted_report(client, roster, bridge)
    version = fx.read_bridge_version(client, bridge["id"])

    response = client.create_load_rating(
        bridge["id"],
        f.load_rating_payload(version, setup["inspection"]["id"]),
        roster.engineer_headers,
    )

    validate_error(response, e.ERR_RATING_SOURCE_NOT_ACCEPTED, 422)
    assert fx.read_inspection(client, setup["inspection"]["id"])["status"] == "SUBMITTED"


def test_the_refused_rating_leaves_no_trace_on_either_entity(client, roster, bridge):
    """
    Nothing is written: the structure's rating collection is empty, its version has
    not moved, and it still has no governing rating.

    PRD §3.4: "A newly created rating is `DRAFT`, with every derived value computed
    immediately from the submitted inputs, and creating it increments the structure's
    `version` by one."
    PRD §2.3: "`total_count` (the number of records matching the filters before
    pagination)".

    Design: Difficulty/cross_entity_state_dependency/load_rating_create_requires_accepted_source_inspection
    """
    setup = _submitted_but_unaccepted_report(client, roster, bridge)
    before = fx.read_bridge(client, bridge["id"])

    client.create_load_rating(
        bridge["id"],
        f.load_rating_payload(before["version"], setup["inspection"]["id"]),
        roster.engineer_headers,
    )

    listing = fx.ratings_for_bridge(client, bridge["id"])
    assert listing["rows"] == []
    assert listing["meta"]["total_count"] == 0

    after = fx.read_bridge(client, bridge["id"])
    a.assert_version_unchanged(after["version"], before["version"], "bridge")
    assert after["governing_load_rating_id"] is None
    assert after["posting_required"] is False


def test_the_same_payload_is_accepted_once_the_report_is_accepted(
    client, roster, bridge
):
    """
    Only the source report's state was ever wrong: after review accepts it, the
    identical rating inputs produce the worked example of the rating equation.

    PRD §3.4: "The source report must be an `ACCEPTED` inspection belonging to the
    same structure the rating is being written against".
    PRD §3.4: "The operating denominator is 1.35 times 500 times 1.33, which is
    897.75, giving 0.6182…, rounded to 0.618, and 22.248, rounded to 22.2 tons."

    Design: Difficulty/cross_entity_state_dependency/load_rating_create_requires_accepted_source_inspection
    """
    setup = _submitted_but_unaccepted_report(client, roster, bridge)
    inspection_id = setup["inspection"]["id"]

    fx.qa_claim(client, inspection_id, roster)
    fx.qa_decide(client, inspection_id, roster, "ACCEPT")

    fresh_version = fx.read_bridge_version(client, bridge["id"])
    rating = validate_success(
        client.create_load_rating(
            bridge["id"],
            f.load_rating_payload(fresh_version, inspection_id),
            roster.engineer_headers,
        ),
        201,
    )

    assert rating["rating_factor_operating"] == 0.618
    assert rating["operating_rating_tons"] == 22.2
    assert rating["posting_required"] is True


# ─── A federal package blocked by a scour-critical structure ────────────────
def _scour_critical_inventory_with_a_locked_cycle(client, roster, bridge):
    """
    A structure finalised at scour code 2, which owes a plan of action it does not
    yet have, plus a locked cycle carrying a `BUILDING` federal package.
    """
    report = fx.accepted_report(client, bridge["id"], roster, qa_clock=FIELD_DAY)
    evaluation = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        2,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.4,
    )
    fx.finalize_scour(client, evaluation["id"], roster)
    cycle = fx.create_cycle(client, fiscal_year=2028, ranking_policy="RISK_BASED")
    submission = fx.start_submission(client, cycle["id"], submission_type="NBI_ANNUAL")
    fx.lock_cycle(client, cycle["id"])
    plans = fx.plans_for_bridge(client, bridge["id"])
    return {
        "report": report,
        "evaluation": evaluation,
        "cycle": cycle,
        "submission": submission,
        "plans": plans,
    }


def test_a_scour_critical_structure_without_an_approved_plan_blocks_the_package(
    client, roster, bridge
):
    """
    The submission's own state and its cycle's state are both correct; what refuses
    the send is the compliance flag on a structure elsewhere in the inventory.

    PRD §3.9: "The owning cycle must be in `LOCKED`, and no structure anywhere in the
    inventory may carry `poa_compliant` false; while any scour-critical structure
    lacks an approved plan of action the package cannot be sent and the attempt fails
    with `ERR_SCOUR_CRITICAL_POA_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/federal_submission_blocked_by_scour_critical_bridge_without_approved_poa
    """
    setup = _scour_critical_inventory_with_a_locked_cycle(client, roster, bridge)

    response = client.submit_federal_submission(
        setup["submission"]["id"], program_admin_headers()
    )

    validate_error(response, e.ERR_SCOUR_CRITICAL_POA_MISSING, 422)

    submission = fx.read_submission(client, setup["submission"]["id"])
    assert submission["status"] == "BUILDING"
    assert submission["submitted_at"] is None
    assert submission["submitted_by_user_id"] is None


def test_the_finalised_evaluation_created_the_obligation_it_now_enforces(
    client, roster, bridge
):
    """
    The plan of action was written by the finalisation cascade rather than by any
    client call, and it starts as a bare obligation with no approver.

    PRD §3.6: "in that case a plan of action is created with `status` `REQUIRED`, its
    `bridge_id` and `scour_evaluation_id` copied from the evaluation being finalised."
    PRD §3.6: "**Hop 4**, caused by the plan insert, sets the structure's
    `poa_compliant` to false, because a scour-critical structure with no approved plan
    is out of compliance."
    PRD §2.3: "an auto-created plan of action ... reachable only by listing their
    collection with the appropriate parent filter."

    Design: Difficulty/cross_entity_state_dependency/federal_submission_blocked_by_scour_critical_bridge_without_approved_poa
    """
    setup = _scour_critical_inventory_with_a_locked_cycle(client, roster, bridge)

    evaluation = fx.read_scour(client, setup["evaluation"]["id"])
    assert evaluation["status"] == "FINAL"
    assert evaluation["derived_scour_status"] == "SCOUR_CRITICAL"

    assert len(setup["plans"]) == 1
    plan = setup["plans"][0]
    assert plan["status"] == "REQUIRED"
    assert plan["bridge_id"] == bridge["id"]
    assert plan["scour_evaluation_id"] == setup["evaluation"]["id"]
    assert plan["approved_by_id"] is None
    assert plan["revision_count"] == 0

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "SCOUR_CRITICAL"
    assert structure["poa_compliant"] is False
    assert structure["inspection_interval_months"] == 12

    compliance = fx.read_compliance(client, bridge["id"])
    assert compliance["bridge_id"] == bridge["id"]
    assert compliance["poa_compliant"] is False
    assert compliance["routine_overdue"] is False
    assert compliance["underwater_overdue"] is False


def test_approving_the_plan_clears_the_inventory_and_lets_the_package_go(
    client, roster, bridge
):
    """
    Approving the plan restores the structure's compliance flag, and the identical
    submission request then succeeds and recomputes the statewide snapshot.

    PRD §3.6: "It moves the plan `SUBMITTED → APPROVED`, stamps `approved_at` from the
    logical clock, stores `approved_by_id`, recomputes the structure's `poa_compliant`
    to true, and increments the structure's `version` by one."
    PRD §3.9: "`inspection_compliance_pct` is 100 if there are no structures at all;
    otherwise it is 100 multiplied by the compliant count, which is the total minus
    the overdue count, divided by the total, rounded half up to two decimal places."
    PRD §3.9: "`error_count` is `poa_noncompliant_count` plus
    `open_immediate_finding_count`."

    Design: Difficulty/cross_entity_state_dependency/federal_submission_blocked_by_scour_critical_bridge_without_approved_poa
    """
    setup = _scour_critical_inventory_with_a_locked_cycle(client, roster, bridge)

    approved = fx.approved_plan(client, setup["plans"][0]["id"], roster)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_id"] == roster.district_id
    assert fx.read_bridge(client, bridge["id"])["poa_compliant"] is True

    submission = fx.send_submission(client, setup["submission"]["id"])

    assert submission["status"] == "SUBMITTED"
    a.assert_instant_equals(submission["submitted_at"], FIELD_DAY, "submitted_at")
    assert submission["total_bridge_count"] == 1
    assert submission["overdue_inspection_count"] == 0
    assert submission["inspection_compliance_pct"] == 100.00
    assert submission["poa_noncompliant_count"] == 0
    assert submission["open_immediate_finding_count"] == 0
    assert submission["error_count"] == 0
    assert fx.read_cycle(client, setup["cycle"]["id"])["status"] == "SUBMITTED"
