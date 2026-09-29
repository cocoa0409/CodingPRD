"""Authority precedence, per-asset disclosure, transferability classification
and the grant cascades (PRD sections 3.3, 3.4, 3.6 / calculations 1-3).
"""
from clock import CLOCK, add_days_dt, format_dt
from db import DB, bump, sorted_records, stamp_new
from services import estate as estate_svc
from services import lookup

GRANT_TERM_DAYS = 90

BASIS_BY_DIRECTIVE = {
    "ONLINE_TOOL": "ONLINE_TOOL",
    "WILL_PROVISION": "WILL_PROVISION",
    "TRUST_PROVISION": "TRUST_PROVISION",
}

PRECEDENCE_RANK = {
    "ONLINE_TOOL": 1,
    "WILL_PROVISION": 2,
    "TRUST_PROVISION": 2,
}


def precedence_rank(directive_type):
    return PRECEDENCE_RANK.get(directive_type, 2)


def has_verified_court_order(estate_id):
    return any(
        d["doc_type"] == "COURT_ORDER" and d["verification_status"] == "VERIFIED"
        for d in lookup.estate_documents(estate_id)
    )


def _specificity(directive):
    if directive.get("platform_id") is not None:
        return 2
    if directive.get("asset_category") is not None:
        return 1
    return 0


def resolve_authority(estate, platform, asset_category=None):
    """Calculation 1 -- platform_authority_precedence.

    Returns resolved_scope / resolved_basis / clamp_reason /
    controlling_directive_id plus the pre-clamp scope, which the CONTENT_ACCESS
    submission gate needs to tell ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED from
    ERR_COURT_ORDER_REQUIRED.
    """
    if platform["status"] == "SUSPENDED":
        return {
            "resolved_scope": "NONE",
            "resolved_basis": "STATUTORY_DEFAULT",
            "clamp_reason": "NONE",
            "controlling_directive_id": None,
            "pre_clamp_scope": "NONE",
        }

    candidates = [
        d for d in lookup.estate_directives(estate["id"])
        if d["status"] == "RECORDED"
        and (d.get("platform_id") is None or d["platform_id"] == platform["id"])
        and (d.get("asset_category") is None or d["asset_category"] == asset_category)
    ]
    # An ONLINE_TOOL directive is only honoured when the platform offers a tool.
    if not platform["supports_online_tool"]:
        candidates = [d for d in candidates if d["directive_type"] != "ONLINE_TOOL"]

    if not candidates:
        winner = None
    else:
        candidates = sorted(
            candidates,
            key=lambda d: (d["precedence_rank"], -_specificity(d),
                           d["created_at"], d["_seq"]),
        )
        winner = candidates[0]

    if winner is None:
        base_scope = "CATALOG_ONLY"
        basis = "STATUTORY_DEFAULT"
    else:
        base_scope = winner["scope"]
        basis = BASIS_BY_DIRECTIVE.get(winner["directive_type"], "STATUTORY_DEFAULT")

    pre_clamp_scope = base_scope
    clamp_reason = "NONE"
    if base_scope == "CATALOG_AND_CONTENT" and platform["requires_court_order_for_content"]:
        if not has_verified_court_order(estate["id"]):
            base_scope = "CATALOG_ONLY"
            clamp_reason = "COURT_ORDER_REQUIRED"

    return {
        "resolved_scope": base_scope,
        "resolved_basis": basis,
        "clamp_reason": clamp_reason,
        "controlling_directive_id": winner["id"] if winner else None,
        "pre_clamp_scope": pre_clamp_scope,
    }


def disclosure_level(grant, asset):
    """Calculation 2 -- asset_disclosure_level."""
    scope = grant["granted_scope"]
    if scope == "NONE":
        return ("UNVERIFIED", "NONE")
    if scope == "CATALOG_ONLY":
        clamp = ("COURT_ORDER_REQUIRED"
                 if grant.get("clamp_reason") == "COURT_ORDER_REQUIRED" else "NONE")
        return ("CATALOG_DISCLOSED", clamp)
    if asset["category"] == "FINANCIAL_ACCOUNT" and grant.get("basis") != "ONLINE_TOOL":
        return ("CATALOG_DISCLOSED", "FINANCIAL_REQUIRES_ONLINE_TOOL")
    return ("CONTENT_DISCLOSED", "NONE")


