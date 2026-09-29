"""Which complaint a wrong request is entitled to hear.

One volume that sits exactly on its tier's floor and one unit below it, a single
request wrong three ways whose answer changes as each layer is repaired, a
mapping refused because a different row was delisted, a price window that is
well formed and still outside its contract's term, one optional field that is
mandatory in one branch and forbidden in the other, a scope check that must run
before the body's foreign keys are resolved, and a remittance ceiling set by the
aggregate the period actually earned.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COLLECTION_EXCEEDS_ACCRUAL,
    ERR_COMMITTED_VOLUME_BELOW_TIER,
    ERR_CONTRACT_ITEM_NOT_ACTIVE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE,
    ERR_EFFECTIVE_WINDOW_INVALID,
    ERR_INVALID_DISTRIBUTION_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_ITEM_NOT_IN_MASTER,
    ERR_MEMBER_SCOPE_VIOLATION,
    ERR_PERIOD_OUTSIDE_CONTRACT_TERM,
    ERR_REQUESTED_PRICE_NOT_ALLOWED,
    ERR_REQUESTED_PRICE_REQUIRED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_TIER_CODE_UNKNOWN,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import (
    FLAT_TIER_LADDER,
    FULL_TIER_LADDER,
    HOLDBACK_FLAT,
    ROLE_COMPLIANCE_ANALYST,
    TIER_0,
    TIER_1,
)
from test_helpers.fixtures import (
    activate_contract,
    build_priced_setup,
    countersign_commitment,
    create_active_contract,
    create_active_tier_activation,
    create_approved_cross_reference,
    create_commitment,
    create_distribution,
    create_item,
    create_member,
    read_contract,
    read_distribution,
    read_item,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    anonymous_headers,
    compliance_analyst_headers,
    contract_manager_headers,
    finance_administrator_headers,
    make_member_materials_manager_headers,
)

# A syntactically valid identifier that names no row in the portfolio.
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"


@pytest.fixture
def full_ladder_and_two_members(api):
    """An ACTIVE contract whose TIER_1 rung asks for 2000 units, and two members."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-FLR",
        tiers=[dict(row) for row in FULL_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    first = create_member(api, member_code="M-1")
    second = create_member(api, member_code="M-2", name="Lakeside Surgical Center")
    return {"contract": contract, "first": first, "second": second}


def _elect(api, member, contract_id, **overrides):
    payload = f.commitment_payload(member["id"], contract_id, **overrides)
    return api.create_commitment(
        payload, headers=make_member_materials_manager_headers(member["id"])
    )


class TestTheVolumeFloorIsInclusive:
    """Two thousand units buys the two-thousand rung; 1999 buys nothing."""

    def test_exactly_the_tier_minimum_elects(self, api, full_ladder_and_two_members):
        """PRD §2.9: "**Committed volume floor** — a commitment's `committed_volume_units` is at
        least the elected tier's minimum committed volume; otherwise
        `ERR_COMMITTED_VOLUME_BELOW_TIER` (409)."
        PRD §3.4: "A newly elected commitment is born with `election_status` `ELECTED`,
        `lop_status` `NOT_ISSUED`, `signer_name` null, `current_tier_code` null,
        `requalification_round` zero, `last_final_compliance_pct` null, all three year-to-date
        ledgers — `ytd_on_contract_spend_cents`, `ytd_total_category_spend_cents` and
        `ytd_measured_volume_units` — at zero, `ytd_leakage_pct` at 0.00, and `leakage_flag`
        false."

        Design: Corner/validations/election_at_the_exact_tier_volume_floor_is_accepted
        """
        setup = full_ladder_and_two_members

        elected = validate_success(
            _elect(
                api,
                setup["first"],
                setup["contract"]["id"],
                elected_tier_code=TIER_1,
                committed_volume_units=2000,
            ),
            201,
        )

        assert elected["election_status"] == "ELECTED"
        assert elected["lop_status"] == "NOT_ISSUED"
        assert elected["committed_volume_units"] == 2000
        assert elected["elected_tier_code"] == TIER_1
        assert elected["signer_name"] is None
        assert elected["requalification_round"] == 0
        assert elected["last_final_compliance_pct"] is None
        assert elected["leakage_flag"] is False

    def test_one_unit_below_the_minimum_is_refused(self, api, full_ladder_and_two_members):
        """PRD §3.4: "Its preconditions are evaluated in this order: the member must exist and be
        `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`; the acting `X-User-ID` must equal the body's
        `member_id`, else `ERR_MEMBER_SCOPE_VIOLATION`; the contract must exist and be `ACTIVE`,
        else `ERR_CONTRACT_NOT_ACTIVE`; the `elected_tier_code` must name an entry of that
        contract's tier ladder, else `ERR_TIER_CODE_UNKNOWN`; no commitment for the same member
        and contract may already sit in `ELECTED`, `ACTIVE` or `REQUAL_REVIEW` — a `TERMINATED`
        predecessor does not block a fresh election — else `ERR_DUPLICATE_COMMITMENT`; the
        `effective_from` date must fall inside the contract's inclusive term, else
        `ERR_PERIOD_OUTSIDE_CONTRACT_TERM`; and `committed_volume_units`, which must itself be
        strictly greater than zero, must be at least the elected tier's
        `min_committed_volume_units`, else `ERR_COMMITTED_VOLUME_BELOW_TIER`."

        Design: Corner/validations/election_at_the_exact_tier_volume_floor_is_accepted
        """
        setup = full_ladder_and_two_members

        response = _elect(
            api,
            setup["second"],
            setup["contract"]["id"],
            elected_tier_code=TIER_1,
            committed_volume_units=1999,
        )

        validate_error(response, ERR_COMMITTED_VOLUME_BELOW_TIER, 409)

    def test_electing_puts_no_tier_in_force_and_counts_nobody(
        self, api, full_ladder_and_two_members
    ):
        """PRD §3.4: "It sets `current_tier_code` to the commitment's `elected_tier_code`, which
        is the first moment the member has a tier actually in force rather than merely elected."
        PRD §3.4: "Creation also reaches the parent contract: `active_commitment_count` is
        recomputed and the contract's `version` increments by one."
        PRD §3.4: "Because an `ELECTED` commitment is not yet one of the counted states, the
        counter's value does not move, but the contract row is touched all the same."

        Design: Corner/validations/election_at_the_exact_tier_volume_floor_is_accepted
        """
        setup = full_ladder_and_two_members
        contract_id = setup["contract"]["id"]

        elected = validate_success(
            _elect(
                api,
                setup["first"],
                contract_id,
                elected_tier_code=TIER_1,
                committed_volume_units=2000,
            ),
            201,
        )
        validate_error(
            _elect(
                api,
                setup["second"],
                contract_id,
                elected_tier_code=TIER_1,
                committed_volume_units=1999,
            ),
            ERR_COMMITTED_VOLUME_BELOW_TIER,
            409,
        )

        assert elected["current_tier_code"] is None
        after = read_contract(api, contract_id)
        assert after["active_commitment_count"] == 0
        assert after["version"] == setup["contract"]["version"] + 1


class TestTheTopOfTheLadderIsWalkedStrictlyDownwards:
    """The same unknown contract answers 401, then 403, then 404, as each layer is fixed."""

    def test_the_missing_identity_header_outranks_everything(self, api):
        """PRD §2.9: "When a request violates more than one rule, exactly one error is returned:
        the one belonging to the **lowest-numbered rung** below."
        PRD §2.9: "**Authentication** — `X-User-ID` present and non-empty on every request except
        `POST /gpo/_clock/set_current_utc`; otherwise `ERR_UNAUTHENTICATED` (401)."
        PRD §2.1: "A request whose `X-User-ID` header is missing or empty is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401); the single exception is the logical-clock endpoint,
        which is a test-driving capability and requires no user identity."

        Design: Corner/validations/unauthenticated_beats_role_which_beats_not_found_returns_401
        """
        response = api.activate_contract(
            UNKNOWN_ID, {}, headers=anonymous_headers(ROLE_COMPLIANCE_ANALYST)
        )

        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_the_wrong_role_is_answered_before_the_lookup(self, api):
        """PRD §2.9: "**Role admission** — `X-User-Role` present, one of the six declared roles,
        and permitted for the requested operation; otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §2.1: "A request whose `X-User-Role` header is missing, is not one of the six role
        names above, or names a role that the requested operation does not admit is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/validations/unauthenticated_beats_role_which_beats_not_found_returns_401
        """
        response = api.activate_contract(UNKNOWN_ID, {}, headers=compliance_analyst_headers())

        validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

    def test_existence_is_tested_only_once_authorisation_passes(self, api):
        """PRD §2.9: "**Path existence** — every identifier in the path resolves, checked left to
        right in the order `contract_id`, `contract_item_id`, `member_id`, `commitment_id`,
        `xref_id`, `activation_id`, `file_id`, `measurement_id`, `distribution_id`, `review_id`,
        `purchase_line_id`; otherwise the matching 404 from §2.8."
        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the
        first violation, so a later rung's error can never mask an earlier rung's error."

        Design: Corner/validations/unauthenticated_beats_role_which_beats_not_found_returns_401
        """
        unauthenticated = api.activate_contract(
            UNKNOWN_ID, {}, headers=anonymous_headers(ROLE_COMPLIANCE_ANALYST)
        )
        unadmitted = api.activate_contract(UNKNOWN_ID, {}, headers=compliance_analyst_headers())

        permitted = api.activate_contract(UNKNOWN_ID, {}, headers=contract_manager_headers())

        assert unauthenticated.status_code == 401
        assert unadmitted.status_code == 403
        validate_error(permitted, ERR_CONTRACT_NOT_FOUND, 404)


@pytest.fixture
def one_active_and_one_delisted_item(api):
    """Two catalog lines on one contract, the second one delisted, and a member."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-DLS",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    live = create_item(api, contract["id"])
    doomed = create_item(
        api,
        contract["id"],
        vendor_item_number="V-2",
        item_description="Mesh graft 10x10",
        base_price_cents=5000,
        floor_price_cents=4000,
    )
    delisted = validate_success(
        api.delist_contract_item(
            doomed["id"],
            f.reason_payload("supplier discontinued the SKU"),
            headers=contract_manager_headers(),
        ),
        200,
    )
    member = create_member(
        api,
        member_code="M-1",
        item_master=[
            f.item_master_row("MI-1"),
            f.item_master_row("MI-2", description="Mesh graft"),
        ],
    )
    return {
        "contract": contract,
        "live": live,
        "doomed": doomed,
        "delisted": delisted,
        "member": member,
        "member_headers": make_member_materials_manager_headers(member["id"]),
    }


class TestADelistedLineIsPresentButUnusable:
    """Delisting is not a delete, so the refusal is a state complaint and not a 404."""

    def test_the_delisted_line_still_resolves(self, api, one_active_and_one_delisted_item):
        """PRD §3.1: "Delisting a catalog line sets its `status` to `DELISTED`, optionally records
        a `reason`, and increments its `version` by one."
        PRD §3.1: "Activations already in `ACTIVE` status are untouched, and cross-references
        already `APPROVED` against it keep working."

        Design: Corner/validations/cross_reference_against_a_delisted_item_is_rejected
        """
        setup = one_active_and_one_delisted_item

        assert setup["delisted"]["status"] == "DELISTED"
        a.assert_version_bump(setup["delisted"], setup["doomed"]["version"])
        reread = read_item(api, setup["doomed"]["id"])
        assert reread["status"] == "DELISTED"
        assert reread["vendor_item_number"] == "V-2"

    def test_a_mapping_onto_the_delisted_line_is_refused(
        self, api, one_active_and_one_delisted_item
    ):
        """PRD §2.9: "Two sibling state errors sit on this rung: `ERR_MEMBER_NOT_ACTIVE` (409)
        when a `SUSPENDED` member is named by a commitment election or a distributor file, and
        `ERR_CONTRACT_ITEM_NOT_ACTIVE` (409) when a `DELISTED` catalog item is named by a
        cross-reference proposal."
        PRD §3.1: "A delisted line can no longer be named by a new cross-reference proposal —
        that attempt returns `ERR_CONTRACT_ITEM_NOT_ACTIVE` — and it can no longer be named by a
        new price activation."

        Design: Corner/validations/cross_reference_against_a_delisted_item_is_rejected
        """
        setup = one_active_and_one_delisted_item

        response = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"], setup["doomed"]["id"], member_item_number="MI-2"
            ),
            headers=setup["member_headers"],
        )

        validate_error(response, ERR_CONTRACT_ITEM_NOT_ACTIVE, 409)

    def test_the_identical_shape_maps_onto_the_live_line(
        self, api, one_active_and_one_delisted_item
    ):
        """PRD §3.5: "A proposal's preconditions run in this order: the member must exist and the
        acting `X-User-ID` must equal the body's `member_id`, else `ERR_MEMBER_SCOPE_VIOLATION`;
        the parent contract must be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`; the catalog item
        must exist and be `ACTIVE` rather than `DELISTED`, else `ERR_CONTRACT_ITEM_NOT_ACTIVE`;
        the `member_item_number` must appear among the current `item_master` entries of that
        member, else `ERR_MEMBER_ITEM_NOT_IN_MASTER`; and no cross-reference already in
        `APPROVED` status may exist for the same member and catalog item, nor for the same member
        and member item number, else `ERR_DUPLICATE_XREF`."
        PRD §3.5: "The mapping is created in `PROPOSED` status."

        Design: Corner/validations/cross_reference_against_a_delisted_item_is_rejected
        """
        setup = one_active_and_one_delisted_item

        proposed = validate_success(
            api.create_cross_reference(
                f.cross_reference_payload(
                    setup["member"]["id"], setup["live"]["id"], member_item_number="MI-1"
                ),
                headers=setup["member_headers"],
            ),
            201,
        )

        assert proposed["status"] == "PROPOSED"
        assert proposed["contract_item_id"] == setup["live"]["id"]
        assert proposed["member_item_number"] == "MI-1"
        assert proposed["approved_by_user_id"] is None

    def test_the_item_master_check_runs_after_the_item_state_check(
        self, api, one_active_and_one_delisted_item
    ):
        """PRD §2.9: "**Referential coherence** — the referenced rows belong together: a catalog
        item named by an activation belongs to the commitment's contract
        (`ERR_ITEM_CONTRACT_MISMATCH`), a member item number named by a cross-reference exists in
        that member's item master (`ERR_MEMBER_ITEM_NOT_IN_MASTER`), and a price may only be
        activated once an `APPROVED` cross-reference links the member to the item
        (`ERR_XREF_NOT_APPROVED`); all 409."

        Design: Corner/validations/cross_reference_against_a_delisted_item_is_rejected
        """
        setup = one_active_and_one_delisted_item

        unknown_number = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"],
                setup["live"]["id"],
                member_item_number="MI-9",
                match_type="MANUAL",
            ),
            headers=setup["member_headers"],
        )
        both_wrong = api.create_cross_reference(
            f.cross_reference_payload(
                setup["member"]["id"],
                setup["doomed"]["id"],
                member_item_number="MI-9",
                match_type="MANUAL",
            ),
            headers=setup["member_headers"],
        )

        validate_error(unknown_number, ERR_MEMBER_ITEM_NOT_IN_MASTER, 409)
        validate_error(both_wrong, ERR_CONTRACT_ITEM_NOT_ACTIVE, 409)


@pytest.fixture
def priceable_member_on_a_one_year_term(api):
    """A countersigned member with an approved mapping and no activation yet."""
    return build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-TRM",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        with_activation=False,
    )


def _request_activation(api, setup, headers=None, **overrides):
    payload = f.price_activation_payload(
        setup["commitment"]["id"], setup["item"]["id"], **overrides
    )
    return api.create_price_activation(payload, headers=headers or contract_manager_headers())


def _activations_of(api, commitment_id, **filters):
    params = dict(filters)
    params["commitment_id"] = commitment_id
    params.setdefault("limit", 10)
    params.setdefault("offset", 0)
    return validate_paginated(
        api.list_price_activations(params, headers=contract_manager_headers())
    )


class TestAPriceWindowMustFitInsideItsContractTerm:
    """Well formed on its own and still illegal, because the term ends on the last of December."""

    def test_a_window_running_past_the_term_is_refused(
        self, api, priceable_member_on_a_one_year_term
    ):
        """PRD §2.9: "**Containment in the contract term** — a price activation window lies inside
        its contract's own effective term; otherwise `ERR_PERIOD_OUTSIDE_CONTRACT_TERM` (409)."
        PRD §3.6: "The window must be oriented — `effective_to` on or after `effective_from`, else
        `ERR_EFFECTIVE_WINDOW_INVALID` — and must sit wholly inside the contract's inclusive term,
        else `ERR_PERIOD_OUTSIDE_CONTRACT_TERM`."

        Design: Corner/validations/activation_window_outside_the_contract_term_is_rejected
        """
        setup = priceable_member_on_a_one_year_term
        a.assert_date(setup["contract"]["effective_to"], "2026-12-31")

        response = _request_activation(
            api, setup, effective_from="2026-12-01", effective_to="2027-01-15"
        )

        validate_error(response, ERR_PERIOD_OUTSIDE_CONTRACT_TERM, 409)

    def test_the_last_day_of_the_term_is_inside_it(self, api, priceable_member_on_a_one_year_term):
        """PRD §2.10: "**Containment** always follows the convention of the thing being contained."
        PRD §2.10: "A price activation is inside its contract's term only when both of its
        inclusive endpoints fall inside the contract's inclusive term."

        Design: Corner/validations/activation_window_outside_the_contract_term_is_rejected
        """
        setup = priceable_member_on_a_one_year_term

        created = validate_success(
            _request_activation(
                api, setup, effective_from="2026-12-01", effective_to="2026-12-31"
            ),
            201,
        )

        assert created["status"] == "DRAFT"
        a.assert_date(created["effective_from"], "2026-12-01")
        a.assert_date(created["effective_to"], "2026-12-31")

    def test_a_reversed_window_is_caught_before_the_overlap(
        self, api, priceable_member_on_a_one_year_term
    ):
        """PRD §2.9: "**Window orientation** — a price activation's `effective_to` is on or after
        its `effective_from`, and a distributor file's, measurement's, distribution's or leakage
        query's `period_end` is strictly after its `period_start`; otherwise
        `ERR_EFFECTIVE_WINDOW_INVALID` (409)."
        PRD §2.9: "**Activation overlap** — no existing price activation for the same commitment,
        catalog item and activation type, in status `DRAFT`, `ENDORSED`, `APPROVED` or `ACTIVE`,
        has a fully closed window colliding with the new one; sharing a single endpoint date is a
        collision."

        Design: Corner/validations/activation_window_outside_the_contract_term_is_rejected
        """
        setup = priceable_member_on_a_one_year_term
        validate_success(
            _request_activation(
                api, setup, effective_from="2026-12-01", effective_to="2026-12-31"
            ),
            201,
        )

        response = _request_activation(
            api, setup, effective_from="2026-12-31", effective_to="2026-12-01"
        )

        validate_error(response, ERR_EFFECTIVE_WINDOW_INVALID, 409)

    def test_neither_rejected_request_leaves_a_row_behind(
        self, api, priceable_member_on_a_one_year_term
    ):
        """PRD §3.6: "Because those replacements are created without a client request, the
        activation list — filterable by `commitment_id`, `contract_item_id`, `status`,
        `activation_type`, `origin`, and by either end of a supersede link through
        `superseded_by_activation_id` or `replaces_activation_id` — is the only channel through
        which a client can find them."

        Design: Corner/validations/activation_window_outside_the_contract_term_is_rejected
        """
        setup = priceable_member_on_a_one_year_term
        _request_activation(api, setup, effective_from="2026-12-01", effective_to="2027-01-15")
        accepted = validate_success(
            _request_activation(
                api, setup, effective_from="2026-12-01", effective_to="2026-12-31"
            ),
            201,
        )
        _request_activation(api, setup, effective_from="2026-12-31", effective_to="2026-12-01")

        rows, meta = _activations_of(api, setup["commitment"]["id"])

        assert meta["total_count"] == 1
        a.assert_exact_ids(rows, [accepted["id"]])
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0


@pytest.fixture
def two_tracks_over_one_window(api):
    """A countersigned TIER_0 member on a 10000-cent item with an 8200-cent floor."""
    return build_priced_setup(
        api,
        contract_overrides={
            "contract_code": "C-CND",
            "tiers": [dict(row) for row in FLAT_TIER_LADDER],
            "holdback_tiers": [dict(row) for row in HOLDBACK_FLAT],
        },
        with_activation=False,
    )


class TestTheRequestedPriceIsMandatoryOnOneTrackAndForbiddenOnTheOther:
    """One optional field, two opposite rules, decided by `activation_type` alone."""

    def test_a_local_exception_without_a_price_is_refused(self, api, two_tracks_over_one_window):
        """PRD §2.9: "**Price-shape coherence** — `requested_price_cents` is supplied for a
        `LOCAL_EXCEPTION` activation and omitted for a `TIER_PRICE` activation; the errors are
        `ERR_REQUESTED_PRICE_REQUIRED` and `ERR_REQUESTED_PRICE_NOT_ALLOWED`, both 409."
        PRD §3.6: "A `LOCAL_EXCEPTION` is a member-requested custom price and may only be
        requested by a `MemberMaterialsManager` whose `X-User-ID` equals the commitment's
        `member_id`."

        Design: Corner/validations/requested_price_shape_is_conditional_on_activation_type
        """
        setup = two_tracks_over_one_window

        response = _request_activation(
            api,
            setup,
            headers=setup["member_headers"],
            activation_type="LOCAL_EXCEPTION",
            effective_from="2026-08-01",
            effective_to="2026-08-31",
        )

        validate_error(response, ERR_REQUESTED_PRICE_REQUIRED, 409)

    def test_a_tier_price_carrying_a_price_is_refused_not_stripped(
        self, api, two_tracks_over_one_window
    ):
        """PRD §3.6: "A `LOCAL_EXCEPTION` additionally carries `requested_price_cents`, a positive
        integer naming the price the member is asking for; a `TIER_PRICE` must omit it."
        PRD §3.6: "Supplying it on a tier price returns `ERR_REQUESTED_PRICE_NOT_ALLOWED`, and
        omitting it on a local exception returns `ERR_REQUESTED_PRICE_REQUIRED`."

        Design: Corner/validations/requested_price_shape_is_conditional_on_activation_type
        """
        setup = two_tracks_over_one_window

        response = _request_activation(
            api,
            setup,
            activation_type="TIER_PRICE",
            effective_from="2026-08-01",
            effective_to="2026-08-31",
            requested_price_cents=9600,
        )

        validate_error(response, ERR_REQUESTED_PRICE_NOT_ALLOWED, 409)
        rows, meta = _activations_of(api, setup["commitment"]["id"])
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_accepted_local_exception_is_priced_at_the_moment_it_is_drafted(
        self, api, two_tracks_over_one_window
    ):
        """PRD §3.6: "An accepted request creates the activation in `DRAFT` status with `origin`
        `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."
        PRD §3.6: "When `activation_type` is `LOCAL_EXCEPTION`, the candidate price is the
        **lesser** of the activation's `requested_price_cents` and the tier price from step 2 — a
        local exception may only ever move *down* from the tier price, and asking for more than the
        tier price is silently ceilinged rather than rejected."

        Design: Corner/validations/requested_price_shape_is_conditional_on_activation_type
        """
        setup = two_tracks_over_one_window

        created = validate_success(
            _request_activation(
                api,
                setup,
                headers=setup["member_headers"],
                activation_type="LOCAL_EXCEPTION",
                effective_from="2026-08-01",
                effective_to="2026-08-31",
                requested_price_cents=9600,
            ),
            201,
        )

        assert created["status"] == "DRAFT"
        assert created["requested_price_cents"] == 9600
        assert created["tier_code_at_activation"] == TIER_0
        assert created["origin"] == "REQUEST"
        a.assert_cents(created["computed_price_cents"], 9600)
        assert created["price_clamped"] is False
        assert created["endorsed_by_user_id"] is None
        assert created["approved_by_user_id"] is None

    def test_the_two_tracks_are_separate_ladders_over_the_same_days(
        self, api, two_tracks_over_one_window
    ):
        """PRD §3.6: "No other activation for the **same commitment, same catalog item and same
        activation type** whose status is `DRAFT`, `ENDORSED`, `APPROVED` or `ACTIVE` may have a
        closed-interval collision with the new window; because both endpoints are inclusive, two
        windows that share even a single day collide, and the rejection is
        `ERR_ACTIVATION_PERIOD_OVERLAP`."
        PRD §3.6: "When `activation_type` is `TIER_PRICE`, the candidate price is simply the tier
        price."

        Design: Corner/validations/requested_price_shape_is_conditional_on_activation_type
        """
        setup = two_tracks_over_one_window
        exception = validate_success(
            _request_activation(
                api,
                setup,
                headers=setup["member_headers"],
                activation_type="LOCAL_EXCEPTION",
                effective_from="2026-08-01",
                effective_to="2026-08-31",
                requested_price_cents=9600,
            ),
            201,
        )

        tier_price = validate_success(
            _request_activation(
                api,
                setup,
                activation_type="TIER_PRICE",
                effective_from="2026-08-01",
                effective_to="2026-08-31",
            ),
            201,
        )

        assert tier_price["status"] == "DRAFT"
        assert tier_price["requested_price_cents"] is None
        a.assert_cents(tier_price["computed_price_cents"], 10000)
        rows, meta = _activations_of(api, setup["commitment"]["id"])
        assert meta["total_count"] == 2
        a.assert_exact_ids(rows, [exception["id"], tier_price["id"]])


@pytest.fixture
def one_rung_contract_and_two_members(api):
    """A contract whose ladder holds TIER_0 only, and two members who could elect it."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-SCP",
        tiers=[dict(row) for row in FLAT_TIER_LADDER],
        holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
    )
    owner = create_member(api, member_code="M-1")
    stranger = create_member(api, member_code="M-2", name="Lakeside Surgical Center")
    return {"contract": contract, "owner": owner, "stranger": stranger}


