"""Endpoint breadth probes: one endpoint answering for state another endpoint made.

Every test here drives two or more endpoints in sequence so that the outcome of
the last call is only explicable by a side effect of an earlier one -- a pin
going stale, a fee that was never posted, a sweep reaching an expiry instant.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_instant_equals,
    count_entries,
    read_billing_run,
    read_budget,
    read_case,
    read_certificate,
    read_contract,
    read_element,
    read_special_assessment,
    read_unit,
)
from test_helpers.factories import (
    billing_run_payload,
    charge_payload,
    installment_payload,
    payment_payload,
    refund_payload,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    adopt_budget,
    approve_special_assessment,
    board_vote_yes,
    convene,
    create_association,
    docket_hearing,
    draft_budget,
    issue_certificate,
    notice_meeting,
    notice_violation_case,
    request_certificate,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS, TITLE_AGENT_HEADERS

HARBOR_POINT = "Harbor Point Condominium Association"


def _seat_a_single_director(ctx) -> None:
    """Seat one director against a ``board_quorum_seats`` of 1."""
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )


# ======================================================================
# An award pinned to a version the next endpoint no longer sees
# ======================================================================
def test_revising_the_element_after_the_award_blocks_activation_on_the_pin(api):
    """The award pins, the PATCH bumps, and activation is the endpoint that pays.

    Approval records `pinned_element_version`; a single manager revision of the
    element's `replacement_cost_cents` advances `CommonElement.version` past that
    pin, so activation -- an endpoint that never touched the element -- refuses.
    The contract must be left exactly as the board left it, still `APPROVED` and
    still carrying the now-stale pin.

    PRD 3.6: "On success the server writes `approval_yes_count`, **pins**
    `pinned_element_version` to the element's `version` at that instant, and
    advances `VendorContract.version` by 1."
    PRD 3.6: "A manager may revise a component's `replacement_cost_cents`,
    `useful_life_years`, `effective_age_years`, `status`, or
    `reserve_designated_cents`; every such revision advances
    `CommonElement.version` by 1, which -- as §3.6 explains below -- invalidates
    any board award that pinned the old version."
    PRD 3.6: "The logical clock must lie at or after `effective_from` and
    strictly before `effective_to`; `insurance_cert_expires_at` must be strictly
    after the logical clock, failing which the response is
    `ERR_VENDOR_INSURANCE_LAPSED`; and the element's current `version` must
    still equal `pinned_element_version`, because a mutated element invalidates
    the board's award -- a mismatch yields `ERR_ELEMENT_SPEC_CHANGED`."
    PRD 3.6: "The only effect is to advance `VendorContract.version` by 1."

    Design: Corner/endpoints/patching_the_element_spec_breaks_the_awarded_contracts_pin_on_activation
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_a_single_director(ctx)
    element_id = add_element(
        ctx,
        "el1",
        name="North Tower Elevator",
        element_class="ELEVATOR",
        replacement_cost_cents=30_000_000,
        useful_life_years=25,
        effective_age_years=5,
    )
    contract_id = add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Ascend Elevator Service LLC",
        contract_cap_cents=5_000_000,
        insurance_cert_expires_at="2027-06-30T00:00:00Z",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-06-30T00:00:00Z",
    )
    schedule_meeting(
        ctx, "mtg_ca", ["CONTRACT_AWARD"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z"
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-08-05T10:00:00Z")
    convene(ctx, "mtg_ca", attending=("d1",))

    get_success_data(api.submit_contract(contract_id, MANAGER_HEADERS))
    board_vote_yes(
        ctx, "VENDOR_CONTRACT", contract_id, "mtg_ca", voters=(("d1", "101"),)
    )
    awarded = get_success_data(api.approve_contract(contract_id, ctx.director("d1")))
    assert awarded["status"] == "APPROVED"
    pinned_version = awarded["pinned_element_version"]
    assert pinned_version == read_element(api, element_id, MANAGER_HEADERS)["version"]

    revised = get_success_data(
        api.update_common_element(
            element_id, {"replacement_cost_cents": 33_000_000}, MANAGER_HEADERS
        )
    )
    assert revised["version"] == pinned_version + 1

    validate_error(
        api.activate_contract(contract_id, MANAGER_HEADERS),
        "ERR_ELEMENT_SPEC_CHANGED",
        409,
    )

    stalled = read_contract(api, contract_id, MANAGER_HEADERS)
    assert stalled["status"] == "APPROVED"
    assert stalled["pinned_element_version"] == pinned_version
    assert stalled["pinned_element_version"] < revised["version"]
    assert stalled["suspension_reason"] == "NONE"

    untouched = read_element(api, element_id, MANAGER_HEADERS)
    assert untouched["replacement_cost_cents"] == 33_000_000
    assert untouched["status"] == "SERVICEABLE"


# ======================================================================
# Certificate issuance depends on an endpoint nobody called
# ======================================================================
def test_issuing_a_certificate_with_only_a_proposed_budget_posts_no_fee(api):
    """A budget that exists is not a budget that was adopted.

    The fiscal-2026 budget sits at `PROPOSED` because ratification never ran, so
    issuance refuses; and because the fee posting is the **first** side effect of
    issuance, a refusal must leave the unit ledger completely empty rather than
    charged for a certificate that was never produced.

    PRD 3.9: "Issuance is a `CommunityManager` act moving `REQUESTED → ISSUED`."
    PRD 3.9: "Four conditions apply: the certificate must be `REQUESTED`; the
    unit's `delinquency_stage` must not be `FORECLOSURE_REFERRAL`, or the
    response is `ERR_CERT_BLOCKED_BY_FORECLOSURE`; a budget whose `status` is
    `ADOPTED` must exist whose `fiscal_year` contains the `closing_date`, or the
    response is `ERR_BUDGET_NOT_ADOPTED`; and `closing_date` must be at or after
    the logical clock, a past closing date being refused with
    `ERR_CERT_CLOSING_DATE_PAST`."
    PRD 3.9: "First the `RESALE_FEE` row is posted on the unit for
    `resale_cert_fee_cents`, with its identifier stored in `cert_fee_entry_id`,
    and the unit's `balance_due_cents` and `delinquency_stage` are recomputed
    with `Unit.version` advancing by 1."
    PRD 3.9: "The certificate is born with `status` `REQUESTED` and with
    `ledger_balance_cents`, `projected_payoff_cents`, `proration_credit_cents`,
    `open_violation_count`, and `special_assessment_disclosure_cents` at 0,
    `disclosed_claim_ids` empty, `requires_reissue` false, and
    `pinned_budget_id`, `pinned_unit_version`, `pinned_budget_version`,
    `cert_fee_entry_id`, `issued_at`, and `expires_at` all null."

    Design: Corner/endpoints/certificate_issue_without_an_adopted_budget_returns_budget_not_adopted
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_200)

    budget = draft_budget(ctx)
    meeting_id = schedule_meeting(
        ctx,
        "mtg_b",
        ["BUDGET_RATIFICATION"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    get_success_data(
        api.propose_budget(
            budget["id"], MANAGER_HEADERS, payload={"ratification_meeting_id": meeting_id}
        )
    )
    assert read_budget(api, budget["id"], MANAGER_HEADERS)["status"] == "PROPOSED"

    certificate = request_certificate(
        ctx, "101", closing_date="2026-11-16T00:00:00Z"
    )
    assert certificate["status"] == "REQUESTED"
    version_after_request = ctx.unit_version("101")

    validate_error(
        api.issue_resale_certificate(certificate["id"], MANAGER_HEADERS),
        "ERR_BUDGET_NOT_ADOPTED",
        409,
    )

    stalled = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert stalled["status"] == "REQUESTED"
    assert stalled["issued_at"] is None
    assert stalled["expires_at"] is None
    assert stalled["pinned_budget_id"] is None
    assert stalled["pinned_budget_version"] is None
    assert stalled["pinned_unit_version"] is None
    assert stalled["cert_fee_entry_id"] is None
    assert stalled["ledger_balance_cents"] == 0

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 0
    unit = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert unit["balance_due_cents"] == 0
    assert unit["version"] == version_after_request


# ======================================================================
# A computed read that disagrees with the row it reads
# ======================================================================
def test_the_questionnaire_flags_reissue_while_the_stored_row_stays_clean(api):
    """One ledger row moves the unit, and only the computed read notices.

    The questionnaire re-runs the payoff against today's ledger and reports
    `requires_reissue` true because the unit's `version` has left the
    certificate's `pinned_unit_version` behind, while the stored certificate is
    untouched and still quotes the figures it pinned. The same version gap is
    what makes the closing endpoint refuse.

    PRD 3.9: "A lender questionnaire is available to a `TitleAgent`, a
    `CommunityManager`, or a `BoardTreasurer` as a computed read that re-runs the
    payoff calculation without persisting anything; its payload carries the
    payoff figures, the unit's delinquency posture, `open_violation_count`,
    `special_assessment_disclosure_cents`, and `disclosed_claim_ids`, and a
    certificate whose `pinned_unit_version` no longer equals the unit's current
    `version` is reported with `requires_reissue` true even though the stored row
    is untouched."
    PRD 3.9: "Under `LEDGER_BALANCE`, `ledger_balance_cents` and
    `projected_payoff_cents` are both the unit's `balance_due_cents` and
    `proration_credit_cents` is 0: today's ledger only, with no forward
    projection and no seller credit."
    PRD 3.9: "Three conditions apply: the named certificate's `status` must be
    `ISSUED` and the logical clock must be strictly before its `expires_at`, or
    the response is `ERR_NO_VALID_CERTIFICATE`; the unit's current `version` must
    still equal the certificate's `pinned_unit_version`, because any ledger
    movement since issuance invalidates the payoff the buyer relied on, and a
    mismatch yields `ERR_CERTIFICATE_STALE`; and the incoming owner must exist
    and belong to the same association."
    PRD 3.1: "Posting a charge recomputes the unit's `balance_due_cents`,
    re-derives its `delinquency_stage`, and advances `Unit.version` by 1."

    Design: Corner/endpoints/lender_questionnaire_reports_requires_reissue_after_the_ledger_moves
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_a_single_director(ctx)
    add_owner(ctx, "o2", full_name="Nora Blake", email="nora@example.test")
    add_unit(ctx, "101", "d1", 5_000, heated_sqft=1_100)
    add_unit(ctx, "102", "o2", 5_000, heated_sqft=1_100)

    adopted = adopt_budget(
        ctx,
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    assert adopted["status"] == "ADOPTED"

    certificate = issue_certificate(
        ctx, "101", closing_date="2026-12-01T00:00:00Z"
    )
    assert certificate["status"] == "ISSUED"
    assert_instant_equals(certificate["issued_at"], "2026-09-15T10:00:00Z")
    assert_instant_equals(certificate["expires_at"], "2026-10-15T10:00:00Z")
    assert certificate["ledger_balance_cents"] == 35_000
    assert certificate["projected_payoff_cents"] == 35_000
    assert certificate["proration_credit_cents"] == 0
    assert certificate["requires_reissue"] is False
    pinned_unit_version = certificate["pinned_unit_version"]
    assert pinned_unit_version == ctx.unit_version("101")

    get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="COLLECTION_COST",
                amount_cents=20_000,
                due_on="2026-10-01T00:00:00Z",
                effective_period="2026-09",
                memo="Demand letter",
            ),
            MANAGER_HEADERS,
        )
    )
    moved = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert moved["balance_due_cents"] == 55_000
    assert moved["version"] == pinned_unit_version + 1

    questionnaire = validate_success(
        api.get_lender_questionnaire(certificate["id"], TITLE_AGENT_HEADERS)
    )
    assert questionnaire["requires_reissue"] is True
    assert questionnaire["ledger_balance_cents"] == 55_000
    assert questionnaire["projected_payoff_cents"] == 55_000
    assert questionnaire["proration_credit_cents"] == 0

    stored = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert stored["status"] == "ISSUED"
    assert stored["requires_reissue"] is False
    assert stored["ledger_balance_cents"] == 35_000
    assert stored["pinned_unit_version"] == pinned_unit_version

    validate_error(
        api.transfer_ownership(
            ctx.units["101"],
            {"new_owner_id": ctx.owners["o2"], "certificate_id": certificate["id"]},
            MANAGER_HEADERS,
        ),
        "ERR_CERTIFICATE_STALE",
        409,
    )
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["current_owner_id"]
        == ctx.owners["d1"]
    )


