"""Response-field projections (PRD 2.12). Formula intermediates are never serialised."""
import clock

I = clock.render_instant
D = clock.render_date


def _base(row, versioned=True):
    out = {"id": row["id"], "created_at": I(row["created_at"])}
    if versioned:
        out["updated_at"] = I(row["updated_at"])
        out["version"] = row["version"]
    return out


def _num(value):
    if value is None:
        return None
    return float(value)


def catalog_item(row):
    out = _base(row)
    out.update(
        nationality_code=row["nationality_code"],
        destination_country=row["destination_country"],
        visa_type=row["visa_type"],
        government_fee_cents=row["government_fee_cents"],
        government_fee_basis=row["government_fee_basis"],
        base_service_fee_cents=row["base_service_fee_cents"],
        agency_turnaround_override_days=row["agency_turnaround_override_days"],
        form_code=row["form_code"],
        requires_appointment=row["requires_appointment"],
    )
    return out


def document_requirement(row):
    out = _base(row, versioned=False)
    out.update(
        catalog_item_id=row["catalog_item_id"],
        doc_type=row["doc_type"],
        is_required=row["is_required"],
        validity_rule=row["validity_rule"],
        validity_param=row["validity_param"],
        applies_max_age_years=row["applies_max_age_years"],
    )
    return out


def agency_form(row):
    out = _base(row)
    out.update(
        form_code=row["form_code"],
        revision=row["revision"],
        required_field_count=row["required_field_count"],
        status=row["status"],
        published_at=I(row["published_at"]),
    )
    return out


def consulate(row):
    out = _base(row)
    out.update(
        name=row["name"],
        destination_country=row["destination_country"],
        jurisdiction_region_codes=list(row["jurisdiction_region_codes"]),
        closure_dates=list(row["closure_dates"]),
    )
    return out


def slot(row):
    out = _base(row)
    out.update(
        consulate_id=row["consulate_id"],
        starts_at=I(row["starts_at"]),
        capacity=row["capacity"],
        booked_count=row["booked_count"],
        status=row["status"],
    )
    return out


def order(row):
    out = _base(row)
    out.update(
        catalog_item_id=row["catalog_item_id"],
        consulate_id=row["consulate_id"],
        parent_order_id=row["parent_order_id"],
        service_level=row["service_level"],
        travel_date=D(row["travel_date"]),
        return_date=D(row["return_date"]),
        delivery_region_code=row["delivery_region_code"],
        workflow_status=row["workflow_status"],
        payment_status=row["payment_status"],
        custody_holder=row["custody_holder"],
        feasibility_status=row["feasibility_status"],
        furthest_stage_reached=row["furthest_stage_reached"],
        applicant_count=row["applicant_count"],
        government_fee_quoted_cents=row["government_fee_quoted_cents"],
        service_fee_quoted_cents=row["service_fee_quoted_cents"],
        total_quoted_cents=row["total_quoted_cents"],
        discount_pct_applied=_num(row["discount_pct_applied"]),
        handling_fee_waived=row["handling_fee_waived"],
        collected_government_cents=row["collected_government_cents"],
        collected_service_cents=row["collected_service_cents"],
        collected_cents=row["collected_government_cents"] + row["collected_service_cents"],
        government_tendered_cents=row["government_tendered_cents"],
        service_earned_cents=row["service_earned_cents"],
        refunded_cents=row["refunded_cents"],
        refund_scheduled_cents=row["refund_scheduled_cents"],
        outstanding_cents=row["outstanding_cents"],
        quoted_by_user_id=row["quoted_by_user_id"],
        submitted_by_user_id=row["submitted_by_user_id"],
        acknowledged_by_user_id=row["acknowledged_by_user_id"],
        quoted_at=I(row["quoted_at"]),
        submitted_at=I(row["submitted_at"]),
        tendered_at=I(row["tendered_at"]),
        decided_at=I(row["decided_at"]),
        effective_submission_date=D(row["effective_submission_date"]),
        projected_completion_date=D(row["projected_completion_date"]),
        rfe_round_count=row["rfe_round_count"],
    )
    return out


