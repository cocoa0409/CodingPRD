"""Domain constants and the calculation rules."""

import store
import util

# --- constants --------------------------------------------------------------
BALLOT_OVERAGE_NUM = 11
BALLOT_OVERAGE_DEN = 10

FREIGHT_TIER_1_MAX = 50000
FREIGHT_TIER_1_CENTS = 45000
FREIGHT_TIER_2_MAX = 200000
FREIGHT_TIER_2_CENTS = 90000
FREIGHT_TIER_3_CENTS = 150000

QC_HOLD_THRESHOLD_BP = 150

SPOILAGE_TIER_MAX = 5000
SPOILAGE_ALLOWANCE_SMALL_BP = 25
SPOILAGE_ALLOWANCE_LARGE_BP = 15
TOLERANCE_TIER_1_MAX = 5000
TOLERANCE_TIER_2_MAX = 20000
TOLERANCE_SMALL_BP = 200
TOLERANCE_MEDIUM_BP = 100
TOLERANCE_LARGE_BP = 50

LINES_PER_FACE = 40

SESSION_EARLY_START_MINUTES = 60
SETUP_BUFFER_MINUTES = 30
MIN_PUBLIC_OBSERVERS = 2
MIN_AUDIT_OBSERVERS = 1

# --- enums ------------------------------------------------------------------
ELECTION_PHASES = ("SETUP", "CONTESTS_CERTIFIED", "STYLES_LOCKED", "DEPLOYED",
                   "POLLS_CLOSED", "RECONCILED")
ROTATION_POLICIES = ("NONE", "PRECINCT_ROTATION", "DISTRICT_ROTATION")
CANDIDATE_ORDER_METHODS = ("ALPHABETICAL_BY_BALLOT_NAME", "FILING_ORDER")
CONTEST_TYPES = ("CANDIDATE", "MEASURE")
LAYOUT_BASES = ("PROVISIONAL_BASIS", "CERTIFIED_BASIS")
RECONCILIATION_BASES = ("PRELIMINARY", "FINAL_CANVASS")
SESSION_TYPES = ("PRE_ELECTION_PUBLIC", "POST_ELECTION_AUDIT")
BALLOT_FORMATS = ("PAPER_STANDARD", "LARGE_PRINT", "AUDIO_BALLOT",
                  "BRAILLE_INDEX", "ELECTRONIC_DISPLAY")
CONTEST_TYPE_RANK = {"CANDIDATE": 0, "MEASURE": 1}


# --- contest_ballot_ordering ------------------------------------------------

def contest_sort_key(contest):
    return (
        CONTEST_TYPE_RANK.get(contest["contest_type"], 99),
        contest["district_code"],
        contest["title"],
        contest["created_at"],
        contest["_seq"],
    )


def ordered_certified_contests(election_id):
    rows = [c for c in store.contests_of(election_id) if c["status"] == "CERTIFIED"]
    rows.sort(key=contest_sort_key)
    return rows


# --- candidate_ballot_order -------------------------------------------------

PROVISIONAL_STATUSES = ("FILED", "CERTIFIED", "DISQUALIFIED")


def candidate_sort_key(candidate, method):
    if method == "FILING_ORDER":
        return (candidate["filing_received_at"], candidate["ballot_name"],
                candidate["created_at"], candidate["_seq"])
    return (candidate["ballot_name"], candidate["filing_received_at"],
            candidate["created_at"], candidate["_seq"])


def ordered_candidates(contest, election, basis):
    rows = store.candidates_of(contest["id"])
    if basis == "CERTIFIED_BASIS":
        rows = [c for c in rows if c["status"] == "CERTIFIED"]
    else:
        rows = [c for c in rows if c["status"] in PROVISIONAL_STATUSES]
    rows.sort(key=lambda c: candidate_sort_key(c, election["candidate_order_method"]))
    return rows


def rotation_group(election, contest, style, n):
    """The rotation offset g for one (style, contest) pair."""
    if n == 0:
        return 0
    policy = election["rotation_policy"]
    if policy == "NONE":
        return 0
    if not contest.get("rotation_required"):
        return 0
    seed = style.get("rotation_seed_index") or 0
    if policy == "PRECINCT_ROTATION":
        return seed % n
    if policy == "DISTRICT_ROTATION":
        codes = sorted(style["district_codes"])
        if contest["district_code"] not in codes:
            return 0
        d = codes.index(contest["district_code"])
        return (seed + d) % n
    return 0


def contest_layout(election, contest, style, basis):
    """{candidate_id, ballot_name, base_order_index, printed_position} in printed order."""
    roster = ordered_candidates(contest, election, basis)
    n = len(roster)
    g = rotation_group(election, contest, style, n)
    entries = []
    for base_index, candidate in enumerate(roster):
        entries.append({
            "candidate_id": candidate["id"],
            "ballot_name": candidate["ballot_name"],
            "base_order_index": base_index,
            "printed_position": ((base_index + g) % n) + 1 if n else None,
        })
    entries.sort(key=lambda e: e["printed_position"])
    return entries, g, n


# --- precinct_ballot_requirement -------------------------------------------

def required_ballot_quantity(registered_voter_count):
    return util.ceil_div(registered_voter_count * BALLOT_OVERAGE_NUM, BALLOT_OVERAGE_DEN)