# ======================================================================
# The refund endpoint sits one cent above the cash another endpoint took in
# ======================================================================
def test_a_refund_one_cent_past_collected_cash_is_refused_and_the_exact_cent_clears(api):
    """`collected_cents` minus `refunded_cents` is a ceiling, not a target.

    Two installment rounds charge the whole assessment and one payment collects
    it, so a rescission opens the refund path with exactly 1000000 cents of
    restricted cash behind it. A refund of 1000001 is refused and moves nothing;
    the identical request one cent lower clears the balance to zero.

    PRD 3.4: "It is available only while `funding_status` is `REFUNDING`;
    attempting it otherwise yields `ERR_INVALID_BALLOT_STATE`."
    PRD 3.4: "The requested amount may not exceed `collected_cents` minus
    `refunded_cents`, or the response is `ERR_REFUND_EXCEEDS_COLLECTED`."
    PRD 3.4: "When the posting brings `refunded_cents` up to `collected_cents`,
    `funding_status` moves `REFUNDING → REFUNDED`, the association's
    `restricted_sa_cash_cents` falls by the refunded cents, and
    `Association.version` advances by 1 along with `SpecialAssessment.version`."
    PRD 3.4: "`funding_status` becomes `REFUNDING` when `collected_cents` is
    greater than 0 and becomes `REFUNDED` directly when nothing was ever
    collected; and `SpecialAssessment.version` advances by 1."

    Design: Corner/endpoints/refund_one_cent_past_collected_cash_is_rejected
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_a_single_director(ctx)
    add_owner(
        ctx,
        "tr",
        full_name="Tess Marlow",
        email="tess@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_500)

    assessment = approve_special_assessment(
        ctx,
        total_amount_cents=1_000_000,
        installment_count=2,
        purpose="Garage waterproofing",
        ballots=(("o1", "101", "YES"),),
    )
    assert assessment["approval_status"] == "APPROVED"
    assessment_id = assessment["id"]

    for due_on, period in (
        ("2026-09-01T00:00:00Z", "2026-09"),
        ("2026-10-01T00:00:00Z", "2026-10"),
    ):
        get_success_data(
            api.post_installment(
                assessment_id,
                installment_payload(due_on=due_on, effective_period=period),
                ctx.treasurer(),
            )
        )
    get_success_data(
        api.create_payment(
            ctx.units["101"],
            payment_payload(1_000_000, effective_period="2026-10"),
            ctx.treasurer(),
        )
    )
    collected = read_special_assessment(api, assessment_id, MANAGER_HEADERS)
    assert collected["charged_cents"] == 1_000_000
    assert collected["collected_cents"] == 1_000_000
    assert collected["funding_status"] == "FULLY_COLLECTED"

    get_success_data(
        api.rescind_special_assessment(
            assessment_id, ctx.director("d1"), payload={"reason": "Scope cancelled"}
        )
    )
    refunding = read_special_assessment(api, assessment_id, MANAGER_HEADERS)
    assert refunding["approval_status"] == "RESCINDED"
    assert refunding["funding_status"] == "REFUNDING"
    assert refunding["refunded_cents"] == 0
    assert ctx.association()["restricted_sa_cash_cents"] == 1_000_000

    validate_error(
        api.refund_special_assessment(
            assessment_id,
            refund_payload(ctx.units["101"], 1_000_001, effective_period="2026-11"),
            ctx.treasurer(),
        ),
        "ERR_REFUND_EXCEEDS_COLLECTED",
        409,
    )
    blocked = read_special_assessment(api, assessment_id, MANAGER_HEADERS)
    assert blocked["collected_cents"] == 1_000_000
    assert blocked["refunded_cents"] == 0
    assert blocked["funding_status"] == "REFUNDING"
    assert ctx.association()["restricted_sa_cash_cents"] == 1_000_000
    assert count_entries(ctx.ledger("101"), entry_type="CREDIT_REFUND") == 0

    get_success_data(
        api.refund_special_assessment(
            assessment_id,
            refund_payload(ctx.units["101"], 1_000_000, effective_period="2026-11"),
            ctx.treasurer(),
        )
    )
    settled = read_special_assessment(api, assessment_id, MANAGER_HEADERS)
    assert settled["refunded_cents"] == 1_000_000
    assert settled["funding_status"] == "REFUNDED"
    assert ctx.association()["restricted_sa_cash_cents"] == 0

    credits = [
        row for row in ctx.ledger("101") if row["entry_type"] == "CREDIT_REFUND"
    ]
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == -1_000_000
    assert credits[0]["special_assessment_id"] == assessment_id
    assert credits[0]["bucket"] == "NONE"


# ======================================================================
# A posture derived from the ledger closes a different endpoint
# ======================================================================
def test_a_foreclosure_posture_lets_the_request_through_and_stops_the_issue(api):
    """The request endpoint never looks at delinquency; the issue endpoint does.

    One aged collection cost of 400000 cents puts the unit two rungs down the
    ladder at `FORECLOSURE_REFERRAL`, which is invisible to the certificate
    request and fatal to issuance -- and because issuance never got past its
    conditions, no `RESALE_FEE` row exists.

    PRD 3.1: "Rule 2: if `oldest_unpaid_age_days` is at least 180 and
    `balance_due_cents` is at least twice `lien_threshold_cents`, the posture is
    `FORECLOSURE_REFERRAL`."
    PRD 2.9: "A resale certificate may not be issued for a unit whose
    `delinquency_stage` is `FORECLOSURE_REFERRAL` -- otherwise
    `ERR_CERT_BLOCKED_BY_FORECLOSURE`, on certificate issuance."
    PRD 3.9: "A `TitleAgent` or a `CommunityManager` requests a resale
    certificate for a unit by supplying the `closing_date` used for proration and
    forward projection, an optional `payoff_basis` of `LEDGER_BALANCE` or
    `ESTIMATED_PAYOFF` defaulting to `LEDGER_BALANCE`, the `requesting_agent_id`
    opaque identifier of the closing agent, and the mandatory
    `expected_unit_version`."
    PRD 3.9: "First the `RESALE_FEE` row is posted on the unit for
    `resale_cert_fee_cents`, with its identifier stored in `cert_fee_entry_id`,
    and the unit's `balance_due_cents` and `delinquency_stage` are recomputed
    with `Unit.version` advancing by 1."

    Design: Corner/endpoints/foreclosure_referral_unit_cannot_be_certified_for_closing
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_a_single_director(ctx)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_400)

    adopted = adopt_budget(ctx, attending=("d1",))
    assert adopted["status"] == "ADOPTED"

    get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="COLLECTION_COST",
                amount_cents=400_000,
                due_on="2026-01-01T00:00:00Z",
                effective_period="2026-01",
                memo="Counsel fees",
            ),
            MANAGER_HEADERS,
        )
    )
    delinquent = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert delinquent["balance_due_cents"] == 400_000
    assert delinquent["oldest_unpaid_age_days"] == 252
    assert delinquent["delinquency_stage"] == "FORECLOSURE_REFERRAL"

    certificate = request_certificate(
        ctx, "101", closing_date="2026-11-16T00:00:00Z"
    )
    assert certificate["status"] == "REQUESTED"
    _certs, meta = validate_paginated(
        api.list_resale_certificates(
            MANAGER_HEADERS, params={"unit_id": ctx.units["101"]}
        )
    )
    assert meta["total_count"] == 1

    validate_error(
        api.issue_resale_certificate(certificate["id"], MANAGER_HEADERS),
        "ERR_CERT_BLOCKED_BY_FORECLOSURE",
        409,
    )

    stalled = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert stalled["status"] == "REQUESTED"
    assert stalled["cert_fee_entry_id"] is None
    assert stalled["issued_at"] is None
    rows = ctx.ledger("101")
    assert count_entries(rows, entry_type="RESALE_FEE") == 0
    assert len(rows) == 1
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == (
        400_000
    )


