"""Authorization breadth probes: the same request, refused and then allowed.

Every test drives one capability twice from two identities that differ only in
role or in prior participation. The refusal must leave no trace, and the paired
call from the correct identity must succeed with its full side effects -- which
is what separates a genuine role boundary from a broken endpoint.
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
    fetch_ledger_entries,
    find_entry,
    read_budget,
    read_case,
    read_certificate,
    read_claim,
    read_contract,
    read_element,
    read_special_assessment,
    read_unit,
)
from test_helpers.factories import (
    charge_payload,
    insurance_claim_payload,
    payment_payload,
    resale_certificate_payload,
    special_assessment_payload,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    adjust_claim,
    adopt_budget,
    board_vote_yes,
    convene,
    create_association,
    docket_hearing,
    draft_budget,
    issue_certificate,
    notice_meeting,
    notice_violation_case,
    report_claim,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import (
    ADJUSTER_HEADERS,
    ATTORNEY_HEADERS,
    MANAGER_HEADERS,
    TITLE_AGENT_HEADERS,
)

HARBOR_POINT = "Harbor Point Condominium Association"


def _seat_director(ctx, label, full_name, email, board_role="DIRECTOR"):
    add_owner(
        ctx,
        label,
        full_name=full_name,
        email=email,
        board_role=board_role,
        is_seated=True,
    )


def _seat_treasurer(ctx):
    _seat_director(ctx, "tr", "Tina Cole", "tina@example.test", board_role="TREASURER")


def _owner_and_unit(api, **overrides):
    """One association, one owner of record, one unit holding the whole interest."""
    ctx = create_association(api, legal_name=HARBOR_POINT, **overrides)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_000)
    return ctx


# ======================================================================
# Manager versus board
# ======================================================================
def test_the_manager_who_proposed_the_budget_may_not_ratify_it(api):
    """The manager drives the whole budget pipeline up to the vote, and no further.

    Everything the ratification rungs ask for is in place -- the budget is
    `NOTICED`, the meeting is `IN_SESSION` and quorate, and the notice period has
    elapsed -- so the only defect is the caller's role. The refused call must not
    mint per-unit assessments, and the same call from the seated director then
    adopts the budget and allocates the whole 1100000-cent monthly pool to the
    single unit.

    PRD 2.1: "If both headers are present and well formed but the named role is
    not among the roles authorized for the target endpoint, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 4: "| `POST` | `/budgets/{budget_id}/ratify` | Tally owner veto ballots at
    the ratification meeting; adopts or rejects. | `BoardDirector` |"
    PRD 4: "| `POST` | `/budgets/{budget_id}/send-notice` | Mail the statutory
    ratification notice. | `CommunityManager` |"
    PRD 3.1: "A newly created unit is fiscally blank: `monthly_assessment_cents`
    is 0 and stays 0 until a budget adoption allocates to it,
    `balance_due_cents` is 0, `credit_balance_cents` is 0,
    `oldest_unpaid_age_days` is 0, `delinquency_stage` is `CURRENT`,
    `voting_eligible` is true, `lien_recorded_at` is null, and
    `transfer_blocked` is true."

    Design: Corner/rbac/community_manager_cannot_ratify_the_budget_they_proposed
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    meeting_id = schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION"],
        "2026-09-15T10:00:00Z",
        "2026-09-15T12:00:00Z",
    )
    budget = draft_budget(ctx, ratification_meeting_id=meeting_id)
    get_success_data(api.propose_budget(budget["id"], MANAGER_HEADERS))
    get_success_data(api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    set_clock(api, "2026-09-15T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))

    error = validate_error(
        api.ratify_budget(budget["id"], MANAGER_HEADERS),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    assert error["error_id"] == "ERR_ROLE_NOT_PERMITTED"

    unratified = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert unratified["status"] == "NOTICED"
    assert unratified["adopted_at"] is None
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)[
        "monthly_assessment_cents"
    ] == 0

    adopted = validate_success(
        api.ratify_budget(budget["id"], ctx.director("d1")), 200
    )
    assert adopted["status"] == "ADOPTED"
    assert adopted["monthly_assessable_cents"] == 1_100_000
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)[
        "monthly_assessment_cents"
    ] == 1_100_000


def test_a_seated_director_may_not_reverse_a_ledger_row(api):
    """Corrections are the treasurer's exclusive province, not the board's.

    The director who may award contracts and decide hearings is refused on the
    reversal endpoint, and the charge stays `POSTED` with the balance unmoved;
    the treasurer's identical call posts the compensating row and clears the
    unit.

    PRD 4: "| `POST` | `/ledger-entries/{ledger_entry_id}/reverse` | Post a
    compensating REVERSAL entry against a charge, preserving INVARIANT L. |
    `BoardTreasurer` |"
    PRD 2.9: "2. The acting role appears in the target endpoint's authorized role
    list -- otherwise `ERR_ROLE_NOT_PERMITTED`, on every endpoint."
    PRD 3.1: "A successful reversal creates a `REVERSAL` row whose
    `reverses_entry_id` names the original and whose `amount_cents` is the exact
    negation of the original's, flips the original's `status` to `REVERSED`,
    recomputes the unit's `balance_due_cents`, re-derives its
    `delinquency_stage`, and advances `Unit.version` by 1."

    Design: Corner/rbac/board_director_cannot_reverse_a_ledger_entry
    """
    ctx = _owner_and_unit(api)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    _seat_treasurer(ctx)
    charge = get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=20_000,
                due_on="2026-08-15T00:00:00Z",
                effective_period="2026-08",
                memo="August assessment",
            ),
            MANAGER_HEADERS,
        )
    )

    validate_error(
        api.reverse_ledger_entry(
            charge["id"],
            ctx.director("d1"),
            payload={"memo": "director-initiated reversal"},
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 1
    rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units["101"])
    assert rows[0]["status"] == "POSTED"
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 20_000
    )

    reversal = validate_success(
        api.reverse_ledger_entry(
            charge["id"], ctx.treasurer(), payload={"memo": "billed in error"}
        ),
        201,
    )
    assert reversal["amount_cents"] == -20_000
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 0