def _elect_as(api, acting_member, body_member_id, contract_id, **overrides):
    payload = f.commitment_payload(body_member_id, contract_id, **overrides)
    return api.create_commitment(
        payload, headers=make_member_materials_manager_headers(acting_member["id"])
    )


def _commitments_of(api, member_id, contract_id):
    params = f.page(10, 0, member_id=member_id, contract_id=contract_id)
    return validate_paginated(api.list_commitments(params, headers=contract_manager_headers()))


class TestScopeIsAnsweredBeforeTheBodyIsResolved:
    """One body wrong three ways; each repair reveals exactly the next rung down."""

    def test_another_members_election_is_refused_on_scope(
        self, api, one_rung_contract_and_two_members
    ):
        """PRD §2.9: "**Member scope** — for the entity-backed `MemberMaterialsManager`,
        `X-User-ID` must equal the member the operation touches: the body `member_id` on a create,
        or the `member_id` reachable from the path resource otherwise."
        PRD §2.9: "Otherwise `ERR_MEMBER_SCOPE_VIOLATION` (403)."
        PRD §2.1: "Concretely, a `MemberMaterialsManager` may only elect a commitment whose
        `member_id` equals its own `X-User-ID`, may only propose a cross-reference for its own
        `member_id`, may only sign the letter of participation of a commitment whose `member_id`
        equals its `X-User-ID`, may only request a local pricing exception on a commitment it
        owns, and may only read the leakage report of a commitment it owns."

        Design: Corner/validations/member_scope_is_checked_before_body_foreign_keys
        """
        setup = one_rung_contract_and_two_members

        response = _elect_as(
            api,
            setup["stranger"],
            setup["owner"]["id"],
            UNKNOWN_ID,
            elected_tier_code="TIER_9",
        )

        validate_error(response, ERR_MEMBER_SCOPE_VIOLATION, 403)

    def test_the_body_foreign_key_is_resolved_only_once_scope_passes(
        self, api, one_rung_contract_and_two_members
    ):
        """PRD §2.9: "**Body foreign-key existence** — every foreign key in the body resolves,
        checked in body-declaration order `contract_id`, `member_id`, `contract_item_id`,
        `commitment_id`; otherwise the matching 404."
        PRD §2.8: "Foreign keys named in a request body are resolved after the path identifiers,
        in the order the body declares them — `contract_id`, then `member_id`, then
        `contract_item_id`, then `commitment_id` — and an unresolvable one returns the same 404
        error identifier as its path counterpart."

        Design: Corner/validations/member_scope_is_checked_before_body_foreign_keys
        """
        setup = one_rung_contract_and_two_members

        response = _elect_as(
            api,
            setup["owner"],
            setup["owner"]["id"],
            UNKNOWN_ID,
            elected_tier_code="TIER_9",
        )

        validate_error(response, ERR_CONTRACT_NOT_FOUND, 404)

    def test_the_unknown_tier_code_surfaces_last(self, api, one_rung_contract_and_two_members):
        """PRD §2.9: "**Known tier codes** — an elected tier code, and the tier code an activation
        must price against, appear in the contract's tier ladder, and the contract's derived
        default tier code appears there too; otherwise `ERR_TIER_CODE_UNKNOWN` (409)."

        Design: Corner/validations/member_scope_is_checked_before_body_foreign_keys
        """
        setup = one_rung_contract_and_two_members

        response = _elect_as(
            api,
            setup["owner"],
            setup["owner"]["id"],
            setup["contract"]["id"],
            elected_tier_code="TIER_9",
        )

        validate_error(response, ERR_TIER_CODE_UNKNOWN, 409)

    def test_the_fully_corrected_request_elects_and_the_rejects_wrote_nothing(
        self, api, one_rung_contract_and_two_members
    ):
        """PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the
        first violation, so a later rung's error can never mask an earlier rung's error."
        PRD §3.4: "Commitments may be listed filtered by `member_id`, `contract_id`,
        `election_status` and `lop_status`."

        Design: Corner/validations/member_scope_is_checked_before_body_foreign_keys
        """
        setup = one_rung_contract_and_two_members
        owner = setup["owner"]
        contract_id = setup["contract"]["id"]
        _elect_as(api, setup["stranger"], owner["id"], UNKNOWN_ID, elected_tier_code="TIER_9")
        _elect_as(api, owner, owner["id"], UNKNOWN_ID, elected_tier_code="TIER_9")
        _elect_as(api, owner, owner["id"], contract_id, elected_tier_code="TIER_9")
        assert _commitments_of(api, owner["id"], contract_id)[1]["total_count"] == 0

        elected = validate_success(
            _elect_as(api, owner, owner["id"], contract_id, elected_tier_code=TIER_0), 201
        )

        assert elected["election_status"] == "ELECTED"
        rows, meta = _commitments_of(api, owner["id"], contract_id)
        assert meta["total_count"] == 1
        a.assert_exact_ids(rows, [elected["id"]])


