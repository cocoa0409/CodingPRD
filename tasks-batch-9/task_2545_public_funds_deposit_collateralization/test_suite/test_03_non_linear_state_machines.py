"""Non-linear lifecycles: the substitution fork-join and the cyclic qualification review."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import attest_payload, return_for_info_payload
from test_helpers.fixtures import COMPLIANCE, OFFICER, REGULATOR
from test_helpers.test_users import (
    OFFICER_USER_ID,
    make_bank_compliance_officer_headers,
    make_custodian_headers,
)


def _substitution_awaiting_compliance(client):
    """A dedicated arrangement holding one 5,000,000-cent treasury pledge, with an agency
    debenture standing by, and a substitution request that the custodian has already
    acknowledged."""
    perimeter = fixtures.build_substitution_ready(
        client,
        outgoing_par_cents=5_000_000,
        incoming_par_cents=5_100_000,
        incoming_asset_type="AGENCY_DEBENTURE",
    )
    request = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        perimeter["allocation_id"],
        perimeter["incoming_asset_id"],
        5_100_000,
    )
    assert request["status"] == "SUBMITTED"
    assert request["value_adequacy_delta_cents"] is None

    acked = fixtures.custodian_ack(client, request["id"], perimeter["custodian_id"])
    assert acked["status"] == "CUSTODIAN_ACKED"
    assert acked["custodian_acked_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert acked["value_adequacy_delta_cents"] is None

    perimeter["request"] = acked
    perimeter["request_id"] = request["id"]
    return perimeter


def test_settling_after_only_the_custodian_branch_is_refused(client):
    """With only the custodian branch complete the request sits in CUSTODIAN_ACKED, and a
    settle attempt is refused as inadmissible without moving any par — the outgoing
    allocation is still ACTIVE afterwards.

    PRD: "Swapping pledged collateral is not a unilateral act, so a substitution in this
    service is a **fork-join**: an independent compliance branch and an independent custodian
    branch run in either order, and only when both have completed may the custodian settle."
    PRD: "Only a `Custodian` whose `X-User-ID` equals the agreement's `custodian_id` may
    settle, only from `READY_TO_SETTLE`, only while that custodian's own `approval_status` is
    `APPROVED`, and only when the incoming asset's `eligibility_status` is still `ELIGIBLE`
    and its `available_par_cents` is at least `incoming_par_cents`; the par-capacity rule of
    §3.4 applies to the incoming pledge exactly as it does to a directly created allocation,
    with `ERR_ALLOCATION_OVERSUBSCRIBED` on breach."
    PRD: "**State admissibility** — the target resource is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/substitution_fork_join_requires_both_branches
    """
    perimeter = _substitution_awaiting_compliance(client)

    response = client.settle_substitution(
        perimeter["request_id"], make_custodian_headers(perimeter["custodian_id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    request = get_success_data(
        client.get_substitution_request(perimeter["request_id"], OFFICER), 200
    )
    assert request["status"] == "CUSTODIAN_ACKED"
    assert request["settled_at"] is None

    allocation = get_success_data(
        client.get_pledge_allocation(perimeter["allocation_id"], OFFICER), 200
    )
    assert allocation["status"] == "ACTIVE"
    assert allocation["allocated_par_cents"] == 5_000_000


def test_the_second_branch_joins_the_request_and_only_then_settles(client):
    """When the compliance branch lands second it joins the request to READY_TO_SETTLE and
    writes a value adequacy delta of 47,000 cents, after which the same settle call succeeds:
    the old allocation becomes SUBSTITUTED and a single new ACTIVE allocation of 5,100,000
    cents par worth 4,947,000 cents is minted under the request.

    PRD: "This branch, and only this branch, computes and stores `value_adequacy_delta_cents`:
    the haircut value the incoming pledge would carry, obtained by applying the two-step
    valuation of §3.4 to `incoming_par_cents` on the incoming asset, less the outgoing
    allocation's current `allocated_collateral_value_cents`."
    PRD: "Arriving first, it carries the request `SUBMITTED → COMPLIANCE_APPROVED`; arriving
    second, against a request already in `CUSTODIAN_ACKED`, it performs exactly the same
    writes and checks and carries the request `CUSTODIAN_ACKED → READY_TO_SETTLE`."
    PRD: "**Hop two**, caused by hop one, has the pledge agreement recompute
    `total_pledged_par_cents`, `total_collateral_value_cents` and `active_allocation_count`."

    Design: Difficulty/non_linear_state_machine/substitution_fork_join_requires_both_branches
    """
    perimeter = _substitution_awaiting_compliance(client)

    joined = fixtures.compliance_approve(client, perimeter["request_id"])
    assert joined["status"] == "READY_TO_SETTLE"
    assert joined["value_adequacy_delta_cents"] == 47_000

    settled = fixtures.settle_substitution(
        client, perimeter["request_id"], perimeter["custodian_id"]
    )
    assert settled["status"] == "SETTLED"
    assert settled["settled_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    outgoing = get_success_data(
        client.get_pledge_allocation(perimeter["allocation_id"], OFFICER), 200
    )
    assert outgoing["status"] == "SUBSTITUTED"
    assert outgoing["release_reason"] == "SUBSTITUTION_SETTLED"

    minted, _meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"created_by_substitution_id": perimeter["request_id"]}
        )
    )
    assert len(minted) == 1
    assert minted[0]["status"] == "ACTIVE"
    assert minted[0]["allocated_par_cents"] == 5_100_000
    assert minted[0]["allocated_collateral_value_cents"] == 4_947_000

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 4_947_000
    assert agreement["total_pledged_par_cents"] == 5_100_000
    assert agreement["active_allocation_count"] == 1


def _review_returned_for_more_information(client):
    """A draft bank whose package has been attested, taken under review and returned once."""
    fixtures.set_clock(client)
    depository = fixtures.create_draft_depository(client)
    review = fixtures.file_qualification_review(client, depository["id"])
    assert review["status"] == "SUBMITTED"
    assert review["round_count"] == 1

    attested = fixtures.attest_review(client, review["id"], attestation_note="Round 1 package")
    assert attested["status"] == "ATTESTED"
    assert attested["round_count"] == 1

    fixtures.begin_review(client, review["id"])
    returned = get_success_data(
        client.return_for_info_qualification_review(
            review["id"],
            return_for_info_payload(info_request_note="Provide audited call report"),
            REGULATOR,
        ),
        200,
    )
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["attested_by_user_id"] is None
    return depository, review


def _return_for_info(client, review_id, note):
    return get_success_data(
        client.return_for_info_qualification_review(
            review_id, return_for_info_payload(info_request_note=note), REGULATOR
        ),
        200,
    )


def test_re_attesting_a_returned_package_walks_the_cycle_and_counts_rounds(client):
    """Each re-attestation of a returned package closes the review cycle again, lifting
    round_count from 1 to 2 and then to 3 while every return clears the attester back to null
    and leaves the bank sitting at UNDER_REVIEW.

    PRD: "Re-attesting a `RETURNED_FOR_INFO` package is the move that closes the review cycle
    `ATTESTED → UNDER_REVIEW → RETURNED_FOR_INFO → ATTESTED`, and it additionally increments
    `round_count` by 1."
    PRD: "Returning the package for more information requires an `info_request_note`, drives
    the review to `RETURNED_FOR_INFO`, and clears `attested_by_user_id` back to null so that
    the second line must attest afresh — the depository's `approval_status` deliberately stays
    at `UNDER_REVIEW` throughout."

    Design: Difficulty/non_linear_state_machine/qualification_review_return_for_info_cycle_round_counting
    """
    depository, review = _review_returned_for_more_information(client)

    second = fixtures.attest_review(
        client, review["id"], attestation_note="Round 2 package with call report"
    )
    assert second["status"] == "ATTESTED"
    assert second["round_count"] == 2

    fixtures.begin_review(client, review["id"])
    returned = _return_for_info(client, review["id"], "Provide liquidity attestation")
    assert returned["attested_by_user_id"] is None

    third = fixtures.attest_review(
        client, review["id"], attestation_note="Round 3 package with liquidity attestation"
    )
    assert third["status"] == "ATTESTED"
    assert third["round_count"] == 3

    bank = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert bank["approval_status"] == "UNDER_REVIEW"


def test_the_fourth_attestation_hits_the_round_ceiling(client):
    """After three rounds the loop is closed: the attempt that would produce a fourth round is
    refused, the count stays at 3, the package stays RETURNED_FOR_INFO and the bank is still
    only UNDER_REVIEW.

    PRD: "Rounds are capped: the incremented `round_count` may be at most 3, so a package that
    has already been through three rounds is refused with `ERR_ROUND_LIMIT_REACHED` on the
    attempt that would produce a fourth."
    PRD: "**Round ceilings** — `ERR_ROUND_LIMIT_REACHED` (HTTP 409) on re-attesting a returned
    qualification package or requesting an amendment beyond the permitted number of rounds."

    Design: Difficulty/non_linear_state_machine/qualification_review_return_for_info_cycle_round_counting
    """
    depository, review = _review_returned_for_more_information(client)

    fixtures.attest_review(client, review["id"], attestation_note="Round 2 package")
    fixtures.begin_review(client, review["id"])
    _return_for_info(client, review["id"], "Provide liquidity attestation")
    fixtures.attest_review(client, review["id"], attestation_note="Round 3 package")
    fixtures.begin_review(client, review["id"])
    _return_for_info(client, review["id"], "Provide collateral custody letter")

    response = client.attest_qualification_review(
        review["id"], attest_payload(attestation_note="Round 4 package"), COMPLIANCE
    )
    validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED.value, 409)

    reviews, _meta = validate_paginated(
        client.list_qualification_reviews(depository["id"], REGULATOR)
    )
    assert len(reviews) == 1
    assert reviews[0]["round_count"] == 3
    assert reviews[0]["status"] == "RETURNED_FOR_INFO"

    bank = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert bank["approval_status"] == "UNDER_REVIEW"


def test_the_cycle_is_no_way_around_the_two_person_rule(client):
    """Re-attesting a returned package under the filing officer's own identity is refused, so
    walking the loop cannot be used to collapse the two lines of defence into one.

    PRD: "The attester's `X-User-ID` must differ from `submitted_by_user_id`, or the attempt is
    refused with `ERR_SEGREGATION_OF_DUTIES`; and a package belonging to a depository whose
    `approval_status` is already `DENIED` cannot be attested at all."
    PRD: "**Segregation of duties** — the acting `X-User-ID` differs from the identity that
    performed the incompatible earlier step, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/qualification_review_return_for_info_cycle_round_counting
    """
    _depository, review = _review_returned_for_more_information(client)

    response = client.attest_qualification_review(
        review["id"],
        attest_payload(attestation_note="Round 2 package"),
        make_bank_compliance_officer_headers(OFFICER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
