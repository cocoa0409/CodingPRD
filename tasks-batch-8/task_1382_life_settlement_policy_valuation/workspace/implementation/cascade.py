"""State-transition side effects: clock-driven automatic transitions and the
multi-entity cascades (acceptance, release, rescission, maturity, lapse,
license hold). Every mutated entity is touched (updated_at + version bump).
"""

from datetime import timedelta

import calc
from db import stamp, store, touch

CASE_TERMINAL = {"UW_DECLINED", "RESCINDED", "WITHDRAWN", "EXPIRED", "MATURED", "LAPSED"}
OFFER_TERMINAL = {"REJECTED", "WITHDRAWN", "EXPIRED"}
PACKAGE_TERMINAL = {"CLOSED", "CANCELLED"}
ESCROW_TERMINAL = {"CLOSED", "REVERSED"}
LE_REPORT_TERMINAL = {"SUPERSEDED", "EXPIRED"}
CLAIM_TERMINAL = {"PAID", "DENIED"}


# ---------------------------------------------------------------------------
# Logical clock automatic transitions (PRD §2.4)
# ---------------------------------------------------------------------------


def run_clock_transitions():
    now = store.clock
    today = now.date()

    # Offers past expiry
    for o in list(store.offers.values()):
        if o["status"] in ("PENDING", "COUNTERED") and o["expires_at"] < now:
            o["status"] = "EXPIRED"
            touch(o)

    # LE reports past validity
    for r in list(store.le_reports.values()):
        if r["status"] == "DELIVERED" and r["valid_through"] < now:
            r["status"] = "EXPIRED"
            touch(r)

    # Licenses past their closed window (no hold cascade on expiry)
    for lic in list(store.licenses.values()):
        if lic["status"] in ("ACTIVE", "SUSPENDED") and lic["expiry_date"] < today:
            lic["status"] = "EXPIRED"
            touch(lic)

    # Premium payments past grace (may trigger the lapse cascade)
    for p in list(store.payments.values()):
        if p["status"] == "SCHEDULED" and p["grace_deadline"] < now:
            p["status"] = "MISSED"
            touch(p)
            sched = store.schedules[p["schedule_id"]]
            sched["missed_payment_count"] += 1
            if sched["missed_payment_count"] >= 2 and sched["status"] == "ACTIVE":
                sched["status"] = "TERMINATED"
                touch(sched)
                lapse_cascade(sched)
            else:
                touch(sched)

    # MARKETED cases past their deadline with no live offers
    for c in list(store.cases.values()):
        if (
            c["status"] == "MARKETED"
            and c["marketing_deadline"] is not None
            and c["marketing_deadline"] < now
        ):
            live = any(
                o["case_id"] == c["id"] and o["status"] in ("PENDING", "COUNTERED")
                for o in store.offers.values()
            )
            if not live:
                c["status"] = "EXPIRED"
                touch(c)


def lapse_cascade(sched):
    case = store.cases[sched["case_id"]]
    if case["status"] == "ACQUIRED":
        case["status"] = "LAPSED"
        touch(case)
        policy = store.policies.get(case["policy_id"])
        if policy:
            policy["status"] = "LAPSED"
            touch(policy)
        pf = store.portfolios.get(case["portfolio_id"])
        if pf:
            pf["nav_stale"] = True
            touch(pf)


# ---------------------------------------------------------------------------
# License suspension / reinstatement hold cascades (PRD §2.8)
# ---------------------------------------------------------------------------


def suspension_cascade(license_row):
    for case in store.cases.values():
        if case["status"] not in ("MARKETED", "IN_CLOSING"):
            continue
        if case["hold_status"] != "CLEAR":
            continue
        policy = store.policies.get(case["policy_id"])
        insured = store.insureds.get(policy["insured_id"]) if policy else None
        if insured and insured["state_code"] == license_row["state_code"]:
            case["hold_status"] = "COMPLIANCE_HOLD"
            case["_hold_license_id"] = license_row["id"]
            touch(case)


def reinstate_cascade(license_row):
    for case in store.cases.values():
        if case["hold_status"] == "COMPLIANCE_HOLD" and case.get("_hold_license_id") == license_row["id"]:
            case["hold_status"] = "CLEAR"
            case["_hold_license_id"] = None
            touch(case)


# ---------------------------------------------------------------------------
# Offer acceptance cascade (PRD §3.3)
# ---------------------------------------------------------------------------


def acceptance_cascade(offer, case, effective_price, commission_bps):
    offer["effective_price_cents"] = effective_price
    offer["status"] = "ACCEPTED"
    touch(offer)

    case["accepted_offer_id"] = offer["id"]
    case["purchase_price_cents"] = effective_price
    case["broker_commission_bps"] = commission_bps
    case["status"] = "IN_CLOSING"
    touch(case)

    for o in store.offers.values():
        if (
            o["case_id"] == case["id"]
            and o["id"] != offer["id"]
            and o["status"] in ("PENDING", "COUNTERED")
        ):
            o["status"] = "REJECTED"
            touch(o)

    create_closing_package(case, offer)


