"""
Error corners of the Digital Estate Fiduciary Access API.

Three clusters of guards in this contract are easy to collapse into one another:
the four gates on a disposition election, the two eligibility gates on a refund
claim, and the three fiscal preconditions on a transfer execution. Each test
below drives one guard on its own so that the error identifier and its HTTP
status are pinned individually, and drives the ordering that decides which of
two competing guards reports.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    factories as f,
    fixtures as fx,
    make_platform_compliance_headers,
)
from test_helpers.api_errors import (
    ERR_ASSET_NOT_TRANSFERABLE,
    ERR_BENEFICIARY_ALLOCATION_EXCEEDED,
    ERR_BENEFICIARY_REQUIRED,
    ERR_DISPOSITION_UNSUPPORTED,
    ERR_DISTRIBUTION_POOL_EXHAUSTED,
    ERR_INVALID_ELECTION_STATE,
    ERR_REFUND_NOT_OFFERED,
    ERR_SUBSCRIPTION_TERM_MISSING,
    ERR_VALUATION_REQUIRED,
)
from test_helpers.constants import (
    BASIS_ALTERNATE,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_EMAIL,
    CLAIM_FILED,
    CLOCK_EPOCH,
    DISPOSITION_ELECTED,
    DISPOSITION_PENDING,
    ELECTION_DELETE,
    ELECTION_EXECUTED,
    ELECTION_MEMORIALIZE,
    ELECTION_PENDING_COUNTERSIGN,
    ELECTION_TRANSFER,
    EL_ACTION_EXECUTE,
    EL_ACTION_SUBMIT,
    METHOD_PRORATA_DAILY,
    NON_TRANSFERABLE,
    REFUND_POLICY_NONE,
    REFUND_POLICY_PRORATA_DAILY,
    RUN_SUPERSEDED,
    TRANSFERABLE,
)


def _election_estate(api, case_number):
    """A provider that refuses memorialization, one EMAIL and one cloud account, one heir."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api, supports_memorialization=False)
    ctx = fx.authorized_estate(api, case_number)
    mail = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_EMAIL, account_handle="mail-1", quoted_value_cents=0,
    )
    vault = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=200000,
    )
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    heir = fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives", relationship="child")
    assert mail["transferability"] == NON_TRANSFERABLE
    assert vault["transferability"] == TRANSFERABLE
    return platform, ctx, mail, vault, heir


def test_transferring_a_personal_account_names_the_transferability_guard(api):
    """
    An EMAIL account is personal to the decedent and never transferable, so an
    otherwise perfectly formed TRANSFER election naming a beneficiary is refused
    with ERR_ASSET_NOT_TRANSFERABLE.

    PRD §3.9: A `TRANSFER` requires the account's `transferability` to be exactly `TRANSFERABLE`, or the election is refused with `ERR_ASSET_NOT_TRANSFERABLE`.

    Design: Corner/errors/every_election_guard_names_its_own_error_and_persists_nothing
    """
    _platform, ctx, mail, _vault, heir = _election_estate(api, "PR-2737-C33A")

    version = fx.asset_version(api, ctx, mail["id"])
    response = api.create_disposition_election(
        mail["id"],
        f.election_payload(
            version,
            election=ELECTION_TRANSFER,
            beneficiary_designation_id=heir["id"],
            election_note="hand over the mailbox",
        ),
        ctx.fid_headers,
    )
    validate_error(response, ERR_ASSET_NOT_TRANSFERABLE)


def test_electing_a_disposition_the_provider_refuses_names_the_support_guard(api):
    """
    The provider hosting the cloud account does not memorialize, so a
    MEMORIALIZE election against a transferable, disclosed account is refused
    with ERR_DISPOSITION_UNSUPPORTED rather than any transferability error.

    PRD §3.9: The provider must support the elected disposition — its `supports_memorialization`, `supports_deletion` or `supports_transfer` flag, whichever corresponds — or the election is refused with `ERR_DISPOSITION_UNSUPPORTED`.

    Design: Corner/errors/every_election_guard_names_its_own_error_and_persists_nothing
    """
    _platform, ctx, _mail, vault, _heir = _election_estate(api, "PR-2737-C33B")

    version = fx.asset_version(api, ctx, vault["id"])
    response = api.create_disposition_election(
        vault["id"],
        f.election_payload(
            version, election=ELECTION_MEMORIALIZE, election_note="freeze the archive"
        ),
        ctx.fid_headers,
    )
    validate_error(response, ERR_DISPOSITION_UNSUPPORTED)


