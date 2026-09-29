"""Percentage rent and transfer consent: filing, assessment, pricing, payment."""

from flask import Blueprint

import auth
import calc
import cascades
import serialize
import store
import validate as v
from errors import ApiError
from response import object_response

bp = Blueprint("money", __name__)

CREDIT_RATINGS = {"AAA", "A", "BBB", "SPECULATIVE"}
TRANSFER_TYPES = {"ASSIGNMENT", "SUBLEASE"}


def _subleases_in_period(lease_id, period_start, period_end, statuses):
    """Inclusion set: SUBLEASE rows whose term overlaps the statement period."""
    rows = []
    for row in store.transfers.values():
        if row["lease_id"] != lease_id or row["transfer_type"] != "SUBLEASE":
            continue
        if row["status"] not in statuses:
            continue
        if cascades.closed_overlaps(row["term_start"], row["term_end"],
                                    period_start, period_end):
            rows.append(row)
    return store.sort_rows(rows)


# ===========================================================================
# Statement filing
# ===========================================================================
@bp.post("/percentage-rent-statements")
def file_statement():
    payload = v.body()
    lease = None
    if v.fk_present(payload, "lease_id"):
        lease = cascades.fetch("lease", v.fk_value(payload, "lease_id"))

    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)

    lease_id = v.req_str(payload, "lease_id")
    period_start = v.req_dt(payload, "period_start")
    period_end = v.req_dt(payload, "period_end")
    reported = v.req_money(payload, "reported_gross_sales_cents")
    expected_version = v.req_int(payload, "expected_lease_version")

    if expected_version != lease["version"]:
        raise ApiError(
            "ERR_STALE_LEASE_VERSION",
            "expected_lease_version %d does not match the lease version %d."
            % (expected_version, lease["version"]),
        )

    cascades.require_operative(lease)

    superseded = None
    for row in store.by_lease(store.statements, lease_id):
        if row["status"] == "VOID":
            continue
        if (row["period_start"] == period_start
                and row["period_end"] == period_end):
            # An exact period match is a supersession, deliberately accepted.
            superseded = row
            continue
        if cascades.overlaps(period_start, period_end,
                             row["period_start"], row["period_end"]):
            raise ApiError("ERR_INTERVAL_OVERLAP",
                           "The period intersects another live statement on "
                           "this lease.")

    if not period_start < period_end:
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "period_start must be strictly before period_end.")
    if period_end > store.now():
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "period_end may not be after the current logical "
                       "instant; the period has not closed.")

    if superseded is not None and superseded["status"] == "SUBMITTED":
        superseded["status"] = "VOID"
        store.touch(superseded)

    record = {
        "lease_id": lease_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_gross_sales_cents": reported,
        "audited_gross_sales_cents": None,
        "status": "SUBMITTED",
        "included_sublease_rent_cents": None,
        "gross_percentage_rent_cents": None,
        "base_rent_offset_credit_cents": calc.base_rent_offset_credit(
            lease["current_annual_base_rent_cents"]),
        "amount_due_cents": None,
        "underreport_penalty_cents": None,
        "assessment_variant": None,
    }
    store.stamp(record)
    store.statements[record["id"]] = record

    store.touch(lease)
    return object_response(serialize.statement(record), 201)


@bp.post("/percentage-rent-statements/<statement_id>/assess")
def assess_statement(statement_id):
    statement = cascades.fetch("statement", statement_id)
    auth.require({"LeaseAccountant"})
    lease = store.leases.get(statement["lease_id"])

    if statement["status"] != "SUBMITTED":
        raise cascades.invalid_state(
            "The statement is in %s and cannot be assessed provisionally."
            % statement["status"]
        )
    if lease is None or lease["lease_status"] not in ("ACTIVE", "IN_DEFAULT"):
        raise cascades.invalid_state(
            "Provisional assessment requires the lease tenancy axis to be "
            "ACTIVE or IN_DEFAULT."
        )

    rows = _subleases_in_period(lease["id"], statement["period_start"],
                               statement["period_end"], ("ACTIVE",))
    included = calc.sublease_inclusion_base(rows)
    gross, credit, amount_due = calc.percentage_rent_due(
        statement["reported_gross_sales_cents"], included,
        lease["percentage_rent_breakpoint_cents"],
        lease["percentage_rent_rate_bps"],
        lease["current_annual_base_rent_cents"],
    )

    statement["included_sublease_rent_cents"] = included
    statement["gross_percentage_rent_cents"] = gross
    statement["base_rent_offset_credit_cents"] = credit
    statement["amount_due_cents"] = amount_due
    statement["assessment_variant"] = "PROVISIONAL"
    statement["status"] = "PROVISIONAL_ASSESSED"
    store.touch(statement)

    lease["arrears_balance_cents"] = lease["arrears_balance_cents"] + amount_due
    store.touch(lease)
    return object_response(serialize.statement(statement), 200)


