"""Routes: exemption applications and abatement agreements (PRD §3.7)."""

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_int, req_enum, lookup, stamp_new, touch,
    parse_date_field, append_audit,
)
from services import (
    revalidate_bill_cascade, flag_forecasts_force, EXEMPTION_TYPES,
)
from serializers import exemption_view, abatement_view

bp = Blueprint("incentives", __name__)

ALL_ROLES = ("FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/assets/<asset_id>/exemption-applications
    # ------------------------------------------------------------------
    @app.post("/bpp/assets/<asset_id>/exemption-applications")
    def create_exemption(asset_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        a = lookup(store.assets, asset_id, "Asset")
        body = get_body()
        etype = req_enum(body, "exemption_type", EXEMPTION_TYPES)
        pct = req_int(body, "exemption_pct", min_v=1, max_v=100)
        effective = parse_date_field(body, "effective_date")
        expiration = parse_date_field(body, "expiration_date")
        if not (effective < expiration):
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "effective_date must be strictly earlier than expiration_date")

        jurisdiction = store.jurisdictions[a["jurisdiction_id"]]
        # program availability (priority 14)
        if etype not in jurisdiction["offered_exemption_types"]:
            E.raise_err(E.ERR_EXEMPTION_PROGRAM_UNAVAILABLE,
                        "The asset's jurisdiction does not offer this exemption type")
        # period overlap (priority 23) — half-open intervals
        for e in store.exemptions.values():
            if (
                e["asset_id"] == asset_id
                and e["exemption_type"] == etype
                and e["application_status"] in ("SUBMITTED", "APPROVED", "SUSPENDED")
            ):
                # half-open intersection: eff1 < exp2 and eff2 < exp1
                if e["effective_date"] < expiration and effective < e["expiration_date"]:
                    E.raise_err(E.ERR_EXEMPTION_PERIOD_OVERLAP,
                                "Overlapping exemption period for this asset and type")
        # exemption cap (priority 28)
        if pct > jurisdiction["max_exemption_pct"]:
            E.raise_err(E.ERR_EXEMPTION_CAP_EXCEEDED,
                        "exemption_pct exceeds the jurisdiction maximum")

        app_obj = {
            "asset_id": asset_id,
            "exemption_type": etype,
            "exemption_pct": pct,
            "effective_date": effective,
            "expiration_date": expiration,
            "application_status": "DRAFT",
            "suspended_date": None,
        }
        stamp_new(store, app_obj)
        store.exemptions[app_obj["id"]] = app_obj
        return created(exemption_view(app_obj))

    # ------------------------------------------------------------------
    # GET /bpp/exemption-applications/<application_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/exemption-applications/<application_id>")
    def get_exemption(application_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        e = lookup(store.exemptions, application_id, "ExemptionApplication")
        return ok(exemption_view(e))

    # ------------------------------------------------------------------
    # GET /bpp/assets/<asset_id>/exemption-applications
    # ------------------------------------------------------------------
    @app.get("/bpp/assets/<asset_id>/exemption-applications")
    def list_exemptions(asset_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        lookup(store.assets, asset_id, "Asset")
        limit, offset = parse_pagination()
        items = [e for e in store.exemptions.values() if e["asset_id"] == asset_id]
        st = request.args.get("application_status")
        if st is not None:
            items = [e for e in items if e["application_status"] == st]
        et = request.args.get("exemption_type")
        if et is not None:
            items = [e for e in items if e["exemption_type"] == et]
        items.sort(key=lambda e: e["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([exemption_view(e) for e in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/exemption-applications/<application_id>/submit
    # ------------------------------------------------------------------
    @app.post("/bpp/exemption-applications/<application_id>/submit")
    def submit_exemption(application_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        e = lookup(store.exemptions, application_id, "ExemptionApplication")
        get_body()
        if e["application_status"] != "DRAFT":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Only a DRAFT application may be submitted")
        # cross-entity state gate: linked asset must not be DISPOSED
        asset = store.assets.get(e["asset_id"])
        if asset is not None and asset["lifecycle_status"] == "DISPOSED":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                        "Cannot submit an exemption application for a DISPOSED asset")
        e["application_status"] = "SUBMITTED"
        touch(e)
        return ok(exemption_view(e))

    # ------------------------------------------------------------------
    # POST /bpp/exemption-applications/<application_id>/review
    # ------------------------------------------------------------------
    @app.post("/bpp/exemption-applications/<application_id>/review")
    def review_exemption(application_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        e = lookup(store.exemptions, application_id, "ExemptionApplication")
        body = get_body()
        decision = req_enum(body, "decision", {"APPROVE", "DENY"})
        if e["application_status"] != "SUBMITTED":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Only a SUBMITTED application may be reviewed")
        e["application_status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
        touch(e)
        return ok(exemption_view(e))

    # ------------------------------------------------------------------
    # POST /bpp/exemption-applications/<application_id>/compliance
    # ------------------------------------------------------------------
    @app.post("/bpp/exemption-applications/<application_id>/compliance")
    def exemption_compliance(application_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        e = lookup(store.exemptions, application_id, "ExemptionApplication")
        body = get_body()
        action = req_enum(body, "action", {"SUSPEND", "REINSTATE"})
        asset = store.assets.get(e["asset_id"])
        if action == "SUSPEND":
            if e["application_status"] != "APPROVED":
                E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                            "SUSPEND requires application status APPROVED")
            e["application_status"] = "SUSPENDED"
            e["suspended_date"] = store.clock_date()
            touch(e)
            if asset is not None:
                append_audit(store, asset["client_id"], "EXEMPTION_SUSPENDED",
                             f"Exemption application {e['id']} suspended", caller.user_id)
        else:  # REINSTATE
            if e["application_status"] != "SUSPENDED":
                E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                            "REINSTATE requires application status SUSPENDED")
            e["application_status"] = "APPROVED"
            e["suspended_date"] = None
            touch(e)
        return ok(exemption_view(e))

    # ------------------------------------------------------------------
    # POST /bpp/assets/<asset_id>/abatements
    # ------------------------------------------------------------------
    @app.post("/bpp/assets/<asset_id>/abatements")
    def create_abatement(asset_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        a = lookup(store.assets, asset_id, "Asset")
        body = get_body()
        first_year = req_int(body, "first_tax_year")
        last_year = req_int(body, "last_tax_year")
        pct = req_int(body, "abatement_pct", min_v=1, max_v=100)
        if last_year < first_year:
            E.raise_err(E.ERR_INVALID_REQUEST, "last_tax_year must be >= first_tax_year")
        # overlap (priority 22) — closed intervals; sharing an endpoint counts
        for ag in store.abatements.values():
            if (
                ag["asset_id"] == asset_id
                and ag["agreement_status"] in ("ACTIVE", "RECERTIFICATION_DUE")
                and ag["first_tax_year"] <= last_year
                and first_year <= ag["last_tax_year"]
            ):
                E.raise_err(E.ERR_ABATEMENT_OVERLAP,
                            "Overlapping abatement coverage for this asset")
        ag = {
            "asset_id": asset_id,
            "first_tax_year": first_year,
            "last_tax_year": last_year,
            "abatement_pct": pct,
            "agreement_status": "ACTIVE",
            "last_recertified_year": first_year,
        }
        stamp_new(store, ag)
        store.abatements[ag["id"]] = ag
        return created(abatement_view(ag))

    # ------------------------------------------------------------------
    # GET /bpp/abatements/<agreement_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/abatements/<agreement_id>")
    def get_abatement(agreement_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        ag = lookup(store.abatements, agreement_id, "AbatementAgreement")
        return ok(abatement_view(ag))

    # ------------------------------------------------------------------
    # GET /bpp/assets/<asset_id>/abatements
    # ------------------------------------------------------------------
    @app.get("/bpp/assets/<asset_id>/abatements")
    def list_abatements(asset_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        lookup(store.assets, asset_id, "Asset")
        limit, offset = parse_pagination()
        items = [ag for ag in store.abatements.values() if ag["asset_id"] == asset_id]
        st = request.args.get("agreement_status")
        if st is not None:
            items = [ag for ag in items if ag["agreement_status"] == st]
        items.sort(key=lambda ag: ag["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([abatement_view(ag) for ag in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/abatements/<agreement_id>/recertify
    # ------------------------------------------------------------------
    @app.post("/bpp/abatements/<agreement_id>/recertify")
    def recertify_abatement(agreement_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        ag = lookup(store.abatements, agreement_id, "AbatementAgreement")
        body = get_body()
        tax_year = req_int(body, "tax_year")
        if ag["agreement_status"] != "RECERTIFICATION_DUE":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                        "Recertification requires status RECERTIFICATION_DUE")
        if tax_year != ag["last_recertified_year"] + 1:
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "tax_year must equal last_recertified_year + 1")
        ag["agreement_status"] = "ACTIVE"
        ag["last_recertified_year"] = tax_year
        touch(ag)
        return ok(abatement_view(ag))

    # ------------------------------------------------------------------
    # POST /bpp/abatements/<agreement_id>/terminate
    # ------------------------------------------------------------------
    @app.post("/bpp/abatements/<agreement_id>/terminate")
    def terminate_abatement(agreement_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        ag = lookup(store.abatements, agreement_id, "AbatementAgreement")
        get_body()
        if ag["agreement_status"] not in ("ACTIVE", "RECERTIFICATION_DUE"):
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                        "Only an ACTIVE or RECERTIFICATION_DUE agreement may be terminated")
        ag["agreement_status"] = "TERMINATED"
        touch(ag)

        asset = store.assets.get(ag["asset_id"])
        client_id = asset["client_id"] if asset is not None else None

        # Revalidate affected bills (clawback)
        covered_years = set(range(ag["first_tax_year"], ag["last_tax_year"] + 1))
        if asset is not None:
            for bill in list(store.bills.values()):
                if bill["validation_status"] not in ("MATCHED", "DISCREPANCY"):
                    continue
                notice = store.notices[bill["notice_id"]]
                rendition = store.renditions[notice["rendition_id"]]
                if (
                    rendition["client_id"] == asset["client_id"]
                    and rendition["jurisdiction_id"] == asset["jurisdiction_id"]
                    and rendition["tax_year"] in covered_years
                ):
                    revalidate_bill_cascade(store, bill, caller.user_id)

            # Flag published forecasts whose tax year is covered
            flag_forecasts_force(store, client_id, covered_years, caller.user_id)

            append_audit(store, client_id, "ABATEMENT_TERMINATED",
                         f"Abatement agreement {ag['id']} terminated", caller.user_id)
        return ok(abatement_view(ag))
