"""The record-level contract: minted numbers, defaults, computed reads and 404s."""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_audit_triple,
    assert_ce_standing,
    assert_immutable_row,
    assert_license_number,
)
from test_helpers.clock import parse_instant
from test_helpers.constants import CLOCK_STARTUP_DEFAULT, DEFAULT_LIMIT
from test_helpers.test_users import make_analyst_headers

LICENCE_EXPIRY = "2028-07-31T00:00:00Z"


class TestLicenceApplicationCreation:
    """The mint, the two opening dimensions and every zeroed counter."""

    def test_the_licence_number_counter_runs_per_person_type(self, client):
        """Two salespersons and a broker draw from two independent counters.

        The PRD says "The server mints a `license_number` on creation: the prefix
        `SP-` for a `SALESPERSON` and `BR-` for a `BROKER`, followed by a
        six-digit zero-padded counter that is maintained **separately for each
        `person_type`** and incremented on every create, so the first salesperson
        ever registered is numbered `SP-000001` and the first broker `BR-000001`
        even though both exist in the same registry."

        Design: Corner/entities/licensee_creation_returns_201_with_a_generated_license_number_and_applicant_defaults
        """
        first = validate_success(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", "Sam Sales"), make_analyst_headers()
            ),
            expected_status=201,
        )
        second = validate_success(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", "Sue Second"), make_analyst_headers()
            ),
            expected_status=201,
        )
        broker = validate_success(
            client.create_licensee(
                factories.licensee_payload("BROKER", "Dana Broker"), make_analyst_headers()
            ),
            expected_status=201,
        )

        assert first["license_number"] == "SP-000001"
        assert second["license_number"] == "SP-000002"
        assert broker["license_number"] == "BR-000001"
        assert_license_number(second["license_number"], "SALESPERSON")
        assert_license_number(broker["license_number"], "BROKER")

    def test_a_fresh_application_opens_with_every_counter_at_zero(self, client):
        """The two standing dimensions start apart and nothing is stamped yet.

        The PRD says "A fresh application starts with `license_status` at
        `APPLICANT` and `discipline_status` at `NONE` — the two dimensions of a
        licensee's standing, which from here on evolve independently of one
        another."

        Design: Corner/entities/licensee_creation_returns_201_with_a_generated_license_number_and_applicant_defaults
        """
        applicant = validate_success(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", "Sam Sales"), make_analyst_headers()
            ),
            expected_status=201,
        )

        assert applicant["license_status"] == "APPLICANT"
        assert applicant["discipline_status"] == "NONE"
        assert applicant["exam_attempt_count"] == 0
        assert applicant["exam_best_score"] == 0
        assert applicant["exam_passed_at"] is None
        assert applicant["prior_sanction_count"] == 0
        assert applicant["recovery_paid_cents"] == 0
        assert applicant["ce_hours_valid"] == 0
        for field in (
            "sponsoring_brokerage_id",
            "supervising_broker_id",
            "license_issued_at",
            "license_expires_at",
            "inactive_since",
            "ce_period_start_on",
            "suspension_ends_at",
        ):
            assert applicant[field] is None, f"{field} is null at application"

        assert_audit_triple(applicant, expected_version=1)
        assert applicant["created_at"] == applicant["updated_at"]


