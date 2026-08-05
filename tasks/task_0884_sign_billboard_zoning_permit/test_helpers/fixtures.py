"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors, not confusing assertion failures. Every Applicant/Inspector
action threads the actual entity id through make_*_headers() so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_parcel_payload, create_applicant_payload, create_inspector_payload,
    create_application_payload, create_variance_payload, create_billboard_payload,
    create_lease_payload, create_non_conforming_payload, create_violation_payload,
    create_inspection_payload,
)
from .test_users import (
    make_applicant_headers, make_inspector_headers,
    make_planner_headers, make_zoningboard_headers,
)
from .constants import DEFAULT_WALL_FEE_CENTS, DIGITAL_FACE_FEE_CENTS, BASE_FACE_FEE_CENTS


# ─── Tier 0: Base creators ───────────────────────────────────────────────────
def create_parcel(api, **overrides):
    return get_success_data(
        api.create_parcel(create_parcel_payload(**overrides), make_planner_headers())
    )


def create_applicant(api, **overrides):
    return get_success_data(
        api.create_applicant(create_applicant_payload(**overrides), make_planner_headers())
    )


def create_inspector(api, **overrides):
    return get_success_data(
        api.create_inspector(create_inspector_payload(**overrides), make_planner_headers())
    )


def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, make_planner_headers()))


# ─── Tier 1: Application state progression ───────────────────────────────────
def create_application(api, parcel_id, applicant_id, **overrides):
    return get_success_data(
        api.create_application(
            create_application_payload(parcel_id, applicant_id, **overrides),
            make_applicant_headers(applicant_id),
        )
    )


def submit_application(api, application_id, applicant_id):
    return get_success_data(
        api.submit_application(application_id, make_applicant_headers(applicant_id))
    )


def review_application(api, application_id, review_type, outcome):
    return get_success_data(
        api.review_application(
            application_id,
            {"review_type": review_type, "outcome": outcome},
            make_planner_headers(),
        )
    )


def decide_application(api, application_id, decision):
    return get_success_data(
        api.decide_application(application_id, {"decision": decision}, make_planner_headers())
    )


def create_submitted_application(api, parcel=None, applicant=None, **app_overrides):
    """Parcel + applicant + application walked DRAFT -> SUBMITTED.
    Returns (parcel, applicant, application)."""
    if parcel is None:
        parcel = create_parcel(api)
    if applicant is None:
        applicant = create_applicant(api)
    app = create_application(api, parcel["id"], applicant["id"], **app_overrides)
    app = submit_application(api, app["id"], applicant["id"])
    return parcel, applicant, app


def create_approved_application(api, parcel=None, applicant=None, **app_overrides):
    """Conforming application walked DRAFT -> SUBMITTED -> (DIMENSIONAL PASS, OVERLAY
    CLEARED) -> APPROVED. Returns (parcel, applicant, application)."""
    parcel, applicant, app = create_submitted_application(api, parcel, applicant, **app_overrides)
    review_application(api, app["id"], "DIMENSIONAL", "PASS")
    review_application(api, app["id"], "OVERLAY", "CLEARED")
    app = decide_application(api, app["id"], "APPROVE")
    return parcel, applicant, app


# ─── Tier 2: Variances ───────────────────────────────────────────────────────
def file_variance(api, application_id, applicant_id, kind, requested_value=None,
                  justification="hardship"):
    return get_success_data(
        api.create_variance(
            create_variance_payload(application_id, kind, requested_value, justification),
            make_applicant_headers(applicant_id),
        )
    )


def recommend_variance(api, variance_id, recommendation="RECOMMEND_APPROVE",
                       planner_user_id="planner-1"):
    return get_success_data(
        api.recommend_variance(
            variance_id, {"recommendation": recommendation},
            make_planner_headers(planner_user_id),
        )
    )


def decide_variance(api, variance_id, decision, granted_value=None,
                    board_user_id="board-1"):
    payload = {"decision": decision}
    if granted_value is not None:
        payload["granted_value"] = granted_value
    return get_success_data(
        api.decide_variance(variance_id, payload, make_zoningboard_headers(board_user_id))
    )


