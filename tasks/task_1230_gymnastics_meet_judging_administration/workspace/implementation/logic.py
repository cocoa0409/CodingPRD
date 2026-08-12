"""Business logic: calculations, cascades, and clock-driven system transitions."""
import math
from datetime import timedelta
from decimal import Decimal

from common import (CATEGORY_INDEX, DB, PER_ATHLETE_SECONDS, RATING_TIERS,
                    BAND_TIERS, athlete_count, meet_of_entry, meet_of_score,
                    meet_of_session, new_entity, now, q3, session_gyms,
                    sort_items, touch)

OPEN_INQUIRY_STATES = ("FILED", "UNDER_REVIEW")
SCORE_CLOSED_STATES = ("FINAL", "VOID")


# ----------------------------------------------------------------------------
# Score helpers
# ----------------------------------------------------------------------------

def compute_provisional(difficulty, execution, deduction):
    total = q3(difficulty + execution - deduction)
    if total < 0:
        total = Decimal("0.000")
    return total


def finalize_score(score):
    """PUBLISHED -> FINAL via inquiry-window expiry."""
    score["score_state"] = "FINAL"
    score["final_total"] = score["provisional_total"]
    score["finalized_at"] = now()
    touch(score)


def expire_inquiry(inq):
    """FILED -> EXPIRED; linked score returns UNDER_INQUIRY -> PUBLISHED."""
    inq["inquiry_state"] = "EXPIRED"
    inq["resolved_at"] = now()
    touch(inq)
    score = DB.scores.get(inq["score_id"])
    if score is not None and score["score_state"] == "UNDER_INQUIRY":
        score["score_state"] = "PUBLISHED"
        score["final_total"] = score["provisional_total"]
        touch(score)


def has_open_inquiry(score_id):
    for iq in DB.inquiries.values():
        if iq["score_id"] == score_id and iq["inquiry_state"] in OPEN_INQUIRY_STATES:
            return True
    return False


# ----------------------------------------------------------------------------
# Panel helpers
# ----------------------------------------------------------------------------

def confirmed_count(panel_id):
    n = 0
    for a in DB.assignments.values():
        if a["judge_panel_id"] == panel_id and a["assignment_state"] == "CONFIRMED":
            n += 1
    return n


def recompute_panel(panel):
    if panel["panel_state"] in ("FORMING", "FULL"):
        new_state = ("FULL" if confirmed_count(panel["id"]) >= panel["required_judge_count"]
                     else "FORMING")
        if new_state != panel["panel_state"]:
            panel["panel_state"] = new_state
            touch(panel)


def compute_conflict(assignment):
    if assignment["assignment_state"] == "RECUSED":
        return False
    judge = DB.judges.get(assignment["judge_id"])
    panel = DB.panels.get(assignment["judge_panel_id"])
    if judge is None or panel is None:
        return False
    return judge["affiliated_gym"] in session_gyms(panel["session_id"])


def recompute_conflicts_for_session(session_id):
    for panel in DB.panels.values():
        if panel["session_id"] != session_id:
            continue
        for a in DB.assignments.values():
            if a["judge_panel_id"] != panel["id"]:
                continue
            new_flag = compute_conflict(a)
            if new_flag != a["conflict_flag"]:
                a["conflict_flag"] = new_flag
                touch(a)


# ----------------------------------------------------------------------------
# All-around / qualification
# ----------------------------------------------------------------------------

def compute_all_around(entry):
    aa = Decimal("0.000")
    for apparatus in ("VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"):
        for s in DB.scores.values():
            if (s["athlete_entry_id"] == entry["id"]
                    and s["apparatus"] == apparatus
                    and s["score_state"] == "FINAL"):
                aa += s["final_total"]
    return q3(aa)


