"""Serializers — public JSON representation of each entity.

Field lists come verbatim from the scaffold §1.1 entity table plus the common
fields (id, created_at, updated_at, version) from PRD §2.4.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _project(record, fields):
    return {k: record.get(k) for k in (_COMMON + fields)}


def importer_view(r):
    return _project(r, [
        "name", "ior_number", "owner_user_id", "continuous_bond_id", "status",
    ])


def bond_view(r):
    return _project(r, [
        "importer_id", "bond_type", "limit_cents",
        "outstanding_liability_cents", "status",
    ])


def isf_view(r):
    return _project(r, [
        "importer_id", "bill_of_lading", "vessel_eta", "data_element_count",
        "filed_at", "late_filing", "status",
    ])


def entry_view(r):
    return _project(r, [
        "importer_id", "bond_id", "isf_filing_id", "statement_id",
        "entry_type", "country_of_origin", "entry_date",
        "provisional_total_cents", "final_total_cents", "total_duties_owed_cents",
        "filed_by_user_id", "reviewed_by_user_id", "status",
    ])


def line_view(r):
    return _project(r, [
        "entry_id", "hts_code", "customs_value_cents", "assists_cents",
        "quantity", "preference_claim", "pga_flag",
        "dutiable_value_cents", "line_duty_cents", "preference_verified",
    ])


def pga_view(r):
    return _project(r, [
        "entry_id", "agency", "decision", "reviewed_by_user_id",
    ])


def exam_slot_view(r):
    return _project(r, [
        "station_code", "entry_id", "window_start", "window_end", "status",
    ])


def statement_view(r):
    return _project(r, [
        "importer_id", "period_month", "statement_total_cents",
        "entry_count", "status",
    ])


def psc_view(r):
    return _project(r, [
        "entry_id", "filing_kind", "corrected_value_delta_cents",
        "adjustment_cents", "status",
    ])
