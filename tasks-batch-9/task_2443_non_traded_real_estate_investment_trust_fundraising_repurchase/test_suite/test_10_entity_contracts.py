"""Entity-level contracts: field surfaces, declared defaults, computed figures.

Every test here starts against an empty database with the logical clock at its
boot instant of 2026-08-01T00:00:00Z (PRD §2.6) and builds the whole of the state
it needs, so nothing carries over between tests.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    BOARD,
    COMPLIANCE,
    AccountStatus,
    ApiErrorId,
    ClassCode,
    EscrowStatus,
    LiquidityEventStatus,
    LiquidityEventType,
    RegistrationStatus,
    RepurchasePlanStatus,
    SPONSOR,
    SellingAgreementStatus,
    ShareClassStatus,
    SubscriptionStatus,
    SuitabilityStatus,
    TRANSFER_AGENT,
    VoteChoice,
    assert_ballot_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_offering_axes,
    assert_ok,
    assert_system_fields,
    assert_total_count,
    assert_version_is,
    investor_payload,
    make_investor_user_headers,
    share_class_payload,
    stockholder_vote_payload,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld

# Syntactically valid UUIDs that no request in this file ever stores.
UNSTORED_UUID = "00000000-0000-4000-8000-000000000000"
UNSTORED_UUID_B = "00000000-0000-4000-8000-000000000001"
UNSTORED_UUID_C = "00000000-0000-4000-8000-000000000002"

WAYFARER = {
    "name": "Wayfarer Diversified REIT",
    "minimum_offering_amount_cents": 25000000,
    "maximum_offering_amount_cents": 90000000000,
    "escrow_deadline_date": "2026-12-31",
    "initial_offering_price_cents": 1000,
    "rescission_window_days": 7,
}


class TestOfferingRegistrationSurface:
    def test_offering_creation_returns_every_declared_field_with_axis_defaults(self, api):
        """Pins the whole created-offering surface: echoed inputs plus the three axis defaults and the three zeroed money totals.

        PRD §3.1: "A newly created offering opens with `registration_status` at
        `DRAFT`, `escrow_status` at `COLLECTING`, `repurchase_plan_status` at
        `ACTIVE`, a null `repurchase_plan_suspension_reason`, and
        `escrow_balance_cents`, `gross_proceeds_cents` and `aggregate_nav_cents`
        all at zero."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most
        recent mutation of the row, and `version` is an integer that starts at 1
        on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/offering_creation_returns_all_declared_fields_with_axis_defaults
        """
        offering = assert_created(api.create_offering(dict(WAYFARER), SPONSOR))

        assert_fields(
            offering,
            name="Wayfarer Diversified REIT",
            minimum_offering_amount_cents=25000000,
            maximum_offering_amount_cents=90000000000,
            escrow_deadline_date="2026-12-31",
            initial_offering_price_cents=1000,
            rescission_window_days=7,
            repurchase_plan_suspension_reason=None,
            escrow_balance_cents=0,
            gross_proceeds_cents=0,
            aggregate_nav_cents=0,
        )
        assert_offering_axes(
            offering,
            registration_status=RegistrationStatus.DRAFT,
            escrow_status=EscrowStatus.COLLECTING,
            repurchase_plan_status=RepurchasePlanStatus.ACTIVE,
        )
        assert_version_is(offering, 1)

    def test_offering_retrieval_returns_the_stored_row_unchanged(self, api):
        """Pins a single-resource read as a pure read: same values, version still 1, envelope reports a single object.

        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three
        fractional digits recording when the row was first written."
        PRD §3.1: "A newly created offering opens with `registration_status` at
        `DRAFT`, `escrow_status` at `COLLECTING`, `repurchase_plan_status` at
        `ACTIVE`, a null `repurchase_plan_suspension_reason`, and
        `escrow_balance_cents`, `gross_proceeds_cents` and `aggregate_nav_cents`
        all at zero."

        Design: Corner/entities/offering_retrieval_returns_stored_offering_unchanged
        """
        created = assert_created(api.create_offering(dict(WAYFARER), SPONSOR))

        response = api.get_offering(created["id"], TRANSFER_AGENT)
        read_back = assert_ok(response)

        assert response.json()["response_type"] == "object", (
            "a single-resource read must report response_type 'object'"
        )
        assert_system_fields(read_back)
        assert_fields(
            read_back,
            id=created["id"],
            name="Wayfarer Diversified REIT",
            rescission_window_days=7,
            registration_status=RegistrationStatus.DRAFT,
            aggregate_nav_cents=0,
            created_at=created["created_at"],
        )
        assert_version_is(read_back, 1)


class TestCollectionListingContract:
    def test_investor_listing_reports_whole_filtered_set_and_flips_has_more(
        self, api, world: ReitWorld
    ):
        """Pins total_count as the count of all matching rows and has_more as false only on the last page, with pages in created_at order.

        PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count` — the total number of rows matching the filters,
        not the number returned on this page — and `has_more`, a boolean that is
        true when rows remain beyond the current page."
        PRD §2.3: "Collections are returned in ascending `created_at` order
        unless a subsection of §3 states otherwise for a particular
        computation."

        Design: Corner/entities/investor_listing_pagination_reports_total_count_and_has_more
        """
        first = world.investor(
            legal_name="Ada Fennimore",
            email="ada.fennimore@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )
        world.investor(
            legal_name="Bo Whitlock",
            email="bo.whitlock@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )
        third = world.investor(
            legal_name="Cyd Marchetti",
            email="cyd.marchetti@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )

        page_one_response = api.list_investors({"limit": 2, "offset": 0}, TRANSFER_AGENT)
        page_one = assert_total_count(page_one_response, 3)
        page_one_body = page_one_response.json()

        assert page_one_body["response_type"] == "array", (
            "a collection read must report response_type 'array'"
        )
        assert len(page_one) == 2, f"a limit of 2 must return 2 rows, got {len(page_one)}"
        assert page_one_body["meta"]["has_more"] is True, (
            "has_more must be true while a third row remains beyond the first page"
        )
        assert page_one[0]["id"] == first["id"], (
            "the first page must start with the earliest-created account"
        )

        page_two_response = api.list_investors({"limit": 2, "offset": 2}, TRANSFER_AGENT)
        page_two = assert_total_count(page_two_response, 3)
        page_two_body = page_two_response.json()

        assert len(page_two) == 1, f"the final page carries 1 row, got {len(page_two)}"
        assert page_two_body["meta"]["has_more"] is False, (
            "has_more must be false once no row remains beyond the current page"
        )
        assert page_two[0]["id"] == third["id"], (
            "the second page must continue in ascending created_at order"
        )


class TestUnresolvableIdentifiers:
    def test_unknown_offering_id_on_the_path_reports_resource_not_found(self, api):
        """Pins a syntactically valid but unstored path identifier to the 404 error envelope rather than an empty success.

        PRD §2.7: "The first reference that does not resolve to a stored row
        determines the response, which is always `ERR_RESOURCE_NOT_FOUND` with
        HTTP 404 regardless of which entity was missing."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"

        Design: Corner/entities/unknown_offering_id_returns_resource_not_found
        """
        response = api.get_offering(UNSTORED_UUID, SPONSOR)

        assert_error(response, ApiErrorId.RESOURCE_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error", (
            "a 4xx body must report response_type 'error'"
        )


class TestSchemaRejection:
    def test_offering_creation_without_its_minimum_amount_is_rejected(self, api):
        """Pins the omission of a required money input to the schema error, with no offering row left behind.

        PRD §2.9: "**Schema (400).** The body parses, every required input is
        present, and every value matches its declared type, enum, range and
        format, otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "The registration is described by a `name` of between 1 and
        120 characters, a `minimum_offering_amount_cents` of at least 1 cent
        representing the proceeds that must accumulate in escrow before escrow
        may be broken, a `maximum_offering_amount_cents` that may not be smaller
        than that minimum and caps aggregate proceeds for the life of the
        offering, an `escrow_deadline_date` in `YYYY-MM-DD` form giving the last
        calendar date on which escrow may be broken, and an
        `initial_offering_price_cents` strictly greater than zero that prices
        shares in any class for which no valuation has yet been published."

        Design: Corner/entities/missing_required_field_on_offering_creation_returns_invalid_request
        """
        response = api.create_offering(
            {
                "name": "Halfbuilt REIT",
                "maximum_offering_amount_cents": 90000000000,
                "escrow_deadline_date": "2026-12-31",
                "initial_offering_price_cents": 1000,
            },
            SPONSOR,
        )

        assert_error(response, ApiErrorId.INVALID_REQUEST, 400)
        assert_total_count(api.list_offerings(None, SPONSOR), 0)

    def test_share_class_code_outside_the_declared_enum_is_rejected(
        self, api, world: ReitWorld
    ):
        """Pins an unknown enum member on a share-class code to the schema error, with no class persisted.

        PRD §3.1: "A `SponsorOperator` adds a **ShareClass** to an offering by
        naming the parent `offering_id` and a `class_code`, which must be one of
        `T`, `S`, `D` or `I` and must be unique among that offering's classes — a
        second attempt at a code the offering already uses is refused with
        `ERR_DUPLICATE_SHARE_CLASS_CODE`."
        PRD §2.9: "**Schema (400).** The body parses, every required input is
        present, and every value matches its declared type, enum, range and
        format, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/type_constraint_violations_rejected_as_invalid_request
        """
        offering = world.offering(
            name="Typecheck REIT",
            minimum_offering_amount_cents=25000000,
            maximum_offering_amount_cents=90000000000,
            escrow_deadline_date="2026-12-31",
            initial_offering_price_cents=1000,
        )

        response = api.create_share_class(
            share_class_payload(offering["id"], class_code="X"), SPONSOR
        )

        assert_error(response, ApiErrorId.INVALID_REQUEST, 400)
        assert_total_count(api.list_share_classes(None, SPONSOR), 0)

    def test_offering_maximum_below_its_minimum_is_rejected(self, api, world: ReitWorld):
        """Pins an inverted money interval to the schema error, leaving only the earlier well-formed offering stored.

        PRD §2.9: "This level catches zero or negative money and share amounts,
        unknown enum members, malformed `YYYY-MM`, `YYYY-MM-DD` and ISO 8601
        values, a `period_end_date` earlier than its `period_start_date`, a
        `request_cutoff_at` at or before its `opens_at`, a
        `maximum_offering_amount_cents` below its `minimum_offering_amount_cents`,
        and a pagination `limit` outside 1 through 100."

        Design: Corner/entities/type_constraint_violations_rejected_as_invalid_request
        """
        world.offering(
            name="Typecheck REIT",
            minimum_offering_amount_cents=25000000,
            maximum_offering_amount_cents=90000000000,
            escrow_deadline_date="2026-12-31",
            initial_offering_price_cents=1000,
        )

        response = api.create_offering(
            {
                "name": "Inverted REIT",
                "minimum_offering_amount_cents": 90000000000,
                "maximum_offering_amount_cents": 25000000,
                "escrow_deadline_date": "2026-12-31",
                "initial_offering_price_cents": 1000,
            },
            SPONSOR,
        )

        assert_error(response, ApiErrorId.INVALID_REQUEST, 400)
        assert_total_count(api.list_offerings(None, SPONSOR), 1)

    def test_pagination_limit_of_zero_is_rejected_rather_than_clamped(self, api):
        """Pins a limit below the accepted floor to the schema error instead of silent clamping to the default.

        PRD §2.3: "A `limit` below 1 or above 100, or a non-integer value for
        either parameter, is a malformed request and is rejected with
        `ERR_INVALID_REQUEST` and HTTP 400 rather than being silently clamped."

        Design: Corner/entities/type_constraint_violations_rejected_as_invalid_request
        """
        response = api.list_investors({"limit": 0}, TRANSFER_AGENT)

        assert_error(response, ApiErrorId.INVALID_REQUEST, 400)


class TestDeclaredDefaults:
    def test_omitted_rescission_window_and_conversion_code_take_their_declared_defaults(
        self, api, world: ReitWorld
    ):
        """Pins the offering's rescission window to 5 days and a non-converting class to a null conversion code when both keys are absent.

        PRD §3.1: "The sponsor may also supply `rescission_window_days`, the
        number of days after a lot's issuance during which a stockholder may
        unwind the purchase; the field must not be negative and defaults to 5
        when omitted."
        PRD §3.1: "Finally, `converts_to_class_code` optionally names the class
        code a lot moves into once its trail-fee cap is exhausted, and is null
        for classes that never convert."
        PRD §3.1: "A new class opens `ACTIVE` with `shares_outstanding_e4` at
        zero."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_declared_defaults
        """
        offering = assert_created(
            api.create_offering(
                {
                    "name": "Default Harbor REIT",
                    "minimum_offering_amount_cents": 25000000,
                    "maximum_offering_amount_cents": 90000000000,
                    "escrow_deadline_date": "2026-12-31",
                    "initial_offering_price_cents": 1000,
                },
                SPONSOR,
            )
        )

        share_class = assert_created(
            api.create_share_class(
                {
                    "offering_id": offering["id"],
                    "class_code": ClassCode.I,
                    "upfront_selling_commission_bps": 0,
                    "dealer_manager_fee_bps": 0,
                    "annual_distribution_fee_bps": 0,
                    "distribution_fee_cap_bps": 0,
                },
                SPONSOR,
            )
        )

        assert_fields(offering, rescission_window_days=5)
        assert_fields(
            share_class,
            converts_to_class_code=None,
            status=ShareClassStatus.ACTIVE,
            shares_outstanding_e4=0,
        )
        assert world.read_offering(offering["id"])["rescission_window_days"] == 5, (
            "the defaulted rescission window must be visible on a later read"
        )

    def test_omitted_suitability_flag_on_a_selling_agreement_defaults_to_true(
        self, api, world: ReitWorld
    ):
        """Pins the agreement's absent boolean flag to true rather than false, alongside its opening status and zeroed finding counters.

        PRD §3.3: "A `ComplianceOfficer` creates it with the `offering_id`, the
        `broker_dealer_id`, a `max_commission_bps` between 0 and 1300 inclusive
        that ceilings the total upfront load the firm may place, and an optional
        `suitability_documentation_required` flag that defaults to true and
        determines whether stockholders placed under the agreement must carry
        documented suitability."
        PRD §3.3: "An agreement opens `PENDING` with `open_minor_finding_count`
        and `open_major_finding_count` both at zero."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_declared_defaults
        """
        offering = world.offering(
            name="Default Harbor REIT",
            minimum_offering_amount_cents=25000000,
            maximum_offering_amount_cents=90000000000,
            escrow_deadline_date="2026-12-31",
            initial_offering_price_cents=1000,
        )
        world.share_class(offering["id"], class_code=ClassCode.I)
        firm = world.broker_dealer(
            firm_name="Default Harbor Placement", crd_number="CRD-180001"
        )

        agreement = assert_created(
            api.create_selling_agreement(
                {
                    "offering_id": offering["id"],
                    "broker_dealer_id": firm["id"],
                    "max_commission_bps": 700,
                },
                COMPLIANCE,
            )
        )

        assert_fields(
            agreement,
            suitability_documentation_required=True,
            status=SellingAgreementStatus.PENDING,
            open_minor_finding_count=0,
            open_major_finding_count=0,
        )


class TestConcentrationBasis:
    @pytest.mark.parametrize(
        "state_code, expected_limit_cents",
        [("OH", 6000000), ("TX", 10000000)],
        ids=["strict_state_uses_the_lesser_figure", "other_state_uses_net_worth"],
    )
    def test_concentration_limit_is_ten_percent_of_the_state_dependent_basis(
        self, api, state_code, expected_limit_cents
    ):
        """Pins the computed concentration limit to 10% of the lesser of net worth and income in a strict state, and to 10% of net worth elsewhere, from identical attested figures.

        PRD §3.2: "Five states supervise non-traded offerings more strictly than
        the rest: `OH`, `MA`, `NM`, `IA` and `AL`."
        PRD §3.2: "For a stockholder resident in one of those five, the
        concentration basis is the **lesser** of the attested net worth and the
        attested annual income; for a stockholder resident anywhere else, the
        basis is the attested net worth alone, and annual income does not enter
        the arithmetic."
        PRD §3.2: "`concentration_limit_cents` is then ten percent of that basis
        — the basis multiplied by 1000 basis points, divided by 10,000, and
        floored to a whole cent."

        Design: Corner/entities/investor_concentration_limit_computed_from_state_dependent_basis
        """
        investor = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name=f"Attested Holder {state_code}",
                    email=f"attested.holder.{state_code.lower()}@example.com",
                    state_code=state_code,
                    net_worth_cents=100000000,
                    annual_income_cents=60000000,
                ),
                SPONSOR,
            )
        )

        assert investor["concentration_limit_cents"] == expected_limit_cents, (
            f"a {state_code} resident attesting 100000000 net worth and 60000000 income "
            f"must carry a limit of {expected_limit_cents}, got "
            f"{investor['concentration_limit_cents']}"
        )

    def test_new_investor_account_opens_undocumented_with_zeroed_running_totals(self, api):
        """Pins the opening state of an account: incomplete suitability, active account, no documentation reference and four zeroed running totals.

        PRD §3.2: "New accounts start with `suitability_status` at `INCOMPLETE`,
        `account_status` at `ACTIVE`, a null
        `suitability_documentation_reference`, and the running totals
        `cumulative_invested_cents`, `total_shares_e4`,
        `cumulative_distributions_received_cents` and
        `cumulative_early_repurchase_deduction_cents` all at zero."

        Design: Corner/entities/investor_concentration_limit_computed_from_state_dependent_basis
        """
        investor = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name="Otis Havercamp",
                    email="otis.havercamp@example.com",
                    state_code="OH",
                    net_worth_cents=100000000,
                    annual_income_cents=60000000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            investor,
            suitability_status=SuitabilityStatus.INCOMPLETE,
            suitability_documentation_reference=None,
            account_status=AccountStatus.ACTIVE,
            cumulative_invested_cents=0,
            total_shares_e4=0,
            cumulative_distributions_received_cents=0,
            cumulative_early_repurchase_deduction_cents=0,
        )


class TestSystemFieldsAndRevisionCounter:
    def test_documenting_suitability_advances_version_without_reminting_identity(
        self, api, world: ReitWorld
    ):
        """Pins version 1 on creation and exactly 2 after one mutation, with id and created_at untouched and the documentation reference stored.

        PRD §2.4: "Every persisted resource is addressed by an `id` that the
        server mints as a UUID."
        PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three
        fractional digits recording when the row was first written."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most
        recent mutation of the row, and `version` is an integer that starts at 1
        on creation and increases by exactly 1 on every mutation of that row."
        PRD §3.2: "A `BrokerDealerRep` or a `ComplianceOfficer` may take an
        account from `INCOMPLETE` to `DOCUMENTED`, which stores the supplied
        string in `suitability_documentation_reference` and increments the
        account's `version`."

        Design: Corner/entities/system_fields_minted_and_version_increments_on_each_mutation
        """
        created = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name="Ruth Enderby",
                    email="ruth.enderby@example.com",
                    state_code="TX",
                    net_worth_cents=400000000,
                    annual_income_cents=80000000,
                ),
                SPONSOR,
            )
        )
        assert_version_is(created, 1)

        mutated = assert_ok(
            api.record_suitability_documentation(
                created["id"],
                {"documentation_reference": "SUIT-ENDERBY-2026-08"},
                COMPLIANCE,
            )
        )

        assert_system_fields(mutated)
        assert_version_is(mutated, 2)
        assert_fields(
            mutated,
            id=created["id"],
            created_at=created["created_at"],
            suitability_status=SuitabilityStatus.DOCUMENTED,
            suitability_documentation_reference="SUIT-ENDERBY-2026-08",
        )

        read_back = world.read_investor(created["id"])
        assert_version_is(read_back, 2)
        assert_fields(
            read_back,
            id=created["id"],
            created_at=created["created_at"],
            suitability_documentation_reference="SUIT-ENDERBY-2026-08",
        )


class TestBallotImmutability:
    def test_cast_ballot_carries_no_revision_counter_and_snapshots_voting_power(
        self, api, world: ReitWorld
    ):
        """Pins a ballot to an id-and-created_at-only row whose voting power is the snapshot of the holder's shares at casting time, against a vote whose record-date snapshot is already fixed.

        PRD §2.4: "A `StockholderVote` is immutable from the instant it is
        written: it carries only `id` and `created_at`."
        PRD §2.4: "It has no `updated_at` field and no `version` field, and no
        operation in this specification modifies a ballot once cast."
        PRD §3.9: "As with a tender, the `investor_id` comes from the acting
        stockholder's `X-User-ID` rather than the payload, and
        `voting_shares_e4` is snapshotted from that stockholder's
        `total_shares_e4` at the instant the ballot is written."
        PRD §3.9: "The `SponsorOperator` then opens the solicitation:
        `OPEN_VOTE` moves `BOARD_APPROVED` to `VOTE_OPEN`, is permitted only
        while the offering's `registration_status` is anything other than
        `DRAFT`, snapshots `record_date_shares_e4` as the sum of
        `shares_outstanding_e4` across every share class of the offering, and is
        the moment ballots become acceptable."

        Design: Corner/entities/stockholder_vote_is_immutable_and_carries_no_version
        """
        funded = world.broken_escrow_offering(
            30000000,
            offering={
                "name": "Ballotwright REIT",
                "minimum_offering_amount_cents": 30000000,
                "maximum_offering_amount_cents": 50000000000,
                "escrow_deadline_date": "2026-12-31",
                "initial_offering_price_cents": 1000,
                "rescission_window_days": 5,
            },
            agreement={"max_commission_bps": 100, "suitability_documentation_required": True},
        )
        investor_id = funded["investor_id"]

        world.set_clock("2026-09-02T00:00:00Z")
        world.published_nav(
            funded["share_class_id"],
            "2026-08-01",
            "2026-08-31",
            30000000,
            0,
            "IVA-2026-08-BW",
        )

        event = world.liquidity_event(
            funded["offering_id"],
            event_type=LiquidityEventType.LISTING,
            proposed_effective_date="2027-03-01",
        )
        world.drive_liquidity_event(event["id"], "BOARD_APPROVE", BOARD)
        opened = world.drive_liquidity_event(event["id"], "OPEN_VOTE", SPONSOR)

        assert_fields(
            opened,
            status=LiquidityEventStatus.VOTE_OPEN,
            record_date_shares_e4=300000000,
        )

        response = api.cast_stockholder_vote(
            stockholder_vote_payload(event["id"], choice=VoteChoice.FOR),
            make_investor_user_headers(investor_id),
        )
        assert response.status_code == 201, (
            f"casting a ballot must return 201 Created, got {response.status_code}"
        )
        ballot = response.json()["data"]

        assert_ballot_fields(ballot)
        assert_fields(
            ballot,
            liquidity_event_id=event["id"],
            investor_id=investor_id,
            choice=VoteChoice.FOR,
            voting_shares_e4=300000000,
        )

        read_back = assert_ok(api.get_stockholder_vote(ballot["id"], SPONSOR))
        assert_ballot_fields(read_back)
        assert_fields(read_back, id=ballot["id"], voting_shares_e4=300000000)


class TestCrossReferenceResolution:
    @pytest.mark.parametrize(
        "broken_keys",
        [("offering_id", "investor_id"), ("share_class_id",)],
        ids=["offering_and_investor_both_unknown", "share_class_unknown"],
    )
    def test_unresolvable_body_foreign_keys_report_resource_not_found(
        self, api, world: ReitWorld, broken_keys
    ):
        """Pins every unresolvable body foreign key on a subscription — one or several at once — to the same 404 identifier.

        PRD §2.7: "The first reference that does not resolve to a stored row
        determines the response, which is always `ERR_RESOURCE_NOT_FOUND` with
        HTTP 404 regardless of which entity was missing."
        PRD §2.7: "A subscription request that names both an unknown offering
        and an unknown investor therefore reports the offering, because the
        offering is resolved first."

        Design: Corner/entities/cross_reference_integrity_resolves_body_foreign_keys_in_declared_order
        """
        world_rows = world.effective_offering(
            offering={
                "name": "Crossref REIT",
                "minimum_offering_amount_cents": 30000000,
                "maximum_offering_amount_cents": 50000000000,
                "escrow_deadline_date": "2026-12-31",
                "initial_offering_price_cents": 1000,
                "rescission_window_days": 5,
            },
            agreement={"max_commission_bps": 100, "suitability_documentation_required": True},
        )
        holder = world.documented_investor(
            legal_name="Ines Broadwater",
            email="ines.broadwater@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )

        payload = subscription_payload(
            world_rows["offering_id"],
            world_rows["share_class_id"],
            holder["id"],
            world_rows["selling_agreement_id"],
            gross_investment_cents=250000,
        )
        unstored = {
            "offering_id": UNSTORED_UUID,
            "investor_id": UNSTORED_UUID_B,
            "share_class_id": UNSTORED_UUID_C,
        }
        for key in broken_keys:
            payload[key] = unstored[key]

        response = api.create_subscription(payload, SPONSOR)

        assert_error(response, ApiErrorId.RESOURCE_NOT_FOUND, 404)
        assert_total_count(api.list_subscriptions(None, SPONSOR), 0)

    def test_fully_resolvable_subscription_body_is_priced_off_the_initial_offering_price(
        self, api, world: ReitWorld
    ):
        """Pins the same flat endpoint accepting a body whose four foreign keys all resolve, pricing the ticket off the initial offering price with both load lines at zero.

        PRD §3.4: "Consider the valuation records for the share class that are
        currently `PUBLISHED`. If there are none, the price is the offering's
        `initial_offering_price_cents`."
        PRD §3.4: "`upfront_selling_commission_cents` is the gross investment
        multiplied by the class's `upfront_selling_commission_bps`, divided by
        10,000, rounded half up to a whole cent."
        PRD §3.4: "`net_invested_cents` is the gross investment less the sum of
        those two rounded lines."
        PRD §3.4: "`shares_issued_e4` is the net invested amount multiplied by
        10,000 and divided by the pinned transaction price, floored to a whole
        share unit — a stockholder is never issued a fraction of a
        ten-thousandth of a share."
        PRD §3.4: "A freshly authored subscription sits in `PENDING` with a null
        `rejection_reason` and a null `accepted_at`."

        Design: Corner/entities/cross_reference_integrity_resolves_body_foreign_keys_in_declared_order
        """
        world_rows = world.effective_offering(
            offering={
                "name": "Crossref REIT",
                "minimum_offering_amount_cents": 30000000,
                "maximum_offering_amount_cents": 50000000000,
                "escrow_deadline_date": "2026-12-31",
                "initial_offering_price_cents": 1000,
                "rescission_window_days": 5,
            },
            agreement={"max_commission_bps": 100, "suitability_documentation_required": True},
        )
        holder = world.documented_investor(
            legal_name="Ines Broadwater",
            email="ines.broadwater@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )

        subscription = assert_created(
            api.create_subscription(
                subscription_payload(
                    world_rows["offering_id"],
                    world_rows["share_class_id"],
                    holder["id"],
                    world_rows["selling_agreement_id"],
                    gross_investment_cents=250000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            subscription,
            offering_id=world_rows["offering_id"],
            share_class_id=world_rows["share_class_id"],
            investor_id=holder["id"],
            selling_agreement_id=world_rows["selling_agreement_id"],
            status=SubscriptionStatus.PENDING,
            rejection_reason=None,
            accepted_at=None,
            transaction_price_cents=1000,
            upfront_selling_commission_cents=0,
            dealer_manager_fee_cents=0,
            net_invested_cents=250000,
            shares_issued_e4=2500000,
            unapplied_cash_cents=0,
        )
        assert_total_count(api.list_subscriptions(None, SPONSOR), 1)
