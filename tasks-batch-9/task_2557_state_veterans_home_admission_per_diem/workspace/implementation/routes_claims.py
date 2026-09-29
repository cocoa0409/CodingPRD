"""Census day reads, per diem claim assembly, submission and adjudication."""
from flask import Blueprint

import calc
import services
from calc import (
    BED_HOLD_PAYABLE_DAYS_PER_MONTH,
    BED_HOLD_RATE_BPS,
    PER_DIEM_RATE_CENTS,
    apply_bps,
    census_out,
    claim_out,
)
from common import (
    f_enum,
    f_id,
    f_int,
    f_month,
    f_str,
    fail,
    guard,
    json_body,
    object_response,
    pagination,
    paginate,
    present,
    q_bool,
    q_date,
    q_month,
    q_str,
)
from store import clock_month, new_record, now_iso, order_key, store, touch_once

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = ("StateProgramAdmin", "BusinessOfficeManager", "FederalPerDiemAuditor")
BASES = ("AUDITED_BASIS", "CENSUS_BASIS")
REJECTION_CODES = ("CENSUS_MISMATCH", "RECOGNITION_LAPSE", "DUPLICATE_PERIOD")


def find_day(day_id):
    day = store.census_days.get(day_id)
    if day is None:
        fail("ERR_CENSUS_DAY_NOT_FOUND", "No census day with id %s." % day_id)
    return day


def find_claim(claim_id):
    claim = store.claims.get(claim_id)
    if claim is None:
        fail("ERR_CLAIM_NOT_FOUND", "No per diem claim with id %s." % claim_id)
    return claim


def quote(claim, days):
    """Price an attributable set without mutating the claim."""
    unit = store.care_units.get(claim["care_unit_id"])
    rate = PER_DIEM_RATE_CENTS[unit["care_level"]]
    resident_days = sum(1 for d in days if d["census_class"] == "RESIDENT_DAY")
    bed_hold_days = sum(1 for d in days if d["census_class"] == "BED_HOLD_DAY")
    if claim["basis"] == "AUDITED_BASIS":
        per_day = apply_bps(rate, BED_HOLD_RATE_BPS)
        payable = min(bed_hold_days, BED_HOLD_PAYABLE_DAYS_PER_MONTH)
        billable = resident_days + payable
        amount = rate * resident_days + per_day * payable
    else:
        billable = resident_days + bed_hold_days
        amount = rate * billable
    return {
        "resident_day_count": resident_days,
        "bed_hold_day_count": bed_hold_days,
        "billable_day_count": billable,
        "claim_amount_cents": amount,
        "census_reported_resident_count": len(set(d["resident_id"] for d in days)),
    }


# ------------------------------------------------------------------ reads ----
@bp.get("/census-days/<day_id>")
def get_day(day_id):
    guard(*CLAIM_READ_ROLES)
    return object_response(census_out(find_day(day_id)))


@bp.get("/census-days")
def list_days():
    guard(*CLAIM_READ_ROLES)
    limit, offset = pagination()
    resident_id = q_str("resident_id")
    care_unit_id = q_str("care_unit_id")
    per_diem_claim_id = q_str("per_diem_claim_id")
    date_from = q_date("service_date_from")
    date_to = q_date("service_date_to")
    census_class = q_str("census_class")
    claimed = q_bool("claimed")
    rows = list(store.census_days.values())
    if resident_id is not None:
        rows = [d for d in rows if d["resident_id"] == resident_id]
    if care_unit_id is not None:
        rows = [d for d in rows if d["care_unit_id"] == care_unit_id]
    if per_diem_claim_id is not None:
        rows = [d for d in rows if d["per_diem_claim_id"] == per_diem_claim_id]
    if date_from is not None:
        rows = [d for d in rows if d["service_date"] >= date_from]
    if date_to is not None:
        rows = [d for d in rows if d["service_date"] <= date_to]
    if census_class is not None:
        rows = [d for d in rows if d["census_class"] == census_class]
    if claimed is not None:
        rows = [d for d in rows if calc.census_day_claimed(d) == claimed]
    rows = sorted(rows, key=lambda d: (d["service_date"], d["created_at"], d["_seq"]))
    return paginate(rows, limit, offset, census_out)


@bp.get("/per-diem-claims/<claim_id>")
def get_claim(claim_id):
    guard(*CLAIM_READ_ROLES)
    return object_response(claim_out(find_claim(claim_id)))


@bp.get("/per-diem-claims")
def list_claims():
    guard(*CLAIM_READ_ROLES)
    limit, offset = pagination()
    veterans_home_id = q_str("veterans_home_id")
    care_unit_id = q_str("care_unit_id")
    corrects_claim_id = q_str("corrects_claim_id")
    claim_month = q_month("claim_month")
    status = q_str("status")
    basis = q_str("basis")
    rows = list(store.claims.values())
    if veterans_home_id is not None:
        rows = [c for c in rows if c["veterans_home_id"] == veterans_home_id]
    if care_unit_id is not None:
        rows = [c for c in rows if c["care_unit_id"] == care_unit_id]
    if corrects_claim_id is not None:
        rows = [c for c in rows if c["corrects_claim_id"] == corrects_claim_id]
    if claim_month is not None:
        rows = [c for c in rows if c["claim_month"] == claim_month]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if basis is not None:
        rows = [c for c in rows if c["basis"] == basis]
    rows = sorted(
        rows,
        key=lambda c: (
            c["claim_month"],
            c["correction_generation"],
            c["created_at"],
            c["_seq"],
        ),
    )
    return paginate(rows, limit, offset, claim_out)


# ----------------------------------------------------------------- writes ----
@bp.post("/per-diem-claims")
def open_claim():
    guard("BusinessOfficeManager")
    body = json_body()
    veterans_home_id = f_id(body, "veterans_home_id")
    care_unit_id = f_id(body, "care_unit_id")
    claim_month = f_month(body, "claim_month")
    basis = f_enum(body, "basis", BASES, required=False, default="AUDITED_BASIS")

    home = store.homes.get(veterans_home_id)
    if home is None:
        fail("ERR_HOME_NOT_FOUND", "No veterans home with id %s." % veterans_home_id)
    unit = store.care_units.get(care_unit_id)
    if unit is None:
        fail("ERR_CARE_UNIT_NOT_FOUND", "No care unit with id %s." % care_unit_id)

    for other in store.claims.values():
        if (
            other["care_unit_id"] == unit["id"]
            and other["claim_month"] == claim_month
            and other["status"] in ("DRAFT", "SUBMITTED")
        ):
            fail(
                "ERR_CLAIM_PERIOD_OVERLAP",
                "Another DRAFT or SUBMITTED claim already occupies this unit-month.",
            )
    if services.has_consumed_day(unit["id"], claim_month):
        fail(
            "ERR_CENSUS_DAY_ALREADY_CLAIMED",
            "This unit-month holds census days already billed by a live claim.",
        )

    claim = new_record()
    claim.update(
        {
            "veterans_home_id": home["id"],
            "care_unit_id": unit["id"],
            "corrects_claim_id": None,
            "claim_month": claim_month,
            "basis": basis,
            "status": "DRAFT",
            "resident_day_count": 0,
            "bed_hold_day_count": 0,
            "billable_day_count": 0,
            "claim_amount_cents": 0,
            "census_reported_resident_count": 0,
            "recognition_verified": False,
            "correction_generation": 0,
            "submitted_at": None,
            "adjudicated_at": None,
            "paid_amount_cents": None,
            "rejection_code": None,
            "adjudication_note": None,
        }
    )
    store.claims[claim["id"]] = claim
    services.attribute_and_price(claim)
    touch_once(home)
    touch_once(unit)
    return object_response(claim_out(claim), 201)


