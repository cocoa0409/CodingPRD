"""Business logic: lookups, state transitions, calculations, clock triggers."""

import math
from datetime import timedelta
from decimal import Decimal

from db import store, new_record, touch
from errors import err
from util import (
    round_half_up_cents,
    month_end_instant,
    months_between,
    postal_code_valid,
)

ISSUES_PER_YEAR = {"WEEKLY": 52, "MONTHLY": 12, "QUARTERLY": 4}

# Flat back-issue shipping by destination country (PRD 3.7: flat fee derived
# from country_code; the document pins no amounts, so these are the system
# constants: domestic $5.00, foreign $15.00).
SHIPPING_DOMESTIC_CENTS = 500
SHIPPING_FOREIGN_CENTS = 1500

BACK_ISSUE_MARKUP_BPS = 15000  # 1.5x for issues older than 12 months
GIFT_CREDIT_BPS = 1000  # 10% of gift price, CREDIT mode (pinned)
GRACE_PERIOD_DAYS = 30

POSTAL_FORM_BY_CLASS = {
    "PERIODICAL": "PS_3541",
    "STANDARD": "PS_3602_R",
    "FIRST_CLASS": "PS_3541_A",
}

# ---------------------------------------------------------------------------
# Lookup helpers (existence validated left-to-right by callers)
# ---------------------------------------------------------------------------


def get_publication(pid):
    pub = store.publications.get(pid)
    if pub is None:
        raise err("ERR_PUBLICATION_NOT_FOUND", "Publication id does not exist")
    return pub


def get_issue(issue_id, publication_id=None):
    issue = store.issues.get(issue_id)
    if issue is None or (
        publication_id is not None and issue["publication_id"] != publication_id
    ):
        raise err(
            "ERR_ISSUE_NOT_FOUND", "Issue id does not exist on this Publication"
        )
    return issue


def get_subscriber(sid):
    sub = store.subscribers.get(sid)
    if sub is None:
        raise err("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber id does not exist")
    return sub


def get_subscription(subscription_id, publication_id=None):
    sub = store.subscriptions.get(subscription_id)
    if sub is None or (
        publication_id is not None and sub["publication_id"] != publication_id
    ):
        raise err(
            "ERR_SUBSCRIPTION_NOT_FOUND",
            "Subscription id does not exist on this Publication",
        )
    return sub


def get_term(term_id, subscription_id=None):
    term = store.terms.get(term_id)
    if term is None or (
        subscription_id is not None and term["subscription_id"] != subscription_id
    ):
        raise err(
            "ERR_SUBSCRIPTION_NOT_FOUND", "SubscriptionTerm id does not exist"
        )
    return term


def get_series(series_id, publication_id=None):
    series = store.renewal_series.get(series_id)
    if series is None or (
        publication_id is not None and series["publication_id"] != publication_id
    ):
        raise err("ERR_SERIES_NOT_FOUND", "RenewalSeries id does not exist")
    return series


def get_renewal_event(event_id, subscription_id=None):
    ev = store.renewal_events.get(event_id)
    if ev is None or (
        subscription_id is not None and ev["subscription_id"] != subscription_id
    ):
        raise err("ERR_RENEWAL_EVENT_NOT_FOUND", "RenewalEvent id does not exist")
    return ev


def get_batch(batch_id, issue_id=None):
    batch = store.batches.get(batch_id)
    if batch is None or (issue_id is not None and batch["issue_id"] != issue_id):
        raise err(
            "ERR_BATCH_NOT_FOUND", "MailingBatch id does not exist on this Issue"
        )
    return batch


def get_label(label_id, batch_id=None):
    lbl = store.labels.get(label_id)
    if lbl is None or (batch_id is not None and lbl["batch_id"] != batch_id):
        raise err("ERR_BATCH_NOT_FOUND", "MailingLabel id does not exist")
    return lbl


def get_postal_statement(statement_id):
    ps = store.postal_statements.get(statement_id)
    if ps is None:
        raise err("ERR_BATCH_NOT_FOUND", "PostalStatement id does not exist")
    return ps


def get_order(order_id, publication_id=None):
    order = store.back_issue_orders.get(order_id)
    if order is None or (
        publication_id is not None
        and order["_publication_id"] != publication_id
    ):
        raise err("ERR_ORDER_NOT_FOUND", "BackIssueOrder id does not exist")
    return order


