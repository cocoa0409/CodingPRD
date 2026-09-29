"""Cyclic profile repair, the booking's two independent dimensions, docket rounds."""
from test_helpers import (
    ApiErrorId,
    FOLIO_RESORT_AMOUNT_CENTS,
    QUOTED_MANDATORY_FEE_CENTS,
    add_booking,
    add_complaint,
    add_inquiry,
    create_remediation_payload,
    read_booking,
    read_profile,
    read_property,
    remediate_profile,
    setup_deployed_profile,
    setup_quoted_booking,
    setup_single_fee_deployed_profile,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AGENT,
    COMPLIANCE,
    COMPLIANCE_2,
    LIAISON,
    LIAISON_2,
    REVENUE,
    advance_to_posted_folio,
)

UNDER_FLOOR_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "CHECKOUT",
}
HONEST_MAP = {"RESORT": 8972, "DESTINATION": 5980, "WIFI_PREMIUM": 2600}


def test_flagged_path_walks_back_to_deployed_through_remediation_and_sign_off(api):
    """DEPLOYED to FLAGGED to REMEDIATED and back to DEPLOYED, once round.

    PRD 3.3: "Confirmation is a `ComplianceOfficer` action and moves a profile
    `REMEDIATED → DEPLOYED`, closing the cycle
    `DEPLOYED → FLAGGED → REMEDIATED → DEPLOYED`. It requires the profile's
    recomputed `disclosure_score` to be at or above 80". PRD 3.3 on repair: "On
    success the profile's `confirmed_undisclosed_count` is reset to 0 ... its
    `remediation_round` increments by 1, its `disclosure_score` is recomputed
    from the new switches, and its `last_audited_at` is stamped."

    Design: Difficulty/non_linear_state_machine/disclosure_profile_deployed_flagged_remediated_redeployed_cycle
    """
    env = setup_deployed_profile(profile_overrides=UNDER_FLOOR_PROFILE)

    assert env["profile"]["status"] == "DEPLOYED"
    assert env["profile"]["disclosure_score"] == 58
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 58
    assert prop["disclosure_posture"] == "NON_COMPLIANT"

    flagged = validate_success(api.audit_profile(env["profile"]["id"], COMPLIANCE))
    assert flagged["status"] == "FLAGGED"
    assert flagged["disclosure_score"] == 58
    assert flagged["remediation_round"] == 0
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 0
    assert prop["disclosure_posture"] == "NON_COMPLIANT"
    assert prop["open_disclosure_obligation_count"] == 1

    remediated = remediate_profile(
        env, create_remediation_payload(disclosure_placement="RATE_DETAILS")
    )
    assert remediated["status"] == "REMEDIATED"
    assert remediated["disclosure_score"] == 90
    assert remediated["remediation_round"] == 1
    assert remediated["confirmed_undisclosed_count"] == 0
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 90
    assert prop["disclosure_posture"] == "COMPLIANT"
    assert prop["open_disclosure_obligation_count"] == 0

    redeployed = validate_success(
        api.confirm_remediation(env["profile"]["id"], COMPLIANCE)
    )
    assert redeployed["status"] == "DEPLOYED"
    assert redeployed["disclosure_score"] == 90
    # Signing off a repair is not itself a new round.
    assert redeployed["remediation_round"] == 1


