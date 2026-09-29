"""Declared edges fired one at a time: what each transition moves, what it
leaves alone, which terminal states admit nothing further, and which refusals
each machine reports from a state it does not accept.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OFFICER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_HEADERS,
    make_facility_registrant_headers,
    make_responsible_person_agent_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _cleared_dossier_listed_product(api, **listing_overrides):
    """A LISTED product whose FULL-mode dossier is still ADEQUATE."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={
            "product_name": "Aster Blush Powder",
            "category_code": "07A",
            "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            "label_contact_value": "safety@aster.example",
            **listing_overrides,
        },
    )
    dossier = X.dossier_at_decision(
        api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
    )
    get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
    bundle["listing"] = get_success_data(
        api.decide_listing(
            bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
        )
    )
    bundle["dossier_id"] = dossier["id"]
    return bundle


class TestRegistrationSubmissionIsAStateGuardedEdge:
    """One edge, nothing more, and no second helping of it."""

    def test_the_submission_moves_the_file_to_review_and_mints_nothing(self, api):
        """The whole effect of the submission is the transition and the version bump: no
        registration number, no coverage window, no cycle and not one ledger fact, because all
        of those belong to the later approval.

        PRD: "The transition `DRAFT → PENDING_REVIEW` is the whole of the operation's effect, plus the customary bump of the establishment's `version` by exactly 1."

        Design: Corner/state_machines/facility_submit_registration_advances_draft_to_pending_review
        """
        draft = X.create_draft_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        registrant = make_facility_registrant_headers(draft["id"])

        pending = get_success_data(api.submit_registration(draft["id"], registrant))

        assert pending["registration_status"] == K.REGISTRATION_STATUS_PENDING_REVIEW
        assert pending["version"] == draft["version"] + 1
        assert pending["facility_fei"] is None
        assert pending["registration_cycle_count"] == 0
        assert pending["current_period_start"] is None
        assert pending["grace_end_date"] is None

        _periods, period_meta = validate_paginated(
            api.list_registration_periods(draft["id"], registrant)
        )
        assert period_meta["total_count"] == 0
        _entries, ledger_meta = validate_paginated(
            api.list_ledger_entries(draft["id"], REVIEWER_HEADERS)
        )
        assert ledger_meta["total_count"] == 0

    def test_replaying_the_submission_is_a_conflict_rather_than_a_second_success(self, api):
        """Already being in the target state is not the same as being safe to repeat: the
        replay is refused on the state gate and the refused call advances no version.

        PRD: "Submitting the registration for agency review is admissible only from `DRAFT`; from any other registration state the request is rejected with `ERR_INVALID_FACILITY_STATE` (HTTP 409)."

        Design: Corner/state_machines/second_submit_registration_is_rejected_rather_than_treated_as_idempotent
        """
        pending = X.create_pending_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        registrant = make_facility_registrant_headers(pending["id"])

        validate_error(
            api.submit_registration(pending["id"], registrant),
            E.ERR_INVALID_FACILITY_STATE,
        )

        stored = X.read_facility(api, pending["id"])
        assert stored["version"] == pending["version"]
        assert stored["registration_status"] == K.REGISTRATION_STATUS_PENDING_REVIEW


class TestRejectionIsTheOnlyTerminalRegistrationState:
    """Three doors, all locked, and nothing behind them moves."""

    def test_a_rejected_file_admits_neither_a_resubmission_nor_a_second_decision(self, api):
        """A rejection cannot be re-opened from either side: the registrant's replay and the
        reviewer's change of heart both hit the same state gate, and the establishment is left
        exactly as the rejection found it.

        PRD: "A rejection moves the establishment `PENDING_REVIEW → REJECTED`, which is terminal: no product listing may ever be created against a rejected establishment, and none of the renewal paths can revive it."
        PRD: "Both branches require `registration_status` to be `PENDING_REVIEW`; anything else is `ERR_INVALID_FACILITY_STATE`."

        Design: Corner/state_machines/rejected_facility_is_terminal_and_admits_no_further_transition
        """
        rejected = X.create_rejected_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        registrant = make_facility_registrant_headers(rejected["id"])

        validate_error(
            api.submit_registration(rejected["id"], registrant),
            E.ERR_INVALID_FACILITY_STATE,
        )
        validate_error(
            api.decide_registration(
                rejected["id"], F.registration_decision_payload("APPROVE"), REVIEWER_HEADERS
            ),
            E.ERR_INVALID_FACILITY_STATE,
        )

        stored = X.read_facility(api, rejected["id"])
        assert stored["registration_status"] == K.REGISTRATION_STATUS_REJECTED
        assert stored["version"] == rejected["version"]
        assert stored["facility_fei"] is None

    def test_a_rejected_establishment_may_never_acquire_a_product(self, api):
        """The establishment exists, so this is not a lookup failure, and its posture is not
        the objection either: the register simply does not admit new products for a file it
        has refused.

        PRD: "The governing establishment must have `registration_status` `REGISTERED` or `RENEWAL_DUE`; a `DRAFT`, `PENDING_REVIEW`, `REJECTED` or `LAPSED` establishment cannot acquire new listings, and the attempt is rejected with `ERR_FACILITY_NOT_REGISTERED` (HTTP 409)."

        Design: Corner/state_machines/rejected_facility_is_terminal_and_admits_no_further_transition
        """
        rejected = X.create_rejected_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        person = X.create_responsible_person(api, legal_name="Aster Brands Inc")
        agent = make_responsible_person_agent_headers(person["id"])

        validate_error(
            api.create_listing(
                F.listing_payload(
                    rejected["id"], person["id"],
                    product_name="Aster Blush Powder", category_code="07A",
                    label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
                    label_contact_value="safety@aster.example",
                ),
                agent,
            ),
            E.ERR_FACILITY_NOT_REGISTERED,
        )

        _rows, meta = validate_paginated(api.list_listings(REVIEWER_HEADERS))
        assert meta["total_count"] == 0


