"""Resource serializers.

Common fields follow PRD 2.4: every resource carries `id` and `created_at`;
all but `InvoiceLine`, `Payment` and `AllowanceLedgerEntry` additionally carry
`updated_at` and `version`.  Every instant is rendered under rule (i) of the
timestamp adjudication in clock.py.
"""

from clock import render_date, render_hhmm, render_instant
from store import db


def _common(row):
    out = {"id": row["id"], "created_at": render_instant(row["created_at"])}
    if "version" in row:
        out["updated_at"] = render_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


# ---------------------------------------------------------------------------
# Live computed aggregates.
# ---------------------------------------------------------------------------
def account_outstanding(account_id):
    """PRD 3.1 / calculations.account_outstanding_balance."""
    total = 0
    for invoice in db.invoices.values():
        if invoice["account_id"] == account_id and invoice["status"] in (
            "ISSUED",
            "PARTIALLY_PAID",
        ):
            total += invoice_amount_due(invoice)
    return total


def request_items(request_id):
    return [i for i in db.request_items.values() if i["service_request_id"] == request_id]


def request_final_total(service_request):
    total = 0
    for item in request_items(service_request["id"]):
        if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
            continue
        total += item["charged_service_cents"] + item["part_fee_cents"]
    return total


def invoice_lines(invoice_id):
    rows = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id]
    rows.sort(key=lambda l: l["sequence_index"])
    return rows


def invoice_taxable_subtotal(invoice):
    return sum(l["amount_cents"] for l in invoice_lines(invoice["id"]) if l["taxable"])


def invoice_nontaxable_subtotal(invoice):
    return sum(
        l["amount_cents"] for l in invoice_lines(invoice["id"]) if not l["taxable"]
    )


def invoice_amount_paid(invoice):
    return sum(
        p["amount_cents"] for p in db.payments.values() if p["invoice_id"] == invoice["id"]
    )


def invoice_total(invoice):
    return (
        invoice_taxable_subtotal(invoice)
        + invoice_nontaxable_subtotal(invoice)
        + invoice["tax_cents"]
    )


def invoice_amount_due(invoice):
    return invoice_total(invoice) - invoice_amount_paid(invoice)


def bench_day_booked_minutes(bench_day_id):
    """PRD 3.7 / calculations.bench_minutes_booked."""
    total = 0
    for item in db.request_items.values():
        if item["bench_day_id"] == bench_day_id and item["custody_location"] == "BENCH":
            minutes = item["service_minutes_assessed"]
            if minutes is None:
                minutes = item["service_minutes_declared"]
            total += minutes
    return total


def run_active_stops(run_id):
    stops = [
        s
        for s in db.route_stops.values()
        if s["route_run_id"] == run_id
        and s["status"] in ("SCHEDULED", "ARRIVED", "SERVICED")
    ]
    stops.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return stops


def stop_service_minutes(stop, assessed=False):
    """PRD 3.4: sum over the stop's billable items."""
    total = 0
    for item in request_items(stop["service_request_id"]):
        if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
            continue
        if assessed and item["service_minutes_assessed"] is not None:
            total += item["service_minutes_assessed"]
        else:
            total += item["service_minutes_declared"]
    return total


def run_booked_minutes(run_id, assessed=False):
    return sum(stop_service_minutes(s, assessed) for s in run_active_stops(run_id))


def compartment_stored_item_count(compartment):
    request_id = compartment["current_service_request_id"]
    if not request_id:
        return 0
    return len(
        [
            i
            for i in request_items(request_id)
            if i["custody_location"] == "LOCKER"
        ]
    )


def compartment_stored_value(compartment):
    request_id = compartment["current_service_request_id"]
    if not request_id:
        return 0
    return sum(
        i["final_gross_cents"]
        for i in request_items(request_id)
        if i["custody_location"] in ("LOCKER", "BENCH")
    )


# ---------------------------------------------------------------------------
# Serializers.
# ---------------------------------------------------------------------------
def account(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "account_type": row["account_type"],
            "zone_code": row["zone_code"],
            "billing_mode": row["billing_mode"],
            "tax_exempt": row["tax_exempt"],
            "credit_limit_cents": row["credit_limit_cents"],
            "contact_email": row["contact_email"],
            "status": row["status"],
            "outstanding_balance_cents": account_outstanding(row["id"]),
        }
    )
    return out


def plan_tier(row):
    out = _common(row)
    out.update(
        {
            "code": row["code"],
            "monthly_fee_cents": row["monthly_fee_cents"],
            "included_items_per_cycle": row["included_items_per_cycle"],
            "overage_discount_pct": row["overage_discount_pct"],
            "allowed_cadences": list(row["allowed_cadences"]),
        }
    )
    return out


