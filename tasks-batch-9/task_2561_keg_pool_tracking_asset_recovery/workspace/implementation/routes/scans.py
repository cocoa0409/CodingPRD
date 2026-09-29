"""The scan stream: custody projection, fill billing, misdelivery detection
and return incentives."""
from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("scans", __name__)

ALL_ROLES = ("PoolOperator", "Brewer", "Distributor", "ServiceTechnician",
             "AssetRecoveryAnalyst")
SCAN_POINTS = ("FILL", "DISTRIBUTION", "RETAIL", "RETURN")
PARTY_TYPES = ("BREWER", "DISTRIBUTOR", "RETAIL_ACCOUNT")
BRAND_CODE_PATTERN = r"^[A-Z0-9]{2,8}$"
KEG_TERMINAL = ("LOST", "STOLEN", "SCRAPPED")

# The closed loop of PRD 3.5: the only accepted movements.
TRANSITIONS = {
    "FILL": {"ISSUED_TO_BREWER": "FILLED"},
    "DISTRIBUTION": {"FILLED": "IN_TRADE"},
    "RETAIL": {"IN_TRADE": "AT_RETAIL"},
    "RETURN": {"IN_TRADE": "IN_SERVICE", "AT_RETAIL": "IN_SERVICE"},
}
# Which party type each scan point requires.
REQUIRED_PARTY = {
    "FILL": "BREWER",
    "DISTRIBUTION": "DISTRIBUTOR",
    "RETAIL": "RETAIL_ACCOUNT",
    "RETURN": "DISTRIBUTOR",
}
PARTY_FIELD = {
    "BREWER": "brewer_id",
    "DISTRIBUTOR": "distributor_id",
    "RETAIL_ACCOUNT": "retail_account_code",
}


