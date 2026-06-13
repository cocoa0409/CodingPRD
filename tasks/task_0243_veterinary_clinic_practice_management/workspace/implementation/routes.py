"""All 51 endpoints under the /clinic prefix (PRD §4, SCAFFOLD §1.5)."""
from flask import Blueprint, request

import db
import errors
import lookup
import calculations as calc
import services
import validation as v
from calculations import parse_dt
from middleware import get_role, require_roles
from response import success
from serialize import public
from listing import paginated

bp = Blueprint("clinic", __name__)

ALL_ROLES = ("Receptionist", "Veterinarian", "PracticeManager")

SPECIES = {"DOG", "CAT", "RABBIT", "FERRET"}
TIERS = {"BASIC", "PLUS", "PREMIER"}
VACCINE_CODES = {"RABIES", "DHPP", "BORDETELLA", "FVRCP"}
ORDER_TYPES = {"BLOODWORK", "URINALYSIS", "DENTAL_XRAY", "CYTOLOGY", "BIOPSY"}


def _created(record):
    return success(public(record), status=201, response_type="object")


def _ok(record):
    return success(public(record), status=200, response_type="object")


# =============================================================================
# Operatory
# =============================================================================
@bp.route("/clinic/operatories", methods=["POST"])
def create_operatory():
    role = get_role()
    require_roles(role, ("PracticeManager",))
    body = v.get_json_body()
    name = v.require_str(body, "name")
    buffer_minutes = v.optional_int(body, "cleanup_buffer_minutes", default=30, minimum=0)
    rec = db.new_common()
    rec.update({
        "name": name,
        "cleanup_buffer_minutes": buffer_minutes,
        "booked_minutes": 0,
        "status": "OPEN",
    })
    db.operatories[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/operatories", methods=["GET"])
def list_operatories():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.operatories)


@bp.route("/clinic/operatories/<oid>", methods=["GET"])
def get_operatory(oid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.operatory(oid))


# =============================================================================
# Kennel
# =============================================================================
@bp.route("/clinic/kennels", methods=["POST"])
def create_kennel():
    role = get_role()
    require_roles(role, ("PracticeManager",))
    body = v.get_json_body()
    name = v.require_str(body, "name")
    capacity = v.require_int(body, "capacity", minimum=1)
    rec = db.new_common()
    rec.update({"name": name, "capacity": capacity, "status": "OPEN"})
    db.kennels[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/kennels", methods=["GET"])
def list_kennels():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.kennels)


@bp.route("/clinic/kennels/<kid>", methods=["GET"])
def get_kennel(kid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.kennel(kid))


# =============================================================================
# Household
# =============================================================================
@bp.route("/clinic/households", methods=["POST"])
def create_household():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    account_name = v.require_str(body, "account_name")
    rec = db.new_common()
    rec.update({
        "account_name": account_name,
        "account_credit_cents": 0,
        "lifetime_invoiced_cents": 0,
        "status": "ACTIVE",
    })
    db.households[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/households", methods=["GET"])
def list_households():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.households)


@bp.route("/clinic/households/<hid>", methods=["GET"])
def get_household(hid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.household(hid))


# =============================================================================
# Deposit (posts credit to a household; not OCC-guarded per §2.6)
# =============================================================================
@bp.route("/clinic/deposits", methods=["POST"])
def post_deposit():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    # FK existence (priority 4) — household_id, optional estimate_id
    household_id = v.require_str(body, "household_id")
    household = lookup.household(household_id)
    estimate = None
    if body.get("estimate_id") is not None:
        estimate = lookup.estimate(body["estimate_id"])
    amount = v.require_int(body, "amount_cents", minimum=0)
    # expected_household_version is recorded but deposit is NOT OCC-guarded (§2.6).
    v.require_int(body, "expected_household_version", minimum=0)

    household["account_credit_cents"] += amount
    if estimate is not None:
        estimate["deposit_posted_cents"] += amount
        db.touch(estimate)
    db.touch(household)
    return success(public(household), status=201, response_type="object")


# =============================================================================
# Owner
# =============================================================================
@bp.route("/clinic/owners", methods=["POST"])
def create_owner():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    household_id = v.require_str(body, "household_id")
    lookup.household(household_id)
    full_name = v.require_str(body, "full_name")
    email = v.require_str(body, "email")
    is_primary = v.optional_bool(body, "is_primary", default=False)
    # email unique across all owners (§3.1)
    for o in db.owners.values():
        if o["email"] == email:
            errors.raise_err(errors.ERR_OWNER_EMAIL_TAKEN, "Owner email already in use.")
    rec = db.new_common()
    rec.update({
        "household_id": household_id,
        "full_name": full_name,
        "email": email,
        "is_primary": is_primary,
    })
    db.owners[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/owners", methods=["GET"])
def list_owners():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.owners, {"household_id": request.args.get("household_id")})


