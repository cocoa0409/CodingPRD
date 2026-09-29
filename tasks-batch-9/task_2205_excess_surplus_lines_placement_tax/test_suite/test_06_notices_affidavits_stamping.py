"""Notices, affidavits and the stamping office: three of the policy's four
independent state dimensions, and the segregation of duties on signing.
"""

from test_helpers import (
    ERR_AFFIDAVIT_COUNT_MISMATCH,
    ERR_INVALID_STATE,
    ERR_NOTICES_INCOMPLETE,
    ERR_NOTICES_NOT_AFFIXED,
    ERR_REJECTION_REASON_REQUIRED,
    ERR_SEGREGATION_OF_DUTIES,
    COMPLIANCE_OFFICER_ANDERS,
    COMPLIANCE_OFFICER_BRIGID,
    COMPLIANCE_OFFICER_BRIGID_ID,
    STATE_REGULATOR_TX,
    TAX_FILER_NINA,
    assert_policy_dimensions,
    validate_error,
    validate_success,
)


def test_affixing_the_required_notices_advances_only_the_compliance_dimension(
    policy_world,
):
    """One dimension moves and the other three stand still.

    PRD 3.6: "On success the policy's `notice_codes_affixed` becomes the supplied
    array de-duplicated and sorted in ascending ASCII order, and the policy's
    `version` increments."

    Design: Corner/state_machines/affixing_the_required_notices_advances_only_the_compliance_dimension
    """
    world = policy_world
    before = world.get_policy()
    assert_policy_dimensions(
        before,
        status="ISSUED",
        compliance_status="PENDING_NOTICES",
        tax_status="UNCALCULATED",
        stamping_status="PENDING",
    )
    assert before["notice_codes_affixed"] == []

    after = world.affix_notices(["TX-SL-1", "TX-SL-2"])
    assert_policy_dimensions(
        after,
        status="ISSUED",
        compliance_status="NOTICES_AFFIXED",
        tax_status="UNCALCULATED",
        stamping_status="PENDING",
    )
    assert after["notice_codes_affixed"] == ["TX-SL-1", "TX-SL-2"]
    assert after["version"] == before["version"] + 1


def test_affixing_an_incomplete_notice_set_is_refused(policy_world):
    """Every required code must be present; extras and duplicates are tolerated.

    PRD 3.6: "The owning broker supplies a `notice_codes` array; the request is
    refused with `ERR_NOTICES_INCOMPLETE` unless that array contains every code
    listed in `required_notice_codes` on the program whose `state_code` equals the
    policy's `home_state`."

    Design: Corner/errors/affixing_an_incomplete_notice_set_is_refused
    """
    world = policy_world
    assert world.program("TX")["required_notice_codes"] == ["TX-SL-1", "TX-SL-2"]

    validate_error(
        world.api.affix_notices(
            world.policy["id"], {"notice_codes": ["TX-SL-1"]}, world.broker_headers
        ),
        ERR_NOTICES_INCOMPLETE,
        422,
    )
    still_pending = world.get_policy()
    assert_policy_dimensions(still_pending, compliance_status="PENDING_NOTICES")
    assert still_pending["notice_codes_affixed"] == []

    complete = world.affix_notices(["TX-SL-2", "TX-SL-1", "TX-SL-1"])
    assert complete["notice_codes_affixed"] == ["TX-SL-1", "TX-SL-2"]
    assert_policy_dimensions(complete, compliance_status="NOTICES_AFFIXED")


def test_an_affidavit_attesting_the_wrong_declination_count_is_refused(affixed_world):
    """The sworn count must match the figure pinned on the placement.

    PRD 3.6: "And `declination_count_attested` must equal the `declination_count`
    recorded on the policy's placement, else `ERR_AFFIDAVIT_COUNT_MISMATCH` —
    which is why a change request that zeroes the placement's count invalidates
    any affidavit drafted against the old figure."

    Design: Corner/errors/an_affidavit_attesting_the_wrong_declination_count_is_refused
    """
    world = affixed_world
    assert world.get_placement()["declination_count"] == 3

    understated = world.draft_affidavit(declination_count_attested=2)
    assert understated["status"] == "DRAFT"
    validate_error(
        world.api.sign_affidavit(understated["id"], world.broker_headers),
        ERR_AFFIDAVIT_COUNT_MISMATCH,
        422,
    )

    accurate = world.draft_affidavit(declination_count_attested=3)
    signed = world.sign_affidavit(accurate)
    assert signed["status"] == "SIGNED"


