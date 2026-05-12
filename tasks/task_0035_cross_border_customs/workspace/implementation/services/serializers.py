"""Serializers — return clean dicts for API responses."""

# Each serializer returns a fresh dict (defensive copy) so route handlers
# can't accidentally mutate persisted state.


def serialize_hs_code(hs):
    return {
        "id": hs["id"],
        "code": hs["code"],
        "description": hs["description"],
        "keywords": list(hs.get("keywords") or []),
        "country_code_map": dict(hs.get("country_code_map") or {}),
        "tariff_rate_bps": int(hs["tariff_rate_bps"]),
        "vat_rate_bps": int(hs["vat_rate_bps"]),
        "consumption_tax_rate_bps": int(hs.get("consumption_tax_rate_bps") or 0),
        "postal_tax_rate_bps": int(hs["postal_tax_rate_bps"]),
        "status": hs["status"],
        "created_at": hs["created_at"],
    }


def serialize_tariff_rule(tr):
    return {
        "id": tr["id"],
        "hs_code_id": tr["hs_code_id"],
        "origin_country": tr["origin_country"],
        "destination_country": tr["destination_country"],
        "tariff_rate_bps": int(tr["tariff_rate_bps"]),
        "effective_from": tr["effective_from"],
        "effective_to": tr.get("effective_to"),
        "created_at": tr["created_at"],
    }


def serialize_exchange_rate(er):
    return {
        "id": er["id"],
        "from_currency": er["from_currency"],
        "to_currency": er["to_currency"],
        "rate_micros": int(er["rate_micros"]),
        "effective_date": er["effective_date"],
        "created_at": er["created_at"],
    }


def serialize_importer(im):
    return {
        "id": im["id"],
        "name": im["name"],
        "license_number": im["license_number"],
        "status": im["status"],
        "created_at": im["created_at"],
        "updated_at": im["updated_at"],
        "version": im["version"],
    }


def serialize_declarant(dc):
    return {
        "id": dc["id"],
        "name": dc["name"],
        "agent_code": dc["agent_code"],
        "status": dc["status"],
        "created_at": dc["created_at"],
        "updated_at": dc["updated_at"],
        "version": dc["version"],
    }


def serialize_order(od):
    return {
        "id": od["id"],
        "external_order_ref": od["external_order_ref"],
        "importer_id": od["importer_id"],
        "declarant_id": od["declarant_id"],
        "trade_mode": od["trade_mode"],
        "origin_country": od["origin_country"],
        "destination_country": od["destination_country"],
        "currency": od["currency"],
        "line_items": list(od.get("line_items") or []),
        "total_value_minor": int(od["total_value_minor"]),
        "status": od["status"],
        "created_at": od["created_at"],
        "updated_at": od["updated_at"],
        "version": od["version"],
    }


def serialize_declaration(dec):
    return {
        "id": dec["id"],
        "order_id": dec["order_id"],
        "declarant_id": dec["declarant_id"],
        "trade_mode": dec["trade_mode"],
        "destination_country": dec["destination_country"],
        "dutiable_value_method": dec["dutiable_value_method"],
        "importer_id_card_number": dec.get("importer_id_card_number"),
        "bonded_zone_code": dec.get("bonded_zone_code"),
        "contract_number": dec.get("contract_number"),
        "dutiable_value_cny_minor": dec.get("dutiable_value_cny_minor"),
        "tariff_amount_cny_minor": dec.get("tariff_amount_cny_minor"),
        "vat_amount_cny_minor": dec.get("vat_amount_cny_minor"),
        "consumption_tax_cny_minor": dec.get("consumption_tax_cny_minor"),
        "total_tax_cny_minor": dec.get("total_tax_cny_minor"),
        "tax_mode": dec.get("tax_mode"),
        "exchange_rate_date_used": dec.get("exchange_rate_date_used"),
        "status": dec["status"],
        "submission_count": int(dec.get("submission_count") or 0),
        "query_id": dec.get("query_id"),
        "rejection_reason": dec.get("rejection_reason"),
        "release_condition": dec.get("release_condition"),
        "pickup_coordinated_at": dec.get("pickup_coordinated_at"),
        "created_at": dec["created_at"],
        "updated_at": dec["updated_at"],
        "version": dec["version"],
    }


def serialize_line(ln):
    return {
        "id": ln["id"],
        "declaration_id": ln["declaration_id"],
        "order_line_index": int(ln["order_line_index"]),
        "hs_code_id": ln["hs_code_id"],
        "classification_source": ln["classification_source"],
        "override_review_status": ln["override_review_status"],
        "declared_value_minor": ln.get("declared_value_minor"),
        "line_dutiable_value_cny_minor": ln.get("line_dutiable_value_cny_minor"),
        "created_at": ln["created_at"],
    }


def serialize_query(q):
    return {
        "id": q["id"],
        "declaration_id": q["declaration_id"],
        "question": q["question"],
        "required_documents": list(q.get("required_documents") or []),
        "response_text": q.get("response_text"),
        "response_documents": list(q.get("response_documents") or []) if q.get("response_documents") is not None else None,
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def serialize_inspection(ap):
    return {
        "id": ap["id"],
        "declaration_id": ap["declaration_id"],
        "scheduled_at": ap["scheduled_at"],
        "bay_code": ap["bay_code"],
        "status": ap["status"],
        "created_at": ap["created_at"],
    }


def serialize_payment_notice(pn):
    return {
        "id": pn["id"],
        "declaration_id": pn["declaration_id"],
        "amount_cny_minor": int(pn["amount_cny_minor"]),
        "due_at": pn["due_at"],
        "payment_channel": pn.get("payment_channel"),
        "voucher_url": pn.get("voucher_url"),
        "status": pn["status"],
        "idempotency_key": pn.get("idempotency_key"),
        "created_at": pn["created_at"],
        "updated_at": pn["updated_at"],
        "version": pn["version"],
    }


def serialize_refund(rf):
    return {
        "id": rf["id"],
        "declaration_id": rf["declaration_id"],
        "refund_reason": rf["refund_reason"],
        "supporting_documents": list(rf.get("supporting_documents") or []),
        "refundable_amount_cny_minor": rf.get("refundable_amount_cny_minor"),
        "executed_amount_cny_minor": int(rf.get("executed_amount_cny_minor") or 0),
        "status": rf["status"],
        "rejection_reason": rf.get("rejection_reason"),
        "created_at": rf["created_at"],
        "updated_at": rf["updated_at"],
        "version": rf["version"],
    }


def serialize_audit(ev):
    return {
        "id": ev["id"],
        "subject_type": ev["subject_type"],
        "subject_id": ev["subject_id"],
        "actor_role": ev["actor_role"],
        "actor_id": ev["actor_id"],
        "event_type": ev["event_type"],
        "before_value": dict(ev.get("before_value") or {}),
        "after_value": dict(ev.get("after_value") or {}),
        "created_at": ev["created_at"],
    }
