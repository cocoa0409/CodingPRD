"""Routes: MailingBatches, MailingLabels, PostalStatements and issue-scoped
reverse-FK list endpoints."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import store, new_record, touch
from errors import err
from routes_pub import list_response, PD, PD_CM, PD_CM_FM
from serializers import (
    ser_batch,
    ser_label,
    ser_postal_statement,
    ser_subscription,
    ser_term,
    ser_back_issue_order,
    ser_entitlement,
    ser_revenue_entry,
)
from services import (
    POSTAL_FORM_BY_CLASS,
    get_publication,
    get_issue,
    get_batch,
    get_label,
    get_postal_statement,
    postal_rate_cents,
    paid_percentage_bps,
    label_eligible_subscriptions,
    format_address_block,
)
from util import body, success, req_string, req_enum, opt_enum, opt_bool, require_fields

bp = Blueprint("mail", __name__)

PM = ["ProductionManager"]
FM = ["FulfillmentManager"]
PCO = ["PostalComplianceOfficer"]
BATCH_READERS = ["PublishingDirector", "ProductionManager", "FulfillmentManager", "PostalComplianceOfficer"]
LABEL_READERS = ["PublishingDirector", "FulfillmentManager", "PostalComplianceOfficer"]
STATEMENT_READERS = ["PublishingDirector", "PostalComplianceOfficer"]

DEFAULT_PIECE_WEIGHT_OZ = 3.0

# ---------------------------------------------------------------------------
# MailingBatches
# ---------------------------------------------------------------------------


@bp.post("/publications/<publicationId>/issues/<issueId>/mailing-batches")
@require_roles(FM)
def create_batch(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    data = body()
    require_fields(data, ["batch_label", "postal_class", "permit_number"])
    rec = new_record()
    rec.update(
        {
            "issue_id": issue["id"],
            "batch_label": req_string(data, "batch_label"),
            "postal_class": req_enum(
                data, "postal_class", {"PERIODICAL", "STANDARD", "FIRST_CLASS"}
            ),
            "entry_point": opt_enum(
                data, "entry_point", {"ORIGIN", "DDU", "DSCF", "SCF"}, "ORIGIN"
            ),
            "expected_piece_count": 0,
            "total_postage_cents": 0,
            "permit_number": req_string(data, "permit_number"),
            "is_controlled_copy_included": opt_bool(
                data, "is_controlled_copy_included", True
            ),
            "status": "DRAFT",
        }
    )
    store.batches[rec["id"]] = rec
    return success(ser_batch(rec), 201)


def _list_batches(issue_id):
    records = [b for b in store.batches.values() if b["issue_id"] == issue_id]
    return list_response(records, ser_batch, ("status",))


@bp.get("/publications/<publicationId>/issues/<issueId>/mailing-batches")
@require_roles(BATCH_READERS)
def list_batches(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    return _list_batches(issue["id"])


@bp.get("/issues/<id>/mailing-batches")
@require_roles(BATCH_READERS)
def list_batches_alias(id):
    issue = get_issue(id)
    return _list_batches(issue["id"])


@bp.get("/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>")
@require_roles(BATCH_READERS)
def get_batch_detail(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    return success(ser_batch(get_batch(batchId, issue["id"])), 200)


@bp.get("/mailing-batches/<batchId>")
@require_roles(BATCH_READERS)
def get_batch_flat(batchId):
    return success(ser_batch(get_batch(batchId)), 200)


@bp.post(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/generate-labels"
)
@require_roles(FM)
def generate_labels(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    if issue["status"] != "AT_PRINTER":
        raise err(
            "ERR_ISSUE_NOT_AT_PRINTER",
            "Label generation requires Issue.status == AT_PRINTER",
        )
    if batch["status"] != "DRAFT":
        raise err(
            "ERR_LABELS_ALREADY_GENERATED", "Labels already generated for this batch"
        )
    data = body()
    expected = data.get("expected_batch_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(
                "ERR_INVALID_REQUEST", "expected_batch_version must be an integer"
            )
        if expected != batch["version"]:
            raise err(
                "ERR_STALE_BATCH_VERSION",
                "expected_batch_version does not match current MailingBatch.version",
            )
    if expected is None:
        raise err(
            "ERR_INVALID_REQUEST", "Missing required field: expected_batch_version"
        )
    weight = data.get("piece_weight_oz", DEFAULT_PIECE_WEIGHT_OZ)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
        raise err("ERR_INVALID_REQUEST", "piece_weight_oz must be a positive number")
    total_postage = 0
    for sub, subscriber in label_eligible_subscriptions(issue, batch):
        is_controlled = sub["qualification_tier"] in ("CONTROLLED", "COMPLIMENTARY")
        lbl = new_record(common_fields=False)
        lbl.update(
            {
                "batch_id": batch["id"],
                "subscription_id": sub["id"],
                "subscriber_id": subscriber["id"],
                "address_block": format_address_block(subscriber),
                "postal_code": subscriber["postal_code"],
                "is_controlled_copy": is_controlled,
                "piece_weight_oz": weight,
                "postage_cents": postal_rate_cents(
                    batch["postal_class"],
                    batch["entry_point"],
                    weight,
                    is_controlled,
                ),
            }
        )
        store.labels[lbl["id"]] = lbl
        total_postage += lbl["postage_cents"]
    batch["expected_piece_count"] = sum(
        1 for l in store.labels.values() if l["batch_id"] == batch["id"]
    )
    batch["total_postage_cents"] = total_postage
    batch["status"] = "LABELS_GENERATED"
    touch(batch)
    return success(ser_batch(batch), 200)


@bp.post(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/verify-postal"
)
@require_roles(PCO)
def verify_postal(publicationId, issueId, batchId):
    pub = get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    if batch["status"] != "LABELS_GENERATED":
        raise err(
            "ERR_INVALID_STATE", "MailingBatch must be LABELS_GENERATED to verify"
        )
    labels = [l for l in store.labels.values() if l["batch_id"] == batch["id"]]
    paid_count = sum(1 for l in labels if not l["is_controlled_copy"])
    controlled_count = sum(1 for l in labels if l["is_controlled_copy"])
    paid_bps = paid_percentage_bps(paid_count, paid_count + controlled_count)
    total_pages = issue["total_pages"]
    ad_bps = (
        (issue["ad_pages_sold"] * 10000) // total_pages if total_pages else 0
    )
    if batch["postal_class"] == "PERIODICAL":
        if paid_bps < 5000:
            raise err(
                "ERR_PAID_RATIO_BELOW_MINIMUM",
                "PERIODICAL class requires paid_percentage_bps >= 5000",
            )
        if ad_bps > 7500:
            raise err(
                "ERR_AD_CONTENT_EXCEEDS_LIMIT",
                "PERIODICAL class requires advertising_percentage_bps <= 7500",
            )
    if batch["postal_class"] == "STANDARD" and batch["is_controlled_copy_included"]:
        raise err(
            "ERR_STANDARD_NO_CONTROLLED",
            "STANDARD class does not permit controlled copies",
        )
    statement = new_record(common_fields=False)
    statement.update(
        {
            "batch_id": batch["id"],
            "form_number": POSTAL_FORM_BY_CLASS[batch["postal_class"]],
            "paid_piece_count": paid_count,
            "controlled_piece_count": controlled_count,
            "paid_percentage_bps": paid_bps,
            "advertising_percentage_bps": ad_bps,
            "total_postage_cents": batch["total_postage_cents"],
            "filed_at": store.now(),
        }
    )
    store.postal_statements[statement["id"]] = statement
    # Early-warning control: PAID publication below 70% paid share is flagged.
    if pub["circulation_model"] == "PAID" and paid_bps < 7000:
        pub["flagged_for_audit"] = True
        touch(pub)
    batch["status"] = "POSTAL_VERIFIED"
    touch(batch)
    return success(ser_batch(batch), 200)


@bp.post(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/tender"
)
@require_roles(FM)
def tender_batch(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    if batch["status"] != "POSTAL_VERIFIED":
        raise err("ERR_INVALID_STATE", "MailingBatch must be POSTAL_VERIFIED to tender")
    if store.now() < issue["mail_date"] - timedelta(days=1):
        raise err("ERR_TENDER_TOO_EARLY", "current_utc < mail_date - 1 day")
    batch["status"] = "TENDERED"
    touch(batch)
    return success(ser_batch(batch), 200)


@bp.post(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/confirm"
)
@require_roles(PCO)
def confirm_batch(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    if batch["status"] != "TENDERED":
        raise err("ERR_INVALID_STATE", "MailingBatch must be TENDERED to confirm")
    batch["status"] = "CONFIRMED"
    touch(batch)
    return success(ser_batch(batch), 200)


# ---------------------------------------------------------------------------
# MailingLabels
# ---------------------------------------------------------------------------


def _list_batch_labels(batch_id):
    records = [l for l in store.labels.values() if l["batch_id"] == batch_id]
    return list_response(records, ser_label, ("is_controlled_copy",))


@bp.get("/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/labels")
@require_roles(LABEL_READERS)
def list_labels(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    return _list_batch_labels(batch["id"])


@bp.get("/mailing-batches/<id>/mailing-labels")
@require_roles(LABEL_READERS)
def list_labels_alias(id):
    batch = get_batch(id)
    return _list_batch_labels(batch["id"])


@bp.get(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/labels/<labelId>"
)
@require_roles(LABEL_READERS)
def get_label_detail(publicationId, issueId, batchId, labelId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    return success(ser_label(get_label(labelId, batch["id"])), 200)


@bp.get("/mailing-labels/<labelId>")
@require_roles(LABEL_READERS)
def get_label_flat(labelId):
    return success(ser_label(get_label(labelId)), 200)


# ---------------------------------------------------------------------------
# PostalStatements
# ---------------------------------------------------------------------------


def _list_statements(batch_id):
    records = [
        s for s in store.postal_statements.values() if s["batch_id"] == batch_id
    ]
    return list_response(records, ser_postal_statement)


@bp.get(
    "/publications/<publicationId>/issues/<issueId>/mailing-batches/<batchId>/postal-statements"
)
@require_roles(STATEMENT_READERS)
def list_postal_statements(publicationId, issueId, batchId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    batch = get_batch(batchId, issue["id"])
    return _list_statements(batch["id"])


@bp.get("/mailing-batches/<id>/postal-statements")
@require_roles(STATEMENT_READERS)
def list_postal_statements_alias(id):
    batch = get_batch(id)
    return _list_statements(batch["id"])


@bp.get("/postal-statements/<statementId>")
@require_roles(STATEMENT_READERS)
def get_postal_statement_flat(statementId):
    return success(ser_postal_statement(get_postal_statement(statementId)), 200)


# ---------------------------------------------------------------------------
# Issue-scoped reverse-FK list endpoints
# ---------------------------------------------------------------------------


@bp.get("/issues/<id>/subscriptions")
@require_roles(PD_CM)
def list_issue_subscriptions(id):
    issue = get_issue(id)
    records = [
        s for s in store.subscriptions.values() if s["start_issue_id"] == issue["id"]
    ]
    return list_response(records, ser_subscription)


@bp.get("/issues/<id>/subscription-terms")
@require_roles(PD_CM)
def list_issue_terms(id):
    issue = get_issue(id)
    records = [
        t
        for t in store.terms.values()
        if t["term_start_issue_id"] == issue["id"]
        or t["term_end_issue_id"] == issue["id"]
    ]
    return list_response(records, ser_term)


@bp.get("/issues/<id>/back-issue-orders")
@require_roles(PD_CM_FM)
def list_issue_orders(id):
    issue = get_issue(id)
    records = [
        o for o in store.back_issue_orders.values() if o["issue_id"] == issue["id"]
    ]
    return list_response(records, ser_back_issue_order)


@bp.get("/issues/<id>/digital-entitlements")
@require_roles(PD_CM)
def list_issue_entitlements(id):
    issue = get_issue(id)
    records = [
        e for e in store.entitlements.values() if e["issue_id"] == issue["id"]
    ]
    return list_response(records, ser_entitlement)


@bp.get("/issues/<id>/deferred-revenue-entries")
@require_roles(PD_CM)
def list_issue_revenue_entries(id):
    issue = get_issue(id)
    records = [
        e for e in store.revenue_entries.values() if e["issue_id"] == issue["id"]
    ]
    return list_response(records, ser_revenue_entry)
