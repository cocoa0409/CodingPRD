"""Revenue distribution and owner disbursements (PRD 3.8)."""
from flask import Blueprint

from calc import (DAY_BASIS, STATUTORY_INTEREST_ANNUAL_PCT,
                  SUSPENSE_INTEREST_ANNUAL_PCT, db, get_disbursement,
                  get_revenue, get_well, guard_terminal,
                  recompute_suspense_balance, revenue_disbursements,
                  severance_rate, statutory_due_date, well_allocations,
                  well_interests, well_revenues)
from common import (ZERO6, add_days, dec, month_last_day, now_ts, ok, ok_list,
                    q6, rhu, today, touch)
from errors import fail
from store import by_created, insert, order_key, out_disbursement, out_revenue, rows
from validate import (READ_ALL, ROLE_COMPLIANCE, ROLE_JIA, acting_user,
                      authenticate, authorize, body, filt, is_partner,
                      pagination, present, require, v_cents, v_date, v_enum,
                      v_month, v_number, window)

bp = Blueprint("revenues", __name__)

INTEREST_BASES = ("FROM_DUE_DATE", "FROM_PROCEEDS_RECEIPT")


@bp.route("/wells/<well_id>/production-revenues", methods=["POST"])
def book_revenue(well_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["production_month", "gross_revenue_cents", "volume_units",
                   "sale_date"])
    production_month = v_month(data, "production_month")
    gross_revenue_cents = v_cents(data, "gross_revenue_cents", strictly_positive=True)
    volume_units = v_number(data, "volume_units", strictly_positive=True, places=6)
    sale_date = v_date(data, "sale_date")

    well = get_well(well_id)
    guard_terminal("well", well)
    if well["well_status"] not in ("PRODUCING", "SHUT_IN"):
        fail("ERR_WELL_NOT_PRODUCING")
    for existing in well_revenues(well["id"]):
        if existing["production_month"] == production_month:
            fail("ERR_DUPLICATE_PRODUCTION_MONTH")

    revenue = insert("revenues", {
        "well_id": well["id"],
        "production_month": production_month,
        "gross_revenue_cents": gross_revenue_cents,
        "volume_units": volume_units,
        "sale_date": sale_date,
        "severance_tax_cents": 0,
        "net_proceeds_cents": 0,
        "total_royalty_cents": 0,
        "total_disbursed_cents": 0,
        "statutory_due_date": statutory_due_date(production_month,
                                                 well["product_type"]),
        "released_at": None,
        "distribution_status": "ACCRUED",
    })
    return ok(out_revenue(revenue), 201)


@bp.route("/production-revenues", methods=["GET"])
def list_revenues():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("revenues")
    for name in ("well_id", "distribution_status", "production_month"):
        value = filt(name)
        if value is not None:
            found = [r for r in found if r[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_revenue(r) for r in page], limit, offset, total)


@bp.route("/production-revenues/<revenue_id>", methods=["GET"])
def read_revenue(revenue_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_revenue(get_revenue(revenue_id)))


@bp.route("/production-revenues/<revenue_id>/release", methods=["POST"])
def release_revenue(revenue_id):
    authenticate()
    authorize(ROLE_JIA)
    revenue = get_revenue(revenue_id)
    well = db.wells[revenue["well_id"]]

    if revenue["distribution_status"] != "ACCRUED":
        fail("ERR_REVENUE_NOT_ACCRUED")
    if well["pooling_status"] != "POOLED_EFFECTIVE":
        fail("ERR_WELL_NOT_POOLED")
    if well["allocation_factor_total"] != dec("1.000000"):
        fail("ERR_WELL_NOT_POOLED")
    allocations = well_allocations(well["id"], committed_only=True)
    positions = well_interests(well["id"], "ACTIVE")
    if not positions:
        fail("ERR_NOT_AN_INTEREST_HOLDER")

    gross = revenue["gross_revenue_cents"]

    # Tier 1: severance tax and the lease-pool split.
    tax = rhu(dec(gross) * severance_rate(well["product_type"]))
    net_proceeds = gross - tax
    lease_pool = {}
    for alloc in allocations:
        lease_pool[alloc["id"]] = rhu(dec(net_proceeds) * dec(alloc["allocation_factor"]))
    residual = net_proceeds - sum(lease_pool.values())
    if allocations and residual != 0:
        target = sorted(allocations,
                        key=lambda a: (-a["allocation_factor"], order_key(a)))[0]
        lease_pool[target["id"]] += residual

    # Tier 2: lessor royalty off each lease pool.
    royalty = {}
    for alloc in allocations:
        lease = db.leases[alloc["lease_id"]]
        royalty[alloc["id"]] = rhu(dec(lease_pool[alloc["id"]])
                                   * dec(lease["royalty_rate"]))
    total_royalty = sum(royalty.values())
    wi_pool = dict((a["id"], lease_pool[a["id"]] - royalty[a["id"]])
                   for a in allocations)

    # Tier 3: normalized net revenue interest, per lease pool.
    nri_denominator = sum((dec(p["net_revenue_interest_pct"]) for p in positions),
                          dec(0))
    normalized = {}
    for position in positions:
        if nri_denominator > 0:
            normalized[position["id"]] = q6(dec(position["net_revenue_interest_pct"])
                                            / nri_denominator)
        else:
            normalized[position["id"]] = ZERO6
    nri_target = sorted(positions,
                        key=lambda p: (-p["net_revenue_interest_pct"],
                                       order_key(p)))[0]
    residual = dec("1.000000") - sum(normalized.values(), dec(0))
    if residual != 0:
        normalized[nri_target["id"]] = q6(normalized[nri_target["id"]] + residual)

    gross_share = {}
    for alloc in allocations:
        for position in positions:
            gross_share[(alloc["id"], position["id"])] = rhu(
                dec(wi_pool[alloc["id"]]) * dec(normalized[position["id"]]))
        assigned = sum(gross_share[(alloc["id"], p["id"])] for p in positions)
        leftover = wi_pool[alloc["id"]] - assigned
        if leftover != 0:
            gross_share[(alloc["id"], nri_target["id"])] += leftover

    # Tier 4: non-consent recovery withheld progressively.
    balances = dict((p["id"], max(0, p["non_consent_recoverable_balance_cents"]))
                    for p in positions)
    total_disbursed = 0
    affected_owners = []
    for alloc in allocations:
        for position in positions:
            share = gross_share[(alloc["id"], position["id"])]
            withheld = min(share, balances[position["id"]])
            if withheld < 0:
                withheld = 0
            balances[position["id"]] -= withheld
            net_amount = share - withheld
            total_disbursed += share
            owner = db.owners[position["owner_id"]]
            status = "ACCRUED"
            reason = None
            if not owner["tax_id_on_file"]:
                status = "SUSPENDED"
                reason = "MISSING_TAX_ID"
            elif net_amount == 0 and withheld > 0:
                status = "SUSPENDED"
                reason = "NON_CONSENT_RECOVERY"
            insert("disbursements", {
                "revenue_id": revenue["id"],
                "owner_id": owner["id"],
                "lease_id": alloc["lease_id"],
                "gross_share_cents": share,
                "withheld_recovery_cents": withheld,
                "net_amount_cents": net_amount,
                "late_interest_cents": 0,
                "interest_basis": None,
                "paid_at": None,
                "suspense_reason": reason,
                "disbursement_status": status,
                "_ever_missing_tax_id": reason == "MISSING_TAX_ID",
            })
            if owner["id"] not in affected_owners:
                affected_owners.append(owner["id"])

    for position in positions:
        if balances[position["id"]] != position["non_consent_recoverable_balance_cents"]:
            position["non_consent_recoverable_balance_cents"] = balances[position["id"]]
            touch(position)

    revenue["severance_tax_cents"] = tax
    revenue["net_proceeds_cents"] = net_proceeds
    revenue["total_royalty_cents"] = total_royalty
    revenue["total_disbursed_cents"] = total_disbursed
    revenue["released_at"] = now_ts()
    revenue["distribution_status"] = "RELEASED"
    touch(revenue)

    for owner_id in affected_owners:
        recompute_suspense_balance(db.owners[owner_id])
    return ok(out_revenue(revenue))


