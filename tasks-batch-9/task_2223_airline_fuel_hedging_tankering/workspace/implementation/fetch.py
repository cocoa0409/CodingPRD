"""Path- and body-level existence lookups (validation ladder steps 4 and 5)."""

from db import db
from errors import fail


def _get(table, row_id, error_id, label):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "No %s with id %r." % (label, row_id))
    return row


def policy(row_id):
    return _get(db.policies, row_id, "ERR_POLICY_NOT_FOUND", "HedgePolicy")


def counterparty(row_id):
    return _get(db.counterparties, row_id, "ERR_COUNTERPARTY_NOT_FOUND", "Counterparty")


def station(row_id):
    return _get(db.stations, row_id, "ERR_STATION_NOT_FOUND", "Station")


def forecast(row_id):
    return _get(db.forecasts, row_id, "ERR_FORECAST_NOT_FOUND", "ConsumptionForecast")


def program(row_id):
    return _get(db.programs, row_id, "ERR_PROGRAM_NOT_FOUND", "HedgeProgram")


def instrument(row_id):
    return _get(db.instruments, row_id, "ERR_INSTRUMENT_NOT_FOUND", "HedgeInstrument")


def posting(row_id):
    return _get(db.postings, row_id, "ERR_COLLATERAL_POSTING_NOT_FOUND", "CollateralPosting")


def mtm_run(row_id):
    return _get(db.mtm_runs, row_id, "ERR_MTM_RUN_NOT_FOUND", "MarkToMarketRun")


def flight_leg(row_id):
    return _get(db.legs, row_id, "ERR_FLIGHT_LEG_NOT_FOUND", "FlightLeg")


def directive(row_id):
    return _get(db.directives, row_id, "ERR_DIRECTIVE_NOT_FOUND", "TankeringDirective")


def exception(row_id):
    return _get(db.exceptions, row_id, "ERR_EXCEPTION_NOT_FOUND", "PolicyException")
