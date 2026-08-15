"""Development agreements: adoption gating, the referendum threshold, and the
qualification cascade onto vesting."""
from test_helpers import (
    ApiErrorId,
    assert_development_agreement,
    assert_petition,
    certify_petition_now,
    create_development_agreement_payload,
    draft_and_adopt_da,
    file_in_window_appeal,
    file_petition_now,
    resolve_appeal_now,
    setup_approved_application,
    validate_error,
    validate_success,
)


class TestAdoptionGate:
    def test_da_adopt_requires_application_approved(self, api):
        """PRD 3.8: "Adoption, again by a `DecisionAuthority`, requires the
        parent application to stand `APPROVED` — else
        `ERR_APPLICATION_NOT_APPROVED`".
        PRD 3.9: "A timely appeal ruled `REVERSED` moves the appeal to
        `REVERSED`, drives the decision to `REVERSED_ON_APPEAL`, and remands
        the application to `DECISION_PENDING` for re-decision".

        The agreement is drafted while the application stands APPROVED (the
        drafting posture PRD 3.8 describes — "a `DecisionAuthority` drafts one
        on an approved application"), then the application is remanded to
        DECISION_PENDING through the appeal path, so adoption is attempted
        against a parent that no longer stands APPROVED.

        Design: Difficulty/cross_entity_state_dependency/da_adopt_requires_application_approved
        """
        ctx = setup_approved_application()
        payload = create_development_agreement_payload(
            agreement_number="ORD-X", registered_voters=12500
        )
        da = validate_success(
            api.create_development_agreement(
                ctx["application"]["id"], payload, ctx["authority_headers"]
            ),
            expected_status=201,
        )
        assert da["status"] == "DRAFT"

        # Remand the application out of APPROVED via a REVERSED appeal.
        file_in_window_appeal(ctx)
        resolve_appeal_now(ctx, ruling="REVERSED")

        response = api.adopt_development_agreement(da["id"], ctx["authority_headers"])
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)

        after = validate_success(
            api.get_development_agreement(da["id"], ctx["authority_headers"])
        )
        assert after["status"] == "DRAFT", (
            f"rejected adoption must leave the agreement DRAFT, got {after['status']}"
        )

    def test_da_adopt_success_sets_pending_referendum(self, api):
        """PRD 3.8: "Adoption, again by a `DecisionAuthority`, requires the
        parent application to stand `APPROVED` ... and moves the agreement to
        `ADOPTED`, setting its `vesting_status` to `PENDING_REFERENDUM` and
        fixing its `referendum_deadline` at the `adoption_date` plus the
        `REFERENDUM_WINDOW_DAYS` window."

        Design: Difficulty/cross_entity_state_dependency/da_adopt_requires_application_approved
        """
        ctx = setup_approved_application()
        da = draft_and_adopt_da(ctx, agreement_number="ORD-OK", registered_voters=12500)
        assert_development_agreement(da)
        assert da["status"] == "ADOPTED", (
            f"adoption on an APPROVED application must land ADOPTED, got {da['status']}"
        )
        assert da["vesting_status"] == "PENDING_REFERENDUM", (
            f"adoption opens the referendum window, got {da['vesting_status']}"
        )
        assert da["referendum_deadline"], "referendum_deadline must be stamped"


class TestReferendumQualificationCascade:
    def test_qualified_petition_repeals_da_and_invalidates_vesting(self, api):
        """PRD 3.8: "A timely petition whose valid signatures reach the
        requirement is disposed as `CERTIFIED_QUALIFIED`, and qualification
        detonates the agreement: the parent development agreement moves to
        `REPEALED` and its `vesting_status` to `INVALIDATED`."
        PRD 3.8: "The petition's `required_signature_count` is computed from
        the parent agreement as ten percent of `registered_voters`, with the
        raw decimal product rounded up to a whole signature before any
        comparison".

        1250 valid signatures meets ceil(0.10 × 12500) = 1250 exactly.

        Design: Difficulty/transitive_cascade/referendum_qualified_cascades_da_repeal_vesting_invalidate
        """
        ctx = setup_approved_application()
        da = draft_and_adopt_da(ctx, agreement_number="ORD-1", registered_voters=12500)
        petition = file_petition_now(ctx, da, valid_signature_count=1250)

        certified = certify_petition_now(ctx, petition["id"])
        assert_petition(certified)
        assert certified["status"] == "CERTIFIED_QUALIFIED", (
            f"1250 >= 1250 qualifies, got {certified['status']}"
        )

        da_after = validate_success(
            api.get_development_agreement(da["id"], ctx["authority_headers"])
        )
        assert da_after["status"] == "REPEALED", (
            f"cascade hop 2: agreement must be REPEALED, got {da_after['status']}"
        )
        assert da_after["vesting_status"] == "INVALIDATED", (
            f"cascade hop 3: vesting must be INVALIDATED, got "
            f"{da_after['vesting_status']}"
        )

    def test_petition_computes_required_signatures_and_qualifies_flag(self, api):
        """PRD 3.8: "The petition's `required_signature_count` is computed from
        the parent agreement as ten percent of `registered_voters`, with the
        raw decimal product rounded up to a whole signature before any
        comparison, and its `qualifies` flag is true exactly when
        `valid_signature_count` reaches the requirement — a count equal to the
        requirement qualifies, one short does not."

        Design: Difficulty/transitive_cascade/referendum_qualified_cascades_da_repeal_vesting_invalidate
        """
        ctx = setup_approved_application()
        da = draft_and_adopt_da(ctx, agreement_number="ORD-Q", registered_voters=12500)
        petition = file_petition_now(ctx, da, valid_signature_count=1250)

        assert_petition(petition)
        assert petition["required_signature_count"] == 1250, (
            f"ceil(0.10 × 12500) must be 1250, got "
            f"{petition['required_signature_count']}"
        )
        assert petition["qualifies"] is True, (
            "a count equal to the requirement qualifies"
        )


