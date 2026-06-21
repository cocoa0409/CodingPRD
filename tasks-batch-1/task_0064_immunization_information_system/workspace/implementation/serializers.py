def ser_patient(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "state_code": p["state_code"],
        "schedule_status": p["schedule_status"],
        "active_certificate_id": p["active_certificate_id"],
    }


def ser_provider(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "vfc_pin": p["vfc_pin"],
        "authorized_product_codes": list(p["authorized_product_codes"]),
        "status": p["status"],
    }


def ser_product(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "product_code": p["product_code"],
        "antigen": p["antigen"],
        "doses_in_series": p["doses_in_series"],
        "min_age_days": p["min_age_days"],
        "recommended_age_days": p["recommended_age_days"],
        "min_interval_days": p["min_interval_days"],
        "grace_period_days": p["grace_period_days"],
        "status": p["status"],
    }


def ser_lot(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "product_id": l["product_id"],
        "lot_number": l["lot_number"],
        "received_date": l["received_date"],
        "expiration_date": l["expiration_date"],
        "doses_total": l["doses_total"],
        "administered_count": l["administered_count"],
        "status": l["status"],
    }


def ser_immunization(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "patient_id": i["patient_id"],
        "lot_id": i["lot_id"],
        "provider_id": i["provider_id"],
        "report_id": i["report_id"],
        "administered_date": i["administered_date"],
        "dose_number": i["dose_number"],
        "validity": i["validity"],
        "status": i["status"],
    }


def ser_allergy(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "patient_id": a["patient_id"],
        "antigen": a["antigen"],
        "severity": a["severity"],
        "origin": a["origin"],
        "source_event_id": a["source_event_id"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "provider_id": r["provider_id"],
        "line_count": r["line_count"],
        "accepted_count": r["accepted_count"],
        "rejected_count": r["rejected_count"],
        "status": r["status"],
    }


def ser_adverse(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "immunization_id": a["immunization_id"],
        "patient_id": a["patient_id"],
        "seriousness": a["seriousness"],
        "symptoms": a["symptoms"],
        "status": a["status"],
    }


def ser_evaluation(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "patient_id": e["patient_id"],
        "as_of_date": e["as_of_date"],
        "overall_status": e["overall_status"],
        "antigen_results": e["antigen_results"],
        "completeness_pct": e["completeness_pct"],
    }


def ser_certificate(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "patient_id": c["patient_id"],
        "evaluation_id": c["evaluation_id"],
        "certificate_type": c["certificate_type"],
        "status": c["status"],
    }


def ser_recall(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "lot_id": r["lot_id"],
        "reason": r["reason"],
        "invalidated_count": r["invalidated_count"],
        "status": r["status"],
    }
