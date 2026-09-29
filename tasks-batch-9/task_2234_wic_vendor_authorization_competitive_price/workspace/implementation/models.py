"""Record factories. Every documented field is present at construction time."""

from decimal import Decimal

from store import new_record


def peer_group(**kw):
    return new_record(
        code=kw["code"],
        store_type=kw["store_type"],
        min_monthly_redemption_cents=kw["min_monthly_redemption_cents"],
        max_monthly_redemption_cents=kw["max_monthly_redemption_cents"],
        mar_method=kw["mar_method"],
        competitive_allowance_pct=kw["competitive_allowance_pct"],
        min_submissions_for_ceiling=kw["min_submissions_for_ceiling"],
        min_stock_multiplier=kw["min_stock_multiplier"],
        status="ACTIVE",
        member_count=0,
        retired_at=None,
    )


def food_category(**kw):
    return new_record(
        code=kw["code"],
        name=kw["name"],
        is_formula=kw["is_formula"],
        formula_restriction_level=kw["formula_restriction_level"],
        min_stock_units=kw["min_stock_units"],
        min_variety_count=kw["min_variety_count"],
        max_units_per_transaction=kw["max_units_per_transaction"],
        stock_required=kw["stock_required"],
    )


def food_item(**kw):
    return new_record(
        food_category_id=kw["food_category_id"],
        upc=kw["upc"],
        brand=kw["brand"],
        container_size_oz=kw["container_size_oz"],
        contract_brand=kw["contract_brand"],
        required_for_authorization=kw["required_for_authorization"],
        status="ACTIVE",
        delisted_at=None,
        delist_reason=None,
    )


def vendor(**kw):
    return new_record(
        store_name=kw["store_name"],
        store_type=kw["store_type"],
        reported_monthly_redemption_cents=kw["reported_monthly_redemption_cents"],
        peer_group_id=None,
        authorization_status="APPLICANT",
        authorized_at=None,
        reauthorization_due_at=None,
        reauth_completed_count=0,
        training_type=None,
        training_completed_at=None,
        training_expires_at=None,
        accepted_submission_count=0,
        price_submission_complete=False,
        open_finding_count=0,
        cure_deadline_at=None,
        compliance_buy_required=False,
        risk_flag="NONE",
        risk_score=Decimal("0.0"),
        risk_tier="LOW",
        risk_epoch_at=None,
        reauthorization_hold=False,
        reauth_blocked_reason=None,
        authorization_blocked_reason=None,
        recoupment_balance_cents=0,
        avg_monthly_redemption_cents=0,
        sanction_points=0,
        disqualified_until=None,
        denial_reason=None,
    )


def price_cycle(**kw):
    return new_record(
        cycle_code=kw["cycle_code"],
        submission_open_at=kw["submission_open_at"],
        submission_due_at=kw["submission_due_at"],
        status="OPEN",
        closed_at=None,
        published_at=None,
        provisional_ceiling_count=0,
        published_ceiling_count=0,
        skipped_pair_count=0,
    )


def price_submission(**kw):
    return new_record(
        vendor_id=kw["vendor_id"],
        food_item_id=kw["food_item_id"],
        price_cycle_id=kw["price_cycle_id"],
        shelf_price_cents=kw["shelf_price_cents"],
        status="SUBMITTED",
        review_reason=None,
        revision_count=0,
        reviewed_by_user_id=None,
        reviewed_at=None,
        voided_reason=None,
    )


def price_ceiling(**kw):
    return new_record(
        peer_group_id=kw["peer_group_id"],
        food_item_id=kw["food_item_id"],
        price_cycle_id=kw["price_cycle_id"],
        mar_cents=kw["mar_cents"],
        basis=kw["basis"],
        base_cents=kw["base_cents"],
        cap_cents=kw["cap_cents"],
        cap_binding=kw["cap_binding"],
        peer_submission_count=kw["peer_submission_count"],
        contributing_submission_count=kw["contributing_submission_count"],
        status=kw["status"],
        superseded_reason=None,
        effective_from=kw["effective_from"],
    )


def monitoring_visit(**kw):
    return new_record(
        vendor_id=kw["vendor_id"],
        visit_type=kw["visit_type"],
        scheduled_for=kw["scheduled_for"],
        auto_generated=kw.get("auto_generated", False),
        status="SCHEDULED",
        conducted_at=None,
        outcome="PENDING",
        stock_findings=[],
        stock_compliance_pct=Decimal("0.0"),
        buy_items=[],
        overcharge_cents=0,
        cancelled_reason=None,
    )


def redemption_claim(**kw):
    return new_record(
        vendor_id=kw["vendor_id"],
        claim_month=kw["claim_month"],
        governing_price_cycle_id=None,
        line_count=0,
        submitted_total_cents=0,
        adjudicated_total_cents=None,
        net_payable_cents=None,
        accepted_line_count=0,
        reduced_line_count=0,
        rejected_line_count=0,
        status="SUBMITTED",
        adjudicated_at=None,
        paid_at=None,
    )


def claim_line(**kw):
    return new_record(
        redemption_claim_id=kw["redemption_claim_id"],
        line_number=kw["line_number"],
        upc=kw["upc"],
        food_item_id=None,
        quantity=kw["quantity"],
        charged_unit_price_cents=kw["charged_unit_price_cents"],
        medical_doc_on_file=kw["medical_doc_on_file"],
        edit_result="PENDING",
        edit_code=None,
        applied_mar_cents=None,
        allowed_cents=0,
        recouped_cents=0,
    )


def adjustment(**kw):
    return new_record(
        redemption_claim_id=kw["redemption_claim_id"],
        reason_code=kw["reason_code"],
        recoupment_rate=kw["recoupment_rate"],
        recoupment_cents=kw["recoupment_cents"],
        line_recoupments=kw["line_recoupments"],
        status="PENDING",
        created_by_user_id=kw["created_by_user_id"],
        applied_by_user_id=None,
        applied_at=None,
        reversed_at=None,
        reversal_reason=None,
    )


def sanction_case(**kw):
    return new_record(
        vendor_id=kw["vendor_id"],
        source_visit_id=kw["source_visit_id"],
        violation_code=kw["violation_code"],
        narrative=kw["narrative"],
        base_tier=kw["base_tier"],
        case_points=kw["case_points"],
        cumulative_points_at_open=kw["cumulative_points_at_open"],
        effective_tier=kw["effective_tier"],
        disqualification_months=kw["disqualification_months"],
        cmp_amount_cents=kw["cmp_amount_cents"],
        cmp_permitted=kw["cmp_permitted"],
        cmp_paid_cents=0,
        status="OPENED",
        resolution="NONE",
        opened_by_user_id=kw["opened_by_user_id"],
        notice_served_at=None,
        response_due_at=None,
        dismissal_reason=None,
    )
