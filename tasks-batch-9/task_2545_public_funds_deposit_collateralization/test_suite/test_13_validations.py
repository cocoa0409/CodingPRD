"""Rejection paths: fiscal ceilings, scoped uniqueness, aggregate limits, segregation of duties,
cross-entity coherence, interval sanity, cure guards and the two blocking postures.
"""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, OPEN_ENDED_SENTINEL, clock_stamp
from test_helpers.factories import (
    amount_payload,
    attest_payload,
    create_collateral_asset_payload,
    create_deposit_account_payload,
    create_pledge_agreement_payload,
    create_pledge_allocation_payload,
    create_qualification_review_payload,
    create_runoff_forecast_payload,
    create_safekeeping_receipt_payload,
    create_substitution_request_payload,
    cure_payload,
    projected_window,
    signature_payload,
)
from test_helpers.fixtures import COMPLIANCE, OFFICER, REGULATOR
from test_helpers.test_users import (
    COMPLIANCE_USER_ID,
    OFFICER_USER_ID,
    make_bank_compliance_officer_headers,
    make_custodian_headers,
    make_public_unit_treasurer_headers,
)

FIVE_AM = "2026-08-01T05:00:00Z"
SIX_AM = "2026-08-01T06:00:00Z"
TEN_AM = "2026-08-01T10:00:00Z"
THIRD_DAY = "2026-08-03T00:00:00Z"


def test_the_deposit_ceiling_and_the_ledger_floor_are_both_inclusive(client):
    """A unit whose statutory ceiling is 100,000,000 cents may be funded to exactly that figure,
    but one cent more is refused as a statutory breach and a withdrawal of one cent more than the
    balance is refused as an overdraft — and neither rejection leaves any trace on the ledger,
    the unit aggregates or the account's version.

    PRD: "Before a deposit is accepted, the owning unit's `total_deposit_balance_cents` plus the
    deposited `amount_cents` must be at most its `statutory_max_deposit_cents`; exceeding it is
    refused with `ERR_STATUTORY_DEPOSIT_LIMIT`."
    PRD: "A withdrawal supplies `amount_cents` too, is admissible only on a `FUNDED` account,
    and may not exceed the account's current `ledger_balance_cents`, else
    `ERR_INSUFFICIENT_LEDGER_BALANCE`."
    PRD: "33. **Fiscal ceilings and floors** — the statutory deposit limit
    (`ERR_STATUTORY_DEPOSIT_LIMIT`, HTTP 422) on a deposit; the ledger balance floor
    (`ERR_INSUFFICIENT_LEDGER_BALANCE`, HTTP 422) on a withdrawal; the approved pledge capacity
    ceiling (`ERR_PLEDGE_CAPACITY_EXCEEDED`, HTTP 422) on a pledge allocation; the statutory
    capacity ceiling (`ERR_CAPACITY_ABOVE_STATUTORY_CEILING`, HTTP 422) on filing a qualification
    package and on deciding one; and the cure overage ceiling (`ERR_CURE_EXCEEDS_OUTSTANDING`,
    HTTP 422) on curing a margin call."

    Design: Corner/validations/statutory_deposit_limit_and_insufficient_ledger_balance_rejected
    """
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(
        client, unit_type="COUNTY", statutory_max_deposit_cents=100_000_000
    )
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    assert account["ledger_balance_cents"] == 100_000_000
    assert account["funding_status"] == "FUNDED"
    funded_version = account["version"]

    treasurer = make_public_unit_treasurer_headers(public_unit["id"])
    overshoot = client.create_deposit(account["id"], amount_payload(1), treasurer)
    validate_error(overshoot, ApiErrorId.ERR_STATUTORY_DEPOSIT_LIMIT.value, 422)

    overdraft = client.create_withdrawal(
        account["id"], amount_payload(100_000_001), treasurer
    )
    validate_error(overdraft, ApiErrorId.ERR_INSUFFICIENT_LEDGER_BALANCE.value, 422)

    unchanged = get_success_data(
        client.get_deposit_account(account["id"], treasurer), 200
    )
    assert unchanged["ledger_balance_cents"] == 100_000_000
    assert unchanged["version"] == funded_version

    unit = get_success_data(client.get_public_unit(public_unit["id"], REGULATOR), 200)
    assert unit["total_deposit_balance_cents"] == 100_000_000
    assert unit["total_uninsured_cents"] == 75_000_000

    drained = fixtures.withdraw(client, account["id"], public_unit["id"], 100_000_000)
    assert drained["ledger_balance_cents"] == 0
    assert drained["funding_status"] == "FUNDED"


def test_each_business_identifier_is_unique_only_inside_its_own_parent(client):
    """A cusip and an agreement number collide within one depository, while the very same receipt
    number is refused under the agreement that already carries it and accepted under a sibling
    agreement of the same bank — three constraints, three different scoping parents.

    PRD: "The depository must be `APPROVED` before any collateral may be registered against it,
    and the `cusip` must be unique within that depository, a collision being refused with
    `ERR_DUPLICATE_IDENTIFIER`."
    PRD: "The `agreement_number` must be unique within the depository, and a collision is refused
    with `ERR_DUPLICATE_IDENTIFIER`."
    PRD: "The agreement must be in `EXECUTED` status, the issuing custodian must be `APPROVED`
    and `tri_party_capable`, its `X-User-ID` must equal the agreement's `custodian_id`, and the
    `receipt_number` must be unique within that agreement, a collision being refused with
    `ERR_DUPLICATE_IDENTIFIER`."
    PRD: "27. **Uniqueness** — `ERR_DUPLICATE_IDENTIFIER` (HTTP 409) on registering a collateral
    asset, drafting a pledge agreement or issuing a safekeeping receipt whose business identifier
    is already taken in its scope."

    Design: Corner/validations/duplicate_identifier_rejected_per_scoping_parent
    """
    perimeter = fixtures.build_dedicated_perimeter(client)
    first_agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    second_agreement = fixtures.create_executed_dedicated_agreement(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        perimeter["account_id"],
        perimeter["public_unit_id"],
    )
    fixtures.create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"], cusip="CU-0001"
    )
    first_receipt = fixtures.issue_receipt(
        client,
        first_agreement["id"],
        perimeter["custodian_id"],
        0,
        0,
        receipt_number="RC-0001",
    )
    assert first_receipt["discrepancy_par_cents"] == 0

    duplicate_cusip = client.create_collateral_asset(
        create_collateral_asset_payload(
            perimeter["depository_id"],
            perimeter["custodian_id"],
            cusip="CU-0001",
            asset_type="AGENCY_DEBENTURE",
            par_value_cents=5_000_000,
        ),
        OFFICER,
    )
    validate_error(duplicate_cusip, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)

    duplicate_number = client.create_pledge_agreement(
        create_pledge_agreement_payload(
            perimeter["depository_id"],
            perimeter["custodian_id"],
            deposit_account_id=perimeter["account_id"],
            agreement_number=first_agreement["agreement_number"],
        ),
        OFFICER,
    )
    validate_error(duplicate_number, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)

    duplicate_receipt = client.create_safekeeping_receipt(
        create_safekeeping_receipt_payload(
            first_agreement["id"], 0, 0, receipt_number="RC-0001"
        ),
        make_custodian_headers(perimeter["custodian_id"]),
    )
    validate_error(duplicate_receipt, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)

    reused_elsewhere = fixtures.issue_receipt(
        client,
        second_agreement["id"],
        perimeter["custodian_id"],
        0,
        0,
        receipt_number="RC-0001",
    )
    assert reused_elsewhere["receipt_number"] == first_receipt["receipt_number"]
    assert reused_elsewhere["id"] != first_receipt["id"]
    assert reused_elsewhere["discrepancy_par_cents"] == 0

    under_first, first_meta = validate_paginated(
        client.list_agreement_safekeeping_receipts(first_agreement["id"], REGULATOR)
    )
    assert first_meta["total_count"] == 1
    assert len(under_first) == 1
    _under_second, second_meta = validate_paginated(
        client.list_agreement_safekeeping_receipts(second_agreement["id"], REGULATOR)
    )
    assert second_meta["total_count"] == 1

    assert fixtures.confirm_receipt(client, first_receipt["id"])[
        "confirmation_status"
    ] == "CONFIRMED"
    assert fixtures.confirm_receipt(client, reused_elsewhere["id"])[
        "confirmation_status"
    ] == "CONFIRMED"