def subscription(row):
    out = _common(row)
    out.update(
        {
            "account_id": row["account_id"],
            "plan_tier_id": row["plan_tier_id"],
            "cadence": row["cadence"],
            "anchor_date": render_date(row["anchor_date"]),
            "status": row["status"],
            "effective_monthly_fee_cents": row["effective_monthly_fee_cents"],
            "included_items_this_cycle": row["included_items_this_cycle"],
            "allowance_remaining": row["allowance_remaining"],
            "cycle_index": row["cycle_index"],
            "cycle_start_date": render_date(row["cycle_start_date"]),
            "cycle_end_date": render_date(row["cycle_end_date"]),
            "next_service_date": render_date(row["next_service_date"]),
            "skip_count_this_cycle": row["skip_count_this_cycle"],
            "paused_at": render_instant(row["paused_at"]),
        }
    )
    return out


def item_class_spec(row):
    out = _common(row)
    out.update(
        {
            "item_class": row["item_class"],
            "bevel_angle_degrees": row["bevel_angle_degrees"],
            "base_service_minutes": row["base_service_minutes"],
            "list_price_cents": row["list_price_cents"],
            "required_certification": row["required_certification"],
            "price_tier": row["price_tier"],
            "min_locker_size": row["min_locker_size"],
            "loaner_eligible": row["loaner_eligible"],
        }
    )
    return out


def service_request(row):
    out = _common(row)
    out.update(
        {
            "account_id": row["account_id"],
            "subscription_id": row["subscription_id"],
            "origin_warranty_claim_id": row["origin_warranty_claim_id"],
            "channel": row["channel"],
            "priority": row["priority"],
            "requested_date": render_date(row["requested_date"]),
            "locker_site_code": row["locker_site_code"],
            "locker_high_value_authorized": row["locker_high_value_authorized"],
            "status": row["status"],
            "billing_status": row["billing_status"],
            "item_count": len(request_items(row["id"])),
            "quoted_total_cents": row["quoted_total_cents"],
            "final_total_cents": request_final_total(row),
            "completed_at": render_instant(row["completed_at"]),
        }
    )
    return out


def request_item(row):
    out = _common(row)
    out.update(
        {
            "service_request_id": row["service_request_id"],
            "item_class_spec_id": row["item_class_spec_id"],
            "bench_day_id": row["bench_day_id"],
            "rework_of_request_item_id": row["rework_of_request_item_id"],
            "assessed_by_technician_id": row["assessed_by_technician_id"],
            "item_class": row["item_class"],
            "declared_damage_tier": row["declared_damage_tier"],
            "assessed_damage_tier": row["assessed_damage_tier"],
            "quoted_gross_cents": row["quoted_gross_cents"],
            "final_gross_cents": row["final_gross_cents"],
            "charged_service_cents": row["charged_service_cents"],
            "part_fee_cents": row["part_fee_cents"],
            "service_minutes_declared": row["service_minutes_declared"],
            "service_minutes_assessed": row["service_minutes_assessed"],
            "requires_reauthorization": row["requires_reauthorization"],
            "authorization_status": row["authorization_status"],
            "service_status": row["service_status"],
            "custody_location": row["custody_location"],
            "allowance_applied": row["allowance_applied"],
            "delivered_at": render_instant(row["delivered_at"]),
        }
    )
    return out


def technician(row):
    out = _common(row)
    out.update({"full_name": row["full_name"], "certifications": list(row["certifications"])})
    return out


def van(row):
    out = _common(row)
    out.update(
        {
            "code": row["code"],
            "default_service_minute_budget": row["default_service_minute_budget"],
            "default_stop_cap": row["default_stop_cap"],
        }
    )
    return out


def route_run(row):
    from constants import DRIVE_BUFFER_MINUTES_PER_STOP

    stops = run_active_stops(row["id"])
    booked = sum(stop_service_minutes(s) for s in stops)
    out = _common(row)
    out.update(
        {
            "van_id": row["van_id"],
            "technician_id": row["technician_id"],
            "run_date": render_date(row["run_date"]),
            "zone_code": row["zone_code"],
            "service_minute_budget": row["service_minute_budget"],
            "stop_cap": row["stop_cap"],
            "day_window_start": render_hhmm(row["day_window_start"]),
            "day_window_end": render_hhmm(row["day_window_end"]),
            "status": row["status"],
            "scheduled_stop_count": len(stops),
            "booked_service_minutes": booked,
            "committed_minutes_provisional": booked
            + DRIVE_BUFFER_MINUTES_PER_STOP * len(stops),
            "committed_minutes_final": row["committed_minutes_final"],
        }
    )
    return out


