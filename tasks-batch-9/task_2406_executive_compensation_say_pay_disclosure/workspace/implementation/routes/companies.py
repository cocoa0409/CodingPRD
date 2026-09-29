"""Companies, market data and executives (PRD §3.1)."""

from flask import Blueprint

import calc
from db import apply_changes, insert, now, ordered, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_IR_LEAD,
    authenticate,
)
from response import object_response
from routes.common import fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("companies", __name__)

GICS_SECTORS = {"TECH", "INDUSTRIALS", "HEALTHCARE", "FINANCIALS", "CONSUMER", "ENERGY"}
LISTING_STATUSES = {"ACTIVE", "DELISTED"}
ROLE_TITLES = {"CEO", "CFO", "COO", "CHRO", "GC"}
MARKET_FIELDS = (
    "revenue_usd",
    "market_cap_usd",
    "share_price_usd",
    "ceo_tdc_usd",
    "listing_status",
)


@bp.post("/exec-comp/companies")
def create_company():
    authenticate([ROLE_COMP_CONSULTANT])
    body = Body()
    legal_name = body.string("legal_name", required=True, min_len=1, max_len=120)
    ticker = body.string("ticker", required=True, min_len=1, max_len=5)
    if not ticker.isupper() or not ticker.isalpha():
        raise ApiError("ERR_INVALID_REQUEST", "ticker must be 1-5 uppercase letters")
    is_issuer = body.boolean("is_issuer", default=False)
    gics_sector = body.enum("gics_sector", GICS_SECTORS, required=True)
    revenue_usd = body.number("revenue_usd", required=True, gt=0, places=2)
    market_cap_usd = body.number("market_cap_usd", required=True, gt=0, places=2)
    share_price_usd = body.number("share_price_usd", required=True, gt=0, places=2)
    ceo_tdc_usd = body.number("ceo_tdc_usd", required=True, minimum=0, places=2)
    listing_status = body.enum("listing_status", LISTING_STATUSES, default="ACTIVE")

    for existing in store.companies.values():
        if existing["ticker"] == ticker:
            raise ApiError("ERR_ISSUER_ALREADY_EXISTS", "ticker is already registered")
        if is_issuer and existing["is_issuer"]:
            raise ApiError("ERR_ISSUER_ALREADY_EXISTS", "an issuer is already registered")

    company = insert(
        store.companies,
        {
            "legal_name": legal_name,
            "ticker": ticker,
            "is_issuer": is_issuer,
            "gics_sector": gics_sector,
            "revenue_usd": revenue_usd,
            "market_cap_usd": market_cap_usd,
            "share_price_usd": share_price_usd,
            "ceo_tdc_usd": ceo_tdc_usd,
            "listing_status": listing_status,
            "market_data_updated_at": now(),
        },
    )
    return object_response(company, 201)


@bp.get("/exec-comp/companies/<cid>")
def read_company(cid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_IR_LEAD])
    return object_response(fetch("companies", cid))


@bp.post("/exec-comp/companies/<cid>/market-data")
def refresh_market_data(cid):
    authenticate([ROLE_COMP_CONSULTANT])
    company = fetch("companies", cid)
    body = Body()
    if not any(body.present(field) for field in MARKET_FIELDS):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "a refresh must carry at least one market-data field",
        )
    revenue_usd = body.number("revenue_usd", gt=0, places=2)
    market_cap_usd = body.number("market_cap_usd", gt=0, places=2)
    share_price_usd = body.number("share_price_usd", gt=0, places=2)
    ceo_tdc_usd = body.number("ceo_tdc_usd", minimum=0, places=2)
    listing_status = body.enum("listing_status", LISTING_STATUSES)

    if company["listing_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_REQUEST", "a delisted company can no longer be refreshed"
        )

    price_supplied = share_price_usd is not None
    changes = {"market_data_updated_at": now()}
    if revenue_usd is not None:
        changes["revenue_usd"] = revenue_usd
    if market_cap_usd is not None:
        changes["market_cap_usd"] = market_cap_usd
    if share_price_usd is not None:
        changes["share_price_usd"] = share_price_usd
    if ceo_tdc_usd is not None:
        changes["ceo_tdc_usd"] = ceo_tdc_usd
    if listing_status is not None:
        changes["listing_status"] = listing_status
    apply_changes(company, changes)
    touch(company)

    _market_data_cascade(company, price_supplied)
    return object_response(company)