class TestFreshRowsBeginInTheirDeclaredStates:
    """Four machines, four initial states, none of them inferred from a parent."""

    def test_a_second_product_initialises_both_of_its_dimensions_independently(self, api):
        """The two state dimensions of a listing are separate machines, so a brand-new product
        under an establishment that already markets one starts in the register's initial state
        on one axis and the safety machine's initial state on the other.

        PRD: "A freshly created listing answers 201 and begins with `listing_status` `DRAFT`, `safety_status` `UNSUBSTANTIATED`, `listing_number` and `suspension_reason` both null, `allergen_disclosure_complete` true, `undisclosed_allergen_count` 0, `distributed_units_total` 0, `open_recall_count` 0, `open_serious_event_count` 0, `marketable` false and `version` 1."

        Design: Corner/state_machines/four_entities_begin_in_their_documented_initial_states
        """
        bundle = _cleared_dossier_listed_product(api)

        second = X.create_draft_listing(
            api, bundle["facility_id"], bundle["person_id"],
            product_name="Aster Lip Balm", category_code="12A",
            label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            label_contact_value="safety@aster.example",
        )

        A.assert_listing_defaults(second)
        assert bundle["listing"]["listing_status"] == K.LISTING_STATUS_LISTED

    def test_a_new_dossier_starts_undecided_at_round_zero(self, api):
        """A dossier is born with neither a review mode nor a score nor a reviewer, because
        nothing has been asked of the agency yet.

        PRD: "The new dossier records the listing through its `listing_id` and starts in `status` `DRAFT` with `revision_round` 0, `review_mode` null, `adequacy_score` null, `decided_at` null, and both `screening_reviewer_user_id` and `full_reviewer_user_id` null."

        Design: Corner/state_machines/four_entities_begin_in_their_documented_initial_states
        """
        bundle = _cleared_dossier_listed_product(api)
        second = X.create_draft_listing(
            api, bundle["facility_id"], bundle["person_id"],
            product_name="Aster Lip Balm", category_code="12A",
            label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            label_contact_value="safety@aster.example",
        )

        dossier = X.open_dossier(
            api, second["id"], bundle["agent"],
            assessment_basis=K.ASSESSMENT_BASIS_PANEL_MONOGRAPH,
        )

        assert dossier["listing_id"] == second["id"]
        assert dossier["status"] == K.SUBSTANTIATION_STATUS_DRAFT
        assert dossier["revision_round"] == 0
        assert dossier["review_mode"] is None
        assert dossier["adequacy_score"] is None
        assert dossier["decided_at"] is None
        assert dossier["screening_reviewer_user_id"] is None
        assert dossier["full_reviewer_user_id"] is None

    def test_a_new_recall_demands_a_plan_and_counts_against_the_product(self, api):
        """Opening enforcement business against a marketed product starts the recall in the
        state that asks the sponsor for a plan, with every plan and effectiveness field still
        empty, and immediately registers one open recall on the product.

        PRD: "The action is created with `status` `PLAN_REQUIRED` and `plan_round` 0, with `corrective_summary`, `distribution_depth`, `plan_submitted_at`, `plan_decision_user_id`, `plan_decision_at` and `effectiveness_rate_final` all null."
        PRD: "Opening a recall raises the listing's `open_recall_count` by 1 and recomputes `marketable` — which is how a recall blocks a delisting even while the product remains on the register."

        Design: Corner/state_machines/four_entities_begin_in_their_documented_initial_states
        """
        bundle = _cleared_dossier_listed_product(api)

        recall = X.open_recall(
            api, bundle["listing_id"], K.INITIATION_BASIS_VOLUNTARY, "CLASS_II"
        )

        assert recall["status"] == K.RECALL_STATUS_PLAN_REQUIRED
        assert recall["plan_round"] == 0
        assert recall["corrective_summary"] is None
        assert recall["distribution_depth"] is None
        assert recall["plan_submitted_at"] is None
        assert recall["plan_decision_user_id"] is None
        assert recall["plan_decision_at"] is None
        assert recall["effectiveness_rate_final"] is None

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["open_recall_count"] == 1
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED

    def test_a_new_withdrawal_round_opens_with_every_tally_at_zero(self, api):
        """A round is opened before any paperwork is produced, so it carries no records, no
        shipped denominator, no rates and no verdict.

        PRD: "A successful open creates a `MarketWithdrawal` with `status` `OPEN`, `records_produced_count` 0, `shipped_units_total` 0, `outstanding_units_total` 0 and both recovery rates 0.00, moves the recall to `EXECUTING` — from `PLAN_ACCEPTED`, from `EXTENDED`, or as a self-loop from `EXECUTING` — and raises the recall's `version` by exactly 1."

        Design: Corner/state_machines/four_entities_begin_in_their_documented_initial_states
        """
        bundle = _cleared_dossier_listed_product(api)
        recall = X.recall_with_accepted_plan(
            api, bundle["listing_id"], bundle["agent"],
            initiation_basis=K.INITIATION_BASIS_VOLUNTARY, officer=OFFICER_HEADERS,
        )

        withdrawal = X.open_withdrawal(api, recall, OFFICER_HEADERS, K.DEPTH_CONSUMER)

        assert withdrawal["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert withdrawal["records_produced_count"] == 0
        assert withdrawal["shipped_units_total"] == 0
        assert withdrawal["outstanding_units_total"] == 0
        A.assert_two_decimal_value(
            withdrawal["reported_recovery_rate"], 0.00, "reported_recovery_rate"
        )
        A.assert_two_decimal_value(
            withdrawal["verified_recovery_rate"], 0.00, "verified_recovery_rate"
        )
        assert withdrawal["effectiveness_verdict"] is None
        assert X.read_recall(api, recall["id"])["status"] == K.RECALL_STATUS_EXECUTING


class TestSubmitReturnResubmitIsNotANoOp:
    """One designee's slot counter observed three times across one cycle."""

    def test_the_slot_is_taken_released_and_taken_again(self, api):
        """The submission occupies the designee's only slot, the agency's return gives it
        back and flips the party dormant, and the resubmission takes it a third time — the
        counter is genuinely walked, not merely restored.

        PRD: "On success the listing moves to `SUBMITTED`, the designee's `active_designation_count` rises by 1 and its `status` becomes `ACTIVE`, one `STATE_TRANSITION` ledger entry is appended against the listing, and the `version` of both the listing and the designee rises by exactly 1."
        PRD: "`SUBMITTED → RETURNED` sends the file back to the sponsor: it releases the designation slot, decrementing the designee's `active_designation_count` by 1 and flipping its `status` to `DORMANT` if that count reaches 0, and increments the `version` of both the listing and the designee by 1."

        Design: Corner/state_machines/listing_return_then_resubmit_releases_and_restores_the_designation_slot
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={
                "facility_name": "Aster Labs Newark",
                "owner_operator_name": "Aster Holdings LLC",
            },
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )

        get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
        after_submit = X.read_responsible_person(api, bundle["person_id"])
        assert after_submit["active_designation_count"] == 1
        assert after_submit["status"] == K.RP_STATUS_ACTIVE

        get_success_data(
            api.decide_listing(
                bundle["listing_id"],
                F.listing_decision_payload("RETURN", decision_note="Clarify the credential"),
                REVIEWER_HEADERS,
            )
        )
        after_return = X.read_responsible_person(api, bundle["person_id"])
        assert after_return["active_designation_count"] == 0
        assert after_return["status"] == K.RP_STATUS_DORMANT

        resubmitted = get_success_data(
            api.submit_listing(bundle["listing_id"], bundle["agent"])
        )
        assert resubmitted["listing_status"] == K.LISTING_STATUS_SUBMITTED
        after_resubmit = X.read_responsible_person(api, bundle["person_id"])
        assert after_resubmit["active_designation_count"] == 1
        assert after_resubmit["status"] == K.RP_STATUS_ACTIVE

    def test_no_register_number_is_minted_anywhere_in_the_cycle(self, api):
        """A number belongs to a listing decision of `LIST`, so three hops that never reach one
        leave the product unnumbered and uncounted by its establishment.

        PRD: "`SUBMITTED → LISTED` mints the register number into `listing_number`, formatted as the literal prefix `CPL-` followed by a six-digit zero-padded ordinal that is the listing's position among all listed listings ordered by ascending `created_at`; the number is minted only on the **first** listing decision, so a product that is later suspended and restored, or delisted and re-registered, keeps the number it was first given."

        Design: Corner/state_machines/listing_return_then_resubmit_releases_and_restores_the_designation_slot
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={
                "facility_name": "Aster Labs Newark",
                "owner_operator_name": "Aster Holdings LLC",
            },
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )

        submitted = get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
        assert submitted["listing_number"] is None

        returned = get_success_data(
            api.decide_listing(
                bundle["listing_id"],
                F.listing_decision_payload("RETURN", decision_note="Clarify the credential"),
                REVIEWER_HEADERS,
            )
        )
        assert returned["listing_status"] == K.LISTING_STATUS_RETURNED
        assert returned["listing_number"] is None

        resubmitted = get_success_data(
            api.submit_listing(bundle["listing_id"], bundle["agent"])
        )
        assert resubmitted["listing_number"] is None
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 0


