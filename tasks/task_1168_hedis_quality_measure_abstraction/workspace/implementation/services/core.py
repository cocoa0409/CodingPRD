"""Core business services: lookups, bump helpers, rate recomputation,
over-read selector top-up, gap reconciliation."""
import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import db, new_id, subtract_months


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def touch(rec):
    """Common-fields mutation: updated_at = logical now, version += 1."""
    rec["updated_at"] = db.clock
    rec["version"] += 1


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def find_run(run_id):
    return get_or_404(db.runs, run_id)


def find_season(season_id):
    return get_or_404(db.seasons, season_id)


def find_spec(spec_id):
    return get_or_404(db.specs, spec_id)


def find_sample(sample_id):
    return get_or_404(db.samples, sample_id)


def find_chase(chase_id):
    return get_or_404(db.chases, chase_id)


def find_abstraction(abstraction_id):
    return get_or_404(db.abstractions, abstraction_id)


def find_batch(batch_id):
    return get_or_404(db.batches, batch_id)


def find_gap(gap_id):
    return get_or_404(db.gap_items, gap_id)


def find_engagement(engagement_id):
    return get_or_404(db.engagements, engagement_id)


def find_finding(finding_id):
    return get_or_404(db.findings, finding_id)


def find_member(member_id):
    return get_or_404(db.members, member_id)


def find_provider(provider_id):
    return get_or_404(db.providers, provider_id)


def find_entry(entry_id):
    return get_or_404(db.population_entries, entry_id)


def run_sample(run_id):
    for s in db.samples.values():
        if s["run_id"] == run_id:
            return s
    return None


def sample_of_run(run):
    return run_sample(run["id"])


def round4(value):
    """Round half-up to 4 decimal places; returns float for JSON."""
    d = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(d)


def round2(value):
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# §3.5 over-read selector top-up
# ---------------------------------------------------------------------------

COUNTED_ABSTRACTION_STATES = {"SUBMITTED", "CONFIRMED", "OVERREAD_PASSED"}


def abstractions_of_sample(sample_id):
    chase_ids = {c["id"] for c in db.chases.values() if c["sample_id"] == sample_id}
    return [a for a in db.abstractions.values() if a["chase_id"] in chase_ids]


def selector_top_up(sample):
    """Flag requires_overread=true on earliest SUBMITTED abstractions until
    count(flagged among SUBMITTED) >= ceil(required_overread_fraction * submitted_count).
    Never unflags an already-flagged abstraction."""
    subs = [a for a in abstractions_of_sample(sample["id"]) if a["status"] == "SUBMITTED"]
    subs.sort(key=lambda a: (a["submitted_at"] or a["created_at"], a["created_at"]))
    submitted_count = len(subs)
    if submitted_count == 0:
        return
    target = math.ceil(sample["required_overread_fraction"] * submitted_count)
    flagged = sum(1 for a in subs if a["requires_overread"])
    for a in subs:
        if flagged >= target:
            break
        if not a["requires_overread"]:
            a["requires_overread"] = True
            a["updated_at"] = db.clock  # flag mutation touches updated_at but not version
            flagged += 1


# ---------------------------------------------------------------------------
# §3.7 rate determination (incremental recompute of counters; rates only at compute-rate)
# ---------------------------------------------------------------------------

def chase_for_member(sample_id, member_ref):
    for c in db.chases.values():
        if c["sample_id"] == sample_id and c["member_ref"] == member_ref:
            return c
    return None


