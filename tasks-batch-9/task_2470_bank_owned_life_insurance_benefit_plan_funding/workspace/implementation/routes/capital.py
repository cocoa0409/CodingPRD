"""Capital snapshots: the shared denominator (PRD 2.7)."""

from flask import Blueprint

from cascades import rerate_all_carriers_after_snapshot
from response import resource_response
from store import create_record, db
from validation import (
    actor,
    authorize,
    find_capital_position,
    get_datetime,
    get_money,
    json_body,
)

bp = Blueprint("capital", __name__)


@bp.post("/capital-positions")
def file_capital_position():
    authorize(("TreasuryController",))
    body = json_body()
    raw_as_of, as_of = get_datetime(body, "as_of_date", required=True)
    tier1 = get_money(body, "tier1_capital_usd", required=True, positive_only=True)
    total_assets = get_money(body, "total_assets_usd", required=True, positive_only=True)

    record = create_record(
        db.capital_positions,
        {
            "as_of_date": raw_as_of,
            "_as_of_date": as_of,
            "tier1_capital_usd": tier1,
            "total_assets_usd": total_assets,
            "recorded_by_user_id": actor(),
        },
        versioned=False,
    )
    # a new latest snapshot re-rates every carrier's concentration posture
    rerate_all_carriers_after_snapshot()
    return resource_response(record, 201)


@bp.get("/capital-positions/<record_id>")
def read_capital_position(record_id):
    authorize(("TreasuryController", "RiskOfficer", "BoardSecretary"))
    return resource_response(find_capital_position(record_id))