def test_the_statutory_capacity_ceiling_admits_the_ceiling_itself(client):
    """A package asking for one cent above the five-billion-dollar statutory ceiling is refused
    and creates no review at all, while a package asking for exactly the ceiling is filed as the
    bank's first round and carries that whole figure onto the depository at approval.

    PRD: "A `BankCollateralOfficer` files a **qualification review** under a depository,
    supplying only `requested_pledge_capacity_cents`, the pledge capacity the bank asks the state
    to authorise; it must be strictly positive, and it must not exceed the statutory ceiling of
    500,000,000,000 cents (five billion dollars), a ceiling enforced both when the package is
    filed and again when the regulator decides it, with `ERR_CAPACITY_ABOVE_STATUTORY_CEILING` on
    either."
    PRD: "An approval requires the review to be `UNDER_REVIEW` with a non-null
    `attested_by_user_id`; it sets the review to `APPROVED` with `decided_at` stamped from the
    clock, carries the depository from `UNDER_REVIEW` to `APPROVED` with `approved_at` stamped,
    copies `requested_pledge_capacity_cents` into the depository's
    `approved_pledge_capacity_cents`, and increments the depository's `version`."

    Design: Corner/validations/qualification_capacity_above_statutory_ceiling_rejected
    """
    fixtures.set_clock(client)
    depository = fixtures.create_draft_depository(client)

    above_ceiling = client.create_qualification_review(
        depository["id"],
        create_qualification_review_payload(
            requested_pledge_capacity_cents=500_000_000_001
        ),
        OFFICER,
    )
    validate_error(
        above_ceiling, ApiErrorId.ERR_CAPACITY_ABOVE_STATUTORY_CEILING.value, 422
    )

    still_draft = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert still_draft["approval_status"] == "DRAFT"
    _empty, empty_meta = validate_paginated(
        client.list_qualification_reviews(depository["id"], REGULATOR)
    )
    assert empty_meta["total_count"] == 0

    review = fixtures.file_qualification_review(
        client, depository["id"], requested_pledge_capacity_cents=500_000_000_000
    )
    assert review["status"] == "SUBMITTED"
    assert review["round_count"] == 1

    fixtures.attest_review(client, review["id"])
    fixtures.begin_review(client, review["id"])
    decided = fixtures.decide_review(client, review["id"], "APPROVE")
    assert decided["status"] == "APPROVED"

    approved = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert approved["approval_status"] == "APPROVED"
    assert approved["approved_pledge_capacity_cents"] == 500_000_000_000
    assert approved["approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    reviews, meta = validate_paginated(
        client.list_qualification_reviews(depository["id"], REGULATOR)
    )
    assert meta["total_count"] == 1
    assert reviews[0]["round_count"] == 1


def test_the_pledge_capacity_guard_counts_par_and_admits_the_capacity_itself(client):
    """A bank approved for exactly 400,000,000 cents of capacity is refused an allocation of
    400,000,001 par yet accepted at 400,000,000 on the identical asset and the identical pinned
    agreement version, even though the haircut value of the accepted pledge is only 392,000,000 —
    the ceiling is compared against par, not against value.

    PRD: "- **Approved pledge capacity.** The depository's `total_pledged_par_cents` plus the
    newly requested `allocated_par_cents` must not exceed the `approved_pledge_capacity_cents` the
    state granted at qualification, else `ERR_PLEDGE_CAPACITY_EXCEEDED`."
    PRD: "A depository's `total_pledged_par_cents` is likewise the sum of `allocated_par_cents`
    over the `ACTIVE` allocations of its `EXECUTED` agreements whose intervals cover the current
    clock."
    PRD: "From `pledged_par_cents` the service also derives `pledge_status`: `UNPLEDGED` when
    nothing is pledged, `PARTIALLY_PLEDGED` when some but not all of the par is pledged, and
    `FULLY_PLEDGED` when the pledged par equals `par_value_cents` exactly."

    Design: Corner/validations/allocation_beyond_approved_pledge_capacity_rejected
    """
    perimeter = fixtures.build_dedicated_perimeter(
        client, requested_pledge_capacity_cents=400_000_000
    )
    assert perimeter["depository"]["approved_pledge_capacity_cents"] == 400_000_000
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=500_000_000,
        market_price_bps=10000,
    )
    pinned_version = fixtures.agreement_version(client, perimeter["agreement_id"])

    over_capacity = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            perimeter["agreement_id"],
            asset["id"],
            400_000_001,
            pinned_version,
            effective_from=DEFAULT_CLOCK_UTC,
        ),
        OFFICER,
    )
    validate_error(over_capacity, ApiErrorId.ERR_PLEDGE_CAPACITY_EXCEEDED.value, 422)

    untouched = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert untouched["total_pledged_par_cents"] == 0

    accepted = get_success_data(
        client.create_pledge_allocation(
            create_pledge_allocation_payload(
                perimeter["agreement_id"],
                asset["id"],
                400_000_000,
                pinned_version,
                effective_from=DEFAULT_CLOCK_UTC,
            ),
            OFFICER,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["allocated_par_cents"] == 400_000_000
    assert accepted["allocated_collateral_value_cents"] == 392_000_000

    at_capacity = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert at_capacity["total_pledged_par_cents"] == 400_000_000
    assert (
        at_capacity["total_pledged_par_cents"]
        == at_capacity["approved_pledge_capacity_cents"]
    )

    pledged_asset = get_success_data(
        client.get_collateral_asset(asset["id"], OFFICER), 200
    )
    assert pledged_asset["pledged_par_cents"] == 400_000_000
    assert pledged_asset["available_par_cents"] == 100_000_000
    assert pledged_asset["pledge_status"] == "PARTIALLY_PLEDGED"

    one_cent_more = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            perimeter["agreement_id"],
            asset["id"],
            1,
            fixtures.agreement_version(client, perimeter["agreement_id"]),
            effective_from=DEFAULT_CLOCK_UTC,
        ),
        OFFICER,
    )
    validate_error(one_cent_more, ApiErrorId.ERR_PLEDGE_CAPACITY_EXCEEDED.value, 422)


