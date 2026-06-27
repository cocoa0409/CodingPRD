"""Serialize internal records into API output shapes.

Each entity exposes an explicit public field list (so internal bookkeeping keys
like _seq never leak). Computed fields are filled by the recompute helpers in
services and stored on the record, so serialization is a straight projection.
"""

# Public fields per entity, in the order declared by the scaffold.
TITLE_FIELDS = [
    "id", "isbn13", "name", "category", "list_price_cents", "returnable",
    "demand_flag", "pod_eligible", "on_hand_qty", "reserved_qty", "status",
    "created_at", "updated_at", "version",
]
STOCK_ITEM_FIELDS = [
    "id", "title_id", "source", "cost_cents", "state",
    "reserved_order_line_id", "consignment_copy_id",
    "created_at", "updated_at", "version",
]
MEMBER_FIELDS = [
    "id", "email", "full_name", "tier", "store_credit_cents", "loyalty_points",
    "is_local_author", "status", "created_at", "updated_at", "version",
]
CREDIT_LEDGER_FIELDS = [
    "id", "member_id", "delta_cents", "reason", "ref_id", "created_at",
]
SALES_ORDER_FIELDS = [
    "id", "member_id", "payment_status", "fulfillment_status",
    "credit_redeemed_cents", "subtotal_cents", "member_discount_cents",
    "net_paid_cents", "points_provisional", "points_final",
    "created_at", "updated_at", "version",
]
ORDER_LINE_FIELDS = [
    "id", "order_id", "title_id", "quantity", "unit_price_cents",
    "line_total_cents", "reserved_qty", "created_at", "updated_at", "version",
]
SPECIAL_ORDER_FIELDS = [
    "id", "member_id", "title_id", "quantity", "fulfillment_method", "state",
    "quoted_unit_cents", "promised_eta", "revision_count",
    "created_at", "updated_at", "version",
]
PUBLISHER_RETURN_FIELDS = [
    "id", "title_id", "quantity", "state", "credit_unit_cents",
    "credit_total_cents", "created_at", "updated_at", "version",
]
AUTHOR_EVENT_FIELDS = [
    "id", "title_id", "name", "starts_at", "capacity", "base_price_cents",
    "tickets_sold", "state", "created_at", "updated_at", "version",
]
EVENT_TICKET_FIELDS = [
    "id", "event_id", "member_id", "price_paid_cents", "state",
    "created_at", "updated_at", "version",
]
BUYBACK_FIELDS = [
    "id", "member_id", "state", "offer_total_cents",
    "created_at", "updated_at", "version",
]
BUYBACK_LINE_FIELDS = [
    "id", "buyback_id", "title_id", "condition_grade", "quantity",
    "line_offer_cents", "created_at", "updated_at", "version",
]
CONSIGNMENT_AGREEMENT_FIELDS = [
    "id", "author_member_id", "title_id", "units_sold_to_date",
    "total_payout_cents", "state", "created_at", "updated_at", "version",
]
CONSIGNMENT_COPY_FIELDS = [
    "id", "agreement_id", "sale_price_cents", "state", "payout_cents",
    "created_at", "updated_at", "version",
]


def _project(rec, fields):
    return {f: rec.get(f) for f in fields}


def title_out(rec):
    from services import recompute_title_counts
    recompute_title_counts(rec, mutate=False)
    return _project(rec, TITLE_FIELDS)


def stock_item_out(rec):
    return _project(rec, STOCK_ITEM_FIELDS)


def member_out(rec):
    from services import recompute_member_balances
    recompute_member_balances(rec)
    return _project(rec, MEMBER_FIELDS)


def credit_ledger_out(rec):
    return _project(rec, CREDIT_LEDGER_FIELDS)


def sales_order_out(rec):
    return _project(rec, SALES_ORDER_FIELDS)


def order_line_out(rec):
    return _project(rec, ORDER_LINE_FIELDS)


def special_order_out(rec):
    return _project(rec, SPECIAL_ORDER_FIELDS)


def publisher_return_out(rec):
    return _project(rec, PUBLISHER_RETURN_FIELDS)


def author_event_out(rec):
    return _project(rec, AUTHOR_EVENT_FIELDS)


def event_ticket_out(rec):
    return _project(rec, EVENT_TICKET_FIELDS)


def buyback_out(rec):
    return _project(rec, BUYBACK_FIELDS)


def buyback_line_out(rec):
    return _project(rec, BUYBACK_LINE_FIELDS)


def consignment_agreement_out(rec):
    return _project(rec, CONSIGNMENT_AGREEMENT_FIELDS)


def consignment_copy_out(rec):
    return _project(rec, CONSIGNMENT_COPY_FIELDS)