@bp.post("/percentage-rent-statements/<statement_id>/audit")
def audit_statement(statement_id):
    statement = cascades.fetch("statement", statement_id)
    auth.require({"LeaseAccountant"})
    payload = v.body()
    audited = v.req_money(payload, "audited_gross_sales_cents")
    lease = store.leases.get(statement["lease_id"])

    if statement["status"] != "PROVISIONAL_ASSESSED":
        raise cascades.invalid_state(
            "The statement is in %s and cannot be audited."
            % statement["status"]
        )

    rows = _subleases_in_period(lease["id"], statement["period_start"],
                               statement["period_end"],
                               ("ACTIVE", "CONSENT_GRANTED"))
    included = calc.sublease_inclusion_base(rows)
    gross, credit, amount_due = calc.percentage_rent_due(
        audited, included,
        lease["percentage_rent_breakpoint_cents"],
        lease["percentage_rent_rate_bps"],
        lease["current_annual_base_rent_cents"],
    )
    penalty = calc.underreport_penalty(
        statement["reported_gross_sales_cents"], audited,
        lease["percentage_rent_rate_bps"],
    )
    previously_posted = statement.get("amount_due_cents") or 0

    statement["audited_gross_sales_cents"] = audited
    statement["included_sublease_rent_cents"] = included
    statement["gross_percentage_rent_cents"] = gross
    statement["base_rent_offset_credit_cents"] = credit
    statement["amount_due_cents"] = amount_due
    statement["underreport_penalty_cents"] = penalty
    statement["assessment_variant"] = "AUDITED_FINAL"
    statement["status"] = "FINAL_ASSESSED"
    store.touch(statement)

    # A reconciliation, not a second charge.
    net = amount_due - previously_posted + penalty
    lease["arrears_balance_cents"] = lease["arrears_balance_cents"] + net
    store.touch(lease)
    return object_response(serialize.statement(statement), 200)


# ===========================================================================
# Transfer consent
# ===========================================================================
def _activate_transfer(transfer, lease):
    transfer["status"] = "ACTIVE"
    store.touch(transfer)
    if transfer["transfer_type"] == "ASSIGNMENT":
        lease["lessee_id"] = transfer["transferee_lessee_id"]
    else:
        cascades.recompute_sublease_base(lease)
    store.touch(lease)


