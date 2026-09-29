"""Domain services: lookups, derived-field refreshes and cascades."""
from decimal import Decimal, ROUND_FLOOR

import calculations as calc
from clock import days
from db import base_record, db, now, ordered, touch
from errors import ApiError

INVENTORY_CUSTODY = ("ACQUIRED", "LISTED", "REVERTED")


# ----------------------------------------------------------------- lookups --

def _find(collection, record_id, error_id):
    if not isinstance(record_id, str) or record_id == "":
        raise ApiError(error_id)
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_property(record_id):
    return _find(db.properties, record_id, "ERR_PROPERTY_NOT_FOUND")


def get_funding_source(record_id):
    return _find(db.funding_sources, record_id, "ERR_FUNDING_SOURCE_NOT_FOUND")


def get_packet(record_id):
    return _find(db.packets, record_id, "ERR_PACKET_NOT_FOUND")


def get_title_action(record_id):
    return _find(db.title_actions, record_id, "ERR_TITLE_ACTION_NOT_FOUND")


def get_contractor(record_id):
    return _find(db.contractors, record_id, "ERR_CONTRACTOR_NOT_FOUND")


def get_order(record_id):
    return _find(db.orders, record_id, "ERR_ORDER_NOT_FOUND")


def get_run(record_id):
    return _find(db.runs, record_id, "ERR_RUN_NOT_FOUND")


def get_applicant(record_id):
    return _find(db.applicants, record_id, "ERR_APPLICANT_NOT_FOUND")


def get_application(record_id):
    return _find(db.applications, record_id, "ERR_APPLICATION_NOT_FOUND")


def get_agreement(record_id):
    return _find(db.agreements, record_id, "ERR_AGREEMENT_NOT_FOUND")


# --------------------------------------------------------- adjacency graph --

def neighbour_ids(property_id):
    ids = []
    for edge in ordered(list(db.adjacencies.values())):
        if edge["property_id"] == property_id:
            other = edge["adjacent_property_id"]
        elif edge["adjacent_property_id"] == property_id:
            other = edge["property_id"]
        else:
            continue
        if other not in ids:
            ids.append(other)
    return ids


def inventory_neighbour_count(property_id):
    count = 0
    for other_id in neighbour_ids(property_id):
        other = db.properties.get(other_id)
        if other is not None and other["custody_status"] in INVENTORY_CUSTODY:
            count += 1
    return count


def owns_adjacent_parcel(applicant_id, property_id):
    """True when an edge of >= 20 shared feet links the parcel to one the
    applicant owns of record (either direction)."""
    minimum = calc.SIDE_LOT_MIN_SHARED_BOUNDARY_FEET
    for edge in db.adjacencies.values():
        if Decimal(str(edge["shared_boundary_feet"])) < minimum:
            continue
        if edge["property_id"] == property_id:
            other_id = edge["adjacent_property_id"]
        elif edge["adjacent_property_id"] == property_id:
            other_id = edge["property_id"]
        else:
            continue
        other = db.properties.get(other_id)
        if other is not None and other["owner_of_record_applicant_id"] == applicant_id:
            return True
    return False


# ------------------------------------------------------------ blight score --

def blight_score_for(prop):
    return calc.blight_priority_score(
        prop, "SWEEP_FINAL", now(), inventory_neighbour_count(prop["id"])
    )


def refresh_blight(prop, bump_version=True):
    """Recompute current_blight_score with the live (SWEEP_FINAL) variant."""
    score = blight_score_for(prop)
    prop["current_blight_score"] = score
    if bump_version:
        touch(prop)
    return score


def stamp_intake_score(prop):
    prop["intake_blight_score"] = calc.blight_priority_score(
        prop, "INTAKE_PROVISIONAL", now(), inventory_neighbour_count(prop["id"])
    )


# ---------------------------------------------------------- funding ledger --

def packets_of(funding_source_id):
    return [p for p in db.packets.values() if p["funding_source_id"] == funding_source_id]


def orders_of_source(funding_source_id):
    return [o for o in db.orders.values() if o["funding_source_id"] == funding_source_id]


def runs_of_source(funding_source_id):
    return [r for r in db.runs.values() if r["funding_source_id"] == funding_source_id]