def test_a_custodians_share_is_measured_after_the_write_against_a_growing_denominator(client):
    """The same 9,800,000 cents of value that is perfectly legal at a custodian limited to 10000
    basis points is refused at a custodian limited to 4000, because after the write it would be
    half of the bank's pledged value; a smaller 3,920,000-cent pledge at that same custodian
    passes at 2857 basis points, since its own value swells the denominator too.

    PRD: "- **Custodian concentration.** After the write, the collateral value the depository
    holds at this custodian, multiplied by 10000, must be at most the depository's
    `total_pledged_collateral_value_cents` multiplied by that custodian's
    `concentration_limit_bps`. Exceeding the limit is refused with
    `ERR_CUSTODIAN_CONCENTRATION_EXCEEDED`."
    PRD: "A depository's `total_pledged_collateral_value_cents` is the sum of
    `total_collateral_value_cents` over its agreements in `EXECUTED` status."
    PRD: "26. **Custodian concentration** — `ERR_CUSTODIAN_CONCENTRATION_EXCEEDED` (HTTP 422)
    when a new allocation would push one custodian's share of a depository's pledged collateral
    value above that custodian's limit. This rung guards creating a pledge allocation."

    Design: Corner/validations/custodian_concentration_limit_exceeded_rejected
    """
    fixtures.set_clock(client)
    generous = fixtures.create_approved_custodian(
        client, name="Alpha Custody", tri_party_capable=True, concentration_limit_bps=10000
    )
    strict = fixtures.create_approved_custodian(
        client,
        name="Beta Custody",
        custodian_type="FEDERAL_RESERVE",
        tri_party_capable=True,
        concentration_limit_bps=4000,
    )
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    generous_agreement = fixtures.create_executed_dedicated_agreement(
        client, depository["id"], generous["id"], account["id"], public_unit["id"]
    )
    strict_agreement = fixtures.create_executed_dedicated_agreement(
        client, depository["id"], strict["id"], account["id"], public_unit["id"]
    )
    at_generous = fixtures.create_collateral_asset(
        client, depository["id"], generous["id"], par_value_cents=10_000_000
    )
    large_at_strict = fixtures.create_collateral_asset(
        client, depository["id"], strict["id"], par_value_cents=10_000_000
    )
    small_at_strict = fixtures.create_collateral_asset(
        client, depository["id"], strict["id"], par_value_cents=4_000_000
    )

    seeded = fixtures.create_allocation(
        client, generous_agreement["id"], at_generous["id"], 10_000_000
    )
    assert seeded["allocated_collateral_value_cents"] == 9_800_000
    seeded_bank = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert seeded_bank["total_pledged_collateral_value_cents"] == 9_800_000

    over_concentrated = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            strict_agreement["id"],
            large_at_strict["id"],
            10_000_000,
            fixtures.agreement_version(client, strict_agreement["id"]),
            effective_from=DEFAULT_CLOCK_UTC,
        ),
        OFFICER,
    )
    validate_error(
        over_concentrated, ApiErrorId.ERR_CUSTODIAN_CONCENTRATION_EXCEEDED.value, 422
    )

    unmoved_bank = get_success_data(
        client.get_depository(depository["id"], REGULATOR), 200
    )
    assert unmoved_bank["total_pledged_collateral_value_cents"] == 9_800_000
    unmoved_asset = get_success_data(
        client.get_collateral_asset(large_at_strict["id"], OFFICER), 200
    )
    assert unmoved_asset["pledge_status"] == "UNPLEDGED"
    assert unmoved_asset["pledged_par_cents"] == 0

    accepted = fixtures.create_allocation(
        client, strict_agreement["id"], small_at_strict["id"], 4_000_000
    )
    assert accepted["allocated_collateral_value_cents"] == 3_920_000

    diluted = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert diluted["total_pledged_collateral_value_cents"] == 13_720_000
    assert 3_920_000 * 10000 // 13_720_000 == 2857
    assert 9_800_000 * 10000 // 13_720_000 == 7142
    assert 9_800_000 * 10000 // 19_600_000 == 5000


def test_the_officer_who_filed_a_package_may_not_attest_it_even_wearing_the_second_lines_role(
    client,
):
    """Attesting under the filing officer's own user id is refused although the request carries a
    permitted role, and the identical call from a different user id with that same role succeeds —
    so the check reads the review's recorded submitter, not the role header.

    PRD: "The attester's `X-User-ID` must differ from `submitted_by_user_id`, or the attempt is
    refused with `ERR_SEGREGATION_OF_DUTIES`; and a package belonging to a depository whose
    `approval_status` is already `DENIED` cannot be attested at all."
    PRD: "A `BankComplianceOfficer` attests a package in `SUBMITTED` or `RETURNED_FOR_INFO`
    status, supplying an `attestation_note`, which drives the review to `ATTESTED` and records the
    attester's `X-User-ID` as `attested_by_user_id`."
    PRD: "The filed review is `SUBMITTED`, its `depository_id` is taken from the path rather than
    the body, its `submitted_by_user_id` records the filing officer's `X-User-ID`, and its
    `round_count` is 1."

    Design: Corner/validations/same_user_cannot_attest_the_qualification_review_it_submitted
    """
    fixtures.set_clock(client)
    depository = fixtures.create_draft_depository(client)
    review = fixtures.file_qualification_review(client, depository["id"])
    assert review["submitted_by_user_id"] == OFFICER_USER_ID
    assert review["status"] == "SUBMITTED"
    assert review["attested_by_user_id"] is None

    self_attestation = client.attest_qualification_review(
        review["id"],
        attest_payload(attestation_note="Self-attested"),
        make_bank_compliance_officer_headers(OFFICER_USER_ID),
    )
    validate_error(self_attestation, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    reviews, _meta = validate_paginated(
        client.list_qualification_reviews(depository["id"], REGULATOR)
    )
    assert len(reviews) == 1
    assert reviews[0]["status"] == "SUBMITTED"
    assert reviews[0]["attested_by_user_id"] is None

    attested = fixtures.attest_review(
        client, review["id"], attestation_note="Independently attested"
    )
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == COMPLIANCE_USER_ID
    assert attested["attestation_note"] == "Independently attested"


def test_circulation_needs_both_halves_of_custodian_eligibility(client):
    """An approved custodian that is not tri-party capable and a tri-party custodian that is still
    only pending approval each block circulation with the same refusal, leaving the draft exactly
    where it was, while the custodian that satisfies both halves lets the document out for
    signature.

    PRD: "Circulating the draft carries it to `PENDING_SIGNATURES`. Circulation is admissible
    from `DRAFT` and from `AMENDMENT_REQUESTED`, and it has two cross-entity preconditions beyond
    the state check: the named custodian's `approval_status` must be `APPROVED` **and** its
    `tri_party_capable` flag must be true, else `ERR_CUSTODIAN_NOT_ELIGIBLE`, and the depository's
    `approval_status` must be `APPROVED`, else `ERR_DEPOSITORY_NOT_APPROVED`."
    PRD: "12. **Custodian eligibility** — the agreement's custodian has `approval_status`
    `APPROVED` and `tri_party_capable` true, else `ERR_CUSTODIAN_NOT_ELIGIBLE` (HTTP 409). This
    rung guards exactly three operations: circulating a pledge agreement, settling a substitution,
    and issuing a safekeeping receipt."

    Design: Corner/validations/circulate_with_ineligible_custodian_rejected
    """
    fixtures.set_clock(client)
    plain_custodian = get_success_data(
        client.create_custodian(
            {"name": "No Triparty Trust", "custodian_type": "TRUST_BANK"}, REGULATOR
        ),
        201,
    )
    approved_plain = get_success_data(
        client.approve_custodian(plain_custodian["id"], REGULATOR), 200
    )
    assert approved_plain["approval_status"] == "APPROVED"
    assert approved_plain["tri_party_capable"] is False
    assert approved_plain["concentration_limit_bps"] == 6000

    pending_custodian = fixtures.create_custodian(
        client, name="Unapproved Custody", tri_party_capable=True
    )
    assert pending_custodian["approval_status"] == "PENDING_APPROVAL"
    assert pending_custodian["tri_party_capable"] is True

    eligible_custodian = fixtures.create_approved_custodian(
        client, name="Good Custody", tri_party_capable=True
    )
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"]
    )
    without_triparty = fixtures.draft_dedicated_agreement(
        client, depository["id"], plain_custodian["id"], account["id"]
    )
    without_approval = fixtures.draft_dedicated_agreement(
        client, depository["id"], pending_custodian["id"], account["id"]
    )
    fully_eligible = fixtures.draft_dedicated_agreement(
        client, depository["id"], eligible_custodian["id"], account["id"]
    )

    refused_triparty = client.circulate_pledge_agreement(without_triparty["id"], OFFICER)
    validate_error(refused_triparty, ApiErrorId.ERR_CUSTODIAN_NOT_ELIGIBLE.value, 409)
    stalled = get_success_data(
        client.get_pledge_agreement(without_triparty["id"], OFFICER), 200
    )
    assert stalled["status"] == "DRAFT"

    refused_approval = client.circulate_pledge_agreement(
        without_approval["id"], OFFICER
    )
    validate_error(refused_approval, ApiErrorId.ERR_CUSTODIAN_NOT_ELIGIBLE.value, 409)
    also_stalled = get_success_data(
        client.get_pledge_agreement(without_approval["id"], OFFICER), 200
    )
    assert also_stalled["status"] == "DRAFT"

    circulated = fixtures.circulate(client, fully_eligible["id"])
    assert circulated["status"] == "PENDING_SIGNATURES"