def test_stamping_rejection_without_a_reason_is_refused(stamping_submitted_world):
    """A blank rejection reason is not a reason.

    PRD 3.6: "On `REJECT` the `rejection_reason` must be a non-empty string, else
    `ERR_REJECTION_REASON_REQUIRED`; the stamping dimension advances `SUBMITTED →
    REJECTED`, and the same request also drives the independent compliance
    dimension to `DEFICIENT` — from `NOTICES_AFFIXED → DEFICIENT` or from
    `COMPLIANT → DEFICIENT`, whichever applies — with the policy's `version`
    incrementing by one for the request as a whole."

    Design: Corner/errors/stamping_rejection_without_a_reason_is_refused
    """
    world = stamping_submitted_world
    before = world.get_policy()
    assert_policy_dimensions(before, stamping_status="SUBMITTED")

    validate_error(
        world.api.stamping_decision(
            before["id"],
            {"decision": "REJECT", "rejection_reason": ""},
            STATE_REGULATOR_TX,
        ),
        ERR_REJECTION_REASON_REQUIRED,
        422,
    )
    unchanged = world.get_policy()
    assert_policy_dimensions(
        unchanged, stamping_status="SUBMITTED", compliance_status="NOTICES_AFFIXED"
    )
    assert unchanged["version"] == before["version"]

    accepted = world.stamping_decision("ACCEPT")
    assert_policy_dimensions(
        accepted, stamping_status="ACCEPTED", compliance_status="NOTICES_AFFIXED"
    )
    assert accepted["version"] == before["version"] + 1


def test_a_home_state_without_a_stamping_office_needs_no_stamping_submission(
    nv_home_world,
):
    """A `NOT_REQUIRED` stamping dimension is terminal from the moment of issue.

    PRD 3.5: "The four state dimensions are initialised as follows: `status` is
    `ISSUED`, with `CANCELLED` the only other value and terminal;
    `compliance_status` is `PENDING_NOTICES`, out of `PENDING_NOTICES`,
    `NOTICES_AFFIXED`, `COMPLIANT` and the terminal `DEFICIENT`; `tax_status` is
    `UNCALCULATED`, out of `UNCALCULATED`, `CALCULATED`, `ADJUSTED`, `FILED` and
    `REMITTED`, none of which is terminal; and `stamping_status` is `PENDING` when
    the home state's `stamping_office_required` is true and `NOT_REQUIRED` when it
    is false, out of `NOT_REQUIRED`, `PENDING`, `SUBMITTED`, `ACCEPTED` and
    `REJECTED`, of which `NOT_REQUIRED`, `ACCEPTED` and `REJECTED` are terminal."

    Design: Corner/validations/a_home_state_without_a_stamping_office_needs_no_stamping_submission
    """
    world = nv_home_world
    assert world.program("NV")["stamping_office_required"] is False

    policy = world.issue_policy(policy_number="SL-2026-0600")
    assert policy["home_state"] == "NV"
    assert_policy_dimensions(policy, status="ISSUED", stamping_status="NOT_REQUIRED")

    world.affix_notices(["NV-SL"])
    calculated = world.calculate_tax()
    assert calculated["total_tax_cents"] == 35875
    assert calculated["total_stamping_fee_cents"] == 0

    validate_error(
        world.api.submit_stamping(policy["id"], TAX_FILER_NINA),
        ERR_INVALID_STATE,
        409,
    )
    after = world.get_policy()
    assert_policy_dimensions(after, stamping_status="NOT_REQUIRED")
    assert after["stamping_submitted_at"] is None


def test_either_the_owning_broker_or_a_compliance_officer_may_sign_an_affidavit(
    affidavit_world,
):
    """Two roles hold the pen, and the diligent-search signature completes
    compliance.

    PRD 3.6: "On success the affidavit's `signed_by_user_id` is set to the acting
    `X-User-ID`, its `signed_at` to the current logical clock, its `status` to the
    terminal `SIGNED`, and its `version` increments."

    Design: Corner/rbac/either_the_owning_broker_or_a_compliance_officer_may_sign_an_affidavit
    """
    world = affidavit_world
    diligent = world.affidavit
    assert diligent["affidavit_type"] == "DILIGENT_SEARCH"

    by_officer = world.sign_affidavit(diligent, signer=COMPLIANCE_OFFICER_BRIGID)
    assert by_officer["status"] == "SIGNED"
    assert by_officer["signed_by_user_id"] == COMPLIANCE_OFFICER_BRIGID_ID
    assert by_officer["signed_at"] == "2026-08-01T00:00:00Z"
    assert_policy_dimensions(world.get_policy(), compliance_status="COMPLIANT")

    premium_tax = world.draft_affidavit(
        affidavit_type="PREMIUM_TAX", declination_count_attested=3
    )
    by_broker = world.sign_affidavit(premium_tax)
    assert by_broker["status"] == "SIGNED"
    assert by_broker["signed_by_user_id"] == world.broker["id"]

    rows = validate_success(
        world.api.list_affidavits(world.policy["id"], COMPLIANCE_OFFICER_BRIGID), 200
    )
    assert len(rows) == 2
    assert all(row["status"] == "SIGNED" for row in rows)