def certify_short_petition(api, ctx, petition_id):
    """Certify a petition whose count falls short of the requirement.

    PRD 3.8: "A timely petition whose count falls short is disposed as
    `CERTIFIED_INSUFFICIENT`; the same shortfall condition is the one reported
    as `ERR_INSUFFICIENT_SIGNATURES`."

    The sentence asserts both the disposition and the error for the same
    condition; either the certification succeeds and returns the disposed
    petition, or the certification is refused with the named error while the
    disposition is applied. The terminal disposition is asserted via a fresh
    read either way.
    """
    response = api.certify_referendum_petition(petition_id, ctx["authority_headers"])
    if response.status_code == 200:
        certified = validate_success(response)
        assert certified["status"] == "CERTIFIED_INSUFFICIENT", (
            f"a short petition must be disposed CERTIFIED_INSUFFICIENT, got "
            f"{certified['status']}"
        )
    else:
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SIGNATURES)

    after = validate_success(
        api.get_referendum_petition(petition_id, ctx["authority_headers"])
    )
    assert after["status"] == "CERTIFIED_INSUFFICIENT", (
        f"after certification the petition must stand CERTIFIED_INSUFFICIENT, "
        f"got {after['status']}"
    )
    return after


class TestSignatureThresholdBoundary:
    def test_one_signature_short_is_certified_insufficient(self, api):
        """PRD 3.8: "its `qualifies` flag is true exactly when
        `valid_signature_count` reaches the requirement — a count equal to the
        requirement qualifies, one short does not." and "A timely petition
        whose count falls short is disposed as `CERTIFIED_INSUFFICIENT`; the
        same shortfall condition is the one reported as
        `ERR_INSUFFICIENT_SIGNATURES`."

        Design: Difficulty/boundary_precision_check/referendum_signature_threshold_exact_count
        """
        ctx = setup_approved_application()
        da = draft_and_adopt_da(ctx, agreement_number="ORD-2", registered_voters=12500)
        petition = file_petition_now(ctx, da, valid_signature_count=1249)
        assert petition["required_signature_count"] == 1250
        assert petition["qualifies"] is False

        certify_short_petition(api, ctx, petition["id"])

        da_after = validate_success(
            api.get_development_agreement(da["id"], ctx["authority_headers"])
        )
        assert da_after["status"] == "ADOPTED", (
            f"an insufficient petition must not disturb the agreement, got "
            f"{da_after['status']}"
        )

    def test_exact_required_count_certifies_qualified(self, api):
        """PRD 3.8: "its `qualifies` flag is true exactly when
        `valid_signature_count` reaches the requirement — a count equal to the
        requirement qualifies, one short does not." and "A timely petition
        whose valid signatures reach the requirement is disposed as
        `CERTIFIED_QUALIFIED`".

        Design: Difficulty/boundary_precision_check/referendum_signature_threshold_exact_count
        """
        ctx = setup_approved_application()
        da = draft_and_adopt_da(ctx, agreement_number="ORD-3", registered_voters=12500)
        petition = file_petition_now(ctx, da, valid_signature_count=1250)

        certified = certify_petition_now(ctx, petition["id"])
        assert certified["status"] == "CERTIFIED_QUALIFIED", (
            f"1250 == 1250 must certify qualified (inclusive), got "
            f"{certified['status']}"
        )


def test_referendum_threshold_ceil_on_odd_voter_count(api):
    """PRD 3.8: "The petition's `required_signature_count` is computed from the
    parent agreement as ten percent of `registered_voters`, with the raw
    decimal product rounded up to a whole signature before any comparison".

    registered_voters=12501 gives the raw product 1250.1, which rounds UP to
    1251 — so 1250 valid signatures fall one short.

    Design: Corner/calculations/referendum_threshold_ceil_on_odd_voter_count
    """
    ctx = setup_approved_application()
    da = draft_and_adopt_da(ctx, agreement_number="ORD-C", registered_voters=12501)
    petition = file_petition_now(ctx, da, valid_signature_count=1250)

    assert petition["required_signature_count"] == 1251, (
        f"ceil(0.10 × 12501) = ceil(1250.1) must be 1251, got "
        f"{petition['required_signature_count']}"
    )
    assert petition["qualifies"] is False, "1250 < 1251 must not qualify"

    certify_short_petition(api, ctx, petition["id"])
