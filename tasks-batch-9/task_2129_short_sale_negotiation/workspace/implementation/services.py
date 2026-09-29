"""Domain services: selectors, derived ledgers, staling rules and cascades."""
from decimal import Decimal

import calc
import constants as K
from db import db
from errors import fail
from timeutil import add_days, elapsed_days


# ---------------------------------------------------------------------------
# path / body resolution (ladder rungs 5 and 6)
# ---------------------------------------------------------------------------
def need(collection, rid, error_id):
    rec = db.get(collection, rid)
    if rec is None:
        fail(error_id, "No such resource: %s." % rid)
    return rec


def need_case(case_id):
    return need("cases", case_id, "ERR_CASE_NOT_FOUND")


def need_package(pid):
    return need("packages", pid, "ERR_PACKAGE_NOT_FOUND")


def need_document(did):
    return need("documents", did, "ERR_DOCUMENT_NOT_FOUND")


def need_listing(lid):
    return need("listings", lid, "ERR_LISTING_NOT_FOUND")


def need_offer(oid):
    return need("offers", oid, "ERR_OFFER_NOT_FOUND")


def need_valuation(vid):
    return need("valuations", vid, "ERR_VALUATION_NOT_FOUND")


def need_dispute(did):
    return need("disputes", did, "ERR_DISPUTE_NOT_FOUND")


def need_lien(lid):
    return need("liens", lid, "ERR_LIEN_NOT_FOUND")


def need_mi_claim(mid):
    return need("mi_claims", mid, "ERR_MI_CLAIM_NOT_FOUND")


def need_approval(aid):
    return need("approvals", aid, "ERR_APPROVAL_NOT_FOUND")


def need_extension(eid):
    return need("extensions", eid, "ERR_EXTENSION_NOT_FOUND")


# ---------------------------------------------------------------------------
# child collections
# ---------------------------------------------------------------------------
def case_packages(case_id):
    return [p for p in db.all("packages") if p["case_id"] == case_id]


def case_package(case_id):
    rows = case_packages(case_id)
    return rows[0] if rows else None


def package_documents(package_id):
    return [d for d in db.all("documents") if d["package_id"] == package_id]


def case_listings(case_id):
    return [l for l in db.all("listings") if l["case_id"] == case_id]


def case_offers(case_id):
    return [o for o in db.all("offers") if o["case_id"] == case_id]


def offer_net_sheets(offer_id):
    return [n for n in db.all("net_sheets") if n["offer_id"] == offer_id]


def case_valuations(case_id):
    return [v for v in db.all("valuations") if v["case_id"] == case_id]


def valuation_disputes(valuation_id):
    return [d for d in db.all("disputes") if d["valuation_id"] == valuation_id]


def case_liens(case_id):
    return [l for l in db.all("liens") if l["case_id"] == case_id]


def case_mi_claims(case_id):
    return [m for m in db.all("mi_claims") if m["case_id"] == case_id]


def case_mi_claim(case_id):
    rows = case_mi_claims(case_id)
    return rows[0] if rows else None


def case_approvals(case_id):
    return [a for a in db.all("approvals") if a["case_id"] == case_id]


def approval_extensions(approval_id):
    return [e for e in db.all("extensions") if e["approval_letter_id"] == approval_id]


# ---------------------------------------------------------------------------
# case state guard (ladder rung 9)
# ---------------------------------------------------------------------------
def require_case_actionable(case):
    if case["negotiation_status"] in K.CASE_TERMINAL_NEGOTIATION:
        fail(
            "ERR_CASE_NOT_ACTIONABLE",
            "The case is %s and accepts no further business operations."
            % case["negotiation_status"],
        )


# ---------------------------------------------------------------------------
# calculations.days_on_market + the controlling-listing selector
# ---------------------------------------------------------------------------
def days_on_market(listing):
    now = db.now()
    window_end = listing["ended_at"] if listing["ended_at"] is not None else now
    end = min(now, window_end)
    return max(elapsed_days(listing["listed_at"], end), 0)


def controlling_listing(case_id):
    candidates = [
        l
        for l in case_listings(case_id)
        if l["marketing_status"] in ("ACTIVE", "UNDER_CONTRACT")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["listed_at"], l["_seq"]), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# the controlling-valuation selector + calculations.minimum_acceptable_net
# ---------------------------------------------------------------------------
def controlling_valuation(case_id):
    candidates = [
        v
        for v in case_valuations(case_id)
        if v["status"] in ("RECEIVED", "DISPUTED", "REVISED", "FINAL")
        and v["value_cents"] is not None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: (v["effective_date"], v["_seq"]), reverse=True)
    return candidates[0]


