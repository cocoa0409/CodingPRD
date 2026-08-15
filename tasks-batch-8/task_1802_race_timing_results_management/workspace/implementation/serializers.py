"""Entity -> JSON dict serializers. Datetimes are stored internally as
aware datetimes and rendered here with fmt_dt."""
from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_race(r):
    out = _common(r)
    out.update(
        {
            "name": r["name"],
            "race_date": fmt_dt(r["race_date"]),
            "distance_km": r["distance_km"],
            "course_type": r["course_type"],
            "course_time_limit_minutes": r["course_time_limit_minutes"],
            "qualifying_standard_ms": r["qualifying_standard_ms"],
            "status": r["status"],
            "timing_locked_at": fmt_dt(r["timing_locked_at"]),
            "locked_by_user_id": r["locked_by_user_id"],
            "timing_config_fingerprint": r["timing_config_fingerprint"],
            "provisional_published_at": fmt_dt(r["provisional_published_at"]),
            "protest_window_closes_at": fmt_dt(r["protest_window_closes_at"]),
            "finalized_at": fmt_dt(r["finalized_at"]),
            "amendment_count": r["amendment_count"],
        }
    )
    return out


def ser_wave(w):
    out = _common(w)
    out.update(
        {
            "race_id": w["race_id"],
            "wave_index": w["wave_index"],
            "scheduled_start_time": fmt_dt(w["scheduled_start_time"]),
            "max_capacity": w["max_capacity"],
            "actual_start_time": fmt_dt(w["actual_start_time"]),
            "status": w["status"],
        }
    )
    return out


def ser_timing_point(p):
    out = _common(p)
    out.update(
        {
            "race_id": p["race_id"],
            "point_index": p["point_index"],
            "kind": p["kind"],
            "distance_km": p["distance_km"],
            "device_id": p["device_id"],
            "deploy_at": fmt_dt(p["deploy_at"]),
            "expected_teardown_at": fmt_dt(p["expected_teardown_at"]),
            "status": p["status"],
        }
    )
    return out


def ser_registration(r):
    out = _common(r)
    out.update(
        {
            "race_id": r["race_id"],
            "wave_id": r["wave_id"],
            "chip_id": r["chip_id"],
            "bib_number": r["bib_number"],
            "participant_name": r["participant_name"],
            "birth_date": r["birth_date"],
            "gender": r["gender"],
            "lifecycle_status": r["lifecycle_status"],
            "payment_status": r["payment_status"],
            "age_on_race_day": r["age_on_race_day"],
            "age_group": r["age_group"],
        }
    )
    return out


def ser_chip(c):
    out = _common(c)
    out.update(
        {
            "chip_code": c["chip_code"],
            "status": c["status"],
            "current_registration_id": c["current_registration_id"],
        }
    )
    return out


def ser_timing_read(r):
    # Append-only log: id + created_at only; no updated_at / version.
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "timing_point_id": r["timing_point_id"],
        "chip_id": r["chip_id"],
        "read_timestamp": fmt_dt(r["read_timestamp"]),
        "status": r["status"],
        "reject_reason": r["reject_reason"],
        "adjusted_by_correction_id": r["adjusted_by_correction_id"],
    }


def ser_result(r):
    out = _common(r)
    out.update(
        {
            "race_id": r["race_id"],
            "registration_id": r["registration_id"],
            "status": r["status"],
            "exclusion_reason": r["exclusion_reason"],
            "chip_time_ms": r["chip_time_ms"],
            "gun_time_ms": r["gun_time_ms"],
            "finish_timestamp": fmt_dt(r["finish_timestamp"]),
            "completed_splits": r["completed_splits"],
            "overall_rank_gun": r["overall_rank_gun"],
            "age_group_rank_chip": r["age_group_rank_chip"],
            "qualified": r["qualified"],
            "revision": r["revision"],
        }
    )
    return out


def ser_result_flag(f):
    out = _common(f)
    out.update(
        {
            "registration_id": f["registration_id"],
            "flag_type": f["flag_type"],
            "origin": f["origin"],
            "status": f["status"],
            "detail": f["detail"],
        }
    )
    return out


def ser_protest(p):
    out = _common(p)
    out.update(
        {
            "race_id": p["race_id"],
            "registration_id": p["registration_id"],
            "timing_read_id": p["timing_read_id"],
            "requested_action": p["requested_action"],
            "corrected_timestamp": fmt_dt(p["corrected_timestamp"]),
            "reason": p["reason"],
            "filed_by_user_id": p["filed_by_user_id"],
            "status": p["status"],
            "resolved_by_user_id": p["resolved_by_user_id"],
        }
    )
    return out


def ser_correction(c):
    out = _common(c)
    out.update(
        {
            "race_id": c["race_id"],
            "timing_read_id": c["timing_read_id"],
            "kind": c["kind"],
            "corrected_timestamp": fmt_dt(c["corrected_timestamp"]),
            "reason": c["reason"],
            "protest_id": c["protest_id"],
            "status": c["status"],
            "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        }
    )
    return out


def ser_certification(c):
    out = _common(c)
    out.update(
        {
            "race_id": c["race_id"],
            "status": c["status"],
            "issued_by_user_id": c["issued_by_user_id"],
            "issued_at": fmt_dt(c["issued_at"]),
            "qualified_count": c["qualified_count"],
            "revocation_reason": c["revocation_reason"],
        }
    )
    return out


def ser_award(a):
    out = _common(a)
    out.update(
        {
            "race_id": a["race_id"],
            "registration_id": a["registration_id"],
            "category": a["category"],
            "place": a["place"],
            "basis": a["basis"],
            "basis_time_ms": a["basis_time_ms"],
            "status": a["status"],
        }
    )
    return out
