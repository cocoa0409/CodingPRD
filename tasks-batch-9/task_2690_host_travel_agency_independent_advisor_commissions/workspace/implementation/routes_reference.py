"""The logical clock and the reference data: split schedules, consortiums and
suppliers (PRD 3.1, 2.5)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import (authenticate, entry_int, entry_number, field_dt, field_enum,
                    field_int, field_list, field_number, field_object_keys,
                    field_str, read_body, _bad)
from listing import list_response
from lookup import get_consortium, get_supplier
from store import fmt_ts, new_row, ordered, serialize, store, touch

bp = Blueprint("reference", __name__)

ALL_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor",
             "SupplierPortal")
OPERATOR_ROLES = ("HostOperations", "HostController", "ComplianceOfficer")


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(OPERATOR_ROLES)
    body = read_body(("to_iso8601",))
    target = field_dt(body, "to_iso8601")

    if target < store.clock:
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN")

    store.clock = target

    expired = 0
    for credential in ordered(store.credentials.values()):
        if credential["status"] != "VERIFIED":
            continue
        if credential["expires_on"] > store.clock:
            continue
        credential["status"] = "EXPIRED"
        touch(credential)
        expired += 1
        if credential["credential_type"] == "EO_POLICY":
            advisor = store.advisors.get(credential["advisor_id"])
            if advisor is not None:
                calc.recompute_eo_coverage(advisor)

    refreshed = 0
    for claim in ordered(store.claims.values()):
        if claim["status"] not in ("SUBMITTED", "DENIED"):
            continue
        calc.refresh_claim_aging(claim)
        refreshed += 1

    for supplier in ordered(store.suppliers.values()):
        calc.recompute_supplier_aging(supplier)

    return ok({
        "current_utc": fmt_ts(store.clock),
        "expired_credential_count": expired,
        "refreshed_claim_count": refreshed,
    })


# --------------------------------------------------------------------------
# split schedules
# --------------------------------------------------------------------------

def _read_production_ladder(body):
    raw = field_list(body, "tiers")
    if not raw:
        _bad("tiers must carry at least one entry.")
    entries = []
    for obj in raw:
        field_object_keys(obj, "tiers",
                          ("tier_level", "min_production_cents", "advisor_pct"))
        entries.append({
            "tier_level": entry_int(obj, "tiers", "tier_level", minimum=1),
            "min_production_cents": entry_int(obj, "tiers", "min_production_cents",
                                              minimum=0),
            "advisor_pct": entry_number(obj, "tiers", "advisor_pct", minimum=0,
                                        maximum=1, exclusive_min=True),
        })
    levels = sorted(entry["tier_level"] for entry in entries)
    if levels != list(range(1, len(entries) + 1)):
        _bad("tier_level values must run from 1 upward with no gaps.")
    zero_floors = [e for e in entries if e["min_production_cents"] == 0]
    if len(zero_floors) != 1:
        _bad("Exactly one tier must sit at a min_production_cents of 0.")
    previous = None
    for entry in sorted(entries, key=lambda e: e["tier_level"]):
        if previous is not None and entry["min_production_cents"] <= previous:
            _bad("min_production_cents must increase strictly with tier_level.")
        previous = entry["min_production_cents"]
    return sorted(entries, key=lambda e: e["min_production_cents"])


def _read_fee_ladder(body):
    raw = field_list(body, "platform_fee_tiers")
    if not raw:
        _bad("platform_fee_tiers must carry at least one entry.")
    entries = []
    for obj in raw:
        field_object_keys(obj, "platform_fee_tiers", ("min_share_cents", "fee_pct"))
        entries.append({
            "min_share_cents": entry_int(obj, "platform_fee_tiers",
                                         "min_share_cents", minimum=0),
            "fee_pct": entry_number(obj, "platform_fee_tiers", "fee_pct",
                                    minimum=0, maximum=1, exclusive_max=True),
        })
    zero_floors = [e for e in entries if e["min_share_cents"] == 0]
    if len(zero_floors) != 1:
        _bad("Exactly one platform fee tier must sit at a min_share_cents of 0.")
    entries = sorted(entries, key=lambda e: e["min_share_cents"])
    previous = None
    for entry in entries:
        if previous is not None and entry["min_share_cents"] <= previous:
            _bad("min_share_cents must increase strictly.")
        previous = entry["min_share_cents"]
    return entries


@bp.post("/split-schedules")
def create_split_schedule():
    authenticate(("HostOperations",))
    body = read_body(("name", "tiers", "platform_fee_tiers",
                      "chargeback_retention_pct"))
    name = field_str(body, "name", max_len=200)
    tiers = _read_production_ladder(body)
    fee_tiers = _read_fee_ladder(body)
    retention = field_number(body, "chargeback_retention_pct", required=False,
                             default=0.10, minimum=0, maximum=1,
                             exclusive_max=True)

    row = new_row({
        "name": name,
        "tiers": tiers,
        "platform_fee_tiers": fee_tiers,
        "chargeback_retention_pct": retention,
    })
    store.split_schedules[row["id"]] = row
    return created(serialize(row))


# --------------------------------------------------------------------------
# consortiums
# --------------------------------------------------------------------------

@bp.post("/consortiums")
def create_consortium():
    authenticate(("HostOperations",))
    body = read_body(("name", "membership_fee_cents", "marketing_fund_accrual_pct",
                      "consortium_channel_bonus_pct"))
    name = field_str(body, "name", max_len=200)
    fee = field_int(body, "membership_fee_cents", minimum=0)
    accrual = field_number(body, "marketing_fund_accrual_pct", minimum=0,
                           maximum=1, exclusive_max=True)
    bonus = field_number(body, "consortium_channel_bonus_pct", minimum=0,
                         maximum=1, exclusive_max=True)

    row = new_row({
        "name": name,
        "membership_fee_cents": fee,
        "marketing_fund_accrual_pct": accrual,
        "consortium_channel_bonus_pct": bonus,
        "marketing_fund_balance_cents": 0,
    })
    store.consortiums[row["id"]] = row
    return created(serialize(row))


# --------------------------------------------------------------------------
# suppliers
# --------------------------------------------------------------------------

ACCREDITATION_SCHEMES = ("IATA", "CLIA", "ARC", "TIDS")


@bp.post("/suppliers")
def create_supplier():
    authenticate(("HostOperations",))
    body = read_body(("name", "accreditation_scheme", "base_commission_pct",
                      "preferred_override_commission_pct", "rate_ceiling_pct",
                      "max_commission_per_booking_cents", "remit_terms_days",
                      "consortium_id", "program_status",
                      "probation_chargeback_threshold"))
    name = field_str(body, "name", max_len=200)
    scheme = field_enum(body, "accreditation_scheme", ACCREDITATION_SCHEMES)
    base_pct = field_number(body, "base_commission_pct", minimum=0, maximum=1,
                            exclusive_min=True, exclusive_max=True)
    override_pct = field_number(body, "preferred_override_commission_pct",
                                minimum=0, maximum=1, exclusive_min=True,
                                exclusive_max=True)
    ceiling_pct = field_number(body, "rate_ceiling_pct", minimum=0, maximum=1,
                               exclusive_min=True)
    max_commission = field_int(body, "max_commission_per_booking_cents", minimum=1)
    remit_terms = field_int(body, "remit_terms_days", minimum=0)
    consortium_id = field_str(body, "consortium_id", required=False)
    # PROBATION is reachable only through the chargeback cascade (PRD 3.1).
    program_status = field_enum(body, "program_status", ("STANDARD", "PREFERRED"),
                                required=False, default="STANDARD")
    threshold = field_int(body, "probation_chargeback_threshold", required=False,
                          default=2, minimum=1)

    if consortium_id is not None:
        get_consortium(consortium_id)

    row = new_row({
        "name": name,
        "accreditation_scheme": scheme,
        "consortium_id": consortium_id,
        "program_status": program_status,
        "base_commission_pct": base_pct,
        "preferred_override_commission_pct": override_pct,
        "rate_ceiling_pct": ceiling_pct,
        "max_commission_per_booking_cents": max_commission,
        "remit_terms_days": remit_terms,
        "probation_chargeback_threshold": threshold,
        "chargeback_count": 0,
        "aging_0_30_cents": 0,
        "aging_31_60_cents": 0,
        "aging_61_90_cents": 0,
        "aging_over_90_cents": 0,
        "total_outstanding_cents": 0,
    })
    store.suppliers[row["id"]] = row
    return created(serialize(row))


@bp.get("/suppliers/<supplier_id>")
def read_supplier(supplier_id):
    authenticate(ALL_ROLES)
    supplier = get_supplier(supplier_id)
    calc.recompute_supplier_aging(supplier)
    return ok(serialize(supplier))


@bp.get("/suppliers")
def list_suppliers():
    authenticate(ALL_ROLES)
    for supplier in store.suppliers.values():
        calc.recompute_supplier_aging(supplier)
    return list_response(store.suppliers.values(),
                         (("consortium_id", "consortium_id"),
                          ("program_status", "program_status"),
                          ("accreditation_scheme", "accreditation_scheme")))
