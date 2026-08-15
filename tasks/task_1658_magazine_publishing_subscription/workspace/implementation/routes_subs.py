"""Routes: Subscribers, Subscriptions, SubscriptionTerms, RenewalSeries,
RenewalEvents, DigitalEntitlements (plus flat aliases)."""

from flask import Blueprint

from auth import require_roles
from db import store, new_record, touch
from errors import err
from routes_pub import list_response, PD, CM, PD_CM, PD_CM_FM
from serializers import (
    ser_subscriber,
    ser_subscription,
    ser_term,
    ser_renewal_series,
    ser_renewal_event,
    ser_entitlement,
    ser_revenue_entry,
    ser_label,
    ser_back_issue_order,
)
from services import (
    get_publication,
    get_subscriber,
    get_subscription,
    get_term,
    get_series,
    get_renewal_event,
    get_entitlement,
    create_term,
    open_term,
    apply_gift_credit,
    suspend_subscription,
    resume_subscription,
    expire_pending_renewal_events,
    recompute_circulation_class,
    recompute_remaining,
    default_series_for,
    find_series_by_code,
    renewal_window_open,
    fire_renewal_event,
    issue_sequence,
    post_revenue_entry,
)
from util import (
    body,
    success,
    paginate,
    sorted_by_creation,
    req_string,
    req_int,
    req_enum,
    opt_enum,
    opt_bool,
    opt_string,
    require_fields,
    postal_code_valid,
)

bp = Blueprint("subs", __name__)

PD_FM_PCO = ["PublishingDirector", "FulfillmentManager", "PostalComplianceOfficer"]

ADDRESS_FIELDS = (
    "address_line1",
    "address_line2",
    "city",
    "state_code",
    "postal_code",
    "country_code",
)

# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------


@bp.post("/subscribers")
@require_roles(CM)
def create_subscriber():
    data = body()
    require_fields(
        data,
        ["email", "full_name", "address_line1", "city", "state_code", "postal_code"],
    )
    state_code = req_string(data, "state_code")
    if len(state_code) != 2:
        raise err("ERR_INVALID_REQUEST", "state_code must be exactly 2 characters")
    rec = new_record()
    rec.update(
        {
            "email": req_string(data, "email"),
            "full_name": req_string(data, "full_name"),
            "address_line1": req_string(data, "address_line1"),
            "address_line2": opt_string(data, "address_line2"),
            "city": req_string(data, "city"),
            "state_code": state_code,
            "postal_code": req_string(data, "postal_code"),
            "country_code": opt_string(data, "country_code", "US"),
            "is_deliverable": True,
            "circulation_class": "NON_QUALIFIED",
        }
    )
    store.subscribers[rec["id"]] = rec
    return success(ser_subscriber(rec), 201)


@bp.get("/subscribers")
@require_roles(PD_CM_FM)
def list_subscribers():
    return list_response(
        store.subscribers.values(),
        ser_subscriber,
        ("circulation_class", "is_deliverable"),
    )


@bp.get("/subscribers/<subscriberId>")
@require_roles(PD_CM_FM)
def get_subscriber_detail(subscriberId):
    return success(ser_subscriber(get_subscriber(subscriberId)), 200)


@bp.patch("/subscribers/<subscriberId>")
@require_roles(CM)
def update_subscriber(subscriberId):
    sub = get_subscriber(subscriberId)
    data = body()
    for field in ADDRESS_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if value is None:
            if field == "address_line2":
                sub[field] = None
                continue
            raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
        if not isinstance(value, str):
            raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
        if field == "state_code" and len(value) != 2:
            raise err(
                "ERR_INVALID_REQUEST", "state_code must be exactly 2 characters"
            )
        sub[field] = value
    # Postal hygiene: an invalid postal_code flips deliverability off.
    sub["is_deliverable"] = postal_code_valid(sub["country_code"], sub["postal_code"])
    touch(sub)
    return success(ser_subscriber(sub), 200)


