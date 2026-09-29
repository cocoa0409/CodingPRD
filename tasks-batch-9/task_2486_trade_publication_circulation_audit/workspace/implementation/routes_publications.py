"""Publications, qualification rules, digital snapshot creation, sweep reads."""
from flask import Blueprint

import calc
import validation as V
from auth import (OPERATOR_ROLES, ROLE_CIRCULATION_AUDITOR,
                  ROLE_CIRCULATION_MANAGER, ROLE_PUBLISHER_EXECUTIVE, endpoint)
from envelope import created, ok, paginate
from errors import ApiError
from lookups import get_publication
from store import base_record, collection_sorted, db, now, serialize

publications_bp = Blueprint("publications", __name__)

PUB_READ_ROLES = OPERATOR_ROLES
HYGIENE_READ_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_CIRCULATION_AUDITOR,
                      ROLE_PUBLISHER_EXECUTIVE)


# --------------------------------------------------------------------------
# POST /circulation/publications
# --------------------------------------------------------------------------
@publications_bp.route("/circulation/publications", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_publication():
    payload = V.body()
    fields = V.parse(payload, [
        V.f_str("name", max_len=200),
        V.f_enum("frequency", V.FREQUENCIES),
        V.f_str("industry_code", max_len=40),
        V.f_int("qualification_validity_months", required=False, minimum=1, maximum=60, default=36),
        V.f_int("renewal_grace_days", required=False, minimum=0, maximum=365, default=90),
        V.f_int("source_doc_retention_months", required=False, minimum=1, maximum=120, default=36),
        V.f_pct("undeliverable_restrict_pct", required=False, default=V.round_half_up("5.00", 2)),
        V.f_pct("materiality_pct", required=False, default=V.round_half_up("2.00", 2)),
        V.f_pct("controlled_cap_pct", required=False, maximum="99.00",
                default=V.round_half_up("25.00", 2)),
    ])

    pub = base_record()
    pub.update({
        "name": fields["name"],
        "frequency": fields["frequency"],
        "industry_code": fields["industry_code"],
        "qualification_validity_months": fields["qualification_validity_months"],
        "renewal_grace_days": fields["renewal_grace_days"],
        "source_doc_retention_months": fields["source_doc_retention_months"],
        "undeliverable_restrict_pct": fields["undeliverable_restrict_pct"],
        "materiality_pct": fields["materiality_pct"],
        "controlled_cap_pct": fields["controlled_cap_pct"],
        "copies_on_file_total": 0,
        "paid_copies_on_file": 0,
        "qualified_non_paid_copies_on_file": 0,
        "controlled_copies_on_file": 0,
        "deliverable_copies": 0,
        "undeliverable_copies": 0,
        "removed_copies": 0,
        "undeliverable_pct": V.round_half_up("0.00", 2),
        "open_material_findings_count": 0,
        "open_critical_findings_count": 0,
        "audit_posture": "OPEN",
    })
    db.publications[pub["id"]] = pub
    return created(serialize(pub))


@publications_bp.route("/circulation/publications/<pub_id>", methods=["GET"])
@endpoint(*PUB_READ_ROLES)
def read_publication(pub_id):
    return ok(serialize(get_publication(pub_id)))


# --------------------------------------------------------------------------
# qualification rules
# --------------------------------------------------------------------------
@publications_bp.route("/circulation/publications/<pub_id>/qualification-rules", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_qualification_rule(pub_id):
    pub = get_publication(pub_id)
    payload = V.body()
    fields = V.parse(payload, [
        V.f_enum("dimension", V.RULE_DIMENSIONS),
        V.f_strlist("allowed_values", min_items=1, max_items=20),
        V.f_int("points", minimum=0, maximum=100),
        V.f_bool("is_mandatory", required=False, default=False),
    ])

    existing = calc.rules_for(pub["id"])
    if fields["dimension"] in existing:
        raise ApiError("ERR_RULE_DIMENSION_EXISTS",
                       "A %s rule already exists for this publication." % fields["dimension"])

    rule = base_record()
    rule.update({
        "publication_id": pub["id"],
        "dimension": fields["dimension"],
        "allowed_values": fields["allowed_values"],
        "points": fields["points"],
        "is_mandatory": fields["is_mandatory"],
    })
    db.qualification_rules[rule["id"]] = rule
    return created(serialize(rule))


@publications_bp.route("/circulation/publications/<pub_id>/qualification-rules", methods=["GET"])
@endpoint(*PUB_READ_ROLES)
def list_qualification_rules(pub_id):
    pub = get_publication(pub_id)
    dimension = V.filter_enum("dimension", V.RULE_DIMENSIONS)
    rows = [r for r in db.qualification_rules.values() if r["publication_id"] == pub["id"]]
    if dimension:
        rows = [r for r in rows if r["dimension"] == dimension]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# digital audience snapshots  (PRD 3.6)
# --------------------------------------------------------------------------
@publications_bp.route("/circulation/publications/<pub_id>/digital-snapshots", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_digital_snapshot(pub_id):
    pub = get_publication(pub_id)
    payload = V.body()

    def cross(values):
        if values["newsletter_unique_opens"] > values["newsletter_sends"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "newsletter_unique_opens may not exceed newsletter_sends.")

    fields = V.parse(payload, [
        V.f_dt("window_start"),
        V.f_dt("window_end"),
        V.f_int("website_unique_visitors", minimum=0),
        V.f_int("newsletter_sends", minimum=0),
        V.f_int("newsletter_unique_opens", minimum=0),
        V.f_pct("overlap_pct", required=False, default=V.round_half_up("15.00", 2)),
        V.f_enum("source", V.SNAPSHOT_SOURCES),
    ], cross=cross)

    if not fields["window_start"] < fields["window_end"]:
        raise ApiError("ERR_INVALID_PERIOD_RANGE",
                       "window_start must be strictly before window_end.")
    if fields["window_end"] > now():
        raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                       "The measurement window has not closed yet.")

    gross, dedup = calc.combined_reach(
        fields["website_unique_visitors"], fields["newsletter_unique_opens"],
        fields["overlap_pct"])

    snap = base_record()
    snap.update({
        "publication_id": pub["id"],
        "window_start": fields["window_start"],
        "window_end": fields["window_end"],
        "website_unique_visitors": fields["website_unique_visitors"],
        "newsletter_sends": fields["newsletter_sends"],
        "newsletter_unique_opens": fields["newsletter_unique_opens"],
        "overlap_pct": fields["overlap_pct"],
        "source": fields["source"],
        "combined_reach_gross": gross,
        "combined_reach_deduplicated": dedup,
        "status": "RECORDED",
        "validated_by_user_id": None,
    })
    db.snapshots[snap["id"]] = snap
    return created(serialize(snap))


@publications_bp.route("/circulation/publications/<pub_id>/digital-snapshots", methods=["GET"])
@endpoint(*PUB_READ_ROLES)
def list_digital_snapshots(pub_id):
    pub = get_publication(pub_id)
    status = V.filter_enum("status", V.SNAPSHOT_STATUSES)
    rows = [s for s in db.snapshots.values() if s["publication_id"] == pub["id"]]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# hygiene run listing (newest first, PRD 3.5)
# --------------------------------------------------------------------------
@publications_bp.route("/circulation/publications/<pub_id>/hygiene-runs", methods=["GET"])
@endpoint(*HYGIENE_READ_ROLES)
def list_hygiene_runs(pub_id):
    pub = get_publication(pub_id)
    run_type = V.filter_enum("run_type", V.RUN_TYPES)
    rows = [r for r in db.hygiene_runs.values() if r["publication_id"] == pub["id"]]
    if run_type:
        rows = [r for r in rows if r["run_type"] == run_type]
    return paginate(collection_sorted(rows, newest_first=True))
