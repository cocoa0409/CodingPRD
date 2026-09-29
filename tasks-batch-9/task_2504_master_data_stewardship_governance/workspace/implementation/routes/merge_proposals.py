"""Duplicate resolution: matching, review, survivorship (PRD 3.7)."""

from flask import Blueprint, g

import db
import response
import services
import validation as v
from auth import endpoint, entitle
from errors import fail

bp = Blueprint("merge_proposals", __name__)

STATUSES = ("PROPOSED", "UNDER_REVIEW", "MERGED", "REJECTED", "REWORK")
DECISIONS = ("MERGE", "REJECT", "REWORK")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")


@bp.post("/mdm/merge-proposals")
@endpoint("DataSteward", "DataOwner")
def create_proposal():
    body = v.body()
    survivor_id = v.req_str(body, "survivor_master_record_id", 1)
    duplicate_id = v.req_str(body, "duplicate_master_record_id", 1)
    name_similarity_pct = v.req_num(body, "name_similarity_pct", 0, 100)
    key_overlap_pct = v.req_num(body, "key_overlap_pct", 0, 100)

    survivor = db.resolve(db.store.master_records, survivor_id,
                          "ERR_MASTER_RECORD_NOT_FOUND")
    duplicate = db.resolve(db.store.master_records, duplicate_id,
                           "ERR_MASTER_RECORD_NOT_FOUND")

    domain = db.store.domains[survivor["domain_id"]]
    entitle(domain)

    if survivor["domain_id"] != duplicate["domain_id"]:
        fail("ERR_CROSS_DOMAIN_MERGE", "The two candidate records belong to different domains.")
    if survivor["id"] == duplicate["id"]:
        fail("ERR_SELF_MERGE", "The two candidate records must be distinct rows.")

    score = services.match_score(survivor, duplicate, name_similarity_pct, key_overlap_pct)
    if score < services.MATCH_CREATION_FLOOR:
        fail("ERR_MATCH_SCORE_BELOW_FLOOR",
             "The computed match_score falls below the 45.00 proposal floor.")

    proposal = db.create("MergeProposal", {
        "domain_id": domain["id"],
        "survivor_master_record_id": survivor["id"],
        "duplicate_master_record_id": duplicate["id"],
        "proposer_steward_id": g.user_id,
        "reviewer_steward_id": None,
        "name_similarity_pct": name_similarity_pct,
        "key_overlap_pct": key_overlap_pct,
        "match_score": score,
        "match_confidence": services.match_confidence(score),
        "status": "PROPOSED",
        "effective_survivor_master_record_id": None,
        "survivor_swapped": False,
        "survivorship_variant": None,
        "survivorship_field_map": None,
        "rework_count": 0,
        "override_justification": None,
        "decided_at": None,
    })
    db.store.merge_proposals[proposal["id"]] = proposal
    return response.created(proposal)


