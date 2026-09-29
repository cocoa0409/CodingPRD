"""Relationship lookups over the in-memory store."""

from db import ordered, store


def specs():
    return ordered(store.specifications.values())


def feature_sets_for(specification_id, device_type=None):
    rows = [
        fs for fs in store.feature_sets.values()
        if fs["specification_id"] == specification_id
        and (device_type is None or fs["device_type"] == device_type)
    ]
    return ordered(rows)


def feature_sets_of_spec(specification_id):
    return feature_sets_for(specification_id)


def submissions_for_spec(specification_id):
    return ordered([s for s in store.submissions.values()
                    if s["specification_id"] == specification_id])


def submissions_for_member(member_id):
    return ordered([s for s in store.submissions.values() if s["member_id"] == member_id])


def plans_for_submission(submission_id):
    return ordered([p for p in store.test_plans.values() if p["submission_id"] == submission_id])


def live_plan(submission_id):
    """The submission's single non-VOIDED test plan, if any."""
    rows = [p for p in plans_for_submission(submission_id) if p["state"] != "VOIDED"]
    return rows[-1] if rows else None


def sessions_for_plan(test_plan_id):
    return ordered([s for s in store.test_sessions.values() if s["test_plan_id"] == test_plan_id])


def sessions_for_lab(laboratory_id):
    return ordered([s for s in store.test_sessions.values() if s["laboratory_id"] == laboratory_id])


def sessions_for_submission(submission_id):
    rows = []
    for plan in plans_for_submission(submission_id):
        rows.extend(sessions_for_plan(plan["id"]))
    return ordered(rows)


def listing_for_submission(submission_id):
    rows = [l for l in store.listings.values() if l["submission_id"] == submission_id]
    return ordered(rows)[0] if rows else None


def listings_for_member(member_id):
    return ordered([l for l in store.listings.values() if l["member_id"] == member_id])


def participations_for_plugfest(plugfest_id):
    return ordered([p for p in store.participations.values() if p["plugfest_id"] == plugfest_id])


def participations_for_member(member_id):
    return ordered([p for p in store.participations.values() if p["member_id"] == member_id])


def participations_for_submission(submission_id):
    return ordered([p for p in store.participations.values()
                    if p["submission_id"] == submission_id])


def plugfests_for_host(laboratory_id):
    return ordered([p for p in store.plugfests.values()
                    if p["host_laboratory_id"] == laboratory_id])


def cases_for_listing(listing_id):
    return ordered([c for c in store.cases.values() if c["listing_id"] == listing_id])


def cases_for_member(member_id):
    rows = []
    for listing in listings_for_member(member_id):
        rows.extend(cases_for_listing(listing["id"]))
    return ordered(rows)
