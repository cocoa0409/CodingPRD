"""The ordered rejection pipeline of PRD 2.12, checks 1 through 25.

Checks 26..79 are business rules and live in the individual route handlers,
still evaluated in ascending priority order.
"""
from core import (
    EXISTENCE_ORDER, fail, get_body, lookup, read_identity, read_pagination,
    require_role, validate_body,
)


class Ctx(object):
    __slots__ = ("user_id", "role", "raw", "data", "limit", "offset", "refs")

    def __init__(self):
        self.user_id = None
        self.role = None
        self.raw = {}
        self.data = {}
        self.limit = 10
        self.offset = 0
        self.refs = {}

    def get(self, kind):
        return self.refs.get(kind)


# ---------------------------------------------------------------------------
# Advertiser resolution (PRD 2.1 / 2.12 check 4 and check 25)
# ---------------------------------------------------------------------------
def _adv_of_line_item(li):
    if li is None:
        return None
    camp = lookup("campaign", li.get("campaign_id"))
    return camp.get("advertiser_id") if camp else None


def advertiser_id_of(kind, row):
    if row is None:
        return None
    if kind == "advertiser":
        return row["id"]
    if kind in ("budget_plan", "trade_fund_account", "campaign", "invoice"):
        return row.get("advertiser_id")
    if kind == "line_item":
        return _adv_of_line_item(row)
    if kind == "product_assignment":
        return _adv_of_line_item(lookup("line_item", row.get("line_item_id")))
    if kind == "engagement_event":
        return _adv_of_line_item(lookup("line_item", row.get("line_item_id")))
    if kind == "study":
        camp = lookup("campaign", row.get("campaign_id"))
        return camp.get("advertiser_id") if camp else None
    if kind == "dispute":
        inv = lookup("invoice", row.get("invoice_id"))
        return inv.get("advertiser_id") if inv else None
    return None


# order in which an owning advertiser is looked for
_OWNER_PRIORITY = (
    "advertiser", "campaign", "line_item", "invoice", "budget_plan",
    "dispute", "product_assignment", "trade_fund_account", "engagement_event",
    "study",
)


def _resolve_owner(pending):
    """pending: list of (kind, id).  Returns owning advertiser id, or None."""
    by_kind = {}
    for kind, value in pending:
        if value is None:
            continue
        by_kind.setdefault(kind, []).append(value)
    for kind in _OWNER_PRIORITY:
        for value in by_kind.get(kind, []):
            if kind == "advertiser":
                # a direct advertiser reference is the owner whether or not the
                # row exists; existence is a later check
                if lookup("advertiser", value) is not None:
                    return value
                continue
            row = lookup(kind, value)
            owner = advertiser_id_of(kind, row)
            if owner is not None:
                return owner
    return None


def guard(roles, path_refs=(), body_specs=(), paginated=False, body_refs=(),
          occ=None, mutating=False, owner_refs=None):
    """Runs checks 1..25 and returns a populated Ctx.

    path_refs   : iterable of (kind, id) taken from the URL
    body_specs  : iterable of core.F field specifications
    body_refs   : iterable of (kind, body_field_name)
    occ         : (body_field_name, kind, error_id) version expectation
    mutating    : apply check 25 (advertiser not REJECTED/TERMINATED)
    owner_refs  : override list of (kind, field-or-value) used for check 4
    """
    ctx = Ctx()
    # 1 + 2 -- authentication and role recognition
    ctx.user_id, ctx.role = read_identity()
    # 3 -- endpoint authorisation
    require_role(ctx.role, roles)
    ctx.raw = get_body()

    body_ref_list = list(body_refs)

    # 4 -- AdvertiserUser ownership
    if ctx.role == "AdvertiserUser":
        pending = list(path_refs)
        if owner_refs is None:
            for kind, field in body_ref_list:
                value = ctx.raw.get(field)
                if isinstance(value, str):
                    pending.append((kind, value))
        else:
            pending = list(owner_refs)
        owner = _resolve_owner(pending)
        if owner is not None and owner != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "This resource belongs to another advertiser.")

    # 5 -- body shape
    ctx.data = validate_body(ctx.raw, body_specs)

    # 6 -- pagination
    if paginated:
        ctx.limit, ctx.offset = read_pagination()

    # 7..19 -- existence, in the entity order of PRD 2.12
    pending = []
    for kind, value in path_refs:
        pending.append((kind, value, True))
    for kind, field in body_ref_list:
        value = ctx.data.get(field)
        if value is not None:
            pending.append((kind, value, False))
    for kind, _collection, error_id in EXISTENCE_ORDER:
        for pkind, value, _is_path in pending:
            if pkind != kind:
                continue
            row = lookup(kind, value) if isinstance(value, str) else None
            if row is None:
                fail(error_id, "%s does not exist." % kind.replace("_", " ").title())
            ctx.refs.setdefault(kind, row)
            ctx.refs.setdefault(kind + "s", []).append(row)

    # 20..24 -- stale-parent version expectation
    if occ is not None:
        field, kind, error_id = occ
        expected = ctx.data.get(field)
        parent = ctx.refs.get(kind)
        if parent is not None and expected is not None and expected != parent["version"]:
            fail(error_id, "Expected %s %s but the row is at version %s."
                 % (kind, expected, parent["version"]))

    # make the owning advertiser reachable as ctx.get("advertiser")
    adv = ctx.refs.get("advertiser") or _resolve_advertiser_from_refs(ctx)
    if adv is not None:
        ctx.refs["advertiser"] = adv

    # 25 -- terminated / rejected advertiser
    if mutating:
        if adv is not None and adv["onboarding_status"] in ("REJECTED", "TERMINATED"):
            fail("ERR_ADVERTISER_TERMINATED",
                 "Advertiser onboarding_status is %s." % adv["onboarding_status"])
    return ctx


def _resolve_advertiser_from_refs(ctx):
    for kind in _OWNER_PRIORITY:
        row = ctx.refs.get(kind)
        if row is None:
            continue
        owner = advertiser_id_of(kind, row)
        if owner is not None:
            adv = lookup("advertiser", owner)
            if adv is not None:
                return adv
    return None


def advertiser_of(row_kind, row):
    return lookup("advertiser", advertiser_id_of(row_kind, row))
