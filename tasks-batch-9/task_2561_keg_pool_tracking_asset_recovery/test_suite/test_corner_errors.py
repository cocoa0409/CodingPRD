"""Corner coverage for §1.9 section ``errors``.

Every test in this module translates exactly one non-stub instance of the
``errors`` section of SCAFFOLD_CORNER_DESIGN.yaml: the error catalogue's own
codes, proved distinguishable from the neighbouring codes that the same
request could otherwise have produced, and always with the refusal shown to
have written nothing and the corrected replay shown to succeed.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_brewer_headers,
    make_distributor_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
ANALYST = make_analyst_headers(ANALYST_USER_ID)
TECH = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECH = make_technician_headers(SECOND_TECHNICIAN_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"
POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}
SECOND_POOL = {
    "pool_code": "SK-20L",
    "size_liters": 20,
    "stainless_weight_kg": 7.5,
    "replacement_cost_cents": 16000,
    "region_code": "CO",
}
KEG_SPECS_TWO = [
    {"asset_tag": "K-0001"},
    {"asset_tag": "K-0002", "fill_count": 5, "fills_at_last_pressure_test": 5},
]
KEG_SPECS_THREE = KEG_SPECS_TWO + [
    {"asset_tag": "K-0003", "fill_count": 6, "fills_at_last_pressure_test": 6},
]


# ==========================================================================
# Design: Corner/errors/request_with_no_headers_is_unauthenticated_before_the_404
# ==========================================================================


def _three_shapes_of_a_bad_identity():
    """The three header shapes §2.1 calls unauthenticated, aimed at a pool
    identifier that genuinely does not resolve."""
    fixtures.pin_clock(CLOCK)
    return [
        ("role header omitted entirely", {"X-User-ID": "op-1"}),
        ("blank user identifier", {"X-User-ID": "", "X-User-Role": "PoolOperator"}),
        ("role outside the declared five", build_user_headers("aud-1", "Auditor")),
    ]


def test_bad_identity_is_401_before_the_path_lookup():
    """All three shapes of a bad identity are refused as unauthenticated even
    though the addressed pool does not exist.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, naming the role that principal is
    acting in."

    PRD: "If either header is absent or blank, or if `X-User-Role` is not one
    of the five role names declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "Checks are evaluated in a fixed precedence order, and the first
    check that fails determines the response; no later check may mask an
    earlier one."

    Design: Corner/errors/request_with_no_headers_is_unauthenticated_before_the_404
    """
    for label, headers in _three_shapes_of_a_bad_identity():
        response = api_client.raw(
            "GET", f"/pools/{NON_EXISTENT_UUID}", headers=headers
        )
        assert response.status_code == 401, (
            f"{label}: expected 401, got {response.status_code}"
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_a_valid_identity_reaches_the_404_the_bad_ones_never_saw():
    """The same absent pool identifier answers 404 once the identity is
    well-formed, which is what the 401s were pre-empting.

    PRD: "If either header is absent or blank, or if `X-User-Role` is not one
    of the five role names declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "A path identifier that does not resolve produces the 404 belonging
    to that resource type: `ERR_BREWER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_KEG_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_SERVICE_CYCLE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND`
    or `ERR_INVESTIGATION_NOT_FOUND`."

    Design: Corner/errors/request_with_no_headers_is_unauthenticated_before_the_404
    """
    _three_shapes_of_a_bad_identity()

    validate_error(
        api_client.get_pool(NON_EXISTENT_UUID, OPERATOR),
        ApiErrorId.ERR_POOL_NOT_FOUND,
        404,
    )


# ==========================================================================
# Design: Corner/errors/every_path_id_lookup_has_its_own_not_found_code
# ==========================================================================


def _eleven_read_by_id_probes():
    """One read-by-id probe per entity in the 404 catalogue, each addressing an
    identifier the empty store cannot resolve."""
    fixtures.pin_clock(CLOCK)
    return [
        ("brewer", api_client.get_brewer, ApiErrorId.ERR_BREWER_NOT_FOUND),
        ("distributor", api_client.get_distributor, ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND),
        ("scan event", api_client.get_scan_event, ApiErrorId.ERR_SCAN_EVENT_NOT_FOUND),
        ("float agreement", api_client.get_float_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        ("issuance order", api_client.get_issuance_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
        ("service centre", api_client.get_service_center, ApiErrorId.ERR_SERVICE_CENTER_NOT_FOUND),
        ("service cycle", api_client.get_service_cycle, ApiErrorId.ERR_SERVICE_CYCLE_NOT_FOUND),
        ("loss assessment", api_client.get_loss_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        ("claim", api_client.get_reconciliation_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
        ("accrual", api_client.get_return_incentive, ApiErrorId.ERR_ACCRUAL_NOT_FOUND),
        ("investigation", api_client.get_theft_investigation, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND),
    ]


def test_each_entity_reports_its_own_404_code():
    """Eleven read-by-id endpoints each answer the 404 code belonging to their
    own resource type, never a shared generic code.

    PRD: "A path identifier that does not resolve produces the 404 belonging
    to that resource type: `ERR_BREWER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_KEG_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_SERVICE_CYCLE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND`
    or `ERR_INVESTIGATION_NOT_FOUND`."

    PRD: "Every path identifier resolves, left to right — the 404 catalogue
    above."

    Design: Corner/errors/every_path_id_lookup_has_its_own_not_found_code
    """
    seen = []
    for label, read, expected in _eleven_read_by_id_probes():
        response = read(NON_EXISTENT_UUID, OPERATOR)
        assert response.status_code == 404, (
            f"{label}: expected 404, got {response.status_code}"
        )
        error_data = validate_error(response, expected, 404)
        seen.append(error_data["error_id"])

    assert len(set(seen)) == 11, f"the eleven 404 codes must be distinct, got {seen}"


# ==========================================================================
# Design: Corner/errors/the_four_uniqueness_conflicts_are_reported_separately
# ==========================================================================


def _one_brewer_one_index_two_pools_and_one_tagged_keg():
    """Brewer RDG, an index row at 2026-07-01, pool HB-50L holding K-0001 and a
    second empty pool SK-20L — one live value per uniqueness rule."""
    stock = fixtures.setup_pool_with_kegs(
        keg_specs=[{"asset_tag": "K-0001"}], pool_overrides=POOL, clock=CLOCK
    )
    return {
        "index": stock["index"],
        "pool": stock["pool"],
        "keg": stock["kegs"][0],
        "brewer": fixtures.create_brewer(),
        "second_pool": fixtures.create_pool(**SECOND_POOL),
    }


def test_duplicate_brand_code_and_pool_code_are_separate_conflicts():
    """A repeated brand code and a repeated pool code each report their own
    409, even when every other field of the payload differs.

    PRD: "A `PoolOperator` registers a brewing company by supplying its legal
    `name`, between 1 and 120 characters and not blank, and its `brand_code` —
    the collar brand code stamped on the kegs that brewer fills, 2 to 8
    characters drawn from uppercase letters and digits, and unique across every
    brewer on the platform."

    PRD: "A duplicate is refused with `ERR_DUPLICATE_BRAND_CODE`."

    PRD: "A `PoolOperator` creates it with a `pool_code` of 3 to 16 characters,
    unique across all pools and refused with `ERR_DUPLICATE_POOL_CODE` if
    repeated; a `size_liters` that must be one of 20, 30, 50 or 58; a
    `stainless_weight_kg` giving the empty stainless mass of one keg in this
    class, which must be greater than zero, no greater than 60, and carry at
    most two decimal places; a `replacement_cost_cents` greater than zero,
    which is the new-keg cost used as the gross basis of replacement-cost loss
    assessments; and a two-character uppercase `region_code` naming the region
    the pool serves."

    Design: Corner/errors/the_four_uniqueness_conflicts_are_reported_separately
    """
    ctx = _one_brewer_one_index_two_pools_and_one_tagged_keg()

    validate_error(
        api_client.create_brewer(
            factories.create_brewer_payload(
                name="Ridgeline Brewing of Denver", credit_limit_cents=100000
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_DUPLICATE_BRAND_CODE,
        409,
    )
    validate_error(
        api_client.create_pool(
            factories.create_pool_payload(
                replacement_cost_cents=24000, region_code="WY"
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_DUPLICATE_POOL_CODE,
        409,
    )

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["name"] == "Ridgeline Brewing"
    assert brewer["credit_limit_cents"] == 400000
    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["replacement_cost_cents"] == 23500
    assert pool["region_code"] == "CO"


def test_asset_tags_and_index_dates_collide_across_scopes():
    """An asset tag already etched in one pool is unavailable in a second pool,
    a repeated index date is refused, and a fresh tag in that same second pool
    still imports.

    PRD: "Asset tags are unique **globally**, across every pool and not merely
    within one: a tag is etched onto the shell, so the same tag may not be
    reused when a keg is re-homed into a different pool, and a repeat is
    refused with `ERR_DUPLICATE_ASSET_TAG`."

    PRD: "Index rows are immutable and `effective_date` is unique across the
    series, so a correction is posted as a new row under a later date rather
    than as a second row for the same date; a repeat date is refused with
    `ERR_DUPLICATE_INDEX_DATE`."

    PRD: "Importing a physical keg into a pool is the only operation that
    raises `kegs_total`."

    Design: Corner/errors/the_four_uniqueness_conflicts_are_reported_separately
    """
    ctx = _one_brewer_one_index_two_pools_and_one_tagged_keg()
    second_pool_id = ctx["second_pool"]["id"]

    validate_error(
        api_client.import_keg(
            second_pool_id, factories.import_keg_payload("K-0001"), OPERATOR
        ),
        ApiErrorId.ERR_DUPLICATE_ASSET_TAG,
        409,
    )
    validate_error(
        api_client.post_commodity_index(
            factories.commodity_index_payload("2026-07-01", 500), OPERATOR
        ),
        ApiErrorId.ERR_DUPLICATE_INDEX_DATE,
        409,
    )

    rows, meta = validate_paginated(api_client.list_commodity_index(OPERATOR))
    assert meta["total_count"] == 1
    assert rows[0]["usd_cents_per_kg"] == 480

    control = validate_success(
        api_client.import_keg(
            second_pool_id, factories.import_keg_payload("K-9001"), OPERATOR
        ),
        201,
    )
    assert control["asset_tag"] == "K-9001"
    assert control["pool_id"] == second_pool_id

    assert fixtures.read_pool(ctx["pool"]["id"])["kegs_total"] == 1
    assert fixtures.read_pool(second_pool_id)["kegs_total"] == 1


# ==========================================================================
# Design: Corner/errors/stale_expected_keg_version_on_assessment_create_returns_412
# ==========================================================================


def _a_dispatched_keg_holding_an_import_time_version():
    """One keg allocated and dispatched to the brewer, with the `version` the
    operator read back at import kept aside as the stale one."""
    ctx = fixtures.setup_dispatched_float(
        requested_keg_count=1,
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=3,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    keg_id = ctx["allocated_keg_ids"][0]
    ctx["keg_id"] = keg_id
    ctx["import_version"] = next(
        keg for keg in ctx["kegs"] if keg["id"] == keg_id
    )["version"]
    return ctx


def test_import_time_keg_version_is_stale_after_allocation():
    """Replaying the import-time version on an assessment create is 412, and
    none of the later checks in the ladder is reported instead.

    PRD: "Opening a loss assessment requires `expected_keg_version`, carrying
    the client's last observed `version` of the parent `Keg`."

    PRD: "A mismatch is rejected with `ERR_STALE_KEG_VERSION` (HTTP 412)."

    PRD: "Each allocated keg moves `IN_FLOAT → ISSUED_TO_BREWER`, records
    `current_brewer_id` from the agreement and `issuance_order_id` from the
    order, sets `dwell_started_at` to the logical clock, sets `dwell_flag` to
    `WITHIN_LIMIT`, and advances its own `version`."

    PRD: "The `brewer_id` is not supplied: it is resolved as the keg's
    `filling_brewer_id` when that is set, and otherwise as its
    `current_brewer_id`."

    Design: Corner/errors/stale_expected_keg_version_on_assessment_create_returns_412
    """
    ctx = _a_dispatched_keg_holding_an_import_time_version()
    keg_id = ctx["keg_id"]

    current_version = fixtures.keg_version(keg_id)
    assert current_version > ctx["import_version"], (
        "allocation advances the keg's own version, so the import-time "
        f"version {ctx['import_version']} must be behind {current_version}"
    )

    validate_error(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id, "NOT_RETURNED_DWELL", ctx["import_version"]
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_STALE_KEG_VERSION,
        412,
    )

    assert fixtures.read_keg(keg_id)["assessment_open"] is False
    _, meta = validate_paginated(
        api_client.list_loss_assessments(ANALYST, params={"keg_id": keg_id})
    )
    assert meta["total_count"] == 0


def test_the_same_body_succeeds_once_the_keg_version_is_re_read():
    """Re-reading the keg and replaying the identical body opens the
    assessment, which proves only the version guard had refused it.

    PRD: "Opening an assessment takes a `keg_id`, a `cause`, an
    `expected_keg_version` that must equal the keg's current `version` —
    otherwise `ERR_STALE_KEG_VERSION` — and optionally an `assessment_basis`
    and a `theft_investigation_id` when the assessment was raised out of an
    investigation."

    PRD: "The `created_by_user_id` is stamped with the acting `X-User-ID`, the
    assessment opens in `assessment_status` `PROPOSED` with `chargeback_status`
    `NONE`, the keg's `assessment_open` flag is raised, and
    `dwell_days_at_assessment` records the keg's dwell at creation, taken from
    whichever clock is open — the brewer clock when both are."

    Design: Corner/errors/stale_expected_keg_version_on_assessment_create_returns_412
    """
    ctx = _a_dispatched_keg_holding_an_import_time_version()
    keg_id = ctx["keg_id"]

    validate_error(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id, "NOT_RETURNED_DWELL", ctx["import_version"]
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_STALE_KEG_VERSION,
        412,
    )

    assessment = validate_success(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id, "NOT_RETURNED_DWELL", fixtures.keg_version(keg_id)
            ),
            ANALYST,
        ),
        201,
    )
    assert assessment["assessment_status"] == "PROPOSED"
    assert assessment["chargeback_status"] == "NONE"
    assert assessment["created_by_user_id"] == ANALYST_USER_ID
    assert fixtures.read_keg(keg_id)["assessment_open"] is True


# ==========================================================================
# Design: Corner/errors/stale_expected_claim_version_on_respond_returns_412
# ==========================================================================


def _a_countered_claim_and_the_version_the_distributor_first_read():
    """A cross-brand misdelivery claim for 1200 cents, countered at 600 by the
    brewer whose collar was found, with the distributor still holding the
    version it read at submission."""
    ctx = fixtures.setup_open_claim(
        claimed_offset_cents=1200,
        owning_fill_at="2026-08-03T00:00:00Z",
        distribution_at="2026-08-05T00:00:00Z",
        other_brand_code="OAK",
        other_brewer_name="Oakline Ales",
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=2,
        keg_count=2,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_TWO,
        effective_date="2026-08-01",
        clock="2026-08-10T23:00:00Z",
    )
    ctx["stale_version"] = ctx["claim"]["version"]
    ctx["counter"] = fixtures.respond_to_claim(
        ctx["claim"]["id"],
        "COUNTER",
        make_brewer_headers(ctx["other_brewer"]["id"]),
        counter_offset_cents=600,
    )
    return ctx


def test_the_counter_invalidates_the_version_the_distributor_holds():
    """An in-turn AGREE carrying the pre-counter version is 412, not the
    out-of-turn 409, because the version guard is judged first.

    PRD: "Every subsequent move is a single response carrying a `response` of
    `COUNTER`, `AGREE`, `REJECT` or `WITHDRAW`, an `expected_claim_version`
    that must equal the claim's current `version` — otherwise
    `ERR_STALE_CLAIM_VERSION` — and, for a counter, a `counter_offset_cents`."

    PRD: "Second, turn-taking: the claim's `last_responder_role` must differ
    from the acting role, so the same side can never move twice in a row; a
    distributor trying to counter its own outstanding counter is
    `ERR_RESPONDER_OUT_OF_TURN`."

    PRD: "The supplied `expected_agreement_version`, `expected_keg_version` or
    `expected_claim_version` matches its parent's current `version` —
    `ERR_STALE_AGREEMENT_VERSION`, `ERR_STALE_KEG_VERSION` or
    `ERR_STALE_CLAIM_VERSION` (412)."

    PRD: "A `COUNTER` flips the claim between the two live states and
    increments `round_count`: from `SUBMITTED` the brewer counters into
    `COUNTERED`, and from `COUNTERED` the distributor counters back into
    `SUBMITTED`, each time overwriting `counter_offset_cents` with the new
    figure and stamping `last_responder_role` with the side that just moved."

    Design: Corner/errors/stale_expected_claim_version_on_respond_returns_412
    """
    ctx = _a_countered_claim_and_the_version_the_distributor_first_read()
    claim_id = ctx["claim"]["id"]

    validate_error(
        api_client.respond_reconciliation_claim(
            claim_id,
            factories.claim_response_payload("AGREE", ctx["stale_version"]),
            make_distributor_headers(ctx["distributor"]["id"]),
        ),
        ApiErrorId.ERR_STALE_CLAIM_VERSION,
        412,
    )

    claim = fixtures.read_claim(claim_id)
    assert claim["status"] == "COUNTERED"
    assert claim["round_count"] == 1
    assert claim["counter_offset_cents"] == 600
    assert claim["agreed_offset_cents"] is None
    assert claim["last_responder_role"] == "Brewer"


def test_the_re_read_version_agrees_to_the_outstanding_counter():
    """The replayed AGREE fixes the agreed figure to the outstanding counter
    and mints a reconciliation offset that moves no return history.

    PRD: "The claim moves to `AGREED`, `closed_at` is stamped with the logical
    clock, and `agreed_offset_cents` is fixed to whichever figure was
    outstanding: the `counter_offset_cents` when a counter had been made, and
    the original `claimed_offset_cents` when the brewer simply accepted the
    opening claim."

    PRD: "A `ReturnIncentiveAccrual` of `accrual_type` `RECONCILIATION_OFFSET`
    is then minted for the claimant with `claim_id` set to this claim,
    `incentive_cents` equal to `agreed_offset_cents`, and `status` `ACCRUED`;
    the distributor's `incentive_accrual_cents` grows by that amount."

    PRD: "Crucially, a reconciliation offset is **not** a return:
    `total_returns_count`, `on_time_returns_count`, `on_time_return_pct`,
    `avg_dwell_days` and `cooperation_tier` are all left exactly as they were,
    and no tier promotion is evaluated."

    PRD: "Finally the keg's `misdelivery_open` flag is cleared and the keg's
    `version` advances."

    Design: Corner/errors/stale_expected_claim_version_on_respond_returns_412
    """
    ctx = _a_countered_claim_and_the_version_the_distributor_first_read()
    claim_id = ctx["claim"]["id"]
    distributor_id = ctx["distributor"]["id"]
    tier_before = fixtures.read_distributor(distributor_id)["cooperation_tier"]

    validate_error(
        api_client.respond_reconciliation_claim(
            claim_id,
            factories.claim_response_payload("AGREE", ctx["stale_version"]),
            make_distributor_headers(distributor_id),
        ),
        ApiErrorId.ERR_STALE_CLAIM_VERSION,
        412,
    )

    agreed = validate_success(
        api_client.respond_reconciliation_claim(
            claim_id,
            factories.claim_response_payload(
                "AGREE", fixtures.claim_version(claim_id)
            ),
            make_distributor_headers(distributor_id),
        )
    )
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_offset_cents"] == 600
    assert agreed["closed_at"] == "2026-08-10T23:00:00Z"

    accruals, meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR,
            params={
                "distributor_id": distributor_id,
                "accrual_type": "RECONCILIATION_OFFSET",
            },
        )
    )
    assert meta["total_count"] == 1
    assert accruals[0]["incentive_cents"] == 600
    assert accruals[0]["status"] == "ACCRUED"
    assert accruals[0]["claim_id"] == claim_id

    distributor = fixtures.read_distributor(distributor_id)
    assert distributor["incentive_accrual_cents"] == 600
    assert distributor["total_returns_count"] == 0
    assert distributor["on_time_return_pct"] == 0.00
    assert distributor["cooperation_tier"] == tier_before

    assert fixtures.read_keg(ctx["keg_id"])["misdelivery_open"] is False


# ==========================================================================
# Design: Corner/errors/suspended_distributor_cannot_record_a_return_scan
# ==========================================================================


def _an_in_trade_keg_whose_distributor_was_then_suspended():
    """A keg handed to a BRONZE distributor on 2026-08-03, whose standing is
    then moved to SUSPENDED through a second cooperation-agreement write."""
    ctx = fixtures.setup_keg_in_trade(
        fill_scanned_at="2026-08-03T00:00:00Z",
        distribution_scanned_at="2026-08-03T00:00:00Z",
        cooperation_tier="BRONZE",
        cooperation_effective_date="2026-08-01",
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=2,
        keg_count=2,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_TWO,
        effective_date="2026-08-01",
        clock="2026-08-05T23:00:00Z",
    )
    fixtures.sign_cooperation_agreement(
        ctx["distributor"]["id"], "BRONZE", "2026-08-01", status="SUSPENDED"
    )
    return ctx


def _return_scan_attempt(ctx):
    return api_client.scan_keg(
        ctx["keg_id"],
        factories.return_scan_payload(
            ctx["distributor"]["id"],
            "2026-08-05T00:00:00Z",
            ctx["brewer"]["brand_code"],
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )


def test_a_suspended_distributor_is_refused_the_return_it_may_legally_make():
    """The return is legal for a keg in trade and the actor is a known
    distributor, yet suspension refuses it and mints nothing.

    PRD: "The distributor's `status` is not `SUSPENDED` —
    `ERR_DISTRIBUTOR_SUSPENDED` (409), on a distribution or return scan and on
    an accrual payment."

    PRD: "The `party_type` must be `DISTRIBUTOR`, the supplied
    `distributor_id` must equal the keg's `current_distributor_id`, and that
    distributor must not be `SUSPENDED`."

    PRD: "Legality of the movement is judged against the keg's current
    `custody_state`, and this is the only check that judges it: a `FILL` is
    legal only from `ISSUED_TO_BREWER`, a `DISTRIBUTION` only from `FILLED`, a
    `RETAIL` only from `IN_TRADE`, and a `RETURN` only from either `IN_TRADE`
    or `AT_RETAIL`."

    PRD: "Signing or revising a **cooperation agreement** is how a distributor
    enters the incentive scheme."

    PRD: "The operator supplies the new `cooperation_tier` and the
    `effective_date` on which it takes effect, and may optionally revise
    `return_incentive_rate_cents_per_keg` or the distributor's `status` in the
    same call."

    Design: Corner/errors/suspended_distributor_cannot_record_a_return_scan
    """
    ctx = _an_in_trade_keg_whose_distributor_was_then_suspended()

    validate_error(
        _return_scan_attempt(ctx), ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409
    )

    assert fixtures.read_keg(ctx["keg_id"])["custody_state"] == "IN_TRADE"
    _, meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": ctx["distributor"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.read_distributor(ctx["distributor"]["id"])["total_returns_count"] == 0


def test_reactivating_the_distributor_lets_the_identical_return_mint_its_accrual():
    """Once the standing is ACTIVE again the same scan is accepted, closing a
    two-day accountability spell worth the full base rate.

    PRD: "The keg moves `IN_TRADE → IN_SERVICE` or `AT_RETAIL → IN_SERVICE`,
    the custody spell closes, `dwell_started_at` resets to `scanned_at`, and
    `distributor_custody_started_at` is cleared."

    PRD: "That closed spell mints a `ReturnIncentiveAccrual` of `accrual_type`
    `RETURN_DWELL`, which records `distributor_id`, `keg_id`, the `dwell_days`
    it closed, the band factor `tier_pct_bp`, the tier factor
    `cooperation_multiplier_bp`, the resulting `incentive_cents`, and
    `triggering_scanned_at` set to the return scan's `scanned_at`; its
    `claim_id` is unset, its `status` opens at `ACCRUED`, and `paid_at` and
    `clawback_reason` are unset."

    PRD: "A scan's `dwell_days_closed` is the brewer clock read at that scan's
    `scanned_at`, and the keg's `cumulative_dwell_days` is the sum of
    `dwell_days_closed` across all its scans."

    PRD: "A return accrual's `dwell_days` is the distributor clock read at that
    same instant."

    PRD: "The operator may supply `return_incentive_rate_cents_per_keg`, the
    base per-keg return incentive before any dwell band or cooperation
    multiplier is applied; it defaults to 250 cents and must lie between 0 and
    2000 inclusive."

    PRD: "The dwell band factor is 10000 basis points when the accountability
    spell closed in 14 days or fewer, 6000 basis points from 15 through 29
    days, 2500 basis points from 30 through 44 days, and 0 basis points at 45
    days or more — so a keg returned outside the 45-day distributor allowance
    earns nothing."

    PRD: "The cooperation factor is 0 basis points for a `NONE`-tier
    distributor, 10000 for `BRONZE`, 11500 for `SILVER` and 13000 for `GOLD`,
    taken from the tier as it stands *at the moment of this scan*."

    PRD: "The accrual's `incentive_cents` is the base rate multiplied by the
    band factor as a proportion of 10000, multiplied by the cooperation factor
    as a proportion of 10000, rounded half up to whole cents — and that
    rounding happens once, on this one row, before any summation."

    PRD: "Then the counters are recomputed *including* the accrual just minted:
    `total_returns_count` is the number of `RETURN_DWELL` accruals of this
    distributor in `ACCRUED`, `PAID` or `CLAWED_BACK`; `on_time_returns_count`
    is the subset of those whose `dwell_days` is 45 or fewer;
    `on_time_return_pct` is 0.00 when the total is zero and otherwise the
    on-time count divided by the total, multiplied by 100, rounded half up to
    two decimals; and `avg_dwell_days` is 0.00 when the set is empty and
    otherwise the mean of `dwell_days` across that set, rounded half up to two
    decimals."

    PRD: "Third, at most **one** step up the ladder is applied and no step may
    be skipped: a `BRONZE` distributor becomes `SILVER` when its total is at
    least 3 returns and its on-time percentage is at least 90.00, and a
    `SILVER` distributor becomes `GOLD` when its total is at least 5 returns
    and its on-time percentage is at least 96.00, recording
    `cooperation_effective_date` as the current logical date in either case."

    Design: Corner/errors/suspended_distributor_cannot_record_a_return_scan
    """
    ctx = _an_in_trade_keg_whose_distributor_was_then_suspended()
    distributor_id = ctx["distributor"]["id"]

    validate_error(
        _return_scan_attempt(ctx), ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409
    )

    reactivated = fixtures.sign_cooperation_agreement(
        distributor_id, "BRONZE", "2026-08-01", status="ACTIVE"
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["cooperation_tier"] == "BRONZE"

    scan = validate_success(_return_scan_attempt(ctx), 201)
    assert scan["custody_state_after"] == "IN_SERVICE"
    assert scan["dwell_days_closed"] == 2
    assert fixtures.read_keg(ctx["keg_id"])["custody_state"] == "IN_SERVICE"

    accruals, meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": distributor_id}
        )
    )
    assert meta["total_count"] == 1
    accrual = accruals[0]
    assert accrual["accrual_type"] == "RETURN_DWELL"
    assert accrual["dwell_days"] == 2
    assert accrual["tier_pct_bp"] == 10000
    assert accrual["cooperation_multiplier_bp"] == 10000
    assert accrual["incentive_cents"] == 250
    assert accrual["status"] == "ACCRUED"

    distributor = fixtures.read_distributor(distributor_id)
    assert distributor["incentive_accrual_cents"] == 250
    assert distributor["total_returns_count"] == 1
    assert distributor["on_time_return_pct"] == 100.00
    assert distributor["avg_dwell_days"] == 2.00
    assert distributor["cooperation_tier"] == "BRONZE"


# ==========================================================================
# Design: Corner/errors/major_defect_quarantine_can_never_be_retested_into_float
# ==========================================================================


def _one_cycle_quarantined_by_a_defect_and_one_by_a_failed_test():
    """Two kegs booked into the same centre six hours apart, one quarantined by
    a major inspection defect and one by a failing pressure test."""
    stock = fixtures.setup_pool_with_kegs(
        keg_specs=[
            {"asset_tag": "K-BAD1", "initial_custody_state": "IN_SERVICE"},
            {"asset_tag": "K-BAD2", "initial_custody_state": "IN_SERVICE"},
        ],
        pool_overrides=POOL,
        clock=CLOCK,
    )
    center = fixtures.create_service_center(4, intake_buffer_hours=4)

    defect = fixtures.create_service_cycle(
        stock["kegs"][0]["id"], center["id"], "2026-08-01T10:00:00Z"
    )
    fixtures.record_clean(defect["id"], "2026-08-01T11:00:00Z", caustic_cycle_minutes=14)
    defect = fixtures.record_inspect(
        defect["id"], "2026-08-01T12:00:00Z", inspection_result="MAJOR_DEFECT"
    )

    failed = fixtures.create_service_cycle(
        stock["kegs"][1]["id"], center["id"], "2026-08-01T16:00:00Z"
    )
    fixtures.record_clean(failed["id"], "2026-08-01T17:00:00Z", caustic_cycle_minutes=14)
    fixtures.record_inspect(failed["id"], "2026-08-01T18:00:00Z")
    failed = fixtures.record_pressure_test(
        failed["id"],
        "2026-08-01T19:00:00Z",
        pressure_test_psi=34,
        pressure_test_result="FAIL",
    )

    return {
        "center": center,
        "defect_cycle": defect,
        "defect_keg_id": stock["kegs"][0]["id"],
        "failed_cycle": failed,
        "failed_keg_id": stock["kegs"][1]["id"],
    }


def test_a_major_defect_quarantine_refuses_the_retest_the_stage_table_allows():
    """The retest reaches the quarantine rule because the stage edge exists, and
    is then refused on the quarantine reason alone.

    PRD: "**`PRESSURE_TEST`** requires `stage` `INSPECTED`, or `stage`
    `QUARANTINED` with a `quarantine_reason` of `PRESSURE_TEST_FAIL` for the
    retest loop."

    PRD: "A result of `MAJOR_DEFECT` diverts the cycle to `QUARANTINED` with
    `quarantine_reason` recorded as `INSPECTION_MAJOR_DEFECT`, and moves the keg
    to custody `QUARANTINED` with `service_state` `SERVICE_FAILED`."

    PRD: "A cycle quarantined for `INSPECTION_MAJOR_DEFECT` may never be
    retested and may never be released: a structural defect cannot be argued
    away by a pressure gauge, and the keg must be scrapped through a damage
    assessment instead."

    PRD: "Both a retest and a release attempt on such a cycle are refused with
    `ERR_QUARANTINE_RELEASE_BLOCKED`."

    Design: Corner/errors/major_defect_quarantine_can_never_be_retested_into_float
    """
    ctx = _one_cycle_quarantined_by_a_defect_and_one_by_a_failed_test()

    validate_error(
        api_client.record_service_step(
            ctx["defect_cycle"]["id"],
            factories.pressure_test_step_payload(
                "2026-08-01T20:00:00Z", pressure_test_psi=42, pressure_test_result="PASS"
            ),
            TECH,
        ),
        ApiErrorId.ERR_QUARANTINE_RELEASE_BLOCKED,
        409,
    )

    cycle = fixtures.read_cycle(ctx["defect_cycle"]["id"])
    assert cycle["stage"] == "QUARANTINED"
    assert cycle["quarantine_reason"] == "INSPECTION_MAJOR_DEFECT"
    assert cycle["pressure_test_psi"] is None
    assert cycle["pressure_test_result"] is None

    keg = fixtures.read_keg(ctx["defect_keg_id"])
    assert keg["custody_state"] == "QUARANTINED"
    assert keg["service_state"] == "SERVICE_FAILED"


def test_a_pressure_fail_quarantine_accepts_the_identical_retest():
    """The same step on the sibling cycle passes, and neither the refusal nor
    the accepted retest releases an occupancy slot.

    PRD: "A cycle quarantined for `PRESSURE_TEST_FAIL` may be retested, and a
    passing retest overwrites the failed pressure fields and moves the keg from
    custody `QUARANTINED` back to `IN_SERVICE`."

    PRD: "With an adequate pressure, a `pressure_test_result` of `PASS`
    advances the stage to `PRESSURE_TESTED`, records `pressure_tested_at` and
    stamps `pressure_test_performed_by_user_id` with the acting `X-User-ID`,
    while a `FAIL` diverts to `QUARANTINED` with `quarantine_reason`
    `PRESSURE_TEST_FAIL` and sets the keg's `service_state` to
    `SERVICE_FAILED`."

    PRD: "A `ServiceCenter` is created with a `name`, a two-letter
    `region_code`, a `concurrent_cycle_capacity` between 1 and 50, and an
    `intake_buffer_hours` between 0 and 48 that defaults to 4; its
    `open_cycle_count` starts at 0 and is thereafter derived as the number of
    that centre's cycles whose `stage` is `RECEIVED`, `CLEANED`, `INSPECTED`,
    `PRESSURE_TESTED` or `QUARANTINED`."

    Design: Corner/errors/major_defect_quarantine_can_never_be_retested_into_float
    """
    ctx = _one_cycle_quarantined_by_a_defect_and_one_by_a_failed_test()

    validate_error(
        api_client.record_service_step(
            ctx["defect_cycle"]["id"],
            factories.pressure_test_step_payload(
                "2026-08-01T20:00:00Z", pressure_test_psi=42, pressure_test_result="PASS"
            ),
            TECH,
        ),
        ApiErrorId.ERR_QUARANTINE_RELEASE_BLOCKED,
        409,
    )

    retested = validate_success(
        api_client.record_service_step(
            ctx["failed_cycle"]["id"],
            factories.pressure_test_step_payload(
                "2026-08-01T21:00:00Z", pressure_test_psi=42, pressure_test_result="PASS"
            ),
            SECOND_TECH,
        )
    )
    assert retested["stage"] == "PRESSURE_TESTED"
    assert retested["pressure_test_result"] == "PASS"
    assert retested["pressure_test_psi"] == 42
    assert retested["pressure_test_performed_by_user_id"] == SECOND_TECHNICIAN_USER_ID
    assert fixtures.read_keg(ctx["failed_keg_id"])["custody_state"] == "IN_SERVICE"

    center = validate_success(
        api_client.get_service_center(ctx["center"]["id"], OPERATOR)
    )
    assert center["open_cycle_count"] == 2


# ==========================================================================
# Design: Corner/errors/a_disputed_assessment_blocks_a_second_one_while_a_proposed_one_is_superseded
# ==========================================================================


def _a_filled_keg_carrying_one_proposed_assessment():
    """A keg filled once under a chargeable brewer, with a first assessment
    standing in PROPOSED."""
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-01T12:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=1,
        float_size_kegs=3,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["first"] = fixtures.open_loss_assessment(
        ctx["keg_id"], "LOST_IN_TRADE", assessment_basis="REPLACEMENT_COST"
    )
    return ctx


def _open_second_assessment(keg_id):
    return api_client.create_loss_assessment(
        factories.create_loss_assessment_payload(
            keg_id,
            "NOT_RETURNED_DWELL",
            fixtures.keg_version(keg_id),
            assessment_basis="REPLACEMENT_COST",
        ),
        ANALYST,
    )


def test_a_second_assessment_supersedes_a_merely_proposed_one():
    """Opening a second assessment while the first is PROPOSED is accepted and
    silently supersedes the first, keeping the keg flagged.

    PRD: "A keg may carry only one live assessment, but the two live states
    behave differently."

    PRD: "Opening a second assessment on the same keg while the first is still
    `PROPOSED` is legitimate — the prior assessment moves to `SUPERSEDED`, its
    `version` advances, the new one is created in `PROPOSED` and the keg's
    `assessment_open` stays true — but opening one while an existing assessment
    is `DISPUTED` is refused with `ERR_ASSESSMENT_ALREADY_OPEN`."

    PRD: "A newer assessment legitimately supersedes a proposed one when fresh
    evidence arrives, so the second create is not blocked by a state
    precondition; the stale-version check is what stops an analyst from valuing
    a keg that has meanwhile been returned, quarantined or attached to a theft
    investigation."

    PRD: "Under **`REPLACEMENT_COST`**, `gross_value_cents` is simply the
    pool's `replacement_cost_cents`, and `fill_count` is ignored entirely."

    PRD: "`brewer_liability_pct_bp` is keyed off the cause alone: 6000 basis
    points for `LOST_IN_TRADE`, 10000 for `DAMAGED_BEYOND_REPAIR`, 10000 for
    `NOT_RETURNED_DWELL` and 0 for `STOLEN_SUSPECTED`."

    Design: Corner/errors/a_disputed_assessment_blocks_a_second_one_while_a_proposed_one_is_superseded
    """
    ctx = _a_filled_keg_carrying_one_proposed_assessment()

    second = validate_success(_open_second_assessment(ctx["keg_id"]), 201)
    assert second["assessment_status"] == "PROPOSED"

    first = fixtures.read_assessment(ctx["first"]["id"])
    assert first["assessment_status"] == "SUPERSEDED"
    assert first["chargeback_status"] == "NONE"
    assert fixtures.read_keg(ctx["keg_id"])["assessment_open"] is True

    assert first["gross_value_cents"] == 23500
    assert first["brewer_liability_pct_bp"] == 6000
    assert second["gross_value_cents"] == 23500
    assert second["brewer_liability_pct_bp"] == 10000


def test_a_disputed_assessment_blocks_the_next_create_outright():
    """Once the live assessment is DISPUTED the identical create is refused and
    writes nothing.

    PRD: "A brewer may **dispute** a `PROPOSED` assessment by supplying a
    `dispute_reason`, with the acting `X-User-ID` required to equal the
    assessment's `brewer_id`; this moves `assessment_status` to `DISPUTED` and
    leaves `assessment_open` raised."

    PRD: "Opening a second assessment on the same keg while the first is still
    `PROPOSED` is legitimate — the prior assessment moves to `SUPERSEDED`, its
    `version` advances, the new one is created in `PROPOSED` and the keg's
    `assessment_open` stays true — but opening one while an existing assessment
    is `DISPUTED` is refused with `ERR_ASSESSMENT_ALREADY_OPEN`."

    PRD: "A keg does not carry a second open assessment while an existing one
    is `DISPUTED` — `ERR_ASSESSMENT_ALREADY_OPEN` (409)."

    Design: Corner/errors/a_disputed_assessment_blocks_a_second_one_while_a_proposed_one_is_superseded
    """
    ctx = _a_filled_keg_carrying_one_proposed_assessment()
    keg_id = ctx["keg_id"]

    second = validate_success(_open_second_assessment(keg_id), 201)
    disputed = fixtures.dispute_assessment(
        second["id"],
        ctx["brewer"]["id"],
        "Keg was collected by the distributor; scan was missed.",
    )
    assert disputed["assessment_status"] == "DISPUTED"
    assert disputed["dispute_reason"] == (
        "Keg was collected by the distributor; scan was missed."
    )

    validate_error(
        _open_second_assessment(keg_id), ApiErrorId.ERR_ASSESSMENT_ALREADY_OPEN, 409
    )

    rows, meta = validate_paginated(
        api_client.list_loss_assessments(ANALYST, params={"keg_id": keg_id})
    )
    assert meta["total_count"] == 2
    assert fixtures.read_assessment(second["id"])["assessment_status"] == "DISPUTED"
    assert {row["assessment_status"] for row in rows} == {"SUPERSEDED", "DISPUTED"}


# ==========================================================================
# Design: Corner/errors/an_accrual_can_only_be_paid_once
# ==========================================================================


def _one_accrued_return_incentive():
    """A two-day return by a BRONZE distributor, which mints exactly one
    ACCRUED accrual of the full base rate."""
    return fixtures.setup_returned_keg(
        return_scanned_at="2026-08-05T00:00:00Z",
        fill_scanned_at="2026-08-03T00:00:00Z",
        distribution_scanned_at="2026-08-03T00:00:00Z",
        cooperation_tier="BRONZE",
        cooperation_effective_date="2026-08-01",
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=2,
        keg_count=2,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_TWO,
        effective_date="2026-08-01",
        clock="2026-08-05T23:00:00Z",
    )


def test_paying_an_accrual_moves_the_status_but_not_the_ledger():
    """The accrual opens ACCRUED with its claim reference unset, and paying it
    records the instant without moving the incentive ledger.

    PRD: "That closed spell mints a `ReturnIncentiveAccrual` of `accrual_type`
    `RETURN_DWELL`, which records `distributor_id`, `keg_id`, the `dwell_days`
    it closed, the band factor `tier_pct_bp`, the tier factor
    `cooperation_multiplier_bp`, the resulting `incentive_cents`, and
    `triggering_scanned_at` set to the return scan's `scanned_at`; its
    `claim_id` is unset, its `status` opens at `ACCRUED`, and `paid_at` and
    `clawback_reason` are unset."

    PRD: "A `PoolOperator` remits an accrual by supplying `paid_at`; the accrual
    must be in `ACCRUED`, otherwise `ERR_ACCRUAL_NOT_PAYABLE`, and the earning
    distributor must not be `SUSPENDED`."

    PRD: "The accrual moves to `PAID` and records `paid_at`, while the
    distributor's `incentive_accrual_cents` is deliberately **unchanged**,
    because paid rows stay inside the ledger sum."

    Design: Corner/errors/an_accrual_can_only_be_paid_once
    """
    ctx = _one_accrued_return_incentive()
    accrual = fixtures.read_accrual(ctx["accrual"]["id"])
    assert accrual["status"] == "ACCRUED"
    assert accrual["accrual_type"] == "RETURN_DWELL"
    assert accrual["incentive_cents"] == 250
    assert accrual["dwell_days"] == 2
    assert accrual["keg_id"] == ctx["keg_id"]
    assert accrual["claim_id"] is None
    assert accrual["paid_at"] is None

    paid = validate_success(
        api_client.pay_return_incentive(
            accrual["id"], {"paid_at": "2026-08-05T20:00:00Z"}, OPERATOR
        )
    )
    assert paid["status"] == "PAID"
    assert paid["paid_at"] == "2026-08-05T20:00:00Z"
    assert (
        fixtures.read_distributor(ctx["distributor"]["id"])["incentive_accrual_cents"]
        == 250
    )


def test_a_second_payment_is_a_payability_refusal_that_restamps_nothing():
    """The second payment is refused as unpayable rather than as terminal, and
    it neither re-stamps the instant nor double-counts the ledger.

    PRD: "A `PoolOperator` remits an accrual by supplying `paid_at`; the accrual
    must be in `ACCRUED`, otherwise `ERR_ACCRUAL_NOT_PAYABLE`, and the earning
    distributor must not be `SUSPENDED`."

    PRD: "An accrual is only payable from `ACCRUED` —
    `ERR_ACCRUAL_NOT_PAYABLE` (409)."

    PRD: "The distributor's `incentive_accrual_cents` is then the sum of the
    already-rounded `incentive_cents` across its accruals in `ACCRUED` or
    `PAID`."

    Design: Corner/errors/an_accrual_can_only_be_paid_once
    """
    ctx = _one_accrued_return_incentive()
    accrual_id = ctx["accrual"]["id"]
    fixtures.pay_accrual(accrual_id, "2026-08-05T20:00:00Z")

    validate_error(
        api_client.pay_return_incentive(
            accrual_id, {"paid_at": "2026-08-05T22:00:00Z"}, OPERATOR
        ),
        ApiErrorId.ERR_ACCRUAL_NOT_PAYABLE,
        409,
    )

    accrual = fixtures.read_accrual(accrual_id)
    assert accrual["status"] == "PAID"
    assert accrual["paid_at"] == "2026-08-05T20:00:00Z"
    assert (
        fixtures.read_distributor(ctx["distributor"]["id"])["incentive_accrual_cents"]
        == 250
    )


# ==========================================================================
# Design: Corner/errors/an_unknown_collar_brand_is_refused_differently_at_fill_and_at_distribution
# ==========================================================================


def _two_kegs_at_the_brewer_one_of_them_filled():
    """A two-keg dispatch where the first keg is already filled under the
    brewer's own collar and the second is still waiting to be filled."""
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-03T00:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=2,
        float_size_kegs=2,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock="2026-08-05T23:00:00Z",
    )
    ctx["unfilled_keg_id"] = ctx["allocated_keg_ids"][1]
    return ctx