def _world_sitting_in_five_wrong_states(api):
    """One built world in which five transition endpoints are all inadmissible.

    The listing is LISTED (so no listing decision is due), its dossier ADEQUATE
    (so no review decision is due), the engagement merely SCHEDULED (so no
    response is due), the recall PLAN_ACCEPTED (so no plan decision is due) and
    the withdrawal still OPEN with its records unproduced.
    """
    bundle = _cleared_dossier_listed_product(api, lot_authorized_units=5000)
    bundle["inspection"] = X.schedule_inspection(
        api, bundle["facility_id"], "2026-09-01", "2026-09-04"
    )
    bundle["record"] = X.create_distribution_records(
        api, bundle["listing_id"], bundle["agent"],
        [{"lot_code": "LOT-A", "ship_date": "2026-08-05", "delivery_date": "2026-08-07",
          "units_shipped": 600}],
    )[0]
    bundle["recall"] = X.recall_with_accepted_plan(
        api, bundle["listing_id"], bundle["agent"],
        initiation_basis=K.INITIATION_BASIS_MANDATORY, officer=OFFICER_HEADERS,
    )
    bundle["withdrawal"] = X.open_withdrawal(
        api, bundle["recall"], OFFICER_HEADERS, K.DEPTH_WHOLESALE
    )
    return bundle


class TestEachMachineReportsItsOwnStateRefusal:
    """Five inadmissible calls, five entity-specific conflicts, no generic one."""

    def test_the_register_and_the_safety_file_each_name_their_own_conflict(self, api):
        """A product already on the register admits no further listing decision, and a dossier
        already scored admits no second review decision — and the two refusals are told apart
        by their identifiers rather than by a shared conflict code.

        PRD: "Either way the listing's `listing_status` must be `SUBMITTED`, and the decision call is refused with `ERR_FACILITY_POSTURE_FROZEN` when the governing establishment's `compliance_posture` is `FROZEN`."
        PRD: "The decision requires the dossier's `status` to be `SUBMITTED`."
        PRD: "11. The per-entity state-admissibility checks, in this order: `ERR_INVALID_FACILITY_STATE`, `ERR_INVALID_OWNERSHIP_CHANGE_STATE`, `ERR_INVALID_LISTING_STATE`, `ERR_INVALID_SUBSTANTIATION_STATE`, `ERR_INVALID_ADVERSE_EVENT_STATE`, `ERR_INVALID_INSPECTION_STATE`, `ERR_INVALID_RECALL_STATE`, `ERR_INVALID_WITHDRAWAL_STATE`."

        Design: Corner/state_machines/invalid_from_state_rejections_across_five_entity_state_gates
        """
        bundle = _world_sitting_in_five_wrong_states(api)

        validate_error(
            api.decide_listing(
                bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
            ),
            E.ERR_INVALID_LISTING_STATE,
        )
        validate_error(
            api.decide_substantiation_review(
                bundle["dossier_id"],
                F.review_decision_payload(K.REVIEW_MODE_FULL),
                REVIEWER_HEADERS,
            ),
            E.ERR_INVALID_SUBSTANTIATION_STATE,
        )

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED
        A.assert_listing_number_format(listing["listing_number"], 1)
        assert X.read_substantiation(api, bundle["dossier_id"])["status"] == (
            K.SUBSTANTIATION_STATUS_ADEQUATE
        )

    def test_an_unobserved_engagement_and_an_accepted_plan_refuse_their_next_hop(self, api):
        """Answering findings that were never issued is a state objection, not a window one, so
        the response-window rule is never consulted; and an accepted plan gives the agency no
        second bite at the decision.

        PRD: "The engagement's `status` must be `OBSERVATIONS_ISSUED`, or the attempt is `ERR_INVALID_INSPECTION_STATE`, and the logical clock must be at or before `response_due_at`, or it is refused with `ERR_INSPECTION_RESPONSE_WINDOW_CLOSED` (HTTP 422) — the window is inclusive of its final millisecond."
        PRD: "An `EnforcementOfficer` then disposes of the submitted plan with a `decision` of `ACCEPT` or `REJECT` and an optional `decision_note`; the recall's `status` must be `PLAN_SUBMITTED`, or the call is refused with `ERR_INVALID_RECALL_STATE` (HTTP 409)."

        Design: Corner/state_machines/invalid_from_state_rejections_across_five_entity_state_gates
        """
        bundle = _world_sitting_in_five_wrong_states(api)

        validate_error(
            api.submit_inspection_response(
                bundle["facility_id"], bundle["inspection"]["id"],
                F.inspection_response_payload(), bundle["registrant"],
            ),
            E.ERR_INVALID_INSPECTION_STATE,
        )
        validate_error(
            api.decide_recall_plan(
                bundle["recall"]["id"],
                F.plan_decision_payload("REJECT", decision_note="A second bite"),
                OFFICER_HEADERS,
            ),
            E.ERR_INVALID_RECALL_STATE,
        )

        engagement = X.read_inspection(
            api, bundle["facility_id"], bundle["inspection"]["id"]
        )
        assert engagement["status"] == K.INSPECTION_STATUS_SCHEDULED
        assert engagement["response_submitted_at"] is None
        assert engagement["response_summary"] is None

        recall = X.read_recall(api, bundle["recall"]["id"])
        assert recall["status"] == K.RECALL_STATUS_EXECUTING

    def test_the_withdrawal_state_gate_outranks_the_record_linkage_check(self, api):
        """The round has produced no paperwork, so the named record is not linked to it either
        — yet the state objection is reported, because per-entity state admissibility is
        settled before any referential check.

        PRD: "11. The per-entity state-admissibility checks, in this order: `ERR_INVALID_FACILITY_STATE`, `ERR_INVALID_OWNERSHIP_CHANGE_STATE`, `ERR_INVALID_LISTING_STATE`, `ERR_INVALID_SUBSTANTIATION_STATE`, `ERR_INVALID_ADVERSE_EVENT_STATE`, `ERR_INVALID_INSPECTION_STATE`, `ERR_INVALID_RECALL_STATE`, `ERR_INVALID_WITHDRAWAL_STATE`."
        PRD: "16. The referential checks, in this order: `ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH`, `ERR_RECORD_NOT_IN_WITHDRAWAL`, `ERR_NO_DISTRIBUTION_RECORDS`."

        Design: Corner/state_machines/invalid_from_state_rejections_across_five_entity_state_gates
        """
        bundle = _world_sitting_in_five_wrong_states(api)
        assert bundle["withdrawal"]["status"] == K.WITHDRAWAL_STATUS_OPEN

        validate_error(
            api.post_recovery_entry(
                bundle["withdrawal"]["id"],
                F.recovery_entry_payload(
                    bundle["record"]["id"], 100, K.ENTRY_KIND_VERIFIED_RETURN
                ),
                bundle["agent"],
            ),
            E.ERR_INVALID_WITHDRAWAL_STATE,
        )

        record = X.read_record(api, bundle["record"]["id"])
        assert record["units_verified_returned"] == 0
        assert record["units_outstanding"] == 600
        assert record["withdrawal_id"] is None
        A.assert_record_unit_balance(record)


class TestSupersessionLocksOneDossierAndFreesTheNext:
    """The lockdown is per row: the old file is sealed, the new one runs.""" 

    def test_filing_a_fresh_file_seals_the_cleared_one_and_resets_the_product(self, api):
        """The newest dossier is the only live one, so opening it drives its predecessor to a
        terminal state and takes the product's safety dimension back to the beginning.

        PRD: "Every dossier of that listing whose `status` is not already `SUPERSEDED` moves to `SUPERSEDED`, which is terminal: neither a further submission nor a review decision is ever accepted on a superseded dossier."

        Design: Corner/state_machines/superseded_substantiation_cannot_be_resubmitted_or_re_decided
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={
                "facility_name": "Aster Labs Newark",
                "owner_operator_name": "Aster Holdings LLC",
            },
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        first = X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )
        assert first["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE

        X.open_dossier(
            api, bundle["listing_id"], bundle["agent"],
            assessor_name="Dr. Noor Alvarez",
            assessment_basis=K.ASSESSMENT_BASIS_INGREDIENT_READ_ACROSS,
        )

        assert X.read_substantiation(api, first["id"])["status"] == (
            K.SUBSTANTIATION_STATUS_SUPERSEDED
        )
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
        assert listing["marketable"] is False

    def test_the_sealed_file_refuses_a_submission_and_any_reviewer_s_decision(self, api):
        """Both edges out of the superseded row are closed, and swapping in a second reviewer
        changes nothing — the objection is the row's state, not who is asking.

        PRD: "Submitting the dossier for review carries no payload and is admissible from `DRAFT`, `DEFICIENT` or `REVALIDATION_REQUIRED`; from `SUBMITTED`, `ADEQUATE` or `SUPERSEDED` it is `ERR_INVALID_SUBSTANTIATION_STATE`."

        Design: Corner/state_machines/superseded_substantiation_cannot_be_resubmitted_or_re_decided
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={
                "facility_name": "Aster Labs Newark",
                "owner_operator_name": "Aster Holdings LLC",
            },
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        first = X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )
        X.open_dossier(
            api, bundle["listing_id"], bundle["agent"],
            assessor_name="Dr. Noor Alvarez",
            assessment_basis=K.ASSESSMENT_BASIS_INGREDIENT_READ_ACROSS,
        )

        validate_error(
            api.submit_substantiation(first["id"], bundle["agent"]),
            E.ERR_INVALID_SUBSTANTIATION_STATE,
        )
        validate_error(
            api.decide_substantiation_review(
                first["id"],
                F.review_decision_payload(K.REVIEW_MODE_SCREENING),
                REVIEWER_2_HEADERS,
            ),
            E.ERR_INVALID_SUBSTANTIATION_STATE,
        )

    def test_the_successor_transitions_normally_and_the_audit_trail_survives(self, api):
        """The new row takes the ordinary submission edge into its first review round while the
        sealed row keeps the score and the reviewer identity it was decided with.

        PRD: "A successful submission moves the dossier to `SUBMITTED`, increments `revision_round` by exactly 1 — it counts every entry into `SUBMITTED`, including re-submissions after a deficiency or a revalidation demand, and ranges from 0 to 99 — sets the listing's `safety_status` to `UNDER_SUBSTANTIATION`, refreshes `data_gap_present` from the listing's current ingredient set, recomputes `marketable`, and increments both the dossier's `version` and the listing's `version` by 1."

        Design: Corner/state_machines/superseded_substantiation_cannot_be_resubmitted_or_re_decided
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={
                "facility_name": "Aster Labs Newark",
                "owner_operator_name": "Aster Holdings LLC",
            },
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        first = X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )
        second = X.open_dossier(
            api, bundle["listing_id"], bundle["agent"],
            assessor_name="Dr. Noor Alvarez",
            assessment_basis=K.ASSESSMENT_BASIS_INGREDIENT_READ_ACROSS,
        )
        X.attach_items(
            api, second["id"], bundle["agent"],
            [(K.EVIDENCE_READ_ACROSS, K.CREDENTIAL_QSA)],
        )

        submitted = X.submit_dossier(api, second["id"], bundle["agent"])

        assert submitted["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
        assert submitted["revision_round"] == 1
        assert X.read_listing(api, bundle["listing_id"])["safety_status"] == (
            K.SAFETY_STATUS_UNDER_SUBSTANTIATION
        )

        sealed = X.read_substantiation(api, first["id"])
        A.assert_two_decimal_value(sealed["adequacy_score"], 65.00, "adequacy_score")
        assert sealed["full_reviewer_user_id"] == "RVW-1"
        assert sealed["review_mode"] == K.REVIEW_MODE_FULL


class TestAcceptedOwnershipFilingRenamesTheEstablishment:
    """The ACCEPT edge reaches across into the establishment row itself."""

    def test_the_filing_derives_a_sixty_day_deadline_and_is_not_late(self, api):
        """Filed on the effective date itself, the filing's deadline lands at the very end of
        the sixtieth day after it and the lateness flag is false.

        PRD: "The new filing starts in `status` `FILED`, records the establishment through its `facility_id`, stamps `filed_at` with the logical-clock instant at which the server accepted it, and derives `filing_deadline_at` as the end of the day 60 days after `change_effective_date` — that is, the instant 23:59:59.999Z on that day, so a filing made at any point during the deadline day is on time."
        PRD: "The boolean `is_late_filing` is true exactly when `filed_at` is strictly after `filing_deadline_at`, and false otherwise, including the boundary case where the two are equal."

        Design: Corner/state_machines/accepted_ownership_change_renames_the_owner_and_clears_abbreviated_eligibility
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        registrant = make_facility_registrant_headers(facility["id"])

        filing = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(
                    facility["version"],
                    change_effective_date="2026-08-01",
                    new_owner_operator_name="Meridian Personal Care Holdings",
                ),
                registrant,
            )
        )

        assert filing["status"] == "FILED"
        assert filing["facility_id"] == facility["id"]
        assert filing["filed_at"] == K.DEFAULT_CLOCK_UTC
        A.assert_deadline_at_end_of_day(filing["filing_deadline_at"], "2026-09-30")
        assert filing["is_late_filing"] is False
        assert filing["decision_note"] is None
        assert filing["decided_by_user_id"] is None
        assert X.read_facility(api, facility["id"])["version"] == facility["version"] + 1

    def test_acceptance_renames_the_owner_and_closes_the_abbreviated_path(self, api):
        """One ruling writes across two rows: the establishment takes the incoming owner's
        name and loses its abbreviated eligibility, the filing records the reviewer who ruled,
        and the establishment's version has moved twice — once for the filing, once for this.

        PRD: "`FILED → ACCEPTED` overwrites the establishment's `owner_operator_name` with `new_owner_operator_name`, sets `abbreviated_renewal_eligible` to false, appends an `OWNERSHIP_CHANGE` ledger entry whose `subject_entity` is `OwnershipChangeUpdate` and whose `subject_id` is the filing, and increments both the filing's `version` and the establishment's `version` by exactly 1."
        PRD: "Both rulings store the supplied `decision_note` and capture the deciding reviewer's `X-User-ID` in `decided_by_user_id`."

        Design: Corner/state_machines/accepted_ownership_change_renames_the_owner_and_clears_abbreviated_eligibility
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        registrant = make_facility_registrant_headers(facility["id"])
        assert facility["abbreviated_renewal_eligible"] is True

        filing = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(
                    facility["version"],
                    change_effective_date="2026-08-01",
                    new_owner_operator_name="Meridian Personal Care Holdings",
                ),
                registrant,
            )
        )
        decided = get_success_data(
            api.decide_ownership_change(
                filing["id"],
                F.ownership_decision_payload("ACCEPT", decision_note="Stock purchase verified"),
                REVIEWER_HEADERS,
            )
        )

        assert decided["status"] == "ACCEPTED"
        assert decided["decided_by_user_id"] == "RVW-1"
        assert decided["decision_note"] == "Stock purchase verified"

        after = X.read_facility(api, facility["id"])
        assert after["owner_operator_name"] == "Meridian Personal Care Holdings"
        assert after["abbreviated_renewal_eligible"] is False
        assert after["version"] == facility["version"] + 2

        entries = X.ledger_entries(api, facility["id"], K.ENTRY_TYPE_OWNERSHIP_CHANGE)
        assert len(entries) == 1
        assert entries[0]["subject_entity"] == "OwnershipChangeUpdate"
        assert entries[0]["subject_id"] == filing["id"]

    def test_the_coverage_cycle_is_untouched_by_the_change_of_hands(self, api):
        """An ownership change is not a registration event: the establishment stays registered
        on the very same coverage window it already held.

        PRD: "The establishment mirrors the currently active period so that clients need not join: `current_period_start` and `current_period_end` copy the active period's bounds, and `renewal_window_open_date` and `grace_end_date` copy its two derived dates."
        PRD: "A change of ownership mid-period is therefore enough to force the establishment down the `STANDARD` path for the remainder of that period, and so is any posture escalation, since a `RESTRICTED` or `FROZEN` establishment is never abbreviated-eligible."

        Design: Corner/state_machines/accepted_ownership_change_renames_the_owner_and_clears_abbreviated_eligibility
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        registrant = make_facility_registrant_headers(facility["id"])
        filing = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(
                    facility["version"], change_effective_date="2026-08-01",
                    new_owner_operator_name="Meridian Personal Care Holdings",
                ),
                registrant,
            )
        )
        get_success_data(
            api.decide_ownership_change(
                filing["id"], F.ownership_decision_payload("ACCEPT"), REVIEWER_HEADERS
            )
        )

        after = X.read_facility(api, facility["id"])
        assert after["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        A.assert_facility_period_mirror(
            after, facility["current_period_start"], facility["current_period_end"],
            facility["renewal_window_open_date"], facility["grace_end_date"],
        )


