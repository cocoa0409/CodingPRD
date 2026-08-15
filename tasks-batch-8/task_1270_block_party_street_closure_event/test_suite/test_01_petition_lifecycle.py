"""Petition lifecycle: support modes, thresholds, the cure loop, signature rules,
and the petition lock (PRD §3.2)."""
import pytest

from test_helpers import (
    NEIGHBOR,
    OFFICER,
    add_signature_record,
    api_client,
    assert_petition,
    assert_permit_application,
    create_application_record,
    create_petition_record,
    create_segment_record,
    create_organizer_record,
    cure_petition_record,
    make_organizer_headers,
    set_logical_clock,
    setup_draft_application,
    setup_issued_application,
    setup_petition,
    setup_under_review_application,
    submit_application_record,
    submit_petition_record,
    validate_error,
    validate_success,
    verify_petition_record,
)


class TestSupportModeDivergence:
    def test_support_mode_and_threshold_computed_at_creation(self, api):
        """PRD §3.2: "The first is `support_mode`: for a `RESIDENTIAL` segment the mode is
        `DISTINCT_HOUSEHOLD`, and for a `MIXED_USE` segment it is `SIGNATURE_COUNT`."
        PRD §3.2: "on a `RESIDENTIAL` segment the threshold is 60 percent of the segment's
        `household_count` rounded up to a whole number".

        Design: Difficulty/dual_variant_calc/petition_support_metric_modes_diverge
        """
        ctx = setup_petition(signatures=[], outcome="collecting")
        petition = ctx["petition"]
        assert_petition(petition)
        assert petition["required_signatures"] == 3, "ceil(0.60 * 5 households) == 3"
        assert petition["support_mode"] == "DISTINCT_HOUSEHOLD"
        assert petition["valid_signature_count"] == 0
        assert petition["distinct_household_count"] == 0
        assert petition["status"] == "COLLECTING"

    def test_distinct_household_metric_gates_submit(self, api):
        """PRD §3.2: "Under `DISTINCT_HOUSEHOLD` the metric is `distinct_household_count`,
        so two active signatures from the same address count once."
        PRD §3.2: "the metric is checked at that moment, falling short yielding
        `ERR_SIGNATURE_THRESHOLD_NOT_MET`."

        Design: Difficulty/dual_variant_calc/petition_support_metric_modes_diverge
        """
        ctx = setup_petition(signatures=[], outcome="collecting")
        petition, organizer = ctx["petition"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # 3 ACTIVE signatures from only 2 distinct households.
        add_signature_record(petition["id"], household_address="1 Maple Ave",
                             signer_name="Sam One", signer_email="s1@example.com")
        add_signature_record(petition["id"], household_address="1 Maple Ave",
                             signer_name="Sam Two", signer_email="s2@example.com")
        add_signature_record(petition["id"], household_address="2 Maple Ave",
                             signer_name="Sam Three", signer_email="s3@example.com")
        petition = validate_success(api.get_petition(petition["id"], headers), 200)
        assert petition["valid_signature_count"] == 3
        assert petition["distinct_household_count"] == 2

        # DISTINCT_HOUSEHOLD metric 2 < required 3 -> rejected even though 3 rows exist.
        res = api.submit_petition(petition["id"], headers)
        validate_error(res, "ERR_SIGNATURE_THRESHOLD_NOT_MET")
        petition = validate_success(api.get_petition(petition["id"], headers), 200)
        assert petition["status"] == "COLLECTING"

        # Third distinct household reaches the metric; submit now succeeds.
        add_signature_record(petition["id"], household_address="3 Maple Ave",
                             signer_name="Sam Four", signer_email="s4@example.com")
        petition = validate_success(api.submit_petition(petition["id"], headers), 200)
        assert petition["status"] == "SUBMITTED"


class TestPetitionThresholdBoundary:
    def test_submit_at_exact_threshold_passes(self, api):
        """PRD §3.2: "The threshold is satisfied when the applicable metric reaches
        `required_signatures`; exact equality passes."

        Design: Difficulty/boundary_precision_check/petition_threshold_exact_boundary
        """
        ctx = setup_petition(outcome="collecting")
        petition, organizer = ctx["petition"], ctx["organizer"]
        assert petition["required_signatures"] == 3
        submitted = submit_petition_record(petition["id"], organizer)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["distinct_household_count"] == 3

    def test_submit_one_below_threshold_rejected(self, api):
        """PRD §3.2: "The threshold is satisfied when the applicable metric reaches
        `required_signatures`; exact equality passes."
        PRD §3.2: "the metric is checked at that moment, falling short yielding
        `ERR_SIGNATURE_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/petition_threshold_exact_boundary
        """
        ctx = setup_petition(
            signatures=[
                {"household_address": "4 Ash Way", "signer_name": "Q Four", "signer_email": "q4@example.com"},
                {"household_address": "5 Ash Way", "signer_name": "Q Five", "signer_email": "q5@example.com"},
            ],
            outcome="collecting",
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        assert petition["required_signatures"] == 3
        res = api.submit_petition(petition["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_SIGNATURE_THRESHOLD_NOT_MET")
        petition = validate_success(
            api.get_petition(petition["id"], make_organizer_headers(organizer["id"])), 200
        )
        assert petition["status"] == "COLLECTING"
        assert petition["distinct_household_count"] == 2


class TestPetitionCureLoop:
    def test_deficient_review_parks_petition_and_cure_increments_round(self, api):
        """PRD §3.2: "A `DEFICIENT` decision instead parks the petition in `DEFICIENT`
        with the supplied `note` recorded as `deficiency_note`, a field that stays absent
        until the first deficiency."
        PRD §3.2: "The organizer may then cure the petition, which returns it from
        `DEFICIENT` to `COLLECTING` — curing from any other state fails with
        `ERR_INVALID_STATE` — and increments `cure_round`, which counts these deficiency
        cycles starting from zero."

        Design: Difficulty/non_linear_state_machine/petition_cure_loop_cycle
        """
        ctx = setup_petition(outcome="submitted")
        petition, organizer = ctx["petition"], ctx["organizer"]
        deficient = verify_petition_record(petition["id"], "DEFICIENT", note="illegible row")
        assert deficient["status"] == "DEFICIENT"
        assert deficient["deficiency_note"] == "illegible row"

        cured = cure_petition_record(petition["id"], organizer)
        assert cured["status"] == "COLLECTING"
        assert cured["cure_round"] == 1

    def test_cured_petition_resubmits_and_verifies(self, api):
        """PRD §3.2: "An `APPROVE` decision re-checks the metric against the threshold at
        verification time — signatures withdrawn since submission can sink a petition here,
        again surfacing `ERR_SIGNATURE_THRESHOLD_NOT_MET` — and on success moves the
        petition to `VERIFIED`".

        Design: Difficulty/non_linear_state_machine/petition_cure_loop_cycle
        """
        ctx = setup_petition(outcome="submitted")
        petition, organizer = ctx["petition"], ctx["organizer"]
        verify_petition_record(petition["id"], "DEFICIENT", note="illegible row")
        cure_petition_record(petition["id"], organizer)
        add_signature_record(petition["id"], household_address="4 Oak St",
                             signer_name="W Four", signer_email="w4@example.com")
        resubmitted = submit_petition_record(petition["id"], organizer)
        assert resubmitted["status"] == "SUBMITTED"
        verified = verify_petition_record(petition["id"], "APPROVE")
        assert verified["status"] == "VERIFIED"
        assert verified["cure_round"] == 1


class TestApplicationSubmitGatedByPetition:
    def test_submit_blocked_while_petition_only_submitted(self, api):
        """PRD §3.3: "First, the backing petition must be `VERIFIED` (else
        `ERR_PETITION_NOT_VERIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_petition_state
        """
        ctx = setup_draft_application(outcome="submitted")
        application, organizer = ctx["application"], ctx["organizer"]
        res = api.submit_permit_application(application["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_PETITION_NOT_VERIFIED")
        current = validate_success(
            api.get_permit_application(application["id"], make_organizer_headers(organizer["id"])), 200
        )
        assert current["status"] == "DRAFT"

    def test_submit_succeeds_after_petition_verified(self, api):
        """PRD §3.3: "First, the backing petition must be `VERIFIED` (else
        `ERR_PETITION_NOT_VERIFIED`)."
        PRD §3.3: "Submitting the application is the point of no return from `DRAFT` to
        `UNDER_REVIEW`".

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_petition_state
        """
        ctx = setup_draft_application(outcome="submitted")
        petition, organizer = ctx["petition"], ctx["organizer"]
        verify_petition_record(petition["id"], "APPROVE")
        submitted = submit_application_record(ctx["application"], organizer)
        assert submitted["status"] == "UNDER_REVIEW"
        assert_permit_application(submitted)


class TestPetitionCornerClaims:
    def test_mixed_use_threshold_and_mode(self, api):
        """PRD §3.2: "on a `RESIDENTIAL` segment the threshold is 60 percent of the segment's
        `household_count` rounded up to a whole number, while on a `MIXED_USE` segment it is
        60 percent of `household_count` plus 50 percent of `business_count`, the sum rounded
        up to a whole number."
        PRD §3.2: "for a `RESIDENTIAL` segment the mode is `DISTINCT_HOUSEHOLD`, and for a
        `MIXED_USE` segment it is `SIGNATURE_COUNT`."

        Design: Corner/entities/petition_computed_threshold_fields
        """
        ctx = setup_petition(
            signatures=[],
            outcome="collecting",
            segment_overrides={
                "jurisdiction": "COUNTY",
                "segment_kind": "MIXED_USE",
                "household_count": 2,
                "business_count": 2,
                "length_m": 30,
            },
        )
        petition = ctx["petition"]
        assert_petition(petition)
        # ceil(0.6*2 + 0.5*2) = ceil(2.2) = 3.
        assert petition["required_signatures"] == 3
        assert petition["support_mode"] == "SIGNATURE_COUNT"
        assert petition["status"] == "COLLECTING"
        assert petition["valid_signature_count"] == 0
        assert petition["cure_round"] == 0

    def test_petition_submit_twice_rejected(self, api):
        """PRD §3.2: "submitting the petition moves it from `COLLECTING` to `SUBMITTED` —
        submitting from any other state is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/petition_submit_twice_returns_409
        """
        ctx = setup_petition(outcome="submitted")
        petition, organizer = ctx["petition"], ctx["organizer"]
        assert petition["status"] == "SUBMITTED"
        res = api.submit_petition(petition["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_INVALID_STATE")
        current = validate_success(
            api.get_petition(petition["id"], make_organizer_headers(organizer["id"])), 200
        )
        assert current["status"] == "SUBMITTED"

    def test_duplicate_signature_pair_rejected(self, api):
        """PRD §3.2: "the pair of `household_address` and `signer_email` must be unique among
        the petition's `ACTIVE` signatures — a repeat pairing is refused with
        `ERR_DUPLICATE_SIGNATURE`."
        PRD §3.2: "`valid_signature_count`, the number of `ACTIVE` signature rows, and
        `distinct_household_count`, the number of distinct `household_address` values among
        them."

        Design: Corner/validations/duplicate_signature_returns_409
        """
        ctx = setup_petition(signatures=[], outcome="collecting")
        petition, organizer = ctx["petition"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        add_signature_record(petition["id"], household_address="1 Birch Rd",
                             signer_name="O One", signer_email="o1@example.com")
        res = api.add_signature(
            petition["id"],
            {"household_address": "1 Birch Rd", "signer_name": "O One Again",
             "signer_email": "o1@example.com"},
            NEIGHBOR,
        )
        validate_error(res, "ERR_DUPLICATE_SIGNATURE")
        # Same address with a different signer email is a distinct signature.
        add_signature_record(petition["id"], household_address="1 Birch Rd",
                             signer_name="O Two", signer_email="o2@example.com")
        petition = validate_success(api.get_petition(petition["id"], headers), 200)
        assert petition["valid_signature_count"] == 2
        assert petition["distinct_household_count"] == 1

    def test_withdraw_on_locked_petition_rejected(self, api):
        """PRD §3.2: "the moment any application referencing it is issued, the petition
        transitions from `VERIFIED` to its terminal `LOCKED` state, from which neither
        signature creation nor withdrawal is possible."
        PRD §3.2: "a withdrawal against a `LOCKED` petition is rejected with
        `ERR_PETITION_LOCKED`."

        Design: Corner/state_machines/locked_petition_withdraw_returns_409
        """
        ctx = setup_issued_application(
            application_overrides={"expected_attendance": 100},
            tcp_overrides={"barricade_count": 1},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 10}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        assert petition["status"] == "LOCKED"
        sig_id = ctx["signatures"][0]["id"]
        res = api.withdraw_signature(petition["id"], sig_id, NEIGHBOR)
        validate_error(res, "ERR_PETITION_LOCKED")
        current = validate_success(
            api.get_petition(petition["id"], make_organizer_headers(organizer["id"])), 200
        )
        assert current["valid_signature_count"] == 3
        assert current["distinct_household_count"] == 3

    def test_withdrawal_suspends_application_and_reverify_restores(self, api):
        """PRD §3.2: "If the petition was `VERIFIED` and the withdrawal drops the applicable
        metric below `required_signatures`, the petition automatically collapses to
        `DEFICIENT` with `deficiency_note` set to "signature withdrawal below threshold",
        and — the cascade that makes the petition the backbone of the whole program — every
        linked application in `UNDER_REVIEW` or `APPROVED` drops to `SUSPENDED` with
        `decision_reason` recorded as "petition deficient"."
        PRD §3.2: "Applications suspended in this way return to `UNDER_REVIEW` only when the
        petition is verified again".

        Design: Corner/state_machines/withdrawal_suspends_and_reverify_restores
        """
        ctx = setup_under_review_application()
        petition, organizer = ctx["petition"], ctx["organizer"]
        application = ctx["application"]
        headers = make_organizer_headers(organizer["id"])

        res = api.withdraw_signature(petition["id"], ctx["signatures"][0]["id"], NEIGHBOR)
        validate_success(res, 200)
        petition = validate_success(api.get_petition(petition["id"], headers), 200)
        assert petition["status"] == "DEFICIENT"
        assert petition["distinct_household_count"] == 2
        application = validate_success(api.get_permit_application(application["id"], headers), 200)
        assert application["status"] == "SUSPENDED"

        cure_petition_record(petition["id"], organizer)
        add_signature_record(petition["id"], household_address="9 Elm St",
                             signer_name="F Nine", signer_email="f9@example.com")
        submit_petition_record(petition["id"], organizer)
        verified = verify_petition_record(petition["id"], "APPROVE")
        assert verified["status"] == "VERIFIED"
        assert verified["cure_round"] == 1
        application = validate_success(api.get_permit_application(application["id"], headers), 200)
        assert application["status"] == "UNDER_REVIEW"
