"""OperatingAgreement attachment and EINApplication lifecycle.

Covers PRD §3.3 (operating agreements + template-type matching) and
§3.4 (EIN application lifecycle, SoD on /approve, EIN derivation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_append_only_fields,
    assert_ein_application,
    assert_operating_agreement,
    assert_status,
    attach_operating_agreement,
    create_and_activate_entity,
    create_ein_application,
    create_ein_application_payload,
    create_operating_agreement_payload,
    create_submitted_ein,
    get_entity,
    make_filer_headers,
    make_tax_officer_headers,
    submit_ein_application,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# OperatingAgreement — PRD §3.3
# ---------------------------------------------------------------------------
class TestOperatingAgreementAttachment:

    @pytest.mark.parametrize("entity_type,template_code", [
        ("LLC", "LLC_MM"),
        ("LLC", "LLC_MGR"),
        ("CORP", "CORP_BYLAWS"),
        ("LP", "LP_AGREEMENT"),
    ])
    def test_template_match_accepted(self, api, entity_type,
                                     template_code):
        """PRD §3.3: "The template_code must match the entity's
        entity_type according to a fixed cross-reference: an LLC
        accepts the templates LLC_MM (member-managed) and LLC_MGR
        (manager-managed); a CORP accepts the single template
        CORP_BYLAWS; an LP accepts the single template LP_AGREEMENT."

        Claim: each (entity_type, template_code) pair listed in PRD §3.3
        is accepted; the returned row carries only id + created_at.
        """
        kwargs: dict = {}
        if entity_type == "CORP":
            kwargs["authorized_shares"] = 1
        entity, _ = create_and_activate_entity(
            entity_type=entity_type, **kwargs,
        )
        resp = api.create_operating_agreement(
            create_operating_agreement_payload(
                entity["id"], template_code=template_code,
            ),
            make_filer_headers(entity["id"]),
        )
        agreement = validate_success(resp, expected_status=201)
        assert_operating_agreement(agreement)
        assert agreement["template_code"] == template_code

    @pytest.mark.parametrize("entity_type,bad_template", [
        ("LLC", "CORP_BYLAWS"),
        ("LLC", "LP_AGREEMENT"),
        ("CORP", "LLC_MM"),
        ("CORP", "LP_AGREEMENT"),
        ("LP", "LLC_MGR"),
        ("LP", "CORP_BYLAWS"),
    ])
    def test_template_type_mismatch_rejected(self, api, entity_type,
                                             bad_template):
        """PRD §3.3: "A template that does not match the entity type is
        rejected with ERR_TEMPLATE_TYPE_MISMATCH and HTTP 422."

        Claim: cross-type template selections → ERR_TEMPLATE_TYPE_MISMATCH.
        """
        kwargs: dict = {}
        if entity_type == "CORP":
            kwargs["authorized_shares"] = 1
        entity, _ = create_and_activate_entity(
            entity_type=entity_type, **kwargs,
        )
        resp = api.create_operating_agreement(
            create_operating_agreement_payload(
                entity["id"], template_code=bad_template,
            ),
            make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_TYPE_MISMATCH.value)

    def test_operating_agreement_has_no_updated_at_or_version(self, api):
        """PRD §3.3: "An OperatingAgreement row carries only id and
        created_at — it has neither updated_at nor version because
        there is nothing to update after attachment."

        Claim: returned row omits updated_at and version.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        agreement = attach_operating_agreement(
            entity["id"], template_code="LLC_MM",
        )
        assert_append_only_fields(agreement)


