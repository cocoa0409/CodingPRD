"""The cross-cutting layers: version guards, one deep cascade and one boundary.

The four guarded writes are each exercised with a version that a real writer
would plausibly still be holding, and each refusal is paired with evidence that
nothing moved.
"""
from test_helpers import (
    BILLING,
    CONSULTANT,
    PRINCIPAL,
    adjudicate_background_payload,
    api_client,
    append_ledger_adjustment,
    create_accommodation_term_payload,
    create_onboarded_household,
    create_placement_payload,
    create_replacement_claim_payload,
    create_trial_engagement_payload,
    file_claim,
    invoice_milestone,
    ledger_adjustment_payload,
    propose_accommodation_term,
    read_background_verification,
    read_candidate,
    read_client,
    read_ledger,
    read_milestones,
    read_placement,
    read_requisition,
    record_reference,
    respond_to_term,
    review_claim,
    review_claim_payload,
    set_clock,
    setup_active_placement,
    setup_passed_trial,
    setup_scenario,
    setup_vetted_candidate,
    terminate_placement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_reference,
)

THIRD_REFERENCE = {
    "principal_employer_name": "Pemberton House",
    "contact_email": "pemberton@mail.example",
    "employment_start_month": "2024-01",
    "employment_end_month": "2024-06",
}


