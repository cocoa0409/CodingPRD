"""Claim construction, the pinned withhold arithmetic and the capped appeal loop."""

from test_helpers import (
    ApiErrorId,
    assert_billing_claim,
    assert_day_ledger,
    assert_money,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_billing_claim_payload
from test_helpers.test_users import BILLING_ANALYST


def _ffs_episode_with_one_compliant_day_and_a_meal_plan(mrn: str, full_name: str) -> dict:
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE",
        home_distance_km=6.0,
        primary_diagnosis_code="UTI_COMPLICATED",
        qualifying_condition_code="UTI_COMPLICATED",
        mrn=mrn,
        full_name=full_name,
    )
    episode_id = parts["episode"]["id"]
    parts["meal_plan"] = fx.open_meal_plan(
        episode_id, diet_code="NONE", daily_delivery_count=2
    )
    parts["visit"] = fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=6.0
    )
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    parts["episode"] = fx.read_episode(episode_id)
    return parts


def test_claim_withhold_rate_is_keyed_on_the_gross_amount(api):
    """PRD §3.9: "Its money is then computed in four pinned steps and in no other
    order: `gross_amount_usd` is the episode's `reimbursement_amount_usd` plus
    its `meal_credit_total_usd`, rounded half up to two decimals; `withhold_rate`
    is then selected by comparing **that gross figure** — never the net — against
    the 9600.00 threshold, taking 0.02 when the gross is at or below 9600.00 and
    0.05 when it is strictly above; `withhold_amount_usd` is the gross multiplied
    by that rate, rounded half up to two decimals; and `net_payable_usd` is the
    gross less the withhold, rounded half up to two decimals."
    PRD §3.7: "on a `FEE_FOR_SERVICE` episode meals are separately billable at
    28.00 US dollars per credited day, so `meal_credit_total_usd` is
    `credited_day_count` multiplied by 28.00, rounded half up to two decimals,
    and that money later rolls into the claim."

    Design: Difficulty/combinatorial_formula/claim_withhold_tier_keyed_on_gross_never_on_net_mode_c
    """
    parts = _ffs_episode_with_one_compliant_day_and_a_meal_plan("MRN-N1", "Nina Net")
    episode = parts["episode"]

    plan = fx.read_meal_plan(episode["id"], parts["meal_plan"]["id"])
    assert plan["credited_day_count"] == 1
    assert_money(plan["meal_credit_total_usd"], 28.00, "meal_credit_total_usd")
    assert episode["billable_day_count"] == 1
    assert_money(
        episode["reimbursement_amount_usd"], 9600.00, "reimbursement_amount_usd"
    )

    claim = validate_success(
        api.create_billing_claim(
            create_billing_claim_payload(episode["id"], episode["version"]),
            BILLING_ANALYST,
        ),
        201,
    )
    assert_billing_claim(claim)
    assert_money(claim["gross_amount_usd"], 9628.00, "gross_amount_usd")
    assert claim["withhold_rate"] == 0.05, (
        "a gross strictly above 9600.00 selects the 0.05 rate, got "
        f"{claim['withhold_rate']}"
    )
    assert claim["billed_day_count"] == 1
    assert claim["status"] == "BUILT"


def test_claim_net_payable_follows_the_pinned_four_step_order(api):
    """PRD §2.7: "**The claim arithmetic keys its withhold rate on the gross
    amount, never on the net.** The four steps run in this pinned order and no
    other: first the gross amount, then the withhold rate selected by comparing
    that gross amount against the tier threshold, then the withhold amount, then
    the net payable. Each step is rounded to two decimals half up as it is
    produced."
    PRD §3.9: "`withhold_amount_usd` is the gross multiplied by that rate,
    rounded half up to two decimals; and `net_payable_usd` is the gross less the
    withhold, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/claim_withhold_tier_keyed_on_gross_never_on_net_mode_c
    """
    parts = _ffs_episode_with_one_compliant_day_and_a_meal_plan("MRN-N2", "Nina Net Two")
    episode = parts["episode"]

    claim = fx.build_claim(episode["id"], episode["version"])

    assert_money(claim["withhold_amount_usd"], 481.40, "withhold_amount_usd")
    assert_money(claim["net_payable_usd"], 9146.60, "net_payable_usd")
    assert claim["net_payable_usd"] != 9435.44, (
        "keying the withhold tier off the net is the wrong evaluation order"
    )
    assert_money(claim["paid_amount_usd"], 0.00, "paid_amount_usd")
    assert claim["appeal_count"] == 0
    assert claim["denial_reason"] is None


