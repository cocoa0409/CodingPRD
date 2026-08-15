"""Pinned fee calculation, family-discount counting rule, and the scholarship
review cycle with its budget commitment."""
from test_helpers import (
    FO,
    PC,
    REV1,
    REV2,
    ApiErrorId,
    create_household,
    create_published_season,
    drop_registration,
    find_refund_transaction,
    get_household_credit,
    get_registration,
    household_headers,
    pay_registration,
    register_participant,
    review_and_approve_application,
    setup_household_with_participants,
    setup_household_with_scholarship,
    setup_multi_session_catalog,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api


def _three_session_fee_catalog() -> dict:
    """Three published sessions at 10000 resident / 15001 nonresident under a
    season with family_discount_threshold 3 and family_discount_pct 10."""
    return setup_multi_session_catalog(
        [
            {"title": "S1", "fee_resident_cents": 10000,
             "fee_nonresident_cents": 15001},
            {"title": "S2", "fee_resident_cents": 10000,
             "fee_nonresident_cents": 15001},
            {"title": "S3", "fee_resident_cents": 10000,
             "fee_nonresident_cents": 15001},
        ],
        season_overrides={"family_discount_threshold": 3,
                          "family_discount_pct": 10,
                          "scholarship_budget_cents": 100000},
    )


def test_scholarship_step_applies_first(api):
    """PRD §3.6: "The scholarship step applies first: when the household holds
    an `APPROVED` application for the season, its `approved_pct` — locked onto
    the registration as `scholarship_pct_applied`, zero when no such
    application exists — is deducted by multiplying the base by one hundred
    minus that percent and dividing by one hundred, rounding half-up to a
    whole cent."
    PRD §3.6: "Count the household's existing registrations in the same season
    whose `enrollment_status` is `ENROLLED` — `WAITLISTED` siblings do not
    count — then add one for the registration being created; if that total
    reaches the season's `family_discount_threshold`, meeting the threshold
    exactly qualifies, and `family_discount_applied` is recorded true,
    otherwise false."

    Design: Difficulty/combinatorial_formula/fee_calculation_multi_input_branching
    """
    catalog = _three_session_fee_catalog()
    s1, s2, _s3 = catalog["sessions"]
    household_n, parts_n, _app = setup_household_with_scholarship(
        catalog["season"]["id"], 25, 5000, count=3, residency="NONRESIDENT",
        account_name="HN", name_prefix="Nn",
    )

    # Nonresident base 15001 with a 25% scholarship, no family discount yet:
    # round_half_up(15001 * 75 / 100) == 11251 for the first two registrations.
    r1 = register_participant(s1["session"]["id"], parts_n[0]["id"], household_n["id"])
    assert r1["fee_charged_cents"] == 11251
    assert r1["scholarship_pct_applied"] == 25
    assert r1["family_discount_applied"] is False

    r2 = register_participant(s2["session"]["id"], parts_n[1]["id"], household_n["id"])
    # existing ENROLLED == 1 -> 1 + 1 == 2 < threshold 3: still no family step.
    assert r2["fee_charged_cents"] == 11251
    assert r2["family_discount_applied"] is False


def test_family_step_after_scholarship_and_resident_control(api):
    """PRD §3.6: "The family step applies second: when the family discount
    evaluates in this registration's favor, the rounded intermediate is
    multiplied by one hundred minus the season's `family_discount_pct` and
    divided by one hundred, again rounding half-up to a whole cent. The two
    roundings are pinned in this order — scholarship first, family second."
    PRD §3.6: "The base is the session's `fee_resident_cents` when the
    household's `residency_status` is `RESIDENT` at the creation instant, and
    `fee_nonresident_cents` otherwise, a still-`PENDING` household paying the
    non-resident rate; that basis is snapshotted onto the registration as
    `residency_at_registration`, `RESIDENT` if and only if the household was
    `RESIDENT` at that instant."

    Design: Difficulty/combinatorial_formula/fee_calculation_multi_input_branching
    """
    catalog = _three_session_fee_catalog()
    s1, s2, s3 = catalog["sessions"]
    household_n, parts_n, _app = setup_household_with_scholarship(
        catalog["season"]["id"], 25, 5000, count=3, residency="NONRESIDENT",
        account_name="HN", name_prefix="Nn",
    )
    household_r, parts_r = setup_household_with_participants(
        count=1, residency="RESIDENT", account_name="HR", name_prefix="Res",
    )

    register_participant(s1["session"]["id"], parts_n[0]["id"], household_n["id"])
    register_participant(s2["session"]["id"], parts_n[1]["id"], household_n["id"])
    # Third registration: existing ENROLLED == 2 -> 2 + 1 >= 3 -> family step:
    # round_half_up(11251 * 90 / 100) == 10126.
    r3 = register_participant(s3["session"]["id"], parts_n[2]["id"], household_n["id"])
    assert r3["fee_charged_cents"] == 10126
    assert r3["scholarship_pct_applied"] == 25
    assert r3["family_discount_applied"] is True

    # Resident control registration: untouched 10000 resident base.
    rr = register_participant(s1["session"]["id"], parts_r[0]["id"], household_r["id"])
    assert rr["fee_charged_cents"] == 10000
    assert rr["residency_at_registration"] == "RESIDENT"
    assert rr["scholarship_pct_applied"] == 0


def _family_discount_catalog() -> dict:
    return setup_multi_session_catalog(
        [{"title": "SX", "capacity": 10, "fee_resident_cents": 10000,
          "fee_nonresident_cents": 10000}],
        season_overrides={"family_discount_threshold": 3, "family_discount_pct": 10},
    )


def test_family_discount_threshold_met_at_third_registration(api):
    """PRD §3.6: "Count the household's existing registrations in the same
    season whose `enrollment_status` is `ENROLLED` — `WAITLISTED` siblings do
    not count — then add one for the registration being created; if that total
    reaches the season's `family_discount_threshold`, meeting the threshold
    exactly qualifies, and `family_discount_applied` is recorded true,
    otherwise false."

    Design: Difficulty/combinatorial_formula/family_discount_threshold_evaluation_order
    """
    catalog = _family_discount_catalog()
    session_id = catalog["sessions"][0]["session"]["id"]
    household, kids = setup_household_with_participants(
        count=4, residency="RESIDENT", account_name="HR", name_prefix="Kid",
    )

    rp1 = register_participant(session_id, kids[0]["id"], household["id"])
    assert rp1["fee_charged_cents"] == 10000          # existing 0 -> 1 < 3
    assert rp1["family_discount_applied"] is False
    rp2 = register_participant(session_id, kids[1]["id"], household["id"])
    assert rp2["fee_charged_cents"] == 10000          # existing 1 -> 2 < 3
    # existing 2 -> 2 + 1 == 3 >= threshold 3: 10000 * 0.9 == 9000.
    rp3 = register_participant(session_id, kids[2]["id"], household["id"])
    assert rp3["fee_charged_cents"] == 9000
    assert rp3["family_discount_applied"] is True


def test_family_discount_never_recomputed_after_sibling_drop(api):
    """PRD §3.6: "There is no retroactivity: once recorded,
    `family_discount_applied` and `fee_charged_cents` never change."
    PRD §3.6: "The fee is computed exactly once at creation and stored in
    `fee_charged_cents`, never recomputed afterwards — later residency
    changes, later scholarship approvals or revocations, and later drops of
    siblings all leave it untouched."

    Design: Difficulty/combinatorial_formula/family_discount_threshold_evaluation_order
    """
    catalog = _family_discount_catalog()
    session_id = catalog["sessions"][0]["session"]["id"]
    household, kids = setup_household_with_participants(
        count=4, residency="RESIDENT", account_name="HR", name_prefix="Kid",
    )
    control, solo = setup_household_with_participants(
        count=2, residency="RESIDENT", account_name="H2", name_prefix="Solo",
    )

    register_participant(session_id, kids[0]["id"], household["id"])
    rp2 = register_participant(session_id, kids[1]["id"], household["id"])
    rp3 = register_participant(session_id, kids[2]["id"], household["id"])
    assert rp3["fee_charged_cents"] == 9000

    # Drop the second (paid) registration: full 10000 refund is at the review
    # threshold, so it waits for finance approval before crediting (PRD §3.7).
    pay_registration(rp2["id"], household["id"], amount_cents=10000)
    drop_registration(rp2["id"], household["id"])
    refund = find_refund_transaction(rp2["id"])
    validate_success(_api.approve_refund(refund["id"], FO))
    assert get_household_credit(household["id"]) == 10000

    # The survivor keeps its pinned discounted fee; a newcomer recomputes
    # against the current ENROLLED set ({rp1, rp3} -> 2 + 1 >= 3).
    assert get_registration(rp3["id"])["fee_charged_cents"] == 9000
    rp4 = register_participant(session_id, kids[3]["id"], household["id"])
    assert rp4["fee_charged_cents"] == 9000
    assert rp4["family_discount_applied"] is True

    # Control household: existing 0 then 1 -> never reaches the threshold.
    rq1 = register_participant(session_id, solo[0]["id"], control["id"])
    assert rq1["fee_charged_cents"] == 10000
    rq2 = register_participant(session_id, solo[1]["id"], control["id"])
    assert rq2["fee_charged_cents"] == 10000
    assert rq2["family_discount_applied"] is False


def test_scholarship_revoke_releases_commitment(api):
    """PRD §3.5: "A `FinanceOfficer` may revoke an `APPROVED` application,
    moving it to `REVOKED`; the revocation subtracts the application's
    `estimated_commitment_cents` from the season's
    `scholarship_committed_cents` as a compensating reversal, bumping the
    season's `version` once more. Revocation is deliberately non-retroactive
    for money already charged: existing registrations keep their pinned
    `scholarship_pct_applied` and `fee_charged_cents`, while future
    registrations by that household in that season receive a scholarship
    percent of zero."

    Design: Corner/calculations/scholarship_revoke_releases_commitment
    """
    catalog = setup_multi_session_catalog(
        [{"title": "Guitar", "fee_resident_cents": 10000,
          "fee_nonresident_cents": 10000}],
        season_overrides={"scholarship_budget_cents": 100000},
    )
    season_id = catalog["season"]["id"]
    session_id = catalog["sessions"][0]["session"]["id"]
    household, parts, application = setup_household_with_scholarship(
        season_id, 50, 5000, count=2, account_name="HS", name_prefix="Strum",
    )

    r1 = register_participant(session_id, parts[0]["id"], household["id"])
    assert r1["fee_charged_cents"] == 5000
    assert r1["scholarship_pct_applied"] == 50

    validate_success(_api.revoke_scholarship_application(application["id"], FO))
    season = validate_success(_api.get_season(season_id, PC))
    assert season["scholarship_committed_cents"] == 0

    r2 = register_participant(session_id, parts[1]["id"], household["id"])
    assert r2["fee_charged_cents"] == 10000
    assert r2["scholarship_pct_applied"] == 0

    assert get_registration(r1["id"])["fee_charged_cents"] == 5000


def _run_review_loop(application_id: str, household_id: str) -> dict:
    """Drive SUBMITTED -> UNDER_REVIEW -> MORE_INFO_REQUESTED -> RESUBMITTED
    -> UNDER_REVIEW -> APPROVED, returning each step's payload."""
    steps = {}
    steps["start1"] = validate_success(
        _api.start_review_scholarship_application(application_id, REV1))
    steps["request"] = validate_success(
        _api.request_info_scholarship_application(
            application_id, {"info_request_note": "provide paystub"}, REV1))
    steps["resubmit"] = validate_success(
        _api.resubmit_scholarship_application(
            application_id, {"statement": "paystub attached"},
            household_headers(household_id)))
    steps["start2"] = validate_success(
        _api.start_review_scholarship_application(application_id, REV1))
    steps["approve"] = validate_success(
        _api.approve_scholarship_application(
            application_id,
            {"approved_pct": 50, "estimated_commitment_cents": 5000}, REV2))
    return steps


def test_scholarship_review_cycle_states(api):
    """PRD §3.5: "A reviewer claims a `SUBMITTED` or `RESUBMITTED` application
    by starting review, moving it to `UNDER_REVIEW` and stamping `reviewed_by`
    with their own `X-User-ID`; a later start-review after resubmission
    overwrites the previous `reviewed_by`, and the segregation check always
    compares against this latest value. From `UNDER_REVIEW` the reviewer may
    request more information, moving the application to `MORE_INFO_REQUESTED`
    and recording the payload's `info_request_note` describing what to supply.
    The household then resubmits with an updated `statement` — the caller must
    belong to the applicant household, else `ERR_NOT_HOUSEHOLD_MEMBER` —
    returning the application to `RESUBMITTED`, from which a fresh
    start-review cycles it back to `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/scholarship_review_cycle
    """
    season = create_published_season(scholarship_budget_cents=100000)
    household = create_household("HX")
    application = submit_application(household["id"], season["id"],
                                     statement="initial")

    steps = _run_review_loop(application["id"], household["id"])
    assert steps["start1"]["status"] == "UNDER_REVIEW"
    assert steps["request"]["status"] == "MORE_INFO_REQUESTED"
    assert steps["request"]["info_request_note"] == "provide paystub"
    assert steps["resubmit"]["status"] == "RESUBMITTED"
    assert steps["resubmit"]["statement"] == "paystub attached"
    assert steps["start2"]["status"] == "UNDER_REVIEW"
    # The second start-review overwrote the first reviewer's stamp.
    assert steps["start2"]["reviewed_by"] == "rev-1"
    assert steps["approve"]["status"] == "APPROVED"


def test_scholarship_review_cycle_decision_side_effects(api):
    """PRD §3.5: "A successful approval stamps the payload's `approved_pct` —
    one of `25`, `50`, `75`, or `100` — and `estimated_commitment_cents` onto
    the application, records the caller as `decided_by`, and adds the
    commitment to the season's `scholarship_committed_cents`, bumping the
    season's `version`."

    Design: Difficulty/non_linear_state_machine/scholarship_review_cycle
    """
    season = create_published_season(scholarship_budget_cents=100000)
    household = create_household("HX")
    application = submit_application(household["id"], season["id"],
                                     statement="initial")

    steps = _run_review_loop(application["id"], household["id"])
    approved = steps["approve"]
    assert approved["status"] == "APPROVED"
    assert approved["approved_pct"] == 50
    assert approved["decided_by"] == "rev-2"
    season_after = validate_success(_api.get_season(season["id"], PC))
    assert season_after["scholarship_committed_cents"] == 5000


def test_withdraw_approved_application_rejected(api):
    """PRD §3.5: "Before any decision, the household may withdraw from
    `SUBMITTED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `RESUBMITTED`,
    moving the application to `WITHDRAWN` — again only for its own household."
    PRD §2.8: "Generic state-machine legality — the attempted trigger must be
    defined for the entity's current state. Publishing an already-published
    session, dropping an already-dropped registration, verifying an
    already-verified form, withdrawing a denied application, closing a season
    before its registration deadline, or completing a session with unfinished
    meetings are all `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_approved_application_rejected
    """
    season = create_published_season(scholarship_budget_cents=100000)
    household = create_household("HX")
    application = submit_application(household["id"], season["id"])
    review_and_approve_application(application["id"], 25, 5000)

    resp = _api.withdraw_scholarship_application(
        application["id"], household_headers(household))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_reviewer_cannot_approve_own_review(api):
    """PRD §3.5: "Approval moves the application to `APPROVED` and is fenced
    by two checks, evaluated state legality first, then segregation, then
    budget: the approving reviewer's `X-User-ID` must differ from
    `reviewed_by` — the same person may not both claim and approve — else
    `ERR_SEGREGATION_OF_DUTIES`; and the season's budget must absorb the
    commitment, meaning `scholarship_committed_cents` plus the payload's
    `estimated_commitment_cents` must not exceed the season's
    `scholarship_budget_cents`, with a commitment landing exactly on the
    remaining budget allowed, else `ERR_SCHOLARSHIP_BUDGET_EXCEEDED`."

    Design: Corner/rbac/reviewer_cannot_approve_own_review
    """
    season = create_published_season(scholarship_budget_cents=100000)
    household = create_household("HX")
    application = submit_application(household["id"], season["id"])
    validate_success(
        _api.start_review_scholarship_application(application["id"], REV1))

    resp = _api.approve_scholarship_application(
        application["id"],
        {"approved_pct": 25, "estimated_commitment_cents": 5000}, REV1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    approved = validate_success(
        _api.approve_scholarship_application(
            application["id"],
            {"approved_pct": 25, "estimated_commitment_cents": 5000}, REV2))
    assert approved["status"] == "APPROVED"