@bp.route("/clinic/owners/<ownerid>", methods=["GET"])
def get_owner(ownerid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.owner(ownerid))


# =============================================================================
# Patient
# =============================================================================
@bp.route("/clinic/patients", methods=["POST"])
def create_patient():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    household_id = v.require_str(body, "household_id")
    lookup.household(household_id)
    name = v.require_str(body, "name")
    species = v.require_enum(body, "species", SPECIES)
    weight_kg = v.require_number(body, "weight_kg", gt=0)
    rec = db.new_common()
    rec.update({
        "household_id": household_id,
        "name": name,
        "species": species,
        "weight_kg": weight_kg,
        "status": "ACTIVE",
    })
    db.patients[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/patients", methods=["GET"])
def list_patients():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.patients, {"household_id": request.args.get("household_id")})


@bp.route("/clinic/patients/<pid>", methods=["GET"])
def get_patient(pid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.patient(pid))


@bp.route("/clinic/patients/<pid>/deactivate", methods=["POST"])
def deactivate_patient(pid):
    role = get_role()
    require_roles(role, ("Receptionist",))
    patient = lookup.patient(pid)
    if patient["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not active.")
    for appt in db.appointments.values():
        if appt["patient_id"] == pid and appt["status"] in ("SCHEDULED", "CHECKED_IN", "IN_EXAM"):
            errors.raise_err(errors.ERR_PATIENT_HAS_OPEN_VISITS, "Patient has open visits.")
    patient["status"] = "INACTIVE"
    db.touch(patient)
    return _ok(patient)


@bp.route("/clinic/patients/<pid>/mark-deceased", methods=["POST"])
def mark_deceased(pid):
    role = get_role()
    require_roles(role, ("Veterinarian",))
    patient = lookup.patient(pid)
    if patient["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not active.")
    patient["status"] = "DECEASED"
    db.touch(patient)
    services.cascade_patient_deceased(patient)
    return _ok(patient)


# =============================================================================
# WellnessPlan
# =============================================================================
@bp.route("/clinic/wellness-plans", methods=["POST"])
def create_wellness_plan():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    tier = v.require_enum(body, "tier", TIERS)
    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "tier": tier,
        "service_discount_pct": float(calc.TIER_SERVICE_DISCOUNT_PCT[tier]),
        "bundled_vaccines_remaining": calc.TIER_BUNDLED_VACCINES[tier],
        "realized_savings_cents": 0,
        "status": "ACTIVE",
    })
    db.wellness_plans[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/wellness-plans", methods=["GET"])
def list_wellness_plans():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.wellness_plans, {"patient_id": request.args.get("patient_id")},
                     serializer=_wellness_public)


@bp.route("/clinic/wellness-plans/<wpid>", methods=["GET"])
def get_wellness_plan(wpid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return success(_wellness_public(lookup.wellness_plan(wpid)), status=200, response_type="object")


def _wellness_public(plan):
    data = public(plan)
    data["projected_savings_cents"] = calc.wellness_projected_savings(
        plan["tier"], plan["service_discount_pct"]
    )
    return data


# =============================================================================
# Appointment
# =============================================================================
@bp.route("/clinic/appointments", methods=["POST"])
def create_appointment():
    role = get_role()
    require_roles(role, ("Receptionist",))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    scheduled_start = v.require_datetime(body, "scheduled_start")
    scheduled_end = v.require_datetime(body, "scheduled_end")
    visit_reason = v.require_str(body, "visit_reason")
    if not (parse_dt(scheduled_end) > parse_dt(scheduled_start)):
        errors.raise_err(errors.ERR_INVALID_TIME_RANGE, "scheduled_end must be after scheduled_start.")
    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "visit_reason": visit_reason,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    })
    db.appointments[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/appointments", methods=["GET"])
def list_appointments():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.appointments, {"patient_id": request.args.get("patient_id")})


