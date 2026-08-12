"""RetentionCheckpoint list/get + ops epoch endpoint."""

import db
from errors import err_not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services.common import touch, recompute_pipeline
from routes.events import release_event_bookings
from flask import request


def _serialize(c):
    return dict(c)


def register(bp):
    @bp.route("/retention-checkpoints", methods=["GET"])
    def list_checkpoints():
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.retention_checkpoints.values(), key=lambda x: db.parse_dt(x["created_at"]))
        aid = request.args.get("application_id")
        kind = request.args.get("kind")
        st = request.args.get("status")
        if aid is not None:
            items = [c for c in items if c["application_id"] == aid]
        if kind is not None:
            items = [c for c in items if c["kind"] == kind]
        if st is not None:
            items = [c for c in items if c["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(c) for c in page], limit, offset, total)

    @bp.route("/retention-checkpoints/<cid>", methods=["GET"])
    def get_checkpoint(cid):
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        cp = db.retention_checkpoints.get(cid)
        if cp is None:
            err_not_found("RetentionCheckpoint not found")
        return success_object(_serialize(cp))

    @bp.route("/ops/evaluate-due", methods=["POST"])
    def evaluate_due():
        require_roles("CoalitionAdmin")
        clock_dt = db.parse_dt(db.get_clock())
        clock_date = clock_dt.date()

        checkpoints_evaluated = 0
        certifications_lapsed = 0
        events_completed = 0
        follow_ups_due = 0

        # 1. retention checkpoints: due_date ASC, created_at ASC
        pending = [c for c in db.retention_checkpoints.values() if c["status"] == "PENDING"]
        pending.sort(key=lambda c: (db.parse_date(c["due_date"]), db.parse_dt(c["created_at"])))
        for cp in pending:
            app = db.account_applications.get(cp["application_id"])
            if app is None:
                continue
            due = db.parse_date(cp["due_date"])
            window_end = db.parse_date(cp["window_end"])
            resolved = None
            if clock_date >= due:
                if app["status"] == "OPENED":
                    resolved = "EVALUATED_RETAINED"
                elif app["status"] == "CLOSED_EARLY" and db.parse_dt(app["closed_at"]).date() <= due:
                    resolved = "EVALUATED_NOT_RETAINED"
            if resolved is None and clock_date >= window_end and app["status"] == "OPENED":
                inst = db.partner_institutions.get(app["institution_id"])
                if inst is not None and inst["certification_status"] != "CERTIFIED":
                    resolved = "EXPIRED_UNCONFIRMED"
            if resolved is not None:
                cp["status"] = resolved
                cp["evaluated_at"] = db.now_iso()
                touch(cp)
                checkpoints_evaluated += 1

        # 2. lapse certifications
        for inst in db.partner_institutions.values():
            if inst["certification_status"] != "CERTIFIED":
                continue
            exp = inst.get("certification_expires_at")
            if exp is not None and clock_dt >= db.parse_dt(exp):
                inst["certification_status"] = "LAPSED"
                touch(inst)
                certifications_lapsed += 1

        # 3. complete past events
        for ev in db.account_opening_events.values():
            if ev["status"] != "SCHEDULED":
                continue
            if clock_dt > db.parse_dt(ev["ends_at"]):
                release_event_bookings(ev)
                ev["status"] = "COMPLETED"
                touch(ev)
                events_completed += 1

        # 4. due follow-ups
        for p in db.education_pairings.values():
            if p["status"] != "COMPLETED":
                continue
            due_at = p.get("follow_up_due_at")
            if due_at is not None and clock_dt >= db.parse_dt(due_at):
                p["status"] = "FOLLOW_UP_DUE"
                touch(p)
                follow_ups_due += 1

        return success_object({
            "checkpoints_evaluated": checkpoints_evaluated,
            "certifications_lapsed": certifications_lapsed,
            "events_completed": events_completed,
            "follow_ups_due": follow_ups_due,
        })
