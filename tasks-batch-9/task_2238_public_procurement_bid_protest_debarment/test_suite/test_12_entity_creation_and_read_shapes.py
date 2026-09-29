"""Creation, read and listing shapes of the core procurement entities.

Every test in this module builds its own state from scratch through the public
API, because the database is empty when each test starts.
"""
from datetime import datetime
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_envelope_meta,
    assert_mutable_audit_fields,
    assert_pagination_meta,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    HEARING_OFFICER_HEADERS,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
    make_vendor_headers,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_NEXT_DAY = "2026-08-02T00:00:00Z"
BID_DUE_UTC = "2026-08-27T00:00:00Z"
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"

UNKNOWN_VENDOR_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_SOLICITATION_ID = "00000000-0000-0000-0000-0000000000aa"


# ---------------------------------------------------------------------------
# Private helpers (composed here rather than added to the shared helpers)
# ---------------------------------------------------------------------------
def _instant(value: Any) -> datetime:
    """Parse an ISO-8601 UTC instant, with or without fractional digits.

    Instants are compared at millisecond precision, so two renderings of the
    same instant that differ only in trailing zeros are the same instant.
    """
    assert isinstance(value, str) and value.endswith("Z"), (
        "expected an ISO-8601 UTC instant ending in Z, got {!r}".format(value)
    )
    text = value[:-1]
    if "." not in text:
        text += ".000"
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f")


def _assert_same_instant(actual: Any, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        "expected {} to be {}, got {!r}".format(label, expected, actual)
    )


def _assert_object_envelope(response) -> None:
    body = response.json()
    assert_envelope_meta(body["meta"])
    assert isinstance(body["meta"].get("api_request_timestamp"), str), (
        "meta.api_request_timestamp must be a string"
    )
    assert body["response_type"] == "object", (
        "a single resource must be returned with response_type object, got {!r}".format(
            body["response_type"]
        )
    )


def _assert_array_envelope(response) -> None:
    body = response.json()
    assert_envelope_meta(body["meta"])
    assert body["response_type"] == "array", (
        "a collection must be returned with response_type array, got {!r}".format(
            body["response_type"]
        )
    )


def _requirement(code: str, description: str) -> Dict[str, Any]:
    return fac.requirement_payload(
        requirement_code=code,
        description=description,
        materiality="MATERIAL",
        is_waivable=False,
    )


def _draft_solicitation_payload(
    number: str, title: str, requirement_code: str, requirement_description: str
) -> Dict[str, Any]:
    return fac.solicitation_payload(
        solicitation_number=number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[_requirement(requirement_code, requirement_description)],
    )


