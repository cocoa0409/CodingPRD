"""Clock, service accounts, contracts and beer lines."""
from flask import Blueprint, g

import projections
import serializers
import settlement
import store
from common import (ALLOWED_FREQUENCY_DAYS, API_PREFIX, D, FREQUENCY_MULTIPLIER,
                    ROLE_AUDITOR, ROLE_BREWER, ROLE_DISPATCH, ROLE_TECH, ROLE_VENUE)
from envelope import empty_response, object_response
from errors import raise_error
from helpers import listing, match, resolve_body, resolve_path
from security import guard
from shape import F, parse_body, query_bool, query_enum, query_str

bp = Blueprint("core", __name__)

ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
BILLING_MODES = ["PROGRAM_BILL", "DIRECT_BILL"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED"]
FUNDING_STATUSES = ["NONE", "BREWER_FUNDED", "SELF_FUNDED"]
LINE_STATUSES = ["IN_SERVICE", "OUT_OF_SERVICE"]
COMPLIANCE_FLAGS = ["COMPLIANT", "NON_COMPLIANT"]
BEER_STYLE_GROUPS = ["ALE", "LAGER", "NITRO", "CIDER"]
BORES = [D("0.1875"), D("0.25"), D("0.375")]


# ------------------------------------------------------------------- the clock

@bp.post(API_PREFIX + "/_clock/set_current_utc")
@guard(ROLE_DISPATCH, ROLE_TECH, ROLE_VENUE, ROLE_AUDITOR, ROLE_BREWER)
def set_clock():
    body = parse_body([F("current_utc", "datetime", required=True)])
    store.set_clock(body["current_utc"])
    # Every time-dependent projection (line days_overdue / compliance_flag, loop
    # health_score / status) is re-derived from the clock whenever it is read, so
    # the new instant is reflected the moment this response is built.
    return empty_response()


# ---------------------------------------------------------------- service accounts

@bp.post(API_PREFIX + "/accounts")
@guard(ROLE_DISPATCH)
def create_account():
    body = parse_body([
        F("venue_name", "str", required=True, max_len=120),
        F("access_window_start_minute", "int", required=True, min_value=0, max_value=1439),
        F("access_window_end_minute", "int", required=True, min_value=1, max_value=1440),
        F("glycol_system_present", "bool"),
    ])
    if body["access_window_end_minute"] <= body["access_window_start_minute"]:
        raise_error("ERR_INVALID_REQUEST",
                    "access_window_end_minute must be strictly greater than the start.")
    glycol = bool(body["glycol_system_present"]) if body["glycol_system_present"] is not None else False
    account = store.new_row({
        "venue_name": body["venue_name"],
        "status": "ACTIVE",
        "access_window_start_minute": body["access_window_start_minute"],
        "access_window_end_minute": body["access_window_end_minute"],
        "glycol_system_present": glycol,
        "billing_mode": "DIRECT_BILL",
        "lines_out_of_service_count": 0,
        "open_complaint_count": 0,
        "suspended_reason": "NONE",
    })
    store.accounts[account["id"]] = account
    if glycol:
        # The loop is minted by the same request but is not part of this payload.
        loop = store.new_row({
            "account_id": account["id"],
            "glycol_pct": D("35.0"),
            "pump_psi": D("12.0"),
            "bath_temp_f": D("28.0"),
        })
        loop["last_serviced_at"] = loop["created_at"]
        store.glycol_loops[loop["id"]] = loop
    return object_response(serializers.account(account), 201)


@bp.get(API_PREFIX + "/accounts/<account_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_VENUE, ROLE_BREWER)
def read_account(account_id):
    account = resolve_path("account_id", account_id)
    return object_response(serializers.account(account))


@bp.get(API_PREFIX + "/accounts")
@guard(ROLE_DISPATCH, ROLE_AUDITOR)
def list_accounts():
    status = query_enum("status", ACCOUNT_STATUSES)
    billing_mode = query_enum("billing_mode", BILLING_MODES)
    rows = [r for r in store.accounts.values()
            if match(r, "status", status) and match(r, "billing_mode", billing_mode)]
    return listing(rows, serializers.account)


@bp.post(API_PREFIX + "/accounts/<account_id>/status")
@guard(ROLE_AUDITOR)
def account_status(account_id):
    account = resolve_path("account_id", account_id)
    body = parse_body([F("to_status", "enum", required=True, values=ACCOUNT_STATUSES)])
    target = body["to_status"]
    if target == "SUSPENDED":
        if account["status"] != "ACTIVE":
            raise_error("ERR_ACCOUNT_NOT_ACTIVE")
        if projections.has_open_visits(account["id"]):
            raise_error("ERR_ACCOUNT_HAS_OPEN_VISITS")
        projections.suspend_account(account, "MANUAL")
    elif target == "ACTIVE":
        if account["status"] != "SUSPENDED":
            raise_error("ERR_ACCOUNT_NOT_ACTIVE")
        candidates = [c for c in store.account_contracts(account["id"])
                      if c["status"] != "EXPIRED"]
        newest = store.by_created_desc(candidates)[0] if candidates else None
        if newest is None or account["lines_out_of_service_count"] * 2 >= newest["contracted_line_count"]:
            raise_error("ERR_LINE_COMPLIANCE_UNRESOLVED")
        account["status"] = "ACTIVE"
        account["suspended_reason"] = "NONE"
        store.touch(account)
        for contract in store.account_contracts(account["id"]):
            if contract["status"] == "SUSPENDED":
                contract["status"] = "ACTIVE"
                store.touch(contract)
                projections.recompute_billing_mode(account)
    else:
        if account["status"] not in ("ACTIVE", "SUSPENDED"):
            raise_error("ERR_ACCOUNT_NOT_ACTIVE")
        if projections.has_open_visits(account["id"]):
            raise_error("ERR_ACCOUNT_HAS_OPEN_VISITS")
        account["status"] = "TERMINATED"
        store.touch(account)
        for contract in store.account_contracts(account["id"]):
            if contract["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
                contract["status"] = "EXPIRED"
                store.touch(contract)
        projections.recompute_billing_mode(account)
    return object_response(serializers.account(account))


# --------------------------------------------------------------------- contracts

@bp.post(API_PREFIX + "/contracts")
@guard(ROLE_DISPATCH)
def create_contract():
    body = parse_body([
        F("account_id", "id", required=True),
        F("cleaning_frequency_days", "int", required=True),
        F("contracted_line_count", "int", required=True, min_value=1),
        F("per_line_rate_cents", "int", required=True, min_value=0),
        F("visit_base_fee_cents", "int", required=True, min_value=0),
        F("effective_from", "datetime", required=True),
        F("expected_account_version", "int", required=True),
        F("brewer_program_id", "id", nullable=True),
    ])
    if body["cleaning_frequency_days"] not in ALLOWED_FREQUENCY_DAYS:
        raise_error("ERR_INVALID_REQUEST",
                    "cleaning_frequency_days must be exactly 14, 21 or 28.")
    account = resolve_body("account_id", body["account_id"])
    program = resolve_body("brewer_program_id", body["brewer_program_id"], optional=True)
    if body["expected_account_version"] != account["version"]:
        raise_error("ERR_STALE_ACCOUNT_VERSION")
    if account["status"] != "ACTIVE":
        raise_error("ERR_ACCOUNT_NOT_ACTIVE")
    contract = store.new_row({
        "account_id": account["id"],
        "brewer_program_id": program["id"] if program is not None else None,
        "status": "DRAFT",
        "cleaning_frequency_days": body["cleaning_frequency_days"],
        "contracted_line_count": body["contracted_line_count"],
        "per_line_rate_cents": body["per_line_rate_cents"],
        "visit_base_fee_cents": body["visit_base_fee_cents"],
        "effective_from": body["effective_from"],
        "funding_status": "NONE",
        "frequency_multiplier": FREQUENCY_MULTIPLIER[body["cleaning_frequency_days"]],
    })
    if program is not None:
        contract["funding_status"] = ("BREWER_FUNDED" if program["status"] == "ACTIVE"
                                     else "SELF_FUNDED")
    store.contracts[contract["id"]] = contract
    store.touch(account)          # drafting increments the owning account's version
    return object_response(serializers.contract(contract), 201)


@bp.get(API_PREFIX + "/contracts/<contract_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_VENUE, ROLE_BREWER)
def read_contract(contract_id):
    return object_response(serializers.contract(resolve_path("contract_id", contract_id)))


@bp.get(API_PREFIX + "/contracts")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_VENUE, ROLE_BREWER)
def list_contracts():
    account_id = query_str("account_id")
    program_id = query_str("brewer_program_id")
    status = query_enum("status", CONTRACT_STATUSES)
    funding_status = query_enum("funding_status", FUNDING_STATUSES)
    rows = [r for r in store.contracts.values()
            if match(r, "account_id", account_id)
            and match(r, "brewer_program_id", program_id)
            and match(r, "status", status)
            and match(r, "funding_status", funding_status)]
    return listing(rows, serializers.contract)


@bp.post(API_PREFIX + "/contracts/<contract_id>/status")
@guard(ROLE_DISPATCH)
def contract_status(contract_id):
    contract = resolve_path("contract_id", contract_id)
    body = parse_body([F("to_status", "enum", required=True,
                         values=["ACTIVE", "SUSPENDED", "EXPIRED"])])
    target = body["to_status"]
    account = store.accounts.get(contract["account_id"])
    if target == "ACTIVE" and contract["status"] == "DRAFT":
        if account is not None and account["status"] != "ACTIVE":
            raise_error("ERR_ACCOUNT_NOT_ACTIVE")
        program_id = contract.get("brewer_program_id")
        if program_id is not None:
            program = store.programs.get(program_id)
            if program is None or program["status"] != "ACTIVE":
                raise_error("ERR_PROGRAM_NOT_ACTIVE")
        if store.now() < contract["effective_from"]:
            raise_error("ERR_CONTRACT_NOT_YET_EFFECTIVE")
        for sibling in store.account_contracts(contract["account_id"]):
            if sibling["id"] != contract["id"] and sibling["status"] == "ACTIVE":
                sibling["status"] = "EXPIRED"
                store.touch(sibling)
        contract["status"] = "ACTIVE"
        store.touch(contract)
        if account is not None:
            projections.recompute_billing_mode(account)
            store.touch(account)   # activation increments the account version again
    elif target == "ACTIVE" and contract["status"] == "SUSPENDED":
        if account is not None and account["status"] != "ACTIVE":
            raise_error("ERR_ACCOUNT_NOT_ACTIVE")
        contract["status"] = "ACTIVE"
        store.touch(contract)
        if account is not None:
            projections.recompute_billing_mode(account)
    elif target == "SUSPENDED" and contract["status"] == "ACTIVE":
        contract["status"] = "SUSPENDED"
        store.touch(contract)
        if account is not None:
            projections.recompute_billing_mode(account)
    elif target == "EXPIRED" and contract["status"] in ("ACTIVE", "SUSPENDED"):
        contract["status"] = "EXPIRED"
        store.touch(contract)
        if account is not None:
            projections.recompute_billing_mode(account)
    else:
        raise_error("ERR_INVALID_REQUEST",
                    "A contract in %s cannot move to %s." % (contract["status"], target))
    return object_response(serializers.contract(contract))


# --------------------------------------------------------------------- beer lines

@bp.post(API_PREFIX + "/beer-lines")
@guard(ROLE_DISPATCH)
def create_beer_line():
    body = parse_body([
        F("account_id", "id", required=True),
        F("line_number", "int", required=True, min_value=1),
        F("run_length_feet", "num", required=True, gt=0),
        F("vertical_rise_feet", "num", required=True, ge=0),
        F("inner_diameter_inches", "num", required=True, allowed=BORES),
        F("beer_style_group", "enum", required=True, values=BEER_STYLE_GROUPS),
        F("average_daily_throughput_liters", "num", required=True, ge=0),
    ])
    account = resolve_body("account_id", body["account_id"])
    if account["status"] != "ACTIVE":
        raise_error("ERR_ACCOUNT_NOT_ACTIVE")
    contract = store.active_contract(account["id"])
    if contract is None:
        raise_error("ERR_NO_ACTIVE_CONTRACT")
    existing = store.account_lines(account["id"])
    if any(l["line_number"] == body["line_number"] for l in existing):
        raise_error("ERR_DUPLICATE_LINE_NUMBER")
    if len(existing) + 1 > contract["contracted_line_count"]:
        raise_error("ERR_CONTRACT_LINE_LIMIT_EXCEEDED")
    line = store.new_row({
        "account_id": account["id"],
        "line_number": body["line_number"],
        "run_length_feet": body["run_length_feet"],
        "vertical_rise_feet": body["vertical_rise_feet"],
        "inner_diameter_inches": body["inner_diameter_inches"],
        "beer_style_group": body["beer_style_group"],
        "average_daily_throughput_liters": body["average_daily_throughput_liters"],
        "status": "IN_SERVICE",
        "compliance_grade_flag": "COMPLIANT",
        "last_chemical_type": "NONE",
        "last_cleaned_at": None,
    })
    store.lines[line["id"]] = line
    projections.recompute_account_counters(account)
    return object_response(serializers.beer_line(line), 201)


@bp.get(API_PREFIX + "/beer-lines/<line_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_beer_line(line_id):
    return object_response(serializers.beer_line(resolve_path("line_id", line_id)))


@bp.get(API_PREFIX + "/beer-lines")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_beer_lines():
    account_id = query_str("account_id")
    status = query_enum("status", LINE_STATUSES)
    compliance_flag = query_enum("compliance_flag", COMPLIANCE_FLAGS)
    rows = []
    for row in store.lines.values():
        if not match(row, "account_id", account_id):
            continue
        if not match(row, "status", status):
            continue
        if compliance_flag is not None and projections.line_compliance_flag(row) != compliance_flag:
            continue
        rows.append(row)
    return listing(rows, serializers.beer_line)


@bp.post(API_PREFIX + "/beer-lines/<line_id>/return-to-service")
@guard(ROLE_AUDITOR)
def return_line_to_service(line_id):
    line = resolve_path("line_id", line_id)
    parse_body([])
    if line["status"] != "OUT_OF_SERVICE":
        raise_error("ERR_INVALID_REQUEST", "The line is not out of service.")
    newest = projections.newest_posted_cycle(line["id"])
    if newest is not None and newest["compliance_result"] != "PASS":
        raise_error("ERR_LINE_STILL_NON_COMPLIANT")
    line["status"] = "IN_SERVICE"
    line["compliance_grade_flag"] = "COMPLIANT"
    store.touch(line)
    account = store.accounts.get(line["account_id"])
    if account is not None:
        projections.recompute_account_counters(account)
    return object_response(serializers.beer_line(line))