def route_stop(row):
    out = _common(row)
    out.update(
        {
            "route_run_id": row["route_run_id"],
            "service_request_id": row["service_request_id"],
            "account_id": row["account_id"],
            "spilled_from_route_run_id": row["spilled_from_route_run_id"],
            "sequence": row["sequence"],
            "arrival_window_start": render_hhmm(row["arrival_window_start"]),
            "arrival_window_end": render_hhmm(row["arrival_window_end"]),
            "stop_service_minutes": stop_service_minutes(row),
            "spill_hop_count": row["spill_hop_count"],
            "status": row["status"],
        }
    )
    return out


def locker_compartment(row):
    out = _common(row)
    out.update(
        {
            "site_code": row["site_code"],
            "size": row["size"],
            "current_service_request_id": row["current_service_request_id"],
            "status": row["status"],
            "access_code": row["access_code"],
            "hold_expires_at": render_instant(row["hold_expires_at"]),
            "last_released_at": render_instant(row["last_released_at"]),
            "stored_item_count": compartment_stored_item_count(row),
            "stored_value_cents": compartment_stored_value(row),
        }
    )
    return out


def bench_day(row):
    out = _common(row)
    out.update(
        {
            "bench_date": render_date(row["bench_date"]),
            "bench_minute_budget": row["bench_minute_budget"],
            "booked_minutes": bench_day_booked_minutes(row["id"]),
        }
    )
    return out


def loaner_unit(row):
    out = _common(row)
    out.update(
        {
            "item_class_spec_id": row["item_class_spec_id"],
            "grade": row["grade"],
            "cycle_ceiling": row["cycle_ceiling"],
            "cycle_count": row["cycle_count"],
            "damage_reported": row["damage_reported"],
            "status": row["status"],
        }
    )
    return out


def loaner_issue(row):
    out = _common(row)
    out.update(
        {
            "loaner_unit_id": row["loaner_unit_id"],
            "service_request_id": row["service_request_id"],
            "requested_grade": row["requested_grade"],
            "issued_at": render_instant(row["issued_at"]),
            "due_at": render_instant(row["due_at"]),
            "returned_at": render_instant(row["returned_at"]),
            "delay_attribution": row["delay_attribution"],
            "late_fee_cents": row["late_fee_cents"],
            "substituted": row["substituted"],
            "status": row["status"],
        }
    )
    return out


def warranty_claim(row):
    out = _common(row)
    out.update(
        {
            "request_item_id": row["request_item_id"],
            "account_id": row["account_id"],
            "rework_service_request_id": row["rework_service_request_id"],
            "decided_by_technician_id": row["decided_by_technician_id"],
            "reason": row["reason"],
            "abuse_finding": row["abuse_finding"],
            "resubmit_count": row["resubmit_count"],
            "credit_basis_cents": row["credit_basis_cents"],
            "status": row["status"],
        }
    )
    return out


def invoice(row):
    out = _common(row)
    paid = invoice_amount_paid(row)
    out.update(
        {
            "account_id": row["account_id"],
            "service_request_id": row["service_request_id"],
            "billing_mode": row["billing_mode"],
            "billing_period": row["billing_period"],
            "taxable_subtotal_cents": invoice_taxable_subtotal(row),
            "nontaxable_subtotal_cents": invoice_nontaxable_subtotal(row),
            "tax_cents": row["tax_cents"],
            "total_cents": invoice_total(row),
            "amount_paid_cents": paid,
            "amount_due_cents": invoice_total(row) - paid,
            "status": row["status"],
        }
    )
    return out


def invoice_line(row):
    out = _common(row)
    out.update(
        {
            "invoice_id": row["invoice_id"],
            "request_item_id": row["request_item_id"],
            "source_warranty_claim_id": row["source_warranty_claim_id"],
            "source": row["source"],
            "description": row["description"],
            "amount_cents": row["amount_cents"],
            "taxable": row["taxable"],
            "sequence_index": row["sequence_index"],
        }
    )
    return out


def payment(row):
    out = _common(row)
    out.update(
        {
            "invoice_id": row["invoice_id"],
            "amount_cents": row["amount_cents"],
            "method": row["method"],
            "applied_at": render_instant(row["applied_at"]),
            "resulting_invoice_status": row["resulting_invoice_status"],
        }
    )
    return out


def allowance_entry(row):
    out = _common(row)
    out.update(
        {
            "subscription_id": row["subscription_id"],
            "request_item_id": row["request_item_id"],
            "cycle_index": row["cycle_index"],
            "kind": row["kind"],
            "quantity": row["quantity"],
            "reason": row["reason"],
        }
    )
    return out
