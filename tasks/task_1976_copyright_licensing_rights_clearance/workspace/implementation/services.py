"""Business logic: posture derivation, cascades, clock sweeps, calculations.

Implements PRD 2.9 (posture precedence chain), 3.5 (usage accounting),
3.7 (takedown cascades / revocation strikes), 3.9 (sweeps), and the fee
recipe of 3.3.
"""
from datetime import timedelta

import state as S


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_holder(hid):
    return S.rights_holders.get(hid)


def get_asset(aid):
    return S.assets.get(aid)


def get_request(rid):
    return S.clearance_requests.get(rid)


def get_license(lid):
    return S.licenses.get(lid)


def get_reservation(rid):
    return S.usage_reservations.get(rid)


def get_assessment(aid):
    return S.fair_use_assessments.get(aid)


def get_notice(nid):
    return S.takedown_notices.get(nid)


def asset_licenses(asset_id):
    return [lic for lic in S.licenses.values() if lic["asset_id"] == asset_id]


def asset_notices(asset_id):
    return [n for n in S.takedown_notices.values() if n["asset_id"] == asset_id]


def asset_requests(asset_id):
    return [r for r in S.clearance_requests.values() if r["asset_id"] == asset_id]


def request_rounds(req_id):
    return sorted(
        [r for r in S.negotiation_rounds.values()
         if r["clearance_request_id"] == req_id],
        key=lambda r: r["round_index"],
    )


def license_reservations(lic_id):
    return [r for r in S.usage_reservations.values() if r["license_id"] == lic_id]


def license_events(lic_id):
    return [e for e in S.usage_events.values() if e["license_id"] == lic_id]


def license_payments(lic_id):
    return [p for p in S.license_payments.values() if p["license_id"] == lic_id]


def license_alerts(lic_id):
    return [a for a in S.renewal_alerts.values() if a["license_id"] == lic_id]


def asset_diligence_logs(asset_id):
    return sorted(
        [d for d in S.diligence_logs.values() if d["asset_id"] == asset_id],
        key=lambda d: (d["created_at"], d["_seq"]),
    )


# ---------------------------------------------------------------------------
# Territory semantics (scaffold §1.3 territory_weight)
# ---------------------------------------------------------------------------
def territory_contains(a, b):
    return a == "WORLD" or a == b


def territories_overlap(a, b):
    return territory_contains(a, b) or territory_contains(b, a)


# ---------------------------------------------------------------------------
# License computed usage fields (PRD 3.5 / scaffold usage_consumption)
# ---------------------------------------------------------------------------
def license_units_reserved(lic):
    return sum(r["units"] for r in license_reservations(lic["id"])
               if r["status"] == "HELD")


def license_units_consumed_gross(lic):
    # PRD 3.5: gross counts every event — "struck usage still counted, because
    # the use happened" — and is untouched by takedown strikes (PRD 3.7).
    return sum(e["units"] for e in license_events(lic["id"]))


def license_units_struck(lic):
    return sum(e["units"] for e in license_events(lic["id"])
               if e["posting_kind"] == "STRUCK")


def license_units_consumed_net(lic):
    return license_units_consumed_gross(lic) - license_units_struck(lic)


def license_units_available(lic):
    return (lic["unit_limit"]
            - license_units_reserved(lic)
            - license_units_consumed_net(lic))


# ---------------------------------------------------------------------------
# Fee status (PRD 3.6 / scaffold fee_status_rule)
# ---------------------------------------------------------------------------
def license_paid_total(lic):
    return sum(p["amount_cents"] for p in license_payments(lic["id"]))


def recompute_fee_status(lic):
    pays = license_payments(lic["id"])
    paid = sum(p["amount_cents"] for p in pays)
    if paid <= 0 and len(pays) > 0:
        lic["fee_status"] = "REFUNDED"
    elif paid == 0:
        lic["fee_status"] = "UNPAID"
    elif paid < lic["fee_agreed_cents"]:
        lic["fee_status"] = "PARTIALLY_PAID"
    elif paid == lic["fee_agreed_cents"]:
        lic["fee_status"] = "PAID"
    else:
        # overpayment is rejected before this rule ever runs
        lic["fee_status"] = "PAID"


