"""Selecting a remedy: the safety check runs before the ownership check.

PRD §3.5: "A candidate that fails both checks answers with the safety code, not the
mismatch code."
"""

from test_helpers import (
    ENGINEER_HEADERS,
    ERR_REMEDY_OPTION_MISMATCH,
    ERR_SAFETY_REMEDY_REQUIRED,
    create_family,
    create_field_action,
    create_remedy_option,
    read_field_action,
    validate_error,
)


def _build_world(api):
    """A safety recall with no options of its own beside a campaign that owns two."""
    family = create_family(
        api,
        family_code="FAM-E",
        name="Built-in Oven Platform",
        launch_date="2024-04-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=21000,
        reserve_cap_cents=90000000,
    )
    recall = create_field_action(
        api,
        family["id"],
        action_code="FA-E-SAFE",
        action_type="SAFETY_RECALL",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=2000,
        regulatory_notice_filed=True,
    )
    campaign = create_field_action(
        api,
        family["id"],
        action_code="FA-E-CAMP",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-06-01",
        affected_build_end_date="2025-08-31",
        affected_unit_count=5000,
        regulatory_notice_filed=False,
    )
    interim = create_remedy_option(
        api,
        campaign["id"],
        option_code="OPT-E-INT",
        remedy_class="INTERIM_REPAIR",
        parts_cost_cents=1500,
        labor_hours_centi=80,
        admin_cost_cents=400,
        expected_take_rate_bps=4000,
        is_engineering_approved=True,
    )
    permanent = create_remedy_option(
        api,
        campaign["id"],
        option_code="OPT-E-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=5000,
        labor_hours_centi=200,
        admin_cost_cents=900,
        expected_take_rate_bps=7000,
        is_engineering_approved=True,
    )
    return {
        "family": family,
        "recall": recall,
        "campaign": campaign,
        "interim": interim,
        "permanent": permanent,
    }


def test_safety_remedy_required_outranks_the_ownership_mismatch(api):
    """A foreign, non-permanent candidate on a recall answers with the safety code.

    PRD §3.5: "Two checks then run in a fixed order: first, if the action's
    `is_safety_recall` is true and the named candidate's `remedy_class` is anything
    other than `PERMANENT_REPAIR`, the request answers `ERR_SAFETY_REMEDY_REQUIRED`;
    second, if the candidate's `field_action_id` is not this action, the request
    answers `ERR_REMEDY_OPTION_MISMATCH`." PRD §2.9 states the same ordering: "Note
    that rung 17 is evaluated before this rung: a safety recall pointed at a
    non-permanent remedy that also belongs to a different field action answers with
    `ERR_SAFETY_REMEDY_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_remedy_required_outranks_remedy_option_mismatch_on_select
    """
    world = _build_world(api)
    assert world["recall"]["is_safety_recall"] is True

    response = api.select_remedy(
        ENGINEER_HEADERS,
        world["recall"]["id"],
        expected_field_action_version=1,
        remedy_option_id=world["interim"]["id"],
    )
    validate_error(response, ERR_SAFETY_REMEDY_REQUIRED, expected_status=422)


def test_a_foreign_permanent_repair_candidate_answers_the_mismatch_code(api):
    """With the safety rung satisfied only the ownership rung remains.

    PRD §3.5: "second, if the candidate's `field_action_id` is not this action, the
    request answers `ERR_REMEDY_OPTION_MISMATCH`." The candidate is a
    `PERMANENT_REPAIR`, so PRD §3.5's safety check passes and the option's ownership
    by the sibling campaign is the only remaining violation.

    Design: Difficulty/priority_pair_validation_conflict/safety_remedy_required_outranks_remedy_option_mismatch_on_select
    """
    world = _build_world(api)

    response = api.select_remedy(
        ENGINEER_HEADERS,
        world["recall"]["id"],
        expected_field_action_version=1,
        remedy_option_id=world["permanent"]["id"],
    )
    validate_error(response, ERR_REMEDY_OPTION_MISMATCH, expected_status=422)


def test_neither_refused_selection_mutates_the_recall(api):
    """A refused selection writes nothing and does not advance the version.

    PRD §3.5: "A successful selection writes `selected_remedy_option_id`, recomputes
    the selected option's `per_unit_expected_cents` and the action's
    `specific_accrual_cents`, and advances the action's `version` by 1." PRD §3.5 also
    fixes the starting point: "A new action starts with ... a null
    `selected_remedy_option_id`, a `specific_accrual_cents` of 0", and PRD §2.7 makes
    that version the OCC guard, so a rejected request must leave it untouched.

    Design: Difficulty/priority_pair_validation_conflict/safety_remedy_required_outranks_remedy_option_mismatch_on_select
    """
    world = _build_world(api)

    api.select_remedy(
        ENGINEER_HEADERS,
        world["recall"]["id"],
        expected_field_action_version=1,
        remedy_option_id=world["interim"]["id"],
    )
    api.select_remedy(
        ENGINEER_HEADERS,
        world["recall"]["id"],
        expected_field_action_version=1,
        remedy_option_id=world["permanent"]["id"],
    )

    recall = read_field_action(api, world["recall"]["id"])
    assert recall["selected_remedy_option_id"] is None
    assert recall["specific_accrual_cents"] == 0
    assert recall["version"] == 1
    assert recall["is_safety_recall"] is True
