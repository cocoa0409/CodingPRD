"""Family endpoints, including the fee ledger."""
from flask import Blueprint

import db
from errors import raise_err
from middleware import route
from response import success_object, success_list
from serializers import ser_family, ser_student
from services import core
from services import fees as fees_svc
from validation import get_body, req_string, req_int

bp = Blueprint("families", __name__)


@bp.route("/families", methods=["POST"])
@route(["Parent"])
def create_family():
    body = get_body()
    display_name = req_string(body, "display_name")
    district_code = req_string(body, "district_code")
    rec = core.make_record({
        "display_name": display_name,
        "district_code": district_code,
        "fee_balance_cents": 0,
        "oldest_unpaid_charge_at": None,
        "fee_status": "CURRENT",
    })
    db.families[rec["id"]] = rec
    return success_object(ser_family(rec), status=201)


@bp.route("/families/<family_id>", methods=["GET"])
@route(["Parent", "Registrar", "AcademicDirector", "StateAuditor"],
       ownership=("family", "family_id"),
       parent_chain=(("family", "family_id", db.families),))
def get_family(family_id):
    fam = db.families[family_id]
    fees_svc.refresh_fee_status(fam)
    return success_object(ser_family(fam))


@bp.route("/families/<family_id>/students", methods=["GET"])
@route(["Parent", "Registrar", "AcademicDirector", "StateAuditor"],
       ownership=("family", "family_id"),
       parent_chain=(("family", "family_id", db.families),))
def list_family_students(family_id):
    recs = [s for s in db.students.values() if s["family_id"] == family_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_student(s) for s in page], limit, offset, total)


@bp.route("/families/<family_id>/ledger", methods=["GET"])
@route(["Parent", "Registrar", "AcademicDirector", "StateAuditor"],
       ownership=("family", "family_id"),
       parent_chain=(("family", "family_id", db.families),))
def get_family_ledger(family_id):
    fam = db.families[family_id]
    fees_svc.refresh_fee_status(fam)
    return success_object({
        "fee_balance_cents": fam["fee_balance_cents"],
        "fee_status": fam["fee_status"],
        "oldest_unpaid_charge_at": fam["oldest_unpaid_charge_at"],
    })


@bp.route("/families/<family_id>/ledger-payments", methods=["POST"])
@route(["Parent", "Registrar"],
       ownership=("family", "family_id"),
       parent_chain=(("family", "family_id", db.families),))
def create_ledger_payment(family_id):
    fam = db.families[family_id]
    body = get_body()
    amount = req_int(body, "amount_cents", lo=1)
    fees_svc.credit_family(fam, amount)
    return success_object(ser_family(fam), status=201)


@bp.route("/families/<family_id>/students", methods=["POST"])
@route(["Parent"],
       ownership=("family", "family_id"),
       parent_chain=(("family", "family_id", db.families),))
def create_student(family_id):
    body = get_body()
    full_name = req_string(body, "full_name")
    from validation import req_date
    date_of_birth = req_date(body, "date_of_birth")
    rec = core.make_record({
        "family_id": family_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "transcript_sealed": False,
        "sealed_at": None,
        "diploma_number": None,
    })
    db.students[rec["id"]] = rec
    return success_object(ser_student(rec), status=201)
