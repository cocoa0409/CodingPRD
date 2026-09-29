"""From the screen that reserves a home to the ledger entry that funds its lease.

Each refusal in this file is caused by something other than the request: the home's compliance
posture, the applicant who screened first, the caller's role, or the running total of every
payment already recorded.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_APPROVED,
    ERR_DEPOSIT_OVERPAYMENT,
    ERR_HOME_NOT_VACANT,
    ERR_HOME_SHOWINGS_BLOCKED,
    ERR_LEASE_TERM_INVALID,
    ERR_RENT_CONCESSION_EXCEEDED,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    APP_CONDITIONAL_APPROVED,
    APP_SUBMITTED,
    ASSET_PIPELINE,
    CLOCK_AUG_01,
    LEASE_DRAFT,
    OBLIGATION_RESOLVED,
    OCC_RESERVED,
    OCC_VACANT,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
)


def test_the_frozen_home_blocks_every_screen_and_the_winner_blocks_the_next_one(api):
    """One obligation stops both applicants; resolving it lets the first reserve the home.

    PRD SS3.8: "Screening requires the home's `occupancy_status` to be exactly `VACANT`, otherwise
    `ERR_HOME_NOT_VACANT`, and the home's `leasing_posture` not to be `FROZEN`, a frozen home being
    refused with `ERR_HOME_SHOWINGS_BLOCKED`."  The posture is not a stored flag -- PRD SS2.8:
    "`leasing_posture` is not an independent dimension: it is a **derived projection** recomputed
    from scratch every time either stored dimension changes, a compliance obligation changes state,
    a showing is booked or cancelled, or the logical clock moves", clause 3 being "if the home has
    at least one compliance obligation whose `severity` is `CRITICAL` and whose `status` is one of
    `OPEN`, `PLANNED`, `RESOLUTION_SUBMITTED` or `RESOLUTION_REJECTED`, the posture is `FROZEN`."
    The decision and its deposit stack are the PRD's own worked example: "an applicant with a
    verified income of 560000, credit `B`, no evictions, a fraud score of 1093 and one pet has a
    `rent_to_income_bps` of 3839, misses clauses 1 through 4 on the credit tier alone, and lands in
    clause 5 as `CONDITIONAL_APPROVED` with a multiplier of 15000, a `security_deposit_cents` of
    322500, a `pet_deposit_cents` of 30000 and a `total_move_in_deposit_cents` of 352500."  And
    PRD SS3.8 on the cascade that locks the second applicant out: "Both approval outcomes then
    cascade the home's `occupancy_status` `VACANT` -> `RESERVED`."  A refused screen writes nothing
    -- PRD SS3.8 has the application "created in `SUBMITTED` with `rent_to_income_bps`, ... and
    `total_move_in_deposit_cents` ... all 0".

    Design: Corner/validations/screening_reads_the_home_posture_and_occupancy_before_deciding
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    obligation = x.planned_obligation(
        api,
        home["id"],
        severity="CRITICAL",
        planned_resolution_on="2026-08-25",
        description="Structural deck failure",
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="deck-permit-901"),
            x.COMPLIANCE,
        )
    )
    assert_home_dimensions(
        ok(api.get_home(home["id"], x.AGENT)), ASSET_PIPELINE, OCC_VACANT, POSTURE_FROZEN
    )

    first = x.verified_prospect(api, market["id"])
    second = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p4@example.com",
            "full_name": "Peter Four",
            "phone": "+1-404-555-0104",
            "declared_monthly_income_cents": 900000,
            "credit_tier": "A",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 9600,
            "verified_monthly_income_cents": 800000,
            "device_reputation_bps": 9200,
            "ip_geo_distance_km": 5,
        },
    )
    app_one = x.submitted_application(
        api, home["id"], first.prospect_id, requested_move_in_date="2026-10-01"
    )
    app_two = x.submitted_application(
        api,
        home["id"],
        second.prospect_id,
        requested_move_in_date="2026-10-01",
        pet_count=0,
        pet_breeds=[],
    )

    failed(
        api.screen_rental_application(app_one["id"], {}, x.AGENT),
        ERR_HOME_SHOWINGS_BLOCKED,
    )
    blocked = ok(api.get_rental_application(app_one["id"], x.AGENT))
    assert_fields(blocked, status=APP_SUBMITTED, rent_to_income_bps=0)

    resolved = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload("ACCEPT", review_note="Deck rebuilt and inspected"),
            x.DIRECTOR,
        )
    )
    assert_fields(resolved, status=OBLIGATION_RESOLVED)
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), leasing_posture=POSTURE_RESTRICTED)

    screened = ok(api.screen_rental_application(app_one["id"], {}, x.AGENT))
    assert_fields(
        screened,
        status=APP_CONDITIONAL_APPROVED,
        rent_to_income_bps=3839,
        risk_multiplier_bps=15000,
    )
    assert_money_group(
        screened,
        security_deposit_cents=322500,
        pet_deposit_cents=30000,
        total_move_in_deposit_cents=352500,
    )
    assert_home_dimensions(
        ok(api.get_home(home["id"], x.AGENT)), ASSET_PIPELINE, OCC_RESERVED
    )

    failed(api.screen_rental_application(app_two["id"], {}, x.AGENT), ERR_HOME_NOT_VACANT)
    shut_out = ok(api.get_rental_application(app_two["id"], x.AGENT))
    assert_fields(shut_out, status=APP_SUBMITTED)
    assert_money_group(shut_out, total_move_in_deposit_cents=0)