def test_the_beneficiary_discriminator_rejects_every_incoherent_pairing(client):
    """A stray companion target on a deposit-account agreement, a stray companion target on a
    pooled agreement, and a pooled agreement naming a program the drafting bank has not joined all
    collapse to one refusal, and none of the three leaves a document behind.

    PRD: "The beneficiary discriminator is polymorphic and its companion field is conditional: a
    `DEPOSIT_ACCOUNT` agreement must supply `deposit_account_id` and must omit
    `pooled_program_id`, while a `POOLED_PROGRAM` agreement must supply `pooled_program_id`, must
    omit `deposit_account_id`, and may only name a program of which the drafting depository is
    already a member, meaning the depository's own `pooled_program_id` equals the named program."
    PRD: "Any breach of that coherence rule — a missing companion, a superfluous companion, or a
    pool the bank does not belong to — is refused with `ERR_BENEFICIARY_TARGET_INVALID`."
    PRD: "A drafted agreement begins at `status` `DRAFT` with `signature_count` zero,
    `amendment_round` zero, all three party stamps (`depository_signed_at`,
    `public_unit_signed_at`, `custodian_signed_at`) null, both `executed_at` and `terminated_at`
    null, and `total_pledged_par_cents`, `total_collateral_value_cents` and
    `active_allocation_count` all zero."

    Design: Corner/validations/pledge_agreement_beneficiary_target_incoherence_rejected
    """
    fixtures.set_clock(client)
    pool = fixtures.create_pooled_program(client)
    custodian = fixtures.create_approved_custodian(client, tri_party_capable=True)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    outside_bank = fixtures.create_approved_depository(client, name="Plain Bank")
    member_bank = fixtures.create_approved_depository(
        client, name="Pooled Bank", charter_type="NATIONAL", pooled_program_id=pool["id"]
    )
    assert outside_bank["pooled_program_id"] is None
    assert member_bank["pooled_program_id"] == pool["id"]
    account = fixtures.create_deposit_account(
        client, outside_bank["id"], public_unit["id"]
    )

    both_on_account = client.create_pledge_agreement(
        create_pledge_agreement_payload(
            outside_bank["id"],
            custodian["id"],
            beneficiary_type="DEPOSIT_ACCOUNT",
            deposit_account_id=account["id"],
            pooled_program_id=pool["id"],
            agreement_number="AG-1",
        ),
        OFFICER,
    )
    validate_error(both_on_account, ApiErrorId.ERR_BENEFICIARY_TARGET_INVALID.value, 422)

    both_on_pool = client.create_pledge_agreement(
        create_pledge_agreement_payload(
            member_bank["id"],
            custodian["id"],
            beneficiary_type="POOLED_PROGRAM",
            pooled_program_id=pool["id"],
            deposit_account_id=account["id"],
            agreement_number="AG-2",
        ),
        OFFICER,
    )
    validate_error(both_on_pool, ApiErrorId.ERR_BENEFICIARY_TARGET_INVALID.value, 422)

    foreign_pool = client.create_pledge_agreement(
        create_pledge_agreement_payload(
            outside_bank["id"],
            custodian["id"],
            beneficiary_type="POOLED_PROGRAM",
            pooled_program_id=pool["id"],
            agreement_number="AG-3",
        ),
        OFFICER,
    )
    validate_error(foreign_pool, ApiErrorId.ERR_BENEFICIARY_TARGET_INVALID.value, 422)

    coherent = fixtures.draft_pooled_agreement(
        client, member_bank["id"], custodian["id"], pool["id"], agreement_number="AG-4"
    )
    assert coherent["status"] == "DRAFT"
    assert coherent["deposit_account_id"] is None
    assert coherent["pooled_program_id"] == pool["id"]
    assert coherent["signature_count"] == 0
    assert coherent["amendment_round"] == 0

    _agreements, meta = validate_paginated(
        client.list_pledge_agreements(OFFICER, {"depository_id": outside_bank["id"]})
    )
    assert meta["total_count"] == 0


def test_a_pooled_account_needs_both_a_willing_unit_and_a_member_bank(client):
    """Opening a pooled account fails when the unit prefers dedicated collateral and fails again
    when the bank belongs to no program, yet the pairing that satisfies both halves opens, and a
    dedicated account at that same pooled bank is perfectly legal.

    PRD: "A fourth gate enforces coherence with the unit's declared intent: the requested
    `pledging_mode` must equal the owning public unit's `collateral_program_preference`, and a
    `POOLED` account may only be opened at a depository whose `pooled_program_id` is non-null;
    either violation is refused with `ERR_PLEDGING_MODE_MISMATCH`."
    PRD: "The account also carries `pool_priority_rank`, derived once from its public unit's
    `unit_type`: a `SCHOOL_DISTRICT` ranks 1, a `COUNTY` ranks 2, a `MUNICIPALITY` ranks 3 and a
    `STATE_AGENCY` ranks 4, which is also the field's default."
    PRD: "Accounts still in `PENDING_FUNDING` are **not** participants and receive nothing, even
    though they may already carry a requirement."
    PRD: "At creation the four derived pool figures `aggregate_required_collateral_cents`,
    `aggregate_collateral_value_cents`, `unallocated_collateral_cents` and
    `participant_account_count` are all zero and `pool_posture` is `ADEQUATE`."

    Design: Corner/validations/deposit_account_pledging_mode_mismatch_rejected
    """
    fixtures.set_clock(client)
    pool = fixtures.create_pooled_program(client)
    dedicated_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    pooled_unit = fixtures.create_pooled_public_unit(
        client, name="Ridge Schools", unit_type="SCHOOL_DISTRICT"
    )
    assert dedicated_unit["collateral_program_preference"] == "DEDICATED"
    assert pooled_unit["collateral_program_preference"] == "POOLED"
    outside_bank = fixtures.create_approved_depository(client, name="Plain Bank")
    member_bank = fixtures.create_approved_depository(
        client, name="Pooled Bank", charter_type="NATIONAL", pooled_program_id=pool["id"]
    )

    unwilling_unit = client.create_deposit_account(
        create_deposit_account_payload(
            member_bank["id"], dedicated_unit["id"], pledging_mode="POOLED"
        ),
        make_public_unit_treasurer_headers(dedicated_unit["id"]),
    )
    validate_error(unwilling_unit, ApiErrorId.ERR_PLEDGING_MODE_MISMATCH.value, 422)

    bank_without_pool = client.create_deposit_account(
        create_deposit_account_payload(
            outside_bank["id"], pooled_unit["id"], pledging_mode="POOLED"
        ),
        make_public_unit_treasurer_headers(pooled_unit["id"]),
    )
    validate_error(bank_without_pool, ApiErrorId.ERR_PLEDGING_MODE_MISMATCH.value, 422)

    pooled_account = fixtures.create_deposit_account(
        client, member_bank["id"], pooled_unit["id"], pledging_mode="POOLED"
    )
    assert pooled_account["pledging_mode"] == "POOLED"
    assert pooled_account["pool_priority_rank"] == 1
    assert pooled_account["funding_status"] == "PENDING_FUNDING"
    assert pooled_account["collateral_status"] == "UNSECURED"
    assert pooled_account["pooled_allocated_collateral_cents"] == 0

    dedicated_account = fixtures.create_deposit_account(
        client, member_bank["id"], dedicated_unit["id"], pledging_mode="DEDICATED"
    )
    assert dedicated_account["pledging_mode"] == "DEDICATED"
    assert dedicated_account["pool_priority_rank"] == 2

    program = get_success_data(client.get_pooled_program(pool["id"], REGULATOR), 200)
    assert program["participant_account_count"] == 0
    assert program["pool_posture"] == "ADEQUATE"