def create_closing_package(case, offer):
    policy = store.policies[case["policy_id"]]
    insured = store.insureds[policy["insured_id"]]
    doc_types = list(calc.BASE_CLOSING_DOCS)
    if insured["state_code"] in calc.STATE_SUPPLEMENT_STATES:
        doc_types.append(calc.STATE_SUPPLEMENT_DOC)
    documents = [
        {"doc_type": dt, "required": True, "signed": False, "signed_at": None}
        for dt in doc_types
    ]
    pkg = {
        "case_id": case["id"],
        "offer_id": offer["id"],
        "status": "ASSEMBLED",
        "documents": documents,
        "deficiency_notes": None,
        "approved_by_user_id": None,
        "ownership_confirmed_at": None,
    }
    stamp(pkg)
    store.packages[pkg["id"]] = pkg

    escrow = {
        "case_id": case["id"],
        "status": "OPEN",
        "expected_funding_cents": calc.expected_funding(case["purchase_price_cents"]),
        "funded_amount_cents": None,
        "balance_cents": 0,
        "funded_at": None,
        "releasable_at": None,
        "released_at": None,
        "released_by_user_id": None,
        "refund_cents": None,
    }
    stamp(escrow)
    store.escrows[escrow["id"]] = escrow
    return pkg, escrow


# ---------------------------------------------------------------------------
# Escrow release / rescission (PRD §3.5)
# ---------------------------------------------------------------------------


def package_for_case(case_id):
    for p in store.packages.values():
        if p["case_id"] == case_id:
            return p
    return None


def escrow_for_case(case_id):
    for e in store.escrows.values():
        if e["case_id"] == case_id:
            return e
    return None


def release_cascade(escrow, case, releaser_user_id):
    policy = store.policies[case["policy_id"]]
    now = store.clock
    for bucket, amount in calc.waterfall(case, policy):
        disb = {
            "escrow_id": escrow["id"],
            "bucket": bucket,
            "amount_cents": amount,
            "payee_broker_id": case["broker_id"] if bucket == "BROKER_COMMISSION" and amount > 0 else None,
            "status": "PENDING",
        }
        stamp(disb)
        store.disbursements[disb["id"]] = disb

    escrow["balance_cents"] = escrow["funded_amount_cents"] - sum(
        d["amount_cents"]
        for d in store.disbursements.values()
        if d["escrow_id"] == escrow["id"]
    )
    escrow["released_at"] = now
    escrow["released_by_user_id"] = releaser_user_id
    escrow["status"] = "RELEASED"
    touch(escrow)

    pkg = package_for_case(case["id"])
    if pkg and pkg["status"] == "OWNERSHIP_CONFIRMED":
        pkg["status"] = "CLOSED"
        touch(pkg)

    case["status"] = "ACQUIRED"
    case["acquired_at"] = now
    touch(case)


def rescind_cascade(escrow, case):
    purchase_price = case["purchase_price_cents"]

    escrow["refund_cents"] = escrow["funded_amount_cents"]
    escrow["balance_cents"] = 0
    escrow["status"] = "REVERSED"
    touch(escrow)

    pkg = package_for_case(case["id"])
    if pkg and pkg["status"] not in PACKAGE_TERMINAL:
        pkg["status"] = "CANCELLED"
        touch(pkg)

    case["purchase_price_cents"] = None  # accepted_offer_id kept for audit
    case["status"] = "RESCINDED"
    touch(case)

    pf = store.portfolios.get(case["portfolio_id"])
    if pf:
        pf["invested_capital_cents"] -= purchase_price or 0
        pf["holding_count"] -= 1
        pf["nav_stale"] = True
        touch(pf)


# ---------------------------------------------------------------------------
# Death-claim settle maturity cascade (PRD §3.8)
# ---------------------------------------------------------------------------


def maturity_cascade(claim, case):
    now = store.clock
    case["status"] = "MATURED"
    case["matured_at"] = now
    touch(case)

    policy = store.policies.get(case["policy_id"])
    if policy:
        policy["status"] = "MATURED"
        touch(policy)
        insured = store.insureds.get(policy["insured_id"])
        if insured:
            insured["status"] = "DECEASED"
            touch(insured)

    sched = calc.active_schedule(case["id"])
    if sched:
        sched["status"] = "TERMINATED"
        touch(sched)

    pf = store.portfolios.get(case["portfolio_id"])
    if pf:
        pf["nav_stale"] = True
        touch(pf)
        for snap in store.snapshots.values():
            if snap["portfolio_id"] == pf["id"] and snap["status"] == "DRAFT":
                snap["status"] = "SUPERSEDED"
                touch(snap)


# ---------------------------------------------------------------------------
# Tracking verification support
# ---------------------------------------------------------------------------


def verified_death_source_count(case_id):
    channels = set()
    for ev in store.tracking_events.values():
        if (
            ev["case_id"] == case_id
            and ev["status"] == "VERIFIED"
            and ev["outcome"] == "DEATH_INDICATED"
        ):
            channels.add(ev["source_channel"])
    return len(channels)


def recompute_reported_claim_sources(case_id):
    count = verified_death_source_count(case_id)
    for claim in store.death_claims.values():
        if claim["case_id"] == case_id and claim["status"] == "REPORTED":
            if claim["verification_source_count"] != count:
                claim["verification_source_count"] = count
                touch(claim)
