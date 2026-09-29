"""Compensating invariants: conserved totals returning to exactly their prior literal."""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── The federal obligation across withdrawal and re-presentation ──────────────

def _presented_offer_of_sixteen_million_obligated(api):
    state = fixtures.parcel_with_presented_offer(api)
    assert state["offer"]["net_offer_cents"] == 21_400_000
    assert state["project"]["federal_obligated_cents"] == 16_050_000
    return state


def _withdraw(api, state):
    return validate_success(
        api.withdraw_purchase_offer(
            state["offer"]["id"],
            factories.withdraw_offer_payload(
                state["offer"]["id"], withdrawal_reason="owner requested more time"
            ),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )


def test_withdrawing_a_presented_offer_releases_exactly_the_item_it_booked(api):
    """The deobligation drops the stored item rather than re-deriving the amount.

    "From `PRESENTED` the withdrawal is the exact compensating action for
    presentation: the offer moves to `WITHDRAWN` with `withdrawal_reason` stored,
    the parcel's `acquisition_status` returns from `OFFER_OUTSTANDING` to
    `VALUE_ESTABLISHED`, `federal_obligated_cents` is recomputed and returns
    bit-for-bit to its pre-presentation value, and the offer's, parcel's and
    project's `version` each advance by 1."

    "An offer that leaves `PRESENTED` or `ACCEPTED` for `DECLINED`, `EXPIRED`,
    `WITHDRAWN` or `SUPERSEDED` drops out of group one entirely, and because the
    item was rounded on the way in and is simply absent on the way out, the
    deobligation is the exact amount that was added, never a re-derived
    approximation."

    Design: Difficulty/compensating_invariant/federal_obligation_returns_to_the_same_literal_after_offer_withdrawal_and_re_presentation
    """
    state = _presented_offer_of_sixteen_million_obligated(api)

    withdrawn = _withdraw(api, state)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["net_offer_cents"] == 21_400_000

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "VALUE_ESTABLISHED"

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 0


def test_presenting_a_fresh_offer_restores_the_identical_obligation_literal(api):
    """A second offer from the same accepted review appraisal books the same figure.

    "Presentation moves `status` to `PRESENTED`, stamps `presented_at` from the
    logical clock, computes `expires_at` as `presented_at` plus 30 calendar days,
    moves the parcel's `acquisition_status` from `VALUE_ESTABLISHED` to
    `OFFER_OUTSTANDING`, recomputes the project's `federal_obligated_cents`."

    "Offers at `ACCEPTED`, `WITHDRAWN` or an existing `SUPERSEDED` are untouched."

    "Each is recomputed from scratch over its declared input set at every trigger
    listed in §3, so a compensating action always returns the total to exactly the
    value it held before the action it compensates."

    Design: Difficulty/compensating_invariant/federal_obligation_returns_to_the_same_literal_after_offer_withdrawal_and_re_presentation
    """
    state = _presented_offer_of_sixteen_million_obligated(api)
    first_offer_id = state["offer"]["id"]
    _withdraw(api, state)

    replacement = fixtures.build_offer(
        api, state["project"], state["parcel"]["id"], state["review_appraisal"]
    )
    assert replacement["net_offer_cents"] == 21_400_000
    assert replacement["dob_deduction_cents"] == 0

    presented = validate_success(
        api.present_purchase_offer(
            replacement["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    assert presented["status"] == "PRESENTED"

    original = validate_success(
        api.get_purchase_offer(
            first_offer_id, TEST_USERS["program_administrator_headers"]
        )
    )
    assert original["status"] == "WITHDRAWN"
    assert original["superseded_by_offer_id"] is None

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 16_050_000

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "OFFER_OUTSTANDING"


# ─── The program income balance across a ledger reversal ──────────────────────

def _project_with_two_credits(api):
    """A lease credit of 300,002 and a salvage credit of 100,002, both half-cent shares."""
    state = fixtures.create_approved_project(api)
    state["entry_a"] = fixtures.post_program_income(
        api,
        state["project"]["id"],
        entry_type="LEASE_REVENUE",
        amount_cents=300_002,
        posted_on="2026-07-15",
    )
    state["entry_b"] = fixtures.post_program_income(
        api,
        state["project"]["id"],
        entry_type="SALVAGE_PROCEEDS",
        amount_cents=100_002,
        posted_on="2026-08-01",
    )
    return state


def test_two_half_cent_entries_are_rounded_individually_before_the_balance_sums(api):
    """The balance is 300004, which the round-once-at-the-total answer cannot produce.

    "Round-each-entry-then-sum matters: with a `cost_share_federal_pct` of 0.75, a
    `LEASE_REVENUE` of 100002 cents yields a federal share of 75002 (75001.5
    rounded half up) and a `SALVAGE_PROCEEDS` of 300002 cents yields 225002,
    giving a balance of 300004. Summing the gross amounts first would give 300003,
    which is wrong."

    "**The signed federal share.** `federal_share_cents` is computed per entry, and
    the rounding happens on each entry before the balance accumulates it."

    Design: Difficulty/compensating_invariant/program_income_balance_returns_to_the_same_literal_after_ledger_entry_reversal
    """
    state = _project_with_two_credits(api)

    assert state["entry_a"]["federal_share_cents"] == 225_002
    assert state["entry_b"]["federal_share_cents"] == 75_002

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["program_income_balance_cents"] == 300_004
    assert project["program_income_balance_cents"] != 300_003


def test_reversal_leaves_a_mirror_already_reversed_and_restores_the_prior_balance(api):
    """Both the target and its twin exit the ACTIVE set, leaving no rounding residue.

    "The operation flips the target's `status` from `ACTIVE` to `REVERSED` and
    creates a mirror entry carrying `reverses_entry_id` set to the target's `id`,
    the **opposite** sign, the **same** magnitude, and `status` `REVERSED`."

    "The mirror is created already `REVERSED` rather than `ACTIVE`, which is the
    whole point: both the target and its mirror leave the `ACTIVE` input set, so
    the balance returns to exactly its pre-target value with no rounding residue
    left behind."

    "The response body is the **reversing** entry, not the target."

    Design: Difficulty/compensating_invariant/program_income_balance_returns_to_the_same_literal_after_ledger_entry_reversal
    """
    state = _project_with_two_credits(api)

    mirror = validate_success(
        api.reverse_program_income_entry(
            state["entry_a"]["id"],
            factories.reverse_program_income_entry_payload(
                state["entry_a"]["id"],
                reversal_note="lease receipt attributed to the wrong project",
            ),
            TEST_USERS["program_administrator_headers"],
        ),
        201,
    )

    assert mirror["reverses_entry_id"] == state["entry_a"]["id"]
    assert mirror["federal_share_cents"] == -225_002
    assert mirror["amount_cents"] == 300_002
    assert mirror["status"] == "REVERSED"

    target = validate_success(
        api.get_program_income_entry(
            state["entry_a"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert target["status"] == "REVERSED"

    survivor = validate_success(
        api.get_program_income_entry(
            state["entry_b"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert survivor["status"] == "ACTIVE"

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["program_income_balance_cents"] == 75_002

    rows, _meta = validate_paginated(
        api.list_program_income_entries(
            TEST_USERS["program_administrator_headers"],
            params={"project_id": state["project"]["id"]},
        )
    )
    assert len(rows) == 3


# ─── The parcel deduction total against the offer's snapshot ───────────────────

DOB_RECORDS = (
    {
        "benefit_source": "NFIP_CLAIM",
        "amount_cents": 1_200_000,
        "repair_documented_cents": 300_000,
        "received_on": "2026-05-01",
    },
    {"benefit_source": "SBA_LOAN", "amount_cents": 500_001, "received_on": "2026-05-10"},
    {"benefit_source": "SBA_LOAN", "amount_cents": 700_001, "received_on": "2026-05-20"},
)


def _parcel_with_three_deductions_and_one_offer(api):
    state = fixtures.parcel_value_established(api)
    state["dob_records"] = [
        fixtures.record_dob(api, state["project"], state["parcel"]["id"], **record)
        for record in DOB_RECORDS
    ]
    state["offer"] = fixtures.build_offer(
        api, state["project"], state["parcel"]["id"], state["review_appraisal"]
    )
    assert state["offer"]["dob_deduction_cents"] == 1_500_002
    assert state["offer"]["net_offer_cents"] == 19_794_998
    return state


def _reverse_the_first_sba_record(api, state):
    record = state["dob_records"][1]
    return validate_success(
        api.reverse_dob_record(
            record["id"],
            factories.reverse_dob_record_payload(
                record["id"],
                reversal_reason="SBA loan was disbursed for contents, not structure repair",
            ),
            TEST_USERS["program_administrator_headers"],
        )
    )


def test_reversing_a_deduction_restores_the_parcel_total_but_not_the_offer(api):
    """One action moves the parcel's running total and deliberately leaves the snapshot.

    "Its `status` becomes `REVERSED`, the `reversal_reason` is stored, and its
    `deductible_cents` is **frozen at its last `ACTIVE` value for audit** rather
    than zeroed, so the record still shows what it had been deducting."

    "Offers already created keep their snapshotted `dob_deduction_cents` - a
    reversal never rewrites an offer that has already been built."

    Design: Difficulty/compensating_invariant/dob_reversal_restores_parcel_deduction_total_without_rewriting_the_created_offer
    """
    state = _parcel_with_three_deductions_and_one_offer(api)
    parcel_before = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel_before["dob_deduction_total_cents"] == 1_500_002

    reversed_record = _reverse_the_first_sba_record(api, state)
    assert reversed_record["status"] == "REVERSED"
    assert reversed_record["deductible_cents"] == 250_001

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["dob_deduction_total_cents"] == 1_250_001

    offer = validate_success(
        api.get_purchase_offer(
            state["offer"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert offer["dob_deduction_cents"] == 1_500_002
    assert offer["net_offer_cents"] == 19_794_998


def test_a_new_offer_after_the_reversal_reads_the_restored_total_and_supersedes(api):
    """Only a freshly built offer picks up the restored deduction total.

    "The input set is every `DuplicationOfBenefitsRecord` on the parcel whose
    `status` is `ACTIVE`; `REVERSED` records are excluded entirely."

    "Every existing `PurchaseOffer` on the same parcel whose `status` is `DRAFT`,
    `DECLINED` or `EXPIRED` moves to `SUPERSEDED` with its
    `superseded_by_offer_id` set to the newly created offer's `id`, and each of
    those offers' `version` advances by 1."

    "For an `OWNER_OCCUPIED` parcel, the rate is read from the single half-open
    band containing `pre_incentive_net_cents`: 0.10 when `pre_incentive_net_cents`
    is below 10,000,000 cents; 0.07 when it is at least 10,000,000 and below
    25,000,000; and 0.05 when it is 25,000,000 or more."

    Design: Difficulty/compensating_invariant/dob_reversal_restores_parcel_deduction_total_without_rewriting_the_created_offer
    """
    state = _parcel_with_three_deductions_and_one_offer(api)
    _reverse_the_first_sba_record(api, state)

    replacement = fixtures.build_offer(
        api, state["project"], state["parcel"]["id"], state["review_appraisal"]
    )

    assert replacement["dob_deduction_cents"] == 1_250_001
    assert replacement["pre_incentive_net_cents"] == 18_749_999
    assert replacement["incentive_cents"] == 1_312_500
    assert replacement["net_offer_cents"] == 20_062_499

    superseded = validate_success(
        api.get_purchase_offer(
            state["offer"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_offer_id"] == replacement["id"]
