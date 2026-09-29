"""Per-entity JSON projections plus the derived-counter reconcilers of PRD §2.8.

Every sync_* helper recomputes a derived field from current state and, when the
value actually moves, refreshes updated_at and increments version — the
"recomputing a derived field counts as a mutation" rule of PRD §2.5.
"""

import calc
from common import fmt_datetime, num2, store, touch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": fmt_datetime(rec["created_at"])}
    if versioned:
        out["updated_at"] = fmt_datetime(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def _apply(rec, values):
    changed = False
    for key, value in values.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def staff_user(rec):
    out = _common(rec)
    out.update(
        {
            "staff_code": rec["staff_code"],
            "full_name": rec["full_name"],
            "role": rec["role"],
            "authority_tier": rec["authority_tier"],
            "is_active": rec["is_active"],
        }
    )
    return out


def consumer(rec):
    out = _common(rec)
    sentiment = calc.consumer_sentiment(rec, "agent_view")
    out.update(
        {
            "external_ref": rec["external_ref"],
            "full_name": rec["full_name"],
            "email": rec.get("email"),
            "phone": rec.get("phone"),
            "postal_code": rec.get("postal_code"),
            "is_vulnerable_flag": rec["is_vulnerable_flag"],
            "sentiment_index": num2(sentiment["sentiment_index"]),
            "goodwill_authorized_cents": rec["goodwill_authorized_cents"],
            "goodwill_outstanding_cents": rec["goodwill_outstanding_cents"],
            "goodwill_paid_cents": rec["goodwill_paid_cents"],
            "goodwill_voided_cents": rec["goodwill_voided_cents"],
            "open_kit_count": rec["open_kit_count"],
            "complaint_count": rec["complaint_count"],
        }
    )
    return out


def plant(rec):
    out = _common(rec)
    out.update(
        {
            "plant_code": rec["plant_code"],
            "name": rec["name"],
            "region": rec["region"],
            "oversight_posture": rec["oversight_posture"],
            "open_investigation_count": rec["open_investigation_count"],
            "recall_initiated_count": rec["recall_initiated_count"],
        }
    )
    return out


def production_line(rec):
    out = _common(rec)
    out.update(
        {
            "plant_id": rec["plant_id"],
            "line_code": rec["line_code"],
            "nominal_units_per_hour": rec["nominal_units_per_hour"],
            "lot_count": rec["lot_count"],
        }
    )
    return out


def product(rec):
    out = _common(rec)
    out.update(
        {
            "sku": rec["sku"],
            "name": rec["name"],
            "category": rec["category"],
            "is_regulated_food": rec["is_regulated_food"],
            "unit_retail_price_cents": rec["unit_retail_price_cents"],
            "units_per_case": rec["units_per_case"],
        }
    )
    return out


def production_lot(rec):
    out = _common(rec)
    out.update(
        {
            "product_id": rec["product_id"],
            "production_line_id": rec["production_line_id"],
            "batch_code": rec["batch_code"],
            "normalized_batch_code": rec["normalized_batch_code"],
            "code_date": fmt_datetime(rec["code_date"]),
            "units_produced": rec["units_produced"],
            "release_status": rec["release_status"],
            "linked_complaint_count": rec["linked_complaint_count"],
            "provisional_complaint_count": rec["provisional_complaint_count"],
            "adjudicated_complaint_count": rec["adjudicated_complaint_count"],
            "duplicate_complaint_count": rec["duplicate_complaint_count"],
            "goodwill_charged_cents": rec["goodwill_charged_cents"],
        }
    )
    return out


def contact(rec):
    out = _common(rec)
    out.update(
        {
            "consumer_id": rec["consumer_id"],
            "channel": rec["channel"],
            "received_at": fmt_datetime(rec["received_at"]),
            "raw_message": rec["raw_message"],
            "handle_or_address": rec.get("handle_or_address"),
            "status": rec["status"],
            "complaint_count": rec["complaint_count"],
            "intake_agent_ref": rec["intake_agent_ref"],
        }
    )
    return out


def complaint(rec):
    out = _common(rec)
    out.update(
        {
            "contact_id": rec["contact_id"],
            "consumer_id": rec["consumer_id"],
            "product_id": rec.get("product_id"),
            "lot_id": rec.get("lot_id"),
            "duplicate_of_complaint_id": rec.get("duplicate_of_complaint_id"),
            "responded_template_id": rec.get("responded_template_id"),
            "reported_batch_code": rec.get("reported_batch_code"),
            "pack_code_date": fmt_datetime(rec.get("pack_code_date")),
            "complaint_type": rec["complaint_type"],
            "foreign_object_class": rec["foreign_object_class"],
            "medical_attention_sought": rec["medical_attention_sought"],
            "hospitalization": rec["hospitalization"],
            "vulnerable_consumer": rec["vulnerable_consumer"],
            "symptom_codes": list(rec["symptom_codes"]),
            "units_claimed": rec["units_claimed"],
            "product_identification_status": rec["product_identification_status"],
            "provisional_severity_score": num2(rec["provisional_severity_score"]),
            "provisional_severity_band": rec["provisional_severity_band"],
            "adjudicated_severity_score": num2(rec.get("adjudicated_severity_score")),
            "adjudicated_severity_band": rec.get("adjudicated_severity_band"),
            "effective_severity_band": calc.effective_band(rec),
            "handling_status": rec["handling_status"],
            "regulatory_status": rec["regulatory_status"],
            "pre_hold_handling_status": rec.get("pre_hold_handling_status"),
            "responded_at": fmt_datetime(rec.get("responded_at")),
            "triaged_by_ref": rec.get("triaged_by_ref"),
            "created_by_ref": rec["created_by_ref"],
            "linked_signal_count": rec["linked_signal_count"],
        }
    )
    return out


def sample_kit(rec):
    out = _common(rec)
    out.update(
        {
            "complaint_id": rec["complaint_id"],
            "consumer_id": rec["consumer_id"],
            "kit_code": rec["kit_code"],
            "seal_id_issued": rec["seal_id_issued"],
            "status": rec["status"],
            "shipped_at": fmt_datetime(rec.get("shipped_at")),
            "expected_return_by": fmt_datetime(rec.get("expected_return_by")),
            "occupied_from": fmt_datetime(rec.get("occupied_from")),
            "occupied_until": fmt_datetime(rec.get("occupied_until")),
            "received_at": fmt_datetime(rec.get("received_at")),
            "seal_id_returned": rec.get("seal_id_returned"),
            "transit_hours": num2(rec.get("transit_hours")),
            "chain_integrity_status": rec["chain_integrity_status"],
            "disposition": rec["disposition"],
            "custody_event_count": rec["custody_event_count"],
        }
    )
    return out


def custody_event(rec):
    out = _common(rec, versioned=False)
    out.update(
        {
            "sample_kit_id": rec["sample_kit_id"],
            "sequence_no": rec["sequence_no"],
            "event_type": rec["event_type"],
            "occurred_at": fmt_datetime(rec["occurred_at"]),
            "actor_label": rec["actor_label"],
            "seal_id_observed": rec.get("seal_id_observed"),
            "notes": rec.get("notes"),
        }
    )
    return out


def remedy(rec):
    out = _common(rec)
    out.update(
        {
            "complaint_id": rec["complaint_id"],
            "consumer_id": rec["consumer_id"],
            "remedy_type": rec["remedy_type"],
            "requested_value_cents": rec["requested_value_cents"],
            "base_value_cents": rec["base_value_cents"],
            "uplift_pct": num2(rec["uplift_pct"]),
            "uplift_cents": rec["uplift_cents"],
            "payout_cents": rec["payout_cents"],
            "authority_tier_required": rec["authority_tier_required"],
            "kit_returned_credit_applied": rec["kit_returned_credit_applied"],
            "status": rec["status"],
            "revision_count": rec["revision_count"],
            "authored_by_ref": rec["authored_by_ref"],
            "decided_by_ref": rec.get("decided_by_ref"),
            "fulfilled_at": fmt_datetime(rec.get("fulfilled_at")),
        }
    )
    return out


def regulatory_report(rec):
    out = _common(rec)
    out.update(
        {
            "complaint_id": rec["complaint_id"],
            "report_kind": rec["report_kind"],
            "status": rec["status"],
            "escalated_at": fmt_datetime(rec["escalated_at"]),
            "due_at": fmt_datetime(rec["due_at"]),
            "determination_note": rec.get("determination_note"),
            "determined_by_ref": rec.get("determined_by_ref"),
            "submitted_by_ref": rec.get("submitted_by_ref"),
            "submitted_at": fmt_datetime(rec.get("submitted_at")),
            "submitted_late": rec.get("submitted_late"),
            "agency_reference": rec.get("agency_reference"),
        }
    )
    return out


def trend_signal(rec):
    out = _common(rec)
    out.update(
        {
            "scope_level": rec["scope_level"],
            "plant_id": rec["plant_id"],
            "production_line_id": rec.get("production_line_id"),
            "lot_id": rec.get("lot_id"),
            "window_start": fmt_datetime(rec["window_start"]),
            "window_end": fmt_datetime(rec["window_end"]),
            "weighted_complaint_count": num2(rec["weighted_complaint_count"]),
            "units_in_scope": rec["units_in_scope"],
            "observed_rate_ppm": num2(rec["observed_rate_ppm"]),
            "threshold_ppm": num2(rec["threshold_ppm"]),
            "status": rec["status"],
            "detection_source": rec["detection_source"],
            "membership_count": rec["membership_count"],
            "opened_by_ref": rec.get("opened_by_ref"),
        }
    )
    return out


def signal_membership(rec):
    out = _common(rec, versioned=False)
    out.update(
        {
            "trend_signal_id": rec["trend_signal_id"],
            "complaint_id": rec["complaint_id"],
            "severity_weight": num2(rec["severity_weight"]),
            "included_variant": rec["included_variant"],
        }
    )
    return out


def response_template(rec):
    out = _common(rec)
    out.update(
        {
            "template_code": rec["template_code"],
            "title": rec["title"],
            "body": rec["body"],
            "applies_to_type": rec["applies_to_type"],
            "max_band_allowed": rec["max_band_allowed"],
            "requires_supervisor_approval": rec["requires_supervisor_approval"],
            "status": rec["status"],
            "usage_count": rec["usage_count"],
        }
    )
    return out


# ---------------------------------------------------------------------------
# derived-counter reconcilers
# ---------------------------------------------------------------------------
def sync_contact(rec):
    if rec is None:
        return
    count = sum(1 for c in store.complaints.values() if c.get("contact_id") == rec["id"])
    _apply(rec, {"complaint_count": count})


def sync_consumer(rec):
    if rec is None:
        return
    open_kits = sum(
        1
        for k in store.sample_kits.values()
        if k.get("consumer_id") == rec["id"]
        and k.get("status") in ("REQUESTED", "SHIPPED", "IN_TRANSIT_INBOUND", "RECEIVED")
    )
    complaints = sum(
        1
        for c in store.complaints.values()
        if c.get("consumer_id") == rec["id"] and c.get("handling_status") != "DUPLICATE"
    )
    _apply(rec, {"open_kit_count": open_kits, "complaint_count": complaints})


def sync_line(rec):
    if rec is None:
        return
    count = sum(
        1 for l in store.production_lots.values() if l.get("production_line_id") == rec["id"]
    )
    _apply(rec, {"lot_count": count})


def sync_lot(rec):
    if rec is None:
        return
    linked = 0
    provisional = 0
    adjudicated = 0
    duplicate = 0
    for c in store.complaints.values():
        if c.get("lot_id") != rec["id"]:
            continue
        linked += 1
        if c.get("handling_status") == "DUPLICATE":
            duplicate += 1
        elif c.get("adjudicated_severity_score") is None:
            provisional += 1
        else:
            adjudicated += 1
    _apply(
        rec,
        {
            "linked_complaint_count": linked,
            "provisional_complaint_count": provisional,
            "adjudicated_complaint_count": adjudicated,
            "duplicate_complaint_count": duplicate,
        },
    )


def sync_plant(rec):
    """plant_oversight_posture — derived, never settable directly (PRD §2.8)."""
    if rec is None:
        return
    open_count = 0
    recall_count = 0
    hold = False
    for s in store.trend_signals.values():
        if s.get("plant_id") != rec["id"]:
            continue
        status = s.get("status")
        if status in ("INVESTIGATION_OPEN", "RECALL_EVALUATION"):
            open_count += 1
        if status == "RECALL_INITIATED":
            recall_count += 1
        if status in ("RECALL_EVALUATION", "RECALL_INITIATED"):
            hold = True
    if hold:
        posture = "INVESTIGATION_HOLD"
    elif open_count >= 1:
        posture = "WATCH"
    else:
        posture = "NORMAL"
    _apply(
        rec,
        {
            "open_investigation_count": open_count,
            "recall_initiated_count": recall_count,
            "oversight_posture": posture,
        },
    )


def sync_all_plants():
    for rec in list(store.plants.values()):
        sync_plant(rec)


def sync_complaint_signal_count(rec):
    if rec is None:
        return
    count = sum(
        1 for m in store.signal_memberships.values() if m.get("complaint_id") == rec["id"]
    )
    _apply(rec, {"linked_signal_count": count})


def sync_signal(rec):
    if rec is None:
        return
    count = sum(
        1 for m in store.signal_memberships.values() if m.get("trend_signal_id") == rec["id"]
    )
    _apply(rec, {"membership_count": count})


def sync_kit(rec):
    if rec is None:
        return
    count = sum(
        1 for e in store.custody_events.values() if e.get("sample_kit_id") == rec["id"]
    )
    _apply(rec, {"custody_event_count": count})


SERIALIZERS = {
    "staff_users": staff_user,
    "consumers": consumer,
    "plants": plant,
    "production_lines": production_line,
    "products": product,
    "production_lots": production_lot,
    "contacts": contact,
    "complaints": complaint,
    "sample_kits": sample_kit,
    "custody_events": custody_event,
    "remedies": remedy,
    "regulatory_reports": regulatory_report,
    "trend_signals": trend_signal,
    "signal_memberships": signal_membership,
    "response_templates": response_template,
}