# ---------------------------------------------------------------------------
# MFN floor (PRD 3.3 / scaffold mfn_floor)
# ---------------------------------------------------------------------------
def mfn_floor_cents(req):
    asset = get_asset(req["asset_id"])
    if asset is None or asset.get("rights_holder_id") is None:
        return 0
    holder = get_holder(asset["rights_holder_id"])
    if holder is None:
        return 0
    if holder["holder_kind"] == "ESTATE":
        return 0
    return holder["mfn_floor_cents"] * req["requested_units"]


# ---------------------------------------------------------------------------
# Fee estimate (PRD 3.3 / scaffold license_fee_estimate)
# ---------------------------------------------------------------------------
def fee_estimate_cents(req, apply_floor=False):
    base = S.MEDIA_UNIT_RATE_CENTS[req["media"]] * req["requested_units"]
    territory_mult = S.TERRITORY_WEIGHT[req["territory"]]
    term_days = whole_days(req["use_start_at"], req["use_end_at"])
    if term_days <= 90:
        term_mult = 1.0
    elif term_days <= 365:
        term_mult = 1.25
    else:
        term_mult = 1.6
    raw = base * territory_mult * term_mult
    if req["requested_units"] >= S.BULK_UNITS_MIN:
        raw = raw * (1.0 - S.BULK_DISCOUNT)
    # round half-up exactly once at the final step (PRD 2.6)
    from decimal import Decimal, ROUND_HALF_UP
    fee = int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if apply_floor:
        floor = mfn_floor_cents(req)
        if floor > fee:
            fee = floor
    return fee


# ---------------------------------------------------------------------------
# Asset posture (PRD 2.9 / scaffold asset_posture)
# ---------------------------------------------------------------------------
def derive_posture(asset):
    """Pure derivation per the fixed precedence chain, first match wins."""
    clock = S.now_dt()
    if asset.get("retired_at") is not None:
        return "RETIRED"
    notices = asset_notices(asset["id"])
    for n in notices:
        if n["status"] == "UPHELD":
            return "SUSPENDED"
    for n in notices:
        if n["status"] == "PENDING" and clock > n["counter_notice_due_at"]:
            return "SUSPENDED"
    if asset["orphan_status"] == "DILIGENCE_PENDING":
        return "ENCUMBERED"
    for n in notices:
        if n["status"] == "PENDING" and clock <= n["counter_notice_due_at"]:
            return "ENCUMBERED"
    for lic in asset_licenses(asset["id"]):
        if lic["lifecycle"] == "ACTIVE" and lic["territory"] == "WORLD":
            return "ENCUMBERED"
    return "CLEAR"


def _cascade_license_suspended(lic):
    """ACTIVE -> SUSPENDED side effects (PRD 3.7)."""
    lic["lifecycle"] = "SUSPENDED"
    lic["suspension_cause"] = "TAKEDOWN"
    for r in license_reservations(lic["id"]):
        if r["status"] == "HELD":
            r["status"] = "FORFEITED"
            S.touch(r)
    for a in license_alerts(lic["id"]):
        if a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            S.touch(a)
    S.touch(lic)


def _cascade_license_reactivated(lic):
    """SUSPENDED (by TAKEDOWN) -> ACTIVE side effects (PRD 3.7)."""
    lic["lifecycle"] = "ACTIVE"
    lic["suspension_cause"] = None
    # recreate renewal alert if its fires_at is still in the future
    fires_at = lic["term_end_at"] - timedelta(days=S.RENEWAL_ALERT_LEAD_DAYS)
    if fires_at > S.now_dt():
        alert = S.stamp_new({
            "license_id": lic["id"],
            "fires_at": fires_at,
            "status": "SCHEDULED",
        })
        S.renewal_alerts[alert["id"]] = alert
        lic["renewal_alert_id"] = alert["id"]
    S.touch(lic)