@pytest.mark.parametrize("direction", ["transfer_without_a_designation", "delete_with_a_designation"])
def test_both_directions_of_the_beneficiary_linkage_rule_report_the_same_code(api, direction):
    """
    The beneficiary linkage rule is symmetrical: a TRANSFER that names nobody and
    a DELETE that names somebody are both ERR_BENEFICIARY_REQUIRED at HTTP 400.

    PRD §3.9: And the beneficiary linkage must match the election exactly: `beneficiary_designation_id` is required for a `TRANSFER` and must be absent for a `MEMORIALIZE` or a `DELETE`, with either violation reported as `ERR_BENEFICIARY_REQUIRED` at HTTP 400.

    Design: Corner/errors/every_election_guard_names_its_own_error_and_persists_nothing
    """
    _platform, ctx, mail, vault, heir = _election_estate(api, "PR-2737-C33C")

    if direction == "transfer_without_a_designation":
        asset_id = vault["id"]
        payload_extras = {
            "election": ELECTION_TRANSFER,
            "election_note": "transfer without naming anybody",
        }
    else:
        asset_id = mail["id"]
        payload_extras = {
            "election": ELECTION_DELETE,
            "beneficiary_designation_id": heir["id"],
            "election_note": "delete but also name a beneficiary",
        }

    version = fx.asset_version(api, ctx, asset_id)
    response = api.create_disposition_election(
        asset_id, f.election_payload(version, **payload_extras), ctx.fid_headers
    )
    validate_error(response, ERR_BENEFICIARY_REQUIRED)


def test_a_delete_election_cannot_reach_submitted_without_a_countersignature(api):
    """
    A DELETE election opens at PENDING_COUNTERSIGN with no countersigner and
    still advances the account's version by one. Submission is defined only from
    DRAFT, so an uncountersigned submission is refused on the entity-state band
    of the §2.7 ladder, and the account's disposition posture stays PENDING
    because no submission ever landed.

    PRD §3.9: A `DELETE` election opens at `PENDING_COUNTERSIGN`, because deletion destroys an account permanently and one fiduciary acting alone may not order it.

    PRD §3.9: Creation also increases the account's `version` by one, which is why a second election attempt built on a stale reading fails the concurrency check with `ERR_STALE_ASSET_VERSION`.

    PRD §3.9: Submission advances the election `DRAFT → SUBMITTED` and is a `Fiduciary` action.

    PRD §2.7: Estate closure first (`ERR_ESTATE_CLOSED`, 409), then whether the target record is in a state from which the submitted action is defined, per entity in this order: document (`ERR_INVALID_DOCUMENT_STATE`), platform request (`ERR_INVALID_REQUEST_STATE`), authority grant (`ERR_INVALID_GRANT_STATE`), disposition election (`ERR_INVALID_ELECTION_STATE`), cancellation order (`ERR_INVALID_ORDER_STATE`), refund claim (`ERR_INVALID_CLAIM_STATE`), valuation run (`ERR_INVALID_RUN_STATE`) — all HTTP 409 — and lastly the once-per-estate finalization guard (`ERR_VALUATION_ALREADY_FINALIZED`, 409).

    Design: Corner/errors/every_election_guard_names_its_own_error_and_persists_nothing
    """
    _platform, ctx, _mail, vault, _heir = _election_estate(api, "PR-2737-C33D")

    version_before = fx.asset_version(api, ctx, vault["id"])
    election = validate_success(
        api.create_disposition_election(
            vault["id"],
            f.election_payload(
                version_before, election=ELECTION_DELETE, election_note="purge the archive"
            ),
            ctx.fid_headers,
        ),
        201,
    )
    assert election["status"] == ELECTION_PENDING_COUNTERSIGN
    assert election["countersigned_by_fiduciary_id"] is None
    assert fx.asset_version(api, ctx, vault["id"]) == version_before + 1

    validate_error(
        api.transition_disposition_election(
            election["id"], f.election_transition_payload(EL_ACTION_SUBMIT), ctx.fid_headers
        ),
        ERR_INVALID_ELECTION_STATE,
    )

    assert fx.read_asset(api, ctx, vault["id"])["disposition_status"] == DISPOSITION_PENDING