@bp.get("/mdm/merge-proposals")
@endpoint(*READERS)
def list_proposals():
    limit, offset = v.pagination()
    filters = [
        ("domain_id", "domain_id"),
        ("survivor_master_record_id", "survivor_master_record_id"),
        ("duplicate_master_record_id", "duplicate_master_record_id"),
        ("effective_survivor_master_record_id", "effective_survivor_master_record_id"),
        ("proposer_steward_id", "proposer_steward_id"),
        ("reviewer_steward_id", "reviewer_steward_id"),
    ]
    rows = db.ordered(db.store.merge_proposals)
    for arg, field in filters:
        value = v.str_filter(arg)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = v.enum_filter("status", STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/merge-proposals/<proposal_id>")
@endpoint(*READERS)
def read_proposal(proposal_id):
    proposal = db.resolve(db.store.merge_proposals, proposal_id,
                          "ERR_MERGE_PROPOSAL_NOT_FOUND")
    return response.entity(proposal)


@bp.post("/mdm/merge-proposals/<proposal_id>/review")
@endpoint("DataSteward", "DataOwner")
def review_proposal(proposal_id):
    proposal = db.resolve(db.store.merge_proposals, proposal_id,
                          "ERR_MERGE_PROPOSAL_NOT_FOUND")
    domain = db.store.domains[proposal["domain_id"]]
    entitle(domain)

    if proposal["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "Review is only available from PROPOSED status.")

    proposal["status"] = "UNDER_REVIEW"
    proposal["reviewer_steward_id"] = g.user_id
    db.bump(proposal)
    return response.entity(proposal)


@bp.post("/mdm/merge-proposals/<proposal_id>/decide")
@endpoint("DataOwner")
def decide_proposal(proposal_id):
    proposal = db.resolve(db.store.merge_proposals, proposal_id,
                          "ERR_MERGE_PROPOSAL_NOT_FOUND")
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    rework_note = None
    if decision == "REWORK":
        rework_note = v.req_str(body, "rework_note", 10)
    override_justification = v.opt_str(body, "override_justification", 0)

    domain = db.store.domains[proposal["domain_id"]]
    entitle(domain)

    if proposal["status"] != "UNDER_REVIEW":
        fail("ERR_PROPOSAL_NOT_UNDER_REVIEW", "The proposal is not UNDER_REVIEW.")

    if proposal["proposer_steward_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The steward who proposed the merge may not decide it.")

    if decision == "REJECT":
        proposal["status"] = "REJECTED"
        proposal["decided_at"] = db.now()
        db.bump(proposal)
        return response.entity(proposal)

    if decision == "REWORK":
        proposal["status"] = "REWORK"
        proposal["reviewer_steward_id"] = None
        db.bump(proposal)
        return response.entity(proposal)

    # --- MERGE -------------------------------------------------------------
    if domain["governance_posture"] not in ("OPEN", "RESTRICTED"):
        fail("ERR_DOMAIN_POSTURE_BLOCKED",
             "A FROZEN domain blocks the merge decision.")

    survivor = db.store.master_records[proposal["survivor_master_record_id"]]
    duplicate = db.store.master_records[proposal["duplicate_master_record_id"]]
    if survivor["curation_status"] != "CURATED" or duplicate["curation_status"] != "CURATED":
        fail("ERR_RECORD_NOT_CURATED", "Both candidate records must be CURATED.")

    variant, winner, loser = services.select_survivor(domain, survivor, duplicate)

    winner_source = db.store.source_systems[winner["source_system_id"]]
    if winner_source["status"] != "CERTIFIED":
        fail("ERR_SOURCE_NOT_CERTIFIED",
             "The effective survivor's source system is not CERTIFIED.")

    confidence = proposal["match_confidence"]
    if confidence == "LOW":
        fail("ERR_MATCH_CONFIDENCE_TOO_LOW",
             "A LOW-confidence proposal cannot be merged.")
    if confidence == "MEDIUM":
        if override_justification is None or len(override_justification) < 20:
            fail("ERR_MATCH_CONFIDENCE_TOO_LOW",
                 "A MEDIUM-confidence merge requires an override_justification of at least 20 characters.")

    # Hop 1
    proposal["status"] = "MERGED"
    proposal["decided_at"] = db.now()
    proposal["effective_survivor_master_record_id"] = winner["id"]
    proposal["survivor_swapped"] = winner["id"] != proposal["survivor_master_record_id"]
    proposal["survivorship_variant"] = variant
    if override_justification is not None:
        proposal["override_justification"] = override_justification

    # Hop 2
    proposal["survivorship_field_map"] = services.apply_survivorship(winner, loser)
    db.bump(winner)

    # Hop 3
    loser["curation_status"] = "MERGED_AWAY"
    loser["superseded_by_master_record_id"] = winner["id"]
    if loser["publication_status"] == "PUBLISHED":
        loser["publication_status"] = "RETRACTED"
    db.bump(loser)

    db.bump(proposal)
    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(proposal)


@bp.post("/mdm/merge-proposals/<proposal_id>/rescore")
@endpoint("DataSteward", "DataOwner")
def rescore_proposal(proposal_id):
    proposal = db.resolve(db.store.merge_proposals, proposal_id,
                          "ERR_MERGE_PROPOSAL_NOT_FOUND")
    body = v.body()
    name_similarity_pct = v.req_num(body, "name_similarity_pct", 0, 100)
    key_overlap_pct = v.req_num(body, "key_overlap_pct", 0, 100)

    domain = db.store.domains[proposal["domain_id"]]
    entitle(domain)

    if proposal["status"] != "REWORK":
        fail("ERR_INVALID_STATE_TRANSITION", "Rescoring is only available from REWORK status.")

    survivor = db.store.master_records[proposal["survivor_master_record_id"]]
    duplicate = db.store.master_records[proposal["duplicate_master_record_id"]]
    for record in (survivor, duplicate):
        if record["curation_status"] not in ("CANDIDATE", "CURATED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A candidate record that has been merged away or quarantined cannot participate.")

    score = services.match_score(survivor, duplicate, name_similarity_pct, key_overlap_pct)
    if score < services.MATCH_CREATION_FLOOR:
        fail("ERR_MATCH_SCORE_BELOW_FLOOR",
             "The recomputed match_score falls below the 45.00 floor.")

    proposal["name_similarity_pct"] = name_similarity_pct
    proposal["key_overlap_pct"] = key_overlap_pct
    proposal["match_score"] = score
    proposal["match_confidence"] = services.match_confidence(score)
    proposal["status"] = "PROPOSED"
    proposal["rework_count"] += 1
    db.bump(proposal)
    return response.entity(proposal)
