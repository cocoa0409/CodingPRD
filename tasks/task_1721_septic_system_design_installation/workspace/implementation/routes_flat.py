"""Flat alias read surface (SCAFFOLD.yaml §1.5, PRD §2.5): FK reverse
reachability and filtered lists. All endpoints are GET, all roles."""

import db
import helpers as H
import middleware as mw
import response as R

S = db.STORE
P = "/septic-ops"


def _flat_list(collection, filter_map):
    def view():
        rows = H.apply_filters(H.rows_of(collection), filter_map)
        return R.respond_list(rows)
    return view


def _flat_get(collection):
    def view(**kw):
        row_id = next(iter(kw.values()))
        rec = S[collection].get(row_id)
        if rec is None:
            import errors
            errors.not_found("Resource not found")
        return R.respond_object(rec)
    return view


def _flat_child_list(parent_collection, child_collection, fk_field):
    """GET /<parents>/{id}/<children> — parent must exist (404), then filter."""
    def view(**kw):
        row_id = next(iter(kw.values()))
        rec = S[parent_collection].get(row_id)
        if rec is None:
            import errors
            errors.not_found("Resource not found")
        return R.respond_list(H.children(child_collection, fk_field, rec["id"]))
    return view


def register(app):
    def add(path, endpoint, view):
        app.add_url_rule(path, endpoint, mw.auth()(view),
                         methods=["GET"], strict_slashes=False)

    # staff registries — filtered lists + get by id
    add(P + "/soil-scientists", "flat_scientists",
        _flat_list("soil_scientists", {"installer_company_id": "installer_company_id"}))
    add(P + "/system-designers", "flat_designers",
        _flat_list("system_designers", {"installer_company_id": "installer_company_id"}))
    add(P + "/inspectors", "flat_inspectors",
        _flat_list("inspectors", {"installer_company_id": "installer_company_id"}))
    add(P + "/health-officers", "flat_officers",
        _flat_list("health_officers", {"installer_company_id": "installer_company_id"}))
    add(P + "/project-managers", "flat_pms",
        _flat_list("project_managers", {"installer_company_id": "installer_company_id"}))

    add(P + "/customers", "flat_customers",
        _flat_list("customers", {"installer_company_id": "installer_company_id"}))
    add(P + "/customers/<cuid>", "flat_customer_get", _flat_get("customers"))

    add(P + "/sites", "flat_sites",
        _flat_list("sites", {"customer_id": "customer_id",
                             "installer_company_id": "installer_company_id",
                             "status": "status"}))
    add(P + "/sites/<sid>", "flat_site_get", _flat_get("sites"))

    add(P + "/soil-scientists/<ssid>", "flat_scientist_get",
        _flat_get("soil_scientists"))
    add(P + "/soil-scientists/<ssid>/soil-evaluations", "flat_scientist_evals",
        _flat_child_list("soil_scientists", "soil_evaluations", "evaluator_id"))
    add(P + "/soil-scientists/<ssid>/percolation-tests", "flat_scientist_percs",
        _flat_child_list("soil_scientists", "percolation_tests", "evaluator_id"))

    add(P + "/soil-evaluations", "flat_evals",
        _flat_list("soil_evaluations", {"site_id": "site_id",
                                        "evaluator_id": "evaluator_id",
                                        "superseded_by_id": "superseded_by_id",
                                        "status": "status"}))
    add(P + "/soil-evaluations/<eid>", "flat_eval_get", _flat_get("soil_evaluations"))

    add(P + "/percolation-tests", "flat_percs",
        _flat_list("percolation_tests", {"site_id": "site_id",
                                         "evaluator_id": "evaluator_id",
                                         "superseded_by_id": "superseded_by_id",
                                         "status": "status"}))
    add(P + "/percolation-tests/<ptid>", "flat_perc_get",
        _flat_get("percolation_tests"))

    add(P + "/system-designers/<dsid>", "flat_designer_get",
        _flat_get("system_designers"))
    add(P + "/system-designers/<dsid>/designs", "flat_designer_designs",
        _flat_child_list("system_designers", "designs", "designer_id"))

    add(P + "/designs", "flat_designs",
        _flat_list("designs", {"site_id": "site_id",
                               "designer_id": "designer_id",
                               "soil_evaluation_id": "soil_evaluation_id",
                               "percolation_test_id": "percolation_test_id",
                               "supersedes_design_id": "supersedes_design_id",
                               "status": "status"}))
    add(P + "/designs/<did>", "flat_design_get", _flat_get("designs"))
    add(P + "/designs/<did>/permits", "flat_design_permits",
        _flat_child_list("designs", "permits", "design_id"))
    add(P + "/designs/<did>/variance-requests", "flat_design_variances",
        _flat_child_list("designs", "variance_requests", "design_id"))
    add(P + "/designs/<did>/repair-cases", "flat_design_repairs",
        _flat_child_list("designs", "repair_cases", "replacement_design_id"))

    add(P + "/permits", "flat_permits",
        _flat_list("permits", {"site_id": "site_id",
                               "design_id": "design_id",
                               "status": "status"}))
    add(P + "/permits/<pid>", "flat_permit_get", _flat_get("permits"))
    add(P + "/permits/<pid>/installations", "flat_permit_installations",
        _flat_child_list("permits", "installations", "permit_id"))

    add(P + "/installations", "flat_installations",
        _flat_list("installations", {"site_id": "site_id",
                                     "permit_id": "permit_id",
                                     "status": "status"}))
    add(P + "/installations/<iid>", "flat_installation_get",
        _flat_get("installations"))
    add(P + "/installations/<iid>/maintenance-contracts",
        "flat_installation_contracts",
        _flat_child_list("installations", "maintenance_contracts",
                         "installation_id"))
    add(P + "/installations/<iid>/repair-cases", "flat_installation_repairs",
        _flat_child_list("installations", "repair_cases",
                         "failed_installation_id"))

    add(P + "/inspectors/<iid>", "flat_inspector_get", _flat_get("inspectors"))
    add(P + "/inspectors/<iid>/inspections", "flat_inspector_inspections",
        _flat_child_list("inspectors", "inspections", "inspector_id"))

    add(P + "/inspections", "flat_inspections",
        _flat_list("inspections", {"installation_id": "installation_id",
                                   "inspector_id": "inspector_id",
                                   "result": "result"}))
    add(P + "/inspections/<inspid>", "flat_inspection_get",
        _flat_get("inspections"))

    add(P + "/material-verifications", "flat_materials",
        _flat_list("material_verifications",
                   {"installation_id": "installation_id",
                    "verified": "verified",
                    "verified_by": "verified_by"}))
    add(P + "/material-verifications/<mvid>", "flat_material_get",
        _flat_get("material_verifications"))

    add(P + "/variance-requests", "flat_variances",
        _flat_list("variance_requests", {"site_id": "site_id",
                                         "design_id": "design_id",
                                         "decided_by": "decided_by",
                                         "status": "status"}))
    add(P + "/variance-requests/<vid>", "flat_variance_get",
        _flat_get("variance_requests"))

    add(P + "/health-officers/<hid>", "flat_officer_get",
        _flat_get("health_officers"))
    add(P + "/health-officers/<hid>/variance-requests",
        "flat_officer_variances",
        _flat_child_list("health_officers", "variance_requests", "decided_by"))

    add(P + "/maintenance-contracts", "flat_contracts",
        _flat_list("maintenance_contracts", {"site_id": "site_id",
                                             "customer_id": "customer_id",
                                             "installation_id": "installation_id",
                                             "status": "status"}))
    add(P + "/maintenance-contracts/<mcid>", "flat_contract_get",
        _flat_get("maintenance_contracts"))
    add(P + "/maintenance-contracts/<mcid>/visits", "flat_contract_visits",
        _flat_child_list("maintenance_contracts", "maintenance_visits",
                         "contract_id"))

    add(P + "/visits", "flat_visits",
        _flat_list("maintenance_visits", {"contract_id": "contract_id"}))
    add(P + "/visits/<vid>", "flat_visit_get", _flat_get("maintenance_visits"))

    add(P + "/repair-cases", "flat_repairs",
        _flat_list("repair_cases", {"site_id": "site_id",
                                    "failed_installation_id": "failed_installation_id",
                                    "replacement_design_id": "replacement_design_id",
                                    "status": "status"}))
    add(P + "/repair-cases/<rid>", "flat_repair_get", _flat_get("repair_cases"))

    add(P + "/project-managers/<pmid>", "flat_pm_get",
        _flat_get("project_managers"))
    add(P + "/project-managers/<pmid>/material-verifications",
        "flat_pm_materials",
        _flat_child_list("project_managers", "material_verifications",
                         "verified_by"))
