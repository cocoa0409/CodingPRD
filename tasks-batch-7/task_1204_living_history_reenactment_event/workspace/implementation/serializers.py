"""Entity -> JSON dict serialization. Datetimes formatted with 3 fractional digits."""

from services import derived
from util import fmt_dt


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def event(e):
    d = _common(e)
    d.update(
        name=e["name"],
        site_name=e["site_name"],
        event_starts_at=fmt_dt(e["event_starts_at"]),
        event_ends_at=fmt_dt(e["event_ends_at"]),
        adult_day_price_cents=e["adult_day_price_cents"],
        child_day_price_cents=e["child_day_price_cents"],
        adult_weekend_price_cents=e["adult_weekend_price_cents"],
        child_weekend_price_cents=e["child_weekend_price_cents"],
        early_bird_pct=e["early_bird_pct"],
        early_bird_cutoff_at=fmt_dt(e["early_bird_cutoff_at"]),
        service_fee_cents=e["service_fee_cents"],
        refund_retain_pct=e["refund_retain_pct"],
        required_liability_cents=e["required_liability_cents"],
        max_minor_per_adult=e["max_minor_per_adult"],
        vendor_frontage_rate_cents=e["vendor_frontage_rate_cents"],
        vendor_multi_day_discount_pct=e["vendor_multi_day_discount_pct"],
        vendor_min_fee_cents=e["vendor_min_fee_cents"],
        vendor_late_insurance_surcharge_cents=e["vendor_late_insurance_surcharge_cents"],
        vendor_insurance_deadline_at=fmt_dt(e["vendor_insurance_deadline_at"]),
        event_posture=e["event_posture"],
        restriction_level=derived.restriction_level(e),
        approved_combatant_count=derived.event_approved_combatant_count(e),
        cancelled_at=fmt_dt(e["cancelled_at"]),
    )
    return d


def agreement(a):
    d = _common(a)
    d.update(
        event_id=a["event_id"],
        agreement_type=a["agreement_type"],
        document_ref=a["document_ref"],
        coverage_amount_cents=a["coverage_amount_cents"],
        effective_from=fmt_dt(a["effective_from"]),
        effective_until=fmt_dt(a["effective_until"]),
        status=a["status"],
        signed_at=fmt_dt(a["signed_at"]),
        signer_name=a["signer_name"],
    )
    return d


def unit(u):
    d = _common(u)
    d.update(
        event_id=u["event_id"],
        name=u["name"],
        unit_type=u["unit_type"],
        portrayal_name=u["portrayal_name"],
        headcount_estimate=u["headcount_estimate"],
        status=u["status"],
        vet_notes=u["vet_notes"],
        approved_combatant_count=derived.unit_approved_combatant_count(u),
    )
    return d


def participant(p):
    d = _common(p)
    d.update(
        event_id=p["event_id"],
        unit_id=p["unit_id"],
        supervisor_participant_id=p["supervisor_participant_id"],
        full_name=p["full_name"],
        age_at_event=p["age_at_event"],
        impression_class=p["impression_class"],
        persona_description=p["persona_description"],
        is_minor=p["age_at_event"] < 18,
        status=p["status"],
        vet_notes=p["vet_notes"],
        checked_in_at=fmt_dt(p["checked_in_at"]),
    )
    return d


def equipment_item(it):
    d = _common(it)
    d.update(
        participant_id=it["participant_id"],
        item_type=it["item_type"],
        description=it["description"],
        status=it["status"],
        failure_count=it["failure_count"],
    )
    return d


def inspection(i):
    d = _common(i)
    d.update(
        equipment_item_id=i["equipment_item_id"],
        inspection_kind=i["inspection_kind"],
        scheduled_for=fmt_dt(i["scheduled_for"]),
        status=i["status"],
        recorded_by_user_id=i["recorded_by_user_id"],
        failure_reason=i["failure_reason"],
        waived_by_user_id=i["waived_by_user_id"],
        waiver_reason=i["waiver_reason"],
    )
    return d


def site_area(a):
    d = _common(a)
    d.update(
        event_id=a["event_id"],
        area_name=a["area_name"],
        area_kind=a["area_kind"],
        capacity_units=a["capacity_units"],
        status=a["status"],
        allocated_units=derived.area_allocated_units(a),
    )
    return d


def allocation(a):
    d = _common(a)
    d.update(
        site_area_id=a["site_area_id"],
        unit_id=a["unit_id"],
        vendor_id=a["vendor_id"],
        starts_at=fmt_dt(a["starts_at"]),
        ends_at=fmt_dt(a["ends_at"]),
        units=a["units"],
        status=a["status"],
    )
    return d


def program_slot(s):
    d = _common(s)
    d.update(
        event_id=s["event_id"],
        site_area_id=s["site_area_id"],
        title=s["title"],
        starts_at=fmt_dt(s["starts_at"]),
        ends_at=fmt_dt(s["ends_at"]),
        open_flame=s["open_flame"],
        required_combatants=s["required_combatants"],
        status=s["status"],
        cancel_reason=s["cancel_reason"],
    )
    return d


def ticket_order(o):
    d = _common(o)
    d.update(
        event_id=o["event_id"],
        buyer_user_id=o["buyer_user_id"],
        buyer_name=o["buyer_name"],
        lines=o["lines"],
        status=o["status"],
        quoted_total_cents=o["quoted_total_cents"],
        final_total_cents=o["final_total_cents"],
        refund_amount_cents=o["refund_amount_cents"],
        retained_fee_cents=o["retained_fee_cents"],
        refund_reason=o["refund_reason"],
        paid_at=fmt_dt(o["paid_at"]),
        refunded_at=fmt_dt(o["refunded_at"]),
    )
    return d


def parking_pass(p):
    d = _common(p)
    d.update(
        ticket_order_id=p["ticket_order_id"],
        site_area_id=p["site_area_id"],
        vehicle_plate=p["vehicle_plate"],
        vehicle_class=p["vehicle_class"],
        units_used=p["units_used"],
        status=p["status"],
    )
    return d


def vendor(v):
    d = _common(v)
    d.update(
        event_id=v["event_id"],
        owner_user_id=v["owner_user_id"],
        business_name=v["business_name"],
        wares_description=v["wares_description"],
        frontage_feet=v["frontage_feet"],
        requested_days=v["requested_days"],
        status=v["status"],
        provisional_fee_cents=v["provisional_fee_cents"],
        final_fee_cents=v["final_fee_cents"],
        fee_paid_cents=v["fee_paid_cents"],
        insurance_cert_ref=v["insurance_cert_ref"],
        insurance_uploaded_at=fmt_dt(v["insurance_uploaded_at"]),
        balance_due_cents=v["balance_due_cents"],
    )
    return d


def contingency_alert(a):
    d = _common(a)
    d.update(
        event_id=a["event_id"],
        alert_kind=a["alert_kind"],
        severity=a["severity"],
        message=a["message"],
        status=a["status"],
        resolved_at=fmt_dt(a["resolved_at"]),
    )
    return d
