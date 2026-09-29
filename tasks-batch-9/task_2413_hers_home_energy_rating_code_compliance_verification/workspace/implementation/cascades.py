"""Multi-hop cascades (PRD §3.5 / §3.6 / §3.8).

Every hop of every cascade is mandatory and runs inside the same request as the
operation that triggered it — there is no deferred reconciliation anywhere.
"""

from db import db, new_row, touch
from derived import recompute_builder
from graph import (
    builder_of_rating,
    builder_of_subdivision,
    live_rating_of_home,
    members_of_sample_set,
    packages_of_rating,
    plan_models_of_subdivision,
    sample_sets_of_subdivision,
    subdivisions_of_builder,
)

OPEN_SAMPLE_SET_STATUSES = ("FORMING", "SELECTED", "TESTED")


def create_corrective_action(rating, reason):
    action = new_row(
        "CorrectiveAction",
        {
            "rating_id": rating["id"],
            "reason": reason,
            "status": "OPEN",
            "attempt_count": 0,
            "remediation_note": None,
        },
    )
    db.corrective_actions[action["id"]] = action
    return action


def step_rater_discipline(rater):
    """ACTIVE -> PROBATION -> SUSPENDED on each qualifying QA failure."""
    rater["qa_failure_count"] = rater["qa_failure_count"] + 1
    if rater["certification_status"] == "ACTIVE":
        rater["certification_status"] = "PROBATION"
    elif rater["certification_status"] == "PROBATION":
        rater["certification_status"] = "SUSPENDED"
    touch(rater)


def suspend_builder(builder):
    if builder is None:
        return
    if builder["status"] != "SAMPLING_SUSPENDED":
        builder["status"] = "SAMPLING_SUSPENDED"
        touch(builder)
    recompute_builder(builder)


def void_sampling_arrangements(builder):
    """Cascade A hops 4-5: void every live sample set of this builder."""
    for subdivision in subdivisions_of_builder(builder["id"]):
        touched_any = False
        for sample_set in sample_sets_of_subdivision(subdivision["id"]):
            if sample_set["status"] not in OPEN_SAMPLE_SET_STATUSES:
                continue
            touched_any = True
            for home in members_of_sample_set(sample_set["id"]):
                home["sample_set_id"] = None
                home["sampling_role"] = "UNASSIGNED"
                home["individual_testing_required"] = True
                touch(home)
            sample_set["status"] = "VOIDED_SAMPLING"
            sample_set["tested_home_id"] = None
            sample_set["representative_index"] = None
            sample_set["member_count"] = 0
            sample_set["tested_member_count"] = 0
            sample_set["represented_member_count"] = 0
            touch(sample_set)
        if touched_any:
            for plan in plan_models_of_subdivision(subdivision["id"]):
                if plan["status"] != "ARCHIVED":
                    plan["status"] = "ARCHIVED"
                    touch(plan)


def revoke_issued_packages(rating, reason):
    revoked = 0
    for package in packages_of_rating(rating["id"]):
        if package["status"] == "ISSUED":
            package["status"] = "REVOKED"
            package["revocation_reason"] = reason
            touch(package)
            revoked += 1
    return revoked


def cascade_qa_major_failure(rating):
    """Cascade A — a QAReview completes with FAIL_MAJOR."""
    revoke_issued_packages(rating, "QA_MAJOR_FAILURE")
    builder = builder_of_rating(rating)
    if builder is None:
        return
    recompute_builder(builder)
    if builder["revoked_package_count"] >= 1:
        suspend_builder(builder)
    if not builder["sampling_eligible"]:
        void_sampling_arrangements(builder)


def cascade_rating_void(rating):
    """Cascade C — a rating is voided."""
    revoke_issued_packages(rating, "RATING_VOID")
    for package in packages_of_rating(rating["id"]):
        if package["status"] == "DRAFT":
            package["status"] = "SUPERSEDED"
            touch(package)
    builder = builder_of_rating(rating)
    if builder is None:
        return
    recompute_builder(builder)
    if builder["revoked_package_count"] >= 1:
        suspend_builder(builder)


def cascade_sample_set_failure(sample_set):
    """Cascade B — a sample set closes FAILED_EXPANDED."""
    tested_home_id = sample_set["tested_home_id"]
    for home in members_of_sample_set(sample_set["id"]):
        if home["id"] == tested_home_id:
            continue
        home["individual_testing_required"] = True
        home["sampling_role"] = "REPRESENTED"
        touch(home)
        rating = live_rating_of_home(home["id"])
        if rating is not None:
            rating["confirmed_index"] = None
            rating["compliance_status"] = "FAILING"
            rating["compliance_path"] = "NONE"
            touch(rating)
            create_corrective_action(rating, "SAMPLE_SET_FAILURE")
    subdivision = db.subdivisions.get(sample_set["subdivision_id"])
    suspend_builder(builder_of_subdivision(subdivision))
