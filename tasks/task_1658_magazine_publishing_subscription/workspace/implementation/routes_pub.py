"""Routes: logical clock, Publications, Issues (including lifecycle actions)."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import store, new_record, touch
from errors import err
from serializers import (
    ser_publication,
    ser_issue,
    ser_subscription,
    ser_renewal_series,
    ser_audit,
    ser_back_issue_order,
)
from services import (
    ISSUES_PER_YEAR,
    get_publication,
    get_issue,
    qualified_subscriptions_for_issue,
    served_subscriptions_for_issue,
    recognize_pro_rata,
    open_term,
    suspend_subscription,
    resume_subscription,
    expire_pending_renewal_events,
    enter_grace,
    auto_renew_subscription,
    grant_gift_entitlement,
    recompute_circulation_class,
    recompute_remaining,
    run_system_transitions,
)
from util import (
    body,
    success,
    iso,
    parse_iso,
    paginate,
    sorted_by_creation,
    req_string,
    req_int,
    req_enum,
    opt_enum,
    opt_int,
    req_datetime,
    require_fields,
)

bp = Blueprint("pub", __name__)

PD = ["PublishingDirector"]
PM = ["ProductionManager"]
FM = ["FulfillmentManager"]
CM = ["CirculationManager"]
PD_CM_FM = ["PublishingDirector", "CirculationManager", "FulfillmentManager"]
PD_CM = ["PublishingDirector", "CirculationManager"]


def list_response(records, serializer, filters=()):
    items = sorted_by_creation(records)
    for field in filters:
        raw = request_arg(field)
        if raw is None:
            continue
        items = [r for r in items if record_matches(r, field, raw)]
    page, meta = paginate(items)
    return success([serializer(r) for r in page], 200, pagination=meta)


def request_arg(field):
    from flask import request

    return request.args.get(field)


def record_matches(rec, field, raw):
    value = rec.get(field)
    if isinstance(value, bool):
        if raw.lower() == "true":
            return value is True
        if raw.lower() == "false":
            return value is False
        return False
    return str(value) == raw


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
@require_roles(PD)
def set_clock():
    data = body()
    target = parse_iso(data.get("to_iso8601"))
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    old = store.current_utc
    store.current_utc = target
    run_system_transitions(old, target)
    return success({"current_utc": iso(store.current_utc)}, 200)


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------


@bp.post("/publications")
@require_roles(PD)
def create_publication():
    data = body()
    require_fields(
        data,
        ["title", "issn", "frequency", "circulation_model", "base_cover_price_cents"],
    )
    title = req_string(data, "title")
    issn = req_string(data, "issn")
    if len(issn) != 8:
        raise err("ERR_INVALID_REQUEST", "issn must be exactly 8 characters")
    frequency = req_enum(data, "frequency", {"WEEKLY", "MONTHLY", "QUARTERLY"})
    circulation_model = req_enum(
        data, "circulation_model", {"PAID", "CONTROLLED", "MIXED"}
    )
    price = req_int(data, "base_cover_price_cents", minimum=0)
    method = opt_enum(
        data,
        "deferred_revenue_method",
        {"PRO_RATA_ISSUE", "STRAIGHT_LINE_MONTH"},
        "PRO_RATA_ISSUE",
    )
    rec = new_record()
    rec.update(
        {
            "title": title,
            "issn": issn,
            "frequency": frequency,
            "circulation_model": circulation_model,
            "issues_per_year": ISSUES_PER_YEAR[frequency],
            "base_cover_price_cents": price,
            "deferred_revenue_method": method,
            "status": "ACTIVE",
            "flagged_for_audit": False,
        }
    )
    store.publications[rec["id"]] = rec
    return success(ser_publication(rec), 201)


@bp.get("/publications")
@require_roles(ALL_ROLES)
def list_publications():
    return list_response(store.publications.values(), ser_publication, ("status",))


@bp.get("/publications/<publicationId>")
@require_roles(ALL_ROLES)
def get_publication_detail(publicationId):
    return success(ser_publication(get_publication(publicationId)), 200)


@bp.post("/publications/<publicationId>/suspend")
@require_roles(PD)
def suspend_publication(publicationId):
    pub = get_publication(publicationId)
    if pub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Publication must be ACTIVE to suspend")
    for issue in store.issues.values():
        if issue["publication_id"] != pub["id"]:
            continue
        if issue["status"] not in ("FINALIZED", "PLANNING", "EDITORIAL_CLOSED"):
            raise err(
                "ERR_ISSUE_PIPELINE_ACTIVE",
                "Publication suspend blocked: an issue is mid-pipeline",
            )
    pub["status"] = "SUSPENDED"
    touch(pub)
    for sub in store.subscriptions.values():
        if sub["publication_id"] == pub["id"] and sub["status"] == "ACTIVE":
            suspend_subscription(sub, cascade_from_publication=True)
            expire_pending_renewal_events(sub["id"])
    return success(ser_publication(pub), 200)


@bp.post("/publications/<publicationId>/resume")
@require_roles(PD)
def resume_publication(publicationId):
    pub = get_publication(publicationId)
    if pub["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Publication must be SUSPENDED to resume")
    pub["status"] = "ACTIVE"
    touch(pub)
    for sub in store.subscriptions.values():
        if sub["publication_id"] == pub["id"] and sub["status"] == "SUSPENDED":
            resume_subscription(sub)
    return success(ser_publication(pub), 200)


@bp.post("/publications/<publicationId>/cease")
@require_roles(PD)
def cease_publication(publicationId):
    pub = get_publication(publicationId)
    if pub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Publication must be ACTIVE to cease")
    for issue in store.issues.values():
        if issue["publication_id"] == pub["id"] and issue["status"] != "FINALIZED":
            raise err(
                "ERR_ISSUE_PIPELINE_ACTIVE",
                "Publication cease blocked: not all issues are FINALIZED",
            )
    for sub in store.subscriptions.values():
        if sub["publication_id"] != pub["id"]:
            continue
        if sub["status"] not in ("EXPIRED", "CANCELLED", "RENEWED"):
            raise err(
                "ERR_ACTIVE_SUBSCRIPTIONS_REMAIN",
                "Publication cease blocked: subscriptions not in a terminal state",
            )
    for sub in store.subscriptions.values():
        if sub["publication_id"] != pub["id"]:
            continue
        for term in store.terms.values():
            if term["subscription_id"] == sub["id"] and (
                term["deferred_balance_cents"] != 0
            ):
                raise err(
                    "ERR_UNRECOGNIZED_DEFERRED_REVENUE",
                    "Publication cease blocked: unrecognized deferred revenue remains",
                )
    pub["status"] = "CEASED"
    touch(pub)
    return success(ser_publication(pub), 200)


# --- Publication-scoped list aliases (flat {id} placeholder) ---------------


@bp.get("/publications/<id>/issues")
@require_roles(ALL_ROLES)
def list_publication_issues_alias(id):
    pub = get_publication(id)
    return _list_issues(pub["id"])


@bp.get("/publications/<id>/subscriptions")
@require_roles(PD_CM_FM)
def list_publication_subscriptions_alias(id):
    pub = get_publication(id)
    records = [
        s for s in store.subscriptions.values() if s["publication_id"] == pub["id"]
    ]
    return list_response(
        records, ser_subscription, ("status", "subscriber_id", "qualification_tier")
    )


@bp.get("/publications/<id>/renewal-series")
@require_roles(PD_CM)
def list_publication_series_alias(id):
    pub = get_publication(id)
    records = [
        r for r in store.renewal_series.values() if r["publication_id"] == pub["id"]
    ]
    return list_response(records, ser_renewal_series)


@bp.get("/publications/<id>/circulation-audits")
@require_roles(PD_CM)
def list_publication_audits_alias(id):
    pub = get_publication(id)
    records = [a for a in store.audits.values() if a["publication_id"] == pub["id"]]
    return list_response(records, ser_audit, ("status",))


@bp.get("/publications/<id>/back-issue-orders")
@require_roles(PD_CM_FM)
def list_publication_orders_alias(id):
    pub = get_publication(id)
    records = [
        o
        for o in store.back_issue_orders.values()
        if o["_publication_id"] == pub["id"]
    ]
    return list_response(
        records, ser_back_issue_order, ("status", "subscriber_id", "issue_id")
    )


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


@bp.post("/publications/<publicationId>/issues")
@require_roles(PM)
def create_issue(publicationId):
    pub = get_publication(publicationId)
    data = body()
    require_fields(
        data,
        [
            "issue_number",
            "volume_number",
            "cover_date",
            "editorial_close_date",
            "ad_close_date",
            "ship_to_printer_date",
            "mail_date",
        ],
    )
    issue_number = req_int(data, "issue_number", minimum=0)
    volume_number = req_int(data, "volume_number", minimum=0)
    cover_date = req_datetime(data, "cover_date")
    editorial_close = req_datetime(data, "editorial_close_date")
    ad_close = req_datetime(data, "ad_close_date")
    ship_date = req_datetime(data, "ship_to_printer_date")
    mail_date = req_datetime(data, "mail_date")
    if ad_close < editorial_close:
        raise err(
            "ERR_INVALID_REQUEST",
            "ad_close_date must not fall before editorial_close_date",
        )
    ad_pages_sold = opt_int(data, "ad_pages_sold", default=0, minimum=0)
    print_run_override = opt_int(data, "print_run_override", default=None, minimum=0)
    newsstand_buffer = opt_int(data, "newsstand_buffer_copies", default=0, minimum=0)
    total_pages = opt_int(data, "total_pages", default=None, minimum=1)
    rec = new_record()
    rec.update(
        {
            "publication_id": pub["id"],
            "issue_number": issue_number,
            "volume_number": volume_number,
            "cover_date": cover_date,
            "editorial_close_date": editorial_close,
            "ad_close_date": ad_close,
            "ship_to_printer_date": ship_date,
            "mail_date": mail_date,
            "ad_pages_sold": ad_pages_sold,
            "total_pages": total_pages,
            "print_run_override": print_run_override,
            "print_run": None,
            "qualified_subscriber_count": 0,
            "newsstand_buffer_copies": newsstand_buffer,
            "revenue_recognized_cents": 0,
            "status": "PLANNING",
        }
    )
    store.issues[rec["id"]] = rec
    return success(ser_issue(rec), 201)


def _list_issues(publication_id):
    records = [i for i in store.issues.values() if i["publication_id"] == publication_id]
    return list_response(records, ser_issue, ("status",))


@bp.get("/publications/<publicationId>/issues")
@require_roles(ALL_ROLES)
def list_issues(publicationId):
    pub = get_publication(publicationId)
    return _list_issues(pub["id"])


@bp.get("/publications/<publicationId>/issues/<issueId>")
@require_roles(ALL_ROLES)
def get_issue_detail(publicationId, issueId):
    get_publication(publicationId)
    return success(ser_issue(get_issue(issueId, publicationId)), 200)


@bp.get("/issues/<issueId>")
@require_roles(ALL_ROLES)
def get_issue_flat(issueId):
    return success(ser_issue(get_issue(issueId)), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/close-editorial")
@require_roles(PM)
def close_editorial(publicationId, issueId):
    pub = get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "PLANNING":
        raise err("ERR_INVALID_STATE", "Issue must be PLANNING to close editorial")
    if pub["status"] != "ACTIVE":
        raise err(
            "ERR_PUBLICATION_NOT_ACTIVE", "Operation requires Publication ACTIVE"
        )
    if store.now() < issue["editorial_close_date"]:
        raise err(
            "ERR_EDITORIAL_NOT_CLOSED_YET", "current_utc < editorial_close_date"
        )
    issue["status"] = "EDITORIAL_CLOSED"
    touch(issue)
    return success(ser_issue(issue), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/close-ads")
@require_roles(PM)
def close_ads(publicationId, issueId):
    pub = get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "EDITORIAL_CLOSED":
        raise err("ERR_INVALID_STATE", "Issue must be EDITORIAL_CLOSED to close ads")
    data = body()
    expected = data.get("expected_issue_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(
                "ERR_INVALID_REQUEST", "expected_issue_version must be an integer"
            )
        if expected != issue["version"]:
            raise err(
                "ERR_STALE_ISSUE_VERSION",
                "expected_issue_version does not match current Issue.version",
            )
    if store.now() < issue["ad_close_date"]:
        raise err("ERR_AD_CLOSE_NOT_REACHED", "current_utc < ad_close_date")
    if issue["ad_pages_sold"] <= 0 and pub["circulation_model"] != "CONTROLLED":
        raise err(
            "ERR_NO_AD_PAGES",
            "PAID/MIXED publications require ad_pages_sold > 0 at close-ads",
        )
    if expected is None:
        raise err(
            "ERR_INVALID_REQUEST", "Missing required field: expected_issue_version"
        )
    issue["status"] = "AD_CLOSED"
    touch(issue)
    return success(ser_issue(issue), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/reopen-ads")
@require_roles(PM)
def reopen_ads(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "AD_CLOSED":
        raise err("ERR_INVALID_STATE", "Issue must be AD_CLOSED to reopen ads")
    for batch in store.batches.values():
        if batch["issue_id"] == issue["id"] and batch["status"] != "DRAFT":
            raise err(
                "ERR_BATCH_ALREADY_GENERATED",
                "Cannot reopen ads: a MailingBatch has already left DRAFT",
            )
    issue["status"] = "EDITORIAL_CLOSED"
    touch(issue)
    return success(ser_issue(issue), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/ship-to-printer")
@require_roles(PM)
def ship_to_printer(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "AD_CLOSED":
        raise err("ERR_INVALID_STATE", "Issue must be AD_CLOSED to ship to printer")
    if store.now() < issue["ship_to_printer_date"]:
        raise err(
            "ERR_PRINTER_DATE_NOT_REACHED", "current_utc < ship_to_printer_date"
        )
    qualified = len(qualified_subscriptions_for_issue(issue))
    override = issue["print_run_override"]
    if override is not None and override < qualified:
        raise err(
            "ERR_PRINT_RUN_TOO_SMALL",
            "print_run_override < qualified_subscriber_count",
        )
    issue["qualified_subscriber_count"] = qualified
    issue["print_run"] = (
        override if override is not None else qualified + issue["newsstand_buffer_copies"]
    )
    issue["status"] = "AT_PRINTER"
    touch(issue)
    return success(ser_issue(issue), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/mark-mailed")
@require_roles(FM)
def mark_mailed(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "AT_PRINTER":
        raise err("ERR_INVALID_STATE", "Issue must be AT_PRINTER to mark mailed")
    for batch in store.batches.values():
        if batch["issue_id"] == issue["id"] and batch["status"] != "CONFIRMED":
            raise err(
                "ERR_BATCH_NOT_CONFIRMED",
                "Issue mark-mailed blocked: not all MailingBatches are CONFIRMED",
            )
    if store.now() < issue["mail_date"]:
        raise err("ERR_MAIL_DATE_NOT_REACHED", "current_utc < mail_date")
    for sub in served_subscriptions_for_issue(issue):
        sub["issues_served"] += 1
        recompute_remaining(sub)
        term = open_term(sub["id"])
        if (
            term is not None
            and term["status"] == "OPEN"
            and term["recognition_variant"] == "PRO_RATA_ISSUE"
        ):
            recognize_pro_rata(term, issue)
        if sub["is_gift"]:
            grant_gift_entitlement(sub, issue)
        if sub["issues_remaining"] == 0:
            if sub["auto_renew"]:
                auto_renew_subscription(sub)
            else:
                enter_grace(sub)
        else:
            touch(sub)
    issue["revenue_recognized_cents"] = sum(
        e["amount_cents"]
        for e in store.revenue_entries.values()
        if e["issue_id"] == issue["id"] and e["entry_type"] == "RECOGNITION"
    )
    issue["status"] = "MAILED"
    touch(issue)
    return success(ser_issue(issue), 200)


@bp.post("/publications/<publicationId>/issues/<issueId>/finalize")
@require_roles(PM)
def finalize_issue(publicationId, issueId):
    get_publication(publicationId)
    issue = get_issue(issueId, publicationId)
    if issue["status"] != "MAILED":
        raise err("ERR_INVALID_STATE", "Issue must be MAILED to finalize")
    issue["status"] = "FINALIZED"
    touch(issue)
    return success(ser_issue(issue), 200)