def recompute_asset_posture(asset):
    """Recompute posture; run cascade side effects on transitions (PRD 2.9)."""
    old = asset.get("posture", "CLEAR")
    new = derive_posture(asset)
    if new == old:
        return
    asset["posture"] = new
    if new == "SUSPENDED":
        for lic in asset_licenses(asset["id"]):
            if lic["lifecycle"] == "ACTIVE":
                _cascade_license_suspended(lic)
    elif old == "SUSPENDED":
        # moving away from SUSPENDED: restore only takedown-suspended licenses
        for lic in asset_licenses(asset["id"]):
            if (lic["lifecycle"] == "SUSPENDED"
                    and lic.get("suspension_cause") == "TAKEDOWN"):
                _cascade_license_reactivated(lic)
    S.touch(asset)


def touch_asset(asset):
    """Cascade-touch the asset (version bump, updated_at refresh) per PRD 2.9."""
    S.touch(asset)


# ---------------------------------------------------------------------------
# License expiry side effects (PRD 3.9)
# ---------------------------------------------------------------------------
def _license_expire(lic):
    lic["lifecycle"] = "EXPIRED"
    for r in license_reservations(lic["id"]):
        if r["status"] == "HELD":
            r["status"] = "FORFEITED"
            S.touch(r)
    clock = S.now_dt()
    for a in license_alerts(lic["id"]):
        if a["status"] == "SCHEDULED":
            if a["fires_at"] <= clock:
                a["status"] = "FIRED"
            else:
                a["status"] = "CANCELLED"
            S.touch(a)
    S.touch(lic)


# ---------------------------------------------------------------------------
# Clock sweeps (PRD 2.5, 3.9)
# ---------------------------------------------------------------------------
def run_clock_sweeps():
    """Evaluate every clock-driven transition, in a fixed order."""
    clock = S.now_dt()

    # 1) Clearance-request expiry sweep:
    #    SUBMITTED -> EXPIRED when clock >= use_end_at
    #    APPROVED  -> EXPIRED when clock >= use_end_at and grant never executed
    for req in list(S.clearance_requests.values()):
        if req["status"] in ("SUBMITTED", "APPROVED"):
            if clock >= req["use_end_at"]:
                req["status"] = "EXPIRED"
                S.touch(req)

    # 2) Reservation forfeiture sweep: HELD -> FORFEITED at hold_expires_at
    for r in list(S.usage_reservations.values()):
        if r["status"] == "HELD" and clock >= r["hold_expires_at"]:
            r["status"] = "FORFEITED"
            S.touch(r)

    # 3) Takedown counter-window lapse sweep: PENDING -> UPHELD when
    #    clock strictly greater than counter_notice_due_at
    for n in list(S.takedown_notices.values()):
        if n["status"] == "PENDING" and clock > n["counter_notice_due_at"]:
            n["status"] = "UPHELD"
            S.touch(n)

    # 4) License expiry sweep: ACTIVE -> EXPIRED when clock >= term_end_at
    for lic in list(S.licenses.values()):
        if lic["lifecycle"] == "ACTIVE" and clock >= lic["term_end_at"]:
            _license_expire(lic)

    # 5) Renewal-alert firing sweep: SCHEDULED -> FIRED at fires_at while
    #    license still ACTIVE
    for a in list(S.renewal_alerts.values()):
        if a["status"] == "SCHEDULED" and clock >= a["fires_at"]:
            lic = get_license(a["license_id"])
            if lic is not None and lic["lifecycle"] == "ACTIVE":
                a["status"] = "FIRED"
                S.touch(a)

    # 6) Asset posture recompute (any of the above may have shifted posture)
    for asset in list(S.assets.values()):
        recompute_asset_posture(asset)
