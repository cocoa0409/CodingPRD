"""Answer-routing selector and spam scoring (SCAFFOLD §1.3 calc 3 & 4, PRD §3.4-3.6)."""
from db import db


def area_code(caller_id):
    """First three characters of a caller_id, or '' if too short/empty."""
    if caller_id and len(caller_id) >= 3:
        return caller_id[:3]
    return ""


def spam_score_provisional(caller_id, rule):
    """Provisional spam score (PRD §3.4): static signals only.

    0 + anonymous_penalty (if caller_id == '') + 50 (if area code blocked),
    capped at 100.
    """
    score = 0
    if caller_id == "":
        score += rule["anonymous_penalty"]
    if area_code(caller_id) in rule["blocked_area_codes"]:
        score += 50
    return min(100, score)


def spam_score_final(caller_id, rule, reached_in_progress):
    """Final spam score (PRD §3.6): like provisional, minus 30 (floor 0) if the
    call ever reached IN_PROGRESS."""
    score = spam_score_provisional(caller_id, rule)
    if reached_in_progress:
        score = max(0, score - 30)
    return score


def active_spam_rule(account_id):
    """The matched ACTIVE SpamRule for an account, or None.

    Deterministic: oldest ACTIVE rule first.
    """
    rules = [r for r in db.spam_rules.values()
             if r["account_id"] == account_id and r["status"] == "ACTIVE"]
    if not rules:
        return None
    rules.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rules[0]


def _rank_candidates(candidates):
    """Sort by active_call_count ASC, max_concurrent_calls DESC, created_at ASC
    (never id) (SCAFFOLD §1.3 calc 4, PRD §3.5)."""
    return sorted(
        candidates,
        key=lambda r: (r["active_call_count"], -r["max_concurrent_calls"],
                       r["created_at"], r["_seq"]),
    )


def select_receptionist(requested_language, senior=False):
    """Pick an eligible receptionist for an answer (PRD §3.5) or escalation
    (senior=True requires max_concurrent_calls >= 2). Returns the record or None.

    Eligibility: status AVAILABLE, active_call_count < max_concurrent_calls,
    requested_language in languages.
    """
    candidates = []
    for r in db.receptionists.values():
        if r["status"] != "AVAILABLE":
            continue
        if r["active_call_count"] >= r["max_concurrent_calls"]:
            continue
        if requested_language not in r["languages"]:
            continue
        if senior and r["max_concurrent_calls"] < 2:
            continue
        candidates.append(r)
    if not candidates:
        return None
    return _rank_candidates(candidates)[0]


def any_receptionist_speaks_language(requested_language):
    """True if at least one receptionist (any status) speaks the language —
    used to disambiguate ERR_NO_LANGUAGE_MATCH from empty-pool OVERFLOW."""
    for r in db.receptionists.values():
        if requested_language in r["languages"]:
            return True
    return False


def published_script(account_id):
    """The account's single PUBLISHED CallScript, or None (PRD §3.2)."""
    for s in db.call_scripts.values():
        if s["account_id"] == account_id and s["status"] == "PUBLISHED":
            return s
    return None
