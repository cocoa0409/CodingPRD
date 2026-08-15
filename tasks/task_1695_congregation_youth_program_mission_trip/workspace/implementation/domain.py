"""Domain logic: computed rollups, calculations, cascades, sweeps, serializers."""
from datetime import timedelta
from decimal import Decimal

from store import DB
from util import (
    fmt_clock,
    round_half_up_cents,
    trip_end_instant,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLES = ["ProgramDirector", "TripLeader", "Treasurer", "ScholarshipReviewer", "Guardian", "Chaperone"]

DESTINATION_TYPES = ["IN_STATE", "OUT_OF_STATE", "INTERNATIONAL"]
INSURANCE_TIERS = ["NONE", "DOMESTIC", "INTERNATIONAL"]  # ascending rank
INCOME_BRACKETS = ["BAND_A", "BAND_B", "BAND_C", "BAND_D", "UNDISCLOSED"]
FORM_TYPES = ["PARENTAL_CONSENT", "MEDICAL_RELEASE", "MEDIA_RELEASE", "CONDUCT_AGREEMENT"]
REQUIRED_FORM_TYPES = ["PARENTAL_CONSENT", "MEDICAL_RELEASE", "CONDUCT_AGREEMENT"]
PAYMENT_METHODS = ["CASH", "CHECK", "CARD_ONLINE"]
SEGMENT_TYPES = ["TRAVEL", "LODGING", "SERVICE", "MEAL", "FREE"]
ASSIGNMENT_ROLES = ["LEAD", "SUPPORT"]
SANCTIONS = ["SENT_HOME", "BARRED_FROM_FUTURE"]

TRIP_STATUSES = ["DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "ROSTER_LOCKED",
                 "IN_PROGRESS", "DEBRIEFED", "CANCELLED"]
REGISTRATION_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "WAITLISTED", "REJECTED",
                         "CONFIRMED", "WITHDRAWN", "DISMISSED", "CANCELLED", "COMPLETED"]
PAYMENT_STATUSES = ["PENDING_DEPOSIT", "PARTIALLY_PAID", "PAID_IN_FULL", "DELINQUENT", "REFUNDED"]
APPLICATION_STATUSES = ["UNDER_REVIEW", "APPROVED", "DENIED", "DISBURSED", "RESCINDED",
                        "RETURNED", "WITHDRAWN"]

REG_NON_TERMINAL = ["DRAFT", "SUBMITTED", "APPROVED", "WAITLISTED", "CONFIRMED"]
REG_TERMINAL = ["REJECTED", "WITHDRAWN", "DISMISSED", "CANCELLED", "COMPLETED"]
TRIP_PRE_LOCK = ["DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED"]

LATE_FEE_FLAT_CENTS = 2500
LATE_FEE_PCT = Decimal("0.05")
CARD_PCT = Decimal("0.029")
CARD_FLAT_CENTS = 30
CHECK_FLAT_CENTS = 25

INSURANCE_RANK = {"NONE": 0, "DOMESTIC": 1, "INTERNATIONAL": 2}
INCOME_BASE = {"BAND_A": 50, "BAND_B": 35, "BAND_C": 20, "BAND_D": 5, "UNDISCLOSED": 0}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def regs_of_trip(trip_id):
    return [r for r in DB.registrations.values() if r["trip_id"] == trip_id]


def account_of_registration(registration_id):
    for a in DB.fundraising_accounts.values():
        if a["registration_id"] == registration_id:
            return a
    return None


def forms_of_registration(registration_id):
    return [f for f in DB.consent_forms.values() if f["registration_id"] == registration_id]


def payments_of_registration(registration_id):
    return [p for p in DB.payments.values() if p["registration_id"] == registration_id]


def donations_of_account(account_id):
    return [d for d in DB.donations.values() if d["fundraising_account_id"] == account_id]


def applications_of_registration(registration_id):
    return [a for a in DB.scholarship_applications.values() if a["registration_id"] == registration_id]