@bp.post("/kegs/<keg_id>/scan")
def record_scan(keg_id):
    actor = middleware.authenticate("PoolOperator", "Brewer", "Distributor")
    payload = util.body()
    util.forbid_version_fields(payload)
    scan_point = util.req_enum(payload, "scan_point", SCAN_POINTS)
    party_type = util.req_enum(payload, "party_type", PARTY_TYPES)
    scanned_at = util.parse_instant(util.req_present(payload, "scanned_at"),
                                    "scanned_at")
    brand_code = util.req_string(payload, "brand_code_scanned", 2, 8,
                                 pattern=BRAND_CODE_PATTERN)
    # A party identifier the declared party_type forbids is a shape failure.
    for field in ("brewer_id", "distributor_id", "retail_account_code"):
        if field != PARTY_FIELD[party_type]:
            util.forbid(payload, field,
                        "is not accepted when party_type is %s" % party_type)
    brewer_id = util.opt_string(payload, "brewer_id")
    distributor_id = util.opt_string(payload, "distributor_id")
    retail_account_code = util.opt_string(payload, "retail_account_code", 1,
                                          120)

    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    if brewer_id is not None and brewer_id not in db.brewers:
        fail("ERR_BREWER_NOT_FOUND")
    if distributor_id is not None and distributor_id not in db.distributors:
        fail("ERR_DISTRIBUTOR_NOT_FOUND")

    # Step 8: the entity-backed actor owns the party side it supplied.
    if actor.role == "Brewer" and brewer_id is not None:
        middleware.owner_check(actor, brewer_id)
    if actor.role == "Distributor" and distributor_id is not None:
        middleware.owner_check(actor, distributor_id)

    brewer = db.brewers.get(brewer_id) if brewer_id else None
    distributor = db.distributors.get(distributor_id) if distributor_id \
        else None
    pool = db.pools.get(keg["pool_id"])
    agreement = None

    # Step 10: a fill is only billable under a dispatched order.
    if scan_point == "FILL":
        order = db.orders.get(keg["issuance_order_id"]) \
            if keg["issuance_order_id"] else None
        if order is None or order["status"] != "DISPATCHED":
            fail("ERR_INVALID_STATE",
                 "The keg's governing issuance order is not DISPATCHED.")
    # Step 11: a written-off keg accepts no further custody movement.
    if keg["custody_state"] in KEG_TERMINAL:
        fail("ERR_ALREADY_TERMINAL",
             "The keg's custody_state is %s." % keg["custody_state"])
    # Steps 12, 15 and 16 read the filling brewer, so they only run once the
    # brewer side of a fill is actually known.
    if scan_point == "FILL" and brewer is not None \
            and brewer_id == keg["current_brewer_id"]:
        agreement = recompute.active_agreement(brewer_id, keg["pool_id"])
        if agreement is None:
            fail("ERR_AGREEMENT_NOT_ACTIVE",
                 "No ACTIVE float agreement covers that brewer and pool.")
        if agreement["float_posture"] == "SUSPENDED":
            fail("ERR_FLOAT_SUSPENDED", "The agreement's float is SUSPENDED.")
        if brewer["status"] == "SUSPENDED":
            fail("ERR_BREWER_SUSPENDED", "The brewer's status is SUSPENDED.")
    # Step 17: the wholesaler taking or handing back custody is in good standing.
    if scan_point in ("DISTRIBUTION", "RETURN") and distributor is not None \
            and party_type == "DISTRIBUTOR":
        if distributor["status"] == "SUSPENDED":
            fail("ERR_DISTRIBUTOR_SUSPENDED",
                 "The distributor's status is SUSPENDED.")
    # Step 18: movement legality, judged here and nowhere else.
    target_state = TRANSITIONS[scan_point].get(keg["custody_state"])
    if target_state is None:
        fail("ERR_SCAN_SEQUENCE_INVALID",
             "A %s scan is not legal from custody_state %s."
             % (scan_point, keg["custody_state"]))
    if scan_point == "FILL":
        # Steps 20 and 21: only a certified keg may be filled.
        if keg["service_state"] != "SERVICE_OK":
            fail("ERR_KEG_NOT_FIT_FOR_FILL",
                 "The keg's service_state is %s." % keg["service_state"])
        if calc.certification_lapsed(keg):
            fail("ERR_PRESSURE_TEST_OVERDUE",
                 "The keg's pressure certification has lapsed.")
        # Step 27: the collar must be the filling brewer's own brand.
        if brewer is not None and brand_code != brewer["brand_code"]:
            fail("ERR_BRAND_MISMATCH",
                 "brand_code_scanned does not match the brewer's brand_code.")
    # Step 28: the identifier matches party_type and the point's requirement.
    if party_type != REQUIRED_PARTY[scan_point]:
        fail("ERR_SCAN_PARTY_MISMATCH",
             "A %s scan must be recorded by a %s."
             % (scan_point, REQUIRED_PARTY[scan_point]))
    supplied = {"BREWER": brewer_id, "DISTRIBUTOR": distributor_id,
                "RETAIL_ACCOUNT": retail_account_code}[party_type]
    if supplied is None:
        fail("ERR_SCAN_PARTY_MISMATCH",
             "%s is required when party_type is %s."
             % (PARTY_FIELD[party_type], party_type))
    if scan_point == "FILL" and brewer_id != keg["current_brewer_id"]:
        fail("ERR_SCAN_PARTY_MISMATCH",
             "brewer_id does not hold this keg.")
    if scan_point == "RETURN" and distributor_id != keg["current_distributor_id"]:
        fail("ERR_SCAN_PARTY_MISMATCH",
             "distributor_id does not hold this keg.")
    # Step 29: a trade-side collar must belong to some known brewer.
    if scan_point in ("DISTRIBUTION", "RETAIL", "RETURN"):
        if not any(row["brand_code"] == brand_code
                   for row in db.brewers.values()):
            fail("ERR_BRAND_OWNER_UNKNOWN",
                 "brand_code_scanned resolves to no known brewer.")
    # Step 33: no handheld reads the future.
    util.not_future_instant(scanned_at, "scanned_at")
    # Step 34 then step 35: stream integrity, then interval placement.
    for row in db.scan_events.values():
        if row["keg_id"] == keg["id"] and row["scan_point"] == scan_point \
                and row["scanned_at"] == scanned_at:
            fail("ERR_DUPLICATE_SCAN",
                 "That scan_point and scanned_at pair is already recorded.")
    if keg["dwell_started_at"] is not None \
            and scanned_at < keg["dwell_started_at"]:
        fail("ERR_CUSTODY_INTERVAL_CONFLICT",
             "scanned_at falls inside an already-closed custody interval.")

    dwell_days_closed = util.spell_days(keg["dwell_started_at"], scanned_at)
    is_late_arrival = keg["last_scanned_at"] is not None \
        and scanned_at < keg["last_scanned_at"]
    net_charge = None
    if scan_point == "FILL":
        charge = calc.fill_charge(agreement, dwell_days_closed)
        net_charge = charge["net_cents"]
        # Step 50: the fiscal gate is judged last.
        exposure = brewer["chargeback_balance_cents"] \
            + agreement["billed_amount_cents"] + net_charge
        if exposure > brewer["credit_limit_cents"]:
            fail("ERR_CREDIT_LIMIT_EXCEEDED",
                 "Projected exposure of %d cents exceeds the brewer's credit "
                 "limit." % exposure)

    scan = util.common_fields(versioned=False)
    scan.update({
        "keg_id": keg["id"],
        "scan_point": scan_point,
        "party_type": party_type,
        "brewer_id": brewer_id,
        "distributor_id": distributor_id,
        "retail_account_code": retail_account_code,
        "scanned_at": scanned_at,
        "recorded_at": clock.now(),
        "brand_code_scanned": brand_code,
        "misdelivery_detected": False,
        "is_late_arrival": is_late_arrival,
        "custody_state_after": target_state,
        "dwell_days_closed": dwell_days_closed,
        "fill_charge_net_cents": net_charge,
    })

    keg["custody_state"] = target_state
    keg["scan_count"] = keg["scan_count"] + 1
    keg["cumulative_dwell_days"] = keg["cumulative_dwell_days"] \
        + dwell_days_closed
    if keg["last_scanned_at"] is None or scanned_at > keg["last_scanned_at"]:
        keg["last_scanned_at"] = scanned_at
    if keg["dwell_started_at"] is None or scanned_at > keg["dwell_started_at"]:
        keg["dwell_started_at"] = scanned_at

    if scan_point == "FILL":
        keg["fill_count"] = keg["fill_count"] + 1
        keg["filled_brand_code"] = brand_code
        keg["filling_brewer_id"] = brewer_id
        keg["misdelivery_open"] = False
        if keg["service_state"] == "SERVICE_OK" \
                and keg["fill_count"] - keg["fills_at_last_pressure_test"] \
                >= calc.PRESSURE_TEST_INTERVAL_FILLS:
            keg["service_state"] = "SERVICE_DUE"
    elif scan_point == "DISTRIBUTION":
        keg["current_distributor_id"] = distributor_id
        keg["distributor_custody_started_at"] = scanned_at

    # Misdelivery detection runs on the three trade-side points only.
    if scan_point in ("DISTRIBUTION", "RETAIL", "RETURN"):
        if brand_code != keg["filled_brand_code"]:
            scan["misdelivery_detected"] = True
            keg["misdelivery_open"] = True

    distributor_days = calc.distributor_spell_days(keg, scanned_at)
    if scan_point == "RETURN":
        spell_open = keg["distributor_custody_started_at"] is not None
        keg["distributor_custody_started_at"] = None
    else:
        spell_open = False
    util.bump(keg)
    db.scan_events[scan["id"]] = scan

    if scan_point == "FILL":
        agreement["billed_fills_count"] = agreement["billed_fills_count"] + 1
        agreement["billed_amount_cents"] = agreement["billed_amount_cents"] \
            + net_charge
        util.bump(agreement)
        recompute.recompute_brewer_loss_counters(brewer)
    if scan_point == "RETURN" and spell_open:
        _mint_return_accrual(keg, distributor, scanned_at, distributor_days)
    recompute.cascade_pool(pool)
    return response.created(scan)


