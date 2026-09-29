"""Opt-out requests and guest complaints (PRD 3.6, 3.7)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import resolve
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("guest", __name__)

OPT_OUT_STATUSES = ("REQUESTED", "GRANTED", "DENIED", "EXPIRED", "REVOKED")
DENIAL_REASONS = ("NOT_AVOIDABLE", "SERVICE_ALREADY_CONSUMED", "POLICY_EXCEPTION_DENIED")
COMPLAINT_REASONS = ("NOT_DISCLOSED", "MISSTATED_AMOUNT", "MANDATORY_NOT_AVOIDABLE",
                     "TOTAL_NOT_SHOWN")
COMPLAINT_STATUSES = ("SUBMITTED", "UNDER_INVESTIGATION", "SUBSTANTIATED",
                      "UNSUBSTANTIATED", "REFUNDED")
DISMISSAL_REASONS = ("DISCLOSURE_EVIDENCED", "GUEST_ACKNOWLEDGED_AT_CHECK_IN",
                     "DUPLICATE_COMPLAINT")
REFUND_VARIANTS = ("FULL_FEE_REFUND", "DISCLOSURE_GAP_DIFFERENTIAL")
ADJUSTABLE_FOLIO_STATUSES = ("POSTED", "ADJUSTED")
REFUND_LINE_DESCRIPTION = "Complaint refund"


def _adjustable_folio(booking, allowed=ADJUSTABLE_FOLIO_STATUSES):
    folio = store.folio_of_booking(booking["id"])
    if folio is None or folio["status"] not in allowed:
        raise ApiError("ERR_FOLIO_NOT_ADJUSTABLE",
                       "The folio cannot absorb a compensating line.")
    return folio


def _absorb(folio, booking):
    """A compensating line moves POSTED -> ADJUSTED, or leaves ADJUSTED alone."""
    folio["status"] = "ADJUSTED"
    derive.refresh_folio(folio)
    store.touch(folio)
    derive.refresh_booking_money(booking, folio)
    store.touch(booking)


def _mandatory_line_for(folio, fee_id):
    for line in store.lines_of_folio(folio["id"]):
        if line["line_type"] == "MANDATORY_FEE" and line["fee_id"] == fee_id:
            return line
    return None


def _standing_credit_count(folio, fee_id):
    credits = 0
    for line in store.lines_of_folio(folio["id"]):
        if line["fee_id"] != fee_id:
            continue
        if line["line_type"] == "FEE_CREDIT":
            credits += 1
        elif line["line_type"] == "FEE_REBILL":
            credits -= 1
    return credits


# ------------------------------------------------------------ opt-out requests

@bp.post("/bookings/<identifier>/opt-out-requests")
def create_opt_out(identifier):
    user_id, role = auth.require([auth.GUEST, auth.GUEST_SERVICES_AGENT])
    if role == auth.GUEST:
        auth.acting_booking(user_id)
        existing = resolve.peek("booking", identifier)
        if existing is not None:
            auth.booking_owns(user_id, existing["id"])
    booking = resolve.booking(identifier)

    payload = shape.body()
    fee_id = shape.identifier(payload, "fee_id")
    fee = resolve.fee(fee_id)

    # rank 24 — the fee must belong to the booking's pinned program
    if fee["fee_program_id"] != booking["fee_program_id"]:
        raise ApiError("ERR_FEE_NOT_ON_BOOKING_PROGRAM",
                       "The fee is not on the booking's pinned fee program.")

    # rank 30 — no live duplicate for the same (booking, fee) pair
    for existing in store.opt_outs_of_booking(booking["id"]):
        if existing["fee_id"] == fee["id"] and existing["status"] in ("REQUESTED", "GRANTED"):
            raise ApiError("ERR_DUPLICATE_OPT_OUT",
                           "A live opt-out already exists for this fee.")

    # rank 31 — the fee must be declinable at all
    if not fee["avoidable"] or fee["classification"] not in ("MANDATORY", "CONDITIONAL"):
        raise ApiError("ERR_FEE_NOT_AVOIDABLE", "The fee cannot be opted out of.")

    # rank 32 — the request must land early enough (inclusive comparison)
    delta = booking["arrival_date"] - clock.now()
    hours_before_arrival = int(delta.total_seconds() // 3600)
    if hours_before_arrival < fee["opt_out_window_hours"]:
        raise ApiError("ERR_OPT_OUT_WINDOW_CLOSED", "The opt-out window has closed.")

    row = {
        "booking_id": booking["id"],
        "fee_id": fee["id"],
        "status": "REQUESTED",
        "requested_hours_before_arrival": hours_before_arrival,
        "credit_cents": 0,
        "tax_credit_cents": 0,
        "credit_line_sequence_no": None,
        "denial_reason_code": None,
        "decided_at": None,
    }
    store.stamp_new(row)
    store.opt_out_requests[row["id"]] = row
    return envelope.created(serialize.opt_out_request(row))


@bp.get("/opt-out-requests/<identifier>")
def read_opt_out(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    if role == auth.GUEST:
        auth.acting_booking(user_id)
        existing = resolve.peek("opt_out_request", identifier)
        if existing is not None:
            auth.booking_owns(user_id, existing["booking_id"])
    return envelope.ok(serialize.opt_out_request(resolve.opt_out_request(identifier)))


@bp.get("/opt-out-requests")
def list_opt_outs():
    auth.require(auth.ALL_ROLES)
    rows = envelope.apply_filters(
        store.sort_default(store.opt_out_requests.values()),
        [("booking_id", envelope.str_filter("booking_id")),
         ("fee_id", envelope.str_filter("fee_id")),
         ("status", envelope.str_filter("status"))],
    )
    return envelope.page(rows, serialize.opt_out_request)


@bp.post("/opt-out-requests/<identifier>/grant")
def grant_opt_out(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    request_row = resolve.opt_out_request(identifier)
    booking = store.bookings.get(request_row["booking_id"])

    if request_row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED opt-out may be granted.")

    folio = _adjustable_folio(booking)

    source = _mandatory_line_for(folio, request_row["fee_id"])
    if source is None or _standing_credit_count(folio, request_row["fee_id"]) > 0:
        raise ApiError("ERR_FEE_LINE_NOT_ON_FOLIO",
                       "The folio carries no creditable mandatory-fee line for that fee.")

    fee = store.fees.get(request_row["fee_id"])
    rule = store.taxability_rule(source["jurisdiction_id"], source["fee_code"])
    if rule is not None and rule["taxability"] == "TAXABLE_IF_MANDATORY":
        determination = "TAXABLE_IF_MANDATORY_WAIVED"
    else:
        determination = source["taxability_determination"]

    credit = derive.append_line(
        folio, "FEE_CREDIT", source["jurisdiction_id"],
        fee["disclosure_text"] if fee else source["description"],
        source["amount_cents"], determination, source["tax_rate_bps"],
        -source["tax_cents"], fee_id=source["fee_id"], fee_code=source["fee_code"],
    )

    request_row["status"] = "GRANTED"
    request_row["credit_cents"] = abs(credit["amount_cents"])
    request_row["tax_credit_cents"] = abs(credit["tax_cents"])
    request_row["credit_line_sequence_no"] = credit["sequence_no"]
    request_row["decided_at"] = clock.now()
    store.touch(request_row)
    _absorb(folio, booking)
    return envelope.ok(serialize.opt_out_request(request_row))


@bp.post("/opt-out-requests/<identifier>/deny")
def deny_opt_out(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    request_row = resolve.opt_out_request(identifier)
    payload = shape.body()
    reason = shape.enum(payload, "denial_reason_code", DENIAL_REASONS)

    if request_row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED opt-out may be denied.")

    request_row["status"] = "DENIED"
    request_row["denial_reason_code"] = reason
    request_row["decided_at"] = clock.now()
    store.touch(request_row)
    return envelope.ok(serialize.opt_out_request(request_row))


@bp.post("/opt-out-requests/<identifier>/revoke")
def revoke_opt_out(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    request_row = resolve.opt_out_request(identifier)
    booking = store.bookings.get(request_row["booking_id"])

    if request_row["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_STATE", "Only a GRANTED opt-out may be revoked.")

    folio = _adjustable_folio(booking, allowed=("ADJUSTED",))

    credit_line = None
    for line in store.lines_of_folio(folio["id"]):
        if line["sequence_no"] == request_row["credit_line_sequence_no"] \
                and line["line_type"] == "FEE_CREDIT":
            credit_line = line
            break
    if credit_line is None:
        raise ApiError("ERR_FEE_LINE_NOT_ON_FOLIO",
                       "The credit line named by the request is not on the folio.")

    source = _mandatory_line_for(folio, request_row["fee_id"])
    determination = source["taxability_determination"] if source is not None \
        else credit_line["taxability_determination"]
    rate_bps = source["tax_rate_bps"] if source is not None else credit_line["tax_rate_bps"]

    derive.append_line(
        folio, "FEE_REBILL", credit_line["jurisdiction_id"], credit_line["description"],
        request_row["credit_cents"], determination, rate_bps,
        request_row["tax_credit_cents"], fee_id=credit_line["fee_id"],
        fee_code=credit_line["fee_code"],
    )

    request_row["status"] = "REVOKED"
    request_row["credit_cents"] = 0
    request_row["tax_credit_cents"] = 0
    request_row["credit_line_sequence_no"] = None
    request_row["decided_at"] = clock.now()
    store.touch(request_row)
    _absorb(folio, booking)
    return envelope.ok(serialize.opt_out_request(request_row))


# --------------------------------------------------------------- complaints

def _entitlement(complaint, booking, line):
    """PRD 3.7: the variant is selected by complaint_reason alone."""
    disputed = line["amount_cents"]
    fee_code = line.get("fee_code")
    disclosed = 0
    if fee_code:
        disclosed = booking.get("disclosed_fee_amounts", {}).get(fee_code, 0) or 0
    if complaint["complaint_reason"] == "MISSTATED_AMOUNT":
        variant = "DISCLOSURE_GAP_DIFFERENTIAL"
        differential = disputed - disclosed
        if differential < 0:
            differential = 0
        entitlement = differential + calc.rhu(
            calc.bps_of(differential, line["tax_rate_bps"]))
    else:
        variant = "FULL_FEE_REFUND"
        entitlement = disputed + line["tax_cents"]
    complaint["refund_variant"] = variant
    complaint["disputed_amount_cents"] = disputed
    complaint["disclosed_amount_cents"] = disclosed
    complaint["refund_entitlement_cents"] = entitlement
    return entitlement


@bp.post("/bookings/<identifier>/guest-complaints")
def create_complaint(identifier):
    user_id, role = auth.require([auth.GUEST, auth.GUEST_SERVICES_AGENT])
    if role == auth.GUEST:
        auth.acting_booking(user_id)
        existing = resolve.peek("booking", identifier)
        if existing is not None:
            auth.booking_owns(user_id, existing["id"])
    booking = resolve.booking(identifier)

    payload = shape.body()
    line_id = shape.identifier(payload, "folio_line_id")
    reason = shape.enum(payload, "complaint_reason", COMPLAINT_REASONS)
    narrative = shape.string(payload, "narrative", min_len=8, max_len=1000)

    line = resolve.folio_line(line_id)

    # rank 25 — the line must be a fee line on one of this booking's folios
    folio = store.folios.get(line["folio_id"])
    if folio is None or folio["booking_id"] != booking["id"] \
            or line["line_type"] not in ("MANDATORY_FEE", "OPTIONAL_FEE"):
        raise ApiError("ERR_FOLIO_LINE_NOT_ON_BOOKING",
                       "The disputed line does not belong to this booking.")

    row = {
        "booking_id": booking["id"],
        "folio_line_id": line["id"],
        "complaint_reason": reason,
        "narrative": narrative,
        "status": "SUBMITTED",
        "refund_variant": None,
        "disputed_amount_cents": 0,
        "disclosed_amount_cents": 0,
        "refund_entitlement_cents": 0,
        "refunded_amount_cents": 0,
        "dismissal_reason_code": None,
        "investigated_by_user_id": None,
        "adjudicated_by_user_id": None,
    }
    store.stamp_new(row)
    store.complaints[row["id"]] = row

    prop = derive.property_of(booking)
    if prop is not None:
        derive.recompute_property(prop)
    return envelope.created(serialize.complaint(row))


@bp.get("/guest-complaints/<identifier>")
def read_complaint(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    if role == auth.GUEST:
        auth.acting_booking(user_id)
        existing = resolve.peek("complaint", identifier)
        if existing is not None:
            auth.booking_owns(user_id, existing["booking_id"])
    return envelope.ok(serialize.complaint(resolve.complaint(identifier)))


@bp.get("/guest-complaints")
def list_complaints():
    auth.require(auth.ALL_ROLES)
    rows = envelope.apply_filters(
        store.sort_default(store.complaints.values()),
        [("booking_id", envelope.str_filter("booking_id")),
         ("folio_line_id", envelope.str_filter("folio_line_id")),
         ("status", envelope.str_filter("status")),
         ("refund_variant", envelope.str_filter("refund_variant"))],
    )
    return envelope.page(rows, serialize.complaint)


@bp.post("/guest-complaints/<identifier>/investigate")
def investigate_complaint(identifier):
    user_id, _role = auth.require([auth.COMPLIANCE_OFFICER, auth.GUEST_SERVICES_AGENT])
    complaint = resolve.complaint(identifier)
    if complaint["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED complaint may be moved under investigation.")
    complaint["status"] = "UNDER_INVESTIGATION"
    complaint["investigated_by_user_id"] = user_id
    store.touch(complaint)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/guest-complaints/<identifier>/substantiate")
def substantiate_complaint(identifier):
    user_id, _role = auth.require([auth.COMPLIANCE_OFFICER])
    complaint = resolve.complaint(identifier)

    # rank 9 — segregation of duties precedes the state gate
    if complaint["investigated_by_user_id"] is not None \
            and user_id == complaint["investigated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The adjudicator must differ from the investigator.")
    if complaint["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an UNDER_INVESTIGATION complaint may be substantiated.")

    booking = store.bookings.get(complaint["booking_id"])
    line = store.folio_lines.get(complaint["folio_line_id"])

    # level one — the complaint's own arithmetic
    _entitlement(complaint, booking, line)
    complaint["status"] = "SUBSTANTIATED"
    complaint["adjudicated_by_user_id"] = user_id
    store.touch(complaint)

    # level two — the booking's standing
    if booking["disclosure_status"] in ("PENDING_AUDIT", "DISCLOSED", "DISPUTED"):
        booking["disclosure_status"] = "UNDISCLOSED_CONFIRMED"
        store.touch(booking)

    # level three — the path's confirmed count and score
    profile = store.profiles.get(booking["channel_disclosure_profile_id"])
    flagged = False
    if profile is not None:
        profile["confirmed_undisclosed_count"] = profile["confirmed_undisclosed_count"] + 1
        score = derive.rescore_profile(profile)
        # level four — conditional flagging
        if score is not None and score < calc.FLAG_SCORE_FLOOR and profile["status"] == "DEPLOYED":
            profile["status"] = "FLAGGED"
            store.touch(profile)
            flagged = True

    prop = derive.property_of(booking)
    if prop is not None:
        derive.recompute_property(prop, force=flagged)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/guest-complaints/<identifier>/dismiss")
def dismiss_complaint(identifier):
    user_id, _role = auth.require([auth.COMPLIANCE_OFFICER])
    complaint = resolve.complaint(identifier)
    payload = shape.body()
    reason = shape.enum(payload, "dismissal_reason_code", DISMISSAL_REASONS)

    if complaint["investigated_by_user_id"] is not None \
            and user_id == complaint["investigated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The adjudicator must differ from the investigator.")
    if complaint["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an UNDER_INVESTIGATION complaint may be dismissed.")

    complaint["status"] = "UNSUBSTANTIATED"
    complaint["dismissal_reason_code"] = reason
    complaint["refund_entitlement_cents"] = 0
    complaint["refund_variant"] = None
    complaint["adjudicated_by_user_id"] = user_id
    store.touch(complaint)

    booking = store.bookings.get(complaint["booking_id"])
    if booking["disclosure_status"] in ("PENDING_AUDIT", "DISPUTED"):
        booking["disclosure_status"] = "DISCLOSED"
        store.touch(booking)

    prop = derive.property_of(booking)
    if prop is not None:
        derive.recompute_property(prop)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/guest-complaints/<identifier>/refund")
def refund_complaint(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    complaint = resolve.complaint(identifier)
    payload = shape.body()
    amount = shape.integer(payload, "refund_amount_cents", minimum=1)

    if complaint["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBSTANTIATED complaint may be refunded.")

    booking = store.bookings.get(complaint["booking_id"])
    folio = _adjustable_folio(booking)

    if complaint["refund_entitlement_cents"] <= 0:
        raise ApiError("ERR_NO_REFUND_ENTITLEMENT", "The complaint carries no entitlement.")
    if amount > complaint["refund_entitlement_cents"]:
        raise ApiError("ERR_REFUND_EXCEEDS_ENTITLEMENT",
                       "The refund exceeds the complaint's entitlement.")

    line = store.folio_lines.get(complaint["folio_line_id"])
    derive.append_line(
        folio, "COMPLAINT_REFUND", line["jurisdiction_id"], REFUND_LINE_DESCRIPTION,
        amount, "EXEMPT", 0, 0,
        fee_id=line.get("fee_id"), fee_code=line.get("fee_code"),
    )

    complaint["status"] = "REFUNDED"
    complaint["refunded_amount_cents"] = amount
    store.touch(complaint)

    if booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED":
        booking["disclosure_status"] = "CURED"
    _absorb(folio, booking)

    prop = derive.property_of(booking)
    if prop is not None:
        derive.recompute_property(prop)
    return envelope.ok(serialize.complaint(complaint))
