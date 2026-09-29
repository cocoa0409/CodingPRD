"""The logical clock and the nightly compliance batch (PRD 2.4 / 3.9)."""
from datetime import timedelta

from flask import Blueprint

import calc
import envelope
import security
import shapes
import store
from security import ADMIN

bp = Blueprint("ops", __name__)

OPERABLE = ("ISSUED", "ACTIVE", "SUSPENDED")


@bp.post("/osup/_clock/set_current_utc")
def set_clock():
    security.authenticate((ADMIN,))
    data = shapes.body()
    raw = shapes.req_str(data, "to_iso8601")
    moment = store.parse_dt(raw, field="to_iso8601")
    # repositioning the clock writes no entity rows at all
    store.set_clock(moment, raw)
    return envelope.ok({"current_utc": store.now_str()})


@bp.post("/osup/_ops/run-daily-compliance-sweep")
def run_sweep():
    security.authenticate((ADMIN,))
    counters = {
        "certificates_expired": 0,
        "bonds_expired": 0,
        "guides_lapsed": 0,
        "permits_expired": 0,
        "authorizations_revoked": 0,
        "permits_suspended": 0,
    }
    today = store.today()
    touched_outfitters = set()
    suspended_this_run = set()
    lapsed_guides = set()

    # ---- step one: expire paper ------------------------------------------
    for cert in store.sort_created(store.all_of("insurance_certificates")):
        if cert["status"] == "ACTIVE" and store.as_date(cert["expiration_date"]) < today:
            cert["status"] = "EXPIRED"
            store.touch(cert)
            counters["certificates_expired"] += 1
    for bond in store.sort_created(store.all_of("bonds")):
        if bond["status"] == "ACTIVE" and store.as_date(bond["expiration_date"]) < today:
            bond["status"] = "EXPIRED"
            store.touch(bond)
            counters["bonds_expired"] += 1

    # ---- step two: lapse guides ------------------------------------------
    for guide in store.sort_created(store.all_of("guides")):
        if guide["status"] != "QUALIFIED":
            continue
        expires = guide.get("first_aid_expires_on")
        if expires is not None and store.as_date(expires) < today:
            guide["status"] = "LAPSED"
            guide["base_client_capacity"] = 0
            store.touch(guide)
            counters["guides_lapsed"] += 1
            lapsed_guides.add(guide["id"])
            touched_outfitters.add(guide["outfitter_id"])

    # ---- step three: expire permits --------------------------------------
    for permit in store.sort_created(store.all_of("permits")):
        if permit["administrative_status"] not in OPERABLE:
            continue
        if store.as_date(permit["term_end_date"]) < today:
            calc.close_out_permit(permit, "EXPIRED", counters)
            counters["permits_expired"] += 1
            touched_outfitters.add(permit["outfitter_id"])

    # ---- step four: re-derive the surviving permits -----------------------
    for permit in store.sort_created(store.all_of("permits")):
        if permit["administrative_status"] not in OPERABLE:
            continue
        touched_outfitters.add(permit["outfitter_id"])
        calc.recompute_permit_signals(permit)
        store.touch(permit)
        before = permit["administrative_status"]
        # the point-threshold cascade takes precedence over the insurance one
        calc.derive_compliance(permit, counters)
        if permit["administrative_status"] == "SUSPENDED" and before == "ACTIVE":
            suspended_this_run.add(permit["id"])
            continue
        if (
            permit["insurance_current"] is False
            and permit["administrative_status"] == "ACTIVE"
        ):
            days = calc.suspension_days_for_threshold(permit)
            until = store.fmt_dt(store.now_dt() + timedelta(days=days))
            calc.suspend_permit(permit, "INSURANCE_LAPSE", until, counters)
            suspended_this_run.add(permit["id"])

    # ---- step five: revoke authorizations whose basis is gone -------------
    affected_permits = set()
    for row in store.sort_created(store.all_of("authorizations")):
        if row["status"] != "AUTHORIZED":
            continue
        permit = store.get("permits", row["permit_id"])
        if row["guide_id"] in lapsed_guides:
            reason = "GUIDE_LAPSED"
        elif permit is None or permit["administrative_status"] not in OPERABLE:
            reason = "PERMIT_CLOSED"
        elif permit["id"] in suspended_this_run:
            reason = "PERMIT_SUSPENDED"
        elif permit["administrative_status"] == "SUSPENDED":
            reason = "PERMIT_SUSPENDED"
        else:
            continue
        row["status"] = "REVOKED"
        row["revoked_at"] = store.now_str()
        row["revocation_reason_code"] = reason
        store.touch(row)
        counters["authorizations_revoked"] += 1
        if permit is not None:
            affected_permits.add(permit["id"])

    for permit_id in sorted(affected_permits):
        permit = store.get("permits", permit_id)
        if permit is None:
            continue
        calc.recompute_permit_capacity_total(permit)
        store.touch(permit)
        touched_outfitters.add(permit["outfitter_id"])
        area = store.get("use_areas", permit["use_area_id"])
        if (
            area is not None
            and permit["administrative_status"] == "ACTIVE"
            and permit["authorized_client_capacity_total"] < area["party_size_max"]
            and permit["compliance_status"] == "COMPLIANT"
        ):
            permit["compliance_status"] = "PROBATION"
            store.touch(permit)

    # ---- step six: re-derive the outfitters the run touched ---------------
    for outfitter_id in sorted(touched_outfitters):
        calc.derive_outfitter(outfitter_id)

    payload = {"swept_at": store.now_str()}
    payload.update(counters)
    return envelope.ok(payload)
