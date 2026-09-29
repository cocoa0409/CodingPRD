"""Declared lifecycles: initial states, the happy walk, undeclared actions,
terminal states, replayed actions and the conditional cascades a transition
fires at its children.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    FARM_DIRECTOR_USER_ID,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_integer,
    assert_money,
    assert_status,
    factories,
    fixtures,
    make_affiliate_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dispose_agreement(api: ApiClient, agreement_id: str, action: str, headers=None, **fields):
    """Raw agreement disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_agreement(
        agreement_id,
        factories.disposition_payload(action, **fields),
        headers or COMPLIANCE_OFFICER_HEADERS,
    )


def _dispose_plan(api: ApiClient, plan_id: str, action: str, **fields):
    """Raw plan disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_development_plan(
        plan_id, factories.disposition_payload(action, **fields), FARM_DIRECTOR_HEADERS
    )


def _draft_without_a_staffing_floor(api: ApiClient, affiliate_id: str) -> dict:
    """Draft a licence that leaves `minimum_active_players` to its default."""
    payload = factories.agreement_payload()
    payload.pop("minimum_active_players")
    return validate_success(
        api.create_agreement(affiliate_id, payload, COMPLIANCE_OFFICER_HEADERS), 201
    )


def test_a_fresh_licence_and_a_fresh_clearance_sit_in_their_declared_initial_states(api: ApiClient):
    """Two creates, two declared initial states, no derived work done yet.

    PRD 3.2: "A newly drafted licence sits in status `DRAFT` with `posture`
    `FROZEN`, `provisional_club_obligation_cents` and `affiliate_overflow_cents`
    at 0, `final_club_obligation_cents` null, `settlement_status` `NOT_SETTLED`,
    and `submitted_by_user_id` null."  PRD 3.5 pins the medical side just as
    tightly: "A new request is persisted in status `REQUESTED` with
    `requested_by_user_id` taken from the acting `X-User-ID`, and
    `issued_by_user_id`, `cleared_workload_ceiling_index`, `expires_on` and
    `restriction_note` all null."  Opening the medical loop is not itself a
    medical verdict, so the player keeps the standing PRD 3.5 gives them at
    registration: "On registration, `roster_status` is `RESERVE_LIST` and
    `medical_status` is `PENDING_CLEARANCE`; `option_years_used` is 0 and
    `option_years_remaining` is 3; `workload_index` and
    `workload_index_projected` are both `0.00`; `promotion_readiness` is
    `0.0000`; and `current_affiliate_id` is null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    affiliate = fixtures.create_affiliate(
        api,
        name="Initial State Club",
        level="DOUBLE_A",
        market_city="Birmingham",
        meal_stipend_cents_per_day=3000,
    )
    agreement = fixtures.create_agreement(api, affiliate["id"])

    assert_status(agreement, "DRAFT", "AffiliationAgreement")
    assert agreement["posture"] == "FROZEN", (
        f"a draft licence is FROZEN before certification, got {agreement['posture']}"
    )
    assert_money(
        agreement["provisional_club_obligation_cents"], 0, "provisional_club_obligation_cents"
    )
    assert_money(agreement["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert agreement["final_club_obligation_cents"] is None, (
        f"the final obligation waits for settlement, got {agreement['final_club_obligation_cents']!r}"
    )
    assert agreement["settlement_status"] == "NOT_SETTLED", (
        f"a draft licence is NOT_SETTLED, got {agreement['settlement_status']!r}"
    )
    assert agreement["submitted_by_user_id"] is None, (
        f"nobody has submitted the draft yet, got {agreement['submitted_by_user_id']!r}"
    )
    assert agreement["affiliate_id"] == affiliate["id"], (
        f"the draft records its club, got {agreement['affiliate_id']!r}"
    )

    player = fixtures.create_player(
        api, full_name="Initial State Player", origin="DOMESTIC_DRAFT", signed_date="2025-06-10"
    )
    clearance = fixtures.request_clearance(api, player["id"], "LEVEL_ASSIGNMENT")

    assert_status(clearance, "REQUESTED", "MedicalClearance")
    assert clearance["requested_by_user_id"] == FARM_DIRECTOR_USER_ID, (
        f"the requester is stamped from X-User-ID, got {clearance['requested_by_user_id']!r}"
    )
    for field in ("issued_by_user_id", "cleared_workload_ceiling_index", "expires_on", "restriction_note"):
        assert clearance[field] is None, (
            f"MedicalClearance.{field} must start null, got {clearance[field]!r}"
        )

    stored_player = fixtures.read_player(api, player["id"])
    assert stored_player["medical_status"] == "PENDING_CLEARANCE", (
        f"a request is not a verdict, got {stored_player['medical_status']!r}"
    )
    assert stored_player["roster_status"] == "RESERVE_LIST", (
        f"the player is still unassigned, got {stored_player['roster_status']!r}"
    )


def test_submitting_then_certifying_walks_the_licence_and_derives_two_postures(api: ApiClient):
    """The identical happy path lands `OPEN` at one club and `RESTRICTED` at another.

    PRD 3.2: "Submission records `submitted_by_user_id` from the acting
    `X-User-ID`, runs the provisional expense allocation described in Section 3.3
    — writing `provisional_club_obligation_cents` and `affiliate_overflow_cents`
    — and recomputes `posture`, which stays `FROZEN` because the licence is not
    yet `ACTIVE`."  Certification then splits the two clubs apart, because PRD
    3.2 says "Activation then runs the posture derivation, writing `posture` to
    either `OPEN` or `RESTRICTED` according to the rules in Section 2.9 — a club
    that satisfies its staffing floor and role coverage comes out `OPEN`, a club
    that does not comes out `RESTRICTED` and is immediately barred from
    promotions." and PRD 2.9 fixes the arithmetic: "Failing that, it is
    `RESTRICTED` when the affiliate's `active_roster_count` is below the
    agreement's `minimum_active_players`, or when any role listed in the
    agreement's `required_staff_roles` has no allocation at this affiliate that
    is both in status `ACTIVE` and filling that `staff_role`."

    Design: Corner/state_machines/agreement_submit_then_activate_walks_the_happy_path_and_derives_posture
    """
    open_club = fixtures.create_affiliate(
        api,
        name="Posture Open Club",
        level="HIGH_A",
        market_city="Eugene",
        meal_stipend_cents_per_day=2800,
    )
    open_agreement = fixtures.create_agreement(api, open_club["id"])
    submitted = fixtures.submit_agreement(api, open_agreement["id"], open_club["id"])

    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert submitted["posture"] == "FROZEN", (
        f"a submitted licence is not yet ACTIVE, so it stays FROZEN, got {submitted['posture']}"
    )
    assert submitted["submitted_by_user_id"] == open_club["id"], (
        f"the submitter is the club's own operator id, got {submitted['submitted_by_user_id']!r}"
    )
    assert_money(
        submitted["provisional_club_obligation_cents"], 0, "provisional_club_obligation_cents"
    )
    assert_money(submitted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert submitted["settlement_status"] == "NOT_SETTLED", (
        f"submission is not settlement, got {submitted['settlement_status']!r}"
    )

    activated = fixtures.activate_agreement(api, open_agreement["id"])
    assert_status(activated, "ACTIVE", "AffiliationAgreement")
    assert activated["posture"] == "OPEN", (
        f"a zero floor with no required roles derives OPEN, got {activated['posture']}"
    )

    restricted_club = fixtures.create_affiliate(
        api,
        name="Posture Restricted Club",
        level="HIGH_A",
        market_city="Spokane",
        meal_stipend_cents_per_day=2800,
    )
    restricted_agreement = _draft_without_a_staffing_floor(api, restricted_club["id"])
    assert_integer(
        restricted_agreement["minimum_active_players"], 22, "minimum_active_players"
    )
    fixtures.submit_agreement(api, restricted_agreement["id"], restricted_club["id"])
    restricted_activated = fixtures.activate_agreement(api, restricted_agreement["id"])

    assert_status(restricted_activated, "ACTIVE", "AffiliationAgreement")
    assert restricted_activated["posture"] == "RESTRICTED", (
        "an empty roster under a floor of 22 derives RESTRICTED, got "
        f"{restricted_activated['posture']}"
    )


def test_undeclared_actions_out_of_draft_and_out_of_active_are_both_refused(api: ApiClient):
    """Three actions that no declared transition offers, three state refusals.

    PRD 3.2: "Once terminated or rejected, a licence accepts no further
    disposition; requesting one yields `ERR_INVALID_AGREEMENT_STATE`, as does any
    action that is not a declared transition out of the licence's current
    status."  Certification is reachable only from `SUBMITTED` — PRD 3.2: "A
    `ComplianceOfficer` activates a `SUBMITTED` licence, moving it `SUBMITTED` →
    `ACTIVE`, which is permitted only when the affiliate's `facility_status` is
    not `DEFICIENT`; an activation attempted over an open major deficiency is
    refused with `ERR_FACILITY_DEFICIENCY_BLOCKING`." — and submission only from
    `DRAFT`, per PRD 3.2: "When the club's `AffiliateOperator` submits, the
    licence moves `DRAFT` → `SUBMITTED`, and three conditions must hold: the
    acting `X-User-ID` must equal the agreement's `affiliate_id`,
    `term_end_date` must be strictly after `term_start_date`, and no other
    agreement for the same club may currently sit in status `SUBMITTED` or
    `ACTIVE` — a second concurrent licence is refused with
    `ERR_DUPLICATE_ACTIVE_AGREEMENT`."

    Design: Corner/state_machines/undeclared_agreement_actions_from_draft_and_active_are_rejected
    """
    club = fixtures.create_affiliate(
        api,
        name="Undeclared Action Club",
        level="SINGLE_A",
        market_city="Fresno",
        meal_stipend_cents_per_day=2600,
    )
    draft = fixtures.create_agreement(api, club["id"])

    validate_error(
        _dispose_agreement(api, draft["id"], "ACTIVATE"),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )
    validate_error(
        _dispose_agreement(api, draft["id"], "SUSPEND"),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )
    assert_status(
        fixtures.read_agreement(api, club["id"], draft["id"]), "DRAFT", "AffiliationAgreement"
    )

    licensed = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Already Certified Club",
            "level": "SINGLE_A",
            "market_city": "Stockton",
            "meal_stipend_cents_per_day": 2600,
        },
    )
    validate_error(
        _dispose_agreement(
            api,
            licensed["agreement_id"],
            "SUBMIT",
            make_affiliate_operator_headers(licensed["affiliate_id"]),
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )
    assert_status(
        fixtures.read_agreement(api, licensed["affiliate_id"], licensed["agreement_id"]),
        "ACTIVE",
        "AffiliationAgreement",
    )


def test_a_rejected_licence_is_terminal_yet_a_replacement_may_still_be_drafted(api: ApiClient):
    """Nothing moves the rejected row again, and the club is not locked out.

    PRD 3.2: "Alternatively the officer may reject a `SUBMITTED` licence, moving
    it `SUBMITTED` → `REJECTED`, a terminal state, and setting `posture` to
    `FROZEN`."  Terminality is absolute, per PRD 3.2: "Once terminated or
    rejected, a licence accepts no further disposition; requesting one yields
    `ERR_INVALID_AGREEMENT_STATE`, as does any action that is not a declared
    transition out of the licence's current status."  A replacement draft is
    nonetheless admissible, because the duplicate guard in PRD 3.2 names only two
    statuses: "no other agreement for the same club may currently sit in status
    `SUBMITTED` or `ACTIVE` — a second concurrent licence is refused with
    `ERR_DUPLICATE_ACTIVE_AGREEMENT`."

    Design: Corner/state_machines/rejected_agreement_is_terminal_and_accepts_no_further_action
    """
    club = fixtures.create_affiliate(
        api,
        name="Rejected Licence Club",
        level="DOUBLE_A",
        market_city="Pensacola",
        meal_stipend_cents_per_day=3000,
    )
    agreement = fixtures.create_agreement(api, club["id"])
    fixtures.submit_agreement(api, agreement["id"], club["id"])
    rejected = fixtures.dispose_agreement(
        api, agreement["id"], "REJECT", note="facility plan incomplete"
    )

    assert_status(rejected, "REJECTED", "AffiliationAgreement")
    assert rejected["posture"] == "FROZEN", (
        f"a rejection freezes the posture, got {rejected['posture']}"
    )

    for action in ("REINSTATE", "TERMINATE"):
        validate_error(
            _dispose_agreement(api, agreement["id"], action),
            ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
            409,
        )
    validate_error(
        _dispose_agreement(
            api, agreement["id"], "SUBMIT", make_affiliate_operator_headers(club["id"])
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )
    assert_status(
        fixtures.read_agreement(api, club["id"], agreement["id"]),
        "REJECTED",
        "AffiliationAgreement",
    )

    rows, meta = validate_paginated(
        api.list_agreements(club["id"], COMPLIANCE_OFFICER_HEADERS, {"status": "REJECTED"})
    )
    assert_integer(meta["total_count"], 1, "agreement total_count")
    assert rows[0]["id"] == agreement["id"], (
        f"the filtered listing returns the rejected licence, got {rows[0]['id']!r}"
    )

    replacement = fixtures.create_agreement(api, club["id"])
    assert_status(replacement, "DRAFT", "AffiliationAgreement")
    assert replacement["id"] != agreement["id"], "the replacement must be a new row"


def test_a_consumed_action_fails_on_its_second_attempt_and_writes_nothing(api: ApiClient):
    """Two actions replayed once each: the second attempt is a state error.

    PRD 3.2: "Once terminated or rejected, a licence accepts no further
    disposition; requesting one yields `ERR_INVALID_AGREEMENT_STATE`, as does any
    action that is not a declared transition out of the licence's current
    status."  The medical record behaves the same way, per PRD 3.5: "Any
    clearance action that is not a declared transition out of the record's
    current status is refused with `ERR_INVALID_CLEARANCE_STATE`, and each
    successful disposition increments the clearance's `version` by one."  Because
    the replayed issue is refused rather than applied, the fields the first issue
    wrote stand — PRD 3.5: "Issuing records `issued_by_user_id`,
    `cleared_workload_ceiling_index` — the workload-index ceiling the medical
    staff is willing to clear the player for — and `expires_on`; it advances the
    player's `medical_status` to `CLEARED`; and it returns a player sitting in
    `RESTRICTED` roster standing to `RESERVE_LIST` when that player holds no
    active assignment."

    Design: Corner/state_machines/repeating_a_consumed_action_fails_on_the_second_attempt
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    club = fixtures.create_affiliate(
        api,
        name="Replay Club",
        level="HIGH_A",
        market_city="Rome",
        meal_stipend_cents_per_day=2800,
    )
    agreement = fixtures.create_agreement(api, club["id"])
    player = fixtures.create_player(
        api, full_name="Replay Player", origin="DOMESTIC_DRAFT", signed_date="2025-06-10"
    )
    clearance = fixtures.request_clearance(api, player["id"], "LEVEL_ASSIGNMENT")

    submitted = fixtures.submit_agreement(api, agreement["id"], club["id"])
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    validate_error(
        _dispose_agreement(
            api, agreement["id"], "SUBMIT", make_affiliate_operator_headers(club["id"])
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )

    issued = fixtures.dispose_clearance(
        api,
        clearance["id"],
        "ISSUE",
        cleared_workload_ceiling_index=20.00,
        expires_on="2026-12-31",
    )
    assert_status(issued, "ISSUED", "MedicalClearance")

    replay = api.dispose_medical_clearance(
        clearance["id"],
        factories.clearance_issue_payload(
            cleared_workload_ceiling_index=25.00, expires_on="2027-06-30"
        ),
        MEDICAL_DIRECTOR_HEADERS,
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_CLEARANCE_STATE.value, 409)

    stored = fixtures.read_clearance(api, player["id"], clearance["id"])
    assert_decimal(
        stored["cleared_workload_ceiling_index"],
        "20.00",
        2,
        "MedicalClearance.cleared_workload_ceiling_index",
    )
    assert stored["expires_on"] == "2026-12-31", (
        f"the refused replay may not rewrite expires_on, got {stored['expires_on']!r}"
    )

    rows, meta = validate_paginated(
        api.list_medical_clearances(player["id"], MEDICAL_DIRECTOR_HEADERS)
    )
    assert_integer(meta["total_count"], 1, "clearance total_count")
    assert_status(rows[0], "ISSUED", "MedicalClearance")


def test_suspending_the_licence_cascades_to_the_active_assignment_only(api: ApiClient):
    """One club, two assignments, and a cascade that is conditional on status.

    PRD 3.2: "Suspending an `ACTIVE` licence moves it `ACTIVE` → `SUSPENDED`,
    sets `posture` to `FROZEN`, and cascades to the club's players: every
    assignment at that affiliate currently in status `ACTIVE` moves to
    `SUSPENDED`, while assignments in `PENDING_CLEARANCE`, `COMPLETED` or
    `REVOKED` are left untouched."  The cascaded suspension carries its own
    consequences, per PRD 3.6: "In every case the club's roster counters are
    recomputed, because a suspended assignment no longer occupies a roster slot,
    and the player's `current_affiliate_id` is cleared. The player's
    `roster_status` depends on what caused the suspension: it moves to
    `RESTRICTED` when the cause was a clearance revocation, and to
    `RESERVE_LIST` otherwise."

    Design: Corner/state_machines/agreement_suspend_cascades_only_to_active_assignments
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Cascade Club",
            "level": "SINGLE_A",
            "market_city": "Modesto",
            "meal_stipend_cents_per_day": 2600,
        },
    )
    active = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Cascade Player X",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    pending_player = fixtures.create_player(
        api, full_name="Cascade Player Y", origin="DOMESTIC_DRAFT", signed_date="2025-06-11"
    )
    pending = fixtures.create_assignment(
        api,
        pending_player["id"],
        club["affiliate_id"],
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )

    before = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(before["active_roster_count"], 1, "active_roster_count")

    suspended = fixtures.dispose_agreement(api, club["agreement_id"], "SUSPEND")
    assert_status(suspended, "SUSPENDED", "AffiliationAgreement")
    assert suspended["posture"] == "FROZEN", (
        f"a suspended licence is FROZEN, got {suspended['posture']}"
    )

    assert_status(
        fixtures.read_assignment(api, active["assignment_id"]), "SUSPENDED", "PlayerAssignment"
    )
    assert_status(
        fixtures.read_assignment(api, pending["id"]), "PENDING_CLEARANCE", "PlayerAssignment"
    )

    after = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(after["active_roster_count"], 0, "active_roster_count")

    cascaded_player = fixtures.read_player(api, active["player_id"])
    assert cascaded_player["roster_status"] == "RESERVE_LIST", (
        f"a licence suspension is not a medical restriction, got {cascaded_player['roster_status']!r}"
    )
    assert cascaded_player["current_affiliate_id"] is None, (
        f"the club mirror is cleared, got {cascaded_player['current_affiliate_id']!r}"
    )
    assert cascaded_player["medical_status"] == "CLEARED", (
        f"the clearance is untouched by a licence event, got {cascaded_player['medical_status']!r}"
    )


