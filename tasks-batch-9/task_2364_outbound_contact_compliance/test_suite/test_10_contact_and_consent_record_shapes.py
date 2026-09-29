"""Record shapes and identity handling for contacts, consent records,
revocation requests and suppression entries.

Every test builds its own preconditions through the documented endpoints,
because the database is empty when the test starts.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    InternalDncStatus,
    ListType,
    PhoneType,
    PHONE_C1,
    RiskTier,
    RndResult,
    STATE_CA,
    SuppressionStatus,
    TZ_LOS_ANGELES,
    UTC_OFFSET_LOS_ANGELES,
    assert_attempt_budget_conserved,
    assert_common_fields,
    assert_consent_census_conserved,
    assert_created,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    make_dialer_operator_headers,
)

# The canonical working instant the recipes below drive the logical clock to, and
# the millisecond rendering the server is required to stamp rows with while the
# clock sits there.
_CLOCK_ISO = "2026-08-03T00:00:00Z"
_CLOCK_STAMP = "2026-08-03T00:00:00.000Z"

_NATIONAL_LIST_PHONES = ("+18005550000", "+18005550001", "+18005550002")


def _fresh_contact_payload(**overrides):
    """A contact import payload with the two optional fields omitted."""
    defaults = {
        "phone_number": PHONE_C1,
        "state_code": STATE_CA,
        "utc_offset_minutes": UTC_OFFSET_LOS_ANGELES,
        "time_zone_label": TZ_LOS_ANGELES,
        "phone_type": None,
        "attempt_budget_total": None,
    }
    defaults.update(overrides)
    return factories.contact_payload(**defaults)


class TestContactImportShape:
    """Importing a consumer and reading the row back."""

    def test_01_import_echoes_inputs_and_stamps_the_declared_openings(
        self, clocked_world
    ):
        """A contact import returns 201 with every input echoed and every
        derived counter at its declared opening value.

        PRD 3.1: "A freshly imported contact is fully determined:
        `attempts_charged` is 0, `attempt_budget_remaining` equals
        `attempt_budget_total`, `internal_dnc_status` is `CLEAR`, `risk_tier` is
        `LOW`, all five census counters — `active_consent_count`,
        `suspended_consent_count`, `revoked_consent_count`,
        `superseded_consent_count` and `total_consent_count` — are 0,
        `overdue_propagation_count` is 0, `rnd_result` is `NOT_CHECKED`,
        `rnd_checked_at` and `rnd_claimed_consent_date` are null, and
        `rnd_safe_harbor_eligible` is false. The record is returned with a 201."
        PRD 2.4: "`version` (integer): a counter that starts at 1 when the row is
        created and increments by exactly 1 on every mutation of that row."

        Design: Corner/entities/contact_creation_persists_every_input_field
        """
        contact = clocked_world.create_contact(
            phone_number=PHONE_C1,
            state_code=STATE_CA,
            utc_offset_minutes=UTC_OFFSET_LOS_ANGELES,
            time_zone_label=TZ_LOS_ANGELES,
            phone_type=PhoneType.WIRELESS,
            attempt_budget_total=5,
        )

        assert_common_fields(contact)
        assert_fields_equal(
            contact,
            phone_number=PHONE_C1,
            state_code=STATE_CA,
            utc_offset_minutes=UTC_OFFSET_LOS_ANGELES,
            time_zone_label=TZ_LOS_ANGELES,
            phone_type=PhoneType.WIRELESS,
            attempt_budget_total=5,
            attempts_charged=0,
            attempt_budget_remaining=5,
            internal_dnc_status=InternalDncStatus.CLEAR,
            risk_tier=RiskTier.LOW,
            rnd_result=RndResult.NOT_CHECKED,
            rnd_safe_harbor_eligible=False,
            total_consent_count=0,
            overdue_propagation_count=0,
        )
        assert_fields_null(contact, "rnd_checked_at", "rnd_claimed_consent_date")
        assert_version_is(contact, 1)
        assert_timestamp_equals(contact["created_at"], _CLOCK_STAMP)
        assert_attempt_budget_conserved(contact)
        assert_consent_census_conserved(contact)

    def test_02_reading_a_contact_returns_the_untouched_stored_row(
        self, clocked_world
    ):
        """Reading an imported contact returns the stored values with the row
        still at version 1 and `updated_at` still on the creation instant.

        PRD 3.1: "Reading a contact returns its live suppression status, risk
        tier, consent census, attempt-budget numbers and reassigned-number
        stamps, and is open to all five roles."
        PRD 2.4: "`updated_at` (string): an ISO 8601 UTC timestamp in the same
        format, refreshed on every mutation of the row."

        Design: Corner/entities/contact_retrieval_returns_the_stored_row
        """
        contact = clocked_world.create_contact(
            phone_number=PHONE_C1,
            state_code=STATE_CA,
            utc_offset_minutes=UTC_OFFSET_LOS_ANGELES,
            time_zone_label=TZ_LOS_ANGELES,
            phone_type=PhoneType.WIRELESS,
            attempt_budget_total=3,
        )

        read_back = assert_ok(
            clocked_world.api.get_contact(
                contact["id"], make_dialer_operator_headers()
            )
        )

        assert_fields_equal(
            read_back,
            id=contact["id"],
            phone_number=PHONE_C1,
            state_code=STATE_CA,
            attempt_budget_total=3,
            attempt_budget_remaining=3,
            attempts_charged=0,
        )
        assert_version_is(read_back, 1)
        assert read_back["updated_at"] == read_back["created_at"], (
            "no mutation has touched the row, so updated_at must still equal "
            "created_at, got %s vs %s"
            % (read_back["updated_at"], read_back["created_at"])
        )

    def test_03_omitted_optional_import_fields_take_their_declared_defaults(
        self, clocked_world
    ):
        """Omitting `phone_type` and `attempt_budget_total` yields `UNKNOWN` and
        3, with the remaining budget derived from the defaulted total.

        PRD 3.1: "`phone_type` records the carrier classification captured at
        import: one of `WIRELESS`, `LANDLINE` or `UNKNOWN`, defaulting to
        `UNKNOWN` when omitted."
        PRD 3.1: "`attempt_budget_total` is the lifetime permitted-attempt
        allowance for this consumer and must lie between 1 and 20 inclusive,
        defaulting to 3."

        Design: Corner/entities/contact_defaults_applied_when_optional_inputs_omitted
        """
        contact = assert_created(
            clocked_world.api.create_contact(
                _fresh_contact_payload(), clocked_world.admin
            )
        )

        assert_fields_equal(
            contact,
            phone_type=PhoneType.UNKNOWN,
            attempt_budget_total=3,
            attempt_budget_remaining=3,
            attempts_charged=0,
        )
        assert_attempt_budget_conserved(contact)

    def test_04_system_managed_properties_ignore_client_supplied_values(
        self, clocked_world
    ):
        """A client that submits its own `id`, `created_at`, `version` and
        `attempts_charged` still gets a server-minted identifier, version 1,
        `attempts_charged` 0 and a `created_at` on the logical clock instant.

        PRD 2.4: "All eleven resource families in this domain — contacts, consent
        records, revocation requests, suppression entries, scrub jobs, campaigns,
        dialer profiles, agent scripts, calling-window policies, contact attempts
        and complaints — carry the same four system-managed properties, and none
        of them omits any of the four:"
        PRD 2.4: "`id` (string): a server-minted unique identifier formatted as a
        UUID, with no type prefix of any kind."
        PRD 3.1: "A freshly imported contact is fully determined:
        `attempts_charged` is 0, `attempt_budget_remaining` equals
        `attempt_budget_total`, `internal_dnc_status` is `CLEAR`, `risk_tier` is
        `LOW`"

        Design: Corner/entities/contact_system_fields_are_server_stamped_input_ignored
        """
        spoofed_id = "11111111-1111-1111-1111-111111111111"

        contact = assert_created(
            clocked_world.api.create_contact(
                _fresh_contact_payload(
                    id=spoofed_id,
                    created_at="2020-01-01T00:00:00Z",
                    version=99,
                    attempts_charged=7,
                ),
                clocked_world.admin,
            )
        )

        assert_common_fields(contact)
        assert contact["id"] != spoofed_id, (
            "the identifier must be server-minted, got the client's value %s"
            % (contact["id"],)
        )
        assert_timestamp_equals(contact["created_at"], _CLOCK_STAMP)
        assert_version_is(contact, 1)
        assert_fields_equal(
            contact, attempts_charged=0, attempt_budget_remaining=3
        )


class TestContactImportValidation:
    """Malformed contact imports are refused before a row is written."""

    def test_05_utc_offset_above_the_declared_ceiling_is_refused(
        self, clocked_world
    ):
        """An import whose `utc_offset_minutes` is 900 exceeds the declared
        ceiling of 840 and is refused as a malformed request.

        PRD 3.1: "Two more fields describe the recipient's clock:
        `utc_offset_minutes`, a fixed integer offset of the consumer's local time
        from UTC that must lie between −720 and 840 inclusive, and
        `time_zone_label`, the IANA label shown to agents."
        PRD 2.8: "Request well-formedness on every endpoint — body parses, every
        required field present, every enum value a member of its declared set,
        every number inside its declared range, phone numbers in E.164 form,
        timestamps and dates parseable, `limit` within 1 to 100 —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contact_utc_offset_above_range_rejected
        """
        response = clocked_world.api.create_contact(
            _fresh_contact_payload(
                utc_offset_minutes=900, time_zone_label="Pacific/Kiritimati"
            ),
            clocked_world.admin,
        )
        assert_error(response, ApiErrorId.INVALID_REQUEST)

        # No row was written, so the same number imports cleanly as version 1.
        accepted = assert_created(
            clocked_world.api.create_contact(
                _fresh_contact_payload(), clocked_world.admin
            )
        )
        assert_version_is(accepted, 1)

    def test_06_phone_number_outside_e164_form_is_refused(self, clocked_world):
        """An import whose `phone_number` carries no leading plus sign is refused
        as a malformed request rather than stored unnormalised.

        PRD 3.1: "The import carries the consumer's `phone_number` in E.164 form
        — a leading plus sign, a first digit between 1 and 9, and then between
        seven and fourteen further digits — together with `state_code`, exactly
        two uppercase letters naming the US state whose calling-window policy
        will gate every attempt to this consumer."
        PRD 2.8: "Request well-formedness on every endpoint — body parses, every
        required field present, every enum value a member of its declared set,
        every number inside its declared range, phone numbers in E.164 form,
        timestamps and dates parseable, `limit` within 1 to 100 —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contact_non_e164_phone_number_rejected
        """
        response = clocked_world.api.create_contact(
            _fresh_contact_payload(phone_number="4155550101"),
            clocked_world.admin,
        )
        assert_error(response, ApiErrorId.INVALID_REQUEST)

    def test_07_import_without_state_code_is_refused(self, clocked_world):
        """An import that omits `state_code` is refused as a malformed request
        rather than stored with an absent state.

        PRD 3.1: "The import carries the consumer's `phone_number` in E.164 form
        — a leading plus sign, a first digit between 1 and 9, and then between
        seven and fourteen further digits — together with `state_code`, exactly
        two uppercase letters naming the US state whose calling-window policy
        will gate every attempt to this consumer."
        PRD 2.8: "Request well-formedness on every endpoint — body parses, every
        required field present, every enum value a member of its declared set,
        every number inside its declared range, phone numbers in E.164 form,
        timestamps and dates parseable, `limit` within 1 to 100 —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contact_missing_required_state_code_rejected
        """
        response = clocked_world.api.create_contact(
            _fresh_contact_payload(state_code=None), clocked_world.admin
        )
        assert_error(response, ApiErrorId.INVALID_REQUEST)


class TestSuppressionEntryListing:
    """Paging the do-not-call list."""

    def test_08_suppression_listing_reports_total_count_and_has_more(
        self, clocked_world
    ):
        """Three active national rows read with `limit` 2 return two items with a
        `total_count` of 3 and `has_more` true, and the second page returns the
        remaining row with `has_more` false.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` counts the rows matching the filters before pagination is
        applied and `has_more` says whether any matching row remains beyond the
        returned page."
        PRD 3.4: "Entries may be listed and narrowed by `list_type`,
        `phone_number`, `state_code` and `status`, with `limit` and `offset`."

        Design: Corner/entities/suppression_entry_listing_paginates_with_total_count_and_has_more
        """
        for phone_number in _NATIONAL_LIST_PHONES:
            clocked_world.create_fresh_national_list(phone_number)

        query = {
            "list_type": ListType.NATIONAL,
            "status": SuppressionStatus.ACTIVE,
            "limit": 2,
            "offset": 0,
        }
        first_rows, first_meta = assert_page(
            clocked_world.api.list_suppression_entries(
                clocked_world.officer, query
            )
        )
        assert len(first_rows) == 2, (
            "limit 2 must cap the page at two rows, got %d" % len(first_rows)
        )
        assert_total_count(first_meta, 3)
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0
        assert first_meta["has_more"] is True, (
            "a third matching row remains beyond the first page"
        )

        second_query = dict(query, offset=2)
        second_rows, second_meta = assert_page(
            clocked_world.api.list_suppression_entries(
                clocked_world.officer, second_query
            )
        )
        assert len(second_rows) == 1, (
            "offset 2 must return the single remaining row, got %d"
            % len(second_rows)
        )
        assert_total_count(second_meta, 3)
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False, (
            "no matching row remains beyond the second page"
        )
        assert second_rows[0]["id"] not in [row["id"] for row in first_rows], (
            "the two pages must be disjoint"
        )


class TestUnknownRowReferences:
    """Unknown identifiers are diagnosed per resource family."""

    def test_09_reading_an_unknown_contact_is_not_found(self, clocked_world):
        """Reading a syntactically valid but unknown contact identifier is
        refused as a missing contact, not answered with an empty envelope.

        PRD 2.8: "The `Contact` named by a path identifier or a payload
        `contact_id`, on `GET /compliance/contacts/{id}`,
        `POST /compliance/contacts/{id}/number-status-check`,
        `POST /compliance/consent-records`,
        `POST /compliance/revocation-requests`,
        `POST /compliance/contact-attempts`, `POST /compliance/complaints` and
        `GET /compliance/contacts/{id}/revocation-requests` —
        `ERR_CONTACT_NOT_FOUND`."
        PRD 2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/contact_get_unknown_id_not_found
        """
        response = clocked_world.api.get_contact(
            NON_EXISTENT_UUID, make_dialer_operator_headers()
        )
        error = assert_error(response, ApiErrorId.CONTACT_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_10_reading_an_unknown_consent_record_is_not_found(
        self, clocked_world
    ):
        """Reading a syntactically valid but unknown consent-record identifier is
        refused as a missing consent record.

        PRD 2.8: "Then the `ConsentRecord` named by a path identifier on
        `GET /compliance/consent-records/{id}`,
        `POST /compliance/consent-records/{id}/suspend` and
        `POST /compliance/consent-records/{id}/reinstate` —
        `ERR_CONSENT_RECORD_NOT_FOUND`."
        PRD 2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/consent_record_get_unknown_id_not_found
        """
        response = clocked_world.api.get_consent_record(
            NON_EXISTENT_UUID, clocked_world.officer
        )
        error = assert_error(response, ApiErrorId.CONSENT_RECORD_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_11_validating_an_unknown_revocation_request_is_not_found(
        self, clocked_world
    ):
        """Validating a syntactically valid but unknown revocation-request
        identifier is refused as a missing revocation request.

        PRD 2.8: "Then the `RevocationRequest` on
        `POST /compliance/revocation-requests/{id}/validate`,
        `POST /compliance/revocation-requests/{id}/reject` and
        `POST /compliance/revocation-requests/{id}/propagate` —
        `ERR_REVOCATION_REQUEST_NOT_FOUND`."
        PRD 2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/revocation_request_validate_unknown_id_not_found
        """
        response = clocked_world.api.validate_revocation_request(
            NON_EXISTENT_UUID,
            factories.revocation_validate_payload(),
            clocked_world.officer,
        )
        error = assert_error(response, ApiErrorId.REVOCATION_REQUEST_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_12_removing_an_unknown_suppression_entry_is_not_found(
        self, clocked_world
    ):
        """Removing a syntactically valid but unknown suppression-entry
        identifier is refused as a missing suppression entry.

        PRD 2.8: "Then the `SuppressionEntry` on
        `POST /compliance/suppression-entries/{id}/remove` —
        `ERR_SUPPRESSION_ENTRY_NOT_FOUND`."
        PRD 2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/suppression_entry_remove_unknown_id_not_found
        """
        response = clocked_world.api.remove_suppression_entry(
            NON_EXISTENT_UUID,
            factories.suppression_remove_payload(removal_reason="DATA_ERROR"),
            clocked_world.officer,
        )
        error = assert_error(response, ApiErrorId.SUPPRESSION_ENTRY_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"], "the failure envelope must carry a message"

    def test_13_capturing_consent_for_an_unknown_contact_is_not_found(
        self, clocked_world
    ):
        """A consent capture naming an unknown `contact_id` is refused as a
        missing contact even though the supplied `expected_contact_version`
        matches a real contact's version, and the real row stays untouched.

        PRD 2.8: "The `Contact` named by a path identifier or a payload
        `contact_id`, on `GET /compliance/contacts/{id}`,
        `POST /compliance/contacts/{id}/number-status-check`,
        `POST /compliance/consent-records`,
        `POST /compliance/revocation-requests`,
        `POST /compliance/contact-attempts`, `POST /compliance/complaints` and
        `GET /compliance/contacts/{id}/revocation-requests` —
        `ERR_CONTACT_NOT_FOUND`."
        PRD 2.9: "Creating a campaign whose `dialer_profile_id` and
        `agent_script_id` are both unknown is reported as
        `ERR_DIALER_PROFILE_NOT_FOUND`; capturing a consent whose `contact_id`
        and `disclosure_script_id` are both unknown is reported as
        `ERR_CONTACT_NOT_FOUND`; logging a complaint whose `contact_id` and
        `campaign_id` are both unknown is reported as `ERR_CONTACT_NOT_FOUND`."

        Design: Corner/entities/consent_create_with_unknown_contact_id_not_found
        """
        contact = clocked_world.create_ca_contact()
        script = clocked_world.approved_script()

        response = clocked_world.api.create_consent_record(
            factories.consent_record_payload(
                contact_id=NON_EXISTENT_UUID,
                disclosure_script_id=script["id"],
                expected_contact_version=contact["version"],
                signature_evidence="evidence-ghost",
            ),
            clocked_world.officer,
        )
        assert_error(response, ApiErrorId.CONTACT_NOT_FOUND)

        untouched = clocked_world.read_contact(contact["id"])
        assert_fields_equal(untouched, total_consent_count=0)
        assert_version_is(untouched, 1)
