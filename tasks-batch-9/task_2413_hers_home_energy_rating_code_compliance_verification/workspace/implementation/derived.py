"""Derived/computed field maintenance.

Every derived field is recomputed as a full aggregation (never patched blindly),
and any row whose derived values actually moved gets its updated_at refreshed and
its version incremented — even when no client addressed it directly (PRD §2.4/§2.10).
"""

from calc import qa_sampling_quota
from db import db, touch
from graph import (
    OPEN_COUNTED_CA_STATUSES,
    corrective_actions_of_builder,
    homes_of_subdivision,
    members_of_sample_set,
    packages_of_builder,
    ratings_of_builder,
    rating_of_qa_review,
    tests_of_inspection,
)
from validation import parse_datetime


def apply_derived(row, new_values):
    changed = False
    for key, value in new_values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def effective_certification_status(rater):
    """certification_status, except EXPIRED at or after cert_expires_at (PRD §2.11).

    Pure read-time derivation: moving the clock disables a person *without
    touching their row* (PRD §2.5).
    """
    expires = parse_datetime(rater["cert_expires_at"], "cert_expires_at")
    if db.logical_clock >= expires:
        return "EXPIRED"
    return rater["certification_status"]


def recompute_subdivision(subdivision):
    homes = homes_of_subdivision(subdivision["id"])
    homes_count = len(homes)
    sampled = sum(1 for h in homes if h["sample_set_id"] is not None)
    return apply_derived(
        subdivision,
        {
            "homes_count": homes_count,
            "sampled_home_count": sampled,
            "unsampled_home_count": homes_count - sampled,
        },
    )


def recompute_sample_set(sample_set):
    members = members_of_sample_set(sample_set["id"])
    return apply_derived(
        sample_set,
        {
            "member_count": len(members),
            "tested_member_count": sum(
                1 for h in members if h["sampling_role"] == "TESTED"
            ),
            "represented_member_count": sum(
                1 for h in members if h["sampling_role"] == "REPRESENTED"
            ),
        },
    )


def recompute_inspection(inspection):
    failed = sum(
        1 for t in tests_of_inspection(inspection["id"]) if t["result"] == "FAIL"
    )
    return apply_derived(inspection, {"failed_test_count": failed})


def recompute_builder(builder):
    """builder_incentive_ledger + open corrective action count + sampling_eligible."""
    packages = packages_of_builder(builder["id"])
    certified = sum(
        p["certified_amount_cents"] or 0 for p in packages if p["status"] == "ISSUED"
    )
    revoked = sum(1 for p in packages if p["status"] == "REVOKED")
    open_actions = sum(
        1
        for c in corrective_actions_of_builder(builder["id"])
        if c["status"] in OPEN_COUNTED_CA_STATUSES
    )
    eligible = (
        builder["builder_type"] == "PRODUCTION"
        and builder["status"] == "ACTIVE"
        and open_actions == 0
    )
    return apply_derived(
        builder,
        {
            "open_corrective_action_count": open_actions,
            "revoked_package_count": revoked,
            "certified_incentive_cents": certified,
            "sampling_eligible": eligible,
        },
    )


def recompute_rater(rater):
    confirmed = sum(
        1
        for r in db.ratings.values()
        if r["rater_id"] == rater["id"] and r["stage"] in ("CONFIRMED", "REGISTERED")
    )
    completed = 0
    for review in db.qa_reviews.values():
        if review["status"] != "COMPLETED":
            continue
        rating = rating_of_qa_review(review)
        if rating is not None and rating["rater_id"] == rater["id"]:
            completed += 1
    owed, hold = qa_sampling_quota(
        rater["certification_status"], confirmed, completed
    )
    return apply_derived(
        rater,
        {
            "confirmed_rating_count": confirmed,
            "qa_completed_count": completed,
            "qa_files_owed": owed,
            "registry_hold": hold,
        },
    )


def reconcile():
    """Bring every derived field in the store up to date after a mutation."""
    for inspection in list(db.inspections.values()):
        recompute_inspection(inspection)
    for sample_set in list(db.sample_sets.values()):
        recompute_sample_set(sample_set)
    for subdivision in list(db.subdivisions.values()):
        recompute_subdivision(subdivision)
    for builder in list(db.builders.values()):
        recompute_builder(builder)
    for rater in list(db.raters.values()):
        recompute_rater(rater)


# Keep an import-time reference so unused-import linters do not strip helpers.
_UNUSED = (ratings_of_builder,)
