"""Row -> JSON projection. Every instant goes through clock.render_instant."""

import derive
from clock import render_instant
from store import DB


def _common(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "updated_at": render_instant(row["updated_at"]),
        "version": row["version"],
    }


def plan(row):
    out = _common(row)
    out.update(
        {
            "tier": row["tier"],
            "name": row["name"],
            "monthly_fee_cents": row["monthly_fee_cents"],
            "max_members": row["max_members"],
            "profile_quota_per_cycle": row["profile_quota_per_cycle"],
            "scan_quota_per_cycle": row["scan_quota_per_cycle"],
            "removal_quota_per_cycle": row["removal_quota_per_cycle"],
            "per_member_removal_subcap": row["per_member_removal_subcap"],
        }
    )
    return out


def account(row):
    out = _common(row)
    pools = derive.pool_figures(row["id"])
    out.update(
        {
            "plan_id": row["plan_id"],
            "primary_member_id": row["primary_member_id"],
            "status": row["status"],
            "legal_hold": row["legal_hold"],
            "legal_hold_set_at": render_instant(row["legal_hold_set_at"]),
            "suspended_at": render_instant(row["suspended_at"]),
            "cancelled_at": render_instant(row["cancelled_at"]),
        }
    )
    for resource in ("profile", "scan", "removal"):
        figures = pools[resource]
        out[f"{resource}_units_granted"] = figures["granted"]
        out[f"{resource}_units_consumed"] = figures["consumed"]
        out[f"{resource}_units_released"] = figures["released"]
        out[f"{resource}_units_remaining"] = figures["remaining"]
    return out


def member(row):
    out = _common(row)
    out.update(
        {
            "account_id": row["account_id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "role_in_family": row["role_in_family"],
            "is_primary": row["is_primary"],
            "status": row["status"],
            "authorization_status": row["authorization_status"],
            "invitation_token": row["invitation_token"],
            "activated_at": render_instant(row["activated_at"]),
            "authorization_revoked_at": render_instant(row["authorization_revoked_at"]),
            "removal_units_consumed_this_cycle": derive.member_removal_net(row),
        }
    )
    return out


def profile(row):
    out = _common(row)
    exposures = derive.profile_exposures(row["id"])
    hyg = derive.profile_hygiene(row)
    out.update(
        {
            "member_id": row["member_id"],
            "full_name": row["full_name"],
            "date_of_birth": row["date_of_birth"],
            "primary_address": row["primary_address"],
            "rescan_cadence_days": row["rescan_cadence_days"],
            "two_factor_attested": row["two_factor_attested"],
            "status": row["status"],
            "activated_at": render_instant(row["activated_at"]),
            "retired_at": render_instant(row["retired_at"]),
            "last_completed_scan_at": render_instant(row["last_completed_scan_at"]),
            "open_exposure_count": len(
                [e for e in exposures if e["status"] in ("FOUND", "REAPPEARED")]
            ),
            "suppressed_exposure_count": len(
                [e for e in exposures if e["status"] in ("SUPPRESSED", "RE_SUPPRESSED")]
            ),
            "hygiene_score": hyg["hygiene_score"],
            "hygiene_band": hyg["hygiene_band"],
        }
    )
    return out


def identifier(row):
    # Immutable: only id and created_at (PRD §2.4).
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "profile_id": row["profile_id"],
        "identifier_type": row["identifier_type"],
        "identifier_value": row["identifier_value"],
    }


def broker(row):
    out = _common(row)
    reappearances, expired, rejected, on_time = derive.broker_counts_lifetime(row["id"])
    import calc

    out.update(
        {
            "name": row["name"],
            "opt_out_method": row["opt_out_method"],
            "jurisdiction": row["jurisdiction"],
            "response_window_days": row["response_window_days"],
            "requires_identity_verification": row["requires_identity_verification"],
            "status": row["status"],
            "retired_at": render_instant(row["retired_at"]),
            "reappearance_count": reappearances,
            "expired_request_count": expired,
            "rejected_request_count": rejected,
            "on_time_completion_count": on_time,
            "compliance_score": calc.compliance_score(
                reappearances, expired, rejected, on_time
            ),
        }
    )
    return out


def document(row):
    out = _common(row)
    out.update(
        {
            "member_id": row["member_id"],
            "document_type": row["document_type"],
            "document_reference": row["document_reference"],
            # Caller-supplied instant: echoed VERBATIM (see clock.py adjudication).
            "expires_at": row["expires_at"],
            "status": row["status"],
            "verified_at": render_instant(row["verified_at"]),
            "rejection_reason_code": row["rejection_reason_code"],
            "effective_status": derive.document_effective_status(row),
        }
    )
    return out


def scan(row):
    out = _common(row)
    new_exposures = len(
        [e for e in DB.exposures.values() if e["discovered_by_scan_id"] == row["id"]]
    )
    out.update(
        {
            "profile_id": row["profile_id"],
            "kind": row["kind"],
            "status": row["status"],
            "retry_count": row["retry_count"],
            "started_at": render_instant(row["started_at"]),
            "completed_at": render_instant(row["completed_at"]),
            "failure_reason": row["failure_reason"],
            "entitlement_units_held": row["entitlement_units_held"],
            "findings_count": row["findings_count"],
            "new_exposure_count": new_exposures,
            "reappearance_hit_count": row["reappearance_hit_count"],
        }
    )
    return out


