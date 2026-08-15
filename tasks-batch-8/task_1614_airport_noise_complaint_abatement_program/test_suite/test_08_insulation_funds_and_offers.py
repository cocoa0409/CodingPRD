"""The insulation fund ledger: offer issuance and its guards, the pinned
grant-obligation split (provisional vs final), reservation release paths,
waterfall allocation, ledger conservation, and the offer-issue OCC guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_parcel,
    advance_study,
    assert_fund_ledger_invariants,
    assert_same_instant,
    create_application,
    create_fund,
    create_study,
    decide_application,
    fund_version,
    issue_offer,
    read_fund,
    screen_application,
    set_clock,
    setup_adopted_study_with_parcel,
    setup_decided_application,
    setup_issued_offer,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]
COORDINATOR = TEST_USERS["study_coordinator_headers"]


def test_fund_close_with_reserved_rejected(api):
    """PRD 3.8: "A `NoiseOfficeAdmin` may close an `ACTIVE` fund, moving it to
    `CLOSED`, only when `reserved_cents` is exactly zero (else
    `ERR_FUND_HAS_RESERVED`)".

    Design: Corner/state_machines/fund_close_with_reserved_rejected
    """
    ctx = setup_issued_offer(decision="ELIGIBLE_TIER2", est_cost_cents=500_000)
    fund = read_fund(ctx["fund"]["id"])
    assert fund["reserved_cents"] == 460_000

    response = api.close_fund(fund["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_FUND_HAS_RESERVED)

    reread = read_fund(fund["id"])
    assert reread["status"] == "ACTIVE"


def test_offer_auto_expiry_on_read_releases_reservation(api):
    """PRD 2.4: "Offer expirations are deliberately not swept by the clock. An
    expired offer is retracted lazily — only when the application holding it is
    next read, whether individually or through a list".
    PRD 3.8: "any read of an application whose `offer_expires_at` has passed moves
    it from `OFFER_ISSUED` back to `UNFUNDED`, stamps `last_offer_expired_at`, and
    releases the reservation back to available (bumping the fund's `version`)".
    PRD 3.8: "computes `offer_expires_at` as exactly 45 days after issuance".

    Design: Corner/state_machines/offer_auto_expiry_on_read_releases_reservation
    """
    ctx = setup_issued_offer(decision="ELIGIBLE_TIER2", est_cost_cents=500_000)
    # Issued at the startup clock 2026-08-01 -> expiry 2026-09-15.
    assert_same_instant(
        ctx["application"]["offer_expires_at"], "2026-09-15T00:00:00Z", "offer_expires_at"
    )

    set_clock("2026-09-16T00:00:00Z")

    swept = validate_success(api.get_application(ctx["application"]["id"], COORDINATOR))
    assert swept["funding_status"] == "UNFUNDED"
    assert swept["last_offer_expired_at"] is not None

    fund = read_fund(ctx["fund"]["id"])
    assert fund["available_cents"] == 5_000_000
    assert fund["reserved_cents"] == 0
    assert_fund_ledger_invariants(fund)


def test_offer_accept_after_expiry_returns_offer_expired(api):
    """PRD 3.8: "Accepting the offer moves `OFFER_ISSUED` to `GRANT_COMMITTED` and
    is only valid strictly before `offer_expires_at`; at or after expiry the request
    is rejected with `ERR_OFFER_EXPIRED`."

    Design: Corner/errors/offer_accept_after_expiry_returns_offer_expired
    """
    ctx = setup_issued_offer(
        decision="ELIGIBLE_TIER2",
        est_cost_cents=500_000,
        intake_closes_at="2026-12-31T00:00:00Z",
    )
    # Past the 45-day expiry; the application has not been read since.
    set_clock("2026-09-16T00:00:00Z")

    response = api.accept_offer(ctx["application"]["id"], {}, LIAISON)
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED)


def test_issue_offer_with_insufficient_fund_rejected(api):
    """PRD 3.8: "the fund's `available_cents` must cover at least half of the
    provisional obligation, boundary inclusive (else `ERR_INSUFFICIENT_FUNDS`)".

    Design: Corner/validations/issue_offer_with_insufficient_fund_rejected
    """
    ctx = setup_decided_application(
        decision="ELIGIBLE_TIER1",
        est_cost_cents=7_777_777,
        rooms_count=5,
        fund_total_cents=100,
        parcel_measured=72.0,
        parcel_modeled=73.0,
    )
    response = api.issue_offer(
        ctx["application"]["id"],
        {"expected_fund_version": ctx["fund"]["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FUNDS)


def test_issue_offer_without_active_fund_rejected(api):
    """PRD 3.8: "an `ACTIVE` fund must exist (else `ERR_NO_ACTIVE_FUND`)".

    Design: Corner/validations/issue_offer_without_active_fund_rejected
    """
    ctx = setup_decided_application(
        decision="ELIGIBLE_TIER1",
        est_cost_cents=300_000,
        rooms_count=5,
        parcel_measured=72.0,
        parcel_modeled=73.0,
    )
    # No reservations exist, so the fund may close.
    closed = validate_success(api.close_fund(ctx["fund"]["id"], {}, ADMIN), 200)
    assert closed["status"] == "CLOSED"

    # Present the closed fund's current version so only the active-fund guard
    # can fail.
    response = api.issue_offer(
        ctx["application"]["id"],
        {"expected_fund_version": closed["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_FUND)


def test_waterfall_full_partial_skip_in_one_run(api):
    """PRD 3.8: "Each candidate's provisional obligation is computed; when the
    fund's availability covers the whole obligation, a full offer is issued and
    reserved; when it covers at least half, boundary inclusive, a partial offer
    equal to the entire remaining availability is issued and reserved; otherwise
    the candidate is skipped and recorded in the run's `skipped_application_ids`."
    PRD 3.8: "The run's response reports `offers_issued`, `total_reserved_cents`,
    and `skipped_application_ids`".

    Design: Corner/calculations/waterfall_full_partial_skip_in_one_run
    """
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=10_000_000)
    ctx = setup_adopted_study_with_parcel(measured=75.2, modeled=76.0)
    study_id = ctx["study"]["id"]
    from test_helpers import add_parcel

    parcel_b = add_parcel(study_id, parcel_ref="P-B", dnl_db_measured=72.0,
                          dnl_db_modeled=73.0)
    parcel_c = add_parcel(study_id, parcel_ref="P-C", dnl_db_measured=66.0,
                          dnl_db_modeled=67.5)

    # Parcels added before adoption here — rebuild: the fixture adopted the study
    # already, so P-B/P-C recompute under FINAL automatically on create.
    a1 = create_application(ctx["parcel"]["id"], est_cost_cents=7_777_777)
    submit_application(a1["id"])
    screen_application(a1["id"])
    a1 = decide_application(a1["id"], "ELIGIBLE_TIER1")
    # Band 75 -> 80 points + RESIDENTIAL 10 = 90.
    assert a1["priority_score"] == 90

    a2 = create_application(parcel_b["id"], est_cost_cents=5_000_000)
    submit_application(a2["id"])
    screen_application(a2["id"])
    a2 = decide_application(a2["id"], "ELIGIBLE_TIER2")
    assert a2["priority_score"] == 70

    a3 = create_application(parcel_c["id"], est_cost_cents=2_000_000)
    submit_application(a3["id"])
    screen_application(a3["id"])
    a3 = decide_application(a3["id"], "ELIGIBLE_TIER2")
    assert a3["priority_score"] == 50

    run = validate_success(api.allocate_fund(fund["id"], {}, ADMIN), 200)
    assert run["offers_issued"] == 2
    assert run["total_reserved_cents"] == 10_000_000
    assert a2["id"] in run["skipped_application_ids"]

    app3 = validate_success(api.get_application(a3["id"], COORDINATOR))
    # Remaining 1,194,445 is >= half of the 1,840,000 obligation (920,000).
    assert app3["funding_status"] == "OFFER_ISSUED"
    assert app3["offered_amount_cents"] == 1_194_445

    fund_after = read_fund(fund["id"])
    assert fund_after["available_cents"] == 0
    assert fund_after["reserved_cents"] == 10_000_000
    assert_fund_ledger_invariants(fund_after)


def test_waterfall_tie_break_earlier_submitted_wins(api):
    """PRD 3.8: "Candidates are applications at `ELIGIBLE_TIER1` or
    `ELIGIBLE_TIER2` with funding `UNFUNDED`, visited in descending `priority_score`
    order, ties broken by earlier `submitted_at` and then by earlier `created_at` —
    never by identifier."

    Design: Corner/calculations/waterfall_tie_break_earlier_submitted_wins
    """
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=2_000_000)
    study = setup_adopted_study_with_parcel(measured=66.0, modeled=67.5)
    parcel_two = None
    from test_helpers import add_parcel

    parcel_two = add_parcel(study["study"]["id"], parcel_ref="P-T2",
                            dnl_db_measured=66.0, dnl_db_modeled=67.5)

    early = create_application(study["parcel"]["id"], est_cost_cents=2_000_000)
    submit_application(early["id"])

    set_clock("2026-08-02T00:00:00Z")

    late = create_application(parcel_two["id"], est_cost_cents=2_000_000)
    submit_application(late["id"])

    for app in (early, late):
        screen_application(app["id"])
        decide_application(app["id"], "ELIGIBLE_TIER2")

    run = validate_success(api.allocate_fund(fund["id"], {}, ADMIN), 200)
    assert run["offers_issued"] == 1
    assert late["id"] in run["skipped_application_ids"]

    winner = validate_success(api.get_application(early["id"], COORDINATOR))
    assert winner["funding_status"] == "OFFER_ISSUED"
    # Full TIER2 obligation on 2,000,000: 1,600,000 + 160,000 + 80,000.
    assert winner["offered_amount_cents"] == 1_840_000
