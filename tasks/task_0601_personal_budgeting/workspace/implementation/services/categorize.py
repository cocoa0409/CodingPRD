"""Auto-categorization selector policy (PRD §3.4, scaffold calc auto_categorize).

Candidates: enabled rules in the same household whose lowercased match_substring
occurs in the lowercased merchant_name. Winner: lowest priority, then earliest
created_at (never id). The winning rule's category is assigned ONLY IF that
category belongs to the household's current period; otherwise leave uncategorized.
"""

from db import db


def auto_categorize(txn, household):
    if txn.get("budget_category_id") is not None:
        return  # already categorized
    merchant = (txn.get("merchant_name") or "").lower()
    candidates = []
    for r in db.category_rules.values():
        if r["household_id"] != household["id"]:
            continue
        if not r["enabled"]:
            continue
        if r["match_substring"].lower() in merchant:
            candidates.append(r)
    if not candidates:
        return
    candidates.sort(key=lambda r: (r["priority"], r["created_at"], r.get("_seq", 0)))
    winner = candidates[0]
    target_cat = db.budget_categories.get(winner["budget_category_id"])
    cur = household.get("current_period_id")
    if target_cat is None or cur is None or target_cat["budget_period_id"] != cur:
        return  # stale-period rule; leave uncategorized
    txn["budget_category_id"] = winner["budget_category_id"]
