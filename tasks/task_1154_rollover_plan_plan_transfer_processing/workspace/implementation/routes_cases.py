"""Rollover cases: CRUD, submit, cancel, decide-eligibility (PRD §3.3, §3.4)."""

from flask import Blueprint, g, request

import errors
from db import clock_date, create_entity, store, touch
from middleware import (
    ALL_ROLES,
    body,
    opt_bool,
    opt_int,
    opt_str,
    paginate,
    req_enum,
    require_roles,
)
from response import ok, ok_list
from services import (
    CASE_TYPES,
    DOC_RULE_ORDER,
    DOC_TYPES,
    SUSPENDABLE_STATUSES,  # noqa: F401
    TERMINAL_CASE_STATUSES,
    VERIF_DIRECTIONS,
    VERIF_METHODS,
    account_vested,
    active_loans_of_account,
    case_owner_participant_id,
    case_receiving_account,
    case_source_account,
    docs_of_case,
    eligibility_event,
    msb_rows_of,
    serialize_case,
    serialize_disbursement,
    serialize_document,
    serialize_notice,
    serialize_redeposit,
    serialize_verification,
)

bp = Blueprint("cases", __name__)

OUTBOUND_TYPES = {"DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT", "PLAN_TRANSFER"}


def get_case_or_404(case_id, ownership_mask=True):
    c = store.cases.get(case_id)
    if c is None:
        raise errors.err_case_not_found()
    if ownership_mask and g.role == "Participant" and case_owner_participant_id(c) != g.user_id:
        raise errors.err_case_not_found()
    return c


def _account_owned_or_404(account_id):
    """Ownership masking for account references made by a Participant (PRD §2.1)."""
    acct = store.accounts.get(account_id)
    if acct is None:
        raise errors.err_account_not_found()
    if g.role == "Participant" and acct["participant_id"] != g.user_id:
        raise errors.err_account_not_found()
    return acct


def _validate_case_payload(data, creating=True):
    """Structural validation of case elections; returns normalized fields."""
    case_type = req_enum(data, "case_type", CASE_TYPES) if creating else None
    return case_type


@bp.post("/v1/rollover-cases")
@require_roles("Participant")
def create_case():
    data = body()
    case_type = req_enum(data, "case_type", CASE_TYPES)
    source_account_id = opt_str(data, "source_account_id")
    receiving_account_id = opt_str(data, "receiving_account_id")
    receiving_plan_id = opt_str(data, "receiving_plan_id")
    receiving_institution_name = opt_str(data, "receiving_institution_name")
    requested_amount_cents = opt_int(data, "requested_amount_cents")
    withholding_acknowledged = opt_bool(data, "withholding_acknowledged", False)

    # Structural requirements per case type (PRD §3.3).
    if case_type in ("DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT"):
        if not source_account_id:
            raise errors.err_validation("source_account_id is required for %s" % case_type)
        if receiving_account_id:
            raise errors.err_validation("receiving_account_id must be null for %s" % case_type)
        if bool(receiving_plan_id) == bool(receiving_institution_name):
            raise errors.err_validation(
                "exactly one of receiving_plan_id / receiving_institution_name must be set"
            )
    elif case_type == "PLAN_TRANSFER":
        if not source_account_id or not receiving_account_id or not receiving_plan_id:
            raise errors.err_validation(
                "source_account_id, receiving_account_id and receiving_plan_id are required for PLAN_TRANSFER"
            )
        if receiving_institution_name:
            raise errors.err_validation("receiving_institution_name must be null for PLAN_TRANSFER")
    elif case_type == "IN_PLAN_ROTH_CONVERSION":
        if not source_account_id or not receiving_account_id:
            raise errors.err_validation(
                "source_account_id and receiving_account_id are required for IN_PLAN_ROTH_CONVERSION"
            )
    elif case_type == "ROLLOVER_IN":
        if source_account_id:
            raise errors.err_validation("source_account_id must be null for ROLLOVER_IN")
        if not receiving_account_id:
            raise errors.err_validation("receiving_account_id is required for ROLLOVER_IN")

    # Existence + ownership of referenced accounts/plans (priority 2/3).
    src = _account_owned_or_404(source_account_id) if source_account_id else None
    recv = _account_owned_or_404(receiving_account_id) if receiving_account_id else None
    if receiving_plan_id and receiving_plan_id not in store.plans:
        raise errors.err_plan_not_found()

    # PRD §3.3 scopes the plan-state guard (ERR_PLAN_FROZEN) to the submit flow
    # only; case creation carries no plan-state gate, so a DRAFT may be opened
    # on a FROZEN plan and is then rejected at submit time.

    # Cross-reference consistency (priority 6).
    if case_type == "IN_PLAN_ROTH_CONVERSION" and receiving_account_id != source_account_id:
        raise errors.err_participant_mismatch("Conversion receiving account must be the source account")
    if case_type == "PLAN_TRANSFER":
        if receiving_plan_id == src["plan_id"]:
            raise errors.err_same_plan_transfer()
        if recv["participant_id"] != src["participant_id"] or recv["plan_id"] != receiving_plan_id:
            raise errors.err_participant_mismatch(
                "receiving account must belong to the same participant and sit at receiving_plan_id"
            )
    if requested_amount_cents is not None and requested_amount_cents <= 0:
        raise errors.err_validation("requested_amount_cents must be positive when present")

    # Open-case exclusivity on the source account (half-open occupation interval).
    if source_account_id:
        for c in store.cases.values():
            if c.get("source_account_id") == source_account_id and c["status"] not in TERMINAL_CASE_STATUSES:
                raise errors.err_open_case_exists()

    # Amount check last (PLAN_TRANSFER ignores it — it moves the full balance).
    if requested_amount_cents is not None and case_type != "PLAN_TRANSFER" and src is not None:
        if requested_amount_cents > account_vested(src["id"]):
            raise errors.err_amount_exceeds_vested()

    case = create_entity(
        store.cases,
        {
            "case_type": case_type,
            "source_account_id": source_account_id,
            "receiving_account_id": receiving_account_id,
            "receiving_plan_id": receiving_plan_id,
            "receiving_institution_name": receiving_institution_name,
            "requested_amount_cents": requested_amount_cents,
            "withholding_acknowledged": withholding_acknowledged,
            "status": "DRAFT",
            "prior_status": None,
            "qualifying_event": None,
            "gross_cents": None,
            "basis_portion_cents": None,
            "taxable_cents": None,
            "withholding_cents": None,
            "net_cents": None,
            "forfeiture_cents": 0,
            "disbursement_issued_date": None,
            "rollover_deadline_date": None,
            "eligibility_decided_by": None,
            "denial_reason": None,
        },
    )
    return ok(serialize_case(case), status=201)


