"""Cascade side effects. Batch/cascade effects apply in created_at ASC order of
the affected child entities (global_invariants.ordering). Each cascaded entity
transition is a direct write to that entity -> its version increments by 1."""
from db import db
from services import calc
from services.core import bump, touch, refresh_event, sort_entities


def _event_children(ev, table):
    return sort_entities([x for x in table.values() if x.get("event_id") == ev["id"]])


def project_cancel_cascade(project):
    """Compensating cascade for project cancellation: non-terminal registrations
    -> CANCELLED (transport cleared); ACTIVE supervision -> WITHDRAWN."""
    regs = sort_entities(
        [
            r
            for r in db.registrations.values()
            if r["project_id"] == project["id"]
            and r["rsvp_status"] in ("REGISTERED", "CONFIRMED", "CHECKED_IN")
        ]
    )
    for r in regs:
        r["rsvp_status"] = "CANCELLED"
        r["transport_manifest_id"] = None
        bump(r)
    for a in sort_entities(
        [
            a
            for a in db.assignments.values()
            if a["project_id"] == project["id"] and a["status"] == "ACTIVE"
        ]
    ):
        a["status"] = "WITHDRAWN"
        bump(a)


def event_complete_cascade(ev):
    """CONFIRMED regs -> NO_SHOW (transport cleared); LOCKED projects -> COMPLETED;
    manifests {BOOKED, CONFIRMED} -> COMPLETED; meal plans ORDERED -> FULFILLED."""
    for r in sort_entities(
        [
            r
            for r in db.registrations.values()
            if r["event_id"] == ev["id"] and r["rsvp_status"] == "CONFIRMED"
        ]
    ):
        r["rsvp_status"] = "NO_SHOW"
        r["transport_manifest_id"] = None
        bump(r)
    for p in sort_entities(
        [
            p
            for p in db.projects.values()
            if p["event_id"] == ev["id"] and p["status"] == "LOCKED"
        ]
    ):
        p["status"] = "COMPLETED"
        bump(p)
    for m in sort_entities(
        [
            m
            for m in db.manifests.values()
            if m["event_id"] == ev["id"] and m["status"] in ("BOOKED", "CONFIRMED")
        ]
    ):
        m["status"] = "COMPLETED"
        bump(m)
    for mp in _event_children(ev, db.meal_plans):
        if mp["status"] == "ORDERED":
            mp["status"] = "FULFILLED"
            bump(mp)
    refresh_event(ev)


def event_cancel_cascade(ev):
    """Full compensating unwind for event cancellation."""
    for r in sort_entities(
        [
            r
            for r in db.registrations.values()
            if r["event_id"] == ev["id"] and r["rsvp_status"] in ("REGISTERED", "CONFIRMED")
        ]
    ):
        r["rsvp_status"] = "CANCELLED"
        r["transport_manifest_id"] = None
        bump(r)
    for o in _event_children(ev, db.orders):
        if o["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            o["status"] = "CANCELLED"
            bump(o)
    for m in _event_children(ev, db.manifests):
        if m["status"] in ("BOOKED", "CONFIRMED"):
            m["status"] = "CANCELLED"
            bump(m)
            for r in db.registrations.values():
                if r["transport_manifest_id"] == m["id"]:
                    r["transport_manifest_id"] = None
                    touch(r)
    for mp in _event_children(ev, db.meal_plans):
        if mp["status"] in ("DRAFT", "ORDERED"):
            mp["status"] = "CANCELLED"
            bump(mp)
    for sp in _event_children(ev, db.sponsorships):
        if sp["status"] in ("PLEDGED", "COMMITTED"):
            sp["status"] = "WITHDRAWN"
            bump(sp)
    for p in sort_entities(
        [
            p
            for p in db.projects.values()
            if p["event_id"] == ev["id"] and p["status"] in ("MATCHED", "LOCKED")
        ]
    ):
        p["status"] = "VETTED"
        p["event_id"] = None
        bump(p)
        for a in sort_entities(
            [
                a
                for a in db.assignments.values()
                if a["project_id"] == p["id"] and a["status"] == "ACTIVE"
            ]
        ):
            a["status"] = "WITHDRAWN"
            bump(a)
    refresh_event(ev)


def waiver_version_bump_cascade(ev, new_version):
    """Void stale SIGNED/VERIFIED waivers; demote affected CONFIRMED registrations."""
    affected = sort_entities(
        [
            r
            for r in db.registrations.values()
            if r["event_id"] == ev["id"]
            and r["waiver_status"] in ("WAIVER_SIGNED", "WAIVER_VERIFIED")
            and r["waiver_signed_version"] is not None
            and r["waiver_signed_version"] < new_version
        ]
    )
    for r in affected:
        r["waiver_status"] = "WAIVER_VOIDED"
        demoted = False
        if r["rsvp_status"] == "CONFIRMED":
            r["rsvp_status"] = "REGISTERED"
            demoted = True
        bump(r)
        if demoted:
            project = db.projects.get(r["project_id"])
            if project is not None:
                from services.core import maybe_demote_project

                maybe_demote_project(project)
                touch(project)
    refresh_event(ev)


def refresh_partner_reputation(partner):
    """Auto suspend/reinstate with hysteresis band; suspension cancels
    PROPOSED/VETTED projects (MATCHED/LOCKED/COMPLETED untouched)."""
    score, survey_count = calc.partner_reputation(partner)
    if (
        partner["status"] == "ACTIVE"
        and survey_count >= calc.SUSPEND_MIN_SURVEYS
        and score is not None
    ):
        from decimal import Decimal

        if Decimal(str(score)) < calc.SUSPEND_RATING_THRESHOLD:
            partner["status"] = "SUSPENDED"
            bump(partner)
            for p in sort_entities(
                [
                    p
                    for p in db.projects.values()
                    if p["nonprofit_id"] == partner["id"]
                    and p["status"] in ("PROPOSED", "VETTED")
                ]
            ):
                p["status"] = "CANCELLED"
                bump(p)
                project_cancel_cascade(p)
            return
    if partner["status"] == "SUSPENDED" and score is not None:
        from decimal import Decimal

        if Decimal(str(score)) >= calc.REINSTATE_RATING_THRESHOLD:
            partner["status"] = "ACTIVE"
            bump(partner)
