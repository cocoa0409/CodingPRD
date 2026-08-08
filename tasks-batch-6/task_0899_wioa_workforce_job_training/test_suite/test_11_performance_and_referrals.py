"""WIOA performance summary (raw vs exclusion-adjusted credential rate, empty cohort)
and job-referral placement outcomes."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant, make_eligible, enroll,
    create_employer, setup_obligated_voucher,
    create_referral_payload,
    CM, BSR, ANY,
)


def _two_exiter_cohort(api):
    """P1: included exiter with a completed credential-bearing voucher.
    P2: exiter marked exit_exclusion=true, no credential. Returns la_id."""
    ctx = setup_obligated_voucher(api, authorized_cost_cents=100000)
    validate_success(api.complete_voucher(ctx["v_id"], {"credential_earned": True}, CM))
    validate_success(api.exit_participant(ctx["p_id"], CM))  # exit_exclusion default false
    # P2 in the same area: eligible, enrolled, exited WITH exclusion.
    p2 = intake_participant(api, ctx["la_id"], full_name="P Two")
    make_eligible(api, p2["id"])
    enroll(api, p2["id"])
    validate_success(api.exit_participant(p2["id"], CM, {"exit_exclusion": True}))
    return ctx["la_id"]


def test_performance_raw_and_adjusted_credential_rates_diverge(api):
    """PRD §3.8: "the `raw_credential_rate` is `credential_count` divided by
    `exiter_count`, and the `adjusted_credential_rate` is `credential_count` divided by
    `included_count`."

    Design: Difficulty/dual_variant_calc/performance_raw_vs_adjusted_credential_rate
    """
    la_id = _two_exiter_cohort(api)
    summary = validate_success(api.get_performance_summary(la_id, ANY))
    assert summary["raw_credential_rate"] == 0.5, summary
    assert summary["adjusted_credential_rate"] == 1.0, summary


def test_performance_cohort_counts(api):
    """PRD §3.8: "Among exiters, `excluded_count` is the number with `exit_exclusion` true,
    and the included exiters are those with `exit_exclusion` false, of which `included_count`
    is the number. `credential_count` is the number of included exiters whose
    `credential_attained` is true".

    Design: Difficulty/dual_variant_calc/performance_raw_vs_adjusted_credential_rate
    """
    la_id = _two_exiter_cohort(api)
    summary = validate_success(api.get_performance_summary(la_id, ANY))
    assert summary["exiter_count"] == 2, summary
    assert summary["excluded_count"] == 1, summary
    assert summary["included_count"] == 1, summary
    assert summary["credential_count"] == 1, summary


def test_performance_empty_cohort_credential_rates_zero(api):
    """PRD §3.8: "Each rate is rounded half-up to four decimal places, and whenever the
    relevant denominator is zero the rate is reported as exactly 0.0."

    Design: Difficulty/boundary_precision_check/performance_empty_cohort_zero_rate
    """
    area = create_area(api)
    summary = validate_success(api.get_performance_summary(area["id"], ANY))
    assert summary["exiter_count"] == 0, summary
    assert summary["raw_credential_rate"] == 0.0, summary
    assert summary["adjusted_credential_rate"] == 0.0, summary


def test_performance_empty_cohort_placement_rate_zero(api):
    """PRD §3.8: "The `placement_rate` is `placement_count` divided by `included_count`. ...
    whenever the relevant denominator is zero the rate is reported as exactly 0.0."

    Design: Difficulty/boundary_precision_check/performance_empty_cohort_zero_rate
    """
    area = create_area(api)
    summary = validate_success(api.get_performance_summary(area["id"], ANY))
    assert summary["placement_rate"] == 0.0, summary


def test_place_referral_for_not_enrolled_participant_rejected(api):
    """PRD §3.7: "Placement is rejected with `ERR_INVALID_STATE` unless the referral is
    `REFERRED`, and rejected with `ERR_PARTICIPANT_NOT_ENROLLED` unless the participant's
    enrollment is either `ENROLLED` or `EXITED`".

    Design: Corner/state_machines/place_not_enrolled_participant_returns_not_enrolled
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])  # NOT_ENROLLED
    emp = create_employer(api, area["id"])
    jr = validate_success(api.create_referral(p["id"], create_referral_payload(emp["id"]), CM), 201)
    resp = api.place_referral(jr["id"], BSR)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ENROLLED.value)


def test_reject_placed_referral_rejected(api):
    """PRD §3.7: "Rejecting a referral moves `status` to `REJECTED` (rejected with
    `ERR_INVALID_STATE` unless `REFERRED`)."

    Design: Corner/state_machines/reject_placed_referral_returns_invalid_state
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])
    enroll(api, p["id"])
    emp = create_employer(api, area["id"])
    jr = validate_success(api.create_referral(p["id"], create_referral_payload(emp["id"]), BSR), 201)
    validate_success(api.place_referral(jr["id"], BSR, {"placement_wage_cents_per_hour": 2500}))
    resp = api.reject_referral(jr["id"], BSR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