def test_the_officer_who_approved_the_carrier_cannot_sign_the_policys_affidavit(
    affidavit_world,
):
    """The clearing officer is barred from swearing on the resulting placement.

    PRD 3.6: "The acting `X-User-ID` must differ from the `reviewer_user_id` of
    every `APPROVED` or `CONDITIONAL` market security review whose `carrier_id`
    equals the policy's `carrier_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_officer_who_approved_the_carrier_cannot_sign_the_policys_affidavit
    """
    world = affidavit_world
    assert world.review["reviewer_user_id"] is not None

    validate_error(
        world.api.sign_affidavit(world.affidavit["id"], COMPLIANCE_OFFICER_ANDERS),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    still_draft = validate_success(
        world.api.list_affidavits(world.policy["id"], COMPLIANCE_OFFICER_ANDERS), 200
    )[0]
    assert still_draft["status"] == "DRAFT"
    assert still_draft["signed_by_user_id"] is None
    assert still_draft["signed_at"] is None

    # A different officer is unaffected by the bar.
    signed = world.sign_affidavit(signer=COMPLIANCE_OFFICER_BRIGID)
    assert signed["status"] == "SIGNED"


def test_the_four_policy_dimensions_advance_one_at_a_time_on_one_row(policy_world):
    """Compliance, tax and stamping each move without disturbing the others.

    PRD 2.8: "A policy is unusual in carrying **four independent state dimensions
    on one record**: `status`, `compliance_status`, `tax_status` and
    `stamping_status`. They advance separately and no ordering between them is
    implied."

    Design: Difficulty/non_linear_state_machine/policy_four_state_dimensions_advance_independently_on_one_row
    """
    world = policy_world
    issued = world.get_policy()
    assert_policy_dimensions(
        issued,
        status="ISSUED",
        compliance_status="PENDING_NOTICES",
        tax_status="UNCALCULATED",
        stamping_status="PENDING",
    )

    affixed = world.affix_notices(["TX-SL-2", "TX-SL-1", "TX-SL-2"])
    assert affixed["notice_codes_affixed"] == ["TX-SL-1", "TX-SL-2"]
    assert_policy_dimensions(
        affixed,
        status="ISSUED",
        compliance_status="NOTICES_AFFIXED",
        tax_status="UNCALCULATED",
        stamping_status="PENDING",
    )

    calculated = world.calculate_tax()
    assert_policy_dimensions(
        calculated,
        status="ISSUED",
        compliance_status="NOTICES_AFFIXED",
        tax_status="CALCULATED",
        stamping_status="PENDING",
    )

    submitted = world.submit_stamping()
    assert_policy_dimensions(
        submitted,
        status="ISSUED",
        compliance_status="NOTICES_AFFIXED",
        tax_status="CALCULATED",
        stamping_status="SUBMITTED",
    )
    assert submitted["stamping_submitted_at"] == "2026-08-01T00:00:00Z"


def test_a_stamping_rejection_moves_two_dimensions_in_a_single_request(policy_world):
    """One request, two dimensions, one version increment.

    PRD 2.8: "When a single request advances two dimensions — processing a
    cancellation moves both `status` and `tax_status`; a stamping rejection moves
    both `stamping_status` and `compliance_status` — the policy's `version` still
    increments by exactly 1 for that request."

    Design: Difficulty/non_linear_state_machine/policy_four_state_dimensions_advance_independently_on_one_row
    """
    world = policy_world
    world.calculate_tax()

    # The stamping office cannot be reached while compliance lags behind.
    validate_error(
        world.api.submit_stamping(world.policy["id"], TAX_FILER_NINA),
        ERR_NOTICES_NOT_AFFIXED,
        409,
    )

    world.affix_notices(["TX-SL-1", "TX-SL-2"])
    submitted = world.submit_stamping()

    rejected = world.stamping_decision(
        "REJECT",
        rejection_reason="Stamping office could not match the filed diligent search record.",
    )
    assert_policy_dimensions(
        rejected,
        status="ISSUED",
        compliance_status="DEFICIENT",
        tax_status="CALCULATED",
        stamping_status="REJECTED",
    )
    assert rejected["version"] == submitted["version"] + 1