def setup_partial_area_variance_approved(api):
    """Dual-variant fee scenario: parcel max_sign_area_sqft=100, allowed DIGITAL_DISPLAY;
    MONUMENT application requesting 150 sqft / EXTERNAL (provisional fee from 150); an AREA
    variance is granted at 100 (partial relief); DIMENSIONAL PASS (effective 100 <= 100)
    and OVERLAY CLEARED; application APPROVED (approved_area_sqft frozen to 100).
    Returns (parcel, applicant, application)."""
    parcel = create_parcel(api, max_sign_area_sqft=100, allowed_illumination="DIGITAL_DISPLAY",
                           max_signs=5)
    applicant = create_applicant(api)
    app = create_application(api, parcel["id"], applicant["id"], sign_type="MONUMENT",
                             requested_area_sqft=150, requested_height_ft=20,
                             requested_setback_ft=15, requested_illumination="EXTERNAL")
    app = submit_application(api, app["id"], applicant["id"])
    var = file_variance(api, app["id"], applicant["id"], "AREA", requested_value=150)
    recommend_variance(api, var["id"])
    decide_variance(api, var["id"], "GRANT", granted_value=100)
    review_application(api, app["id"], "DIMENSIONAL", "PASS")
    review_application(api, app["id"], "OVERLAY", "CLEARED")
    app = decide_application(api, app["id"], "APPROVE")
    return parcel, applicant, app


def setup_variance_under_review(api, parcel=None, applicant=None, recommender_id="planner-1"):
    """A variance filed against a submitted MONUMENT/150/EXTERNAL application and recommended
    (SUBMITTED -> UNDER_REVIEW). Returns (parcel, applicant, application, variance)."""
    if parcel is None:
        parcel = create_parcel(api, max_sign_area_sqft=100)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, sign_type="MONUMENT", requested_area_sqft=150,
        requested_height_ft=20, requested_setback_ft=15, requested_illumination="EXTERNAL")
    var = file_variance(api, app["id"], applicant["id"], "AREA", requested_value=150)
    var = recommend_variance(api, var["id"], planner_user_id=recommender_id)
    return parcel, applicant, app, var


# ─── Tier 3: Permits ─────────────────────────────────────────────────────────
def issue_permit(api, application_id, expected_application_version):
    return get_success_data(
        api.create_permit(
            {"application_id": application_id,
             "expected_application_version": expected_application_version},
            make_planner_headers(),
        )
    )


def create_issued_permit(api, parcel=None, applicant=None, **app_overrides):
    """Approved application + issued permit (status ISSUED).
    Returns (parcel, applicant, application, permit)."""
    parcel, applicant, app = create_approved_application(api, parcel, applicant, **app_overrides)
    permit = issue_permit(api, app["id"], app["version"])
    return parcel, applicant, app, permit


def pay_permit(api, permit_id, applicant_id, amount_cents=DEFAULT_WALL_FEE_CENTS):
    return get_success_data(
        api.pay_permit(permit_id, {"amount_cents": amount_cents},
                       make_applicant_headers(applicant_id))
    )


def create_active_permit(api, parcel=None, applicant=None,
                         amount_cents=DEFAULT_WALL_FEE_CENTS, **app_overrides):
    """Approved application + issued + paid permit (status ACTIVE, one parcel slot consumed).
    Returns (parcel, applicant, application, permit)."""
    parcel, applicant, app, permit = create_issued_permit(api, parcel, applicant, **app_overrides)
    permit = pay_permit(api, permit["id"], applicant["id"], amount_cents=amount_cents)
    return parcel, applicant, app, permit


def revoke_permit(api, permit_id):
    return get_success_data(api.revoke_permit(permit_id, make_planner_headers()))


# ─── Tier 4: Inspections ─────────────────────────────────────────────────────
def schedule_inspection(api, permit_id, inspector_id, scheduled_start, scheduled_end):
    return get_success_data(
        api.create_inspection(
            create_inspection_payload(permit_id, inspector_id, scheduled_start, scheduled_end),
            make_planner_headers(),
        )
    )


def create_permit_with_scheduled_inspection(api, inspector=None,
                                            scheduled_start="2026-06-01T10:00:00Z",
                                            scheduled_end="2026-06-01T11:00:00Z"):
    """ACTIVE permit + one SCHEDULED inspection.
    Returns (parcel, applicant, application, permit, inspector, inspection)."""
    parcel, applicant, app, permit = create_active_permit(api)
    if inspector is None:
        inspector = create_inspector(api)
    inspection = schedule_inspection(api, permit["id"], inspector["id"],
                                     scheduled_start, scheduled_end)
    return parcel, applicant, app, permit, inspector, inspection