@bp.route("/clinic/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.appointment(aid))


# Action -> allowed roles (action-specific RBAC, PRD §1.7).
_APPT_ACTION_ROLES = {
    "check-in": ("Receptionist",),
    "no-show": ("Receptionist",),
    "cancel": ("Receptionist",),
    "begin-exam": ("Veterinarian",),
    "reschedule": ("Veterinarian",),
    "complete": ("Veterinarian",),
}


@bp.route("/clinic/appointments/<aid>/transition", methods=["POST"])
def transition_appointment(aid):
    role = get_role()
    # endpoint-level role gate (Receptionist or Veterinarian)
    require_roles(role, ("Receptionist", "Veterinarian"))
    appt = lookup.appointment(aid)
    body = v.get_json_body()
    action = v.require_str(body, "action")
    if action not in _APPT_ACTION_ROLES:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Unknown action.")
    require_roles(role, _APPT_ACTION_ROLES[action])

    if action == "check-in":
        if appt["status"] != "SCHEDULED":
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not SCHEDULED.")
        patient = db.patients[appt["patient_id"]]
        if patient["status"] != "ACTIVE":
            errors.raise_err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not active.")
        appt["status"] = "CHECKED_IN"
        db.touch(appt)

    elif action == "no-show":
        if appt["status"] != "SCHEDULED":
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not SCHEDULED.")
        if calc.parse_dt(calc.to_iso(_now())) < parse_dt(appt["scheduled_end"]):
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Too early for no-show.")
        appt["status"] = "NO_SHOW"
        db.touch(appt)

    elif action == "begin-exam":
        if appt["status"] != "CHECKED_IN":
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not CHECKED_IN.")
        appt["status"] = "IN_EXAM"
        db.touch(appt)

    elif action == "reschedule":
        if appt["status"] != "IN_EXAM":
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not IN_EXAM.")
        if appt["reschedule_count"] >= 3:
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Reschedule limit reached.")
        for sg in db.surgeries.values():
            if sg["appointment_id"] == aid and sg["status"] in ("BOOKED", "IN_PROGRESS"):
                errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Open surgery blocks reschedule.")
        new_start = v.require_datetime(body, "scheduled_start")
        new_end = v.require_datetime(body, "scheduled_end")
        if not (parse_dt(new_end) > parse_dt(new_start)):
            errors.raise_err(errors.ERR_INVALID_TIME_RANGE, "scheduled_end must be after scheduled_start.")
        appt["status"] = "SCHEDULED"
        appt["reschedule_count"] += 1
        appt["scheduled_start"] = new_start
        appt["scheduled_end"] = new_end
        db.touch(appt)

    elif action == "complete":
        if appt["status"] != "IN_EXAM":
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not IN_EXAM.")
        for lo in db.lab_orders.values():
            if lo["appointment_id"] == aid and lo["status"] in ("ORDERED", "COLLECTED"):
                errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Open lab orders block completion.")
        for sg in db.surgeries.values():
            if sg["appointment_id"] == aid and sg["status"] in ("BOOKED", "IN_PROGRESS"):
                errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Open surgery blocks completion.")
        appt["status"] = "COMPLETED"
        db.touch(appt)
        services.settle_realized_savings(appt)

    elif action == "cancel":
        if appt["status"] not in ("SCHEDULED", "CHECKED_IN", "IN_EXAM"):
            errors.raise_err(errors.ERR_APPOINTMENT_INVALID_STATE, "Appointment not cancellable.")
        appt["status"] = "CANCELLED"
        db.touch(appt)
        services.cascade_appointment_cancel(appt)

    return _ok(appt)


# =============================================================================
# Vaccination
# =============================================================================
@bp.route("/clinic/vaccinations", methods=["POST"])
def create_vaccination():
    role = get_role()
    require_roles(role, ("Veterinarian",))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    vaccine_code = v.require_enum(body, "vaccine_code", VACCINE_CODES)
    administered_at = v.require_datetime(body, "administered_at")
    bundled = v.optional_bool(body, "bundled", default=False)

    if parse_dt(administered_at) > _now():
        errors.raise_err(errors.ERR_FUTURE_ADMINISTRATION, "administered_at is in the future.")

    # re-dose interval guard (§3.4): latest prior dose of same code for patient
    interval = calc.MIN_INTERVAL_DAYS[vaccine_code]
    prior = _latest_prior_vaccination(patient_id, vaccine_code)
    if prior is not None:
        gap_days = (parse_dt(administered_at).date() - parse_dt(prior["administered_at"]).date()).days
        if gap_days < interval:
            errors.raise_err(errors.ERR_VACCINE_INTERVAL, "Re-dose interval not met.")

    # fee determination + bundle draw
    plan = services.active_plan_for_patient(patient_id)
    fee_cents = calc.STANDARD_VACCINE_FEE_CENTS
    drew_bundle = False
    if bundled and plan is not None and plan["bundled_vaccines_remaining"] > 0:
        fee_cents = 0
        drew_bundle = True

    next_due_at, reminder_at = calc.vaccine_schedule(vaccine_code, administered_at)

    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "vaccine_code": vaccine_code,
        "administered_at": administered_at,
        "bundled": bundled,
        "fee_cents": fee_cents,
        "next_due_at": next_due_at,
        "reminder_at": reminder_at,
    })
    db.vaccinations[rec["id"]] = rec

    if drew_bundle:
        plan["bundled_vaccines_remaining"] -= 1
        plan["realized_savings_cents"] += calc.STANDARD_VACCINE_FEE_CENTS
        db.touch(plan)

    return _created(rec)