def recompute_run_counters(run):
    """Recompute admin_numerator_count and sample_numerator_count (§3.7) plus
    per-entry sample_compliant flags. Does not touch rates or version."""
    entries = [e for e in db.population_entries.values() if e["run_id"] == run["id"]]
    non_excluded = [e for e in entries if not e["is_excluded"]]
    run["admin_numerator_count"] = sum(1 for e in non_excluded if e["admin_compliant"])

    if run["collection_method"] == "HYBRID":
        sample = sample_of_run(run)
        spec = db.specs.get(run["spec_id"])
        hybrid_policy = spec["hybrid_policy"] if spec else "SAMPLE_ONLY"
        numerator = 0
        if sample is not None:
            sampled = [e for e in entries if e["is_sampled"]]
            for e in sampled:
                chase = chase_for_member(sample["id"], e["member_ref"])
                hit = False
                if chase is not None:
                    for a in db.abstractions.values():
                        if (a["chase_id"] == chase["id"] and a["result"] == "HIT"
                                and a["status"] in COUNTED_ABSTRACTION_STATES):
                            hit = True
                            break
                new_flag = bool(hit)
                if e["sample_compliant"] != new_flag:
                    e["sample_compliant"] = new_flag
                if hybrid_policy == "ADMIN_SUPPLEMENTED":
                    compliant = hit or e["admin_compliant"]
                else:
                    compliant = hit
                if compliant:
                    numerator += 1
        run["sample_numerator_count"] = numerator


def compute_rates(run):
    """Set admin_rate / hybrid_rate / final_rate (4dp half-up) on the run."""
    denom = run["denominator_count"]
    run["admin_rate"] = round4(Decimal(run["admin_numerator_count"]) / Decimal(denom))
    if run["collection_method"] == "HYBRID":
        sample = sample_of_run(run)
        hybrid_denom = sample["drawn_size"] - run["sample_exclusion_count"]
        run["hybrid_rate"] = round4(Decimal(run["sample_numerator_count"]) / Decimal(hybrid_denom))
        run["final_rate"] = run["hybrid_rate"]
    else:
        run["final_rate"] = run["admin_rate"]


# ---------------------------------------------------------------------------
# §3.7 gap list regeneration / provider reconciliation
# ---------------------------------------------------------------------------

def entry_is_compliant(run, entry, spec):
    """Compliance under the run's method for gap minting at compute-rate."""
    if run["collection_method"] == "ADMINISTRATIVE":
        return entry["admin_compliant"]
    # HYBRID: not sampled -> judged administratively; sampled -> variant rule
    if not entry["is_sampled"]:
        return entry["admin_compliant"]
    if spec["hybrid_policy"] == "ADMIN_SUPPLEMENTED":
        return entry["sample_compliant"] or entry["admin_compliant"]
    return entry["sample_compliant"]


def provider_by_ref(provider_ref):
    if provider_ref is None:
        return None
    for p in db.providers.values():
        if p["provider_ref"] == provider_ref:
            return p
    return None


def decrement_provider_gap_count(provider_ref):
    p = provider_by_ref(provider_ref)
    if p is not None:
        p["open_gap_count"] = max(0, p["open_gap_count"] - 1)
        p["updated_at"] = db.clock
        p["version"] += 1


def increment_provider_gap_count(provider_ref):
    p = provider_by_ref(provider_ref)
    if p is not None:
        p["open_gap_count"] += 1
        p["updated_at"] = db.clock
        p["version"] += 1


def regenerate_gap_list(run):
    """compute-rate side effect: delete this run's OPEN|OUTREACH_DONE gaps,
    mint one OPEN gap per non-excluded non-compliant entry; reconcile counts."""
    spec = db.specs.get(run["spec_id"])
    doomed = [g for g in db.gap_items.values()
              if g["run_id"] == run["id"] and g["status"] in ("OPEN", "OUTREACH_DONE")]
    for g in doomed:
        del db.gap_items[g["id"]]
        decrement_provider_gap_count(g["provider_ref"])

    entries = sorted(
        (e for e in db.population_entries.values()
         if e["run_id"] == run["id"] and not e["is_excluded"]),
        key=lambda e: e["member_ref"],
    )
    member_by_ref = {m["member_ref"]: m for m in db.members.values()}
    for e in entries:
        if entry_is_compliant(run, e, spec):
            continue
        member = member_by_ref.get(e["member_ref"])
        provider_ref = member["attributed_provider_ref"] if member else None
        gap = {
            "id": new_id(),
            "run_id": run["id"],
            "member_ref": e["member_ref"],
            "provider_ref": provider_ref,
            "gap_reason": "NO_EVIDENCE_OF_SERVICE",
            "status": "OPEN",
            "closure_source": None,
            "created_at": db.clock,
            "updated_at": db.clock,
            "version": 1,
        }
        db.gap_items[gap["id"]] = gap
        increment_provider_gap_count(provider_ref)