def checks_of_chaperone(chaperone_id):
    return [c for c in DB.background_checks.values() if c["chaperone_id"] == chaperone_id]


def assignments_of_trip(trip_id):
    return [a for a in DB.chaperone_assignments.values() if a["trip_id"] == trip_id]


def program_of_trip(trip):
    return DB.programs.get(trip["program_id"])


# ---------------------------------------------------------------------------
# Recomputes (each bumps version/updated_at on the owner iff values changed)
# ---------------------------------------------------------------------------

def _apply_changes(collection, entity, changes):
    changed = False
    for k, v in changes.items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    if changed:
        DB.touch(collection, entity["id"])
    return changed


def recompute_trip(trip):
    """Recompute trip rollups from source data."""
    regs = regs_of_trip(trip["id"])
    seats = sum(1 for r in regs if r["registration_status"] in ("APPROVED", "CONFIRMED"))
    confirmed = sum(1 for r in regs if r["registration_status"] == "CONFIRMED")

    end_inst = trip_end_instant(trip["end_date"])
    cleared = 0
    for a in assignments_of_trip(trip["id"]):
        if a["status"] != "CONFIRMED":
            continue
        ok = False
        for chk in checks_of_chaperone(a["chaperone_id"]):
            if chk["status"] == "CLEARED" and chk.get("_expires_dt") is not None \
                    and chk["_expires_dt"] >= end_inst:
                ok = True
                break
        if ok:
            cleared += 1

    ratio = trip["chaperone_ratio"]
    required = -(-confirmed // ratio)  # integer ceiling
    lodging_total = sum(
        r["cost_cents"]
        for r in DB.lodging_reservations.values()
        if r["trip_id"] == trip["id"] and r["status"] == "CONFIRMED"
    )
    _apply_changes("trips", trip, {
        "seats_taken": seats,
        "confirmed_youth_count": confirmed,
        "cleared_chaperone_count": cleared,
        "required_cleared_chaperones": required,
        "ratio_compliant": cleared >= required,
        "lodging_cost_total_cents": lodging_total,
    })


def recompute_account(account):
    gross = 0
    fees = 0
    for d in donations_of_account(account["id"]):
        if d["status"] in ("RECEIVED", "APPLIED"):
            gross += d["amount_cents"]
            fees += d["fee_cents"]
    net = gross - fees
    available = net - account["credit_applied_cents"]
    goal_met = account["goal_cents"] > 0 and gross >= account["goal_cents"]
    _apply_changes("fundraising_accounts", account, {
        "raised_gross_cents": gross,
        "fee_total_cents": fees,
        "raised_net_cents": net,
        "available_credit_cents": available,
        "goal_met": goal_met,
    })


def recompute_program_fund(program):
    reserved = 0
    disbursed = 0
    for app in DB.scholarship_applications.values():
        reg = DB.registrations.get(app["registration_id"])
        if reg is None:
            continue
        trip = DB.trips.get(reg["trip_id"])
        if trip is None or trip["program_id"] != program["id"]:
            continue
        if app["status"] == "APPROVED":
            reserved += app["award_cents"]
        elif app["status"] == "DISBURSED":
            disbursed += app["award_cents"]
    _apply_changes("programs", program, {
        "scholarship_reserved_cents": reserved,
        "scholarship_disbursed_cents": disbursed,
        "scholarship_available_cents": program["scholarship_fund_total_cents"] - reserved - disbursed,
    })


def recompute_chaperone_screening(chaperone):
    best = None
    for chk in checks_of_chaperone(chaperone["id"]):
        if chk["status"] == "CLEARED" and chk.get("_expires_dt") is not None:
            if best is None or chk["_expires_dt"] > best:
                best = chk["_expires_dt"]
    _apply_changes("chaperones", chaperone, {
        "current_screening_expires_at": fmt_clock(best) if best else "",
    })


def registration_money(reg, trip, update_status=True):
    """Refresh covered_cents / amount_due_cents; optionally recompute payment_status."""
    covered = sum(
        p["amount_cents"] for p in payments_of_registration(reg["id"]) if p["status"] == "POSTED"
    )
    covered += reg["fundraising_credit_applied_cents"] + reg["scholarship_awarded_cents"]

    basis = reg["final_cost_share_cents"] if trip.get("_locked") else reg["provisional_cost_share_cents"]
    due_total = basis + reg["late_fees_total_cents"]
    amount_due = max(0, due_total - covered)

    changes = {"covered_cents": covered, "amount_due_cents": amount_due}

    if update_status and reg["payment_status"] != "REFUNDED":
        if reg["payment_status"] == "DELINQUENT":
            final_due = trip["_final_payment_due_dt"]
            if due_total > 0 and covered >= due_total:
                changes["payment_status"] = "PAID_IN_FULL"
            elif DB.clock_dt <= final_due and covered >= trip["deposit_cents"]:
                changes["payment_status"] = "PARTIALLY_PAID"
        else:
            if due_total > 0 and covered >= due_total:
                changes["payment_status"] = "PAID_IN_FULL"
            elif covered >= trip["deposit_cents"]:
                changes["payment_status"] = "PARTIALLY_PAID"
            else:
                changes["payment_status"] = "PENDING_DEPOSIT"

    _apply_changes("registrations", reg, changes)


def recompute_provisional_shares(trip):
    """Recompute provisional share + amount due for non-terminal registrations.

    Only valid pre-lock; callers must check trip status. Does NOT touch
    payment_status (spec lists only share/amount-due reconciliation).
    """
    if trip["status"] not in TRIP_PRE_LOCK:
        return
    share = trip["base_cost_cents"] + round_half_up_cents(
        trip["lodging_cost_total_cents"], trip["capacity_youth"]
    )
    for reg in regs_of_trip(trip["id"]):
        if reg["registration_status"] not in REG_NON_TERMINAL:
            continue
        if reg["provisional_cost_share_cents"] != share:
            reg["provisional_cost_share_cents"] = share
            # amount_due moves with the basis; payment_status is not recomputed here
            due_total = share + reg["late_fees_total_cents"]
            reg["amount_due_cents"] = max(0, due_total - reg["covered_cents"])
            DB.touch("registrations", reg["id"])


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def donation_fee(channel, amount_cents):
    if channel == "CASH":
        return 0
    if channel == "CHECK":
        return CHECK_FLAT_CENTS
    # CARD_ONLINE: percentage component rounded half-up BEFORE the flat add-on
    pct = int((CARD_PCT * Decimal(amount_cents)).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return pct + CARD_FLAT_CENTS


def compute_need_score(reg):
    participant = DB.participants.get(reg["participant_id"])
    trip = DB.trips.get(reg["trip_id"])
    if participant is None or trip is None:
        return 0
    score = INCOME_BASE.get(participant["annual_income_bracket"], 0)
    score += min(20, 5 * max(0, participant["household_size"] - 2))

    siblings = 0
    for other in regs_of_trip(trip["id"]):
        if other["id"] == reg["id"]:
            continue
        if other["registration_status"] not in ("APPROVED", "CONFIRMED"):
            continue
        op = DB.participants.get(other["participant_id"])
        if op is not None and op["family_key"] == participant["family_key"]:
            siblings += 1
    score += min(20, 10 * siblings)

    account = account_of_registration(reg["id"])
    if account is not None:
        recompute_account(account)
        if account["goal_cents"] > 0 and account["raised_gross_cents"] >= account["goal_cents"]:
            score += 10
        elif account["raised_gross_cents"] > 0:
            score += 5

    return min(100, score)


def compute_award_cents(app, reg, trip, program):
    """Pinned evaluation order: need_score -> basis -> need_cap -> min-chain."""
    need_score = compute_need_score(reg)
    cost_basis = reg["final_cost_share_cents"] if trip.get("_locked") else reg["provisional_cost_share_cents"]
    # need_cap = round_half_up(need_score/100 * max_award_pct_bp/10000 * cost_basis)
    numerator = Decimal(need_score) * Decimal(program["max_award_pct_bp"]) * Decimal(cost_basis)
    need_cap = int((numerator / Decimal(1000000)).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    award = min(
        app["requested_cents"],
        need_cap,
        program["per_registration_cap_cents"],
        program["scholarship_available_cents"],
    )
    return need_score, award


def compute_final_cost_shares(trip, confirmed_regs):
    """Waterfall: round-then-sum with signed remainder one cent at a time."""
    n = len(confirmed_regs)
    lodging = trip["lodging_cost_total_cents"]
    share = round_half_up_cents(lodging, n)
    delta = lodging - n * share
    step = 1 if delta > 0 else -1
    remaining = abs(delta)
    for reg in confirmed_regs:
        adj = 0
        if remaining > 0:
            adj = step
            remaining -= 1
        reg["final_cost_share_cents"] = trip["base_cost_cents"] + share + adj


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_registration_terminal(reg, trip, refund_payments, scholarship_mode):
    """Shared cascade for withdraw / dismiss / trip cancel.

    scholarship_mode: "withdraw" (DISBURSED -> RETURNED) or "dismiss" (retain DISBURSED).
    Closes account, voids forms, hops scholarship, optionally refunds payments.
    """
    account = account_of_registration(reg["id"])
    if account is not None and account["status"] == "OPEN":
        _apply_changes("fundraising_accounts", account, {"status": "CLOSED"})

    for form in forms_of_registration(reg["id"]):
        if form["status"] != "VOIDED":
            _apply_changes("consent_forms", form, {"status": "VOIDED"})

    program = program_of_trip(trip)
    for app in applications_of_registration(reg["id"]):
        if app["status"] == "UNDER_REVIEW":
            _apply_changes("scholarship_applications", app, {"status": "WITHDRAWN"})
        elif app["status"] == "APPROVED":
            _apply_changes("scholarship_applications", app, {"status": "RESCINDED"})
        elif app["status"] == "DISBURSED" and scholarship_mode == "withdraw":
            _apply_changes("scholarship_applications", app, {"status": "RETURNED"})
            if reg["scholarship_awarded_cents"] != 0:
                reg["scholarship_awarded_cents"] = 0
                DB.touch("registrations", reg["id"])
        if program is not None:
            recompute_program_fund(program)

    refunded_any = False
    if refund_payments:
        for p in payments_of_registration(reg["id"]):
            if p["status"] == "POSTED":
                _apply_changes("payments", p, {"status": "REFUNDED"})
                refunded_any = True
        registration_money(reg, trip, update_status=False)
        if refunded_any and reg["payment_status"] != "REFUNDED":
            reg["payment_status"] = "REFUNDED"
            DB.touch("registrations", reg["id"])
    else:
        registration_money(reg, trip, update_status=False)


def trip_cancel_cascade(trip):
    for reg in regs_of_trip(trip["id"]):
        if reg["registration_status"] not in REG_NON_TERMINAL:
            continue
        reg["registration_status"] = "CANCELLED"
        DB.touch("registrations", reg["id"])
        cascade_registration_terminal(reg, trip, refund_payments=True, scholarship_mode="withdraw")
    recompute_trip(trip)


# ---------------------------------------------------------------------------
# Sweeps (logical clock advance)
# ---------------------------------------------------------------------------

def delinquency_sweep():
    for reg in sorted(DB.registrations.values(), key=lambda r: r["_seq"]):
        if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
            continue
        trip = DB.trips.get(reg["trip_id"])
        if trip is None:
            continue
        registration_money(reg, trip, update_status=False)
        fired = False
        # Sweep A: deposit milestone
        if (not reg["deposit_late_fee_assessed"]
                and DB.clock_dt > trip["_deposit_due_dt"]
                and reg["covered_cents"] < trip["deposit_cents"]):
            amount_due = reg["amount_due_cents"]
            fee = max(LATE_FEE_FLAT_CENTS,
                      int((LATE_FEE_PCT * Decimal(amount_due)).quantize(Decimal("1"), rounding="ROUND_HALF_UP")))
            reg["late_fees_total_cents"] += fee
            reg["deposit_late_fee_assessed"] = True
            fired = True
        # Refresh amount due before sweep B
        basis = reg["final_cost_share_cents"] if trip.get("_locked") else reg["provisional_cost_share_cents"]
        reg["amount_due_cents"] = max(0, basis + reg["late_fees_total_cents"] - reg["covered_cents"])
        # Sweep B: final milestone
        if (not reg["final_late_fee_assessed"]
                and DB.clock_dt > trip["_final_payment_due_dt"]
                and reg["amount_due_cents"] > 0):
            amount_due = reg["amount_due_cents"]
            fee = max(LATE_FEE_FLAT_CENTS,
                      int((LATE_FEE_PCT * Decimal(amount_due)).quantize(Decimal("1"), rounding="ROUND_HALF_UP")))
            reg["late_fees_total_cents"] += fee
            reg["final_late_fee_assessed"] = True
            fired = True
        if fired:
            basis = reg["final_cost_share_cents"] if trip.get("_locked") else reg["provisional_cost_share_cents"]
            reg["amount_due_cents"] = max(0, basis + reg["late_fees_total_cents"] - reg["covered_cents"])
            reg["payment_status"] = "DELINQUENT"
            DB.touch("registrations", reg["id"])


def screening_expiry_sweep():
    for chk in sorted(DB.background_checks.values(), key=lambda c: c["_seq"]):
        if chk["status"] != "CLEARED":
            continue
        expires = chk.get("_expires_dt")
        if expires is None or DB.clock_dt < expires:
            continue
        chk["status"] = "EXPIRED"
        DB.touch("background_checks", chk["id"])
        chaperone_id = chk["chaperone_id"]
        affected_trips = set()
        for a in DB.chaperone_assignments.values():
            if a["chaperone_id"] != chaperone_id or a["status"] not in ("PROPOSED", "CONFIRMED"):
                continue
            trip = DB.trips.get(a["trip_id"])
            if trip is None:
                continue
            if trip_end_instant(trip["end_date"]) >= expires:
                a["status"] = "REMOVED"
                a["removal_reason"] = "AUTO_SCREENING"
                DB.touch("chaperone_assignments", a["id"])
                affected_trips.add(a["trip_id"])
        for tid in affected_trips:
            trip = DB.trips.get(tid)
            if trip is not None:
                recompute_trip(trip)
        chaperone = DB.chaperones.get(chaperone_id)
        if chaperone is not None:
            recompute_chaperone_screening(chaperone)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _public(entity, fields):
    return {k: entity[k] for k in fields}


PROGRAM_FIELDS = ["id", "name", "ministry_year", "status", "scholarship_fund_total_cents",
                  "scholarship_reserved_cents", "scholarship_disbursed_cents",
                  "scholarship_available_cents", "max_award_pct_bp",
                  "per_registration_cap_cents", "default_chaperone_ratio",
                  "code_of_conduct_text", "discipline_policy_text",
                  "created_at", "updated_at", "version"]

TRIP_FIELDS = ["id", "program_id", "name", "destination_name", "destination_type",
               "start_date", "end_date", "capacity_youth", "base_cost_cents",
               "deposit_cents", "chaperone_ratio", "required_insurance_tier",
               "registration_open_at", "registration_close_at", "deposit_due_at",
               "final_payment_due_at", "emergency_protocol_text", "status",
               "seats_taken", "confirmed_youth_count", "cleared_chaperone_count",
               "required_cleared_chaperones", "ratio_compliant",
               "lodging_cost_total_cents", "debrief_summary",
               "debrief_actual_participant_count", "debrief_incident_count",
               "debrief_lessons_learned", "debriefed_at",
               "created_at", "updated_at", "version"]

PARTICIPANT_FIELDS = ["id", "program_id", "family_key", "guardian_user_id", "first_name",
                      "last_name", "birth_date", "grade", "annual_income_bracket",
                      "household_size", "barred_until", "created_at", "updated_at", "version"]

REGISTRATION_FIELDS = ["id", "trip_id", "participant_id", "guardian_user_id",
                       "registration_status", "payment_status", "insurance_tier",
                       "provisional_cost_share_cents", "final_cost_share_cents",
                       "late_fees_total_cents", "covered_cents", "amount_due_cents",
                       "fundraising_credit_applied_cents", "scholarship_awarded_cents",
                       "conduct_acknowledged", "deposit_late_fee_assessed",
                       "final_late_fee_assessed", "dismiss_sanction", "dismiss_reason",
                       "created_at", "updated_at", "version"]

CONSENT_FORM_FIELDS = ["id", "registration_id", "form_type", "status", "signed_by_name",
                       "signed_at", "medical_notes", "reviewed_by_user_id",
                       "rejection_reason", "created_at", "updated_at", "version"]

ACCOUNT_FIELDS = ["id", "registration_id", "status", "goal_cents", "raised_gross_cents",
                  "fee_total_cents", "raised_net_cents", "credit_applied_cents",
                  "available_credit_cents", "goal_met", "created_at", "updated_at", "version"]

DONATION_FIELDS = ["id", "fundraising_account_id", "donor_name", "amount_cents", "channel",
                   "fee_cents", "status", "received_at", "created_at", "updated_at", "version"]

PAYMENT_FIELDS = ["id", "registration_id", "amount_cents", "method", "status", "posted_at",
                  "created_at", "updated_at", "version"]

APPLICATION_FIELDS = ["id", "registration_id", "requested_cents", "need_score",
                      "award_cents", "status", "approved_by_user_id",
                      "disbursed_by_user_id", "decision_reason",
                      "created_at", "updated_at", "version"]

CHAPERONE_FIELDS = ["id", "program_id", "first_name", "last_name", "email", "phone",
                    "current_screening_expires_at", "created_at", "updated_at", "version"]

CHECK_FIELDS = ["id", "chaperone_id", "status", "vendor_reference", "cleared_at",
                "expires_at", "created_at", "updated_at", "version"]

ASSIGNMENT_FIELDS = ["id", "trip_id", "chaperone_id", "role", "status", "removal_reason",
                     "created_at", "updated_at", "version"]

ITINERARY_FIELDS = ["id", "trip_id", "segment_type", "title", "start_at", "end_at",
                    "location", "vehicle_code", "created_at", "updated_at", "version"]

LODGING_FIELDS = ["id", "trip_id", "site_name", "room_code", "check_in_date",
                  "check_out_date", "room_capacity", "cost_cents", "status",
                  "created_at", "updated_at", "version"]


def ser_program(e):
    recompute_program_fund(e)
    return _public(e, PROGRAM_FIELDS)


def ser_trip(e):
    recompute_trip(e)
    return _public(e, TRIP_FIELDS)


def ser_participant(e):
    return _public(e, PARTICIPANT_FIELDS)


def ser_registration(e):
    return _public(e, REGISTRATION_FIELDS)


def ser_consent_form(e):
    return _public(e, CONSENT_FORM_FIELDS)


def ser_account(e):
    recompute_account(e)
    return _public(e, ACCOUNT_FIELDS)


def ser_donation(e):
    return _public(e, DONATION_FIELDS)


def ser_payment(e):
    return _public(e, PAYMENT_FIELDS)


def ser_application(e):
    return _public(e, APPLICATION_FIELDS)


def ser_chaperone(e):
    recompute_chaperone_screening(e)
    return _public(e, CHAPERONE_FIELDS)


def ser_check(e):
    return _public(e, CHECK_FIELDS)


def ser_assignment(e):
    return _public(e, ASSIGNMENT_FIELDS)


def ser_itinerary_item(e):
    return _public(e, ITINERARY_FIELDS)


def ser_lodging(e):
    return _public(e, LODGING_FIELDS)
