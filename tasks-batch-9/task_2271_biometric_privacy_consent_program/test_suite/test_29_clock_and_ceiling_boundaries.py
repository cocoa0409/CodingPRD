"""Two inclusive boundaries: the statutory lead time and the board's ceiling.

One second before eligibility the solicitation is refused and at the exact instant it
succeeds; two individually affordable estimates cannot both be committed.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_asset_state,
    assert_cents,
    assert_instant_equals,
    assert_is_null,
    assert_pagination,
    assert_program_state,
    baseline_with_active_asset,
    consent_payload,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_program,
    create_published_notice,
    create_published_policy,
    current_jurisdiction_version,
    read_asset,
    read_assessment,
    read_program,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ILLINOIS_CHEAPER = {
    "state_code": "IL",
    "statute_name": "BIPA",
    "private_right_of_action": "FULL",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 1095,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 20000,
    "per_violation_reckless_cents": 100000,
    "cure_period_days": 0,
}

WASHINGTON_CHEAPER = {
    "state_code": "WA",
    "statute_name": "My Health My Data",
    "private_right_of_action": "FULL",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 730,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 8000,
    "per_violation_reckless_cents": 40000,
    "cure_period_days": 0,
}

BOARD_CEILING_CENTS = 30000


def test_a_solicitation_one_second_early_is_refused_and_one_at_the_instant_stands(api):
    """The fourteen-day lead is inclusive at its lower edge.

    PRD §3.6: "The current logical clock must be at or after the covering published
    packet's `consent_eligible_from`. Soliciting inside the statutory lead time is
    rejected with `ERR_NOTICE_LEAD_NOT_MET`."

    PRD §3.6: "A successful solicitation lands the record in `SOLICITED`, copies the
    collection point's `pinned_policy_id` into the record's own `pinned_policy_id`, sets
    `solicitation_round` to 1, and leaves `signed_at`, `pinned_retention_days`,
    `record_retention_until`, `decline_reason` and `revocation_reason` null."

    PRD §3.6: "It then recomputes the point's `consent_gap_count`, the program's
    `consent_gap_count` and the program's `posture` — a solicited-but-unanswered record
    is itself a gap, so soliciting consent at an otherwise clean program moves it to
    `RESTRICTED` until the individual answers."

    The two attempts are the identical request one second apart, so nothing but the
    clock can explain the difference; the refused one writes no consent row at all.

    Design: Corner/validations/consent_solicited_exactly_at_consent_eligible_from_succeeds
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    assert_instant_equals(
        ctx["notice"]["consent_eligible_from"],
        "2026-08-15T00:00:00.000Z",
        "consent_eligible_from",
    )
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")

    set_clock(api, "2026-08-14T23:59:59Z")

    too_early = api.create_consent_record(
        consent_payload(subject["id"], ctx["asset_id"]), HR_ADMIN
    )
    validate_error(too_early, ApiErrorId.NOTICE_LEAD_NOT_MET)
    _rows, meta = validate_paginated(
        api.list_consent_records(HR_ADMIN, {"data_subject_id": subject["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)

    set_clock(api, "2026-08-15T00:00:00Z")

    solicited = validate_success(
        api.create_consent_record(consent_payload(subject["id"], ctx["asset_id"]), HR_ADMIN),
        expected_status=201,
    )

    assert solicited["status"] == "SOLICITED"
    assert solicited["solicitation_round"] == 1
    assert solicited["pinned_policy_id"] == ctx["policy_id"]
    assert_is_null(solicited["signed_at"], "signed_at on a solicited record")

    assert_asset_state(read_asset(api, ctx["asset_id"]), consent_gap_count=1)
    assert_program_state(read_program(api, ctx["program_id"]), consent_gap_count=1, posture="RESTRICTED")


def test_two_individually_affordable_estimates_cannot_both_be_committed(api):
    """The ceiling is tested against the running total, not against one estimate.

    PRD §3.9: "Four preconditions guard it: the assessment must be `DRAFT`; the acting
    `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`;
    no other assessment for the same pairing of `program_id` and `jurisdiction_id` may
    already be `FINAL`, else `ERR_ASSESSMENT_ALREADY_FINAL`; and the program's existing
    `pra_exposure_cents` plus this assessment's `exposure_cents` must not exceed
    `exposure_ceiling_cents`, else `ERR_EXPOSURE_CAP_EXCEEDED`."

    PRD §3.9: "Finalization stamps `finalized_by_user_id` from the acting `X-User-ID`,
    adds `exposure_cents` into the program's `pra_exposure_cents`, recomputes the
    program's `posture` (a program whose carried exposure reaches eighty percent of its
    ceiling freezes, per §2.6), and increments the program's `version` by 1."

    PRD §2.6: "Otherwise, if `exposure_ceiling_cents` is greater than zero and carried
    exposure has reached at least eighty percent of it, `posture` becomes `FROZEN`. The
    comparison is evaluated entirely in integers — one hundred times `pra_exposure_cents`
    against eighty times `exposure_ceiling_cents` — so no floating-point drift is
    possible and exactly eighty percent does freeze the program."

    Each estimate is comfortably inside the 30,000-cent ceiling on its own — 25,000 in
    Illinois and 10,000 in Washington — but 35,000 together. The refused second
    finalization leaves the accumulator exactly where the first one put it, and the
    program is already frozen at 25,000 because that is 83 percent of the ceiling.

    Design: Corner/validations/two_individually_affordable_assessments_breach_the_ceiling_in_aggregate
    """
    program = create_program(api, exposure_ceiling_cents=BOARD_CEILING_CENTS)
    illinois = create_jurisdiction(api, program["id"], **ILLINOIS_CHEAPER)
    washington = create_jurisdiction(api, program["id"], **WASHINGTON_CHEAPER)
    policy = create_published_policy(api, program["id"], [illinois["id"], washington["id"]])
    create_published_notice(
        api, program["id"], illinois["id"], policy["id"], locales=["en"]
    )
    create_published_notice(
        api, program["id"], washington["id"], policy["id"], locales=["en"]
    )
    illinois_point = create_asset(api, program["id"], illinois["id"], target_status="ACTIVE")
    washington_point = create_asset(
        api,
        program["id"],
        washington["id"],
        target_status="ACTIVE",
        system_category="ACCESS_CONTROL",
        modality="HAND_GEOMETRY",
        template_storage_location="door-vault-wa",
    )
    illinois_subject = create_data_subject(api, program["id"], illinois["id"], "EMP-0001")
    washington_subject = create_data_subject(api, program["id"], washington["id"], "EMP-0002")
    create_consent(api, illinois_subject["id"], illinois_point["id"])
    create_consent(api, washington_subject["id"], washington_point["id"])

    illinois_estimate = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": illinois["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(api, illinois["id"]),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    washington_estimate = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": washington["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(api, washington["id"]),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert_cents(illinois_estimate["exposure_cents"], 25000, "Illinois exposure_cents")
    assert_cents(washington_estimate["exposure_cents"], 10000, "Washington exposure_cents")

    committed = validate_success(
        api.transition_exposure_assessment(
            illinois_estimate["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )
    assert committed["status"] == "FINAL"
    assert_program_state(
        read_program(api, program["id"]), pra_exposure_cents=25000, posture="FROZEN"
    )

    refused = api.transition_exposure_assessment(
        washington_estimate["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
    )

    validate_error(refused, ApiErrorId.EXPOSURE_CAP_EXCEEDED)

    unchanged = read_assessment(api, washington_estimate["id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["finalized_by_user_id"], "finalized_by_user_id after a refused commit")
    assert_program_state(
        read_program(api, program["id"]), pra_exposure_cents=25000, posture="FROZEN"
    )