def _market_data_cascade(company, price_supplied):
    # L1: re-size every ACCEPTED membership touching this company in a group
    #     that is still DRAFT or SCREENED.
    reverting_groups = []
    for member in ordered(list(store.peer_group_members.values())):
        if member["status"] != "ACCEPTED":
            continue
        group = store.peer_groups.get(member["peer_group_id"])
        if group is None or group["status"] not in ("DRAFT", "SCREENED"):
            continue
        if (
            member["peer_company_id"] != company["id"]
            and group["issuer_company_id"] != company["id"]
        ):
            continue
        was_in_band = member["in_size_band"]
        in_band = domain.recompute_member_fit(member)
        # L2: a membership whose fit flipped to false pulls a SCREENED group back.
        if (
            group["status"] == "SCREENED"
            and was_in_band is True
            and in_band is False
            and group not in reverting_groups
        ):
            reverting_groups.append(group)

    for group in reverting_groups:
        domain.revert_group_to_draft(group)
        # L3: dependent DRAFT programs lose their benchmark-derived fields.
        domain.clear_dependent_draft_programs(group)

    # Independent leg: a share-price move re-marks outstanding awards.
    if price_supplied:
        for program in ordered(list(store.pay_programs.values())):
            if program["issuer_company_id"] != company["id"]:
                continue
            for award in domain.program_awards(program["id"]):
                if award["status"] == "GRANTED":
                    domain.recompute_award_values(award)
            before = domain.watched(program)
            domain.recompute_program_alignment(program)
            domain.stale_if_watched_changed(program, before)


@bp.get("/exec-comp/companies/<cid>/peer-groups")
def list_company_peer_groups(cid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    company = fetch("companies", cid)
    rows = ordered(
        [
            g
            for g in store.peer_groups.values()
            if g["issuer_company_id"] == company["id"]
        ]
    )
    return paginated(rows)


@bp.get("/exec-comp/companies/<cid>/peer-memberships")
def list_company_memberships(cid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR])
    company = fetch("companies", cid)
    rows = ordered(
        [
            m
            for m in store.peer_group_members.values()
            if m["peer_company_id"] == company["id"]
        ]
    )
    return paginated(rows)


@bp.get("/exec-comp/companies/<cid>/executives")
def list_company_executives(cid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    company = fetch("companies", cid)
    rows = ordered(
        [e for e in store.executives.values() if e["company_id"] == company["id"]]
    )
    return paginated(rows)


@bp.post("/exec-comp/companies/<cid>/executives")
def create_executive(cid):
    authenticate([ROLE_COMP_CONSULTANT])
    company = fetch("companies", cid)
    body = Body()
    full_name = body.string("full_name", required=True, min_len=1, max_len=120)
    role_title = body.enum("role_title", ROLE_TITLES, required=True)
    is_neo = body.boolean("is_neo", default=True)
    base_salary_usd = body.number("base_salary_usd", required=True, gt=0, places=2)
    sti_target_pct = body.number(
        "sti_target_pct", required=True, minimum=0, maximum=400, places=2
    )
    executive = insert(
        store.executives,
        {
            "company_id": company["id"],
            "full_name": full_name,
            "role_title": role_title,
            "is_neo": is_neo,
            "base_salary_usd": base_salary_usd,
            "sti_target_pct": sti_target_pct,
        },
    )
    return object_response(executive, 201)


@bp.get("/exec-comp/companies/<cid>/restatement-events")
def list_company_restatements(cid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    company = fetch("companies", cid)
    rows = ordered(
        [
            e
            for e in store.restatement_events.values()
            if e["company_id"] == company["id"]
        ]
    )
    return paginated(rows)