# --- Subscriber-scoped list aliases ----------------------------------------


@bp.get("/subscribers/<id>/subscriptions")
@require_roles(PD_CM)
def list_subscriber_subscriptions_alias(id):
    sub = get_subscriber(id)
    records = [
        s for s in store.subscriptions.values() if s["subscriber_id"] == sub["id"]
    ]
    return list_response(records, ser_subscription, ("status", "publication_id"))


@bp.get("/subscribers/<id>/back-issue-orders")
@require_roles(PD_CM_FM)
def list_subscriber_orders_alias(id):
    sub = get_subscriber(id)
    records = [
        o for o in store.back_issue_orders.values() if o["subscriber_id"] == sub["id"]
    ]
    return list_response(records, ser_back_issue_order, ("status",))


@bp.get("/subscribers/<id>/mailing-labels")
@require_roles(PD_FM_PCO)
def list_subscriber_labels_alias(id):
    sub = get_subscriber(id)
    records = [l for l in store.labels.values() if l["subscriber_id"] == sub["id"]]
    return list_response(records, ser_label)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@bp.post("/publications/<publicationId>/subscribers/<subscriberId>/subscriptions")
@require_roles(CM)
def create_subscription(publicationId, subscriberId):
    pub = get_publication(publicationId)
    subscriber = get_subscriber(subscriberId)
    data = body()
    # Priority 7: referential integrity of start issue and gift donor.
    start_issue_id = data.get("start_issue_id")
    if start_issue_id is not None:
        issue = store.issues.get(start_issue_id)
        if (
            issue is None
            or issue["publication_id"] != pub["id"]
            or issue["status"] in ("MAILED", "FINALIZED")
        ):
            raise err(
                "ERR_INVALID_START_ISSUE",
                "start_issue_id not on this Publication or already MAILED/FINALIZED",
            )
    is_gift = opt_bool(data, "is_gift", False)
    donor_id = data.get("donor_subscriber_id")
    if is_gift and donor_id is not None:
        donor = store.subscribers.get(donor_id)
        has_active_paid = any(
            s["subscriber_id"] == donor_id
            and s["publication_id"] == pub["id"]
            and s["qualification_tier"] == "PAID"
            and s["status"] == "ACTIVE"
            for s in store.subscriptions.values()
        )
        if donor is None or not has_active_paid:
            raise err(
                "ERR_DONOR_NOT_FOUND",
                "donor_subscriber_id has no active paid subscription on this Publication",
            )
    # Priority 8: tier/payment consistency.
    tier = data.get("qualification_tier")
    price = data.get("price_paid_cents")
    payment_method = data.get("payment_method", "CARD")
    if tier == "PAID":
        if (
            isinstance(price, bool)
            or not isinstance(price, int)
            or price <= 0
            or payment_method == "NONE"
        ):
            raise err(
                "ERR_PAID_REQUIRES_PAYMENT",
                "PAID subscription requires price_paid_cents > 0 and payment_method != NONE",
            )
    if tier == "CONTROLLED":
        if isinstance(price, bool) or not isinstance(price, int) or price != 0:
            raise err(
                "ERR_CONTROLLED_MUST_BE_FREE",
                "CONTROLLED subscription requires price_paid_cents == 0",
            )
    # Priority 17: required fields and well-formedness.
    require_fields(
        data, ["start_issue_id", "term_issues", "price_paid_cents", "qualification_tier"]
    )
    if not isinstance(start_issue_id, str):
        raise err("ERR_INVALID_REQUEST", "start_issue_id must be a string")
    term_issues = req_int(data, "term_issues", minimum=1)
    price_paid = req_int(data, "price_paid_cents", minimum=0)
    tier = req_enum(data, "qualification_tier", {"PAID", "CONTROLLED", "COMPLIMENTARY"})
    payment_method = opt_enum(
        data, "payment_method", {"CARD", "CHECK", "INVOICE", "NONE"}, "CARD"
    )
    if payment_method == "NONE" and tier == "PAID":
        raise err(
            "ERR_PAID_REQUIRES_PAYMENT",
            "PAID subscription requires payment_method != NONE",
        )
    if is_gift and donor_id is None:
        raise err(
            "ERR_INVALID_REQUEST", "donor_subscriber_id is required when is_gift=true"
        )
    if not is_gift and donor_id is not None:
        raise err(
            "ERR_INVALID_REQUEST", "donor_subscriber_id is present iff is_gift=true"
        )
    auto_renew = opt_bool(data, "auto_renew", False)
    expire_action = opt_enum(
        data, "expire_action", {"EXPIRE", "CONVERT_TO_CONTROLLED"}, "EXPIRE"
    )
    rec = new_record()
    rec.update(
        {
            "subscriber_id": subscriber["id"],
            "publication_id": pub["id"],
            "start_issue_id": start_issue_id,
            "term_issues": term_issues,
            "price_paid_cents": price_paid,
            "qualification_tier": tier,
            "payment_method": payment_method,
            "is_gift": is_gift,
            "donor_subscriber_id": donor_id if is_gift else None,
            "renewal_series_code": None,
            "renewal_effort_number": 0,
            "issues_served": 0,
            "issues_suspended_count": 0,
            "issues_remaining": term_issues,
            "auto_renew": auto_renew,
            "expire_action": expire_action,
            "status": "PENDING_START",
            "_entered_grace_at": None,
            "_mailed_snapshot": 0,
        }
    )
    store.subscriptions[rec["id"]] = rec
    if is_gift:
        apply_gift_credit(rec)
    return success(ser_subscription(rec), 201)


