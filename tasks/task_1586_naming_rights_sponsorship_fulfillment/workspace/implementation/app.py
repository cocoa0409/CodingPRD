"""Naming Rights & Sponsorship Fulfillment API — Flask entry point and routes."""
import datetime
import os
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask

from core import (
    ROLES, CATEGORIES, ASSET_CLASSES, HOLDERS, UNIT_KINDS, ESCALATOR_MODES,
    ApiError, authn, require_role, body_json, check_shape, pagination_params,
    do_list, qfilter, ok, err_resp, db, create_record, touch, pub, new_uuid, now_iso,
    e_forbidden, e_not_found, e_invalid_request, e_invalid_state, e_rights_conflict,
    e_contested, e_season_window, e_season_out_of_term, e_season_closed,
    e_season_not_closed, e_grant_outside_term, e_category_conflict, e_duplicate_grant,
    e_suite_conflict, e_over_delivery, e_dup_opportunity, e_sponsor_not_active,
    e_asset_not_available, e_contract_not_active, e_deliverable_not_open,
    e_renewal_state, e_invalid_amount, e_credit_cap, e_credit_balance,
    e_payment_balance, e_invoice_not_payable, e_no_payable, e_stale_contract,
    e_stale_opportunity, e_sod,
)
from domain import (
    season_fee_cents, make_good_amount, seasons_overlap, recompute_receivable,
    recompute_outstanding, recompute_rights, rederive_invoice_status,
    cancel_deliverable, release_grant, terminate_contract, league_contest_sweep,
    league_release_sweep, run_countersign, advance_season,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _api_error(e):
    return err_resp(e)


@app.errorhandler(404)
def _404(e):
    return err_resp(e_not_found())


@app.errorhandler(405)
def _405(e):
    return err_resp(e_not_found("Resource not found"))


@app.errorhandler(Exception)
def _500(e):
    return err_resp(ApiError("ERR_INTERNAL", 500, str(e)))


# --- Scope helpers (SponsorContact reads are scoped to their own sponsor_id) ---
def check_scope(role, uid, sponsor_id):
    if role == "SponsorContact" and sponsor_id != uid:
        raise e_forbidden("Resource is outside the sponsor contact's scope")


def contract_of_grant(g):
    return db.contracts[g["contract_id"]]


def contract_of_deliverable(d):
    return db.contracts[d["contract_id"]]


def contract_of_evidence(e):
    return db.contracts[db.deliverables[e["deliverable_id"]]["contract_id"]]


# =============================================================================
# Venues
# =============================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"display_name": ("str", True), "city": ("str", True)})
    require_role(role, {"VenueAdmin"})
    v = create_record(db.venues, {"display_name": body["display_name"],
                                  "city": body["city"], "current_season": 2026})
    return ok(pub(v), 201)


@app.route("/venues/<vid>", methods=["GET"])
def get_venue(vid):
    uid, role = authn()
    v = db.venues.get(vid)
    if not v:
        raise e_not_found("Venue not found")
    return ok(pub(v))


@app.route("/venues/<vid>/advance-season", methods=["POST"])
def advance_season_ep(vid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {})
    require_role(role, {"VenueAdmin"})
    v = db.venues.get(vid)
    if not v:
        raise e_not_found("Venue not found")
    advance_season(v)
    return ok(pub(v))


# =============================================================================
# Sponsors
# =============================================================================
@app.route("/sponsors", methods=["POST"])
def create_sponsor():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"legal_name": ("str", True), "display_name": ("str", True),
                       "industry_category": ("enum:" + "|".join(CATEGORIES), True)})
    require_role(role, {"SponsorshipSales"})
    s = create_record(db.sponsors, {"legal_name": body["legal_name"],
                                    "display_name": body["display_name"],
                                    "industry_category": body["industry_category"],
                                    "sponsor_status": "PROSPECT"})
    return ok(pub(s), 201)


@app.route("/sponsors/<sid>", methods=["GET"])
def get_sponsor(sid):
    uid, role = authn()
    s = db.sponsors.get(sid)
    if not s:
        raise e_not_found("Sponsor not found")
    check_scope(role, uid, s["id"])
    return ok(pub(s))


@app.route("/sponsors/<sid>/transition", methods=["POST"])
def sponsor_transition(sid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:QUALIFY|SUSPEND|REINSTATE|BLOCK", True)})
    require_role(role, {"SponsorshipSales"})
    s = db.sponsors.get(sid)
    if not s:
        raise e_not_found("Sponsor not found")
    action = body["action"]
    if action == "QUALIFY":
        if s["sponsor_status"] != "PROSPECT":
            raise e_invalid_state("QUALIFY requires PROSPECT")
        s["sponsor_status"] = "ACTIVE"
        touch(s)
    elif action == "SUSPEND":
        if s["sponsor_status"] != "ACTIVE":
            raise e_invalid_state("SUSPEND requires ACTIVE")
        s["sponsor_status"] = "SUSPENDED"
        touch(s)
        for c in sorted((c for c in db.contracts.values() if c["sponsor_id"] == sid),
                        key=lambda r: r["_seq"]):
            if c["contract_status"] == "ACTIVE":
                c["contract_status"] = "SUSPENDED"
                touch(c)
    elif action == "REINSTATE":
        if s["sponsor_status"] != "SUSPENDED":
            raise e_invalid_state("REINSTATE requires SUSPENDED")
        s["sponsor_status"] = "ACTIVE"
        touch(s)
    elif action == "BLOCK":
        if s["sponsor_status"] not in ("ACTIVE", "SUSPENDED"):
            raise e_invalid_state("BLOCK requires ACTIVE or SUSPENDED")
        s["sponsor_status"] = "BLOCKED"
        touch(s)
        for c in sorted((c for c in db.contracts.values() if c["sponsor_id"] == sid),
                        key=lambda r: r["_seq"]):
            if c["contract_status"] in ("COUNTERSIGNED", "ACTIVE", "SUSPENDED"):
                terminate_contract(c)
    return ok(pub(s))


# =============================================================================
# Assets
# =============================================================================
@app.route("/assets", methods=["POST"])
def create_asset():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"venue_id": ("str", True), "name": ("str", True),
                       "asset_class": ("enum:" + "|".join(ASSET_CLASSES), True),
                       "rate_card_unit_cents": ("int", True),
                       "avg_impressions_per_unit": ("int", True),
                       "cpm_cents": ("int", True)})
    require_role(role, {"VenueAdmin"})
    if body["venue_id"] not in db.venues:
        raise e_not_found("Venue not found")
    for f in ("rate_card_unit_cents", "avg_impressions_per_unit", "cpm_cents"):
        if body[f] <= 0:
            raise e_invalid_amount(f"{f} must be a positive integer")
    a = create_record(db.assets, {"venue_id": body["venue_id"], "name": body["name"],
                                  "asset_class": body["asset_class"],
                                  "rate_card_unit_cents": body["rate_card_unit_cents"],
                                  "avg_impressions_per_unit": body["avg_impressions_per_unit"],
                                  "cpm_cents": body["cpm_cents"],
                                  "asset_status": "AVAILABLE"})
    return ok(pub(a), 201)


