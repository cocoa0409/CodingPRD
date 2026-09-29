"""The two-branch advertising review fork and the posture gate in front of publication."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import assert_advertised_item
from test_helpers.factories import ice_bed_reading_payload
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_COOL_USER_ID,
    make_compliance_officer_headers,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
)


def _drafted_ad_on_a_labelled_cod_lot(api) -> dict:
    """A cased and labelled cod lot with one advertisement sitting in `DRAFT`."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    item = fixtures.draft_ad_item(api, counter_id, lot["id"])
    env.update({"lot": lot, "label": label, "ad_item": item})
    return env


def test_01_clearing_the_origin_branch_alone_leaves_the_advertisement_in_draft(api):
    """PRD §3.6: "Once `cool_review_status` is `COOL_CLEARED` **and** `claim_review_status` is
    `CLAIM_CLEARED`, the advertisement's `status` moves from `DRAFT` to `APPROVED` and it
    becomes eligible for publication; neither branch alone advances `status` out of `DRAFT`."

    Design: Difficulty/non_linear_state_machine/advertised_item_fork_join_two_review_branches
    """
    env = _drafted_ad_on_a_labelled_cod_lot(api)

    response = api.clear_ad_cool(
        env["ad_item"]["id"],
        {"decision": "CLEAR"},
        make_compliance_officer_headers(OFFICER_COOL_USER_ID),
    )
    item = validate_success(response, expected_status=200)

    assert_advertised_item(item)
    assert item["cool_review_status"] == "COOL_CLEARED"
    assert item["claim_review_status"] == "CLAIM_PENDING"
    assert item["status"] == "DRAFT"
    assert item["cool_reviewer_user_id"] == OFFICER_COOL_USER_ID


def test_02_the_origin_branch_composes_the_four_bar_separated_facts(api):
    """PRD §3.6: "That statement is the same four derived facts as the case label,
    concatenated in exactly this order and separated by a space, a vertical bar and a space:
    the `display_market_name`, then the `production_method_statement`, then the
    `origin_statement`, then the `frozen_disclosure_statement`."

    Design: Difficulty/non_linear_state_machine/advertised_item_fork_join_two_review_branches
    """
    env = _drafted_ad_on_a_labelled_cod_lot(api)

    item = fixtures.clear_ad_cool(api, env["ad_item"]["id"], officer_id=OFFICER_COOL_USER_ID)

    assert item["cool_statement"] == (
        "Atlantic Cod | WILD CAUGHT | Wild caught in US (WILD_LONGLINE) | FRESH - NEVER FROZEN"
    )


def test_03_the_second_branch_joins_and_approves_the_advertisement(api):
    """PRD §3.6: "The sustainability-claim branch is decided by a different
    `ComplianceOfficer` submitting a `decision` and optionally a `note`. Both dispositions
    require the advertisement to still be in `DRAFT` and require the acting `X-User-ID` to
    differ from the recorded `cool_reviewer_user_id`, per §2.1."

    Design: Difficulty/non_linear_state_machine/advertised_item_fork_join_two_review_branches
    """
    env = _drafted_ad_on_a_labelled_cod_lot(api)
    fixtures.clear_ad_cool(api, env["ad_item"]["id"], officer_id=OFFICER_COOL_USER_ID)

    response = api.clear_ad_claim(
        env["ad_item"]["id"],
        {"decision": "CLEAR"},
        make_compliance_officer_headers(OFFICER_CLAIM_USER_ID),
    )
    item = validate_success(response, expected_status=200)

    assert item["claim_review_status"] == "CLAIM_CLEARED"
    assert item["status"] == "APPROVED"
    assert item["claim_reviewer_user_id"] == OFFICER_CLAIM_USER_ID
    assert item["cool_reviewer_user_id"] == OFFICER_COOL_USER_ID


def test_04_publication_is_refused_while_the_counter_is_restricted(api):
    """PRD §3.6: "It requires the counter's `posture` to be exactly `OPEN` — a `RESTRICTED`
    counter fails with `ERR_COUNTER_RESTRICTED` and a `SUSPENDED` one with
    `ERR_COUNTER_SUSPENDED` — and it requires a `CaseLabel` for the advertisement's `lot_id`
    to exist with `status` `PUBLISHED`, because an advertisement may not stand in front of
    product that carries no label at the case."

    Design: Difficulty/cross_entity_state_dependency/ad_publish_blocked_by_counter_posture_restricted
    """
    env = _drafted_ad_on_a_labelled_cod_lot(api)
    counter_id = env["counter"]["id"]
    fixtures.clear_ad_cool(api, env["ad_item"]["id"], officer_id=OFFICER_COOL_USER_ID)
    fixtures.clear_ad_claim(api, env["ad_item"]["id"], officer_id=OFFICER_CLAIM_USER_ID)

    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    reading = api.create_ice_bed_reading(
        ice_bed_reading_payload(counter_id, 4, "2026-08-01T13:00:00Z", 6.0),
        make_seafood_manager_headers(counter_id),
    )
    validate_success(reading, expected_status=201)

    response = api.publish_ad_item(env["ad_item"]["id"], {}, make_merchandising_lead_headers())
    validate_error(response, ApiErrorId.ERR_COUNTER_RESTRICTED.value, expected_status=409)


def test_05_a_single_open_excursion_restricts_the_counter_and_freezes_the_advertisement(api):
    """PRD §2.6: "Otherwise, if `open_excursion_count` is at least 1, or `violation_points` is
    at least 6, the posture is `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/ad_publish_blocked_by_counter_posture_restricted
    """
    env = _drafted_ad_on_a_labelled_cod_lot(api)
    counter_id = env["counter"]["id"]
    fixtures.clear_ad_cool(api, env["ad_item"]["id"], officer_id=OFFICER_COOL_USER_ID)
    fixtures.clear_ad_claim(api, env["ad_item"]["id"], officer_id=OFFICER_CLAIM_USER_ID)

    fixtures.set_clock(api, "2026-08-01T14:00:00Z")
    validate_success(
        api.create_ice_bed_reading(
            ice_bed_reading_payload(counter_id, 4, "2026-08-01T13:00:00Z", 6.0),
            make_seafood_manager_headers(counter_id),
        ),
        expected_status=201,
    )
    response = api.publish_ad_item(env["ad_item"]["id"], {}, make_merchandising_lead_headers())
    validate_error(response, ApiErrorId.ERR_COUNTER_RESTRICTED.value, expected_status=409)

    counter = fixtures.read_counter(api, counter_id)
    assert counter["open_excursion_count"] == 1
    assert counter["posture"] == "RESTRICTED"
    assert fixtures.read_ad_item(api, env["ad_item"]["id"])["status"] == "APPROVED"
    assert fixtures.read_case_label(api, counter_id, env["label"]["id"])["status"] == "PUBLISHED"
    assert fixtures.read_lot(api, counter_id, env["lot"]["id"])["intake_status"] == "CASED"