def _latest_prior_vaccination(patient_id, vaccine_code):
    candidates = [
        v_ for v_ in db.vaccinations.values()
        if v_["patient_id"] == patient_id and v_["vaccine_code"] == vaccine_code
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (parse_dt(r["administered_at"]), r["_seq"]))
    return candidates[-1]


@bp.route("/clinic/vaccinations", methods=["GET"])
def list_vaccinations():
    role = get_role()
    require_roles(role, ALL_ROLES)
    limit, offset = v.parse_pagination()
    rows = list(db.vaccinations.values())
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    due_only = request.args.get("due_only")
    if due_only is not None and str(due_only).lower() in ("true", "1"):
        now = _now()
        rows = [r for r in rows if parse_dt(r["reminder_at"]) <= now]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    from response import list_response
    return list_response([public(r) for r in page], limit, offset, total)


@bp.route("/clinic/vaccinations/<vid>", methods=["GET"])
def get_vaccination(vid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.vaccination(vid))


# =============================================================================
# Prescription
# =============================================================================
@bp.route("/clinic/prescriptions", methods=["POST"])
def create_prescription():
    role = get_role()
    require_roles(role, ("Veterinarian",))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    drug_name = v.require_str(body, "drug_name")
    refills_authorized = v.require_int(body, "refills_authorized", minimum=0)
    is_controlled = v.optional_bool(body, "is_controlled", default=False)
    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "drug_name": drug_name,
        "is_controlled": is_controlled,
        "refills_authorized": refills_authorized,
        "refills_used": 0,
        "last_refill_at": None,
        "status": "ACTIVE",
    })
    db.prescriptions[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/prescriptions", methods=["GET"])
def list_prescriptions():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.prescriptions, {"patient_id": request.args.get("patient_id")})


@bp.route("/clinic/prescriptions/<rxid>", methods=["GET"])
def get_prescription(rxid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.prescription(rxid))


@bp.route("/clinic/prescriptions/<rxid>/refill", methods=["POST"])
def refill_prescription(rxid):
    role = get_role()
    require_roles(role, ("Veterinarian",))
    rx = lookup.prescription(rxid)
    if rx["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_PRESCRIPTION_NOT_ACTIVE, "Prescription not active.")
    patient = db.patients[rx["patient_id"]]
    if patient["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not active.")
    now = _now()
    if rx["is_controlled"] and rx["last_refill_at"] is not None:
        elapsed_days = (now - parse_dt(rx["last_refill_at"])).total_seconds() / 86400.0
        if elapsed_days < calc.CONTROLLED_COOLDOWN_DAYS:
            errors.raise_err(errors.ERR_CONTROLLED_COOLDOWN, "Controlled-substance cooldown active.")
    remaining = rx["refills_authorized"] - rx["refills_used"]
    if remaining <= 0:
        errors.raise_err(errors.ERR_NO_REFILLS_REMAINING, "No refills remaining.")
    rx["refills_used"] += 1
    rx["last_refill_at"] = calc.to_iso(now)
    if rx["refills_authorized"] - rx["refills_used"] == 0:
        rx["status"] = "EXHAUSTED"
    db.touch(rx)
    return _ok(rx)


# =============================================================================
# Estimate
# =============================================================================
def _validate_line_items(line_items):
    if not isinstance(line_items, list):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "line_items must be an array.")
    cleaned = []
    for li in line_items:
        if not isinstance(li, dict):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "Each line item must be an object.")
        service_code = li.get("service_code")
        if not isinstance(service_code, str) or service_code == "":
            errors.raise_err(errors.ERR_INVALID_REQUEST, "line item service_code required.")
        qty = li.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            errors.raise_err(errors.ERR_INVALID_REQUEST, "line item qty must be >= 1.")
        unit_price = li.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            errors.raise_err(errors.ERR_INVALID_REQUEST, "line item unit_price_cents must be >= 0.")
        eligible = li.get("eligible_for_plan_discount", False)
        if not isinstance(eligible, bool):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "line item eligible_for_plan_discount must be boolean.")
        cleaned.append({
            "service_code": service_code,
            "qty": qty,
            "unit_price_cents": unit_price,
            "eligible_for_plan_discount": eligible,
        })
    return cleaned


