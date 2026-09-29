"""Derived values, state derivation and multi-hop cascades.

Aggregate/derived figures (fund ledger, room minutes, chain counts, waitlist
figures, program compliance) are computed from the rows they aggregate, so the
declared conservation invariants hold by construction.  Stored state that drives
gating (compliance_posture, donor overall_status) is refreshed explicitly and
each refresh advances the row's version at most once per request.
"""

from decimal import Decimal

import calc
from db import by_created, db, new_entity, new_event, now, touch
from errors import ApiError
from util import add_days, dec

# --------------------------------------------------------------------------- #
# relationship helpers
# --------------------------------------------------------------------------- #


def program_of(row):
    return db.programs.get(row["program_id"])


def chain_of_segment(segment):
    return db.chains.get(segment["exchange_chain_id"])


def program_of_segment(segment):
    return db.programs.get(chain_of_segment(segment)["program_id"])


def program_of_donor(donor):
    return db.programs.get(donor["program_id"])


def program_of_review(review):
    return db.programs.get(review["program_id"])


def program_of_plan(plan):
    return program_of_review(db.reviews[plan["program_outcome_review_id"]])


def program_of_claim(claim):
    return program_of_donor(db.donors[claim["donor_candidate_id"]])


def program_of_follow_up(follow_up):
    return program_of_donor(db.donors[follow_up["donor_candidate_id"]])


def segments_of_chain(chain):
    rows = [s for s in db.segments.values() if s["exchange_chain_id"] == chain["id"]]
    return by_created(rows)


def ordered_segments(chain):
    """Non-WITHDRAWN segments, position ASC then created_at ASC."""
    rows = [s for s in segments_of_chain(chain) if s["status"] != "WITHDRAWN"]
    return sorted(rows, key=lambda s: (s["position"], s["created_at"], s["_seq"]))


def segments_of_donor(donor):
    return by_created([s for s in db.segments.values() if s["donor_candidate_id"] == donor["id"]])


def segments_of_recipient(recipient):
    return by_created(
        [s for s in db.segments.values() if s["recipient_candidate_id"] == recipient["id"]]
    )


def evaluations_of_donor(donor):
    return by_created(
        [e for e in db.evaluations.values() if e["donor_candidate_id"] == donor["id"]]
    )


def follow_ups_of_donor(donor):
    return by_created(
        [f for f in db.follow_ups.values() if f["donor_candidate_id"] == donor["id"]]
    )


def claims_of_donor(donor):
    return by_created([c for c in db.claims.values() if c["donor_candidate_id"] == donor["id"]])


def bookings_of_segment(segment):
    return by_created(
        [b for b in db.bookings.values() if b["chain_segment_id"] == segment["id"]]
    )


def bookings_of_room(room):
    return by_created([b for b in db.bookings.values() if b["operating_room_id"] == room["id"]])


def bookings_of_surgeon(staff_id):
    return by_created([b for b in db.bookings.values() if b["surgeon_staff_id"] == staff_id])


def chains_of_program(program):
    return by_created([c for c in db.chains.values() if c["program_id"] == program["id"]])


def donors_of_program(program):
    return by_created([d for d in db.donors.values() if d["program_id"] == program["id"]])


def reviews_of_program(program):
    return by_created([r for r in db.reviews.values() if r["program_id"] == program["id"]])


def plans_of_review(review):
    return by_created(
        [p for p in db.plans.values() if p["program_outcome_review_id"] == review["id"]]
    )


def follow_ups_of_program(program):
    donor_ids = set(d["id"] for d in db.donors.values() if d["program_id"] == program["id"])
    return by_created(
        [f for f in db.follow_ups.values() if f["donor_candidate_id"] in donor_ids]
    )


def claims_of_program(program):
    donor_ids = set(d["id"] for d in db.donors.values() if d["program_id"] == program["id"])
    return by_created([c for c in db.claims.values() if c["donor_candidate_id"] in donor_ids])


def waitlist_events_of(recipient):
    rows = [
        e
        for e in db.waitlist_events.values()
        if e["recipient_candidate_id"] == recipient["id"]
    ]
    return sorted(rows, key=lambda e: (e["effective_at"], e["created_at"], e["_seq"]))


# --------------------------------------------------------------------------- #
# program derived figures (donor fund ledger, compliance, breaches)
# --------------------------------------------------------------------------- #


def fund_committed_cents(program):
    total = 0
    for claim in claims_of_program(program):
        if claim["status"] == "ADJUDICATED":
            total += claim["fund_part_cents"]
    return total


def fund_remaining_cents(program):
    return program["donor_fund_pool_cents"] - fund_committed_cents(program)


def program_compliance_pct(program):
    return calc.compliance_pct(follow_ups_of_program(program), now())


def program_cit_breach_count(program):
    count = 0
    for chain in chains_of_program(program):
        for segment in segments_of_chain(chain):
            if segment["cit_breach"]:
                count += 1
    return count


# --------------------------------------------------------------------------- #
# recipient derived figures
# --------------------------------------------------------------------------- #


