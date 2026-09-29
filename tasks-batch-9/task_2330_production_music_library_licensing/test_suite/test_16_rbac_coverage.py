"""Role authorization, tenant ownership and separation of duties.

Every call here differs from a legal one only in the acting `X-User-ID` and
`X-User-Role`, so an implementation that admits any authenticated caller, or that
hard-codes one role per route, is caught. The refusals are paired with the
identical call made by the party the PRD does authorize.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    ACCOUNTANT_TWO,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    assert_cents_equal,
    assert_composer_money,
    assert_created,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_statement_figures,
    assert_status,
    finalize_statement,
    headers_without_role,
    make_composer_headers,
    make_headers,
    make_licensee_headers,
    new_active_agreement,
    new_active_blanket,
    new_cataloged_work,
    new_composer,
    new_draft_agreement,
    new_draft_statement,
    new_licensee,
    new_tier,
    open_usage_report,
    put_default_search_profile,
    quote_sync_request,
    read_agreement,
    read_composer,
    read_licensee,
    read_statement,
    review_sync_request,
    submit_sync_request,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_COMPOSER_IDENTITY_MISMATCH,
    ERR_COMPOSER_NOT_FOUND,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSEE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)

UNKNOWN_LICENSE_ID = "00000000-0000-4000-8000-000000000c11"
UNKNOWN_COMPOSER_ID = "00000000-0000-4000-8000-000000000d11"


# ---------------------------------------------------------------------------
# One exclusive operation per role, invoked by an adjacent peer role
# ---------------------------------------------------------------------------


def _peer_role_ground(api):
    """Two composers, one catalogued work, one licensee and two live requests.

    Composer one has an ACTIVE agreement and a CATALOGED work; composer two's
    agreement is left in PENDING_SIGNATURE so only its own composer could sign
    it. The licensee owns one UNDER_REVIEW and one QUOTED sync request.
    """
    composer_one = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")
    agreement_one = new_active_agreement(api, composer_one["id"], sync_fee_share_pct=40.00)
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer_one["id"],
                agreement_one["id"],
                title="Harbour Lights",
                duration_sec=180,
                tempo_bpm=130,
                genre="CINEMATIC",
                mood_tags=["EPIC"],
                instrumentation=["STRINGS"],
            ),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))

    composer_two = new_composer(api, display_name="Tomas Reyes", pro_affiliation="BMI")
    agreement_two = new_draft_agreement(api, composer_two["id"], sync_fee_share_pct=40.00)
    agreement_two = assert_ok(
        api.submit_agreement_for_signature(agreement_two["id"], None, RIGHTS_MANAGER)
    )

    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api,
        legal_name="Northwind Pictures",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=90000000,
    )

    reviewed = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                composition["id"],
                licensee["id"],
                tier["id"],
                media_type="FILM",
                distribution_scale="NATIONAL",
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )
    reviewed = assert_ok(api.review_sync_request(reviewed["id"], None, LICENSING_AGENT))

    quoted = assert_created(
        api.create_sync_request(
            build.sync_request_payload(
                composition["id"],
                licensee["id"],
                tier["id"],
                media_type="FILM",
                distribution_scale="LOCAL",
                requested_term_start="2026-09-01T00:00:00Z",
                requested_term_months=12,
            ),
            LICENSING_AGENT,
        )
    )
    assert_ok(api.review_sync_request(quoted["id"], None, LICENSING_AGENT))
    quoted = assert_ok(
        api.quote_sync_request(quoted["id"], build.quote_payload(14), LICENSING_AGENT)
    )

    return {
        "composer_one": composer_one,
        "agreement_one": agreement_one,
        "composer_two": composer_two,
        "agreement_two": agreement_two,
        "composition": composition,
        "tier": tier,
        "licensee": licensee,
        "reviewed_request": reviewed,
        "quoted_request": quoted,
    }


def _ingest_as_rights_manager(api, ground):
    return api.create_composition(
        build.composition_payload(
            ground["composer_one"]["id"],
            ground["agreement_one"]["id"],
            title="Rights Manager Upload",
            duration_sec=120,
            tempo_bpm=100,
            genre="CLASSICAL",
            mood_tags=["CALM"],
            instrumentation=["PIANO"],
        ),
        RIGHTS_MANAGER,
    )


def _write_search_profile_as_licensing_agent(api, ground):
    return api.put_search_profile(
        build.search_profile_payload(
            weight_mood=40, weight_genre=30, weight_instrumentation=20, weight_tempo=10
        ),
        LICENSING_AGENT,
    )


def _draft_agreement_as_catalog_admin(api, ground):
    return api.create_composer_agreement(
        build.royalty_split_agreement_payload(ground["composer_one"]["id"]), CATALOG_ADMIN
    )


def _open_licensee_as_catalog_admin(api, ground):
    return api.create_licensee(
        build.licensee_payload(
            legal_name="Admin Made Licensee", licensee_type="AGENCY", credit_limit_cents=100000
        ),
        CATALOG_ADMIN,
    )


def _quote_as_licensee(api, ground):
    return api.quote_sync_request(
        ground["reviewed_request"]["id"],
        build.quote_payload(14),
        make_licensee_headers(ground["licensee"]["id"]),
    )


def _append_ledger_entry_as_rights_manager(api, ground):
    return api.create_royalty_ledger_entry(
        build.ledger_entry_payload(
            ground["composer_one"]["id"], 1000, memo="Rights manager adjustment"
        ),
        RIGHTS_MANAGER,
    )


def _sign_agreement_as_rights_manager(api, ground):
    return api.sign_agreement(
        ground["agreement_two"]["id"], {"signature_name": "Tomas Reyes"}, RIGHTS_MANAGER
    )


def _accept_quote_as_licensing_agent(api, ground):
    return api.accept_sync_request(ground["quoted_request"]["id"], None, LICENSING_AGENT)


def _request_revision_as_licensing_agent(api, ground):
    return api.request_sync_revision(
        ground["quoted_request"]["id"],
        build.revision_payload("Agent-side revision"),
        LICENSING_AGENT,
    )


PEER_ROLE_REFUSALS = [
    pytest.param(_ingest_as_rights_manager, id="ingest_by_rights_manager"),
    pytest.param(
        _write_search_profile_as_licensing_agent, id="search_profile_by_licensing_agent"
    ),
    pytest.param(_draft_agreement_as_catalog_admin, id="agreement_draft_by_catalog_admin"),
    pytest.param(_open_licensee_as_catalog_admin, id="licensee_account_by_catalog_admin"),
    pytest.param(_quote_as_licensee, id="quote_by_licensee"),
    pytest.param(
        _append_ledger_entry_as_rights_manager, id="manual_ledger_entry_by_rights_manager"
    ),
    pytest.param(_sign_agreement_as_rights_manager, id="signature_by_rights_manager"),
    pytest.param(_accept_quote_as_licensing_agent, id="quote_acceptance_by_licensing_agent"),
    pytest.param(
        _request_revision_as_licensing_agent, id="revision_request_by_licensing_agent"
    ),
]


class TestExclusiveOperationsRefusePeerRoles:
    @pytest.mark.parametrize("invoke", PEER_ROLE_REFUSALS)
    def test_an_exclusive_operation_refuses_the_adjacent_peer_role(self, api, invoke):
        """PRD §2.1: "If `X-User-Role` is absent, or is present but is not one of the
        roles listed for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_peer_role
        """
        ground = _peer_role_ground(api)

        assert_declared_error(invoke(api, ground), ERR_UNAUTHORIZED)

    def test_refused_peer_calls_transition_nothing_and_reserve_nothing(self, api):
        """PRD §3.4: "Acceptance belongs to the licensee alone; a `LicensingAgent` may
        quote but may never accept on the buyer's behalf."

        Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_peer_role
        """
        ground = _peer_role_ground(api)
        reserved_before = read_licensee(api, ground["licensee"]["id"])["reserved_spend_cents"]

        for invoke in (
            _quote_as_licensee,
            _sign_agreement_as_rights_manager,
            _accept_quote_as_licensing_agent,
            _request_revision_as_licensing_agent,
        ):
            assert_declared_error(invoke(api, ground), ERR_UNAUTHORIZED)

        reviewed = assert_ok(
            api.get_sync_request(ground["reviewed_request"]["id"], LICENSING_AGENT)
        )
        assert_status(reviewed, "UNDER_REVIEW")
        assert reviewed["quoted_fee_cents"] is None

        licensee = read_licensee(api, ground["licensee"]["id"])
        assert_cents_equal(
            licensee["reserved_spend_cents"], reserved_before, "reserved_spend_cents"
        )
        assert_cents_equal(
            licensee["reserved_spend_cents"],
            ground["quoted_request"]["quoted_fee_cents"],
            "reserved_spend_cents",
        )

        assert_status(read_agreement(api, ground["agreement_two"]["id"]), "PENDING_SIGNATURE")

        quoted = assert_ok(api.get_sync_request(ground["quoted_request"]["id"], LICENSING_AGENT))
        assert_status(quoted, "QUOTED")
        assert quoted["revision_round"] == 0

    def test_an_unresolvable_licence_is_not_found_before_the_role_is_checked(self, api):
        """PRD §2.6: "**Path entity exists** — on every endpoint with a path parameter:
        the identifier in the path matches no row of the addressed entity → the
        matching not-found error (404)."

        Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_peer_role
        """
        _peer_role_ground(api)

        response = api.revoke_license(
            UNKNOWN_LICENSE_ID, {"reason": "Accountant-initiated revocation"}, ACCOUNTANT_ONE
        )
        assert_declared_error(response, ERR_LICENSE_NOT_FOUND)


# ---------------------------------------------------------------------------
# An absent or unrecognised X-User-Role header
# ---------------------------------------------------------------------------


HEADERLESS_STATES = [
    pytest.param(headers_without_role(), id="role_header_absent"),
    pytest.param(
        make_headers(CATALOG_ADMIN["X-User-ID"], "Archivist"), id="role_value_unrecognised"
    ),
]


class TestMissingOrUnrecognisedRoleHeader:
    @pytest.mark.parametrize("headers", HEADERLESS_STATES)
    def test_a_read_without_a_recognised_role_is_unauthorized(self, api, headers):
        """PRD §2.1: "If `X-User-Role` is absent, or is present but is not one of the
        roles listed for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/missing_x_user_role_header_is_unauthorized_unless_the_path_id_is_absent
        """
        composer = new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")

        assert_declared_error(api.get_composer(composer["id"], headers), ERR_UNAUTHORIZED)
        assert_ok(api.get_composer(composer["id"], CATALOG_ADMIN))

    def test_a_write_without_a_role_header_is_unauthorized(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which that user acts."

        Design: Corner/rbac/missing_x_user_role_header_is_unauthorized_unless_the_path_id_is_absent
        """
        new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")

        response = api.create_composer(
            build.composer_payload(display_name="Anonymous Upload"), headers_without_role()
        )
        assert_declared_error(response, ERR_UNAUTHORIZED)

    def test_an_unresolvable_composer_is_not_found_even_without_a_role_header(self, api):
        """PRD §2.7: "Identifiers in a URL path are resolved strictly left to right, and
        the request fails on the first identifier that matches no row, with the 404
        belonging to that entity."

        Design: Corner/rbac/missing_x_user_role_header_is_unauthorized_unless_the_path_id_is_absent
        """
        new_composer(api, display_name="Nadia Okoro", pro_affiliation="ASCAP")

        response = api.get_composer(UNKNOWN_COMPOSER_ID, headers_without_role())
        assert_declared_error(response, ERR_COMPOSER_NOT_FOUND)