@bp.route("/clinic/estimates", methods=["POST"])
def create_estimate():
    role = get_role()
    require_roles(role, ("Veterinarian", "Receptionist"))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    line_items = _validate_line_items(v.require(body, "line_items"))
    deposit_required = v.optional_int(body, "deposit_required_cents", default=0, minimum=0)
    plan = services.active_plan_for_patient(patient_id)
    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "line_items": line_items,
        "deposit_required_cents": deposit_required,
        "deposit_posted_cents": 0,
        "estimated_total_cents": calc.estimate_projected_total(line_items, plan),
        "revision": 1,
        "status": "DRAFT",
    })
    db.estimates[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/estimates", methods=["GET"])
def list_estimates():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.estimates, {"patient_id": request.args.get("patient_id")})


@bp.route("/clinic/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.estimate(eid))


_ESTIMATE_ACTION_ROLES = {
    "present": ("Veterinarian",),
    "revise": ("Veterinarian",),
    "decline": ("Receptionist",),
    "approve": ("Receptionist",),
    "expire": ("PracticeManager",),
}


@bp.route("/clinic/estimates/<eid>/transition", methods=["POST"])
def transition_estimate(eid):
    role = get_role()
    require_roles(role, ("Veterinarian", "Receptionist", "PracticeManager"))
    est = lookup.estimate(eid)
    body = v.get_json_body()
    action = v.require_str(body, "action")
    if action not in _ESTIMATE_ACTION_ROLES:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Unknown action.")
    require_roles(role, _ESTIMATE_ACTION_ROLES[action])

    if action == "present":
        if est["status"] != "DRAFT":
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate not DRAFT.")
        if not est["line_items"]:
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate has no line items.")
        plan = services.active_plan_for_patient(est["patient_id"])
        est["estimated_total_cents"] = calc.estimate_projected_total(est["line_items"], plan)
        est["status"] = "PRESENTED"
        db.touch(est)

    elif action == "decline":
        if est["status"] != "PRESENTED":
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate not PRESENTED.")
        est["status"] = "DECLINED"
        db.touch(est)

    elif action == "revise":
        if est["status"] != "DECLINED":
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate not DECLINED.")
        new_items = _validate_line_items(v.require(body, "line_items"))
        est["status"] = "DRAFT"
        est["revision"] += 1
        est["line_items"] = new_items
        plan = services.active_plan_for_patient(est["patient_id"])
        est["estimated_total_cents"] = calc.estimate_projected_total(new_items, plan)
        db.touch(est)

    elif action == "approve":
        if est["status"] != "PRESENTED":
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate not PRESENTED.")
        if est["deposit_posted_cents"] < est["deposit_required_cents"]:
            errors.raise_err(errors.ERR_DEPOSIT_NOT_MET, "Deposit requirement not met.")
        est["status"] = "APPROVED"
        db.touch(est)

    elif action == "expire":
        if est["status"] not in ("DRAFT", "PRESENTED"):
            errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Estimate not expirable.")
        est["status"] = "EXPIRED"
        db.touch(est)
        if est["deposit_posted_cents"] > 0:
            patient = db.patients.get(est["patient_id"])
            if patient is not None:
                household = db.households.get(patient["household_id"])
                if household is not None:
                    household["account_credit_cents"] += est["deposit_posted_cents"]
                    db.touch(household)

    return _ok(est)


# =============================================================================
# Surgery
# =============================================================================
@bp.route("/clinic/surgeries", methods=["POST"])
def create_surgery():
    role = get_role()
    require_roles(role, ("Veterinarian",))
    body = v.get_json_body()
    # FK existence (priority 4): appointment_id, operatory_id, estimate_id
    appointment_id = v.require_str(body, "appointment_id")
    appointment = lookup.appointment(appointment_id)
    operatory_id = v.require_str(body, "operatory_id")
    operatory = lookup.operatory(operatory_id)
    estimate_id = v.require_str(body, "estimate_id")
    estimate = lookup.estimate(estimate_id)
    procedure_name = v.require_str(body, "procedure_name")
    window_start = v.require_datetime(body, "window_start")
    window_end = v.require_datetime(body, "window_end")
    if not (parse_dt(window_end) > parse_dt(window_start)):
        errors.raise_err(errors.ERR_INVALID_TIME_RANGE, "window_end must be after window_start.")
    # funding estimate must be APPROVED (§3.8)
    if estimate["status"] != "APPROVED":
        errors.raise_err(errors.ERR_ESTIMATE_INVALID_STATE, "Funding estimate not APPROVED.")
    # operatory overlap + buffer (priority 11)
    if services.operatory_conflict(operatory_id, operatory["cleanup_buffer_minutes"],
                                   window_start, window_end):
        errors.raise_err(errors.ERR_OPERATORY_CONFLICT, "Operatory booking conflict.")

    patient = db.patients[appointment["patient_id"]]
    total = calc.surgery_total(patient["weight_kg"], window_start, window_end)
    minutes = calc.window_minutes(window_start, window_end)

    rec = db.new_common()
    rec.update({
        "appointment_id": appointment_id,
        "operatory_id": operatory_id,
        "estimate_id": estimate_id,
        "procedure_name": procedure_name,
        "window_start": window_start,
        "window_end": window_end,
        "surgery_total_cents": total,
        "deposit_consumed_cents": 0,
        "status": "BOOKED",
    })
    db.surgeries[rec["id"]] = rec

    operatory["booked_minutes"] += minutes
    db.touch(operatory)
    services.commit_surgery_deposit(rec, estimate)
    return _created(rec)


@bp.route("/clinic/surgeries", methods=["GET"])
def list_surgeries():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.surgeries, {
        "appointment_id": request.args.get("appointment_id"),
        "operatory_id": request.args.get("operatory_id"),
        "estimate_id": request.args.get("estimate_id"),
    })


