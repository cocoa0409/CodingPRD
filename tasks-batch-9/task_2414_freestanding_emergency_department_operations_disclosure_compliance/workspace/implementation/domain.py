"""Derivations, serialisers and the cross-entity cascades."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from constants import (
    ACUITY_ALLOWANCE_CENTS,
    ALL_ANCILLARY_CODES,
    BOARD_CERT_MIN_SHARE,
    CATEGORY_CODES,
    COVERAGE_FLOOR_HOURS_PER_DAY,
    DEFECT_RESTRICT_THRESHOLD,
    ESTIMATE_TIER_B_THRESHOLD_CENTS,
    ESTIMATE_TIER_C_THRESHOLD_CENTS,
    FORECAST_WINDOW_DAYS,
    MEAN_WEIGHT,
    PATIENTS_PER_PHYSICIAN_HOUR,
    PEAK_WEIGHT,
    PHARMACY_TIER_CODES,
    POSTURE_CHANGE_SEVERITY,
    RESTRICTED_CODES_BY_POSTURE,
    SIGNAGE_VALIDITY_DAYS,
    STATE_BENCHMARK_RATE,
    TIER_A_RATE,
    TIER_B_RATE,
    TIER_C_RATE,
)
from db import db, iso, new_id, row_key, sorted_rows, touch
from errors import ApiError
from validate import num, quarter_ceiling, rh, rh2

UTC = timezone.utc


# --- lookups -------------------------------------------------------------


def _find(table, row_id, error_id):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def get_facility(fid):
    return _find(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")


def get_template(tid):
    return _find(db.templates, tid, "ERR_DISCLOSURE_TEMPLATE_NOT_FOUND")


def get_contract(cid):
    return _find(db.contracts, cid, "ERR_PAYER_CONTRACT_NOT_FOUND")


def get_shift(sid):
    return _find(db.shifts, sid, "ERR_PHYSICIAN_SHIFT_NOT_FOUND")


def get_forecast(fid):
    return _find(db.forecasts, fid, "ERR_VOLUME_FORECAST_NOT_FOUND")


def get_agreement(aid):
    return _find(db.agreements, aid, "ERR_TRANSFER_AGREEMENT_NOT_FOUND")


def get_mou(mid):
    return _find(db.mous, mid, "ERR_AMBULANCE_MOU_NOT_FOUND")


def get_encounter(eid):
    return _find(db.encounters, eid, "ERR_ENCOUNTER_NOT_FOUND")


def get_ancillary(oid):
    return _find(db.ancillary_orders, oid, "ERR_ANCILLARY_ORDER_NOT_FOUND")


def get_transfer_order(oid):
    return _find(db.transfer_orders, oid, "ERR_TRANSFER_ORDER_NOT_FOUND")


def get_claim(cid):
    return _find(db.claims, cid, "ERR_CLAIM_NOT_FOUND")


def get_dispute(did):
    return _find(db.disputes, did, "ERR_DISPUTE_CASE_NOT_FOUND")


def rows_of(table, **filters):
    out = []
    for row in table.values():
        if all(row.get(key) == value for key, value in filters.items()):
            out.append(row)
    return sorted_rows(out)


def clock_date_str():
    return db.clock.astimezone(UTC).strftime("%Y-%m-%d")


# --- derived statuses ----------------------------------------------------


def contract_status(contract):
    today = clock_date_str()
    if contract["effective_start_date"] <= today <= contract["effective_end_date"]:
        return "ACTIVE"
    return "TERMINATED"


def contract_idr_eligible(contract):
    return (
        contract["network_status"] == "OUT_OF_NETWORK"
        and contract["state_protection_regime"] != "STATE_EXEMPT_FSED"
    )


def agreement_status(agreement):
    today = clock_date_str()
    if today < agreement["effective_start_date"]:
        return "PENDING"
    if today <= agreement["effective_end_date"]:
        return "ACTIVE"
    return "EXPIRED"


def mou_status(mou):
    return "ACTIVE" if db.clock < mou["coverage_end_at"] else "EXPIRED"


def mou_units_reserved(mou):
    return sum(
        1
        for order in db.transfer_orders.values()
        if order["ambulance_mou_id"] == mou["id"]
        and order["status"] in ("REQUESTED", "ACCEPTED")
    )


def mou_units_available(mou):
    return mou["units_committed"] - mou_units_reserved(mou)


def mou_saturation_state(mou):
    return "SATURATED" if mou_units_available(mou) == 0 else "AVAILABLE"


def facility_ambulance_totals(facility):
    committed = 0
    reserved = 0
    for mou in db.mous.values():
        if mou["facility_id"] != facility["id"]:
            continue
        if mou_status(mou) != "ACTIVE":
            continue
        committed += mou["units_committed"]
        reserved += mou_units_reserved(mou)
    return committed, reserved


def facility_transfer_capacity_state(facility):
    committed, reserved = facility_ambulance_totals(facility)
    return "AVAILABLE" if committed - reserved > 0 else "SATURATED"


def observation_beds_occupied(facility):
    return sum(
        1
        for enc in db.encounters.values()
        if enc["facility_id"] == facility["id"] and enc["observation_bed_held"]
    )


def declined_transfer_count(encounter):
    return sum(
        1
        for order in db.transfer_orders.values()
        if order["encounter_id"] == encounter["id"] and order["status"] == "DECLINED"
    )


# --- posture -------------------------------------------------------------


def settled_signage_status(facility):
    status = facility["signage_attestation_status"]
    expires = facility["signage_expires_at"]
    if status == "ATTESTED" and expires is not None and db.clock >= expires:
        return "LAPSED"
    return status


def compute_posture(facility, signage_status=None):
    signage = signage_status or settled_signage_status(facility)
    if facility["license_status"] == "SUSPENDED":
        return "SUSPENDED"
    if facility["license_status"] == "PROBATION":
        return "RESTRICTED"
    if signage != "ATTESTED":
        return "RESTRICTED"
    if facility["current_published_template_id"] is None:
        return "RESTRICTED"
    if facility["open_compliance_defect_count"] >= DEFECT_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


def effective_posture(facility):
    """Pure read of the posture a gate should consult (no side effects)."""
    return compute_posture(facility)


def effective_restricted_codes(facility):
    return list(RESTRICTED_CODES_BY_POSTURE[effective_posture(facility)])


def recompute_posture(facility):
    """Mutating recomputation: settles signage aging, persists the posture, and
    on an actual change appends POSTURE_CHANGE, bumps version and (OPEN ->
    RESTRICTED only) fires the forecast cascade."""
    signage = settled_signage_status(facility)
    facility["signage_attestation_status"] = signage
    previous = facility["compliance_posture"]
    posture = compute_posture(facility, signage)
    facility["compliance_posture"] = posture
    facility["restricted_service_codes"] = list(RESTRICTED_CODES_BY_POSTURE[posture])
    if posture == previous:
        return False
    append_ledger(
        facility,
        "POSTURE_CHANGE",
        POSTURE_CHANGE_SEVERITY[posture],
        "FACILITY",
        facility["id"],
        "Facility compliance posture changed from %s to %s." % (previous, posture),
        defect_counted=False,
    )
    touch(facility)
    if previous == "OPEN" and posture == "RESTRICTED":
        escalate_forecasts(facility)
    return True


# --- compliance ledger ---------------------------------------------------


def append_ledger(
    facility, event_type, severity, subject_type, subject_id, detail, defect_counted=False
):
    entry = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
        "facility_id": facility["id"],
        "event_type": event_type,
        "severity": severity,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "detail": detail,
        "recorded_at": db.clock,
        "defect_counted": bool(defect_counted),
    }
    db.ledger[entry["id"]] = entry
    return entry


def record_defect(facility, event_type, severity, subject_type, subject_id, detail):
    """Append a defect-counted finding, increment the counter and run the
    posture recomputation cascade."""
    append_ledger(
        facility, event_type, severity, subject_type, subject_id, detail, defect_counted=True
    )
    facility["open_compliance_defect_count"] += 1
    touch(facility)
    recompute_posture(facility)


# --- forecasting ---------------------------------------------------------


def compute_required_coverage(forecast):
    volumes = forecast["historical_daily_volumes"]
    if not volumes:
        forecast["forecast_basis"] = "FLOOR_ONLY"
        daily = Decimal("0.00")
        per_day = Decimal(COVERAGE_FLOOR_HOURS_PER_DAY)
    else:
        forecast["forecast_basis"] = "HISTORY"
        window = volumes[-FORECAST_WINDOW_DAYS:]
        window_mean = rh2(Decimal(sum(window)) / Decimal(len(window)))
        if forecast["method"] == "TRAILING_MEAN":
            daily = window_mean
        else:
            daily = rh2(
                Decimal(PEAK_WEIGHT) * Decimal(max(window))
                + Decimal(MEAN_WEIGHT) * window_mean
            )
        raw_hours = daily / Decimal(PATIENTS_PER_PHYSICIAN_HOUR)
        per_day = max(Decimal(COVERAGE_FLOOR_HOURS_PER_DAY), quarter_ceiling(raw_hours))
    forecast["forecast_daily_volume"] = rh2(daily)
    forecast["required_physician_hours_per_day"] = rh2(per_day)
    total = rh2(rh2(per_day) * Decimal(forecast["period_days"]))
    forecast["required_physician_hours_total"] = total
    forecast["required_board_certified_hours_total"] = rh2(
        total * Decimal(BOARD_CERT_MIN_SHARE)
    )


def _period_bounds(forecast):
    start = datetime.strptime(forecast["period_start_date"], "%Y-%m-%d").replace(tzinfo=UTC)
    end = start + timedelta(days=forecast["period_days"])
    return start, end


def reconcile_coverage(facility, forecast):
    """Returns (scheduled_hours, board_certified_hours, deficit_hours, compliant)."""
    period_start, period_end = _period_bounds(forecast)
    candidates = [
        shift
        for shift in db.shifts.values()
        if shift["facility_id"] == facility["id"]
        and shift["role_type"] == "PHYSICIAN"
        and shift["start_utc"] < period_end
        and shift["end_utc"] > period_start
    ]
    total = Decimal("0")
    board = Decimal("0")
    for shift in sorted_rows(candidates):
        span_end = min(shift["end_utc"], period_end)
        span_start = max(shift["start_utc"], period_start)
        seconds = int((span_end - span_start).total_seconds())
        hours = rh2(Decimal(seconds) / Decimal(3600))
        total += hours
        if shift["board_certified"]:
            board += hours
    scheduled = rh2(total)
    board_hours = rh2(board)
    deficit = rh2(forecast["required_physician_hours_total"] - scheduled)
    if deficit < 0:
        deficit = Decimal("0.00")
    compliant = deficit == 0 and board_hours >= forecast["required_board_certified_hours_total"]
    return scheduled, board_hours, deficit, compliant


def active_forecasts(facility):
    return [
        fc
        for fc in db.forecasts.values()
        if fc["facility_id"] == facility["id"] and fc["status"] == "ACTIVE"
    ]


def select_active_forecast(facility):
    candidates = active_forecasts(facility)
    if not candidates:
        return None
    candidates.sort(key=lambda fc: (_negated_date(fc["period_start_date"]),) + row_key(fc))
    return candidates[0]


def _negated_date(value):
    """Sort key producing period_start_date DESC."""
    return tuple(-int(part) for part in value.split("-"))


def refresh_coverage_flag(facility):
    forecast = select_active_forecast(facility)
    if forecast is None:
        facility["coverage_deficit_flag"] = False
        return
    _, _, deficit, _ = reconcile_coverage(facility, forecast)
    facility["coverage_deficit_flag"] = deficit > 0


def escalate_forecasts(facility):
    """OPEN -> RESTRICTED cascade: escalate ACTIVE TRAILING_MEAN forecasts to
    PEAK_ADJUSTED, recompute their required hours, then recompute the facility's
    coverage_deficit_flag from the selected active forecast."""
    for forecast in active_forecasts(facility):
        if forecast["method"] != "TRAILING_MEAN":
            continue
        forecast["method"] = "PEAK_ADJUSTED"
        forecast["escalated_by_posture"] = True
        compute_required_coverage(forecast)
        touch(forecast)
    refresh_coverage_flag(facility)


# --- estimates and pricing ----------------------------------------------


def disclosed_estimate_cents(template, acuity_level):
    base = template["facility_fee_cents"] + ACUITY_ALLOWANCE_CENTS[acuity_level]
    if base < ESTIMATE_TIER_B_THRESHOLD_CENTS:
        rate = Decimal(TIER_A_RATE)
    elif base < ESTIMATE_TIER_C_THRESHOLD_CENTS:
        rate = Decimal(TIER_B_RATE)
    else:
        rate = Decimal(TIER_C_RATE)
    surcharge = rh(Decimal(base) * rate)
    return base + surcharge


def code_in_scope(facility, category, code):
    if category == "IMAGING":
        return code in facility["imaging_scope"]
    if category == "LABORATORY":
        return code in facility["lab_scope"]
    return code in PHARMACY_TIER_CODES[facility["pharmacy_scope_tier"]]


def category_of(code):
    for category, codes in CATEGORY_CODES.items():
        if code in codes:
            return category
    return None


# --- claim settlement ---------------------------------------------------


def claim_line_set(claim):
    lines = [claim["billed_facility_fee_cents"]]
    resulted = [
        order
        for order in db.ancillary_orders.values()
        if order["encounter_id"] == claim["encounter_id"] and order["status"] == "RESULTED"
    ]
    for order in sorted_rows(resulted):
        lines.append(order["line_total_cents"])
    return lines


def allowed_total_for(claim, contract, billed_total):
    if claim["protection_variant"] == "PROTECTED_STATE":
        benchmark = rh(Decimal(billed_total) * Decimal(STATE_BENCHMARK_RATE))
        return max(contract["qualifying_payment_amount_cents"], benchmark)
    return contract["qualifying_payment_amount_cents"]


def settle_claim(claim, contract, allowed_total=None):
    """Steps 1-6 of calculations.claim_settlement, writing the claim's money
    fields. `allowed_total` overrides step two (the IDR award path)."""
    lines = claim_line_set(claim)
    billed_total = sum(lines)
    if allowed_total is None:
        allowed_total = allowed_total_for(claim, contract, billed_total)

    # Step 3 - per-line allocation, residual on the last line.
    allocations = []
    if billed_total == 0:
        allocations = [0] * (len(lines) - 1)
    else:
        for billed in lines[:-1]:
            allocations.append(
                rh(Decimal(allowed_total) * Decimal(billed) / Decimal(billed_total))
            )
    allocations.append(allowed_total - sum(allocations))

    # Step 4 - deductible waterfall in set order.
    remaining = contract["in_network_deductible_remaining_cents"]
    deductibles = []
    for share in allocations:
        absorbed = min(remaining, share) if share > 0 else 0
        remaining -= absorbed
        deductibles.append(absorbed)

    # Step 5 - coinsurance rounded per line, then summed.
    rate = contract["in_network_coinsurance_rate"]
    coinsurance = [
        rh(Decimal(allocations[i] - deductibles[i]) * rate) for i in range(len(allocations))
    ]
    cost_share = sum(deductibles) + sum(coinsurance)

    # Step 6 - variant-specific settlement.
    unallowed = billed_total - allowed_total
    if claim["protection_variant"] in ("PROTECTED_NSA", "PROTECTED_STATE"):
        patient = cost_share
        balance_bill = 0
        written_off = unallowed
    else:
        patient = cost_share + unallowed
        balance_bill = unallowed
        written_off = 0

    claim["allowed_amount_cents"] = allowed_total
    claim["plan_paid_cents"] = allowed_total - cost_share
    claim["patient_responsibility_cents"] = patient
    claim["balance_bill_amount_cents"] = balance_bill
    claim["written_off_cents"] = written_off


def select_protection_variant(contract, encounter):
    disclosure = encounter["disclosure_state"]
    if disclosure in ("DISCLOSURE_REFUSED", "DISCLOSURE_DEFECT"):
        return "PROTECTED_NSA"
    if contract["network_status"] == "IN_NETWORK":
        return "PROTECTED_NSA"
    if contract["state_protection_regime"] == "FEDERAL_NSA_ONLY":
        return "PROTECTED_NSA"
    if contract["state_protection_regime"] == "STATE_PROTECTED_FSED":
        return "PROTECTED_STATE"
    return "UNPROTECTED"


# --- disclosure defect at disposition -----------------------------------


def fire_disclosure_defect(facility, encounter):
    if encounter["disclosure_state"] != "DISCLOSURE_PRESENTED":
        return
    encounter["disclosure_state"] = "DISCLOSURE_DEFECT"
    record_defect(
        facility,
        "DISCLOSURE_DEFECT",
        "MAJOR",
        "ENCOUNTER",
        encounter["id"],
        "Encounter reached disposition with the disclosure conversation still open.",
    )


# --- serialisers ---------------------------------------------------------


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def facility_view(facility):
    signage = settled_signage_status(facility)
    posture = compute_posture(facility, signage)
    committed, reserved = facility_ambulance_totals(facility)
    data = {
        "name": facility["name"],
        "state_code": facility["state_code"],
        "license_category": facility["license_category"],
        "license_status": facility["license_status"],
        "signage_attestation_status": signage,
        "signage_attested_at": iso(facility["signage_attested_at"]),
        "signage_expires_at": iso(facility["signage_expires_at"]),
        "signage_attested_by_user_id": facility["signage_attested_by_user_id"],
        "observation_bed_count": facility["observation_bed_count"],
        "observation_beds_occupied": observation_beds_occupied(facility),
        "imaging_scope": list(facility["imaging_scope"]),
        "lab_scope": list(facility["lab_scope"]),
        "pharmacy_scope_tier": facility["pharmacy_scope_tier"],
        "max_concurrent_physicians": facility["max_concurrent_physicians"],
        "open_compliance_defect_count": facility["open_compliance_defect_count"],
        "compliance_posture": posture,
        "restricted_service_codes": list(RESTRICTED_CODES_BY_POSTURE[posture]),
        "current_published_template_id": facility["current_published_template_id"],
        "ambulance_units_committed_total": committed,
        "ambulance_units_reserved_total": reserved,
        "transfer_capacity_state": "AVAILABLE" if committed - reserved > 0 else "SATURATED",
        "coverage_deficit_flag": facility["coverage_deficit_flag"],
    }
    data.update(_common(facility))
    return data


def template_view(template):
    data = {
        "facility_id": template["facility_id"],
        "version_label": template["version_label"],
        "supersedes_version_label": template["supersedes_version_label"],
        "facility_fee_cents": template["facility_fee_cents"],
        "observation_hourly_cents": template["observation_hourly_cents"],
        "network_status_statement": template["network_status_statement"],
        "required_signage_elements": list(template["required_signage_elements"]),
        "status": template["status"],
        "published_at": iso(template["published_at"]),
        "published_by_user_id": template["published_by_user_id"],
    }
    data.update(_common(template))
    return data


def contract_view(contract):
    data = {
        "facility_id": contract["facility_id"],
        "payer_name": contract["payer_name"],
        "network_status": contract["network_status"],
        "qualifying_payment_amount_cents": contract["qualifying_payment_amount_cents"],
        "in_network_coinsurance_rate": num(contract["in_network_coinsurance_rate"]),
        "in_network_deductible_remaining_cents": contract[
            "in_network_deductible_remaining_cents"
        ],
        "state_protection_regime": contract["state_protection_regime"],
        "effective_start_date": contract["effective_start_date"],
        "effective_end_date": contract["effective_end_date"],
        "status": contract_status(contract),
        "idr_eligible": contract_idr_eligible(contract),
    }
    data.update(_common(contract))
    return data


def shift_view(shift):
    data = {
        "facility_id": shift["facility_id"],
        "clinician_user_id": shift["clinician_user_id"],
        "role_type": shift["role_type"],
        "board_certified": shift["board_certified"],
        "start_utc": iso(shift["start_utc"]),
        "end_utc": iso(shift["end_utc"]),
        "duration_hours": num(shift["duration_hours"]),
    }
    data.update(_common(shift))
    return data


def forecast_view(forecast):
    facility = db.facilities[forecast["facility_id"]]
    scheduled, _, deficit, _ = reconcile_coverage(facility, forecast)
    data = {
        "facility_id": forecast["facility_id"],
        "period_start_date": forecast["period_start_date"],
        "period_days": forecast["period_days"],
        "historical_daily_volumes": list(forecast["historical_daily_volumes"]),
        "method": forecast["method"],
        "forecast_basis": forecast["forecast_basis"],
        "forecast_daily_volume": num(forecast["forecast_daily_volume"]),
        "required_physician_hours_per_day": num(
            forecast["required_physician_hours_per_day"]
        ),
        "required_physician_hours_total": num(forecast["required_physician_hours_total"]),
        "required_board_certified_hours_total": num(
            forecast["required_board_certified_hours_total"]
        ),
        "scheduled_physician_hours": num(scheduled),
        "coverage_deficit_hours": num(deficit),
        "escalated_by_posture": forecast["escalated_by_posture"],
        "status": forecast["status"],
    }
    data.update(_common(forecast))
    return data


def encounter_view(encounter):
    data = {
        "facility_id": encounter["facility_id"],
        "pinned_disclosure_template_id": encounter["pinned_disclosure_template_id"],
        "patient_reference": encounter["patient_reference"],
        "acuity_level": encounter["acuity_level"],
        "presenting_service_line": encounter["presenting_service_line"],
        "arrival_at": iso(encounter["arrival_at"]),
        "registered_by_user_id": encounter["registered_by_user_id"],
        "clinical_state": encounter["clinical_state"],
        "disclosure_state": encounter["disclosure_state"],
        "disclosure_decided_by_user_id": encounter["disclosure_decided_by_user_id"],
        "disclosed_estimate_cents": encounter["disclosed_estimate_cents"],
        "mse_start_deadline_at": iso(encounter["mse_start_deadline_at"]),
        "mse_started_at": iso(encounter["mse_started_at"]),
        "mse_completed_at": iso(encounter["mse_completed_at"]),
        "mse_physician_user_id": encounter["mse_physician_user_id"],
        "mse_timeliness": encounter["mse_timeliness"],
        "stabilization_status": encounter["stabilization_status"],
        "observation_bed_held": encounter["observation_bed_held"],
        "observation_started_at": iso(encounter["observation_started_at"]),
        "declined_transfer_count": declined_transfer_count(encounter),
    }
    data.update(_common(encounter))
    return data


def ancillary_view(order):
    data = {
        "encounter_id": order["encounter_id"],
        "category": order["category"],
        "code": order["code"],
        "quantity": order["quantity"],
        "unit_charge_cents": order["unit_charge_cents"],
        "line_total_cents": order["line_total_cents"],
        "status": order["status"],
    }
    data.update(_common(order))
    return data


def agreement_view(agreement):
    data = {
        "facility_id": agreement["facility_id"],
        "destination_hospital_name": agreement["destination_hospital_name"],
        "service_line": agreement["service_line"],
        "capability_tier": agreement["capability_tier"],
        "accepts_unstable": agreement["accepts_unstable"],
        "effective_start_date": agreement["effective_start_date"],
        "effective_end_date": agreement["effective_end_date"],
        "status": agreement_status(agreement),
    }
    data.update(_common(agreement))
    return data


def mou_view(mou):
    reserved = mou_units_reserved(mou)
    available = mou["units_committed"] - reserved
    data = {
        "facility_id": mou["facility_id"],
        "carrier_name": mou["carrier_name"],
        "level_of_care": mou["level_of_care"],
        "coverage_start_at": iso(mou["coverage_start_at"]),
        "coverage_end_at": iso(mou["coverage_end_at"]),
        "units_committed": mou["units_committed"],
        "units_reserved": reserved,
        "units_available": available,
        "saturation_state": "SATURATED" if available == 0 else "AVAILABLE",
        "status": mou_status(mou),
    }
    data.update(_common(mou))
    return data


def transfer_order_view(order):
    data = {
        "encounter_id": order["encounter_id"],
        "transfer_agreement_id": order["transfer_agreement_id"],
        "ambulance_mou_id": order["ambulance_mou_id"],
        "clinical_benefit_certified": order["clinical_benefit_certified"],
        "certifying_physician_user_id": order["certifying_physician_user_id"],
        "requested_at": iso(order["requested_at"]),
        "round_index": order["round_index"],
        "reserved_unit_count": order["reserved_unit_count"],
        "status": order["status"],
        "decline_reason": order["decline_reason"],
    }
    data.update(_common(order))
    return data


def claim_view(claim):
    data = {
        "encounter_id": claim["encounter_id"],
        "payer_contract_id": claim["payer_contract_id"],
        "billed_facility_fee_cents": claim["billed_facility_fee_cents"],
        "billed_ancillary_cents": claim["billed_ancillary_cents"],
        "billed_total_cents": claim["billed_total_cents"],
        "protection_variant": claim["protection_variant"],
        "allowed_amount_cents": claim["allowed_amount_cents"],
        "plan_paid_cents": claim["plan_paid_cents"],
        "patient_responsibility_cents": claim["patient_responsibility_cents"],
        "balance_bill_amount_cents": claim["balance_bill_amount_cents"],
        "written_off_cents": claim["written_off_cents"],
        "pre_award_allowed_cents": claim["pre_award_allowed_cents"],
        "pre_award_plan_paid_cents": claim["pre_award_plan_paid_cents"],
        "pre_award_patient_responsibility_cents": claim[
            "pre_award_patient_responsibility_cents"
        ],
        "pre_award_written_off_cents": claim["pre_award_written_off_cents"],
        "negotiation_rounds_used": claim["negotiation_rounds_used"],
        "status": claim["status"],
    }
    data.update(_common(claim))
    return data


def dispute_view(dispute):
    data = {
        "claim_id": dispute["claim_id"],
        "initiated_by_user_id": dispute["initiated_by_user_id"],
        "round_index": dispute["round_index"],
        "last_offer_cents": dispute["last_offer_cents"],
        "last_counteroffer_cents": dispute["last_counteroffer_cents"],
        "last_offer_by_user_id": dispute["last_offer_by_user_id"],
        "idr_award_cents": dispute["idr_award_cents"],
        "awarded_at": iso(dispute["awarded_at"]),
        "status": dispute["status"],
    }
    data.update(_common(dispute))
    return data


def ledger_view(entry):
    return {
        "id": entry["id"],
        "created_at": iso(entry["created_at"]),
        "facility_id": entry["facility_id"],
        "event_type": entry["event_type"],
        "severity": entry["severity"],
        "subject_type": entry["subject_type"],
        "subject_id": entry["subject_id"],
        "detail": entry["detail"],
        "recorded_at": iso(entry["recorded_at"]),
        "defect_counted": entry["defect_counted"],
    }


def signage_expiry(attested_at):
    return attested_at + timedelta(days=SIGNAGE_VALIDITY_DAYS)


ALL_CODES = list(ALL_ANCILLARY_CODES)
