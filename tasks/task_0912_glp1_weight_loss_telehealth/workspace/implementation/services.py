"""Lookups, cascades and shared domain behaviour."""

from datetime import timedelta

import calculations as calc
import errors
from errors import ApiError
from store import (format_iso, new_record, ordered, parse_iso,
                   shift_preserving_style, store, touch, whole_days_between)


# --- lookups ---------------------------------------------------------------
def _find(collection, identifier, error_id):
    record = collection.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def get_patient(identifier):
    return _find(store.patients, identifier, errors.ERR_PATIENT_NOT_FOUND)


def get_provider(identifier):
    return _find(store.providers, identifier, errors.ERR_PROVIDER_NOT_FOUND)


def get_pharmacy(identifier):
    return _find(store.pharmacies, identifier, errors.ERR_PHARMACY_RESOURCE_NOT_FOUND)


def get_supply_lot(identifier):
    return _find(store.supply_lots, identifier, errors.ERR_PHARMACY_RESOURCE_NOT_FOUND)


def get_screening(identifier):
    return _find(store.screenings, identifier, errors.ERR_CLINICAL_RECORD_NOT_FOUND)


def get_consult(identifier):
    return _find(store.consults, identifier, errors.ERR_CLINICAL_RECORD_NOT_FOUND)


def get_prescription(identifier):
    return _find(store.prescriptions, identifier, errors.ERR_CLINICAL_RECORD_NOT_FOUND)


def get_titration_step(identifier):
    return _find(store.titration_steps, identifier, errors.ERR_CLINICAL_RECORD_NOT_FOUND)


def get_check_in(identifier):
    return _find(store.check_ins, identifier, errors.ERR_CLINICAL_RECORD_NOT_FOUND)


def get_prior_authorization(identifier):
    return _find(store.prior_authorizations, identifier,
                 errors.ERR_FULFILLMENT_RECORD_NOT_FOUND)


def get_pharmacy_order(identifier):
    return _find(store.pharmacy_orders, identifier,
                 errors.ERR_FULFILLMENT_RECORD_NOT_FOUND)


def get_subscription(identifier):
    return _find(store.subscriptions, identifier, errors.ERR_BILLING_RECORD_NOT_FOUND)


def get_billing_cycle(identifier):
    return _find(store.billing_cycles, identifier, errors.ERR_BILLING_RECORD_NOT_FOUND)


def get_coaching_session(identifier):
    return _find(store.coaching_sessions, identifier, errors.ERR_BILLING_RECORD_NOT_FOUND)


# --- collection scans ------------------------------------------------------
def steps_of(prescription_id):
    return ordered([s for s in store.titration_steps.values()
                    if s["prescription_id"] == prescription_id])


def orders_of_prescription(prescription_id):
    return ordered([o for o in store.pharmacy_orders.values()
                    if o["prescription_id"] == prescription_id])


def orders_of_step(titration_step_id):
    return ordered([o for o in store.pharmacy_orders.values()
                    if o["titration_step_id"] == titration_step_id])


def check_ins_of(prescription_id):
    return ordered([c for c in store.check_ins.values()
                    if c["prescription_id"] == prescription_id])


def cycles_of(subscription_id):
    return ordered([c for c in store.billing_cycles.values()
                    if c["subscription_id"] == subscription_id])


def sessions_of_cycle(billing_cycle_id):
    return ordered([s for s in store.coaching_sessions.values()
                    if s["billing_cycle_id"] == billing_cycle_id])


def has_open_escalation(prescription_id, excluding_id=None):
    for c in store.check_ins.values():
        if c["prescription_id"] != prescription_id:
            continue
        if excluding_id is not None and c["id"] == excluding_id:
            continue
        if c["status"] == "ESCALATED":
            return True
    return False


# --- severity indices (PRD 3.8) -------------------------------------------
TRIAGED_STATUSES = ("CLEARED", "ESCALATED", "RESOLVED")


def recompute_severity_indices(prescription):
    now = store.now_dt()
    window_start = now - timedelta(days=calc.SEVERITY_WINDOW_DAYS)
    baseline = parse_iso(prescription["last_dose_change_at"])

    candidates = [c for c in store.check_ins.values()
                  if c["prescription_id"] == prescription["id"]
                  and c["status"] in TRIAGED_STATUSES]

    rolling_pool = []
    since_pool = []
    for c in candidates:
        submitted = parse_iso(c["submitted_at"])
        if submitted is None:
            continue
        if window_start < submitted <= now:
            rolling_pool.append(c)
        if baseline is not None and submitted >= baseline:
            since_pool.append(c)

    prescription["severity_index_rolling"] = calc.index_of(rolling_pool)
    prescription["severity_index_since_dose_change"] = calc.index_of(since_pool)
    touch(prescription)