def test_a_redeployed_path_refuses_both_a_second_sign_off_and_a_bare_repair(api):
    """Once back in DEPLOYED neither confirm-remediation nor remediate is legal.

    PRD 2.6 ranks "Target-state admissibility for the requested transition,
    including terminal-state lockdown — `ERR_INVALID_STATE` (HTTP 409)". PRD 3.3
    pins the two source states: "Confirmation is a `ComplianceOfficer` action and
    moves a profile `REMEDIATED → DEPLOYED`, closing the cycle
    `DEPLOYED → FLAGGED → REMEDIATED → DEPLOYED`" and "Remediation moves a
    profile `FLAGGED → REMEDIATED`".

    Design: Difficulty/non_linear_state_machine/disclosure_profile_deployed_flagged_remediated_redeployed_cycle
    """
    env = setup_deployed_profile(profile_overrides=UNDER_FLOOR_PROFILE)
    validate_success(api.audit_profile(env["profile"]["id"], COMPLIANCE))
    remediate_profile(
        env, create_remediation_payload(disclosure_placement="RATE_DETAILS")
    )
    validate_success(api.confirm_remediation(env["profile"]["id"], COMPLIANCE))

    validate_error(
        api.confirm_remediation(env["profile"]["id"], COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api.remediate_profile(
            env["profile"]["id"], create_remediation_payload(), REVENUE
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    profile = read_profile(env["profile"]["id"])
    assert profile["status"] == "DEPLOYED"
    assert profile["remediation_round"] == 1


def test_confirmation_advances_standing_only_when_the_quote_was_honest(api):
    """One confirm moves both dimensions; the silent booking moves only its stay.

    PRD 3.4: "Confirmation is where an honest booking path earns its clean
    standing: when the path's `first_quote_shows_total` is true, its
    `disclosure_placement` is either `FIRST_QUOTE` or `RATE_DETAILS`, and the
    booking's `quote_disclosure_gap_cents` is 0, then the same row's
    `disclosure_status` also transitions `PENDING_AUDIT → DISCLOSED`. If any of
    those three conditions fails, standing stays at `PENDING_AUDIT`."

    Design: Difficulty/non_linear_state_machine/booking_stay_and_disclosure_dimensions_advance_independently
    """
    env = setup_quoted_booking(
        booking_overrides={"disclosed_fee_amounts": HONEST_MAP}
    )
    honest = env["booking"]
    silent = add_booking(env)

    assert honest["quote_disclosure_gap_cents"] == 0
    assert silent["quote_disclosure_gap_cents"] == QUOTED_MANDATORY_FEE_CENTS
    assert honest["stay_status"] == "QUOTED"
    assert honest["disclosure_status"] == "PENDING_AUDIT"

    confirmed_honest = validate_success(api.confirm_booking(honest["id"], AGENT))
    assert confirmed_honest["stay_status"] == "CONFIRMED"
    assert confirmed_honest["disclosure_status"] == "DISCLOSED"

    confirmed_silent = validate_success(api.confirm_booking(silent["id"], AGENT))
    assert confirmed_silent["stay_status"] == "CONFIRMED"
    assert confirmed_silent["disclosure_status"] == "PENDING_AUDIT"


def test_a_checked_out_stay_can_still_be_driven_to_undisclosed_confirmed(api):
    """The stay dimension finishes while the disclosure dimension moves alone.

    PRD 3.4: "`stay_status` tracks stay progress through `QUOTED`, `CONFIRMED`,
    `IN_HOUSE` and `CHECKED_OUT`, and advances only through operator stay
    actions. `disclosure_status` tracks disclosure standing through
    `PENDING_AUDIT`, `DISCLOSED`, `DISPUTED`, `UNDISCLOSED_CONFIRMED` and
    `CURED`, and advances only through posture cascades, itemisation variance and
    complaint adjudication. Neither dimension constrains the other, and every
    combination of the two is reachable — a booking may sit at `QUOTED` with
    `DISPUTED` standing, or at `CHECKED_OUT` with `UNDISCLOSED_CONFIRMED`
    standing."

    Design: Difficulty/non_linear_state_machine/booking_stay_and_disclosure_dimensions_advance_independently
    """
    env = setup_quoted_booking(
        booking_overrides={"disclosed_fee_amounts": HONEST_MAP}
    )
    sibling = add_booking(env)
    validate_success(api.confirm_booking(sibling["id"], AGENT))
    env["booking"] = validate_success(api.confirm_booking(env["booking"]["id"], AGENT))
    assert env["booking"]["disclosure_status"] == "DISCLOSED"

    advance_to_posted_folio(env)
    assert env["booking"]["stay_status"] == "CHECKED_OUT"

    complaint = add_complaint(
        env,
        fee_code="RESORT",
        complaint_reason="MISSTATED_AMOUNT",
        narrative="The resort fee billed is two cents under what I was shown.",
    )
    validate_success(api.investigate_complaint(complaint["id"], COMPLIANCE))
    adjudicated = validate_success(
        api.substantiate_complaint(complaint["id"], COMPLIANCE_2)
    )

    assert adjudicated["refund_variant"] == "DISCLOSURE_GAP_DIFFERENTIAL"
    assert adjudicated["disputed_amount_cents"] == FOLIO_RESORT_AMOUNT_CENTS
    assert adjudicated["disclosed_amount_cents"] == 8972
    # The differential is floored at 0 because the guest was shown more.
    assert adjudicated["refund_entitlement_cents"] == 0
    validate_error(
        api.refund_complaint(complaint["id"], 1, AGENT),
        ApiErrorId.ERR_NO_REFUND_ENTITLEMENT,
    )

    booking = read_booking(env["booking"]["id"])
    assert booking["stay_status"] == "CHECKED_OUT"
    assert booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED"

    untouched = read_booking(sibling["id"])
    assert untouched["stay_status"] == "CONFIRMED"
    assert untouched["disclosure_status"] == "PENDING_AUDIT"

    profile = read_profile(env["profile"]["id"])
    assert profile["confirmed_undisclosed_count"] == 1
    assert profile["disclosure_score"] == 95
    assert profile["status"] == "DEPLOYED"

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 95
    assert prop["disclosure_posture"] == "COMPLIANT"
    assert prop["open_disclosure_obligation_count"] == 2
    assert prop["aggregate_disclosure_gap_cents"] == 0


def _docket_at_remediation_required(api, env):
    """A docket driven to REMEDIATION_REQUIRED over a single deployed path."""
    inquiry = add_inquiry(env)
    validate_success(
        api.draft_inquiry_response(
            inquiry["id"], "The operator's account of what each path displays.", LIAISON
        )
    )
    validate_success(api.submit_inquiry_response(inquiry["id"], LIAISON_2))
    return validate_success(
        api.require_inquiry_remediation(
            inquiry["id"], "Rebuild the OTA path so the total appears first.", ADMIN
        )
    )


def test_rejecting_a_remediation_submission_opens_a_second_round(api):
    """A rejection re-enters REMEDIATION_REQUIRED at round 2 without re-listing.

    PRD 3.8: "Rejecting the remediation closes the cycle. It is a
    `PlatformAdmin` action from `REMEDIATION_SUBMITTED` back to
    `REMEDIATION_REQUIRED`, carrying a `rejection_reason`. It records that
    reason, increments `remediation_round` by 1, transitions every profile id
    already in `flagged_profile_ids` whose status is `DEPLOYED` or `REMEDIATED`
    back to `FLAGGED` — the list itself is **not** re-appended, so it never
    accumulates duplicates". PRD 3.8 on premature submission: "a submission made
    while any of them is still `FLAGGED` is premature and rejected with
    `ERR_REMEDIATION_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/regulator_inquiry_remediation_rejection_round_trip_cycle
    """
    env = setup_single_fee_deployed_profile()
    profile_id = env["profile"]["id"]
    assert env["profile"]["disclosure_score"] == 100

    inquiry = _docket_at_remediation_required(api, env)
    assert inquiry["status"] == "REMEDIATION_REQUIRED"
    assert inquiry["remediation_round"] == 1
    assert inquiry["flagged_profile_ids"] == [profile_id]
    assert inquiry["exposure_cents"] == 0
    assert read_profile(profile_id)["status"] == "FLAGGED"
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 0
    assert prop["disclosure_posture"] == "NON_COMPLIANT"

    repaired = remediate_profile(env, create_remediation_payload())
    assert repaired["status"] == "REMEDIATED"
    assert repaired["remediation_round"] == 1
    assert repaired["disclosure_score"] == 100

    submitted = validate_success(
        api.submit_inquiry_remediation(
            inquiry["id"], "Every fee now lists its included services.", LIAISON
        )
    )
    assert submitted["status"] == "REMEDIATION_SUBMITTED"
    assert submitted["remediation_round"] == 1

    rejected = validate_success(
        api.reject_inquiry_remediation(
            inquiry["id"], "The itemisation still omits the included services.", ADMIN
        )
    )
    assert rejected["status"] == "REMEDIATION_REQUIRED"
    assert rejected["remediation_round"] == 2
    assert rejected["rejection_reason"] == (
        "The itemisation still omits the included services."
    )
    assert rejected["flagged_profile_ids"] == [profile_id]

    assert read_profile(profile_id)["status"] == "FLAGGED"
    prop_after = read_property(env["property"]["id"])
    assert prop_after["disclosure_posture"] == "NON_COMPLIANT"
    assert prop_after["open_disclosure_obligation_count"] == 2

    validate_error(
        api.submit_inquiry_remediation(
            inquiry["id"], "Resubmitting without repairing the path.", LIAISON
        ),
        ApiErrorId.ERR_REMEDIATION_INCOMPLETE,
    )


def test_acceptance_clears_the_flag_list_and_locks_the_docket(api):
    """Round 2 completes, acceptance empties the list, and the docket is terminal.

    PRD 3.8: "Acceptance is a `PlatformAdmin` action into the terminal
    `ACCEPTED`, taken from `REMEDIATION_SUBMITTED` ... It sets
    `flagged_profile_ids` to the empty array — acceptance **clears** the list
    without un-flagging anything, since remediation has already returned those
    paths to service — recomputes the property's
    `open_disclosure_obligation_count`, which falls by 1 for the closed docket".
    PRD 3.8 also pins the unreachable edge: "`WITHDRAWN` is **not** reachable
    from `REMEDIATION_SUBMITTED` and not from `ACCEPTED`."

    Design: Difficulty/non_linear_state_machine/regulator_inquiry_remediation_rejection_round_trip_cycle
    """
    env = setup_single_fee_deployed_profile()
    profile_id = env["profile"]["id"]
    inquiry = _docket_at_remediation_required(api, env)
    remediate_profile(env, create_remediation_payload())
    validate_success(
        api.submit_inquiry_remediation(inquiry["id"], "First repair filed.", LIAISON)
    )
    validate_success(
        api.reject_inquiry_remediation(inquiry["id"], "Not yet sufficient.", ADMIN)
    )

    second_repair = remediate_profile(env, create_remediation_payload())
    assert second_repair["status"] == "REMEDIATED"
    assert second_repair["remediation_round"] == 2
    assert second_repair["disclosure_score"] == 100

    resubmitted = validate_success(
        api.submit_inquiry_remediation(inquiry["id"], "Second repair filed.", LIAISON)
    )
    assert resubmitted["status"] == "REMEDIATION_SUBMITTED"
    assert resubmitted["remediation_round"] == 2

    accepted = validate_success(api.accept_inquiry(inquiry["id"], ADMIN))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["flagged_profile_ids"] == []

    prop = read_property(env["property"]["id"])
    assert prop["open_disclosure_obligation_count"] == 0
    assert prop["disclosure_posture"] == "COMPLIANT"
    assert prop["min_channel_disclosure_score"] == 100
    assert read_profile(profile_id)["status"] == "REMEDIATED"

    validate_error(
        api.withdraw_inquiry(inquiry["id"], "Regulator stood the docket down.", ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api.reject_inquiry_remediation(inquiry["id"], "Reopening the docket.", ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )
