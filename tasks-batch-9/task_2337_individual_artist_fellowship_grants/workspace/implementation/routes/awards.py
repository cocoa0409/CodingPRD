"""RecommendationSlot, Award and PaymentInstallment endpoints."""

from flask import Blueprint

import constants as C
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from routes import support as sup
from services import calc, cascade, derive

bp = Blueprint("awards", __name__)

PO = (mw.PROGRAM_OFFICER,)
ARTIST_ONLY = (mw.ARTIST,)
BOARD_ONLY = (mw.BOARD,)
FISCAL_ONLY = (mw.FISCAL,)
ALL = sup.ALL_ROLES
NO_PANELIST = sup.NO_PANELIST
TAX_ROLES = (mw.PROGRAM_OFFICER, mw.ARTIST, mw.FISCAL)


def _own_award(award, user_id, role):
    if role == mw.ARTIST and award["artist_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def _midnight_iso(moment):
    return db.iso3(moment.replace(hour=0, minute=0, second=0, microsecond=0))


# ================================================== recommendation slots


@bp.get("/grants/recommendation-slots/<recommendation_slot_id>")
def read_slot(recommendation_slot_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("slots", recommendation_slot_id)))


@bp.get("/grants/recommendation-slots")
def list_slots():
    mw.authorize(ALL)
    rows = db.rows("slots")
    rows.sort(key=lambda r: (int(r["rank"]), r["_seq"]))
    rows = sup.eq(rows, "panel_id", v.query_str("panel_id"))
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "cycle_id", v.query_str("cycle_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    return sup.listed(rows)


@bp.post("/grants/recommendation-slots/<recommendation_slot_id>/board-action")
def board_action(recommendation_slot_id):
    user_id, _ = mw.authorize(BOARD_ONLY)
    data = v.body()
    action = v.req_enum(data, "action", C.BOARD_ACTIONS)
    expected_version = v.req_int(data, "expected_cycle_version", minimum=0)
    struck_reason = v.opt_enum(data, "struck_reason_code", C.STRUCK_REASONS)
    if action == "STRIKE" and struck_reason is None:
        v.bad("struck_reason_code is required for a STRIKE.")

    slot = sup.resolve("slots", recommendation_slot_id)
    cycle = db.get("cycles", slot["cycle_id"])
    application = db.get("applications", slot["application_id"])

    # P60 optimistic concurrency, before any state, posture or fiscal outcome.
    if expected_version != int(cycle["version"]):
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    if slot["status"] != "PROPOSED":
        raise ApiError("ERR_SLOT_STATE_INVALID")
    if cycle["status"] != "BOARD_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    if action == "STRIKE":
        derive.set_fields(
            slot,
            status="BOARD_STRUCK",
            struck_reason_code=struck_reason,
            board_action_by=user_id,
        )
        if application is not None:
            derive.set_fields(
                application, status="NOT_RECOMMENDED", notified_at=cascade.now_iso()
            )
            derive.refresh_discipline_by_id(application["discipline_category_id"])
        db.mark(cycle)  # either accepted action moves the cycle version by one
        derive.refresh_cycle(cycle)
        return response.obj(db.public(slot))

    # --- APPROVE ---
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_POSTURE_FROZEN")
    if cycle["posture"] == "RESTRICTED":
        raise ApiError("ERR_CYCLE_POSTURE_RESTRICTED")
    if application is None or application["status"] != "SCORED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    artist = db.get("artists", application["artist_id"])
    last_end = db.dt_of(artist, "last_award_period_end") if artist else None
    if last_end is not None:
        earliest = db.plus_days(last_end, C.AWARD_COOLING_DAYS)
        if db.dt_of(cycle, "grant_period_start") < earliest:
            raise ApiError("ERR_AWARD_PERIOD_COOLING_VIOLATION")

    for other in db.rows("slots", lambda r, p=slot["panel_id"]: r["panel_id"] == p):
        if int(other["rank"]) < int(slot["rank"]) and other["status"] not in (
            C.SLOT_DISPOSED_STATUSES
        ):
            raise ApiError("ERR_SLOT_RANK_ORDER_VIOLATION")

    discipline = db.get("disciplines", application["discipline_category_id"])
    amount, is_prorated = calc.waterfall_allocation(
        cycle, discipline, discipline["committed_cents"]
    )
    if amount is None:
        raise ApiError("ERR_DISCIPLINE_ALLOCATION_EXHAUSTED")

    derive.set_fields(
        slot,
        status="BOARD_APPROVED",
        awarded_amount_cents=amount,
        board_action_by=user_id,
    )
    derive.set_fields(
        application, status="RECOMMENDED", notified_at=cascade.now_iso()
    )
    cascade.create_award(slot, cycle, application, amount, is_prorated, user_id)
    derive.refresh_artist(artist)
    derive.refresh_discipline(discipline)
    db.mark(cycle)
    derive.refresh_cycle(cycle)
    return response.obj(db.public(slot))


# ================================================================ awards


@bp.get("/grants/awards/<award_id>")
def read_award(award_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("awards", award_id)))


@bp.get("/grants/awards")
def list_awards():
    mw.authorize(ALL)
    rows = db.rows("awards")
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "artist_id", v.query_str("artist_id"))
    rows = sup.eq(rows, "cycle_id", v.query_str("cycle_id"))
    rows = sup.eq(rows, "recommendation_slot_id", v.query_str("recommendation_slot_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "payment_status", v.query_str("payment_status"))
    rows = sup.eq(rows, "reporting_status", v.query_str("reporting_status"))
    return sup.listed(rows)


@bp.post("/grants/awards/<award_id>/accept")
def accept_award(award_id):
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    data = v.body()
    version = v.req_str(data, "accept_agreement_version")
    signed = v.req_bool(data, "tax_certification_signed")
    if version != C.AGREEMENT_VERSION:
        v.bad("accept_agreement_version must be %s." % C.AGREEMENT_VERSION)

    award = sup.resolve("awards", award_id)
    _own_award(award, user_id, role)

    # P64 deliberately outranks the P65 state check.
    deadline = db.dt_of(award, "acceptance_deadline_at")
    if deadline is not None and db.now() > deadline:
        raise ApiError("ERR_ACCEPTANCE_DEADLINE_PASSED")
    if award["status"] != "OFFERED":
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if not signed:
        raise ApiError("ERR_TAX_CERTIFICATION_REQUIRED")

    cycle = db.get("cycles", award["cycle_id"])
    artist = db.get("artists", award["artist_id"])
    application = db.get("applications", award["application_id"])

    due_at = db.plus_days(
        db.dt_of(award, "grant_period_end"),
        int(cycle["final_report_due_offset_days"]),
    )
    derive.set_fields(
        award,
        status="ACCEPTED",
        accept_agreement_version=version,
        tax_certification_signed=True,
        final_report_due_at=db.iso3(due_at),
    )

    schedule = calc.payment_schedule(
        award["gross_amount_cents"],
        artist["tin_status"] if artist else "MISSING",
        db.date_of(award, "grant_period_start"),
    )
    for line in schedule:
        db.insert(
            "installments",
            {
                "award_id": award["id"],
                "replaces_installment_id": None,
                "installment_number": line["installment_number"],
                "scheduled_date": db.iso3(db.parse_dt(line["scheduled_date"].isoformat())),
                "gross_cents": line["gross_cents"],
                "withholding_rate": line["withholding_rate"],
                "withholding_cents": line["withholding_cents"],
                "net_cents": line["net_cents"],
                "status": "SCHEDULED",
                "released_by": None,
                "released_at": None,
                "paid_at": None,
                "reversal_reason_code": None,
                "hold_reason_code": None,
            },
        )
    derive.refresh_award_ledger(award)
    if application is not None and application["status"] == "RECOMMENDED":
        derive.set_fields(application, status="AWARDED")
    return response.obj(db.public(award))


@bp.post("/grants/awards/<award_id>/decline")
def decline_award(award_id):
    user_id, role = mw.authorize(ARTIST_ONLY, entity_backed=True)
    award = sup.resolve("awards", award_id)
    _own_award(award, user_id, role)
    if award["status"] != "OFFERED":
        raise ApiError("ERR_AWARD_STATE_INVALID")
    cascade.unwind_award(award, "DECLINED")
    return response.obj(db.public(award))


@bp.post("/grants/awards/<award_id>/rescind")
def rescind_award(award_id):
    mw.authorize(PO)
    data = v.body()
    reason = v.req_enum(data, "rescind_reason_code", C.RESCIND_REASONS)
    award = sup.resolve("awards", award_id)
    if award["status"] not in ("OFFERED", "ACCEPTED"):
        raise ApiError("ERR_AWARD_STATE_INVALID")
    for installment in derive.installments_of_award(award["id"]):
        if installment["status"] in ("RELEASED", "PAID"):
            raise ApiError("ERR_AWARD_HAS_DISBURSEMENTS")
    cascade.unwind_award(award, "RESCINDED", reason)
    derive.set_fields(award, scheduled_withholding_cents=0, undisbursed_gross_cents=0)
    return response.obj(db.public(award))


@bp.get("/grants/awards/<award_id>/tax-report")
def tax_report(award_id):
    mw.authorize(TAX_ROLES)
    tax_year = v.query_int("tax_year", db.now().year, minimum=1)
    basis = v.query_enum("basis", C.TAX_BASES) or "ACCRUAL"
    award = sup.resolve("awards", award_id)
    installments = sorted(
        derive.installments_of_award(award["id"]),
        key=lambda r: (int(r["installment_number"]), r["_seq"]),
    )
    totals = calc.tax_reportable(installments, tax_year, basis)
    return response.obj(
        {
            "award_id": award["id"],
            "tax_year": tax_year,
            "basis": basis,
            "reportable_gross_cents": totals["gross_cents"],
            "reportable_withholding_cents": totals["withholding_cents"],
            "reportable_net_cents": totals["net_cents"],
            "installment_count": totals["installment_count"],
        }
    )


# ========================================================== installments


@bp.get("/grants/payment-installments/<payment_installment_id>")
def read_installment(payment_installment_id):
    mw.authorize(NO_PANELIST)
    return response.obj(db.public(sup.resolve("installments", payment_installment_id)))


@bp.get("/grants/payment-installments")
def list_installments():
    mw.authorize(NO_PANELIST)
    rows = db.rows("installments")
    rows.sort(key=lambda r: (int(r["installment_number"]), r["_seq"]))
    rows = sup.eq(rows, "award_id", v.query_str("award_id"))
    rows = sup.eq(
        rows, "replaces_installment_id", v.query_str("replaces_installment_id")
    )
    rows = sup.eq(rows, "status", v.query_str("status"))
    return sup.listed(rows)


@bp.post("/grants/payment-installments/<payment_installment_id>/release")
def release_installment(payment_installment_id):
    user_id, _ = mw.authorize(FISCAL_ONLY)
    installment = sup.resolve("installments", payment_installment_id)
    award = db.get("awards", installment["award_id"])
    cycle = db.get("cycles", award["cycle_id"]) if award else None

    # P55 segregation of duties.
    if award is not None and user_id == award["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if installment["status"] != "SCHEDULED":
        raise ApiError("ERR_INSTALLMENT_STATE_INVALID")

    if cycle is None or cycle["status"] != "AWARDED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_POSTURE_FROZEN")
    if award["status"] not in ("ACCEPTED", "ACTIVE"):
        raise ApiError("ERR_AWARD_STATE_INVALID")

    moment = db.now()
    if moment < db.dt_of(installment, "scheduled_date"):
        raise ApiError("ERR_INSTALLMENT_NOT_DUE")
    for other in derive.installments_of_award(award["id"]):
        if int(other["installment_number"]) < int(installment["installment_number"]):
            if other["status"] in ("SCHEDULED", "HELD"):
                raise ApiError("ERR_INSTALLMENT_NOT_DUE")

    derive.set_fields(
        installment,
        status="RELEASED",
        released_by=user_id,
        released_at=db.iso3(moment),
    )
    derive.refresh_award_ledger(award)
    return response.obj(db.public(installment))


@bp.post("/grants/payment-installments/<payment_installment_id>/pay")
def pay_installment(payment_installment_id):
    mw.authorize(FISCAL_ONLY)
    installment = sup.resolve("installments", payment_installment_id)
    award = db.get("awards", installment["award_id"])
    cycle = db.get("cycles", award["cycle_id"]) if award else None

    if installment["status"] != "RELEASED":
        raise ApiError("ERR_INSTALLMENT_STATE_INVALID")
    if cycle is not None and cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_POSTURE_FROZEN")
    if award["status"] not in ("ACCEPTED", "ACTIVE"):
        raise ApiError("ERR_AWARD_STATE_INVALID")

    derive.set_fields(installment, status="PAID", paid_at=db.iso3(db.now()))
    if award["status"] == "ACCEPTED":
        derive.set_fields(award, status="ACTIVE")
    derive.refresh_award_ledger(award)
    return response.obj(db.public(installment))


@bp.post("/grants/payment-installments/<payment_installment_id>/reverse")
def reverse_installment(payment_installment_id):
    mw.authorize(FISCAL_ONLY)
    data = v.body()
    reason = v.req_enum(data, "reversal_reason_code", C.REVERSAL_REASONS)
    installment = sup.resolve("installments", payment_installment_id)
    award = db.get("awards", installment["award_id"])

    if installment["status"] != "PAID":
        raise ApiError("ERR_INSTALLMENT_STATE_INVALID")
    if award["status"] not in ("ACCEPTED", "ACTIVE"):
        raise ApiError("ERR_AWARD_STATE_INVALID")

    # paid_at is retained so the cash-basis tax year does not move.
    derive.set_fields(installment, status="REVERSED", reversal_reason_code=reason)
    db.insert(
        "installments",
        {
            "award_id": award["id"],
            "replaces_installment_id": installment["id"],
            "installment_number": installment["installment_number"],
            "scheduled_date": _midnight_iso(db.now()),
            "gross_cents": installment["gross_cents"],
            "withholding_rate": installment["withholding_rate"],
            "withholding_cents": installment["withholding_cents"],
            "net_cents": installment["net_cents"],
            "status": "SCHEDULED",
            "released_by": None,
            "released_at": None,
            "paid_at": None,
            "reversal_reason_code": None,
            "hold_reason_code": None,
        },
    )
    derive.refresh_award_ledger(award)
    return response.obj(db.public(installment))
