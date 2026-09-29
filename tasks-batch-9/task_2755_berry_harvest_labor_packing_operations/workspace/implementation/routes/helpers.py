"""Shared route plumbing: short role aliases and list filtering."""

from flask import request

import config

HM = config.ROLE_HARVEST_MANAGER
FSO = config.ROLE_FOOD_SAFETY_OFFICER
CS = config.ROLE_CREW_SUPERVISOR
PC = config.ROLE_PAYROLL_CLERK
PO = config.ROLE_PACKHOUSE_OPERATOR
SM = config.ROLE_SALES_MANAGER
PICKER = config.ROLE_PICKER

ALL_READERS = (HM, FSO, CS, PC, PO, SM)


def filter_args(records, spec):
    """Apply the optional equality filters a list endpoint declares.

    `spec` maps query-parameter name -> record field name. An absent or empty
    parameter is ignored; an unmatched value simply yields an empty page.
    """
    for arg, field in spec.items():
        raw = request.args.get(arg)
        if raw is None or raw == "":
            continue
        records = [r for r in records if r.get(field) == raw]
    return records
