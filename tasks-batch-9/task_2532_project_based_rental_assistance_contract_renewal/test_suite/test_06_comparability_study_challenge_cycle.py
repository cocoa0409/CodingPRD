"""The bounded challenge negotiation, supersession of a rejected filing, and the state
guard that outranks the comparable-rent ceiling at approval time."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_COMPARABLES,
    TEST_USERS,
    api_client,
    challenge_study_payload,
    create_comparable_payload,
    create_study_payload,
    decide_study_payload,
    setup_adjustment_elected,
    setup_study,
    setup_submitted_study,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]
CA_USER_ID = TEST_USERS["contract_administrator_user_id"]

DOGWOOD_ROW = {
    "address_label": "40 Dogwood Row",
    "raw_rent_cents": 110000,
    "adjustment_total_cents": 0,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}
MAPLE_COURT = {
    "address_label": "418 Maple Court",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}
LARKSPUR_WAY = {
    "address_label": "77 Larkspur Way",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}


def test_the_challenge_cycle_runs_three_rounds_and_the_fourth_attempt_is_refused():
    """"a study may be challenged at most three times, and a fourth attempt against a study
    whose `challenge_round` already equals 3 is refused with `ERR_MAX_CHALLENGE_ROUNDS`
    (HTTP 409) — that budget check runs after the state precondition and before any
    comparable is struck, so a refused challenge leaves every comparable intact".

    Design: Difficulty/non_linear_state_machine/rcs_submit_challenge_cycle_terminates_at_three_rounds
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    bundle = setup_submitted_study(
        ctx["case"]["id"], ctx["owner_headers"], REFERENCE_COMPARABLES
    )
    study_id = bundle["study"]["id"]
    comp_a, comp_b, comp_c = bundle["comparables"]
    assert bundle["study"]["state"] == "SUBMITTED"
    assert bundle["study"]["challenge_round"] == 0

    round_one = validate_success(
        api_client.challenge_study(
            study_id,
            challenge_study_payload(
                "Alder Court is a luxury conversion and is not comparable", [comp_a["id"]]
            ),
            CA_HEADERS,
        )
    )
    assert round_one["state"] == "CHALLENGED"
    assert round_one["challenge_round"] == 1
    validate_success(api_client.submit_study(study_id, ctx["owner_headers"]))

    round_two = validate_success(
        api_client.challenge_study(
            study_id,
            challenge_study_payload("Adjustment worksheet still unsigned", []),
            CA_HEADERS,
        )
    )
    assert round_two["challenge_round"] == 2, (
        "refiling after a challenge expressly does not reset the counter, got "
        f"{round_two['challenge_round']}"
    )
    validate_success(api_client.submit_study(study_id, ctx["owner_headers"]))

    round_three = validate_success(
        api_client.challenge_study(
            study_id,
            challenge_study_payload("Utility adjustment source not disclosed", []),
            CA_HEADERS,
        )
    )
    assert round_three["challenge_round"] == 3
    resubmitted = validate_success(
        api_client.submit_study(study_id, ctx["owner_headers"])
    )
    assert resubmitted["state"] == "SUBMITTED", (
        f"the third refiling is still lawful, got {resubmitted['state']}"
    )

    validate_error(
        api_client.challenge_study(
            study_id, challenge_study_payload("Fourth look", [comp_b["id"]]), CA_HEADERS
        ),
        ApiErrorId.ERR_MAX_CHALLENGE_ROUNDS.value,
        expected_status=409,
    )

    after = validate_success(api_client.get_study(study_id, CA_HEADERS))
    assert after["state"] == "SUBMITTED", (
        "the loop counter, not a state, terminates the negotiation, got "
        f"{after['state']}"
    )
    assert after["challenge_round"] == 3
    assert after["accepted_comparable_count"] == 2, (
        "the refused fourth challenge struck nothing, got "
        f"{after['accepted_comparable_count']}"
    )
    rows, meta = validate_paginated(
        api_client.list_study_comparables(study_id, CA_HEADERS, status="ACCEPTED")
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {comp_b["id"], comp_c["id"]}, (
        "the budget check ran before any comparable was touched"
    )


def test_the_first_strike_permanently_lowers_the_market_rent_and_the_study_stays_decidable():
    """A lawful challenge "sets `status` to `STRUCK` on every named comparable ... recomputes
    `accepted_comparable_count` and `estimated_market_rent_cents` over the remaining accepted
    comparables, writes that recomputed estimate onto the case's
    `comparable_market_rent_cents`, sets the case's `challenge_reviewer_user_id` to the
    challenging `X-User-ID`".

    Design: Difficulty/non_linear_state_machine/rcs_submit_challenge_cycle_terminates_at_three_rounds
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    bundle = setup_submitted_study(case_id, ctx["owner_headers"], REFERENCE_COMPARABLES)
    study_id = bundle["study"]["id"]
    comp_a, comp_b, comp_c = bundle["comparables"]
    assert bundle["study"]["estimated_market_rent_cents"] == 130200
    assert validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))[
        "comparable_market_rent_cents"
    ] == 130200

    challenged = validate_success(
        api_client.challenge_study(
            study_id,
            challenge_study_payload(
                "Alder Court is a luxury conversion and is not comparable", [comp_a["id"]]
            ),
            CA_HEADERS,
        )
    )
    assert challenged["estimated_market_rent_cents"] == 129200, (
        "(123600*2 + 140400*1) / 3 is 129200 once the weight-3 comparable is struck, got "
        f"{challenged['estimated_market_rent_cents']}"
    )
    assert challenged["accepted_comparable_count"] == 2
    assert challenged["last_challenge_reason"] == (
        "Alder Court is a luxury conversion and is not comparable"
    )

    struck_rows, _ = validate_paginated(
        api_client.list_study_comparables(study_id, CA_HEADERS, status="STRUCK")
    )
    assert [row["id"] for row in struck_rows] == [comp_a["id"]]
    assert struck_rows[0]["version"] == 2, (
        f"the struck comparable's version incremented, got {struck_rows[0]['version']}"
    )
    accepted_rows, _ = validate_paginated(
        api_client.list_study_comparables(study_id, CA_HEADERS, status="ACCEPTED")
    )
    assert {row["id"] for row in accepted_rows} == {comp_b["id"], comp_c["id"]}

    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["comparable_market_rent_cents"] == 129200, (
        "the challenge publishes the recomputed estimate onto the case, got "
        f"{case_after['comparable_market_rent_cents']}"
    )
    assert case_after["challenge_reviewer_user_id"] == CA_USER_ID

    validate_success(api_client.submit_study(study_id, ctx["owner_headers"]))
    validate_success(
        api_client.challenge_study(
            study_id, challenge_study_payload("Adjustment worksheet unsigned", []), CA_HEADERS
        )
    )
    refiled = validate_success(api_client.submit_study(study_id, ctx["owner_headers"]))
    assert refiled["estimated_market_rent_cents"] == 129200, (
        "a challenge that strikes nothing leaves the estimate where the first strike put "
        f"it, got {refiled['estimated_market_rent_cents']}"
    )
    assert refiled["challenge_round"] == 2

    accepted = validate_success(
        api_client.decide_study(study_id, decide_study_payload("ACCEPT"), CA_HEADERS)
    )
    assert accepted["state"] == "ACCEPTED", (
        "a study inside its round budget is still decidable, got " f"{accepted['state']}"
    )
    assert accepted["estimated_market_rent_cents"] == 129200
    final_case = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert final_case["comparable_market_rent_cents"] == 129200, (
        "acceptance does not change the published market rent, got "
        f"{final_case['comparable_market_rent_cents']}"
    )


def _case_needing_a_study_and_over_market() -> dict:
    """A mark-up-to-market case at RCS_IN_PROGRESS whose OCAF rent 120752 sits above the
    published comparable market rent 111500, with the only study REJECTED."""
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_1_MARK_UP_TO_MARKET", adjustment_method="OCAF"
    )
    bundle = setup_submitted_study(
        ctx["case"]["id"], ctx["owner_headers"], [DOGWOOD_ROW]
    )
    rejected = validate_success(
        api_client.decide_study(
            bundle["study"]["id"],
            decide_study_payload("REJECT", "Single comparable is insufficient support"),
            CA_HEADERS,
        )
    )
    ctx["study"] = rejected
    ctx["case"] = validate_success(
        api_client.get_renewal_case(ctx["case"]["id"], CA_HEADERS)
    )
    return ctx


def test_the_missing_accepted_study_outranks_the_over_market_rent_at_approval():
    """"If `rcs_required` is true and no accepted study exists, the request is refused with
    `ERR_RCS_NOT_ACCEPTED` (HTTP 409), and because that guard outranks the fiscal ceilings, a
    case that both lacks an accepted study and would breach its ceiling reports this code".

    Design: Difficulty/priority_pair_validation_conflict/approve_rents_state_guard_outranks_the_over_market_rent_ceiling
    """
    ctx = _case_needing_a_study_and_over_market()
    case = ctx["case"]
    assert case["rcs_required"] is True
    assert case["ocaf_rent_per_unit_cents"] == 120752
    assert case["comparable_market_rent_cents"] == 111500, (
        "110000 + 0 + 1500 is a whole dollar already, and rejection leaves the estimate "
        f"published on the case, got {case['comparable_market_rent_cents']}"
    )
    assert ctx["study"]["state"] == "REJECTED"

    validate_error(
        api_client.approve_rents(case["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_RCS_NOT_ACCEPTED.value,
        expected_status=409,
    )

    unchanged = validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))
    assert unchanged["rent_track_status"] == "RCS_IN_PROGRESS"
    assert unchanged["approved_rent_per_unit_cents"] is None
    assert unchanged["rents_approver_user_id"] is None

    owner = validate_success(api_client.get_owner(ctx["owner"]["id"], CA_HEADERS))
    assert owner["compliance_flag"] == "REVIEW_REQUIRED", (
        "the rejection reached across the aggregate boundary onto the owner, got "
        f"{owner['compliance_flag']}"
    )


def test_curing_the_state_violation_exposes_the_comparable_rent_ceiling():
    """"When `adjustment_method` is `OCAF`, the candidate is the case's stored
    `ocaf_rent_per_unit_cents`, and the ceiling is the case's `comparable_market_rent_cents`
    when `rcs_required` is true ... Where a ceiling exists and the candidate strictly exceeds
    it, the approval is refused rather than trimmed: the operating-cost-adjustment track
    reports `ERR_RENT_EXCEEDS_COMPARABLE`".

    Design: Difficulty/priority_pair_validation_conflict/approve_rents_state_guard_outranks_the_over_market_rent_ceiling
    """
    ctx = _case_needing_a_study_and_over_market()
    case_id = ctx["case"]["id"]
    first_study_id = ctx["study"]["id"]

    validate_error(
        api_client.approve_rents(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_RCS_NOT_ACCEPTED.value,
        expected_status=409,
    )

    successor = validate_success(
        api_client.create_study(
            create_study_payload(
                case_id,
                appraiser_name="Ardmore Appraisal Associates",
                supersedes_study_id=first_study_id,
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api_client.create_comparable(
            create_comparable_payload(successor["id"], **DOGWOOD_ROW),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    validate_success(api_client.submit_study(successor["id"], ctx["owner_headers"]))
    accepted = validate_success(
        api_client.decide_study(
            successor["id"], decide_study_payload("ACCEPT"), CA_HEADERS
        )
    )
    assert accepted["state"] == "ACCEPTED"
    assert validate_success(api_client.get_study(first_study_id, CA_HEADERS))[
        "state"
    ] == "SUPERSEDED"

    validate_error(
        api_client.approve_rents(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_RENT_EXCEEDS_COMPARABLE.value,
        expected_status=422,
    )

    after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert after["comparable_market_rent_cents"] == 111500, (
        "curing the state violation left the fiscal one untouched, got "
        f"{after['comparable_market_rent_cents']}"
    )
    assert after["ocaf_rent_per_unit_cents"] == 120752
    assert after["approved_rent_per_unit_cents"] is None, (
        "the over-market rent is refused rather than trimmed, got "
        f"{after['approved_rent_per_unit_cents']}"
    )
    assert after["rent_track_status"] == "RCS_IN_PROGRESS"


def test_superseding_a_study_links_the_pair_and_only_a_rejected_study_can_be_superseded():
    """"When present, it must name a study in state `REJECTED` whose `renewal_case_id` equals
    the new study's `renewal_case_id`; naming a study in any other state ... is refused with
    `ERR_TRANSITION_NOT_ALLOWED`. A lawful supersession moves the named predecessor from
    `REJECTED` to `SUPERSEDED`, increments its `version` by 1, and leaves the new study in
    `DRAFT` with its own `challenge_round` at 0".

    Design: Corner/endpoints/superseding_a_study_links_the_pair_and_only_a_rejected_study_can_be_superseded
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    owner_id = ctx["owner"]["id"]
    assert validate_success(api_client.get_owner(owner_id, CA_HEADERS))[
        "compliance_flag"
    ] == "OK"

    first = setup_study(
        case_id,
        ctx["owner_headers"],
        [MAPLE_COURT, LARKSPUR_WAY],
        appraiser_name="Whitlock Valuation Group",
    )
    study_one_id = first["study"]["id"]
    assert first["study"]["state"] == "DRAFT"
    assert first["study"]["challenge_round"] == 0

    validate_success(api_client.submit_study(study_one_id, ctx["owner_headers"]))
    challenged = validate_success(
        api_client.challenge_study(
            study_one_id,
            challenge_study_payload(
                "418 Maple Court is outside the submarket",
                [first["comparables"][0]["id"]],
            ),
            CA_HEADERS,
        )
    )
    assert challenged["challenge_round"] == 1
    assert challenged["accepted_comparable_count"] == 1
    validate_success(api_client.submit_study(study_one_id, ctx["owner_headers"]))
    rejected = validate_success(
        api_client.decide_study(
            study_one_id,
            decide_study_payload(
                "REJECT", "Appraiser did not adjust for the unit-mix difference"
            ),
            CA_HEADERS,
        )
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["last_challenge_reason"] == (
        "Appraiser did not adjust for the unit-mix difference"
    )
    assert validate_success(api_client.get_owner(owner_id, CA_HEADERS))[
        "compliance_flag"
    ] == "REVIEW_REQUIRED", "the rejection flagged the owner across the aggregate boundary"
    predecessor_version = rejected["version"]

    successor = validate_success(
        api_client.create_study(
            create_study_payload(
                case_id,
                appraiser_name="Ardmore Appraisal Associates",
                supersedes_study_id=study_one_id,
            ),
            ctx["owner_headers"],
        ),
        expected_status=201,
    )
    assert successor["state"] == "DRAFT"
    assert successor["challenge_round"] == 0, (
        "the successor does not inherit the predecessor's round, got "
        f"{successor['challenge_round']}"
    )
    assert successor["supersedes_study_id"] == study_one_id

    predecessor = validate_success(api_client.get_study(study_one_id, CA_HEADERS))
    assert predecessor["state"] == "SUPERSEDED", (
        "creating the successor drove the predecessor to its terminal state in the same "
        f"request, got {predecessor['state']}"
    )
    assert predecessor["version"] == predecessor_version + 1

    linked, linked_meta = validate_paginated(
        api_client.list_studies(
            CA_HEADERS, renewal_case_id=case_id, supersedes_study_id=study_one_id
        )
    )
    assert linked_meta["total_count"] == 1
    assert linked[0]["id"] == successor["id"], (
        "the filter resolves the link from the other direction"
    )

    validate_error(
        api_client.create_study(
            create_study_payload(
                case_id,
                appraiser_name="Third Appraiser LLC",
                supersedes_study_id=successor["id"],
            ),
            ctx["owner_headers"],
        ),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    assert validate_success(api_client.get_study(successor["id"], CA_HEADERS))[
        "state"
    ] == "DRAFT", "only a REJECTED study is supersedable, and the DRAFT one was untouched"