@bp.route("/clinic/surgeries/<sid>", methods=["GET"])
def get_surgery(sid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.surgery(sid))


@bp.route("/clinic/surgeries/<sid>/transition", methods=["POST"])
def transition_surgery(sid):
    role = get_role()
    require_roles(role, ("Veterinarian",))
    sg = lookup.surgery(sid)
    body = v.get_json_body()
    action = v.require_str(body, "action")
    if action not in ("start", "complete", "cancel"):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Unknown action.")

    if action == "start":
        if sg["status"] != "BOOKED":
            errors.raise_err(errors.ERR_SURGERY_INVALID_STATE, "Surgery not BOOKED.")
        appointment = db.appointments[sg["appointment_id"]]
        if appointment["status"] != "IN_EXAM":
            errors.raise_err(errors.ERR_APPOINTMENT_NOT_IN_EXAM, "Parent appointment not IN_EXAM.")
        sg["status"] = "IN_PROGRESS"
        db.touch(sg)

    elif action == "complete":
        if sg["status"] != "IN_PROGRESS":
            errors.raise_err(errors.ERR_SURGERY_INVALID_STATE, "Surgery not IN_PROGRESS.")
        sg["status"] = "DONE"
        db.touch(sg)

    elif action == "cancel":
        if sg["status"] not in ("BOOKED", "IN_PROGRESS"):
            errors.raise_err(errors.ERR_SURGERY_INVALID_STATE, "Surgery not cancellable.")
        minutes = calc.window_minutes(sg["window_start"], sg["window_end"])
        sg["status"] = "CANCELLED"
        op = db.operatories.get(sg["operatory_id"])
        if op is not None:
            op["booked_minutes"] -= minutes
            db.touch(op)
        services.refund_surgery_deposit(sg)
        db.touch(sg)

    return _ok(sg)


