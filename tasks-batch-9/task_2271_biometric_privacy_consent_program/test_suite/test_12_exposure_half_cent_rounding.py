"""The single rounding at the end of the exposure estimate.

Oregon's per-violation figure is chosen so the fully multiplied product lands
exactly on a half cent, which separates rounding half-up from truncation and from
banker's rounding.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    assert_cents,
    assert_program_state,
    assert_two_decimal_value,
    create_asset,
    create_consent,
    create_data_subject,
    create_oregon_jurisdiction,
    create_program,
    create_published_notice,
    create_published_policy,
    current_jurisdiction_version,
    draft_exposure_assessment,
    read_program,
    validate_success,
)


def _oregon_program_with_one_unanswered_solicitation(api):
    program = create_program(api)
    jurisdiction = create_oregon_jurisdiction(api, program["id"])
    policy = create_published_policy(api, program["id"], [jurisdiction["id"]])
    create_published_notice(
        api, program["id"], jurisdiction["id"], policy["id"], locales=["en"]
    )
    asset = create_asset(
        api,
        program["id"],
        jurisdiction["id"],
        target_status="ACTIVE",
        template_storage_location="tk-vault-or-01",
    )
    subject = create_data_subject(api, program["id"], jurisdiction["id"], "EMP-OR-0001")
    consent = create_consent(api, subject["id"], asset["id"])
    return {
        "program_id": program["id"],
        "jurisdiction_id": jurisdiction["id"],
        "policy_id": policy["id"],
        "asset_id": asset["id"],
        "subject_id": subject["id"],
        "consent_id": consent["id"],
    }


def test_a_half_cent_product_rounds_up_to_14585(api):
    """33336 x 0.50 x 1.25 x 0.70 is 14584.5 and must land on 14585.

    PRD §3.9: "The fully multiplied product is rounded half-up to zero decimal
    places — **exactly one rounding, applied to the product and never to any
    individual factor or intermediate**."

    Oregon's limited private right of action contributes the 0.50 factor, the one
    unanswered solicitation opens a consent gap and arms the 1.25 multiplier, and
    the 30-day cure window with a published in-scope policy takes 0.30 off.
    Truncation or banker's rounding would both yield 14584.

    Design: Difficulty/boundary_precision_check/pra_exposure_half_cent_rounds_up_to_14585_not_14584
    """
    ctx = _oregon_program_with_one_unanswered_solicitation(api)

    assessment = draft_exposure_assessment(api, ctx, variant="PER_VIOLATION_STACKED")

    assert_cents(assessment["base_cents"], 33336, "base_cents")
    assert_two_decimal_value(
        assessment["notice_gap_multiplier"], 1.25, "notice_gap_multiplier"
    )
    assert_two_decimal_value(assessment["cure_credit_pct"], 0.30, "cure_credit_pct")
    assert_cents(assessment["exposure_cents"], 14585, "exposure_cents")
    assert assessment["exposure_cents"] != 14584, (
        "14584 is what truncation or banker's rounding of 14584.5 would produce"
    )


def test_the_unanswered_solicitation_is_the_only_violation_unit_and_stays_uncommitted(api):
    """One negligent unit, no reckless unit, and nothing carried by the program.

    PRD §3.9: "The **negligent** bucket is every consent record on a scoped point
    whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED` — an individual
    who was asked and never answered, who must be asked again, or whose consent
    lapsed."

    PRD §3.9: "A `PrivacyOfficer` drafts an **exposure assessment** for one
    `program_id` and one `jurisdiction_id`, optionally linking it to the
    `incident_id` that prompted it (null for a routine posture assessment),
    choosing a `variant` of `PER_VIOLATION_STACKED` or `PER_SUBJECT_CAPPED`, and
    pinning `expected_jurisdiction_version` per §2.8."

    Design: Difficulty/boundary_precision_check/pra_exposure_half_cent_rounds_up_to_14585_not_14584
    """
    ctx = _oregon_program_with_one_unanswered_solicitation(api)
    version_before = current_jurisdiction_version(api, ctx["jurisdiction_id"])

    created = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": ctx["program_id"],
                "jurisdiction_id": ctx["jurisdiction_id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": version_before,
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )

    assert created["negligent_unit_count"] == 1
    assert created["reckless_unit_count"] == 0
    assert created["status"] == "DRAFT"
    assert created["finalized_by_user_id"] is None
    assert_cents(created["exposure_cents"], 14585, "exposure_cents")

    assert_program_state(read_program(api, ctx["program_id"]), pra_exposure_cents=0)
    assert current_jurisdiction_version(api, ctx["jurisdiction_id"]) == version_before + 1, (
        "drafting increments the state profile's own version"
    )