def _scan_count(keg_id, scan_point=None):
    params = {"keg_id": keg_id}
    if scan_point is not None:
        params["scan_point"] = scan_point
    _, meta = validate_paginated(api_client.list_scan_events(OPERATOR, params=params))
    return meta["total_count"]


def test_an_unknown_collar_at_distribution_is_an_unattributable_owner():
    """A distribution collar that names no brewer at all is refused as an
    unknown owner, and the identical scan under the real collar is accepted
    without any misdelivery.

    PRD: "On any distribution, retail or return scan the `brand_code_scanned`
    must resolve to some existing brewer's `brand_code`, otherwise a
    misdelivery could not be attributed to an owner and the scan is refused
    with `ERR_BRAND_OWNER_UNKNOWN`."

    PRD: "Misdelivery detection then runs on those same three scan points: when
    `brand_code_scanned` differs from the keg's stored `filled_brand_code`, the
    scan records `misdelivery_detected` as true and the keg's `misdelivery_open`
    flag is raised."

    PRD: "The keg moves `FILLED → IN_TRADE`, records `current_distributor_id`,
    and opens a fresh distributor accountability spell by setting
    `distributor_custody_started_at` to the scan's `scanned_at`."

    Design: Corner/errors/an_unknown_collar_brand_is_refused_differently_at_fill_and_at_distribution
    """
    ctx = _two_kegs_at_the_brewer_one_of_them_filled()
    keg_id = ctx["keg_id"]
    distributor = fixtures.create_distributor()
    payload = factories.distribution_scan_payload(
        distributor["id"], "2026-08-04T00:00:00Z", "ZZZ"
    )

    validate_error(
        api_client.scan_keg(
            keg_id, payload, make_distributor_headers(distributor["id"])
        ),
        ApiErrorId.ERR_BRAND_OWNER_UNKNOWN,
        422,
    )
    assert _scan_count(keg_id, "DISTRIBUTION") == 0
    assert _scan_count(keg_id) == 1
    assert fixtures.read_keg(keg_id)["custody_state"] == "FILLED"

    accepted = fixtures.distribution_scan(
        keg_id,
        distributor["id"],
        "2026-08-04T00:00:00Z",
        ctx["brewer"]["brand_code"],
    )
    assert accepted["misdelivery_detected"] is False
    keg = fixtures.read_keg(keg_id)
    assert keg["custody_state"] == "IN_TRADE"
    assert keg["distributor_custody_started_at"] == "2026-08-04T00:00:00Z"
    assert keg["misdelivery_open"] is False