@app.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    uid, role = authn()
    a = db.assets.get(aid)
    if not a:
        raise e_not_found("Asset not found")
    return ok(pub(a))


@app.route("/assets", methods=["GET"])
def list_assets():
    uid, role = authn()
    limit, offset = pagination_params()
    return do_list(list(db.assets.values()),
                   [qfilter("venue_id"), qfilter("asset_class"), qfilter("asset_status")],
                   limit, offset)


@app.route("/assets/<aid>/transition", methods=["POST"])
def asset_transition(aid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:RETIRE|REINSTATE", True)})
    require_role(role, {"VenueAdmin"})
    a = db.assets.get(aid)
    if not a:
        raise e_not_found("Asset not found")
    if body["action"] == "RETIRE":
        if a["asset_status"] != "AVAILABLE":
            raise e_invalid_state("RETIRE requires AVAILABLE")
        a["asset_status"] = "RETIRED"
    else:
        if a["asset_status"] != "RETIRED":
            raise e_invalid_state("REINSTATE requires RETIRED")
        a["asset_status"] = "AVAILABLE"
    touch(a)
    return ok(pub(a))


# =============================================================================
# Rights windows
# =============================================================================
@app.route("/rights-windows", methods=["POST"])
def create_window():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"venue_id": ("str", True),
                       "holder": ("enum:" + "|".join(HOLDERS), True),
                       "category": ("enum:" + "|".join(CATEGORIES), True),
                       "first_season": ("int", True), "last_season": ("int", True)})
    require_role(role, {"VenueAdmin"})
    if body["venue_id"] not in db.venues:
        raise e_not_found("Venue not found")
    w = create_record(db.rights_windows, {
        "venue_id": body["venue_id"], "holder": body["holder"],
        "category": body["category"], "first_season": body["first_season"],
        "last_season": body["last_season"], "window_status": "RESERVED"})
    return ok(pub(w), 201)


@app.route("/rights-windows/<wid>", methods=["GET"])
def get_window(wid):
    uid, role = authn()
    w = db.rights_windows.get(wid)
    if not w:
        raise e_not_found("Rights window not found")
    return ok(pub(w))


@app.route("/rights-windows", methods=["GET"])
def list_windows():
    uid, role = authn()
    limit, offset = pagination_params()
    return do_list(list(db.rights_windows.values()),
                   [qfilter("venue_id"), qfilter("holder"), qfilter("category"),
                    qfilter("window_status")], limit, offset)


@app.route("/rights-windows/<wid>/transition", methods=["POST"])
def window_transition(wid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:ACTIVATE|RELEASE", True)})
    require_role(role, {"VenueAdmin"})
    w = db.rights_windows.get(wid)
    if not w:
        raise e_not_found("Rights window not found")
    if body["action"] == "ACTIVATE":
        if w["window_status"] != "RESERVED":
            raise e_invalid_state("ACTIVATE requires RESERVED")
        w["window_status"] = "ACTIVE"
        touch(w)
        league_contest_sweep(w)
    else:  # RELEASE
        if w["window_status"] not in ("RESERVED", "ACTIVE"):
            raise e_invalid_state("RELEASE requires RESERVED or ACTIVE")
        was_active = w["window_status"] == "ACTIVE"
        w["window_status"] = "RELEASED"
        touch(w)
        if was_active:
            league_release_sweep(w)
    return ok(pub(w))


# =============================================================================
# Contracts
# =============================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"venue_id": ("str", True), "sponsor_id": ("str", True),
                       "title": ("str", True), "term_first_season": ("int", True),
                       "term_last_season": ("int", True), "base_fee_cents": ("int", True),
                       "escalator_pct": ("num", True),
                       "escalator_mode": ("enum:" + "|".join(ESCALATOR_MODES), True),
                       "renewed_from_contract_id": ("str", False)})
    require_role(role, {"SponsorshipSales"})
    v = db.venues.get(body["venue_id"])
    if not v:
        raise e_not_found("Venue not found")
    sp = db.sponsors.get(body["sponsor_id"])
    if not sp:
        raise e_not_found("Sponsor not found")
    rcid = body.get("renewed_from_contract_id")
    if rcid is not None and rcid not in db.contracts:
        raise e_not_found("Renewed-from contract not found")
    # tier 7: temporal placement
    if (body["term_first_season"] < v["current_season"]
            or body["term_last_season"] < body["term_first_season"]):
        raise e_season_window("Term window malformed")
    # tier 9: referential
    if sp["sponsor_status"] != "ACTIVE":
        raise e_sponsor_not_active()
    # tier 10: fiscal
    if body["base_fee_cents"] <= 0:
        raise e_invalid_amount("base_fee_cents must be a positive integer")
    if body["escalator_pct"] < 0:
        raise e_invalid_amount("escalator_pct must be >= 0")
    c = create_record(db.contracts, {
        "venue_id": body["venue_id"], "sponsor_id": body["sponsor_id"],
        "title": body["title"], "term_first_season": body["term_first_season"],
        "term_last_season": body["term_last_season"],
        "base_fee_cents": body["base_fee_cents"],
        "escalator_pct": body["escalator_pct"],
        "escalator_mode": body["escalator_mode"],
        "renewed_from_contract_id": rcid,
        "contract_status": "DRAFT", "rights_status": "CLEAR",
        "scheduled_total_cents": 0, "receivable_cents": 0,
        "make_good_outstanding_cents": 0})
    return ok(pub(c), 201)


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    uid, role = authn()
    c = db.contracts.get(cid)
    if not c:
        raise e_not_found("Contract not found")
    check_scope(role, uid, c["sponsor_id"])
    return ok(pub(c))