def _mint_return_accrual(keg, distributor, scanned_at, dwell_days):
    """The closed accountability spell mints a RETURN_DWELL accrual, priced on
    the tier as it stands, before any promotion is evaluated."""
    band_bp, multiplier_bp, cents = calc.return_incentive(distributor,
                                                          dwell_days)
    accrual = util.common_fields()
    accrual.update({
        "distributor_id": distributor["id"],
        "keg_id": keg["id"],
        "claim_id": None,
        "accrual_type": "RETURN_DWELL",
        "dwell_days": dwell_days,
        "tier_pct_bp": band_bp,
        "cooperation_multiplier_bp": multiplier_bp,
        "incentive_cents": cents,
        "triggering_scanned_at": scanned_at,
        "status": "ACCRUED",
        "paid_at": None,
        "clawback_reason": None,
    })
    db.accruals[accrual["id"]] = accrual
    recompute.recompute_distributor_stats(distributor)
    recompute.maybe_promote_tier(distributor)
    return accrual


@bp.get("/scan-events/<scan_event_id>")
def read_scan(scan_event_id):
    middleware.authenticate(*ALL_ROLES)
    scan = db.scan_events.get(scan_event_id)
    if scan is None:
        fail("ERR_SCAN_EVENT_NOT_FOUND")
    return response.ok(scan)


@bp.get("/scan-events")
def list_scans():
    middleware.authenticate(*ALL_ROLES)
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("keg_id", "brewer_id", "distributor_id",
                             "scan_point")}
    misdelivery = middleware.qbool("misdelivery_detected")
    late = middleware.qbool("is_late_arrival")
    rows = []
    for scan in db.scan_events.values():
        if not all(view.match(scan, field, value)
                   for field, value in filters.items()):
            continue
        if misdelivery is not None \
                and scan["misdelivery_detected"] != misdelivery:
            continue
        if late is not None and scan["is_late_arrival"] != late:
            continue
        rows.append(scan)
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)
