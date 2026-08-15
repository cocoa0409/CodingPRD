"""Prior authorizations: create, decide, appeal."""

from flask import Blueprint

from db import store, new_id, now_iso
from errors import (
    ApiError,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_INVALID_TRANSITION,
    ERR_ALREADY_TERMINAL,
    ERR_PA_NOT_REQUIRED,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, body_optional, req_string, req_enum, opt_string,
    get_enrollment_or_404, get_pa_or_404, pagination_params, paginate, touch,
)
from services.calc import (
    serialize_pa, bi_for_enrollment, pas_for_enrollment,
    activate_reserved_assistance, release_all_nonterminal_assistances,
    cancel_pending_shipments, MAX_APPEAL_ROUNDS,
)

bp = Blueprint("prior_auth", __name__)


@bp.post("/hub/enrollments/<eid>/prior-authorization")
def create_pa(eid):
    require_roles("CaseManager")
    e = get_enrollment_or_404(eid)
    data = body()
    clinical_notes = req_string(data, "clinical_notes")
    payer_reference = req_string(data, "payer_reference")

    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    if e["status"] != "BENEFITS_VERIFIED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "PA creation requires enrollment in BENEFITS_VERIFIED.",
                       409)
    bi = bi_for_enrollment(eid)
    if bi is None or not bi["requires_prior_auth"]:
        raise ApiError(ERR_PA_NOT_REQUIRED,
                       "The plan does not require prior authorization.", 422)

    ts = now_iso()
    pa = {
        "id": new_id(),
        "enrollment_id": eid,
        "clinical_notes": clinical_notes,
        "payer_reference": payer_reference,
        "status": "SUBMITTED",
        "appeal_round": 0,
        "decision_rationale": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.prior_authorizations[pa["id"]] = pa
    e["status"] = "PA_PENDING"
    touch(e)
    return success_object(serialize_pa(pa), 201)


@bp.get("/hub/enrollments/<eid>/prior-authorizations")
def list_pas(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(pas_for_enrollment(eid), limit, offset)
    return success_array([serialize_pa(p) for p in page], limit, offset, total, 200)


@bp.post("/hub/prior-authorizations/<pid>/decision")
def decide_pa(pid):
    require_roles("PayerReviewer")
    pa = get_pa_or_404(pid)
    data = body()
    outcome = req_enum(data, "outcome", ("APPROVED", "DENIED"))
    rationale = opt_string(data, "rationale")

    if pa["status"] in ("APPROVED", "DENIED_FINAL"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "Prior authorization is terminal.", 409)
    if pa["status"] == "DENIED":
        # A DENIED (non-final) PA is awaiting an appeal, not a decision.
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Decision requires PA in SUBMITTED or APPEALED.", 409)

    e = store.enrollments[pa["enrollment_id"]]
    pa["decision_rationale"] = rationale

    if outcome == "APPROVED":
        # SUBMITTED -> APPROVED or APPEALED -> APPROVED.
        pa["status"] = "APPROVED"
        touch(pa)
        # Cascade: enrollment PA_PENDING -> APPROVED + approval cascade.
        if e["status"] == "PA_PENDING":
            e["status"] = "APPROVED"
            touch(e)
            activate_reserved_assistance(e)
        return success_object(serialize_pa(pa), 200)

    # outcome == DENIED
    if pa["status"] == "APPEALED" and pa["appeal_round"] >= MAX_APPEAL_ROUNDS:
        pa["status"] = "DENIED_FINAL"
        touch(pa)
        # Cascade: enrollment PA_PENDING -> DENIED_CLOSED; release assistances,
        # cancel pending shipments.
        if e["status"] == "PA_PENDING":
            e["status"] = "DENIED_CLOSED"
            touch(e)
            release_all_nonterminal_assistances(e)
            cancel_pending_shipments(e)
        return success_object(serialize_pa(pa), 200)

    # SUBMITTED -> DENIED or APPEALED -> DENIED (appeal_round < cap).
    pa["status"] = "DENIED"
    touch(pa)
    if e["status"] == "PA_PENDING":
        e["status"] = "PA_DENIED"
        touch(e)
    return success_object(serialize_pa(pa), 200)


@bp.post("/hub/prior-authorizations/<pid>/appeal")
def appeal_pa(pid):
    require_roles("CaseManager")
    pa = get_pa_or_404(pid)
    body_optional()  # optional clinical_notes accepted
    if pa["status"] in ("APPROVED", "DENIED_FINAL"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "Prior authorization is terminal.", 409)
    if pa["status"] != "DENIED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Appeal requires PA in DENIED.", 409)
    if pa["appeal_round"] >= MAX_APPEAL_ROUNDS:
        # Appeal cap reached: this PA cannot be appealed again. From the
        # scaffold, appeal preconditions are status==DENIED and
        # appeal_round < 2; a violation here is an invalid transition.
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Appeal round cap reached.", 409)

    pa["status"] = "APPEALED"
    pa["appeal_round"] += 1
    touch(pa)
    e = store.enrollments[pa["enrollment_id"]]
    if e["status"] == "PA_DENIED":
        e["status"] = "PA_PENDING"
        touch(e)
    return success_object(serialize_pa(pa), 200)
