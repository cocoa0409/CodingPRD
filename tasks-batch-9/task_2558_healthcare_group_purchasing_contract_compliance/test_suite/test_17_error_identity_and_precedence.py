"""Which error identifier a refused request reports, and which rung reported it.

Eleven path-parameterised reads that each name their own resource type while an
unmatched filter value stays an empty two-hundred, two ladders whose shape band
runs ahead of the uniqueness rung that would otherwise claim the same body, two
election guards that are never interchangeable, a settlement chain where every
machine answers with its own state code, and an activation that resolves a real
catalog item only to discover it belongs to somebody else's contract.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACTIVATION_NOT_FOUND,
    ERR_COMMITMENT_NOT_ACTIVE,
    ERR_COMMITMENT_NOT_ELECTED,
    ERR_COMMITMENT_NOT_FOUND,
    ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW,
    ERR_CONTRACT_ITEM_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DISTRIBUTION_BASIS_MISMATCH,
    ERR_DISTRIBUTION_NOT_FOUND,
    ERR_DUPLICATE_DISTRIBUTION_PERIOD,
    ERR_DUPLICATE_TIER_CODE,
    ERR_FILE_NOT_FOUND,
    ERR_INVALID_HOLDBACK_LADDER,
    ERR_INVALID_MEASUREMENT_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIER_LADDER,
    ERR_ITEM_CONTRACT_MISMATCH,
    ERR_MEASUREMENT_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_PURCHASE_LINE_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
    ERR_STALE_COMMITMENT_VERSION,
    ERR_XREF_NOT_FOUND,
)
from test_helpers.constants import FLAT_TIER_LADDER, HOLDBACK_FLAT, TIER_0
from test_helpers.fixtures import (
    collect_distribution,
    commitment_version,
    countersign_commitment,
    create_active_contract,
    create_approved_cross_reference,
    create_commitment,
    create_distribution,
    create_item,
    create_member,
    measure,
    open_measurement,
    read_commitment,
    set_clock,
)
from test_helpers.test_users import (
    UNOWNED_MEMBER_USER_ID,
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_headers,
    distributor_agent_headers,
    finance_administrator_headers,
    make_member_materials_manager_headers,
)

# Eleven syntactically valid identifiers, one per path-parameterised resource
# type, none of which matches a row.
UNKNOWN_CONTRACT_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ITEM_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_COMMITMENT_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_XREF_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_ACTIVATION_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_FILE_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_MEASUREMENT_ID = "00000000-0000-4000-8000-000000000008"
UNKNOWN_DISTRIBUTION_ID = "00000000-0000-4000-8000-000000000009"
UNKNOWN_REVIEW_ID = "00000000-0000-4000-8000-00000000000a"
UNKNOWN_PURCHASE_LINE_ID = "00000000-0000-4000-8000-00000000000b"
UNKNOWN_PARENT_CONTRACT_ID = "00000000-0000-4000-8000-00000000000c"
UNKNOWN_FILTER_FILE_ID = "00000000-0000-4000-8000-00000000000d"

# Tier ladders that each break exactly one of the three shape rules, plus the
# two that repeat TIER_1 — one otherwise well shaped, one not.
EMPTY_TIERS = []
DEFAULTLESS_TIERS = [f.tier_row("TIER_1", 1000, 50.00, 100)]
FLAT_DISCOUNT_TIERS = [
    f.tier_row(TIER_0, 0, 0.00, 800),
    f.tier_row("TIER_1", 2000, 80.00, 800),
]
REPEATED_CODE_TIERS = [
    f.tier_row(TIER_0, 0, 0.00, 0),
    f.tier_row("TIER_1", 2000, 80.00, 800),
    f.tier_row("TIER_1", 4000, 90.00, 1500),
]
REPEATED_CODE_AND_FLAT_TIERS = [
    f.tier_row(TIER_0, 0, 0.00, 0),
    f.tier_row("TIER_1", 2000, 80.00, 800),
    f.tier_row("TIER_1", 4000, 90.00, 800),
]

# Holdback ladders that each break exactly one holdback rule.
EMPTY_HOLDBACK = []
REPEATED_POOL_HOLDBACK = [f.holdback_row(0, 0), f.holdback_row(0, 250)]
OVER_RATE_HOLDBACK = [f.holdback_row(0, 1001)]
DECREASING_HOLDBACK = [f.holdback_row(0, 250), f.holdback_row(100000, 100)]


def _unknown_reads(api):
    """The eleven single-resource reads, each on an identifier that matches nothing."""
    return [
        (
            "contract",
            api.get_contract(UNKNOWN_CONTRACT_ID, headers=contract_manager_headers()),
            ERR_CONTRACT_NOT_FOUND,
        ),
        (
            "contract item",
            api.get_contract_item(UNKNOWN_ITEM_ID, headers=contract_manager_headers()),
            ERR_CONTRACT_ITEM_NOT_FOUND,
        ),
        (
            "member",
            api.get_member(UNKNOWN_MEMBER_ID, headers=contract_manager_headers()),
            ERR_MEMBER_NOT_FOUND,
        ),
        (
            "commitment",
            api.get_commitment(UNKNOWN_COMMITMENT_ID, headers=compliance_analyst_headers()),
            ERR_COMMITMENT_NOT_FOUND,
        ),
        (
            "cross-reference",
            api.get_cross_reference(
                UNKNOWN_XREF_ID,
                headers=make_member_materials_manager_headers(UNOWNED_MEMBER_USER_ID),
            ),
            ERR_XREF_NOT_FOUND,
        ),
        (
            "price activation",
            api.get_price_activation(UNKNOWN_ACTIVATION_ID, headers=contract_manager_headers()),
            ERR_ACTIVATION_NOT_FOUND,
        ),
        (
            "distributor file",
            api.get_distributor_file(UNKNOWN_FILE_ID, headers=distributor_agent_headers()),
            ERR_FILE_NOT_FOUND,
        ),
        (
            "compliance measurement",
            api.get_measurement(UNKNOWN_MEASUREMENT_ID, headers=compliance_analyst_headers()),
            ERR_MEASUREMENT_NOT_FOUND,
        ),
        (
            "fee distribution",
            api.get_distribution(
                UNKNOWN_DISTRIBUTION_ID, headers=finance_administrator_headers()
            ),
            ERR_DISTRIBUTION_NOT_FOUND,
        ),
        (
            "clinical evidence review",
            api.get_evidence_review(UNKNOWN_REVIEW_ID, headers=clinical_reviewer_headers()),
            ERR_REVIEW_NOT_FOUND,
        ),
        (
            "purchase line",
            api.get_purchase_line(
                UNKNOWN_PURCHASE_LINE_ID, headers=compliance_analyst_headers()
            ),
            ERR_PURCHASE_LINE_NOT_FOUND,
        ),
    ]


def _register(api, **overrides):
    """POST /gpo/contracts, returning the raw response so refusals can be read."""
    return api.create_contract(f.contract_payload(**overrides), headers=contract_manager_headers())


def _portfolio(api):
    return validate_paginated(
        api.list_contracts(f.page(100, 0), headers=contract_manager_headers())
    )


def _request_activation(api, commitment_id, contract_item_id, **overrides):
    payload = f.price_activation_payload(
        commitment_id, contract_item_id, effective_to="2026-08-31", **overrides
    )
    return api.create_price_activation(payload, headers=contract_manager_headers())


class TestEveryUnknownPathIdentifierReportsItsOwnCode:
    """Eleven resource types, eleven codes — and a filter value that is nobody's id."""

    def test_each_single_resource_read_names_the_resource_type_it_could_not_find(self, api):
        """PRD §2.8: "Identifiers appearing in a URL path are resolved **left to right**, and
        the first identifier that resolves to nothing terminates the request with the 404 that
        names that resource type: `ERR_CONTRACT_NOT_FOUND` for an unknown `contract_id`,
        `ERR_CONTRACT_ITEM_NOT_FOUND` for `contract_item_id`, `ERR_MEMBER_NOT_FOUND` for
        `member_id`, `ERR_COMMITMENT_NOT_FOUND` for `commitment_id`, `ERR_XREF_NOT_FOUND` for
        `xref_id`, `ERR_ACTIVATION_NOT_FOUND` for `activation_id`, `ERR_FILE_NOT_FOUND` for
        `file_id`, `ERR_MEASUREMENT_NOT_FOUND` for `measurement_id`,
        `ERR_DISTRIBUTION_NOT_FOUND` for `distribution_id`, `ERR_REVIEW_NOT_FOUND` for
        `review_id`, and `ERR_PURCHASE_LINE_NOT_FOUND` for `purchase_line_id`."
        PRD §2.9: "Applies to every path-parameterised endpoint."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        reads = _unknown_reads(api)
        assert len(reads) == 11

        for label, response, expected in reads:
            assert response.status_code == 404, "the {0} read should be a 404".format(label)
            validate_error(response, expected, 404)

    def test_no_two_unknown_reads_report_the_same_identifier(self, api):
        """PRD §2.9: "**Path existence** — every identifier in the path resolves, checked left
        to right in the order `contract_id`, `contract_item_id`, `member_id`, `commitment_id`,
        `xref_id`, `activation_id`, `file_id`, `measurement_id`, `distribution_id`, `review_id`,
        `purchase_line_id`; otherwise the matching 404 from §2.8."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        reported = [
            validate_error(response, expected, 404)["error_id"]
            for _, response, expected in _unknown_reads(api)
        ]

        # Eleven resource types do not collapse into one generic not-found.
        assert len(reported) == 11
        assert len(set(reported)) == 11

    def test_the_nested_create_resolves_its_path_before_it_reads_the_body(self, api):
        """PRD §2.8: "Only one route in the whole API nests a child under its parent, namely
        adding an item to a contract's catalog."
        PRD §2.8: "Foreign keys named in a request body are resolved after the path
        identifiers, in the order the body declares them — `contract_id`, then `member_id`,
        then `contract_item_id`, then `commitment_id` — and an unresolvable one returns the
        same 404 error identifier as its path counterpart."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        # The body is entirely well formed: only the parent in the path is missing.
        response = api.create_contract_item(
            UNKNOWN_PARENT_CONTRACT_ID,
            f.contract_item_payload(),
            headers=contract_manager_headers(),
        )

        validate_error(response, ERR_CONTRACT_NOT_FOUND, 404)

    def test_an_unmatched_filter_value_is_an_empty_page_rather_than_a_not_found(self, api):
        """PRD §2.8: "Consequently, children are discovered by **filtering a top-level list**,
        not by reading a nested path: catalog items and evidence reviews and fee distributions
        are filtered by `contract_id`, compliance measurements by `commitment_id`, purchase
        lines by `distributor_file_id`, commitments by `member_id` and `contract_id`,
        cross-references by `member_id` and `contract_item_id`, distributor files by
        `member_id` and `contract_id`, and price activations by `commitment_id` and
        `contract_item_id`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` indicates whether rows
        remain beyond the current page."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        response = api.list_purchase_lines(
            f.page(10, 0, distributor_file_id=UNKNOWN_FILTER_FILE_ID),
            headers=compliance_analyst_headers(),
        )

        # A filter selects rows; it does not resolve a resource, so the same
        # unmatched id that is a 404 in a path is simply an empty page here.
        assert response.status_code == 200
        assert response.json()["response_type"] == "array"
        lines, meta = validate_paginated(response)
        assert lines == []
        a.assert_page_meta(meta, limit=10, offset=0, total_count=0, has_more=False)


# The ten registration bodies of the ladder scenario, differing only in their
# ladders and — for the last one — in a single out-of-range fee rate.
LADDER_BODIES = {
    "C-E1": {"tiers": EMPTY_TIERS, "holdback_tiers": HOLDBACK_FLAT},
    "C-E2": {"tiers": DEFAULTLESS_TIERS, "holdback_tiers": HOLDBACK_FLAT},
    "C-E3": {"tiers": FLAT_DISCOUNT_TIERS, "holdback_tiers": HOLDBACK_FLAT},
    "C-E4": {"tiers": REPEATED_CODE_TIERS, "holdback_tiers": HOLDBACK_FLAT},
    "C-E5": {"tiers": REPEATED_CODE_AND_FLAT_TIERS, "holdback_tiers": HOLDBACK_FLAT},
    "C-E6": {"tiers": FLAT_TIER_LADDER, "holdback_tiers": EMPTY_HOLDBACK},
    "C-E7": {"tiers": FLAT_TIER_LADDER, "holdback_tiers": REPEATED_POOL_HOLDBACK},
    "C-E8": {"tiers": FLAT_TIER_LADDER, "holdback_tiers": OVER_RATE_HOLDBACK},
    "C-E9": {"tiers": FLAT_TIER_LADDER, "holdback_tiers": DECREASING_HOLDBACK},
    "C-E10": {
        "tiers": FLAT_TIER_LADDER,
        "holdback_tiers": HOLDBACK_FLAT,
        "admin_fee_bps": 501,
    },
}

EXPECTED_LADDER_REFUSALS = {
    "C-E1": (ERR_INVALID_TIER_LADDER, 400),
    "C-E2": (ERR_INVALID_TIER_LADDER, 400),
    "C-E3": (ERR_INVALID_TIER_LADDER, 400),
    "C-E4": (ERR_DUPLICATE_TIER_CODE, 409),
    "C-E5": (ERR_INVALID_TIER_LADDER, 400),
    "C-E6": (ERR_INVALID_HOLDBACK_LADDER, 400),
    "C-E7": (ERR_INVALID_HOLDBACK_LADDER, 400),
    "C-E8": (ERR_INVALID_HOLDBACK_LADDER, 400),
    "C-E9": (ERR_INVALID_HOLDBACK_LADDER, 400),
    "C-E10": (ERR_INVALID_REQUEST, 400),
}


def _refuse(api, contract_code):
    return _register(api, contract_code=contract_code, **LADDER_BODIES[contract_code])


class TestLadderShapeOutranksTheDuplicateTierCode:
    """Two ladders, five shape rules apiece, and one repeated code that is not a shape rule."""

    def test_a_tier_ladder_that_is_empty_or_lacks_its_default_rung_is_a_shape_error(self, api):
        """PRD §3.1: "The heart of the contract is its **tier ladder**, submitted as `tiers`: an
        array of 1 to 5 entries, each an object carrying a `tier_code`, a
        `min_committed_volume_units` integer, a `min_compliance_pct` percentage, and a
        `discount_bps` integer between 0 and 5000."
        PRD §3.1: "Exactly one entry must be the **default tier**, meaning its
        `min_committed_volume_units` is 0 and its `min_compliance_pct` is 0.00 — the rung nobody
        can fall below."
        PRD §3.1: "A ladder that is empty, exceeds five entries, lacks its default entry, or
        fails the strictly-increasing test is rejected with `ERR_INVALID_TIER_LADDER` at HTTP
        400; a ladder that merely repeats a `tier_code` is instead rejected with
        `ERR_DUPLICATE_TIER_CODE` at HTTP 409, which is the uniqueness rung, not a shape
        complaint."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        validate_error(_refuse(api, "C-E1"), ERR_INVALID_TIER_LADDER, 400)

        # A single rung at 1000 units and 50.00 percent leaves nobody a floor.
        validate_error(_refuse(api, "C-E2"), ERR_INVALID_TIER_LADDER, 400)

    def test_a_discount_ladder_that_is_not_strictly_increasing_is_a_shape_error(self, api):
        """PRD §3.1: "When the entries are sorted by `min_committed_volume_units` ascending,
        `discount_bps` must be strictly increasing, so a richer volume commitment always buys a
        strictly deeper discount."
        PRD §3.1: "A ladder that is empty, exceeds five entries, lacks its default entry, or
        fails the strictly-increasing test is rejected with `ERR_INVALID_TIER_LADDER` at HTTP
        400; a ladder that merely repeats a `tier_code` is instead rejected with
        `ERR_DUPLICATE_TIER_CODE` at HTTP 409, which is the uniqueness rung, not a shape
        complaint."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        # Both rungs carry 800 basis points, so the 2000-unit rung buys nothing more.
        validate_error(_refuse(api, "C-E3"), ERR_INVALID_TIER_LADDER, 400)

    def test_a_well_shaped_ladder_that_repeats_a_tier_code_is_the_uniqueness_error(self, api):
        """PRD §3.1: "And `tier_code` must be unique within the ladder."
        PRD §2.9: "**Uniqueness** — one non-terminated commitment per member-and-contract pair
        (`ERR_DUPLICATE_COMMITMENT`); one `APPROVED` cross-reference per member-and-catalog-item
        pair and per member-and-member-item-number pair (`ERR_DUPLICATE_XREF`); one
        non-superseded compliance measurement per commitment-and-period triple
        (`ERR_DUPLICATE_MEASUREMENT_PERIOD`); one non-reversed fee distribution per
        contract-and-period triple (`ERR_DUPLICATE_DISTRIBUTION_PERIOD`); and one occurrence of
        each tier code inside a submitted tier ladder (`ERR_DUPLICATE_TIER_CODE`); all 409."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        # Default rung present, discounts 0 / 800 / 1500 strictly increasing: the
        # only defect is the second TIER_1.
        validate_error(_refuse(api, "C-E4"), ERR_DUPLICATE_TIER_CODE, 409)

    def test_the_same_repetition_over_a_flat_discount_ladder_is_the_shape_error(self, api):
        """PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at
        the first violation, so a later rung's error can never mask an earlier rung's error."
        PRD §2.9: "Two ladder-shape errors are evaluated with this rung and also carry HTTP 400:
        `ERR_INVALID_TIER_LADDER` for a malformed tier ladder and `ERR_INVALID_HOLDBACK_LADDER`
        for a malformed holdback ladder, both defined in §3.1."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        # The very same repeated TIER_1, now over 0 / 800 / 800: the shape band at
        # rung 6 answers before the uniqueness band at rung 15 is ever reached.
        validate_error(_refuse(api, "C-E5"), ERR_INVALID_TIER_LADDER, 400)

    def test_each_holdback_ladder_defect_reports_the_holdback_code(self, api):
        """PRD §3.1: "Alongside the tier ladder sits the **holdback ladder**, submitted as
        `holdback_tiers`: an array of 1 to 4 entries, each an object carrying
        `min_gross_pool_cents` and `holdback_bps`."
        PRD §3.1: "Every `min_gross_pool_cents` must be zero or greater and must be unique
        within the ladder; every `holdback_bps` must be between 0 and 1000 inclusive — at most
        ten percent; and when the entries are sorted by `min_gross_pool_cents` ascending,
        `holdback_bps` must be non-decreasing."
        PRD §3.1: "A malformed holdback ladder is rejected with `ERR_INVALID_HOLDBACK_LADDER` at
        HTTP 400."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        # Empty, a repeated pool floor, a rate above 1000, and 250 falling to 100.
        for contract_code in ("C-E6", "C-E7", "C-E8", "C-E9"):
            validate_error(_refuse(api, contract_code), ERR_INVALID_HOLDBACK_LADDER, 400)

    def test_a_fee_rate_outside_its_declared_range_is_a_plain_request_shape_failure(self, api):
        """PRD §3.1: "`admin_fee_bps` is the administrative fee rate in basis points applied to
        each on-contract purchase line's extended cost, and it must be between 0 and 500
        inclusive — at most five percent."
        PRD §2.9: "**Request shape** — the body parses, every required field is present, every
        enum value is a declared member of its enumeration, every integer sits inside its
        declared range, every date and timestamp is ISO 8601, and every decimal carries no more
        places than its declared scale; otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        # Both ladders are impeccable here, so no ladder error is available.
        validate_error(_refuse(api, "C-E10"), ERR_INVALID_REQUEST, 400)

    def test_none_of_the_refused_registrations_created_a_contract(self, api):
        """PRD §3.1: "A ladder that is empty, exceeds five entries, lacks its default entry, or
        fails the strictly-increasing test is rejected with `ERR_INVALID_TIER_LADDER` at HTTP
        400; a ladder that merely repeats a `tier_code` is instead rejected with
        `ERR_DUPLICATE_TIER_CODE` at HTTP 409, which is the uniqueness rung, not a shape
        complaint."
        PRD §3.1: "A malformed holdback ladder is rejected with `ERR_INVALID_HOLDBACK_LADDER` at
        HTTP 400."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` indicates whether rows
        remain beyond the current page."

        Design: Corner/errors/ladder_shape_errors_outrank_the_duplicate_tier_code_check
        """
        for contract_code, (expected, status) in EXPECTED_LADDER_REFUSALS.items():
            validate_error(_refuse(api, contract_code), expected, status)

        contracts, meta = _portfolio(api)
        assert contracts == []
        assert meta["total_count"] == 0


@pytest.fixture
def two_elected_commitments(api):
    """One ACTIVE contract carrying two freshly ELECTED commitments, no letters issued."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-EG",
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    first_member = create_member(api, member_code="M-1")
    second_member = create_member(api, member_code="M-2", name="Lakeside Surgical Center")
    return {
        "contract": contract,
        "first_member": first_member,
        "second_member": second_member,
        "first": create_commitment(api, first_member["id"], contract["id"]),
        "second": create_commitment(api, second_member["id"], contract["id"]),
    }


