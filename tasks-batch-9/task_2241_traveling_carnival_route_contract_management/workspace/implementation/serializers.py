"""Response shapes.  Ledger aggregates are derived at read time from the rows
that own them, so a read always reflects the post-cascade truth."""

import calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def jurisdiction(row):
    out = _common(row)
    out.update({
        "state_code": row["state_code"],
        "name": row["name"],
        "permit_lead_days": row["permit_lead_days"],
        "requires_state_ride_inspection": row["requires_state_ride_inspection"],
        "inspection_slot_capacity_per_day": row["inspection_slot_capacity_per_day"],
        "amusement_tax_pct": row["amusement_tax_pct"],
        "max_consecutive_work_days": row["max_consecutive_work_days"],
        "housing_permit_required": row["housing_permit_required"],
        "permit_fee_cents": row["permit_fee_cents"],
    })
    return out


def venue(row):
    out = _common(row)
    out.update({
        "jurisdiction_id": row["jurisdiction_id"],
        "name": row["name"],
        "city": row["city"],
        "lot_area_sqft": row["lot_area_sqft"],
        "power_amps_available": row["power_amps_available"],
        "expected_attendance": row["expected_attendance"],
        "housing_pads_available": row["housing_pads_available"],
        "lot_surface": row["lot_surface"],
    })
    return out


def ride(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "ride_class": row["ride_class"],
        "footprint_sqft": row["footprint_sqft"],
        "power_amps": row["power_amps"],
        "crew_size_setup": row["crew_size_setup"],
        "setup_hours": row["setup_hours"],
        "axle_count": row["axle_count"],
        "requires_state_inspection": row["requires_state_inspection"],
        "status": row["status"],
    })
    return out


def worker(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "employment_type": row["employment_type"],
        "visa_expires_on": row["visa_expires_on"],
        "hourly_rate_cents": row["hourly_rate_cents"],
        "certified_ride_classes": list(row["certified_ride_classes"]),
        "housing_required": row["housing_required"],
        "scheduled_hours_total": calc.worker_scheduled_hours_total(row["id"]),
        "worked_days_count": calc.worker_worked_days_count(row["id"]),
        "compliance_status": calc.worker_compliance_status(row),
    })
    return out


def route(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "season_year": row["season_year"],
        "home_base_state": row["home_base_state"],
        "status": row["status"],
        "stop_count": calc.route_stop_count(row["id"]),
        "total_haul_miles": calc.route_total_haul_miles(row["id"]),
        "total_travel_hours": row["total_travel_hours"],
        "total_guaranteed_cents": calc.route_total_guaranteed_cents(row["id"]),
        "closed_stop_count": calc.route_closed_stop_count(row["id"]),
    })
    return out


def route_stop(row):
    out = _common(row)
    out.update({
        "route_id": row["route_id"],
        "venue_id": row["venue_id"],
        "previous_stop_id": row["previous_stop_id"],
        "sequence_index": row["sequence_index"],
        "haul_miles_from_previous": row["haul_miles_from_previous"],
        "travel_hours_from_previous": row["travel_hours_from_previous"],
        "load_in_start": row["load_in_start"],
        "open_date": row["open_date"],
        "close_date": row["close_date"],
        "teardown_deadline": row["teardown_deadline"],
        "operating_days": row["operating_days"],
        "scheduled_operating_hours": row["scheduled_operating_hours"],
        "status": row["status"],
        "allocated_sqft_used": calc.stop_allocated_sqft_used(row["id"]),
        "power_amps_used": calc.stop_power_amps_used(row["id"]),
        "operating_ride_count": calc.stop_operating_ride_count(row["id"]),
        "labor_cost_provisional_cents":
            calc.stop_labor_cost_provisional_cents(row["id"]),
        "closure_hours_adjudicated": calc.stop_closure_hours_adjudicated(row),
        "compliance_posture": calc.stop_compliance_posture(row)[0],
    })
    return out


def contract(row):
    out = _common(row)
    out.update({
        "route_stop_id": row["route_stop_id"],
        "counterparty_name": row["counterparty_name"],
        "sponsor_name": row["sponsor_name"],
        "revenue_split_pct_operator": row["revenue_split_pct_operator"],
        "guarantee_cents": row["guarantee_cents"],
        "ride_minimum_count": row["ride_minimum_count"],
        "exclusivity": row["exclusivity"],
        "settlement_basis": row["settlement_basis"],
        "negotiation_round": row["negotiation_round"],
        "status": row["status"],
        "last_sent_by_user_id": row["last_sent_by_user_id"],
        "executed_at": row["executed_at"],
    })
    return out


