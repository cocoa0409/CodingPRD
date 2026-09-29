"""What a row looks like the moment it is born, and how it is found again.

Creation reads, retrieval reads, paged listings, missing-row reads, missing
required fields, applied defaults, computed fields, ignored system fields, enum
and range constraints, the one immutable resource, the one nested route, and the
body-declared foreign keys of a deliberately flat graph.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COMMITMENT_NOT_FOUND,
    ERR_CONTRACT_ITEM_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
)
from test_helpers.constants import (
    FLAT_TIER_LADDER,
    HOLDBACK_FLAT,
    TIER_0,
    TWO_RUNG_TIER_LADDER,
)
from test_helpers.fixtures import (
    create_active_contract,
    create_commitment,
    create_contract,
    create_cross_reference,
    create_item,
    create_member,
    lines_of_file,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_headers,
    finance_administrator_headers,
    make_member_materials_manager_headers,
)

UNKNOWN_COMMITMENT_ID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_REVIEW_ID = "00000000-0000-0000-0000-0000000000bb"
UNKNOWN_CONTRACT_ID = "00000000-0000-0000-0000-0000000000cc"
UNKNOWN_ITEM_ID = "00000000-0000-0000-0000-0000000000dd"
UNKNOWN_MEMBER_ID = "00000000-0000-0000-0000-0000000000ee"


@pytest.fixture
def three_contracts(api):
    """Two CAT-SUT contracts and one CAT-MSH contract, all still DRAFT."""
    set_clock(api)
    first = create_contract(
        api,
        contract_code="C-PAG-1",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    second = create_contract(
        api,
        contract_code="C-PAG-2",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    third = create_contract(
        api,
        contract_code="C-PAG-3",
        supplier_name="Beta Devices",
        category_code="CAT-MSH",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    return {"first": first, "second": second, "third": third}


@pytest.fixture
def received_file(api):
    """A RECEIVED statement with two lines, on an ACTIVE contract and ACTIVE member."""
    set_clock(api)
    contract = create_active_contract(api, contract_code="C-ECC")
    member = create_member(api, member_code="M-ECC")
    file_row = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [
            f.purchase_line_row("MI-1", 3, 1250, "2026-08-05"),
            f.purchase_line_row("MI-1", 10, 900, "2026-08-06"),
        ],
        stage="RECEIVED",
    )
    return {"contract": contract, "member": member, "file": file_row}


@pytest.fixture
def reverse_reachability_setup(api):
    """One row of every child kind, each reachable only through a filtered list."""
    set_clock(api)
    contract = create_active_contract(api, contract_code="C-FKR")
    item = create_item(api, contract["id"])
    member = create_member(api, member_code="M-FKR")
    commitment = create_commitment(api, member["id"], contract["id"])
    xref = create_cross_reference(api, member["id"], item["id"])
    file_row = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [f.purchase_line_row("MI-1", 4, 1000, "2026-08-05")],
        stage="RECEIVED",
    )
    return {
        "contract": contract,
        "item": item,
        "member": member,
        "commitment": commitment,
        "xref": xref,
        "file": file_row,
    }


def _contract_page(api, **params):
    return validate_paginated(
        api.list_contracts(f.page(**params), headers=finance_administrator_headers())
    )


class TestContractCreationShape:
    """A 201 create is a full projection of a row nobody has touched yet."""

    def test_a_new_contract_is_born_draft_with_a_derived_default_tier(self, api, clock):
        """PRD §3.1: "Every new contract is born in `DRAFT` status with `evidence_endorsed`
        false and `active_commitment_count` zero."
        PRD §3.1: "On a well-formed submission the server derives `default_tier_code` as the
        `tier_code` of that single default entry."
        PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by one
        on every accepted mutation of that row, including mutations the server performs on
        its own initiative as part of a cascade."

        Design: Corner/entities/contract_creation_derives_default_tier_and_zero_counters
        """
        created = validate_success(
            api.create_contract(
                f.contract_payload(
                    contract_code="C-CRE-1",
                    tiers=[dict(row) for row in TWO_RUNG_TIER_LADDER],
                    holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
                ),
                headers=contract_manager_headers(),
            ),
            201,
        )

        a.assert_identifier(created["id"])
        assert created["default_tier_code"] == TIER_0
        assert created["status"] == "DRAFT"
        assert created["evidence_endorsed"] is False
        assert created["active_commitment_count"] == 0
        a.assert_versioned_entity(created, 1)
        a.assert_audit_timestamps(created)

    def test_both_submitted_ladders_are_echoed_back_entry_for_entry(self, api, clock):
        """PRD §3.1: "The heart of the contract is its **tier ladder**, submitted as `tiers`:
        an array of 1 to 5 entries, each an object carrying a `tier_code`, a
        `min_committed_volume_units` integer, a `min_compliance_pct` percentage, and a
        `discount_bps` integer between 0 and 5000."
        PRD §3.1: "Alongside the tier ladder sits the **holdback ladder**, submitted as
        `holdback_tiers`: an array of 1 to 4 entries, each an object carrying
        `min_gross_pool_cents` and `holdback_bps`."

        Design: Corner/entities/contract_creation_derives_default_tier_and_zero_counters
        """
        created = validate_success(
            api.create_contract(
                f.contract_payload(
                    contract_code="C-CRE-1",
                    tiers=[dict(row) for row in TWO_RUNG_TIER_LADDER],
                    holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
                ),
                headers=contract_manager_headers(),
            ),
            201,
        )

        assert len(created["tiers"]) == 2
        assert len(created["holdback_tiers"]) == 1
        a.assert_tier_ladder_echoed(created, TWO_RUNG_TIER_LADDER)
        a.assert_holdback_ladder_echoed(created, HOLDBACK_FLAT)

    def test_supplied_system_fields_are_ignored_rather_than_honoured(self, api, clock):
        """PRD §3.1: "Every new contract is born in `DRAFT` status with `evidence_endorsed`
        false and `active_commitment_count` zero."
        PRD §2.7: "Several fields in this system are **derived**: the server recomputes them
        from other rows rather than accepting them from a client."
        PRD §2.4: "Every resource in the system carries a server-minted `id` formatted as a
        UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC
        string with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`)."

        Design: Corner/entities/contract_create_extra_status_field_input_ignored
        """
        created = validate_success(
            api.create_contract(
                f.contract_payload(
                    contract_code="C-SYS",
                    tiers=[dict(row) for row in FLAT_TIER_LADDER],
                    holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
                    status="ACTIVE",
                    evidence_endorsed=True,
                    active_commitment_count=7,
                ),
                headers=contract_manager_headers(),
            ),
            201,
        )

        assert created["status"] == "DRAFT"
        assert created["evidence_endorsed"] is False
        assert created["active_commitment_count"] == 0
        a.assert_identifier(created["id"])
        assert created["version"] == 1

    def test_omitting_the_three_optional_switches_applies_the_declared_defaults(
        self, api, clock
    ):
        """PRD §3.1: "Three optional switches round out the header:
        `requires_clinical_review`, a boolean defaulting to true; `share_basis`, an
        enumeration of `ACCRUAL` or `COLLECTED` defaulting to `COLLECTED`; and
        `leakage_alert_threshold_pct`, a percentage between 0.00 and 100.00 carrying two
        decimal places and defaulting to 15.00."

        Design: Corner/entities/contract_create_applies_declared_defaults_when_optionals_omitted
        """
        payload = f.omit(
            f.contract_payload(
                contract_code="C-DEF",
                tiers=[dict(row) for row in FLAT_TIER_LADDER],
                holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
            ),
            "requires_clinical_review",
            "share_basis",
            "leakage_alert_threshold_pct",
        )

        created = validate_success(
            api.create_contract(payload, headers=contract_manager_headers()), 201
        )

        assert created["requires_clinical_review"] is True
        assert created["share_basis"] == "COLLECTED"
        a.assert_pct(created["leakage_alert_threshold_pct"], 15.00)
        assert created["status"] == "DRAFT"
        assert created["evidence_endorsed"] is False

    def test_omitting_the_mandatory_fee_rate_is_a_request_shape_failure(self, api, clock):
        """PRD §3.1: "`admin_fee_bps` is the administrative fee rate in basis points applied
        to each on-contract purchase line's extended cost, and it must be between 0 and 500
        inclusive — at most five percent."
        PRD §2.9: "**Request shape** — the body parses, every required field is present,
        every enum value is a declared member of its enumeration, every integer sits inside
        its declared range, every date and timestamp is ISO 8601, and every decimal carries
        no more places than its declared scale; otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/contract_create_missing_admin_fee_bps_returns_invalid_request
        """
        payload = f.omit(
            f.contract_payload(
                contract_code="C-MISS",
                tiers=[dict(row) for row in FLAT_TIER_LADDER],
                holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
            ),
            "admin_fee_bps",
        )

        validate_error(
            api.create_contract(payload, headers=contract_manager_headers()),
            ERR_INVALID_REQUEST,
            400,
        )

        rows, meta = _contract_page(api, limit=10, offset=0)
        assert rows == []
        a.assert_page_meta(meta, total_count=0, has_more=False)


class TestMemberRetrieval:
    """The read is a projection of what was stored, not a recomputation."""

    def test_the_member_read_returns_the_stored_item_master_and_zero_ledgers(self, api, clock):
        """PRD §3.3: "A new member is `ACTIVE`, with `watchlist_status` `NONE` and
        `fee_credit_balance_cents` zero."
        PRD §3.3: "Registration carries a `member_code` of 1 to 40 characters that must be
        globally unique, a `name` of 1 to 120 characters giving the legal entity name, an
        `aggregation_group_code` of 1 to 40 characters used purely for reporting rollups with
        no behavioural effect anywhere in this specification, and the member's `item_master`:
        an array of 1 to 50 entries, each an object carrying a `member_item_number`, a
        `description`, and a `units_per_uom` integer, with `member_item_number` unique inside
        the array."

        Design: Corner/entities/member_retrieval_returns_stored_item_master_and_zero_ledgers
        """
        created = create_member(
            api,
            member_code="M-RET",
            item_master=[
                f.item_master_row("MI-1"),
                f.item_master_row("MI-2", "Mesh graft", 5),
            ],
        )

        member = validate_success(
            api.get_member(created["id"], headers=compliance_analyst_headers()), 200
        )

        assert member["status"] == "ACTIVE"
        assert member["watchlist_status"] == "NONE"
        assert member["fee_credit_balance_cents"] == 0
        assert member["member_code"] == "M-RET"
        assert member["aggregation_group_code"] == "AGG-NORTH"
        assert [row["member_item_number"] for row in member["item_master"]] == ["MI-1", "MI-2"]
        assert [row["units_per_uom"] for row in member["item_master"]] == [1, 5]


class TestContractListingPages:
    """total_count counts the filtered set; has_more looks past the page."""

    def test_two_pages_of_two_report_the_same_total_and_opposite_has_more(
        self, api, three_contracts
    ):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the number
        of rows matching the filters before pagination is applied and `has_more` indicates
        whether rows remain beyond the current page."
        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by the
        resource's creation timestamp, `created_at`, ascending — oldest first, newest last."

        Design: Corner/entities/contract_listing_pages_with_total_count_and_has_more
        """
        first_page, first_meta = _contract_page(api, limit=2, offset=0)
        second_page, second_meta = _contract_page(api, limit=2, offset=2)

        assert len(first_page) == 2
        a.assert_page_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
        assert len(second_page) == 1
        a.assert_page_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
        a.assert_exact_ids(
            first_page + second_page,
            [
                three_contracts["first"]["id"],
                three_contracts["second"]["id"],
                three_contracts["third"]["id"],
            ],
        )

    def test_the_total_count_follows_the_category_filter_not_the_table(
        self, api, three_contracts
    ):
        """PRD §3.1: "Contracts may be listed with filters on `status` and `category_code`
        alongside the usual `limit` and `offset`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the number
        of rows matching the filters before pagination is applied and `has_more` indicates
        whether rows remain beyond the current page."

        Design: Corner/entities/contract_listing_pages_with_total_count_and_has_more
        """
        rows, meta = _contract_page(api, limit=10, offset=0, category_code="CAT-SUT")

        assert len(rows) == 2
        a.assert_page_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
        a.assert_exact_ids(
            rows, [three_contracts["first"]["id"], three_contracts["second"]["id"]]
        )


class TestUnknownIdentifierReads:
    """Each resource type answers with its own 404 identifier."""

    def test_unknown_commitment_and_review_reads_each_report_their_own_code(self, api, clock):
        """PRD §2.8: "Identifiers appearing in a URL path are resolved **left to right**, and
        the first identifier that resolves to nothing terminates the request with the 404 that
        names that resource type: `ERR_CONTRACT_NOT_FOUND` for an unknown `contract_id`,
        `ERR_CONTRACT_ITEM_NOT_FOUND` for `contract_item_id`, `ERR_MEMBER_NOT_FOUND` for
        `member_id`, `ERR_COMMITMENT_NOT_FOUND` for `commitment_id`, `ERR_XREF_NOT_FOUND` for
        `xref_id`, `ERR_ACTIVATION_NOT_FOUND` for `activation_id`, `ERR_FILE_NOT_FOUND` for
        `file_id`, `ERR_MEASUREMENT_NOT_FOUND` for `measurement_id`,
        `ERR_DISTRIBUTION_NOT_FOUND` for `distribution_id`, `ERR_REVIEW_NOT_FOUND` for
        `review_id`, and `ERR_PURCHASE_LINE_NOT_FOUND` for `purchase_line_id`."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/commitment_and_review_reads_with_unknown_id_return_not_found
        """
        commitment_error = validate_error(
            api.get_commitment(UNKNOWN_COMMITMENT_ID, headers=compliance_analyst_headers()),
            ERR_COMMITMENT_NOT_FOUND,
            404,
        )
        review_error = validate_error(
            api.get_evidence_review(UNKNOWN_REVIEW_ID, headers=clinical_reviewer_headers()),
            ERR_REVIEW_NOT_FOUND,
            404,
        )

        assert commitment_error["message"]
        assert review_error["message"]


class TestPurchaseLineComputedFieldsAndImmutability:
    """Extended cost at receipt; classification only later; no version at all."""

    def test_extended_cost_is_written_at_receipt_while_classification_waits(
        self, api, received_file
    ):
        """PRD §3.7: "An accepted submission creates the file in `RECEIVED` status and turns
        each entry of `lines` into exactly one **purchase line**, each carrying the file's
        identifier as `distributor_file_id`, the submitted `member_item_number`,
        `quantity_units`, `unit_price_paid_cents` and `purchase_date`, an
        `extended_cost_cents` computed immediately as `quantity_units` multiplied by
        `unit_price_paid_cents`, a `classification` of `UNCLASSIFIED`, a `reject_reason` of
        `NONE`, `contract_units` of 0, and `matched_vendor_item_number` null."
        PRD §3.7: "The file's `line_count` is set to the number of purchase lines created,
        while `accepted_line_count` and `rejected_line_count` remain 0 and `loaded_at` and
        `reverse_note` remain null."

        Design: Corner/entities/purchase_line_extended_cost_computed_at_file_receipt
        """
        file_row = received_file["file"]
        assert file_row["status"] == "RECEIVED"
        assert file_row["line_count"] == 2
        assert file_row["accepted_line_count"] == 0
        assert file_row["rejected_line_count"] == 0

        lines = lines_of_file(api, file_row["id"])

        assert len(lines) == 2
        assert sorted(line["extended_cost_cents"] for line in lines) == [3750, 9000]
        for line in lines:
            a.assert_line_classification(
                line,
                "UNCLASSIFIED",
                matched_vendor_item_number=None,
                contract_units=0,
                reject_reason="NONE",
            )

    def test_a_purchase_line_read_carries_no_version_and_no_updated_at(
        self, api, received_file
    ):
        """PRD §2.4: "Purchase lines are the exception. A purchase line is an append-only
        record created only as part of receiving a distributor file, never updated by any
        client request, and it therefore carries only `id` and `created_at`: it has no
        `updated_at` field and no `version` field at all."
        PRD §3.7: "Purchase lines are immutable append-only records: no request ever creates,
        updates or deletes one directly, and they are discovered only through the purchase-line
        list — filterable by `distributor_file_id`, `classification` and `reject_reason` — or
        through a single-line read."

        Design: Corner/entities/purchase_line_is_immutable_with_no_write_endpoint_or_version
        """
        file_row = received_file["file"]
        listed = lines_of_file(api, file_row["id"])
        line_id = a.line_by_item_and_quantity(listed, "MI-1", 3)["id"]

        line = validate_success(
            api.get_purchase_line(line_id, headers=compliance_analyst_headers()), 200
        )

        assert line["distributor_file_id"] == file_row["id"]
        assert line["extended_cost_cents"] == 3750
        assert "version" not in line
        assert "updated_at" not in line
        a.assert_identifier(line["id"])
        a.assert_date(line["purchase_date"])


class TestCatalogItemConstraints:
    """Rung 6 catches the unknown unit of measure and the floor above the base."""

    def test_a_unit_of_measure_outside_the_enumeration_is_refused(self, api, draft_contract):
        """PRD §3.1: "Each catalog line carries a `vendor_item_number` of 1 to 40 characters,
        unique among the items of that same contract; an `item_description` of 1 to 200
        characters; a `uom` drawn from `EA`, `BX` or `CS` naming the contract unit of measure;
        a `units_per_uom` integer of at least 1 recording how many eaches a contract unit
        contains, which is descriptive only and is **never** used in any pricing or conversion
        arithmetic; a `base_price_cents` integer strictly greater than zero giving the
        undiscounted contract price per contract unit; a `floor_price_cents` integer that is
        zero or greater and no greater than `base_price_cents`, giving the hard contractual
        price floor below which no activation may ever price; and an optional
        `requires_evidence` boolean defaulting to false."
        PRD §2.9: "**Request shape** — the body parses, every required field is present, every
        enum value is a declared member of its enumeration, every integer sits inside its
        declared range, every date and timestamp is ISO 8601, and every decimal carries no more
        places than its declared scale; otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/contract_item_unknown_uom_enum_returns_invalid_request
        """
        validate_error(
            api.create_contract_item(
                draft_contract["id"],
                f.contract_item_payload(uom="PK"),
                headers=contract_manager_headers(),
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        rows, meta = validate_paginated(
            api.list_contract_items(
                f.page(contract_id=draft_contract["id"]), headers=contract_manager_headers()
            )
        )
        assert rows == []
        a.assert_page_meta(meta, total_count=0)

    def test_a_floor_above_the_base_price_is_refused_on_the_same_rung(
        self, api, draft_contract
    ):
        """PRD §3.1: "a `floor_price_cents` integer that is zero or greater and no greater than
        `base_price_cents`, giving the hard contractual price floor below which no activation
        may ever price"
        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the
        first violation, so a later rung's error can never mask an earlier rung's error."

        Design: Corner/entities/contract_item_unknown_uom_enum_returns_invalid_request
        """
        validate_error(
            api.create_contract_item(
                draft_contract["id"],
                f.contract_item_payload(
                    vendor_item_number="V-2",
                    item_description="Mesh graft",
                    base_price_cents=5000,
                    floor_price_cents=6000,
                ),
                headers=contract_manager_headers(),
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        rows, _meta = validate_paginated(
            api.list_contract_items(
                f.page(contract_id=draft_contract["id"]), headers=contract_manager_headers()
            )
        )
        assert rows == []


class TestParentAndBodyForeignKeys:
    """The one nested route resolves its path parent; every other write names peers in the body."""

    def test_the_nested_item_create_reports_its_missing_path_parent(self, api, clock):
        """PRD §2.9: "**Path existence** — every identifier in the path resolves, checked left
        to right in the order `contract_id`, `contract_item_id`, `member_id`, `commitment_id`,
        `xref_id`, `activation_id`, `file_id`, `measurement_id`, `distribution_id`, `review_id`,
        `purchase_line_id`; otherwise the matching 404 from §2.8."
        PRD §2.8: "The resource graph is deliberately **flat**. Only one route in the whole API
        nests a child under its parent, namely adding an item to a contract's catalog."

        Design: Corner/entities/contract_item_create_under_unknown_parent_contract_not_found
        """
        validate_error(
            api.create_contract_item(
                UNKNOWN_CONTRACT_ID,
                f.contract_item_payload(),
                headers=contract_manager_headers(),
            ),
            ERR_CONTRACT_NOT_FOUND,
            404,
        )

    def test_an_unknown_catalog_item_in_the_body_reports_the_item(self, api, clock):
        """PRD §2.8: "Foreign keys named in a request body are resolved after the path
        identifiers, in the order the body declares them — `contract_id`, then `member_id`, then
        `contract_item_id`, then `commitment_id` — and an unresolvable one returns the same 404
        error identifier as its path counterpart."

        Design: Corner/entities/flat_topology_xref_body_foreign_keys_validated_not_found
        """
        member = create_member(api, member_code="M-FK")

        validate_error(
            api.create_cross_reference(
                f.cross_reference_payload(member["id"], UNKNOWN_ITEM_ID),
                headers=make_member_materials_manager_headers(member["id"]),
            ),
            ERR_CONTRACT_ITEM_NOT_FOUND,
            404,
        )

    def test_when_both_body_keys_are_unknown_the_member_is_reported_first(self, api, clock):
        """PRD §2.9: "**Body foreign-key existence** — every foreign key in the body resolves,
        checked in body-declaration order `contract_id`, `member_id`, `contract_item_id`,
        `commitment_id`; otherwise the matching 404."
        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the
        first violation, so a later rung's error can never mask an earlier rung's error."

        Design: Corner/entities/flat_topology_xref_body_foreign_keys_validated_not_found
        """
        validate_error(
            api.create_cross_reference(
                f.cross_reference_payload(UNKNOWN_MEMBER_ID, UNKNOWN_ITEM_ID),
                headers=make_member_materials_manager_headers(UNKNOWN_MEMBER_ID),
            ),
            ERR_MEMBER_NOT_FOUND,
            404,
        )

    def test_every_child_is_reachable_from_its_parent_through_a_filtered_list(
        self, api, reverse_reachability_setup
    ):
        """PRD §2.8: "Consequently, children are discovered by **filtering a top-level list**,
        not by reading a nested path: catalog items and evidence reviews and fee distributions
        are filtered by `contract_id`, compliance measurements by `commitment_id`, purchase
        lines by `distributor_file_id`, commitments by `member_id` and `contract_id`,
        cross-references by `member_id` and `contract_item_id`, distributor files by `member_id`
        and `contract_id`, and price activations by `commitment_id` and `contract_item_id`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` indicates whether rows
        remain beyond the current page."

        Design: Corner/entities/fk_reverse_reachability_reads_find_children_from_each_parent
        """
        setup = reverse_reachability_setup
        headers = finance_administrator_headers()

        items, items_meta = validate_paginated(
            api.list_contract_items(
                f.page(contract_id=setup["contract"]["id"]), headers=headers
            )
        )
        commitments, _cm = validate_paginated(
            api.list_commitments(
                f.page(
                    member_id=setup["member"]["id"], contract_id=setup["contract"]["id"]
                ),
                headers=headers,
            )
        )
        xrefs, _xm = validate_paginated(
            api.list_cross_references(
                f.page(
                    member_id=setup["member"]["id"], contract_item_id=setup["item"]["id"]
                ),
                headers=headers,
            )
        )
        lines, lines_meta = validate_paginated(
            api.list_purchase_lines(
                f.page(distributor_file_id=setup["file"]["id"]), headers=headers
            )
        )

        a.assert_exact_ids(items, [setup["item"]["id"]])
        a.assert_exact_ids(commitments, [setup["commitment"]["id"]])
        a.assert_exact_ids(xrefs, [setup["xref"]["id"]])
        assert xrefs[0]["status"] == "PROPOSED"
        assert len(lines) == 1
        assert lines[0]["distributor_file_id"] == setup["file"]["id"]
        a.assert_page_meta(items_meta, total_count=1, has_more=False)
        a.assert_page_meta(lines_meta, total_count=1, has_more=False)