NAI_BOUNDARY_OBSERVATIONS = 5
CAPPED_CRITICAL_OBSERVATIONS = 12


class TestTheCleanCloseForkNeverOpensAResponseWindow:
    """One observations call ends the engagement outright at the inclusive boundary."""

    def test_five_major_recordkeeping_findings_score_exactly_the_clean_threshold(self, api):
        """Fifteen deduction points in the heaviest category leave that subscore at 50.00 and
        every other category untouched at 100.00, and the five rounded weighted terms add to
        exactly the clean-close threshold.

        PRD: "Step three multiplies each subscore by that category's weight — `PERSONNEL` 0.15, `PREMISES` 0.20, `EQUIPMENT` 0.15, `RAW_MATERIALS` 0.20 and `RECORDKEEPING` 0.30, weights that sum to exactly 1.00, with recordkeeping deliberately the heaviest because documentation failures are the most predictive of the rest — **and rounds each of the five weighted terms to two decimals before any of them are added**."
        PRD: "All five categories are scored, including those with no findings at all, which score 100.00; a category with twelve critical findings has 72 deduction points, is capped at 30, and scores 0.00 — the cap means a catastrophic category cannot drag the whole engagement below its own weight."

        Design: Corner/state_machines/inspection_nai_fork_closes_immediately_with_no_response_window
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        engagement = X.schedule_inspection(api, facility["id"], "2026-09-01", "2026-09-04")

        scored = X.issue_observations(
            api, facility["id"], engagement["id"],
            F.repeated_observations("RECORDKEEPING", K.SEVERITY_MAJOR, NAI_BOUNDARY_OBSERVATIONS),
        )

        A.assert_two_decimal_value(scored["readiness_score"], 85.00, "readiness_score")
        assert scored["observation_count"] == NAI_BOUNDARY_OBSERVATIONS
        A.assert_category_subscores(
            scored["category_subscores"],
            {"PERSONNEL": 100.00, "PREMISES": 100.00, "EQUIPMENT": 100.00,
             "RAW_MATERIALS": 100.00, "RECORDKEEPING": 50.00},
        )

    def test_the_engagement_closes_clean_and_asks_for_nothing(self, api):
        """85.00 is inclusive of the clean-close threshold, so the engagement is over at once:
        the outcome is recorded, no response window opens, and the establishment takes both the
        score and the outcome immediately.

        PRD: "At 85.00 or above the engagement takes `SCHEDULED → CLOSED_NAI` and is over: `outcome_class` becomes `NAI`, `response_due_at` stays null because no response will be asked for, the establishment's `gmp_readiness_score` and `last_inspection_outcome` are both set — the latter to `NAI` — and one `INSPECTION_OUTCOME` ledger entry is appended."

        Design: Corner/state_machines/inspection_nai_fork_closes_immediately_with_no_response_window
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        engagement = X.schedule_inspection(api, facility["id"], "2026-09-01", "2026-09-04")

        scored = X.issue_observations(
            api, facility["id"], engagement["id"],
            F.repeated_observations("RECORDKEEPING", K.SEVERITY_MAJOR, NAI_BOUNDARY_OBSERVATIONS),
        )

        assert scored["status"] == K.INSPECTION_STATUS_CLOSED_NAI
        assert scored["outcome_class"] == K.OUTCOME_CLASS_NAI
        assert scored["response_due_at"] is None
        assert scored["response_submitted_at"] is None
        assert scored["response_summary"] is None

        after = X.read_facility(api, facility["id"])
        A.assert_two_decimal_value(after["gmp_readiness_score"], 85.00, "gmp_readiness_score")
        assert after["last_inspection_outcome"] == K.OUTCOME_CLASS_NAI
        assert after["compliance_posture"] == K.POSTURE_OPEN

        entries = X.ledger_entries(api, facility["id"], K.ENTRY_TYPE_INSPECTION_OUTCOME)
        assert len(entries) == 1
        assert entries[0]["subject_id"] == engagement["id"]