def test_a_pledge_may_not_be_empty_inverted_or_older_than_its_own_agreement(client):
    """A zero-length interval, an inverted interval and a start that predates the executed
    agreement are all refused as interval-sanity breaches, while the pledge that begins exactly at
    the agreement's own execution instant is accepted open-ended.

    PRD: "- **Interval sanity.** `effective_from` must be strictly before `effective_to`, and
    `effective_from` must be at or after the agreement's `executed_at` — a pledge cannot predate
    the document that authorises it. A violation is refused with `ERR_INVALID_INTERVAL`."
    PRD: "An optional `effective_to` gives the exclusive end of the occupation interval; when it
    is omitted the allocation is open-ended and the service stores the sentinel instant
    `9999-12-31T00:00:00Z` in its place."
    PRD: "The interval is half-open: it includes `effective_from` and excludes `effective_to`."
    PRD: "21. **Allocation interval sanity** — `ERR_INVALID_INTERVAL` (HTTP 422) on creating a
    pledge allocation whose interval is empty or begins before the agreement was executed."

    Design: Corner/validations/allocation_interval_sanity_violations_rejected
    """
    perimeter = fixtures.build_dedicated_perimeter(client)
    assert perimeter["agreement"]["executed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    asset = fixtures.create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"]
    )
    pinned_version = fixtures.agreement_version(client, perimeter["agreement_id"])

    empty_interval = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            perimeter["agreement_id"],
            asset["id"],
            1_000_000,
            pinned_version,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        ),
        OFFICER,
    )
    validate_error(empty_interval, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)

    inverted_interval = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            perimeter["agreement_id"],
            asset["id"],
            1_000_000,
            pinned_version,
            effective_from="2026-09-02T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        ),
        OFFICER,
    )
    validate_error(inverted_interval, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)

    predates_agreement = client.create_pledge_allocation(
        create_pledge_allocation_payload(
            perimeter["agreement_id"],
            asset["id"],
            1_000_000,
            pinned_version,
            effective_from="2026-07-31T23:59:59Z",
        ),
        OFFICER,
    )
    validate_error(predates_agreement, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)

    accepted = get_success_data(
        client.create_pledge_allocation(
            create_pledge_allocation_payload(
                perimeter["agreement_id"],
                asset["id"],
                1_000_000,
                pinned_version,
                effective_from=DEFAULT_CLOCK_UTC,
            ),
            OFFICER,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["effective_from"] == DEFAULT_CLOCK_UTC
    assert accepted["effective_to"] == OPEN_ENDED_SENTINEL
    assert accepted["allocated_collateral_value_cents"] == 980_000

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["active_allocation_count"] == 1
    assert agreement["total_pledged_par_cents"] == 1_000_000


def test_a_forecast_horizon_must_be_paved_end_to_end_without_gaps_or_overlaps(client):
    """A gap, an overlap, a chain that starts after the horizon and a zero-length leading window
    are each refused, none of them touches the account's version, and the contiguous chain that
    replaces them projects the peak window's requirement against a bank holding no free collateral
    at all.

    PRD: "Any break in that chain is refused with `ERR_FORECAST_WINDOW_DISCONTINUITY`, while a
    horizon whose `horizon_start` is at or after its `horizon_end` is refused with
    `ERR_INVALID_INTERVAL`."
    PRD: "Each window is half-open, including its start and excluding its end, and the chain must
    be exactly contiguous and exactly coextensive with the horizon: every window's `window_start`
    must be strictly before its `window_end`, each window's `window_end` must equal the next
    window's `window_start` with no gaps and no overlaps, the first window's `window_start` must
    equal `horizon_start`, and the last window's `window_end` must equal `horizon_end`."
    PRD: "For each window the projected uninsured amount is `projected_balance_cents` less the
    25,000,000-cent insurance coverage limit, floored at zero; the window's projected requirement
    is that uninsured figure multiplied by the frozen percentage, divided by 10000, rounded half up
    to whole cents."
    PRD: "The forecast's `projected_peak_balance_cents` is the largest `projected_balance_cents`
    across the windows."
    PRD: "Under `PEAK_WINDOW` the forecast takes the largest per-window projected requirement in
    the horizon, on the theory that the treasury must be collateralised for its worst moment, so a
    mid-horizon tax-collection spike sets the plan."
    PRD: "`pledge_capacity_gap_cents` is then the projected requirement less that capacity,
    floored at zero, and it is the number a treasurer takes to the bank: if it is positive, the
    bank does not currently own enough free collateral to cover the forecast cycle."
    PRD: "A filed forecast begins at `status` `OPEN` with `requires_reforecast` false and
    `superseded_at` null."
    PRD: "Because a forecast is a claim about an account, filing one increments that
    `DepositAccount`'s `version` by 1."

    Design: Corner/validations/runoff_forecast_window_chain_discontinuity_rejected
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    treasurer = make_public_unit_treasurer_headers(perimeter["public_unit_id"])
    account_id = perimeter["account_id"]
    pinned_version = fixtures.account_version(client, account_id, treasurer)
    horizon_start = DEFAULT_CLOCK_UTC
    midpoint = "2026-08-15T00:00:00Z"
    horizon_end = "2026-08-31T00:00:00Z"

    broken_chains = [
        [
            projected_window(horizon_start, "2026-08-10T00:00:00Z", 100_000_000),
            projected_window("2026-08-11T00:00:00Z", horizon_end, 20_000_000),
        ],
        [
            projected_window(horizon_start, "2026-08-20T00:00:00Z", 100_000_000),
            projected_window(midpoint, horizon_end, 20_000_000),
        ],
        [
            projected_window("2026-08-02T00:00:00Z", midpoint, 100_000_000),
            projected_window(midpoint, horizon_end, 20_000_000),
        ],
        [
            projected_window(horizon_start, horizon_start, 100_000_000),
            projected_window(horizon_start, horizon_end, 20_000_000),
        ],
    ]
    for windows in broken_chains:
        response = client.create_runoff_forecast(
            create_runoff_forecast_payload(
                account_id, horizon_start, horizon_end, windows, pinned_version
            ),
            treasurer,
        )
        validate_error(response, ApiErrorId.ERR_FORECAST_WINDOW_DISCONTINUITY.value, 422)

    forecast = get_success_data(
        client.create_runoff_forecast(
            create_runoff_forecast_payload(
                account_id,
                horizon_start,
                horizon_end,
                [
                    projected_window(horizon_start, midpoint, 100_000_000),
                    projected_window(midpoint, horizon_end, 20_000_000),
                ],
                pinned_version,
            ),
            treasurer,
        ),
        201,
    )
    assert forecast["status"] == "OPEN"
    assert forecast["requires_reforecast"] is False
    assert forecast["superseded_at"] is None
    assert forecast["projected_peak_balance_cents"] == 100_000_000
    assert forecast["projected_required_collateral_cents"] == 78_750_000
    assert forecast["unpledged_capacity_cents"] == 0
    assert forecast["pledge_capacity_gap_cents"] == 78_750_000

    assert fixtures.account_version(client, account_id, treasurer) == pinned_version + 1

    forecasts, meta = validate_paginated(
        client.list_account_runoff_forecasts(account_id, treasurer)
    )
    assert meta["total_count"] == 1
    assert forecasts[0]["id"] == forecast["id"]


def test_only_new_collateral_of_the_right_size_inside_the_window_can_cure(client):
    """Collateral that was already pledged when the deficiency was measured is refused as
    ineligible, a fresh pledge one cent too large is refused as an overpayment, and once the clock
    reaches the breach deadline the very same offer is refused as out of time — the call is still
    ISSUED with nothing cured even though the bank now holds more than it needs.

    PRD: "Every one of them must be `ACTIVE`, must sit under an agreement in `EXECUTED` status
    belonging to the same depository as the call, must rest on an asset whose `eligibility_status`
    is `ELIGIBLE`, and must have been created strictly after the issuing run's `as_of` — collateral
    that was already pledged when the deficiency was measured cannot be offered a second time to
    cure it."
    PRD: "An offered allocation resting on an ineligible asset or an ineligible asset type is
    caught by the collateral-type rung and reported as `ERR_COLLATERAL_TYPE_INELIGIBLE`; any other
    failure of the four conditions is reported as `ERR_CURE_ALLOCATION_INELIGIBLE`, and one bad
    identifier spoils the whole request."
    PRD: "Overpayment is not tolerated at all: the tolerance for exceeding the call is zero cents,
    so a credited value strictly greater than the call's current `outstanding_cents` is refused
    with `ERR_CURE_EXCEEDS_OUTSTANDING`."
    PRD: "Cures may be posted only while the logical clock is strictly before the call's
    `breach_deadline_at`; a later attempt is refused with `ERR_CURE_WINDOW_CLOSED`."
    PRD: "Its `cure_deadline_at` is the run's `as_of` advanced by a number of hours that depends on
    how badly the bank is short: 24 hours when `deficiency_ratio_bps` is at least 2000, otherwise
    48 hours when it is at least 500, and otherwise 120 hours, which is five full days for a
    trivial shortfall."
    PRD: "Its `breach_deadline_at` is `cure_deadline_at` advanced by a further 24 hours of
    escalation grace."

    Design: Corner/validations/margin_call_cure_credit_guards_rejected
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    pre_run_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=8_750_000,
    )
    pre_run_allocation = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        pre_run_asset["id"],
        8_750_000,
        effective_from=DEFAULT_CLOCK_UTC,
    )
    assert pre_run_allocation["allocated_collateral_value_cents"] == 8_750_000

    run = fixtures.create_mtm_run(
        client,
        perimeter["depository_id"],
        "2026-07-31T00:00:00Z",
        DEFAULT_CLOCK_UTC,
        basis="SUPERVISORY",
    )
    assert run["as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert run["total_required_collateral_cents"] == 78_750_000
    assert run["total_collateral_value_cents"] == 8_750_000
    assert run["deficiency_cents"] == 70_000_000
    assert run["deficiency_ratio_bps"] == 8888
    assert run["outcome"] == "DEFICIENT"

    call = fixtures.latest_margin_call(client, perimeter["depository_id"])
    assert call["required_cure_cents"] == 70_000_000
    assert call["outstanding_cents"] == 70_000_000
    assert call["status"] == "ISSUED"
    assert call["cure_deadline_at"] == clock_stamp("2026-08-02T00:00:00Z")
    assert call["breach_deadline_at"] == clock_stamp(THIRD_DAY)

    fixtures.set_clock(client, SIX_AM)
    fresh_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=70_000_001,
    )
    fresh_allocation = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        fresh_asset["id"],
        70_000_001,
        effective_from=SIX_AM,
    )
    assert fresh_allocation["allocated_collateral_value_cents"] == 70_000_001

    stale_credit = client.cure_margin_call(
        call["id"], cure_payload([pre_run_allocation["id"]]), OFFICER
    )
    validate_error(stale_credit, ApiErrorId.ERR_CURE_ALLOCATION_INELIGIBLE.value, 422)

    overpayment = client.cure_margin_call(
        call["id"], cure_payload([fresh_allocation["id"]]), OFFICER
    )
    validate_error(overpayment, ApiErrorId.ERR_CURE_EXCEEDS_OUTSTANDING.value, 422)

    fixtures.set_clock(client, THIRD_DAY)
    too_late = client.cure_margin_call(
        call["id"], cure_payload([fresh_allocation["id"]]), OFFICER
    )
    validate_error(too_late, ApiErrorId.ERR_CURE_WINDOW_CLOSED.value, 409)

    unmoved = get_success_data(client.get_margin_call(call["id"], OFFICER), 200)
    assert unmoved["status"] == "ISSUED"
    assert unmoved["cured_cents"] == 0
    assert unmoved["outstanding_cents"] == 70_000_000
    assert unmoved["cured_at"] is None

    bank = get_success_data(
        client.get_depository(perimeter["depository_id"], OFFICER), 200
    )
    assert bank["open_margin_call_count"] == 1
    assert bank["collateral_posture"] == "MARGIN_DEFICIENT"

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 78_750_001
    assert account["collateral_status"] == "SECURED"