# ─── Tier 5: Violations ──────────────────────────────────────────────────────
def cite_violation(api, parcel_id, kind="NO_PERMIT", permit_id=None):
    return get_success_data(
        api.create_violation(
            create_violation_payload(parcel_id, kind, permit_id), make_planner_headers()
        )
    )


def setup_escalatable_permit_violation(api,
                                       scheduled_start="2026-06-01T10:00:00Z",
                                       scheduled_end="2026-06-01T11:00:00Z",
                                       escalate_clock="2026-07-01T00:00:00Z"):
    """ACTIVE permit + one SCHEDULED inspection + one OPEN violation linked to the permit,
    with the clock advanced strictly past the violation cure_deadline so escalation is legal.
    Returns (parcel, applicant, permit, inspector, inspection, violation)."""
    (parcel, applicant, app, permit, inspector,
     inspection) = create_permit_with_scheduled_inspection(api, scheduled_start=scheduled_start,
                                                            scheduled_end=scheduled_end)
    violation = cite_violation(api, parcel["id"], kind="EXCEEDS_PERMIT", permit_id=permit["id"])
    set_clock(api, escalate_clock)
    return parcel, applicant, permit, inspector, inspection, violation


# ─── Tier 6: Non-conforming registry ─────────────────────────────────────────
def register_non_conforming(api, parcel_id, original_value_cents=1000000,
                            amortization_period_years=5, description="legacy sign"):
    return get_success_data(
        api.create_non_conforming(
            create_non_conforming_payload(parcel_id, original_value_cents,
                                          amortization_period_years, description),
            make_planner_headers(),
        )
    )


def list_non_conforming_for_parcel(api, parcel_id):
    resp = api.list_non_conforming(make_planner_headers(), params={"parcel_id": parcel_id})
    return get_success_data(resp)


# ─── Tier 7: Billboards & leases ─────────────────────────────────────────────
def create_billboard(api, parcel=None, operator=None, face_count=1, is_digital=False):
    if parcel is None:
        parcel = create_parcel(api)
    if operator is None:
        operator = create_applicant(api)
    bb = get_success_data(
        api.create_billboard(
            create_billboard_payload(parcel["id"], operator["id"], face_count, is_digital),
            make_applicant_headers(operator["id"]),
        )
    )
    return parcel, operator, bb


def _default_registration_fee(face_count, is_digital):
    per_face = DIGITAL_FACE_FEE_CENTS if is_digital else BASE_FACE_FEE_CENTS
    return per_face * face_count


def register_billboard(api, billboard_id, operator_id, amount_cents):
    return get_success_data(
        api.register_billboard(billboard_id, {"amount_cents": amount_cents},
                               make_applicant_headers(operator_id))
    )


def create_registered_billboard(api, parcel=None, operator=None, face_count=1,
                                is_digital=False, amount_cents=None):
    """UNREGISTERED billboard registered to REGISTERED (registration_expires_at = clock + 365d).
    Returns (parcel, operator, billboard) with billboard['version'] current after registration."""
    parcel, operator, bb = create_billboard(api, parcel, operator, face_count, is_digital)
    if amount_cents is None:
        amount_cents = _default_registration_fee(face_count, is_digital)
    bb = register_billboard(api, bb["id"], operator["id"], amount_cents)
    return parcel, operator, bb


def get_billboard(api, billboard_id):
    return get_success_data(api.get_billboard(billboard_id, make_planner_headers()))


def create_lease(api, billboard_id, operator_id, start_date, end_date,
                 expected_billboard_version, lessee_name="Ad Buyer"):
    return get_success_data(
        api.create_lease(
            create_lease_payload(billboard_id, expected_billboard_version, start_date,
                                 end_date, lessee_name),
            make_applicant_headers(operator_id),
        )
    )


def create_registered_billboard_with_lease(api, face_count=1, is_digital=False,
                                           start_date="2026-06-01T00:00:00Z",
                                           end_date="2026-07-01T00:00:00Z"):
    """Registered billboard + one ACTIVE lease over [start_date, end_date).
    Returns (parcel, operator, billboard_after_lease, lease). billboard_after_lease['version']
    reflects the version bump from the lease create."""
    parcel, operator, bb = create_registered_billboard(api, face_count=face_count,
                                                        is_digital=is_digital)
    lease = create_lease(api, bb["id"], operator["id"], start_date, end_date, bb["version"])
    bb_after = get_billboard(api, bb["id"])
    return parcel, operator, bb_after, lease