def recompute_ledger(fs):
    committed = 0
    disbursed = 0
    for packet in packets_of(fs["id"]):
        if packet["status"] == "BOARD_APPROVED":
            committed += packet["committed_cents"]
        elif packet["status"] == "CLOSED":
            disbursed += packet["offer_price_cents"] + packet["title_search_fee_cents"]
    for order in orders_of_source(fs["id"]):
        if order["status"] == "SCHEDULED":
            committed += order["estimated_cost_cents"]
        elif order["status"] == "COMPLETED":
            disbursed += order["actual_cost_cents"] or 0
    for run in runs_of_source(fs["id"]):
        if run["status"] == "EXECUTED":
            committed += run["admin_fee_cents"]
    fs["committed_cents"] = committed
    fs["disbursed_cents"] = disbursed
    fs["available_cents"] = fs["authorized_cents"] - committed - disbursed
    fs["reserve_floor_cents"] = calc.reserve_floor_cents(fs["authorized_cents"])


def _park_packets(fs):
    for packet in ordered(packets_of(fs["id"])):
        if packet["status"] == "DUE_DILIGENCE":
            packet["status"] = "ON_HOLD_FUNDING"
            packet["hold_reason"] = "FUNDING_SOURCE_CONSTRAINED"
            touch(packet)


def _release_packets(fs):
    for packet in ordered(packets_of(fs["id"])):
        if packet["status"] == "ON_HOLD_FUNDING":
            packet["status"] = "DUE_DILIGENCE"
            packet["hold_reason"] = None
            touch(packet)


def apply_reserve_floor(fs):
    if fs["status"] == "ACTIVE" and fs["available_cents"] < fs["reserve_floor_cents"]:
        fs["status"] = "CONSTRAINED"
        _park_packets(fs)
    elif fs["status"] == "CONSTRAINED" and fs["available_cents"] >= fs["reserve_floor_cents"]:
        fs["status"] = "ACTIVE"
        _release_packets(fs)


def refresh_funding(fs, bump_version=True):
    recompute_ledger(fs)
    apply_reserve_floor(fs)
    if bump_version:
        touch(fs)


def restriction_admits(fs, category, work_type=None):
    """category is one of 'ACQUISITION', 'MAINTENANCE', 'DEMOLITION_RUN'."""
    restriction = fs["restriction"]
    if restriction == "ANY":
        return True
    if category == "ACQUISITION":
        return restriction == "ACQUISITION_ONLY"
    if category == "DEMOLITION_RUN":
        return restriction == "DEMOLITION_ONLY"
    # maintenance order
    if restriction == "ACQUISITION_ONLY":
        return False
    return work_type == "DEMOLITION"


# ------------------------------------------------------------- applicants ---

def owned_parcels(applicant_id):
    """Parcels in the eligibility roll-up: owned of record and PROSPECT or
    CONVEYED (a reverted parcel is back with the land bank)."""
    return [
        p for p in ordered(list(db.properties.values()))
        if p["owner_of_record_applicant_id"] == applicant_id
        and p["custody_status"] in ("PROSPECT", "CONVEYED")
    ]


def agreements_of_applicant(applicant_id):
    result = []
    for agreement in db.agreements.values():
        application = db.applications.get(agreement["application_id"])
        if application is not None and application["applicant_id"] == applicant_id:
            result.append(agreement)
    return result


def applicant_rollup(applicant_id):
    parcels = owned_parcels(applicant_id)
    delinquent = sum(p["delinquent_tax_balance_cents"] for p in parcels)
    violations = sum(p["open_code_violation_count"] for p in parcels)
    conveyed = len([p for p in parcels if p["custody_status"] == "CONVEYED"])
    cutoff = now() - days(calc.REVERTER_LOOKBACK_DAYS)
    recent = 0
    for agreement in agreements_of_applicant(applicant_id):
        if agreement["status"] == "REVERTED" and agreement["reverted_at"] is not None:
            if agreement["reverted_at"] >= cutoff:
                recent += 1
    return {
        "delinquent_tax_total_cents": delinquent,
        "open_code_violation_total": violations,
        "conveyed_property_count": conveyed,
        "recent_reverter_count": recent,
    }


def eligibility_status_for(rollup):
    if (
        rollup["delinquent_tax_total_cents"] > 0
        or rollup["open_code_violation_total"] >= calc.CODE_VIOLATION_BAR
        or rollup["recent_reverter_count"] >= 1
    ):
        return "BARRED"
    return "ELIGIBLE"


def refresh_applicant(applicant, force=False):
    """Recompute the roll-ups; bump the version only when something moved."""
    rollup = applicant_rollup(applicant["id"])
    status = eligibility_status_for(rollup)
    changed = force
    for key, value in rollup.items():
        if applicant.get(key) != value:
            changed = True
        applicant[key] = value
    if applicant.get("eligibility_status") != status:
        changed = True
    applicant["eligibility_status"] = status
    if changed:
        touch(applicant)
    return rollup


