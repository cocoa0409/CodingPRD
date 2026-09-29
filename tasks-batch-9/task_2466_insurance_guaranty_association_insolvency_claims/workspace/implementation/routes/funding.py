"""Member insurers, assessments, member assessment invoices, surcharge recoupment."""

from flask import Blueprint

import domain
from auth import (
    ROLE_ASSESSMENT_OFFICER,
    ROLE_ASSOCIATION_ADMIN,
    ROLE_MEMBER_INSURER_AGENT,
    acting_user_id,
    endpoint,
)
from calc import (
    DEFAULT_ANNUAL_CAP_RATE_BPS,
    MAX_AGGREGATE_SURCHARGE_BPS,
    member_assessment_allocation,
    recoupment_surcharge_projection,
)
from envelope import list_response, object_response
from errors import fail
from shape import F, enum_filter, get_body, no_body, paginate, pagination, str_filter, validate
from store import now_iso, sort_rows, stamp_new, store, touch

funding_bp = Blueprint("funding", __name__)


def _require_member_ownership(member_assessment_id):
    """Validation priority 4: a MemberInsurerAgent acts only on its own invoice.

    Evaluated ahead of the existence check; with no invoice row there is no
    member_insurer_id to differ from, so the check passes and the 404 stands.
    """
    row = store.member_assessments.get(member_assessment_id)
    if row is not None and row["member_insurer_id"] != acting_user_id():
        fail(
            "ERR_NOT_ASSESSED_MEMBER",
            "X-User-ID is not the member insurer this invoice was issued to.",
        )
    return row


def _member_ordering(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["sequence"]))


# ==========================================================================
# member insurers
# ==========================================================================
@funding_bp.route("/member-insurers", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_member_insurer():
    values = validate(
        get_body(),
        [
            F("naic_code", "str"),
            F("insurer_name", "str"),
            F("assessable_line", "enum", enum=domain.LINES),
            F("base_year", "int", minimum=2000, maximum=2100),
            F("direct_written_premium_cents", "int", minimum=0),
            F(
                "annual_cap_rate_bps",
                "int",
                required=False,
                default=DEFAULT_ANNUAL_CAP_RATE_BPS,
                minimum=0,
                maximum=200,
            ),
        ],
    )
    for existing in store.member_insurers.values():
        if (
            existing["naic_code"] == values["naic_code"]
            and existing["assessable_line"] == values["assessable_line"]
            and existing["base_year"] == values["base_year"]
        ):
            fail(
                "ERR_MEMBER_DUPLICATE_LINE",
                "naic_code '%s' is already registered for line '%s' and base year %s."
                % (values["naic_code"], values["assessable_line"], values["base_year"]),
            )

    row = {
        "naic_code": values["naic_code"],
        "insurer_name": values["insurer_name"],
        "assessable_line": values["assessable_line"],
        "base_year": values["base_year"],
        "direct_written_premium_cents": values["direct_written_premium_cents"],
        "annual_cap_rate_bps": values["annual_cap_rate_bps"],
        "account_status": "ACTIVE",
        "sequence": store.next_sequence("member_insurer"),
    }
    stamp_new(row)
    store.member_insurers[row["id"]] = row
    return object_response(domain.serialize_member_insurer(row), 201)


@funding_bp.route("/member-insurers/<member_insurer_id>", methods=["PATCH"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def update_member_insurer(member_insurer_id):
    row = domain.get_member_insurer(member_insurer_id)
    body = get_body()
    values = validate(
        body,
        [
            F("direct_written_premium_cents", "int", required=False, minimum=0),
            F("annual_cap_rate_bps", "int", required=False, minimum=0, maximum=200),
            F("account_status", "enum", required=False, enum=domain.ACCOUNT_STATUSES),
        ],
    )
    for field in ("direct_written_premium_cents", "annual_cap_rate_bps", "account_status"):
        if values[field] is not None:
            row[field] = values[field]
    touch(row)
    return object_response(domain.serialize_member_insurer(row))


@funding_bp.route("/member-insurers/<member_insurer_id>", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_ASSESSMENT_OFFICER, ROLE_MEMBER_INSURER_AGENT])
def read_member_insurer(member_insurer_id):
    row = domain.get_member_insurer(member_insurer_id)
    return object_response(domain.serialize_member_insurer(row))


# ==========================================================================
# assessments
# ==========================================================================
@funding_bp.route("/assessments", methods=["POST"])
@endpoint([ROLE_ASSESSMENT_OFFICER])
def create_assessment():
    body = get_body()

    # priority 13: body foreign keys resolve before request-shape validation
    raw_insolvency_id = body.get("insolvency_id")
    if isinstance(raw_insolvency_id, str) and raw_insolvency_id not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % raw_insolvency_id,
        )

    values = validate(
        body,
        [
            F("insolvency_id", "str"),
            F("assessable_line", "enum", enum=domain.LINES),
            F("base_year", "int", minimum=2000, maximum=2100),
            F("needed_amount_cents", "int", exclusive_minimum=0),
        ],
    )
    if values["insolvency_id"] not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % values["insolvency_id"],
        )
    insolvency = store.insolvencies[values["insolvency_id"]]
    if insolvency["status"] == "CLOSED":
        fail("ERR_INSOLVENCY_CLOSED", "The insolvency file is closed.")

    row = {
        "insolvency_id": values["insolvency_id"],
        "assessable_line": values["assessable_line"],
        "base_year": values["base_year"],
        "needed_amount_cents": values["needed_amount_cents"],
        "status": "DRAFT",
        "levied_amount_cents": 0,
        "shortfall_cents": 0,
        "member_count": 0,
        "certified_at_utc": None,
    }
    stamp_new(row)
    store.assessments[row["id"]] = row
    return object_response(domain.serialize_assessment(row), 201)