def exposure(row):
    out = _common(row)
    out.update(
        {
            "profile_id": row["profile_id"],
            "broker_id": row["broker_id"],
            "discovered_by_scan_id": row["discovered_by_scan_id"],
            "exposure_kind": row["exposure_kind"],
            "source_url": row["source_url"],
            "status": row["status"],
            "first_found_at": render_instant(row["first_found_at"]),
            "last_seen_at": render_instant(row["last_seen_at"]),
            "last_suppressed_at": render_instant(row["last_suppressed_at"]),
            "suppression_count": row["suppression_count"],
            "reappearance_count": row["reappearance_count"],
            "fee_exempt": row["status"] == "REAPPEARED",
        }
    )
    return out


def removal_request(row):
    out = _common(row)
    out.update(
        {
            "exposure_id": row["exposure_id"],
            "broker_id": row["broker_id"],
            "member_id": row["member_id"],
            "status": row["status"],
            "submitted_at": render_instant(row["submitted_at"]),
            "acknowledged_at": render_instant(row["acknowledged_at"]),
            "closed_at": render_instant(row["closed_at"]),
            "sla_deadline_at": render_instant(row["sla_deadline_at"]),
            "effective_window_days": row["effective_window_days"],
            "deadline_variant": row["deadline_variant"],
            "submitted_by_agent_id": row["submitted_by_agent_id"],
            "completed_by_agent_id": row["completed_by_agent_id"],
            "broker_reference": row["broker_reference"],
            "rejection_reason_code": row["rejection_reason_code"],
            "escalation_count": row["escalation_count"],
            "entitlement_units_consumed": row["entitlement_units_consumed"],
            "entitlement_units_released": row["entitlement_units_released"],
            "on_time": derive.request_on_time(row),
        }
    )
    return out


def breach_event(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            # Caller-supplied instants: echoed VERBATIM.
            "breach_date": row["breach_date"],
            "disclosed_at": row["disclosed_at"],
            "record_types": list(row["record_types"]),
            "base_severity_points": row["base_severity_points"],
            "ingest_count": row["ingest_count"],
            "alert_count": len(
                [a for a in DB.alerts.values() if a["breach_event_id"] == row["id"]]
            ),
        }
    )
    return out


def alert(row):
    out = _common(row)
    out.update(
        {
            "breach_event_id": row["breach_event_id"],
            "identifier_id": row["identifier_id"],
            "member_id": row["member_id"],
            "severity": row["severity"],
            "severity_points": row["severity_points"],
            "status": row["status"],
            "acknowledged_at": render_instant(row["acknowledged_at"]),
            "resolved_at": render_instant(row["resolved_at"]),
            "escalation_count": row["escalation_count"],
        }
    )
    return out


def finding(row):
    import constants as K

    out = _common(row)
    out.update(
        {
            "profile_id": row["profile_id"],
            "finding_type": row["finding_type"],
            "detail": row["detail"],
            "status": row["status"],
            # Adjudication of friction 8: `weight` is ALWAYS the per-type penalty.
            # PRD §3.7 says the weight "contributes to the score only while the
            # finding's status is OPEN" -- the contribution is gated, not the
            # weight itself. Reporting 0 on a REMEDIATED row would erase a value
            # the PRD declares the row exposes.
            "weight": K.HYGIENE_WEIGHTS[row["finding_type"]],
            "remediated_at": render_instant(row["remediated_at"]),
        }
    )
    return out


def addon(row):
    out = _common(row)
    bound, available = derive.addon_seat_counts(row)
    out.update(
        {
            "account_id": row["account_id"],
            "addon_type": row["addon_type"],
            "seats_total": row["seats_total"],
            "per_seat_fee_cents": row["per_seat_fee_cents"],
            "status": row["status"],
            "suspended_at": render_instant(row["suspended_at"]),
            "prorated_charge_cents": row["prorated_charge_cents"],
            "seats_bound": bound,
            "seats_available": available,
        }
    )
    return out


def seat(row):
    out = _common(row)
    out.update(
        {
            "addon_id": row["addon_id"],
            "member_id": row["member_id"],
            "device_label": row["device_label"],
            "status": row["status"],
            "bound_at": render_instant(row["bound_at"]),
            "released_at": render_instant(row["released_at"]),
            "voided_at": render_instant(row["voided_at"]),
            "bind_count": row["bind_count"],
            "rebind_eligible_at": render_instant(derive.seat_rebind_eligible_at(row)),
        }
    )
    return out


def cycle(row):
    out = _common(row)
    pre, discount, total = derive.cycle_money(row)
    out.update(
        {
            "account_id": row["account_id"],
            "cycle_seq": row["cycle_seq"],
            "starts_at": render_instant(row["starts_at"]),
            "ends_at": render_instant(row["ends_at"]),
            "status": row["status"],
            "base_charge_cents": row["base_charge_cents"],
            "proration_charge_cents": row["proration_charge_cents"],
            "proration_credit_cents": row["proration_credit_cents"],
            "addon_charge_cents": row["addon_charge_cents"],
            "addon_credit_cents": row["addon_credit_cents"],
            "pre_discount_total_cents": pre,
            "loyalty_discount_cents": discount,
            "total_charged_cents": total,
            "closed_at": render_instant(row["closed_at"]),
        }
    )
    return out


def ledger_entry(row):
    signed = row["amount"] if row["entry_type"] in ("GRANT", "RELEASE") else -row["amount"]
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "account_id": row["account_id"],
        "member_id": row["member_id"],
        "cycle_id": row["cycle_id"],
        "resource_type": row["resource_type"],
        "entry_type": row["entry_type"],
        "amount": row["amount"],
        "signed_amount": signed,
        "reason_code": row["reason_code"],
        "source_reference": row["source_reference"],
    }