def evaluate_qualification(entry):
    """Returns dict(qualified, mobility, target, score_used, threshold)."""
    meet = meet_of_entry(entry)
    gymnast = DB.gymnasts.get(entry["gymnast_id"])
    level = gymnast["competitive_level"] if gymnast else None
    aa = entry["all_around_total"] or Decimal("0.000")

    state_th = regional_th = national_th = None
    if level in ("L4", "L5"):
        state_th = Decimal("32.000")
    elif level in ("L6", "L7", "L8"):
        state_th = Decimal("34.000")
        regional_th = Decimal("35.500")
    elif level in ("L9", "L10"):
        state_th = Decimal("34.500")
        regional_th = Decimal("36.000")
        if level == "L10":
            national_th = Decimal("37.500")

    aa_state = state_th is not None and aa >= state_th
    aa_regional = regional_th is not None and aa >= regional_th
    aa_national = national_th is not None and aa >= national_th
    aa_qualifies = aa_state or aa_regional or aa_national

    finals = [s for s in DB.scores.values()
              if s["athlete_entry_id"] == entry["id"] and s["score_state"] == "FINAL"]
    best_event = max((s["final_total"] for s in finals), default=Decimal("0.000"))
    event_qualifies = len(finals) > 0 and best_event >= Decimal("9.000")

    rule = meet["qualifying_score_rule"] if meet else "BOTH"
    if rule == "ALL_AROUND_ONLY":
        qualified = aa_qualifies
        mobility = aa
    elif rule == "PER_EVENT":
        qualified = event_qualifies
        mobility = best_event
    else:  # BOTH
        qualified = aa_qualifies or event_qualifies
        mobility = max(aa, best_event) if event_qualifies else aa

    target = score_used = threshold = None
    if qualified:
        if rule == "PER_EVENT":
            target, score_used, threshold = "STATE", best_event, Decimal("9.000")
        elif aa_qualifies:
            if aa_national:
                target, threshold = "NATIONAL", national_th
            elif aa_regional:
                target, threshold = "REGIONAL", regional_th
            else:
                target, threshold = "STATE", state_th
            score_used = aa
        else:  # BOTH, event path only
            target, score_used, threshold = "STATE", best_event, Decimal("9.000")

    return {"qualified": qualified, "mobility": mobility, "target": target,
            "score_used": score_used, "threshold": threshold}


def ensure_qualification_record(entry, result):
    if not result["qualified"]:
        return
    for r in DB.qual_records.values():
        if r["athlete_entry_id"] == entry["id"]:
            return
    rec = new_entity()
    rec.update({
        "athlete_entry_id": entry["id"],
        "target_meet_level": result["target"],
        "qualifying_score_used": result["score_used"],
        "threshold_applied": result["threshold"],
        "qualification_state": "PROVISIONAL",
        "confirmed_at": None,
    })
    DB.qual_records[rec["id"]] = rec


def complete_entry(entry):
    entry["entry_status"] = "COMPLETED"
    entry["all_around_total"] = compute_all_around(entry)
    result = evaluate_qualification(entry)
    entry["qualification_mobility_score"] = result["mobility"]
    ensure_qualification_record(entry, result)
    touch(entry)


# ----------------------------------------------------------------------------
# Award ordering / ranks
# ----------------------------------------------------------------------------

def session_entries(session_id):
    return [e for e in DB.entries.values() if e["session_id"] == session_id]


def session_scores(session_id):
    ids = {e["id"] for e in session_entries(session_id)}
    return [s for s in DB.scores.values() if s["athlete_entry_id"] in ids]


def rank_groups(rows, key_fn):
    """Competition ranking: equal keys share a rank; next rank skips.
    rows must be pre-sorted for presentation; returns {id: rank}."""
    ranks = {}
    prev_key = None
    prev_rank = 0
    for idx, row in enumerate(rows, start=1):
        k = key_fn(row)
        if prev_key is not None and k == prev_key:
            ranks[row["id"]] = prev_rank
        else:
            ranks[row["id"]] = idx
            prev_rank = idx
            prev_key = k
    return ranks


def compute_award_ordering(session):
    """Sets is_tied / tiebreak_rank on FINAL apparatus scores of the session."""
    meet = meet_of_session(session)
    policy = meet["tiebreak_policy"] if meet else "USAG_CLASSIC"
    for apparatus in ("VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"):
        scores = [s for s in session_scores(session["id"])
                  if s["apparatus"] == apparatus and s["score_state"] == "FINAL"]
        totals = {}
        for s in scores:
            totals.setdefault(s["final_total"], 0)
        for s in scores:
            tied = totals[s["final_total"]] > 1
            if s["is_tied"] != tied:
                s["is_tied"] = tied
        if policy == "USAG_CLASSIC":
            ordered = sorted(scores,
                             key=lambda s: (-s["final_total"], -s["execution_score"],
                                            -s["difficulty_score"], s["neutral_deduction"],
                                            s["created_at"], s["_seq"]))
            key_fn = lambda s: (-s["final_total"], -s["execution_score"],
                                -s["difficulty_score"], s["neutral_deduction"])
        else:  # NCAA_MODIFIED
            ordered = sorted(scores,
                             key=lambda s: (-s["final_total"], s["created_at"], s["_seq"]))
            key_fn = lambda s: (-s["final_total"],)
        ranks = rank_groups(ordered, key_fn)
        for s in scores:
            s["tiebreak_rank"] = ranks[s["id"]]