@funding_bp.route("/assessments/<assessment_id>", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_ASSESSMENT_OFFICER])
def read_assessment(assessment_id):
    row = domain.get_assessment(assessment_id)
    return object_response(domain.serialize_assessment(row))


@funding_bp.route("/assessments/<assessment_id>/certify", methods=["POST"])
@endpoint([ROLE_ASSESSMENT_OFFICER])
def certify_assessment(assessment_id):
    assessment = domain.get_assessment(assessment_id)
    no_body()

    if assessment["status"] != "DRAFT":
        fail(
            "ERR_ASSESSMENT_INVALID_STATE",
            "An assessment in '%s' cannot be certified." % assessment["status"],
        )

    insolvency = store.insolvencies.get(assessment["insolvency_id"])
    if insolvency is None or insolvency["status"] != "TRIGGERED":
        fail(
            "ERR_INSOLVENCY_NOT_TRIGGERED",
            "The triggering event has not been recorded on this insolvency file.",
        )

    pool = [
        m
        for m in store.member_insurers.values()
        if m["account_status"] == "ACTIVE"
        and m["assessable_line"] == assessment["assessable_line"]
        and m["base_year"] == assessment["base_year"]
        and int(m["direct_written_premium_cents"] or 0) > 0
    ]
    if not pool:
        fail(
            "ERR_PREMIUM_BASE_EMPTY",
            "No ACTIVE member insurer carries a positive premium base for this line and year.",
        )

    pool = _member_ordering(pool)
    allocation = member_assessment_allocation(pool, assessment["needed_amount_cents"])

    levied_total = 0
    for item in allocation:
        member = item["member"]
        invoice = {
            "assessment_id": assessment_id,
            "member_insurer_id": member["id"],
            "premium_base_cents": int(member["direct_written_premium_cents"] or 0),
            "cap_amount_cents": item["cap_amount_cents"],
            "levied_amount_cents": item["levied_amount_cents"],
            "paid_amount_cents": 0,
            "capped": item["capped"],
            "billing_status": "INVOICED",
            "recoupment_status": "NOT_STARTED",
            "surcharge_rate_bps": 0,
            "surcharge_base_cents": 0,
            "projected_recoupment_cents": 0,
            "recouped_amount_cents": 0,
            "sequence": store.next_sequence("member_assessment:%s" % assessment_id),
        }
        stamp_new(invoice)
        store.member_assessments[invoice["id"]] = invoice
        levied_total += item["levied_amount_cents"]

    assessment["levied_amount_cents"] = levied_total
    assessment["member_count"] = len(allocation)
    assessment["shortfall_cents"] = max(
        0, int(assessment["needed_amount_cents"]) - levied_total
    )
    assessment["certified_at_utc"] = now_iso()
    assessment["status"] = "CERTIFIED"
    touch(assessment)
    # Insolvency.assessment_shortfall_cents is derived from the certified
    # assessments of the file, so the roll-up needs no separate write.
    return object_response(domain.serialize_assessment(assessment))


