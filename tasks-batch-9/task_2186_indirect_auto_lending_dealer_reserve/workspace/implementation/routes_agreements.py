"""Routes: dealer agreements and rate sheets/tiers."""
from datetime import timedelta

from flask import Blueprint, g

from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, ok, list_response,
    require_roles, scope_dealer_id, scope_body_dealer_id, get_body,
    v_str, v_int, v_enum, v_dt, v_id, get_dealer, get_agreement, get_sheet,
    qfilter, is_dealer_principal, serialize, ALL_ROLES,
    AGREEMENT_NOTICE_BUFFER_DAYS,
)
import services as S

bp = Blueprint("agreements", __name__)

AGREEMENT_STATUSES = ("PENDING_COUNTERSIGN", "ACTIVE", "SUPERSEDED", "TERMINATED")


# ---------------------------------------------------------------------------
# Dealer agreements
# ---------------------------------------------------------------------------
@bp.route("/lending/dealer-agreements", methods=["POST"])
def create_agreement():
    require_roles("PortfolioAdmin")
    body = get_body()
    scope_body_dealer_id(body)

    dealer_id = v_id(body, "dealer_id", required=True)
    method = v_enum(body, "participation_method", ("RATE_PARTICIPATION", "FLAT_FEE"), required=True)
    max_participation = v_int(body, "max_participation_bps", required=True, minimum=0, maximum=250)
    from_raw, eff_from = v_dt(body, "effective_from", required=True)
    to_raw, eff_to = v_dt(body, "effective_to", required=True)
    expected = v_int(body, "expected_dealer_version", required=True)
    flat_fee_cap = v_int(body, "flat_fee_cap_cents", required=False, minimum=0, default=0)
    window_days = v_int(body, "chargeback_window_days", required=False, minimum=60, maximum=720, default=360)
    supersedes = v_id(body, "supersedes_agreement_id", required=False, default=None)
    if window_days % 30 != 0:
        fail("ERR_INVALID_REQUEST", "chargeback_window_days must be an exact multiple of 30.")
    if eff_to <= eff_from:
        fail("ERR_INVALID_REQUEST", "effective_to must be strictly after effective_from.")

    dealer = get_dealer(dealer_id)
    predecessor = None
    if supersedes is not None:
        predecessor = get_agreement(supersedes)

    if expected != dealer["version"]:
        fail("ERR_STALE_DEALER_VERSION", "Dealer version has advanced.")

    if predecessor is None:
        for existing in S.dealer_agreements(dealer_id):
            if existing["status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
                continue
            earliest = dtv(existing, "effective_to") + timedelta(days=AGREEMENT_NOTICE_BUFFER_DAYS)
            if eff_from < earliest:
                fail("ERR_AGREEMENT_WINDOW_CONFLICT",
                     "A mandatory 30-day notice buffer separates successive agreements.")
    else:
        if predecessor["dealer_id"] != dealer_id:
            fail("ERR_AGREEMENT_WINDOW_CONFLICT",
                 "A successor may only supersede an agreement of the same dealership.")
        if not (eff_from > dtv(predecessor, "effective_from") and eff_from <= dtv(predecessor, "effective_to")):
            fail("ERR_AGREEMENT_WINDOW_CONFLICT",
                 "A successor must start inside the term it replaces.")

    agreement = new_rec()
    agreement["dealer_id"] = dealer_id
    agreement["supersedes_agreement_id"] = supersedes
    agreement["participation_method"] = method
    agreement["max_participation_bps"] = max_participation
    agreement["flat_fee_cap_cents"] = flat_fee_cap
    agreement["chargeback_window_days"] = window_days
    putdt(agreement, "effective_from", from_raw, eff_from)
    putdt(agreement, "effective_to", to_raw, eff_to)
    agreement["status"] = "PENDING_COUNTERSIGN"
    stamp(agreement, "countersigned_at", None)
    agreement["signer_name"] = None
    store.agreements[agreement["id"]] = agreement
    bump(dealer)
    return ok(serialize(agreement), 201)


@bp.route("/lending/dealer-agreements/<agreement_id>", methods=["GET"])
def read_agreement(agreement_id):
    require_roles(*ALL_ROLES)
    agreement = get_agreement(agreement_id)
    scope_dealer_id(agreement["dealer_id"])
    return ok(serialize(agreement))


@bp.route("/lending/dealer-agreements", methods=["GET"])
def list_agreements():
    require_roles(*ALL_ROLES)
    records = list(store.agreements.values())
    if is_dealer_principal():
        records = [a for a in records if a["dealer_id"] == g.user_id]
    dealer_id = qfilter("dealer_id")
    if dealer_id is not None:
        records = [a for a in records if a["dealer_id"] == dealer_id]
    supersedes = qfilter("supersedes_agreement_id")
    if supersedes is not None:
        records = [a for a in records if a.get("supersedes_agreement_id") == supersedes]
    status = qfilter("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    records.sort(key=lambda a: (a.get("created_at") or "", a.get("_seq") or 0))
    return list_response(records)


@bp.route("/lending/dealer-agreements/<agreement_id>/countersign", methods=["POST"])
def countersign(agreement_id):
    require_roles("DealerPrincipal")
    agreement = get_agreement(agreement_id)
    scope_dealer_id(agreement["dealer_id"])
    body = get_body()
    signer_name = v_str(body, "signer_name", required=True, min_len=1, max_len=None)

    if agreement["status"] != "PENDING_COUNTERSIGN":
        fail("ERR_INVALID_STATE", "Only a PENDING_COUNTERSIGN agreement may be countersigned.")
    dealer = get_dealer(agreement["dealer_id"])
    if dealer["status"] not in ("PROSPECT", "ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "The dealership may not countersign in its current status.")

    agreement["status"] = "ACTIVE"
    stamp(agreement, "countersigned_at", clock.now())
    agreement["signer_name"] = signer_name
    bump(agreement)

    predecessor_id = agreement.get("supersedes_agreement_id")
    if predecessor_id:
        predecessor = store.agreements.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "ACTIVE":
            predecessor["status"] = "SUPERSEDED"
            stamp(predecessor, "effective_to", dtv(agreement, "effective_from") - timedelta(days=1))
            bump(predecessor)

    if dealer["status"] == "PROSPECT":
        dealer["status"] = "ACTIVE"
    bump(dealer)
    return ok(serialize(agreement))


# ---------------------------------------------------------------------------
# Rate sheets
# ---------------------------------------------------------------------------
@bp.route("/lending/rate-sheets", methods=["POST"])
def create_rate_sheet():
    require_roles("PortfolioAdmin")
    body = get_body()
    program_code = v_str(body, "program_code", required=True, min_len=1, max_len=None)
    from_raw, eff_from = v_dt(body, "effective_from", required=True)
    to_raw, eff_to = v_dt(body, "effective_to", required=True)
    if eff_to <= eff_from:
        fail("ERR_INVALID_REQUEST", "effective_to must be strictly after effective_from.")
    sheet = new_rec()
    sheet["program_code"] = program_code
    putdt(sheet, "effective_from", from_raw, eff_from)
    putdt(sheet, "effective_to", to_raw, eff_to)
    sheet["status"] = "DRAFT"
    sheet["tier_count"] = 0
    stamp(sheet, "published_at", None)
    store.sheets[sheet["id"]] = sheet
    return ok(serialize(sheet), 201)


@bp.route("/lending/rate-sheets/<sheet_id>", methods=["GET"])
def read_rate_sheet(sheet_id):
    require_roles(*ALL_ROLES)
    sheet = get_sheet(sheet_id)
    return ok(serialize(sheet))


@bp.route("/lending/rate-sheets/<sheet_id>/tiers", methods=["POST"])
def create_tier(sheet_id):
    require_roles("PortfolioAdmin")
    sheet = get_sheet(sheet_id)
    body = get_body()
    tier_code = v_enum(body, "tier_code", ("T1", "T2", "T3"), required=True)
    min_score = v_int(body, "min_credit_score", required=True, minimum=300, maximum=900)
    max_score = v_int(body, "max_credit_score", required=True, minimum=300, maximum=900)
    max_ltv = v_int(body, "max_ltv_pct", required=True, minimum=50, maximum=150)
    max_term = v_int(body, "max_term_months", required=True, minimum=12, maximum=96)
    buy_rate = v_int(body, "buy_rate_apr_bps", required=True, minimum=0, maximum=3000)
    advance_rate = v_int(body, "advance_rate_pct", required=True, minimum=50, maximum=150)
    acquisition_fee = v_int(body, "acquisition_fee_cents", required=True, minimum=0)
    if max_score < min_score:
        fail("ERR_INVALID_REQUEST", "max_credit_score must be at or above min_credit_score.")
    for existing in S.sheet_tiers(sheet_id):
        if existing["tier_code"] == tier_code:
            fail("ERR_INVALID_REQUEST", "tier_code must be unique within its rate sheet.")

    if sheet["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Tier rows may only be appended to a DRAFT rate sheet.")

    tier = new_rec(versioned=False)
    tier["rate_sheet_id"] = sheet_id
    tier["tier_code"] = tier_code
    tier["min_credit_score"] = min_score
    tier["max_credit_score"] = max_score
    tier["max_ltv_pct"] = max_ltv
    tier["max_term_months"] = max_term
    tier["buy_rate_apr_bps"] = buy_rate
    tier["advance_rate_pct"] = advance_rate
    tier["acquisition_fee_cents"] = acquisition_fee
    store.tiers[tier["id"]] = tier
    sheet["tier_count"] += 1
    bump(sheet)
    return ok(serialize(tier), 201)


@bp.route("/lending/rate-sheets/<sheet_id>/tiers", methods=["GET"])
def list_tiers(sheet_id):
    require_roles(*ALL_ROLES)
    get_sheet(sheet_id)
    return list_response(S.sheet_tiers(sheet_id))


@bp.route("/lending/rate-sheets/<sheet_id>/publish", methods=["POST"])
def publish_rate_sheet(sheet_id):
    require_roles("PortfolioAdmin")
    sheet = get_sheet(sheet_id)
    if sheet["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT rate sheet may be published.")
    if sheet["tier_count"] < 1:
        fail("ERR_RATE_SHEET_NO_TIERS", "A rate sheet must carry at least one tier row.")

    new_from = dtv(sheet, "effective_from")
    new_to = dtv(sheet, "effective_to")
    for other in store.sheets.values():
        if other["id"] == sheet["id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if other["program_code"] != sheet["program_code"]:
            continue
        if dtv(other, "effective_from") < new_to and new_from < dtv(other, "effective_to"):
            fail("ERR_RATE_SHEET_WINDOW_OVERLAP",
                 "The window intersects an existing PUBLISHED sheet for this program.")

    now = clock.now()
    sheet["status"] = "PUBLISHED"
    stamp(sheet, "published_at", now)
    bump(sheet)

    retirable = []
    for other in store.sheets.values():
        if other["id"] == sheet["id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if other["program_code"] != sheet["program_code"]:
            continue
        if dtv(other, "effective_to") <= now:
            retirable.append(other)
    retirable.sort(key=lambda s: (dtv(s, "effective_from"), s.get("created_at") or "", s.get("_seq") or 0))
    for other in retirable:
        other["status"] = "RETIRED"
        bump(other)

    return ok(serialize(sheet))
