"""Entity intake: declared defaults, derived fields, typed 404s and shape checks.

Every test here translates one instance of the corner design index's ``entities``
section. State is built exclusively through the documented endpoints; the server
is restarted before each test, so the store starts empty and the logical clock
starts at its default instant.
"""

from test_helpers import (
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    IR_ANALYST_2,
    IR_ANALYST_2_USER_ID,
    ApiClient,
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    make_investor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"

MISSING_COMPANY_ID = "00000000-0000-0000-0000-0000000000c0"
MISSING_CONTACT_ID = "00000000-0000-0000-0000-0000000000c1"
MISSING_INQUIRY_ID = "00000000-0000-0000-0000-0000000000f0"


class TestCompanyCreationDefaults:
    """POST /companies with only the three required inputs."""

    def test_company_creation_applies_declared_defaults(self, api: ApiClient):
        """PRD §3.1: "`dividend_reserve_cents` is the cash, in whole cents, available to fund dividend execution; when omitted it starts at zero, and it may never be negative."
        PRD §3.1: "`blackout_window_start` and `blackout_window_end` delimit the scheduled earnings quiet period described in §2.7; when either is omitted it is stored as null, and a null start means the issuer has no scheduled blackout at all."
        PRD §3.1: "Registration also stamps the derived fields: `disclosure_posture` is derived immediately and `posture_recomputed_at` is stamped with the logical clock, `open_inquiry_count` and `dividend_paid_cents` both begin at zero, and `version` begins at 1."
        PRD §2.7: "Otherwise the posture is `OPEN`."

        Design: Corner/entities/company_creation_applies_declared_defaults
        """
        fixtures.set_clock(api, CLOCK_START)

        response = api.create_company(
            factories.company_payload(
                ticker="CRE",
                legal_name="Creation Defaults Corp",
                shares_outstanding=1000000,
            ),
            IR_ADMIN,
        )
        company = validate_success(response, expected_status=201)

        assertions.assert_company(
            company,
            ticker="CRE",
            legal_name="Creation Defaults Corp",
            shares_outstanding=1000000,
            dividend_reserve_cents=0,
            dividend_paid_cents=0,
            disclosure_posture="OPEN",
            open_inquiry_count=0,
            blackout_window_start=None,
            blackout_window_end=None,
            version=1,
        )
        assert isinstance(company["id"], str) and company["id"]

    def test_company_creation_stamps_posture_recomputed_at_from_the_logical_clock(
        self, api: ApiClient
    ):
        """PRD §3.1: "Registration also stamps the derived fields: `disclosure_posture` is derived immediately and `posture_recomputed_at` is stamped with the logical clock, `open_inquiry_count` and `dividend_paid_cents` both begin at zero, and `version` begins at 1."
        PRD §2.4: "Every deadline, window, staleness test and overlap comparison in this system reads a server-held **logical UTC clock** rather than real wall-clock time."

        Design: Corner/entities/company_creation_applies_declared_defaults
        """
        fixtures.set_clock(api, "2026-08-05T09:30:00Z")

        company = validate_success(
            api.create_company(
                factories.company_payload(
                    ticker="CREB",
                    legal_name="Clock Stamped Corp",
                    shares_outstanding=250000,
                ),
                IR_ADMIN,
            ),
            expected_status=201,
        )

        assertions.assert_ts_equals(
            company["posture_recomputed_at"],
            "2026-08-05T09:30:00.000Z",
            "posture_recomputed_at",
        )
        assert company["disclosure_posture"] == "OPEN"
        assert company["version"] == 1


class TestCompanyRetrieval:
    """GET /companies/{id} hands back the stored row."""

    def test_company_retrieval_returns_the_stored_row_unchanged(self, api: ApiClient):
        """PRD §3.1: "Reading a single issuer returns its stored posture alongside `open_inquiry_count`, `dividend_reserve_cents` and `dividend_paid_cents`; addressing an issuer that does not exist yields `ERR_COMPANY_NOT_FOUND`."
        PRD §2.11: "Reads return the stored value."
        PRD §2.11: "Nothing recomputes on read."

        Design: Corner/entities/company_retrieval_returns_stored_row_unchanged
        """
        fixtures.set_clock(api, CLOCK_START)
        created = fixtures.create_company(
            api,
            ticker="RET",
            legal_name="Retrieval Corp",
            shares_outstanding=500000,
            dividend_reserve_cents=25000,
            blackout_window_start="2026-09-01T00:00:00Z",
            blackout_window_end="2026-09-15T00:00:00Z",
        )

        read = validate_success(api.get_company(created["id"], IR_ANALYST))

        assertions.assert_company(
            read,
            id=created["id"],
            ticker="RET",
            shares_outstanding=500000,
            dividend_reserve_cents=25000,
            dividend_paid_cents=0,
            open_inquiry_count=0,
            disclosure_posture="OPEN",
            version=1,
        )
        assertions.assert_ts_equals(
            read["blackout_window_start"],
            "2026-09-01T00:00:00.000Z",
            "blackout_window_start",
        )
        assertions.assert_ts_equals(
            read["blackout_window_end"],
            "2026-09-15T00:00:00.000Z",
            "blackout_window_end",
        )


class TestContactListingPagination:
    """GET /contacts under one issuer, paged two rows at a time."""

    @staticmethod
    def _three_contacts(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="LST", legal_name="Listing Corp", shares_outstanding=1000000
        )
        first = fixtures.create_contact(
            api,
            company["id"],
            contact_type="INSTITUTIONAL_HOLDER",
            display_name="List One",
            email="l1@funds.test",
            shares_held=30000,
        )
        second = fixtures.create_contact(
            api,
            company["id"],
            contact_type="RETAIL_HOLDER",
            display_name="List Two",
            email="l2@retail.test",
            shares_held=100,
        )
        third = fixtures.create_contact(
            api,
            company["id"],
            contact_type="SELL_SIDE_ANALYST",
            display_name="List Three",
            email="l3@bank.test",
        )
        return company, [first, second, third]

    def test_contacts_listing_first_page_reports_total_count_and_has_more(
        self, api: ApiClient
    ):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be smaller than 1 and may not be larger than 100."
        PRD §2.3: "`total_count` reports the number of rows matching the request's filters before pagination is applied, and `has_more` is true when rows matching the filters remain beyond the returned page."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object."

        Design: Corner/entities/contacts_listing_paginates_with_total_count_and_has_more
        """
        company, contacts = self._three_contacts(api)

        rows, meta = validate_paginated(
            api.list_contacts(IR_ANALYST, company_id=company["id"], limit=2, offset=0)
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert {row["id"] for row in rows} <= {contact["id"] for contact in contacts}

    def test_contacts_listing_last_page_reports_has_more_false(self, api: ApiClient):
        """PRD §2.3: "`offset` is the number of rows to skip before the page begins and defaults to 0."
        PRD §2.3: "`total_count` reports the number of rows matching the request's filters before pagination is applied, and `has_more` is true when rows matching the filters remain beyond the returned page."

        Design: Corner/entities/contacts_listing_paginates_with_total_count_and_has_more
        """
        company, contacts = self._three_contacts(api)

        first_rows, _ = validate_paginated(
            api.list_contacts(IR_ANALYST, company_id=company["id"], limit=2, offset=0)
        )
        rows, meta = validate_paginated(
            api.list_contacts(IR_ANALYST, company_id=company["id"], limit=2, offset=2)
        )

        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["offset"] == 2

        seen = [row["id"] for row in first_rows] + [row["id"] for row in rows]
        assert sorted(seen) == sorted(contact["id"] for contact in contacts)


class TestTypedNotFound:
    """A path id that matches no row carries the entity's own 404 code."""

    def test_unknown_company_path_returns_company_not_found(self, api: ApiClient):
        """PRD §3.1: "Reading a single issuer returns its stored posture alongside `open_inquiry_count`, `dividend_reserve_cents` and `dividend_paid_cents`; addressing an issuer that does not exist yields `ERR_COMPANY_NOT_FOUND`."

        Design: Corner/entities/unknown_company_and_contact_paths_return_typed_not_found
        """
        fixtures.set_clock(api, CLOCK_START)

        validate_error(
            api.get_company(MISSING_COMPANY_ID, IR_ADMIN),
            ApiErrorId.COMPANY_NOT_FOUND.value,
        )

    def test_unknown_contact_path_returns_contact_not_found(self, api: ApiClient):
        """PRD §3.2: "A `company_id` that resolves to nothing yields `ERR_COMPANY_NOT_FOUND`; addressing a contact that does not exist yields `ERR_CONTACT_NOT_FOUND`."

        Design: Corner/entities/unknown_company_and_contact_paths_return_typed_not_found
        """
        fixtures.set_clock(api, CLOCK_START)

        validate_error(
            api.get_contact(MISSING_CONTACT_ID, IR_ADMIN),
            ApiErrorId.CONTACT_NOT_FOUND.value,
        )


class TestInquiryRequiredFields:
    """POST /inquiries needs both topic_category and subject."""

    @staticmethod
    def _company_and_holder(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api,
            ticker="REQ",
            legal_name="Required Fields Corp",
            shares_outstanding=1000000,
        )
        holder = fixtures.create_contact(
            api,
            company["id"],
            contact_type="RETAIL_HOLDER",
            display_name="Req Holder",
            email="req@retail.test",
            shares_held=100,
        )
        return company, holder

    def test_inquiry_intake_without_topic_category_is_rejected(self, api: ApiClient):
        """PRD §2.10: "Request shape — the body and query parameters parse; every required field is present and non-null; enum-typed values are members of their declared enumeration; numeric fields are non-negative; `shares_held` and `capacity_slots` are integers; `window_start` is strictly before `window_end`; `guidance_low` is less than or equal to `guidance_high`; and any reason-style string supplied is non-empty (`ERR_INVALID_REQUEST`)."
        PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."

        Design: Corner/entities/inquiry_creation_missing_required_fields_rejected
        """
        company, holder = self._company_and_holder(api)

        validate_error(
            api.create_inquiry(
                {
                    "company_id": company["id"],
                    "contact_id": holder["id"],
                    "subject": "Where is my dividend cheque?",
                },
                IR_ANALYST,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        rows, meta = validate_paginated(
            api.list_inquiries(IR_ANALYST, company_id=company["id"])
        )
        assert rows == []
        assert meta["total_count"] == 0

        reread = validate_success(api.get_company(company["id"], IR_ANALYST))
        assert reread["open_inquiry_count"] == 0
        assert reread["version"] == 1

    def test_inquiry_intake_without_subject_is_rejected(self, api: ApiClient):
        """PRD §3.5: "Either an `IRAdmin` or an `IRAnalyst` intakes one on the inquirer's behalf, naming the issuer through `company_id` and the inquirer through `contact_id`, and supplying a `topic_category` — one of `DIVIDEND`, `RECORD_DATE`, `PROXY`, `GUIDANCE`, `MODEL_REQUEST` or `OTHER` — plus a `subject` line that must be non-empty and at most 200 characters."
        PRD §2.10: "Request shape — the body and query parameters parse; every required field is present and non-null; enum-typed values are members of their declared enumeration; numeric fields are non-negative; `shares_held` and `capacity_slots` are integers; `window_start` is strictly before `window_end`; `guidance_low` is less than or equal to `guidance_high`; and any reason-style string supplied is non-empty (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/inquiry_creation_missing_required_fields_rejected
        """
        company, holder = self._company_and_holder(api)

        validate_error(
            api.create_inquiry(
                {
                    "company_id": company["id"],
                    "contact_id": holder["id"],
                    "topic_category": "DIVIDEND",
                },
                IR_ANALYST,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        _, meta = validate_paginated(
            api.list_inquiries(IR_ANALYST, company_id=company["id"])
        )
        assert meta["total_count"] == 0


class TestContactCreationDefaults:
    """POST /contacts with only the four required inputs."""

    def test_contact_creation_applies_declared_defaults(self, api: ApiClient):
        """PRD §3.2: "Four inputs are optional: `shares_held` defaults to 0 and may never be negative; `nda_on_file` defaults to false; `coverage_status` defaults to `NOT_COVERING` and may otherwise be `INITIATED` or `SUSPENDED`; and `activist_flag` defaults to false."
        PRD §3.2: "Three fields are seeded by the system and cannot be supplied at creation: `model_access_status` starts at `NONE`, `threat_level` starts at `NONE`, and `dividend_received_cents` starts at 0."
        PRD §3.2: "Both tier boundaries are inclusive on their low side, so exactly 1.0000 is `TIER_2` and exactly 5.0000 is `TIER_1`, while a holder of no shares is `UNTIERED` and never `TIER_3`."

        Design: Corner/entities/contact_creation_defaults_when_optional_fields_omitted
        """
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="DEF", legal_name="Defaults Corp", shares_outstanding=1000000
        )

        contact = validate_success(
            api.create_contact(
                factories.contact_payload(
                    company["id"],
                    contact_type="RETAIL_HOLDER",
                    display_name="Default Holder",
                    email="def@retail.test",
                ),
                IR_ADMIN,
            ),
            expected_status=201,
        )

        assertions.assert_contact(
            contact,
            company_id=company["id"],
            contact_type="RETAIL_HOLDER",
            shares_held=0,
            ownership_pct=assertions.approx_4dp(0.0),
            target_tier="UNTIERED",
            nda_on_file=False,
            coverage_status="NOT_COVERING",
            activist_flag=False,
            model_access_status="NONE",
            threat_level="NONE",
            dividend_received_cents=0,
            version=1,
        )


class TestContactOwnershipDerivation:
    """ownership_pct and target_tier are computed, never supplied."""

    def test_contact_creation_computes_ownership_pct_and_tier_1(self, api: ApiClient):
        """PRD §3.2: "On creation, and again on every position update, the system divides the contact's `shares_held` by the issuer's `shares_outstanding` as stored at that moment, multiplies the quotient by 100, and rounds the result half up to 4 decimal places to obtain `ownership_pct`."
        PRD §3.2: "From that rounded figure — never from the raw quotient — it derives the outreach tier stored in `target_tier`, evaluated top to bottom with the first matching clause winning: a percentage of at least 5.0 is `TIER_1`; otherwise a percentage of at least 1.0 is `TIER_2`; otherwise any percentage strictly greater than zero is `TIER_3`; and a percentage of exactly zero is `UNTIERED`."

        Design: Corner/entities/contact_creation_computes_ownership_pct_and_tier
        """
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="OWN", legal_name="Ownership Corp", shares_outstanding=1000000
        )

        contact = validate_success(
            api.create_contact(
                factories.contact_payload(
                    company["id"],
                    contact_type="INSTITUTIONAL_HOLDER",
                    display_name="Big Holder",
                    email="big@funds.test",
                    shares_held=60000,
                ),
                IR_ADMIN,
            ),
            expected_status=201,
        )

        assertions.assert_contact(
            contact,
            shares_held=60000,
            ownership_pct=assertions.approx_4dp(6.0000),
            target_tier="TIER_1",
            version=1,
        )

    def test_contact_creation_leaves_the_issuer_row_untouched(self, api: ApiClient):
        """PRD §2.7: "`disclosure_posture` is a **stored** field, and only four events re-derive it: an operator-triggered posture recompute, a shareholder-servicing action that sets a threat level, a share-position update that automatically escalates a contact's threat level, and the fourth link of the disclosure-withdrawal cascade described in §3.4."
        PRD §2.11: "It is refreshed by inquiry intake, by the dispatch of an approved answer, and by every cascade link that changes an inquiry's status, and each refresh is a **full recount** over the issuer's inquiries rather than an incremental adjustment."
        PRD §2.5: "`version` (integer): a counter that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/contact_creation_computes_ownership_pct_and_tier
        """
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="OWNB", legal_name="Ownership Issuer Corp", shares_outstanding=1000000
        )

        fixtures.create_contact(
            api,
            company["id"],
            contact_type="INSTITUTIONAL_HOLDER",
            display_name="Big Holder",
            email="big@funds.test",
            shares_held=60000,
        )

        reread = validate_success(api.get_company(company["id"], IR_ADMIN))
        assert reread["version"] == 1
        assert reread["shares_outstanding"] == 1000000
        assert reread["open_inquiry_count"] == 0
        assertions.assert_ts_equals(
            reread["posture_recomputed_at"], CLOCK_START, "posture_recomputed_at"
        )


class TestResponseDraftSystemFields:
    """author_user_id comes from the acting header, not the body."""

    def test_response_draft_stamps_author_user_id_from_the_actor_header(
        self, api: ApiClient
    ):
        """PRD §3.6: "The acting `X-User-ID` is stamped as `author_user_id` and becomes the only user permitted to move the draft forward; `reviewer_user_id`, `reviewer_note`, `pinned_disclosure_version` and `blocked_reason` all start null, `status` starts at `DRAFT`, `revision_round` starts at 1, and `version` starts at 1."
        PRD §2.1: "When `X-User-Role` is `IRAdmin`, `IRAnalyst`, `DisclosureOfficer` or `TransferAgentLiaison`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity: the server records it where a workflow calls for an audit stamp — as `author_user_id` and `reviewer_user_id` on a response draft, and as `submitted_by_user_id`, `acknowledged_by_user_id` and `executed_by_user_id` on a transfer-agent instruction — and compares it to previously recorded stamps to enforce segregation of duties, but it never compares it to any entity's `id`."

        Design: Corner/entities/response_draft_system_fields_come_from_the_actor_header
        """
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="SYS", legal_name="System Fields Corp", shares_outstanding=1000000
        )
        holder = fixtures.create_contact(
            api,
            company["id"],
            contact_type="RETAIL_HOLDER",
            display_name="Sys Holder",
            email="sys@retail.test",
            shares_held=100,
        )
        inquiry = fixtures.create_routed_inquiry(
            api,
            company["id"],
            holder["id"],
            topic_category="OTHER",
            subject="How do I update my address?",
            headers=IR_ANALYST_2,
        )

        draft = validate_success(
            api.create_response_draft(
                factories.response_draft_payload(
                    inquiry["id"],
                    body_text="Please use the shareholder portal to update your address of record.",
                    disclosure_class="PUBLIC_DOMAIN",
                ),
                IR_ANALYST_2,
            ),
            expected_status=201,
        )

        assertions.assert_response_draft(
            draft,
            inquiry_id=inquiry["id"],
            author_user_id=IR_ANALYST_2_USER_ID,
            reviewer_user_id=None,
            reviewer_note=None,
            pinned_disclosure_version=None,
            blocked_reason=None,
            cited_disclosure_id=None,
            status="DRAFT",
            revision_round=1,
            version=1,
        )
        assertions.assert_utc_timestamp(draft["created_at"], "created_at")
        assertions.assert_utc_timestamp(draft["updated_at"], "updated_at")


class TestRoadshowEventShapeChecks:
    """POST /roadshow-events refuses an unknown enum member and an inverted window."""

    @staticmethod
    def _company(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        return fixtures.create_company(
            api,
            ticker="TYP",
            legal_name="Type Constraints Corp",
            shares_outstanding=1000000,
        )

    def test_roadshow_event_rejects_an_event_type_outside_the_enumeration(
        self, api: ApiClient
    ):
        """PRD §2.10: "Request shape — the body and query parameters parse; every required field is present and non-null; enum-typed values are members of their declared enumeration; numeric fields are non-negative; `shares_held` and `capacity_slots` are integers; `window_start` is strictly before `window_end`; `guidance_low` is less than or equal to `guidance_high`; and any reason-style string supplied is non-empty (`ERR_INVALID_REQUEST`)."
        PRD §3.8: "An `IRAdmin` schedules one against an issuer named by `company_id`, declaring an `event_type` of `CONFERENCE` for a sponsored investor conference or `NDR` for a non-deal roadshow, a `venue_city` of at most 80 non-empty characters that is printed on the outreach plan, and the shape of the meeting grid: `window_start` is the earliest instant any slot may begin and `window_end`, which must be strictly later, is the latest instant any slot may end."

        Design: Corner/entities/roadshow_event_enum_and_range_constraints_rejected
        """
        company = self._company(api)

        validate_error(
            api.create_roadshow_event(
                factories.roadshow_event_payload(
                    company["id"],
                    event_type="SUMMIT",
                    venue_city="Paris",
                    window_start="2026-09-01T13:00:00Z",
                    window_end="2026-09-01T18:00:00Z",
                    slot_minutes=30,
                    capacity_slots=4,
                ),
                IR_ADMIN,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        _, meta = validate_paginated(
            api.list_roadshow_events(IR_ADMIN, company_id=company["id"])
        )
        assert meta["total_count"] == 0

    def test_roadshow_event_rejects_a_window_whose_start_is_not_before_its_end(
        self, api: ApiClient
    ):
        """PRD §2.10: "Request shape — the body and query parameters parse; every required field is present and non-null; enum-typed values are members of their declared enumeration; numeric fields are non-negative; `shares_held` and `capacity_slots` are integers; `window_start` is strictly before `window_end`; `guidance_low` is less than or equal to `guidance_high`; and any reason-style string supplied is non-empty (`ERR_INVALID_REQUEST`)."
        PRD §3.8: "An `IRAdmin` schedules one against an issuer named by `company_id`, declaring an `event_type` of `CONFERENCE` for a sponsored investor conference or `NDR` for a non-deal roadshow, a `venue_city` of at most 80 non-empty characters that is printed on the outreach plan, and the shape of the meeting grid: `window_start` is the earliest instant any slot may begin and `window_end`, which must be strictly later, is the latest instant any slot may end."

        Design: Corner/entities/roadshow_event_enum_and_range_constraints_rejected
        """
        company = self._company(api)

        validate_error(
            api.create_roadshow_event(
                factories.roadshow_event_payload(
                    company["id"],
                    event_type="NDR",
                    venue_city="Paris",
                    window_start="2026-09-01T18:00:00Z",
                    window_end="2026-09-01T13:00:00Z",
                    slot_minutes=30,
                    capacity_slots=4,
                ),
                IR_ADMIN,
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        _, meta = validate_paginated(
            api.list_roadshow_events(IR_ADMIN, company_id=company["id"])
        )
        assert meta["total_count"] == 0


class TestInquiryBodyForeignKeyOrder:
    """company_id is resolved before contact_id on POST /inquiries."""

    @staticmethod
    def _company_and_holder(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api, ticker="FKO", legal_name="FK Order Corp", shares_outstanding=1000000
        )
        holder = fixtures.create_contact(
            api,
            company["id"],
            contact_type="RETAIL_HOLDER",
            display_name="FK Holder",
            email="fk@retail.test",
            shares_held=100,
        )
        return company, holder

    def test_inquiry_body_fks_report_company_not_found_when_both_are_unknown(
        self, api: ApiClient
    ):
        """PRD §2.10: "Existence of every foreign key supplied in the request body, checked in body-field declaration order — `company_id` first, then `contact_id`, then `event_id`, then `inquiry_id`, then `cited_disclosure_id`, then `linked_prior_inquiry_id` — with the error being the not-found code of whichever referenced entity is missing."
        PRD §2.10: "Checks therefore run in a fixed order, and the **first** check to fail decides the response; later checks are never reached."

        Design: Corner/entities/inquiry_body_foreign_keys_checked_in_declaration_order
        """
        self._company_and_holder(api)

        validate_error(
            api.create_inquiry(
                factories.inquiry_payload(
                    MISSING_COMPANY_ID,
                    MISSING_CONTACT_ID,
                    topic_category="OTHER",
                    subject="Both parents missing.",
                ),
                IR_ANALYST,
            ),
            ApiErrorId.COMPANY_NOT_FOUND.value,
        )

    def test_inquiry_body_fks_report_contact_not_found_when_only_the_contact_is_unknown(
        self, api: ApiClient
    ):
        """PRD §2.10: "Existence of every foreign key supplied in the request body, checked in body-field declaration order — `company_id` first, then `contact_id`, then `event_id`, then `inquiry_id`, then `cited_disclosure_id`, then `linked_prior_inquiry_id` — with the error being the not-found code of whichever referenced entity is missing."
        PRD §3.5: "A `contact_id` or `linked_prior_inquiry_id` that resolves to nothing yields `ERR_CONTACT_NOT_FOUND` or `ERR_INQUIRY_NOT_FOUND` respectively, and a contact that exists but belongs to a different issuer than the one named is refused with `ERR_CONTACT_COMPANY_MISMATCH`."

        Design: Corner/entities/inquiry_body_foreign_keys_checked_in_declaration_order
        """
        company, holder = self._company_and_holder(api)

        validate_error(
            api.create_inquiry(
                factories.inquiry_payload(
                    company["id"],
                    MISSING_CONTACT_ID,
                    topic_category="OTHER",
                    subject="Contact missing only.",
                ),
                IR_ANALYST,
            ),
            ApiErrorId.CONTACT_NOT_FOUND.value,
        )

        accepted = validate_success(
            api.create_inquiry(
                factories.inquiry_payload(
                    company["id"],
                    holder["id"],
                    topic_category="OTHER",
                    subject="Both parents present.",
                ),
                IR_ANALYST,
            ),
            expected_status=201,
        )
        assertions.assert_inquiry(
            accepted, company_id=company["id"], contact_id=holder["id"], status="NEW"
        )


class TestSelfReferentialPriorInquiryLink:
    """linked_prior_inquiry_id must resolve, and only an ESCALATED prior scores."""

    @staticmethod
    def _company_holder_and_prior(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api,
            ticker="SLF",
            legal_name="Self Reference Corp",
            shares_outstanding=1000000,
        )
        holder = fixtures.create_contact(
            api,
            company["id"],
            contact_type="INSTITUTIONAL_HOLDER",
            display_name="Self Holder",
            email="slf@funds.test",
            shares_held=20000,
        )
        prior = fixtures.create_inquiry(
            api,
            company["id"],
            holder["id"],
            topic_category="GUIDANCE",
            subject="First question about FY2026.",
        )
        return company, holder, prior

    def test_prior_inquiry_link_that_resolves_to_nothing_returns_inquiry_not_found(
        self, api: ApiClient
    ):
        """PRD §3.5: "A `contact_id` or `linked_prior_inquiry_id` that resolves to nothing yields `ERR_CONTACT_NOT_FOUND` or `ERR_INQUIRY_NOT_FOUND` respectively, and a contact that exists but belongs to a different issuer than the one named is refused with `ERR_CONTACT_COMPANY_MISMATCH`."
        PRD §2.10: "Existence of every foreign key supplied in the request body, checked in body-field declaration order — `company_id` first, then `contact_id`, then `event_id`, then `inquiry_id`, then `cited_disclosure_id`, then `linked_prior_inquiry_id` — with the error being the not-found code of whichever referenced entity is missing."

        Design: Corner/entities/self_referential_prior_inquiry_link_must_resolve
        """
        company, holder, _prior = self._company_holder_and_prior(api)

        validate_error(
            api.create_inquiry(
                factories.inquiry_payload(
                    company["id"],
                    holder["id"],
                    topic_category="GUIDANCE",
                    subject="Follow-up to a missing inquiry.",
                    linked_prior_inquiry_id=MISSING_INQUIRY_ID,
                ),
                IR_ANALYST,
            ),
            ApiErrorId.INQUIRY_NOT_FOUND.value,
        )

    def test_prior_inquiry_link_to_a_new_inquiry_adds_no_followup_term(
        self, api: ApiClient
    ):
        """PRD §3.5: "The base term comes from the topic: 40 for `GUIDANCE`, 30 for `MODEL_REQUEST`, 20 for `PROXY`, 15 for `DIVIDEND`, 15 for `RECORD_DATE` and 10 for `OTHER`."
        PRD §3.5: "Add 10 when `linked_prior_inquiry_id` is not null **and** the inquiry it names is itself in status `ESCALATED` — a follow-up to a routine inquiry earns nothing."
        PRD §3.5: "Otherwise the queue is `IR_DESK`."
        PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."
        PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."

        Design: Corner/entities/self_referential_prior_inquiry_link_must_resolve
        """
        company, holder, prior = self._company_holder_and_prior(api)
        assert prior["status"] == "NEW"

        follow_up = validate_success(
            api.create_inquiry(
                factories.inquiry_payload(
                    company["id"],
                    holder["id"],
                    topic_category="GUIDANCE",
                    subject="Follow-up to my first question.",
                    linked_prior_inquiry_id=prior["id"],
                ),
                IR_ANALYST,
            ),
            expected_status=201,
        )

        assertions.assert_inquiry(
            follow_up,
            linked_prior_inquiry_id=prior["id"],
            sensitivity_score=40,
            routing_queue="IR_DESK",
            status="NEW",
        )
        assertions.assert_ts_equals(
            follow_up["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at"
        )

        reread = validate_success(api.get_company(company["id"], IR_ADMIN))
        assert reread["open_inquiry_count"] == 2


class TestDisclosureGuidanceFlag:
    """is_guidance is derived from disclosure_type and metric together."""

    @staticmethod
    def _company(api: ApiClient):
        fixtures.set_clock(api, CLOCK_START)
        return fixtures.create_company(
            api,
            ticker="GUI",
            legal_name="Guidance Flag Corp",
            shares_outstanding=1000000,
        )

    def test_disclosure_is_guidance_true_for_guidance_update_with_a_metric(
        self, api: ApiClient
    ):
        """PRD §3.4: "The `is_guidance` flag is not an operator's opinion but a derivation: it is true exactly when `disclosure_type` is `GUIDANCE_UPDATE` and `metric` is anything other than `NONE`, and it is that flag which selects the row into the consensus guidance band of §3.7."
        PRD §3.4: "A new row is born in `DRAFT` with `published_at` null and `version` 1."

        Design: Corner/entities/disclosure_is_guidance_flag_derived_from_type_and_metric
        """
        company = self._company(api)

        disclosure = validate_success(
            api.create_disclosure(
                factories.guidance_disclosure_payload(
                    company["id"],
                    "FY2026-EPS-RANGE",
                    metric="EPS",
                    period_label="FY2026",
                    guidance_low=2.00,
                    guidance_high=2.20,
                ),
                DISCLOSURE_OFFICER,
            ),
            expected_status=201,
        )

        assertions.assert_disclosure(
            disclosure,
            company_id=company["id"],
            disclosure_type="GUIDANCE_UPDATE",
            fact_key="FY2026-EPS-RANGE",
            metric="EPS",
            period_label="FY2026",
            is_guidance=True,
            status="DRAFT",
            published_at=None,
            version=1,
        )

    def test_disclosure_is_guidance_false_when_metric_defaults_to_none(
        self, api: ApiClient
    ):
        """PRD §3.4: "The `is_guidance` flag is not an operator's opinion but a derivation: it is true exactly when `disclosure_type` is `GUIDANCE_UPDATE` and `metric` is anything other than `NONE`, and it is that flag which selects the row into the consensus guidance band of §3.7."
        PRD §3.4: "Guidance rows carry the guidance framework itself: `metric` is one of `REVENUE`, `EPS`, `FCF_MARGIN` or `NONE` and defaults to `NONE`; `period_label` is a label such as FY2026 and defaults to null; and `guidance_low` and `guidance_high` bound the guided range, both defaulting to null and both required when `disclosure_type` is `GUIDANCE_UPDATE`, with the low end required to be less than or equal to the high end."
        PRD §3.4: "A new row is born in `DRAFT` with `published_at` null and `version` 1."

        Design: Corner/entities/disclosure_is_guidance_flag_derived_from_type_and_metric
        """
        company = self._company(api)

        disclosure = validate_success(
            api.create_disclosure(
                factories.disclosure_payload(
                    company["id"],
                    disclosure_type="PRESS_RELEASE",
                    fact_key="PR-2026-08-01",
                ),
                DISCLOSURE_OFFICER,
            ),
            expected_status=201,
        )

        assertions.assert_disclosure(
            disclosure,
            disclosure_type="PRESS_RELEASE",
            fact_key="PR-2026-08-01",
            metric="NONE",
            period_label=None,
            guidance_low=None,
            guidance_high=None,
            is_guidance=False,
            status="DRAFT",
            published_at=None,
            version=1,
        )


class TestMeetingRequestProvisionalScore:
    """Only the provisional variant runs at intake."""

    def test_meeting_request_intake_computes_only_the_provisional_score(
        self, api: ApiClient
    ):
        """PRD §3.8: "Start with tier points read from the contact's `target_tier`: 50 for `TIER_1`, 35 for `TIER_2`, 20 for `TIER_3` and 5 for `UNTIERED`."
        PRD §3.8: "Add 8 when the contact's `nda_on_file` is true, and nothing when it is false."
        PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."
        PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."
        PRD §3.8: "The **provisional** variant runs at intake, is written to `provisional_priority_score`, uses the contact as it stands at intake, and its lead-time bonus is always zero."
        PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score` null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist` false, and it increments the parent event's `request_ledger_total` by 1 along with the event's `version`."

        Design: Corner/entities/meeting_request_intake_computes_only_the_provisional_score
        """
        fixtures.set_clock(api, CLOCK_START)
        company = fixtures.create_company(
            api,
            ticker="PRV",
            legal_name="Provisional Score Corp",
            shares_outstanding=1000000,
        )
        holder = fixtures.create_contact(
            api,
            company["id"],
            contact_type="RETAIL_HOLDER",
            display_name="Retail Requester",
            email="prv@retail.test",
            shares_held=5000,
        )
        assert holder["target_tier"] == "TIER_3"

        event = fixtures.open_event(
            api,
            company["id"],
            event_type="CONFERENCE",
            venue_city="Boston",
            window_start="2026-09-01T13:00:00Z",
            window_end="2026-09-01T18:00:00Z",
            slot_minutes=30,
            capacity_slots=4,
        )
        event_version_before = event["version"]

        request = validate_success(
            api.create_meeting_request(
                factories.meeting_request_payload(
                    event["id"],
                    holder["id"],
                    requested_slot_start="2026-09-01T13:00:00Z",
                    requested_slot_end="2026-09-01T13:30:00Z",
                ),
                make_investor_headers(holder["id"]),
            ),
            expected_status=201,
        )

        assertions.assert_meeting_request(
            request,
            event_id=event["id"],
            contact_id=holder["id"],
            provisional_priority_score=assertions.approx_2dp(13.20),
            final_priority_score=None,
            allocated_at=None,
            release_reason=None,
            promoted_from_waitlist=False,
            status="REQUESTED",
        )

        reread_event = validate_success(api.get_roadshow_event(event["id"], IR_ADMIN))
        assertions.assert_roadshow_event(
            reread_event,
            request_ledger_total=1,
            allocated_count=0,
            waitlisted_count=0,
            released_count=0,
            declined_count=0,
            status="OPEN_FOR_REQUESTS",
            version=event_version_before + 1,
        )
