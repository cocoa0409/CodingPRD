"""Cross-aggregate helpers: mirrored fields, derived counters and the two
multi-hop cascades.  Route modules call into here so that a cascade behaves
identically no matter which endpoint set it off.
"""
from core import (ApiError, db, invalid, new_record, now_date, now_dt,
                  sort_records, touch)
import calc


# ===================================================================== lookups
def all_of(table):
    return sort_records(list(table.values()))


def children(table, field, value):
    return sort_records([r for r in table.values() if r.get(field) == value])


def packets_of(meeting_id):
    return children(db.packets, "meeting_id", meeting_id)


def items_of(packet_id):
    return children(db.agenda_items, "packet_id", packet_id)


def motions_of(meeting_id):
    return children(db.motions, "meeting_id", meeting_id)


def minutes_of(meeting_id):
    return children(db.minutes, "meeting_id", meeting_id)


def submissions_of(cycle_id):
    return children(db.submissions, "cycle_id", cycle_id)


def cycles_of(title_id):
    return children(db.cycles, "code_title_id", title_id)


def notices_of_meeting(meeting_id):
    return children(db.notices, "meeting_id", meeting_id)


def notices_of_instrument(instrument_id):
    return children(db.notices, "instrument_id", instrument_id)


# ============================================== agenda packet / meeting notice
def packet_derived(packet):
    """item_count and contains_public_hearing are derived from the items."""
    items = items_of(packet["id"])
    packet["item_count"] = len(items)
    packet["contains_public_hearing"] = any(
        item["item_type"] == "PUBLIC_HEARING" for item in items)
    return packet


def recompute_packet_notice(packet, meeting):
    """Recomputes required_notice_hours / notice_deadline_at on the packet."""
    hours, deadline = calc.meeting_notice_requirement(
        meeting, packet["contains_public_hearing"], packet["late_addendum"])
    packet["required_notice_hours"] = hours
    packet["notice_deadline_at"] = deadline
    return hours, deadline


def posted_packet_of(meeting_id):
    for packet in packets_of(meeting_id):
        if packet["status"] == "POSTED":
            return packet
    return None


def mirror_meeting_notice(meeting):
    """PRD 2.10: the meeting mirrors whichever packet is currently POSTED.

    Where no such packet exists the first two read null and notice_compliant
    reads false.  Always recomputed, never incrementally patched.
    """
    packet = posted_packet_of(meeting["id"])
    if packet is None:
        new = (None, None, False)
    else:
        new = (packet["posted_at"], packet["required_notice_hours"],
               packet["notice_compliant"])
    old = (meeting["notice_posted_at"], meeting["required_notice_hours"],
           meeting["notice_compliant"])
    meeting["notice_posted_at"] = new[0]
    meeting["required_notice_hours"] = new[1]
    meeting["notice_compliant"] = new[2]
    if old != new:
        touch(meeting)
    return meeting


# ==================================================== publication notices
def new_notice(notice_type, instrument=None, meeting=None):
    notice = new_record()
    notice.update({
        "notice_type": notice_type,
        "instrument_id": instrument["id"] if instrument is not None else None,
        "meeting_id": meeting["id"] if meeting is not None else None,
        "status": "DRAFT",
        "required_publication_count": None,
        "publication_deadline_on": None,
        "newspaper_name": None,
        "column_inches": None,
        "publication_dates": None,
        "gross_cost_cents": None,
        "discount_pct": None,
        "invoice_total_cents": None,
        "publication_completed_on": None,
    })
    count, deadline = calc.publication_requirement(notice_type, instrument, meeting)
    notice["required_publication_count"] = count
    notice["publication_deadline_on"] = deadline
    db.notices[notice["id"]] = notice
    return notice


def create_instrument_notice(instrument):
    """Hop 4 of officialization, and the replacement raised by an override."""
    return new_notice(calc.instrument_notice_type(instrument), instrument=instrument)


def void_notices(notices):
    """VOID keeps publication_dates and the whole invoice for audit."""
    for notice in notices:
        if notice["status"] in ("DRAFT", "ORDERED"):
            notice["status"] = "VOID"
            touch(notice)


def void_meeting_agenda_notices(meeting_id):
    void_notices([n for n in notices_of_meeting(meeting_id)
                  if n["notice_type"] == "MEETING_AGENDA"])


def void_instrument_notices(instrument_id):
    void_notices(notices_of_instrument(instrument_id))


