"""Version tokens on parent records, and a rate boundary crossed in both directions.

Two writes that no state machine forbids and that are therefore guarded only by a
declared parent version: opening a second measurement period on a commitment the
first create already moved, and repricing a catalog item whose meaning lives on
the contract. Then the leakage alert, whose comparison is strictly greater-than,
watched as a cumulative rate lands exactly on the threshold, is nudged over it by
a one-unit file, and is walked back down through the same point by a reversal.
"""

from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BASE_PRICE_BELOW_FLOOR,
    ERR_DUPLICATE_MEASUREMENT_PERIOD,
    ERR_STALE_COMMITMENT_VERSION,
    ERR_STALE_CONTRACT_VERSION,
)
from test_helpers.constants import (
    DEFAULT_LEAKAGE_ALERT_THRESHOLD_PCT,
    FLAT_TIER_LADDER,
    HOLDBACK_FLAT,
)
from test_helpers.fixtures import (
    activate_contract,
    commitment_version,
    countersign_commitment,
    create_active_contract,
    create_active_tier_activation,
    create_approved_cross_reference,
    create_commitment,
    create_item,
    create_member,
    read_commitment,
    read_contract,
    read_distributor_file,
    read_item,
    read_member,
    reverse_distributor_file,
    set_clock,
    submit_distributor_file,
)
from test_helpers.test_users import compliance_analyst_headers, contract_manager_headers

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# The commitment token: a legal second period refused on the snapshot alone
# ---------------------------------------------------------------------------


