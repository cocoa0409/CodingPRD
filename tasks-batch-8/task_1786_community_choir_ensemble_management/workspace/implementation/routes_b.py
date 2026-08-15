"""Routes: dues invoices & payments (waterfall), scholarship grants."""

import store
from domain import (
    GRANT_DECISIONS, OPEN_INVOICE_STATUSES, PAYMENT_METHODS, after_invoice_cured,
    dues_final, dues_provisional, gate_season, invoice_balance,
    reveal_invoice_final, sync_member, treasury_credit, treasury_debit,
)
from errors import ApiError
from routes_common import (
    apply_filters, many, member_ownership_check, one, route,
    scope_member_filter,
)
from serializers import grant_view, invoice_view, payment_view
from store import all_of, new_row, touch
from timeutil import clock
from validate import check_body, check_enum, get_or_404, resolve_ids

INVOICE_READ_ROLES = ("President", "Treasurer", "ChoirDirector", "Member")
PAYMENT_READ_ROLES = ("President", "Treasurer", "Member")
GRANT_READ_ROLES = ("President", "Treasurer", "Member")


# ------------------------------------------------------------- dues invoices
@route("POST", "/v1/dues-invoices", roles=["Treasurer"], code=201)
def create_invoice(ctx):
    ids = resolve_ids(ctx["body"], (store.members, "member_id"))
    body = check_body(ctx["body"], {"member_id": ("string", True)})
    member = ids.get("member_id") or get_or_404(store.members, body["member_id"])
    season = store.seasons[member["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    if member["status"] not in ("ENROLLED", "ACTIVE", "PROBATION", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "invoices can only be issued for ENROLLED-or-later members")
    now = clock.now
    invoice = new_row(
        store.dues_invoices,
        member_id=member["id"],
        season_id=member["season_id"],
        issued_at=clock.now_server_string(),
        provisional_amount_cents=dues_provisional(season, now),
        final_amount_cents=None,
        scholarship_applied_cents=0,
        paid_cents=0,
        late_fee_cents=0,
        status="ISSUED",
    )
    invoice["_issued_dt"] = now
    sync_member(member)
    return one(invoice_view, invoice, 201)


@route("GET", "/v1/dues-invoices/{rid}", roles=INVOICE_READ_ROLES)
def get_invoice(ctx):
    invoice = get_or_404(store.dues_invoices, ctx["path"]["rid"])
    member_ownership_check(ctx, invoice["member_id"])
    return one(invoice_view, invoice)


@route("GET", "/v1/dues-invoices", roles=INVOICE_READ_ROLES)
def list_invoices(ctx):
    filters = scope_member_filter(ctx, {
        "member_id": ctx["args"].get("member_id"),
        "season_id": ctx["args"].get("season_id"),
        "status": ctx["args"].get("status"),
    })
    return many(invoice_view, apply_filters(all_of(store.dues_invoices), filters), ctx["args"])


# ------------------------------------------------------------- dues payments
@route("POST", "/v1/dues-payments", roles=["Treasurer"], code=201)
def create_payment(ctx):
    ids = resolve_ids(ctx["body"], (store.members, "member_id"))
    body = check_body(ctx["body"], {
        "member_id": ("string", True),
        "amount_cents": ("int", True),
        "method": ("string", True),
    })
    member = ids.get("member_id") or get_or_404(store.members, body["member_id"])
    check_enum(body, "method", PAYMENT_METHODS)
    if body["amount_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must not be negative")
    season = store.seasons[member["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    amount = body["amount_cents"]
    now = clock.now

    # payment_waterfall: reveal finals (hypothetically), walk open invoices
    # oldest-first, reject the whole payment on any remainder.
    invoices = [i for i in store.dues_invoices.values() if i["member_id"] == member["id"]]
    pending_finals = {}
    for inv in invoices:
        if inv["final_amount_cents"] is None:
            pending_finals[inv["id"]] = dues_final(season, now)
    open_invoices = sorted(
        (i for i in invoices if i["status"] in OPEN_INVOICE_STATUSES),
        key=lambda i: (i["_issued_dt"], i["_seq"]),
    )

    def effective_balance(inv):
        amount_due = pending_finals.get(inv["id"])
        if amount_due is None:
            amount_due = inv["final_amount_cents"]
        if amount_due is None:
            amount_due = inv["provisional_amount_cents"]
        return amount_due - inv["scholarship_applied_cents"] - inv["paid_cents"] + inv["late_fee_cents"]

    remaining = amount
    allocations = []
    for inv in open_invoices:
        bal = effective_balance(inv)
        if bal <= 0 or remaining <= 0:
            continue
        take = min(remaining, bal)
        allocations.append({"invoice_id": inv["id"], "amount_cents": take})
        remaining -= take
    if remaining > 0:
        raise ApiError("ERR_OVERPAYMENT", "payment exceeds the member's total open invoice balance")

    # commit: reveals, payment row, treasury credit, invoice transitions
    for inv in invoices:
        if inv["id"] in pending_finals:
            inv["final_amount_cents"] = pending_finals[inv["id"]]
            touch(inv)
    payment = new_row(
        store.dues_payments,
        member_id=member["id"],
        amount_cents=amount,
        method=body["method"],
        allocations=allocations,
        status="POSTED",
        received_at=clock.now_server_string(),
    )
    treasury_credit(season, amount)
    for alloc in allocations:
        inv = store.dues_invoices[alloc["invoice_id"]]
        inv["paid_cents"] += alloc["amount_cents"]
        if invoice_balance(inv) == 0:
            inv["status"] = "PAID"
        elif inv["status"] == "ISSUED":
            inv["status"] = "PARTIAL"
        touch(inv)
        if inv["status"] == "PAID":
            after_invoice_cured(inv)
    sync_member(member)
    return one(payment_view, payment, 201)


@route("GET", "/v1/dues-payments/{rid}", roles=PAYMENT_READ_ROLES)
def get_payment(ctx):
    payment = get_or_404(store.dues_payments, ctx["path"]["rid"])
    member_ownership_check(ctx, payment["member_id"])
    return one(payment_view, payment)


@route("GET", "/v1/dues-payments", roles=PAYMENT_READ_ROLES)
def list_payments(ctx):
    filters = scope_member_filter(ctx, {
        "member_id": ctx["args"].get("member_id"),
        "status": ctx["args"].get("status"),
    })
    return many(payment_view, apply_filters(all_of(store.dues_payments), filters), ctx["args"])


@route("POST", "/v1/dues-payments/{rid}/refund", roles=["Treasurer"])
def refund_payment(ctx):
    payment = get_or_404(store.dues_payments, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    member = store.members[payment["member_id"]]
    season = store.seasons[member["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    if payment["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", "only a POSTED payment can be refunded")
    treasury_debit(season, payment["amount_cents"], check=True)
    payment["status"] = "REFUNDED"
    touch(payment)
    reopened = False
    for alloc in payment["allocations"]:
        inv = store.dues_invoices[alloc["invoice_id"]]
        inv["paid_cents"] -= alloc["amount_cents"]
        if inv["status"] == "PAID":
            inv["status"] = "ISSUED"
            reopened = True
        touch(inv)
    if reopened and member["status"] == "ACTIVE":
        member["status"] = "ENROLLED"
        touch(member)
    sync_member(member)
    return one(payment_view, payment)


# --------------------------------------------------------- scholarship grants
@route("POST", "/v1/scholarship-grants", roles=["Member", "Treasurer"], code=201)
def create_grant(ctx):
    body = ctx["body"]
    if ctx["role"] == "Member" and isinstance(body, dict) and body.get("member_id") is not None:
        member_ownership_check(ctx, body["member_id"])
    ids = resolve_ids(body, (store.members, "member_id"))
    body = check_body(body, {
        "member_id": ("string", True),
        "requested_cents": ("int", True),
        "need_note": ("string", False),
    })
    member = ids.get("member_id") or get_or_404(store.members, body["member_id"])
    season = store.seasons[member["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    grant = new_row(
        store.scholarship_grants,
        member_id=member["id"],
        season_id=member["season_id"],
        requested_cents=body["requested_cents"],
        need_note=body.get("need_note"),
        status="REQUESTED",
        approved_cents=None,
        invoice_id=None,
        decided_by_user_id=None,
    )
    return one(grant_view, grant, 201)


@route("GET", "/v1/scholarship-grants/{rid}", roles=GRANT_READ_ROLES)
def get_grant(ctx):
    grant = get_or_404(store.scholarship_grants, ctx["path"]["rid"])
    member_ownership_check(ctx, grant["member_id"])
    return one(grant_view, grant)


@route("GET", "/v1/scholarship-grants", roles=GRANT_READ_ROLES)
def list_grants(ctx):
    filters = scope_member_filter(ctx, {
        "member_id": ctx["args"].get("member_id"),
        "season_id": ctx["args"].get("season_id"),
        "invoice_id": ctx["args"].get("invoice_id"),
        "status": ctx["args"].get("status"),
    })
    return many(grant_view, apply_filters(all_of(store.scholarship_grants), filters), ctx["args"])


@route("POST", "/v1/scholarship-grants/{rid}/decision", roles=["Treasurer"])
def decide_grant(ctx):
    grant = get_or_404(store.scholarship_grants, ctx["path"]["rid"])
    body = check_body(ctx["body"], {
        "decision": ("string", True),
        "approved_cents": ("int", False),
    })
    check_enum(body, "decision", GRANT_DECISIONS)
    season = store.seasons[grant["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "only a REQUESTED grant can be decided")
    grant["decided_by_user_id"] = ctx["uid"]
    if body["decision"] == "REJECT":
        grant["status"] = "REJECTED"
        touch(grant)
        return one(grant_view, grant)
    approved = body.get("approved_cents")
    if approved is None:
        approved = min(grant["requested_cents"], season["pool_available_cents"])
    if approved <= 0 or approved > season["pool_available_cents"]:
        raise ApiError("ERR_SCHOLARSHIP_POOL_EXHAUSTED", "approved amount exceeds the available pool")
    grant["approved_cents"] = approved
    grant["status"] = "APPROVED"
    season["pool_reserved_cents"] += approved
    season["pool_available_cents"] -= approved
    touch(season)
    touch(grant)
    return one(grant_view, grant)


@route("POST", "/v1/scholarship-grants/{rid}/apply", roles=["Treasurer"])
def apply_grant(ctx):
    grant = get_or_404(store.scholarship_grants, ctx["path"]["rid"])
    body = ctx["body"]
    invoice = None
    if isinstance(body, dict) and body.get("invoice_id") is not None:
        invoice = get_or_404(store.dues_invoices, body["invoice_id"])
    body = check_body(body, {
        "invoice_id": ("string", True),
        "amount_cents": ("int", False),
    })
    if body.get("amount_cents") is not None and body["amount_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be positive")
    season = store.seasons[grant["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    # state tier: grant first, then the target invoice
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_GRANT_NOT_APPROVED", "the grant is not APPROVED")
    if invoice["status"] not in OPEN_INVOICE_STATUSES or invoice_balance(invoice) <= 0:
        raise ApiError("ERR_INVOICE_NOT_OPEN", "the invoice is not open with a positive balance")
    reveal_invoice_final(invoice, clock.now)
    bound = min(grant["approved_cents"], invoice_balance(invoice))
    applied = body.get("amount_cents")
    if applied is not None:
        if applied > bound:
            raise ApiError("ERR_GRANT_EXCEEDS_INVOICE_BALANCE", "amount exceeds min(approved, invoice balance)")
    else:
        applied = bound
    season["pool_reserved_cents"] -= grant["approved_cents"]
    season["pool_spent_cents"] += applied
    season["pool_available_cents"] += grant["approved_cents"] - applied
    touch(season)
    invoice["scholarship_applied_cents"] += applied
    if invoice_balance(invoice) == 0:
        invoice["status"] = "WAIVED"
    touch(invoice)
    grant["status"] = "APPLIED"
    grant["invoice_id"] = invoice["id"]
    touch(grant)
    if invoice["status"] == "WAIVED":
        after_invoice_cured(invoice)
    else:
        sync_member(store.members[invoice["member_id"]])
    return one(grant_view, grant)


@route("POST", "/v1/scholarship-grants/{rid}/revoke", roles=["Treasurer"])
def revoke_grant(ctx):
    grant = get_or_404(store.scholarship_grants, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    season = store.seasons[grant["season_id"]]
    gate_season(season, ("OPEN", "REHEARSING"))
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "only an APPROVED grant can be revoked")
    season["pool_reserved_cents"] -= grant["approved_cents"]
    season["pool_available_cents"] += grant["approved_cents"]
    touch(season)
    grant["status"] = "REVOKED"
    touch(grant)
    return one(grant_view, grant)