def test_the_regional_director_alone_may_write_the_six_month_term_at_the_floor(api):
    """204249 is one cent too deep and six months is one role too high -- until rd-1 asks.

    PRD SS3.8: "The referenced application's `status` must be `APPROVED` or
    `CONDITIONAL_APPROVED`, otherwise `ERR_APPLICATION_NOT_APPROVED`; ... the
    `monthly_rent_cents` must not fall below the market's concession floor, which is the home's
    `asking_rent_cents` less the quantity (`asking_rent_cents` multiplied by the market's
    `max_rent_concession_bps`, divided by 10,000, rounded half up), a deeper discount being refused
    with `ERR_RENT_CONCESSION_EXCEEDED`; and `term_months` must equal the market's
    `standard_lease_term_months` unless the acting role is `RegionalDirector`, who alone may write a
    non-standard term -- anyone else attempting one is refused with `ERR_LEASE_TERM_INVALID`."  The
    accepted row's shape is PRD SS3.8's: "The lease is created in `DRAFT` with its `home_id` copied
    from the application, its `required_deposit_cents` copied from the application's
    `total_move_in_deposit_cents`, `deposit_paid_cents` 0, and `signed_on` and `void_reason` the
    empty string."  Which refusal speaks is fixed by PRD SS2.7, where "**Rank 308 -- application
    not approved.** `ERR_APPLICATION_NOT_APPROVED` (409) on lease drafting" precedes "**Rank 608 --
    concession floor breached.**" and "**Rank 610 -- non-standard lease term.**", and "Evaluation
    stops at the first violated rule, and only that rule's error is reported."

    Design: Corner/validations/lease_creation_rejects_unapproved_applications_and_off_policy_terms
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    first = x.verified_prospect(api, market["id"])
    second = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p4@example.com",
            "full_name": "Peter Four",
            "phone": "+1-404-555-0104",
            "declared_monthly_income_cents": 900000,
            "credit_tier": "A",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 9600,
            "verified_monthly_income_cents": 800000,
            "device_reputation_bps": 9200,
            "ip_geo_distance_km": 5,
        },
    )
    unscreened = x.submitted_application(
        api,
        home["id"],
        second.prospect_id,
        requested_move_in_date="2026-10-01",
        pet_count=0,
        pet_breeds=[],
    )
    approved = x.screened_application(
        api, home["id"], first.prospect_id, requested_move_in_date="2026-10-01"
    )
    assert_money_group(approved.screened, total_move_in_deposit_cents=352500)

    failed(
        api.create_lease(
            f.lease_payload(
                unscreened["id"], start_date="2026-10-01", monthly_rent_cents=215000
            ),
            x.AGENT,
        ),
        ERR_APPLICATION_NOT_APPROVED,
    )
    failed(
        api.create_lease(
            f.lease_payload(
                approved.application_id,
                start_date="2026-10-01",
                term_months=6,
                monthly_rent_cents=215000,
            ),
            x.AGENT,
        ),
        ERR_LEASE_TERM_INVALID,
    )
    failed(
        api.create_lease(
            f.lease_payload(
                approved.application_id, start_date="2026-10-01", monthly_rent_cents=204249
            ),
            x.AGENT,
        ),
        ERR_RENT_CONCESSION_EXCEEDED,
    )

    lease = created(
        api.create_lease(
            f.lease_payload(
                approved.application_id,
                start_date="2026-10-01",
                term_months=6,
                monthly_rent_cents=204250,
            ),
            x.DIRECTOR,
        )
    )
    assert_fields(lease, status=LEASE_DRAFT, term_months=6, home_id=home["id"])
    assert_money_group(
        lease,
        monthly_rent_cents=204250,
        required_deposit_cents=352500,
        deposit_paid_cents=0,
    )
    assert_absent_or_empty(lease, "signed_on")
    assert_absent_or_empty(lease, "void_reason")
    assert_fields(
        ok(api.get_rental_application(unscreened["id"], x.AGENT)), status=APP_SUBMITTED
    )


def test_the_overpayment_rule_reads_the_running_total_not_the_single_payment(api):
    """152501 is legal in isolation and illegal as the second half; 152500 lands exactly.

    PRD SS3.8: "A `LeasingAgent` records each move-in deposit payment as an `amount_cents` figure
    that accumulates into `deposit_paid_cents` and increments the lease's `version` by 1. This is a
    funding ledger entry only: the lease stays in `DRAFT` no matter how much has been paid, and
    reaching the required amount never executes it. A payment that would take `deposit_paid_cents`
    plus `amount_cents` **strictly above** `required_deposit_cents` is refused with
    `ERR_DEPOSIT_OVERPAYMENT`, so the funding position can land exactly on the requirement but never
    overshoot it."  The requirement is inherited, PRD SS3.8: "its `required_deposit_cents` copied
    from the application's `total_move_in_deposit_cents`, `deposit_paid_cents` 0", that figure being
    the PRD's own 352500 for "an applicant with a verified income of 560000, credit `B`, no
    evictions, a fraud score of 1093 and one pet".  A refused payment leaves the ledger alone -- PRD
    SS2.9: "if a guard rejects the operation, nothing at all is written, including the cascade
    targets."

    Design: Corner/validations/deposit_payments_are_capped_by_the_running_paid_total
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    prospect = x.verified_prospect(api, market["id"])
    approved = x.screened_application(
        api, home["id"], prospect.prospect_id, requested_move_in_date="2026-10-01"
    )
    lease = x.draft_lease(api, approved.application_id, start_date="2026-10-01")
    assert_money_group(
        lease, required_deposit_cents=352500, deposit_paid_cents=0, monthly_rent_cents=208000
    )

    failed(
        api.pay_deposit(lease["id"], f.deposit_payment_payload(352501), x.AGENT),
        ERR_DEPOSIT_OVERPAYMENT,
    )
    assert_money_group(ok(api.get_lease(lease["id"], x.AGENT)), deposit_paid_cents=0)

    part = ok(api.pay_deposit(lease["id"], f.deposit_payment_payload(200000), x.AGENT))
    assert_fields(part, status=LEASE_DRAFT)
    assert_money_group(part, deposit_paid_cents=200000)

    failed(
        api.pay_deposit(lease["id"], f.deposit_payment_payload(152501), x.AGENT),
        ERR_DEPOSIT_OVERPAYMENT,
    )
    assert_money_group(ok(api.get_lease(lease["id"], x.AGENT)), deposit_paid_cents=200000)

    funded = ok(api.pay_deposit(lease["id"], f.deposit_payment_payload(152500), x.AGENT))
    assert_fields(funded, status=LEASE_DRAFT)
    assert_money_group(funded, deposit_paid_cents=352500)

    failed(
        api.pay_deposit(lease["id"], f.deposit_payment_payload(1), x.AGENT),
        ERR_DEPOSIT_OVERPAYMENT,
    )
    settled = ok(api.get_lease(lease["id"], x.AGENT))
    assert_fields(settled, status=LEASE_DRAFT)
    assert_money_group(settled, deposit_paid_cents=352500)
