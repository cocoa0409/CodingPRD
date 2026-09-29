"""All 30 read endpoints (single fetches, reverse-reachability lists, filtered
lists, the ranked unit search and the release pre-flight summary)."""
from flask import Blueprint, request

import calc
import services as svc
from middleware import endpoint, pagination, q_enum, q_num
from response import array_response, object_response, paginate
from store import by_created, db, public, public_list

bp = Blueprint("reads", __name__)

ALL = ("IntakeCoordinator", "ParentGuardian", "CollectionSite",
       "ProcessingTechnologist", "MedicalDirector", "RegistryOperator",
       "TransplantCenter", "BillingAdministrator", "FacilitiesEngineer",
       "PlatformAdmin")


def _page(rows, limit, offset):
    window, total = paginate(rows, limit, offset)
    return array_response(public_list(window), limit, offset, total)


# ------------------------------------------------------------- single fetches
@bp.route("/cbb/enrollments/<eid>", methods=["GET"])
@endpoint("IntakeCoordinator", "ParentGuardian", "MedicalDirector",
          "BillingAdministrator", "PlatformAdmin")
def get_enrollment(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    return object_response(public(svc.get_enrollment(eid)))


@bp.route("/cbb/storage-accounts/<aid>", methods=["GET"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def get_account(user_id, role, aid):
    svc.require_pg_account(user_id, role, aid)
    return object_response(public(svc.get_account(aid)))


@bp.route("/cbb/collection-kits/<kid>", methods=["GET"])
@endpoint("IntakeCoordinator", "CollectionSite", "ParentGuardian", "PlatformAdmin")
def get_kit(user_id, role, kid):
    return object_response(public(svc.get_kit(kid)))


@bp.route("/cbb/collections/<cid>", methods=["GET"])
@endpoint("CollectionSite", "ProcessingTechnologist", "MedicalDirector",
          "PlatformAdmin")
def get_collection(user_id, role, cid):
    return object_response(public(svc.get_collection(cid)))


@bp.route("/cbb/units/<uid>", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "RegistryOperator",
          "TransplantCenter", "BillingAdministrator", "PlatformAdmin")
def get_unit(user_id, role, uid):
    return object_response(public(svc.get_unit(uid)))


@bp.route("/cbb/processing-runs/<rid>", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "PlatformAdmin")
def get_run(user_id, role, rid):
    return object_response(public(svc.get_run(rid)))


@bp.route("/cbb/quality-tests/<tid>", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "TransplantCenter",
          "PlatformAdmin")
def get_test(user_id, role, tid):
    return object_response(public(svc.get_test(tid)))


@bp.route("/cbb/maternal-screenings/<sid>", methods=["GET"])
@endpoint("MedicalDirector", "IntakeCoordinator", "ParentGuardian", "PlatformAdmin")
def get_screening(user_id, role, sid):
    return object_response(public(svc.get_screening(sid)))


@bp.route("/cbb/storage-tanks/<tid>", methods=["GET"])
@endpoint("FacilitiesEngineer", "ProcessingTechnologist", "MedicalDirector",
          "PlatformAdmin")
def get_tank(user_id, role, tid):
    return object_response(public(svc.get_tank(tid)))


@bp.route("/cbb/temperature-excursions/<xid>", methods=["GET"])
@endpoint("FacilitiesEngineer", "MedicalDirector", "PlatformAdmin")
def get_excursion(user_id, role, xid):
    return object_response(public(svc.get_excursion(xid)))


@bp.route("/cbb/registry-listings/<lid>", methods=["GET"])
@endpoint("RegistryOperator", "MedicalDirector", "TransplantCenter", "PlatformAdmin")
def get_listing(user_id, role, lid):
    return object_response(public(svc.get_listing(lid)))


@bp.route("/cbb/storage-invoices/<iid>", methods=["GET"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def get_invoice(user_id, role, iid):
    return object_response(public(svc.get_invoice(iid)))


@bp.route("/cbb/reservations/<rid>", methods=["GET"])
@endpoint("TransplantCenter", "MedicalDirector", "RegistryOperator", "PlatformAdmin")
def get_reservation(user_id, role, rid):
    svc.require_tc_reservation(user_id, role, rid)
    return object_response(public(svc.get_reservation(rid)))


# ------------------------------------------------- reverse-reachability lists
@bp.route("/cbb/enrollments/<eid>/storage-accounts", methods=["GET"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def list_enrollment_accounts(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    svc.get_enrollment(eid)
    limit, offset = pagination()
    rows = by_created([a for a in db.accounts.values() if a["enrollment_id"] == eid])
    return _page(rows, limit, offset)


@bp.route("/cbb/enrollments/<eid>/collection-kits", methods=["GET"])
@endpoint("IntakeCoordinator", "CollectionSite", "ParentGuardian", "PlatformAdmin")
def list_enrollment_kits(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    svc.get_enrollment(eid)
    limit, offset = pagination()
    return _page(svc.enrollment_kits(eid), limit, offset)


@bp.route("/cbb/enrollments/<eid>/maternal-screenings", methods=["GET"])
@endpoint("MedicalDirector", "IntakeCoordinator", "ParentGuardian", "PlatformAdmin")
def list_enrollment_screenings(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    svc.get_enrollment(eid)
    limit, offset = pagination()
    return _page(svc.enrollment_screenings(eid), limit, offset)


@bp.route("/cbb/collection-kits/<kid>/collections", methods=["GET"])
@endpoint("CollectionSite", "ProcessingTechnologist", "PlatformAdmin")
def list_kit_collections(user_id, role, kid):
    svc.get_kit(kid)
    limit, offset = pagination()
    return _page(svc.kit_collections(kid), limit, offset)


@bp.route("/cbb/collections/<cid>/units", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "PlatformAdmin")
def list_collection_units(user_id, role, cid):
    svc.get_collection(cid)
    limit, offset = pagination()
    rows = by_created([u for u in db.units.values() if u["collection_id"] == cid])
    return _page(rows, limit, offset)


@bp.route("/cbb/storage-tanks/<tid>/units", methods=["GET"])
@endpoint("FacilitiesEngineer", "ProcessingTechnologist", "MedicalDirector",
          "PlatformAdmin")
def list_tank_units(user_id, role, tid):
    svc.get_tank(tid)
    limit, offset = pagination()
    return _page(svc.tank_units(tid), limit, offset)


@bp.route("/cbb/storage-accounts/<aid>/units", methods=["GET"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def list_account_units(user_id, role, aid):
    svc.get_account(aid)
    limit, offset = pagination()
    return _page(svc.account_units(aid), limit, offset)


@bp.route("/cbb/storage-tanks/<tid>/temperature-excursions", methods=["GET"])
@endpoint("FacilitiesEngineer", "MedicalDirector", "PlatformAdmin")
def list_tank_excursions(user_id, role, tid):
    svc.get_tank(tid)
    limit, offset = pagination()
    return _page(svc.tank_excursions(tid), limit, offset)


@bp.route("/cbb/units/<uid>/processing-runs", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "PlatformAdmin")
def list_unit_runs(user_id, role, uid):
    svc.get_unit(uid)
    limit, offset = pagination()
    return _page(svc.unit_runs(uid), limit, offset)


@bp.route("/cbb/units/<uid>/quality-tests", methods=["GET"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "TransplantCenter",
          "PlatformAdmin")
def list_unit_tests(user_id, role, uid):
    svc.get_unit(uid)
    limit, offset = pagination()
    return _page(svc.unit_tests(uid), limit, offset)


@bp.route("/cbb/units/<uid>/registry-listings", methods=["GET"])
@endpoint("RegistryOperator", "MedicalDirector", "PlatformAdmin")
def list_unit_listings(user_id, role, uid):
    svc.get_unit(uid)
    limit, offset = pagination()
    return _page(svc.unit_listings(uid), limit, offset)


@bp.route("/cbb/storage-accounts/<aid>/storage-invoices", methods=["GET"])
@endpoint("BillingAdministrator", "ParentGuardian", "PlatformAdmin")
def list_account_invoices(user_id, role, aid):
    svc.require_pg_account(user_id, role, aid)
    svc.get_account(aid)
    limit, offset = pagination()
    return _page(svc.account_invoices(aid), limit, offset)


# ----------------------------------------------------------- filtered lists
@bp.route("/cbb/enrollments", methods=["GET"])
@endpoint("IntakeCoordinator", "MedicalDirector", "BillingAdministrator",
          "PlatformAdmin")
def list_enrollments(user_id, role):
    limit, offset = pagination()
    lifecycle = q_enum("lifecycle_status",
                       ("CONSENT_PENDING", "ACTIVE", "KIT_DISPATCHED", "COLLECTED",
                        "CLOSED", "WITHDRAWN"))
    consent = q_enum("consent_status",
                     ("PENDING", "CONSENTED", "AMENDMENT_PENDING", "REVOKED"))
    program = q_enum("program_type", ("PRIVATE_FAMILY", "PUBLIC_DONATION"))
    site = request.args.get("collection_site_code")
    rows = by_created(list(db.enrollments.values()))
    if lifecycle:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle]
    if consent:
        rows = [r for r in rows if r["consent_status"] == consent]
    if program:
        rows = [r for r in rows if r["program_type"] == program]
    if site:
        rows = [r for r in rows if r["collection_site_code"] == site]
    return _page(rows, limit, offset)


@bp.route("/cbb/reservations", methods=["GET"])
@endpoint("TransplantCenter", "MedicalDirector", "RegistryOperator", "PlatformAdmin")
def list_reservations(user_id, role):
    limit, offset = pagination()
    status = q_enum("status", ("PENDING_CONFIRMATORY", "CONFIRMED", "DECLINED",
                               "RELEASED", "CANCELLED", "EXPIRED"))
    unit_id = request.args.get("unit_id")
    superseded = request.args.get("superseded_by_reservation_id")
    test_id = request.args.get("confirmatory_test_id")
    rows = by_created(list(db.reservations.values()))
    if unit_id:
        rows = [r for r in rows if r["unit_id"] == unit_id]
    if superseded:
        rows = [r for r in rows if r["superseded_by_reservation_id"] == superseded]
    if test_id:
        rows = [r for r in rows if r["confirmatory_test_id"] == test_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return _page(rows, limit, offset)


@bp.route("/cbb/storage-tanks", methods=["GET"])
@endpoint("FacilitiesEngineer", "ProcessingTechnologist", "MedicalDirector",
          "PlatformAdmin")
def list_tanks(user_id, role):
    limit, offset = pagination()
    status = q_enum("status", ("ONLINE", "ALARM", "MAINTENANCE", "OFFLINE"))
    tank_class = q_enum("tank_class", ("STANDARD", "PREMIUM"))
    rows = by_created(list(db.tanks.values()))
    if status:
        rows = [r for r in rows if r["status"] == status]
    if tank_class:
        rows = [r for r in rows if r["tank_class"] == tank_class]
    return _page(rows, limit, offset)


# ------------------------------------------------------------- computed reads
@bp.route("/cbb/units/search", methods=["GET"])
@endpoint("TransplantCenter", "RegistryOperator", "MedicalDirector", "PlatformAdmin")
def search_units(user_id, role):
    limit, offset = pagination()
    scope = q_enum("program_scope", ("PUBLIC", "PRIVATE_DIRECTED"), required=True)
    weight = q_num("patient_weight_kg", required=True, gt=0)
    q_num("required_hla_match_count", ge=0, le=6)
    min_dose = q_num("min_dose_x1e7_per_kg", ge=0)

    ranked = []
    for unit in db.units.values():
        if unit["eligibility_status"] != "ELIGIBLE":
            continue
        if unit["processing_status"] != "CRYOPRESERVED":
            continue
        tank = db.tanks.get(unit.get("tank_id"))
        if tank is None or tank["status"] != "ONLINE":
            continue
        listings = svc.unit_listings(unit["id"])
        if scope == "PUBLIC":
            if unit["availability_status"] != "LISTED":
                continue
            active = [l for l in listings if l["listing_status"] == "ACTIVE"]
            if not active:
                continue
        else:
            if unit["availability_status"] != "PRIVATE_STORED":
                continue
            active = [l for l in listings if l["listing_status"] == "ACTIVE"]
        if unit.get("post_processing_tnc_millions") is None:
            continue
        dose = calc.pre_cryo_dose(unit["post_processing_tnc_millions"], weight)
        if min_dose is not None and dose < min_dose:
            continue
        grade = None
        if active:
            grade = active[-1]["potency_grade"]
        elif listings:
            grade = listings[-1]["potency_grade"]
        ranked.append((dose, unit, grade, tank))

    ranked.sort(key=lambda t: (-t[0], -int(t[1]["post_processing_cd34_thousands"]),
                               t[1]["created_at"], t[1]["_seq"]))
    rows = [{
        "unit_id": unit["id"],
        "unit_registry_code": unit["unit_registry_code"],
        "program_type": unit["program_type"],
        "potency_grade": grade,
        "post_processing_tnc_millions": unit["post_processing_tnc_millions"],
        "post_processing_cd34_thousands": unit["post_processing_cd34_thousands"],
        "post_processing_viability_pct": unit["post_processing_viability_pct"],
        "pre_cryo_dose_x1e7_per_kg": calc.num(dose),
        "tank_code": tank["tank_code"],
    } for dose, unit, grade, tank in ranked]
    window, total = paginate(rows, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/cbb/reservations/<rid>/release-summary", methods=["GET"])
@endpoint("TransplantCenter", "MedicalDirector", "PlatformAdmin")
def release_summary(user_id, role, rid):
    svc.require_tc_reservation(user_id, role, rid)
    reservation = svc.get_reservation(rid)
    return object_response(svc.release_summary(reservation, user_id))