@bp.get("/publications/<publicationId>/subscriptions")
@require_roles(PD_CM_FM)
def list_subscriptions(publicationId):
    pub = get_publication(publicationId)
    records = [
        s for s in store.subscriptions.values() if s["publication_id"] == pub["id"]
    ]
    return list_response(
        records, ser_subscription, ("status", "subscriber_id", "qualification_tier")
    )


@bp.get("/publications/<publicationId>/subscriptions/<subscriptionId>")
@require_roles(PD_CM_FM)
def get_subscription_detail(publicationId, subscriptionId):
    get_publication(publicationId)
    return success(ser_subscription(get_subscription(subscriptionId, publicationId)), 200)


@bp.get("/subscriptions/<subscriptionId>")
@require_roles(PD_CM_FM)
def get_subscription_flat(subscriptionId):
    return success(ser_subscription(get_subscription(subscriptionId)), 200)


@bp.post("/publications/<publicationId>/subscriptions/<subscriptionId>/activate")
@require_roles(CM)
def activate_subscription(publicationId, subscriptionId):
    pub = get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    if sub["status"] != "PENDING_START":
        raise err(
            "ERR_INVALID_STATE", "Subscription must be PENDING_START to activate"
        )
    if pub["status"] != "ACTIVE":
        raise err(
            "ERR_PUBLICATION_NOT_ACTIVE", "Operation requires Publication ACTIVE"
        )
    if sub["qualification_tier"] == "PAID" and (
        sub["price_paid_cents"] <= 0 or sub["payment_method"] == "NONE"
    ):
        raise err(
            "ERR_PAID_REQUIRES_PAYMENT",
            "PAID subscription requires price_paid_cents > 0 and payment_method != NONE",
        )
    if sub["qualification_tier"] == "CONTROLLED" and sub["price_paid_cents"] != 0:
        raise err(
            "ERR_CONTROLLED_MUST_BE_FREE",
            "CONTROLLED subscription requires price_paid_cents == 0",
        )
    subscriber = store.subscribers[sub["subscriber_id"]]
    if not subscriber["is_deliverable"]:
        raise err("ERR_UNDELIVERABLE_ADDRESS", "Subscriber address is not deliverable")
    create_term(sub, 1, sub["start_issue_id"], sub["term_issues"], sub["price_paid_cents"])
    sub["status"] = "ACTIVE"
    series = default_series_for(pub["id"])
    if series is not None:
        sub["renewal_series_code"] = series["series_code"]
    recompute_circulation_class(sub["subscriber_id"])
    touch(sub)
    return success(ser_subscription(sub), 200)