@bp.get("/v1/rollover-cases")
@require_roles(*ALL_ROLES)
def list_cases():
    rows = list(store.cases.values())
    if g.role == "Participant":
        rows = [c for c in rows if case_owner_participant_id(c) == g.user_id]
    for param in ("source_account_id", "receiving_account_id", "receiving_plan_id", "status", "case_type"):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c.get(param) == v]
    rows.sort(key=lambda c: c["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_case(c) for c in page], total, limit, offset)


@bp.get("/v1/rollover-cases/<case_id>")
@require_roles(*ALL_ROLES)
def get_case(case_id):
    return ok(serialize_case(get_case_or_404(case_id)))


@bp.patch("/v1/rollover-cases/<case_id>")
@require_roles("Participant")
def amend_case(case_id):
    case = get_case_or_404(case_id)
    data = body()
    expected = data.get("expected_rollover_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err_validation("expected_rollover_case_version is required")
    if case["status"] != "DRAFT":
        raise errors.err_case_invalid_state("Only DRAFT cases may be amended")
    if expected != case["version"]:
        raise errors.err_stale_version()
    # Each successful amendment wholly replaces the prior election set (PRD §3.3).
    amount = opt_int(data, "requested_amount_cents")
    if amount is not None and amount <= 0:
        raise errors.err_validation("requested_amount_cents must be positive when present")
    case["requested_amount_cents"] = amount
    case["receiving_plan_id"] = opt_str(data, "receiving_plan_id")
    case["receiving_institution_name"] = opt_str(data, "receiving_institution_name")
    case["withholding_acknowledged"] = opt_bool(data, "withholding_acknowledged", False)
    touch(case)
    return ok(serialize_case(case))


@bp.post("/v1/rollover-cases/<case_id>/submit")
@require_roles("Participant")
def submit_case(case_id):
    case = get_case_or_404(case_id)
    if case["status"] != "DRAFT":
        raise errors.err_case_invalid_state("Only DRAFT cases may be submitted")
    case_type = case["case_type"]
    src = case_source_account(case)
    recv = case_receiving_account(case)
    src_plan = store.plans.get(src["plan_id"]) if src else None
    participant = store.participants.get(case_owner_participant_id(case))
    today = clock_date()

    # State guards (priority 4).
    if case_type == "ROLLOVER_IN":
        if recv is None or recv["status"] != "ACTIVE":
            raise errors.err_account_not_active()
        recv_plan = store.plans.get(recv["plan_id"])
        if recv_plan is not None and recv_plan["status"] == "FROZEN":
            raise errors.err_plan_frozen()
    else:
        if src_plan is not None and src_plan["status"] == "FROZEN":
            raise errors.err_plan_frozen()
        if src is None or src["status"] != "ACTIVE":
            raise errors.err_account_not_active()
        if case_type == "IN_PLAN_ROTH_CONVERSION" and (recv is None or recv["status"] != "ACTIVE"):
            raise errors.err_account_not_active()

    # Cross-reference consistency (priority 6).
    if case_type == "PLAN_TRANSFER":
        if case.get("receiving_plan_id") == src["plan_id"]:
            raise errors.err_same_plan_transfer()
        recv_plan = store.plans.get(case.get("receiving_plan_id")) if case.get("receiving_plan_id") else None
        if recv is None or recv["participant_id"] != src["participant_id"] or recv_plan is None or recv["plan_id"] != recv_plan["id"]:
            raise errors.err_participant_mismatch()
    if case_type == "IN_PLAN_ROTH_CONVERSION" and case.get("receiving_account_id") != case.get("source_account_id"):
        raise errors.err_participant_mismatch("Conversion receiving account must be the source account")

    # Eligibility snapshot (outbound types; ROLLOVER_IN / conversion exempt).
    qe = None
    if case_type in OUTBOUND_TYPES:
        qe = eligibility_event(src_plan, participant, today)
        if qe == "NONE":
            raise errors.err_not_eligible()

    # Withholding acknowledgement (INDIRECT only).
    if case_type == "INDIRECT_ROLLOVER_OUT" and not case.get("withholding_acknowledged"):
        raise errors.err_withholding_ack()

    # Capability gates (priority 8).
    if case_type == "PLAN_TRANSFER":
        rplan = store.plans.get(case.get("receiving_plan_id"))
        if rplan is not None and not rplan.get("accepts_incoming_transfers", True):
            raise errors.err_plan_capability("Receiving plan does not accept incoming transfers")
        if active_loans_of_account(src["id"]) and rplan is not None and not rplan.get("accepts_loan_transfers", True):
            raise errors.err_plan_capability("Receiving plan does not accept loan transfers")
    elif case_type == "ROLLOVER_IN":
        rplan = store.plans.get(recv["plan_id"])
        if rplan is not None and not rplan.get("accepts_incoming_rollovers", True):
            raise errors.err_plan_capability("Receiving plan does not accept incoming rollovers")
    elif case_type == "IN_PLAN_ROTH_CONVERSION":
        if src_plan is not None and not src_plan.get("allows_in_plan_roth_conversion", True):
            raise errors.err_plan_capability("Plan does not allow in-plan Roth conversions")
    # After-tax basis in scope requires the receiving plan to accept after-tax basis.
    if src is not None:
        has_after_tax_basis = any(
            r["source_type"] == "AFTER_TAX" and r["basis_cents"] > 0 for r in msb_rows_of(src["id"])
        )
        if has_after_tax_basis:
            if case_type in ("DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT"):
                target = store.plans.get(case.get("receiving_plan_id")) if case.get("receiving_plan_id") else None
            elif case_type == "PLAN_TRANSFER":
                target = store.plans.get(case.get("receiving_plan_id"))
            else:  # IN_PLAN_ROTH_CONVERSION
                target = src_plan
            if target is not None and not target.get("accepts_after_tax_basis", True):
                raise errors.err_plan_capability("Receiving plan does not accept after-tax basis")

    # Open-case exclusivity (other non-terminal case on the same source account).
    if src is not None:
        for c in store.cases.values():
            if (
                c["id"] != case["id"]
                and c.get("source_account_id") == src["id"]
                and c["status"] not in TERMINAL_CASE_STATUSES
            ):
                raise errors.err_open_case_exists()

    # Amount check last; PLAN_TRANSFER ignores it.
    if case.get("requested_amount_cents") is not None and case_type != "PLAN_TRANSFER":
        if case["requested_amount_cents"] > account_vested(src["id"]):
            raise errors.err_amount_exceeds_vested()

    # Side effects: store qualifying event, create required documents, route.
    case["qualifying_event"] = qe
    required = _required_doc_types(case, participant, src, src_plan, qe)
    for dt in required:
        create_entity(
            store.documents,
            {
                "rollover_case_id": case["id"],
                "doc_type": dt,
                "status": "REQUIRED",
                "submitted_by": None,
                "reviewed_by": None,
                "review_note": None,
            },
        )
    case["status"] = "ELIGIBILITY_REVIEW" if not required else "DOCS_PENDING"
    touch(case)
    return ok(serialize_case(case))


def _required_doc_types(case, participant, src, src_plan, qe):
    """required_document_rules (SCAFFOLD §1.3) in pinned deterministic order."""
    case_type = case["case_type"]
    wanted = set()
    if (
        src_plan is not None
        and src_plan.get("requires_spousal_consent", True)
        and participant is not None
        and participant["marital_status"] == "MARRIED"
        and src is not None
        and account_vested(src["id"]) > src_plan.get("spousal_consent_threshold_cents", 500000)
        and case_type in ("DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT", "PLAN_TRANSFER")
    ):
        wanted.add("SPOUSAL_CONSENT")
    if qe == "SEPARATION":
        wanted.add("SEPARATION_VERIFICATION")
    if qe == "DISABILITY":
        wanted.add("DISABILITY_PROOF")
    if case_type == "INDIRECT_ROLLOVER_OUT":
        wanted.add("IDENTITY_PROOF")
    if case_type in ("DIRECT_ROLLOVER_OUT", "PLAN_TRANSFER"):
        wanted.add("RECEIVING_PLAN_ACCEPTANCE")
    if case_type == "ROLLOVER_IN":
        wanted.add("SOURCE_PLAN_STATEMENT")
    return [dt for dt in DOC_RULE_ORDER if dt in wanted]


@bp.post("/v1/rollover-cases/<case_id>/cancel")
@require_roles("Participant")
def cancel_case(case_id):
    case = get_case_or_404(case_id)
    if case["status"] not in ("DRAFT", "DOCS_PENDING", "ELIGIBILITY_REVIEW"):
        raise errors.err_case_invalid_state("Case cannot be cancelled from its current state")
    case["status"] = "CANCELLED"
    touch(case)
    return ok(serialize_case(case))


@bp.post("/v1/rollover-cases/<case_id>/decide-eligibility")
@require_roles("RolloverProcessor")
def decide_eligibility(case_id):
    case = get_case_or_404(case_id, ownership_mask=False)
    if case["status"] != "ELIGIBILITY_REVIEW":
        raise errors.err_case_invalid_state("Case is not in ELIGIBILITY_REVIEW")
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "DENY", "REQUEST_DOCS"})
    if decision == "APPROVE":
        docs = docs_of_case(case["id"])
        if docs and any(d["status"] != "ACCEPTED" for d in docs):
            raise errors.err_documents_outstanding()
        case["eligibility_decided_by"] = g.user_id
        if case["case_type"] in ("PLAN_TRANSFER", "ROLLOVER_IN"):
            case["status"] = "ACCEPTANCE_PENDING"
        else:
            case["status"] = "ELIGIBLE"
        touch(case)
    elif decision == "DENY":
        reason = data.get("denial_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err_validation("denial_reason is required when decision is DENY")
        case["denial_reason"] = reason
        case["eligibility_decided_by"] = g.user_id
        case["status"] = "DENIED"
        touch(case)
    else:  # REQUEST_DOCS
        raw = data.get("request_doc_types")
        if not isinstance(raw, list) or not raw:
            raise errors.err_validation("request_doc_types must be a non-empty list")
        seen = set()
        ordered = []
        for dt in raw:
            if dt not in DOC_TYPES:
                raise errors.err_validation("invalid doc_type: %r" % dt)
            if dt not in seen:
                seen.add(dt)
                ordered.append(dt)
        existing = {d["doc_type"] for d in docs_of_case(case["id"])}
        for dt in ordered:
            if dt in existing:
                continue  # at most one row per (case, doc_type)
            create_entity(
                store.documents,
                {
                    "rollover_case_id": case["id"],
                    "doc_type": dt,
                    "status": "REQUIRED",
                    "submitted_by": None,
                    "reviewed_by": None,
                    "review_note": None,
                },
            )
        case["status"] = "DOCS_PENDING"
        touch(case)
    return ok(serialize_case(case))


# --------------------------------------------------- case sub-resource lists
@bp.get("/v1/rollover-cases/<case_id>/documents")
@require_roles(*ALL_ROLES)
def list_case_documents(case_id):
    get_case_or_404(case_id)
    rows = docs_of_case(case_id)
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_document(d) for d in page], total, limit, offset)


