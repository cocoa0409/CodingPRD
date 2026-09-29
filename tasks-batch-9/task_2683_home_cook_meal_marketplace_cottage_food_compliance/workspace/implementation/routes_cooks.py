"""Cook registration, onboarding documents, onboarding decisions and standing."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    ANONYMOUS,
    COMPLIANCE_REVIEWER,
    COOK,
    DINER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
    SAFETY_OFFICER,
    acting_user,
    guard,
    require_owner,
)
from core import ApiError, created, db, new_row, ok, parse_date, public, touch
from listing import list_rows

bp = Blueprint("cooks", __name__)

COOK_READ_ROLES = [
    COOK,
    DINER,
    COMPLIANCE_REVIEWER,
    SAFETY_OFFICER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
]
DOC_READ_ROLES = [COOK, COMPLIANCE_REVIEWER, PLATFORM_ADMIN]
CERT_FIELDS = ("certificate_number", "issuing_authority", "issued_on", "expires_on")
INSPECTION_FIELDS = ("kitchen_type_claimed", "inspection_date")


def find_cook(cook_id):
    cook = db.cooks.get(cook_id)
    if cook is None:
        raise ApiError("ERR_COOK_NOT_FOUND")
    return cook


# ------------------------------------------------------------- registration
@bp.route("/cooks", methods=["POST"])
@guard([ANONYMOUS, PLATFORM_ADMIN])
def create_cook():
    body = v.body()
    legal_name = v.s_str(body, "legal_name", 1, 120)
    email = v.s_str(body, "email", 1, 320)
    state_code = v.s_str(body, "state_code", 2, 2)
    claimed = v.s_enum(body, "claimed_kitchen_type", v.KITCHEN_TYPES)
    weekly = v.s_int(body, "weekly_capacity_meals", minimum=1, required=False)
    if weekly is None:
        weekly = 40

    policy = calc.policy_for_state(state_code)
    if policy is None:
        raise ApiError("ERR_STATE_POLICY_NOT_FOUND", "no state policy for %s" % state_code)
    if claimed not in policy["allowed_kitchen_types"]:
        raise ApiError(
            "ERR_KITCHEN_TYPE_NOT_ALLOWED", "%s is not allowed in %s" % (claimed, state_code)
        )
    lowered = email.lower()
    for other in db.cooks.values():
        if other["email"].lower() == lowered:
            raise ApiError("ERR_DUPLICATE_COOK_EMAIL", "email already registered")

    row = new_row(
        db.cooks,
        {
            "legal_name": legal_name,
            "email": email,
            "state_code": state_code,
            "claimed_kitchen_type": claimed,
            "verified_kitchen_type": None,
            "weekly_capacity_meals": weekly,
            "onboarding_status": "DRAFT",
            "compliance_standing": "CLEAR",
            "standing_reason": None,
            "safety_score": 100,
            "cap_status": "UNDER_CAP",
            "ytd_gross_sales_cents": 0,
            "ytd_cottage_revenue_cents": 0,
            "pending_payout_cents": 0,
            "lifetime_paid_cents": 0,
        },
    )
    return created(public(row))


@bp.route("/cooks/<cook_id>", methods=["GET"])
@guard(COOK_READ_ROLES)
def get_cook(cook_id):
    return ok(public(find_cook(cook_id)))


@bp.route("/cooks", methods=["GET"])
@guard([COMPLIANCE_REVIEWER, SAFETY_OFFICER, FINANCE_OPERATOR, PLATFORM_ADMIN])
def list_cooks():
    return list_rows(
        list(db.cooks.values()), ["state_code", "onboarding_status", "compliance_standing"]
    )


@bp.route("/cooks/<cook_id>/compliance-summary", methods=["GET"])
@guard([COOK, COMPLIANCE_REVIEWER, SAFETY_OFFICER, PLATFORM_ADMIN])
def compliance_summary(cook_id):
    cook = find_cook(cook_id)
    require_owner(cook_id)
    policy = calc.policy_for_cook(cook)
    incidents = calc.cook_incidents(cook_id)
    return ok(
        {
            "cook_id": cook["id"],
            "safety_score": calc.safety_score(cook_id),
            "provisional_safety_score": calc.safety_score(cook_id, advisory=True),
            "compliance_standing": cook["compliance_standing"],
            "cap_status": cook["cap_status"],
            "ytd_cottage_revenue_cents": int(cook["ytd_cottage_revenue_cents"]),
            "cap_remaining_cents": int(policy["cottage_food_annual_cap_cents"])
            - int(cook["ytd_cottage_revenue_cents"]),
            "open_incident_count": len(
                [i for i in incidents if i["status"] in ("INTAKE", "TRIAGED")]
            ),
            "substantiated_incident_count": len(
                [i for i in incidents if i["status"] == "SUBSTANTIATED"]
            ),
            "approved_menu_item_count": len(
                [m for m in calc.cook_menu_items(cook_id) if m["review_status"] == "APPROVED"]
            ),
        }
    )


# ------------------------------------------------------- onboarding documents
def _validate_doc_fields(body, doc_type, policy):
    """Priority 31 then 32."""
    supplied_cert = [f for f in CERT_FIELDS if v.present(body, f)]
    supplied_inspection = [f for f in INSPECTION_FIELDS if v.present(body, f)]
    if doc_type == "FOOD_HANDLER_CERT":
        if len(supplied_cert) != len(CERT_FIELDS) or supplied_inspection:
            raise ApiError(
                "ERR_DOC_FIELDS_INVALID_FOR_TYPE",
                "a FOOD_HANDLER_CERT requires exactly the four certificate fields",
            )
        issued = parse_date(body["issued_on"])
        expires = parse_date(body["expires_on"])
        if expires <= issued:
            raise ApiError(
                "ERR_CERT_VALIDITY_TOO_LONG", "expires_on must fall strictly after issued_on"
            )
        if (expires - issued).days > int(policy["cert_validity_max_days"]):
            raise ApiError(
                "ERR_CERT_VALIDITY_TOO_LONG", "certificate validity span exceeds the state ceiling"
            )
    else:
        if len(supplied_inspection) != len(INSPECTION_FIELDS) or supplied_cert:
            raise ApiError(
                "ERR_DOC_FIELDS_INVALID_FOR_TYPE",
                "a KITCHEN_INSPECTION requires exactly kitchen_type_claimed and inspection_date",
            )


@bp.route("/onboarding-documents", methods=["POST"])
@guard([COOK, PLATFORM_ADMIN])
def create_document():
    body = v.body()
    cook_id = v.s_id(body, "cook_id")
    doc_type = v.s_enum(body, "doc_type", v.DOC_TYPES)
    expected = v.s_int(body, "expected_cook_version")
    # Conditional fields carry their declared JSON types when supplied; whether
    # they belong to the doc_type at all is priority 31.
    certificate_number = v.s_str(body, "certificate_number", 1, 120, required=False)
    issuing_authority = v.s_str(body, "issuing_authority", 1, 200, required=False)
    issued_on_raw, _ = v.s_date(body, "issued_on", required=False)
    expires_on_raw, _ = v.s_date(body, "expires_on", required=False)
    kitchen_type_claimed = v.s_enum(body, "kitchen_type_claimed", v.KITCHEN_TYPES, required=False)
    inspection_date_raw, _ = v.s_date(body, "inspection_date", required=False)

    cook = find_cook(cook_id)
    require_owner(cook_id)
    if expected != int(cook["version"]):
        raise ApiError("ERR_STALE_COOK_VERSION", "expected_cook_version does not match")

    # Priority 11 - the onboarding dimension must declare the submission edge and
    # a SUSPENDED or REVOKED cook may not submit at all.
    if cook["onboarding_status"] not in ("DRAFT", "DOCS_SUBMITTED"):
        raise ApiError(
            "ERR_INVALID_COOK_TRANSITION",
            "no document submission edge from %s" % cook["onboarding_status"],
        )
    if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
        raise ApiError(
            "ERR_INVALID_COOK_TRANSITION", "a suspended or revoked cook may not submit documents"
        )

    policy = calc.policy_for_cook(cook)
    _validate_doc_fields(body, doc_type, policy)

    row = new_row(
        db.documents,
        {
            "cook_id": cook_id,
            "doc_type": doc_type,
            "review_status": "SUBMITTED",
            "certificate_number": certificate_number,
            "issuing_authority": issuing_authority,
            "issued_on": issued_on_raw,
            "expires_on": expires_on_raw,
            "kitchen_type_claimed": kitchen_type_claimed,
            "inspection_date": inspection_date_raw,
            "superseded_by_document_id": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
        },
    )

    superseded_verified = False
    for older in calc.ordered_documents(cook_id):
        if older["id"] == row["id"] or older["doc_type"] != doc_type:
            continue
        if older["review_status"] in (
            "SUBMITTED",
            "VERIFIED",
            "REJECTED",
            "PASSED",
            "FAILED",
            "WAIVED",
        ):
            if older["review_status"] == "VERIFIED":
                superseded_verified = True
            older["review_status"] = "SUPERSEDED"
            older["superseded_by_document_id"] = row["id"]
            touch(older)

    cook["onboarding_status"] = "DOCS_SUBMITTED"
    touch(cook)
    if superseded_verified:
        services.reevaluate_revert(cook)
    return created(public(row))


@bp.route("/onboarding-documents/<document_id>", methods=["GET"])
@guard(DOC_READ_ROLES)
def get_document(document_id):
    row = db.documents.get(document_id)
    if row is None:
        raise ApiError("ERR_DOCUMENT_NOT_FOUND")
    return ok(public(row))


@bp.route("/onboarding-documents", methods=["GET"])
@guard(DOC_READ_ROLES)
def list_documents():
    return list_rows(
        list(db.documents.values()),
        ["cook_id", "doc_type", "review_status", "superseded_by_document_id"],
    )


CERT_DECISIONS = {"VERIFY": "VERIFIED", "REJECT": "REJECTED"}
INSPECTION_DECISIONS = {"PASS": "PASSED", "FAIL": "FAILED", "WAIVE": "WAIVED"}
ALL_DECISIONS = ["VERIFY", "REJECT", "PASS", "FAIL", "WAIVE"]


@bp.route("/onboarding-documents/<document_id>/review", methods=["POST"])
@guard([COMPLIANCE_REVIEWER, PLATFORM_ADMIN])
def review_document(document_id):
    body = v.body()
    decision = v.s_enum(body, "decision", ALL_DECISIONS)
    note = v.s_str(body, "note", 1, 2000, required=False)

    doc = db.documents.get(document_id)
    if doc is None:
        raise ApiError("ERR_DOCUMENT_NOT_FOUND")
    cook = find_cook(doc["cook_id"])

    table = CERT_DECISIONS if doc["doc_type"] == "FOOD_HANDLER_CERT" else INSPECTION_DECISIONS
    if decision not in table:
        raise ApiError(
            "ERR_INVALID_DOCUMENT_TRANSITION",
            "%s is not a legal decision for %s" % (decision, doc["doc_type"]),
        )
    if doc["review_status"] != "SUBMITTED":
        raise ApiError("ERR_DOC_ALREADY_REVIEWED", "the document has already been graded")

    policy = calc.policy_for_cook(cook)
    if decision == "VERIFY":
        expires = parse_date(doc.get("expires_on"))
        if expires is None or expires <= db.now().date():
            raise ApiError(
                "ERR_INVALID_DOCUMENT_TRANSITION", "the certificate expires_on is not in the future"
            )
    if decision == "WAIVE" and doc.get("kitchen_type_claimed") != "HOME_COTTAGE":
        raise ApiError(
            "ERR_INVALID_DOCUMENT_TRANSITION", "only HOME_COTTAGE may skip a physical inspection"
        )
    if decision == "PASS" and doc.get("kitchen_type_claimed") not in policy["allowed_kitchen_types"]:
        raise ApiError("ERR_KITCHEN_TYPE_NOT_ALLOWED", "the claimed kitchen type is not allowed")

    doc["review_status"] = table[decision]
    doc["reviewed_by_user_id"] = acting_user()
    doc["reviewed_at"] = db.now_iso()
    touch(doc)

    services.reevaluate_onboarding(cook)
    return ok(public(doc))


# --------------------------------------------------------- onboarding decision
@bp.route("/cooks/<cook_id>/onboarding-decision", methods=["POST"])
@guard([COMPLIANCE_REVIEWER, PLATFORM_ADMIN])
def onboarding_decision(cook_id):
    body = v.body()
    decision = v.s_enum(body, "decision", ["ACTIVATE", "REJECT"])
    note = v.s_str(body, "note", 1, 2000, required=False)

    cook = find_cook(cook_id)
    status = cook["onboarding_status"]

    if decision == "ACTIVATE":
        if status != "VERIFIED":
            raise ApiError("ERR_INVALID_COOK_TRANSITION", "ACTIVATE is legal only from VERIFIED")
        if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
            raise ApiError(
                "ERR_INVALID_COOK_TRANSITION", "a suspended or revoked cook cannot be activated"
            )
        policy = calc.policy_for_cook(cook)
        if cook["verified_kitchen_type"] not in policy["allowed_kitchen_types"]:
            raise ApiError(
                "ERR_KITCHEN_TYPE_NOT_ALLOWED", "the verified kitchen type is no longer allowed"
            )
        cook["onboarding_status"] = "ACTIVE"
        cook["standing_reason"] = None
    else:
        if status not in ("VERIFIED", "DOCS_SUBMITTED"):
            raise ApiError(
                "ERR_INVALID_COOK_TRANSITION", "REJECT is legal only from VERIFIED or DOCS_SUBMITTED"
            )
        cook["onboarding_status"] = "REJECTED"
        cook["standing_reason"] = note
    touch(cook)
    return ok(public(cook))


# ------------------------------------------------------------ standing actions
@bp.route("/cooks/<cook_id>/standing-actions", methods=["POST"])
@guard([SAFETY_OFFICER, PLATFORM_ADMIN])
def standing_action(cook_id):
    body = v.body()
    action = v.s_enum(body, "action", ["WARN", "SUSPEND", "REINSTATE", "REVOKE"])
    reason = v.s_str(body, "reason", 1, 2000)

    cook = find_cook(cook_id)
    standing = cook["compliance_standing"]
    suspend = False

    if action == "WARN":
        if standing != "CLEAR":
            raise ApiError("ERR_INVALID_COOK_TRANSITION", "WARN is legal only from CLEAR")
        cook["compliance_standing"] = "WARNED"
    elif action == "SUSPEND":
        if standing not in ("CLEAR", "WARNED"):
            raise ApiError("ERR_INVALID_COOK_TRANSITION", "SUSPEND is legal from CLEAR or WARNED")
        cook["compliance_standing"] = "SUSPENDED"
        suspend = True
    elif action == "REINSTATE":
        if standing != "SUSPENDED":
            raise ApiError("ERR_INVALID_COOK_TRANSITION", "REINSTATE is legal only from SUSPENDED")
        if [i for i in calc.cook_incidents(cook_id) if i["status"] in ("INTAKE", "TRIAGED")]:
            raise ApiError(
                "ERR_INVALID_COOK_TRANSITION", "open incidents block reinstatement"
            )
        cook["compliance_standing"] = "CLEAR"
    else:
        if standing != "SUSPENDED":
            raise ApiError("ERR_INVALID_COOK_TRANSITION", "REVOKE is legal only from SUSPENDED")
        cook["compliance_standing"] = "REVOKED"

    cook["standing_reason"] = reason
    touch(cook)
    if suspend:
        services.suspension_cascade(cook)
    return ok(public(cook))
