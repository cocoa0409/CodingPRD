"""Consent-aware record locator disclosure engine (PRD 3.7)."""
from db import clock, db, parse_iso
from errors import ApiError
from services import repo
from services.matching import score_pair
from services.precision import dec, out

NON_PARTICIPATING = ("SUSPENDED", "WITHDRAWN", "TERMINATED")
SEGMENTING_PURPOSES = ("PAYMENT", "OPERATIONS")


def candidate_records():
    rows = []
    for record in repo.all_rows("patient_records"):
        if record["match_state"] != "CLUSTERED":
            continue
        cluster = repo.get("clusters", record["cluster_id"])
        if cluster is None or cluster["status"] != "ACTIVE":
            continue
        rows.append(record)
    return rows


def resolve_cluster(config, demographics):
    """Step one: score every candidate and pick the eligible best."""
    threshold = dec(config["auto_link_threshold"])
    scored = []
    top = None
    for record in candidate_records():
        score, _variant, _agreements = score_pair(config, demographics, record)
        if top is None or score > top:
            top = score
        scored.append((score, record))
    eligible = [pair for pair in scored if pair[0] >= threshold]
    if not eligible:
        return None, top
    eligible.sort(key=lambda pair: (pair[1]["created_at"], pair[1]["_seq"]))
    eligible.sort(key=lambda pair: pair[0], reverse=True)
    return eligible[0][1], top


def governing_directives(cluster_id, querying_participant_id):
    """Step three: the applicable, ordered directive set."""
    moment = clock()
    rows = []
    for directive in repo.where("directives", cluster_id=cluster_id, status="ACTIVE"):
        effective = parse_iso(directive["effective_from"])
        if effective is None or effective > moment:
            continue
        if directive["scope"] == "SINGLE_PARTICIPANT":
            if directive["scoped_participant_id"] != querying_participant_id:
                continue
        rows.append(directive)
    rows.sort(
        key=lambda d: (parse_iso(d["effective_from"]), d["created_at"], d["_seq"]),
        reverse=True,
    )
    rows.sort(key=lambda d: 0 if d["scope"] == "SINGLE_PARTICIPANT" else 1)
    return rows


def base_decision_for(policy, directives):
    governing = None
    for directive in directives:
        if directive["directive_type"] in ("OPT_IN", "OPT_OUT"):
            governing = directive
            break
    if governing is not None:
        return governing["directive_type"], governing["id"]
    if policy["model"] == "OPT_OUT" and policy["default_share_for_treatment"]:
        return "OPT_IN", None
    return "OPT_OUT", None


def suppressed_categories(policy, directives, purpose_of_use):
    segmented = set(policy["sensitive_categories_segmented"] or [])
    restricted = set()
    for directive in directives:
        if directive["directive_type"] == "SENSITIVE_CATEGORY_RESTRICTION":
            restricted |= set(directive["restricted_categories"] or [])
    suppressed = restricted & segmented
    if purpose_of_use in SEGMENTING_PURPOSES:
        suppressed |= segmented
    return suppressed


def conduit_override(participant, purpose_of_use):
    if purpose_of_use != "PUBLIC_HEALTH":
        return False
    if participant["org_type"] != "PUBLIC_HEALTH":
        return False
    for subscription in repo.participant_subscriptions(participant["id"]):
        if (
            subscription["subscription_scope"] == "PUBLIC_HEALTH_CONDUIT"
            and subscription["status"] == "ACTIVE"
        ):
            return True
    return False


def classify(member, emergency, base_decision, conduit, suppressed, purpose_of_use):
    """Step five classification chain, applied strictly in order."""
    contributor = repo.participant(member["participant_id"])
    if contributor is not None and contributor["onboarding_status"] in NON_PARTICIPATING:
        return "WITHHELD", "CONTRIBUTOR_NOT_PARTICIPATING"
    if emergency:
        return "BREAK_GLASS_DISCLOSED", None
    if base_decision == "OPT_OUT" and not conduit:
        return "WITHHELD", "OPT_OUT"
    hits = set(member["sensitive_categories"] or []) & suppressed
    if hits:
        if purpose_of_use in SEGMENTING_PURPOSES:
            return "WITHHELD", "PURPOSE_RESTRICTED"
        return "WITHHELD", "SENSITIVE_CATEGORY"
    return "DISCLOSED", None


def decide(disclosed, withheld, emergency, base_decision, conduit):
    """Step six, first matching clause wins."""
    if emergency:
        return "PERMITTED_EMERGENCY"
    if base_decision == "OPT_OUT" and not conduit and disclosed == 0:
        return "DENIED_OPT_OUT"
    if conduit and base_decision == "OPT_OUT" and withheld == 0:
        return "PERMITTED_PUBLIC_HEALTH"
    if disclosed > 0 and withheld > 0:
        return "PARTIAL_SEGMENTED"
    if disclosed == 0 and withheld > 0:
        return "DENIED_SEGMENTED"
    return "PERMITTED"


def evaluate(participant, config, policy, demographics, purpose_of_use, session):
    """Runs steps one through six and returns the query outcome plus the audit plan."""
    chosen, top = resolve_cluster(config, demographics)
    outcome = {
        "cluster_id": None,
        "top_candidate_score": out(top) if top is not None else None,
        "governing_policy_id": None,
        "governing_directive_id": None,
        "consent_decision": "NO_MATCH",
        "disclosed_record_count": 0,
        "withheld_record_count": 0,
        "withheld_categories": [],
    }
    if chosen is None:
        return outcome, [], None

    cluster = repo.get("clusters", chosen["cluster_id"])
    outcome["cluster_id"] = cluster["id"]
    outcome["governing_policy_id"] = policy["id"]

    directives = governing_directives(cluster["id"], participant["id"])
    base_decision, governing_directive_id = base_decision_for(policy, directives)
    outcome["governing_directive_id"] = governing_directive_id

    if session is not None and session["cluster_id"] != cluster["id"]:
        # A cited session covering a different cluster rejects the query.
        raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")
    emergency = session is not None
    conduit = conduit_override(participant, purpose_of_use)
    suppressed = suppressed_categories(policy, directives, purpose_of_use)

    plan = []
    disclosed = 0
    withheld = 0
    withheld_categories = set()
    for member in repo.cluster_members(cluster["id"]):
        action, reason = classify(
            member, emergency, base_decision, conduit, suppressed, purpose_of_use
        )
        hits = sorted(set(member["sensitive_categories"] or []) & suppressed)
        if action == "WITHHELD":
            withheld += 1
            withheld_categories |= set(hits)
        else:
            disclosed += 1
        plan.append(
            {
                "record_id": member["id"],
                "disclosing_participant_id": member["participant_id"],
                "action": action,
                "suppression_reason": reason,
                "sensitive_category_hit": hits,
            }
        )

    outcome["disclosed_record_count"] = disclosed
    outcome["withheld_record_count"] = withheld
    outcome["withheld_categories"] = sorted(withheld_categories)
    outcome["consent_decision"] = decide(
        disclosed, withheld, emergency, base_decision, conduit
    )
    return outcome, plan, cluster