def applicant(row):
    out = _base(row)
    out.update(
        order_id=row["order_id"],
        full_name=row["full_name"],
        date_of_birth=D(row["date_of_birth"]),
        nationality_code=row["nationality_code"],
        residence_region_code=row["residence_region_code"],
        readiness_status=row["readiness_status"],
        age_years=row["age_years"],
        required_doc_count=row["required_doc_count"],
        accepted_doc_count=row["accepted_doc_count"],
    )
    return out


def applicant_document(row):
    out = _base(row)
    out.update(
        applicant_id=row["applicant_id"],
        doc_type=row["doc_type"],
        is_required=row["is_required"],
        validity_rule=row["validity_rule"],
        validity_param=row["validity_param"],
        review_status=row["review_status"],
        issue_date=D(row["issue_date"]),
        expiry_date=D(row["expiry_date"]),
        resubmission_count=row["resubmission_count"],
        rejection_reason=row["rejection_reason"],
        reviewed_by_user_id=row["reviewed_by_user_id"],
    )
    return out


def photo(row):
    out = _base(row)
    out.update(
        applicant_id=row["applicant_id"],
        taken_on=D(row["taken_on"]),
        head_height_ratio=_num(row["head_height_ratio"]),
        background_code=row["background_code"],
        resolution_px=row["resolution_px"],
        compliance_status=row["compliance_status"],
        retake_count=row["retake_count"],
        failure_reasons=list(row["failure_reasons"]),
    )
    return out


def prepared_form(row):
    out = _base(row)
    out.update(
        applicant_id=row["applicant_id"],
        agency_form_id=row["agency_form_id"],
        form_code=row["form_code"],
        revision_used=row["revision_used"],
        filled_field_count=row["filled_field_count"],
        prep_status=row["prep_status"],
        signed_at=I(row["signed_at"]),
        signed_by_user_id=row["signed_by_user_id"],
    )
    return out


def appointment(row):
    out = _base(row)
    out.update(
        applicant_id=row["applicant_id"],
        slot_id=row["slot_id"],
        booking_status=row["booking_status"],
        reschedule_count=row["reschedule_count"],
        no_show_count=row["no_show_count"],
        booked_at=I(row["booked_at"]),
    )
    return out


def courier_leg(row):
    out = _base(row)
    out.update(
        order_id=row["order_id"],
        leg_index=row["leg_index"],
        from_holder=row["from_holder"],
        to_holder=row["to_holder"],
        scheduled_date=D(row["scheduled_date"]),
        leg_status=row["leg_status"],
        attempt_count=row["attempt_count"],
    )
    return out


def custody_event(row):
    out = _base(row, versioned=False)
    out.update(
        order_id=row["order_id"],
        holder_type=row["holder_type"],
        leg_index=row["leg_index"],
        acquired_at=I(row["acquired_at"]),
        released_at=I(row["released_at"]),
        reason=row["reason"],
    )
    return out


def rfe(row):
    out = _base(row)
    out.update(
        order_id=row["order_id"],
        round_index=row["round_index"],
        requested_doc_type=row["requested_doc_type"],
        issued_at=I(row["issued_at"]),
        deadline_at=I(row["deadline_at"]),
        rfe_status=row["rfe_status"],
        responded_at=I(row["responded_at"]),
        response_count=row["response_count"],
    )
    return out


def ledger_entry(row):
    out = _base(row, versioned=False)
    out.update(
        order_id=row["order_id"],
        stream=row["stream"],
        kind=row["kind"],
        amount_cents=row["amount_cents"],
        reason=row["reason"],
        recorded_at=I(row["recorded_at"]),
    )
    return out


def shipment(row):
    out = _base(row)
    out.update(
        order_id=row["order_id"],
        method=row["method"],
        address_region_code=row["address_region_code"],
        signature_required=row["signature_required"],
        delivery_status=row["delivery_status"],
        attempt_count=row["attempt_count"],
        escalation_fee_cents=row["escalation_fee_cents"],
    )
    return out


def sla_segment(row):
    out = _base(row, versioned=False)
    out.update(
        order_id=row["order_id"],
        segment_kind=row["segment_kind"],
        cause=row["cause"],
        started_at=I(row["started_at"]),
        ended_at=I(row["ended_at"]),
        business_minutes=row["business_minutes"],
    )
    return out