# --- pharmacy order cancellation (PRD 3.7) --------------------------------
def cancel_order(order, reason):
    """Uniform cancellation for the endpoint path and every cascade path."""
    was_reserved = order["status"] == "RESERVED"
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    touch(order)

    if was_reserved:
        lot = store.supply_lots.get(order["supply_lot_id"])
        if lot is not None:
            lot["available_units"] += order["units_requested"]
            lot["reserved_units"] -= order["units_requested"]
            touch(lot)
        prescription = store.prescriptions.get(order["prescription_id"])
        if prescription is not None:
            remaining = [o for o in orders_of_prescription(prescription["id"])
                         if o["status"] in ("CREATED", "RESERVED")]
            if not remaining:
                prescription["fulfillment_status"] = "UNROUTED"
                touch(prescription)
    return order


# --- clinical hold / release cascades (PRD 3.8) ---------------------------
def apply_clinical_hold(prescription):
    """Hops 2-5 of the escalation cascade."""
    if prescription["clinical_status"] != "ACTIVE":
        return
    prescription["clinical_status"] = "HELD"
    touch(prescription)
    for step in steps_of(prescription["id"]):
        if step["status"] != "DUE":
            continue
        step["status"] = "HELD"
        step["hold_reason"] = "SIDE_EFFECT"
        touch(step)
        for order in orders_of_step(step["id"]):
            if order["status"] in ("CREATED", "RESERVED"):
                cancel_order(order, "CLINICAL_HOLD")


def apply_hold_release(prescription):
    """Hops 2-3 of the resolution cascade; only SIDE_EFFECT holds are lifted."""
    if prescription["clinical_status"] != "HELD":
        return
    prescription["clinical_status"] = "ACTIVE"
    touch(prescription)
    for step in steps_of(prescription["id"]):
        if step["status"] == "HELD" and step["hold_reason"] == "SIDE_EFFECT":
            step["status"] = "DUE"
            step["hold_reason"] = None
            touch(step)


# --- titration steps -------------------------------------------------------
def create_titration_step(prescription, step_number, dose_level):
    now_iso = store.now_iso()
    earliest = format_iso(store.now_dt()
                          + timedelta(days=calc.TITRATION_MIN_INTERVAL_DAYS))
    return new_record(store.titration_steps, {
        "prescription_id": prescription["id"],
        "second_signer_provider_id": None,
        "step_number": step_number,
        "dose_level": dose_level,
        "dose_mg": calc.dose_mg_for(prescription["drug_family"], dose_level),
        "status": "DUE",
        "earliest_escalation_at": earliest,
        "administered_at": None,
        "hold_reason": None,
    })


def next_step_number(prescription_id):
    existing = steps_of(prescription_id)
    return max([s["step_number"] for s in existing], default=0) + 1


# --- routing selector (PRD 3.7) -------------------------------------------
def select_supply_lot(prescription, patient, units_requested):
    required_form = "BRANDED" if prescription["active_route_mode"] == "INSURANCE" \
        else "COMPOUNDED"
    horizon = store.now_dt() + timedelta(days=calc.LOT_MIN_SHELF_LIFE_DAYS)

    candidates = []
    for lot in ordered(list(store.supply_lots.values())):
        if lot["status"] != "RELEASED":
            continue
        if not calc.strengths_match(lot["strength_mg"], prescription["dose_mg"]):
            continue
        if lot["available_units"] < units_requested:
            continue
        expires = parse_iso(lot["expires_at"])
        if expires is None or expires < horizon:
            continue
        pharmacy = store.pharmacies.get(lot["pharmacy_id"])
        if pharmacy is None or pharmacy["status"] != "ACTIVE":
            continue
        if pharmacy["dispense_type"] != required_form:
            continue
        if patient["state_code"] not in pharmacy["served_state_codes"]:
            continue
        candidates.append(lot)

    if not candidates:
        return None, None

    candidates.sort(key=lambda l: (parse_iso(l["expires_at"]),
                                   -l["available_units"],
                                   l["created_at"],
                                   l["_seq"]))
    winner = candidates[0]
    return winner, required_form


