"""Traversal helpers over the in-memory object graph."""

from core.store import db, find, newest


def participant(participant_id):
    return db.participants.get(participant_id)


def committee(committee_id):
    return db.committees.get(committee_id)


def seats_of(committee_row):
    return find("memberships", committee_id=committee_row["id"])


def voting_seats(committee_row):
    return [s for s in seats_of(committee_row)
            if s["status"] == "ACTIVE" and s["voting_rights"] is True]


def roster_seats(committee_row):
    """Roster basis: ACTIVE or SUSPENDED seats regardless of voting_rights."""
    return [s for s in seats_of(committee_row) if s["status"] in ("ACTIVE", "SUSPENDED")]


def work_items_of_committee(committee_row):
    return find("work_items", sponsoring_committee_id=committee_row["id"])


def sponsoring_committee(work_item):
    if work_item is None or work_item.get("sponsoring_committee_id") is None:
        return None
    return db.committees.get(work_item["sponsoring_committee_id"])


def drafts_of(work_item):
    return find("drafts", work_item_id=work_item["id"])


def work_item_of_draft(draft):
    return db.work_items.get(draft["work_item_id"])


def ballots_of_draft(draft):
    return find("ballots", draft_id=draft["id"])


def ballots_of_committee(committee_row):
    return find("ballots", committee_id=committee_row["id"])


def ballots_of_work_item(work_item):
    out = []
    for draft in drafts_of(work_item):
        out.extend(ballots_of_draft(draft))
    out.sort(key=lambda r: r["_seq"])
    return out


def votes_of_ballot(ballot):
    return find("votes", ballot_id=ballot["id"])


def votes_of_draft(draft):
    out = []
    for ballot in ballots_of_draft(draft):
        out.extend(votes_of_ballot(ballot))
    out.sort(key=lambda r: r["_seq"])
    return out


def votes_of_work_item(work_item):
    out = []
    for ballot in ballots_of_work_item(work_item):
        out.extend(votes_of_ballot(ballot))
    out.sort(key=lambda r: r["_seq"])
    return out


def ballot_of_vote(vote):
    return db.ballots.get(vote["ballot_id"])


def draft_of_ballot(ballot):
    return db.drafts.get(ballot["draft_id"])


def reviews_of_draft(draft):
    return find("public_reviews", draft_id=draft["id"])


def reviews_of_work_item(work_item):
    out = []
    for draft in drafts_of(work_item):
        out.extend(reviews_of_draft(draft))
    out.sort(key=lambda r: r["_seq"])
    return out


def latest_review_of_draft(draft):
    """The most recently created public review recorded against the draft."""
    return newest(reviews_of_draft(draft))


def comments_of_review(review):
    return find("comments", public_review_id=review["id"])


def comment_of_vote(vote):
    return newest(find("comments", source_vote_id=vote["id"]))


def review_of_comment(comment):
    if comment.get("public_review_id") is None:
        return None
    return db.public_reviews.get(comment["public_review_id"])


def draft_of_comment(comment):
    if comment.get("draft_id") is not None:
        return db.drafts.get(comment["draft_id"])
    review = review_of_comment(comment)
    if review is not None:
        return db.drafts.get(review["draft_id"])
    return None


def latest_draft_of(work_item):
    """The work item's latest revision, by highest revision_number."""
    best = None
    for draft in drafts_of(work_item):
        if best is None or draft["revision_number"] > best["revision_number"] or (
                draft["revision_number"] == best["revision_number"]
                and draft["_seq"] > best["_seq"]):
            best = draft
    return best


def disclosures_of(work_item):
    return find("patent_disclosures", work_item_id=work_item["id"])


def appeals_of(work_item):
    return find("appeals", work_item_id=work_item["id"])


def maintenance_of(work_item):
    return find("maintenance_items", work_item_id=work_item["id"])


def committee_governing_draft(draft):
    """The committee whose chair governs actions on this draft's work item."""
    work_item = work_item_of_draft(draft)
    return sponsoring_committee(work_item)