def classify_transferability(asset, platform):
    """Calculation 3 -- asset_transferability_class, first match wins."""
    category = asset["category"]
    if category in ("EMAIL", "SOCIAL_PROFILE"):
        return ("NON_TRANSFERABLE", "CATEGORY_PERSONAL")
    if category == "SUBSCRIPTION":
        return ("LICENSE_TERMINATES_AT_DEATH", "CATEGORY_SUBSCRIPTION_LICENCE")
    if category == "CLOUD_STORAGE" and platform["license_terminates_at_death"]:
        return ("LICENSE_TERMINATES_AT_DEATH", "PROVIDER_LICENCE_TERMINATES")
    if category == "LOYALTY_PROGRAM" and not platform["supports_transfer"]:
        return ("LICENSE_TERMINATES_AT_DEATH", "PROVIDER_LICENCE_TERMINATES")
    if not platform["supports_transfer"]:
        return ("NON_TRANSFERABLE", "PROVIDER_NO_TRANSFER")
    return ("TRANSFERABLE", "TRANSFERABLE_PROPERTY")


def has_active_authority(asset):
    """An ACTIVE grant covering the account's estate and platform, and the
    account itself disclosed."""
    if asset["access_status"] not in estate_svc.DISCLOSED_STATUSES:
        return False
    return any(
        g["status"] == "ACTIVE"
        and g["estate_id"] == asset["estate_id"]
        and g["platform_id"] == asset["platform_id"]
        for g in DB.grants.values()
    )


# ------------------------------------------------------------------ cascades

def create_grant(request):
    effective_from = CLOCK.instant()
    grant = {
        "estate_id": request["estate_id"],
        "platform_id": request["platform_id"],
        "platform_request_id": request["id"],
        "granted_scope": request["resolved_scope"],
        "basis": request["resolved_basis"],
        "clamp_reason": request["clamp_reason"],
        "status": "ACTIVE",
        "effective_from": format_dt(effective_from),
        "expires_at": format_dt(add_days_dt(effective_from, GRANT_TERM_DAYS)),
        "revocation_reason": None,
    }
    stamp_new(grant)
    DB.grants[grant["id"]] = grant
    return grant


def disclose_assets(grant):
    """Hop 2 of an approval: walk the platform's accounts in created_at ASC
    order and raise each one's access_status. Never narrows an account."""
    touched = []
    if grant["granted_scope"] == "NONE":
        return touched
    candidates = sorted_records([
        a for a in lookup.estate_assets(grant["estate_id"])
        if a["platform_id"] == grant["platform_id"]
        and a["access_status"] in ("UNVERIFIED", "ACCESS_REVOKED", "CATALOG_DISCLOSED")
    ])
    for asset in candidates:
        level, clamp = disclosure_level(grant, asset)
        if level == "UNVERIFIED":
            continue
        if asset["access_status"] == "CATALOG_DISCLOSED" and level != "CONTENT_DISCLOSED":
            continue
        asset["access_status"] = level
        asset["content_clamp_reason"] = clamp
        if asset.get("disclosed_at") is None:
            asset["disclosed_at"] = CLOCK.iso()
        bump(asset)
        touched.append(asset)
    return touched


def open_cancellation_orders(assets):
    """Hop 3 of an approval: a PENDING CancellationOrder for every newly
    disclosed SUBSCRIPTION account that does not already have one."""
    created = []
    for asset in sorted_records(assets):
        if asset["category"] != "SUBSCRIPTION":
            continue
        if lookup.asset_orders(asset["id"]):
            continue
        platform = DB.platforms.get(asset["platform_id"])
        order = {
            "asset_id": asset["id"],
            "status": "PENDING",
            "effective_date": None,
            "platform_reference": None,
            "auto_renew_stopped": False,
            "failure_reason": None,
            "refund_policy_snapshot": platform["refund_policy"] if platform else None,
            "requested_at": None,
            "confirmed_at": None,
        }
        stamp_new(order)
        DB.orders[order["id"]] = order
        created.append(order)
    return created


def revoke_asset_access(assets, reset_clamp):
    revoked = []
    for asset in sorted_records(assets):
        if asset["access_status"] not in estate_svc.DISCLOSED_STATUSES:
            continue
        asset["access_status"] = "ACCESS_REVOKED"
        if reset_clamp:
            asset["content_clamp_reason"] = "NONE"
        bump(asset)
        revoked.append(asset)
    return revoked


def revoke_grant(grant, revocation_reason, reset_clamp=False):
    """Drop a grant and cascade every account it had disclosed."""
    grant["status"] = "REVOKED"
    grant["revocation_reason"] = revocation_reason
    bump(grant)
    assets = [a for a in lookup.estate_assets(grant["estate_id"])
              if a["platform_id"] == grant["platform_id"]]
    return revoke_asset_access(assets, reset_clamp)