@pytest.fixture
def seventy_cents_billed_on_a_collected_contract(api):
    """A settlement whose accrual is 70 cents, on a contract that never declared its basis."""
    set_clock(api)
    contract = validate_success(
        api.create_contract(
            f.omit(
                f.contract_payload(
                    contract_code="C-COL",
                    tiers=[dict(row) for row in FLAT_TIER_LADDER],
                    holdback_tiers=[dict(row) for row in HOLDBACK_FLAT],
                ),
                "share_basis",
            ),
            headers=contract_manager_headers(),
        ),
        201,
    )
    activate_contract(api, contract["id"])
    contract = read_contract(api, contract["id"])
    item = create_item(api, contract["id"], base_price_cents=1200, floor_price_cents=1000)
    member = create_member(api, member_code="M-1")
    commitment = create_commitment(api, member["id"], contract["id"])
    commitment = countersign_commitment(api, commitment["id"], member["id"])
    create_approved_cross_reference(api, member["id"], item["id"])
    create_active_tier_activation(api, commitment["id"], item["id"])
    submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-06"),
        ],
        stage="LOADED",
    )
    return {
        "contract": contract,
        "member": member,
        "commitment": commitment,
        "distribution": create_distribution(api, contract["id"]),
    }


def _collect(api, distribution_id, cents):
    return api.collect_distribution(
        distribution_id, f.collect_payload(cents), headers=finance_administrator_headers()
    )


