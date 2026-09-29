"""Domain arithmetic, ledgers and cascades (PRD section 3, SCAFFOLD 1.3)."""
from decimal import Decimal

import clock
from errors import ApiError
from store import db, new_row, touch, ordered
from validation import D, q2, q4, q6

ZERO = Decimal("0.00")
ONE = Decimal("1")

# --- pinned constants (SCAFFOLD 1.3 `constants:` blocks) ----------------------
WW_MAX_STORAGE_DAYS = 60
VESSEL_OVERAGE_YEARS = 25
VESSEL_BLOCK_YEARS = 30
VESSEL_OVERAGE_SURCHARGE_PCT = Decimal("0.25")
APPROVED_SOCIETIES = ("LR", "ABS", "DNV", "BV", "NK", "CCS")
CANCEL_UNEARNED_PCT_PRE_ATTACHMENT = Decimal("1.00")
CANCEL_UNEARNED_PCT_POST_ATTACHMENT = Decimal("0.50")
GA_ADJUSTER_FEE_PCT = Decimal("0.05")
GA_CASH_DEPOSIT_THRESHOLD = Decimal("25000")
GA_CASH_DEPOSIT_PCT = Decimal("0.20")
DECLARATION_AUDIT_TOLERANCE_PCT = Decimal("2.5")
DECLARATION_SUSPENSION_PCT = Decimal("10.0")
ZERO_BASE_VARIANCE_PCT = Decimal("100.00")
SUBROGATION_TIME_BAR_DAYS = 365
SURVEY_WINDOW_MIN_MINUTES = 30
SURVEY_WINDOW_MAX_MINUTES = 480
MANDATORY_DOC_TYPES = ("SURVEY_REPORT", "BILL_OF_LADING", "CARRIER_CLAIM_LETTER")
WAR_TIER_MULTIPLIER = {
    "GREEN": Decimal("1.0"),
    "AMBER": Decimal("1.5"),
    "LISTED_AREA": Decimal("0.0"),
}


