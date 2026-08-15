"""Time-based sweeps, run atomically with every clock-set."""
import db
from db import clock, _parse_iso, _format_iso
from services.core import (
    dec, round_half_up_cents, touch, recompute_call, motion_tallies,
)


def run_sweeps():
    """Run all sweeps against the current logical clock. Returns counts dict."""
    now = clock.now()
    counts = {
        "offers_expired": 0,
        "motions_expired": 0,
        "assessments_delinquent": 0,
        "assessments_defaulted": 0,
        "physicians_suspended": 0,
        "seats_swept": 0,
    }

    # --- Offers past acceptance deadline -> EXPIRED (strict >) ---
    for o in db.buy_in_offers.values():
        if o["status"] == "OFFERED":
            deadline = _parse_iso(o["acceptance_deadline"])
            if now > deadline:
                o["status"] = "EXPIRED"
                o["updated_at"] = clock.now_iso()
                counts["offers_expired"] += 1

    # --- Motions OPEN/TABLED with clock > closes_at -> EXPIRED (strict >) ---
    for m in db.motions.values():
        if m["status"] in ("OPEN", "TABLED") and m.get("closes_at"):
            closes = _parse_iso(m["closes_at"])
            if now > closes:
                m["status"] = "EXPIRED"
                m["updated_at"] = clock.now_iso()
                counts["motions_expired"] += 1

    # --- Assessments: due -> DELINQUENT (late fee once), due+grace -> DEFAULTED ---
    for a in db.assessments.values():
        call = db.capital_calls.get(a["capital_call_id"])
        if call is None:
            continue
        due = _parse_iso(call["due_date"])
        grace_days = db.policy["delinquency_grace_days"] if db.policy else 30
        grace_deadline = due.timestamp() + grace_days * 86400
        from datetime import datetime, timezone
        grace_dt = datetime.fromtimestamp(grace_deadline, tz=timezone.utc)

        if a["status"] in ("BILLED", "PARTIAL") and now > due:
            # becomes DELINQUENT, late fee applied exactly once
            a["status"] = "DELINQUENT"
            if a["late_fee_cents"] == 0:
                pct = db.policy["late_fee_pct"] if db.policy else 0.10
                a["late_fee_cents"] = round_half_up_cents(
                    dec(a["assessed_cents"]) * dec(pct))
            a["updated_at"] = clock.now_iso()
            a["version"] += 1
            counts["assessments_delinquent"] += 1

        if a["status"] == "DELINQUENT" and now > grace_dt:
            a["status"] = "DEFAULTED"
            a["updated_at"] = clock.now_iso()
            a["version"] += 1
            counts["assessments_defaulted"] += 1
            # Cascade: physician standing -> SUSPENDED
            phys = db.physicians.get(a["physician_id"])
            if phys is not None and phys["standing"] in ("GOOD_STANDING", "PROBATION"):
                phys["standing"] = "SUSPENDED"
                touch(phys)
                counts["physicians_suspended"] += 1
            # Bubble-up: call PARTIALLY_DEFAULTED when nothing payable remains
            recompute_call(call)
            touch(call)

    # --- Board seats past current_term_end ---
    for s in db.board_seats.values():
        if s["status"] == "FILLED" and s.get("current_term_end"):
            end = _parse_iso(s["current_term_end"])
            if now >= end:
                if s.get("next_holder_physician_id"):
                    # promote successor
                    s["current_holder_physician_id"] = s["next_holder_physician_id"]
                    s["current_term_start"] = s["next_term_start"]
                    s["current_term_end"] = s["next_term_end"]
                    s["next_holder_physician_id"] = None
                    s["next_term_start"] = None
                    s["next_term_end"] = None
                else:
                    s["current_holder_physician_id"] = None
                    s["current_term_start"] = None
                    s["current_term_end"] = None
                    s["status"] = "VACANT"
                s["updated_at"] = clock.now_iso()
                s["version"] += 1
                counts["seats_swept"] += 1

    return counts