class TestTheRemittanceCeilingIsTheAggregateThePeriodEarned:
    """Seventy cents is collectable; seventy-one is not, and neither is a second seventy."""

    def test_the_settlement_opens_at_seventy_cents_on_the_collected_default(
        self, api, seventy_cents_billed_on_a_collected_contract
    ):
        """PRD §3.1: "Three optional switches round out the header: `requires_clinical_review`, a
        boolean defaulting to true; `share_basis`, an enumeration of `ACCRUAL` or `COLLECTED`
        defaulting to `COLLECTED`; and `leakage_alert_threshold_pct`, a percentage between 0.00 and
        100.00 carrying two decimal places and defaulting to 15.00."
        PRD §3.9: "The rounding happens per line and only per line — never on the summed spend —
        and the difference is real: two lines of 1150 cents at 300 basis points each yield 34.5
        cents, rounded half up to 35, for a total of 70 cents, whereas rounding the aggregate would
        give 2300 times 300 divided by 10000, or 69 cents."
        PRD §3.9: "The new row is created in `ACCRUED` status with `collected_fee_cents` at 0,
        `basis` null, `holdback_bps_applied`, `holdback_cents`, `gross_pool_cents`,
        `net_pool_cents`, `member_pool_cents`, `member_share_total_cents`, `undistributed_cents`
        and `gpo_retained_cents` all at 0, `member_shares` an empty array, and `reverse_note`
        null."

        Design: Corner/validations/collected_fee_cannot_exceed_the_accrued_fee
        """
        setup = seventy_cents_billed_on_a_collected_contract

        assert setup["contract"]["share_basis"] == "COLLECTED"
        distribution = setup["distribution"]
        assert distribution["status"] == "ACCRUED"
        assert distribution["accrued_fee_cents"] == 70
        assert distribution["collected_fee_cents"] == 0
        assert distribution["basis"] is None
        assert distribution["member_shares"] == []

    def test_one_cent_over_the_accrual_is_refused(
        self, api, seventy_cents_billed_on_a_collected_contract
    ):
        """PRD §2.9: "**Fee settlement coherence** — the collected fee does not exceed the accrued
        fee (`ERR_COLLECTION_EXCEEDS_ACCRUAL`), and the distribute action matches the contract's
        declared share basis (`ERR_DISTRIBUTION_BASIS_MISMATCH` or
        `ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE`); all 409."
        PRD §3.9: "It carries a `collected_fee_cents` body field, which must be an integer of at
        least 0, else `ERR_INVALID_REQUEST`, and must not exceed `accrued_fee_cents`, else
        `ERR_COLLECTION_EXCEEDS_ACCRUAL` — the GPO cannot collect more than it billed."

        Design: Corner/validations/collected_fee_cannot_exceed_the_accrued_fee
        """
        setup = seventy_cents_billed_on_a_collected_contract

        over = _collect(api, setup["distribution"]["id"], 71)
        negative = _collect(api, setup["distribution"]["id"], -1)

        validate_error(over, ERR_COLLECTION_EXCEEDS_ACCRUAL, 409)
        validate_error(negative, ERR_INVALID_REQUEST, 400)
        still_accrued = read_distribution(api, setup["distribution"]["id"])
        assert still_accrued["status"] == "ACCRUED"
        assert still_accrued["collected_fee_cents"] == 0

    def test_a_collected_basis_contract_has_no_hop_out_of_accrued(
        self, api, seventy_cents_billed_on_a_collected_contract
    ):
        """PRD §3.9: "The `ACCRUED → DISTRIBUTED` route is legal only when `share_basis` is
        `ACCRUAL`, meaning the GPO shares what it billed and carries the collection risk itself; if
        `share_basis` is `COLLECTED`, distributing straight from `ACCRUED` returns
        `ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE`, since the cash has not been recorded yet."
        PRD §3.9: "Exactly one of the two hops is available for any given contract, and any other
        starting status returns `ERR_INVALID_DISTRIBUTION_STATE`."

        Design: Corner/validations/collected_fee_cannot_exceed_the_accrued_fee
        """
        setup = seventy_cents_billed_on_a_collected_contract

        response = api.distribute_distribution(
            setup["distribution"]["id"], {}, headers=finance_administrator_headers()
        )

        validate_error(response, ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE, 409)

    def test_exactly_the_accrual_collects_once_and_only_once(
        self, api, seventy_cents_billed_on_a_collected_contract
    ):
        """PRD §3.9: "The collect action drives `ACCRUED → COLLECTED` and requires the row to be in
        `ACCRUED` status, else `ERR_INVALID_DISTRIBUTION_STATE`."
        PRD §3.9: "The row's `version` increments by one."

        Design: Corner/validations/collected_fee_cannot_exceed_the_accrued_fee
        """
        setup = seventy_cents_billed_on_a_collected_contract
        distribution = setup["distribution"]

        collected = validate_success(_collect(api, distribution["id"], 70), 200)
        again = _collect(api, distribution["id"], 70)

        assert collected["status"] == "COLLECTED"
        assert collected["collected_fee_cents"] == 70
        assert collected["accrued_fee_cents"] == 70
        a.assert_version_bump(collected, distribution["version"])
        validate_error(again, ERR_INVALID_DISTRIBUTION_STATE, 409)