def test_claim_build_on_an_episode_with_no_compliant_day_is_refused(api):
    """PRD §3.9: "Building a claim is a `BillingAnalyst` operation naming the
    `episode_id` and carrying `expected_episode_version`; a stale value is
    `ERR_STALE_VERSION` at HTTP 412, and an episode whose `billable_day_count` is
    0 is refused with `ERR_NO_BILLABLE_DAYS` at HTTP 422 — at least one compliant
    day is required before a claim exists at all."

    Design: Difficulty/boundary_precision_check/zero_billable_days_blocks_claim_build_on_empty_compliant_set
    """
    parts = fx.setup_active_episode(
        program_track="CMS_WAIVER",
        home_distance_km=2.0,
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        mrn="MRN-Z1",
        full_name="Zed Zero",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=2.0
    )
    day = fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])
    assert day["status"] == "CARVED_OUT", (
        "one in-person visit is one short of the waiver requirement of two"
    )

    episode = fx.read_episode(episode_id)
    validate_error(
        api.create_billing_claim(
            create_billing_claim_payload(episode_id, episode["version"]),
            BILLING_ANALYST,
        ),
        ApiErrorId.ERR_NO_BILLABLE_DAYS.value,
    )


def test_carved_out_only_episode_reports_zero_reimbursement_and_no_claims(api):
    """PRD §3.9: "An episode's `reimbursement_amount_usd` is driven entirely by
    `billable_day_count` — carved-out and pending days contribute nothing — and
    the arithmetic forks on `program_track`."
    PRD §2.8: "Therefore an episode's `service_day_count` always equals the sum
    of its `billable_day_count`, its `carved_out_day_count` and its
    `pending_day_count`."

    Design: Difficulty/boundary_precision_check/zero_billable_days_blocks_claim_build_on_empty_compliant_set
    """
    parts = fx.setup_active_episode(
        program_track="CMS_WAIVER",
        home_distance_km=2.0,
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        mrn="MRN-Z2",
        full_name="Zed Zero Two",
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z", distance_km=2.0
    )
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=1, billable=0, carved_out=1, pending=0)
    assert_money(
        episode["reimbursement_amount_usd"], 0.00, "reimbursement_amount_usd"
    )

    validate_error(
        api.create_billing_claim(
            create_billing_claim_payload(episode_id, episode["version"]),
            BILLING_ANALYST,
        ),
        ApiErrorId.ERR_NO_BILLABLE_DAYS.value,
    )

    rows, meta = validate_paginated(
        api.list_episode_billing_claims(episode_id, BILLING_ANALYST)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_third_appeal_is_refused_by_the_appeal_cap(api):
    """PRD §3.9: "A claim in `DENIED` whose `appeal_count` is strictly below 2
    moves `DENIED → APPEALED` with `appeal_count` incremented by 1 and `version`
    advanced by 1; the payer's response then arrives as another recorded outcome,
    so the cycle `SUBMITTED → DENIED → APPEALED → DENIED` can run at most twice
    before the door shuts."
    PRD §3.9: "An appeal attempted on a claim whose `appeal_count` has already
    reached 2 is refused with `ERR_APPEAL_LIMIT_EXCEEDED` at HTTP 409, leaving
    the claim in `DENIED`, from which the only remaining move is to close it."

    Design: Corner/errors/claim_appeal_cap_of_two_returns_appeal_limit_exceeded_on_the_third_attempt
    """
    parts = fx.setup_built_claim_on_discharged_ffs_episode()
    episode_id = parts["episode"]["id"]
    claim = parts["claim"]

    assert_money(claim["gross_amount_usd"], 9600.00, "gross_amount_usd")
    assert claim["withhold_rate"] == 0.02, (
        "9600.00 sits exactly on the inclusive low-withhold boundary"
    )
    assert_money(claim["withhold_amount_usd"], 192.00, "withhold_amount_usd")
    assert_money(claim["net_payable_usd"], 9408.00, "net_payable_usd")

    fx.submit_claim(claim["id"])
    fx.record_outcome(claim["id"], "DENIED", "documentation")
    fx.appeal_claim(claim["id"])
    fx.record_outcome(claim["id"], "DENIED", "documentation again")
    fx.appeal_claim(claim["id"])
    denied = fx.record_outcome(claim["id"], "DENIED", "final")
    assert denied["status"] == "DENIED"
    assert denied["appeal_count"] == 2

    validate_error(
        api.appeal_billing_claim(claim["id"], BILLING_ANALYST),
        ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED.value,
    )

    unchanged = fx.read_claim(episode_id, claim["id"])
    assert unchanged["appeal_count"] == 2
    assert_money(unchanged["paid_amount_usd"], 0.00, "paid_amount_usd")


def test_claim_paid_after_an_appeal_recovers_sixty_percent(api):
    """PRD §3.9: "From `SUBMITTED` or `APPEALED`, an outcome of `PAID` sets
    `status` to `PAID` and sets `paid_amount_usd` according to where the claim
    came from: a claim paid straight out of `SUBMITTED` receives its full
    `net_payable_usd`, while a claim paid after an appeal receives
    `net_payable_usd` multiplied by 0.60 and rounded half up to two decimals,
    because appeal recovery is partial."

    Design: Corner/errors/appealed_claim_paid_recovers_sixty_percent_of_net_payable
    """
    parts = fx.setup_built_claim_on_discharged_ffs_episode()
    claim = parts["claim"]

    fx.submit_claim(claim["id"])
    fx.record_outcome(claim["id"], "DENIED", "coding")
    appealed = fx.appeal_claim(claim["id"])
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1

    paid = validate_success(
        api.record_claim_outcome(claim["id"], {"outcome": "PAID"}, BILLING_ANALYST)
    )
    assert paid["status"] == "PAID"
    assert_money(paid["net_payable_usd"], 9408.00, "net_payable_usd")
    assert_money(paid["paid_amount_usd"], 5644.80, "paid_amount_usd")
    assert paid["paid_amount_usd"] != 9408.00, (
        "an appeal recovery pays 0.60 of the net, not the full amount"
    )
    assert paid["appeal_count"] == 1


def test_claim_build_with_a_stale_episode_version_is_rejected(api):
    """PRD §2.6: "A `POST /billing-claims` request must carry
    `expected_episode_version` holding the `version` of the target `Episode` the
    client last read. A newly built claim legitimately supersedes any prior claim
    still in `BUILT`, so the build has to be anchored to the exact day-ledger the
    client saw; if the episode's `version` has advanced — a compliance day
    flipped, a visit was attested, the episode was discharged — the build is
    rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/claim_build_with_stale_episode_version_returns_stale_version
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE", mrn="MRN-OE", full_name="Ove OccEpisode"
    )
    episode_id = parts["episode"]["id"]

    fx.perform_and_attest_visit(
        episode_id, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z"
    )
    fx.finalize_day(fx.compliance_day_for(episode_id, "2026-06-01")["id"])

    stale_version = fx.read_episode(episode_id)["version"]
    fresh = fx.sign_med_rec(episode_id)

    validate_error(
        api.create_billing_claim(
            create_billing_claim_payload(episode_id, stale_version), BILLING_ANALYST
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    claim = validate_success(
        api.create_billing_claim(
            create_billing_claim_payload(episode_id, fresh["version"]),
            BILLING_ANALYST,
        ),
        201,
    )
    assert claim["status"] == "BUILT"
    assert claim["billed_day_count"] == 1
    assert_money(claim["gross_amount_usd"], 9600.00, "gross_amount_usd")

    rows, meta = validate_paginated(
        api.list_episode_billing_claims(episode_id, BILLING_ANALYST)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == claim["id"]