# ==========================================================================
# member assessment invoices
# ==========================================================================
@funding_bp.route("/member-assessments", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_ASSESSMENT_OFFICER, ROLE_MEMBER_INSURER_AGENT])
def list_member_assessments():
    limit, offset = pagination()
    assessment_id = str_filter("assessment_id")
    member_insurer_id = str_filter("member_insurer_id")
    billing_status = enum_filter("billing_status", domain.BILLING_STATUSES)
    recoupment_status = enum_filter("recoupment_status", domain.RECOUPMENT_STATUSES)

    rows = list(store.member_assessments.values())
    if assessment_id is not None:
        rows = [r for r in rows if r["assessment_id"] == assessment_id]
    if member_insurer_id is not None:
        rows = [r for r in rows if r["member_insurer_id"] == member_insurer_id]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    if recoupment_status is not None:
        rows = [r for r in rows if r["recoupment_status"] == recoupment_status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_member_assessment(r) for r in page], limit, offset, total
    )


@funding_bp.route("/member-assessments/<member_assessment_id>", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_ASSESSMENT_OFFICER, ROLE_MEMBER_INSURER_AGENT])
def read_member_assessment(member_assessment_id):
    row = domain.get_member_assessment(member_assessment_id)
    return object_response(domain.serialize_member_assessment(row))


@funding_bp.route("/member-assessments/<member_assessment_id>/payments", methods=["POST"])
@endpoint([ROLE_MEMBER_INSURER_AGENT])
def create_payment(member_assessment_id):
    _require_member_ownership(member_assessment_id)
    invoice = domain.get_member_assessment(member_assessment_id)
    values = validate(
        get_body(),
        [F("amount_cents", "int", exclusive_minimum=0), F("payment_ref", "str")],
    )

    if invoice["billing_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        fail(
            "ERR_MEMBER_ASSESSMENT_INVALID_STATE",
            "An invoice whose billing_status is '%s' cannot take a payment."
            % invoice["billing_status"],
        )

    levied = int(invoice["levied_amount_cents"] or 0)
    paid = int(invoice["paid_amount_cents"] or 0)
    total = paid + int(values["amount_cents"])
    if total > levied:
        fail(
            "ERR_OVERPAYMENT",
            "amount_cents exceeds the invoice's outstanding balance of %d cents."
            % (levied - paid),
        )

    if total == levied:
        invoice["paid_amount_cents"] = levied
        invoice["billing_status"] = "PAID"
    else:
        invoice["paid_amount_cents"] = total
        invoice["billing_status"] = "PARTIALLY_PAID"
    touch(invoice)

    assessment = store.assessments.get(invoice["assessment_id"])
    if assessment is not None and assessment["status"] == "CERTIFIED":
        siblings = domain.invoices_of_assessment(assessment["id"])
        if siblings and all(s["billing_status"] == "PAID" for s in siblings):
            assessment["status"] = "SETTLED"
            touch(assessment)
    return object_response(domain.serialize_member_assessment(invoice))