class TestElectionGuardsSpeakForTheirOwnDimension:
    """`ELECTED` is what a letter needs; `ACTIVE` is what a requalification needs."""

    def test_open_requalification_on_an_elected_commitment_reports_not_active(
        self, api, two_elected_commitments
    ):
        """PRD §3.4: "Opening a requalification is a `ComplianceAnalyst` action that moves
        `election_status` from `ACTIVE` to `REQUAL_REVIEW`, optionally recording a `reason`, and
        increments the commitment's `version` by one."
        PRD §3.4: "It requires `election_status` to be `ACTIVE` — otherwise
        `ERR_COMMITMENT_NOT_ACTIVE` — and it requires `lop_status` to be `COUNTERSIGNED`,
        otherwise `ERR_INVALID_LOP_STATE`."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        commitment = two_elected_commitments["first"]
        assert commitment["election_status"] == "ELECTED"

        response = api.open_requalification(
            commitment["id"],
            f.reason_payload("annual review"),
            headers=compliance_analyst_headers(),
        )

        validate_error(response, ERR_COMMITMENT_NOT_ACTIVE, 409)
        after = read_commitment(api, commitment["id"])
        assert after["election_status"] == "ELECTED"
        assert after["version"] == commitment["version"]

    def test_the_state_guard_answers_before_the_version_guard_when_a_measurement_opens(
        self, api, two_elected_commitments
    ):
        """PRD §3.8: "The commitment must exist and its `election_status` must be `ACTIVE` or
        `REQUAL_REVIEW`, else `ERR_COMMITMENT_NOT_ACTIVE`."
        PRD §3.8: "The declared version must match, else `ERR_STALE_COMMITMENT_VERSION` at HTTP
        412, as §2.6 describes."
        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the
        first violation, so a later rung's error can never mask an earlier rung's error."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        commitment = two_elected_commitments["first"]

        # The declared version is the commitment's true, freshly read version, so
        # the concurrency rung has nothing to complain about.
        declared = commitment_version(api, commitment["id"])
        assert declared == commitment["version"]

        response = api.create_measurement(
            f.measurement_payload(commitment["id"], declared),
            headers=compliance_analyst_headers(),
        )

        error = validate_error(response, ERR_COMMITMENT_NOT_ACTIVE, 409)
        assert error["error_id"] != ERR_STALE_COMMITMENT_VERSION

    def test_terminating_an_elected_commitment_leaves_the_letter_dimension_alone(
        self, api, two_elected_commitments
    ):
        """PRD §3.4: "The commitment has never had a tier in force and has never been counted on
        its contract, so terminating it sets `election_status` to `TERMINATED` and stops there."
        PRD §3.4: "No other letter transition touches `election_status`, and no election
        transition touches `lop_status`."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        commitment = two_elected_commitments["second"]
        assert commitment["lop_status"] == "NOT_ISSUED"

        terminated = validate_success(
            api.terminate_commitment(
                commitment["id"],
                f.reason_payload("member left the aggregation group"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )

        assert terminated["election_status"] == "TERMINATED"
        assert terminated["lop_status"] == "NOT_ISSUED"
        assert terminated["current_tier_code"] is None

    def test_issuing_a_letter_on_a_terminated_commitment_reports_not_elected(
        self, api, two_elected_commitments
    ):
        """PRD §3.4: "A `ContractManager` issues it, driving `lop_status` from `NOT_ISSUED` to
        `ISSUED` and setting `signer_name` to null; issuance is permitted only while
        `election_status` is still `ELECTED`, and a commitment that has moved past `ELECTED`
        refuses it with `ERR_COMMITMENT_NOT_ELECTED`."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        commitment = two_elected_commitments["second"]
        terminated = validate_success(
            api.terminate_commitment(
                commitment["id"],
                f.reason_payload("member left the aggregation group"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )
        # The document guard is satisfied — the letter has never been issued — so
        # the election guard is the only thing left to refuse.
        assert terminated["lop_status"] == "NOT_ISSUED"

        response = api.issue_lop(commitment["id"], {}, headers=contract_manager_headers())

        validate_error(response, ERR_COMMITMENT_NOT_ELECTED, 409)
        assert read_commitment(api, commitment["id"])["lop_status"] == "NOT_ISSUED"

    def test_countersigning_activates_the_election_and_the_refused_call_now_succeeds(
        self, api, two_elected_commitments
    ):
        """PRD §3.4: "It advances `lop_status` from `SIGNED` to `COUNTERSIGNED`."
        PRD §3.4: "In the same request it drives `election_status` from `ELECTED` to `ACTIVE`."
        PRD §3.4: "It requires `election_status` to be `ACTIVE` — otherwise
        `ERR_COMMITMENT_NOT_ACTIVE` — and it requires `lop_status` to be `COUNTERSIGNED`,
        otherwise `ERR_INVALID_LOP_STATE`."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        setup = two_elected_commitments
        commitment = setup["first"]

        countersigned = countersign_commitment(
            api, commitment["id"], setup["first_member"]["id"], signer_name="Dana Whitfield"
        )
        assert countersigned["election_status"] == "ACTIVE"
        assert countersigned["lop_status"] == "COUNTERSIGNED"

        opened = validate_success(
            api.open_requalification(
                commitment["id"],
                f.reason_payload("annual review"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )

        assert opened["election_status"] == "REQUAL_REVIEW"
        assert opened["lop_status"] == "COUNTERSIGNED"

    def test_a_measurement_opens_while_the_commitment_sits_in_requal_review(
        self, api, two_elected_commitments
    ):
        """PRD §3.8: "The commitment must exist and its `election_status` must be `ACTIVE` or
        `REQUAL_REVIEW`, else `ERR_COMMITMENT_NOT_ACTIVE`."
        PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at 0,
        `compliance_pct` at 0.00, `preliminary_compliance_pct` null, `qualified_tier_code` null,
        `basis_empty` false, and `computed_variant` null; the parent commitment's `version`
        increments by one."

        Design: Corner/errors/commitment_election_guards_report_not_elected_and_not_active
        """
        setup = two_elected_commitments
        commitment = setup["first"]
        countersign_commitment(
            api, commitment["id"], setup["first_member"]["id"], signer_name="Dana Whitfield"
        )
        opened = validate_success(
            api.open_requalification(
                commitment["id"],
                f.reason_payload("annual review"),
                headers=compliance_analyst_headers(),
            ),
            200,
        )

        measurement = validate_success(
            api.create_measurement(
                f.measurement_payload(commitment["id"], opened["version"]),
                headers=compliance_analyst_headers(),
            ),
            201,
        )

        assert measurement["status"] == "DRAFT"
        a.assert_pct(measurement["compliance_pct"], 0.00)
        assert measurement["computed_variant"] is None


@pytest.fixture
def accrual_settlement_setup(api):
    """An ACCRUAL-basis contract, a countersigned commitment, a DRAFT measurement, no purchases."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-STG",
        share_basis="ACCRUAL",
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    buyer = create_member(api, member_code="M-1")
    commitment = create_commitment(api, buyer["id"], contract["id"])
    countersign_commitment(api, commitment["id"], buyer["id"], signer_name="Dana Whitfield")
    return {
        "contract": contract,
        "member": buyer,
        "commitment": commitment,
        "measurement": open_measurement(api, commitment["id"]),
    }


class TestSettlementStateGuardsEachReportTheirOwnCode:
    """Four refusals along one settlement chain, and not one of them borrows another's code."""

    def test_finalizing_a_draft_measurement_reports_the_measurement_state(
        self, api, accrual_settlement_setup
    ):
        """PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at 0,
        `compliance_pct` at 0.00, `preliminary_compliance_pct` null, `qualified_tier_code` null,
        `basis_empty` false, and `computed_variant` null; the parent commitment's `version`
        increments by one."
        PRD §3.8: "Finalizing requires the measurement to be in `PRELIMINARY` status, else
        `ERR_INVALID_MEASUREMENT_STATE`, and requires the commitment's `election_status` to be
        `REQUAL_REVIEW`, else `ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW`."

        Design: Corner/errors/measurement_and_distribution_state_guards_return_their_own_codes
        """
        measurement = accrual_settlement_setup["measurement"]
        assert measurement["status"] == "DRAFT"

        response = api.finalize_measurement(
            measurement["id"], {}, headers=compliance_analyst_headers()
        )

        validate_error(response, ERR_INVALID_MEASUREMENT_STATE, 409)

    def test_measuring_an_empty_basis_lands_preliminary_and_refuses_a_second_run(
        self, api, accrual_settlement_setup
    ):
        """PRD §3.8: "The measure action drives `DRAFT → PRELIMINARY` — any other starting status
        returns `ERR_INVALID_MEASUREMENT_STATE` — writes the result to both `compliance_pct` and
        `preliminary_compliance_pct`, sets `computed_variant` to `PRELIMINARY`, computes
        `qualified_tier_code` from the preliminary figures, and increments the measurement's
        `version` by one."
        PRD §3.8: "When `total_category_spend_cents` comes out at 0, `compliance_pct` is 0.00 and
        `basis_empty` is set to true; otherwise `compliance_pct` is `on_contract_spend_cents`
        multiplied by 100, divided by `total_category_spend_cents`, rounded half up to two
        decimal places, and `basis_empty` is false."

        Design: Corner/errors/measurement_and_distribution_state_guards_return_their_own_codes
        """
        measurement = accrual_settlement_setup["measurement"]

        measured = measure(api, measurement["id"])
        assert measured["status"] == "PRELIMINARY"
        a.assert_pct(measured["compliance_pct"], 0.00)
        assert measured["basis_empty"] is True
        assert measured["computed_variant"] == "PRELIMINARY"

        # Measure is a transition, not an idempotent recompute.
        repeated = api.measure(measurement["id"], {}, headers=compliance_analyst_headers())

        validate_error(repeated, ERR_INVALID_MEASUREMENT_STATE, 409)

    def test_finalize_past_the_measurement_state_reaches_the_readiness_rung(
        self, api, accrual_settlement_setup
    ):
        """PRD §3.8: "Finalizing requires the measurement to be in `PRELIMINARY` status, else
        `ERR_INVALID_MEASUREMENT_STATE`, and requires the commitment's `election_status` to be
        `REQUAL_REVIEW`, else `ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW`."
        PRD §2.9: "**Requalification readiness** — a measurement may only be finalized while its
        commitment's election status is `REQUAL_REVIEW` (`ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW`),
        and a local exception may be neither endorsed nor approved while its commitment is in
        `REQUAL_REVIEW` (`ERR_REQUALIFICATION_IN_PROGRESS`); both 409."

        Design: Corner/errors/measurement_and_distribution_state_guards_return_their_own_codes
        """
        setup = accrual_settlement_setup
        measured = measure(api, setup["measurement"]["id"])
        assert measured["status"] == "PRELIMINARY"
        assert read_commitment(api, setup["commitment"]["id"])["election_status"] == "ACTIVE"

        response = api.finalize_measurement(
            setup["measurement"]["id"], {}, headers=compliance_analyst_headers()
        )

        # The measurement's own state now passes, so the next band answers.
        validate_error(response, ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW, 409)

    def test_a_second_distribution_over_the_same_period_is_the_duplicate_period_error(
        self, api, accrual_settlement_setup
    ):
        """PRD §3.9: "The new row is created in `ACCRUED` status with `collected_fee_cents` at 0,
        `basis` null, `holdback_bps_applied`, `holdback_cents`, `gross_pool_cents`,
        `net_pool_cents`, `member_pool_cents`, `member_share_total_cents`, `undistributed_cents`
        and `gpo_retained_cents` all at 0, `member_shares` an empty array, and `reverse_note`
        null."
        PRD §3.9: "`accrued_fee_cents` is computed at the moment of creation and is never
        recomputed by any later transition."
        PRD §3.9: "No distribution for the same contract in any status other than `REVERSED` may
        already cover the identical `period_start` and `period_end` pair, else
        `ERR_DUPLICATE_DISTRIBUTION_PERIOD` — a reversed settlement releases its period so it can
        be settled again."

        Design: Corner/errors/measurement_and_distribution_state_guards_return_their_own_codes
        """
        contract = accrual_settlement_setup["contract"]
        assert contract["share_basis"] == "ACCRUAL"

        first = create_distribution(api, contract["id"])
        assert first["status"] == "ACCRUED"
        a.assert_cents(first["accrued_fee_cents"])
        assert first["accrued_fee_cents"] == 0

        repeated = api.create_distribution(
            f.distribution_payload(contract["id"]), headers=finance_administrator_headers()
        )

        validate_error(repeated, ERR_DUPLICATE_DISTRIBUTION_PERIOD, 409)

    def test_collect_is_open_from_accrued_and_then_distribute_is_a_basis_mismatch(
        self, api, accrual_settlement_setup
    ):
        """PRD §3.9: "The collect action drives `ACCRUED → COLLECTED` and requires the row to be
        in `ACCRUED` status, else `ERR_INVALID_DISTRIBUTION_STATE`."
        PRD §3.9: "The `COLLECTED → DISTRIBUTED` route is legal only when `share_basis` is
        `COLLECTED`, meaning members share only cash actually received; if `share_basis` is
        `ACCRUAL`, distributing from `COLLECTED` returns `ERR_DISTRIBUTION_BASIS_MISMATCH`,
        because that contract's members are owed the billed figure and settling on the collected
        one would shortchange them."
        PRD §3.9: "Distributing pins `basis` to the contract's `share_basis` so the settlement
        records the rule it was computed under."

        Design: Corner/errors/measurement_and_distribution_state_guards_return_their_own_codes
        """
        contract = accrual_settlement_setup["contract"]
        distribution = create_distribution(api, contract["id"])

        # Collection is available whatever the basis; a zero remittance is legal.
        collected = collect_distribution(api, distribution["id"], 0)
        assert collected["status"] == "COLLECTED"

        response = api.distribute_distribution(
            distribution["id"], {}, headers=finance_administrator_headers()
        )

        # Recording the remittance on an ACCRUAL contract has stranded this row.
        validate_error(response, ERR_DISTRIBUTION_BASIS_MISMATCH, 409)
        after = validate_success(
            api.get_distribution(distribution["id"], headers=finance_administrator_headers()),
            200,
        )
        assert after["status"] == "COLLECTED"
        assert after["basis"] is None


@pytest.fixture
def two_contracts_and_a_foreign_mapping(api):
    """C-X and C-Y over one term, a commitment on C-X, and APPROVED mappings onto both items."""
    set_clock(api)
    own = create_active_contract(
        api,
        contract_code="C-X",
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    own_item = create_item(api, own["id"], vendor_item_number="V-X")
    other = create_active_contract(
        api,
        contract_code="C-Y",
        supplier_name="Northwind Medical",
        category_code="CAT-MSH",
        admin_fee_bps=250,
        member_share_bps=5000,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    other_item = create_item(
        api,
        other["id"],
        vendor_item_number="V-Y",
        item_description="Mesh graft 10x10",
        base_price_cents=5000,
        floor_price_cents=4000,
    )
    buyer = create_member(
        api,
        member_code="M-1",
        item_master=[
            f.item_master_row("MI-1"),
            f.item_master_row("MI-2", description="Mesh graft"),
        ],
    )
    commitment = create_commitment(api, buyer["id"], own["id"])
    countersign_commitment(api, commitment["id"], buyer["id"], signer_name="Dana Whitfield")
    return {
        "own_contract": own,
        "own_item": own_item,
        "other_contract": other,
        "other_item": other_item,
        "member": buyer,
        "commitment": commitment,
        "own_xref": create_approved_cross_reference(
            api, buyer["id"], own_item["id"], member_item_number="MI-1"
        ),
        "foreign_xref": create_approved_cross_reference(
            api, buyer["id"], other_item["id"], member_item_number="MI-2"
        ),
    }


class TestAnActivationMustNameItsOwnContractsItem:
    """The item resolves, the mapping is approved, and it is still the wrong contract."""

    def test_naming_the_other_contracts_item_is_a_referential_mismatch(
        self, api, two_contracts_and_a_foreign_mapping
    ):
        """PRD §3.6: "The catalog item must exist and its own contract must be the same contract
        the commitment names, else `ERR_ITEM_CONTRACT_MISMATCH`."
        PRD §2.9: "**Referential coherence** — the referenced rows belong together: a catalog item
        named by an activation belongs to the commitment's contract (`ERR_ITEM_CONTRACT_MISMATCH`),
        a member item number named by a cross-reference exists in that member's item master
        (`ERR_MEMBER_ITEM_NOT_IN_MASTER`), and a price may only be activated once an `APPROVED`
        cross-reference links the member to the item (`ERR_XREF_NOT_APPROVED`); all 409."

        Design: Corner/errors/activation_naming_an_item_from_another_contract_is_rejected
        """
        setup = two_contracts_and_a_foreign_mapping
        # V-Y is real, and this very member already has an APPROVED mapping onto it.
        assert setup["foreign_xref"]["status"] == "APPROVED"
        assert setup["other_item"]["contract_id"] == setup["other_contract"]["id"]
        assert setup["commitment"]["contract_id"] == setup["own_contract"]["id"]

        response = _request_activation(
            api, setup["commitment"]["id"], setup["other_item"]["id"]
        )

        error = validate_error(response, ERR_ITEM_CONTRACT_MISMATCH, 409)
        assert error["error_id"] != ERR_CONTRACT_ITEM_NOT_FOUND

    def test_an_unresolvable_item_id_is_still_a_body_foreign_key_not_found(
        self, api, two_contracts_and_a_foreign_mapping
    ):
        """PRD §2.9: "**Body foreign-key existence** — every foreign key in the body resolves,
        checked in body-declaration order `contract_id`, `member_id`, `contract_item_id`,
        `commitment_id`; otherwise the matching 404."
        PRD §2.8: "Foreign keys named in a request body are resolved after the path identifiers,
        in the order the body declares them — `contract_id`, then `member_id`, then
        `contract_item_id`, then `commitment_id` — and an unresolvable one returns the same 404
        error identifier as its path counterpart."

        Design: Corner/errors/activation_naming_an_item_from_another_contract_is_rejected
        """
        setup = two_contracts_and_a_foreign_mapping

        response = _request_activation(api, setup["commitment"]["id"], UNKNOWN_ITEM_ID)

        validate_error(response, ERR_CONTRACT_ITEM_NOT_FOUND, 404)

    def test_the_same_request_against_its_own_contracts_item_is_accepted(
        self, api, two_contracts_and_a_foreign_mapping
    ):
        """PRD §3.6: "An accepted request creates the activation in `DRAFT` status with `origin`
        `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."
        PRD §3.6: "The server then pins `tier_code_at_activation`: the commitment's
        `current_tier_code` if it has one, or the contract's `default_tier_code` when
        `current_tier_code` is still null — which is the case for any commitment whose letter has
        not yet been countersigned."
        PRD §3.6: "Take 10000 basis points, subtract the tier's `discount_bps`, multiply the base
        price by that difference, divide by 10000, and round the result half up to a whole number
        of cents."
        PRD §3.6: "Worked over a `base_price_cents` of 10000 against a ladder whose rungs carry
        0, 800 and 1500 basis points of discount, the tier prices are 10000, 9200 and 8500 cents
        respectively; over a `base_price_cents` of 10010 at 1500 basis points the exact result is
        8508.5 cents, which rounds half up to 8509."

        Design: Corner/errors/activation_naming_an_item_from_another_contract_is_rejected
        """
        setup = two_contracts_and_a_foreign_mapping

        activation = validate_success(
            _request_activation(api, setup["commitment"]["id"], setup["own_item"]["id"]), 201
        )

        a.assert_identifier(activation["id"])
        assert activation["status"] == "DRAFT"
        assert activation["origin"] == "REQUEST"
        assert activation["tier_code_at_activation"] == TIER_0
        # The only rung carries 0 basis points, so the tier price is the base price.
        assert activation["computed_price_cents"] == 10000