# =========================================================== numbering series
def mint_check(series):
    """Raised before anything is committed, so a failed mint is atomic."""
    if series is None:
        return
    if series["status"] != "OPEN":
        raise ApiError("ERR_NUMBER_SERIES_CLOSED", 409)
    if series["next_sequence"] > calc.MAX_SEQUENCE:
        raise ApiError("ERR_NUMBER_SERIES_EXHAUSTED", 422)


def mint_number(series):
    sequence = series["next_sequence"]
    number = "%s-%d-%03d" % (series["prefix"], series["series_year"], sequence)
    series["next_sequence"] = sequence + 1
    series["minted_count"] = series["minted_count"] + 1
    touch(series)
    return number


# ==================================================== instrument effective date
def accepted_cycle_of(instrument):
    """The SupplementCycle carrying this instrument's ACCEPTED submission."""
    best = None
    for sub in sort_records(list(db.submissions.values())):
        if sub["instrument_id"] != instrument["id"] or sub["status"] != "ACCEPTED":
            continue
        cycle = db.cycles.get(sub["cycle_id"])
        if cycle is not None and cycle["status"] == "CERTIFIED":
            best = cycle
    return best


def apply_effective_date(instrument):
    """Writes effective_date_basis and effective_date from the current inputs."""
    basis = calc.effective_date_basis_for(instrument)
    certified_on = None
    if basis == "SUPPLEMENT_CERTIFIED":
        cycle = accepted_cycle_of(instrument)
        certified_on = cycle["certified_on"] if cycle is not None else None
    instrument["effective_date_basis"] = basis
    instrument["effective_date"] = calc.instrument_effective_date(
        instrument, basis, certified_on)
    touch(instrument)
    return basis, instrument["effective_date"]


# ============================================ supplement cycle derived counters
def recompute_cycle_counters(cycle):
    subs = submissions_of(cycle["id"])
    live = [s for s in subs if s["status"] != "WITHDRAWN"]
    held = [s for s in subs if s["status"] == "CONFLICT_HELD"]
    new = (
        len(live),
        len([s for s in live if s["origin"] == "CLIENT"]),
        len(held) // 2,
    )
    old = (cycle["submission_count"], cycle["client_submission_count"],
           cycle["conflict_count"])
    cycle["submission_count"] = new[0]
    cycle["client_submission_count"] = new[1]
    cycle["conflict_count"] = new[2]
    if old != new:
        touch(cycle)
    return cycle


def supersede_target(cycle_id, instrument_id, code_section_ref, exclude_id=None):
    """A PENDING row of the SAME instrument on the SAME section is a draft."""
    for sub in submissions_of(cycle_id):
        if sub["id"] == exclude_id:
            continue
        if (sub["status"] == "PENDING"
                and sub["instrument_id"] == instrument_id
                and sub["code_section_ref"] == code_section_ref):
            return sub
    return None


def conflict_target(cycle_id, instrument_id, code_section_ref, exclude_id=None):
    """A PENDING or IN_REVIEW row of a DIFFERENT instrument on the same section."""
    for sub in submissions_of(cycle_id):
        if sub["id"] == exclude_id:
            continue
        if (sub["status"] in ("PENDING", "IN_REVIEW")
                and sub["code_section_ref"] == code_section_ref
                and sub["instrument_id"] != instrument_id):
            return sub
    return None


def new_submission(cycle, instrument, code_section_ref, action, origin):
    sub = new_record()
    sub.update({
        "cycle_id": cycle["id"],
        "instrument_id": instrument["id"],
        "code_section_ref": code_section_ref,
        "action": action,
        "origin": origin,
        "status": "PENDING",
        "conflict_with_submission_id": None,
        "resolution_basis": None,
        "resolved_by_user_id": None,
    })
    db.submissions[sub["id"]] = sub
    if origin == "CLIENT":
        victim = supersede_target(cycle["id"], instrument["id"], code_section_ref,
                                  exclude_id=sub["id"])
        if victim is not None:
            victim["status"] = "WITHDRAWN"
            touch(victim)
    partner = conflict_target(cycle["id"], instrument["id"], code_section_ref,
                              exclude_id=sub["id"])
    if partner is not None:
        sub["status"] = "CONFLICT_HELD"
        sub["conflict_with_submission_id"] = partner["id"]
        partner["status"] = "CONFLICT_HELD"
        partner["conflict_with_submission_id"] = sub["id"]
        touch(partner)
    recompute_cycle_counters(cycle)
    return sub