@bp.get("/v1/rollover-cases/<case_id>/disbursements")
@require_roles(*ALL_ROLES)
def list_case_disbursements(case_id):
    get_case_or_404(case_id)
    rows = [d for d in store.disbursements.values() if d["rollover_case_id"] == case_id]
    rows.sort(key=lambda d: d["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_disbursement(d) for d in page], total, limit, offset)


@bp.get("/v1/rollover-cases/<case_id>/redeposits")
@require_roles(*ALL_ROLES)
def list_case_redeposits(case_id):
    get_case_or_404(case_id)
    rows = [r for r in store.redeposits.values() if r.get("rollover_case_id") == case_id]
    rows.sort(key=lambda r: r["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_redeposit(r) for r in page], total, limit, offset)


@bp.get("/v1/rollover-cases/<case_id>/verifications")
@require_roles(*ALL_ROLES)
def list_case_verifications(case_id):
    get_case_or_404(case_id)
    rows = [v for v in store.verifications.values() if v["rollover_case_id"] == case_id]
    rows.sort(key=lambda v: v["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_verification(v) for v in page], total, limit, offset)


@bp.get("/v1/rollover-cases/<case_id>/notices")
@require_roles(*ALL_ROLES)
def list_case_notices(case_id):
    get_case_or_404(case_id)
    rows = [n for n in store.notices.values() if n["rollover_case_id"] == case_id]
    rows.sort(key=lambda n: n["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_notice(n) for n in page], total, limit, offset)


@bp.post("/v1/rollover-cases/<case_id>/verifications")
@require_roles("RolloverProcessor")
def create_verification(case_id):
    get_case_or_404(case_id, ownership_mask=False)
    data = body()
    direction = req_enum(data, "direction", VERIF_DIRECTIONS)
    method = req_enum(data, "method", VERIF_METHODS)
    ver = create_entity(
        store.verifications,
        {
            "rollover_case_id": case_id,
            "direction": direction,
            "method": method,
            "status": "PENDING",
            "verified_at": None,
        },
    )
    return ok(serialize_verification(ver), status=201)