def test_an_unknown_collar_at_fill_is_a_brand_mismatch_that_bills_nothing():
    """The same unknown collar on a fill is judged against the filling brewer's
    own brand instead, so it reports a mismatch and leaves the billing ledger
    exactly where the accepted fill left it.

    PRD: "A fill scan's `brand_code_scanned` equals the filling brewer's
    `brand_code` — `ERR_BRAND_MISMATCH` (422)."

    PRD: "Fills never trigger misdelivery detection — they define the brand
    instead."

    PRD: "Rejected scans leave the ledger untouched."

    Design: Corner/errors/an_unknown_collar_brand_is_refused_differently_at_fill_and_at_distribution
    """
    ctx = _two_kegs_at_the_brewer_one_of_them_filled()
    brewer_id = ctx["brewer"]["id"]
    unfilled = ctx["unfilled_keg_id"]
    fills_before = fixtures.read_keg(unfilled)["fill_count"]

    validate_error(
        api_client.scan_keg(
            unfilled,
            factories.fill_scan_payload(brewer_id, "2026-08-04T00:00:00Z", "ZZZ"),
            make_brewer_headers(brewer_id),
        ),
        ApiErrorId.ERR_BRAND_MISMATCH,
        422,
    )

    assert _scan_count(unfilled) == 0
    keg = fixtures.read_keg(unfilled)
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["fill_count"] == fills_before
    assert keg["filled_brand_code"] is None
    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_fills_count"] == 1
    assert agreement["billed_amount_cents"] == 2200