def get_entitlement(entitlement_id, subscription_id=None):
    ent = store.entitlements.get(entitlement_id)
    if ent is None or (
        subscription_id is not None and ent["subscription_id"] != subscription_id
    ):
        raise err(
            "ERR_SUBSCRIPTION_NOT_FOUND", "DigitalEntitlement id does not exist"
        )
    return ent


def get_revenue_entry(entry_id):
    entry = store.revenue_entries.get(entry_id)
    if entry is None:
        raise err(
            "ERR_SUBSCRIPTION_NOT_FOUND", "DeferredRevenueEntry id does not exist"
        )
    return entry


def get_audit(audit_id, publication_id=None):
    audit = store.audits.get(audit_id)
    if audit is None or (
        publication_id is not None and audit["publication_id"] != publication_id
    ):
        raise err("ERR_AUDIT_NOT_FOUND", "CirculationAuditRecord id does not exist")
    return audit


# ---------------------------------------------------------------------------
# Derived state helpers
# ---------------------------------------------------------------------------


def issue_sequence(publication_id):
    """Issues of a publication in sequence order: volume, issue number."""
    seq = [i for i in store.issues.values() if i["publication_id"] == publication_id]
    seq.sort(key=lambda i: (i["volume_number"], i["issue_number"], i["_seq"]))
    return seq


def issue_seq_index(publication_id, issue_id):
    for idx, issue in enumerate(issue_sequence(publication_id)):
        if issue["id"] == issue_id:
            return idx
    return None


def recompute_remaining(sub):
    sub["issues_remaining"] = max(
        0,
        sub["term_issues"] - sub["issues_served"] - sub["issues_suspended_count"],
    )


def open_term(subscription_id):
    """Latest OPEN (or FULLY_RECOGNIZED open-balance) term; the current term."""
    terms = [
        t for t in store.terms.values() if t["subscription_id"] == subscription_id
    ]
    if not terms:
        return None
    terms.sort(key=lambda t: t["term_index"])
    return terms[-1]


def terms_of(subscription_id):
    terms = [
        t for t in store.terms.values() if t["subscription_id"] == subscription_id
    ]
    terms.sort(key=lambda t: t["_seq"])
    return terms


def recompute_circulation_class(subscriber_id):
    """PAID tier -> PAID_QUALIFIED; CONTROLLED/COMPLIMENTARY ->
    CONTROLLED_QUALIFIED; no live subscriptions -> NON_QUALIFIED."""
    subscriber = store.subscribers.get(subscriber_id)
    if subscriber is None:
        return
    live_statuses = {"ACTIVE", "SUSPENDED", "GRACE"}
    tiers = [
        s["qualification_tier"]
        for s in store.subscriptions.values()
        if s["subscriber_id"] == subscriber_id and s["status"] in live_statuses
    ]
    if "PAID" in tiers:
        subscriber["circulation_class"] = "PAID_QUALIFIED"
    elif tiers:
        subscriber["circulation_class"] = "CONTROLLED_QUALIFIED"
    else:
        subscriber["circulation_class"] = "NON_QUALIFIED"


def newsstand_sold(issue_id):
    """Copies decremented from newsstand inventory (fulfilled, not refunded)."""
    return sum(
        o["quantity"]
        for o in store.back_issue_orders.values()
        if o["issue_id"] == issue_id
        and o["status"] in ("FULFILLED", "SHIPPED", "DELIVERED")
    )


def newsstand_available(issue):
    return issue["newsstand_buffer_copies"] - newsstand_sold(issue["id"])


def paid_percentage_bps(paid_count, total_count):
    """Integer basis points, truncated (floor); zero when total is zero."""
    if total_count == 0:
        return 0
    return (paid_count * 10000) // total_count


# ---------------------------------------------------------------------------
# Deferred revenue (PRD 2.10 / 3.5; calculations table)
# ---------------------------------------------------------------------------


def post_revenue_entry(term, issue_id, amount_cents, variant, entry_type, recognized_at):
    entry = new_record(common_fields=False)
    entry.update(
        {
            "subscription_term_id": term["id"],
            "issue_id": issue_id,
            "recognized_at": recognized_at,
            "amount_cents": int(amount_cents),
            "variant": variant,
            "entry_type": entry_type,
        }
    )
    store.revenue_entries[entry["id"]] = entry
    return entry


def apply_recognition(term, amount):
    term["recognized_balance_cents"] += amount
    term["deferred_balance_cents"] -= amount
    if term["deferred_balance_cents"] == 0 and term["status"] == "OPEN":
        term["status"] = "FULLY_RECOGNIZED"
    touch(term)