class TestVendorFileCreationAndReadShapes:
    """The state vendor file: registration defaults, read-back, listing, 404s."""

    def test_registering_a_vendor_returns_every_declared_default(self):
        """A newly registered vendor starts life with `eligibility_status` set to `ELIGIBLE`, a `protest_fee_balance_cents` of 0, a `debarment_strike_count` of 0, a null `active_debarment_id`, a null `reinstatement_earliest_petition_utc`, a null `suspension_reason_code` and `version` 1.

        Design: Corner/entities/corner_vendor_created_with_all_declared_defaults
        """
        fx.set_clock(CLOCK_START)

        response = api_client.create_vendor(
            fac.vendor_payload(
                legal_name="Aldergate Constructors",
                tax_id="100000030",
                contact_email="v30@example.gov",
            ),
            ADMIN_HEADERS,
        )
        vendor = validate_success(response, expected_status=201)
        _assert_object_envelope(response)

        assert vendor["legal_name"] == "Aldergate Constructors"
        assert vendor["tax_id"] == "100000030"
        assert vendor["contact_email"] == "v30@example.gov"

        assert vendor["eligibility_status"] == "ELIGIBLE"
        assert vendor["protest_fee_balance_cents"] == 0
        assert vendor["debarment_strike_count"] == 0

        assert vendor["active_debarment_id"] is None
        assert vendor["reinstatement_earliest_petition_utc"] is None
        assert vendor["suspension_reason_code"] is None

        assert is_valid_uuid(vendor["id"]), (
            "the id must be a server-minted UUID, got {!r}".format(vendor["id"])
        )
        assert_mutable_audit_fields(vendor, expected_version=1)

    def test_reading_a_vendor_by_id_returns_the_credited_balance(self):
        """A deposit credits the vendor's `protest_fee_balance_cents` by the supplied `amount_cents` and bumps the vendor's `version`; the amount must be strictly positive, and a zero or negative deposit is a shape violation rejected with `ERR_INVALID_REQUEST`.

        Design: Corner/entities/corner_vendor_retrieved_by_id_matches_stored_row
        """
        fx.set_clock(CLOCK_START)
        vendor = fx.create_vendor(
            legal_name="Brasswick Utility",
            tax_id="100000031",
            contact_email="v31@example.gov",
        )
        fx.fund_vendor(vendor["id"], 100000)

        response = api_client.get_vendor(vendor["id"], OFFICER_HEADERS)
        stored = validate_success(response)

        assert stored["id"] == vendor["id"]
        assert stored["tax_id"] == "100000031"
        assert stored["legal_name"] == "Brasswick Utility"
        assert stored["protest_fee_balance_cents"] == 100000
        assert stored["eligibility_status"] == "ELIGIBLE"

    def test_listing_vendors_reports_the_page_window_and_total_count(self):
        """Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` indicates whether any matching row remains beyond the current window.

        Design: Corner/entities/corner_vendors_listed_with_pagination_fields
        """
        fx.set_clock(CLOCK_START)
        fx.create_vendor(
            legal_name="Calder Bros Excavating",
            tax_id="100000032",
            contact_email="v32@example.gov",
        )
        fx.create_vendor(
            legal_name="Dunmoor Electric",
            tax_id="100000033",
            contact_email="v33@example.gov",
        )
        fx.create_vendor(
            legal_name="Elmsford Coatings",
            tax_id="100000034",
            contact_email="v34@example.gov",
        )

        first_response = api_client.list_vendors(
            ADMIN_HEADERS, params={"limit": 2, "offset": 0}
        )
        first_page, first_meta = validate_paginated(first_response)
        _assert_array_envelope(first_response)

        assert len(first_page) == 2, (
            "a limit of 2 must return exactly 2 rows, got {}".format(len(first_page))
        )
        assert_pagination_meta(
            first_meta, total_count=3, limit=2, offset=0, has_more=True
        )

        second_response = api_client.list_vendors(
            ADMIN_HEADERS, params={"limit": 2, "offset": 2}
        )
        second_page, second_meta = validate_paginated(second_response)

        assert len(second_page) == 1, (
            "the second page of a three-row table must hold exactly 1 row, got "
            "{}".format(len(second_page))
        )
        assert_pagination_meta(
            second_meta, total_count=3, limit=2, offset=2, has_more=False
        )

    def test_reading_an_unknown_vendor_id_is_a_not_found_error(self):
        """The per-segment mapping is: a vendor segment yields `ERR_VENDOR_NOT_FOUND`, a solicitation segment `ERR_SOLICITATION_NOT_FOUND`, a bid segment `ERR_BID_NOT_FOUND`, a protest segment `ERR_PROTEST_NOT_FOUND`, a hearing segment `ERR_HEARING_NOT_FOUND`, an award segment `ERR_AWARD_NOT_FOUND`, a debarment-proceeding segment `ERR_PROCEEDING_NOT_FOUND`, a reinstatement-petition segment `ERR_PETITION_NOT_FOUND` and a subcontractor-screening segment `ERR_SCREENING_NOT_FOUND`.

        Design: Corner/entities/corner_vendor_not_found_for_unknown_id
        """
        fx.set_clock(CLOCK_START)
        fx.create_vendor(
            legal_name="Fairholt Drainage",
            tax_id="100000035",
            contact_email="v35@example.gov",
        )

        response = api_client.get_vendor(UNKNOWN_VENDOR_ID, OFFICER_HEADERS)
        error = validate_error(
            response, ApiErrorId.ERR_VENDOR_NOT_FOUND.value, expected_status=404
        )

        assert isinstance(error["message"], str) and error["message"].strip(), (
            "the error message must be a non-empty string"
        )
        assert response.json()["response_type"] == "error"

    def test_registering_a_vendor_without_a_tax_id_is_rejected(self):
        """Request-body shape: every required input field present, every enum member recognised, every integer inside its declared range, a hearing window whose `scheduled_end_utc` is strictly after its `scheduled_start_utc` and whose length is a whole number of minutes, an `original_question_deadline_utc` strictly before the `original_bid_due_utc`, and every array declared non-empty actually non-empty — `ERR_INVALID_REQUEST`.

        Before anything else can happen, a `SystemAdmin` registers each vendor in
        the state vendor file, supplying the vendor's registered `legal_name`
        (between 1 and 200 characters), its `tax_id` and its notice-of-record
        `contact_email`.

        Design: Corner/entities/corner_vendor_creation_rejects_missing_required_tax_id
        """
        fx.set_clock(CLOCK_START)

        response = api_client.create_vendor(
            {"legal_name": "Glenmara Sitework", "contact_email": "v36@example.gov"},
            ADMIN_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        _, meta = validate_paginated(api_client.list_vendors(ADMIN_HEADERS))
        assert_pagination_meta(meta, total_count=0)


class TestSolicitationDraftingAndIssuanceShapes:
    """Drafting a solicitation, its declared defaults and its computed dates."""

    def test_drafted_solicitation_carries_null_predecessor_and_zeroed_counters(self):
        """An optional `predecessor_solicitation_id` may be supplied when the draft is being created as the successor of an earlier procurement; on an originally advertised solicitation it is null.

        Requirements created at draft time carry
        `introduced_by_addendum_sequence` of 0, meaning they were part of the
        original solicitation rather than added later. The solicitation itself
        is created in `status` `DRAFT`.

        Design: Corner/entities/corner_solicitation_defaults_predecessor_and_counters_on_creation
        """
        fx.set_clock(CLOCK_START)

        response = api_client.create_solicitation(
            _draft_solicitation_payload(
                "SOL-2238-C01",
                "Bridge Deck Sealing",
                "REQ-SEAL",
                "approved sealer product list",
            ),
            OFFICER_HEADERS,
        )
        solicitation = validate_success(response, expected_status=201)
        _assert_object_envelope(response)

        assert solicitation["status"] == "DRAFT"
        assert solicitation["issued_by_user_id"] is None
        assert solicitation["predecessor_solicitation_id"] is None

        assert solicitation["cumulative_extension_days"] == 0
        assert solicitation["addendum_count"] == 0
        assert solicitation["protest_escrow_cents"] == 0

        assert solicitation["apparent_low_bid_id"] is None
        assert solicitation["bids_opened_at_utc"] is None

        requirements, _ = validate_paginated(
            api_client.list_requirements(solicitation["id"], OFFICER_HEADERS)
        )
        assert len(requirements) == 1, (
            "the draft must carry exactly its one declared requirement, got "
            "{}".format(len(requirements))
        )
        assert requirements[0]["requirement_code"] == "REQ-SEAL"
        assert requirements[0]["introduced_by_addendum_sequence"] == 0

    def test_issuance_computes_the_effective_bid_due_and_question_deadline(self):
        """Issuance stamps `issued_by_user_id` with the acting officer's `X-User-ID`, which is the value the segregation-of-duties rule of §2.8 will later compare against, sets `effective_bid_due_utc` equal to `original_bid_due_utc`, sets `cumulative_extension_days` to 0, sets `question_deadline_utc` equal to `original_question_deadline_utc`, and increments the solicitation's `version` by 1.

        Neither `original_bid_due_utc` nor `original_question_deadline_utc` is
        ever mutated again; they are the historical record of what was first
        advertised.

        Design: Corner/entities/corner_solicitation_computed_due_dates_ignore_client_supplied_values
        """
        fx.set_clock(CLOCK_START)
        draft = fx.create_solicitation(
            solicitation_number="SOL-2238-C02",
            title="Median Cable Barrier",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc=BID_DUE_UTC,
            original_question_deadline_utc=QUESTION_DEADLINE_UTC,
            mandatory_requirements=[
                _requirement("REQ-CABLE", "high-tension cable system")
            ],
        )

        response = api_client.issue_solicitation(draft["id"], OFFICER_HEADERS)
        issued = validate_success(response)

        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == OFFICER_USER_ID

        _assert_same_instant(
            issued["effective_bid_due_utc"], BID_DUE_UTC, "effective_bid_due_utc"
        )
        _assert_same_instant(
            issued["original_bid_due_utc"], BID_DUE_UTC, "original_bid_due_utc"
        )
        _assert_same_instant(
            issued["question_deadline_utc"],
            QUESTION_DEADLINE_UTC,
            "question_deadline_utc",
        )
        assert issued["cumulative_extension_days"] == 0

    def test_a_requirement_with_an_unrecognised_materiality_is_rejected(self):
        """Each entry of `mandatory_requirements` becomes a `MandatoryRequirement` row carrying a `requirement_code` unique within the solicitation, a prose `description`, a `materiality` of either `MATERIAL` or `INFORMALITY`, and an `is_waivable` flag that defaults to false and records whether the procurement officer may waive non-compliance with that requirement.

        Design: Corner/entities/corner_requirement_materiality_enum_rejected_when_invalid
        """
        fx.set_clock(CLOCK_START)

        response = api_client.create_solicitation(
            fac.solicitation_payload(
                solicitation_number="SOL-2238-C04",
                title="Sign Panel Replacement",
                issuing_agency_code="DOT",
                estimated_value_cents=10000000,
                original_bid_due_utc=BID_DUE_UTC,
                original_question_deadline_utc=QUESTION_DEADLINE_UTC,
                mandatory_requirements=[
                    fac.requirement_payload(
                        requirement_code="REQ-SHEET",
                        description="retroreflective sheeting grade",
                        materiality="MAJOR",
                        is_waivable=False,
                    )
                ],
            ),
            OFFICER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        _, meta = validate_paginated(api_client.list_solicitations(OFFICER_HEADERS))
        assert_pagination_meta(meta, total_count=0)


class TestSealedBidCreationShapes:
    """Filing a sealed bid: server-stamped fields and parent resolution."""

    def test_a_new_bid_has_its_system_fields_stamped_by_the_server(self):
        """A new bid is created with `submitted_at_utc` from the logical clock and with both of its parallel state dimensions at their initial values: `responsiveness_status` is `UNREVIEWED` and `responsibility_status` is `NOT_REVIEWED`.

        Its `evaluated_price_cents` starts null, its `corrected_total_price_cents`
        starts null, its `informality_loading_cents` starts at 0, its
        `nonresponsive_reason_codes` starts empty and its `superseded_by_bid_id`
        starts null.

        Design: Corner/entities/corner_bid_system_fields_are_server_stamped
        """
        fx.set_clock(CLOCK_START)
        vendor = fx.create_vendor(
            legal_name="Harrowgate Bridge",
            tax_id="100000037",
            contact_email="v37@example.gov",
        )
        draft = fx.create_solicitation(
            solicitation_number="SOL-2238-C03",
            title="Deck Joint Replacement",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc=BID_DUE_UTC,
            original_question_deadline_utc=QUESTION_DEADLINE_UTC,
            mandatory_requirements=[
                _requirement("REQ-JOINT", "modular joint supplier approval")
            ],
        )
        fx.issue_solicitation(draft["id"])
        fx.set_clock(CLOCK_NEXT_DAY)
        observed_version = fx.read_solicitation(draft["id"])["version"]

        response = api_client.create_bid(
            fac.bid_payload(
                draft["id"],
                vendor["id"],
                total_price_cents=4000000,
                acknowledged_addendum_sequences=[],
                expected_solicitation_version=observed_version,
            ),
            make_vendor_headers(vendor["id"]),
        )
        bid = validate_success(response, expected_status=201)
        _assert_object_envelope(response)

        _assert_same_instant(
            bid["submitted_at_utc"], CLOCK_NEXT_DAY, "submitted_at_utc"
        )
        assert bid["responsiveness_status"] == "UNREVIEWED"
        assert bid["responsibility_status"] == "NOT_REVIEWED"

        assert bid["evaluated_price_cents"] is None
        assert bid["informality_loading_cents"] == 0
        assert bid["nonresponsive_reason_codes"] == []
        assert bid["superseded_by_bid_id"] is None

        assert bid["total_price_cents"] == 4000000
        assert bid["corrected_total_price_cents"] is None

    def test_a_bid_naming_an_unknown_solicitation_is_rejected_before_the_version_pin(
        self,
    ):
        """Foreign keys carried in a request body are resolved after every path segment has resolved.

        A `solicitation_id` that does not resolve yields
        `ERR_SOLICITATION_NOT_FOUND`; a `vendor_id`, `prime_vendor_id`,
        `sub_vendor_id` or `protester_vendor_id` that does not resolve yields
        `ERR_VENDOR_NOT_FOUND`; a `winning_bid_id` or `challenged_bid_id` that
        does not resolve yields `ERR_BID_NOT_FOUND`; a `source_protest_id` that
        does not resolve yields `ERR_PROTEST_NOT_FOUND`; and a member of
        `answers_question_ids` that does not resolve yields
        `ERR_QUESTION_NOT_FOUND`.

        Design: Corner/entities/corner_bid_creation_rejected_for_unknown_parent_solicitation
        """
        fx.set_clock(CLOCK_START)
        vendor = fx.create_vendor(
            legal_name="Jessup Milling",
            tax_id="100000039",
            contact_email="v39@example.gov",
        )
        decoy = fx.create_solicitation(
            solicitation_number="SOL-2238-C54",
            title="Unrelated Decoy Solicitation",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc=BID_DUE_UTC,
            original_question_deadline_utc=QUESTION_DEADLINE_UTC,
            mandatory_requirements=[_requirement("REQ-DECOY", "unrelated requirement")],
        )
        issued_decoy = fx.issue_solicitation(decoy["id"])
        genuine_version = issued_decoy["version"]

        response = api_client.create_bid(
            fac.bid_payload(
                UNKNOWN_SOLICITATION_ID,
                vendor["id"],
                total_price_cents=4000000,
                acknowledged_addendum_sequences=[],
                expected_solicitation_version=genuine_version,
            ),
            make_vendor_headers(vendor["id"]),
        )
        error = validate_error(
            response, ApiErrorId.ERR_SOLICITATION_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] != ApiErrorId.ERR_STALE_SOLICITATION_VERSION.value, (
            "the body foreign-key check must run before the version pin"
        )

        _, meta = validate_paginated(api_client.list_bids(OFFICER_HEADERS))
        assert_pagination_meta(meta, total_count=0)

        assert fx.read_solicitation(decoy["id"])["version"] == genuine_version


class TestAgencyRecordItemAppendOnlyShape:
    """The agency record of a protest is an append-only journal."""

    def test_a_filed_record_item_exposes_no_version_and_no_updated_at(self):
        """Four resource types are append-only journal rows and carry neither: a `MandatoryRequirement`, an `Addendum`, a `QuestionSubmission` and an `AgencyRecordItem` expose only `id` and `created_at`.

        For those four, `updated_at` and `version` are absent from the payload
        entirely — not null, absent. The server appends the item with a
        `sequence_number` equal to the protest's current `record_item_count` plus
        1, stamps `submitted_at_utc` from the logical clock and
        `submitted_by_role` with the caller's `X-User-Role`, then recomputes the
        protest's `record_item_count` and increments the protest's `version` by
        1. The first item filed with `item_type` `AGENCY_REPORT` by a caller
        acting as `ProcurementOfficer` advances the protest
        `FILED → UNDER_REVIEW` in the same request — the agency report is the
        pleading that opens the review.

        Design: Corner/entities/corner_agency_record_item_is_immutable_and_carries_no_version
        """
        fx.set_clock(CLOCK_START)
        vendor = fx.create_vendor(
            legal_name="Innismore Concrete",
            tax_id="100000038",
            contact_email="v38@example.gov",
        )
        fx.fund_vendor(vendor["id"], 100000)
        draft = fx.create_solicitation(
            solicitation_number="SOL-2238-C05",
            title="Sidewalk ADA Ramp Program",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc=BID_DUE_UTC,
            original_question_deadline_utc=QUESTION_DEADLINE_UTC,
            mandatory_requirements=[
                _requirement("REQ-ADA", "ADA detectable warning spec")
            ],
        )
        fx.issue_solicitation(draft["id"])
        fx.submit_question(
            draft["id"],
            vendor["id"],
            question_text="is a domed panel or cast-in-place warning required?",
        )
        protest = fx.file_protest(
            draft["id"],
            vendor["id"],
            grounds_code="SOLICITATION_IMPROPRIETY",
            narrative="the warning specification names one manufacturer",
        )
        fx.add_record_item(
            protest["id"], item_type="AGENCY_REPORT", document_ref="AR-C05-001"
        )

        response = api_client.list_record_items(
            protest["id"], HEARING_OFFICER_HEADERS, params={"limit": 10, "offset": 0}
        )
        items, _ = validate_paginated(response)

        assert len(items) == 1, (
            "exactly one agency record item must be on the record, got {}".format(
                len(items)
            )
        )
        item = items[0]
        assert item["sequence_number"] == 1
        assert item["item_type"] == "AGENCY_REPORT"
        assert item["document_ref"] == "AR-C05-001"
        assert item["submitted_by_role"] == "ProcurementOfficer"
        _assert_same_instant(item["submitted_at_utc"], CLOCK_START, "submitted_at_utc")

        assert "version" not in item, (
            "an append-only record item must omit version entirely, got {!r}".format(
                item.get("version")
            )
        )
        assert "updated_at" not in item, (
            "an append-only record item must omit updated_at entirely, got "
            "{!r}".format(item.get("updated_at"))
        )
        assert_append_only_shape(item)

        stored_protest = fx.read_protest(protest["id"])
        assert stored_protest["record_item_count"] == 1
        assert stored_protest["status"] == "UNDER_REVIEW"


class TestSubcontractorScreeningGraphEdge:
    """A screening is the vendor-to-vendor edge under one solicitation."""

    def test_screening_an_eligible_subcontractor_clears_and_links_both_vendors(self):
        """When the subcontractor's `eligibility_status` is `ELIGIBLE`, `result` becomes `CLEARED` and `blocked_reason_code` is null.

        In all three cases `screened_at_utc` is stamped from the logical clock
        and `rescreened_count` starts at 0.

        Design: Corner/entities/corner_subcontractor_screening_creates_a_vendor_to_vendor_graph_edge
        """
        fx.set_clock(CLOCK_START)
        prime = fx.create_vendor(
            legal_name="Kirkvale Prime Builders",
            tax_id="100000040",
            contact_email="v40@example.gov",
        )
        sub = fx.create_vendor(
            legal_name="Lowmead Rebar",
            tax_id="100000041",
            contact_email="v41@example.gov",
        )
        draft = fx.create_solicitation(
            solicitation_number="SOL-2238-C06",
            title="Retaining Wall Construction",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc=BID_DUE_UTC,
            original_question_deadline_utc=QUESTION_DEADLINE_UTC,
            mandatory_requirements=[
                _requirement("REQ-WALL", "proprietary wall system approval")
            ],
        )
        fx.issue_solicitation(draft["id"])

        response = api_client.create_subcontractor_screening(
            fac.screening_payload(draft["id"], prime["id"], sub["id"], tier=2),
            OFFICER_HEADERS,
        )
        screening = validate_success(response, expected_status=201)
        _assert_object_envelope(response)

        assert screening["result"] == "CLEARED"
        assert screening["blocked_reason_code"] is None

        assert screening["tier"] == 2
        assert screening["prime_vendor_id"] == prime["id"]
        assert screening["sub_vendor_id"] == sub["id"]
        assert screening["solicitation_id"] == draft["id"]

        _assert_same_instant(
            screening["screened_at_utc"], CLOCK_START, "screened_at_utc"
        )
        assert screening["rescreened_count"] == 0

        read_back = validate_success(
            api_client.get_subcontractor_screening(screening["id"], OFFICER_HEADERS)
        )
        assert read_back["id"] == screening["id"]
        assert read_back["result"] == "CLEARED"
        assert read_back["tier"] == 2
        assert read_back["prime_vendor_id"] == prime["id"]
        assert read_back["sub_vendor_id"] == sub["id"]
        assert read_back["solicitation_id"] == draft["id"]
