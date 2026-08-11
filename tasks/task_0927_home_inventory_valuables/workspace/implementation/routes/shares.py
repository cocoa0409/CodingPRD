"""Share grants and redacted redemption (PRD 3.9)."""

import derive
import serializers
import store
from constants import (
    REDACTION_LEVELS,
    SCOPE_KINDS,
    SHARE_DEFAULT_ACCESS_CAP,
    SHARE_MAX_DURATION_DAYS,
)
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from timeutil import add_days, clock, parse_instant

SCOPE_POINTERS = {"ROOM": "scope_room_id", "PACKAGE": "scope_package_id", "CLAIM": "scope_claim_id"}
ALL_POINTERS = ("scope_room_id", "scope_package_id", "scope_claim_id")


def _grant(ctx):
    return ctx.row("share_grant_id")


def _grant_household(ctx):
    return _grant(ctx)["household_id"]


def _share_shape(ctx):
    kind = ctx.body.get("scope_kind")
    if kind in SCOPE_KINDS:
        required = SCOPE_POINTERS.get(kind)
        for name in ALL_POINTERS:
            value = ctx.body.get(name)
            if name == required:
                if value is None:
                    raise ApiError("ERR_INVALID_REQUEST", "%s is required for this scope_kind." % name)
            elif value is not None:
                raise ApiError("ERR_INVALID_REQUEST", "%s must be null for this scope_kind." % name)
    starts = parse_instant(ctx.body.get("starts_at")) if isinstance(ctx.body.get("starts_at"), str) else None
    expires = parse_instant(ctx.body.get("expires_at")) if isinstance(ctx.body.get("expires_at"), str) else None
    if starts is not None and expires is not None and expires <= starts:
        raise ApiError("ERR_INVALID_REQUEST", "expires_at must be after starts_at.")
    cap = ctx.body.get("access_cap")
    if isinstance(cap, int) and not isinstance(cap, bool) and cap < 1:
        raise ApiError("ERR_INVALID_REQUEST", "access_cap must be at least 1.")


def _share_rung18(ctx):
    """Half-open windows, no buffer: exact adjacency is allowed."""
    starts = parse_instant(ctx.body["starts_at"])
    expires = parse_instant(ctx.body["expires_at"])
    for other in store.all_of(store.share_grants):
        if other["status"] != "ACTIVE":
            continue
        if other["household_id"] != ctx.body["household_id"]:
            continue
        if other["recipient_ref"] != ctx.body["recipient_ref"]:
            continue
        other_start = other.get("_starts_at_dt")
        other_end = other.get("_expires_at_dt")
        if other_start is None or other_end is None:
            continue
        if starts < other_end and other_start < expires:
            raise ApiError("ERR_SHARE_WINDOW_OVERLAP")


def _share_rung19(ctx):
    starts = parse_instant(ctx.body["starts_at"])
    expires = parse_instant(ctx.body["expires_at"])
    if expires > add_days(starts, SHARE_MAX_DURATION_DAYS):
        raise ApiError("ERR_SHARE_WINDOW_TOO_LONG")


