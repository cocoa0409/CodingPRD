"""Resource resolution helpers. Path params resolve left to right, before any body work."""

from db import db
from errors import ApiError

NOT_FOUND = {
    "markets": "ERR_MARKET_NOT_FOUND",
    "media_channels": "ERR_MEDIA_CHANNEL_NOT_FOUND",
    "geo_cells": "ERR_GEO_CELL_NOT_FOUND",
    "data_windows": "ERR_DATA_WINDOW_NOT_FOUND",
    "spend_observations": "ERR_SPEND_OBSERVATION_NOT_FOUND",
    "sales_observations": "ERR_SALES_OBSERVATION_NOT_FOUND",
    "model_runs": "ERR_MODEL_RUN_NOT_FOUND",
    "channel_contributions": "ERR_CHANNEL_CONTRIBUTION_NOT_FOUND",
    "experiments": "ERR_EXPERIMENT_NOT_FOUND",
    "calibration_records": "ERR_CALIBRATION_RECORD_NOT_FOUND",
    "budget_scenarios": "ERR_BUDGET_SCENARIO_NOT_FOUND",
    "budget_allocations": "ERR_BUDGET_ALLOCATION_NOT_FOUND",
    "reconciliation_reports": "ERR_RECONCILIATION_REPORT_NOT_FOUND",
}


def must(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def must_field(collection, body, field_name, required=True):
    """Resolve a body foreign key, raising the collection's not-found error."""
    value = body.get(field_name)
    if value is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % field_name)
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an identifier string." % field_name)
    return must(collection, value)