def compute_aa_ranks(session):
    entries = [e for e in session_entries(session["id"])
               if e["entry_status"] == "COMPLETED"]
    ordered = sorted(entries, key=lambda e: (-(e["all_around_total"] or Decimal("0")),
                                             e["created_at"], e["_seq"]))
    ranks = rank_groups(ordered, lambda e: e["all_around_total"])
    for e in entries:
        e["all_around_rank"] = ranks[e["id"]]


def run_session_close_computations(session):
    compute_award_ordering(session)
    compute_aa_ranks(session)
    for e in session_entries(session["id"]):
        if e["entry_status"] != "COMPLETED":
            continue
        result = evaluate_qualification(e)
        e["qualified_for_next_meet"] = result["qualified"]
        e["qualification_mobility_score"] = result["mobility"]
        ensure_qualification_record(e, result)


# ----------------------------------------------------------------------------
# Clock-driven system transitions (fixpoint sweep)
# ----------------------------------------------------------------------------

def _sweep_once():
    changed = False
    t = now()

    # Sessions: time-driven state progression (only once meet is published)
    for s in DB.sessions.values():
        meet = meet_of_session(s)
        if meet is None or meet["posture"] not in (
                "SCHEDULED", "WARMUP_OPEN", "IN_COMPETITION"):
            continue
        if s["state"] == "SCHEDULED" and t >= s["scheduled_start"] - timedelta(
                minutes=s["warmup_open_offset_minutes"]):
            s["state"] = "WARMUP_OPEN"
            touch(s)
            changed = True
        elif s["state"] == "WARMUP_OPEN" and t >= s["scheduled_start"] - timedelta(
                minutes=s["march_in_offset_minutes"]):
            s["state"] = "MARCH_IN"
            touch(s)
            changed = True
        elif s["state"] == "MARCH_IN" and t >= s["scheduled_start"]:
            s["state"] = "IN_ROTATION"
            touch(s)
            for r in DB.rotations.values():
                if (r["session_id"] == s["id"] and r["rotation_number"] == 1
                        and r["state"] == "PENDING"):
                    r["state"] = "WARMUP"
                    touch(r)
            for e in session_entries(s["id"]):
                if e["entry_status"] == "CHECKED_IN":
                    e["entry_status"] = "COMPETING"
                    touch(e)
            changed = True
        elif s["state"] == "IN_ROTATION":
            rots = [r for r in DB.rotations.values() if r["session_id"] == s["id"]]
            if rots and all(r["state"] in ("SCORING_CLOSED", "FINALIZED")
                            for r in rots):
                s["state"] = "SCORING"
                touch(s)
                changed = True

    # Meet posture: time-driven advancement
    for m in DB.meets.values():
        sessions = [s for s in DB.sessions.values() if s["meet_id"] == m["id"]]
        if not sessions:
            continue
        if m["posture"] == "SCHEDULED":
            earliest = min(s["scheduled_start"] - timedelta(
                minutes=s["warmup_open_offset_minutes"]) for s in sessions)
            if t >= earliest:
                m["posture"] = "WARMUP_OPEN"
                touch(m)
                changed = True
        if m["posture"] == "WARMUP_OPEN":
            earliest_start = min(s["scheduled_start"] for s in sessions)
            if t >= earliest_start:
                m["posture"] = "IN_COMPETITION"
                touch(m)
                for p in DB.panels.values():
                    if p["meet_id"] == m["id"] and p["panel_state"] == "FULL":
                        p["panel_state"] = "ACTIVE"
                        touch(p)
                changed = True

    # Rotations: warm-up opens 60 minutes before scheduled start
    for r in DB.rotations.values():
        meet = meet_of_session(DB.sessions.get(r["session_id"])) \
            if DB.sessions.get(r["session_id"]) else None
        if meet is None or meet["posture"] not in (
                "SCHEDULED", "WARMUP_OPEN", "IN_COMPETITION"):
            continue
        if r["state"] == "PENDING" and t >= r["scheduled_start"] - timedelta(minutes=60):
            r["state"] = "WARMUP"
            touch(r)
            changed = True

    # Warm-up blocks: go live at block_start, complete at block_end
    for b in DB.blocks.values():
        if b["state"] == "SCHEDULED" and t >= b["block_start"]:
            b["state"] = "IN_PROGRESS"
            touch(b)
            changed = True
        elif b["state"] == "IN_PROGRESS" and t >= b["block_end"]:
            b["state"] = "COMPLETE"
            touch(b)
            changed = True

    # Rotations: all blocks resolved -> TIMED_WARMUP_HELD
    for r in DB.rotations.values():
        if r["state"] != "WARMUP":
            continue
        blocks = [b for b in DB.blocks.values() if b["rotation_id"] == r["id"]]
        if all(b["state"] in ("COMPLETE", "SKIPPED") for b in blocks):
            r["state"] = "TIMED_WARMUP_HELD"
            touch(r)
            changed = True

    # Inquiries: FILED expires after published_at + 4 * inquiry window
    for iq in DB.inquiries.values():
        if iq["inquiry_state"] != "FILED":
            continue
        score = DB.scores.get(iq["score_id"])
        if score is None or score["published_at"] is None:
            continue
        meet = meet_of_score(score)
        window = meet["inquiry_window_minutes"] if meet else 5
        if t > score["published_at"] + timedelta(minutes=4 * window):
            expire_inquiry(iq)
            changed = True

    # Scores: PUBLISHED finalize when inquiry window lapses unchallenged
    for sc in DB.scores.values():
        if sc["score_state"] != "PUBLISHED" or sc["published_at"] is None:
            continue
        meet = meet_of_score(sc)
        window = meet["inquiry_window_minutes"] if meet else 5
        if t > sc["published_at"] + timedelta(minutes=window) \
                and not has_open_inquiry(sc["id"]):
            finalize_score(sc)
            changed = True

    # Rotations: SCORING_CLOSED -> FINALIZED when all scores terminal
    for r in DB.rotations.values():
        if r["state"] != "SCORING_CLOSED":
            continue
        scores = [s for s in DB.scores.values() if s["rotation_id"] == r["id"]]
        if all(s["score_state"] in SCORE_CLOSED_STATES for s in scores):
            r["state"] = "FINALIZED"
            touch(r)
            changed = True

    # Entries: COMPETING -> COMPLETED once all four apparatus scores terminal
    for e in DB.entries.values():
        if e["entry_status"] != "COMPETING":
            continue
        finals = [s for s in DB.scores.values()
                  if s["athlete_entry_id"] == e["id"]
                  and s["score_state"] in SCORE_CLOSED_STATES]
        if len(finals) >= 4:
            complete_entry(e)
            changed = True

    return changed