def refresh_owner_of(prop, force=False):
    owner_id = prop.get("owner_of_record_applicant_id")
    if owner_id:
        applicant = db.applicants.get(owner_id)
        if applicant is not None:
            refresh_applicant(applicant, force=force)


# ------------------------------------------------------- disposition gates --

PROGRAM_TYPE = {
    "SIDE_LOT": "INDIVIDUAL",
    "HOMEOWNER_SALE": "INDIVIDUAL",
    "DEVELOPER_RFP": "DEVELOPER",
    "COMMUNITY_USE": "NONPROFIT",
}


def hearings_of(property_id):
    return [h for h in db.hearings.values() if h["property_id"] == property_id]


def governing_hearing(property_id):
    hearings = hearings_of(property_id)
    if not hearings:
        return None
    return sorted(
        hearings, key=lambda h: (h["hearing_at"], h["created_at"], h["_seq"])
    )[-1]


def screenings_of(application_id):
    return sorted(
        [s for s in db.screenings.values() if s["application_id"] == application_id],
        key=lambda s: s["sequence_no"],
    )


def governing_screening(application_id):
    rows = screenings_of(application_id)
    return rows[-1] if rows else None


def run_submit_gate(application, prop, applicant, offer_price_cents, is_resubmit):
    """The shared submission ladder of PRD 3.7 / 3.8 in its pinned order."""
    if prop["custody_status"] != "LISTED":
        raise ApiError("ERR_PROPERTY_NOT_LISTED")

    rollup = applicant_rollup(applicant["id"])
    if rollup["delinquent_tax_total_cents"] > 0:
        raise ApiError("ERR_APPLICANT_TAX_DELINQUENT")
    if rollup["open_code_violation_total"] >= calc.CODE_VIOLATION_BAR:
        raise ApiError("ERR_APPLICANT_CODE_VIOLATOR")

    program = application["program"]
    if applicant["applicant_type"] != PROGRAM_TYPE[program]:
        raise ApiError("ERR_APPLICANT_TYPE_NOT_ELIGIBLE")
    if program == "COMMUNITY_USE" and not applicant.get("nonprofit_registration_no"):
        raise ApiError("ERR_NONPROFIT_REGISTRATION_REQUIRED")
    if program == "SIDE_LOT":
        if prop["structure_present"]:
            raise ApiError("ERR_SIDE_LOT_REQUIRES_VACANT")
        if not owns_adjacent_parcel(applicant["id"], prop["id"]):
            raise ApiError("ERR_NOT_ADJACENT_OWNER")

    if program == "COMMUNITY_USE":
        hearing = governing_hearing(prop["id"])
        if hearing is None or (now() - hearing["hearing_at"]) > days(calc.HEARING_VALIDITY_DAYS):
            raise ApiError("ERR_HEARING_STALE")
        if hearing["comment_count"] < calc.HEARING_QUORUM_COMMENTS:
            raise ApiError("ERR_HEARING_SUPPORT_INSUFFICIENT")
        if Decimal(str(hearing["support_ratio"])) < calc.HEARING_SUPPORT_MIN_RATIO:
            raise ApiError("ERR_HEARING_SUPPORT_INSUFFICIENT")

    quote = calc.quoted_price_cents(prop, program)
    if offer_price_cents < quote:
        raise ApiError("ERR_OFFER_BELOW_QUOTE")

    if is_resubmit and application["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")

    if program == "HOMEOWNER_SALE":
        if rollup["conveyed_property_count"] >= calc.HOMEOWNER_MAX_CONVEYED:
            raise ApiError("ERR_HOMEOWNER_LIMIT_EXCEEDED")

    return quote


def evaluate_screening(application, prop, applicant):
    rollup = applicant_rollup(applicant["id"])
    disqualifiers = []
    if rollup["delinquent_tax_total_cents"] > 0:
        disqualifiers.append("DELINQUENT_TAXES")
    if rollup["open_code_violation_total"] >= calc.CODE_VIOLATION_BAR:
        disqualifiers.append("CODE_VIOLATIONS")
    if rollup["recent_reverter_count"] >= 1:
        disqualifiers.append("RECENT_REVERTER")
    if application["program"] == "COMMUNITY_USE" and not applicant.get("nonprofit_registration_no"):
        disqualifiers.append("NONPROFIT_REGISTRATION_MISSING")
    if application["program"] == "SIDE_LOT" and not owns_adjacent_parcel(
        applicant["id"], prop["id"]
    ):
        disqualifiers.append("NOT_ADJACENT_OWNER")
    quote = calc.quoted_price_cents(prop, application["program"])
    if application["offer_price_cents"] < quote:
        disqualifiers.append("INSUFFICIENT_OFFER")
    return {
        "rollup": rollup,
        "disqualifiers": disqualifiers,
        "eligibility_score": calc.eligibility_score(len(disqualifiers)),
        "outcome": "PASS" if not disqualifiers else "FAIL",
    }


