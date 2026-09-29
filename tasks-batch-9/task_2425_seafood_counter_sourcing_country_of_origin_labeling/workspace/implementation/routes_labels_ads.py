"""Case labels (PRD 3.4) and the advertising review fork (PRD 3.6)."""

import calc
import serializers
import services
from auth import counter_scope
from common import base_record, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import opt_enum, opt_id, opt_str, req_datetime, req_enum, req_int, req_str
from web import listing, route

WITHDRAW_REASONS = (
    "SPECIES_MISMATCH",
    "COLD_CHAIN_HOLD",
    "CLAIM_REVOKED",
    "SUPERSEDED",
    "MANUAL",
)
REJECTION_CATEGORIES = ("COOL_MISSING", "FROZEN_DISCLOSURE")
DECISIONS = ("CLEAR", "REJECT")

READ_ROLES = ("ChainAdmin", "SeafoodManager", "ComplianceOfficer", "MerchandisingLead")


def resolve_label(label_id):
    label = db.case_labels.get(label_id)
    if label is not None:
        lot = db.lots.get(label["lot_id"])
        if lot is not None:
            counter_scope(lot["counter_id"])
    else:
        fail("ERR_CASE_LABEL_NOT_FOUND")
    return label


def resolve_item(item_id):
    item = db.ad_items.get(item_id)
    if item is None:
        fail("ERR_AD_ITEM_NOT_FOUND")
    return item


# --------------------------------------------------------------------------
# case labels
# --------------------------------------------------------------------------

@route("/case-labels", methods=["POST"], roles=("SeafoodManager",))
def publish_label(body):
    raw_lot = opt_id(body, "lot_id")
    raw_certification = opt_id(body, "certification_id")

    lot = None
    if raw_lot is not None:
        lot = db.lots.get(raw_lot)
        if lot is not None:
            counter_scope(lot["counter_id"])
    if raw_lot is not None and lot is None:
        fail("ERR_LOT_NOT_FOUND")
    certification = None
    if raw_certification is not None:
        certification = db.certifications.get(raw_certification)
        if certification is None:
            fail("ERR_CERTIFICATION_NOT_FOUND")

    lot_id = req_str(body, "lot_id")
    expected_lot_version = req_int(body, "expected_lot_version")
    certification_id = opt_str(body, "certification_id")

    if expected_lot_version != lot["version"]:
        fail("ERR_STALE_LOT_VERSION")

    counter = services.lot_counter(lot)
    if counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")
    if services.counter_has_open_excursion(counter["id"]):
        fail("ERR_OPEN_EXCURSION_BLOCKS")

    if certification is not None:
        services.check_claim(
            certification, lot["counter_id"], lot["supplier_id"], lot["species_id"]
        )

    species = db.species.get(lot["species_id"])
    statements = calc.label_statements(lot, species, certification)

    for previous in services.published_labels_for_lot(lot["id"]):
        services.withdraw_label(previous, "SUPERSEDED")

    record = base_record("case_label")
    record.update(
        {
            "lot_id": lot_id,
            "certification_id": certification_id,
            "display_market_name": statements["display_market_name"],
            "origin_statement": statements["origin_statement"],
            "production_method_statement": statements["production_method_statement"],
            "frozen_disclosure_statement": statements["frozen_disclosure_statement"],
            "sustainability_claim_text": statements["sustainability_claim_text"],
            "status": "PUBLISHED",
            "withdraw_reason": None,
            "published_at": db.clock,
            "withdrawn_at": None,
        }
    )
    db.case_labels[record["id"]] = record
    touch(lot)
    return obj_result(serializers.case_label, record, 201)


@route("/case-labels/<label_id>", methods=["GET"], roles=READ_ROLES)
def get_label(body, label_id):
    return obj_result(serializers.case_label, resolve_label(label_id))


@route("/case-labels", methods=["GET"], roles=READ_ROLES)
def list_labels(body):
    return listing(
        serializers.case_label,
        list(db.case_labels.values()),
        string_fields=("lot_id", "certification_id", "status", "withdraw_reason"),
    )