@funding_bp.route(
    "/member-assessments/<member_assessment_id>/surcharge-filings", methods=["POST"]
)
@endpoint([ROLE_MEMBER_INSURER_AGENT])
def create_surcharge_filing(member_assessment_id):
    _require_member_ownership(member_assessment_id)
    invoice = domain.get_member_assessment(member_assessment_id)
    values = validate(
        get_body(),
        [
            F("surcharge_rate_bps", "int", minimum=0, maximum=MAX_AGGREGATE_SURCHARGE_BPS),
            F("surcharge_base_cents", "int", minimum=0),
            F("filing_ref", "str"),
        ],
    )

    if invoice["recoupment_status"] != "NOT_STARTED":
        fail(
            "ERR_MEMBER_ASSESSMENT_INVALID_STATE",
            "A surcharge has already been filed on this invoice (recoupment_status '%s')."
            % invoice["recoupment_status"],
        )

    already_filed = 0
    for sibling in domain.invoices_of_member(invoice["member_insurer_id"]):
        if sibling["recoupment_status"] in ("SURCHARGE_FILED", "RECOUPING"):
            already_filed += int(sibling["surcharge_rate_bps"] or 0)
    if already_filed + int(values["surcharge_rate_bps"]) > MAX_AGGREGATE_SURCHARGE_BPS:
        fail(
            "ERR_SURCHARGE_AGGREGATE_EXCEEDED",
            "The member's filed surcharge rates would total %d bps, above the statutory %d bps."
            % (already_filed + int(values["surcharge_rate_bps"]), MAX_AGGREGATE_SURCHARGE_BPS),
        )

    invoice["surcharge_rate_bps"] = values["surcharge_rate_bps"]
    invoice["surcharge_base_cents"] = values["surcharge_base_cents"]
    invoice["projected_recoupment_cents"] = recoupment_surcharge_projection(
        values["surcharge_base_cents"],
        values["surcharge_rate_bps"],
        invoice["levied_amount_cents"],
    )
    invoice["recoupment_status"] = "SURCHARGE_FILED"
    touch(invoice)
    return object_response(domain.serialize_member_assessment(invoice))


@funding_bp.route(
    "/member-assessments/<member_assessment_id>/recoupment-remittances", methods=["POST"]
)
@endpoint([ROLE_MEMBER_INSURER_AGENT])
def create_recoupment_remittance(member_assessment_id):
    _require_member_ownership(member_assessment_id)
    invoice = domain.get_member_assessment(member_assessment_id)
    values = validate(
        get_body(),
        [F("proceeds_cents", "int", exclusive_minimum=0), F("remittance_ref", "str")],
    )

    if invoice["recoupment_status"] not in ("SURCHARGE_FILED", "RECOUPING"):
        fail(
            "ERR_RECOUPMENT_NOT_FILED",
            "Surcharge proceeds may only be remitted while recoupment_status is "
            "SURCHARGE_FILED or RECOUPING (currently '%s')." % invoice["recoupment_status"],
        )

    levied = int(invoice["levied_amount_cents"] or 0)
    recouped = int(invoice["recouped_amount_cents"] or 0)
    total = recouped + int(values["proceeds_cents"])
    if total > levied:
        fail(
            "ERR_OVER_RECOUPMENT",
            "recouped_amount_cents plus proceeds_cents would exceed the levy by %d cents."
            % (total - levied),
        )

    if total == levied:
        invoice["recouped_amount_cents"] = levied
        invoice["recoupment_status"] = "RECOUPED"
    else:
        invoice["recouped_amount_cents"] = total
        invoice["recoupment_status"] = "RECOUPING"
    touch(invoice)
    return object_response(domain.serialize_member_assessment(invoice))