class TestTheResponseWindowIsClosedOnTheFollowingMillisecond:
    """The answering guard is a clock comparison, inclusive of its final millisecond."""

    def _engagement_awaiting_a_response(self, api):
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
            state_or_province="NJ",
        )
        engagement = X.schedule_inspection(api, facility["id"], "2026-09-01", "2026-09-04")
        X.set_clock(api, "2026-09-02T09:00:00Z")
        scored = X.issue_observations(
            api, facility["id"], engagement["id"],
            F.repeated_observations("PREMISES", K.SEVERITY_CRITICAL, CAPPED_CRITICAL_OBSERVATIONS),
        )
        return facility, scored

    def test_a_capped_category_scores_eighty_and_opens_a_fifteen_day_window(self, api):
        """Seventy-two deduction points are capped at thirty, so the worst possible premises
        category costs only its own weight and the engagement scores 80.00 — below the clean
        threshold, so a response is asked for by the end of the fifteenth day after issuance.

        PRD: "Below 85.00 the engagement takes `SCHEDULED → OBSERVATIONS_ISSUED`: `response_due_at` is set to the logical clock plus fifteen days, pinned to 23:59:59.999Z of that day, `outcome_class` is set to the non-terminal marker `PENDING_RESPONSE` rather than to any final classification, the establishment's `gmp_readiness_score` is updated, and — this is the part that is easy to get wrong — the establishment's `last_inspection_outcome` is **left alone**, because no outcome has been reached yet."

        Design: Corner/state_machines/inspection_response_after_the_due_instant_is_rejected
        """
        facility, scored = self._engagement_awaiting_a_response(api)

        A.assert_two_decimal_value(scored["readiness_score"], 80.00, "readiness_score")
        assert scored["observation_count"] == CAPPED_CRITICAL_OBSERVATIONS
        A.assert_two_decimal_value(
            scored["category_subscores"]["PREMISES"], 0.00, "category_subscores.PREMISES"
        )
        assert scored["status"] == K.INSPECTION_STATUS_OBSERVATIONS_ISSUED
        assert scored["outcome_class"] == K.OUTCOME_CLASS_PENDING_RESPONSE
        A.assert_deadline_at_end_of_day(scored["response_due_at"], "2026-09-17")

        after = X.read_facility(api, facility["id"])
        A.assert_two_decimal_value(after["gmp_readiness_score"], 80.00, "gmp_readiness_score")
        assert after["last_inspection_outcome"] is None

    def test_one_millisecond_past_the_due_instant_the_answer_is_refused(self, api):
        """Midnight on the day after the deadline day is past the window's final millisecond,
        so the answer is refused and the engagement keeps waiting with nothing recorded on it.

        PRD: "The engagement's `status` must be `OBSERVATIONS_ISSUED`, or the attempt is `ERR_INVALID_INSPECTION_STATE`, and the logical clock must be at or before `response_due_at`, or it is refused with `ERR_INSPECTION_RESPONSE_WINDOW_CLOSED` (HTTP 422) — the window is inclusive of its final millisecond."

        Design: Corner/state_machines/inspection_response_after_the_due_instant_is_rejected
        """
        facility, scored = self._engagement_awaiting_a_response(api)
        X.set_clock(api, "2026-09-18T00:00:00Z")

        validate_error(
            api.submit_inspection_response(
                facility["id"], scored["id"], F.inspection_response_payload(),
                make_facility_registrant_headers(facility["id"]),
            ),
            E.ERR_INSPECTION_RESPONSE_WINDOW_CLOSED,
        )

        stored = X.read_inspection(api, facility["id"], scored["id"])
        assert stored["status"] == K.INSPECTION_STATUS_OBSERVATIONS_ISSUED
        assert stored["response_submitted_at"] is None
        assert stored["response_summary"] is None
        assert X.read_facility(api, facility["id"])["last_inspection_outcome"] is None


class TestSilenceEscalatesTheEngagementWhateverItScored:
    """The third closing edge is the sweep's, and it ignores the stored score."""

    def _unanswered_engagement_over_a_marketed_product(self, api):
        bundle = _cleared_dossier_listed_product(api)
        engagement = X.schedule_inspection(api, bundle["facility_id"], "2026-09-01", "2026-09-04")
        X.set_clock(api, "2026-09-02T09:00:00Z")
        X.issue_observations(
            api, bundle["facility_id"], engagement["id"],
            F.repeated_observations("PREMISES", K.SEVERITY_CRITICAL, CAPPED_CRITICAL_OBSERVATIONS),
        )
        X.set_clock(api, "2026-09-18T00:00:00Z")
        bundle["engagement_id"] = engagement["id"]
        return bundle

    def test_the_sweep_escalates_the_unanswered_engagement_rather_than_closing_it(self, api):
        """80.00 is comfortably above the closing threshold that would have produced a
        blemished-but-closed outcome, yet the engagement escalated instead, because that branch
        is reserved for engagements that actually answered.

        PRD: "An engagement still in `OBSERVATIONS_ISSUED` when the logical clock passes `response_due_at` takes `OBSERVATIONS_ISSUED → ESCALATED_OAI` on the sweep, with a cascade identical to the one above — **regardless of how high its `readiness_score` was**."
        PRD: "An engagement in `RESPONSE_SUBMITTED` closes `CLOSED_VAI` when its `readiness_score` is 70.00 or more, counted in `closed_vai_count`, or escalates to `ESCALATED_OAI` when it is below that, counted in `escalated_oai_count`."

        Design: Corner/state_machines/unanswered_observations_escalate_to_oai_on_the_sweep_and_revalidate_the_dossier
        """
        bundle = self._unanswered_engagement_over_a_marketed_product(api)

        counters = X.run_sweep(api)

        A.assert_sweep_counters(
            counters, escalated_oai_count=1, closed_vai_count=0, revalidation_required_count=1
        )

        engagement = X.read_inspection(api, bundle["facility_id"], bundle["engagement_id"])
        assert engagement["status"] == K.INSPECTION_STATUS_ESCALATED_OAI
        assert engagement["outcome_class"] == K.OUTCOME_CLASS_OAI
        A.assert_two_decimal_value(engagement["readiness_score"], 80.00, "readiness_score")

    def test_the_escalation_forces_the_posture_up_on_zero_points(self, api):
        """No adverse event has ever been recorded, so the points reading is still the mildest
        one available; the posture is raised anyway, by the override reading alone.

        PRD: "The **override reading** is `FROZEN` when the establishment's `registration_status` is `LAPSED`, or when any recall action anywhere under the establishment's listings has reached `ESCALATED_MANDATORY`; it is `RESTRICTED` when any inspection engagement of the establishment has reached `ESCALATED_OAI`; and it is `OPEN` otherwise."
        PRD: "An establishment sitting at zero points with a single `ESCALATED_OAI` engagement is therefore `RESTRICTED`, and an establishment at zero points with a single `ESCALATED_MANDATORY` recall is `FROZEN`."

        Design: Corner/state_machines/unanswered_observations_escalate_to_oai_on_the_sweep_and_revalidate_the_dossier
        """
        bundle = self._unanswered_engagement_over_a_marketed_product(api)
        X.run_sweep(api)

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")
        assert facility["last_inspection_outcome"] == K.OUTCOME_CLASS_OAI
        assert facility["compliance_posture"] == K.POSTURE_RESTRICTED

    def test_the_cascade_invalidates_the_safety_file_without_unlisting_the_product(self, api):
        """The dossier and the product's safety dimension both fall to revalidation, but the
        register entry itself is untouched: the product keeps its status, its number and its
        place in the establishment's count.

        PRD: "hops 3 and 4 are the familiar revalidation chain, moving every `ADEQUATE` dossier of the establishment to `REVALIDATION_REQUIRED` and each such listing's `safety_status` to `REVALIDATION_REQUIRED` with `marketable` false."
        PRD: "The ledger takes an `INSPECTION_OUTCOME` entry, then a `POSTURE_CHANGE` entry, then one `STATE_TRANSITION` entry per revalidated listing."

        Design: Corner/state_machines/unanswered_observations_escalate_to_oai_on_the_sweep_and_revalidate_the_dossier
        """
        bundle = self._unanswered_engagement_over_a_marketed_product(api)
        X.run_sweep(api)

        assert X.read_substantiation(api, bundle["dossier_id"])["status"] == (
            K.SUBSTANTIATION_STATUS_REVALIDATION_REQUIRED
        )
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_REVALIDATION_REQUIRED
        assert listing["marketable"] is False
        assert listing["listing_status"] == K.LISTING_STATUS_LISTED
        A.assert_listing_number_format(listing["listing_number"], 1)
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

        entries = X.ledger_entries(api, bundle["facility_id"])
        tail = [
            e for e in entries
            if e["entry_type"] in (K.ENTRY_TYPE_INSPECTION_OUTCOME, K.ENTRY_TYPE_POSTURE_CHANGE)
        ]
        A.assert_entry_types_in_order(
            tail, [K.ENTRY_TYPE_INSPECTION_OUTCOME, K.ENTRY_TYPE_POSTURE_CHANGE]
        )
        A.assert_posture_change_entry(tail[1], K.POSTURE_OPEN, K.POSTURE_RESTRICTED)
        assert entries[-1]["entry_type"] == K.ENTRY_TYPE_STATE_TRANSITION
        assert entries[-1]["subject_id"] == bundle["listing_id"]