# ---------------------------------------------------------------------------
# The licensee tenant boundary
# ---------------------------------------------------------------------------


def _two_licensee_ground(api):
    """Licensee one owns a QUOTED request, an ACTIVE blanket and a DUE report.

    Licensee two owns nothing at all, so every call it makes against licensee
    one's rows crosses the tenant boundary.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    owner = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=90000000,
    )
    intruder = new_licensee(
        api, legal_name="Harbour Media", licensee_type="AGENCY", credit_limit_cents=90000000
    )

    deal = Deal(work, tier, owner)
    submit_sync_request(
        api,
        deal,
        media_type="FILM",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
    )
    review_sync_request(api, deal)
    quote_sync_request(api, deal, 14)

    blanket = new_active_blanket(
        api,
        licensee=owner,
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=25.00,
    )
    open_usage_report(api, blanket)

    return {"work": work, "tier": tier, "deal": deal, "blanket": blanket, "intruder": intruder}


def _revision_by_other_licensee(api, ground):
    return api.request_sync_revision(
        ground["deal"].sync_request_id,
        build.revision_payload("Intruder revision", revised_term_months=6),
        make_licensee_headers(ground["intruder"]["id"]),
    )


def _report_creation_by_other_licensee(api, ground):
    return api.create_usage_report(
        build.usage_report_payload(
            ground["blanket"].agreement_id,
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T00:00:00Z",
        ),
        make_licensee_headers(ground["intruder"]["id"]),
    )


def _report_submission_by_other_licensee(api, ground):
    return api.submit_usage_report(
        ground["blanket"].usage_report_id, None, make_licensee_headers(ground["intruder"]["id"])
    )


def _cue_sheet_by_other_licensee(api, ground):
    return api.create_cue_sheet(
        build.cue_sheet_payload(
            [build.cue(ground["work"].composition_id, "THEME", 30)],
            usage_report_id=ground["blanket"].usage_report_id,
            production_title="Intruder Bulletin",
            broadcast_date="2026-08-12T00:00:00Z",
            market_tier="NETWORK",
        ),
        make_licensee_headers(ground["intruder"]["id"]),
    )


def _sync_request_for_another_licensee(api, ground):
    return api.create_sync_request(
        build.sync_request_payload(
            ground["work"].composition_id,
            ground["deal"].licensee_id,
            ground["tier"]["id"],
            media_type="FILM",
            distribution_scale="LOCAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        ),
        make_licensee_headers(ground["intruder"]["id"]),
    )


CROSS_TENANT_WRITES = [
    pytest.param(_revision_by_other_licensee, id="revision_on_another_licensees_request"),
    pytest.param(_report_creation_by_other_licensee, id="report_under_another_licensees_blanket"),
    pytest.param(
        _report_submission_by_other_licensee, id="submission_of_another_licensees_report"
    ),
    pytest.param(_cue_sheet_by_other_licensee, id="cue_sheet_under_another_licensees_report"),
    pytest.param(_sync_request_for_another_licensee, id="request_raised_for_another_licensee"),
]


class TestLicenseeTenantBoundary:
    @pytest.mark.parametrize("invoke", CROSS_TENANT_WRITES)
    def test_a_write_against_another_licensees_row_is_refused(self, api, invoke):
        """PRD §2.1: "A `Licensee`-role request touching another licensee's row is
        refused with `ERR_LICENSEE_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/licensee_tenant_boundary_holds_across_every_licensee_write
        """
        ground = _two_licensee_ground(api)

        assert_declared_error(invoke(api, ground), ERR_LICENSEE_MISMATCH)

        request = assert_ok(
            api.get_sync_request(ground["deal"].sync_request_id, LICENSING_AGENT)
        )
        assert_status(request, "QUOTED")
        assert request["revision_round"] == 0
        report = assert_ok(
            api.get_usage_report(ground["blanket"].usage_report_id, LICENSING_AGENT)
        )
        assert_status(report, "DUE")

    def test_the_owning_licensee_performs_the_same_writes_successfully(self, api):
        """PRD §3.4: "A `Licensee` — and only the owning licensee, on pain of
        `ERR_LICENSEE_MISMATCH` — sends a `revision_note` and optionally
        `revised_term_months`, `revised_distribution_scale` and
        `revised_exclusive_requested`, moving the request `QUOTED → REVISION_REQUESTED`."

        Design: Corner/rbac/licensee_tenant_boundary_holds_across_every_licensee_write
        """
        ground = _two_licensee_ground(api)
        owner_headers = make_licensee_headers(ground["deal"].licensee_id)

        revised = assert_ok(
            api.request_sync_revision(
                ground["deal"].sync_request_id,
                build.revision_payload("Owner revision", revised_term_months=6),
                owner_headers,
            )
        )
        assert_status(revised, "REVISION_REQUESTED")
        assert revised["revision_round"] == 1
        assert revised["requested_term_months"] == 6

        sheet = assert_created(
            api.create_cue_sheet(
                build.cue_sheet_payload(
                    [build.cue(ground["work"].composition_id, "THEME", 30)],
                    usage_report_id=ground["blanket"].usage_report_id,
                    production_title="Evening Bulletin",
                    broadcast_date="2026-08-12T00:00:00Z",
                    market_tier="NETWORK",
                ),
                owner_headers,
            )
        )
        assert sheet["usage_report_id"] == ground["blanket"].usage_report_id
        assert_credits_equal(sheet["total_credits"], 1.00, "total_credits")

        submitted = assert_ok(
            api.submit_usage_report(ground["blanket"].usage_report_id, None, owner_headers)
        )
        assert_status(submitted, "SUBMITTED")


# ---------------------------------------------------------------------------
# The composer identity boundary
# ---------------------------------------------------------------------------


def _two_composer_ground(api):
    """Composer one's agreement is PENDING_SIGNATURE, composer two's is ACTIVE.

    Composer one also owns a single manual adjustment entry, so its royalty
    preview and ledger listing have something to report.
    """
    composer_one = new_composer(
        api,
        display_name="Nadia Okoro",
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.30,
    )
    agreement_one = new_draft_agreement(api, composer_one["id"], sync_fee_share_pct=40.00)
    agreement_one = assert_ok(
        api.submit_agreement_for_signature(agreement_one["id"], None, RIGHTS_MANAGER)
    )

    composer_two = new_composer(api, display_name="Tomas Reyes", pro_affiliation="BMI")
    agreement_two = new_active_agreement(api, composer_two["id"], sync_fee_share_pct=40.00)

    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer_one["id"], 40000, memo="Catalogue bonus"),
            ACCOUNTANT_ONE,
        )
    )

    return {
        "composer_one": composer_one,
        "agreement_one": agreement_one,
        "composer_two": composer_two,
        "agreement_two": agreement_two,
    }


def _sign_another_composers_agreement(api, ground):
    return api.sign_agreement(
        ground["agreement_one"]["id"],
        {"signature_name": "Tomas Reyes"},
        make_composer_headers(ground["composer_two"]["id"]),
    )


def _preview_another_composers_royalties(api, ground):
    return api.get_royalty_preview(
        ground["composer_one"]["id"],
        build.preview_params(basis="ACCRUAL"),
        make_composer_headers(ground["composer_two"]["id"]),
    )


def _list_another_composers_ledger(api, ground):
    return api.list_royalty_ledger_entries(
        {"composer_id": ground["composer_one"]["id"]},
        make_composer_headers(ground["composer_two"]["id"]),
    )


CROSS_COMPOSER_CALLS = [
    pytest.param(_sign_another_composers_agreement, id="signing_another_composers_agreement"),
    pytest.param(_preview_another_composers_royalties, id="previewing_another_composers_period"),
    pytest.param(_list_another_composers_ledger, id="listing_another_composers_ledger"),
]


class TestComposerIdentityBoundary:
    @pytest.mark.parametrize("invoke", CROSS_COMPOSER_CALLS)
    def test_addressing_another_composers_row_is_refused(self, api, invoke):
        """PRD §2.1: "A `Composer`-role request that addresses or reads another
        composer's row — signing an agreement, deciding an amendment, requesting a
        royalty preview, or listing statements and ledger entries — is refused with
        `ERR_COMPOSER_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/composer_identity_mismatch_outranks_state_and_business_checks
        """
        ground = _two_composer_ground(api)

        assert_declared_error(invoke(api, ground), ERR_COMPOSER_IDENTITY_MISMATCH)
        assert_status(read_agreement(api, ground["agreement_one"]["id"]), "PENDING_SIGNATURE")

    def test_identity_mismatch_answers_before_the_agreement_state_check(self, api):
        """PRD §2.6: "**Composer ownership** — on agreement signing, amendment
        decisions, the composer royalty preview, and royalty ledger listing: role
        `Composer` addressing a composer other than `X-User-ID` →
        `ERR_COMPOSER_IDENTITY_MISMATCH` (403)."

        Design: Corner/rbac/composer_identity_mismatch_outranks_state_and_business_checks
        """
        ground = _two_composer_ground(api)

        response = api.decide_amendment(
            ground["agreement_two"]["id"],
            {"decision": "ACCEPT"},
            make_composer_headers(ground["composer_one"]["id"]),
        )
        assert_declared_error(response, ERR_COMPOSER_IDENTITY_MISMATCH)
        assert_status(read_agreement(api, ground["agreement_two"]["id"]), "ACTIVE")

    def test_the_owning_composer_signs_and_reads_its_own_preview(self, api, clock_origin):
        """PRD §3.1: "Only the composer can then sign, supplying a `signature_name`; the
        acting `X-User-ID` must be the agreement's composer or the request is refused
        with `ERR_COMPOSER_IDENTITY_MISMATCH`."

        Design: Corner/rbac/composer_identity_mismatch_outranks_state_and_business_checks
        """
        ground = _two_composer_ground(api)
        owner_headers = make_composer_headers(ground["composer_one"]["id"])

        signed = assert_ok(
            api.sign_agreement(
                ground["agreement_one"]["id"], {"signature_name": "Nadia Okoro"}, owner_headers
            )
        )
        assert_status(signed, "ACTIVE")
        # The `signature_name` echo is deliberately not asserted: PRD §3.1 names
        # `signature_name` only as a field the composer supplies, and the same
        # sentence enumerates what signature *records* — "records `signed_at`
        # from the logical clock".  Persisting and echoing the name back is one
        # faithful reading; treating it as a transient input is another, so the
        # response-visibility of that field is not uniquely derivable.
        assert_same_instant(signed["signed_at"], clock_origin)

        preview = assert_ok(
            api.get_royalty_preview(
                ground["composer_one"]["id"], build.preview_params(basis="ACCRUAL"), owner_headers
            )
        )
        assert_cents_equal(preview["accrual_gross_cents"], 40000, "accrual_gross_cents")
        assert_cents_equal(preview["projected_net_cents"], 28000, "projected_net_cents")


# ---------------------------------------------------------------------------
# Separation of duties on payment
# ---------------------------------------------------------------------------


def _finalized_statement_ground(api):
    """A statement finalized by the first accountant, net 28000 and PAYABLE."""
    composer = new_composer(
        api,
        display_name="Nadia Okoro",
        pro_affiliation="ASCAP",
        payee_country="US",
        tax_withholding_pct=0.30,
    )
    assert_created(
        api.create_royalty_ledger_entry(
            build.ledger_entry_payload(composer["id"], 40000, memo="Catalogue bonus"),
            ACCOUNTANT_ONE,
        )
    )
    statement = new_draft_statement(api, composer["id"])
    statement = finalize_statement(api, statement["id"])
    return {"composer": composer, "statement": statement}


class TestSeparationOfDutiesOnPayment:
    def test_the_finalizing_accountant_may_not_pay_the_statement(self, api):
        """PRD §2.1: "Paying a royalty statement requires that `X-User-ID` differ from
        the `finalized_by_user_id` already recorded on that statement; if they are equal
        the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_requires_two_distinct_accountant_user_ids
        """
        ground = _finalized_statement_ground(api)
        statement_id = ground["statement"]["id"]
        assert ground["statement"]["finalized_by_user_id"] == ACCOUNTANT_ONE["X-User-ID"]

        response = api.pay_royalty_statement(
            statement_id, {"payment_reference": "wire-self-approved"}, ACCOUNTANT_ONE
        )
        assert_declared_error(response, ERR_SEGREGATION_OF_DUTIES)

        reread = read_statement(api, statement_id)
        assert_status(reread, "FINALIZED")
        assert reread["paid_at"] is None
        assert reread["paid_by_user_id"] is None
        assert reread["payout_status"] == "PAYABLE"

    def test_a_second_accountant_identifier_moves_the_statement_to_paid(
        self, api, clock_origin
    ):
        """PRD §2.1: "Two distinct `RoyaltyAccountant` user identifiers are therefore
        needed to move any statement from `DRAFT` all the way to `PAID`."

        Design: Corner/rbac/segregation_of_duties_requires_two_distinct_accountant_user_ids
        """
        ground = _finalized_statement_ground(api)
        statement_id = ground["statement"]["id"]

        paid = assert_ok(
            api.pay_royalty_statement(
                statement_id, {"payment_reference": "wire-2026-08-0001"}, ACCOUNTANT_TWO
            )
        )
        assert_status(paid, "PAID")
        assert paid["paid_by_user_id"] == ACCOUNTANT_TWO["X-User-ID"]
        assert_same_instant(paid["paid_at"], clock_origin)
        assert_statement_figures(
            paid,
            gross_cents=40000,
            recouped_cents=0,
            withholding_cents=12000,
            net_payable_cents=28000,
            payout_status="PAYABLE",
        )

        assert_composer_money(
            read_composer(api, ground["composer"]["id"]),
            accrued_unpaid_cents=0,
            lifetime_paid_cents=28000,
        )


# ---------------------------------------------------------------------------
# Shared operations, once per declared role
# ---------------------------------------------------------------------------


def _shared_operations_ground(api):
    """One CATALOGED work, a written search profile, a licensee with an ACTIVE
    blanket agreement and the August report already opened by the agent."""
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    put_default_search_profile(
        api,
        weight_mood=40,
        weight_genre=30,
        weight_instrumentation=20,
        weight_tempo=10,
        tempo_tolerance_bpm=8,
    )
    tier = new_tier(
        api,
        code="FILM-STD",
        media_type="FILM",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=600000,
    )
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=90000000,
    )
    blanket = new_active_blanket(
        api,
        licensee=licensee,
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=60,
        pool_share_pct=25.00,
    )
    open_usage_report(api, blanket)
    return {"work": work, "tier": tier, "licensee": licensee, "blanket": blanket}


class TestSharedOperationsAcceptEveryDeclaredRole:
    def test_composer_creation_is_shared_by_catalog_admin_and_rights_manager(self, api):
        """PRD §3.1: "Either a `CatalogAdmin` or a `RightsManager` creates one with a
        `display_name` — the credit name that will appear on cue sheets — and three
        optional attributes: `pro_affiliation`, naming the performing-rights society the
        composer is registered with, one of `ASCAP`, `BMI`, `SESAC`, `PRS` or `NONE` and
        defaulting to `NONE`; `payee_country`, an ISO-3166 alpha-2 code used for the
        withholding audit trail and defaulting to `US`; and `tax_withholding_pct`, the
        withholding rate applied to post-recoupment statement amounts, expressed as a
        fraction between 0.00 and 0.50 with exactly two decimals and defaulting to 0.30."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        _shared_operations_ground(api)

        by_admin = assert_created(
            api.create_composer(
                build.composer_payload(display_name="Admin Created", pro_affiliation="SESAC"),
                CATALOG_ADMIN,
            )
        )
        by_rights_manager = assert_created(
            api.create_composer(
                build.composer_payload(display_name="Rights Created", pro_affiliation="SESAC"),
                RIGHTS_MANAGER,
            )
        )
        assert by_admin["id"] != by_rights_manager["id"]
        assert by_admin["display_name"] == "Admin Created"
        assert by_rights_manager["display_name"] == "Rights Created"

    def test_sync_request_creation_is_shared_by_the_agent_and_the_owning_licensee(self, api):
        """PRD §3.4: "Either the `Licensee` itself or a `LicensingAgent` creates it with
        the `composition_id` of the wanted work, the `licensee_id` of the buyer — which,
        for the `Licensee` role, must be that role's own `X-User-ID` — the `tier_id` of
        the rate card to price from, a `media_type`, a `distribution_scale`, a
        `requested_term_start` given as a date at midnight UTC, and a
        `requested_term_months` between 1 and 120."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        ground = _shared_operations_ground(api)
        licensee_id = ground["licensee"]["id"]

        by_agent = assert_created(
            api.create_sync_request(
                build.sync_request_payload(
                    ground["work"].composition_id,
                    licensee_id,
                    ground["tier"]["id"],
                    media_type="FILM",
                    distribution_scale="NATIONAL",
                    requested_term_start="2026-09-01T00:00:00Z",
                    requested_term_months=12,
                ),
                LICENSING_AGENT,
            )
        )
        by_licensee = assert_created(
            api.create_sync_request(
                build.sync_request_payload(
                    ground["work"].composition_id,
                    licensee_id,
                    ground["tier"]["id"],
                    media_type="FILM",
                    distribution_scale="LOCAL",
                    requested_term_start="2026-09-01T00:00:00Z",
                    requested_term_months=12,
                ),
                make_licensee_headers(licensee_id),
            )
        )
        assert_status(by_agent, "SUBMITTED")
        assert_status(by_licensee, "SUBMITTED")

    def test_usage_report_creation_is_shared_by_the_agent_and_the_owning_licensee(self, api):
        """PRD §3.6: "A report is created by the `Licensee` or a `LicensingAgent` with
        the `blanket_agreement_id`, a `period_start` that must be exactly a cadence
        boundary derived from `coverage_start`, and a `period_end` that must be exactly
        that boundary advanced by one cadence and pulled back one day; a period that is
        not a cadence boundary, whose end does not match the cadence, or that falls
        outside the coverage interval, is refused with `ERR_REPORT_PERIOD_INVALID`."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        ground = _shared_operations_ground(api)

        august = assert_ok(
            api.get_usage_report(ground["blanket"].usage_report_id, LICENSING_AGENT)
        )
        assert_status(august, "DUE")

        september = assert_created(
            api.create_usage_report(
                build.usage_report_payload(
                    ground["blanket"].agreement_id,
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-30T00:00:00Z",
                ),
                make_licensee_headers(ground["licensee"]["id"]),
            )
        )
        assert_status(september, "DUE")

    def test_cue_sheet_creation_is_shared_by_the_agent_and_the_owning_licensee(self, api):
        """PRD §3.7: "Either the `Licensee` that owns the parent or a `LicensingAgent`
        creates one with a `production_title` naming the programme, a `broadcast_date`
        given as a date at midnight UTC for the first transmission, a `market_tier` of
        `NETWORK`, `CABLE`, `LOCAL` or `DIGITAL` weighting that transmission, and a
        `cues` array of 1 to 20 objects, each carrying a `composition_id` that must
        reference an existing work, a `usage_type` of `THEME`, `FEATURE`, `BACKGROUND`
        or `LOGO`, and a `duration_sec` between 1 and 3600."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        ground = _shared_operations_ground(api)
        report_id = ground["blanket"].usage_report_id

        by_agent = assert_created(
            api.create_cue_sheet(
                build.cue_sheet_payload(
                    [build.cue(ground["work"].composition_id, "THEME", 30)],
                    usage_report_id=report_id,
                    production_title="Agent Filed Sheet",
                    broadcast_date="2026-08-10T00:00:00Z",
                    market_tier="NETWORK",
                ),
                LICENSING_AGENT,
            )
        )
        by_licensee = assert_created(
            api.create_cue_sheet(
                build.cue_sheet_payload(
                    [build.cue(ground["work"].composition_id, "FEATURE", 30)],
                    usage_report_id=report_id,
                    production_title="Licensee Filed Sheet",
                    broadcast_date="2026-08-11T00:00:00Z",
                    market_tier="NETWORK",
                ),
                make_licensee_headers(ground["licensee"]["id"]),
            )
        )
        assert by_agent["usage_report_id"] == report_id
        assert by_licensee["usage_report_id"] == report_id
        assert_credits_equal(by_agent["total_credits"], 1.00, "agent sheet total_credits")
        assert_credits_equal(by_licensee["total_credits"], 0.65, "licensee sheet total_credits")

    def test_facet_search_returns_the_same_ranking_to_each_of_its_three_roles(self, api):
        """PRD §3.3: "The `relevance_score` is the weighted figure multiplied by the
        availability factor and then by the recency factor, rounded half up to 2 decimals
        exactly once at the very end; because of the recency lift, a score above 100.00
        is legitimate and must not be clamped."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        ground = _shared_operations_ground(api)

        pages = []
        for headers in (
            CATALOG_ADMIN,
            LICENSING_AGENT,
            make_licensee_headers(ground["licensee"]["id"]),
        ):
            rows, meta = assert_page(api.search_compositions({"mood_tags": "EPIC"}, headers))
            assert meta["total_count"] == 1
            assert rows[0]["id"] == ground["work"].composition_id
            assert rows[0]["relevance_score"] == pytest.approx(110.00, abs=0.01)
            pages.append(rows)

        assert pages[0] == pages[1] == pages[2]

    def test_the_clock_endpoint_accepts_the_accountant_role(self, api):
        """PRD §2.5: "The service maintains a single logical clock that begins at
        `2026-08-01T00:00:00Z` and changes only when a caller submits a new instant as
        `to_iso8601` to `POST /_clock/set_current_utc` — the one endpoint mounted outside
        `/music-library`, available to `CatalogAdmin`, `RightsManager`, `LicensingAgent`
        and `RoyaltyAccountant`."

        Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
        """
        _shared_operations_ground(api)

        sweep = assert_ok(api.set_clock("2026-08-02T00:00:00Z", ACCOUNTANT_ONE))
        assert_same_instant(sweep["current_utc"], "2026-08-02T00:00:00Z")
