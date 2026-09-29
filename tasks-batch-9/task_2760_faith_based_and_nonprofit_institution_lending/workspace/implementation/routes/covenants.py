"""Covenant surveillance and the breach cycle (PRD section 3.8)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import COMMITTEE_MEMBER, CREDIT_ANALYST, LOAN_SERVICER, READ_ALL
from errors import ApiError

bp = Blueprint("covenants", __name__)

COVENANT_TYPES = ("DSCR_UNRESTRICTED_GIVING", "MEMBERSHIP_TREND",
                  "PLEDGE_COLLECTION_RATE")
TEST_FREQUENCIES = ("QUARTERLY", "ANNUAL")


@bp.route("/covenants", methods=["POST"])
def create_covenant():
    auth.authenticate((CREDIT_ANALYST,))
    b = shapes.body()
    loan = resolve.loan(b.get("loan_id"))
    if loan is None:
        shapes.req_id_field(b, "loan_id")
    covenant_type = shapes.req_enum(b, "covenant_type", COVENANT_TYPES)
    threshold = shapes.req_ratio(b, "threshold_ratio", gt=0)
    frequency = shapes.req_enum(b, "test_frequency", TEST_FREQUENCIES)
    # ladder 27
    if loan["servicing_status"] == "PAID_OFF":
        raise ApiError("ERR_LOAN_TERMINAL")

    row = store.base_record()
    row.update({
        "loan_id": loan["id"],
        "covenant_type": covenant_type,
        "threshold_ratio": threshold,
        "test_frequency": frequency,
        "status": "COMPLIANT",
        "last_test_as_of": None,
        "last_test_numerator_dollars": None,
        "last_test_denominator_dollars": None,
        "last_test_ratio": None,
        "last_test_result": None,
        "consecutive_fail_count": 0,
        "test_count": 0,
        "waiver_count": 0,
        "cure_evidence_note": None,
    })
    store.covenants[row["id"]] = row
    store.mark_created(row)
    calc.recompute_posture(loan)
    return envelope.created(serializers.covenant(row))


@bp.route("/covenants/<covenant_id>", methods=["GET"])
def get_covenant(covenant_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.covenant(covenant_id)
    auth.scope(ctx, auth.owner_of_covenant(row))
    return envelope.ok(serializers.covenant(row))


@bp.route("/covenants", methods=["GET"])
def list_covenants():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.covenants.values()),
                                {"loan_id": "loan_id",
                                 "covenant_type": "covenant_type",
                                 "status": "status"})
    return envelope.listing(envelope.sort_created_asc(rows),
                            serializers.covenant)


@bp.route("/covenants/<covenant_id>/tests", methods=["POST"])
def test_covenant(covenant_id):
    auth.authenticate((LOAN_SERVICER,))
    covenant = resolve.covenant(covenant_id)
    b = shapes.body()
    as_of_raw, as_of_dt = shapes.req_dt(b, "as_of_date")
    loan = store.loans[covenant["loan_id"]]
    # ladder 27
    if loan["servicing_status"] == "PAID_OFF":
        raise ApiError("ERR_LOAN_TERMINAL")

    application = store.loan_applications.get(loan["loan_application_id"])
    institution_id = application["institution_id"] if application else None
    basis = loan.get("giving_basis") or calc.BLENDED
    numerator = calc.net_available_dollars(institution_id, as_of_dt, basis)
    denominator = calc.cents_to_dollars(loan["annual_debt_service_cents"])
    if denominator == 0:
        ratio = Decimal("0.0000")
    else:
        ratio = calc.rhu(Decimal(numerator) / Decimal(denominator), 4)
    result = "PASS" if ratio >= covenant["threshold_ratio"] else "FAIL"

    covenant["last_test_as_of"] = as_of_raw
    covenant["last_test_numerator_dollars"] = numerator
    covenant["last_test_denominator_dollars"] = denominator
    covenant["last_test_ratio"] = ratio
    covenant["last_test_result"] = result
    covenant["test_count"] += 1

    status = covenant["status"]
    if status == "COMPLIANT":
        if result == "FAIL":
            covenant["status"] = "BREACH_PENDING_CURE"
            covenant["consecutive_fail_count"] = 1
        else:
            covenant["consecutive_fail_count"] = 0
    elif status == "BREACH_PENDING_CURE":
        if result == "PASS":
            covenant["status"] = "COMPLIANT"
            covenant["consecutive_fail_count"] = 0
        else:
            covenant["status"] = "BREACHED"
            covenant["consecutive_fail_count"] = 2
    elif status == "BREACHED":
        if result == "PASS":
            covenant["consecutive_fail_count"] = 0
        else:
            covenant["consecutive_fail_count"] += 1
    elif status == "WAIVED":
        if result == "PASS":
            covenant["status"] = "COMPLIANT"
            covenant["consecutive_fail_count"] = 0
        else:
            covenant["status"] = "BREACH_PENDING_CURE"
            covenant["consecutive_fail_count"] = 1
    store.touch(covenant)
    calc.recompute_posture(loan)
    return envelope.ok(serializers.covenant(covenant))


@bp.route("/covenants/<covenant_id>/cure", methods=["POST"])
def cure_covenant(covenant_id):
    auth.authenticate((LOAN_SERVICER,))
    covenant = resolve.covenant(covenant_id)
    b = shapes.body()
    note = shapes.req_str(b, "cure_evidence_note")
    # ladder 22
    if covenant["status"] not in ("BREACH_PENDING_CURE", "BREACHED"):
        raise ApiError("ERR_COVENANT_INVALID_STATE")
    if covenant.get("last_test_result") != "PASS":
        raise ApiError("ERR_COVENANT_INVALID_STATE")
    covenant["status"] = "COMPLIANT"
    covenant["consecutive_fail_count"] = 0
    covenant["cure_evidence_note"] = note
    store.touch(covenant)
    calc.recompute_posture(store.loans[covenant["loan_id"]])
    return envelope.ok(serializers.covenant(covenant))


@bp.route("/covenants/<covenant_id>/waive", methods=["POST"])
def waive_covenant(covenant_id):
    auth.authenticate((COMMITTEE_MEMBER,))
    covenant = resolve.covenant(covenant_id)
    b = shapes.body()
    note = shapes.req_str(b, "waiver_note")
    # ladder 22
    if covenant["status"] != "BREACHED":
        raise ApiError("ERR_COVENANT_INVALID_STATE")
    covenant["status"] = "WAIVED"
    covenant["waiver_count"] += 1
    covenant["waiver_note"] = note
    store.touch(covenant)
    calc.recompute_posture(store.loans[covenant["loan_id"]])
    return envelope.ok(serializers.covenant(covenant))
