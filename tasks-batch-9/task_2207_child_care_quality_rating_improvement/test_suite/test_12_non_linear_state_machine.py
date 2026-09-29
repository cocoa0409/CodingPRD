"""State machines that re-enter a state they already left.

The rating cycle returns to `AWARDED` after `UNDER_APPEAL`, the observation visit
returns to `SCORES_ENTERED` after `RELIABILITY_CHECK`, the appeal bounces between
`UNDER_REVIEW` and `INFO_REQUESTED`, and the grant's compliance dimension cycles back
into `UNDER_REVIEW` from `REMEDIATED` while the disbursement dimension never moves.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_grant,
    adjudicate_expenditure,
    approve_claim,
    build_rating_spine,
    create_expenditure_payload,
    file_appeal,
    make_observer_headers,
    make_provider_headers,
    make_reviewer_headers,
    offer_grant,
    pay_claim,
    score_payload,
    set_clock,
    start_appeal_review,
    submit_claim,
    submit_expenditure,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = make_reviewer_headers()

#: Five domains whose weights sum to 1.00; LEARNING_ENVIRONMENT is observation-linked.
DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 12,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 25,
        "block_min_points": 10,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 8,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 15,
        "block_min_points": 6,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 4,
        "weight": 0.10,
        "observation_linked": False,
    },
]

POINTS = {
    "LEARNING_ENVIRONMENT": 26,
    "STAFF_QUALIFICATIONS": 22,
    "FAMILY_PARTNERSHIP": 16,
    "ADMINISTRATION": 12,
    "CHILD_ASSESSMENT": 8,
}

#: The lead observer's six subscale scores average to 5.83.
LEAD_SCORES = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 6.0,
    "INTERACTION": 6.0,
    "PROGRAM_STRUCTURE": 5.0,
}
#: Five of six subscales land within 1.0 of the lead, so reliability is 83.33.
SECONDARY_SCORES_ADMISSIBLE = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 5.0,
    "INTERACTION": 7.0,
    "PROGRAM_STRUCTURE": 3.0,
}
#: ACTIVITIES is 3.0 away from the lead as well, so only four match and reliability is 66.67.
SECONDARY_SCORES_INADMISSIBLE = dict(SECONDARY_SCORES_ADMISSIBLE, ACTIVITIES=3.0)

#: Qualifying fte 1.80 against an active_staff_fte of 2.00, so compliance is 90.00.
CREDENTIALS_90 = [
    {"role_type": "DIRECTOR", "credential_level": 5, "fte": 1.00,
     "expires_on": "2027-12-31"},
    {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 0.80,
     "expires_on": "2027-12-31"},
]


def _tier_four_spine(stop_at, legal_name, license_number, licensed_capacity=80,
                     **overrides):
    """Two-observer spine that awards tier 4 on 2026-08-10 at weighted_total 80.00."""
    params = {
        "stop_at": stop_at,
        "domains": DOMAINS,
        "provider_overrides": {
            "legal_name": legal_name,
            "license_number": license_number,
            "county_code": "MARION",
            "region_code": "RURAL",
            "licensed_capacity": licensed_capacity,
            "active_staff_fte": 2.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        "credentials": CREDENTIALS_90,
        "claimed": POINTS,
        "verified": POINTS,
        "with_secondary": True,
        "lead_per_subscale": LEAD_SCORES,
        "secondary_per_subscale": SECONDARY_SCORES_ADMISSIBLE,
        "window_start": "2026-08-05T09:00:00Z",
        "window_end": "2026-08-05T13:00:00Z",
        "enrol_clock": "2026-08-03T00:00:00Z",
        "cycle_clock": "2026-08-04T00:00:00Z",
        "award_clock": "2026-08-10T00:00:00Z",
        "activation_clock": "2026-09-05T00:00:00Z",
    }
    params.update(overrides)
    return build_rating_spine(**params)


# --- RatingCycle: AWARDED -> UNDER_APPEAL -> AWARDED -------------------------


def _sustained_appeal_cycle(api):
    """Published tier-4 cycle with a paid claim, then an appeal sustained at tier 5."""
    ctx = _tier_four_spine("PUBLISHED", "Sunrise Learning Center", "LIC-2207-A")
    claim = submit_claim(ctx["provider"]["id"], "2026-09", 100, 200, 300)
    claim = approve_claim(claim["id"], "INTERIM")
    claim = pay_claim(claim["id"])

    set_clock("2026-09-08T00:00:00Z")
    appeal = file_appeal(ctx["provider"]["id"], ctx["cycle"]["id"], "SCORING_ERROR")
    appeal = start_appeal_review(appeal["id"])
    sustained = validate_success(
        api.appeal_review_action(
            appeal["id"], {"action": "SUSTAIN", "adjusted_tier": 5}, REVIEWER
        )
    )
    return ctx, claim, sustained


def test_sustained_appeal_drives_the_cycle_back_into_awarded_from_under_appeal(api):
    """PRD §3.6: "The appeal moves `UNDER_REVIEW → SUSTAINED` and stamps `decided_on`, and a
    three-hop cascade follows. In the first hop the cycle returns `UNDER_APPEAL → AWARDED`
    with its `awarded_tier` replaced by the ordered `adjusted_tier`, `appeal_adjusted` set to
    true, and the validity arithmetic rerun while keeping the original `effective_date`."
    PRD §3.6: "Finally, the cycle's publication state becomes `UNPUBLISHED`, so a corrected
    snapshot has to be republished rather than the stale one silently persisting. The cycle
    path `AWARDED → UNDER_APPEAL → AWARDED` is genuinely cyclic."

    Design: Difficulty/non_linear_state_machine/rating_cycle_awarded_under_appeal_awarded_cycle
    """
    ctx, _claim, sustained = _sustained_appeal_cycle(api)

    assert sustained["status"] == "SUSTAINED", (
        f"the appeal must reach SUSTAINED, got {sustained['status']}"
    )
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "AWARDED", (
        f"the cycle re-enters AWARDED after UNDER_APPEAL, got {cycle['status']}"
    )
    assert cycle["awarded_tier"] == 5, (
        f"awarded_tier is replaced by the ordered adjusted_tier 5, got "
        f"{cycle['awarded_tier']}"
    )
    assert cycle["appeal_adjusted"] is True, (
        f"appeal_adjusted must be true after a sustain, got {cycle['appeal_adjusted']}"
    )
    assert cycle["publication_status"] == "UNPUBLISHED", (
        f"the publication state becomes UNPUBLISHED, got {cycle['publication_status']}"
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["public_listing_visible"] is False, (
        f"the cycle named by current_rating_cycle_id is no longer PUBLISHED, so "
        f"public_listing_visible must be false, got {provider['public_listing_visible']}"
    )


def test_appeal_adjusted_validity_rerun_keeps_the_original_effective_date(api):
    """PRD §3.5: "When the cycle carries `appeal_adjusted` as true — that is, on the rerun
    triggered by a sustained appeal — the `effective_date` is instead the value stored by the
    cycle's original award and is not moved by the appeal decision date."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise.
    The `expires_on` instant is the `effective_date` advanced by that many calendar months and
    then pulled back by one day, at 23:59:59.999 UTC."

    Design: Difficulty/non_linear_state_machine/rating_cycle_awarded_under_appeal_awarded_cycle
    """
    ctx, _claim, _sustained = _sustained_appeal_cycle(api)
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))

    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z", (
        f"the effective_date stored by the 2026-08-10 award survives the 2026-09-08 appeal "
        f"decision, got {cycle['effective_date']}"
    )
    assert cycle["validity_months"] == 36, (
        f"awarded_tier 5 is at least 4, so validity_months is 36, got "
        f"{cycle['validity_months']}"
    )
    assert cycle["expires_on"] == "2029-08-31T23:59:59.999Z", (
        f"2026-09-01 plus 36 months less one day, got {cycle['expires_on']}"
    )
    assert cycle["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z", (
        f"2029-08-31 minus 90 days, got {cycle['rerating_window_opens_on']}"
    )


# --- ObservationVisit: RELIABILITY_CHECK -> SCORES_ENTERED -> FINALIZED -------

#: Qualifying fte 1.20 against an active_staff_fte of 2.00, so compliance is 60.00.
CREDENTIALS_60 = [
    {"role_type": "DIRECTOR", "credential_level": 4, "fte": 1.00,
     "expires_on": "2027-12-31"},
    {"role_type": "ASSISTANT", "credential_level": 1, "fte": 0.20,
     "expires_on": "2027-12-31"},
]

POINTS_SINGLE_OBSERVER = {
    "LEARNING_ENVIRONMENT": 15,
    "STAFF_QUALIFICATIONS": 12,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 7,
    "CHILD_ASSESSMENT": 5,
}


def _visit_at_reliability_check_below_threshold():
    """Two-observer visit whose reliability lands at 66.67 and cannot be finalized."""
    return _tier_four_spine(
        "RELIABILITY_CHECK",
        "Cedar House Child Care",
        "LIC-2207-C",
        licensed_capacity=60,
        secondary_per_subscale=SECONDARY_SCORES_INADMISSIBLE,
    )


def test_finalize_is_refused_while_reliability_sits_below_the_admissible_threshold(api):
    """PRD §3.4: "The reliability percentage is one hundred multiplied by the matched count,
    divided by six, and rounded half up to two decimal places. Scores are admissible when
    that percentage is at least 83.33 — the comparison is inclusive."
    PRD §3.4: "Five matched subscales produce exactly 83.33 and therefore pass; four matched
    subscales produce 66.67 and fail."

    Design: Difficulty/non_linear_state_machine/observation_visit_fork_join_with_reliability_rescore_loop
    """
    ctx = _visit_at_reliability_check_below_threshold()
    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["reliability_pct"] == pytest.approx(66.67, abs=0.005), (
        f"four of six subscales are within 1.0, so reliability_pct is 66.67, got "
        f"{visit['reliability_pct']}"
    )
    assert visit["status"] == "RELIABILITY_CHECK"

    validate_error(
        api.finalize_visit(ctx["visit"]["id"], ADMIN),
        "ERR_RELIABILITY_BELOW_THRESHOLD",
        422,
    )

    unchanged = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert unchanged["status"] == "RELIABILITY_CHECK", (
        f"the refused finalization must leave the visit at RELIABILITY_CHECK, got "
        f"{unchanged['status']}"
    )
    assert unchanged["rescore_count"] == 0


def test_secondary_rescore_appends_an_attempt_and_lifts_reliability_to_admissible(api):
    """PRD §3.4: "From `RELIABILITY_CHECK`, either observer may replace a subscale score;
    that submission returns the visit `RELIABILITY_CHECK → SCORES_ENTERED`, appends the new
    attempt row, demotes the prior row, increments `rescore_count` by 1, and recomputes both
    the composite and the reliability percentage."
    PRD §3.4: "The composite is the lead observer's average, and only the lead observer's."

    Design: Difficulty/non_linear_state_machine/observation_visit_fork_join_with_reliability_rescore_loop
    """
    ctx = _visit_at_reliability_check_below_threshold()
    validate_error(
        api.finalize_visit(ctx["visit"]["id"], ADMIN),
        "ERR_RELIABILITY_BELOW_THRESHOLD",
        422,
    )

    validate_success(
        api.submit_score(
            ctx["visit"]["id"],
            score_payload("ACTIVITIES", 5.0),
            make_observer_headers(ctx["secondary"]["id"]),
        ),
        201,
    )

    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["rescore_count"] == 1, (
        f"one rescore from RELIABILITY_CHECK increments rescore_count to 1, got "
        f"{visit['rescore_count']}"
    )
    assert visit["reliability_pct"] == pytest.approx(83.33, abs=0.005), (
        f"five of six subscales now match, so reliability_pct is 83.33, got "
        f"{visit['reliability_pct']}"
    )
    assert visit["composite"] == pytest.approx(5.83, abs=0.005), (
        f"the composite is the lead average and is untouched by a secondary rescore, got "
        f"{visit['composite']}"
    )

    rows, _meta = validate_paginated(
        api.list_observation_scores(
            ADMIN,
            params={
                "observation_visit_id": ctx["visit"]["id"],
                "observer_id": ctx["secondary"]["id"],
                "subscale_code": "ACTIVITIES",
                "limit": 100,
            },
        )
    )
    by_attempt = {row["attempt_no"]: row for row in rows}
    assert by_attempt[2]["is_current"] is True, (
        "the appended attempt_no 2 row must be the current row"
    )
    assert by_attempt[1]["is_current"] is False, (
        "the demoted attempt_no 1 row must no longer be current"
    )
    assert by_attempt[2]["raw_score"] == pytest.approx(5.0, abs=0.005)


def test_reliability_checked_branch_keeps_the_percentage_on_visit_and_cycle(api):
    """PRD §3.4: "The reliability-checked branch runs from `RELIABILITY_CHECK → FINALIZED`.
    It requires the visit's `reliability_pct` to be at least 83.33, and it requires both named
    observers to be in `RELIABLE` standing with certification covering the visit's
    `window_start` date. It stamps `finalized_on` from the logical clock, keeps the computed
    `reliability_pct` on the visit, propagates both the composite and the reliability
    percentage onto the parent cycle as `observation_composite` and `reliability_pct`,
    advances the cycle `OBSERVATION_SCHEDULED → OBSERVATION_FINALIZED`, and reruns the
    per-domain points award under the final variant."

    Design: Difficulty/non_linear_state_machine/observation_visit_fork_join_with_reliability_rescore_loop
    """
    ctx = _visit_at_reliability_check_below_threshold()
    validate_error(
        api.finalize_visit(ctx["visit"]["id"], ADMIN),
        "ERR_RELIABILITY_BELOW_THRESHOLD",
        422,
    )
    validate_success(
        api.submit_score(
            ctx["visit"]["id"],
            score_payload("ACTIVITIES", 5.0),
            make_observer_headers(ctx["secondary"]["id"]),
        ),
        201,
    )

    finalized = validate_success(api.finalize_visit(ctx["visit"]["id"], ADMIN))
    assert finalized["status"] == "FINALIZED", (
        f"the visit must reach FINALIZED once reliability is admissible, got "
        f"{finalized['status']}"
    )
    assert finalized["reliability_pct"] == pytest.approx(83.33, abs=0.005), (
        f"the reliability-checked branch keeps the computed value, got "
        f"{finalized['reliability_pct']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED"
    assert cycle["observation_composite"] == pytest.approx(5.83, abs=0.005)
    assert cycle["reliability_pct"] == pytest.approx(83.33, abs=0.005)
    assert cycle["domain_points"] == {
        "LEARNING_ENVIRONMENT": 24,
        "STAFF_QUALIFICATIONS": 20,
        "FAMILY_PARTNERSHIP": 16,
        "ADMINISTRATION": 12,
        "CHILD_ASSESSMENT": 8,
    }


def test_single_observer_branch_nulls_the_reliability_percentage_at_the_same_join(api):
    """PRD §3.4: "The single-observer branch runs from `SCORES_ENTERED → FINALIZED` and is
    legal only below the upper tiers. It requires that the visit have no
    `secondary_observer_id` at all, that the tier implied by a provisional tier-determination
    run be no greater than 3, and that the lead observer be in `RELIABLE` standing with
    certification covering `window_start`. It stamps `finalized_on`, sets the visit's
    `reliability_pct` to null rather than to a computed value, propagates the composite onto
    the cycle while leaving the cycle's `reliability_pct` null, advances the cycle to
    `OBSERVATION_FINALIZED`, and likewise reruns the final points award."

    Design: Difficulty/non_linear_state_machine/observation_visit_fork_join_with_reliability_rescore_loop
    """
    ctx = _tier_four_spine(
        "SCORES_ENTERED",
        "Dogwood Early Center",
        "LIC-2207-D",
        licensed_capacity=40,
        credentials=CREDENTIALS_60,
        claimed=POINTS_SINGLE_OBSERVER,
        verified=POINTS_SINGLE_OBSERVER,
        with_secondary=False,
        lead_per_subscale=None,
        secondary_per_subscale=None,
        raw_score=4.0,
        window_start="2026-08-06T09:00:00Z",
        window_end="2026-08-06T13:00:00Z",
    )
    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["status"] == "SCORES_ENTERED"

    finalized = validate_success(api.finalize_visit(ctx["visit"]["id"], ADMIN))
    assert finalized["status"] == "FINALIZED"
    assert finalized["reliability_pct"] is None, (
        f"the single-observer branch sets reliability_pct to null, got "
        f"{finalized['reliability_pct']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED"
    assert cycle["observation_composite"] == pytest.approx(4.00, abs=0.005)
    assert cycle["reliability_pct"] is None, (
        f"the cycle's reliability_pct stays null on the single-observer branch, got "
        f"{cycle['reliability_pct']}"
    )
    assert cycle["domain_points"] == {
        "LEARNING_ENVIRONMENT": 18,
        "STAFF_QUALIFICATIONS": 10,
        "FAMILY_PARTNERSHIP": 10,
        "ADMINISTRATION": 7,
        "CHILD_ASSESSMENT": 5,
    }


# --- ImprovementGrant: the compliance axis cycles while OPEN never moves ------


def _open_grant_e():
    """Published tier-4 provider plus an OPEN 1,000,000 cent grant. Returns (ctx, grant)."""
    ctx = _tier_four_spine(
        "PUBLISHED", "Evergreen Kids Academy", "LIC-2207-E", licensed_capacity=70
    )
    grant = offer_grant(
        ctx["provider"]["id"], ctx["cycle"]["id"], 1_000_000, "2026-12-31"
    )
    grant = accept_grant(ctx["provider"]["id"], grant["id"])
    return ctx, grant


def _reject_one_equipment_line(ctx, grant, invoice_date):
    line = submit_expenditure(
        ctx["provider"]["id"], grant["id"], "EQUIPMENT", 200_000, invoice_date
    )
    return adjudicate_expenditure(line["id"], "REJECT")


def test_first_expenditure_rejection_moves_compliance_without_moving_disbursement(api):
    """PRD §3.8: "Rejection moves the line `SUBMITTED → REJECTED` and unwinds the commitment
    exactly: `committed_cents` decreases by the line's `amount_cents`, `available_cents`
    increases by the same amount, and that category's `category_spend_cents` entry decreases by
    the same amount, so a submit-then-reject pair leaves the grant's ledger identity intact
    with zero drift. Rejection also drives the compliance dimension: a first rejection moves it
    `COMPLIANT → UNDER_REVIEW`, a second rejection on the same grant moves it
    `UNDER_REVIEW → FINDING_ISSUED`, and a rejection against a grant already `REMEDIATED` moves
    it back `REMEDIATED → UNDER_REVIEW`, making the compliance axis cyclic."
    PRD §3.8: "The two evolve separately: a grant may be `OPEN` and `FINDING_ISSUED` at the
    same time, or `CLOSED` and still `COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/improvement_grant_orthogonal_compliance_axis
    """
    ctx, grant = _open_grant_e()
    line = submit_expenditure(
        ctx["provider"]["id"], grant["id"], "EQUIPMENT", 200_000, "2026-09-10"
    )

    committed = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert committed["status"] == "OPEN"
    assert committed["compliance_status"] == "COMPLIANT"
    assert committed["committed_cents"] == 200_000
    assert committed["available_cents"] == 800_000
    assert committed["category_spend_cents"]["EQUIPMENT"] == 200_000

    rejected = adjudicate_expenditure(line["id"], "REJECT")
    assert rejected["status"] == "REJECTED"

    after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert after["compliance_status"] == "UNDER_REVIEW", (
        f"a first rejection moves compliance COMPLIANT -> UNDER_REVIEW, got "
        f"{after['compliance_status']}"
    )
    assert after["status"] == "OPEN", (
        f"the disbursement dimension must stay exactly OPEN, got {after['status']}"
    )
    assert after["committed_cents"] == 0, (
        f"the rejection unwinds the commitment to 0, got {after['committed_cents']}"
    )
    assert after["available_cents"] == 1_000_000, (
        f"available_cents returns to the full award, got {after['available_cents']}"
    )
    assert after["category_spend_cents"]["EQUIPMENT"] == 0, (
        f"the EQUIPMENT bucket returns to 0, got "
        f"{after['category_spend_cents']['EQUIPMENT']}"
    )


def test_second_rejection_issues_a_finding_that_holds_further_submission(api):
    """PRD §3.8: "a second rejection on the same grant moves it
    `UNDER_REVIEW → FINDING_ISSUED`"
    PRD §3.8: "the compliance hold, which refuses submission with
    `ERR_GRANT_COMPLIANCE_HOLD` and HTTP 409 while the compliance dimension sits at
    `FINDING_ISSUED`, since a finding must be remediated first"

    Design: Difficulty/non_linear_state_machine/improvement_grant_orthogonal_compliance_axis
    """
    ctx, grant = _open_grant_e()
    _reject_one_equipment_line(ctx, grant, "2026-09-10")
    _reject_one_equipment_line(ctx, grant, "2026-09-15")

    held = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert held["compliance_status"] == "FINDING_ISSUED", (
        f"the second rejection moves compliance UNDER_REVIEW -> FINDING_ISSUED, got "
        f"{held['compliance_status']}"
    )
    assert held["status"] == "OPEN", (
        f"the disbursement dimension must stay exactly OPEN, got {held['status']}"
    )
    assert held["available_cents"] == 1_000_000

    validate_error(
        api.create_expenditure(
            grant["id"],
            create_expenditure_payload(
                held["version"], "PROF_DEV", 150_000, "2026-09-20"
            ),
            make_provider_headers(ctx["provider"]["id"]),
        ),
        "ERR_GRANT_COMPLIANCE_HOLD",
        409,
    )


def test_remediation_reopens_submission_and_a_later_rejection_re_enters_under_review(api):
    """PRD §3.8: "Remediating is how a provider clears a compliance finding: it moves the
    compliance dimension `FINDING_ISSUED → REMEDIATED` and permits expenditure submission
    again once the grant is `OPEN`."
    PRD §3.8: "a rejection against a grant already `REMEDIATED` moves it back
    `REMEDIATED → UNDER_REVIEW`, making the compliance axis cyclic."

    Design: Difficulty/non_linear_state_machine/improvement_grant_orthogonal_compliance_axis
    """
    ctx, grant = _open_grant_e()
    provider_headers = make_provider_headers(ctx["provider"]["id"])
    _reject_one_equipment_line(ctx, grant, "2026-09-10")
    _reject_one_equipment_line(ctx, grant, "2026-09-15")

    remediated = validate_success(
        api.grant_decision(grant["id"], {"decision": "REMEDIATE"}, provider_headers)
    )
    assert remediated["compliance_status"] == "REMEDIATED", (
        f"REMEDIATE moves compliance FINDING_ISSUED -> REMEDIATED, got "
        f"{remediated['compliance_status']}"
    )
    assert remediated["status"] == "OPEN", (
        f"the disbursement dimension must stay exactly OPEN, got {remediated['status']}"
    )

    line = validate_success(
        api.create_expenditure(
            grant["id"],
            create_expenditure_payload(
                remediated["version"], "PROF_DEV", 150_000, "2026-09-20"
            ),
            provider_headers,
        ),
        201,
    )
    admitted = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert admitted["committed_cents"] == 150_000, (
        f"the remediated grant admits the line, got {admitted['committed_cents']}"
    )
    assert admitted["available_cents"] == 850_000
    assert admitted["category_spend_cents"]["PROF_DEV"] == 150_000

    adjudicate_expenditure(line["id"], "REJECT")
    cycled = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert cycled["compliance_status"] == "UNDER_REVIEW", (
        f"a rejection against a REMEDIATED grant re-enters UNDER_REVIEW, got "
        f"{cycled['compliance_status']}"
    )
    assert cycled["status"] == "OPEN", (
        f"the disbursement dimension never left OPEN, got {cycled['status']}"
    )


# --- Appeal: UNDER_REVIEW <-> INFO_REQUESTED, twice and no more --------------


def _appeal_under_review_f():
    """Published tier-4 cycle with an appeal filed on 2026-09-08 and review started."""
    ctx = _tier_four_spine(
        "PUBLISHED", "Foxglove Learning Co-op", "LIC-2207-F", licensed_capacity=55
    )
    set_clock("2026-09-08T00:00:00Z")
    appeal = file_appeal(
        ctx["provider"]["id"], ctx["cycle"]["id"], "DOCUMENTATION_OMITTED"
    )
    appeal = start_appeal_review(appeal["id"])
    return ctx, appeal


def _request_info(api, appeal_id):
    return api.appeal_review_action(appeal_id, {"action": "REQUEST_INFO"}, REVIEWER)


def _respond(api, appeal_id, provider_id, narrative):
    return validate_success(
        api.appeal_provider_action(
            appeal_id,
            {"action": "RESPOND", "narrative": narrative},
            make_provider_headers(provider_id),
        )
    )


def test_information_request_loop_runs_exactly_twice_then_hits_the_round_limit(api):
    """PRD §3.6: "Requesting information moves the appeal `UNDER_REVIEW → INFO_REQUESTED` and
    increments `info_request_count` by 1, and it is available only while `info_request_count`
    is less than 2 — a third request is `ERR_APPEAL_INFO_ROUND_LIMIT` with HTTP 409 — and only
    to the reviewer already recorded on the appeal. The provider answers with its own action:
    responding moves the appeal `INFO_REQUESTED → UNDER_REVIEW`, appending the supplied
    `narrative` and changing no counter, and it requires the acting identifier to be the
    cycle's provider. The negotiation loop `UNDER_REVIEW → INFO_REQUESTED → UNDER_REVIEW`
    therefore runs at most twice."

    Design: Difficulty/non_linear_state_machine/appeal_under_review_info_requested_bidirectional_rounds
    """
    ctx, appeal = _appeal_under_review_f()
    provider_id = ctx["provider"]["id"]

    first = validate_success(_request_info(api, appeal["id"]))
    assert first["status"] == "INFO_REQUESTED", (
        f"the first request moves UNDER_REVIEW -> INFO_REQUESTED, got {first['status']}"
    )
    assert first["info_request_count"] == 1

    back = _respond(api, appeal["id"], provider_id, "First bundle of missing records.")
    assert back["status"] == "UNDER_REVIEW", (
        f"RESPOND returns the appeal to UNDER_REVIEW, got {back['status']}"
    )
    assert back["info_request_count"] == 1, (
        f"RESPOND changes no counter, got {back['info_request_count']}"
    )

    second = validate_success(_request_info(api, appeal["id"]))
    assert second["status"] == "INFO_REQUESTED"
    assert second["info_request_count"] == 2, (
        f"the second request increments the counter to 2, got "
        f"{second['info_request_count']}"
    )

    back_again = _respond(
        api, appeal["id"], provider_id, "Second bundle of missing records."
    )
    assert back_again["status"] == "UNDER_REVIEW"
    assert back_again["info_request_count"] == 2

    validate_error(
        _request_info(api, appeal["id"]), "ERR_APPEAL_INFO_ROUND_LIMIT", 409
    )

    unchanged = validate_success(api.get_appeal(appeal["id"], ADMIN))
    assert unchanged["status"] == "UNDER_REVIEW", (
        f"the refused third request leaves the appeal at UNDER_REVIEW, got "
        f"{unchanged['status']}"
    )
    assert unchanged["info_request_count"] == 2, (
        f"the refused third request leaves info_request_count at 2, got "
        f"{unchanged['info_request_count']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "UNDER_APPEAL", (
        f"the cycle stays UNDER_APPEAL for the whole negotiation, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "SUPPRESSED", (
        f"filing suppressed the publication and the loop does not restore it, got "
        f"{cycle['publication_status']}"
    )


def test_denial_after_two_rounds_restores_the_active_published_cycle_unchanged(api):
    """PRD §3.6: "Denying an appeal from `UNDER_REVIEW` moves it to `DENIED`, stamps
    `decided_on`, and returns the cycle `UNDER_APPEAL → ACTIVE`; the cycle's publication state
    returns to `PUBLISHED` when `published_at` is non-null and otherwise stays `UNPUBLISHED`,
    and the held subsidy claims become adjudicable again."

    Design: Difficulty/non_linear_state_machine/appeal_under_review_info_requested_bidirectional_rounds
    """
    ctx, appeal = _appeal_under_review_f()
    provider_id = ctx["provider"]["id"]
    validate_success(_request_info(api, appeal["id"]))
    _respond(api, appeal["id"], provider_id, "First bundle of missing records.")
    validate_success(_request_info(api, appeal["id"]))
    _respond(api, appeal["id"], provider_id, "Second bundle of missing records.")

    denied = validate_success(
        api.appeal_review_action(appeal["id"], {"action": "DENY"}, REVIEWER)
    )
    assert denied["status"] == "DENIED", (
        f"DENY from UNDER_REVIEW moves the appeal to DENIED, got {denied['status']}"
    )
    assert denied["info_request_count"] == 2
    assert denied["decided_on"].startswith("2026-09-08"), (
        f"decided_on is stamped from the logical clock date 2026-09-08, got "
        f"{denied['decided_on']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "ACTIVE", (
        f"the denial returns the cycle UNDER_APPEAL -> ACTIVE, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "PUBLISHED", (
        f"published_at is non-null, so publication returns to PUBLISHED, got "
        f"{cycle['publication_status']}"
    )
    assert cycle["awarded_tier"] == 4, (
        f"a denial leaves awarded_tier untouched at 4, got {cycle['awarded_tier']}"
    )
    assert cycle["appeal_adjusted"] is False, (
        f"a denial never sets appeal_adjusted, got {cycle['appeal_adjusted']}"
    )
