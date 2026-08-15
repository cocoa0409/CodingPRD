"""Soil evaluations and percolation tests (single-generational science)."""

from flask import g

import constants as C
import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
SCIENTIST = ("SoilScientist",)
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>"


def _create_soil_evaluation(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) body FK: evaluator must exist within this installer company
    evaluator = H.fk_company_staff("soil_scientists", cid, b.get("evaluator_id"))
    # (19) ranges
    soil_class = mw.req_enum(b, "soil_class", C.SOIL_CLASSES)
    limiting = mw.req_int(b, "limiting_layer_inches")
    if limiting < 1 or limiting > 240:
        errors.invalid_request("limiting_layer_inches must be between 1 and 240")
    rec = db.create_record("soil_evaluations", {
        "site_id": site["id"],
        "evaluator_id": evaluator["id"],
        "soil_class": soil_class,
        "limiting_layer_inches": limiting,
        "evaluation_date_period": site["current_period_index"],
        "superseded_by_id": None,
        "status": "RECORDED",
    })
    svc.supersede_science(site, "soil_evaluations", rec)
    return R.respond_object(rec, 201)


def _create_percolation_test(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    evaluator = H.fk_company_staff("soil_scientists", cid, b.get("evaluator_id"))
    mpi = mw.req_num(b, "minutes_per_inch")
    if mpi < 0.5 or mpi > 240.0:
        errors.invalid_request("minutes_per_inch must be between 0.5 and 240.0")
    pits = mw.req_int(b, "test_pit_count")
    if pits < 2 or pits > 12:
        errors.invalid_request("test_pit_count must be between 2 and 12")
    rec = db.create_record("percolation_tests", {
        "site_id": site["id"],
        "evaluator_id": evaluator["id"],
        "minutes_per_inch": mpi,
        "test_pit_count": pits,
        "test_date_period": site["current_period_index"],
        "superseded_by_id": None,
        "status": "RECORDED",
    })
    svc.supersede_science(site, "percolation_tests", rec)
    return R.respond_object(rec, 201)


def _list_science(collection):
    def view(cid, cuid, sid):
        site = H.resolve_site(cid, cuid, sid)
        rows = H.children(collection, "site_id", site["id"])
        rows = H.apply_filters(rows, {"status": "status"})
        return R.respond_list(rows)
    return view


def _get_science(collection, id_param):
    def view(cid, cuid, sid, **kw):
        site = H.resolve_site(cid, cuid, sid)
        return R.respond_object(H.resolve_science(collection, site, kw[id_param]))
    return view


def _void_science(collection, id_param, date_field):
    def view(cid, cuid, sid, **kw):
        site = H.resolve_site(cid, cuid, sid)
        rec = H.resolve_science(collection, site, kw[id_param])
        # (5) state
        if rec["status"] != "RECORDED":
            errors.invalid_state("Only a RECORDED record may be voided")
        # (11) segregation of duties: only the recording scientist may void
        if g.user_id != rec["evaluator_id"]:
            raise errors.ApiError(
                errors.ERR_SEGREGATION_OF_DUTIES, 403,
                "Only the recording soil scientist may void this record")
        # (26) refused while pinned by a live (SUBMITTED/APPROVED) design
        pin_field = ("soil_evaluation_id" if collection == "soil_evaluations"
                     else "percolation_test_id")
        for d in svc.designs_of_site(site["id"]):
            if d["status"] in ("SUBMITTED", "APPROVED") and d[pin_field] == rec["id"]:
                raise errors.ApiError(
                    errors.ERR_PINNED_BY_LIVE_DESIGN, 409,
                    "Record is pinned by a live design")
        db.set_fields(rec, status="VOIDED")
        return R.respond_object(rec)
    return view


def register(app):
    app.add_url_rule(BASE + "/soil-evaluations", "soil_eval_create",
                     mw.auth(*SCIENTIST)(_create_soil_evaluation),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/soil-evaluations", "soil_eval_list",
                     mw.auth()(_list_science("soil_evaluations")),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/soil-evaluations/<eid>", "soil_eval_get",
                     mw.auth()(_get_science("soil_evaluations", "eid")),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/soil-evaluations/<eid>/void", "soil_eval_void",
                     mw.auth(*SCIENTIST)(
                         _void_science("soil_evaluations", "eid",
                                       "evaluation_date_period")),
                     methods=["POST"], strict_slashes=False)

    app.add_url_rule(BASE + "/percolation-tests", "perc_create",
                     mw.auth(*SCIENTIST)(_create_percolation_test),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/percolation-tests", "perc_list",
                     mw.auth()(_list_science("percolation_tests")),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/percolation-tests/<ptid>", "perc_get",
                     mw.auth()(_get_science("percolation_tests", "ptid")),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/percolation-tests/<ptid>/void", "perc_void",
                     mw.auth(*SCIENTIST)(
                         _void_science("percolation_tests", "ptid",
                                       "test_date_period")),
                     methods=["POST"], strict_slashes=False)