def _consumer_listing_with_a_serious_event(api):
    """A serious event received 2026-08-05, so its report falls due 2026-08-20."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Aster Labs Newark",
            "owner_operator_name": "Aster Holdings LLC",
            "state_or_province": "NJ",
        },
        person_overrides={"legal_name": "Aster Brands Inc"},
        listing_overrides={
            "product_name": "Aster Blush Powder",
            "category_code": "07A",
            "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            "label_contact_value": "safety@aster.example",
        },
    )
    X.set_clock(api, "2026-08-05T08:00:00Z")
    bundle["event"] = X.record_serious_event(
        api, bundle["listing_id"], bundle["agent"], "2026-08-05T00:00:00Z",
        event_description="Periorbital dermatitis after single use",
        outcome_code="SERIOUS_PERSISTENT",
    )
    return bundle


class TestTheReportDeadlineIsInclusiveToTheMillisecond:
    """Filing on the deadline's own final millisecond is on time, not late."""

    def test_the_serious_intake_pins_its_deadline_to_the_fifteenth_day_end(self, api):
        """The basis is the receipt instant, the deadline is the last millisecond of the
        fifteenth day after it, and the file is kept for the longer serious term measured from
        receipt rather than from the deadline.

        PRD: "**The fifteen-day clock.** The report deadline is the end of the fifteenth day after the day of the basis instant: take the calendar date of `deadline_basis_at`, add fifteen days, and pin the result to 23:59:59.999Z."
        PRD: "A `SERIOUS` intake takes the `RECORDED → REPORT_DUE` edge: `deadline_basis_at` becomes `received_at`, `deadline_at` is computed from it, `retention_until` becomes the calendar date of `received_at` plus six years, and both the listing's and the establishment's `open_serious_event_count` rise by 1."

        Design: Corner/state_machines/serious_event_reported_at_the_deadline_instant_scores_the_timely_base
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        event = bundle["event"]

        assert event["report_status"] == K.EVENT_STATUS_REPORT_DUE
        assert event["deadline_basis_at"] == "2026-08-05T00:00:00Z"
        A.assert_deadline_at_end_of_day(event["deadline_at"], "2026-08-20")
        assert event["retention_until"] == "2032-08-05"
        A.assert_two_decimal_value(event["event_points"], 0.00, "event_points")

        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 1
        assert X.read_listing(api, bundle["listing_id"])["open_serious_event_count"] == 1

    def test_filing_on_the_final_millisecond_scores_the_timely_base(self, api):
        """The clock stands exactly on the deadline, so the filing is timely with no lateness
        at all and the event costs the establishment the cheapest of the three bases.

        PRD: "The deadline is inclusive: a filing whose `submitted_at` equals `deadline_at` to the millisecond is timely."
        PRD: "The base is 2 for a timely report, 5 for a late one and 9 for a report that is overdue and still unfiled — the unfiled state is deliberately the most expensive of the three."

        Design: Corner/state_machines/serious_event_reported_at_the_deadline_instant_scores_the_timely_base
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-20T23:59:59.999Z")

        filed = get_success_data(
            api.file_adverse_event_report(
                bundle["event"]["id"], bundle["agent"], F.report_payload()
            )
        )

        assert filed["report_status"] == K.EVENT_STATUS_REPORTED_TIMELY
        assert filed["submitted_at"] == "2026-08-20T23:59:59.999Z"
        assert filed["lateness_days"] == 0
        A.assert_two_decimal_value(filed["event_points"], 2.00, "event_points")

    def test_the_timely_filing_clears_the_counter_and_leaves_the_dial_alone(self, api):
        """Two points is far below the first escalation threshold, so the establishment carries
        the cost without moving its posture, the open obligation is discharged, and the ledger
        holds the single report fact.

        PRD: "A timely filing does the same bookkeeping minus the escalation: `submitted_at`, zero lateness, points on the timely base, both counters decremented, the establishment's points and posture recomputed, and one `ADVERSE_EVENT_REPORT` ledger entry."

        Design: Corner/state_machines/serious_event_reported_at_the_deadline_instant_scores_the_timely_base
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-20T23:59:59.999Z")
        X.file_report(api, bundle["event"]["id"], bundle["agent"])

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 2.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        assert facility["open_serious_event_count"] == 0

        rows, meta = validate_paginated(
            api.list_adverse_events(
                bundle["listing_id"], bundle["agent"],
                {"report_status": K.EVENT_STATUS_REPORTED_TIMELY},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == bundle["event"]["id"]

        entries = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_ADVERSE_EVENT_REPORT)
        assert len(entries) == 1
        assert entries[0]["subject_id"] == bundle["event"]["id"]


class TestTheOverdueBaseIsDearerThanTheLateBase:
    """The same event, scored twice, moves the dial up and then back down."""

    def test_the_sweep_prices_the_unfiled_event_on_the_overdue_base(self, api):
        """Two days past the deadline and still unfiled, the event is priced on the dearest
        base at the two-day lateness factor, which alone is enough to escalate the posture.

        PRD: "The sweep sets `lateness_days` from the clock exactly as a filing would, computes `event_points` on the overdue base of 9, and then runs the identical hop-2-through-hop-4 chain of points, posture, substantiation and listing."
        PRD: "The lateness factor is one plus a tenth per day of lateness, capped at 2.0, so lateness stops accruing at ten days."

        Design: Corner/state_machines/overdue_sweep_then_catch_up_filing_lowers_points_and_de_escalates_posture
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-22T00:00:00Z")

        counters = X.run_sweep(api)
        A.assert_sweep_counters(counters, overdue_event_count=1)

        rows, _meta = validate_paginated(
            api.list_adverse_events(bundle["listing_id"], bundle["agent"])
        )
        swept = rows[0]
        assert swept["report_status"] == K.EVENT_STATUS_REPORT_OVERDUE
        assert swept["lateness_days"] == 2
        A.assert_two_decimal_value(swept["event_points"], 10.80, "event_points")

    def test_the_overdue_marking_escalates_yet_keeps_the_obligation_open(self, api):
        """10.80 is at or above the first threshold so the establishment is restricted, and the
        event still counts as an open obligation because nothing has been reported.

        PRD: "What it pointedly does **not** do is move `open_serious_event_count`: the event is still unreported and must keep showing up as an open obligation."

        Design: Corner/state_machines/overdue_sweep_then_catch_up_filing_lowers_points_and_de_escalates_posture
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-22T00:00:00Z")
        X.run_sweep(api)

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 10.80, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_RESTRICTED
        assert facility["open_serious_event_count"] == 1

    def test_the_catch_up_filing_lowers_the_price_and_de_escalates(self, api):
        """Filing the overdue event re-prices it on the cheaper late base at the very same
        lateness, which takes the total back under the threshold, so the posture falls again
        and the obligation is finally discharged.

        PRD: "**Catching up.** An overdue event can still be filed, taking the `REPORT_OVERDUE → REPORTED_LATE` edge. This recomputes `event_points` on the late base of 5 instead of the overdue base of 9, which for identical lateness strictly **lowers** the contribution — the 17.10 of the example above becomes 9.50 — and then recomputes `serious_event_points` and `compliance_posture`, at which point a de-escalation from `RESTRICTED` back to `OPEN` is entirely possible."

        Design: Corner/state_machines/overdue_sweep_then_catch_up_filing_lowers_points_and_de_escalates_posture
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-22T00:00:00Z")
        X.run_sweep(api)

        filed = X.file_report(api, bundle["event"]["id"], bundle["agent"])

        assert filed["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert filed["lateness_days"] == 2
        A.assert_two_decimal_value(filed["event_points"], 6.00, "event_points")

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 6.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        assert facility["open_serious_event_count"] == 0

    def test_both_directions_of_the_dial_are_recorded_in_the_ledger(self, api):
        """The breach and the eventual report each leave their own fact, and the posture entries
        book the escalation and the de-escalation in the order they happened.

        PRD: "One `DEADLINE_BREACH` ledger entry is appended per event swept."
        PRD: "The ledger records this in a fixed order: one `ADVERSE_EVENT_REPORT` entry against the event, then — only when the posture actually changed — one `POSTURE_CHANGE` entry carrying the before and after values, then one `STATE_TRANSITION` entry per revalidated listing."

        Design: Corner/state_machines/overdue_sweep_then_catch_up_filing_lowers_points_and_de_escalates_posture
        """
        bundle = _consumer_listing_with_a_serious_event(api)
        X.set_clock(api, "2026-08-22T00:00:00Z")
        X.run_sweep(api)
        X.file_report(api, bundle["event"]["id"], bundle["agent"])

        breaches = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_DEADLINE_BREACH)
        assert len(breaches) == 1
        assert breaches[0]["subject_id"] == bundle["event"]["id"]

        reports = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_ADVERSE_EVENT_REPORT)
        assert len(reports) == 1
        assert reports[0]["sequence_no"] > breaches[0]["sequence_no"]

        postures = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_POSTURE_CHANGE)
        assert len(postures) == 2
        A.assert_posture_change_entry(postures[0], K.POSTURE_OPEN, K.POSTURE_RESTRICTED)
        A.assert_posture_change_entry(postures[1], K.POSTURE_RESTRICTED, K.POSTURE_OPEN)