def restore_suspended_applications(property_id):
    """PRD 3.4: a clearing adjudication releases the parcel's suspended
    applications back to the status they held."""
    for application in ordered(list(db.applications.values())):
        if application["property_id"] != property_id:
            continue
        if application["status"] != "SUSPENDED_TITLE":
            continue
        target = application.get("suspended_from_status") or "SUBMITTED"
        application["status"] = target
        application["suspended_from_status"] = None
        touch(application)


def suspend_applications(property_id):
    for application in ordered(list(db.applications.values())):
        if application["property_id"] != property_id:
            continue
        if application["status"] in ("SUBMITTED", "SCREENED", "RECOMMENDED"):
            application["suspended_from_status"] = application["status"]
            application["status"] = "SUSPENDED_TITLE"
            touch(application)


# -------------------------------------------------------- maintenance work --

def orders_of_property(property_id):
    return [o for o in db.orders.values() if o["property_id"] == property_id]


def intersects(a_start, a_end, b_start, b_end):
    """Half-open intersection: each interval starts strictly before the other
    ends."""
    return a_start < b_end and b_start < a_end


def has_demolition_order(property_id):
    for order in orders_of_property(property_id):
        if order["work_type"] == "DEMOLITION" and order["status"] in ("SCHEDULED", "COMPLETED"):
            return True
    return False


# --------------------------------------------------- demolition allocation --

def _candidate_pool(ward_filter, bump_version=False):
    candidates = []
    for prop in ordered(list(db.properties.values())):
        if prop["custody_status"] not in ("ACQUIRED", "LISTED"):
            continue
        if prop["title_status"] != "CLEAR":
            continue
        if not prop["structure_present"]:
            continue
        if has_demolition_order(prop["id"]):
            continue
        if ward_filter is not None and prop["situs_ward"] != ward_filter:
            continue
        refresh_blight(prop, bump_version=bump_version)
        if Decimal(str(prop["current_blight_score"])) < calc.MIN_SCORE_THRESHOLD:
            continue
        candidates.append(prop)
    return candidates