class TestTheRequisitionVersionGate:
    def test_01_an_offer_built_on_a_pre_negotiation_version_is_refused(self):
        """The negotiation consumed that version, so the offer is holding a stale
        picture.

        PRD §2.8: "Creating a placement through `POST /placements` requires
        `expected_requisition_version`, carrying the client's last observed
        `version` of the `RoleRequisition` named by `requisition_id`. If the
        requisition's stored `version` differs, the create is refused with
        `ERR_STALE_REQUISITION_VERSION` (HTTP 412) — the writer's picture of which
        candidate holds the outstanding offer and which trials are still live is out
        of date, and a blind write would void a placement it never saw."

        Design: Corner/cross_cutting_complexity_layers/a_stale_requisition_version_is_refused_when_the_offer_is_created
        """
        scenario = setup_passed_trial()
        stale_version = read_requisition(scenario["requisition"])["version"]

        term = propose_accommodation_term(
            scenario["requisition"], scenario["candidate"]
        )
        respond_to_term(term, scenario["client_headers"], "ACCEPT")

        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    scenario["requisition"]["id"],
                    scenario["candidate"]["id"],
                    stale_version,
                ),
                CONSULTANT,
            ),
            "ERR_STALE_REQUISITION_VERSION",
            412,
        )

        _, meta = validate_paginated(api_client.list_placements(CONSULTANT))
        assert meta["total_count"] == 0
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"

    def test_02_the_same_offer_body_lands_once_the_version_is_refreshed(self):
        """Only the version differs from the refused attempt.

        PRD §2.4: "`version` is an integer that begins at 1 when the row is created
        and increments by exactly 1 on every mutation of that row, including
        mutations reached indirectly through a cascade."

        PRD §3.6: "Fifth, the requisition moves `TRIALING → OFFER_PENDING`, or takes
        the `OFFER_PENDING → OFFER_PENDING` self-loop on the supersede path, and its
        `version` is incremented."

        Design: Corner/cross_cutting_complexity_layers/the_current_requisition_version_is_accepted_where_the_stale_one_was_refused
        """
        scenario = setup_passed_trial()
        stale_version = read_requisition(scenario["requisition"])["version"]

        term = propose_accommodation_term(
            scenario["requisition"], scenario["candidate"]
        )
        respond_to_term(term, scenario["client_headers"], "ACCEPT")

        current_version = read_requisition(scenario["requisition"])["version"]
        assert current_version > stale_version

        placement = validate_success(
            api_client.create_placement(
                create_placement_payload(
                    scenario["requisition"]["id"],
                    scenario["candidate"]["id"],
                    current_version,
                ),
                CONSULTANT,
            ),
            201,
        )
        assert placement["placement_status"] == "PENDING_ACCEPTANCE"
        assert placement["fee_cents"] == 2_000_000

        after = read_requisition(scenario["requisition"])
        assert after["status"] == "OFFER_PENDING"
        assert after["version"] == current_version + 1

    def test_03_a_fresh_proposal_on_a_stale_version_leaves_the_counter_alive(self):
        """A stale proposal would have superseded a round the writer never saw.

        PRD §2.8: "Proposing a new accommodation term through `POST
        /role-requisitions/{id}/accommodation-terms` likewise requires
        `expected_requisition_version` against the same parent, and a mismatch is
        refused with `ERR_STALE_REQUISITION_VERSION` (HTTP 412). A fresh proposal
        drives any open term on that requisition to `SUPERSEDED`, so a stale writer
        would silently discard a negotiation round it never observed."

        Design: Corner/cross_cutting_complexity_layers/a_stale_requisition_version_is_refused_when_a_new_term_is_proposed
        """
        scenario = setup_passed_trial()
        stale_version = read_requisition(scenario["requisition"])["version"]

        term = propose_accommodation_term(
            scenario["requisition"], scenario["candidate"]
        )
        countered = respond_to_term(
            term, scenario["client_headers"], "COUNTER", weekly_hours=42
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_no"] == 2

        validate_error(
            api_client.create_accommodation_term(
                scenario["requisition"]["id"],
                create_accommodation_term_payload(
                    scenario["candidate"]["id"], stale_version, weekly_hours=45
                ),
                CONSULTANT,
            ),
            "ERR_STALE_REQUISITION_VERSION",
            412,
        )

        rows, meta = validate_paginated(
            api_client.list_accommodation_terms(
                CONSULTANT, {"requisition_id": scenario["requisition"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == term["id"]
        assert rows[0]["status"] == "COUNTERED"
        assert rows[0]["round_no"] == 2
        assert rows[0]["weekly_hours"] == 42


class TestTheCandidateAndPlacementVersionGates:
    def test_04_an_adjudication_on_a_pre_reference_version_is_refused(self):
        """A third verified reference moved the candidate between the read and the
        decision.

        PRD §2.8: "Adjudicating a flagged background result through `POST
        /background-verifications/{id}/adjudicate` requires
        `expected_candidate_version`, carrying the last observed `version` of the
        subject `Candidate`. A mismatch is refused with
        `ERR_STALE_CANDIDATE_VERSION` (HTTP 412), because a failing disposition fans
        a multi-hop cascade across the candidate's trials and their requisitions and
        the adjudicator must have seen the vetting state, scores and trial set that
        the cascade is about to act on."

        PRD §3.3: "`PASS` moves the screen `FLAGGED → ADJUDICATED_PASS`, stamps
        `adjudicated_by_user_id` and `waiver_note`, advances the candidate
        `BACKGROUND_PENDING → CLEARED`, and increments both `Candidate.version` and
        `BackgroundVerification.version` by 1."

        Design: Corner/cross_cutting_complexity_layers/a_stale_candidate_version_is_refused_at_adjudication
        """
        scenario = setup_scenario(
            stage="background_recorded", background_result="FLAGGED"
        )
        verification = scenario["background"]
        assert verification["status"] == "FLAGGED"

        stale_version = read_candidate(scenario["candidate"])["version"]
        verify_reference(record_reference(scenario["candidate"], **THIRD_REFERENCE))

        validate_error(
            api_client.adjudicate_background_verification(
                verification["id"],
                adjudicate_background_payload("PASS", stale_version),
                PRINCIPAL,
            ),
            "ERR_STALE_CANDIDATE_VERSION",
            412,
        )

        stored = read_background_verification(verification)
        assert stored["status"] == "FLAGGED"
        assert stored["waiver_note"] is None
        assert read_candidate(scenario["candidate"])["vetting_status"] == (
            "BACKGROUND_PENDING"
        )

        fresh_version = read_candidate(scenario["candidate"])["version"]
        adjudicated = validate_success(
            api_client.adjudicate_background_verification(
                verification["id"],
                adjudicate_background_payload("PASS", fresh_version),
                PRINCIPAL,
            )
        )
        assert adjudicated["status"] == "ADJUDICATED_PASS"
        assert read_candidate(scenario["candidate"])["vetting_status"] == "CLEARED"

    def test_05_a_claim_built_on_a_pre_termination_version_is_refused(self):
        """The termination bumped the placement after the household read it.

        PRD §2.8: "Filing a replacement claim through `POST
        /placements/{id}/replacement-claims` requires `expected_placement_version`,
        carrying the last observed `version` of the subject `Placement`. A mismatch
        is refused with `ERR_STALE_PLACEMENT_VERSION` (HTTP 412); re-filing after a
        denial legitimately supersedes the earlier claim, so a stale filer might not
        have seen the previous decision, the re-allocated milestone schedule or the
        current guarantee snapshot."

        Design: Corner/cross_cutting_complexity_layers/a_stale_placement_version_is_refused_when_a_claim_is_filed
        """
        scenario = setup_active_placement()
        stale_version = read_placement(scenario["placement"])["version"]

        set_clock("2026-09-20T00:00:00Z")
        terminated = terminate_placement(scenario["placement"], "2026-09-20")
        assert terminated["placement_status"] == "TERMINATED_NO_REMEDY"
        assert terminated["version"] > stale_version

        validate_error(
            api_client.create_replacement_claim(
                scenario["placement"]["id"],
                create_replacement_claim_payload(
                    "REFUND", "2026-09-20", stale_version
                ),
                scenario["client_headers"],
            ),
            "ERR_STALE_PLACEMENT_VERSION",
            412,
        )

        _, meta = validate_paginated(
            api_client.list_placement_replacement_claims(
                scenario["placement"]["id"], PRINCIPAL
            )
        )
        assert meta["total_count"] == 0
        assert read_placement(scenario["placement"])["placement_status"] == (
            "TERMINATED_NO_REMEDY"
        )


class TestVersionCountsEveryWrite:
    def test_06_four_writes_of_three_kinds_leave_the_household_at_version_four(self):
        """A version that only tracked lifecycle transitions would stop at three.

        PRD §2.4: "`version` is an integer that begins at 1 when the row is created
        and increments by exactly 1 on every mutation of that row, including
        mutations reached indirectly through a cascade."

        PRD §2.12: "The invariant is exact and holds after every append: the
        household's `outstanding_balance_cents` equals the sum of
        `signed_amount_cents` across its ledger, and equals the last row's
        `balance_after_cents`."

        Design: Corner/cross_cutting_complexity_layers/every_write_to_a_household_increments_its_version
        """
        set_clock("2026-08-01T00:00:00Z")
        household = create_onboarded_household()
        assert read_client(household)["version"] == 3

        entry = validate_success(
            api_client.create_ledger_adjustment(
                household["id"], ledger_adjustment_payload(250_000), BILLING
            ),
            201,
        )
        assert entry["balance_after_cents"] == 250_000

        stored = read_client(household)
        assert stored["version"] == 4
        assert stored["outstanding_balance_cents"] == 250_000
        assert stored["status"] == "ONBOARDED"
        assert stored["confidentiality_agreement_status"] == "COUNTERSIGNED"


class TestTheApprovedReplacementCascade:
    def test_07_a_granted_replacement_voids_only_the_open_milestones(self):
        """The aged receivable survives the grant while the two open rows do not.

        PRD §3.8: "`APPROVE_REPLACEMENT` grants a fresh search rather than money.
        The claim moves `UNDER_REVIEW → APPROVED_REPLACEMENT`; the placement moves
        to `TERMINATED_REPLACED`, which is admissible whether it was still `ACTIVE`
        or had already been recorded as `TERMINATED_NO_REMEDY`; every `FeeMilestone`
        of that placement whose `invoice_status` is `PENDING` moves to `VOIDED`, with
        the fee already collected carried as search credit and **no ledger movement
        of any kind**; the requisition moves `PLACED → SOURCING` so the search
        reopens without consuming a scoping round; and the candidate moves `PLACED →
        COOLING_OFF` if still `PLACED`. Every row touched has its `version`
        incremented."

        Design: Corner/cross_cutting_complexity_layers/approving_a_replacement_voids_the_open_milestones_and_reopens_the_search
        """
        scenario = setup_active_placement()
        invoice_milestone(scenario["milestones"][0])
        set_clock("2026-09-20T00:00:00Z")

        claim = file_claim(
            scenario["placement"],
            scenario["client_headers"],
            "REPLACEMENT",
            "2026-09-20",
        )
        assert review_claim(claim, "OPEN_REVIEW")["status"] == "UNDER_REVIEW"

        approved = validate_success(
            api_client.review_replacement_claim(
                claim["id"], review_claim_payload("APPROVE_REPLACEMENT"), PRINCIPAL
            )
        )
        assert approved["status"] == "APPROVED_REPLACEMENT"

        assert read_placement(scenario["placement"])["placement_status"] == (
            "TERMINATED_REPLACED"
        )

        milestones = read_milestones(scenario["placement"])
        assert [row["invoice_status"] for row in milestones] == [
            "OVERDUE",
            "VOIDED",
            "VOIDED",
        ]
        assert milestones[0]["amount_cents"] == 600_000

        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["scoping_round"] == 1

        household = read_client(scenario["client"])
        assert household["outstanding_balance_cents"] == 600_000
        entries = read_ledger(scenario["client"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "FEE_INVOICED"

        assert read_candidate(scenario["candidate"])["availability_status"] == (
            "COOLING_OFF"
        )


class TestTheCreditLimitBoundary:
    def test_08_a_balance_exactly_on_the_limit_still_books_a_trial(self):
        """Fifty thousand dollars on the nose is the largest balance that still
        transacts.

        PRD §2.12: "The balance drives one gate. When a household's
        `outstanding_balance_cents` is **strictly greater** than 5,000,000 cents —
        fifty thousand dollars — it is on **credit hold**, and neither a new trial
        booking nor a new offer may be made for it; both are refused with
        `ERR_CLIENT_CREDIT_HOLD` (HTTP 409). A balance of exactly 5,000,000 cents
        still transacts."

        PRD §3.4: "`iso_week_key` is derived from `start_at` as the ISO year and
        week formatted as four digits, a hyphen, the letter `W` and two digits, with
        each week beginning at Monday 00:00:00.000Z."

        Design: Corner/cross_cutting_complexity_layers/a_balance_exactly_on_the_credit_limit_still_transacts
        """
        scenario = setup_vetted_candidate()
        append_ledger_adjustment(
            scenario["client"],
            5_000_000,
            memo="Balance carried at the credit limit.",
        )
        assert read_client(scenario["client"])["outstanding_balance_cents"] == (
            5_000_000
        )

        trial = validate_success(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(scenario["candidate"]["id"]),
                CONSULTANT,
            ),
            201,
        )
        assert trial["status"] == "SCHEDULED"
        assert trial["iso_week_key"] == "2026-W33"

        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "TRIALING"
        assert requisition["active_trial_count"] == 1
