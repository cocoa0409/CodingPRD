"""All read endpoints (PRD section 4, HTTP 200)."""

from flask import Blueprint

import db
import engine
import enums
import middleware
import response
import store
import validators

bp = Blueprint("reads", __name__)

STAFF_READ = ("PlatformAdmin", "PharmacyOperations", "VerifyingPharmacist")
STAFF_AND_TECH = STAFF_READ + ("PackagingTechnician",)
STAFF_TECH_PATIENT = STAFF_AND_TECH + ("Patient",)
STAFF_AND_PATIENT = STAFF_READ + ("Patient",)
STAFF_AND_PRESCRIBER = STAFF_READ + ("Prescriber",)
RX_READERS = STAFF_READ + ("Prescriber", "Patient")


def _paginate(rows, order=None):
    limit, offset = validators.pagination_params()
    ordered = store.ordered(rows) if order is None else order(rows)
    total = len(ordered)
    page = ordered[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return store.serialize_many(page), meta


def _scope_rows(role, user_id, kind, rows):
    if role != "Patient":
        return rows
    return [
        row for row in rows if middleware.owning_patient_id(kind, row) == user_id
    ]


def _matches(row, filters):
    for field, value in filters.items():
        if value is None:
            continue
        if row.get(field) != value:
            return False
    return True


# ------------------------------------------------------------- insurance plans

@bp.get("/insurance-plans/<plan_id>")
def get_insurance_plan(plan_id):
    middleware.authenticate(STAFF_READ)
    plan = middleware.lookup("insurance_plan", plan_id)
    return response.object_response(store.serialize(plan))


# -------------------------------------------------------------------- patients

@bp.get("/patients")
def list_patients():
    middleware.authenticate(STAFF_READ)
    filters = {
        "insurance_plan_id": validators.query_filter("insurance_plan_id"),
        "autoship_status": validators.query_filter(
            "autoship_status", enums.AUTOSHIP_STATUSES
        ),
        "sync_status": validators.query_filter("sync_status", enums.SYNC_STATUSES),
    }
    rows = [row for row in db.patients.values() if _matches(row, filters)]
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    user_id, role = middleware.authenticate(STAFF_TECH_PATIENT)
    patient = middleware.lookup("patient", patient_id)
    middleware.enforce_scope(role, user_id, "patient", patient)
    return response.object_response(store.serialize(patient))


@bp.get("/patients/<patient_id>/adherence-summary")
def get_adherence_summary(patient_id):
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    patient = middleware.lookup("patient", patient_id)
    middleware.enforce_scope(role, user_id, "patient", patient)
    figures = engine.adherence_figures(patient)
    return response.object_response(
        {
            "patient_id": patient["id"],
            "rolling_28_day_score_pct": figures["rolling_28_day_score_pct"],
            "cycle_scoped_score_pct": figures["cycle_scoped_score_pct"],
            "taken_count": figures["taken_count"],
            "missed_count": figures["missed_count"],
            "expected_pouch_count": figures["expected_pouch_count"],
            "consecutive_missed_pickups": patient["consecutive_missed_pickups"],
            "autoship_status": patient["autoship_status"],
        }
    )


# --------------------------------------------------------------- prescriptions

@bp.get("/prescriptions")
def list_prescriptions():
    user_id, role = middleware.authenticate(RX_READERS)
    filters = {
        "patient_id": validators.query_filter("patient_id"),
        "supersedes_rx_id": validators.query_filter("supersedes_rx_id"),
        "status": validators.query_filter("status", enums.PRESCRIPTION_STATUSES),
    }
    rows = [row for row in db.prescriptions.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "prescription", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/prescriptions/<prescription_id>")
def get_prescription(prescription_id):
    user_id, role = middleware.authenticate(RX_READERS)
    prescription = middleware.lookup("prescription", prescription_id)
    middleware.enforce_scope(role, user_id, "prescription", prescription)
    return response.object_response(store.serialize(prescription))


# ----------------------------------------------------------------- fill cycles

@bp.get("/fill-cycles")
def list_fill_cycles():
    user_id, role = middleware.authenticate(STAFF_TECH_PATIENT)
    filters = {
        "patient_id": validators.query_filter("patient_id"),
        "reissue_of_cycle_id": validators.query_filter("reissue_of_cycle_id"),
        "vacation_exception_id": validators.query_filter("vacation_exception_id"),
        "packaging_status": validators.query_filter(
            "packaging_status", enums.PACKAGING_STATUSES
        ),
        "insurance_status": validators.query_filter(
            "insurance_status", enums.INSURANCE_STATUSES
        ),
    }
    rows = [row for row in db.fill_cycles.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "fill_cycle", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/fill-cycles/<cycle_id>")
def get_fill_cycle(cycle_id):
    user_id, role = middleware.authenticate(STAFF_TECH_PATIENT)
    cycle = middleware.lookup("fill_cycle", cycle_id)
    middleware.enforce_scope(role, user_id, "fill_cycle", cycle)
    return response.object_response(store.serialize(cycle))


@bp.get("/fill-cycles/<cycle_id>/adherence-events")
def list_cycle_adherence_events(cycle_id):
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    validators.pagination_params()
    cycle = middleware.lookup("fill_cycle", cycle_id)
    middleware.enforce_scope(role, user_id, "fill_cycle", cycle)
    rows = engine.events_of_cycle(cycle_id)

    def order(items):
        return sorted(items, key=lambda e: (e["occurred_at"], e["created_at"], e["id"]))

    items, meta = _paginate(rows, order=order)
    return response.array_response(items, meta)


# ----------------------------------------------------------------- cycle lines

@bp.get("/cycle-lines")
def list_cycle_lines():
    middleware.authenticate(STAFF_AND_TECH)
    filters = {
        "cycle_id": validators.query_filter("cycle_id"),
        "prescription_id": validators.query_filter("prescription_id"),
        "line_status": validators.query_filter("line_status", enums.LINE_STATUSES),
    }
    rows = [row for row in db.cycle_lines.values() if _matches(row, filters)]
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/cycle-lines/<line_id>")
def get_cycle_line(line_id):
    middleware.authenticate(STAFF_AND_TECH)
    line = middleware.lookup("cycle_line", line_id)
    return response.object_response(store.serialize(line))


# ----------------------------------------------------------------- pouch rolls

@bp.get("/pouch-rolls")
def list_pouch_rolls():
    middleware.authenticate(STAFF_AND_TECH)
    filters = {
        "cycle_id": validators.query_filter("cycle_id"),
        "verification_status": validators.query_filter(
            "verification_status", enums.ROLL_STATUSES
        ),
    }
    rows = [row for row in db.pouch_rolls.values() if _matches(row, filters)]
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/pouch-rolls/<roll_id>")
def get_pouch_roll(roll_id):
    middleware.authenticate(STAFF_AND_TECH)
    roll = middleware.lookup("pouch_roll", roll_id)
    return response.object_response(store.serialize(roll))


# --------------------------------------------------------------------- pouches

@bp.get("/pouches")
def list_pouches():
    middleware.authenticate(STAFF_AND_TECH)
    filters = {
        "roll_id": validators.query_filter("roll_id"),
        "verification_result": validators.query_filter(
            "verification_result", enums.POUCH_RESULTS
        ),
        "dose_slot": validators.query_filter("dose_slot", enums.DOSE_SLOTS),
    }
    rows = [row for row in db.pouches.values() if _matches(row, filters)]
    items, meta = _paginate(
        rows, order=lambda items: sorted(items, key=lambda p: p["pouch_index"])
    )
    return response.array_response(items, meta)


@bp.get("/pouches/<pouch_id>")
def get_pouch(pouch_id):
    middleware.authenticate(STAFF_AND_TECH)
    pouch = middleware.lookup("pouch", pouch_id)
    return response.object_response(store.serialize(pouch))


# ------------------------------------------------------------------- shipments

@bp.get("/shipments")
def list_shipments():
    user_id, role = middleware.authenticate(STAFF_TECH_PATIENT)
    filters = {
        "cycle_id": validators.query_filter("cycle_id"),
        "shipment_kind": validators.query_filter("shipment_kind", enums.SHIPMENT_KINDS),
        "status": validators.query_filter("status", enums.SHIPMENT_STATUSES),
    }
    rows = [row for row in db.shipments.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "shipment", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/shipments/<shipment_id>")
def get_shipment(shipment_id):
    user_id, role = middleware.authenticate(STAFF_TECH_PATIENT)
    shipment = middleware.lookup("shipment", shipment_id)
    middleware.enforce_scope(role, user_id, "shipment", shipment)
    return response.object_response(store.serialize(shipment))


# -------------------------------------------------------- refill authorizations

@bp.get("/refill-authorizations")
def list_refill_authorizations():
    middleware.authenticate(STAFF_AND_PRESCRIBER)
    filters = {
        "prescription_id": validators.query_filter("prescription_id"),
        "status": validators.query_filter("status", enums.AUTH_STATUSES),
    }
    rows = [row for row in db.refill_authorizations.values() if _matches(row, filters)]
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/refill-authorizations/<request_id>")
def get_refill_authorization(request_id):
    middleware.authenticate(STAFF_AND_PRESCRIBER)
    row = middleware.lookup("refill_authorization", request_id)
    return response.object_response(store.serialize(row))


# ---------------------------------------------------------- travel exceptions

@bp.get("/vacation-exceptions")
def list_vacation_exceptions():
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    filters = {
        "patient_id": validators.query_filter("patient_id"),
        "status": validators.query_filter("status", enums.VACATION_STATUSES),
    }
    rows = [row for row in db.vacation_exceptions.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "vacation_exception", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/vacation-exceptions/<request_id>")
def get_vacation_exception(request_id):
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    row = middleware.lookup("vacation_exception", request_id)
    middleware.enforce_scope(role, user_id, "vacation_exception", row)
    return response.object_response(store.serialize(row))


# ---------------------------------------------------------------- credit memos

@bp.get("/credit-memos")
def list_credit_memos():
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    filters = {
        "patient_id": validators.query_filter("patient_id"),
        "cycle_id": validators.query_filter("cycle_id"),
        "applied_to_cycle_id": validators.query_filter("applied_to_cycle_id"),
        "reason": validators.query_filter("reason", enums.MEMO_REASONS),
        "status": validators.query_filter("status", enums.MEMO_STATUSES),
    }
    rows = [row for row in db.credit_memos.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "credit_memo", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/credit-memos/<memo_id>")
def get_credit_memo(memo_id):
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    row = middleware.lookup("credit_memo", memo_id)
    middleware.enforce_scope(role, user_id, "credit_memo", row)
    return response.object_response(store.serialize(row))


# ------------------------------------------------------------ adherence events

@bp.get("/adherence-events")
def list_adherence_events():
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    filters = {
        "cycle_id": validators.query_filter("cycle_id"),
        "event_type": validators.query_filter("event_type", enums.EVENT_TYPES),
        "source": validators.query_filter("source", enums.EVENT_SOURCES),
    }
    rows = [row for row in db.adherence_events.values() if _matches(row, filters)]
    rows = _scope_rows(role, user_id, "adherence_event", rows)
    items, meta = _paginate(rows)
    return response.array_response(items, meta)


@bp.get("/adherence-events/<event_id>")
def get_adherence_event(event_id):
    user_id, role = middleware.authenticate(STAFF_AND_PATIENT)
    row = middleware.lookup("adherence_event", event_id)
    middleware.enforce_scope(role, user_id, "adherence_event", row)
    return response.object_response(store.serialize(row))