def precinct_ballots_received(precinct_id):
    total = 0
    for lot in store.lots_of_precinct(precinct_id):
        if lot["custody_state"] in ("ISSUED", "RETURNED"):
            total += lot["issued_quantity"] or 0
    return total


# --- print_job_invoice_total -----------------------------------------------

def freight_cents(billing_quantity):
    if billing_quantity <= FREIGHT_TIER_1_MAX:
        return FREIGHT_TIER_1_CENTS
    if billing_quantity <= FREIGHT_TIER_2_MAX:
        return FREIGHT_TIER_2_CENTS
    return FREIGHT_TIER_3_CENTS


def invoice(job, basis):
    """Returns the invoice component dict for the requested variant."""
    rate = job["unit_cost_cents_per_thousand"]
    if basis == "ESTIMATE":
        subtotal = util.round_half_up(job["quantity_ordered"] * rate, 1000)
        delivered_quantity = 0
        billing_quantity = job["quantity_ordered"]
        credit = 0
    else:
        lots = [l for l in store.lots_of_job(job["id"]) if l["custody_state"] != "VOIDED"]
        lots.sort(key=lambda l: (l["lot_code"], l["created_at"], l["_seq"]))
        subtotal = 0
        delivered_quantity = 0
        for lot in lots:
            subtotal += util.round_half_up(lot["quantity_shipped"] * rate, 1000)
            delivered_quantity += lot["quantity_shipped"]
        billing_quantity = delivered_quantity
        credit = util.round_half_up(subtotal * (job.get("defect_rate_bp") or 0), 10000)
    freight = freight_cents(billing_quantity)
    return {
        "invoice_basis": basis,
        "invoice_subtotal_cents": subtotal,
        "delivered_quantity": delivered_quantity,
        "freight_cents": freight,
        "defect_credit_cents": credit,
        "invoice_total_cents": subtotal + freight - credit,
    }


# --- ballot_accountability_reconciliation ----------------------------------

def accountability(election_id, basis):
    lots = store.lots_of_election(election_id)
    if basis == "FINAL_CANVASS":
        lots = [l for l in lots if l["custody_state"] == "RETURNED"]
    else:
        lots = [l for l in lots if l["custody_state"] in ("ISSUED", "RETURNED")]
    gross_issued = sum((l["issued_quantity"] or 0) for l in lots)
    allowance_bp = (SPOILAGE_ALLOWANCE_SMALL_BP if gross_issued <= SPOILAGE_TIER_MAX
                    else SPOILAGE_ALLOWANCE_LARGE_BP)
    spoilage_credit = util.floor_div(gross_issued * allowance_bp, 10000)
    net_issued = gross_issued - spoilage_credit
    accounted = sum((l["accounted_quantity"] or 0) for l in lots)
    gross_variance = gross_issued - accounted
    net_variance = gross_variance - spoilage_credit if gross_variance > 0 else gross_variance
    if net_issued <= TOLERANCE_TIER_1_MAX:
        tolerance_bp = TOLERANCE_SMALL_BP
    elif net_issued <= TOLERANCE_TIER_2_MAX:
        tolerance_bp = TOLERANCE_MEDIUM_BP
    else:
        tolerance_bp = TOLERANCE_LARGE_BP
    tolerance_ballots = util.floor_div(net_issued * tolerance_bp, 10000)
    status = "BALANCED" if abs(net_variance) <= tolerance_ballots else "OUT_OF_BALANCE"
    return {
        "basis": basis,
        "lot_count": len(lots),
        "gross_issued": gross_issued,
        "allowance_bp": allowance_bp,
        "spoilage_credit": spoilage_credit,
        "net_issued": net_issued,
        "accounted": accounted,
        "gross_variance": gross_variance,
        "net_variance": net_variance,
        "tolerance_bp": tolerance_bp,
        "tolerance_ballots": tolerance_ballots,
        "ballot_accountability_status": status,
    }


# --- la_test_discrepancy ---------------------------------------------------

def discrepancy(deck, reported_marks, reported_blank_count, reported_overvote_count):
    expected = {}
    for mark in deck["expected_marks"]:
        key = (mark["contest_id"], mark["candidate_id"])
        expected[key] = expected.get(key, 0) + mark["mark_count"]
    reported = {}
    for mark in reported_marks:
        key = (mark["contest_id"], mark["candidate_id"])
        reported[key] = reported.get(key, 0) + mark["mark_count"]
    mark_delta = 0
    for key in sorted(set(expected) | set(reported)):
        mark_delta += abs(reported.get(key, 0) - expected.get(key, 0))
    total = mark_delta
    total += abs(reported_blank_count - (deck["blank_count"] or 0))
    total += abs(reported_overvote_count - (deck["overvote_count"] or 0))
    return total


# --- election_deployment_readiness ----------------------------------------

def precinct_deployment_status(precinct, ballots_received):
    if ballots_received < (precinct["required_ballot_quantity"] or 0):
        return "NOT_READY"
    for unit in store.units_of_precinct(precinct["id"]):
        if unit["program_status"] == "LA_PASSED" and unit["custody_status"] == "DEPLOYED":
            return "READY"
    return "NOT_READY"
