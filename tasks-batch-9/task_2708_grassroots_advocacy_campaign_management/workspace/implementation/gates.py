"""Rejection-ladder gates (PRD 2.8).  Each helper implements one rung so the
route handlers can call them in strict numeric order.
"""

from datetime import timedelta

from flask import g

import calc
from common import R_PARTNER, R_SUPPORTER, db, err, whole_minute


# rung 6 -------------------------------------------------------------------
def gate_owner_supporter(supporter_id):
    if g.role == R_SUPPORTER and g.user_id != supporter_id:
        err("ERR_NOT_RESOURCE_OWNER", "supporter may only act on their own rows")


def gate_owner_partner(partner_id):
    if g.role == R_PARTNER and g.user_id != partner_id:
        err("ERR_NOT_RESOURCE_OWNER", "delegate may only act on its own partner")


# rung 7 -------------------------------------------------------------------
def gate_segment_version(segment, expected):
    if expected is not None and int(expected) != int(segment["version"]):
        err(
            "ERR_STALE_SEGMENT_VERSION",
            "expected_segment_version %s does not match %s"
            % (expected, segment["version"]),
        )


def gate_variant_version(variant, expected):
    if expected is not None and int(expected) != int(variant["version"]):
        err(
            "ERR_STALE_VARIANT_VERSION",
            "expected_variant_version %s does not match %s"
            % (expected, variant["version"]),
        )


# rung 8 -------------------------------------------------------------------
def gate_campaign_active(campaign, allow_draft=False):
    status = campaign["status"]
    if status == "ACTIVE":
        return
    if allow_draft and status == "DRAFT":
        return
    err("ERR_CAMPAIGN_NOT_ACTIVE", "campaign status is %s" % status)


# rung 9 -------------------------------------------------------------------
def gate_not_frozen(campaign):
    if campaign["posture"] == "FROZEN":
        err("ERR_CAMPAIGN_FROZEN", "campaign posture is FROZEN")


# rung 10 ------------------------------------------------------------------
def gate_not_restricted(campaign, channel):
    if campaign["posture"] == "RESTRICTED" and channel in ("SMS", "PHONE"):
        err(
            "ERR_CAMPAIGN_RESTRICTED",
            "campaign posture is RESTRICTED; only EMAIL waves remain open",
        )


# rung 11 ------------------------------------------------------------------
def gate_state(current, allowed):
    if current not in allowed:
        err("ERR_INVALID_STATE_TRANSITION", "transition not declared from %s" % current)


# rung 12 ------------------------------------------------------------------
def gate_sod(other_user_id):
    if other_user_id is not None and g.user_id == other_user_id:
        err("ERR_SEGREGATION_OF_DUTIES", "the same operator may not perform both steps")


# rung 13 ------------------------------------------------------------------
def gate_contactable(sup, channel):
    if sup["suppressed"]:
        err("ERR_SUPPORTER_SUPPRESSED", "supporter has revoked every channel")
    if calc.consent_state(sup, channel) != "GRANTED":
        err("ERR_CONSENT_MISSING", "supporter has no GRANTED consent on %s" % channel)


def gate_contactable_any(sup):
    if sup["suppressed"]:
        err("ERR_SUPPORTER_SUPPRESSED", "supporter has revoked every channel")
    if not any(calc.consent_state(sup, c) == "GRANTED" for c in calc.CHANNELS):
        err("ERR_CONSENT_MISSING", "supporter has no GRANTED channel")


# rung 14 ------------------------------------------------------------------
LAWFUL_BASES = ("EXPRESS_WRITTEN", "OPT_IN_FORM", "EVENT_CARD", "VERBAL_RECORDED")


def gate_lawful_basis(action, lawful_basis):
    if action == "GRANT":
        if lawful_basis is None or lawful_basis not in LAWFUL_BASES:
            err("ERR_LAWFUL_BASIS_INVALID", "a GRANT requires a valid lawful_basis")
    else:
        if lawful_basis is not None:
            err("ERR_LAWFUL_BASIS_INVALID", "a REVOKE must not carry a lawful_basis")


# rung 15 / 16 -------------------------------------------------------------
def gate_window_sane(start, end):
    if not (start < end):
        err("ERR_INVALID_WINDOW", "window_start must be strictly before window_end")
    if not whole_minute(start) or not whole_minute(end):
        err("ERR_INVALID_WINDOW", "window bounds must be aligned to a whole minute")


def gate_window_inside_campaign(campaign, start, end):
    if start < campaign["start_date"] or end > campaign["end_date"]:
        err(
            "ERR_WINDOW_OUTSIDE_CAMPAIGN",
            "window must fall inside the campaign span",
        )


# rung 17 ------------------------------------------------------------------
def gate_blackout(campaign_id, start, end):
    for milestone in calc.milestones_of(campaign_id):
        if milestone["kind"] != "RECESS":
            continue
        if calc.windows_overlap_closed_halfopen(
            start, end, milestone["window_start"], milestone["window_end"]
        ):
            err(
                "ERR_BLACKOUT_WINDOW",
                "send window intersects a RECESS milestone window",
            )


# rung 18 ------------------------------------------------------------------
BUFFER = timedelta(minutes=calc.MEETING_TRAVEL_BUFFER_MINUTES)


def gate_meeting_conflict(legislator_id, start, end):
    for meeting in db.meetings.values():
        if meeting["legislator_id"] != legislator_id:
            continue
        if meeting["status"] not in ("REQUESTED", "CONFIRMED", "HELD"):
            continue
        buffered_start = meeting["window_start"] - BUFFER
        buffered_end = meeting["window_end"] + BUFFER
        # both intervals are half-open
        if start < buffered_end and end > buffered_start:
            err(
                "ERR_MEETING_WINDOW_CONFLICT",
                "meeting collides with an existing interval once the travel buffer applies",
            )


# rung 19 ------------------------------------------------------------------
def gate_channel_saturation(campaign_id, channel, start, end):
    overlapping = 0
    for activation in calc.activations_of(campaign_id):
        if activation["channel"] != channel:
            continue
        if activation["delivery_state"] not in ("SCHEDULED", "SENDING"):
            continue
        # both send windows are closed intervals
        if start <= activation["window_end"] and end >= activation["window_start"]:
            overlapping += 1
    if overlapping >= calc.CHANNEL_WINDOW_MAX_OVERLAP:
        err(
            "ERR_CHANNEL_WINDOW_SATURATED",
            "two overlapping waves already hold this campaign-and-channel window",
        )