@bp.post("/transfer-requests")
def create_transfer():
    payload = v.body()
    lease = None
    parent = None
    if v.fk_present(payload, "lease_id"):
        lease = cascades.fetch("lease", v.fk_value(payload, "lease_id"))
    if v.fk_present(payload, "parent_transfer_id"):
        parent = cascades.fetch("transfer",
                                v.fk_value(payload, "parent_transfer_id"))
    if v.fk_present(payload, "transferee_lessee_id"):
        cascades.fetch("lessee", v.fk_value(payload, "transferee_lessee_id"))

    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)

    lease_id = v.req_str(payload, "lease_id")
    transfer_type = v.req_enum(payload, "transfer_type", TRANSFER_TYPES)
    transferee_legal_name = v.req_str(payload, "transferee_legal_name")
    term_start = v.req_dt(payload, "term_start")
    term_end = v.req_dt(payload, "term_end")
    credit_rating = v.opt_enum(payload, "transferee_credit_rating_code",
                               CREDIT_RATINGS, "BBB")
    consent_deposit = v.opt_money(payload, "consent_deposit_cents", 0)
    transferee_lessee_id = v.opt_str(payload, "transferee_lessee_id")
    net_consideration = v.opt_money(payload, "net_consideration_cents")
    premises_unit_code = v.opt_str(payload, "premises_unit_code")
    annual_sublease_rent = v.opt_money(payload, "annual_sublease_rent_cents")
    sublet_area = v.opt_area(payload, "sublet_area_sqft")

    if transfer_type == "ASSIGNMENT":
        missing = [name for name, value in
                   (("transferee_lessee_id", transferee_lessee_id),
                    ("net_consideration_cents", net_consideration))
                   if value is None]
    else:
        missing = [name for name, value in
                   (("premises_unit_code", premises_unit_code),
                    ("annual_sublease_rent_cents", annual_sublease_rent),
                    ("sublet_area_sqft", sublet_area))
                   if value is None]
    if missing:
        raise ApiError(
            "ERR_TRANSFER_FIELDS_MISMATCHED",
            "A %s requires %s." % (transfer_type, ", ".join(missing)),
        )

    if transfer_type == "SUBLEASE":
        # §2.8 priority 5: "one `premises_unit_code` among a lease's active
        # subleases". A unit is only "already taken" for a term that actually
        # collides: §2.9 fixes the turnover buffer between successive subleases
        # of one unit at zero days, so "back-to-back subleases of the same unit
        # are permitted with no gap" and half-open terms that merely touch do
        # not occupy the unit at the same time.
        for row in store.by_lease(store.transfers, lease_id):
            if (row["transfer_type"] == "SUBLEASE"
                    and row["status"] == "ACTIVE"
                    and row["premises_unit_code"] == premises_unit_code
                    and cascades.overlaps(term_start, term_end,
                                          row["term_start"], row["term_end"])):
                raise ApiError(
                    "ERR_DUPLICATE_RECORD",
                    "That premises_unit_code is already taken by an active "
                    "sublease of this lease.",
                )

    cascades.require_operative(lease)

    if transfer_type == "SUBLEASE":
        for row in store.by_lease(store.transfers, lease_id):
            if (row["transfer_type"] != "SUBLEASE"
                    or row["premises_unit_code"] != premises_unit_code):
                continue
            if row["status"] not in ("SUBMITTED", "CONSENT_GRANTED", "ACTIVE"):
                continue
            if cascades.overlaps(term_start, term_end,
                                 row["term_start"], row["term_end"]):
                raise ApiError(
                    "ERR_INTERVAL_OVERLAP",
                    "The proposed term intersects another sublease of the "
                    "same unit on this lease.",
                )

    if not term_start < term_end:
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "term_start must be strictly before term_end.")
    if transfer_type == "SUBLEASE":
        if (term_start < lease["commencement_date"]
                or term_end > lease["expiration_date"]):
            raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                           "A sublease term must sit inside the lease term.")

    tier_depth = 1 if parent is None else (parent.get("tier_depth") or 1) + 1

    record = {
        "lease_id": lease_id,
        "parent_transfer_id": parent["id"] if parent is not None else None,
        "transfer_type": transfer_type,
        "transferee_legal_name": transferee_legal_name,
        "transferee_lessee_id": transferee_lessee_id,
        "transferee_credit_rating_code": credit_rating,
        "premises_unit_code": premises_unit_code,
        "term_start": term_start,
        "term_end": term_end,
        "annual_sublease_rent_cents": annual_sublease_rent,
        "sublet_area_sqft": sublet_area,
        "net_consideration_cents": net_consideration,
        "consent_deposit_cents": consent_deposit,
        # Derived once at application and never re-derived.
        "submitted_late": store.now() > term_start,
        "tier_depth": tier_depth,
        "allocable_base_rent_cents": None,
        "transfer_fee_gross_cents": None,
        "admin_charge_cents": None,
        "late_surcharge_cents": None,
        "total_transfer_fee_cents": None,
        "transfer_fee_paid_cents": 0,
        "status": "SUBMITTED",
    }
    store.stamp(record)
    store.transfers[record["id"]] = record
    return object_response(serialize.transfer(record), 201)


