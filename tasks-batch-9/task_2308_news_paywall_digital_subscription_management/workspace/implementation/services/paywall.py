"""Rule selection and the access decision (PRD 3.3)."""
import config
from db import db
from response import touch
from services import engagement
from services.entitlement import entitlement_source
from services.events import create_event


def specificity_score(content_type_match, section_match, propensity_band_match):
    score = 0
    if content_type_match != "ANY":
        score += 100
    if section_match != "ANY":
        score += 10
    if propensity_band_match != "ANY":
        score += 1
    return score


def ranked_rules(rows):
    """specificity DESC, priority ASC, created_at ASC - never id."""
    return sorted(rows, key=lambda r: (-r["specificity_score"], r["priority"], r["_seq"]))


def select_rule(article, reader):
    candidates = [
        rule
        for rule in db.paywall_rules.values()
        if rule["status"] == "ACTIVE"
        and rule["content_type_match"] in (article["content_type"], "ANY")
        and rule["section_match"] in (article["section"], "ANY")
        and rule["propensity_band_match"] in (reader["propensity_band"], "ANY")
    ]
    if not candidates:
        return None, "METER", config.SITE_DEFAULT_METER_ALLOWANCE, None
    selected = ranked_rules(candidates)[0]
    override = selected["meter_allowance_override"]
    allowance_base = (
        override if override is not None else config.SITE_DEFAULT_METER_ALLOWANCE
    )
    return selected, selected["action"], allowance_base, selected["id"]


def access_decision(reader, article):
    """Returns the single ReaderEvent that carries the verdict."""
    meter_rolled = engagement.maybe_reset_meter_period(reader)
    reader_dirty = meter_rolled

    decision = None
    meter_index = None
    effective_allowance = None
    applied_rule_id = None

    if article["access_class"] == "OPEN":
        decision = "GRANTED_FREE"
    elif entitlement_source(reader) != "NONE":
        decision = "GRANTED_ENTITLED"
    elif article["access_class"] == "PREMIUM":
        decision = "BLOCKED_PAYWALL"
    else:
        _rule, action, allowance_base, applied_rule_id = select_rule(article, reader)
        if action == "ALLOW_FREE":
            decision = "GRANTED_FREE"
        elif action == "HARD_PAYWALL":
            decision = "BLOCKED_PAYWALL"
        elif action == "REGISTRATION_WALL" and not reader["is_registered"]:
            decision = "BLOCKED_REGISTRATION"
        else:
            effective_allowance = max(
                config.METER_ALLOWANCE_FLOOR,
                allowance_base + config.PROPENSITY_ALLOWANCE_DELTA[reader["propensity_band"]],
            )
            if (
                not reader["is_registered"]
                and reader["metered_distinct_article_count"]
                >= config.REGISTRATION_WALL_THRESHOLD
            ):
                decision = "BLOCKED_REGISTRATION"
            elif article["id"] in reader["metered_article_ids"]:
                decision = "GRANTED_METERED"
                meter_index = reader["metered_article_ids"].index(article["id"]) + 1
            elif reader["metered_distinct_article_count"] >= effective_allowance:
                decision = "BLOCKED_METER"
            else:
                reader["metered_article_ids"].append(article["id"])
                reader["metered_distinct_article_count"] = len(reader["metered_article_ids"])
                decision = "GRANTED_METERED"
                meter_index = reader["metered_distinct_article_count"]
                reader_dirty = True

    granted = decision.startswith("GRANTED")
    event = create_event(
        reader,
        "ARTICLE_VIEW_GRANTED" if granted else "ARTICLE_VIEW_BLOCKED",
        article_id=article["id"],
        applied_rule_id=applied_rule_id,
        decision=decision,
        meter_index=meter_index,
        effective_allowance=effective_allowance,
    )
    if granted:
        if engagement.rescore(reader):
            reader_dirty = True
    if reader_dirty:
        touch(reader)
    return event
