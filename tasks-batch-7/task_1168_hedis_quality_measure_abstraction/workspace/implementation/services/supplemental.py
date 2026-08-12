"""§3.6 supplemental record screening/matching."""
from db import db


def normalize_ref(s):
    """TOLERANT variant: uppercase(trim(s)); if all digits, strip leading zeros
    (empty -> '0')."""
    n = s.strip().upper()
    if n.isdigit():
        n = n.lstrip("0")
        if n == "":
            n = "0"
    return n


def member_refs():
    return {m["member_ref"] for m in db.members.values()}


def member_matches(raw_ref, policy):
    refs = member_refs()
    if policy == "EXACT":
        return raw_ref in refs
    target = normalize_ref(raw_ref)
    return any(normalize_ref(r) == target for r in refs)


def canonical_triple(member_ref, service_date, evidence_code, policy):
    """Duplicate comparison key: normalized member_ref, date part, evidence_code."""
    if policy == "EXACT":
        ref_key = member_ref
    else:
        ref_key = normalize_ref(member_ref)
    return (ref_key, service_date.date().isoformat(), evidence_code)


def screen_batch(batch, run, season, spec):
    """Run supplemental_record_matching over the batch's records; sets
    dispositions, accepted_record_count, matching_policy_used."""
    policy = spec["matching_policy"]
    batch["matching_policy_used"] = policy

    year = season["measurement_year"]
    window_start = "%04d-01-01" % year
    window_end = "%04d-12-31" % year

    records = sorted(
        (r for r in db.records.values() if r["batch_id"] == batch["id"]),
        key=lambda r: r["created_at"],
    )

    # cross-batch accepted triples (same run, other ACCEPTED batches)
    accepted_batches = [b for b in db.batches.values()
                        if b["run_id"] == run["id"] and b["status"] == "ACCEPTED"
                        and b["id"] != batch["id"]]
    accepted_ids = {b["id"] for b in accepted_batches}
    seen_triples = set()
    for r in db.records.values():
        if r["batch_id"] in accepted_ids and r["disposition"] == "ACCEPTED":
            seen_triples.add(canonical_triple(r["member_ref"], r["service_date"],
                                              r["evidence_code"], policy))

    accepted_count = 0
    for r in records:
        # 1. match
        if not member_matches(r["member_ref"], policy):
            r["disposition"] = "REJECTED_UNKNOWN_MEMBER"
            continue
        # 2. window
        d = r["service_date"].date().isoformat()
        if d < window_start or d > window_end:
            r["disposition"] = "REJECTED_OUT_OF_WINDOW"
            continue
        # 3. duplicate
        triple = canonical_triple(r["member_ref"], r["service_date"], r["evidence_code"], policy)
        if triple in seen_triples:
            r["disposition"] = "REJECTED_DUPLICATE"
            continue
        seen_triples.add(triple)
        r["disposition"] = "ACCEPTED"
        accepted_count += 1

    batch["accepted_record_count"] = accepted_count
    batch["record_count"] = len(records)
