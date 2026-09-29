"""Path- and body-reference existence lookups (PRD section 2.7, priorities 6-23)."""
from db import DB
from errors import ApiError


def _get(collection, key, error_id):
    record = collection.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def get_estate(estate_id):
    return _get(DB.estates, estate_id, "ERR_ESTATE_NOT_FOUND")


def get_fiduciary(fiduciary_id):
    return _get(DB.fiduciaries, fiduciary_id, "ERR_FIDUCIARY_NOT_FOUND")


def get_document(document_id):
    return _get(DB.documents, document_id, "ERR_DOCUMENT_NOT_FOUND")


def get_platform(platform_id):
    return _get(DB.platforms, platform_id, "ERR_PLATFORM_NOT_FOUND")


def get_directive(directive_id):
    return _get(DB.directives, directive_id, "ERR_DIRECTIVE_NOT_FOUND")


def get_asset(asset_id):
    return _get(DB.assets, asset_id, "ERR_ASSET_NOT_FOUND")


def get_term(term_id):
    return _get(DB.terms, term_id, "ERR_SUBSCRIPTION_TERM_NOT_FOUND")


def get_request(request_id):
    return _get(DB.requests, request_id, "ERR_REQUEST_NOT_FOUND")


def get_grant(grant_id):
    return _get(DB.grants, grant_id, "ERR_GRANT_NOT_FOUND")


def get_designation(designation_id):
    return _get(DB.designations, designation_id, "ERR_DESIGNATION_NOT_FOUND")


def get_election(election_id):
    return _get(DB.elections, election_id, "ERR_ELECTION_NOT_FOUND")


def get_order(order_id):
    return _get(DB.orders, order_id, "ERR_ORDER_NOT_FOUND")


def get_claim(claim_id):
    return _get(DB.claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def get_run(run_id):
    return _get(DB.runs, run_id, "ERR_VALUATION_RUN_NOT_FOUND")


# ------------------------------------------------------- ownership walk-ups

def estate_of_asset(asset):
    return DB.estates.get(asset["estate_id"])


def asset_of_term(term):
    return DB.assets.get(term["asset_id"])


def asset_of_order(order):
    return DB.assets.get(order["asset_id"])


def order_of_claim(claim):
    return DB.orders.get(claim["cancellation_order_id"])


def asset_of_claim(claim):
    order = order_of_claim(claim)
    return DB.assets.get(order["asset_id"]) if order else None


def asset_of_election(election):
    return DB.assets.get(election["asset_id"])


def estate_of_term(term):
    asset = asset_of_term(term)
    return estate_of_asset(asset) if asset else None


def estate_of_order(order):
    asset = asset_of_order(order)
    return estate_of_asset(asset) if asset else None


def estate_of_claim(claim):
    asset = asset_of_claim(claim)
    return estate_of_asset(asset) if asset else None


def estate_of_election(election):
    asset = asset_of_election(election)
    return estate_of_asset(asset) if asset else None


# ------------------------------------------------------- child collections

def estate_assets(estate_id):
    return [a for a in DB.assets.values() if a["estate_id"] == estate_id]


def estate_documents(estate_id):
    return [d for d in DB.documents.values() if d["estate_id"] == estate_id]


def estate_fiduciaries(estate_id):
    return [f for f in DB.fiduciaries.values() if f["estate_id"] == estate_id]


def estate_directives(estate_id):
    return [d for d in DB.directives.values() if d["estate_id"] == estate_id]


def estate_requests(estate_id):
    return [r for r in DB.requests.values() if r["estate_id"] == estate_id]


def estate_grants(estate_id):
    return [g for g in DB.grants.values() if g["estate_id"] == estate_id]


def estate_designations(estate_id):
    return [d for d in DB.designations.values() if d["estate_id"] == estate_id]


def estate_runs(estate_id):
    return [r for r in DB.runs.values() if r["estate_id"] == estate_id]


def asset_terms(asset_id):
    return [t for t in DB.terms.values() if t["asset_id"] == asset_id]


def asset_orders(asset_id):
    return [o for o in DB.orders.values() if o["asset_id"] == asset_id]


def asset_elections(asset_id):
    return [e for e in DB.elections.values() if e["asset_id"] == asset_id]


def order_claims(order_id):
    return [c for c in DB.claims.values() if c["cancellation_order_id"] == order_id]


def estate_orders(estate_id):
    ids = {a["id"] for a in estate_assets(estate_id)}
    return [o for o in DB.orders.values() if o["asset_id"] in ids]


def estate_terms(estate_id):
    ids = {a["id"] for a in estate_assets(estate_id)}
    return [t for t in DB.terms.values() if t["asset_id"] in ids]


def estate_claims(estate_id):
    ids = {o["id"] for o in estate_orders(estate_id)}
    return [c for c in DB.claims.values() if c["cancellation_order_id"] in ids]