def mi_credit_cents(case_id):
    claim = case_mi_claim(case_id)
    if claim is not None and claim["status"] == "APPROVED":
        return claim["required_contribution_cents"]
    return 0


def recompute_case_value(case):
    controlling = controlling_valuation(case["id"])
    if controlling is None:
        case["final_value_cents"] = None
        case["minimum_acceptable_net_cents"] = None
        return
    case["final_value_cents"] = controlling["value_cents"]
    case["minimum_acceptable_net_cents"] = calc.minimum_acceptable_net(
        controlling["value_cents"],
        case["investor_type"],
        case["unpaid_principal_balance_cents"],
        mi_credit_cents(case["id"]),
    )


def recompute_junior_ledger(case):
    total = 0
    count = 0
    for lien in case_liens(case["id"]):
        count += 1
        if lien["status"] == "APPROVED":
            total += lien["approved_contribution_cents"]
    case["junior_contribution_total_cents"] = total
    case["junior_lien_count"] = count


# ---------------------------------------------------------------------------
# net-sheet staling rules (PRD §3.8)
# ---------------------------------------------------------------------------
def stale_case_sheets(case_id, variant):
    for offer in case_offers(case_id):
        for sheet in offer_net_sheets(offer["id"]):
            if sheet["variant"] == variant and sheet["status"] == "CURRENT":
                sheet["status"] = "STALE"


def stale_offer_sheets(offer_id):
    for sheet in offer_net_sheets(offer_id):
        if sheet["status"] == "CURRENT":
            sheet["status"] = "STALE"


def junior_payoff_for_variant(case_id, variant):
    liens = sorted(case_liens(case_id), key=lambda l: (l["lien_position"], l["_seq"]))
    total = 0
    for lien in liens:
        if variant == "PRELIMINARY":
            if lien["status"] in ("DEMAND_SENT", "NEGOTIATING", "APPROVED"):
                total += lien["demand_cents"] or 0
        else:
            if lien["status"] == "APPROVED":
                total += lien["approved_contribution_cents"] or 0
    return total


# ---------------------------------------------------------------------------
# hardship scoring variants (PRD §3.3)
# ---------------------------------------------------------------------------
def qualifying_document_count(package, variant):
    docs = package_documents(package["id"])
    now = db.now()
    kinds = set()
    for doc in docs:
        if doc["doc_type"] not in K.REQUIRED_DOCUMENT_TYPES:
            continue
        if variant == "INTAKE":
            if doc["status"] in ("PENDING", "VERIFIED"):
                kinds.add(doc["doc_type"])
        else:  # SERVICER_AUDIT
            if doc["status"] != "VERIFIED":
                continue
            if elapsed_days(doc["issued_on"], now) <= K.DOCUMENT_MAX_AGE_DAYS:
                kinds.add(doc["doc_type"])
    return len(kinds)


def score_package(package, variant):
    return calc.hardship_severity_score(
        package["hardship_reason"],
        package["monthly_income_cents"],
        package["monthly_expenses_cents"],
        package["liquid_assets_cents"],
        qualifying_document_count(package, variant),
    )


def required_kinds_verified(package):
    """Every required doc_type has at least one VERIFIED document."""
    verified = {
        d["doc_type"] for d in package_documents(package["id"]) if d["status"] == "VERIFIED"
    }
    return all(kind in verified for kind in K.REQUIRED_DOCUMENT_TYPES)


def required_kinds_present(package):
    """Every required doc_type has at least one PENDING-or-VERIFIED document."""
    present = {
        d["doc_type"]
        for d in package_documents(package["id"])
        if d["status"] in ("PENDING", "VERIFIED")
    }
    return all(kind in present for kind in K.REQUIRED_DOCUMENT_TYPES)


# ---------------------------------------------------------------------------
# approval-letter chain helpers (PRD §3.9)
# ---------------------------------------------------------------------------
def expire_letter_if_past_deadline(letter):
    """Lazy expiry — ladder rung 10.

    Called only on the three operations the PRD names: closing under a letter,
    filing an extension request against it, and deciding one.
    """
    if letter["status"] != "ACTIVE":
        return
    if db.now() > letter["closing_deadline"]:
        letter["status"] = "EXPIRED"
        cancel_requested_extensions(letter["id"])
        fail("ERR_APPROVAL_EXPIRED", "The approval letter's closing deadline has passed.")


def cancel_requested_extensions(approval_id, except_id=None):
    fired = False
    for ext in approval_extensions(approval_id):
        if ext["id"] == except_id:
            continue
        if ext["status"] == "REQUESTED":
            ext["status"] = "CANCELLED"
            fired = True
    return fired


