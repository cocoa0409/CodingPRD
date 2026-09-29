"""The landfill-gas wellfield and quarterly surface-emission monitoring."""
from core import (Body, ALL_ROLES, D, clock, created, endpoint, err, filtered,
                  fk_or_404, get_or_404, new_row, obj_response, paged, public,
                  rows, table, touch)
import services as S


def _corrective_candidate(landfill_id):
    """Least recently attended ONLINE well; a never-tuned well sorts as though
    its last_tuned_at were its created_at. Ties break by created_at ascending.
    There is no random choice and no ordering by id."""
    pool = [w for w in S.wells_of_landfill(landfill_id) if w["status"] == "ONLINE"]
    if not pool:
        return None
    pool.sort(key=lambda w: (w["last_tuned_at"] or w["created_at"],
                             w["created_at"], w["_seq"]))
    return pool[0]


def register(app):
    # ---------------------------------------------------------- gas wells -----
    @endpoint(app, "/gas-wells", ["POST"], ["EnvironmentalManager"])
    def drill_well(user_id, role):
        b = Body()
        cell_id = b.fk("cell_id")
        well_code = b.string("well_code", minlen=1, maxlen=20)
        depth_ft = b.number("depth_ft", gt=0)
        cell = fk_or_404("cell", cell_id)
        for other in S.wells_of_landfill(cell["landfill_id"]):
            if other["well_code"] == well_code:
                raise err("ERR_DUPLICATE_WELL_CODE",
                          "That well code is already used on this site.")
        row = new_row("gas_well", {
            "cell_id": cell["id"],
            "well_code": well_code,
            "depth_ft": depth_ft,
            "last_vacuum_in_h2o": None,
            "last_methane_pct": None,
            "last_oxygen_pct": None,
            "last_tuned_at": None,
            "offline_reason": None,
            "status": "DRILLED",
        })
        return created(public(row))

    @endpoint(app, "/gas-wells/<gas_well_id>", ["GET"], ALL_ROLES)
    def read_well(user_id, role, gas_well_id):
        return obj_response(public(get_or_404("gas_well", gas_well_id)))

    @endpoint(app, "/gas-wells", ["GET"], ALL_ROLES)
    def list_wells(user_id, role):
        return paged(filtered(rows("gas_well"), {
            "cell_id": "cell_id",
            "status": "status",
        }))

    @endpoint(app, "/cells/<cell_id>/gas-wells", ["GET"], ALL_ROLES)
    def list_cell_wells(user_id, role, cell_id):
        get_or_404("cell", cell_id)
        pool = [w for w in rows("gas_well") if w["cell_id"] == cell_id]
        return paged(filtered(pool, {"status": "status"}))

    @endpoint(app, "/gas-wells/<gas_well_id>/connect", ["POST"],
              ["EnvironmentalManager"])
    def connect_well(user_id, role, gas_well_id):
        well = get_or_404("gas_well", gas_well_id)
        if well["status"] not in ("DRILLED", "OFFLINE"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a DRILLED or OFFLINE well may be connected.")
        cell = S.cell_of(well["cell_id"])
        if cell["status"] not in ("ACTIVE", "FULL", "CLOSED"):
            raise err("ERR_CELL_NOT_READY_FOR_WELLFIELD",
                      "The cell has no gas to collect yet.")
        well["status"] = "CONNECTED"
        touch(well)
        return obj_response(public(well))

    @endpoint(app, "/gas-wells/<gas_well_id>/tune", ["POST"],
              ["EnvironmentalManager"])
    def tune_well(user_id, role, gas_well_id):
        b = Body()
        vacuum = b.number("last_vacuum_in_h2o")
        methane = b.number("last_methane_pct")
        oxygen = b.number("last_oxygen_pct")
        well = get_or_404("gas_well", gas_well_id)
        if well["status"] not in ("CONNECTED", "TUNING_REQUIRED", "ONLINE"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "This well is not in the field-tuning cycle.")
        if D(oxygen) >= S.WELL_OXYGEN_CRITICAL_PCT:
            raise err("ERR_WELL_OXYGEN_CRITICAL",
                      "Air intrusion: valve the well out instead of tuning it.")
        in_spec = (D(methane) >= S.WELL_SPEC_METHANE_MIN
                   and D(oxygen) <= S.WELL_SPEC_OXYGEN_MAX
                   and D(vacuum) >= S.WELL_SPEC_VACUUM_MIN)
        well["last_vacuum_in_h2o"] = vacuum
        well["last_methane_pct"] = methane
        well["last_oxygen_pct"] = oxygen
        well["last_tuned_at"] = clock()
        well["status"] = "ONLINE" if in_spec else "TUNING_REQUIRED"
        touch(well)
        cell = S.cell_of(well["cell_id"])
        lf = S.landfill_of_cell(cell)
        if in_spec:
            if S.restore_gas_compliance(lf):
                touch(lf)
        else:
            lf["gas_collection_status"] = "CORRECTIVE_ACTION"
            touch(lf)
        return obj_response(public(well))

    @endpoint(app, "/gas-wells/<gas_well_id>/take-offline", ["POST"],
              ["EnvironmentalManager"])
    def take_well_offline(user_id, role, gas_well_id):
        b = Body()
        reason = b.string("offline_reason")
        well = get_or_404("gas_well", gas_well_id)
        if well["status"] not in ("CONNECTED", "TUNING_REQUIRED", "ONLINE"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a live well may be valved out.")
        well["offline_reason"] = reason
        well["status"] = "OFFLINE"
        touch(well)
        lf = S.landfill_of_cell(S.cell_of(well["cell_id"]))
        if S.restore_gas_compliance(lf):
            touch(lf)
        return obj_response(public(well))

    @endpoint(app, "/gas-wells/<gas_well_id>/abandon", ["POST"],
              ["EnvironmentalManager"])
    def abandon_well(user_id, role, gas_well_id):
        b = Body()
        reason = b.string("offline_reason")
        well = get_or_404("gas_well", gas_well_id)
        if well["status"] != "OFFLINE":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only an OFFLINE well may be abandoned.")
        well["offline_reason"] = reason
        well["status"] = "ABANDONED"
        touch(well)
        return obj_response(public(well))

    # ----------------------------------------------- surface-emission scans ---
    @endpoint(app, "/surface-emission-scans", ["POST"], ["EnvironmentalManager"])
    def record_scan(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        scanned_on = b.timestamp("scanned_on")
        grid_points_count = b.integer("grid_points_count", minimum=1)
        max_reading_ppm = b.number("max_reading_ppm", ge=0)
        exceedance = D(max_reading_ppm) >= S.SEM_EXCEEDANCE_PPM
        if exceedance:
            point_ref = b.string("exceedance_point_ref", minlen=1)
        else:
            b.forbid("exceedance_point_ref",
                     "must be omitted below the 500 ppm exceedance threshold.")
            point_ref = None
        lf = fk_or_404("landfill", landfill_id)
        row = new_row("surface_emission_scan", {
            "landfill_id": lf["id"],
            "corrective_well_id": None,
            "scanned_on": scanned_on,
            "grid_points_count": grid_points_count,
            "max_reading_ppm": max_reading_ppm,
            "exceedance_point_ref": point_ref,
            "remediation_note": None,
            "status": "EXCEEDANCE_OPEN" if exceedance else "PASSED",
        })
        if exceedance:
            # Link 2: one ONLINE well is deterministically nominated for re-tuning.
            candidate = _corrective_candidate(lf["id"])
            if candidate is not None:
                candidate["status"] = "TUNING_REQUIRED"
                touch(candidate)
                row["corrective_well_id"] = candidate["id"]
            # Link 3 fires even when the candidate pool was empty.
            lf["gas_collection_status"] = "CORRECTIVE_ACTION"
            touch(lf)
        return created(public(row))

    @endpoint(app, "/surface-emission-scans/<surface_emission_scan_id>", ["GET"],
              ALL_ROLES)
    def read_scan(user_id, role, surface_emission_scan_id):
        return obj_response(public(get_or_404("surface_emission_scan",
                                              surface_emission_scan_id)))

    @endpoint(app, "/surface-emission-scans", ["GET"], ALL_ROLES)
    def list_scans(user_id, role):
        return paged(filtered(rows("surface_emission_scan"), {
            "landfill_id": "landfill_id",
            "corrective_well_id": "corrective_well_id",
            "status": "status",
        }))

    @endpoint(app, "/surface-emission-scans/<surface_emission_scan_id>/resolve",
              ["POST"], ["EnvironmentalManager"])
    def resolve_scan(user_id, role, surface_emission_scan_id):
        b = Body()
        note = b.string("remediation_note")
        scan = get_or_404("surface_emission_scan", surface_emission_scan_id)
        if scan["status"] != "EXCEEDANCE_OPEN":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only an open exceedance may be resolved.")
        well_id = scan.get("corrective_well_id")
        if well_id:
            well = table("gas_well").get(well_id)
            if well is None or well["status"] != "ONLINE":
                raise err("ERR_INVALID_STATE_TRANSITION",
                          "The nominated corrective well is not back ONLINE.")
        scan["remediation_note"] = note
        scan["status"] = "RESOLVED"
        touch(scan)
        lf = S.landfill_of(scan["landfill_id"])
        if S.restore_gas_compliance(lf):
            touch(lf)
        return obj_response(public(scan))
