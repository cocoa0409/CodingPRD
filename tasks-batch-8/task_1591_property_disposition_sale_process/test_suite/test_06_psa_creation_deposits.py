"""Purchase agreement creation (referential gate + OCC + supersede), the
deposit schedule, deposit delinquency sweep, the parallel asset state
dimensions, and the open-due-diligence cash gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_timestamp_prefix,
    cheap_asset_payload,
    close_offers,
    create_psa,
    create_psa_payload,
    get_asset,
    pipeline_to_bid,
    pipeline_to_dd_active,
    pipeline_to_executed,
    pipeline_to_psa_draft,
    post_deposit,
    select_bid,
    set_clock,
    shortlist_bid,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
CO = TEST_USERS["co_headers"]


class TestPsaCreationGates:
    def test_err_bid_not_selected(self, api):
        """PRD: "The referenced bid must be `SELECTED` and must belong to the
        same asset; anything else is `ERR_BID_NOT_SELECTED`."

        Design: Corner/errors/err_bid_not_selected
        """
        ws = pipeline_to_bid()
        set_clock("2026-09-16T00:00:00Z")
        close_offers(ws["asset"]["id"])
        shortlist_bid(ws["bid"]["id"])  # SHORTLISTED, deliberately not SELECTED
        version = get_asset(ws["asset"]["id"])["version"]
        payload = create_psa_payload(ws["asset"]["id"], ws["bid"]["id"], version)
        validate_error(api.create_psa(payload, DM), ApiErrorId.ERR_BID_NOT_SELECTED)
        assert get_asset(ws["asset"]["id"])["deal_status"] == "IDLE", \
            "no agreement created, so the deal dimension never left IDLE"

    def test_occ_psa_create_stale_version(self, api):
        """PRD: "If `expected_asset_version` does not match the asset's current
        `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD: "Creation supersedes any existing `DRAFT` agreement of the same
        asset, flipping it to `SUPERSEDED`, and advances the asset's deal
        dimension from `IDLE` to `PSA_DRAFT`, bumping the asset's `version`."

        Design: Corner/cross_cutting_layers/occ_psa_create_stale_version
        """
        ws = pipeline_to_psa_draft()  # first DRAFT agreement exists
        first_psa = ws["psa"]
        # The workspace asset was refreshed after the first create; the version
        # a caller held *before* that create is stale now.
        stale_version = ws["asset"]["version"] - 1

        resp = api.create_psa(
            create_psa_payload(ws["asset"]["id"], ws["bid"]["id"], stale_version,
                               "BANKERS_360"), DM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        second = create_psa(ws["asset"]["id"], ws["bid"]["id"], "BANKERS_360")
        assert second["status"] == "DRAFT"

        psas = validate_success(api.list_asset_psas(ws["asset"]["id"], DM))
        assert len(psas) == 2
        assert psas[0]["id"] == first_psa["id"]
        assert psas[0]["status"] == "SUPERSEDED"
        assert psas[1]["id"] == second["id"]
        assert psas[1]["status"] == "DRAFT"

        bid = validate_success(api.get_bid(ws["bid"]["id"], DM))
        assert bid["status"] == "SELECTED", \
            "superseding the draft agreement does not un-select the bid"


class TestDepositSchedule:
    def test_deposit_schedule_min_floor(self, api):
        """PRD: "`initial_deposit_cents` is the greater of three hundred basis
        points of the price, rounded half up, and a fixed floor of 10,000,000
        cents, while `additional_deposit_cents` is two hundred basis points of
        the price, rounded half up."
        PRD: "Two Deposit rows are auto-created in `DUE` status — the `INITIAL`
        kind due three days after `executed_at`, the `ADDITIONAL` kind due at
        `dd_deadline`"

        Design: Corner/calculations/deposit_schedule_min_floor
        """
        ws = pipeline_to_executed(
            asset_payload=cheap_asset_payload(),
            analysis_overrides={"cap_rate_bps": 500,
                                "est_sale_price_cents": 320_000_000,
                                "est_selling_costs_cents": 0},
            proof_of_funds=100_000_000,
            price_cents=300_000_000,
            deposit_cents=10_000_000,
            dd_period_days=20,
            closing_date="2026-10-15T00:00:00Z",
        )
        psa = ws["psa"]
        # 3% of 300,000,000 is 9,000,000 — below the fixed floor.
        assert psa["initial_deposit_cents"] == 10_000_000
        # 2% of 300,000,000 = 6,000,000.
        assert psa["additional_deposit_cents"] == 6_000_000

        deposits = ws["deposits"]
        assert len(deposits) == 2
        initial, additional = deposits[0], deposits[1]
        assert initial["kind"] == "INITIAL"
        assert initial["amount_cents"] == 10_000_000
        assert initial["status"] == "DUE"
        assert_timestamp_prefix(initial["due_date"], "2026-09-19T00:00:00")
        assert additional["kind"] == "ADDITIONAL"
        assert additional["amount_cents"] == 6_000_000
        assert additional["status"] == "DUE"
        assert_timestamp_prefix(additional["due_date"], "2026-10-06T00:00:00")

    def test_deposit_delinquency_sweep_then_post_rejected(self, api):
        """PRD: "moves any `DUE` deposit whose `due_date` lies before the new
        clock position to `DELINQUENT`"
        PRD: "Only a deposit still in `DUE` can be posted — one whose `due_date`
        has passed has already been swept to `DELINQUENT` by the clock and can
        never be posted — and a deposit whose agreement is `TERMINATED`,
        `CLOSED`, or `SUPERSEDED` is likewise unpostable; both rejections carry
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/deposit_delinquency_sweep_then_post_rejected
        """
        ws = pipeline_to_executed()  # executed at clock 2026-09-16
        initial = ws["deposits"][0]
        assert initial["status"] == "DUE"
        # INITIAL due date is executed_at + 3 days = 2026-09-19.
        set_clock("2026-09-20T00:00:00Z")
        deposits = validate_success(api.list_psa_deposits(ws["psa"]["id"], CO))
        assert deposits[0]["status"] == "DELINQUENT"
        validate_error(api.post_deposit(initial["id"], CO),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestParallelDimensions:
    def test_parallel_dimensions_deal_walks_marketing_frozen(self, api):
        """PRD: "An Asset carries two state fields that evolve independently on
        the same row."
        PRD: "The deal dimension has no direct writer endpoints at all: it
        advances purely as a cascade of purchase-agreement lifecycle events"
        PRD: "Opening due diligence moves the agreement from `EXECUTED` to
        `DD_ACTIVE` and cascades the asset's `deal_status` to `DD_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_independent
        """
        ws = pipeline_to_bid()
        set_clock("2026-09-16T00:00:00Z")
        close_offers(ws["asset"]["id"])
        shortlist_bid(ws["bid"]["id"])
        select_bid(ws["bid"]["id"])
        after_select = get_asset(ws["asset"]["id"])
        assert after_select["marketing_status"] == "OFFERS_CLOSED"
        assert after_select["deal_status"] == "IDLE", \
            "selection alone does not start the deal dimension"

        ws["psa"] = create_psa(ws["asset"]["id"], ws["bid"]["id"])
        after_draft = get_asset(ws["asset"]["id"])
        assert after_draft["marketing_status"] == "OFFERS_CLOSED"
        assert after_draft["deal_status"] == "PSA_DRAFT"

        ws2 = pipeline_to_executed(ws)
        assert ws2["asset"]["marketing_status"] == "OFFERS_CLOSED"
        assert ws2["asset"]["deal_status"] == "PSA_EXECUTED"

        post_deposit(ws2["deposits"][0]["id"])
        opened = validate_success(api.open_dd(ws2["psa"]["id"], DM))
        assert opened["status"] == "DD_ACTIVE"
        after_dd = get_asset(ws["asset"]["id"])
        assert after_dd["marketing_status"] == "OFFERS_CLOSED", \
            "the marketing dimension never moved while the deal walked"
        assert after_dd["deal_status"] == "DD_ACTIVE"

    def test_withdraw_blocked_while_deal_live_then_unwinds(self, api):
        """PRD: "Withdrawal is permitted only while `deal_status` is `IDLE`, so
        a live deal always blocks withdrawal"
        PRD: "it unwinds back to `IDLE` when a deal chain terminates or is
        superseded."
        PRD: "under `SELLER_DEFAULT` or `MUTUAL`, all `POSTED` deposits are
        `REFUNDED` instead; in every case the deal dimension unwinds to `IDLE`."

        Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_independent
        """
        ws = pipeline_to_dd_active()
        # Deal dimension is live (DD_ACTIVE): withdrawal is blocked.
        validate_error(api.withdraw_asset(ws["asset"]["id"], DM),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        terminated = validate_success(
            api.terminate_psa(ws["psa"]["id"], "MUTUAL", DM))
        assert terminated["status"] == "TERMINATED"
        unwound = get_asset(ws["asset"]["id"])
        assert unwound["deal_status"] == "IDLE"
        assert unwound["marketing_status"] == "OFFERS_CLOSED"

        withdrawn = validate_success(api.withdraw_asset(ws["asset"]["id"], DM))
        assert withdrawn["marketing_status"] == "WITHDRAWN"
        assert withdrawn["deal_status"] == "IDLE"


class TestOpenDdGate:
    def test_open_dd_requires_initial_deposit_posted(self, api):
        """PRD: "Opening due diligence moves the agreement from `EXECUTED` to
        `DD_ACTIVE` and cascades the asset's `deal_status` to `DD_ACTIVE`. The
        gate is cash: the `INITIAL` deposit of this agreement must be `POSTED`,
        and if it is not, the open is rejected with `ERR_DEPOSIT_NOT_POSTED`."

        Design: Difficulty/cross_entity_state_dependency/open_dd_requires_initial_deposit_posted
        """
        ws = pipeline_to_executed()
        assert ws["deposits"][0]["status"] == "DUE"
        validate_error(api.open_dd(ws["psa"]["id"], DM),
                       ApiErrorId.ERR_DEPOSIT_NOT_POSTED)

    def test_open_dd_succeeds_after_initial_posted(self, api):
        """PRD: "Deposits move from `DUE` to `POSTED` when a `ClosingOfficer`
        records the funds, stamping `posted_at` from the clock."
        PRD: "The gate is cash: the `INITIAL` deposit of this agreement must be
        `POSTED`, and if it is not, the open is rejected with
        `ERR_DEPOSIT_NOT_POSTED`."

        Design: Difficulty/cross_entity_state_dependency/open_dd_requires_initial_deposit_posted
        """
        ws = pipeline_to_executed()
        posted = post_deposit(ws["deposits"][0]["id"])
        assert posted["status"] == "POSTED"
        assert posted["posted_at"] is not None
        opened = validate_success(api.open_dd(ws["psa"]["id"], DM))
        assert opened["status"] == "DD_ACTIVE"
        assert get_asset(ws["asset"]["id"])["deal_status"] == "DD_ACTIVE"


class TestReverseLookups:
    def test_bid_psas_reverse_lookup(self, api):
        """PRD: "Read endpoints frequently address a collection beneath a parent
        resource, such as the analyses or payoffs of a given asset, or the
        deposits and statements of a given agreement."
        PRD Endpoint Definitions: the psas-of-a-bid listing returns
        PurchaseAgreements created from that bid.

        Design: Corner/endpoints/bid_psas_reverse_lookup
        """
        ws = pipeline_to_psa_draft()
        listed = validate_success(api.list_bid_psas(ws["bid"]["id"], DM))
        assert len(listed) == 1
        assert listed[0]["id"] == ws["psa"]["id"]
        assert listed[0]["bid_id"] == ws["bid"]["id"]