@bp.route("/owner-disbursements", methods=["GET"])
def list_disbursements():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("disbursements")
    owner_filter = filt("owner_id")
    if is_partner():
        me = acting_user()
        if owner_filter is not None and owner_filter != me:
            fail("ERR_OWNER_MISMATCH")
        owner_filter = me
    if owner_filter is not None:
        found = [d for d in found if d["owner_id"] == owner_filter]
    for name in ("revenue_id", "lease_id", "disbursement_status", "suspense_reason"):
        value = filt(name)
        if value is not None:
            found = [d for d in found if d[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_disbursement(d) for d in page], limit, offset, total)


@bp.route("/owner-disbursements/<disbursement_id>", methods=["GET"])
def read_disbursement(disbursement_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_disbursement(get_disbursement(disbursement_id)))


@bp.route("/owner-disbursements/<disbursement_id>/suspense-release", methods=["POST"])
def release_suspense(disbursement_id):
    authenticate()
    authorize(ROLE_COMPLIANCE)
    disb = get_disbursement(disbursement_id)
    if disb["disbursement_status"] != "SUSPENDED":
        fail("ERR_DISBURSEMENT_NOT_PAYABLE")
    disb["disbursement_status"] = "ACCRUED"
    disb["suspense_reason"] = None
    touch(disb)
    owner = db.owners.get(disb["owner_id"])
    if owner is not None:
        recompute_suspense_balance(owner)
    return ok(out_disbursement(disb))


@bp.route("/owner-disbursements/<disbursement_id>/payment", methods=["POST"])
def pay_disbursement(disbursement_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    basis = None
    if present(data, "interest_basis"):
        basis = v_enum(data, "interest_basis", INTEREST_BASES)

    disb = get_disbursement(disbursement_id)
    if disb["disbursement_status"] != "ACCRUED":
        fail("ERR_DISBURSEMENT_NOT_PAYABLE")
    if disb["net_amount_cents"] <= 0:
        fail("ERR_DISBURSEMENT_NOT_PAYABLE")
    revenue = db.revenues[disb["revenue_id"]]
    if revenue["released_at"] is None:
        fail("ERR_PAYMENT_BEFORE_RELEASE")
    paid_on = today()
    if revenue["released_at"].date() > paid_on:
        fail("ERR_PAYMENT_BEFORE_RELEASE")

    if basis is None:
        basis = ("FROM_PROCEEDS_RECEIPT" if disb.get("_ever_missing_tax_id")
                 else "FROM_DUE_DATE")
    if basis == "FROM_DUE_DATE":
        start = revenue["statutory_due_date"]
        annual = STATUTORY_INTEREST_ANNUAL_PCT
    else:
        year = int(revenue["production_month"][0:4])
        month = int(revenue["production_month"][5:7])
        start = add_days(month_last_day(year, month), 1)
        annual = SUSPENSE_INTEREST_ANNUAL_PCT
    days = (paid_on - start).days
    if days < 0:
        days = 0
    interest = rhu(dec(disb["net_amount_cents"]) * annual * dec(days) / DAY_BASIS)

    disb["late_interest_cents"] = interest
    disb["interest_basis"] = basis
    disb["paid_at"] = now_ts()
    disb["disbursement_status"] = "PAID"
    touch(disb)
    return ok(out_disbursement(disb))