def test_marking_a_half_finished_plan_achieved_is_refused_until_the_last_module_lands(api: ApiClient):
    """The same action, two outcomes, separated only by one module of progress.

    PRD 3.7: "A plan reaches its happy terminal state when a `FarmDirector`
    marks it achieved, moving it `ACTIVE` → `ACHIEVED`. This requires
    `completion_pct` to be exactly `100.00`; an attempt made while any module
    remains outstanding is refused with `ERR_INVALID_PLAN_STATE`, which is also
    the error for any plan action that is not a declared transition out of the
    plan's current status."  The figure the precondition reads is the one PRD 3.7
    defines: "Recording progress updates `completed_module_count`, recomputes
    `completion_pct` as the completed count divided by the number of modules,
    multiplied by one hundred and rounded half-up to two decimal places, and
    recomputes the player's `promotion_readiness`."  Once the plan is terminal the
    player has no `ACTIVE` plan left, and PRD 3.7 fixes the consequence: "It
    reads the player's single `ACTIVE` development plan; plans in `DRAFT`,
    `REVISION_REQUESTED`, `ACHIEVED` or `LAPSED` contribute nothing, and a player
    with no `ACTIVE` plan scores `0.0000` regardless of how much workload history
    they have."

    Design: Corner/state_machines/plan_mark_achieved_requires_full_completion_then_succeeds
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate_with_active_player(
        api,
        affiliate_overrides={
            "name": "Plan Club",
            "level": "HIGH_A",
            "market_city": "Eugene",
            "meal_stipend_cents_per_day": 2800,
        },
        player_overrides={
            "full_name": "Plan Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    plan = fixtures.active_plan_on(
        api,
        club["assignment_id"],
        target_level="DOUBLE_A",
        curriculum_modules=["MOD_MECHANICS", "MOD_PITCH_MIX"],
    )
    halfway = fixtures.dispose_plan(
        api, plan["plan_id"], "RECORD_PROGRESS", completed_module_count=1
    )
    assert_decimal(halfway["completion_pct"], "50.00", 2, "DevelopmentPlan.completion_pct")
    assert_status(halfway, "ACTIVE", "DevelopmentPlan")

    refused = _dispose_plan(api, plan["plan_id"], "MARK_ACHIEVED")
    validate_error(refused, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
    assert_status(
        fixtures.read_plan(api, club["assignment_id"], plan["plan_id"]),
        "ACTIVE",
        "DevelopmentPlan",
    )

    complete = fixtures.dispose_plan(
        api, plan["plan_id"], "RECORD_PROGRESS", completed_module_count=2
    )
    assert_decimal(complete["completion_pct"], "100.00", 2, "DevelopmentPlan.completion_pct")
    assert_integer(complete["completed_module_count"], 2, "completed_module_count")

    achieved = fixtures.dispose_plan(api, plan["plan_id"], "MARK_ACHIEVED")
    assert_status(achieved, "ACHIEVED", "DevelopmentPlan")

    replay = _dispose_plan(api, plan["plan_id"], "RECORD_PROGRESS", completed_module_count=2)
    validate_error(replay, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

    player = fixtures.read_player(api, club["player_id"])
    assert_decimal(
        player["promotion_readiness"], "0.0000", 4, "Player.promotion_readiness"
    )


def test_the_hard_cap_auto_rejects_only_the_still_submitted_sibling(api: ApiClient):
    """Two approvals cap the pool; the cascade reaches one sibling and no other.

    PRD 3.9: "When an approval drives the pool `OPEN` → `HARD_CAPPED`, every
    sibling signing against that pool still in status `SUBMITTED` moves to
    `REJECTED` with `rejection_reason` set to `POOL_HARD_CAPPED`; siblings already
    `APPROVED` or already `REJECTED` are untouched."  The cap itself is arithmetic,
    per PRD 3.9: "Fourth, the pool's ledger is recomputed with the post-forfeit
    figure: `effective_pool_cents` becomes the base allotment plus the trade
    adjustment minus the now-updated `forfeited_cents`; `allocated_cents` becomes
    the new allocated figure; `remaining_cents` becomes the effective pool minus
    the allocated amount, which may be negative; and the pool's status becomes
    `HARD_CAPPED` when the allocated amount is strictly greater than the effective
    pool, or stays `OPEN` otherwise."  The second approval crosses the pool by
    400000 cents, which is taxed but does not breach the third tier, because PRD
    3.9 sets that trigger higher: "`tier3_breach` is set true when the total
    overage is strictly above 1000000 cents *and* the prior overage was at most
    1000000 cents — that is, when this particular approval is the one that
    crossed the second ceiling — and on such a breach 250000 cents is added to the
    pool's `forfeited_cents`."

    Design: Corner/state_machines/pool_hard_cap_auto_rejects_only_the_still_submitted_siblings
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Boca Chica Academy",
            "market_city": "Boca Chica",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    signings = []
    for name, bonus in (
        ("Prospect Uno", 3000000),
        ("Prospect Dos", 2400000),
        ("Prospect Tres", 1000000),
    ):
        prospect = fixtures.create_player(
            api,
            INTERNATIONAL_SCOUT_HEADERS,
            full_name=name,
            origin="INTERNATIONAL_FA",
            signed_date="2026-01-15",
        )
        signings.append(
            fixtures.create_signing(
                api, pool["id"], prospect["id"], academy["affiliate_id"], bonus_cents=bonus
            )["id"]
        )

    first = fixtures.dispose_signing(api, signings[0], "APPROVE")
    assert_status(first, "APPROVED", "InternationalSigning")
    assert_money(first["pool_charge_cents"], 3000000, "pool_charge_cents")
    assert_money(first["overage_tax_cents"], 0, "overage_tax_cents")

    after_first = fixtures.read_pool(api, pool["id"])
    assert_status(after_first, "OPEN", "SigningPool")
    assert_money(after_first["allocated_cents"], 3000000, "allocated_cents")
    assert_money(after_first["remaining_cents"], 2000000, "remaining_cents")

    second = fixtures.dispose_signing(api, signings[1], "APPROVE")
    assert_money(second["overage_tax_cents"], 300000, "overage_tax_cents")
    assert second["tier3_breach"] is False, (
        f"a 400000-cent overage stays inside the second ceiling, got {second!r}"
    )

    capped = fixtures.read_pool(api, pool["id"])
    assert_money(capped["allocated_cents"], 5400000, "allocated_cents")
    assert_money(capped["overage_tax_accrued_cents"], 300000, "overage_tax_accrued_cents")
    assert_money(capped["forfeited_cents"], 0, "forfeited_cents")
    assert_money(capped["effective_pool_cents"], 5000000, "effective_pool_cents")
    assert_money(capped["remaining_cents"], -400000, "remaining_cents")
    assert_status(capped, "HARD_CAPPED", "SigningPool")

    auto_rejected = fixtures.read_signing(api, signings[2])
    assert_status(auto_rejected, "REJECTED", "InternationalSigning")
    assert auto_rejected["rejection_reason"] == "POOL_HARD_CAPPED", (
        f"the cascade names its own cause, got {auto_rejected['rejection_reason']!r}"
    )

    untouched = fixtures.read_signing(api, signings[0])
    assert_status(untouched, "APPROVED", "InternationalSigning")
    assert_money(untouched["pool_charge_cents"], 3000000, "pool_charge_cents")