# =============================================================================
# BoardingStay
# =============================================================================
@bp.route("/clinic/boarding-stays", methods=["POST"])
def create_boarding_stay():
    role = get_role()
    require_roles(role, ("Receptionist", "PracticeManager"))
    body = v.get_json_body()
    patient_id = v.require_str(body, "patient_id")
    lookup.patient(patient_id)
    kennel_id = v.require_str(body, "kennel_id")
    kennel = lookup.kennel(kennel_id)
    check_in_date = v.require_datetime(body, "check_in_date")
    check_out_date = v.require_datetime(body, "check_out_date")
    nightly_rate = v.require_int(body, "nightly_rate_cents", minimum=0)
    # check_out must be on/after check_in (§3.9)
    if parse_dt(check_out_date).date() < parse_dt(check_in_date).date():
        errors.raise_err(errors.ERR_INVALID_TIME_RANGE, "check_out_date before check_in_date.")
    # kennel aggregate-capacity overlap (priority 12)
    if not services.kennel_capacity_ok(kennel_id, check_in_date, check_out_date, kennel["capacity"]):
        errors.raise_err(errors.ERR_KENNEL_AT_CAPACITY, "Kennel at capacity.")
    total = calc.boarding_total(check_in_date, check_out_date, nightly_rate)
    rec = db.new_common()
    rec.update({
        "patient_id": patient_id,
        "kennel_id": kennel_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "nightly_rate_cents": nightly_rate,
        "board_total_cents": total,
        "status": "RESERVED",
    })
    db.boarding_stays[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/boarding-stays", methods=["GET"])
def list_boarding_stays():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.boarding_stays, {
        "patient_id": request.args.get("patient_id"),
        "kennel_id": request.args.get("kennel_id"),
    })


@bp.route("/clinic/boarding-stays/<bid>", methods=["GET"])
def get_boarding_stay(bid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.boarding(bid))


@bp.route("/clinic/boarding-stays/<bid>/transition", methods=["POST"])
def transition_boarding_stay(bid):
    role = get_role()
    require_roles(role, ("Receptionist",))
    stay = lookup.boarding(bid)
    body = v.get_json_body()
    action = v.require_str(body, "action")
    if action not in ("check-in", "check-out", "cancel"):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Unknown action.")

    if action == "check-in":
        if stay["status"] != "RESERVED":
            errors.raise_err(errors.ERR_BOARDING_INVALID_STATE, "Stay not RESERVED.")
        patient = db.patients[stay["patient_id"]]
        if patient["status"] != "ACTIVE":
            errors.raise_err(errors.ERR_PATIENT_NOT_ACTIVE, "Patient is not active.")
        stay["status"] = "CHECKED_IN"
        db.touch(stay)

    elif action == "check-out":
        if stay["status"] != "CHECKED_IN":
            errors.raise_err(errors.ERR_BOARDING_INVALID_STATE, "Stay not CHECKED_IN.")
        stay["status"] = "CHECKED_OUT"
        stay["board_total_cents"] = calc.boarding_total(
            stay["check_in_date"], stay["check_out_date"], stay["nightly_rate_cents"]
        )
        db.touch(stay)

    elif action == "cancel":
        if stay["status"] not in ("RESERVED", "CHECKED_IN"):
            errors.raise_err(errors.ERR_BOARDING_INVALID_STATE, "Stay not cancellable.")
        stay["status"] = "CANCELLED"
        db.touch(stay)

    return _ok(stay)


# =============================================================================
# LabOrder
# =============================================================================
@bp.route("/clinic/lab-orders", methods=["POST"])
def create_lab_order():
    role = get_role()
    require_roles(role, ("Veterinarian",))
    body = v.get_json_body()
    appointment_id = v.require_str(body, "appointment_id")
    lookup.appointment(appointment_id)
    order_type = v.require_enum(body, "order_type", ORDER_TYPES)
    fee_cents = v.require_int(body, "fee_cents", minimum=0)
    rec = db.new_common()
    rec.update({
        "appointment_id": appointment_id,
        "order_type": order_type,
        "fee_cents": fee_cents,
        "result_text": None,
        "status": "ORDERED",
    })
    db.lab_orders[rec["id"]] = rec
    return _created(rec)


@bp.route("/clinic/lab-orders", methods=["GET"])
def list_lab_orders():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.lab_orders, {"appointment_id": request.args.get("appointment_id")})


@bp.route("/clinic/lab-orders/<loid>", methods=["GET"])
def get_lab_order(loid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.lab_order(loid))


@bp.route("/clinic/lab-orders/<loid>/transition", methods=["POST"])
def transition_lab_order(loid):
    role = get_role()
    require_roles(role, ("Veterinarian",))
    lo = lookup.lab_order(loid)
    body = v.get_json_body()
    action = v.require_str(body, "action")
    if action not in ("collect", "result", "cancel"):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Unknown action.")

    if action == "collect":
        if lo["status"] != "ORDERED":
            errors.raise_err(errors.ERR_LAB_ORDER_INVALID_STATE, "Lab order not ORDERED.")
        lo["status"] = "COLLECTED"
        db.touch(lo)

    elif action == "result":
        if lo["status"] != "COLLECTED":
            errors.raise_err(errors.ERR_LAB_ORDER_INVALID_STATE, "Lab order not COLLECTED.")
        result_text = body.get("result_text")
        if not isinstance(result_text, str) or result_text == "":
            errors.raise_err(errors.ERR_INVALID_REQUEST, "result_text required.")
        lo["status"] = "RESULTED"
        lo["result_text"] = result_text
        db.touch(lo)

    elif action == "cancel":
        if lo["status"] not in ("ORDERED", "COLLECTED"):
            errors.raise_err(errors.ERR_LAB_ORDER_INVALID_STATE, "Lab order not cancellable.")
        lo["status"] = "CANCELLED"
        db.touch(lo)

    return _ok(lo)