def ride_allocation(row):
    out = _common(row)
    out.update({
        "ride_id": row["ride_id"],
        "route_stop_id": row["route_stop_id"],
        "status": row["status"],
        "footprint_charged_sqft": row["footprint_charged_sqft"],
        "power_charged_amps": row["power_charged_amps"],
        "occupation_start": row["occupation_start"],
        "occupation_end": row["occupation_end"],
        "released_at": row["released_at"],
    })
    return out


def permit_application(row):
    out = _common(row)
    out.update({
        "route_stop_id": row["route_stop_id"],
        "permit_type": row["permit_type"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "axles_declared": row["axles_declared"],
        "fee_cents": row["fee_cents"],
        "status": row["status"],
        "submitted_at": row["submitted_at"],
        "decided_at": row["decided_at"],
        "denial_reason": row["denial_reason"],
    })
    return out


def inspection_order(row):
    out = _common(row)
    out.update({
        "ride_allocation_id": row["ride_allocation_id"],
        "authority": row["authority"],
        "scheduled_date": row["scheduled_date"],
        "status": row["status"],
        "attempt_number": row["attempt_number"],
        "defect_count": row["defect_count"],
        "result_recorded_at": row["result_recorded_at"],
    })
    return out


def crew_assignment(row):
    out = _common(row)
    out.update({
        "route_stop_id": row["route_stop_id"],
        "worker_id": row["worker_id"],
        "crew_role": row["crew_role"],
        "shift_start": row["shift_start"],
        "shift_end": row["shift_end"],
        "shift_hours": row["shift_hours"],
        "cost_cents": row["cost_cents"],
        "housing_pad_assigned": row["housing_pad_assigned"],
        "status": row["status"],
    })
    return out


def ticket_sale(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "route_stop_id": row["route_stop_id"],
        "channel": row["channel"],
        "units": row["units"],
        "unit_price_cents": row["unit_price_cents"],
        "gross_cents": row["gross_cents"],
        "business_date": row["business_date"],
    }


def settlement(row):
    out = _common(row)
    out.update({
        "contract_id": row["contract_id"],
        "variant": row["variant"],
        "status": row["status"],
        "gross_cents": row["gross_cents"],
        "tax_cents": row["tax_cents"],
        "taxable_net_cents": row["taxable_net_cents"],
        "effective_operator_pct": row["effective_operator_pct"],
        "split_share_cents": row["split_share_cents"],
        "shortfall_penalty_cents": row["shortfall_penalty_cents"],
        "guarantee_effective_cents": row["guarantee_effective_cents"],
        "makegood_deduction_cents": row["makegood_deduction_cents"],
        "settlement_due_cents": row["settlement_due_cents"],
        "dispute_reason": row["dispute_reason"],
        "finalized_at": row["finalized_at"],
    })
    return out


def weather_closure(row):
    out = _common(row)
    out.update({
        "route_stop_id": row["route_stop_id"],
        "cause": row["cause"],
        "closed_from": row["closed_from"],
        "closed_to": row["closed_to"],
        "closure_hours_raw": row["closure_hours_raw"],
        "abated_hours": row["abated_hours"],
        "status": row["status"],
    })
    return out


def make_good(row):
    out = _common(row)
    out.update({
        "weather_closure_id": row["weather_closure_id"],
        "contract_id": row["contract_id"],
        "kind": row["kind"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "responded_at": row["responded_at"],
    })
    return out


def readiness(stop):
    posture, blocking = calc.stop_compliance_posture(stop)
    executed = calc.executed_contract_of_stop(stop["id"])
    return {
        "route_stop_id": stop["id"],
        "compliance_posture": posture,
        "blocking_error_id": blocking,
        "event_permit_ok": calc.event_permit_ok(stop),
        "inspections_ok": calc.inspections_ok(stop),
        "crew_coverage_ok": calc.crew_coverage_ok(stop),
        "committed_ride_count": len(
            calc.allocations_of_stop(stop["id"], ("COMMITTED",))),
        "ride_minimum_required": int(executed["ride_minimum_count"]) if executed else 0,
    }