def select_cascade_cycle(instrument):
    """Earliest window_close_on wins, tie-broken by earliest created_at."""
    today = now_date()
    eligible = []
    for cycle in cycles_of(instrument.get("code_title_id")):
        if cycle["status"] != "OPEN":
            continue
        if cycle["window_open_on"] <= today <= cycle["window_close_on"]:
            eligible.append(cycle)
    if not eligible:
        raise ApiError("ERR_NO_OPEN_SUPPLEMENT_CYCLE", 409)
    eligible.sort(key=lambda c: (c["window_close_on"], c["created_at"], c["_seq"]))
    return eligible[0]


# ===================================== cascade: minutes approval officialization
def _mint_precheck(instruments):
    """Simulates the sequential mints so a doomed cascade commits nothing."""
    consumed = {}
    for instrument in instruments:
        series = db.number_series.get(instrument["number_series_id"])
        if series is None:
            continue
        if series["status"] != "OPEN":
            raise ApiError("ERR_NUMBER_SERIES_CLOSED", 409)
        offset = consumed.get(series["id"], 0)
        if series["next_sequence"] + offset > calc.MAX_SEQUENCE:
            raise ApiError("ERR_NUMBER_SERIES_EXHAUSTED", 422)
        consumed[series["id"]] = offset + 1


def minutes_approval_cascade(minutes):
    """Hops 1-4 of PRD 3.4.  Nothing is written until the mints are known good."""
    meeting_id = minutes["meeting_id"]
    sitting_motions = motions_of(meeting_id)

    # hop 3 candidates, discovered before any write so the mint can be pre-checked
    candidates = []
    for motion in sitting_motions:
        if motion["motion_type"] not in ("ORDINANCE_ADOPTION", "RESOLUTION_ADOPTION"):
            continue
        if motion["outcome"] not in calc.PASSING_OUTCOMES:
            continue
        instrument = db.instruments.get(motion["instrument_id"])
        if instrument is not None and instrument["status"] == "ADOPTED_UNOFFICIAL":
            candidates.append(instrument)
    _mint_precheck(candidates)

    # hop 1
    minutes["status"] = "APPROVED"
    minutes["approved_on"] = now_date()
    touch(minutes)

    # hop 2 -- the WHOLE record of that sitting becomes official at once
    for motion in sitting_motions:
        if not motion["result_official"]:
            motion["result_official"] = True
            touch(motion)

    # hop 3 and hop 4
    for instrument in candidates:
        series = db.number_series.get(instrument["number_series_id"])
        instrument["status"] = "ADOPTED"
        instrument["adoption_date"] = now_date()
        if series is not None:
            instrument["assigned_number"] = mint_number(series)
        touch(instrument)
        if instrument["requires_publication"]:
            create_instrument_notice(instrument)
        else:
            instrument["effective_date_basis"] = "ADOPTION_IMMEDIATE"
            instrument["effective_date"] = instrument["adoption_date"]
            instrument["status"] = "EFFECTIVE"
            touch(instrument)
    return minutes


# ================================================ public records request ledger
def recompute_ledger(request):
    calc.records_request_fee_ledger(request)
    return request


def closure_dates_for(series_id):
    return [r["closed_on"] for r in db.requests.values()
            if r.get("target_series_id") == series_id
            and r["fulfillment_status"] == "CLOSED"
            and r.get("closed_on") is not None]


def recompute_series_eligibility(series):
    value = calc.destruction_eligibility_date(series, closure_dates_for(series["id"]))
    if series["eligible_through_on"] != value:
        series["eligible_through_on"] = value
        touch(series)
    return value


def blocking_request_for(series_id):
    """The earliest-created request on this series outside CLOSED and WITHDRAWN."""
    open_requests = [r for r in db.requests.values()
                     if r.get("target_series_id") == series_id
                     and r["fulfillment_status"] not in ("CLOSED", "WITHDRAWN")]
    if not open_requests:
        return None
    return sort_records(open_requests)[0]["id"]


def cascade_candidates(minutes):
    """Instruments hop 3 will officialize, in motion creation order."""
    candidates = []
    for motion in motions_of(minutes["meeting_id"]):
        if motion["motion_type"] not in ("ORDINANCE_ADOPTION", "RESOLUTION_ADOPTION"):
            continue
        if motion["outcome"] not in calc.PASSING_OUTCOMES:
            continue
        instrument = db.instruments.get(motion["instrument_id"])
        if instrument is not None and instrument["status"] == "ADOPTED_UNOFFICIAL":
            candidates.append(instrument)
    return candidates


def precheck_minutes_cascade(minutes):
    """Runs the mint feasibility check before the tally writes anything."""
    _mint_precheck(cascade_candidates(minutes))
