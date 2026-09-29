"""Operating days, the day-close cascade, its amendment compensations, and the
scale-house waste-load lifecycle."""
from decimal import Decimal

from core import (Body, ALL_ROLES, D, clock, created, endpoint, err, filtered,
                  fk_or_404, get_or_404, new_row, obj_response, paged, public,
                  q2, rows, touch)
import services as S


def _cleared_certified_tons(day):
    total = Decimal("0")
    for l in S.loads_of_day(day["id"]):
        if l["screening_status"] == "CLEARED" and l["certified_net_tons"] is not None:
            total += D(l["certified_net_tons"])
    return q2(total)


def _day_approvals(day):
    seen = []
    for l in S.loads_of_day(day["id"]):
        aid = l.get("special_waste_approval_id")
        if aid and aid not in seen:
            seen.append(aid)
    from core import table
    return [table("special_waste_approval")[a] for a in seen
            if a in table("special_waste_approval")]


def register(app):
    # ------------------------------------------------------- operating days ---
    @endpoint(app, "/operating-days", ["POST"], ["SiteOperator"])
    def open_day(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        active_cell_id = b.fk("active_cell_id")
        operating_date = b.timestamp("operating_date")
        face = b.number("working_face_area_sf", gt=0)
        cover = b.enum("cover_material_type", S.COVER_MATERIALS)
        lf = fk_or_404("landfill", landfill_id)
        cell = fk_or_404("cell", active_cell_id)
        S.scope(user_id, lf["id"])
        if cell["landfill_id"] != lf["id"]:
            raise err("ERR_CROSS_SITE_REFERENCE",
                      "active_cell_id names a cell of another landfill.")
        if cell["status"] != "ACTIVE":
            raise err("ERR_CELL_NOT_ACCEPTING_WASTE",
                      "The working-face cell is not ACTIVE.")
        for other in rows("operating_day"):
            if other["landfill_id"] == lf["id"] \
                    and other["operating_date"] == operating_date:
                raise err("ERR_DUPLICATE_OPERATING_DATE",
                          "An operating day already exists for that date.")
        row = new_row("operating_day", {
            "landfill_id": lf["id"],
            "active_cell_id": cell["id"],
            "operating_date": operating_date,
            "working_face_area_sf": face,
            "cover_material_type": cover,
            "tons_placed": 0.0,
            "effective_density_tons_per_cy": 0.0,
            "airspace_consumed_cy": 0.0,
            "amend_reason": None,
            "status": "OPEN",
        })
        return created(public(row))

    @endpoint(app, "/operating-days/<operating_day_id>", ["GET"], ALL_ROLES)
    def read_day(user_id, role, operating_day_id):
        return obj_response(public(get_or_404("operating_day", operating_day_id)))

    @endpoint(app, "/operating-days", ["GET"], ALL_ROLES)
    def list_days(user_id, role):
        return paged(filtered(rows("operating_day"), {
            "landfill_id": "landfill_id",
            "active_cell_id": "active_cell_id",
            "status": "status",
        }))

    @endpoint(app, "/operating-days/<operating_day_id>/waste-loads", ["GET"],
              ALL_ROLES)
    def list_day_loads(user_id, role, operating_day_id):
        day = get_or_404("operating_day", operating_day_id)
        return paged(filtered(S.loads_of_day(day["id"]), {
            "screening_status": "screening_status",
            "billing_status": "billing_status",
        }))

    @endpoint(app, "/operating-days/<operating_day_id>/close", ["POST"],
              ["SiteOperator"])
    def close_day(user_id, role, operating_day_id):
        day = get_or_404("operating_day", operating_day_id)
        S.scope(user_id, day["landfill_id"])
        lf = S.landfill_of_day(day)
        if day["status"] not in ("OPEN", "AMENDED"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A day closes only from OPEN or AMENDED.")
        density = S.effective_density(lf["planned_density_tons_per_cy"],
                                     day["cover_material_type"],
                                     day["working_face_area_sf"])
        tons = _cleared_certified_tons(day)
        consumption = S.day_consumption(tons, density)
        # Rung 23 — permitted-airspace ceiling.
        if D(lf["consumed_airspace_cy"]) + consumption \
                > D(lf["permitted_total_airspace_cy"]):
            raise err("ERR_PERMITTED_AIRSPACE_EXCEEDED",
                      "The close would drive consumption past the permit.")
        # Rung 24 — a live host community agreement prices the day.
        hca = S.live_host_agreement(lf["id"])
        if hca is None:
            raise err("ERR_NO_EXECUTED_HOST_AGREEMENT",
                      "No executed host community agreement prices this site.")
        # Rung 28 — closing-out integrity.
        loads = S.loads_of_day(day["id"])
        for l in loads:
            if l["screening_status"] in ("PENDING", "FLAGGED"):
                raise err("ERR_PENDING_SCREENING_PRESENT",
                          "A load is still in screening.")
        for l in loads:
            if l["screening_status"] == "CLEARED" \
                    and l["certified_net_tons"] is None:
                raise err("ERR_UNCERTIFIED_LOADS_PRESENT",
                          "A cleared load has no certified weight.")
        # Step three — final pricing in the pinned chronological order.
        pending = [l for l in loads if l["screening_status"] == "CLEARED"
                   and l["billing_status"] == "PROVISIONAL"]
        for load in sorted(pending, key=S.load_order_key):
            cumulative = S.cumulative_month_tons(load)
            royalty = S.royalty_amount(load["certified_net_tons"], cumulative, hca)
            load["host_royalty_amount"] = royalty
            load["final_charge_amount"] = S.final_charge_amount(
                load["certified_net_tons"], royalty, hca)
            load["billing_status"] = "FINALIZED"
            touch(load)
        # Steps one, two and four.
        day["tons_placed"] = float(tons)
        day["effective_density_tons_per_cy"] = float(density)
        day["airspace_consumed_cy"] = float(consumption)
        day["status"] = "CLOSED"
        touch(day)
        # Link 1 and link 2.
        cell = S.cell_of(day["active_cell_id"])
        S.sync_cell(cell)
        touch(cell)
        went_full = False
        if cell["status"] == "ACTIVE" and D(cell["consumed_airspace_cy"]) \
                >= D(cell["design_airspace_cy"]) * S.CELL_FULL_FRACTION:
            cell["status"] = "FULL"
            touch(cell)
            went_full = True
        # Link 3 and link 4.
        if went_full:
            S.sync_landfill(lf)
            if lf["active_cell_count"] == 0:
                lf["operating_status"] = "SUSPENDED_NO_AIRSPACE"
                S.suspend_approved_approvals(lf)
        # Ledger sync.
        S.sync_landfill(lf)
        S.apply_life_restriction(lf)
        touch(lf)
        # Tonnage sync.
        for approval in _day_approvals(day):
            changed = S.sync_approval(approval)
            if approval["status"] == "APPROVED" \
                    and D(approval["consumed_tons"]) >= D(approval["approved_tons_cap"]):
                approval["status"] = "EXHAUSTED"
                changed = True
            if changed:
                touch(approval)
        return obj_response(public(day))

    @endpoint(app, "/operating-days/<operating_day_id>/amend", ["POST"],
              ["SiteOperator"])
    def amend_day(user_id, role, operating_day_id):
        b = Body()
        amend_reason = b.string("amend_reason")
        day = get_or_404("operating_day", operating_day_id)
        S.scope(user_id, day["landfill_id"])
        lf = S.landfill_of_day(day)
        if day["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a CLOSED day may be amended.")
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION", "The site is CLOSED.")
        # Compensation 1.
        day["airspace_consumed_cy"] = 0.0
        day["effective_density_tons_per_cy"] = 0.0
        day["tons_placed"] = 0.0
        day["amend_reason"] = amend_reason
        day["status"] = "AMENDED"
        touch(day)
        # Compensation 2 and 3.
        cell = S.cell_of(day["active_cell_id"])
        S.sync_cell(cell)
        reopened = False
        if cell["status"] == "FULL" and D(cell["consumed_airspace_cy"]) \
                < D(cell["design_airspace_cy"]) * S.CELL_FULL_FRACTION:
            cell["status"] = "ACTIVE"
            reopened = True
        touch(cell)
        # Compensation 4.
        for load in S.loads_of_day(day["id"]):
            if load["billing_status"] == "FINALIZED":
                load["billing_status"] = "PROVISIONAL"
                load["final_charge_amount"] = None
                load["host_royalty_amount"] = None
                touch(load)
        # Compensation 5.
        S.sync_landfill(lf)
        if reopened:
            S.lift_no_airspace_suspension(lf)
        touch(lf)
        for approval in _day_approvals(day):
            changed = S.sync_approval(approval)
            if approval["status"] == "EXHAUSTED" \
                    and D(approval["consumed_tons"]) < D(approval["approved_tons_cap"]):
                approval["status"] = "APPROVED"
                changed = True
            if changed:
                touch(approval)
        return obj_response(public(day))

    # ---------------------------------------------------------- waste loads ---
    @endpoint(app, "/waste-loads", ["POST"], ["ScaleOperator"])
    def receive_load(user_id, role):
        b = Body()
        operating_day_id = b.fk("operating_day_id")
        hauler_ref = b.string("hauler_ref", minlen=1, maxlen=40)
        waste_stream = b.enum("waste_stream", S.WASTE_STREAMS)
        manifest_tons = b.number("manifest_tons", gt=0)
        load_check_result = b.enum("load_check_result", S.LOAD_CHECK_RESULTS)
        if waste_stream in S.SPECIAL_STREAMS:
            approval_id = b.fk("special_waste_approval_id")
        else:
            b.forbid("special_waste_approval_id",
                     "must be omitted for ordinary waste streams.")
            approval_id = None
        day = fk_or_404("operating_day", operating_day_id)
        approval = (fk_or_404("special_waste_approval", approval_id)
                    if approval_id is not None else None)
        S.scope(user_id, day["landfill_id"])
        cell = S.cell_of(day["active_cell_id"])
        if cell["landfill_id"] != day["landfill_id"]:
            raise err("ERR_CROSS_SITE_REFERENCE",
                      "The working-face cell belongs to another landfill.")
        if approval is not None:
            if approval["landfill_id"] != day["landfill_id"]:
                raise err("ERR_CROSS_SITE_REFERENCE",
                          "The approval belongs to another landfill.")
            if approval["profile_stream"] != waste_stream:
                raise err("ERR_CROSS_SITE_REFERENCE",
                          "The approval does not cover this waste stream.")
        if day["status"] != "OPEN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Loads are received only against an OPEN operating day.")
        lf = S.landfill_of_day(day)
        if lf["operating_status"] not in ("OPEN", "RESTRICTED_AIRSPACE"):
            raise err("ERR_SITE_NOT_ACCEPTING_WASTE",
                      "The site is not accepting waste.")
        if cell["status"] != "ACTIVE":
            raise err("ERR_CELL_NOT_ACCEPTING_WASTE",
                      "The working-face cell is not ACTIVE.")
        counted = len([l for l in S.loads_of_day(day["id"])
                       if l["screening_status"] != "REJECTED"]) + 1
        if counted > lf["daily_load_limit"]:
            raise err("ERR_DAILY_LOAD_LIMIT_EXCEEDED",
                      "The scale house has reached its daily load limit.")
        row = new_row("waste_load", {
            "operating_day_id": day["id"],
            "special_waste_approval_id": approval_id,
            "hauler_ref": hauler_ref,
            "waste_stream": waste_stream,
            "manifest_tons": manifest_tons,
            "load_check_result": load_check_result,
            "certified_net_tons": None,
            "screening_state_reason": None,
            "gate_charge_amount": None,
            "host_royalty_amount": None,
            "final_charge_amount": None,
            "screening_status": "PENDING",
            "billing_status": "UNBILLED",
        })
        return created(public(row))

    @endpoint(app, "/waste-loads/<waste_load_id>", ["GET"], ALL_ROLES)
    def read_load(user_id, role, waste_load_id):
        return obj_response(public(get_or_404("waste_load", waste_load_id)))

    @endpoint(app, "/waste-loads", ["GET"], ALL_ROLES)
    def list_loads(user_id, role):
        return paged(filtered(rows("waste_load"), {
            "operating_day_id": "operating_day_id",
            "special_waste_approval_id": "special_waste_approval_id",
            "screening_status": "screening_status",
            "billing_status": "billing_status",
        }))

    @endpoint(app, "/waste-loads/<waste_load_id>/clear-screening", ["POST"],
              ["ScaleOperator"])
    def clear_screening(user_id, role, waste_load_id):
        load = get_or_404("waste_load", waste_load_id)
        day = S.day_of(load["operating_day_id"])
        S.scope(user_id, day["landfill_id"])
        lf = S.landfill_of_day(day)
        cell = S.cell_of(day["active_cell_id"])
        approval_id = load.get("special_waste_approval_id")
        approval = None
        if approval_id:
            from core import table
            approval = table("special_waste_approval").get(approval_id)
        if load["screening_status"] not in ("PENDING", "FLAGGED"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a PENDING or FLAGGED load may be cleared.")
        if day["status"] != "OPEN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The operating day is no longer OPEN.")
        if lf["operating_status"] not in ("OPEN", "RESTRICTED_AIRSPACE"):
            raise err("ERR_SITE_NOT_ACCEPTING_WASTE",
                      "The site is not accepting waste.")
        if cell["status"] != "ACTIVE":
            raise err("ERR_CELL_NOT_ACCEPTING_WASTE",
                      "The working-face cell is not ACTIVE.")
        if load["load_check_result"] != "PASS":
            raise err("ERR_PROHIBITED_MATERIAL",
                      "The working-face load check did not pass.")
        if load["waste_stream"] in S.SPECIAL_STREAMS and (
                approval is None
                or approval["profile_stream"] != load["waste_stream"]):
            raise err("ERR_PROHIBITED_MATERIAL",
                      "Special waste requires a matching approved profile.")
        if approval is not None:
            now = clock()
            if approval["status"] != "APPROVED" \
                    or not approval["effective_from"] <= now \
                    or not approval["expires_on"] > now:
                raise err("ERR_APPROVAL_EXPIRED",
                          "The special-waste approval is not usable.")
        hca = S.live_host_agreement(lf["id"])
        if hca is None:
            raise err("ERR_NO_EXECUTED_HOST_AGREEMENT",
                      "No executed host community agreement prices this site.")
        if approval is not None:
            if D(approval["consumed_tons"]) + D(load["manifest_tons"]) \
                    > D(approval["approved_tons_cap"]):
                raise err("ERR_APPROVAL_TONNAGE_CAP_EXCEEDED",
                          "The approved tonnage cap would be exceeded.")
        load["screening_status"] = "CLEARED"
        load["billing_status"] = "PROVISIONAL"
        load["gate_charge_amount"] = S.gate_charge_amount(load["manifest_tons"], hca)
        touch(load)
        if approval is not None:
            S.sync_approval(approval)
            touch(approval)
        return obj_response(public(load))

    @endpoint(app, "/waste-loads/<waste_load_id>/flag", ["POST"], ["ScaleOperator"])
    def flag_load(user_id, role, waste_load_id):
        b = Body()
        reason = b.string("screening_state_reason")
        load = get_or_404("waste_load", waste_load_id)
        day = S.day_of(load["operating_day_id"])
        S.scope(user_id, day["landfill_id"])
        if load["screening_status"] != "PENDING":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a PENDING load may be flagged.")
        if day["status"] != "OPEN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The operating day is no longer OPEN.")
        load["screening_state_reason"] = reason
        load["screening_status"] = "FLAGGED"
        touch(load)
        return obj_response(public(load))

    @endpoint(app, "/waste-loads/<waste_load_id>/reject", ["POST"], ["ScaleOperator"])
    def reject_load(user_id, role, waste_load_id):
        b = Body()
        reason = b.string("screening_state_reason")
        load = get_or_404("waste_load", waste_load_id)
        day = S.day_of(load["operating_day_id"])
        S.scope(user_id, day["landfill_id"])
        if load["screening_status"] not in ("PENDING", "FLAGGED"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a PENDING or FLAGGED load may be turned away.")
        if day["status"] != "OPEN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The operating day is no longer OPEN.")
        load["screening_state_reason"] = reason
        load["screening_status"] = "REJECTED"
        load["billing_status"] = "VOID"
        load["gate_charge_amount"] = None
        touch(load)
        approval_id = load.get("special_waste_approval_id")
        if approval_id:
            from core import table
            approval = table("special_waste_approval").get(approval_id)
            if approval is not None and S.sync_approval(approval):
                touch(approval)
        return obj_response(public(load))

    @endpoint(app, "/waste-loads/<waste_load_id>/certify-weight", ["POST"],
              ["ScaleOperator"])
    def certify_weight(user_id, role, waste_load_id):
        b = Body()
        certified = b.number("certified_net_tons", gt=0)
        load = get_or_404("waste_load", waste_load_id)
        day = S.day_of(load["operating_day_id"])
        S.scope(user_id, day["landfill_id"])
        if load["screening_status"] != "CLEARED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A certified weight belongs to a cleared load.")
        load["certified_net_tons"] = certified
        touch(load)
        return obj_response(public(load))
