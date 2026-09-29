"""Writes whose gate lives in another entity's state, not in the target's own axis.

Cataloguing a work is a legal move on the composition's own catalogue axis, yet it
is refused until the governing composer agreement reaches `ACTIVE`; issuing a
blanket licence is a legal move on its own, yet it is refused until the blanket
agreement's coverage axis reads `ACTIVE` and stays refused the moment the
independent reporting axis flips to `DELINQUENT`.
"""

from test_helpers import (
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    advance_clock,
    assert_blanket_axes,
    assert_cents_equal,
    assert_composition_axes,
    assert_created,
    assert_declared_error,
    assert_ok,
    assert_same_instant,
    assert_status,
    assert_sweep_lists,
    composition_version,
    ledger_entries,
    make_composer_headers,
    new_blanket_tier,
    new_cataloged_work,
    new_composer,
    new_draft_agreement,
    new_draft_blanket,
    new_licensee,
    read_blanket_agreement,
    read_composition,
    read_license,
    select_ledger_entries,
)
from test_helpers import factories as build

DELINQUENCY_INSTANT = "2026-09-16T00:00:00Z"


def _work_under_unsigned_agreement(api):
    """A composer, an agreement left in `DRAFT`, and a fully tagged `INGESTED` work."""
    composer = new_composer(
        api,
        display_name="Hana Petrov",
        pro_affiliation="PRS",
        payee_country="GB",
        tax_withholding_pct=0.20,
    )
    agreement = new_draft_agreement(api, composer["id"], sync_fee_share_pct=35.00)
    composition = assert_created(
        api.create_composition(
            build.composition_payload(
                composer["id"],
                agreement["id"],
                title="Salt Flats",
                duration_sec=220,
                tempo_bpm=76,
                genre="CLASSICAL",
                mood_tags=["CALM", "HOPEFUL"],
                instrumentation=["STRINGS"],
            ),
            CATALOG_ADMIN,
        )
    )
    return composer, agreement, composition


class TestCatalogingWaitsOnTheComposerAgreement:
    def test_cataloging_is_refused_while_the_governing_agreement_is_still_draft(self, api):
        """PRD §3.2: "The governing agreement must be in `ACTIVE`, otherwise the request
        is refused with `ERR_AGREEMENT_NOT_ACTIVE` — a work whose composer has not
        signed cannot be sold."

        Design: Difficulty/cross_entity_state_dependency/cataloging_requires_active_composer_agreement
        """
        _composer, agreement, composition = _work_under_unsigned_agreement(api)
        assert_status(agreement, "DRAFT")
        assert_composition_axes(composition, "INGESTED", "AVAILABLE")

        assert_declared_error(
            api.catalog_composition(composition["id"], None, CATALOG_ADMIN),
            "ERR_AGREEMENT_NOT_ACTIVE",
        )

        assert_composition_axes(
            read_composition(api, composition["id"]), "INGESTED", "AVAILABLE"
        )

    def test_cataloging_is_refused_while_the_agreement_only_awaits_signature(self, api):
        """PRD §2.6: "**Governing agreement active** — on `POST /music-library/compositions/{composition_id}/catalog` and `POST /music-library/sync-requests/{sync_request_id}/quote`: the work's governing agreement is in any state other than `ACTIVE` → `ERR_AGREEMENT_NOT_ACTIVE` (409)."

        Design: Difficulty/cross_entity_state_dependency/cataloging_requires_active_composer_agreement
        """
        _composer, agreement, composition = _work_under_unsigned_agreement(api)
        pending = assert_ok(
            api.submit_agreement_for_signature(agreement["id"], None, RIGHTS_MANAGER)
        )
        assert_status(pending, "PENDING_SIGNATURE")

        assert_declared_error(
            api.catalog_composition(composition["id"], None, CATALOG_ADMIN),
            "ERR_AGREEMENT_NOT_ACTIVE",
        )

        assert_composition_axes(
            read_composition(api, composition["id"]), "INGESTED", "AVAILABLE"
        )

    def test_the_signature_that_activates_the_agreement_unblocks_cataloging(
        self, api, clock_origin
    ):
        """PRD §3.1: "Signature moves `PENDING_SIGNATURE → ACTIVE`, records `signed_at`
        from the logical clock, and settles the money that signing creates."

        Design: Difficulty/cross_entity_state_dependency/cataloging_requires_active_composer_agreement
        """
        composer, agreement, composition = _work_under_unsigned_agreement(api)
        assert_ok(api.submit_agreement_for_signature(agreement["id"], None, RIGHTS_MANAGER))
        assert_declared_error(
            api.catalog_composition(composition["id"], None, CATALOG_ADMIN),
            "ERR_AGREEMENT_NOT_ACTIVE",
        )

        signed = assert_ok(
            api.sign_agreement(
                agreement["id"],
                {"signature_name": "Hana Petrov"},
                make_composer_headers(composer["id"]),
            )
        )
        assert_status(signed, "ACTIVE")
        assert_same_instant(signed["signed_at"], clock_origin)

        cataloged = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
        assert_composition_axes(cataloged, "CATALOGED", "AVAILABLE")

        # The agreement is a ROYALTY_SPLIT with `advance_cents` 0, so signing settles
        # neither a signing advance nor a work-for-hire buyout.
        assert ledger_entries(api, composer["id"]) == []