def auto_close_gap_for_entry(run, entry):
    """Supplemental acceptance cascade link 2: close OPEN|OUTREACH_DONE gap."""
    for g in db.gap_items.values():
        if (g["run_id"] == run["id"] and g["member_ref"] == entry["member_ref"]
                and g["status"] in ("OPEN", "OUTREACH_DONE")):
            g["status"] = "CLOSED_COMPLIANT"
            g["closure_source"] = "AUTO_EVIDENCE"
            touch(g)
            decrement_provider_gap_count(g["provider_ref"])


# ---------------------------------------------------------------------------
# §3.3 eligible population identification
# ---------------------------------------------------------------------------

def identify_population(run, spec):
    """Mint PopulationEntries for eligible members; returns count."""
    anchor = spec["anchor_date"].date()
    window_end = anchor
    window_start = subtract_months(anchor, spec["continuous_enrollment_months"]) + timedelta(days=1)

    segments_by_member = {}
    for seg in db.enrollment_segments.values():
        segments_by_member.setdefault(seg["member_id"], []).append(seg)

    minted = 0
    for member in sorted(db.members.values(), key=lambda m: m["member_ref"]):
        if spec["gender_requirement"] != "ANY" and member["gender"] != spec["gender_requirement"]:
            continue
        age = _whole_years(member["birth_date"].date(), anchor)
        if age < spec["age_min"] or age > spec["age_max"]:
            continue
        segs = sorted(segments_by_member.get(member["id"], []),
                      key=lambda s: (s["span_start"].date(), s["span_end"].date()))
        merged = _merge_closed([(s["span_start"].date(), s["span_end"].date()) for s in segs])
        clipped = [(max(a, window_start), min(b, window_end))
                   for (a, b) in merged if a <= window_end and b >= window_start]
        clipped = [(a, b) for (a, b) in clipped if a <= b]
        gaps = _uncovered(clipped, window_start, window_end)
        if len(gaps) <= 1 and all((b - a).days + 1 <= spec["allowable_gap_days"] for (a, b) in gaps):
            entry = {
                "id": new_id(),
                "run_id": run["id"],
                "member_ref": member["member_ref"],
                "is_excluded": False,
                "exclusion_reason": None,
                "is_sampled": False,
                "admin_compliant": False,
                "sample_compliant": False,
                "created_at": db.clock,
                "updated_at": db.clock,
                "version": 1,
            }
            db.population_entries[entry["id"]] = entry
            minted += 1
    return minted


def _whole_years(birth, anchor):
    years = anchor.year - birth.year
    if (anchor.month, anchor.day) < (birth.month, birth.day):
        years -= 1
    return years


def _merge_closed(intervals):
    if not intervals:
        return []
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + timedelta(days=1):
            # closed intervals: a <= prev_end + 1 day merges (adjacent days are contiguous)
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _uncovered(clipped, window_start, window_end):
    """Day-ranges strictly inside the clipped window not covered by any interval."""
    if window_start > window_end:
        return []
    gaps = []
    cursor = window_start
    for a, b in sorted(clipped):
        if a > cursor:
            gaps.append((cursor, a - timedelta(days=1)))
        if b >= cursor:
            cursor = b + timedelta(days=1)
        if cursor > window_end:
            break
    if cursor <= window_end:
        gaps.append((cursor, window_end))
    return gaps