def recipient_active_days(recipient):
    return calc.waitlist_active_days(waitlist_events_of(recipient), now())


def recipient_priority_score(recipient):
    return calc.waitlist_priority_score(
        recipient["medical_urgency_points"],
        recipient_active_days(recipient),
        recipient["dialysis_years"],
        recipient["cpra"],
        recipient["age_years"],
    )


def recipient_decline_count(recipient):
    return len([s for s in segments_of_recipient(recipient) if s["status"] == "DECLINED"])


# --------------------------------------------------------------------------- #
# chain / room derived figures
# --------------------------------------------------------------------------- #


def chain_segment_count(chain):
    return len(ordered_segments(chain))


def chain_is_closed_loop(chain):
    ordered = ordered_segments(chain)
    if not ordered:
        return False
    first_donor = db.donors.get(ordered[0]["donor_candidate_id"])
    if first_donor is None:
        return False
    intended = first_donor.get("intended_recipient_id")
    if intended is None:
        return False
    return ordered[-1]["recipient_candidate_id"] == intended


def chain_total_planned_cit(chain):
    total = 0
    for segment in ordered_segments(chain):
        if segment["status"] in ("OFFER_SENT", "ACCEPTED", "TRANSPLANTED"):
            total += segment["planned_cit_minutes"] or 0
    return total


def chain_committed_donor_count(chain):
    if chain["status"] not in ("COMMITTED", "EXECUTING") or chain["committed_at"] is None:
        return 0
    donor_ids = set()
    for segment in segments_of_chain(chain):
        if segment["status"] == "WITHDRAWN":
            continue
        if segment["created_at"] <= chain["committed_at"]:
            donor_ids.add(segment["donor_candidate_id"])
    return len(donor_ids)


def room_reserved_minutes(room):
    total = 0
    for booking in bookings_of_room(room):
        if booking["status"] in ("ACTIVE", "COMPLETED"):
            total += booking["duration_minutes"] or 0
    return total


# --------------------------------------------------------------------------- #
# donor derived state
# --------------------------------------------------------------------------- #


def donor_screening_index(donor):
    return calc.screening_risk_index(
        donor["medical_risk_points"], donor["psychosocial_risk_points"]
    )


def donor_is_chain_committed(donor):
    for segment in segments_of_donor(donor):
        if segment["status"] == "WITHDRAWN":
            continue
        chain = chain_of_segment(segment)
        if chain is None or chain["status"] not in ("COMMITTED", "EXECUTING"):
            continue
        if chain["committed_at"] is not None and segment["created_at"] <= chain["committed_at"]:
            return True
    return False


def derive_donor_overall_status(donor):
    if donor["medical_status"] == "EXCLUDED" or donor["psychosocial_status"] == "EXCLUDED":
        return "EXCLUDED"
    if donor["advocacy_status"] == "OBJECTED":
        return "ADVOCATE_BLOCKED"
    if donor["donated_at"] is not None:
        return "DONATED"
    if donor_is_chain_committed(donor):
        return "CHAIN_COMMITTED"
    if (
        donor["advocacy_status"] == "ATTESTED"
        and donor["medical_status"] == "CLEARED"
        and donor["psychosocial_status"] == "CLEARED"
    ):
        final = donor["final_risk_index"]
        if final is not None and dec(final) >= calc.RISK_INDEX_CEILING:
            return "CONDITIONAL_APPROVED"
        return "APPROVED"
    if evaluations_of_donor(donor):
        return "EVAL_IN_PROGRESS"
    return "REFERRED"


def refresh_donor_status(donor):
    """Re-derive overall_status; version advances only when the row changes."""
    derived = derive_donor_overall_status(donor)
    if derived != donor["overall_status"]:
        donor["overall_status"] = derived
        touch(donor)
        return True
    return False


# --------------------------------------------------------------------------- #
# compliance posture (PRD 2.8)
# --------------------------------------------------------------------------- #


def has_unanswered_flagged(program):
    for review in reviews_of_program(program):
        if review["status"] != "FINALIZED" or review["flag_level"] != "FLAGGED":
            continue
        answered = any(
            plan["status"] in ("ACCEPTED", "CLOSED") for plan in plans_of_review(review)
        )
        if not answered:
            return True
    return False


def has_open_watch(program):
    for review in reviews_of_program(program):
        if review["status"] != "FINALIZED" or review["flag_level"] != "WATCH":
            continue
        closed = any(plan["status"] == "CLOSED" for plan in plans_of_review(review))
        if not closed:
            return True
    return False


def derive_posture(program):
    if has_unanswered_flagged(program):
        return "FROZEN"
    if program_compliance_pct(program) < dec(program["follow_up_compliance_threshold_pct"]):
        return "RESTRICTED"
    if has_open_watch(program):
        return "RESTRICTED"
    if program_cit_breach_count(program) >= calc.CIT_BREACH_RESTRICT_COUNT:
        return "RESTRICTED"
    return "OPEN"


