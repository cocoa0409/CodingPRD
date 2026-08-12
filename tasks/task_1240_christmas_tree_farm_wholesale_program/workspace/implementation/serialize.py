"""Entity serializers. Internal storage keeps datetimes/dates as objects;
these functions produce the exact wire shapes declared in SCAFFOLD 1.1."""
from timeutil import fmt_dt, fmt_dt_seconds, fmt_opt_dt


def season_out(s):
    return {
        "id": s["id"],
        "year": s["year"],
        "booking_open_at": fmt_dt(s["booking_open_at"]),
        "booking_close_at": fmt_dt(s["booking_close_at"]),
        "harvest_window_start": s["harvest_window_start"].isoformat(),
        "harvest_window_end": s["harvest_window_end"].isoformat(),
        "shipping_window_start": fmt_dt(s["shipping_window_start"]),
        "shipping_window_end": fmt_dt(s["shipping_window_end"]),
        "posture": s["posture"],
        "ops_run_index": s["ops_run_index"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def block_out(b):
    return {
        "id": b["id"],
        "season_id": b["season_id"],
        "block_code": b["block_code"],
        "acreage": b["acreage"],
        "ucut_designated": b["ucut_designated"],
        "rotation_state": b["rotation_state"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def crop_lot_out(lot):
    return {
        "id": lot["id"],
        "block_id": lot["block_id"],
        "species": lot["species"],
        "planted_year": lot["planted_year"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def bucket_out(b):
    return {
        "id": b["id"],
        "crop_lot_id": b["crop_lot_id"],
        "height_class": b["height_class"],
        "baseline_count": b["baseline_count"],
        "standing_count": b["standing_count"],
        "reserved_count": b["reserved_count"],
        "tagged_active_count": b["tagged_active_count"],
        "cut_cumulative": b["cut_cumulative"],
        "culled_cumulative": b["culled_cumulative"],
        "ucut_sold_cumulative": b["ucut_sold_cumulative"],
        "consigned_cumulative": b["consigned_cumulative"],
        "available_count": b["standing_count"] - b["reserved_count"],
        "last_shrink_delta": b["last_shrink_delta"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def survey_out(sv):
    return {
        "id": sv["id"],
        "crop_lot_id": sv["crop_lot_id"],
        "surveyed_counts": dict(sv["surveyed_counts"]),
        "status": sv["status"],
        "posted_at": fmt_opt_dt(sv["posted_at"]),
        "created_at": sv["created_at"],
        "updated_at": sv["updated_at"],
        "version": sv["version"],
    }


def buyer_out(buyer, exposure_cents):
    return {
        "id": buyer["id"],
        "name": buyer["name"],
        "credit_limit_cents": buyer["credit_limit_cents"],
        "standing": buyer["standing"],
        "exposure_cents": exposure_cents,
        "created_at": buyer["created_at"],
        "updated_at": buyer["updated_at"],
        "version": buyer["version"],
    }


def order_out(o):
    return {
        "id": o["id"],
        "season_id": o["season_id"],
        "buyer_account_id": o["buyer_account_id"],
        "species": o["species"],
        "height_class": o["height_class"],
        "quantity": o["quantity"],
        "unit_price_cents": o["unit_price_cents"],
        "allocated_qty": o["allocated_qty"],
        "invoice_subtotal_cents": o["invoice_subtotal_cents"],
        "discount_pct_applied": o["discount_pct_applied"],
        "invoice_discount_cents": o["invoice_discount_cents"],
        "invoice_total_cents": o["invoice_total_cents"],
        "submitted_at": fmt_opt_dt(o["submitted_at"]),
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def allocation_out(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "bucket_id": a["bucket_id"],
        "quantity": a["quantity"],
        "cut_qty": a["cut_qty"],
        "loaded_qty": a["loaded_qty"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def crew_out(c):
    return {
        "id": c["id"],
        "season_id": c["season_id"],
        "crew_code": c["crew_code"],
        "size": c["size"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ticket_out(t):
    return {
        "id": t["id"],
        "crew_id": t["crew_id"],
        "block_id": t["block_id"],
        "work_date": t["work_date"].isoformat(),
        "hours_worked": t["hours_worked"],
        "lines": [dict(line) for line in t["lines"]],
        "piece_total_cents": t["piece_total_cents"],
        "hourly_floor_cents": t["hourly_floor_cents"],
        "gross_pay_cents": t["gross_pay_cents"],
        "pay_basis": t["pay_basis"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def load_out(ld):
    return {
        "id": ld["id"],
        "season_id": ld["season_id"],
        "carrier_name": ld["carrier_name"],
        "capacity_units": ld["capacity_units"],
        "pickup_window_start": fmt_dt(ld["pickup_window_start"]),
        "pickup_window_end": fmt_dt(ld["pickup_window_end"]),
        "lines": [dict(line) for line in ld["lines"]],
        "total_units": ld["total_units"],
        "status": ld["status"],
        "created_at": ld["created_at"],
        "updated_at": ld["updated_at"],
        "version": ld["version"],
    }


def consignment_out(c):
    return {
        "id": c["id"],
        "season_id": c["season_id"],
        "bucket_id": c["bucket_id"],
        "lot_name": c["lot_name"],
        "quantity": c["quantity"],
        "unit_price_cents": c["unit_price_cents"],
        "max_return_pct": c["max_return_pct"],
        "delivered_count": c["delivered_count"],
        "returned_count": c["returned_count"],
        "provisional_settlement_cents": c["provisional_settlement_cents"],
        "final_settlement_cents": c["final_settlement_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def tag_out(t):
    return {
        "id": t["id"],
        "block_id": t["block_id"],
        "bucket_id": t["bucket_id"],
        "customer_name": t["customer_name"],
        "price_cents": t["price_cents"],
        "expires_at": fmt_dt_seconds(t["expires_at"]),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def cull_out(c):
    return {
        "id": c["id"],
        "bucket_id": c["bucket_id"],
        "count": c["count"],
        "reason": c["reason"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def replant_out(r):
    return {
        "id": r["id"],
        "block_id": r["block_id"],
        "species": r["species"],
        "planned_count": r["planned_count"],
        "proposed_by_user_id": r["proposed_by_user_id"],
        "approved_by_user_id": r["approved_by_user_id"],
        "created_crop_lot_id": r["created_crop_lot_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
