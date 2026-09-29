"""Recovery-fund arithmetic: the estimate, the final award and disbursement.

A claim carries two quite different computations. The preliminary estimate is
stamped at filing and consults only the per-claim cap. The final award, run at
adjudication, starts from the gross, nets any mediation settlement and is then
clipped twice — once by the per-claim cap and once by the licence's remaining
aggregate room. Disbursement is separate again: it pro-rates the approved
cohort on one licence, moves the cash and suspends the licence until the money
comes back.
"""

from test_helpers import factories as F
from test_helpers import fixtures as H
from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    make_consumer_headers,
    validate_success,
)


def _c20_licence(api):
    """A C-20 licence whose accepted complaints go straight to investigation."""
    H.set_clock(api, "2026-08-01T00:00:00Z")
    classification = H.create_c20_classification(api)
    return H.mint_active_license(api, classification)


def test_preliminary_estimate_clamps_only_at_the_per_claim_cap(api):
    """A 2,000,000 claim against a 1,500,000 per-claim cap is estimated at the cap.

    "That estimate is deliberately crude and is never revised afterwards: it is
    the smaller of the `claimed_amount_cents` and the appropriation's
    `per_claim_cap_cents`, and nothing else."

    Design: Corner/calculations/corner_preliminary_estimate_clamps_only_at_the_per_claim_cap
    """
    fund = H.open_fund_account(
        api,
        initial_balance_cents=5000000,
        per_claim_cap_cents=1500000,
        per_license_aggregate_cap_cents=2000000,
    )
    ctx = _c20_licence(api)
    consumer = H.register_consumer(api, full_name="Ed Estimate", mailing_state="CA")

    H.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = H.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=2000000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Rooftop unit removed and never replaced",
    )
    H.screen_accepted(api, complaint["id"])

    claim = validate_success(
        api.create_claim(
            F.claim_payload(fund["id"], complaint["id"], 2000000),
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )

    assert claim["estimated_award_cents"] == 1500000


def test_filed_claim_lands_in_filed_copying_the_complaint_parties(api):
    """Filing copies the parties across, banks zeroes and awards nothing yet.

    "A filed claim lands in `FILED` with `consumer_id` and `license_id` copied
    from the complaint, `paid_amount_cents` and `repaid_amount_cents` at zero,
    and `estimated_award_cents` stamped from the **preliminary estimate**."

    Design: Corner/calculations/corner_preliminary_estimate_clamps_only_at_the_per_claim_cap
    """
    fund = H.open_fund_account(
        api,
        initial_balance_cents=5000000,
        per_claim_cap_cents=1500000,
        per_license_aggregate_cap_cents=2000000,
    )
    ctx = _c20_licence(api)
    consumer = H.register_consumer(api, full_name="Ed Estimate", mailing_state="CA")

    H.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = H.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=2000000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Rooftop unit removed and never replaced",
    )
    H.screen_accepted(api, complaint["id"])

    claim = validate_success(
        api.create_claim(
            F.claim_payload(fund["id"], complaint["id"], 2000000),
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )

    assert claim["status"] == "FILED"
    assert claim["license_id"] == ctx.license_id
    assert claim["consumer_id"] == consumer["id"]
    assert claim["paid_amount_cents"] == 0
    assert claim["repaid_amount_cents"] == 0
    assert claim["awarded_amount_cents"] is None


def test_filing_a_claim_leaves_the_appropriated_pool_untouched(api):
    """Only a disbursement can lower the pool, so filing leaves it at 5,000,000.

    "The live `balance_cents` is fully derived and is initialised to the
    appropriated amount: it is the `initial_balance_cents`, less the sum of
    `paid_amount_cents` over every claim charged to this account whose `status`
    is `PAID` or `REIMBURSED`, plus the sum of `repaid_amount_cents` over every
    claim charged to this account."

    Design: Corner/calculations/corner_preliminary_estimate_clamps_only_at_the_per_claim_cap
    """
    fund = H.open_fund_account(
        api,
        initial_balance_cents=5000000,
        per_claim_cap_cents=1500000,
        per_license_aggregate_cap_cents=2000000,
    )
    ctx = _c20_licence(api)
    consumer = H.register_consumer(api, full_name="Ed Estimate", mailing_state="CA")

    H.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = H.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=2000000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Rooftop unit removed and never replaced",
    )
    H.screen_accepted(api, complaint["id"])
    validate_success(
        api.create_claim(
            F.claim_payload(fund["id"], complaint["id"], 2000000),
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )

    account = H.read_fund_account(api, fund["id"])
    assert account["balance_cents"] == 5000000


def _two_ripe_judgment_claims(api):
    """Two court-judgment claims on one licence, ripe on the 90th day.

    The appropriation's per-licence aggregate cap is 1,500,000 — exactly what
    the first claim is worth once the judgment and the per-claim cap have
    clipped it — so no room is left for the second.
    """
    H.set_clock(api, "2026-08-01T00:00:00Z")
    fund = H.open_fund_account(
        api,
        initial_balance_cents=5000000,
        per_claim_cap_cents=1500000,
        per_license_aggregate_cap_cents=1500000,
    )
    ctx = _c20_licence(api)
    first_consumer = H.register_consumer(
        api,
        full_name="Xena Exhaust",
        contact_email="xena@home.test",
        mailing_state="CA",
    )
    second_consumer = H.register_consumer(
        api,
        full_name="Yuri Exhaust",
        contact_email="yuri@home.test",
        mailing_state="CA",
    )

    H.set_clock(api, "2026-09-01T00:00:00Z")
    first_complaint = H.file_complaint(
        api,
        first_consumer["id"],
        ctx.license_id,
        alleged_loss_cents=2000000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Two systems billed, none installed",
    )
    H.screen_accepted(api, first_complaint["id"])
    second_complaint = H.file_complaint(
        api,
        second_consumer["id"],
        ctx.license_id,
        alleged_loss_cents=1000000,
        contract_date="2026-08-06",
        work_completed_on="2026-08-21",
        description="Ductwork paid for and abandoned",
    )
    H.screen_accepted(api, second_complaint["id"])

    first_claim = H.file_judgment_claim(
        api,
        fund["id"],
        first_complaint["id"],
        first_consumer["id"],
        1800000,
        1600000,
        "CV-2026-0001",
        "2026-09-01",
    )
    second_claim = H.file_judgment_claim(
        api,
        fund["id"],
        second_complaint["id"],
        second_consumer["id"],
        900000,
        900000,
        "CV-2026-0002",
        "2026-09-01",
    )

    H.set_clock(api, "2026-11-30T00:00:00Z")
    return fund, ctx, first_claim, second_claim


def test_judgment_award_is_clipped_by_the_judgment_then_by_the_per_claim_cap(api):
    """1,800,000 claimed on a 1,600,000 judgment awards the 1,500,000 cap.

    "Begin with the gross: for a `COURT_JUDGMENT` claim it is the smaller of
    `claimed_amount_cents` and `judgment_amount_cents`; for a `FINAL_CITATION`
    claim it is simply `claimed_amount_cents`." "Then clip that net figure down
    to the appropriation's `per_claim_cap_cents`."

    Design: Corner/calculations/corner_approve_with_no_aggregate_room_denies_as_cap_exhausted
    """
    _fund, _ctx, first_claim, _second_claim = _two_ripe_judgment_claims(api)

    approved = H.approve_claim(api, first_claim["id"])

    assert approved["awarded_amount_cents"] == 1500000
    assert approved["status"] == "APPROVED"


def test_approval_encumbers_the_aggregate_room_without_moving_cash(api):
    """The award counts against the licence's cap while the pool stays full.

    "An `APPROVE` whose computation yields at least one cent moves the claim
    `FILED → APPROVED`, stamps `awarded_amount_cents` with the award and
    `adjudicated_on` with the clock date, and recomputes the licence's
    `recovery_encumbered_cents` — the sum of `awarded_amount_cents` over every
    claim on that licence whose `status` is `APPROVED`, `PAID` or `REIMBURSED` —
    so the award immediately counts against the aggregate cap even though no
    money has moved."

    Design: Corner/calculations/corner_approve_with_no_aggregate_room_denies_as_cap_exhausted
    """
    fund, ctx, first_claim, _second_claim = _two_ripe_judgment_claims(api)

    H.approve_claim(api, first_claim["id"])

    licence = H.read_license(api, ctx.license_id)
    assert licence["recovery_encumbered_cents"] == 1500000
    account = H.read_fund_account(api, fund["id"])
    assert account["balance_cents"] == 5000000


def test_approve_with_no_aggregate_room_denies_as_cap_exhausted(api):
    """A second approval computing zero is denied, not approved at 900,000.

    "An `APPROVE` whose computation yields exactly zero, meaning the aggregate
    cap has been exhausted, does **not** approve: the claim moves `FILED →
    DENIED` with `awarded_amount_cents` at zero, `adjudicated_on` stamped, and
    `denial_reason` set automatically to `AGGREGATE_CAP_EXHAUSTED`."

    Design: Corner/calculations/corner_approve_with_no_aggregate_room_denies_as_cap_exhausted
    """
    _fund, _ctx, first_claim, second_claim = _two_ripe_judgment_claims(api)
    H.approve_claim(api, first_claim["id"])

    denied = validate_success(
        api.adjudicate_claim(
            second_claim["id"], {"outcome": "APPROVE"}, FUND_ADJUDICATOR_HEADERS
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["awarded_amount_cents"] == 0
    assert denied["denial_reason"] == "AGGREGATE_CAP_EXHAUSTED"
    assert denied["adjudicated_on"] == "2026-11-30"


def _approved_claim_and_denied_sibling(api):
    """One APPROVED claim of 1,500,000 beside a DENIED sibling on the licence."""
    fund, ctx, first_claim, second_claim = _two_ripe_judgment_claims(api)
    H.approve_claim(api, first_claim["id"])
    denied = validate_success(
        api.adjudicate_claim(
            second_claim["id"], {"outcome": "APPROVE"}, FUND_ADJUDICATOR_HEADERS
        )
    )
    assert denied["status"] == "DENIED"
    return fund, ctx, first_claim, second_claim


def test_prorata_cohort_excludes_the_denied_sibling_and_pays_in_full(api):
    """Only APPROVED claims join the cohort, and a full pool pays them whole.

    "**First**, the pro-rata distribution runs over the **cohort**: every claim
    on the *same licence* as the target claim whose `status` is `APPROVED`,
    ordered by `created_at` ascending." "If the appropriation's `balance_cents`
    is at least that total, every cohort member's `paid_amount_cents` is set to
    its own `awarded_amount_cents` in full."

    Design: Corner/calculations/corner_prorata_cohort_excludes_the_denied_sibling_and_pays_in_full
    """
    fund, _ctx, first_claim, second_claim = _approved_claim_and_denied_sibling(api)

    paid = H.pay_claim(api, first_claim["id"], fund["id"])

    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 1500000
    sibling = validate_success(
        api.get_claim(second_claim["id"], FUND_ADJUDICATOR_HEADERS)
    )
    assert sibling["status"] == "DENIED"
    assert sibling["paid_amount_cents"] == 0


def test_disbursement_lowers_the_pool_and_raises_the_repayment_debt(api):
    """1,500,000 leaves the pool and lands on the licence as repayment debt.

    "Every cohort member then moves `APPROVED → PAID` with `paid_on` set to the
    clock date, **including sibling claims that were not the request's
    target**." "**Second**, *because* cash has moved, the appropriation's
    `balance_cents` falls by the total disbursed while the licence's
    `recovery_paid_to_date_cents` and `outstanding_recovery_repayment_cents`
    both rise by that same total, and the licensee's
    `outstanding_recovery_payout_cents` rises with them."

    Design: Corner/calculations/corner_prorata_cohort_excludes_the_denied_sibling_and_pays_in_full
    """
    fund, ctx, first_claim, _second_claim = _approved_claim_and_denied_sibling(api)

    paid = H.pay_claim(api, first_claim["id"], fund["id"])
    assert paid["paid_on"] == "2026-11-30"

    account = H.read_fund_account(api, fund["id"])
    assert account["balance_cents"] == 3500000

    licence = H.read_license(api, ctx.license_id)
    assert licence["outstanding_recovery_repayment_cents"] == 1500000
    assert licence["recovery_paid_to_date_cents"] == 1500000

    licensee = validate_success(
        api.get_licensee(ctx.licensee_id, LICENSING_ANALYST_HEADERS)
    )
    assert licensee["outstanding_recovery_payout_cents"] == 1500000


def test_disbursement_suspends_the_licence_and_cascades_its_designations(api):
    """The payout suspension is indefinite and parks the qualifier designation.

    "**Third**, *because* `outstanding_recovery_repayment_cents` is now greater
    than zero, the licence moves `ACTIVE → SUSPENDED` with `suspension_reason`
    of `RECOVERY_FUND_PAYOUT` and `suspension_until` left null — the suspension
    is indefinite and lasts until the money is repaid — and its
    `compliance_posture` becomes `NON_COMPLIANT`." "**Fourth**, *because* the
    licence has entered `SUSPENDED`, every designation on it in `ACTIVE` moves
    to `SUSPENDED_BY_LICENSE` and each affected qualifier's
    `active_qualification_count` falls by one."

    Design: Corner/calculations/corner_prorata_cohort_excludes_the_denied_sibling_and_pays_in_full
    """
    fund, ctx, first_claim, _second_claim = _approved_claim_and_denied_sibling(api)
    assignment_id = ctx.assignment["id"]

    H.pay_claim(api, first_claim["id"], fund["id"])

    licence = H.read_license(api, ctx.license_id)
    assert licence["status"] == "SUSPENDED"
    assert licence["suspension_reason"] == "RECOVERY_FUND_PAYOUT"
    assert licence["suspension_until"] is None
    assert licence["compliance_posture"] == "NON_COMPLIANT"

    assignment = validate_success(
        api.get_qualifier_assignment(assignment_id, LICENSING_ANALYST_HEADERS)
    )
    assert assignment["status"] == "SUSPENDED_BY_LICENSE"

    individual = validate_success(
        api.get_qualifying_individual(ctx.individual_id, LICENSING_ANALYST_HEADERS)
    )
    assert individual["active_qualification_count"] == 0
