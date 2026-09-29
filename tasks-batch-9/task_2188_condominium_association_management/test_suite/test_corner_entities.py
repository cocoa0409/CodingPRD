"""Entity-level breadth probes: defaults, computed fields, identity and listing.

Every test in this module exercises the birth state of one entity -- what the
server materialises when the client supplies only the declared input fields --
plus the identity and listing contracts that hang off those entities.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import violation_case_payload
from test_helpers.fixtures import (
    add_owner,
    add_unit,
    create_association,
    draft_budget,
    post_charge,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS

#: Well-formed UUIDs that are deliberately never allocated to any row.
UNKNOWN_UNIT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ASSOCIATION_ID = "22222222-2222-4222-8222-222222222222"

HARBOR_POINT = "Harbor Point Condominium Association"
BAYVIEW_TERRACE = "Bayview Terrace Condominium Association"


# ======================================================================
# Association registration defaults
# ======================================================================
def test_registration_with_only_a_legal_name_materialises_every_bylaw_default(api):
    """A body carrying only `legal_name` must fill all 24 by-law tunables.

    PRD 2.10: "An association is registered with a `legal_name` between 1 and
    200 characters, which is required, and an optional
    `fiscal_year_start_month` between 1 and 12 inclusive that defaults to 1 and
    drives billing periods."
    PRD 2.10: "Every other governance parameter is optional at registration and
    falls back to a statutory default: `master_policy_deductible_cents`
    defaults to 2500000, `association_deductible_cap_cents` to 1000000,
    `late_fee_grace_days` to 10, `late_fee_percent_bp` to 1000,
    `late_fee_min_cents` to 2500, `late_fee_cap_cents` to 10000,
    `lien_threshold_cents` to 180000, `budget_veto_bp` to 5000,
    `special_assessment_approval_bp` to 6667, `board_quorum_seats` to 3,
    `hearing_docket_capacity` to 6, `element_window_buffer_hours` to 24,
    `reserve_adequacy_threshold_bp` to 7000, `reserve_contribution_min_bp` to
    1000, `fine_tier_1_cents` to 5000, `fine_tier_2_cents` to 10000,
    `fine_tier_3_daily_cents` to 25000, `fine_cap_cents` to 250000,
    `repeat_lookback_days` to 365, `cure_period_days` to 14,
    `appeal_window_days` to 30, `budget_notice_days` to 30,
    `certificate_validity_days` to 30, and `resale_cert_fee_cents` to 35000."
    PRD 4: "Resource-creating endpoints return HTTP 201 with the created
    resource in `data`; all other successful endpoints return HTTP 200, with
    mutating endpoints returning the updated resource and computed reads
    returning the computed payload."

    Design: Corner/entities/association_create_applies_every_declared_bylaw_default
    """
    set_clock(api, CLOCK_EPOCH)

    response = api.create_association({"legal_name": HARBOR_POINT}, MANAGER_HEADERS)
    data = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert data["legal_name"] == HARBOR_POINT
    assert data["fiscal_year_start_month"] == 1

    assert data["master_policy_deductible_cents"] == 2_500_000
    assert data["association_deductible_cap_cents"] == 1_000_000
    assert data["late_fee_grace_days"] == 10
    assert data["late_fee_percent_bp"] == 1000
    assert data["late_fee_min_cents"] == 2500
    assert data["late_fee_cap_cents"] == 10000
    assert data["lien_threshold_cents"] == 180_000
    assert data["budget_veto_bp"] == 5000
    assert data["special_assessment_approval_bp"] == 6667
    assert data["board_quorum_seats"] == 3
    assert data["hearing_docket_capacity"] == 6
    assert data["element_window_buffer_hours"] == 24
    assert data["reserve_adequacy_threshold_bp"] == 7000
    assert data["reserve_contribution_min_bp"] == 1000
    assert data["fine_tier_1_cents"] == 5000
    assert data["fine_tier_2_cents"] == 10000
    assert data["fine_tier_3_daily_cents"] == 25000
    assert data["fine_cap_cents"] == 250_000
    assert data["repeat_lookback_days"] == 365
    assert data["cure_period_days"] == 14
    assert data["appeal_window_days"] == 30
    assert data["budget_notice_days"] == 30
    assert data["certificate_validity_days"] == 30
    assert data["resale_cert_fee_cents"] == 35_000


def test_registration_starts_every_derived_and_custodial_figure_at_zero(api):
    """The derived aggregate and the three cash pots are born at 0, version 1.

    PRD 2.10: "At registration the derived and custodial figures start from
    zero: `total_interest_bp` is 0, `operating_cash_cents` is 0,
    `reserve_balance_cents` is 0, `reserve_designated_cents` is 0,
    `restricted_sa_cash_cents` is 0, and `version` is 1."

    Design: Corner/entities/association_create_applies_every_declared_bylaw_default
    """
    set_clock(api, CLOCK_EPOCH)

    data = validate_success(
        api.create_association({"legal_name": HARBOR_POINT}, MANAGER_HEADERS),
        expected_status=201,
    )

    assert data["total_interest_bp"] == 0
    assert data["operating_cash_cents"] == 0
    assert data["reserve_balance_cents"] == 0
    assert data["reserve_designated_cents"] == 0
    assert data["restricted_sa_cash_cents"] == 0
    assert data["version"] == 1


# ======================================================================
# Unit birth posture
# ======================================================================
def test_new_unit_is_born_fiscally_blank_with_opposite_boolean_polarity(api):
    """A brand-new unit reads voting_eligible true AND transfer_blocked true.

    The two booleans start with opposite meanings -- eligible to vote, yet not
    closeable -- so an implementation seeding both from one shared "is clean"
    flag cannot satisfy the paragraph below.

    PRD 3.1: "A newly created unit is fiscally blank:
    `monthly_assessment_cents` is 0 and stays 0 until a budget adoption
    allocates to it, `balance_due_cents` is 0, `credit_balance_cents` is 0,
    `oldest_unpaid_age_days` is 0, `delinquency_stage` is `CURRENT`,
    `voting_eligible` is true, `lien_recorded_at` is null, and
    `transfer_blocked` is true."
    PRD 3.1: "That last field is derived rather than set: it is true exactly
    when the unit has no resale certificate in `ISSUED` status whose
    `expires_at` is still in the future, which is why a brand-new unit cannot
    be closed on."

    Design: Corner/entities/unit_create_computed_ledger_posture_input_ignored
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    owner_id = add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")

    data = validate_success(
        api.create_unit(
            ctx.association_id,
            {
                "current_owner_id": owner_id,
                "unit_label": "101",
                "interest_bp": 5000,
                "heated_sqft": 1200,
            },
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert data["balance_due_cents"] == 0
    assert data["credit_balance_cents"] == 0
    assert data["oldest_unpaid_age_days"] == 0
    assert data["delinquency_stage"] == "CURRENT"
    assert data["voting_eligible"] is True
    assert data["transfer_blocked"] is True
    assert data["monthly_assessment_cents"] == 0
    assert data["lien_recorded_at"] is None
    assert data["interest_bp"] == 5000
    assert data["heated_sqft"] == 1200
    assert data["version"] == 1


# ======================================================================
# Owner birth posture
# ======================================================================
def test_owner_created_without_board_fields_is_none_and_unseated(api):
    """Omitting the board fields yields board_role NONE and is_seated false.

    That is precisely the posture the actor-recognition rung rejects for a
    BoardDirector, so the default must not be promoted on creation.

    PRD 3.1: "Owners of record come next: each carries a `full_name` and an
    `email` used as the notice delivery address, and may optionally be given a
    board seat through `board_role`, whose permitted values are `NONE`,
    `DIRECTOR`, `PRESIDENT`, and `TREASURER` and which defaults to `NONE`,
    together with `is_seated`, a boolean defaulting to false that determines
    whether the seat counts toward board quorum."
    PRD 3.1: "An owner's `owned_unit_count` is never supplied by the client; it
    starts at 0 and the server maintains it as units are created and
    transferred."

    Design: Corner/entities/owner_create_defaults_board_role_none_and_unseated
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)

    data = validate_success(
        api.create_owner(
            ctx.association_id,
            {"full_name": "Owen Pratt", "email": "owen@example.test"},
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert data["board_role"] == "NONE"
    assert data["is_seated"] is False
    assert data["owned_unit_count"] == 0
    assert data["association_id"] == ctx.association_id
    assert data["version"] == 1


# ======================================================================
# Aggregates rolled forward by a unit insert
# ======================================================================
def test_unit_insert_rolls_both_aggregates_forward_once_per_unit(api):
    """Two 2500 bp units leave the association at 5000 bp and version 3.

    Not 10000 bp (a double-count) and not version 2 (one bump for the pair):
    each insert recomputes the sum and advances the parent version once.

    PRD 3.1: "Creating a unit has two secondary effects the caller does not
    request: the association's `total_interest_bp` is recomputed as the sum of
    `interest_bp` over all of its units and `Association.version` advances by
    1, and the named owner's `owned_unit_count` rises by 1 with
    `UnitOwner.version` advancing by 1."

    Design: Corner/entities/unit_creation_recomputes_association_total_interest_and_owned_count
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    owner_id = add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")

    assert ctx.association_version() == 1

    add_unit(ctx, "101", "o1", 2500, heated_sqft=1000)
    validate_success(
        api.create_unit(
            ctx.association_id,
            {
                "current_owner_id": owner_id,
                "unit_label": "102",
                "interest_bp": 2500,
                "heated_sqft": 1000,
            },
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    association = ctx.association()
    assert association["total_interest_bp"] == 5000
    assert association["version"] == 3

    owners, _ = validate_paginated(
        api.list_owners(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    owner_row = next(row for row in owners if row["id"] == owner_id)
    assert owner_row["owned_unit_count"] == 2

    _, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 2


# ======================================================================
# Unit label uniqueness
# ======================================================================
def test_unit_label_uniqueness_key_is_association_plus_label(api):
    """Label "101" is free in a second association but a repeat inside one is 409.

    PRD 3.1: "The label must be unique inside the association -- a collision is
    refused with `ERR_UNIT_LABEL_DUPLICATE` -- while `interest_bp` must fall
    between 1 and 10000 inclusive and `heated_sqft` must be at least 1."

    Design: Corner/entities/unit_label_uniqueness_is_scoped_per_association
    """
    ctx_a = create_association(api, legal_name=HARBOR_POINT)
    owner_a = add_owner(ctx_a, "oa", full_name="Owen Pratt", email="owen@example.test")
    add_unit(ctx_a, "101", "oa", 10000, heated_sqft=1000)

    ctx_b = create_association(api, legal_name=BAYVIEW_TERRACE)
    owner_b = add_owner(ctx_b, "ob", full_name="Beth Nolan", email="beth@example.test")

    # The same door number in a different association is a different key.
    twin = validate_success(
        api.create_unit(
            ctx_b.association_id,
            {
                "current_owner_id": owner_b,
                "unit_label": "101",
                "interest_bp": 10000,
                "heated_sqft": 900,
            },
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert twin["unit_label"] == "101"
    assert twin["association_id"] == ctx_b.association_id

    # A repeat inside the first association collides.
    validate_error(
        api.create_unit(
            ctx_a.association_id,
            {
                "current_owner_id": owner_a,
                "unit_label": "101",
                "interest_bp": 5000,
                "heated_sqft": 1000,
            },
            MANAGER_HEADERS,
        ),
        "ERR_UNIT_LABEL_DUPLICATE",
        expected_status=409,
    )

    _, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx_a.association_id})
    )
    assert meta["total_count"] == 1


# ======================================================================
# Unit field ranges and required fields
# ======================================================================
def test_interest_bp_one_past_the_ceiling_is_a_range_violation(api):
    """10001 bp is a 422 range violation, not an association-level sum error.

    PRD 2.9: "Field types, enum membership, and numeric ranges are valid --
    `interest_bp` between 1 and 10000 inclusive, `heated_sqft` at least 1,
    `installment_count` between 1 and 24 inclusive, `amount_cents` non-zero, a
    payment's `amount_cents` strictly greater than 0, `fiscal_year` between
    2020 and 2100 inclusive, `limit` between 1 and 100 inclusive, `offset` at
    least 0 -- otherwise `ERR_VALIDATION`."

    Design: Corner/entities/unit_create_interest_bp_over_ceiling_returns_err_validation
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    owner_id = add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")

    response = api.create_unit(
        ctx.association_id,
        {
            "current_owner_id": owner_id,
            "unit_label": "101",
            "interest_bp": 10001,
            "heated_sqft": 1000,
        },
        MANAGER_HEADERS,
    )
    validate_error(response, "ERR_VALIDATION", expected_status=422)
    assert response.json()["response_type"] == "error"

    assert ctx.association()["total_interest_bp"] == 0

    _, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0


def test_omitting_interest_bp_is_a_validation_failure_not_an_implicit_zero(api):
    """interest_bp is required input with no default, so omission is a 422.

    PRD 3.1: "Adding a unit requires a payload naming its owner of record
    through `current_owner_id`, a `unit_label` that is the door number, an
    `interest_bp` giving the unit's undivided common-element interest in basis
    points, and a `heated_sqft` giving its heated area."
    PRD 2.9: "Field types, enum membership, and numeric ranges are valid --
    `interest_bp` between 1 and 10000 inclusive, `heated_sqft` at least 1,
    `installment_count` between 1 and 24 inclusive, `amount_cents` non-zero, a
    payment's `amount_cents` strictly greater than 0, `fiscal_year` between
    2020 and 2100 inclusive, `limit` between 1 and 100 inclusive, `offset` at
    least 0 -- otherwise `ERR_VALIDATION`."

    Design: Corner/entities/unit_create_omitting_interest_bp_returns_err_validation
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    owner_id = add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")

    validate_error(
        api.create_unit(
            ctx.association_id,
            {
                "current_owner_id": owner_id,
                "unit_label": "101",
                "heated_sqft": 1000,
            },
            MANAGER_HEADERS,
        ),
        "ERR_VALIDATION",
        expected_status=422,
    )

    _, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0


# ======================================================================
# Identity: unresolvable path segments
# ======================================================================
def test_reading_an_unallocated_unit_id_is_a_not_found_error_envelope(api):
    """An unallocated UUID on the unit read path is 404, not 200 with null data.

    PRD 2.5: "An unknown `association_id` yields `ERR_ASSOCIATION_NOT_FOUND`;
    an unknown `unit_id` yields `ERR_UNIT_NOT_FOUND`; an unknown `budget_id`
    yields `ERR_BUDGET_NOT_FOUND`; an unknown `board_meeting_id` yields
    `ERR_MEETING_NOT_FOUND`; an unknown `special_assessment_id` yields
    `ERR_ASSESSMENT_NOT_FOUND`; an unknown `common_element_id` yields
    `ERR_ELEMENT_NOT_FOUND`; an unknown `vendor_contract_id` yields
    `ERR_CONTRACT_NOT_FOUND`; an unknown `work_order_id` yields
    `ERR_WORK_ORDER_NOT_FOUND`; an unknown `insurance_claim_id` yields
    `ERR_CLAIM_NOT_FOUND`; an unknown `violation_case_id` yields
    `ERR_CASE_NOT_FOUND`; an unknown `resale_certificate_id` yields
    `ERR_CERTIFICATE_NOT_FOUND`; and an unknown `ledger_entry_id` yields
    `ERR_LEDGER_ENTRY_NOT_FOUND`."
    PRD 2.5: "All of these carry HTTP 404."
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/get_unit_with_unknown_id_returns_unit_not_found
    """
    create_association(api, legal_name=HARBOR_POINT)

    response = api.get_unit(UNKNOWN_UNIT_ID, MANAGER_HEADERS)
    validate_error(response, "ERR_UNIT_NOT_FOUND", expected_status=404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}


def test_unknown_parent_in_the_path_beats_a_resolvable_body_reference(api):
    """The path association is resolved before the body FK, so it is a 404 on it.

    The body's `current_owner_id` names a real owner, and the association
    segment names none -- the left-to-right path rung fires first, so the
    identifier is ERR_ASSOCIATION_NOT_FOUND.

    PRD 2.5: "Path parameters are resolved strictly left to right, and the
    first unresolvable segment determines the error."
    PRD 2.9: "Path resources exist, resolved left to right, on every endpoint
    that has path parameters -- otherwise the matching not-found identifier
    from §2.5."
    PRD 2.9: "Body-supplied foreign keys exist, on every write endpoint that
    accepts them -- otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND`."

    Design: Corner/entities/unit_create_under_unknown_association_returns_association_not_found
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    owner_id = add_owner(ctx, "oa", full_name="Owen Pratt", email="owen@example.test")

    validate_error(
        api.create_unit(
            UNKNOWN_ASSOCIATION_ID,
            {
                "current_owner_id": owner_id,
                "unit_label": "101",
                "interest_bp": 5000,
                "heated_sqft": 1000,
            },
            MANAGER_HEADERS,
        ),
        "ERR_ASSOCIATION_NOT_FOUND",
        expected_status=404,
    )

    association = ctx.association()
    assert association["total_interest_bp"] == 0
    assert association["version"] == 1


# ======================================================================
# Listing windows
# ======================================================================
def test_last_page_reports_the_unwindowed_total_and_no_more_rows(api):
    """With four units, limit 2 offset 2 is the last page: total 4, has_more false.

    The same window size at offset 0 reports has_more true, so has_more cannot
    be derived from the returned row count alone.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may
    be no smaller than 1, and may be no larger than 100."
    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset`
    echoing the effective values used, `total_count` giving the number of rows
    matching the filter before the page window was applied, and `has_more` set
    true when rows remain beyond the current window."

    Design: Corner/entities/units_list_pagination_reports_total_count_and_has_more
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    for label in ("101", "102", "103", "104"):
        add_unit(ctx, label, "o1", 2500, heated_sqft=1000)

    response = api.list_units(
        MANAGER_HEADERS,
        params={"association_id": ctx.association_id, "limit": 2, "offset": 2},
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is False
    assert len(rows) == 2

    first_rows, first_meta = validate_paginated(
        api.list_units(
            MANAGER_HEADERS,
            params={"association_id": ctx.association_id, "limit": 2, "offset": 0},
        )
    )
    assert first_meta["total_count"] == 4
    assert first_meta["has_more"] is True
    assert len(first_rows) == 2


def test_limit_above_one_hundred_is_rejected_as_a_range_violation(api):
    """limit 101 is one past the ceiling and is refused with a 422.

    PRD 2.3: "A `limit` outside the range of 1 through 100 inclusive is a range
    violation and is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/units_list_pagination_reports_total_count_and_has_more
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    for label in ("101", "102", "103", "104"):
        add_unit(ctx, label, "o1", 2500, heated_sqft=1000)

    validate_error(
        api.list_units(
            MANAGER_HEADERS,
            params={"association_id": ctx.association_id, "limit": 101},
        ),
        "ERR_VALIDATION",
        expected_status=422,
    )


# ======================================================================
# Ledger immutability
# ======================================================================
def test_reversal_appends_a_new_paired_row_and_leaves_the_original_intact(api):
    """The only mutation of a posted row is its status flip to REVERSED.

    The compensating row is a brand-new id carrying the exact negation; the
    original's `entry_type`, `amount_cents` and `due_on` are unchanged.

    PRD 3.1: "A successful reversal creates a `REVERSAL` row whose
    `reverses_entry_id` names the original and whose `amount_cents` is the
    exact negation of the original's, flips the original's `status` to
    `REVERSED`, recomputes the unit's `balance_due_cents`, re-derives its
    `delinquency_stage`, and advances `Unit.version` by 1."
    PRD 3.1: "`balance_due_cents` is the signed sum of `amount_cents` over
    *every* ledger row of the unit, regardless of `status` -- a reversed pair
    nets to zero, so nothing is double counted."
    PRD 3.1: "Rule 1: if `balance_due_cents` is less than or equal to 0, the
    posture is `CURRENT`."

    Design: Corner/entities/ledger_entry_is_immutable_and_reversal_creates_a_paired_row
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)

    original = post_charge(
        ctx,
        "101",
        entry_type="COLLECTION_COST",
        amount_cents=450_000,
        due_on="2026-08-10T00:00:00Z",
        effective_period="2026-08",
        memo="lien search fee",
    )

    reversal = validate_success(
        api.reverse_ledger_entry(
            original["id"], ctx.treasurer(), payload={"memo": "billed in error"}
        ),
        expected_status=201,
    )

    assert reversal["entry_type"] == "REVERSAL"
    assert reversal["amount_cents"] == -450_000
    assert reversal["reverses_entry_id"] == original["id"]
    assert reversal["status"] == "POSTED"
    assert reversal["id"] != original["id"]

    rows, meta = validate_paginated(
        api.list_ledger_entries(MANAGER_HEADERS, params={"unit_id": ctx.units["101"]})
    )
    assert meta["total_count"] == 2

    stored = next(row for row in rows if row["id"] == original["id"])
    assert stored["entry_type"] == "COLLECTION_COST"
    assert stored["amount_cents"] == 450_000
    assert_instant_equals(stored["due_on"], "2026-08-10T00:00:00Z")
    assert stored["status"] == "REVERSED"

    unit = ctx.unit("101")
    assert unit["balance_due_cents"] == 0
    assert unit["delinquency_stage"] == "CURRENT"


# ======================================================================
# One vote register, two shapes
# ======================================================================
def test_one_vote_register_derives_each_shape_from_its_discriminator(api):
    """An owner ballot weighs interest_bp; a board vote weighs 0.

    The polymorphic `subject_id` resolves against the same budget row for both
    shapes; only the discriminator (`unit_id` versus `meeting_id`) differs.

    PRD 3.3: "From those the server derives `voter_kind`, which is
    `BOARD_DIRECTOR` when `meeting_id` is set and `UNIT_OWNER` when `unit_id`
    is set; `weight_bp`, which is the unit's `interest_bp` at cast time for
    owner ballots and 0 for board votes; and `counted`, initially the unit's
    `voting_eligible` for owner ballots and true for board votes."

    Design: Corner/entities/vote_polymorphic_subject_and_derived_voter_kind_per_shape
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    owner_id = add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    director_id = add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)
    meeting_id = schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION"],
        "2026-09-15T10:00:00Z",
        "2026-09-15T12:00:00Z",
    )
    budget = draft_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
        ratification_meeting_id=meeting_id,
    )

    ballot = validate_success(
        api.cast_vote(
            {
                "association_id": ctx.association_id,
                "subject_type": "BUDGET",
                "subject_id": budget["id"],
                "choice": "NO",
                "voter_owner_id": owner_id,
                "unit_id": ctx.units["101"],
            },
            ctx.owner("o1"),
        ),
        expected_status=201,
    )
    assert ballot["voter_kind"] == "UNIT_OWNER"
    assert ballot["weight_bp"] == 10000
    assert ballot["counted"] is True
    assert ballot["subject_type"] == "BUDGET"
    assert ballot["subject_id"] == budget["id"]
    assert ballot["meeting_id"] is None

    board_vote = validate_success(
        api.cast_vote(
            {
                "association_id": ctx.association_id,
                "subject_type": "BUDGET",
                "subject_id": budget["id"],
                "choice": "YES",
                "voter_owner_id": director_id,
                "meeting_id": meeting_id,
            },
            ctx.director("d1"),
        ),
        expected_status=201,
    )
    assert board_vote["voter_kind"] == "BOARD_DIRECTOR"
    assert board_vote["weight_bp"] == 0
    assert board_vote["counted"] is True
    assert board_vote["unit_id"] is None

    _, meta = validate_paginated(
        api.list_votes(MANAGER_HEADERS, params={"subject_id": budget["id"]})
    )
    assert meta["total_count"] == 2


# ======================================================================
# Violation case birth posture
# ======================================================================
def test_violation_case_is_born_with_continuing_days_one_and_zero_counters(api):
    """continuing_days defaults to 1 while hearing_round and fine_tier are 0.

    The daily tier-3 rate multiplies `continuing_days`, so a 0 default would
    zero out that fine; `hearing_round` 0 is what marks a never-docketed case.

    PRD 3.8: "A `CommunityManager` or `BoardDirector` opens a
    rules-enforcement case by supplying `association_id`, the cited `unit_id`,
    the `rule_code` on which repeat-tier counting keys, the
    `reported_by_owner_id` of the director who reported the violation, and
    optionally `continuing_days`, the number of days the violation persisted,
    which must be at least 1 and defaults to 1."
    PRD 3.8: "The case is born with `status` `OPEN`, `hearing_round` 0,
    `fine_tier` 0, and `fine_amount_cents` 0; `prior_case_id`,
    `decision_owner_id`, `hearing_meeting_id`, `notice_sent_at`,
    `cure_deadline_at`, `hearing_slot_start`, `fine_entry_id`, and
    `appeal_deadline_at` are all null."

    Design: Corner/entities/violation_case_create_defaults_continuing_days_and_zero_counters
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    director_id = add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10000, heated_sqft=1000)

    data = validate_success(
        api.create_violation_case(
            violation_case_payload(
                ctx.association_id,
                ctx.units["101"],
                director_id,
                rule_code="R-14-PETS",
            ),
            MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert data["status"] == "OPEN"
    assert data["continuing_days"] == 1
    assert data["hearing_round"] == 0
    assert data["fine_tier"] == 0
    assert data["fine_amount_cents"] == 0
    assert data["notice_sent_at"] is None
    assert data["cure_deadline_at"] is None
    assert data["prior_case_id"] is None
    assert data["decision_owner_id"] is None
    assert data["fine_entry_id"] is None
    assert data["hearing_meeting_id"] is None
    assert data["hearing_slot_start"] is None
    assert data["appeal_deadline_at"] is None
    assert data["version"] == 1
