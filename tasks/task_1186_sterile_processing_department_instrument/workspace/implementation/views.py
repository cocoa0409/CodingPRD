"""Resource representations. Datetimes/Decimals are converted by
common.jsonable() at the envelope boundary, so there is exactly one renderer.

AssemblyVerification is an immutable audit entry: only id + created_at
(no updated_at, no version — PRD section 2.5).
"""
import domain

_COMMON = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY = ("id", "created_at")


def _pick(record, keys):
    return dict((k, record.get(k)) for k in keys)


TRAY_TEMPLATE_FIELDS = _COMMON + (
    "code", "name", "specialty", "packaging_type", "instrument_requirements",
    "assembly_minutes",
)

TRAY_FIELDS = _COMMON + (
    "template_id", "label", "status", "current_load_id",
    "sterility_expires_at", "cycles_completed", "quarantine_reason",
)

ASSEMBLY_VERIFICATION_FIELDS = _APPEND_ONLY + (
    "tray_id", "technician_id", "lines", "result", "mismatch_count",
)

INSTRUMENT_FIELDS = _COMMON + (
    "instrument_type", "serial_number", "max_cycles", "usage_cycles",
    "replacement_cost_cents", "criticality", "status", "repair_count",
    "assigned_tray_id",
)

REPAIR_ORDER_FIELDS = _COMMON + (
    "instrument_id", "status", "vendor", "quoted_cost_cents",
    "actual_cost_cents", "recommended_outcome", "outcome", "outcome_overridden",
)

STERILIZER_FIELDS = _COMMON + (
    "name", "method", "chamber_capacity", "cycle_minutes",
    "required_certification_level", "status",
)

LOAD_FIELDS = _COMMON + (
    "sterilizer_id", "operator_id", "planned_start_at", "started_at",
    "completed_at", "released_at", "status", "tray_count",
    "total_chargeback_cents", "recall_reason", "recalled_at",
)

BI_FIELDS = _COMMON + (
    "load_id", "lot_number", "status", "result", "due_at", "recorded_at",
)

OR_CASE_FIELDS = _COMMON + (
    "case_number", "surgeon", "scheduled_start_at", "scheduled_end_at",
    "priority", "status", "completed_at",
)

RESERVATION_FIELDS = _COMMON + (
    "case_id", "tray_id", "status", "reserved_at",
)

IUSS_FIELDS = _COMMON + (
    "tray_id", "case_id", "justification", "logged_by_id", "logged_at",
    "status", "review_note",
)

TECHNICIAN_FIELDS = _COMMON + (
    "name", "certification_level", "certified_methods",
    "certification_expires_at", "status", "competency_score",
    "competency_score_lifetime",
)

LOANER_FIELDS = _COMMON + (
    "vendor", "case_id", "tray_count", "due_by", "received_at",
    "received_late", "status",
)


def tray_template_view(r):
    out = _pick(r, TRAY_TEMPLATE_FIELDS)
    out["instrument_requirements"] = [dict(line) for line in
                                      (r.get("instrument_requirements") or [])]
    return out


def tray_view(r):
    return _pick(r, TRAY_FIELDS)


def assembly_verification_view(r):
    out = _pick(r, ASSEMBLY_VERIFICATION_FIELDS)
    out["lines"] = [dict(line) for line in (r.get("lines") or [])]
    return out


def instrument_view(r):
    return _pick(r, INSTRUMENT_FIELDS)


def repair_order_view(r):
    return _pick(r, REPAIR_ORDER_FIELDS)


def sterilizer_view(r):
    return _pick(r, STERILIZER_FIELDS)


def load_view(r):
    out = _pick(r, LOAD_FIELDS)
    out["tray_count"] = domain.tray_count(r)
    return out


def bi_view(r):
    return _pick(r, BI_FIELDS)


def or_case_view(r):
    return _pick(r, OR_CASE_FIELDS)


def reservation_view(r):
    return _pick(r, RESERVATION_FIELDS)


def iuss_view(r):
    return _pick(r, IUSS_FIELDS)


def technician_view(r):
    out = _pick(r, TECHNICIAN_FIELDS)
    rolling, lifetime = domain.competency_scores(r["id"])
    out["competency_score"] = domain.score_number(rolling)
    out["competency_score_lifetime"] = domain.score_number(lifetime)
    return out


def loaner_view(r):
    return _pick(r, LOANER_FIELDS)