class TestLicenceRetrievalRecomputesOnRead:
    """A read is a derivation, not a row dump."""

    def test_the_ce_figures_are_derived_on_every_read(self, client):
        """Nobody wrote these four fields, yet the read reports them.

        The PRD says "`ce_deficient` is simply true whenever `ce_hours_valid` is
        less than `ce_hours_required`, and both are re-derived on every read of
        the licensee."

        Design: Corner/entities/licensee_retrieval_returns_the_stored_row_with_recomputed_read_only_fields
        """
        firm = fixtures.bootstrap_active_brokerage(
            client, name="Harbor Realty Group", broker_name="Dana Broker"
        )
        broker = validate_success(
            client.get_licensee(firm["broker"]["id"], make_analyst_headers())
        )

        assert broker["id"] == firm["broker"]["id"]
        assert broker["license_status"] == "ACTIVE"
        assert broker["discipline_status"] == "NONE"
        assert broker["license_number"] == "BR-000001"
        assert broker["ce_period_start_on"] == "2026-08-01"
        assert_ce_standing(broker, valid=0, required=12)
        assert broker["ce_deficient"] is True

    def test_the_issuance_calendar_and_the_supervision_edge_are_both_stored(self, client):
        """The self-supervision bootstrap is visible on the broker's own row.

        The PRD says "On `EXAM_PASSED → ACTIVE` the server records
        `sponsoring_brokerage_id` as the receiving firm and `supervising_broker_id`
        as the nominated broker, sets `license_issued_at` to the current logical
        instant, sets `license_expires_at` to that instant plus a two-year licence
        term of 730 days, and opens the continuing-education accrual window by
        setting `ce_period_start_on` to the calendar date of that instant."

        Design: Corner/entities/licensee_retrieval_returns_the_stored_row_with_recomputed_read_only_fields
        """
        firm = fixtures.bootstrap_active_brokerage(
            client, name="Harbor Realty Group", broker_name="Dana Broker"
        )
        broker = validate_success(
            client.get_licensee(firm["broker"]["id"], make_analyst_headers())
        )

        assert broker["exam_attempt_count"] == 1
        assert broker["exam_best_score"] == 82
        assert broker["exam_passed_at"] == CLOCK_STARTUP_DEFAULT
        assert broker["license_issued_at"] == CLOCK_STARTUP_DEFAULT
        assert broker["license_expires_at"] == LICENCE_EXPIRY
        assert broker["sponsoring_brokerage_id"] == firm["brokerage"]["id"]
        assert broker["supervising_broker_id"] == firm["broker"]["id"]


class TestLicenceListingFiltersThenWindows:
    """The filter narrows the population before the window is cut from it."""

    def _four_people(self, client):
        sam = fixtures.create_applicant(client, "SALESPERSON", "Sam Sales")
        sue = fixtures.create_applicant(client, "SALESPERSON", "Sue Second")
        sid = fixtures.create_applicant(client, "SALESPERSON", "Sid Third")
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")
        return sam, sue, sid, broker

    def test_the_unfiltered_listing_defaults_to_ten_and_orders_by_creation(self, client):
        """No query string at all still yields a windowed, ordered page.

        The PRD says "`limit` defaults to 10, may not be smaller than 1 and may
        not exceed 100."

        Design: Corner/entities/licensee_listing_filters_by_status_and_paginates_with_default_limit_ten
        """
        sam, sue, sid, broker = self._four_people(client)

        rows, meta = validate_paginated(client.list_licensees(make_analyst_headers()))
        assert meta["total_count"] == 4
        assert meta["limit"] == DEFAULT_LIMIT
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [sam["id"], sue["id"], sid["id"], broker["id"]]

    def test_the_status_filter_sizes_total_count_not_the_table(self, client):
        """Two pages of applicants, and a broker the filter never counts.

        The PRD says "Both are echoed back in `meta` alongside `total_count`, the
        number of records matching the filter before the window is applied, and
        `has_more`, a boolean that is true when records remain beyond the current
        window."

        Design: Corner/entities/licensee_listing_filters_by_status_and_paginates_with_default_limit_ten
        """
        sam, sue, sid, broker = self._four_people(client)

        first_page, first_meta = validate_paginated(
            client.list_licensees(
                make_analyst_headers(), params={"license_status": "APPLICANT", "limit": 2}
            )
        )
        assert [row["id"] for row in first_page] == [sam["id"], sue["id"]]
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            client.list_licensees(
                make_analyst_headers(),
                params={"license_status": "APPLICANT", "limit": 2, "offset": 2},
            )
        )
        assert [row["id"] for row in second_page] == [sid["id"]]
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        brokers, broker_meta = validate_paginated(
            client.list_licensees(make_analyst_headers(), params={"person_type": "BROKER"})
        )
        assert [row["id"] for row in brokers] == [broker["id"]]
        assert broker_meta["total_count"] == 1


NOT_FOUND_CASES = [
    ("get_licensee", api_errors.ERR_LICENSEE_NOT_FOUND),
    ("get_brokerage", api_errors.ERR_BROKERAGE_NOT_FOUND),
    ("get_trust_account", api_errors.ERR_TRUST_ACCOUNT_NOT_FOUND),
    ("get_trust_audit", api_errors.ERR_TRUST_AUDIT_NOT_FOUND),
    ("get_complaint", api_errors.ERR_COMPLAINT_NOT_FOUND),
    ("get_consent_agreement", api_errors.ERR_CONSENT_AGREEMENT_NOT_FOUND),
    ("get_hearing", api_errors.ERR_HEARING_NOT_FOUND),
    ("get_sanction_order", api_errors.ERR_SANCTION_ORDER_NOT_FOUND),
    ("get_education_provider", api_errors.ERR_EDUCATION_PROVIDER_NOT_FOUND),
    ("get_instructor", api_errors.ERR_INSTRUCTOR_NOT_FOUND),
    ("get_course_completion", api_errors.ERR_COURSE_COMPLETION_NOT_FOUND),
    ("get_advertising_name", api_errors.ERR_ADVERTISING_NAME_NOT_FOUND),
]