@app.route("/contracts", methods=["GET"])
def list_contracts():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda c: c["sponsor_id"] == uid)
    preds += [qfilter("venue_id"), qfilter("sponsor_id"),
              qfilter("renewed_from_contract_id"), qfilter("contract_status")]
    return do_list(list(db.contracts.values()), preds, limit, offset)


@app.route("/contracts/<cid>", methods=["PATCH"])
def patch_contract(cid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"title": ("str", False), "term_first_season": ("int", False),
                       "term_last_season": ("int", False), "base_fee_cents": ("int", False),
                       "escalator_pct": ("num", False),
                       "escalator_mode": ("enum:" + "|".join(ESCALATOR_MODES), False)})
    require_role(role, {"SponsorshipSales"})
    c = db.contracts.get(cid)
    if not c:
        raise e_not_found("Contract not found")
    if c["contract_status"] != "DRAFT":
        raise e_invalid_state("Commercial terms are editable only while DRAFT")
    for f in ("title", "term_first_season", "term_last_season", "base_fee_cents",
              "escalator_pct", "escalator_mode"):
        if body.get(f) is not None:
            c[f] = body[f]
    touch(c)
    return ok(pub(c))


@app.route("/contracts/<cid>/transition", methods=["POST"])
def contract_transition(cid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:PROPOSE|REVISE|ACTIVATE|SUSPEND|REINSTATE|TERMINATE", True)})
    require_role(role, {"SponsorshipSales"})
    c = db.contracts.get(cid)
    if not c:
        raise e_not_found("Contract not found")
    action = body["action"]
    sp = db.sponsors[c["sponsor_id"]]
    if action == "PROPOSE":
        if c["contract_status"] != "DRAFT":
            raise e_invalid_state("PROPOSE requires DRAFT")
        if sp["sponsor_status"] != "ACTIVE":
            raise e_sponsor_not_active()
        c["contract_status"] = "PROPOSED"
        touch(c)
    elif action == "REVISE":
        if c["contract_status"] != "PROPOSED":
            raise e_invalid_state("REVISE requires PROPOSED")
        c["contract_status"] = "DRAFT"
        touch(c)
    elif action == "ACTIVATE":
        if c["contract_status"] != "COUNTERSIGNED":
            raise e_invalid_state("ACTIVATE requires COUNTERSIGNED")
        if any(g["contract_id"] == cid and g["grant_status"] in ("PENDING", "CONFLICTED")
               for g in db.grants.values()):
            raise e_invalid_state("Contract has PENDING or CONFLICTED grants")
        v = db.venues[c["venue_id"]]
        if v["current_season"] > c["term_last_season"]:
            raise e_season_closed("Contract term has already closed")
        if sp["sponsor_status"] != "ACTIVE":
            raise e_sponsor_not_active()
        c["contract_status"] = "ACTIVE"
        touch(c)
    elif action == "SUSPEND":
        if c["contract_status"] != "ACTIVE":
            raise e_invalid_state("SUSPEND requires ACTIVE")
        c["contract_status"] = "SUSPENDED"
        touch(c)
    elif action == "REINSTATE":
        if c["contract_status"] != "SUSPENDED":
            raise e_invalid_state("REINSTATE requires SUSPENDED")
        if sp["sponsor_status"] != "ACTIVE":
            raise e_sponsor_not_active()
        c["contract_status"] = "ACTIVE"
        touch(c)
    elif action == "TERMINATE":
        if c["contract_status"] not in ("ACTIVE", "SUSPENDED"):
            raise e_invalid_state("TERMINATE requires ACTIVE or SUSPENDED")
        terminate_contract(c)
    return ok(pub(c))


@app.route("/contracts/<cid>/countersign", methods=["POST"])
def countersign(cid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"expected_contract_version": ("int", True)})
    require_role(role, {"SponsorContact"})
    c = db.contracts.get(cid)
    if not c:
        raise e_not_found("Contract not found")
    if c["sponsor_id"] != uid:
        raise e_forbidden("SponsorContact may only countersign their own contracts")
    if c["contract_status"] != "PROPOSED":
        raise e_invalid_state("Countersign requires PROPOSED")
    if body["expected_contract_version"] != c["version"]:
        raise e_stale_contract()
    run_countersign(c)
    return ok(pub(c))


