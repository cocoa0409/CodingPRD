"""Who may act, and on what: the role denials that keep each actor inside its
own remit, the collection read that excludes a caller its by-id neighbour
admits, correct-role-wrong-identity denials, the one write two roles share, and
the two segregation-of-duties bars that separate a decision from its review.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    OPERATOR_HEADERS,
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

ASTER_LABS = "Aster Labs Newark"
ASTER_HOLDINGS = "Aster Holdings LLC"
BRIGHTLINE_LINE = "Brightline Fill Line"
BRIGHTLINE_HOLDINGS = "Brightline Beauty Holdings"
DESIGNEE_NAME = "Aster Brands Inc"


def _establishment_with_a_recall(api):
    """An approved establishment, a listing and one recall the agency has just opened."""
    bundle = X.registered_facility_with_listing(
        api,
        listing_overrides={"product_name": "Aster Blush Powder"},
        person_overrides={"legal_name": DESIGNEE_NAME},
        facility_overrides={"facility_name": ASTER_LABS,
                            "owner_operator_name": ASTER_HOLDINGS},
    )
    bundle["recall"] = X.open_recall(
        api, bundle["listing_id"], K.INITIATION_BASIS_MANDATORY, officer=OFFICER_HEADERS
    )
    bundle["recall_id"] = bundle["recall"]["id"]
    return bundle


class TestEachRoleIsRefusedAnotherRolesExclusiveOperation:
    """Four denials in one world, each aimed at somebody else's remit."""

    def test_the_registrant_may_not_decide_its_own_registration(self, api):
        """Deciding a pending file belongs to the agency reviewer, so the establishment's own
        registrant is refused on the role alone and its approval stands.

        PRD: "If `X-User-Role` is not one of the five role names below, or is a valid role that the addressed endpoint does not authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD: "A `RegulatoryReviewer` is the agency reviewer. It decides registrations, ownership changes and listings, scores substantiation dossiers, schedules inspections and issues observations."

        Design: Corner/rbac/four_cross_role_operations_are_denied_with_forbidden_role
        """
        bundle = _establishment_with_a_recall(api)

        validate_error(
            api.decide_registration(
                bundle["facility_id"],
                F.registration_decision_payload("REJECT"),
                make_facility_registrant_headers(bundle["facility_id"]),
            ),
            E.ERR_FORBIDDEN_ROLE,
        )

        facility = X.read_facility(api, bundle["facility_id"])
        assert facility["registration_status"] == K.REGISTRATION_STATUS_REGISTERED

    def test_the_designees_agent_may_not_run_the_operator_sweep(self, api):
        """The compliance checkpoint is the platform operator's alone, and the sponsor's agent
        cannot make time pass for the whole register.

        PRD: "A `SystemOperator` is the platform operator. It drives the logical clock and runs the compliance sweep checkpoint."

        Design: Corner/rbac/four_cross_role_operations_are_denied_with_forbidden_role
        """
        bundle = _establishment_with_a_recall(api)

        validate_error(
            api.run_compliance_sweep(bundle["agent"]),
            E.ERR_FORBIDDEN_ROLE,
        )

        result = X.run_sweep(api)
        A.assert_sweep_counters(result)

    def test_the_enforcement_officer_may_not_file_the_firms_recall_plan(self, api):
        """The corrective plan is the sponsor's own submission; the officer who demanded it may
        not write it, and the recall stays where it was opened.

        PRD: "A `ResponsiblePersonAgent` is the label-of-record designee's agent. It creates responsible persons, files listings, ingredients and substantiation dossiers, records and reports adverse events, submits recall plans, records shipments and posts recovery movements."

        Design: Corner/rbac/four_cross_role_operations_are_denied_with_forbidden_role
        """
        bundle = _establishment_with_a_recall(api)

        validate_error(
            api.submit_recall_plan(
                bundle["recall_id"],
                F.recall_plan_payload(corrective_summary="Officer trying to file the firm's plan",
                                      distribution_depth=K.DEPTH_RETAIL),
                OFFICER_HEADERS,
            ),
            E.ERR_FORBIDDEN_ROLE,
        )

        recall = X.read_recall(api, bundle["recall_id"])
        assert recall["status"] == K.RECALL_STATUS_PLAN_REQUIRED
        assert recall["plan_round"] == 0
        assert recall["plan_submitted_at"] is None

    def test_the_regulatory_reviewer_may_not_open_a_recall(self, api):
        """Recall initiation belongs to enforcement, so the reviewer's attempt creates nothing and
        the listing still carries exactly the one recall the officer opened.

        PRD: "An `EnforcementOfficer` is the agency enforcement officer. It opens recall actions, rules on recall plans and runs withdrawal effectiveness reviews."

        Design: Corner/rbac/four_cross_role_operations_are_denied_with_forbidden_role
        """
        bundle = _establishment_with_a_recall(api)

        validate_error(
            api.open_recall_action(
                bundle["listing_id"],
                F.recall_action_payload(K.INITIATION_BASIS_MANDATORY, "CLASS_II"),
                REVIEWER_HEADERS,
            ),
            E.ERR_FORBIDDEN_ROLE,
        )

        rows, meta = validate_paginated(
            api.list_recall_actions(bundle["listing_id"], REVIEWER_HEADERS,
                                    {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 1
        assert A.ids_of(rows) == [bundle["recall_id"]]
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 1


class TestTheRegistryWideCollectionExcludesTheRegistrant:
    """The boundary is the collection, not the entity."""

    def test_the_registrant_is_denied_the_registry_wide_collection(self, api):
        """Browsing every establishment in the register is an agency capability, and the role
        check refuses the registrant before any filter is applied.

        PRD: "If `X-User-Role` is not one of the five role names below, or is a valid role that the addressed endpoint does not authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD: "The table names only the HTTP contract and the roles authorized to invoke each route: the request payload, the response body and the side effects of each operation are specified in the §2 and §3 narratives above, and a reader must reconstruct them from there."

        Design: Corner/rbac/facility_registrant_cannot_browse_the_regulator_wide_facility_registry
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        validate_error(
            api.list_facilities(
                make_facility_registrant_headers(facility["id"]),
                {"registration_status": K.REGISTRATION_STATUS_REGISTERED},
            ),
            E.ERR_FORBIDDEN_ROLE,
        )

    def test_the_same_caller_still_reads_its_own_establishment_by_id(self, api):
        """The denial is not about the data: the identical caller reads its own establishment by
        identifier and sees its approved standing.

        PRD: "When `X-User-Role` is `FacilityRegistrant`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any resource that references a `Facility` compare the resource's facility reference to `X-User-ID`."

        Design: Corner/rbac/facility_registrant_cannot_browse_the_regulator_wide_facility_registry
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )
        registrant = make_facility_registrant_headers(facility["id"])
        validate_error(
            api.list_facilities(registrant,
                                {"registration_status": K.REGISTRATION_STATUS_REGISTERED}),
            E.ERR_FORBIDDEN_ROLE,
        )

        own = get_success_data(api.get_facility(facility["id"], registrant))

        assert own["id"] == facility["id"]
        assert own["registration_status"] == K.REGISTRATION_STATUS_REGISTERED

    def test_an_enforcement_officer_receives_the_collection(self, api):
        """The same filtered collection the registrant was refused is served to an authorized
        agency role, which is what makes the refusal a role boundary rather than a missing route.

        PRD: "The table names only the HTTP contract and the roles authorized to invoke each route: the request payload, the response body and the side effects of each operation are specified in the §2 and §3 narratives above, and a reader must reconstruct them from there."

        Design: Corner/rbac/facility_registrant_cannot_browse_the_regulator_wide_facility_registry
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        rows, meta = validate_paginated(
            api.list_facilities(
                OFFICER_HEADERS,
                {"registration_status": K.REGISTRATION_STATUS_REGISTERED, "limit": K.MAX_LIMIT},
            )
        )

        assert meta["total_count"] == 1
        assert A.ids_of(rows) == [facility["id"]]
        assert rows[0]["registration_status"] == K.REGISTRATION_STATUS_REGISTERED


class TestTheRightRoleWithTheWrongIdentityIsStillRefused:
    """Two registrants, one establishment each, and no reach across the fence."""

    def _two_draft_establishments(self, api):
        """Two DRAFT establishments, each with its own registrant of record."""
        first = X.create_draft_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            facility_type="MANUFACTURER", state_or_province="NJ",
        )
        second = X.create_draft_facility(
            api, facility_name=BRIGHTLINE_LINE, owner_operator_name=BRIGHTLINE_HOLDINGS,
            facility_type="PROCESSOR", state_or_province="OH",
        )
        return first, second

    def test_a_foreign_registrant_is_refused_with_the_ownership_error(self, api):
        """The caller holds exactly the role the route authorizes, so what fails is the identity
        comparison — a different error from a role denial — and neither file moves.

        PRD: "When `X-User-Role` is `FacilityRegistrant`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any resource that references a `Facility` compare the resource's facility reference to `X-User-ID`."
        PRD: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/a_foreign_registrant_cannot_submit_someone_elses_facility
        """
        first, second = self._two_draft_establishments(api)

        validate_error(
            api.submit_registration(
                first["id"], make_facility_registrant_headers(second["id"])
            ),
            E.ERR_NOT_RESOURCE_OWNER,
        )

        assert X.read_facility(api, first["id"])["registration_status"] == \
            K.REGISTRATION_STATUS_DRAFT
        assert X.read_facility(api, second["id"])["registration_status"] == \
            K.REGISTRATION_STATUS_DRAFT

    def test_the_rightful_owner_makes_the_identical_call_succeed(self, api):
        """Nothing about the request was wrong except who sent it: the owner's identical call
        carries the establishment into agency review.

        PRD: "Submitting the registration for agency review is admissible only from `DRAFT`; from any other registration state the request is rejected with `ERR_INVALID_FACILITY_STATE` (HTTP 409)."
        PRD: "Facility creation is the one exception — it is a create-root call with no ownership target, so the check is skipped there, and the `id` the service returns is precisely the value the registrant sends as `X-User-ID` on every subsequent facility call."

        Design: Corner/rbac/a_foreign_registrant_cannot_submit_someone_elses_facility
        """
        first, second = self._two_draft_establishments(api)
        validate_error(
            api.submit_registration(
                first["id"], make_facility_registrant_headers(second["id"])
            ),
            E.ERR_NOT_RESOURCE_OWNER,
        )

        submitted = get_success_data(
            api.submit_registration(first["id"], make_facility_registrant_headers(first["id"]))
        )

        assert submitted["registration_status"] == K.REGISTRATION_STATUS_PENDING_REVIEW
        assert X.read_facility(api, second["id"])["registration_status"] == \
            K.REGISTRATION_STATUS_DRAFT


RECLASSIFICATION_CLOCK = "2026-08-05T08:00:00Z"
INTAKE_INSTANT = "2026-08-05T00:00:00Z"
REBASED_DEADLINE = "2026-08-20T23:59:59.999Z"
SIX_YEAR_RETENTION = "2032-08-05"


class TestReclassificationIsSharedByTheReviewerAndTheAgent:
    """The one write in the domain two roles may both perform — and only those two."""

    def _two_retained_events(self, api):
        """Two retained non-serious events on one listing, with the clock moved past intake."""
        bundle = X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder"},
            person_overrides={"legal_name": DESIGNEE_NAME},
            facility_overrides={"facility_name": ASTER_LABS,
                                "owner_operator_name": ASTER_HOLDINGS},
        )
        X.set_clock(api, RECLASSIFICATION_CLOCK)
        first = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], received_at=INTAKE_INSTANT,
            event_description="Mild irritation, later reassessed upward",
        )
        second = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], received_at=INTAKE_INSTANT,
            event_description="Second mild irritation, later reassessed upward",
        )
        return bundle, first, second

    def test_the_agency_reviewer_may_raise_a_retained_event(self, api):
        """The reviewer's escalation rebases the report clock on the reclassification instant, so
        the deadline is fifteen days after the day the decision was taken.

        PRD: "Either a `RegulatoryReviewer` or the listing's own `ResponsiblePersonAgent` may reclassify an event, supplying `seriousness` and optionally a revised `outcome_code`."
        PRD: "Reclassification takes the `RETAINED → REPORT_DUE` edge, sets `seriousness` to `SERIOUS` and `reclassified_at` to the logical clock, and **rebases the report clock on the reclassification instant**: `deadline_basis_at` becomes `reclassified_at`, not `received_at`, and `deadline_at` is recomputed from that later basis."

        Design: Corner/rbac/reclassification_is_a_shared_operation_for_reviewer_and_agent
        """
        _bundle, first, _second = self._two_retained_events(api)
        assert first["report_status"] == K.EVENT_STATUS_RETAINED

        raised = get_success_data(
            api.reclassify_adverse_event(
                first["id"],
                F.reclassify_payload(K.SERIOUSNESS_SERIOUS, outcome_code="HOSPITALIZATION"),
                REVIEWER_HEADERS,
            )
        )

        assert raised["seriousness"] == K.SERIOUSNESS_SERIOUS
        assert raised["report_status"] == K.EVENT_STATUS_REPORT_DUE
        assert raised["reclassified_at"] == RECLASSIFICATION_CLOCK
        assert raised["deadline_basis_at"] == RECLASSIFICATION_CLOCK
        assert raised["deadline_at"] == REBASED_DEADLINE
        assert raised["retention_until"] == SIX_YEAR_RETENTION

    def test_the_designees_own_agent_may_raise_the_other_event(self, api):
        """The same endpoint accepts the sponsor's agent, and both escalations show up in the
        establishment's open-serious tally.

        PRD: "Either a `RegulatoryReviewer` or the listing's own `ResponsiblePersonAgent` may reclassify an event, supplying `seriousness` and optionally a revised `outcome_code`."
        PRD: "Both open-event counters rise by 1, and `retention_until` is extended to the six-year term — but that term is measured from `received_at`, never from `reclassified_at`, so the retention horizon does not move with the reclassification."

        Design: Corner/rbac/reclassification_is_a_shared_operation_for_reviewer_and_agent
        """
        bundle, first, second = self._two_retained_events(api)
        get_success_data(
            api.reclassify_adverse_event(
                first["id"], F.reclassify_payload(K.SERIOUSNESS_SERIOUS), REVIEWER_HEADERS
            )
        )

        raised = get_success_data(
            api.reclassify_adverse_event(
                second["id"], F.reclassify_payload(K.SERIOUSNESS_SERIOUS), bundle["agent"]
            )
        )

        assert raised["report_status"] == K.EVENT_STATUS_REPORT_DUE
        assert raised["deadline_at"] == REBASED_DEADLINE
        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 2
        assert X.read_listing(api, bundle["listing_id"])["open_serious_event_count"] == 2

    def test_an_enforcement_officer_is_refused_the_shared_operation(self, api):
        """Shared by exactly two roles means closed to the other three: the officer's identical
        call is refused on the role check, ahead of any state objection, and changes nothing.

        PRD: "If `X-User-Role` is not one of the five role names below, or is a valid role that the addressed endpoint does not authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD: "Checks are evaluated in the fixed order below, and the first violated check produces the response."

        Design: Corner/rbac/reclassification_is_a_shared_operation_for_reviewer_and_agent
        """
        bundle, _first, second = self._two_retained_events(api)
        raised = get_success_data(
            api.reclassify_adverse_event(
                second["id"], F.reclassify_payload(K.SERIOUSNESS_SERIOUS), bundle["agent"]
            )
        )
        assert raised["seriousness"] == K.SERIOUSNESS_SERIOUS

        validate_error(
            api.reclassify_adverse_event(
                second["id"],
                F.reclassify_payload(K.SERIOUSNESS_NON_SERIOUS),
                OFFICER_HEADERS,
            ),
            E.ERR_FORBIDDEN_ROLE,
        )

        rows, _meta = validate_paginated(
            api.list_adverse_events(bundle["listing_id"], REVIEWER_HEADERS,
                                    {"limit": K.MAX_LIMIT})
        )
        still = A.find_by_id(rows, second["id"])
        assert still["seriousness"] == K.SERIOUSNESS_SERIOUS
        assert still["report_status"] == K.EVENT_STATUS_REPORT_DUE


LOT_F = "LOT-F"
SHIPPED_UNITS = 1000
VERIFIED_UNITS = 950
UNRECOVERED_UNITS = 50
CLOSING_RATE = 95.00


class TestThePlanDeciderMayNotVerifyTheEffectiveness:
    """Same role, same permissions, different user — and the bar is recorded state."""

    def _withdrawal_ready_for_the_closing_review(self, api):
        """A round whose plan OFF-1 accepted, with 950 of 1000 units verified back."""
        bundle = X.listed_bundle(
            api,
            listing_overrides={"product_name": "Aster Blush Powder",
                               "lot_authorized_units": 5000},
            person_overrides={"legal_name": DESIGNEE_NAME},
        )
        bundle = X.withdrawal_with_produced_records(
            api, bundle,
            specs=[{"lot_code": LOT_F, "consignee_name": "Gulf Coast Retail Group",
                    "consignee_class": K.DEPTH_RETAIL, "ship_date": "2026-08-05",
                    "delivery_date": "2026-08-08", "units_shipped": SHIPPED_UNITS}],
            officer=OFFICER_HEADERS,
        )
        X.post_recovery(
            api, bundle["withdrawal_id"], bundle["records"][0]["id"], VERIFIED_UNITS,
            bundle["agent"],
        )
        return bundle

    def test_the_officer_who_accepted_the_plan_is_barred_from_the_review(self, api):
        """The identity captured at the plan decision is what bars the review, so the same officer
        is refused and the round sits untouched at the state the production left it in.

        PRD: "The enforcement officer whose `X-User-ID` was captured as `plan_decision_user_id` when the recall plan was decided may not afterwards run the effectiveness review on **any** withdrawal round under that recall action, under either basis."
        PRD: "Every decision, whichever way it goes, records the deciding officer's `X-User-ID` in `plan_decision_user_id` and the instant in `plan_decision_at`, and bumps the recall's `version` by 1."

        Design: Corner/rbac/the_officer_who_accepted_the_plan_may_not_verify_the_effectiveness
        """
        bundle = self._withdrawal_ready_for_the_closing_review(api)
        assert X.read_recall(api, bundle["recall_id"])["plan_decision_user_id"] == "OFF-1"

        validate_error(
            api.run_effectiveness_check(
                bundle["withdrawal_id"],
                F.effectiveness_check_payload(K.BASIS_VERIFIED),
                OFFICER_HEADERS,
            ),
            E.ERR_SEGREGATION_OF_DUTIES,
        )

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["status"] == K.WITHDRAWAL_STATUS_RECORDS_PRODUCED
        assert withdrawal["effectiveness_verdict"] is None
        assert withdrawal["effectiveness_reviewer_user_id"] is None
        assert withdrawal["verified_recovered_units"] == VERIFIED_UNITS
        A.assert_two_decimal_value(withdrawal["verified_recovery_rate"], 0.00, "verified rate")

    def test_a_second_distinct_officer_runs_the_identical_payload(self, api):
        """The bar is on the person, not the payload: a second officer sends the same request and
        the pinned intermediates carry the round to an effective verdict.

        PRD: "A second, distinct enforcement officer must perform the review, and that officer's identifier is stored as `effectiveness_reviewer_user_id` on the withdrawal."
        PRD: "Step two selects `unreachable_credit_pct` from the **provisional** rate: 0 when it is 90.00 or more, 3 when it is 80.00 or more, and 6 otherwise — the acknowledgement that the harder a recall is going, the more of the distribution chain is genuinely unreachable."
        PRD: "Alongside them, `outstanding_units_total` is set to `shipped_units_total` minus `verified_recovered_units`, and `effectiveness_verdict` becomes `EFFECTIVE` when `verified_recovery_rate` is 90.00 or more and `NOT_EFFECTIVE` otherwise."

        Design: Corner/rbac/the_officer_who_accepted_the_plan_may_not_verify_the_effectiveness
        """
        bundle = self._withdrawal_ready_for_the_closing_review(api)
        validate_error(
            api.run_effectiveness_check(
                bundle["withdrawal_id"],
                F.effectiveness_check_payload(K.BASIS_VERIFIED),
                OFFICER_HEADERS,
            ),
            E.ERR_SEGREGATION_OF_DUTIES,
        )

        closed = X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, officer=OFFICER_2_HEADERS
        )

        A.assert_two_decimal_value(closed["provisional_verified_rate"], CLOSING_RATE,
                                   "provisional rate")
        assert closed["unreachable_credit_pct"] == 0
        assert closed["adjusted_denominator_units"] == SHIPPED_UNITS
        A.assert_two_decimal_value(closed["verified_recovery_rate"], CLOSING_RATE,
                                   "verified rate")
        assert closed["effectiveness_verdict"] == K.VERDICT_EFFECTIVE
        assert closed["status"] == K.WITHDRAWAL_STATUS_CLOSED_EFFECTIVE
        assert closed["effectiveness_reviewer_user_id"] == "OFF-2"
        assert closed["outstanding_units_total"] == UNRECOVERED_UNITS

    def test_the_closure_reaches_the_recall_and_the_listing(self, api):
        """One effective review closes both sides of the recall and frees the product from the
        open-recall count, recording the closure once in the ledger.

        PRD: "An effective verified review closes the round and the recall together: the withdrawal takes `RECORDS_PRODUCED → CLOSED_EFFECTIVE` or `INTERIM_REVIEWED → CLOSED_EFFECTIVE`, which is terminal; the parent recall moves `EXECUTING → CLOSED_EFFECTIVE`, also terminal, storing `effectiveness_rate_final` as the withdrawal's `verified_recovery_rate`; the listing's `open_recall_count` falls by 1 and its `marketable` flag is recomputed; and one `WITHDRAWAL_CLOSURE` ledger entry is appended against the withdrawal."

        Design: Corner/rbac/the_officer_who_accepted_the_plan_may_not_verify_the_effectiveness
        """
        bundle = self._withdrawal_ready_for_the_closing_review(api)

        X.run_effectiveness_check(
            api, bundle["withdrawal_id"], K.BASIS_VERIFIED, officer=OFFICER_2_HEADERS
        )

        recall = X.read_recall(api, bundle["recall_id"])
        assert recall["status"] == K.RECALL_STATUS_CLOSED_EFFECTIVE
        A.assert_two_decimal_value(recall["effectiveness_rate_final"], CLOSING_RATE,
                                   "final rate")
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 0

        closures = X.ledger_entries(api, bundle["facility_id"], K.ENTRY_TYPE_WITHDRAWAL_CLOSURE)
        assert len(closures) == 1
        assert closures[0]["subject_id"] == bundle["withdrawal_id"]


LITERATURE_ITEM_VALUE = 1.50


class TestTheScreeningReviewerMayNotIssueTheFullDecision:
    """The second bar runs along the review dimension and survives a revision cycle."""

    def _screened_dossier(self, api):
        """A single-item dossier screened by RVW-1 and found deficient."""
        bundle = X.registered_facility_with_listing(
            api,
            listing_overrides={"product_name": "Aster Blush Powder"},
            person_overrides={"legal_name": DESIGNEE_NAME},
            facility_overrides={"facility_name": ASTER_LABS,
                                "owner_operator_name": ASTER_HOLDINGS},
        )
        dossier = X.open_dossier(api, bundle["listing_id"], bundle["agent"],
                                 assessor_name="Dr. Imani Ferro")
        X.attach_items(api, dossier["id"], bundle["agent"],
                       [(K.EVIDENCE_LITERATURE, K.CREDENTIAL_OTHER)])
        X.submit_dossier(api, dossier["id"], bundle["agent"])
        bundle["substantiation_id"] = dossier["id"]
        return bundle

    def test_the_screening_decision_is_attributed_to_the_reviewer_who_issued_it(self, api):
        """A lone literature item attested by an unqualified assessor is worth 5 multiplied by
        0.3, which is nowhere near the pass mark, and the screening reviewer is recorded by name.

        PRD: "An item's value is its evidence weight multiplied by its credential factor, rounded half up to two decimal places."
        PRD: "Under `SCREENING` the score is simply the sum of those per-item values, the total itself rounded half up to two decimal places."
        PRD: "In either mode a score of **60.00 or more** rules the dossier `ADEQUATE` and anything below 60.00 rules it `DEFICIENT`; the pass mark is inclusive at the boundary."

        Design: Corner/rbac/the_reviewer_who_screened_the_dossier_may_not_issue_the_full_decision
        """
        bundle = self._screened_dossier(api)

        screened = X.decide_dossier(api, bundle["substantiation_id"], K.REVIEW_MODE_SCREENING,
                                    reviewer=REVIEWER_HEADERS)

        A.assert_two_decimal_value(screened["adequacy_score"], LITERATURE_ITEM_VALUE, "score")
        assert screened["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT
        assert screened["review_mode"] == K.REVIEW_MODE_SCREENING
        assert screened["screening_reviewer_user_id"] == "RVW-1"
        assert screened["full_reviewer_user_id"] is None
        assert X.read_listing(api, bundle["listing_id"])["safety_status"] == \
            K.SAFETY_STATUS_SUBSTANTIATION_FAILED

    def test_the_screening_reviewer_is_barred_after_the_firm_resubmits(self, api):
        """The resubmission returns the dossier to review as round 2, and the bar follows the
        stored screening identity across that cycle rather than resetting with it.

        PRD: "The reviewer whose `X-User-ID` was captured as `screening_reviewer_user_id` when a screening decision was issued may not afterwards issue a decision under the full review mode on the same dossier."
        PRD: "A successful submission moves the dossier to `SUBMITTED`, increments `revision_round` by exactly 1 — it counts every entry into `SUBMITTED`, including re-submissions after a deficiency or a revalidation demand, and ranges from 0 to 99 — sets the listing's `safety_status` to `UNDER_SUBSTANTIATION`, refreshes `data_gap_present` from the listing's current ingredient set, recomputes `marketable`, and increments both the dossier's `version` and the listing's `version` by 1."

        Design: Corner/rbac/the_reviewer_who_screened_the_dossier_may_not_issue_the_full_decision
        """
        bundle = self._screened_dossier(api)
        X.decide_dossier(api, bundle["substantiation_id"], K.REVIEW_MODE_SCREENING,
                         reviewer=REVIEWER_HEADERS)

        resubmitted = X.submit_dossier(api, bundle["substantiation_id"], bundle["agent"])
        assert resubmitted["revision_round"] == 2
        assert resubmitted["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED

        validate_error(
            api.decide_substantiation_review(
                bundle["substantiation_id"],
                F.review_decision_payload(K.REVIEW_MODE_FULL),
                REVIEWER_HEADERS,
            ),
            E.ERR_SEGREGATION_OF_DUTIES,
        )

        still = X.read_substantiation(api, bundle["substantiation_id"])
        assert still["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
        assert still["full_reviewer_user_id"] is None
        assert still["screening_reviewer_user_id"] == "RVW-1"

    def test_a_second_reviewer_may_issue_the_full_decision(self, api):
        """A different pair of eyes may score the same evidence under the substantive variant, and
        both attributions then stand side by side on the dossier.

        PRD: "The rule bites only in that direction: a screening decision after a full decision is not restricted, and the full reviewer's identifier is captured separately as `full_reviewer_user_id`."
        PRD: "It stores the computed `adequacy_score`, the supplied `review_mode` and `decided_at` at the logical-clock instant of the decision; it records the deciding reviewer's `X-User-ID` in `screening_reviewer_user_id` when the mode was `SCREENING` and in `full_reviewer_user_id` when the mode was `FULL`; and it writes both `screening_contribution` and `full_contribution` onto every evidence item of the dossier, so a client can inspect what each item would be worth under either variant — `full_contribution` holds the item's value after any read-across discount but **before** the per-class cap is applied, since the cap is a property of the group rather than of the item."

        Design: Corner/rbac/the_reviewer_who_screened_the_dossier_may_not_issue_the_full_decision
        """
        bundle = self._screened_dossier(api)
        X.decide_dossier(api, bundle["substantiation_id"], K.REVIEW_MODE_SCREENING,
                         reviewer=REVIEWER_HEADERS)
        X.submit_dossier(api, bundle["substantiation_id"], bundle["agent"])
        validate_error(
            api.decide_substantiation_review(
                bundle["substantiation_id"],
                F.review_decision_payload(K.REVIEW_MODE_FULL),
                REVIEWER_HEADERS,
            ),
            E.ERR_SEGREGATION_OF_DUTIES,
        )

        decided = X.decide_dossier(api, bundle["substantiation_id"], K.REVIEW_MODE_FULL,
                                   reviewer=REVIEWER_2_HEADERS)

        A.assert_two_decimal_value(decided["adequacy_score"], LITERATURE_ITEM_VALUE, "score")
        assert decided["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT
        assert decided["review_mode"] == K.REVIEW_MODE_FULL
        assert decided["full_reviewer_user_id"] == "RVW-2"
        assert decided["screening_reviewer_user_id"] == "RVW-1"

        rows, meta = validate_paginated(
            api.list_review_items(bundle["substantiation_id"], REVIEWER_HEADERS,
                                  {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 1
        A.assert_two_decimal_value(rows[0]["screening_contribution"], LITERATURE_ITEM_VALUE,
                                   "screening contribution")
        A.assert_two_decimal_value(rows[0]["full_contribution"], LITERATURE_ITEM_VALUE,
                                   "full contribution")