@bp.post("/publications/<publicationId>/subscriptions/<subscriptionId>/suspend")
@require_roles(CM)
def suspend_subscription_route(publicationId, subscriptionId):
    pub = get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscription must be ACTIVE to suspend")
    if pub["status"] != "ACTIVE":
        raise err(
            "ERR_PUBLICATION_NOT_ACTIVE", "Operation requires Publication ACTIVE"
        )
    suspend_subscription(sub)
    return success(ser_subscription(sub), 200)


@bp.post("/publications/<publicationId>/subscriptions/<subscriptionId>/resume")
@require_roles(CM)
def resume_subscription_route(publicationId, subscriptionId):
    pub = get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    if sub["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Subscription must be SUSPENDED to resume")
    if pub["status"] != "ACTIVE":
        raise err(
            "ERR_PUBLICATION_NOT_ACTIVE", "Operation requires Publication ACTIVE"
        )
    subscriber = store.subscribers[sub["subscriber_id"]]
    if not subscriber["is_deliverable"]:
        raise err("ERR_UNDELIVERABLE_ADDRESS", "Subscriber address is not deliverable")
    resume_subscription(sub)
    return success(ser_subscription(sub), 200)


@bp.post("/publications/<publicationId>/subscriptions/<subscriptionId>/renew")
@require_roles(CM)
def renew_subscription(publicationId, subscriptionId):
    pub = get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    if sub["status"] != "GRACE":
        raise err("ERR_INVALID_STATE", "Subscription must be GRACE to renew")
    data = body()
    expected = data.get("expected_subscription_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(
                "ERR_INVALID_REQUEST",
                "expected_subscription_version must be an integer",
            )
        if expected != sub["version"]:
            raise err(
                "ERR_STALE_SUBSCRIPTION_VERSION",
                "expected_subscription_version does not match current Subscription.version",
            )
    new_price = data.get("new_price_paid_cents")
    if isinstance(new_price, int) and not isinstance(new_price, bool) and new_price <= 0:
        raise err(
            "ERR_PAID_REQUIRES_PAYMENT",
            "Renewal requires payment accepted for the renewal term (price > 0)",
        )
    require_fields(
        data,
        ["expected_subscription_version", "new_term_issues", "new_price_paid_cents"],
    )
    new_term_issues = req_int(data, "new_term_issues", minimum=1)
    new_price_paid = req_int(data, "new_price_paid_cents", minimum=0)
    previous = open_term(sub["id"])
    next_index = previous["term_index"] + 1 if previous else 1
    start_issue_id = sub["start_issue_id"]
    if previous is not None and previous["term_end_issue_id"]:
        seq = issue_sequence(pub["id"])
        for i, issue in enumerate(seq):
            if issue["id"] == previous["term_end_issue_id"] and i + 1 < len(seq):
                start_issue_id = seq[i + 1]["id"]
                break
    create_term(sub, next_index, start_issue_id, new_term_issues, new_price_paid)
    sub["term_issues"] = new_term_issues
    sub["price_paid_cents"] = new_price_paid
    sub["issues_served"] = 0
    sub["issues_suspended_count"] = 0
    recompute_remaining(sub)
    sub["_entered_grace_at"] = None
    pending = [
        ev
        for ev in store.renewal_events.values()
        if ev["subscription_id"] == sub["id"] and ev["response"] == "PENDING"
    ]
    if pending:
        latest = max(pending, key=lambda e: e["_seq"])
        latest["response"] = "ACCEPTED"
        latest["responded_at"] = store.now()
        touch(latest)
    sub["status"] = "ACTIVE"
    touch(sub)
    recompute_circulation_class(sub["subscriber_id"])
    return success(ser_subscription(sub), 200)