def allocate_run(budget_cents, ward_filter):
    candidates = _candidate_pool(ward_filter)
    ranked = sorted(
        candidates,
        key=lambda p: (
            -Decimal(str(p["current_blight_score"])),
            -p["lot_area_sqft"],
            p["created_at"],
            p["_seq"],
        ),
    )
    provisional_cap = int(
        (Decimal(budget_cents) / (Decimal(1) + calc.ADMIN_RATE)).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    remaining = provisional_cap
    selected = []
    skipped = []
    estimates = {}
    for prop in ranked:
        if len(selected) >= calc.MAX_PROPERTIES_PER_RUN:
            skipped.append(prop["id"])
            continue
        cost = calc.demolition_estimate(prop)
        if cost <= remaining:
            selected.append(prop["id"])
            estimates[prop["id"]] = cost
            remaining -= cost
        else:
            skipped.append(prop["id"])
    subtotal = sum(estimates[pid] for pid in selected)
    admin_fee = calc.rhu_int(calc.ADMIN_RATE * Decimal(subtotal))
    return {
        "provisional_cap_cents": provisional_cap,
        "selected_property_ids": selected,
        "skipped_property_ids": skipped,
        "properties_selected_count": len(selected),
        "skipped_property_count": len(skipped),
        "committed_subtotal_cents": subtotal,
        "admin_fee_cents": admin_fee,
        "total_committed_cents": subtotal + admin_fee,
        "_estimates": estimates,
    }


def create_run_order(run, prop, estimate):
    order = base_record()
    order.update({
        "property_id": prop["id"],
        "contractor_id": None,
        "funding_source_id": run["funding_source_id"],
        "demolition_run_id": run["id"],
        "work_type": "DEMOLITION",
        "window_start": now(),
        "window_end": now() + days(calc.DEMOLITION_WINDOW_DAYS),
        "openings_count": None,
        "estimated_cost_cents": estimate,
        "actual_cost_cents": None,
        "status": "SCHEDULED",
        "completed_at": None,
        "cancelled_reason": None,
    })
    db.orders[order["id"]] = order
    return order


# ------------------------------------------------------------------ sweep ---

def run_compliance_sweep():
    swept_at = now()
    funding_expired = 0
    cure_pending = 0
    reverted = 0
    waived = 0
    restored_sqft = 0

    # Step 1: expire lapsed funding sources.
    for fs in ordered(list(db.funding_sources.values())):
        if fs["status"] in ("ACTIVE", "CONSTRAINED") and fs["expires_on"] < swept_at:
            fs["status"] = "EXPIRED"
            touch(fs)
            funding_expired += 1

    # Step 2: open cure periods.
    for agreement in ordered(list(db.agreements.values())):
        if agreement["status"] != "EXECUTED":
            continue
        if agreement["milestones_completed"] >= agreement["milestone_count"]:
            continue
        if agreement["performance_deadline"] < swept_at:
            agreement["status"] = "CURE_PENDING"
            agreement["cure_deadline"] = agreement["performance_deadline"] + days(
                calc.CURE_PERIOD_DAYS
            )
            touch(agreement)
            cure_pending += 1

    # Step 3: enforce the reverter.
    for agreement in ordered(list(db.agreements.values())):
        if agreement["status"] != "CURE_PENDING":
            continue
        if agreement["milestones_completed"] >= agreement["milestone_count"]:
            continue
        if agreement["cure_deadline"] is None or agreement["cure_deadline"] >= swept_at:
            continue
        if not agreement["reverter_clause_active"]:
            waived += 1
            continue
        agreement["status"] = "REVERTED"
        agreement["reverted_at"] = swept_at
        touch(agreement)
        reverted += 1
        restored_sqft += _enforce_reverter(agreement)

    return {
        "swept_at": swept_at,
        "funding_expired_count": funding_expired,
        "cure_pending_count": cure_pending,
        "reverted_count": reverted,
        "waived_count": waived,
        "restored_inventory_sqft": restored_sqft,
    }


def _enforce_reverter(agreement):
    prop = db.properties.get(agreement["property_id"])
    application = db.applications.get(agreement["application_id"])
    applicant = None
    if application is not None:
        applicant = db.applicants.get(application["applicant_id"])
    restored = 0
    if prop is not None:
        prop["custody_status"] = "REVERTED"
        prop["owner_of_record_applicant_id"] = None
        prop["delinquent_tax_balance_cents"] = (
            prop["delinquent_tax_balance_cents"] + agreement["discharged_tax_cents"]
        )
        prop["title_status"] = "CLOUDED"
        refresh_blight(prop)
        restored = prop["lot_area_sqft"]
        suspend_applications(prop["id"])
    if applicant is not None:
        applicant["reverter_count"] = applicant["reverter_count"] + 1
        applicant["last_reverter_at"] = now()
        refresh_applicant(applicant, force=True)
        applicant["eligibility_status"] = "BARRED"
    return restored


# -------------------------------------------------------- inventory totals --

def inventory_summary(ward=None):
    inventory_count = 0
    inventory_area = 0
    conveyed_area = 0
    for prop in db.properties.values():
        if ward is not None and prop["situs_ward"] != ward:
            continue
        if prop["custody_status"] in INVENTORY_CUSTODY:
            inventory_count += 1
            inventory_area += prop["lot_area_sqft"]
        elif prop["custody_status"] == "CONVEYED":
            conveyed_area += prop["lot_area_sqft"]
    cure_pending = 0
    for agreement in db.agreements.values():
        if agreement["status"] != "CURE_PENDING":
            continue
        if ward is not None:
            prop = db.properties.get(agreement["property_id"])
            if prop is None or prop["situs_ward"] != ward:
                continue
        cure_pending += 1
    total_authorized = sum(f["authorized_cents"] for f in db.funding_sources.values())
    total_committed = sum(f["committed_cents"] for f in db.funding_sources.values())
    total_disbursed = sum(f["disbursed_cents"] for f in db.funding_sources.values())
    total_available = sum(f["available_cents"] for f in db.funding_sources.values())
    return {
        "inventory_property_count": inventory_count,
        "inventory_area_sqft": inventory_area,
        "conveyed_area_sqft": conveyed_area,
        "cure_pending_count": cure_pending,
        "total_authorized_cents": total_authorized,
        "total_committed_cents": total_committed,
        "total_disbursed_cents": total_disbursed,
        "total_available_cents": total_available,
    }