def mint_successor_letter(predecessor, granted_days):
    now = db.now()
    successor = {
        "id": db.new_id(),
        "case_id": predecessor["case_id"],
        "offer_id": predecessor["offer_id"],
        "supersedes_approval_id": predecessor["id"],
        "approved_net_proceeds_cents": predecessor["approved_net_proceeds_cents"],
        "commission_cap_pct": predecessor["commission_cap_pct"],
        "seller_relocation_incentive_cents": predecessor["seller_relocation_incentive_cents"],
        "deficiency_waiver": predecessor["deficiency_waiver"],
        "conditions": list(predecessor["conditions"]),
        "issued_by_user_id": predecessor["issued_by_user_id"],
        "issued_at": predecessor["issued_at"],
        "closing_deadline": add_days(predecessor["closing_deadline"], granted_days),
        "cumulative_extension_days_used": predecessor["cumulative_extension_days_used"]
        + granted_days,
        "status": "ACTIVE",
    }
    db.insert("approvals", successor)
    return successor


# ---------------------------------------------------------------------------
# CASCADE-A hops 3-5 (PRD §3.6)
# ---------------------------------------------------------------------------
def cascade_a_propagate(case):
    """hop 3 -> hop 4 -> hop 5, each firing only if the prior one fired."""
    # hop 3: recompute the case's derived floor
    recompute_case_value(case)
    minimum = case["minimum_acceptable_net_cents"]
    if minimum is None:
        return

    active_before = [a for a in case_approvals(case["id"]) if a["status"] == "ACTIVE"]

    # hop 4: void under-water ACTIVE letters
    voided = []
    for letter in active_before:
        if letter["approved_net_proceeds_cents"] < minimum:
            letter["status"] = "VOIDED"
            voided.append(letter)
    if not voided:
        return

    # hop 5: clean up behind each voided letter
    for letter in voided:
        cancel_requested_extensions(letter["id"])
    still_active = [a for a in case_approvals(case["id"]) if a["status"] == "ACTIVE"]
    if not still_active and case["negotiation_status"] == "APPROVAL_ACTIVE":
        case["negotiation_status"] = "RENEGOTIATION"


# ---------------------------------------------------------------------------
# CASCADE-B (PRD §3.5)
# ---------------------------------------------------------------------------
def cascade_b_offer_rejected(case, offer):
    # hop 1
    offer["status"] = "REJECTED"

    # hop 2, caused by hop 1
    listing = controlling_listing(case["id"])
    if listing is not None and listing["marketing_status"] == "UNDER_CONTRACT":
        listing["marketing_status"] = "ACTIVE"
    case["failed_offer_count"] = case["failed_offer_count"] + 1
    if case["negotiation_status"] == "OFFER_UNDER_REVIEW":
        case["negotiation_status"] = "MARKETED"

    # hop 3, caused by hop 2
    if case["failed_offer_count"] < K.PRICE_REDUCTION_TRIGGER_COUNT:
        return
    case["price_reduction_required"] = True

    # hop 4, caused by hop 3
    package = case_package(case["id"])
    if package is not None and package["status"] == "ACCEPTED":
        package["status"] = "REVALIDATION_REQUIRED"
        package["hardship_score_audit"] = None
        if case["documentation_status"] == "DOC_COMPLETE":
            case["documentation_status"] = "DOC_STALE"


# ---------------------------------------------------------------------------
# vendor scheduling (calculations.vendor_slot_admission)
# ---------------------------------------------------------------------------
def vendor_slot_conflict(vendor_id, start, end):
    from datetime import timedelta

    buffer_delta = timedelta(minutes=K.VENDOR_INSPECTION_BUFFER_MINUTES)
    for val in db.all("valuations"):
        if val["vendor_id"] != vendor_id:
            continue
        if start < val["inspection_end"] + buffer_delta and end > val["inspection_start"] - buffer_delta:
            return True
    return False


def vendor_same_day_count(vendor_id, start):
    from timeutil import utc_date

    target = utc_date(start)
    return sum(
        1
        for val in db.all("valuations")
        if val["vendor_id"] == vendor_id and utc_date(val["inspection_start"]) == target
    )


# ---------------------------------------------------------------------------
# listing window admission (calculations.listing_window_admission)
# ---------------------------------------------------------------------------
def listing_window_conflict(case_id, listed_at):
    """Half-open [listed_at, ended_at); a new listing's end is +infinity."""
    for listing in case_listings(case_id):
        existing_end = listing["ended_at"]
        if existing_end is None or listed_at < existing_end:
            return True
    return False