def recognition_entry_count(term):
    return sum(
        1
        for e in store.revenue_entries.values()
        if e["subscription_term_id"] == term["id"] and e["entry_type"] == "RECOGNITION"
    )


def recognize_pro_rata(term, issue):
    """PRO_RATA_ISSUE: equal per-issue slices, round half up at the division;
    the final issue absorbs the rounding residual."""
    gross = term["gross_amount_cents"]
    total = term["issues_in_term"]
    if recognition_entry_count(term) < total - 1:
        amount = round_half_up_cents(Decimal(gross) / Decimal(total))
    else:
        amount = gross - term["recognized_balance_cents"]
    post_revenue_entry(
        term, issue["id"], amount, "PRO_RATA_ISSUE", "RECOGNITION", issue["mail_date"]
    )
    apply_recognition(term, amount)
    return amount


def straight_line_span_months(term):
    pub = store.publications.get(term["_publication_id"])
    frequency = pub["frequency"] if pub else "MONTHLY"
    n = term["issues_in_term"]
    if frequency == "QUARTERLY":
        return n * 3
    issues_per_month = 4 if frequency == "WEEKLY" else 1
    return -(-n // issues_per_month)  # ceil


def straight_line_month_pass(new_now):
    """Month-end recognition for OPEN STRAIGHT_LINE_MONTH terms: each covered
    month whose month-end has been reached recognizes floor(gross/N); the
    final month also absorbs the residual."""
    for term in list(store.terms.values()):
        if term["status"] != "OPEN":
            continue
        if term["recognition_variant"] != "STRAIGHT_LINE_MONTH":
            continue
        gross = term["gross_amount_cents"]
        n_months = straight_line_span_months(term)
        if n_months <= 0:
            continue
        base = gross // n_months
        residual = gross - base * n_months
        recognized_so_far = recognition_entry_count(term)
        start_year, start_month = term["created_at"].year, term["created_at"].month
        for k in range(recognized_so_far, n_months):
            month_index = start_month - 1 + k
            y = start_year + month_index // 12
            m = month_index % 12 + 1
            end = month_end_instant(y, m)
            if end > new_now:
                break
            amount = base + residual if k == n_months - 1 else base
            post_revenue_entry(
                term, None, amount, "STRAIGHT_LINE_MONTH", "RECOGNITION", end
            )
            apply_recognition(term, amount)
            if term["status"] != "OPEN":
                break


# ---------------------------------------------------------------------------
# Postal rate calculation (per-piece; round half up at final step only)
# ---------------------------------------------------------------------------

_ENTRY_DISCOUNT_BPS = {"ORIGIN": 0, "DDU": 2100, "DSCF": 1300, "SCF": 700}


def postal_rate_cents(postal_class, entry_point, piece_weight_oz, is_controlled_copy):
    w = Decimal(str(piece_weight_oz))
    if postal_class == "PERIODICAL":
        if w <= Decimal("3.3"):
            base = 28
        elif w <= Decimal("6.0"):
            base = 41
        elif w <= Decimal("10.0"):
            base = 58
        else:
            base = 58 + 7 * int(math.ceil(w - Decimal("10.0")))
    elif postal_class == "STANDARD":
        if w <= Decimal("3.3"):
            base = 52
        elif w <= Decimal("6.0"):
            base = 74
        else:
            base = 74 + 11 * int(math.ceil(w - Decimal("6.0")))
    else:  # FIRST_CLASS
        if w <= Decimal("1.0"):
            base = 68
        elif w <= Decimal("2.0"):
            base = 92
        elif w <= Decimal("3.0"):
            base = 116
        else:
            base = 116 + 24 * int(math.ceil(w - Decimal("3.0")))
    discount_bps = _ENTRY_DISCOUNT_BPS.get(entry_point, 0)
    surcharge_bps = (
        500 if (is_controlled_copy and postal_class == "PERIODICAL") else 0
    )
    amount = Decimal(base) * Decimal(10000 - discount_bps + surcharge_bps) / Decimal(
        10000
    )
    return int(amount.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))


# ---------------------------------------------------------------------------
# Subscriptions: terms, gifts, cancellations, expiry
# ---------------------------------------------------------------------------


def compute_term_end_issue_id(publication_id, start_issue_id, term_issues):
    seq = issue_sequence(publication_id)
    idx = None
    for i, issue in enumerate(seq):
        if issue["id"] == start_issue_id:
            idx = i
            break
    if idx is None:
        return None
    end_idx = idx + term_issues - 1
    if 0 <= end_idx < len(seq):
        return seq[end_idx]["id"]
    return None