def _blanket_ground(api):
    """A catalogued work, a blanket-eligible tier and a blanket agreement in `DRAFT`."""
    work = new_cataloged_work(
        api,
        {"display_name": "Kwame Boateng", "pro_affiliation": "ASCAP"},
        {"sync_fee_share_pct": 40.00},
        title="Accra Morning",
        duration_sec=150,
        tempo_bpm=116,
        genre="HIPHOP",
        mood_tags=["UPLIFTING"],
        instrumentation=["PERCUSSION", "BRASS"],
    )
    tier = new_blanket_tier(api, media_type="BROADCAST_TV", base_rate_cents=300000)
    licensee = new_licensee(
        api,
        legal_name="Coastline Channel",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    blanket = new_draft_blanket(
        api,
        licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=10,
        pool_share_pct=20.00,
    )
    return work, tier, blanket


def _attempt_blanket_issuance(api, work, tier, blanket, **overrides):
    """Ask for a blanket licence on the work, echoing the work's current version."""
    payload = build.blanket_license_payload(
        work.composition_id,
        blanket.agreement_id,
        tier["id"],
        composition_version(api, work.composition_id),
        **overrides,
    )
    return api.create_license(payload, LICENSING_AGENT)


def _activate_blanket(api, blanket):
    blanket.agreement = assert_ok(
        api.activate_blanket_agreement(blanket.agreement_id, None, LICENSING_AGENT)
    )
    return blanket.agreement


class TestBlanketIssuanceWaitsOnBothBlanketAxes:
    def test_blanket_issuance_is_refused_while_coverage_is_still_draft(self, api):
        """PRD §3.5: "For a blanket licence, `term_start` must fall inside the agreement's
        coverage interval, which is closed at `coverage_start` and open at
        `coverage_end`, or `ERR_TERM_OUTSIDE_COVERAGE`; and the blanket agreement must
        be in `ACTIVE` coverage with `reporting_status` `COMPLIANT` at the moment of
        issuance, or `ERR_BLANKET_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/blanket_license_issuance_requires_active_and_compliant_blanket
        """
        work, tier, blanket = _blanket_ground(api)
        assert_blanket_axes(blanket.agreement, "DRAFT", "COMPLIANT")

        assert_declared_error(
            _attempt_blanket_issuance(api, work, tier, blanket), "ERR_BLANKET_NOT_ACTIVE"
        )

        assert_blanket_axes(
            read_blanket_agreement(api, blanket.agreement_id), "DRAFT", "COMPLIANT"
        )
        assert read_composition(api, work.composition_id)["active_license_count"] == 0

    def test_blanket_issuance_succeeds_once_coverage_is_activated(self, api):
        """PRD §3.6: "Once active and compliant, blanket-mode licence issuance against
        the agreement becomes possible."

        Design: Difficulty/cross_entity_state_dependency/blanket_license_issuance_requires_active_and_compliant_blanket
        """
        work, tier, blanket = _blanket_ground(api)
        assert_declared_error(
            _attempt_blanket_issuance(api, work, tier, blanket), "ERR_BLANKET_NOT_ACTIVE"
        )

        activated = _activate_blanket(api, blanket)
        assert_blanket_axes(activated, "ACTIVE", "COMPLIANT")

        license_row = assert_created(_attempt_blanket_issuance(api, work, tier, blanket))
        assert license_row["license_mode"] == "BLANKET"
        assert_status(license_row, "ISSUED")
        assert license_row["is_exclusive"] is False
        assert license_row["licensee_id"] == blanket.licensee_id
        assert license_row["blanket_agreement_id"] == blanket.agreement_id
        assert license_row["term_start"].startswith("2026-08-01")
        assert license_row["term_months"] == 12
        assert license_row["term_end"].startswith("2027-07-31")
        assert read_composition(api, work.composition_id)["active_license_count"] == 1

    def test_a_blanket_licence_carries_no_fee_and_appends_no_sync_fee_entry(self, api):
        """PRD §3.5: "When `composer_sync_share_cents` works out to 0, as it always does
        under a work-for-hire agreement, no entry is appended at all."

        Design: Difficulty/cross_entity_state_dependency/blanket_license_issuance_requires_active_and_compliant_blanket
        """
        work, tier, blanket = _blanket_ground(api)
        _activate_blanket(api, blanket)

        license_row = assert_created(_attempt_blanket_issuance(api, work, tier, blanket))
        assert_cents_equal(license_row["final_fee_cents"], 0, "final_fee_cents")
        assert_cents_equal(
            license_row["composer_sync_share_cents"], 0, "composer_sync_share_cents"
        )

        entries = ledger_entries(api, work.composer_id)
        assert select_ledger_entries(entries, source_type="SYNC_FEE") == []

    def test_blanket_issuance_is_refused_again_once_the_reporting_axis_turns_delinquent(
        self, api
    ):
        """PRD §3.6: "While `DELINQUENT`, blanket-mode issuance against the agreement is
        refused with `ERR_BLANKET_NOT_ACTIVE` even though coverage itself is untouched —
        this is the lever that makes reporting matter."

        Design: Difficulty/cross_entity_state_dependency/blanket_license_issuance_requires_active_and_compliant_blanket
        """
        work, tier, blanket = _blanket_ground(api)
        _activate_blanket(api, blanket)
        license_row = assert_created(_attempt_blanket_issuance(api, work, tier, blanket))

        sweep = advance_clock(api, DELINQUENCY_INSTANT)
        assert_sweep_lists(
            sweep,
            expired_license_ids=[],
            expired_blanket_agreement_ids=[],
            delinquent_blanket_agreement_ids=[blanket.agreement_id],
        )

        delinquent = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(delinquent, "ACTIVE", "DELINQUENT")
        assert_same_instant(delinquent["delinquent_since"], DELINQUENCY_INSTANT)

        assert_declared_error(
            _attempt_blanket_issuance(
                api,
                work,
                tier,
                blanket,
                term_start=DELINQUENCY_INSTANT,
                term_months=6,
            ),
            "ERR_BLANKET_NOT_ACTIVE",
        )

        assert_status(read_license(api, license_row["id"]), "ISSUED")
        assert read_composition(api, work.composition_id)["active_license_count"] == 1
