"""Identifier resolution -- PRD 2.7 / 2.11 band 3 not-found family."""

import db
from errors import ApiError

_SPEC = {
    "programs": "ERR_REFRIGERANT_PROGRAM_NOT_FOUND",
    "standards": "ERR_REGIONAL_STANDARD_NOT_FOUND",
    "platforms": "ERR_PLATFORM_NOT_FOUND",
    "certs": "ERR_CERTIFICATION_NOT_FOUND",
    "supplies": "ERR_COMPONENT_SUPPLY_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "builds": "ERR_BUILD_ORDER_NOT_FOUND",
    "warehouses": "ERR_WAREHOUSE_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "cells": "ERR_TEST_CELL_NOT_FOUND",
    "claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "capas": "ERR_CORRECTIVE_ACTION_NOT_FOUND",
}


def require(collection, row_id):
    row = db.db.get(collection, row_id)
    if row is None:
        raise ApiError(_SPEC[collection], "Referenced record does not exist.")
    return row


def program(row_id):
    return require("programs", row_id)


def standard(row_id):
    return require("standards", row_id)


def platform(row_id):
    return require("platforms", row_id)


def cert(row_id):
    return require("certs", row_id)


def supply(row_id):
    return require("supplies", row_id)


def order(row_id):
    return require("orders", row_id)


def build(row_id):
    return require("builds", row_id)


def warehouse(row_id):
    return require("warehouses", row_id)


def reservation(row_id):
    return require("reservations", row_id)


def cell(row_id):
    return require("cells", row_id)


def claim(row_id):
    return require("claims", row_id)


def capa(row_id):
    return require("capas", row_id)