# ==========================================================================
# Design: Corner/errors/a_future_timestamp_is_refused_on_every_endpoint_that_accepts_one
# ==========================================================================

NOON_CLOCK = "2026-08-05T12:00:00Z"
TOMORROW = "2026-08-06T00:00:00Z"


def _a_float_pinned_to_a_midday_clock():
    """A three-keg pool with one filled keg, one keg still on the float and a
    logical clock parked at midday so that the next day is unambiguously
    in the future."""
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-03T00:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=1,
        float_size_kegs=3,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock=NOON_CLOCK,
    )
    return ctx


def _a_second_order_allocated_but_not_dispatched(ctx):
    order = fixtures.create_order(ctx["agreement"]["id"], 1)
    fixtures.allocate_order(order["id"], ctx["agreement"]["id"])
    return fixtures.read_order(order["id"])


def _a_keg_still_on_the_float(ctx, *taken):
    for keg in ctx["kegs"]:
        if keg["id"] not in ctx["allocated_keg_ids"] and keg["id"] not in taken:
            return keg["id"]
    raise AssertionError("the pool was seeded with no spare float keg")


def test_all_four_instant_bearing_endpoints_refuse_tomorrow():
    """A dispatch, a fill scan, a service booking and an agreement activation
    all reject an instant beyond the logical clock with the same code, and none
    of them leaves a trace behind.

    PRD: "No supplied instant or date lies in the future —
    `ERR_SCAN_TIMESTAMP_FUTURE` (422), on a scan, a service-cycle booking, an
    order dispatch, an investigation status change and an agreement
    activation."

    PRD: "Rejected scans leave the ledger untouched."

    Design: Corner/errors/a_future_timestamp_is_refused_on_every_endpoint_that_accepts_one
    """
    ctx = _a_float_pinned_to_a_midday_clock()
    brewer_id = ctx["brewer"]["id"]

    order = _a_second_order_allocated_but_not_dispatched(ctx)
    validate_error(
        api_client.dispatch_issuance_order(
            order["id"], {"dispatched_at": TOMORROW}, OPERATOR
        ),
        ApiErrorId.ERR_SCAN_TIMESTAMP_FUTURE,
        422,
    )
    reread_order = fixtures.read_order(order["id"])
    assert reread_order["status"] == "ALLOCATED"
    assert reread_order["dispatched_at"] is None

    second_keg = order["allocated_keg_ids"][0]
    fixtures.dispatch_order(order["id"], "2026-08-05T00:00:00Z")
    fills_before = fixtures.read_keg(second_keg)["fill_count"]
    validate_error(
        api_client.scan_keg(
            second_keg,
            factories.fill_scan_payload(
                brewer_id, TOMORROW, ctx["brewer"]["brand_code"]
            ),
            make_brewer_headers(brewer_id),
        ),
        ApiErrorId.ERR_SCAN_TIMESTAMP_FUTURE,
        422,
    )
    assert _scan_count(second_keg) == 0
    assert fixtures.read_keg(second_keg)["fill_count"] == fills_before

    float_keg = _a_keg_still_on_the_float(ctx, second_keg)
    center = fixtures.create_service_center(concurrent_cycle_capacity=4)
    validate_error(
        api_client.create_service_cycle(
            factories.create_service_cycle_payload(
                float_keg, center["id"], TOMORROW
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_SCAN_TIMESTAMP_FUTURE,
        422,
    )
    assert fixtures.read_keg(float_keg)["custody_state"] == "IN_FLOAT"
    assert (
        validate_success(api_client.get_service_center(center["id"], OPERATOR))[
            "open_cycle_count"
        ]
        == 0
    )

    other_brewer = fixtures.create_brewer(name="Foothills Brewing", brand_code="FHB")
    draft = fixtures.create_agreement(other_brewer["id"], ctx["pool"]["id"], 1)
    validate_error(
        api_client.activate_float_agreement(
            draft["id"], {"effective_date": "2026-08-06"}, OPERATOR
        ),
        ApiErrorId.ERR_SCAN_TIMESTAMP_FUTURE,
        422,
    )
    reread_agreement = fixtures.read_agreement(draft["id"])
    assert reread_agreement["status"] == "DRAFT"
    assert reread_agreement["effective_date"] is None


def test_an_instant_exactly_at_the_clock_is_not_yet_the_future():
    """The refusal is strictly about instants beyond the clock: a fill and a
    booking recorded at exactly the clock are accepted and post their full
    effects.

    PRD: "No supplied instant or date lies in the future —
    `ERR_SCAN_TIMESTAMP_FUTURE` (422), on a scan, a service-cycle booking, an
    order dispatch, an investigation status change and an agreement
    activation."

    PRD: "An accepted fill appends the scan, raises the keg's `fill_count` by
    one, records `filled_brand_code` from `brand_code_scanned` and
    `filling_brewer_id` from `brewer_id`, closes the open custody spell in the
    manner described above, resets `dwell_started_at` to `scanned_at`, and
    clears `misdelivery_open` — refilling a keg is what settles any
    unreconciled cross-brand history on it."

    PRD: "Booking a keg onto a line creates a `ServiceCycle` from a `keg_id`, a
    `service_center_id` and a `received_at`."

    Design: Corner/errors/a_future_timestamp_is_refused_on_every_endpoint_that_accepts_one
    """
    ctx = _a_float_pinned_to_a_midday_clock()
    brewer_id = ctx["brewer"]["id"]

    order = _a_second_order_allocated_but_not_dispatched(ctx)
    second_keg = order["allocated_keg_ids"][0]
    fixtures.dispatch_order(order["id"], "2026-08-05T00:00:00Z")
    fills_before = fixtures.read_keg(second_keg)["fill_count"]

    scan = validate_success(
        api_client.scan_keg(
            second_keg,
            factories.fill_scan_payload(
                brewer_id, NOON_CLOCK, ctx["brewer"]["brand_code"]
            ),
            make_brewer_headers(brewer_id),
        ),
        201,
    )
    assert scan["fill_charge_net_cents"] == 2200
    keg = fixtures.read_keg(second_keg)
    assert keg["custody_state"] == "FILLED"
    assert keg["fill_count"] == fills_before + 1
    assert keg["dwell_started_at"] == NOON_CLOCK

    float_keg = _a_keg_still_on_the_float(ctx, second_keg)
    center = fixtures.create_service_center(concurrent_cycle_capacity=4)
    cycle = fixtures.create_service_cycle(float_keg, center["id"], NOON_CLOCK)
    assert cycle["stage"] == "RECEIVED"
    assert cycle["received_at"] == NOON_CLOCK
    assert fixtures.read_keg(float_keg)["custody_state"] == "IN_SERVICE"


# ==========================================================================
# Design: Corner/errors/a_loss_assessment_without_any_commodity_index_cannot_be_valued
# ==========================================================================


def _a_filled_keg_with_no_posted_stainless_price():
    """A fill posted against a pool whose commodity series was never seeded, so
    the keg carries a zero scrap value it cannot be assessed against."""
    return fixtures.setup_filled_keg(
        scanned_at="2026-08-01T12:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=1,
        float_size_kegs=2,
        keg_count=2,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_TWO,
        effective_date="2026-08-01",
        clock=CLOCK,
        with_index=False,
    )


def test_a_missing_price_series_stops_the_assessment_but_not_the_fill():
    """Keg import and filling tolerate an empty index series, and only the
    assessment refuses — leaving the keg unflagged and its version intact.

    PRD: "At import time, if no index row is effective on or before the current
    logical date, the keg is still imported and its
    `stainless_scrap_value_cents` simply stays 0 until an index row becomes
    effective; only opening a loss assessment refuses outright in that
    situation."

    PRD: "A commodity index row effective on or before the valuation date must
    also exist, otherwise the scrap credit cannot be valued and the request is
    refused with `ERR_NO_COMMODITY_INDEX` — unlike keg import, which tolerates
    a missing index."

    PRD: "The `created_by_user_id` is stamped with the acting `X-User-ID`, the
    assessment opens in `assessment_status` `PROPOSED` with `chargeback_status`
    `NONE`, the keg's `assessment_open` flag is raised, and
    `dwell_days_at_assessment` records the keg's dwell at creation, taken from
    whichever clock is open — the brewer clock when both are."

    Design: Corner/errors/a_loss_assessment_without_any_commodity_index_cannot_be_valued
    """
    ctx = _a_filled_keg_with_no_posted_stainless_price()
    keg_id = ctx["keg_id"]
    _, index_meta = validate_paginated(api_client.list_commodity_index(OPERATOR))
    assert index_meta["total_count"] == 0

    keg = fixtures.read_keg(keg_id)
    assert keg["custody_state"] == "FILLED"
    assert keg["stainless_scrap_value_cents"] == 0
    assert fixtures.read_agreement(ctx["agreement"]["id"])["billed_amount_cents"] == 2200
    version_before = keg["version"]

    validate_error(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id,
                "DAMAGED_BEYOND_REPAIR",
                version_before,
                assessment_basis="REPLACEMENT_COST",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_NO_COMMODITY_INDEX,
        422,
    )

    after = fixtures.read_keg(keg_id)
    assert after["assessment_open"] is False
    assert after["version"] == version_before
    _, meta = validate_paginated(
        api_client.list_loss_assessments(ANALYST, params={"keg_id": keg_id})
    )
    assert meta["total_count"] == 0


def test_posting_the_price_lets_the_identical_assessment_through():
    """Once a row is effective the very same body is accepted, and the scrap
    credit it pins is the one the keg read now reports.

    PRD: "Each keg also carries a `stainless_scrap_value_cents` figure, which is
    what the shell would fetch as scrap."

    PRD: "It is the pool's `stainless_weight_kg` multiplied by the stainless
    price in force, multiplied by a recovery factor of 65 percent, rounded half
    up to whole cents."

    PRD: "Under **`REPLACEMENT_COST`**, `gross_value_cents` is simply the pool's
    `replacement_cost_cents`, and `fill_count` is ignored entirely."

    PRD: "`scrap_credit_cents` takes the keg's `stainless_scrap_value_cents`
    only when the `cause` is `DAMAGED_BEYOND_REPAIR`, because only then is the
    shell physically in hand; `LOST_IN_TRADE`, `NOT_RETURNED_DWELL` and
    `STOLEN_SUSPECTED` all credit 0 even though the keg has a scrap value on
    paper, since nobody can weigh in a keg they cannot find."

    PRD: "The valuation is **pinned at creation and never recomputed**, which is
    why the `commodity_index_id` in force is stored on the row: a later index
    posting cannot re-price a standing assessment, and resolving one does not
    re-run the arithmetic."

    Design: Corner/errors/a_loss_assessment_without_any_commodity_index_cannot_be_valued
    """
    ctx = _a_filled_keg_with_no_posted_stainless_price()
    keg_id = ctx["keg_id"]
    version_before = fixtures.keg_version(keg_id)
    index = fixtures.post_index("2026-07-01", 480)
    assert fixtures.read_keg(keg_id)["stainless_scrap_value_cents"] == 3900

    assessment = validate_success(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id,
                "DAMAGED_BEYOND_REPAIR",
                version_before,
                assessment_basis="REPLACEMENT_COST",
            ),
            ANALYST,
        ),
        201,
    )
    assert assessment["commodity_index_id"] == index["id"]
    assert assessment["gross_value_cents"] == 23500
    assert assessment["scrap_credit_cents"] == 3900
    assert assessment["assessed_value_cents"] == 19600
    assert assessment["brewer_liability_pct_bp"] == 10000
    assert assessment["net_chargeback_cents"] == 19600
    assert assessment["assessment_status"] == "PROPOSED"
    assert assessment["chargeback_status"] == "NONE"

    keg = fixtures.read_keg(keg_id)
    assert keg["assessment_open"] is True
    assert keg["custody_state"] == "FILLED"
