"""Transitions gated on the state of a row the request never names.

Certifying reads the student's certificate status, and creating a Yellow Ribbon
award reads the agreement's status, both within the same state-gate band as the
target resource's own status.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_submitted_certification,
    create_agreement,
    read_agreement,
    read_certification,
    read_student,
)
from test_helpers.test_users import VA_HEADERS

REVERIFIED_COE_REFERENCE = "COE-2026-77120-R2"


# ─── Certify reads the student's certificate ───────────────────────────
def test_certify_is_refused_while_the_certificate_of_eligibility_is_expired(
    api, baseline
):
    """An expired certificate blocks certification of an otherwise ready submission.

    PRD: "Immediately after that, and within the same state-gate band, the
    student's `coe_status` must be `VERIFIED`, else `ERR_COE_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/certify_requires_verified_coe_on_the_student_row
    """
    scenario = build_submitted_certification(api, baseline)
    get_success_data(api.expire_coe(scenario.student_id, {}, VA_HEADERS))

    response = api.certify_certification(
        scenario.certification_id, {}, baseline.sup_headers
    )
    validate_error(response, e.ERR_COE_NOT_VERIFIED, 409)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "certified_by_official_id": None,
            "amount_basis": None,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == c.ENTITLEMENT_DAYS_GRANTED


def test_certify_succeeds_once_the_certificate_has_been_verified_again(api, baseline):
    """Re-verification reopens the gate and certification then protects the student.

    PRD: "Because a freshly certified certification necessarily has a null
    `tuition_payment_posted_on`, the third conjunct of the protection predicate is
    satisfied, and provided the certificate is verified and the window is still
    open the recomputed `benefit_payment_protected` becomes true."

    Design: Difficulty/cross_entity_state_dependency/certify_requires_verified_coe_on_the_student_row
    """
    scenario = build_submitted_certification(api, baseline)
    get_success_data(api.expire_coe(scenario.student_id, {}, VA_HEADERS))
    api.certify_certification(scenario.certification_id, {}, baseline.sup_headers)

    get_success_data(
        api.verify_coe(
            scenario.student_id,
            f.verify_coe_payload(
                verified_document_reference=REVERIFIED_COE_REFERENCE
            ),
            baseline.sco_headers,
        )
    )
    certified = get_success_data(
        api.certify_certification(scenario.certification_id, {}, baseline.sup_headers)
    )
    a.assert_fields(
        certified,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "amount_basis": c.AMOUNT_BASIS_AS_CERTIFIED,
            "entitlement_days_charged": 110,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {"entitlement_days_remaining": 970, "benefit_payment_protected": True},
    )


# ─── Award creation reads the agreement's status ───────────────────────
def _certified_term_and_a_closed_agreement(api, baseline):
    """Certify a term, then close the agreement and keep its post-close version."""
    scenario = build_certified_certification(api, baseline)
    agreement_id, _version = create_agreement(api, baseline.sup_headers)
    closed = get_success_data(
        api.close_yellow_ribbon_agreement(agreement_id, {}, baseline.sup_headers)
    )
    return scenario, agreement_id, closed["version"]


def test_an_award_against_a_closed_agreement_is_refused_on_its_status(api, baseline):
    """A current version number does not buy access to a closed agreement.

    PRD: "`CLOSED` is terminal, and thereafter any attempt to create a new award
    against the agreement is refused with `ERR_AGREEMENT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/yellow_ribbon_award_requires_active_agreement_row
    """
    scenario, agreement_id, closed_version = _certified_term_and_a_closed_agreement(
        api, baseline
    )

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            scenario.certification_id, agreement_id, closed_version
        ),
        baseline.sup_headers,
    )
    validate_error(response, e.ERR_AGREEMENT_CLOSED, 409)


def test_the_refused_award_leaves_the_pool_and_the_certification_alone(api, baseline):
    """Nothing is debited and the certification keeps its unmet gap.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/yellow_ribbon_award_requires_active_agreement_row
    """
    scenario, agreement_id, closed_version = _certified_term_and_a_closed_agreement(
        api, baseline
    )
    api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            scenario.certification_id, agreement_id, closed_version
        ),
        baseline.sup_headers,
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "status": c.AGREEMENT_STATUS_CLOSED,
            "pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS,
            "participant_count": 0,
        },
    )
    awards = get_success_data(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"agreement_id": agreement_id}
        )
    )
    assert awards == [], f"No award may exist on the closed agreement: {awards}"

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_CERTIFIED, "yr_gap_cents": 160000},
    )