def run_system_transitions():
    guard = 0
    while _sweep_once():
        guard += 1
        if guard > 100:
            break


# ----------------------------------------------------------------------------
# Selectors and layout generators
# ----------------------------------------------------------------------------

def squad_assignment(session):
    meet = meet_of_session(session)
    cap = meet["max_athletes_per_squad"]
    eligible = [e for e in session_entries(session["id"])
                if e["entry_status"] == "REGISTERED" and e["squad_id"] is None]

    def sort_key(e):
        g = DB.gymnasts.get(e["gymnast_id"])
        return (e["created_at"], g["usag_member_number"] if g else "", e["_seq"])

    eligible.sort(key=sort_key)

    groups = []
    by_gym = {}
    for e in eligible:
        g = DB.gymnasts.get(e["gymnast_id"])
        gym = g["home_gym"] if g else ""
        if gym not in by_gym:
            by_gym[gym] = []
            groups.append(by_gym[gym])
        by_gym[gym].append(e)

    squads = sort_items([s for s in DB.squads.values()
                         if s["session_id"] == session["id"]])
    counts = {s["id"]: athlete_count(s["id"]) for s in squads}
    for group in groups:
        target = None
        for s in squads:
            if counts[s["id"]] + len(group) <= cap:
                target = s
                break
        if target is None:
            continue
        for e in group:
            e["squad_id"] = target["id"]
            touch(e)
        counts[target["id"]] += len(group)
    return squads