@bp.post("/per-diem-claims/<claim_id>/correct")
def correct_claim(claim_id):
    guard("BusinessOfficeManager")
    body = json_body()
    expected_version = f_int(body, "expected_claim_version", minimum=0)
    echo_month = f_month(body, "claim_month", required=False)
    basis = f_enum(body, "basis", BASES, required=False)
    correction_note = f_str(body, "correction_note", required=False)

    target = find_claim(claim_id)
    if expected_version != target["version"]:
        fail("ERR_CLAIM_VERSION_STALE", "expected_claim_version does not match the target claim.")
    if target["status"] not in ("PAID", "REJECTED"):
        fail("ERR_CLAIM_STATE_INVALID", "Only a PAID or REJECTED claim may be corrected.")
    if present(body, "claim_month") and echo_month != target["claim_month"]:
        fail("ERR_CLAIM_MONTH_MISMATCH", "The claim_month echo does not match the target's month.")
    if services.has_consumed_day(
        target["care_unit_id"], target["claim_month"], None, target["id"]
    ):
        fail(
            "ERR_CENSUS_DAY_ALREADY_CLAIMED",
            "This unit-month holds census days billed by another live claim.",
        )

    home = store.homes.get(target["veterans_home_id"])
    unit = store.care_units.get(target["care_unit_id"])
    claim = new_record()
    claim.update(
        {
            "veterans_home_id": target["veterans_home_id"],
            "care_unit_id": target["care_unit_id"],
            "corrects_claim_id": target["id"],
            "claim_month": target["claim_month"],
            "basis": basis or target["basis"],
            "status": "DRAFT",
            "resident_day_count": 0,
            "bed_hold_day_count": 0,
            "billable_day_count": 0,
            "claim_amount_cents": 0,
            "census_reported_resident_count": 0,
            "recognition_verified": False,
            "correction_generation": target["correction_generation"] + 1,
            "submitted_at": None,
            "adjudicated_at": None,
            "paid_amount_cents": None,
            "rejection_code": None,
            "adjudication_note": correction_note,
        }
    )
    store.claims[claim["id"]] = claim
    services.attribute_and_price(claim, takeover_id=target["id"])
    touch_once(target)
    if home is not None:
        touch_once(home)
    if unit is not None:
        touch_once(unit)
    return object_response(claim_out(claim), 201)


@bp.post("/per-diem-claims/<claim_id>/submit")
def submit_claim(claim_id):
    guard("BusinessOfficeManager")
    json_body()
    claim = find_claim(claim_id)
    if claim["status"] != "DRAFT":
        fail("ERR_CLAIM_STATE_INVALID", "Only a DRAFT claim may be submitted.")
    home = store.homes.get(claim["veterans_home_id"])
    if home is None or home["recognition_status"] != "RECOGNIZED":
        fail("ERR_HOME_NOT_RECOGNIZED", "The operating home is not federally RECOGNIZED.")
    unit = store.care_units.get(claim["care_unit_id"])
    if unit is not None and unit["certification_status"] == "DECERTIFIED":
        fail("ERR_UNIT_NOT_CERTIFIED", "A decertified unit may not submit a claim.")
    if services.has_consumed_day(
        claim["care_unit_id"], claim["claim_month"], claim["id"], claim["corrects_claim_id"]
    ):
        fail(
            "ERR_CENSUS_DAY_ALREADY_CLAIMED",
            "This unit-month holds census days billed by another live claim.",
        )
    if not claim["claim_month"] < clock_month():
        fail("ERR_CLAIM_MONTH_NOT_CLOSED", "The claim month is not yet closed.")

    days = services.attributable_days(
        claim["care_unit_id"], claim["claim_month"], claim["id"], claim["corrects_claim_id"]
    )
    priced = quote(claim, days)
    if priced["census_reported_resident_count"] < 1 or priced["billable_day_count"] < 1:
        fail("ERR_CLAIM_CENSUS_EMPTY", "The claim carries no billable census.")

    for day in days:
        day["per_diem_claim_id"] = claim["id"]
    claim.update(priced)
    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = now_iso()
    claim["recognition_verified"] = True
    touch_once(claim)
    if unit is not None:
        touch_once(unit)
    return object_response(claim_out(claim))


@bp.post("/per-diem-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    guard("FederalPerDiemAuditor")
    body = json_body()
    outcome = f_enum(body, "outcome", ("PAID", "REJECTED"))
    rejection_code = f_enum(body, "rejection_code", REJECTION_CODES, required=False)
    adjudication_note = f_str(body, "adjudication_note", required=False)
    if outcome == "REJECTED" and rejection_code is None:
        fail("ERR_INVALID_REQUEST", "Field 'rejection_code' is required on a REJECTED outcome.")

    claim = find_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        fail("ERR_CLAIM_STATE_INVALID", "Only a SUBMITTED claim may be adjudicated.")

    claim["status"] = outcome
    claim["adjudicated_at"] = now_iso()
    claim["adjudication_note"] = adjudication_note
    if outcome == "PAID":
        claim["paid_amount_cents"] = claim["claim_amount_cents"]
        claim["rejection_code"] = None
    else:
        claim["paid_amount_cents"] = 0
        claim["rejection_code"] = rejection_code
        for day in sorted(store.census_days.values(), key=order_key):
            if day["per_diem_claim_id"] == claim["id"]:
                day["per_diem_claim_id"] = None
    touch_once(claim)
    unit = store.care_units.get(claim["care_unit_id"])
    if unit is not None:
        touch_once(unit)
    return object_response(claim_out(claim))
