"""Computed reads at the corners of their own formulas.

Canonical ordering, an inclusive band boundary, a threshold that only the third
entry clears, an absorbing replay step, an excluded aggregate row and the two
per-query rate tiers - each pinned to the value the PRD's own order produces.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_field_values,
    assert_row_count,
    rows_of,
)
from test_helpers.fixtures import (
    adjudicate_session,
    append_evidence,
    create_active_credential,
    create_approved_verifier,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    complete_presentation,
    open_address_change,
    open_presentation_session,
    open_proofing_session,
    register_reader_app,
    set_clock,
    submit_session,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    make_holder_headers,
    make_verifier_operator_headers,
)

_THREE_ELEMENTS = ["family_name", "birth_date", "age_over_21"]


class TestMinimisationProjection:
    """The projection emits canonical order, not the order the reader asked in."""

    def test_the_allowed_elements_come_back_in_canonical_core_order(self, api):
        """All three requested elements are allowed, so nothing is withheld - what
        is under test is purely the order of the returned array.

        PRD 3.8: "The eleven core elements, in canonical order, are `family_name`,
        `given_name`, `birth_date`, `portrait`, `document_number`, `expiry_date`,
        `issuing_authority`, `driving_privileges`, `address`, `age_over_18` and
        `age_over_21`."
        PRD 3.8: "`minimized_elements` contains every core element that appears
        both in the session's `requested_elements` and in the allow-list, emitted
        in canonical core order."

        Design: Corner/calculations/minimization_emits_canonical_core_element_order_not_request_order
        """
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": _THREE_ELEMENTS,
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": _THREE_ELEMENTS,
                "base_rate_cents": 30,
            },
        )

        session = open_presentation_session(
            api,
            world,
            context="ROUTINE",
            purpose="verify identity at counter",
            requested_elements=["age_over_21", "family_name", "birth_date"],
            handset_handling="TAP_TO_READ",
            retention_days=7,
        )
        assert_field_values(
            session,
            {
                "state": "CONSENT_PENDING",
                "minimized_elements": ["family_name", "birth_date", "age_over_21"],
                "withheld_elements": [],
                "excess_element_count": 0,
                "age_attestation_only": False,
                "disclosed_element_count": 0,
            },
        )


class TestInvoiceLineSelection:
    """Which applications contribute a line, and what a tier-one line is worth."""

    def test_an_application_still_pending_listing_contributes_no_line(self, api):
        """Two applications, one listed and one pending: only the listed one has
        ever been in a position to serve a query, so the line count is one.

        PRD 3.9: "The applications considered are those of the verifier whose
        `trust_state` is `LISTED` or `DELISTED`, iterated in ascending `created_at`
        order; applications still in `PENDING` are excluded entirely, because they
        have never been in a position to serve a query."

        Design: Corner/calculations/invoice_excludes_pending_reader_apps_from_its_lines
        """
        verifier = create_approved_verifier(api)
        listed = register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            base_rate_cents=30,
        )
        register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-b",
            certificate_serial="SER-B1",
            base_rate_cents=30,
        )
        validate_success(
            api.decide_reader_listing(listed["id"], {"decision": "LIST"}, ADMIN)
        )

        invoice = validate_success(
            api.get_invoice(
                verifier["id"], make_verifier_operator_headers(verifier["id"])
            )
        )
        assert_field_values(invoice, {"line_count": 1, "surcharge_pct": 0})
        assert_cents(invoice, "invoice_amount_cents", 0)
        assert_cents(invoice, "billable_query_balance_cents", 0)

    def test_a_single_query_is_billed_at_the_untouched_base_rate(self, api):
        """One query sits inside the first volume band, so no tier factor and no
        volume discount may be applied to the line.

        PRD 3.9: "When `query_count` is at most 100, the rate is the application's
        `base_rate_cents` unchanged."
        PRD 3.7: "each carries its live `query_count` - the number of that
        application's presentation sessions that reached `COMPLETED` - and its
        `volume_discount_pct`, which is 10 percent once `query_count` has reached
        250 and nothing at all below that."

        Design: Corner/calculations/invoice_tier_one_line_is_base_rate_times_query_count
        """
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": ["family_name", "age_over_21"],
                "base_rate_cents": 45,
            },
        )
        operator = make_verifier_operator_headers(world["verifier"]["id"])
        complete_presentation(
            api,
            world,
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )

        invoice = validate_success(api.get_invoice(world["verifier"]["id"], operator))
        assert_field_values(invoice, {"line_count": 1, "surcharge_pct": 0})
        assert_cents(invoice, "invoice_amount_cents", 45)
        assert_cents(invoice, "billable_query_balance_cents", 45)

        apps = rows_of(
            api.list_verifier_reader_apps(world["verifier"]["id"], operator)
        )
        assert_field_values(apps[0], {"query_count": 1, "volume_discount_pct": 0})


class TestExposureIndexPseudonymReuse:
    """Repeat sightings only become a tracking signal at the third one."""

    def test_only_the_third_sighting_of_a_credential_scores(self, api):
        """Three disclosures score reuse indices 1, 2 and 3; just one of them
        reaches the tracking threshold, so the index is 20 and not 60.

        PRD 3.8: "Its `pseudonym_reuse_index` is one more than the number of
        existing log entries that share both the same `verifier_id` and the same
        `credential_pseudonym` and whose `recorded_at` is strictly earlier - so a
        verifier's first sighting of a credential scores 1, its second scores 2,
        and at 3 or above the entry begins to count as a tracking signal."
        PRD 3.9: "**Pseudonym reuse**: the number of entries whose
        `pseudonym_reuse_index` is 3 or more, weighted 20 points each"

        Design: Corner/calculations/exposure_index_counts_pseudonym_reuse_only_from_the_third_entry
        """
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": ["family_name", "age_over_21"],
                "base_rate_cents": 30,
            },
        )
        verifier_id = world["verifier"]["id"]

        for instant in (None, "2026-08-01T01:00:00Z", "2026-08-01T03:00:00Z"):
            if instant is not None:
                set_clock(api, instant)
            last = complete_presentation(
                api,
                world,
                purpose="age check at till",
                requested_elements=["family_name", "age_over_21"],
                handset_handling="NO_SURRENDER",
                retention_days=7,
            )
        assert_field_values(
            last, {"state": "COMPLETED", "disclosed_element_count": 2}
        )

        verifier = validate_success(api.get_verifier(verifier_id, ADMIN))
        assert_field_values(
            verifier,
            {
                "exposure_index": 20,
                "trust_status": "APPROVED",
                "probation_strike_count": 0,
            },
        )

        report = validate_success(api.get_exposure_index(verifier_id, PRIVACY_AUDITOR))
        assert_field_values(
            report,
            {
                "rolling_window_index": 20,
                "rolling_window_entry_count": 3,
                "since_last_attestation_index": 20,
                "since_attestation_entry_count": 3,
            },
        )

        entries = assert_row_count(
            api.list_verifier_log_entries(verifier_id, PRIVACY_AUDITOR), 3
        )
        assert [entry["pseudonym_reuse_index"] for entry in entries] == [1, 2, 3]


class TestAssuranceBandBoundary:
    """The IAL2 comparison is inclusive at exactly 420 points."""

    def test_a_score_of_exactly_420_is_ial2_and_not_the_band_below(self, api):
        """250 plus 90 plus 80 lands exactly on the boundary, which the PRD makes
        inclusive, and the validity window is the profile's 180 days.

        PRD 3.2: "It requires the strict score to be at least 260 points; a lower
        score is rejected with `ERR_ASSURANCE_LEVEL_INSUFFICIENT` (HTTP 422). On
        success `achieved_assurance_level` is written from the recorded score -
        `IAL2` at 420 points or above, `IAL1_5` at 260 points or above, otherwise
        `IAL1` - `verified_at` is set to the current logical instant,
        `assurance_expires_at` is set to that instant advanced by the profile's
        `proofing_validity_days` (180 days by default), `adjudicator_user_id` is
        set to the acting `X-User-ID`"

        Design: Corner/calculations/adjudication_score_of_exactly_420_maps_to_ial2
        """
        create_profile(api)
        holder = create_holder(api)
        session = open_proofing_session(api, holder["id"])
        append_evidence(
            api,
            session["id"],
            [
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:00:00Z",
                    "source_reference": "doc-1",
                },
                {
                    "evidence_type": "KNOWLEDGE_CHECK",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:10:00Z",
                    "source_reference": "kba-1",
                },
                {
                    "evidence_type": "ADDRESS_CORROBORATION",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:20:00Z",
                    "source_reference": "utility-1",
                },
            ],
        )
        submit_session(api, session["id"])

        verified = adjudicate_session(api, session["id"], "VERIFY")
        assert_field_values(
            verified,
            {
                "state": "VERIFIED",
                "adjudication_score": 420,
                "achieved_assurance_level": "IAL2",
                "assurance_expires_at": "2027-01-28T00:00:00Z",
                "adjudicator_user_id": "ca-001",
            },
        )

        preview = validate_success(
            api.get_assurance_preview(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            preview,
            {
                "adjudication_score": 420,
                "adjudication_assurance_level": "IAL2",
                "evidence_type_count": 3,
            },
        )


class TestRevocationReplay:
    """A four-entry ledger, one ignored reinstatement and an absorbing revocation."""

    def test_the_replay_ends_revoked_and_reports_the_newest_sequence(self, api):
        """Loss, recovery, loss again and a wipe leave four entries; the
        reinstatement lifted only the suspension that preceded it.

        PRD 3.4: "An entry with status `SUSPENDED` sets the effective status to
        suspended. An entry with status `REVOKED` sets it to revoked and is
        **absorbing**: no later entry can lift it ... An entry with status
        `REINSTATED` returns the effective status to valid **only** when the
        effective status at that point in the replay is suspended"
        PRD 3.4: "The credential's revocation-status read reports the replayed
        `status`, the `entry_sequence` of the newest entry (zero when there are
        none), that entry's `effective_at`, a `staleness_seconds` ... and an
        `is_fresh` verdict that is true when `staleness_seconds` is at most the
        profile's `revocation_freshness_seconds`"

        Design: Corner/calculations/revocation_replay_over_four_entries_ends_revoked
        """
        bundle = create_active_credential(api)
        device_id = bundle["device"]["id"]
        credential_id = bundle["credential"]["id"]
        holder_headers = make_holder_headers(bundle["holder"]["id"])

        validate_success(api.report_device_lost(device_id, holder_headers))
        validate_success(
            api.recover_device(
                device_id, {"reattestation_token": "reatt-tok-1"}, holder_headers
            )
        )
        validate_success(api.report_device_lost(device_id, holder_headers))
        validate_success(api.wipe_device(device_id, ADMIN))

        status = validate_success(
            api.get_revocation_status(credential_id, PRIVACY_AUDITOR)
        )
        assert_field_values(
            status,
            {
                "status": "REVOKED",
                "entry_sequence": 4,
                "effective_at": "2026-08-01T00:00:00Z",
                "staleness_seconds": 0,
                "is_fresh": True,
            },
        )

        entries = assert_row_count(
            api.list_revocation_entries(credential_id, PRIVACY_AUDITOR), 4
        )
        assert_field_values(
            entries[1], {"status": "REINSTATED", "reason": "RECOVERY"}
        )
        assert entries[3]["status"] == "REVOKED"


class TestOrderRollupExcludesSupersededChildren:
    """A superseded child stops counting, which closes its order immediately."""

    def test_superseding_the_only_delivery_closes_the_older_order_completed(self, api):
        """The second address change supersedes the first order's only delivery, so
        that order re-derives a delivery count of zero and closes as completed.

        PRD 3.5: "Alongside the cascade, any delivery still sitting in `PENDING`
        against the same credential from an **older** order moves `PENDING ->
        SUPERSEDED`, because the newer order carries strictly fresher data. A
        superseded delivery is excluded from its own order's counters, and the
        older order's status is re-derived immediately."
        PRD 3.5: "The rollup counts `delivery_count` as the children whose `status`
        is anything other than `SUPERSEDED` ... when `delivery_count` is zero, the
        status is `COMPLETED` ... When the resulting status is `COMPLETED` or
        `FAILED_CLOSED` and `closed_at` was still null, `closed_at` is set to the
        current logical instant"

        Design: Corner/calculations/order_rollup_excludes_superseded_delivery_and_closes_completed
        """
        bundle = create_active_credential(api)
        holder_id = bundle["holder"]["id"]

        first_order = open_address_change(api, holder_id, address_line1="22 Birch Lane")
        second_order = open_address_change(api, holder_id, address_line1="31 Elm Court")
        assert_field_values(
            second_order,
            {"status": "OPEN", "delivery_count": 1, "target_address_version": 3},
        )

        closed = validate_success(api.get_update_order(first_order["id"], ADMIN))
        assert_field_values(
            closed,
            {
                "status": "COMPLETED",
                "delivery_count": 0,
                "delivered_count": 0,
                "failed_count": 0,
                "closed_at": "2026-08-01T00:00:00Z",
            },
        )

        superseded = assert_row_count(
            api.list_order_deliveries(first_order["id"], ADMIN), 1
        )
        assert superseded[0]["status"] == "SUPERSEDED"

        live = rows_of(api.list_order_deliveries(second_order["id"], ADMIN))
        assert live[0]["status"] == "PENDING"
