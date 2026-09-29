"""The regulatory frame and applicant intake: what a profession registration echoes
back, how the compact list paginates, and what the server mints and defaults when an
applicant or a credential first arrives."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CREDENTIAL_ACTIVE,
    EVALUATOR_ACTIVE,
    MILITARY_NONE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    applicant_payload,
    assert_audit_triplet,
    credential_payload,
    evaluator_payload,
    make_applicant_headers,
    profession_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProfessionRegistry:
    def test_registering_a_profession_echoes_the_whole_declared_frame(self, api):
        """PRD §4: "Operations that bring a brand-new resource into existence —
        registering a profession or a compact, performing applicant intake, filing a
        credential, a training record or a disciplinary finding, opening an
        application, recording a payment, opening a credential evaluation, awarding
        credit, issuing a permit, registering an evaluator, booking a review assignment
        — return `201 Created`."  PRD §3.1: "The substantive content is the scope
        requirement: `required_scope_elements` is an ordered list of between 1 and 12
        unique uppercase scope-of-practice element codes, and its order is fixed at
        registration and is the canonical order in which matched and missing elements
        are later reported."  PRD §2.4: "`version` is an integer that starts at 1 when
        the row is created and increments by exactly one on every mutation of that row."

        Design: Corner/entities/profession_creation_returns_201_with_all_declared_fields
        """
        response = api.create_profession(profession_payload(), ADMIN_HEADERS)
        profession = validate_success(response, 201)

        assert profession["profession_code"] == "RN"
        assert profession["title"] == "Registered Nurse"
        assert profession["required_scope_elements"] == [
            "ASSESS",
            "TREAT",
            "PRESCRIBE",
            "SUPERVISE",
        ]
        assert profession["critical_scope_elements"] == ["PRESCRIBE"]
        assert profession["exam_waiver_min_score"] == 70.00
        assert profession["expedite_surcharge_pct"] == 0.15
        assert_audit_triplet(profession, expected_version=1)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

    def test_reading_a_profession_back_neither_alters_nor_bumps_it(self, api, setup):
        """PRD §4: "Every other operation, including all reads, all lifecycle
        transitions on an existing resource, all compensating actions, the ops sweep and
        the clock control, returns `200 OK`."  PRD §2.4: "`updated_at` is an ISO 8601
        UTC timestamp in the same format recording the most recent mutation of the row;
        it is refreshed on every mutation, including mutations of purely derived fields
        such as an application's `fee_balance_cents` or an evaluator's
        `open_assignment_count`."

        Design: Corner/entities/profession_retrieval_returns_stored_representation
        """
        created = setup.profession()

        fetched = validate_success(api.get_profession(created["id"], ANALYST_HEADERS), 200)

        assert fetched["id"] == created["id"]
        assert fetched["permit_fee_cents"] == 6000
        assert fetched["standard_processing_days"] == 90
        assert fetched["version"] == 1
        assert fetched["updated_at"] == created["updated_at"]

    def test_the_compact_list_windows_three_partner_states_two_at_a_time(self, api, setup):
        """PRD §2.3: "`limit` caps the number of rows returned; when omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is 100.
        `offset` is the number of rows to skip before the window begins; when omitted it
        defaults to 0, and its minimum accepted value is 0."  PRD §2.3: "List responses
        populate `limit`, `offset`, `total_count` and `has_more` inside `meta`.
        `total_count` is the number of rows matching the request's filters before the
        pagination window is applied, and `has_more` is true exactly when rows matching
        those filters remain beyond the current window."  PRD §2.3: "Unless a specific
        endpoint states otherwise, every list is ordered by `created_at` ascending."

        Design: Corner/entities/reciprocal_agreement_listing_paginates_with_limit_and_offset
        """
        profession = setup.profession()
        texas = setup.compact(profession["id"], partner_state="TX", fee_waiver_pct=0.50)
        new_mexico = setup.compact(
            profession["id"],
            partner_state="NM",
            fee_waiver_pct=0.25,
            exam_waiver_allowed=True,
        )
        arizona = setup.compact(
            profession["id"],
            partner_state="AZ",
            fee_waiver_pct=0.10,
            jurisprudence_waiver_allowed=True,
        )

        first_page, first_meta = validate_paginated(
            api.list_reciprocal_agreements(
                profession["id"], ANALYST_HEADERS, {"limit": 2, "offset": 0}
            )
        )
        assert [row["id"] for row in first_page] == [texas["id"], new_mexico["id"]]
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        last_page, last_meta = validate_paginated(
            api.list_reciprocal_agreements(
                profession["id"], ANALYST_HEADERS, {"limit": 2, "offset": 2}
            )
        )
        assert [row["id"] for row in last_page] == [arizona["id"]]
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False

    def test_an_evaluator_status_outside_the_declared_pair_is_malformed(self, api):
        """PRD §3.1: "Each carries a `full_name`, the `profession_code` they are
        credentialed to review, a `status` of `ACTIVE` or `INACTIVE` defaulting to
        `ACTIVE`, and a `max_concurrent_reviews` cap of at least 1 that defaults to 2."
        PRD §2.8: "Request shape — every required body field present; every enum value a
        declared member; every datetime a well-formed ISO 8601 UTC instant; every cents
        field and hour field at or above its declared floor; every array within its size
        bounds; a profession's `critical_scope_elements` a subset of its
        `required_scope_elements`; a review assignment's `window_end_at` strictly after
        its `window_start_at`; a payment's `amount_cents` strictly greater than zero;
        `profession_code` unique across professions; the pair of `profession_id` and
        `partner_state` unique across reciprocal agreements; `limit` within 1 through
        100 and `offset` at least 0. `ERR_INVALID_REQUEST`, 400. Applies to every
        endpoint."

        Design: Corner/entities/evaluator_create_invalid_enum_status_rejected
        """
        response = api.create_evaluator(
            evaluator_payload(full_name="Bad Enum", status="SUSPENDED"), ADMIN_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        accepted = validate_success(
            api.create_evaluator(evaluator_payload(full_name="Good Enum"), ADMIN_HEADERS), 201
        )
        assert accepted["status"] == EVALUATOR_ACTIVE


class TestApplicantIntake:
    def test_intake_mints_the_audit_block_and_seeds_the_derived_standing_fields(self, api):
        """PRD §2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly one on every mutation of that row."  PRD §3.2:
        "Intake records the applicant's `full_name`, their current `state_code` as
        exactly two uppercase letters — the value later matched against a compact's
        `partner_state` — an optional `residency_months` count of completed in-state
        residency months defaulting to 0 and never negative, and an optional
        `military_status` drawn from `NONE`, `SERVICE_MEMBER`, `MILITARY_SPOUSE` and
        `VETERAN`, defaulting to `NONE`."  PRD §3.2: "At intake the applicant's
        `good_standing_flag` is true, both `disciplinary_risk_index_reported` and
        `disciplinary_risk_index_effective` are 0.00, and `fee_waiver_eligible` is
        derived immediately: it is true exactly when `military_status` is
        `SERVICE_MEMBER`, `MILITARY_SPOUSE` or `VETERAN`, and false when it is `NONE`."

        Design: Corner/entities/applicant_system_fields_generated_on_create
        """
        applicant = validate_success(
            api.create_applicant(
                applicant_payload(
                    full_name="Dara Okafor", residency_months=None, military_status=None
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_audit_triplet(applicant, expected_version=1)
        assert applicant["full_name"] == "Dara Okafor"
        assert applicant["residency_months"] == 0
        assert applicant["military_status"] == MILITARY_NONE
        assert applicant["disciplinary_risk_index_reported"] == 0.00
        assert applicant["disciplinary_risk_index_effective"] == 0.00
        assert applicant["good_standing_flag"] is True
        assert applicant["fee_waiver_eligible"] is False

    def test_reading_an_applicant_that_was_never_minted_is_a_not_found(self, api):
        """PRD §2.7: "Where a URL contains a resource identifier, existence is validated
        left to right, and the first segment that does not resolve decides the response
        with HTTP 404."  PRD §2.8: "Path existence, left to right, as described in §2.7.
        The matching 404 code."

        Design: Corner/entities/applicant_get_with_unknown_id_returns_not_found
        """
        response = api.get_applicant(NON_EXISTENT_UUID, ADMIN_HEADERS)

        validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    def test_a_credential_filed_without_a_status_arrives_active_but_unverified(
        self, api, setup
    ):
        """PRD §3.2: "A filing carries the `issuing_state` as two uppercase letters, the
        `license_number` exactly as printed by that state, the `scope_elements` the
        issuing state grants under the credential as between 0 and 12 unique uppercase
        codes, the `practice_hours` documented against it as a non-negative integer, the
        `issued_at` instant the credential was granted, an optional `status` drawn from
        `ACTIVE`, `LAPSED`, `SUSPENDED` and `REVOKED` defaulting to `ACTIVE`, and an
        optional `verified_good_standing` flag defaulting to false which is set true
        once the issuing state's verification letter has arrived."  PRD §3.2: "The
        credential list accepts an optional `status` filter, and the disciplinary list
        accepts an optional `resolved` filter."

        Design: Corner/entities/credential_defaults_status_active_and_unverified_when_omitted
        """
        applicant = setup.applicant(full_name="Bo Nilsen")

        credential = validate_success(
            api.create_credential(
                applicant["id"],
                credential_payload(
                    license_number="OK-11002",
                    scope_elements=["ASSESS", "TREAT"],
                    practice_hours=900,
                    issued_at="2021-06-01T00:00:00Z",
                    status=None,
                    verified_good_standing=None,
                ),
                make_applicant_headers(applicant["id"]),
            ),
            201,
        )

        assert credential["status"] == CREDENTIAL_ACTIVE
        assert credential["verified_good_standing"] is False
        assert credential["applicant_id"] == applicant["id"]

        rows, meta = validate_paginated(
            api.list_credentials(
                applicant["id"],
                make_applicant_headers(applicant["id"]),
                {"status": CREDENTIAL_ACTIVE},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [credential["id"]]
