"""Logical clock, landfills and cells."""
from core import (Body, ALL_ROLES, D, canon_iso, clock, created, endpoint, err,
                  filtered, get_or_404, fk_or_404, iso_ms, new_row, obj_response,
                  paged, parse_iso, public, rows, store, touch)
import services as S


def register(app):
    # ------------------------------------------------------- logical clock ----
    @endpoint(app, "/_clock/set_current_utc", ["POST"], ["PlatformAdmin"])
    def set_clock(user_id, role):
        b = Body()
        current = b.timestamp("current_utc")
        store.clock = current
        return obj_response({"current_utc": store.clock})

    # ----------------------------------------------------------- landfills ----
    @endpoint(app, "/landfills", ["POST"], ["PlatformAdmin"])
    def create_landfill(user_id, role):
        b = Body()
        name = b.string("name", minlen=1, maxlen=120)
        permit_number = b.string("permit_number", minlen=1, maxlen=40)
        airspace = b.number("permitted_total_airspace_cy", gt=0)
        footprint = b.number("design_footprint_sf", gt=0)
        density = b.number("planned_density_tons_per_cy", gt=0, ge="0.40", le="1.20")
        forecast = b.number("annual_tonnage_forecast", gt=0)
        load_limit = b.integer("daily_load_limit", required=False, minimum=1,
                               maximum=2000, default=200)
        for other in rows("landfill"):
            if other["permit_number"] == permit_number:
                raise err("ERR_DUPLICATE_PERMIT_NUMBER",
                          "permit_number is already registered.")
        row = new_row("landfill", {
            "name": name,
            "permit_number": permit_number,
            "permitted_total_airspace_cy": airspace,
            "design_footprint_sf": footprint,
            "planned_density_tons_per_cy": density,
            "annual_tonnage_forecast": forecast,
            "daily_load_limit": load_limit,
            "assurance_funded_amount": 0.0,
            "certified_airspace_cy": 0.0,
            "consumed_airspace_cy": 0.0,
            "remaining_airspace_cy": 0.0,
            "remaining_life_years": 0.0,
            "active_cell_count": 0,
            "operating_status": "OPEN",
            "gas_collection_status": "COMPLIANT",
            "financial_assurance_status": "UNFUNDED",
        })
        return created(public(row))

    @endpoint(app, "/landfills/<landfill_id>", ["GET"], ALL_ROLES)
    def read_landfill(user_id, role, landfill_id):
        return obj_response(public(get_or_404("landfill", landfill_id)))

    @endpoint(app, "/landfills", ["GET"], ALL_ROLES)
    def list_landfills(user_id, role):
        return paged(filtered(rows("landfill"), {
            "permit_number": "permit_number",
            "operating_status": "operating_status",
            "financial_assurance_status": "financial_assurance_status",
        }))

    @endpoint(app, "/landfills/<landfill_id>/operating-status", ["POST"],
              ["PlatformAdmin"])
    def move_operating_status(user_id, role, landfill_id):
        b = Body()
        target = b.enum("operating_status", S.OPERATING_STATUSES)
        lf = get_or_404("landfill", landfill_id)
        current = lf["operating_status"]
        if target == "OPEN":
            if current not in ("OPEN", "RESTRICTED_AIRSPACE",
                               "SUSPENDED_NO_AIRSPACE", "SUSPENDED_FINANCIAL"):
                raise err("ERR_INVALID_STATE_TRANSITION",
                          "The site cannot be returned to OPEN from %s." % current)
            if current == "SUSPENDED_FINANCIAL" \
                    and lf["financial_assurance_status"] != "FUNDED":
                raise err("ERR_FINANCIAL_ASSURANCE_SHORTFALL",
                          "Assurance must read FUNDED before reopening.")
            if current == "SUSPENDED_NO_AIRSPACE" and lf["active_cell_count"] <= 0:
                raise err("ERR_INVALID_STATE_TRANSITION",
                          "No cell is carrying a working face.")
            lf["operating_status"] = "OPEN"
            touch(lf)
            S.restore_suspended_approvals(lf)
        elif target == "CLOSED":
            if current == "CLOSED":
                raise err("ERR_INVALID_STATE_TRANSITION", "The site is already CLOSED.")
            for c in S.cells_of(lf["id"]):
                if c["status"] not in ("CLOSED", "REJECTED", "DESIGN"):
                    raise err("ERR_INVALID_STATE_TRANSITION",
                              "Cell %s is still in flight." % c["cell_code"])
            lf["operating_status"] = "CLOSED"
            touch(lf)
        else:
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "No administrative move targets %s." % target)
        return obj_response(public(lf))

    @endpoint(app, "/landfills/<landfill_id>/remaining-life-projection", ["GET"],
              ["PlatformAdmin", "SiteOperator", "SurveyorOfRecord",
               "EnvironmentalManager", "RegulatoryAgency", "FinanceOfficer"])
    def read_projection(user_id, role, landfill_id):
        lf = get_or_404("landfill", landfill_id)
        return obj_response(S.remaining_life_projection(lf))

    @endpoint(app, "/landfills/<landfill_id>/cells", ["GET"], ALL_ROLES)
    def list_landfill_cells(user_id, role, landfill_id):
        lf = get_or_404("landfill", landfill_id)
        return paged(filtered(S.cells_of(lf["id"]), {"status": "status"}))

    # --------------------------------------------------------------- cells ----
    @endpoint(app, "/cells", ["POST"], ["SiteOperator"])
    def create_cell(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        cell_code = b.string("cell_code", minlen=1, maxlen=20)
        design_airspace_cy = b.number("design_airspace_cy", gt=0)
        design_area_sf = b.number("design_area_sf", gt=0)
        liner_type = b.enum("liner_type", S.LINER_TYPES)
        start = b.timestamp("construction_start_date")
        end = b.timestamp("construction_end_date")
        piggyback = b.fk("piggyback_over_cell_id", required=False)
        if start > end:
            raise err("ERR_INVALID_REQUEST",
                      "construction_end_date must be at or after "
                      "construction_start_date.")
        lf = fk_or_404("landfill", landfill_id)
        parent = fk_or_404("cell", piggyback) if piggyback is not None else None
        S.scope(user_id, lf["id"])
        if parent is not None and parent["landfill_id"] != lf["id"]:
            raise err("ERR_CROSS_SITE_REFERENCE",
                      "piggyback_over_cell_id names a cell of another landfill.")
        for other in S.cells_of(lf["id"]):
            if other["cell_code"] == cell_code:
                raise err("ERR_DUPLICATE_CELL_CODE",
                          "cell_code is already used at this site.")
        if parent is not None and parent["status"] != "CLOSED":
            raise err("ERR_PIGGYBACK_PARENT_NOT_CLOSED",
                      "A cell may only be built over ground whose cover is complete.")
        row = new_row("cell", {
            "landfill_id": lf["id"],
            "piggyback_over_cell_id": piggyback,
            "cell_code": cell_code,
            "design_airspace_cy": design_airspace_cy,
            "design_area_sf": design_area_sf,
            "liner_type": liner_type,
            "construction_start_date": start,
            "construction_end_date": end,
            "consumed_airspace_cy": 0.0,
            "fill_pct": 0.0,
            "authorized_by_agency_user_id": None,
            "final_cover_reference": None,
            "status": "DESIGN",
        })
        return created(public(row))

    @endpoint(app, "/cells/<cell_id>", ["GET"], ALL_ROLES)
    def read_cell(user_id, role, cell_id):
        return obj_response(public(get_or_404("cell", cell_id)))

    @endpoint(app, "/cells", ["GET"], ALL_ROLES)
    def list_cells(user_id, role):
        return paged(filtered(rows("cell"), {
            "landfill_id": "landfill_id",
            "piggyback_over_cell_id": "piggyback_over_cell_id",
            "status": "status",
        }))

    @endpoint(app, "/cells/<cell_id>/begin-construction", ["POST"], ["SiteOperator"])
    def begin_construction(user_id, role, cell_id):
        cell = get_or_404("cell", cell_id)
        S.scope(user_id, cell["landfill_id"])
        lf = S.landfill_of_cell(cell)
        if cell["status"] != "DESIGN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Construction may only start from DESIGN.")
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A CLOSED site accepts no new cell construction.")
        if cell["piggyback_over_cell_id"] is not None:
            parent = S.cell_of(cell["piggyback_over_cell_id"])
            if parent["status"] != "CLOSED":
                raise err("ERR_PIGGYBACK_PARENT_NOT_CLOSED",
                          "The piggyback parent is no longer CLOSED.")
        cell["status"] = "UNDER_CONSTRUCTION"
        touch(cell)
        return obj_response(public(cell))

    @endpoint(app, "/cells/<cell_id>/authorize-waste-placement", ["POST"],
              ["RegulatoryAgency"])
    def authorize_cell(user_id, role, cell_id):
        b = Body()
        approval_reference = b.string("approval_reference")
        cell = get_or_404("cell", cell_id)
        lf = S.landfill_of_cell(cell)
        if cell["status"] != "QA_CERTIFIED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Authorization requires a QA_CERTIFIED cell.")
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION", "The site is CLOSED.")
        if lf["gas_collection_status"] == "CORRECTIVE_ACTION":
            raise err("ERR_GAS_CORRECTIVE_ACTION_OPEN",
                      "Landfill-gas corrective action is open at this site.")
        if lf["financial_assurance_status"] != "FUNDED":
            raise err("ERR_FINANCIAL_ASSURANCE_SHORTFALL",
                      "Closure assurance must read FUNDED.")
        cell["authorized_by_agency_user_id"] = user_id
        cell["status"] = "READY_FOR_WASTE"
        touch(cell)
        return obj_response(public(cell))

    @endpoint(app, "/cells/<cell_id>/activate", ["POST"], ["SiteOperator"])
    def activate_cell(user_id, role, cell_id):
        cell = get_or_404("cell", cell_id)
        S.scope(user_id, cell["landfill_id"])
        lf = S.landfill_of_cell(cell)
        if cell["status"] != "READY_FOR_WASTE":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The working face opens only from READY_FOR_WASTE.")
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION", "The site is CLOSED.")
        if lf["gas_collection_status"] == "CORRECTIVE_ACTION":
            raise err("ERR_GAS_CORRECTIVE_ACTION_OPEN",
                      "Landfill-gas corrective action is open at this site.")
        cell["status"] = "ACTIVE"
        touch(cell)
        S.sync_landfill(lf)
        S.lift_no_airspace_suspension(lf)
        touch(lf)
        return obj_response(public(cell))

    @endpoint(app, "/cells/<cell_id>/close", ["POST"], ["SiteOperator"])
    def close_cell(user_id, role, cell_id):
        b = Body()
        final_cover_reference = b.string("final_cover_reference")
        cell = get_or_404("cell", cell_id)
        S.scope(user_id, cell["landfill_id"])
        lf = S.landfill_of_cell(cell)
        if cell["status"] != "FULL":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Final cover is placed only on a FULL cell.")
        for w in S.wells_of_cell(cell["id"]):
            if w["status"] in ("DRILLED", "CONNECTED", "TUNING_REQUIRED"):
                raise err("ERR_CELL_HAS_UNFINISHED_WELLS",
                          "The gas collection system in this cell is unfinished.")
        cell["final_cover_reference"] = final_cover_reference
        cell["status"] = "CLOSED"
        touch(cell)
        S.sync_landfill(lf)
        touch(lf)
        return obj_response(public(cell))