def _refund_estate(api, case_number):
    """Two subscription providers, one refunding pro rata and one refunding nothing."""
    fx.set_clock(api, CLOCK_EPOCH)
    p1 = fx.register_subscription_platform(
        api, name="StreamOne", form_code="S1-FORM", refund_policy=REFUND_POLICY_PRORATA_DAILY
    )
    p2 = fx.register_subscription_platform(
        api, name="StreamTwo", form_code="S2-FORM", refund_policy=REFUND_POLICY_NONE
    )
    ctx = fx.authorized_estate(api, case_number)
    s1 = fx.add_subscription_asset(api, ctx, p1["id"], account_handle="s1")
    s2 = fx.add_subscription_asset(api, ctx, p2["id"], account_handle="s2")
    term_s2 = fx.add_subscription_term(api, ctx, s2["id"])

    fx.approved_request(api, ctx, p1["id"], p1["form_code"])
    fx.approved_request(api, ctx, p2["id"], p2["form_code"])

    order1 = fx.cancellation_order_for_asset(api, ctx, s1["id"])
    order2 = fx.cancellation_order_for_asset(api, ctx, s2["id"])
    assert order1["refund_policy_snapshot"] == REFUND_POLICY_PRORATA_DAILY
    assert order2["refund_policy_snapshot"] == REFUND_POLICY_NONE

    order1 = fx.confirmed_cancellation_order(
        api, ctx, p1["id"], order1["id"],
        effective_date="2026-06-30", platform_reference="S1-CANCEL",
    )
    order2 = fx.confirmed_cancellation_order(
        api, ctx, p2["id"], order2["id"],
        effective_date="2026-06-30", platform_reference="S2-CANCEL",
    )
    return p1, p2, ctx, s1, s2, term_s2, order1, order2


def test_a_claim_on_an_account_with_no_term_names_the_missing_term(api):
    """
    The pro-rata provider's order carries a refundable snapshot, but the account
    behind it never had a subscription term recorded, so there are no numbers to
    compute an entitlement from and the filing is refused with
    ERR_SUBSCRIPTION_TERM_MISSING.

    PRD §3.7: First, the account must actually have a `SubscriptionTerm`, since the entitlement is computed from the term's own numbers; without one the filing is refused with `ERR_SUBSCRIPTION_TERM_MISSING`.

    Design: Corner/errors/refund_eligibility_is_read_from_the_term_and_the_frozen_policy_snapshot
    """
    _p1, _p2, ctx, _s1, _s2, _term_s2, order1, _order2 = _refund_estate(api, "PR-2737-C34A")

    response = api.create_refund_claim(
        order1["id"],
        f.refund_claim_payload("2026-05-01", "2026-06-30", pursuit_cost_cents=300),
        ctx.fid_headers,
    )
    validate_error(response, ERR_SUBSCRIPTION_TERM_MISSING)


def test_a_frozen_none_snapshot_survives_a_later_provider_policy_change(api):
    """
    The second provider offered no refund when its order was opened, so a claim
    against that order is refused with ERR_REFUND_NOT_OFFERED even though the
    account does carry a term. PATCHing the provider to PRORATA_DAILY afterwards
    changes nothing: the order's snapshot was taken once, so the same claim is
    refused again with the same code.

    PRD §3.7: Second, the order's `refund_policy_snapshot` must not be `NONE`, or the filing is refused with `ERR_REFUND_NOT_OFFERED` — and because the snapshot was frozen at order creation, a later change to the provider's `refund_policy` can neither open nor close this door.

    PRD §3.6: The snapshot is taken once and never refreshed, so a provider that changes its refund terms afterwards does not change the terms of orders already opened.

    Design: Corner/errors/refund_eligibility_is_read_from_the_term_and_the_frozen_policy_snapshot
    """
    _p1, p2, ctx, _s1, _s2, _term_s2, _order1, order2 = _refund_estate(api, "PR-2737-C34B")

    validate_error(
        api.create_refund_claim(
            order2["id"],
            f.refund_claim_payload("2026-05-01", "2026-06-30", pursuit_cost_cents=300),
            ctx.fid_headers,
        ),
        ERR_REFUND_NOT_OFFERED,
    )

    patched = fx.patch_platform(api, p2["id"], refund_policy=REFUND_POLICY_PRORATA_DAILY)
    assert patched["refund_policy"] == REFUND_POLICY_PRORATA_DAILY

    validate_error(
        api.create_refund_claim(
            order2["id"],
            f.refund_claim_payload("2026-05-01", "2026-06-30", pursuit_cost_cents=300),
            ctx.fid_headers,
        ),
        ERR_REFUND_NOT_OFFERED,
    )
    assert fx.read_order(api, ctx, order2["id"])["refund_policy_snapshot"] == REFUND_POLICY_NONE