PRODUCED_LOT_UNITS = 600


class TestASuccessorRoundCompensatesItsPredecessor:
    """The second round releases what the first produced instead of deleting it."""

    def _first_round_with_its_records_produced(self, api):
        bundle = _cleared_dossier_listed_product(api, lot_authorized_units=5000)
        records = X.create_distribution_records(
            api, bundle["listing_id"], bundle["agent"],
            [{"lot_code": "LOT-A", "ship_date": "2026-08-05", "delivery_date": "2026-08-07",
              "units_shipped": PRODUCED_LOT_UNITS,
              "consignee_name": "Northeast Beauty Wholesale",
              "consignee_class": "WHOLESALE"}],
        )
        recall = X.recall_with_accepted_plan(
            api, bundle["listing_id"], bundle["agent"],
            initiation_basis=K.INITIATION_BASIS_MANDATORY, officer=OFFICER_HEADERS,
        )
        first = X.open_withdrawal(api, recall, OFFICER_HEADERS, K.DEPTH_WHOLESALE)
        bundle["record_id"] = records[0]["id"]
        bundle["recall_id"] = recall["id"]
        bundle["first"] = X.produce_records(api, first["id"], [records[0]["id"]], bundle["agent"])
        return bundle

    def test_the_first_round_binds_the_shipment_and_fixes_the_denominator(self, api):
        """Production is the step that binds an existing shipment record to the round, fixing
        the count, the shipped total and the outstanding total the later arithmetic rests on.

        PRD: "Production sets each named record's `withdrawal_id` to this withdrawal, sets `records_produced_count` to the number of linked records and `shipped_units_total` to the sum of their `units_shipped`, sets `outstanding_units_total` equal to `shipped_units_total` because nothing has been verified yet, leaves both recovery rates at 0.00, and takes `OPEN → RECORDS_PRODUCED`."

        Design: Corner/state_machines/superseding_withdrawal_round_releases_its_predecessors_record_links
        """
        bundle = self._first_round_with_its_records_produced(api)
        first = bundle["first"]

        assert first["status"] == K.WITHDRAWAL_STATUS_RECORDS_PRODUCED
        assert first["records_produced_count"] == 1
        assert first["shipped_units_total"] == PRODUCED_LOT_UNITS
        assert first["outstanding_units_total"] == PRODUCED_LOT_UNITS
        assert X.read_record(api, bundle["record_id"])["withdrawal_id"] == first["id"]

    def test_opening_the_successor_supersedes_the_predecessor_and_zeroes_its_totals(self, api):
        """The second round is a fresh withdrawal at zero, and the first is retired terminally
        with the three totals it had accumulated wiped back to zero.

        PRD: "A successful open creates a `MarketWithdrawal` with `status` `OPEN`, `records_produced_count` 0, `shipped_units_total` 0, `outstanding_units_total` 0 and both recovery rates 0.00, moves the recall to `EXECUTING` — from `PLAN_ACCEPTED`, from `EXTENDED`, or as a self-loop from `EXECUTING` — and raises the recall's `version` by exactly 1."
        PRD: "Any predecessor withdrawal whose `status` was `OPEN`, `RECORDS_PRODUCED`, `INTERIM_REVIEWED` or `EXTENDED_INEFFECTIVE` becomes `SUPERSEDED`, which is terminal: each of its linked distribution records has its `withdrawal_id` cleared back to null so the successor round can produce them afresh, and the predecessor's `records_produced_count`, `shipped_units_total` and `outstanding_units_total` are all zeroed."

        Design: Corner/state_machines/superseding_withdrawal_round_releases_its_predecessors_record_links
        """
        bundle = self._first_round_with_its_records_produced(api)
        before = X.read_recall(api, bundle["recall_id"])

        second = X.open_withdrawal(api, before, OFFICER_HEADERS, K.DEPTH_RETAIL)

        assert second["id"] != bundle["first"]["id"]
        assert second["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert second["records_produced_count"] == 0
        assert second["shipped_units_total"] == 0
        assert second["outstanding_units_total"] == 0

        retired = X.read_withdrawal(api, bundle["first"]["id"])
        assert retired["status"] == K.WITHDRAWAL_STATUS_SUPERSEDED
        assert retired["records_produced_count"] == 0
        assert retired["shipped_units_total"] == 0
        assert retired["outstanding_units_total"] == 0

        after = X.read_recall(api, bundle["recall_id"])
        assert after["status"] == K.RECALL_STATUS_EXECUTING
        assert after["version"] == before["version"] + 1

    def test_the_released_record_keeps_its_own_tallies_and_can_be_produced_afresh(self, api):
        """The release is a compensation, not a deletion: the shipment's link is cleared while
        its unit buckets survive intact, so the successor round can produce the very same record.

        PRD: "The per-record verified unit tallies are deliberately **not** touched by that release, so the conservation invariant below still balances across a supersession."
        PRD: "Records are readable individually and listable across the system, narrowed by `listing_id`, by `withdrawal_id` and by `lot_code`."

        Design: Corner/state_machines/superseding_withdrawal_round_releases_its_predecessors_record_links
        """
        bundle = self._first_round_with_its_records_produced(api)
        second = X.open_withdrawal(
            api, X.read_recall(api, bundle["recall_id"]), OFFICER_HEADERS, K.DEPTH_RETAIL
        )

        released = X.read_record(api, bundle["record_id"])
        assert released["withdrawal_id"] is None
        assert released["units_shipped"] == PRODUCED_LOT_UNITS
        assert released["units_verified_returned"] == 0
        assert released["units_outstanding"] == PRODUCED_LOT_UNITS
        A.assert_record_unit_balance(released)

        _orphaned, meta = validate_paginated(
            api.list_distribution_records(
                OFFICER_HEADERS, {"withdrawal_id": bundle["first"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        reproduced = X.produce_records(
            api, second["id"], [bundle["record_id"]], bundle["agent"]
        )
        assert reproduced["records_produced_count"] == 1
        assert reproduced["shipped_units_total"] == PRODUCED_LOT_UNITS