def test_the_treasurer_may_not_record_the_board_award(api):
    """Money authority and award authority are separated between peers.

    The award vote is in the register and the element is serviceable, so the
    treasurer's call fails on role alone; nothing may be pinned by a refused
    award, and the director's identical call pins the element version the board
    relied on.

    PRD 4: "| `POST` | `/vendor-contracts/{vendor_contract_id}/approve` | Record
    the board award; pins the element version the award was based on. |
    `BoardDirector` |"
    PRD 3.6: "Recording the board award moves the contract `PENDING_APPROVAL →
    APPROVED` and is a `BoardDirector` act."
    PRD 3.6: "On success the server writes `approval_yes_count`, **pins**
    `pinned_element_version` to the element's `version` at that instant, and
    advances `VendorContract.version` by 1."
    PRD 3.6: "`approval_yes_count` starts at 0, `pinned_element_version` is null
    until the board awards, and `suspension_reason` is an enum over `NONE`,
    `INSURANCE_LAPSED`, `PERFORMANCE`, and `ELEMENT_SPEC_CHANGED` defaulting to
    `NONE`."

    Design: Corner/rbac/board_treasurer_cannot_approve_a_vendor_contract
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    _seat_treasurer(ctx)
    element_id = add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    contract_id = add_contract(
        ctx,
        "ct1",
        "el1",
        vendor_name="Ridgeline Roofing",
        contract_cap_cents=1_000_000,
        # The certificate must sit at or after effective_to so it covers the
        # whole term, or submission is refused with ERR_CONTRACT_TERM_INVALID.
        insurance_cert_expires_at="2027-08-31T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-08-31T00:00:00Z",
    )
    get_success_data(api.submit_contract(contract_id, MANAGER_HEADERS))
    schedule_meeting(
        ctx, "mtg1", ["CONTRACT_AWARD"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-08-20T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1",))
    board_vote_yes(
        ctx, "VENDOR_CONTRACT", contract_id, "mtg1", voters=(("d1", "101"),)
    )

    validate_error(
        api.approve_contract(contract_id, ctx.treasurer()),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unawarded = read_contract(api, contract_id, MANAGER_HEADERS)
    assert unawarded["status"] == "PENDING_APPROVAL"
    assert unawarded["pinned_element_version"] is None
    # Casting the award vote already recomputed the tally (PRD 3.5: "When
    # `subject_type` is `VENDOR_CONTRACT`, casting also recomputes that
    # contract's `approval_yes_count`"), and the refused award leaves it alone.
    assert unawarded["approval_yes_count"] == 1

    element_version = read_element(api, element_id, MANAGER_HEADERS)["version"]
    awarded = validate_success(
        api.approve_contract(contract_id, ctx.director("d1")), 200
    )
    assert awarded["status"] == "APPROVED"
    assert awarded["pinned_element_version"] == element_version
    assert awarded["approval_yes_count"] == 1


# ======================================================================
# External parties
# ======================================================================
def test_the_title_agent_may_request_a_certificate_but_not_charge_the_ledger(api):
    """The agent's single write is the certificate request, and nothing else.

    A refused charge must not touch the unit at all -- no row, no version bump --
    which the very next call proves by spending that same unmoved version as the
    optimistic-concurrency token on a certificate request the agent *is*
    authorized to make.

    PRD 4: "| `POST` | `/units/{unit_id}/charges` | Post a manual charge
    (collection cost, interest, or a corrective assessment) to a unit ledger. |
    `CommunityManager`, `BoardTreasurer` |"
    PRD 4: "| `POST` | `/units/{unit_id}/resale-certificates` | Title agent
    requests a resale certificate; supersedes any other REQUESTED certificate for
    the unit. | `TitleAgent`, `CommunityManager` |"
    PRD 2.6: "A mismatch against the unit's current `version` is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD 3.9: "The certificate is born with `status` `REQUESTED` and with
    `ledger_balance_cents`, `projected_payoff_cents`, `proration_credit_cents`,
    `open_violation_count`, and `special_assessment_disclosure_cents` at 0,
    `disclosed_claim_ids` empty, `requires_reissue` false, and
    `pinned_budget_id`, `pinned_unit_version`, `pinned_budget_version`,
    `cert_fee_entry_id`, `issued_at`, and `expires_at` all null."

    Design: Corner/rbac/title_agent_holds_no_write_authority_over_the_unit_ledger
    """
    ctx = _owner_and_unit(api)
    version_before = ctx.unit_version("101")

    validate_error(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="COLLECTION_COST",
                amount_cents=5_000,
                due_on="2026-08-15T00:00:00Z",
                effective_period="2026-08",
                memo="title search fee",
            ),
            TITLE_AGENT_HEADERS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 0
    assert ctx.unit_version("101") == version_before

    requested = validate_success(
        api.request_resale_certificate(
            ctx.units["101"],
            resale_certificate_payload(
                "TA-0001", version_before, closing_date="2026-11-16T00:00:00Z"
            ),
            TITLE_AGENT_HEADERS,
        ),
        201,
    )
    assert requested["status"] == "REQUESTED"
    assert requested["issued_at"] is None
    assert requested["requires_reissue"] is False


def test_the_adjuster_may_not_open_the_claim_they_will_adjust(api):
    """Intake and adjudication are held by different peers, so no self-authored claim exists.

    The adjuster owns assign-adjuster, adjust and settle but cannot report the
    loss; the refusal leaves the claim register empty, and the identical body from
    the manager creates the `REPORTED` claim the adjuster may then take under
    review.

    PRD 4: "| `POST` | `/insurance-claims` | Report a loss under the master
    policy. | `CommunityManager` |"
    PRD 4: "| `POST` | `/insurance-claims/{insurance_claim_id}/assign-adjuster` |
    Take a reported or appealed claim under review. | `InsuranceAdjuster` |"
    PRD 3.7: "From `REPORTED → UNDER_REVIEW` the requirements are that
    `adjustment_status` be `REPORTED` or `APPEALED` and that at least one of
    `unit_id` or `element_id` be set; the side effects are that
    `common_element_damage_cents` is computed as `gross_damage_cents` minus
    `within_unit_boundary_cents` and `InsuranceClaim.version` advances by 1."

    Design: Corner/rbac/insurance_adjuster_cannot_open_the_claim_they_will_adjust
    """
    ctx = _owner_and_unit(api)
    element_id = add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    payload = insurance_claim_payload(
        ctx.association_id,
        ctx.units["101"],
        element_id,
        loss_type="WIND",
        loss_at="2026-07-20T00:00:00Z",
        gross_damage_cents=30_000_000,
        within_unit_boundary_cents=0,
    )

    validate_error(
        api.create_insurance_claim(payload, ADJUSTER_HEADERS),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    _claims, meta = validate_paginated(
        api.list_insurance_claims(
            MANAGER_HEADERS, params={"association_id": ctx.association_id}
        )
    )
    assert meta["total_count"] == 0

    reported = validate_success(
        api.create_insurance_claim(payload, MANAGER_HEADERS), 201
    )
    assert reported["adjustment_status"] == "REPORTED"
    reviewed = validate_success(
        api.assign_adjuster(reported["id"], ADJUSTER_HEADERS), 200
    )
    assert reviewed["adjustment_status"] == "UNDER_REVIEW"
    assert reviewed["common_element_damage_cents"] == 30_000_000


def test_only_the_attorney_may_tender_and_the_tender_voids_the_certificate(api):
    """The litigation dimension is attorney-exclusive, and it reaches into resale.

    The manager who reported the loss cannot move the litigation dimension at
    all, so the issued certificate stays good; when the attorney tenders, the
    cascade runs sideways into the resale pipeline -- `disclosure_required` flips
    true, the `ISSUED` certificate is voided for reissue, and its 35000-cent fee
    is answered with a `REVERSAL` that returns the unit to a zero balance.

    PRD 4: "| `POST` |
    `/insurance-claims/{insurance_claim_id}/litigation-stage` | Advance the
    independent litigation dimension for a construction-defect matter. |
    `AssociationAttorney` |"
    PRD 3.7: "The litigation dimension is driven exclusively by the
    `AssociationAttorney` through a capability that takes a `stage` selector."
    PRD 3.7: "It sets `disclosure_required` to true and then cascades: every
    resale certificate whose `status` is `ISSUED` and whose `unit_id` appears in
    `affected_unit_ids` becomes `VOIDED` with `requires_reissue` set to true,
    because an already-issued certificate cannot disclose a matter tendered after
    it was printed; each such certificate's `cert_fee_entry_id` is answered with a
    `REVERSAL` row, and the affected unit's `balance_due_cents` and
    `delinquency_stage` are recomputed with `Unit.version` advancing by 1."
    PRD 3.7: "`disclosure_required` is true exactly when `litigation_status` is
    `TENDERED` or `IN_LITIGATION`."

    Design: Corner/rbac/only_the_attorney_may_tender_the_claim_and_the_tender_voids_certificates
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    add_element(
        ctx,
        "el1",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=12_000_000,
        useful_life_years=40,
        effective_age_years=5,
    )
    adopt_budget(
        ctx,
        meeting_start="2026-09-15T10:00:00Z",
        meeting_end="2026-09-15T12:00:00Z",
        attending=("d1",),
    )
    certificate = issue_certificate(
        ctx, "101", closing_date="2026-10-05T00:00:00Z"
    )
    assert certificate["status"] == "ISSUED"
    fee_entry_id = certificate["cert_fee_entry_id"]
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 35_000
    )
    claim = report_claim(
        ctx,
        "101",
        "el1",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-06-01T00:00:00Z",
        gross_damage_cents=30_000_000,
        within_unit_boundary_cents=0,
    )
    adjust_claim(ctx, claim["id"], responsibility="DENY")

    validate_error(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, MANAGER_HEADERS),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    untendered = read_claim(api, claim["id"], MANAGER_HEADERS)
    assert untendered["litigation_status"] == "NONE"
    assert untendered["disclosure_required"] is False
    assert (
        read_certificate(api, certificate["id"], MANAGER_HEADERS)["status"] == "ISSUED"
    )

    tendered = validate_success(
        api.set_litigation_stage(claim["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS),
        200,
    )
    assert tendered["litigation_status"] == "TENDERED"
    assert tendered["disclosure_required"] is True

    voided = read_certificate(api, certificate["id"], MANAGER_HEADERS)
    assert voided["status"] == "VOIDED"
    assert voided["requires_reissue"] is True

    rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units["101"])
    fee_row = find_entry(rows, id=fee_entry_id)
    assert fee_row["status"] == "REVERSED"
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert reversal["amount_cents"] == -35_000
    assert reversal["reverses_entry_id"] == fee_entry_id
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 0


# ======================================================================
# Segregation of duties
# ======================================================================
def test_the_reporting_director_may_not_decide_their_own_hearing(api):
    """Both directors attend, so only the actor's identity distinguishes the calls.

    Quorum is met and the case is properly docketed, so the reporter's decision
    fails on segregation of duties alone -- no fine row, no decider recorded --
    while the other attending director's identical call assesses the tier-1 fine.

    PRD 2.1: "Segregation-of-duties violations -- a director recording a hearing
    decision on a violation they reported, a director reviewing their own earlier
    decision on an appeal round, or the manager who proposed a budget casting a
    ballot on it -- are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.8: "Every decision requires that the case be `HEARING_SCHEDULED`, that
    the hearing meeting's `status` be `IN_SESSION` with its `quorum_met` true --
    otherwise `ERR_MEETING_NOT_IN_SESSION` or `ERR_BOARD_QUORUM_NOT_MET` -- and
    that the acting director not be the reporter: the `X-User-ID` must differ
    from `reported_by_owner_id`, or the response is
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "`fine_tier` is 1 when the qualifying chain is empty, 2 when it
    holds exactly one link, and 3 when it holds two or more."
    PRD 2.9: "15. Segregation of duties, as described in §2.1 -- otherwise
    `ERR_SEGREGATION_OF_DUTIES`, on hearing decision recording and on vote
    casting."

    Design: Corner/rbac/the_reporting_director_cannot_decide_their_own_hearing
    """
    ctx = _owner_and_unit(api, board_quorum_seats=2)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    _seat_director(ctx, "d2", "Rita Vance", "rita@example.test")
    schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )
    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="d2"
    )
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg1", "2026-09-01T10:00:00Z")
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-09-01T10:00:00Z")
    convened = convene(ctx, "mtg1", attending=("d1", "d2"))
    assert convened["quorum_met"] is True

    validate_error(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d2")),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    undecided = read_case(api, case["id"], MANAGER_HEADERS)
    assert undecided["status"] == "HEARING_SCHEDULED"
    assert undecided["decision_owner_id"] is None
    assert undecided["fine_amount_cents"] == 0
    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"source_case_id": case["id"]})
    )
    assert meta["total_count"] == 0

    fined = validate_success(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1")), 200
    )
    assert fined["status"] == "FINE_ASSESSED"
    assert fined["fine_tier"] == 1
    assert fined["fine_amount_cents"] == 5_000
    assert fined["decision_owner_id"] == ctx.owners["d1"]


