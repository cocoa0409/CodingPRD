"""Publication to the public registry, the registry hold and its compensation."""
from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import endpoint, get_body, v_int, v_str
from response import object_response
from store import base_row, by_created, db, iso, now, public, touch

bp = Blueprint("registry", __name__)


@bp.route("/cbb/registry-listings", methods=["POST"])
@endpoint("RegistryOperator", "PlatformAdmin")
def publish_listing(user_id, role):
    body = get_body()
    unit_id = v_str(body, "unit_id", min_len=1)
    registry_code = v_str(body, "registry_code", min_len=1, max_len=20)
    hla_a = v_str(body, "hla_a", min_len=1, max_len=20)
    hla_b = v_str(body, "hla_b", min_len=1, max_len=20)
    hla_drb1 = v_str(body, "hla_drb1", min_len=1, max_len=20)
    expected = v_int(body, "expected_unit_version", ge=0)
    unit = svc.get_unit(unit_id)

    # rung 8 -- optimistic concurrency on the unit
    if expected != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION")
    # rung 9 -- the unit's two axes
    if unit["processing_status"] != "CRYOPRESERVED":
        fail("ERR_INVALID_UNIT_STATE")
    if unit["availability_status"] != "UNAVAILABLE":
        fail("ERR_INVALID_UNIT_STATE")
    # rung 11 -- consent currency, widened by the HLA-typing permission
    enrollment = svc.unit_enrollment(unit)
    if enrollment is None or enrollment["consent_status"] != "CONSENTED" \
            or not enrollment["hla_typing_consent"]:
        fail("ERR_CONSENT_NOT_CURRENT")
    # rung 13 / 14 -- the maternal panel
    panel = svc.governing_panel(enrollment["id"])
    if panel is None or not svc.has_current_completed_screening(enrollment["id"]):
        fail("ERR_MATERNAL_SCREENING_INCOMPLETE")
    if panel["overall_result"] == "REACTIVE":
        fail("ERR_MATERNAL_SCREENING_REACTIVE")
    # rung 15 -- sterility on the acceptance test
    test = svc.post_processing_test(unit_id)
    if test is not None and test["sterility_result"] != "NEGATIVE":
        fail("ERR_STERILITY_POSITIVE")
    # rung 18 -- eligibility
    if unit["eligibility_status"] != "ELIGIBLE":
        fail("ERR_UNIT_NOT_ELIGIBLE")
    # rung 20 -- the public listing floor (all four boundaries inclusive)
    tnc = unit.get("post_processing_tnc_millions")
    cd34 = unit.get("post_processing_cd34_thousands")
    viability = unit.get("post_processing_viability_pct")
    score = unit.get("quality_acceptance_score")
    if tnc is None or cd34 is None or viability is None or score is None \
            or int(tnc) < calc.PUBLIC_LISTING_MIN_TNC_MILLIONS \
            or int(cd34) < calc.PUBLIC_LISTING_MIN_CD34_THOUSANDS \
            or calc.D(viability) < calc.PUBLIC_LISTING_MIN_VIABILITY_PCT \
            or calc.D(score) < calc.PUBLIC_ACCEPT_SCORE_MIN:
        fail("ERR_QUALITY_BELOW_PUBLIC_THRESHOLD")
    # rung 21 -- custody model
    if unit["program_type"] != "PUBLIC_DONATION":
        fail("ERR_PROGRAM_TYPE_MISMATCH")
    # rung 23 -- one live listing per unit
    for listing in svc.unit_listings(unit_id):
        if listing["listing_status"] in ("ACTIVE", "SUSPENDED"):
            fail("ERR_DUPLICATE_ACTIVE_LISTING")
    # rung 33 -- account standing
    account = svc.unit_account(unit)
    if account is not None and account["status"] in svc.DELINQUENT_ACCOUNT_STATES:
        fail("ERR_ACCOUNT_DELINQUENT")

    row = base_row()
    row.update({
        "unit_id": unit_id,
        "registry_code": registry_code,
        "hla_a": hla_a,
        "hla_b": hla_b,
        "hla_drb1": hla_drb1,
        "listed_at": iso(now()),
        "potency_grade": calc.potency_grade(tnc, cd34),
        "listing_status": "ACTIVE",
        "suspension_reason_code": None,
    })
    db.listings[row["id"]] = row
    unit["availability_status"] = "LISTED"
    touch(unit)
    return object_response(public(row), 201)


@bp.route("/cbb/registry-listings/<lid>/suspend", methods=["POST"])
@endpoint("RegistryOperator", "PlatformAdmin")
def suspend_listing(user_id, role, lid):
    body = get_body()
    v_str(body, "suspension_note", required=False, min_len=0, max_len=500)
    listing = svc.get_listing(lid)

    if listing["listing_status"] != "ACTIVE":
        fail("ERR_INVALID_LISTING_STATE")

    listing["listing_status"] = "SUSPENDED"
    listing["suspension_reason_code"] = "REGISTRY_HOLD"
    touch(listing)

    unit = db.units.get(listing["unit_id"])
    if unit is not None:
        if unit["availability_status"] == "LISTED":
            unit["availability_status"] = "UNAVAILABLE"
        touch(unit)
        for reservation in by_created(svc.unit_reservations(unit["id"])):
            if reservation["status"] == "PENDING_CONFIRMATORY":
                reservation["status"] = "CANCELLED"
                reservation["cancellation_reason_code"] = "LISTING_SUSPENDED"
                touch(reservation)
    return object_response(public(listing))


@bp.route("/cbb/registry-listings/<lid>/resume", methods=["POST"])
@endpoint("RegistryOperator", "PlatformAdmin")
def resume_listing(user_id, role, lid):
    get_body()
    listing = svc.get_listing(lid)

    if listing["listing_status"] != "SUSPENDED" \
            or listing["suspension_reason_code"] != "REGISTRY_HOLD":
        fail("ERR_INVALID_LISTING_STATE")
    unit = db.units.get(listing["unit_id"])
    if unit is None or unit["eligibility_status"] != "ELIGIBLE":
        fail("ERR_UNIT_NOT_ELIGIBLE")

    listing["listing_status"] = "ACTIVE"
    listing["suspension_reason_code"] = None
    touch(listing)
    if unit["availability_status"] == "UNAVAILABLE":
        unit["availability_status"] = "LISTED"
    touch(unit)
    return object_response(public(listing))
