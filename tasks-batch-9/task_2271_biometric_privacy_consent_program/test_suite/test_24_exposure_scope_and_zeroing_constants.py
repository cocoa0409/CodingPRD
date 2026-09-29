"""Which rows an exposure estimate prices, and which statutes price at zero.

One estimate filtered on three axes at once, and one estimate whose statute
removes the damages entirely while still reporting the violation counts.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    PRIVACY_OFFICER,
    assert_asset_state,
    assert_cents,
    assert_program_state,
    assert_two_decimal_value,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_program,
    create_published_notice,
    create_published_policy,
    current_jurisdiction_version,
    read_asset,
    read_program,
    validate_success,
)

WASHINGTON = {
    "state_code": "WA",
    "statute_name": "My Health My Data",
    "private_right_of_action": "LIMITED",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 730,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 50000,
    "per_violation_reckless_cents": 200000,
    "cure_period_days": 30,
}

TEXAS = {
    "state_code": "TX",
    "statute_name": "CUBI",
    "private_right_of_action": "NONE",
    "damages_model": "ACTUAL_ONLY",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 365,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 100000,
    "per_violation_reckless_cents": 500000,
    "cure_period_days": 0,
}


def _two_states_each_with_a_live_collection_point(api):
    """Illinois and Washington, both lawfully collecting from 1 August."""
    program = create_program(api)
    illinois = create_jurisdiction(api, program["id"], notice_lead_days=0)
    washington = create_jurisdiction(api, program["id"], **WASHINGTON)
    policy = create_published_policy(
        api, program["id"], [illinois["id"], washington["id"]]
    )
    create_published_notice(api, program["id"], illinois["id"], policy["id"])
    create_published_notice(
        api, program["id"], washington["id"], policy["id"], locales=["en"]
    )
    illinois_point = create_asset(
        api, program["id"], illinois["id"], target_status="ACTIVE"
    )
    washington_point = create_asset(
        api,
        program["id"],
        washington["id"],
        target_status="ACTIVE",
        template_storage_location="tk-vault-wa",
    )
    return {
        "program_id": program["id"],
        "illinois_id": illinois["id"],
        "washington_id": washington["id"],
        "illinois_point_id": illinois_point["id"],
        "washington_point_id": washington_point["id"],
    }


def test_an_estimate_prices_only_open_consents_on_its_own_states_live_points(api):
    """Three consent rows exist; exactly one is a violation unit in Illinois.

    PRD §3.9: "The scope of the estimate is those collection points of the
    assessment's program whose `jurisdiction_id` equals the assessment's and whose
    status is `ACTIVE` or `GATED`."

    PRD §3.9: "The **negligent** bucket is every consent record on a scoped point
    whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED` — an individual
    who was asked and never answered, who must be asked again, or whose consent
    lapsed."

    PRD §3.9: "A `DECLINED` record is never a violation in either bucket: a lawful
    decline is exactly what the statute contemplates."

    PRD §3.9: "Otherwise, under the `PER_VIOLATION_STACKED` variant — the plaintiff
    theory that each unconsented collection event is its own violation — `base_cents`
    is the negligent unit count multiplied by the state profile's
    `per_violation_negligent_cents`, plus the reckless unit count multiplied by its
    `per_violation_reckless_cents`; every violation row is priced independently, so
    one individual with both an unconsented collection and a post-revocation
    collection contributes the full sum with no per-person ceiling."

    PRD §3.9: "`notice_gap_multiplier` is 1.25 when at least one scoped collection
    point has a `consent_gap_count` greater than zero, and 1.00 otherwise."

    One unanswered Illinois solicitation prices at 100,000 cents, lifted by the
    notice-gap multiplier to 125,000; the Illinois decline and the Washington
    solicitation are both invisible to it.

    Design: Corner/calculations/pra_exposure_counts_only_open_consents_on_in_state_collectable_assets
    """
    ctx = _two_states_each_with_a_live_collection_point(api)
    unanswered_subject = create_data_subject(
        api, ctx["program_id"], ctx["illinois_id"], "EMP-0001"
    )
    refusing_subject = create_data_subject(
        api, ctx["program_id"], ctx["illinois_id"], "EMP-0002"
    )
    out_of_state_subject = create_data_subject(
        api, ctx["program_id"], ctx["washington_id"], "EMP-0003"
    )
    create_consent(api, unanswered_subject["id"], ctx["illinois_point_id"])
    create_consent(
        api, refusing_subject["id"], ctx["illinois_point_id"], target_status="DECLINED"
    )
    create_consent(api, out_of_state_subject["id"], ctx["washington_point_id"])

    estimate = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": ctx["program_id"],
                "jurisdiction_id": ctx["illinois_id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, ctx["illinois_id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )

    assert estimate["negligent_unit_count"] == 1
    assert estimate["reckless_unit_count"] == 0
    assert_cents(estimate["base_cents"], 100000, "base_cents")
    assert_two_decimal_value(
        estimate["notice_gap_multiplier"], 1.25, "notice_gap_multiplier"
    )
    assert_two_decimal_value(estimate["cure_credit_pct"], 0.00, "cure_credit_pct")
    assert_cents(estimate["exposure_cents"], 125000, "exposure_cents")
    assert estimate["status"] == "DRAFT"

    assert_asset_state(read_asset(api, ctx["illinois_point_id"]), consent_gap_count=1)


def test_a_state_without_statutory_damages_prices_at_zero_but_still_counts(api):
    """The units are counted first and the statutory constants zero them after.

    PRD §3.9: "If the state profile's `damages_model` is `ACTUAL_ONLY`, `base_cents`
    is zero regardless of variant — there are no statutory per-violation damages to
    stack."

    PRD §3.9: "A third factor comes straight from the statute: the
    private-right-of-action factor is 0.00 when `private_right_of_action` is `NONE`,
    0.50 when it is `LIMITED`, and 1.00 when it is `FULL`."

    PRD §2.6: "Otherwise, if `gated_asset_count` is greater than zero, or the
    program's `consent_gap_count` is greater than zero, or at least one open deletion
    obligation exists, `posture` becomes `RESTRICTED`."

    Both zeroing constants apply at once, yet the unanswered solicitation is still
    reported as a violation unit and still carries the notice-gap multiplier. The
    committed figure adds nothing to the ledger, so the program's restriction comes
    from the open consent gap alone.

    Design: Corner/calculations/actual_only_damages_and_no_private_right_of_action_zero_the_exposure
    """
    program = create_program(api)
    texas = create_jurisdiction(api, program["id"], **TEXAS)
    policy = create_published_policy(
        api, program["id"], [texas["id"]], release_language_included=False
    )
    create_published_notice(api, program["id"], texas["id"], policy["id"], locales=["en"])
    point = create_asset(
        api,
        program["id"],
        texas["id"],
        target_status="ACTIVE",
        system_category="ACCESS_CONTROL",
        modality="HAND_GEOMETRY",
        template_storage_location="door-vault-tx",
    )
    subject = create_data_subject(api, program["id"], texas["id"], "EMP-0001")
    create_consent(api, subject["id"], point["id"])

    estimate = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": texas["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, texas["id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )

    assert estimate["negligent_unit_count"] == 1
    assert_cents(estimate["base_cents"], 0, "base_cents")
    assert_two_decimal_value(
        estimate["notice_gap_multiplier"], 1.25, "notice_gap_multiplier"
    )
    assert_two_decimal_value(estimate["cure_credit_pct"], 0.00, "cure_credit_pct")
    assert_cents(estimate["exposure_cents"], 0, "exposure_cents")

    finalized = validate_success(
        api.transition_exposure_assessment(
            estimate["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )
    assert finalized["status"] == "FINAL"
    assert_program_state(
        read_program(api, program["id"]), pra_exposure_cents=0, posture="RESTRICTED"
    )