@endpoint(
    "POST",
    "/vault/share-grants",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={
        "household_id": ("string", True),
        "scope_kind": ("string", True),
        "recipient_ref": ("string", True),
        "redaction_level": ("string", True),
        "starts_at": ("datetime", True),
        "expires_at": ("datetime", True),
        "scope_room_id": ("string", False),
        "scope_package_id": ("string", False),
        "scope_claim_id": ("string", False),
        "access_cap": ("integer", False),
    },
    enums={"scope_kind": SCOPE_KINDS, "redaction_level": REDACTION_LEVELS},
    fks=("household_id", "scope_room_id", "scope_package_id", "scope_claim_id"),
    household=lambda ctx: ctx.body.get("household_id"),
    rung3_extra=_share_shape,
    rungs={18: _share_rung18, 19: _share_rung19},
)
def create_share_grant(ctx):
    cap = ctx.body.get("access_cap")
    row = store.new_row(
        store.share_grants,
        household_id=ctx.body["household_id"],
        scope_kind=ctx.body["scope_kind"],
        scope_room_id=ctx.body.get("scope_room_id"),
        scope_package_id=ctx.body.get("scope_package_id"),
        scope_claim_id=ctx.body.get("scope_claim_id"),
        recipient_ref=ctx.body["recipient_ref"],
        redaction_level=ctx.body["redaction_level"],
        share_token=store.new_token(),
        access_cap=SHARE_DEFAULT_ACCESS_CAP if cap is None else cap,
        access_count=0,
        status="ACTIVE",
        voided_reason=None,
    )
    derive.keep_raw(row, "starts_at", ctx.body["starts_at"])
    derive.keep_raw(row, "expires_at", ctx.body["expires_at"])
    household = store.households.get(row["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)
    return one(serializers.share_grant(row), 201)


@endpoint(
    "GET",
    "/vault/share-grants/{share_grant_id}",
    roles=["Homeowner", "PlatformAdmin"],
    scope_household=_grant_household,
)
def read_share_grant(ctx):
    return one(serializers.share_grant(_grant(ctx)))


@endpoint("GET", "/vault/share-grants", roles=["Homeowner", "PlatformAdmin"])
def list_share_grants(ctx):
    return list_response(
        store.all_of(store.share_grants),
        ctx.args,
        serializers.share_grant,
        {
            "household_id": field("household_id"),
            "scope_room_id": field("scope_room_id"),
            "scope_package_id": field("scope_package_id"),
            "scope_claim_id": field("scope_claim_id"),
            "status": field("status"),
        },
    )


def _revoke_rung13(ctx):
    if _grant(ctx)["status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL")


@endpoint(
    "POST",
    "/vault/share-grants/{share_grant_id}/revoke",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    household=_grant_household,
    scope_household=_grant_household,
    rungs={13: _revoke_rung13},
)
def revoke_share_grant(ctx):
    grant = _grant(ctx)
    grant["status"] = "REVOKED"
    store.touch(grant)
    household = store.households.get(grant["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)
    return one(serializers.share_grant(grant))


# ------------------------------------------------------------- redemption
def _redact(row, level):
    if level == "VALUES_HIDDEN":
        return {k: v for k, v in row.items() if not k.endswith("_cents")}
    if level == "SERIALS_HIDDEN":
        return {k: v for k, v in row.items() if k != "serial_number"}
    return row


def _scoped_rows(grant):
    kind = grant["scope_kind"]
    if kind in ("HOUSEHOLD", "ROOM"):
        rows = [
            i
            for i in store.all_of(store.items)
            if i["household_id"] == grant["household_id"]
            and i["lifecycle_state"] in ("CATALOGED", "FROZEN")
        ]
        if kind == "ROOM":
            rows = [i for i in rows if i["room_id"] == grant.get("scope_room_id")]
        return [serializers.item(i) for i in rows], sum(i["effective_value_cents"] for i in rows)
    if kind == "PACKAGE":
        rows = [
            l for l in store.all_of(store.package_lines) if l["package_id"] == grant.get("scope_package_id")
        ]
        return (
            [serializers.package_line(l) for l in rows],
            sum(l["snapshot_effective_value_cents"] for l in rows),
        )
    rows = [l for l in store.all_of(store.claim_lines) if l["claim_id"] == grant.get("scope_claim_id")]
    return [serializers.claim_line(l) for l in rows], sum(l["net_settlement_cents"] for l in rows)


@endpoint(
    "GET",
    "/vault/shared/{share_token}",
    roles=["Anonymous", "InsuranceAgent", "ClaimsAdjuster"],
    share_token=True,
)
def redeem_share(ctx):
    grant = ctx.scratch["grant"]
    rows, total = _scoped_rows(grant)
    level = grant["redaction_level"]

    # Metering is applied BEFORE the response is rendered.
    grant["access_count"] += 1
    store.touch(grant)
    exhausted = grant["access_count"] >= grant["access_cap"]
    if exhausted:
        grant["status"] = "EXHAUSTED"
        household = store.households.get(grant["household_id"])
        if household is not None:
            derive.recompute_household(household, bump=True)

    household = store.households.get(grant["household_id"])
    payload = {
        "share_grant_id": grant["id"],
        "scope_kind": grant["scope_kind"],
        "redaction_level": level,
        "access_count": grant["access_count"],
        "access_cap": grant["access_cap"],
        "household_name": household["name"] if household else None,
        "rows": [_redact(r, level) for r in rows],
    }
    if level != "VALUES_HIDDEN":
        payload["total_effective_value_cents"] = total
    return one(payload)
