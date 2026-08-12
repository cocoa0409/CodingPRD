"""Cross-entity cascade helpers: episode bubble-up, contract termination,
opportunity release, serializers keyed by entity."""
import db
import util


def evaluate_episode_bubbleup(episode_id):
    """Episode AIRED -> VERIFIED bubble-up per SCAFFOLD state machine note."""
    ep = db.episodes.get(episode_id)
    if ep is None or ep["status"] != "AIRED":
        return
    ep_contracts = [c for c in db.contracts.values() if c["episode_id"] == episode_id]
    if not ep_contracts:
        return
    if not all(c["status"] in ("SETTLED", "TERMINATED") for c in ep_contracts):
        return
    ep_reports = [r for r in db.airing_reports.values() if r["episode_id"] == episode_id]
    if not all(r["status"] == "VERIFIED" for r in ep_reports):
        return
    ep["status"] = "VERIFIED"
    util.touch(ep)


def proposal_opportunity(proposal):
    return db.opportunities.get(proposal["opportunity_id"])


def release_opportunity_to_identified(proposal):
    """PITCHED -> IDENTIFIED on reject / withdraw."""
    opp = proposal_opportunity(proposal)
    if opp is not None and opp["status"] == "PITCHED":
        opp["status"] = "IDENTIFIED"
        util.touch(opp)


def reserve_opportunity(proposal):
    """PITCHED -> RESERVED on contract creation."""
    opp = proposal_opportunity(proposal)
    if opp is not None and opp["status"] == "PITCHED":
        opp["status"] = "RESERVED"
        util.touch(opp)


def unreserve_opportunity(proposal):
    """RESERVED -> IDENTIFIED on contract termination."""
    opp = proposal_opportunity(proposal)
    if opp is not None and opp["status"] == "RESERVED":
        opp["status"] = "IDENTIFIED"
        util.touch(opp)


def void_shipment_continuity(shipment_id):
    """ContinuityRecord LOGGED -> VOID for records referencing the shipment."""
    for rec in db.continuity_records.values():
        if rec["shipment_id"] == shipment_id and rec["status"] == "LOGGED":
            rec["status"] = "VOID"


def brief_brand(brief):
    return db.brands.get(brief["brand_id"])


def contract_brand(contract):
    prop = db.proposals.get(contract["proposal_id"])
    if prop is None:
        return None
    brief = db.briefs.get(prop["brief_id"])
    if brief is None:
        return None
    return db.brands.get(brief["brand_id"])


def contract_episode(contract):
    return db.episodes.get(contract["episode_id"])
