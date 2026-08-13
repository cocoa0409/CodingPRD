"""Identity resolution per PRD §3.3 and the identity_resolution calculation."""

from db import DB
from services.common import new_common, touch


W_NPI = 50
W_TIN = 30
W_LOCATION = 20
MATCH_THRESHOLD = 70
EXACT_SCORE = 100


def _match_score(provider, row):
    score = 0
    if provider["npi"] == row.get("npi"):
        score += W_NPI
    if provider["tin"] == row.get("tin"):
        score += W_TIN
    if provider["location_key"] == row.get("location_key"):
        score += W_LOCATION
    return score


def resolve_row(row, roster_source):
    """Run identity resolution for one non-REJECTED row. Mutates row status,
    resolved_provider_id, and records the winning match score for alias
    creation at commit time."""
    candidates = [
        p for p in DB.providers.values()
        if p["lifecycle_status"] in ("ACTIVE", "SUSPENDED")
        and (
            p["npi"] == row.get("npi")
            or p["tin"] == row.get("tin")
            or p["location_key"] == row.get("location_key")
        )
    ]
    scored = [(p, _match_score(p, row)) for p in candidates]
    at_or_above = [(p, s) for p, s in scored if s >= MATCH_THRESHOLD]
    perfect = [(p, s) for p, s in scored if s == EXACT_SCORE]

    strict = roster_source.get("format") == "FHIR"

    # Tie-break among equal top scores: earliest Provider.created_at wins;
    # a tie surviving even that comparison sends the row to CONFLICT.
    def pick_top(pairs):
        best = max(s for _, s in pairs)
        tops = [p for p, s in pairs if s == best]
        if len(tops) == 1:
            return tops[0], best, False
        earliest = min(p["created_at"] for p in tops)
        tied = [p for p in tops if p["created_at"] == earliest]
        if len(tied) == 1:
            return tied[0], best, False
        return None, best, True

    if strict:
        # FHIR: only a perfect score matches; [70,99] resolves to CONFLICT.
        if len(perfect) == 1:
            p, s = perfect[0]
            if len(at_or_above) == 1:
                _matched(row, p, s, "AUTO_EXACT")
            else:
                _conflict(row)
        elif len(perfect) > 1:
            p, s, still_tied = pick_top(perfect)
            if still_tied or len(at_or_above) > 1:
                _conflict(row)
            else:
                _matched(row, p, s, "AUTO_EXACT")
        elif len(at_or_above) == 0:
            row["status"] = "NEW_PROVIDER"
        else:
            _conflict(row)
        touch(row)
        return

    if len(at_or_above) == 0:
        row["status"] = "NEW_PROVIDER"
    elif len(perfect) == 1 and len(at_or_above) == 1:
        p, s = perfect[0]
        _matched(row, p, s, "AUTO_EXACT")
    elif len(perfect) >= 1 and len(at_or_above) > 1:
        _conflict(row)
    elif len(perfect) > 1:
        _conflict(row)
    else:
        # No perfect scorer; one or more in [70,99].
        if len(at_or_above) == 1:
            p, s = at_or_above[0]
            _matched(row, p, s, "AUTO_FUZZY")
        else:
            p, s, still_tied = pick_top(at_or_above)
            if still_tied:
                _conflict(row)
            else:
                _matched(row, p, s, "AUTO_FUZZY")
    touch(row)


def _matched(row, provider, score, link_kind):
    row["status"] = "MATCHED"
    row["resolved_provider_id"] = provider["id"]
    row["_winning_match_score"] = score
    row["_winning_link_kind"] = link_kind


def _conflict(row):
    row["status"] = "CONFLICT"