@bp.post("/transfer-requests/<transfer_id>/decision")
def decide_transfer(transfer_id):
    transfer = cascades.fetch("transfer", transfer_id)
    auth.require({"AssetManager"})
    payload = v.body()
    decision = v.req_enum(payload, "decision", {"APPROVE", "DENY"})
    v.opt_str(payload, "denial_reason_code", default=None)
    lease = store.leases.get(transfer["lease_id"])

    if transfer["status"] != "SUBMITTED":
        raise cascades.invalid_state(
            "The transfer request is in %s and cannot be decided."
            % transfer["status"]
        )

    if decision == "DENY":
        # No fee is assessed and the consent deposit is not credited anywhere.
        transfer["status"] = "CONSENT_DENIED"
        store.touch(transfer)
        return object_response(serialize.transfer(transfer), 200)

    if lease is None or lease["lease_status"] != "ACTIVE":
        raise cascades.invalid_state(
            "Consent requires the lease tenancy axis to be exactly ACTIVE."
        )
    if (transfer.get("tier_depth") or 1) > calc.MAX_SUBLEASE_TIER_DEPTH:
        raise cascades.invalid_state(
            "The lease permits a maximum sublease tier depth of %d."
            % calc.MAX_SUBLEASE_TIER_DEPTH
        )

    if lease["rent_status"] == "IN_ARBITRATION":
        raise ApiError("ERR_CROSS_ENTITY_BLOCKED",
                       "A transfer may not be consented to while the lease "
                       "rent axis is IN_ARBITRATION.")

    if transfer["transferee_credit_rating_code"] == "SPECULATIVE":
        raise ApiError("ERR_CREDIT_RATING_REFUSED",
                       "A SPECULATIVE transferee is refused consent.")

    if transfer["transfer_type"] == "SUBLEASE":
        for row in store.by_lease(store.transfers, lease["id"]):
            if row["id"] == transfer["id"]:
                continue
            if (row["transfer_type"] != "SUBLEASE"
                    or row["premises_unit_code"] != transfer["premises_unit_code"]):
                continue
            if row["status"] not in ("CONSENT_GRANTED", "ACTIVE"):
                continue
            if cascades.overlaps(transfer["term_start"], transfer["term_end"],
                                 row["term_start"], row["term_end"]):
                raise ApiError(
                    "ERR_INTERVAL_OVERLAP",
                    "Another consented sublease already occupies that unit "
                    "over the proposed term.",
                )

        occupied = transfer.get("sublet_area_sqft") or 0
        for row in store.by_lease(store.transfers, lease["id"]):
            if row["id"] == transfer["id"]:
                continue
            if (row["transfer_type"] == "SUBLEASE"
                    and row["status"] in ("ACTIVE", "CONSENT_GRANTED")):
                occupied += row.get("sublet_area_sqft") or 0
        if occupied > lease["total_permitted_gfa_sqft"]:
            raise ApiError("ERR_SUBLET_AREA_EXCEEDED",
                           "The consented sublet area would exceed the "
                           "development envelope.")

    allocable, gross, admin, late, total = calc.price_transfer(transfer, lease)
    transfer["allocable_base_rent_cents"] = allocable
    transfer["transfer_fee_gross_cents"] = gross
    transfer["admin_charge_cents"] = admin
    transfer["late_surcharge_cents"] = late
    transfer["total_transfer_fee_cents"] = total
    transfer["transfer_fee_paid_cents"] = transfer["consent_deposit_cents"] or 0
    transfer["status"] = "CONSENT_GRANTED"
    store.touch(transfer)

    if transfer["transfer_fee_paid_cents"] >= total:
        # The deposit already covers the fee: continue straight to ACTIVE.
        _activate_transfer(transfer, lease)

    return object_response(serialize.transfer(transfer), 200)


@bp.post("/transfer-requests/<transfer_id>/fee-payments")
def pay_transfer_fee(transfer_id):
    transfer = cascades.fetch("transfer", transfer_id)
    lease = store.leases.get(transfer["lease_id"])
    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()
    amount = v.req_money(payload, "amount_cents")

    if transfer["status"] != "CONSENT_GRANTED":
        raise cascades.invalid_state(
            "The transfer request is in %s and takes no fee payment."
            % transfer["status"]
        )

    outstanding = ((transfer["total_transfer_fee_cents"] or 0)
                   - (transfer["transfer_fee_paid_cents"] or 0))
    if amount != outstanding:
        raise ApiError(
            "ERR_AMOUNT_NOT_RECONCILED",
            "amount_cents must equal the outstanding balance of %d cents "
            "exactly." % outstanding,
        )

    transfer["transfer_fee_paid_cents"] = (
        (transfer["transfer_fee_paid_cents"] or 0) + amount
    )
    _activate_transfer(transfer, lease)
    return object_response(serialize.transfer(transfer), 200)