def test_a_substitution_may_only_name_a_live_allocation_of_its_own_agreement(client):
    """An allocation belonging to the bank's other agreement and an allocation that has already
    been released are refused with the same message, so the request that finally lands is the one
    naming a still-active allocation of the agreement it operates under.

    PRD: "The named outgoing allocation must genuinely belong to the named agreement and must still
    be `ACTIVE`; otherwise the request is refused with `ERR_ALLOCATION_NOT_UNDER_AGREEMENT`."
    PRD: "An admitted request begins at `status` `SUBMITTED` with `submitted_by_user_id` recording
    the requesting officer's `X-User-ID`, with `compliance_approved_at`,
    `compliance_approved_by_user_id`, `custodian_acked_at`, `settled_at`, `rejection_reason` and
    `value_adequacy_delta_cents` all null."
    PRD: "From `pledged_par_cents` the service also derives `pledge_status`: `UNPLEDGED` when
    nothing is pledged, `PARTIALLY_PLEDGED` when some but not all of the par is pledged, and
    `FULLY_PLEDGED` when the pledged par equals `par_value_cents` exactly."

    Design: Corner/validations/substitution_outgoing_allocation_not_under_named_agreement_rejected
    """
    perimeter = fixtures.build_dedicated_perimeter(client)
    other_agreement = fixtures.create_executed_dedicated_agreement(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        perimeter["account_id"],
        perimeter["public_unit_id"],
    )
    released_asset = fixtures.create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"]
    )
    live_asset = fixtures.create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"]
    )
    incoming_asset = fixtures.create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"], cusip="CU-IN"
    )
    released_allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], released_asset["id"], 10_000_000
    )
    live_allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], live_asset["id"], 10_000_000
    )
    retired = fixtures.release_allocation(client, released_allocation["id"])
    assert retired["status"] == "RELEASED"

    wrong_agreement = client.create_substitution_request(
        create_substitution_request_payload(
            other_agreement["id"],
            live_allocation["id"],
            incoming_asset["id"],
            10_000_000,
        ),
        OFFICER,
    )
    validate_error(
        wrong_agreement, ApiErrorId.ERR_ALLOCATION_NOT_UNDER_AGREEMENT.value, 422
    )

    dead_allocation = client.create_substitution_request(
        create_substitution_request_payload(
            perimeter["agreement_id"],
            released_allocation["id"],
            incoming_asset["id"],
            10_000_000,
        ),
        OFFICER,
    )
    validate_error(
        dead_allocation, ApiErrorId.ERR_ALLOCATION_NOT_UNDER_AGREEMENT.value, 422
    )

    admitted = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        live_allocation["id"],
        incoming_asset["id"],
        10_000_000,
    )
    assert admitted["status"] == "SUBMITTED"
    assert admitted["submitted_by_user_id"] == OFFICER_USER_ID
    assert admitted["compliance_approved_at"] is None
    assert admitted["custodian_acked_at"] is None
    assert admitted["value_adequacy_delta_cents"] is None

    _requests, meta = validate_paginated(
        client.list_substitution_requests(
            OFFICER, {"pledge_agreement_id": other_agreement["id"]}
        )
    )
    assert meta["total_count"] == 0

    idle = get_success_data(client.get_pledge_agreement(other_agreement["id"], OFFICER), 200)
    assert idle["active_allocation_count"] == 0
    working = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert working["active_allocation_count"] == 1
    assert working["total_pledged_par_cents"] == 10_000_000

    freed = get_success_data(client.get_collateral_asset(released_asset["id"], OFFICER), 200)
    assert freed["pledge_status"] == "UNPLEDGED"
    assert freed["available_par_cents"] == 10_000_000