@route(
    "/case-labels/<label_id>/withdraw",
    methods=["POST"],
    roles=("SeafoodManager", "ComplianceOfficer"),
)
def withdraw_label_endpoint(body, label_id):
    label = resolve_label(label_id)
    reason = req_enum(body, "reason", WITHDRAW_REASONS)

    if label["status"] != "PUBLISHED":
        fail("ERR_CASE_LABEL_STATE_INVALID")

    # An operator-initiated withdrawal carries no cascade: PRD 3.4 attaches the
    # destruction, cold-chain and claim-revocation hops to the system-driven
    # withdrawals only.
    services.withdraw_label(label, reason, system=False)
    return obj_result(serializers.case_label, label)


# --------------------------------------------------------------------------
# advertised items
# --------------------------------------------------------------------------

@route("/ad-items", methods=["POST"], roles=("MerchandisingLead",))
def draft_ad(body):
    raw_counter = opt_id(body, "counter_id")
    raw_lot = opt_id(body, "lot_id")
    raw_certification = opt_id(body, "certification_id")

    counter = None
    if raw_counter is not None:
        counter = db.counters.get(raw_counter)
        if counter is None:
            fail("ERR_COUNTER_NOT_FOUND")
    lot = None
    if raw_lot is not None:
        lot = db.lots.get(raw_lot)
        if lot is None:
            fail("ERR_LOT_NOT_FOUND")
    certification = None
    if raw_certification is not None:
        certification = db.certifications.get(raw_certification)
        if certification is None:
            fail("ERR_CERTIFICATION_NOT_FOUND")

    counter_id = req_str(body, "counter_id")
    lot_id = req_str(body, "lot_id")
    certification_id = opt_str(body, "certification_id")
    headline = req_str(body, "headline")
    ad_start_at = req_datetime(body, "ad_start_at")
    ad_end_at = req_datetime(body, "ad_end_at")

    if counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")

    if certification is not None:
        services.check_claim(
            certification, lot["counter_id"], lot["supplier_id"], lot["species_id"]
        )

    if not ad_end_at > ad_start_at:
        fail("ERR_AD_WINDOW_INVALID")

    for other in db.ad_items.values():
        if other["lot_id"] != lot_id:
            continue
        if other["status"] not in ("DRAFT", "APPROVED", "PUBLISHED"):
            continue
        if ad_start_at < other["ad_end_at"] and other["ad_start_at"] < ad_end_at:
            fail("ERR_AD_WINDOW_OVERLAP")

    record = base_record("ad_item")
    record.update(
        {
            "counter_id": counter_id,
            "lot_id": lot_id,
            "certification_id": certification_id,
            "headline": headline,
            "ad_start_at": ad_start_at,
            "ad_end_at": ad_end_at,
            "cool_statement": None,
            "status": "DRAFT",
            "cool_review_status": "COOL_PENDING",
            "claim_review_status": "CLAIM_PENDING",
            "cool_reviewer_user_id": None,
            "claim_reviewer_user_id": None,
            "retract_reason": None,
        }
    )
    db.ad_items[record["id"]] = record
    return obj_result(serializers.ad_item, record, 201)


@route("/ad-items/<item_id>", methods=["GET"], roles=READ_ROLES)
def get_ad(body, item_id):
    return obj_result(serializers.ad_item, resolve_item(item_id))


@route("/ad-items", methods=["GET"], roles=READ_ROLES)
def list_ads(body):
    return listing(
        serializers.ad_item,
        list(db.ad_items.values()),
        string_fields=("counter_id", "lot_id", "certification_id", "status"),
    )