def test_recording_the_missing_term_lets_the_pro_rata_claim_through(api):
    """
    Recording the absent term on the pro-rata provider's account opens the door
    the first filing found shut: a sixty-one day claim inside a three-hundred and
    sixty-five day term worth 11999 cents is entitled to 2005 cents, opens FILED
    with nothing credited yet, copies PRORATA_DAILY out of the order's snapshot,
    and raises the term's claimed-day total by its own sixty-one days.

    PRD §3.7: The term is a **closed** interval: both endpoints are inside it, so `term_days` is the number of days from `term_start_date` to `term_end_date` plus one, and a term whose two dates are equal is one day long.

    PRD §3.7: Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share.

    PRD §3.7: A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`.

    Design: Corner/errors/refund_eligibility_is_read_from_the_term_and_the_frozen_policy_snapshot
    """
    _p1, _p2, ctx, s1, _s2, _term_s2, order1, _order2 = _refund_estate(api, "PR-2737-C34C")

    term_s1 = fx.add_subscription_term(api, ctx, s1["id"])
    assert term_s1["claimed_days_total"] == 0

    claim = validate_success(
        api.create_refund_claim(
            order1["id"],
            f.refund_claim_payload("2026-05-01", "2026-06-30", pursuit_cost_cents=300),
            ctx.fid_headers,
        ),
        201,
    )
    assert claim["status"] == CLAIM_FILED
    assert claim["method"] == METHOD_PRORATA_DAILY
    assert claim["claimed_cents"] == 2005
    assert claim["credited_cents"] == 0

    assert fx.read_term(api, ctx, term_s1["id"])["claimed_days_total"] == 61