# =============================================================================
# Invoice (OCC-guarded finalize)
# =============================================================================
@bp.route("/clinic/invoices", methods=["POST"])
def create_invoice():
    role = get_role()
    require_roles(role, ("PracticeManager",))
    body = v.get_json_body()
    # FK existence (priority 4)
    household_id = v.require_str(body, "household_id")
    household = lookup.household(household_id)
    appointment_id = v.require_str(body, "appointment_id")
    appointment = lookup.appointment(appointment_id)
    estimate = None
    if body.get("estimate_id") is not None:
        estimate = lookup.estimate(body["estimate_id"])
    expected_version = v.require_int(body, "expected_household_version", minimum=0)

    # OCC guard (§2.6) — before any credit is applied
    if expected_version != household["version"]:
        errors.raise_err(errors.ERR_STALE_HOUSEHOLD_VERSION, "Stale household version.")

    # assemble chronological actual charge list (§3.11)
    charges = _assemble_actual_charges(appointment)
    if not charges:
        errors.raise_err(errors.ERR_NO_BILLABLE_ITEMS, "No billable items.")
    raw_actual = sum(charges)
    credit_applied = min(raw_actual, household["account_credit_cents"])
    actual_total = raw_actual - credit_applied

    estimate_total = estimate["estimated_total_cents"] if estimate is not None else 0
    variance = actual_total - estimate_total

    rec = {
        "id": db.new_id(),
        "created_at": calc.to_iso(_now()),
        "_seq": db.next_seq(),
        "household_id": household_id,
        "appointment_id": appointment_id,
        "estimate_id": estimate["id"] if estimate is not None else None,
        "estimate_total_cents": estimate_total,
        "actual_total_cents": actual_total,
        "variance_cents": variance,
        "status": "FINALIZED",
    }
    db.invoices[rec["id"]] = rec

    household["account_credit_cents"] -= credit_applied
    household["lifetime_invoiced_cents"] += actual_total
    db.touch(household)
    return _created(rec)


def _assemble_actual_charges(appointment):
    aid = appointment["id"]
    patient_id = appointment["patient_id"]
    charges = []
    # vaccinations administered within [scheduled_start, finalize_time]
    start = parse_dt(appointment["scheduled_start"])
    finalize_time = _now()
    vaxes = []
    for vx in db.vaccinations.values():
        if vx["patient_id"] != patient_id:
            continue
        adm = parse_dt(vx["administered_at"])
        if start <= adm <= finalize_time:
            vaxes.append(vx)
    vaxes.sort(key=lambda r: (parse_dt(r["administered_at"]), r["_seq"]))
    for vx in vaxes:
        charges.append(vx["fee_cents"])
    # RESULTED lab orders, created_at ASC
    labs = [lo for lo in db.lab_orders.values()
            if lo["appointment_id"] == aid and lo["status"] == "RESULTED"]
    labs.sort(key=lambda r: r["_seq"])
    for lo in labs:
        charges.append(lo["fee_cents"])
    # DONE surgeries, created_at ASC
    surgs = [sg for sg in db.surgeries.values()
             if sg["appointment_id"] == aid and sg["status"] == "DONE"]
    surgs.sort(key=lambda r: r["_seq"])
    for sg in surgs:
        charges.append(sg["surgery_total_cents"] - sg["deposit_consumed_cents"])
    return charges


@bp.route("/clinic/invoices", methods=["GET"])
def list_invoices():
    role = get_role()
    require_roles(role, ALL_ROLES)
    return paginated(db.invoices, {
        "household_id": request.args.get("household_id"),
        "appointment_id": request.args.get("appointment_id"),
        "estimate_id": request.args.get("estimate_id"),
    })


@bp.route("/clinic/invoices/<invid>", methods=["GET"])
def get_invoice(invid):
    role = get_role()
    require_roles(role, ALL_ROLES)
    return _ok(lookup.invoice(invid))


# =============================================================================
# Logical clock (PRD §2.9)
# =============================================================================
def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
