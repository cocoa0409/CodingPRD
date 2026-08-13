"""Test-driving endpoints: logical clock + maintenance sweep."""
from datetime import timedelta

from flask import Blueprint

import db
import services
from auth import require
from envelope import ok
from util import body_json, req_datetime, fmt_iso, CLOCK

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("CenterAdmin")
    data = body_json()
    dt = req_datetime(data, "to_iso8601")
    CLOCK.set(dt)
    return ok({"current_utc": fmt_iso(CLOCK.now())})


@bp.route("/_sweeps/run", methods=["POST"])
def run_sweeps():
    require("CenterAdmin")
    now = db.now()

    # 1. expire SENT referrals past sent_at + ttl_days
    referrals_expired = 0
    for ref in db.all_of("referrals"):
        if ref["status"] == "SENT" and ref.get("sent_at") is not None:
            if ref["sent_at"] + timedelta(days=ref["ttl_days"]) <= now:
                ref["status"] = "EXPIRED"
                db.touch(ref)
                org = db.get("organizations", ref["organization_id"])
                if org is not None:
                    services.org_slot_delta(org, -1)
                referrals_expired += 1

    # 2. expire GRANTED consents whose expires_at has passed
    consents_expired = 0
    for consent in db.all_of("consents"):
        if (consent["status"] == "GRANTED"
                and consent.get("expires_at") is not None
                and consent["expires_at"] <= now):
            consent["status"] = "EXPIRED"
            db.touch(consent)
            consents_expired += 1
            services.recompute_reportable(consent["client_id"])
            if consent["scope"] == "REFERRAL_SHARE":
                services.referral_share_cascade(consent["client_id"])

    # 3. CONFIRMED appointments whose end passed -> NO_SHOW
    appointments_no_show = 0
    for appt in db.all_of("appointments"):
        if appt["status"] == "CONFIRMED" and appt["ends_at"] <= now:
            appt["status"] = "NO_SHOW"
            db.touch(appt)
            appointments_no_show += 1

    # 4. SCHEDULED sessions whose end passed -> HELD
    sessions_held = 0
    for sess in db.all_of("sessions"):
        if sess["status"] == "SCHEDULED" and sess["ends_at"] <= now:
            sess["status"] = "HELD"
            db.touch(sess)
            sessions_held += 1

    # 5. HELD sessions with no unmarked ENROLLED enrollment -> RECONCILED
    sessions_reconciled = 0
    for sess in db.all_of("sessions"):
        if sess["status"] != "HELD":
            continue
        unmarked = any(w for w in db.all_of("wk_enrollments")
                       if w["session_id"] == sess["id"]
                       and w["status"] == "ENROLLED")
        if not unmarked:
            sess["status"] = "RECONCILED"
            db.touch(sess)
            sessions_reconciled += 1

    return ok({
        "referrals_expired": referrals_expired,
        "consents_expired": consents_expired,
        "appointments_marked_no_show": appointments_no_show,
        "sessions_marked_held": sessions_held,
        "sessions_reconciled": sessions_reconciled,
    })
