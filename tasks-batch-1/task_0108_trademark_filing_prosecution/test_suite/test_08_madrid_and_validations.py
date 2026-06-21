"""Madrid international applications (fee, forward state-guard), the registered
terminal lockdown, and the file-time / SOU / Madrid business validations.

Sources: Corner/calculations, Corner/state_machines, Corner/validations.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    setup_base_parties,
    setup_filed_application,
    setup_registered_application,
    setup_published_application,
    create_draft_application,
    add_item,
    create_madrid,
    examiner_headers,
)
from test_helpers.factories import (
    create_application_payload,
    create_goods_services_payload,
    create_statement_of_use_payload,
    create_madrid_application_payload,
)


class TestMadridFee:
    """Certifying a Madrid app with three designated countries sets fee_cents ==
    95300 (65300 base + 3*10000)."""

    def test_certify_three_countries_fee_is_95300(self, api):
        """PRD §3.7: "Certification computes and sets fee_cents as the Madrid base of
        65,300 cents plus a per-designated-country component of 10,000 cents
        multiplied by the number of entries in designated_countries."

        Design: Corner/calculations/madrid_fee_base_plus_per_country
        """
        base = setup_filed_application(class_numbers=(9,), filing_basis="USE", mark_text="GLOBAL")
        att_headers = base["att_headers"]
        madrid = create_madrid(base["application"]["id"], ["FR", "DE", "JP"], att_headers)
        certified = validate_success(api.certify_madrid_application(
            madrid["id"], examiner_headers()), 200)
        assert certified["fee_cents"] == 95300, (
            f"3 countries should be 65300+3*10000=95300, got {certified['fee_cents']}")
        assert certified["status"] == "CERTIFIED"


class TestMadridForwardStateGuard:
    """Forwarding a Madrid app still PENDING_CERTIFICATION (not yet certified) is
    rejected ERR_INVALID_STATE."""

    def test_forward_from_pending_certification_rejected(self, api):
        """PRD §3.7: "A certified application is then forwarded by an examiner to the
        international bureau, moving it from CERTIFIED to the terminal
        FORWARDED_TO_WIPO state."
        PRD §3.8: "the target resource must be in a state from which the requested
        transition is permitted, else ERR_INVALID_STATE."

        Design: Corner/state_machines/forward_from_pending_certification_returns_invalid_state
        """
        base = setup_filed_application(class_numbers=(9,), filing_basis="USE", mark_text="INTL")
        att_headers = base["att_headers"]
        madrid = create_madrid(base["application"]["id"], ["FR"], att_headers)
        res = api.forward_madrid_application(madrid["id"], examiner_headers())
        validate_error(res, "ERR_INVALID_STATE")


class TestRegisteredTerminalLockdown:
    """A REGISTERED application (terminal) rejects further transitions like
    approve-publication with ERR_INVALID_STATE."""

    def test_approve_publication_on_registered_rejected(self, api):
        """PRD §3.4: "an examiner registers it, moving it from PUBLISHED to the
        terminal REGISTERED state"
        PRD §3.8: "the target resource must be in a state from which the requested
        transition is permitted, else ERR_INVALID_STATE."

        Design: Corner/state_machines/register_terminal_lockdown_rejects_further_transition
        """
        base = setup_registered_application(class_numbers=(9,), mark_text="LOCKED")
        res = api.approve_publication(base["application"]["id"], examiner_headers())
        validate_error(res, "ERR_INVALID_STATE")


class TestForeignApplicantRequiresAttorney:
    """Filing for a GB-domiciled applicant with attorney_id null is rejected
    ERR_FOREIGN_REQUIRES_ATTORNEY."""

    def test_foreign_applicant_without_attorney_rejected(self, api):
        """PRD §3.2: "the foreign-representation check — if the applicant's
        is_foreign_domiciled is true, the attorney_id must be non-null, otherwise the
        filing is refused with ERR_FOREIGN_REQUIRES_ATTORNEY"

        Design: Corner/validations/foreign_applicant_without_attorney_rejected
        """
        base = setup_base_parties(class_numbers=(9,))
        # A foreign GB applicant self-acts (Applicant role), no attorney of record.
        foreign = validate_success(api.create_applicant(
            {"legal_name": "Foreign Ltd", "entity_type": "CORPORATION", "country_code": "GB"},
            base["applicant_headers"]), 201)
        from test_helpers import make_applicant_headers
        foreign_headers = make_applicant_headers(foreign["id"])
        app = validate_success(api.create_application(
            create_application_payload(
                applicant_id=foreign["id"], mark_text="OVERSEAS",
                filing_basis="USE", filing_tier="TEAS_STANDARD"),
            foreign_headers), 201)
        add_item(app["id"], base["nice_classes"][0]["id"], foreign_headers,
                 acting_headers=foreign_headers)
        res = api.file_application(app["id"], foreign_headers)
        validate_error(res, "ERR_FOREIGN_REQUIRES_ATTORNEY")


class TestTeasPlusRequiresPreApproved:
    """Filing a TEAS_PLUS application with one item whose pre_approved is false is
    rejected ERR_TEAS_PLUS_REQUIRES_PREAPPROVED."""

    def test_teas_plus_with_unapproved_item_rejected(self, api):
        """PRD §3.2: "the tier-compliance check — if the filing_tier is TEAS_PLUS,
        every GoodsServicesItem on the application must have pre_approved equal to
        true, otherwise the filing is refused with ERR_TEAS_PLUS_REQUIRES_PREAPPROVED"

        Design: Corner/validations/teas_plus_with_unapproved_item_rejected
        """
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="FREEFORM", filing_basis="USE", filing_tier="TEAS_PLUS")
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers,
                 description="custom freeform identification", pre_approved=False)
        res = api.file_application(app["id"], att_headers)
        validate_error(res, "ERR_TEAS_PLUS_REQUIRES_PREAPPROVED")


class TestStatementOfUseNotPermitted:
    """Filing a StatementOfUse for a USE-basis application (not INTENT/ALLOWED) is
    rejected ERR_SOU_NOT_PERMITTED."""

    def test_sou_on_use_basis_application_rejected(self, api):
        """PRD §3.4: "A statement may be filed only for an INTENT-basis application
        in ALLOWED status, and the extension_number must not exceed the application's
        granted-extension count; a violation of either condition is refused with
        ERR_SOU_NOT_PERMITTED."

        Design: Corner/validations/sou_on_use_basis_application_rejected
        """
        base = setup_published_application(class_numbers=(9,), filing_basis="USE", mark_text="USEONLY")
        att_headers = base["att_headers"]
        cur = validate_success(api.get_application(
            base["application"]["id"], att_headers), 200)
        res = api.create_statement_of_use(
            create_statement_of_use_payload(
                base["application"]["id"], cur["version"],
                specimen_url="https://x/spec.png", first_use_date="2025-12-01T00:00:00Z"),
            att_headers)
        validate_error(res, "ERR_SOU_NOT_PERMITTED")


class TestMadridCountriesInvalid:
    """Creating a Madrid app whose designated_countries includes 'US' is rejected
    ERR_MADRID_COUNTRIES_INVALID."""

    def test_madrid_designating_us_rejected(self, api):
        """PRD §3.7: "The array must be non-empty, free of duplicates, and must not
        include US; a violation is refused with ERR_MADRID_COUNTRIES_INVALID."

        Design: Corner/validations/madrid_designating_us_rejected
        """
        base = setup_filed_application(class_numbers=(9,), filing_basis="USE", mark_text="USDESIG")
        res = api.create_madrid_application(
            create_madrid_application_payload(base["application"]["id"], ["US", "FR"]),
            base["att_headers"])
        validate_error(res, "ERR_MADRID_COUNTRIES_INVALID")