# ======================================================================
# One run endpoint reaching two deadlines that belong to other endpoints
# ======================================================================
def test_one_run_finalizes_the_unappealed_fine_and_expires_the_stale_certificate(api):
    """Two unrelated deadlines, one checkpoint, and no operator action at all.

    The fine's appeal window closed on 2026-10-01T10:00:00Z and the certificate
    expired on 2026-10-15T10:00:00Z; the run executed on 2026-11-01 is strictly
    past the first and past the second, so it finalizes the fine without
    touching the fine row and expires the certificate while re-blocking the
    unit's transfer -- on top of posting the period's two assessment charges.

    PRD 3.5: "Fourth, the run finalizes unappealed fines: every violation case
    whose `status` is `FINE_ASSESSED` and whose `appeal_deadline_at` the logical
    clock has strictly passed advances `FINE_ASSESSED → FINE_UPHELD`, the run's
    `fines_finalized_count` rises by 1 for each, and each case's own `version`
    advances by 1."
    PRD 3.5: "The fine row itself is untouched; the money was already owed."
    PRD 3.5: "Sixth and last, the run sweeps stale resale certificates: every
    certificate whose `status` is `ISSUED` and whose `expires_at` the logical
    clock has reached or passed moves `ISSUED → EXPIRED`, the unit's
    `transfer_blocked` is set back to true with `Unit.version` advancing by 1,
    and the certificate's own `version` advances by 1."
    PRD 3.5: "First, one `ASSESSMENT` row per unit is posted from the budget's
    `allocation_snapshot`, each carrying that unit's `monthly_cents` as its
    positive `amount_cents`, the run's `due_on` as its `due_on`, the run's
    `period` as its `effective_period`, and the run's identifier as its
    `billing_run_id`; the run reports `assessment_charged_cents` as the sum of
    those amounts, `charged_unit_count` as the number of units that received at
    least one charge in this run, and `remainder_cents_allocated` as the absolute
    rounding drift the allocator reconciled."
    PRD 3.5: "On completion `executed_at` is stamped from the logical clock."

    Design: Corner/endpoints/billing_run_sweeps_finalize_the_fine_and_expire_the_stale_certificate
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_a_single_director(ctx)
    add_owner(
        ctx,
        "d2",
        full_name="Rita Vance",
        email="rita@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 5_000, heated_sqft=1_100)
    add_unit(ctx, "102", "o1", 5_000, heated_sqft=1_100)

    schedule_meeting(
        ctx, "mtg_h", ["HEARING"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )
    budget_meeting_id = schedule_meeting(
        ctx,
        "mtg_b",
        ["BUDGET_RATIFICATION"],
        "2026-09-15T10:00:00Z",
        "2026-09-15T12:00:00Z",
    )
    budget = draft_budget(ctx)
    get_success_data(
        api.propose_budget(
            budget["id"],
            MANAGER_HEADERS,
            payload={"ratification_meeting_id": budget_meeting_id},
        )
    )
    get_success_data(api.send_budget_notice(budget["id"], MANAGER_HEADERS))

    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d2"
    )
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg_h", "2026-09-01T10:00:00Z")
    notice_meeting(ctx, "mtg_h")

    set_clock(api, "2026-09-01T10:00:00Z")
    convene(ctx, "mtg_h", attending=("d1",))
    fined = get_success_data(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1"))
    )
    assert fined["status"] == "FINE_ASSESSED"
    assert fined["fine_tier"] == 1
    assert fined["fine_amount_cents"] == 5_000
    assert_instant_equals(fined["appeal_deadline_at"], "2026-10-01T10:00:00Z")
    fine_entry_id = fined["fine_entry_id"]

    set_clock(api, "2026-09-15T10:00:00Z")
    convene(ctx, "mtg_b", attending=("d1",))
    adopted = get_success_data(api.ratify_budget(budget["id"], ctx.director("d1")))
    assert adopted["status"] == "ADOPTED"

    certificate = issue_certificate(
        ctx, "101", closing_date="2026-12-01T00:00:00Z"
    )
    assert certificate["status"] == "ISSUED"
    assert_instant_equals(certificate["expires_at"], "2026-10-15T10:00:00Z")

    set_clock(api, "2026-11-01T00:00:00Z")
    run = validate_success(
        api.create_billing_run(
            ctx.association_id,
            billing_run_payload(
                budget["id"], period="2026-11", due_on="2026-11-01T00:00:00Z"
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert_instant_equals(run["executed_at"], "2026-11-01T00:00:00Z")
    assert run["assessment_charged_cents"] == 1_100_000
    assert run["charged_unit_count"] == 2
    assert run["remainder_cents_allocated"] == 0
    assert run["late_fees_charged_cents"] == 0
    assert run["fines_finalized_count"] == 1

    upheld = read_case(api, case["id"], MANAGER_HEADERS)
    assert upheld["status"] == "FINE_UPHELD"
    assert upheld["fine_amount_cents"] == 5_000
    assert upheld["fine_entry_id"] == fine_entry_id

    expired = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert expired["status"] == "EXPIRED"
    assert_instant_equals(expired["expires_at"], "2026-10-15T10:00:00Z")
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["transfer_blocked"] is True

    run_id = read_billing_run(api, run["id"], MANAGER_HEADERS)["id"]
    for unit_label in ("101", "102"):
        rows = ctx.ledger(unit_label)
        assessments = [
            row
            for row in rows
            if row["entry_type"] == "ASSESSMENT" and row["billing_run_id"] == run_id
        ]
        assert len(assessments) == 1
        assert assessments[0]["amount_cents"] == 550_000
        assert assessments[0]["effective_period"] == "2026-11"
        assert_instant_equals(assessments[0]["due_on"], "2026-11-01T00:00:00Z")

    fine_rows = [row for row in ctx.ledger("101") if row["entry_type"] == "FINE"]
    assert len(fine_rows) == 1
    assert fine_rows[0]["status"] == "POSTED"
    assert fine_rows[0]["amount_cents"] == 5_000