# ---------------------------------------------------------------------------
# EINApplication — PRD §3.4
# ---------------------------------------------------------------------------
class TestEINApplicationLifecycle:

    def test_create_in_draft(self, api):
        """PRD §3.4: "The application starts with status of DRAFT and
        assigned_ein of null."

        Claim: a new EIN application has status=DRAFT and assigned_ein
        null.
        """
        entity, _ = create_and_activate_entity()
        resp = api.create_ein_application(
            create_ein_application_payload(entity["id"]),
            make_filer_headers(entity["id"]),
        )
        app = validate_success(resp, expected_status=201)
        assert_ein_application(app)
        assert_status(app, "DRAFT")
        assert app.get("assigned_ein") is None

    @pytest.mark.parametrize("bad_ssn", ["12345", "123", "abcd", ""])
    def test_invalid_ssn_last4_rejected(self, api, bad_ssn):
        """PRD §3.4: "The last-four-of-SSN field must be exactly four
        decimal digits, matching the regular expression ^[0-9]{4}$;
        anything else is rejected with ERR_INVALID_INPUT."

        Claim: non-4-digit SSN-last-4 → ERR_INVALID_INPUT.
        """
        entity, _ = create_and_activate_entity()
        resp = api.create_ein_application(
            create_ein_application_payload(
                entity["id"], responsible_party_ssn_last4=bad_ssn,
            ),
            make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_submit_transitions_draft_to_submitted(self, api):
        """PRD §3.4: "The Filer advances the application from DRAFT to
        SUBMITTED, at which point the parent entity must be ACTIVE"

        Claim: submit → SUBMITTED.
        """
        entity, _ = create_and_activate_entity()
        app = create_ein_application(entity["id"])
        resp = api.submit_ein_application(
            app["id"], make_filer_headers(entity["id"]),
        )
        submitted = validate_success(resp)
        assert_status(submitted, "SUBMITTED")

    def test_approve_mints_ein_and_writes_to_entity(self, api,
                                                    tax_officer_headers):
        """PRD §3.4: "approval transitions SUBMITTED to APPROVED, mints
        the next available EIN in the format ^[0-9]{2}-[0-9]{7}$,
        writes that value into assigned_ein, and writes the same value
        into the parent BusinessEntity.ein"

        Claim: approve → APPROVED + assigned_ein matches XX-XXXXXXX +
        the same value lands on BusinessEntity.ein.
        """
        entity, _ = create_and_activate_entity()
        submitted = create_submitted_ein(entity["id"])
        resp = api.approve_ein_application(
            submitted["id"], tax_officer_headers,
        )
        approved = validate_success(resp)
        assert_status(approved, "APPROVED")
        ein = approved["assigned_ein"]
        assert ein is not None and len(ein) == 10 and ein[2] == "-", (
            f"Expected EIN as XX-XXXXXXX, got {ein!r}"
        )
        assert ein.replace("-", "").isdigit()
        # Derived field reconciliation on parent entity.
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["ein"] == ein, (
            f"Entity.ein {ent['ein']!r} must match assigned_ein {ein!r}"
        )

    def test_approve_with_entity_id_as_user_id_violates_segregation(
        self, api,
    ):
        """PRD §3.4: "the TaxOfficer's X-User-ID must not equal the
        BusinessEntity.id that owns the application — that is, the
        entity cannot approve its own EIN — and a violation yields
        ERR_SEGREGATION_OF_DUTIES with HTTP 403."

        Claim: TaxOfficer caller whose X-User-ID equals the owning
        BusinessEntity.id → ERR_SEGREGATION_OF_DUTIES.
        """
        entity, _ = create_and_activate_entity()
        submitted = create_submitted_ein(entity["id"])
        # Caller is TaxOfficer but X-User-ID is the entity's own id.
        bad_headers = make_tax_officer_headers(entity["id"])
        resp = api.approve_ein_application(submitted["id"], bad_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_reject_transitions_to_rejected(self, api,
                                            tax_officer_headers):
        """PRD §3.4: "Rejection transitions SUBMITTED to REJECTED without
        minting."

        Claim: reject → REJECTED with no EIN.
        """
        entity, _ = create_and_activate_entity()
        submitted = create_submitted_ein(entity["id"])
        resp = api.reject_ein_application(
            submitted["id"], tax_officer_headers,
        )
        rejected = validate_success(resp)
        assert_status(rejected, "REJECTED")
        assert rejected.get("assigned_ein") is None
