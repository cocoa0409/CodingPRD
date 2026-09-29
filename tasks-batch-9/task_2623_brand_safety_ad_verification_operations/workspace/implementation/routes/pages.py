"""Pages, the pre-bid placement decision, classifications, review and appeals."""

from urllib.parse import urlsplit

from flask import Blueprint

import calc
import db
import middleware as mw
import response
import services as svc
import validators as v
from errors import fail
from middleware import (
    ROLE_ADVERTISER,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_DISPUTE_OFFICER,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
)
from routes.helpers import build_filters, filtered, respond_list

bp = Blueprint("pages", __name__)

PAGE_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_DISPUTE_OFFICER,
    ROLE_ADVERTISER,
)
CLASSIFICATION_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_PUBLISHER,
    ROLE_DISPUTE_OFFICER,
    ROLE_MEASUREMENT_OPERATOR,
)
APPEAL_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
    ROLE_DISPUTE_OFFICER,
    ROLE_CLASSIFICATION_ANALYST,
)

PAGE_ACCEPTS_CLASSIFICATION = ("UNCLASSIFIED", "MODEL_CLASSIFIED", "HUMAN_CONFIRMED", "RECLASSIFIED")
ATTESTED_PAGE_STATES = ("HUMAN_CONFIRMED", "APPEALED", "RECLASSIFIED")
LIVE_APPEAL_STATES = ("FILED", "MORE_EVIDENCE_REQUIRED")
EFFECTIVE_REVIEW_STATES = ("PENDING_REVIEW", "CONFIRMED", "OVERRIDDEN")


def _derive_domain(url):
    host = urlsplit(url).hostname
    return (host or "").lower()