def test_no_signatory_may_stamp_another_partys_line_or_its_own_twice(client):
    """The custodian is entitled to exactly one of the three lines: its attempts on the depository
    and public-unit lines are refused as party mismatches, and once it has stamped its own line a
    second attempt is refused as a duplicate without overwriting the original timestamp — the third
    distinct party still executes the document.

    PRD: "The `DEPOSITORY` party may be stamped only by a `BankComplianceOfficer` — the bank's
    second line signs for the bank, never its first line."
    PRD: "A role attempting a party it is not entitled to is refused with
    `ERR_SIGNATURE_PARTY_MISMATCH` (HTTP 403); a party whose stamp is already set in the current
    round is refused with `ERR_PARTY_ALREADY_SIGNED` (HTTP 409)."
    PRD: "Each accepted signature stamps the matching `_signed_at` field with the logical clock,
    recomputes `signature_count` as the number of non-null party stamps, and increments the
    agreement's `version`."
    PRD: "The signature that supplies the third distinct party — that is, the one arriving when
    `signature_count` stood at 2 — carries the agreement to `EXECUTED`, sets `signature_count` to 3
    and stamps `executed_at` from the clock."

    Design: Corner/validations/signature_party_and_duplicate_party_guards_rejected
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client, tri_party_capable=True)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_deposit_account(client, depository["id"], public_unit["id"])
    draft = fixtures.draft_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"]
    )
    agreement = fixtures.circulate(client, draft["id"])
    assert agreement["status"] == "PENDING_SIGNATURES"
    assert agreement["signature_count"] == 0
    custodian_headers = make_custodian_headers(custodian["id"])

    for party in ("DEPOSITORY", "PUBLIC_UNIT"):
        response = client.create_signature(
            agreement["id"], signature_payload(party), custodian_headers
        )
        validate_error(response, ApiErrorId.ERR_SIGNATURE_PARTY_MISMATCH.value, 403)

    untouched = get_success_data(client.get_pledge_agreement(agreement["id"], OFFICER), 200)
    assert untouched["status"] == "PENDING_SIGNATURES"
    assert untouched["signature_count"] == 0
    assert untouched["depository_signed_at"] is None
    assert untouched["public_unit_signed_at"] is None
    assert untouched["custodian_signed_at"] is None

    custodian_signed = fixtures.sign(
        client, agreement["id"], "CUSTODIAN", custodian_headers
    )
    assert custodian_signed["signature_count"] == 1
    assert custodian_signed["custodian_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    repeat = client.create_signature(
        agreement["id"], signature_payload("CUSTODIAN"), custodian_headers
    )
    validate_error(repeat, ApiErrorId.ERR_PARTY_ALREADY_SIGNED.value, 409)
    after_repeat = get_success_data(
        client.get_pledge_agreement(agreement["id"], OFFICER), 200
    )
    assert after_repeat["signature_count"] == 1
    assert after_repeat["custodian_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert after_repeat["status"] == "PENDING_SIGNATURES"

    bank_signed = fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)
    assert bank_signed["signature_count"] == 2
    assert bank_signed["depository_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert bank_signed["status"] == "PENDING_SIGNATURES"

    executed = fixtures.sign(
        client,
        agreement["id"],
        "PUBLIC_UNIT",
        make_public_unit_treasurer_headers(public_unit["id"]),
    )
    assert executed["signature_count"] == 3
    assert executed["status"] == "EXECUTED"
    assert executed["executed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)


def test_a_rotting_bank_is_shut_out_first_by_its_grade_and_then_by_its_freeze(client):
    """One deficient run alone drops the bank to grade D and its next applicant is turned away on
    the grade; three consecutive deficient runs freeze it and the identical request is then turned
    away on the posture instead, which is the ordering the ladder promises.

    PRD: "14. **Risk-grade gate** — the depository's `risk_grade` is not `D`, else
    `ERR_DEPOSITORY_RISK_GRADE_BLOCKED` (HTTP 409). This rung guards exactly one operation: opening
    a new deposit account."
    PRD: "9. **Depository posture** — the depository's `collateral_posture` is not `FROZEN`, else
    `ERR_DEPOSITORY_POSTURE_FROZEN` (HTTP 409). This rung guards exactly two operations: opening a
    new deposit account and creating a new substitution request."
    PRD: "A frozen depository's rejection surfaces as `ERR_DEPOSITORY_POSTURE_FROZEN` rather than
    being masked by a later referential check, and a stale parent version surfaces as its own 412
    before any state, posture or business check runs, so a client holding an outdated read learns
    that fact first."
    PRD: "Three gates guard the opening beyond the ordinary ones: the depository's
    `approval_status` must be `APPROVED`, its `collateral_posture` must not be `FROZEN`, and its
    `risk_grade` must not be `D`."
    PRD: "The **volatility component**, `volatility_component_bps`, is 10000 less the lesser of
    10000 and the depository's `consecutive_deficiency_runs` multiplied by 2500 — and here the
    counter is the value **after** step six, not the snapshot."
    PRD: "The run's `deficiency_surcharge_bps_applied` is 1000 basis points when the snapshot is 2
    or more, and zero otherwise."
    PRD: "Step three adds a deficiency surcharge of 1000 basis points when the depository's
    `consecutive_deficiency_runs` counter stands at 2 or more, and nothing otherwise; inside a
    mark-to-market run the counter used here is the snapshot taken before the run mutates it, never
    the post-run value."
    PRD: "Either way the depository's `mtm_run_index` is set to the run's `run_index`, its
    `last_mtm_window_end` is set to the run's `window_end`, and its `collateral_posture` is
    re-derived: `FROZEN` when `consecutive_deficiency_runs` has reached 3 or more, otherwise
    `MARGIN_DEFICIENT` when `open_margin_call_count` is 1 or more, otherwise `COMPLIANT`."

    Design: Corner/validations/new_account_blocked_first_by_risk_grade_then_by_frozen_posture
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    depository_id = perimeter["depository_id"]
    treasurer = make_public_unit_treasurer_headers(perimeter["public_unit_id"])
    applicant = create_deposit_account_payload(
        depository_id,
        perimeter["public_unit_id"],
        deposit_class="TIME_AND_SAVINGS",
        pledging_mode="DEDICATED",
    )

    first_run = fixtures.create_mtm_run(
        client, depository_id, "2026-07-31T00:00:00Z", DEFAULT_CLOCK_UTC, basis="SUPERVISORY"
    )
    assert first_run["deficiency_surcharge_bps_applied"] == 0
    assert first_run["total_required_collateral_cents"] == 78_750_000
    assert first_run["total_collateral_value_cents"] == 0
    assert first_run["deficiency_cents"] == 78_750_000
    assert first_run["coverage_component_bps"] == 0
    assert first_run["volatility_component_bps"] == 7500
    assert first_run["documentation_component_bps"] == 10000
    assert first_run["risk_score_bps"] == 4250
    assert first_run["risk_grade_assigned"] == "D"

    after_first = get_success_data(client.get_depository(depository_id, OFFICER), 200)
    assert after_first["consecutive_deficiency_runs"] == 1
    assert after_first["risk_grade"] == "D"
    assert after_first["collateral_posture"] == "MARGIN_DEFICIENT"

    graded_out = client.create_deposit_account(applicant, treasurer)
    validate_error(graded_out, ApiErrorId.ERR_DEPOSITORY_RISK_GRADE_BLOCKED.value, 409)

    fixtures.set_clock(client, FIVE_AM)
    second_run = fixtures.create_mtm_run(
        client, depository_id, "2026-08-01T04:00:00Z", FIVE_AM, basis="SUPERVISORY"
    )
    assert second_run["deficiency_surcharge_bps_applied"] == 0
    assert second_run["total_required_collateral_cents"] == 78_750_000
    assert second_run["volatility_component_bps"] == 5000
    assert second_run["risk_score_bps"] == 3500
    assert second_run["risk_grade_assigned"] == "D"

    after_second = get_success_data(client.get_depository(depository_id, OFFICER), 200)
    assert after_second["consecutive_deficiency_runs"] == 2
    assert after_second["collateral_posture"] == "MARGIN_DEFICIENT"

    fixtures.set_clock(client, TEN_AM)
    third_run = fixtures.create_mtm_run(
        client, depository_id, "2026-08-01T09:00:00Z", TEN_AM, basis="SUPERVISORY"
    )
    assert third_run["deficiency_surcharge_bps_applied"] == 1000
    assert third_run["total_required_collateral_cents"] == 86_250_000
    assert third_run["deficiency_cents"] == 86_250_000
    assert third_run["volatility_component_bps"] == 2500
    assert third_run["risk_score_bps"] == 2750
    assert third_run["risk_grade_assigned"] == "D"

    frozen = get_success_data(client.get_depository(depository_id, OFFICER), 200)
    assert frozen["consecutive_deficiency_runs"] == 3
    assert frozen["open_margin_call_count"] == 3
    assert frozen["collateral_posture"] == "FROZEN"
    assert frozen["risk_grade"] == "D"

    frozen_out = client.create_deposit_account(applicant, treasurer)
    validate_error(frozen_out, ApiErrorId.ERR_DEPOSITORY_POSTURE_FROZEN.value, 409)

    _accounts, meta = validate_paginated(
        client.list_deposit_accounts(treasurer, {"depository_id": depository_id})
    )
    assert meta["total_count"] == 1