@route("/ad-items/<item_id>/clear-cool", methods=["POST"], roles=("ComplianceOfficer",))
def clear_cool(body, item_id):
    from flask import g

    item = resolve_item(item_id)
    decision = req_enum(body, "decision", DECISIONS)
    rejection_category = opt_enum(body, "rejection_category", REJECTION_CATEGORIES)
    opt_str(body, "note")
    if decision == "REJECT" and rejection_category is None:
        fail("ERR_INVALID_REQUEST", "rejection_category is required when decision is REJECT.")

    if item["status"] != "DRAFT" or item["cool_review_status"] != "COOL_PENDING":
        fail("ERR_AD_ITEM_STATE_INVALID")

    lot = db.lots.get(item["lot_id"])
    counter = db.counters.get(item["counter_id"])
    if decision == "CLEAR":
        if lot is None or lot["intake_status"] not in ("CASED", "HELD"):
            fail("ERR_AD_ITEM_STATE_INVALID")
        species = db.species.get(lot["species_id"])
        item["cool_statement"] = calc.cool_statement(lot, species)
        item["cool_review_status"] = "COOL_CLEARED"
        item["cool_reviewer_user_id"] = g.uid
        services.join_ad_review(item)
        touch(item)
    else:
        item["cool_review_status"] = "COOL_REJECTED"
        item["cool_reviewer_user_id"] = g.uid
        services.join_ad_review(item)
        touch(item)
        services.create_violation(
            counter,
            item["lot_id"],
            rejection_category,
            "Advertisement country-of-origin review rejected: %s." % rejection_category,
        )
    return obj_result(serializers.ad_item, item)


@route("/ad-items/<item_id>/clear-claim", methods=["POST"], roles=("ComplianceOfficer",))
def clear_claim(body, item_id):
    from flask import g

    item = db.ad_items.get(item_id)
    if item is not None and item["cool_reviewer_user_id"] == g.uid:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if item is None:
        fail("ERR_AD_ITEM_NOT_FOUND")

    decision = req_enum(body, "decision", DECISIONS)
    opt_str(body, "note")

    if item["status"] != "DRAFT" or item["claim_review_status"] != "CLAIM_PENDING":
        fail("ERR_AD_ITEM_STATE_INVALID")

    lot = db.lots.get(item["lot_id"])
    counter = db.counters.get(item["counter_id"])
    if decision == "CLEAR":
        if item["certification_id"] is not None:
            certification = db.certifications.get(item["certification_id"])
            if certification is None:
                fail("ERR_CERTIFICATION_NOT_FOUND")
            services.check_claim(
                certification,
                lot["counter_id"] if lot else None,
                lot["supplier_id"] if lot else None,
                lot["species_id"] if lot else None,
            )
        item["claim_review_status"] = "CLAIM_CLEARED"
        item["claim_reviewer_user_id"] = g.uid
        services.join_ad_review(item)
        touch(item)
    else:
        item["claim_review_status"] = "CLAIM_REJECTED"
        item["claim_reviewer_user_id"] = g.uid
        services.join_ad_review(item)
        touch(item)
        services.create_violation(
            counter,
            item["lot_id"],
            "UNSUBSTANTIATED_CLAIM",
            "Advertisement sustainability-claim review rejected.",
        )
    return obj_result(serializers.ad_item, item)


@route("/ad-items/<item_id>/publish", methods=["POST"], roles=("MerchandisingLead",))
def publish_ad(body, item_id):
    item = resolve_item(item_id)

    if item["status"] != "APPROVED":
        fail("ERR_AD_ITEM_STATE_INVALID")

    counter = db.counters.get(item["counter_id"])
    if counter is not None:
        if counter["posture"] == "SUSPENDED":
            fail("ERR_COUNTER_SUSPENDED")
        if counter["posture"] == "RESTRICTED":
            fail("ERR_COUNTER_RESTRICTED")

    if not services.published_labels_for_lot(item["lot_id"]):
        fail("ERR_AD_ITEM_STATE_INVALID")

    item["status"] = "PUBLISHED"
    touch(item)
    return obj_result(serializers.ad_item, item)


@route("/ad-items/<item_id>/close", methods=["POST"], roles=("MerchandisingLead",))
def close_ad(body, item_id):
    item = resolve_item(item_id)

    if item["status"] != "PUBLISHED" or db.clock < item["ad_end_at"]:
        fail("ERR_AD_ITEM_STATE_INVALID")

    item["status"] = "CLOSED"
    touch(item)
    return obj_result(serializers.ad_item, item)


@route(
    "/ad-items/<item_id>/retract",
    methods=["POST"],
    roles=("MerchandisingLead", "ComplianceOfficer"),
)
def retract_ad_endpoint(body, item_id):
    item = resolve_item(item_id)
    req_str(body, "reason")

    if item["status"] != "PUBLISHED":
        fail("ERR_AD_ITEM_STATE_INVALID")

    services.retract_ad(item, "MANUAL")
    return obj_result(serializers.ad_item, item)