# --------------------------------------------------------------------------- #
# pages                                                                       #
# --------------------------------------------------------------------------- #
@bp.post("/pages")
def create_page():
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_PUBLISHER)
    payload = mw.body()
    publisher_id = payload.get("publisher_id")
    mw.own_publisher(caller, publisher_id if isinstance(publisher_id, str) else None)
    publisher = svc.require_ref(db.publishers, publisher_id, "ERR_PUBLISHER_NOT_FOUND")
    url = v.req_string(payload, "url", 1, 300)
    if not url.startswith("https://"):
        fail("ERR_INVALID_REQUEST", "url must begin with https://.")
    for existing in db.pages.values():
        if existing["publisher_id"] == publisher["id"] and existing["url"] == url:
            fail("ERR_DUPLICATE_PAGE_URL")
    record = db.new_record(
        {
            "publisher_id": publisher["id"],
            "url": url,
            "domain": _derive_domain(url),
            "classification_state": "UNCLASSIFIED",
            "current_tier": None,
            "current_classification_id": None,
            "latest_category_codes": [],
            "mfa_score": None,
            "mfa_flag": False,
            "appeal_count": 0,
        }
    )
    db.pages[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/pages/<page_id>")
def read_page(page_id):
    caller = mw.require(*PAGE_READERS)
    record = svc.find(db.pages, page_id)
    mw.own_page(caller, record)
    if record is None:
        fail("ERR_PAGE_NOT_FOUND")
    return response.object_response(record)


@bp.get("/pages")
def list_pages():
    caller = mw.require(*PAGE_READERS)
    predicates = build_filters(
        {
            "publisher_id": "publisher_id",
            "current_classification_id": "current_classification_id",
            "classification_state": "classification_state",
        }
    )
    mfa_flag = mw.query_bool("mfa_flag")
    if mfa_flag is not None:
        predicates.append(lambda record: record["mfa_flag"] == mfa_flag)
    if caller.is_publisher:
        predicates.append(lambda record: record["publisher_id"] == caller.user_id)
    return respond_list(filtered(db.pages, predicates))


# --------------------------------------------------------------------------- #
# pre-bid placement decision (PRD section 3.6)                                        #
# --------------------------------------------------------------------------- #
def _publisher_rollup_tier(publisher_id):
    """Pre-bid variant: the worst human-attested tier of the publisher over the
    trailing 30 days; UNRATED when the candidate set is empty."""
    horizon = db.clock_now() - db.days(calc.ROLLUP_WINDOW_DAYS)
    worst = None
    for page in db.ordered(list(db.pages.values())):
        if page["publisher_id"] != publisher_id:
            continue
        if page["classification_state"] not in ATTESTED_PAGE_STATES:
            continue
        effective = db.page_classifications.get(page["current_classification_id"])
        if effective is None:
            continue
        created = db.parse_dt(effective["created_at"])
        if created is None or created < horizon:
            continue
        tier = effective.get("assigned_tier")
        if tier not in calc.TIER_RANK:
            continue
        if worst is None or calc.TIER_RANK[tier] < calc.TIER_RANK[worst]:
            worst = tier
    return worst if worst is not None else calc.TIER_UNRATED


def _candidate_entries(segment, page):
    lists = []
    for slot in ("inclusion_list_id", "exclusion_list_id"):
        pinned = db.inventory_lists.get(segment.get(slot)) if segment.get(slot) else None
        if pinned is not None and pinned["status"] == "PUBLISHED":
            lists.append(pinned["id"])
    if not lists:
        return []
    categories = page.get("latest_category_codes") or []
    candidates = []
    for entry in db.ordered(list(db.list_entries.values())):
        if entry["list_id"] not in lists:
            continue
        kind = entry["entry_type"]
        value = entry["entry_value"]
        matched = (
            (kind == "PAGE_URL" and value == page["url"])
            or (kind == "DOMAIN" and value == page["domain"])
            or (kind == "PUBLISHER" and value == page["publisher_id"])
            or (kind == "CATEGORY" and value in categories)
        )
        if matched:
            candidates.append(entry)
    # highest specificity first, BLOCK before ALLOW at equal specificity, then
    # earliest created_at; the entry identifier is never a tie-break.
    candidates.sort(
        key=lambda entry: (
            -int(entry["specificity_rank"]),
            0 if entry["action"] == "BLOCK" else 1,
            db.sort_key(entry),
        )
    )
    return candidates


@bp.get("/pages/<page_id>/pre-bid-decision")
def pre_bid_decision(page_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    segment = svc.find(db.pre_bid_segments, mw.query("segment_id"))
    if segment is not None:
        mw.own_campaign(caller, db.campaigns.get(segment["campaign_id"]))
    page = svc.require_path(db.pages, page_id, "ERR_PAGE_NOT_FOUND")
    if segment is None:
        fail("ERR_PRE_BID_SEGMENT_NOT_FOUND")
    # gate zero -- readiness
    if segment["sync_status"] != "SYNCED":
        fail("ERR_SEGMENT_NOT_SYNCED")
    floor_tier = segment["suitability_floor_tier"]
    effective_tier = _publisher_rollup_tier(page["publisher_id"])

    def verdict(decision, reason_code, entry=None):
        return response.object_response(
            {
                "page_id": page["id"],
                "segment_id": segment["id"],
                "decision": decision,
                "reason_code": reason_code,
                "decisive_entry_id": entry["id"] if entry else None,
                "decisive_specificity": entry["entry_type"] if entry else None,
                "effective_tier": effective_tier,
                "floor_tier": floor_tier,
            }
        )

    # gate one -- publisher standing
    publisher = db.publishers.get(page["publisher_id"])
    if publisher is not None and publisher["publisher_status"] in ("RESTRICTED", "DELISTED"):
        return verdict("BLOCK", "PUBLISHER_RESTRICTED")
    # gate two -- list precedence
    candidates = _candidate_entries(segment, page)
    if candidates:
        decisive = candidates[0]
        if decisive["action"] == "BLOCK":
            return verdict("BLOCK", "LIST_EXCLUSION", decisive)
        return verdict("ALLOW_OVERRIDE", "LIST_INCLUSION", decisive)
    # gate three -- the tier floor over the publisher rollup
    if effective_tier == calc.TIER_UNRATED:
        return verdict("BLOCK", "UNRATED_INVENTORY")
    if calc.worse_than(effective_tier, floor_tier):
        return verdict("BLOCK", "BELOW_SUITABILITY_FLOOR")
    return verdict("ALLOW", "MEETS_FLOOR")


# --------------------------------------------------------------------------- #
# page classifications (PRD section 3.3)                                              #
# --------------------------------------------------------------------------- #
def _effective_classification(page):
    return db.page_classifications.get(page.get("current_classification_id"))


def _publish_to_page(page, record):
    page["current_classification_id"] = record["id"]
    page["current_tier"] = record["assigned_tier"]
    page["latest_category_codes"] = list(record["category_codes"])
    page["mfa_score"] = record["mfa_score"]
    page["mfa_flag"] = record["mfa_flag"]


def _apply_mfa_delta(publisher, was_flagged, is_flagged):
    if publisher is None or was_flagged == is_flagged:
        return
    if is_flagged:
        publisher["mfa_page_count"] = int(publisher["mfa_page_count"]) + 1
    else:
        publisher["mfa_page_count"] = max(0, int(publisher["mfa_page_count"]) - 1)
    db.touch(publisher)
    svc.maybe_restrict_publisher(publisher)


@bp.post("/page-classifications")
def create_classification():
    caller = mw.require(ROLE_CLASSIFICATION_ANALYST)
    payload = mw.body()
    # priority 5 -- body reference existence
    page = svc.require_ref(db.pages, payload.get("page_id"), "ERR_PAGE_NOT_FOUND")
    methodology = svc.require_ref(
        db.methodology_versions,
        payload.get("methodology_version_id"),
        "ERR_METHODOLOGY_VERSION_NOT_FOUND",
    )
    # priority 6 -- request well-formedness
    classifier_kind = v.req_enum(payload, "classifier_kind", calc.CLASSIFIER_KIND_CLIENT)
    expected_page_version = v.req_int(payload, "expected_page_version", minimum=0)
    category_codes = v.req_str_list(
        payload,
        "category_codes",
        min_items=0,
        max_items=calc.CATEGORY_CODES_MAX,
        allowed=calc.CATEGORY_SET,
        default=[],
    )
    ad_density_ratio = v.req_decimal(payload, "ad_density_ratio", minimum=0, maximum=1)
    refresh_seconds = v.req_int(payload, "refresh_seconds", minimum=0)
    originality_score = v.req_decimal(payload, "originality_score", minimum=0, maximum=100)
    model_confidence = v.req_decimal(
        payload, "model_confidence", minimum=0, maximum=1, default="1.0"
    )
    # priority 7 -- state reachability
    if page["classification_state"] not in PAGE_ACCEPTS_CLASSIFICATION:
        fail("ERR_INVALID_PAGE_STATE")
    # priority 8 -- page version
    if expected_page_version != int(page["version"]):
        fail("ERR_STALE_PAGE_VERSION")
    # endpoint-local: family mismatch precedes the accreditation guard
    if methodology["standard_family"] != "SUITABILITY":
        fail("ERR_METHODOLOGY_FAMILY_MISMATCH")
    # priority 12 -- lapse evaluation then accreditation standing
    svc.guard_methodology_live(methodology)

    publisher = db.publishers.get(page["publisher_id"])
    sourced_traffic_pct = publisher["sourced_traffic_pct"] if publisher else 0
    # the pinned evaluation order: mfa_score, mfa_flag, base, adjusted, tier
    score, flagged = calc.mfa_score(
        ad_density_ratio, refresh_seconds, sourced_traffic_pct, originality_score
    )
    base, adjusted, tier = calc.risk_scoring(
        category_codes, flagged, classifier_kind, model_confidence
    )
    record = db.new_record(
        {
            "page_id": page["id"],
            "methodology_version_id": methodology["id"],
            "classifier_kind": classifier_kind,
            "category_codes": list(category_codes),
            "model_confidence": calc.plain(model_confidence),
            "ad_density_ratio": calc.plain(ad_density_ratio),
            "refresh_seconds": refresh_seconds,
            "originality_score": calc.plain(originality_score),
            "base_risk_points": calc.num2(base),
            "adjusted_risk_points": calc.num2(adjusted),
            "assigned_tier": tier,
            "mfa_score": calc.num2(score),
            "mfa_flag": flagged,
            "review_state": "PENDING_REVIEW",
            "classifier_user_id": caller.user_id,
            "reviewed_by_user_id": None,
            "review_note": None,
        }
    )
    db.page_classifications[record["id"]] = record
    # supersede the record this write displaces
    displaced = _effective_classification(page)
    if displaced is not None and displaced["review_state"] in EFFECTIVE_REVIEW_STATES:
        displaced["review_state"] = "SUPERSEDED"
        db.touch(displaced)
    was_flagged = bool(page["mfa_flag"])
    _publish_to_page(page, record)
    page["classification_state"] = "MODEL_CLASSIFIED"
    db.touch(page)
    _apply_mfa_delta(publisher, was_flagged, flagged)
    return response.object_response(record, 201)


@bp.get("/page-classifications/<classification_id>")
def read_classification(classification_id):
    caller = mw.require(*CLASSIFICATION_READERS)
    record = svc.find(db.page_classifications, classification_id)
    if record is not None:
        mw.own_page(caller, db.pages.get(record["page_id"]))
    else:
        fail("ERR_PAGE_CLASSIFICATION_NOT_FOUND")
    return response.object_response(record)


@bp.get("/page-classifications")
def list_classifications():
    caller = mw.require(*CLASSIFICATION_READERS)
    predicates = build_filters(
        {
            "page_id": "page_id",
            "methodology_version_id": "methodology_version_id",
            "review_state": "review_state",
            "classifier_kind": "classifier_kind",
        }
    )
    if caller.is_publisher:
        owned = set(
            page["id"] for page in db.pages.values() if page["publisher_id"] == caller.user_id
        )
        predicates.append(lambda record: record["page_id"] in owned)
    return respond_list(filtered(db.page_classifications, predicates))


@bp.post("/page-classifications/<classification_id>/review")
def review_classification(classification_id):
    caller = mw.require(ROLE_CLASSIFICATION_ANALYST)
    record = svc.require_path(
        db.page_classifications, classification_id, "ERR_PAGE_CLASSIFICATION_NOT_FOUND"
    )
    payload = mw.body()
    decision = v.req_enum(payload, "decision", {"CONFIRM", "OVERRIDE"})
    revised = v.req_str_list(
        payload,
        "revised_category_codes",
        min_items=0,
        max_items=calc.CATEGORY_CODES_MAX,
        allowed=calc.CATEGORY_SET,
        default=None,
    )
    review_note = v.opt_string(payload, "review_note")
    page = db.pages.get(record["page_id"])
    # priority 7 -- only the page's currently effective, unreviewed record
    if record["review_state"] != "PENDING_REVIEW":
        fail("ERR_INVALID_CLASSIFICATION_STATE")
    if page is None or page.get("current_classification_id") != record["id"]:
        fail("ERR_INVALID_CLASSIFICATION_STATE")
    if page["classification_state"] != "MODEL_CLASSIFIED":
        fail("ERR_INVALID_CLASSIFICATION_STATE")
    record["reviewed_by_user_id"] = caller.user_id
    record["review_note"] = review_note
    if decision == "CONFIRM":
        record["review_state"] = "CONFIRMED"
    else:
        if revised is None:
            fail("ERR_INVALID_REQUEST", "revised_category_codes is required for an OVERRIDE.")
        if list(revised) == list(record["category_codes"]):
            fail(
                "ERR_INVALID_REQUEST",
                "revised_category_codes must differ from the record's category_codes.",
            )
        publisher = db.publishers.get(page["publisher_id"])
        sourced_traffic_pct = publisher["sourced_traffic_pct"] if publisher else 0
        score, flagged = calc.mfa_score(
            record["ad_density_ratio"],
            record["refresh_seconds"],
            sourced_traffic_pct,
            record["originality_score"],
        )
        # an overridden record is scored as human: never the confidence inflation
        base, adjusted, tier = calc.risk_scoring(
            revised, flagged, "HUMAN", record["model_confidence"]
        )
        record["category_codes"] = list(revised)
        record["mfa_score"] = calc.num2(score)
        record["mfa_flag"] = flagged
        record["base_risk_points"] = calc.num2(base)
        record["adjusted_risk_points"] = calc.num2(adjusted)
        record["assigned_tier"] = tier
        record["review_state"] = "OVERRIDDEN"
        # review republishes only the tier and the categories
        page["current_tier"] = tier
        page["latest_category_codes"] = list(revised)
    db.touch(record)
    page["classification_state"] = "HUMAN_CONFIRMED"
    db.touch(page)
    return response.object_response(record)


# --------------------------------------------------------------------------- #
# appeals (PRD section 3.4)                                                           #
# --------------------------------------------------------------------------- #
def _appeal_publisher_id(appeal):
    classification = db.page_classifications.get(appeal["classification_id"])
    if classification is None:
        return None
    page = db.pages.get(classification["page_id"])
    return page["publisher_id"] if page else None


def _live_appeal_on(classification_id):
    for appeal in db.ordered(list(db.appeals.values())):
        if appeal["classification_id"] == classification_id and appeal["appeal_state"] in (
            LIVE_APPEAL_STATES
        ):
            return appeal
    return None


@bp.post("/appeals")
def file_appeal():
    caller = mw.require(ROLE_PUBLISHER)
    payload = mw.body()
    classification = svc.find(db.page_classifications, payload.get("classification_id"))
    page = db.pages.get(classification["page_id"]) if classification else None
    mw.own_page(caller, page)
    if classification is None:
        fail("ERR_PAGE_CLASSIFICATION_NOT_FOUND")
    if page is None:
        fail("ERR_PAGE_NOT_FOUND")
    reason_code = v.req_enum(payload, "reason_code", calc.APPEAL_REASON_CODES)
    evidence_note = v.req_string(payload, "evidence_note", 1, 1000)
    # priority 7 -- the page must declare the move
    if page["classification_state"] != "HUMAN_CONFIRMED":
        fail("ERR_INVALID_PAGE_STATE")
    # priority 19 -- appeal target currency
    if (
        classification["review_state"] not in ("CONFIRMED", "OVERRIDDEN")
        or page.get("current_classification_id") != classification["id"]
    ):
        fail("ERR_CLASSIFICATION_SUPERSEDED")
    # priority 20 -- a single live appeal per classification
    if _live_appeal_on(classification["id"]) is not None:
        fail("ERR_APPEAL_PENDING")
    # priority 32 -- the 14 day filing window
    created = db.parse_dt(classification["created_at"])
    if created is not None and db.clock_now() > created + db.days(calc.APPEAL_FILING_WINDOW_DAYS):
        fail("ERR_APPEAL_WINDOW_CLOSED")
    record = db.new_record(
        {
            "classification_id": classification["id"],
            "reason_code": reason_code,
            "evidence_note": evidence_note,
            "appeal_state": "FILED",
            "round_no": 1,
            "revised_tier": None,
            "decision_note": None,
            "decided_by_user_id": None,
            "remedy_classification_id": None,
        }
    )
    db.appeals[record["id"]] = record
    page["classification_state"] = "APPEALED"
    page["appeal_count"] = int(page["appeal_count"]) + 1
    db.touch(page)
    return response.object_response(record, 201)


@bp.get("/appeals/<appeal_id>")
def read_appeal(appeal_id):
    caller = mw.require(*APPEAL_READERS)
    record = svc.find(db.appeals, appeal_id)
    if record is not None:
        mw.own_publisher(caller, _appeal_publisher_id(record))
    else:
        fail("ERR_APPEAL_NOT_FOUND")
    return response.object_response(record)


@bp.get("/appeals")
def list_appeals():
    caller = mw.require(*APPEAL_READERS)
    predicates = build_filters(
        {
            "classification_id": "classification_id",
            "remedy_classification_id": "remedy_classification_id",
            "appeal_state": "appeal_state",
            "reason_code": "reason_code",
        }
    )
    if caller.is_publisher:
        predicates.append(lambda record: _appeal_publisher_id(record) == caller.user_id)
    return respond_list(filtered(db.appeals, predicates))


@bp.post("/appeals/<appeal_id>/evidence")
def add_evidence(appeal_id):
    caller = mw.require(ROLE_PUBLISHER)
    record = svc.find(db.appeals, appeal_id)
    if record is not None:
        mw.own_publisher(caller, _appeal_publisher_id(record))
    else:
        fail("ERR_APPEAL_NOT_FOUND")
    payload = mw.body()
    evidence_note = v.req_string(payload, "evidence_note", 1, 1000)
    if record["appeal_state"] != "MORE_EVIDENCE_REQUIRED":
        fail("ERR_INVALID_APPEAL_STATE")
    if int(record["round_no"]) >= calc.APPEAL_MAX_ROUNDS:
        fail("ERR_APPEAL_ROUNDS_EXHAUSTED")
    record["appeal_state"] = "FILED"
    record["round_no"] = int(record["round_no"]) + 1
    record["evidence_note"] = evidence_note
    db.touch(record)
    return response.object_response(record)


def _mint_remedy_classification(disputed, page, revised_tier, officer_user_id):
    """Hop 1 of the overturn cascade: the system attests a remedy record."""
    record = db.new_record(
        {
            "page_id": page["id"],
            "methodology_version_id": disputed["methodology_version_id"],
            "classifier_kind": calc.CLASSIFIER_KIND_APPEAL_REMEDY,
            "category_codes": list(disputed["category_codes"]),
            "model_confidence": disputed["model_confidence"],
            "ad_density_ratio": disputed["ad_density_ratio"],
            "refresh_seconds": disputed["refresh_seconds"],
            "originality_score": disputed["originality_score"],
            "base_risk_points": disputed["base_risk_points"],
            "adjusted_risk_points": disputed["adjusted_risk_points"],
            "assigned_tier": revised_tier,
            "mfa_score": disputed["mfa_score"],
            "mfa_flag": disputed["mfa_flag"],
            "review_state": "CONFIRMED",
            "classifier_user_id": officer_user_id,
            "reviewed_by_user_id": officer_user_id,
            "review_note": None,
        }
    )
    db.page_classifications[record["id"]] = record
    return record


def _overturn_cascade(page):
    """Hops 2, 3 and 4: re-assess claimed batches, then the claims citing them."""
    touched_batches = []
    for batch in db.ordered(list(db.measurement_batches.values())):
        if batch["page_id"] != page["id"] or batch["settlement_status"] != "CLAIMED":
            continue
        svc.assess_batch_tier(batch)
        db.touch(batch)
        touched_batches.append(batch["id"])
    if not touched_batches:
        return
    affected = set(touched_batches)
    for claim in db.ordered(list(db.refund_claims.values())):
        if claim["claim_state"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        if not affected.intersection(claim["batch_ids"]):
            continue
        impressions, _cents = svc.refresh_provisional(claim)
        db.touch(claim)
        if impressions != 0:
            continue
        # hop 4 -- the platform rejects a claim that has lost its basis
        claim["claim_state"] = "REJECTED"
        claim["reject_reason_code"] = calc.REJECT_REASON_APPEAL_OVERTURNED
        for batch in svc.cited_batches(claim):
            if batch["settlement_status"] == "CLAIMED":
                batch["settlement_status"] = "CLOSED_NO_CREDIT"
                db.touch(batch)
        campaign = db.campaigns.get(claim["campaign_id"])
        if campaign is not None:
            campaign["open_claim_count"] = max(0, int(campaign["open_claim_count"]) - 1)
            db.touch(campaign)


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    caller = mw.require(ROLE_DISPUTE_OFFICER)
    record = svc.require_path(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    payload = mw.body()
    outcome = v.req_enum(payload, "outcome", {"MORE_EVIDENCE", "UPHELD", "OVERTURNED"})
    decision_note = v.opt_string(payload, "decision_note")
    revised_tier = v.opt_enum(payload, "revised_tier", calc.TIER_SET)
    disputed = db.page_classifications.get(record["classification_id"])
    page = db.pages.get(disputed["page_id"]) if disputed else None
    # priority 7 -- state reachability
    if record["appeal_state"] not in LIVE_APPEAL_STATES:
        fail("ERR_INVALID_APPEAL_STATE")
    if outcome == "MORE_EVIDENCE" and record["appeal_state"] != "FILED":
        fail("ERR_INVALID_APPEAL_STATE")
    # priority 10 -- segregation of duties on appeals
    if disputed is not None and caller.user_id is not None:
        if caller.user_id in (
            disputed.get("reviewed_by_user_id"),
            disputed.get("classifier_user_id"),
        ):
            fail("ERR_SEGREGATION_OF_DUTIES")
    # priority 14 -- revised tier discipline
    if outcome == "OVERTURNED":
        if revised_tier is None:
            fail("ERR_REVISED_TIER_REQUIRED")
        disputed_tier = disputed.get("assigned_tier") if disputed else None
        if disputed_tier not in calc.TIER_RANK or not (
            calc.TIER_RANK[revised_tier] > calc.TIER_RANK[disputed_tier]
        ):
            fail("ERR_REVISED_TIER_REQUIRED")
    elif outcome == "UPHELD" and revised_tier is not None:
        fail("ERR_REVISED_TIER_REQUIRED")
    # priority 26 -- the appeal round ceiling
    if outcome == "MORE_EVIDENCE" and int(record["round_no"]) >= calc.APPEAL_MAX_ROUNDS:
        fail("ERR_APPEAL_ROUNDS_EXHAUSTED")

    publisher = db.publishers.get(page["publisher_id"]) if page else None
    if outcome == "MORE_EVIDENCE":
        record["appeal_state"] = "MORE_EVIDENCE_REQUIRED"
        record["decision_note"] = decision_note
        db.touch(record)
        return response.object_response(record)
    if outcome == "UPHELD":
        record["appeal_state"] = "UPHELD"
        record["decision_note"] = decision_note
        record["decided_by_user_id"] = caller.user_id
        db.touch(record)
        if page is not None:
            page["classification_state"] = "HUMAN_CONFIRMED"
            db.touch(page)
        if publisher is not None:
            publisher["decided_appeal_count"] = int(publisher["decided_appeal_count"]) + 1
            db.touch(publisher)
        return response.object_response(record)
    # OVERTURNED -- the four-hop remedy cascade
    disputed["review_state"] = "VACATED"
    db.touch(disputed)
    remedy = _mint_remedy_classification(disputed, page, revised_tier, caller.user_id)
    page["current_classification_id"] = remedy["id"]
    page["current_tier"] = remedy["assigned_tier"]
    page["classification_state"] = "RECLASSIFIED"
    db.touch(page)
    record["appeal_state"] = "OVERTURNED"
    record["decision_note"] = decision_note
    record["decided_by_user_id"] = caller.user_id
    record["revised_tier"] = revised_tier
    record["remedy_classification_id"] = remedy["id"]
    db.touch(record)
    if publisher is not None:
        publisher["decided_appeal_count"] = int(publisher["decided_appeal_count"]) + 1
        publisher["overturned_appeal_count"] = int(publisher["overturned_appeal_count"]) + 1
        db.touch(publisher)
    _overturn_cascade(page)
    return response.object_response(record)