def test_the_round_one_decider_may_not_decide_the_appeal_round(api):
    """Segregation of duties has a second, memory-bearing limb on appeal.

    The round-1 decider is not the reporter and attends a quorate second meeting,
    yet the case remembers `decision_owner_id` and disqualifies him from
    reviewing his own decision; a third seated officer may vacate, and the
    vacatur reverses the fine row so the unit returns to exactly its pre-fine
    balance.

    PRD 3.8: "`VACATE`, legal only when `hearing_round` is 2 or greater and
    subject to the same self-review prohibition, moves the case to `FINE_VACATED`
    and is the compensating action for the fine assessment: the unit ledger must
    return to exactly its pre-fine value."
    PRD 3.8: "`UPHOLD`, legal only when `hearing_round` is 2 or greater, moves the
    case to `FINE_UPHELD`."
    PRD 3.8: "It additionally requires that the acting `X-User-ID` differ from
    `decision_owner_id`, because no director may review their own decision; a
    self-review is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "The side effects release the docket slot: the former hearing
    meeting's `hearing_slot_count` falls by 1 with that `BoardMeeting.version`
    advancing by 1, `hearing_meeting_id` and `hearing_slot_start` are cleared to
    null, the `FINE` row stays `POSTED` so the fine remains owed throughout the
    appeal, and `ViolationCase.version` advances by 1."
    PRD 3.8: "First, a `REVERSAL` row is posted whose `reverses_entry_id` is
    `fine_entry_id` and whose `amount_cents` is the negation of
    `fine_amount_cents`, and the original `FINE` row's `status` becomes
    `REVERSED`."

    Design: Corner/rbac/the_round_one_decider_cannot_decide_the_appeal_round
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=2)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(ctx, "o2", full_name="Nora Bell", email="nora@example.test")
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    _seat_director(ctx, "d2", "Rita Vance", "rita@example.test")
    _seat_director(ctx, "d3", "Sam Ruiz", "sam@example.test", board_role="PRESIDENT")
    add_unit(ctx, "101", "o1", 5_000, heated_sqft=1_000)
    add_unit(ctx, "102", "o2", 5_000, heated_sqft=1_000)
    schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
    )
    schedule_meeting(
        ctx, "mtg2", ["HEARING"], "2026-09-20T10:00:00Z", "2026-09-20T12:00:00Z"
    )
    case = notice_violation_case(
        ctx, "101", rule_code="R-14-PETS", reporter_label="o2"
    )
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, case["id"], "mtg1", "2026-09-01T10:00:00Z")
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-09-01T10:00:00Z")
    convene(ctx, "mtg1", attending=("d1", "d2", "d3"))
    fined = get_success_data(
        api.hearing_decision(case["id"], {"outcome": "FINE"}, ctx.director("d1"))
    )
    fine_entry_id = fined["fine_entry_id"]
    get_success_data(
        api.appeal_case(
            case["id"],
            ctx.owner("o1"),
            payload={"grounds": "the dog is a service animal"},
        )
    )
    docket_hearing(ctx, case["id"], "mtg2", "2026-09-20T10:00:00Z", decider_label="d2")
    notice_meeting(ctx, "mtg2")
    set_clock(api, "2026-09-20T10:00:00Z")
    convene(ctx, "mtg2", attending=("d1", "d2", "d3"))

    validate_error(
        api.hearing_decision(case["id"], {"outcome": "VACATE"}, ctx.director("d1")),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    still_docketed = read_case(api, case["id"], MANAGER_HEADERS)
    assert still_docketed["status"] == "HEARING_SCHEDULED"
    assert still_docketed["hearing_round"] == 2
    assert still_docketed["decision_owner_id"] == ctx.owners["d1"]
    fine_row = find_entry(
        fetch_ledger_entries(api, MANAGER_HEADERS, source_case_id=case["id"]),
        entry_type="FINE",
    )
    assert fine_row["status"] == "POSTED"
    assert fine_row["amount_cents"] == 5_000
    assert (
        read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 5_000
    )

    vacated = validate_success(
        api.hearing_decision(case["id"], {"outcome": "VACATE"}, ctx.director("d3")), 200
    )
    assert vacated["status"] == "FINE_VACATED"
    rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units["101"])
    reversal = find_entry(rows, entry_type="REVERSAL")
    assert reversal["amount_cents"] == -5_000
    assert reversal["reverses_entry_id"] == fine_entry_id
    assert find_entry(rows, id=fine_entry_id)["status"] == "REVERSED"
    assert read_unit(api, ctx.units["101"], MANAGER_HEADERS)["balance_due_cents"] == 0


# ======================================================================
# Owner and peer-role splits
# ======================================================================
def test_the_owner_may_pay_their_unit_but_may_not_charge_it(api):
    """The split is per-endpoint, not per-unit-ownership.

    The same owner identity is authorized on payments and unauthorized on
    charges: the payment clears the 20000-cent assessment through the waterfall,
    and the self-charge for a single cent is refused, leaving exactly two rows on
    the unit.

    PRD 4: "| `POST` | `/units/{unit_id}/payments` | Record an owner payment and
    run the application waterfall. | `CommunityManager`, `BoardTreasurer`,
    `UnitOwner` |"
    PRD 4: "| `POST` | `/units/{unit_id}/charges` | Post a manual charge
    (collection cost, interest, or a corrective assessment) to a unit ledger. |
    `CommunityManager`, `BoardTreasurer` |"
    PRD 3.1: "Rule 1: if `balance_due_cents` is less than or equal to 0, the
    posture is `CURRENT`."
    PRD 3.1: "`balance_due_cents` is the signed sum of `amount_cents` over
    *every* ledger row of the unit, regardless of `status` -- a reversed pair nets
    to zero, so nothing is double counted."

    Design: Corner/rbac/unit_owner_may_pay_but_may_not_charge_their_own_ledger
    """
    ctx = _owner_and_unit(api)
    get_success_data(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=20_000,
                due_on="2026-08-15T00:00:00Z",
                effective_period="2026-08",
                memo="August assessment",
            ),
            MANAGER_HEADERS,
        )
    )
    validate_success(
        api.create_payment(
            ctx.units["101"],
            payment_payload(20_000, effective_period="2026-08", memo="owner payment"),
            ctx.owner("o1"),
        ),
        201,
    )
    paid = find_entry(
        fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=ctx.units["101"]),
        entry_type="PAYMENT",
    )
    assert paid["amount_cents"] == -20_000

    validate_error(
        api.create_charge(
            ctx.units["101"],
            charge_payload(
                entry_type="ASSESSMENT",
                amount_cents=1,
                due_on="2026-09-15T00:00:00Z",
                effective_period="2026-09",
                memo="self-charge",
            ),
            ctx.owner("o1"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    settled = read_unit(api, ctx.units["101"], MANAGER_HEADERS)
    assert settled["balance_due_cents"] == 0
    assert settled["delinquency_stage"] == "CURRENT"
    _rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 2


def test_drafting_an_assessment_and_opening_its_ballot_need_two_different_peers(api):
    """Neither board officer can drive the instrument alone.

    The treasurer authors the assessment but is refused on open-ballot, and the
    director who may open it is refused on authorship -- the mirror refusal
    leaves the register at one row -- after which the director's open stamps
    `ballot_opened_at` from the logical clock.

    PRD 4: "| `POST` | `/associations/{association_id}/special-assessments` |
    Draft a special assessment, optionally funding a tendered construction-defect
    matter. | `BoardTreasurer` |"
    PRD 4: "| `POST` |
    `/special-assessments/{special_assessment_id}/open-ballot` | Open owner
    balloting. | `BoardDirector` |"
    PRD 3.4: "Opening balloting moves `approval_status` from `DRAFT` to
    `BALLOTING` and is a `BoardDirector` act."
    PRD 3.4: "On success `ballot_opened_at` is stamped from the logical clock,
    `requires_supermajority_disclosure` is set to true exactly when
    `funding_claim_id` is present (and to false otherwise), forcing litigation
    disclosure on every certificate issued after approval, and
    `SpecialAssessment.version` advances by 1."

    Design: Corner/rbac/assessment_authorship_and_balloting_authority_sit_in_different_hands
    """
    ctx = _owner_and_unit(api, board_quorum_seats=1)
    _seat_director(ctx, "d1", "Dana Reed", "dana@example.test")
    _seat_treasurer(ctx)
    assessment = get_success_data(
        api.create_special_assessment(
            ctx.association_id,
            special_assessment_payload(
                ctx.association_version(),
                purpose="Roof replacement",
                total_amount_cents=4_000_000,
                installment_count=4,
            ),
            ctx.treasurer(),
        )
    )

    validate_error(
        api.open_ballot(assessment["id"], ctx.treasurer()),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    assert (
        read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
            "approval_status"
        ]
        == "DRAFT"
    )

    validate_error(
        api.create_special_assessment(
            ctx.association_id,
            special_assessment_payload(
                ctx.association_version(),
                purpose="Garage waterproofing",
                total_amount_cents=2_000_000,
                installment_count=2,
            ),
            ctx.director("d1"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    _rows, meta = validate_paginated(
        api.list_special_assessments(
            MANAGER_HEADERS, params={"association_id": ctx.association_id}
        )
    )
    assert meta["total_count"] == 1

    balloting = validate_success(
        api.open_ballot(assessment["id"], ctx.director("d1")), 200
    )
    assert balloting["approval_status"] == "BALLOTING"
    assert_instant_equals(balloting["ballot_opened_at"], "2026-08-01T00:00:00Z")
    assert balloting["requires_supermajority_disclosure"] is False