def refresh_posture(program):
    """Re-derive the posture and run the entry/exit chain cascades."""
    previous = program["compliance_posture"]
    derived = derive_posture(program)
    if derived == previous:
        return False
    program["compliance_posture"] = derived
    touch(program)
    if derived == "FROZEN":
        _suspend_chains_for_freeze(program)
    elif previous == "FROZEN":
        _restore_chains_after_freeze(program)
    return True


OFFER_FIELDS_TO_CLEAR = (
    "planned_cit_minutes",
    "planned_cross_clamp_at",
    "planned_reperfusion_at",
    "planned_transport_minutes",
    "offer_sent_at",
    "offer_response_deadline_at",
)


def _suspend_chains_for_freeze(program):
    for chain in chains_of_program(program):
        if chain["status"] not in ("DRAFT", "VALIDATED"):
            continue
        chain["status"] = "SUSPENDED"
        touch(chain)
        for segment in segments_of_chain(chain):
            if segment["status"] == "OFFER_SENT":
                segment["status"] = "PLANNED"
                for field in OFFER_FIELDS_TO_CLEAR:
                    segment[field] = None
                touch(segment)
            for booking in bookings_of_segment(segment):
                if booking["status"] == "ACTIVE":
                    booking["status"] = "CANCELLED"
                    booking["cancel_reason_code"] = "POSTURE_FROZEN"
                    touch(booking)


def _restore_chains_after_freeze(program):
    for chain in chains_of_program(program):
        if chain["status"] == "SUSPENDED":
            chain["status"] = "VALIDATED"
            touch(chain)


# --------------------------------------------------------------------------- #
# chain break cascade
# --------------------------------------------------------------------------- #


def break_chain(chain, reason_code, booking_cancel_reason="CHAIN_BROKEN"):
    chain["status"] = "BROKEN"
    chain["break_reason_code"] = reason_code
    touch(chain)

    affected_donor_ids = []
    for segment in segments_of_chain(chain):
        if segment["donor_candidate_id"] not in affected_donor_ids:
            affected_donor_ids.append(segment["donor_candidate_id"])
        if segment["status"] in ("PLANNED", "OFFER_SENT", "ACCEPTED"):
            segment["status"] = "WITHDRAWN"
            touch(segment)
        for booking in bookings_of_segment(segment):
            if booking["status"] == "ACTIVE":
                booking["status"] = "CANCELLED"
                booking["cancel_reason_code"] = booking_cancel_reason
                touch(booking)

    for donor_id in affected_donor_ids:
        donor = db.donors.get(donor_id)
        if donor is not None:
            refresh_donor_status(donor)


BREAKABLE_CHAIN_STATUSES = ("DRAFT", "VALIDATED", "SUSPENDED", "COMMITTED", "EXECUTING")


def cascade_participant_withdrawal(segments, reason_code):
    """Withdraw live segments then break each of their still-live parent chains."""
    chains = []
    for segment in segments:
        if segment["status"] in ("PLANNED", "OFFER_SENT", "ACCEPTED"):
            segment["status"] = "WITHDRAWN"
            touch(segment)
            chain = chain_of_segment(segment)
            if chain is not None and chain["status"] in BREAKABLE_CHAIN_STATUSES:
                if chain["id"] not in [c["id"] for c in chains]:
                    chains.append(chain)
    for chain in chains:
        break_chain(chain, reason_code)


# --------------------------------------------------------------------------- #
# follow-up creation (donation cascade)
# --------------------------------------------------------------------------- #


def create_follow_ups(donor):
    created = []
    for interval in calc.FOLLOW_UP_INTERVALS:
        row = new_entity(
            "DonorFollowUp",
            {
                "donor_candidate_id": donor["id"],
                "interval_code": interval,
                "due_on": add_days(
                    donor["donated_at"], calc.FOLLOW_UP_DUE_OFFSET_DAYS[interval]
                ),
                "required_fields_count": calc.REQUIRED_FIELDS[interval],
                "submitted_field_count": 0,
                "completeness_pct": Decimal("0"),
                "status": "DUE",
                "submitted_at": None,
                "waiver_reason_code": None,
            },
        )
        db.follow_ups[row["id"]] = row
        created.append(row)
    return created


# --------------------------------------------------------------------------- #
# waitlist events
# --------------------------------------------------------------------------- #


def record_waitlist_event(recipient, from_status, to_status, reason_code, effective_at, actor_user_id):
    row = new_event(
        "WaitlistStatusEvent",
        {
            "recipient_candidate_id": recipient["id"],
            "from_status": from_status,
            "to_status": to_status,
            "reason_code": reason_code,
            "effective_at": effective_at,
            "actor_user_id": actor_user_id,
        },
    )
    db.waitlist_events[row["id"]] = row
    return row


# --------------------------------------------------------------------------- #
# cross-program containment (priority 15)
# --------------------------------------------------------------------------- #


def require_same_program(program_ids):
    distinct = set(pid for pid in program_ids if pid is not None)
    if len(distinct) > 1:
        raise ApiError(
            "ERR_CROSS_PROGRAM_REFERENCE",
            "referenced entities belong to different transplant programs",
        )