class TestEveryFamilyOwnsItsNotFoundCode:
    """Twelve families, twelve distinct 404 codes, never a generic one."""

    @pytest.mark.parametrize("reader, expected_error", NOT_FOUND_CASES)
    def test_a_well_formed_unknown_id_answers_that_familys_code(
        self, client, reader, expected_error
    ):
        """The id parses, so the failure is a lookup miss and not a bad request.

        The PRD says "Each entity has its own 404: `ERR_LICENSEE_NOT_FOUND`,
        `ERR_BROKERAGE_NOT_FOUND`, `ERR_TRUST_ACCOUNT_NOT_FOUND`,
        `ERR_TRUST_AUDIT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CONSENT_AGREEMENT_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`,
        `ERR_SANCTION_ORDER_NOT_FOUND`, `ERR_EDUCATION_PROVIDER_NOT_FOUND`,
        `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_COURSE_COMPLETION_NOT_FOUND` and
        `ERR_ADVERTISING_NAME_NOT_FOUND`."

        Design: Corner/entities/every_entity_family_answers_a_bad_path_id_with_its_own_not_found_code
        """
        response = getattr(client, reader)(NON_EXISTENT_UUID, make_analyst_headers())
        validate_error(response, expected_error, expected_status=404)


class TestMissingRequiredFieldsAreRefusedAtShapeCheck:
    """Rung 3 answers before existence, ownership, state or version.

    A body missing one required field must never be quietly defaulted.
    """

    def _firm_and_broker(self, client):
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")
        brokerage = fixtures.register_brokerage(
            client, broker["id"], "Harbor Realty Group", trust_account_required=False
        )
        brokerage = fixtures.activate(client, brokerage["id"])
        return broker, brokerage

    def test_four_bodies_each_missing_one_required_field_are_all_bad_requests(self, client):
        """One omission each: hours, tender date, expected version, allegation.

        The PRD says "Every field the operation requires must be present, every
        enum value must be a declared member of its enumeration, every integer
        must respect its own bounds (a ledger `amount_cents` must be greater than
        0; `credit_hours` must be at least 1 and at most 12;
        `record_retention_years` must be at least 3 and at most 10;
        `alleged_loss_cents` must be at least 0; `prelicense_hours` must be at
        least 0; `claimed_loss_cents` must be greater than 0;
        `proposed_fine_cents` and `proposed_suspension_days` must each be at least
        0), and every date or datetime must parse as ISO 8601."

        Design: Corner/entities/write_calls_missing_required_fields_return_invalid_request
        """
        broker, brokerage = self._firm_and_broker(client)
        headers = make_analyst_headers()

        validate_error(
            client.create_licensee(
                {"person_type": "SALESPERSON", "full_name": "Nora NoHours"}, headers
            ),
            api_errors.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            client.record_exam_result(broker["id"], {"score": 80}, headers),
            api_errors.ERR_INVALID_REQUEST,
        )
        validate_error(
            client.create_affiliation(
                broker["id"],
                {"brokerage_id": brokerage["id"], "supervising_broker_id": broker["id"]},
                headers,
            ),
            api_errors.ERR_INVALID_REQUEST,
        )
        validate_error(
            client.create_complaint(
                {
                    "complainant_name": "Ora Buyer",
                    "respondent_licensee_id": broker["id"],
                    "alleged_loss_cents": 100000,
                },
                headers,
            ),
            api_errors.ERR_INVALID_REQUEST,
        )

    def test_a_refused_shape_never_reaches_the_version_check(self, client):
        """The affiliation is a 400, not a 412, and the firm is untouched.

        The PRD says "The server therefore evaluates rules in one fixed ladder and
        returns the first failure it meets."

        Design: Corner/entities/write_calls_missing_required_fields_return_invalid_request
        """
        broker, brokerage = self._firm_and_broker(client)
        version_before = brokerage["version"]

        validate_error(
            client.create_affiliation(
                broker["id"],
                {"brokerage_id": brokerage["id"], "supervising_broker_id": broker["id"]},
                make_analyst_headers(),
            ),
            api_errors.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        rows, meta = validate_paginated(client.list_licensees(make_analyst_headers()))
        assert meta["total_count"] == 1 and len(rows) == 1
        unchanged = fixtures.read_licensee(client, broker["id"])
        assert unchanged["exam_attempt_count"] == 1
        assert unchanged["sponsoring_brokerage_id"] is None
        firm = fixtures.read_brokerage(client, brokerage["id"])
        assert firm["version"] == version_before
        assert firm["affiliated_licensee_count"] == 0


class TestOmittedOptionalInputsTakeTheirDeclaredDefaults:
    """Three different default shapes: a term, a null and three zeros."""

    def test_a_new_trust_account_opens_with_three_zeroed_money_fields(self, client):
        """The money fields start at 0, never at null.

        The PRD says "A new account opens in `OPEN` status with
        `book_obligation_cents`, `book_available_cents` and `shortage_cents` all 0
        and `last_audited_at` null."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")
        brokerage = fixtures.register_brokerage(client, broker["id"], "Harbor Realty Group")

        account = validate_success(
            client.create_trust_account(
                brokerage["id"], factories.trust_account_payload("Seaside Bank"), make_analyst_headers()
            ),
            expected_status=201,
        )
        assert account["status"] == "OPEN"
        assert account["book_obligation_cents"] == 0
        assert account["book_available_cents"] == 0
        assert account["shortage_cents"] == 0
        assert account["last_audited_at"] is None

    def test_an_omitted_approval_term_falls_back_to_two_years(self, client):
        """An empty approval body still stamps a 730-day term.

        The PRD says "The analyst may supply `approval_years`, which defaults to
        2; the server stamps `approved_at` with the current logical instant and
        sets `approval_expires_at` to that instant plus `approval_years`
        multiplied by 365 days."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        provider = fixtures.register_provider(client, "Coastal Institute")

        approved = validate_success(
            client.approve_education_provider(provider["id"], make_analyst_headers(), {})
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] == CLOCK_STARTUP_DEFAULT
        assert approved["approval_expires_at"] == LICENCE_EXPIRY

    def test_a_dba_name_keeps_a_null_team_lead_and_an_unreviewed_head(self, client):
        """No team lead was supplied, and none is invented.

        The PRD says "A successful registration starts in `SUBMITTED` with
        `reviewed_by_user_id` and `rejection_reason` null."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        firm = fixtures.bootstrap_active_brokerage(
            client, name="Harbor Realty Group", broker_name="Dana Broker"
        )

        name = validate_success(
            client.create_advertising_name(
                factories.advertising_name_payload(
                    firm["brokerage"]["id"], "Harbor Homes", kind="DBA"
                ),
                make_analyst_headers(),
            ),
            expected_status=201,
        )
        assert name["team_lead_licensee_id"] is None
        assert name["status"] == "SUBMITTED"
        assert name["rejection_reason"] is None
        assert name["reviewed_by_user_id"] is None
        assert name["prohibited_term_hits"] == 0


class TestComputedAdvertisingFieldsIgnoreTheClient:
    """The server normalizes and counts; the request body cannot dictate either."""

    def test_the_normalized_form_is_derived_and_the_clients_copy_discarded(self, client):
        """Case is folded, punctuation vanishes, and two terms are caught.

        The PRD says "Normalization uppercases `name_text` and then discards every
        character that is not a letter A through Z or a digit 0 through 9, so
        spaces, punctuation, ampersands and hyphens all vanish: `"Elm & Oak
        Realty"` and `"elmoakrealty"` normalize identically."

        Design: Corner/entities/advertising_name_normalization_recomputed_and_client_normalized_name_input_ignored
        """
        firm = fixtures.bootstrap_active_brokerage(
            client, name="Harbor Realty Group", broker_name="Dana Broker"
        )
        submitted = validate_success(
            client.create_advertising_name(
                {
                    "brokerage_id": firm["brokerage"]["id"],
                    "kind": "DBA",
                    "name_text": "Bay & Coast Realtors' MLS Group",
                    "normalized_name": "SOMETHINGELSE",
                    "prohibited_term_hits": 0,
                    "status": "APPROVED",
                },
                make_analyst_headers(),
            ),
            expected_status=201,
        )

        assert submitted["normalized_name"] == "BAYCOASTREALTORSMLSGROUP"
        assert submitted["prohibited_term_hits"] == 2
        assert submitted["status"] == "SUBMITTED"

    def test_the_prohibited_count_survives_a_re_read(self, client):
        """Both computed fields are stable, and neither came from the payload.

        The PRD says "`prohibited_term_hits` counts how many of the six prohibited
        terms — `REALTOR`, `MLS`, `COMMISSION`, `STATEOF`, `GUARANTEED`,
        `OFFICIAL` — appear anywhere inside `normalized_name`; each distinct term
        is counted once no matter how often it occurs."

        Design: Corner/entities/advertising_name_normalization_recomputed_and_client_normalized_name_input_ignored
        """
        firm = fixtures.bootstrap_active_brokerage(
            client, name="Harbor Realty Group", broker_name="Dana Broker"
        )
        submitted = fixtures.submit_advertising_name(
            client, firm["brokerage"]["id"], "Bay & Coast Realtors' MLS Group", kind="DBA"
        )

        stored = fixtures.read_advertising_name(client, submitted["id"])
        assert stored["normalized_name"] == "BAYCOASTREALTORSMLSGROUP"
        assert stored["prohibited_term_hits"] == 2
        assert stored["status"] == "SUBMITTED"


class TestSystemFieldsAreServerOwned:
    """A create cannot legislate its own identity, status or audit triple."""

    def test_a_client_supplied_status_and_score_are_both_discarded(self, client):
        """The licensing gate is not bypassable from the request body.

        The PRD says "Clients never supply an `id`; they receive it in the creation
        response and quote it in later paths and payloads."

        Design: Corner/entities/licensee_system_fields_are_server_generated_and_client_status_input_ignored
        """
        created = validate_success(
            client.create_licensee(
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "person_type": "SALESPERSON",
                    "full_name": "Sam Sales",
                    "prelicense_hours": 90,
                    "license_status": "ACTIVE",
                    "exam_best_score": 99,
                    "license_number": "SP-999999",
                    "created_at": "2020-01-01T00:00:00Z",
                },
                make_analyst_headers(),
            ),
            expected_status=201,
        )

        assert created["id"] != "11111111-1111-1111-1111-111111111111"
        assert created["license_status"] == "APPLICANT"
        assert created["exam_best_score"] == 0
        assert created["exam_attempt_count"] == 0
        assert created["license_number"] == "SP-000001"
        # The audit triple carries "three fractional digits" (PRD §2.4), so the
        # instant is compared as an instant rather than as a rendered string.
        assert parse_instant(created["created_at"]) == parse_instant(CLOCK_STARTUP_DEFAULT)
        assert parse_instant(created["updated_at"]) == parse_instant(CLOCK_STARTUP_DEFAULT)
        assert created["version"] == 1

    def test_nothing_from_the_clients_system_payload_was_persisted(self, client):
        """A follow-up read confirms the discarded values never landed.

        The PRD says "`version`, an integer that begins at 1 when the row is
        created and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/licensee_system_fields_are_server_generated_and_client_status_input_ignored
        """
        created = validate_success(
            client.create_licensee(
                {
                    "person_type": "SALESPERSON",
                    "full_name": "Sam Sales",
                    "prelicense_hours": 90,
                    "license_status": "ACTIVE",
                    "exam_best_score": 99,
                },
                make_analyst_headers(),
            ),
            expected_status=201,
        )

        stored = fixtures.read_licensee(client, created["id"])
        assert stored["license_status"] == "APPLICANT"
        assert stored["exam_best_score"] == 0
        assert stored["license_number"] == created["license_number"]
        assert_audit_triple(stored, expected_version=1)


class TestTypeAndRangeConstraintsAreShapeFailures:
    """An undeclared enum member and an out-of-band integer are both 400s."""

    @pytest.mark.parametrize(
        "case",
        ["undeclared_person_type", "retention_below_band", "retention_above_band", "negative_loss"],
    )
    def test_four_malformed_bodies_are_refused_before_any_business_rule(self, client, case):
        """The enum member, the band and the sign are all checked at rung 3.

        The PRD says "**Request-body shape** — `ERR_INVALID_REQUEST` (HTTP 400), on
        every write."

        Design: Corner/entities/out_of_range_integers_and_undeclared_enum_members_are_rejected
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")
        headers = make_analyst_headers()

        if case == "undeclared_person_type":
            response = client.create_licensee(
                {"person_type": "APPRAISER", "full_name": "Avery Appraise", "prelicense_hours": 90},
                headers,
            )
        elif case == "retention_below_band":
            response = client.create_brokerage(
                factories.brokerage_payload(
                    "Harbor Realty Group", broker["id"], record_retention_years=2
                ),
                headers,
            )
        elif case == "retention_above_band":
            response = client.create_brokerage(
                factories.brokerage_payload(
                    "Harbor Realty Group", broker["id"], record_retention_years=11
                ),
                headers,
            )
        else:
            response = client.create_complaint(
                {
                    "complainant_name": "Ora Buyer",
                    "respondent_licensee_id": broker["id"],
                    "allegation_type": "TRUST_SHORTAGE",
                    "alleged_loss_cents": -1,
                },
                headers,
            )

        validate_error(response, api_errors.ERR_INVALID_REQUEST, expected_status=400)

    def test_the_refused_writes_left_no_row_behind(self, client):
        """Neither a brokerage nor a complaint exists after the four refusals.

        The PRD says "Every endpoint below is mounted under the `/commission`
        prefix and returns the standard envelope described in §2.2."

        Design: Corner/entities/out_of_range_integers_and_undeclared_enum_members_are_rejected
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")
        headers = make_analyst_headers()
        client.create_brokerage(
            factories.brokerage_payload("Harbor Realty Group", broker["id"], record_retention_years=2),
            headers,
        )
        client.create_complaint(
            {
                "complainant_name": "Ora Buyer",
                "respondent_licensee_id": broker["id"],
                "allegation_type": "TRUST_SHORTAGE",
                "alleged_loss_cents": -1,
            },
            headers,
        )

        _firms, firm_meta = validate_paginated(client.list_brokerages(headers))
        assert firm_meta["total_count"] == 0
        _cases, case_meta = validate_paginated(client.list_complaints(headers))
        assert case_meta["total_count"] == 0

    @pytest.mark.parametrize("retention_years", [3, 10])
    def test_the_retention_band_is_inclusive_at_both_ends(self, client, retention_years):
        """Three years and ten years are both legal registrations.

        The PRD says "`record_retention_years` must be at least 3 and at most 10".

        Design: Corner/entities/out_of_range_integers_and_undeclared_enum_members_are_rejected
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", "Dana Broker")

        firm = validate_success(
            client.create_brokerage(
                factories.brokerage_payload(
                    "Harbor Realty Group", broker["id"], record_retention_years=retention_years
                ),
                make_analyst_headers(),
            ),
            expected_status=201,
        )
        assert firm["record_retention_years"] == retention_years
        assert firm["status"] == "PENDING"


class TestChildWritesResolveTheirParentFirst:
    """A missing parent answers with the parent's code and creates no orphan."""

    def test_three_child_writes_each_name_their_own_missing_parent(self, client):
        """Path parents and body parents alike answer with the parent's 404.

        The PRD says "Path identifiers are resolved **strictly left to right**, and
        the first unresolvable segment decides the error."

        Design: Corner/entities/child_rows_require_an_existing_parent_and_a_foreign_parent_is_rejected
        """
        school = fixtures.approved_provider_with_instructor(client)
        headers = make_analyst_headers()

        validate_error(
            client.create_trust_account(
                NON_EXISTENT_UUID, factories.trust_account_payload("Seaside Bank"), headers
            ),
            api_errors.ERR_BROKERAGE_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.create_instructor(
                NON_EXISTENT_UUID, factories.instructor_payload("Ivan Extra"), headers
            ),
            api_errors.ERR_EDUCATION_PROVIDER_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.create_course_completion(
                factories.course_completion_payload(
                    NON_EXISTENT_UUID, school["instructor"]["id"], school["provider"]["id"]
                ),
                headers,
            ),
            api_errors.ERR_LICENSEE_NOT_FOUND,
            expected_status=404,
        )

    def test_no_orphan_child_row_was_written_by_any_of_the_three(self, client):
        """The instructor roster and the completion register are both unchanged.

        The PRD says "Identifiers supplied in a request **body** are resolved the
        same way and produce the same family of 404s."

        Design: Corner/entities/child_rows_require_an_existing_parent_and_a_foreign_parent_is_rejected
        """
        school = fixtures.approved_provider_with_instructor(client)
        headers = make_analyst_headers()
        client.create_instructor(
            NON_EXISTENT_UUID, factories.instructor_payload("Ivan Extra"), headers
        )
        client.create_course_completion(
            factories.course_completion_payload(
                NON_EXISTENT_UUID, school["instructor"]["id"], school["provider"]["id"]
            ),
            headers,
        )

        instructors, instructor_meta = validate_paginated(client.list_instructors(headers))
        assert instructor_meta["total_count"] == 1
        assert instructors[0]["id"] == school["instructor"]["id"]
        _completions, completion_meta = validate_paginated(client.list_course_completions(headers))
        assert completion_meta["total_count"] == 0
        _accounts, account_meta = validate_paginated(client.list_trust_accounts(headers))
        assert account_meta["total_count"] == 0


class TestCourseCompletionIsAThreeWayJunction:
    """One row, three foreign keys, and a self-referential supervision edge."""

    def _school_and_a_supervised_salesperson(self, client):
        firm = fixtures.bootstrap_active_brokerage(
            client,
            name="Harbor Realty Group",
            broker_name="Dana Broker",
            trust_account_required=False,
            open_escrow=False,
        )
        sam = fixtures.affiliate_new_salesperson(
            client, firm["brokerage"]["id"], firm["broker"]["id"], "Sam Sales"
        )
        school = fixtures.approved_provider_with_instructor(
            client, provider_name="Coastal Institute", instructor_name="Ivy Teach"
        )
        completion = fixtures.record_completion(
            client,
            sam["id"],
            school["instructor"]["id"],
            school["provider"]["id"],
            credit_hours=12,
            completed_on="2026-08-01",
            course_type="CE_CORE",
        )
        return firm, sam, school, completion

    def test_the_junction_row_is_reachable_from_each_of_its_three_keys(self, client):
        """Student, instructor and provider each find the same single row.

        The PRD says "course-completion listings on `licensee_id`, `instructor_id`,
        `education_provider_id`, `credit_status` and `course_type`".

        Design: Corner/entities/course_completion_is_the_many_to_many_junction_of_licensee_instructor_and_provider
        """
        _firm, sam, school, completion = self._school_and_a_supervised_salesperson(client)
        headers = make_analyst_headers()

        for params in (
            {"licensee_id": sam["id"]},
            {"instructor_id": school["instructor"]["id"]},
            {"education_provider_id": school["provider"]["id"]},
        ):
            rows, meta = validate_paginated(client.list_course_completions(headers, params=params))
            assert meta["total_count"] == 1, f"{params} should reach the junction"
            assert rows[0]["id"] == completion["id"]

        assert completion["credit_status"] == "VALID"
        assert completion["invalidated_at"] is None
        assert_immutable_row(completion)

    def test_the_self_referential_supervision_filter_includes_the_broker(self, client):
        """Dana supervises Sam and also, by the bootstrap, herself.

        The PRD says "Licensee listings filter on `sponsoring_brokerage_id`,
        `supervising_broker_id`, `license_status`, `discipline_status` and
        `person_type`."

        Design: Corner/entities/course_completion_is_the_many_to_many_junction_of_licensee_instructor_and_provider
        """
        firm, sam, _school, _completion = self._school_and_a_supervised_salesperson(client)

        rows, meta = validate_paginated(
            client.list_licensees(
                make_analyst_headers(), params={"supervising_broker_id": firm["broker"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [firm["broker"]["id"], sam["id"]]

    def test_only_the_named_student_is_credited(self, client):
        """The junction moves hours to one licensee and no other.

        The PRD says "`CE_CORE` and `CE_ELECTIVE` hours are added to the student's
        `ce_hours_valid` when `completed_on` falls on or after that licensee's
        `ce_period_start_on`, `PRELICENSE` hours are added to the student's
        `prelicense_hours` — which is how an applicant who is short of the 90- or
        180-hour examination threshold gets there — and `POST_LICENSE` hours count
        toward neither."

        Design: Corner/entities/course_completion_is_the_many_to_many_junction_of_licensee_instructor_and_provider
        """
        firm, sam, _school, _completion = self._school_and_a_supervised_salesperson(client)

        student = fixtures.read_licensee(client, sam["id"])
        assert_ce_standing(student, valid=12, required=12)
        assert student["ce_deficient"] is False

        broker = fixtures.read_licensee(client, firm["broker"]["id"])
        assert_ce_standing(broker, valid=0, required=12)
        assert broker["ce_deficient"] is True