def test_the_compliance_branch_refuses_a_swap_that_would_lose_value(client):
    """The second line prices the incoming pledge before it approves: a like-for-like par swap into
    a heavier-haircut security is a shortfall and is refused with nothing stamped, while the same
    swap sized up by 1,000,000 cents of par clears with a positive adequacy delta.

    PRD: "This branch, and only this branch, computes and stores `value_adequacy_delta_cents`: the
    haircut value the incoming pledge would carry, obtained by applying the two-step valuation of
    §3.4 to `incoming_par_cents` on the incoming asset, less the outgoing allocation's current
    `allocated_collateral_value_cents`."
    PRD: "The delta must be zero or positive, meaning the incoming collateral is worth at least as
    much as what it replaces; a negative delta is refused with
    `ERR_SUBSTITUTION_VALUE_SHORTFALL`."
    PRD: "On success the branch stamps `compliance_approved_at` from the clock, records the
    approver as `compliance_approved_by_user_id`, and increments the request's `version`."
    PRD: "No par moves on this branch."
    PRD: "32. **Substitution value adequacy** — `ERR_SUBSTITUTION_VALUE_SHORTFALL` (HTTP 422) when
    the incoming collateral is worth less than the outgoing collateral it replaces, on compliance
    approval of a substitution."

    Design: Corner/validations/substitution_incoming_value_shortfall_rejected_at_compliance_approve
    """
    perimeter = fixtures.build_dedicated_perimeter(client)
    outgoing_assets = [
        fixtures.create_collateral_asset(
            client, perimeter["depository_id"], perimeter["custodian_id"]
        )
        for _ in range(2)
    ]
    allocations = [
        fixtures.create_allocation(
            client, perimeter["agreement_id"], asset["id"], 10_000_000
        )
        for asset in outgoing_assets
    ]
    for allocation in allocations:
        assert allocation["allocated_collateral_value_cents"] == 9_800_000

    light_muni = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="MUNI_GO",
        par_value_cents=10_000_000,
    )
    heavy_muni = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="MUNI_GO",
        par_value_cents=11_000_000,
    )

    shortfall = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        allocations[0]["id"],
        light_muni["id"],
        10_000_000,
    )
    assert shortfall["value_adequacy_delta_cents"] is None

    refused = client.compliance_approve_substitution(shortfall["id"], COMPLIANCE)
    validate_error(refused, ApiErrorId.ERR_SUBSTITUTION_VALUE_SHORTFALL.value, 422)
    unstamped = get_success_data(
        client.get_substitution_request(shortfall["id"], OFFICER), 200
    )
    assert unstamped["status"] == "SUBMITTED"
    assert unstamped["compliance_approved_at"] is None
    assert unstamped["compliance_approved_by_user_id"] is None
    assert unstamped["value_adequacy_delta_cents"] is None

    adequate = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        allocations[1]["id"],
        heavy_muni["id"],
        11_000_000,
    )
    approved = fixtures.compliance_approve(client, adequate["id"])
    assert approved["status"] == "COMPLIANCE_APPROVED"
    assert approved["value_adequacy_delta_cents"] == 100_000
    assert approved["compliance_approved_by_user_id"] == COMPLIANCE_USER_ID
    assert approved["compliance_approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    for muni in (light_muni, heavy_muni):
        untouched = get_success_data(client.get_collateral_asset(muni["id"], OFFICER), 200)
        assert untouched["pledge_status"] == "UNPLEDGED"
        assert untouched["pledged_par_cents"] == 0

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_pledged_par_cents"] == 20_000_000
    assert agreement["active_allocation_count"] == 2