def create_term(sub, term_index, start_issue_id, issues_in_term, gross_cents):
    pub = store.publications[sub["publication_id"]]
    term = new_record()
    term.update(
        {
            "subscription_id": sub["id"],
            "term_index": term_index,
            "term_start_issue_id": start_issue_id,
            "term_end_issue_id": compute_term_end_issue_id(
                sub["publication_id"], start_issue_id, issues_in_term
            ),
            "issues_in_term": issues_in_term,
            "gross_amount_cents": gross_cents,
            "deferred_balance_cents": gross_cents,
            "recognized_balance_cents": 0,
            # Snapshot of Publication.deferred_revenue_method at term start.
            "recognition_variant": pub["deferred_revenue_method"],
            "status": "OPEN",
            "_publication_id": sub["publication_id"],
        }
    )
    store.terms[term["id"]] = term
    return term


def apply_gift_credit(gift_sub):
    """Donor credit: 10% of the gift price (round half up), capped at the
    donor OPEN term's deferred balance; posts as a RECOGNITION entry."""
    donor_id = gift_sub["donor_subscriber_id"]
    if not donor_id:
        return
    donor_term = None
    for sub in store.subscriptions.values():
        if (
            sub["subscriber_id"] == donor_id
            and sub["publication_id"] == gift_sub["publication_id"]
            and sub["qualification_tier"] == "PAID"
            and sub["status"] == "ACTIVE"
        ):
            candidate = open_term(sub["id"])
            if candidate is not None and candidate["status"] == "OPEN":
                donor_term = candidate
                break
    if donor_term is None:
        return
    credit = min(
        round_half_up_cents(
            Decimal(gift_sub["price_paid_cents"]) * GIFT_CREDIT_BPS / Decimal(10000)
        ),
        donor_term["deferred_balance_cents"],
    )
    if credit <= 0:
        return
    post_revenue_entry(
        donor_term,
        None,
        credit,
        donor_term["recognition_variant"],
        "RECOGNITION",
        store.now(),
    )
    apply_recognition(donor_term, credit)


def suspend_subscription(sub, cascade_from_publication=False):
    sub["status"] = "SUSPENDED"
    # Snapshot how many in-window issues have already mailed, so resume can
    # count the issues missed during the suspension.
    sub["_mailed_snapshot"] = mailed_issue_count_for(sub)
    touch(sub)


def mailed_issue_count_for(sub):
    """MAILED/FINALIZED issues on the publication within this subscription's
    service window [start_idx, start_idx + term_issues)."""
    seq = issue_sequence(sub["publication_id"])
    start_idx = None
    for i, issue in enumerate(seq):
        if issue["id"] == sub["start_issue_id"]:
            start_idx = i
            break
    if start_idx is None:
        start_idx = 0
    window = seq[start_idx : start_idx + sub["term_issues"]]
    return sum(1 for i in window if i["status"] in ("MAILED", "FINALIZED"))


def resume_subscription(sub):
    missed = max(0, mailed_issue_count_for(sub) - sub.get("_mailed_snapshot", 0))
    sub["issues_suspended_count"] += missed
    recompute_remaining(sub)
    sub["status"] = "ACTIVE"
    touch(sub)


def expire_pending_renewal_events(subscription_id):
    for ev in store.renewal_events.values():
        if ev["subscription_id"] == subscription_id and ev["response"] == "PENDING":
            ev["response"] = "EXPIRED"
            touch(ev)


def expire_subscription(sub):
    """GRACE -> EXPIRED (30 days after grace entry), with optional cyclic
    regeneration under expire_action == CONVERT_TO_CONTROLLED."""
    sub["status"] = "EXPIRED"
    touch(sub)
    expire_pending_renewal_events(sub["id"])
    recompute_circulation_class(sub["subscriber_id"])
    if sub["expire_action"] == "CONVERT_TO_CONTROLLED":
        new_sub = new_record()
        new_sub.update(
            {
                "subscriber_id": sub["subscriber_id"],
                "publication_id": sub["publication_id"],
                "start_issue_id": sub["start_issue_id"],
                "term_issues": sub["term_issues"],
                "price_paid_cents": 0,
                "qualification_tier": "CONTROLLED",
                "payment_method": "NONE",
                "is_gift": False,
                "donor_subscriber_id": None,
                "renewal_series_code": sub["renewal_series_code"],
                "renewal_effort_number": 0,
                "issues_served": 0,
                "issues_suspended_count": 0,
                "issues_remaining": sub["term_issues"],
                "auto_renew": False,
                "expire_action": sub["expire_action"],
                "status": "ACTIVE",
                "_entered_grace_at": None,
                "_mailed_snapshot": 0,
            }
        )
        store.subscriptions[new_sub["id"]] = new_sub
        create_term(new_sub, 1, new_sub["start_issue_id"], new_sub["term_issues"], 0)
        recompute_circulation_class(new_sub["subscriber_id"])