# =============================================================================
# Exclusivity grants
# =============================================================================
@app.route("/exclusivity-grants", methods=["POST"])
def create_grant():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"contract_id": ("str", True),
                       "category": ("enum:" + "|".join(CATEGORIES), True),
                       "first_season": ("int", True), "last_season": ("int", True)})
    require_role(role, {"SponsorshipSales"})
    c = db.contracts.get(body["contract_id"])
    if not c:
        raise e_not_found("Contract not found")
    if (body["first_season"] < c["term_first_season"]
            or body["last_season"] > c["term_last_season"]):
        raise e_grant_outside_term()
    if any(g["contract_id"] == c["id"] and g["category"] == body["category"]
           and g["grant_status"] in ("PENDING", "ACTIVE") for g in db.grants.values()):
        raise e_duplicate_grant()
    g = create_record(db.grants, {"contract_id": c["id"], "category": body["category"],
                                  "first_season": body["first_season"],
                                  "last_season": body["last_season"],
                                  "grant_status": "PENDING"})
    return ok(pub(g), 201)


@app.route("/exclusivity-grants/<gid>", methods=["GET"])
def get_grant(gid):
    uid, role = authn()
    g = db.grants.get(gid)
    if not g:
        raise e_not_found("Grant not found")
    check_scope(role, uid, contract_of_grant(g)["sponsor_id"])
    return ok(pub(g))