# --- billing ---------------------------------------------------------------
def grant_coaching_credits(subscription):
    if not subscription["coaching_addon_enabled"]:
        return
    subscription["coaching_credits_granted"] += calc.COACHING_CREDITS_PER_CYCLE
    subscription["coaching_credits_available"] += calc.COACHING_CREDITS_PER_CYCLE
    touch(subscription)


def open_billing_cycle(subscription, period_start_raw):
    """Opens a cycle spanning exactly thirty days and grants add-on credits."""
    period_end_raw = shift_preserving_style(period_start_raw, calc.CYCLE_LENGTH_DAYS)
    subscription["cycle_count"] += 1
    touch(subscription)
    cycle = new_record(store.billing_cycles, {
        "subscription_id": subscription["id"],
        "sequence_number": subscription["cycle_count"],
        "period_start_at": period_start_raw,
        "period_end_at": period_end_raw,
        "status": "OPEN",
        "charge_basis": None,
        "medication_charge_cents": 0,
        "coaching_addon_fee_cents": 0,
        "dispensing_fee_cents": 0,
        "adherence_credit_cents": 0,
        "total_due_cents": 0,
        "settled_amount_cents": 0,
        "proration_credit_cents": 0,
        "coaching_unused_credit_cents": 0,
        "invoiced_at": None,
        "void_reason": None,
    })
    grant_coaching_credits(subscription)
    return cycle


def void_cycle(cycle, void_reason):
    """Applies the state-dependent consequences of a void (PRD 3.9)."""
    previous_status = cycle["status"]
    if previous_status == "SETTLED":
        subscription = store.subscriptions.get(cycle["subscription_id"])
        patient = store.patients.get(subscription["patient_id"]) if subscription else None
        if patient is not None:
            patient["lifetime_credited_cents"] += cycle["settled_amount_cents"]
            touch(patient)
        cycle["settled_amount_cents"] = 0
    elif previous_status == "INVOICED":
        cycle["proration_credit_cents"] = calc.proration_credit(cycle, store.now_dt())
    cycle["status"] = "VOIDED"
    cycle["void_reason"] = void_reason
    touch(cycle)
    return cycle


def forfeit_sessions_of_cycle(subscription, cycle):
    for session in sessions_of_cycle(cycle["id"]):
        if session["status"] != "SCHEDULED":
            continue
        session["status"] = "FORFEITED"
        touch(session)
        subscription["coaching_credits_reserved"] -= 1
        subscription["coaching_credits_forfeited"] += 1
        touch(subscription)


def cascade_cycle_void(subscription, void_reason):
    """Hops 2 and 3 of the pause / cancellation cascade (PRD 3.9)."""
    for cycle in cycles_of(subscription["id"]):
        if cycle["status"] not in ("OPEN", "INVOICED"):
            continue
        void_cycle(cycle, void_reason)
        forfeit_sessions_of_cycle(subscription, cycle)


def triaged_count_in_window(prescription_id, period_start_raw, period_end_raw):
    """Check-ins triaged inside [period_start_at, period_end_at) (PRD 3.9)."""
    start = parse_iso(period_start_raw)
    end = parse_iso(period_end_raw)
    count = 0
    for c in store.check_ins.values():
        if c["prescription_id"] != prescription_id:
            continue
        if c["status"] not in TRIAGED_STATUSES:
            continue
        triaged = parse_iso(c["triaged_at"])
        if triaged is None:
            continue
        if start <= triaged < end:
            count += 1
    return count


# --- calendar overlap ------------------------------------------------------
def consult_conflicts(provider_id, start_dt, end_dt, exclude_id=None):
    """Buffered overlap: both sides widened by fifteen minutes (PRD 3.3)."""
    buffer = timedelta(minutes=calc.CONSULT_BUFFER_MINUTES)
    for other in store.consults.values():
        if other["provider_id"] != provider_id or other["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start = parse_iso(other["scheduled_start_at"])
        other_end = parse_iso(other["scheduled_end_at"])
        if start_dt < other_end + buffer and other_start < end_dt + buffer:
            return True
    return False


def coach_conflicts(coach_provider_id, start_dt, end_dt, exclude_id=None):
    """Plain half-open overlap with no buffer; abutting sessions are legal."""
    for other in store.coaching_sessions.values():
        if other["coach_provider_id"] != coach_provider_id \
                or other["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start = parse_iso(other["scheduled_start_at"])
        other_end = parse_iso(other["scheduled_end_at"])
        if start_dt < other_end and other_start < end_dt:
            return True
    return False


def pause_days_elapsed(subscription):
    return whole_days_between(parse_iso(subscription["paused_at"]), store.now_dt())