@bp.post("/publications/<publicationId>/subscriptions/<subscriptionId>/cancel")
@require_roles(CM)
def cancel_subscription(publicationId, subscriptionId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscription must be ACTIVE to cancel")
    term = open_term(sub["id"])
    if term is not None:
        served = sub["issues_served"]
        if served == 0:
            rate_bps = 10000
        elif served <= 3:
            rate_bps = 9000
        else:
            rate_bps = 5000
        deferred = term["deferred_balance_cents"]
        refund = (deferred * rate_bps) // 10000
        top_up = deferred - refund
        # Unrefunded remainder is recognized immediately.
        post_revenue_entry(
            term, None, top_up, term["recognition_variant"], "RECOGNITION", store.now()
        )
        term["recognized_balance_cents"] += top_up
        term["deferred_balance_cents"] -= top_up
        # REFUND_LIQUIDATION carries the negative of the ENTIRE remaining
        # deferred balance as it stood at cancellation (PRD 3.6: "the negative
        # of the entire remaining deferred balance"), and the liability is
        # then zeroed.
        liquidation = -deferred
        post_revenue_entry(
            term,
            None,
            liquidation,
            term["recognition_variant"],
            "REFUND_LIQUIDATION",
            store.now(),
        )
        term["deferred_balance_cents"] = 0
        term["status"] = "REFUNDED" if rate_bps == 10000 else "PARTIALLY_REFUNDED"
        touch(term)
    expire_pending_renewal_events(sub["id"])
    for ent in store.entitlements.values():
        if ent["subscription_id"] == sub["id"] and ent["revoked_at"] is None:
            ent["revoked_at"] = store.now()
            ent["revocation_reason"] = "REFUND"
            touch(ent)
    sub["status"] = "CANCELLED"
    touch(sub)
    recompute_circulation_class(sub["subscriber_id"])
    return success(ser_subscription(sub), 200)


# ---------------------------------------------------------------------------
# SubscriptionTerms (read-only)
# ---------------------------------------------------------------------------


def _list_terms(subscription_id):
    records = [t for t in store.terms.values() if t["subscription_id"] == subscription_id]
    return list_response(records, ser_term)


@bp.get("/publications/<publicationId>/subscriptions/<subscriptionId>/terms")
@require_roles(PD_CM)
def list_terms(publicationId, subscriptionId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return _list_terms(sub["id"])


@bp.get("/subscriptions/<id>/subscription-terms")
@require_roles(PD_CM)
def list_terms_alias(id):
    sub = get_subscription(id)
    return _list_terms(sub["id"])


@bp.get("/publications/<publicationId>/subscriptions/<subscriptionId>/terms/<termId>")
@require_roles(PD_CM)
def get_term_detail(publicationId, subscriptionId, termId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return success(ser_term(get_term(termId, sub["id"])), 200)


@bp.get("/subscription-terms/<termId>")
@require_roles(PD_CM)
def get_term_flat(termId):
    return success(ser_term(get_term(termId)), 200)


def _list_term_entries(term_id):
    records = [
        e for e in store.revenue_entries.values() if e["subscription_term_id"] == term_id
    ]
    return list_response(records, ser_revenue_entry, ("entry_type", "variant"))


@bp.get(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/terms/<termId>/revenue-entries"
)
@require_roles(PD_CM)
def list_term_entries(publicationId, subscriptionId, termId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    term = get_term(termId, sub["id"])
    return _list_term_entries(term["id"])


@bp.get("/subscription-terms/<id>/deferred-revenue-entries")
@require_roles(PD_CM)
def list_term_entries_alias(id):
    term = get_term(id)
    return _list_term_entries(term["id"])


@bp.get("/deferred-revenue-entries/<entryId>")
@require_roles(PD_CM)
def get_revenue_entry_flat(entryId):
    entry = store.revenue_entries.get(entryId)
    if entry is None:
        raise err("ERR_SUBSCRIPTION_NOT_FOUND", "DeferredRevenueEntry id does not exist")
    return success(ser_revenue_entry(entry), 200)


# ---------------------------------------------------------------------------
# RenewalSeries
# ---------------------------------------------------------------------------


@bp.post("/publications/<publicationId>/renewal-series")
@require_roles(CM)
def create_series(publicationId):
    pub = get_publication(publicationId)
    data = body()
    require_fields(data, ["series_code", "effort_offsets_days", "effort_pricing_cents"])
    series_code = req_string(data, "series_code")
    offsets = data["effort_offsets_days"]
    pricing = data["effort_pricing_cents"]
    if not isinstance(offsets, list) or not all(
        isinstance(o, int) and not isinstance(o, bool) for o in offsets
    ):
        raise err(
            "ERR_INVALID_REQUEST", "effort_offsets_days must be an array of integers"
        )
    if not isinstance(pricing, list) or not all(
        isinstance(p, int) and not isinstance(p, bool) for p in pricing
    ):
        raise err(
            "ERR_INVALID_REQUEST", "effort_pricing_cents must be an array of integers"
        )
    if len(offsets) != len(pricing):
        raise err(
            "ERR_INVALID_REQUEST",
            "effort_pricing_cents must match length of effort_offsets_days",
        )
    is_default = opt_bool(data, "is_default", False)
    if any(
        r["publication_id"] == pub["id"] and r["series_code"] == series_code
        for r in store.renewal_series.values()
    ):
        raise err(
            "ERR_INVALID_REQUEST", "series_code must be unique per publication"
        )
    if is_default and any(
        r["publication_id"] == pub["id"] and r["is_default"]
        for r in store.renewal_series.values()
    ):
        raise err(
            "ERR_INVALID_REQUEST", "Only one default renewal series per publication"
        )
    rec = new_record()
    rec.update(
        {
            "publication_id": pub["id"],
            "series_code": series_code,
            "effort_offsets_days": list(offsets),
            "effort_pricing_cents": list(pricing),
            "max_efforts": len(offsets),
            "is_default": is_default,
        }
    )
    store.renewal_series[rec["id"]] = rec
    return success(ser_renewal_series(rec), 201)


@bp.get("/publications/<publicationId>/renewal-series")
@require_roles(PD_CM)
def list_series(publicationId):
    pub = get_publication(publicationId)
    records = [r for r in store.renewal_series.values() if r["publication_id"] == pub["id"]]
    return list_response(records, ser_renewal_series)


@bp.get("/publications/<publicationId>/renewal-series/<seriesId>")
@require_roles(PD_CM)
def get_series_detail(publicationId, seriesId):
    get_publication(publicationId)
    return success(ser_renewal_series(get_series(seriesId, publicationId)), 200)


@bp.get("/renewal-series/<seriesId>")
@require_roles(PD_CM)
def get_series_flat(seriesId):
    return success(ser_renewal_series(get_series(seriesId)), 200)


# ---------------------------------------------------------------------------
# RenewalEvents
# ---------------------------------------------------------------------------


def _list_renewal_events(subscription_id):
    records = [
        e for e in store.renewal_events.values() if e["subscription_id"] == subscription_id
    ]
    return list_response(records, ser_renewal_event, ("response",))


@bp.get("/publications/<publicationId>/subscriptions/<subscriptionId>/renewal-events")
@require_roles(PD_CM)
def list_renewal_events(publicationId, subscriptionId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return _list_renewal_events(sub["id"])


@bp.get("/subscriptions/<id>/renewal-events")
@require_roles(PD_CM)
def list_renewal_events_alias(id):
    sub = get_subscription(id)
    return _list_renewal_events(sub["id"])


@bp.get(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/renewal-events/<eventId>"
)
@require_roles(PD_CM)
def get_renewal_event_detail(publicationId, subscriptionId, eventId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return success(ser_renewal_event(get_renewal_event(eventId, sub["id"])), 200)


@bp.get("/renewal-events/<eventId>")
@require_roles(PD_CM)
def get_renewal_event_flat(eventId):
    return success(ser_renewal_event(get_renewal_event(eventId)), 200)


@bp.post(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/renewal-events/fire-next"
)
@require_roles(CM)
def fire_next_renewal_event(publicationId, subscriptionId):
    pub = get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    code = sub["renewal_series_code"]
    series = find_series_by_code(pub["id"], code) if code else None
    if series is None:
        raise err(
            "ERR_INVALID_STATE", "Subscription has no active renewal series"
        )
    next_effort = sub["renewal_effort_number"] + 1
    if next_effort > series["max_efforts"]:
        raise err("ERR_INVALID_STATE", "No further renewal efforts remain")
    if not renewal_window_open(sub, series, next_effort):
        raise err(
            "ERR_RENEWAL_WINDOW_NOT_OPEN",
            "current_utc has not reached the next renewal effort's offset window",
        )
    ev = fire_renewal_event(sub, series)
    return success(ser_renewal_event(ev), 201)


@bp.post(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/renewal-events/<eventId>/decline"
)
@require_roles(CM)
def decline_renewal_event(publicationId, subscriptionId, eventId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    ev = get_renewal_event(eventId, sub["id"])
    if ev["response"] != "PENDING":
        raise err("ERR_INVALID_STATE", "RenewalEvent must be PENDING to decline")
    ev["response"] = "DECLINED"
    ev["responded_at"] = store.now()
    touch(ev)
    sub["renewal_effort_number"] += 1
    touch(sub)
    return success(ser_renewal_event(ev), 200)


# ---------------------------------------------------------------------------
# DigitalEntitlements
# ---------------------------------------------------------------------------


def _list_entitlements(subscription_id):
    records = [
        e for e in store.entitlements.values() if e["subscription_id"] == subscription_id
    ]
    return list_response(records, ser_entitlement, ("access_level",))


@bp.get("/publications/<publicationId>/subscriptions/<subscriptionId>/entitlements")
@require_roles(PD_CM)
def list_entitlements(publicationId, subscriptionId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return _list_entitlements(sub["id"])


@bp.get("/subscriptions/<id>/digital-entitlements")
@require_roles(PD_CM)
def list_entitlements_alias(id):
    sub = get_subscription(id)
    return _list_entitlements(sub["id"])


@bp.get(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/entitlements/<entitlementId>"
)
@require_roles(PD_CM)
def get_entitlement_detail(publicationId, subscriptionId, entitlementId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    return success(ser_entitlement(get_entitlement(entitlementId, sub["id"])), 200)


@bp.get("/digital-entitlements/<entitlementId>")
@require_roles(PD_CM)
def get_entitlement_flat(entitlementId):
    return success(ser_entitlement(get_entitlement(entitlementId)), 200)


@bp.post(
    "/publications/<publicationId>/subscriptions/<subscriptionId>/entitlements/<entitlementId>/revoke"
)
@require_roles(CM)
def revoke_entitlement(publicationId, subscriptionId, entitlementId):
    get_publication(publicationId)
    sub = get_subscription(subscriptionId, publicationId)
    ent = get_entitlement(entitlementId, sub["id"])
    data = body()
    reason = data.get("reason")
    if reason not in ("REFUND", "CHARGEBACK", "MANUAL"):
        raise err(
            "ERR_INVALID_REQUEST", "reason must be one of REFUND, CHARGEBACK, MANUAL"
        )
    if ent["revoked_at"] is not None:
        raise err("ERR_INVALID_STATE", "DigitalEntitlement is already revoked")
    ent["revoked_at"] = store.now()
    ent["revocation_reason"] = reason
    touch(ent)
    return success(ser_entitlement(ent), 200)


# --- Subscription-scoped label listing -------------------------------------


@bp.get("/subscriptions/<id>/mailing-labels")
@require_roles(PD_FM_PCO)
def list_subscription_labels_alias(id):
    sub = get_subscription(id)
    records = [l for l in store.labels.values() if l["subscription_id"] == sub["id"]]
    return list_response(records, ser_label)
