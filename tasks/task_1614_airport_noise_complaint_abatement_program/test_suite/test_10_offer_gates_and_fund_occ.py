"""Offer-issuance gates: the study-adoption cross-entity guard, the
validation-ordering pair of referential-before-fiscal guards, and the
optimistic-concurrency stale fund version rejection on issue-offer."""
from test_helpers import (
    ApiErrorId,
    add_parcel,
    advance_study,
    create_application,
    create_fund,
    create_study,
    decide_application,
    fund_version,
    read_fund,
    screen_application,
    setup_adopted_study_with_parcel,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
COORDINATOR = TEST_USERS["study_coordinator_headers"]


def _setup_public_review_application(api, fund_total_cents=20_000_000):
    """ACTIVE fund + study held in PUBLIC_REVIEW (never adopted) with a parcel
    whose preliminary exposure is 71.5 (band 70) + an application decided
    ELIGIBLE_TIER1 on est_cost_cents 7,777,777."""
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=fund_total_cents)
    study = create_study(title="Part150 Iota")
    advance_study(study["id"], "DATA_COLLECTION")
    parcel = add_parcel(
        study["id"],
        parcel_ref="P-700",
        dnl_db_measured=72.0,
        dnl_db_modeled=73.0,
        zone_code="Z7",
    )
    advance_study(study["id"], "PUBLIC_REVIEW")
    application = create_application(
        parcel["id"], rooms_count=5, est_cost_cents=7_777_777
    )
    submit_application(application["id"])
    screen_application(application["id"])
    # Preliminary variant: 73.0 - 1.5 = 71.5 >= 70.0, so tier one is permitted.
    application = decide_application(application["id"], "ELIGIBLE_TIER1")
    return {
        "fund": read_fund(fund["id"]),
        "study": study,
        "parcel": parcel,
        "application": application,
    }


def test_issue_offer_rejected_while_study_not_adopted(api):
    """PRD 3.8: "the parcel's study must be `ADOPTED` (else
    `ERR_STUDY_NOT_ADOPTED`)".

    Design: Difficulty/cross_entity_state_dependency/issue_offer_gated_by_study_adoption
    """
    ctx = _setup_public_review_application(api)

    response = api.issue_offer(
        ctx["application"]["id"],
        {"expected_fund_version": ctx["fund"]["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STUDY_NOT_ADOPTED)

    reread = validate_success(api.get_application(ctx["application"]["id"], COORDINATOR))
    assert reread["funding_status"] == "UNFUNDED"
    fund = read_fund(ctx["fund"]["id"])
    assert fund["reserved_cents"] == 0


def test_issue_offer_succeeds_once_study_adopted(api):
    """PRD 3.7: "Adoption is reserved for a `NoiseOfficeAdmin`: it stamps
    `adopted_at`".
    PRD 3.8: "The fund moves that amount from available to reserved —
    incrementing the fund's `version` — the application records the reserving
    fund on `fund_id`, stamps `offer_issued_at`, computes `offer_expires_at` as
    exactly 45 days after issuance, and moves to `OFFER_ISSUED`".

    Design: Difficulty/cross_entity_state_dependency/issue_offer_gated_by_study_adoption
    """
    ctx = _setup_public_review_application(api)
    # The gate is demonstrably armed before adoption.
    validate_error(
        api.issue_offer(
            ctx["application"]["id"],
            {"expected_fund_version": ctx["fund"]["version"]},
            ADMIN,
        ),
        ApiErrorId.ERR_STUDY_NOT_ADOPTED,
    )

    adopted = validate_success(api.adopt_study(ctx["study"]["id"], {}, ADMIN), 200)
    assert adopted["status"] == "ADOPTED"

    offered = validate_success(
        api.issue_offer(
            ctx["application"]["id"],
            {"expected_fund_version": fund_version(ctx["fund"]["id"])},
            ADMIN,
        ),
        200,
    )
    assert offered["funding_status"] == "OFFER_ISSUED"
    # TIER1 provisional on 7,777,777: 7,777,777 + 777,778 + 250,000.
    assert offered["offered_amount_cents"] == 8_805_555


def test_referential_guard_beats_fiscal_guard_on_issue_offer(api):
    """PRD 2.11: "Every request is checked against a fixed sequence of gates,
    and the first gate that fails determines the error returned; later gates are
    not evaluated for that request."
    PRD 2.11: "12. **Cross-entity state guards** — parcel eligibility, study
    adoption, linked-complaint finality, unclassified-event gates, and
    correlation target state." and "13. **Fiscal guards** — the existence of an
    active fund and the sufficiency of its available balance, evaluated after
    everything else."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_issue_offer
    """
    # Fund holds only 100 cents: the fiscal guard (available >= half of the
    # 8,805,555 obligation) would fail too, but the study guard fires first.
    ctx = _setup_public_review_application(api, fund_total_cents=100)

    response = api.issue_offer(
        ctx["application"]["id"],
        {"expected_fund_version": ctx["fund"]["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STUDY_NOT_ADOPTED)


def test_study_adoption_guard_fires_even_with_ample_funds(api):
    """PRD 3.8: "Issuing an offer directly is a `NoiseOfficeAdmin` action
    guarded in layers: ... the parcel's study must be `ADOPTED` (else
    `ERR_STUDY_NOT_ADOPTED`); an `ACTIVE` fund must exist (else
    `ERR_NO_ACTIVE_FUND`); ... and the fund's `available_cents` must cover at
    least half of the provisional obligation, boundary inclusive (else
    `ERR_INSUFFICIENT_FUNDS`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_issue_offer
    """
    # Ample funding: only the study-adoption guard can fail.
    ctx = _setup_public_review_application(api, fund_total_cents=20_000_000)

    response = api.issue_offer(
        ctx["application"]["id"],
        {"expected_fund_version": ctx["fund"]["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STUDY_NOT_ADOPTED)


def test_occ_stale_fund_version_on_issue_offer_rejected(api):
    """PRD 2.6: "Third, issuing an insulation offer directly — the issue-offer
    endpoint (`POST
    /noise-program/sound-insulation-applications/{applicationId}/issue-offer`) —
    requires `expected_fund_version` matching the target fund's current
    `version`. The reservation arithmetic must be based on the fund's current
    `available_cents`, not a snapshot the client read earlier; a mismatch is
    rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_fund_version_on_issue_offer_rejected
    """
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=20_000_000)
    ctx = setup_adopted_study_with_parcel(measured=72.0, modeled=73.0)
    parcel_two = add_parcel(
        ctx["study"]["id"],
        parcel_ref="P-O2",
        dnl_db_measured=72.0,
        dnl_db_modeled=73.0,
    )

    applications = []
    for parcel in (ctx["parcel"], parcel_two):
        application = create_application(
            parcel["id"], rooms_count=5, est_cost_cents=300_000
        )
        submit_application(application["id"])
        screen_application(application["id"])
        applications.append(decide_application(application["id"], "ELIGIBLE_TIER1"))

    stale_version = fund_version(fund["id"])

    first = validate_success(
        api.issue_offer(
            applications[0]["id"], {"expected_fund_version": stale_version}, ADMIN
        ),
        200,
    )
    assert first["funding_status"] == "OFFER_ISSUED"
    # The first reservation advanced the fund's version.
    assert read_fund(fund["id"])["version"] != stale_version

    replayed = api.issue_offer(
        applications[1]["id"], {"expected_fund_version": stale_version}, ADMIN
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_FUND_VERSION)