def _two_vault_estate(api, case_number):
    """One cloud provider, two disclosed cloud accounts worth 100000 each, two heirs."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, case_number)
    a1 = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=100000,
    )
    a2 = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-2", quoted_value_cents=100000,
    )
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    bd1 = fx.add_beneficiary(
        api, ctx, beneficiary_name="Kai Ives", share_bp=9000, relationship="child"
    )
    bd2 = fx.add_beneficiary(
        api, ctx, beneficiary_name="Lior Ives", share_bp=1000, relationship="nephew"
    )
    assert fx.read_asset(api, ctx, a1["id"])["transferability"] == TRANSFERABLE
    return platform, ctx, a1, a2, bd1, bd2


def test_executing_a_transfer_before_any_valuation_names_the_appraisal_gate(api):
    """
    A transfer election reaches SUBMITTED on an unvalued estate, but there is no
    appraisal behind it: the account's appraised value is still null and no run
    exists, so the provider's desk cannot execute it and the attempt is refused
    with ERR_VALUATION_REQUIRED.

    PRD §3.9: The account's `transferability` must be `TRANSFERABLE` and its `appraised_value_cents` must be non-null with a `COMPUTED` or `FINALIZED` valuation run in existence, or the execution is refused with `ERR_VALUATION_REQUIRED`: nothing may be distributed before the estate has been valued.

    Design: Corner/errors/transfer_execution_needs_an_appraisal_then_hits_the_pool_before_the_share
    """
    platform, ctx, a1, _a2, bd1, _bd2 = _two_vault_estate(api, "PR-2737-C35A")

    assert fx.read_asset(api, ctx, a1["id"])["appraised_value_cents"] is None

    el1 = fx.submitted_election(
        api, ctx, a1["id"],
        election=ELECTION_TRANSFER, beneficiary_designation_id=bd1["id"],
    )

    validate_error(
        api.transition_disposition_election(
            el1["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-XFER-1"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        ERR_VALUATION_REQUIRED,
    )


def test_a_second_transfer_to_the_smaller_share_hits_the_allocation_ceiling(api):
    """
    A valuation of two 100000-cent accounts plans 180000 to the nine-tenths heir
    and 20000 to the one-tenth heir with no remainder. The first transfer lands
    inside the larger plan and moves exactly 100000 out of the pool. The second
    account, worth another 100000, still fits the remaining pool exactly but is
    aimed at the heir whose plan is only 20000, so the execution is refused with
    ERR_BENEFICIARY_ALLOCATION_EXCEEDED.

    PRD §3.8: In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded.

    PRD §3.9: And the named designation's `received_value_cents` plus the account's `appraised_value_cents` must not exceed that designation's `planned_allocation_cents`, with exact equality accepted and any excess refused as `ERR_BENEFICIARY_ALLOCATION_EXCEEDED`, so no beneficiary can be handed more than the plan of §3.8 allotted them.

    Design: Corner/errors/transfer_execution_needs_an_appraisal_then_hits_the_pool_before_the_share
    """
    platform, ctx, a1, a2, bd1, bd2 = _two_vault_estate(api, "PR-2737-C35B")

    run1 = fx.computed_valuation_run(api, ctx)
    assert run1["gross_value_cents"] == 200000
    assert run1["included_asset_count"] == 2
    assert run1["allocation_remainder_cents"] == 0
    assert fx.read_designation(api, ctx, bd1["id"])["planned_allocation_cents"] == 180000
    assert fx.read_designation(api, ctx, bd2["id"])["planned_allocation_cents"] == 20000

    executed = fx.executed_election(
        api, ctx, platform["id"], a1["id"],
        election=ELECTION_TRANSFER,
        platform_confirmation_reference="CV-XFER-1",
        beneficiary_designation_id=bd1["id"],
    )
    assert executed["status"] == ELECTION_EXECUTED
    assert executed["distributed_value_cents"] == 100000
    assert fx.read_designation(api, ctx, bd1["id"])["received_value_cents"] == 100000
    assert fx.read_estate(api, ctx)["undistributed_value_cents"] == 100000
    assert fx.read_asset(api, ctx, a2["id"])["appraised_value_cents"] == 100000

    el2 = fx.submitted_election(
        api, ctx, a2["id"],
        election=ELECTION_TRANSFER, beneficiary_designation_id=bd2["id"],
    )
    validate_error(
        api.transition_disposition_election(
            el2["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-XFER-2"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        ERR_BENEFICIARY_ALLOCATION_EXCEEDED,
    )


def test_the_exhausted_pool_is_reported_before_the_beneficiary_ceiling(api):
    """
    Re-valuing on the alternate basis decays each cloud account by three hundred
    basis points to 97000, leaving a pool of 194000 and an undistributed balance
    of 94000 after the first transfer. Aiming the remaining 97000-cent account at
    the heir who has already drawn 100000 breaks both fiscal rules at once, and
    the pool check is the one reported, because it comes first in the fiscal band.

    PRD §3.8: The gross is then `quoted_value_cents` multiplied by the quantity 10000 minus the total decay basis points, divided by 10000, rounded half up to a whole cent.

    PRD §2.7: **Fiscal and aggregate**, in order: `ERR_REFUND_WINDOW_TOO_SHORT`, `ERR_CREDIT_EXCEEDS_CLAIM`, `ERR_SHARE_TOTAL_INVALID`, `ERR_VALUATION_REQUIRED`, `ERR_DISTRIBUTION_POOL_EXHAUSTED`, `ERR_BENEFICIARY_ALLOCATION_EXCEEDED`, `ERR_VALUATION_NOT_FINALIZED`, `ERR_ASSETS_PENDING_DISPOSITION`, `ERR_DUPLICATE_ASSET_HANDLE`, `ERR_INFO_CYCLE_LIMIT`, `ERR_OPEN_CANCELLATIONS`, `ERR_OPEN_REFUND_CLAIMS`.

    PRD §3.9: The account's `appraised_value_cents` must not exceed the estate's `undistributed_value_cents`, with an amount exactly equal to the remaining pool accepted and anything larger refused as `ERR_DISTRIBUTION_POOL_EXHAUSTED`.

    Design: Corner/errors/transfer_execution_needs_an_appraisal_then_hits_the_pool_before_the_share
    """
    platform, ctx, a1, a2, bd1, bd2 = _two_vault_estate(api, "PR-2737-C35C")

    run1 = fx.computed_valuation_run(api, ctx)
    fx.executed_election(
        api, ctx, platform["id"], a1["id"],
        election=ELECTION_TRANSFER,
        platform_confirmation_reference="CV-XFER-1",
        beneficiary_designation_id=bd1["id"],
    )

    fx.set_clock(api, "2026-08-14T00:00:00Z")
    run2 = fx.computed_valuation_run(api, ctx, basis=BASIS_ALTERNATE)
    assert run2["gross_value_cents"] == 194000
    assert run2["included_asset_count"] == 2
    assert fx.read_run(api, ctx, run1["id"])["status"] == RUN_SUPERSEDED
    assert fx.read_asset(api, ctx, a2["id"])["appraised_value_cents"] == 97000
    assert fx.read_estate(api, ctx)["undistributed_value_cents"] == 94000
    assert fx.read_designation(api, ctx, bd1["id"])["planned_allocation_cents"] == 174600
    assert fx.read_designation(api, ctx, bd2["id"])["planned_allocation_cents"] == 19400

    el3 = fx.submitted_election(
        api, ctx, a2["id"],
        election=ELECTION_TRANSFER, beneficiary_designation_id=bd1["id"],
    )
    validate_error(
        api.transition_disposition_election(
            el3["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-XFER-3"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        ERR_DISTRIBUTION_POOL_EXHAUSTED,
    )

    assert fx.read_asset(api, ctx, a2["id"])["disposition_status"] == DISPOSITION_ELECTED
    assert fx.read_election(api, ctx, el3["id"])["distributed_value_cents"] == 0