@app.route("/exclusivity-grants", methods=["GET"])
def list_grants():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda g: db.contracts[g["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("category"), qfilter("grant_status")]
    return do_list(list(db.grants.values()), preds, limit, offset)


@app.route("/exclusivity-grants/<gid>/transition", methods=["POST"])
def grant_transition(gid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:ACTIVATE|RELEASE", True)})
    require_role(role, {"VenueAdmin"})
    g = db.grants.get(gid)
    if not g:
        raise e_not_found("Grant not found")
    if body["action"] == "ACTIVATE":
        if g["grant_status"] not in ("PENDING", "CONFLICTED"):
            raise e_invalid_state("ACTIVATE requires PENDING or CONFLICTED")
        c = db.contracts[g["contract_id"]]
        if g["grant_status"] == "PENDING":
            if c["contract_status"] != "COUNTERSIGNED":
                raise e_invalid_state("Grant activation requires a COUNTERSIGNED contract")
        else:  # CONFLICTED manual path
            if c["contract_status"] not in ("COUNTERSIGNED", "ACTIVE"):
                raise e_invalid_state("Grant reactivation requires COUNTERSIGNED or ACTIVE contract")
        # tier 6: league preemption check
        for w in db.rights_windows.values():
            if (w["holder"] == "LEAGUE" and w["window_status"] == "ACTIVE"
                    and w["venue_id"] == c["venue_id"] and w["category"] == g["category"]
                    and seasons_overlap(w["first_season"], w["last_season"],
                                        g["first_season"], g["last_season"])):
                raise e_rights_conflict()
        # tier 8: category exclusivity sweep
        for o in db.grants.values():
            if o["id"] == g["id"] or o["grant_status"] != "ACTIVE":
                continue
            oc = db.contracts[o["contract_id"]]
            if (oc["venue_id"] == c["venue_id"] and o["category"] == g["category"]
                    and seasons_overlap(o["first_season"], o["last_season"],
                                        g["first_season"], g["last_season"])):
                raise e_category_conflict()
        g["grant_status"] = "ACTIVE"
        touch(g)
        recompute_rights(c)
    else:  # RELEASE
        if g["grant_status"] not in ("PENDING", "ACTIVE", "CONFLICTED"):
            raise e_invalid_state("RELEASE requires PENDING, ACTIVE, or CONFLICTED")
        release_grant(g)
    return ok(pub(g))


# =============================================================================
# Deliverables
# =============================================================================
@app.route("/deliverables", methods=["POST"])
def create_deliverable():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"contract_id": ("str", True), "asset_id": ("str", True),
                       "season": ("int", True),
                       "unit_kind": ("enum:" + "|".join(UNIT_KINDS), True),
                       "contracted_units": ("int", True),
                       "checkin_date": ("date", False), "checkout_date": ("date", False)})
    if body.get("unit_kind") == "SUITE_NIGHT" and (
            body.get("checkin_date") is None or body.get("checkout_date") is None):
        raise e_invalid_request("SUITE_NIGHT requires checkin_date and checkout_date")
    require_role(role, {"ActivationManager"})
    c = db.contracts.get(body["contract_id"])
    if not c:
        raise e_not_found("Contract not found")
    a = db.assets.get(body["asset_id"])
    if not a:
        raise e_not_found("Asset not found")
    # tier 6: contested-rights gate
    if c["rights_status"] != "CLEAR":
        raise e_contested()
    # tier 7: temporal placement (PRD §3.4 order)
    season = body["season"]
    if season < c["term_first_season"] or season > c["term_last_season"]:
        raise e_season_out_of_term()
    v = db.venues[c["venue_id"]]
    if season < v["current_season"]:
        raise e_season_closed()
    if body.get("unit_kind") == "SUITE_NIGHT":
        ci = datetime.date.fromisoformat(body["checkin_date"])
        co = datetime.date.fromisoformat(body["checkout_date"])
        if ci > co:
            raise e_season_window("checkin_date must be <= checkout_date")
    # tier 8: suite date conflict
    if body.get("unit_kind") == "SUITE_NIGHT":
        day = datetime.timedelta(days=1)
        ci2, co2 = ci, co
        for d1 in db.deliverables.values():
            if (d1["asset_id"] == a["id"] and d1["unit_kind"] == "SUITE_NIGHT"
                    and d1["deliverable_status"] != "CANCELLED"):
                ci1 = datetime.date.fromisoformat(d1["checkin_date"])
                co1 = datetime.date.fromisoformat(d1["checkout_date"])
                if ci2 <= co1 + day and ci1 <= co2 + day:
                    raise e_suite_conflict()
    # tier 9: referential gates
    if c["contract_status"] != "ACTIVE":
        raise e_contract_not_active()
    if a["asset_status"] != "AVAILABLE":
        raise e_asset_not_available()
    # tier 10: fiscal
    if body["contracted_units"] <= 0:
        raise e_invalid_amount("contracted_units must be a positive integer")
    status = "IN_PROGRESS" if season == v["current_season"] else "SCHEDULED"
    d = create_record(db.deliverables, {
        "contract_id": c["id"], "asset_id": a["id"], "season": season,
        "unit_kind": body["unit_kind"], "contracted_units": body["contracted_units"],
        "checkin_date": body.get("checkin_date"), "checkout_date": body.get("checkout_date"),
        "approved_units": 0, "deliverable_status": status})
    return ok(pub(d), 201)


@app.route("/deliverables/<did>", methods=["GET"])
def get_deliverable(did):
    uid, role = authn()
    d = db.deliverables.get(did)
    if not d:
        raise e_not_found("Deliverable not found")
    check_scope(role, uid, contract_of_deliverable(d)["sponsor_id"])
    return ok(pub(d))


@app.route("/deliverables", methods=["GET"])
def list_deliverables():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda d: db.contracts[d["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("asset_id"), qfilter("season"),
              qfilter("deliverable_status")]
    return do_list(list(db.deliverables.values()), preds, limit, offset)


@app.route("/deliverables/<did>/transition", methods=["POST"])
def deliverable_transition(did):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:CANCEL", True)})
    require_role(role, {"ActivationManager"})
    d = db.deliverables.get(did)
    if not d:
        raise e_not_found("Deliverable not found")
    if d["deliverable_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise e_invalid_state("CANCEL requires SCHEDULED or IN_PROGRESS")
    cancel_deliverable(d)
    return ok(pub(d))


# =============================================================================
# Evidence submissions
# =============================================================================
@app.route("/evidence-submissions", methods=["POST"])
def create_evidence():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"deliverable_id": ("str", True), "units_claimed": ("int", True),
                       "evidence_uri": ("str", True)})
    require_role(role, {"ActivationManager"})
    d = db.deliverables.get(body["deliverable_id"])
    if not d:
        raise e_not_found("Deliverable not found")
    if d["deliverable_status"] != "IN_PROGRESS":
        raise e_deliverable_not_open()
    if body["units_claimed"] <= 0:
        raise e_invalid_amount("units_claimed must be a positive integer")
    e = create_record(db.evidence, {"deliverable_id": d["id"],
                                    "units_claimed": body["units_claimed"],
                                    "evidence_uri": body["evidence_uri"],
                                    "submitted_by_user_id": uid,
                                    "submission_status": "SUBMITTED",
                                    "review_note": None})
    return ok(pub(e), 201)


@app.route("/evidence-submissions/<eid>", methods=["GET"])
def get_evidence(eid):
    uid, role = authn()
    e = db.evidence.get(eid)
    if not e:
        raise e_not_found("Evidence submission not found")
    check_scope(role, uid, contract_of_evidence(e)["sponsor_id"])
    return ok(pub(e))


@app.route("/evidence-submissions", methods=["GET"])
def list_evidence():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(
            lambda e: db.contracts[db.deliverables[e["deliverable_id"]]["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("deliverable_id"), qfilter("submission_status")]
    return do_list(list(db.evidence.values()), preds, limit, offset)


@app.route("/evidence-submissions/<eid>/transition", methods=["POST"])
def evidence_transition(eid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:APPROVE|REJECT|RESUBMIT", True),
                       "review_note": ("str", False), "evidence_uri": ("str", False)})
    require_role(role, {"ActivationManager"})
    e = db.evidence.get(eid)
    if not e:
        raise e_not_found("Evidence submission not found")
    action = body["action"]
    d = db.deliverables[e["deliverable_id"]]
    if action == "APPROVE":
        if e["submission_status"] != "SUBMITTED":
            raise e_invalid_state("APPROVE requires SUBMITTED")
        c = db.contracts[d["contract_id"]]
        if c["rights_status"] != "CLEAR":
            raise e_contested()
        if uid == e["submitted_by_user_id"]:
            raise e_sod()
        if d["approved_units"] + e["units_claimed"] > d["contracted_units"]:
            raise e_over_delivery()
        if d["deliverable_status"] != "IN_PROGRESS":
            raise e_deliverable_not_open()
        d["approved_units"] += e["units_claimed"]
        if d["approved_units"] == d["contracted_units"]:
            d["deliverable_status"] = "FULFILLED"
        touch(d)
        e["review_note"] = body.get("review_note")
        e["submission_status"] = "APPROVED"
        touch(e)
    elif action == "REJECT":
        if e["submission_status"] != "SUBMITTED":
            raise e_invalid_state("REJECT requires SUBMITTED")
        if uid == e["submitted_by_user_id"]:
            raise e_sod()
        e["review_note"] = body.get("review_note")
        e["submission_status"] = "REJECTED"
        touch(e)
    else:  # RESUBMIT
        if e["submission_status"] != "REJECTED":
            raise e_invalid_state("RESUBMIT requires REJECTED")
        if d["deliverable_status"] != "IN_PROGRESS":
            raise e_deliverable_not_open()
        if body.get("evidence_uri") is not None:
            e["evidence_uri"] = body["evidence_uri"]
        e["submitted_by_user_id"] = uid
        e["review_note"] = None
        e["submission_status"] = "SUBMITTED"
        touch(e)
    return ok(pub(e))


# =============================================================================
# Make-good credits
# =============================================================================
@app.route("/make-good-credits", methods=["POST"])
def create_credit():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"contract_id": ("str", True), "deliverable_id": ("str", True),
                       "requested_amount_cents": ("int", True)})
    require_role(role, {"ActivationManager"})
    if body["contract_id"] not in db.contracts:
        raise e_not_found("Contract not found")
    if body["deliverable_id"] not in db.deliverables:
        raise e_not_found("Deliverable not found")
    if body["requested_amount_cents"] <= 0:
        raise e_invalid_amount("requested_amount_cents must be a positive integer")
    cr = create_record(db.credits, {"contract_id": body["contract_id"],
                                    "deliverable_id": body["deliverable_id"],
                                    "requested_amount_cents": body["requested_amount_cents"],
                                    "approved_amount_cents": None,
                                    "redeemed_against_invoice_id": None,
                                    "credit_status": "REQUESTED"})
    return ok(pub(cr), 201)


@app.route("/make-good-credits/<cid>", methods=["GET"])
def get_credit(cid):
    uid, role = authn()
    cr = db.credits.get(cid)
    if not cr:
        raise e_not_found("Make-good credit not found")
    check_scope(role, uid, db.contracts[cr["contract_id"]]["sponsor_id"])
    return ok(pub(cr))


@app.route("/make-good-credits", methods=["GET"])
def list_credits():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda cr: db.contracts[cr["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("deliverable_id"),
              qfilter("redeemed_against_invoice_id"), qfilter("credit_status")]
    return do_list(list(db.credits.values()), preds, limit, offset)


@app.route("/make-good-credits/<cid>/transition", methods=["POST"])
def credit_transition(cid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:APPROVE|DECLINE|REDEEM|VOID", True),
                       "approved_amount_cents": ("int", False)})
    require_role(role, {"FinanceManager"})
    cr = db.credits.get(cid)
    if not cr:
        raise e_not_found("Make-good credit not found")
    action = body["action"]
    c = db.contracts[cr["contract_id"]]
    if action == "APPROVE":
        if cr["credit_status"] != "REQUESTED":
            raise e_invalid_state("APPROVE requires REQUESTED")
        amt = body.get("approved_amount_cents")
        if amt is None or amt <= 0:
            raise e_invalid_amount("approved_amount_cents must be present and positive")
        cap = make_good_amount(db.deliverables[cr["deliverable_id"]])
        if amt > cap:
            raise e_credit_cap()
        cr["approved_amount_cents"] = amt
        cr["credit_status"] = "APPROVED"
        touch(cr)
        recompute_outstanding(c)
    elif action == "DECLINE":
        if cr["credit_status"] != "REQUESTED":
            raise e_invalid_state("DECLINE requires REQUESTED")
        cr["credit_status"] = "DECLINED"
        touch(cr)
    elif action == "REDEEM":
        if cr["credit_status"] != "APPROVED":
            raise e_invalid_state("REDEEM requires APPROVED")
        pool = sorted((inv for inv in db.invoices.values()
                       if inv["contract_id"] == c["id"]
                       and inv["invoice_status"] in ("ISSUED", "PARTIALLY_PAID")),
                      key=lambda i: (i["installment_seq"], i["_seq"]))
        if not pool:
            raise e_no_payable()
        target = pool[0]
        remaining = target["amount_cents"] - target["paid_cents"] - target["credits_applied_cents"]
        if cr["approved_amount_cents"] > remaining:
            raise e_credit_balance()
        cr["redeemed_against_invoice_id"] = target["id"]
        cr["credit_status"] = "REDEEMED"
        touch(cr)
        target["credits_applied_cents"] += cr["approved_amount_cents"]
        rederive_invoice_status(target)
        touch(target)
        recompute_outstanding(c)
        recompute_receivable(c)
        d = db.deliverables[cr["deliverable_id"]]
        if d["deliverable_status"] == "MISSED":
            d["deliverable_status"] = "COMPED"
            touch(d)
    else:  # VOID
        if cr["credit_status"] not in ("REQUESTED", "APPROVED"):
            raise e_invalid_state("VOID requires REQUESTED or APPROVED")
        cr["credit_status"] = "VOIDED"
        touch(cr)
        recompute_outstanding(c)
    return ok(pub(cr))


# =============================================================================
# Invoices
# =============================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = authn()
    inv = db.invoices.get(iid)
    if not inv:
        raise e_not_found("Invoice not found")
    check_scope(role, uid, db.contracts[inv["contract_id"]]["sponsor_id"])
    return ok(pub(inv))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda i: db.contracts[i["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("invoice_status"), qfilter("installment_label")]
    return do_list(list(db.invoices.values()), preds, limit, offset)


@app.route("/invoices/<iid>/transition", methods=["POST"])
def invoice_transition(iid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:ISSUE|VOID|WRITE_OFF", True)})
    require_role(role, {"FinanceManager"})
    inv = db.invoices.get(iid)
    if not inv:
        raise e_not_found("Invoice not found")
    action = body["action"]
    c = db.contracts[inv["contract_id"]]
    if action == "ISSUE":
        if inv["invoice_status"] != "DRAFT":
            raise e_invalid_state("ISSUE requires DRAFT")
        if c["rights_status"] != "CLEAR":
            raise e_contested()
        if c["contract_status"] != "ACTIVE":
            raise e_contract_not_active()
        inv["invoice_status"] = "ISSUED"
        touch(inv)
        recompute_receivable(c)
    elif action == "VOID":
        if inv["invoice_status"] != "DRAFT":
            raise e_invalid_state("VOID requires DRAFT")
        inv["invoice_status"] = "VOID"
        touch(inv)
    else:  # WRITE_OFF
        if inv["invoice_status"] not in ("ISSUED", "PARTIALLY_PAID"):
            raise e_invalid_state("WRITE_OFF requires ISSUED or PARTIALLY_PAID")
        inv["invoice_status"] = "WRITTEN_OFF"
        touch(inv)
        recompute_receivable(c)
    return ok(pub(inv))


@app.route("/invoices/<iid>/payments", methods=["POST"])
def post_payment(iid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"amount_cents": ("int", True), "method": ("str", True),
                       "external_ref": ("str", False)})
    require_role(role, {"FinanceManager"})
    inv = db.invoices.get(iid)
    if not inv:
        raise e_not_found("Invoice not found")
    if inv["invoice_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise e_invoice_not_payable()
    amt = body["amount_cents"]
    if amt <= 0:
        raise e_invalid_amount("amount_cents must be a positive integer")
    remaining = inv["amount_cents"] - inv["paid_cents"] - inv["credits_applied_cents"]
    if amt > remaining:
        raise e_payment_balance()
    pay = {"payment_id": new_uuid(), "amount_cents": amt, "method": body["method"],
           "external_ref": body.get("external_ref"), "posted_at": now_iso(), "voided": False}
    inv["payments"].append(pay)
    inv["paid_cents"] += amt
    rederive_invoice_status(inv)
    touch(inv)
    recompute_receivable(db.contracts[inv["contract_id"]])
    return ok({"payment_id": pay["payment_id"], "invoice_id": inv["id"],
               "amount_cents": amt, "paid_cents_after": inv["paid_cents"],
               "invoice_status": inv["invoice_status"]})


@app.route("/invoices/<iid>/payments/<pid>/void", methods=["POST"])
def void_payment(iid, pid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {})
    require_role(role, {"FinanceManager"})
    inv = db.invoices.get(iid)
    if not inv:
        raise e_not_found("Invoice not found")
    pay = next((p for p in inv["payments"] if p["payment_id"] == pid), None)
    if not pay:
        raise e_not_found("Payment not found")
    if inv["invoice_status"] not in ("ISSUED", "PARTIALLY_PAID", "PAID"):
        raise e_invalid_state("Invoice does not accept payment voids")
    if pay["voided"]:
        raise e_invalid_state("Payment is already voided")
    pay["voided"] = True
    inv["paid_cents"] -= pay["amount_cents"]
    rederive_invoice_status(inv)
    touch(inv)
    recompute_receivable(db.contracts[inv["contract_id"]])
    return ok({"payment_id": pid, "invoice_id": inv["id"], "voided": True,
               "paid_cents_after": inv["paid_cents"],
               "invoice_status": inv["invoice_status"]})


# =============================================================================
# Valuation reports
# =============================================================================
@app.route("/valuation-reports", methods=["POST"])
def create_report():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"contract_id": ("str", True), "season": ("int", True)})
    require_role(role, {"ActivationManager"})
    c = db.contracts.get(body["contract_id"])
    if not c:
        raise e_not_found("Contract not found")
    v = db.venues[c["venue_id"]]
    season = body["season"]
    if season >= v["current_season"]:
        raise e_season_not_closed()
    if season < c["term_first_season"] or season > c["term_last_season"]:
        raise e_season_out_of_term()
    prov = 0
    fin = 0
    tot_approved = 0
    tot_contracted = 0
    due = 0
    season_dels = [d for d in db.deliverables.values()
                   if d["contract_id"] == c["id"] and d["season"] == season
                   and d["deliverable_status"] != "CANCELLED"]
    for d in season_dels:
        a = db.assets[d["asset_id"]]
        prov += d["approved_units"] * a["rate_card_unit_cents"]
        line = (Decimal(d["approved_units"]) * Decimal(a["avg_impressions_per_unit"])
                * Decimal(a["cpm_cents"]) / Decimal(1000))
        fin += int(line.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        tot_approved += d["approved_units"]
        tot_contracted += d["contracted_units"]
        for cr in db.credits.values():
            if (cr["deliverable_id"] == d["id"]
                    and cr["credit_status"] in ("APPROVED", "REDEEMED")):
                due += cr["approved_amount_cents"] or 0
    if tot_contracted > 0:
        pct = (Decimal(tot_approved) / Decimal(tot_contracted)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
        fulfillment = float(pct)
    else:
        fulfillment = 0.0
    r = create_record(db.reports, {
        "contract_id": c["id"], "season": season, "report_status": "DRAFT",
        "delivered_value_provisional_cents": prov,
        "delivered_value_final_cents": fin,
        "fulfillment_pct": fulfillment, "make_good_due_cents": due})
    return ok(pub(r), 201)


@app.route("/valuation-reports/<rid>", methods=["GET"])
def get_report(rid):
    uid, role = authn()
    r = db.reports.get(rid)
    if not r:
        raise e_not_found("Valuation report not found")
    check_scope(role, uid, db.contracts[r["contract_id"]]["sponsor_id"])
    return ok(pub(r))


@app.route("/valuation-reports", methods=["GET"])
def list_reports():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda r: db.contracts[r["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("season"), qfilter("report_status")]
    return do_list(list(db.reports.values()), preds, limit, offset)


@app.route("/valuation-reports/<rid>/transition", methods=["POST"])
def report_transition(rid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:ISSUE|ACKNOWLEDGE", True)})
    require_role(role, {"ActivationManager", "SponsorContact"})
    r = db.reports.get(rid)
    if not r:
        raise e_not_found("Valuation report not found")
    action = body["action"]
    if action == "ISSUE":
        if role != "ActivationManager":
            raise e_forbidden("ISSUE is reserved to ActivationManager")
        if r["report_status"] != "DRAFT":
            raise e_invalid_state("ISSUE requires DRAFT")
        r["report_status"] = "ISSUED"
        touch(r)
    else:  # ACKNOWLEDGE
        if role != "SponsorContact":
            raise e_forbidden("ACKNOWLEDGE is reserved to SponsorContact")
        c = db.contracts[r["contract_id"]]
        if c["sponsor_id"] != uid:
            raise e_forbidden("SponsorContact may only acknowledge their own sponsor's reports")
        if r["report_status"] != "ISSUED":
            raise e_invalid_state("ACKNOWLEDGE requires ISSUED")
        r["report_status"] = "ACKNOWLEDGED"
        touch(r)
    return ok(pub(r))


# =============================================================================
# Renewal opportunities
# =============================================================================
@app.route("/renewal-opportunities", methods=["POST"])
def create_opportunity():
    uid, role = authn()
    body = body_json()
    check_shape(body, {"contract_id": ("str", True), "proposed_fee_cents": ("int", True)})
    require_role(role, {"SponsorshipSales"})
    c = db.contracts.get(body["contract_id"])
    if not c:
        raise e_not_found("Contract not found")
    if any(o["contract_id"] == c["id"] and o["stage"] in ("IDENTIFIED", "PROPOSED", "NEGOTIATING")
           for o in db.opportunities.values()):
        raise e_dup_opportunity()
    if c["contract_status"] not in ("ACTIVE", "EXPIRED"):
        raise e_renewal_state()
    if body["proposed_fee_cents"] <= 0:
        raise e_invalid_amount("proposed_fee_cents must be a positive integer")
    o = create_record(db.opportunities, {"contract_id": c["id"],
                                         "proposed_fee_cents": body["proposed_fee_cents"],
                                         "stage": "IDENTIFIED",
                                         "resulting_contract_id": None})
    return ok(pub(o), 201)


@app.route("/renewal-opportunities/<oid>", methods=["GET"])
def get_opportunity(oid):
    uid, role = authn()
    o = db.opportunities.get(oid)
    if not o:
        raise e_not_found("Renewal opportunity not found")
    check_scope(role, uid, db.contracts[o["contract_id"]]["sponsor_id"])
    return ok(pub(o))


@app.route("/renewal-opportunities", methods=["GET"])
def list_opportunities():
    uid, role = authn()
    limit, offset = pagination_params()
    preds = []
    if role == "SponsorContact":
        preds.append(lambda o: db.contracts[o["contract_id"]]["sponsor_id"] == uid)
    preds += [qfilter("contract_id"), qfilter("resulting_contract_id"), qfilter("stage")]
    return do_list(list(db.opportunities.values()), preds, limit, offset)


def _create_renewal_contract(o):
    src = db.contracts[o["contract_id"]]
    new_first = src["term_last_season"] + 1
    new_last = new_first + (src["term_last_season"] - src["term_first_season"])
    return create_record(db.contracts, {
        "venue_id": src["venue_id"], "sponsor_id": src["sponsor_id"],
        "title": src["title"], "term_first_season": new_first,
        "term_last_season": new_last, "base_fee_cents": o["proposed_fee_cents"],
        "escalator_pct": src["escalator_pct"], "escalator_mode": src["escalator_mode"],
        "renewed_from_contract_id": src["id"],
        "contract_status": "DRAFT", "rights_status": "CLEAR",
        "scheduled_total_cents": 0, "receivable_cents": 0,
        "make_good_outstanding_cents": 0})


@app.route("/renewal-opportunities/<oid>/transition", methods=["POST"])
def opportunity_transition(oid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"action": ("enum:PROPOSE|OPEN_NEGOTIATION|MARK_WON|MARK_LOST", True)})
    require_role(role, {"SponsorshipSales"})
    o = db.opportunities.get(oid)
    if not o:
        raise e_not_found("Renewal opportunity not found")
    action = body["action"]
    if action == "PROPOSE":
        if o["stage"] != "IDENTIFIED":
            raise e_invalid_state("PROPOSE requires IDENTIFIED")
        o["stage"] = "PROPOSED"
    elif action == "OPEN_NEGOTIATION":
        if o["stage"] != "PROPOSED":
            raise e_invalid_state("OPEN_NEGOTIATION requires PROPOSED")
        o["stage"] = "NEGOTIATING"
    elif action == "MARK_WON":
        if o["stage"] not in ("PROPOSED", "NEGOTIATING"):
            raise e_invalid_state("MARK_WON requires PROPOSED or NEGOTIATING")
        new_c = _create_renewal_contract(o)
        o["resulting_contract_id"] = new_c["id"]
        o["stage"] = "WON"
    else:  # MARK_LOST
        if o["stage"] not in ("IDENTIFIED", "PROPOSED", "NEGOTIATING"):
            raise e_invalid_state("MARK_LOST requires IDENTIFIED, PROPOSED, or NEGOTIATING")
        o["stage"] = "LOST"
    touch(o)
    return ok(pub(o))


@app.route("/renewal-opportunities/<oid>/counter", methods=["POST"])
def opportunity_counter(oid):
    uid, role = authn()
    body = body_json()
    check_shape(body, {"proposed_fee_cents": ("int", True),
                       "expected_opportunity_version": ("int", True)})
    require_role(role, {"SponsorshipSales"})
    o = db.opportunities.get(oid)
    if not o:
        raise e_not_found("Renewal opportunity not found")
    if o["stage"] != "NEGOTIATING":
        raise e_invalid_state("Counter requires NEGOTIATING")
    if body["expected_opportunity_version"] != o["version"]:
        raise e_stale_opportunity()
    if body["proposed_fee_cents"] <= 0:
        raise e_invalid_amount("proposed_fee_cents must be a positive integer")
    o["proposed_fee_cents"] = body["proposed_fee_cents"]
    o["stage"] = "PROPOSED"
    touch(o)
    return ok(pub(o))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
