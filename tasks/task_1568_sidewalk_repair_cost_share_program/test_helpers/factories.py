"""Payload factories — one per entity, input fields only."""


def create_cycle_payload(cycle_year=2026, window_start_date="2026-01-01",
                         window_end_date="2026-12-31",
                         appropriation_cents=10_000_000, **overrides) -> dict:
    payload = {
        "cycle_year": cycle_year,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "appropriation_cents": appropriation_cents,
    }
    payload.update(overrides)
    return payload


def create_owner_payload(full_name="Test Owner", mailing_address="1 Main St",
                         hardship_tier=None, **overrides) -> dict:
    payload = {"full_name": full_name, "mailing_address": mailing_address}
    if hardship_tier is not None:
        payload["hardship_tier"] = hardship_tier
    payload.update(overrides)
    return payload


def create_parcel_payload(owner_id, parcel_number="P-100",
                          street_address="1 Main St", street_class="LOCAL",
                          is_corner_lot=None, is_city_owned=None,
                          **overrides) -> dict:
    payload = {
        "parcel_number": parcel_number,
        "owner_id": owner_id,
        "street_address": street_address,
        "street_class": street_class,
    }
    if is_corner_lot is not None:
        payload["is_corner_lot"] = is_corner_lot
    if is_city_owned is not None:
        payload["is_city_owned"] = is_city_owned
    payload.update(overrides)
    return payload


def create_segment_payload(parcel_id, segment_code="S-100-1", length_ft=20,
                           width_ft=5, is_corner_segment=None,
                           has_existing_curb_ramp=None, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "segment_code": segment_code,
        "length_ft": length_ft,
        "width_ft": width_ft,
    }
    if is_corner_segment is not None:
        payload["is_corner_segment"] = is_corner_segment
    if has_existing_curb_ramp is not None:
        payload["has_existing_curb_ramp"] = has_existing_curb_ramp
    payload.update(overrides)
    return payload


def create_defect_payload(segment_id, defect_type="SPALLING", area_sqft=20,
                          measured_offset_inches=None, city_tree_involved=None,
                          **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "defect_type": defect_type,
        "area_sqft": area_sqft,
    }
    if measured_offset_inches is not None:
        payload["measured_offset_inches"] = measured_offset_inches
    if city_tree_involved is not None:
        payload["city_tree_involved"] = city_tree_involved
    payload.update(overrides)
    return payload


def create_notice_payload(parcel_id, defect_ids, base_deadline_days=None,
                          prior_notice_id=None, **overrides) -> dict:
    payload = {"parcel_id": parcel_id, "defect_ids": list(defect_ids)}
    if base_deadline_days is not None:
        payload["base_deadline_days"] = base_deadline_days
    if prior_notice_id is not None:
        payload["prior_notice_id"] = prior_notice_id
    payload.update(overrides)
    return payload


def create_application_payload(notice_id, parcel_id, cycle_id,
                               estimated_qty_sqft=100, **overrides) -> dict:
    payload = {
        "notice_id": notice_id,
        "parcel_id": parcel_id,
        "cycle_id": cycle_id,
        "estimated_qty_sqft": estimated_qty_sqft,
    }
    payload.update(overrides)
    return payload


def create_decision_payload(outcome="APPROVE", reviewer_note=None,
                            **overrides) -> dict:
    payload = {"outcome": outcome}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    payload.update(overrides)
    return payload


def create_batch_payload(neighborhood_code="NB-1",
                         work_window_start="2026-09-25",
                         work_window_end="2026-10-15",
                         bid_deadline="2026-09-22T00:00:00Z",
                         **overrides) -> dict:
    payload = {
        "neighborhood_code": neighborhood_code,
        "work_window_start": work_window_start,
        "work_window_end": work_window_end,
        "bid_deadline": bid_deadline,
    }
    payload.update(overrides)
    return payload


def create_work_item_payload(batch_id, notice_id, scope_sqft=50,
                             engineer_unit_rate_cents=1300,
                             **overrides) -> dict:
    payload = {
        "batch_id": batch_id,
        "notice_id": notice_id,
        "scope_sqft": scope_sqft,
        "engineer_unit_rate_cents": engineer_unit_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(company_name="Acme Paving", license_number="L-001",
                              insurance_valid_until="2026-12-31",
                              **overrides) -> dict:
    payload = {
        "company_name": company_name,
        "license_number": license_number,
        "insurance_valid_until": insurance_valid_until,
    }
    payload.update(overrides)
    return payload


def create_bid_payload(batch_id, expected_batch_version, unit_rate_cents=1000,
                       ramp_flat_fee_cents=0, **overrides) -> dict:
    payload = {
        "batch_id": batch_id,
        "unit_rate_cents": unit_rate_cents,
        "ramp_flat_fee_cents": ramp_flat_fee_cents,
        "expected_batch_version": expected_batch_version,
    }
    payload.update(overrides)
    return payload


def create_lien_payload(notice_id, actual_repair_cost_cents=500000,
                        interest_rate_bp=None, **overrides) -> dict:
    payload = {
        "notice_id": notice_id,
        "actual_repair_cost_cents": actual_repair_cost_cents,
    }
    if interest_rate_bp is not None:
        payload["interest_rate_bp"] = interest_rate_bp
    payload.update(overrides)
    return payload


def create_inspection_payload(result="PASS", notes=None, **overrides) -> dict:
    payload = {"result": result}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def create_appeal_payload(grounds="dispute", **overrides) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def create_appeal_decision_payload(decision="UPHELD", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_forestry_decision_payload(decision="PRUNE_APPROVED",
                                     **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_adjustment_payload(delta_cents, expected_program_cycle_version,
                              **overrides) -> dict:
    payload = {
        "delta_cents": delta_cents,
        "expected_program_cycle_version": expected_program_cycle_version,
    }
    payload.update(overrides)
    return payload


def create_extension_payload(extra_days, expected_notice_version,
                             **overrides) -> dict:
    payload = {
        "extra_days": extra_days,
        "expected_notice_version": expected_notice_version,
    }
    payload.update(overrides)
    return payload


def create_reimburse_payload(final_repair_cost_cents, ramp_receipt_cents=None,
                             **overrides) -> dict:
    payload = {"final_repair_cost_cents": final_repair_cost_cents}
    if ramp_receipt_cents is not None:
        payload["ramp_receipt_cents"] = ramp_receipt_cents
    payload.update(overrides)
    return payload