@pytest.fixture
def measurement_token_setup(api) -> Json:
    """A live commitment with no purchase data, so only the token is in play."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-OCC",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    member = create_member(api)
    commitment = create_commitment(api, member["id"], contract["id"])
    countersign_commitment(api, commitment["id"], member["id"], signer_name="Dana Whitfield")
    return {
        "contract": contract,
        "member": member,
        "commitment": commitment,
        "token": commitment_version(api, commitment["id"]),
    }


def _open_period(api, commitment_id: str, token: Any, period_start: str, period_end: str):
    return api.create_measurement(
        f.measurement_payload(
            commitment_id, token, period_start=period_start, period_end=period_end
        ),
        headers=compliance_analyst_headers(),
    )


def _measurements_of(api, commitment_id: str):
    rows, meta = validate_paginated(
        api.list_measurements(
            f.page(100, 0, commitment_id=commitment_id), headers=compliance_analyst_headers()
        )
    )
    return rows, meta


class TestOpeningAMeasurementConsumesTheCommitmentToken:
    """The create is itself a write, so the token has to be re-read between periods."""

    def test_the_first_create_advances_the_commitment_version(
        self, api, measurement_token_setup
    ):
        """August opens against a freshly read token and moves the parent by one.

        PRD §2.6: "Opening a compliance measurement requires `expected_commitment_version` in the request body, carrying the client's last observed `version` of the parent `Commitment`."
        PRD §2.6: "Every accepted measurement create increments the parent commitment's `version` by one."
        PRD §3.8: "The new row is created in `DRAFT` with every money and volume field at 0, `compliance_pct` at 0.00, `preliminary_compliance_pct` null, `qualified_tier_code` null, `basis_empty` false, and `computed_variant` null; the parent commitment's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/measurement_create_with_stale_expected_commitment_version_returns_412
        """
        commitment_id = measurement_token_setup["commitment"]["id"]
        token = measurement_token_setup["token"]

        opened = validate_success(
            _open_period(api, commitment_id, token, "2026-08-01", "2026-09-01"), 201
        )
        a.assert_identifier(opened["id"])
        assert opened["status"] == "DRAFT"
        assert opened["commitment_id"] == commitment_id
        assert opened["computed_variant"] is None
        assert opened["basis_empty"] is False

        after = read_commitment(api, commitment_id)
        assert after["version"] == token + 1

    def test_the_second_period_with_the_first_token_is_stale(
        self, api, measurement_token_setup
    ):
        """September is a legal period; the declaration is simply one behind.

        PRD §2.6: "Two measurements over different periods on the same commitment are both perfectly legal product operations, so no state precondition stops the second one; the hazard is that the second writer derived its period boundaries and its expected tier from a commitment snapshot that the first measurement has already moved, since creating a measurement itself increments `Commitment.version`, and finalizing one later rewrites `current_tier_code` and `requalification_round`."
        PRD §2.6: "If it does not equal the commitment's current `version`, the request is rejected with `ERR_STALE_COMMITMENT_VERSION` and HTTP status 412."
        PRD §2.9: "**Optimistic concurrency** — the declared `expected_commitment_version` or `expected_contract_version` equals the parent's current `version`; otherwise `ERR_STALE_COMMITMENT_VERSION` or `ERR_STALE_CONTRACT_VERSION`, both HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/measurement_create_with_stale_expected_commitment_version_returns_412
        """
        commitment_id = measurement_token_setup["commitment"]["id"]
        token = measurement_token_setup["token"]
        first = validate_success(
            _open_period(api, commitment_id, token, "2026-08-01", "2026-09-01"), 201
        )

        refused = _open_period(api, commitment_id, token, "2026-09-01", "2026-10-01")
        validate_error(refused, ERR_STALE_COMMITMENT_VERSION, 412)

        rows, meta = _measurements_of(api, commitment_id)
        assert a.ids_of(rows) == [first["id"]]
        assert meta["total_count"] == 1

    def test_the_re_read_token_opens_the_second_period(self, api, measurement_token_setup):
        """One re-read of the parent and the identical body is accepted.

        PRD §2.6: "A stale declaration is refused rather than silently measured against a commitment the writer never saw."
        PRD §2.6: "Every accepted measurement create increments the parent commitment's `version` by one."
        PRD §3.8: "No measurement for the same commitment in `DRAFT`, `PRELIMINARY` or `FINAL` status may already cover the identical `period_start` and `period_end` pair, else `ERR_DUPLICATE_MEASUREMENT_PERIOD`; a measurement that has been abandoned into `SUPERSEDED` does not block a fresh one for the same period."

        Design: Corner/cross_cutting_complexity_layers/measurement_create_with_stale_expected_commitment_version_returns_412
        """
        commitment_id = measurement_token_setup["commitment"]["id"]
        token = measurement_token_setup["token"]
        first = validate_success(
            _open_period(api, commitment_id, token, "2026-08-01", "2026-09-01"), 201
        )
        validate_error(
            _open_period(api, commitment_id, token, "2026-09-01", "2026-10-01"),
            ERR_STALE_COMMITMENT_VERSION,
            412,
        )

        fresh = commitment_version(api, commitment_id)
        assert fresh == token + 1
        second = validate_success(
            _open_period(api, commitment_id, fresh, "2026-09-01", "2026-10-01"), 201
        )
        assert second["id"] != first["id"]
        assert second["status"] == "DRAFT"
        assert commitment_version(api, commitment_id) == fresh + 1

    def test_a_current_token_reaches_the_duplicate_period_rule(
        self, api, measurement_token_setup
    ):
        """With nothing to complain about on the token, the uniqueness rung answers.

        PRD §2.9: "Rules are evaluated strictly in ascending order and evaluation stops at the first violation, so a later rung's error can never mask an earlier rung's error."
        PRD §2.9: "**Uniqueness** — one non-terminated commitment per member-and-contract pair (`ERR_DUPLICATE_COMMITMENT`); one `APPROVED` cross-reference per member-and-catalog-item pair and per member-and-member-item-number pair (`ERR_DUPLICATE_XREF`); one non-superseded compliance measurement per commitment-and-period triple (`ERR_DUPLICATE_MEASUREMENT_PERIOD`); one non-reversed fee distribution per contract-and-period triple (`ERR_DUPLICATE_DISTRIBUTION_PERIOD`); and one occurrence of each tier code inside a submitted tier ladder (`ERR_DUPLICATE_TIER_CODE`); all 409."

        Design: Corner/cross_cutting_complexity_layers/measurement_create_with_stale_expected_commitment_version_returns_412
        """
        commitment_id = measurement_token_setup["commitment"]["id"]
        token = measurement_token_setup["token"]
        validate_success(
            _open_period(api, commitment_id, token, "2026-08-01", "2026-09-01"), 201
        )
        second_token = commitment_version(api, commitment_id)
        validate_success(
            _open_period(api, commitment_id, second_token, "2026-09-01", "2026-10-01"), 201
        )

        third_token = commitment_version(api, commitment_id)
        assert third_token == second_token + 1
        refused = _open_period(api, commitment_id, third_token, "2026-09-01", "2026-10-01")
        error = validate_error(refused, ERR_DUPLICATE_MEASUREMENT_PERIOD, 409)
        assert error["error_id"] != ERR_STALE_COMMITMENT_VERSION

        rows, meta = _measurements_of(api, commitment_id)
        assert meta["total_count"] == 2
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# The contract token: a child write metered by its parent's version
# ---------------------------------------------------------------------------


@pytest.fixture
def reprice_setup(api) -> Json:
    """An ACTIVE contract with one item at base 10000 and floor 8200."""
    set_clock(api)
    contract = create_active_contract(
        api,
        contract_code="C-RP",
        requires_clinical_review=False,
        tiers=FLAT_TIER_LADDER,
        holdback_tiers=HOLDBACK_FLAT,
    )
    item = create_item(api, contract["id"])
    return {
        "contract": contract,
        "item": item,
        "token": read_contract(api, contract["id"])["version"],
    }


def _reprice(api, item_id: str, cents: int, token: Any):
    return api.patch_item_base_price(
        item_id, f.base_price_payload(cents, token), headers=contract_manager_headers()
    )


class TestRepricingAnItemConsumesTheContractToken:
    """The item moves, but the token that authorises the move belongs to the contract."""

    def test_one_reprice_advances_both_versions(self, api, reprice_setup):
        """A single edit consumes one contract version and one item version.

        PRD §2.6: "Repricing a catalog item requires `expected_contract_version` in the request body, carrying the client's last observed `version` of the parent `Contract`."
        PRD §3.1: "An accepted reprice increments both the contract's `version` and the item's `version` by one, and — importantly — leaves every already-created price activation holding the `computed_price_cents` it was minted with."

        Design: Corner/cross_cutting_complexity_layers/contract_item_base_price_patch_with_stale_expected_contract_version_returns_412
        """
        item = reprice_setup["item"]
        token = reprice_setup["token"]

        repriced = validate_success(_reprice(api, item["id"], 9500, token), 200)
        a.assert_cents(repriced["base_price_cents"])
        assert repriced["base_price_cents"] == 9500
        a.assert_version_bump(repriced, item["version"])
        assert read_contract(api, reprice_setup["contract"]["id"])["version"] == token + 1

    def test_a_second_legal_edit_with_the_first_token_is_refused(self, api, reprice_setup):
        """Nothing about 9300 is wrong; the declaration is behind by one.

        PRD §2.6: "Successive base-price edits on the same item are each legitimate — a later edit supersedes an earlier one — so no state precondition rejects the second write; but the tier ladder and the floor semantics that give a base price meaning live on the contract, and every accepted edit advances `Contract.version`."
        PRD §2.6: "If it does not equal the contract's current `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/contract_item_base_price_patch_with_stale_expected_contract_version_returns_412
        """
        item = reprice_setup["item"]
        token = reprice_setup["token"]
        validate_success(_reprice(api, item["id"], 9500, token), 200)

        refused = _reprice(api, item["id"], 9300, token)
        validate_error(refused, ERR_STALE_CONTRACT_VERSION, 412)
        assert read_item(api, item["id"])["base_price_cents"] == 9500

    def test_the_stale_token_outranks_the_fiscal_floor(self, api, reprice_setup):
        """8000 is under the 8200 floor, yet the token complaint is what comes back.

        PRD §2.9: "**Optimistic concurrency** — the declared `expected_commitment_version` or `expected_contract_version` equals the parent's current `version`; otherwise `ERR_STALE_COMMITMENT_VERSION` or `ERR_STALE_CONTRACT_VERSION`, both HTTP 412."
        PRD §2.9: "**Base price floor** — a new base price is a positive integer that is not below the item's floor price; otherwise `ERR_BASE_PRICE_BELOW_FLOOR` (409)."
        PRD §3.1: "The new price must be a positive integer that is not below the item's `floor_price_cents`; a price below the floor is rejected with `ERR_BASE_PRICE_BELOW_FLOOR`."

        Design: Corner/cross_cutting_complexity_layers/contract_item_base_price_patch_with_stale_expected_contract_version_returns_412
        """
        item = reprice_setup["item"]
        token = reprice_setup["token"]
        validate_success(_reprice(api, item["id"], 9500, token), 200)
        current = read_contract(api, reprice_setup["contract"]["id"])["version"]

        stale = validate_error(_reprice(api, item["id"], 8000, token), ERR_STALE_CONTRACT_VERSION, 412)
        assert stale["error_id"] != ERR_BASE_PRICE_BELOW_FLOOR

        fresh = validate_error(
            _reprice(api, item["id"], 8000, current), ERR_BASE_PRICE_BELOW_FLOOR, 409
        )
        assert fresh["error_id"] == ERR_BASE_PRICE_BELOW_FLOOR

    def test_the_floor_is_inclusive_and_no_refusal_wrote_anything(self, api, reprice_setup):
        """Seven calls, two accepted edits, and the item's price shows exactly those two.

        PRD §3.1: "The new price must be a positive integer that is not below the item's `floor_price_cents`; a price below the floor is rejected with `ERR_BASE_PRICE_BELOW_FLOOR`."
        PRD §3.1: "An accepted reprice increments both the contract's `version` and the item's `version` by one, and — importantly — leaves every already-created price activation holding the `computed_price_cents` it was minted with."
        PRD §2.4: "Ten of the eleven resource types — contracts, contract items, members, clinical evidence reviews, commitments, item cross-references, price activations, distributor files, compliance measurements and administrative fee distributions — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every accepted mutation of that row, including mutations the server performs on its own initiative as part of a cascade."

        Design: Corner/cross_cutting_complexity_layers/contract_item_base_price_patch_with_stale_expected_contract_version_returns_412
        """
        contract_id = reprice_setup["contract"]["id"]
        item = reprice_setup["item"]
        token = reprice_setup["token"]

        first = validate_success(_reprice(api, item["id"], 9500, token), 200)
        current = read_contract(api, contract_id)["version"]
        validate_error(_reprice(api, item["id"], 9300, token), ERR_STALE_CONTRACT_VERSION, 412)
        validate_error(_reprice(api, item["id"], 8000, token), ERR_STALE_CONTRACT_VERSION, 412)
        validate_error(
            _reprice(api, item["id"], 8000, current), ERR_BASE_PRICE_BELOW_FLOOR, 409
        )

        second = validate_success(_reprice(api, item["id"], 8200, current), 200)
        assert second["base_price_cents"] == 8200
        a.assert_version_bump(second, first["version"])

        reread = read_item(api, item["id"])
        assert reread["base_price_cents"] == 8200
        assert reread["floor_price_cents"] == 8200
        assert reread["version"] == item["version"] + 2
        assert read_contract(api, contract_id)["version"] == token + 2


# ---------------------------------------------------------------------------
# The leakage alert: strictly greater-than, approached from both sides
# ---------------------------------------------------------------------------


AUGUST_LINES = [
    f.purchase_line_row("MI-1", 850, 10000, "2026-08-05"),
    f.purchase_line_row("MI-1", 100, 15000, "2026-08-06"),
]
SEPTEMBER_LINES = [f.purchase_line_row("MI-1", 1, 15000, "2026-09-05")]


@pytest.fixture
def threshold_setup(api) -> Json:
    """A priced member whose contract takes the declared default alert threshold."""
    set_clock(api)
    payload = f.omit(
        f.contract_payload(
            contract_code="C-TH",
            requires_clinical_review=False,
            tiers=FLAT_TIER_LADDER,
            holdback_tiers=HOLDBACK_FLAT,
        ),
        "leakage_alert_threshold_pct",
    )
    created = validate_success(
        api.create_contract(payload, headers=contract_manager_headers()), 201
    )
    activate_contract(api, created["id"])
    contract = read_contract(api, created["id"])
    item = create_item(api, contract["id"])
    member = create_member(api)
    commitment = create_commitment(api, member["id"], contract["id"])
    countersign_commitment(api, commitment["id"], member["id"], signer_name="Dana Whitfield")
    create_approved_cross_reference(api, member["id"], item["id"])
    create_active_tier_activation(
        api,
        commitment["id"],
        item["id"],
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    return {"contract": contract, "item": item, "member": member, "commitment": commitment}


def _land(api, setup: Json, lines, period_start: str, period_end: str) -> Json:
    return submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        lines,
        distributor_code="DIST-MW",
        period_start=period_start,
        period_end=period_end,
        stage="LOADED",
    )


class TestTheLeakageAlertFiresOnlyStrictlyAboveTheThreshold:
    """A cumulative rate over the year-to-date ledgers, watched across the boundary."""

    def test_landing_exactly_on_the_threshold_raises_nothing(self, api, threshold_setup):
        """15.00 percent against a 15.00 threshold leaves the flag and the watchlist alone.

        PRD §3.1: "Three optional switches round out the header: `requires_clinical_review`, a boolean defaulting to true; `share_basis`, an enumeration of `ACCRUAL` or `COLLECTED` defaulting to `COLLECTED`; and `leakage_alert_threshold_pct`, a percentage between 0.00 and 100.00 carrying two decimal places and defaulting to 15.00."
        PRD §3.7: "Against the governing row's `computed_price_cents`, the line classifies as `ON_CONTRACT` when its `unit_price_paid_cents` is less than or equal to that price, and as `OFF_CONTRACT_LEAKAGE` when it is greater."
        PRD §3.7: "**Hop 2 — the year-to-date ledgers**, caused by hop 1's classification writes."
        PRD §3.7: "The server finds the commitment for this file's member-and-contract pair whose `election_status` is `ELECTED`, `ACTIVE` or `REQUAL_REVIEW`, and posts three running sums onto it: `ytd_on_contract_spend_cents` grows by the total `extended_cost_cents` of the file's `ON_CONTRACT` lines; `ytd_total_category_spend_cents` grows by the total `extended_cost_cents` of the file's `ON_CONTRACT`, `OFF_CONTRACT_LEAKAGE` and `UNMATCHED` lines together; and `ytd_measured_volume_units` grows by the total `contract_units` of the file's `ON_CONTRACT` lines."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate landing exactly on the threshold does not raise the flag."
        PRD §3.7: "With the default threshold of 15.00, a member whose leakage stands at exactly 15.00 percent is not flagged and one at 15.01 percent is."

        Design: Corner/cross_cutting_complexity_layers/leakage_flag_not_raised_at_exactly_the_threshold
        """
        a.assert_pct(
            threshold_setup["contract"]["leakage_alert_threshold_pct"],
            DEFAULT_LEAKAGE_ALERT_THRESHOLD_PCT,
        )

        landed = _land(api, threshold_setup, AUGUST_LINES, "2026-08-01", "2026-09-01")
        assert landed["status"] == "LOADED"

        commitment = read_commitment(api, threshold_setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 8500000
        assert commitment["ytd_total_category_spend_cents"] == 10000000
        assert commitment["ytd_measured_volume_units"] == 850
        a.assert_pct(commitment["ytd_leakage_pct"], 15.00)
        assert commitment["leakage_flag"] is False

        member = read_member(api, threshold_setup["member"]["id"])
        assert member["watchlist_status"] == "NONE"

    def test_one_more_leakage_line_crosses_the_boundary(self, api, threshold_setup):
        """A single 15000-cent unit in an abutting period takes the rate to 15.13.

        PRD §2.9: "**Distributor file overlap** — no existing distributor file for the same member, contract and distributor code, in any status other than `REJECTED` or `REVERSED`, has a half-open period colliding with the new file's; abutting periods, where one ends exactly on the day the next begins, do not collide."
        PRD §3.7: "`ytd_leakage_pct` is recomputed as follows: subtract `ytd_on_contract_spend_cents` from `ytd_total_category_spend_cents`, multiply the difference by 100, divide by `ytd_total_category_spend_cents`, and round half up to two decimal places."
        PRD §3.7: "If the recomputed `ytd_leakage_pct` is **strictly greater than** the contract's `leakage_alert_threshold_pct`, `leakage_flag` is set to true; a rate landing exactly on the threshold does not raise the flag."
        PRD §3.7: "**Hop 4 — the watchlist**, caused by hop 3 raising the flag from false to true."
        PRD §3.7: "The member's `watchlist_status` becomes `WATCHLIST` and that member's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/leakage_flag_not_raised_at_exactly_the_threshold
        """
        first = _land(api, threshold_setup, AUGUST_LINES, "2026-08-01", "2026-09-01")
        second = _land(api, threshold_setup, SEPTEMBER_LINES, "2026-09-01", "2026-10-01")
        assert first["status"] == "LOADED"
        assert second["status"] == "LOADED"

        commitment = read_commitment(api, threshold_setup["commitment"]["id"])
        assert commitment["ytd_on_contract_spend_cents"] == 8500000
        assert commitment["ytd_total_category_spend_cents"] == 10015000
        a.assert_pct(commitment["ytd_leakage_pct"], 15.13)
        assert commitment["leakage_flag"] is True

        member = read_member(api, threshold_setup["member"]["id"])
        assert member["watchlist_status"] == "WATCHLIST"

    def test_the_reversal_walks_the_rate_back_down_through_the_threshold(
        self, api, threshold_setup
    ):
        """Equality clears the flag exactly as it failed to raise it.

        PRD §3.7: "First, the same commitment's `ytd_on_contract_spend_cents`, `ytd_total_category_spend_cents` and `ytd_measured_volume_units` are each decremented by **exactly the amounts this file added at load time** — not by a re-derivation from current data — and the commitment's `version` increments by one."
        PRD §3.7: "Second, caused by that decrement, `ytd_leakage_pct` is recomputed by the same formula as hop 3, and if the recomputed rate is less than or equal to the contract's `leakage_alert_threshold_pct` — including the case where the denominator has fallen back to 0 and the rate is therefore 0.00 — then `leakage_flag` is set to false."
        PRD §3.7: "Third, caused by that flag falling, the member's `watchlist_status` returns to `NONE` if and only if no commitment of that member still carries `leakage_flag` true, with a `version` increment on the member."
        PRD §3.7: "`status` becomes `REVERSED`, which is terminal, and the file's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/leakage_flag_not_raised_at_exactly_the_threshold
        """
        _land(api, threshold_setup, AUGUST_LINES, "2026-08-01", "2026-09-01")
        second = _land(api, threshold_setup, SEPTEMBER_LINES, "2026-09-01", "2026-10-01")

        reversed_file = reverse_distributor_file(
            api, second["id"], reason="distributor resent the September file"
        )
        assert reversed_file["status"] == "REVERSED"
        assert read_distributor_file(api, second["id"])["status"] == "REVERSED"

        commitment = read_commitment(api, threshold_setup["commitment"]["id"])
        assert commitment["ytd_total_category_spend_cents"] == 10000000
        assert commitment["ytd_on_contract_spend_cents"] == 8500000
        a.assert_pct(commitment["ytd_leakage_pct"], 15.00)
        assert commitment["leakage_flag"] is False

        member = read_member(api, threshold_setup["member"]["id"])
        assert member["watchlist_status"] == "NONE"