def judge_panel_selector(panel):
    from common import ApiError
    session = DB.sessions.get(panel["session_id"])
    gyms = session_gyms(panel["session_id"])
    band_tier = BAND_TIERS[session["level_band"]]
    need = panel["required_judge_count"]

    def overlaps(other_session):
        return (session["scheduled_start"] < other_session["scheduled_end"]
                and other_session["scheduled_start"] < session["scheduled_end"])

    eligible = []
    for j in DB.judges.values():
        if RATING_TIERS[j["rating"]] < band_tier:
            continue
        if not (j["availability_start"] <= session["scheduled_start"]
                and j["availability_end"] >= session["scheduled_end"]):
            continue
        if j["affiliated_gym"] in gyms:
            continue
        conflicted = False
        for a in DB.assignments.values():
            if a["judge_id"] != j["id"] or a["assignment_state"] != "CONFIRMED":
                continue
            other_panel = DB.panels.get(a["judge_panel_id"])
            if other_panel is None or other_panel["id"] == panel["id"]:
                continue
            other_session = DB.sessions.get(other_panel["session_id"])
            if other_session is not None and overlaps(other_session):
                conflicted = True
                break
        if conflicted:
            continue
        eligible.append(j)

    eligible.sort(key=lambda j: (-RATING_TIERS[j["rating"]], j["usag_judge_number"]))
    if len(eligible) < need:
        raise ApiError("ERR_INSUFFICIENT_JUDGE_POOL", 422,
                       "Eligible judge pool (%d) is smaller than required count (%d)"
                       % (len(eligible), need))
    created = []
    for idx, j in enumerate(eligible[:need]):
        a = new_entity()
        a.update({
            "judge_panel_id": panel["id"],
            "judge_id": j["id"],
            "role": "PANEL_CHIEF" if idx == 0 else "E_JUDGE",
            "assignment_state": "PROPOSED",
            "conflict_flag": False,
        })
        a["conflict_flag"] = compute_conflict(a)
        DB.assignments[a["id"]] = a
        created.append(a)
    return created


def generate_rotations(session):
    from common import ApiError
    existing = [r for r in DB.rotations.values() if r["session_id"] == session["id"]]
    if existing:
        raise ApiError("ERR_ROTATION_OVERLAP", 422,
                       "Rotations already exist for this session")
    total = sum(athlete_count(s["id"]) for s in DB.squads.values()
                if s["session_id"] == session["id"])
    created = []
    current = session["scheduled_start"]
    for idx, slot in enumerate(session["apparatus_set"], start=1):
        apparatus = slot["apparatus"]
        minutes = int(math.ceil(total * PER_ATHLETE_SECONDS[apparatus] / 60.0))
        r = new_entity()
        r.update({
            "session_id": session["id"],
            "rotation_number": idx,
            "apparatus": apparatus,
            "scheduled_start": current,
            "scheduled_end": current + timedelta(minutes=minutes),
            "actual_start": None,
            "actual_end": None,
            "state": "PENDING",
        })
        DB.rotations[r["id"]] = r
        created.append(r)
        current = r["scheduled_end"] + timedelta(minutes=5)
    return created


def generate_warmup_blocks(rotation):
    from common import ApiError
    existing = [b for b in DB.blocks.values() if b["rotation_id"] == rotation["id"]]
    if existing:
        raise ApiError("ERR_WARMUP_BLOCK_OVERLAP", 422,
                       "Warm-up blocks already exist for this rotation")
    session = DB.sessions.get(rotation["session_id"])
    squads = [s for s in DB.squads.values() if s["session_id"] == rotation["session_id"]]
    squads.sort(key=lambda s: (s["rotation_index"], s["created_at"], s["_seq"]))
    window_start = rotation["scheduled_start"] - timedelta(minutes=60)
    total_minutes = 60
    allocated = 0
    created = []
    spans = []
    for s in squads:
        raw = int(math.ceil(athlete_count(s["id"]) * 2))
        block_minutes = max(8, min(20, raw))
        if allocated + block_minutes > total_minutes:
            block_minutes = total_minutes - allocated
        start = window_start + timedelta(minutes=allocated)
        end = start + timedelta(minutes=block_minutes)
        allocated += block_minutes
        spans.append((s, start, end))
    if allocated < total_minutes and spans:
        s, start, end = spans[-1]
        spans[-1] = (s, start, end + timedelta(minutes=total_minutes - allocated))
    for s, start, end in spans:
        b = new_entity()
        b.update({
            "rotation_id": rotation["id"],
            "squad_id": s["id"],
            "apparatus": rotation["apparatus"],
            "block_start": start,
            "block_end": end,
            "state": "SCHEDULED",
        })
        DB.blocks[b["id"]] = b
        created.append(b)
    return created
