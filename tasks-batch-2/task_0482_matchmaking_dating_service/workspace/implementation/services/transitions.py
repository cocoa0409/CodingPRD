"""State-transition side effects and cascades (PRD §3.5, §3.8, §3.9, §3.10)."""
from db import db
from services.common import touch
from services.calculations import refund_on_cancel


def close_introduction(intro):
    """Close a SUGGESTED/ONE_SIDED/MUTUAL introduction.

    Refund credits if it was below MUTUAL; cascade-cancel any SCHEDULED date.
    Bumps the introduction's own version. (Member.version is NOT bumped by an
    introduction refund except where the caller explicitly bumps it.)
    """
    prior = intro["status"]
    was_mutual = (prior == "MUTUAL") or intro.get("_was_mutual", False)
    intro["status"] = "CLOSED"
    if prior == "MUTUAL":
        intro["_was_mutual"] = True
    intro["_was_mutual"] = was_mutual
    # credits: below-MUTUAL refund means they no longer count in any sum because
    # the credit accounting filters on status. CLOSED-below-mutual is excluded
    # from both committed and forecast sums (handled in compute via _was_mutual).
    touch(intro)
    # cascade: cancel SCHEDULED date events on this introduction
    for de in db.date_events.values():
        if de["introduction_id"] == intro["id"] and de["status"] == "SCHEDULED":
            de["status"] = "CANCELLED"
            de["outcome"] = "CANCELLED"
            touch(de)


def cancel_membership(membership):
    """Compute refund, mark CANCELLED, credit wallet."""
    refund = refund_on_cancel(membership)
    membership["refund_cents"] = refund
    membership["status"] = "CANCELLED"
    touch(membership)
    member = db.members.get(membership["member_id"])
    if member:
        member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + refund
        touch(member)
    return refund


def exit_member(member):
    """Depth-3 cascade for member exit (PRD §3.9)."""
    member["status"] = "EXITED"
    touch(member)

    # cancel ACTIVE/FROZEN membership with refund
    mid = member.get("active_membership_id")
    if mid and mid in db.memberships:
        ms = db.memberships[mid]
        if ms["status"] in ("ACTIVE", "FROZEN"):
            refund = refund_on_cancel(ms)
            ms["refund_cents"] = refund
            ms["status"] = "CANCELLED"
            touch(ms)
            member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + refund
            touch(member)

    # close open introductions where member is a party (cascade); refund below-mutual
    for intro in db.introductions.values():
        if intro["member_a_id"] != member["id"] and intro["member_b_id"] != member["id"]:
            continue
        if intro["status"] in ("SUGGESTED", "ONE_SIDED", "MUTUAL"):
            close_introduction(intro)

    # cancel SCHEDULED date events on the member's introductions (also handled by
    # close_introduction cascade, but a date could be scheduled by this member on
    # an introduction whose other party is the one being closed — covered above).
    for de in db.date_events.values():
        if de["status"] != "SCHEDULED":
            continue
        intro = db.introductions.get(de["introduction_id"])
        if not intro:
            continue
        if intro["member_a_id"] == member["id"] or intro["member_b_id"] == member["id"]:
            de["status"] = "CANCELLED"
            de["outcome"] = "CANCELLED"
            touch(de)

    # cancel BOOKED coaching sessions for the member
    for cs in db.coaching_sessions.values():
        if cs["member_id"] == member["id"] and cs["status"] == "BOOKED":
            cs["status"] = "CANCELLED"
            touch(cs)


def flag_background_cascade(member):
    """When a BackgroundCheck is FLAGGED, close open intros for the subject."""
    for intro in db.introductions.values():
        if intro["member_a_id"] != member["id"] and intro["member_b_id"] != member["id"]:
            continue
        if intro["status"] in ("SUGGESTED", "ONE_SIDED"):
            close_introduction(intro)
