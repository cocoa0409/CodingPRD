"""Attribute effective-dating timeline, per PRD §3.4 and the
attribute_effective_dating / conflicting_source_precedence calculations.

Intervals are half-open [effective_date, term_date); term_date null means
+infinity. All comparisons are day-level (ISO date strings compare correctly).
"""

from db import DB, CLOCK
from services.common import new_common, touch


def _attrs_for(provider_id, group, key):
    return [
        a for a in DB.provider_attributes.values()
        if a["provider_id"] == provider_id
        and a["attribute_group"] == group
        and a["attribute_key"] == key
    ]


def _source(attr):
    return DB.roster_sources.get(attr.get("roster_source_id"))


def _rank_of(attr):
    src = _source(attr)
    return src["precedence_rank"] if src else 0


def _source_created(attr):
    src = _source(attr)
    return src["created_at"] if src else ""


def _overlaps(a, b):
    """Half-open interval overlap: a.start < b.end and b.start < a.end,
    None end = +infinity. Adjacent (a.start == b.end) is NOT overlap."""
    a_end = a.get("term_date") or "9999-12-31"
    b_end = b.get("term_date") or "9999-12-31"
    return a["effective_date"] < b_end and b["effective_date"] < a_end


def apply_effective_dating(provider_id, incoming, committer_user_id=None):
    """Apply the §3.4 dating rules for an incoming ProviderAttribute record
    (already stored in DB with status PENDING) against existing ACTIVE
    intervals for the same (provider, group, key).

    Returns the incoming attribute with its final status set. Handles:
    - retro guard (RETRO_PENDING)
    - future effective_date (stays PENDING)
    - supersede / truncate / zero-length cleanup
    - retro-with-split variant
    - cross-source precedence adjudication + conflict creation
    """
    today = CLOCK.today()
    group = incoming["attribute_group"]
    key = incoming["attribute_key"]
    new_eff = incoming["effective_date"]
    new_term = incoming.get("term_date")

    existing = [
        a for a in _attrs_for(provider_id, group, key)
        if a["status"] == "ACTIVE" and a["id"] != incoming["id"]
    ]

    # --- Step 2: retro guard -------------------------------------------------
    # When the incoming effective_date precedes every existing effective date
    # in the group AND applying it would rewrite the historically-first value,
    # the incoming interval enters RETRO_PENDING instead of applying.
    group_attrs = [
        a for a in _attrs_for(provider_id, group, key)
        if a["id"] != incoming["id"] and a["status"] in ("ACTIVE", "PENDING")
    ]
    if group_attrs:
        earliest_eff = min(a["effective_date"] for a in group_attrs)
        if new_eff < earliest_eff:
            # Would change the historically-first value -> adjudicate.
            incoming["status"] = "RETRO_PENDING"
            touch(incoming)
            return incoming

    # --- Future effective date: stays PENDING, no transition fires yet. ------
    if new_eff > today:
        incoming["status"] = "PENDING"
        touch(incoming)
        return incoming

    # --- Cross-source conflict check (§3.5) ---------------------------------
    # Overlapping intervals for the same group/key from different sources
    # never split; precedence decides. Same-value different-source overlap also
    # raises a conflict per the calculation's step 5.
    for inc in list(existing):
        if not _overlaps(incoming, inc):
            continue
        inc_src = _source(inc)
        new_src = _source(incoming)
        if inc_src is None or new_src is None:
            continue
        if inc["roster_source_id"] == incoming["roster_source_id"]:
            continue
        if inc["attribute_value"] == incoming["attribute_value"]:
            continue
        # Different sources, overlapping, different values -> precedence.
        if inc_src["precedence_rank"] < new_src["precedence_rank"]:
            # Incumbent wins automatically: challenger VOIDED, no conflict.
            incoming["status"] = "VOIDED"
            touch(incoming)
            return incoming
        elif new_src["precedence_rank"] < inc_src["precedence_rank"]:
            # Challenger wins automatically.
            inc["status"] = "SUPERSEDED"
            incoming["supersedes_attribute_id"] = inc["id"]
            touch(inc)
            incoming["status"] = "ACTIVE"
            touch(incoming)
            existing.remove(inc)
        else:
            # Equal rank -> conflict; incumbent slot to the earlier-registered
            # source (or earlier-created attribute when sources identical).
            if inc_src["created_at"] < new_src["created_at"]:
                incumbent, challenger = inc, incoming
            elif new_src["created_at"] < inc_src["created_at"]:
                incumbent, challenger = incoming, inc
            else:
                if inc["created_at"] <= incoming["created_at"]:
                    incumbent, challenger = inc, incoming
                else:
                    incumbent, challenger = incoming, inc
            conflict = {
                **new_common(),
                "provider_id": provider_id,
                "attribute_group": group,
                "attribute_key": key,
                "incumbent_attribute_id": incumbent["id"],
                "challenger_attribute_id": challenger["id"],
                "incumbent_source_id": incumbent["roster_source_id"],
                "challenger_source_id": challenger["roster_source_id"],
                "resolution": "PENDING",
                "resolution_reason": None,
                "resolved_value": None,
                "status": "OPEN",
                # SoD bookkeeping: opaque user id of the operator whose commit
                # created the challenger attribute's file.
                "_challenger_committer_user_id": _committer_of(challenger),
            }
            DB.attribute_conflicts[conflict["id"]] = conflict
            # Challenger stays PENDING until adjudication.
            challenger["status"] = "PENDING"
            touch(challenger)
            if incoming["id"] == challenger["id"]:
                return incoming
            else:
                # Incoming became incumbent: it is applied ACTIVE below.
                incoming["status"] = "ACTIVE"
                touch(incoming)
                existing.append(incoming)
                # The old incumbent stays ACTIVE as well (it is the incumbent).
                return incoming

    # --- Step 3: apply rewrite rules -----------------------------------------
    incoming["status"] = "ACTIVE"
    touch(incoming)

    # Retro-with-split variant: incoming effective_date is in the past and
    # lands strictly inside an existing interval -> split instead of truncate.
    for inc in list(existing):
        if not _overlaps(incoming, inc):
            # Adjacent-touch rule is handled by _overlaps returning False for
            # new_eff == inc.term_date (adjacent, not overlapping).
            continue
        inc_start = inc["effective_date"]
        inc_end = inc.get("term_date")
        inside_existing = (
            new_eff < today
            and inc_start < new_eff
            and (inc_end is None or new_eff < inc_end)
            and (new_term is not None and (inc_end is None or new_term < inc_end))
        )
        if inside_existing:
            # Split: left half keeps the original interval truncated to
            # [old_start, new_start); right half is a new ACTIVE interval with
            # the old value spanning [new_term, old_end).
            right = {
                **new_common(),
                "provider_id": provider_id,
                "attribute_group": group,
                "attribute_key": key,
                "attribute_value": inc["attribute_value"],
                "effective_date": new_term,
                "term_date": inc_end,
                "roster_source_id": inc["roster_source_id"],
                "roster_row_id": inc.get("roster_row_id"),
                "supersedes_attribute_id": None,
                "status": "ACTIVE",
            }
            DB.provider_attributes[right["id"]] = right
            inc["term_date"] = new_eff
            touch(inc)
            incoming["supersedes_attribute_id"] = incoming.get("supersedes_attribute_id")
            continue

        # Rule a: existing begins on/after incoming start and incoming covers
        # its whole span -> supersede.
        if inc_start >= new_eff and (
            inc_end is None
            or (new_term is not None and inc_end <= new_term)
            or new_term is None
        ):
            inc["status"] = "SUPERSEDED"
            incoming["supersedes_attribute_id"] = inc["id"]
            touch(inc)
            existing.remove(inc)
            continue

        # Rule b: existing begins strictly before incoming start and extends
        # past it -> truncate.
        if inc_start < new_eff and (inc_end is None or inc_end > new_eff):
            inc["term_date"] = new_eff
            # Rule c: zero-length intervals never persist.
            if inc["term_date"] is not None and inc["term_date"] <= inc["effective_date"]:
                inc["status"] = "SUPERSEDED"
                incoming["supersedes_attribute_id"] = inc["id"]
            touch(inc)
            continue

    return incoming


def _committer_of(attr):
    """Return the opaque user id of the operator who committed the file that
    created this attribute (via its roster_row_id -> roster_file_id)."""
    row_id = attr.get("roster_row_id")
    if not row_id:
        return None
    row = DB.roster_rows.get(row_id)
    if row is None:
        return None
    f = DB.roster_files.get(row["roster_file_id"])
    if f is None:
        return None
    return f.get("_committer_user_id")
