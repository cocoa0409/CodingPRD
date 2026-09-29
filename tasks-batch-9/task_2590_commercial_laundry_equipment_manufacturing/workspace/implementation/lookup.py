"""Path- and body-level resource resolution with the scaffold's error ids."""

from db import db
from errors import (ERR_BUILD_NOT_FOUND, ERR_CLAIM_NOT_FOUND,
                    ERR_DISTRIBUTOR_NOT_FOUND, ERR_DOSSIER_NOT_FOUND,
                    ERR_LOG_NOT_FOUND, ERR_MODEL_NOT_FOUND,
                    ERR_PART_NOT_FOUND, ERR_PROGRAM_NOT_FOUND,
                    ERR_QUOTE_LINE_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
                    ERR_STATION_NOT_FOUND, ERR_TECHNICIAN_NOT_FOUND, fail)


def _get(table, resource_id, error_id, label):
    row = table.get(resource_id)
    if row is None:
        fail(error_id, "No %s with id '%s' exists." % (label, resource_id))
    return row


def model(resource_id):
    return _get(db.models, resource_id, ERR_MODEL_NOT_FOUND, "machine model")


def program(resource_id):
    return _get(db.programs, resource_id, ERR_PROGRAM_NOT_FOUND, "rebate program")


def dossier(resource_id):
    return _get(db.dossiers, resource_id, ERR_DOSSIER_NOT_FOUND,
                "certification dossier")


def part(resource_id):
    return _get(db.parts, resource_id, ERR_PART_NOT_FOUND, "service part")


def station(resource_id):
    return _get(db.stations, resource_id, ERR_STATION_NOT_FOUND, "assembly station")


def technician(resource_id):
    return _get(db.technicians, resource_id, ERR_TECHNICIAN_NOT_FOUND, "technician")


def build(resource_id):
    return _get(db.builds, resource_id, ERR_BUILD_NOT_FOUND, "build order")


def station_log(resource_id):
    return _get(db.logs, resource_id, ERR_LOG_NOT_FOUND, "station log")


def distributor(resource_id):
    return _get(db.distributors, resource_id, ERR_DISTRIBUTOR_NOT_FOUND, "distributor")


def quote(resource_id):
    return _get(db.quotes, resource_id, ERR_QUOTE_NOT_FOUND, "package quote")


def quote_line(resource_id):
    return _get(db.quote_lines, resource_id, ERR_QUOTE_LINE_NOT_FOUND, "quote line")


def quote_line_of(quote_row, line_id):
    """PRD 2.9: a child identifier must belong to the resolved parent."""
    line = db.quote_lines.get(line_id)
    if line is None or line["quote_id"] != quote_row["id"]:
        fail(ERR_QUOTE_LINE_NOT_FOUND,
             "No quote line with id '%s' exists on this quote." % line_id)
    return line


def claim(resource_id):
    return _get(db.claims, resource_id, ERR_CLAIM_NOT_FOUND, "warranty claim")
