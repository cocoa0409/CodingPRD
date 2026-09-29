"""Two interval conventions, deliberately opposite, on two reservation keys.

A distributor file reserves a half-open period, so a file ending on the first of
September and one beginning on that same day abut and both stand.  A price
activation reserves a fully closed window, so sharing that single date is
already a collision.  Both keys are compound, and in both cases the terminal
statuses stop reserving anything at all.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACTIVATION_PERIOD_OVERLAP,
    ERR_FILE_PERIOD_OVERLAP,
)
from test_helpers.constants import TIER_0
from test_helpers.fixtures import (
    build_priced_setup,
    create_active_contract,
    create_member,
    read_activation,
    read_distributor_file,
    read_item,
    reverse_distributor_file,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import (
    compliance_analyst_headers,
    contract_manager_headers,
    distributor_agent_headers,
    make_member_materials_manager_headers,
)


@pytest.fixture
def loaded_august_statement(api):
    """One LOADED D-A statement over [2026-08-01, 2026-09-01), and no commitment at all."""
    set_clock(api)
    contract = create_active_contract(api)
    member = create_member(api)
    file_a = submit_distributor_file(
        api,
        member["id"],
        contract["id"],
        [f.purchase_line_row("MI-1", 100, 9500, "2026-08-05")],
        distributor_code="D-A",
        period_start="2026-08-01",
        period_end="2026-09-01",
    )
    return {"contract": contract, "member": member, "file_a": file_a}


@pytest.fixture
def elected_commitment_with_a_draft_tier_price(api):
    """A DRAFT TIER_PRICE over the closed window [2026-08-01, 2026-09-30].

    The letter of participation has not been countersigned, so the commitment
    carries no `current_tier_code` and the price is taken off the contract's
    default rung.
    """
    setup = build_priced_setup(
        api,
        countersign=False,
        with_xref=False,
        with_activation=False,
    )
    activation = validate_success(
        api.create_price_activation(
            f.price_activation_payload(
                setup["commitment"]["id"],
                setup["item"]["id"],
                effective_from="2026-08-01",
                effective_to="2026-09-30",
            ),
            headers=contract_manager_headers(),
        ),
        201,
    )
    setup["activation"] = activation
    return setup


def _submit_file(api, member_id, contract_id, lines, distributor_code, period_start, period_end):
    payload = f.distributor_file_payload(
        member_id,
        contract_id,
        lines,
        distributor_code=distributor_code,
        period_start=period_start,
        period_end=period_end,
    )
    return api.create_distributor_file(payload, headers=distributor_agent_headers())


def _files_of(api, member_id, **filters):
    params = dict(filters)
    params["member_id"] = member_id
    params.setdefault("limit", 100)
    data, _meta = validate_paginated(
        api.list_distributor_files(params, headers=compliance_analyst_headers())
    )
    return data


def _request_activation(api, commitment_id, contract_item_id, headers, **kwargs):
    payload = f.price_activation_payload(commitment_id, contract_item_id, **kwargs)
    return api.create_price_activation(payload, headers=headers)


def _activations_of(api, commitment_id):
    data, _meta = validate_paginated(
        api.list_price_activations(
            {"commitment_id": commitment_id, "limit": 100},
            headers=contract_manager_headers(),
        )
    )
    return data


class TestHalfOpenFilePeriods:
    """The key is (member, contract, distributor_code) and the period excludes its end."""

    def test_the_next_period_may_begin_on_the_day_the_last_one_ended(
        self, api, loaded_august_statement
    ):
        """PRD §2.10: "The start day is included, the end day is excluded, and
        `period_end` must be strictly after `period_start`."
        PRD §2.10: "This is why two distributor files can abut — one ending on the first
        of September, the next beginning on the first of September — without colliding."
        PRD §3.7: "Because the periods are half-open, a file ending on a given day and a
        file starting on that same day abut rather than collide."

        Design: Difficulty/resource_temporal_overlap/distributor_file_half_open_periods_abut_without_colliding
        """
        setup = loaded_august_statement
        assert setup["file_a"]["status"] == "LOADED"

        abutting = validate_success(
            _submit_file(
                api,
                setup["member"]["id"],
                setup["contract"]["id"],
                [f.purchase_line_row("MI-1", 10, 9500, "2026-09-05")],
                "D-A",
                "2026-09-01",
                "2026-10-01",
            ),
            201,
        )

        assert abutting["status"] == "RECEIVED"
        assert abutting["period_start"] == "2026-09-01"
        assert abutting["period_end"] == "2026-10-01"

    def test_a_straddling_period_is_refused_for_the_same_distributor(
        self, api, loaded_august_statement
    ):
        """PRD §3.7: "and no existing file for the same member, contract and
        `distributor_code`, in any status other than `REJECTED` or `REVERSED`, to have a
        half-open collision with the new period, else `ERR_FILE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/distributor_file_half_open_periods_abut_without_colliding
        """
        setup = loaded_august_statement

        validate_error(
            _submit_file(
                api,
                setup["member"]["id"],
                setup["contract"]["id"],
                [f.purchase_line_row("MI-1", 10, 9500, "2026-08-20")],
                "D-A",
                "2026-08-15",
                "2026-09-15",
            ),
            ERR_FILE_PERIOD_OVERLAP,
            409,
        )

        assert len(_files_of(api, setup["member"]["id"], distributor_code="D-A")) == 1

    def test_a_second_distributor_may_report_the_identical_period(
        self, api, loaded_august_statement
    ):
        """PRD §3.7: "A `DistributorAgent` submits one **sales-tracing file** per member,
        contract, distributor and half-open period, naming `member_id`, `contract_id`, a
        `distributor_code` of 1 to 40 characters, `period_start` and `period_end`, and an
        array `lines` of at least one entry."

        Design: Difficulty/resource_temporal_overlap/distributor_file_half_open_periods_abut_without_colliding
        """
        setup = loaded_august_statement

        other_distributor = validate_success(
            _submit_file(
                api,
                setup["member"]["id"],
                setup["contract"]["id"],
                [f.purchase_line_row("MI-1", 10, 9500, "2026-08-06")],
                "D-B",
                "2026-08-01",
                "2026-09-01",
            ),
            201,
        )

        assert other_distributor["status"] == "RECEIVED"
        assert other_distributor["distributor_code"] == "D-B"
        assert len(_files_of(api, setup["member"]["id"], distributor_code="D-A")) == 1
        assert len(_files_of(api, setup["member"]["id"], distributor_code="D-B")) == 1

    def test_a_reversed_statement_stops_reserving_its_window(
        self, api, loaded_august_statement
    ):
        """PRD §3.7: "and no existing file for the same member, contract and
        `distributor_code`, in any status other than `REJECTED` or `REVERSED`, to have a
        half-open collision with the new period, else `ERR_FILE_PERIOD_OVERLAP`."
        PRD §3.7: "A `ComplianceAnalyst` reverses a file from `LOADED` or from
        `PARTIALLY_LOADED` — the two branches behave identically — optionally recording a
        `reason` stored as `reverse_note`; any other starting status returns
        `ERR_INVALID_FILE_STATE`."
        PRD §3.7: "`status` becomes `REVERSED`, which is terminal, and the file's
        `version` increments by one."

        Design: Difficulty/resource_temporal_overlap/distributor_file_half_open_periods_abut_without_colliding
        """
        setup = loaded_august_statement

        reverse_distributor_file(
            api, setup["file_a"]["id"], "Distributor restated the August statement."
        )
        assert read_distributor_file(api, setup["file_a"]["id"])["status"] == "REVERSED"

        restated = validate_success(
            _submit_file(
                api,
                setup["member"]["id"],
                setup["contract"]["id"],
                [f.purchase_line_row("MI-1", 120, 9500, "2026-08-05")],
                "D-A",
                "2026-08-01",
                "2026-09-01",
            ),
            201,
        )

        assert restated["status"] == "RECEIVED"
        rows = _files_of(api, setup["member"]["id"], distributor_code="D-A")
        assert len(rows) == 2
        assert sorted(row["status"] for row in rows) == ["RECEIVED", "REVERSED"]


class TestClosedActivationWindows:
    """The key is (commitment, item, activation_type) and both endpoints are included."""

    def test_the_draft_row_prices_off_the_contracts_default_rung(
        self, api, elected_commitment_with_a_draft_tier_price
    ):
        """PRD §3.6: "The server then pins `tier_code_at_activation`: the commitment's
        `current_tier_code` if it has one, or the contract's `default_tier_code` when
        `current_tier_code` is still null — which is the case for any commitment whose
        letter has not yet been countersigned."
        PRD §2.10: "A contract's `effective_to` must be strictly after its
        `effective_from`; a price activation's `effective_to` must be on or after its
        `effective_from`, so a single-day price is legal."

        Design: Difficulty/resource_temporal_overlap/price_activation_closed_windows_collide_on_a_shared_endpoint_date
        """
        activation = elected_commitment_with_a_draft_tier_price["activation"]

        assert activation["status"] == "DRAFT"
        assert activation["tier_code_at_activation"] == TIER_0
        assert activation["computed_price_cents"] == 10000
        assert activation["effective_from"] == "2026-08-01"
        assert activation["effective_to"] == "2026-09-30"

    def test_one_shared_endpoint_date_is_already_a_collision(
        self, api, elected_commitment_with_a_draft_tier_price
    ):
        """PRD §2.10: "Because both endpoints are included, two activations sharing
        exactly one endpoint date do overlap, which is the opposite of the half-open file
        rule."
        PRD §3.6: "No other activation for the **same commitment, same catalog item and
        same activation type** whose status is `DRAFT`, `ENDORSED`, `APPROVED` or `ACTIVE`
        may have a closed-interval collision with the new window; because both endpoints
        are inclusive, two windows that share even a single day collide, and the rejection
        is `ERR_ACTIVATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_activation_closed_windows_collide_on_a_shared_endpoint_date
        """
        setup = elected_commitment_with_a_draft_tier_price

        validate_error(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                contract_manager_headers(),
                effective_from="2026-09-30",
                effective_to="2026-12-31",
            ),
            ERR_ACTIVATION_PERIOD_OVERLAP,
            409,
        )

        assert len(_activations_of(api, setup["commitment"]["id"])) == 1

    def test_the_day_after_the_endpoint_is_free(
        self, api, elected_commitment_with_a_draft_tier_price
    ):
        """PRD §2.10: "**Closed windows** apply to contract terms and to prices: a
        contract's `effective_from` and `effective_to`, and a price activation's
        `effective_from` and `effective_to`. Both endpoint days are included."
        PRD §3.6: "An accepted request creates the activation in `DRAFT` status with
        `origin` `REQUEST`, `endorsed_by_user_id`, `approved_by_user_id`, `deny_note`,
        `superseded_by_activation_id` and `replaces_activation_id` all null."

        Design: Difficulty/resource_temporal_overlap/price_activation_closed_windows_collide_on_a_shared_endpoint_date
        """
        setup = elected_commitment_with_a_draft_tier_price

        second = validate_success(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                contract_manager_headers(),
                effective_from="2026-10-01",
                effective_to="2026-12-31",
            ),
            201,
        )

        assert second["status"] == "DRAFT"
        assert second["origin"] == "REQUEST"
        assert second["superseded_by_activation_id"] is None
        assert second["replaces_activation_id"] is None
        assert len(_activations_of(api, setup["commitment"]["id"])) == 2

    def test_the_other_activation_type_may_cover_the_identical_window(
        self, api, elected_commitment_with_a_draft_tier_price
    ):
        """PRD §3.6: "No other activation for the **same commitment, same catalog item and
        same activation type** whose status is `DRAFT`, `ENDORSED`, `APPROVED` or `ACTIVE`
        may have a closed-interval collision with the new window; because both endpoints
        are inclusive, two windows that share even a single day collide, and the rejection
        is `ERR_ACTIVATION_PERIOD_OVERLAP`."
        PRD §3.6: "Two illustrations of the interaction: a requested 9000 cents against a
        zero-discount tier price of 10000 with a floor of 8200 yields a candidate of 9000,
        which is above the floor, so `computed_price_cents` is 9000 and `price_clamped` is
        false; a requested 8000 cents against a 1500-basis-point tier price of 8500 with a
        floor of 8200 yields a candidate of 8000, which is below the floor, so
        `computed_price_cents` becomes 8200 and `price_clamped` is true."

        Design: Difficulty/resource_temporal_overlap/price_activation_closed_windows_collide_on_a_shared_endpoint_date
        """
        setup = elected_commitment_with_a_draft_tier_price

        exception = validate_success(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                make_member_materials_manager_headers(setup["member"]["id"]),
                activation_type="LOCAL_EXCEPTION",
                requested_price_cents=9000,
                effective_from="2026-08-01",
                effective_to="2026-09-30",
            ),
            201,
        )

        assert exception["status"] == "DRAFT"
        assert exception["activation_type"] == "LOCAL_EXCEPTION"
        assert exception["computed_price_cents"] == 9000
        assert exception["price_clamped"] is False

    def test_a_denied_exception_stops_reserving_its_window(
        self, api, elected_commitment_with_a_draft_tier_price
    ):
        """PRD §3.6: "A local exception may be **denied** terminally from either `DRAFT`
        or `ENDORSED`, optionally recording a `reason` that is stored as `deny_note` and
        left null when omitted."
        PRD §3.6: "Rows already in `SUPERSEDED` or `DENIED` are invisible to this guard,
        which is precisely what lets a cascade-minted replacement window start inside the
        window of the row it replaced."

        Design: Difficulty/resource_temporal_overlap/price_activation_closed_windows_collide_on_a_shared_endpoint_date
        """
        setup = elected_commitment_with_a_draft_tier_price
        member_headers = make_member_materials_manager_headers(setup["member"]["id"])
        first = validate_success(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                member_headers,
                activation_type="LOCAL_EXCEPTION",
                requested_price_cents=9000,
                effective_from="2026-08-01",
                effective_to="2026-09-30",
            ),
            201,
        )
        validate_success(
            api.deny_price_activation(
                first["id"],
                f.reason_payload("Local price not justified."),
                headers=contract_manager_headers(),
            ),
            200,
        )
        assert read_activation(api, first["id"])["status"] == "DENIED"

        second = validate_success(
            _request_activation(
                api,
                setup["commitment"]["id"],
                setup["item"]["id"],
                member_headers,
                activation_type="LOCAL_EXCEPTION",
                requested_price_cents=8800,
                effective_from="2026-08-01",
                effective_to="2026-09-30",
            ),
            201,
        )

        assert second["status"] == "DRAFT"
        assert second["computed_price_cents"] == 8800
        rows = _activations_of(api, setup["commitment"]["id"])
        assert len(rows) == 3
        assert sorted(row["status"] for row in rows) == ["DENIED", "DRAFT", "DRAFT"]
        assert read_item(api, setup["item"]["id"])["active_activation_count"] == 0
