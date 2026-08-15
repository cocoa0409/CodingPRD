"""Cooperative service: CRUD, post-margin."""
from errors import ApiError
from db import store, new_common, touch


def create_cooperative(body):
    """Create a Cooperative config. Role: PlatformAdmin."""
    required = ["name", "fiscal_year_end_month", "retirement_methods_allowed",
                "unclaimed_dormancy_years", "annual_meeting_quorum_pct",
                "irrigation_season_start_month", "irrigation_season_end_month"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    coop = new_common({
        "name": body["name"],
        "fiscal_year_end_month": body["fiscal_year_end_month"],
        "capital_credits_pool_cents": 0,
        "retirement_methods_allowed": body["retirement_methods_allowed"],
        "unclaimed_dormancy_years": body["unclaimed_dormancy_years"],
        "annual_meeting_quorum_pct": body["annual_meeting_quorum_pct"],
        "irrigation_season_start_month": body["irrigation_season_start_month"],
        "irrigation_season_end_month": body["irrigation_season_end_month"],
        "active_election_id": None,
    })
    store.cooperatives[coop["id"]] = coop
    return coop


def get_cooperative(coop_id):
    coop = store.cooperatives.get(coop_id)
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")
    return coop


def list_cooperatives(active_election_id=None):
    rows = list(store.cooperatives.values())
    if active_election_id is not None:
        rows = [r for r in rows if str(r.get("active_election_id")) == str(active_election_id)]
    return rows


def post_margin(coop_id, body):
    """Post year-end patronage margin into the allocation pool."""
    coop = get_cooperative(coop_id)
    if "fiscal_year" not in body or "margin_cents" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, "fiscal_year and margin_cents are required")
    coop["capital_credits_pool_cents"] = coop.get("capital_credits_pool_cents", 0) + body["margin_cents"]
    touch(coop)
    return coop