def run_system_transitions(old_now, new_now):
    """Time-based transitions fired when the logical clock is set."""
    if new_now <= old_now:
        return
    # GRACE -> EXPIRED once the 30-day grace period has elapsed.
    for sub in list(store.subscriptions.values()):
        if sub["status"] == "GRACE" and sub.get("_entered_grace_at") is not None:
            if new_now >= sub["_entered_grace_at"] + timedelta(days=GRACE_PERIOD_DAYS):
                expire_subscription(sub)
    # Month-end straight-line recognition pass.
    straight_line_month_pass(new_now)


# ---------------------------------------------------------------------------
# Renewal efforts
# ---------------------------------------------------------------------------


def default_series_for(publication_id):
    for series in store.renewal_series.values():
        if series["publication_id"] == publication_id and series["is_default"]:
            return series
    return None


def find_series_by_code(publication_id, code):
    for series in store.renewal_series.values():
        if series["publication_id"] == publication_id and series["series_code"] == code:
            return series
    return None


def expiry_reference(sub):
    """Instant at which the subscription expires (for renewal windows)."""
    if sub.get("_entered_grace_at") is not None:
        return sub["_entered_grace_at"] + timedelta(days=GRACE_PERIOD_DAYS)
    term = open_term(sub["id"])
    if term is not None and term["term_end_issue_id"] in store.issues:
        return store.issues[term["term_end_issue_id"]]["mail_date"] + timedelta(
            days=GRACE_PERIOD_DAYS
        )
    pub = store.publications.get(sub["publication_id"])
    per_year = ISSUES_PER_YEAR.get(pub["frequency"], 12) if pub else 12
    days = int(math.ceil(sub["term_issues"] * 365 / per_year)) + GRACE_PERIOD_DAYS
    # The term's temporal extent is issue-anchored (PRD 3.2: term_end_issue_id
    # is "the issue term_issues minus one sequential issues after the start
    # issue"; PRD 3.6: grace — and hence expiry — is entered when the term's
    # issues have been served). When the issue sequence does not yet extend to
    # the term's end, project expiry from the start issue's scheduled mail
    # date; never from the operator-controlled clock instant at which the term
    # row happened to be created.
    start_issue = store.issues.get(sub["start_issue_id"])
    if start_issue is not None:
        base = start_issue["mail_date"]
    elif term is not None:
        base = term["created_at"]
    else:
        base = sub["created_at"]
    return base + timedelta(days=days)


def renewal_window_open(sub, series, effort_number):
    if not (1 <= effort_number <= series["max_efforts"]):
        return False
    offset = series["effort_offsets_days"][effort_number - 1]
    return store.now() >= expiry_reference(sub) + timedelta(days=offset)


def fire_renewal_event(sub, series):
    """Create the next RenewalEvent; the previous PENDING event lapses."""
    expire_pending_renewal_events(sub["id"])
    effort_number = sub["renewal_effort_number"] + 1
    ev = new_record()
    ev.update(
        {
            "subscription_id": sub["id"],
            "series_code": series["series_code"],
            "effort_number": effort_number,
            "sent_at": store.now(),
            "offered_price_cents": series["effort_pricing_cents"][effort_number - 1],
            "response": "PENDING",
            "responded_at": None,
        }
    )
    store.renewal_events[ev["id"]] = ev
    sub["renewal_effort_number"] = effort_number
    touch(sub)
    return ev


# ---------------------------------------------------------------------------
# Mailing: labels, distribution
# ---------------------------------------------------------------------------


def format_address_block(subscriber):
    lines = [subscriber["full_name"], subscriber["address_line1"]]
    if subscriber["address_line2"]:
        lines.append(subscriber["address_line2"])
    lines.append(
        f"{subscriber['city']}, {subscriber['state_code']} {subscriber['postal_code']}"
    )
    if subscriber["country_code"] != "US":
        lines.append(subscriber["country_code"])
    return "\n".join(lines)