# --- lookups ----------------------------------------------------------------
def find(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def policy_of(certificate):
    return db.open_policies[certificate["open_policy_id"]]


def certificates_of_policy(policy_id):
    return ordered([c for c in db.certificates.values()
                    if c["open_policy_id"] == policy_id])


def active_entries_of(certificate_id):
    return ordered([e for e in db.accumulation_entries.values()
                    if e["certificate_id"] == certificate_id and e["status"] == "ACTIVE"])


# --- calculation: certificate_insured_value ---------------------------------
def insured_value_for(cert, policy):
    if cert["valuation_basis"] == "DECLARED_VALUE":
        return q2(cert["declared_value"])
    cif_base = D(cert["invoice_value"]) + D(cert["duty_amount"] or 0)
    if policy["freight_basis"] == "PREPAID":
        cif_base = cif_base + D(cert["freight_amount"] or 0)
    return q2(cif_base * (ONE + D(policy["markup_pct"])))


# --- calculation: transit_termination_instant -------------------------------
def transit_termination_for(cert, policy, discharge_port):
    discharge_instant = clock.midnight(cert["discharge_date"])
    if not policy["warehouse_to_warehouse"]:
        return discharge_instant
    storage_deadline = clock.plus_days(discharge_instant, discharge_port["storage_free_days"])
    ww_cap = clock.plus_days(discharge_instant, WW_MAX_STORAGE_DAYS)
    return min(storage_deadline, ww_cap, policy["expiry_at"])


# --- calculation: certificate_premium_components ----------------------------
def premium_components(cert, policy, commodity, vessel, loading_port, discharge_port,
                       insured_value, war_attached):
    effective_rate = q4(
        D(policy["premium_rate_per_mille"])
        * (ONE + D(commodity["rate_loading_pct"]))
        * (ONE + D(vessel["overage_surcharge_pct"]))
    )
    port_multiplier = max(D(loading_port["war_rate_multiplier"]),
                          D(discharge_port["war_rate_multiplier"]))
    effective_war_rate = q4(D(policy["war_rate_per_mille"]) * port_multiplier)

    per_mille = D(insured_value) / Decimal(1000)
    base = q2(per_mille * effective_rate)
    war = q2(per_mille * effective_war_rate) if war_attached else ZERO
    strikes = (q2(per_mille * D(policy["strikes_rate_per_mille"]))
               if cert["strikes_cover_requested"] else ZERO)
    total = q2(base + war + strikes)
    return {
        "effective_rate_per_mille": effective_rate,
        "base_premium_amount": base,
        "war_premium_amount": war,
        "strikes_premium_amount": strikes,
        "total_premium_amount": total,
    }


def war_axis_attached(cert, policy, loading_port, discharge_port):
    """PRD 3.4 'The war axis at issue'."""
    if not cert["war_cover_requested"]:
        return False
    if policy["war_cover_status"] not in ("ATTACHED", "REINSTATED"):
        return False
    if loading_port["war_risk_tier"] == "LISTED_AREA":
        return False
    if discharge_port["war_risk_tier"] == "LISTED_AREA":
        return False
    return True


# --- calculation: vessel_classification_decision ---------------------------
def classification_decision(vessel):
    age = clock.now().year - vessel["year_built"]
    if vessel["classification_society"] not in APPROVED_SOCIETIES:
        return "BLOCKED", ZERO
    if age > VESSEL_BLOCK_YEARS:
        return "BLOCKED", ZERO
    if age > VESSEL_OVERAGE_YEARS:
        return "OVERAGE_SURCHARGED", VESSEL_OVERAGE_SURCHARGE_PCT
    return "APPROVED", ZERO


# --- capacity tower (calculation: accumulation_exposure_check) -------------
def commodity_share_ceiling(policy, commodity):
    return q2(D(policy["conveyance_limit_amount"]) * D(commodity["max_conveyance_share_pct"]))


def check_commodity_share(policy, commodity, candidate):
    if D(candidate) > commodity_share_ceiling(policy, commodity):
        raise ApiError("ERR_COMMODITY_SHARE_EXCEEDED")


def run_capacity_tower(cert, policy, commodity, vessel, discharge_port, candidate,
                       cand_end, exclude_certificate_ids=()):
    """PRD 3.4 'The capacity tower' -- six comparisons, all strictly greater than."""
    check_commodity_share(policy, commodity, candidate)

    if D(candidate) > D(policy["per_certificate_limit_amount"]):
        raise ApiError("ERR_CERTIFICATE_LIMIT_EXCEEDED")

    conveyance_exposure = ZERO
    for other in db.certificates.values():
        if other["id"] in exclude_certificate_ids or other["id"] == cert["id"]:
            continue
        if other["vessel_id"] != cert["vessel_id"]:
            continue
        if other["sailing_date"] != cert["sailing_date"]:
            continue
        if other["status"] not in ("ISSUED", "CLAIMED", "TRANSIT_ENDED"):
            continue
        conveyance_exposure += D(other["insured_value"] or 0)
    if conveyance_exposure + D(candidate) > D(policy["conveyance_limit_amount"]):
        raise ApiError("ERR_CONVEYANCE_LIMIT_EXCEEDED")

    vessel_exposure = ZERO
    for entry in db.accumulation_entries.values():
        if entry["scope_type"] != "VESSEL" or entry["status"] != "ACTIVE":
            continue
        if entry["vessel_id"] != cert["vessel_id"]:
            continue
        if entry["certificate_id"] in exclude_certificate_ids:
            continue
        vessel_exposure += D(entry["amount"])
    if vessel_exposure + D(candidate) > D(vessel["vessel_accumulation_limit_amount"]):
        raise ApiError("ERR_VESSEL_ACCUMULATION_EXCEEDED")

    cand_start = clock.midnight(cert["discharge_date"])
    port_exposure = ZERO
    for entry in db.accumulation_entries.values():
        if entry["scope_type"] != "DISCHARGE_PORT" or entry["status"] != "ACTIVE":
            continue
        if entry["port_id"] != cert["discharge_port_id"]:
            continue
        if entry["certificate_id"] in exclude_certificate_ids:
            continue
        if entry["window_start_at"] < cand_end and entry["window_end_at"] > cand_start:
            port_exposure += D(entry["amount"])
    if port_exposure + D(candidate) > D(discharge_port["port_accumulation_limit_amount"]):
        raise ApiError("ERR_PORT_ACCUMULATION_EXCEEDED")

    if D(policy["aggregate_insured_value_booked"]) + D(candidate) > D(
            policy["annual_aggregate_limit_amount"]):
        raise ApiError("ERR_ANNUAL_AGGREGATE_EXCEEDED")


# --- accumulation ledger movements (PRD 2.11, 3.4) --------------------------
def _make_entry(cert, scope_type, vessel_id, port_id, amount, start_at, end_at):
    entry = new_row()
    entry.update({
        "certificate_id": cert["id"],
        "vessel_id": vessel_id,
        "port_id": port_id,
        "scope_type": scope_type,
        "amount": q2(amount),
        "window_start_at": start_at,
        "window_end_at": end_at,
        "status": "ACTIVE",
        "release_reason": "NONE",
    })
    db.accumulation_entries[entry["id"]] = entry
    return entry


def book_exposure(cert, vessel, loading_port, discharge_port, amount):
    """Create the three ACTIVE ledger rows and raise the three ledgers."""
    attachment = cert["attachment_at"]
    discharge_instant = clock.midnight(cert["discharge_date"])
    termination = cert["transit_termination_at"]
    _make_entry(cert, "VESSEL", vessel["id"], None, amount, attachment, discharge_instant)
    _make_entry(cert, "LOADING_PORT", None, loading_port["id"], amount, attachment,
                discharge_instant)
    _make_entry(cert, "DISCHARGE_PORT", None, discharge_port["id"], amount,
                discharge_instant, termination)
    vessel["accumulated_insured_value"] = q2(D(vessel["accumulated_insured_value"]) + D(amount))
    touch(vessel)
    loading_port["accumulated_insured_value"] = q2(
        D(loading_port["accumulated_insured_value"]) + D(amount))
    touch(loading_port)
    discharge_port["accumulated_insured_value"] = q2(
        D(discharge_port["accumulated_insured_value"]) + D(amount))
    touch(discharge_port)


def release_exposure(cert, reason):
    """Compensating movement: every ACTIVE row is RELEASED and its ledger reduced."""
    for entry in active_entries_of(cert["id"]):
        entry["status"] = "RELEASED"
        entry["release_reason"] = reason
        touch(entry)
        amount = D(entry["amount"])
        if entry["scope_type"] == "VESSEL":
            target = db.vessels.get(entry["vessel_id"])
        else:
            target = db.ports.get(entry["port_id"])
        if target is not None:
            target["accumulated_insured_value"] = q2(
                D(target["accumulated_insured_value"]) - amount)
            touch(target)


# --- calculation: certificate_return_premium --------------------------------
def book_return_premium(cert, policy, delta):
    delta = q2(delta)
    cert["return_premium_amount"] = q2(D(cert["return_premium_amount"]) + delta)
    policy["aggregate_return_premium"] = q2(D(policy["aggregate_return_premium"]) + delta)
    return delta


def cancellation_return(cert):
    pct = (CANCEL_UNEARNED_PCT_PRE_ATTACHMENT
           if clock.now() < cert["attachment_at"]
           else CANCEL_UNEARNED_PCT_POST_ATTACHMENT)
    unreturned = (D(cert["total_premium_amount"]) + D(cert["reinstatement_premium_amount"])
                  - D(cert["return_premium_amount"]))
    return q2(unreturned * pct)


def war_termination_return(cert):
    if cert["war_cover_status"] == "REINSTATED":
        return q2(cert["reinstatement_premium_amount"])
    return q2(D(cert["war_premium_amount"]) + D(cert["strikes_premium_amount"]))


# --- calculation: declaration_premium_reconciliation ------------------------
def reconcile_declaration(declaration):
    members = [c for c in db.certificates.values()
               if c["premium_declaration_id"] == declaration["id"]]
    computed = ZERO
    for cert in members:
        computed += (D(cert["total_premium_amount"] or 0)
                     + D(cert["reinstatement_premium_amount"] or 0)
                     - D(cert["return_premium_amount"] or 0))
    computed = q2(computed)
    declared = D(declaration["declared_premium_total"] or 0)
    variance = q2(declared - computed)
    if computed == ZERO:
        variance_pct = ZERO if declared == ZERO else ZERO_BASE_VARIANCE_PCT
    else:
        variance_pct = q2(abs(variance) / computed * Decimal(100))
    declaration["certificate_count"] = len(members)
    declaration["computed_premium_total"] = computed
    declaration["variance_amount"] = variance
    declaration["variance_pct"] = variance_pct


def recompute_declaration_totals(declaration):
    """Cascade link 5 of the port re-tier: totals move, status and count do not."""
    members = [c for c in db.certificates.values()
               if c["premium_declaration_id"] == declaration["id"]]
    computed = ZERO
    for cert in members:
        computed += (D(cert["total_premium_amount"] or 0)
                     + D(cert["reinstatement_premium_amount"] or 0)
                     - D(cert["return_premium_amount"] or 0))
    computed = q2(computed)
    declared = D(declaration["declared_premium_total"] or 0)
    variance = q2(declared - computed)
    if computed == ZERO:
        variance_pct = ZERO if declared == ZERO else ZERO_BASE_VARIANCE_PCT
    else:
        variance_pct = q2(abs(variance) / computed * Decimal(100))
    declaration["computed_premium_total"] = computed
    declaration["variance_amount"] = variance
    declaration["variance_pct"] = variance_pct
    touch(declaration)


# --- calculation: claim_adjusted_amount ------------------------------------
def quantify_loss(claim, cert):
    insured = D(cert["insured_value"])
    deductible = D(cert["deductible_amount"] or 0)
    if claim["adjustment_basis"] == "DEPRECIATION_PCT":
        if claim["damage_percentage"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'damage_percentage' is required to adjust on this basis.")
        gross = q2(insured * D(claim["damage_percentage"]) / Decimal(100))
        adjusted = gross - deductible
        if adjusted < ZERO:
            adjusted = ZERO
        applied = deductible if deductible < gross else gross
        adjusted = q2(adjusted)
        applied = q2(applied)
    else:
        if claim["sound_market_value"] is None or claim["damaged_sale_proceeds"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Fields 'sound_market_value' and 'damaged_sale_proceeds' are "
                           "required to adjust on this basis.")
        smv = D(claim["sound_market_value"])
        proceeds = D(claim["damaged_sale_proceeds"])
        if smv == ZERO:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'sound_market_value' must be greater than 0.")
        ratio = q6((smv - proceeds) / smv)
        adjusted = q2((insured - deductible) * ratio)
        applied = q2(q2(insured * ratio) - adjusted)
    if adjusted > insured:
        adjusted = q2(insured)
    return adjusted, applied


def documentation_complete_for(claim_id):
    present = {doc["doc_type"] for doc in db.damage_documents.values()
               if doc["claim_file_id"] == claim_id}
    return all(kind in present for kind in MANDATORY_DOC_TYPES)


def append_document(claim, doc_type, reference, received_at, origin):
    doc = new_row(versioned=False)
    doc.update({
        "claim_file_id": claim["id"],
        "doc_type": doc_type,
        "reference": reference,
        "received_at": received_at,
        "origin": origin,
    })
    db.damage_documents[doc["id"]] = doc
    claim["documentation_complete"] = documentation_complete_for(claim["id"])
    return doc


# --- calculation: surveyor_window_conflict ---------------------------------
def window_minutes_of(start_at, end_at):
    return int((end_at - start_at).total_seconds() // 60)


def check_window_conflict(surveyor, start_at, end_at):
    buffer_minutes = surveyor["travel_buffer_minutes"]
    for order in db.survey_orders.values():
        if order["surveyor_id"] != surveyor["id"]:
            continue
        if order["status"] not in ("APPOINTED", "REPORT_FILED"):
            continue
        inflated_end = clock.plus_minutes(order["window_end_at"], buffer_minutes)
        inflated_start = clock.plus_minutes(order["window_start_at"], -buffer_minutes)
        if start_at <= inflated_end and end_at >= inflated_start:
            raise ApiError("ERR_SURVEYOR_WINDOW_CONFLICT")


# --- calculation: ga_contribution_allocation --------------------------------
def ga_contributors(event):
    return ordered([c for c in db.certificates.values()
                    if c["vessel_id"] == event["vessel_id"]
                    and c["sailing_date"] == event["voyage_sailing_date"]
                    and c["status"] in ("ISSUED", "CLAIMED")])


def allocate_ga_contributions(event, contributors):
    fee = q2(GA_ADJUSTER_FEE_PCT * (D(event["sacrifice_amount"])
                                    + D(event["salvage_award_amount"])))
    total_allowance = q2(D(event["sacrifice_amount"]) + D(event["salvage_award_amount"]) + fee)
    total_contributory = q2(sum((D(c["insured_value"]) for c in contributors), ZERO))
    rate = q6(total_allowance / total_contributory)

    raw = {c["id"]: q2(D(c["insured_value"]) * rate) for c in contributors}
    residual = q2(total_allowance - q2(sum(raw.values(), ZERO)))
    # residual waterfall: contributory value DESC, ties broken by created_at ASC
    waterfall = sorted(contributors,
                       key=lambda c: (-D(c["insured_value"]), c["created_at"], c["_seq"]))
    amounts = dict(raw)
    if waterfall:
        first = waterfall[0]["id"]
        amounts[first] = q2(amounts[first] + residual)

    event["adjuster_fee_amount"] = fee
    event["total_allowance_amount"] = total_allowance
    event["total_contributory_value"] = total_contributory
    event["contribution_rate"] = rate
    return amounts


def create_ga_postings(event, contributors, amounts):
    created = []
    for cert in contributors:
        contribution = amounts[cert["id"]]
        required = contribution > GA_CASH_DEPOSIT_THRESHOLD
        expected = q2(contribution * GA_CASH_DEPOSIT_PCT) if required else ZERO
        posting = new_row()
        posting.update({
            "ga_event_id": event["id"],
            "certificate_id": cert["id"],
            "contributory_value": q2(cert["insured_value"]),
            "contribution_amount": contribution,
            "cash_deposit_required": required,
            "cash_deposit_expected_amount": expected,
            "guarantee_amount": None,
            "cash_deposit_amount": None,
            "status": "REQUIRED",
        })
        db.ga_postings[posting["id"]] = posting
        cert["ga_contribution_amount"] = contribution
        touch(cert)
        created.append(posting)
    return created


# --- cascade: POST /ports/{id}/war-risk-tier (PRD 3.6) ----------------------
def listed_area_cascade(port):
    """Links 2..5 of the re-tier cascade; only fires when the new tier is LISTED_AREA."""
    for policy in ordered(list(db.open_policies.values())):
        if policy["war_cover_status"] not in ("ATTACHED", "REINSTATED"):
            continue
        exposed = [c for c in certificates_of_policy(policy["id"])
                   if c["status"] == "ISSUED"
                   and (c["loading_port_id"] == port["id"]
                        or c["discharge_port_id"] == port["id"])]
        if not exposed:
            continue  # a policy with no exposed issued certificate is left untouched
        policy["war_cover_status"] = "TERMINATED"
        policy["war_terminated_at"] = clock.now()
        policy["war_termination_port_unlocode"] = port["unlocode"]

        returns_total = ZERO
        touched_declarations = []
        for cert in exposed:
            if cert["war_cover_status"] not in ("ATTACHED", "REINSTATED"):
                continue
            delta = war_termination_return(cert)
            cert["war_cover_status"] = "TERMINATED"
            cert["return_premium_amount"] = q2(D(cert["return_premium_amount"]) + delta)
            touch(cert)
            returns_total += delta
            declaration_id = cert["premium_declaration_id"]
            if declaration_id:
                declaration = db.premium_declarations.get(declaration_id)
                if (declaration is not None
                        and declaration["status"] in ("SUBMITTED", "UNDER_AUDIT")
                        and declaration["id"] not in touched_declarations):
                    touched_declarations.append(declaration["id"])
        policy["aggregate_return_premium"] = q2(
            D(policy["aggregate_return_premium"]) + returns_total)
        touch(policy)
        for declaration_id in touched_declarations:
            recompute_declaration_totals(db.premium_declarations[declaration_id])


# --- cascade: POST /open-policies/{id}/reinstate-war-cover ------------------
def reinstate_cascade(policy):
    rate = D(policy["reinstatement_rate_per_mille"])
    booked = ZERO
    for cert in certificates_of_policy(policy["id"]):
        if cert["status"] != "ISSUED" or cert["war_cover_status"] != "TERMINATED":
            continue
        loading = db.ports[cert["loading_port_id"]]
        discharge = db.ports[cert["discharge_port_id"]]
        if (loading["war_risk_tier"] == "LISTED_AREA"
                or discharge["war_risk_tier"] == "LISTED_AREA"):
            continue  # still touching a listed port: stays TERMINATED, charged nothing
        amount = q2(D(cert["insured_value"]) / Decimal(1000) * rate)
        cert["war_cover_status"] = "REINSTATED"
        cert["reinstatement_premium_amount"] = amount
        touch(cert)
        booked += amount
    policy["aggregate_premium_booked"] = q2(D(policy["aggregate_premium_booked"]) + booked)


# --- cascade: POST /open-policies/{id}/run-transit-sweep --------------------
def _claim_in_loop(certificate_id):
    loop = ("OPENED", "SURVEY_ORDERED", "SURVEY_RECEIVED", "DOCS_INCOMPLETE")
    return any(cl["certificate_id"] == certificate_id and cl["status"] in loop
               for cl in db.claim_files.values())


def run_transit_sweep(policy):
    now = clock.now()
    for cert in certificates_of_policy(policy["id"]):
        if cert["status"] not in ("ISSUED", "CLAIMED"):
            continue
        if cert["transit_termination_at"] is None or now < cert["transit_termination_at"]:
            continue
        if _claim_in_loop(cert["id"]):
            continue
        cert["status"] = "TRANSIT_ENDED"
        release_exposure(cert, "TRANSIT_ENDED")
        touch(cert)
    if policy["status"] == "ACTIVE" and now >= policy["expiry_at"]:
        policy["status"] = "EXPIRED"