def qualified_subscriptions_for_issue(issue):
    """ACTIVE, deliverable, issues remaining, and started no later than this
    issue in the publication's sequence (print-run qualification)."""
    idx = issue_seq_index(issue["publication_id"], issue["id"])
    result = []
    for sub in store.subscriptions.values():
        if sub["publication_id"] != issue["publication_id"]:
            continue
        if sub["status"] != "ACTIVE":
            continue
        subscriber = store.subscribers.get(sub["subscriber_id"])
        if subscriber is None or not subscriber["is_deliverable"]:
            continue
        if sub["issues_remaining"] <= 0:
            continue
        start_idx = issue_seq_index(issue["publication_id"], sub["start_issue_id"])
        if idx is not None and start_idx is not None and start_idx > idx:
            continue
        result.append(sub)
    result.sort(key=lambda s: s["_seq"])
    return result


def label_eligible_subscriptions(issue, batch):
    """Label generation (MailingBatch DRAFT -> LABELS_GENERATED): one label per
    subscription that is ACTIVE, on this publication, has issues remaining,
    and belongs to a deliverable subscriber, filtered by the batch's
    inclusion rule (DOMESTIC -> US, FOREIGN -> non-US, NEWSSTAND -> none).
    Controlled copies ride only when is_controlled_copy_included is true."""
    result = []
    if batch["batch_label"] == "NEWSSTAND":
        return result
    for sub in store.subscriptions.values():
        if sub["publication_id"] != issue["publication_id"]:
            continue
        if sub["status"] != "ACTIVE":
            continue
        if sub["issues_remaining"] <= 0:
            continue
        subscriber = store.subscribers.get(sub["subscriber_id"])
        if subscriber is None or not subscriber["is_deliverable"]:
            continue
        if batch["batch_label"] == "DOMESTIC" and subscriber["country_code"] != "US":
            continue
        if batch["batch_label"] == "FOREIGN" and subscriber["country_code"] == "US":
            continue
        if not batch["is_controlled_copy_included"] and sub["qualification_tier"] in (
            "CONTROLLED",
            "COMPLIMENTARY",
        ):
            continue
        result.append((sub, subscriber))
    result.sort(key=lambda pair: pair[0]["_seq"])
    return result


def served_subscriptions_for_issue(issue):
    """Subscriptions served at mailing: a label was generated for them on one
    of this issue's batches and they are still ACTIVE with issues remaining."""
    batch_ids = [
        b["id"] for b in store.batches.values() if b["issue_id"] == issue["id"]
    ]
    seen = []
    for lbl in sorted(
        (l for l in store.labels.values() if l["batch_id"] in batch_ids),
        key=lambda l: l["_seq"],
    ):
        if lbl["subscription_id"] in seen:
            continue
        sub = store.subscriptions.get(lbl["subscription_id"])
        if sub is None:
            continue
        if sub["status"] != "ACTIVE":
            continue
        if sub["issues_remaining"] <= 0:
            continue
        seen.append(lbl["subscription_id"])
        yield sub


def grant_gift_entitlement(sub, issue):
    ent = new_record()
    ent.update(
        {
            "subscription_id": sub["id"],
            "issue_id": issue["id"],
            "access_level": "FULL",
            "granted_at": store.now(),
            "revoked_at": None,
            "revocation_reason": None,
        }
    )
    store.entitlements[ent["id"]] = ent
    return ent


def auto_renew_subscription(sub):
    """issues_remaining hit zero with auto_renew: skip GRACE, create the next
    term, and stand the subscription RENEWED (terminal marker)."""
    previous = open_term(sub["id"])
    next_index = previous["term_index"] + 1 if previous else 1
    start_issue_id = sub["start_issue_id"]
    if previous is not None and previous["term_end_issue_id"]:
        seq = issue_sequence(sub["publication_id"])
        for i, issue in enumerate(seq):
            if issue["id"] == previous["term_end_issue_id"] and i + 1 < len(seq):
                start_issue_id = seq[i + 1]["id"]
                break
    create_term(
        sub, next_index, start_issue_id, sub["term_issues"], sub["price_paid_cents"]
    )
    sub["issues_served"] = 0
    sub["issues_suspended_count"] = 0
    recompute_remaining(sub)
    sub["status"] = "RENEWED"
    touch(sub)


def enter_grace(sub):
    sub["status"] = "GRACE"
    sub["_entered_grace_at"] = store.now()
    touch(sub)
